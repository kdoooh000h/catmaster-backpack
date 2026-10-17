"""Staged MCP selection; optional real Runtime with mocked upstream clients.

Set CATMASTER_STANDALONE_RUNTIME to an existing standalone checkout. Integration
state stays in /private/tmp; routing and clients never invoke a provider/network.
"""
from contextlib import nullcontext
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'adapters/codex'))
import market_mcp_runtime as staged


class StagedMCPTests(unittest.TestCase):
    def module(self):
        class Router:
            def __init__(self,data,*args):self.data=data
            def _choose(self,*args):return {'legacy':True}
        class Runtime:
            def __init__(self,data):self.data=data
            def acquire(self,connection,need):
                result=module.Router(self.data)._choose(need,[SimpleNamespace(name='server')],'mcp-server')
                if result['status']!='selected':return result
                result=module.Router(self.data)._choose(need,[SimpleNamespace(name='read')],'mcp-tool')
                if result['status']!='selected':return result
                return {'status':'selected','selection':'opaque','server':'graph','tool':{'name':'read','inputSchema':{'type':'object'}}}
            def invoke(self,*args):return 'original dispatch'
        module=SimpleNamespace(Router=Router,Runtime=Runtime,
            public_access=SimpleNamespace(owner_json=lambda path:json.loads(path.read_text())),
            runtime=SimpleNamespace(Skill=lambda name,description,path:SimpleNamespace(name=name,description=description,path=path)))
        return module

    def test_provisional_ranking_requires_strict_actual_schema_fit(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temp:
            module=self.module();base=module.Runtime
            answers=[{'status':'selected','skill':'server','confidence':.2},
                     {'status':'selected','skill':'read','confidence':.51},
                     {'status':'uncertain','skill':None,'confidence':.6}]
            with patch('market_routing.route',side_effect=answers) as route, \
                    patch.dict(sys.modules,{'backpack_provider_environment':SimpleNamespace(load=lambda data:None)}):
                runtime=staged.install_selection(module)(Path(temp))
                result=runtime.acquire('connection','Read stored relations')
            self.assertEqual(result['status'],'uncertain')
            self.assertNotIn('selection',result)
            self.assertEqual([c.args[4] for c in route.call_args_list],['mcp-discovery','mcp-tool-preview','mcp-fit'])
            self.assertEqual([c.args[3]['minimum_confidence'] for c in route.call_args_list],[.1,.1,.7])
            self.assertIn('inputSchema',route.call_args.args[2][0].description)
            self.assertIs(type(runtime).invoke,base.invoke)

    def test_final_fit_preserves_stricter_setting_and_only_releases_on_pass(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temp:
            data=Path(temp);(data/'config.json').write_text(json.dumps({'version':1,'minimum_confidence':.9}))
            module=self.module()
            with patch('market_routing.route',return_value={'status':'selected','skill':'read','confidence':.96}), \
                    patch.dict(sys.modules,{'backpack_provider_environment':SimpleNamespace(load=lambda data:None)}):
                runtime=staged.install_selection(module)(data)
                result=runtime.acquire('connection','Read stored relations')
            self.assertEqual(result['selection'],'opaque')
            self.assertEqual(result['validation']['minimum_confidence'],.9)
            self.assertEqual(result['routing_policy'],staged.POLICY)

    def test_runtime_does_not_start_over_live_unavailable_service(self):
        module=SimpleNamespace(public_access=SimpleNamespace(safe=lambda p:Path(p)),
            runtime=SimpleNamespace(backpack_maintenance=SimpleNamespace(target_lock=lambda *args:nullcontext())),
            service_info=lambda data:{'pid':12},service_call=Mock(side_effect=RuntimeError('unavailable')),
            os=SimpleNamespace(kill=Mock()),MCPError=RuntimeError)
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temp,patch.object(staged.subprocess,'Popen') as start:
            with self.assertRaisesRegex(RuntimeError,'service_alive_but_unavailable'):
                staged.ensure_service(SimpleNamespace(mcp_backpack=module),temp,'/runtime')
            start.assert_not_called()

    def service_module(self):
        return SimpleNamespace(public_access=SimpleNamespace(safe=lambda p:Path(p)),
            runtime=SimpleNamespace(backpack_maintenance=SimpleNamespace(target_lock=lambda *args:nullcontext())),
            service_info=Mock(return_value={'pid':12}), service_call=Mock(),
            os=SimpleNamespace(kill=Mock()), MCPError=RuntimeError)

    def test_live_service_with_wrong_root_or_pid_is_never_replaced_or_shutdown(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temp:
            for ping in ({'data_root':temp+'/other','pid':12}, {'data_root':temp,'pid':13}):
                with self.subTest(ping=ping):
                    module=self.service_module();module.service_call.return_value=ping
                    module.os.kill.side_effect=ProcessLookupError()
                    with patch.object(staged.subprocess,'Popen') as start:
                        with self.assertRaisesRegex(RuntimeError,'service_identity_mismatch'):
                            staged.ensure_service(SimpleNamespace(mcp_backpack=module),temp,'/runtime')
                    start.assert_not_called()
                    module.os.kill.assert_not_called()
                    module.service_call.assert_called_once_with(Path(temp),'ping',timeout=2)

    def test_healthy_service_with_matching_root_and_pid_is_reused(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temp:
            module=self.service_module();module.service_call.return_value={'data_root':temp,'pid':12}
            with patch.object(staged.subprocess,'Popen') as start:
                staged.ensure_service(SimpleNamespace(mcp_backpack=module),temp,'/runtime')
            start.assert_not_called();module.os.kill.assert_not_called()
            module.service_call.assert_called_once_with(Path(temp),'ping',timeout=2)

    def validated_result(self):
        result={'selection':'a'*32,'server':'Graph',
                'tool':{'name':'read','inputSchema':{'type':'object'}},
                'routing_policy':staged.POLICY,
                'validation':{'status':'selected','confidence':.92,'minimum_confidence':.8}}
        result['validation_binding']=staged.validation_binding('Read stored relations',result)
        return result

    def test_reusable_validation_requires_current_threshold(self):
        result=self.validated_result()
        self.assertTrue(staged.reusable_validation('Read stored relations',result,.7))
        self.assertTrue(staged.reusable_validation('Read stored relations',result,.8))
        self.assertFalse(staged.reusable_validation('Read stored relations',result,.85))
        result['validation']['confidence']=.75
        self.assertFalse(staged.reusable_validation('Read stored relations',result,.8))

    def test_reusable_validation_binds_need_selection_server_and_actual_schema(self):
        result=self.validated_result()
        self.assertFalse(staged.reusable_validation('Write stored relations',result,.7))
        changes={'selection':'b'*32,'server':'Other Graph',
                 'tool':{'name':'read','inputSchema':{'type':'object','required':['id']}}}
        for key,value in changes.items():
            with self.subTest(key=key):
                changed={**result,key:value}
                self.assertNotEqual(staged.validation_binding('Read stored relations',changed),result['validation_binding'])
                self.assertFalse(staged.reusable_validation('Read stored relations',changed,.7))
        for validation in ({'status':'uncertain','confidence':.92,'minimum_confidence':.8},
                           {'status':'selected','confidence':float('nan'),'minimum_confidence':.8},
                           {'status':'selected','confidence':.92,'minimum_confidence':float('inf')}):
            with self.subTest(validation=validation):
                self.assertFalse(staged.reusable_validation('Read stored relations',{**result,'validation':validation},.7))
        self.assertFalse(staged.reusable_validation('Read stored relations',{**result,'routing_policy':'old'},.7))


RUNTIME=os.environ.get('CATMASTER_STANDALONE_RUNTIME')


@unittest.skipUnless(RUNTIME,'set CATMASTER_STANDALONE_RUNTIME for real Runtime boundary checks')
class StandaloneRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(RUNTIME).resolve(strict=True)
        paths=[str(root/folder) for folder in ('core','scripts','adapters/standalone')]
        with patch.object(sys,'path',paths+sys.path):
            spec=importlib.util.spec_from_file_location('market_mcp_test_standalone',root/'core/mcp_backpack.py')
            cls.shared=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.shared)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name)
        self.connection='codex-public-gateway-'+'a'*48+'.json'
        self.binding={'version':2,'data_root':str(self.data),'project_root':None,'enabled':True}
        self.write(self.data/self.connection,self.binding)
        self.server='b'*32
        self.row={'id':self.server,'title':'Synthetic Graph','description':'Read stored relations',
                  'enabled':True,'revision':'initial','connections':[self.connection],
                  'configuration':{'transport':'stdio','command':[sys.executable],'env':{}}}
        self.save_server()
        self.write(self.data/'config.json',{'version':1,'minimum_confidence':.6})
        self.tool={'name':'read','description':'Read stored relations',
                   'inputSchema':{'type':'object','properties':{'id':{'type':'string'}},'required':['id']}}
        self.client=Mock(closed=False)
        self.client.tools.return_value=[self.tool]
        self.client.call.return_value={'content':[{'type':'text','text':'synthetic result'}]}
        self.patch(patch.object(self.shared,'Client',return_value=self.client))
        self.patch(patch.object(staged.subprocess,'Popen',side_effect=AssertionError('unexpected subprocess')))
        self.route=self.patch(patch('market_routing.route',side_effect=self.choose))
        self.patch(patch.dict(sys.modules,{'backpack_provider_environment':SimpleNamespace(load=lambda data:None)}))
        # install_selection replaces Router in this module; restore it per test.
        self.patch(patch.object(self.shared,'Router',self.shared.Router))
        runtime_type=staged.install_selection(self.shared)
        self.service=runtime_type(self.data)
        self.addCleanup(self.service.close)
        self.assertIs(runtime_type.invoke,self.shared.Runtime.invoke)

    def patch(self,patcher):
        value=patcher.start();self.addCleanup(patcher.stop);return value

    def write(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value));path.chmod(0o600)

    def save_server(self):
        self.write(self.data/'mcp-servers.json',{'version':1,'servers':{self.server:self.row}})

    def choose(self,runtime,need,candidates,config,stage):
        return {'status':'selected','skill':candidates[0].name,
                'confidence':.99 if stage=='mcp-fit' else .2}

    def acquire(self):
        result=self.service.acquire(self.connection,'Read stored relations')
        self.assertEqual(result['status'],'selected')
        self.assertTrue(staged.reusable_validation('Read stored relations',result,.7))
        self.client.call.assert_not_called()
        return result['selection']

    def test_tool_preview_uses_actual_complete_schemas_without_extra_listing(self):
        self.acquire()
        preview=next(c for c in self.route.call_args_list if c.args[4]=='mcp-tool-preview')
        self.assertEqual(json.loads(preview.args[2][0].description),self.tool)
        self.assertEqual(self.client.tools.call_count,1)
        self.assertIs(self.service.client(self.row,self.connection),self.client)

    def test_rejected_actual_schema_never_creates_a_ticket_or_dispatches(self):
        def choose(runtime,need,candidates,config,stage):
            if stage=='mcp-fit':return {'status':'uncertain','skill':None,'confidence':.6}
            return self.choose(runtime,need,candidates,config,stage)
        self.route.side_effect=choose
        result=self.service.acquire(self.connection,'Read stored relations')
        self.assertEqual(result['status'],'uncertain')
        self.assertEqual(result['phase'],'actual_tool_validation')
        self.assertNotIn('selection',result)
        paths=list((self.data/'mcp-selections').glob('*.json'))
        self.assertEqual(paths,[])
        self.assertTrue(result['search_exhausted'])
        self.assertFalse(result['unexhausted'])
        self.assertEqual(result['rejected_tools'][0]['tool'],'read')
        self.client.call.assert_not_called()
        self.assertFalse((self.data/'mcp-calls').exists())

    def test_rejected_leaf_keeps_every_other_candidate_and_only_validated_leaf_gets_ticket(self):
        rejected={**self.tool,'name':'candidate-one'}
        other={**self.tool,'name':'candidate-three'}
        self.client.tools.return_value=[rejected,self.tool,other]
        def choose(runtime,need,candidates,config,stage):
            if stage=='mcp-fit' and json.loads(candidates[0].description)['tool']['name']=='candidate-one':
                return {'status':'uncertain','skill':None,'confidence':.6}
            return self.choose(runtime,need,candidates,config,stage)
        self.route.side_effect=choose
        result=self.service.acquire(self.connection,'Read stored relations')
        self.assertEqual(result['status'],'selected')
        self.assertEqual(result['tool'],self.tool)
        self.assertTrue(staged.reusable_validation('Read stored relations',result,.7))
        self.assertEqual([row['tool'] for row in result['rejected_tools']],['candidate-one'])
        previews=[call for call in self.route.call_args_list if call.args[4]=='mcp-tool-preview']
        self.assertEqual([[row.name for row in call.args[2]] for call in previews],
                         [['candidate-one','read','candidate-three'],['read','candidate-three']])
        fits=[call for call in self.route.call_args_list if call.args[4]=='mcp-fit']
        self.assertEqual(len(fits),2)
        self.assertEqual([call.args[3]['minimum_confidence'] for call in fits],[.7,.7])
        paths=list((self.data/'mcp-selections').glob('*.json'))
        self.assertEqual([path.stem for path in paths],[result['selection']])
        self.assertEqual(self.shared.public_access.owner_json(paths[0])['tool'],self.tool)
        self.client.tools.assert_called_once()
        self.shared.Client.assert_called_once()
        self.client.call.assert_not_called()

    def test_three_rejections_report_unexhausted_candidates_without_ticket(self):
        self.client.tools.return_value=[{**self.tool,'name':f'candidate-{n}'} for n in range(4)]
        def choose(runtime,need,candidates,config,stage):
            if stage=='mcp-fit':return {'status':'none','skill':None,'confidence':.9}
            return self.choose(runtime,need,candidates,config,stage)
        self.route.side_effect=choose
        result=self.service.acquire(self.connection,'Read stored relations')
        self.assertEqual(result['status'],'uncertain')
        self.assertEqual(result['reason'],'tool_validation_budget_exhausted')
        self.assertTrue(result['unexhausted'])
        self.assertFalse(result['search_exhausted'])
        self.assertEqual(result['remaining_candidates'],1)
        self.assertEqual([row['tool'] for row in result['rejected_tools']],
                         ['candidate-0','candidate-1','candidate-2'])
        self.assertEqual(len(self.route.call_args_list),7)
        self.client.tools.assert_called_once()
        self.shared.Client.assert_called_once()
        self.client.call.assert_not_called()
        self.assertFalse((self.data/'mcp-selections').exists())

    def test_provider_failure_does_not_search_another_leaf(self):
        self.client.tools.return_value=[self.tool,{**self.tool,'name':'other'}]
        def choose(runtime,need,candidates,config,stage):
            if stage=='mcp-fit':raise RuntimeError('provider_unavailable')
            return self.choose(runtime,need,candidates,config,stage)
        self.route.side_effect=choose
        with self.assertRaisesRegex(RuntimeError,'provider_unavailable'):
            self.service.acquire(self.connection,'Read stored relations')
        self.assertEqual([call.args[4] for call in self.route.call_args_list],
                         ['mcp-discovery','mcp-tool-preview','mcp-fit'])
        bounded=self.route.call_args.args[0]
        self.assertEqual(bounded.MAX_PROVIDER_ATTEMPTS,1)
        self.assertLessEqual(bounded.ROUTING_BUDGET_SECONDS,40)
        self.assertFalse((self.data/'mcp-selections').exists())
        self.client.call.assert_not_called()

    def test_elapsed_budget_stops_before_another_provider_call(self):
        with patch.object(staged.time,'monotonic',side_effect=[0,0,41]):
            result=self.service.acquire(self.connection,'Read stored relations')
        self.assertEqual(result['reason'],'tool_validation_budget_exhausted')
        self.assertTrue(result['unexhausted'])
        self.assertEqual(result['remaining_candidates'],1)
        self.assertEqual([call.args[4] for call in self.route.call_args_list],
                         ['mcp-discovery','mcp-tool-preview'])
        self.assertFalse((self.data/'mcp-selections').exists())
        self.client.call.assert_not_called()

    def test_unknown_fit_does_not_reject_leaf_or_search_another(self):
        self.client.tools.return_value=[self.tool,{**self.tool,'name':'other'}]
        def choose(runtime,need,candidates,config,stage):
            if stage=='mcp-fit':return {'status':'unknown','reason':'unobservable_provider_result'}
            return self.choose(runtime,need,candidates,config,stage)
        self.route.side_effect=choose
        result=self.service.acquire(self.connection,'Read stored relations')
        self.assertEqual(result['status'],'unknown')
        self.assertEqual(result['rejected_tools'],[])
        self.assertEqual(result['remaining_candidates'],2)
        self.assertTrue(result['unexhausted'])
        self.assertEqual(len(self.route.call_args_list),3)
        self.assertFalse((self.data/'mcp-selections').exists())
        self.client.call.assert_not_called()

    def test_completed_receipt_replay_does_not_redispatch(self):
        selection=self.acquire();arguments={'id':'one'}
        result=self.service.invoke(self.connection,selection,arguments)
        self.assertEqual(result['status'],'completed')
        persisted=self.shared.public_access.owner_json(self.data/'mcp-calls'/(selection+'.json'))
        self.assertEqual(persisted['status'],'completed')
        self.assertEqual(self.service.invoke(self.connection,selection,arguments),result)
        self.client.call.assert_called_once_with('read',arguments)
        with self.assertRaisesRegex(self.shared.MCPError,'call_arguments_changed'):
            self.service.invoke(self.connection,selection,{'id':'changed'})
        self.assertEqual(self.client.call.call_count,1)

    def test_unknown_receipt_stays_unknown_and_blocks_fresh_dispatch(self):
        selection=self.acquire();arguments={'id':'one'}
        self.client.call.side_effect=self.shared.MCPError('upstream_result_lost')
        result=self.service.invoke(self.connection,selection,arguments)
        self.assertEqual(result['status'],'unknown')
        self.assertEqual(self.service.invoke(self.connection,selection,arguments),result)
        self.assertEqual(self.shared.public_access.owner_json(
            self.data/'mcp-calls'/(selection+'.json'))['status'],'unknown')
        # Acquisition itself is still read-only; an unresolved call blocks invoke.
        fresh=self.service.acquire(self.connection,'Read stored relations')['selection']
        with self.assertRaisesRegex(self.shared.MCPError,'unresolved_call_blocks_server'):
            self.service.invoke(self.connection,fresh,{'id':'two'})
        self.client.call.assert_called_once_with('read',arguments)

    def test_current_grants_and_configuration_gate_even_completed_receipts(self):
        selection=self.acquire();arguments={'id':'one'}
        self.assertEqual(self.service.invoke(self.connection,selection,arguments)['status'],'completed')
        original=copy.deepcopy(self.row)
        cases=('connection_disabled','grant_removed','server_disabled','configuration_changed')
        for case in cases:
            with self.subTest(case=case):
                self.row=copy.deepcopy(original)
                self.write(self.data/self.connection,self.binding)
                if case=='connection_disabled':
                    self.write(self.data/self.connection,{**self.binding,'enabled':False})
                    error='connection_revoked'
                elif case=='grant_removed':
                    self.row['connections']=[];error='agent_not_authorized'
                elif case=='server_disabled':
                    self.row['enabled']=False;error='server_revoked_or_changed'
                else:
                    self.row['configuration']['env']={'SYNTHETIC_SETTING':'changed'}
                    self.row['revision']='changed';error='server_revoked_or_changed'
                self.save_server()
                with self.assertRaisesRegex(self.shared.MCPError,error):
                    self.service.invoke(self.connection,selection,arguments)
                self.assertEqual(self.client.call.call_count,1)


if __name__=='__main__':unittest.main()
