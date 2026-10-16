import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmarks/directory-depth'))
import slim_experiment as S
from test_adaptive_directory_experiment import tree


class SlimDirectoryTests(unittest.TestCase):
    def test_small_nonterminal_branch_survives_without_redisclosure(self):
        nodes, choices = tree(64)
        later = ['later' + str(i) for i in range(6)]
        nodes['n']['children'].append('later'); nodes['n']['members'] += later
        nodes['later'] = {'depth': 1, 'children': ['later-a', 'later-b'], 'members': later, 'description': 'Required later operation'}
        for suffix, members in [('a', later[:3]), ('b', later[3:])]:
            nodes['later-' + suffix] = {'depth': 2, 'children': [], 'members': members, 'description': 'Redundant child description'}
        choices.update({key: 'Full unchanged later capability ' + key for key in later})
        requests = []
        def call(stage, spec, state):
            requests.append((stage, spec))
            self.assertNotIn('expected_ids', state)
            if stage == 'final':
                criteria = spec['questions']['answer']['criteria']
                self.assertTrue(set(later) <= set(criteria))
                self.assertTrue(all(choices[key] == value for key, value in criteria.items()))
                return {'answers': {'answer': {'type': 'choice', 'choice': 'cap000', 'confidence': .7}}}
            self.assertTrue(all('Follow state.rules.' in q['instructions'] for q in spec['questions'].values()))
            return {'answers': {key: {'type': 'noul', 'noul': int(bool({'cap000', 'later0'} & set(nodes[key]['members'])))} for key in spec['questions']}}
        result = S.select('slim', nodes, 'Current task and later task', choices, 'Select', call)
        self.assertEqual(result['status'], 'selected')
        self.assertEqual(len(requests), 3)
        self.assertNotIn('later-a', {key for stage, spec in requests for key in spec['questions']})
        self.assertTrue(all('later0' in trace['pool'] for trace in result['traces']))
        self.assertEqual(result['confidence'], .7)

    def test_reference_explicitly_disables_review(self):
        with patch.object(S.R, 'route', return_value={'status': 'none'}) as route:
            S.select('repaired', {}, 'Task', {}, 'Select', object())
            self.assertIs(route.call_args.kwargs['review'], False)

    def bundle(self, root):
        root.mkdir()
        nodes, choices = tree()
        data = {'plan.json': {'arms': S.ARMS, 'final_gate': .7, 'input_sha256': {}, 'source_sha256': {},
            'executable': 'fake', 'max_seconds': 5, 'timeout_seconds': 1, 'max_calls': 8, 'max_known_tokens': 1000},
            'catalog.json': [{'id': k, 'description': v} for k, v in choices.items() if k != 'none'],
            'repaired-nodes.json': nodes, 'question.json': {'question': 'Select', 'none': 'None'},
            'cases.json': [{'id': 'case', 'need': 'Task', 'expected_ids': ['cap000'], 'pending_ids': [], 'control': False}]}
        for name, value in data.items(): (root / name).write_text(json.dumps(value))
        return root

    def test_unknown_send_stops_both_arms_without_retry(self):
        class Provider:
            def __init__(self, *args, **kwargs): self.calls = []
            def noul(self, *args):
                self.calls.append({'outcome': 'unknown_no_replay'})
                raise TimeoutError('unknown_no_replay')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(S, 'JevHierarchyProvider', Provider), contextlib.redirect_stdout(io.StringIO()):
                S.run(self.bundle(root / 'bundle'), root / 'live')
            summary = json.loads((root / 'live/summary.json').read_text())
            self.assertEqual(summary['calls'], 1)
            self.assertEqual(summary['stop'], 'budget_or_provider_failure')
            self.assertEqual(len(summary['rows']), 1)

    def test_semantic_failures_remain_and_no_automatic_retry(self):
        class Provider:
            def __init__(self, *args, **kwargs): self.calls = []
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(S, 'JevHierarchyProvider', Provider), patch.object(S, 'select', return_value={'status': 'none', 'traces': [{'pool': []}]}), contextlib.redirect_stdout(io.StringIO()):
                S.run(self.bundle(root / 'bundle'), root / 'live')
            summary = json.loads((root / 'live/summary.json').read_text())
            self.assertEqual(summary['stop'], 'completed')
            self.assertEqual(len(summary['rows']), 2)
            self.assertFalse(any(r['omission_safe_pass'] for r in summary['rows']))


if __name__ == '__main__':
    unittest.main()
