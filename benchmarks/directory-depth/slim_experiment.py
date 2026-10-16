"""Same repaired metadata, explicit-request prompts and fewer repeated levels.

Reuse the tested adaptive selector rather than adding another route engine.
Neither arm can invoke boundary review; its historical experiment stays intact.
"""
import argparse
import json
from pathlib import Path
import time

import adaptive_experiment as A
import adaptive_repair as R
from adaptive_cost_experiment import ROOT, digest
from experiment import JevHierarchyProvider, grade, identity, read, write_once

ARMS = ['repaired', 'slim']


def select(arm, nodes, task, choices, question, call):
    if arm == 'repaired':
        return R.route(nodes, task, choices, question, call, review=False)
    if arm == 'slim':
        # Original explicit-request rules, carry entire <=8-member branches,
        # stop at a small aggregate pool or before costlier duplicate disclosure.
        return A.route(nodes, 'adaptive', task, choices, question, call)
    raise ValueError('unknown_arm')


def freeze(source, output):
    source, output = Path(source), Path(output)
    previous = read(source / 'plan.json')
    for name, sha in previous['input_sha256'].items():
        if digest(source / name) != sha: raise ValueError('source_input_changed')
    for name, sha in previous['source_sha256'].items():
        if digest(ROOT / name) != sha: raise ValueError('source_code_changed')
    cases = read(source / 'cases.json')
    nodes = read(source / 'repaired-nodes.json')
    catalog = read(source / 'catalog.json')
    if len(cases) != 14 or len({c['id'] for c in cases}) != 14:
        raise ValueError('case_set_changed')
    if A.union(nodes, ['n']) != {r['id'] for r in catalog}:
        raise ValueError('coverage_changed')
    output.mkdir(mode=0o700, exist_ok=False)
    for name in ('catalog.json', 'nodes.json', 'repaired-nodes.json', 'question.json', 'cases.json'):
        with (output / name).open('xb') as stream:
            stream.write((source / name).read_bytes())
    sources = list(previous['source_sha256']) + ['benchmarks/directory-depth/slim_experiment.py']
    plan = {'version': 1, 'arms': ARMS, 'case_count': 14, 'repetitions': 1,
        'source_commit': previous['source_commit'], 'baseline_plan_sha256': digest(source / 'plan.json'),
        'same_case_bytes': True, 'same_corrected_description_bytes': True,
        'same_membership': True, 'same_full_final_descriptions': True,
        'directory_gates': previous['directory_gates'], 'final_gate': A.FINAL_GATE,
        'max_boundary_calls_per_task': 0, 'carry_limit': A.CARRY_LIMIT,
        'adaptive_target': A.TARGET, 'final_limit': A.FINAL_LIMIT, 'max_rounds': A.MAX_ROUNDS,
        'max_calls': 196, 'max_known_tokens': 450000, 'max_seconds': 360,
        'timeout_seconds': 15, 'executable': previous['executable'], 'provider': 'typesafe', 'attempts': 1,
        'ordering': 'Alternate two fresh arms by case; one pass; no reuse of historical model responses.',
        'scope': 'Isolated same-14 selector comparison; no installed capability, plugin, MCP or lifecycle changes.',
        'changes': ['Restore explicit-request category question and rules from the tested adaptive selector.',
                    'Carry whole small branches while refining other branches, avoiding duplicate child descriptions.',
                    'Use existing small-pool and reading-cost stopping rules with corrected metadata.',
                    'No boundary review path in the slim selector.'],
        'acceptance': 'All 14 cases retain every required current/later capability and select correctly, controls included. Report all failures; stop on transport, missing usage, malformed output or exhausted budget. No retries or within-run tuning.',
        'token_cap': 'Checked before each call; one response may cross it. Missing usage stops the whole run.',
        'limitations': 'Known regression cases, one pass and a combined prompt/carry policy change; not unseen validation or an individual-factor ablation.',
        'source_sha256': {name: digest(ROOT / name) for name in sources},
        'input_sha256': {path.name: digest(path) for path in output.glob('*.json')}}
    write_once(output / 'plan.json', plan)
    print(json.dumps({'plan': identity(plan), 'cases': 14, 'arms': ARMS, 'final_gate': A.FINAL_GATE}))


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
    if args.operation == 'freeze': freeze(args.source, args.output)
    else: run(args.source, args.output)
