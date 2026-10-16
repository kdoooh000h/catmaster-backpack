import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks/directory-depth'))
import semantic_experiment as X
import test_final_contrast as T
from test_semantic_recall import answer

CASE={'id':'synthetic','need':'现在制作幻灯片，之后处理文档','stratum':'new','kind_stratum':'skill','language':'zh',
      'acceptable_current_ids':[T.POOL[0]],'pending_groups':[[T.POOL[2]]],
      'primary_current_id':T.POOL[0],'primary_pending_ids':[T.POOL[2]]}


class SemanticRunnerTests(unittest.TestCase):
    def trial(self,failed=False,cap=100000,missing=False):
        seen=[]
        class Provider:
            def __init__(self,*a,**kw):self.calls=[]
            def noul(self,spec,state):
                seen.append((spec,state))
                if failed:
                    self.calls.append({'outcome':'unknown','seconds':0});raise RuntimeError('unknown_no_replay')
                self.calls.append({'outcome':'completed','input_tokens':10,'output_tokens':2,'seconds':.01})
                if set(spec['questions'])=={'answer'}:return T.answer(next(iter(spec['questions']['answer']['criteria'])),.8)
                return {'answers':{k:answer('current' if n==0 else 'other') for n,k in enumerate(spec['questions'])}}
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);bundle=out/'bundle';bundle.mkdir()
            def write(p,value):p.write_text(json.dumps(value))
            write(bundle/'catalog.json',[{'name':r['id'],**r} for r in T.ROWS]);write(bundle/'question.json',{'question':T.QUESTION})
            write(out/'cases.json',[CASE]);pool=T.POOL[:2] if missing else T.POOL
            write(out/'synthetic.recall.json',{'recalls':{a:{'pool':pool,'seconds':.1} for a in X.ARMS}})
            plan={'executable':'unused','call_timeout_seconds':20,'max_seconds':240,'max_calls':2,'max_tokens':cap}
            with patch.object(X,'verify',return_value=(plan,bundle)),patch.object(X.C.E,'JevHierarchyProvider',Provider),contextlib.redirect_stdout(io.StringIO()):X.run(out)
            summary=json.loads((out/'live/summary.json').read_text())
            with patch.object(X,'verify',return_value=(plan,bundle)),self.assertRaises(FileExistsError):X.run(out)
        return summary,seen

    def test_one_request_per_arm_raw_need_and_all_later_retained(self):
        summary,seen=self.trial()
        self.assertEqual(summary['stop'],'completed');self.assertEqual(len(seen),2)
        self.assertTrue(all(r['strict_pass'] for r in summary['rows']))
        self.assertTrue(all(state['task']==CASE['need'] for _,state in seen))
        self.assertTrue(all('acceptable_current_ids' not in state for _,state in seen))

    def test_missing_later_prevents_every_send(self):
        summary,seen=self.trial(missing=True)
        self.assertEqual(seen,[]);self.assertEqual(len(summary['rows']),2)
        self.assertTrue(all(not r['strict_pass'] for r in summary['rows']))

    def test_unknown_send_does_not_retry(self):
        summary,seen=self.trial(failed=True)
        self.assertEqual(summary['stop'],'unknown_no_replay');self.assertEqual(len(seen),1)

    def test_budget_checked_before_send(self):
        summary,seen=self.trial(cap=0)
        self.assertEqual(summary['stop'],'budget_stop');self.assertEqual(seen,[])


if __name__=='__main__':unittest.main()
