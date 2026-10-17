"""Mock suffix provider only; historical root requests are never resent."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'benchmarks'))
import taxonomy_threshold_pilot as S


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False))


def alter(path, mutate):
    value = S.read(path); mutate(value); write(path, value)


class SuffixTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.trial = self.root/'trial'; self.trial.mkdir()
        self.output = self.root/'suffix'; self.calls = []; self.behavior = 'completed'; self.score = .7
        self.rows = [{'id': f'cap{n:03}', 'name': f'Name {n}', 'kind': 'skill', 'mode': 'guidance',
                      'description': f'Original full metadata {n}; preserve the stated restrictions.'} for n in range(129)]
        self.nodes = {'n': {'id': 'n', 'depth': 0, 'members': [r['id'] for r in self.rows],
                           'children': ['a', 'b'], 'description': 'Complete catalog.'}}
        for key, selected in [('a', self.rows[:64]), ('b', self.rows[64:])]:
            self.nodes[key] = {'id': key, 'depth': 1, 'members': [r['id'] for r in selected],
                               'children': [], 'description': 'Full scope '+key}
        self.cases = [{'id': f'case{n}', 'stratum': 'failed' if n < 7 else 'new',
            'need': f'Original unchanged task {n}.', 'acceptable_current_ids': ['cap000'],
            'primary_current_id': 'cap000', 'pending_groups': [], 'primary_pending_ids': []} for n in range(10)]
        write(self.trial/'rows.json', self.rows); write(self.trial/'cases.json', self.cases)
        cost = {'calls': 21, 'attempted_sends': 21, 'input_tokens': 95081, 'output_tokens': 8361,
            'known_tokens': 103442, 'input_tokens_complete': True, 'output_tokens_complete': True,
            'wall_seconds': 28.457016, 'real_transport_seconds': 28.17}
        offline = {**cost, 'calls': 11, 'attempted_sends': 11, 'input_tokens': 140000,
                   'output_tokens': 3901, 'known_tokens': 143901, 'wall_seconds': 20., 'real_transport_seconds': 19.}
        self.report = {'phases': {stratum: {'stop': 'completed'} for stratum in ('failed', 'new')},
            'rows': [{'case': c['id'], 'stratum': c['stratum'], 'arm': 'semantic',
                      'omission_safe_pass': c['id'] == 'case6'} for c in self.cases],
            'online_cost': cost, 'build': {'cost': offline}}
        self.analysis = self.root/'analysis.json'; write(self.analysis, self.report)
        self.diagnostics = self.root/'organization-diagnostics.json'
        write(self.diagnostics, {'final_gate_unchanged': .7,
            'summary': {'failed': [{'gate': .2, 'rows': 7, 'known_coverage_and_final_size': 1},
                                  {'gate': .65, 'rows': 7, 'known_coverage_and_final_size': 7},
                                  {'gate': .8, 'rows': 7, 'known_coverage_and_final_size': 7}],
                        # This value deliberately disagrees: selection must
                        # use the failed-seven development summary alone.
                        'new': [{'gate': .1, 'rows': 3, 'known_coverage_and_final_size': 3}]}})
        executable = self.root/'jev'; executable.write_text('do not execute')
        self.original_plan = {'executable': str(executable), 'executable_sha256': S.digest(executable), 'locks': {}}
        for case in self.cases:
            folder = self.trial/('live-'+case['stratum']); folder.mkdir(exist_ok=True)
            stage = 'directory-1-batch-1'
            spec, state, _ = S.X.D.directory_spec(self.nodes, ['a', 'b'], case['need'])
            stem = folder/(case['id']+'--semantic--'+stage)
            write(str(stem)+'.pending-before.json', {'ordinal': 1, 'identity': {'case': case['id'], 'arm': 'semantic'},
                'stage': stage, 'spec': spec, 'state': state})
            write(str(stem)+'.done-after.json', {'ordinal': 1, 'stage': stage,
                'answer': {'answers': {'d1': {'type': 'noul', 'noul': .9}, 'd2': {'type': 'noul', 'noul': .5}}},
                'transport': [{'outcome': 'completed', 'input_tokens': 10, 'output_tokens': 2, 'seconds': .1}]})
        self.start_patch(patch.object(S.X, 'verify', return_value=self.original_plan))
        self.start_patch(patch.object(S.X, 'analyze', return_value=self.report))
        self.start_patch(patch.object(S.X, 'built', return_value=self.nodes))
        owner = self
        class Provider:
            def __init__(self, config, **kwargs):
                self.calls = []
            def noul(self, spec, state):
                # A new root send would immediately fail this test.
                owner.assertEqual({q['type'] for q in spec['questions'].values()}, {'choice'})
                owner.assertEqual(len(list((owner.output/'live').glob('*.pending-before.json'))), len(owner.calls)+1)
                owner.calls.append(deepcopy((spec, state)))
                if owner.behavior == 'raise':
                    self.calls.append({'outcome': 'unknown_no_replay', 'seconds': 0.})
                    raise TimeoutError('unknown_no_replay')
                self.calls.append({'outcome': 'completed', 'seconds': .0, 'input_tokens': 10, 'output_tokens': 2})
                return {'answers': {wire: {'type': 'choice', 'choice': 'current' if n == 0 else 'other',
                    'confidence': owner.score, 'probabilities': {'current': 1. if n == 0 else 0.,
                        'partial': 0., 'other': 0. if n == 0 else 1.}} for n, wire in enumerate(spec['questions'])}}
        self.start_patch(patch.object(S.X, 'JevHierarchyProvider', Provider))

    def start_patch(self, patcher):
        patcher.start(); self.addCleanup(patcher.stop)

    def freeze(self):
        return S.freeze(self.trial, self.output, self.analysis, self.diagnostics)

    def analyze(self):
        with patch.object(S.X, 'JevHierarchyProvider', side_effect=AssertionError('replay_sent')):
            return S.analyze(self.output)

    def test_exact_cached_root_no_reroot_and_one_final_each(self):
        self.freeze()
        preparation = S.read(self.output/'preparation.json')
        self.assertEqual(len(preparation), 9)
        self.assertNotIn('case6', [p['case'] for p in preparation])
        self.assertEqual(preparation, sorted(preparation, key=lambda p: (-p['reserved_tokens'], p['case'])))
        before_gate = S.X.D.DIRECTORY_GATE
        summary = S.run(self.output)
        self.assertEqual(summary['stop'], 'completed'); self.assertEqual(len(self.calls), 9)
        self.assertEqual(S.X.D.DIRECTORY_GATE, before_gate)
        self.assertEqual(summary['prior_usage']['known_tokens'], 103442)
        self.assertEqual(summary['prior_usage']['attempted_sends'], 21)
        for item in summary['rows']:
            self.assertTrue(item['omission_safe_pass'])
            self.assertEqual(item['result']['final_pool_size'], 64)
            self.assertEqual(item['result']['traces'][0]['gate'], .65)
        for spec, state in self.calls:
            self.assertIn(state['task'], [c['need'] for c in self.cases])
            self.assertNotIn('acceptable_current_ids', json.dumps({'spec': spec, 'state': state}))
        report = self.analyze()
        self.assertEqual(report['groups']['failed']['completed_rows'], 6)
        self.assertEqual(report['groups']['new']['completed_rows'], 3)
        self.assertEqual(report['skipped'][0]['gate_065_result'], 'unverified')
        self.assertEqual(report['marginal_suffix_cost']['known_tokens'], 108)
        self.assertEqual(report['completed_composite_cost']['known_tokens'], 216)
        self.assertEqual(report['full_online_experiment_cost']['known_tokens'], 103550)
        self.assertEqual(report['full_experiment_cost_including_offline_build']['known_tokens'], 247451)
        self.assertNotIn(self.cases[0]['need'], json.dumps(report))
        with self.assertRaises(FileExistsError):
            S.run(self.output)

    def test_final_point_seven_unchanged(self):
        self.freeze(); self.score = .6999
        summary = S.run(self.output)
        self.assertTrue(all(r['result']['status'] == 'abstain' for r in summary['rows']))
        self.assertEqual(self.analyze()['groups']['all']['known_positive_accuracy']['correct'], 0)

    def test_unknown_send_stops_no_retry_and_partial_is_unobserved(self):
        self.freeze(); self.behavior = 'raise'
        summary = S.run(self.output)
        self.assertEqual(summary['stop'], 'unknown_no_replay')
        self.assertEqual(summary['attempted_sends'], 1); self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(summary['unattempted']), 8)
        report = self.analyze()
        self.assertEqual(report['interrupted']['grade'], 'unobserved')
        self.assertEqual(report['groups']['all']['completed_rows'], 0)
        self.assertFalse(report['full_online_experiment_cost']['input_tokens_complete'])

    def test_budget_is_carried_and_stops_before_next_pending(self):
        self.freeze()
        reserve = S.read(self.output/'preparation.json')[0]['reserved_tokens']
        # A fixture limit produces exactly one affordable new final request.
        # Preserve the same remaining budget across all suffixes.
        with patch.dict(S.X.LIVE_LIMITS, {'max_tokens': 103442+reserve}):
            alter(self.output/'plan.json', lambda d: d.__setitem__('limits', dict(S.X.LIVE_LIMITS)))
            summary = S.run(self.output)
            self.assertEqual(summary['stop'], 'budget_stop')
            self.assertEqual(summary['attempted_sends'], 1)
            self.assertEqual(summary['prior_usage']['known_tokens'], 103442)
            self.assertEqual(self.analyze()['groups']['all']['completed_rows'], 1)

    def test_frozen_root_or_preparation_or_budget_mutation_is_rejected(self):
        self.freeze()
        altered = next((self.trial/'live-failed').glob('*.done-after.json'))
        alter(altered, lambda d: d['answer']['answers']['d1'].__setitem__('noul', .1))
        with self.assertRaisesRegex(ValueError, 'suffix_locked_input_changed'):
            S.run(self.output)
        self.assertFalse((self.output/'live').exists())

    def test_prior_usage_cannot_be_reset(self):
        self.freeze()
        alter(self.output/'plan.json', lambda d: d['prior_usage'].__setitem__('known_tokens', 0))
        with self.assertRaisesRegex(ValueError, 'suffix_prior_budget_changed'):
            S.run(self.output)

    def test_skip_is_only_from_measured_semantic_pass(self):
        # Changing diagnostics' reference coverage does not skip another task.
        self.freeze()
        plan = S.read(self.output/'plan.json')
        self.assertEqual([r['case'] for r in plan['skipped']], ['case6'])
        self.assertEqual(set(plan['case_order']), {c['id'] for c in self.cases if c['id'] != 'case6'})

    def test_exact_final_payload_replay_rejects_tamper(self):
        self.freeze(); S.run(self.output)
        pending = next((self.output/'live').glob('*.pending-before.json'))
        alter(pending, lambda d: d['state'].__setitem__('task', 'changed task'))
        alter(pending, lambda d: d.__setitem__('reserved_tokens', S.X.E.token_reserve(d['spec'], d['state'])))
        with self.assertRaisesRegex(ValueError, 'replay_payload_or_stage_mismatch'):
            self.analyze()

    def test_summaryless_pending_preserves_unknown(self):
        self.freeze(); self.behavior = 'raise'; S.run(self.output)
        for path in (self.output/'live').glob('*.error.json'):
            path.unlink()
        (self.output/'live/summary.json').unlink()
        report = self.analyze()
        self.assertEqual(report['stop'], 'unobserved_interruption')
        self.assertEqual(report['interrupted']['replay_stop'], 'pending_outcome_unobserved')
        self.assertEqual(report['full_online_experiment_cost']['wall_seconds'], 'unobserved')


if __name__ == '__main__':
    unittest.main()
