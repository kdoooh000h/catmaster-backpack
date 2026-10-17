"""Use Jev's highest-probability option, then check only its current suitability.

Ranking uncertainty never substitutes for suitability. The complete candidate
pool stays available; this module neither retrieves nor acquires capabilities.
"""
from copy import deepcopy

import simple_backpack_selector as S
import focused_current as F
import independent_current as I


def qualification_specification(rows, winner, need):
    # Reuse the unchanged current/partial/other question and shared definitions.
    # No FocusedIndex, translation, task splitting or local ranking is invoked.
    return F.specification(rows, [winner], deepcopy(need))


def select(rows, pool, need, call):
    spec, state, mapping = S.specification(rows, pool, need)
    retained = [key for key in mapping.values() if key != 'none']
    ranking = S.validate(call('rank', spec, state), mapping, retained)
    winner = ranking['raw_choice']
    result = {
        'status': 'abstain', 'choice': None, 'raw_choice': winner,
        'confidence': None,
        'ranking_confidence': ranking['confidence'],
        'ranking_probabilities': ranking['probabilities'],
        'retained_candidates': retained, 'ranking_pool_size': len(retained),
        'verified_candidate': None, 'suitability_judgment': None,
        'confidence_semantics': 'independent_current_suitability_not_unique_best',
        'traces': [{'stage': 'ranking_pool', 'pool': list(retained)}],
        'selection_calls': 1,
    }
    if winner == 'none':
        result['reason'] = 'none_ranked_first'
        return result
    spec, state, mapping = qualification_specification(rows, winner, need)
    fit = I.validate(call('final', spec, state), mapping, [winner])
    judgment = fit['candidate_judgments'][winner]
    result.update(status=fit['status'], choice=fit['choice'],
                  confidence=judgment['confidence'],
                  verified_candidate=winner, suitability_judgment=judgment,
                  selection_calls=2)
    result['traces'].extend([
        {'stage': 'suitability_candidate', 'pool': [winner]},
        {'stage': 'later_reservoir', 'pool': list(retained)},
    ])
    if result['status'] != 'selected':
        result['reason'] = 'highest_probability_candidate_not_qualified'
    return result
