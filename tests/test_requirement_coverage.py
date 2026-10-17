from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks/directory-depth'))
import requirement_coverage as R
import requirement_coverage_experiment as X
import final_contrast as F
from structured_recall import StructuredIndex
import test_final_contrast as T


class RequirementCoverageTests(unittest.TestCase):
    def test_word_aliases_accept_document_nouns_and_reject_other_words(self):
        for need in ['Word 操作手册','Word模板','word 的培训手册','Word report','WORD contract','Word 讲义']:
            self.assertIsNotNone(R.WORD_ALIAS.search(need),need)
        for need in ['Word Counter API','WordPress template','password manual','word count report','keyword report']:
            self.assertIsNone(R.WORD_ALIAS.search(need),need)

    def test_additive_repair_retains_current_and_later_without_gold(self):
        rows=[{'id':'a','kind':'skill','name':'pptx','description':'Create presentations.'},
              {'id':'b','kind':'skill','name':'docx','description':'Create Word documents.'}]
        base={'pool':['a'],'catalog_count':2,'seconds':.01,'status':'recalled','hard_conditions':{}}
        index=StructuredIndex(rows)
        try:
            repaired=R.repair_recall(index,'当前制作演示文稿，然后写 Word 操作手册',base)
            self.assertEqual(set(repaired['recall']['pool']),{'a','b'})
            self.assertEqual(base['pool'],['a'])
            self.assertEqual(repaired['aliases'],['Word 操作手册'])
            self.assertGreaterEqual(repaired['recall']['seconds'],.01)
        finally:index.close()

    def test_unrecognized_need_does_not_rescan_or_mutate(self):
        base={'pool':['a'],'seconds':.01,'status':'recalled'}
        class NoSearch:
            def search(self,*args):raise AssertionError('unnecessary search')
        result=R.repair_recall(NoSearch(),'Word Counter API',base)
        self.assertEqual(result['recall']['pool'],base['pool'])
        self.assertEqual(base,{'pool':['a'],'seconds':.01,'status':'recalled'})

    def test_alias_repair_respects_explicit_kind_filter(self):
        rows=[{'id':'s','name':'docx','kind':'skill','description':'Create Word documents.'},
              {'id':'m','name':'docx','kind':'mcp','description':'Create Word documents.'}]
        index=StructuredIndex(rows)
        try:
            base={'pool':[],'catalog_count':1,'seconds':0,'status':'no_lexical_match','hard_conditions':{'allowed_kinds':['mcp']}}
            result=R.repair_recall(index,'Word 模板',base)
            self.assertEqual(result['recall']['pool'],['m'])
        finally:index.close()

    def test_evidence_is_literal_bilingual_metadata_intersection(self):
        description='Create editable decks with layouts and speaker notes.'
        hints=R.evidence('创建可编辑幻灯片，附讲者备注和统一版式',description)
        self.assertEqual(set(hints),{'editable','layouts','speaker notes'})
        self.assertTrue(all(h in description for h in hints))
        self.assertEqual(R.evidence('制作带讲者备注的演示文稿','Create presentations.'),[])

    def test_negative_requirements_and_negative_metadata_do_not_supply_hints(self):
        self.assertEqual(R.evidence('不需要讲者备注','Supports speaker notes.'),[])
        self.assertEqual(R.evidence('需要讲者备注','Create slides. Does not support speaker notes.'),[])
        self.assertEqual(R.evidence('不需要页码，保留批注','Use page numbers and comments.'),['comments'])

    def test_baseline_exact_and_hint_arms_preserve_every_description_and_order(self):
        original=deepcopy(T.ROWS)
        spec,mapping=R.specification('compact',T.ROWS,T.POOL,T.QUESTION,'需要讲者备注')
        self.assertEqual((spec,mapping),F.specification('typed_compact',T.ROWS,T.POOL,T.QUESTION))
        for arm in ['evidence','coverage']:
            candidate,other=R.specification(arm,T.ROWS,T.POOL,T.QUESTION,'需要讲者备注')
            self.assertEqual(other,mapping)
            for key,value in spec['questions']['answer']['criteria'].items():
                self.assertTrue(candidate['questions']['answer']['criteria'][key].endswith(value))
        self.assertEqual(T.ROWS,original)

    def test_final_gate_is_not_replaced_by_hints_or_top_probability(self):
        for arm in R.ARMS:
            for score,status in [(.69,'abstain'),(.7,'selected')]:
                calls=[]
                def call(stage,spec,state):
                    calls.append((stage,state));return T.answer('c2',score)
                result=R.select(arm,T.ROWS,T.POOL,T.QUESTION,'当前制作带讲者备注的幻灯片，然后读 PDF',call)
                self.assertEqual(result['status'],status)
                self.assertEqual(result['retained_candidates'],T.POOL)
                self.assertEqual(calls,[('final',{'task':'当前制作带讲者备注的幻灯片，然后读 PDF'})])


class RequirementRunnerTests(T.FinalRunnerTests):
    def fake_run(self,*args,**kwargs):
        with patch.object(T,'X',X):return super().fake_run(*args,**kwargs)


if __name__=='__main__':unittest.main()
