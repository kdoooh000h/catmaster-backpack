"""Reconcile saved public receipts offline; never makes a model/network call."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

from source_preflight import save
from ranking_policy import preferences
from merged_catalog import merged, directory


def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def analyze(snapshot, ranking_probe, cases, output):
    snapshot, cases = Path(snapshot), Path(cases)
    source = read(snapshot / 'report.json')
    started = time.perf_counter()
    rows, canonical = merged(snapshot)
    dedup_seconds = time.perf_counter() - started
    catalog_directory = directory(canonical)
    # No reviewed equivalence evidence or valid rank data was observed. Correct
    # behavior is visibility preservation, not arbitrary name-based pruning.
    started = time.perf_counter()
    preferred = preferences(canonical, [], now=time.time())
    preference_seconds = time.perf_counter() - started
    if preferred['visible_ids'] != [r['id'] for r in canonical]:
        raise ValueError('unknown_rank_changed_visibility')
    frozen_cases = read(cases)
    if len(frozen_cases) != 5: raise ValueError('comparison_case_set_changed')
    rank_keys = []
    def walk(value, file):
        if isinstance(value, dict):
            for k, v in value.items():
                if any(s in k.lower() for s in ('rank', 'growth', 'trend', 'installs', 'downloads', 'stars')):
                    rank_keys.append({'file': file, 'key': k})
                walk(v, file)
        elif isinstance(value, list):
            for v in value: walk(v, file)
    for path in sorted(snapshot.glob('plugin-*.json')):
        walk(read(path), path.name)
    registry_pages = sorted(snapshot.glob('registry-page-*.json'))
    received = sum(len(read(path)['servers']) for path in registry_pages)
    registry = next(r for r in source['sources'] if r['source'] == 'registry')
    if received != registry['received']: raise ValueError('registry_receipt_count_mismatch')
    raw_need_hash = hashlib.sha256(json.dumps([c['need'] for c in frozen_cases], ensure_ascii=False).encode()).hexdigest()
    result = {'version': 1, 'status': 'preflight_blocked_live_comparison_not_run',
        'source_read_seconds': source['seconds'], 'source_coverage': source['sources'],
        'plugin_internal_skills_as_candidates': 0,
        'catalog_policy': catalog_directory,
        'complete_source_records': len(rows), 'canonical_records': len(canonical),
        'exact_duplicates_merged': len(rows)-len(canonical), 'kinds': dict(Counter(r['kind'] for r in canonical)),
        'dedup_seconds': dedup_seconds, 'preference_seconds': preference_seconds,
        'rank_records': sum(r.get('rank') is not None for r in canonical),
        'growth_records': sum(r.get('growth') is not None for r in canonical),
        'native_plugin_raw_ranking_fields': rank_keys,
        'ranking_api': read(ranking_probe),
        'mcp_registry': {'pages': len(registry_pages), 'received': received, 'complete': registry['status'] == 'complete',
                         'partial_rows_used_for_selection': False, 'automatic_retry': False},
        'comparison': {'case_ids': [c['id'] for c in frozen_cases], 'case_sha256': sha(cases),
            'raw_need_sha256': raw_need_hash, 'arms': ['accepted_adaptive_directory', 'dedup_rank_growth'],
            'final_confidence': .7, 'current_and_mandatory_later_coverage_required': True,
            'live_rows_completed': 0, 'selection_model_calls': 0, 'selection_tokens': 0,
            'accuracy': None, 'latency_difference': None, 'token_difference': None,
            'unknown_rank_offline_visibility_equal': True,
            'limitation': 'Same five raw needs frozen. Score against predeclared required operations and accepted alternatives in this expanded universe; old repository IDs alone cannot establish expanded-catalog accuracy.'},
        'blockers': ['MCP Registry snapshot is incomplete within the 180-second read budget.',
            'No comparable rank/growth measurements in the observed source metadata; official skills.sh API requires authentication.',
            'Candidate categories are still incomplete; pending items remain visible and cannot be dropped.'],
        'not_changed': ['Daily runtime, source activation and connection settings', 'Concurrent upgrade worktree'],
        'scope': 'Merged public task directory with standalone Skills, whole plugins and MCP services; no plugin-internal Skill candidates, execution or model accuracy claim.',
        'evidence_sha256': {p.name: sha(p) for p in sorted(snapshot.glob('*.json')) if p.name != 'native-skills.json'}}
    save(output, result)
    print(json.dumps({k: result[k] for k in ('status', 'complete_source_records', 'canonical_records',
        'exact_duplicates_merged', 'kinds', 'rank_records', 'growth_records', 'mcp_registry')}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for field in ('snapshot', 'ranking-probe', 'cases', 'output'): parser.add_argument('--'+field, required=True)
    a = parser.parse_args()
    analyze(a.snapshot, a.ranking_probe, a.cases, a.output)
