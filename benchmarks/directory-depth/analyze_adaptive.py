"""Read-only evaluation and sanitized export of the adaptive pilot receipts."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics

from adaptive_experiment import ARMS, gate
from experiment import read, write_once


def analyze(bundle, live, output):
    bundle, live = Path(bundle), Path(live)
    plan, summary, nodes = read(bundle / 'plan.json'), read(live / 'summary.json'), read(bundle / 'nodes.json')
    rows = summary['rows']
    common = [case for case in plan['case_order'] if all(any(row['case'] == case and row['arm'] == arm
              and row['result'].get('reason') not in {'experiment_budget_stop', 'unknown_no_replay'}
              for row in rows) for arm in ARMS)]
    by_arm = {}
    for arm in ARMS:
        selected = [row for row in rows if row['case'] in common and row['arm'] == arm]
        by_arm[arm] = {
            'count': len(selected), 'omission_safe_successes': sum(row['omission_safe_pass'] for row in selected),
            'retained_required': sum(row['all_required_retained'] is True for row in selected),
            'mean_seconds': statistics.mean(row['seconds'] for row in selected),
            'mean_tokens': statistics.mean(row['known_tokens'] for row in selected),
            'mean_calls': statistics.mean(row['calls'] for row in selected)}
    groups = defaultdict(list)
    for path in live.glob('*.pending.json'):
        pending = read(path)
        done = path.with_name(path.name.replace('.pending.json', '.done.json'))
        if not done.exists():
            raise ValueError('unreconciled_pending_request')
        request_hash = hashlib.sha256(json.dumps({'spec': pending['spec'], 'state': pending['state']}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        answer = read(done)['answer']['answers']
        if 'answer' in answer and answer['answer']['type'] == 'choice':
            retained = [answer['answer']['choice']] if answer['answer']['confidence'] >= .7 else []
        else:
            retained = sorted(key for key, value in answer.items() if value['noul'] >= gate(nodes[key]['depth']))
        groups[request_hash].append({'answer': answer, 'retained': retained, 'case': path.name.split('--')[0]})
    repeated = [items for items in groups.values() if len(items) > 1]
    variation = {
        'identical_input_groups': len(repeated),
        'groups_with_any_score_change': sum(len({json.dumps(x['answer'], sort_keys=True) for x in group}) > 1 for group in repeated),
        'groups_with_retained_set_change': sum(len({tuple(x['retained']) for x in group}) > 1 for group in repeated)}
    changed_cases = sorted({x['case'] for group in repeated
                            if len({tuple(x['retained']) for x in group}) > 1 for x in group})
    variation['cases_with_retained_set_change'] = changed_cases
    sensitivity = {}
    for arm in ('deep', 'adaptive'):
        selected = [row for row in rows if row['case'] in common and row['case'] not in changed_cases and row['arm'] == arm]
        sensitivity[arm] = {'count': len(selected),
            'mean_tokens': statistics.mean(row['known_tokens'] for row in selected),
            'mean_seconds': statistics.mean(row['seconds'] for row in selected),
            'mean_calls': statistics.mean(row['calls'] for row in selected)} if selected else None
    sanitized = []
    for row in rows:
        entry = {key: value for key, value in row.items() if key not in {'result', 'transport'}}
        entry['result'] = {key: value for key, value in row['result'].items() if key != 'traces'}
        entry['stages'] = [{'offered': trace['offered_count'], 'retained': trace['retained_count'],
                            'carried': trace['carried_count'], 'pool_size': len(trace['pool'])}
                           for trace in row['result']['traces']]
        sanitized.append(entry)
    protections = read(live.parent / 'protected-before.json')
    changed = [path for path, before in protections.items() if
               (hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None) != before]
    if changed:
        raise ValueError('protected_files_changed')
    result = {'version': 1, 'scope': 'Public Skill guidance selection, not acquisition or business execution.',
        'plan': {key: value for key, value in plan.items() if key != 'executable'},
        'stop': summary['stop'], 'actual_calls': summary['calls'], 'known_tokens': summary['known_tokens'],
        'input_tokens': sum(t.get('input_tokens', 0) for row in rows for t in row['transport']),
        'output_tokens': sum(t.get('output_tokens', 0) for row in rows for t in row['transport']),
        'all_attempt_usage_reported': all(row['usage_complete'] for row in rows),
        'wall_seconds': summary['seconds'], 'common_cases': common, 'by_arm_common_cases': by_arm,
        'rows': sanitized, 'identical_input_variation': variation,
        'posthoc_sensitivity_excluding_retained_set_variation': sensitivity,
        'sensitivity_limit': 'Posthoc diagnostic, not a replacement benchmark or independent validation. Do not attribute the full token difference to adaptive stopping.',
        'source_summary_sha256': hashlib.sha256((live / 'summary.json').read_bytes()).hexdigest(),
        'protected_files_unchanged': len(protections), 'daily_release_checked': '0.3.71+creation.20261015',
        'unrun': ['zh_quote_control', 'mix_cancel_control'],
        'incomplete': ['mix_multi_jira_then_qms/deep'],
        'limitations': ['Single pass on familiar positive cases; no unseen accuracy claim.',
            'Same input can yield different directory scores and retained sets; measured time differences also include transport variation.',
            'Negative controls not run; recorded budget stop was not retried.',
            'Character-based reading-cost heuristic exercised offline, not reached in live completed adaptive runs.',
            'Routing only; root orchestration usage, business execution, monetary cost and backend model revision unmeasured.',
            'No daily install, production catalog update, merge, or lifecycle change.']}
    result['adaptive_vs_deep'] = {metric: (1 - by_arm['adaptive'][metric] / by_arm['deep'][metric]) * 100
                                for metric in ('mean_seconds', 'mean_tokens', 'mean_calls')}
    write_once(output, result)
    print({'common': common, 'gains_percent': result['adaptive_vs_deep'], 'variation': variation,
           'protected': len(protections)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--live', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    analyze(args.bundle, args.live, args.output)
