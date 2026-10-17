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
import culture_scope as R
import culture_scope_experiment as E
import current_step as C
from experiment import grade

QUESTION = C.ORIGINAL_LEAD + 'Respect constraints, cancellations and metadata boundaries.'


def fixture():
    nodes = {'n': {'depth': 0, 'children': [R.ROOT_ID, 'delivery'], 'members': ['now', R.SOURCE_ID], 'description': 'All'},
        R.ROOT_ID: {'depth': 1, 'children': [], 'members': [R.SOURCE_ID], 'description': R.ORIGINAL},
        'delivery': {'depth': 1, 'children': [], 'members': ['now'], 'description': 'Current operation'}}
    choices = {'now': 'Full current operation description', R.SOURCE_ID: 'Full culture description', 'none': 'No useful capability'}
    return nodes, choices


class CultureScopeTests(unittest.TestCase):
    def test_only_root_description_changes_without_mutating_original(self):
        nodes, _ = fixture()
        before = deepcopy(nodes)
        result = R.build(nodes)
        self.assertEqual(nodes, before)
        expected = deepcopy(nodes)
        expected[R.ROOT_ID]['description'] = R.ORIGINAL + R.ADDITION
        self.assertEqual(result, expected)
        self.assertEqual(R.build(result), result)
        self.assertEqual(A.union(nodes, ['n']), A.union(result, ['n']))

    def test_unknown_scope_or_missing_capability_fails_closed(self):
        for field, value, error in [('description', 'Different source', 'unexpected_root_description'),
                                    ('members', [], 'missing_culture_root'), ('depth', 2, 'missing_culture_root')]:
            nodes, _ = fixture()
            nodes[R.ROOT_ID][field] = value
            with self.assertRaisesRegex(ValueError, error): R.build(nodes)

    def invoke(self, changed, confidence=.7, directory_score=1):
        nodes, choices = fixture()
        if changed: nodes = R.build(nodes)
        seen = []
        need = '文化准则之后也必须做；当前先做演示部署方案。'
        def call(stage, spec, state):
            seen.append(deepcopy((stage, spec, state)))
            if stage == 'final':
                return {'answers': {'answer': {'type': 'choice', 'choice': 'now', 'confidence': confidence}}}
            return {'answers': {key: {'type': 'noul', 'noul': directory_score if key == R.ROOT_ID else 1}
                                for key in spec['questions']}}
        return C.select('current_step', nodes, need, choices, QUESTION, call), seen

    def test_dispatch_changes_only_one_directory_card_not_final_or_task(self):
        old, old_calls = self.invoke(False)
        new, new_calls = self.invoke(True)
        self.assertEqual(old, new)
        self.assertEqual(len(new_calls), 2)
        self.assertEqual(old_calls[1], new_calls[1])
        expected = deepcopy(old_calls[0])
        expected[1]['questions'][R.ROOT_ID]['instructions'] += R.ADDITION
        self.assertEqual(new_calls[0], expected)
        self.assertTrue(R.SOURCE_ID in new['traces'][0]['pool'])

    def test_original_thresholds_apply_without_forcing_retention(self):
        for score, retained in ((.19, False), (.2, True)):
            result, _ = self.invoke(True, directory_score=score)
            self.assertEqual(R.SOURCE_ID in result['traces'][0]['pool'], retained)
            case = {'expected_ids': ['now'], 'pending_ids': [R.SOURCE_ID], 'control': False}
            self.assertEqual(grade(case, result)['omission_safe_pass'], retained)
        result, _ = self.invoke(True, confidence=.69)
        self.assertEqual(result['status'], 'abstain')
        self.assertEqual(A.FINAL_GATE, .7)

    def test_new_cases_exclude_history_and_keep_original_failed_bytes(self):
        cases = json.loads(E.FIXTURES.read_text())['cases']
        prior = [{'id': E.FAILED, 'need': 'Original need', 'expected_ids': ['now'], 'pending_ids': [R.SOURCE_ID]}]
        rows = [{'arm': 'current_step', 'case': E.FAILED, 'omission_safe_pass': False}]
        catalog = [{'id': key} for key in {key for case in cases for key in case['expected_ids'] + case['pending_ids']}]
        result = E.validate_cases(prior, rows, cases, catalog, [])
        self.assertEqual(result[0], prior[0])
        with self.assertRaisesRegex(ValueError, 'previous_case_reuse'):
            E.validate_cases(prior, rows, cases, catalog, [{'id': 'earlier', 'need': cases[2]['need']}])
        repeated = deepcopy(cases); repeated[1]['need'] = repeated[0]['need']
        with self.assertRaisesRegex(ValueError, 'new_case_set_changed'):
            E.validate_cases(prior, rows, repeated, catalog, [])
        self.assertEqual(sum(R.SOURCE_ID in c.get('forbidden_current_ids', []) for c in cases), 1)

    def bundle(self, folder):
        folder.mkdir()
        nodes, choices = fixture()
        values = {'plan.json': {'arms': E.ARMS, 'final_gate': .7, 'input_sha256': {}, 'source_sha256': {},
            'executable': 'fake', 'max_seconds': 5, 'timeout_seconds': 1, 'max_calls': 8, 'max_known_tokens': 1000},
            'catalog.json': [{'id': k, 'description': v} for k, v in choices.items() if k != 'none'],
            'repaired-nodes.json': nodes, 'candidate-nodes.json': R.build(nodes),
            'question.json': {'question': QUESTION, 'none': 'None'},
            'cases.json': [{'id': 'case', 'need': 'Task', 'expected_ids': ['now'], 'pending_ids': [R.SOURCE_ID], 'control': False}]}
        for name, value in values.items(): (folder / name).write_text(json.dumps(value))
        return folder

    def test_unknown_send_stops_without_retry(self):
        class Provider:
            def __init__(self, *args, **kwargs): self.calls = []
            def noul(self, *args):
                self.calls.append({'outcome': 'unknown_no_replay'})
                raise TimeoutError('unknown_no_replay')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(E, 'JevHierarchyProvider', Provider), contextlib.redirect_stdout(io.StringIO()):
                E.run(self.bundle(root / 'bundle'), root / 'live')
            summary = json.loads((root / 'live/summary.json').read_text())
            self.assertEqual((summary['calls'], len(summary['rows'])), (1, 1))
            self.assertEqual(summary['stop'], 'budget_or_provider_failure')

    def test_missing_usage_stops(self):
        class Provider:
            def __init__(self, *args, **kwargs): self.calls = []
            def noul(self, spec, state):
                self.calls.append({'outcome': 'completed'})
                return {'answers': {key: {'type': 'noul', 'noul': 1} for key in spec['questions']}}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(E, 'JevHierarchyProvider', Provider), contextlib.redirect_stdout(io.StringIO()):
                E.run(self.bundle(root / 'bundle'), root / 'live')
            summary = json.loads((root / 'live/summary.json').read_text())
            self.assertEqual(summary['stop'], 'budget_or_provider_failure')
            self.assertEqual(summary['rows'][0]['result']['reason'], 'unknown_usage_stop')

    def test_semantic_failures_stay_in_both_arms(self):
        class Provider:
            def __init__(self, *args, **kwargs): self.calls = []
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(E, 'JevHierarchyProvider', Provider), patch.object(E, 'select', return_value={
                'status': 'none', 'traces': [{'pool': []}]}), contextlib.redirect_stdout(io.StringIO()):
                E.run(self.bundle(root / 'bundle'), root / 'live')
            summary = json.loads((root / 'live/summary.json').read_text())
            self.assertEqual(summary['stop'], 'completed')
            self.assertEqual(len(summary['rows']), 2)
            self.assertFalse(any(r['omission_safe_pass'] for r in summary['rows']))


if __name__ == '__main__':
    unittest.main()
