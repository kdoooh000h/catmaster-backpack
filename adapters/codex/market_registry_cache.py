"""Private exact-query snapshots for official Registry search read outages.

Only write a union after every search term's pagination completed (complete=True).
read returns None only for a missing snapshot; invalid/expired data raises
ValueError, unsafe filesystem artifacts raise ValueError or OSError.
refresh accepts fetch_url(url, timeout_seconds), returning a Registry
detail envelope. It never writes: detail refresh cannot discover new names, so
checked_at remains the original complete-search timestamp.
"""
import concurrent.futures
import copy
import hashlib
import json
import math
import os
import re
import secrets
import stat
import time
import urllib.parse

SOURCE = 'https://registry.modelcontextprotocol.io/v0.1/servers'
OFFICIAL = 'io.modelcontextprotocol.registry/official'
MAX_BYTES = 2 * 1024 * 1024
MAX_AGE = 24 * 60 * 60
FRESH_AGE = 300
MAX_NAMES = 12
REQUEST_TIMEOUT = 12
GLOBAL_TIMEOUT = 30


def normalize_terms(terms):
    """Canonical case-insensitive OR query; no keyword injection or truncation."""
    if isinstance(terms, str):
        terms = re.findall(r'[\w@./-]+', terms.strip(), flags=re.UNICODE)
    if not isinstance(terms, (list, tuple)) or not terms:
        raise ValueError('registry_cache_invalid_terms')
    if any(not isinstance(term, str) or not re.fullmatch(r'[\w@./-]{1,200}', term)
           for term in terms):
        raise ValueError('registry_cache_invalid_terms')
    normalized = sorted({term.casefold() for term in terms})
    if not 1 <= len(normalized) <= 4:
        raise ValueError('registry_cache_invalid_terms')
    return normalized


def _filename(terms):
    key = json.dumps(terms, ensure_ascii=True, separators=(',', ':')).encode()
    return hashlib.sha256(key).hexdigest() + '.json'


def _number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _rows(rows, terms):
    if not isinstance(rows, list):
        raise ValueError('registry_cache_invalid_rows')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('server'), dict):
            raise ValueError('registry_cache_invalid_entry')
        server, envelope = row['server'], row.get('_meta')
        meta = envelope.get(OFFICIAL) if isinstance(envelope, dict) else None
        name, version = server.get('name'), server.get('version')
        if (not isinstance(name, str) or not 1 <= len(name) <= 200
                or not isinstance(version, str) or not 1 <= len(version) <= 100
                or not isinstance(meta, dict) or meta.get('isLatest') is not True
                or not isinstance(meta.get('status'), str)
                or meta.get('status') not in {'active', 'deprecated', 'deleted'}
                or not any(term in name.casefold() for term in terms)):
            raise ValueError('registry_cache_invalid_entry')
        if name in seen:
            raise ValueError('registry_cache_duplicate_name')
        seen.add(name)
    return rows


def _validate(snapshot, terms, now, allow_expired=False):
    if (not isinstance(snapshot, dict) or snapshot.get('version') != 1
            or snapshot.get('source') != SOURCE or snapshot.get('complete') is not True
            or snapshot.get('coverage') != 'complete_at_snapshot'
            or snapshot.get('search_terms') != terms):
        raise ValueError('registry_cache_incomplete_or_query_mismatch')
    checked_at = snapshot.get('checked_at')
    refreshed_at = snapshot.get('metadata_refreshed_at')
    if (not _number(now) or not _number(checked_at) or checked_at > now
            or (not allow_expired and now - checked_at > MAX_AGE)):
        raise ValueError('registry_cache_expired_or_invalid_time')
    if refreshed_at is not None and (not _number(refreshed_at)
                                    or not checked_at <= refreshed_at <= now):
        raise ValueError('registry_cache_invalid_refresh_time')
    _rows(snapshot.get('rows'), terms)
    return snapshot


def _directory(cache_root, create=False):
    if create:
        try:
            os.mkdir(cache_root, 0o700)
        except FileExistsError:
            pass
    fd = os.open(cache_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    info = os.fstat(fd)
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        os.close(fd)
        raise ValueError('registry_cache_unsafe_directory')
    return fd


def _read_at(directory, filename):
    fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_nlink != 1
                or info.st_size > MAX_BYTES):
            raise ValueError('registry_cache_unsafe_file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            content = stream.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise ValueError('registry_cache_too_large')
        try:
            return json.loads(content), info
        except (ValueError, UnicodeError, RecursionError):
            raise ValueError('registry_cache_invalid_json') from None
    finally:
        os.close(fd)


def read(cache_root, terms, now=None):
    """Read only this exact normalized query; reject stale or unsafe snapshots."""
    terms = normalize_terms(terms)
    now = time.time() if now is None else now
    try:
        directory = _directory(cache_root)
    except FileNotFoundError:
        return None
    try:
        try:
            snapshot, _ = _read_at(directory, _filename(terms))
        except FileNotFoundError:
            return None
        return _provenance(_validate(snapshot, terms, now), now)
    finally:
        os.close(directory)


def available_queries(cache_root, max_queries=32):
    """Return bounded query hints, never a complete cache or service inventory.

    Inspect at most four directory entries per requested hint (maximum 128).
    Validate ownership, type, permissions and size before parsing any content;
    disclose labels only after full snapshot and canonical filename validation.
    """
    if not isinstance(max_queries, int) or isinstance(max_queries, bool) or not 1 <= max_queries <= 32:
        raise ValueError('registry_cache_invalid_query_hint_limit')
    try:
        directory = _directory(cache_root)
    except (OSError, ValueError):
        return []
    result, now = [], time.time()
    try:
        with os.scandir(directory) as entries:
            for index, entry in enumerate(entries):
                if index >= max_queries * 4 or len(result) >= max_queries:
                    break
                if not re.fullmatch(r'[0-9a-f]{64}\.json', entry.name):
                    continue
                try:
                    snapshot, _ = _read_at(directory, entry.name)
                    if not isinstance(snapshot, dict):
                        continue
                    terms = normalize_terms(snapshot.get('search_terms', []))
                    if entry.name != _filename(terms):
                        continue
                    _validate(snapshot, terms, now)
                    result.append({'search_terms': terms, 'checked_at': snapshot['checked_at']})
                except (OSError, ValueError):
                    continue
    finally:
        os.close(directory)
    return sorted(result, key=lambda hint: hint['search_terms'])


def write(cache_root, terms, rows, checked_at, *, complete):
    """Atomically save a proven complete search, refusing invalid existing files."""
    terms = normalize_terms(terms)
    snapshot = {'version': 1, 'source': SOURCE, 'search_terms': terms,
                'complete': complete, 'coverage': 'complete_at_snapshot',
                'checked_at': checked_at, 'metadata_refreshed_at': None, 'rows': rows}
    _validate(snapshot, terms, time.time())
    content = json.dumps(snapshot, ensure_ascii=True, allow_nan=False,
                         separators=(',', ':')).encode()
    if len(content) > MAX_BYTES:
        raise ValueError('registry_cache_too_large')
    directory = _directory(cache_root, create=True)
    filename, temporary = _filename(terms), '.' + secrets.token_hex(16) + '.tmp'
    try:
        previous = None
        try:
            existing, previous = _read_at(directory, filename)
            # Expiry is normal replacement; malformed provenance is not.
            _validate(existing, terms, time.time(), allow_expired=True)
        except FileNotFoundError:
            pass
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if previous is None:
                # Atomic no-clobber publication if another artifact appeared.
                os.link(temporary, filename, src_dir_fd=directory, dst_dir_fd=directory,
                        follow_symlinks=False)
            else:
                current = os.stat(filename, dir_fd=directory, follow_symlinks=False)
                if (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_size) != (
                        previous.st_dev, previous.st_ino, previous.st_mtime_ns, previous.st_size):
                    raise ValueError('registry_cache_changed_during_write')
                os.replace(temporary, filename, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
    finally:
        os.close(directory)
    return _provenance(snapshot, checked_at)


def _provenance(snapshot, now):
    result = copy.deepcopy(snapshot)
    result['cache_age_seconds'] = now - snapshot['checked_at']
    result['exclusions'] = [
        {'name': row['server']['name'], 'status': row['_meta'][OFFICIAL]['status']}
        for row in snapshot['rows'] if row['_meta'][OFFICIAL]['status'] != 'active']
    return result


def refresh(snapshot, fetch_url, *, now=None, network_outage=False):
    """Reuse <=300s data, or refresh ALL <=12 names only after a read outage.

    Callbacks must honor their supplied timeout. The coordinator returns within
    30s even if a callback fails to do so; it never returns a successful subset.
    """
    now = time.time() if now is None else now
    terms = normalize_terms(snapshot.get('search_terms', []))
    _validate(snapshot, terms, now)
    rows = snapshot['rows']
    if now - snapshot['checked_at'] <= FRESH_AGE:
        return _provenance(snapshot, now)
    if network_outage is not True:
        raise ValueError('registry_cache_refresh_requires_read_outage')
    if len(rows) > MAX_NAMES:
        raise ValueError('registry_cache_fallback_too_broad')
    if not rows:
        result = copy.deepcopy(snapshot)
        result['metadata_refreshed_at'] = None
        return _provenance(result, now)
    deadline = time.monotonic() + GLOBAL_TIMEOUT

    def fetch(row):
        name = row['server']['name']
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('registry_cache_refresh_timeout')
        url = SOURCE + '/' + urllib.parse.quote(name, safe='') + '/versions/latest?include_deleted=true'
        value = fetch_url(url, min(REQUEST_TIMEOUT, remaining))
        _rows([value], terms)
        if value['server']['name'] != name:
            raise ValueError('registry_cache_changed_name')
        return value

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    futures = [pool.submit(fetch, row) for row in rows]
    try:
        done, pending = concurrent.futures.wait(futures, timeout=max(0, deadline - time.monotonic()),
                                               return_when=concurrent.futures.FIRST_EXCEPTION)
        if pending and not any(f.done() and f.exception() is not None for f in done):
            raise ValueError('registry_cache_refresh_timeout')
        for future in done:
            future.result()  # Propagate a failed detail before awaiting any pending work.
        refreshed = [future.result() for future in futures]
    finally:
        for future in futures:
            future.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
    result = copy.deepcopy(snapshot)
    result['rows'] = refreshed
    completed_at = now + max(0, time.monotonic() - (deadline - GLOBAL_TIMEOUT))
    result['metadata_refreshed_at'] = completed_at
    _validate(result, terms, completed_at)
    return _provenance(result, completed_at)
