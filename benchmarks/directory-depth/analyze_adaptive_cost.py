"""Read-only paired cost summary; raw model payloads stay outside the repo."""
import argparse
from collections import defaultdict
import hashlib
from pathlib import Path
import statistics

from adaptive_cost_experiment import ARMS
from adaptive_experiment import gate
from experiment import identity, read, write_once


def metrics(rows):
    if not rows:
        return None
    return {'count': len(rows), 'omission_safe_successes': sum(r['omission_safe_pass'] for r in rows),
            'wrong_accepts': sum(r['wrong_accept'] for r in rows),
            'mean_seconds': statistics.mean(r['seconds'] for r in rows),
            'mean_tokens': statistics.mean(r['known_tokens'] for r in rows),
            'mean_calls': statistics.mean(r['calls'] for r in rows)}


def analyze(bundle, live, output):
    bundle, live = Path(bundle), Path(live)
    plan, summary, nodes = [read(path) for path in (bundle / 'plan.json', live / 'summary.json', bundle / 'nodes.json')]
    rows = summary['rows']
    pairs = {(r['case'], r['repetition']) for r in rows if all(any(
        s['case'] == r['case'] and s['repetition'] == r['repetition'] and s['arm'] == arm and
        s['result'].get('reason') not in {'experiment_budget_stop', 'unknown_no_replay', 'unknown_usage_stop'}
        for s in rows) for arm in ARMS)}
    common = [r for r in rows if (r['case'], r['repetition']) in pairs]
    groups, per_stage = defaultdict(list), defaultdict(lambda: defaultdict(int))
    unresolved, errors = [], []
    for path in live.glob('*.pending.json'):
        request = read(path)
        done = path.with_name(path.name.replace('.pending.json', '.done.json'))
        error = path.with_name(path.name.replace('.pending.json', '.error.json'))
        if not done.exists():
            (errors if error.exists() else unresolved).append(path.name)
            continue
        value = read(done)
        answer = value['answer']['answers']
        retained = ([answer['answer']['choice']] if answer['answer']['confidence'] >= .7 else []) if 'answer' in answer else sorted(
            key for key, score in answer.items() if score['noul'] >= gate(nodes[key]['depth']))
        request_id = identity({'spec': request['spec'], 'state': request['state']})
        groups[request_id].append({'answer': answer, 'retained': retained})
        parts = path.name.split('--')
        arm, stage = parts[2], ('final' if parts[3].startswith('final.') else 'directory')
        per_stage[arm][stage + '_calls'] += 1
        for receipt in value['transport']:
            for field in ('input_tokens', 'output_tokens'):
                per_stage[arm][stage + '_' + field] += receipt.get(field, 0)
    repeated = [values for values in groups.values() if len(values) > 1]
    protections = read(live.parent / 'protected-before.json')
    changed = [path for path, before in protections.items() if
               (hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None) != before]
    aggregate = {arm: metrics([r for r in common if r['arm'] == arm]) for arm in ARMS}
    sanitized = []
    for row in rows:
        item = {key: value for key, value in row.items() if key not in {'result', 'transport'}}
        item['result'] = {key: value for key, value in row['result'].items() if key != 'traces'}
        item['stages'] = [{'offered': t['offered_count'], 'retained': t['retained_count'],
                           'carried': t['carried_count'], 'pool_size': len(t['pool'])} for t in row['result']['traces']]
        sanitized.append(item)
    report = {'version': 1, 'scope': 'Public Skill selector only; not capability execution or daily deployment.',
              'plan': {key: value for key, value in plan.items() if key != 'executable'},
              'stop': summary['stop'], 'actual_calls': summary['calls'], 'known_tokens': summary['known_tokens'],
              'input_tokens': sum(t.get('input_tokens', 0) for r in rows for t in r['transport']),
              'output_tokens': sum(t.get('output_tokens', 0) for r in rows for t in r['transport']),
              'all_attempt_usage_reported': all(r['usage_complete'] for r in rows),
              'wall_seconds': summary['seconds'], 'complete_pairs': sorted(pairs),
              'by_arm': aggregate,
              'positive_by_arm': {arm: metrics([r for r in common if r['arm'] == arm and not r['control']]) for arm in ARMS},
              'control_by_arm': {arm: metrics([r for r in common if r['arm'] == arm and r['control']]) for arm in ARMS},
              'by_repetition': {str(rep): {arm: metrics([r for r in common if r['arm'] == arm and r['repetition'] == rep]) for arm in ARMS}
                                for rep in range(plan['repetitions'])},
              'by_case': {case: {arm: metrics([r for r in common if r['arm'] == arm and r['case'] == case]) for arm in ARMS} for case in plan['case_order']},
              'stage_usage': dict(per_stage), 'rows': sanitized,
              'repeat_variation': {'identical_input_groups': len(repeated),
                                   'groups_with_score_change': sum(len({identity(x['answer']) for x in g}) > 1 for g in repeated),
                                   'groups_with_retained_set_change': sum(len({tuple(x['retained']) for x in g}) > 1 for g in repeated)},
              'unreconciled_requests': unresolved, 'error_receipts': errors,
              'protected_paths_checked': len(protections), 'protected_files_unchanged': not changed,
              'protected_changed_count': len(changed),
              'source_summary_sha256': hashlib.sha256((live / 'summary.json').read_bytes()).hexdigest(),
              'limitations': ['Two repetitions of eight familiar cases, not unseen generalization.',
                  'Combined card compaction and global stopping experiment; no individual-factor ablation.',
                  'Score variation and network latency remain; no statistical significance claim.',
                  'Final descriptions, questions, coverage and gates unchanged; node prompt semantics clarified.',
                  'Token usage excludes root coordination; monetary cost and backend model revision unobservable.',
                  'No real plugin/MCP execution or daily lifecycle modification.']}
    report['reduction_percent'] = {metric: 100 * (1 - aggregate['compact_global'][metric] / aggregate['adaptive'][metric])
                                   for metric in ('mean_tokens', 'mean_seconds', 'mean_calls')} if all(aggregate.values()) else None
    write_once(output, report)
    print({'stop': summary['stop'], 'by_arm': aggregate, 'positive': report['positive_by_arm'],
           'reduction_percent': report['reduction_percent'], 'protection_changed': len(changed),
           'unreconciled': len(unresolved), 'errors': len(errors), 'variation': report['repeat_variation']})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--live', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    analyze(args.bundle, args.live, args.output)
