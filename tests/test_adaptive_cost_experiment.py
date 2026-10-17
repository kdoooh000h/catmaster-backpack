from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmarks/directory-depth'))
import adaptive_experiment as A
import adaptive_cost as C
from test_adaptive_directory_experiment import tree


class AdaptiveCostTests(unittest.TestCase):
    def test_shared_scopes_are_lossless_and_do_not_modify_tree(self):
        nodes = {key: {'description': 'Complete parent scope. Subscopes (complete list): ' + name}
                 for key, name in [('a', 'First; second.'), ('b', 'Third; fourth.')]}
        before = deepcopy(nodes)
        spec, state = C.directory(nodes, ['a', 'b'], '原样中文需求')
        self.assertEqual(nodes, before)
        self.assertEqual(state['scope_context'], {'scope0': 'Complete parent scope.'})
        self.assertEqual(state['task'], '原样中文需求')
        self.assertIn('First; second.', spec['questions']['a']['instructions'])
        self.assertIn('Third; fourth.', spec['questions']['b']['instructions'])
        self.assertNotIn('Complete parent scope.', str(spec))
        self.assertIn('mandatory later work', state['rules'])
        self.assertIn('Quoted text, cancellations', state['rules'])

    def invoke(self, nodes, choices, targets, confidence=.7, keep_all=False):
        calls = []
        def call(stage, spec, state):
            calls.append((stage, spec, state))
            self.assertEqual(state['task'], '原始需求')
            self.assertNotIn('expected_ids', str(state))
            if stage == 'final':
                criteria = spec['questions']['answer']['criteria']
                self.assertEqual(criteria, {key: value for key, value in choices.items() if key in criteria})
                self.assertEqual(spec['questions']['answer']['instructions'], '原始问题')
                return {'answers': {'answer': {'type': 'choice', 'choice': 'cap000', 'confidence': confidence}}}
            return {'answers': {key: {'type': 'noul', 'noul': 1 if keep_all or targets.intersection(nodes[key]['members']) else 0}
                                for key in spec['questions']}}
        return C.route(nodes, '原始需求', choices, '原始问题', call), calls

    def test_global_pool_refines_small_branches(self):
        nodes, choices = tree(64)
        # Start at eight individually small branches, with a large union.
        nodes['n']['children'] = [key for key, value in nodes.items() if value['depth'] == 3]
        result, calls = self.invoke(nodes, choices, {'cap000'}, keep_all=True)
        self.assertEqual(calls[1][0], 'directory-1')
        self.assertEqual(result['final_pool_size'], 64)
        self.assertEqual(result['traces'][1]['carried_count'], 0)
        self.assertEqual(result['stop_reason'], 'terminal_categories')

    def test_required_later_branch_survives_and_final_is_unchanged(self):
        nodes, choices = tree(64)
        result, calls = self.invoke(nodes, choices, {'cap000', 'cap063'})
        self.assertTrue(A.grade({'expected_ids': ['cap000'], 'pending_ids': ['cap063']}, result)['omission_safe_pass'])
        self.assertIn('cap063', calls[-1][1]['questions']['answer']['criteria'])
        self.assertEqual(result['stop_reason'], 'small_pool')

    def test_final_gate_rejects_point_69_and_accepts_point_7(self):
        nodes, choices = tree()
        for confidence, status in [(.69, 'abstain'), (.7, 'selected')]:
            result, _ = self.invoke(nodes, choices, {'cap000'}, confidence)
            self.assertEqual(result['status'], status)
        self.assertEqual([A.gate(d) for d in range(1, 6)], [.2, .3, .4, .45, .45])

    def test_empty_match_does_not_call_final(self):
        nodes, choices = tree()
        result, calls = self.invoke(nodes, choices, set())
        self.assertEqual(result['status'], 'none')
        self.assertEqual(len(calls), 1)

    def test_nonshrinking_pool_never_falls_back_to_full(self):
        nodes, choices = tree(256)
        result, calls = self.invoke(nodes, choices, {'cap000'}, keep_all=True)
        self.assertEqual(result['reason'], 'no_progress')
        self.assertTrue(all(stage != 'final' for stage, _, _ in calls))

    def test_unknown_outcome_and_budget_are_never_replayed(self):
        nodes, choices = tree()
        for outcome in ['unknown_no_replay', 'experiment_budget_stop', 'unknown_usage_stop']:
            calls = []
            def call(stage, spec, state):
                calls.append(stage)
                raise RuntimeError(outcome)
            result = C.route(nodes, 'task', choices, 'question', call)
            self.assertEqual(result['reason'], outcome)
            self.assertEqual(len(calls), 1)

    def test_invalid_scores_do_not_become_dropped_branches(self):
        nodes, choices = tree()
        calls = []
        def call(stage, spec, state):
            calls.append(stage)
            return {'answers': {key: {'type': 'noul', 'noul': float('nan')} for key in spec['questions']}}
        result = C.route(nodes, 'task', choices, 'question', call)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['reason'], 'invalid_directory_scores')
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
