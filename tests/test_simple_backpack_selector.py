from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('simple_backpack_selector',
                                            ROOT / 'benchmarks/simple_backpack_selector.py')
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)
ROWS = [
    {'id': 'broad-package', 'name': 'General preparation', 'kind': 'plugin',
     'mode': S.MODES['plugin'], 'description': 'Prepare a workflow across several stages.'},
    {'id': 'direct-guidance', 'name': 'Specific support', 'kind': 'skill',
     'mode': S.MODES['skill'], 'description': 'Support the requested action and output; do NOT upload files.'},
    {'id': 'later-service', 'name': 'Later service', 'kind': 'mcp',
     'mode': S.MODES['mcp'], 'description': 'Support a later operation. Requires an API key.'},
]
POOL = [r['id'] for r in ROWS]


def response(options, choice='c2', confidence=.8):
    probabilities = {key: 0. for key in options}
    probabilities[choice] = 1.
    return {'answers': {'capability': {'type': 'choice', 'choice': choice,
                                     'confidence': confidence, 'probabilities': probabilities}}}


class SimpleSelectorTests(unittest.TestCase):
    def run_choice(self, choice='c2', confidence=.8, pool=POOL, need='当前做 A，之后必须做 B'):
        calls = []
        def call(stage, spec, state):
            calls.append((stage, spec, state))
            return response(spec['questions']['capability']['criteria'], choice, confidence)
        return S.select(ROWS, pool, need, call), calls

    def test_one_comparative_question_offers_general_and_specialist_without_gold(self):
        result, calls = self.run_choice()
        self.assertEqual(len(calls), 1)
        stage, spec, state = calls[0]
        self.assertEqual(stage, 'final')
        self.assertEqual(set(spec['questions']), {'capability'})
        question = spec['questions']['capability']
        self.assertEqual(question['type'], 'choice')
        self.assertEqual(list(question['criteria']), ['c1', 'c2', 'c3', 'none'])
        self.assertEqual(result['choice'], POOL[1])
        self.assertEqual(set(state), {'task', 'policy'})
        payload = json.dumps({'spec': spec, 'state': state})
        for forbidden in ('expected_ids', 'pending_ids', 'gold', 'current/partial/other'):
            self.assertNotIn(forbidden, payload)
        # One winner can be any kind: metadata is compared, not filtered by type.
        for alias, identifier in zip(['c1', 'c2', 'c3'], POOL):
            self.assertEqual(self.run_choice(alias)[0]['choice'], identifier)

    def test_original_task_metadata_order_and_inputs_are_preserved(self):
        need = {'action': '完整原文 "quoted"', 'output': ['A', 'B'], 'constraints': {'later': 'C'}}
        original_rows, original_need = deepcopy(ROWS), deepcopy(need)
        pool = [POOL[2], POOL[0], POOL[1], POOL[0]]
        spec, state, mapping = S.specification(ROWS, pool, need)
        self.assertEqual(state['task'], need)
        self.assertEqual(list(mapping.values()), [POOL[2], POOL[0], POOL[1], 'none'])
        values = spec['questions']['capability']['criteria']
        for alias, identifier in list(mapping.items())[:-1]:
            row = next(r for r in ROWS if r['id'] == identifier)
            self.assertEqual(json.loads(values[alias]), {k: row[k] for k in ('name', 'kind', 'description')})
        self.assertNotIn('candidates', state)
        state['task']['output'].append('mutated copy')
        self.assertEqual(ROWS, original_rows)
        self.assertEqual(need, original_need)

    def test_raw_point_seven_gate_including_none_and_no_probability_rescaling(self):
        for alias in ['c2', 'none']:
            for confidence, expected in [(.699999, 'abstain'), (.7, 'none' if alias == 'none' else 'selected')]:
                with self.subTest(alias=alias, confidence=confidence):
                    result, _ = self.run_choice(alias, confidence)
                    canonical = 'none' if alias == 'none' else POOL[1]
                    self.assertEqual(result['status'], expected)
                    self.assertEqual(result['choice'], None if expected == 'abstain' else canonical)
                    self.assertEqual(result['raw_choice'], canonical)
                    self.assertEqual(result['confidence'], confidence)
                    self.assertEqual(result['probabilities'][canonical], 1.)
                    self.assertEqual(result['confidence_semantics'], S.CONFIDENCE_SEMANTICS)

    def test_tied_equivalents_can_abstain_and_full_later_reservoir_remains(self):
        spec, _, mapping = S.specification(ROWS, POOL, 'A then B')
        raw = response(mapping, confidence=.6)
        raw['answers']['capability']['probabilities'] = {'c1': .5, 'c2': .5, 'c3': 0., 'none': 0.}
        result = S.validate(raw, mapping, POOL)
        self.assertEqual(result['status'], 'abstain')
        self.assertEqual(result['raw_choice'], POOL[1])
        self.assertEqual(result['probabilities'], {POOL[0]: .5, POOL[1]: .5, POOL[2]: 0., 'none': 0.})
        for alias, confidence in [('c2', .8), ('none', .7), ('c2', .6)]:
            result, _ = self.run_choice(alias, confidence)
            self.assertEqual(result['retained_candidates'], POOL)
            self.assertEqual(result['final_pool_size'], 3)
            self.assertEqual(result['traces'], [{'stage': 'final', 'pool': POOL}])

    def test_existing_grade_contract_observes_current_and_later_without_model_gold(self):
        experiment_spec = importlib.util.spec_from_file_location(
            'selector_grade_contract', ROOT / 'benchmarks/directory-depth/experiment.py')
        experiment = importlib.util.module_from_spec(experiment_spec)
        experiment_spec.loader.exec_module(experiment)
        case = {'expected_ids': [POOL[1]], 'pending_ids': [POOL[2]]}
        result, _ = self.run_choice()
        self.assertTrue(experiment.grade(case, result)['omission_safe_pass'])
        result['traces'][0]['pool'] = POOL[:2]
        self.assertFalse(experiment.grade(case, result)['omission_safe_pass'])
        none, _ = self.run_choice('none', .7)
        self.assertTrue(experiment.grade({'expected_ids': [], 'pending_ids': []}, none)['passed'])

    def test_malformed_answers_options_numbers_and_non_argmax_rejected_without_retry(self):
        spec, _, mapping = S.specification(ROWS, POOL, 'need')
        mutations = [
            lambda r: r.clear(),
            lambda r: r['answers'].update({'extra': {}}),
            lambda r: r['answers'].update({'answer': r['answers'].pop('capability')}),
            lambda r: r['answers'].__setitem__('capability', []),
            lambda r: r['answers']['capability'].__setitem__('type', 'noul'),
            lambda r: r['answers']['capability'].__setitem__('choice', POOL[1]),
            lambda r: r['answers']['capability'].__setitem__('choice', 'c99'),
            lambda r: r['answers']['capability'].__setitem__('choice', []),
            lambda r: r['answers']['capability'].pop('probabilities'),
            lambda r: r['answers']['capability']['probabilities'].pop('c3'),
            lambda r: r['answers']['capability']['probabilities'].update({'fake': 0}),
            lambda r: r['answers']['capability']['probabilities'].update({'c2': .8}),
            lambda r: r['answers']['capability']['probabilities'].update({'c1': .8, 'c2': .2}),
        ]
        for field in ['confidence', 'probability']:
            for value in [True, '0.8', None, -.1, 1.1, 10**1000, float('nan'), float('inf')]:
                def invalid(r, field=field, value=value):
                    answer = r['answers']['capability']
                    (answer if field == 'confidence' else answer['probabilities'])[field if field == 'confidence' else 'c2'] = value
                mutations.append(invalid)
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                calls = []
                def call(*args):
                    calls.append(args)
                    raw = response(mapping)
                    mutate(raw)
                    return raw
                with self.assertRaises(ValueError):
                    S.select(ROWS, POOL, 'need', call)
                self.assertEqual(len(calls), 1)
        with self.assertRaisesRegex(ValueError, 'invalid_option_mapping'):
            S.validate(response(mapping), {**mapping, 'c1': 'fake'}, POOL)

    def test_provider_error_propagates_once(self):
        calls = []
        def fail(*args):
            calls.append(args)
            raise RuntimeError('unknown outcome')
        with self.assertRaisesRegex(RuntimeError, 'unknown outcome'):
            S.select(ROWS, POOL, 'need', fail)
        self.assertEqual(len(calls), 1)

    def test_invalid_catalog_or_pool_stops_before_call_without_silent_drops(self):
        invalid_rows = []
        for field, value in [('id', 'none'), ('kind', 'tool'), ('mode', 'installed'), ('name', ''), ('description', 5)]:
            rows = deepcopy(ROWS)
            rows[0][field] = value
            invalid_rows.append(rows)
        invalid_rows.extend([ROWS + [ROWS[0]], [{k: v for k, v in ROWS[0].items() if k != 'mode'}], None])
        for rows, pool in [(r, POOL) for r in invalid_rows] + [(ROWS, p) for p in [[], ['missing'], POOL + ['missing'], ['none'], [None], [True], 'broad-package']]:
            with self.subTest(rows=rows, pool=pool), self.assertRaises(ValueError):
                S.select(rows, pool, 'need', lambda *a: self.fail('unexpected call'))

    def test_actual_canonical_limit_is_128_and_overflow_never_shortlists(self):
        rows = [{**ROWS[n % 3], 'id': f'id-{n}', 'name': f'Name {n}'} for n in range(129)]
        pool = [r['id'] for r in rows]
        seen = []
        def call(stage, spec, state):
            seen.append(spec)
            return response(spec['questions']['capability']['criteria'], 'c128', .7)
        result = S.select(rows, pool[:128] * 2, 'need', call)
        self.assertEqual(result['choice'], pool[127])
        self.assertEqual(result['final_pool_size'], 128)
        self.assertEqual(result['retained_candidates'], pool[:128])
        self.assertEqual(len(seen[0]['questions']['capability']['criteria']), 129)
        with self.assertRaisesRegex(ValueError, 'final_pool_limit'):
            S.select(rows, pool, 'need', lambda *a: self.fail('unexpected call'))


if __name__ == '__main__':
    unittest.main()
