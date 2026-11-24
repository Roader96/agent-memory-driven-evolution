"""Compressed session regressions, isolated from real archives."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_codex_memory import meta, message, DONE_ID
import codex_memory as m


@unittest.skipUnless(shutil.which('zstd'), 'zstd executable unavailable')
class CompressedSessions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / 'codex'
        self.source = self.home / 'sessions' / 'rollout-test.jsonl'
        self.source.parent.mkdir(parents=True)
        records = [meta(DONE_ID), message(DONE_ID, 'user-1', 'user', '请保留压缩会话的任务证据')]
        self.source.write_text(''.join(json.dumps(r) + '\n' for r in records))
        self.compressed = self.source.with_suffix('.jsonl.zst')
        subprocess.run(['zstd', '-q', str(self.source), '-o', str(self.compressed)], check=True)

    def test_compressed_only_preserves_session_and_original(self):
        before = self.compressed.read_bytes()
        self.source.unlink()
        sessions = m.load_sessions(self.home, {})
        self.assertEqual(len(sessions[DONE_ID].messages), 1)
        self.assertEqual(self.compressed.read_bytes(), before)
        self.assertIn('.jsonl.zst', next(iter(sessions[DONE_ID].source_files)))

    def test_plain_and_compressed_and_archived_copies_deduplicate(self):
        archived = self.home / 'archived_sessions'
        archived.mkdir()
        shutil.copy2(self.compressed, archived / self.compressed.name)
        sessions = m.load_sessions(self.home, {})
        self.assertEqual(len(sessions), 1)
        self.assertEqual(len(sessions[DONE_ID].messages), 1)

    def test_corruption_aborts_before_replacing_archive(self):
        memory = self.root / 'memory'
        m.build(memory, self.home)
        index = memory / '.index/sessions.jsonl'
        before = index.read_bytes()
        self.compressed.write_bytes(b'corrupt compressed source')
        with self.assertRaises(ValueError):
            m.build(memory, self.home)
        self.assertEqual(index.read_bytes(), before)

    def test_restricted_scheduler_path_can_use_installed_decoder(self):
        with patch.dict(os.environ, {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}):
            self.assertIn(DONE_ID, m.load_sessions(self.home, {}))

    def test_missing_decoder_fails_visibly(self):
        with patch.object(m.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'requires the zstd'):
                m.load_sessions(self.home, {})

    def test_fallback_identity_matches_extensions(self):
        self.assertEqual(m.session_id_from_path(Path('sample.jsonl')),
                         m.session_id_from_path(Path('sample.jsonl.zst')))
