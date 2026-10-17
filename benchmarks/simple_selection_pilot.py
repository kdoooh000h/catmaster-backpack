"""Three failed final selections, one changed factor, no repeated root calls.

The cached .65 directory prefix is a controlled input, not a new end-to-end run.
The old independent final and new comparative final both retain the entire pool.
"""
import argparse
import json
from pathlib import Path
import time

import taxonomy_threshold_pilot as P
import simple_backpack_selector as S

X, read, write_once, digest = P.X, P.read, P.write_once, P.digest
SCRIPT = Path(__file__).resolve()
CASES = ['fresh_backend_exception_design', 'new_access_control_design',
         'new_test_driven_feature_plan']
LIMITS = {'max_calls': 3, 'max_tokens': 70000, 'max_seconds': 90,
          'call_timeout_seconds': 20}
ZERO = {'attempted_sends': 0, 'known_tokens': 0, 'wall_seconds': 0.}
ARM = 'comparative-final'
POLICY = {'final_gate': .7, 'final_limit': 128, 'directory_gate': .65,
          'fresh_calls_per_case': 1, 'retries': 0,
          'prefix': 'same recorded final pools and full raw tasks; no fresh root calls',
          'only_changed_factor': 'independent candidate judgments to one comparative Choice',
          'confidence': 'raw provider confidence, no recalibration or sorting',
          'stopping': 'unknown usage/outcome, error, or budget stops all further sends'}


def material(previous):
    plan, _ = P.verify(previous)
    rows, cases, _ = P.load_material(plan)
    return rows, cases


def prepare(previous):
    rows, cases = material(previous)
    result = []
    for key in CASES:
        old = read(Path(previous)/'live'/f'{key}.json')
        X.require(old['omission_safe_pass'] is False, 'cannot_rerun_passed_case')
        pool = old['result']['retained_candidates']
        spec, state, mapping = S.specification(rows, pool, cases[key]['need'])
        result.append({'case': key, 'pool': pool, 'spec': spec, 'state': state,
                       'mapping': mapping, 'reserve': X.E.token_reserve(spec, state)})
    return result


def freeze(previous, output):
    previous, output = Path(previous).resolve(), Path(output).resolve()
    X.require(P.analyze(previous) == read(previous/'analysis.json'), 'old_replay_changed')
    prep = prepare(previous)
    paths = [p for p in previous.rglob('*.json')] + [SCRIPT, Path(S.__file__)]
    locks = {str(p): digest(p) for p in paths}
    output.mkdir(mode=0o700, exist_ok=False)
    write_once(output/'preparation.json', prep)
    plan = {'previous': str(previous), 'limits': LIMITS, 'policy': POLICY,
            'case_order': CASES, 'locks': locks,
            'preparation_sha256': digest(output/'preparation.json'),
            'reservation_total': sum(p['reserve'] for p in prep),
            'model_revision': 'unobservable', 'execution_readiness': 'unobservable',
            'scope': 'three previously exposed failures, not a blind/general accuracy estimate'}
    X.require(plan['reservation_total'] <= LIMITS['max_tokens'], 'plan_exceeds_budget')
    write_once(output/'plan.json', plan)
    return plan


def verify(output):
    output = Path(output)
    plan = read(output/'plan.json')
    X.require(plan['limits'] == LIMITS and plan['policy'] == POLICY
              and plan['case_order'] == CASES, 'frozen_policy_changed')
    for path, sha in plan['locks'].items():
        X.require(digest(path) == sha, 'locked_input_changed')
    X.require(digest(output/'preparation.json') == plan['preparation_sha256']
              and read(output/'preparation.json') == prepare(plan['previous']),
              'preparation_replay_changed')
    return plan


def run(output):
    output = Path(output)
    plan = verify(output)
    _, original = P.verify(plan['previous'])
    rows, cases = material(plan['previous'])
    folder = output/'live'; folder.mkdir(mode=0o700, exist_ok=False)
    recorder = X.Recorder(folder, original, LIMITS)
    completed, active, stop = [], None, 'completed'
    try:
        for item in read(output/'preparation.json'):
            key = item['case']; active = {'case': key, 'arm': ARM}
            recorder.context(active)
            offset, began = len(recorder.transport), time.monotonic()
            result = S.select(rows, item['pool'], cases[key]['need'], recorder.call)
            transport = recorder.transport[offset:]
            row = {**active, 'result': result, **X.E.grade(cases[key], result, None),
                   'transport': transport, **X.usage(transport),
                   'wall_seconds': time.monotonic()-began}
            write_once(folder/f'{key}.json', row)
            completed.append(row); active = None
    except Exception as error:
        stop = str(error)
    summary = {'stop': stop, 'rows': completed, 'interrupted': active,
               'unfinished': CASES[len(completed):], **recorder.summary()}
    write_once(folder/'summary.json', summary)
    return summary


def analyze(output):
    output = Path(output); plan = verify(output)
    rows, cases = material(plan['previous'])
    folder = output/'live'
    receipts = X.load_receipts(folder, LIMITS, ZERO)
    summary, cost = X.verified_summary(folder, receipts, LIMITS, ZERO)
    X.require(summary is not None, 'run_summary_missing_reconcile_only')
    saved = summary['rows']
    X.require([r['case'] for r in saved] == CASES[:len(saved)], 'row_order_changed')
    X.require(len(receipts) <= len(saved)+1, 'send_after_stop')
    items = read(output/'preparation.json')
    verified = []
    for index, row in enumerate(saved):
        item = items[index]; key = item['case']; identity = {'case': key, 'arm': ARM}
        replay = X.Replay([receipts[index]], identity)
        result = S.select(rows, item['pool'], cases[key]['need'], replay.call)
        replay.consumed()
        grades = X.E.grade(cases[key], result, None)
        X.require(row['result'] == result and all(row[k] == v for k, v in grades.items())
                  and row['transport'] == receipts[index]['transport'], 'saved_result_changed')
        old = read(Path(plan['previous'])/'live'/f'{key}.json')
        verified.append({'case': key, 'pool_size': len(item['pool']),
            'old_choice': old['result']['choice'], 'new_choice': result['choice'],
            'old_confidence': old['result']['confidence'], 'new_confidence': result['confidence'],
            'old_pass': old['omission_safe_pass'], 'new_pass': grades['omission_safe_pass'],
            'current_in_pool': grades['current_in_final_pool'],
            'later_group_coverage': grades['later_group_coverage'],
            'all_references_retained': grades['all_required_retained'],
            'old_tokens': old['known_tokens'], 'new_tokens': X.usage(row['transport'])['known_tokens'],
            'old_transport_seconds': sum(t['seconds'] for t in old['transport']),
            'new_transport_seconds': sum(t['seconds'] for t in row['transport'])})
    if len(receipts) > len(saved):
        item = items[len(saved)]
        replay = X.Replay([receipts[-1]], {'case': item['case'], 'arm': ARM},
                          limits=LIMITS, prior=ZERO, total=cost)
        try:
            S.select(rows, item['pool'], cases[item['case']]['need'], replay.call)
        except (ValueError, X.ReplayStop) as error:
            X.require(str(error) == summary['stop'], 'stop_reason_changed')
        else:
            raise ValueError('ungraded_completed_receipt')
        replay.consumed()
    X.require(summary['unfinished'] == CASES[len(saved):], 'unfinished_scope_changed')
    X.require((summary['stop'] == 'completed') == (len(saved) == len(CASES)), 'stop_scope_mismatch')
    totals = {key: sum(r[key] for r in verified) for key in
              ['old_pass', 'new_pass', 'old_tokens', 'new_tokens',
               'old_transport_seconds', 'new_transport_seconds']}
    return {'verification': 'locked_inputs_exact_final_payload_and_result_replay',
            'stop': summary['stop'], 'rows': verified, 'totals': totals,
            'new_cost': cost, 'unfinished': summary['unfinished'], 'policy': POLICY,
            'qualification': 'Paired final-stage replay only; old roots reused; no fresh end-to-end timing, execution, blind or full-catalog validation.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['freeze', 'run', 'analyze'])
    parser.add_argument('output'); parser.add_argument('--previous')
    args = parser.parse_args()
    value = freeze(args.previous, args.output) if args.action == 'freeze' else globals()[args.action](args.output)
    print(json.dumps(value, ensure_ascii=False, indent=2))
