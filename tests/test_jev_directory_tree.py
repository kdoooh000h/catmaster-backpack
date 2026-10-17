"""Catalog-only partition invariants; no model, downloads or query vectors."""
import copy
import importlib.util
import inspect
from pathlib import Path
import unittest

import numpy as np

PATH = Path(__file__).resolve().parents[1] / 'benchmarks/directory-depth/jev_directory_tree.py'
SPEC = importlib.util.spec_from_file_location('jev_directory_tree', PATH)
T = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(T)


def fixture(count=129):
    rows = [{'id': f'cap{i:05}', 'name': f'Original capability {i}',
             'description': 'photography portrait lighting' if i % 2 else 'database query migration'}
            for i in range(count)]
    vectors = np.random.default_rng(13).normal(size=(count, 8))
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    return rows, vectors


class JevDirectoryTreeTests(unittest.TestCase):
    def test_complete_disjoint_and_bounded(self):
        rows, vectors = fixture()
        nodes = T.build(rows, vectors, fanout=4, leaf_size=7)
        result = T.validate(nodes, rows, fanout=4, leaf_size=7)
        self.assertEqual(result['candidate_count'], len(rows))
        self.assertLessEqual(result['max_leaf_size'], 7)
        self.assertLessEqual(result['max_fanout'], 4)
        leaves = [n for n in nodes.values() if not n['children']]
        ids = [key for leaf in leaves for key in leaf['members']]
        self.assertEqual(sorted(ids), sorted(r['id'] for r in rows))
        self.assertEqual(len(ids), len(set(ids)))
        for node in nodes.values():
            if node['children']:
                children = [key for child in node['children'] for key in nodes[child]['members']]
                self.assertEqual(sorted(children), node['members'])
                self.assertEqual(len(children), len(set(children)))

    def test_reproducible_under_input_permutation_without_mutation(self):
        rows, vectors = fixture()
        original_rows, original_vectors = copy.deepcopy(rows), vectors.copy()
        first = T.build(rows, vectors)
        permutation = np.random.default_rng(7).permutation(len(rows))
        self.assertEqual(first, T.build([rows[i] for i in permutation], vectors[permutation]))
        self.assertEqual(first, T.build(rows, vectors))
        self.assertEqual(rows, original_rows)
        np.testing.assert_array_equal(vectors, original_vectors)

    def test_identical_vectors_and_tied_projections_use_sorted_ids(self):
        rows, _ = fixture(20)
        vectors = np.tile([1., 0.], (20, 1))
        nodes = T.build(rows[::-1], vectors, fanout=2, leaf_size=10)
        self.assertEqual(nodes['n.00']['members'], [r['id'] for r in rows[:10]])
        self.assertEqual(nodes['n.01']['members'], [r['id'] for r in rows[10:]])
        tied = np.tile([[1., 0.], [0., 1.]], (10, 1))
        self.assertEqual(T.build(rows, tied, fanout=2, leaf_size=10),
                         T.build(rows[::-1], tied[::-1], fanout=2, leaf_size=10))

    def test_full_catalog_size_has_depth_three(self):
        rows = [{'id': f'id{i:05}'} for i in range(45325)]
        vectors = np.tile([1., 0.], (len(rows), 1))
        result = T.validate(T.build(rows, vectors), rows)
        self.assertEqual(result['candidate_count'], 45325)
        self.assertEqual(result['max_depth'], 3)
        self.assertLessEqual(result['max_leaf_size'], 24)
        self.assertGreaterEqual(result['min_leaf_size'], 11)
        self.assertLessEqual(result['max_leaf_size'], 12)

    def test_same_names_are_distinct_and_whole_plugin_is_indivisible(self):
        rows = [{'id': 'a', 'name': 'Same name', 'kind': 'skill'},
                {'id': 'b', 'name': 'Same name', 'kind': 'plugin',
                 'components': [{'name': 'internal one'}, {'name': 'internal two'}]},
                {'id': 'c'}]
        nodes = T.build(rows, np.eye(3), fanout=2, leaf_size=1)
        self.assertEqual(nodes['n']['members'], ['a', 'b', 'c'])
        self.assertEqual(sum(n['members'] == ['b'] for n in nodes.values() if not n['children']), 1)

    def test_cards_only_summarize_metadata_with_explicit_limits(self):
        rows, vectors = fixture(60)
        for row in rows:
            row['topics'] = ['INHERITED_NOT_SOURCE']
        nodes = T.build(rows, vectors, leaf_size=5)
        for node in nodes.values():
            self.assertIn('absent terms do not rule out members', node['description'])
            self.assertIn('do not replace full descriptions, limitations or requirements', node['description'])
            self.assertNotIn('inherited_not_source', node['description'].lower())
            if node['children']:
                self.assertIn('Direct child cues (all children; approximate):', node['description'])
                for child in node['children']:
                    self.assertIn(child + ':', node['description'])
            else:
                self.assertIn('All member names (not full descriptions):', node['description'])
                for row in rows:
                    if row['id'] in node['members']:
                        self.assertIn(row['name'], node['description'])

    def test_long_member_names_are_never_silently_truncated(self):
        name = 'Original requirement: do not invoke paid providers. ' * 30
        nodes = T.build([{'id': 'long', 'name': name}], np.ones((1, 1)))
        self.assertIn(name, nodes['n']['description'])
        self.assertEqual(T.stats(nodes)['cards_over_target'], 1)

    def test_query_independent_api_has_no_query_gold_or_encoder(self):
        self.assertEqual(list(inspect.signature(T.build).parameters),
                         ['rows', 'vectors', 'fanout', 'leaf_size'])
        rows, vectors = fixture(32)
        with self.assertRaises(TypeError):
            T.build(rows, vectors, query='database')
        with self.assertRaises(TypeError):
            T.build(rows, vectors, expected_ids=['cap00001'])
        # Mutable experiment metadata never affects the catalog organization.
        first = T.build(rows, vectors)
        altered = [dict(r, expected_ids=['irrelevant'], query='arbitrary request') for r in rows]
        self.assertEqual(first, T.build(altered, vectors))

    def test_duplicate_ids_rejected_and_textless_rows_kept(self):
        with self.assertRaisesRegex(ValueError, 'duplicate canonical ids'):
            T.build([{'id': 'same'}, {'id': 'same'}], np.eye(2))
        nodes = T.build([{'id': 'blank'}, {'id': 'named', 'name': ''}], np.eye(2))
        self.assertEqual(nodes['n']['members'], ['blank', 'named'])

    def test_invalid_vectors_rejected_without_dropping_rows(self):
        rows, _ = fixture(2)
        for vectors in (np.zeros((2, 3)), [[float('nan'), 0], [1, 0]],
                        [[float('inf'), 0], [1, 0]], [[2, 0], [1, 0]],
                        np.eye(3), np.ones(2), np.empty((2, 0)), [['x'], ['y']]):
            with self.subTest(vectors=vectors):
                with self.assertRaises(ValueError):
                    T.build(rows, vectors)

    def test_empty_catalog_and_invalid_parameters(self):
        self.assertEqual(T.validate(T.build([], np.empty((0, 3))), [])['candidate_count'], 0)
        for options in ({'fanout': 1}, {'fanout': True}, {'leaf_size': 0}, {'leaf_size': 1.5}):
            with self.assertRaises(ValueError):
                T.build([], np.empty((0, 3)), **options)

    def test_validator_detects_omission_overlap_and_unreachable_nodes(self):
        rows, vectors = fixture(20)
        original = T.build(rows, vectors, fanout=2, leaf_size=10)
        for error in ('omission', 'overlap', 'unreachable'):
            nodes = copy.deepcopy(original)
            if error == 'omission':
                nodes['n.00']['members'].pop()
            elif error == 'overlap':
                nodes['n.00']['members'][0] = nodes['n.01']['members'][0]
            else:
                nodes['extra'] = dict(nodes['n.00'], id='extra')
            with self.subTest(error=error):
                with self.assertRaises(ValueError):
                    T.validate(nodes, rows, fanout=2, leaf_size=10)


if __name__ == '__main__':
    unittest.main()
