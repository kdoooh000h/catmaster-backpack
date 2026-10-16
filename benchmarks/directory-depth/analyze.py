"""Summarize receipts without new calls; counterfactuals are diagnostic only."""
import argparse
from collections import Counter
import hashlib
import statistics
from pathlib import Path

from experiment import ARMS, human_tree, read, schedule, semantic_tree, union, frontier, write_once


def replay(nodes, cuts, traces, threshold):
    """Reuse observed scores, not an equivalent live smaller-batch model run."""
    active = ['n']
    pools = []
    for depth, trace in zip(cuts, traces):
        offered = frontier(nodes, active, depth)
        if not set(offered) <= set(trace['answers']):
            return None
        active = [key for key in offered if trace['answers'][key]['noul'] >= threshold]
        pools.append(sorted(union(nodes, active)))
        if not active:
            break
    return pools


def analyze(bundle, live, output):
    bundle, live = Path(bundle), Path(live)
    plan, catalog, taxonomy = [read(bundle / name) for name in ('plan.json', 'catalog.json', 'taxonomy.json')]
    cases = {case['id']: case for case in read(bundle / 'cases.json')}
    summary = read(live / 'summary.json')
    rows = summary['rows']
    # Equal-case comparison: all arms reached a terminal result before budget exhaustion.
    common = [case for case in cases if all(any(row['case'] == case and row['arm'] == arm
              and row['result'].get('reason') != 'experiment_budget_stop' for row in rows) for arm in ARMS)]
    by_arm = {}
    for arm in ARMS:
        selected = [row for row in rows if row['arm'] == arm and row['case'] in common]
        by_arm[arm] = {
            'case_count': len(selected), 'final_choice_successes': sum(row['passed'] for row in selected),
            'all_required_retained_cases': sum(row['all_required_retained'] is True for row in selected),
            'omission_safe_successes': sum(row['omission_safe_pass'] for row in selected),
            'mean_seconds': statistics.mean(row['seconds'] for row in selected) if selected else None,
            'mean_tokens': statistics.mean(row['known_tokens'] for row in selected) if selected else None,
            'mean_calls': statistics.mean(row['calls'] for row in selected) if selected else None,
            'terminal_pool_sizes': [len(row['result']['traces'][-1]['pool']) for row in selected if row['result']['traces']],
            'statuses': dict(Counter(row['result'].get('reason', row['result']['status']) for row in selected)),
        }
    trees = {4: semantic_tree(catalog, taxonomy, 4), 6: semantic_tree(catalog, taxonomy, 6)}
    human = human_tree(taxonomy)
    counterfactuals = []
    for threshold in (.3, .5, .7):
        for arm, shape in ARMS.items():
            nodes = human if shape is None else trees[shape[0]]
            cuts = [1, 2] if shape is None else schedule(*shape)
            diagnostic = []
            for row in rows:
                if row['arm'] != arm or row['case'] not in common:
                    continue
                pools = replay(nodes, cuts, row['result']['traces'], threshold)
                required = set(cases[row['case']]['expected_ids'] + cases[row['case']]['pending_ids'])
                diagnostic.append({'case': row['case'], 'all_required_retained': all(required <= set(pool) for pool in pools),
                                   'terminal_pool_size': len(pools[-1])})
            counterfactuals.append({'threshold': threshold, 'arm': arm, 'rows': diagnostic})
    compact_rows = [{k: v for k, v in row.items() if k not in {'result', 'transport'}} | {
        'status': row['result']['status'], 'reason': row['result'].get('reason'),
        'stages': [{'offered': trace['offered_count'], 'retained': trace['retained_count'],
                    'pool_size': len(trace['pool'])} for trace in row['result']['traces']]}
        for row in rows]
    result = {
        'version': 1, 'scope': 'public routing experiment; no capability execution or daily deployment',
        'source': read(bundle / 'provenance.json'), 'frozen_plan': {k: v for k, v in plan.items() if k != 'executable'},
        'plan_file_sha256': hashlib.sha256((bundle / 'plan.json').read_bytes()).hexdigest(),
        'raw_summary_sha256': hashlib.sha256((live / 'summary.json').read_bytes()).hexdigest(),
        'stop': summary['stop'], 'planned_cases': len(cases), 'common_completed_cases': common,
        'actual_calls': summary['calls'], 'known_tokens': summary['known_tokens'],
        'input_tokens': sum(t.get('input_tokens', 0) for row in rows for t in row['transport']),
        'output_tokens': sum(t.get('output_tokens', 0) for row in rows for t in row['transport']),
        'usage_complete_for_attempts': all(row['usage_complete'] for row in rows),
        'sum_row_seconds': sum(row['seconds'] for row in rows),
        'final_choice_calls': sum(path.name.endswith('--final.done.json') for path in live.glob('*.done.json')),
        'by_arm_common_cases': by_arm, 'structure_oracle_only': read(bundle / 'structure.json'),
        'rows': compact_rows, 'counterfactuals_diagnostic_only': counterfactuals,
        'counterfactual_limit': 'Threshold sweep reuses recorded scores. Different offered batches can change model scores; no final choices, live accuracy or live cost inferred.',
        'verdict': 'No eligible winner; overly permissive early retention and weak summaries prevent narrowing. More layers increased observed cost; depth alone was not isolated from pruning failure.',
        'unmeasured': ['final .7 choice accuracy', 'negative controls', 'mixed-language cases', 'pending-action case',
                       'main Agent end-to-end latency/tokens', 'monetary cost', 'model/server revision'],
    }
    write_once(output, result)
    print({'common_cases': common, 'calls': result['actual_calls'], 'tokens': result['known_tokens'], 'final_choice_calls': result['final_choice_calls']})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--live', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    analyze(args.bundle, args.live, args.output)
