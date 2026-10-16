"""First-layer culture scope comparison with current-step selection unchanged."""
import argparse
import json
from pathlib import Path
import time

import adaptive_experiment as A
from adaptive_cost_experiment import ROOT, digest
from current_step import select
from culture_scope import build, ROOT_ID, SOURCE_ID, ORIGINAL, ADDITION
from experiment import JevHierarchyProvider, grade, identity, read, write_once

ARMS = ['current_step', 'culture_scope']
FAILED = 'multi_reverse_wiki_now'
FIXTURES = Path(__file__).with_name('culture_scope_cases.json')


def validate_cases(prior, previous_rows, additions, catalog, historical):
    by_id = {c['id']: c for c in prior}
    failed = {r['case'] for r in previous_rows if r['arm'] == 'current_step' and not r['omission_safe_pass']}
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
        if set(required) & set(case.get('forbidden_current_ids', [])):
            raise ValueError('conflicting_gold')
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
    catalog, nodes = read(source / 'catalog.json'), read(source / 'repaired-nodes.json')
    historical = read(Path(__file__).with_name('breadth_cases.json'))['cases']
    historical += read(Path(__file__).with_name('large_public_cases.json'))['cases']
    cases = validate_cases(read(source / 'cases.json'), summary['rows'], read(FIXTURES)['cases'], catalog, historical)
    candidate = build(nodes)
    if A.union(nodes, ['n']) != {r['id'] for r in catalog}: raise ValueError('coverage_changed')
    if [key for key in nodes if nodes[key] != candidate[key]] != [ROOT_ID]: raise ValueError('repair_scope_changed')
    by_id = {r['id']: r for r in catalog}
    for case in cases[1:]:
        case['gold_sources'] = [{'id': key, 'source': by_id[key]['source'], 'description': by_id[key]['description']}
            for key in case['expected_ids'] + case['pending_ids']]
    output.mkdir(mode=0o700, exist_ok=False)
    for name in ('catalog.json', 'nodes.json', 'repaired-nodes.json', 'question.json'):
        with (output / name).open('xb') as stream: stream.write((source / name).read_bytes())
    write_once(output / 'candidate-nodes.json', candidate)
    write_once(output / 'cases.json', cases)
    sources = list(previous['source_sha256']) + ['benchmarks/directory-depth/' + name for name in
        ('culture_scope.py', 'culture_scope_experiment.py', 'culture_scope_cases.json')]
    plan = {'version': 1, 'arms': ARMS, 'case_count': len(cases), 'repetitions': 1,
        'case_order': [c['id'] for c in cases], 'original_failed_case_ids': [FAILED],
        'baseline_plan_sha256': digest(source / 'plan.json'),
        'baseline_results_sha256': digest(source.parent / 'live/summary.json'),
        'base_commit': '6de306a6f88c9a7c81c346cf81798bd9e8185909',
        'same_original_failed_need_and_gold': True, 'same_membership': True,
        'same_final_question_and_full_descriptions': True,
        'directory_gates': previous['directory_gates'], 'final_gate': A.FINAL_GATE,
        'max_boundary_calls_per_task': 0, 'carry_limit': A.CARRY_LIMIT, 'adaptive_target': A.TARGET,
        'final_limit': A.FINAL_LIMIT, 'max_rounds': A.MAX_ROUNDS,
        'max_calls': 98, 'max_known_tokens': 300000, 'max_seconds': 300, 'timeout_seconds': 15,
        'executable': previous['executable'], 'provider': 'typesafe', 'attempts': 1,
        'ordering': 'Original failure then six new cases; alternate fresh arms by case; one pass.',
        'scope': 'Isolated public directory selection only; no installation, daily activation, private catalog or lifecycle changes.',
        'changes': ['Append source-grounded culture operations to one first-layer directory description. No member or rule changes.'],
        'scope_evidence': {'node': ROOT_ID, 'before': ORIGINAL, 'after': ORIGINAL + ADDITION,
            'capability': SOURCE_ID, 'source': by_id[SOURCE_ID]['source'], 'source_description': by_id[SOURCE_ID]['description']},
        'acceptance': 'All seven candidate cases select the current reference at >=0.7 and retain every current/later reference at every layer. Cancelled culture must not become the current selection. Preserve every failure; no retries, within-run tuning or replay of previously passed needs.',
        'token_cap': 'Check before each dispatch; one response may cross it. Stop on transport, unknown usage, malformed output or exhausted budget.',
        'limitations': 'One known failure and six author-written combinations, one pass without independent blind review. Selection and retention only, not business-task execution or population accuracy.',
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
    nodes = {'current_step': nodes, 'culture_scope': candidate}
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
            result = select('current_step', nodes[arm], case['need'], choices, question['question'], call)
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
