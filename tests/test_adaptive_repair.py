import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmarks/directory-depth'))
import adaptive_repair as R
import repair_experiment as E


def fixture():
    # Over both early-stop pool limits, so directory two must be evaluated.
    members = ['target', 'later'] + ['other' + str(i) for i in range(48)]
    nodes = {'n': {'depth': 0, 'children': ['broad'], 'members': members, 'description': 'All'},
             'broad': {'depth': 1, 'children': ['wanted', 'unrelated'], 'members': members, 'description': 'Broad'},
             'wanted': {'depth': 2, 'children': [], 'members': members[:2], 'description': 'Short excerpt'},
             'unrelated': {'depth': 2, 'children': [], 'members': members[2:], 'description': 'Other'}}
    choices = {key: 'Full description for ' + key for key in members} | {'none': 'No task'}
    return nodes, choices


def scored(scores):
    return {'answers': {key: {'type': 'noul', 'noul': value} for key, value in scores.items()}}


class AdaptiveRepairTests(unittest.TestCase):
    def test_boundary_review_recovers_whole_branch_and_keeps_final_gate(self):
        nodes, choices = fixture()
        calls = []
        def call(stage, spec, state):
            calls.append(stage)
            if stage == 'directory-0': return scored({'broad': .9})
            if stage == 'directory-1': return scored({'wanted': .27, 'unrelated': .01})
            if stage == 'boundary-1':
                self.assertEqual(set(spec['questions']), {'wanted'})
                self.assertIn('Full description for target', json.dumps(spec))
                self.assertIn('Full description for later', json.dumps(spec))
                self.assertNotIn('.27', json.dumps(state))
                return scored({'wanted': .8})
            self.assertEqual(stage, 'final')
            self.assertEqual(set(spec['questions']['answer']['criteria']), {'target', 'later', 'none'})
            return {'answers': {'answer': {'type': 'choice', 'choice': 'target', 'confidence': .69}}}
        result = R.route(nodes, 'First current then later.', choices, 'Select', call, review=True)
        self.assertEqual(result['status'], 'abstain')
        self.assertEqual(result['traces'][-1]['recovered'], ['wanted'])
        self.assertEqual(result['boundary_review_calls'], 1)
        self.assertEqual(len(calls), 4)

    def test_nonboundary_is_not_retried(self):
        nodes, choices = fixture()
        calls = []
        def call(stage, *args):
            calls.append(stage)
            return scored({'broad': .01})
        result = R.route(nodes, 'No request', choices, 'Select', call, review=True)
        self.assertEqual(result['status'], 'none')
        self.assertEqual(calls, ['directory-0'])

    def test_second_boundary_does_not_spend_another_review(self):
        nodes, choices = fixture()
        calls = []
        def call(stage, *args):
            calls.append(stage)
            if stage == 'directory-0': return scored({'broad': .1})
            if stage == 'boundary-0': return scored({'broad': .9})
            if stage == 'directory-1': return scored({'wanted': .27, 'unrelated': .01})
            self.fail('unexpected extra request')
        result = R.route(nodes, 'Task', choices, 'Select', call, review=True)
        self.assertEqual(calls, ['directory-0', 'boundary-0', 'directory-1'])
        self.assertEqual(result['boundary_review_calls'], 1)
        self.assertEqual(result['traces'][-1]['review_skipped'], 'one_review_budget_spent')

    def test_unknown_review_never_continues_to_final(self):
        nodes, choices = fixture()
        calls = []
        def call(stage, *args):
            calls.append(stage)
            if stage == 'directory-0': return scored({'broad': .9})
            if stage == 'directory-1': return scored({'wanted': .27, 'unrelated': .01})
            raise TimeoutError('unknown_no_replay')
        result = R.route(nodes, 'Task', choices, 'Select', call, review=True)
        self.assertEqual(result['reason'], 'unknown_no_replay')
        self.assertEqual(calls, ['directory-0', 'directory-1', 'boundary-1'])

    def test_malformed_scores_do_not_enter_review(self):
        nodes, choices = fixture()
        calls = []
        def call(stage, *args):
            calls.append(stage)
            return scored({'broad': float('nan')})
        result = R.route(nodes, 'Task', choices, 'Select', call, review=True)
        self.assertEqual(result['reason'], 'invalid_directory_scores')
        self.assertEqual(len(calls), 1)

    def test_review_payload_limit_is_visible_and_never_truncates(self):
        nodes, choices = fixture()
        choices['target'] = 'long ' * 4000
        calls = []
        def call(stage, *args):
            calls.append(stage)
            if stage == 'directory-0': return scored({'broad': .9})
            return scored({'wanted': .27, 'unrelated': .01})
        result = R.route(nodes, 'Task', choices, 'Select', call, review=True)
        self.assertEqual(result['traces'][-1]['review_skipped'], 'review_payload_limit')
        self.assertEqual(result['status'], 'none')
        self.assertEqual(len(calls), 2)

    def test_runner_keeps_semantic_failures_and_stops_on_unknown(self):
        class Provider:
            def __init__(self, *args, **kwargs): self.calls = []
            def noul(self, *args):
                self.calls.append({'outcome': 'unknown_no_replay'})
                raise TimeoutError('unknown_no_replay')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); bundle = root / 'bundle'; bundle.mkdir()
            nodes, choices = fixture()
            data = {'plan.json': {'arms': E.ARMS, 'final_gate': .7, 'source_sha256': {}, 'input_sha256': {},
                    'executable': 'fake', 'max_seconds': 5, 'timeout_seconds': 1, 'max_calls': 20, 'max_known_tokens': 1000},
                    'nodes.json': nodes, 'repaired-nodes.json': nodes,
                    'catalog.json': [{'id': k, 'description': v} for k, v in choices.items() if k != 'none'],
                    'cases.json': [{'id': 'case', 'need': 'Task', 'expected_ids': ['target'], 'pending_ids': [], 'control': False}],
                    'question.json': {'question': 'Select', 'none': 'None'}}
            for name, value in data.items(): (bundle / name).write_text(json.dumps(value))
            with patch.object(E, 'JevHierarchyProvider', Provider), contextlib.redirect_stdout(io.StringIO()):
                E.run(bundle, root / 'live')
            summary = json.loads((root / 'live/summary.json').read_text())
            self.assertEqual(summary['calls'], 1)
            self.assertEqual(summary['stop'], 'budget_or_provider_failure')
            self.assertEqual(len(summary['rows']), 1)
            self.assertFalse(summary['rows'][0]['omission_safe_pass'])
            self.assertEqual(len(list((root / 'live').glob('*.error.json'))), 1)


if __name__ == '__main__':
    unittest.main()
