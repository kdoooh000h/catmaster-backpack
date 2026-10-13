"""Real local SQLite and file-policy checks; no external/model calls."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/catmaster_backpack'))
import capability_usage as usage

A, B, C = ('cap_' + char * 20 for char in 'abc')
NOW = 1_800_000_000
DAY = 86400


class CapabilityUsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = self.root / 'store'
        self.store.mkdir(mode=0o700)

    def tearDown(self):
        self.temp.cleanup()

    def record(self, identifier=A, receipt='receipt-one', kind='tool', **kwargs):
        options = {'completed': True, 'now': NOW}
        options.update(kwargs)
        return usage.record_use(self.store, identifier, kind, receipt, **options)

    def frequent(self, eligible=(A, B, C), **kwargs):
        options = {'now': NOW}
        options.update(kwargs)
        return usage.frequent_ids(self.store, eligible, **options)

    def test_read_missing_store_and_files_does_not_create_anything(self):
        missing = self.root / 'missing'
        self.assertEqual(usage.direct_ids(missing, (A,)), [])
        self.assertEqual(usage.frequent_ids(missing, (A,)), [])
        self.assertFalse(missing.exists())
        self.assertEqual(self.frequent(), [])
        self.assertEqual(usage.direct_ids(self.store, (A,)), [])
        self.assertEqual(list(self.store.iterdir()), [])

    def test_completed_receipt_is_idempotent_durable_and_private(self):
        raw = 'receipt-with-sensitive-context-that-must-not-be-persisted'
        self.assertEqual(self.record(receipt=raw), {'status': 'recorded', 'counted': True})
        self.assertEqual(self.record(receipt=raw, now=NOW + DAY), {'status': 'duplicate', 'counted': False})
        self.record(receipt='receipt-two')
        self.assertEqual(self.frequent(), [{'id': A, 'uses': 2, 'last_used': NOW, 'kind': 'tool'}])
        path = self.store / usage.USAGE_FILE
        with sqlite3.connect(path) as db:
            rows = db.execute('SELECT * FROM completed_uses ORDER BY receipt_hash').fetchall()
        self.assertEqual(len(rows), 2)
        self.assertIn((hashlib.sha256(raw.encode()).hexdigest(), A, 'tool', NOW), rows)
        self.assertNotIn(raw.encode(), path.read_bytes())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.store / '.capability-usage.lock').stat().st_mode), 0o600)

    def test_same_receipt_other_capability_or_kind_conflicts(self):
        self.record()
        with self.assertRaisesRegex(ValueError, 'usage_receipt_conflict'):
            self.record(identifier=B)
        with self.assertRaisesRegex(ValueError, 'usage_receipt_conflict'):
            self.record(kind='resource')
        self.assertEqual(self.frequent(min_uses=1)[0]['uses'], 1)

    def test_parallel_receipt_replays_count_once(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.record(), range(12)))
        self.assertEqual(sum(row['counted'] for row in results), 1)
        self.assertEqual(self.frequent(min_uses=1)[0]['uses'], 1)

    def test_noncompletion_failure_uncertainty_and_selection_never_count(self):
        for kind in ('tool', 'resource', 'skill', 'command'):
            for event in ('failed', 'unknown', 'uncertain', 'acquire', 'acquired', 'selection',
                          'selected', 'guidance_delivered', 'authorization_required', 'denied'):
                with self.subTest(kind=kind, event=event):
                    self.assertEqual(self.record(kind=kind, event=event)['status'], 'ignored')
            self.assertEqual(self.record(kind=kind, completed=False)['status'], 'ignored')
        self.assertEqual(list(self.store.iterdir()), [])

    def test_skill_command_only_reported_application_counts(self):
        for identifier, kind in ((A, 'skill'), (B, 'command')):
            self.assertEqual(self.record(identifier, kind=kind)['status'], 'ignored')
            self.assertEqual(self.record(identifier, kind=kind, event='applied', completed=False)['status'], 'ignored')
            self.record(identifier, kind + '-one', kind, event='applied')
            self.record(identifier, kind + '-two', kind, event='application_reported')
        self.assertEqual([row['kind'] for row in self.frequent()], ['skill', 'command'])
        self.assertEqual(self.record(C, 'third', 'tool', event='applied')['status'], 'ignored')

    def test_two_uses_promote_and_rolling_window_demotes_on_read(self):
        self.record(receipt='one', now=NOW - 30 * DAY)
        self.assertEqual(self.frequent(), [])
        self.record(receipt='two', now=NOW - DAY)
        self.assertEqual(self.frequent()[0]['uses'], 2)
        before = (self.store / usage.USAGE_FILE).read_bytes()
        self.assertEqual(self.frequent(now=NOW + 1), [])
        self.assertEqual(before, (self.store / usage.USAGE_FILE).read_bytes())

    def test_counts_then_recency_then_id_sort_and_bound(self):
        for identifier, timestamps in ((C, (NOW - 1, NOW)), (B, (NOW - 2, NOW - 2)),
                                       (A, (NOW - 3, NOW - 3, NOW - 3))):
            for index, timestamp in enumerate(timestamps):
                self.record(identifier, identifier + str(index), now=timestamp)
        self.assertEqual([row['id'] for row in self.frequent()], [A, C, B])
        self.assertEqual([row['id'] for row in self.frequent(limit=2)], [A, C])
        self.assertEqual(self.frequent(limit=0), [])
        self.record(B, 'tie', now=NOW - 3)
        self.record(C, 'tie-c', now=NOW - 3)
        self.assertEqual([row['id'] for row in self.frequent()], [C, B, A])

    def test_equal_counts_and_recency_use_deterministic_id_tie(self):
        for identifier in (C, B, A):
            self.record(identifier, identifier + '-one')
            self.record(identifier, identifier + '-two')
        self.assertEqual([row['id'] for row in self.frequent()], [A, B, C])

    def test_eligibility_filters_after_ranking_preserves_counts(self):
        for identifier in (A, B, C):
            self.record(identifier, identifier + '-one')
            self.record(identifier, identifier + '-two')
        self.assertEqual([row['id'] for row in self.frequent((C,), limit=1)], [C])
        self.assertEqual(self.frequent(()), [])
        self.assertEqual(len(self.frequent()), 3)

    def test_future_receipts_do_not_promote_until_time_is_reached(self):
        self.record(receipt='one', now=NOW + 1)
        self.record(receipt='two', now=NOW + 1)
        self.assertEqual(self.frequent(), [])
        self.assertEqual(self.frequent(now=NOW + 1)[0]['uses'], 2)

    def test_explicit_aliases_owner_only_and_disabled_ids_filtered(self):
        eligible = {A, B, C}
        self.assertEqual(usage.configure_direct(self.store, [B, A], eligible), [B, A])
        self.assertEqual(usage.direct_ids(self.store, eligible), [B, A])
        self.assertEqual(usage.direct_ids(self.store, (A,)), [A])
        self.assertEqual(usage.direct_ids(self.store, eligible), [B, A])
        self.assertEqual(eligible, {A, B, C})
        self.assertEqual(stat.S_IMODE((self.store / usage.DIRECT_FILE).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.store / '.direct-capabilities.lock').stat().st_mode), 0o600)
        usage.configure_direct(self.store, [], eligible)
        self.assertEqual(usage.direct_ids(self.store, eligible), [])

    def test_alias_promotion_and_demotion_preserve_normal_directory_bytes(self):
        directory = self.store / 'capability-directory.json'
        original = json.dumps({'leaves': [{'id': 'ordinary', 'members': [A, B]}]}).encode()
        directory.write_bytes(original)
        directory.chmod(0o600)
        usage.configure_direct(self.store, [A], (A, B))
        self.record(receipt='one')
        self.record(receipt='two')
        self.assertEqual(self.frequent()[0]['id'], A)
        self.assertEqual(self.frequent(now=NOW + 31 * DAY), [])
        self.assertEqual(directory.read_bytes(), original)

    def test_direct_invalid_unknown_and_duplicate_ids_do_not_write(self):
        for ids in ([A, A], [B], ['malformed'], A, [A] * 129):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                usage.configure_direct(self.store, ids, (A,))
        self.assertEqual(list(self.store.iterdir()), [])

    def test_malformed_direct_settings_are_not_silently_overwritten(self):
        path = self.store / usage.DIRECT_FILE
        for body in ('{', '[]', '{"schema":"wrong","ids":[]}',
                     json.dumps({'schema': usage.DIRECT_SCHEMA, 'ids': [A, A]}),
                     json.dumps({'schema': usage.DIRECT_SCHEMA, 'ids': ['not-canonical']}),
                     '{"schema":"x","schema":"y","ids":[]}',
                     json.dumps({'schema': usage.DIRECT_SCHEMA, 'ids': [], 'extra': True})):
            path.write_text(body)
            path.chmod(0o600)
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    usage.direct_ids(self.store, (A,))
                with self.assertRaises(ValueError):
                    usage.configure_direct(self.store, [A], (A,))
                self.assertEqual(path.read_text(), body)

    def test_store_symlink_permissions_and_owner_are_refused(self):
        link = self.root / 'link'
        link.symlink_to(self.store, target_is_directory=True)
        for action in (lambda store: usage.direct_ids(store, (A,)),
                       lambda store: usage.configure_direct(store, [A], (A,)),
                       lambda store: usage.frequent_ids(store, (A,)),
                       lambda store: usage.record_use(store, A, 'tool', 'one', completed=True)):
            with self.assertRaises(ValueError):
                action(link)
            self.store.chmod(0o755)
            with self.assertRaises(ValueError):
                action(self.store)
            self.store.chmod(0o700)
            with patch.object(usage.os, 'getuid', return_value=os.getuid() + 1):
                with self.assertRaises(ValueError):
                    action(self.store)

    def test_db_settings_locks_and_sidecars_reject_unsafe_files(self):
        for name in (usage.DIRECT_FILE, usage.USAGE_FILE, '.capability-usage.lock',
                     '.direct-capabilities.lock', usage.USAGE_FILE + '-journal',
                     usage.USAGE_FILE + '-wal', usage.USAGE_FILE + '-shm'):
            actions = ([lambda: usage.direct_ids(self.store, (A,)),
                        lambda: usage.configure_direct(self.store, [A], (A,))]
                       if name == usage.DIRECT_FILE else
                       [lambda: usage.configure_direct(self.store, [A], (A,))]
                       if name == '.direct-capabilities.lock' else
                       [lambda: self.record()])
            if name not in (usage.DIRECT_FILE, '.capability-usage.lock', '.direct-capabilities.lock'):
                actions.append(lambda: self.frequent())
            outside = self.root / 'outside'
            outside.write_text('untouched')
            outside.chmod(0o600)
            path = self.store / name
            if path.exists():
                path.unlink()  # Remove only this test's earlier generated lock.
            for unsafe in ('symlink', 'dangling_symlink', 'hardlink', 'permissions'):
                with self.subTest(name=name, unsafe=unsafe):
                    if unsafe.endswith('symlink'):
                        path.symlink_to(outside if unsafe == 'symlink' else self.root / 'absent')
                    elif unsafe == 'hardlink':
                        os.link(outside, path)
                    else:
                        path.write_text('unsafe')
                        path.chmod(0o644)
                    for action in actions:
                        with self.assertRaises(ValueError):
                            action()
                    path.unlink()
                    self.assertEqual(outside.read_text(), 'untouched')

    def test_existing_database_and_direct_settings_require_current_owner(self):
        self.record()
        usage.configure_direct(self.store, [A], (A,))
        owner = os.getuid()
        for action in (lambda: usage.direct_ids(self.store, (A,)), lambda: self.frequent()):
            # Accept the store owner, then reject the individual file owner.
            with patch.object(usage.os, 'getuid', side_effect=(owner, owner + 1)):
                with self.assertRaisesRegex(ValueError, 'unsafe_capability_usage_file'):
                    action()

    def test_frequent_settings_and_usage_inputs_are_bounded(self):
        for kwargs in ({'limit': -1}, {'limit': 33}, {'limit': True}, {'days': 0},
                       {'days': 366}, {'min_uses': 0}, {'now': float('nan')},
                       {'now': float('inf')}, {'now': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.frequent(**kwargs)
        for args in (('bad', 'tool', 'r'), (A, 'hook', 'r'), (A, [], 'r'),
                     (A, 'tool', ''), (A, 'tool', ' '), (A, 'tool', 'x' * 4097)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                usage.record_use(self.store, *args, completed=True)
        with self.assertRaises(ValueError):
            self.record(completed=1)
        with self.assertRaises(ValueError):
            self.frequent(eligible=A)
        self.assertEqual(list(self.store.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
