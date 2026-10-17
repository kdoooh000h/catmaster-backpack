"""Experimental count/gap gates; independent Noul probabilities are not mass.

Keep early recall gates and final Choice confidence unchanged. A raised gate is
only a hypothesis about precision, never evidence that discarded work is safe.
"""
from copy import deepcopy

import adaptive_experiment as A
import current_step as C

MIN_GAP = .12
MAX_RAISE = .10
PRESSURE_LIMIT = 96
ARMS = ['baseline', 'adaptive_gate', 'adaptive_focus']


def retention(raw, offered, carried, nodes):
    picked = A.retained(raw, offered, nodes)  # Validate every original answer.
    gates = {depth: A.gate(depth) for depth in {nodes[k]['depth'] for k in offered}}
    initial = len(A.union(nodes, carried + picked))
    changes = []
    for depth in sorted(gates):
        if depth < 3 or len(A.union(nodes, carried + picked)) <= PRESSURE_LIMIT:
            continue
        group = [k for k in picked if nodes[k]['depth'] == depth]
        values = sorted({raw['answers'][k]['noul'] for k in group})
        candidates = []
        for low, high in zip(values, values[1:]):
            threshold = min((low + high) / 2, A.gate(depth) + MAX_RAISE)
            if high - low + 1e-12 < MIN_GAP or not low < threshold <= high:
                continue
            kept = [k for k in picked if k not in group or raw['answers'][k]['noul'] >= threshold]
            size = len(A.union(nodes, carried + kept))
            if size < len(A.union(nodes, carried + picked)):
                candidates.append((threshold, size, kept, low, high))
        if not candidates:
            continue
        fits = [item for item in candidates if item[1] <= PRESSURE_LIMIT]
        chosen = min(fits, key=lambda item: item[0]) if fits else min(candidates, key=lambda item: (item[1], item[0]))
        threshold, size, kept, low, high = chosen
        changes.append({'depth': depth, 'base': gates[depth], 'applied': threshold,
                        'gap': [low, high], 'removed': [k for k in picked if k not in kept],
                        'pool_after': size})
        gates[depth], picked = threshold, kept
    return picked, {'base_pool': initial, 'applied_gates': gates, 'changes': changes}


def focused_specification(nodes, offered):
    return {'questions': {key: {
        'type': 'noul',
        'instructions': {
            'question': 'Does this scope directly cover at least one concrete operation required in `task`? Follow `rules`. Judge the requested action and deliverable, not similarity of business domain, vocabulary or tools.',
            'scope': nodes[key]['description'],
        },
        'criteria': {'true': 'A capability in this scope directly performs a mandatory current or later operation.',
                     'false': 'Only background, adjacent expertise, a possible downstream use, or cancelled/quoted/unrequested work.'}
    } for key in offered}}


def select(arm, nodes, task, choices, question, call):
    if arm == 'baseline':
        return C.select('current_step', nodes, task, choices, question, call)
    if arm not in ARMS:
        raise ValueError('unknown_arm')
    if not question.startswith(C.ORIGINAL_LEAD):
        raise ValueError('unknown_final_question')
    def dispatch(stage, spec, state):
        if stage == 'final':
            spec = deepcopy(spec)
            spec['questions']['answer']['instructions'] = C.CURRENT_LEAD + question[len(C.ORIGINAL_LEAD):]
        return call(stage, spec, state)
    return route(nodes, task, choices, question, dispatch, focus=arm == 'adaptive_focus')


def route(nodes, task, choices, question, call, *, focus=False):
    active, traces, stagnant = ['n'], [], 0
    state = {'task': task, 'rules': A.RULES}
    try:
        while True:
            pool = A.union(nodes, active)
            carry = [k for k in active if not nodes[k]['children'] or
                     (k != 'n' and len(nodes[k]['members']) <= A.CARRY_LIMIT)]
            offered = list(dict.fromkeys(child for k in active if k not in carry for child in nodes[k]['children']))
            final = A.final_spec(choices, pool, question)
            # Keep the old estimator even for focused questions: this ablation
            # changes only the dispatched Noul question, not the stopping rule.
            directory = A.specification(nodes, offered)
            reason = None
            if traces and len(pool) <= A.TARGET:
                reason = 'small_pool'
            elif traces and len(pool) <= 48 and A.estimate_chars(directory, state) >= .65 * A.estimate_chars(final, {'task': task}):
                reason = 'estimated_reading_cost'
            elif not offered:
                reason = 'terminal_categories'
            elif len(traces) >= A.MAX_ROUNDS:
                reason = 'round_limit'
            if reason:
                if len(pool) > A.FINAL_LIMIT:
                    return {'status': 'unavailable', 'reason': 'final_limit', 'traces': traces}
                raw = call('final', final, {'task': task})
                answer = raw.get('answers', {}).get('answer') if isinstance(raw, dict) else None
                if not isinstance(answer, dict) or answer.get('type') != 'choice':
                    raise ValueError('invalid_final_answer')
                key, confidence = answer.get('choice'), answer.get('confidence')
                if key not in final['questions']['answer']['criteria'] or not A.probability(confidence):
                    raise ValueError('invalid_final_answer')
                status = 'abstain' if confidence < A.FINAL_GATE else ('none' if key == 'none' else 'selected')
                return {'status': status, 'choice': key if status != 'abstain' else None,
                        'confidence': confidence, 'stop_reason': reason, 'traces': traces, 'final_pool_size': len(pool)}
            if len(offered) > 96:
                return {'status': 'unavailable', 'reason': 'directory_limit', 'traces': traces}
            raw = call('directory-' + str(len(traces)), focused_specification(nodes, offered) if focus else directory, state)
            picked, adjustment = retention(raw, offered, carry, nodes)
            active = list(dict.fromkeys(carry + picked))
            after = A.union(nodes, active)
            traces.append({'offered_count': len(offered), 'retained_count': len(picked),
                           'carried_count': len(carry), 'retained': picked, 'carried': carry,
                           'pool': sorted(after), 'answers': raw['answers'], 'threshold_adjustment': adjustment})
            if not active:
                return {'status': 'none', 'traces': traces}
            stagnant = stagnant + 1 if len(after) >= len(pool) else 0
            if stagnant >= 2 and len(after) > A.FINAL_LIMIT:
                return {'status': 'unavailable', 'reason': 'no_progress', 'traces': traces}
    except Exception as error:
        return {'status': 'unavailable', 'reason': str(error), 'traces': traces}
