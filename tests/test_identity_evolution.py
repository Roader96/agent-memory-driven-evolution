"""Regression coverage for production failure states, never the operator's ledger."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/skill_evolution'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import state
import approve
import approvals
import canonicalize
import curator
import reconcile
import health_alert
import codex_evolution
import install_codex_recall


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [patch.object(state, 'DIR', self.root),
                        patch.object(state, 'STATE_FILE', self.root/'state.json'),
                        patch.object(state, 'LOCK_FILE', self.root/'state.lock'),
                        patch.object(approvals, 'APPROVALS', self.root/'APPROVALS.md'),
                        patch.object(approvals, 'LOG', self.root/'APPROVALS.log')]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def add(self, target='new'):
        p = {'kind':'enhance', 'target':target, 'reason':'real evidence'}
        state.add_proposal(p)
        return p

    def test_noncontiguous_ids_use_maximum(self):
        state.save({**state.empty_state(), 'proposals':[
            {'id':'P001', 'uid':'stable-1', 'kind':'enhance', 'target':'a', 'status':'done'},
            {'id':'P003', 'uid':'stable-3', 'kind':'enhance', 'target':'b', 'status':'done'}]})
        p = self.add()
        self.assertEqual(p['id'], 'P004')
        self.assertTrue(p['uid'])

    def test_concurrent_proposals_do_not_overwrite_each_other(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda n:self.add(f'skill-{n}'), range(12)))
        d = state.load()
        self.assertEqual(len(d['proposals']), 12)
        self.assertEqual(len({p['id'] for p in d['proposals']}), 12)
        self.assertEqual(len({p['uid'] for p in d['proposals']}), 12)

    def test_pending_budget_is_enforced_before_insertion(self):
        for n in range(15): self.add(f'skill-{n}')
        self.assertEqual(len(state.list_pending()), state.MAX_PENDING)

    def test_corrupt_ledger_never_returns_empty_or_overwrites(self):
        state.STATE_FILE.write_text('{broken')
        for call in (state.load, lambda:state.update(lambda d:d.clear())):
            with self.assertRaises(ValueError): call()
        self.assertEqual(state.STATE_FILE.read_text(), '{broken')

    def test_stale_legacy_writer_cannot_erase_new_proposals(self):
        self.add('first')
        stale = state.load()
        self.add('second')
        with self.assertRaises(RuntimeError): state.save(stale)
        self.assertEqual(len(state.load()['proposals']),2)

    def test_duplicate_current_ids_are_rejected(self):
        d = {**state.empty_state(), 'proposals':[{'id':'P1'}, {'id':'P1'}]}
        state.STATE_FILE.write_text(json.dumps(d))
        with self.assertRaises(ValueError): approve.cmd_reject('P1')
        self.assertEqual(json.loads(state.STATE_FILE.read_text()), d)

    def test_migration_preserves_history_and_relinks_by_target(self):
        original = {'version':1, 'proposals':[
            {'id':'P054', 'target':'old', 'kind':'enhance', 'status':'done'},
            {'id':'P054', 'target':'current', 'kind':'repair', 'status':'pending'}],
            'follow_ups':[{'proposal_id':'P054', 'target':'old', 'result':'worse'}],
            'approved_changes':[{'id':'P054', 'target':'old', 'kind':'enhance'}]}
        state.STATE_FILE.write_text(json.dumps(original))
        d = state.load()
        self.assertEqual([p['id'] for p in d['proposals']], ['P054','P055'])
        self.assertEqual(d['proposals'][1]['legacy_id'], 'P054')
        self.assertEqual(d['follow_ups'][0]['proposal_uid'], d['proposals'][0]['uid'])
        self.assertEqual(d['follow_ups'][0]['result'], 'worse')
        self.assertEqual(d['approved_changes'][0]['proposal_uid'], d['proposals'][0]['uid'])
        self.assertTrue(state.STATE_FILE.with_suffix('.json.bak-v1').exists())
        self.assertEqual(d, state.load())

    def test_unresolvable_reference_is_quarantined(self):
        state.STATE_FILE.write_text(json.dumps({'version':1,'proposals':[
            {'id':'P1','target':'a','status':'done'}],
            'follow_ups':[{'proposal_id':'P1','target':'wrong','result':'improved'}]}))
        d=state.load();f=d['follow_ups'][0]
        self.assertEqual(f['link_status'],'unresolved')
        self.assertEqual(f['result'],'inconclusive')
        self.assertEqual(f['legacy_result'],'improved')

    def test_target_and_uid_are_both_checked(self):
        p=self.add()
        with self.assertRaises(ValueError): approve.cmd_approve(p['id'],expected_target='wrong')
        with self.assertRaises(ValueError): approve.cmd_approve(p['id'],expected_uid='wrong')
        self.assertEqual(state.load()['proposals'][0]['status'],'pending')

    def test_render_preserves_valid_checked_decisions(self):
        self.add();path=approvals.render()
        path.write_text(path.read_text().replace('- [ ]','- [x]'))
        approvals.render()
        self.assertIn('- [x]',path.read_text())

    def test_stale_checkbox_is_preserved_for_review_and_not_executed(self):
        p=self.add();path=approvals.render()
        path.write_text(path.read_text().replace('- [ ]','- [x]').replace('| new |','| wrong |'))
        with patch.object(approvals,'_run') as run, self.assertRaises(ValueError): approvals.process()
        run.assert_not_called()
        self.assertTrue((self.root/'APPROVALS.review.md').exists())
        self.assertEqual(state.load()['proposals'][0]['status'],'pending')

    def test_legacy_hermes_proposals_are_deferred_without_execution(self):
        self.add()
        changes=reconcile.reconcile([],active_agent='codex')
        self.assertEqual(len(changes),1)
        d=state.load();self.assertEqual(d['proposals'][0]['status'],'deferred')
        self.assertEqual(d['proposals'][0]['status_history'][0]['from'],'pending')


class TestEvidenceAndAlerts(unittest.TestCase):
    def test_recall_install_preserves_user_instructions_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);codex=root/'codex';codex.mkdir()
            p=codex/'AGENTS.md';p.write_text('# User instructions\nAlways verify results.\n')
            install_codex_recall.install(codex,root/'memory')
            once=p.read_text()
            install_codex_recall.install(codex,root/'memory')
            self.assertEqual(p.read_text(),once)
            self.assertIn('Always verify results.',once)
            self.assertEqual(once.count(install_codex_recall.START),1)

    def test_archived_skill_is_not_a_broken_reference(self):
        fact={'name':'old','installed':False,'archived':True,'load_sessions':30,
              'recent_self_errors':4,'self_errors':4}
        self.assertEqual(curator.curate([fact]),[])

    def test_historical_usage_without_recent_failure_is_not_broken(self):
        fact={'name':'old','installed':False,'load_sessions':30,'self_errors':0}
        self.assertEqual(curator.curate([fact]),[])

    def test_failure_window_drops_banners_duplicates_and_derived_index(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);errors=root/'errors.jsonl';learn=root/'review.md'
            errors.write_text('\n'.join(json.dumps(x) for x in [
                {'date':'2099-01-01','what':'Hermes Agent v0.1.0 upstream deadbeef','count':8},
                {'event_id':'e1','date':'2099-01-01','what':'TimeoutError connecting','count':1},
                {'event_id':'e1','date':'2099-01-01','what':'TimeoutError connecting','count':1},
                {'date':'2000-01-01','what':'old failure','count':20}]))
            learn.write_text('- TimeoutError connecting (99次)')
            note=root/'2026-09-14-看门狗故障修复.md';note.write_text('## 摘要\n\n真实事件说明\n')
            with patch.object(canonicalize,'ERRORS_JSONL',str(errors)), \
                 patch.object(canonicalize,'INCIDENTS_GLOB',str(root/'*修复.md')), \
                 patch.object(canonicalize,'LEARNINGS_REVIEW',str(learn)):
                entries=canonicalize.load_all_failures(days=30)
                self.assertEqual(len(entries),1)
                self.assertEqual(entries[0]['count'],1)
                all_entries=canonicalize.load_all_failures()
                self.assertNotIn('摘要',[x['text'] for x in all_entries])
                self.assertTrue(any('看门狗' in x['text'] for x in all_entries))

    def test_failed_alert_remains_retryable_and_success_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'alert.json'
            self.assertTrue(health_alert.plan(p,'failure',now=10000))
            health_alert.ack(p,False)
            self.assertFalse(health_alert.plan(p,'failure',now=10001))
            self.assertTrue(health_alert.plan(p,'failure',now=14000))
            health_alert.ack(p,True)
            self.assertFalse(health_alert.plan(p,'failure',now=20000))
            self.assertTrue(health_alert.plan(p,'different failure',now=20001))

    def test_gpt_review_cannot_skip_checks_or_use_modified_evidence(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);packet={'required_checks':codex_evolution.CHECKS,'created_at':'test'}
            import hashlib
            packet['packet_id']=hashlib.sha256(json.dumps(packet,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            p=root/'packet.json';p.write_text(json.dumps(packet))
            result={'packet_id':packet['packet_id'],'reviewer':'gpt_session','checks':[]}
            r=root/'result.json';r.write_text(json.dumps(result))
            with self.assertRaises(ValueError):codex_evolution.complete(root,p,r)
            result['checks']=[{'id':key,'status':'pass','detail':'Verified against local evidence and isolated tests.'} for key in codex_evolution.CHECKS]
            r.write_text(json.dumps(result));report=codex_evolution.complete(root,p,r)
            self.assertTrue(report.exists())
            packet['created_at']='tampered';p.write_text(json.dumps(packet))
            with self.assertRaises(ValueError):codex_evolution.complete(root,p,r)


if __name__=='__main__': unittest.main()
