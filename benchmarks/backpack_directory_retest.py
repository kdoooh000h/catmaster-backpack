"""One-shot, routing-only retest of the nine frozen public requirements.

Use the selected Python environment/PYTHONPATH to choose the package under test.
This harness never refreshes a directory, acquires guidance, or invokes business
tools. Every output file is created exclusively; an existing run cannot resume.
Stage PENDING receipts are durable before entering the real Jev provider. A
missing completion receipt means unknown, never permission to resend.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import time


CASE_IDS = (
    "schema_actual", "region_actual", "text_actual", "design_mixed", "schema_zh",
    "info_synonym", "backend_mixed", "absent_geology", "absent_language",
)
DELIVERY_MODE_KEY = "_delivery_mode"
DELIVERY_MODES = {"direct_result", "guided_workflow", "either"}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def identity(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    allow_nan=False).encode()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_once(path, value):
    """No replacement or retry; fsync before a possible external send."""
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(Path(path).parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def frozen_cases(value):
    rows = value.get("mcp", []) + value.get("route_only", [])
    if tuple(row.get("id") for row in rows) != CASE_IDS:
        raise ValueError("expected_exact_nine_frozen_cases_in_original_order")
    # Preserve exact need, gold order and stratum. Business arguments are neither
    # sent nor needed for routing; the complete original JSON is frozen too.
    result = [{k: row[k] for k in ("id", "kind", "gold", "stratum", "need")} for row in rows]
    for row in result:
        if (not isinstance(row["need"], str) or not row["need"].strip()
                or row["kind"] not in {None, "skill", "tool", "resource", "command"}
                or not isinstance(row["gold"], list)
                or any(not isinstance(name, str) or not name for name in row["gold"])
                or (row["kind"] is None) != (not row["gold"])):
            raise ValueError("invalid_frozen_case")
    return result


def gold_ids(case, catalog):
    return {key for key, entry in catalog.items()
            if entry["kind"] == case["kind"] and entry["name"] in case["gold"]}


def probability(value):
    return type(value) in (int, float) and 0 <= value <= 1 and math.isfinite(value)


def stage_gates(module):
    hierarchy = module.select_hierarchical.__globals__
    common = hierarchy.get("RETENTION_PROBABILITY")
    return {
        "roots": getattr(module, "ROOT_GATE", hierarchy.get("ROOT_RETENTION_PROBABILITY", common)),
        "leaves": getattr(module, "LEAF_GATE", hierarchy.get("LEAF_RETENTION_PROBABILITY", common)),
        "hierarchy_default_final": hierarchy.get("FINAL_CONFIDENCE_GATE"),
        "effective_final": module.FINAL_GATE,
        "plugin_final": module.FINAL_GATE,
        "membership": module.MEMBERSHIP_GATE,
        "secondary_membership": getattr(module, "SECONDARY_MEMBERSHIP_GATE", None),
        "delivery_mode": module.FINAL_GATE if hasattr(module, "_DeliveryProvider") else None,
        "candidate_limit": hierarchy.get("FINAL_CANDIDATE_LIMIT"),
    }


def retention(spec, traces, gold, gates, *, final_ids=None):
    """Expand memberships as set unions, including stops before final Choice."""
    leaves = {node["id"]: set(node["members"]) for node in spec["leaves"]}
    roots = {node["id"]: set().union(*(leaves[key] for key in node["children"]))
             for node in spec["roots"]}
    stages = {"roots": None, "leaves": None, "pool": None}
    for trace in traces:
        stage = trace.get("stage")
        if stage not in {"roots", "leaves"}:
            continue
        nodes = roots if stage == "roots" else leaves
        answers = trace.get("answers")
        offered = trace.get("offered_ids", list(answers or {}))
        gate = gates[stage]
        valid = (not trace.get("discarded_by_selector", False)
                 and ("delivery_mode" not in trace or trace["delivery_mode"].get("type") == "choice")
                 and isinstance(answers, dict) and set(answers) == set(offered)
                 and set(offered) <= set(nodes) and probability(gate)
                 and all(isinstance(a, dict) and a.get("type") == "noul"
                         and probability(a.get("noul")) for a in answers.values()))
        offered_union = set().union(*(nodes[key] for key in offered if key in nodes))
        retained = [key for key in offered if answers[key]["noul"] >= gate] if valid else None
        union = set().union(*(nodes[key] for key in retained)) if valid else None
        stages[stage] = {
            "offered_ids": offered, "retained_ids": retained,
            "offered_union_count": len(offered_union),
            "retained_union_count": len(union) if union is not None else None,
            "gold_offered": bool(gold & offered_union) if gold else None,
            "gold_retained": bool(gold & union) if gold and union is not None else None,
            "valid_response": valid,
        }
        if stage == "leaves" and valid:
            stages["pool"] = {"union_count": len(union), "gold_retained": bool(gold & union) if gold else None,
                              "candidate_ids": sorted(union), "presented_to_choice": False}
    if final_ids is not None:
        union = set(final_ids) - {"none"}
        stages["pool"] = {"union_count": len(union), "gold_retained": bool(gold & union) if gold else None,
                          "candidate_ids": sorted(union), "presented_to_choice": True}
    return stages


def grade(case, result, catalog):
    entry = catalog.get(result.get("choice"), {}) if result.get("status") == "selected" else {}
    # Baseline SUMMARY omits selected IDs; its checked kind/name remain evidence.
    kind, name = entry.get("kind", result.get("kind")), entry.get("name", result.get("name"))
    selected = result.get("status") == "selected"
    right = selected and kind == case["kind"] and name in case["gold"]
    negative = not case["gold"]
    return {"kind": kind, "name": name, "accepted_right_kind_and_name": right,
            "wrong_accepted": selected and not right,
            "strict_negative_pass": result.get("status") == "none" if negative else None,
            "negative_safe_abstention": result.get("status") == "unavailable" if negative else None,
            "passed": result.get("status") == "none" if negative else right}


def usage_totals(rows):
    known = []
    partial_incoming = partial_outgoing = partial_cases = 0
    for row in rows:
        usage = row.get("usage")
        if (isinstance(usage, dict) and usage.get("available") is True
                and all(type(usage.get(k)) is int and usage[k] >= 0
                        for k in ("input_tokens", "output_tokens"))):
            known.append(usage)
        else:
            # A later unknown call must not hide known earlier stage usage.
            transports = [receipt for trace in row.get("traces", []) for receipt in trace.get("transport", [])]
            incoming = [receipt["input_tokens"] for receipt in transports
                        if type(receipt.get("input_tokens")) is int and receipt["input_tokens"] >= 0]
            outgoing = [receipt["output_tokens"] for receipt in transports
                        if type(receipt.get("output_tokens")) is int and receipt["output_tokens"] >= 0]
            partial_incoming += sum(incoming)
            partial_outgoing += sum(outgoing)
            partial_cases += bool(incoming or outgoing)
    incoming = sum(row["input_tokens"] for row in known) + partial_incoming
    outgoing = sum(row["output_tokens"] for row in known) + partial_outgoing
    complete = len(known) == len(rows)
    return {"known_input_tokens": incoming, "known_output_tokens": outgoing,
            "known_total_tokens": incoming + outgoing, "known_cases": len(known),
            "partial_usage_cases": partial_cases,
            "unknown_cases": len(rows) - len(known), "complete": complete,
            "total_tokens": incoming + outgoing if complete else None}


def summary(rows):
    positive = [row for row in rows if row["expected_kind"] is not None]
    negative = [row for row in rows if row["expected_kind"] is None]
    stage_retention = {}
    for stage in ("roots", "leaves", "pool"):
        values = [row["retention"][stage].get("gold_retained") if row["retention"].get(stage) is not None else None
                  for row in positive]
        stage_retention[stage] = {"retained": sum(value is True for value in values),
                                  "dropped": sum(value is False for value in values),
                                  "unobserved": sum(value is None for value in values)}
    return {"case_count": len(rows), "positive_count": len(positive), "negative_count": len(negative),
            "passed_cases": sum(row["passed"] for row in rows),
            "accepted_right_kind_and_name": sum(row["accepted_right_kind_and_name"] for row in rows),
            "wrong_accepted": sum(row["wrong_accepted"] for row in rows),
            "strict_negative_passes": sum(row["strict_negative_pass"] is True for row in negative),
            "negative_safe_abstentions": sum(row["negative_safe_abstention"] is True for row in negative),
            "positive_gold_retention": stage_retention,
            "usage": usage_totals(rows),
            "known_selector_seconds": sum(row["selector_seconds"] for row in rows if row["selector_seconds"] is not None),
            "unknown_selector_duration_cases": sum(row["selector_seconds"] is None for row in rows),
            "case_elapsed_seconds": sum(row["case_elapsed_seconds"] for row in rows)}


def baseline_rows(cases, evidence, catalog, spec):
    by_id = {row["case"]: row for row in evidence["summary"]["cases"]}
    if set(by_id) != set(CASE_IDS):
        raise ValueError("baseline_summary_case_mismatch")
    rows = []
    # The frozen baseline numeric retention gate was .20 (the `yes` flags
    # describe .50 and are not the selector's retention rule). Final acceptance
    # is taken from SUMMARY, never re-decided using today's gates.
    gates = {"roots": .20, "leaves": .20, "plugin_final": .65,
             "hierarchy_final": .60, "membership": .20, "candidate_limit": 96}
    for case in cases:
        source = by_id[case["id"]]
        decision = evidence["decisions"][case["id"]]
        traces = []
        for index, row in enumerate(decision["decisions"]):
            if row.get("method") == "noul":
                traces.append({"stage": "roots" if index == 0 else "leaves", "answers": row["answers"]})
        final_presented = any(row.get("method") == "choice" for row in decision["decisions"])
        final_ids = decision["candidate_ids"] if final_presented else None
        result = {"case": case["id"], "expected_kind": case["kind"], "expected_names": case["gold"],
                  "stratum": case["stratum"], "status": source["status"],
                  "routing": source.get("routing"), "usage": source.get("selector_usage"),
                  "selector_seconds": source.get("selector_seconds"),
                  "case_elapsed_seconds": source["full_seconds"],
                  "case_duration_scope": "old_protocol_flow_including_acquisition_and_business_where_attempted",
                  "retention": retention(spec, traces, gold_ids(case, catalog), gates, final_ids=final_ids)}
        result.update(grade(case, source, catalog))
        rows.append(result)
    return rows, gates


class TraceProvider:
    """Transparent recorder around the selected package's real provider."""
    def __init__(self, real, folder, directory):
        self.real, self.folder, self.directory = real, folder, directory
        self.traces = []
        self.final_ids = None

    @property
    def calls(self):
        return self.real.calls

    def call(self, stage, method, args, offered_ids, *, question_ids=None):
        number = len(self.traces) + 1
        trace = {"stage": stage, "offered_ids": list(offered_ids), "started_at": utc()}
        if question_ids is not None:
            trace["question_ids"] = list(question_ids)
        self.traces.append(trace)
        prefix = self.folder / f"{number:02d}-{stage}"
        write_once(str(prefix) + "-PENDING.json", {**trace, "status": "pending_unknown_no_replay"})
        started = time.monotonic()
        before = len(self.real.calls)
        try:
            raw = method(*args)
        except Exception:
            trace["outcome"] = "failed_or_unknown_no_replay"
            raise
        else:
            trace["outcome"] = "returned"
            # Only typed routing fields; never unsolicited provider metadata.
            if stage in {"roots", "leaves", "singleton"}:
                answers = raw.get("answers") if isinstance(raw, dict) else None
                trace["answers"] = {key: {"type": "noul" if answer.get("type") == "noul" else "invalid",
                                          "noul": answer["noul"] if probability(answer.get("noul")) else None}
                                    for key, answer in (answers or {}).items()
                                    if key in offered_ids and isinstance(answer, dict)}
                expected = question_ids if question_ids is not None else offered_ids
                trace["response_keys_match"] = isinstance(answers, dict) and set(answers) == set(expected)
                if DELIVERY_MODE_KEY in expected:
                    mode = answers.get(DELIVERY_MODE_KEY) if isinstance(answers, dict) else None
                    valid = (isinstance(mode, dict) and mode.get("type") == "choice"
                             and isinstance(mode.get("choice"), str)
                             and mode.get("choice") in DELIVERY_MODES and probability(mode.get("confidence")))
                    trace["delivery_mode"] = {"type": "choice" if valid else "invalid",
                                              "choice": mode["choice"] if valid else None,
                                              "confidence": mode["confidence"] if valid else None}
                if not trace["response_keys_match"]:
                    trace.pop("answers", None)
            elif isinstance(raw, dict):
                trace["answer"] = {"type": "choice" if raw.get("type") == "choice" else "invalid",
                                   "choice": raw["choice"] if raw.get("choice") in offered_ids else None,
                                   "confidence": raw["confidence"] if probability(raw.get("confidence")) else None}
            return raw
        finally:
            trace["elapsed_seconds"] = time.monotonic() - started
            trace["transport"] = [{k: r[k] for k in ("completed", "outcome", "seconds", "failure_code", "input_tokens", "output_tokens") if k in r}
                                  for r in self.real.calls[before:]]
            # Interrupts/crashes deliberately leave a pending receipt alone.
            if "outcome" in trace:
                write_once(str(prefix) + "-COMPLETE.json", trace)

    def noul(self, spec, state):
        questions = list(spec["questions"])
        ids = [key for key in questions if key != DELIVERY_MODE_KEY]
        stage = "roots" if set(ids) == set(self.directory.root_ids) else "leaves" if set(ids) <= set(self.directory.leaf_ids) else "singleton"
        return self.call(stage, self.real.noul, (spec, state), ids, question_ids=questions)

    def choose(self, question, state, choices):
        self.final_ids = list(choices)
        return self.call("final", self.real.choose, (question, state, choices), self.final_ids)


def source_evidence(module):
    modules = {"plugin_directory": Path(module.__file__),
               "hierarchical_choice_routing": Path(module.select_hierarchical.__globals__["__file__"]),
               "jev_hierarchy_provider": Path(module.JevHierarchyProvider.__init__.__globals__["__file__"]),
               "template": Path(module.__file__).parent / "routing/task-directory-template.json"}
    return {name: {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for name, path in modules.items()}


def compare_reports(left, right):
    """Compare recorded current selectors; never compare legacy full flows."""
    if left.get("same_need_and_gold_sha256") != right.get("same_need_and_gold_sha256") or not left.get("same_need_and_gold_sha256"):
        raise ValueError("comparison_requires_same_frozen_needs_and_gold")
    rows = [report["current"]["cases"] for report in (left, right)]
    if any(tuple(row["case"] for row in group) != CASE_IDS for group in rows):
        raise ValueError("comparison_requires_exact_nine_current_cases")
    if any(row.get("case_duration_scope") != "routing_only" for group in rows for row in group):
        raise ValueError("comparison_requires_routing_only_current_reports")
    comparable_time = [index for index in range(len(CASE_IDS))
                       if all(type(group[index].get("selector_seconds")) in (int, float)
                              and math.isfinite(group[index]["selector_seconds"])
                              and group[index]["selector_seconds"] >= 0 for group in rows)]
    comparable_usage = [index for index in range(len(CASE_IDS))
                        if all(usage_totals([group[index]])["complete"] for group in rows)]
    results = []
    for report, group in zip((left, right), rows):
        selector_summary = summary(group)
        selector_summary.pop("case_elapsed_seconds")
        results.append({"source_version": report["source_version"], "gates": report["gates"],
                        "summary": selector_summary,
                        "matched_selector_seconds": sum(group[index]["selector_seconds"] for index in comparable_time),
                        "matched_usage": usage_totals([group[index] for index in comparable_usage]) if comparable_usage else None,
                        "cases": [{key: row[key] for key in ("case", "status", "kind", "name", "passed", "wrong_accepted", "selector_seconds")}
                                  for row in group]})
    return {"schema": "catmaster-public-directory-retest-comparison/v1",
            "scope": "same_nine_current_selectors_routing_only",
            "same_need_and_gold_sha256": left["same_need_and_gold_sha256"],
            "matched_selector_case_ids": [CASE_IDS[index] for index in comparable_time],
            "unmatched_selector_duration_cases": len(CASE_IDS) - len(comparable_time),
            "matched_usage_case_ids": [CASE_IDS[index] for index in comparable_usage],
            "baseline": results[0], "current": results[1],
            "limits": "Single observed run per version; no legacy full-flow timing or native-host acceptance comparison."}


def run(args):
    # Delayed import ensures `--help` never loads a provider. Package selection
    # belongs to the invoking environment, not a hard-coded installed checkout.
    from catmaster_backpack import plugin_directory as module

    case_path = Path(args.baseline_cases).resolve()
    base_root = case_path.parents[2]
    paths = {
        "cases": case_path,
        "summary": Path(args.baseline_summary or case_path.parent / "SUMMARY.json"),
        "catalog": Path(args.baseline_catalog or base_root / "PUBLIC-CATALOG.json"),
        "classification": Path(args.baseline_classification or base_root / "CLASSIFICATION.json"),
        "directory": Path(args.baseline_directory or base_root / "store/capability-directory.json"),
    }
    evidence = {name: load(path) for name, path in paths.items()}
    cases = frozen_cases(evidence["cases"])
    evidence["decisions"] = {case["id"]: load(case_path.parent / (case["id"] + "-DECISIONS.json")) for case in cases}
    catalog = load(args.catalog)
    if not isinstance(catalog, dict) or not catalog:
        raise ValueError("invalid_public_catalog")
    for entry in catalog.values():
        module.wire(entry)  # Enforce the package's secret-free metadata boundary.
    if any(module.SECRET.search(case["need"]) for case in cases):
        raise ValueError("sensitive_case_need")
    if any(case["gold"] and not gold_ids(case, catalog) for case in cases):
        raise ValueError("expected_kind_and_name_missing_from_catalog")
    # A fair retest requires the same metadata and stable IDs. `package` points
    # may move between isolated stores, so exclude only that local locator.
    public = lambda entries: {key: {k: v for k, v in entry.items() if k != "package"} for key, entry in entries.items()}
    if public(catalog) != public(evidence["catalog"]):
        raise ValueError("public_catalog_changed_since_frozen_baseline")
    current_cache = module.read_cache(args.store)
    if set(current_cache.get("entries", {})) != set(catalog):
        raise ValueError("isolated_store_catalog_mismatch")
    # A non-ready cache is still valid evidence: selection can return unavailable
    # without calling Jev. Never refresh or repair inside the experiment.
    try:
        directory = module.available_directory(args.store, catalog)
    except (OSError, ValueError, TypeError, KeyError):
        directory = None
    gates = stage_gates(module)
    if any(gates[key] is None for key in ("roots", "leaves")):
        raise ValueError("unobservable_selector_gates")
    old_rows, old_gates = baseline_rows(cases, evidence, evidence["catalog"], evidence["directory"]["directory"])
    folder = Path(args.out).resolve()
    folder.mkdir(mode=0o700, parents=False, exist_ok=False)
    frozen = {"schema": "catmaster-public-directory-retest/v1", "created_at": utc(),
              "baseline_version": args.baseline_version, "source_version": args.source_version,
              "scope": "same_nine_frozen_needs_routing_only", "business_invocations": 0,
              "native_host_acceptance": "unobservable", "resume": "forbidden_for_all_existing_runs",
              "baseline_inputs": {key: {"path": str(path), "sha256": identity(evidence[key])} for key, path in paths.items()},
              "source": source_evidence(module), "gates": gates,
              "baseline_gates": old_gates, "baseline_gate_scope": "frozen_0.2.3_source_constants_operator_evidence",
              "cases": cases, "catalog": public(catalog), "directory": current_cache,
              "baseline_evidence": evidence}
    write_once(folder / "CASES-BEFORE-CALLS.json", frozen)
    new_rows = []
    for case in cases:
        case_folder = folder / case["id"]
        case_folder.mkdir(mode=0o700)
        write_once(case_folder / "PENDING.json", {"case": case["id"], "need_sha256": identity(case["need"]),
                                                 "started_at": utc(), "status": "pending_unknown_no_replay"})
        started = time.monotonic()
        providers = []

        def factory(deadline):
            if directory is None:
                raise ValueError("directory_changed_after_freeze")
            provider = TraceProvider(module.JevHierarchyProvider(module.CONFIG, deadline=deadline), case_folder, directory)
            providers.append(provider)
            return provider

        result = module.select(case["need"], catalog, args.store, provider_factory=factory)
        elapsed = time.monotonic() - started
        traces = [trace for provider in providers for trace in provider.traces]
        routing = result.get("routing") or {}
        if routing.get("reason") == "deadline_exceeded" and traces:
            # A response returned after the deadline is observable, but the
            # selector did not accept its probabilities as retained nodes.
            traces[-1]["discarded_by_selector"] = True
        pool = providers[-1].final_ids if providers else None
        case_retention = retention(current_cache["directory"], traces, gold_ids(case, catalog), gates, final_ids=pool) \
            if directory is not None else {"roots": None, "leaves": None, "pool": None}
        if pool is None and case_retention["pool"] is not None and "delivery_mode" in result:
            # Leaf membership union is observable; a wrapper may filter it and
            # then stop before Choice. Do not report that raw union as the
            # actual filtered final pool or duplicate the filtering policy.
            case_retention["leaf_union_before_filter"] = case_retention["pool"]
            case_retention["pool"] = None
        row = {"case": case["id"], "expected_kind": case["kind"], "expected_names": case["gold"],
               "stratum": case["stratum"], "status": result["status"],
               "reason": result.get("reason"), "routing": result.get("routing"),
               "delivery_mode": result.get("delivery_mode"),
               "usage": result.get("usage"), "selector_seconds": result.get("elapsed_seconds"),
               "case_elapsed_seconds": elapsed, "case_duration_scope": "routing_only",
               "traces": traces, "retention": case_retention,
               **grade(case, result, catalog)}
        write_once(case_folder / "COMPLETE.json", {"status": "finished_no_replay", "result": result, "row": row})
        new_rows.append(row)
    report = {"schema": frozen["schema"], "source_version": args.source_version,
              "baseline_version": args.baseline_version, "source": frozen["source"], "gates": gates,
              "scope": frozen["scope"], "business_invocations": 0,
              "mcp_business_evidence": "reused_frozen_results_unaffected_not_replayed_or_reverified",
              "native_host_acceptance": "unobservable",
              "duration_comparison": "selector_seconds_comparable_where_known; old_full_seconds_includes_other_work",
              "baseline": {"gates": old_gates, "classification": evidence["classification"], "summary": summary(old_rows), "cases": old_rows},
              "current": {"classification": current_cache.get("summary"), "summary": summary(new_rows), "cases": new_rows},
              "same_need_and_gold_sha256": identity(cases)}
    write_once(folder / "REPORT.json", report)
    return report


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    for name in ("store", "catalog", "baseline-cases", "out", "baseline-version", "source-version"):
        result.add_argument("--" + name)
    for name in ("baseline-summary", "baseline-catalog", "baseline-classification", "baseline-directory"):
        result.add_argument("--" + name)
    result.add_argument("--compare-reports", nargs=2, metavar=("OLD_REPORT", "NEW_REPORT"),
                        help="Read two current routing reports and print a selector-only comparison; makes no calls.")
    result.add_argument("--comparison-out", help="Optional new immutable comparison JSON path.")
    return result


def main():
    command = parser()
    args = command.parse_args()
    try:
        if args.compare_reports:
            report = compare_reports(*(load(path) for path in args.compare_reports))
            if args.comparison_out:
                write_once(args.comparison_out, report)
            print(json.dumps(report, ensure_ascii=False))
            return
        required = ("store", "catalog", "baseline_cases", "out", "baseline_version", "source_version")
        if any(getattr(args, key) is None for key in required):
            command.error("routing run requires --store, --catalog, --baseline-cases, --out, --baseline-version and --source-version")
        if args.comparison_out:
            command.error("--comparison-out requires --compare-reports")
        report = run(args)
    except FileExistsError:
        raise SystemExit("Existing run or receipt: resume/replay is forbidden. Reconcile its evidence before any new experiment.") from None
    except (ValueError, OSError, KeyError, TypeError):
        raise SystemExit("Retest stopped; inspect immutable receipts. No retry or resume was attempted.") from None
    print(json.dumps({"report": str(Path(args.out).resolve() / "REPORT.json"),
                      "baseline": report["baseline"]["summary"], "current": report["current"]["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
