"""Breadth evaluation without tuning, replaying failures or touching daily data."""
import argparse
from pathlib import Path
import json
import time

import adaptive_experiment as A
import adaptive_cost as C
from adaptive_cost_experiment import ROOT, SOURCES, digest
from experiment import JevHierarchyProvider, grade, identity, read, write_once

ARMS = ['adaptive', 'compact_global']


def freeze(source, output, executable):
    source, output = Path(source), Path(output)
    old = read(source / 'plan.json')
    for name, sha in old['input_sha256'].items():
        if digest(source / name) != sha:
            raise ValueError('source_input_changed')
    for name, sha in old['source_sha256'].items():
        if digest(ROOT / name) != sha:
            raise ValueError('previous_candidate_changed')
    cases = read(Path(__file__).with_name('expanded_cases.json'))['cases']
    rows = read(source / 'catalog.json')
    by_id = {row['id']: row for row in rows}
    previous = {case['need'] for case in read(source / 'cases.json')}
    if len({c['id'] for c in cases}) != len(cases) or any(c['need'] in previous for c in cases):
        raise ValueError('duplicate_case_or_old_request')
    for case in cases:
        required = case['expected_ids'] + case['pending_ids']
        if any(key not in by_id or key in case['need'] for key in required):
            raise ValueError('invalid_gold_or_named_capability')
        case['gold_sources'] = [by_id[key]['source'] for key in required]
    output.mkdir(mode=0o700, exist_ok=False)
    for name in ('catalog.json', 'nodes.json', 'question.json'):
        write_once(output / name, read(source / name))
    write_once(output / 'cases.json', cases)
    sources = SOURCES + ['benchmarks/directory-depth/expanded_experiment.py', 'benchmarks/directory-depth/expanded_cases.json']
    plan = {'version': 1, 'arms': ARMS, 'case_order': [c['id'] for c in cases], 'repetitions': 1,
            'source_commit': old['source_commit'], 'source_catalog_count': len(rows),
            'tree_sha256': old['tree_sha256'], 'baseline_plan_sha256': digest(source / 'plan.json'),
            'same_query': True, 'same_full_final_descriptions': True,
            'directory_gates': old['directory_gates'], 'final_gate': .7,
            'max_calls': 180, 'max_known_tokens': 350000, 'max_seconds': 360,
            'timeout_seconds': 15, 'executable': executable, 'provider': 'typesafe', 'attempts': 1,
            'ordering': 'controls first; alternate arm order by case; fresh stateless requests',
            'acceptance': 'Record all semantic failures without tuning; only passing selected tasks may proceed to artifact use. Stop whole run on transport, missing usage, malformed output or budget.',
            'execution_sample_cases': ['zh_data_profile', 'mix_api_contract', 'syn_release_notes', 'zh_query_join'],
            'execution_scope': 'Use selected pinned public Skill guidance in isolated local fixtures; no native installation, market connection, MCP service or business account execution.',
            'source_sha256': {name: digest(ROOT / name) for name in sources},
            'input_sha256': {path.name: digest(path) for path in output.glob('*.json')}}
    write_once(output / 'plan.json', plan)
    print(json.dumps({'plan': identity(plan), 'cases': len(cases), 'new_requests': True}))


def run(bundle, output):
    bundle, output = Path(bundle), Path(output)
    plan = read(bundle / 'plan.json')
    for name, sha in plan['input_sha256'].items():
        if digest(bundle / name) != sha:
            raise ValueError('frozen_input_changed')
    for name, sha in plan['source_sha256'].items():
        if digest(ROOT / name) != sha:
            raise ValueError('frozen_source_changed')
    rows, nodes, cases, question = [read(bundle / name) for name in ('catalog.json', 'nodes.json', 'cases.json', 'question.json')]
    choices = {r['id']: r['description'] for r in rows} | {'none': question['none']}
    output.mkdir(mode=0o700, exist_ok=False)
    began = time.monotonic()
    provider = JevHierarchyProvider({'executable': plan['executable'], 'timeout_seconds': plan['timeout_seconds']}, deadline=began + plan['max_seconds'])
    results, calls, spent = [], 0, 0
    def finish(reason):
        write_once(output / 'summary.json', {'rows': results, 'stop': reason, 'calls': calls,
                                           'known_tokens': spent, 'seconds': time.monotonic() - began})
    for index, case in enumerate(cases):
        for arm in (ARMS if index % 2 == 0 else ARMS[::-1]):
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
                write_once(str(path) + '.done.json', {'answer': raw, 'transport': provider.calls[first:]})
                if not all('input_tokens' in r and 'output_tokens' in r for r in provider.calls[first:]):
                    raise RuntimeError('unknown_usage_stop')
                return raw
            result = (A.route(nodes, 'adaptive', case['need'], choices, question['question'], call) if arm == 'adaptive'
                      else C.route(nodes, case['need'], choices, question['question'], call))
            receipts = provider.calls[offset:]
            row = {'case': case['id'], 'arm': arm, 'repetition': 0, 'control': case['control'],
                   'seconds': time.monotonic() - started, 'calls': len(receipts), 'result': result, 'transport': receipts,
                   'known_tokens': sum(r.get('input_tokens', 0) + r.get('output_tokens', 0) for r in receipts),
                   'usage_complete': all('input_tokens' in r and 'output_tokens' in r for r in receipts), **grade(case, result)}
            results.append(row)
            write_once(output / (prefix + '.json'), row)
            print(json.dumps({key: row[key] for key in ('case', 'arm', 'omission_safe_pass', 'seconds', 'calls', 'known_tokens')}
                             | {'choice': result.get('choice'), 'status': result['status'], 'reason': result.get('reason')}), flush=True)
            if result.get('reason') not in {None, 'directory_limit', 'final_limit', 'no_progress'} or any(r.get('outcome') != 'completed' for r in receipts):
                finish('budget_or_provider_failure')
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
            parser.error('--executable required for freeze')
        freeze(args.source, args.output, args.executable)
    else:
        run(args.source, args.output)
