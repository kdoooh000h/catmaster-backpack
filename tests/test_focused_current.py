from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmarks/directory-depth'))
import focused_current as F
from semantic_recall import SemanticIndex
from test_semantic_recall import ROWS, VECTORS, answer


class Dictionary:
    def matches(self, need, *, vocabulary):
        return []


class FocusedCurrentTests(unittest.TestCase):
    def index(self, vectors=VECTORS):
        dense = SemanticIndex(ROWS, vectors, lambda qs: np.array([[1, 0]] * len(qs)), query_prefix='')
        return F.FocusedIndex(ROWS, Dictionary(), dense)

    def test_ordering_hint_is_separate_from_raw_task(self):
        need = '先排查故障，读取日志；之后整理 Word 文档。现在不要发布。'
        self.assertEqual(F.current_hint(need), '先排查故障，读取日志')
        self.assertEqual(F.current_hint('先查地址，再查路线'), '先查地址，再查路线')
        self.assertEqual(F.current_hint('之后再处理'), '之后再处理')

    def test_reservoir_preserved_and_allowed_kind_filters_before_ranking(self):
        index = self.index()
        try:
            result = index.search('Current operation', {'pool': ['later'], 'catalog_count': 2, 'seconds': 0,
                                  'hard_conditions': {'allowed_kinds': ['skill']}}, per_kind=1, per_route=1, shortlist_size=1)
            self.assertIn('later', result['pool'])
            self.assertEqual(result['shortlist'], ['now'])
            self.assertNotIn('tool', result['pool'])
        finally:
            index.close()

    def test_dense_and_fused_boundary_ties_expand_without_silent_cut(self):
        index = self.index(np.array([[1, 0]] * len(ROWS)))
        try:
            result = index.search('未知', {'pool': ['later'], 'catalog_count': 4, 'seconds': 0},
                                  per_kind=1, per_route=1, max_reservoir=2)
            self.assertEqual(set(result['shortlist']), {r['id'] for r in ROWS})
            self.assertEqual(result['status'], 'widen_required')
        finally:
            index.close()

    def test_shared_definitions_full_metadata_and_only_shortlist_is_judged(self):
        need = 'Current operation，之后 Later operation；不发布'
        recall = {'pool': ['now', 'later', 'legacy'], 'shortlist': ['now']}
        calls = []
        def call(stage, spec, state):
            calls.append((spec, state))
            return {'answers': {'c1': answer(confidence=.7)}}
        result = F.select(ROWS, recall, need, call)
        spec, state = calls[0]
        self.assertEqual(state['task'], need)
        self.assertEqual(state['fit_definitions'], F.I.CRITERIA)
        self.assertEqual(spec['questions']['c1']['instructions']['candidate']['description'], ROWS[0]['description'])
        self.assertNotIn('candidates', state)
        self.assertEqual(result['choice'], 'now')
        self.assertEqual(result['retained_candidates'], recall['pool'])
        self.assertEqual(result['traces'][0]['pool'], ['now'])
        self.assertEqual(result['traces'][1]['pool'], recall['pool'])

    def test_gate_does_not_accept_partial_or_subthreshold_answers(self):
        for choice, confidence in [('current', .699), ('partial', 1), ('other', 1)]:
            result = F.select(ROWS, {'pool': ['now', 'later'], 'shortlist': ['now']}, 'Current operation',
                              lambda *args: {'answers': {'c1': answer(choice, confidence)}})
            self.assertEqual(result['status'], 'abstain')
        with self.assertRaises(ValueError):
            F.select(ROWS, {'pool': ['now'], 'shortlist': ['later']}, 'Current operation', lambda *args: {})


if __name__ == '__main__':
    unittest.main()
