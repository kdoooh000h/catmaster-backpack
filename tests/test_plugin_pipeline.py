"""Critical registry/connection/delivery behavior; fixtures are explicitly simulated."""
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/catmaster_backpack'))
from plugin_pipeline import add_plugin, connect_host, init_store, inspect_plugin, load_registry, plugin_unchanged
from plugin_pipeline import LIMIT, atomic_json, read_json, unregister_plugin
from plugin_runtime import Gateway as KernelGateway, dispatch_event, run_bounded
from plugin_release import configuration_digest, QWEN_CONFIG_VIEW


def Gateway(connection):
    """Explicit simulated client handshake; never counted as native evidence."""
    gateway = KernelGateway(connection)
    gateway.initialize({'protocolVersion': '2024-11-05', 'capabilities': {},
                        'clientInfo': {'name': 'simulated-fixture-client', 'version': '1'}})
    gateway.observed('tools/list')
    return gateway

INDEX = {'tools': [{'name': 'sample', 'description': 'sample fixture', 'inputSchema': {'type': 'object'}}], 'resources': []}
HANDSHAKE = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'simulated', 'version': '1'}}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.root = Path(self.temp.name)
        self.project = self.root / 'project';self.project.mkdir()
        self.store = self.root / 'store';init_store(self.store, self.project)
        self.profile = self.root / 'profile'
        self.connection = self.profile / 'backpack-connection.json'

    def tearDown(self):
        self.temp.cleanup()

    def plugin(self, name, event='SessionStart', output=None):
        root = self.root / name;(root / '.claude-plugin').mkdir(parents=True)
        (root / '.claude-plugin/plugin.json').write_text(json.dumps({'name': name}))
        (root / 'hooks').mkdir()
        script = root / 'hook.py'
        value = output or {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': name + '-guide'}}
        script.write_text('import json,sys\nevent=json.load(sys.stdin)\nprint(' + repr(json.dumps(value)) + ')\n')
        (root / 'hooks/hooks.json').write_text(json.dumps({'hooks': {event: [{'matcher': '', 'hooks': [
            {'type': 'command', 'command': sys.executable, 'args': [str(script)], 'timeout': 1}]}]}}))
        return root

    def start(self, session='s1', delivery='d1'):
        return dispatch_event(self.connection, {'hook_event_name': 'SessionStart', 'session_id': session,
                                              'cwd': str(self.project), 'delivery_id': delivery})

    def token(self, result):
        return re.search(r'session_token=([^ ]+)', '\n'.join(result['context']))[1]

    def service(self, name='service', failure=False):
        package = self.plugin(name)
        script = package / 'server.py'
        script.write_text('import json,sys\nfor line in sys.stdin:\n p=json.loads(line)\n if "id" not in p: continue\n'
            ' m=p["method"]\n r=' + repr(HANDSHAKE) + ' if m=="initialize" else ' + repr(INDEX) + ' if m=="tools/list" else {"resources":[]} if m=="resources/list" else '
            + repr({'content': [{'type': 'text', 'text': 'observed'}], 'isError': failure}) + ' if m=="tools/call" else {}\n'
            ' print(json.dumps({"jsonrpc":"2.0","id":p["id"],"result":r}),flush=True)\n')
        (package / '.mcp.json').write_text(json.dumps({'mcpServers': {name: {'command': sys.executable, 'args': [str(script)]}}}))
        add_plugin(self.store, package);connect_host(self.store, 'claude-code', self.profile)
        return package

    def select(self, gateway, token, kind='tool'):
        with patch('plugin_runtime.pick', side_effect=lambda need, entries: {'status':'selected', 'choice': next(k for k,v in entries.items() if v['kind']==kind), 'confidence':1}):
            return gateway.acquire('public fixture', token)['selection']

    def test_new_plugin_after_connect_uses_existing_pipe(self):
        result = connect_host(self.store, 'claude-code', self.profile)
        settings = Path(result['settings_file']);before = settings.read_bytes()
        add_plugin(self.store, self.plugin('later'))
        output = self.start()
        self.assertIn('later-guide', output['context'])
        self.assertEqual(before, settings.read_bytes())
        self.assertTrue(Path(self.project / '.mcp.json').is_file())
        self.assertEqual(set(json.loads((self.project / '.mcp.json').read_text())['mcpServers']), {'backpack'})

    def test_atomic_json_size_boundary_preserves_previous_readable_bytes(self):
        path = self.root / 'bounded.json'
        value = 'x' * (LIMIT - 3)  # Two quotes and one trailing newline.
        atomic_json(path, value)
        self.assertEqual(path.stat().st_size, LIMIT)
        self.assertEqual(read_json(path), value)
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'json_output_too_large'):
            atomic_json(path, value + '\u96ea')  # Check encoded UTF-8 bytes, not characters.
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.root.glob('bounded.json.before-backpack-*')), [])

    def test_large_registration_cannot_make_registry_unreadable(self):
        index = {'tools': [
            {'name': 'tool_' + str(i), 'description': 'x' * 7000,
             'inputSchema': {'type': 'object'}} for i in range(100)
        ], 'resources': []}
        self.assertLess(len(json.dumps(index).encode()), LIMIT)
        packages = [self.plugin(name) for name in ['large-one', 'large-two']]
        for package in packages:
            (package / '.mcp.json').write_text(json.dumps({'mcpServers': {'sample': {
                'command': sys.executable, 'args': [str(package / 'hook.py')]}}}))
        with patch('plugin_runtime.discover_server', return_value=index):
            self.assertEqual(add_plugin(self.store, packages[0])['status'], 'registered')
            path = self.store / 'registry.json'
            before = path.read_bytes()
            previous = load_registry(self.store)[2]
            with self.assertRaisesRegex(ValueError, 'json_output_too_large'):
                add_plugin(self.store, packages[1])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(load_registry(self.store)[2], previous)
        self.assertEqual(unregister_plugin(self.store, 'large-one')['status'], 'unregistered')
        self.assertEqual(load_registry(self.store)[2]['plugins'], {})

    def test_pattern_schema_round_trip_reaches_only_valid_leaf_arguments(self):
        package = self.plugin('pattern-service')
        calls = self.root / 'pattern-calls.jsonl'
        index = {'tools': [{'name': 'pattern-tool', 'description': 'Fixture dynamic keys',
                            'inputSchema': {'type': 'object',
                                            'patternProperties': {'^x-': {'type': 'string'}},
                                            'additionalProperties': False}}], 'resources': []}
        script = package / 'server.py'
        script.write_text(
            'import json,sys,pathlib\nfor line in sys.stdin:\n p=json.loads(line)\n'
            ' if "id" not in p: continue\n m=p["method"]\n'
            ' if m=="tools/call":\n'
            '  with pathlib.Path(' + repr(str(calls)) + ').open("a") as f:f.write(json.dumps(p["params"]["arguments"])+"\\n")\n'
            '  r={"content":[{"type":"text","text":json.dumps(p["params"]["arguments"])}]}\n'
            ' else:r=' + repr(HANDSHAKE) + ' if m=="initialize" else ' + repr(index)
            + ' if m=="tools/list" else {"resources":[]} if m=="resources/list" else {}\n'
            ' print(json.dumps({"jsonrpc":"2.0","id":p["id"],"result":r}),flush=True)\n')
        (package / '.mcp.json').write_text(json.dumps({'mcpServers': {'sample': {
            'command': sys.executable, 'args': [str(script)]}}}))
        add_plugin(self.store, package)
        connect_host(self.store, 'claude-code', self.profile)
        token = self.token(self.start())
        gateway = Gateway(self.connection)
        selection = self.select(gateway, token)
        result = gateway.invoke(selection, {'x-foo': 'ok'}, token)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(json.loads(result['result']['content'][0]['text']), {'x-foo': 'ok'})
        rejected = self.select(gateway, token)
        with self.assertRaisesRegex(ValueError, '^unexpected_argument$'):
            gateway.invoke(rejected, {'other': 'bad'}, token)
        self.assertEqual(calls.read_text().splitlines(), [json.dumps({'x-foo': 'ok'})])

    def test_existing_native_settings_preserved_and_connect_idempotent(self):
        self.profile.mkdir();(self.profile / 'settings.json').write_text(json.dumps({'permissions': {'deny': ['Bash(rm:*)']}, 'theme': 'dark'}))
        one = connect_host(self.store, 'claude-code', self.profile)
        path = Path(one['settings_file']);snapshot = path.read_bytes()
        connect_host(self.store, 'claude-code', self.profile)
        self.assertEqual(snapshot, path.read_bytes())
        self.assertEqual(json.loads(snapshot)['theme'], 'dark')
        self.assertEqual(json.loads(snapshot)['permissions'], {'deny': ['Bash(rm:*)']})

    def test_changed_registered_hook_script_does_not_execute(self):
        package = self.plugin('immutable');add_plugin(self.store, package)
        connect_host(self.store, 'claude-code', self.profile)
        (package / 'hook.py').write_text('raise RuntimeError("changed")')
        result = self.start()
        self.assertTrue(result['blocked'])
        self.assertEqual(result['status'], 'unknown')

    def test_receipt_replay_and_changed_delivery_input(self):
        add_plugin(self.store, self.plugin('delivery'));connect_host(self.store, 'claude-code', self.profile)
        first = self.start();self.assertEqual(first, self.start())
        conflict = dispatch_event(self.connection, {'hook_event_name': 'SessionStart', 'session_id': 's1',
            'cwd': str(self.project), 'delivery_id': 'd1', 'source': 'resume'})
        self.assertTrue(conflict['blocked']);self.assertEqual(conflict['reason'], 'delivery_input_conflict')

    def test_hook_cannot_grant_host_permission(self):
        add_plugin(self.store, self.plugin('grant', 'PreToolUse', {'hookSpecificOutput': {
            'hookEventName': 'PreToolUse', 'permissionDecision': 'allow'}}))
        connect_host(self.store, 'claude-code', self.profile)
        result = dispatch_event(self.connection, {'hook_event_name': 'PreToolUse', 'session_id': 's1',
            'cwd': str(self.project), 'tool_name': 'Read', 'tool_use_id': 'call'})
        self.assertTrue(result['blocked'])
        self.assertNotIn('permissionDecision', result)

    def test_scope_escape_and_unsupported_host_event(self):
        connect_host(self.store, 'factory-droid', self.profile)
        with self.assertRaisesRegex(ValueError, 'scope'):
            dispatch_event(self.connection, {'hook_event_name': 'SessionStart', 'session_id': 's', 'cwd': str(self.root)})
        add_plugin(self.store, self.plugin('failure', 'PostToolUseFailure'))
        ready = connect_host(self.store, 'factory-droid', self.profile)['plugin_readiness']['failure']
        self.assertFalse(ready['ready']);self.assertIn('host_event:PostToolUseFailure', ready['unsupported'])

    def native_hook(self, event, settings_file=None):
        settings = json.loads((Path(settings_file) if settings_file else self.profile / 'settings.json').read_text())
        command = settings['hooks']['SessionStart'][0]['hooks'][0]['command']
        return subprocess.run(shlex.split(command), input=json.dumps(event), text=True,
                              capture_output=True, cwd=self.root, timeout=10)

    def scope_fixture(self, host='claude-code'):
        marker = self.root / 'hook-executions.txt'
        package = self.plugin('scope')
        script = package / 'hook.py'
        script.write_text(script.read_text() + '\nwith open(' + repr(str(marker)) +
                          ', "a") as f: f.write(event["cwd"] + "\\n")\n')
        path = package / 'hooks/hooks.json'
        hooks = json.loads(path.read_text())['hooks']
        for name in ('UserPromptSubmit', 'PreToolUse', 'Stop'):
            hooks[name] = hooks['SessionStart']
        path.write_text(json.dumps({'hooks': hooks}))
        add_plugin(self.store, package)
        connect_host(self.store, host, self.profile)
        return marker

    def test_native_cc_outside_callbacks_are_silent_without_database_or_hook_effects(self):
        marker = self.scope_fixture()
        before = {str(p.relative_to(self.store)): p.read_bytes() for p in self.store.rglob('*') if p.is_file()}
        for name in ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'Stop'):
            with self.subTest(event=name):
                result = self.native_hook({'hook_event_name': name, 'session_id': 'outside',
                                           'cwd': str(self.root), 'tool_name': 'Read'})
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
                self.assertFalse((self.store / 'pipeline-state.sqlite').exists())
                self.assertFalse(marker.exists())
                self.assertEqual(before, {str(p.relative_to(self.store)): p.read_bytes()
                                         for p in self.store.rglob('*') if p.is_file()})

    def test_native_cc_project_and_child_callbacks_execute_and_outside_preserves_database(self):
        marker = self.scope_fixture()
        child = self.project / 'child';child.mkdir()
        for i, cwd in enumerate((self.project, child)):
            with self.subTest(cwd=cwd):
                result = self.native_hook({'hook_event_name': 'SessionStart', 'session_id': 'inside-' + str(i),
                                           'cwd': str(cwd), 'delivery_id': 'start-' + str(i)})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('scope-guide', json.loads(result.stdout)['hookSpecificOutput']['additionalContext'])
        self.assertEqual(marker.read_text().splitlines(), [str(self.project), str(child)])
        before = {str(p.relative_to(self.store)): p.read_bytes() for p in self.store.rglob('*') if p.is_file()}
        for name in ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'Stop'):
            result = self.native_hook({'hook_event_name': name, 'session_id': 'outside', 'cwd': str(self.root)})
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(before, {str(p.relative_to(self.store)): p.read_bytes()
                                 for p in self.store.rglob('*') if p.is_file()})
        self.assertEqual(marker.read_text().splitlines(), [str(self.project), str(child)])

    def test_native_cc_invalid_cwd_and_event_remain_fail_closed(self):
        marker = self.scope_fixture()
        events = [{'hook_event_name': 'SessionStart', 'session_id': 'invalid', 'cwd': cwd}
                  for cwd in ('', None, 7, 'relative', str(self.root / 'missing'), str(self.store / 'registry.json'))]
        events += [{'hook_event_name': 'SessionStart', 'session_id': 'invalid'},
                   {'hook_event_name': 'Unsupported', 'session_id': 'invalid', 'cwd': str(self.root)},
                   {'hook_event_name': 'SessionStart', 'session_id': None, 'cwd': str(self.root)}]
        for event in events:
            with self.subTest(event=event):
                result = self.native_hook(event)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')
                self.assertEqual(json.loads(result.stderr)['status'], 'failed')
                self.assertFalse((self.store / 'pipeline-state.sqlite').exists())
                self.assertFalse(marker.exists())

    def test_direct_cc_dispatch_still_rejects_outside_callbacks(self):
        marker = self.scope_fixture()
        for name in ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'Stop'):
            with self.subTest(event=name), self.assertRaisesRegex(ValueError, 'hook_project_scope_mismatch'):
                dispatch_event(self.connection, {'hook_event_name': name, 'session_id': 'outside', 'cwd': str(self.root)})
        self.assertFalse((self.store / 'pipeline-state.sqlite').exists())
        self.assertFalse(marker.exists())

    def test_direct_droid_dispatch_still_rejects_outside_callbacks(self):
        connect_host(self.store, 'factory-droid', self.profile)
        with self.assertRaisesRegex(ValueError, 'hook_project_scope_mismatch'):
            dispatch_event(self.connection, {'hook_event_name': 'SessionStart', 'session_id': 'outside', 'cwd': str(self.root)})
        self.assertFalse((self.store / 'pipeline-state.sqlite').exists())

    def test_native_droid_outside_noops_and_inside_keeps_dispatch(self):
        marker = self.scope_fixture('factory-droid'); settings = self.profile / '.factory/settings.json'
        before = {str(p.relative_to(self.store)): p.read_bytes() for p in self.store.rglob('*') if p.is_file()}
        for name in ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'Stop', 'SessionEnd'):
            result = self.native_hook({'hook_event_name': name, 'session_id': 'outside', 'cwd': str(self.root)}, settings)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(before, {str(p.relative_to(self.store)): p.read_bytes() for p in self.store.rglob('*') if p.is_file()})
        self.assertFalse(marker.exists())
        result = self.native_hook({'hook_event_name': 'SessionStart', 'session_id': 'inside', 'cwd': str(self.project)}, settings)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('scope-guide', json.loads(result.stdout)['hookSpecificOutput']['additionalContext'])
        self.assertEqual(marker.read_text().splitlines(), [str(self.project)])

    def test_native_droid_invalid_events_and_cwd_remain_rejected(self):
        marker = self.scope_fixture('factory-droid'); settings = self.profile / '.factory/settings.json'
        for raw in ({'hook_event_name': 'SessionStart', 'session_id': 'invalid', 'cwd': 'relative'},
                    {'hook_event_name': 'Unsupported', 'session_id': 'invalid', 'cwd': str(self.root)}):
            result = self.native_hook(raw, settings)
            self.assertEqual(result.returncode, 2); self.assertEqual(result.stdout, '')
        self.assertFalse(marker.exists()); self.assertFalse((self.store / 'pipeline-state.sqlite').exists())

    def test_droid_project_mcp_preserves_existing_and_shares_profile_entry(self):
        settings = self.project / '.factory/mcp.json'; settings.parent.mkdir()
        settings.write_text(json.dumps({'mcpServers': {'existing': {'command': 'existing'}}}))
        self.profile.mkdir(); (self.profile / '.factory').mkdir()
        global_settings = self.profile / '.factory/mcp.json'
        global_settings.write_text(json.dumps({'mcpServers': {'global-other': {'command': 'other'}}}))
        before_global = global_settings.read_bytes()
        first = connect_host(self.store, 'factory-droid', self.profile); before = settings.read_bytes()
        other = self.root / 'other-profile'; connect_host(self.store, 'factory-droid', other)
        self.assertEqual(settings.read_bytes(), before); self.assertEqual(global_settings.read_bytes(), before_global)
        self.assertEqual(json.loads(before)['mcpServers']['existing'], {'command': 'existing'})
        self.assertEqual(first['project_settings_file'], str(settings))
        for profile in (self.profile, other):
            self.assertEqual(connect_host(self.store, 'factory-droid', profile)['status'], 'configured')
        command = json.loads(before)['mcpServers']['backpack']['args'][1]
        self.assertIn('${FACTORY_HOME_OVERRIDE:-$HOME}', command)

    def test_droid_conflicting_project_or_global_backpack_is_preserved(self):
        for relative in ('global', 'project'):
            with self.subTest(scope=relative):
                profile = self.root / (relative + '-profile')
                path = (profile if relative == 'global' else self.project) / '.factory/mcp.json'
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text('{"mcpServers":{"backpack":{"command":"other"}}}')
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, 'existing_backpack_connection_conflict'):
                    connect_host(self.store, 'factory-droid', profile)
                self.assertEqual(path.read_bytes(), before); self.assertFalse((profile / 'backpack-connection.json').exists())

    def test_native_qwen_outside_callbacks_are_silent_without_database_or_hook_effects(self):
        marker = self.scope_fixture('qwen-code')
        before = {str(p.relative_to(self.store)): p.read_bytes() for p in self.store.rglob('*') if p.is_file()}
        for name in ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'Stop', 'SessionEnd'):
            with self.subTest(event=name):
                result = self.native_hook({'hook_event_name': name, 'session_id': 'outside',
                                           'cwd': str(self.root), 'tool_name': 'read_file'})
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
                self.assertFalse((self.store / 'pipeline-state.sqlite').exists())
                self.assertFalse(marker.exists())
                self.assertEqual(before, {str(p.relative_to(self.store)): p.read_bytes()
                                         for p in self.store.rglob('*') if p.is_file()})

    def test_native_qwen_project_and_child_execute_and_outside_preserves_database(self):
        marker = self.scope_fixture('qwen-code')
        child = self.project / 'child';child.mkdir()
        for i, cwd in enumerate((self.project, child)):
            result = self.native_hook({'hook_event_name': 'SessionStart', 'session_id': 'inside-' + str(i),
                                       'cwd': str(cwd), 'delivery_id': 'start-' + str(i)})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('scope-guide', json.loads(result.stdout)['hookSpecificOutput']['additionalContext'])
        self.assertEqual(marker.read_text().splitlines(), [str(self.project), str(child)])
        before = {str(p.relative_to(self.store)): p.read_bytes() for p in self.store.rglob('*') if p.is_file()}
        for name in ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'Stop', 'SessionEnd'):
            result = self.native_hook({'hook_event_name': name, 'session_id': 'outside', 'cwd': str(self.root)})
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(before, {str(p.relative_to(self.store)): p.read_bytes()
                                 for p in self.store.rglob('*') if p.is_file()})
        self.assertEqual(marker.read_text().splitlines(), [str(self.project), str(child)])

    def test_native_qwen_invalid_cwd_and_event_remain_fail_closed(self):
        marker = self.scope_fixture('qwen-code')
        before = {str(p.relative_to(self.store)): p.read_bytes() for p in self.store.rglob('*') if p.is_file()}
        events = [{'hook_event_name': 'SessionStart', 'session_id': 'invalid', 'cwd': cwd}
                  for cwd in ('', None, 7, 'relative', str(self.root / 'missing'), str(self.store / 'registry.json'))]
        events += [{'hook_event_name': 'SessionStart', 'session_id': 'invalid'},
                   {'hook_event_name': 'Unsupported', 'session_id': 'invalid', 'cwd': str(self.root)},
                   {'session_id': 'invalid', 'cwd': str(self.root)},
                   {'hook_event_name': 'SessionStart', 'session_id': None, 'cwd': str(self.root)},
                   {'hook_event_name': 'SessionStart', 'cwd': str(self.root)}]
        for event in events:
            with self.subTest(event=event):
                result = self.native_hook(event)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')
                self.assertEqual(json.loads(result.stderr)['status'], 'failed')
                self.assertFalse((self.store / 'pipeline-state.sqlite').exists())
                self.assertFalse(marker.exists())
                self.assertEqual(before, {str(p.relative_to(self.store)): p.read_bytes()
                                         for p in self.store.rglob('*') if p.is_file()})

    def test_native_qwen_symlink_scope_uses_real_directory(self):
        marker = self.scope_fixture('qwen-code')
        escape = self.project / 'escape';escape.symlink_to(self.root, target_is_directory=True)
        result = self.native_hook({'hook_event_name': 'SessionStart', 'session_id': 'outside', 'cwd': str(escape)})
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertFalse((self.store / 'pipeline-state.sqlite').exists())
        self.assertFalse(marker.exists())
        inside = self.root / 'inside';inside.symlink_to(self.project, target_is_directory=True)
        result = self.native_hook({'hook_event_name': 'SessionStart', 'session_id': 'inside', 'cwd': str(inside)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('scope-guide', json.loads(result.stdout)['hookSpecificOutput']['additionalContext'])
        self.assertEqual(marker.read_text().splitlines(), [str(inside)])

    def test_direct_qwen_dispatch_still_rejects_outside_callbacks(self):
        marker = self.scope_fixture('qwen-code')
        for name in ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'Stop', 'SessionEnd'):
            with self.subTest(event=name), self.assertRaisesRegex(ValueError, 'hook_project_scope_mismatch'):
                dispatch_event(self.connection, {'hook_event_name': name, 'session_id': 'outside', 'cwd': str(self.root)})
        self.assertFalse((self.store / 'pipeline-state.sqlite').exists())
        self.assertFalse(marker.exists())

    def test_qwen_gateway_selection_keeps_session_scope(self):
        package = self.plugin('qwen-library');(package / 'skills/one').mkdir(parents=True)
        (package / 'skills/one/SKILL.md').write_text('Public Qwen fixture guidance')
        add_plugin(self.store, package);connect_host(self.store, 'qwen-code', self.profile)
        token = self.token(self.start());other = self.token(self.start('s2', 'd2'))
        gateway = Gateway(self.connection)
        try:
            selection = self.select(gateway, token, 'skill')
            with self.assertRaisesRegex(ValueError, 'selection_session_scope_conflict'):
                gateway.invoke(selection, {}, other)
            self.assertEqual(gateway.invoke(selection, {}, token)['status'], 'completed')
            with self.assertRaisesRegex(ValueError, 'selection_session_scope_conflict'):
                gateway.invoke(selection, {}, other)
            with patch('plugin_runtime.pick', side_effect=AssertionError('invalid token reached selection')):
                with self.assertRaisesRegex(ValueError, 'current_native_start_context_required'):
                    gateway.acquire('fixture guidance', 'outside-token')
        finally:
            gateway.close()

    def pi_scope_extension(self):
        """Real generated TS, fake Pi API and deterministic subprocess fixture."""
        from plugin_pipeline import adapter, WritePlan
        marker = self.root / 'pi-executions.jsonl'
        script = self.root / 'pi-dispatch.py'
        script.write_text('import json,sqlite3,sys\nevent=json.load(sys.stdin)\n'
            + 'with open(' + repr(str(marker)) + ', "a") as f: f.write(json.dumps(event) + "\\n")\n'
            + 'db=sqlite3.connect(' + repr(str(self.store / 'pipeline-state.sqlite')) + ')\n'
            + 'db.execute("CREATE TABLE IF NOT EXISTS observed(event TEXT)")\n'
            + 'db.execute("INSERT INTO observed VALUES (?)", (event["hook_event_name"],))\ndb.commit()\ndb.close()\n'
            + 'print(json.dumps({"blocked":False,"context":"pi-guide","reason":""}))\n')
        plan = WritePlan()
        result = adapter('pi').install(self.profile, self.project, [sys.executable, str(script)], self.connection, plan)
        plan.commit()
        harness = self.root / 'pi-harness.mjs'
        harness.write_text("""import extension from EXTENSION;
const calls = JSON.parse(process.argv[2]); const handlers = {}; const registrations = [];
extension({registerMcpServer: (...args) => registrations.push(args), on: (name, handler) => { handlers[name] = handler; }});
const results = [];
for (const call of calls) {
  const ctx = {cwd: call.cwd, sessionManager: {getSessionId: () => 'fixture'}};
  const event = {text: 'public fixture', toolName: 'read', input: {}, toolCallId: 'fixture', content: [], isError: false};
  results.push(handlers[call.event] ? await handlers[call.event](event, ctx) : null);
}
console.log(JSON.stringify({registrations, events: Object.keys(handlers), results}));
""".replace('EXTENSION', json.dumps(Path(result['extension_file']).as_uri())))
        return marker, harness

    def run_pi_scope(self, harness, launch_cwd, calls=()):
        result = subprocess.run([shutil.which('node'), '--experimental-strip-types', str(harness), json.dumps(calls)],
                                cwd=launch_cwd, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    @unittest.skipUnless(shutil.which('node'), 'Node required for generated Pi TS fixture')
    def test_generated_pi_outside_and_missing_root_register_nothing(self):
        marker, harness = self.pi_scope_extension()
        outside = self.root / 'project-sibling';outside.mkdir()
        escape = self.project / 'escape';escape.symlink_to(outside, target_is_directory=True)
        before = {str(p.relative_to(self.store)): p.read_bytes() for p in self.store.rglob('*') if p.is_file()}
        for cwd in (self.root, outside, escape):
            with self.subTest(cwd=cwd):
                result = self.run_pi_scope(harness, cwd)
                self.assertEqual((result['registrations'], result['events']), ([], []))
        self.project.rename(self.root / 'moved-project')
        result = self.run_pi_scope(harness, self.root)
        self.assertEqual((result['registrations'], result['events']), ([], []))
        self.assertFalse(marker.exists())
        self.assertEqual(before, {str(p.relative_to(self.store)): p.read_bytes() for p in self.store.rglob('*') if p.is_file()})

    @unittest.skipUnless(shutil.which('node'), 'Node required for generated Pi TS fixture')
    def test_generated_pi_project_child_and_symlink_execute(self):
        marker, harness = self.pi_scope_extension()
        child = self.project / 'child';child.mkdir()
        alias = self.root / 'project-alias';alias.symlink_to(child, target_is_directory=True)
        events = ('session_start', 'input', 'before_agent_start', 'tool_call', 'tool_result', 'session_shutdown')
        for cwd in (self.project, child, alias):
            with self.subTest(cwd=cwd):
                result = self.run_pi_scope(harness, cwd, [{'event': event, 'cwd': str(cwd)} for event in events])
                self.assertEqual(len(result['registrations']), 1)
                self.assertEqual(result['events'], list(events))
                self.assertEqual(result['results'][1], {'action': 'continue'})
                self.assertIn('pi-guide', result['results'][2]['message']['content'])
        observed = [json.loads(line) for line in marker.read_text().splitlines()]
        self.assertEqual([event['hook_event_name'] for event in observed],
                         ['SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'SessionEnd'] * 3)

    @unittest.skipUnless(shutil.which('node'), 'Node required for generated Pi TS fixture')
    def test_generated_pi_all_outside_or_invalid_callbacks_have_no_effect(self):
        marker, harness = self.pi_scope_extension()
        outside = self.root / 'project-sibling';outside.mkdir()
        escape = self.project / 'escape';escape.symlink_to(outside, target_is_directory=True)
        events = ('session_start', 'input', 'before_agent_start', 'tool_call', 'tool_result', 'session_shutdown')
        invalid = (str(outside), str(escape), '', None, 7, 'relative', str(self.root / 'missing'), str(harness))
        before = {str(p.relative_to(self.store)): p.read_bytes() for p in self.store.rglob('*') if p.is_file()}
        calls = [{'event': event, 'cwd': cwd} for cwd in invalid for event in events]
        result = self.run_pi_scope(harness, self.project, calls)
        self.assertEqual(len(result['registrations']), 1)
        self.assertEqual(result['results'], [None] * len(calls))
        self.assertFalse(marker.exists())
        self.assertEqual(before, {str(p.relative_to(self.store)): p.read_bytes() for p in self.store.rglob('*') if p.is_file()})
        # An outside callback also preserves already-created dispatch state.
        self.run_pi_scope(harness, self.project, [{'event': 'session_start', 'cwd': str(self.project)}])
        before = {str(p.relative_to(self.store)): p.read_bytes() for p in self.store.rglob('*') if p.is_file()}
        observed = marker.read_bytes()
        self.run_pi_scope(harness, self.project, calls)
        self.assertEqual(observed, marker.read_bytes())
        self.assertEqual(before, {str(p.relative_to(self.store)): p.read_bytes() for p in self.store.rglob('*') if p.is_file()})
        result = self.run_pi_scope(harness, self.project,
            [{'event': 'session_start', 'cwd': str(self.project)}, {'event': 'input', 'cwd': str(self.project)}]
            + calls + [{'event': 'before_agent_start', 'cwd': str(self.project)}])
        self.assertEqual(result['results'][2:-1], [None] * len(calls))
        self.assertIn('pi-guide', result['results'][-1]['message']['content'])
        # Only the two explicitly inside events above may execute.
        lines = marker.read_bytes().splitlines()
        self.assertEqual(lines[:-2], observed.splitlines())

    def test_direct_pi_dispatch_still_rejects_outside_callbacks(self):
        connect_host(self.store, 'pi', self.profile)
        with self.assertRaisesRegex(ValueError, 'hook_project_scope_mismatch'):
            dispatch_event(self.connection, {'hook_event_name': 'SessionStart', 'session_id': 'outside', 'cwd': str(self.root)})
        self.assertFalse((self.store / 'pipeline-state.sqlite').exists())

    def test_library_loaded_without_native_skill_install(self):
        package = self.plugin('library');(package / 'skills/one').mkdir(parents=True)
        (package / 'skills/one/SKILL.md').write_text('---\nname: one\ndescription: public test instructions\n---\nDo public fixture work.')
        add_plugin(self.store, package);connect_host(self.store, 'claude-code', self.profile)
        token = self.token(self.start());gateway = Gateway(self.connection)
        try:
            with patch('plugin_runtime.pick', side_effect=lambda need, entries: {'status':'selected', 'choice': next(k for k,v in entries.items() if v['kind']=='skill'), 'confidence':1}):
                selected = gateway.acquire('fixture guidance', token)
            self.assertIn('public fixture work', selected['guidance'])
            self.assertEqual(selected['schema'], {'type': 'object', 'properties': {}, 'additionalProperties': False})
            self.assertIn('guidance is already delivered', selected['invocation_contract'])
            other = self.token(self.start('s2', 'd2'))
            with self.assertRaisesRegex(ValueError, 'scope'):
                gateway.invoke(selected['selection'], {}, other)
            self.assertFalse((self.profile / 'skills/one').exists())
            self.assertEqual(gateway.invoke(selected['selection'], {}, token)['status'], 'completed')
            # A cached result has the same ownership check as the first execution.
            with self.assertRaisesRegex(ValueError, 'scope'):
                gateway.invoke(selected['selection'], {}, other)
        finally:
            gateway.close()

    def test_resource_contract_advertises_only_empty_arguments_before_dispatch(self):
        package = self.plugin('resource-contract')
        script = package / 'server.py'
        script.write_text('import json,sys\nfor line in sys.stdin:\n p=json.loads(line)\n if "id" not in p:continue\n'
            ' m=p["method"]\n r=' + repr({**HANDSHAKE, 'capabilities': {'resources': {}}}) +
            ' if m=="initialize" else {"tools":[]} if m=="tools/list" else ' +
            repr({'resources': [{'uri': 'fixture://contract', 'name': 'contract', 'description': 'Read public contract document.'}]}) +
            ' if m=="resources/list" else ' + repr({'contents': [{'uri': 'fixture://contract', 'text': 'public resource content'}]}) +
            ' if m=="resources/read" else {}\n print(json.dumps({"jsonrpc":"2.0","id":p["id"],"result":r}),flush=True)\n')
        (package / '.mcp.json').write_text(json.dumps({'mcpServers': {'contract': {'command': sys.executable, 'args': [str(script)]}}}))
        add_plugin(self.store, package);connect_host(self.store, 'claude-code', self.profile)
        token = self.token(self.start());gateway = Gateway(self.connection)
        try:
            with patch('plugin_runtime.pick', side_effect=lambda need, entries: {'status': 'selected', 'choice': next(k for k, v in entries.items() if v['kind'] == 'resource'), 'confidence': 1}):
                selected = gateway.acquire('public resource document', token)
            self.assertEqual(selected['schema'], {'type': 'object', 'properties': {}, 'additionalProperties': False})
            self.assertIn('arguments={}', selected['invocation_contract'])
            with self.assertRaisesRegex(ValueError, 'takes_no_arguments'):
                gateway.invoke(selected['selection'], {'uri': 'fixture://contract'}, token)
            self.assertEqual(gateway.db.execute('SELECT state FROM selections WHERE id=?', (selected['selection'],)).fetchone()[0], 'selected')
            self.assertEqual(gateway.db.execute('SELECT count(*) FROM operations').fetchone()[0], 0)
            self.assertEqual(gateway.invoke(selected['selection'], {}, token)['status'], 'completed')
        finally:
            gateway.close()

    def test_symlink_component_escape_is_rejected(self):
        package = self.plugin('escape');(package / 'skills/one').mkdir(parents=True)
        outside = self.root / 'outside.md';outside.write_text('outside')
        (package / 'skills/one/SKILL.md').symlink_to(outside)
        with self.assertRaises(ValueError):
            inspect_plugin(package)

    def test_guidance_changed_while_selector_runs_is_not_disclosed(self):
        package=self.plugin('changing-library');(package/'skills/one').mkdir(parents=True)
        guidance=package/'skills/one/SKILL.md';guidance.write_text('---\nname: one\ndescription: public guide\n---\nRegistered guide.')
        add_plugin(self.store,package);connect_host(self.store,'claude-code',self.profile)
        token=self.token(self.start());gateway=Gateway(self.connection)
        def selected(need,entries):
            guidance.write_text('Unregistered replacement')
            return {'status':'selected','choice':next(k for k,v in entries.items() if v['kind']=='skill'),'confidence':1}
        try:
            with patch('plugin_runtime.pick',side_effect=selected):
                with self.assertRaisesRegex(ValueError,'selected_plugin_changed'):
                    gateway.acquire('public guide',token)
            self.assertEqual(gateway.db.execute('SELECT count(*) FROM selections').fetchone()[0],0)
        finally:
            gateway.close()

    def test_failed_reconnect_preserves_binding_and_all_host_bytes(self):
        connect_host(self.store, 'claude-code', self.profile)
        paths = [self.connection, self.profile/'settings.json', self.project/'.mcp.json']
        before = {p:p.read_bytes() for p in paths}
        other = self.root/'other-store';init_store(other, self.project)
        with self.assertRaisesRegex(ValueError, 'binding_conflict'):
            connect_host(other, 'claude-code', self.profile)
        self.assertEqual(before, {p:p.read_bytes() for p in paths})
        fresh = self.root/'fresh-profile'
        with self.assertRaisesRegex(ValueError, 'connection_conflict'):
            connect_host(other, 'claude-code', fresh)
        self.assertFalse((fresh/'backpack-connection.json').exists())
        self.assertFalse((fresh/'settings.json').exists())

    def test_same_project_and_profile_connect_does_not_lock_itself(self):
        result=connect_host(self.store,'claude-code',self.project)
        self.assertEqual(result['status'],'configured')
        self.assertTrue((self.project/'backpack-connection.json').is_file())

    def test_qwen_connection_surfaces_only_its_two_fixed_entrypoints(self):
        self.profile.mkdir();(self.profile/'settings.json').write_text(json.dumps({'tools':{'visible':['existing_tool']}}))
        connect_host(self.store,'qwen-code',self.profile)
        settings=json.loads((self.profile/'settings.json').read_text())
        self.assertEqual(settings['tools']['visible'],['existing_tool','mcp__backpack__acquire','mcp__backpack__invoke'])
        before=(self.profile/'settings.json').read_bytes()
        add_plugin(self.store,self.plugin('future-qwen'))
        self.assertEqual(before,(self.profile/'settings.json').read_bytes())

    def test_qwen_project_mcp_preserves_existing_settings_and_stays_out_of_profile(self):
        existing = {'mcpServers': {'existing': {'command': 'existing-command'}}, 'theme': 'dark'}
        self.profile.mkdir();(self.profile / 'settings.json').write_text(json.dumps(existing))
        project_settings = self.project / '.qwen/settings.json'
        project_settings.parent.mkdir()
        project_settings.write_text(json.dumps({'mcpServers': {'project-other': {'command': 'other'}},
                                                'tools': {'exclude': ['fixture-tool']}}))
        result = connect_host(self.store, 'qwen-code', self.profile)
        profile = json.loads((self.profile / 'settings.json').read_text())
        self.assertEqual(profile['mcpServers'], existing['mcpServers'])
        self.assertEqual(profile['theme'], 'dark')
        settings = json.loads(project_settings.read_text())
        self.assertEqual(settings['mcpServers']['project-other'], {'command': 'other'})
        self.assertEqual(settings['tools'], {'exclude': ['fixture-tool']})
        self.assertIn('backpack', settings['mcpServers'])
        self.assertEqual(result['project_settings_file'], str(project_settings))
        self.assertFalse((self.root / '.qwen/settings.json').exists())
        receipt = json.loads((self.profile / 'backpack-release.json').read_text())
        self.assertEqual(receipt['configuration'][str(project_settings)],
                         configuration_digest(project_settings.read_bytes(), QWEN_CONFIG_VIEW))
        self.assertEqual(receipt['configuration_views'][str(project_settings)], QWEN_CONFIG_VIEW)

    def test_qwen_two_profiles_share_project_mcp_with_pinned_receipts(self):
        connect_host(self.store, 'qwen-code', self.profile)
        project_settings = self.project / '.qwen/settings.json'
        before = project_settings.read_bytes()
        second = self.root / 'second-profile'
        connect_host(self.store, 'qwen-code', second)
        self.assertEqual(project_settings.read_bytes(), before)
        for profile in (self.profile, second):
            with self.subTest(profile=profile):
                settings = json.loads((profile / 'settings.json').read_text())
                self.assertNotIn('backpack', settings.get('mcpServers', {}))
                receipt = json.loads((profile / 'backpack-release.json').read_text())
                self.assertEqual(receipt['configuration'][str(project_settings)], configuration_digest(before, QWEN_CONFIG_VIEW))
                result = connect_host(self.store, 'qwen-code', profile)
                self.assertEqual(result['status'], 'configured')
                self.assertEqual(project_settings.read_bytes(), before)
        mcp = json.loads(before)['mcpServers']['backpack']
        self.assertEqual(mcp['command'], '/bin/sh')
        self.assertEqual(mcp['cwd'], str(self.project))
        self.assertIn('${QWEN_HOME:-$HOME/.qwen}/backpack-runtime.py', mcp['args'][1])

    def test_qwen_existing_profile_backpack_conflict_preserves_settings(self):
        self.profile.mkdir();settings = self.profile / 'settings.json'
        settings.write_text(json.dumps({'mcpServers': {'backpack': {'command': 'unmanaged'}}}))
        before = settings.read_bytes()
        with self.assertRaisesRegex(ValueError, 'existing_backpack_connection_conflict'):
            connect_host(self.store, 'qwen-code', self.profile)
        self.assertEqual(settings.read_bytes(), before)
        self.assertFalse((self.profile / 'backpack-connection.json').exists())
        self.assertFalse((self.profile / 'backpack-release.json').exists())
        self.assertFalse((self.project / '.qwen/settings.json').exists())

    def test_qwen_existing_project_backpack_conflict_preserves_settings(self):
        self.profile.mkdir();profile_settings = self.profile / 'settings.json'
        profile_settings.write_text(json.dumps({'theme': 'existing'}))
        project_settings = self.project / '.qwen/settings.json';project_settings.parent.mkdir()
        project_settings.write_text(json.dumps({'mcpServers': {'backpack': {'command': 'unmanaged'}}}))
        before = {path: path.read_bytes() for path in (profile_settings, project_settings)}
        with self.assertRaisesRegex(ValueError, 'existing_backpack_connection_conflict'):
            connect_host(self.store, 'qwen-code', self.profile)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertFalse((self.profile / 'backpack-connection.json').exists())
        self.assertFalse((self.profile / 'backpack-release.json').exists())

    def test_invocation_rechecks_guidance_and_all_script_extensions(self):
        package = self.plugin('guidance');(package/'skills/one').mkdir(parents=True)
        leaf = package/'skills/one/SKILL.md';leaf.write_text('Original guidance')
        for name in ['handler.mjs', 'handler.cjs', 'executable']:
            (package/name).write_text('Original')
        add_plugin(self.store, package);connect_host(self.store, 'claude-code', self.profile)
        token = self.token(self.start());gateway = Gateway(self.connection)
        try:
            selection = self.select(gateway, token, 'skill')
            leaf.write_text('Modified guidance')
            with self.assertRaisesRegex(ValueError, 'selected_plugin_changed'):
                gateway.invoke(selection, {}, token)
            leaf.write_text('Original guidance')
            plugin = load_registry(self.store)[2]['plugins']['guidance']
            for name in ['handler.mjs', 'handler.cjs', 'executable']:
                path=package/name;path.write_text('Changed')
                self.assertFalse(plugin_unchanged(plugin));path.write_text('Original')
        finally:
            gateway.close()

    def test_crash_claim_blocks_new_selection_in_another_session(self):
        self.service();token = self.token(self.start());gateway = Gateway(self.connection)
        class CrashPeer:
            sent_business = False
            def __init__(self, *args): pass
            def call(self, method, params):
                if method == 'tools/list': return INDEX
                self.sent_business=True;raise KeyboardInterrupt('simulated process loss')
            def close(self): pass
        try:
            selection = self.select(gateway, token)
            with patch('plugin_runtime.Peer', CrashPeer), self.assertRaises(KeyboardInterrupt):
                gateway.invoke(selection, {'query':'one'}, token)
            other = self.token(self.start('s2','d2'))
            with self.assertRaisesRegex(ValueError, 'scope'):
                gateway.invoke(selection, {'query':'one'}, other)
            gateway.close();gateway=Gateway(self.connection)
            fresh = self.select(gateway, other)
            with self.assertRaisesRegex(ValueError, 'previous_operation_unknown'):
                gateway.invoke(fresh, {'query':'one'}, other)
        finally:
            gateway.close()

    def test_parallel_equivalent_operations_dispatch_once(self):
        self.service();token = self.token(self.start());gateway=Gateway(self.connection)
        one=self.select(gateway,token);two=self.select(gateway,token)
        began=threading.Event();release=threading.Event();calls=[];outputs=[]
        class WaitingPeer:
            sent_business=False
            def __init__(self,*args): pass
            def call(self,method,params):
                if method=='tools/list': return INDEX
                self.sent_business=True;calls.append(method);began.set();release.wait(3)
                return {'content': []}
            def close(self): pass
        def invoke_one():
            native=Gateway(self.connection)
            try: outputs.append(native.invoke(one,{},token))
            finally: native.close()
        try:
            with patch('plugin_runtime.Peer',WaitingPeer):
                thread=threading.Thread(target=invoke_one);thread.start()
                self.assertTrue(began.wait(2))
                with self.assertRaisesRegex(ValueError,'previous_operation_unknown'):
                    gateway.invoke(two,{},token)
                release.set();thread.join(3)
            self.assertEqual(calls,['tools/call']);self.assertEqual(outputs[0]['status'],'completed')
        finally:
            release.set();gateway.close()

    def test_native_leaf_deny_and_ask_prevent_business_rpc(self):
        self.service();token=self.token(self.start());gateway=Gateway(self.connection)
        try:
            for decision in ['deny','ask']:
                settings=self.profile/'settings.json';value=json.loads(settings.read_text())
                value['permissions']={decision:['mcp__service__sample']};settings.write_text(json.dumps(value))
                selection=self.select(gateway,token)
                with patch('plugin_runtime.Peer',side_effect=AssertionError('business process must not start')):
                    result=gateway.invoke(selection,{},token)
                self.assertEqual(result['status'],'denied');self.assertEqual(result['effect'],'not_dispatched')
        finally:
            gateway.close()

    def test_business_error_dispatches_failure_hook(self):
        self.service(failure=True)
        add_plugin(self.store,self.plugin('observe-failure','PostToolUseFailure'))
        token=self.token(self.start());gateway=Gateway(self.connection)
        try:
            result=gateway.invoke(self.select(gateway,token),{},token)
            self.assertEqual(result['status'],'failed')
            rows=gateway.db.execute('SELECT event,result FROM hook_receipts').fetchall()
            self.assertTrue(any(r['event']=='PostToolUseFailure' and 'observe-failure:0' in r['result'] for r in rows))
            self.assertFalse(any(r['event']=='PostToolUse' for r in rows))
        finally:
            gateway.close()

    def test_original_mcp_hook_matcher_denies_leaf_before_rpc(self):
        self.service();package=self.plugin('leaf-deny','PreToolUse',{'hookSpecificOutput':{
            'hookEventName':'PreToolUse','permissionDecision':'deny','permissionDecisionReason':'fixture denial'}})
        path=package/'hooks/hooks.json';body=json.loads(path.read_text())
        body['hooks']['PreToolUse'][0]['matcher']='^mcp__service__sample$';path.write_text(json.dumps(body))
        add_plugin(self.store,package);token=self.token(self.start());gateway=Gateway(self.connection)
        try:
            selection=self.select(gateway,token)
            with patch('plugin_runtime.Peer',side_effect=AssertionError('leaf RPC must not start')):
                result=gateway.invoke(selection,{},token)
            self.assertEqual(result['status'],'denied');self.assertEqual(result['effect'],'not_dispatched')
        finally:
            gateway.close()

    def test_unreported_pre_hook_effect_keeps_operation_quarantined(self):
        self.service();token=self.token(self.start());gateway=Gateway(self.connection);effects=[]
        def interrupted(*args,**kwargs):
            effects.append('observed external hook effect')
            raise OSError('receipt persistence interrupted')
        try:
            first=self.select(gateway,token)
            with patch('plugin_runtime.dispatch_event',side_effect=interrupted):
                self.assertEqual(gateway.invoke(first,{},token)['status'],'unknown')
            with self.assertRaisesRegex(ValueError,'previous_operation_unknown'):
                gateway.invoke(self.select(gateway,token),{},token)
            self.assertEqual(effects,['observed external hook effect'])
        finally:
            gateway.close()

    def test_concurrent_plugin_registration_retains_both(self):
        packages=[self.plugin('a'),self.plugin('b')];barrier=threading.Barrier(2);errors=[]
        from plugin_pipeline import plugin_unchanged as check
        def joined(plugin):
            barrier.wait(3);return check(plugin)
        def register(package):
            try: add_plugin(self.store,package)
            except BaseException as error: errors.append(error)
        with patch('plugin_pipeline.plugin_unchanged',joined):
            threads=[threading.Thread(target=register,args=(p,)) for p in packages]
            for thread in threads: thread.start()
            for thread in threads: thread.join(5)
        self.assertEqual(errors,[]);self.assertEqual(set(load_registry(self.store)[2]['plugins']),{'a','b'})

    def test_hermes_preserves_tool_search_and_flags_default_components(self):
        self.profile.mkdir();(self.profile/'config.yaml').write_text(json.dumps({'tools':{'tool_search':{'enabled':'on'}}}))
        connect_host(self.store,'hermes',self.profile)
        self.assertEqual(json.loads((self.profile/'config.yaml').read_text())['tools']['tool_search']['enabled'],'on')
        package=self.plugin('unsupported');(package/'agents').mkdir();(package/'agents/one.md').write_text('Agent')
        self.assertIn('agents',inspect_plugin(package)['unsupported'])

    def test_hermes_generated_bridge_registers_only_inside_and_uses_actual_cwd(self):
        from types import SimpleNamespace
        connect_host(self.store, 'hermes', self.profile)
        code = (self.profile / 'plugins/backpack-pipes/__init__.py').read_text(); namespace = {}
        exec(compile(code, 'generated-hermes-bridge', 'exec'), namespace)
        class Context:
            def __init__(self): self.hooks = {}
            def register_hook(self, name, callback): self.hooks[name] = callback
        with patch('os.getcwd', return_value=str(self.root)):
            outside = Context(); namespace['register'](outside)
            self.assertEqual(outside.hooks, {})
        child = self.project / 'child'; child.mkdir()
        observed = []
        def run(argv, **kwargs):
            observed.append(json.loads(kwargs['input']))
            return SimpleNamespace(stdout='{"blocked":false,"context":"current"}', returncode=0)
        with patch('os.getcwd', return_value=str(child)), patch.object(namespace['subprocess'], 'run', run):
            inside = Context(); namespace['register'](inside)
            self.assertIn('on_session_finalize', inside.hooks)
            self.assertNotIn('on_session_end', inside.hooks)
            self.assertEqual(inside.hooks['pre_llm_call'](session_id='fixture', user_message='public'), {'context': 'current'})
        self.assertEqual(observed[0]['cwd'], str(child))
        with patch('os.getcwd', return_value=str(self.root)), patch.object(namespace['subprocess'], 'run', run):
            inside.hooks['pre_llm_call'](session_id='fixture', user_message='public')
        self.assertEqual(len(observed), 1)

    def test_hermes_existing_yaml_preserves_model_and_other_preferences(self):
        try: import yaml
        except ImportError: self.skipTest('Install the hermes optional dependency to verify existing YAML')
        self.profile.mkdir(); path = self.profile / 'config.yaml'
        path.write_text('model:\n  default: fixture-model\n  provider: auto\nmemory:\n  memory_enabled: true\nplugins:\n  enabled: [existing-plugin]\n')
        before = yaml.safe_load(path.read_text()); connect_host(self.store, 'hermes', self.profile)
        after = json.loads(path.read_text())
        self.assertEqual(after['model'], before['model']); self.assertEqual(after['memory'], before['memory'])
        self.assertEqual(after['plugins']['enabled'], ['existing-plugin', 'backpack-pipes'])

    def test_hermes_invalid_yaml_error_cannot_echo_source_or_change_user_file(self):
        try: import yaml
        except ImportError: self.skipTest('Install the hermes optional dependency to verify existing YAML')
        self.profile.mkdir(); path = self.profile / 'config.yaml'; original = b'private_fixture_value: [not-closed\n'
        path.write_bytes(original)
        with self.assertRaisesRegex(ValueError, '^invalid_existing_hermes_yaml_config$'):
            connect_host(self.store, 'hermes', self.profile)
        self.assertEqual(path.read_bytes(), original); self.assertFalse(self.connection.exists())

    def test_hermes_outside_mcp_is_empty_and_creates_no_runtime_state(self):
        connect_host(self.store, 'hermes', self.profile)
        packets = [{'id': 0, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26', 'capabilities': {},
                     'clientInfo': {'name': 'fixture', 'version': '1'}}}, {'id': 1, 'method': 'tools/list'},
                   {'id': 2, 'method': 'resources/list'}, {'id': 3, 'method': 'tools/call',
                    'params': {'name': 'acquire', 'arguments': {'need': 'public', 'session_token': 'not-authorized'}}}]
        before = {str(p): p.read_bytes() for p in self.store.rglob('*') if p.is_file()}
        result = subprocess.run([sys.executable, str(ROOT / 'src/catmaster_backpack/plugin_pipeline.py'), 'serve',
                                 '--connection', str(self.connection)], cwd=self.root,
                                input=''.join(json.dumps(p) + '\n' for p in packets), capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(responses[1]['result'], {'tools': []})
        self.assertEqual(responses[2]['result'], {'resources': []})
        self.assertIn('error', responses[3])
        self.assertFalse((self.store / 'pipeline-state.sqlite').exists())
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.store.rglob('*') if p.is_file()})

    def test_hermes_kernel_outside_discovery_and_token_cannot_access_plugin_catalog(self):
        connect_host(self.store, 'hermes', self.profile)
        with patch('plugin_runtime.Path.cwd', return_value=self.root): gateway = KernelGateway(self.connection)
        self.assertFalse(gateway.scope_active)
        for operation in (lambda: gateway.discovery(), lambda: gateway.acquire('public', 'unbound'),
                          lambda: gateway.invoke('unbound', {}, 'unbound')):
            with self.assertRaisesRegex(ValueError, 'connector_outside_project'): operation()
        gateway.close(); self.assertFalse((self.store / 'pipeline-state.sqlite').exists())
        with patch('plugin_runtime.Path.cwd', return_value=self.project): inside = KernelGateway(self.connection)
        self.assertTrue(inside.scope_active)
        inside.initialize({'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {}})
        inside.observed('tools/list'); inside.close()

    def test_output_flood_and_nonreading_stdin_have_deadlines(self):
        began=time.monotonic()
        with self.assertRaisesRegex(ValueError,'output_too_large'):
            run_bounded([sys.executable,'-c','import os\nwhile True: os.write(1,b"x"*65536)'],b'{}',1)
        with self.assertRaisesRegex(ValueError,'deadline'):
            run_bounded([sys.executable,'-c','import time;time.sleep(10)'],b'x'*1048576,.15)
        self.assertLess(time.monotonic()-began,2)

    def test_hook_cleanup_kills_descendant_after_parent_exits(self):
        script='import subprocess,sys\np=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"],stdout=subprocess.DEVNULL)\nprint(p.pid)'
        output,code=run_bounded([sys.executable,'-c',script],b'',1)
        self.assertEqual(code,0)
        pid=int(output.strip())
        # ps sees a zombie on some systems; a runnable descendant is unacceptable.
        import subprocess
        state=subprocess.run(['ps','-o','stat=','-p',str(pid)],capture_output=True,text=True).stdout.strip()
        self.assertTrue(not state or state.startswith('Z'),state)

    def test_denied_or_ask_guidance_is_never_disclosed_by_acquire(self):
        package=self.plugin('library');(package/'skills/one').mkdir(parents=True)
        (package/'skills/one/SKILL.md').write_text('Prohibited complete guidance')
        add_plugin(self.store,package);connect_host(self.store,'claude-code',self.profile)
        token=self.token(self.start());gateway=Gateway(self.connection)
        try:
            for decision in ['deny','ask']:
                path=self.profile/'settings.json';settings=json.loads(path.read_text())
                settings['permissions']={decision:['Skill(one)']};path.write_text(json.dumps(settings))
                with patch('plugin_runtime.pick',side_effect=lambda need,entries:{'status':'selected','choice':next(k for k,v in entries.items() if v['kind']=='skill'),'confidence':1}):
                    result=gateway.acquire('public guidance',token)
                self.assertEqual(result['status'],'denied');self.assertNotIn('guidance',result)
        finally:
            gateway.close()

    def test_session_end_failure_still_revokes_token(self):
        package=self.plugin('end-failure','SessionEnd')
        (package/'hook.py').write_text('raise SystemExit(1)')
        add_plugin(self.store,package);connect_host(self.store,'claude-code',self.profile)
        token=self.token(self.start());gateway=Gateway(self.connection)
        try:
            result=dispatch_event(self.connection,{'hook_event_name':'SessionEnd','session_id':'s1',
                'cwd':str(self.project),'delivery_id':'end'})
            self.assertEqual(result['status'],'unknown')
            with self.assertRaisesRegex(ValueError,'current_native_start_context_required'):
                gateway.session(token)
        finally:
            gateway.close()

    def test_protocol_error_after_side_effect_cannot_replay(self):
        package=self.plugin('side-effect');script=package/'server.py';ledger=self.project/'effects.txt'
        script.write_text('import json,sys,pathlib\nfor line in sys.stdin:\n p=json.loads(line)\n if "id" not in p: continue\n'
            ' m=p["method"]\n if m=="tools/call":\n  with pathlib.Path(' + repr(str(ledger)) + ').open("a") as f:f.write("effect\\n")\n'
            '  body={"error":{"code":-32603,"message":"failure after write"}}\n else:\n'
            '  r=' + repr(HANDSHAKE) + ' if m=="initialize" else ' + repr(INDEX) + ' if m=="tools/list" else {"resources":[]} if m=="resources/list" else {}\n  body={"result":r}\n'
            ' print(json.dumps({"jsonrpc":"2.0","id":p["id"],**body}),flush=True)\n')
        (package/'.mcp.json').write_text(json.dumps({'mcpServers':{'side-effect':{'command':sys.executable,'args':[str(script)]}}}))
        add_plugin(self.store,package);connect_host(self.store,'claude-code',self.profile)
        token=self.token(self.start());gateway=Gateway(self.connection)
        try:
            self.assertEqual(gateway.invoke(self.select(gateway,token),{},token)['status'],'unknown')
            with self.assertRaisesRegex(ValueError,'previous_operation_unknown'):
                gateway.invoke(self.select(gateway,token),{},token)
            self.assertEqual(ledger.read_text(),'effect\n')
        finally:
            gateway.close()

    def test_transport_close_revokes_only_its_used_session(self):
        connect_host(self.store,'claude-code',self.profile)
        first=self.token(self.start());other=self.token(self.start('other','start2'))
        gateway=Gateway(self.connection)
        self.assertEqual(gateway.acquire('public fixture',first)['status'],'unavailable')
        gateway.close()
        fresh=Gateway(self.connection)
        try:
            with self.assertRaisesRegex(ValueError,'current_native_start_context_required'):
                fresh.session(first)
            self.assertEqual(fresh.session(other),'other')
        finally:
            fresh.close()

    def test_sigterm_mcp_transport_runs_session_cleanup(self):
        import signal,subprocess
        connect_host(self.store,'qwen-code',self.profile);token=self.token(self.start())
        command=[sys.executable,'-X','pycache_prefix='+str(self.root/'bytecode'),str(ROOT/'src/catmaster_backpack/plugin_pipeline.py'),
            'serve','--connection',str(self.connection)]
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
        try:
            process.stdin.write(json.dumps({'id':0,'method':'initialize','params':{'protocolVersion':'2024-11-05',
                'capabilities':{},'clientInfo':{'name':'local-stdio-fixture','version':'1'}}})+'\n');process.stdin.flush()
            self.assertIn('protocolVersion',process.stdout.readline())
            process.stdin.write(json.dumps({'id':1,'method':'tools/call','params':{'name':'acquire',
                'arguments':{'need':'public fixture','session_token':token}}})+'\n');process.stdin.flush()
            self.assertIn('unavailable',process.stdout.readline())
            process.send_signal(signal.SIGTERM);process.wait(timeout=4)
            self.assertEqual(process.returncode,0)
            gateway=Gateway(self.connection)
            try:
                with self.assertRaisesRegex(ValueError,'current_native_start_context_required'):
                    gateway.session(token)
            finally:
                gateway.close()
        finally:
            if process.poll() is None:process.kill();process.wait()
            process.stdin.close();process.stdout.close()

    def test_old_transport_close_does_not_revoke_resumed_generation(self):
        connect_host(self.store,'claude-code',self.profile)
        old_token=self.token(self.start());old=Gateway(self.connection)
        old.acquire('public fixture',old_token)
        new_token=self.token(self.start('s1','resume-generation'));new=Gateway(self.connection)
        new.acquire('public fixture',new_token)
        old.close()
        try:
            self.assertEqual(new.session(new_token),'s1')
            with self.assertRaisesRegex(ValueError,'current_native_start_context_required'):
                new.session(old_token)
        finally:
            new.close()


if __name__ == '__main__':
    unittest.main()
