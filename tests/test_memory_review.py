"""Review health must distinguish completed paperwork from sufficient evidence."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import codex_evolution


class MemoryReviewTests(unittest.TestCase):
    def test_insufficient_review_is_not_reported_as_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = {'required_checks': codex_evolution.CHECKS}
            packet['packet_id'] = hashlib.sha256(json.dumps(
                packet, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            result = {'reviewer': 'gpt_session', 'packet_id': packet['packet_id'],
                      'checks': [{'id': key, 'status': 'insufficient_data',
                                  'detail': 'There is no verified outcome evidence for this check.'}
                                 for key in codex_evolution.CHECKS]}
            p, r = root/'packet.json', root/'result.json'
            p.write_text(json.dumps(packet))
            r.write_text(json.dumps(result))
            codex_evolution.complete(root, p, r)
            health = json.loads((root/'skill-evolution/review-health.json').read_text())
            self.assertEqual(health['status'], 'reviewed_with_insufficient_data')
            self.assertEqual(set(health['insufficient_ids']), set(codex_evolution.CHECKS))
            self.assertEqual(health['findings_count'], 0)

    def test_prepare_includes_observations_without_creating_experience_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_path = codex_evolution.prepare(root/'memory', root/'codex')
            packet = json.loads(packet_path.read_text())
            self.assertEqual(packet['memory_experience']['active_memories'], 0)
            self.assertEqual(packet['memory_experience']['accepted_tasks'], 0)
            self.assertFalse((root/'memory/.index/experiences.sqlite3').exists())
            digest = packet.pop('packet_id')
            self.assertEqual(digest, hashlib.sha256(json.dumps(
                packet, sort_keys=True, ensure_ascii=False).encode()).hexdigest())


if __name__ == '__main__':
    unittest.main()
