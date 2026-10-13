"""Simulated hosts and real local stdio; native acceptance is a separate layer."""
import json
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/catmaster_backpack'))
from plugin_pipeline import add_plugin, connect_host, init_store, unregister_plugin
from plugin_runtime import Gateway, Peer, dispatch_event
from plugin_discovery import PROTOCOL, RESOURCE, reconcile


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.project = self.root / 'project'; self.project.mkdir()
        self.store = self.root / 'store'; init_store(self.store, self.project)
        self.profile = self.root / 'profile'
        self.connected = connect_host(self.store, 'claude-code', self.profile)
        self.connection = self.profile / 'backpack-connection.json'
        self.gateway = Gateway(self.connection)

    def tearDown(self):
        self.gateway.close(); self.temp.cleanup()

    def handshake(self, offer=None):
        caps = {} if offer is None else {'experimental': {'catmasterBackpack': offer}}
        self.gateway.initialize({'protocolVersion': '2025-03-26', 'clientInfo': {'name': 'fixture', 'version': '1'}, 'capabilities': caps})
        self.gateway.observed('tools/list')

    def start(self, delivery='first'):
        output = dispatch_event(self.connection, {'hook_event_name': 'SessionStart', 'session_id': 'same-session',
            'cwd': str(self.project), 'delivery_id': delivery})
        return re.search(r'session_token=([^ ]+)', '\n'.join(output['context']))[1]

    def package(self, name='late', version='one', startup=False, prompts=False):
        package = self.root / name; package.mkdir(exist_ok=True)
        (package / 'component.json').write_text(json.dumps({'name': name, 'version': version}))
        ledger = self.root / (name + '-effects')
        script = '''import json,sys,pathlib
for line in sys.stdin:
 p=json.loads(line)
 if 'id' not in p:continue
 m=p['method'];r={}
 if m=='initialize':r={'protocolVersion':'2024-11-05','serverInfo':{'name':'fixture','version':VERSION},'capabilities':CAPS}
 elif m=='tools/list':r={'tools':[{'name':'probe','description':'test','inputSchema':{'type':'object'}}]}
 elif m=='tools/call':
  with pathlib.Path(LEDGER).open('a') as f:f.write('business\\n')
  r={'content':[{'type':'text','text':VERSION}]}
 else:
  print(json.dumps({'jsonrpc':'2.0','id':p['id'],'error':{'code':-32601,'message':'unavailable'}}),flush=True);continue
 print(json.dumps({'jsonrpc':'2.0','id':p['id'],'result':r}),flush=True)
'''.replace('VERSION', repr(version)).replace('CAPS', repr({'tools': {}, **({'prompts': {}} if prompts else {})})).replace('LEDGER', repr(str(ledger)))
        (package / 'server.py').write_text(script)
        (package / '.mcp.json').write_text(json.dumps({'mcpServers': {'fixture': {'command': sys.executable, 'args': [str(package / 'server.py')]}}}))
        if startup:
            (package / 'hooks').mkdir(exist_ok=True)
            (package / 'hook.py').write_text('import json,sys\ne=json.load(sys.stdin)\nprint(json.dumps({"hookSpecificOutput":{"hookEventName":e["hook_event_name"],"additionalContext":"initialized"}}))\n')
            (package / 'hooks/hooks.json').write_text(json.dumps({'hooks': {event: [{'matcher': '', 'hooks': [{'type': 'command', 'command': sys.executable, 'args': [str(package / 'hook.py')]}]}] for event in ('SessionStart', 'UserPromptSubmit')}}))
        return package

    def select(self, token):
        with patch('plugin_runtime.pick', side_effect=lambda need, entries: {'status':'selected','choice':next(iter(entries))}):
            return self.gateway.acquire('probe', token)['selection']

    def test_missing_runtime_and_received_downgrade_are_distinct(self):
        add_plugin(self.store, self.package())
        plan = reconcile(self.connection)
        self.assertIsNone(plan['negotiated_connector_protocol'])
        self.assertEqual(plan['plugins']['late']['states'], ['pending_runtime'])
        token = self.start(); self.handshake({'connectorProtocols': ['catmaster-connector/99']})
        plan = self.gateway.discovery(token)
        self.assertEqual(plan['plugins']['late']['states'], ['unsupported'])
        self.assertEqual(plan['bindings'][0]['reason'], 'connector_version_mismatch')
        self.assertFalse((self.root / 'late-effects').exists())

    def test_received_delivery_downgrade_prevents_execution(self):
        add_plugin(self.store, self.package()); token = self.start()
        self.handshake({'connectorProtocols': [PROTOCOL], 'disabledDeliveries': ['mcp_gateway_call']})
        plan = self.gateway.discovery(token)
        self.assertFalse(plan['plugins']['late']['ready'])
        self.assertEqual(plan['bindings'][0]['reason'], 'receiver_declined_delivery')

    def test_add_replace_unregister_same_running_peer_and_configs(self):
        self.handshake(); token = self.start()
        paths = [self.connection, self.profile / 'settings.json', self.project / '.mcp.json']
        before = [p.read_bytes() for p in paths]; peer = self.gateway.peer
        first = self.gateway.discovery(token); package = self.package()
        add_plugin(self.store, package); added = self.gateway.discovery(token)
        self.assertGreater(added['binding_revision'], first['binding_revision'])
        self.assertEqual(added['registry_revision'], 1)
        self.assertTrue(added['plugins']['late']['ready'])
        old = self.select(token); self.package(version='two'); add_plugin(self.store, package, replace=True)
        with self.assertRaisesRegex(ValueError, 'selected_plugin_changed'):
            self.gateway.invoke(old, {}, token)
        self.assertEqual(self.gateway.invoke(self.select(token), {}, token)['result']['content'][0]['text'], 'two')
        old = self.select(token); unregister_plugin(self.store, 'late')
        with self.assertRaisesRegex(ValueError, 'selected_plugin_changed'):
            self.gateway.invoke(old, {}, token)
        self.assertEqual(self.gateway.discovery(token)['registry_revision'], 3)
        self.assertEqual(before, [p.read_bytes() for p in paths]); self.assertEqual(peer, self.gateway.peer)
        self.assertEqual((self.root / 'late-effects').read_text(), 'business\n')

    def test_late_start_dependency_does_not_backfill_native_event(self):
        self.handshake(); token = self.start(); add_plugin(self.store, self.package(startup=True))
        plan = self.gateway.discovery(token)
        self.assertEqual(plan['plugins']['late']['states'], ['pending_activation', 'wired'])
        event = {'hook_event_name':'UserPromptSubmit','session_id':'same-session','cwd':str(self.project),'message_id':'later'}
        self.assertEqual(dispatch_event(self.connection, event)['handlers'], [])
        new = self.start('real-next-start')
        self.assertTrue(self.gateway.discovery(new)['plugins']['late']['ready'])
        self.assertEqual(dispatch_event(self.connection, {**event, 'message_id':'next'})['handlers'], ['late:1'])

    def test_same_sid_generation_cannot_reuse_old_selection_or_cached_result(self):
        self.handshake(); add_plugin(self.store, self.package()); token = self.start()
        selected = self.select(token); self.gateway.invoke(selected, {}, token)
        new = self.start('new-generation')
        with self.assertRaisesRegex(ValueError, 'current_native_start_context_required'):
            self.gateway.invoke(selected, {}, token)
        with self.assertRaisesRegex(ValueError, 'selection_session_scope_conflict'):
            self.gateway.invoke(selected, {}, new)
        self.assertEqual(self.gateway.invoke(self.select(new), {}, new)['status'], 'completed')

    def test_revocation_during_leaf_handshake_stops_business_rpc(self):
        self.handshake(); package = self.package(); add_plugin(self.store, package); token = self.start()
        selected = self.select(token); original = Peer.call
        def intercepted(peer, method, params, *args):
            result = original(peer, method, params, *args)
            if method == 'tools/list': self.start('revoked-before-business')
            return result
        with patch.object(Peer, 'call', intercepted):
            result = self.gateway.invoke(selected, {}, token)
        self.assertEqual(result['effect'], 'business_RPC_not_sent')
        self.assertFalse((self.root / 'late-effects').exists())

    def test_discovery_does_not_grant_leaf_permission_or_call_business(self):
        self.handshake(); token = self.start(); package = self.package(); add_plugin(self.store, package)
        report = self.gateway.acquire('', token, describe_connection=True)
        self.assertFalse(report['discovery']['permission_grant'])
        self.assertFalse((self.root / 'late-effects').exists())
        path = self.profile / 'settings.json'; settings = json.loads(path.read_text())
        settings['permissions'] = {'deny':['mcp__fixture__probe']}; path.write_text(json.dumps(settings))
        result = self.gateway.invoke(self.select(token), {}, token)
        self.assertEqual(result['status'], 'denied'); self.assertFalse((self.root / 'late-effects').exists())

    def test_producer_unsupported_feature_is_not_silent_partial_success(self):
        self.handshake(); token = self.start(); add_plugin(self.store, self.package(prompts=True))
        plan = self.gateway.discovery(token)
        self.assertFalse(plan['plugins']['late']['ready'])
        self.assertIn('producer_feature:prompts', [n['reason'] for n in plan['bindings']])

    def test_incompatible_producer_protocol_is_not_registered(self):
        package = self.package(); script = package / 'server.py'
        script.write_text(script.read_text().replace("'protocolVersion':'2024-11-05'", "'protocolVersion':'2099-01-01'"))
        with self.assertRaisesRegex(ValueError, 'unsupported_producer_protocol_version'):
            add_plugin(self.store, package)
        self.assertEqual(json.loads((self.store / 'registry.json').read_text())['plugins'], {})
        self.assertFalse((self.root / 'late-effects').exists())

    def test_real_stdio_subscription_changes_without_reconnect(self):
        process = subprocess.Popen([sys.executable, '-X', 'pycache_prefix=/tmp/backpack-discovery-test-cache',
            str(ROOT / 'src/catmaster_backpack/plugin_pipeline.py'), 'serve', '--connection', str(self.connection)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        packets = queue.Queue()
        def read():
            for line in process.stdout: packets.put(json.loads(line))
        thread = threading.Thread(target=read, daemon=True); thread.start()
        def call(identifier, method, params={}):
            process.stdin.write(json.dumps({'jsonrpc':'2.0','id':identifier,'method':method,'params':params})+'\n'); process.stdin.flush()
            result = packets.get(timeout=5); self.assertEqual(result.get('id'), identifier); return result['result']
        try:
            call(1, 'initialize', {'protocolVersion':'2025-03-26','clientInfo':{'name':'actual-local-stdio-fixture'},'capabilities':{}})
            call(2, 'resources/list'); call(3, 'resources/subscribe', {'uri':RESOURCE})
            add_plugin(self.store, self.package())
            update = packets.get(timeout=5)
            self.assertEqual(update['method'], 'notifications/resources/updated')
            report = call(4, 'resources/read', {'uri':RESOURCE})
            document = json.loads(report['contents'][0]['text'])
            self.assertEqual(document['registry_revision'], 1)
            self.assertEqual(document['received_host_handshake']['client']['name'], 'actual-local-stdio-fixture')
            call(5, 'resources/unsubscribe', {'uri':RESOURCE}); unregister_plugin(self.store, 'late')
            with self.assertRaises(queue.Empty): packets.get(timeout=1)
        finally:
            process.stdin.close(); process.wait(timeout=5); thread.join(timeout=1)
            process.stdout.close(); process.stderr.close()
        self.assertEqual(process.returncode, 0)

    def test_unregister_reregister_and_version_rollback_do_not_revive_handles(self):
        self.handshake(); package = self.package(); add_plugin(self.store, package); token = self.start()
        selected = self.select(token); cached = self.select(token); self.gateway.invoke(cached, {}, token)
        unregister_plugin(self.store, 'late'); add_plugin(self.store, package)
        for handle in (selected, cached):
            with self.assertRaisesRegex(ValueError, 'selected_plugin_changed'):
                self.gateway.invoke(handle, {}, token)
        selected = self.select(token)
        self.package(version='two'); add_plugin(self.store, package, replace=True)
        self.package(version='one'); add_plugin(self.store, package, replace=True)
        with self.assertRaisesRegex(ValueError, 'selected_plugin_changed'):
            self.gateway.invoke(selected, {}, token)
        self.assertEqual((self.root / 'late-effects').read_text(), 'business\n')

    def test_explicit_refresh_rediscoveries_without_a_package_file_change(self):
        self.handshake(); package = self.package(); add_plugin(self.store, package); token = self.start()
        old = self.select(token)
        self.assertEqual(add_plugin(self.store, package)['status'], 'already_registered')
        receipt = add_plugin(self.store, package, replace=True)
        self.assertEqual(receipt['status'], 'registered')
        self.assertEqual(self.gateway.discovery(token)['registry_revision'], 2)
        with self.assertRaisesRegex(ValueError, 'selected_plugin_changed'):
            self.gateway.invoke(old, {}, token)
        self.assertFalse((self.root / 'late-effects').exists())

    def test_declined_hook_delivery_is_enforced_only_on_its_bound_session(self):
        self.handshake({'disabledDeliveries':['native_event_bridge']}); token = self.start()
        package = self.root / 'hook'; (package / 'hooks').mkdir(parents=True)
        (package / 'component.json').write_text('{"name":"hook"}')
        ledger = self.root / 'hook-effects'
        (package / 'hook.py').write_text('from pathlib import Path\nPath('+repr(str(ledger))+').write_text("effect")\nprint("{}")\n')
        (package / 'hooks/hooks.json').write_text(json.dumps({'hooks':{'UserPromptSubmit':[{'hooks':[{'type':'command','command':sys.executable,'args':[str(package / 'hook.py')]}]}]}}))
        add_plugin(self.store, package)
        plan = self.gateway.discovery(token)  # The host token binds this peer to one native session.
        self.assertFalse(plan['plugins']['hook']['ready'])
        event = {'hook_event_name':'UserPromptSubmit','session_id':'same-session','cwd':str(self.project),'message_id':'declined'}
        self.assertEqual(dispatch_event(self.connection, event)['handlers'], [])
        self.assertFalse(ledger.exists())
        self.start_other_session = dispatch_event(self.connection, {'hook_event_name':'SessionStart','session_id':'other-session','cwd':str(self.project)})
        self.assertEqual(dispatch_event(self.connection, {**event,'session_id':'other-session'})['handlers'], ['hook:0'])

    def test_session_start_activation_respects_mutually_exclusive_matchers(self):
        self.handshake(); package = self.package(startup=True)
        path = package / 'hooks/hooks.json'; body = json.loads(path.read_text())
        handler = body['hooks']['SessionStart'][0]
        body['hooks']['SessionStart'] = [{**handler,'matcher':'^startup$'}, {**handler,'matcher':'^resume$'}]
        path.write_text(json.dumps(body)); add_plugin(self.store, package)
        for source in ('startup','resume'):
            output = dispatch_event(self.connection, {'hook_event_name':'SessionStart','session_id':'same-session',
                'cwd':str(self.project),'source':source,'delivery_id':source})
            token = re.search(r'session_token=([^ ]+)', '\n'.join(output['context']))[1]
            self.assertEqual(len(output['handlers']), 1)
            self.assertTrue(self.gateway.discovery(token)['plugins']['late']['ready'])

    def test_startup_only_package_is_pending_until_a_real_later_start(self):
        self.handshake(); token = self.start(); package = self.package(startup=True)
        path = package / 'hooks/hooks.json'; body = json.loads(path.read_text())
        body['hooks'].pop('UserPromptSubmit'); path.write_text(json.dumps(body))
        # Keep only the original startup Hook, with no other component.
        (package / '.mcp.json').unlink()
        add_plugin(self.store, package)
        plan = self.gateway.discovery(token)
        self.assertFalse(plan['plugins']['late']['ready'])
        self.assertIn('pending_activation', plan['plugins']['late']['states'])
        self.assertTrue(self.gateway.discovery(self.start('actual-later-start'))['plugins']['late']['ready'])

    def test_codex_connector_preserves_native_configuration_and_requires_trust(self):
        profile = self.root / 'codex'; profile.mkdir()
        original = 'model = "existing"\n[mcp_servers.other]\ncommand = "safe-existing"\n'
        (profile / 'config.toml').write_text(original)
        result = connect_host(self.store, 'codex', profile)
        self.assertTrue((profile / 'config.toml').read_text().startswith(original))
        self.assertIn('native /hooks', result['hook_trust'])
        before = (profile / 'config.toml').read_bytes()
        connect_host(self.store, 'codex', profile)
        self.assertEqual(before, (profile / 'config.toml').read_bytes())

    def test_receiver_decline_cannot_remove_an_independent_deny_hook(self):
        self.handshake(); package = self.package(); add_plugin(self.store, package)
        deny = self.root / 'deny'; (deny / 'hooks').mkdir(parents=True)
        (deny / 'component.json').write_text('{"name":"deny"}')
        (deny / 'hook.py').write_text('print(\'{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"fixture policy"}}\')\n')
        (deny / 'hooks/hooks.json').write_text(json.dumps({'hooks':{'PreToolUse':[{'hooks':[{'type':'command','command':sys.executable,'args':[str(deny / 'hook.py')]}]}]}}))
        add_plugin(self.store, deny); token = self.start()
        self.assertEqual(self.gateway.invoke(self.select(token), {}, token)['status'], 'denied')
        declined = Gateway(self.connection)
        try:
            declined.initialize({'protocolVersion':'2024-11-05','clientInfo':{},'capabilities':{'experimental':{'catmasterBackpack':{'disabledDeliveries':['native_event_bridge']}}}})
            declined.observed('tools/list'); plan = declined.discovery(token)
            self.assertEqual(declined.acquire('probe', token)['status'], 'unavailable')
            self.assertIn('mandatory_hook_receiver_declined', [n['reason'] for n in plan['bindings']])
            # A peer that accepted delivery cannot execute while a required current check is unavailable.
            result = self.gateway.invoke(self.select(token), {}, token)
            self.assertEqual(result['status'], 'denied')
            self.assertEqual(result['reason'], 'mandatory_hook_delivery_unavailable')
            self.assertFalse((self.root / 'late-effects').exists())
        finally:
            declined.close()

    def test_old_active_peer_does_not_disable_hooks_in_new_token_generation(self):
        self.handshake({'disabledDeliveries':['native_event_bridge']}); token = self.start()
        self.gateway.discovery(token)
        new = self.start('resumed-generation'); accepted = Gateway(self.connection)
        try:
            accepted.initialize({'protocolVersion':'2024-11-05','clientInfo':{},'capabilities':{}})
            accepted.observed('tools/list'); accepted.discovery(new)
            from plugin_discovery import hook_delivery_declined
            self.assertFalse(hook_delivery_declined(self.connection, 'same-session'))
            self.assertTrue(self.gateway.handshake_ready)  # Old transport remains active.
        finally:
            accepted.close()

    def test_late_policy_start_dependency_blocks_existing_tool_until_initialized(self):
        self.handshake(); add_plugin(self.store, self.package()); token = self.start(); old = self.select(token)
        policy = self.package(name='policy', startup=True)
        path = policy / 'hooks/hooks.json'; body = json.loads(path.read_text())
        body['hooks']['PreToolUse'] = body['hooks'].pop('UserPromptSubmit'); path.write_text(json.dumps(body))
        add_plugin(self.store, policy)
        plan = self.gateway.discovery(token)
        self.assertFalse(plan['plugins']['late']['ready'])
        with self.assertRaisesRegex(ValueError, 'selection_policy_changed'):
            self.gateway.invoke(old, {}, token)
        self.assertFalse((self.root / 'late-effects').exists())
        new = self.start('initialized-policy')
        self.assertTrue(self.gateway.discovery(new)['plugins']['late']['ready'])

    def test_failed_startup_revokes_old_generation_even_when_new_token_not_issued(self):
        self.handshake(); add_plugin(self.store, self.package()); token = self.start(); selected = self.select(token)
        package = self.root / 'failed-start'; (package / 'hooks').mkdir(parents=True)
        (package / 'component.json').write_text('{"name":"failed-start"}')
        (package / 'hook.py').write_text('raise RuntimeError("fixture startup failed")\n')
        (package / 'hooks/hooks.json').write_text(json.dumps({'hooks':{'SessionStart':[{'hooks':[{'type':'command','command':sys.executable,'args':[str(package / 'hook.py')]}]}]}}))
        add_plugin(self.store, package)
        result = dispatch_event(self.connection, {'hook_event_name':'SessionStart','session_id':'same-session',
            'cwd':str(self.project),'delivery_id':'failed-new-generation'})
        self.assertTrue(result['blocked'])
        with self.assertRaisesRegex(ValueError, 'current_native_start_context_required'):
            self.gateway.invoke(selected, {}, token)
        self.assertFalse((self.root / 'late-effects').exists())

    def test_native_end_then_transport_close_runs_initialized_cleanup_once(self):
        self.handshake(); package = self.package(startup=True)
        ledger = self.root / 'cleanup-effects'; script = package / 'cleanup.py'
        script.write_text('from pathlib import Path\nwith Path('+repr(str(ledger))+').open("a") as f:f.write("cleanup\\n")\nprint("{}")\n')
        path = package / 'hooks/hooks.json'; body = json.loads(path.read_text())
        body['hooks']['SessionEnd'] = [{'hooks':[{'type':'command','command':sys.executable,'args':[str(script)]}]}]
        path.write_text(json.dumps(body)); add_plugin(self.store, package); token = self.start()
        self.gateway.acquire('', token, describe_connection=True)
        result = dispatch_event(self.connection, {'hook_event_name':'SessionEnd','session_id':'same-session',
            'cwd':str(self.project),'delivery_id':'native-end'})
        self.assertEqual(result['handlers'], ['late:2'])
        self.gateway.close()
        self.assertEqual(ledger.read_text(), 'cleanup\n')
        # The tearDown owns a fresh, unused handle after the closed one.
        self.gateway = Gateway(self.connection)

    def test_new_policy_cannot_reuse_a_completed_cached_selection(self):
        self.handshake(); package = self.package(); add_plugin(self.store, package); token = self.start()
        selected = self.select(token); self.gateway.invoke(selected, {}, token)
        policy = self.root / 'cache-policy'; (policy / 'hooks').mkdir(parents=True)
        (policy / 'component.json').write_text('{"name":"cache-policy"}')
        (policy / 'hook.py').write_text('print(\'{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny"}}\')\n')
        (policy / 'hooks/hooks.json').write_text(json.dumps({'hooks':{'PreToolUse':[{'hooks':[{'type':'command','command':sys.executable,'args':[str(policy / 'hook.py')]}]}]}}))
        add_plugin(self.store, policy)
        with self.assertRaisesRegex(ValueError, 'selection_policy_changed'):
            self.gateway.invoke(selected, {}, token)
        self.assertEqual(self.gateway.invoke(self.select(token), {}, token)['status'], 'denied')
        self.assertEqual((self.root / 'late-effects').read_text(), 'business\n')

    def test_revocation_during_matching_does_not_return_cached_private_result(self):
        self.handshake(); add_plugin(self.store, self.package()); token = self.start()
        selected = self.select(token); self.gateway.invoke(selected, {}, token)
        original = self.gateway.discovery
        def interrupted(value):
            plan = original(value); self.start('revoked-during-matching'); return plan
        with patch.object(self.gateway, 'discovery', interrupted):
            with self.assertRaisesRegex(ValueError, 'current_native_start_context_required'):
                self.gateway.invoke(selected, {}, token)
        self.assertFalse(self.gateway.db.in_transaction)

    def test_policy_added_during_leaf_handshake_stops_business_rpc(self):
        self.handshake(); package = self.package(); add_plugin(self.store, package); token = self.start()
        selected = self.select(token); policy = self.package(name='new-policy', startup=True)
        path = policy / 'hooks/hooks.json'; body = json.loads(path.read_text())
        body['hooks']['PreToolUse'] = body['hooks'].pop('UserPromptSubmit'); path.write_text(json.dumps(body))
        original = Peer.call
        def interrupted(peer, method, params, *args):
            result = original(peer, method, params, *args)
            if method == 'tools/list': add_plugin(self.store, policy)
            return result
        with patch.object(Peer, 'call', interrupted):
            result = self.gateway.invoke(selected, {}, token)
        self.assertEqual(result['effect'], 'business_RPC_not_sent')
        self.assertFalse((self.root / 'late-effects').exists())

    def test_declined_end_delivery_is_retained_after_token_revocation(self):
        self.handshake({'disabledDeliveries':['native_event_bridge']})
        package = self.package(startup=True); ledger = self.root / 'declined-cleanup'; script = package / 'cleanup.py'
        script.write_text('from pathlib import Path\nPath('+repr(str(ledger))+').write_text("effect")\nprint("{}")\n')
        path = package / 'hooks/hooks.json'; body = json.loads(path.read_text())
        body['hooks']['SessionEnd'] = [{'hooks':[{'type':'command','command':sys.executable,'args':[str(script)]}]}]
        path.write_text(json.dumps(body)); add_plugin(self.store, package)
        for mode in ('native', 'transport'):
            with self.subTest(mode=mode):
                token = self.start('generation-'+mode)
                self.gateway.acquire('', token, describe_connection=True)
                event = {'hook_event_name':'SessionEnd','session_id':'same-session','cwd':str(self.project),'delivery_id':mode}
                if mode == 'transport':event['_closing_tokens'] = [token]
                result = dispatch_event(self.connection, event, origin='host' if mode == 'native' else 'transport_close')
                self.assertEqual(result['handlers'], [])
                self.assertFalse(ledger.exists())
                with self.assertRaisesRegex(ValueError, 'current_native_start_context_required'):
                    self.gateway.session(token)


class QwenIdleBindingTests(unittest.TestCase):
    """Synthetic session generations; real Qwen EOF is checked separately."""
    SID = '11111111-1111-4111-8111-111111111111'
    OTHER = '22222222-2222-4222-8222-222222222222'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.project = self.root / 'project'; self.project.mkdir()
        self.store = self.root / 'store'; init_store(self.store, self.project)
        self.profile = self.root / 'profile'
        connect_host(self.store, 'qwen-code', self.profile)
        self.connection = self.profile / 'backpack-connection.json'
        self.gateways = []
        self.ledger = self.root / 'ends'
        package = self.root / 'cleanup'; (package / 'hooks').mkdir(parents=True)
        (package / 'component.json').write_text('{"name":"cleanup"}')
        script = package / 'hook.py'
        script.write_text('import json,sys,pathlib\ne=json.load(sys.stdin)\n'
                         'if e["hook_event_name"]=="SessionEnd":\n'
                         ' with pathlib.Path(' + repr(str(self.ledger)) + ').open("a") as f:f.write("end\\n")\n'
                         'print("{}")\n')
        (package / 'hooks/hooks.json').write_text(json.dumps({'hooks': {
            event: [{'hooks': [{'type': 'command', 'command': sys.executable, 'args': [str(script)]}]}]
            for event in ('SessionStart', 'SessionEnd')}}))
        add_plugin(self.store, package)

    def tearDown(self):
        for gateway in self.gateways:
            gateway.close()
        self.temp.cleanup()

    def start(self, sid=None, delivery='first'):
        output = dispatch_event(self.connection, {'hook_event_name': 'SessionStart',
            'session_id': sid or self.SID, 'cwd': str(self.project), 'delivery_id': delivery})
        return re.search(r'session_token=([^ ]+)', '\n'.join(output['context']))[1]

    def gateway(self, sid=None, tools=True):
        gateway = Gateway(self.connection); self.gateways.append(gateway)
        with patch.dict('os.environ', {'QWEN_CODE_SESSION_ID': sid or self.SID}):
            gateway.initialize({'protocolVersion': '2025-03-26', 'capabilities': {},
                                'clientInfo': {'name': 'fixture', 'version': '1'}})
        if tools:
            gateway.observed('tools/list')
        return gateway

    def close(self, gateway):
        gateway.close(); self.gateways.remove(gateway)

    def test_idle_discovered_session_closes_without_acquire_and_cleans_once(self):
        token = self.start(); gateway = self.gateway()
        self.assertEqual(gateway.native_tokens, {token: self.SID})
        self.close(gateway)
        fresh = self.gateway('33333333-3333-4333-8333-333333333333')
        with self.assertRaisesRegex(ValueError, 'current_native_start_context_required'):
            fresh.session(token)
        self.assertEqual(self.ledger.read_text(), 'end\n')

    def test_protocol_only_probe_does_not_take_session(self):
        token = self.start(); gateway = self.gateway(tools=False)
        self.close(gateway)
        fresh = self.gateway(self.OTHER, tools=False)
        self.assertEqual(fresh.session(token), self.SID)
        self.assertFalse(self.ledger.exists())

    def test_other_session_and_invalid_native_marker_remain_unowned(self):
        token = self.start(); other = self.start(self.OTHER, 'other')
        invalid = self.gateway('invalid-marker'); self.close(invalid)
        gateway = self.gateway(); self.close(gateway)
        fresh = self.gateway('33333333-3333-4333-8333-333333333333')
        self.assertEqual(fresh.session(other), self.OTHER)
        with self.assertRaisesRegex(ValueError, 'current_native_start_context_required'):
            fresh.session(token)
        self.assertEqual(self.ledger.read_text(), 'end\n')

    def test_close_cannot_capture_new_generation_after_initialize(self):
        old = self.start(); gateway = self.gateway(tools=False)
        new = self.start(delivery='second')
        gateway.observed('tools/list'); gateway.observed('tools/list')
        self.assertEqual(gateway.native_tokens, {old: self.SID})
        self.close(gateway)
        fresh = self.gateway(self.OTHER, tools=False)
        self.assertEqual(fresh.session(new), self.SID)
        self.assertFalse(self.ledger.exists())

    def test_native_end_then_transport_close_still_runs_cleanup_once(self):
        self.start(); gateway = self.gateway()
        dispatch_event(self.connection, {'hook_event_name': 'SessionEnd', 'session_id': self.SID,
            'cwd': str(self.project), 'delivery_id': 'native-end'})
        self.close(gateway)
        self.assertEqual(self.ledger.read_text(), 'end\n')

    def test_same_sid_in_another_connection_and_unknown_operations_are_preserved(self):
        token = self.start(); other_profile = self.root / 'other-profile'
        connect_host(self.store, 'qwen-code', other_profile)
        other_connection = other_profile / 'backpack-connection.json'
        output = dispatch_event(other_connection, {'hook_event_name': 'SessionStart',
            'session_id': self.SID, 'cwd': str(self.project), 'delivery_id': 'other-connection'})
        other_token = re.search(r'session_token=([^ ]+)', '\n'.join(output['context']))[1]
        gateway = self.gateway()
        gateway.db.execute('INSERT INTO operations VALUES(?,?,?)', ('old-unknown', 'old-selection', 'unknown'))
        self.close(gateway)
        other = Gateway(other_connection); self.gateways.append(other)
        self.assertEqual(other.session(other_token), self.SID)
        self.assertEqual(other.db.execute('SELECT state FROM operations WHERE id=?',
                                         ('old-unknown',)).fetchone()[0], 'unknown')
        with self.assertRaisesRegex(ValueError, 'current_native_start_context_required'):
            other.session(token)


if __name__ == '__main__': unittest.main()
