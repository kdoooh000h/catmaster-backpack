"""Registered metadata refresh, coverage and stops; no real model or host permission."""
from copy import deepcopy
import json,os
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/catmaster_backpack'))
import plugin_directory as directory
from plugin_pipeline import init_store,atomic_json


class Classifier:
    def __init__(self, fail=False):self.calls=[];self.fail=fail
    def noul(self,spec,state):
        self.calls.append({'input_tokens':10,'output_tokens':2})
        if self.fail:raise TimeoutError('PRIVATE must not leak')
        name=state['capability_metadata']['name'];leaf='data_query' if name=='query' else 'writing_knowledge'
        return {'answers':{key:{'type':'noul','noul':.9 if key==leaf else .01} for key in spec['questions']}}


class Selector:
    def __init__(self, *,single=False,confidence=.9,fail=False):self.calls=[];self.single=single;self.confidence=confidence;self.fail=fail;self.pool=None
    def noul(self,spec,state):
        self.calls.append({'input_tokens':10,'output_tokens':2})
        if self.fail:raise TimeoutError('PRIVATE error')
        return {'answers':{key:{'type':'noul','noul':self.confidence if key=='match' else .9 if key in ('data_content','data_query') else .01} for key in spec['questions']}}
    def choose(self,question,state,choices):
        self.calls.append({'input_tokens':10,'output_tokens':2});self.pool=choices
        key=next(key for key in choices if key!='none')
        return {'type':'choice','choice':key,'confidence':self.confidence}


class DirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.project=self.root/'project';self.project.mkdir();self.store=self.root/'store';init_store(self.store,self.project)
        self.calls=[];self.populate()
    def populate(self, names=('query','write')):
        _,_,registry=directory.load_registry(self.store)
        registry['plugins']={'fixture':{'name':'fixture','root':str(self.project),'library':[
            {'kind':'skill','path':name+'/SKILL.md','name':name,'description':'Query SQL database.' if name=='query' else 'Write prose.'} for name in names], 'indexes':{}}}
        atomic_json(self.store/'registry.json',registry)
    def factory(self):
        p=Classifier();self.calls.append(p);return p
    def refresh(self):return directory.refresh(self.store,provider_factory=self.factory)
    def entries(self):return directory.registered_entries(directory.load_registry(self.store)[2])
    def test_changed_only_refresh_covers_every_registered_capability(self):
        result=self.refresh();self.assertEqual((result['status'],result['classification_calls']),('ready',2))
        entries=self.entries();tree=directory.available_directory(self.store,entries)
        self.assertEqual(set(tree.members(tree.root_ids)),set(entries))
        self.assertEqual(self.refresh()['classification_calls'],0)
        registry=directory.load_registry(self.store)[2];registry['plugins']['fixture']['library'][0]['description']='Query and inspect SQL database.'
        atomic_json(self.store/'registry.json',registry)
        self.assertEqual(self.refresh()['classification_calls'],1)
    def test_uncertain_classification_is_cached_and_does_not_replay(self):
        provider=Classifier(fail=True)
        first=directory.refresh(self.store,provider_factory=lambda:provider)
        self.assertEqual(first['pending'],2);self.assertEqual(len(provider.calls),2)
        second=directory.refresh(self.store,provider_factory=lambda:provider)
        self.assertEqual(second['classification_calls'],0);self.assertEqual(len(provider.calls),2)
        self.assertNotIn('PRIVATE',json.dumps(directory.read_cache(self.store)))
    def test_new_unclassified_or_changed_entry_stops_before_routing(self):
        self.refresh();entries=self.entries();entries['new']=dict(next(iter(entries.values())),name='new')
        provider=Selector();r=directory.select('query',entries,self.store,provider_factory=lambda _:provider)
        self.assertEqual(r['reason'],'directory_review_required');self.assertEqual(provider.calls,[])
        entries=self.entries();next(iter(entries.values()))['description']='changed'
        self.assertEqual(directory.select('query',entries,self.store,provider_factory=lambda _:provider)['reason'],'directory_review_required')
    def test_unavailable_entries_prune_but_unregistered_ids_remain_bound(self):
        self.refresh();entries=self.entries();query={k:v for k,v in entries.items() if v['name']=='query'}
        tree=directory.available_directory(self.store,query);self.assertEqual(set(tree.members(tree.root_ids)),set(query))
    def test_singleton_requires_three_typed_decisions_and_no_global_choice(self):
        self.populate(('query',));self.refresh();provider=Selector(single=True)
        result=directory.select('query database',self.entries(),self.store,provider_factory=lambda _:provider)
        self.assertEqual(result['status'],'selected');self.assertEqual(result['reason'],'singleton_confirmed');self.assertEqual(len(provider.calls),3);self.assertIsNone(provider.pool)
        for confidence in (.2,.64,True,float('nan')):
            p=Selector(single=True,confidence=confidence)
            self.assertNotEqual(directory.select('query',self.entries(),self.store,provider_factory=lambda _:p)['status'],'selected')
    def test_provider_failure_is_one_shot_and_discloses_no_guidance(self):
        self.refresh();p=Selector(fail=True)
        result=directory.select('query',self.entries(),self.store,provider_factory=lambda _:p)
        self.assertEqual(result['status'],'unavailable');self.assertEqual(len(p.calls),1);self.assertNotIn('choice',result);self.assertNotIn('PRIVATE',json.dumps(result))
    def test_cache_owner_mode_and_symlink_checks(self):
        self.refresh();path=self.store/directory.FILE;path.chmod(0o644)
        with self.assertRaises(ValueError):directory.read_cache(self.store)
        path.rename(self.store/'retained.json');path.symlink_to(self.store/'retained.json')
        with self.assertRaises(OSError):directory.read_cache(self.store)
    def test_model_classification_never_reads_guidance_or_calls_business_tools(self):
        self.refresh()
        self.assertFalse(any((self.project/name/'SKILL.md').exists() for name in ('query','write')))
        self.assertEqual(len(self.calls),2)
    def test_service_identity_disambiguates_same_name_tools(self):
        first={'kind':'tool','plugin':'db','server':'reports','name':'query','description':'Query SQL.'}
        second=dict(first,server='billing')
        self.assertNotEqual(directory.wire(first),directory.wire(second))
        self.assertIn('/reports/query:',directory.wire(first))
    def test_template_change_stops_before_provider(self):
        self.refresh();provider=Selector();changed=directory.template();changed['roots'][0]['description']+=' New operation.'
        with patch('plugin_directory.template',return_value=changed):
            result=directory.select('query',self.entries(),self.store,provider_factory=lambda _:provider)
        self.assertEqual(result['reason'],'directory_review_required');self.assertEqual(provider.calls,[])
    def test_pending_ineligible_capability_does_not_disable_available_subset(self):
        class Partial(Classifier):
            def noul(inner,spec,state):
                if state['capability_metadata']['name']=='write':raise TimeoutError('unknown')
                return super().noul(spec,state)
        result=directory.refresh(self.store,provider_factory=Partial)
        self.assertEqual(result['status'],'pending')
        entries=self.entries();available={k:v for k,v in entries.items() if v['name']=='query'}
        self.assertTrue(directory.available_directory(self.store,available))
        with self.assertRaises(ValueError):directory.available_directory(self.store,entries)
    def test_classification_budget_defers_unattempted_and_resumes_only_them(self):
        with patch('plugin_directory.MAX_CLASSIFICATION_CALLS',1):
            self.assertEqual(self.refresh()['classification_calls'],1)
            self.assertEqual(self.refresh()['classification_calls'],1)
            self.assertEqual(self.refresh()['classification_calls'],0)
        self.assertEqual(len(self.calls),2)
    def test_registration_changed_during_refresh_does_not_publish_stale_tree(self):
        class Changed(Classifier):
            def noul(inner,spec,state):
                registry=directory.load_registry(self.store)[2]
                registry['plugins']['fixture']['library'][0]['description']+=' Changed.'
                atomic_json(self.store/'registry.json',registry)
                return super().noul(spec,state)
        result=directory.refresh(self.store,provider_factory=Changed)
        self.assertEqual(result['status'],'stale');self.assertIsNone(directory.read_cache(self.store)['directory'])
    def test_public_shared_core_copies_have_identical_bytes(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('public_capability_directory.py','hierarchical_choice_routing.py','jev_hierarchy_provider.py'):
            self.assertEqual((root/'core'/name).read_bytes(),(root/'src/catmaster_backpack/routing'/name).read_bytes())

if __name__=='__main__':unittest.main()
