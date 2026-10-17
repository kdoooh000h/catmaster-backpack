import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adapters/codex'))
import market_node as node
from market_connect import service_target


class NodeMCPTests(unittest.TestCase):
    def package(self, root):
        package = root/'node_modules/@example/demo'
        package.mkdir(parents=True)
        (package/'package.json').write_text(json.dumps({'name':'@example/demo','version':'1.2.3',
            'type':'module','bin':{'demo':'main.js'}}))
        (root/'package-lock.json').write_text(json.dumps({'packages':{
            'node_modules/@example/demo':{'version':'1.2.3','integrity':'test'}}}))
        (package/'main.js').write_text('if (import.meta.url === `file://${process.argv[1]}`) console.log("started");')
        return package

    @unittest.skipUnless(shutil.which('node'), 'Node runtime required')
    def test_real_bin_starts_main_guard_and_preserves_logical_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); package=self.package(root)
            bins=root/'node_modules/.bin'; bins.mkdir(); (bins/'demo').symlink_to('../@example/demo/main.js')
            original={'transport':'stdio','command':['npx','--yes','--ignore-scripts','--package=@example/demo@1.2.3','demo']}
            config=node.configuration(original, root)
            self.assertEqual(service_target(config), service_target(original))
            result=subprocess.run(config['command'], capture_output=True, text=True, timeout=5, check=True)
            self.assertEqual(result.stdout.strip(), 'started')
            config['command'][3]='/older/release/market_node.py'
            self.assertEqual(service_target(config), ['npm','@example/demo'])
            self.assertIsNone(node.target(config))

    def test_changed_package_or_unsafe_bin_fails_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); package=self.package(root); path=package/'package.json'
            original=json.loads(path.read_text())
            for changes in ({'version':'9.9.9'}, {'bin':{'demo':'../../outside.js'}},
                            {'bin':{'other':'main.js'}}, {'bin':{'demo':'/tmp/outside.js'}}):
                path.write_text(json.dumps({**original, **changes}))
                with self.assertRaises(ValueError): node.entrypoint(root,'@example/demo@1.2.3','demo')

    def test_unpinned_packages_and_runtime_flags_are_not_wrapped(self):
        for args in (['npx','--yes','--ignore-scripts','--package=demo@latest','demo'],
                     ['npx','--yes','--unsafe','--package=demo@1.2.3','demo']):
            with self.assertRaises(ValueError): node.configuration({'command':args},Path('/tmp/test'))


if __name__ == '__main__': unittest.main()
