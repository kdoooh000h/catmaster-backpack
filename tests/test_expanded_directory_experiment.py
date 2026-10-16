import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmarks/directory-depth'))
import expanded_experiment as E


class ExpandedDirectoryTests(unittest.TestCase):
    def bundle(self, root):
        root.mkdir()
        values = {'plan.json': {'input_sha256': {}, 'source_sha256': {}, 'executable': 'fake',
                    'timeout_seconds': 1, 'max_seconds': 5, 'max_calls': 8, 'max_known_tokens': 200},
                  'catalog.json': [{'id': 'wanted', 'description': 'Capability'}],
                  'nodes.json': {}, 'question.json': {'question': 'Original question', 'none': 'No match'},
                  'cases.json': [{'id': str(i), 'need': '原始需求', 'expected_ids': ['wanted'],
                                   'pending_ids': [], 'control': False} for i in range(2)]}
        for name, value in values.items():
            (root / name).write_text(json.dumps(value))
        return root

    def test_semantic_failures_remain_in_denominator(self):
        class Provider:
            def __init__(self, *args, **kwargs): self.calls = []
        wrong = {'status': 'none', 'traces': [{'pool': []}]}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(E, 'JevHierarchyProvider', Provider), patch.object(E.A, 'route', return_value=wrong), patch.object(E.C, 'route', return_value=wrong), contextlib.redirect_stdout(io.StringIO()):
                E.run(self.bundle(root / 'bundle'), root / 'live')
            result = json.loads((root / 'live/summary.json').read_text())
            self.assertEqual(result['stop'], 'completed')
            self.assertEqual(len(result['rows']), 4)
            self.assertFalse(any(r['omission_safe_pass'] for r in result['rows']))

    def test_unknown_transport_stops_without_retry(self):
        class Provider:
            def __init__(self, *args, **kwargs): self.calls = []
            def noul(self, spec, state):
                self.calls.append({'outcome': 'unknown_no_replay'})
                raise TimeoutError('unknown_no_replay')
        def route(*args):
            try: args[-1]('directory-0', {'questions': {}}, {'task': '原始需求'})
            except TimeoutError as error: return {'status': 'unavailable', 'reason': str(error), 'traces': []}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(E, 'JevHierarchyProvider', Provider), patch.object(E.A, 'route', side_effect=route), contextlib.redirect_stdout(io.StringIO()):
                E.run(self.bundle(root / 'bundle'), root / 'live')
            result = json.loads((root / 'live/summary.json').read_text())
            self.assertEqual(result['calls'], 1)
            self.assertEqual(result['stop'], 'budget_or_provider_failure')
            self.assertEqual(len(list((root / 'live').glob('*.pending.json'))), 1)
            self.assertEqual(len(list((root / 'live').glob('*.error.json'))), 1)
            self.assertEqual(len(list((root / 'live').glob('*.done.json'))), 0)

    def test_new_cases_and_no_capability_names_in_needs(self):
        folder = Path(E.__file__).parent
        cases = json.loads((folder / 'expanded_cases.json').read_text())['cases']
        old = json.loads((folder / 'large_public_cases.json').read_text())['cases']
        self.assertEqual(len(cases), 14)
        self.assertEqual(len({c['id'] for c in cases}), 14)
        self.assertFalse({c['need'] for c in cases}.intersection(c['need'] for c in old))
        for case in cases:
            self.assertTrue(all(key not in case['need'] for key in case['expected_ids'] + case['pending_ids']))


if __name__ == '__main__':
    unittest.main()
