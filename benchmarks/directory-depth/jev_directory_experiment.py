"""Frozen failed-only comparison: local shortlist versus Jev directory relevance.

Gold is used only after selection. Both arms dispatch from structural/budget
checks alone. Receipts precede every send; unknown outcome/usage ends the trial.
No capability execution, automatic replay, encoder download or fallback.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time

import focused_current as F
import focused_experiment as P
import jev_directory_route as D
import jev_directory_tree as T
import semantic_experiment as X
from bilingual_terms import BilingualDictionary
from experiment import JevHierarchyProvider, read, write_once
from semantic_index import digest, load as load_semantic

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARMS = ['program_shortlist', 'jev_directories']
LIMITS = {'max_calls': 80, 'max_tokens': 300000, 'max_seconds': 240,
          'call_timeout_seconds': 20, 'attempts': 1, 'retries': 0}
STOPPING = 'Structural/budget stops only; no reference or grade controls dispatch or future cases. Unknown outcome/usage ends the entire trial, without retry or fallback.'
historical_cases = P.historical_cases
token_reserve = P.token_reserve
known_usage = P.known_usage


def sources():
    paths = list(HERE.glob('*.py')) + list(HERE.glob('*cases.json')) + [ROOT/'core/jev_hierarchy_provider.py']
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(set(paths))}


def validate_cases(selected, previous, rows):
    """Require exactly the seven failed raw needs and three unseen raw needs."""
    previous = Path(previous)
    prior_cases = read(previous/'cases.json')
    old = {c['id']: c for c in prior_cases}
    summary = read(previous/'live/summary.json')
    if summary.get('stop') != 'completed':
        raise ValueError('previous_run_incomplete')
    focused = [r for r in summary['rows'] if r['arm'] == 'focused']
    if len({r['case'] for r in focused}) != len(focused) or {r['case'] for r in focused} != set(old):
        raise ValueError('invalid_previous_focused_rows')
    if any(type(r.get('omission_safe_pass')) is not bool for r in focused):
        raise ValueError('invalid_previous_grade')
    failed = {r['case'] for r in focused if r['omission_safe_pass'] is False}
    passed = {r['case'] for r in focused if r['omission_safe_pass'] is True}
    if len(failed) != 7 or len(passed) != 8:
        raise ValueError('previous_scope_changed')
    if not isinstance(selected, list) or len(selected) != 10 or any(not isinstance(c, dict) for c in selected):
        raise ValueError('expected_seven_failed_three_new')
    if (len({c['id'] for c in selected}) != len(selected)
            or len({c['need'].strip().casefold() for c in selected}) != len(selected)):
        raise ValueError('duplicate_case')
    if {c['id'] for c in selected if c.get('stratum') == 'failed'} != failed:
        raise ValueError('failed_scope_changed')
    if sum(c.get('stratum') == 'new' for c in selected) != 3:
        raise ValueError('expected_seven_failed_three_new')
    historical, _ = historical_cases(previous, Path(read(previous/'plan.json')['bundle']))
    old_needs = {c['need'].strip().casefold() for c in historical}
    old_ids = {c['id'] for c in historical}
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
        if any(not g or len(g) != len(set(g)) or not set(g) <= set(by_id) for g in groups):
            raise ValueError('invalid_reference_group')
        if (case['primary_current_id'] not in groups[0]
                or len(case['primary_pending_ids']) != len(case['pending_groups'])
                or any(p not in g for p, g in zip(case['primary_pending_ids'], case['pending_groups']))):
            raise ValueError('invalid_primary_reference')
        if len(case.get('later_requirements', [])) != len(case['pending_groups']):
            raise ValueError('missing_later_reference')
        for reference in case.get('references', []):
            row = by_id[reference['id']]
            if hashlib.sha256(row['description'].encode()).hexdigest() != reference['description_sha256']:
                raise ValueError('reference_changed')
            if any(reference[k] != row[k] for k in ('name', 'kind', 'description') if k in reference):
                raise ValueError('reference_metadata_changed')
    return selected


def structural_recall(recall, rows):
    """Reference-free guard. Missing gold must never prevent a send."""
    pool, short = recall.get('pool', []), recall.get('shortlist', [])
    identifiers = {r['id'] for r in rows}
    valid = (recall.get('status') == 'recalled' and bool(short)
             and len(pool) == len(set(pool)) and len(short) == len(set(short))
             and set(short) <= set(pool) <= identifiers and len(pool) <= 384 and len(short) <= 48)
    return {'eligible': bool(valid), 'pool_size': len(pool), 'shortlist_size': len(short),
            'reason': None if valid else 'invalid_or_oversize_recall'}


def grade(case, result, recall=None):
    """Post-call requirement coverage; primary anchors are diagnostics only."""
    retained = result.get('retained_candidates', [])
    current_pool = recall['shortlist'] if recall is not None else retained
    current_available = bool(set(case['acceptable_current_ids']) & set(current_pool))
    later = [bool(set(g) & set(retained)) for g in case['pending_groups']]
    current = (result.get('status') == 'selected' and result.get('choice') in case['acceptable_current_ids']
               and type(result.get('confidence')) in (int, float) and result['confidence'] >= .7)
    primary_current = case['primary_current_id'] in current_pool
    primary_later = [p in retained for p in case['primary_pending_ids']]
    anchors = primary_current and all(primary_later)
    return {'correct_current': bool(current), 'current_in_final_pool': current_available,
            'later_group_coverage': later, 'missing_later_groups': [n for n, kept in enumerate(later) if not kept],
            'all_required_retained': bool(current_available and all(later)),
            'omission_safe_pass': bool(current and current_available and all(later)),
            'primary_current_in_final_pool': primary_current, 'primary_later_in_pool': primary_later,
            'all_primary_references_retained': anchors, 'strict_pass': bool(current and anchors),
            'strict_anchor_pass': bool(current and anchors and result.get('choice') == case['primary_current_id'])}


def previous_inputs(previous, bundle):
    """Verify recorded entries pointwise: newly added source files are allowed."""
    previous, bundle = Path(previous).resolve(), Path(bundle).resolve()
    prior = read(previous/'plan.json')
    for path, sha in prior.get('locks', {}).items():
        if digest(path) != sha:
            raise ValueError('previous_external_input_changed')
    for path, sha in prior.get('frozen_sha256', {}).items():
        if digest(previous/path) != sha:
            raise ValueError('previous_frozen_input_changed')
    for path, sha in prior.get('source_sha256', {}).items():
        if digest(ROOT/path) != sha:
            raise ValueError('previous_source_changed')
    if Path(prior['bundle']).resolve() != bundle:
        raise ValueError('previous_catalog_changed')
    catalog_sha = prior.get('catalog_sha256', prior.get('locks', {}).get(str(bundle/'catalog.json')))
    if not catalog_sha or digest(bundle/'catalog.json') != catalog_sha:
        raise ValueError('previous_catalog_changed')
    if digest(prior['executable']) != prior['executable_sha256']:
        raise ValueError('provider_changed')
    return prior


def baseline_paths(prior):
    """Resolve only the prior locked local model/cache and dictionary."""
    locks = [Path(p) for p in prior['locks']]
    manifests = [p for p in locks if p.name == 'model-manifest.json']
    dictionaries = [p for p in locks if p.name == 'cedict.txt']
    if len(manifests) != 1 or len(dictionaries) != 1:
        raise ValueError('ambiguous_baseline_inputs')
    manifest = manifests[0]
    return manifest, manifest.parent/'index', dictionaries[0]


def freeze(root, previous, cases_path, bundle):
    root, previous, cases_path, bundle = [Path(p).resolve() for p in (root, previous, cases_path, bundle)]
    prior = previous_inputs(previous, bundle)
    rows = read(bundle/'catalog.json')
    document = read(cases_path)
    selected = validate_cases(document.get('cases') if isinstance(document, dict) else document, previous, rows)
    nodes = read(root/'nodes.json')
    tree_report = T.validate(nodes, rows)
    manifest, index_dir, dictionary_path = baseline_paths(prior)
    model, vector_lock = read(manifest), read(index_dir/'index.json')
    external = [cases_path, root/'nodes.json', bundle/'catalog.json', manifest, index_dir/'index.json',
                index_dir/'vectors.npy', dictionary_path, Path(prior['executable']), previous/'plan.json',
                previous/'cases.json', previous/'live/summary.json']
    external += [Path(model['snapshot'])/name for name in vector_lock['model_files']]
    external += [root/name for name in ('tree-precheck.json', 'tree_precheck.json', 'precheck.json', 'tree-plan.json') if (root/name).exists()]
    _, history_locks = historical_cases(previous, bundle)
    locks = {str(p.resolve()): digest(p) for p in external}
    locks.update(history_locks)
    hashes = sources()
    out = root/'trial'
    out.mkdir(mode=0o700, exist_ok=False)
    write_once(out/'cases.json', selected)
    write_once(out/'nodes.json', nodes)
    write_once(out/'tree-precheck.json', tree_report)
    began = time.monotonic()
    semantic = load_semantic(bundle/'catalog.json', manifest, index_dir)
    index_load_seconds = time.monotonic()-began
    began = time.monotonic()
    dictionary = BilingualDictionary(path=dictionary_path)
    dictionary_load_seconds = time.monotonic()-began
    began = time.monotonic()
    lexical, structured, open_lexical = X.SearchIndex(rows), X.StructuredIndex(rows), X.OpenLexicalIndex(rows)
    focused = F.FocusedIndex(rows, dictionary, semantic)
    local_index_startup_seconds = time.monotonic()-began
    audits = []
    try:
        for case in selected:
            began = time.monotonic()
            base = X.F.repair_recall(structured, case['need'], structured.search(case['need'], lexical.search(case['need'])))['recall']
            hybrid = semantic.search(case['need'], open_lexical.search(case['need'], base, per_kind=3), per_kind=3)
            recall = focused.search(case['need'], hybrid)
            fresh_seconds = time.monotonic()-began
            recall['fresh_retrieval_seconds'] = fresh_seconds
            check = structural_recall(recall, rows)
            # Neither grading references nor relevance gold enter preparation.
            write_once(out/(case['id']+'.recall.json'), {'recall': recall, 'structural_check': check})
            audits.append({'case': case['id'], **check, 'fresh_retrieval_seconds': fresh_seconds})
    finally:
        for index in (lexical, structured, open_lexical, focused):
            index.close()
    if any(digest(path) != sha for path, sha in locks.items()) or hashes != sources():
        raise ValueError('input_changed_during_freeze')
    write_once(out/'preflight.json', audits)
    plan = {'version': 1, 'arms': ARMS, 'previous': str(previous), 'bundle': str(bundle),
            'catalog_sha256': digest(bundle/'catalog.json'), 'case_order': [c['id'] for c in selected],
            'final_gate': .7, 'directory_gate': .2, 'per_need_max_calls': 8, **LIMITS,
            'executable': prior['executable'], 'executable_sha256': prior['executable_sha256'],
            'source_sha256': hashes, 'locks': locks,
            'frozen_sha256': {p.name: digest(p) for p in out.glob('*.json')},
            'index_load_seconds': index_load_seconds, 'dictionary_load_seconds': dictionary_load_seconds,
            'local_index_startup_seconds': local_index_startup_seconds, 'stopping_policy': STOPPING,
            'acceptance': 'Provider-reported current confidence >=0.7 and acceptable current; every later requirement group retained. Primary references are separate diagnostics.',
            'budget_basis': 'Before each send reserve ceil(UTF-8 payload bytes/2)+80*question_count+2500. Unknown outcome or usage stops without replay.',
            'runtime_readiness': 'unobservable', 'backend_model_revision': 'unobservable'}
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
    if (plan['arms'] != ARMS or plan['final_gate'] != .7 or plan['directory_gate'] != .2
            or plan['per_need_max_calls'] != 8 or plan['stopping_policy'] != STOPPING
            or any(plan.get(k) != v for k, v in LIMITS.items())):
        raise ValueError('frozen_policy_changed')
    if digest(plan['executable']) != plan['executable_sha256']:
        raise ValueError('provider_changed')
    return plan, Path(plan['bundle'])


verify_frozen = verify


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
    deadline = started+plan['max_seconds']
    spent = ordinal = 0
    completed, provider, active = [], None, None
    stop = 'completed'
    tree_load_seconds = 0.
    selected = read(out/'cases.json')
    schedule = [(case['id'], arm) for number, case in enumerate(selected)
                for arm in ARMS[number % 2:]+ARMS[:number % 2]]
    try:
        rows = read(bundle/'catalog.json')
        began = time.monotonic()
        nodes = read(out/'nodes.json')
        T.validate(nodes, rows)
        tree_load_seconds = time.monotonic()-began
        provider = JevHierarchyProvider({'executable': plan['executable'], 'timeout_seconds': plan['call_timeout_seconds']}, deadline=deadline)
        for number, case in enumerate(selected):
            recall = read(out/(case['id']+'.recall.json'))['recall']
            shift = number % 2
            for arm in ARMS[shift:]+ARMS[:shift]:
                offset, began = len(provider.calls), time.monotonic()
                arm_calls = 0
                stages = []
                active = {'case': case['id'], 'arm': arm}

                def invoke(stage, spec, state):
                    nonlocal spent, ordinal, arm_calls
                    if (not re.fullmatch(r'(final|directory-[1-9][0-9]*-batch-[1-9][0-9]*)', stage)
                            or stage in stages or arm_calls >= (1 if arm == 'program_shortlist' else 8)):
                        raise RuntimeError('stage_call_contract')
                    if time.monotonic() >= deadline:
                        raise RuntimeError('time_budget_stop')
                    reserve = token_reserve(spec, state)
                    if ordinal >= plan['max_calls'] or spent+reserve > plan['max_tokens']:
                        raise RuntimeError('budget_stop')
                    ordinal += 1
                    arm_calls += 1
                    stages.append(stage)
                    stem = live/(case['id']+'--'+arm+'--'+stage)
                    write_once(str(stem)+'.pending.json', {'ordinal': ordinal, 'stage': stage,
                               'spec': spec, 'state': state, 'reserved_tokens': reserve})
                    before = len(provider.calls)
                    try:
                        raw = provider.noul(spec, state)
                    except Exception as error:
                        write_once(str(stem)+'.error.json', {'ordinal': ordinal, 'stage': stage,
                                   'error': str(error), 'transport': provider.calls[before:], 'replay': False})
                        raise
                    transport = provider.calls[before:]
                    write_once(str(stem)+'.done.json', {'ordinal': ordinal, 'stage': stage,
                               'answer': raw, 'transport': transport})
                    if not known_usage(transport):
                        raise RuntimeError('unknown_usage_or_outcome')
                    spent += transport[0]['input_tokens']+transport[0]['output_tokens']
                    if spent > plan['max_tokens']:
                        raise RuntimeError('actual_token_budget_exceeded')
                    return raw

                check = structural_recall(recall, rows) if arm == 'program_shortlist' else {'eligible': True}
                if arm == 'program_shortlist':
                    if check['eligible']:
                        result = F.select(rows, recall, case['need'], invoke)
                    else:
                        result = {'status': 'structural_guard_failed', 'choice': None, 'confidence': None,
                                  'retained_candidates': recall.get('pool', []), 'final_pool_size': len(recall.get('shortlist', [])),
                                  'traces': [{'stage': 'current_shortlist', 'pool': recall.get('shortlist', [])},
                                             {'stage': 'later_reservoir', 'pool': recall.get('pool', [])}]}
                else:
                    result = D.route(nodes, rows, case['need'], invoke)
                wall = time.monotonic()-began
                transport = provider.calls[offset:]
                real_transport = sum(t['seconds'] for t in transport if type(t.get('seconds')) in (int, float))
                local_seconds = max(0., wall-real_transport)
                retrieval_seconds = recall.get('fresh_retrieval_seconds', recall.get('seconds', 0.)) if arm == 'program_shortlist' else 0.
                # Cold tree/model setup stays separate from warm selectors.
                item = {'case': case['id'], 'arm': arm, 'stratum': case['stratum'],
                        'kind_stratum': case.get('kind_stratum'), 'language': case.get('language'),
                        'result': result, 'structural_check': check, **grade(case, result, recall if arm == 'program_shortlist' else None),
                        'calls': len(transport), 'attempted_sends': arm_calls,
                        'tokens': sum(t['input_tokens']+t['output_tokens'] for t in transport),
                        'fresh_retrieval_seconds': retrieval_seconds, 'retrieval_seconds': retrieval_seconds,
                        'real_transport_seconds': real_transport, 'local_routing_seconds': local_seconds,
                        'dispatch_seconds': wall, 'selector_seconds': retrieval_seconds+wall,
                        'transport': transport, 'stages': stages}
                write_once(live/(case['id']+'--'+arm+'.json'), item)
                completed.append(item)
                active = None
    except Exception as error:
        stop = str(error)
    transport = provider.calls if provider is not None else []
    done = {(r['case'], r['arm']) for r in completed}
    known_tokens = sum(t[k] for t in transport for k in ('input_tokens', 'output_tokens') if type(t.get(k)) is int)
    summary = {'stop': stop, 'rows': completed, 'calls': len(transport), 'attempted_sends': ordinal,
               'known_tokens': known_tokens, 'transport': transport, 'interrupted': active,
               'unfinished': [{'case': case, 'arm': arm} for case, arm in schedule if (case, arm) not in done],
               'real_transport_seconds': sum(t['seconds'] for t in transport if type(t.get('seconds')) in (int, float)),
               'wall_seconds': time.monotonic()-started, 'tree_load_seconds': tree_load_seconds,
               'baseline_setup_seconds': {key: plan.get(key) for key in ('index_load_seconds', 'dictionary_load_seconds', 'local_index_startup_seconds')},
               'stopping_policy': STOPPING}
    write_once(live/'summary.json', summary)
    print(json.dumps({'stop': stop, 'calls': len(transport), 'known_tokens': known_tokens}), flush=True)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['freeze', 'run'])
    parser.add_argument('--root'); parser.add_argument('--previous'); parser.add_argument('--cases')
    parser.add_argument('--bundle'); parser.add_argument('--output')
    parser.add_argument('--max-calls', type=int); parser.add_argument('--max-tokens', type=int)
    args = parser.parse_args()
    if args.operation == 'freeze':
        if not all((args.root, args.previous, args.cases, args.bundle)):
            parser.error('freeze requires --root --previous --cases --bundle')
        print(freeze(args.root, args.previous, args.cases, args.bundle))
    else:
        if not args.output:
            parser.error('run requires --output')
        run(args.output, max_calls=args.max_calls, max_tokens=args.max_tokens)
