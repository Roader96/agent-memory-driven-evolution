"""Offline retrieval plumbing tests; fake vectors do NOT measure model benefit."""
from __future__ import annotations
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import codex_memory
import codex_semantic

HAS_NUMPY = importlib.util.find_spec('numpy') is not None
if HAS_NUMPY:
    import numpy as np


def summary(session_id='session-a', **updates):
    row = {'session_id':session_id, 'date':'2026-10-01', 'updated':'2026-10-01T12:00:00+08:00',
           'title':'Memory workflow', 'project':'project-a', 'cwd':'/tmp/project-a',
           'status':'done', 'evidence_count':0, 'goal':[], 'claims':[], 'verified':[],
           'open_items':[], 'decisions':[], 'corrections':[], 'sources':[]}
    row.update(updates)
    return row


class RetrievalFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home/'.index').mkdir()
        model = self.home/'models/multilingual-e5-small'
        model.mkdir(parents=True)
        self.provenance = model/'model-provenance.json'
        self.provenance.write_text(json.dumps({'repo':'local/test', 'revision':'fixed-v1', 'weights':'fixture'}))
        self.experiences = []
        self.source = self.home/'source-evidence.md'
        self.source.write_text('User correction: read corrections before raw claims.',encoding='utf-8')
        self.ref = {'path':str(self.source),'quote':'read corrections before raw claims'}
        module = types.SimpleNamespace(load_experiences=lambda home:self.experiences)
        self.optional = patch.dict(sys.modules, {'codex_experience':module})
        self.optional.start()

    def tearDown(self):
        self.optional.stop()
        self.tmp.cleanup()

    def archive(self, *rows):
        path = self.home/'.index/sessions.jsonl'
        path.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows),encoding='utf-8')
        return path


class RetrievalUnitTests(RetrievalFixture):
    def test_units_index_every_kind_and_late_corrections_without_changing_archive(self):
        row = summary(corrections=['纠正一：不是只改技能', '纠正二：要按任务类型', '纠正三：优先用户记忆'],
                      decisions=['decision one', 'decision two', 'decision three'],
                      verified=['PASS tool-output signal'], claims=['助手声称：所有问题都解决了'])
        path = self.archive(row)
        before = path.read_bytes()
        units = codex_semantic.retrieval_units(self.home)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(len([u for u in units if u['unit_kind']=='correction']),3)
        self.assertTrue(any('纠正三' in codex_semantic.document(u) for u in units))
        self.assertTrue(any('decision three' in u['text'] for u in units))
        claim = next(u for u in units if u['unit_kind']=='claim_unverified')
        self.assertIn('unverified',codex_semantic.document(claim))
        signal = next(u for u in units if u['unit_kind']=='verified')
        self.assertEqual(signal['evidence_level'],'tool_output_signal_not_task_success')
        for unit in units:
            self.assertEqual(unit['source_session_id'],row['session_id'])
            self.assertTrue(unit['source_path'].endswith('/memory.md'))

    def test_legacy_document_api_remains_usable_and_does_not_drop_third_correction(self):
        text = codex_semantic.document(summary(corrections=['first','second','third'],claims=['unconfirmed']))
        self.assertTrue(text.startswith('passage: '))
        self.assertIn('third',text)
        self.assertIn('assistant_claim_unverified',text)

    def test_new_user_correction_markers_are_candidates_not_verification(self):
        stamp = datetime.fromisoformat('2026-11-09T17:00:00+08:00')
        session = codex_memory.Session('new-correction',cwd='/tmp/project-a')
        session.messages = [codex_memory.Message('user','自进化不一定非要站在skill的角度，同样类型任务的memory同样重要。',stamp,'t','u','fixture',1)]
        row = codex_memory.build_summary(session)
        self.assertTrue(any('不一定非要' in value for value in row['corrections']))
        self.assertEqual(row['verified'],[])
        self.archive(row)
        units = codex_semantic.retrieval_units(self.home)
        self.assertTrue(any(u['unit_kind']=='correction' and 'memory' in u['text'] for u in units))

    def test_lexical_priority_requires_content_match_and_claims_stay_unverified(self):
        correction=summary(corrections=['same retrieval keyword'])
        claim=summary(claims=['same retrieval keyword'])
        self.assertGreater(codex_memory.score_query(correction,'retrieval'),codex_memory.score_query(claim,'retrieval'))
        self.assertEqual(codex_memory.score_query(summary(status='blocked'),'blocked'),0)
        self.archive(claim)
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(codex_memory.recall(self.home,'retrieval'),0)
        self.assertIn('未验证助手声明',output.getvalue())
        self.assertNotIn('证据：same retrieval keyword',output.getvalue())

    def test_lexical_output_is_bounded_and_prioritizes_corrections_over_nested_logs(self):
        envelope=json.dumps({'value':{'output':'PASS: actual output\n'+'nested-log '*1400}})
        rows=[summary('session-'+str(i),corrections=['memory workflow 应先记住用户纠正'],
                      decisions=['memory workflow 保留决定'],verified=[envelope]*8) for i in range(10)]
        self.archive(*rows)
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(codex_memory.recall(self.home,'memory',limit=100),0)
        text=output.getvalue()
        self.assertLess(len(text),5300)
        self.assertIn('用户纠正候选',text)
        self.assertIn('决策摘录',text)
        self.assertLess(text.index('用户纠正候选'),text.index('工具证据信号'))
        self.assertIn('/memory.md',text)
        self.assertNotIn('nested-log '*50,text)

    def test_active_experiences_retain_scope_provenance_and_status(self):
        self.archive(summary())
        self.experiences=[{'memory_id':'m1','revision':3,'status':'active','scope':'project-a',
                          'task_family':'recall','conditions':'when resuming work',
                          'recommended_action':'read the correction first','avoid':'trusting raw claims',
                          'evidence_refs':[self.ref],'evidence_level':'user_explicit','updated_at':'2026-11-09'},
                         {'memory_id':'m2','revision':1,'status':'candidate','scope':'global','recommended_action':'not promoted'}]
        units=codex_semantic.retrieval_units(self.home)
        xp=[u for u in units if u['source_type']=='experience']
        self.assertEqual(len(xp),1)
        unit=xp[0]
        self.assertEqual(unit['revision'],3)
        self.assertEqual(unit['evidence_refs'],[self.ref])
        self.assertEqual(unit['evidence_level'],'user_explicit')
        self.assertFalse(codex_semantic._in_scope(unit))
        self.assertFalse(codex_semantic._in_scope(unit,family='recall'))
        self.assertFalse(codex_semantic._in_scope(unit,project='project-b',family='recall'))
        self.assertTrue(codex_semantic._in_scope(unit,project='project-a',family='recall'))
        self.assertFalse(codex_semantic._in_scope(unit,project='project-a',family='writing'))
        self.assertTrue(codex_semantic._in_scope({**unit,'scope':'global'}))

    def test_experiences_with_missing_or_changed_sources_are_not_retrievable(self):
        self.archive(summary(goal=['The raw session remains archived']))
        self.experiences=[{'memory_id':'m1','revision':2,'status':'active','scope':'global',
                          'recommended_action':'Read the correction first','evidence_refs':[self.ref]}]
        self.assertTrue(any(u['source_type']=='experience' for u in codex_semantic.retrieval_units(self.home)))
        for change in (lambda:self.source.write_text('Different source text'),lambda:self.source.unlink()):
            change()
            warnings=[]
            units=codex_semantic.retrieval_units(self.home,warnings)
            self.assertTrue(all(u['source_type']=='session' for u in units))
            self.assertEqual(warnings[0]['memory_id'],'m1')
            self.assertEqual(warnings[0]['revision'],2)

    def test_session_filter_does_not_confuse_two_explicit_project_paths(self):
        unit=codex_semantic._session_units(summary(cwd='/one/project-a',goal=['task']))[0]
        self.assertFalse(codex_semantic._in_scope(unit,project='/two/project-a'))
        self.assertTrue(codex_semantic._in_scope(unit,project='/one/project-a'))
        self.assertTrue(codex_semantic._in_scope(unit))

    def test_optional_experience_module_can_be_absent(self):
        self.archive(summary(goal=['retained legacy task']))
        with patch.dict(sys.modules,{'codex_experience':None}):
            units=codex_semantic.retrieval_units(self.home)
        self.assertEqual(len(units),1)
        self.assertEqual(units[0]['source_type'],'session')


@unittest.skipUnless(HAS_NUMPY,'numpy optional; cache tests require offline retrieval runtime')
class RetrievalIndexTests(RetrievalFixture):
    class FakeEncoder:
        def __init__(self): self.calls=[]
        def encode(self,texts):
            import numpy as np
            self.calls.append(list(texts))
            # Deterministic plumbing fixture, not a semantic model or benefit test.
            return np.asarray([[1.0,0.0] if 'orthogonal-query' not in text else [0.0,1.0] for text in texts],dtype='float32')

    def test_unit_build_cache_and_fingerprint_invalidate_old_vectors(self):
        import numpy as np
        self.archive(summary(corrections=['first','second','third correction'],claims=['raw claim']))
        path=self.home/'.index/semantic.npz'
        np.savez(path,hashes=np.asarray(['legacy']),vectors=np.asarray([[0.,1.]]),rows=np.asarray(['{}']),model_id=np.asarray('fixed-v1'))
        encoder=self.FakeEncoder()
        first=codex_semantic.build(self.home,encoder)
        self.assertEqual(first['encoded'],4)
        self.assertTrue(any('third correction' in text for text in encoder.calls[0]))
        self.assertTrue(any('assistant_claim_unverified' in text for text in encoder.calls[0]))
        with np.load(path,allow_pickle=False) as index:
            self.assertEqual(int(index['index_schema']),codex_semantic.INDEX_SCHEMA_VERSION)
            self.assertEqual(len(index['vectors']),4)
            self.assertEqual(len(index['sessions']),1)
        second=codex_semantic.build(self.home,encoder)
        self.assertEqual(second['encoded'],0)
        self.assertEqual(len(encoder.calls),1)
        self.provenance.write_text(json.dumps({'repo':'local/test','revision':'fixed-v2','weights':'fixture'}))
        third=codex_semantic.build(self.home,encoder)
        self.assertEqual(third['encoded'],4)
        self.assertNotEqual(first['model_fingerprint'],third['model_fingerprint'])
        with patch.object(codex_semantic,'INDEX_SCHEMA_VERSION',codex_semantic.INDEX_SCHEMA_VERSION+1):
            self.assertEqual(codex_semantic.build(self.home,encoder)['encoded'],4)

    def test_search_labels_deduplicates_and_applies_scope_and_similarity_before_priority(self):
        self.archive(summary(corrections=['first correction','second correction'],claims=['raw claim']),
                     summary('session-b',corrections=['third correction']))
        self.experiences=[{'memory_id':'scoped','revision':1,'status':'active','scope':'project-other',
                          'task_family':'recall','recommended_action':'private project advice',
                          'evidence_refs':[self.ref],'evidence_level':'user_explicit'}]
        encoder=self.FakeEncoder()
        with patch.object(codex_semantic,'Encoder',return_value=encoder):
            results=codex_semantic.search(self.home,'correction',limit=10,max_per_session=1)
            self.assertEqual(len(results),2)
            self.assertTrue(all(x['unit']['unit_kind']=='correction' for x in results))
            self.assertTrue(all(x['session']['session_id'].startswith('session-') for x in results))
            self.assertTrue(all(x['source_path'].endswith('/memory.md') for x in results))
            self.assertEqual(codex_semantic.search(self.home,'orthogonal-query'),[])
            selected=codex_semantic.search(self.home,'correction',project='project-other',family='recall')
            self.assertEqual(len(selected),1)
            self.assertEqual(selected[0]['unit']['memory_id'],'scoped')
            self.assertEqual(codex_semantic.search(self.home,'',limit=3),[])
            self.assertEqual(codex_semantic.search(self.home,'correction',limit=0),[])

    def test_rebuild_drops_previously_encoded_experience_when_source_is_removed(self):
        self.archive(summary(goal=['retained raw session']))
        self.experiences=[{'memory_id':'m1','revision':1,'status':'active','scope':'global',
                          'recommended_action':'Check the correction','evidence_refs':[self.ref]}]
        encoder=self.FakeEncoder()
        first=codex_semantic.build(self.home,encoder)
        self.assertEqual(first['experiences'],1)
        self.source.unlink()
        second=codex_semantic.build(self.home,encoder)
        self.assertEqual(second['experiences'],0)
        self.assertEqual(second['evidence_warnings'][0]['memory_id'],'m1')
        self.assertEqual(second['documents'],1)


if __name__=='__main__': unittest.main()
