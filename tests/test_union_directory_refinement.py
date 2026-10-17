from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'benchmarks/directory-depth'))
sys.path.insert(0, str(BASE / 'benchmarks'))
import jev_taxonomy_build as B
import union_directory_refinement as U


def fixture(groups, *, unknown=(), split=()):
    taxonomy = {'version': 1, 'roots': [
        {'id': root, 'name': root, 'description': f'Authored {root} scope.',
         'children': [{'id': leaf, 'name': leaf, 'description': f'Authored {leaf} scope.'}
                      for leaf in ('a', 'b')]}
        for root in groups]}
    numbers = sorted(set(unknown).union(*(set(members) for members in groups.values())))
    rows = [{'id': f'entity/{number:03}', 'name': f'Entity {number}', 'kind': 'plugin',
             'description': 'Explicit catalog metadata.', 'publisher_labels': ['Weak label'],
             'task': 'SECRET_TASK', 'gold': 'SECRET_GOLD', 'topics': ['SECRET_TOPIC']}
            for number in numbers]
    assignments = {}
    for row, number in zip(rows, numbers):
        supported = [root for root, members in groups.items() if number in members]
        assignments[row['id']] = {
            'id': row['id'], 'primary_root': supported[0] if supported else B.UNRESOLVED,
            'supported_roots': supported, 'global_unknown': number in unknown,
            'uncertain': False, 'leaves': {root: ['b'] if root in split else []
                                          for root in supported},
            'primary': {'preserve': True}, 'multi': {'preserve': True},
            'cross': {'preserve': True},
            'leaf': {root: {'choice': 'b', 'confidence': .9} for root in supported if root in split},
            'deferred_roots': [root for root in supported if root not in split]}
    nodes = B._build(B._taxonomy(taxonomy), assignments, [row['id'] for row in rows], split)
    B.validate(nodes, rows)
    return rows, nodes, assignments, taxonomy


class MockJev:
    def __init__(self, confidence=.9, selected='a'):
        self.calls, self.confidence, self.selected = [], confidence, selected

    def __call__(self, stage, spec, state):
        self.calls.append(deepcopy((stage, spec, state)))
        return {'answers': {wire: {
            'type': 'choice', 'choice': self.selected, 'confidence': self.confidence,
            'probabilities': {key: float(key == self.selected) for key in question['criteria']}}
            for wire, question in spec['questions'].items()}}


class UnionDirectoryRefinementTests(unittest.TestCase):
    def test_over_limit_union_refines_all_selected_small_roots_without_mutation(self):
        data = fixture({'software': range(80), 'data': range(80, 160), 'writing': range(5)})
        before, model = deepcopy(data), MockJev()
        result = U.prepare(*data, ['data', 'software'], model)
        self.assertEqual(result['selected_union_count'], 160)
        self.assertEqual(result['refined_roots'], ['software', 'data'])
        self.assertEqual(result['split_roots'], ['software', 'data'])
        self.assertEqual(sum(len(spec['questions']) for _, spec, _ in model.calls), 160)
        self.assertTrue(all(len(spec['questions']) <= 32 for _, spec, _ in model.calls))
        for identifier, original in data[2].items():
            assignment = result['assignments'][identifier]
            for field in ('primary_root', 'supported_roots', 'global_unknown', 'primary', 'multi', 'cross'):
                self.assertEqual(assignment[field], original[field])
            for root in ('software', 'data'):
                if root in assignment['supported_roots']:
                    self.assertEqual(assignment['leaves'][root], ['a'])
                    self.assertNotIn(root, assignment['deferred_roots'])
                    self.assertIn(['n', B._root_id(root), B._leaf_id(root, 'a')], assignment['leaf_paths'])
        self.assertEqual(result['nodes'][B._root_id('writing')]['children'], [])
        self.assertEqual(B.validate(result['nodes'], data[0])['candidate_count'], 160)
        self.assertEqual(data, before)

    def test_union_at_128_is_exact_noop_with_zero_calls_and_independent_copies(self):
        data, model = fixture({'software': range(64), 'data': range(64, 128)}), MockJev()
        result = U.prepare(*data, ['software', 'data'], model)
        self.assertEqual(result['selected_union_count'], 128)
        self.assertEqual(result['nodes'], data[1])
        self.assertEqual(result['assignments'], data[2])
        self.assertIsNot(result['nodes'], data[1])
        self.assertIsNot(result['assignments'], data[2])
        self.assertEqual(result['refined_roots'], [])
        self.assertEqual(result['calls'], [])
        self.assertEqual(model.calls, [])

    def test_overlapping_memberships_use_unique_union_not_sum(self):
        data, model = fixture({'software': range(80), 'data': range(40, 120)}), MockJev()
        result = U.prepare(*data, ['data', 'software', 'software'], model)
        self.assertEqual(result['selected_union_count'], 120)
        self.assertEqual(result['refined_roots'], [])
        self.assertEqual(model.calls, [])
        self.assertEqual(B.validate(result['nodes'], data[0])['leaf_memberships'], 160)

    def test_selected_global_unknown_contributes_to_union_and_all_unknown_paths_survive(self):
        data = fixture({'software': range(128)}, unknown=(0, 128))
        model = MockJev(confidence=.49)
        result = U.prepare(*data, ['software', B.UNKNOWN], model)
        self.assertEqual(result['selected_union_count'], 129)
        self.assertEqual(result['refined_roots'], ['software'])
        self.assertEqual(result['nodes'][B.UNKNOWN], data[1][B.UNKNOWN])
        for number in (0, 128):
            self.assertIn(['n', B.UNKNOWN], result['assignments'][f'entity/{number:03}']['leaf_paths'])
        assignment = result['assignments']['entity/000']
        self.assertEqual(assignment['leaves']['software'], ['a', B.UNRESOLVED_LEAF])
        self.assertEqual(assignment['leaf']['software']['confidence'], .49)
        self.assertTrue(assignment['uncertain'])
        self.assertIn(['n', B._root_id('software'), B._unknown_id('software')], assignment['leaf_paths'])
        B.validate(result['nodes'], data[0])

    def test_existing_split_roots_count_toward_union_and_are_preserved_without_reclassification(self):
        data = fixture({'software': range(60), 'data': range(60, 120),
                        'writing': range(120, 140)}, split=('writing',))
        model = MockJev()
        result = U.prepare(*data, ['writing', 'software', 'data'], model)
        self.assertEqual(result['selected_union_count'], 140)
        self.assertEqual(result['refined_roots'], ['software', 'data'])
        self.assertEqual(result['split_roots'], ['software', 'data', 'writing'])
        for node_id in (B._root_id('writing'), B._leaf_id('writing', 'b')):
            self.assertEqual(result['nodes'][node_id], data[1][node_id])
        for number in range(120, 140):
            self.assertEqual(result['assignments'][f'entity/{number:03}'], data[2][f'entity/{number:03}'])
        for _, spec, _ in model.calls:
            self.assertNotIn('writing', {q['instructions']['root'] for q in spec['questions'].values()})
        B.validate(result['nodes'], data[0])

    def test_payloads_are_only_builder_leaf_metadata_and_deterministic(self):
        data, model = fixture({'software': range(65), 'data': range(65, 129)}), MockJev()
        first = U.prepare(*data, ['software', 'data'], model, batch_size=7)
        reversed_data = (list(reversed(data[0])), data[1], data[2], data[3])
        second = U.prepare(*reversed_data, ['data', 'software'], MockJev(), batch_size=7)
        self.assertEqual(first, second)
        for stage, spec, state in model.calls:
            self.assertRegex(stage, r'^union-leaf-[1-9][0-9]*$')
            self.assertLessEqual(len(spec['questions']), 7)
            self.assertEqual(set(state), {'policy', 'candidates', 'roots'})
            for candidate in state['candidates'].values():
                self.assertEqual(set(candidate), {'name', 'kind', 'description', 'publisher_labels'})
            payload = json.dumps((spec, state))
            self.assertNotIn('SECRET_', payload)
            self.assertNotIn('entity/', payload)
            items = [(question['instructions']['candidate'], question['instructions']['root'])
                     for question in spec['questions'].values()]
            expected = B._specification('leaf', items, state['candidates'], B._taxonomy(data[3]))
            self.assertEqual((spec, state), expected[:2])

    def test_unknown_choice_is_not_duplicated_and_half_confidence_has_no_fallback(self):
        data = fixture({'software': range(129)})
        for selected, confidence, leaves in ((B.UNRESOLVED_LEAF, .2, [B.UNRESOLVED_LEAF]),
                                              ('a', .5, ['a'])):
            with self.subTest(selected=selected):
                result = U.prepare(*data, ['software'], MockJev(confidence, selected))
                self.assertEqual(result['assignments']['entity/000']['leaves']['software'], leaves)
                B.validate(result['nodes'], data[0])

    def test_callback_failure_and_invalid_answer_propagate_without_retry_or_input_edits(self):
        data = fixture({'software': range(129)})
        before = deepcopy(data)
        for malformed in (False, True):
            calls = []
            def call(*args):
                calls.append(args)
                if malformed:
                    return {'answers': {}}
                raise TimeoutError('unknown_no_retry')
            with self.subTest(malformed=malformed), self.assertRaises(ValueError if malformed else TimeoutError):
                U.prepare(*data, ['software'], call)
            self.assertEqual(len(calls), 1)
            self.assertEqual(data, before)


if __name__ == '__main__':
    unittest.main()
