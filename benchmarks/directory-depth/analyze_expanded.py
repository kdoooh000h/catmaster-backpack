"""Expanded-case report with explicit failures and actual-use boundaries."""
import argparse
from pathlib import Path

from analyze_adaptive_cost import analyze, metrics
from experiment import read, write_once


def summarize(bundle, live, output):
    bundle, live = Path(bundle), Path(live)
    intermediate = live.parent / 'aggregation-intermediate.json'
    analyze(bundle, live, intermediate)
    result = read(intermediate)
    rows = read(live / 'summary.json')['rows']
    nodes = read(bundle / 'nodes.json')
    cases = {c['id']: c for c in read(bundle / 'cases.json')}
    passing = [key for key in cases if len([r for r in rows if r['case'] == key]) == 2
               and all(r['omission_safe_pass'] for r in rows if r['case'] == key)]
    result['scope'] = 'New public-directory requests plus selected pinned Skill script/guidance use; no installed gateway or MCP acceptance.'
    result['candidate_eligible'] = all(r['omission_safe_pass'] for r in rows if r['arm'] == 'compact_global') and len(rows) == 2 * len(cases)
    result['both_pass_cases'] = passing
    result['both_pass_metrics'] = {arm: metrics([r for r in rows if r['case'] in passing and r['arm'] == arm])
                                   for arm in ('adaptive', 'compact_global')}
    result['failures'] = []
    for row in rows:
        if row['omission_safe_pass']:
            continue
        case = cases[row['case']]
        index = row['first_omission_stage']
        scores = []
        if index:
            trace = row['result']['traces'][index - 1]
            for key, answer in trace['answers'].items():
                if set(case['expected_ids'] + case['pending_ids']).intersection(nodes[key]['members']):
                    scores.append({'node': key, 'depth': nodes[key]['depth'], 'score': answer['noul']})
        result['failures'].append({'case': row['case'], 'arm': row['arm'],
            'expected_current': case['expected_ids'], 'required_later': case['pending_ids'],
            'first_omission_stage': index, 'scores_at_omission': scores,
            'status': row['result']['status'], 'selected': row['result'].get('choice'),
            'confidence': row['result'].get('confidence')})
    result['actual_use'] = read(live.parent / 'use-result.json')
    result['limitations'] = [
        'One frozen pass on 14 new requests; tests authored by the same evaluator with public metadata available. Not an independent blind evaluation.',
        'Both semantic failures and successes remain in the denominator. Whole-set lower cost includes early failures and is not a quality-equivalent improvement.',
        'Both-pass cost subset is posthoc descriptive evidence, not a replacement benchmark.',
        'Research task selected deepread in both arms; it may help, but required research-summarizer was excluded, so the predeclared omission rule fails.',
        'No selector parameters, thresholds or descriptions were changed after the new cases ran; no retry of model decisions.',
        'Three selected Skill artifacts were checked locally; API example flags needed correction from observed argparse errors. Failed data-quality selection was not bypassed.',
        'Skill sources came from the pinned public benchmark archive after selection, not the installed Backpack acquisition gateway. Market installation, plugin/MCP execution and native-agent end-to-end costs are not tested.',
        'Jev tokens are reported; root task reasoning time/tokens and monetary cost remain unobservable.',
        'No daily catalog, lifecycle, native cache or installation promotion.']
    write_once(output, result)
    print({'by_arm': result['by_arm'], 'candidate_eligible': result['candidate_eligible'],
           'actual_use_completed': result['actual_use']['completed_artifacts'],
           'both_pass': result['both_pass_metrics'], 'failures': result['failures']})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--live', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    summarize(args.bundle, args.live, args.output)
