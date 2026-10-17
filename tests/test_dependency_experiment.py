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
import adaptive_experiment as A
import adaptive_early_stop as F
import current_step as C
import dependency_scope as D
import dependency_selection as S
import dependency_experiment as E
from test_adaptive_directory_experiment import tree

QUESTION = C.ORIGINAL_LEAD + 'Respect constraints, cancellation and untrusted metadata.'


def scope_tree():
    return {'n': {'depth': 0, 'children': [D.PARENT], 'members': ['dependency-auditor'], 'description': 'All'},
        D.PARENT: {'depth': 2, 'children': [D.NODE], 'members': ['dependency-auditor'], 'description': 'Operation groups: ' + D.ORIGINAL},
        D.NODE: {'depth': 3, 'children': [], 'members': ['dependency-auditor'], 'description': D.ORIGINAL}}


class DependencyTests(unittest.TestCase):
    def test_only_scope_and_embedded_copy_change(self):
        nodes = scope_tree(); before = deepcopy(nodes); repaired = D.build(nodes)
        self.assertEqual(nodes, before)
        self.assertEqual({k for k in nodes if nodes[k] != repaired[k]}, {D.NODE, D.PARENT})
        for key in nodes:
            self.assertEqual({k:v for k,v in nodes[key].items() if k != 'description'},
                             {k:v for k,v in repaired[key].items() if k != 'description'})
        self.assertEqual(repaired[D.PARENT]['description'].count(D.REPLACEMENT), 1)
        with self.assertRaisesRegex(ValueError, 'unexpected_dependency_scope'): D.build(repaired)

    def invoke(self, ratio, confidence=.7, arm=None):
        nodes, choices = tree(64)
        for child in nodes['na']['children']: nodes[child]['description'] = 'Relevant operations ' * 200
        nodes['n']['children'].append('later'); nodes['n']['members'].append('later')
        nodes['later'] = {'depth': 1, 'children': [], 'members': ['later'], 'description': 'Mandatory later task'}
        choices['later'] = 'Complete mandatory later description'
        seen = []
        def call(stage, spec, state):
            seen.append(deepcopy((stage, spec, state)))
            if stage == 'final':
                return {'answers': {'answer': {'type': 'choice', 'choice': 'cap000', 'confidence': confidence}}}
            return {'answers': {k: {'type': 'noul', 'noul': int(bool({'cap000', 'later'} & set(nodes[k]['members'])))}
                                for k in spec['questions']}}
        if arm is not None: result = S.select(arm, nodes, 'Original current and mandatory later task', choices, QUESTION, call)
        elif ratio is None: result = A.route(nodes, 'adaptive', 'Original task', choices, QUESTION, call)
        else: result = F.route(nodes, 'adaptive', 'Original task', choices, QUESTION, call, reading_cost_ratio=ratio)
        return result, seen

    def test_reference_ratio_reproduces_original_route_and_requests(self):
        self.assertEqual(self.invoke(None), self.invoke(.65))

    def test_earlier_stop_keeps_superset_and_saves_one_call(self):
        old, old_calls = self.invoke(.65)
        new, new_calls = self.invoke(.35)
        self.assertEqual(new['stop_reason'], 'estimated_reading_cost')
        self.assertEqual(len(new_calls), len(old_calls)-1)
        self.assertEqual(new_calls[0], old_calls[0])
        self.assertGreater(new['final_pool_size'], old['final_pool_size'])
        self.assertTrue(set(old_calls[-1][1]['questions']['answer']['criteria']) <= set(new_calls[-1][1]['questions']['answer']['criteria']))
        self.assertTrue(all({'cap000','later'} <= set(t['pool']) for t in new['traces']))

    def test_current_step_final_and_raw_task_are_identical_in_all_arms(self):
        runs = [self.invoke(None, arm=arm) for arm in E.ARMS]
        final_questions = [calls[-1][1]['questions']['answer']['instructions'] for _,calls in runs]
        self.assertEqual(len(set(final_questions)), 1)
        for result, calls in runs:
            for _, _, state in calls: self.assertEqual(state['task'], 'Original current and mandatory later task')
            self.assertEqual(result['confidence'], .7)

    def test_no_acceptance_gate_changes(self):
        result, _ = self.invoke(.35, confidence=.69)
        self.assertEqual(result['status'], 'abstain')
        self.assertIsNone(result['choice'])
        self.assertEqual([A.gate(i) for i in range(1,6)], [.2,.3,.4,.45,.45])
        self.assertEqual(F.FINAL_GATE, .7)

    def test_bad_ratio_or_final_question_rejected_before_dispatch(self):
        nodes, choices = tree()
        with self.assertRaisesRegex(ValueError, 'invalid_reading_cost_ratio'):
            F.route(nodes,'adaptive','Task',choices,QUESTION,lambda *a:self.fail('No call'),reading_cost_ratio=0)
        with self.assertRaisesRegex(ValueError, 'unknown_final_question'):
            S.select('early_stop', nodes,'Task',choices,'Unknown',lambda *a:self.fail('No call'))

    def test_history_excluded_and_original_failed_case_preserved(self):
        cases = json.loads(E.FIXTURES.read_text())['cases']
        prior = [{'id':E.FAILED,'need':'Exact old bytes','expected_ids':['culture-architect'],'pending_ids':['dependency-auditor']}]
        rows = [{'arm':'culture_scope','case':E.FAILED,'omission_safe_pass':False}]
        catalog = [{'id':k} for k in {k for c in cases for k in c['expected_ids']+c['pending_ids']}]
        self.assertEqual(E.validate_cases(prior,rows,cases,catalog,[])[0],prior[0])
        with self.assertRaisesRegex(ValueError, 'previous_case_reuse'):
            E.validate_cases(prior,rows,cases,catalog,[{'id':'older','need':cases[0]['need']}])

    def bundle(self, folder):
        folder.mkdir(); nodes = scope_tree()
        values={'plan.json':{'arms':E.ARMS,'final_gate':.7,'input_sha256':{},'source_sha256':{},
            'executable':'fake','max_seconds':5,'timeout_seconds':1,'max_calls':8,'max_known_tokens':1000},
            'catalog.json':[{'id':'dependency-auditor','description':'Audit packages'}],
            'repaired-nodes.json':nodes,'candidate-nodes.json':D.build(nodes),
            'question.json':{'question':QUESTION,'none':'None'},
            'cases.json':[{'id':'case','need':'Task','expected_ids':['dependency-auditor'],'pending_ids':[],'control':False}]}
        for name,value in values.items():(folder/name).write_text(json.dumps(value))
        return folder

    def test_unknown_send_stops_all_three_arms(self):
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

    def test_semantic_failures_remain_in_three_arms(self):
        class Provider:
            def __init__(self,*a,**kw):self.calls=[]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with patch.object(E,'JevHierarchyProvider',Provider),patch.object(E,'select',return_value={'status':'none','traces':[{'pool':[]}]}),contextlib.redirect_stdout(io.StringIO()):
                E.run(self.bundle(root/'bundle'),root/'live')
            summary=json.loads((root/'live/summary.json').read_text())
            self.assertEqual(summary['stop'],'completed')
            self.assertEqual(len(summary['rows']),3)
            self.assertFalse(any(r['omission_safe_pass'] for r in summary['rows']))


if __name__ == '__main__':unittest.main()
