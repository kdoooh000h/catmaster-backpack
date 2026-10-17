"""Read-only receipt replay and sanitized metrics for the frozen Jev trial.

No provider, model or encoder is invoked. Replay verifies exact raw-task payloads,
question maps and traversal, while references remain post-selection grading data.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path

import jev_directory_experiment as E
from experiment import read, write_once


class ReplayStop(Exception):
    pass


def require(condition, code):
    if not condition:
        raise ValueError(code)


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def close(left, right):
    return number(left) and number(right) and math.isclose(left, right, abs_tol=1e-8, rel_tol=1e-8)


def usage(transport):
    result = {}
    for field in ('input_tokens', 'output_tokens'):
        known = [t[field] for t in transport if type(t.get(field)) is int and t[field] >= 0]
        result[field] = sum(known)
        result[field+'_complete'] = len(known) == len(transport)
    result['known_tokens'] = result['input_tokens']+result['output_tokens']
    return result


def validate_answer(spec, raw):
    """Validate even answered calls whose usage was unavailable at runtime."""
    questions = spec.get('questions', {})
    require(bool(questions), 'empty_receipt_questions')
    kinds = {q.get('type') for q in questions.values()}
    mapping = {wire: wire for wire in questions}
    if kinds == {'noul'}:
        E.D.retain(raw, mapping)
    elif kinds == {'choice'}:
        E.D.I.validate(raw, mapping, list(mapping))
    else:
        raise ValueError('invalid_receipt_question_types')


def load_receipts(live, schedule):
    receipts, by_arm = [], {key: [] for key in schedule}
    known_files = set()
    for path in live.glob('*.pending.json'):
        stem = path.name[:-len('.pending.json')]
        matches = [(case, arm, stem[len(case+'--'+arm+'--'):]) for case, arm in schedule
                   if stem.startswith(case+'--'+arm+'--')]
        require(len(matches) == 1, 'unknown_receipt_identity')
        case, arm, stage = matches[0]
        pending = read(path)
        require(type(pending.get('ordinal')) is int and pending['ordinal'] > 0, 'invalid_receipt_ordinal')
        require(pending.get('stage') == stage, 'receipt_stage_mismatch')
        require(pending.get('reserved_tokens') == E.token_reserve(pending['spec'], pending['state']), 'receipt_reserve_mismatch')
        done_path, error_path = live/(stem+'.done.json'), live/(stem+'.error.json')
        require(not (done_path.exists() and error_path.exists()), 'conflicting_receipt_outcomes')
        outcome = read(done_path) if done_path.exists() else read(error_path) if error_path.exists() else None
        kind = 'done' if done_path.exists() else 'error' if error_path.exists() else 'pending'
        answer_error = None
        if outcome is not None:
            require(outcome.get('ordinal') == pending['ordinal'] and outcome.get('stage') == stage, 'receipt_outcome_identity_mismatch')
            transport = outcome.get('transport')
            require(isinstance(transport, list) and len(transport) <= 1 and all(isinstance(t, dict) for t in transport), 'invalid_receipt_transport')
            for receipt in transport:
                require(receipt.get('seconds') is None or number(receipt['seconds']), 'invalid_transport_seconds')
                for field in ('input_tokens', 'output_tokens'):
                    require(field not in receipt or (type(receipt[field]) is int and receipt[field] >= 0), 'invalid_transport_usage')
            if kind == 'done':
                try:
                    validate_answer(pending['spec'], outcome.get('answer'))
                except ValueError as error:
                    answer_error = str(error)
            else:
                require(outcome.get('replay') is False and isinstance(outcome.get('error'), str), 'invalid_error_receipt')
        else:
            transport = []
        item = {'case': case, 'arm': arm, 'stage': stage, 'ordinal': pending['ordinal'],
                'pending': pending, 'outcome': outcome, 'kind': kind, 'transport': transport, 'answer_error': answer_error}
        receipts.append(item); by_arm[(case, arm)].append(item)
        known_files.add(stem)
    for path in list(live.glob('*.done.json'))+list(live.glob('*.error.json')):
        stem = path.name.rsplit('.', 2)[0]
        require(stem in known_files, 'orphan_outcome_receipt')
    receipts.sort(key=lambda r: r['ordinal'])
    require([r['ordinal'] for r in receipts] == list(range(1, len(receipts)+1)), 'nonsequential_or_duplicate_ordinals')
    previous_schedule_index = -1
    spent = 0
    for receipt in receipts:
        position = schedule.index((receipt['case'], receipt['arm']))
        require(position >= previous_schedule_index, 'receipt_schedule_order_mismatch')
        previous_schedule_index = position
        receipt['spent_before'] = spent
        spent += usage(receipt['transport'])['known_tokens']
        receipt['spent_after'] = spent
        if receipt['kind'] != 'done' or not E.known_usage(receipt['transport']) or receipt['answer_error']:
            require(receipt is receipts[-1], 'send_after_unknown_or_error')
    for arm_receipts in by_arm.values():
        arm_receipts.sort(key=lambda r: r['ordinal'])
    return receipts, by_arm


def omissions(case, result, arm):
    """First group loss in recorded pools; shortlist and reservoir differ."""
    traces = result.get('traces', [])
    directory_number = 0
    stages = []
    for trace in traces:
        label = trace['stage']
        if label == 'directory':
            directory_number += 1
            label = 'directory-'+str(directory_number)
        stages.append((label, set(trace.get('pool', []))))

    def first(group, purpose):
        eligible = stages
        if arm == 'program_shortlist':
            eligible = [(label, pool) for label, pool in stages
                        if label == ('current_shortlist' if purpose == 'current' else 'later_reservoir')]
        return next((label for label, pool in eligible if not set(group) & pool), None)
    return {'current': first(case['acceptable_current_ids'], 'current'),
            'later': [first(group, 'later') for group in case['pending_groups']],
            'primary_current': first([case['primary_current_id']], 'current'),
            'primary_later': [first([identifier], 'later') for identifier in case['primary_pending_ids']]}


def replay_arm(case, arm, recall, rows, nodes, receipts, limits, *, interrupted=False, stop=None,
               trial_attempts=0, trial_spent=0):
    cursor = 0

    def call(stage, spec, state):
        nonlocal cursor
        if cursor >= len(receipts):
            if interrupted:
                # Budget can be reconstructed exactly. Clock timestamps were not
                # recorded, so a time stop can only be preserved as reported.
                if stop == 'budget_stop':
                    require(trial_attempts >= limits['max_calls']
                            or trial_spent+E.token_reserve(spec, state) > limits['max_tokens'],
                            'unjustified_budget_stop')
                raise ReplayStop('unrecorded_next_send')
            raise ValueError('missing_stage_receipt')
        receipt = receipts[cursor]; cursor += 1
        pending = receipt['pending']
        require(receipt['stage'] == stage and pending['spec'] == spec and pending['state'] == state,
                'replay_payload_or_stage_mismatch')
        require(receipt['ordinal'] <= limits['max_calls']
                and receipt['spent_before']+pending['reserved_tokens'] <= limits['max_tokens'], 'send_exceeded_frozen_budget')
        if receipt['kind'] == 'pending':
            raise ReplayStop('pending_outcome_unobserved')
        if receipt['kind'] == 'error':
            raise ReplayStop(receipt['outcome']['error'])
        if not E.known_usage(receipt['transport']):
            raise ReplayStop('unknown_usage_or_outcome')
        if receipt['spent_after'] > limits['max_tokens']:
            raise ReplayStop('actual_token_budget_exceeded')
        return receipt['outcome']['answer']

    check = E.structural_recall(recall, rows) if arm == 'program_shortlist' else {'eligible': True}
    try:
        if arm == 'program_shortlist':
            if check['eligible']:
                result = E.F.select(rows, recall, case['need'], call)
            else:
                result = {'status': 'structural_guard_failed', 'choice': None, 'confidence': None,
                          'retained_candidates': recall.get('pool', []), 'final_pool_size': len(recall.get('shortlist', [])),
                          'traces': [{'stage': 'current_shortlist', 'pool': recall.get('shortlist', [])},
                                     {'stage': 'later_reservoir', 'pool': recall.get('pool', [])}]}
        else:
            result = E.D.route(nodes, rows, case['need'], call)
    except (ReplayStop, ValueError) as error:
        # Only the recorded interrupted arm may end without a result. A payload
        # or accounting mismatch is never accepted as an observed runtime stop.
        if isinstance(error, ValueError) and str(error).startswith(('replay_', 'send_', 'missing_')):
            raise
        require(interrupted, 'completed_arm_replay_failed')
        require(cursor == len(receipts), 'unused_stage_receipts')
        reason = str(error)
        if reason != 'unrecorded_next_send':
            require(reason == stop, 'interrupted_reason_mismatch')
        return None, check, reason
    require(cursor == len(receipts), 'unused_stage_receipts')
    require(not interrupted, 'interrupted_arm_replayed_complete')
    return result, check, None


def rate(count, total):
    return {'correct': count, 'total': total, 'rate': count/total if total else None}


def aggregate(rows, expected):
    later_total = sum(len(r['later_group_coverage']) for r in rows)
    return {'completed_rows': len(rows), 'planned_rows': expected,
            'known_positive_accuracy': rate(sum(r['correct_current'] for r in rows), len(rows)),
            'omission_safe_accuracy': rate(sum(r['omission_safe_pass'] for r in rows), len(rows)),
            'all_required_retained': rate(sum(r['all_required_retained'] for r in rows), len(rows)),
            'later_group_coverage': rate(sum(sum(r['later_group_coverage']) for r in rows), later_total),
            'primary_reference_coverage': rate(sum(r['all_primary_references_retained'] for r in rows), len(rows)),
            'status_counts': dict(Counter(r['status'] for r in rows)),
            'calls': sum(r['calls'] for r in rows), 'tokens': sum(r['tokens'] for r in rows),
            'input_tokens': sum(r['input_tokens'] for r in rows), 'output_tokens': sum(r['output_tokens'] for r in rows),
            **{field: sum(r[field] for r in rows) for field in
               ('warm_selector_seconds', 'fresh_retrieval_seconds', 'real_transport_seconds', 'local_routing_seconds')}}


def analyze(trial):
    trial = Path(trial)
    plan, bundle = E.verify(trial)
    cases, rows, nodes = read(trial/'cases.json'), read(bundle/'catalog.json'), read(trial/'nodes.json')
    E.T.validate(nodes, rows)
    summary, limits = read(trial/'live/summary.json'), read(trial/'live/run-limits.json')
    for key, maximum in E.LIMITS.items():
        if key in ('max_calls', 'max_tokens'):
            require(type(limits.get(key)) is int and 0 <= limits[key] <= plan[key], 'invalid_recorded_run_cap')
        else:
            require(limits.get(key) == maximum, 'recorded_policy_changed')
    require(summary.get('stopping_policy') == E.STOPPING, 'summary_stopping_policy_changed')
    schedule = [(case['id'], arm) for number, case in enumerate(cases)
                for arm in E.ARMS[number % 2:]+E.ARMS[:number % 2]]
    receipts, by_arm = load_receipts(trial/'live', schedule)
    for receipt in receipts:
        if receipt['answer_error']:
            require(summary.get('stop') == receipt['answer_error'] and summary.get('interrupted') == {'case': receipt['case'], 'arm': receipt['arm']},
                    'invalid_answer_not_recorded_as_terminal_failure')
    transport = [t for receipt in receipts for t in receipt['transport']]
    totals = usage(transport)
    require(summary.get('transport') == transport and summary.get('calls') == len(transport)
            and summary.get('attempted_sends') == len(receipts) and summary.get('known_tokens') == totals['known_tokens'],
            'summary_transport_or_usage_mismatch')
    require(close(summary.get('real_transport_seconds'), sum(t['seconds'] for t in transport if number(t.get('seconds')))),
            'summary_transport_time_mismatch')
    require(number(summary.get('wall_seconds')) and number(summary.get('tree_load_seconds')), 'invalid_summary_timing')
    saved = summary['rows']
    keys = [(r['case'], r['arm']) for r in saved]
    require(keys == schedule[:len(keys)], 'summary_row_schedule_mismatch')
    unfinished = [{'case': case, 'arm': arm} for case, arm in schedule[len(keys):]]
    require(summary.get('unfinished') == unfinished, 'unfinished_scope_mismatch')
    if summary['stop'] == 'completed':
        require(not unfinished and summary.get('interrupted') is None, 'completed_summary_is_incomplete')
    else:
        require(bool(unfinished), 'stopped_summary_has_no_unfinished')
    active = summary.get('interrupted')
    if active is not None:
        require(active == unfinished[0], 'interrupted_scope_mismatch')
    allowed = set(keys) | ({(active['case'], active['arm'])} if active else set())
    require(all(not values or key in allowed for key, values in by_arm.items()), 'receipt_outside_observed_scope')
    expected_row_files = {case+'--'+arm+'.json' for case, arm in keys}
    actual_row_files = {p.name for p in (trial/'live').glob('*.json')
                        if '--' in p.name and not p.name.endswith(('.pending.json', '.done.json', '.error.json'))}
    require(actual_row_files == expected_row_files, 'row_file_scope_mismatch')
    sanitized = []
    by_case = {c['id']: c for c in cases}
    for item in saved:
        case, arm = by_case[item['case']], item['arm']
        recall = read(trial/(case['id']+'.recall.json'))['recall']
        arm_receipts = by_arm[(case['id'], arm)]
        result, check, _ = replay_arm(case, arm, recall, rows, nodes, arm_receipts, limits)
        require(item == read(trial/'live'/(case['id']+'--'+arm+'.json')), 'row_file_content_mismatch')
        require(item.get('result') == result and item.get('structural_check') == check, 'replay_result_or_trace_mismatch')
        grades = E.grade(case, result, recall if arm == 'program_shortlist' else None)
        require(all(item.get(key) == value for key, value in grades.items()), 'row_grade_mismatch')
        require(item.get('stratum') == case['stratum'], 'row_stratum_mismatch')
        arm_transport = [t for receipt in arm_receipts for t in receipt['transport']]
        arm_usage = usage(arm_transport)
        require(item.get('transport') == arm_transport and item.get('calls') == len(arm_transport)
                and item.get('attempted_sends') == len(arm_receipts) and item.get('tokens') == arm_usage['known_tokens']
                and item.get('stages') == [r['stage'] for r in arm_receipts], 'row_accounting_mismatch')
        actual_transport = sum(t['seconds'] for t in arm_transport if number(t.get('seconds')))
        retrieval = recall.get('fresh_retrieval_seconds', recall.get('seconds', 0.)) if arm == 'program_shortlist' else 0.
        wall = item.get('dispatch_seconds')
        require(number(wall) and close(item.get('real_transport_seconds'), actual_transport)
                and close(item.get('local_routing_seconds'), max(0., wall-actual_transport))
                and close(item.get('fresh_retrieval_seconds'), retrieval) and close(item.get('retrieval_seconds'), retrieval)
                and close(item.get('selector_seconds'), retrieval+wall), 'row_timing_mismatch')
        sanitized.append({'case': case['id'], 'arm': arm, 'stratum': case['stratum'], 'status': result['status'],
                          'choice': result.get('choice'), 'confidence': result.get('confidence'),
                          **grades, 'first_omission_stage': omissions(case, result, arm),
                          'calls': len(arm_transport), 'tokens': arm_usage['known_tokens'],
                          'input_tokens': arm_usage['input_tokens'], 'output_tokens': arm_usage['output_tokens'],
                          'warm_selector_seconds': item['selector_seconds'], 'fresh_retrieval_seconds': retrieval,
                          'real_transport_seconds': actual_transport, 'local_routing_seconds': item['local_routing_seconds']})
    interruption = None
    if active:
        case, arm = by_case[active['case']], active['arm']
        recall = read(trial/(case['id']+'.recall.json'))['recall']
        _, _, replay_stop = replay_arm(case, arm, recall, rows, nodes, by_arm[(case['id'], arm)], limits,
                                      interrupted=True, stop=summary['stop'], trial_attempts=len(receipts),
                                      trial_spent=totals['known_tokens'])
        interruption = {**active, 'reported_stop': summary['stop'], 'replay_stop': replay_stop,
                        'receipts': [{'ordinal': r['ordinal'], 'stage': r['stage'], 'outcome': r['kind'],
                                      'usage_known': E.known_usage(r['transport'])}
                                     for r in by_arm[(case['id'], arm)]],
                        'grade': 'unobserved', 'first_omission_stage': 'unobserved'}
    build_seconds = None
    for locked_path in plan.get('locks', {}):
        if Path(locked_path).name == 'tree-precheck.json':
            value = read(locked_path).get('build_seconds')
            if number(value):
                build_seconds = value
    groups = {}
    for stratum in ('failed', 'new', 'all'):
        chosen = [r for r in sanitized if stratum == 'all' or r['stratum'] == stratum]
        expected = sum(stratum == 'all' or case['stratum'] == stratum for case in cases)
        paired_ids = {r['case'] for r in chosen if sum(v['case'] == r['case'] for v in chosen) == 2}
        paired = [r for r in chosen if r['case'] in paired_ids]
        wins = Counter()
        for case_id in paired_ids:
            pair = {r['arm']: r['omission_safe_pass'] for r in paired if r['case'] == case_id}
            wins['tie' if len(set(pair.values())) == 1 else next(arm for arm in E.ARMS if pair[arm])] += 1
        groups[stratum] = {'arms': {arm: aggregate([r for r in chosen if r['arm'] == arm], expected) for arm in E.ARMS},
                           'paired_completed': {'cases': len(paired_ids), 'omission_safe_wins': dict(wins),
                               'arms': {arm: aggregate([r for r in paired if r['arm'] == arm], len(paired_ids)) for arm in E.ARMS}}}
    return {'version': 1, 'verification': 'frozen_inputs_and_receipt_replay_passed',
            'stop': summary['stop'], 'completed_rows': len(sanitized), 'planned_rows': len(schedule),
            'unfinished': unfinished, 'interrupted': interruption, 'groups': groups, 'rows': sanitized,
            'trial_cost': {'calls': len(transport), 'attempted_sends': len(receipts), **totals,
                           'real_transport_seconds': summary['real_transport_seconds'], 'wall_seconds': summary['wall_seconds']},
            'cold_setup_seconds': {'tree_load': summary['tree_load_seconds'], 'tree_build': build_seconds,
                                   **{key: plan.get(key) for key in ('index_load_seconds', 'dictionary_load_seconds', 'local_index_startup_seconds')}},
            'limits': {'directory_gate': .2, 'final_gate': .7,
                       'deadline_enforcement': 'unobservable_from_receipts_without_clock_timestamps',
                       'runtime_readiness': 'unobservable', 'backend_model_revision': 'unobservable',
                       'accuracy_scope': 'authored_known_positive_cases_only; incomplete arms excluded from accuracy denominators'}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('trial'); parser.add_argument('--output')
    args = parser.parse_args()
    result = analyze(args.trial)
    if args.output:
        write_once(args.output, result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
