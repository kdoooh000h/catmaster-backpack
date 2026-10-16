"""Prioritize the current step only at final dispatch; preserve later candidates."""
from copy import deepcopy

import adaptive_experiment as A

ORIGINAL_LEAD = 'Which one supplied Skill best matches the concrete work requested in state.task? '
CURRENT_LEAD = (
    'Which one supplied Skill best supports the step to perform NOW in state.task? '
    'For multiple required steps, identify the next step from the explicit current focus '
    'or stated execution order, not mere mention order. Compare candidates for that step, '
    'rather than the entire workflow. A Skill useful only for a required later step '
    'remains available for later; do not select it for the current step. '
    'If no step is prioritized, evaluate the immediate work as stated without inventing an order. ')


def select(arm, nodes, task, choices, question, call):
    if arm not in {'slim', 'current_step'}:
        raise ValueError('unknown_arm')
    if not question.startswith(ORIGINAL_LEAD):
        raise ValueError('unknown_final_question')

    def dispatch(stage, spec, state):
        if arm == 'current_step' and stage == 'final':
            spec = deepcopy(spec)
            spec['questions']['answer']['instructions'] = CURRENT_LEAD + question[len(ORIGINAL_LEAD):]
        return call(stage, spec, state)

    # Keep the original question in the reading-cost estimator, so the prompt
    # change cannot itself alter directory depth, stopping or candidate coverage.
    return A.route(nodes, 'adaptive', task, choices, question, dispatch)
