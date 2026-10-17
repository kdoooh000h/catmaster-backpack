"""Frozen paired recall comparison; both arms use the same current-step final."""
import argparse
import json
from pathlib import Path
import time

import conditional_experiment as C
import conditional_current as F
import conditional_current_experiment as P
from conditional_search import SearchIndex
import structured_recall as S
from experiment import write_once

ARMS = ['lexical_current', 'structured_current']
FAILED = ['new_word_now_spreadsheet_later', 'new_spreadsheet_now_wiki_later']
FIXTURES = Path(__file__).with_name('structured_recall_cases.json')


def sources():
    result = P.sources()
    for path in [Path(__file__), Path(S.__file__), FIXTURES]:
        result[str(path.relative_to(C.ROOT))] = C.digest(path)
    return result


def freeze(previous, output):
    previous, out = Path(previous).resolve(), Path(output).resolve()
    prior_plan, bundle = P.verify_frozen(previous)
    summary = C.E.read(previous/'live/summary.json')
    if summary['stop'] != 'completed': raise ValueError('previous_run_incomplete')
    failed = {r['case'] for r in summary['rows'] if r['arm']=='conditional_current' and not r['omission_safe_pass']}
    if failed != set(FAILED): raise ValueError('failed_scope_changed')
    old = {c['id']:c for c in C.E.read(previous/'cases.json')}
    additions = C.E.read(FIXTURES)['cases']
    earlier = C.E.read(bundle/'cases.json')
    seen_ids = set(old)|{c['id'] for c in earlier}
    seen_needs = {c['need'] for c in list(old.values())+earlier}
    if (len(additions)!=4 or len({c['id'] for c in additions})!=4
            or len({c['need'] for c in additions})!=4
            or any(c['id'] in seen_ids or c['need'] in seen_needs for c in additions)):
        raise ValueError('new_cases_not_distinct')
    rows = C.E.read(bundle/'catalog.json'); by_id = {r['id']:r for r in rows}
    for case in additions:
        targets = case['expected_ids']+case['pending_ids']
        if (len(case['expected_ids'])!=1 or not case['pending_ids']
                or len(set(targets))!=len(targets) or not set(targets)<=set(by_id)):
            raise ValueError('invalid_reference_targets')
        if any(i.casefold() in case['need'].casefold() for i in targets):
            raise ValueError('named_capability_in_need')
    cases = [old[i] for i in FAILED]+additions
    # Neither index accepts evaluation labels or changes catalog metadata.
    lexical = SearchIndex(rows); structured = S.StructuredIndex(rows)
    out.mkdir(mode=0o700, exist_ok=False); audits = []
    try:
        for case in cases:
            if case['id'] in FAILED:
                baseline = C.E.read(previous/(case['id']+'.recall.json'))['recall']
                basis = 'unchanged_prior_recall_historical_query_time'
            else:
                baseline = lexical.search(case['need']); basis = 'fresh_shared_lexical_recall'
            candidate = structured.search(case['need'], baseline)
            recalls = dict(zip(ARMS, [baseline, candidate]))
            coverage = {arm: sorted(set(case['expected_ids']+case['pending_ids'])-set(r['pool'])) for arm,r in recalls.items()}
            valid = all(r['status']=='recalled' and 0<len(r['pool'])<=96 for r in recalls.values())
            if not set(baseline['pool'])<=set(candidate['pool']): raise ValueError('baseline_candidate_lost')
            value = {'case':case['id'], 'need':case['need'], 'basis':basis, 'recalls':recalls,
                     'missing_required':coverage, 'valid_for_paired_dispatch':valid}
            write_once(out/(case['id']+'.recall.json'),value)
            audits.append({'case':case['id'],'missing_required':coverage,'valid_for_paired_dispatch':valid,
                           'pool_sizes':{a:len(r['pool']) for a,r in recalls.items()},
                           'added':len(candidate['pool'])-len(baseline['pool']),
                           'augmentation_seconds':candidate['augmentation_seconds']})
    finally: lexical.close(); structured.close()
    write_once(out/'cases.json', cases)
    write_once(out/'preflight.json', {'rows':audits,'ready':all(r['valid_for_paired_dispatch'] for r in audits),
                                     'candidate_reference_coverage':all(not r['missing_required'][ARMS[1]] for r in audits)})
    plan = {'version':1,'arms':ARMS,'previous':str(previous),'catalog_bundle':str(bundle),
            'original_failed':FAILED,'case_order':[c['id'] for c in cases],'final_gate':.7,
            'max_calls':12,'max_tokens':140000,'max_seconds':120,'call_timeout_seconds':20,'attempts':1,
            'executable':prior_plan['executable'],'executable_sha256':prior_plan['executable_sha256'],
            'source_sha256':sources(), 'catalog_sha256':C.digest(bundle/'catalog.json'),
            'question_sha256':C.digest(bundle/'question.json'),
            'frozen_sha256':{p.name:C.digest(p) for p in out.glob('*.json')},
            'index_seconds':{'lexical':lexical.seconds,'additional_structured':structured.seconds},
            'difference':'Only recall changes. Both use the identical current-step final, raw need, complete original descriptions, catalog ordering and 0.7 gate.',
            'acceptance':'All six candidate needs choose their declared current reference at >=0.7 and retain every required later reference.',
            'preflight_policy':'Require bounded nonempty pools and complete candidate reference coverage before live. Known-incomplete baseline pools are sent once for matched actual cost/answer measurement; their omissions remain failures.',
            'cost_basis':'Actual Jev usage and fresh final-dispatch wall times. Warm selector adds stored query time; original two baseline query times are historical. Index builds separate. Root Agent costs and backend model revision unobservable.',
            'limits':'Two known failures plus four author-written combinations, one paired pass; not blind population accuracy or task execution. Additive recall has no general completeness proof. No daily changes or retries.'}
    write_once(out/'plan.json',plan)
    print(json.dumps({'preflight':audits,'index_seconds':plan['index_seconds'],'max_calls':12,'max_tokens':140000},ensure_ascii=False),flush=True)


def verify_frozen(out):
    plan=C.E.read(out/'plan.json');bundle=Path(plan['catalog_bundle'])
    if plan['source_sha256']!=sources():raise ValueError('frozen_sources_changed')
    for name,sha in plan['frozen_sha256'].items():
        if C.digest(out/name)!=sha:raise ValueError('frozen_inputs_changed')
    for name,key in [('catalog.json','catalog_sha256'),('question.json','question_sha256')]:
        if C.digest(bundle/name)!=plan[key]:raise ValueError('catalog_or_question_changed')
    if C.digest(plan['executable'])!=plan['executable_sha256']:raise ValueError('provider_changed')
    if plan['final_gate']!=.7 or plan['arms']!=ARMS:raise ValueError('frozen_policy_changed')
    return plan,bundle


def run(output):
    out=Path(output);plan,bundle=verify_frozen(out);preflight=C.E.read(out/'preflight.json')
    if not preflight['ready'] or not preflight['candidate_reference_coverage']:
        raise ValueError('candidate_preflight_failed_no_live_sends')
    live=out/'live';live.mkdir(mode=0o700,exist_ok=False)
    rows=C.E.read(bundle/'catalog.json');question=C.E.read(bundle/'question.json')['question']
    cases=C.E.read(out/'cases.json');began=time.monotonic();spent=0;ordinal=0;completed=[];stop='completed'
    provider=C.E.JevHierarchyProvider({'executable':plan['executable'],'timeout_seconds':20},deadline=began+plan['max_seconds'])
    try:
        for number,case in enumerate(cases):
            recall_info=C.E.read(out/(case['id']+'.recall.json'))
            for arm in (ARMS if number%2 else list(reversed(ARMS))):
                recall=recall_info['recalls'][arm];offset=len(provider.calls);start=time.monotonic()
                def invoke(stage,spec,state):
                    nonlocal spent,ordinal
                    if stage!='final' or len(provider.calls)!=offset:raise RuntimeError('one_call_contract')
                    reserve=len(json.dumps({'spec':spec,'state':state},ensure_ascii=False))//2+len(spec['questions']['answer']['criteria'])*24+2000
                    if ordinal>=plan['max_calls'] or spent+reserve>plan['max_tokens']:raise RuntimeError('budget_stop')
                    stem=live/(case['id']+'--'+arm+'--final');ordinal+=1
                    write_once(str(stem)+'.pending.json',{'spec':spec,'state':state,'ordinal':ordinal})
                    before=len(provider.calls)
                    try:raw=provider.noul(spec,state)
                    except Exception as error:
                        write_once(str(stem)+'.error.json',{'error':str(error),'transport':provider.calls[before:]});raise
                    transport=provider.calls[before:]
                    write_once(str(stem)+'.done.json',{'answer':raw,'transport':transport})
                    if (len(transport)!=1 or transport[0].get('outcome')!='completed'
                            or not {'input_tokens','output_tokens'}<=transport[0].keys()):
                        raise RuntimeError('unknown_usage_or_outcome')
                    spent+=transport[0]['input_tokens']+transport[0]['output_tokens'];return raw
                result=F.select('conditional_current',rows,recall['pool'],question,case['need'],invoke)
                wall=time.monotonic()-start;transport=provider.calls[offset:]
                item={'case':case['id'],'arm':arm,'stratum':'old_failure' if case['id'] in FAILED else 'new',
                      'result':result,**C.grade(case,result),'calls':len(transport),
                      'tokens':sum(r['input_tokens']+r['output_tokens'] for r in transport),
                      'jev_cli_seconds':sum(r['seconds'] for r in transport),'current_dispatch_wall_seconds':wall,
                      'retrieval_seconds':recall['seconds'],'retrieval_basis':recall_info['basis'],
                      'selector_seconds':wall+recall['seconds'],'transport':transport}
                write_once(live/(case['id']+'--'+arm+'.json'),item);completed.append(item)
                print(json.dumps({k:v for k,v in item.items() if k not in {'result','transport','first_lost'}},ensure_ascii=False),flush=True)
    except Exception as error:stop=str(error)
    write_once(live/'summary.json',{'stop':stop,'rows':completed,'calls':len(provider.calls),'transport':provider.calls,
                                  'known_tokens':sum(r.get('input_tokens',0)+r.get('output_tokens',0) for r in provider.calls),
                                  'wall_seconds':time.monotonic()-began})
    print(json.dumps({'stop':stop,'calls':len(provider.calls),'known_tokens':spent}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['freeze','run'])
    parser.add_argument('--previous');parser.add_argument('--output',required=True);args=parser.parse_args()
    if args.operation=='freeze':freeze(args.previous,args.output)
    else:run(args.output)
