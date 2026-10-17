"""Reconcile frozen current-shortlist receipts without new provider calls."""
import argparse
import json
from pathlib import Path
import statistics

import focused_experiment as X
from experiment import read, write_once


def aggregate(rows):
    live = [r for r in rows if r['calls']]
    return {'cases': len(rows), **{k: sum(r[k] for r in rows) for k in
            ['omission_safe_pass', 'strict_pass', 'legacy_anchor_pass', 'all_required_retained',
             'all_primary_references_retained', 'calls', 'tokens']},
            'measured_cases': len(live), 'means': {k: statistics.mean(r[k] for r in live) for k in
            ['tokens', 'input_tokens', 'output_tokens', 'retrieval_seconds', 'dispatch_seconds',
             'selector_seconds', 'shortlist_size', 'pool_size']} if live else None}


def analyze(output, destination):
    out = Path(output)
    plan, bundle = X.verify(out)
    summary = read(out/'live/summary.json')
    selected = read(out/'cases.json')
    rows = read(bundle/'catalog.json')
    by_id = {r['id']: r for r in rows}
    X.validate_cases(selected, Path(plan['previous']), rows)
    cases = {c['id']: c for c in selected}
    expected = {(c, a) for c in cases for a in X.ARMS}
    actual = {(r['case'], r['arm']) for r in summary['rows']}
    if summary['stop'] != 'completed' or actual != expected or len(summary['rows']) != len(expected):
        raise ValueError('incomplete_comparison')
    receipts, records, coverage = {}, [], {}
    for row in summary['rows']:
        case, arm = cases[row['case']], row['arm']
        info = read(out/(case['id']+'.recall.json'))
        recall = info['recalls'][arm]
        base = info['recalls']['full_independent']
        if not set(base['pool']) <= set(info['recalls']['focused']['pool']):
            raise ValueError('baseline_reservoir_lost')
        check = X.coverage(case, recall, arm)
        result = row['result']
        if row['coverage'] != check or result['retained_candidates'] != recall['pool']:
            raise ValueError('coverage_or_reservoir_changed')
        grade = X.grade(case, result, recall)
        if any(row[k] != v for k, v in grade.items()):
            raise ValueError('grade_changed')
        stem = out/'live'/(case['id']+'--'+arm)
        item = {k: v for k, v in row.items() if k not in ['result', 'transport', 'coverage']}
        item.update(status=result['status'], choice=result['choice'], confidence=result['confidence'],
                    selected_name=by_id.get(result['choice'], {}).get('name'),
                    selected_kind=by_id.get(result['choice'], {}).get('kind'),
                    pool_size=len(recall['pool']), shortlist_size=len(recall['shortlist']),
                    input_tokens=0, output_tokens=0,
                    legacy_anchor_pass=bool(grade['legacy_correct_current'] and grade['all_primary_references_retained']))
        cov = {**check, 'later_required': len(case['pending_groups']),
               'later_retained': sum(bool(set(g) & set(recall['pool'])) for g in case['pending_groups']),
               'required_groups': len(case['pending_groups'])+1,
               'retained_groups': int(check['current_in_shortlist']) + len(case['pending_groups'])-len(check['missing_later_groups']),
               'primary_required': len(case['primary_pending_ids'])+1,
               'primary_retained': int(check['primary_current_in_shortlist'])+sum(check['primary_later_in_pool'])}
        coverage.setdefault(case['id'], {})[arm] = cov
        if check['eligible']:
            pending, done = read(str(stem)+'.pending.json'), read(str(stem)+'.done.json')
            spec, state, _ = X.specification(arm, rows, recall, case['need'])
            if pending['spec'] != spec or pending['state'] != state or state['task'] != case['need']:
                raise ValueError('payload_changed')
            if X.select(arm, rows, recall, case['need'], lambda *args: done['answer']) != result:
                raise ValueError('saved_answer_changed')
            transport = done['transport']
            if not X.known_usage(transport) or transport != row['transport'] or row['calls'] != 1:
                raise ValueError('receipt_changed')
            receipt = transport[0]
            if row['tokens'] != receipt['input_tokens']+receipt['output_tokens']:
                raise ValueError('tokens_changed')
            if pending['reserved_tokens'] != X.token_reserve(spec, state) or pending['ordinal'] in receipts:
                raise ValueError('pending_changed')
            receipts[pending['ordinal']] = receipt
            item.update(input_tokens=receipt['input_tokens'], output_tokens=receipt['output_tokens'],
                        payload_bytes=len(json.dumps({'spec': spec, 'state': state}, ensure_ascii=False).encode()),
                        questions=len(spec['questions']))
        elif (row['calls'] or row['tokens'] or row['transport'] or result['status'] != 'preflight_failed'
              or Path(str(stem)+'.pending.json').exists()):
            raise ValueError('ineligible_send')
        records.append(item)
    live = out/'live'
    if (sorted(receipts) != list(range(1, summary['calls']+1))
            or [receipts[i] for i in sorted(receipts)] != summary['transport']
            or len(list(live.glob('*.pending.json'))) != len(receipts)
            or len(list(live.glob('*.done.json'))) != len(receipts)
            or list(live.glob('*.error.json'))
            or sum(r['tokens'] for r in records) != summary['known_tokens']):
        raise ValueError('receipt_set_changed')
    totals = {arm: aggregate([r for r in records if r['arm'] == arm]) for arm in X.ARMS}
    paired_ids = set.intersection(*[{r['case'] for r in records if r['arm'] == a and r['calls']} for a in X.ARMS])
    paired = {arm: aggregate([r for r in records if r['arm'] == arm and r['case'] in paired_ids]) for arm in X.ARMS}
    changes = {k: 100*(paired['focused']['means'][k]/v-1) for k, v in (paired['full_independent']['means'] or {}).items() if v}
    strata = {field: {str(value): {a: aggregate([r for r in records if r['arm'] == a and r[field] == value]) for a in X.ARMS}
                     for value in sorted({r[field] for r in records})} for field in ['stratum', 'kind_stratum', 'language']}
    dic = read(out.parent/'cedict-manifest.json')
    report = {'version': 1, 'reference_version': 2, 'final_gate': .7, 'catalog_count': len(rows),
              'catalog_sha256': plan['locks'][str(bundle/'catalog.json')],
              'source_sha256': plan['source_sha256'], 'cases_sha256': plan['frozen_sha256']['cases.json'],
              'aggregates': totals, 'strata': strata, 'paired_cases': sorted(paired_ids),
              'paired': paired, 'paired_change_percent': changes, 'reference_coverage': coverage,
              'rows': records, 'calls': summary['calls'], 'tokens': summary['known_tokens'],
              'run_limits': read(live/'run-limits.json'),
              'startup_seconds': {k: plan[k] for k in ['index_load_seconds', 'dictionary_load_seconds', 'local_index_startup_seconds']},
              'dictionary': dic,
              'limitations': ['Prospective retrieval-informed metadata references; published old scores are unchanged.',
                              'Current equivalence coverage and known primary-anchor retention are separate; exhaustive semantic recall is unproven.',
                              'Only remaining failed cases and five new needs; one localization metadata gap excluded before retrieval.',
                              'No capability installation/execution; no claim all requested output details exist.',
                              'Independent suitability confidence remains >=0.7; changing prompt/context need not preserve calibration.',
                              'Warm times include fresh local retrieval and one final dispatch. Cold model/dictionary/index startup is separate.',
                              'Paired costs use only same needs actually sent in both arms. Offline omissions remain denominator failures.',
                              'One live sample per eligible pair; concurrent Mac load uncontrolled. Main-Agent usage, money and backend revision unobservable.'],
              'verdict': 'do_not_promote'}
    write_once(destination, report)
    print(json.dumps({k: report[k] for k in ['aggregates', 'paired_change_percent', 'calls', 'tokens']}, ensure_ascii=False), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    analyze(args.output, args.destination)
