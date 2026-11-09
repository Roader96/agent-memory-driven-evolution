"""Isolated evidence, retrieval and use-feedback tests; no model or real vault."""
from __future__ import annotations
import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
import codex_experience as exp


class TestExperience(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root/"memory"
        self.source = self.root/"verified.txt"
        self.source.write_text("User correction: preserve history.\nVerified retrieval regression passed.\nTask failed: wrong project.\n", encoding="utf-8")
        self.record = {"task_family": "memory-retrieval", "scope": "Project-A",
                       "conditions": "When recalling historical memory",
                       "recommended_action": "Preserve history and cite the original source",
                       "avoid": "Do not trust an unverified claim", "evidence_level": "user_explicit",
                       "evidence_refs": [{"path": str(self.source), "quote": "User correction: preserve history."}]}

    def tearDown(self):
        self.temp.cleanup()

    def remember(self, **changes):
        return exp.remember(self.home, {**self.record, **changes})

    def brief(self, **changes):
        args = dict(query="historical memory", family="memory-retrieval", project="Project-A", task_id="task-1")
        args.update(changes)
        return exp.brief(self.home, **args)

    def feedback(self, **changes):
        payload = {"task_id": "task-1", "outcome_status": "unknown", "applied_memory_ids": [],
                   "observed_actions": [], "user_corrections": [], "evidence_refs": []}
        return exp.feedback(self.home, {**payload, **changes})

    def test_read_only_load_and_stats_do_not_create_storage(self):
        self.assertEqual(exp.load_experiences(self.home), [])
        self.assertEqual(exp.stats(self.home)["retrieval_receipts"], 0)
        self.assertFalse(self.home.exists())

    def test_failed_first_transaction_leaves_readable_empty_state(self):
        with self.assertRaises(ValueError): self.remember(expected_revision=99)
        self.assertEqual(exp.load_experiences(self.home), [])
        self.assertEqual(exp.stats(self.home)["active_memories"], 0)

    def test_identical_records_deduplicate_with_and_without_explicit_identity(self):
        first = self.remember()
        self.assertEqual(first, self.remember())
        self.assertEqual(first, self.remember(memory_id=first["memory_id"]))
        self.assertEqual(len(exp.load_experiences(self.home)), 1)
        with sqlite3.connect(str(exp._path(self.home))) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM versions").fetchone()[0], 1)

    def test_duplicate_source_is_not_independent_corroboration(self):
        r = self.remember(evidence_refs=self.record["evidence_refs"] * 5)
        self.assertEqual(len(r["evidence_refs"]), 1)
        self.assertEqual(r["source_count"], 1)

    def test_missing_or_mismatched_sources_are_rejected_without_a_database(self):
        for refs in ([], [{"path":str(self.root/"missing"),"quote":"anything"}],
                     [{"path":str(self.source),"quote":"fabricated success"}],
                     [{"path":str(self.source),"quote":""}]):
            with self.assertRaises(ValueError):
                self.remember(evidence_refs=refs)
        self.assertFalse(self.home.exists())

    def test_unverified_records_remain_candidates_and_cannot_be_activated(self):
        r = self.remember(evidence_level="unverified")
        self.assertEqual(r["status"], "candidate")
        self.assertEqual(exp.load_experiences(self.home), [])
        self.assertEqual(len(exp.load_experiences(self.home, include_candidates=True)), 1)
        self.assertEqual(self.brief()["retrieved_ids"], [])
        with self.assertRaises(ValueError):
            self.remember(evidence_level="unverified", status="active")

    def test_scope_and_family_cannot_bypass_project_boundaries(self):
        local = self.remember()
        global_item = self.remember(scope="global")
        ids = self.brief()["retrieved_ids"]
        self.assertEqual(set(ids), {local["memory_id"], global_item["memory_id"]})
        self.assertEqual(self.brief(project="Project-B")["retrieved_ids"], [global_item["memory_id"]])
        self.assertEqual(self.brief(project="")["retrieved_ids"], [global_item["memory_id"]])
        self.assertEqual(self.brief(family="different-family")["retrieved_ids"], [])

    def test_unrelated_queries_and_project_only_requests_do_not_recall(self):
        self.remember()
        self.assertEqual(self.brief(query="banana-fertilizer")["retrieved_ids"], [])
        self.assertEqual(self.brief(query="", family="")["retrieved_ids"], [])

    def test_chinese_query_is_relevant_without_spaces(self):
        r = self.remember(conditions="历史记忆召回失败", recommended_action="检索对应项目并核对原始证据")
        self.assertEqual(self.brief(query="记忆召回")["retrieved_ids"], [r["memory_id"]])

    def test_empty_retrieval_still_creates_receipt_not_adoption(self):
        receipt = self.brief()
        self.assertEqual(receipt["retrieved_ids"], [])
        self.assertEqual(receipt["adoption"], "not_observed")
        stats = exp.stats(self.home)
        self.assertEqual(stats["retrieval_receipts"], 1)
        self.assertEqual(stats["applied_tasks"], 0)
        self.assertEqual(stats["accepted_tasks"], 0)

    def test_budget_never_truncates_into_misleading_partial_advice(self):
        self.remember()
        receipt = self.brief(max_chars=12)
        self.assertLessEqual(len(receipt["text"]), 12)
        self.assertEqual(receipt["retrieved_ids"], [])

    def test_lost_or_changed_evidence_is_warned_and_not_used(self):
        memory=self.remember()
        for replacement in ("The quotation has disappeared.", None):
            if replacement is None: self.source.unlink()
            else: self.source.write_text(replacement,encoding="utf-8")
            receipt=self.brief()
            self.assertEqual(receipt["retrieved_ids"],[])
            self.assertEqual(receipt["evidence_warnings"][0]["memory_id"],memory["memory_id"])
            self.assertEqual(exp.load_experiences(self.home)[0]["status"],"active")

    def test_revision_requires_parent_and_preserves_history(self):
        first = self.remember(memory_id="memory-1")
        with self.assertRaises(ValueError):
            self.remember(memory_id="memory-1", recommended_action="New action")
        second = self.remember(memory_id="memory-1", expected_revision=1, recommended_action="New action")
        self.assertEqual(second["revision"], 2)
        self.assertEqual(second["parent_revision"], 1)
        # Same mutation retried with the original parent is idempotent.
        self.assertEqual(second, self.remember(memory_id="memory-1", expected_revision=1, recommended_action="New action"))
        with self.assertRaises(ValueError):
            self.remember(memory_id="memory-1", expected_revision=1, recommended_action="Stale divergent action")
        with sqlite3.connect(str(exp._path(self.home))) as conn:
            records = [json.loads(r[0]) for r in conn.execute("SELECT record FROM versions ORDER BY revision")]
        self.assertEqual(records, [first, second])

    def test_simultaneous_stale_writers_cannot_overwrite_each_other(self):
        self.remember(memory_id="concurrent")
        def update(n):
            try:
                self.remember(memory_id="concurrent", expected_revision=1, recommended_action="Action " + str(n))
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(update, range(6)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(exp.load_experiences(self.home)[0]["revision"], 2)

    def test_concurrent_duplicate_intake_creates_one_memory(self):
        with ThreadPoolExecutor(max_workers=5) as pool:
            result = list(pool.map(lambda _: self.remember(), range(5)))
        self.assertEqual(len({r["memory_id"] for r in result}), 1)
        self.assertEqual(len(exp.load_experiences(self.home)), 1)

    def test_supersede_requires_current_parent_and_preserves_source(self):
        first = self.remember(memory_id="old")
        with self.assertRaises(ValueError):
            self.remember(memory_id="replacement", supersedes={"memory_id":"old", "revision":99})
        replacement = self.remember(memory_id="replacement", recommended_action="Updated historical memory action",
                                    supersedes={"memory_id":"old", "revision":1})
        self.assertEqual([r["memory_id"] for r in exp.load_experiences(self.home)], ["replacement"])
        with sqlite3.connect(str(exp._path(self.home))) as conn:
            old = json.loads(conn.execute("SELECT record FROM versions WHERE memory_id='old' AND revision=2").fetchone()[0])
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(old["evidence_refs"], first["evidence_refs"])
        self.assertTrue(self.source.exists())
        self.assertEqual(replacement["supersedes"]["revision"], 1)

    def test_success_requires_actual_matching_source_and_receipt(self):
        self.remember()
        self.brief()
        with self.assertRaises(ValueError): self.feedback(outcome_status="verified_success")
        with self.assertRaises(ValueError): self.feedback(outcome_status="failed")
        with self.assertRaises(ValueError): self.feedback(outcome_status="user_accepted")
        refs=[{"path":str(self.source),"quote":"Verified retrieval regression passed."}]
        with self.assertRaises(ValueError): self.feedback(task_id="unknown-task",outcome_status="verified_success",evidence_refs=refs)
        result=self.feedback(outcome_status="verified_success",evidence_refs=refs)
        self.assertEqual(result["outcome_status"], "verified_success")

    def test_unretrieved_id_and_receipt_from_other_task_are_refused(self):
        r=self.remember();receipt=self.brief()
        with self.assertRaises(ValueError):
            self.feedback(applied_memory_ids=["forged"],observed_actions=["Claimed to use it"])
        with self.assertRaises(ValueError):
            self.feedback(task_id="different-task",receipt_id=receipt["receipt_id"],applied_memory_ids=[r["memory_id"]],observed_actions=["Used it"])
        with self.assertRaises(ValueError): self.feedback(applied_memory_ids=[r["memory_id"]])

    def test_retrieval_is_not_actual_adoption_and_unknown_is_not_success(self):
        r=self.remember();self.brief()
        self.assertEqual(exp.stats(self.home)["applied_tasks"],0)
        result=self.feedback(applied_memory_ids=[r["memory_id"]],observed_actions=["Read the historical source"])
        self.assertEqual(result["outcome_status"],"unknown")
        stats=exp.stats(self.home)
        self.assertEqual(stats["applied_tasks"],1)
        self.assertEqual(stats["accepted_tasks"],0)
        self.assertEqual(stats["outcome_task_counts"]["unknown"],1)
        self.assertEqual(stats["outcome_task_counts"]["verified_success"],0)

    def test_feedback_is_idempotent_and_retains_earlier_observations(self):
        r=self.remember();self.brief()
        kwargs=dict(applied_memory_ids=[r["memory_id"]],observed_actions=["Cited source"])
        self.assertFalse(self.feedback(**kwargs)["duplicate"])
        self.assertTrue(self.feedback(**kwargs)["duplicate"])
        self.assertEqual(exp.stats(self.home)["feedback_observations"],1)
        self.feedback(**kwargs,outcome_status="failed",evidence_refs=[{"path":str(self.source),"quote":"Task failed: wrong project."}])
        stats=exp.stats(self.home)
        self.assertEqual(stats["feedback_observations"],2)
        self.assertEqual(stats["applied_memory_uses"],1)
        self.assertEqual(stats["outcome_task_counts"]["unknown"],1)
        self.assertEqual(stats["outcome_task_counts"]["failed"],1)

    def test_feedback_frozen_revision_survives_memory_change(self):
        first=self.remember(memory_id="changing")
        receipt=self.brief()
        self.remember(memory_id="changing",expected_revision=1,recommended_action="New behavior")
        out=self.feedback(receipt_id=receipt["receipt_id"],applied_memory_ids=[first["memory_id"]],observed_actions=["Used previous advice"])
        self.assertEqual(out["revisions"], {"changing":1})
        self.assertEqual(out["applied_snapshots"]["changing"]["recommended_action"],first["recommended_action"])
        self.assertEqual(receipt["snapshots"]["changing"]["evidence_refs"],first["evidence_refs"])

    def test_feedback_is_returned_to_later_recall_without_automatic_promotion(self):
        memory=self.remember(memory_id="feedback-memory");self.brief()
        self.feedback(applied_memory_ids=[memory["memory_id"]],observed_actions=["Read old source"],
                      user_corrections=["preserve history."],
                      evidence_refs=[{"path":str(self.source),"quote":"User correction: preserve history."}])
        self.feedback(applied_memory_ids=[memory["memory_id"]],observed_actions=["Applied source"],
                      outcome_status="failed",evidence_refs=[{"path":str(self.source),"quote":"Task failed: wrong project."}])
        receipt=self.brief(task_id="task-2")
        observation=receipt["retrieved"][0]["use_observations"]
        self.assertEqual(observation["applied_tasks"],1)
        self.assertEqual(observation["outcome_observations"]["unknown"],1)
        self.assertEqual(observation["outcome_observations"]["failed"],1)
        self.assertIn("preserve history.",receipt["text"])
        self.assertIn("not causal",receipt["text"])
        self.assertEqual(exp.load_experiences(self.home)[0]["revision"],1)
        self.remember(memory_id="feedback-memory",expected_revision=1,recommended_action="Revised memory advice")
        self.assertEqual(self.brief(task_id="task-3")["retrieved"][0]["use_observations"]["applied_tasks"],0)

    def test_user_correction_requires_a_matching_source_even_when_outcome_unknown(self):
        self.remember();self.brief()
        with self.assertRaises(ValueError):
            self.feedback(user_corrections=["Invented correction"])
        with self.assertRaises(ValueError):
            self.feedback(user_corrections=["Invented correction"],
                          evidence_refs=[{"path":str(self.source),"quote":"User correction: preserve history."}])
        self.assertEqual(exp.stats(self.home)["feedback_observations"],0)

    def test_later_failed_observation_is_not_counted_as_current_acceptance(self):
        self.remember();self.brief()
        self.feedback(outcome_status="user_accepted",evidence_refs=[
            {"path":str(self.source),"quote":"Verified retrieval regression passed."}])
        self.feedback(outcome_status="failed",evidence_refs=[
            {"path":str(self.source),"quote":"Task failed: wrong project."}])
        observed=exp.stats(self.home)
        self.assertEqual(observed["ever_accepted_tasks"],1)
        self.assertEqual(observed["latest_accepted_tasks"],0)
        self.assertEqual(observed["latest_outcome_task_counts"]["failed"],1)

    def test_brief_cli_full_is_opt_in_and_text_obeys_budget(self):
        self.remember()
        def run(extra):
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                code=exp.main(["brief","--query","historical memory","--project","Project-A",
                               "--task-id","cli-task","--memory-home",str(self.home),"--max-chars","1500"]+extra)
            self.assertEqual(code,0)
            return json.loads(output.getvalue())
        small=run([])
        self.assertTrue(small["retrieved_ids"])
        self.assertNotIn("snapshots",small)
        self.assertNotIn("retrieved",small)
        self.assertLessEqual(len(small["text"]),1500)
        self.assertIn("snapshots",run(["--full"]))

    def test_private_file_and_json_cli(self):
        input_file=self.root/"input.json";input_file.write_text(json.dumps(self.record),encoding="utf-8")
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            code=exp.main(["remember","--input",str(input_file),"--memory-home",str(self.home)])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(output.getvalue())["revision"],1)
        self.assertEqual(os.stat(exp._path(self.home)).st_mode & 0o777,0o600)


if __name__ == "__main__":
    unittest.main()
