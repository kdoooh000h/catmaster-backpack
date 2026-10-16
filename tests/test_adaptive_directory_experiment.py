from pathlib import Path
import sys
import unittest
from unittest.mock import patch

FOLDER = Path(__file__).resolve().parents[1] / 'benchmarks/directory-depth'
sys.path.insert(0, str(FOLDER))
import adaptive_catalog as C
import adaptive_experiment as A


def tree(count=32):
    nodes = {}
    def add(members, key, depth):
        nodes[key] = {'id': key, 'depth': depth, 'members': members,
                      'description': 'Requested operation category ' + key, 'children': []}
        if len(members) > 4:
            middle = len(members) // 2
            nodes[key]['children'] = [key + 'a', key + 'b']
            add(members[:middle], key + 'a', depth + 1)
            add(members[middle:], key + 'b', depth + 1)
    add([f'cap{i:03}' for i in range(count)], 'n', 0)
    choices = {key: 'Complete original description ' + key + ': ' + 'requirements ' * 40 for key in nodes['n']['members']}
    choices['none'] = 'No useful capability'
    return nodes, choices


class AdaptiveDirectoryTests(unittest.TestCase):
    def invoke(self, nodes, choices, mode, targets, confidence=.7, keep_all=False):
        calls = []
        def call(stage, spec, state):
            self.assertEqual(state['task'], 'ordinary unchanged task')
            self.assertNotIn('expected_ids', str(state))
            calls.append((stage, spec, state))
            if stage != 'final':
                return {'answers': {key: {'type': 'noul', 'noul': 1 if keep_all or targets.intersection(nodes[key]['members']) else 0}
                                    for key in spec['questions']}}
            offered = spec['questions']['answer']['criteria']
            self.assertEqual(list(offered), [key for key in choices if key in offered])
            for key in offered:
                self.assertEqual(offered[key], choices[key])
            return {'answers': {'answer': {'type': 'choice', 'choice': 'cap000', 'confidence': confidence}}}
        result = A.route(nodes, mode, 'ordinary unchanged task', choices, 'original question', call)
        return result, calls

    def test_stops_early_and_avoids_redundant_directory_calls(self):
        nodes, choices = tree()
        adaptive, adaptive_calls = self.invoke(nodes, choices, 'adaptive', {'cap000'})
        deep, deep_calls = self.invoke(nodes, choices, 'deep', {'cap000'})
        self.assertEqual(adaptive['stop_reason'], 'small_pool')
        self.assertEqual(adaptive['final_pool_size'], 16)
        self.assertEqual(deep['final_pool_size'], 4)
        self.assertEqual(len(adaptive_calls), 2)
        self.assertEqual(len(deep_calls), 4)
        self.assertEqual(adaptive['choice'], deep['choice'])

    def test_fixed_two_stops_after_two_directory_steps(self):
        nodes, choices = tree()
        result, calls = self.invoke(nodes, choices, 'fixed2', {'cap000'})
        self.assertEqual(result['stop_reason'], 'fixed_depth')
        self.assertEqual(len(calls), 3)
        self.assertEqual(result['final_pool_size'], 8)

    def test_estimated_reading_cost_can_stop_before_smaller_pool(self):
        nodes, choices = tree(64)
        for key in nodes['na']['children']:
            nodes[key]['description'] = 'Detailed category operations ' * 2000
        result, calls = self.invoke(nodes, choices, 'adaptive', {'cap000'})
        self.assertEqual(result['stop_reason'], 'estimated_reading_cost')
        self.assertEqual(result['final_pool_size'], 32)
        self.assertEqual(len(calls), 2)

    def test_point_seven_stays_required(self):
        nodes, choices = tree()
        result, _ = self.invoke(nodes, choices, 'adaptive', {'cap000'}, .69)
        self.assertEqual(result['status'], 'abstain')
        self.assertIsNone(result['choice'])
        self.assertEqual(A.gate(1), .2)
        self.assertEqual(A.gate(5), .45)

    def test_does_not_recheck_small_carried_branch(self):
        nodes, choices = tree(64)
        # A separate mandatory small branch must survive while the large one splits.
        nodes['pending'] = {'id': 'pending', 'depth': 1, 'members': ['later'], 'children': [], 'description': 'Mandatory later action'}
        nodes['n']['children'].append('pending')
        nodes['n']['members'].append('later')
        choices['later'] = 'Full later guidance'
        result, calls = self.invoke(nodes, choices, 'adaptive', {'cap000', 'later'})
        self.assertEqual(result['traces'][1]['carried'], ['pending'])
        self.assertTrue(all('later' in trace['pool'] for trace in result['traces']))
        self.assertIn('later', calls[-1][1]['questions']['answer']['criteria'])

    def test_stops_unproductive_expansion_without_full_fallback(self):
        nodes, choices = tree(256)
        result, calls = self.invoke(nodes, choices, 'adaptive', {'cap000'}, keep_all=True)
        self.assertEqual(result['reason'], 'no_progress')
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(stage != 'final' for stage, _, _ in calls))

    def test_multiple_required_branches_and_omission_accounting(self):
        nodes, choices = tree(64)
        result, _ = self.invoke(nodes, choices, 'adaptive', {'cap000', 'cap063'})
        score = A.grade({'expected_ids': ['cap000'], 'pending_ids': ['cap063']}, result)
        self.assertTrue(score['omission_safe_pass'])
        result, _ = self.invoke(nodes, choices, 'adaptive', {'cap000'})
        score = A.grade({'expected_ids': ['cap000'], 'pending_ids': ['cap063']}, result)
        self.assertTrue(score['passed'])
        self.assertFalse(score['omission_safe_pass'])

    def test_malformed_and_timeout_never_replay(self):
        nodes, choices = tree()
        for error in ('invalid', 'unknown_no_replay'):
            calls = []
            def call(stage, spec, state):
                calls.append(stage)
                if error == 'invalid':
                    return {'answers': {}}
                raise TimeoutError(error)
            result = A.route(nodes, 'adaptive', 'task', choices, 'question', call)
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(len(calls), 1)

    def test_catalog_rejects_lost_members_and_preserves_complete_coverage(self):
        rows = [{'id': str(i), 'name': 'operation ' + str(i), 'description': 'Distinct operation ' + str(i)} for i in range(8)]
        tax = {'roots': [{'id': 'r', 'label': 'Root', 'description': 'All work', 'children': ['d']}],
               'leaves': [{'id': 'd', 'label': 'Domain', 'description': 'Domain operations', 'members': [r['id'] for r in rows]}]}
        with patch.object(C, 'TOPICS', {'d': [('First operations', '0 1 2')]}):
            with self.assertRaisesRegex(ValueError, 'incomplete_topics'):
                C.build(rows, tax)
        with patch.object(C, 'TOPICS', {'d': [('First operations', '0 1 2 3'), ('Second operations', '4 5 6 7')]}):
            nodes = C.build(rows, tax)
        self.assertEqual(C.union(nodes, ['n']), {r['id'] for r in rows})
        self.assertEqual(C.union(nodes, nodes['d']['children']), set(nodes['d']['members']))


if __name__ == '__main__':
    unittest.main()
