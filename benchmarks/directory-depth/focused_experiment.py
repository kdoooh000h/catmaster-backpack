"""Frozen failed-only/new current-shortlist A/B; no capability execution.

References are offline gates and scoring data only. A send contains the raw
task and full candidate descriptions, never reference labels or retrieval gold.
Unknown transport/usage is a terminal observation, with no resume or replay.
"""
import argparse
import json
from pathlib import Path
import re
import time

import semantic_experiment as X
import independent_current as I
import focused_current as F
from bilingual_terms import BilingualDictionary
from experiment import JevHierarchyProvider, read, write_once
from semantic_index import digest, load as load_semantic

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARMS = ['full_independent', 'focused']
LIMITS = {'max_calls': 30, 'max_tokens': 320000, 'max_seconds': 180,
          'call_timeout_seconds': 20, 'attempts': 1, 'retries': 0}


def sources():
    paths = list(HERE.glob('*.py')) + [ROOT/'core/jev_hierarchy_provider.py']
    if (HERE/'focused_cases.json').exists():
        paths.append(HERE/'focused_cases.json')
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}


def coverage(case, recall, arm):
    if arm not in ARMS:
        raise ValueError('unknown_arm')
    pool, short = recall['pool'], recall['shortlist']
    missing = [n for n, group in enumerate(case['pending_groups']) if not set(group) & set(pool)]
    current = bool(set(case['acceptable_current_ids']) & set(short))
    primary_current = case['primary_current_id'] in short
    primary_later = [p in pool for p in case['primary_pending_ids']]
    valid = (recall.get('status') == 'recalled' and bool(short)
             and len(pool) == len(set(pool)) and len(short) == len(set(short))
             and set(short) <= set(pool) and len(pool) <= 384
             and len(short) <= (48 if arm == 'focused' else 256)
             and (arm != 'full_independent' or short == pool))
    return {'eligible': bool(valid and current and not missing),
            'current_in_shortlist': current, 'missing_later_groups': missing,
            'missing_groups': ([] if current else [0]) + [n+1 for n in missing],
            'primary_current_in_shortlist': primary_current,
            'primary_later_in_pool': primary_later,
            'missing_primary': ([case['primary_current_id']] if not primary_current else [])
                               + [p for p, kept in zip(case['primary_pending_ids'], primary_later) if not kept],
            'pool_size': len(pool), 'shortlist_size': len(short)}


def grade(case, result, recall):
    """Prospective requirement groups control success; anchors are diagnostic."""
    current = result.get('status') == 'selected' and result.get('choice') in case['acceptable_current_ids']
    covered = (bool(set(case['acceptable_current_ids']) & set(recall['shortlist']))
               and all(set(g) & set(result.get('retained_candidates', [])) for g in case['pending_groups']))
    anchors = (case['primary_current_id'] in recall['shortlist']
               and set(case['primary_pending_ids']) <= set(result.get('retained_candidates', [])))
    legacy = case.get('legacy_acceptable_current_ids', case['acceptable_current_ids'])
    return {'correct_current': bool(current), 'all_required_retained': bool(covered),
            'omission_safe_pass': bool(current and covered), 'strict_pass': bool(current and covered and anchors),
            'all_primary_references_retained': bool(anchors),
            'strict_anchor_pass': bool(current and anchors and result.get('choice') == case['primary_current_id']),
            'legacy_correct_current': bool(result.get('status') == 'selected' and result.get('choice') in legacy)}


def historical_cases(previous, bundle):
    """Read only frozen ancestry; new repository fixtures are not past trials."""
    paths, visited, cursor = set(), set(), Path(previous).resolve()
    while True:
        if cursor in visited:
            raise ValueError('cyclic_previous_trials')
        visited.add(cursor)
        paths.add(cursor/'plan.json')
        if (cursor/'cases.json').exists():
            paths.add(cursor/'cases.json')
        prior = read(cursor/'plan.json')
        if not prior.get('previous'):
            break
        cursor = Path(prior['previous']).resolve()
    if (Path(bundle)/'cases.json').exists():
        paths.add(Path(bundle)/'cases.json')
    history = []
    def collect(value):
        if isinstance(value, dict):
            if isinstance(value.get('id'), str) and isinstance(value.get('need'), str):
                history.append(value)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    for path in sorted(paths):
        if path.name == 'cases.json':
            collect(read(path))
    return history, {str(path): digest(path) for path in sorted(paths)}


def validate_cases(selected, previous, rows):
    old = {c['id']: c for c in read(previous/'cases.json')}
    summary = read(previous/'live/summary.json')
    if summary['stop'] != 'completed':
        raise ValueError('previous_run_incomplete')
    failed = {r['case'] for r in summary['rows'] if r['arm'] == 'hybrid_independent' and not r['strict_pass']}
    if not isinstance(selected, list) or not selected:
        raise ValueError('invalid_cases')
    if len({c['id'] for c in selected}) != len(selected) or len({c['need'].strip().casefold() for c in selected}) != len(selected):
        raise ValueError('duplicate_case')
    historical, _ = historical_cases(previous, Path(read(previous/'plan.json')['bundle']))
    old_needs = {c['need'].strip().casefold() for c in historical}
    old_ids = {c['id'] for c in historical}
    if {c['id'] for c in selected if c['stratum'] == 'failed'} != failed:
        raise ValueError('failed_scope_changed')
    by_id = {r['id']: r for r in rows}
    for case in selected:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', case['id']) or not case['need'].strip():
            raise ValueError('invalid_case_identity')
        if case['stratum'] == 'failed':
            if case['need'] != old[case['id']]['need']:
                raise ValueError('old_need_changed')
        elif case['stratum'] == 'new':
            if case['id'] in old_ids or case['need'].strip().casefold() in old_needs:
                raise ValueError('prior_case_replayed')
        else:
            raise ValueError('unknown_stratum')
        groups = [case['acceptable_current_ids']] + case['pending_groups']
        if any(not g or len(set(g)) != len(g) or not set(g) <= set(by_id) for g in groups):
            raise ValueError('invalid_reference_group')
        if (case['primary_current_id'] not in groups[0]
                or len(case['primary_pending_ids']) != len(case['pending_groups'])
                or any(p not in g for p, g in zip(case['primary_pending_ids'], case['pending_groups']))):
            raise ValueError('invalid_primary_reference')
        if 'later_requirements' in case and len(case['later_requirements']) != len(case['pending_groups']):
            raise ValueError('missing_later_reference')
        if not set(case.get('legacy_acceptable_current_ids', [])) <= set(by_id):
            raise ValueError('unknown_legacy_reference')
        for reference in case.get('references', []):
            import hashlib
            if hashlib.sha256(by_id[reference['id']]['description'].encode()).hexdigest() != reference['description_sha256']:
                raise ValueError('reference_changed')
    return selected


def specification(arm, rows, recall, need):
    return (F.specification if arm == 'focused' else I.specification)(rows, recall['shortlist'], need)


def select(arm, rows, recall, need, call):
    return F.select(rows, recall, need, call) if arm == 'focused' else I.select(rows, recall['pool'], need, call)


def freeze(previous, root, cases_path, bundle):
    previous, root, cases_path, bundle = [Path(p).resolve() for p in (previous, root, cases_path, bundle)]
    prior = read(previous/'plan.json')
    for path, sha in prior.get('locks', {}).items():
        if digest(path) != sha:
            raise ValueError('previous_external_input_changed')
    for path, sha in prior.get('frozen_sha256', {}).items():
        if digest(previous/path) != sha:
            raise ValueError('previous_frozen_input_changed')
    # Compare only previously recorded sources, not the expanded new file set.
    for path, sha in prior.get('source_sha256', {}).items():
        if digest(ROOT/path) != sha:
            raise ValueError('previous_source_changed')
    if Path(prior['bundle']).resolve() != bundle or digest(bundle/'catalog.json') != prior['catalog_sha256']:
        raise ValueError('previous_catalog_changed')
    if digest(prior['executable']) != prior['executable_sha256']:
        raise ValueError('provider_changed')
    rows = read(bundle/'catalog.json')
    case_document = read(cases_path)
    selected = validate_cases(case_document.get('cases') if isinstance(case_document, dict) else case_document, previous, rows)
    _, history_locks = historical_cases(previous, bundle)
    aligned = previous.parent/'aligned'
    manifest = aligned/'model-manifest.json'
    model = read(manifest)
    index_lock = read(aligned/'index/index.json')
    external = [cases_path, root/'cedict.txt', manifest, aligned/'index/index.json', aligned/'index/vectors.npy',
                previous/'plan.json', previous/'cases.json', previous/'live/summary.json', Path(prior['executable']), bundle/'catalog.json']
    external += [Path(model['snapshot'])/name for name in index_lock['model_files']]
    # Hash before local encoding and ensure no input changed during the freeze.
    locks = {str(p.resolve()): digest(p) for p in external}
    locks.update(history_locks)
    source_hashes = sources()
    out = root/'trial-new'
    out.mkdir(mode=0o700, exist_ok=False)
    started = time.monotonic()
    semantic = load_semantic(bundle/'catalog.json', manifest, aligned/'index')
    load_seconds = time.monotonic()-started
    started = time.monotonic()
    dictionary = BilingualDictionary(path=root/'cedict.txt')
    dictionary_seconds = time.monotonic()-started
    started = time.monotonic()
    lexical, structured, open_lexical = X.SearchIndex(rows), X.StructuredIndex(rows), X.OpenLexicalIndex(rows)
    focused = F.FocusedIndex(rows, dictionary, semantic)
    local_index_seconds = time.monotonic()-started
    audits = []
    try:
        for case in selected:
            base = X.F.repair_recall(structured, case['need'], structured.search(case['need'], lexical.search(case['need'])))['recall']
            hybrid = semantic.search(case['need'], open_lexical.search(case['need'], base, per_kind=3), per_kind=3)
            recalls = {'full_independent': {**hybrid, 'shortlist': list(hybrid['pool'])},
                       'focused': focused.search(case['need'], hybrid)}
            checks = {}
            for arm, recall in recalls.items():
                checks[arm] = coverage(case, recall, arm)
                if checks[arm]['eligible']:
                    spec, state, _ = specification(arm, rows, recall, case['need'])
                    checks[arm]['payload_bytes'] = len(json.dumps({'spec': spec, 'state': state}, ensure_ascii=False).encode())
            write_once(out/(case['id']+'.recall.json'), {'recalls': recalls, 'checks': checks})
            audits.append({'case': case['id'], 'stratum': case['stratum'], **checks})
    finally:
        for index in (lexical, structured, open_lexical, focused):
            index.close()
    if locks != {p: digest(p) for p in locks} or source_hashes != sources():
        raise ValueError('input_changed_during_freeze')
    write_once(out/'cases.json', selected)
    write_once(out/'preflight.json', audits)
    plan = {'version': 1, 'arms': ARMS, 'previous': str(previous), 'bundle': str(bundle),
            'case_order': [c['id'] for c in selected], 'final_gate': .7, **LIMITS,
            'executable': prior['executable'], 'executable_sha256': prior['executable_sha256'],
            'source_sha256': source_hashes, 'locks': locks,
            'frozen_sha256': {p.name: digest(p) for p in out.glob('*.json')},
            'index_load_seconds': load_seconds,
            'dictionary_load_seconds': dictionary_seconds, 'local_index_startup_seconds': local_index_seconds,
            'acceptance': 'Acceptable current in shortlist; each mandatory later group in reservoir; provider current confidence >=0.7. Primary anchors are separate diagnostics, never prospective vetoes.',
            'difference': 'Fresh unchanged lexical/structured repair + open lexical/dense per-kind 3 full pool versus dictionary/current focused shortlist and additive later reservoir.',
            'budget_basis': 'Pre-send reserve = UTF-8 payload bytes/2 rounded up + question count*80 +2500; conservative estimate, not a guarantee of actual token use. Unknown usage/outcome stops without replay.',
            'limits': 'Failed-only plus authored new needs; local encoder and metadata selection only. Runtime capability execution and backend model revision unobservable.'}
    write_once(out/'plan.json', plan)
    return out


def verify(out):
    out = Path(out)
    plan = read(out/'plan.json')
    if plan['source_sha256'] != sources():
        raise ValueError('frozen_sources_changed')
    for path, sha in plan['locks'].items():
        if digest(path) != sha:
            raise ValueError('external_input_changed')
    for path, sha in plan['frozen_sha256'].items():
        if digest(out/path) != sha:
            raise ValueError('frozen_input_changed')
    if (plan['arms'] != ARMS or plan['final_gate'] != .7
            or any(plan.get(k) != v for k, v in LIMITS.items())):
        raise ValueError('frozen_policy_changed')
    if digest(plan['executable']) != plan['executable_sha256']:
        raise ValueError('provider_changed')
    return plan, Path(plan['bundle'])


verify_frozen = verify


def token_reserve(spec, state):
    size = len(json.dumps({'spec': spec, 'state': state}, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    return (size+1)//2 + len(spec['questions'])*80 + 2500


def known_usage(transport):
    return (len(transport) == 1 and transport[0].get('outcome') == 'completed'
            and all(type(transport[0].get(k)) is int and transport[0][k] >= 0 for k in ('input_tokens', 'output_tokens')))


def run(output, *, max_calls=None, max_tokens=None):
    out = Path(output)
    plan, bundle = verify(out)
    plan = dict(plan)
    for key, value in [('max_calls', max_calls), ('max_tokens', max_tokens)]:
        if value is not None:
            if type(value) is not int or not 0 <= value <= plan[key]:
                raise ValueError('invalid_run_cap')
            plan[key] = value
    live = out/'live'
    live.mkdir(mode=0o700, exist_ok=False)
    write_once(live/'run-limits.json', {key: plan[key] for key in LIMITS})
    started = time.monotonic()
    spent = ordinal = 0
    completed, provider, active = [], None, None
    stop = 'completed'
    try:
        rows, selected = read(bundle/'catalog.json'), read(out/'cases.json')
        provider = JevHierarchyProvider({'executable': plan['executable'], 'timeout_seconds': plan['call_timeout_seconds']},
                                        deadline=started+plan['max_seconds'])
        for number, case in enumerate(selected):
            info = read(out/(case['id']+'.recall.json'))
            shift = number % 2
            for arm in ARMS[shift:]+ARMS[:shift]:
                recall = info['recalls'][arm]
                check = coverage(case, recall, arm)
                offset, began, invoked = len(provider.calls), time.monotonic(), False
                active = {'case': case['id'], 'arm': arm}

                def invoke(stage, spec, state):
                    nonlocal spent, ordinal, invoked
                    if stage != 'final' or invoked or len(provider.calls) != offset:
                        raise RuntimeError('one_call_contract')
                    if not coverage(case, recall, arm)['eligible']:
                        raise RuntimeError('preflight_gate_changed')
                    if time.monotonic() >= started+plan['max_seconds']:
                        raise RuntimeError('time_budget_stop')
                    reserve = token_reserve(spec, state)
                    if ordinal >= plan['max_calls'] or spent+reserve > plan['max_tokens']:
                        raise RuntimeError('budget_stop')
                    invoked = True
                    ordinal += 1
                    stem = live/(case['id']+'--'+arm)
                    write_once(str(stem)+'.pending.json', {'ordinal': ordinal, 'spec': spec, 'state': state, 'reserved_tokens': reserve})
                    before = len(provider.calls)
                    try:
                        raw = provider.noul(spec, state)
                    except Exception as error:
                        write_once(str(stem)+'.error.json', {'error': str(error), 'transport': provider.calls[before:]})
                        raise
                    transport = provider.calls[before:]
                    write_once(str(stem)+'.done.json', {'answer': raw, 'transport': transport})
                    if not known_usage(transport):
                        raise RuntimeError('unknown_usage_or_outcome')
                    spent += transport[0]['input_tokens']+transport[0]['output_tokens']
                    return raw

                if check['eligible']:
                    result = select(arm, rows, recall, case['need'], invoke)
                else:
                    result = {'status': 'preflight_failed', 'choice': None, 'confidence': None,
                              'retained_candidates': recall['pool'], 'final_pool_size': len(recall['shortlist'])}
                wall = time.monotonic()-began
                transport = provider.calls[offset:]
                item = {'case': case['id'], 'arm': arm, 'stratum': case['stratum'],
                        'kind_stratum': case.get('kind_stratum'), 'language': case.get('language'),
                        'result': result, 'coverage': check, **grade(case, result, recall),
                        'calls': len(transport), 'tokens': sum(t['input_tokens']+t['output_tokens'] for t in transport),
                        'retrieval_seconds': recall['seconds'], 'dispatch_seconds': wall,
                        'selector_seconds': recall['seconds']+wall, 'transport': transport}
                write_once(live/(case['id']+'--'+arm+'.json'), item)
                completed.append(item)
                active = None
                if spent > plan['max_tokens']:
                    raise RuntimeError('actual_token_budget_exceeded')
    except Exception as error:
        stop = str(error)
    transport = provider.calls if provider is not None else []
    summary = {'stop': stop, 'rows': completed, 'calls': len(transport), 'attempted_sends': ordinal,
               'known_tokens': sum(t.get('input_tokens', 0)+t.get('output_tokens', 0) for t in transport),
               'transport': transport, 'interrupted': active, 'wall_seconds': time.monotonic()-started}
    write_once(live/'summary.json', summary)
    print(json.dumps({'stop': stop, 'calls': len(transport), 'known_tokens': summary['known_tokens']}), flush=True)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['freeze', 'run'])
    parser.add_argument('--previous'); parser.add_argument('--root'); parser.add_argument('--cases')
    parser.add_argument('--bundle'); parser.add_argument('--output')
    parser.add_argument('--max-calls', type=int); parser.add_argument('--max-tokens', type=int)
    args = parser.parse_args()
    if args.operation == 'freeze':
        if not all((args.previous, args.root, args.cases, args.bundle)):
            parser.error('freeze requires --previous --root --cases --bundle')
        print(freeze(args.previous, args.root, args.cases, args.bundle))
    else:
        if not args.output:
            parser.error('run requires --output')
        run(args.output, max_calls=args.max_calls, max_tokens=args.max_tokens)
