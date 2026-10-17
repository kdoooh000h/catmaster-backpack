"""Offline checks before bounded public-catalog selection A/B."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks/directory-depth'))
import complete_sources as S
import merged_experiment as E
from resume_merged import completed_stage


def row(identifier,kind='skill',stars=None,growth=None,installs=None):
    m={}
    for name,value,scope in [('stars',stars,'repository'),('growth7d',growth,'repository'),('installs',installs,'skill')]:
        if value is not None:m[name]={'value':value,'scope':scope,'metric':name}
    return {'id':identifier,'name':identifier,'description':'Review dependency vulnerabilities and licenses.',
            'kind':kind,'topics':['security'],'measurements':m}


def page(name,cursor):
    return {'servers':[{'server':{'name':name,'version':'1'},'_meta':{}}], 'metadata':{'nextCursor':cursor}}


class CompletionTests(unittest.TestCase):
    def test_empty_resume_is_not_misreported_as_complete_registry(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/'old';old.mkdir()
            with self.assertRaisesRegex(ValueError,'resume_requires_saved_pages'):
                S.registry(old,root/'new',seconds=1,max_pages=3)

    def test_registry_resume_uses_only_saved_next_cursor_and_no_previous_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/'old';old.mkdir()
            (old/'registry-page-0.json').write_text(json.dumps(page('old','opaque-cursor')))
            value=page('new',None);process=SimpleNamespace(returncode=0,stdout=json.dumps(value).encode()+b'\n200')
            with patch.object(S.subprocess,'run',return_value=process) as call,contextlib.redirect_stdout(io.StringIO()):
                S.registry(old,root/'new',seconds=1,max_pages=3)
            self.assertEqual(call.call_count,1)
            self.assertIn('cursor=opaque-cursor',call.call_args.args[0][-1])
            result=json.loads((root/'new/summary.json').read_text())
            self.assertTrue(result['complete']);self.assertEqual(result['reused_pages'],1)
            self.assertEqual(result['rows'],2)

    def test_registry_cycle_never_becomes_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/'old';old.mkdir()
            (old/'registry-page-0.json').write_text(json.dumps(page('old','cursor')))
            process=SimpleNamespace(returncode=0,stdout=json.dumps(page('new','cursor')).encode()+b'\n200')
            with patch.object(S.subprocess,'run',return_value=process),self.assertRaisesRegex(ValueError,'repeated_registry_cursor'):
                S.registry(old,root/'new',seconds=1,max_pages=3)
            self.assertFalse((root/'new/summary.json').exists())

    def test_ranking_units_and_unknown_visibility_are_preserved(self):
        rows=[row('small',stars=10),row('install-only',installs=1000000),row('unknown'),
              row('large',stars=100),row('rising',stars=30,growth=1000)]
        ordered,backups=E.preference_order(rows)
        self.assertEqual([r['id'] for r in ordered],['large','install-only','unknown','rising','small'])
        self.assertEqual(backups,['rising'])
        self.assertEqual({r['id'] for r in ordered},{r['id'] for r in rows})

    def test_stale_measurements_not_used_and_repository_scope_is_explicit(self):
        item={**row('cap'),'repo':'public/repo'}
        feeds=[{'kind':'skill','feed':'stale','metric':'stars','at':100,'stale':True,
                'rows':[{'repo':'public/repo','stars':999}]},
               {'kind':'skill','feed':'fresh','metric':'stars','at':100,'stale':False,
                'rows':[{'repo':'public/repo','stars':10}]}]
        result=E.measurements(item,feeds)
        self.assertEqual(result['stars']['value'],10);self.assertEqual(result['stars']['scope'],'repository')

    def test_final_threshold_remains_point_seven_for_both_arms(self):
        rows=[row('correct')]
        nodes={'n':{'members':['correct'],'children':['leaf'],'depth':0},
               'leaf':{'members':['correct'],'children':[],'depth':1,'description':'Dependency review'}}
        for arm in E.ARMS:
            for confidence,status in [(.699,'abstain'),(.7,'selected')]:
                def call(stage,spec,state):
                    if stage=='final':return {'answers':{'answer':{'type':'choice','choice':'correct','confidence':confidence}}}
                    return {'answers':{k:{'type':'noul','noul':1} for k in spec['questions']}}
                result=E.route(arm,nodes,rows,'先审查依赖，再做后续任务。','Choose current step.',call)
                self.assertEqual(result['status'],status)
                self.assertIn('correct',result['traces'][0]['pool'])

    def test_global_pressure_expands_small_branches_instead_of_dropping_members(self):
        members=[str(i) for i in range(104)]
        nodes={'n':{'members':members,'children':[],'depth':0}}
        for index in range(13):
            group=members[index*8:(index+1)*8];nid='g'+str(index)
            nodes['n']['children'].append(nid)
            nodes[nid]={'members':group,'children':[nid+'a',nid+'b'],'depth':1,'description':'review'}
            for suffix,part in [('a',group[:4]),('b',group[4:])]:
                nodes[nid+suffix]={'members':part,'children':[],'depth':2,'description':'review'}
        counts=[]
        def call(stage,spec,state):
            self.assertNotEqual(stage,'final');counts.append(len(spec['questions']))
            return {'answers':{k:{'type':'noul','noul':1} for k in spec['questions']}}
        result=E.route('baseline',nodes,[row(i) for i in members],'Review all operations.','Choose.',call)
        self.assertEqual(counts,[13,26])
        self.assertEqual(result['reason'],'final_limit')
        self.assertEqual(set(result['traces'][-1]['pool']),set(members))

    def test_child_descriptions_do_not_repeat_whole_parent_scope(self):
        rows=[row(str(i)) for i in range(16)]
        nodes=E.build_nodes(rows)
        parent=E.TOPICS['security'][1]
        children=[n for k,n in nodes.items() if k.startswith('t-security-skill')]
        self.assertTrue(children)
        self.assertTrue(all(parent not in n['description'] for n in children))
        self.assertTrue(all(n['members'] for n in children))

    def test_completed_stage_reuse_requires_identical_input(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'stage';spec={'questions':{}};state={'task':'原始需求'}
            Path(str(path)+'.pending.json').write_text(json.dumps({'spec':spec,'state':state}))
            value={'answer':{'answers':{}},'transport':[{'outcome':'completed'}]}
            Path(str(path)+'.done.json').write_text(json.dumps(value))
            self.assertEqual(completed_stage(path,spec,state),value)
            with self.assertRaisesRegex(ValueError,'saved_request_changed'):
                completed_stage(path,spec,{'task':'changed'})

    def test_pending_stage_is_never_replayed(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'stage';Path(str(path)+'.pending.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'requires_reconciliation'):
                completed_stage(path,{},{} )


if __name__=='__main__':unittest.main()
