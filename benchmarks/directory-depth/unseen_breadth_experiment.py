"""New-request breadth check with frozen selectors and predeclared alternatives."""
import argparse
from collections import Counter
import json
from pathlib import Path
import time

import conditional_experiment as C
from conditional_search import SearchIndex
import structured_recall as S
import requirement_coverage as F
import requirement_coverage_experiment as P
from experiment import write_once

ARMS=['compact','coverage']
REQUESTS=Path(__file__).with_name('unseen_breadth_requests.json')
REFERENCES=Path(__file__).with_name('unseen_breadth_references.json')


def sources():
    result=P.sources()
    for path in [Path(__file__),REQUESTS,REFERENCES]:result[str(path.relative_to(C.ROOT))]=C.digest(path)
    return result


def groups(case):return [case['acceptable_current_ids']]+case['pending_groups']
def anchors(case):return [case['primary_current_id']]+case['primary_pending_ids']


def grade(case,result):
    traces=result.get('traces',[])
    covered=bool(traces) and all(all(set(g)&set(t['pool']) for g in groups(case)) for t in traces)
    anchor_kept=bool(traces) and all(set(anchors(case))<=set(t['pool']) for t in traces)
    current=result['status']=='selected' and result.get('choice') in case['acceptable_current_ids']
    return {'correct_current':bool(current),'all_required_retained':bool(covered),
            'omission_safe_pass':bool(current and covered),'all_primary_references_retained':anchor_kept,
            'strict_anchor_pass':bool(result['status']=='selected' and result.get('choice')==case['primary_current_id'] and anchor_kept)}


def historical_cases(previous,bundle):
    paths=set();cursor=Path(previous)
    while True:
        path=cursor/'cases.json'
        if path.exists():paths.add(path)
        plan=C.E.read(cursor/'plan.json')
        if 'previous' not in plan:break
        cursor=Path(plan['previous'])
    paths.add(bundle/'cases.json')
    paths.update(p for p in Path(__file__).parent.glob('*cases*.json') if not p.name.startswith('unseen_'))
    cases=[]
    def collect(value):
        if isinstance(value,dict):
            if isinstance(value.get('id'),str) and isinstance(value.get('need'),str):cases.append(value)
            for v in value.values():collect(v)
        elif isinstance(value,list):
            for v in value:collect(v)
    for path in sorted(paths):collect(C.E.read(path))
    return cases,{str(p):C.digest(p) for p in paths}


def validate_cases(requests,references,history,rows):
    if len(requests)!=12 or len(references)!=12:raise ValueError('case_count_changed')
    by_ref={r['id']:r for r in references};by_id={r['id']:r for r in rows}
    if len(by_ref)!=12 or len({c['id'] for c in requests})!=12 or len({c['need'] for c in requests})!=12:
        raise ValueError('duplicate_case')
    if Counter(c['kind_stratum'] for c in requests)!={'skill':4,'plugin':4,'mcp':4}:
        raise ValueError('kind_coverage_changed')
    if Counter(c['language'] for c in requests)!={'zh':4,'synonym':4,'mixed':4}:
        raise ValueError('language_coverage_changed')
    old_ids={c['id'] for c in history};old_needs={c['need'].strip().casefold() for c in history};cases=[]
    for request in requests:
        if request['id'] in old_ids or request['need'].strip().casefold() in old_needs:raise ValueError('prior_case_replayed')
        case={**request,**by_ref[request['id']]}
        if len(case['pending_groups'])!=len(case['later_requirements']):raise ValueError('later_reference_mismatch')
        if case['primary_current_id'] not in case['acceptable_current_ids'] or len(case['primary_pending_ids'])!=len(case['pending_groups']):raise ValueError('invalid_primary')
        if any(p not in g for p,g in zip(case['primary_pending_ids'],case['pending_groups'])):raise ValueError('invalid_later_primary')
        ids=set()
        for group in groups(case):
            if not group or len(set(group))!=len(group) or not set(group)<=set(by_id):raise ValueError('invalid_reference_group')
            ids.update(group)
        if by_id[case['primary_current_id']]['kind']!=case['kind_stratum']:raise ValueError('primary_kind_mismatch')
        if any(i.casefold() in case['need'].casefold() for i in ids if '-' in i):raise ValueError('named_capability_in_need')
        if {r['id'] for r in case['references']}!=ids:raise ValueError('reference_evidence_missing')
        for r in case['references']:
            import hashlib
            if hashlib.sha256(by_id[r['id']]['description'].encode()).hexdigest()!=r['description_sha256']:raise ValueError('reference_metadata_changed')
        cases.append(case)
    return cases


def freeze(previous,output):
    previous,out=Path(previous).resolve(),Path(output).resolve();prior,bundle=P.verify_frozen(previous)
    if C.E.read(previous/'live/summary.json')['stop']!='completed':raise ValueError('prior_incomplete')
    rows=C.E.read(bundle/'catalog.json');question=C.E.read(bundle/'question.json')['question']
    history,history_hashes=historical_cases(previous,bundle)
    cases=validate_cases(C.E.read(REQUESTS)['cases'],C.E.read(REFERENCES)['cases'],history,rows)
    lexical,structured=SearchIndex(rows),S.StructuredIndex(rows)
    out.mkdir(mode=0o700,exist_ok=False);audits=[]
    try:
        for case in cases:
            original=structured.search(case['need'],lexical.search(case['need']))
            repaired=F.repair_recall(structured,case['need'],original);recall=repaired['recall'];pool=set(recall['pool'])
            missing=[i for i,g in enumerate(groups(case)) if not pool&set(g)]
            missing_primary=sorted(set(anchors(case))-pool)
            eligible=not missing and recall['status']=='recalled' and 0<len(pool)<=96
            audit={'case':case['id'],'kind_stratum':case['kind_stratum'],'language':case['language'],
                   'missing_groups':missing,'missing_primary_ids':missing_primary,'eligible_for_live':eligible,
                   'pool_size':len(pool),'original_pool_size':len(original['pool']),'payload_chars':{}}
            if eligible:
                for arm in ARMS:
                    spec,mapping=F.specification(arm,rows,recall['pool'],question,case['need'])
                    audit['payload_chars'][arm]=len(json.dumps({'spec':spec,'state':{'task':case['need']}},ensure_ascii=False))
            write_once(out/(case['id']+'.recall.json'),{**repaired,**audit,'original_recall':original,'basis':'fresh_shared_structured_recall_and_alias_repair'})
            audits.append(audit)
    finally:lexical.close();structured.close()
    write_once(out/'cases.json',cases);write_once(out/'preflight.json',{'rows':audits,'eligible':sum(a['eligible_for_live'] for a in audits),'cases':len(cases)})
    plan={'version':1,'arms':ARMS,'previous':str(previous),'catalog_bundle':str(bundle),'case_order':[c['id'] for c in cases],
          'final_gate':.7,'max_calls':24,'max_tokens':200000,'max_seconds':120,'call_timeout_seconds':20,'attempts':1,
          'executable':prior['executable'],'executable_sha256':prior['executable_sha256'],'source_sha256':sources(),
          'catalog_sha256':C.digest(bundle/'catalog.json'),'question_sha256':C.digest(bundle/'question.json'),
          'history_sha256':history_hashes,'frozen_sha256':{p.name:C.digest(p) for p in out.glob('*.json')},
          'index_seconds':{'lexical':lexical.seconds,'structured':structured.seconds},
          'difference':'Frozen selectors; same fresh alias-repaired recall, complete raw requests, compact descriptions, option order/IDs and 0.7 gate. Only existing literal evidence and coverage instruction differ.',
          'acceptance':'All twelve candidate needs select a predeclared acceptable current reference at >=0.7, preserve every mandatory later reference group and retain every primary anchor. All offline failures remain in denominators.',
          'preflight_policy':'No live send for missing reference groups or over-wide/empty pools. Record the failure; do not tune requests, references, selectors or recall after observing it.',
          'cost_basis':'Paired live-case means only, plus all-case call totals. All retrieval and final times fresh; index builds separate. Main Agent cost, money and backend revision unobservable.',
          'limits':'Twelve author-written new requests fixed before reference inspection; not an independent blind holdout or proof of all equivalent capabilities. Public metadata selection only; no real capability execution or daily changes. Current strata use primary references; accepted alternatives can cross kinds.'}
    write_once(out/'plan.json',plan)
    print(json.dumps({'preflight':audits,'eligible':sum(a['eligible_for_live'] for a in audits),'index_seconds':plan['index_seconds'],'max_calls':24,'max_tokens':200000},ensure_ascii=False),flush=True)


def verify_frozen(out):
    plan=C.E.read(out/'plan.json');bundle=Path(plan['catalog_bundle'])
    if plan['source_sha256']!=sources():raise ValueError('frozen_sources_changed')
    for name,sha in plan['frozen_sha256'].items():
        if C.digest(out/name)!=sha:raise ValueError('frozen_input_changed')
    for name,sha in plan['history_sha256'].items():
        if C.digest(name)!=sha:raise ValueError('history_changed')
    for name,key in [('catalog.json','catalog_sha256'),('question.json','question_sha256')]:
        if C.digest(bundle/name)!=plan[key]:raise ValueError('catalog_or_question_changed')
    if C.digest(plan['executable'])!=plan['executable_sha256']:raise ValueError('provider_changed')
    if plan['arms']!=ARMS or plan['final_gate']!=.7 or plan['attempts']!=1:raise ValueError('policy_changed')
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
            shift=number%len(ARMS)
            for arm in ARMS[shift:]+ARMS[:shift]:
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
                item={'case':case['id'],'arm':arm,'stratum':'new','kind_stratum':case['kind_stratum'],'language':case['language'],'multitask':bool(case['pending_groups']),
                      'result':result,**grade(case,result),'calls':len(transport),
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
