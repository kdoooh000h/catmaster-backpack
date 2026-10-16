"""Isolate dependency description repair from earlier adaptive stopping."""
import argparse
import json
from pathlib import Path
import time

import adaptive_experiment as A
from adaptive_cost_experiment import ROOT, digest
from dependency_selection import select
from dependency_scope import build, NODE, PARENT, ORIGINAL, REPLACEMENT
from experiment import JevHierarchyProvider, grade, identity, read, write_once

ARMS = ['baseline', 'described', 'early_stop']
FAILED = 'culture_now_then_dependencies'
FIXTURES = Path(__file__).with_name('dependency_cases.json')


def validate_cases(prior, previous_rows, additions, catalog, historical):
    by_id = {c['id']: c for c in prior}
    failed = {r['case'] for r in previous_rows if r['arm'] == 'culture_scope' and not r['omission_safe_pass']}
    if failed != {FAILED}: raise ValueError('failed_scope_changed')
    if len(additions) != 6 or len({c['id'] for c in additions}) != 6 or len({c['need'] for c in additions}) != 6:
        raise ValueError('new_case_set_changed')
    old_ids, old_needs = {c['id'] for c in prior + historical}, {c['need'] for c in prior + historical}
    catalog_ids = {r['id'] for r in catalog}
    for case in additions:
        if case['id'] in old_ids or case['need'] in old_needs: raise ValueError('previous_case_reuse')
        required = case['expected_ids'] + case['pending_ids']
        if len(case['expected_ids']) != 1 or not case['pending_ids'] or case['control']:
            raise ValueError('invalid_multi_step_gold')
        if len(required) != len(set(required)) or not set(required) <= catalog_ids:
            raise ValueError('invalid_required_targets')
        if any(key.lower() in case['need'].lower() for key in catalog_ids if '-' in key):
            raise ValueError('named_skill_in_need')
        if set(required) & set(case.get('forbidden_current_ids', [])): raise ValueError('conflicting_gold')
    return [by_id[FAILED]] + additions


def freeze(source, output):
    source, output = Path(source), Path(output)
    previous = read(source / 'plan.json')
    for name, sha in previous['input_sha256'].items():
        if digest(source / name) != sha: raise ValueError('source_input_changed')
    for name, sha in previous['source_sha256'].items():
        if digest(ROOT / name) != sha: raise ValueError('source_code_changed')
    summary = read(source.parent / 'live/summary.json')
    if summary['stop'] != 'completed': raise ValueError('previous_run_incomplete')
    catalog, nodes = read(source / 'catalog.json'), read(source / 'candidate-nodes.json')
    historical = []
    for name in ('breadth_cases.json', 'large_public_cases.json', 'current_step_cases.json'):
        historical += read(Path(__file__).with_name(name))['cases']
    cases = validate_cases(read(source / 'cases.json'), summary['rows'], read(FIXTURES)['cases'], catalog, historical)
    candidate = build(nodes)
    if A.union(nodes, ['n']) != {r['id'] for r in catalog}: raise ValueError('coverage_changed')
    if {key for key in nodes if nodes[key] != candidate[key]} != {NODE, PARENT}: raise ValueError('repair_scope_changed')
    by_id = {r['id']: r for r in catalog}
    for case in cases[1:]:
        case['gold_sources'] = [{'id': key, 'source': by_id[key]['source'], 'description': by_id[key]['description']}
            for key in case['expected_ids'] + case['pending_ids']]
    output.mkdir(mode=0o700, exist_ok=False)
    for name in ('catalog.json', 'nodes.json', 'question.json'):
        with (output / name).open('xb') as stream: stream.write((source / name).read_bytes())
    with (output / 'repaired-nodes.json').open('xb') as stream: stream.write((source / 'candidate-nodes.json').read_bytes())
    write_once(output / 'candidate-nodes.json', candidate)
    write_once(output / 'cases.json', cases)
    sources = list(previous['source_sha256']) + ['benchmarks/directory-depth/' + name for name in
        ('dependency_scope.py', 'dependency_selection.py', 'dependency_experiment.py', 'dependency_cases.json', 'adaptive_early_stop.py')]
    plan = {'version': 1, 'arms': ARMS, 'case_count': len(cases), 'repetitions': 1,
        'case_order': [c['id'] for c in cases], 'original_failed_case_ids': [FAILED],
        'baseline_plan_sha256': digest(source / 'plan.json'),
        'baseline_results_sha256': digest(source.parent / 'live/summary.json'),
        'base_commit': 'eebb3c04b4722728798021930d87beb88009eadc',
        'same_original_failed_need_and_gold': True, 'same_membership': True,
        'same_final_question_and_full_descriptions': True, 'first_layer_culture_repair_preserved': True,
        'directory_gates': previous['directory_gates'], 'final_gate': A.FINAL_GATE,
        'max_boundary_calls_per_task': 0, 'carry_limit': A.CARRY_LIMIT, 'adaptive_target': A.TARGET,
        'final_limit': A.FINAL_LIMIT, 'max_rounds': A.MAX_ROUNDS,
        'reading_cost_ratio': {'baseline': .65, 'described': .65, 'early_stop': .35},
        'reading_cost_pool_limit': 48,
        'max_calls': 147, 'max_known_tokens': 420000, 'max_seconds': 360, 'timeout_seconds': 15,
        'executable': previous['executable'], 'provider': 'typesafe', 'attempts': 1,
        'ordering': 'Original failure then six new cases; rotate three fresh arms by case; one pass.',
        'scope': 'Isolated public directory selection; no daily installation, private catalog or lifecycle changes.',
        'changes': {'baseline': 'Current-step selection plus previous culture repair, unchanged.',
            'described': 'Clarify package vulnerabilities, licenses, transitive risk and upgrade planning in the third-layer scope and its embedded parent copy.',
            'early_stop': 'Same clarified scopes; lower only the reading-cost stopping ratio from .65 to .35 when the retained pool is at most 48. Keep the whole retained pool for final selection.'},
        'scope_evidence': {'node': NODE, 'parent': PARENT, 'before': ORIGINAL, 'after': REPLACEMENT,
            'source': by_id['dependency-auditor']['source'], 'source_description': by_id['dependency-auditor']['description']},
        'acceptance': 'Candidate must select every current reference at >=0.7 and retain every current/later reference throughout all seven cases. Cost preference applies only among all-pass arms. All semantic failures remain; no retries, tuning or passed-need replay.',
        'token_cap': 'Check before dispatch; one response may cross it. Stop on transport, missing usage, malformed output or exhausted budget.',
        'limitations': 'One known failure and six author-written combinations, one pass without independent blind review. The earlier stopping heuristic is calibrated from prior traces, not proven optimal. Selection only, no business execution or population accuracy claim.',
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
    candidate = read(bundle / 'candidate-nodes.json')
    if candidate != build(nodes): raise ValueError('candidate_metadata_changed')
    nodes = {'baseline': nodes, 'described': candidate, 'early_stop': candidate}
    output.mkdir(mode=0o700, exist_ok=False)
    began = time.monotonic()
    provider = JevHierarchyProvider({'executable': plan['executable'], 'timeout_seconds': plan['timeout_seconds']},
        deadline=began + plan['max_seconds'])
    completed, calls, spent = [], 0, 0
    def finish(reason):
        write_once(output / 'summary.json', {'rows': completed, 'stop': reason, 'calls': calls,
                   'known_tokens': spent, 'seconds': time.monotonic() - began})
    for index, case in enumerate(cases):
        for arm in (ARMS[index % 3:] + ARMS[:index % 3]):
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
            result = select(arm, nodes[arm], case['need'], choices, question['question'], call)
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
