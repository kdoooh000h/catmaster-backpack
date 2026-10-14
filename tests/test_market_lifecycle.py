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


if __name__ == '__main__': unittest.main()
