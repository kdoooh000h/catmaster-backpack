"""Frozen failed-only and unseen comparison; no capability execution."""
import argparse
import json
from pathlib import Path
import time

import conditional_experiment as C
import requirement_coverage as F
import unseen_breadth_experiment as X
import independent_current as I
from conditional_search import SearchIndex
from structured_recall import StructuredIndex
from semantic_recall import OpenLexicalIndex
from semantic_index import load as load_semantic, digest
from experiment import write_once

ARMS=['baseline','hybrid_independent']
HERE=Path(__file__).parent


def sources():
    result=X.sources()
    for name in ['semantic_recall.py','semantic_index.py','independent_current.py',
                 'semantic_experiment.py','semantic_new_requests.json','semantic_new_references.json']:
        p=HERE/name;result[str(p.relative_to(C.ROOT))]=digest(p)
    return result


def cases(previous,rows):
    old=C.E.read(previous/'cases.json');summary=C.E.read(previous/'live/summary.json')
    failed={r['case'] for r in summary['rows'] if r['arm']=='coverage' and not r['omission_safe_pass']}
    result=[{**c,'stratum':'failed'} for c in old if c['id'] in failed]
    if len(result)!=10:raise ValueError('unexpected_failed_set')
    requests=C.E.read(HERE/'semantic_new_requests.json')['cases']
    refs=C.E.read(HERE/'semantic_new_references.json')
    by_ref={c['id']:c for c in refs['cases']};by_id={r['id']:r for r in rows}
    _,bundle=X.verify_frozen(previous);history,_=X.historical_cases(previous,bundle)
    old_needs={c['need'].strip().casefold() for c in history}
    for request in requests:
        if request['need'].strip().casefold() in old_needs:raise ValueError('prior_need_replayed')
        if request['id'] not in by_ref:continue
        case={**request,**by_ref[request['id']],'stratum':'new'}
        for group in X.groups(case):
            if not group or not set(group)<=set(by_id):raise ValueError('unknown_reference')
        if len(case['pending_groups'])!=len(case['later_requirements']):raise ValueError('missing_later_reference')
        import hashlib
        for ref in case['references']:
            if hashlib.sha256(by_id[ref['id']]['description'].encode()).hexdigest()!=ref['description_sha256']:
                raise ValueError('reference_changed')
        result.append(case)
    if len(result)!=15 or len({c['need'] for c in result})!=15:raise ValueError('case_set_changed')
    return result


def coverage(case,recall,arm):
    pool=set(recall['pool']);missing=[i for i,g in enumerate(X.groups(case)) if not pool&set(g)]
    primary=sorted(set(X.anchors(case))-pool)
    return {'missing_groups':missing,'missing_primary':primary,
            'eligible':not missing and not primary and bool(pool) and len(pool)<=(96 if arm=='baseline' else 256)}


def freeze(previous,root,per_kind):
    previous,root=Path(previous).resolve(),Path(root).resolve()
    prior,bundle=X.verify_frozen(previous);rows=C.E.read(bundle/'catalog.json');question=C.E.read(bundle/'question.json')['question']
    selected=cases(previous,rows)
    if C.E.read(root/'new-requests-before-reference.json')!=C.E.read(HERE/'semantic_new_requests.json'):
        raise ValueError('new_requests_changed')
    out=root/'trial';out.mkdir(mode=0o700,exist_ok=False)
    started=time.monotonic();index=load_semantic(bundle/'catalog.json',root/'aligned/model-manifest.json',root/'aligned/index')
    load_seconds=time.monotonic()-started
    lex,structured,open_lex=SearchIndex(rows),StructuredIndex(rows),OpenLexicalIndex(rows)
    audits=[]
    try:
        for case in selected:
            base=F.repair_recall(structured,case['need'],structured.search(case['need'],lex.search(case['need'])))['recall']
            hybrid=index.search(case['need'],open_lex.search(case['need'],base,per_kind=3),per_kind=per_kind)
            recalls={'baseline':base,'hybrid_independent':hybrid};checks={}
            for arm,recall in recalls.items():
                check=coverage(case,recall,arm);checks[arm]=check
                if check['eligible']:
                    if arm=='baseline':spec,_=F.specification('coverage',rows,recall['pool'],question,case['need']);state={'task':case['need']}
                    else:spec,state,_=I.specification(rows,recall['pool'],case['need'])
                    check['payload_chars']=len(json.dumps({'spec':spec,'state':state},ensure_ascii=False))
                check['pool_size']=len(recall['pool'])
            write_once(out/(case['id']+'.recall.json'),{'recalls':recalls,'checks':checks})
            audits.append({'case':case['id'],'stratum':case['stratum'],**checks})
            print(json.dumps(audits[-1],ensure_ascii=False),flush=True)
    finally:lex.close();structured.close();open_lex.close()
    write_once(out/'cases.json',selected);write_once(out/'preflight.json',audits)
    locks={str(p):digest(p) for p in [root/'aligned/index/index.json',root/'aligned/index/vectors.npy',root/'aligned/model-manifest.json',root/'new-requests-before-reference.json',previous/'plan.json',previous/'cases.json',previous/'live/summary.json']}
    plan={'arms':ARMS,'previous':str(previous),'bundle':str(bundle),'final_gate':.7,'per_kind':per_kind,
          'max_calls':30,'max_tokens':400000,'max_seconds':240,'call_timeout_seconds':20,
          'attempts':1,'executable':prior['executable'],'executable_sha256':prior['executable_sha256'],
          'catalog_sha256':digest(bundle/'catalog.json'),'question_sha256':digest(bundle/'question.json'),
          'source_sha256':sources(),'locks':locks,'frozen_sha256':{p.name:digest(p) for p in out.glob('*.json')},
          'index_load_seconds':load_seconds,'lexical_index_seconds':lex.seconds+structured.seconds,
          'acceptance':'Accepted current choice at provider Choice confidence >=0.7, every mandatory reference group and primary anchor retained. No daily promotion unless all scored needs pass.',
          'difference':'baseline = previous alias/coverage selector; candidate = additive open lexical and local multilingual semantic recall plus independent current/partial/other Choices, batched once. Confidence now means suitability rather than unique-best separation; same numerical .7 is not a calibration equivalence.',
          'excluded':C.E.read(HERE/'semantic_new_references.json')['excluded']}
    write_once(out/'plan.json',plan)


def verify(out):
    plan=C.E.read(out/'plan.json');bundle=Path(plan['bundle'])
    if plan['source_sha256']!=sources():raise ValueError('frozen_sources_changed')
    for p,sha in plan['locks'].items():
        if digest(p)!=sha:raise ValueError('external_input_changed')
    for p,sha in plan['frozen_sha256'].items():
        if digest(out/p)!=sha:raise ValueError('frozen_input_changed')
    for p,key in [('catalog.json','catalog_sha256'),('question.json','question_sha256')]:
        if digest(bundle/p)!=plan[key]:raise ValueError('catalog_changed')
    if digest(plan['executable'])!=plan['executable_sha256']:raise ValueError('provider_changed')
    if plan['arms']!=ARMS or plan['final_gate']!=.7 or plan['attempts']!=1:raise ValueError('policy_changed')
    return plan,bundle


def specification(arm,rows,recall,question,need):
    if arm=='baseline':
        spec,mapping=F.specification('coverage',rows,recall['pool'],question,need)
        return spec,{'task':need},mapping
    return I.specification(rows,recall['pool'],need)


def select(arm,rows,recall,question,need,call):
    if arm=='baseline':return F.select('coverage',rows,recall['pool'],question,need,call)
    return I.select(rows,recall['pool'],need,call)


def run(out):
    out=Path(out);plan,bundle=verify(out);live=out/'live';live.mkdir(mode=0o700,exist_ok=False)
    rows=C.E.read(bundle/'catalog.json');question=C.E.read(bundle/'question.json')['question']
    selected=C.E.read(out/'cases.json');began=time.monotonic();spent=0;ordinal=0;results=[];stop='completed'
    provider=C.E.JevHierarchyProvider({'executable':plan['executable'],'timeout_seconds':plan['call_timeout_seconds']},deadline=began+plan['max_seconds'])
    try:
        for n,case in enumerate(selected):
            info=C.E.read(out/(case['id']+'.recall.json'));shift=n%2
            for arm in ARMS[shift:]+ARMS[:shift]:
                recall=info['recalls'][arm];check=coverage(case,recall,arm);offset=len(provider.calls);start=time.monotonic()
                def invoke(stage,spec,state):
                    nonlocal spent,ordinal
                    if stage!='final' or len(provider.calls)!=offset:raise ValueError('one_call_contract')
                    reserve=len(json.dumps({'spec':spec,'state':state},ensure_ascii=False))//2+len(spec['questions'])*80+2500
                    if ordinal>=plan['max_calls'] or spent+reserve>plan['max_tokens']:raise RuntimeError('budget_stop')
                    ordinal+=1;stem=live/(case['id']+'--'+arm)
                    write_once(str(stem)+'.pending.json',{'ordinal':ordinal,'spec':spec,'state':state})
                    before=len(provider.calls)
                    try:raw=provider.noul(spec,state)
                    except Exception as error:
                        write_once(str(stem)+'.error.json',{'error':str(error),'transport':provider.calls[before:]});raise
                    transport=provider.calls[before:]
                    write_once(str(stem)+'.done.json',{'answer':raw,'transport':transport})
                    if len(transport)!=1 or transport[0].get('outcome')!='completed' or not {'input_tokens','output_tokens'}<=transport[0].keys():
                        raise RuntimeError('unknown_usage_or_outcome')
                    spent+=transport[0]['input_tokens']+transport[0]['output_tokens'];return raw
                if check['eligible']:result=select(arm,rows,recall,question,case['need'],invoke)
                else:result={'status':'preflight_failed','choice':None,'confidence':None,'retained_candidates':recall['pool'],
                             'final_pool_size':len(recall['pool']),'traces':[{'stage':'recall','pool':sorted(recall['pool'])}]}
                wall=time.monotonic()-start;transport=provider.calls[offset:];graded=X.grade(case,result)
                item={'case':case['id'],'stratum':case['stratum'],'arm':arm,'kind_stratum':case['kind_stratum'],'language':case['language'],
                      **graded,'strict_pass':graded['omission_safe_pass'] and graded['all_primary_references_retained'],
                      'result':result,'calls':len(transport),'tokens':sum(t['input_tokens']+t['output_tokens'] for t in transport),
                      'retrieval_seconds':recall['seconds'],'dispatch_seconds':wall,'selector_seconds':recall['seconds']+wall,'transport':transport}
                write_once(live/(case['id']+'--'+arm+'.json'),item);results.append(item)
                print(json.dumps({k:v for k,v in item.items() if k not in ['result','transport']}|{'status':result['status'],'confidence':result['confidence']},ensure_ascii=False),flush=True)
    except Exception as error:stop=str(error)
    write_once(live/'summary.json',{'stop':stop,'rows':results,'calls':len(provider.calls),'transport':provider.calls,
                                  'known_tokens':sum(t.get('input_tokens',0)+t.get('output_tokens',0) for t in provider.calls),'wall_seconds':time.monotonic()-began})
    print(json.dumps({'stop':stop,'calls':len(provider.calls),'known_tokens':spent}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('operation',choices=['freeze','run']);p.add_argument('--previous');p.add_argument('--root');p.add_argument('--per-kind',type=int,default=6);p.add_argument('--output')
    a=p.parse_args()
    if a.operation=='freeze':freeze(a.previous,a.root,a.per_kind)
    else:run(a.output)
