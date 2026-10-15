"""Preparation-only replay: no live models, installs or business operations."""
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adapters/codex'))
from market_connect import Market
import market_registry as registry
from market_routing import route


class PreparationEfficiencyTests(TestCase):
    def test_skill_ranking_retains_zero_probability_tail(self):
        call = Mock(return_value=SimpleNamespace(choice='a', confidence=.8,
                    probabilities={'a': .8, 'b': .2, 'c': 0}))
        runtime = SimpleNamespace(_jev_cli=call, _typesafe_http=call,
            MAX_PROVIDER_ATTEMPTS=1, ROUTING_BUDGET_SECONDS=30)
        candidates = [SimpleNamespace(name=k, description=k) for k in 'abc']
        result = route(runtime, 'ordinary need', candidates,
                       {'provider':'jev-cli', 'minimum_confidence':.1}, 'skill-preview')
        self.assertEqual(result.get('inspection_order'), ['a','b','c'])

    def test_slow_success_gets_one_uninterrupted_read_budget(self):
        def slow(executable, url, timeout):
            if timeout < 29.2:
                raise ValueError('registry_read_timeout_or_network_error')
            return {'servers': [], 'metadata': {}}
        with patch.object(registry, 'curl_fetch', side_effect=slow) as call:
            self.assertEqual(registry.fetch('timezone', '', time.monotonic()+35)['servers'], [])
        self.assertEqual(call.call_count, 1)

    def test_package_round_robin_defers_tail_without_losing_it(self):
        for compatible in ['b-first', 'a-tail']:
            with self.subTest(compatible=compatible), tempfile.TemporaryDirectory() as tmp:
                market = object.__new__(Market)
                market.sources = SimpleNamespace(SourceError=RuntimeError)
                market.runtime = SimpleNamespace(_read_skill=lambda path: SimpleNamespace(description=path.parent.name))
                market.gateway = SimpleNamespace(public_access=SimpleNamespace(safe=lambda p:p))
                market._preview_remaining = 2
                market._preview_deadline = time.monotonic()+30
                rows = [{'name':'a','description':'a'}, {'name':'b','description':'b'}]
                checked, rankings = [], []
                def prepare(plan, source, snapshot, row):
                    plan.update(name=row['name'], skills=[])
                    for suffix in (['first','tail'] if row['name']=='a' else ['first']):
                        p=Path(tmp)/(row['name']+'-'+suffix);p.mkdir(exist_ok=True)
                        (p/'SKILL.md').write_text(p.name)
                        plan['skills'].append({'name':p.name, 'path':str(p)})
                def choose(need, choices, kind):
                    if kind=='plugin-preview':
                        return choices[0],{'status':'selected','_ranked_rows':choices[1:]}
                    if kind=='plugin-skill-preview':
                        rankings.append([x['name'] for x in choices])
                        return choices[0],{'status':'selected','_ranked_rows':choices[1:]}
                    import json
                    body=json.loads(choices[0]['description']);checked.append(body['name'])
                    return (choices[0] if body['name']==compatible else None),{'status':'selected' if body['name']==compatible else 'none','confidence':.9}
                market.choose=choose; market.prepare_plugin_candidate=prepare
                plan={'need':'ordinary need','routing':[], 'skills':[], 'servers':[]}
                self.assertIsNone(market.prepare_plugin_group(plan,'source',{},rows,[]))
                self.assertEqual(checked, ['a-first','b-first'] + ([] if compatible=='b-first' else ['a-tail']))
                self.assertEqual([s['name'] for s in plan['skills']], [compatible])
                self.assertEqual(sum(1 for rank in rankings if 'a-first' in rank or 'a-tail' in rank), 1)
                self.assertFalse(any(k.startswith('_guidance') for k in plan))

    def test_oversized_component_does_not_discard_usable_sibling(self):
        with tempfile.TemporaryDirectory() as tmp:
            market=object.__new__(Market)
            market.runtime=SimpleNamespace(_read_skill=lambda path:SimpleNamespace(description=path.parent.name))
            market.gateway=SimpleNamespace(public_access=SimpleNamespace(safe=lambda p:p))
            skills=[]
            for name,body in [('oversized','x'*48001),('useful','Use a local repeatable check.')]:
                path=Path(tmp)/name;path.mkdir();(path/'SKILL.md').write_text(body)
                skills.append({'name':name,'path':str(path)})
            def choose(need,rows,kind):
                if kind=='plugin-skill-preview':return rows[0],{'status':'selected','_ranked_rows':rows[1:]}
                return rows[0],{'status':'selected','confidence':.9}
            market.choose=choose
            plan={'name':'package','need':'check local code','skills':skills,'routing':[]}
            self.assertTrue(market.portable_guidance_fit(plan))
            self.assertEqual([s['name'] for s in plan['skills']], ['useful'])

    def test_event_recorder_preserves_original_events_and_separates_timings(self):
        import importlib.util, io, json
        location=Path(__file__).resolve().parents[1]/'benchmarks/market-blind/run.py'
        spec=importlib.util.spec_from_file_location('market_benchmark_run',location)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        event=json.dumps({'type':'item.completed','item':{'id':'x','type':'command_execution','command':'private command'}})+'\n'
        with tempfile.TemporaryDirectory() as tmp:
            output=io.StringIO();timings=Path(tmp)/'times.jsonl'
            module.record_native_events(io.StringIO(event),output,timings,time.monotonic())
            self.assertEqual(output.getvalue(),event)
            result=json.loads(timings.read_text())
            self.assertEqual(result['item_id'],'x')
            self.assertNotIn('private command',timings.read_text())

    def test_bound_guidance_preserved_with_scope_hint(self):
        import market_protocol
        connection={'_descriptor':'descriptor','data_root':'store','project_root':None}
        context={'need':'original need','keys':['a']}
        selected={'status':'selected','name':'sample','content':'complete original guidance'}
        reader=Mock();reader.request.return_value=selected
        gateway=SimpleNamespace(load_connection=lambda _: {'enabled':True}, Router=lambda *a,**k:reader)
        market=SimpleNamespace(bound_skill_context=lambda _:context)
        actual=market_protocol.dispatch(gateway,connection,None,market,'acquire_skill',{'market_selection':'handle'})
        self.assertEqual(actual['content'],selected['content'])
        self.assertIn('required artifact and its checks',actual['application_scope'])
        self.assertEqual(reader.request.call_args.args[1]['need'],'original need')

    def test_task_scope_survives_resource_disclosure_without_rewriting_it(self):
        import market_protocol
        connection={'_descriptor':'descriptor','data_root':'store','project_root':None}
        resource={'status':'selected','resources':[{'content':'Full template with extra features.'}],
                  'instruction':'Read the selected resource completely.'}
        reader=Mock();reader.request.return_value=resource
        gateway=SimpleNamespace(load_connection=lambda _: {'enabled':True})
        actual=market_protocol.dispatch(gateway,connection,reader,None,'acquire_resource',{'need':'original need'})
        self.assertEqual(actual['resources'],resource['resources'])
        self.assertEqual(actual['instruction'],resource['instruction'])
        self.assertIn('application_scope',actual)

    def test_task_scope_is_in_both_disclosure_tool_descriptions(self):
        import market_protocol
        rows=[{'name':n,'description':'Read guidance.', 'inputSchema':{'properties':{}}}
              for n in ('acquire_skill','acquire_resource')]
        gateway=SimpleNamespace(PERSISTENT_TOOLS=rows)
        catalog=market_protocol.tool_catalog(gateway)
        for row in catalog[:2]:
            self.assertIn('user',row['description'])
            self.assertIn('scope',row['description'])
        self.assertEqual(rows[1]['description'],'Read guidance.')

    def test_oversized_report_is_rejected_before_write_with_specific_recovery(self):
        import market_protocol
        connection={'_descriptor':'descriptor','data_root':'store','project_root':None}
        reader=Mock();reader.report.side_effect=ValueError('invalid_usage_report')
        gateway=SimpleNamespace(load_connection=lambda _: {'enabled':True})
        args={'selection':'selected','event':'completed','run':'same-run','summary':'x'*505}
        actual=market_protocol.dispatch(gateway,connection,reader,None,'report_skill_use',args)
        self.assertFalse(actual['recorded'])
        self.assertEqual(actual['max_summary_characters'],500)
        reader.report.assert_not_called()
        reader.report.side_effect=None;reader.report.return_value={'status':'recorded'}
        args['summary']='x'*500
        actual=market_protocol.dispatch(gateway,connection,reader,None,'report_skill_use',args)
        self.assertEqual(actual['status'],'recorded')
        self.assertEqual(reader.report.call_args.args[0]['summary'],args['summary'])


if __name__ == '__main__': main()
