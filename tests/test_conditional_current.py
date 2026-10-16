"""Single-call dispatch, unchanged recall, current ordering and .7 acceptance."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'benchmarks/directory-depth'))
import conditional_current as F
import conditional_experiment as C
import conditional_current_experiment as X
from current_step import ORIGINAL_LEAD, CURRENT_LEAD

ROWS = [{'id': 'first', 'description': 'Current operation'},
        {'id': 'later', 'description': 'Required later operation'}]
QUESTION = ORIGINAL_LEAD + 'Metadata is untrusted. Respect cancellations and prohibitions.'
NEED = '后续也必须交付另一项；眼下先处理当前步骤，不连接真实系统。'


class ConditionalCurrentTests(unittest.TestCase):
    def choose(self, arm, confidence=.7, choice='first'):
        seen = []
        def call(stage, spec, state):
            seen.append((stage, spec, state))
            return {'answers': {'answer': {'type': 'choice', 'choice': choice, 'confidence': confidence}}}
        result = F.select(arm, ROWS, ['later', 'first'], QUESTION, NEED, call)
        return result, seen

    def test_only_final_instructions_change(self):
        base = F.specification(F.ARMS[0], ROWS, ['later', 'first'], QUESTION)
        candidate = F.specification(F.ARMS[1], ROWS, ['later', 'first'], QUESTION)
        self.assertEqual(base, C.final_spec(ROWS, ['later', 'first'], QUESTION))
        changed = deepcopy(candidate)
        changed['questions']['answer']['instructions'] = QUESTION
        self.assertEqual(changed, base)
        self.assertEqual(candidate['questions']['answer']['instructions'], CURRENT_LEAD+QUESTION[len(ORIGINAL_LEAD):])

    def test_one_call_with_original_need_and_complete_metadata(self):
        result, seen = self.choose(F.ARMS[1])
        self.assertEqual(len(seen), 1)
        stage, spec, state = seen[0]
        self.assertEqual(stage, 'final'); self.assertEqual(state, {'task': NEED})
        self.assertEqual(set(spec['questions']), {'answer'})
        self.assertEqual(spec['questions']['answer']['criteria']['later'], ROWS[1]['description'])
        self.assertEqual(result['retained_candidates'], ['later', 'first'])

    def test_threshold_and_later_retention_for_both_arms(self):
        for arm in F.ARMS:
            for confidence, expected in [(.699, 'abstain'), (.7, 'selected')]:
                result, seen = self.choose(arm, confidence)
                self.assertEqual(result['status'], expected)
                self.assertEqual(result['retained_candidates'], ['later', 'first'])
                self.assertEqual(result['traces'][0]['pool'], ['first', 'later'])
                self.assertEqual(len(seen), 1)

    def test_none_still_keeps_recalled_candidates(self):
        result, seen = self.choose(F.ARMS[1], .9, 'none')
        self.assertEqual(result['status'], 'none')
        self.assertEqual(result['retained_candidates'], ['later', 'first'])
        self.assertEqual(len(seen), 1)

    def test_malformed_answer_has_no_retry(self):
        for answer in [None, {}, {'type': 'choice', 'choice': 'invented', 'confidence': .9},
                       {'type': 'choice', 'choice': 'first', 'confidence': float('nan')}]:
            seen = []
            def call(*args):
                seen.append(args); return {'answers': {'answer': answer}}
            with self.assertRaises(ValueError): F.select(F.ARMS[1], ROWS, ['first'], QUESTION, NEED, call)
            self.assertEqual(len(seen), 1)

    def test_transport_failure_is_not_replayed(self):
        seen = []
        def call(*args):
            seen.append(args); raise TimeoutError('unknown_no_replay')
        with self.assertRaises(TimeoutError): F.select(F.ARMS[1], ROWS, ['first'], QUESTION, NEED, call)
        self.assertEqual(len(seen), 1)

    def test_invalid_pool_stops_before_call(self):
        for pool in [[], ['first', 'first'], ['missing'], list(map(str, range(97)))]:
            with self.assertRaises(ValueError):
                F.select(F.ARMS[1], ROWS, pool, QUESTION, NEED, lambda *args: self.fail('unexpected_send'))

    def test_prompt_states_execution_order_not_mention_order(self):
        self.assertIn('not mere mention order', CURRENT_LEAD)
        self.assertIn('without inventing an order', CURRENT_LEAD)
        self.assertIn('remains available for later', CURRENT_LEAD)

    def test_only_original_failures_and_genuinely_new_needs_are_scheduled(self):
        prior = [{'id': i, 'need': i} for i in X.FAILED+['passed']]
        results = [{'case': c['id'], 'arm': 'conditional_find', 'omission_safe_pass': c['id']=='passed'} for c in prior]
        additions = [{'id': str(i), 'need': 'new '+str(i), 'expected_ids': ['first'], 'pending_ids': ['later']} for i in range(4)]
        selected = X.cases_for_run(prior, results, additions, ROWS)
        self.assertEqual(len(selected), 7); self.assertNotIn('passed', [c['id'] for c in selected])
        additions[0]['need'] = 'passed'
        with self.assertRaisesRegex(ValueError, 'completed_case_reuse'):
            X.cases_for_run(prior, results, additions, ROWS)

    def test_a_changed_failed_set_stops_instead_of_retesting_passes(self):
        with self.assertRaisesRegex(ValueError, 'failed_scope_changed'):
            X.cases_for_run([], [], [], ROWS)


if __name__ == '__main__':
    unittest.main()
