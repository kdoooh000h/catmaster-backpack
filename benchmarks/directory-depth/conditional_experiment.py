"""Frozen find-style vs adaptive experiment. Public metadata selection only.

prepare performs offline recall checks first. run requires those checks to pass;
no market downloads, installation, task execution, retries or automatic resumes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time

import merged_experiment as E
from conditional_search import SearchIndex
from source_preflight import save

ROOT = Path(__file__).resolve().parents[2]
ARMS = ['adaptive', 'conditional_find']


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources():
    return {str(p.relative_to(ROOT)): digest(p) for p in [
        Path(__file__), Path(__file__).with_name('conditional_search.py'),
        Path(E.__file__), Path(E.__file__).with_name('adaptive_experiment.py'),
        Path(E.__file__).with_name('experiment.py'), ROOT/'core/jev_hierarchy_provider.py']}


def final_spec(rows, pool, question):
    # Exactly the same descriptions, ID order, instruction and raw task as the
    # adaptive arm. Retrieval order is not a hidden preference in final Choice.
    selected = set(pool)
    choices = {r['id']: r['description'] for r in rows if r['id'] in selected}
    choices['none'] = 'No offered capability meets the explicitly required current operation.'
    return {'questions': {'answer': {'type': 'choice', 'instructions': question, 'criteria': choices}}}


def grade(case, result):
    required = set(case['expected_ids'] + case['pending_ids'])
    traces = result.get('traces', [])
    kept = bool(traces) and all(required <= set(t['pool']) for t in traces)
    current = result['status'] == 'selected' and result.get('choice') in case['expected_ids']
    return {'correct_current': current, 'all_required_retained': kept,
            'omission_safe_pass': bool(current and kept),
            'first_lost': {i: next((j+1 for j, t in enumerate(traces) if i not in t['pool']), None)
                           for i in sorted(required)}}


def prepare(bundle, output):
    bundle, out = Path(bundle).resolve(), Path(output).resolve()
    out.mkdir(mode=0o700, exist_ok=False)
    rows = E.read(bundle/'catalog.json')
    # Build before evaluation labels are loaded. Never pass gold to retrieval.
    index = SearchIndex(rows)
    cases, question = E.read(bundle/'cases.json'), E.read(bundle/'question.json')['question']
    results = []
    try:
        for case in cases:
            recall = index.search(case['need'])
            required = set(case['expected_ids'] + case['pending_ids'])
            missing = sorted(required - set(recall['pool']))
            item = {'case': case['id'], 'need': case['need'], 'recall': recall,
                    'missing_required': missing, 'reference_coverage_pass': not missing,
                    'final_payload_chars': len(json.dumps(final_spec(rows, recall['pool'], question), ensure_ascii=False))}
            save(out/(case['id']+'.recall.json'), item)
            results.append({k: v for k, v in item.items() if k not in {'recall', 'need'}} |
                           {k: recall[k] for k in ['status', 'pool_size', 'seconds', 'boundary_ties']})
    finally:
        index.close()
    plan = {'version': 1, 'arms': ARMS, 'bundle': str(bundle), 'final_gate': .7,
            'catalog_count': len(rows), 'cases': len(cases), 'max_calls': 60,
            'max_tokens': 220000, 'max_seconds': 180, 'attempts': 1,
            'per_clause': 8, 'per_concept': 3, 'max_candidates': 96,
            'index_seconds': index.seconds, 'source_sha256': sources(),
            'input_sha256': {name: digest(bundle/name) for name in
                             ['catalog.json', 'nodes.json', 'cases.json', 'question.json']},
            'executable': '/Users/kk/.local/bin/jev',
            'executable_sha256': digest('/Users/kk/.local/bin/jev'),
            'recall_sha256': {p.name: digest(p) for p in out.glob('*.recall.json')},
            'scope': 'Known five development needs. Same merged frozen public corpus; whole plugins; metadata selection only.',
            'hypothesis': 'Per-clause lexical recall with additive bilingual concepts reduces directory calls without losing current or mandatory later references.',
            'live_start_requires': 'All five offline reference-coverage checks pass, no pool overflow, valid tests. No per-case tuning or gold injection.',
            'no_daily_changes': True, 'no_market_reads': True,
            'limitations': ['Lexical coverage is not a semantic completeness guarantee.',
                           'The bilingual vocabulary and method are evaluated on known development needs, not a blind generalization test.',
                           'Main Agent, intent entry tokens and backend revision are unobservable.',
                           'One response can cross a pre-dispatch token cap; conservative estimated reserve also checked.']}
    save(out/'plan.json', plan)
    preflight = {'rows': results, 'index_seconds': index.seconds,
                 'ready_for_live': all(r['reference_coverage_pass'] and r['status'] == 'recalled' for r in results)}
    save(out/'preflight.json', preflight)
    print(json.dumps(preflight, ensure_ascii=False), flush=True)


def run(output):
    out = Path(output); plan = E.read(out/'plan.json'); bundle = Path(plan['bundle'])
    if not E.read(out/'preflight.json')['ready_for_live']:
        raise ValueError('offline_recall_failed_no_live_sends')
    for name, sha in plan['input_sha256'].items():
        if digest(bundle/name) != sha: raise ValueError('frozen_input_changed')
    if sources() != plan['source_sha256']: raise ValueError('frozen_source_changed')
    if digest(plan['executable']) != plan['executable_sha256']: raise ValueError('frozen_executable_changed')
    for name, sha in plan['recall_sha256'].items():
        if digest(out/name) != sha: raise ValueError('frozen_recall_changed')
    live = out/'live'; live.mkdir(mode=0o700, exist_ok=False)
    rows, nodes, cases, question = [E.read(bundle/n) for n in ['catalog.json', 'nodes.json', 'cases.json', 'question.json']]
    began = time.monotonic(); spent = 0; calls = 0; completed = []
    provider = E.JevHierarchyProvider({'executable': plan['executable'], 'timeout_seconds': 20}, deadline=began+plan['max_seconds'])
    stop = 'completed'
    try:
        for number, case in enumerate(cases):
            for arm in (ARMS if number % 2 else list(reversed(ARMS))):
                offset = len(provider.calls); started = time.monotonic()
                def invoke(stage, spec, state):
                    nonlocal spent, calls
                    # Reserve based on complete input plus structured output;
                    # this is deliberately conservative, not billed usage.
                    count = sum(len(q.get('criteria', {})) for q in spec['questions'].values())
                    reserve = len(json.dumps({'spec': spec, 'state': state}, ensure_ascii=False))//2 + count*24 + 2000
                    if calls >= plan['max_calls'] or spent+reserve > plan['max_tokens']:
                        raise RuntimeError('budget_stop')
                    path = live/(case['id']+'--'+arm+'--'+stage)
                    if Path(str(path)+'.pending.json').exists(): raise RuntimeError('pending_send_no_replay')
                    save(str(path)+'.pending.json', {'spec': spec, 'state': state, 'ordinal': calls+1})
                    calls += 1; before = len(provider.calls)
                    try:
                        raw = provider.noul(spec, state)
                    except Exception as error:
                        save(str(path)+'.error.json', {'error': str(error), 'transport': provider.calls[before:]})
                        raise
                    receipts = provider.calls[before:]
                    save(str(path)+'.done.json', {'answer': raw, 'transport': receipts})
                    if len(receipts) != 1 or receipts[0].get('outcome') != 'completed' or not {'input_tokens', 'output_tokens'} <= receipts[0].keys():
                        raise RuntimeError('unknown_outcome_or_usage_stop')
                    spent += receipts[0]['input_tokens']+receipts[0]['output_tokens']
                    return raw
                recall_seconds = 0
                if arm == 'adaptive':
                    result = E.route('baseline', nodes, rows, case['need'], question['question'], invoke)
                else:
                    recall = E.read(out/(case['id']+'.recall.json'))['recall']
                    pool = recall['pool']; recall_seconds = recall['seconds']
                    raw = invoke('final', final_spec(rows, pool, question['question']), {'task': case['need']})
                    answer = raw['answers'].get('answer', {})
                    choices = final_spec(rows, pool, question['question'])['questions']['answer']['criteria']
                    if answer.get('type') != 'choice' or answer.get('choice') not in choices or not E.probability(answer.get('confidence')):
                        raise ValueError('invalid_final_answer')
                    confidence, choice = answer['confidence'], answer['choice']
                    result = {'status': 'abstain' if confidence < .7 else 'none' if choice == 'none' else 'selected',
                              'choice': choice if confidence >= .7 else None, 'confidence': confidence,
                              'traces': [{'pool': sorted(pool), 'stage': 'conditional_recall'}], 'final_pool_size': len(pool)}
                receipts = provider.calls[offset:]
                item = {'case': case['id'], 'arm': arm, 'result': result, **grade(case, result),
                        'jev_cli_seconds': sum(r['seconds'] for r in receipts), 'local_search_seconds': recall_seconds,
                        'route_wall_seconds': time.monotonic()-started+recall_seconds,
                        'calls': len(receipts), 'tokens': sum(r['input_tokens']+r['output_tokens'] for r in receipts)}
                save(live/(case['id']+'--'+arm+'.json'), item); completed.append(item)
                print(json.dumps({k: v for k, v in item.items() if k != 'result'}, ensure_ascii=False), flush=True)
    except Exception as error:
        stop = str(error)
    # Costs include failures, even when no complete row was produced.
    all_tokens = sum(r.get('input_tokens', 0)+r.get('output_tokens', 0) for r in provider.calls)
    save(live/'summary.json', {'stop': stop, 'rows': completed, 'calls': len(provider.calls),
                             'known_tokens': all_tokens, 'wall_seconds': time.monotonic()-began,
                             'transport': provider.calls})
    print(json.dumps({'stop': stop, 'calls': len(provider.calls), 'tokens': all_tokens}), flush=True)


def report(output, destination):
    out = Path(output); summary = E.read(out/'live/summary.json'); plan = E.read(out/'plan.json')
    cases = {c['id']: c for c in E.read(Path(plan['bundle'])/'cases.json')}
    if summary['stop'] != 'completed' or len(summary['rows']) != 10: raise ValueError('incomplete_comparison')
    receipts = []; compact = []
    for row in summary['rows']:
        if any(row[k] != v for k, v in grade(cases[row['case']], row['result']).items()): raise ValueError('grade_changed')
        current = []
        for path in sorted((out/'live').glob(row['case']+'--'+row['arm']+'--*.done.json')):
            done = E.read(path); pending = E.read(str(path).replace('.done.json', '.pending.json'))
            if pending['state']['task'] != cases[row['case']]['need']: raise ValueError('raw_need_changed')
            current += done['transport']
        if len(current) != row['calls'] or sum(r['input_tokens']+r['output_tokens'] for r in current) != row['tokens']:
            raise ValueError('usage_mismatch')
        if row['result']['status'] == 'selected' and row['result']['confidence'] < .7: raise ValueError('final_gate_changed')
        receipts += current
        compact.append({k: v for k, v in row.items() if k != 'result'} | {k: row['result'].get(k) for k in ['status', 'choice', 'confidence', 'final_pool_size']})
    if len(receipts) != summary['calls'] or any(r['outcome'] != 'completed' for r in receipts): raise ValueError('receipt_mismatch')
    if sum(r['input_tokens']+r['output_tokens'] for r in receipts) != summary['known_tokens']: raise ValueError('total_usage_mismatch')
    missing = [p.name for p in (out/'live').glob('*.pending.json') if not Path(str(p).replace('.pending.json', '.done.json')).exists()]
    if missing: raise ValueError('unknown_pending_send')
    aggregate = {}
    for arm in ARMS:
        values = [r for r in compact if r['arm'] == arm]
        aggregate[arm] = {'cases': len(values), 'correct_current': sum(r['correct_current'] for r in values),
                          'all_required_retained': sum(r['all_required_retained'] for r in values),
                          'omission_safe_passes': sum(r['omission_safe_pass'] for r in values),
                          **{'mean_'+k: statistics.mean(r[k] for r in values) for k in
                             ['jev_cli_seconds', 'local_search_seconds', 'route_wall_seconds', 'tokens', 'calls', 'final_pool_size']}}
    result = {'version': 1, 'catalog_count': plan['catalog_count'], 'final_gate': .7,
              'preflight': E.read(out/'preflight.json'), 'aggregates': aggregate, 'rows': compact,
              'calls': summary['calls'], 'known_tokens': summary['known_tokens'],
              'index_seconds': plan['index_seconds'], 'limits': plan['limitations'],
              'verdict': 'known_five_pass_only' if aggregate['conditional_find']['omission_safe_passes'] == 5 else 'do_not_promote',
              'no_daily_install_or_market_execution': True}
    save(destination, result)
    print(json.dumps({'aggregates': aggregate, 'calls': summary['calls'], 'tokens': summary['known_tokens']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('operation', choices=['prepare', 'run', 'report'])
    parser.add_argument('--bundle'); parser.add_argument('--output', required=True); parser.add_argument('--destination')
    args = parser.parse_args()
    if args.operation == 'prepare': prepare(args.bundle, args.output)
    elif args.operation == 'run': run(args.output)
    else: report(args.output, args.destination)
