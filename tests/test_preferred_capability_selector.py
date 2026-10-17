from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'benchmarks'), str(ROOT/'benchmarks/directory-depth')]
import preferred_capability_selector as P

ROWS = [
    {'id': 'a', 'name': 'Specialist', 'kind': 'plugin',
     'description': 'Supports the current output; no uploads.',
     'mode': P.S.MODES['plugin']},
    {'id': 'b', 'name': 'Related specialist', 'kind': 'skill',
     'description': 'Supports a similar task.', 'mode': P.S.MODES['skill']},
    {'id': 'later', 'name': 'Future service', 'kind': 'mcp',
     'description': 'Supports later work, requires credentials.', 'mode': P.S.MODES['mcp']},
]
POOL = [r['id'] for r in ROWS]
NEED = '当前做 A，不上传；之后必须做 B。'


def rank(choice='c1', confidence=.51):
    probs = {'c1': .51, 'c2': .34, 'c3': .09, 'none': .06}
    if choice == 'none':
        probs = {'c1': .2, 'c2': .1, 'c3': .1, 'none': .6}
    return {'answers': {'capability': {'type': 'choice', 'choice': choice,
            'confidence': confidence, 'probabilities': probs}}}


def fit(choice='current', confidence=.9):
    probs = {key: .025 for key in P.I.CRITERIA}; probs[choice] = .95
    return {'answers': {'c1': {'type': 'choice', 'choice': choice,
            'confidence': confidence, 'probabilities': probs}}}


class PreferredSelectorTests(unittest.TestCase):
    def run_route(self, ranked=None, fitted=None):
        calls = []
        def call(stage, spec, state):
            calls.append((stage, deepcopy(spec), deepcopy(state)))
            return deepcopy((ranked or rank()) if stage == 'rank' else (fitted or fit()))
        return P.select(ROWS, POOL, NEED, call), calls

    def test_low_ranking_certainty_uses_highest_probability_with_independent_gate(self):
        result, calls = self.run_route()
        self.assertEqual(result['choice'], 'a')
        self.assertEqual(result['ranking_confidence'], .51)
        self.assertEqual(result['confidence'], .9)
        self.assertEqual([c[0] for c in calls], ['rank', 'final'])
        self.assertEqual(len(calls[1][1]['questions']), 1)
        self.assertEqual(result['ranking_probabilities']['a'], .51)

    def test_final_gate_boundary_and_partial_other_rejection_no_runner_up_retry(self):
        for label, conf, status in [('current', .699999, 'abstain'), ('current', .7, 'selected'),
                                    ('partial', .99, 'abstain'), ('other', .99, 'abstain')]:
            with self.subTest(label=label, confidence=conf):
                result, calls = self.run_route(fitted=fit(label, conf))
                self.assertEqual(result['status'], status)
                self.assertEqual(len(calls), 2)
                self.assertEqual(result['verified_candidate'], 'a')
                self.assertEqual(result['choice'], 'a' if status == 'selected' else None)
                self.assertEqual(result['retained_candidates'], POOL)

    def test_high_rank_confidence_cannot_bypass_suitability(self):
        result, calls = self.run_route(ranked=rank(confidence=.99), fitted=fit('other', .99))
        self.assertEqual(result['status'], 'abstain')
        self.assertEqual(len(calls), 2)

    def test_none_leader_does_not_force_a_capability_or_claim_empty_catalog(self):
        result, calls = self.run_route(ranked=rank('none', .6))
        self.assertEqual(result['status'], 'abstain')
        self.assertEqual(result['reason'], 'none_ranked_first')
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['retained_candidates'], POOL)

    def test_tied_maximum_uses_provider_choice_and_no_new_tie_break_rule(self):
        raw = rank('c2', .3)
        raw['answers']['capability']['probabilities'] = {'c1': .5, 'c2': .5, 'c3': 0., 'none': 0.}
        result, _ = self.run_route(ranked=raw)
        self.assertEqual(result['choice'], 'b')

    def test_raw_need_and_selected_metadata_preserved_without_competitor_repetition(self):
        before = deepcopy(ROWS)
        result, calls = self.run_route()
        question = calls[1][1]['questions']['c1']
        self.assertEqual(question['instructions']['candidate'],
                         {k: ROWS[0][k] for k in ['name', 'kind', 'description']})
        self.assertEqual(calls[1][2]['task'], NEED)
        self.assertEqual(calls[1][2]['policy'], P.I.POLICY)
        self.assertEqual(result['retained_candidates'], POOL)
        self.assertEqual(ROWS, before)

    def test_invalid_rank_rejected_before_qualification(self):
        for mutation in ['fake', 'nonmax', 'nan', 'extra']:
            raw = rank()
            answer = raw['answers']['capability']
            if mutation == 'fake': answer['choice'] = 'missing'
            if mutation == 'nonmax': answer['choice'] = 'c2'
            if mutation == 'nan': answer['confidence'] = float('nan')
            if mutation == 'extra': raw['answers']['extra'] = {}
            calls = []
            def call(*args):
                calls.append(args); return raw
            with self.assertRaises(ValueError): P.select(ROWS, POOL, NEED, call)
            self.assertEqual(len(calls), 1)

    def test_invalid_fit_or_unknown_outcome_propagates_without_retry(self):
        for failure in ['timeout', 'wrong_id', 'invalid_probability']:
            calls = []
            def call(stage, spec, state):
                calls.append(stage)
                if stage == 'rank': return rank()
                if failure == 'timeout': raise TimeoutError('unknown_no_replay')
                raw = fit()
                if failure == 'wrong_id': raw['answers']['c2'] = raw['answers'].pop('c1')
                else: raw['answers']['c1']['probabilities']['current'] = True
                return raw
            with self.assertRaises((ValueError, TimeoutError)): P.select(ROWS, POOL, NEED, call)
            self.assertEqual(calls, ['rank', 'final'])


if __name__ == '__main__':
    unittest.main()
