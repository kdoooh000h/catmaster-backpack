"""Two-level Jev selection over a caller-supplied capability directory.

This module only selects; it never acquires, executes, or authorizes a capability.
Providers implement ``noul(spec, state)`` and ``choose(question, state, choices)``.
Each method is invoked at most once per stage, without retries or fallback.
The provider owns transport policy and in-flight timeouts. ``deadline`` is an
absolute value on ``clock`` (monotonic by default), checked around every call.

The returned choice is private routing data. Only ``diagnostics`` is intended
for public reporting: it contains fixed codes and counts, never input text,
node/capability IDs, raw responses, or exception messages. Nothing is persisted.
"""

from collections.abc import Mapping
from copy import deepcopy
import json
import math
import time

if __package__:
    from .public_capability_directory import PublicCapabilityDirectory
else:
    from public_capability_directory import PublicCapabilityDirectory


RETENTION_PROBABILITY = 0.20
FINAL_CONFIDENCE_GATE = 0.60
FINAL_CANDIDATE_LIMIT = 96

_INSTRUCTIONS = (
    'Assess whether this directory contains a specialist workflow that directly performs '
    'at least one explicitly requested operation or deliverable in the original unchanged task, '
    'including mandatory later actions. Merely related background domain, hypothetical helpfulness, '
    'or adding unrequested planning, governance, or documentation tasks is insufficient. '
    'Quoted text, translation subjects, '
    'hypothetical mentions, explicitly cancelled actions, actions explicitly not requested now or later, '
    'and possible future tasks without a current instruction to perform them are data, not required actions. '
    'Do not restrict the required operations to the first or immediately executable step. '
    'Multiple cards may each contain a directly required specialist workflow. Evaluate this card: '
)
_CRITERIA = {
    'true': 'Contains a specialist workflow that directly performs an explicitly requested operation or deliverable, including a mandatory later action.',
    'false': 'Contains no directly requested specialist workflow; merely related background, hypothetical helpfulness, unrequested additional tasks, data, cancelled action, or future possibility without a current instruction.',
}


class _InvalidResponse(Exception):
    pass


class _DeadlineExceeded(Exception):
    pass


def _probability(value):
    # bool is an int subclass; it is not a typed probability. Check the range
    # first so even enormous out-of-range integers cannot overflow isfinite.
    return type(value) in (int, float) and 0 <= value <= 1 and math.isfinite(value)


def _noul_spec(directory, ids):
    return {'questions': {
        card['id']: {
            'type': 'noul',
            'instructions': _INSTRUCTIONS + json.dumps(card, ensure_ascii=False),
            'criteria': dict(_CRITERIA),
        }
        for card in directory.cards(ids)
    }}


def _retained(raw, ids):
    answers = raw.get('answers') if isinstance(raw, Mapping) else None
    if not isinstance(answers, Mapping) or set(answers) != set(ids):
        raise _InvalidResponse
    retained = []
    for key in ids:
        answer = answers[key]
        value = answer.get('noul') if isinstance(answer, Mapping) else None
        if (not isinstance(answer, Mapping) or answer.get('type') != 'noul'
                or not _probability(value)):
            raise _InvalidResponse
        if value >= RETENTION_PROBABILITY:
            retained.append(key)
    return retained


def _choice_fields(raw, pool):
    if isinstance(raw, Mapping):
        if raw.get('type') != 'choice':
            raise _InvalidResponse
        choice, confidence = raw.get('choice'), raw.get('confidence')
    else:
        if getattr(raw, 'type', 'choice') != 'choice':
            raise _InvalidResponse
        choice, confidence = getattr(raw, 'choice', None), getattr(raw, 'confidence', None)
    if not isinstance(choice, str) or choice not in pool or not _probability(confidence):
        raise _InvalidResponse
    return choice, confidence


def select_hierarchical(directory, question, state, provider, *, deadline=None,
                        clock=time.monotonic):
    """Select from retained roots/leaves and an exact subset of original choices.

    ``directory`` must be a validated ``PublicCapabilityDirectory`` (two levels;
    no third-level traversal). ``state`` and the original question are passed
    unchanged to every provider stage, using independent copies of state.
    A selected union covering the entire catalog abstains rather than issuing
    a global Choice. The limit of 96 counts capabilities, excluding ``none``.

    Returns ``status`` (selected/none/abstain/error), ``choice``, ``confidence``,
    and public ``diagnostics``. Only a valid final response at confidence >=.60
    produces a choice; explicit final ``none`` is distinct from abstention.
    Choice mappings require ``type='choice'``; an already validated runtime
    Answer object may supply choice/confidence attributes instead. A valid
    below-gate response retains its numeric confidence, with no choice.
    A late provider response is discarded, without retrying its unknown effects.
    """
    diagnostics = {'stage': 'input', 'reason': None, 'provider_calls': 0,
                   'root_count': 0, 'retained_root_count': 0,
                   'leaf_count': 0, 'retained_leaf_count': 0,
                   'candidate_count': 0}

    def result(status, reason, choice=None, confidence=None):
        diagnostics['reason'] = reason
        return {'status': status, 'choice': choice, 'confidence': confidence,
                'diagnostics': dict(diagnostics)}

    if not isinstance(directory, PublicCapabilityDirectory):
        return result('error', 'invalid_directory')
    if not isinstance(question, str) or not question.strip():
        return result('error', 'missing_question')
    if not isinstance(state, Mapping):
        return result('error', 'invalid_state')
    if (deadline is not None and
            (type(deadline) not in (int, float) or
             (type(deadline) is float and not math.isfinite(deadline)))):
        return result('error', 'invalid_deadline')
    if not callable(clock):
        return result('error', 'invalid_clock')
    try:
        noul_method, choose_method = getattr(provider, 'noul', None), getattr(provider, 'choose', None)
    except Exception:
        return result('error', 'invalid_provider')
    if not callable(noul_method) or not callable(choose_method):
        return result('error', 'invalid_provider')

    def check_deadline():
        if deadline is not None and clock() >= deadline:
            raise _DeadlineExceeded

    def call(stage, method, *args):
        diagnostics['stage'] = stage
        check_deadline()
        diagnostics['provider_calls'] += 1
        raw = method(*args)
        check_deadline()
        return raw

    try:
        # Freeze caller-owned inputs; a provider may mutate its argument copies.
        directory = deepcopy(directory)
        original_state = deepcopy(state)
        roots = list(directory.root_ids)
        diagnostics['root_count'] = len(roots)
        selected_roots = _retained(call('roots', noul_method,
            _noul_spec(directory, roots), deepcopy(original_state)), roots)
        diagnostics['retained_root_count'] = len(selected_roots)
        if not selected_roots:
            return result('abstain', 'no_roots')

        children = {leaf for root in selected_roots for leaf in directory.children(root)}
        leaves = [leaf for leaf in directory.leaf_ids if leaf in children]
        diagnostics['leaf_count'] = len(leaves)
        selected_leaves = _retained(call('leaves', noul_method,
            _noul_spec(directory, leaves), deepcopy(original_state)), leaves)
        diagnostics['retained_leaf_count'] = len(selected_leaves)
        if not selected_leaves:
            return result('abstain', 'no_leaves')

        pool = directory.subset(selected_leaves)
        diagnostics['candidate_count'] = len(pool) - 1
        if diagnostics['candidate_count'] > FINAL_CANDIDATE_LIMIT:
            return result('abstain', 'candidate_limit_exceeded')
        if directory.members(selected_leaves) == directory.members(roots):
            return result('abstain', 'full_catalog_retained')

        choice, confidence = _choice_fields(call('final', choose_method,
            question, deepcopy(original_state), deepcopy(pool)), pool)
        if confidence < FINAL_CONFIDENCE_GATE:
            return result('abstain', 'final_confidence_below_gate', confidence=confidence)
        return result('none' if choice == 'none' else 'selected', 'final_choice', choice, confidence)
    except _DeadlineExceeded:
        return result('abstain', 'deadline_exceeded')
    except _InvalidResponse:
        return result('error', 'invalid_provider_response')
    except TimeoutError:
        return result('error', 'provider_timeout')
    except Exception:
        # Do not leak exception strings, class names, raw replies, or IDs.
        return result('error', 'routing_failed')
