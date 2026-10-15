"""Benchmark novelty guards, with no provider, network or installation scans."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

PATH = Path(__file__).resolve().parents[1]/'benchmarks/market-blind/novelty_gateway.py'
SPEC = importlib.util.spec_from_file_location('market_blind_novelty',PATH)
novelty = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(novelty)


class BaseMarket:
    def __init__(self, gateway, connection):
        self.gateway,self.connection = gateway,connection
        self.data = Path(connection['data_root'])
        self.ranked = []
        self.granted = []
        self.keys = ['new-key']

    def portable_guidance_fit(self, plan):
        self.ranked = list(plan['skills'])
        return bool(self.ranked)

    def prepare(self, arguments):
        plan = {'name':'new-plugin','skills':[{'name':'Existing'}]}
        accepted = self.portable_guidance_fit(plan)
        return {'status':'prepared' if accepted else 'setup_required',
                'components':{'skills':len(plan['skills'])}}

    def view(self, plan):
        return {'name':plan['name']}

    def connect_skills(self, plan):
        self.granted.extend(plan['skills'])

    def bound_skill_keys(self, token):
        return self.keys

    def bound_skill_context(self, token):
        return {'keys':self.keys,'need':'original task','validation':None}


class NoveltyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.store = self.run/'case/store'
        self.store.mkdir(parents=True,mode=0o700)
        self.inventory_path = self.run/'installed-before.json'
        self.write(self.inventory_path,{'names':['Existing','Unconsidered private baseline name'],
                                        'records':[{'path':'must never be scanned'}]})
        self.descriptor = self.store/'codex-public-gateway-test.json'
        self.binding = {'version':2,'enabled':True,'data_root':str(self.store),'project_root':None}
        self.write(self.descriptor,self.binding)
        self.connection = {**self.binding,'_descriptor':str(self.descriptor)}
        self.digest = hashlib.sha256(self.inventory_path.read_bytes()).hexdigest()
        self.inventory = novelty.Inventory(self.inventory_path,self.digest,self.descriptor)
        self.items = {'new-key':{'name':'New'},'old-key':{'name':'Existing'}}
        self.gateway = SimpleNamespace(public_access=SimpleNamespace(registry=lambda data:{'items':self.items}))
        self.market = novelty.novel_market(BaseMarket,self.inventory)(self.gateway,self.connection)

    def write(self,path,value):
        path.write_text(json.dumps(value));path.chmod(0o600)

    def protocol(self, result=None):
        return SimpleNamespace(Market=BaseMarket,
            dispatch=Mock(return_value=result or {'status':'selected','name':'New','content':'new guidance'}),
            tool_catalog=lambda gateway:[{'name':'acquire_skill','inputSchema':{
                'properties':{'need':{},'market_selection':{}},'required':['need']}}])

    def test_filter_preserves_all_eligible_candidates_and_order(self):
        rows = [{'name':'Alpha','path':'a'},{'name':'publisher:EXISTING','path':'old'},
                {'name':'Beta','path':'b'},{'name':'Gamma','path':'c'}]
        plan = {'name':'new-plugin','skills':rows.copy()}
        self.assertTrue(self.market.portable_guidance_fit(plan))
        self.assertEqual(self.market.ranked,[rows[0],rows[2],rows[3]])
        self.assertEqual(plan['skills'],self.market.ranked)
        self.assertEqual(plan['excluded_existing'],['publisher:EXISTING'])
        self.assertEqual(self.market.view(plan)['excluded_existing'],['publisher:EXISTING'])
        self.assertNotIn('Unconsidered private baseline name',json.dumps(self.market.view(plan)))

    def test_new_plugin_with_only_existing_leaf_is_rejected_and_not_counted(self):
        result = self.market.prepare({'kind':'plugin','need':'ordinary unchanged need'})
        self.assertEqual(result['status'],'setup_required')
        self.assertEqual(result['components']['skills'],0)
        self.assertEqual(result['excluded_existing'],['Existing'])
        self.assertEqual(self.market.ranked,[])
        self.assertEqual(self.market.granted,[])

    def test_connect_rechecks_before_any_grant(self):
        with self.assertRaisesRegex(ValueError,'benchmark_existing_skill_excluded'):
            self.market.connect_skills({'skills':[{'name':'New'},{'name':'Existing'}]})
        self.assertEqual(self.market.granted,[])
        self.market.connect_skills({'skills':[{'name':'New'}]})
        self.assertEqual(self.market.granted,[{'name':'New'}])

    def test_old_grant_cannot_be_reintroduced_by_later_acquire(self):
        self.assertEqual(self.market.bound_skill_keys('receipt'),['new-key'])
        self.market.keys = ['new-key','old-key']
        with self.assertRaisesRegex(ValueError,'benchmark_existing_skill_excluded'):
            self.market.bound_skill_keys('receipt')
        with self.assertRaisesRegex(ValueError,'benchmark_existing_skill_excluded'):
            self.market.bound_skill_context('receipt')

    def test_acquire_requires_market_receipt_and_checks_name_before_disclosure(self):
        protocol = self.protocol({'status':'selected','name':'Existing','content':'must not disclose'})
        original = protocol.dispatch
        novelty.install(protocol,SimpleNamespace(Market=BaseMarket),self.inventory)
        with self.assertRaisesRegex(ValueError,'benchmark_market_selection_required'):
            protocol.dispatch(self.gateway,self.connection,None,self.market,'acquire_skill',{'need':'ordinary'})
        original.assert_not_called()
        with self.assertRaisesRegex(ValueError,'benchmark_existing_skill_excluded'):
            protocol.dispatch(self.gateway,self.connection,None,self.market,'acquire_skill',
                              {'need':'ordinary','market_selection':'receipt'})
        original.assert_called_once()
        required = protocol.tool_catalog(self.gateway)[0]['inputSchema']['required']
        self.assertEqual(required,['need','market_selection'])

    def test_eligible_acquire_preserves_arguments_and_original_result(self):
        result = {'status':'selected','name':'New','content':'new guidance'}
        protocol = self.protocol(result)
        original = protocol.dispatch
        novelty.install(protocol,SimpleNamespace(Market=BaseMarket),self.inventory)
        arguments = {'need':'original user need stays unchanged','market_selection':'receipt'}
        self.assertIs(protocol.dispatch(self.gateway,self.connection,None,self.market,'acquire_skill',arguments),result)
        original.assert_called_once_with(self.gateway,self.connection,None,self.market,'acquire_skill',arguments)

    def test_inventory_digest_and_exact_connection_binding_are_enforced(self):
        with self.assertRaisesRegex(ValueError,'benchmark_inventory_digest_mismatch'):
            novelty.Inventory(self.inventory_path,'0'*64,self.descriptor)
        other = {**self.connection,'_descriptor':str(self.store/'other.json')}
        with self.assertRaisesRegex(ValueError,'benchmark_inventory_binding_mismatch'):
            self.inventory.check(other)
        self.write(self.inventory_path,{'names':[]})
        with self.assertRaisesRegex(ValueError,'benchmark_inventory_digest_mismatch'):
            self.market.bound_skill_keys('receipt')

    def test_changed_descriptor_or_nonprivate_snapshot_is_rejected(self):
        self.write(self.descriptor,{**self.binding,'enabled':False})
        with self.assertRaisesRegex(ValueError,'benchmark_connection_changed'):
            self.inventory.check(self.connection)
        self.inventory_path.chmod(0o644)
        with self.assertRaisesRegex(ValueError,'benchmark_snapshot_not_private'):
            novelty.Inventory(self.inventory_path,self.digest,self.descriptor)


if __name__ == '__main__':
    unittest.main()
