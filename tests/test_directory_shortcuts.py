"""Local shortcut integration: real directory/SQLite, fake classification/routing."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/catmaster_backpack'))
import capability_usage
import plugin_directory as directory
from plugin_pipeline import atomic_json, init_store

NOW = 1_800_000_000
LEAVES = {'query': 'data_query', 'rare_write': 'writing_knowledge', 'fresh': 'code_execution'}


class MetadataClassifier:
    def __init__(self):
        self.calls = []
        self.names = []

    def noul(self, spec, state):
        self.calls.append({'input_tokens': 10, 'output_tokens': 2})
        name = state['capability_metadata']['name']
        self.names.append(name)
        leaf = LEAVES[name]
        return {'answers': {
            key: ({'type': 'choice', 'choice': leaf, 'confidence': .9} if key == 'primary'
                  else {'type': 'noul', 'noul': .9 if key == leaf else .01})
            for key in spec['questions']}}


class RouteProvider:
    def __init__(self, choice, retained=(), *, confidence=.9, fail=False):
        self.choice = choice
        self.retained = set(retained)
        self.confidence = confidence
        self.fail = fail
        self.calls = []
        self.specs = []
        self.states = []
        self.pool = None

    def noul(self, spec, state):
        self.calls.append({'input_tokens': 10, 'output_tokens': 2})
        self.specs.append(deepcopy(spec))
        self.states.append(deepcopy(state))
        if self.fail:
            raise TimeoutError('private failure fixture')
        return {'answers': {
            key: ({'type': 'choice', 'choice': 'either', 'confidence': .9}
                  if key == '_delivery_mode' else
                  {'type': 'noul', 'noul': self.confidence if key == 'match' else
                   .9 if key in self.retained else .01})
            for key in spec['questions']}}

    def choose(self, question, state, choices):
        self.calls.append({'input_tokens': 10, 'output_tokens': 2})
        self.states.append(deepcopy(state))
        self.pool = deepcopy(choices)
        return {'type': 'choice', 'choice': self.choice, 'confidence': self.confidence}


class DirectoryShortcutTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        self.store = self.root / 'store'
        init_store(self.store, self.project)
        timer = patch('capability_usage.time.time', return_value=NOW)
        timer.start()
        self.addCleanup(timer.stop)
        self.populate()
        self.classifier = MetadataClassifier()

    def populate(self, names=('query', 'rare_write')):
        registry = directory.load_registry(self.store)[2]
        registry['plugins'] = {'fixture': {
            'name': 'fixture', 'root': str(self.project),
            'library': ([{'kind': 'skill', 'path': 'rare_write/SKILL.md', 'name': 'rare_write',
                         'description': 'Apply a specialist prose-writing workflow.'}]
                        if 'rare_write' in names else []),
            'indexes': {'service': {'tools': [
                {'name': name, 'description': 'Query current SQL data.' if name == 'query'
                 else 'Execute the requested code.', 'inputSchema': {'type': 'object'}}
                for name in names if name != 'rare_write'], 'resources': []}}}}
        atomic_json(self.store / 'registry.json', registry)

    def entries(self):
        return directory.registered_entries(directory.load_registry(self.store)[2])

    def key(self, name):
        return next(key for key, entry in self.entries().items() if entry['name'] == name)

    def refresh(self):
        return directory.refresh(self.store, provider_factory=lambda: self.classifier)

    def tree(self, entries=None):
        return directory.available_directory(self.store, self.entries() if entries is None else entries)

    def pin(self, *names):
        return capability_usage.configure_direct(self.store, [self.key(name) for name in names], self.entries())

    def successful_use(self, name='query', receipt='one', now=NOW):
        key = self.key(name)
        entry = self.entries()[key]
        return capability_usage.record_use(self.store, key, entry['kind'], receipt,
                                          completed=True, event='completed', now=now)

    def select(self, provider, need='Perform the requested fixture operation.'):
        return directory.select(need, self.entries(), self.store, provider_factory=lambda _: provider)

    def test_pin_existing_capability_preserves_all_normal_memberships(self):
        self.refresh()
        before = self.tree()
        memberships = {leaf: before.members([leaf]) for leaf in before.leaf_ids}
        self.pin('query')
        self.assertEqual(self.refresh()['classification_calls'], 0)
        after = self.tree()
        for leaf, members in memberships.items():
            self.assertEqual(after.members([leaf]), members)
        query = self.key('query')
        self.assertIn('direct_' + query, after.shortcut_root_ids)
        self.assertEqual(after.members(['direct_' + query]), [query])
        self.assertEqual(directory.read_cache(self.store)['entries'][query]['status'], 'classified')
        shelf = directory.first_layer(self.store, self.entries())
        self.assertEqual(shelf['direct'][0]['id'], query)
        self.assertTrue(shelf['ordinary_categories_preserved'])
        self.assertTrue(set(before.root_ids) <= {card['id'] for card in shelf['categories']})

    def test_new_explicit_direct_only_capability_bypasses_classifier(self):
        self.refresh()
        self.populate(('query', 'rare_write', 'fresh'))
        self.pin('fresh')
        factory = Mock(side_effect=AssertionError('classification must not run'))
        result = directory.refresh(self.store, provider_factory=factory)
        self.assertEqual((result['status'], result['classification_calls'], result['pending']), ('ready', 0, 0))
        factory.assert_not_called()
        key = self.key('fresh')
        record = directory.read_cache(self.store)['entries'][key]
        self.assertEqual((record['status'], record['leaves']), ('direct', []))
        tree = self.tree()
        self.assertEqual(tree.members(['direct_' + key]), [key])
        self.assertEqual(set(tree.members(tree.root_ids)), set(self.entries()))

    def test_unpin_direct_only_entry_reclassifies_before_normal_routing(self):
        self.populate(('fresh',))
        self.pin('fresh')
        self.assertEqual(self.refresh()['classification_calls'], 0)
        self.pin()
        provider = RouteProvider(self.key('fresh'), ('software', 'code_execution'))
        self.assertEqual(self.select(provider)['reason'], 'directory_review_required')
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.refresh()['classification_calls'], 1)
        self.assertEqual(self.classifier.names, ['fresh'])
        tree = self.tree()
        self.assertEqual(tree.shortcut_root_ids, [])
        self.assertEqual(tree.members(['code_execution']), [self.key('fresh')])
        self.assertEqual(directory.read_cache(self.store)['entries'][self.key('fresh')]['status'], 'classified')

    def test_recent_use_promotes_on_read_and_routes_with_two_calls(self):
        self.refresh()
        before = (self.store / directory.FILE).read_bytes()
        self.successful_use(receipt='one')
        self.assertNotIn('frequent', self.tree().root_ids)
        self.successful_use(receipt='two')
        tree = self.tree()
        self.assertIn('frequent', tree.shortcut_root_ids)
        self.assertEqual(tree.members(['frequent']), [self.key('query')])
        self.assertEqual(tree.members(['data_query']), [self.key('query')])
        provider = RouteProvider(self.key('query'), ('frequent',))
        result = self.select(provider)
        self.assertEqual((result['status'], result['choice']), ('selected', self.key('query')))
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(result['routing']['provider_calls'], 2)
        self.assertEqual(set(provider.specs[0]['questions']), set(tree.root_ids) | {'_delivery_mode'})
        self.assertEqual(set(provider.pool), {self.key('query'), 'none'})
        self.assertEqual(directory.first_layer(self.store, self.entries())['frequent'][0]['uses'], 2)
        self.assertEqual((self.store / directory.FILE).read_bytes(), before)

    def test_recent_use_ageing_removes_only_alias_not_normal_route(self):
        self.refresh()
        self.successful_use(receipt='one')
        self.successful_use(receipt='two')
        self.assertIn('frequent', self.tree().root_ids)
        before = (self.store / directory.FILE).read_bytes()
        with patch('capability_usage.time.time', return_value=NOW + 31 * 86400):
            tree = self.tree()
            self.assertNotIn('frequent', tree.root_ids)
            self.assertEqual(tree.members(['data_query']), [self.key('query')])
            self.assertEqual(directory.first_layer(self.store, self.entries())['frequent'], [])
            provider = RouteProvider(self.key('query'), ('data_content', 'data_query'))
            result = self.select(provider)
            self.assertEqual((result['status'], result['choice']), ('selected', self.key('query')))
            self.assertEqual(len(provider.calls), 3)
        self.assertEqual((self.store / directory.FILE).read_bytes(), before)

    def test_rare_capability_remains_routable_beside_frequent_capability(self):
        self.refresh()
        for index in range(4):
            self.successful_use(receipt='success-' + str(index))
        tree = self.tree()
        self.assertIn('frequent', tree.root_ids)
        self.assertEqual(tree.members(['writing_knowledge']), [self.key('rare_write')])
        provider = RouteProvider(self.key('rare_write'), ('product_planning', 'writing_knowledge'))
        result = self.select(provider, 'Apply the specialist workflow to write prose.')
        self.assertEqual((result['status'], result['choice']), ('selected', self.key('rare_write')))
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(set(provider.pool), {self.key('rare_write'), 'none'})

    def test_direct_selection_only_accepts_current_eligible_shelf_ids(self):
        self.refresh()
        self.pin('query')
        self.refresh()
        provider = RouteProvider(self.key('query'))
        for key, entries in ((self.key('rare_write'), self.entries()),
                             ('cap_' + '0' * 20, self.entries()),
                             (self.key('query'), {self.key('rare_write'): self.entries()[self.key('rare_write')]})):
            with self.subTest(key=key, eligible=list(entries)):
                result = directory.select_direct('Query data.', key, entries, self.store,
                                                 provider_factory=lambda _: provider)
                self.assertEqual((result['status'], result['reason']), ('unavailable', 'shortcut_not_available'))
        self.assertEqual(provider.calls, [])

    def test_explicit_direct_and_frequent_match_accepts_inclusive_70_once(self):
        self.refresh()
        for shelf in ('direct', 'frequent'):
            if shelf == 'direct':
                self.pin('query')
                self.refresh()
            else:
                self.pin()
                self.refresh()
                self.successful_use(receipt='one')
                self.successful_use(receipt='two')
            provider = RouteProvider(self.key('query'), confidence=.70)
            result = directory.select_direct('Query current SQL data.', self.key('query'), self.entries(),
                                             self.store, provider_factory=lambda _: provider)
            with self.subTest(shelf=shelf):
                self.assertEqual((result['status'], result['choice'], result['confidence']),
                                 ('selected', self.key('query'), .70))
                self.assertEqual(result['routing']['provider_calls'], 1)
                self.assertEqual(len(provider.calls), 1)
                self.assertEqual(set(provider.specs[0]['questions']), {'match'})
                self.assertIsNone(provider.pool)
                self.assertEqual(provider.states, [{'task': 'Query current SQL data.'}])

    def test_direct_match_rejects_invalid_probability_and_never_replays(self):
        self.refresh()
        self.pin('query')
        self.refresh()
        for confidence in (.699, True, float('nan'), float('inf'), -1, 2):
            provider = RouteProvider(self.key('query'), confidence=confidence)
            result = directory.select_direct('Query SQL data.', self.key('query'), self.entries(), self.store,
                                             provider_factory=lambda _: provider)
            with self.subTest(confidence=confidence):
                self.assertEqual(result['status'], 'unavailable')
                self.assertNotIn('choice', result)
                self.assertEqual(len(provider.calls), 1)
        provider = RouteProvider(self.key('query'), fail=True)
        result = directory.select_direct('Query SQL data.', self.key('query'), self.entries(), self.store,
                                         provider_factory=lambda _: provider)
        self.assertEqual(result['reason'], 'shortcut_confirmation_failed_or_unknown')
        self.assertEqual(len(provider.calls), 1)
        self.assertNotIn('private failure fixture', str(result))

    def test_direct_match_discards_late_result_without_replay(self):
        self.refresh()
        self.pin('query')
        self.refresh()
        provider = RouteProvider(self.key('query'))
        ticks = iter((0, 12, 12))
        result = directory.select_direct('Query SQL data.', self.key('query'), self.entries(), self.store,
                                         provider_factory=lambda _: provider, clock=lambda: next(ticks))
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn('choice', result)
        self.assertEqual(len(provider.calls), 1)

    def test_corrupt_optional_statistics_do_not_suppress_normal_selection(self):
        self.refresh()
        self.successful_use(receipt='one')
        self.successful_use(receipt='two')
        (self.store / capability_usage.USAGE_FILE).write_bytes(b'not a SQLite database')
        tree = self.tree()
        self.assertNotIn('frequent', tree.root_ids)
        self.assertEqual(tree.members(['data_query']), [self.key('query')])
        provider = RouteProvider(self.key('query'), ('data_content', 'data_query'))
        result = self.select(provider)
        self.assertEqual((result['status'], result['choice']), ('selected', self.key('query')))
        self.assertEqual(len(provider.calls), 3)
        shelf = directory.first_layer(self.store, self.entries())
        self.assertEqual(shelf['frequent'], [])
        self.assertIn('data_content', {card['id'] for card in shelf['categories']})


if __name__ == '__main__':
    unittest.main()
