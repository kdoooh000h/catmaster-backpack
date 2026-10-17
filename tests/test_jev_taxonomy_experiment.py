"""Offline fixtures and mock providers; no model, query encoder or network."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'benchmarks/directory-depth'))
import jev_taxonomy_experiment as A

ROWS = [{'id': f'cap{n:03}', 'name': f'Capability {n}', 'kind': 'skill', 'mode': 'guidance',
         'description': f'Full original metadata {n}; preserve all requirements.'} for n in range(129)]
TAXONOMY = {'version': 1, 'roots': [
    {'id': name, 'name': name, 'description': 'Complete '+name+' scope.',
     'children': [{'id': 'leaf', 'name': 'Leaf', 'description': 'Complete child scope.'}]}
    for name in ('a', 'b')]}
CASE = {'id': 'oldfail', 'stratum': 'failed', 'need': '原始当前任务，然后完成后续工作；保留全部限制。',
        'acceptable_current_ids': ['cap000'], 'pending_groups': [['cap001']],
        'primary_current_id': 'cap000', 'primary_pending_ids': ['cap001']}


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False))


def alter(path, mutate):
    data = A.read(path); mutate(data); write(path, data)


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.trial = Path(self.temp.name)/'trial'; self.trial.mkdir()
        self.calls, self.behavior, self.score = [], 'completed', .7
        self.taxonomy = deepcopy(TAXONOMY)
        self.selected = [deepcopy(CASE), {**deepcopy(CASE), 'id': 'newneed', 'stratum': 'new', 'need': 'Unchanged new task.'}]
        self.rewrite_frozen()
        owner = self

        class Provider:
            def __init__(self, config, **kwargs):
                self.calls = []
            def noul(self, spec, state):
                owner.calls.append(deepcopy((spec, state)))
                # A receipt must exist before every send, including failed sends.
                pending_count = sum(len(list((owner.trial/folder).glob('*.pending-before.json')))
                    for folder in ('build', 'live-failed', 'live-new'))
                self_count = len(owner.calls)
                owner.assertEqual(pending_count, self_count)
                if owner.behavior == 'raise':
                    self.calls.append({'outcome': 'unknown_no_replay', 'seconds': 0.})
                    raise TimeoutError('unknown_no_replay')
                receipt = {'outcome': 'completed', 'seconds': 0., 'input_tokens': 10, 'output_tokens': 2}
                if owner.behavior == 'missing_usage':
                    receipt.pop('output_tokens')
                self.calls.append(receipt)
                answers = {}
                for number, (wire, question) in enumerate(spec['questions'].items()):
                    if question['type'] == 'noul':
                        probability = .1 if 'roots' in state else (.2 if number == 0 else .1999)
                        answers[wire] = {'type': 'noul', 'noul': probability}
                    else:
                        options = list(question['criteria'])
                        if 'roots' in state:
                            candidate = state['candidates'][question['instructions']['candidate']]
                            index = int(candidate['name'].split()[-1])
                            chosen = ('a' if index < 65 else 'b') if 'primary' in str(question) else 'leaf'
                            confidence = .8
                        else:
                            chosen, confidence = ('current' if number == 0 else 'other'), owner.score
                        probabilities = {option: (1. if option == chosen else 0.) for option in options}
                        answers[wire] = {'type': 'choice', 'choice': chosen, 'confidence': confidence,
                                         'probabilities': probabilities}
                if owner.behavior == 'invalid_answer':
                    next(iter(answers.values()))['type'] = 'broken'
                return {'answers': answers}
        self.provider = Provider
        self.provider_patch = patch.object(A, 'JevHierarchyProvider', Provider)
        self.provider_patch.start(); self.addCleanup(self.provider_patch.stop)

    def rewrite_frozen(self):
        for name, value in [('rows.json', ROWS), ('cases.json', self.selected), ('taxonomy.json', self.taxonomy),
                            ('balanced-nodes.json', A.T.build(ROWS, np.tile([1., 0.], (len(ROWS), 1))))]:
            write(self.trial/name, value)
        executable = Path(self.temp.name)/'jev-dummy'; executable.write_text('never execute')
        self.plan = {'arms': A.ARMS, 'build_limits': A.BUILD_LIMITS, 'live_limits': A.LIVE_LIMITS,
            'policy': A.POLICY, 'stopping_policy': A.STOPPING, 'source_sha256': A.sources(),
            'locks': {}, 'frozen_sha256': {p.name: A.digest(p) for p in self.trial.glob('*.json') if p.name != 'plan.json'},
            'executable': str(executable), 'executable_sha256': A.digest(executable), 'balanced_cold_build_seconds': .01}
        write(self.trial/'plan.json', self.plan)

    def build(self):
        summary = A.build(self.trial)
        self.assertEqual(summary['stop'], 'completed')
        return summary

    def analyze(self):
        with patch.object(A, 'JevHierarchyProvider', side_effect=AssertionError('replay_sent')):
            return A.analyze(self.trial)

    def test_paired_same_router_raw_task_threshold_and_no_gold(self):
        self.build()
        failed = A.run(self.trial)
        self.assertEqual(failed['stop'], 'completed')
        self.assertEqual(failed['calls'], 4)
        self.assertEqual([r['arm'] for r in failed['rows']], ['balanced', 'semantic'])
        self.assertTrue(all(r['omission_safe_pass'] for r in failed['rows']))
        online = [(spec, state) for spec, state in self.calls if 'task' in state]
        for spec, state in online:
            self.assertEqual(state['task'], CASE['need'])
            payload = json.dumps({'spec': spec, 'state': state}, ensure_ascii=False)
            for forbidden in ('acceptable_current_ids', 'primary_current_id', 'pending_groups', 'stratum'):
                self.assertNotIn(forbidden, payload)
        report = self.analyze()
        self.assertEqual(report['groups']['failed']['paired_completed']['cases'], 1)
        self.assertEqual(report['phases']['failed']['cost']['calls'], 4)
        self.assertNotIn(CASE['need'], json.dumps(report, ensure_ascii=False))
        semantic = next(r for r in report['rows'] if r['arm'] == 'semantic')
        self.assertEqual(semantic['last_frontier']['pool_size'], 65)
        self.assertEqual(semantic['actual_final_pool']['pool_size'], 65)
        # Equality at .2 retained the first scope; .1999 dropped the second.
        self.assertEqual(semantic['observed_pools'][0]['pool_size'], 65)
        self.score = .6999
        new = A.run(self.trial, 'new')
        self.assertEqual(new['stop'], 'completed')
        self.assertTrue(all(r['result']['status'] == 'abstain' for r in new['rows']))
        self.assertEqual([r['arm'] for r in new['rows']], ['semantic', 'balanced'])
        report = self.analyze()
        self.assertEqual(report['online_cost']['calls'], 8)
        self.assertEqual(report['groups']['all']['paired_completed']['cases'], 2)
        self.assertEqual(report['build']['cost']['calls'], 5)
        self.assertTrue(all(r['reached_final'] for r in report['rows']))
        self.assertEqual(report['groups']['all']['arms']['semantic']['reached_final_rows'], 2)

    def test_identical_tree_inputs_produce_identical_calls(self):
        self.build()
        balanced = A.read(self.trial/'balanced-nodes.json')
        # This specifically isolates organization: both arms receive the same
        # tree and unchanged D.route, with no arm-specific query processing.
        with patch.object(A, 'built', return_value=balanced), patch.object(A, 'route', wraps=A.route) as route:
            summary = A.run(self.trial)
        self.assertEqual(route.call_count, 2)
        for call in route.call_args_list:
            self.assertEqual(call.args[:3], (balanced, ROWS, CASE['need']))
        self.assertEqual(summary['rows'][0]['result'], summary['rows'][1]['result'])
        online = [(s, t) for s, t in self.calls if 'task' in t]
        self.assertEqual(online[:2], online[2:])

    def test_retained_frontier_without_final_has_no_final_coverage_claim(self):
        nodes = {'n': {'id': 'n', 'depth': 0, 'members': [r['id'] for r in ROWS],
                       'children': ['leaf'], 'description': 'Complete scope.'},
                 'leaf': {'id': 'leaf', 'depth': 1, 'members': [r['id'] for r in ROWS],
                          'children': [], 'description': 'Terminal complete scope.'}}
        def call(stage, spec, state):
            self.assertNotEqual(stage, 'final')
            return {'answers': {wire: {'type': 'noul', 'noul': .2} for wire in spec['questions']}}
        result = A.route(nodes, ROWS, CASE['need'], call)
        self.assertEqual(result['reason'], 'terminal_pool_too_wide')
        item = {'status': result['status'], **A.E.grade(CASE, result, None), **A.pools(CASE, result),
                'calls': 1, 'input_tokens': 10, 'output_tokens': 2, 'known_tokens': 12, 'wall_seconds': 0.}
        self.assertFalse(item['reached_final'])
        self.assertIsNone(item['actual_final_pool'])
        aggregate = A.aggregate([item], 1)
        self.assertEqual(aggregate['current_retained_pool_coverage']['correct'], 1)
        self.assertEqual(aggregate['actual_final_pool_current_coverage']['total'], 0)
        self.assertIsNone(aggregate['actual_final_pool_current_coverage']['rate'])

    def test_failed_grade_does_not_gate_new_dispatch(self):
        self.selected[0]['acceptable_current_ids'] = ['cap128']
        self.selected[0]['primary_current_id'] = 'cap128'
        self.rewrite_frozen(); self.build()
        failed = A.run(self.trial)
        self.assertTrue(all(not r['omission_safe_pass'] for r in failed['rows']))
        new = A.run(self.trial, 'new')
        self.assertEqual(new['stop'], 'completed')
        self.assertEqual(len(new['rows']), 2)

    def test_unknown_live_send_stops_no_retry_and_unobserved(self):
        self.build(); self.behavior = 'raise'
        summary = A.run(self.trial)
        self.assertEqual(summary['stop'], 'unknown_no_replay')
        self.assertEqual(summary['attempted_sends'], 1)
        self.assertEqual(summary['rows'], [])
        self.assertEqual(summary['input_tokens_complete'], False)
        report = self.analyze()
        self.assertEqual(report['phases']['failed']['interrupted']['grade'], 'unobserved')
        self.assertEqual(report['groups']['failed']['arms']['balanced']['known_positive_accuracy']['total'], 0)
        with self.assertRaises(FileExistsError):
            A.run(self.trial)
        with self.assertRaisesRegex(ValueError, 'failed_phase_unfinished'):
            A.run(self.trial, 'new')

    def test_unknown_usage_stops_even_with_valid_answers(self):
        self.build(); self.behavior = 'missing_usage'
        summary = A.run(self.trial)
        self.assertEqual(summary['stop'], 'unknown_usage_or_outcome')
        self.assertEqual(summary['attempted_sends'], 1)
        self.assertEqual(self.analyze()['phases']['failed']['interrupted']['grade'], 'unobserved')

    def test_shared_phase_call_budget(self):
        with patch.dict(A.LIVE_LIMITS, {'max_calls': 5}):
            self.rewrite_frozen(); self.build()
            failed = A.run(self.trial)
            self.assertEqual(failed['stop'], 'completed')
            new = A.run(self.trial, 'new')
            for key in ('attempted_sends', 'known_tokens', 'wall_seconds'):
                self.assertEqual(new['prior_usage'][key], failed[key])
            self.assertLess(new['remaining_seconds'], A.LIVE_LIMITS['max_seconds'])
            self.assertEqual(new['stop'], 'budget_stop')
            self.assertEqual(failed['attempted_sends']+new['attempted_sends'], 5)
            self.analyze()

    def test_shared_token_reservation_and_wall_budget(self):
        self.build()
        failed = A.run(self.trial)
        # Charge an already observed first phase nearly all of a new time cap;
        # this checks callback accounting independently of wall-clock speed.
        used = {key: failed[key] for key in ('attempted_sends', 'known_tokens', 'wall_seconds')}
        folder = Path(self.temp.name)/'isolated'; folder.mkdir()
        limits = {**A.LIVE_LIMITS, 'max_tokens': used['known_tokens']+1}
        recorder = A.Recorder(folder, self.plan, limits, used); recorder.context({'case': 'x', 'arm': 'balanced'})
        with self.assertRaisesRegex(RuntimeError, 'budget_stop'):
            recorder.call('final', {'questions': {'x': {'type': 'noul'}}}, {'task': 'unchanged'})
        self.assertEqual(recorder.receipts, [])
        folder2 = Path(self.temp.name)/'elapsed'; folder2.mkdir()
        used['wall_seconds'] = A.LIVE_LIMITS['max_seconds']
        recorder = A.Recorder(folder2, self.plan, A.LIVE_LIMITS, used); recorder.context({'case': 'x', 'arm': 'balanced'})
        with self.assertRaisesRegex(RuntimeError, 'time_budget_stop'):
            recorder.call('final', {'questions': {'x': {'type': 'noul'}}}, {})

    def test_build_failure_blocks_online_without_fallback(self):
        self.behavior = 'raise'
        summary = A.build(self.trial)
        self.assertEqual(summary['stop'], 'unknown_no_replay')
        self.assertEqual(summary['attempted_sends'], 1)
        self.assertFalse((self.trial/'build-manifest.json').exists())
        with self.assertRaisesRegex(ValueError, 'build_unfinished_no_fallback'):
            A.run(self.trial)
        with self.assertRaises(FileExistsError):
            A.build(self.trial)
        report = self.analyze()
        self.assertEqual(report['build']['replay_stop'], 'unknown_no_replay')
        self.assertEqual(report['phases'], {})

    def test_source_input_and_dynamic_build_digest_verification(self):
        with patch.object(A, 'sources', return_value={}):
            with self.assertRaisesRegex(ValueError, 'frozen_sources_changed'):
                A.build(self.trial)
        self.assertFalse((self.trial/'build').exists())
        self.build()
        alter(self.trial/'build/assignments.json', lambda d: d.clear())
        with self.assertRaisesRegex(ValueError, 'build_output_changed'):
            A.run(self.trial)

    def test_exact_replay_rejects_payload_and_grade_tampering(self):
        self.build(); A.run(self.trial)
        pending = next((self.trial/'live-failed').glob('*.pending-before.json'))
        alter(pending, lambda d: d['state'].__setitem__('task', 'different task'))
        # Keep the size-dependent reservation consistent: payload equality must
        # still reject it before any answer can affect traversal.
        alter(pending, lambda d: d.__setitem__('reserved_tokens', A.E.token_reserve(d['spec'], d['state'])))
        with self.assertRaisesRegex(ValueError, 'replay_payload_or_stage_mismatch'):
            self.analyze()

    def test_malformed_typed_answer_is_a_terminal_observed_failure(self):
        self.build(); self.behavior = 'invalid_answer'
        summary = A.run(self.trial)
        self.assertEqual(summary['stop'], 'invalid_directory_probability')
        self.assertEqual(summary['attempted_sends'], 1)
        report = self.analyze()
        self.assertEqual(report['phases']['failed']['interrupted']['grade'], 'unobserved')

    def test_unknown_pending_after_process_interruption(self):
        self.build(); self.behavior = 'raise'; A.run(self.trial)
        # Simulate a process death after durable send intent, before any
        # outcome/summary was observed. Replay cannot invent answer or grades.
        for path in (self.trial/'live-failed').glob('*.error.json'):
            path.unlink()
        (self.trial/'live-failed/summary.json').unlink()
        report = self.analyze()
        self.assertEqual(report['phases']['failed']['stop'], 'unobserved_interruption')
        self.assertEqual(report['phases']['failed']['interrupted']['replay_stop'], 'pending_outcome_unobserved')
        self.assertEqual(report['online_cost']['input_tokens_complete'], False)
        self.assertEqual(report['online_cost']['wall_seconds'], 'unobserved')

    def test_recover_observed_rows_without_phase_summary(self):
        self.build(); A.run(self.trial)
        (self.trial/'live-failed/summary.json').unlink()
        report = self.analyze()
        self.assertEqual(report['phases']['failed']['stop'], 'unobserved_interruption')
        self.assertEqual(len(report['rows']), 2)
        self.assertEqual(report['phases']['failed']['cost']['wall_seconds'], 'unobserved')

    def test_unknown_build_receipt_metadata_tamper_rejected(self):
        self.build()
        pending = next((self.trial/'build').glob('*.pending-before.json'))
        alter(pending, lambda d: next(iter(d['state']['candidates'].values())).__setitem__('description', 'changed full metadata'))
        alter(pending, lambda d: d.__setitem__('reserved_tokens', A.E.token_reserve(d['spec'], d['state'])))
        with self.assertRaisesRegex(ValueError, 'replay_payload_or_stage_mismatch'):
            self.analyze()

    def test_unjustified_budget_stop_tamper_rejected(self):
        self.build(); self.behavior = 'raise'; A.run(self.trial)
        for path in (self.trial/'live-failed').glob('*.error.json'):
            path.unlink()
        for path in (self.trial/'live-failed').glob('*.pending-before.json'):
            path.unlink()
        path = self.trial/'live-failed/summary.json'
        alter(path, lambda d: d.update(stop='budget_stop', transport=[], calls=0, attempted_sends=0,
            input_tokens_complete=True, output_tokens_complete=True))
        with self.assertRaisesRegex(ValueError, 'unjustified_budget_stop'):
            self.analyze()


class FreezeTests(unittest.TestCase):
    def test_catalog_only_freeze_preserves_inputs_and_source_locks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); previous = root/'previous'; previous.mkdir()
            bundle = root/'fullbundle'; bundle.mkdir()
            rows = [{**ROWS[n % len(ROWS)], 'id': f'item{n:03}'} for n in range(240)]
            write(root/'sample-catalog.json', rows)
            np.save(root/'sample-vectors.npy', np.tile([1., 0.], (240, 1)))
            write(bundle/'catalog.json', rows)
            write(root/'sample-plan.json', {'locks': {str(bundle/'catalog.json'): A.digest(bundle/'catalog.json')},
                'sample_count': 240, 'sampled_kind_counts': {'skill': 240}, 'target_counts': {'skill': 240}, 'source_catalog_count': 1000})
            write(root/'cases.json', [CASE]); write(root/'taxonomy.json', TAXONOMY)
            executable = root/'jev'; executable.write_text('never execute')
            write(previous/'plan.json', {'bundle': str(bundle)})
            write(previous/'cases.json', [CASE]); (previous/'live').mkdir(); write(previous/'live/summary.json', {})
            prior = {'bundle': str(bundle), 'executable': str(executable), 'executable_sha256': A.digest(executable)}
            with patch.object(A.E, 'previous_inputs', return_value=prior), \
                    patch.object(A.E, 'validate_cases', return_value=[CASE]), \
                    patch.object(A.E, 'historical_cases', return_value=([], {})), \
                    patch.object(A, 'JevHierarchyProvider', side_effect=AssertionError('freeze_sent')):
                trial = A.freeze(root, root/'cases.json', root/'taxonomy.json', previous)
            self.assertEqual(trial, root/'trial')
            plan = A.verify(trial)
            self.assertEqual(A.read(trial/'rows.json'), rows)
            self.assertIn('benchmarks/directory-depth/jev_taxonomy_build.py', plan['source_sha256'])
            self.assertIn('benchmarks/directory-depth/jev_taxonomy.json', plan['source_sha256'])
            self.assertIn('core/jev_hierarchy_provider.py', plan['source_sha256'])
            self.assertIn(str(bundle/'catalog.json'), plan['locks'])
            self.assertEqual(A.T.validate(A.read(trial/'balanced-nodes.json'), rows)['candidate_count'], 240)
            write(root/'sample-plan.json', {})
            with self.assertRaisesRegex(ValueError, 'external_input_changed'):
                A.verify(trial)


if __name__ == '__main__':
    unittest.main()
