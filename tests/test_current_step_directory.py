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
import current_step as C
import current_step_experiment as E
from test_adaptive_directory_experiment import tree


QUESTION = C.ORIGINAL_LEAD + 'Respect constraints, quotations, cancellations and metadata boundaries.'


class CurrentStepTests(unittest.TestCase):
    def invoke(self, arm, need, confidence=.7, response=None):
        nodes, choices = tree(64)
        for name in ('later', 'third'):
            nodes['n']['children'].append(name)
            nodes['n']['members'].append(name)
            nodes[name] = {'depth': 1, 'children': [], 'members': [name], 'description': 'Mandatory later step'}
            choices[name] = 'Full unchanged later description ' + name
        seen = []
        def call(stage, spec, state):
            seen.append(deepcopy((stage, spec, state)))
            if stage == 'final':
                return response if response is not None else {'answers': {'answer': {
                    'type': 'choice', 'choice': 'cap000', 'confidence': confidence}}}
            return {'answers': {key: {'type': 'noul', 'noul': int(bool(
                {'cap000', 'later', 'third'} & set(nodes[key]['members'])))} for key in spec['questions']}}
        result = C.select(arm, nodes, need, choices, QUESTION, call)
        return result, seen

    def test_only_final_instruction_changes_not_task_pool_or_call_count(self):
        # Explicit current focus appears after later work: do not extract by order.
        need = '之后要做第二项和第三项；当前先做第一项，三项都必须完成。'
        old, old_calls = self.invoke('slim', need)
        new, new_calls = self.invoke('current_step', need)
        self.assertEqual(old, new)
        self.assertEqual(old_calls[:-1], new_calls[:-1])
        self.assertEqual(len(old_calls), len(new_calls))
        self.assertEqual(new_calls[-1][2], {'task': need})
        self.assertEqual(old_calls[-1][1]['questions']['answer']['criteria'],
                         new_calls[-1][1]['questions']['answer']['criteria'])
        self.assertEqual(new_calls[-1][1]['questions']['answer']['instructions'],
                         C.CURRENT_LEAD + QUESTION[len(C.ORIGINAL_LEAD):])
        for trace in new['traces']:
            self.assertTrue({'cap000', 'later', 'third'} <= set(trace['pool']))
        self.assertTrue({'later', 'third'} <= set(new_calls[-1][1]['questions']['answer']['criteria']))

    def test_confidence_gate_unchanged(self):
        for confidence, status in ((.69, 'abstain'), (.7, 'selected')):
            result, _ = self.invoke('current_step', 'Current and later work', confidence)
            self.assertEqual(result['status'], status)
            self.assertEqual(result['confidence'], confidence)

    def test_malformed_or_unoffered_answer_is_not_accepted(self):
        for answer in ({}, {'answers': {'answer': {'type': 'choice', 'choice': 'invented', 'confidence': .99}}}):
            result, _ = self.invoke('current_step', 'Task', response=answer)
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(result['reason'], 'invalid_final_answer')

    def test_estimator_uses_original_question_and_dispatch_does_not_mutate(self):
        spec = {'questions': {'answer': {'type': 'choice', 'instructions': QUESTION, 'criteria': {'x': 'Full'}}}}
        before = deepcopy(spec)
        received = []
        def route(nodes, mode, task, choices, question, call):
            self.assertEqual(question, QUESTION)
            call('final', spec, {'task': task})
            return {'status': 'none'}
        with patch.object(C.A, 'route', route):
            C.select('current_step', {}, 'Task', {}, QUESTION, lambda *args: received.append(args))
        self.assertEqual(spec, before)
        self.assertNotEqual(received[0][1], before)

    def test_unknown_prompt_rejected_before_calls(self):
        with self.assertRaisesRegex(ValueError, 'unknown_final_question'):
            C.select('current_step', {}, 'Task', {}, 'Other prompt', lambda *args: self.fail('No dispatch'))

    def bundle(self, folder):
        folder.mkdir()
        nodes, choices = tree()
        values = {'plan.json': {'arms': E.ARMS, 'final_gate': .7, 'input_sha256': {}, 'source_sha256': {},
            'executable': 'fake', 'max_seconds': 5, 'timeout_seconds': 1, 'max_calls': 8, 'max_known_tokens': 1000},
            'catalog.json': [{'id': k, 'description': v} for k, v in choices.items() if k != 'none'],
            'repaired-nodes.json': nodes, 'question.json': {'question': QUESTION, 'none': 'None'},
            'cases.json': [{'id': 'case', 'need': 'Task', 'expected_ids': ['cap000'], 'pending_ids': [], 'control': False}]}
        for name, value in values.items(): (folder / name).write_text(json.dumps(value))
        return folder

    def test_unknown_send_stops_entire_comparison_without_retry(self):
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

    def test_missing_usage_stops_and_semantic_failures_are_kept(self):
        class Provider:
            def __init__(self, *args, **kwargs): self.calls = []
            def noul(self, spec, state):
                self.calls.append({'outcome': 'completed'})
                return {'answers': {key: {'type': 'noul', 'noul': 0} for key in spec['questions']}}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(E, 'JevHierarchyProvider', Provider), contextlib.redirect_stdout(io.StringIO()):
                E.run(self.bundle(root / 'bundle'), root / 'live')
            summary = json.loads((root / 'live/summary.json').read_text())
            self.assertEqual(summary['stop'], 'budget_or_provider_failure')
            self.assertEqual(summary['rows'][0]['result']['reason'], 'unknown_usage_stop')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(E, 'JevHierarchyProvider', Provider), patch.object(E, 'select', return_value={
                'status': 'none', 'traces': [{'pool': []}]}), contextlib.redirect_stdout(io.StringIO()):
                E.run(self.bundle(root / 'bundle'), root / 'live')
            summary = json.loads((root / 'live/summary.json').read_text())
            self.assertEqual(summary['stop'], 'completed')
            self.assertEqual(len(summary['rows']), 2)
            self.assertFalse(any(r['omission_safe_pass'] for r in summary['rows']))

    def test_fixture_validation_preserves_failed_cases_and_rejects_passed_case_reuse(self):
        cases = json.loads(E.FIXTURES.read_text())['cases']
        prior = [{'id': key, 'need': key, 'expected_ids': ['old'], 'pending_ids': ['later']} for key in E.FAILED]
        results = [{'case': key, 'arm': 'slim', 'omission_safe_pass': False} for key in E.FAILED]
        catalog = [{'id': key} for key in {k for c in cases for k in c['expected_ids'] + c['pending_ids']}]
        frozen = E.validate_cases(prior, results, cases, catalog)
        self.assertEqual(frozen[:2], prior)
        reused = deepcopy(cases)
        reused[0]['need'] = prior[0]['need']
        with self.assertRaisesRegex(ValueError, 'completed_case_reuse'):
            E.validate_cases(prior, results, reused, catalog)
        with self.assertRaisesRegex(ValueError, 'failed_scope_changed'):
            E.validate_cases(prior, results[:-1], cases, catalog)


if __name__ == '__main__':
    unittest.main()
