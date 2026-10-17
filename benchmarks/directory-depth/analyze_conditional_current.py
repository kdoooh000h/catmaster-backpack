"""Reconcile the one-call current-step trial from frozen inputs and receipts."""
import argparse
import json
from pathlib import Path
import statistics

import conditional_current as F
import conditional_current_experiment as X
import conditional_experiment as C
from experiment import write_once


def aggregate(values):
    called = [r for r in values if r['live_called']]
    return {'cases': len(values), 'live_cases': len(called),
            **{key: sum(r[key] for r in values) for key in
               ['correct_current', 'all_required_retained', 'omission_safe_pass', 'calls', 'tokens']},
            'called_means': {key: statistics.mean(r[key] for r in called) if called else None
                             for key in ['tokens', 'calls', 'jev_cli_seconds',
                                         'current_dispatch_wall_seconds', 'selector_seconds']}}


def report(output, destination):
    out = Path(output); plan, bundle = X.verify_frozen(out)
    summary = C.E.read(out/'live/summary.json')
    cases = {c['id']: c for c in C.E.read(out/'cases.json')}
    catalog = C.E.read(bundle/'catalog.json'); question = C.E.read(bundle/'question.json')['question']
    pairs = {(c, a) for c in cases for a in F.ARMS}
    if (summary['stop'] != 'completed' or len(summary['rows']) != len(pairs)
            or {(r['case'], r['arm']) for r in summary['rows']} != pairs):
        raise ValueError('incomplete_comparison')
    previous = Path(plan['previous'])
    if C.digest(previous/'live/summary.json') != plan['old_result_sha256']:
        raise ValueError('previous_results_changed')
    old_bundle = Path(C.E.read(previous/'plan.json')['bundle'])
    originals = {c['id']: c for c in C.E.read(old_bundle/'cases.json')}
    for key in X.FAILED:
        if cases[key] != originals[key]: raise ValueError('original_case_changed')
    if set(cases) & (set(originals)-set(X.FAILED)):
        raise ValueError('passed_case_replayed')
    receipts = {}; rows = []; pool_coverage = {}
    for row in summary['rows']:
        case = cases[row['case']]; result = row['result']
        recall_audit = C.E.read(out/(row['case']+'.recall.json')); recall = recall_audit['recall']
        if result['retained_candidates'] != recall['pool']:
            raise ValueError('retained_pool_changed')
        if result['traces'] != [{'stage': 'conditional_recall', 'pool': sorted(recall['pool'])}]:
            raise ValueError('trace_changed')
        if row['case'] in X.FAILED and recall != C.E.read(previous/(row['case']+'.recall.json'))['recall']:
            raise ValueError('original_recall_changed')
        if any(row[key] != value for key, value in C.grade(case, result).items()):
            raise ValueError('grade_changed')
        current = []; answer = None
        stem = row['case']+'--'+row['arm']+'--final'
        if recall_audit['eligible_for_live']:
            pending = C.E.read(out/'live'/(stem+'.pending.json'))
            done = C.E.read(out/'live'/(stem+'.done.json'))
            if pending['state'] != {'task': case['need']}:
                raise ValueError('raw_need_changed')
            if pending['spec'] != F.specification(row['arm'], catalog, recall['pool'], question):
                raise ValueError('final_payload_changed')
            answer = done['answer']['answers']['answer']
            confidence, choice = answer['confidence'], answer['choice']
            status = 'abstain' if confidence < .7 else 'none' if choice == 'none' else 'selected'
            if (result['status'] != status or result['confidence'] != confidence
                    or result['raw_choice'] != choice
                    or result['choice'] != (choice if confidence >= .7 else None)):
                raise ValueError('final_answer_mismatch')
            current = done['transport']
            if len(current) != 1 or pending['ordinal'] in receipts:
                raise ValueError('one_call_contract_broken')
            receipts[pending['ordinal']] = current[0]
        elif (result['status'] != 'preflight_failed' or row['live_called']
              or (out/'live'/(stem+'.pending.json')).exists()):
            raise ValueError('preflight_failure_policy_changed')
        if (current != row['transport'] or row['calls'] != len(current)
                or row['tokens'] != sum(r['input_tokens']+r['output_tokens'] for r in current)
                or row['jev_cli_seconds'] != sum(r['seconds'] for r in current)):
            raise ValueError('usage_mismatch')
        pool_coverage[case['id']] = {
            'required': len(case['expected_ids']+case['pending_ids']),
            'retained': sum(i in recall['pool'] for i in case['expected_ids']+case['pending_ids']),
            'pending_required': len(case['pending_ids']),
            'pending_retained': sum(i in recall['pool'] for i in case['pending_ids']),
            'missing_ids': recall_audit['missing_required']}
        rows.append({k: v for k, v in row.items() if k not in {'transport', 'result', 'first_lost'}} |
                    {k: result.get(k) for k in ['status', 'choice', 'raw_choice', 'confidence', 'final_pool_size']} |
                    {'expected_ids': case['expected_ids'], 'pending_ids': case['pending_ids'],
                     'missing_ids': recall_audit['missing_required']})
    ordered = [receipts[i] for i in sorted(receipts)]
    if (sorted(receipts) != list(range(1, summary['calls']+1))
            or ordered != summary['transport'] or any(r['outcome'] != 'completed' for r in ordered)
            or sum(r['input_tokens']+r['output_tokens'] for r in ordered) != summary['known_tokens']):
        raise ValueError('total_receipt_mismatch')
    pending_files = list((out/'live').glob('*.pending.json'))
    done_files = list((out/'live').glob('*.done.json'))
    if (len(pending_files) != len(ordered) or len(done_files) != len(ordered)
            or list((out/'live').glob('*.error.json'))
            or any(not Path(str(p).replace('.pending.json', '.done.json')).exists() for p in pending_files)):
        raise ValueError('unknown_or_extra_call')
    totals = {arm: aggregate([r for r in rows if r['arm'] == arm]) for arm in F.ARMS}
    strata = {group: {arm: aggregate([r for r in rows if r['arm'] == arm and r['stratum'] == group])
                     for arm in F.ARMS} for group in ['old_failure', 'new']}
    baseline, candidate = [totals[a]['called_means'] for a in F.ARMS]
    value = {'version': 1, 'catalog_count': len(catalog), 'final_gate': .7,
             'difference': plan['difference'], 'aggregates': totals, 'strata': strata, 'rows': rows,
             'calls': summary['calls'], 'known_tokens': summary['known_tokens'],
             'new_index_seconds': plan['new_index_seconds'], 'reference_coverage': pool_coverage,
             'change_percent_called_only': {k: 100*(candidate[k]/baseline[k]-1) for k in baseline},
             'source_sha256': plan['source_sha256'], 'catalog_sha256': plan['catalog_sha256'],
             'frozen_case_sha256': plan['frozen_sha256']['cases.json'],
             'scope': 'Three original failed needs and four new author-written combinations. No passed need rerun; no daily installation or capability execution.',
             'limits': [plan['limits'], plan['cost_basis'],
                        'Known incomplete recalls are skipped before model dispatch and count as failures in the seven-case denominator.',
                        'Latency and token means compare only the same five live pairs; skipped rows do not lower these means.',
                        'Reference coverage is not proof that every equivalent capability is retained. Recalled alternatives have not been executed.',
                        'The complete recalled pool is preserved, not semantically relabeled as later-only capabilities.',
                        'All five live current references are historical control Skills; the two new public publisher references fail recall.'],
             'verdict': 'do_not_promote' if totals[F.ARMS[1]]['omission_safe_pass'] != len(cases) else 'bounded_case_pass_only'}
    write_once(destination, value)
    print(json.dumps({'aggregates': totals, 'change_percent_called_only': value['change_percent_called_only'],
                      'calls': value['calls'], 'tokens': value['known_tokens']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output', required=True)
    parser.add_argument('--destination', required=True); args = parser.parse_args()
    report(args.output, args.destination)
