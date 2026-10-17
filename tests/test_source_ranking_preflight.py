"""Deterministic boundary checks; these are not live routing accuracy tests."""
import copy
import json
import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmarks/directory-depth'))
from source_preflight import deduplicate
from ranking_policy import preferences, accept_choice
from merged_catalog import directory, merged, plugin_identity


def row(i, rank=None, growth=None):
    return {'id': i, 'kind': 'skill', 'mode': 'guidance', 'description': 'SQL review',
            'identity': ['owner/repo', 'commit', i], 'rank': rank, 'growth': growth,
            'provenance': {'source': 'public'}}


def measurement(value, board='same', window='all-time', at=100):
    return {'value': value, 'board': board, 'window': window, 'metric': window, 'at': at}


def group(ids):
    return {'members': ids, 'operation_contract': 'Review SELECT query plans without executing SQL.',
            'evidence': 'Synthetic unit fixture; not an observed capability-equivalence claim.'}


class RankingTests(unittest.TestCase):
    def test_exact_aliases_merge_with_all_provenance(self):
        a = row('a'); b = copy.deepcopy(a); b['id'] = 'another-source-a'
        result = deduplicate([a, b])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['aliases'], ['a', 'another-source-a'])
        self.assertEqual(len(result[0]['provenance']), 1)

    def test_deduplication_is_idempotent_and_preserves_alternate_source_metrics(self):
        a = row('a', measurement(1)); b = copy.deepcopy(a); b['id'] = 'alias'
        b['provenance'] = {'source': 'other-public'}
        b['rank'] = measurement(8, board='another-board')
        result = deduplicate([a, b])
        self.assertEqual(deduplicate(result), result)
        self.assertEqual(set(result[0]['aliases']), {'a', 'alias'})
        self.assertEqual(len(result[0]['metric_observations']), 2)
        self.assertEqual(len(result[0]['provenance']), 2)
        self.assertIsNone(result[0]['rank'])

    def test_names_or_descriptions_never_prove_identity(self):
        self.assertEqual(len(deduplicate([row('a'), row('b')])), 2)
        a = row('a'); b = copy.deepcopy(a); b['id'] = 'b'; b['identity'][1] = 'new-version'
        self.assertEqual(len(deduplicate([a, b])), 2)
        b = copy.deepcopy(a); b['id'] = 'b'; b['mode'] = 'execution'
        self.assertEqual(len(deduplicate([a, b])), 2)

    def test_conflicting_metadata_is_not_silently_lost(self):
        a = row('a'); b = copy.deepcopy(a); b['id'] = 'b'; b['description'] = 'Executes SQL'
        result = deduplicate([a, b])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['descriptions'], ['SQL review', 'Executes SQL'])
        self.assertIn('Executes SQL', result[0]['description'])

    def test_best_rank_primary_fast_growth_backup_and_remaining_retained(self):
        rows = [row('a', measurement(3), measurement(10, window='7d')),
                row('b', measurement(1), measurement(1, window='7d')),
                row('c', measurement(2), measurement(30, window='7d'))]
        result = preferences(rows, [group(['a', 'b', 'c'])], now=100)
        self.assertEqual(result['visible_ids'], ['b', 'c'])
        self.assertEqual(set(result['all_ids']), {'a', 'b', 'c'})
        self.assertIsNone(result['selected'])

    def test_missing_metrics_do_not_remove_or_demote_unknown_candidates(self):
        rows = [row('a'), row('b'), row('c')]
        result = preferences(rows, [group(['a', 'b', 'c'])], now=100)
        self.assertEqual(result['visible_ids'], ['a', 'b', 'c'])

    def test_incomparable_boards_and_windows_preserve_visibility(self):
        rows = [row('a', measurement(1, board='one')), row('b', measurement(100, board='two'))]
        result = preferences(rows, [group(['a', 'b'])], now=100)
        self.assertEqual(set(result['visible_ids']), {'a', 'b'})
        rows = [row('a', measurement(1), measurement(9, window='7d')),
                row('b', measurement(2), measurement(8, window='24h')),
                row('c', measurement(3), measurement(99, window='7d'))]
        self.assertEqual(set(preferences(rows, [group(['a', 'b', 'c'])], now=100)['visible_ids']), {'a', 'b', 'c'})

    def test_later_different_operation_remains_visible(self):
        rows = [row('a', measurement(1)), row('b', measurement(2)), row('culture')]
        result = preferences(rows, [group(['a', 'b'])], now=100)
        self.assertIn('culture', result['visible_ids'])

    def test_equivalence_proof_required_and_modes_not_interchangeable(self):
        rows = [row('a'), row('b')]
        with self.assertRaisesRegex(ValueError, 'equivalence_evidence_required'):
            preferences(rows, [{'members': ['a', 'b']}], now=100)
        rows[1]['mode'] = 'execution'
        with self.assertRaisesRegex(ValueError, 'mixed_execution_contracts'):
            preferences(rows, [group(['a', 'b'])], now=100)

    def test_stale_future_nan_boolean_metrics_are_unknown(self):
        for value in [measurement(1, at=-100000), measurement(1, at=200), measurement(float('nan')), measurement(True)]:
            result = preferences([row('a', value), row('b')], [group(['a', 'b'])], now=100)
            self.assertEqual(set(result['visible_ids']), {'a', 'b'})

    def test_threshold_and_choices_cannot_be_overridden_by_rank(self):
        self.assertIsNone(accept_choice({'choice': 'a', 'confidence': .6999}, ['a']))
        self.assertEqual(accept_choice({'choice': 'a', 'confidence': .7}, ['a']), 'a')
        with self.assertRaises(ValueError): accept_choice({'choice': 'outside', 'confidence': 1}, ['a'])

    def test_overlapping_groups_rejected(self):
        with self.assertRaisesRegex(ValueError, 'overlapping_equivalence_groups'):
            preferences([row('a'), row('b'), row('c')], [group(['a', 'b']), group(['b', 'c'])], now=100)

    def test_no_equivalence_means_rank_alone_cannot_hide_anything(self):
        rows = [row('a', measurement(1)), row('b', measurement(999))]
        self.assertEqual(preferences(rows, [], now=100)['visible_ids'], ['a', 'b'])


class MergedCatalogTests(unittest.TestCase):
    def test_category_combines_sources_and_delivery_types(self):
        rows = [row('a'), row('b'), row('c')]
        for item in rows: item['publisher_labels'] = ['development']
        rows[1]['kind'] = 'plugin'; rows[2]['kind'] = 'mcp'
        rows[0]['provenance'] = {'source': 'market-one'}
        rows[1]['provenance'] = {'source': 'market-two'}
        result = directory(rows)
        self.assertEqual(result['nodes']['software']['members'], ['a', 'b', 'c'])
        self.assertFalse(result['source_directories'])
        self.assertFalse(set(result['nodes']) & {'market-one', 'market-two'})

    def test_unclassified_candidates_are_always_retained(self):
        result = directory([row('unknown')])
        self.assertEqual(result['pending_count'], 1)
        self.assertTrue(result['nodes']['pending']['always_retain'])

    def test_plugin_internal_skills_cannot_be_added_as_candidates(self):
        item = row('internal'); item['parent_plugin'] = 'plugin'
        with self.assertRaisesRegex(ValueError, 'plugin_internal_skill'):
            directory([item])

    def test_pinned_same_implementation_merges_across_markets_without_losing_descriptions(self):
        revision = 'a' * 40
        source = {'source': 'git-subdir', 'url': 'https://github.com/public/package.git',
                  'path': 'plugin', 'sha': revision}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'catalog.json').write_text('[]')
            for market, description in [('one', 'Review SQL plans'), ('two', '审查 SQL 查询')]:
                snapshot = {'repo': 'publisher/' + market, 'commit': 'b' * 40, 'checked_at': 100,
                    'items': [{'name': 'sql', 'description': description, 'entry': {'name': 'sql', 'source': source,
                        'category': 'development', 'skills': ['internal-one', 'internal-two']}}]}
                (root / ('plugin-' + market + '.json')).write_text(json.dumps(
                    {'source': market, 'status': 'complete', 'snapshot': snapshot}))
            original, canonical = merged(root)
            self.assertEqual((len(original), len(canonical)), (2, 1))
            self.assertEqual(canonical[0]['kind'], 'plugin')
            self.assertEqual(len(canonical[0]['aliases']), 2)
            self.assertEqual(len(canonical[0]['provenance']), 2)
            self.assertEqual(len(canonical[0]['descriptions']), 2)
            self.assertEqual(directory(canonical)['plugin_internal_candidates'], 0)

    def test_native_identity_ignores_random_catalog_snapshot_revision(self):
        item = {'native_entry': {'pluginId': 'example@public', 'version': '1.0.0'}}
        self.assertEqual(plugin_identity({'commit': 'random-one'}, item),
                         plugin_identity({'commit': 'random-two'}, item))

    def test_unpinned_external_sources_are_not_falsely_merged(self):
        item = {'name': 'same-name', 'entry': {'source': {'source': 'github', 'repo': 'public/repo', 'ref': 'main'}}}
        self.assertNotEqual(plugin_identity({'repo': 'market/one', 'commit': 'a'*40}, item),
                            plugin_identity({'repo': 'market/two', 'commit': 'b'*40}, item))

    def test_different_component_overrides_are_not_merged(self):
        snap = {'repo': 'public/market', 'commit': 'a'*40}
        a = {'name': 'one', 'entry': {'source': './plugin', 'commands': ['./commands/one']}}
        b = copy.deepcopy(a); b['entry']['commands'] = ['./commands/two']
        self.assertNotEqual(plugin_identity(snap, a), plugin_identity(snap, b))


if __name__ == '__main__': unittest.main()
