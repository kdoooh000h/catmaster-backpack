import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmarks/directory-depth'))
import resume_repair as R


class ResumeRepairTests(unittest.TestCase):
    def fixture(self, root):
        bundle, live = root / 'bundle', root / 'live'
        bundle.mkdir(); live.mkdir()
        nodes = {'n': {'depth': 0, 'children': ['leaf'], 'members': ['target'], 'description': 'All'},
                 'leaf': {'depth': 1, 'children': [], 'members': ['target'], 'description': 'Task'}}
        data = {'plan.json': {'source_sha256': {}, 'input_sha256': {}, 'executable': 'fake',
                    'max_seconds': 5, 'timeout_seconds': 1}, 'nodes.json': nodes, 'repaired-nodes.json': nodes,
                'catalog.json': [{'id': 'target', 'description': 'Task'}],
                'cases.json': [{'id': 'case', 'need': 'Task', 'expected_ids': ['target'], 'pending_ids': [], 'control': False}],
                'question.json': {'question': 'Select', 'none': 'None'}}
        for name, value in data.items(): (bundle / name).write_text(json.dumps(value))
        before = {'rows': [{'case': 'case', 'arm': 'adaptive', 'seconds': .01,
                           'result': {'reason': 'experiment_budget_stop'}}],
                  'stop': 'budget_or_provider_failure', 'calls': 1, 'known_tokens': 10, 'seconds': .01}
        (live / 'summary.json').write_text(json.dumps(before))
        approval = root / 'approval.json'
        approval.write_text(json.dumps({'plan_sha256': R.digest(bundle / 'plan.json'),
            'user_message': 'TEST FIXTURE approval, never live', 'additional_calls': 2, 'additional_known_tokens': 100}))
        spec = R.A.specification(nodes, ['leaf'])
        state = {'task': 'Task', 'rules': R.A.RULES}
        (live / 'r0--case--adaptive--directory-0.pending.json').write_text(json.dumps({'spec': spec, 'state': state}))
        (live / 'r0--case--adaptive--directory-0.done.json').write_text(json.dumps({
            'answer': {'answers': {'leaf': {'type': 'noul', 'noul': .9}}},
            'transport': [{'outcome': 'completed', 'input_tokens': 9, 'output_tokens': 1, 'seconds': .01}]}))
        return bundle, live, approval

    def test_completed_stage_not_resent_and_original_receipts_preserved(self):
        sent = []
        class Provider:
            def __init__(self, *args, **kwargs): self.calls = []
            def noul(self, spec, state):
                sent.append(spec)
                self.calls.append({'outcome': 'completed', 'input_tokens': 19, 'output_tokens': 1, 'seconds': .01})
                return {'answers': {'answer': {'type': 'choice', 'choice': 'target', 'confidence': .9}}}
        with tempfile.TemporaryDirectory() as folder:
            bundle, live, approval = self.fixture(Path(folder))
            original = {p.name: p.read_bytes() for p in live.iterdir()}
            with patch.object(R, 'ARMS', ['adaptive']), patch.object(R, 'JevHierarchyProvider', Provider), contextlib.redirect_stdout(io.StringIO()):
                R.resume(bundle, live, approval)
            summary = R.read(live / 'summary-resumed.json')
            self.assertEqual(summary['stop'], 'completed')
            self.assertEqual(summary['calls'], 2)
            self.assertEqual(summary['known_tokens'], 30)
            self.assertEqual(summary['extension']['replayed_locally_only'], 1)
            self.assertEqual(len(sent), 1)
            self.assertEqual(set(sent[0]['questions']), {'answer'})
            self.assertTrue(summary['rows'][0]['omission_safe_pass'])
            self.assertTrue(all((live / name).read_bytes() == value for name, value in original.items()))

    def test_unresolved_send_blocks_all_new_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle, live, approval = self.fixture(Path(folder))
            (live / 'unknown.pending.json').write_text('{}')
            with patch.object(R, 'JevHierarchyProvider') as provider:
                with self.assertRaisesRegex(ValueError, 'unreconciled_send_stop'):
                    R.resume(bundle, live, approval)
                provider.assert_not_called()


if __name__ == '__main__':
    unittest.main()
