"""Two narrow suitability checks using exact cached comparative rankings.

No ranking, root or passed-case replay is sent to the provider. Historical gold
stays frozen; selection acceptance is reported separately from that gold score.
"""
import argparse
import json
from pathlib import Path

import simple_selection_pilot as Q
import preferred_capability_selector as P

X, read, write_once, digest = Q.X, Q.read, Q.write_once, Q.digest
SCRIPT = Path(__file__).resolve()
CASES = ['new_access_control_design', 'new_test_driven_feature_plan']
LIMITS = {'max_calls': 2, 'max_tokens': 10000, 'max_seconds': 60,
          'call_timeout_seconds': 20}
ARM = 'highest-then-fit'
POLICY = {'ranking': 'use provider argmax; ranking confidence does not gate use',
          'suitability': 'same current/partial/other Choice, current confidence >=0.7',
          'scope': 'two previously abstained rankings, unchanged tasks and pools',
          'reuse': 'exact rank receipts; only single-winner suitability calls are fresh',
          'later': 'retain complete pool', 'retries': 0,
          'stopping': 'any error, unknown outcome/usage or budget stops all further sends',
          'gold': 'unchanged old references; report eligibility separately, not as accuracy'}


def material(previous):
    old = Q.verify(previous)
    return Q.material(old['previous'])


def prefix(previous, key):
    stem = Path(previous)/'live'/f'{key}--{Q.ARM}--final'
    pending = read(str(stem)+'.pending-before.json')
    done = read(str(stem)+'.done-after.json')
    X.require(pending['identity'] == {'case': key, 'arm': Q.ARM}
              and pending['stage'] == done['stage'] == 'final'
              and pending['ordinal'] == done['ordinal']
              and X.E.known_usage(done['transport']), 'invalid_rank_prefix')
    return pending, done


def route(previous, key, call):
    rows, cases = material(previous)
    pool = read(Path(previous)/'live'/f'{key}.json')['result']['retained_candidates']
    pending, done = prefix(previous, key)
    count = 0
    def cached(stage, spec, state):
        nonlocal count
        count += 1
        if stage == 'rank':
            X.require(count == 1 and spec == pending['spec'] and state == pending['state'],
                      'cached_rank_payload_changed')
            return done['answer']
        X.require(stage == 'final' and count == 2, 'extra_or_repeated_call')
        return call(stage, spec, state)
    return P.select(rows, pool, cases[key]['need'], cached)


def preparation(previous):
    prepared = []
    for key in CASES:
        saved = read(Path(previous)/'live'/f'{key}.json')
        X.require(saved['result']['status'] == 'abstain'
                  and saved['result']['raw_choice'] != 'none', 'only_abstained_rankings_allowed')
        class Captured(Exception):
            pass
        def capture(stage, spec, state):
            prepared.append({'case': key, 'spec': spec, 'state': state,
                             'reserve': X.E.token_reserve(spec, state)})
            raise Captured()
        try:
            route(previous, key, capture)
        except Captured:
            pass
    X.require([p['case'] for p in prepared] == CASES, 'missing_fit_preparation')
    return prepared


def freeze(previous, output):
    previous, output = Path(previous).resolve(), Path(output).resolve()
    Q.analyze(previous)
    prep = preparation(previous)
    paths = list(previous.rglob('*.json')) + [SCRIPT, Path(P.__file__)]
    output.mkdir(mode=0o700, exist_ok=False)
    write_once(output/'preparation.json', prep)
    plan = {'previous': str(previous), 'limits': LIMITS, 'policy': POLICY, 'cases': CASES,
            'locks': {str(p): digest(p) for p in paths},
            'preparation_sha256': digest(output/'preparation.json'),
            'total_reserved_tokens': sum(p['reserve'] for p in prep)}
    X.require(plan['total_reserved_tokens'] <= LIMITS['max_tokens'], 'plan_exceeds_budget')
    write_once(output/'plan.json', plan)
    return plan


def verify(output):
    output = Path(output); plan = read(output/'plan.json')
    X.require(plan['limits'] == LIMITS and plan['policy'] == POLICY and plan['cases'] == CASES,
              'frozen_policy_changed')
    for path, sha in plan['locks'].items():
        X.require(digest(path) == sha, 'locked_input_changed')
    X.require(digest(output/'preparation.json') == plan['preparation_sha256']
              and read(output/'preparation.json') == preparation(plan['previous']),
              'preparation_changed')
    return plan


def run(output):
    output = Path(output); plan = verify(output)
    old = Q.verify(plan['previous'])
    _, provider_plan = Q.P.verify(old['previous'])
    _, cases = material(plan['previous'])
    folder = output/'live'; folder.mkdir(mode=0o700, exist_ok=False)
    recorder = X.Recorder(folder, provider_plan, LIMITS)
    completed, active, stop = [], None, 'completed'
    try:
        for key in CASES:
            active = {'case': key, 'arm': ARM}; recorder.context(active)
            offset = len(recorder.transport)
            result = route(plan['previous'], key, recorder.call)
            transport = recorder.transport[offset:]
            row = {**active, 'result': result, **X.E.grade(cases[key], result),
                   'transport': transport, **X.usage(transport)}
            write_once(folder/f'{key}.json', row); completed.append(row); active = None
    except Exception as error:
        stop = str(error)
    summary = {'stop': stop, 'rows': completed, 'interrupted': active,
               'unfinished': CASES[len(completed):], **recorder.summary()}
    write_once(folder/'summary.json', summary)
    return summary


def analyze(output):
    output = Path(output); plan = verify(output)
    _, cases = material(plan['previous']); folder = output/'live'
    receipts = X.load_receipts(folder, LIMITS, Q.ZERO)
    summary, cost = X.verified_summary(folder, receipts, LIMITS, Q.ZERO)
    X.require(summary is not None, 'run_summary_missing_reconcile_only')
    saved = summary['rows']; verified = []
    X.require([r['case'] for r in saved] == CASES[:len(saved)]
              and len(receipts) <= len(saved)+1, 'unexpected_send_or_row_order')
    for i, row in enumerate(saved):
        key = CASES[i]
        replay = X.Replay([receipts[i]], {'case': key, 'arm': ARM})
        result = route(plan['previous'], key, replay.call); replay.consumed()
        grades = X.E.grade(cases[key], result)
        X.require(result == row['result'] and all(row[k] == v for k, v in grades.items())
                  and row['transport'] == receipts[i]['transport'], 'row_replay_changed')
        old = read(Path(plan['previous'])/'live'/f'{key}.json')
        verified.append({'case': key, 'selected': result['choice'],
            'selected_by_original_reference': grades['omission_safe_pass'],
            'highest_probability_candidate_qualified': result['status'] == 'selected',
            'ranking_confidence': result['ranking_confidence'], 'fit_confidence': result['confidence'],
            'fit_judgment': result['suitability_judgment'],
            'ranking_pool_size': result['ranking_pool_size'],
            'whole_pool_retained': result['retained_candidates'] == old['result']['retained_candidates'],
            'known_references_retained': grades['all_required_retained'],
            'fresh_fit_tokens': X.usage(row['transport'])['known_tokens'],
            'cached_rank_tokens': old['known_tokens'],
            'fresh_fit_seconds': sum(t['seconds'] for t in row['transport']),
            'cached_rank_seconds': sum(t['seconds'] for t in old['transport'])})
    if len(receipts) > len(saved):
        key = CASES[len(saved)]
        replay = X.Replay([receipts[-1]], {'case': key, 'arm': ARM},
                          limits=LIMITS, prior=Q.ZERO, total=cost)
        try:
            route(plan['previous'], key, replay.call)
        except (ValueError, X.ReplayStop) as error:
            X.require(str(error) == summary['stop'], 'stop_reason_changed')
        else:
            raise ValueError('ungraded_completed_receipt')
        replay.consumed()
    X.require(summary['unfinished'] == CASES[len(saved):]
              and (summary['stop'] == 'completed') == (len(saved) == len(CASES)), 'stop_scope_changed')
    return {'verification': 'exact_cached_ranking_and_new_fit_replay', 'stop': summary['stop'],
            'rows': verified, 'fresh_cost': cost, 'unfinished': summary['unfinished'],
            'qualification': 'Two exposed ranking failures; fresh suitability only, no acquisition/execution or fresh end-to-end timing; original gold unchanged.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['freeze', 'run', 'analyze'])
    parser.add_argument('output'); parser.add_argument('--previous')
    args = parser.parse_args()
    value = freeze(args.previous, args.output) if args.action == 'freeze' else globals()[args.action](args.output)
    print(json.dumps(value, ensure_ascii=False, indent=2))
