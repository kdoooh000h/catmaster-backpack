"""Typed delivery contract constrains final candidates without another round."""
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from catmaster_backpack.plugin_directory import _DeliveryProvider

class Real:
    def __init__(self,mode='direct_result',confidence=.9):self.mode=mode;self.confidence=confidence;self.calls=[]
    def noul(self,spec,state):
        self.calls.append(spec)
        return {'answers':{key:({'type':'choice','choice':self.mode,'confidence':self.confidence}
                               if key=='_delivery_mode' else {'type':'noul','noul':.9})
                           for key in spec['questions']}}

class DeliveryTests(unittest.TestCase):
    def provider(self,mode='direct_result',confidence=.9):
        p=_DeliveryProvider(Real(mode,confidence),{'tool':{'kind':'tool'},'guide':{'kind':'skill'},'resource':{'kind':'resource'}})
        spec={'questions':{'root':{'type':'noul'}}};state={'task':'Original unchanged task'}
        r=p.noul(spec,state)
        self.assertEqual(set(r['answers']),{'root'});self.assertEqual(set(spec['questions']),{'root'})
        self.assertEqual(state,{'task':'Original unchanged task'})
        return p
    def test_high_confidence_mode_filters_exact_kinds(self):
        pool={'tool':'Tool','guide':'Guide','resource':'Resource','none':'None'}
        self.assertEqual(self.provider().candidates(pool),{'tool':'Tool','resource':'Resource','none':'None'})
        self.assertEqual(self.provider('guided_workflow').candidates(pool),{'guide':'Guide','none':'None'})
    def test_uncertain_or_either_never_excludes_a_kind(self):
        pool={'tool':'Tool','guide':'Guide','none':'None'}
        for mode,confidence in [('direct_result',.69),('guided_workflow',.69),('either',1)]:
            self.assertEqual(self.provider(mode,confidence).candidates(pool),pool)
    def test_inclusive_mode_gate_and_no_extra_provider_round(self):
        p=self.provider(confidence=.70);p.noul({'questions':{'leaf':{'type':'noul'}}},{'task':'Same'})
        self.assertEqual(len(p.calls),2);self.assertNotIn('_delivery_mode',p.calls[1]['questions'])
        self.assertEqual(p.candidates({'tool':'Tool','guide':'Guide','none':'None'}),{'tool':'Tool','none':'None'})
    def test_invalid_mode_answers_fail_without_retry(self):
        for mode,confidence in [('bad',.9),('direct_result',True),('direct_result',float('nan')),('direct_result',1.1)]:
            p=_DeliveryProvider(Real(mode,confidence),{})
            with self.assertRaisesRegex(ValueError,'invalid_delivery_response'):p.noul({'questions':{'root':{'type':'noul'}}},{'task':'Same'})
            self.assertEqual(len(p.calls),1)

if __name__=='__main__':unittest.main()
