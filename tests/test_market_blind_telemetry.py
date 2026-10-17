"""Failure accounting for the live blind pilot, with no external calls."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / 'benchmarks/market-blind/summarize.py'
SPEC = importlib.util.spec_from_file_location('blind_summary', PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class TelemetryTests(unittest.TestCase):
    def test_timeout_recovers_observed_usage_without_claiming_full_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            case=Path(temp);(case/'work').mkdir()
            (case/'events.jsonl').write_text(json.dumps({'type':'thread.started','thread_id':'test-thread'})+'\n'+
                json.dumps({'type':'turn.started'})+'\n')
            sessions=case/'home/.codex/sessions';sessions.mkdir(parents=True)
            totals={'input_tokens':100,'cached_input_tokens':80,'output_tokens':10,'reasoning_output_tokens':4}
            row={'timestamp':'2026-10-15T00:00:00Z','type':'event_msg',
                 'payload':{'type':'token_count','info':{'total_token_usage':totals,'last_token_usage':totals}}}
            # Repeated usage notifications must not double count the cumulative total.
            (sessions/'rollout-test-thread.jsonl').write_text((json.dumps(row)+'\n')*2)
            result=module.case_summary(case,set())
            self.assertEqual(result['known_total_tokens'],110)
            self.assertFalse(result['token_coverage_complete'])
            observed=result['native_session_usage']
            self.assertEqual(observed['observed_usage_updates'],1)
            self.assertEqual(observed['noncached_input_tokens'],20)
            self.assertEqual(observed['reasoning_output_tokens'],4)

    def test_completed_turn_and_session_usage_are_not_added(self):
        with tempfile.TemporaryDirectory() as temp:
            case=Path(temp);(case/'work').mkdir()
            totals={'input_tokens':100,'cached_input_tokens':80,'output_tokens':10}
            rows=[{'type':'thread.started','thread_id':'test-thread'},{'type':'turn.started'},
                  {'type':'turn.completed','usage':totals}]
            (case/'events.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            sessions=case/'home/.codex/sessions';sessions.mkdir(parents=True)
            row={'type':'event_msg','payload':{'type':'token_count','info':{'total_token_usage':totals}}}
            (sessions/'rollout-test-thread.jsonl').write_text(json.dumps(row)+'\n')
            result=module.case_summary(case,set())
            self.assertEqual(result['known_total_tokens'],110)
            self.assertTrue(result['token_coverage_complete'])

    def test_missing_usage_keeps_known_subtotal_and_marks_incomplete(self):
        result = module.usage([{'input_tokens': 20, 'output_tokens': 3}, None], 2)
        self.assertEqual(result['known_total_tokens'], 23)
        self.assertEqual(result['calls_with_usage'], 1)
        self.assertFalse(result['complete'])

    def test_cached_input_is_not_added_twice(self):
        result = module.usage([{'input_tokens': 20, 'cached_input_tokens': 15, 'output_tokens': 3}], 1)
        self.assertEqual(result['known_total_tokens'], 23)

    def test_overlapping_waits_are_not_double_counted(self):
        self.assertEqual(module.interval_seconds([(2,5),(3,7),(9,10)]),6)

    def test_native_cache_is_separate_and_missing_cache_is_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            case=Path(temp);(case/'work').mkdir()
            rows=[{'type':'turn.started'},{'type':'turn.completed','usage':{
                'input_tokens':100,'cached_input_tokens':80,'output_tokens':5}}]
            (case/'events.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            value=module.case_summary(case,set())
            self.assertEqual(value['known_total_tokens'],105)
            self.assertEqual(value['native_usage']['noncached_input_tokens'],20)
            del rows[-1]['usage']['cached_input_tokens']
            (case/'events.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            self.assertIsNone(module.case_summary(case,set())['native_usage']['noncached_input_tokens'])

    def test_unanswered_gateway_request_is_not_success(self):
        with tempfile.TemporaryDirectory() as temp:
            case = Path(temp); (case/'work').mkdir()
            (case/'run.json').write_text(json.dumps({'status':'timed_out','elapsed_seconds':360}))
            (case/'backpack-wire.jsonl').write_text(json.dumps({'direction':'in','at':1,'message':{
                'id':1,'method':'tools/call','params':{'name':'invoke_mcp','arguments':{'selection':'opaque'}}}})+'\n')
            value = module.case_summary(case, set())
            self.assertFalse(value['token_coverage_complete'])
            self.assertEqual(value['backpack_calls'][0]['status'], 'no_recorded_response')
            self.assertIsNone(value['acceptance'])

    def test_same_name_is_flagged_and_handle_not_in_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            case=Path(temp); (case/'work').mkdir()
            value={'status':'selected','name':'Already-Here','selection':'opaque-secret'}
            rows=[{'direction':'in','at':1,'message':{'id':1,'method':'tools/call','params':{'name':'acquire_skill','arguments':{'need':'ordinary'}}}},
                  {'direction':'out','at':2,'message':{'id':1,'result':{'content':[{'type':'text','text':json.dumps(value)}]}}}]
            (case/'backpack-wire.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in rows))
            result=module.case_summary(case, {'already-here'})
            self.assertTrue(result['backpack_calls'][0]['preexisting_name'])
            self.assertNotIn('opaque-secret',json.dumps(result))

    def test_transport_retry_does_not_claim_complete_token_accounting(self):
        with tempfile.TemporaryDirectory() as temp:
            case=Path(temp); (case/'work').mkdir()
            rows=[{'type':'turn.started'}, {'type':'error','message':'Reconnecting... stream disconnected'},
                  {'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':2}}]
            (case/'events.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in rows))
            result=module.case_summary(case,set())
            self.assertEqual(result['known_total_tokens'],12)
            self.assertFalse(result['token_coverage_complete'])


if __name__ == '__main__': unittest.main()
