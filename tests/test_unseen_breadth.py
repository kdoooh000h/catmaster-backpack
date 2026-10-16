from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks/directory-depth'))
import unseen_breadth_experiment as X
import test_final_contrast as T

CASE={'id':'synthetic','need':'当前处理文档，然后读 PDF','kind_stratum':'skill','language':'zh',
      'acceptable_current_ids':T.POOL[:2],'pending_groups':[[T.POOL[2]]],
      'primary_current_id':T.POOL[0],'primary_pending_ids':[T.POOL[2]]}


def result(choice,pool,status='selected'):
    return {'status':status,'choice':choice,'traces':[{'pool':pool}]}


class BreadthGradeTests(unittest.TestCase):
    def test_predeclared_alternative_is_accepted_but_not_primary_success(self):
        graded=X.grade(CASE,result(T.POOL[1],T.POOL))
        self.assertTrue(graded['omission_safe_pass'])
        self.assertTrue(graded['all_primary_references_retained'])
        self.assertFalse(graded['strict_anchor_pass'])

    def test_missing_later_group_cannot_be_hidden_by_correct_current(self):
        graded=X.grade(CASE,result(T.POOL[0],T.POOL[:2]))
        self.assertTrue(graded['correct_current'])
        self.assertFalse(graded['all_required_retained'])
        self.assertFalse(graded['omission_safe_pass'])

    def test_later_choice_and_abstention_fail(self):
        for candidate in [result(T.POOL[2],T.POOL),result(None,T.POOL,'abstain')]:
            self.assertFalse(X.grade(CASE,candidate)['omission_safe_pass'])

    def test_current_alternative_does_not_erase_missing_primary_anchor(self):
        graded=X.grade(CASE,result(T.POOL[1],T.POOL[1:]))
        self.assertTrue(graded['omission_safe_pass'])
        self.assertFalse(graded['all_primary_references_retained'])

    def test_single_step_and_every_trace_are_checked(self):
        case={**CASE,'pending_groups':[],'primary_pending_ids':[]}
        self.assertTrue(X.grade(case,result(T.POOL[0],T.POOL[:1]))['omission_safe_pass'])
        r=result(T.POOL[0],T.POOL);r['traces'].append({'pool':[]})
        self.assertFalse(X.grade(case,r)['omission_safe_pass'])

    def test_frozen_requests_cover_types_languages_and_are_distinct(self):
        requests=json.loads(X.REQUESTS.read_text())['cases']
        refs=json.loads(X.REFERENCES.read_text())['cases']
        self.assertEqual(len({c['need'] for c in requests}),12)
        self.assertEqual({c['id'] for c in requests},{c['id'] for c in refs})
        for field,values in [('kind_stratum',['skill','plugin','mcp']),('language',['zh','synonym','mixed'])]:
            self.assertTrue(all(sum(c[field]==v for c in requests)==4 for v in values))
        self.assertEqual(sum(bool(r['pending_groups']) for r in refs),9)


class BreadthRunnerTests(unittest.TestCase):
    def fake_run(self,failure=False,cap=50000,eligible=True):
        seen=[]
        class Provider:
            def __init__(self,*args,**kwargs):self.calls=[]
            def noul(self,spec,state):
                seen.append((spec,state))
                if failure:
                    self.calls.append({'outcome':'unknown','seconds':.001})
                    raise RuntimeError('unknown_no_replay')
                self.calls.append({'outcome':'completed','input_tokens':10,'output_tokens':2,'seconds':.001})
                return T.answer(next(iter(spec['questions']['answer']['criteria'])),.8)
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);bundle=out/'bundle';bundle.mkdir()
            def save(path,data):path.write_text(json.dumps(data))
            save(bundle/'catalog.json',T.ROWS);save(bundle/'question.json',{'question':T.QUESTION})
            save(out/'cases.json',[CASE]);save(out/'synthetic.recall.json',{'eligible_for_live':eligible,'basis':'synthetic','recall':{'pool':T.POOL,'seconds':.01}})
            plan={'executable':'unused','call_timeout_seconds':20,'max_seconds':120,'max_calls':2,'max_tokens':cap}
            with patch.object(X,'verify_frozen',return_value=(plan,bundle)),patch.object(X.C.E,'JevHierarchyProvider',Provider),contextlib.redirect_stdout(io.StringIO()):X.run(out)
            summary=json.loads((out/'live/summary.json').read_text())
            with patch.object(X,'verify_frozen',return_value=(plan,bundle)),self.assertRaises(FileExistsError):X.run(out)
        return summary,seen

    def test_pair_uses_same_raw_need_one_call_and_no_reference_leak(self):
        summary,seen=self.fake_run()
        self.assertEqual(summary['stop'],'completed');self.assertEqual(summary['calls'],2)
        self.assertEqual(summary['known_tokens'],24)
        self.assertTrue(all(r['omission_safe_pass'] for r in summary['rows']))
        self.assertTrue(all(state=={'task':CASE['need']} for _,state in seen))
        self.assertTrue(all(len(spec['questions'])==1 for spec,_ in seen))

    def test_known_omission_is_counted_without_live_calls(self):
        summary,seen=self.fake_run(eligible=False)
        self.assertEqual(seen,[]);self.assertEqual(len(summary['rows']),2)
        self.assertTrue(all(not r['omission_safe_pass'] for r in summary['rows']))

    def test_unknown_send_never_retries(self):
        summary,seen=self.fake_run(failure=True)
        self.assertEqual(summary['stop'],'unknown_no_replay');self.assertEqual(len(seen),1)
        self.assertEqual(summary['rows'],[])

    def test_budget_stop_precedes_send(self):
        summary,seen=self.fake_run(cap=0)
        self.assertEqual(summary['stop'],'budget_stop');self.assertEqual(seen,[])


if __name__=='__main__':unittest.main()
