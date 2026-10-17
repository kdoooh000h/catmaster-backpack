"""Final multilingual fit gates: no live provider, installation or task calls."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adapters/codex'))
import market_guidance_fit as fit
from market_routing import route


class Error(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class GuidanceFitTests(unittest.TestCase):
    def setUp(self):
        self.runtime = SimpleNamespace(BackpackError=Error,
            Answer=lambda choice, confidence, probabilities: SimpleNamespace(
                choice=choice, confidence=confidence, probabilities=probabilities),
            _jev_cli=Mock(), _typesafe_http=Mock(), MAX_PROVIDER_ATTEMPTS=1,
            ROUTING_BUDGET_SECONDS=10, RETRYABLE_ERRORS=set(), RETRY_DELAY_SECONDS=0)
        self.config = {'provider': 'jev-cli', 'minimum_confidence': .7,
                       'executable': 'configured-jev', 'jev_provider': 'configured-provider'}
        self.candidate = SimpleNamespace(name='sample', description=json.dumps({
            'entrypoint': 'Complete original guidance. ' * 1000, 'resources': ['template.html']}))

    def response(self, contribution=('yes', .9), portable=('yes', .8)):
        return SimpleNamespace(returncode=0, stdout=json.dumps({'answers': {
            key: {'choice': value[0], 'confidence': value[1]}
            for key, value in [('contribution', contribution), ('portable', portable)]}}))

    def test_one_call_preserves_full_evidence_and_language_and_cleans_private_files(self):
        paths = []
        def execute(command, **kwargs):
            self.assertEqual(command[:3], ['configured-jev', 'run', '--json'])
            self.assertEqual(command[command.index('--retries')+1], '0')
            paths.extend([Path(command[-1]), Path(command[command.index('--state')+1][1:])])
            self.assertEqual(json.loads(paths[0].read_text()), {'questions': fit.QUESTIONS})
            self.assertEqual(json.loads(paths[1].read_text()), {
                'need': '中文 controls 同义需求', 'guide': json.loads(self.candidate.description)})
            self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in paths))
            self.assertLessEqual(kwargs['timeout'], 10)
            return self.response()
        with patch.object(fit.subprocess, 'run', side_effect=execute) as call:
            result = route(self.runtime, '中文 controls 同义需求', [self.candidate], self.config, 'plugin-ready')
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result['status'], 'selected')
        self.assertEqual(result['confidence'], .8)
        self.assertEqual(set(result['fit_checks']), {'contribution', 'portable'})
        self.assertTrue(all(not p.exists() for p in paths))
        self.runtime._jev_cli.assert_not_called()

    def test_both_dimensions_must_pass_and_floor_never_drops(self):
        cases = [((('yes', .99), ('yes', .69)), .1, 'uncertain'),
                 ((('yes', .69), ('yes', .99)), .7, 'uncertain'),
                 ((('yes', .7), ('yes', .7)), .7, 'selected'),
                 ((('yes', .99), ('yes', .8)), .9, 'uncertain'),
                 ((('yes', .99), ('no', .9)), .7, 'none'),
                 ((('no', .99), ('yes', .9)), .7, 'none')]
        for answers, floor, expected in cases:
            with self.subTest(answers=answers, floor=floor), patch.object(
                    fit.subprocess, 'run', return_value=self.response(*answers)):
                result = route(self.runtime, 'need', [self.candidate],
                               {**self.config, 'minimum_confidence': floor}, 'plugin-ready')
                self.assertEqual(result['status'], expected)
                self.assertEqual(result['skill'], 'sample' if expected == 'selected' else None)

    def test_malformed_answers_cannot_grant_guidance(self):
        valid = json.loads(self.response().stdout)
        invalid = ['not json', '{}', json.dumps({'answers': {'contribution': valid['answers']['contribution']}})]
        for confidence in [float('nan'), float('inf'), -.1, 1.1, True, '0.9', None]:
            value = json.loads(self.response().stdout)
            value['answers']['portable']['confidence'] = confidence
            invalid.append(json.dumps(value))
        for answer in [None, [], {'choice': 'perhaps', 'confidence': 1}]:
            value = json.loads(self.response().stdout); value['answers']['portable'] = answer
            invalid.append(json.dumps(value))
        for value in invalid:
            with self.subTest(value=value), patch.object(fit.subprocess, 'run',
                    return_value=SimpleNamespace(returncode=0, stdout=value)):
                with self.assertRaisesRegex(Error, 'invalid_provider_response'):
                    route(self.runtime, 'need', [self.candidate], self.config, 'plugin-ready')
        self.runtime._jev_cli.assert_not_called()

    def test_provider_failure_never_downgrades_to_old_question(self):
        cases = [(FileNotFoundError(), 'provider_missing'),
                 (subprocess.TimeoutExpired('jev', 1), 'provider_timeout')]
        for exc, code in cases:
            with self.subTest(code=code), patch.object(fit.subprocess, 'run', side_effect=exc):
                with self.assertRaisesRegex(Error, code):
                    route(self.runtime, 'need', [self.candidate], self.config, 'plugin-ready')
        with patch.object(fit.subprocess, 'run', return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(Error, 'provider_failed'):
                route(self.runtime, 'need', [self.candidate], self.config, 'plugin-ready')
        self.runtime._jev_cli.assert_not_called()

    def test_plain_guidance_and_provider_environment_supported(self):
        self.candidate.description = 'Full plain guidance with resources and constraints.'
        self.config.update(provider_environment={'reference': 'test'}, model='test-model')
        environment = SimpleNamespace(apply=Mock(return_value={'SAFE': 'test'}))
        def execute(command, **kwargs):
            state = json.loads(Path(command[command.index('--state')+1][1:]).read_text())
            self.assertEqual(state['guide'], self.candidate.description)
            self.assertEqual(kwargs['env'], {'SAFE': 'test'})
            self.assertEqual(command[command.index('--model')+1], 'test-model')
            return self.response()
        with patch.dict(sys.modules, backpack_provider_environment=environment), patch.object(
                fit.subprocess, 'run', side_effect=execute):
            self.assertEqual(route(self.runtime, 'need', [self.candidate], self.config, 'plugin-ready')['status'], 'selected')
        environment.apply.assert_called_once()

    def test_legacy_http_and_other_stages_keep_their_protocol(self):
        for provider, stage in [('typesafe-http', 'plugin-ready'), ('jev-cli', 'mcp-fit')]:
            call = self.runtime._typesafe_http if provider == 'typesafe-http' else self.runtime._jev_cli
            call.return_value = SimpleNamespace(choice='sample', confidence=.9)
            with self.subTest(provider=provider, stage=stage), patch.object(fit, 'check') as atomic:
                result = route(self.runtime, 'need', [self.candidate], {**self.config, 'provider': provider}, stage)
                self.assertEqual(result['status'], 'selected')
                atomic.assert_not_called()
                self.assertNotIn('fit_checks', result)

    def test_final_stage_requires_exactly_one_guide(self):
        with patch.object(fit, 'check') as atomic:
            for candidates in [[], [self.candidate, self.candidate]]:
                with self.assertRaisesRegex(Error, 'invalid_market_choice'):
                    route(self.runtime, 'need', candidates, self.config, 'plugin-ready')
            atomic.assert_not_called()


if __name__ == '__main__':
    unittest.main()
