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
    'Does this card contain executable tools/resources or guidance for directly performing '
    'any operation or deliverable explicitly required by the original unchanged task, '
    'including mandatory later actions? Multiple cards may match; do not restrict matches '
    'to the first or immediately executable step. Exclude related background, hypothetical '
    'helpfulness, and unrequested planning/governance/documentation. Treat quotations, '
    'translation subjects, hypothetical '
    'mentions, cancelled or explicitly unrequested actions, and future possibilities without '
    'a current instruction as data, not required actions. Card: '
)
_CRITERIA = {
    'true': 'Contains tools/resources or guidance for a directly required operation or deliverable, including a mandatory later action.',
    'false': 'Contains no directly required tool/resource or guidance; only related background, hypothetical help, added tasks, or data.',
}


class _InvalidResponse(Exception):
    pass


class _InvalidCandidateFilter(Exception):
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


def _retained(raw, ids, gate):
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
        if value >= gate:
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


def _filtered_pool(pool, candidate_filter):
    try:
        filtered = candidate_filter(deepcopy(pool))
        if not isinstance(filtered, Mapping):
            raise _InvalidCandidateFilter
        filtered = dict(filtered)
        if ('none' not in filtered or not set(filtered) <= set(pool)
                or any(value != pool[key] for key, value in filtered.items())):
            raise _InvalidCandidateFilter
        # Use original values/order, never filter-owned objects. The filter can
        # remove candidates, but cannot introduce or alter routing identities.
        return {key: deepcopy(value) for key, value in pool.items() if key in filtered}
    except Exception:
        raise _InvalidCandidateFilter from None


def select_hierarchical(directory, question, state, provider, *, deadline=None,
                        clock=time.monotonic, root_gate=RETENTION_PROBABILITY,
                        leaf_gate=RETENTION_PROBABILITY, final_gate=FINAL_CONFIDENCE_GATE,
                        candidate_filter=None):
    """Select from retained roots/leaves and an exact subset of original choices.

    ``directory`` must be a validated ``PublicCapabilityDirectory`` (two levels;
    no third-level traversal). ``state`` and the original question are passed
    unchanged to every provider stage, using independent copies of state.
    Retained shortcut roots expand directly; normal roots still receive one
    leaf stage. Shortcut-only routing skips leaves, but requires final Choice.
    An optional ``candidate_filter`` receives a copy of the retained pool and
    must return a subset Mapping with unchanged IDs/descriptions and ``none``.
    Final candidates preserve original order. An empty capability subset
    abstains; a pool covering the entire catalog also abstains rather than
    issuing a global Choice. The limit of 96 counts filtered capabilities,
    excluding ``none``.

    Returns ``status`` (selected/none/abstain/error), ``choice``, ``confidence``,
    and public ``diagnostics``. Gates must be finite probabilities in ascending
    order (root <= leaf <= final); defaults are .20, .20, .60. A stage retains
    responses equal to its gate. Only a valid final response at ``final_gate``
    or higher produces a choice; explicit final ``none`` is distinct from abstention.
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
    if (not all(_probability(gate) for gate in (root_gate, leaf_gate, final_gate))
            or not root_gate <= leaf_gate <= final_gate):
        return result('error', 'invalid_gates')
    if candidate_filter is not None and not callable(candidate_filter):
        return result('error', 'invalid_candidate_filter')
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
            _noul_spec(directory, roots), deepcopy(original_state)), roots, root_gate)
        diagnostics['retained_root_count'] = len(selected_roots)
        if not selected_roots:
            return result('abstain', 'no_roots')

        shortcut_ids = set(directory.shortcut_root_ids)
        selected_shortcuts = [root for root in selected_roots if root in shortcut_ids]
        normal_roots = [root for root in selected_roots if root not in shortcut_ids]
        children = {leaf for root in normal_roots for leaf in directory.children(root)}
        leaves = [leaf for leaf in directory.leaf_ids if leaf in children]
        diagnostics['leaf_count'] = len(leaves)
        selected_leaves = []
        if normal_roots:
            selected_leaves = _retained(call('leaves', noul_method,
                _noul_spec(directory, leaves), deepcopy(original_state)), leaves, leaf_gate)
        diagnostics['retained_leaf_count'] = len(selected_leaves)
        if not selected_leaves and not selected_shortcuts:
            return result('abstain', 'no_leaves')

        pool = directory.subset(selected_leaves + selected_shortcuts)
        if candidate_filter is not None:
            pool = _filtered_pool(pool, candidate_filter)
        diagnostics['candidate_count'] = len(pool) - 1
        if not diagnostics['candidate_count']:
            return result('abstain', 'no_candidates')
        if diagnostics['candidate_count'] > FINAL_CANDIDATE_LIMIT:
            return result('abstain', 'candidate_limit_exceeded')
        if set(pool) - {'none'} == set(directory.members(roots)):
            return result('abstain', 'full_catalog_retained')

        choice, confidence = _choice_fields(call('final', choose_method,
            question, deepcopy(original_state), deepcopy(pool)), pool)
        if confidence < final_gate:
            return result('abstain', 'final_confidence_below_gate', confidence=confidence)
        return result('none' if choice == 'none' else 'selected', 'final_choice', choice, confidence)
    except _DeadlineExceeded:
        return result('abstain', 'deadline_exceeded')
    except _InvalidResponse:
        return result('error', 'invalid_provider_response')
    except _InvalidCandidateFilter:
        return result('error', 'invalid_candidate_filter')
    except TimeoutError:
        return result('error', 'provider_timeout')
    except Exception:
        # Do not leak exception strings, class names, raw replies, or IDs.
        return result('error', 'routing_failed')
