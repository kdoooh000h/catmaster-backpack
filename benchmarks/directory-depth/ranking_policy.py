"""Experimental ranking preferences, never task-fit scores or authorization.

Only a reviewed equivalence set may collapse alternate implementations. Ordinary
topic/category membership is insufficient. Unknown or incomparable measurements
retain their original visibility. All alternatives remain addressable.
"""
import math

FINAL_GATE = .7


def valid_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def metric(row, field, now, max_age):
    value = row.get(field)
    if not isinstance(value, dict): return None
    required = ('board', 'metric', 'window', 'at', 'value')
    if any(k not in value for k in required): return None
    if any(not isinstance(value[k], str) or not value[k] for k in ('board', 'metric', 'window')): return None
    if not valid_number(value['value']) or not valid_number(value['at']): return None
    if not 0 <= now - value['at'] <= max_age: return None
    if field == 'rank' and (type(value['value']) is not int or value['value'] < 1): return None
    return value


def preferences(rows, equivalence_groups, *, now, max_age=86400):
    """Group metadata must be independently reviewed before passing it here.

    A common timestamp/window/board is mandatory for comparisons. Rank is lower
    first; growth is higher first and chooses backup.
    No attempt to compare rank 1 from one market with rank 2 from another.
    """
    by_id = {r['id']: r for r in rows}
    if len(by_id) != len(rows): raise ValueError('duplicate_ids')
    consumed, groups = set(), []
    for group in equivalence_groups:
        ids = group.get('members', [])
        if not group.get('evidence') or not group.get('operation_contract'):
            raise ValueError('equivalence_evidence_required')
        if len(set(ids)) != len(ids) or len(ids) < 2 or not set(ids) <= by_id.keys():
            raise ValueError('invalid_equivalence_members')
        if consumed.intersection(ids): raise ValueError('overlapping_equivalence_groups')
        members = [by_id[i] for i in ids]
        if len({(r['kind'], r.get('mode')) for r in members}) != 1:
            raise ValueError('mixed_execution_contracts')
        consumed.update(ids)
        comparable, unknown = {}, []
        for row in members:
            rank = metric(row, 'rank', now, max_age)
            if rank is None:
                unknown.append(row['id']); continue
            board = tuple(rank[k] for k in ('board', 'metric', 'window', 'at'))
            comparable.setdefault(board, []).append(row)
        for board, bucket in comparable.items():
            # Stable ties avoid fabricating precision across unrelated signals.
            ordered = sorted(bucket, key=lambda row: metric(row, 'rank', now, max_age)['value'])
            primary, others = ordered[0], ordered[1:]
            growth = [(row, metric(row, 'growth', now, max_age)) for row in others]
            growth = [(row, m) for row, m in growth if m is not None and m['board'] == board[0]]
            growth_boards = {tuple(m[k] for k in ('board', 'metric', 'window', 'at')) for _, m in growth}
            backup = max(growth, key=lambda pair: pair[1]['value'])[0] if len(growth_boards) == 1 and growth else None
            # A missing/incomparable growth measurement cannot become zero.
            # Keep those members visible; only proven comparable alternates can
            # move behind the chosen representative.
            known_growth = {row['id'] for row, _ in growth} if len(growth_boards) == 1 else set()
            visible = [primary['id']] + ([backup['id']] if backup else [])
            visible += [r['id'] for r in others if r['id'] not in known_growth and r['id'] not in visible]
            groups.append({'contract': group['operation_contract'], 'evidence': group['evidence'],
                           'primary': primary['id'], 'backup': backup['id'] if backup else None,
                           'visible': visible, 'all_members': [r['id'] for r in bucket],
                           'ranking_board': list(board)})
        for identifier in unknown:
            groups.append({'primary': identifier, 'backup': None, 'visible': [identifier],
                           'all_members': [identifier], 'reason': 'rank_unknown_or_stale'})
    for row in rows:
        if row['id'] not in consumed:
            groups.append({'primary': row['id'], 'backup': None, 'visible': [row['id']],
                           'all_members': [row['id']], 'reason': 'no_verified_equivalence'})
    if sorted(i for g in groups for i in g['all_members']) != sorted(by_id):
        raise ValueError('membership_not_preserved')
    return {'groups': groups, 'visible_ids': [i for g in groups for i in g['visible']],
            'all_ids': [r['id'] for r in rows], 'minimum_final_confidence': FINAL_GATE,
            'selected': None, 'execution': 'not_performed'}


def accept_choice(answer, offered):
    """Rank never supplies or raises Jev's final fit confidence."""
    confidence = answer.get('confidence')
    if not valid_number(confidence) or not 0 <= confidence <= 1 or answer.get('choice') not in offered:
        raise ValueError('invalid_final_answer')
    return answer['choice'] if confidence >= FINAL_GATE else None
