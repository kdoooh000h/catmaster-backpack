"""Lazily classify authored children when a selected directory union exceeds 128.

This helper uses catalog metadata only. The caller supplies the existing complete
taxonomy and membership tree; root memberships are never classified again.
"""
from copy import deepcopy

import jev_taxonomy_build as B


UNION_LIMIT = 128


def prepare(rows, nodes, assignments, roots_spec, selected_root_ids, call,
            batch_size=32, *, max_payload_bytes=B.MAX_PAYLOAD_BYTES):
    """Return copied tree state and leaf-call receipts for selected deferred roots.

    ``selected_root_ids`` contains authored taxonomy keys and optionally
    ``B.UNKNOWN`` (``n.unknown``). All selected directories contribute unique
    members to the union, including previously split roots and global unknown.
    Only selected terminal, deferred authored roots are eligible for refinement.
    Callback failures or invalid answers propagate without retry.
    """
    if (type(batch_size) is not int or not 1 <= batch_size <= 32
            or type(max_payload_bytes) is not int or max_payload_bytes < 1
            or not callable(call)):
        raise ValueError('invalid_refinement_limit_or_callback')
    rows = list(rows)
    ids = B._row_ids(rows)
    roots = B._taxonomy(roots_spec)
    B.validate(nodes, rows)
    if not isinstance(assignments, dict) or set(assignments) != set(ids):
        raise ValueError('invalid_refinement_assignments')
    selected = set(selected_root_ids)
    if not selected <= set(roots) | {B.UNKNOWN}:
        raise ValueError('unknown_selected_root')
    union = set()
    for root in selected:
        node = nodes.get(B.UNKNOWN if root == B.UNKNOWN else B._root_id(root))
        if node:
            union.update(node['members'])
    split_roots = [root for root in roots
                   if nodes.get(B._root_id(root), {}).get('classification_split') is True]
    refined = [root for root in roots if root in selected
               and nodes.get(B._root_id(root), {}).get('classification_split') is False
               and not nodes[B._root_id(root)]['children']
               and any(root in assignment['deferred_roots']
                       for assignment in assignments.values())] if len(union) > UNION_LIMIT else []
    result = {'nodes': deepcopy(nodes), 'assignments': deepcopy(assignments), 'calls': [],
              'split_roots': split_roots, 'refined_roots': refined,
              'selected_union_count': len(union)}
    if not refined:
        return result

    updated = result['assignments']
    ordered = sorted(rows, key=lambda row: row['id'])
    local = {f'c{index}': row['id'] for index, row in enumerate(ordered, 1)}
    items = [(alias, root) for alias, key in local.items() for root in refined
             if root in updated[key]['supported_roots']]
    needed = {alias for alias, _ in items}
    candidates = {alias: B._candidate(row) for alias, row in zip(local, ordered)
                  if alias in needed}
    for index, (spec, state, mapping) in enumerate(B._batches(
            'leaf', items, batch_size, candidates, roots, max_payload_bytes), 1):
        stage = f'union-leaf-{index}'
        raw = call(stage, spec, state)
        answers = B._answers(raw, spec)
        result['calls'].append({'stage': stage, 'spec': deepcopy(spec),
                                'state': deepcopy(state), 'answer': deepcopy(raw)})
        for wire, (alias, root) in mapping.items():
            assignment, answer = updated[local[alias]], answers[wire]
            assignment['leaf'][root] = answer
            assignment['leaves'][root] = [answer['choice']]
            if answer['confidence'] < B.FALLBACK_GATE:
                assignment['uncertain'] = True
                if B.UNRESOLVED_LEAF not in assignment['leaves'][root]:
                    assignment['leaves'][root].append(B.UNRESOLVED_LEAF)
    for assignment in updated.values():
        assignment['deferred_roots'] = [root for root in assignment['deferred_roots']
                                        if root not in refined]
    result['split_roots'] = [root for root in roots if root in split_roots or root in refined]
    result['nodes'] = B._build(roots, updated, ids, result['split_roots'])
    B.validate(result['nodes'], rows)
    return result
