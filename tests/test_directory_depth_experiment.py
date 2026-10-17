"""Routing safety checks for the isolated public experiment, without model calls."""
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / 'benchmarks/directory-depth/experiment.py'
SPEC = importlib.util.spec_from_file_location('directory_depth_experiment', PATH)
E = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E)


def fixture(count=64):
    rows = [{'id': f'cap{i:03}', 'description': f'Full original capability {i}: ' +
             ('science physics laboratory' if i % 2 else 'design website accessibility')}
            for i in range(count)]
    taxonomy = {'leaves': [{'id': 'domain', 'label': 'Public test', 'description': 'All test capabilities',
                            'members': [row['id'] for row in rows]}],
                'roots': [{'id': 'root', 'label': 'Test root', 'description': 'Public only', 'children': ['domain']}]}
    return rows, taxonomy


def answers(ids, score):
    return {'answers': {key: {'type': 'noul', 'noul': score} for key in ids}}


class DepthExperimentTests(unittest.TestCase):
    def setUp(self):
        self.rows, self.tax = fixture()
        self.nodes = E.semantic_tree(self.rows, self.tax, 6)
        self.choices = {row['id']: row['description'] for row in self.rows}
        self.choices['none'] = 'No useful capability'

    def test_tree_is_complete_disjoint_deterministic(self):
        self.assertEqual(self.nodes, E.semantic_tree(self.rows, self.tax, 6))
        terminals = [node for node in self.nodes.values() if not node['children']]
        members = [key for node in terminals for key in node['members']]
        self.assertEqual(len(members), len(set(members)))
        self.assertEqual(set(members), set(self.choices) - {'none'})
        self.assertTrue(all(len(node['children']) in (0, 2) for node in self.nodes.values()))

    def test_schedules_reach_identical_terminal_pool(self):
        endings = []
        for layers in (2, 3, 4, 6):
            active = ['n']
            for depth in E.schedule(6, layers):
                offered = E.frontier(self.nodes, active, depth)
                active = [key for key in offered if 'cap000' in self.nodes[key]['members']]
            endings.append(E.union(self.nodes, active))
        self.assertEqual(endings, [{'cap000'}] * 4)
        self.assertEqual(E.schedule(6, 4), [2, 3, 5, 6])

    def call_for(self, targets, final_score=.7, final_key='cap000'):
        def call(stage, spec, state):
            self.assertEqual(state, {'task': 'ordinary unchanged request'})
            self.assertNotIn('expected_ids', json.dumps(spec))
            if stage != 'final':
                return {'answers': {key: {'type': 'noul', 'noul': .1 if targets & set(self.nodes[key]['members']) else 0}
                                    for key in spec['questions']}}
            criteria = spec['questions']['answer']['criteria']
            self.assertEqual(list(criteria), [key for key in self.choices if key in targets or key == 'none'])
            self.assertEqual(criteria['cap000'], self.choices['cap000'])
            return {'answers': {'answer': {'type': 'choice', 'choice': final_key, 'confidence': final_score}}}
        return call

    def test_multiple_branches_and_pending_are_preserved(self):
        result = E.route(self.nodes, E.schedule(6, 3), 'ordinary unchanged request', self.choices, 'question',
                         self.call_for({'cap000', 'cap063'}))
        grade = E.grade({'expected_ids': ['cap000'], 'pending_ids': ['cap063']}, result)
        self.assertTrue(grade['omission_safe_pass'])
        self.assertTrue(grade['all_required_retained'])
        self.assertEqual(result['final_pool_size'], 2)

    def test_current_choice_does_not_hide_pending_omission(self):
        result = E.route(self.nodes, [3, 6], 'ordinary unchanged request', self.choices, 'question', self.call_for({'cap000'}))
        grade = E.grade({'expected_ids': ['cap000'], 'pending_ids': ['cap063']}, result)
        self.assertTrue(grade['passed'])
        self.assertFalse(grade['omission_safe_pass'])
        self.assertFalse(grade['all_required_retained'])

    def test_final_point_seven_boundary(self):
        for score, status in ((.69, 'abstain'), (.7, 'selected')):
            result = E.route(self.nodes, [3, 6], 'ordinary unchanged request', self.choices, 'question',
                             self.call_for({'cap000'}, score))
            self.assertEqual(result['status'], status)

    def test_malformed_scores_rejected(self):
        for raw in ({}, {'answers': {'a': []}}, {'answers': {'a': {'type': 'noul', 'noul': True}}},
                    answers(['a'], float('nan')), answers(['a'], 1.1), answers(['a', 'b'], .5)):
            with self.assertRaises(ValueError):
                E.validate_retention(raw, ['a'])

    def test_limit_is_explicit_and_never_truncates(self):
        rows, tax = fixture(128)
        nodes = E.semantic_tree(rows, tax, 6)
        calls = []
        def call(stage, spec, state):
            calls.append(stage)
            return answers(spec['questions'], 1)
        result = E.route(nodes, [3, 6], 'task', {r['id']: r['description'] for r in rows}, 'question', call)
        self.assertEqual(result['reason'], 'final_limit')
        self.assertNotIn('final', calls)
        self.assertEqual(len(result['traces'][-1]['pool']), 128)

    def test_negative_stops_without_execution(self):
        result = E.route(self.nodes, [3, 6], 'quote only', self.choices, 'question',
                         lambda stage, spec, state: answers(spec['questions'], 0))
        self.assertEqual(result['status'], 'none')
        self.assertTrue(E.grade({'expected_ids': [], 'pending_ids': []}, result)['omission_safe_pass'])

    def test_transport_error_preserves_observed_trace(self):
        calls = []
        def call(stage, spec, state):
            calls.append(stage)
            if len(calls) == 2:
                raise TimeoutError('unknown_no_replay')
            return answers(spec['questions'], 1)
        result = E.route(self.nodes, [3, 6], 'task', self.choices, 'question', call)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['reason'], 'unknown_no_replay')
        self.assertEqual(len(result['traces']), 1)
        self.assertFalse(E.grade({'expected_ids': ['cap000'], 'pending_ids': []}, result)['omission_safe_pass'])

    def test_write_once_is_private_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'receipt.json'
            E.write_once(path, {'test': 1})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                E.write_once(path, {'test': 2})
            self.assertEqual(E.read(path), {'test': 1})

    def test_budget_stops_before_another_call_and_output_cannot_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp) / 'bundle'
            bundle.mkdir()
            values = {'catalog.json': self.rows, 'taxonomy.json': self.tax,
                      'cases.json': [{'id': 'case', 'need': 'test', 'expected_ids': ['cap000'],
                                      'pending_ids': [], 'stratum': 'synthetic', 'control': False}],
                      'question.json': {'question': 'Pick guidance', 'none': 'No guidance'}}
            for name, value in values.items():
                E.write_once(bundle / name, value)
            plan = {'arms': E.ARMS, 'runner_sha256': E.hashlib.sha256(PATH.read_bytes()).hexdigest(),
                    'tree_hashes': {str(h): E.identity(E.semantic_tree(self.rows, self.tax, h)) for h in (4, 6)},
                    'human_tree_hash': E.identity(E.human_tree(self.tax)), 'max_calls': 0,
                    'max_seconds': 10, 'max_known_tokens': 100, 'call_timeout_seconds': 1,
                    'executable': 'never-executed',
                    'frozen_sha256': {name: E.hashlib.sha256((bundle / name).read_bytes()).hexdigest() for name in values}}
            E.write_once(bundle / 'plan.json', plan)
            with patch.object(E, 'JevHierarchyProvider') as provider:
                provider.return_value.calls = []
                output = Path(temp) / 'out'
                E.run(bundle, output)
                provider.return_value.noul.assert_not_called()
                self.assertEqual(E.read(output / 'summary.json')['calls'], 0)
                self.assertEqual(E.read(output / 'summary.json')['rows'][0]['result']['reason'], 'experiment_budget_stop')
                with self.assertRaises(FileExistsError):
                    E.run(bundle, output)


if __name__ == '__main__':
    unittest.main()
