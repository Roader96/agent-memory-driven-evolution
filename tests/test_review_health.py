"""Isolated regressions for review coverage, degradation and honest outcomes."""
import copy
import json
import sys
import tempfile
import unittest
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/skill_evolution"))
import librarian
import followup


def evidence():
    return {"date": "2026-10-16", "error_clusters": [{"title": "重复失败", "count": 4}],
            "failed_sessions": [{"confidence": "high", "title": "失败会话"}],
            "followup_summary": {"worse_items": [], "review_items": ["P1:累计计数增加"]}}


def report(ids="C1 F1 W1"):
    return "## 技能提案\n## 证据覆盖\n" + ids + "：已有提案覆盖，等待执行和可比窗口复核。" * 12


class TestReviewHealth(unittest.TestCase):
    def test_batch_hermes_review_disables_tools_and_bounds_turns(self):
        adapter = librarian.agent_adapter
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'hermes'
            binary.touch()
            with patch.object(adapter, 'hermes_bin', return_value=str(binary)), \
                 patch.object(adapter.subprocess, 'run', return_value=SimpleNamespace(
                     returncode=0, stdout='review result', stderr='')) as run:
                self.assertEqual(adapter._llm_hermes('evidence', source='test', timeout=1,
                                                    query_file=True), 'review result')
            argv = run.call_args.args[0]
            self.assertEqual(argv[argv.index('--toolsets') + 1], '')
            self.assertEqual(argv[argv.index('--max-turns') + 1], '1')
            self.assertEqual(argv[argv.index('--source') + 1], 'tool')
            self.assertFalse(Path(argv[argv.index('--query-file') + 1]).exists())

    def test_monitor_reports_degradation_even_when_job_exited_successfully(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            vault = home / 'vault'
            (vault / 'daily').mkdir(parents=True)
            (vault / '.checkpoints').mkdir()
            for days in (1, 2, 3):
                day = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
                (vault / 'daily' / f'{day}-每日总结.md').write_text('real summary')
            hp = vault / '.checkpoints/evolution-health.json'
            hp.write_text(json.dumps({'checked_at': datetime.now().isoformat(),
                                      'status': 'degraded', 'reason': 'missing_coverage:C1'}))
            log = home / 'monitor.log'
            env = {**os.environ, 'HOME': str(home), 'HERMES_VAULT': str(vault),
                   'WATCHDOG_MONITOR_LOG': str(log), 'WATCHDOG_SILENT': '1'}
            subprocess.run(['bash', str(root / 'scripts/watchdog_monitor.sh')], env=env, check=True)
            self.assertIn('weekly审查降级:missing_coverage:C1', log.read_text())
            self.assertNotIn('all chains healthy', log.read_text())

    def test_budget_keeps_valid_json_and_all_required_evidence(self):
        ev = evidence()
        ev["error_clusters"] = [{"title": "错误" * 2000, "count": 4} for _ in range(10)]
        ev["done"] = ["过去的目标" * 2000] * 300
        prepared = librarian.prepare_evidence(ev)
        encoded = librarian.evidence_json(prepared)
        decoded = json.loads(encoded)
        self.assertLessEqual(len(encoded), 12000)
        self.assertEqual(decoded["required_coverage"], [f"C{i}" for i in range(1, 11)] + ["F1", "W1"])
        self.assertEqual(len(decoded["error_clusters"]), 10)

    def run_review(self, outputs):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(librarian, "VAULT", Path(tmp)), \
             patch.object(librarian, "gather_evidence", return_value=evidence()), \
             patch.object(librarian, "call_llm", side_effect=outputs) as call, \
             patch.object(librarian.state, "load", return_value={"proposals": []}), \
             patch.object(librarian.state, "add_proposal") as add, \
             patch.object(librarian.agent_adapter, "_log_llm_failure") as log, \
             patch.object(librarian.agent_adapter, "last_llm_failure", return_value=""), \
             patch.dict("os.environ", {"LIBRARIAN_STANDALONE": "0"}):
            result = librarian.main()
            health = json.loads((Path(tmp) / ".checkpoints/evolution-health.json").read_text())
            text = (Path(tmp) / "skill-evolution/2026-10-16-skill-evolution-weekly.md").read_text()
            return result, health, text, call.call_count, add.call_count, log.call_count

    def test_missing_coverage_gets_one_content_retry(self):
        ok, health, _, calls, adds, logs = self.run_review([report("C1 F1"), report()])
        self.assertTrue(ok)
        self.assertEqual(health["status"], "ok")
        self.assertEqual((calls, adds, logs), (2, 0, 0))

    def test_failed_repair_records_exact_reason_without_enqueuing(self):
        ok, health, text, calls, adds, logs = self.run_review([report("C1"), report("C1")])
        self.assertFalse(ok)
        self.assertEqual(health["status"], "degraded")
        self.assertIn("missing_coverage:F1,W1", text)
        self.assertEqual((calls, adds, logs), (2, 0, 1))

    def test_transport_failure_is_not_misreported_as_coverage_failure(self):
        ok, health, _, calls, adds, logs = self.run_review([""])
        self.assertFalse(ok)
        self.assertEqual(health["reason"], "empty_or_invalid_output")
        self.assertEqual((calls, adds, logs), (1, 0, 1))

    def test_cumulative_cluster_growth_proves_recurrence_not_worse_rate(self):
        fu = {"proposal_id": "P1", "target": "cron", "metric": "cluster:timeout",
              "baseline": 10, "check_after": "2000-01-01", "result": None}
        doc = {"follow_ups": [fu]}
        with patch.object(followup.state, "load", return_value=doc), patch.object(followup.state, "save"):
            checked = followup.check_due([], [{"title": "timeout", "count": 12}])
            self.assertEqual(checked[0]["result"], "inconclusive")
            self.assertTrue(checked[0]["recurrence_detected"])
            self.assertEqual(len(followup.summary()["review_items"]), 1)

    def test_legacy_counts_are_reinterpreted_without_changing_audit_records(self):
        doc = {"follow_ups": [{"proposal_id": "P1", "target": "cron", "metric": "cluster:timeout",
                               "result": "worse", "result_detail": "baseline=11 现在=20"}]}
        before = copy.deepcopy(doc)
        with patch.object(followup.state, "load", return_value=doc):
            summary = followup.summary()
        self.assertEqual((summary["worse"], summary["inconclusive"]), (0, 1))
        self.assertEqual(len(summary["review_items"]), 1)
        self.assertEqual(doc, before)


if __name__ == "__main__":
    unittest.main()
