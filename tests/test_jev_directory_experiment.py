"""Mock transport and local fixtures only: never load an encoder or call Jev."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'benchmarks/directory-depth'))
import jev_directory_experiment as E

ROWS = [{'id': f'cap{n:03}', 'name': f'Capability {n}', 'kind': 'skill', 'mode': 'guidance',
         'description': f'Full original metadata {n}. Requirements: keep local; never upload private files.'}
        for n in range(129)]
CASE = {'id': 'synthetic', 'need': '先做当前工作，然后保留后续所需工具；不要上传私密文件。',
        'stratum': 'new', 'kind_stratum': 'skill', 'language': 'zh',
        'acceptable_current_ids': ['cap000'], 'pending_groups': [['cap001']],
        'primary_current_id': 'cap002', 'primary_pending_ids': ['cap001'], 'later_requirements': ['Later work']}
NODES = E.T.build(ROWS, np.tile([1., 0.], (len(ROWS), 1)))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False))


def recall(short=None, pool=None, status='recalled'):
    return {'pool': ['cap000', 'cap001'] if pool is None else pool,
            'shortlist': ['cap000'] if short is None else short, 'status': status,
            'seconds': .02, 'fresh_retrieval_seconds': .03}


class RunnerTests(unittest.TestCase):
    def trial(self, *, cases=None, score=.7, behavior='completed', max_tokens=300000,
              max_calls=80, recalls=None, run_cap=None, clock=None):
        seen, receipts = [], []
        selected = cases or [deepcopy(CASE)]
        class Provider:
            def __init__(self, config, **kwargs):
                self.calls = receipts
            def noul(self, spec, state):
                assert len(list((out/'live').glob('*.pending.json'))) == len(seen)+1
                seen.append(deepcopy((spec, state)))
                if behavior == 'raise':
                    self.calls.append({'outcome': 'unknown_no_replay', 'seconds': .0})
                    raise TimeoutError('unknown_no_replay')
                receipt = {'outcome': behavior, 'seconds': .0, 'input_tokens': 10, 'output_tokens': 2}
                if behavior == 'missing_usage':
                    receipt = {'outcome': 'completed', 'seconds': .0}
                self.calls.append(receipt)
                if next(iter(spec['questions'].values()))['type'] == 'noul':
                    return {'answers': {key: {'type': 'noul', 'noul': .8 if n == 0 else .1}
                                        for n, key in enumerate(spec['questions'])}}
                return {'answers': {key: {'type': 'choice', 'choice': 'current' if n == 0 else 'other',
                        'confidence': score, 'probabilities': {'current': .8 if n == 0 else .1,
                        'partial': .1, 'other': .1 if n == 0 else .8}}
                        for n, key in enumerate(spec['questions'])}}
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp); bundle = out/'bundle'; bundle.mkdir()
            write(bundle/'catalog.json', ROWS)
            write(out/'cases.json', selected); write(out/'nodes.json', NODES)
            for case in selected:
                write(out/(case['id']+'.recall.json'), {'recall': recalls or recall()})
            plan = {**E.LIMITS, 'executable': 'never-called', 'max_tokens': max_tokens, 'max_calls': max_calls}
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(E, 'verify', return_value=(plan, bundle)))
                stack.enter_context(patch.object(E, 'JevHierarchyProvider', Provider))
                # No local query model/search is permitted during new-arm routing.
                stack.enter_context(patch.object(E, 'load_semantic', side_effect=AssertionError('encoder_called')))
                stack.enter_context(patch.object(E.F.FocusedIndex, 'search', side_effect=AssertionError('program_query_prefilter')))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                if clock:
                    stack.enter_context(patch.object(E.time, 'monotonic', side_effect=clock))
                summary = E.run(out, max_calls=run_cap)
            self.assertEqual(summary, json.loads((out/'live/summary.json').read_text()))
            artifacts = {p.name: json.loads(p.read_text()) for p in (out/'live').glob('*.json')}
            with patch.object(E, 'verify', return_value=(plan, bundle)), self.assertRaises(FileExistsError):
                E.run(out)
        return summary, seen, artifacts

    def test_raw_need_full_metadata_later_traces_and_threshold(self):
        summary, seen, artifacts = self.trial()
        self.assertEqual(summary['stop'], 'completed')
        self.assertEqual(summary['calls'], 3)
        self.assertTrue(all(r['omission_safe_pass'] for r in summary['rows']))
        self.assertFalse(summary['rows'][0]['all_primary_references_retained'])
        self.assertEqual(summary['rows'][0]['result']['traces'], [
            {'stage': 'current_shortlist', 'pool': ['cap000']},
            {'stage': 'later_reservoir', 'pool': ['cap000', 'cap001']}])
        candidate = summary['rows'][1]
        self.assertEqual(candidate['result']['traces'][0]['before_count'], len(ROWS))
        self.assertIn('cap001', candidate['result']['traces'][0]['pool'])
        self.assertIn('cap001', candidate['result']['retained_candidates'])
        self.assertEqual(candidate['stages'], ['directory-1-batch-1', 'final'])
        self.assertEqual(candidate['selector_seconds'], candidate['dispatch_seconds'])
        self.assertEqual(candidate['real_transport_seconds'], 0.)
        self.assertEqual(summary['unfinished'], [])
        for spec, state in seen:
            self.assertEqual(state['task'], CASE['need'])
            payload = json.dumps({'spec': spec, 'state': state}, ensure_ascii=False)
            for forbidden in ('acceptable_current_ids', 'primary_current_id', 'pending_groups', 'stratum', 'dictionary_matches'):
                self.assertNotIn(forbidden, payload)
            if next(iter(spec['questions'].values()))['type'] == 'choice':
                self.assertIn(ROWS[0]['description'], payload)
        pending = artifacts['synthetic--jev_directories--directory-1-batch-1.pending.json']
        self.assertEqual(pending['ordinal'], 2)
        self.assertIn('answer', artifacts['synthetic--jev_directories--final.done.json'])
        summary, _, _ = self.trial(score=.69)
        self.assertTrue(all(r['result']['status'] == 'abstain' for r in summary['rows']))
        self.assertTrue(all(not r['omission_safe_pass'] for r in summary['rows']))

    def test_reference_mutation_changes_grades_never_dispatch(self):
        original, calls, _ = self.trial()
        changed = deepcopy(CASE)
        changed['acceptable_current_ids'] = ['cap128']
        changed['pending_groups'] = [['cap127']]
        changed['primary_current_id'] = 'cap128'
        changed['primary_pending_ids'] = ['cap127']
        mutated, mutated_calls, _ = self.trial(cases=[changed])
        self.assertEqual(calls, mutated_calls)
        self.assertEqual(mutated['stop'], 'completed')
        self.assertTrue(all(r['omission_safe_pass'] for r in original['rows']))
        self.assertTrue(all(not r['omission_safe_pass'] for r in mutated['rows']))
        # A failed grade also cannot stop later cases.
        second = {**changed, 'id': 'second', 'need': 'A distinct original task'}
        continued, _, _ = self.trial(cases=[changed, second])
        self.assertEqual(len(continued['rows']), 4)
        self.assertEqual([r['arm'] for r in continued['rows']], E.ARMS+E.ARMS[::-1])

    def test_missing_gold_does_not_gate_baseline_but_structural_errors_do(self):
        summary, seen, _ = self.trial(recalls=recall(short=['cap003'], pool=['cap003']))
        self.assertEqual(summary['stop'], 'completed')
        self.assertEqual(len(seen), 3)
        self.assertFalse(summary['rows'][0]['omission_safe_pass'])
        for bad in [recall(short=['cap000', 'cap000']), recall(status='widen_required'),
                    recall(short=['cap000'], pool=['cap001'])]:
            summary, seen, _ = self.trial(recalls=bad)
            self.assertEqual(summary['rows'][0]['result']['status'], 'structural_guard_failed')
            self.assertEqual(len(seen), 2)
            self.assertEqual(summary['rows'][1]['arm'], 'jev_directories')

    def test_budget_and_deadline_before_pending_or_send(self):
        for options in ({'max_tokens': 0}, {'max_calls': 0}, {'run_cap': 0}):
            summary, seen, artifacts = self.trial(**options)
            self.assertEqual(summary['stop'], 'budget_stop')
            self.assertEqual(seen, [])
            self.assertFalse(any('pending' in name for name in artifacts))
            self.assertEqual(len(summary['unfinished']), 2)
        summary, seen, _ = self.trial(max_calls=2)
        self.assertEqual(summary['stop'], 'budget_stop')
        self.assertEqual(len(seen), 2)
        self.assertEqual(len(summary['rows']), 1)
        ticks = iter([0., 0., 0., 0., 241., 241.])
        summary, seen, _ = self.trial(clock=lambda: next(ticks))
        self.assertEqual(summary['stop'], 'time_budget_stop')
        self.assertEqual(seen, [])

    def test_unknown_transport_or_usage_terminates_without_retry(self):
        for behavior, reason in [('raise', 'unknown_no_replay'), ('unknown', 'unknown_usage_or_outcome'),
                                 ('missing_usage', 'unknown_usage_or_outcome')]:
            summary, seen, artifacts = self.trial(behavior=behavior)
            self.assertEqual(summary['stop'], reason)
            self.assertEqual(len(seen), 1)
            self.assertEqual(summary['rows'], [])
            self.assertEqual(summary['interrupted'], {'case': CASE['id'], 'arm': E.ARMS[0]})
            self.assertEqual(len(summary['unfinished']), 2)
            self.assertIn('synthetic--program_shortlist--final.pending.json', artifacts)

    def test_utf8_budget_reserve(self):
        spec, state, _ = E.F.specification(ROWS, ['cap000'], CASE['need'])
        size = len(json.dumps({'spec': spec, 'state': state}, ensure_ascii=False).encode())
        self.assertEqual(E.token_reserve(spec, state), (size+1)//2+80+2500)


class FreezeTests(unittest.TestCase):
    def test_cases_require_exact_failed_seven_and_exclude_passed_and_ancestry(self):
        with tempfile.TemporaryDirectory() as temp:
            previous = Path(temp); (previous/'live').mkdir()
            old = [{**deepcopy(CASE), 'id': f'old{i}', 'need': f'Old original need {i}',
                    'primary_current_id': 'cap000'} for i in range(15)]
            write(previous/'cases.json', old)
            write(previous/'plan.json', {'bundle': str(previous)})
            write(previous/'live/summary.json', {'stop': 'completed', 'rows': [
                {'case': c['id'], 'arm': 'focused', 'omission_safe_pass': n >= 7} for n, c in enumerate(old)]})
            selected = [{**c, 'stratum': 'failed'} for c in old[:7]] + [
                {**deepcopy(CASE), 'id': f'new{i}', 'need': f'New need {i}', 'primary_current_id': 'cap000'} for i in range(3)]
            with patch.object(E, 'historical_cases', return_value=(old, {})):
                self.assertEqual(E.validate_cases(selected, previous, ROWS), selected)
                replay = deepcopy(selected); replay[0] = {**old[8], 'stratum': 'failed'}
                with self.assertRaisesRegex(ValueError, 'failed_scope_changed'):
                    E.validate_cases(replay, previous, ROWS)
                replay = deepcopy(selected); replay[-1] = {**old[9], 'stratum': 'new'}
                with self.assertRaisesRegex(ValueError, 'prior_case_replayed'):
                    E.validate_cases(replay, previous, ROWS)
                changed = deepcopy(selected); changed[0]['need'] += 'changed'
                with self.assertRaisesRegex(ValueError, 'old_need_changed'):
                    E.validate_cases(changed, previous, ROWS)
                ancestor = {**old[0], 'id': 'ancestor', 'need': selected[-1]['need']}
                with patch.object(E, 'historical_cases', return_value=(old+[ancestor], {})):
                    with self.assertRaisesRegex(ValueError, 'prior_case_replayed'):
                        E.validate_cases(selected, previous, ROWS)

    def test_previous_sources_checked_pointwise_not_by_new_file_set(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); previous = root/'previous'; previous.mkdir()
            source = root/'older.py'; source.write_text('old bytes')
            (root/'new.py').write_text('new source is allowed')
            bundle = root/'bundle'; bundle.mkdir(); write(bundle/'catalog.json', ROWS)
            executable = root/'jev'; executable.write_text('no invocation')
            plan = {'bundle': str(bundle), 'catalog_sha256': E.digest(bundle/'catalog.json'),
                    'executable': str(executable), 'executable_sha256': E.digest(executable),
                    'source_sha256': {'older.py': E.digest(source)}}
            write(previous/'plan.json', plan)
            with patch.object(E, 'ROOT', root):
                self.assertEqual(E.previous_inputs(previous, bundle), plan)
                source.write_text('changed bytes')
                with self.assertRaisesRegex(ValueError, 'previous_source_changed'):
                    E.previous_inputs(previous, bundle)

    def test_freeze_rebuilds_baseline_and_locks_tree_fixture_and_encoder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); previous = root/'previous'; previous.mkdir(); (previous/'live').mkdir()
            bundle = root/'bundle'; bundle.mkdir(); write(bundle/'catalog.json', ROWS)
            write(root/'nodes.json', NODES); write(root/'tree-precheck.json', {'catalog_count': len(ROWS)})
            cases_path = root/'public-cases.json'; write(cases_path, {'cases': [CASE]})
            write(previous/'plan.json', {}); write(previous/'cases.json', [])
            write(previous/'live/summary.json', {})
            aligned = root/'aligned'; (aligned/'index').mkdir(parents=True)
            snapshot = root/'snapshot'; snapshot.mkdir(); (snapshot/'weights').write_text('local weights')
            write(aligned/'model-manifest.json', {'snapshot': str(snapshot)})
            write(aligned/'index/index.json', {'model_files': {'weights': E.digest(snapshot/'weights')}})
            (aligned/'index/vectors.npy').write_bytes(b'local vectors')
            dictionary = root/'cedict.txt'; dictionary.write_text('幻燈片 幻灯片 [huan4 deng1 pian4] /slide/\n')
            executable = root/'jev'; executable.write_text('fake executable')
            prior = {'executable': str(executable), 'executable_sha256': E.digest(executable),
                     'locks': {str(aligned/'model-manifest.json'): '', str(dictionary): ''}}
            lexical, structured, open_lexical, semantic, focused = [MagicMock() for _ in range(5)]
            base = {'pool': ['cap000'], 'seconds': .01}
            hybrid = {'pool': ['cap000', 'cap001'], 'seconds': .02}
            lexical.search.return_value = base; structured.search.return_value = base
            open_lexical.search.return_value = base; semantic.search.return_value = hybrid
            focused.search.return_value = recall()
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(E, 'previous_inputs', return_value=prior))
                stack.enter_context(patch.object(E, 'validate_cases', return_value=[CASE]))
                stack.enter_context(patch.object(E, 'historical_cases', return_value=([], {})))
                stack.enter_context(patch.object(E, 'load_semantic', return_value=semantic))
                stack.enter_context(patch.object(E.X, 'SearchIndex', return_value=lexical))
                stack.enter_context(patch.object(E.X, 'StructuredIndex', return_value=structured))
                stack.enter_context(patch.object(E.X, 'OpenLexicalIndex', return_value=open_lexical))
                stack.enter_context(patch.object(E.X.F, 'repair_recall', return_value={'recall': base}))
                stack.enter_context(patch.object(E.F, 'FocusedIndex', return_value=focused))
                out = E.freeze(root, previous, cases_path, bundle)
                with self.assertRaises(FileExistsError):
                    E.freeze(root, previous, cases_path, bundle)
            self.assertEqual(out, root.resolve()/'trial')
            semantic.search.assert_called_once_with(CASE['need'], base, per_kind=3)
            open_lexical.search.assert_called_once_with(CASE['need'], base, per_kind=3)
            focused.search.assert_called_once_with(CASE['need'], hybrid)
            for index in (lexical, structured, open_lexical, focused):
                index.close.assert_called_once()
            plan, _ = E.verify(out)
            for path in (cases_path, root/'nodes.json', root/'tree-precheck.json', snapshot/'weights', aligned/'index/vectors.npy', dictionary):
                self.assertIn(str(path.resolve()), plan['locks'])
            self.assertEqual(read_json(out/'nodes.json'), NODES)
            dictionary.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'external_input_changed'):
                E.verify(out)

    def test_verify_rejects_source_and_policy_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp); executable = out/'jev'; executable.write_text('unused')
            write(out/'cases.json', [])
            plan = {**E.LIMITS, 'arms': E.ARMS, 'final_gate': .7, 'directory_gate': .2,
                    'per_need_max_calls': 8, 'stopping_policy': E.STOPPING, 'bundle': str(out),
                    'source_sha256': {'a.py': 'frozen'}, 'locks': {},
                    'frozen_sha256': {'cases.json': E.digest(out/'cases.json')},
                    'executable': str(executable), 'executable_sha256': E.digest(executable)}
            write(out/'plan.json', plan)
            with patch.object(E, 'sources', return_value={'a.py': 'changed'}):
                with self.assertRaisesRegex(ValueError, 'frozen_sources_changed'):
                    E.verify(out)
            with patch.object(E, 'sources', return_value=plan['source_sha256']):
                self.assertEqual(E.verify(out)[1], out)
                plan['final_gate'] = .69; write(out/'plan.json', plan)
                with self.assertRaisesRegex(ValueError, 'frozen_policy_changed'):
                    E.verify(out)


def read_json(path):
    return json.loads(Path(path).read_text())


if __name__ == '__main__':
    unittest.main()
