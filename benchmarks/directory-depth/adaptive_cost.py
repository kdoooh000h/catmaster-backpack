"""Cost candidate: shared scope text and a global, rather than branch, stop.

The existing adaptive experiment is an immutable comparison arm. This module
changes neither its tree nor any candidate's full final description.
"""
import adaptive_experiment as A


def directory(nodes, offered, task):
    scopes, questions = {}, {}
    for key in offered:
        description = nodes[key]['description']
        parent, separator, members = description.partition(' Subscopes (complete list): ')
        if separator:
            # Keep all words; write an identical ancestor scope only once.
            scope = next((name for name, value in scopes.items() if value == parent), None)
            if scope is None:
                scope = 'scope' + str(len(scopes))
                scopes[scope] = parent
            description = 'Context ' + scope + '; complete subscopes: ' + members
        questions[key] = {'type': 'noul',
            'instructions': 'Follow state.rules. Match this category: ' + description,
            'criteria': {'true': 'Directly supports a requested operation.',
                         'false': 'No requested operation matches.'}}
    state = {'task': task, 'rules': A.RULES}
    if scopes:
        state['scope_context'] = scopes
        state['rules'] += (' Shared scopes explain the context of subscopes. '
                           'Score only the listed subscopes, not other work in their parent scope.')
    return {'questions': questions}, state


def route(nodes, task, choices, question, call):
    active, traces, stagnant = ['n'], [], 0
    try:
        while True:
            pool = A.union(nodes, active)
            # A small individual branch is not a small aggregate final list.
            # Terminal branches are still kept whole, including later work.
            carry = [key for key in active if not nodes[key]['children']]
            offered = list(dict.fromkeys(child for key in active if key not in carry
                                         for child in nodes[key]['children']))
            final = A.final_spec(choices, pool, question)
            spec, state = directory(nodes, offered, task)
            reason = None
            if traces and len(pool) <= A.TARGET:
                reason = 'small_pool'
            elif traces and len(pool) <= 48 and A.estimate_chars(spec, state) >= .65 * A.estimate_chars(final, {'task': task}):
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
                        'confidence': confidence, 'stop_reason': reason, 'traces': traces,
                        'final_pool_size': len(pool)}
            if len(offered) > 96:
                return {'status': 'unavailable', 'reason': 'directory_limit', 'traces': traces}
            raw = call('directory-' + str(len(traces)), spec, state)
            picked = A.retained(raw, offered, nodes)
            active = list(dict.fromkeys(carry + picked))
            after = A.union(nodes, active)
            traces.append({'offered_count': len(offered), 'retained_count': len(picked),
                           'carried_count': len(carry), 'retained': picked, 'carried': carry,
                           'pool': sorted(after), 'answers': raw['answers']})
            if not active:
                return {'status': 'none', 'traces': traces}
            stagnant = stagnant + 1 if len(after) >= len(pool) else 0
            if stagnant >= 2 and len(after) > A.FINAL_LIMIT:
                return {'status': 'unavailable', 'reason': 'no_progress', 'traces': traces}
    except Exception as error:
        return {'status': 'unavailable', 'reason': str(error), 'traces': traces}
