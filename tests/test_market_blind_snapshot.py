"""Frozen public corpora preserve observation identity without touching setup."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

FOLDER = Path(__file__).resolve().parents[1] / 'benchmarks/market-blind'
sys.path.insert(0, str(FOLDER))
SPEC = importlib.util.spec_from_file_location('market_blind_snapshot', FOLDER / 'snapshot_gateway.py')
snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)


class SnapshotTests(unittest.TestCase):
    def test_complete_snapshot_is_read_once_and_original_time_is_retained(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            root = Path(temporary)
            read = Mock(return_value={'checked_at':123,'items':[{'name':'public-capability'}]})
            first = snapshot.freeze(root,'plugin:public',read)
            first['items'].clear()
            second = snapshot.freeze(root,'plugin:public',read)
            self.assertEqual(second,{'checked_at':123,'items':[{'name':'public-capability'}]})
            read.assert_called_once_with()
            for path in root.glob('*'):
                self.assertEqual(path.stat().st_mode & 0o777,0o600)

    def test_failed_or_partial_read_does_not_publish_a_successful_corpus(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            root=Path(temporary)
            with self.assertRaisesRegex(ValueError,'read_failed'):
                snapshot.freeze(root,'registry-query:time',Mock(side_effect=ValueError('read_failed')))
            self.assertEqual(list(root.glob('*.json')),[])

    def test_replaced_snapshot_symlink_is_rejected_without_reading_target(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            root=Path(temporary)
            snapshot.freeze(root,'plugin:public',lambda:{'items':[]})
            path=next(root.glob('*.json'));outside=root/'other';outside.write_text('untrusted')
            path.unlink();path.symlink_to(outside)
            read=Mock()
            with self.assertRaisesRegex(ValueError,'benchmark_unsafe_snapshot_path'):
                snapshot.freeze(root,'plugin:public',read)
            read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
