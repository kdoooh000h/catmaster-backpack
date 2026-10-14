"""Public market boundary tests; optional installed-runtime integration tests.

CATMASTER_STANDALONE_RUNTIME points to an existing standalone installation.
All mutable state is isolated in TemporaryDirectory; no live home or provider.
"""
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import Mock, patch
import zipfile

ADAPTER = Path(__file__).resolve().parents[1] / 'adapters/codex'
sys.path.insert(0, str(ADAPTER))
from market_connect import Market, extract_package
import market_gateway
import market_protocol


def safe_path(value):
    if not value or Path(value).is_absolute() or '..' in Path(value).parts or '\\' in value:
        raise ValueError('unsafe')
    return value


class ArchiveTests(unittest.TestCase):
    def archive(self, rows):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for path, content, mode in rows:
                entry = zipfile.ZipInfo(path)
                entry.external_attr = mode << 16
                archive.writestr(entry, content)
        return stream.getvalue()

    def test_selected_subtree_only(self):
        content = self.archive([('repo/plugins/a/plugin.json', '{}', stat.S_IFREG | 0o644),
                                ('repo/plugins/b/secret', 'unselected', stat.S_IFREG | 0o644)])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'out'
            extract_package(content, 'plugins/a', root, safe_path)
            self.assertEqual([p.name for p in root.iterdir()], ['plugin.json'])

    def test_symlink_traversal_and_duplicate_fail_before_writes(self):
        rows = [
            [('repo/plugin/link', '/outside', stat.S_IFLNK | 0o777)],
            [('repo/plugin/../../outside', 'bad', stat.S_IFREG | 0o644)],
            [('repo/plugin/a', '1', stat.S_IFREG | 0o644), ('repo/plugin/a', '2', stat.S_IFREG | 0o644)],
        ]
        for case in rows:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / 'out'
                with self.assertRaises(ValueError):
                    extract_package(self.archive(case), 'plugin', root, safe_path)
                self.assertFalse(root.exists())


RUNTIME = os.environ.get('CATMASTER_STANDALONE_RUNTIME')


@unittest.skipUnless(RUNTIME, 'set CATMASTER_STANDALONE_RUNTIME for installed-runtime boundary checks')
class MarketIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gateway = market_gateway.load_gateway(RUNTIME)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name).resolve()
        self.descriptor = self.data / ('codex-public-gateway-' + 'a' * 48 + '.json')
        self.value = {'version': 2, 'data_root': str(self.data), 'project_root': None, 'enabled': True}
        self.write(self.descriptor, self.value)
        self.connection = {**self.value, '_descriptor': str(self.descriptor)}
        self.market = Market(self.gateway, self.connection)
        self.addCleanup(self.market.close)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        path.chmod(0o600)

    def plan(self, skills=False, servers=True):
        token = 'b' * 48
        root = self.data / 'market-plans' / token / 'package'
        root.mkdir(parents=True)
        self.write(root / 'plugin.json', {'name': 'sample', 'skills': './skills'})
        plan = {'version': 1, 'id': token, 'kind': 'plugin', 'name': 'sample', 'need': 'test',
                'descriptor': self.descriptor.name, 'connection': self.value, 'status': 'prepared',
                'expires': 10**12, 'source': {'kind': 'plugin', 'commit': 'd' * 40},
                'routing': [], 'skills': [], 'servers': []}
        if skills:
            skill = root / 'skills/sample'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('---\nname: sample\ndescription: Format a short test message.\n---\nUse plain text.\n')
            plan['skills'] = [{'name': 'sample', 'path': str(skill), 'digest': self.gateway.public_access.fingerprint(skill)}]
        if servers:
            plan['servers'] = [self.market.server({'title': 'sample', 'description': 'echo',
                'source': {'kind': 'test'}, 'configuration': {'transport': 'streamable-http', 'url': 'https://example.com/mcp', 'headers': {}}}, plan)]
        plan.update(package=str(root), package_digest=self.gateway.public_access.fingerprint(root))
        plan.update(mcp_before=self.market.marker('mcp-servers.json'), skills_before=self.market.marker('public-access.json'))
        self.market.save(plan)
        return plan

    def test_plugin_templates_are_disclosed_with_original_receipt_and_rechecked(self):
        plan = self.plan(skills=True, servers=False)
        root = Path(plan['skills'][0]['path'])
        template = root / 'templates/concept-map.md'
        template.parent.mkdir()
        template.write_text('Template rules: include a labeled diagram.')
        plan['skills'][0]['digest'] = self.gateway.public_access.fingerprint(root)
        plan['package_digest'] = self.gateway.public_access.fingerprint(Path(plan['package']))
        self.market.save(plan)
        self.market.connect(plan['id'])
        key = self.market.bound_skill_keys(plan['id'])[0]
        router = self.gateway.Router(self.data, None, allowed=[key])
        module = sys.modules[router.__class__.__mro__[1].__module__]
        with patch.object(router, '_choose', return_value={'status': 'selected', 'skill': key, 'confidence': 1}):
            selected = router.request('acquire', {'need': 'format a message'})
        with patch.object(router, '_choose', return_value={'status': 'selected', 'skill': 'templates/concept-map.md', 'confidence': 1}) as choose:
            value = router.request('resource', {'selection': selected['selection'], 'need': 'diagram template'})
        self.assertIn('templates/concept-map.md', [c.name for c in choose.call_args.args[1]])
        self.assertEqual(value['resources'][0]['content'], template.read_text())
        self.assertEqual(Path(value['resources'][0]['absolute_path']).read_text(), template.read_text())
        with patch.object(router, '_choose', return_value={'status': 'selected', 'skill': '../outside', 'confidence': 1}):
            with self.assertRaisesRegex(ValueError, 'invalid_resource_choice'):
                router.request('resource', {'selection': selected['selection'], 'need': 'template'})
        state = json.loads((self.data / 'public-access.json').read_text())
        state['items'].pop(key)
        self.write(self.data / 'public-access.json', state)
        with self.assertRaises(Exception):
            router.request('resource', {'selection': selected['selection'], 'need': 'template'})

    def test_receipt_survives_new_gateway_and_is_idempotent(self):
        plan = self.plan(skills=True)
        result = self.market.connect(plan['id'])
        self.assertEqual(result['components'], {'skills': 1, 'mcp': 1})
        before = (self.data / 'mcp-servers.json').read_bytes()
        reopened = Market(self.gateway, self.connection)
        try:
            self.assertEqual(reopened.connect(plan['id'])['status'], 'connected')
        finally:
            reopened.close()
        self.assertEqual(before, (self.data / 'mcp-servers.json').read_bytes())
        row = next(iter(json.loads(before)['servers'].values()))
        self.assertEqual(row['connections'], [self.descriptor.name])

    def test_expired_disabled_and_cross_connection_receipts_cannot_mutate(self):
        plan = self.plan()
        for change in ('expired', 'disabled', 'connection'):
            with self.subTest(change=change):
                copy = dict(plan)
                self.write(self.descriptor, self.value)
                if change == 'expired': copy['expires'] = 0
                if change == 'connection': copy['descriptor'] = 'other'
                if change == 'disabled': self.write(self.descriptor, {**self.value, 'enabled': False})
                self.market.save(copy)
                with self.assertRaises((ValueError, RuntimeError)):
                    self.market.connect(plan['id'])
                self.assertFalse((self.data / 'mcp-servers.json').exists())

    def test_revocation_is_not_restored_by_completed_receipt(self):
        plan = self.plan()
        self.market.connect(plan['id'])
        registry = json.loads((self.data / 'mcp-servers.json').read_text())
        registry['servers'][plan['servers'][0]['id']]['enabled'] = False
        self.write(self.data / 'mcp-servers.json', registry)
        with self.assertRaisesRegex(ValueError, 'revoked'):
            self.market.connect(plan['id'])
        self.assertFalse(json.loads((self.data / 'mcp-servers.json').read_text())['servers'][plan['servers'][0]['id']]['enabled'])

    def test_interrupted_setup_does_not_retry_and_preserves_unrelated_server(self):
        plan = self.plan(skills=True)
        with patch.object(self.market, 'connect_servers', side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError): self.market.connect(plan['id'])
        with patch.object(self.market, 'connect_servers') as mutation:
            self.assertEqual(self.market.connect(plan['id'])['status'], 'reconciliation_required')
            mutation.assert_not_called()
        self.assertTrue((self.market.folder / (plan['id'] + '-skills-backup.json')).exists())

    def test_changed_package_fails_before_grants(self):
        plan = self.plan()
        (Path(plan['package']) / 'plugin.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'package_changed'):
            self.market.connect(plan['id'])
        self.assertFalse((self.data / 'mcp-servers.json').exists())

    def test_native_components_are_not_silently_ignored(self):
        plan = self.plan(servers=False)
        root = Path(plan['package'])
        for key in ('hooks', 'apps', 'userConfig', 'dependencies'):
            self.write(root / 'plugin.json', {'name': 'sample', key: {'needed': True}})
            self.assertIn(key, self.market.inspect_plugin(root, plan))

    def test_market_entry_and_masked_overlay_require_native_setup(self):
        plan = self.plan(servers=False)
        root = Path(plan['package'])
        for key in ('hooks', 'apps', 'commands'):
            plan['market_entry'] = {key: {'required': True}}
            self.assertIn(key, self.market.inspect_plugin(root, plan))
        plan['market_entry'] = {}
        self.write(root / 'plugin.json', {'name': 'sample', 'hooks': {}, 'extensions': {'com.openai': {'hooks': {'required': True}}}})
        self.assertIn('hooks', self.market.inspect_plugin(root, plan))

    def test_removed_service_invalidates_prepared_and_future_setup(self):
        plan = self.plan()
        self.market.connect(plan['id'])
        outstanding = {**plan, 'id': 'c' * 48, 'mcp_before': self.market.marker('mcp-servers.json')}
        self.market.save(outstanding)
        self.write(self.data / 'mcp-servers.json', {'version': 1, 'servers': {}})
        with self.assertRaisesRegex(ValueError, 'changed_reprepare'):
            self.market.connect(outstanding['id'])
        with self.assertRaisesRegex(ValueError, 'removed_or_interrupted'):
            self.market.server({'title': 'sample', 'description': 'same service', 'source': {},
                               'configuration': plan['servers'][0]['configuration']}, {})
        self.assertEqual(json.loads((self.data / 'mcp-servers.json').read_text())['servers'], {})

    def test_bound_plugin_skill_selection_excludes_other_sources(self):
        plan = self.plan(skills=True, servers=False)
        self.market.connect(plan['id'])
        keys = self.market.bound_skill_keys(plan['id'])
        with patch.object(self.gateway.Router, '_choose', side_effect=lambda need, rows: {'status': 'selected', 'skill': rows[0].name, 'confidence': 1}) as choose:
            result = market_protocol.dispatch(self.gateway, self.connection, self.gateway.Router(self.data), self.market,
                'acquire_skill', {'need': 'format text', 'market_selection': plan['id']})
        self.assertEqual([row.name for row in choose.call_args.args[1]], keys)
        self.assertEqual(result['source']['kind'], 'plugin')

    def test_dependency_prefetch_does_not_inherit_credentials_or_run_scripts(self):
        plan = self.plan()
        plan['servers'][0]['configuration'] = {'transport': 'stdio', 'command': ['npx', '--package=@example/test@1.2.3', 'test'], 'env': {}}
        process = Mock()
        process.wait.return_value = 0
        with patch('market_connect.subprocess.Popen', return_value=process) as launch, patch.dict(os.environ, {'SECRET_KEY': 'must-not-leak'}), patch('market_connect.shutil.which', return_value='/npm'), patch.object(self.market, 'dependency_installed', side_effect=[False, True]):
            self.market.prefetch(plan)
        command = launch.call_args.args[0]
        self.assertIn('--ignore-scripts', command)
        self.assertIn('--registry=https://registry.npmjs.org', command)
        self.assertNotIn('SECRET_KEY', launch.call_args.kwargs['env'])
        self.assertFalse(launch.call_args.kwargs.get('shell', False))

    def test_verified_existing_dependencies_do_not_repeat_installation(self):
        plan = self.plan()
        plan['servers'][0]['configuration'] = {'transport': 'stdio', 'command': ['npx', '--package=@example/test@1.2.3', 'test'], 'env': {}}
        with patch.object(self.market, 'dependency_installed', return_value=True), patch('market_connect.shutil.which', return_value='/npm'), patch('market_connect.subprocess.Popen') as launch:
            self.market.prefetch(plan)
        launch.assert_not_called()

    def test_published_row_does_not_bypass_interrupted_setup(self):
        plan = self.plan()
        plan['status'] = 'connecting'
        self.market.save(plan)
        row = plan['servers'][0]
        self.write(self.data / 'mcp-servers.json', {'version': 1, 'servers': {row['id']: row}})
        with self.assertRaisesRegex(ValueError, 'setup_interrupted'):
            self.market.server({'title': row['title'], 'description': row['description'], 'source': row['source'], 'configuration': row['configuration']}, {})

    def test_revocation_during_preparation_cannot_capture_a_fresh_marker(self):
        existing = self.plan()['servers'][0]
        self.write(self.data / 'mcp-servers.json', {'version': 1, 'servers': {existing['id']: existing}})
        def resolve_then_remove(plan, source, search):
            plan.update(name='example', source={'kind': 'registry'})
            plan['servers'] = [self.market.server(existing, plan)]
            self.write(self.data / 'mcp-servers.json', {'version': 1, 'servers': {}})
        with patch.object(self.market, 'prepare_mcp', side_effect=resolve_then_remove), self.assertRaisesRegex(ValueError, 'changed_reprepare'):
            self.market.prepare({'kind': 'mcp', 'source': 'registry', 'need': 'echo'})

    def test_manifest_optional_http_mcp_plugin(self):
        plan = self.plan(servers=False)
        root = Path(plan['package'])
        # Test fixture removal only, not a user's package.
        (root / 'plugin.json').unlink()
        self.write(root / '.mcp.json', {'mcpServers': {'docs': {'type': 'http', 'url': 'https://example.com/mcp'}}})
        self.assertEqual(self.market.inspect_plugin(root, plan), [])
        self.assertEqual(len(plan['servers']), 1)

    def test_unpinned_npx_eval_and_credentials_require_setup(self):
        for config in ({'command': 'npx', 'args': ['-y', 'some-package']},
                       {'command': 'node', 'args': ['-e', 'code']},
                       {'command': 'bash', 'args': ['script.sh']},
                       {'type': 'http', 'url': 'https://example.com', 'headers': {'Authorization': 'token'}},
                       {'command': 'node', 'args': ['${TOKEN}']}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                self.market.plugin_mcp(config, self.data)

    def test_all_local_plugin_scripts_are_deferred_including_traversal(self):
        outside = self.data / 'outside.py'
        outside.write_text('raise RuntimeError("must never execute")')
        root = self.data / 'package'
        root.mkdir()
        (root / 'inside.py').write_text('pass')
        for entry in (str(root / '../outside.py'), str(root / 'inside.py')):
            with self.assertRaisesRegex(ValueError, 'requires_native_host'):
                self.market.plugin_mcp({'command': 'python3', 'args': [entry]}, root)

    def test_server_identity_survives_source_revision_and_version_changes(self):
        value = {'title': 'test', 'description': 'test', 'source': {'kind': 'registry', 'version': '1'},
                 'configuration': {'transport': 'streamable-http', 'url': 'https://example.com/mcp'}}
        first = self.market.server(value, {})
        second = self.market.server({**value, 'source': {'kind': 'plugin', 'commit': 'new'}}, {})
        self.assertEqual(first['id'], second['id'])
        plan = self.plan()
        self.market.connect(plan['id'])
        registry = json.loads((self.data / 'mcp-servers.json').read_text())
        registry['servers'][first['id']]['enabled'] = False
        self.write(self.data / 'mcp-servers.json', registry)
        plan['servers'] = [second]
        with self.assertRaisesRegex(ValueError, 'changed_reprepare'):
            self.market.connect_servers(plan)
        self.assertFalse(json.loads((self.data / 'mcp-servers.json').read_text())['servers'][first['id']]['enabled'])

    def test_bad_component_metadata_cannot_poison_existing_registry(self):
        plan = self.plan()
        self.market.connect(plan['id'])
        before = (self.data / 'mcp-servers.json').read_bytes()
        value = {'title': 'x', 'description': 'x' * 1201, 'source': {},
                 'configuration': {'transport': 'streamable-http', 'url': 'https://example.com/mcp'}}
        with self.assertRaisesRegex(ValueError, 'invalid_market_server_metadata'):
            self.market.server(value, {})
        self.assertEqual(before, (self.data / 'mcp-servers.json').read_bytes())

    def test_incomplete_registry_never_selects_arbitrary_first_page(self):
        with patch.object(self.market.manager.mcp.sources, 'browse', return_value={'next_cursor': 'more', 'items': []}), patch.object(self.market, 'choose') as choose:
            result = self.market.prepare({'kind': 'mcp', 'source': 'registry', 'need': 'test'})
        self.assertEqual(result['status'], 'search_too_broad')
        choose.assert_not_called()

    def test_uncertain_market_never_downloads_or_connects(self):
        with patch.object(self.market.manager.plugins.sources, 'browse', return_value={'items': [{'name': 'sample', 'description': 'test'}]}), patch.object(self.market, 'choose', return_value=(None, {'status': 'uncertain', 'confidence': 0.3})):
            result = self.market.prepare({'kind': 'plugin', 'source': 'anthropic', 'need': 'test'})
        self.assertEqual(result['status'], 'uncertain')
        self.assertEqual(list(self.market.folder.iterdir()), [])

    def test_connect_preserves_unrelated_registry_rows(self):
        plan = self.plan()
        other = {**plan['servers'][0], 'id': 'f' * 32, 'title': 'existing', 'connections': []}
        self.write(self.data / 'mcp-servers.json', {'version': 1, 'servers': {other['id']: other}})
        plan['mcp_before'] = self.market.marker('mcp-servers.json')
        self.market.save(plan)
        self.market.connect(plan['id'])
        actual = json.loads((self.data / 'mcp-servers.json').read_text())['servers']
        self.assertEqual(actual[other['id']], other)

    def test_protocol_rechecks_descriptor_and_rejects_extra_arguments(self):
        reader = self.gateway.Router(self.data)
        with self.assertRaisesRegex(ValueError, 'invalid_arguments'):
            market_protocol.dispatch(self.gateway, self.connection, reader, self.market,
                                     'connect_market_capability', {'selection': 'a', 'command': 'anything'})
        self.write(self.descriptor, {**self.value, 'enabled': False})
        with self.assertRaisesRegex(ValueError, 'connection_disabled'):
            market_protocol.dispatch(self.gateway, self.connection, reader, self.market, 'prepare_market_capability', {})

    def test_actual_stdio_startup_exposes_extension_and_keeps_empty_inventory(self):
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25'}},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'resources/list'},
        ]
        result = subprocess.run([sys.executable, str(ADAPTER / 'market_gateway.py'), '--runtime-root', RUNTIME,
                                 '--connection', str(self.descriptor)], input=''.join(json.dumps(m) + '\n' for m in messages),
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        tools = {t['name']: t for t in replies[1]['result']['tools']}
        self.assertEqual(len(tools), 7)
        self.assertIn('prepare_market_capability', tools)
        self.assertIn('market_selection', tools['acquire_skill']['inputSchema']['properties'])
        self.assertEqual(replies[2]['result'], {'resources': []})


if __name__ == '__main__':
    unittest.main()
