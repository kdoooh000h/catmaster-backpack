"""Frozen current-step comparison: two failed needs plus six new combinations."""
import argparse
import json
from pathlib import Path
import time

import adaptive_experiment as A
from adaptive_cost_experiment import ROOT, digest
from current_step import select
from experiment import JevHierarchyProvider, grade, identity, read, write_once

ARMS = ['slim', 'current_step']
FAILED = ['multi_culture_then_wiki', 'multi_accounts_then_finance']
FIXTURES = Path(__file__).with_name('current_step_cases.json')


def validate_cases(prior, previous_rows, additions, catalog):
    by_id = {c['id']: c for c in prior}
    failed = {r['case'] for r in previous_rows if r['arm'] == 'slim' and not r['omission_safe_pass']}
    if failed != set(FAILED):
        raise ValueError('failed_scope_changed')
    if len(additions) != 6 or len({c['id'] for c in additions}) != 6:
        raise ValueError('new_case_count_changed')
    old_needs = {c['need'] for c in prior}
    catalog_ids = {r['id'] for r in catalog}
    for case in additions:
        if case['id'] in by_id or case['need'] in old_needs:
            raise ValueError('completed_case_reuse')
        required = case['expected_ids'] + case['pending_ids']
        if len(case['expected_ids']) != 1 or not case['pending_ids'] or case['control']:
            raise ValueError('invalid_multi_step_gold')
        if len(required) != len(set(required)) or not set(required) <= catalog_ids:
            raise ValueError('invalid_required_targets')
        if any(key.lower() in case['need'].lower() for key in catalog_ids if '-' in key):
            raise ValueError('named_skill_in_need')
    return [by_id[key] for key in FAILED] + additions


def freeze(source, output):
    source, output = Path(source), Path(output)
    previous = read(source / 'plan.json')
    for name, sha in previous['input_sha256'].items():
        if digest(source / name) != sha: raise ValueError('source_input_changed')
    for name, sha in previous['source_sha256'].items():
        if digest(ROOT / name) != sha: raise ValueError('source_code_changed')
    prior_summary = read(source.parent / 'live/summary.json')
    if prior_summary['stop'] != 'completed': raise ValueError('previous_run_incomplete')
    catalog, nodes = read(source / 'catalog.json'), read(source / 'repaired-nodes.json')
    cases = validate_cases(read(source / 'cases.json'), prior_summary['rows'], read(FIXTURES)['cases'], catalog)
    if A.union(nodes, ['n']) != {r['id'] for r in catalog}: raise ValueError('coverage_changed')
    by_id = {r['id']: r for r in catalog}
    for case in cases[2:]:
        case['gold_sources'] = [{'id': key, 'source': by_id[key]['source'], 'description': by_id[key]['description']}
            for key in case['expected_ids'] + case['pending_ids']]
    output.mkdir(mode=0o700, exist_ok=False)
    for name in ('catalog.json', 'nodes.json', 'repaired-nodes.json', 'question.json'):
        with (output / name).open('xb') as stream: stream.write((source / name).read_bytes())
    write_once(output / 'cases.json', cases)
    sources = list(previous['source_sha256']) + [
        'benchmarks/directory-depth/current_step.py', 'benchmarks/directory-depth/current_step_experiment.py',
        'benchmarks/directory-depth/current_step_cases.json']
    plan = {'version': 1, 'arms': ARMS, 'case_count': len(cases), 'repetitions': 1,
        'case_order': [c['id'] for c in cases], 'original_failed_case_ids': FAILED,
        'baseline_plan_sha256': digest(source / 'plan.json'),
        'baseline_results_sha256': digest(source.parent / 'live/summary.json'),
        'base_commit': 'cbc877bc799fbb21784b5e4aa30fe13da082c5cc',
        'same_original_failed_need_and_gold': True, 'same_corrected_description_bytes': True,
        'same_membership': True, 'same_full_final_descriptions': True,
        'directory_gates': previous['directory_gates'], 'final_gate': A.FINAL_GATE,
        'max_boundary_calls_per_task': 0, 'carry_limit': A.CARRY_LIMIT, 'adaptive_target': A.TARGET,
        'final_limit': A.FINAL_LIMIT, 'max_rounds': A.MAX_ROUNDS,
        'max_calls': 112, 'max_known_tokens': 350000, 'max_seconds': 360, 'timeout_seconds': 15,
        'executable': previous['executable'], 'provider': 'typesafe', 'attempts': 1,
        'ordering': 'Two original failures then six new cases; alternate fresh arms by case; one pass.',
        'scope': 'Isolated multi-step selection only; no installed capability, plugin, MCP, dispatcher or lifecycle changes.',
        'changes': ['Only final dispatch instructions prioritize the explicit current step. All required later candidates remain.',
                    'Directory policy, raw task, full criteria, order, gate and reading-cost estimator are unchanged.'],
        'acceptance': 'All eight candidate cases retain every current/later target and select the current target at >=0.7. All failures remain. No retries, within-run tuning or replay of previously passed needs.',
        'token_cap': 'Checked before each dispatch; one response may cross it. Stop on transport, unknown usage, malformed output or exhausted budget.',
        'limitations': 'Two known failures and six author-written combinations, one pass without independent blind review. Exact reference-target selection and retention only; no task execution or population-accuracy claim.',
        'source_sha256': {name: digest(ROOT / name) for name in sources},
        'input_sha256': {path.name: digest(path) for path in output.glob('*.json')}}
    write_once(output / 'plan.json', plan)
    print(json.dumps({'plan': identity(plan), 'cases': len(cases), 'arms': ARMS, 'final_gate': A.FINAL_GATE}))


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
        ('catalog.json', 'repaired-nodes.json', 'cases.json', 'question.json')]
    choices = {row['id']: row['description'] for row in rows} | {'none': question['none']}
    output.mkdir(mode=0o700, exist_ok=False)
    began = time.monotonic()
    provider = JevHierarchyProvider({'executable': plan['executable'], 'timeout_seconds': plan['timeout_seconds']},
        deadline=began + plan['max_seconds'])
    completed, calls, spent = [], 0, 0
    def finish(reason):
        write_once(output / 'summary.json', {'rows': completed, 'stop': reason, 'calls': calls,
                   'known_tokens': spent, 'seconds': time.monotonic() - began})
    for index, case in enumerate(cases):
        for arm in (ARMS if index % 2 == 0 else ARMS[::-1]):
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
