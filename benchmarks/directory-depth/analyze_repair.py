"""Preserve failures and attribute boundary-review cost, without changing gold."""
import argparse
from collections import defaultdict
import hashlib
from pathlib import Path

from analyze_adaptive_cost import metrics
from experiment import identity, read, write_once


def analyze(bundle, live, output, summary_name='summary.json'):
    bundle, live = Path(bundle), Path(live)
    plan, summary = read(bundle / 'plan.json'), read(live / summary_name)
    arms = plan['arms']
    if len(arms) < 2 or len(arms) != len(set(arms)):
        raise ValueError('invalid_comparison_arms')
    baseline = arms[0]
    nodes = read(bundle / 'repaired-nodes.json')
    cases = {case['id']: case for case in read(bundle / 'cases.json')}
    rows = summary['rows']
    finished = [r for r in rows if r['usage_complete'] and r['result'].get('reason') in
                {None, 'directory_limit', 'final_limit', 'no_progress'}]
    complete = [case for case in cases if {r['arm'] for r in finished if r['case'] == case} == set(arms)]
    usage, repeated = defaultdict(lambda: defaultdict(float)), defaultdict(list)
    missing, errors = [], []
    for path in live.glob('*.pending.json'):
        request = read(path)
        done = path.with_name(path.name.replace('.pending.json', '.done.json'))
        error = path.with_name(path.name.replace('.pending.json', '.error.json'))
        if not done.exists():
            (errors if error.exists() else missing).append(path.name)
            continue
        result = read(done)
        arm, stage = path.name.split('--')[2:4]
        stage = stage.split('-')[0].split('.')[0]
        for receipt in result['transport']:
            usage[arm][stage + '_calls'] += 1
            usage[arm][stage + '_tokens'] += receipt.get('input_tokens', 0) + receipt.get('output_tokens', 0)
            usage[arm][stage + '_seconds'] += receipt['seconds']
        repeated[identity({'spec': request['spec'], 'state': request['state']})].append(result['answer'])
    boundary, failures, sanitized = [], [], []
    for row in rows:
        required = set(cases[row['case']]['expected_ids'] + cases[row['case']]['pending_ids'])
        stages = []
        for index, trace in enumerate(row['result']['traces']):
            rescued = set().union(*(set(nodes[key]['members']) for key in trace.get('recovered', [])))
            stages.append({'pool_size': len(trace['pool']), 'offered': trace['offered_count'],
                           'boundary': trace.get('boundary', []), 'reviewed': trace.get('reviewed', []),
                           'recovered': trace.get('recovered', []), 'review_skipped': trace.get('review_skipped')})
            if trace.get('reviewed'):
                boundary.append({'case': row['case'], 'stage': index + 1, 'nodes': trace['reviewed'],
                    'recovered': trace['recovered'], 'required_ids_recovered': sorted(required & rescued)})
        if not row['omission_safe_pass']:
            index = row['first_omission_stage']
            trace = row['result']['traces'][index - 1] if index else None
            failures.append({'case': row['case'], 'arm': row['arm'], 'first_omission_stage': index,
                'scores_at_omission': [{'node': key, 'score': value['noul']} for key, value in trace['answers'].items()
                                       if required & set(nodes[key]['members'])] if trace else [],
                'selected': row['result'].get('choice'), 'confidence': row['result'].get('confidence'),
                'status': row['result']['status']})
        sanitized.append({key: value for key, value in row.items() if key not in {'transport', 'result'}} |
            {'result': {key: value for key, value in row['result'].items() if key != 'traces'}, 'stages': stages})
    protected = read(live.parent / 'protected-before.json')
    changed = [path for path, before in protected.items() if
        (hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None) != before]
    aggregate = {arm: metrics([r for r in rows if r['arm'] == arm]) for arm in arms}
    full = summary['stop'] == 'completed' and len(rows) == len(cases) * len(arms) and len(complete) == len(cases)
    result = {'version': 1, 'scope': plan['scope'],
        'plan': {key: value for key, value in plan.items() if key != 'executable'},
        'stop': summary['stop'], 'complete_cases': len(complete), 'all_cases_complete': full,
        'actual_calls': summary['calls'], 'known_tokens': summary['known_tokens'], 'wall_seconds': summary['seconds'],
        'usage_complete': all(r['usage_complete'] for r in rows), 'unresolved': missing, 'errors': errors,
        'by_arm': aggregate,
        'complete_case_ids': complete,
        'complete_case_metrics': {arm: metrics([r for r in rows if r['arm'] == arm and r['case'] in complete]) for arm in arms},
        'case_progress': {case: {arm: ('completed' if any(r['case'] == case and r['arm'] == arm for r in finished)
            else 'incomplete' if any(r['case'] == case and r['arm'] == arm for r in rows) else 'unrun')
            for arm in arms} for case in cases},
        'positive_by_arm': {arm: metrics([r for r in rows if r['arm'] == arm and not r['control']]) for arm in arms},
        'candidate_eligible_on_this_regression': {arm: full and all(r['omission_safe_pass'] for r in rows if r['arm'] == arm)
                                                for arm in arms if arm != baseline},
        'change_vs_baseline_percent': {arm: {field: 100 * (aggregate[arm][field] / aggregate[baseline][field] - 1)
            for field in ('mean_tokens', 'mean_seconds', 'mean_calls')} for arm in arms if full},
        'stage_usage': dict(usage), 'boundary_reviews': boundary, 'failures': failures, 'rows': sanitized,
        'identical_request_groups_with_score_variation': sum(len(v) > 1 and len({identity(a) for a in v}) > 1 for v in repeated.values()),
        'protected_paths_checked': len(protected), 'protected_files_unchanged': not changed,
        'source_summary_sha256': hashlib.sha256((live / summary_name).read_bytes()).hexdigest(),
        'budget_extension': summary.get('extension'),
        'limitations': [plan['limitations'],
            'One pass with independently sampled comparison arms; score and network variation remain. No significance claim.',
            'All semantic failures remain in denominators; lower cost from early failure is not quality-equivalent improvement.',
            'The frozen plan defines the combined treatment; this run does not isolate each changed factor.',
            'Boundary review limit is declared in the frozen plan; all calls, skipped reviews and errors are preserved.',
            'Jev selector timing and reported tokens only. Root-agent and full task execution costs, backend model revision and monetary charges unobservable.',
            'Daily 0.3.73 installation, dispatcher, lifecycle and other worktrees are not modified or functionally retested.']}
    write_once(output, result)
    print({'by_arm': aggregate, 'eligible': result['candidate_eligible_on_this_regression'],
           'boundary_reviews': len(boundary), 'required_rescues': [b for b in boundary if b['required_ids_recovered']],
           'failures': failures, 'changed_protected_paths': len(changed), 'stop': summary['stop']})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--live', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--summary', default='summary.json')
    args = parser.parse_args()
    analyze(args.bundle, args.live, args.output, args.summary)
