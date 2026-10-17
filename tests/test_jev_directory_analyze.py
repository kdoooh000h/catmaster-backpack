"""Sanitized receipt replay, using a mocked provider and catalog-only tree."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'benchmarks/directory-depth'))
import jev_directory_analyze as A
import jev_directory_experiment as E

ROWS = [{'id': f'c{n:03}', 'name': f'Full name {n}', 'kind': 'skill', 'mode': 'guidance',
         'description': f'Full private-fixture description {n}. Do not truncate requirements.'} for n in range(129)]
NODES = E.T.build(ROWS, np.tile([1., 0.], (129, 1)))
CASE = {'id': 'case1', 'stratum': 'failed', 'need': 'Original sensitive need stays out of sanitized reports.',
        'acceptable_current_ids': ['c000'], 'pending_groups': [['c001']], 'primary_current_id': 'c000',
        'primary_pending_ids': ['c001']}
RECALL = {'status': 'recalled', 'pool': ['c000', 'c001'], 'shortlist': ['c000'],
          'seconds': .01, 'fresh_retrieval_seconds': .02}


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False))


def alter(path, change):
    data = A.read(path); change(data); write(path, data)


class AnalyzerTests(unittest.TestCase):
    def fixture(self, *, mutate=None, max_calls=80, behavior='completed', short=None):
        class Provider:
            def __init__(self, config, **kwargs):
                self.calls = []
            def noul(self, spec, state):
                if behavior == 'raise':
                    self.calls.append({'outcome': 'unknown_no_replay', 'seconds': .0})
                    raise TimeoutError('unknown_no_replay')
                receipt = {'outcome': 'completed', 'seconds': .0, 'input_tokens': 10, 'output_tokens': 2}
                if behavior == 'missing_usage':
                    receipt.pop('output_tokens')
                self.calls.append(receipt)
                if next(iter(spec['questions'].values()))['type'] == 'noul':
                    return {'answers': {wire: {'type': 'noul', 'noul': .2 if n == 0 else .1999}
                                        for n, wire in enumerate(spec['questions'])}}
                answer = {'answers': {wire: {'type': 'choice', 'choice': 'current' if n == 0 else 'other',
                        'confidence': .7, 'probabilities': {'current': .8 if n == 0 else .1,
                        'partial': .1, 'other': .1 if n == 0 else .8}}
                        for n, wire in enumerate(spec['questions'])}}
                if behavior == 'invalid_answer':
                    next(iter(answer['answers'].values()))['confidence'] = 9
                return answer
        with tempfile.TemporaryDirectory() as temp:
            trial = Path(temp); bundle = trial/'bundle'; bundle.mkdir()
            write(bundle/'catalog.json', ROWS); write(trial/'nodes.json', NODES)
            cases = [CASE, {**CASE, 'id': 'case2', 'stratum': 'new', 'need': 'Another raw private need.'}]
            write(trial/'cases.json', cases)
            for case in cases:
                recall = deepcopy(RECALL)
                if short is not None:
                    recall['shortlist'] = short
                write(trial/(case['id']+'.recall.json'), {'recall': recall})
            plan = {**E.LIMITS, 'executable': 'never-executed', 'max_calls': max_calls, 'locks': {},
                    'index_load_seconds': 1., 'dictionary_load_seconds': 2., 'local_index_startup_seconds': 3.}
            with patch.object(E, 'verify', return_value=(plan, bundle)), patch.object(E, 'JevHierarchyProvider', Provider), contextlib.redirect_stdout(io.StringIO()):
                summary = E.run(trial)
            if mutate:
                mutate(trial)
            # An analyzer must not construct a provider even for replay failures.
            with patch.object(E, 'verify', return_value=(plan, bundle)) as verify, patch.object(E, 'JevHierarchyProvider', side_effect=AssertionError('live_call')):
                result = A.analyze(trial)
                verify.assert_called_once_with(trial)
            return result, summary

    def test_replay_exact_payload_thresholds_aggregation_and_sanitization(self):
        result, summary = self.fixture()
        self.assertEqual(result['stop'], 'completed')
        self.assertEqual(result['completed_rows'], 4)
        self.assertEqual(result['trial_cost']['calls'], 6)
        self.assertEqual(result['trial_cost']['input_tokens'], 60)
        self.assertEqual(result['trial_cost']['output_tokens'], 12)
        self.assertTrue(result['trial_cost']['input_tokens_complete'])
        self.assertTrue(result['trial_cost']['output_tokens_complete'])
        self.assertEqual(result['groups']['all']['paired_completed']['cases'], 2)
        for stratum in ('failed', 'new', 'all'):
            for arm in E.ARMS:
                aggregate = result['groups'][stratum]['arms'][arm]
                self.assertEqual(aggregate['known_positive_accuracy']['rate'], 1.)
                self.assertEqual(aggregate['omission_safe_accuracy']['rate'], 1.)
                self.assertEqual(aggregate['later_group_coverage']['rate'], 1.)
        candidate = next(r for r in result['rows'] if r['arm'] == 'jev_directories')
        original = next(r for r in summary['rows'] if r['arm'] == 'jev_directories')
        self.assertEqual(candidate['warm_selector_seconds'], original['dispatch_seconds'])
        self.assertEqual(candidate['first_omission_stage']['later'], [None])
        text = json.dumps(result)
        for excluded in (CASE['need'], ROWS[0]['description'], 'fit_definitions', 'reserved_tokens', 'spec', 'answers', 'candidates'):
            self.assertNotIn(excluded, text)

    def test_payload_tamper_is_rejected(self):
        def mutate(trial):
            alter(trial/'live/case1--program_shortlist--final.pending.json', lambda d: d['state'].update(task='Tampered task'))
            # Keep reserve consistent, so exact replay payload comparison is decisive.
            alter(trial/'live/case1--program_shortlist--final.pending.json',
                  lambda d: d.update(reserved_tokens=E.token_reserve(d['spec'], d['state'])))
        with self.assertRaisesRegex(ValueError, 'replay_payload_or_stage_mismatch'):
            self.fixture(mutate=mutate)

    def test_receipt_ordinals_pairs_question_maps_and_budget_tamper_rejected(self):
        def duplicate(trial):
            for suffix in ('pending', 'done'):
                alter(trial/f'live/case1--jev_directories--final.{suffix}.json', lambda d: d.update(ordinal=1))
        with self.assertRaisesRegex(ValueError, 'nonsequential_or_duplicate_ordinals'):
            self.fixture(mutate=duplicate)
        def orphan(trial):
            (trial/'live/case1--jev_directories--final.pending.json').unlink()
        with self.assertRaisesRegex(ValueError, 'orphan_outcome_receipt'):
            self.fixture(mutate=orphan)
        def missing_answer(trial):
            alter(trial/'live/case1--jev_directories--directory-1-batch-1.done.json',
                  lambda d: d['answer']['answers'].pop('d1'))
        with self.assertRaisesRegex(ValueError, 'send_after_unknown_or_error|invalid_answer_not_recorded_as_terminal_failure'):
            self.fixture(mutate=missing_answer)
        def cap(trial):
            alter(trial/'live/run-limits.json', lambda d: d.update(max_tokens=0))
        with self.assertRaisesRegex(ValueError, 'send_exceeded_frozen_budget'):
            self.fixture(mutate=cap)

    def test_saved_result_trace_grade_and_timing_tamper_rejected(self):
        for field, value, expected in [('tokens', 99, 'row_accounting_mismatch'),
                                       ('correct_current', False, 'row_grade_mismatch'),
                                       ('selector_seconds', 100., 'row_timing_mismatch')]:
            def mutate(trial, field=field, value=value):
                alter(trial/'live/case1--program_shortlist.json', lambda d: d.update({field: value}))
                alter(trial/'live/summary.json', lambda d: d['rows'][0].update({field: value}))
            with self.assertRaisesRegex(ValueError, expected):
                self.fixture(mutate=mutate)
        def traces(trial):
            alter(trial/'live/case1--program_shortlist.json', lambda d: d['result']['traces'][1].update(pool=[]))
            alter(trial/'live/summary.json', lambda d: d['rows'][0]['result']['traces'][1].update(pool=[]))
        with self.assertRaisesRegex(ValueError, 'replay_result_or_trace_mismatch'):
            self.fixture(mutate=traces)

    def test_omission_stages_keep_current_shortlist_separate_from_later_reservoir(self):
        result, _ = self.fixture(short=['c001'])
        baseline = next(r for r in result['rows'] if r['arm'] == 'program_shortlist')
        self.assertFalse(baseline['omission_safe_pass'])
        self.assertEqual(baseline['first_omission_stage']['current'], 'current_shortlist')
        self.assertEqual(baseline['first_omission_stage']['later'], [None])
        case = {**CASE, 'acceptable_current_ids': ['c128'], 'primary_current_id': 'c128',
                'pending_groups': [['c127']], 'primary_pending_ids': ['c127']}
        omission = A.omissions(case, {'traces': [{'stage': 'directory', 'pool': ['c000']},
                                                {'stage': 'final_pool', 'pool': ['c000']}]}, 'jev_directories')
        self.assertEqual(omission, {'current': 'directory-1', 'later': ['directory-1'],
                                    'primary_current': 'directory-1', 'primary_later': ['directory-1']})

    def test_unknown_and_failed_answers_are_explicit_and_excluded_from_accuracy(self):
        for behavior, reason in [('raise', 'unknown_no_replay'), ('missing_usage', 'unknown_usage_or_outcome'),
                                 ('invalid_answer', 'invalid_fit_answer')]:
            result, _ = self.fixture(behavior=behavior)
            self.assertEqual(result['stop'], reason)
            self.assertEqual(result['completed_rows'], 0)
            self.assertEqual(result['interrupted']['reported_stop'], reason)
            self.assertEqual(result['interrupted']['grade'], 'unobserved')
            self.assertEqual(len(result['unfinished']), 4)
            self.assertIsNone(result['groups']['all']['arms']['program_shortlist']['known_positive_accuracy']['rate'])
        result, _ = self.fixture(behavior='missing_usage')
        self.assertEqual(result['trial_cost']['input_tokens'], 10)
        self.assertFalse(result['trial_cost']['output_tokens_complete'])

    def test_budget_stop_keeps_unpaired_completed_arm_distinct(self):
        result, _ = self.fixture(max_calls=1)
        self.assertEqual(result['stop'], 'budget_stop')
        self.assertEqual(result['completed_rows'], 1)
        self.assertEqual(result['groups']['all']['paired_completed']['cases'], 0)
        self.assertEqual(result['groups']['all']['arms']['program_shortlist']['completed_rows'], 1)
        self.assertEqual(result['groups']['all']['arms']['jev_directories']['completed_rows'], 0)
        self.assertEqual(result['interrupted']['replay_stop'], 'unrecorded_next_send')


if __name__ == '__main__':
    unittest.main()
