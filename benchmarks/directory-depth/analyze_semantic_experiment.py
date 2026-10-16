"""Reconcile every frozen pair and receipt without any new model calls."""
import argparse
import json
from pathlib import Path
import statistics

import semantic_experiment as X
from experiment import write_once


def aggregate(rows):
    measured=[r for r in rows if r['calls']]
    return {'cases':len(rows),**{k:sum(r[k] for r in rows) for k in
            ['strict_pass','omission_safe_pass','all_required_retained','all_primary_references_retained','calls','tokens']},
            'measured_cases':len(measured),'measured_means':{k:statistics.mean(r[k] for r in measured)
            for k in ['tokens','input_tokens','output_tokens','retrieval_seconds','dispatch_seconds','selector_seconds','final_pool_size']} if measured else None}


def report(out,destination):
    out=Path(out);plan,bundle=X.verify(out);summary=X.C.E.read(out/'live/summary.json')
    cases={c['id']:c for c in X.C.E.read(out/'cases.json')};rows=X.C.E.read(bundle/'catalog.json');by={r['id']:r for r in rows}
    question=X.C.E.read(bundle/'question.json')['question']
    if list(cases.values())!=X.cases(Path(plan['previous']),rows):raise ValueError('case_set_changed')
    expected={(c,a) for c in cases for a in X.ARMS}
    if summary['stop']!='completed' or {(r['case'],r['arm']) for r in summary['rows']}!=expected or len(summary['rows'])!=len(expected):
        raise ValueError('incomplete_comparison')
    records=[];receipts={};coverage={}
    for row in summary['rows']:
        case=cases[row['case']];arm=row['arm'];result=row['result'];info=X.C.E.read(out/(case['id']+'.recall.json'))
        recall=info['recalls'][arm];check=X.coverage(case,recall,arm);pool=set(recall['pool'])
        if not set(info['recalls']['baseline']['pool'])<=set(info['recalls']['hybrid_independent']['pool']):raise ValueError('baseline_candidate_lost')
        if result['retained_candidates']!=recall['pool'] or any(set(t['pool'])!=pool for t in result['traces']):raise ValueError('pool_changed')
        grade=X.X.grade(case,result)
        if any(row[k]!=v for k,v in grade.items()) or row['strict_pass']!=(grade['omission_safe_pass'] and grade['all_primary_references_retained']):raise ValueError('grade_changed')
        cov={'required_groups':len(X.X.groups(case)),'retained_groups':sum(bool(set(g)&pool) for g in X.X.groups(case)),
             'primary_required':len(X.X.anchors(case)),'primary_retained':sum(i in pool for i in X.X.anchors(case)),
             'later_required':len(case['pending_groups']),'later_retained':sum(bool(set(g)&pool) for g in case['pending_groups']),
             'later_primary_retained':sum(i in pool for i in case['primary_pending_ids']),**check,'pool_size':len(pool)}
        coverage.setdefault(case['id'],{})[arm]=cov
        item={k:v for k,v in row.items() if k not in ['result','transport']}|{
              k:result.get(k) for k in ['status','choice','confidence','final_pool_size']}
        item.update(input_tokens=0,output_tokens=0,selected_name=by.get(result.get('choice'),{}).get('name'),
                    selected_kind=by.get(result.get('choice'),{}).get('kind'),accepted_candidates=[])
        stem=out/'live'/(case['id']+'--'+arm)
        if check['eligible']:
            pending=X.C.E.read(str(stem)+'.pending.json');done=X.C.E.read(str(stem)+'.done.json')
            spec,state,mapping=X.specification(arm,rows,recall,question,case['need'])
            if pending['spec']!=spec or pending['state']!=state or state['task']!=case['need']:raise ValueError('payload_changed')
            checked=X.select(arm,rows,recall,question,case['need'],lambda *args:done['answer'])
            if checked!=result:raise ValueError('saved_response_validation_changed')
            transport=done['transport']
            if len(transport)!=1 or transport!=row['transport'] or row['calls']!=1:raise ValueError('call_contract_broken')
            t=transport[0]
            if t.get('outcome')!='completed' or row['tokens']!=t['input_tokens']+t['output_tokens']:raise ValueError('usage_mismatch')
            if pending['ordinal'] in receipts:raise ValueError('duplicate_ordinal')
            receipts[pending['ordinal']]=t
            item.update(input_tokens=t['input_tokens'],output_tokens=t['output_tokens'],
                        payload_chars=len(json.dumps({'spec':spec,'state':state},ensure_ascii=False)),questions=len(spec['questions']))
            item['accepted_candidates']=[{'id':i,'name':by[i]['name'],'kind':by[i]['kind'],**result['candidate_judgments'][i]}
                                         for i in result.get('accepted_candidates',[])]
            if result.get('choice') and not row['strict_pass']:
                item['unlisted_selection_description']=by[result['choice']]['description']
                item['posthoc_note']='Outside frozen accepted set; descriptive plausibility is not retroactive benchmark credit or execution proof.'
        elif (row['calls'] or row['tokens'] or row['transport'] or result['status']!='preflight_failed'
              or Path(str(stem)+'.pending.json').exists()):raise ValueError('ineligible_send')
        records.append(item)
    if sorted(receipts)!=list(range(1,summary['calls']+1)) or [receipts[i] for i in sorted(receipts)]!=summary['transport']:raise ValueError('receipt_order_mismatch')
    if sum(r['tokens'] for r in records)!=summary['known_tokens']:raise ValueError('token_total_mismatch')
    if len(list((out/'live').glob('*.pending.json')))!=len(receipts) or len(list((out/'live').glob('*.done.json')))!=len(receipts) or list((out/'live').glob('*.error.json')):raise ValueError('extra_or_unknown_call')
    aggregates={a:aggregate([r for r in records if r['arm']==a]) for a in X.ARMS}
    paired=set.intersection(*[{r['case'] for r in records if r['arm']==a and r['calls']} for a in X.ARMS])
    pairs={a:aggregate([r for r in records if r['arm']==a and r['case'] in paired]) for a in X.ARMS}
    changes={k:100*(pairs['hybrid_independent']['measured_means'][k]/v-1)
             for k,v in pairs['baseline']['measured_means'].items() if v}
    strata={field:{str(value):{a:aggregate([r for r in records if r['arm']==a and r[field]==value]) for a in X.ARMS}
                   for value in sorted({r[field] for r in records})} for field in ['stratum','kind_stratum','language']}
    local_index=X.C.E.read(out.parent/'aligned/index/index.json')
    result={'version':1,'final_gate':.7,'catalog_count':len(rows),'aggregates':aggregates,'strata':strata,
            'paired_cases':sorted(paired),'paired':pairs,'paired_change_percent':changes,'reference_coverage':coverage,
            'rows':records,'calls':summary['calls'],'tokens':summary['known_tokens'],'source_sha256':plan['source_sha256'],
            'catalog_sha256':plan['catalog_sha256'],'cases_sha256':plan['frozen_sha256']['cases.json'],
            'model':local_index['model'],'model_files_sha256':local_index['model_files'],
            'index_build_seconds':local_index['seconds'],'index_load_seconds':plan['index_load_seconds'],
            'index_dimensions':local_index['dimensions'],'index_vectors_sha256':local_index['vectors_sha256'],
            'per_kind':plan['per_kind'],'excluded_before_testing':plan['excluded'],
            'limits':[plan['difference'],'All 15 cases remain in pass denominators; costs are separately reported for the same three live pairs and for all calls.',
                      'Five new scored requests; a sixth authored request was withheld before recall because no defensible full-scope positive reference was found.',
                      'Frozen alternatives are incomplete. Three selected unlisted alternatives appear relevant on post-hoc metadata review but receive no score change.',
                      'Historical control Skills remain explicit. Metadata selection is not installation, execution or readiness. No private or daily runtime changes.',
                      'Independent suitability confidence is not uniqueness confidence; the unchanged numeric .7 does not establish equivalent calibration.',
                      'Main-Agent usage, monetary cost and Jev backend revision are unobservable. Local-model setup and index construction are separate from warm selector timing.'],
            'verdict':'do_not_promote'}
    write_once(destination,result)
    print(json.dumps({'aggregates':aggregates,'paired':pairs,'paired_change_percent':changes,'calls':summary['calls'],'tokens':summary['known_tokens']},ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--destination',required=True)
    a=p.parse_args();report(a.output,a.destination)
