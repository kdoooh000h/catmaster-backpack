"""Offline accounting/receipt tests, not simulated benchmark acceptance."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest


spec = importlib.util.spec_from_file_location(
    "backpack_directory_retest", Path(__file__).resolve().parents[1] / "benchmarks/backpack_directory_retest.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


class RetestHarnessTests(unittest.TestCase):
    def test_unknown_usage_remains_unknown_but_known_tokens_are_counted(self):
        rows = [{"usage": {"available": True, "input_tokens": 3, "output_tokens": 2}},
                {"usage": None}, {"usage": {"available": False, "input_tokens": None, "output_tokens": None}}]
        totals = harness.usage_totals(rows)
        self.assertEqual(totals["known_total_tokens"], 5)
        self.assertEqual(totals["unknown_cases"], 2)
        self.assertIsNone(totals["total_tokens"])
        self.assertFalse(totals["complete"])

    def test_strict_negative_distinguishes_none_from_safe_abstention(self):
        case = {"kind": None, "gold": []}
        for status in ("unavailable", "error", "abstain"):
            row = harness.grade(case, {"status": status}, {})
            self.assertFalse(row["passed"])
            self.assertFalse(row["strict_negative_pass"])
        self.assertTrue(harness.grade(case, {"status": "none"}, {})["passed"])

    def test_partial_usage_survives_later_unknown_stage(self):
        rows = [{"usage": {"available": False, "input_tokens": None, "output_tokens": None},
                 "traces": [{"transport": [{"input_tokens": 7, "output_tokens": 2}]},
                            {"transport": [{"outcome": "unknown_no_replay"}]}]}]
        totals = harness.usage_totals(rows)
        self.assertEqual(totals["known_total_tokens"], 9)
        self.assertEqual(totals["partial_usage_cases"], 1)
        self.assertEqual(totals["unknown_cases"], 1)
        self.assertIsNone(totals["total_tokens"])

    def test_same_name_wrong_kind_is_wrong_accepted(self):
        case = {"kind": "tool", "gold": ["search_objects"]}
        catalog = {"bad": {"kind": "skill", "name": "search_objects"}}
        row = harness.grade(case, {"status": "selected", "choice": "bad"}, catalog)
        self.assertFalse(row["passed"])
        self.assertTrue(row["wrong_accepted"])

    def test_gold_retention_uses_union_and_survives_pre_choice_stop(self):
        directory = {"roots": [{"id": "r", "children": ["l", "overlap"]}],
                     "leaves": [{"id": "l", "members": ["gold", "other"]},
                                {"id": "overlap", "members": ["gold"]}]}
        traces = [
            {"stage": "roots", "answers": {"r": {"type": "noul", "noul": .15}}},
            {"stage": "leaves", "answers": {"l": {"type": "noul", "noul": .3},
                                                "overlap": {"type": "noul", "noul": .4}}},
        ]
        result = harness.retention(directory, traces, {"gold"}, {"roots": .1, "leaves": .3})
        self.assertTrue(result["roots"]["gold_retained"])
        self.assertTrue(result["leaves"]["gold_retained"])
        self.assertEqual(result["pool"]["union_count"], 2)
        self.assertFalse(result["pool"]["presented_to_choice"])

    def test_root_stop_has_observed_false_and_unobserved_later_stages(self):
        directory = {"roots": [{"id": "r", "children": ["l"]}],
                     "leaves": [{"id": "l", "members": ["gold"]}]}
        traces = [{"stage": "roots", "answers": {"r": {"type": "noul", "noul": .05}}}]
        result = harness.retention(directory, traces, {"gold"}, {"roots": .1, "leaves": .3})
        self.assertFalse(result["roots"]["gold_retained"])
        self.assertIsNone(result["leaves"])
        self.assertIsNone(result["pool"])

    def test_discarded_late_response_is_not_retained_gold(self):
        directory = {"roots": [{"id": "r", "children": ["l"]}],
                     "leaves": [{"id": "l", "members": ["gold"]}]}
        traces = [{"stage": "roots", "discarded_by_selector": True,
                   "answers": {"r": {"type": "noul", "noul": .9}}}]
        result = harness.retention(directory, traces, {"gold"}, {"roots": .1, "leaves": .3})
        self.assertIsNone(result["roots"]["gold_retained"])
        self.assertFalse(result["roots"]["valid_response"])

    def test_unknown_send_has_durable_pending_receipt_before_transport(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            class FailingTransport:
                calls = []
                def noul(self, spec, state):
                    self.pending_seen = (folder / "01-roots-PENDING.json").is_file()
                    raise TimeoutError("unknown")
            real = FailingTransport()
            provider = harness.TraceProvider(real, folder, SimpleNamespace(root_ids=["r"], leaf_ids=["l"]))
            with self.assertRaises(TimeoutError):
                provider.noul({"questions": {"r": {}}}, {})
            self.assertTrue(real.pending_seen)
            receipt = harness.load(folder / "01-roots-COMPLETE.json")
            self.assertEqual(receipt["outcome"], "failed_or_unknown_no_replay")
            with self.assertRaises(FileExistsError):
                harness.write_once(folder / "01-roots-PENDING.json", {})

    def test_interrupt_leaves_pending_without_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            class InterruptedTransport:
                calls = []
                def noul(self, spec, state):
                    raise KeyboardInterrupt()
            provider = harness.TraceProvider(InterruptedTransport(), folder, SimpleNamespace(root_ids=["r"], leaf_ids=["l"]))
            with self.assertRaises(KeyboardInterrupt):
                provider.noul({"questions": {"r": {}}}, {})
            self.assertTrue((folder / "01-roots-PENDING.json").is_file())
            self.assertFalse((folder / "01-roots-COMPLETE.json").exists())

    def test_mode_choice_is_separate_from_root_noul_retention(self):
        with tempfile.TemporaryDirectory() as temporary:
            class RecordedTransport:
                calls = []
                def noul(self, spec, state):
                    return {"answers": {"r": {"type": "noul", "noul": .2},
                                        "_delivery_mode": {"type": "choice", "choice": "direct_result", "confidence": .8}}}
            directory = SimpleNamespace(root_ids=["r"], leaf_ids=["l"])
            provider = harness.TraceProvider(RecordedTransport(), Path(temporary), directory)
            raw = provider.noul({"questions": {"r": {}, "_delivery_mode": {}}}, {})
            trace = provider.traces[0]
            self.assertEqual(trace["stage"], "roots")
            self.assertEqual(trace["offered_ids"], ["r"])
            self.assertEqual(trace["question_ids"], ["r", "_delivery_mode"])
            self.assertTrue(trace["response_keys_match"])
            self.assertEqual(set(trace["answers"]), {"r"})
            self.assertEqual(trace["delivery_mode"], raw["answers"]["_delivery_mode"])
            spec = {"roots": [{"id": "r", "children": ["l"]}],
                    "leaves": [{"id": "l", "members": ["gold"]}]}
            self.assertTrue(harness.retention(spec, provider.traces, {"gold"}, {"roots": .1, "leaves": .3})["roots"]["gold_retained"])

    def test_missing_mode_answer_does_not_validate_full_raw_response(self):
        with tempfile.TemporaryDirectory() as temporary:
            class MissingModeTransport:
                calls = []
                def noul(self, spec, state):
                    return {"answers": {"r": {"type": "noul", "noul": .2}}}
            provider = harness.TraceProvider(MissingModeTransport(), Path(temporary), SimpleNamespace(root_ids=["r"], leaf_ids=["l"]))
            provider.noul({"questions": {"r": {}, "_delivery_mode": {}}}, {})
            trace = provider.traces[0]
            self.assertFalse(trace["response_keys_match"])
            self.assertNotIn("answers", trace)
            self.assertEqual(trace["delivery_mode"]["type"], "invalid")

    def test_final_pool_records_actual_filtered_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            class FinalTransport:
                calls = []
                def choose(self, question, state, choices):
                    return {"type": "choice", "choice": "gold", "confidence": .9}
            provider = harness.TraceProvider(FinalTransport(), Path(temporary), SimpleNamespace(root_ids=["r"], leaf_ids=["l"]))
            provider.choose("Exact question", {}, {"gold": "Tool", "none": "None"})
            self.assertEqual(provider.final_ids, ["gold", "none"])
            spec = {"roots": [{"id": "r", "children": ["l"]}],
                    "leaves": [{"id": "l", "members": ["gold", "guidance"]}]}
            pool = harness.retention(spec, [], {"gold"}, {"roots": .1, "leaves": .3}, final_ids=provider.final_ids)["pool"]
            self.assertEqual(pool["union_count"], 1)
            self.assertEqual(pool["candidate_ids"], ["gold"])
            self.assertTrue(pool["presented_to_choice"])

    def test_report_comparison_uses_only_matched_selector_seconds(self):
        def report(multiplier):
            rows = []
            for index, key in enumerate(harness.CASE_IDS):
                rows.append({"case": key, "expected_kind": "tool", "status": "unavailable", "kind": None,
                             "name": None, "passed": False, "wrong_accepted": False,
                             "accepted_right_kind_and_name": False, "case_duration_scope": "routing_only",
                             "selector_seconds": None if index == 0 and multiplier == 1 else multiplier,
                             "case_elapsed_seconds": 1000, "usage": None,
                             "retention": {"roots": None, "leaves": None, "pool": None}})
            return {"same_need_and_gold_sha256": "same-frozen-identity", "source_version": str(multiplier),
                    "gates": {}, "current": {"cases": rows}}
        old, new = report(1), report(2)
        comparison = harness.compare_reports(old, new)
        self.assertEqual(comparison["baseline"]["matched_selector_seconds"], 8)
        self.assertEqual(comparison["current"]["matched_selector_seconds"], 16)
        self.assertEqual(comparison["matched_selector_case_ids"], list(harness.CASE_IDS[1:]))
        self.assertEqual(comparison["matched_usage_case_ids"], [])
        self.assertIsNone(comparison["baseline"]["matched_usage"])
        self.assertNotIn("case_elapsed_seconds", comparison["baseline"]["summary"])
        old["current"]["cases"][0]["case_duration_scope"] = "legacy_full_flow"
        with self.assertRaises(ValueError):
            harness.compare_reports(old, new)
        old["same_need_and_gold_sha256"] = "different"
        with self.assertRaises(ValueError):
            harness.compare_reports(old, new)

    def test_frozen_cases_accept_only_original_nine_order(self):
        rows = [{"id": key, "kind": "tool", "gold": ["name"], "stratum": "mixed", "need": "Exact need"}
                for key in harness.CASE_IDS]
        self.assertEqual(harness.frozen_cases({"mcp": rows[:3], "route_only": rows[3:]}), rows)
        rows.reverse()
        with self.assertRaises(ValueError):
            harness.frozen_cases({"mcp": rows[:3], "route_only": rows[3:]})


if __name__ == "__main__":
    unittest.main()
