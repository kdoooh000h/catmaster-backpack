"""Frozen .65 root-gate suffix, sharing the original experiment's online cap.

Recorded root judgments are cached prefix evidence. Only final suitability calls
are fresh. The original .2 success is skipped and remains unverified at .65.
"""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent/'directory-depth'))
import jev_taxonomy_experiment as X
from experiment import read, write_once
from semantic_index import digest

SCRIPT = Path(__file__).resolve()
GATE = .65
ARM = 'semantic-suffix'
POLICY = {'directory_gate': GATE, 'final_gate': .7, 'final_limit': 128,
          'question_batch': 64, 'per_need_max_calls': 8, 'fresh_calls_per_suffix': 1,
          'order': 'descending final token reservation, canonical case id breaks ties',
          'prefix': 'exact recorded root request and answer, no fresh root calls',
          'selection': 'lowest failed-seven diagnostic gate with all reference coverage and pool <=128'}


@contextmanager
def gate():
    original = X.D.DIRECTORY_GATE
    X.D.DIRECTORY_GATE = GATE
    try:
        yield
    finally:
        X.D.DIRECTORY_GATE = original


class CaptureFinal(Exception):
    pass


def require(condition, code):
    X.require(condition, code)


def original_report(trial, analysis_path):
    report = X.analyze(trial)
    require(report == read(analysis_path), 'original_analysis_changed_or_not_replayed')
    require(set(report['phases']) == {'failed', 'new'}
            and all(p['stop'] == 'completed' for p in report['phases'].values()), 'original_phases_incomplete')
    cost = report['online_cost']
    require(cost['input_tokens_complete'] and cost['output_tokens_complete'], 'original_usage_unknown')
    return report


def choose_gate(diagnostics):
    # Selection reads the seven failed development rows only; exposed new
    # counterfactuals are locked as history but never enter this decision.
    entries = diagnostics['summary']['failed']
    require(all(row['rows'] == 7 for row in entries), 'expected_seven_development_cases')
    eligible = [row['gate'] for row in entries if row['known_coverage_and_final_size'] == 7]
    require(eligible and min(eligible) == GATE and diagnostics['final_gate_unchanged'] == .7,
            'development_gate_evidence_changed')
    return GATE


def root_prefix(trial, case):
    folder = Path(trial)/('live-'+case['stratum'])
    stem = folder/(case['id']+'--semantic--directory-1-batch-1')
    pending_path, done_path = Path(str(stem)+'.pending-before.json'), Path(str(stem)+'.done-after.json')
    pending, done = read(pending_path), read(done_path)
    require(pending['identity'] == {'case': case['id'], 'arm': 'semantic'}
            and pending['stage'] == 'directory-1-batch-1' and done['stage'] == pending['stage']
            and pending['ordinal'] == done['ordinal'] and X.E.known_usage(done['transport']),
            'invalid_cached_root_receipt')
    return {'pending_path': str(pending_path), 'done_path': str(done_path),
            'stage': pending['stage'], 'spec': pending['spec'], 'state': pending['state'],
            'answer': done['answer'], 'transport': done['transport']}


def route_suffix(nodes, rows, case, prefix, final_call):
    count = 0
    def call(stage, spec, state):
        nonlocal count
        if stage == prefix['stage']:
            require(count == 0 and spec == prefix['spec'] and state == prefix['state'],
                    'cached_root_payload_or_stage_mismatch')
            count += 1
            return prefix['answer']
        require(stage == 'final' and count == 1, 'fresh_root_or_extra_suffix_call_forbidden')
        count += 1
        return final_call(stage, spec, state)
    with gate():
        result = X.route(nodes, rows, case['need'], call)
    require(count in (1, 2), 'cached_root_not_used')
    return result


def prepare(trial, case, nodes, rows):
    prefix = root_prefix(trial, case)
    final = None
    def capture(stage, spec, state):
        nonlocal final
        final = {'stage': stage, 'spec': spec, 'state': state,
                 'reserved_tokens': X.E.token_reserve(spec, state)}
        raise CaptureFinal()
    structural = None
    try:
        structural = route_suffix(nodes, rows, case, prefix, capture)
    except CaptureFinal:
        pass
    return {'case': case['id'], 'stratum': case['stratum'], 'prefix': prefix,
            'final': final, 'reserved_tokens': final['reserved_tokens'] if final else 0,
            'structural_result': structural}


def freeze(trial, output, analysis_path, diagnostics_path):
    trial, output, analysis_path, diagnostics_path = map(lambda p: Path(p).resolve(),
                                                        (trial, output, analysis_path, diagnostics_path))
    original_plan = X.verify(trial)
    report = original_report(trial, analysis_path)
    diagnostics = read(diagnostics_path); choose_gate(diagnostics)
    cases, rows, nodes = read(trial/'cases.json'), read(trial/'rows.json'), X.built(trial)
    semantic = [r for r in report['rows'] if r['arm'] == 'semantic']
    require(len(semantic) == 10 and {r['case'] for r in semantic} == {c['id'] for c in cases},
            'original_semantic_scope_changed')
    passed = [r['case'] for r in semantic if r['omission_safe_pass'] is True]
    require(len(passed) == 1, 'expected_one_original_semantic_pass')
    chosen = [case for case in cases if case['id'] not in passed]
    require(len(chosen) == 9 and sum(c['stratum'] == 'failed' for c in chosen) == 6
            and sum(c['stratum'] == 'new' for c in chosen) == 3, 'suffix_scope_changed')
    preparation = [prepare(trial, case, nodes, rows) for case in chosen]
    preparation.sort(key=lambda p: (-p['reserved_tokens'], p['case']))
    paths = [p for p in trial.rglob('*') if p.is_file()]+[analysis_path, diagnostics_path, SCRIPT]
    locks = dict(original_plan['locks'])
    locks.update({str(p): digest(p) for p in paths})
    output.mkdir(mode=0o700, exist_ok=False)
    write_once(output/'preparation.json', preparation)
    cost = report['online_cost']
    used = {key: cost[key] for key in ('attempted_sends', 'known_tokens', 'wall_seconds')}
    require(used['attempted_sends'] <= X.LIVE_LIMITS['max_calls']
            and used['known_tokens'] <= X.LIVE_LIMITS['max_tokens']
            and used['wall_seconds'] < X.LIVE_LIMITS['max_seconds'], 'original_budget_exhausted')
    plan = {'version': 1, 'trial': str(trial), 'analysis_path': str(analysis_path),
        'diagnostics_path': str(diagnostics_path), 'policy': POLICY, 'limits': X.LIVE_LIMITS,
        'original_online_cost': cost, 'original_offline_cost': report['build']['cost'],
        'prior_usage': used, 'locks': locks,
        'frozen_sha256': {'preparation.json': digest(output/'preparation.json')},
        'case_order': [p['case'] for p in preparation],
        'skipped': [{'case': identifier, 'reason': 'already observed omission-safe semantic pass at .2',
                     'gate_065_result': 'unverified'} for identifier in passed],
        'gate_selection_scope': 'failed seven only; six development suffixes and three previously exposed new suffixes',
        'latency_qualification': 'Cached prefix plus new final is not fresh end-to-end latency.',
        'backend_model_revision': 'unobservable', 'no_organization_only_advantage_claim': True}
    X.verify(trial)
    require(all(digest(path) == sha for path, sha in locks.items()), 'input_changed_during_suffix_freeze')
    write_once(output/'plan.json', plan)
    return output


def verify(output):
    output = Path(output)
    plan = read(output/'plan.json')
    require(plan['policy'] == POLICY and plan['limits'] == X.LIVE_LIMITS, 'suffix_policy_changed')
    original_plan = X.verify(plan['trial'])
    require(str(SCRIPT) in plan['locks'], 'suffix_script_lock_missing')
    original = read(plan['analysis_path'])
    require(plan['original_online_cost'] == original['online_cost']
            and plan['original_offline_cost'] == original['build']['cost']
            and plan['prior_usage'] == {key: original['online_cost'][key] for key in
                ('attempted_sends', 'known_tokens', 'wall_seconds')}, 'suffix_prior_budget_changed')
    passed = [r['case'] for r in original['rows'] if r['arm'] == 'semantic' and r['omission_safe_pass'] is True]
    require(plan['skipped'] == [{'case': key, 'reason': 'already observed omission-safe semantic pass at .2',
                               'gate_065_result': 'unverified'} for key in passed], 'suffix_skip_changed')
    required = {r['case'] for r in original['rows'] if r['arm'] == 'semantic' and r['case'] not in passed}
    require(len(required) == len(plan['case_order']) and set(plan['case_order']) == required, 'suffix_scope_changed')
    choose_gate(read(plan['diagnostics_path']))
    for path, sha in plan['locks'].items():
        require(digest(path) == sha, 'suffix_locked_input_changed')
    for name, sha in plan['frozen_sha256'].items():
        require(digest(output/name) == sha, 'suffix_frozen_input_changed')
    preparation = read(output/'preparation.json')
    require([p['case'] for p in preparation] == plan['case_order']
            and preparation == sorted(preparation, key=lambda p: (-p['reserved_tokens'], p['case'])),
            'suffix_order_changed')
    return plan, original_plan


def load_material(plan):
    trial = Path(plan['trial'])
    return read(trial/'rows.json'), {c['id']: c for c in read(trial/'cases.json')}, X.built(trial)


def run(output):
    output = Path(output)
    plan, original_plan = verify(output)
    folder = output/'live'; folder.mkdir(mode=0o700, exist_ok=False)
    recorder = X.Recorder(folder, original_plan, X.LIVE_LIMITS, plan['prior_usage'])
    rows, cases, nodes = load_material(plan)
    completed, active, stop = [], None, 'completed'
    preparation = read(output/'preparation.json')
    try:
        for item in preparation:
            case = cases[item['case']]
            active = {'case': case['id'], 'arm': ARM}
            recorder.context(active)
            offset, began = len(recorder.transport), time.monotonic()
            result = route_suffix(nodes, rows, case, item['prefix'], recorder.call)
            transport = recorder.transport[offset:]
            result_row = {**active, 'stratum': case['stratum'], 'result': result,
                **X.E.grade(case, result, None), 'calls': len(transport), **X.usage(transport),
                'transport': transport, 'attempted_sends': len(recorder.local),
                'stages': [p['stage'] for p in recorder.local],
                'suffix_wall_seconds': time.monotonic()-began}
            write_once(folder/(case['id']+'.json'), result_row)
            completed.append(result_row); active = None
    except Exception as error:
        stop = str(error)
    summary = {'stop': stop, 'rows': completed, 'interrupted': active,
        'unattempted': plan['case_order'][len(completed)+(active is not None):],
        'unfinished': plan['case_order'][len(completed):], **recorder.summary()}
    write_once(folder/'summary.json', summary)
    return summary


def analyze(output):
    output = Path(output)
    plan, _ = verify(output)
    rows, cases, nodes = load_material(plan)
    # Recreate frozen preparations from current locked root receipts, including
    # exact raw task, metadata, maps and size-based scheduling. No API is used.
    preparation = read(output/'preparation.json')
    expected = [prepare(plan['trial'], cases[p['case']], nodes, rows) for p in preparation]
    require(preparation == expected, 'suffix_preparation_replay_changed')
    folder = output/'live'
    require(folder.is_dir(), 'suffix_not_started')
    receipts = X.load_receipts(folder, X.LIVE_LIMITS, plan['prior_usage'])
    summary, marginal = X.verified_summary(folder, receipts, X.LIVE_LIMITS, plan['prior_usage'])
    stop = summary['stop'] if summary else 'unobserved_interruption'
    saved = summary['rows'] if summary else []
    if summary is None:
        for item in preparation:
            path = folder/(item['case']+'.json')
            if not path.exists():
                break
            saved.append(read(path))
    order = plan['case_order']
    require([r['case'] for r in saved] == order[:len(saved)], 'suffix_row_order_changed')
    by_case = {key: [] for key in order}
    positions = []
    for receipt in receipts:
        pending = receipt['pending']; identity = pending['identity']
        require(identity.get('arm') == ARM and identity.get('case') in by_case
                and pending['stage'] == 'final', 'suffix_sent_fresh_root_or_extra_stage')
        by_case[identity['case']].append(receipt); positions.append(order.index(identity['case']))
    require(positions == sorted(positions) and all(len(v) <= 1 for v in by_case.values()),
            'suffix_receipt_schedule_changed')
    require(all(position <= len(saved) for position in positions), 'suffix_send_after_interruption')
    sanitized, interrupted = [], None
    for index, item in enumerate(preparation[:min(len(preparation), len(saved)+1)]):
        case, complete = cases[item['case']], index < len(saved)
        identity = {'case': case['id'], 'arm': ARM}
        replay = X.Replay(by_case[case['id']], identity, None if complete else stop,
                          limits=X.LIVE_LIMITS, prior=plan['prior_usage'], total=marginal)
        result, reason = None, None
        try:
            result = route_suffix(nodes, rows, case, item['prefix'], replay.call)
        except X.ReplayStop as error:
            require(not complete, 'completed_suffix_replay_failed'); reason = str(error)
            require(reason == stop or reason == 'unrecorded_next_send' and stop in
                    ('budget_stop', 'time_budget_stop', 'unobserved_interruption')
                    or reason == 'pending_outcome_unobserved' and summary is None, 'suffix_stop_mismatch')
        except ValueError as error:
            if str(error).startswith(('replay_', 'missing_', 'unused_', 'unjustified_', 'cached_', 'fresh_')):
                raise
            require(not complete and str(error) == stop, 'suffix_runtime_stop_mismatch'); reason = str(error)
        replay.consumed()
        if not complete:
            require(result is None, 'interrupted_suffix_replayed_complete')
            interrupted = {**identity, 'grade': 'unobserved', 'replay_stop': reason}
            continue
        stored = saved[index]
        transport = [t for r in by_case[case['id']] for t in r['transport']]
        grades = X.E.grade(case, result, None)
        require(stored == read(folder/(case['id']+'.json')) and stored['result'] == result
                and stored['arm'] == ARM and stored['stratum'] == case['stratum']
                and all(stored.get(k) == v for k, v in grades.items()), 'suffix_result_trace_or_grade_changed')
        require(stored['transport'] == transport and stored['calls'] == len(transport)
                and stored['attempted_sends'] == len(by_case[case['id']])
                and stored['stages'] == [r['pending']['stage'] for r in by_case[case['id']]]
                and all(stored.get(k) == v for k, v in X.usage(transport).items())
                and X.number(stored.get('suffix_wall_seconds')), 'suffix_row_accounting_changed')
        prefix_transport = item['prefix']['transport']
        sanitized.append({**identity, 'stratum': case['stratum'], 'status': result['status'],
            'choice': result.get('choice'), 'confidence': result.get('confidence'), **grades,
            **X.pools(case, result), 'calls': len(transport), **X.usage(transport),
            'wall_seconds': stored['suffix_wall_seconds'],
            'cached_prefix_cost': {'calls': len(prefix_transport), **X.usage(prefix_transport),
                'historical_transport_seconds': sum(t['seconds'] for t in prefix_transport if X.number(t.get('seconds')))},
            'composite_calls': len(prefix_transport)+len(transport),
            'composite_known_tokens': X.usage(prefix_transport)['known_tokens']+X.usage(transport)['known_tokens']})
    unfinished = order[len(saved):]
    if summary:
        active = {'case': unfinished[0], 'arm': ARM} if unfinished else None
        require(summary['unfinished'] == unfinished and summary['interrupted'] == active
                and summary['unattempted'] == order[len(saved)+(active is not None):]
                and (stop == 'completed') == (not unfinished), 'suffix_summary_scope_changed')
    expected_files = {r['case']+'.json' for r in saved}
    actual_files = {p.name for p in folder.glob('*.json') if p.name not in ('summary.json', 'run-limits.json')
                    and not p.name.endswith(('.pending-before.json', '.done-after.json', '.error.json'))}
    require(actual_files == expected_files, 'suffix_row_file_scope_changed')
    groups = {stratum: X.aggregate([r for r in sanitized if stratum == 'all' or r['stratum'] == stratum],
        sum(stratum == 'all' or p['stratum'] == stratum for p in preparation)) for stratum in ('failed', 'new', 'all')}
    original = plan['original_online_cost']
    full = {key: original[key]+marginal[key] for key in ('calls', 'attempted_sends', 'input_tokens',
            'output_tokens', 'known_tokens', 'real_transport_seconds')}
    full['wall_seconds'] = original['wall_seconds']+marginal['wall_seconds'] if X.number(marginal['wall_seconds']) else 'unobserved'
    for key in ('input_tokens_complete', 'output_tokens_complete'):
        full[key] = original[key] and marginal[key]
    offline = plan['original_offline_cost']
    full_experiment = {key: full[key]+offline[key] for key in
        ('calls', 'attempted_sends', 'input_tokens', 'output_tokens', 'known_tokens', 'real_transport_seconds')}
    full_experiment['wall_seconds'] = full['wall_seconds']+offline['wall_seconds'] if X.number(full['wall_seconds']) else 'unobserved'
    for key in ('input_tokens_complete', 'output_tokens_complete'):
        full_experiment[key] = full[key] and offline[key]
    return {'verification': 'locked_inputs_and_exact_cached_prefix_suffix_replay_passed',
        'gate': GATE, 'final_gate': .7, 'stop': stop, 'rows': sanitized, 'groups': groups,
        'unfinished': unfinished, 'interrupted': interrupted, 'skipped': plan['skipped'],
        'marginal_suffix_cost': marginal, 'original_online_cost': original,
        'full_online_experiment_cost': full, 'original_offline_build_cost': offline,
        'full_experiment_cost_including_offline_build': full_experiment,
        'completed_composite_cost': {'calls': sum(r['composite_calls'] for r in sanitized),
            'known_tokens': sum(r['composite_known_tokens'] for r in sanitized)},
        'qualifications': {'prefix': 'historical root judgments reused exactly; no root reruns',
            'latency': 'New suffix wall time excludes cached prefix; no fresh end-to-end latency measured.',
            'skipped': 'Original .2 pass is excluded and unverified at .65.',
            'new': 'Three new cases were previously exposed; this is not unseen validation.',
            'comparison': 'Gate and suffix policy changed; no organization-only advantage established.',
            'backend_model_revision': 'unobservable', 'full_catalog_scaling': 'unverified'}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['freeze', 'run', 'analyze'])
    parser.add_argument('--trial'); parser.add_argument('--output', required=True)
    parser.add_argument('--analysis'); parser.add_argument('--diagnostics'); parser.add_argument('--report')
    args = parser.parse_args()
    if args.operation == 'freeze':
        if not all((args.trial, args.analysis, args.diagnostics)):
            parser.error('freeze requires --trial --analysis --diagnostics --output')
        result = str(freeze(args.trial, args.output, args.analysis, args.diagnostics))
    else:
        result = globals()[args.operation](args.output)
    if args.report:
        write_once(args.report, result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
