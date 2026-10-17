"""Frozen multi-source directory A/B; public metadata, never capability execution."""
import argparse
from collections import Counter
import json
import hashlib
import math
from pathlib import Path
import re
import sys
import time

import adaptive_experiment as A
from experiment import JevHierarchyProvider, probability, union, vectors, dot, identity
from merged_catalog import merged, TOPICS
from source_preflight import deduplicate, save, key

REF_ROOTS = {
 'engineering':['software','operations','security','data','research'],
 'engineering-team':['software','operations','security','visual'],
 'marketing-skill':['business','writing','visual','research'],
 'c-level-advisor':['business'], 'c-level-agents':['business'],
 'product-team':['business','research','visual'], 'project-management':['business','writing','data'],
 'ra-qm-team':['business','security','writing'], 'finance':['business','data'],
 'business-operations':['business','operations'], 'commercial':['business'],
}
MAP={'development':'software','design':'visual','writing':'writing','data':'data',
     'automation':'operations','collaboration':'business','ai':'software','security':'security'}
ARMS=['baseline','ranked']


def read(p):return json.loads(Path(p).read_text())


def repos(row):
    result=[]
    if row.get('repo'):result.append(row['repo'].casefold())
    identity=row.get('identity',[])
    if len(identity)>1 and identity[0]=='github-plugin':result.append(identity[1])
    provenance=row.get('provenance',[])
    if isinstance(provenance,dict):provenance=[provenance]
    result += [r['repo'].casefold() for r in provenance if r.get('repo')]
    return set(result)


def rank_index(feeds):
    result={}
    for feed in feeds:
        if feed.get('stale') is not False:continue
        for item in feed['rows']:
            repo=item.get('repo','').casefold()
            if repo:result.setdefault(repo,[]).append((feed,item))
    return result


def measurements(row,feeds,index=None):
    candidates=[]
    index=rank_index(feeds) if index is None else index
    for repo in repos(row):
        for feed,item in index.get(repo,[]):
            repo=item.get('repo','').casefold()
            same_repo=repo and repo in repos(row)
            same_skill=(row['kind']=='skill' and same_repo and
                        item.get('slug',item.get('name',''))==row['name'])
            if not same_repo:continue
            if type(item.get('stars')) is int and item['stars']>=0:
                candidates.append({'metric':'stars','value':item['stars'],'scope':'repository','repo':repo,
                                   'feed':feed['feed'],'at':feed['at']})
            growth=item.get('growth7d',item.get('stars7d'))
            if type(growth) is int:
                candidates.append({'metric':'growth7d','value':growth,'scope':'repository','repo':repo,
                                   'feed':feed['feed'],'at':feed['at']})
            if same_skill and feed['feed']=='all-time':
                candidates.append({'metric':'installs','value':item['installs'],'scope':'skill',
                                   'feed':feed['feed'],'at':feed['at']})
    # Never add counters or pick the largest conflicting source value.
    selected={}
    for metric in ('stars','growth7d','installs'):
        choices=[v for v in candidates if v['metric']==metric]
        if choices:
            selected[metric]=sorted(choices,key=lambda v:(v['feed']!='github-topics',v['feed']!='claudius-'+row['kind']+'-growth',-v['at'],v['feed']))[0]
    return selected


def build_nodes(rows):
    """Purpose first, delivery second, query-independent text splits thereafter."""
    by_id={r['id']:r for r in rows};vec=vectors(rows);nodes={}
    def split(ids,node_id,depth,scope,delivery_text):
        centroid=Counter()
        for identifier in ids:centroid.update(vec[identifier])
        cues=[word for word,_ in sorted(centroid.items(),key=lambda p:(-p[1],p[0]))[:18]]
        # Children describe their own members. Repeating the whole parent scope
        # made every narrow child appear to support every operation in it.
        examples=sorted(ids,key=lambda i:(-sum(vec[i].get(w,0) for w in cues),i))[:2]
        concrete='; '.join(by_id[i]['description'][:420] for i in examples)
        description=(delivery_text+' Specific operation cues: '+', '.join(cues)+'. '
                     'Example documented capabilities (not exhaustive): '+concrete)
        if len(ids)<=8:
            description=delivery_text+' Member descriptions: '+'; '.join(by_id[i]['description'] for i in ids)
        nodes[node_id]={'id':node_id,'depth':depth,'members':ids,'children':[], 'description':description}
        if len(ids)>8 and depth<13:
            anchor=ids[0];first=min(ids,key=lambda i:(dot(vec[anchor],vec[i]),i))
            second=min(ids,key=lambda i:(dot(vec[first],vec[i]),i))
            ordered=sorted(ids,key=lambda i:(dot(vec[i],vec[first])-dot(vec[i],vec[second]),i))
            middle=len(ids)//2
            for suffix,part in [('a',ordered[:middle]),('b',ordered[middle:])]:
                split(part,node_id+suffix,depth+1,scope,delivery_text);nodes[node_id]['children'].append(node_id+suffix)
    roots=[]
    delivery={'skill':'Standalone guidance applied by the Agent; no independent external service is required by this metadata.',
              'plugin':'Whole plugin packages. Guidance, tools and actual setup requirements remain package-specific; internal Skills are not separate candidates.',
              'mcp':'Executable MCP tools for actual external operations/data access, not specialist planning instructions. For a design-only task that forbids connecting real systems, domain similarity alone is insufficient.'}
    for topic,(label,scope,_) in TOPICS.items():
        ids=[r['id'] for r in rows if topic in r['topics']]
        if not ids:continue
        nid='t-'+topic;roots.append(nid)
        nodes[nid]={'id':nid,'depth':1,'members':ids,'children':[],'description':label+': '+scope}
        for kind,text in delivery.items():
            part=[i for i in ids if by_id[i]['kind']==kind]
            if not part:continue
            child=nid+'-'+kind;split(part,child,2,scope,text);nodes[nid]['children'].append(child)
    nodes['n']={'id':'n','depth':0,'members':[r['id'] for r in rows],'children':roots,'description':'Merged task catalog'}
    if union(nodes,roots)!=set(by_id):raise ValueError('uncovered_catalog_members')
    return nodes


def prepare(evidence,old,reference,output,app):
    evidence,old,reference,out=map(Path,(evidence,old,reference,output))
    out.mkdir(mode=0o700,exist_ok=False)
    census=read(evidence/'registry/summary.json')
    if not census['complete']:raise ValueError('registry_not_complete')
    classification=read(evidence/'classification/completed.json')
    if not classification['complete']:raise ValueError('classification_not_complete')
    _,rows=merged(old)
    # Reuse the installed deterministic metadata vocabulary without touching its
    # live manager/history. Broader fallback belongs to every task directory.
    sys.path.insert(0,str(Path(app)/'adapters/standalone'))
    import capability_categories as C
    from market_directory import declared_topics
    for row in rows:
        hard=declared_topics({'categories':row.get('publisher_labels',[])})
        soft=classification['possible_index_labels'].get(row['id'],[])
        row['topics']=list(dict.fromkeys(hard+classification['labels'].get(row['id'],[])+soft))
        row['classification_basis']='publisher_or_Jev_with_possible_multilabel_aliases'
        if not row['topics']:raise ValueError('unclassified_original_candidate')
    for envelope in read(evidence/'registry/servers.json'):
        server=envelope['server'];official=envelope.get('_meta',{}).get('io.modelcontextprotocol.registry/official',{})
        if official.get('status')!='active':continue
        repository=server.get('repository',{}).get('url','')
        match=re.fullmatch(r'https://github.com/([^/]+/[^/]+?)(?:\.git)?',repository)
        row={'id':'registry-'+key([server['name'],server['version']])[:20],'name':server.get('title',server['name']),
             'description':server.get('description',''),'kind':'mcp','mode':'execution_requirements_unverified',
             'identity':['registry',server['name'],server['version']],
             'provenance':{'source':'registry','repo':match[1] if match else '', 'version':server['version']}}
        labels=[MAP[label] for label in C.classify(row) if label in MAP]
        row['topics']=list(dict.fromkeys(labels)) or list(TOPICS)
        row['classification_basis']='metadata_vocabulary' if labels else 'broad_all_topics_fallback'
        rows.append(row)
    # Historical public reference corpus is retained only as a labelled control,
    # preserving old gold and comparability. It is not an activated market.
    for original in read(reference/'catalog.json'):
        labels=[]
        for domain in original['source_domains']:
            labels += REF_ROOTS.get(domain.removeprefix('domain:'),[])
        rows.append({**original,'kind':'skill','mode':'guidance','identity':['historical-reference',original['id']],
                     'provenance':{'repo':original['repo'],'source':original['source'],'role':'historical_control_not_enabled'},
                     'topics':list(dict.fromkeys(labels)) or list(TOPICS),'classification_basis':'historical_public_domains'})
    rows=deduplicate(rows)
    if len({r['id'] for r in rows})!=len(rows):raise ValueError('duplicate_catalog_ids')
    feeds=read(evidence/'rankings/feeds-resolved.json')
    index=rank_index(feeds)
    for row in rows:row['measurements']=measurements(row,feeds,index)
    nodes=build_nodes(rows)
    for name,value in [('catalog.json',rows),('nodes.json',nodes),('cases.json',read(reference/'cases.json')),
                       ('question.json',read(reference/'question.json'))]:save(out/name,value)
    plan={'arms':ARMS,'cases':5,'final_gate':.7,'directory_gates':[.2,.3,.4,.45],
          'max_rounds':10,'final_limit':96,'max_calls':120,'max_tokens':140000,'max_seconds':240,
          'attempts':1,'scope':'Merged public metadata selection only; historical 376 control labelled separately; no installation/execution.',
          'comparison':'Same classified/deduplicated catalog and tree. Ranked arm orders by observed popularity and records rising backup; no unverified semantic candidate deletion.',
          'classification_cost':{k:classification[k] for k in ['total_calls','total_known_tokens','seconds']},
          'catalog_count':len(rows),'kinds':dict(Counter(r['kind'] for r in rows)),
          'rank_coverage':sum(bool(r['measurements']) for r in rows),
          'growth_coverage':sum('growth7d' in r['measurements'] for r in rows),
          'broad_fallback':sum(r['classification_basis']=='broad_all_topics_fallback' for r in rows),
          'input_sha256':{p.name:key(read(p)) for p in out.glob('*.json')}}
    save(out/'plan.json',plan);print(json.dumps({k:v for k,v in plan.items() if k not in {'input_sha256','classification_cost'}}),flush=True)


def preference_order(rows):
    """Reorder only comparable kind/metric/scope slots. Never mix units."""
    result=list(rows);groups={};backup=[]
    for index,row in enumerate(rows):
        observed=row['measurements']
        metric='stars' if 'stars' in observed else 'installs' if 'installs' in observed else None
        if metric:groups.setdefault((row['kind'],metric,observed[metric]['scope']),[]).append(index)
    for (_,metric,_),slots in groups.items():
        ranked=sorted([rows[i] for i in slots],key=lambda r:(-r['measurements'][metric]['value'],r['id']))
        growth=[r for r in ranked[1:] if 'growth7d' in r['measurements']]
        if growth:
            rising=max(growth,key=lambda r:r['measurements']['growth7d']['value'])
            backup.append(rising['id']);ranked.remove(rising);ranked.insert(1,rising)
        for index,row in zip(slots,ranked):result[index]=row
    return result,backup


def route(arm,nodes,rows,need,question,call):
    by_id={r['id']:r for r in rows};active=['n'];traces=[];state={'task':need,'rules':A.RULES}
    for depth in range(11):
        pool=union(nodes,active)
        carry=[i for i in active if not nodes[i]['children'] or (len(pool)<=96 and i!='n' and len(nodes[i]['members'])<=8)]
        offered=list(dict.fromkeys(c for i in active if i not in carry for c in nodes[i]['children']))
        reading_stop=False
        if depth and len(pool)<=48:
            final_preview=A.final_spec({i:by_id[i]['description'] for i in pool}|{'none':'No matching capability'},pool,question)
            reading_stop=A.estimate_chars(A.specification(nodes,offered),state)>=.65*A.estimate_chars(final_preview,{'task':need})
        if depth and (len(pool)<=24 or reading_stop or not offered or depth==10):
            if len(pool)>96:return {'status':'unavailable','reason':'final_limit','traces':traces,'final_pool_size':len(pool)}
            ordered=[r for r in rows if r['id'] in pool]
            backups=[]
            if arm=='ranked':
                ordered,backups=preference_order(ordered)
            choices={r['id']:r['description']+ ('\nObserved preference metadata: '+json.dumps(r['measurements'],ensure_ascii=False) if arm=='ranked' and r['measurements'] else '') for r in ordered}
            choices['none']='No offered capability meets the explicitly required current operation.'
            instruction=question+ (' Among equally suitable candidates prefer observed popularity; growth is an alternative. Repository statistics do not prove task fit. Never sacrifice required operations for popularity.' if arm=='ranked' else '')
            spec={'questions':{'answer':{'type':'choice','instructions':instruction,'criteria':choices}}}
            raw=call('final',spec,{'task':need});answer=raw['answers']['answer']
            if answer.get('type')!='choice' or answer.get('choice') not in choices or not probability(answer.get('confidence')):raise ValueError('invalid_final_answer')
            confidence=answer['confidence'];chosen=answer['choice']
            return {'status':'abstain' if confidence<.7 else 'none' if chosen=='none' else 'selected',
                    'choice':chosen if confidence>=.7 else None,'confidence':confidence,'traces':traces,
                    'final_pool_size':len(pool),'backup_order':backups}
        if len(offered)>192:return {'status':'unavailable','reason':'directory_limit','traces':traces}
        spec=A.specification(nodes,offered);raw=call('directory-'+str(depth),spec,state)
        picked=A.retained(raw,offered,nodes);active=list(dict.fromkeys(carry+picked))
        traces.append({'pool':sorted(union(nodes,active)),'retained':picked,'carried':carry,'answers':raw['answers']})
        if not active:return {'status':'none','traces':traces}


def run(bundle,output):
    bundle,out=Path(bundle),Path(output);plan=read(bundle/'plan.json')
    for name,sha in plan['input_sha256'].items():
        if key(read(bundle/name))!=sha:raise ValueError('frozen_input_changed')
    lock=read(bundle/'source-lock.json')
    root=Path(__file__).resolve().parents[2]
    for name,sha in lock['sources'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=sha:raise ValueError('frozen_source_changed')
    if hashlib.sha256(Path(lock['executable']).read_bytes()).hexdigest()!=lock['executable_sha256']:
        raise ValueError('frozen_executable_changed')
    out.mkdir(mode=0o700,exist_ok=False)
    rows,nodes,cases,question=[read(bundle/name) for name in ['catalog.json','nodes.json','cases.json','question.json']]
    began=time.monotonic();provider=JevHierarchyProvider({'executable':'/Users/kk/.local/bin/jev','timeout_seconds':20},deadline=began+plan['max_seconds'])
    spent,calls,done=0,0,[]
    for index,case in enumerate(cases):
        for arm in (ARMS if index%2==0 else list(reversed(ARMS))):
            started=time.monotonic();offset=len(provider.calls);prefix=case['id']+'--'+arm
            def invoke(stage,spec,state):
                nonlocal spent,calls
                if spent>=plan['max_tokens'] or calls>=plan['max_calls']:raise RuntimeError('budget_stop')
                calls+=1;path=out/(prefix+'--'+stage);save(str(path)+'.pending.json',{'spec':spec,'state':state})
                before=len(provider.calls)
                try:raw=provider.noul(spec,state)
                except Exception as error:
                    save(str(path)+'.error.json',{'error':str(error),'transport':provider.calls[before:]});raise
                receipts=provider.calls[before:];save(str(path)+'.done.json',{'answer':raw,'transport':receipts})
                if any('input_tokens' not in r or 'output_tokens' not in r for r in receipts):raise RuntimeError('unknown_usage_stop')
                spent+=sum(r['input_tokens']+r['output_tokens'] for r in receipts)
                return raw
            try:result=route(arm,nodes,rows,case['need'],question['question'],invoke)
            except Exception as error:
                save(out/'summary.json',{'rows':done,'stop':str(error),'calls':calls,'known_tokens':spent});return
            required=set(case['expected_ids']+case['pending_ids'])
            retained=all(required<=set(t['pool']) for t in result['traces'])
            correct=result['status']=='selected' and result.get('choice') in case['expected_ids']
            receipts=provider.calls[offset:]
            item={'case':case['id'],'arm':arm,'result':result,'correct_current':correct,'all_required_retained':retained,
                  'omission_safe_pass':correct and retained,'seconds':time.monotonic()-started,'calls':len(receipts),
                  'known_tokens':sum(r.get('input_tokens',0)+r.get('output_tokens',0) for r in receipts),'transport':receipts}
            done.append(item);save(out/(prefix+'.json'),item)
            print(json.dumps({k:v for k,v in item.items() if k not in {'result','transport'}}),flush=True)
    save(out/'summary.json',{'rows':done,'stop':'completed','calls':calls,'known_tokens':spent,'seconds':time.monotonic()-began})


if __name__=='__main__':
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='operation',required=True)
    a=s.add_parser('prepare')
    for name in ['evidence','old','reference','output','app']:a.add_argument('--'+name,required=True)
    a=s.add_parser('run');a.add_argument('--bundle',required=True);a.add_argument('--output',required=True)
    a=p.parse_args();v=vars(a).copy();v.pop('operation');(prepare if a.operation=='prepare' else run)(**v)
