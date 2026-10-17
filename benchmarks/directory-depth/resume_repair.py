"""Resume only a reconciled budget stop after explicit additional user budget.

Completed stages are replayed locally from identical frozen requests, NEVER
sent again. Unknown/error/pending outcomes block this continuation entirely.
The original plan, partial row and summary remain immutable.
"""
import argparse
import json
from pathlib import Path
import time

import adaptive_experiment as A
import adaptive_repair as R
from adaptive_cost_experiment import ROOT, digest
from experiment import JevHierarchyProvider, grade, identity, read, write_once
from repair_experiment import ARMS


def resume(bundle, live, authorization):
    bundle, live = Path(bundle), Path(live)
    plan, previous, approval = read(bundle / 'plan.json'), read(live / 'summary.json'), read(authorization)
    if approval.get('plan_sha256') != digest(bundle / 'plan.json') or not approval.get('user_message'):
        raise ValueError('missing_bound_human_budget')
    if any(type(approval.get(field)) is not int or approval[field] <= 0
           for field in ('additional_calls', 'additional_known_tokens')):
        raise ValueError('invalid_additional_budget')
    if previous['stop'] != 'budget_or_provider_failure':
        raise ValueError('not_budget_stopped')
    if list(live.glob('*.error.json')):
        raise ValueError('unreconciled_error_stop')
    for path in live.glob('*.pending.json'):
        done = path.with_name(path.name.replace('.pending.json', '.done.json'))
        if not done.exists() or any(r.get('outcome') != 'completed' for r in read(done)['transport']):
            raise ValueError('unreconciled_send_stop')
    for name, sha in plan['input_sha256'].items():
        if digest(bundle / name) != sha: raise ValueError('frozen_input_changed')
    for name, sha in plan['source_sha256'].items():
        if digest(ROOT / name) != sha: raise ValueError('frozen_source_changed')
    original = {(row['case'], row['arm']): row for row in previous['rows']}
    unfinished = [r for r in previous['rows'] if r['result'].get('reason')]
    if not unfinished or any(r['result'].get('reason') != 'experiment_budget_stop' for r in unfinished):
        raise ValueError('not_pure_budget_stop')
    write_once(live / 'budget-extension.json', approval | {'original_summary_sha256': digest(live / 'summary.json')})
    rows, nodes, repaired, cases, question = [read(bundle / name) for name in
        ('catalog.json', 'nodes.json', 'repaired-nodes.json', 'cases.json', 'question.json')]
    choices = {r['id']: r['description'] for r in rows} | {'none': question['none']}
    began = time.monotonic()
    provider = JevHierarchyProvider({'executable': plan['executable'], 'timeout_seconds': plan['timeout_seconds']},
        deadline=began + plan['max_seconds'] - previous['seconds'])
    results, added_calls, added_tokens, replayed_calls = [], 0, 0, 0
    def finish(reason):
        write_once(live / 'summary-resumed.json', {'rows': results, 'stop': reason,
            'calls': previous['calls'] + added_calls, 'known_tokens': previous['known_tokens'] + added_tokens,
            'seconds': previous['seconds'] + time.monotonic() - began,
            'extension': {'calls': added_calls, 'known_tokens': added_tokens, 'replayed_locally_only': replayed_calls}})
    for index, case in enumerate(cases):
        arms = ARMS[index % len(ARMS):] + ARMS[:index % len(ARMS)]
        for arm in arms:
            old = original.get((case['id'], arm))
            if old and old['result'].get('reason') != 'experiment_budget_stop':
                results.append(old)
                continue
            prefix = 'r0--' + case['id'] + '--' + arm
            receipts, started = [], time.monotonic()
            def call(stage, spec, state):
                nonlocal added_calls, added_tokens, replayed_calls
                path = live / (prefix + '--' + stage)
                pending, done = Path(str(path) + '.pending.json'), Path(str(path) + '.done.json')
                if pending.exists():
                    saved = read(pending)
                    if identity({'spec': saved['spec'], 'state': saved['state']}) != identity({'spec': spec, 'state': state}):
                        raise ValueError('replay_input_mismatch')
                    value = read(done)
                    receipts.extend(value['transport'])
                    replayed_calls += 1
                    return value['answer']
                if added_calls >= approval['additional_calls'] or added_tokens >= approval['additional_known_tokens']:
                    raise RuntimeError('experiment_budget_stop')
                added_calls += 1
                write_once(pending, {'spec': spec, 'state': state, 'ordinal': previous['calls'] + added_calls, 'at': time.time()})
                offset = len(provider.calls)
                try:
                    raw = provider.noul(spec, state)
                except Exception as error:
                    write_once(str(path) + '.error.json', {'error': str(error), 'transport': provider.calls[offset:]})
                    raise
                finally:
                    added_tokens += sum(r.get('input_tokens', 0) + r.get('output_tokens', 0) for r in provider.calls[offset:])
                new = provider.calls[offset:]
                receipts.extend(new)
                write_once(done, {'answer': raw, 'transport': new})
                if not new or not all('input_tokens' in r and 'output_tokens' in r for r in new):
                    raise RuntimeError('unknown_usage_stop')
                return raw
            result = (A.route(nodes, 'adaptive', case['need'], choices, question['question'], call) if arm == 'adaptive'
                else R.route(repaired, case['need'], choices, question['question'], call, review=arm == 'repaired_boundary'))
            row = {'case': case['id'], 'arm': arm, 'repetition': 0, 'control': case['control'],
                'seconds': (old['seconds'] if old else 0) + time.monotonic() - started,
                'calls': len(receipts), 'result': result, 'transport': receipts,
                'known_tokens': sum(r.get('input_tokens', 0) + r.get('output_tokens', 0) for r in receipts),
                'usage_complete': all('input_tokens' in r and 'output_tokens' in r for r in receipts), **grade(case, result)}
            results.append(row)
            write_once(live / (prefix + ('.continued.json' if old else '.json')), row)
            print(json.dumps({key: row[key] for key in ('case', 'arm', 'omission_safe_pass', 'seconds', 'calls', 'known_tokens')}), flush=True)
            if result.get('reason') not in {None, 'directory_limit', 'final_limit', 'no_progress'}:
                finish('budget_or_provider_failure')
                return
    finish('completed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--live', required=True)
    parser.add_argument('--authorization', required=True)
    args = parser.parse_args()
    resume(args.bundle, args.live, args.authorization)
