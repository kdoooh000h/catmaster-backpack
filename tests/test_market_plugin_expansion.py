"""Registered marketplace discovery and same-call rank reuse; no live calls."""
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adapters/codex'))
from market_connect import Market, register_public_plugin_markets
from market_routing import route


class ExpansionTests(unittest.TestCase):
    def test_publisher_markets_are_available_without_rewriting_user_source_registry(self):
        module=SimpleNamespace(BUILTINS=[{'id':'anthropic','repo':'official/catalog'}])
        register_public_plugin_markets(module);register_public_plugin_markets(module)
        self.assertEqual([r['id'] for r in module.BUILTINS],
            ['anthropic','github:wshobson/agents','github:trailofbits/skills'])
        self.assertEqual(module.BUILTINS[0]['repo'],'official/catalog')

    def market(self):
        market = object.__new__(Market)
        rows = [{'id':'github:public/catalog','name':'public/catalog','agent':'claude','about':'Review, debugging and test guidance'},
                {'id':'opencode','name':'other format','agent':'opencode'}]
        market.manager = SimpleNamespace(plugins=SimpleNamespace(sources=SimpleNamespace(
            listing=lambda: {'sources':rows})))
        market.current = Mock(return_value={})
        market.recent_plugin_catalog = Mock(return_value=None)
        market.descriptor = 'isolated-test-connection.json'
        market.runtime = SimpleNamespace(_sensitive=lambda need: False)
        market.folder = Path('/unused')
        return market

    def test_only_registered_claude_markets_enter_directories(self):
        market = self.market()
        self.assertEqual([r['id'] for r in market.plugin_directories()],
                         ['anthropic','openai','github:public/catalog'])
        self.assertIn('Review, debugging and test guidance',market.plugin_directories()[-1]['description'])
        market.choose = Mock()
        with self.assertRaisesRegex(ValueError,'unsupported_market_source'):
            market.prepare({'kind':'plugin','need':'review this file','source':'github:unregistered/repo'})
        market.choose.assert_not_called()

    def prepare_market(self, temporary, explicit=False, failure=None):
        market = self.market()
        market.folder = Path(temporary) / 'plans'
        market.marker = Mock(return_value=None)
        market.unchanged = Mock()
        market.save = Mock()
        market.view = lambda plan: {'status':'prepared','need':plan['need'],
                                   'unavailable_sources':plan.get('unavailable_sources',[])}
        market.choose = Mock(side_effect=[({'id':'anthropic'},{'status':'selected'}),
                                         ({'id':'github:public/catalog'},{'status':'selected'})])
        market.prepare_plugin = Mock(side_effect=failure or [
            {'status':'setup_required','unavailable_candidates':[{'name':'native','requirements':['commands']}]},None])
        arguments = {'kind':'plugin','need':'Review a local function without editing it'}
        if explicit:
            arguments['source']='anthropic'
        return market,arguments

    def test_completed_incompatibility_advances_market_without_need_rewrite(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            market,args = self.prepare_market(temporary)
            result=market.prepare(args)
            self.assertEqual(result['status'],'prepared')
            self.assertEqual([c.args[1] for c in market.prepare_plugin.call_args_list],
                             ['anthropic','github:public/catalog'])
            self.assertTrue(all(c.args[0]['need']==args['need'] for c in market.prepare_plugin.call_args_list))
            self.assertEqual(market._plugin_probe_limit,8)
            self.assertEqual(result['unavailable_sources'][0]['source'],'anthropic')
            self.assertEqual(market.save.call_count,1)

    def test_explicit_source_does_not_silently_probe_another(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            market,args = self.prepare_market(temporary,explicit=True)
            result=market.prepare(args)
            self.assertEqual(result['status'],'setup_required')
            self.assertEqual(market.prepare_plugin.call_count,1)
            market.choose.assert_not_called()
            market.save.assert_not_called()

    def test_provider_error_and_outage_never_advance_to_another_source(self):
        import tempfile
        for failure in [RuntimeError('provider_timeout'),RuntimeError('source read failed')]:
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as temporary:
                market,args = self.prepare_market(temporary,failure=[failure])
                with self.assertRaises(RuntimeError):market.prepare(args)
                self.assertEqual(market.prepare_plugin.call_count,1)
                self.assertEqual(market.choose.call_count,1)
                market.save.assert_not_called()

    def test_catalog_read_rejection_can_use_an_independent_registered_source(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            market,args=self.prepare_market(temporary,failure=[
                {'status':'catalog_unavailable','reason':'public_catalog_rate_limited'},None])
            result=market.prepare(args)
            self.assertEqual(result['status'],'prepared')
            self.assertEqual(result['unavailable_sources'][0]['result']['reason'],'public_catalog_rate_limited')
            self.assertEqual(market.prepare_plugin.call_count,2)

    def test_same_call_ranking_keeps_all_candidates_including_zero_probability(self):
        class Error(RuntimeError):pass
        provider=Mock(return_value=SimpleNamespace(choice='b',confidence=.6,probabilities={'a':0,'b':.6,'c':.3,'none':.1}))
        runtime=SimpleNamespace(_jev_cli=provider,BackpackError=Error,MAX_PROVIDER_ATTEMPTS=1,ROUTING_BUDGET_SECONDS=30,
                                _typesafe_http=provider)
        candidates=[SimpleNamespace(name=n,description=n) for n in 'abc']
        result=route(runtime,'review a file',candidates,{'provider':'jev-cli','minimum_confidence':.1},'plugin')
        self.assertEqual(result['inspection_order'],['b','c','a'])
        self.assertEqual(provider.call_count,1)
        provider.return_value=SimpleNamespace(choice='none',confidence=.95,probabilities={'none':.95})
        self.assertNotIn('inspection_order',route(runtime,'review a file',candidates,{'provider':'jev-cli','minimum_confidence':.1},'plugin'))

    def test_rejected_package_reuses_complete_rank_without_resending_catalog(self):
        market=object.__new__(Market)
        market.sources=SimpleNamespace(SourceError=RuntimeError)
        rows=[{'name':n,'description':n} for n in ['first','later','last']]
        market.manager=SimpleNamespace(plugins=SimpleNamespace(sources=SimpleNamespace(browse=lambda source:{'items':rows})))
        market.plugin_catalog=market.manager.plugins.sources.browse
        market.choose=Mock(return_value=(rows[0],{'status':'selected','_ranked_rows':rows[1:]}))
        market.prepare_plugin_candidate=Mock(side_effect=[{'status':'setup_required','name':'first'},None])
        plan={'need':'Review this file','routing':[]}
        self.assertIsNone(market.prepare_plugin(plan,'github:public/catalog'))
        self.assertEqual(market.choose.call_count,1)
        self.assertEqual([c.args[-1]['name'] for c in market.prepare_plugin_candidate.call_args_list],['first','later'])
        self.assertNotIn('_ranked_rows',str(plan['routing']))


if __name__ == '__main__':unittest.main()
