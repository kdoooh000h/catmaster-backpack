import io
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adapters/codex'))
from market_connect import Market, extract_package
from market_packages import resolve
from market_routing import route


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        # Catalog persistence has separate boundary checks. These fixtures test
        # package progression with the supplied complete in-memory catalog.
        patcher = patch.object(Market, 'plugin_catalog', lambda market, source:
                               market.manager.plugins.sources.browse(source))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_known_setup_failure_can_advance_without_grants_or_need_rewrite(self):
        market=object.__new__(Market)
        market.sources=SimpleNamespace(SourceError=RuntimeError)
        market.manager=SimpleNamespace(plugins=SimpleNamespace(sources=SimpleNamespace(browse=lambda source:{
            'items':[{'name':'native','description':'Review code'},{'name':'portable','description':'Debug code'}]})))
        market.choose=Mock(side_effect=[({'name':'native'},{'status':'selected'}),
                                       ({'name':'portable'},{'status':'selected'})])
        market.prepare_plugin_candidate=Mock(side_effect=[{'status':'setup_required','name':'native','requirements':['agents']},None])
        plan={'need':'Review a local function','routing':[],'skills':[],'servers':[]}
        self.assertIsNone(market.prepare_plugin(plan,'anthropic'))
        self.assertEqual(market.choose.call_count,2)
        self.assertEqual(market.choose.call_args.args[0],plan['need'])
        self.assertEqual([r['name'] for r in market.choose.call_args.args[1]],['portable'])
        self.assertEqual(plan['unavailable_candidates'][0]['requirements'],['agents'])

    def test_none_does_not_retry_or_prepare_a_package(self):
        market=object.__new__(Market)
        market.sources=SimpleNamespace(SourceError=RuntimeError)
        market.manager=SimpleNamespace(plugins=SimpleNamespace(sources=SimpleNamespace(browse=lambda source:{
            'items':[{'name':'native','description':'Review code'}]})))
        market.choose=Mock(return_value=(None,{'status':'none'}));market.prepare_plugin_candidate=Mock()
        result=market.prepare_plugin({'need':'Review','routing':[]},'anthropic')
        self.assertEqual(result['status'],'none')
        market.prepare_plugin_candidate.assert_not_called()

    def test_ambiguous_metadata_can_inspect_all_alternatives_but_not_truncate(self):
        market=object.__new__(Market);market.sources=SimpleNamespace(SourceError=RuntimeError)
        rows=[{'name':'one','description':'Review'},{'name':'two','description':'Debug'}]
        market.manager=SimpleNamespace(plugins=SimpleNamespace(sources=SimpleNamespace(browse=lambda source:{'items':rows})))
        market.choose=Mock(return_value=(None,{'status':'none','confidence':.3,'_inspection_rows':rows}))
        market.prepare_plugin_candidate=Mock(side_effect=[{'status':'setup_required','name':'one'},None])
        plan={'need':'Find a bug','routing':[]}
        self.assertIsNone(market.prepare_plugin(plan,'anthropic'))
        self.assertEqual(market.prepare_plugin_candidate.call_count,2)
        self.assertEqual(market.choose.call_count,1)
        self.assertNotIn('_inspection_rows',plan['routing'][0])
        market._preview_remaining=1;market._preview_deadline=10**12
        market.prepare_plugin_candidate.reset_mock()
        market.choose.return_value=(None,{'status':'none','confidence':.3,'_inspection_rows':list(rows)})
        result=market.prepare_plugin_group({'need':'Find a bug','routing':[]},'anthropic',{},rows,[])
        self.assertEqual(result['status'],'none')
        market.prepare_plugin_candidate.assert_not_called()

    def test_unsafe_preparation_rejects_package_and_continues_without_installing(self):
        market=object.__new__(Market);market.sources=SimpleNamespace(SourceError=RuntimeError)
        rows=[{'name':'bad','description':'Review'},{'name':'safe','description':'Debug'}]
        market.manager=SimpleNamespace(plugins=SimpleNamespace(sources=SimpleNamespace(browse=lambda source:{'items':rows})))
        market.choose=Mock(side_effect=[(rows[0],{'status':'selected'}),(rows[1],{'status':'selected'})])
        market.prepare_plugin_candidate=Mock(side_effect=[ValueError('unsafe_market_archive'),None])
        plan={'need':'Find a bug','routing':[]}
        self.assertIsNone(market.prepare_plugin(plan,'anthropic'))
        self.assertEqual(plan['unavailable_candidates'][0]['requirements'],['package_rejected_unsafe_archive'])

    def test_unavailable_category_does_not_hide_a_usable_sibling(self):
        market=object.__new__(Market)
        market.sources=SimpleNamespace(SourceError=RuntimeError)
        rows=[{'name':category+str(i),'description':'Guidance','entry':{'category':category}}
              for category in ['productivity','development'] for i in range(50)]
        market.manager=SimpleNamespace(plugins=SimpleNamespace(sources=SimpleNamespace(browse=lambda source:{'items':rows})))
        from market_directory import directories, declared_topics
        market.task_directories=lambda candidates,kind: directories(candidates,{i:declared_topics(row) for i,row in enumerate(candidates)})
        selected={'status':'selected'}
        market.choose=Mock(side_effect=[({'id':'business'},dict(selected)),(rows[0],dict(selected)),
            (None,{'status':'none'}),({'id':'software'},dict(selected)),(rows[50],dict(selected))])
        market.prepare_plugin_candidate=Mock(side_effect=[{'status':'setup_required','name':rows[0]['name'],'requirements':['agents']},None])
        plan={'need':'Review a local function','routing':[]}
        self.assertIsNone(market.prepare_plugin(plan,'anthropic'))
        second_directories=market.choose.call_args_list[3].args[1]
        self.assertEqual([d['id'] for d in second_directories],['software'])
        self.assertEqual(plan['unavailable_candidates'][0]['name'],'productivity0')

    def sources(self):
        def safe(path, allow_empty=False):
            if not path and allow_empty: return path
            if not path or Path(path).is_absolute() or '..' in Path(path).parts: raise ValueError('unsafe')
            return path
        return SimpleNamespace(safe_path=safe, SHA=re.compile('[a-f0-9]{40}'), fetch=Mock(side_effect=[
            json.dumps({'full_name': 'acme/plugin', 'private': False, 'default_branch': 'main'}).encode(),
            json.dumps({'sha': 'a' * 40}).encode()]))

    def test_external_source_uses_exact_pin_and_package_path(self):
        sources = self.sources()
        repository = Mock(return_value='acme/plugin')
        result = resolve({'source': 'git-subdir', 'url': 'https://github.com/acme/plugin.git',
                          'sha': 'a' * 40, 'ref': 'deleted-branch', 'path': './plugins/tool'}, {},
                         sources, SimpleNamespace(repository=repository))
        self.assertEqual(result, ('acme/plugin', 'a' * 40, 'plugins/tool'))
        self.assertTrue(sources.fetch.call_args.args[0].endswith('/commits/' + 'a' * 40))

    def test_unsafe_or_changed_sources_never_download_archive(self):
        for location in ({'source': 'command', 'command': 'bad'},
                         {'source': 'github', 'repo': 'acme/plugin', 'sha': 'main'},
                         {'source': 'github', 'repo': 'acme/plugin', 'path': '../outside'}):
            with self.subTest(location=location), self.assertRaises(ValueError):
                resolve(location, {}, self.sources(), SimpleNamespace(repository=lambda value: 'acme/plugin'))
        sources = self.sources()
        with self.assertRaisesRegex(ValueError, 'commit_changed'):
            resolve({'source': 'github', 'repo': 'acme/plugin', 'sha': 'b' * 40}, {}, sources,
                    SimpleNamespace(repository=lambda value: 'acme/plugin'))
        for key in ('private', 'archived', 'disabled'):
            sources = self.sources()
            sources.fetch.side_effect = None
            sources.fetch.return_value = json.dumps({'full_name': 'acme/plugin', 'private': False, key: True}).encode()
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                resolve({'source': 'github', 'repo': 'acme/plugin'}, {}, sources,
                        SimpleNamespace(repository=lambda value: 'acme/plugin'))
            self.assertEqual(sources.fetch.call_count, 1)

    def test_root_archive_is_safe_and_preserves_real_files(self):
        content = io.BytesIO()
        with zipfile.ZipFile(content, 'w') as archive:
            archive.writestr('repo/.claude-plugin/plugin.json', '{"name":"demo"}')
            archive.writestr('repo/skills/demo/SKILL.md', 'real instructions')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'package'
            extract_package(content.getvalue(), '', root, self.sources().safe_path)
            self.assertEqual((root/'skills/demo/SKILL.md').read_text(), 'real instructions')

    def test_final_fit_remains_strict_and_can_reject_ranked_candidate(self):
        class Error(RuntimeError): pass
        provider = Mock(return_value=SimpleNamespace(choice='market-0', confidence=.44))
        runtime = SimpleNamespace(_jev_cli=provider, _typesafe_http=provider, BackpackError=Error,
                                  MAX_PROVIDER_ATTEMPTS=1, ROUTING_BUDGET_SECONDS=30)
        rows = [SimpleNamespace(name='market-0', description='Local time conversion')]
        cfg = {'provider': 'jev-cli', 'minimum_confidence': .1}
        self.assertEqual(route(runtime, 'convert time', rows, cfg, 'mcp-discovery')['status'], 'selected')
        self.assertEqual(route(runtime, 'convert time', rows, {**cfg, 'minimum_confidence': .7}, 'mcp-fit')['status'], 'uncertain')
        provider.return_value = SimpleNamespace(choice='none', confidence=.95)
        self.assertEqual(route(runtime, 'convert time', rows, {**cfg, 'minimum_confidence': .7}, 'mcp-fit')['status'], 'none')
        self.assertEqual(set(provider.call_args.args[3]), {'market-0', 'none'})
        self.assertEqual(provider.call_args.args[2], {'need':'convert time'})
        self.assertEqual(provider.call_args.args[3]['market-0'], 'Local time conversion')


if __name__ == '__main__': unittest.main()
