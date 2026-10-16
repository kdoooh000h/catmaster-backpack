"""Freeze new domains without changing either selector or retrying old cases."""
import argparse
from pathlib import Path
import random

from adaptive_cost_experiment import ROOT, digest
from experiment import read, write_once
import slim_experiment as S

FIXTURES = Path(__file__).with_name('breadth_cases.json')


def validate_cases(cases, old_cases, catalog, nodes):
    by_id = {row['id']: row for row in catalog}
    old_needs = {c['need'] for c in old_cases}
    old_targets = {key for c in old_cases for key in c['expected_ids'] + c['pending_ids']}
    if len(cases) != 28 or len({c['id'] for c in cases}) != 28 or len({c['need'] for c in cases}) != 28:
        raise ValueError('invalid_case_set')
    required = {key for c in cases for key in c['expected_ids'] + c['pending_ids']}
    if len(required) != 20 or required & old_targets:
        raise ValueError('targets_not_new')
    for case in cases:
        targets = case['expected_ids'] + case['pending_ids']
        if case['need'] in old_needs or any(key not in by_id or key.casefold() in case['need'].casefold() for key in targets):
            raise ValueError('old_request_invalid_or_named_target')
        if case['control'] != (not targets) or (not case['control'] and len(case['expected_ids']) != 1):
            raise ValueError('invalid_gold')
    roots = sorted(key for key, node in nodes.items() if node['depth'] == 1 and required & set(node['members']))
    domains = sorted({domain for key in required for domain in by_id[key]['source_domains']})
    multi = [case for case in cases if case['pending_ids']]
    if len(roots) != 6 or len(domains) < 14 or len(multi) != 4 or sum(c['control'] for c in cases) != 4:
        raise ValueError('breadth_coverage_changed')
    for case in multi:
        first_roots = {key for key in roots if case['expected_ids'][0] in nodes[key]['members']}
        later_roots = {key for key in roots if any(i in nodes[key]['members'] for i in case['pending_ids'])}
        if first_roots & later_roots:
            raise ValueError('multi_task_not_cross_root')
    return {'roots': roots, 'source_domains': domains, 'new_target_ids': sorted(required),
            'controls': 4, 'positive_cases': 24, 'cross_root_multi_cases': 4}


def freeze(source, output):
    source, output = Path(source), Path(output)
    previous = read(source / 'plan.json')
    for name, sha in previous['input_sha256'].items():
        if digest(source / name) != sha: raise ValueError('source_input_changed')
    for name, sha in previous['source_sha256'].items():
        if digest(ROOT / name) != sha: raise ValueError('selector_changed_before_new_cases')
    if previous['arms'] != S.ARMS or previous['final_gate'] != .7:
        raise ValueError('previous_policy_changed')
    cases = read(FIXTURES)['cases']
    prior = read(source / 'cases.json') + read(Path(__file__).with_name('large_public_cases.json'))['cases']
    catalog, nodes = read(source / 'catalog.json'), read(source / 'repaired-nodes.json')
    coverage = validate_cases(cases, prior, catalog, nodes)
    by_id = {row['id']: row for row in catalog}
    for case in cases:
        case['gold_sources'] = [{'id': key, 'source': by_id[key]['source'],
                                 'description': by_id[key]['description']}
                               for key in case['expected_ids'] + case['pending_ids']]
    random.Random(20261016).shuffle(cases)
    output.mkdir(mode=0o700, exist_ok=False)
    for name in ('catalog.json', 'nodes.json', 'repaired-nodes.json', 'question.json'):
        with (output / name).open('xb') as stream: stream.write((source / name).read_bytes())
    write_once(output / 'cases.json', cases)
    sources = list(previous['source_sha256']) + [
        'benchmarks/directory-depth/breadth_experiment.py', 'benchmarks/directory-depth/breadth_cases.json',
        'benchmarks/directory-depth/large_public_cases.json']
    plan = {**previous, 'case_count': 28, 'case_order': [c['id'] for c in cases],
        'baseline_plan_sha256': digest(source / 'plan.json'), 'same_case_bytes': False,
        'same_selector_bytes': True, 'coverage': coverage,
        'max_calls': 392, 'max_known_tokens': 800000, 'max_seconds': 600,
        'ordering': 'Case order shuffled once with seed 20261016; alternate fresh arms by case; one pass.',
        'scope': 'New-case breadth selection test only; no installs, private data, lifecycle changes or capability execution.',
        'changes': ['Only new public synthetic needs and evaluation gold; both selectors and corrected metadata unchanged.'],
        'acceptance': 'All new cases must retain every annotated current/later target and select correctly; controls must return none. Every semantic failure remains. Stop on transport, missing usage, malformed output or budget. No retries or in-run tuning.',
        'limitations': 'Author-written new regression cases after code freeze, not independent blind review or a random sample of real users. Reference-target omission and exact first-target choice are measured; generic substitutes are not assumed equivalent. One pass; no population-accuracy or significance claim.',
        'source_sha256': {name: digest(ROOT / name) for name in sources},
        'input_sha256': {path.name: digest(path) for path in output.glob('*.json')}}
    write_once(output / 'plan.json', plan)
    print({'cases': 28, 'roots': len(coverage['roots']), 'source_domains': len(coverage['source_domains']),
           'new_targets': 20, 'selector_unchanged': True, 'final_gate': .7})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['freeze', 'run'])
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.operation == 'freeze': freeze(args.source, args.output)
    else: S.run(args.source, args.output)
