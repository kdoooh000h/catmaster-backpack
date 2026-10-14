import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adapters/codex'))
import market_python as python
from market_connect import service_target


class PythonMCPTests(unittest.TestCase):
    def library(self, **changes):
        package = {'registryType': 'pypi', 'identifier': 'demo-mcp', 'version': '1.2.3',
                   'transport': {'type': 'stdio'}, **changes}
        return SimpleNamespace(items={'receipt': {'server': {'packages': [package]}}},
            options=lambda receipt: {'options': [], 'name': 'publisher/demo', 'title': 'Demo',
                                     'description': 'Local storage', 'version': '1.2.3'})

    def test_only_bounded_pinned_supported_packages_get_options(self):
        with patch.object(python.shutil, 'which', return_value='/uv'):
            self.assertEqual(len(python.options(self.library(), 'receipt')['options']), 1)
            for changes in ({'version': 'latest'}, {'identifier': 'https://example.com/x.whl'},
                            {'runtimeArguments': [{'value': '--index-url=bad'}]},
                            {'packageArguments': [{'value': '--from=other'}]}):
                self.assertEqual(python.options(self.library(**changes), 'receipt')['options'], [])
        with patch.object(python.shutil, 'which', return_value=None):
            self.assertEqual(python.options(self.library(), 'receipt')['options'], [])

    def test_required_secret_never_becomes_an_automatic_setup_default(self):
        library = self.library(environmentVariables=[{'name': 'KEY', 'isSecret': True,
            'isRequired': True, 'default': 'published-secret'}])
        with patch.object(python.shutil, 'which', return_value='/uv'):
            option = python.options(library, 'receipt')['options'][0]
            self.assertEqual(option['fields'][0]['default'], '')
            with self.assertRaisesRegex(ValueError, 'configuration_required'):
                python.configuration(library, 'receipt', option, Path('/tmp/test'), 'test')

    def test_declared_extras_and_entrypoint_are_normalized_not_executed_as_flags(self):
        package = {'identifier': 'demo-mcp', 'runtimeHint': 'uvx', 'packageArguments': [
            {'type': 'named', 'name': '--from', 'value': 'demo-mcp[server]'},
            {'type': 'positional', 'value': 'demo-server'}]}
        self.assertEqual(python.package_launch(package), ('server', 'demo-server'))
        package['packageArguments'][0]['value'] = 'other[server]'
        with self.assertRaises(ValueError): python.package_launch(package)

    def test_explicit_entrypoint_must_belong_to_selected_distribution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dist = root/'venv/lib/python3.14/site-packages/demo_mcp-1.2.3.dist-info'
            dist.mkdir(parents=True)
            (dist/'METADATA').write_text('Name: demo-mcp\nVersion: 1.2.3\n')
            (dist/'entry_points.txt').write_text('[console_scripts]\ndemo = demo:cli\ndemo-server = demo:server\n')
            entry = root/'venv/bin/demo-server';entry.parent.mkdir();entry.write_text('entry')
            self.assertEqual(python.entrypoint(root, 'demo-mcp', '1.2.3', 'demo-server'), entry)
            with self.assertRaisesRegex(ValueError, 'unique_entrypoint'):
                python.entrypoint(root, 'demo-mcp', '1.2.3', 'another-package')

    def config(self, data):
        library = self.library()
        with patch.object(python.shutil, 'which', return_value='/uv'):
            option = python.options(library, 'receipt')['options'][0]
            return python.configuration(library, 'receipt', option, data, 'connection')['configuration']

    def test_identity_survives_release_path_but_execution_does_not_accept_foreign_runner(self):
        config = self.config(Path('/tmp/test'))
        self.assertEqual(service_target(config), ['pypi', 'demo-mcp'])
        config['command'][3] = '/older/release/market_python.py'
        self.assertEqual(service_target(config), ['pypi', 'demo-mcp'])
        self.assertIsNone(python.target(config))

    def test_changed_environment_rejected_before_running_package(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dist = root/'venv/lib/python3.14/site-packages/demo_mcp-1.2.3.dist-info'
            dist.mkdir(parents=True)
            (dist/'METADATA').write_text('Name: demo-mcp\nVersion: 1.2.3\n')
            (dist/'entry_points.txt').write_text('[console_scripts]\ndemo = demo:main\n')
            entry = root/'venv/bin/demo'; entry.parent.mkdir(); entry.write_text('original')
            (root/'ready.json').write_text(json.dumps({'name':'demo-mcp','version':'1.2.3',
                'entrypoint':'demo','digest':python.tree_digest(root/'venv')}))
            self.assertEqual(python.verify(root, 'demo-mcp', '1.2.3'), entry)
            entry.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'environment_changed'):
                python.verify(root, 'demo-mcp', '1.2.3')

    def test_install_uses_isolated_home_wheels_and_no_python_downloads(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp).resolve()
            market = SimpleNamespace(data=data, descriptor='connection', folder=data,
                gateway=SimpleNamespace(public_access=SimpleNamespace(safe=lambda p:p)),
                runtime=SimpleNamespace(_atomic_json=lambda p,v:p.write_text(json.dumps(v))), current=Mock())
            config = self.config(data)
            with patch.object(python.subprocess, 'Popen') as launch, patch.object(python.shutil, 'which', return_value='/uv'), patch.object(
                    python, 'entrypoint', return_value=Path('/fake/demo')), patch.object(python, 'tree_digest', return_value='digest'), patch.dict(
                    os.environ, {'SECRET_KEY': 'do-not-copy'}):
                launch.return_value.wait.return_value = 0
                self.assertTrue(python.install(market, {'configuration':config}, {'id':'plan'}))
            self.assertEqual(launch.call_count, 2)
            call = launch.call_args
            self.assertIn('--only-binary', call.args[0])
            self.assertNotIn('--no-build', call.args[0])  # uv rejects combining this with --only-binary
            self.assertIn('--no-python-downloads', call.args[0])
            self.assertIn('demo-mcp==1.2.3', call.args[0])
            self.assertNotIn('SECRET_KEY', call.kwargs['env'])
            self.assertTrue(Path(call.kwargs['env']['HOME']).is_relative_to(data))
            self.assertNotIn('--system', call.args[0])

    def test_interrupted_install_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp).resolve();config = self.config(data)
            python.target(config)[2].mkdir(parents=True)
            market = SimpleNamespace(data=data, descriptor='connection',
                gateway=SimpleNamespace(public_access=SimpleNamespace(safe=lambda p:p)))
            with patch.object(python.subprocess, 'Popen') as launch, self.assertRaisesRegex(ValueError, 'setup_interrupted'):
                python.install(market, {'configuration':config}, {'id':'plan'})
            launch.assert_not_called()


if __name__ == '__main__': unittest.main()
