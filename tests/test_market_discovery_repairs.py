import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adapters/codex'))
import market_registry as registry
from market_routing import route


def entry(name):
    return {'server': {'name': name, 'version': '1', 'description': name},
            '_meta': {'io.modelcontextprotocol.registry/official': {'status': 'active'}}}


class DiscoveryRepairs(unittest.TestCase):
    def test_stage_prompt_keeps_abstention_and_exact_candidates(self):
        class Error(RuntimeError): pass
        provider = Mock(return_value=SimpleNamespace(choice='none', confidence=.9))
        runtime = SimpleNamespace(_jev_cli=provider, _typesafe_http=provider, BackpackError=Error,
                                  MAX_PROVIDER_ATTEMPTS=1, ROUTING_BUDGET_SECONDS=30)
        rows = [SimpleNamespace(name='a', description='Code review directory')]
        cfg = {'provider': 'jev-cli', 'minimum_confidence': .1}
        answer = route(runtime, 'review a file', rows, cfg, 'directory')
        self.assertEqual(answer['status'], 'none')
        self.assertIn('indexes, not executable tools', provider.call_args.args[1])
        self.assertEqual(set(provider.call_args.args[3]), {'a', 'none'})
        provider.return_value = SimpleNamespace(choice='a', confidence=.05)
        self.assertEqual(route(runtime, 'review a file', rows, cfg, 'directory')['status'], 'uncertain')
        route(runtime, 'review a file', rows, cfg, 'plugin')
        self.assertIn('portable Skill guidance', provider.call_args.args[1])

    def test_union_all_pages_and_dedup_does_not_drop_later_match(self):
        def fetch(q, cursor, deadline):
            return {'servers': [entry(q + ('-later' if cursor else ''))],
                    'metadata': {} if cursor else {'nextCursor': 'next'}}
        library = SimpleNamespace(items={})
        with patch.object(registry, 'fetch', side_effect=fetch):
            result = registry.browse(library, 'clock timezone clock')
        self.assertEqual(result['search_terms'], ['clock', 'timezone'])
        self.assertEqual({r['name'] for r in result['items']}, {'clock', 'clock-later', 'timezone', 'timezone-later'})
        self.assertIsNone(result['next_cursor'])

    def test_incomplete_or_cyclic_pages_never_select_first_page(self):
        page = {'servers': [entry('a')], 'metadata': {'nextCursor': 'again'}}
        with patch.object(registry, 'fetch', return_value=page), self.assertRaisesRegex(ValueError, 'invalid_pagination'):
            registry.browse(SimpleNamespace(items={}), 'a')
        with patch.object(registry, 'pages', return_value=[entry(str(i)) for i in range(193)]):
            result = registry.browse(SimpleNamespace(items={}), 'a')
        self.assertEqual(result['items'], [])
        self.assertEqual(result['candidate_count'], 193)

    def test_query_bound_and_network_failures_are_explicit(self):
        for search in ('', 'one two three four five'):
            with patch.object(registry, 'fetch') as fetch:
                self.assertEqual(registry.browse(SimpleNamespace(items={}), search)['next_cursor'], 'search_required')
                fetch.assert_not_called()
        with patch.object(registry.shutil, 'which', return_value=None), patch.object(registry.urllib.request, 'build_opener') as opener:
            opener.return_value.open.side_effect = TimeoutError()
            with self.assertRaisesRegex(ValueError, 'registry_read_timeout_or_network_error'):
                registry.fetch('clock', '', registry.time.monotonic() + 80)
            self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'], 45)

    def test_curl_retains_https_identity_size_and_no_redirect_boundary(self):
        response = SimpleNamespace(returncode=0, stdout=b'{"servers": []}\n200')
        with patch.object(registry.subprocess, 'run', return_value=response) as run:
            self.assertEqual(registry.curl_fetch('/usr/bin/curl', registry.ROOT, 35), {'servers': []})
            argv = run.call_args.args[0]
            self.assertEqual(argv[:2], ['/usr/bin/curl', '-q'])
            self.assertIn('=https', argv)
            self.assertNotIn('--location', argv)
            self.assertNotIn('--insecure', argv)
        for code, status, reason in [(0, b'302', 'redirect'), (22, b'429', 'rate_limited'), (63, b'200', 'too_large'), (28, b'000', 'network_error')]:
            with patch.object(registry.subprocess, 'run', return_value=SimpleNamespace(returncode=code, stdout=b'{}\n'+status)):
                with self.assertRaisesRegex(ValueError, reason):
                    registry.curl_fetch('/usr/bin/curl', registry.ROOT, 35)
        with patch.object(registry, '_fetch', side_effect=ValueError('registry_read_timeout_or_network_error')) as fetch:
            with self.assertRaises(ValueError): registry.fetch('clock', '', registry.time.monotonic()+80)
            self.assertEqual(fetch.call_count, 1)

    def test_conflicting_versions_in_one_search_abort(self):
        a, b = entry('a'), entry('a')
        b['server']['description'] = 'changed'
        with patch.object(registry, 'pages', return_value=[a,b]), self.assertRaisesRegex(ValueError, 'changed_during_search'):
            registry.browse(SimpleNamespace(items={}), 'a')

    def test_latest_version_conflict_never_creates_complete_cache(self):
        a,b=entry('alpha'),entry('alpha');b['server']['version']='2'
        with patch.object(registry,'pages',side_effect=[[a],[b]]), \
                patch('market_registry_cache.read',return_value=None), \
                patch('market_registry_cache.write') as save, \
                self.assertRaisesRegex(ValueError,'changed_during_search'):
            registry.browse(SimpleNamespace(items={}), 'alpha beta', Path('/unused'))
        save.assert_not_called()

    def test_read_outage_fallback_keeps_cache_provenance(self):
        a=entry('graph');a['_meta']['io.modelcontextprotocol.registry/official']['isLatest']=True
        snapshot={'rows':[a],'cache_age_seconds':600,'checked_at':1,'coverage':'complete_at_snapshot','metadata_refreshed_at':None}
        refreshed={**snapshot,'metadata_refreshed_at':601,'exclusions':[]}
        with patch.object(registry,'pages',side_effect=ValueError('registry_read_timeout_or_network_error')), \
                patch('market_registry_cache.read',return_value=snapshot), \
                patch('market_registry_cache.refresh',return_value=refreshed) as refresh:
            result=registry.browse(SimpleNamespace(items={}), 'graph', Path('/unused'))
        self.assertEqual(result['catalog']['mode'],'query_cache_live_details')
        self.assertEqual(result['catalog']['checked_at'],1)
        self.assertEqual(result['catalog']['coverage'],'complete_at_snapshot')
        self.assertTrue(refresh.call_args.kwargs['network_outage'])
        self.assertEqual(len(result['items']),1)

    def test_broad_search_stops_after_exceeding_bound_without_selecting_prefix(self):
        count = 0
        def fetch(query, cursor, deadline):
            nonlocal count
            count += 1
            return {'servers': [entry(str(count * 100 + i)) for i in range(100)],
                    'metadata': {'nextCursor': str(count)}}
        with patch.object(registry, 'fetch', side_effect=fetch):
            result = registry.browse(SimpleNamespace(items={}), 'broad')
        self.assertEqual(count, 2)
        self.assertEqual(result['items'], [])
        self.assertTrue(result['next_cursor'])


if __name__ == '__main__': unittest.main()
