"""One old failure plus three new needs; fixed recall, three one-call finals."""
import argparse
import json
from pathlib import Path
import time

import conditional_experiment as C
from conditional_search import SearchIndex
import structured_recall as S
import structured_recall_experiment as P
import final_contrast as F
from experiment import write_once

FAILED = ['new_slides_then_word_handout']
FIXTURES = Path(__file__).with_name('final_contrast_cases.json')


def sources():
    result = P.sources()
    for p in [Path(__file__), Path(F.__file__), FIXTURES]:
        result[str(p.relative_to(C.ROOT))] = C.digest(p)
    return result


def freeze(previous, output):
    previous, out = Path(previous).resolve(), Path(output).resolve()
    prior, bundle = P.verify_frozen(previous)
    summary = C.E.read(previous/'live/summary.json')
    failed = {r['case'] for r in summary['rows'] if r['arm']=='structured_current' and not r['omission_safe_pass']}
    if summary['stop'] != 'completed' or failed != set(FAILED):
        raise ValueError('previous_failed_scope_changed')
    old = {c['id']:c for c in C.E.read(previous/'cases.json')}
    earlier = C.E.read(bundle/'cases.json') + C.E.read(Path(prior['previous'])/'cases.json')
    additions = C.E.read(FIXTURES)['cases']
    seen_ids = set(old) | {c['id'] for c in earlier}
    seen_needs = {c['need'] for c in list(old.values())+earlier}
    if (len(additions)!=3 or len({c['id'] for c in additions})!=3
            or len({c['need'] for c in additions})!=3
            or any(c['id'] in seen_ids or c['need'] in seen_needs for c in additions)):
        raise ValueError('new_cases_not_distinct')
    rows = C.E.read(bundle/'catalog.json'); by_id = {r['id']:r for r in rows}
    question = C.E.read(bundle/'question.json')['question']
    for case in additions:
        targets = case['expected_ids']+case['pending_ids']
        if (len(case['expected_ids'])!=1 or not case['pending_ids']
                or len(set(targets))!=len(targets) or not set(targets)<=set(by_id)):
            raise ValueError('invalid_reference_targets')
        if any(i.casefold() in case['need'].casefold() for i in targets):
            raise ValueError('named_capability_in_need')
    if {by_id[c['expected_ids'][0]]['kind'] for c in additions} != {'skill','plugin','mcp'}:
        raise ValueError('new_reference_kind_coverage_changed')
    cases = [old[i] for i in FAILED]+additions
    lexical, structured = SearchIndex(rows), S.StructuredIndex(rows)
    out.mkdir(mode=0o700, exist_ok=False); audits = []
    try:
        for case in cases:
            if case['id'] in FAILED:
                recall = C.E.read(previous/(case['id']+'.recall.json'))['recalls']['structured_current']
                basis = 'unchanged_previous_pool_and_historical_query_time'
            else:
                recall = structured.search(case['need'], lexical.search(case['need']))
                basis = 'new_shared_unchanged_structured_recall'
            missing = sorted(set(case['expected_ids']+case['pending_ids'])-set(recall['pool']))
            valid = recall['status']=='recalled' and 0<len(recall['pool'])<=96 and not missing
            audit = {'case':case['id'],'missing_required':missing,'eligible_for_live':valid,
                     'pool_size':len(recall['pool']), 'payload_chars':{}}
            if valid:
                for arm in F.ARMS:
                    spec, mapping = F.specification(arm, rows, recall['pool'], question)
                    if list(mapping.values()) != list(F.specification('current_full',rows,recall['pool'],question)[1]):
                        raise ValueError('candidate_identity_or_order_changed')
                    audit['payload_chars'][arm] = len(json.dumps({'spec':spec,'state':{'task':case['need']}},ensure_ascii=False))
            write_once(out/(case['id']+'.recall.json'), {'case':case['id'],'recall':recall,'basis':basis,**audit})
            audits.append(audit)
    finally:
        lexical.close(); structured.close()
    write_once(out/'cases.json', cases)
    write_once(out/'preflight.json', {'rows':audits,'eligible':sum(a['eligible_for_live'] for a in audits)})
    plan = {'version':1,'arms':F.ARMS,'previous':str(previous),'catalog_bundle':str(bundle),
            'original_failed':FAILED,'case_order':[c['id'] for c in cases],'final_gate':.7,
            'max_calls':12,'max_tokens':140000,'max_seconds':120,'call_timeout_seconds':20,'attempts':1,
            'executable':prior['executable'],'executable_sha256':prior['executable_sha256'],
            'source_sha256':sources(),'catalog_sha256':C.digest(bundle/'catalog.json'),
            'question_sha256':C.digest(bundle/'question.json'),
            'previous_summary_sha256':C.digest(previous/'live/summary.json'),
            'frozen_sha256':{p.name:C.digest(p) for p in out.glob('*.json')},
            'index_seconds':{'lexical':lexical.seconds,'additional_structured':structured.seconds},
            'difference':'Same raw need, recall, canonical option order and 0.7 gate. current_full is unchanged; typed_full changes instructions and adds kind/mode labels; typed_compact additionally shortens reversible option IDs and generic leading boilerplate.',
            'acceptance':'All four compact-arm needs choose the frozen current reference at >=0.7 and retain every required later reference; compare tokens and time with both other arms.',
            'preflight_policy':'Missing-reference or over-wide cases remain failures for every arm; zero live sends for those cases. No fixture or retrieval tuning after inspection.',
            'cost_basis':'Actual Jev input/output usage and dispatch wall time; warm selector adds shared retrieval time. Old query time is historical; index builds separate. Root Agent costs and backend revision unobservable.',
            'limits':'One old failure and three author-written combinations, one three-arm pass; no blind generalization claim, readiness check or task execution. No retries or daily changes.'}
    write_once(out/'plan.json', plan)
    print(json.dumps({'preflight':audits,'index_seconds':plan['index_seconds'],'max_calls':12,'max_tokens':140000},ensure_ascii=False),flush=True)


def verify_frozen(out):
    plan = C.E.read(out/'plan.json'); bundle = Path(plan['catalog_bundle'])
    if plan['source_sha256'] != sources(): raise ValueError('frozen_sources_changed')
    for name, sha in plan['frozen_sha256'].items():
        if C.digest(out/name)!=sha: raise ValueError('frozen_inputs_changed')
    for name,key in [('catalog.json','catalog_sha256'),('question.json','question_sha256')]:
        if C.digest(bundle/name)!=plan[key]: raise ValueError('catalog_or_question_changed')
    if C.digest(plan['executable'])!=plan['executable_sha256']: raise ValueError('provider_changed')
    if C.digest(Path(plan['previous'])/'live/summary.json')!=plan['previous_summary_sha256']:
        raise ValueError('previous_results_changed')
    if plan['final_gate']!=.7 or plan['arms']!=F.ARMS or plan['attempts']!=1:
        raise ValueError('frozen_policy_changed')
    return plan,bundle


def run(output):
    out=Path(output); plan,bundle=verify_frozen(out)
    live=out/'live'; live.mkdir(mode=0o700,exist_ok=False)
    rows=C.E.read(bundle/'catalog.json'); question=C.E.read(bundle/'question.json')['question']
    cases=C.E.read(out/'cases.json'); began=time.monotonic(); spent=0; ordinal=0; completed=[]; stop='completed'
    provider=C.E.JevHierarchyProvider({'executable':plan['executable'],'timeout_seconds':plan['call_timeout_seconds']},deadline=began+plan['max_seconds'])
    try:
        for number,case in enumerate(cases):
            info=C.E.read(out/(case['id']+'.recall.json')); recall=info['recall']
            shift=number%len(F.ARMS)
            for arm in F.ARMS[shift:]+F.ARMS[:shift]:
                offset=len(provider.calls); start=time.monotonic()
                def invoke(stage,spec,state):
                    nonlocal spent,ordinal
                    if stage!='final' or len(provider.calls)!=offset: raise RuntimeError('one_call_contract')
                    reserve=len(json.dumps({'spec':spec,'state':state},ensure_ascii=False))//2+len(spec['questions']['answer']['criteria'])*24+2000
                    if ordinal>=plan['max_calls'] or spent+reserve>plan['max_tokens']: raise RuntimeError('budget_stop')
                    stem=live/(case['id']+'--'+arm+'--final'); ordinal+=1
                    write_once(str(stem)+'.pending.json',{'spec':spec,'state':state,'ordinal':ordinal})
                    before=len(provider.calls)
                    try: raw=provider.noul(spec,state)
                    except Exception as error:
                        write_once(str(stem)+'.error.json',{'error':str(error),'transport':provider.calls[before:]}); raise
                    transport=provider.calls[before:]
                    write_once(str(stem)+'.done.json',{'answer':raw,'transport':transport})
                    if (len(transport)!=1 or transport[0].get('outcome')!='completed'
                            or not {'input_tokens','output_tokens'}<=transport[0].keys()):
                        raise RuntimeError('unknown_usage_or_outcome')
                    spent+=transport[0]['input_tokens']+transport[0]['output_tokens']; return raw
                if info['eligible_for_live']:
                    result=F.select(arm,rows,recall['pool'],question,case['need'],invoke)
                else:
                    result={'status':'preflight_failed','choice':None,'confidence':None,
                            'retained_candidates':recall['pool'],'final_pool_size':len(recall['pool']),
                            'traces':[{'stage':'conditional_recall','pool':sorted(recall['pool'])}]}
                wall=time.monotonic()-start; transport=provider.calls[offset:]
                item={'case':case['id'],'arm':arm,'stratum':'old_failure' if case['id'] in FAILED else 'new',
                      'result':result,**C.grade(case,result),'calls':len(transport),
                      'tokens':sum(r['input_tokens']+r['output_tokens'] for r in transport),
                      'jev_cli_seconds':sum(r['seconds'] for r in transport),'current_dispatch_wall_seconds':wall,
                      'retrieval_seconds':recall['seconds'],'retrieval_basis':info['basis'],
                      'selector_seconds':wall+recall['seconds'],'transport':transport}
                write_once(live/(case['id']+'--'+arm+'.json'),item); completed.append(item)
                print(json.dumps({k:v for k,v in item.items() if k not in {'result','transport','first_lost'}} | {'confidence':result['confidence'],'status':result['status']},ensure_ascii=False),flush=True)
    except Exception as error: stop=str(error)
    write_once(live/'summary.json',{'stop':stop,'rows':completed,'calls':len(provider.calls),'transport':provider.calls,
                                  'known_tokens':sum(r.get('input_tokens',0)+r.get('output_tokens',0) for r in provider.calls),
                                  'wall_seconds':time.monotonic()-began})
    print(json.dumps({'stop':stop,'calls':len(provider.calls),'known_tokens':spent}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('operation',choices=['freeze','run'])
    parser.add_argument('--previous'); parser.add_argument('--output',required=True); args=parser.parse_args()
    if args.operation=='freeze': freeze(args.previous,args.output)
    else: run(args.output)
