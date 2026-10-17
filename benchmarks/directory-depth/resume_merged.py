"""Finish the original five-need record without replaying completed requests.

Same input, code lock, stage IDs and output directory. An existing pending send
without a known result is observation-only and stops this continuation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import merged_experiment as E
from source_preflight import save, key


def completed_stage(path,spec,state):
    pending=Path(str(path)+'.pending.json');done=Path(str(path)+'.done.json')
    if done.exists():
        prior=E.read(pending)
        if prior!={'spec':spec,'state':state}:raise ValueError('saved_request_changed')
        value=E.read(done)
        if not value['transport'] or any(r.get('outcome')!='completed' for r in value['transport']):
            raise ValueError('saved_outcome_not_completed')
        return value
    if pending.exists():raise ValueError('pending_send_requires_reconciliation')
    return None


def resume(bundle,output):
    bundle,out=Path(bundle),Path(output);plan=E.read(bundle/'plan.json');prior=E.read(out/'summary.json')
    if prior['stop']!='budget_stop':raise ValueError('only_known_budget_stop_can_continue')
    for name,sha in plan['input_sha256'].items():
        if key(E.read(bundle/name))!=sha:raise ValueError('frozen_input_changed')
    lock=E.read(bundle/'source-lock.json');root=Path(__file__).resolve().parents[2]
    if hashlib.sha256(Path(lock['executable']).read_bytes()).hexdigest()!=lock['executable_sha256']:
        raise ValueError('frozen_executable_changed')
    for name,sha in lock['sources'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=sha:raise ValueError('frozen_source_changed')
    amendment={'original_known_tokens':prior['known_tokens'],'same_record_total_cap':350000,
               'no_completed_request_replay':True,'max_total_calls':120,
               'reason':'Finish the originally requested five-need comparison only; no prompt, gate, case or index tuning. All previous classification and failed-run costs retained.'}
    save(out/'completion-amendment.json',amendment)
    rows,nodes,cases,question=[E.read(bundle/name) for name in ['catalog.json','nodes.json','cases.json','question.json']]
    known_receipts=[]
    for f in out.glob('*.done.json'):known_receipts+=E.read(f)['transport']
    spent=sum(r['input_tokens']+r['output_tokens'] for r in known_receipts)
    if spent!=prior['known_tokens']:raise ValueError('saved_usage_does_not_reconcile')
    calls=len(known_receipts);done=list(prior['rows']);finished={(r['case'],r['arm']) for r in done}
    began=time.monotonic();provider=E.JevHierarchyProvider({'executable':lock['executable'],'timeout_seconds':20},deadline=began+240)
    try:
        for index,case in enumerate(cases):
            for arm in (E.ARMS if index%2==0 else list(reversed(E.ARMS))):
                if (case['id'],arm) in finished:continue
                prefix=case['id']+'--'+arm;receipts=[];reused=0
                def invoke(stage,spec,state):
                    nonlocal calls,spent,reused
                    path=out/(prefix+'--'+stage)
                    previous=completed_stage(path,spec,state)
                    if previous is not None:
                        receipts.extend(previous['transport']);reused+=len(previous['transport']);return previous['answer']
                    if spent>=amendment['same_record_total_cap'] or calls>=120:raise RuntimeError('budget_stop')
                    calls+=1;save(str(path)+'.pending.json',{'spec':spec,'state':state});offset=len(provider.calls)
                    try:raw=provider.noul(spec,state)
                    except Exception as error:
                        save(str(path)+'.error.json',{'error':str(error),'transport':provider.calls[offset:]});raise
                    current=provider.calls[offset:];save(str(path)+'.done.json',{'answer':raw,'transport':current})
                    if not current or any('input_tokens' not in r or 'output_tokens' not in r for r in current):raise RuntimeError('unknown_usage_stop')
                    spent+=sum(r['input_tokens']+r['output_tokens'] for r in current);receipts.extend(current)
                    return raw
                result=E.route(arm,nodes,rows,case['need'],question['question'],invoke)
                required=set(case['expected_ids']+case['pending_ids'])
                retained=all(required<=set(t['pool']) for t in result['traces'])
                correct=result['status']=='selected' and result.get('choice') in case['expected_ids']
                item={'case':case['id'],'arm':arm,'result':result,'correct_current':correct,'all_required_retained':retained,
                      'omission_safe_pass':correct and retained,'seconds':sum(r['seconds'] for r in receipts),
                      'time_basis':'sum_of_actual_CLI_receipts','calls':len(receipts),
                      'known_tokens':sum(r['input_tokens']+r['output_tokens'] for r in receipts),
                      'transport':receipts,'reused_stages':reused}
                save(out/(prefix+'.json'),item);done.append(item)
                print(json.dumps({k:v for k,v in item.items() if k not in {'result','transport'}}),flush=True)
        stop='completed'
    except Exception as error:stop=str(error)
    save(out/'completed-summary.json',{'rows':done,'stop':stop,'calls':calls,'known_tokens':spent,
         'new_calls':len(provider.calls),'new_tokens':sum(r.get('input_tokens',0)+r.get('output_tokens',0) for r in provider.calls),
         'continuation_seconds':time.monotonic()-began})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--bundle',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();resume(a.bundle,a.output)
