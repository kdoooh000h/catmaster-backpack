"""Frozen same-14 regression comparison; never writes an installed capability."""
import argparse
import json
from pathlib import Path
import time

import adaptive_experiment as A
import adaptive_repair as R
from adaptive_cost_experiment import ROOT, digest
from experiment import JevHierarchyProvider, grade, identity, read, write_once

ARMS = ['adaptive', 'repaired', 'repaired_boundary']


def freeze(source, output):
    source, output = Path(source), Path(output)
    old = read(source / 'plan.json')
    for name, sha in old['input_sha256'].items():
        if digest(source / name) != sha:
            raise ValueError('source_input_changed')
    for name, sha in old['source_sha256'].items():
        if digest(ROOT / name) != sha:
            raise ValueError('baseline_source_changed')
    nodes, rows = read(source / 'nodes.json'), read(source / 'catalog.json')
    repaired = R.build(nodes, rows)
    output.mkdir(mode=0o700, exist_ok=False)
    # Copy bytes, including original needs, gold and full final descriptions.
    for name in ('catalog.json', 'nodes.json', 'question.json', 'cases.json'):
        with (output / name).open('xb') as stream:
            stream.write((source / name).read_bytes())
    write_once(output / 'repaired-nodes.json', repaired)
    sources = list(old['source_sha256']) + ['benchmarks/directory-depth/' + name for name in
                                           ('adaptive_repair.py', 'repair_experiment.py')]
    plan = {'version': 1, 'arms': ARMS, 'repetitions': 1,
            'source_commit': old['source_commit'], 'baseline_plan_sha256': digest(source / 'plan.json'),
            'case_count': 14, 'same_case_bytes': True, 'same_membership': True,
            'same_full_final_descriptions': True, 'directory_gates': old['directory_gates'], 'final_gate': .7,
            'boundary_margin': R.BOUNDARY_MARGIN, 'max_boundary_calls_per_task': 1,
            'max_boundary_cards': R.REVIEW_CARD_LIMIT, 'max_boundary_chars': R.REVIEW_CHAR_LIMIT,
            'max_calls': 240, 'max_known_tokens': 450000, 'max_seconds': 420,
            'timeout_seconds': 15, 'executable': old['executable'], 'provider': 'typesafe', 'attempts': 1,
            'ordering': 'Rotate three arms by case; independent stateless requests; one pass.',
            'scope': 'Selector regression only; no capability execution, installation or native lifecycle mutation.',
            'acceptance': 'All 14 omissions/choices/controls must pass. Keep all semantic failures. Stop whole run on transport, missing usage, malformed output or budget. No retries or within-run tuning.',
            'limitations': 'Known development cases used to diagnose and repair metadata, not unseen validation. Review rescues only near-threshold branches within a one-call budget; cannot guarantee no omissions.',
            'source_sha256': {name: digest(ROOT / name) for name in sources},
            'input_sha256': {path.name: digest(path) for path in output.glob('*.json')}}
    write_once(output / 'plan.json', plan)
    print(json.dumps({'plan': identity(plan), 'cases': 14, 'arms': ARMS, 'final_gate': .7}))


def run(bundle, output):
    bundle, output = Path(bundle), Path(output)
    plan = read(bundle / 'plan.json')
    if plan['arms'] != ARMS or plan['final_gate'] != A.FINAL_GATE:
        raise ValueError('frozen_policy_changed')
    for name, sha in plan['input_sha256'].items():
        if digest(bundle / name) != sha:
            raise ValueError('frozen_input_changed')
    for name, sha in plan['source_sha256'].items():
        if digest(ROOT / name) != sha:
            raise ValueError('frozen_source_changed')
    rows, nodes, repaired, cases, question = [read(bundle / name) for name in
        ('catalog.json', 'nodes.json', 'repaired-nodes.json', 'cases.json', 'question.json')]
    choices = {row['id']: row['description'] for row in rows} | {'none': question['none']}
    output.mkdir(mode=0o700, exist_ok=False)
    began = time.monotonic()
    provider = JevHierarchyProvider({'executable': plan['executable'], 'timeout_seconds': plan['timeout_seconds']},
                                    deadline=began + plan['max_seconds'])
    results, calls, spent = [], 0, 0
    def finish(reason):
        write_once(output / 'summary.json', {'rows': results, 'stop': reason, 'calls': calls,
                    'known_tokens': spent, 'seconds': time.monotonic() - began})
    for index, case in enumerate(cases):
        arms = ARMS[index % len(ARMS):] + ARMS[:index % len(ARMS)]
        for arm in arms:
            started, offset = time.monotonic(), len(provider.calls)
            prefix = 'r0--' + case['id'] + '--' + arm
            def call(stage, spec, state):
                nonlocal calls, spent
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
            result = (A.route(nodes, 'adaptive', case['need'], choices, question['question'], call) if arm == 'adaptive'
                      else R.route(repaired, case['need'], choices, question['question'], call, review=arm == 'repaired_boundary'))
            receipts = provider.calls[offset:]
            row = {'case': case['id'], 'arm': arm, 'repetition': 0, 'control': case['control'],
                   'seconds': time.monotonic() - started, 'calls': len(receipts), 'result': result, 'transport': receipts,
                   'known_tokens': sum(r.get('input_tokens', 0) + r.get('output_tokens', 0) for r in receipts),
                   'usage_complete': all('input_tokens' in r and 'output_tokens' in r for r in receipts), **grade(case, result)}
            results.append(row)
            write_once(output / (prefix + '.json'), row)
            print(json.dumps({key: row[key] for key in ('case', 'arm', 'omission_safe_pass', 'seconds', 'calls', 'known_tokens')}
                | {'choice': result.get('choice'), 'status': result['status'], 'reason': result.get('reason'),
                   'review_calls': result.get('boundary_review_calls', 0)}), flush=True)
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
    if args.operation == 'freeze':
        freeze(args.source, args.output)
    else:
        run(args.source, args.output)
