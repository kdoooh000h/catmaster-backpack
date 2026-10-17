#!/usr/bin/env python3
"""Summarize native/backpack receipts without exposing handles or credentials.

This is telemetry, not a self-grader: artifact acceptance is recorded separately.
Cached input is a subset of input_tokens and is never added a second time.
"""
import argparse
import json
from pathlib import Path

def lines(path):
    if not path.exists(): return []
    rows=[]
    for text in path.read_text().splitlines():
        try: rows.append(json.loads(text))
        except ValueError: rows.append({'parse_error': True})
    return rows

def payload(message):
    value=message.get('result', {})
    for part in value.get('content', []):
        if part.get('type')=='text':
            try: return json.loads(part['text'])
            except ValueError: pass
    return {}

def usage(values, expected):
    rows=[x for x in values if isinstance(x,dict) and isinstance(x.get('input_tokens'),int) and isinstance(x.get('output_tokens'),int)]
    result={'calls_expected':expected,'calls_with_usage':len(rows),'complete':len(rows)==expected,
            'input_tokens':sum(x['input_tokens'] for x in rows),
            'output_tokens':sum(x['output_tokens'] for x in rows)}
    result['known_total_tokens']=result['input_tokens']+result['output_tokens']
    return result

def interval_seconds(spans):
    total=0; end=None
    for start,stop in sorted(spans):
        if stop < start:continue
        total+=max(0,stop-max(start,end if end is not None else start))
        end=max(end if end is not None else stop,stop)
    return round(total,3)

def session_usage(case, events):
    """Recover observed cumulative usage, never an estimate of an unfinished request.

    Only the single recorded native thread is read. Repeated token_count events
    report cumulative totals, so neither those nor reasoning/cache subsets add
    another charge to the total. Raw session text stays in the private home.
    """
    threads={e.get('thread_id') for e in events if e.get('type')=='thread.started'}-{None}
    if len(threads)!=1:return None
    thread=next(iter(threads))
    # Thread IDs are filenames supplied by the native runtime, not glob patterns.
    paths=[p for p in (case/'home/.codex/sessions').rglob('rollout-*.jsonl') if p.stem.endswith('-'+thread)]
    if len(paths)!=1:return None
    updates=[];previous=None
    for event in lines(paths[0]):
        body=event.get('payload',{})
        if event.get('type')!='event_msg' or body.get('type')!='token_count':continue
        info=body.get('info') or {};total=info.get('total_token_usage') or {}
        if not all(type(total.get(k)) is int and total[k]>=0 for k in ('input_tokens','output_tokens')):continue
        identity=(total['input_tokens'],total['output_tokens'])
        if identity==previous:continue
        if previous and any(a<b for a,b in zip(identity,previous)):return None
        previous=identity
        # Include only token counters, not unrelated session/response metadata.
        fields=('input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens')
        updates.append({'at':event.get('timestamp'),
            'cumulative':{k:total[k] for k in fields if type(total.get(k)) is int},
            'last_request':{k:v for k,v in (info.get('last_token_usage') or {}).items()
                            if k in fields and type(v) is int}})
    if not updates:return None
    total=updates[-1]['cumulative'];cached=total.get('cached_input_tokens')
    return {**total,'known_total_tokens':total['input_tokens']+total['output_tokens'],
        'noncached_input_tokens':total['input_tokens']-cached
            if type(cached) is int and 0<=cached<=total['input_tokens'] else None,
        'observed_usage_updates':len(updates),'updates':updates,
        'coverage':'Observed usage events only; an interrupted in-flight request may be missing.'}

def case_summary(case, baseline):
    run=json.loads((case/'run.json').read_text()) if (case/'run.json').exists() else {'status':'not_started'}
    events=lines(case/'events.jsonl')
    complete=[x for x in events if x.get('type')=='turn.completed']
    transport_errors=[x.get('message',str(x.get('error',''))) for x in events
                      if x.get('type')=='error' and any(term in str(x).lower()
                      for term in ('reconnect','stream disconnected','tls','connection'))]
    started=sum(x.get('type')=='turn.started' for x in events)
    native=usage([x.get('usage') for x in complete],started)
    native['cached_input_tokens']=sum(x.get('usage',{}).get('cached_input_tokens',0) for x in complete)
    native['cache_accounting_complete']=bool(complete) and native['complete'] and all(
        isinstance(x.get('usage',{}).get('cached_input_tokens'),int)
        and 0 <= x['usage']['cached_input_tokens'] <= x['usage']['input_tokens'] for x in complete)
    native['noncached_input_tokens']=(native['input_tokens']-native['cached_input_tokens']
                                      if native['cache_accounting_complete'] else None)
    native['cache_write_input_tokens']=sum(x.get('usage',{}).get('cache_write_input_tokens',0) for x in complete)
    observed=session_usage(case,events)
    jev=lines(case/'jev.jsonl')
    routing=usage([x.get('usage') for x in jev if x.get('event')=='finished'],sum(x.get('event')=='started' for x in jev))
    requests={}; calls=[]; spans=[]
    for row in lines(case/'backpack-wire.jsonl'):
        msg=row.get('message',{})
        if row.get('direction')=='in' and msg.get('method')=='tools/call':
            requests[msg['id']]=row
        if row.get('direction')!='out' or msg.get('id') not in requests:continue
        request=requests.pop(msg['id']);params=request['message']['params']
        spans.append((request['at'],row['at']))
        value=payload(msg)
        result={'tool':params['name'],'elapsed_seconds':round(row['at']-request['at'],3),
                'status':value.get('status'), 'reason':value.get('reason'),
                'is_error':msg.get('result',{}).get('isError',False),
                'need':params.get('arguments',{}).get('need'),
                'search':params.get('arguments',{}).get('search')}
        if value.get('name'):
            result['selected_name']=value['name']
            result['preexisting_name']=value['name'].casefold() in baseline
        if value.get('source'): result['source']=value['source']
        if value.get('components'): result['components']=value['components']
        if params['name']=='report_skill_use':result['reported_event']=params['arguments'].get('event')
        if params['name'] in ('acquire_mcp','invoke_mcp'):
            result['selected_server']=value.get('server');result['selected_tool']=value.get('tool')
        calls.append(result)
    for row in requests.values():
        calls.append({'tool':row['message']['params']['name'],'status':'no_recorded_response','is_error':True})
    wait=interval_seconds(spans)
    return {'case':case.name, **{k:run.get(k) for k in ('status','returncode','elapsed_seconds')},
            'backpack_wait_seconds':wait,
            'other_elapsed_seconds':round(max(0,run['elapsed_seconds']-wait),3) if run.get('elapsed_seconds') is not None else None,
            'jev_elapsed_seconds':round(sum(x.get('elapsed_seconds',0) for x in jev if x.get('event')=='finished'),3),
            'host_operations':{kind:sum(e.get('type')=='item.completed' and e.get('item',{}).get('type')==kind for e in events)
                               for kind in ('mcp_tool_call','command_execution','file_change')},
            'native_turn_completed':len(complete),'native_usage':native,'native_session_usage':observed,'jev_usage':routing,
            'native_transport_error_events':transport_errors,
            'backpack_calls':calls,'known_total_tokens':max(native['known_total_tokens'],
                observed['known_total_tokens'] if observed else 0)+routing['known_total_tokens'],
            'token_coverage_complete':native['complete'] and routing['complete'] and bool(complete) and not transport_errors,
            'final_exists':(case/'final.txt').exists(),
            'output_files':sorted(str(x.relative_to(case/'work')) for x in (case/'work').rglob('*') if x.is_file()),
            'acceptance':json.loads((case/'acceptance.json').read_text()) if (case/'acceptance.json').exists() else None}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('root');args=parser.parse_args()
    root=Path(args.root);manifest=json.loads((root/'manifest.json').read_text())
    inventory=json.loads((root/'installed-before.json').read_text())
    baseline={n.casefold() for n in inventory['names']}
    cases=[case_summary(root/name,baseline) for name in manifest['tasks']]
    result={'schema':'backpack-blind-pilot-v1','cases':cases,
            'known_total_tokens':sum(c['known_total_tokens'] for c in cases),
            'native_elapsed_seconds':round(sum(c['elapsed_seconds'] or 0 for c in cases),3),
            'usd_cost':None,'notes':['Family fixed by evaluator; no capability names supplied.',
                'Actual endpoint/model behind configured aliases is unobservable.',
                'Known token totals exclude orchestration and missing provider usage.',
                'Task correctness and discovery/connection/use acceptance require evidence review.']}
    (root/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));(root/'summary.json').chmod(0o600)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
