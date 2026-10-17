"""Read-only source preflight. No source activation, installation or model calls.

Only approved public source metadata is copied. Private Skill stores, credentials,
plugin payloads and MCP processes are never read or run. Incomplete reads remain
explicit; they must not be replaced by an apparently complete shortlist.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace


def save(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def deduplicate(rows):
    """Exact implementation identity only; same name/description is insufficient.

    Versions, operation mode and component path are identity boundaries.
    All description variants and source aliases survive an identity merge.
    """
    groups = {}
    for row in rows:
        identity = row.get('identity')
        identity = ['exact', identity, row['kind'], row.get('mode')] if identity else ['unverified', row['id']]
        marker = key(identity)
        if marker not in groups:
            groups[marker] = {**row, 'aliases': [], 'provenance': [], 'metric_observations': [],
                              'descriptions': [], 'publisher_labels': []}
        result = groups[marker]
        for description in row.get('descriptions', [row['description']]):
            if description not in result['descriptions']: result['descriptions'].append(description)
        result['description'] = '\nAlternate source description: '.join(result['descriptions'])
        for label in row.get('publisher_labels', []):
            if label not in result['publisher_labels']: result['publisher_labels'].append(label)
        for alias in row.get('aliases', [row['id']]):
            if alias not in result['aliases']: result['aliases'].append(alias)
        provenance = row['provenance'] if isinstance(row['provenance'], list) else [row['provenance']]
        for item in provenance:
            if item not in result['provenance']: result['provenance'].append(item)
        observations = row.get('metric_observations', [{'id': row['id'], 'rank': row.get('rank'), 'growth': row.get('growth')}])
        for item in observations:
            if item not in result['metric_observations']: result['metric_observations'].append(item)
        for field in ('rank', 'growth'):
            if any(item.get(field) != result.get(field) for item in result['metric_observations']):
                result[field] = None  # Keep raw observations; never choose an arbitrary market's rank.
    return list(groups.values())


def collect(args):
    began = time.monotonic()
    out = Path(args.output).resolve()
    out.mkdir(mode=0o700, exist_ok=False)
    runtime = Path(args.runtime).resolve()
    data = Path(args.data).resolve()
    sys.path.insert(0, str(runtime / 'adapters/standalone'))
    sys.path.insert(0, str(runtime / 'scripts'))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'adapters/codex'))
    import external_skills
    import plugin_sources
    import market_connect
    import market_registry

    source_state = external_skills.registry(data)
    rows, coverage = [], []
    for sid, source in source_state['sources'].items():
        if not source['enabled']:
            coverage.append({'source': sid, 'kind': 'skill', 'status': 'disabled'})
            continue
        if source.get('scope') not in (None, args.project):
            coverage.append({'source': sid, 'kind': 'skill', 'status': 'different_project'})
            continue
        snap = source['snapshot']
        provenance = {k: snap.get(k) for k in ('repo', 'commit', 'checked_at', 'url')}
        coverage.append({'source': snap['repo'], 'kind': 'skill', 'status': 'complete_enabled_snapshot',
                         'count': len(source['skills']), 'issues': len(source.get('issues', [])), **provenance})
        for skill in source['skills']:
            rows.append({'id': 'skill-' + key([sid, skill['path']])[:20], 'kind': 'skill', 'mode': 'guidance',
                         'name': skill['name'], 'description': skill['description'],
                         'identity': [snap['repo'].lower(), snap['commit'], skill['path']],
                         'rank': None, 'growth': None, 'provenance': {**provenance, 'path': skill['path']}})
    save(out / 'enabled-skills.json', rows)
    enabled_repos = {s['snapshot']['repo'] for s in source_state['sources'].values() if s['enabled']}
    coverage.append({'source': 'openai/plugins', 'kind': 'skill',
                     'status': 'enabled' if 'openai/plugins' in enabled_repos else 'not_enabled_in_public_skill_registry'})

    # The owner is read-only and the manager root is isolated. Native plugin/list
    # is metadata-only; no native install/update/enable command is used.
    sandbox = out / 'manager'; sandbox.mkdir(mode=0o700)
    custom_path = data / 'plugin-sources.json'
    if custom_path.is_file():
        custom = json.loads(custom_path.read_text())
        save(sandbox / 'plugin-sources.json', custom)
    owner = SimpleNamespace(manager=SimpleNamespace(data=sandbox, _safe_roots=lambda: None,
        hosts=SimpleNamespace(home=Path.home(), environment=dict(os.environ))), error=ValueError)
    owner.safe = lambda p: Path(p)
    owner.read = lambda p: Path(p).read_bytes() if Path(p).is_file() else None
    owner.executable = lambda name: shutil.which(name)
    # Only load the Codex metadata adapter, without constructing runtime hosts.
    import importlib.util
    spec = importlib.util.spec_from_file_location('preflight_codex_adapter', runtime / 'adapters/codex/plugin_manager.py')
    adapter = importlib.util.module_from_spec(spec); spec.loader.exec_module(adapter)
    owner.adapters = {'codex': adapter.Adapter(owner)}
    market_connect.register_public_plugin_markets(plugin_sources)
    library = plugin_sources.Library(owner)
    # Match the public gateway source set; OpenCode is native-only there.
    sources = [s for s in library.listing()['sources'] if s['id'] in {'openai', 'anthropic'} or s['id'].startswith('github:')]

    def plugin_snapshot(source):
        start = time.monotonic()
        try:
            result = library.browse(source['id'])
            return {'source': source['id'], 'kind': 'plugin', 'status': 'complete',
                    'seconds': time.monotonic()-start, 'snapshot': result}
        except Exception as exc:
            return {'source': source['id'], 'kind': 'plugin', 'status': 'unavailable',
                    'seconds': time.monotonic()-start, 'error': str(exc)}

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(plugin_snapshot, sources))
    for result in results:
        save(out / ('plugin-' + key(result['source'])[:16] + '.json'), result)
        snap = result.pop('snapshot', None)
        coverage.append({**result, 'count': len(snap['items']) if snap else 0})
        if snap is None: continue
        for item in snap['items']:
            identity = [snap.get('repo') or snap.get('marketplace'), snap['commit'], item['name']]
            rows.append({'id': 'plugin-' + key([result['source'], identity])[:20], 'kind': 'plugin',
                         'mode': 'package_requirements_unverified', 'name': item['name'],
                         'description': item['description'], 'identity': identity,
                         'rank': None, 'growth': None,
                         'provenance': {'source': result['source'], 'commit': snap['commit'],
                                        'checked_at': snap['checked_at'], 'url': item.get('url')}})

    # Full pagination has a separate bounded acquisition budget. A partial read
    # is preserved for diagnosis, never labelled complete or sent to a selector.
    mcp, cursor, seen, error = [], '', set(), None
    deadline = time.monotonic() + args.registry_seconds
    for page in range(args.registry_pages):
        try:
            result = market_registry.fetch('', cursor, deadline)
            if not isinstance(result.get('servers'), list): raise ValueError('invalid_servers')
            save(out / ('registry-page-' + str(page) + '.json'), result)
            mcp.extend(result['servers'])
            cursor = result.get('metadata', {}).get('nextCursor')
            if not cursor: break
            if not isinstance(cursor, str) or cursor in seen: raise ValueError('invalid_cursor')
            seen.add(cursor)
        except Exception as exc:
            error = str(exc); break
    else:
        error = 'bounded_page_limit'
    complete = error is None and not cursor
    coverage.append({'source': 'registry', 'kind': 'mcp', 'status': 'complete' if complete else 'incomplete',
                     'received': len(mcp), 'error': error, 'has_more': bool(cursor)})
    if complete:
        for item in mcp:
            server = item.get('server', {})
            if item.get('_meta', {}).get('io.modelcontextprotocol.registry/official', {}).get('status') != 'active': continue
            identity = [server['name'], server['version']]
            rows.append({'id': 'mcp-' + key(identity)[:20], 'kind': 'mcp', 'mode': 'execution_requirements_unverified',
                         'name': server['name'], 'description': server.get('description', ''), 'identity': identity,
                         'rank': None, 'growth': None, 'provenance': {'source': 'registry', 'version': server['version']}})

    # These separate protocol-reference entries are also an exposed source.
    try:
        result = market_registry.curl_fetch(shutil.which('curl'),
            'https://registry.npmjs.org/@modelcontextprotocol/server-everything/latest', 15)
        save(out / 'mcp-reference.json', result)
        rows.append({'id': 'mcp-reference', 'kind': 'mcp', 'mode': 'execution_requirements_unverified',
            'name': result['name'], 'description': result.get('description', 'MCP protocol examples: echo and addition.'),
            'identity': ['npm', result['name'], result['version']], 'rank': None, 'growth': None,
            'provenance': {'source': 'reference', 'version': result['version']}})
        coverage.append({'source': 'reference', 'kind': 'mcp', 'status': 'complete', 'count': 1})
    except Exception as exc:
        coverage.append({'source': 'reference', 'kind': 'mcp', 'status': 'unavailable', 'error': str(exc)})

    canonical = deduplicate(rows)
    save(out / 'catalog.json', canonical)
    report = {'version': 1, 'sources': coverage, 'records': len(rows), 'canonical_records': len(canonical),
              'kinds': dict(Counter(r['kind'] for r in canonical)),
              'rank_records': sum(r.get('rank') is not None for r in canonical),
              'growth_records': sum(r.get('growth') is not None for r in canonical),
              'seconds': time.monotonic()-began, 'model_calls': 0, 'model_tokens': 0,
              'execution': 'not_performed', 'install': 'not_performed',
              'limitations': ['Public connection source universe, not private Skills.',
                  'Plugin/MCP package requirements and execution are not validated by directory reads.',
                  'Missing rank/growth is unknown, never zero popularity.'],
              'live_comparison_ready': False}
    save(out / 'report.json', report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--data', required=True)
    parser.add_argument('--project', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--registry-pages', type=int, default=60)
    parser.add_argument('--registry-seconds', type=float, default=180)
    collect(parser.parse_args())
