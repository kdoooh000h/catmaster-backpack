"""Isolated packaging/version tests; no model calls or daily host profiles."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from catmaster_backpack import plugin_pipeline as pipeline, plugin_release as release


class PluginReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        self.store = self.root / 'store'
        pipeline.init_store(self.store, self.project)

    def installation(self, version, adapter_change=None):
        target = self.root / ('release-' + version)
        package = target / 'catmaster_backpack'
        shutil.copytree(ROOT / 'src/catmaster_backpack', package,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        (package / '__init__.py').write_text('__version__ = "' + version + '"\n')
        metadata = target / ('catmaster_backpack-' + version + '.dist-info/METADATA')
        metadata.parent.mkdir()
        metadata.write_text('Name: catmaster-backpack\nVersion: ' + version + '\n')
        if adapter_change:
            adapter = package / 'data/adapters/qwen-code/plugin_pipes.py'
            text = adapter.read_text()
            change = ("settings['adapter_revision'] = 'fixture'\n    " if adapter_change == 'changed' else
                      "write(profile / 'unrecorded.json', {'fixture': True})\n    ")
            adapter.write_text(text.replace('write(settings_path, settings)', change + 'write(settings_path, settings)'))
        with patch.object(release, '__file__', str(package / 'plugin_release.py')):
            return release.snapshot()

    def connect(self, runtime, host='qwen-code'):
        profile = self.root / ('profile-' + host)
        with patch.object(release, 'snapshot', return_value=runtime):
            result = pipeline.connect_host(self.store, host, profile)
        connection = profile / 'backpack-connection.json'
        return connection, result

    def switch(self, connection, runtime, **kwargs):
        with patch.object(release, 'snapshot', return_value=runtime):
            return release.switch_release(connection, host_stopped=True, **kwargs)

    def bridge_version(self, connection):
        result = subprocess.run([sys.executable, '-I', str(connection.parent / 'backpack-runtime.py'),
                                 'version', '--connection', str(connection)],
                                capture_output=True, text=True, cwd=self.root, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_six_host_wheel_paths_switch_and_rollback_without_host_config_changes(self):
        old, new = self.installation('0.2.0'), self.installation('0.2.1')
        for host in pipeline.HOSTS:
            with self.subTest(host=host):
                connection, _ = self.connect(old, host)
                receipt = release.read_receipt(connection)
                before = {p: Path(p).read_bytes() for p in receipt['configuration']}
                self.assertEqual(self.bridge_version(connection)['caller_version'], '0.2.0')
                self.assertEqual(self.switch(connection, new)['status'], 'upgraded')
                self.assertEqual(self.bridge_version(connection)['caller_version'], '0.2.1')
                # Reconnecting from the new CLI retains the original launch argv.
                with patch.object(release, 'snapshot', return_value=new):
                    pipeline.connect_host(self.store, host, connection.parent)
                self.assertEqual(before, {p: Path(p).read_bytes() for p in before})
                self.assertEqual(self.switch(connection, new, rollback=True)['status'], 'rolled_back')
                self.assertEqual(self.bridge_version(connection)['caller_version'], '0.2.0')
                self.assertEqual(before, {p: Path(p).read_bytes() for p in before})
                self.assertTrue(list(connection.parent.glob('backpack-release.json.before-backpack-*')))
                self.assertTrue(Path(old['runtime']).is_file())
                self.assertTrue(Path(new['runtime']).is_file())

    def test_config_conflict_blocks_upgrade_and_rollback_without_writes(self):
        old, new = self.installation('0.2.0'), self.installation('0.2.1')
        connection, _ = self.connect(old)
        settings = connection.parent / 'settings.json'
        original = settings.read_bytes()
        for rollback in (False, True):
            if rollback:
                settings.write_bytes(original)
                self.switch(connection, new)
            changed = json.loads(settings.read_text()); changed['model'] = {'name': 'changed-model'}
            settings.write_text(json.dumps(changed))
            changed_bytes = settings.read_bytes()
            before = release.receipt_path(connection).read_bytes()
            with self.assertRaisesRegex(ValueError, 'managed_configuration_changed'):
                self.switch(connection, new, rollback=rollback)
            self.assertEqual(before, release.receipt_path(connection).read_bytes())
            self.assertEqual(settings.read_bytes(), changed_bytes)

    def test_new_connection_preserves_existing_unmanaged_bridge_and_host_bytes(self):
        for kind in ('file', 'symlink', 'dangling_symlink'):
            with self.subTest(kind=kind):
                profile = self.root / ('unmanaged-' + kind)
                profile.mkdir()
                bridge = profile / 'backpack-runtime.py'
                target = self.root / ('bridge-target-' + kind)
                if kind == 'file':
                    bridge.write_bytes(b'unmanaged bridge sentinel\n')
                else:
                    if kind == 'symlink':
                        target.write_bytes(b'unmanaged symlink target sentinel\n')
                    bridge.symlink_to(target)
                settings = profile / 'settings.json'
                settings.write_bytes(b'{"theme": "unmanaged sentinel"}\n')
                mcp = self.project / '.mcp.json'
                mcp.write_bytes(b'{"mcpServers": {"other": {"command": "existing"}}}\n')
                before = {settings:settings.read_bytes(), mcp:mcp.read_bytes()}
                bridge_before = os.readlink(bridge) if bridge.is_symlink() else bridge.read_bytes()
                with self.assertRaisesRegex(ValueError, 'existing_runtime_bridge_conflict'):
                    pipeline.connect_host(self.store, 'claude-code', profile)
                self.assertEqual(before, {path:path.read_bytes() for path in before})
                self.assertEqual(bridge_before, os.readlink(bridge) if bridge.is_symlink() else bridge.read_bytes())
                if target.exists():
                    self.assertEqual(target.read_bytes(), b'unmanaged symlink target sentinel\n')
                self.assertFalse((profile/'backpack-connection.json').exists())
                self.assertFalse((profile/'backpack-release.json').exists())

    def test_changed_adapter_reconnect_refuses_changed_or_extra_targets_before_commit(self):
        old = self.installation('0.2.0')
        connection, _ = self.connect(old)
        receipt = release.read_receipt(connection)
        before = {Path(p):Path(p).read_bytes() for p in receipt['configuration']}
        before[release.receipt_path(connection)] = release.receipt_path(connection).read_bytes()
        for change, version in [('changed', '0.2.2'), ('extra', '0.2.3')]:
            with self.subTest(change=change):
                new = self.installation(version, adapter_change=change)
                with patch.object(pipeline, '__file__', new['runtime']), patch.object(release, 'snapshot', return_value=new):
                    with self.assertRaisesRegex(ValueError, 'managed_reconnect_configuration_conflict'):
                        pipeline.connect_host(self.store, 'qwen-code', connection.parent)
                self.assertEqual(before, {p:p.read_bytes() for p in before})
                self.assertFalse((connection.parent/'unrecorded.json').exists())
                self.assertFalse(list(connection.parent.glob('*.before-backpack-*')))

    def test_damaged_current_runtime_also_refuses_rollback(self):
        old, new = self.installation('0.2.0'), self.installation('0.2.1')
        connection, _ = self.connect(old)
        self.switch(connection, new)
        before = release.receipt_path(connection).read_bytes()
        Path(new['runtime']).write_text('damaged current runtime')
        with self.assertRaisesRegex(ValueError, 'retained_runtime_changed'):
            self.switch(connection, new, rollback=True)
        self.assertEqual(before, release.receipt_path(connection).read_bytes())

    def codex_with_native_state_fixture(self):
        """Synthetic TOML only; this neither grants nor proves native Hook trust."""
        profile = self.root/'profile-codex'
        profile.mkdir()
        config = profile/'config.toml'
        config.write_text('model = "fixture-model"\nmodel_provider = "fixture-provider"\n'
                          'approval_policy = "on-request"\nsandbox_mode = "workspace-write"\n')
        old = self.installation('0.2.2')
        connection, _ = self.connect(old, 'codex')
        native = (b'\n# synthetic unit fixture; no native trust granted\n'
                  b'[hooks.state."fixture-hook"]\ntrusted_hash = "synthetic-unit-fixture"\n'
                  b'[tui]\nscreen_reader_detection_done = true\n')
        config.write_bytes(config.read_bytes()+native)
        return old, connection, config

    def test_codex_native_state_view_accepts_only_native_state_and_preserves_bytes(self):
        old, connection, config = self.codex_with_native_state_fixture()
        new = self.installation('0.2.3')
        receipt = release.read_receipt(connection)
        self.assertEqual(receipt['configuration_views'][str(config)], release.CODEX_CONFIG_VIEW)
        self.assertEqual(receipt['configuration_views'][str(connection)], release.BYTE_VIEW)
        self.assertEqual(receipt['configuration_views'][str(config.parent/'hooks.json')], release.BYTE_VIEW)
        config.write_bytes(b'# unrelated formatting comment\n' + config.read_bytes())
        release.version_status(connection)
        before = {Path(p):Path(p).read_bytes() for p in receipt['configuration']}
        self.assertEqual(self.switch(connection,new)['status'],'upgraded')
        with patch.object(release, 'snapshot', return_value=new):
            pipeline.connect_host(self.store,'codex',connection.parent)
        self.assertEqual(before,{p:p.read_bytes() for p in before})
        self.assertEqual(self.switch(connection,new,rollback=True)['status'],'rolled_back')
        self.assertEqual(before,{p:p.read_bytes() for p in before})

    def test_codex_view_rejects_mcp_provider_permission_hook_and_other_config_changes(self):
        old, connection, config = self.codex_with_native_state_fixture()
        new = self.installation('0.2.3')
        original = config.read_bytes()
        variants = {
            'model': original.replace(b'fixture-model',b'changed-model'),
            'provider': original.replace(b'fixture-provider',b'changed-provider'),
            'provider_definition': original+b'\n[model_providers.fixture-provider]\nbase_url="https://example.invalid/changed"\n',
            'permissions': original.replace(b'on-request',b'never'),
            'sandbox': original.replace(b'workspace-write',b'danger-full-access'),
            'mcp_definition': original+b'\n[mcp_servers.backpack.env]\nFIXTURE="changed"\n',
            'hook_definition': original+b'\n[hooks]\nenabled=false\n',
            'other_tui': original+b'other_native_property=true\n',
            'lookalike_state': original+b'\n[other_hooks.state]\ntrusted_hash="different"\n',
        }
        before_receipt=release.receipt_path(connection).read_bytes()
        for label,raw in variants.items():
            with self.subTest(label=label):
                config.write_bytes(raw)
                with self.assertRaisesRegex(ValueError,'managed_configuration_changed'):
                    self.switch(connection,new)
                self.assertEqual(config.read_bytes(),raw)
                self.assertEqual(release.receipt_path(connection).read_bytes(),before_receipt)
        config.write_bytes(original)
        for target in (config.parent/'hooks.json',config.parent/'backpack-runtime.py',connection):
            with self.subTest(exact_file=target.name):
                before=target.read_bytes()
                if target.name=='hooks.json':
                    body=json.loads(before)
                    body['hooks']['SessionStart'][0]['hooks'][0]['command']+=' --fixture-changed'
                    changed=json.dumps(body).encode()
                else:
                    changed=before+b'\n'
                target.write_bytes(changed)
                with self.assertRaisesRegex(ValueError,'managed_configuration_changed'):
                    self.switch(connection,new)
                self.assertEqual(target.read_bytes(),changed)
                self.assertEqual(release.receipt_path(connection).read_bytes(),before_receipt)
                target.write_bytes(before)

    def test_codex_native_view_cannot_rewrite_excluded_state_during_reconnect(self):
        _,connection,config = self.codex_with_native_state_fixture()
        receipt=release.read_receipt(connection)
        before=config.read_bytes()
        plan=pipeline.WritePlan()
        plan.text(config,before.decode().replace('synthetic-unit-fixture','other-unit-fixture'))
        with self.assertRaisesRegex(ValueError,'managed_reconnect_configuration_conflict'):
            release.verify_reconnect_plan(plan,receipt)
        self.assertEqual(config.read_bytes(),before)

    def test_old_codex_receipt_without_view_remains_byte_pinned(self):
        profile=self.root/'profile-codex'
        old=self.installation('0.2.1')
        connection,_=self.connect(old,'codex')
        config=profile/'config.toml'
        receipt=release.read_receipt(connection)
        receipt.pop('configuration_views')
        receipt['configuration'][str(config)]=release.digest(config)
        release.receipt_path(connection).write_text(json.dumps(receipt))
        before=release.receipt_path(connection).read_bytes()
        raw=config.read_bytes()+b'\n[tui]\nscreen_reader_detection_done=true\n'
        config.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'managed_configuration_changed'):
            self.switch(connection,self.installation('0.2.2'))
        self.assertEqual(release.receipt_path(connection).read_bytes(),before)
        self.assertEqual(config.read_bytes(),raw)

    def test_codex_configuration_view_scope_and_toml_types_stay_distinct(self):
        _,connection,config=self.codex_with_native_state_fixture()
        receipt=release.read_receipt(connection)
        receipt['configuration_views'][str(connection)]=release.CODEX_CONFIG_VIEW
        with self.assertRaisesRegex(ValueError,'configuration_view_scope_conflict'):
            release.verify_profile(receipt)
        samples=[b'value=1\n',b'value="1"\n',b'value=true\n',b'value=2026-10-10\n',b'value="2026-10-10"\n']
        self.assertEqual(len({release.configuration_digest(raw,release.CODEX_CONFIG_VIEW) for raw in samples}),len(samples))

    def test_changed_runtime_blocks_switch_and_bridge_execution(self):
        old, new = self.installation('0.2.0'), self.installation('0.2.1')
        connection, _ = self.connect(old)
        Path(old['runtime']).write_text('raise RuntimeError("modified")\n')
        before = release.receipt_path(connection).read_bytes()
        with self.assertRaisesRegex(ValueError, 'retained_runtime_changed'):
            self.switch(connection, new)
        result = subprocess.run([sys.executable, '-I', str(connection.parent / 'backpack-runtime.py'),
                                 'version', '--connection', str(connection)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('modified', result.stderr)
        self.assertEqual(before, release.receipt_path(connection).read_bytes())

    def test_changed_rollback_candidate_refused(self):
        old, new = self.installation('0.2.0'), self.installation('0.2.1')
        connection, _ = self.connect(old)
        self.switch(connection, new)
        Path(old['runtime']).write_text('changed prior version')
        before = release.receipt_path(connection).read_bytes()
        with self.assertRaisesRegex(ValueError, 'retained_runtime_changed'):
            self.switch(connection, new, rollback=True)
        self.assertEqual(before, release.receipt_path(connection).read_bytes())

    def test_active_sessions_or_peers_refuse_switch_unknown_receipts_retained(self):
        old, new = self.installation('0.2.0'), self.installation('0.2.1')
        connection, _ = self.connect(old)
        identity = pipeline.read_json(connection)['connection_id']
        db = sqlite3.connect(self.store / 'pipeline-state.sqlite')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE sessions(connection_id TEXT,ready INTEGER)')
        db.execute('CREATE TABLE connector_peers(connection_id TEXT,active INTEGER)')
        db.execute('CREATE TABLE operations(id TEXT,status TEXT)')
        db.execute("INSERT INTO operations VALUES('unknown-op','unknown')")
        for table, flag in [('sessions', 'ready'), ('connector_peers', 'active')]:
            db.execute(f'INSERT INTO {table} VALUES(?,1)', (identity,))
            db.commit()
            before = release.receipt_path(connection).read_bytes()
            with self.assertRaisesRegex(ValueError, 'active_native_connection_refuses_release_switch'):
                self.switch(connection, new)
            self.assertEqual(before, release.receipt_path(connection).read_bytes())
            db.execute(f'UPDATE {table} SET {flag}=0')
            db.commit()
        self.switch(connection, new)
        self.switch(connection, new, rollback=True)
        self.assertEqual(db.execute('SELECT * FROM operations').fetchall(), [('unknown-op', 'unknown')])

    def test_legacy_connection_is_not_silently_adopted(self):
        profile = self.root / 'legacy'
        profile.mkdir()
        connection = profile / 'backpack-connection.json'
        descriptor = {'schema': pipeline.SCHEMA, 'host': 'qwen-code', 'store': str(self.store),
                      'project_root': str(self.project), 'profile_root': str(profile),
                      'connection_id': pipeline.hashlib.sha256((str(self.store) + 'qwen-code' + str(profile)).encode()).hexdigest()[:32]}
        connection.write_text(json.dumps(descriptor))
        result = pipeline.connect_host(self.store, 'qwen-code', profile)
        self.assertEqual(result['release']['status'], 'unmanaged')
        self.assertFalse(release.receipt_path(connection).exists())
        self.assertFalse((profile / 'backpack-runtime.py').exists())
        before = connection.read_bytes()
        with self.assertRaises(ValueError):
            release.switch_release(connection, host_stopped=True)
        self.assertEqual(before, connection.read_bytes())

    def test_legacy_connection_dangling_receipt_symlink_refuses_before_host_writes(self):
        profile = self.root / 'legacy-dangling-receipt'
        profile.mkdir()
        connection = profile / 'backpack-connection.json'
        descriptor = {'schema': pipeline.SCHEMA, 'host': 'qwen-code', 'store': str(self.store),
                      'project_root': str(self.project), 'profile_root': str(profile),
                      'connection_id': pipeline.hashlib.sha256((str(self.store) + 'qwen-code' + str(profile)).encode()).hexdigest()[:32]}
        connection.write_text(json.dumps(descriptor))
        settings = profile / 'settings.json'
        settings.write_bytes(b'{"theme":"legacy unmanaged sentinel"}\n')
        path = release.receipt_path(connection)
        path.symlink_to(profile / 'missing-receipt')
        before = {p:p.read_bytes() for p in (connection, settings)}
        with self.assertRaisesRegex(ValueError, 'release_receipt_symlink_refused'):
            pipeline.connect_host(self.store, 'qwen-code', profile)
        self.assertEqual(before, {p:p.read_bytes() for p in before})
        self.assertTrue(path.is_symlink())
        self.assertEqual(os.readlink(path), str(profile / 'missing-receipt'))
        self.assertFalse((profile/'backpack-runtime.py').exists())
        self.assertFalse(list(profile.glob('*.before-backpack-*')))

    def test_source_mode_and_non_newer_candidate_are_not_upgrade_paths(self):
        old, same = self.installation('0.2.0'), self.installation('0.2.1')
        connection, _ = self.connect(old)
        before = release.receipt_path(connection).read_bytes()
        source = {**same, 'installation': 'source_checkout'}
        with self.assertRaisesRegex(ValueError, 'retained_wheel_installations'):
            self.switch(connection, source)
        downgrade = {**same, 'version': '0.1.0'}
        with self.assertRaisesRegex(ValueError, 'candidate_version_not_newer'):
            self.switch(connection, downgrade)
        with self.assertRaisesRegex(ValueError, 'host_stop_confirmation_required'):
            release.switch_release(connection)
        self.assertEqual(self.switch(connection, old)['status'], 'already_current')
        self.assertEqual(before, release.receipt_path(connection).read_bytes())

    def test_version_receipt_symlink_is_refused(self):
        connection, _ = self.connect(self.installation('0.2.0'))
        path = release.receipt_path(connection)
        saved = path.with_suffix('.saved')
        path.rename(saved)
        path.symlink_to(saved)
        with self.assertRaisesRegex(ValueError, 'release_receipt_symlink_refused'):
            release.version_status(connection)

    def test_public_cli_version_matches_project(self):
        import tomllib
        version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
        result = subprocess.run([sys.executable, '-m', 'catmaster_backpack', '--version'], cwd=ROOT,
                                env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(version, result.stdout)

    def test_qwen_native_version_marker_and_formatting_preserve_settings_bytes(self):
        old, new = self.installation('0.2.0'), self.installation('0.2.1')
        connection, _ = self.connect(old)
        receipt = release.read_receipt(connection)
        settings = [connection.parent / 'settings.json', self.project / '.qwen/settings.json']
        for path in settings:
            self.assertEqual(receipt['configuration_views'][str(path)], release.QWEN_CONFIG_VIEW)
            value = json.loads(path.read_text()); value['$version'] = 4
            path.write_text(json.dumps(value, sort_keys=True, indent=4))
        before = {path: path.read_bytes() for path in settings}
        self.assertEqual(release.version_status(connection)['status'], 'verified')
        self.assertEqual(self.switch(connection, new)['status'], 'upgraded')
        self.assertEqual(before, {path: path.read_bytes() for path in settings})

    def test_qwen_model_permissions_MCP_and_hooks_remain_protected(self):
        connection, _ = self.connect(self.installation('0.2.0'))
        cases = [('model', {'name': 'changed'}), ('security', {'approvalMode': 'yolo'}),
                 ('mcpServers', {'unrelated': {'command': 'changed'}}), ('hooks', {})]
        for path in [connection.parent / 'settings.json', self.project / '.qwen/settings.json']:
            before = path.read_bytes()
            for key, changed in cases:
                with self.subTest(path=path.name, field=key):
                    value = json.loads(before); value[key] = changed
                    if value == json.loads(before):
                        value[key] = {'changed': True}
                    path.write_text(json.dumps(value))
                    with self.assertRaisesRegex(ValueError, 'managed_configuration_changed'):
                        release.version_status(connection)
                    path.write_bytes(before)

    def test_qwen_view_rejects_invalid_JSON_marker_and_wrong_scope(self):
        for raw in [b'{"$version":"4"}', b'{"$version":true}', b'{"$version":-1}', b'{"$version":null}',
                    b'{"model":1,"model":2}', b'{"value":NaN}', b'[]']:
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'managed_qwen_config_invalid'):
                release.configuration_digest(raw, release.QWEN_CONFIG_VIEW)
        connection, _ = self.connect(self.installation('0.2.0'))
        receipt = release.read_receipt(connection)
        receipt['configuration_views'][str(connection)] = release.QWEN_CONFIG_VIEW
        with self.assertRaisesRegex(ValueError, 'configuration_view_scope_conflict'):
            release.verify_profile(receipt)

    def test_old_qwen_byte_receipt_remains_strict_and_not_silently_migrated(self):
        connection, _ = self.connect(self.installation('0.2.0'))
        receipt = release.read_receipt(connection)
        for path in [connection.parent / 'settings.json', self.project / '.qwen/settings.json']:
            receipt['configuration_views'][str(path)] = release.BYTE_VIEW
            receipt['configuration'][str(path)] = release.configuration_digest(path.read_bytes())
        saved = json.dumps(receipt, indent=2).encode(); release.receipt_path(connection).write_bytes(saved)
        path = self.project / '.qwen/settings.json'; value = json.loads(path.read_text()); value['$version'] = 4
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'managed_configuration_changed'):
            release.version_status(connection)
        self.assertEqual(release.receipt_path(connection).read_bytes(), saved)

    def test_public_pipeline_help_exposes_operator_release_actions(self):
        result = subprocess.run([sys.executable, '-m', 'catmaster_backpack', 'pipelines', '--help'], cwd=ROOT,
                                env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('upgrade', result.stdout)
        self.assertIn('rollback', result.stdout)

    def test_bridge_serves_fixed_mcp_tools_from_retained_runtime(self):
        connection, _ = self.connect(self.installation('0.2.0'))
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': '2025-11-25', 'capabilities': {},
                'clientInfo': {'name': 'release-fixture', 'version': '1'}}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        ]
        result = subprocess.run([sys.executable, '-I', str(connection.parent / 'backpack-runtime.py'),
                                 'serve', '--connection', str(connection)],
                                input=''.join(json.dumps(m) + '\n' for m in messages),
                                capture_output=True, text=True, cwd=self.root, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = {r['id']: r for r in map(json.loads, result.stdout.splitlines()) if 'id' in r}
        self.assertIn('result', responses[1])
        self.assertEqual({t['name'] for t in responses[2]['result']['tools']}, {'acquire', 'invoke'})
        # EOF closes the observed peer; release switching can proceed afterwards.
        release.verify_stopped(self.store, pipeline.read_json(connection)['connection_id'])


if __name__ == '__main__':
    unittest.main()
