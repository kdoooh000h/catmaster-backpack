"""One typed current-step choice; retain the complete recalled pool for later."""
from conditional_experiment import final_spec
from current_step import CURRENT_LEAD, ORIGINAL_LEAD
from experiment import probability

ARMS = ['conditional_baseline', 'conditional_current']
FINAL_GATE = .7


def specification(arm, rows, pool, question):
    if arm not in ARMS:
        raise ValueError('unknown_arm')
    spec = final_spec(rows, pool, question)
    if arm == 'conditional_current':
        if not question.startswith(ORIGINAL_LEAD):
            raise ValueError('unknown_final_question')
        spec['questions']['answer']['instructions'] = CURRENT_LEAD + question[len(ORIGINAL_LEAD):]
    return spec


def select(arm, rows, pool, question, need, call):
    if not pool or len(pool) > 96 or len(set(pool)) != len(pool):
        raise ValueError('invalid_recalled_pool')
    spec = specification(arm, rows, pool, question)
    options = spec['questions']['answer']['criteria']
    if set(options) != set(pool) | {'none'}:
        raise ValueError('unknown_candidate_id')
    # No extractor, rewriter, second question, intermediate pruning or retry.
    raw = call('final', spec, {'task': need})
    answers = raw.get('answers') if isinstance(raw, dict) else None
    if not isinstance(answers, dict) or set(answers) != {'answer'}:
        raise ValueError('invalid_answer_map')
    answer = answers['answer']
    if (not isinstance(answer, dict) or answer.get('type') != 'choice'
            or answer.get('choice') not in options or not probability(answer.get('confidence'))):
        raise ValueError('invalid_final_answer')
    score, chosen = answer['confidence'], answer['choice']
    return {'status': 'abstain' if score < FINAL_GATE else 'none' if chosen == 'none' else 'selected',
            'choice': chosen if score >= FINAL_GATE else None, 'confidence': score,
            'raw_choice': chosen, 'retained_candidates': list(pool),
            'traces': [{'stage': 'conditional_recall', 'pool': sorted(pool)}],
            'final_pool_size': len(pool)}
