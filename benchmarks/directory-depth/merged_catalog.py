"""Merge public markets into task directories, preserving package boundaries.

A standalone Skill, whole plugin or MCP service is one candidate. Plugin-internal
Skills are component metadata, never extra independently selected candidates.
Market identifiers are provenance only and never create directory nodes.
"""
import json
from pathlib import Path
import posixpath
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'adapters/codex'))
from market_directory import TOPICS, declared_topics, publisher_labels
from source_preflight import deduplicate, key


def plugin_identity(snapshot, item):
    native = item.get('native_entry')
    if isinstance(native, dict):
        # Native directory snapshots use a random revision token. The observed
        # package identity/version is the stable boundary, not that token.
        return ['native-plugin', native['pluginId'], native['version']]
    entry = item.get('entry', {})
    cosmetic = {'name', 'description', 'source', 'category', 'categories', 'author',
                'homepage', 'repository', 'license', 'keywords', 'tags'}
    overlays = {k: v for k, v in entry.items() if k not in cosmetic}
    suffix = [key(overlays)] if overlays else []
    source = entry.get('source')
    if isinstance(source, str):
        path = posixpath.normpath(source)
        if path.startswith('/') or path == '..' or path.startswith('../'):
            raise ValueError('unsafe_plugin_source')
        return ['github-plugin', snapshot['repo'].casefold(), snapshot['commit'], path, *suffix]
    if isinstance(source, dict):
        repo = source.get('repo') or source.get('url')
        if isinstance(repo, str):
            repo = repo.removeprefix('https://github.com/').removesuffix('.git').casefold()
        revision = source.get('sha')
        if (isinstance(repo, str) and re.fullmatch(r'[a-z0-9_.-]+/[a-z0-9_.-]+', repo)
                and isinstance(revision, str) and re.fullmatch(r'[a-f0-9]{40}', revision)):
            path = posixpath.normpath(source.get('path', '.'))
            if path.startswith('/') or path == '..' or path.startswith('../'):
                raise ValueError('unsafe_plugin_source')
            return ['github-plugin', repo, revision, path, *suffix]
    # An unpinned external source is not evidence of an identical implementation.
    return ['unresolved-plugin', snapshot['repo'], snapshot['commit'], item['name']]


def merged(snapshot):
    """Use the frozen complete sources only; never read native Skill folders."""
    snapshot = Path(snapshot)
    rows = [r for r in json.loads((snapshot / 'catalog.json').read_text()) if r['kind'] != 'plugin']
    for path in sorted(snapshot.glob('plugin-*.json')):
        result = json.loads(path.read_text())
        if result['status'] != 'complete': continue
        snap = result['snapshot']
        for item in snap['items']:
            identity = plugin_identity(snap, item)
            rows.append({'id': 'plugin-' + key([result['source'], item['name'], identity])[:20], 'kind': 'plugin',
                'mode': 'package_requirements_unverified', 'name': item['name'], 'description': item['description'],
                'identity': identity, 'rank': None, 'growth': None, 'publisher_labels': publisher_labels(item),
                'provenance': {'source': result['source'], 'commit': snap['commit'],
                               'checked_at': snap['checked_at'], 'url': item.get('url')}})
    return rows, deduplicate(rows)


def directory(rows):
    """Reuse publisher categories across markets. Unclassified stays visible.

    Missing classification is explicitly pending; it is not guessed from which
    market published a candidate. This compiler never silently removes an item.
    """
    groups = {topic: [] for topic in TOPICS}
    pending = []
    for row in rows:
        if row.get('parent_plugin') or row.get('plugin_internal'):
            raise ValueError('plugin_internal_skill_cannot_be_independent_candidate')
        labels = declared_topics({'categories': row.get('publisher_labels', [])})
        if not labels: pending.append(row['id'])
        for label in labels: groups[label].append(row['id'])
    nodes = {}
    for topic, members in groups.items():
        if members:
            title, description, _ = TOPICS[topic]
            nodes[topic] = {'id': topic, 'label': title, 'description': description,
                            'members': list(dict.fromkeys(members))}
    if pending:
        nodes['pending'] = {'id': 'pending', 'label': '待补分类 / pending',
            'description': 'Classification is incomplete. Keep these candidates available; no operation is ruled out.',
            'members': pending, 'always_retain': True}
    covered = {i for node in nodes.values() for i in node['members']}
    if covered != {r['id'] for r in rows}: raise ValueError('directory_coverage_lost')
    return {'policy': 'merged-task-catalog-v1', 'nodes': nodes,
            'candidate_count': len(rows), 'classified_count': len(rows)-len(pending),
            'pending_count': len(pending), 'source_directories': False,
            'plugin_internal_candidates': 0, 'final_confidence': .7}
