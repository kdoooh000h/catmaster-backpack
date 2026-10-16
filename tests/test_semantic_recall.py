from copy import deepcopy
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks/directory-depth'))
from semantic_recall import SemanticIndex, OpenLexicalIndex
import independent_current as F

ROWS=[{'id':'now','name':'Current','kind':'skill','mode':'guidance','description':'Current operation'},
      {'id':'later','name':'Later','kind':'skill','mode':'guidance','description':'Later operation'},
      {'id':'tool','name':'Tool','kind':'mcp','mode':'execution_requirements_unverified','description':'Tool operation'},
      {'id':'legacy','name':'Legacy','kind':'plugin','mode':'package_requirements_unverified','description':'Legacy operation'}]
VECTORS=np.array([[1,0],[0,1],[0,1],[-1,0]],dtype=np.float32)


def answer(choice='current',confidence=.8):
    probs={k:.05 for k in F.CRITERIA};probs[choice]=.9
    return {'type':'choice','choice':choice,'confidence':confidence,'probabilities':probs}


class SemanticRecallTests(unittest.TestCase):
    def index(self,encoder=None):
        return SemanticIndex(ROWS,VECTORS,encoder or (lambda q:np.array([[0,1] for _ in q])))

    def test_full_need_and_all_clauses_keep_later_and_baseline(self):
        seen=[]
        def encode(q):seen.extend(q);return np.array([[1,0] if i==0 else [0,1] for i,_ in enumerate(q)])
        result=self.index(encode).search('先做当前；然后做后续',{'pool':['legacy'],'catalog_count':4,'seconds':0},per_kind=1)
        self.assertEqual(seen,['query: 先做当前；然后做后续','query: 先做当前','query: 然后做后续'])
        self.assertEqual(set(result['pool']),{'now','later','tool','legacy'})

    def test_kind_filter_applies_before_neighbor_selection(self):
        result=self.index().search('需求',{'pool':[],'catalog_count':2,'seconds':0,'hard_conditions':{'allowed_kinds':['skill']}},per_kind=1)
        self.assertEqual(result['pool'],['later'])

    def test_ties_survive_and_overwide_pool_stops_without_truncation(self):
        index=SemanticIndex(ROWS,np.array([[1,0]]*4),lambda q:np.array([[1,0]]*len(q)))
        result=index.search('需求',{'pool':[],'catalog_count':4,'seconds':0},per_kind=1,max_candidates=2)
        self.assertEqual(result['status'],'widen_required');self.assertEqual(len(result['pool']),4)

    def test_invalid_vector_or_baseline_is_rejected(self):
        with self.assertRaises(ValueError):SemanticIndex(ROWS,VECTORS*2,lambda q:q)
        with self.assertRaises(ValueError):self.index().search('x',{'pool':['unknown'],'catalog_count':4,'seconds':0})

    def test_open_lexical_unknown_domain_needs_no_object_vocabulary(self):
        rows=[{**r,'name':'quuxophone' if r['id']=='tool' else r['name']} for r in ROWS]
        index=OpenLexicalIndex(rows)
        try:
            result=index.search('Inspect quuxophone records',{'pool':['legacy'],'catalog_count':4,'seconds':0})
            self.assertIn('tool',result['pool']);self.assertIn('legacy',result['pool'])
            filtered=index.search('Inspect quuxophone records',{'pool':[],'catalog_count':2,'seconds':0,'hard_conditions':{'allowed_kinds':['skill']}})
            self.assertNotIn('tool',filtered['pool'])
        finally:index.close()


class IndependentCurrentTests(unittest.TestCase):
    def test_shared_raw_task_full_metadata_and_one_call(self):
        calls=[]
        def call(stage,spec,state):
            calls.append((stage,spec,state))
            return {'answers':{k:answer('current' if k=='c1' else 'other') for k in spec['questions']}}
        result=F.select(ROWS,['now','later'],'当前做A，后续做B',call)
        self.assertEqual(len(calls),1);self.assertEqual(result['choice'],'now')
        self.assertEqual(calls[0][2]['task'],'当前做A，后续做B')
        self.assertEqual(calls[0][2]['candidates']['c2']['description'],ROWS[1]['description'])
        self.assertEqual(result['retained_candidates'],['now','later'])

    def test_point_seven_gate_and_partial_or_later_never_pass(self):
        for choice,confidence in [('current',.699),('partial',1),('other',1)]:
            result=F.validate({'answers':{'c1':answer(choice,confidence)}},{'c1':'now'},['now'])
            self.assertEqual(result['status'],'abstain')
        result=F.validate({'answers':{'c1':answer('current',.7)}},{'c1':'now'},['now'])
        self.assertEqual(result['choice'],'now')

    def test_multiple_fit_candidates_remain_available_without_probability_sum(self):
        result=F.validate({'answers':{'c1':answer(),'c2':answer()}},{'c1':'now','c2':'later'},['now','later'])
        self.assertEqual(result['confidence'],.8)
        self.assertEqual(result['accepted_candidates'],['now','later'])

    def test_invalid_or_missing_answer_is_rejected(self):
        for raw in [{'answers':{}},{'answers':{'c1':answer(confidence=float('nan'))}}]:
            with self.assertRaises(ValueError):F.validate(raw,{'c1':'now'},['now'])
        bad=answer();bad['probabilities']['current']=.1
        with self.assertRaises(ValueError):F.validate({'answers':{'c1':bad}},{'c1':'now'},['now'])


if __name__=='__main__':unittest.main()
