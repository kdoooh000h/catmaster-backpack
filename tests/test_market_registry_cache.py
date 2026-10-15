import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.parse

ENTRY = Path(__file__).resolve().parents[1] / 'adapters/codex/market_registry_cache.py'
SPEC = importlib.util.spec_from_file_location('market_registry_cache', ENTRY)
cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cache)


def row(name='com.example/search-a', version='1', status='active', latest=True):
    return {'server': {'name': name, 'version': version},
            '_meta': {cache.OFFICIAL: {'status': status, 'isLatest': latest}}}


class RegistryCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'cache'
        self.now = time.time()

    def save(self, rows=None, age=0, terms=('search',)):
        return cache.write(self.root, terms, [row()] if rows is None else rows,
                           self.now - age, complete=True)

    def artifact(self, terms=('search',)):
        return self.root / cache._filename(cache.normalize_terms(terms))

    def corrupt(self, change):
        path = self.artifact()
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value))

    def test_private_exact_query_round_trip_and_fresh_reuse(self):
        rows = [row(), row('com.example/tools')]
        self.save(rows, terms=['Tools', 'Search', 'search'])
        snapshot = cache.read(self.root, ['search', 'TOOLS'], self.now)
        fetch = Mock()
        result = cache.refresh(snapshot, fetch, now=self.now + 300)
        fetch.assert_not_called()
        self.assertEqual(result['rows'], rows)
        self.assertEqual(result['cache_age_seconds'], 300)
        self.assertEqual(result['coverage'], 'complete_at_snapshot')
        self.assertIsNone(result['metadata_refreshed_at'])
        self.assertEqual(result['source'], cache.SOURCE)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.artifact(['search', 'tools']).stat().st_mode & 0o777, 0o600)

    def test_missing_and_different_terms_do_not_mix_snapshots(self):
        self.assertIsNone(cache.read(self.root, ['search'], self.now))
        self.save()
        self.assertIsNone(cache.read(self.root, ['search', 'tools'], self.now))
        self.corrupt(lambda v: v.update(search_terms=['tools']))
        with self.assertRaisesRegex(ValueError, 'query_mismatch'):
            cache.read(self.root, ['search'], self.now)

    def test_partial_sets_and_wrong_source_rejected_without_overwrite(self):
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            cache.write(self.root, ['search'], [row()], self.now, complete=False)
        self.save()
        self.corrupt(lambda v: v.update(complete=False))
        original = self.artifact().read_bytes()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.save()
        self.assertEqual(self.artifact().read_bytes(), original)
        self.corrupt(lambda v: v.update(complete=True, source='https://mirror.invalid'))
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            cache.read(self.root, ['search'], self.now)

    def test_expiry_and_future_timestamp_rejected(self):
        with patch.object(cache.time, 'time', return_value=self.now):
            snapshot = self.save(age=cache.MAX_AGE)
        self.assertIsNotNone(cache.read(self.root, ['search'], self.now))
        with self.assertRaisesRegex(ValueError, 'expired'):
            cache.read(self.root, ['search'], self.now + 1)
        with self.assertRaisesRegex(ValueError, 'expired'):
            cache.refresh(snapshot, Mock(), now=self.now + 1, network_outage=True)
        self.save()  # Valid expired snapshots can be replaced by a complete search.
        with self.assertRaisesRegex(ValueError, 'invalid_time'):
            cache.read(self.root, ['search'], self.now - 1)

    def test_symlink_and_unsafe_artifacts_never_overwritten(self):
        self.root.mkdir(mode=0o700)
        target = Path(self.temporary.name) / 'untouched'
        target.write_text('keep')
        self.artifact().symlink_to(target)
        for operation in (lambda: self.save(), lambda: cache.read(self.root, ['search'], self.now)):
            with self.assertRaises((OSError, ValueError)):
                operation()
        self.assertEqual(target.read_text(), 'keep')
        self.assertTrue(self.artifact().is_symlink())
        self.artifact().unlink()
        self.save()
        self.artifact().chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'unsafe_file'):
            self.save()
        self.artifact().chmod(0o600)
        self.artifact().write_text('invalid JSON')
        with self.assertRaisesRegex(ValueError, 'invalid_json'):
            self.save()
        self.assertEqual(self.artifact().read_text(), 'invalid JSON')

    def test_symlink_directory_and_nonregular_file_rejected(self):
        directory = Path(self.temporary.name) / 'actual'
        directory.mkdir(mode=0o700)
        self.root.symlink_to(directory, target_is_directory=True)
        with self.assertRaises((OSError, ValueError)):
            self.save()
        self.root.unlink()
        self.root.mkdir(mode=0o700)
        os.mkfifo(self.artifact(), 0o600)
        with self.assertRaisesRegex(ValueError, 'unsafe_file'):
            cache.read(self.root, ['search'], self.now)

    def test_size_limit_and_unsafe_owner_rejected(self):
        self.save()
        with self.artifact().open('wb') as stream:
            stream.truncate(cache.MAX_BYTES + 1)
        with self.assertRaisesRegex(ValueError, 'unsafe_file'):
            cache.read(self.root, ['search'], self.now)
        with patch.object(cache.os, 'getuid', return_value=os.getuid() + 1):
            with self.assertRaisesRegex(ValueError, 'unsafe_directory'):
                cache.read(self.root, ['search'], self.now)

    def test_older_cache_requires_confirmed_search_read_outage(self):
        snapshot = self.save(age=301)
        fetch = Mock()
        with self.assertRaisesRegex(ValueError, 'requires_read_outage'):
            cache.refresh(snapshot, fetch, now=self.now)
        fetch.assert_not_called()

    def test_available_queries_discloses_only_valid_canonical_unexpired_labels(self):
        self.assertEqual(cache.available_queries(self.root), [])
        self.save()
        self.save([], terms=['empty'])
        self.save([row('com.example/expired')], terms=['expired'])
        expired = self.artifact(['expired'])
        value = json.loads(expired.read_text())
        value['checked_at'] = self.now - cache.MAX_AGE - 10
        expired.write_text(json.dumps(value))
        # A valid snapshot stored under a different query hash discloses no label.
        self.artifact(['wrong-name']).write_text(self.artifact().read_text())
        self.artifact(['wrong-name']).chmod(0o600)
        result = cache.available_queries(self.root)
        self.assertEqual(result, [
            {'search_terms': ['empty'], 'checked_at': self.now},
            {'search_terms': ['search'], 'checked_at': self.now}])
        self.assertTrue(all(set(hint) == {'search_terms', 'checked_at'} for hint in result))
        self.assertEqual(len(cache.available_queries(self.root, max_queries=1)), 1)
        with self.assertRaises(ValueError):
            cache.available_queries(self.root, max_queries=33)

    def test_query_hints_skip_unsafe_files_before_reading_or_parsing(self):
        self.root.mkdir(mode=0o700)
        fifo = self.artifact(['fifo'])
        os.mkfifo(fifo, 0o600)
        target = Path(self.temporary.name) / 'outside'
        target.write_text('must not read')
        self.artifact(['symlink']).symlink_to(target)
        readable = self.artifact(['readable'])
        readable.write_text('must not read')
        readable.chmod(0o644)
        unowned = self.artifact(['unowned'])
        unowned.write_text('must not read')
        unowned.chmod(0o600)
        unowned_inode = unowned.stat().st_ino
        original_fstat = os.fstat

        def fstat(fd):
            info = original_fstat(fd)
            if info.st_ino == unowned_inode:
                return SimpleNamespace(st_uid=os.getuid() + 1, st_mode=info.st_mode,
                                       st_nlink=info.st_nlink, st_size=info.st_size)
            return info

        started = time.monotonic()
        with patch.object(cache.os, 'fstat', side_effect=fstat), \
                patch.object(cache.os, 'fdopen', side_effect=AssertionError('unsafe read')), \
                patch.object(cache.json, 'loads', side_effect=AssertionError('unsafe parse')):
            self.assertEqual(cache.available_queries(self.root), [])
        self.assertLess(time.monotonic() - started, 0.3)

    def test_all_candidates_refreshed_without_resetting_search_time(self):
        rows = [row('com.example/search-' + str(i)) for i in range(12)]
        snapshot = self.save(rows, age=301)
        calls, active, peak = [], 0, 0
        lock = threading.Lock()

        def fetch(url, timeout):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                calls.append((url, timeout))
            time.sleep(0.005)
            name = urllib.parse.unquote(url.split('/servers/')[1].split('/versions/')[0])
            with lock:
                active -= 1
            return row(name, version='2', status='deleted' if name.endswith('-5') else 'active')

        result = cache.refresh(snapshot, fetch, now=self.now, network_outage=True)
        self.assertEqual(len(calls), 12)
        self.assertLessEqual(peak, 4)
        self.assertTrue(all(url.startswith(cache.SOURCE + '/') and '/versions/latest?' in url
                            and 0 < timeout <= 12 for url, timeout in calls))
        self.assertTrue(all('%2F' in url for url, _ in calls))
        self.assertEqual([r['server']['name'] for r in result['rows']],
                         [r['server']['name'] for r in rows])
        self.assertTrue(all(r['server']['version'] == '2' for r in result['rows']))
        self.assertEqual(result['checked_at'], snapshot['checked_at'])
        self.assertEqual(result['coverage'], 'complete_at_snapshot')
        self.assertEqual(result['exclusions'], [{'name': 'com.example/search-5', 'status': 'deleted'}])
        self.assertGreaterEqual(result['metadata_refreshed_at'], self.now)
        self.assertEqual(cache.read(self.root, ['search'], self.now)['rows'], rows)

    def test_larger_set_declines_explicitly_without_truncating(self):
        snapshot = self.save([row('com.example/search-' + str(i)) for i in range(13)], age=301)
        fetch = Mock()
        with self.assertRaisesRegex(ValueError, 'fallback_too_broad'):
            cache.refresh(snapshot, fetch, now=self.now, network_outage=True)
        fetch.assert_not_called()
        self.assertEqual(len(cache.read(self.root, ['search'], self.now)['rows']), 13)

    def test_fresh_larger_snapshot_does_not_need_bounded_detail_refresh(self):
        snapshot = self.save([row('com.example/search-' + str(i)) for i in range(13)])
        fetch = Mock()
        result = cache.refresh(snapshot, fetch, now=self.now)
        fetch.assert_not_called()
        self.assertEqual(len(result['rows']), 13)

    def test_old_empty_snapshot_does_not_claim_live_metadata_refresh(self):
        snapshot = self.save([], age=301)
        fetch = Mock()
        result = cache.refresh(snapshot, fetch, now=self.now, network_outage=True)
        fetch.assert_not_called()
        self.assertEqual(result['rows'], [])
        self.assertEqual(result['checked_at'], snapshot['checked_at'])
        self.assertEqual(result['coverage'], 'complete_at_snapshot')
        self.assertIsNone(result['metadata_refreshed_at'])

    def test_failed_one_changed_name_or_invalid_latest_returns_no_subset(self):
        snapshot = self.save([row(), row('com.example/search-b')], age=301)
        original = copy.deepcopy(snapshot)
        for failure in ('network', 'name', 'status', 'latest'):
            def fetch(url, timeout):
                if 'search-b' not in url:
                    return row(version='2')
                if failure == 'network':
                    raise ValueError('detail_unavailable')
                return row('com.example/search-changed' if failure == 'name' else 'com.example/search-b',
                           status='unknown' if failure == 'status' else 'active',
                           latest=failure != 'latest')
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                cache.refresh(snapshot, fetch, now=self.now, network_outage=True)
            self.assertEqual(snapshot, original)

    def test_global_deadline_returns_without_waiting_for_uncooperative_callback(self):
        snapshot = self.save(age=301)
        finished = threading.Event()

        def fetch(url, timeout):
            finished.wait(1)
            return row()

        try:
            with patch.object(cache, 'GLOBAL_TIMEOUT', 0.02):
                started = time.monotonic()
                with self.assertRaisesRegex(ValueError, 'refresh_timeout'):
                    cache.refresh(snapshot, fetch, now=self.now, network_outage=True)
                self.assertLess(time.monotonic() - started, 0.3)
        finally:
            finished.set()

    def test_failure_does_not_wait_on_an_earlier_pending_future(self):
        snapshot = self.save([row(), row('com.example/search-b')], age=301)
        finished = threading.Event()

        def fetch(url, timeout):
            if 'search-b' in url:
                raise ValueError('detail_unavailable')
            finished.wait(1)
            return row()

        try:
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, 'detail_unavailable'):
                cache.refresh(snapshot, fetch, now=self.now, network_outage=True)
            self.assertLess(time.monotonic() - started, 0.3)
        finally:
            finished.set()


if __name__ == '__main__':
    unittest.main()
