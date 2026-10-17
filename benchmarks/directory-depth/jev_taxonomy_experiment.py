"""One-shot frozen taxonomy pilot with receipt-only, provider-free replay.

Only catalog organization varies. Both arms call the unchanged directory router;
references are read only for post-selection grades. There is no query encoder.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import time

import numpy as np

import jev_directory_experiment as E
import jev_directory_route as D
import jev_directory_tree as T
from experiment import JevHierarchyProvider, read, write_once
from semantic_index import digest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARMS = ['balanced', 'semantic']
BUILD_LIMITS = {'max_calls': 64, 'max_tokens': 240000, 'max_seconds': 180,
                'call_timeout_seconds': 20}
LIVE_LIMITS = {'max_calls': 64, 'max_tokens': 240000, 'max_seconds': 240,
               'call_timeout_seconds': 20}
POLICY = {'directory_gate': .2, 'final_gate': .7, 'final_limit': 128,
          'question_batch': 64, 'per_need_max_calls': 8,
          'build_batch_size': 32, 'build_max_payload_bytes': 64000, 'build_split_above': 128,
          'attempts': 1, 'retries': 0}
STOPPING = 'Unknown outcome or usage stops; no retry, fallback, gold dispatch gate or threshold tuning.'


def require(condition, code):
    if not condition:
        raise ValueError(code)


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def same_number(left, right):
    return number(left) and number(right) and math.isclose(left, right, abs_tol=1e-8, rel_tol=1e-8)


def sources():
    paths = list(HERE.glob('*.py')) + list(HERE.glob('*cases.json'))
    paths += [HERE/'jev_taxonomy.json', ROOT/'core/jev_hierarchy_provider.py']
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(set(paths))}


def builder():
    # Lazy import keeps freeze and read-only source verification model-free.
    import jev_taxonomy_build
    return jev_taxonomy_build


def unpack_built(value):
    if isinstance(value, dict):
        return value['nodes'], value['assignments'], value.get('calls')
    nodes, assignments, calls = value
    return nodes, assignments, calls


def classify(rows, taxonomy, call):
    return unpack_built(builder().classify(rows, taxonomy, call,
        batch_size=POLICY['build_batch_size'], max_payload_bytes=POLICY['build_max_payload_bytes'],
        split_above=POLICY['build_split_above']))


def freeze(root, cases_path, taxonomy_path, previous):
    """Consume precomputed catalog vectors, never load a query model/index."""
    root, cases_path, taxonomy_path, previous = map(lambda p: Path(p).resolve(),
                                                  (root, cases_path, taxonomy_path, previous))
    previous_plan = read(previous/'plan.json')
    prior = E.previous_inputs(previous, previous_plan['bundle'])
    rows = read(root/'sample-catalog.json')
    sample = read(root/'sample-plan.json')
    document = read(cases_path)
    cases = E.validate_cases(document.get('cases') if isinstance(document, dict) else document, previous, rows)
    require(type(sample.get('sample_count')) is int and sample['sample_count'] > 128
            and len(rows) == sample['sample_count'] and len({r['id'] for r in rows}) == len(rows),
            'invalid_sample_count_or_canonical_rows')
    counts = dict(Counter(r['kind'] for r in rows))
    require(counts == sample['sampled_kind_counts'] and sum(counts.values()) == sample['sample_count'],
            'sample_kind_counts_changed')
    if 'target_counts' in sample:
        require(counts == sample['target_counts'], 'sample_target_counts_changed')
    taxonomy = read(taxonomy_path)
    inputs = [root/'sample-catalog.json', root/'sample-vectors.npy', root/'sample-plan.json',
              cases_path, taxonomy_path, previous/'plan.json', previous/'cases.json',
              previous/'live/summary.json', Path(prior['executable'])]
    locks = dict(sample['locks'])
    locks.update({str(p): digest(p) for p in inputs})
    _, history_locks = E.historical_cases(previous, Path(prior['bundle']))
    locks.update(history_locks)
    # Retain earlier external and frozen bundles pointwise; newly added sources
    # need not have existed when the previous experiment was frozen.
    locks.update(prior.get('locks', {}))
    locks.update({str(previous/p): sha for p, sha in prior.get('frozen_sha256', {}).items()})
    for path, sha in locks.items():
        require(Path(path).is_absolute() and digest(path) == sha, 'sample_or_previous_input_changed')
    source_hashes = sources()
    began = time.monotonic()
    vectors = np.load(root/'sample-vectors.npy', allow_pickle=False)
    nodes = T.build(rows, vectors, 16, 24)
    cold_seconds = time.monotonic()-began
    out = root/'trial'
    out.mkdir(mode=0o700, exist_ok=False)
    for name, value in [('rows.json', rows), ('cases.json', cases), ('taxonomy.json', taxonomy),
                        ('balanced-nodes.json', nodes), ('sample-plan.json', sample)]:
        write_once(out/name, value)
    require(source_hashes == sources() and all(digest(p) == sha for p, sha in locks.items()),
            'input_changed_during_freeze')
    plan = {'version': 1, 'arms': ARMS, 'previous': str(previous), 'locks': locks,
            'source_sha256': source_hashes,
            'frozen_sha256': {p.name: digest(p) for p in out.glob('*.json')},
            'executable': prior['executable'], 'executable_sha256': prior['executable_sha256'],
            'build_limits': BUILD_LIMITS, 'live_limits': LIVE_LIMITS, 'policy': POLICY,
            'stopping_policy': STOPPING, 'balanced_cold_build_seconds': cold_seconds,
            'source_catalog_count': sample.get('source_catalog_count'),
            'sampled_kind_counts': sample['sampled_kind_counts'], 'sample_count': sample['sample_count'],
            'case_order': [c['id'] for c in cases],
            'budget_basis': 'ceil(UTF8 payload bytes/2)+80*questions+2500 before every send',
            'backend_model_revision': 'unobservable', 'runtime_readiness': 'unobservable',
            'full_catalog_scaling': 'unverified'}
    write_once(out/'plan.json', plan)
    return out


def verify(trial):
    trial = Path(trial)
    plan = read(trial/'plan.json')
    require(plan['source_sha256'] == sources(), 'frozen_sources_changed')
    for path, sha in plan['locks'].items():
        require(digest(path) == sha, 'external_input_changed')
    for path, sha in plan['frozen_sha256'].items():
        require(digest(trial/path) == sha, 'frozen_input_changed')
    require(plan['arms'] == ARMS and plan['build_limits'] == BUILD_LIMITS
            and plan['live_limits'] == LIVE_LIMITS and plan['policy'] == POLICY
            and plan['stopping_policy'] == STOPPING, 'frozen_policy_changed')
    require(digest(plan['executable']) == plan['executable_sha256'], 'provider_changed')
    return plan


def usage(transport):
    totals = {}
    for key in ('input_tokens', 'output_tokens'):
        values = [t[key] for t in transport if type(t.get(key)) is int and t[key] >= 0]
        totals[key] = sum(values)
        totals[key+'_complete'] = len(values) == len(transport)
    totals['known_tokens'] = totals['input_tokens']+totals['output_tokens']
    return totals


class Recorder:
    """Shared bounded callback; a pre-send receipt is the only send permission."""
    def __init__(self, folder, plan, limits, used=None):
        self.folder, self.limits = Path(folder), limits
        self.used = used or {'attempted_sends': 0, 'known_tokens': 0, 'wall_seconds': 0.}
        self.started = time.monotonic()
        self.remaining_seconds = max(0., limits['max_seconds']-self.used['wall_seconds'])
        self.deadline = self.started+self.remaining_seconds
        self.provider = JevHierarchyProvider({'executable': plan['executable'],
            'timeout_seconds': limits['call_timeout_seconds']}, deadline=self.deadline)
        self.receipts, self.transport = [], []
        self.active, self.local = None, []
        write_once(self.folder/'run-limits.json', {'limits': limits, 'prior_usage': self.used,
            'remaining_seconds': self.remaining_seconds})

    def context(self, identity):
        self.active, self.local = identity, []

    def call(self, stage, spec, state):
        require(isinstance(stage, str) and re.fullmatch(r'[A-Za-z0-9_-]+', stage), 'invalid_stage')
        require(stage not in [r['stage'] for r in self.local], 'duplicate_stage')
        if self.active != {'build': True}:
            require(re.fullmatch(r'final|directory-[1-9][0-9]*-batch-[1-9][0-9]*', stage)
                    and len(self.local) < POLICY['per_need_max_calls'], 'stage_call_contract')
        now = time.monotonic()
        if now >= self.deadline:
            raise RuntimeError('time_budget_stop')
        reserve = E.token_reserve(spec, state)
        spent = self.used['known_tokens']+usage(self.transport)['known_tokens']
        ordinal = self.used['attempted_sends']+len(self.receipts)+1
        if ordinal > self.limits['max_calls'] or spent+reserve > self.limits['max_tokens']:
            raise RuntimeError('budget_stop')
        identity = self.active
        prefix = '' if identity == {'build': True} else identity['case']+'--'+identity['arm']+'--'
        stem = self.folder/(prefix+stage)
        pending = {'ordinal': ordinal, 'identity': identity, 'stage': stage,
                   'spec': spec, 'state': state, 'reserved_tokens': reserve,
                   'elapsed_before_send': now-self.started}
        write_once(str(stem)+'.pending-before.json', pending)
        self.receipts.append(pending); self.local.append(pending)
        offset = len(self.provider.calls)
        try:
            answer = self.provider.noul(spec, state)
        except Exception as error:
            transport = self.provider.calls[offset:]
            self.transport.extend(transport)
            write_once(str(stem)+'.error.json', {'ordinal': ordinal, 'stage': stage,
                'error': str(error), 'transport': transport, 'replay': False})
            raise
        transport = self.provider.calls[offset:]
        self.transport.extend(transport)
        write_once(str(stem)+'.done-after.json', {'ordinal': ordinal, 'stage': stage,
            'answer': answer, 'transport': transport})
        if not E.known_usage(transport):
            raise RuntimeError('unknown_usage_or_outcome')
        if self.used['known_tokens']+usage(self.transport)['known_tokens'] > self.limits['max_tokens']:
            raise RuntimeError('actual_token_budget_exceeded')
        return answer

    def summary(self):
        totals = usage(self.transport)
        if len(self.transport) < len(self.receipts):
            totals['input_tokens_complete'] = totals['output_tokens_complete'] = False
        return {'transport': self.transport, 'calls': len(self.transport),
                'attempted_sends': len(self.receipts), **totals,
                'wall_seconds': time.monotonic()-self.started,
                'real_transport_seconds': sum(t['seconds'] for t in self.transport if number(t.get('seconds'))),
                'prior_usage': self.used, 'remaining_seconds': self.remaining_seconds}


def build(trial):
    trial = Path(trial)
    plan = verify(trial)
    folder = trial/'build'; folder.mkdir(mode=0o700, exist_ok=False)
    recorder = Recorder(folder, plan, BUILD_LIMITS)
    recorder.context({'build': True})
    stop, report = 'completed', None
    try:
        nodes, assignments, calls = classify(read(trial/'rows.json'), read(trial/'taxonomy.json'), recorder.call)
        report = builder().validate(nodes, read(trial/'rows.json'))
        write_once(folder/'nodes.json', nodes)
        write_once(folder/'assignments.json', assignments)
        write_once(folder/'classification-calls.json', calls)
    except Exception as error:
        stop = str(error)
    summary = {'stop': stop, 'validation': report, **recorder.summary()}
    write_once(folder/'summary.json', summary)
    if stop == 'completed':
        verify(trial)
        paths = ['nodes.json', 'assignments.json', 'classification-calls.json', 'summary.json']
        write_once(trial/'build-manifest.json', {'sha256': {p: digest(folder/p) for p in paths}})
    return summary


def built(trial):
    trial = Path(trial)
    require((trial/'build-manifest.json').is_file(), 'build_unfinished_no_fallback')
    manifest = read(trial/'build-manifest.json')
    expected = {'nodes.json', 'assignments.json', 'classification-calls.json', 'summary.json'}
    require(set(manifest['sha256']) == expected, 'invalid_build_manifest')
    for name, sha in manifest['sha256'].items():
        require(digest(trial/'build'/name) == sha, 'build_output_changed')
    require(read(trial/'build/summary.json')['stop'] == 'completed', 'build_unfinished_no_fallback')
    nodes = read(trial/'build/nodes.json')
    builder().validate(nodes, read(trial/'rows.json'))
    return nodes


def route(nodes, rows, need, call):
    return D.route(nodes, rows, need, call, final_limit=128, batch_size=64, max_calls=8)


def schedule(cases, stratum):
    return [(case, arm) for number, case in enumerate(cases) if case['stratum'] == stratum
            for arm in ARMS[number % 2:]+ARMS[:number % 2]]


def run(trial, stratum='failed'):
    require(stratum in ('failed', 'new'), 'invalid_stratum')
    trial = Path(trial)
    plan = verify(trial)
    semantic = built(trial)
    used = {'attempted_sends': 0, 'known_tokens': 0, 'wall_seconds': 0.}
    if stratum == 'new':
        require((trial/'live-failed/summary.json').is_file(), 'failed_phase_required_first')
        report = analyze(trial)
        require(report['phases']['failed']['stop'] == 'completed', 'failed_phase_unfinished_no_resume')
        previous = read(trial/'live-failed/summary.json')
        used = {key: previous[key] for key in used}
    folder = trial/('live-'+stratum); folder.mkdir(mode=0o700, exist_ok=False)
    rows, cases = read(trial/'rows.json'), read(trial/'cases.json')
    balanced = read(trial/'balanced-nodes.json'); T.validate(balanced, rows)
    recorder = Recorder(folder, plan, LIVE_LIMITS, used)
    completed, active, stop = [], None, 'completed'
    tasks = schedule(cases, stratum)
    try:
        for case, arm in tasks:
            active = {'case': case['id'], 'arm': arm}
            recorder.context(active)
            before, began = len(recorder.transport), time.monotonic()
            result = route(balanced if arm == 'balanced' else semantic, rows, case['need'], recorder.call)
            transport = recorder.transport[before:]
            item = {**active, 'stratum': stratum, 'result': result, **E.grade(case, result, None),
                    'transport': transport, 'calls': len(transport), **usage(transport),
                    'attempted_sends': len(recorder.local), 'stages': [r['stage'] for r in recorder.local],
                    'wall_seconds': time.monotonic()-began}
            write_once(folder/(case['id']+'--'+arm+'.json'), item)
            completed.append(item); active = None
    except Exception as error:
        stop = str(error)
    summary = {'stop': stop, 'stratum': stratum, 'rows': completed,
               'interrupted': active, 'unfinished': [{'case': case['id'], 'arm': arm}
                    for case, arm in tasks[len(completed):]], **recorder.summary()}
    write_once(folder/'summary.json', summary)
    return summary


class ReplayStop(Exception):
    pass


def load_receipts(folder, limits, prior):
    receipts, stems = [], set()
    for path in Path(folder).glob('*.pending-before.json'):
        stem = str(path)[:-len('.pending-before.json')]; stems.add(stem)
        pending = read(path)
        done, error = Path(stem+'.done-after.json'), Path(stem+'.error.json')
        require(not (done.exists() and error.exists()), 'conflicting_receipt_outcomes')
        kind = 'done' if done.exists() else 'error' if error.exists() else 'pending'
        outcome = read(done if done.exists() else error) if kind != 'pending' else None
        require(type(pending.get('ordinal')) is int, 'invalid_receipt_ordinal')
        require(pending.get('reserved_tokens') == E.token_reserve(pending['spec'], pending['state']),
                'receipt_reserve_mismatch')
        elapsed = pending.get('elapsed_before_send')
        require(number(elapsed) and elapsed < max(0., limits['max_seconds']-prior['wall_seconds']),
                'send_exceeded_recorded_deadline')
        transport = [] if outcome is None else outcome.get('transport')
        require(isinstance(transport, list) and len(transport) <= 1
                and all(isinstance(t, dict) for t in transport), 'invalid_receipt_transport')
        for t in transport:
            require(t.get('seconds') is None or number(t['seconds']), 'invalid_transport_seconds')
            for key in ('input_tokens', 'output_tokens'):
                require(key not in t or type(t[key]) is int and t[key] >= 0, 'invalid_transport_usage')
        if outcome is not None:
            require(outcome.get('ordinal') == pending['ordinal'] and outcome.get('stage') == pending['stage'],
                    'receipt_outcome_identity_mismatch')
        if kind == 'error':
            require(outcome.get('replay') is False and isinstance(outcome.get('error'), str), 'invalid_error_receipt')
        receipts.append({'pending': pending, 'outcome': outcome, 'kind': kind, 'transport': transport})
    for suffix in ('.done-after.json', '.error.json'):
        require(all(str(p)[:-len(suffix)] in stems for p in Path(folder).glob('*'+suffix)), 'orphan_outcome_receipt')
    receipts.sort(key=lambda r: r['pending']['ordinal'])
    start = prior['attempted_sends']+1
    require([r['pending']['ordinal'] for r in receipts] == list(range(start, start+len(receipts))),
            'nonsequential_receipt_ordinals')
    spent = prior['known_tokens']
    for index, receipt in enumerate(receipts):
        p = receipt['pending']
        require(p['ordinal'] <= limits['max_calls'] and spent+p['reserved_tokens'] <= limits['max_tokens'],
                'send_exceeded_frozen_budget')
        spent += usage(receipt['transport'])['known_tokens']
        receipt['spent_after'] = spent
        if receipt['kind'] != 'done' or not E.known_usage(receipt['transport']) or spent > limits['max_tokens']:
            require(index == len(receipts)-1, 'send_after_unknown_or_error')
    return receipts


class Replay:
    def __init__(self, receipts, identity, stop=None, *, limits=None, prior=None, total=None):
        self.receipts, self.identity, self.stop, self.cursor = receipts, identity, stop, 0
        self.limits, self.prior, self.total = limits, prior, total

    def call(self, stage, spec, state):
        if self.cursor >= len(self.receipts):
            if self.stop is not None:
                if self.stop == 'budget_stop':
                    require(self.prior['attempted_sends']+self.total['attempted_sends'] >= self.limits['max_calls']
                            or self.prior['known_tokens']+self.total['known_tokens']+E.token_reserve(spec, state)
                            > self.limits['max_tokens'], 'unjustified_budget_stop')
                elif self.stop == 'time_budget_stop':
                    require(number(self.total['wall_seconds'])
                            and self.prior['wall_seconds']+self.total['wall_seconds'] >= self.limits['max_seconds'],
                            'unjustified_time_budget_stop')
                else:
                    require(self.stop == 'unobserved_interruption', 'missing_terminal_receipt')
                raise ReplayStop('unrecorded_next_send')
            raise ValueError('missing_stage_receipt')
        receipt = self.receipts[self.cursor]; self.cursor += 1
        pending, outcome = receipt['pending'], receipt['outcome']
        require(pending['identity'] == self.identity and pending['stage'] == stage
                and pending['spec'] == spec and pending['state'] == state, 'replay_payload_or_stage_mismatch')
        if receipt['kind'] == 'pending':
            raise ReplayStop('pending_outcome_unobserved')
        if receipt['kind'] == 'error':
            raise ReplayStop(outcome['error'])
        if not E.known_usage(receipt['transport']):
            raise ReplayStop('unknown_usage_or_outcome')
        if self.limits and receipt['spent_after'] > self.limits['max_tokens']:
            raise ReplayStop('actual_token_budget_exceeded')
        return outcome['answer']

    def consumed(self):
        require(self.cursor == len(self.receipts), 'unused_stage_receipts')


def verified_summary(folder, receipts, limits, prior):
    folder = Path(folder)
    recorded = read(folder/'run-limits.json')
    require(recorded == {'limits': limits, 'prior_usage': prior,
        'remaining_seconds': max(0., limits['max_seconds']-prior['wall_seconds'])}, 'recorded_limits_changed')
    summary = read(folder/'summary.json') if (folder/'summary.json').exists() else None
    transport = [t for receipt in receipts for t in receipt['transport']]
    totals = usage(transport)
    if len(transport) < len(receipts):
        totals['input_tokens_complete'] = totals['output_tokens_complete'] = False
    if summary is not None:
        require(summary.get('transport') == transport and summary.get('calls') == len(transport)
                and summary.get('attempted_sends') == len(receipts)
                and all(summary.get(k) == v for k, v in totals.items())
                and summary.get('prior_usage') == prior
                and summary.get('remaining_seconds') == recorded['remaining_seconds'], 'summary_accounting_mismatch')
        require(number(summary.get('wall_seconds')) and same_number(summary.get('real_transport_seconds'),
            sum(t['seconds'] for t in transport if number(t.get('seconds')))), 'summary_timing_mismatch')
    return summary, {'calls': len(transport), 'attempted_sends': len(receipts), **totals,
                     'wall_seconds': summary['wall_seconds'] if summary else 'unobserved',
                     'real_transport_seconds': sum(t['seconds'] for t in transport if number(t.get('seconds')))}


def pools(case, result):
    traces = []
    for index, trace in enumerate(result.get('traces', []), 1):
        pool = set(trace.get('pool', []))
        traces.append({'stage': trace['stage'], 'ordinal': index, 'pool_size': len(pool),
            'current_covered': bool(pool & set(case['acceptable_current_ids'])),
            'later_covered': [bool(pool & set(group)) for group in case['pending_groups']],
            'primary_current_covered': case['primary_current_id'] in pool,
            'primary_later_covered': [key in pool for key in case['primary_pending_ids']]})
    frontiers = [t for t in traces if t['stage'] == 'directory']
    finals = [t for t in traces if t['stage'] == 'final_pool']
    return {'observed_pools': traces, 'reached_final': bool(finals),
            'last_frontier': frontiers[-1] if frontiers else None,
            'actual_final_pool': finals[-1] if finals else None}


def aggregate(rows, expected):
    def rate(count, total):
        return {'correct': count, 'total': total, 'rate': count/total if total else None}
    later_total = sum(len(r['later_group_coverage']) for r in rows)
    finals = [r['actual_final_pool'] for r in rows if r['reached_final']]
    final_later_total = sum(len(pool['later_covered']) for pool in finals)
    return {'completed_rows': len(rows), 'planned_rows': expected,
        'known_positive_accuracy': rate(sum(r['correct_current'] for r in rows), len(rows)),
        'omission_safe_accuracy': rate(sum(r['omission_safe_pass'] for r in rows), len(rows)),
        'current_retained_pool_coverage': rate(sum(r['current_in_final_pool'] for r in rows), len(rows)),
        'reached_final_rows': len(finals),
        'actual_final_pool_current_coverage': rate(sum(pool['current_covered'] for pool in finals), len(finals)),
        'actual_final_pool_later_group_coverage': rate(sum(sum(pool['later_covered']) for pool in finals), final_later_total),
        'later_group_coverage': rate(sum(sum(r['later_group_coverage']) for r in rows), later_total),
        'primary_reference_coverage': rate(sum(r['all_primary_references_retained'] for r in rows), len(rows)),
        'status_counts': dict(Counter(r['status'] for r in rows)),
        **{k: sum(r[k] for r in rows) for k in ('calls', 'input_tokens', 'output_tokens', 'known_tokens', 'wall_seconds')}}


def analyze(trial):
    """Replay exact tasks, metadata, wire maps and answers; never send anything."""
    trial = Path(trial)
    plan = verify(trial)
    rows, cases, taxonomy = read(trial/'rows.json'), read(trial/'cases.json'), read(trial/'taxonomy.json')
    balanced = read(trial/'balanced-nodes.json'); T.validate(balanced, rows)
    zero = {'attempted_sends': 0, 'known_tokens': 0, 'wall_seconds': 0.}
    folder = trial/'build'
    require(folder.is_dir(), 'build_not_started')
    receipts = load_receipts(folder, BUILD_LIMITS, zero)
    build_summary, offline_cost = verified_summary(folder, receipts, BUILD_LIMITS, zero)
    build_stop = build_summary['stop'] if build_summary else 'unobserved_interruption'
    replay = Replay(receipts, {'build': True}, None if build_stop == 'completed' else build_stop,
                    limits=BUILD_LIMITS, prior=zero, total=offline_cost)
    semantic = None; build_replay_stop = None
    try:
        nodes, assignments, calls = classify(rows, taxonomy, replay.call)
    except ReplayStop as error:
        require(build_stop != 'completed', 'completed_build_replay_failed')
        build_replay_stop = str(error)
        require(build_stop == build_replay_stop or build_replay_stop in
                ('unrecorded_next_send', 'pending_outcome_unobserved') and build_summary is None
                or build_replay_stop == 'unrecorded_next_send' and build_stop in ('budget_stop', 'time_budget_stop'),
                'build_stop_mismatch')
    except ValueError as error:
        if str(error).startswith(('replay_', 'missing_', 'unused_', 'unjustified_')):
            raise
        require(build_stop == str(error), 'build_stop_mismatch')
        build_replay_stop = str(error)
    else:
        require(build_stop == 'completed', 'unfinished_build_replayed_complete')
        semantic = built(trial)
        require(nodes == semantic and assignments == read(folder/'assignments.json')
                and calls == read(folder/'classification-calls.json'), 'replay_build_output_mismatch')
        require(builder().validate(nodes, rows) == build_summary['validation'], 'build_validation_changed')
    replay.consumed()
    phases, sanitized, prior = {}, [], zero
    for stratum in ('failed', 'new'):
        folder = trial/('live-'+stratum)
        if not folder.exists():
            continue
        require(semantic is not None, 'online_without_completed_build')
        if stratum == 'new':
            require(phases.get('failed', {}).get('stop') == 'completed', 'new_after_unfinished_failed')
        tasks = schedule(cases, stratum)
        receipts = load_receipts(folder, LIVE_LIMITS, prior)
        summary, cost = verified_summary(folder, receipts, LIVE_LIMITS, prior)
        stop = summary['stop'] if summary else 'unobserved_interruption'
        saved = summary['rows'] if summary else []
        if summary is None:
            # A process can die after a row was durably written but before the
            # phase summary. Recover only the consecutive observed prefix.
            for case, arm in tasks:
                path = folder/(case['id']+'--'+arm+'.json')
                if not path.exists():
                    break
                saved.append(read(path))
        keys = [{'case': case['id'], 'arm': arm} for case, arm in tasks]
        require([{k: item[k] for k in ('case', 'arm')} for item in saved] == keys[:len(saved)], 'row_schedule_changed')
        if summary:
            require(summary.get('stratum') == stratum and summary.get('unfinished') == keys[len(saved):], 'unfinished_scope_changed')
            require(summary.get('interrupted') == (keys[len(saved)] if len(saved) < len(keys) else None), 'interrupted_scope_changed')
            require((stop == 'completed') == (len(saved) == len(keys)), 'phase_completion_mismatch')
        by_identity = {tuple(key.values()): [] for key in keys}
        previous_position = -1
        for receipt in receipts:
            identity = receipt['pending']['identity']
            require(identity in keys, 'receipt_outside_phase')
            position = keys.index(identity)
            require(position >= previous_position, 'receipt_schedule_changed'); previous_position = position
            by_identity[(identity['case'], identity['arm'])].append(receipt)
        active_report = None
        allowed = keys[:len(saved)+1] if len(saved) < len(keys) else keys
        require(all(r['pending']['identity'] in allowed for r in receipts), 'receipt_after_interrupted_arm')
        for index, (case, arm) in enumerate(tasks[:min(len(tasks), len(saved)+1)]):
            identity = keys[index]
            local = by_identity[(case['id'], arm)]
            complete = index < len(saved)
            replay = Replay(local, identity, None if complete else stop,
                            limits=LIVE_LIMITS, prior=prior, total=cost)
            result, interrupted_reason = None, None
            try:
                result = route(balanced if arm == 'balanced' else semantic, rows, case['need'], replay.call)
            except ReplayStop as error:
                require(not complete, 'completed_arm_replay_failed'); interrupted_reason = str(error)
                require(stop == interrupted_reason or interrupted_reason in
                        ('unrecorded_next_send', 'pending_outcome_unobserved') and summary is None
                        or interrupted_reason == 'unrecorded_next_send' and stop in ('budget_stop', 'time_budget_stop'),
                        'runtime_stop_mismatch')
            except ValueError as error:
                if str(error).startswith(('replay_', 'missing_', 'unused_', 'unjustified_')):
                    raise
                require(not complete and stop == str(error), 'runtime_stop_mismatch'); interrupted_reason = str(error)
            replay.consumed()
            if not complete:
                require(result is None, 'interrupted_arm_replayed_complete')
                active_report = {**identity, 'reported_stop': stop, 'replay_stop': interrupted_reason,
                    'grade': 'unobserved', 'coverage': 'unobserved'}
                continue
            item = saved[index]
            require(read(folder/(case['id']+'--'+arm+'.json')) == item, 'row_file_changed')
            grades = E.grade(case, result, None)
            require(item['result'] == result and item['stratum'] == stratum
                    and all(item.get(k) == v for k, v in grades.items()), 'replay_result_trace_or_grade_changed')
            transport = [t for receipt in local for t in receipt['transport']]
            require(item['transport'] == transport and item['calls'] == len(transport)
                    and item['attempted_sends'] == len(local)
                    and item['stages'] == [r['pending']['stage'] for r in local]
                    and all(item.get(k) == v for k, v in usage(transport).items())
                    and number(item.get('wall_seconds')), 'row_accounting_changed')
            sanitized.append({**identity, 'stratum': stratum, 'status': result['status'],
                'choice': result.get('choice'), 'confidence': result.get('confidence'), **grades,
                **pools(case, result), 'calls': item['calls'], **usage(transport), 'wall_seconds': item['wall_seconds']})
        expected_files = {item['case']+'--'+item['arm']+'.json' for item in saved}
        actual_files = {p.name for p in folder.glob('*.json') if '--' in p.name
                        and not p.name.endswith(('.pending-before.json', '.done-after.json', '.error.json'))}
        require(actual_files == expected_files, 'row_file_scope_changed')
        phases[stratum] = {'stop': stop, 'cost': cost, 'interrupted': active_report,
                          'unfinished': keys[len(saved):]}
        if summary:
            prior = {key: prior[key]+summary[key] for key in zero}
    groups = {}
    for stratum in ('failed', 'new', 'all'):
        selected = [r for r in sanitized if stratum == 'all' or r['stratum'] == stratum]
        expected = sum(stratum == 'all' or c['stratum'] == stratum for c in cases)
        paired = {r['case'] for r in selected if sum(s['case'] == r['case'] for s in selected) == 2}
        wins = Counter()
        for case_id in paired:
            pair = {r['arm']: r['omission_safe_pass'] for r in selected if r['case'] == case_id}
            wins['tie' if len(set(pair.values())) == 1 else next(a for a in ARMS if pair[a])] += 1
        groups[stratum] = {'arms': {arm: aggregate([r for r in selected if r['arm'] == arm], expected) for arm in ARMS},
            'paired_completed': {'cases': len(paired), 'omission_safe_wins': dict(wins),
                'arms': {arm: aggregate([r for r in selected if r['arm'] == arm and r['case'] in paired], len(paired)) for arm in ARMS}}}
    paired_rows = [r for r in sanitized if sum(s['case'] == r['case'] for s in sanitized) == 2]
    savings = sum(r['known_tokens']*(1 if r['arm'] == 'balanced' else -1) for r in paired_rows)
    paired_count = len(paired_rows)//2
    token_break_even = math.ceil(offline_cost['known_tokens']/(savings/paired_count)) if paired_count and savings > 0 else None
    return {'version': 1, 'verification': 'frozen_inputs_and_exact_receipt_replay_passed',
        'build': {'stop': build_stop, 'replay_stop': build_replay_stop, 'cost': offline_cost},
        'phases': phases, 'groups': groups, 'rows': sanitized,
        'online_cost': {key: sum(p['cost'][key] for p in phases.values()) for key in
            ('calls', 'attempted_sends', 'input_tokens', 'output_tokens', 'known_tokens', 'real_transport_seconds')}
            | {key+'_complete': all(p['cost'][key+'_complete'] for p in phases.values())
                for key in ('input_tokens', 'output_tokens')}
            | {'wall_seconds': sum(p['cost']['wall_seconds'] for p in phases.values())
                if all(number(p['cost']['wall_seconds']) for p in phases.values()) else 'unobserved'},
        'cold_balanced_build_seconds': plan['balanced_cold_build_seconds'],
        'token_break_even_additional_cases': token_break_even,
        'limits': {'build': BUILD_LIMITS, 'online_shared_across_phases': LIVE_LIMITS, **POLICY},
        'qualifications': {'full_catalog_scaling': 'unverified', 'backend_model_revision': 'unobservable',
            'runtime_readiness': 'unobservable', 'deadline_provenance': 'recorded_local_elapsed_timestamps',
            'interrupted_grades': 'unobserved; excluded from observed accuracy denominators',
            'break_even': 'token-only estimate from completed pairs; accuracy and future workload may differ'}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['freeze', 'build', 'run', 'analyze'])
    parser.add_argument('--root'); parser.add_argument('--cases'); parser.add_argument('--taxonomy')
    parser.add_argument('--previous'); parser.add_argument('--trial'); parser.add_argument('--output')
    parser.add_argument('--stratum', choices=['failed', 'new'], default='failed')
    args = parser.parse_args()
    if args.operation == 'freeze':
        if not all((args.root, args.cases, args.taxonomy, args.previous)):
            parser.error('freeze requires --root --cases --taxonomy --previous')
        result = str(freeze(args.root, args.cases, args.taxonomy, args.previous))
    else:
        if not args.trial:
            parser.error(args.operation+' requires --trial')
        result = run(args.trial, args.stratum) if args.operation == 'run' else globals()[args.operation](args.trial)
    if args.output:
        write_once(args.output, result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
