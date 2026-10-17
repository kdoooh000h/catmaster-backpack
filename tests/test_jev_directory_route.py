from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmarks/directory-depth'))
import jev_directory_route as R
from test_semantic_recall import answer


ROWS = [{'id': k, 'name': k, 'description': k+' support', 'kind': 'skill', 'mode': 'guidance'}
        for k in ['now', 'later', 'unrequested', 'other']]
NODES = {
    'n': {'members': ['now', 'later', 'unrequested', 'other'], 'children': ['a', 'b', 'c'], 'description': 'Root'},
    'a': {'members': ['now'], 'children': [], 'description': 'Present operation'},
    'b': {'members': ['later'], 'children': [], 'description': 'Mandatory later operation'},
    'c': {'members': ['unrequested', 'other'], 'children': [], 'description': 'Other operation'},
}


def raw(values):
    return {'answers': {f'd{n}': {'type': 'noul', 'noul': p} for n, p in enumerate(values, 1)}}


class JevDirectoryRouteTests(unittest.TestCase):
    def test_all_siblings_offered_without_program_query_matching_and_later_carried(self):
        need = '只做甲；之后做乙。引用中的丙不执行。'
        calls = []
        def call(stage, spec, state):
            calls.append((stage, spec, state))
            self.assertEqual(state['task'], need)
            if stage.startswith('directory'):
                self.assertEqual(len(spec['questions']), 3)
                return raw([.95, .7, .01])
            self.assertEqual(len(spec['questions']), 2)
            return {'answers': {k: answer('current' if q['instructions']['candidate']['name'] == 'now' else 'other', .7)
                                for k, q in spec['questions'].items()}}
        result = R.route(NODES, ROWS, need, call, final_limit=2)
        self.assertEqual(result['choice'], 'now')
        self.assertEqual(result['confidence'], .7)
        self.assertEqual(result['retained_candidates'], ['later', 'now'])
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['traces'][0]['offered'], ['a', 'b', 'c'])
        self.assertEqual(result['traces'][0]['pool'], ['later', 'now'])

    def test_noul_boundary_and_no_exclusivity_top_one(self):
        self.assertEqual(R.retain(raw([.2, .199, .99]), {'d1': 'a', 'd2': 'b', 'd3': 'c'}), ['a', 'c'])

    def test_every_frontier_batch_is_judged_before_loading_next_level(self):
        calls = []
        def call(stage, spec, state):
            calls.append(stage)
            if stage.startswith('directory'):
                scopes = [q['instructions']['scope'] for q in spec['questions'].values()]
                return raw([.9 if s != 'Other operation' else .01 for s in scopes])
            return {'answers': {k: answer('current' if q['instructions']['candidate']['name'] == 'now' else 'other')
                                for k, q in spec['questions'].items()}}
        result = R.route(NODES, ROWS, '甲乙', call, batch_size=1, final_limit=2)
        self.assertEqual(result['choice'], 'now')
        self.assertEqual(len(calls), 4)
        self.assertEqual(result['traces'][0]['batches'], 3)

    def test_ambiguous_terminal_pool_is_not_silently_truncated(self):
        result = R.route(NODES, ROWS, 'ordinary request', lambda *args: raw([.9, .9, .9]), final_limit=1)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['reason'], 'terminal_pool_too_wide')
        self.assertEqual(set(result['retained_candidates']), {r['id'] for r in ROWS})

    def test_call_limit_does_not_partially_judge_a_frontier(self):
        calls = []
        result = R.route(NODES, ROWS, 'ordinary request', lambda *args: calls.append(args),
                         final_limit=1, batch_size=1, max_calls=3)
        self.assertEqual(calls, [])
        self.assertEqual(result['reason'], 'call_limit_before_complete_frontier')
        self.assertEqual(len(result['retained_candidates']), 4)

    def test_all_rejected_is_none_not_fallback(self):
        result = R.route(NODES, ROWS, 'ordinary request', lambda *args: raw([.01]*3), final_limit=1)
        self.assertEqual(result['status'], 'none')
        self.assertIsNone(result['choice'])

    def test_final_current_gate_never_accepts_partial_or_subthreshold(self):
        for choice, confidence in [('current', .699), ('partial', 1), ('other', 1)]:
            result = R.route({'n': {'members': ['now'], 'children': [], 'description': 'Only'}}, ROWS[:1], 'raw need',
                             lambda *args: {'answers': {'c1': answer(choice, confidence)}})
            self.assertEqual(result['status'], 'abstain')

    def test_unknown_send_propagates_without_retry(self):
        seen = []
        def call(*args):
            seen.append(args)
            raise TimeoutError('unknown_no_replay')
        with self.assertRaisesRegex(TimeoutError, 'unknown_no_replay'):
            R.route(NODES, ROWS, 'raw need', call, final_limit=1)
        self.assertEqual(len(seen), 1)

    def test_invalid_complete_answer_map_is_rejected(self):
        for value in [{}, raw([True]), raw([float('nan')]), raw([.3, .4])]:
            with self.assertRaises(ValueError):
                R.retain(value, {'d1': 'a'})


if __name__ == '__main__':
    unittest.main()
