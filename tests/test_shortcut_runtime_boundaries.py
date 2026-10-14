"""Optional views/usage never break transport, quarantine or leaf permissions.

Backends and host events here are explicitly simulated test fixtures.
"""
import json
from unittest.mock import MagicMock,patch
import unittest
import test_plugin_pipeline as fixtures
import test_directory_shortcuts as shortcut_fixtures
import capability_usage
import plugin_directory as directory
import plugin_runtime

class OptionalDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.f=shortcut_fixtures.DirectoryShortcutTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
    def test_corrupt_direct_file_disables_only_aliases(self):
        f=self.f;f.refresh();f.pin('query');f.refresh()
        (f.store/capability_usage.DIRECT_FILE).write_text('{broken')
        view=directory.first_layer(f.store,f.entries())
        self.assertEqual(view['direct_status'],'unavailable');self.assertEqual(view['direct'],[])
        provider=shortcut_fixtures.RouteProvider(f.key('query'),('data_content','data_query'))
        self.assertEqual(f.select(provider)['choice'],f.key('query'))
        self.assertEqual(len(provider.calls),3)
    def test_corrupt_alias_preserves_previously_direct_only_capability(self):
        f=self.f;f.refresh();f.populate(('query','rare_write','fresh'));f.pin('fresh');f.refresh()
        (f.store/capability_usage.DIRECT_FILE).write_text('{broken')
        tree=f.tree()
        self.assertIn(f.key('fresh'),tree.members(tree.root_ids))
        self.assertIn('registered_unclassified',tree.root_ids)

class RuntimeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.PipelineTests();self.f.setUp();self.addCleanup(self.f.tearDown)
    def client(self):
        f=self.f;f.service();token=f.token(f.start());gateway=fixtures.Gateway(f.connection)
        self.addCleanup(gateway.close);return gateway,token
    def test_unknown_post_hook_never_counts_as_successful_use(self):
        gateway,token=self.client();selection=self.f.select(gateway,token)
        with patch.object(gateway,'after',return_value={'status':'unknown','context':[]}):
            result=gateway.invoke(selection,{},token)
        self.assertEqual(result['status'],'completed');self.assertEqual(result['post_hook_status'],'unknown')
        row=gateway.db.execute('SELECT state FROM operations WHERE selection=?',(selection,)).fetchone()
        self.assertEqual(row['state'],'unknown')
        entries=directory.registered_entries(directory.load_registry(self.f.store)[2])
        self.assertEqual(capability_usage.frequent_ids(self.f.store,entries,min_uses=1),[])
    def test_completed_receipt_replay_does_not_double_count_or_redispatch(self):
        gateway,token=self.client();selection=self.f.select(gateway,token)
        self.assertEqual(gateway.invoke(selection,{},token)['status'],'completed')
        ledger=(self.f.store/'operations.jsonl').read_bytes()
        self.assertEqual(gateway.invoke(selection,{},token)['status'],'completed')
        self.assertEqual((self.f.store/'operations.jsonl').read_bytes(),ledger)
        entries=directory.registered_entries(directory.load_registry(self.f.store)[2])
        recent=capability_usage.frequent_ids(self.f.store,entries,min_uses=1)
        self.assertEqual(len(recent),1);self.assertEqual(recent[0]['uses'],1)
    def test_denied_leaf_is_hidden_and_cannot_use_direct_confirmation(self):
        gateway,token=self.client();entries=directory.registered_entries(directory.load_registry(self.f.store)[2])
        key=next(k for k,e in entries.items() if e['kind']=='tool')
        capability_usage.configure_direct(self.f.store,[key],entries)
        path=self.f.profile/'settings.json';settings=json.loads(path.read_text())
        entry=entries[key];settings['permissions']={'deny':['mcp__'+entry['server']+'__'+entry['target']]}
        path.write_text(json.dumps(settings))
        self.assertEqual(gateway.public_view(session_token=token)['first_layer']['direct'],[])
        with patch('plugin_directory.JevHierarchyProvider',side_effect=AssertionError('denied alias must not reach model')):
            self.assertEqual(gateway.acquire('actual tool result',token,capability_id=key)['status'],'unavailable')
    def test_corrupt_alias_does_not_end_subscribed_transport(self):
        gateway,token=self.client();f=self.f
        class Classifier:
            calls=[]
            def noul(self,spec,state):
                return {'answers':{k:({'type':'choice','choice':'data_query','confidence':.9} if k=='primary' else
                                    {'type':'noul','noul':.9 if k=='data_query' else .01}) for k in spec['questions']}}
        directory.refresh(f.store,provider_factory=Classifier)
        entries=directory.registered_entries(directory.load_registry(f.store)[2])
        key=next(k for k,e in entries.items() if e['kind']=='tool');capability_usage.configure_direct(f.store,[key],entries)
        directory.refresh(f.store,provider_factory=Classifier)
        (f.store/capability_usage.DIRECT_FILE).write_text('{broken')
        gateway.subscription=True;selector=MagicMock();selector.__enter__.return_value=selector
        selector.select.side_effect=[[],[(object(),1)]]
        with patch('plugin_runtime.selectors.DefaultSelector',return_value=selector),patch('plugin_runtime.os.read',return_value=b'{"id":1,"method":"ping"}\n'):
            packets=plugin_runtime.stdio_packets(gateway)
            self.assertEqual(next(packets)['method'],'ping');packets.close()
        self.assertEqual(gateway.public_view(session_token=token)['first_layer']['direct_status'],'unavailable')
        self.assertTrue(gateway.public_view(session_token=token)['first_layer']['categories'])
    def guidance_client(self):
        f=self.f;package=f.plugin('library');(package/'skills/one').mkdir(parents=True)
        (package/'skills/one/SKILL.md').write_text('---\nname: one\ndescription: Apply a public review procedure.\n---\nReview the supplied code and record findings.\n')
        fixtures.add_plugin(f.store,package);fixtures.connect_host(f.store,'claude-code',f.profile)
        token=f.token(f.start());gateway=fixtures.Gateway(f.connection);self.addCleanup(gateway.close)
        return gateway,token,f.select(gateway,token,kind='skill')
    def test_guidance_delivery_does_not_count_and_report_is_idempotent(self):
        gateway,token,selection=self.guidance_client();entries=directory.registered_entries(directory.load_registry(self.f.store)[2])
        self.assertEqual(capability_usage.frequent_ids(self.f.store,entries,min_uses=1),[])
        first=gateway.report_use(selection,token);second=gateway.report_use(selection,token)
        self.assertEqual(first,{'status':'recorded','counted':True,'evidence':'agent_reported'})
        self.assertEqual(second,{'status':'duplicate','counted':False,'evidence':'agent_reported'})
        self.assertEqual(capability_usage.frequent_ids(self.f.store,entries,min_uses=1)[0]['uses'],1)
    def test_other_session_cannot_report_guidance_use(self):
        gateway,token,selection=self.guidance_client()
        other=self.f.token(self.f.start('other-session','other-start'))
        with self.assertRaisesRegex(ValueError,'selection_session_scope_conflict'):gateway.report_use(selection,other)
        entries=directory.registered_entries(directory.load_registry(self.f.store)[2])
        self.assertEqual(capability_usage.frequent_ids(self.f.store,entries,min_uses=1),[])
    def test_all_native_usage_report_aliases_skip_leaf_hooks(self):
        f=self.f
        package=f.plugin('deny-business',event='PreToolUse',output={
            'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny',
                                  'permissionDecisionReason':'Business calls are denied.'}})
        fixtures.add_plugin(f.store,package)
        fixtures.connect_host(f.store,'claude-code',f.profile)
        f.start()
        aliases=('mcp__backpack__report_use','backpack_report_use','backpack__report_use',
                 'mcp_backpack_report_use','backpack___report_use')
        for name in aliases:
            with self.subTest(name=name):
                result=fixtures.dispatch_event(f.connection,{'hook_event_name':'PreToolUse',
                    'session_id':'s1','cwd':str(f.project),'delivery_id':name,'tool_name':name})
                self.assertFalse(result['blocked']);self.assertEqual(result['handlers'],[])
        leaf=fixtures.dispatch_event(f.connection,{'hook_event_name':'PreToolUse',
            'session_id':'s1','cwd':str(f.project),'delivery_id':'actual-business',
            'tool_name':'mcp__service__query'})
        self.assertTrue(leaf['blocked']);self.assertTrue(leaf['handlers'])
    def test_first_subscription_snapshot_failure_still_allows_ping(self):
        gateway,token=self.client();gateway.subscription=False
        selector=MagicMock();selector.__enter__.return_value=selector
        selector.select.side_effect=[[(object(),1)],[(object(),1)]]
        chunks=[b'{"id":1,"method":"resources/subscribe"}\n',b'{"id":2,"method":"ping"}\n']
        with patch('plugin_runtime.selectors.DefaultSelector',return_value=selector),patch('plugin_runtime.os.read',side_effect=chunks),patch.object(gateway,'public_view',side_effect=ValueError('optional snapshot failure')):
            packets=plugin_runtime.stdio_packets(gateway)
            self.assertEqual(next(packets)['method'],'resources/subscribe')
            gateway.subscription=True
            self.assertEqual(next(packets)['method'],'ping');packets.close()

if __name__=='__main__':unittest.main()
