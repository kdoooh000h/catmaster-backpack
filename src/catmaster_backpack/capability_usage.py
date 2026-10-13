"""Owner-configured aliases and receipt-backed recent use, never authorization.

Callers supply current, enabled, host-eligible canonical IDs. These helpers only
return extra directory entries; they never edit normal classification or dispatch
operations. Application reports must describe actual completed application, not
acquisition of guidance. No task text or raw receipt is persisted.
"""
from contextlib import closing, contextmanager
import hashlib
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time

try:
    from .plugin_pipeline import atomic_json, file_lock, read_json
except ImportError:
    from plugin_pipeline import atomic_json, file_lock, read_json

DIRECT_FILE = 'direct-capabilities.json'
DIRECT_SCHEMA = 'catmaster-direct-capabilities/v1'
USAGE_FILE = 'capability-usage.sqlite'
KINDS = frozenset(('tool', 'resource', 'skill', 'command'))
MAX_DIRECT = 24
MAX_FREQUENT = 32
_ID = re.compile(r'cap_[0-9a-f]{20}\Z')


def _capability_id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError('invalid_canonical_capability_id')
    return value


def _ids(values):
    if isinstance(values, (str, bytes)):
        raise ValueError('capability_ids_collection_required')
    try:
        return {_capability_id(value) for value in values}
    except TypeError as exc:
        raise ValueError('capability_ids_collection_required') from exc


def _store(store):
    path = Path(store).absolute()
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise ValueError('usage_store_requires_owner_only_access')
    return path


def _safe_file(path):
    """Validate existing files, including dangling links, without following them."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077 or info.st_nlink != 1):
        raise ValueError('unsafe_capability_usage_file')
    return info


@contextmanager
def _locked(store, name):
    path = store / name
    if _safe_file(path) is None:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            _safe_file(path)
        else:
            os.close(fd)
    with file_lock(path):
        _safe_file(path)
        yield


def _read_direct(path):
    if _safe_file(path) is None:
        return []
    value = read_json(path)
    if (not isinstance(value, dict) or set(value) != {'schema', 'ids'}
            or value['schema'] != DIRECT_SCHEMA or not isinstance(value['ids'], list)
            or len(value['ids']) > MAX_DIRECT):
        raise ValueError('invalid_direct_capabilities_settings')
    ids = value['ids']
    if len(_ids(ids)) != len(ids):
        raise ValueError('duplicate_direct_capability_id')
    return ids


def configure_direct(store, ids, eligible_ids):
    """Persist explicit owner aliases; unknown/currently ineligible IDs are refused."""
    if not isinstance(ids, (list, tuple)) or len(ids) > MAX_DIRECT:
        raise ValueError('invalid_direct_capabilities_settings')
    selected = _ids(ids)
    if len(selected) != len(ids):
        raise ValueError('duplicate_direct_capability_id')
    if not selected <= _ids(eligible_ids):
        raise ValueError('ineligible_direct_capability_id')
    store = _store(store)
    with _locked(store, '.direct-capabilities.lock'):
        path = store / DIRECT_FILE
        _read_direct(path)  # Refuse unsafe or malformed settings before replacement.
        atomic_json(path, {'schema': DIRECT_SCHEMA, 'ids': list(ids)})
        _safe_file(path)
    return list(ids)


def direct_ids(store, eligible_ids):
    """Read aliases without creating files; stale aliases remain stored but hidden."""
    eligible = _ids(eligible_ids)
    try:
        store = _store(store)
    except FileNotFoundError:
        return []
    return [identifier for identifier in _read_direct(store / DIRECT_FILE) if identifier in eligible]


def _now(value):
    value = time.time() if value is None else value
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0):
        raise ValueError('invalid_usage_timestamp')
    return float(value)


def _db_files(store):
    path = store / USAGE_FILE
    info = _safe_file(path)
    for suffix in ('-journal', '-wal', '-shm'):
        _safe_file(store / (USAGE_FILE + suffix))
    return path, info


def record_use(store, capability_id, kind, receipt_id, *, completed=False,
               event='completed', now=None):
    """Count completed operations or reported applications once per durable receipt.

    Tool/resource events must be ``completed``; Skill/command events must be
    ``applied`` or ``application_reported``. Every kind also requires the explicit
    ``completed=True`` assertion. Failure, unknown, selection and acquisition
    events are ignored without a write. Replays do not refresh their timestamp.
    """
    capability_id = _capability_id(capability_id)
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError('invalid_capability_kind')
    if (not isinstance(receipt_id, str) or not receipt_id.strip()
            or len(receipt_id) > 4096):
        raise ValueError('invalid_usage_receipt_id')
    if type(completed) is not bool or not isinstance(event, str):
        raise ValueError('invalid_usage_completion')
    timestamp = _now(now)
    allowed = ('completed',) if kind in ('tool', 'resource') else ('applied', 'application_reported')
    if not completed or event not in allowed:
        return {'status': 'ignored', 'counted': False}
    receipt = hashlib.sha256(receipt_id.encode('utf-8')).hexdigest()
    store = _store(store)
    with _locked(store, '.capability-usage.lock'):
        path, info = _db_files(store)
        if info is None:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        with closing(sqlite3.connect(path, timeout=10)) as db:
            db.execute('PRAGMA journal_mode=DELETE')
            db.execute('CREATE TABLE IF NOT EXISTS completed_uses ('
                       'receipt_hash TEXT PRIMARY KEY, capability_id TEXT NOT NULL, '
                       'kind TEXT NOT NULL, used_at REAL NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS completed_uses_time ON completed_uses(used_at)')
            with db:
                row = db.execute('SELECT capability_id,kind FROM completed_uses WHERE receipt_hash=?',
                                 (receipt,)).fetchone()
                if row is not None:
                    if row != (capability_id, kind):
                        raise ValueError('usage_receipt_conflict')
                    result = {'status': 'duplicate', 'counted': False}
                else:
                    db.execute('INSERT INTO completed_uses VALUES(?,?,?,?)',
                               (receipt, capability_id, kind, timestamp))
                    result = {'status': 'recorded', 'counted': True}
        _db_files(store)
    return result


def frequent_ids(store, eligible_ids, *, now=None, limit=6, days=30, min_uses=2):
    """Recalculate rolling aliases, ordered by count, recency and canonical ID.

    Only timestamps in ``[now - days * 86400, now]`` count. Reads never create a
    store, database, settings or lock, and never delete or reclassify capabilities.
    """
    for name, value, maximum in (('limit', limit, MAX_FREQUENT), ('days', days, 365),
                                 ('min_uses', min_uses, 1_000_000)):
        if type(value) is not int or value < (0 if name == 'limit' else 1) or value > maximum:
            raise ValueError('invalid_frequent_' + name)
    eligible = _ids(eligible_ids)
    timestamp = _now(now)
    try:
        store = _store(store)
    except FileNotFoundError:
        return []
    path, info = _db_files(store)
    if info is None:
        return []
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
        rows = db.execute('SELECT capability_id,COUNT(*),MAX(used_at),MIN(kind),MAX(kind) '
                          'FROM completed_uses WHERE used_at>=? AND used_at<=? '
                          'GROUP BY capability_id HAVING COUNT(*)>=? '
                          'ORDER BY COUNT(*) DESC,MAX(used_at) DESC,capability_id ASC',
                          (timestamp - days * 86400, timestamp, min_uses)).fetchall()
    result = []
    for identifier, uses, last_used, kind, max_kind in rows:
        _capability_id(identifier)
        if kind not in KINDS or kind != max_kind:
            raise ValueError('invalid_recorded_capability_kind')
        if identifier in eligible and len(result) < limit:
            result.append({'id': identifier, 'uses': uses, 'last_used': last_used, 'kind': kind})
    return result
