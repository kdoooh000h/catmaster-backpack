"""Frozen one-call final-question A/B, excluding already-passing needs.

Only the final question lead differs. Original failed-case recall is reused
byte-for-byte. New-case recall is computed once and shared by both arms. A new
case that fails offline reference coverage stays a failure without live sends.
"""
import argparse
import json
from pathlib import Path
import time

import conditional_experiment as C
import conditional_current as F
from conditional_search import SearchIndex
from experiment import write_once

FAILED = ['finance_packages_then_wiki', 'signals_then_finance_and_culture',
          'cancel_finance_keep_discovery_jira']
FIXTURES = Path(__file__).with_name('conditional_current_cases.json')


def sources():
    result = C.sources()
    for path in [Path(__file__), Path(F.__file__), FIXTURES,
                 Path(__file__).with_name('current_step.py')]:
        result[str(path.relative_to(C.ROOT))] = C.digest(path)
    return result


def cases_for_run(prior, results, additions, rows):
    failed = {r['case'] for r in results if r['arm'] == 'conditional_find' and not r['omission_safe_pass']}
    if failed != set(FAILED):
        raise ValueError('failed_scope_changed')
    old = {c['id']: c for c in prior}
    if len(additions) != 4 or len({c['id'] for c in additions}) != 4:
        raise ValueError('new_case_count_changed')
    by_id = {r['id']: r for r in rows}
    for case in additions:
        if case['id'] in old or case['need'] in {c['need'] for c in prior}:
            raise ValueError('completed_case_reuse')
        targets = case['expected_ids'] + case['pending_ids']
        if (len(case['expected_ids']) != 1 or not case['pending_ids']
                or len(set(targets)) != len(targets) or not set(targets) <= set(by_id)):
            raise ValueError('invalid_reference_targets')
        # Product/file-format names are ordinary requests, not named Skills.
        if any(i.casefold() in case['need'].casefold() for i in targets if '-' in i):
            raise ValueError('named_capability_in_need')
    return [old[i] for i in FAILED] + additions


def freeze(previous, output):
    previous, out = Path(previous).resolve(), Path(output).resolve()
    plan = C.E.read(previous/'plan.json'); bundle = Path(plan['bundle'])
    summary = C.E.read(previous/'live/summary.json')
    if summary['stop'] != 'completed': raise ValueError('previous_run_incomplete')
    for name, sha in plan['input_sha256'].items():
        if C.digest(bundle/name) != sha: raise ValueError('previous_inputs_changed')
    for name, sha in plan['source_sha256'].items():
        if C.digest(C.ROOT/name) != sha: raise ValueError('previous_source_changed')
    for name, sha in plan['recall_sha256'].items():
        if C.digest(previous/name) != sha: raise ValueError('previous_recall_changed')
    if C.digest(plan['executable']) != plan['executable_sha256']: raise ValueError('provider_changed')
    rows = C.E.read(bundle/'catalog.json')
    index = SearchIndex(rows)
    additions = C.E.read(FIXTURES)['cases']
    cases = cases_for_run(C.E.read(bundle/'cases.json'), summary['rows'], additions, rows)
    out.mkdir(mode=0o700, exist_ok=False)
    by_id = {r['id']: r for r in rows}; audits = []
    try:
        for case in cases:
            if case['id'] in FAILED:
                old = C.E.read(previous/(case['id']+'.recall.json'))
                if old['need'] != case['need']: raise ValueError('old_need_changed')
                recall = old['recall']; basis = 'reused_unchanged_original_recall'
            else:
                recall = index.search(case['need']); basis = 'new_shared_recall'
                case['gold_sources'] = [{k: by_id[i].get(k) for k in ['id', 'name', 'description', 'source', 'provenance']}
                                       for i in case['expected_ids']+case['pending_ids']]
            missing = sorted(set(case['expected_ids']+case['pending_ids'])-set(recall['pool']))
            eligible = not missing and recall['status'] == 'recalled'
            value = {'case': case['id'], 'recall': recall, 'basis': basis,
                     'missing_required': missing, 'eligible_for_live': eligible}
            write_once(out/(case['id']+'.recall.json'), value)
            audits.append({k: v for k, v in value.items() if k != 'recall'} |
                          {'pool_size': len(recall['pool']), 'retrieval_seconds': recall['seconds']})
    finally:
        index.close()
    write_once(out/'cases.json', cases)
    new_plan = {'version': 1, 'arms': F.ARMS, 'catalog_bundle': str(bundle),
                'previous': str(previous), 'original_failed': FAILED, 'new_cases': 4, 'cases': len(cases),
                'case_order': [c['id'] for c in cases], 'final_gate': F.FINAL_GATE,
                'max_calls': 14, 'max_tokens': 120000, 'max_seconds': 90, 'call_timeout_seconds': 20,
                'attempts': 1, 'executable': plan['executable'], 'executable_sha256': plan['executable_sha256'],
                'new_index_seconds': index.seconds, 'source_sha256': sources(),
                'catalog_sha256': C.digest(bundle/'catalog.json'), 'question_sha256': C.digest(bundle/'question.json'),
                'frozen_sha256': {p.name: C.digest(p) for p in out.glob('*.json')},
                'old_result_sha256': C.digest(previous/'live/summary.json'),
                'difference': 'Replace only final instruction lead with the existing current_step.CURRENT_LEAD. Same raw need, full criteria, option order and pool.',
                'acceptance': 'All seven candidate needs select the original current reference at confidence >=0.7 and retain every required later reference. Failed preflight cases count as failures.',
                'preflight_failure_policy': 'Do not send a known incomplete/over-wide recall pool. Record failure for both arms and continue independent eligible cases.',
                'cost_basis': 'Warm selector wall time includes retrieval and final local assembly; one-off index separate. Reused query duration is historical and explicitly marked. Main Agent and backend revision unobservable.',
                'limits': 'Three known failed needs plus four author-written new combinations, one paired pass; not independent blind validation or business execution. No threshold reduction or retries.'}
    write_once(out/'plan.json', new_plan)
    write_once(out/'preflight.json', {'rows': audits, 'eligible': sum(r['eligible_for_live'] for r in audits),
                                    'cases': len(cases), 'new_index_seconds': index.seconds})
    print(json.dumps({'preflight': audits, 'max_calls': 14, 'max_tokens': 120000}, ensure_ascii=False), flush=True)


def verify_frozen(out):
    plan = C.E.read(out/'plan.json'); bundle = Path(plan['catalog_bundle'])
    if plan['source_sha256'] != sources(): raise ValueError('frozen_sources_changed')
    for name, sha in plan['frozen_sha256'].items():
        if C.digest(out/name) != sha: raise ValueError('frozen_input_changed')
    if C.digest(bundle/'catalog.json') != plan['catalog_sha256']: raise ValueError('catalog_changed')
    if C.digest(bundle/'question.json') != plan['question_sha256']: raise ValueError('question_changed')
    if C.digest(plan['executable']) != plan['executable_sha256']: raise ValueError('executable_changed')
    if plan['final_gate'] != .7 or plan['arms'] != F.ARMS: raise ValueError('frozen_policy_changed')
    return plan, bundle


def run(output):
    out = Path(output); plan, bundle = verify_frozen(out)
    live = out/'live'; live.mkdir(mode=0o700, exist_ok=False)
    rows, question = C.E.read(bundle/'catalog.json'), C.E.read(bundle/'question.json')['question']
    cases = C.E.read(out/'cases.json'); completed = []; spent = 0; ordinals = 0
    started = time.monotonic()
    provider = C.E.JevHierarchyProvider({'executable': plan['executable'], 'timeout_seconds': plan['call_timeout_seconds']},
                                       deadline=started+plan['max_seconds'])
    stop = 'completed'
    try:
        for number, case in enumerate(cases):
            recalled = C.E.read(out/(case['id']+'.recall.json')); recall = recalled['recall']
            for arm in (F.ARMS if number % 2 else list(reversed(F.ARMS))):
                offset = len(provider.calls); began = time.monotonic()
                def invoke(stage, spec, state):
                    nonlocal spent, ordinals
                    if len(provider.calls) != offset: raise RuntimeError('one_call_limit')
                    if stage != 'final': raise RuntimeError('unexpected_stage')
                    reserve = len(json.dumps({'spec': spec, 'state': state}, ensure_ascii=False))//2 + len(spec['questions']['answer']['criteria'])*24 + 2000
                    if ordinals >= plan['max_calls'] or spent+reserve > plan['max_tokens']:
                        raise RuntimeError('budget_stop')
                    path = live/(case['id']+'--'+arm+'--final')
                    # Exclusive creation and a non-resumable run directory make
                    # interrupted/unknown sends observation-only, never replay.
                    ordinals += 1
                    write_once(str(path)+'.pending.json', {'spec': spec, 'state': state, 'ordinal': ordinals})
                    before = len(provider.calls)
                    try:
                        raw = provider.noul(spec, state)
                    except Exception as error:
                        write_once(str(path)+'.error.json', {'error': str(error), 'transport': provider.calls[before:]})
                        raise
                    current = provider.calls[before:]
                    write_once(str(path)+'.done.json', {'answer': raw, 'transport': current})
                    if (len(current) != 1 or current[0].get('outcome') != 'completed'
                            or not {'input_tokens', 'output_tokens'} <= current[0].keys()):
                        raise RuntimeError('unknown_usage_or_outcome')
                    spent += current[0]['input_tokens']+current[0]['output_tokens']
                    return raw
                if recalled['eligible_for_live']:
                    result = F.select(arm, rows, recall['pool'], question, case['need'], invoke)
                else:
                    result = {'status': 'preflight_failed', 'choice': None, 'confidence': None,
                              'retained_candidates': recall['pool'], 'final_pool_size': len(recall['pool']),
                              'traces': [{'stage': 'conditional_recall', 'pool': sorted(recall['pool'])}]}
                transport = provider.calls[offset:]
                item = {'case': case['id'], 'arm': arm, 'stratum': 'old_failure' if case['id'] in FAILED else 'new',
                        'result': result, **C.grade(case, result), 'live_called': bool(transport),
                        'calls': len(transport), 'tokens': sum(r['input_tokens']+r['output_tokens'] for r in transport),
                        'jev_cli_seconds': sum(r['seconds'] for r in transport),
                        'current_dispatch_wall_seconds': time.monotonic()-began,
                        'retrieval_seconds': recall['seconds'], 'retrieval_basis': recalled['basis'],
                        'selector_seconds': time.monotonic()-began+recall['seconds'], 'transport': transport}
                write_once(live/(case['id']+'--'+arm+'.json'), item); completed.append(item)
                print(json.dumps({k: v for k, v in item.items() if k not in {'result', 'transport', 'first_lost'}}, ensure_ascii=False), flush=True)
    except Exception as error:
        stop = str(error)
    write_once(live/'summary.json', {'stop': stop, 'rows': completed, 'calls': len(provider.calls),
                                   'known_tokens': sum(r.get('input_tokens', 0)+r.get('output_tokens', 0) for r in provider.calls),
                                   'transport': provider.calls, 'wall_seconds': time.monotonic()-started})
    print(json.dumps({'stop': stop, 'calls': len(provider.calls), 'known_tokens': spent}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('operation', choices=['freeze', 'run'])
    parser.add_argument('--previous'); parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.operation == 'freeze': freeze(args.previous, args.output)
    else: run(args.output)
