"""Frozen paired cost experiment. Unknown outcomes and failed gates stop it."""
import argparse
import hashlib
from pathlib import Path
import json
import time

import adaptive_experiment as A
import adaptive_cost as C
from experiment import JevHierarchyProvider, grade, identity, read, write_once

ARMS = ['adaptive', 'compact_global']
CASE_ORDER = ['zh_quote_control', 'mix_cancel_control', 'zh_llm_cost',
              'syn_custom_controller', 'syn_upgrade_moment', 'mix_multi_jira_then_qms',
              'zh_vendor_scorecard', 'mix_financial_model']
ROOT = Path(__file__).resolve().parents[2]
SOURCES = ['benchmarks/directory-depth/' + name for name in
           ('adaptive_cost.py', 'adaptive_cost_experiment.py', 'adaptive_experiment.py',
            'adaptive_catalog.py', 'experiment.py')] + ['core/jev_hierarchy_provider.py']


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze(source, output, executable):
    source, output = Path(source), Path(output)
    old = read(source / 'plan.json')
    for name, value in old['input_sha256'].items():
        if digest(source / name) != value:
            raise ValueError('source_input_changed')
    for name, value in old['source_sha256'].items():
        if digest(Path(__file__).with_name(name)) != value:
            raise ValueError('baseline_source_changed')
    output.mkdir(mode=0o700, exist_ok=False)
    for name in ('catalog.json', 'nodes.json', 'question.json'):
        write_once(output / name, read(source / name))
    by_id = {case['id']: case for case in read(source / 'cases.json')}
    write_once(output / 'cases.json', [by_id[key] for key in CASE_ORDER])
    plan = {'version': 1, 'arms': ARMS, 'case_order': CASE_ORDER, 'repetitions': 2,
            'source_catalog_count': len(read(source / 'catalog.json')),
            'source_commit': old['source_commit'], 'tree_sha256': old['tree_sha256'],
            'baseline_plan_sha256': digest(source / 'plan.json'),
            'same_query': True, 'same_full_final_descriptions': True,
            'directory_gates': old['directory_gates'], 'final_gate': .7,
            'max_calls': 160, 'max_known_tokens': 260000, 'max_seconds': 300,
            'timeout_seconds': 15, 'executable': executable, 'provider': 'typesafe',
            'attempts': 1, 'ordering': 'two fresh repetitions; alternate arms by case and repetition',
            'acceptance': 'Stop after any candidate omission, wrong selection, negative-control failure, abstention or unavailable result. Never replay. Controls first. Compare all complete pairs, including failures.',
            'token_cap': 'Checked before each call; one response can cross it. Missing usage stops the experiment.',
            'source_sha256': {name: digest(ROOT / name) for name in SOURCES},
            'input_sha256': {path.name: digest(path) for path in output.glob('*.json')}}
    write_once(output / 'plan.json', plan)
    print(json.dumps({'plan': identity(plan), 'cases': len(by_id), 'repetitions': 2}))


def run(bundle, output):
    bundle, output = Path(bundle), Path(output)
    plan = read(bundle / 'plan.json')
    for name, value in plan['input_sha256'].items():
        if digest(bundle / name) != value:
            raise ValueError('frozen_input_changed')
    for name, value in plan['source_sha256'].items():
        if digest(ROOT / name) != value:
            raise ValueError('frozen_source_changed')
    rows, nodes, cases, question = [read(bundle / name) for name in
                                    ('catalog.json', 'nodes.json', 'cases.json', 'question.json')]
    choices = {row['id']: row['description'] for row in rows} | {'none': question['none']}
    output.mkdir(mode=0o700, exist_ok=False)
    began = time.monotonic()
    provider = JevHierarchyProvider({'executable': plan['executable'], 'timeout_seconds': plan['timeout_seconds']},
                                    deadline=began + plan['max_seconds'])
    results, calls, spent = [], 0, 0
    def finish(reason):
        write_once(output / 'summary.json', {'rows': results, 'stop': reason, 'calls': calls,
                    'known_tokens': spent, 'seconds': time.monotonic() - began})
    for repetition in range(plan['repetitions']):
        for index, case in enumerate(cases):
            arms = ARMS if (index + repetition) % 2 == 0 else ARMS[::-1]
            for arm in arms:
                started, call_start = time.monotonic(), len(provider.calls)
                prefix = f'r{repetition}--{case["id"]}--{arm}'
                def call(stage, spec, state):
                    nonlocal calls, spent
                    if calls >= plan['max_calls'] or spent >= plan['max_known_tokens'] or time.monotonic() - began >= plan['max_seconds']:
                        raise RuntimeError('experiment_budget_stop')
                    calls += 1
                    path = output / (prefix + '--' + stage)
                    write_once(str(path) + '.pending.json', {'spec': spec, 'state': state,
                               'ordinal': calls, 'at': time.time()})
                    offset = len(provider.calls)
                    try:
                        raw = provider.noul(spec, state)
                    except Exception as error:
                        write_once(str(path) + '.error.json', {'error': str(error), 'transport': provider.calls[offset:]})
                        raise
                    finally:
                        spent += sum(r.get('input_tokens', 0) + r.get('output_tokens', 0) for r in provider.calls[offset:])
                    write_once(str(path) + '.done.json', {'answer': raw, 'transport': provider.calls[offset:]})
                    if not all('input_tokens' in r and 'output_tokens' in r for r in provider.calls[offset:]):
                        raise RuntimeError('unknown_usage_stop')
                    return raw
                if arm == 'adaptive':
                    result = A.route(nodes, 'adaptive', case['need'], choices, question['question'], call)
                else:
                    result = C.route(nodes, case['need'], choices, question['question'], call)
                receipts = provider.calls[call_start:]
                row = {'case': case['id'], 'arm': arm, 'repetition': repetition, 'control': case['control'],
                       'seconds': time.monotonic() - started, 'calls': len(receipts), 'result': result,
                       'transport': receipts, 'known_tokens': sum(r.get('input_tokens', 0) + r.get('output_tokens', 0) for r in receipts),
                       'usage_complete': all('input_tokens' in r and 'output_tokens' in r for r in receipts), **grade(case, result)}
                results.append(row)
                write_once(output / (prefix + '.json'), row)
                print(json.dumps({key: row[key] for key in ('case', 'arm', 'repetition', 'omission_safe_pass', 'seconds', 'calls', 'known_tokens')}
                                 | {'status': result['status'], 'reason': result.get('reason'), 'pool': result.get('final_pool_size')}), flush=True)
                if result.get('reason') not in {None, 'directory_limit', 'final_limit', 'no_progress'} or any(r.get('outcome') != 'completed' for r in receipts):
                    finish('budget_or_provider_failure')
                    return
                if arm == 'compact_global' and not row['omission_safe_pass']:
                    finish('candidate_acceptance_failed')
                    return
    finish('completed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['freeze', 'run'])
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--executable')
    args = parser.parse_args()
    if args.operation == 'freeze':
        if not args.executable:
            parser.error('--executable is required for freeze')
        freeze(args.source, args.output, args.executable)
    else:
        run(args.source, args.output)
