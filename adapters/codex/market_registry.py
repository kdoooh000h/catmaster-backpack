"""Bounded anonymous Registry reads; no writes, mirrors, installs or TLS bypass."""
import concurrent.futures
import json
import re
import secrets
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = 'https://registry.modelcontextprotocol.io/v0.1/servers'
MAX_CANDIDATES = 192
MAX_PAGES = 6
MAX_BYTES = 2 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('registry_redirect_rejected')


def _fetch(query, cursor, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError('registry_deadline_exceeded')
    params = {'version': 'latest', 'limit': 100, 'search': query}
    if cursor:
        params['cursor'] = cursor
    url = ROOT + '?' + urllib.parse.urlencode(params)
    executable = shutil.which('curl')
    if executable:
        return curl_fetch(executable, url, min(35, remaining))
    request = urllib.request.Request(url,
                                     headers={'User-Agent': 'CatMaster-Backpack', 'Accept': 'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=min(35, remaining)) as response:
            content = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        raise ValueError('registry_rate_limited' if code in {403, 429} else 'registry_http_error') from None
    except (OSError, urllib.error.URLError):
        raise ValueError('registry_read_timeout_or_network_error') from None
    if len(content) > MAX_BYTES:
        raise ValueError('registry_response_too_large')
    try:
        value = json.loads(content)
    except ValueError:
        raise ValueError('registry_invalid_json') from None
    if not isinstance(value, dict):
        raise ValueError('registry_invalid_response')
    return value


def curl_fetch(executable, url, timeout):
    # Native curl negotiates HTTP/2 when supported. -q disables curlrc and its
    # credentials/options; no netrc, redirects, retries or insecure TLS flags.
    try:
        result = subprocess.run([executable, '-q', '--silent', '--show-error', '--fail',
            '--proto', '=https', '--max-time', str(timeout), '--max-filesize', str(MAX_BYTES),
            '--header', 'Accept: application/json', '--user-agent', 'CatMaster-Backpack',
            '--write-out', '\n%{http_code}', '--url', url], capture_output=True, timeout=timeout + 2)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('registry_read_timeout_or_network_error') from None
    content, _, status = result.stdout.rpartition(b'\n')
    if status in {b'403', b'429'}:
        raise ValueError('registry_rate_limited')
    if status.startswith(b'3'):
        raise ValueError('registry_redirect_rejected')
    if result.returncode == 63 or len(content) > MAX_BYTES:
        raise ValueError('registry_response_too_large')
    if result.returncode in {6, 7, 28, 35, 52, 56}:
        raise ValueError('registry_read_timeout_or_network_error')
    if result.returncode or status != b'200':
        raise ValueError('registry_http_error')
    try:
        value = json.loads(content)
    except ValueError:
        raise ValueError('registry_invalid_json') from None
    if not isinstance(value, dict):
        raise ValueError('registry_invalid_response')
    return value


def fetch(query, cursor, deadline):
    # Only this anonymous idempotent GET may retry a confirmed read failure.
    # Setup and business receipts never pass through this transport.
    for attempt in range(2):
        try:
            return _fetch(query, cursor, deadline)
        except ValueError as error:
            if (str(error) != 'registry_read_timeout_or_network_error' or attempt
                    or deadline - time.monotonic() < 1):
                raise


def pages(query, deadline):
    rows, cursors, cursor = [], set(), ''
    for _ in range(MAX_PAGES):
        value = fetch(query, cursor, deadline)
        items, meta = value.get('servers'), value.get('metadata', {})
        if not isinstance(items, list) or len(items) > 100 or not isinstance(meta, dict):
            raise ValueError('registry_invalid_response')
        rows.extend(items)
        # A single term already exceeding the final bound cannot become a
        # selectable complete union. Stop reading its remaining pages early;
        # return an explicit broad-search result, never a truncated candidate set.
        active = {(r.get('server', {}).get('name'), r.get('server', {}).get('version')) for r in rows
                  if isinstance(r, dict) and isinstance(r.get('server'), dict)
                  and isinstance(r['server'].get('name'), str) and isinstance(r['server'].get('version'), str)
                  and isinstance(r.get('_meta', {}), dict)
                  and isinstance(r.get('_meta', {}).get('io.modelcontextprotocol.registry/official', {}), dict)
                  and r.get('_meta', {}).get('io.modelcontextprotocol.registry/official', {}).get('status') == 'active'}
        if len(active) > MAX_CANDIDATES:
            raise ValueError('registry_search_too_broad')
        cursor = meta.get('nextCursor')
        if cursor is None or cursor == '':
            return rows
        if not isinstance(cursor, str) or len(cursor) > 1024 or cursor in cursors:
            raise ValueError('registry_invalid_pagination')
        cursors.add(cursor)
    raise ValueError('registry_search_too_broad')


def browse(library, search):
    # The upstream API matches name substrings, not natural-language sentences.
    # OR the supplied functional terms. Never inject known capability names or
    # silently take only the first page. Chinese can be supplied as a term too.
    terms = list(dict.fromkeys(re.findall(r'[\w@./-]+', search.strip(), flags=re.UNICODE)))
    if not terms or len(terms) > 4:
        return {'items': [], 'next_cursor': 'search_required',
                'instruction': 'Supply one to four short functional search terms, preferably English for the public name index; do not guess a product name.'}
    deadline = time.monotonic() + 80
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(terms)) as pool:
            batches = list(pool.map(lambda term: pages(term, deadline), terms))
    except ValueError as error:
        if str(error) == 'registry_search_too_broad':
            return {'items': [], 'next_cursor': 'too_broad',
                    'instruction': 'Use one more specific functional keyword; this result exceeds the complete candidate bound.'}
        raise
    unique = {}
    for rows in batches:
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('registry_invalid_entry')
            server = row.get('server')
            envelope = row.get('_meta', {})
            if not isinstance(envelope, dict):
                raise ValueError('registry_invalid_entry')
            meta = envelope.get('io.modelcontextprotocol.registry/official', {})
            if not isinstance(server, dict) or not isinstance(meta, dict):
                raise ValueError('registry_invalid_entry')
            if meta.get('status') != 'active':
                continue
            name, version = server.get('name'), server.get('version')
            if not isinstance(name, str) or not 1 <= len(name) <= 200 or not isinstance(version, str) or not 1 <= len(version) <= 100:
                raise ValueError('registry_invalid_entry')
            key = (name, version)
            if key in unique and unique[key] != server:
                raise ValueError('registry_changed_during_search')
            unique[key] = server
    if len(unique) > MAX_CANDIDATES:
        return {'items': [], 'next_cursor': 'too_broad', 'candidate_count': len(unique)}
    now = time.time()
    library.items = {k: v for k, v in library.items.items() if now - v['checked_at'] < 900}
    if len(library.items) + len(unique) > 640:
        raise ValueError('registry_receipt_limit')
    result = []
    for (name, version), server in sorted(unique.items()):
        token = secrets.token_hex(16)
        library.items[token] = {'server': server, 'checked_at': now, 'source': 'registry'}
        result.append({'receipt': token, 'name': name, 'title': str(server.get('title', name))[:200],
                       'description': str(server.get('description', ''))[:1200], 'version': version})
    return {'items': result, 'next_cursor': None, 'search_terms': terms, 'checked_at': now}
