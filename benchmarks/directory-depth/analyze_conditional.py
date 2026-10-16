"""Offline reconciliation of a frozen conditional-find run; never sends requests."""
import argparse
import json
from pathlib import Path
import statistics
from conditional_experiment import ARMS, ROOT, digest, final_spec, grade, E, save


def report(output, destination):
    out = Path(output); summary = E.read(out/'live/summary.json'); plan = E.read(out/'plan.json')
    cases = {c['id']: c for c in E.read(Path(plan['bundle'])/'cases.json')}
    if summary['stop'] != 'completed' or len(summary['rows']) != 10: raise ValueError('incomplete_comparison')
    if {(r['case'], r['arm']) for r in summary['rows']} != {(c, a) for c in cases for a in ARMS}:
        raise ValueError('case_arm_coverage_mismatch')
    receipts = []; compact = []; ordinals = []
    bundle = Path(plan['bundle'])
    for name, sha in plan['input_sha256'].items():
        if digest(bundle/name) != sha: raise ValueError('frozen_input_changed')
    for name, sha in plan['recall_sha256'].items():
        if digest(out/name) != sha: raise ValueError('frozen_recall_changed')
    for name, sha in plan['source_sha256'].items():
        if digest(ROOT/name) != sha:
            raise ValueError('frozen_source_changed')
    if digest(plan['executable']) != plan['executable_sha256']: raise ValueError('frozen_executable_changed')
    for row in summary['rows']:
        if any(row[k] != v for k, v in grade(cases[row['case']], row['result']).items()): raise ValueError('grade_changed')
        current = []; final_answer = None
        for path in sorted((out/'live').glob(row['case']+'--'+row['arm']+'--*.done.json')):
            done = E.read(path); pending = E.read(str(path).replace('.done.json', '.pending.json'))
            if pending['state']['task'] != cases[row['case']]['need']: raise ValueError('raw_need_changed')
            ordinals.append(pending['ordinal'])
            if path.name.endswith('--final.done.json'):
                final_answer = done['answer']['answers']['answer']
                confidence, choice = final_answer['confidence'], final_answer['choice']
                actual_status = 'abstain' if confidence < .7 else 'none' if choice == 'none' else 'selected'
                if (row['result']['status'] != actual_status or row['result']['confidence'] != confidence or
                    row['result'].get('choice') != (choice if confidence >= .7 else None)):
                    raise ValueError('final_answer_mismatch')
                if row['arm'] == 'conditional_find':
                    recall = E.read(out/(row['case']+'.recall.json'))['recall']
                    if pending['spec'] != final_spec(E.read(bundle/'catalog.json'), recall['pool'], E.read(bundle/'question.json')['question']):
                        raise ValueError('final_payload_changed')
                    if set(row['result']['traces'][0]['pool']) != set(recall['pool']):
                        raise ValueError('recalled_pool_changed')
            current += done['transport']
        if len(current) != row['calls'] or sum(r['input_tokens']+r['output_tokens'] for r in current) != row['tokens']:
            raise ValueError('usage_mismatch')
        if row['result']['status'] == 'selected' and row['result']['confidence'] < .7: raise ValueError('final_gate_changed')
        receipts += current
        compact.append({k: v for k, v in row.items() if k != 'result'} |
                       {k: row['result'].get(k) for k in ['status', 'choice', 'confidence', 'final_pool_size']} |
                       {'raw_final_choice': final_answer['choice'] if final_answer else None,
                        'top_final_probabilities': sorted(final_answer.get('probabilities', {}).items(), key=lambda item: -item[1])[:5] if final_answer else []})
    if len(receipts) != summary['calls'] or any(r['outcome'] != 'completed' for r in receipts): raise ValueError('receipt_mismatch')
    if sum(r['input_tokens']+r['output_tokens'] for r in receipts) != summary['known_tokens']: raise ValueError('total_usage_mismatch')
    missing = [p.name for p in (out/'live').glob('*.pending.json') if not Path(str(p).replace('.pending.json', '.done.json')).exists()]
    if missing: raise ValueError('unknown_pending_send')
    if sorted(ordinals) != list(range(1, summary['calls']+1)): raise ValueError('ordinal_mismatch')
    aggregate = {}
    for arm in ARMS:
        values = [r for r in compact if r['arm'] == arm]
        aggregate[arm] = {'cases': len(values), 'correct_current': sum(r['correct_current'] for r in values),
                          'all_required_retained': sum(r['all_required_retained'] for r in values),
                          'omission_safe_passes': sum(r['omission_safe_pass'] for r in values),
                          **{'mean_'+k: statistics.mean(r[k] for r in values) for k in
                             ['jev_cli_seconds', 'local_search_seconds', 'route_wall_seconds', 'tokens', 'calls', 'final_pool_size']}}
    baseline, candidate = aggregate['adaptive'], aggregate['conditional_find']
    result = {'version': 1, 'catalog_count': plan['catalog_count'], 'final_gate': .7,
              'preflight': E.read(out/'preflight.json'), 'aggregates': aggregate, 'rows': compact,
              'calls': summary['calls'], 'known_tokens': summary['known_tokens'],
              'index_seconds': plan['index_seconds'], 'limits': plan['limitations'],
              'change_percent': {key: 100*(candidate['mean_'+key]/baseline['mean_'+key]-1)
                                 for key in ['tokens', 'calls', 'jev_cli_seconds', 'route_wall_seconds']},
              'semantic_scope': 'Strict original-reference selection and intermediate retention on five known development needs; no business-task execution or proven capability equivalence.',
              'sources': {'public_enabled_source_candidates': plan['catalog_count']-376, 'historical_control_skills': 376,
                          'skill': 682, 'whole_plugin': 628, 'mcp': 44015, 'new_market_reads': 0},
              'verdict': 'known_five_pass_only' if aggregate['conditional_find']['omission_safe_passes'] == 5 else 'do_not_promote',
              'no_daily_install_or_market_execution': True}
    save(destination, result)
    print(json.dumps({'aggregates': aggregate, 'calls': summary['calls'], 'tokens': summary['known_tokens']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    report(args.output, args.destination)
