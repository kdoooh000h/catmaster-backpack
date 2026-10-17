"""Keep current-step selection while isolating description and cost-stop effects."""
from copy import deepcopy
import current_step as C
import adaptive_early_stop as E


def select(arm, nodes, task, choices, question, call):
    if arm in {'baseline', 'described'}:
        return C.select('current_step', nodes, task, choices, question, call)
    if arm != 'early_stop': raise ValueError('unknown_arm')
    if not question.startswith(C.ORIGINAL_LEAD): raise ValueError('unknown_final_question')
    def dispatch(stage, spec, state):
        if stage == 'final':
            spec = deepcopy(spec)
            spec['questions']['answer']['instructions'] = C.CURRENT_LEAD + question[len(C.ORIGINAL_LEAD):]
        return call(stage, spec, state)
    return E.route(nodes, 'adaptive', task, choices, question, dispatch, reading_cost_ratio=.35)
