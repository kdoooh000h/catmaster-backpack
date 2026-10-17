"""Synthetic transport checks; these tests never load an encoder or call Jev."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'benchmarks/directory-depth'))
import focused_experiment as X

ROWS = [
    {'id': 'current', 'name': 'Current work', 'kind': 'skill', 'mode': 'guidance',
     'description': 'Create editable presentations. Do NOT upload private files; needs local input.'},
    {'id': 'later', 'name': 'Later work', 'kind': 'mcp', 'mode': 'execution_requirements_unverified',
     'description': 'Read PDF files; requires an API key.'},
    {'id': 'anchor', 'name': 'Old arbitrary primary', 'kind': 'plugin', 'mode': 'package_requirements_unverified',
     'description': 'Create presentations, with account prerequisites.'},
]
CASE = {'id': 'synthetic', 'need': '先制作幻灯片，然后读取 PDF；不要上传私密文件。',
        'stratum': 'new', 'kind_stratum': 'skill', 'language': 'zh',
        'acceptable_current_ids': ['current', 'anchor'], 'legacy_acceptable_current_ids': ['anchor'],
        'pending_groups': [['later']], 'primary_current_id': 'anchor', 'primary_pending_ids': ['later']}


def recall(pool=None, short=None, status='recalled'):
    pool = ['current', 'later'] if pool is None else pool
    return {'pool': list(pool), 'shortlist': list(pool if short is None else short), 'seconds': .01, 'status': status}


class FocusedRunnerTests(unittest.TestCase):
    def trial(self, *, recalls=None, behavior='completed', cap=240000, calls=30, score=.7, cases=None,
              run_cap=None, clock=None):
        seen, receipts, events = [], [], []
        class Provider:
            def __init__(self, config, **kwargs):
                self.calls = receipts
                self.config = config
            def noul(self, spec, state):
                # Receipt must already exist before transport starts.
                pending = list((out/'live').glob('*.pending.json'))
                assert len(pending) == len(seen)+1
                events.append('send')
                seen.append(deepcopy((spec, state)))
                if behavior == 'raise':
                    self.calls.append({'outcome': 'unknown_no_replay', 'seconds': .01})
                    raise TimeoutError('unknown_no_replay')
                receipt = {'outcome': behavior, 'seconds': .01, 'input_tokens': 10, 'output_tokens': 2}
                if behavior == 'missing_usage':
                    receipt = {'outcome': 'completed', 'seconds': .01}
                self.calls.append(receipt)
                return {'answers': {wire: {'type': 'choice', 'choice': 'current' if n == 0 else 'other',
                    'confidence': score, 'probabilities': {'current': .8 if n == 0 else .1, 'partial': .1,
                                                        'other': .1 if n == 0 else .8}}
                    for n, wire in enumerate(spec['questions'])}}
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            bundle = out/'bundle'; bundle.mkdir()
            def write(path, value):
                path.write_text(json.dumps(value, ensure_ascii=False))
            write(bundle/'catalog.json', ROWS)
            write(out/'cases.json', cases or [CASE])
            values = recalls or {'full_independent': recall(), 'focused': recall(short=['current'])}
            for case in cases or [CASE]:
                write(out/(case['id']+'.recall.json'), {'recalls': values, 'checks': {'eligible': True}})
            plan = {**X.LIMITS, 'executable': 'unused', 'max_tokens': cap, 'max_calls': calls}
            def verify(path):
                events.append('verify')
                return plan, bundle
            with patch.object(X, 'verify', side_effect=verify), patch.object(X, 'JevHierarchyProvider', Provider), contextlib.redirect_stdout(io.StringIO()):
                if clock is None:
                    summary = X.run(out, max_calls=run_cap)
                else:
                    with patch.object(X.time, 'monotonic', side_effect=clock):
                        summary = X.run(out, max_calls=run_cap)
            self.assertEqual(summary, json.loads((out/'live/summary.json').read_text()))
            artifacts = {p.name: json.loads(p.read_text()) for p in (out/'live').glob('*.json')}
            with patch.object(X, 'verify', return_value=(plan, bundle)), self.assertRaises(FileExistsError):
                X.run(out)
        return summary, seen, artifacts, events

    def test_current_shortlist_later_reservoir_and_raw_payload(self):
        summary, seen, artifacts, events = self.trial()
        self.assertEqual(summary['stop'], 'completed')
        self.assertEqual(summary['calls'], 2)
        self.assertEqual(events, ['verify', 'send', 'send'])
        self.assertTrue(all(r['omission_safe_pass'] for r in summary['rows']))
        self.assertTrue(all(not r['strict_anchor_pass'] for r in summary['rows']))
        focused = summary['rows'][1]
        self.assertEqual(focused['result']['retained_candidates'], ['current', 'later'])
        self.assertEqual(focused['result']['final_pool_size'], 1)
        for spec, state in seen:
            self.assertEqual(state['task'], CASE['need'])
            payload = json.dumps({'spec': spec, 'state': state}, ensure_ascii=False)
            self.assertIn(ROWS[0]['description'], payload)
            for secret in ['acceptable_current_ids', 'primary_current_id', 'legacy_acceptable_current_ids', 'pending_groups', 'stratum', 'dictionary_matches']:
                self.assertNotIn(secret, payload)
        self.assertEqual(artifacts['synthetic--focused.pending.json']['ordinal'], 2)
        self.assertIn('transport', artifacts['synthetic--focused.done.json'])

    def test_threshold_is_provider_point_seven(self):
        summary, _, _, _ = self.trial(score=.69)
        self.assertTrue(all(r['result']['status'] == 'abstain' for r in summary['rows']))
        summary, _, _, _ = self.trial(score=.7)
        self.assertTrue(all(r['result']['status'] == 'selected' for r in summary['rows']))

    def test_preflight_recomputed_and_current_cannot_hide_in_reservoir(self):
        for bad in [recall(short=['later']), recall(pool=['current'], short=['current']),
                    recall(status='widen_required'), recall(short=['current', 'current'])]:
            summary, seen, _, _ = self.trial(recalls={'full_independent': bad, 'focused': bad})
            self.assertEqual(seen, [])
            self.assertEqual(len(summary['rows']), 2)
            self.assertTrue(all(r['result']['status'] == 'preflight_failed' for r in summary['rows']))

    def test_width_caps_are_hard_gates(self):
        many = ['current', 'later'] + [f'extra{i}' for i in range(383)]
        self.assertFalse(X.coverage(CASE, recall(many, ['current']), 'focused')['eligible'])
        self.assertFalse(X.coverage(CASE, recall(many[:49], many[:49]), 'focused')['eligible'])
        self.assertFalse(X.coverage(CASE, recall(many[:257]), 'full_independent')['eligible'])
        self.assertTrue(X.coverage(CASE, recall(many[:384], ['current']), 'focused')['eligible'])
        self.assertTrue(X.coverage(CASE, recall(many[:256]), 'full_independent')['eligible'])

    def test_budget_before_pending_and_send(self):
        for kwargs in [{'cap': 0}, {'calls': 0}, {'run_cap': 0}]:
            summary, seen, artifacts, _ = self.trial(**kwargs)
            self.assertEqual(summary['stop'], 'budget_stop')
            self.assertEqual(seen, [])
            self.assertFalse(any('pending' in name for name in artifacts))
        summary, seen, _, _ = self.trial(calls=1)
        self.assertEqual(len(seen), 1)
        self.assertEqual(summary['stop'], 'budget_stop')

    def test_utf8_reserve_and_time_checked_before_send(self):
        spec, state, _ = X.specification('focused', ROWS, recall(short=['current']), CASE['need'])
        expected = (len(json.dumps({'spec': spec, 'state': state}, ensure_ascii=False).encode())+1)//2 + 80 + 2500
        self.assertEqual(X.token_reserve(spec, state), expected)
        ticks = iter([0, 0, 181, 181])
        summary, seen, _, _ = self.trial(clock=lambda: next(ticks))
        self.assertEqual(summary['stop'], 'time_budget_stop')
        self.assertEqual(seen, [])

    def test_unknown_transport_or_usage_stops_without_retry(self):
        for behavior, stop in [('raise', 'unknown_no_replay'), ('unknown', 'unknown_usage_or_outcome'),
                               ('missing_usage', 'unknown_usage_or_outcome')]:
            summary, seen, artifacts, _ = self.trial(behavior=behavior)
            self.assertEqual(summary['stop'], stop)
            self.assertEqual(len(seen), 1)
            self.assertEqual(summary['interrupted'], {'case': 'synthetic', 'arm': 'full_independent'})
            self.assertIn('synthetic--full_independent.pending.json', artifacts)
            self.assertEqual(summary['rows'], [])

    def test_alternates_arm_order(self):
        second = {**CASE, 'id': 'second', 'need': 'Another raw task'}
        summary, _, _, _ = self.trial(cases=[CASE, second])
        self.assertEqual([r['arm'] for r in summary['rows']], ['full_independent', 'focused', 'focused', 'full_independent'])

    def test_verify_detects_source_and_external_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp); executable = out/'jev'; executable.write_text('fake')
            frozen = out/'cases.json'; frozen.write_text('[]')
            plan = {**X.LIMITS, 'arms': X.ARMS, 'final_gate': .7, 'bundle': str(out),
                    'executable': str(executable), 'executable_sha256': X.digest(executable),
                    'source_sha256': {'source.py': 'frozen'}, 'locks': {str(executable): X.digest(executable)},
                    'frozen_sha256': {'cases.json': X.digest(frozen)}}
            (out/'plan.json').write_text(json.dumps(plan))
            with patch.object(X, 'sources', return_value=plan['source_sha256']):
                self.assertEqual(X.verify(out)[1], out)
                executable.write_text('changed')
                with self.assertRaisesRegex(ValueError, 'external_input_changed'):
                    X.verify(out)
            with patch.object(X, 'sources', return_value={'source.py': 'changed'}):
                with self.assertRaisesRegex(ValueError, 'frozen_sources_changed'):
                    X.verify(out)

    def test_failed_only_contract_excludes_previously_passing_cases(self):
        with tempfile.TemporaryDirectory() as temp:
            previous = Path(temp)
            (previous/'live').mkdir()
            old = [{**CASE, 'id': 'failed', 'need': 'Previously failed need'},
                   {**CASE, 'id': 'passed', 'need': 'Previously passed need'}]
            (previous/'cases.json').write_text(json.dumps(old))
            (previous/'plan.json').write_text(json.dumps({'bundle': str(previous)}))
            (previous/'live/summary.json').write_text(json.dumps({'stop': 'completed', 'rows': [
                {'case': 'failed', 'arm': 'hybrid_independent', 'strict_pass': False},
                {'case': 'passed', 'arm': 'hybrid_independent', 'strict_pass': True}]}))
            selected = [{**old[0], 'stratum': 'failed'}, CASE]
            with patch.object(X, 'historical_cases', return_value=(old, {})):
                self.assertEqual(X.validate_cases(selected, previous, ROWS), selected)
                with self.assertRaisesRegex(ValueError, 'failed_scope_changed'):
                    X.validate_cases(selected + [{**old[1], 'stratum': 'failed'}], previous, ROWS)
                with self.assertRaisesRegex(ValueError, 'prior_case_replayed'):
                    X.validate_cases([selected[0], {**old[1], 'stratum': 'new'}], previous, ROWS)

    def test_frozen_ancestry_can_have_a_plan_without_own_case_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); older = root/'older'; older.mkdir()
            current = root/'current'; current.mkdir()
            (older/'plan.json').write_text(json.dumps({}))
            (current/'plan.json').write_text(json.dumps({'previous': str(older)}))
            (current/'cases.json').write_text(json.dumps([CASE]))
            history, locks = X.historical_cases(current, root/'bundle')
            self.assertEqual(history, [CASE])
            self.assertIn(str((older/'plan.json').resolve()), locks)
            self.assertNotIn(str((older/'cases.json').resolve()), locks)

    def test_freeze_rebuilds_shared_baseline_and_locks_encoder_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); previous = root/'prior'; previous.mkdir()
            (previous/'live').mkdir()
            aligned = root/'aligned'; (aligned/'index').mkdir(parents=True)
            snapshot = root/'snapshot'; snapshot.mkdir()
            (snapshot/'weights').write_text('local-only')
            bundle = root/'bundle'; bundle.mkdir()
            executable = root/'jev'; executable.write_text('fake executable')
            cases = root/'selected.json'
            def write(path, value):
                path.write_text(json.dumps(value))
            write(bundle/'catalog.json', ROWS)
            prior = {'bundle': str(bundle), 'catalog_sha256': X.digest(bundle/'catalog.json'),
                     'executable': str(executable), 'executable_sha256': X.digest(executable)}
            write(previous/'plan.json', prior)
            old = {**CASE, 'id': 'failed', 'stratum': 'failed', 'need': 'Previously failed need'}
            write(previous/'cases.json', [old])
            write(previous/'live/summary.json', {'stop': 'completed', 'rows': [
                {'case': 'failed', 'arm': 'hybrid_independent', 'strict_pass': False}]})
            write(cases, {'cases': [old, CASE], 'reference_version': 2})
            (root/'cedict.txt').write_text('幻燈片 幻灯片 [huan4 deng1 pian4] /slide/\n')
            write(aligned/'model-manifest.json', {'snapshot': str(snapshot)})
            write(aligned/'index/index.json', {'model_files': {'weights': X.digest(snapshot/'weights')}})
            (aligned/'index/vectors.npy').write_bytes(b'frozen vectors')
            base = {'pool': ['current'], 'status': 'recalled', 'seconds': .01, 'catalog_count': 3}
            hybrid = {**base, 'pool': ['current', 'later']}
            lexical, structured, open_lexical, semantic, focused = [MagicMock() for _ in range(5)]
            lexical.search.return_value = base
            structured.search.return_value = base
            open_lexical.search.return_value = base
            semantic.search.return_value = hybrid
            focused.search.return_value = recall(short=['current'])
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(X, 'load_semantic', return_value=semantic))
                stack.enter_context(patch.object(X.X, 'SearchIndex', return_value=lexical))
                stack.enter_context(patch.object(X.X, 'StructuredIndex', return_value=structured))
                stack.enter_context(patch.object(X.X, 'OpenLexicalIndex', return_value=open_lexical))
                stack.enter_context(patch.object(X.X.F, 'repair_recall', return_value={'recall': base}))
                stack.enter_context(patch.object(X.F, 'FocusedIndex', return_value=focused))
                out = X.freeze(previous, root, cases, bundle)
            self.assertEqual(out, root.resolve()/'trial-new')
            self.assertEqual(semantic.search.call_count, 2)
            semantic.search.assert_any_call(CASE['need'], base, per_kind=3)
            open_lexical.search.assert_any_call(CASE['need'], base, per_kind=3)
            focused.search.assert_any_call(CASE['need'], hybrid)
            for index in (lexical, structured, open_lexical, focused):
                index.close.assert_called_once()
            plan, _ = X.verify(out)
            for path in [cases, root/'cedict.txt', snapshot/'weights', aligned/'index/vectors.npy']:
                self.assertIn(str(path.resolve()), plan['locks'])
            frozen = json.loads((out/'synthetic.recall.json').read_text())
            self.assertEqual(frozen['recalls']['full_independent']['shortlist'], hybrid['pool'])
            self.assertTrue(frozen['checks']['focused']['eligible'])
            self.assertFalse(frozen['checks']['focused']['primary_current_in_shortlist'])
            cases.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'external_input_changed'):
                X.verify(out)


if __name__ == '__main__':
    unittest.main()
