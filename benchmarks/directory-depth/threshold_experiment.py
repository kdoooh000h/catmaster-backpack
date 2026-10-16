"""Frozen threshold/prompt ablation; reuse the old passing baseline without sends."""
import argparse
import json
from pathlib import Path
import time

import adaptive_experiment as A
from adaptive_cost_experiment import ROOT, digest
from adaptive_threshold import ARMS, MIN_GAP, MAX_RAISE, PRESSURE_LIMIT, select
from experiment import JevHierarchyProvider, grade, identity, read, write_once

FAILED = 'finance_packages_then_wiki'
FIXTURES = Path(__file__).with_name('threshold_cases.json')


def validate_cases(prior, previous_rows, additions, catalog, historical):
    by_id = {c['id']: c for c in prior}
    old = [r for r in previous_rows if r['case'] == FAILED]
    if not any(r['arm'] == 'early_stop' and r['result'].get('reason') == 'final_limit' for r in old):
        raise ValueError('failed_scope_changed')
    baseline = [r for r in old if r['arm'] == 'described']
    if len(baseline) != 1 or not baseline[0]['omission_safe_pass']:
        raise ValueError('passing_baseline_missing')
    if len(additions) != 4 or len({c['id'] for c in additions}) != 4 or len({c['need'] for c in additions}) != 4:
        raise ValueError('new_case_set_changed')
    ids, needs = {c['id'] for c in prior + historical}, {c['need'] for c in prior + historical}
    catalog_ids = {r['id'] for r in catalog}
    for case in additions:
        if case['id'] in ids or case['need'] in needs: raise ValueError('previous_case_reuse')
        required = case['expected_ids'] + case['pending_ids']
        if len(case['expected_ids']) != 1 or not case['pending_ids'] or case['control']:
            raise ValueError('invalid_multi_step_gold')
        if len(required) != len(set(required)) or not set(required) <= catalog_ids:
            raise ValueError('invalid_required_targets')
        if any(key.lower() in case['need'].lower() for key in catalog_ids if '-' in key):
            raise ValueError('named_skill_in_need')
        if set(required) & set(case.get('forbidden_current_ids', [])): raise ValueError('conflicting_gold')
    return [by_id[FAILED]] + additions, baseline[0]


def freeze(source, output):
    source, output = Path(source), Path(output)
    previous = read(source / 'plan.json')
    for name, sha in previous['input_sha256'].items():
        if digest(source / name) != sha: raise ValueError('source_input_changed')
    for name, sha in previous['source_sha256'].items():
        if digest(ROOT / name) != sha: raise ValueError('source_code_changed')
    summary = read(source.parent / 'live/summary.json')
    if summary['stop'] != 'completed': raise ValueError('previous_run_incomplete')
    catalog = read(source / 'catalog.json')
    historical = []
    for name in ('breadth_cases.json', 'large_public_cases.json', 'expanded_cases.json', 'current_step_cases.json', 'culture_scope_cases.json'):
        historical += read(Path(__file__).with_name(name))['cases']
    cases, reused = validate_cases(read(source / 'cases.json'), summary['rows'], read(FIXTURES)['cases'], catalog, historical)
    by_id = {r['id']: r for r in catalog}
    for case in cases[1:]:
        case['gold_sources'] = [{'id': key, 'source': by_id[key]['source'], 'description': by_id[key]['description']}
                               for key in case['expected_ids'] + case['pending_ids']]
    output.mkdir(mode=0o700, exist_ok=False)
    for name in ('catalog.json', 'candidate-nodes.json', 'question.json'):
        with (output / name).open('xb') as stream: stream.write((source / name).read_bytes())
    write_once(output / 'cases.json', cases)
    write_once(output / 'reused-baseline.json', reused)
    sources = list(previous['source_sha256']) + ['benchmarks/directory-depth/' + name for name in
        ('adaptive_threshold.py', 'threshold_experiment.py', 'threshold_cases.json')]
    plan = {'version': 1, 'arms': ARMS, 'case_count': len(cases), 'repetitions': 1,
        'case_order': [c['id'] for c in cases], 'original_failed_case_ids': [FAILED],
        'case_arms': {c['id']: ARMS[1:] if c['id'] == FAILED else ARMS for c in cases},
        'primary_comparison': 'Four new cases, three fresh arms. The old failed need gets two new arms only; its previously passing description baseline is reused and excluded from paired live aggregates.',
        'baseline_plan_sha256': digest(source / 'plan.json'),
        'baseline_results_sha256': digest(source.parent / 'live/summary.json'),
        'base_commit': 'e8cd61c679d10019572b3ade9fe98300927df04e',
        'same_membership_and_descriptions': True, 'same_raw_need_and_final_question': True,
        'directory_gates': previous['directory_gates'], 'final_gate': A.FINAL_GATE,
        'adaptive_gate_policy': {'pressure_limit': PRESSURE_LIMIT, 'min_gap': MIN_GAP, 'max_raise': MAX_RAISE, 'first_adaptive_depth': 3},
        'final_limit': A.FINAL_LIMIT, 'max_rounds': A.MAX_ROUNDS,
        'reading_cost_ratio': .65, 'max_calls': 98, 'max_known_tokens': 380000, 'max_seconds': 240,
        'timeout_seconds': 15, 'executable': previous['executable'], 'executable_sha256': digest(previous['executable']),
        'provider': 'typesafe', 'attempts': 1,
        'ordering': 'Old failure once per new candidate, then four new cases with rotating three-arm order; no passed-arm replay.',
        'scope': 'Public isolated directory experiment; no runtime install, private catalog or other worktree writes.',
        'changes': {'baseline': 'Accepted description repairs and current-step selector unchanged.',
                    'adaptive_gate': 'Raise only depth >=3 Noul retention gates by <=0.1 when retained pool >96 and adjacent score gap >=0.12; never normalize independent Nouls or force top-k.',
                    'adaptive_focus': 'Same adaptive gates; structured Noul asks about performing a concrete required action rather than domain similarity. Original state/rules, scope text, final Choice and estimator unchanged.'},
        'acceptance': 'All current references selected at >=0.7 and every current/later reference retained throughout all five cases. Only all-pass candidates eligible for promotion; compare costs on the four fresh complete triplets. No retry or post-live tuning.',
        'token_cap': 'Checked before dispatch; one response can cross it. Unknown send/usage or malformed response stops all remaining sends.',
        'limitations': 'One prior boundary failure and four author-written combinations; one sample per arm, not blind or population accuracy. Noul probabilities and Choice confidence are different signals; neither is locally calibrated. Provider backend revision unobservable.',
        'source_sha256': {name: digest(ROOT / name) for name in sources},
        'input_sha256': {path.name: digest(path) for path in output.glob('*.json')}}
    write_once(output / 'plan.json', plan)
    print(json.dumps({'plan': identity(plan), 'cases': len(cases), 'new_live_rows': 14, 'arms': ARMS}))


def run(bundle, output):
    bundle, output = Path(bundle), Path(output)
    plan = read(bundle / 'plan.json')
    if plan['arms'] != ARMS or plan['final_gate'] != A.FINAL_GATE:
        raise ValueError('frozen_policy_changed')
    for name, sha in plan['input_sha256'].items():
        if digest(bundle / name) != sha: raise ValueError('frozen_input_changed')
    for name, sha in plan['source_sha256'].items():
        if digest(ROOT / name) != sha: raise ValueError('frozen_source_changed')
    rows, nodes, cases, question = [read(bundle / name) for name in
        ('catalog.json', 'candidate-nodes.json', 'cases.json', 'question.json')]
    choices = {row['id']: row['description'] for row in rows} | {'none': question['none']}
    if digest(plan['executable']) != plan['executable_sha256']: raise ValueError('executable_changed')
    output.mkdir(mode=0o700, exist_ok=False)
    began = time.monotonic()
    provider = JevHierarchyProvider({'executable': plan['executable'], 'timeout_seconds': plan['timeout_seconds']},
        deadline=began + plan['max_seconds'])
    completed, calls, spent = [], 0, 0
    def finish(reason):
        write_once(output / 'summary.json', {'rows': completed, 'stop': reason, 'calls': calls,
                   'known_tokens': spent, 'seconds': time.monotonic() - began})
    for index, case in enumerate(cases):
        order = ARMS[index % 3:] + ARMS[:index % 3]
        for arm in [arm for arm in order if arm in plan['case_arms'][case['id']]]:
            prefix = 'r0--' + case['id'] + '--' + arm
            started, offset = time.monotonic(), len(provider.calls)
            def call(stage, spec, state):
                nonlocal calls, spent
                if stage.startswith('boundary'):
                    raise RuntimeError('forbidden_boundary_review')
                if calls >= plan['max_calls'] or spent >= plan['max_known_tokens'] or time.monotonic() - began >= plan['max_seconds']:
                    raise RuntimeError('experiment_budget_stop')
                calls += 1
                path = output / (prefix + '--' + stage)
                write_once(str(path) + '.pending.json', {'spec': spec, 'state': state, 'ordinal': calls, 'at': time.time()})
                first = len(provider.calls)
                try:
                    raw = provider.noul(spec, state)
                except Exception as error:
                    write_once(str(path) + '.error.json', {'error': str(error), 'transport': provider.calls[first:]})
                    raise
                finally:
                    spent += sum(r.get('input_tokens', 0) + r.get('output_tokens', 0) for r in provider.calls[first:])
                receipts = provider.calls[first:]
                write_once(str(path) + '.done.json', {'answer': raw, 'transport': receipts})
                if not receipts or not all('input_tokens' in r and 'output_tokens' in r for r in receipts):
                    raise RuntimeError('unknown_usage_stop')
                return raw
            result = select(arm, nodes, case['need'], choices, question['question'], call)
            receipts = provider.calls[offset:]
            row = {'case': case['id'], 'arm': arm, 'repetition': 0, 'control': case['control'],
                'seconds': time.monotonic() - started, 'calls': len(receipts), 'result': result, 'transport': receipts,
                'known_tokens': sum(r.get('input_tokens', 0) + r.get('output_tokens', 0) for r in receipts),
                'usage_complete': all('input_tokens' in r and 'output_tokens' in r for r in receipts), **grade(case, result)}
            completed.append(row)
            write_once(output / (prefix + '.json'), row)
            print(json.dumps({key: row[key] for key in ('case', 'arm', 'omission_safe_pass', 'seconds', 'calls', 'known_tokens')}
                | {'status': result['status'], 'choice': result.get('choice'), 'reason': result.get('reason')}), flush=True)
            if result.get('reason') not in {None, 'directory_limit', 'final_limit', 'no_progress'} or any(r.get('outcome') != 'completed' for r in receipts):
                finish('budget_or_provider_failure')
                return
    finish('completed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['freeze', 'run'])
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    (freeze if args.operation == 'freeze' else run)(args.source, args.output)
