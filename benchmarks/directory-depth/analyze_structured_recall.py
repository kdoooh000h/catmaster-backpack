"""Read-only reconciliation of the frozen structured-recall paired trial."""
import argparse
import json
from pathlib import Path
import statistics

import conditional_current as F
import conditional_experiment as C
import structured_recall_experiment as X
from experiment import write_once


def aggregate(rows):
    return {'cases':len(rows),
            **{k:sum(r[k] for r in rows) for k in ['correct_current','all_required_retained','omission_safe_pass','calls','tokens']},
            'means':{k:statistics.mean(r[k] for r in rows) for k in
                     ['calls','tokens','input_tokens','output_tokens','jev_cli_seconds','current_dispatch_wall_seconds',
                      'retrieval_seconds','selector_seconds','final_pool_size']},
            'median_selector_seconds':statistics.median(r['selector_seconds'] for r in rows)}


def report(output,destination):
    out=Path(output);plan,bundle=X.verify_frozen(out);summary=C.E.read(out/'live/summary.json')
    cases={c['id']:c for c in C.E.read(out/'cases.json')};catalog=C.E.read(bundle/'catalog.json')
    question=C.E.read(bundle/'question.json')['question'];by_id={r['id']:r for r in catalog}
    expected={(c,a) for c in cases for a in X.ARMS}
    if (summary['stop']!='completed' or len(summary['rows'])!=len(expected)
            or {(r['case'],r['arm']) for r in summary['rows']}!=expected):raise ValueError('incomplete_comparison')
    previous=Path(plan['previous']);old={c['id']:c for c in C.E.read(previous/'cases.json')}
    if set(old)&set(cases)!=set(X.FAILED):raise ValueError('passed_case_replayed')
    if any(cases[i]!=old[i] for i in X.FAILED):raise ValueError('original_failed_need_changed')
    receipts={};compact=[];coverage={};payloads={}
    for row in summary['rows']:
        case=cases[row['case']];result=row['result']
        info=C.E.read(out/(case['id']+'.recall.json'));recall=info['recalls'][row['arm']]
        base=info['recalls'][X.ARMS[0]];candidate=info['recalls'][X.ARMS[1]]
        if not set(base['pool'])<=set(candidate['pool']):raise ValueError('baseline_candidate_lost')
        if case['id'] in X.FAILED and base!=C.E.read(previous/(case['id']+'.recall.json'))['recall']:
            raise ValueError('previous_recall_changed')
        if result['retained_candidates']!=recall['pool'] or result['traces']!=[{'stage':'conditional_recall','pool':sorted(recall['pool'])}]:
            raise ValueError('retained_pool_changed')
        if any(row[k]!=v for k,v in C.grade(case,result).items()):raise ValueError('grade_changed')
        stem=case['id']+'--'+row['arm']+'--final'
        pending=C.E.read(out/'live'/(stem+'.pending.json'));done=C.E.read(out/'live'/(stem+'.done.json'))
        if pending['state']!={'task':case['need']}:raise ValueError('raw_need_changed')
        if pending['spec']!=F.specification('conditional_current',catalog,recall['pool'],question):
            raise ValueError('final_spec_changed')
        payloads[(case['id'],row['arm'])]=pending
        answer=done['answer']['answers']['answer'];score,choice=answer['confidence'],answer['choice']
        status='abstain' if score<.7 else 'none' if choice=='none' else 'selected'
        if (result['status']!=status or result['confidence']!=score or result['raw_choice']!=choice
                or result['choice']!=(choice if score>=.7 else None)):raise ValueError('final_answer_mismatch')
        transport=done['transport']
        if len(transport)!=1 or row['calls']!=1 or transport!=row['transport']:raise ValueError('one_call_contract_broken')
        t=transport[0]
        if (t.get('outcome')!='completed' or not {'input_tokens','output_tokens'}<=t.keys()
                or row['tokens']!=t['input_tokens']+t['output_tokens'] or row['jev_cli_seconds']!=t['seconds']):
            raise ValueError('usage_mismatch')
        if pending['ordinal'] in receipts:raise ValueError('duplicate_ordinal')
        receipts[pending['ordinal']]=t
        required=case['expected_ids']+case['pending_ids']
        coverage.setdefault(case['id'],{})[row['arm']]={
            'required':len(required),'retained':sum(i in recall['pool'] for i in required),
            'pending_required':len(case['pending_ids']),'pending_retained':sum(i in recall['pool'] for i in case['pending_ids']),
            'missing_ids':sorted(set(required)-set(recall['pool']))}
        compact.append({k:v for k,v in row.items() if k not in {'result','transport','first_lost'}} |
                       {k:result.get(k) for k in ['status','choice','raw_choice','confidence','final_pool_size']} |
                       {'input_tokens':t['input_tokens'],'output_tokens':t['output_tokens'],
                        'expected_ids':case['expected_ids'],'pending_ids':case['pending_ids'],
                        'top_choice_probabilities':[{'id':i,'name':by_id.get(i,{}).get('name'),'kind':by_id.get(i,{}).get('kind'),'probability':p}
                           for i,p in sorted(answer.get('probabilities',{}).items(),key=lambda item:-item[1])[:5]]})
    for case in cases:
        left,right=[payloads[(case,a)] for a in X.ARMS]
        lq,rq=[p['spec']['questions']['answer'] for p in [left,right]]
        if lq['instructions']!=rq['instructions'] or left['state']!=right['state']:
            raise ValueError('more_than_recall_changed')
        if any(rq['criteria'].get(k)!=v for k,v in lq['criteria'].items()):
            raise ValueError('original_description_changed')
    ordered=[receipts[i] for i in sorted(receipts)]
    if (sorted(receipts)!=list(range(1,summary['calls']+1)) or ordered!=summary['transport']
            or sum(t['input_tokens']+t['output_tokens'] for t in ordered)!=summary['known_tokens']):
        raise ValueError('total_receipt_mismatch')
    pending=list((out/'live').glob('*.pending.json'));done=list((out/'live').glob('*.done.json'))
    if (len(pending)!=len(ordered) or len(done)!=len(ordered) or list((out/'live').glob('*.error.json'))
            or any(not Path(str(p).replace('.pending.json','.done.json')).exists() for p in pending)):
        raise ValueError('unknown_or_extra_call')
    totals={a:aggregate([r for r in compact if r['arm']==a]) for a in X.ARMS}
    strata={g:{a:aggregate([r for r in compact if r['arm']==a and r['stratum']==g]) for a in X.ARMS} for g in ['old_failure','new']}
    baseline,candidate=[totals[a]['means'] for a in X.ARMS]
    result={'version':1,'catalog_count':len(catalog),'final_gate':.7,'difference':plan['difference'],
            'aggregates':totals,'strata':strata,'rows':compact,'reference_coverage':coverage,
            'calls':summary['calls'],'known_tokens':summary['known_tokens'],'index_seconds':plan['index_seconds'],
            'change_percent':{k:100*(candidate[k]/baseline[k]-1) for k in baseline if baseline[k]},
            'source_sha256':plan['source_sha256'],'catalog_sha256':plan['catalog_sha256'],
            'frozen_cases_sha256':plan['frozen_sha256']['cases.json'],
            'preflight':C.E.read(out/'preflight.json'),
            'limits':[plan['limits'],plan['cost_basis'],
                      'Strict frozen reference coverage, not proof that recalled alternatives are incapable or that every equivalent capability survives.',
                      'The complete recalled pool remains available; no semantic later-only label or runtime execution is claimed.',
                      'This combined treatment includes facets, generic-name anchors and per-kind supplementary slots; individual-factor effects are not isolated.',
                      'Four public publisher Skills and two historical control Skills are current references. No public plugin/MCP task is executed.'],
            'verdict':'bounded_six_pass_only' if totals[X.ARMS[1]]['omission_safe_pass']==6 else 'do_not_promote'}
    write_once(destination,result)
    print(json.dumps({'aggregates':totals,'change_percent':result['change_percent'],'calls':result['calls'],'known_tokens':result['known_tokens']},ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--destination',required=True)
    args=parser.parse_args();report(args.output,args.destination)
