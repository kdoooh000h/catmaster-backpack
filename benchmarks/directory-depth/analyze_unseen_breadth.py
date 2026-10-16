"""Audit new-request breadth, predeclared alternatives and every skipped case."""
import argparse
import json
from pathlib import Path
import statistics

import conditional_experiment as C
import requirement_coverage as F
from final_contrast import decode
import unseen_breadth_experiment as X
from experiment import write_once


def aggregate(rows):
    measured=[r for r in rows if r['calls']]
    metrics=['tokens','input_tokens','output_tokens','jev_cli_seconds',
             'current_dispatch_wall_seconds','retrieval_seconds','selector_seconds',
             'final_pool_size','payload_chars']
    return {'cases':len(rows),'measured_cases':len(measured),
            **{k:sum(r[k] for r in rows) for k in ['correct_current','all_required_retained','omission_safe_pass','all_primary_references_retained','strict_anchor_pass','calls','tokens']},
            'measured_means':{k:statistics.mean(r[k] for r in measured) for k in metrics} if measured else None}


def report(output,destination):
    out=Path(output);plan,bundle=X.verify_frozen(out);summary=C.E.read(out/'live/summary.json')
    cases={c['id']:c for c in C.E.read(out/'cases.json')};catalog=C.E.read(bundle/'catalog.json')
    question=C.E.read(bundle/'question.json')['question'];by_id={r['id']:r for r in catalog}
    expected={(c,a) for c in cases for a in X.ARMS}
    if (summary['stop']!='completed' or len(summary['rows'])!=len(expected)
            or {(r['case'],r['arm']) for r in summary['rows']}!=expected):
        raise ValueError('incomplete_comparison')
    history,_=X.historical_cases(Path(plan['previous']),bundle)
    checked_cases=X.validate_cases(C.E.read(X.REQUESTS)['cases'],C.E.read(X.REFERENCES)['cases'],history,catalog)
    if list(cases.values())!=checked_cases:raise ValueError('frozen_cases_or_references_changed')
    if C.E.read(out.parent/'requests-before-reference-inspection.json')!=C.E.read(X.REQUESTS):
        raise ValueError('requests_changed_after_reference_inspection')
    receipts={};compact=[];coverage={}
    for row in summary['rows']:
        case=cases[row['case']];result=row['result']
        info=C.E.read(out/(case['id']+'.recall.json'));recall=info['recall']
        if not set(info['original_recall']['pool'])<=set(recall['pool']):
            raise ValueError('original_candidate_lost')
        required=X.groups(case);pool=set(recall['pool'])
        missing=[i for i,g in enumerate(required) if not set(g)&pool]
        eligible=not missing and recall['status']=='recalled' and 0<len(recall['pool'])<=96
        if info['missing_groups']!=missing or info['eligible_for_live']!=eligible:
            raise ValueError('preflight_mismatch')
        if result['retained_candidates']!=recall['pool'] or result['traces']!=[{'stage':'conditional_recall','pool':sorted(recall['pool'])}]:
            raise ValueError('retained_pool_changed')
        if any(row[k]!=v for k,v in X.grade(case,result).items()):raise ValueError('grade_changed')
        coverage[case['id']]={'required':len(required),'retained':len(required)-len(missing),
                             'pending_required':len(case['pending_groups']),
                             'pending_retained':sum(bool(set(g)&pool) for g in case['pending_groups']),
                             'missing_group_indices':missing,'primary_required':len(X.anchors(case)),
                             'primary_retained':sum(i in pool for i in X.anchors(case)),
                             'missing_primary_ids':sorted(set(X.anchors(case))-pool),
                             'facets':recall.get('request_facets'), 'supplemental_query_count':len(recall.get('queries',[]))}
        item={k:v for k,v in row.items() if k not in {'result','transport','first_lost'}} | {
            k:result.get(k) for k in ['status','choice','raw_choice','confidence','final_pool_size']} | {
            'acceptable_current_ids':case['acceptable_current_ids'],'pending_groups':case['pending_groups'],
            'primary_current_id':case['primary_current_id'],'primary_pending_ids':case['primary_pending_ids'],
            'selected_kind':by_id.get(result.get('choice'),{}).get('kind'),
            'failure_stage':'recall' if missing else 'none' if row['omission_safe_pass'] else 'final',
            'input_tokens':0,'output_tokens':0,'payload_chars':None,'top_choice_probabilities':[]}
        stem=case['id']+'--'+row['arm']+'--final'
        if eligible:
            pending=C.E.read(out/'live'/(stem+'.pending.json'));done=C.E.read(out/'live'/(stem+'.done.json'))
            spec,mapping=F.specification(row['arm'],catalog,recall['pool'],question,case['need'])
            if pending['state']!={'task':case['need']} or pending['spec']!=spec:
                raise ValueError('raw_need_or_spec_changed')
            if list(mapping.values())!=list(F.specification('compact',catalog,recall['pool'],question,case['need'])[1].values()):
                raise ValueError('candidate_identity_or_order_changed')
            payload_chars=len(json.dumps({'spec':spec,'state':pending['state']},ensure_ascii=False))
            if payload_chars!=info['payload_chars'][row['arm']]:raise ValueError('payload_size_mismatch')
            # Re-run the local validator on the saved answer only: no provider.
            checked=F.select(row['arm'],catalog,recall['pool'],question,case['need'],lambda *a:done['answer'])
            if result!=checked:raise ValueError('mapped_result_mismatch')
            transport=done['transport']
            if len(transport)!=1 or row['calls']!=1 or transport!=row['transport']:
                raise ValueError('one_call_contract_broken')
            t=transport[0]
            if (t.get('outcome')!='completed' or not {'input_tokens','output_tokens'}<=t.keys()
                    or row['tokens']!=t['input_tokens']+t['output_tokens'] or row['jev_cli_seconds']!=t['seconds']):
                raise ValueError('usage_mismatch')
            if pending['ordinal'] in receipts:raise ValueError('duplicate_ordinal')
            receipts[pending['ordinal']]=t
            answer=decode(done['answer'],mapping)['answers']['answer']
            item.update(input_tokens=t['input_tokens'],output_tokens=t['output_tokens'],payload_chars=payload_chars,
                        top_choice_probabilities=[{'id':i,'name':by_id.get(i,{}).get('name'),
                                                   'kind':by_id.get(i,{}).get('kind'),'probability':p}
                            for i,p in sorted(answer.get('probabilities',{}).items(),key=lambda pair:-pair[1])[:5]])
        elif (row['calls'] or row['tokens'] or row['transport'] or result['status']!='preflight_failed'
              or list((out/'live').glob(stem+'.*'))):raise ValueError('ineligible_case_dispatched')
        compact.append(item)
    ordered=[receipts[i] for i in sorted(receipts)]
    if (sorted(receipts)!=list(range(1,summary['calls']+1)) or ordered!=summary['transport']
            or sum(t['input_tokens']+t['output_tokens'] for t in ordered)!=summary['known_tokens']):
        raise ValueError('total_receipt_mismatch')
    pending=list((out/'live').glob('*.pending.json'));done=list((out/'live').glob('*.done.json'))
    if len(pending)!=len(ordered) or len(done)!=len(ordered) or list((out/'live').glob('*.error.json')):
        raise ValueError('unknown_or_extra_call')
    totals={a:aggregate([r for r in compact if r['arm']==a]) for a in X.ARMS}
    strata={field:{str(value):{a:aggregate([r for r in compact if r['arm']==a and r[field]==value]) for a in X.ARMS}
                   for value in sorted({r[field] for r in compact})} for field in ['kind_stratum','language','multitask']}
    candidate=totals['coverage']['measured_means']
    changes={a:{k:100*(candidate[k]/v-1) for k,v in totals[a]['measured_means'].items() if v}
             for a in ['compact']}
    output={'version':1,'catalog_count':len(catalog),'final_gate':.7,'difference':plan['difference'],
            'aggregates':totals,'strata':strata,'rows':compact,'shared_reference_coverage':coverage,
            'calls':summary['calls'],'known_tokens':summary['known_tokens'],'index_seconds':plan['index_seconds'],
            'coverage_change_percent':changes,'source_sha256':plan['source_sha256'],
            'catalog_sha256':plan['catalog_sha256'],'cases_sha256':plan['frozen_sha256']['cases.json'],
            'preflight':C.E.read(out/'preflight.json'),
            'limits':[plan['limits'],plan['cost_basis'],
                      'All twelve new cases remain in accuracy denominators. Cost means cover only the same four live pairs; eight known recall failures receive no model calls.',
                      'Strict frozen-reference coverage does not prove every equivalent capability survives or that other candidates are incapable.',
                      'Selectors are unchanged from the two-failure repair. Both arms share fresh retrieval; only the previously defined evidence/coverage final treatment differs.',
                      'Skill/plugin/MCP strata refer to primary targets, not forced selection kinds. No MCP reaches live selection because all four fail reference coverage. No capability is installed or executed.'],
            'verdict':'bounded_all_pass' if totals['coverage']['omission_safe_pass']==len(cases) and totals['coverage']['all_primary_references_retained']==len(cases) else 'do_not_promote'}
    write_once(destination,output)
    print(json.dumps({'aggregates':totals,'coverage_change_percent':changes,'calls':summary['calls'],
                      'known_tokens':summary['known_tokens'],'verdict':output['verdict']},ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--destination',required=True)
    args=p.parse_args();report(args.output,args.destination)
