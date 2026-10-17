"""Build a complete catalog organization, never a request relevance filter.

Vectors must be precomputed, normalized *catalog-only* vectors aligned with rows.
This module has no query, search, encoder, model, gold-answer or routing input.
Each supplied canonical ID (including a whole plugin) remains an indivisible row.
Cards are approximate metadata summaries; Jev must judge request relevance.
"""
from collections import Counter
import math
import re

import numpy as np


ROOT = 'n'
CARD_TARGET = 1200
_CAUTION = ('Scope cues are approximate; absent terms do not rule out members. '
            'Names and cues do not replace full descriptions, limitations or requirements.')
_STOP = frozenset('''a an and are as at be been by can for from has have how in
    into is it its of on or that the their these this to using use used when with
    you your skill skills tool tools plugin plugins capability capabilities
    provides support supports helps help create creating including includes
    based available designed tasks task'''.split())


def _row_ids(rows):
    ids = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'].strip():
            raise ValueError('every row needs a nonempty canonical id')
        ids.append(row['id'])
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate canonical ids')
    return ids


def _tokens(row):
    # Do not reuse topics, inherited classifications or query-derived labels.
    parts = [row.get('name', ''), row.get('description', '')]
    for field in ('publisher_labels', 'keywords', 'tags'):
        value = row.get(field, [])
        parts.extend(value if isinstance(value, list) else [value])
    text = ' '.join(part for part in parts if isinstance(part, str)).casefold()
    return {token for token in re.findall(r'[^\W_]+', text, flags=re.UNICODE)
            if 3 <= len(token) <= 40 and not token.isdecimal() and token not in _STOP}


def _split(indices, vectors):
    """Median partition along two deterministic farthest catalog anchors."""
    values = vectors[indices]
    # indices arrive in canonical-ID order, which breaks every exact tie.
    anchor_a = int(np.argmin(values @ values[0]))
    anchor_b = int(np.argmin(values @ values[anchor_a]))
    direction = values[anchor_b] - values[anchor_a]
    if np.any(direction):
        projection = values @ direction
        order = np.argsort(projection, kind='stable')
        midpoint = len(indices) // 2
        # Restore canonical order before the next split and tie break.
        return (np.sort(indices[order[:midpoint]]),
                np.sort(indices[order[midpoint:]]))
    midpoint = len(indices) // 2
    return indices[:midpoint], indices[midpoint:]


def _partition(indices, vectors, fanout):
    # Packing four binary levels produces at most 16 disjoint child scopes.
    groups = [indices]
    while len(groups) < fanout:
        eligible = [i for i, group in enumerate(groups) if len(group) > 1]
        if not eligible:
            break
        chosen = min(eligible, key=lambda i: (-len(groups[i]), i))
        left, right = _split(groups[chosen], vectors)
        groups[chosen:chosen + 1] = [left, right]
    return groups


def _scope(indices, token_sets, idf):
    counts = Counter(token for i in indices for token in token_sets[i])
    return sorted(counts, key=lambda token: (-counts[token] * idf[token] ** 2, token))[:8]


def _card(indices, rows, cues, children, child_cues):
    scope = ', '.join(cues) if cues else 'no textual cues available'
    prefix = f'{len(indices)} catalog rows. Approximate metadata cues: {scope}.'
    if children:
        labels = [child + ': ' + (', '.join(child_cues[child][:3]) or 'no textual cues')
                  for child in children]
        details = 'Direct child cues (all children; approximate): ' + '; '.join(labels) + '.'
    else:
        names = []
        for i in indices:
            name = rows[i].get('name')
            names.append(name if isinstance(name, str) and name.strip() else rows[i]['id'])
        duplicated_names = {name for name, count in Counter(names).items() if count > 1}
        labels = [f'{name} [{rows[i]["id"]}]' if name in duplicated_names else name
                  for i, name in zip(indices, names)]
        details = 'All member names (not full descriptions): ' + ('; '.join(labels) or '(empty catalog)') + '.'
    # This is a size target, never a silent name/requirement truncation rule.
    return prefix + ' ' + details + ' ' + _CAUTION


def build(rows, vectors, fanout=16, leaf_size=24):
    """Return nodes keyed by ID, with root ``n`` and depth starting at zero.

    ``vectors[i]`` must describe ``rows[i]`` and have unit L2 norm. Zero/missing,
    nonfinite and unnormalized vectors fail explicitly; no row is discarded.
    Input order is immaterial when vectors are reordered together with rows.
    Equal vectors use deterministic canonical-ID median splits. This function
    only organizes already canonicalized rows and rejects duplicate IDs.
    """
    if isinstance(fanout, bool) or not isinstance(fanout, int) or fanout < 2:
        raise ValueError('fanout must be an integer of at least two')
    if isinstance(leaf_size, bool) or not isinstance(leaf_size, int) or leaf_size < 1:
        raise ValueError('leaf_size must be a positive integer')
    rows = list(rows)
    ids = _row_ids(rows)
    try:
        vectors = np.asarray(vectors)
        if vectors.dtype.kind not in 'fiu':
            raise ValueError('vectors must be numeric')
        if vectors.ndim != 2 or vectors.shape[0] != len(rows) or vectors.shape[1] == 0:
            raise ValueError('vectors must be a nonempty-dimension matrix aligned with rows')
        if not np.isfinite(vectors).all():
            raise ValueError('vectors must be finite')
        # Float64 prevents integer overflow and validates supplied float32 caches.
        vectors = vectors.astype(np.float64, copy=False)
        norms = np.linalg.norm(vectors, axis=1)
        if not np.allclose(norms, 1.0, rtol=1e-4, atol=1e-5):
            raise ValueError('vectors must be normalized and nonzero')
    except (TypeError, OverflowError) as exc:
        raise ValueError('invalid catalog vectors') from exc
    order = sorted(range(len(rows)), key=ids.__getitem__)
    rows = [rows[i] for i in order]
    vectors = vectors[order]
    token_sets = [_tokens(row) for row in rows]
    frequencies = Counter(token for tokens in token_sets for token in tokens)
    idf = {token: math.log((len(rows) + 1) / (count + 1)) + 1
           for token, count in frequencies.items()}
    nodes = {}
    scopes = {}

    def visit(indices, node_id, depth):
        node = {'id': node_id, 'depth': depth,
                'members': [rows[i]['id'] for i in indices], 'children': [],
                'description': ''}
        nodes[node_id] = node
        scopes[node_id] = _scope(indices, token_sets, idf)
        if len(indices) > leaf_size:
            for i, group in enumerate(_partition(indices, vectors, fanout)):
                child_id = f'{node_id}.{i:02d}'
                node['children'].append(child_id)
                visit(group, child_id, depth + 1)
        node['description'] = _card(indices, rows, scopes[node_id], node['children'], scopes)

    visit(np.arange(len(rows)), ROOT, 0)
    validate(nodes, rows, fanout=fanout, leaf_size=leaf_size)
    return nodes


def stats(nodes):
    """Summarize stored organization, without relevance or coverage claims."""
    leaves = [node for node in nodes.values() if not node['children']]
    return {'node_count': len(nodes), 'candidate_count': len(nodes[ROOT]['members']),
            'leaf_count': len(leaves),
            'max_depth': max(node['depth'] for node in nodes.values()),
            'max_fanout': max(len(node['children']) for node in nodes.values()),
            'min_leaf_size': min(len(node['members']) for node in leaves),
            'max_leaf_size': max(len(node['members']) for node in leaves),
            'max_card_chars': max(len(node['description']) for node in nodes.values()),
            'cards_over_target': sum(len(node['description']) > CARD_TARGET for node in nodes.values())}


def validate(nodes, rows, fanout=16, leaf_size=24):
    """Raise ValueError for lost/duplicated rows or a malformed partition tree."""
    expected = set(_row_ids(rows))
    if ROOT not in nodes or set(nodes[ROOT]['members']) != expected:
        raise ValueError('root must contain exactly every canonical id')
    seen = set()

    def visit(node_id, depth):
        if node_id in seen or node_id not in nodes:
            raise ValueError('child missing, repeated, or cyclic')
        seen.add(node_id)
        node = nodes[node_id]
        members = node['members']
        if node['id'] != node_id or node['depth'] != depth:
            raise ValueError('node identity or depth mismatch')
        if len(members) != len(set(members)) or not set(members) <= expected:
            raise ValueError('duplicated or foreign canonical ids')
        if not isinstance(node['description'], str):
            raise ValueError('invalid directory card')
        children = node['children']
        if children:
            if not 2 <= len(children) <= fanout:
                raise ValueError('invalid child fanout')
            combined = []
            for child in children:
                visit(child, depth + 1)
                if not nodes[child]['members']:
                    raise ValueError('empty child')
                combined.extend(nodes[child]['members'])
            if len(combined) != len(set(combined)) or set(combined) != set(members):
                raise ValueError('children must be an exact disjoint union of parent')
        elif len(members) > leaf_size:
            raise ValueError('leaf exceeds leaf_size')

    visit(ROOT, 0)
    if seen != set(nodes):
        raise ValueError('unreachable nodes')
    return stats(nodes)
