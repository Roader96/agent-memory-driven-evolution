"""Isolated standalone integration: no real HOME, schedules, models or memories."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import install_codex_recall


class TestMemoryIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="memory integration ")
        self.home = Path(self.tmp.name) / "home"
        self.codex = self.home / "codex sessions"
        self.memory = self.home / "local memories"
        self.codex.mkdir(parents=True)
        self.instructions = self.codex / "AGENTS.md"
        self.instructions.write_text("# User rules\nKeep the manual project policy.\n", encoding="utf-8")
        self.env = dict(os.environ, HOME=str(self.home), CODEX_HOME=str(self.codex),
                        CODEX_MEMORY_HOME=str(self.memory), PYTHON_BIN=sys.executable)

    def tearDown(self):
        self.tmp.cleanup()

    def run_command(self, args):
        result = subprocess.run(args, cwd=ROOT, env=self.env, text=True,
                                capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-5000:])
        return result

    def install(self):
        return self.run_command(["bash", str(ROOT / "install_codex_memory.sh"), "--yes", "--no-cron",
                                 "--memory-home", str(self.memory), "--codex-home", str(self.codex)])

    def test_standalone_reinstall_preserves_rules_and_has_no_schedule_or_model_dependency(self):
        self.install()
        worker = self.memory / "bin/codex_experience.py"
        self.assertTrue(worker.is_file())
        self.assertEqual(worker.read_bytes(), (ROOT / "scripts/codex_experience.py").read_bytes())
        stats = self.run_command([sys.executable, str(worker), "stats", "--memory-home", str(self.memory)])
        self.assertIsInstance(json.loads(stats.stdout), dict)
        self.assertFalse((self.memory / ".index/experiences.sqlite3").exists(),
                         "read-only stats must not create a memory ledger")
        self.assertFalse((self.memory / ".runtime").exists())
        self.assertFalse((self.home / "Library/LaunchAgents").exists())
        self.assertFalse((self.home / ".hermes").exists())
        self.assertTrue((self.memory / ".index/sessions.jsonl").is_file())

        first = self.instructions.read_text(encoding="utf-8")
        # A user may add instructions after installation; updating the managed
        # block must preserve both the old policy and the new content.
        self.instructions.write_text(first + "\nNew manual policy after installation.\n", encoding="utf-8")
        self.install()
        second = self.instructions.read_text(encoding="utf-8")
        self.assertIn("Keep the manual project policy.", second)
        self.assertIn("New manual policy after installation.", second)
        self.assertEqual(second.count(install_codex_recall.START), 1)
        self.assertIn("receipt_id", second)
        self.assertIn("Applied IDs must come from that receipt", second)
        self.assertIn("Use unknown", second)

    def test_corrupt_managed_block_is_not_overwritten(self):
        original = "Manual policy\n" + install_codex_recall.START + "\nmissing end marker\n"
        self.instructions.write_text(original, encoding="utf-8")
        with self.assertRaises(ValueError):
            install_codex_recall.install(self.codex, self.memory)
        self.assertEqual(self.instructions.read_text(encoding="utf-8"), original)

    def test_optional_stats_failure_does_not_invalidate_archive(self):
        self.install()
        worker = self.memory / "bin/codex_experience.py"
        worker.write_text("raise SystemExit(7)\n", encoding="utf-8")
        self.run_command(["bash", str(self.memory / "run_maintenance.sh")])
        log = (self.memory / "maintenance.log").read_text(encoding="utf-8")
        self.assertIn("WARN experience statistics unavailable", log)
        self.assertIn("OK codex structured memory maintenance", log)
        self.assertTrue((self.memory / "INDEX.md").is_file())
        self.assertTrue((self.memory / ".index/sessions.jsonl").is_file())

    def test_installed_experience_loop_and_reinstall_preserve_observations(self):
        self.install()
        worker = self.memory / "bin/codex_experience.py"
        source = self.memory / "manual-evidence.md"
        source.write_text("Test email navigation in the target client first.\n", encoding="utf-8")
        experience = {"memory_id": "mem-example", "task_family": "email-newsletter",
                      "scope": "example-project", "conditions": "HTML email navigation",
                      "recommended_action": "Test email navigation in the target client first.",
                      "avoid": "Assuming browser preview is sufficient.",
                      "evidence_level": "user_explicit", "status": "active",
                      "evidence_refs": [{"path": str(source),
                                         "quote": "Test email navigation in the target client first."}]}
        input_file = self.memory / "experience-input.json"
        input_file.write_text(json.dumps(experience), encoding="utf-8")
        self.run_command([sys.executable, str(worker), "remember", "--memory-home", str(self.memory),
                          "--input", str(input_file)])
        result = self.run_command([sys.executable, str(worker), "brief", "--memory-home", str(self.memory),
                                   "--query", "email navigation", "--family", "email-newsletter",
                                   "--project", "example-project", "--task-id", "isolated-task"])
        brief = json.loads(result.stdout)
        self.assertIn("mem-example", brief["retrieved_ids"])
        feedback = {"receipt_id": brief["receipt_id"], "task_id": "isolated-task",
                    "applied_memory_ids": ["mem-example"], "outcome_status": "unknown",
                    "observed_actions": ["Tested navigation before generating the full email."],
                    "user_corrections": [], "evidence_refs": []}
        input_file.write_text(json.dumps(feedback), encoding="utf-8")
        self.run_command([sys.executable, str(worker), "feedback", "--memory-home", str(self.memory),
                          "--input", str(input_file)])
        before = json.loads(self.run_command([sys.executable, str(worker), "stats",
                                              "--memory-home", str(self.memory)]).stdout)
        self.assertEqual(before["accepted_tasks"], 0)
        self.assertEqual(before["applied_tasks"], 1)
        self.install()
        after = json.loads(self.run_command([sys.executable, str(worker), "stats",
                                             "--memory-home", str(self.memory)]).stdout)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
