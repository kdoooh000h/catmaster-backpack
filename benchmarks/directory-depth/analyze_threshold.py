"""Reconcile receipts and compare only fresh matched cases; no model calls."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import subprocess

import adaptive_threshold as T
from adaptive_cost_experiment import ROOT, digest
from analyze_adaptive_cost import metrics
from experiment import grade, identity, read, write_once
from threshold_experiment import FAILED


def aggregate(rows):
    return metrics(rows) | {
        'current_reference_selected': sum(r['passed'] for r in rows),
        'all_required_retained': sum(bool(r['all_required_retained']) for r in rows),
        'median_seconds': statistics.median(r['seconds'] for r in rows),
        'total_tokens': sum(r['known_tokens'] for r in rows),
        'total_calls': sum(r['calls'] for r in rows),
        'mean_last_pool': statistics.mean(len(r['result']['traces'][-1]['pool']) for r in rows),
    }


def sanitize(row, nodes, case):
    result = {key: value for key,value in row.items() if key not in {'transport','result'}}
    result['result'] = {key:value for key,value in row['result'].items() if key != 'traces'}
    required = set(case['expected_ids'] + case['pending_ids'])
    result['stages'] = [{
        'pool_size': len(t['pool']), 'offered': t['offered_count'], 'carried': t['carried_count'],
        'missing_required_ids': sorted(required - set(t['pool'])),
        'required_branch_scores': {k:v['noul'] for k,v in t['answers'].items() if required & set(nodes[k]['members'])},
        'threshold_adjustment': t.get('threshold_adjustment'),
    } for t in row['result']['traces']]
    return result


def analyze(bundle, live, output):
    bundle,live = Path(bundle),Path(live)
    plan,summary,nodes = read(bundle/'plan.json'),read(live/'summary.json'),read(bundle/'candidate-nodes.json')
    for name,sha in plan['source_sha256'].items():
        if digest(ROOT/name) != sha: raise ValueError('frozen_source_changed')
    for name,sha in plan['input_sha256'].items():
        if digest(bundle/name) != sha: raise ValueError('frozen_input_changed')
    if digest(plan['executable']) != plan['executable_sha256']: raise ValueError('executable_changed')
    cases={c['id']:c for c in read(bundle/'cases.json')}
    question=read(bundle/'question.json')
    choices={r['id']:r['description'] for r in read(bundle/'catalog.json')} | {'none':question['none']}
    rows=summary['rows'];expected={(key,arm) for key,arms in plan['case_arms'].items() for arm in arms}
    actual={(r['case'],r['arm']) for r in rows}
    if summary['stop']!='completed' or len(rows)!=len(expected) or actual!=expected:
        raise ValueError('incomplete_or_duplicate_rows')
    ordinals=[];stages=defaultdict(lambda:defaultdict(float));all_receipts=[];adjustments=0
    for row in rows:
        case=cases[row['case']];arm=row['arm'];traces=row['result']['traces'];receipts=[]
        expected_grade=grade(case,row['result'])
        if any(row[k]!=v for k,v in expected_grade.items()):raise ValueError('grade_changed')
        prefix=live/('r0--'+row['case']+'--'+arm)
        expected_requests=[]
        for index,trace in enumerate(traces):
            keys=list(trace['answers'])
            spec=(T.focused_specification if arm=='adaptive_focus' else T.A.specification)(nodes,keys)
            expected_requests.append(('directory-'+str(index),spec,{'task':case['need'],'rules':T.A.RULES},trace['answers']))
            if arm=='baseline': kept=T.A.retained({'answers':trace['answers']},keys,nodes)
            else:
                kept,adjust=T.retention({'answers':trace['answers']},keys,trace['carried'],nodes)
                if identity(adjust)!=identity(trace['threshold_adjustment']):raise ValueError('gate_reconciliation_failed')
                adjustments+=len(adjust['changes'])
            if kept!=trace['retained'] or sorted(T.A.union(nodes,trace['carried']+kept))!=trace['pool']:
                raise ValueError('pool_reconciliation_failed')
        if row['result']['status'] in {'selected','abstain'} or row['result'].get('stop_reason'):
            spec=T.A.final_spec(choices,set(traces[-1]['pool']),question['question'])
            spec['questions']['answer']['instructions']=T.C.CURRENT_LEAD+question['question'][len(T.C.ORIGINAL_LEAD):]
            expected_requests.append(('final',spec,{'task':case['need']},None))
        for stage,spec,state,answers in expected_requests:
            pending=read(str(prefix)+'--'+stage+'.pending.json');done=read(str(prefix)+'--'+stage+'.done.json')
            if pending['spec']!=spec or pending['state']!=state:raise ValueError('request_changed')
            if answers is not None and done['answer']['answers']!=answers:raise ValueError('answer_changed')
            if stage=='final':
                answer=done['answer']['answers']['answer']
                result=row['result'];confidence=answer['confidence']
                status='abstain' if confidence<.7 else ('none' if answer['choice']=='none' else 'selected')
                if result['status']!=status or result['confidence']!=confidence or result['choice']!=(None if status=='abstain' else answer['choice']):
                    raise ValueError('final_gate_changed')
            ordinals.append(pending['ordinal']);receipts+=done['transport']
            kind='final' if stage=='final' else 'directory'
            for receipt in done['transport']:
                if receipt.get('outcome')!='completed' or not {'input_tokens','output_tokens'}<=receipt.keys():
                    raise ValueError('unknown_transport_or_usage')
                stages[arm][kind+'_calls']+=1
                stages[arm][kind+'_tokens']+=receipt['input_tokens']+receipt['output_tokens']
                stages[arm][kind+'_seconds']+=receipt['seconds']
        if receipts!=row['transport'] or len(receipts)!=row['calls'] or sum(r['input_tokens']+r['output_tokens'] for r in receipts)!=row['known_tokens']:
            raise ValueError('row_usage_changed')
        all_receipts+=receipts
    if sorted(ordinals)!=list(range(1,summary['calls']+1)) or len(all_receipts)!=summary['calls']:
        raise ValueError('call_sequence_changed')
    if len(list(live.glob('*.pending.json')))!=summary['calls'] or len(list(live.glob('*.done.json')))!=summary['calls'] or list(live.glob('*.error.json')):
        raise ValueError('unreconciled_receipt')
    if sum(r['known_tokens'] for r in rows)!=summary['known_tokens']:raise ValueError('total_usage_changed')
    protected=read(live.parent/'protected-before.json')
    changed=[p for p,sha in protected.items() if (digest(p) if Path(p).is_file() else None)!=sha]
    others={}
    for name,before in read(live.parent/'other-worktrees-before.json').items():
        path=Path(before['path'])
        files=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=path).decode().split('\0')
        current={str(path/f):digest(path/f) for f in set(files) if f and (path/f).is_file()}
        others[name]={'head_unchanged':subprocess.check_output(['git','rev-parse','HEAD'],cwd=path,text=True).strip()==before['head'],
            'status_unchanged':hashlib.sha256(subprocess.check_output(['git',*before['status_command']],cwd=path)).hexdigest()==before['status_sha256'],
            'snapshotted_files':len(before['files']),
            'changed_or_missing_files':sum(current.get(p)!=sha for p,sha in before['files'].items()),
            'added_files':len(set(current)-set(before['files']))}
    fresh=[r for r in rows if r['case']!=FAILED]
    by_arm={arm:aggregate([r for r in fresh if r['arm']==arm]) for arm in T.ARMS}
    reused=read(bundle/'reused-baseline.json')
    public={'version':1,'scope':plan['scope'],'plan':{k:v for k,v in plan.items() if k!='executable'},
        'stop':summary['stop'],'actual_calls':summary['calls'],'known_tokens':summary['known_tokens'],'wall_seconds':summary['seconds'],
        'fresh_case_metrics':by_arm,'fresh_case_ids':[k for k in cases if k!=FAILED],
        'change_vs_baseline_percent':{arm:{field:100*(by_arm[arm][field]/by_arm['baseline'][field]-1) for field in ('mean_tokens','mean_seconds','mean_calls')} for arm in T.ARMS[1:]},
        'candidate_all_five_metrics':{arm:aggregate([r for r in rows if r['arm']==arm]) for arm in T.ARMS[1:]},
        'candidate_eligible':{arm:all(r['omission_safe_pass'] for r in rows if r['arm']==arm) for arm in T.ARMS[1:]},
        'reused_old_baseline':{'counted_as_new_measurement':False,'row':sanitize(reused,nodes,cases[FAILED])},
        'rows':[sanitize(r,nodes,cases[r['case']]) for r in rows],
        'live_gate_adjustments':adjustments,'stage_usage':dict(stages),
        'validation':{'offline_tests':12,'all_requests_reconciled':True,'receipt_pairs':len(ordinals),'frozen_inputs_and_source_match':True,
            'protected_files':len(protected),'changed_protected_count':len(changed),'other_worktrees':others,
            'passed_baseline_resent':False,'unknown_sends':0,'transport_errors':0,'missing_usage':0},
        'source_summary_sha256':digest(live/'summary.json'),
        'offline_gate_replay':read(live.parent/'offline-policy.json'),
        'offline_route_replay':read(live.parent/'offline-route-replay.json'),
        'jev_usage_audit':read(live.parent/'jev-use-audit.json'),
        'preferred_candidate':'unchanged_description_baseline',
        'limitations':[plan['limitations'],'Adaptive gates never fired live, so cost differences in that arm are sampling/timing differences, not a demonstrated threshold gain.',
            'Focused treatment changes both question wording and its structure; individual contributions are not isolated.',
            'Old passing baseline is historical, excluded from fresh cost comparisons. All semantic failures remain.',
            'Costs cover Jev selection only, excluding root analysis, intent entry and business execution. No daily installation or real capability execution is validated.']}
    write_once(output,public)
    print(json.dumps({k:public[k] for k in ('actual_calls','known_tokens','fresh_case_metrics','candidate_eligible','live_gate_adjustments','validation')},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--bundle',required=True);parser.add_argument('--live',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();analyze(args.bundle,args.live,args.output)
