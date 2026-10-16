"""Freeze public inputs before the one-shot pilot. No model calls or installation."""
import argparse
import hashlib
from pathlib import Path

from experiment import ARMS, human_tree, identity, read, schedule, semantic_tree, structure, write_once

CASE_IDS = ['zh_llm_cost', 'zh_vendor_scorecard', 'syn_custom_controller',
            'syn_upgrade_moment', 'mix_financial_model', 'mix_multi_jira_then_qms',
            'zh_quote_control', 'mix_cancel_control']
ARCHIVE_SHA = '30ce857856ee03a5940b1382e56ca1f9b209028f1e2d8087b7a71bf6705c23c9'


def validate(rows, raw, taxonomy, cases):
    ids = {r['id'] for r in rows}
    if rows != raw or len(rows) != 376 or len(ids) != 376:
        raise ValueError('unexpected_catalog')
    leaves = {leaf['id']: leaf for leaf in taxonomy['leaves']}
    if len(leaves) != len(taxonomy['leaves']):
        raise ValueError('duplicate_leaf')
    if set().union(*(set(leaf['members']) for leaf in leaves.values())) != ids:
        raise ValueError('incomplete_taxonomy')
    if {child for root in taxonomy['roots'] for child in root['children']} != set(leaves):
        raise ValueError('incomplete_roots')
    if [case['id'] for case in cases] != CASE_IDS:
        raise ValueError('unexpected_cases')
    for case in cases:
        gold = set(case['expected_ids'] + case['pending_ids'])
        if not gold <= ids or bool(gold) == case['control']:
            raise ValueError('invalid_gold')
        if any(target.casefold() in case['need'].casefold() for target in gold):
            raise ValueError('named_capability_in_need')


def prepare(source, original, output, executable):
    source, original, out = Path(source), Path(original), Path(output)
    rows = read(source / 'CATALOG.json')
    taxonomy = read(original / 'large_public_directory.json')
    by_id = {case['id']: case for case in read(original / 'large_public_cases.json')['cases']}
    cases = [by_id[key] for key in CASE_IDS]
    validate(rows, read(source / 'CATALOG-RAW.json'), taxonomy, cases)
    if hashlib.sha256((source / 'PUBLIC-SOURCE.zip').read_bytes()).hexdigest() != ARCHIVE_SHA:
        raise ValueError('archive_changed')
    question = {k: v for k, v in read(source / 'QUESTION.json').items() if k in {'question', 'none'}}
    out.mkdir(mode=0o700, exist_ok=False)
    values = {'catalog.json': rows, 'taxonomy.json': taxonomy, 'cases.json': cases,
              'question.json': question, 'provenance.json': read(source / 'PUBLIC-CATALOG-PROFILE.json')}
    for name, value in values.items():
        write_once(out / name, value)
    trees = {height: semantic_tree(rows, taxonomy, height) for height in (4, 5, 6)}
    human = human_tree(taxonomy)
    sweep = {'human2': structure(human, [1, 2], rows)}
    for height, tree in trees.items():
        for layers in range(1, height + 1):
            sweep[f'height{height}_layers{layers}'] = structure(tree, schedule(height, layers), rows)
    write_once(out / 'structure.json', sweep)
    plan = {'version': 1, 'arms': ARMS, 'case_ids': CASE_IDS, 'executable': executable,
            'provider': 'typesafe', 'call_timeout_seconds': 15, 'max_calls': 200,
            'max_seconds': 900, 'max_known_tokens': 300000,
            'budget_note': 'Check known tokens before each call; one in-flight response may cross the cap. Missing usage is unknown.',
            'directory_threshold': .1, 'final_threshold': .7, 'final_limit': 96, 'node_limit': 192,
            'order': 'rotate arms by case index', 'attempts_per_stage': 1,
            'stopping': 'stop entire pilot on transport/malformed outcome or budget; never retry',
            'acceptance': 'Compare final current-first choice and retention of all current/pending gold separately; no winner with observed omissions.',
            'limitations': '8-case pilot; Jev routing only, no task execution; human vs lexical trees confound topology and summaries; H6 arms isolate expansion depth.',
            'tree_hashes': {str(height): identity(tree) for height, tree in trees.items()},
            'human_tree_hash': identity(human),
            'runner_sha256': hashlib.sha256((Path(__file__).parent / 'experiment.py').read_bytes()).hexdigest(),
            'frozen_sha256': {name: hashlib.sha256((out / name).read_bytes()).hexdigest() for name in [*values, 'structure.json']}}
    write_once(out / 'plan.json', plan)
    print({'catalog_count': len(rows), 'cases': len(cases), 'arms': len(ARMS), 'plan_sha256': identity(plan)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--original', default=str(Path(__file__).parent))
    parser.add_argument('--output', required=True)
    parser.add_argument('--executable', default='jev')
    args = parser.parse_args()
    prepare(args.source, args.original, args.output, args.executable)
