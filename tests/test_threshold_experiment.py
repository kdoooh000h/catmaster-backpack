import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmarks/directory-depth'))
import adaptive_threshold as T
import threshold_experiment as E
from test_adaptive_directory_experiment import tree

QUESTION = T.C.ORIGINAL_LEAD + 'Respect complete requirements and cancellation.'


def group(depth=3, count=30, scores=(.41, .45, .65, .8, .95)):
    nodes = {str(i): {'depth': depth, 'members': [f'{i}-{j}' for j in range(count)],
                      'description': 'Concrete operation', 'children': []} for i in range(len(scores))}
    raw = {'answers': {str(i): {'type': 'noul', 'noul': p} for i,p in enumerate(scores)}}
    return nodes, raw


class ThresholdTests(unittest.TestCase):
    def test_pressure_and_gap_raise_only_bounded_gate(self):
        nodes, raw = group(); original = deepcopy(raw)
        kept, info = T.retention(raw, list(nodes), [], nodes)
        self.assertEqual(kept, ['2', '3', '4'])
        self.assertEqual(info['applied_gates'][3], .5)
        self.assertEqual(info['changes'][0]['pool_after'], 90)
        self.assertEqual(raw, original)

    def test_early_gates_and_small_pools_unchanged(self):
        for depth, count in [(1,30), (2,30), (3,10)]:
            nodes, raw = group(depth, count)
            kept, info = T.retention(raw, list(nodes), [], nodes)
            self.assertEqual(kept, T.A.retained(raw, list(nodes), nodes))
            self.assertFalse(info['changes'])

    def test_near_scores_do_not_force_top_k(self):
        nodes, raw = group(scores=(.41,.44,.46,.51,.55))
        kept, info = T.retention(raw, list(nodes), [], nodes)
        self.assertEqual(len(T.A.union(nodes, kept)),150)
        self.assertFalse(info['changes'])

    def test_carried_later_branch_is_preserved(self):
        nodes, raw = group()
        nodes['later'] = {'depth': 2, 'members': ['later-target'], 'children': [], 'description': 'Later'}
        kept, info = T.retention(raw, list(raw['answers']), ['later'], nodes)
        self.assertIn('later-target', T.A.union(nodes, ['later'] + kept))
        self.assertEqual(info['changes'][0]['pool_after'],91)

    def test_capacity_counts_union_not_overlapping_members_twice(self):
        nodes, raw = group()
        for node in nodes.values(): node['members'] = nodes['0']['members']
        _,info = T.retention(raw,list(nodes),[],nodes)
        self.assertEqual(info['base_pool'],30)
        self.assertFalse(info['changes'])

    def test_invalid_scores_and_answer_keys_rejected(self):
        nodes, raw = group()
        for value in [True, float('nan'), -1, 1.1]:
            bad = deepcopy(raw);bad['answers']['0']['noul']=value
            with self.assertRaisesRegex(ValueError,'invalid_directory_scores'):
                T.retention(bad,list(nodes),[],nodes)
        with self.assertRaisesRegex(ValueError,'invalid_directory_answers'):
            T.retention({'answers':{}},list(nodes),[],nodes)

    def invoke(self, arm, confidence=.7):
        nodes, choices = tree(64);seen=[]
        def call(stage,spec,state):
            seen.append(deepcopy((stage,spec,state)))
            if stage=='final':
                return {'answers':{'answer':{'type':'choice','choice':'cap000','confidence':confidence}}}
            return {'answers':{k:{'type':'noul','noul':int('cap000' in nodes[k]['members'])} for k in spec['questions']}}
        return T.select(arm,nodes,'Raw Chinese mixed task 原始需求',choices,QUESTION,call),seen

    def test_adaptive_equals_baseline_when_no_pressure(self):
        baseline,old = self.invoke('baseline');candidate,new=self.invoke('adaptive_gate')
        for trace in candidate['traces']:trace.pop('threshold_adjustment')
        self.assertEqual((baseline,old),(candidate,new))

    def test_focus_changes_only_directory_questions(self):
        _,old=self.invoke('adaptive_gate');_,new=self.invoke('adaptive_focus')
        self.assertEqual(len(old),len(new))
        self.assertEqual(old[-1],new[-1])
        for left,right in zip(old[:-1],new[:-1]):
            self.assertEqual(left[0],right[0]);self.assertEqual(left[2],right[2])
            self.assertEqual(set(left[1]['questions']),set(right[1]['questions']))
            for key in left[1]['questions']:
                scope=right[1]['questions'][key]['instructions']['scope']
                self.assertTrue(left[1]['questions'][key]['instructions'].endswith(scope))

    def test_final_point_seven_unchanged(self):
        for arm in T.ARMS:
            result,_=self.invoke(arm,.69)
            self.assertEqual(result['status'],'abstain');self.assertIsNone(result['choice'])
            result,_=self.invoke(arm,.7)
            self.assertEqual(result['status'],'selected')

    def test_new_cases_and_reused_failure_are_checked_before_sending(self):
        additions=json.loads(E.FIXTURES.read_text())['cases']
        old={'id':E.FAILED,'need':'Exact previous need','expected_ids':['saas-metrics-coach'],
             'pending_ids':['dependency-auditor','confluence-expert']}
        rows=[{'case':E.FAILED,'arm':'early_stop','result':{'reason':'final_limit'}},
              {'case':E.FAILED,'arm':'described','omission_safe_pass':True}]
        catalog=[{'id':key} for key in {key for c in additions for key in c['expected_ids']+c['pending_ids']}]
        cases,reused=E.validate_cases([old],rows,additions,catalog,[])
        self.assertEqual(cases[0],old);self.assertEqual(reused,rows[1])
        with self.assertRaisesRegex(ValueError,'previous_case_reuse'):
            E.validate_cases([old],rows,additions,catalog,[{'id':'earlier','need':additions[0]['need']}])

    def bundle(self, root):
        root.mkdir();nodes,choices=tree()
        values={'plan.json':{'arms':T.ARMS,'final_gate':.7,'input_sha256':{},'source_sha256':{},
                'executable':str(root/'fake'),'executable_sha256':None,'max_seconds':5,'timeout_seconds':1,
                'max_calls':4,'max_known_tokens':1000,'case_arms':{E.FAILED:T.ARMS[1:]}},
            'catalog.json':[{'id':k,'description':v} for k,v in choices.items() if k!='none'],
            'candidate-nodes.json':nodes,'question.json':{'question':QUESTION,'none':'None'},
            'cases.json':[{'id':E.FAILED,'need':'Task','expected_ids':['cap000'],'pending_ids':['cap001'],'control':False}]}
        (root/'fake').write_text('fake')
        values['plan.json']['executable_sha256']=E.digest(root/'fake')
        for name,value in values.items():(root/name).write_text(json.dumps(value))
        return root

    def test_old_passing_baseline_never_resent_and_semantic_failures_retained(self):
        class Provider:
            def __init__(self,*a,**kw):self.calls=[]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with patch.object(E,'JevHierarchyProvider',Provider),patch.object(E,'select',return_value={'status':'none','traces':[{'pool':[]}]}),contextlib.redirect_stdout(io.StringIO()):
                E.run(self.bundle(root/'bundle'),root/'live')
            summary=json.loads((root/'live/summary.json').read_text())
            self.assertEqual(summary['stop'],'completed')
            self.assertEqual([r['arm'] for r in summary['rows']],T.ARMS[1:])
            self.assertFalse(any(r['omission_safe_pass'] for r in summary['rows']))

    def test_unknown_send_stops_without_second_arm(self):
        class Provider:
            def __init__(self,*a,**kw):self.calls=[]
            def noul(self,*a):
                self.calls.append({'outcome':'unknown_no_replay'})
                raise TimeoutError('unknown_no_replay')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with patch.object(E,'JevHierarchyProvider',Provider),contextlib.redirect_stdout(io.StringIO()):
                E.run(self.bundle(root/'bundle'),root/'live')
            summary=json.loads((root/'live/summary.json').read_text())
            self.assertEqual((summary['calls'],len(summary['rows'])),(1,1))
            self.assertEqual(summary['stop'],'budget_or_provider_failure')


if __name__ == '__main__':unittest.main()
