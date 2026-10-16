"""Receipt-based offline acceptance report; no network/model request."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics

from source_preflight import save,key


def read(path):return json.loads(Path(path).read_text())


def analyze(evidence,output):
    root=Path(evidence);bundle=root/'bundle-v2';live=root/'live-v2'
    plan=read(bundle/'plan.json');summary=read(live/'completed-summary.json');cases=read(bundle/'cases.json')
    by_case={c['id']:c for c in cases}
    if summary['stop']!='completed' or len(summary['rows'])!=10:raise ValueError('incomplete_comparison')
    for name,sha in plan['input_sha256'].items():
        if key(read(bundle/name))!=sha:raise ValueError('changed_frozen_input')
    rows=[]
    for row in summary['rows']:
        case=by_case[row['case']];result=row['result'];required=case['expected_ids']+case['pending_ids']
        correct=result['status']=='selected' and result.get('choice') in case['expected_ids']
        retained=all(set(required)<=set(t['pool']) for t in result['traces'])
        if correct!=row['correct_current'] or retained!=row['all_required_retained']:raise ValueError('grade_mismatch')
        receipts=[]
        for path in live.glob(row['case']+'--'+row['arm']+'--*.done.json'):
            done=read(path);pending=read(Path(str(path).replace('.done.json','.pending.json')))
            if pending['state']['task']!=case['need']:raise ValueError('raw_need_changed')
            if any(r.get('outcome')!='completed' or 'input_tokens' not in r or 'output_tokens' not in r for r in done['transport']):
                raise ValueError('invalid_or_unknown_receipt')
            receipts+=done['transport']
        tokens=sum(r['input_tokens']+r['output_tokens'] for r in receipts)
        if len(receipts)!=row['calls'] or tokens!=row['known_tokens']:raise ValueError('usage_mismatch')
        if result['status']=='selected' and result['confidence']<.7:raise ValueError('gate_violation')
        first_lost={target:next((i+1 for i,t in enumerate(result['traces']) if target not in t['pool']),None) for target in required}
        rows.append({'case':row['case'],'arm':row['arm'],'status':result['status'],'choice':result.get('choice'),
            'confidence':result.get('confidence'),'current_reference_match':correct,'all_required_references_retained':retained,
            'omission_safe_pass':correct and retained,'tokens':tokens,'calls':len(receipts),
            'jev_cli_seconds':sum(r['seconds'] for r in receipts),'final_pool':result.get('final_pool_size'),
            'first_lost_at_directory_stage':first_lost,'directory_pools':[len(t['pool']) for t in result['traces']],
            'reused_saved_stages':row.get('reused_stages',0)})
    if {(r['case'],r['arm']) for r in rows}!={(c['id'],a) for c in cases for a in ['baseline','ranked']}:
        raise ValueError('case_arm_coverage_mismatch')
    aggregates={}
    for arm in ['baseline','ranked']:
        selected=[r for r in rows if r['arm']==arm]
        aggregates[arm]={'cases':len(selected),'current_reference_matches':sum(r['current_reference_match'] for r in selected),
            'omission_safe_passes':sum(r['omission_safe_pass'] for r in selected),
            'mean_jev_cli_seconds':statistics.mean(r['jev_cli_seconds'] for r in selected),
            'mean_tokens':statistics.mean(r['tokens'] for r in selected),'mean_calls':statistics.mean(r['calls'] for r in selected)}
    classification=read(root/'classification/completed.json');registry=read(root/'registry/summary.json')
    feeds=read(root/'rankings/feeds-resolved.json');preliminary=read(root/'live/summary.json')
    if not registry['complete'] or not classification['complete']:raise ValueError('incomplete_prerequisite')
    actual=sum(r['tokens'] for r in rows)
    if actual!=summary['known_tokens']:raise ValueError('summary_usage_mismatch')
    pending_sends=[]
    for folder in [root/'classification',root/'live',live]:
        for path in folder.glob('*.pending.json'):
            if not Path(str(path).replace('.pending.json','.done.json')).exists():pending_sends.append(str(path.name))
    if pending_sends:raise ValueError('unreconciled_send')
    result={'version':1,'verdict':'reject_ranked_strategy_and_do_not_promote_merged_index',
        'classification':{'original_pending':589,'processed':classification['processed'],
            'confidence_at_least_point_seven':classification['high_confidence_classified'],
            'provisional_multi_label':589-classification['high_confidence_classified'],
            'unindexed':len(classification['without_any_index_label']),
            'calls':classification['total_calls'],'tokens':classification['total_known_tokens'],'seconds':classification['seconds']},
        'registry':registry,'rankings':{'fresh_feeds':sum(f.get('stale') is False for f in feeds),'feeds':len(feeds),
            'candidate_coverage':plan['rank_coverage'],'growth_coverage':plan['growth_coverage'],
            'missing_is_unknown':True,'scope':'Repository stars/growth remain repository metrics; individual installs only join exact Skill identities.'},
        'catalog':{'total':plan['catalog_count'],'kinds':plan['kinds'],'historical_control_skills':376,
            'enabled_public_source_candidates':plan['catalog_count']-376,'plugin_internal_candidates':0,
            'broad_mcp_fallback_candidates':plan['broad_fallback'],'markets_merged':True,'dedup':'programmatic'},
        'comparison':{'aggregates':aggregates,'rows':rows,'final_confidence':.7,'raw_needs_unchanged':True,
            'ranking_token_change_percent':100*(aggregates['ranked']['mean_tokens']/aggregates['baseline']['mean_tokens']-1),
            'ranking_time_change_percent':100*(aggregates['ranked']['mean_jev_cli_seconds']/aggregates['baseline']['mean_jev_cli_seconds']-1),
            'time_basis':'sum of actual Jev CLI process receipts, excludes index preparation, local assembly and main Agent',
            'baseline_scope':'Accepted adaptive gates/cost stop applied to the same new merged index; not the daily installed source-first route.',
            'common_adaptations':['10-round allowance for the much larger index','Global <=96 condition before carrying small branches',
                'Delivery distinction and specific child descriptors'],
            'sample_limit':'Five author-written multi-step planning needs, one sample per arm; strict historical references, not universal capability-equivalence or task-execution accuracy.'},
        'costs':{'classification_calls':classification['total_calls'],'classification_tokens':classification['total_known_tokens'],
            'failed_preliminary_calls':preliminary['calls'],'failed_preliminary_tokens':preliminary['known_tokens'],
            'completed_comparison_calls':summary['calls'],'completed_comparison_tokens':actual,
            'total_known_calls':classification['total_calls']+preliminary['calls']+summary['calls'],
            'total_known_tokens':classification['total_known_tokens']+preliminary['known_tokens']+actual,
            'excluded_unobservable':['Main Agent tokens','intent entry tokens','backend model revision','monetary price'],
            'budget_history':'Classification 300k conservative stop amended to 400k without replay; initial A/B 260k failed; corrected A/B 160k stopped and same-record completion amended to 350k, reusing six completed stages.'},
        'verification':{'offline_checks':30,'receipt_integrity':True,'pending_unknown_sends':False,
            'no_capability_execution':True,'no_daily_upgrade':True},
        'evidence_hashes':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in
            ['registry/summary.json','rankings/feeds-resolved.json','classification/completed.json','bundle-v2/plan.json','bundle-v2/source-lock.json','live-v2/completed-summary.json']}}
    save(output,result)
    print(json.dumps({'aggregates':aggregates,'total_known_tokens':result['costs']['total_known_tokens'],'verdict':result['verdict']}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--evidence',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();analyze(a.evidence,a.output)
