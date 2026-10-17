"""Frozen adaptive traversal with an isolated earlier cost stop.

Fork of adaptive_experiment.route with only a configurable reading-cost ratio.
The .65 setting must reproduce the original under identical observed answers.
Stopping keeps the whole current pool; no confidence gate or candidate is changed.
"""
from adaptive_experiment import (
    ARMS, FINAL_GATE, FINAL_LIMIT, TARGET, CARRY_LIMIT, MAX_ROUNDS, RULES,
    union, specification, final_spec, estimate_chars, retained, probability)


def route(nodes, mode, task, choices, question, call, *, reading_cost_ratio=.35):
    if not 0 < reading_cost_ratio <= 1:
        raise ValueError('invalid_reading_cost_ratio')
    if mode not in ARMS:
        raise ValueError('unknown_arm')
    active, traces = ['n'], []
    state = {'task': task, 'rules': RULES}
    stagnant = 0
    try:
        while True:
            pool = union(nodes, active)
            carry = [key for key in active if not nodes[key]['children'] or
                     (mode == 'adaptive' and key != 'n' and len(nodes[key]['members']) <= CARRY_LIMIT)]
            offered = list(dict.fromkeys(child for key in active if key not in carry for child in nodes[key]['children']))
            final = final_spec(choices, pool, question)
            directory = specification(nodes, offered)
            reason = None
            if traces and mode == 'fixed2' and len(traces) >= 2:
                reason = 'fixed_depth'
            elif traces and mode == 'adaptive' and len(pool) <= TARGET:
                reason = 'small_pool'
            elif traces and mode == 'adaptive' and len(pool) <= 48 and estimate_chars(directory, state) >= reading_cost_ratio * estimate_chars(final, {'task': task}):
                reason = 'estimated_reading_cost'
            elif not offered:
                reason = 'terminal_categories'
            elif len(traces) >= MAX_ROUNDS:
                reason = 'round_limit'
            if reason:
                if len(pool) > FINAL_LIMIT:
                    return {'status': 'unavailable', 'reason': 'final_limit', 'traces': traces}
                raw = call('final', final, {'task': task})
                answer = raw.get('answers', {}).get('answer') if isinstance(raw, dict) else None
                if not isinstance(answer, dict) or answer.get('type') != 'choice':
                    raise ValueError('invalid_final_answer')
                key, confidence = answer.get('choice'), answer.get('confidence')
                if key not in final['questions']['answer']['criteria'] or not probability(confidence):
                    raise ValueError('invalid_final_answer')
                status = 'abstain' if confidence < FINAL_GATE else ('none' if key == 'none' else 'selected')
                return {'status': status, 'choice': key if status != 'abstain' else None,
                        'confidence': confidence, 'stop_reason': reason, 'traces': traces, 'final_pool_size': len(pool)}
            if len(offered) > 96:
                return {'status': 'unavailable', 'reason': 'directory_limit', 'traces': traces}
            raw = call('directory-' + str(len(traces)), directory, state)
            picked = retained(raw, offered, nodes)
            active = list(dict.fromkeys(carry + picked))
            after = union(nodes, active)
            traces.append({'offered_count': len(offered), 'retained_count': len(picked),
                'carried_count': len(carry), 'retained': picked, 'carried': carry,
                'pool': sorted(after), 'answers': raw['answers']})
            if not active:
                return {'status': 'none', 'traces': traces}
            stagnant = stagnant + 1 if len(after) >= len(pool) else 0
            if stagnant >= 2 and len(after) > FINAL_LIMIT:
                return {'status': 'unavailable', 'reason': 'no_progress', 'traces': traces}
    except Exception as error:
        return {'status': 'unavailable', 'reason': str(error), 'traces': traces}


