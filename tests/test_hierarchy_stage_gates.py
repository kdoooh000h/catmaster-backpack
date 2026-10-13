"""Stage gates and one-shot hierarchy stops using deterministic local providers."""

from copy import deepcopy
import json
import math
from pathlib import Path
import sys
from types import MappingProxyType
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from catmaster_backpack.routing.hierarchical_choice_routing import select_hierarchical
from catmaster_backpack.routing.public_capability_directory import PublicCapabilityDirectory


def directory(candidate_count=1):
    choices = {'none': 'No matching capability.'}
    choices.update({f'cap-{i}': f'Original description {i}.' for i in range(candidate_count)})
    choices['other'] = 'Other original description.'
    return PublicCapabilityDirectory({
        'version': 1,
        'provenance': {'source': 'deterministic test fixture'},
        'roots': [
            {'id': 'root-a', 'label': 'First root', 'description': 'Tools and guidance.',
             'children': ['leaf-a']},
            {'id': 'root-b', 'label': 'Second root', 'description': 'Other tools.',
             'children': ['leaf-b']},
        ],
        'leaves': [
            {'id': 'leaf-a', 'label': 'First leaf', 'description': 'Tools and guidance.',
             'members': [f'cap-{i}' for i in range(candidate_count)]},
            {'id': 'leaf-b', 'label': 'Second leaf', 'description': 'Other tools.',
             'members': ['other']},
        ],
    }, choices)


def shortcut_fixture():
    choices = {'rare': 'Rare original description.', 'none': 'No matching capability.',
               'cap-0': 'Original description 0.', 'unused': 'Unselected original description.'}
    roots = [('root-a', 'leaf-a'), ('root-b', 'leaf-b'), ('root-c', 'leaf-c'),
             ('shortcut-root', 'shortcut-leaf')]
    leaves = [('leaf-a', ['cap-0']), ('leaf-b', ['rare']), ('leaf-c', ['unused']),
              ('shortcut-leaf', ['cap-0'])]
    spec = {
        'version': 1,
        'provenance': {'source': 'deterministic shortcut fixture',
                       'shortcut_roots': ['shortcut-root']},
        'roots': [{'id': root, 'label': root, 'description': 'Documented root.',
                   'children': [leaf]} for root, leaf in roots],
        'leaves': [{'id': leaf, 'label': leaf, 'description': 'Documented leaf.',
                    'members': members} for leaf, members in leaves],
    }
    return spec, choices


def shortcut_provider(**kwargs):
    provider = Provider(root=0, **kwargs)
    provider.scores.update({'root-c': 0, 'leaf-c': 0,
                            'shortcut-root': .9, 'shortcut-leaf': .9})
    return provider


class Provider:
    def __init__(self, root=.9, leaf=.9, final=.9, *, other=0, choice='cap-0',
                 bad_stage=None, bad_answer=None, mutate=False):
        self.scores = {'root-a': root, 'root-b': other, 'leaf-a': leaf, 'leaf-b': other}
        self.final, self.choice = final, choice
        self.bad_stage, self.bad_answer, self.mutate = bad_stage, bad_answer, mutate
        self.calls = []

    def noul(self, spec, state):
        stage = 'roots' if 'root-a' in spec['questions'] else 'leaves'
        self.calls.append((stage, deepcopy(spec), deepcopy(state)))
        if self.mutate:
            state['task'] = 'provider alteration'
            state['nested']['values'].append('provider alteration')
        if self.bad_stage == stage:
            return self.bad_answer
        return {'answers': {key: {'type': 'noul', 'noul': self.scores[key]}
                            for key in spec['questions']}}

    def choose(self, question, state, choices):
        self.calls.append(('final', question, deepcopy(state), deepcopy(choices)))
        if self.bad_stage == 'final':
            return self.bad_answer
        return {'type': 'choice', 'choice': self.choice, 'confidence': self.final}


class StageGateTests(unittest.TestCase):
    def run_selector(self, provider, *, tree=None, **gates):
        return select_hierarchical(tree or directory(), 'Original unchanged question.',
                                   {'task': 'Original unchanged task.', 'nested': {'values': []}},
                                   provider, **gates)

    def test_default_gates_remain_inclusive(self):
        provider = Provider(root=.20, leaf=.20, final=.60)
        result = self.run_selector(provider)
        self.assertEqual((result['status'], result['choice'], result['confidence']),
                         ('selected', 'cap-0', .60))
        self.assertEqual([call[0] for call in provider.calls], ['roots', 'leaves', 'final'])

    def test_custom_gates_are_inclusive_at_every_stage(self):
        provider = Provider(root=.10, leaf=.30, final=.70)
        result = self.run_selector(provider, root_gate=.10, leaf_gate=.30, final_gate=.70)
        self.assertEqual(result['status'], 'selected')
        self.assertEqual(result['diagnostics']['provider_calls'], 3)

    def test_each_below_gate_stops_dependent_stages(self):
        cases = [
            ({'root': math.nextafter(.10, 0)}, 'no_roots', ['roots']),
            ({'leaf': math.nextafter(.30, 0)}, 'no_leaves', ['roots', 'leaves']),
            ({'final': math.nextafter(.70, 0)}, 'final_confidence_below_gate',
             ['roots', 'leaves', 'final']),
        ]
        for scores, reason, stages in cases:
            with self.subTest(stage=reason):
                provider = Provider(**scores)
                result = self.run_selector(provider, root_gate=.10, leaf_gate=.30, final_gate=.70)
                self.assertEqual((result['status'], result['diagnostics']['reason']),
                                 ('abstain', reason))
                self.assertIsNone(result['choice'])
                self.assertEqual([call[0] for call in provider.calls], stages)
                if reason == 'final_confidence_below_gate':
                    self.assertEqual(result['confidence'], scores['final'])

    def test_invalid_probability_gates_make_no_provider_calls(self):
        for name in ('root_gate', 'leaf_gate', 'final_gate'):
            for value in (True, False, None, '.3', -1, 1.01, 10**1000,
                          float('nan'), float('inf'), -float('inf')):
                with self.subTest(gate=name, value=repr(value)):
                    provider = Provider()
                    result = self.run_selector(provider, **{name: value})
                    self.assertEqual((result['status'], result['diagnostics']['reason']),
                                     ('error', 'invalid_gates'))
                    self.assertEqual(provider.calls, [])
                    self.assertEqual(result['diagnostics']['provider_calls'], 0)

    def test_descending_gates_rejected_before_provider_inspection(self):
        class Uninspectable:
            def __getattribute__(self, name):
                raise AssertionError('provider must not be inspected')
        for gates in ({'root_gate': .4, 'leaf_gate': .3, 'final_gate': .7},
                      {'root_gate': .1, 'leaf_gate': .8, 'final_gate': .7}):
            result = self.run_selector(Uninspectable(), **gates)
            self.assertEqual(result['diagnostics']['reason'], 'invalid_gates')

    def test_zero_and_one_are_valid_gates(self):
        provider = Provider(root=0, leaf=0, final=0, other=0)
        result = self.run_selector(provider, root_gate=0, leaf_gate=0, final_gate=0)
        self.assertEqual(result['diagnostics']['reason'], 'full_catalog_retained')
        provider = Provider(root=1, leaf=1, final=1)
        self.assertEqual(self.run_selector(provider, root_gate=1, leaf_gate=1, final_gate=1)
                         ['status'], 'selected')

    def test_omitted_roots_and_leaves_do_not_reappear_in_final_pool(self):
        provider = Provider(root=.1, leaf=.3, other=.09)
        result = self.run_selector(provider, root_gate=.1, leaf_gate=.3, final_gate=.7)
        self.assertEqual(result['status'], 'selected')
        self.assertEqual(list(provider.calls[1][1]['questions']), ['leaf-a'])
        self.assertEqual(provider.calls[2][3],
                         {'none': 'No matching capability.', 'cap-0': 'Original description 0.'})
        provider = Provider(other=.9)
        provider.scores['leaf-b'] = math.nextafter(.3, 0)
        result = self.run_selector(provider, root_gate=.1, leaf_gate=.3, final_gate=.7)
        self.assertEqual(result['status'], 'selected')
        self.assertEqual(list(provider.calls[1][1]['questions']), ['leaf-a', 'leaf-b'])
        self.assertEqual(list(provider.calls[2][3]), ['none', 'cap-0'])

    def test_full_catalog_never_issues_global_choice(self):
        provider = Provider(other=.9)
        result = self.run_selector(provider, root_gate=.1, leaf_gate=.3, final_gate=.7)
        self.assertEqual((result['status'], result['diagnostics']['reason']),
                         ('abstain', 'full_catalog_retained'))
        self.assertEqual([call[0] for call in provider.calls], ['roots', 'leaves'])

    def test_final_candidate_limit_stays_96_excluding_none(self):
        for count, reason, calls in ((96, 'final_choice', 3),
                                     (97, 'candidate_limit_exceeded', 2)):
            with self.subTest(count=count):
                provider = Provider()
                result = self.run_selector(provider, tree=directory(count))
                self.assertEqual(result['diagnostics']['candidate_count'], count)
                self.assertEqual(result['diagnostics']['reason'], reason)
                self.assertEqual(len(provider.calls), calls)

    def test_typed_noul_errors_stop_without_retry(self):
        for stage, ids, calls in (('roots', ['root-a', 'root-b'], 1),
                                  ('leaves', ['leaf-a'], 2)):
            for invalid in ({'type': 'choice', 'noul': .9}, {'noul': .9},
                            {'type': 'noul', 'noul': True},
                            {'type': 'noul', 'noul': float('nan')},
                            {'type': 'noul', 'noul': 1.1}):
                with self.subTest(stage=stage, invalid=invalid):
                    provider = Provider(bad_stage=stage, bad_answer={
                        'answers': {key: invalid for key in ids}})
                    result = self.run_selector(provider)
                    self.assertEqual(result['diagnostics']['reason'], 'invalid_provider_response')
                    self.assertEqual(len(provider.calls), calls)
        for answers in ({}, {'root-a': {'type': 'noul', 'noul': .9}},
                        {'root-a': {'type': 'noul', 'noul': .9},
                         'root-b': {'type': 'noul', 'noul': 0}, 'extra': {}}):
            provider = Provider(bad_stage='roots', bad_answer={'answers': answers})
            self.assertEqual(self.run_selector(provider)['diagnostics']['reason'],
                             'invalid_provider_response')
            self.assertEqual(len(provider.calls), 1)

    def test_typed_final_errors_reject_outside_pool_and_invalid_confidence(self):
        for answer in ({'choice': 'cap-0', 'confidence': .9},
                       {'type': 'noul', 'choice': 'cap-0', 'confidence': .9},
                       {'type': 'choice', 'choice': 'other', 'confidence': .9},
                       {'type': 'choice', 'choice': 'cap-0', 'confidence': True},
                       {'type': 'choice', 'choice': 'cap-0', 'confidence': float('inf')}):
            with self.subTest(answer=answer):
                provider = Provider(bad_stage='final', bad_answer=answer)
                result = self.run_selector(provider)
                self.assertEqual(result['diagnostics']['reason'], 'invalid_provider_response')
                self.assertEqual(len(provider.calls), 3)
                self.assertIsNone(result['choice'])

    def test_task_state_copies_and_original_identity_are_preserved(self):
        provider = Provider(mutate=True)
        tree = directory()
        state = {'task': 'Original unchanged task.', 'nested': {'values': []}}
        original_state = deepcopy(state)
        result = select_hierarchical(tree, 'Original unchanged question.', state, provider,
                                     root_gate=.1, leaf_gate=.3, final_gate=.7)
        self.assertEqual(result['status'], 'selected')
        self.assertEqual(state, original_state)
        self.assertTrue(all(call[2] == original_state for call in provider.calls))
        self.assertEqual(provider.calls[-1][1], 'Original unchanged question.')
        public = json.dumps(result['diagnostics'])
        for private in ('Original unchanged', 'root-a', 'leaf-a', 'cap-0'):
            self.assertNotIn(private, public)

    def test_compact_cards_cover_tools_resources_and_later_actions(self):
        provider = Provider()
        self.run_selector(provider)
        for call in provider.calls[:2]:
            for item in call[1]['questions'].values():
                instructions = item['instructions']
                for required in ('tools/resources or guidance', 'original unchanged task',
                                 'mandatory later actions', 'translation subjects',
                                 'cancelled or explicitly unrequested actions'):
                    self.assertIn(required, instructions)
                self.assertLess(len(instructions), 800)

    def test_explicit_none_still_requires_final_gate(self):
        self.assertEqual(self.run_selector(Provider(choice='none', final=.7), final_gate=.7)
                         ['status'], 'none')
        result = self.run_selector(Provider(choice='none', final=.69), final_gate=.7)
        self.assertEqual(result['status'], 'abstain')
        self.assertIsNone(result['choice'])

    def test_candidate_filter_preserves_original_identity_none_and_order(self):
        tree = directory(3)
        original_pool = tree.subset(['leaf-a'])
        received, returned = [], []
        def candidate_filter(pool):
            received.append(pool)
            self.assertEqual(pool, original_pool)
            pool.pop('cap-1')
            # Reordering the filter result must not reorder original Choices.
            result = {key: pool[key] for key in ('cap-2', 'cap-0', 'none')}
            returned.append(result)
            return MappingProxyType(result)
        class MutatingProvider(Provider):
            def choose(inner, question, state, choices):
                self.assertIsNot(choices, received[0])
                self.assertIsNot(choices, returned[0])
                result = super().choose(question, state, choices)
                returned[0]['cap-0'] = 'Filter-owned mutation after validation.'
                choices['cap-0'] = 'Provider-owned mutation after validation.'
                return result
        provider = MutatingProvider()
        result = self.run_selector(provider, tree=tree, candidate_filter=candidate_filter)
        self.assertEqual(result['status'], 'selected')
        self.assertEqual(result['diagnostics']['candidate_count'], 2)
        self.assertEqual(provider.calls[-1][3],
                         {'none': original_pool['none'], 'cap-0': original_pool['cap-0'],
                          'cap-2': original_pool['cap-2']})
        self.assertEqual(tree.subset(['leaf-a']), original_pool)
        self.assertEqual(provider.calls[-1][1], 'Original unchanged question.')
        self.assertEqual(len(received), 1)
        self.assertEqual(len(provider.calls), 3)

    def test_noncallable_candidate_filters_stop_before_provider_calls(self):
        for invalid in (True, False, 0, 'filter', {}, []):
            with self.subTest(candidate_filter=invalid):
                provider = Provider()
                result = self.run_selector(provider, candidate_filter=invalid)
                self.assertEqual((result['status'], result['diagnostics']['reason']),
                                 ('error', 'invalid_candidate_filter'))
                self.assertEqual(result['diagnostics']['provider_calls'], 0)
                self.assertEqual(provider.calls, [])

    def test_invalid_filter_results_stop_without_final_choice(self):
        invalid_results = (
            None, True, False, [], [('none', 'No matching capability.')], {},
            {'cap-0': 'Original description 0.'},
            {'none': 'Changed none.', 'cap-0': 'Original description 0.'},
            {'none': 'No matching capability.', 'cap-0': 'Changed description.'},
            {'none': 'No matching capability.', 'cap-0': True},
            {'none': 'No matching capability.', 'invented': 'Original description 0.'},
            {'none': 'No matching capability.', True: 'Original description 0.'},
            # Registered but omitted by the hierarchy is still outside this pool.
            {'none': 'No matching capability.', 'other': 'Other original description.'},
        )
        for invalid in invalid_results:
            with self.subTest(result=invalid):
                provider = Provider()
                calls = []
                def candidate_filter(pool):
                    calls.append(deepcopy(pool))
                    return invalid
                result = self.run_selector(provider, candidate_filter=candidate_filter)
                self.assertEqual((result['status'], result['diagnostics']['reason']),
                                 ('error', 'invalid_candidate_filter'))
                self.assertEqual([call[0] for call in provider.calls], ['roots', 'leaves'])
                self.assertEqual(len(calls), 1)
                self.assertIsNone(result['choice'])

    def test_filter_input_mutation_cannot_alter_original_descriptions(self):
        tree = directory()
        original_pool = tree.subset(['leaf-a'])
        def candidate_filter(pool):
            pool['cap-0'] = 'ALTERED_PRIVATE_DESCRIPTION'
            return pool
        provider = Provider()
        result = self.run_selector(provider, tree=tree, candidate_filter=candidate_filter)
        self.assertEqual(result['diagnostics']['reason'], 'invalid_candidate_filter')
        self.assertEqual(tree.subset(['leaf-a']), original_pool)
        self.assertNotIn('ALTERED_PRIVATE_DESCRIPTION', json.dumps(result))
        self.assertEqual(len(provider.calls), 2)

    def test_filter_exceptions_have_fixed_reason_and_no_retry(self):
        for exception in (RuntimeError('FILTER_PRIVATE_ERROR'),
                          TimeoutError('FILTER_PRIVATE_ERROR'), ValueError('FILTER_PRIVATE_ERROR')):
            with self.subTest(exception=type(exception).__name__):
                attempts = []
                def candidate_filter(pool):
                    attempts.append(pool)
                    raise exception
                provider = Provider()
                result = self.run_selector(provider, candidate_filter=candidate_filter)
                self.assertEqual((result['status'], result['diagnostics']['reason']),
                                 ('error', 'invalid_candidate_filter'))
                self.assertEqual(len(provider.calls), 2)
                self.assertEqual(len(attempts), 1)
                self.assertNotIn('FILTER_PRIVATE_ERROR', json.dumps(result))

    def test_empty_filtered_capability_subset_abstains(self):
        provider = Provider()
        result = self.run_selector(provider,
                                   candidate_filter=lambda pool: {'none': pool['none']})
        self.assertEqual((result['status'], result['diagnostics']['reason']),
                         ('abstain', 'no_candidates'))
        self.assertEqual(result['diagnostics']['candidate_count'], 0)
        self.assertEqual(len(provider.calls), 2)
        self.assertIsNone(result['choice'])
        self.assertIsNone(result['confidence'])

    def test_filter_can_reduce_full_catalog_without_global_fallback(self):
        provider = Provider(other=.9)
        observed = []
        def candidate_filter(pool):
            observed.append(deepcopy(pool))
            return {key: value for key, value in pool.items() if key != 'other'}
        result = self.run_selector(provider, candidate_filter=candidate_filter)
        self.assertEqual(set(observed[0]), {'none', 'cap-0', 'other'})
        self.assertEqual(result['status'], 'selected')
        self.assertEqual(result['diagnostics']['candidate_count'], 1)
        self.assertEqual(provider.calls[-1][3],
                         {'none': 'No matching capability.', 'cap-0': 'Original description 0.'})
        self.assertEqual(len(provider.calls), 3)
        provider = Provider(other=.9)
        result = self.run_selector(provider, candidate_filter=lambda pool: pool)
        self.assertEqual(result['diagnostics']['reason'], 'full_catalog_retained')
        self.assertEqual(len(provider.calls), 2)

    def test_candidate_limit_counts_filtered_pool(self):
        for count, reason, calls in ((96, 'final_choice', 3),
                                     (97, 'candidate_limit_exceeded', 2)):
            with self.subTest(count=count):
                keep = {'none', *(f'cap-{i}' for i in range(count))}
                provider = Provider()
                result = self.run_selector(provider, tree=directory(100),
                    candidate_filter=lambda pool: {key: value for key, value in pool.items()
                                                   if key in keep})
                self.assertEqual(result['diagnostics']['candidate_count'], count)
                self.assertEqual(result['diagnostics']['reason'], reason)
                self.assertEqual(len(provider.calls), calls)

    def test_filter_never_restores_candidates_omitted_before_leaves(self):
        for scores, reason in (({'root': .19}, 'no_roots'), ({'leaf': .19}, 'no_leaves')):
            with self.subTest(reason=reason):
                attempts = []
                def candidate_filter(pool):
                    attempts.append(pool)
                    return pool
                result = self.run_selector(Provider(**scores), candidate_filter=candidate_filter)
                self.assertEqual(result['diagnostics']['reason'], reason)
                self.assertEqual(attempts, [])

    def test_explicit_none_filter_preserves_default_result(self):
        for scores in ({}, {'other': .9}, {'root': .19}, {'final': .59}):
            with self.subTest(scores=scores):
                self.assertEqual(self.run_selector(Provider(**scores)),
                                 self.run_selector(Provider(**scores), candidate_filter=None))

    def test_shortcut_only_skips_leaves_and_requires_final_choice(self):
        spec, choices = shortcut_fixture()
        provider = shortcut_provider()
        result = self.run_selector(provider, tree=PublicCapabilityDirectory(spec, choices),
                                   root_gate=.1, leaf_gate=.3, final_gate=.7)
        self.assertEqual((result['status'], result['choice']), ('selected', 'cap-0'))
        self.assertEqual([call[0] for call in provider.calls], ['roots', 'final'])
        self.assertEqual(result['diagnostics']['provider_calls'], 2)
        self.assertEqual(result['diagnostics']['leaf_count'], 0)
        self.assertEqual(result['diagnostics']['retained_leaf_count'], 0)
        self.assertEqual(result['diagnostics']['candidate_count'], 1)
        self.assertEqual(provider.calls[-1][3],
                         {'none': choices['none'], 'cap-0': choices['cap-0']})
        self.assertEqual(provider.calls[-1][1], 'Original unchanged question.')

    def test_mixed_shortcut_and_normal_roots_keep_rare_normal_candidates(self):
        spec, choices = shortcut_fixture()
        provider = shortcut_provider(other=.9, choice='rare')
        result = self.run_selector(provider, tree=PublicCapabilityDirectory(spec, choices))
        self.assertEqual((result['status'], result['choice']), ('selected', 'rare'))
        self.assertEqual([call[0] for call in provider.calls], ['roots', 'leaves', 'final'])
        self.assertEqual(list(provider.calls[1][1]['questions']), ['leaf-b'])
        self.assertEqual(provider.calls[-1][3],
                         {'rare': choices['rare'], 'none': choices['none'], 'cap-0': choices['cap-0']})
        self.assertEqual(result['diagnostics']['retained_root_count'], 2)
        self.assertEqual(result['diagnostics']['leaf_count'], 1)
        self.assertEqual(result['diagnostics']['retained_leaf_count'], 1)
        self.assertEqual(result['diagnostics']['candidate_count'], 2)
        self.assertEqual(result['diagnostics']['provider_calls'], 3)

    def test_shortcut_continues_when_normal_leaf_scores_are_below_gate(self):
        spec, choices = shortcut_fixture()
        provider = shortcut_provider(other=.9)
        provider.scores['leaf-b'] = math.nextafter(.3, 0)
        result = self.run_selector(provider, tree=PublicCapabilityDirectory(spec, choices),
                                   root_gate=.1, leaf_gate=.3, final_gate=.7)
        self.assertEqual(result['status'], 'selected')
        self.assertEqual([call[0] for call in provider.calls], ['roots', 'leaves', 'final'])
        self.assertEqual(result['diagnostics']['leaf_count'], 1)
        self.assertEqual(result['diagnostics']['retained_leaf_count'], 0)
        self.assertEqual(list(provider.calls[-1][3]), ['none', 'cap-0'])

    def test_shortcut_and_normal_memberships_are_deduplicated(self):
        spec, choices = shortcut_fixture()
        provider = shortcut_provider()
        provider.scores['root-a'] = .9
        provider.scores['leaf-a'] = .9
        result = self.run_selector(provider, tree=PublicCapabilityDirectory(spec, choices))
        self.assertEqual(result['status'], 'selected')
        self.assertEqual(result['diagnostics']['retained_root_count'], 2)
        self.assertEqual(result['diagnostics']['retained_leaf_count'], 1)
        self.assertEqual(result['diagnostics']['candidate_count'], 1)
        self.assertEqual(list(provider.calls[-1][3]), ['none', 'cap-0'])
        self.assertEqual(len(provider.calls), 3)

    def test_shortcut_root_score_never_substitutes_for_typed_final_answer(self):
        spec, choices = shortcut_fixture()
        cases = [
            (shortcut_provider(final=.69), 'abstain', 'final_confidence_below_gate'),
            (shortcut_provider(bad_stage='final', bad_answer={
                'choice': 'cap-0', 'confidence': .99}), 'error', 'invalid_provider_response'),
            (shortcut_provider(choice='none', final=.7), 'none', 'final_choice'),
        ]
        for provider, status, reason in cases:
            with self.subTest(status=status):
                result = self.run_selector(provider, tree=PublicCapabilityDirectory(spec, choices),
                                           final_gate=.7)
                self.assertEqual((result['status'], result['diagnostics']['reason']), (status, reason))
                self.assertEqual([call[0] for call in provider.calls], ['roots', 'final'])
                if status != 'none':
                    self.assertIsNone(result['choice'])
        provider = shortcut_provider()
        provider.scores['shortcut-root'] = 0
        result = self.run_selector(provider, tree=PublicCapabilityDirectory(spec, choices))
        self.assertEqual(result['diagnostics']['reason'], 'no_roots')
        self.assertEqual([call[0] for call in provider.calls], ['roots'])

    def test_shortcut_full_catalog_guard_and_candidate_filter_still_apply(self):
        spec, choices = shortcut_fixture()
        spec['leaves'][-1]['members'] = ['rare', 'cap-0', 'unused']
        provider = shortcut_provider()
        result = self.run_selector(provider, tree=PublicCapabilityDirectory(spec, choices))
        self.assertEqual((result['status'], result['diagnostics']['reason']),
                         ('abstain', 'full_catalog_retained'))
        self.assertEqual([call[0] for call in provider.calls], ['roots'])
        self.assertEqual(result['diagnostics']['candidate_count'], 3)
        provider = shortcut_provider()
        result = self.run_selector(provider, tree=PublicCapabilityDirectory(spec, choices),
            candidate_filter=lambda pool: {key: value for key, value in pool.items()
                                           if key in ('none', 'cap-0')})
        self.assertEqual(result['status'], 'selected')
        self.assertEqual(result['diagnostics']['candidate_count'], 1)
        self.assertEqual([call[0] for call in provider.calls], ['roots', 'final'])

    def test_invalid_shortcut_provenance_is_rejected_before_routing(self):
        for invalid in (['unknown'], ['leaf-a'], ['none'],
                        ['shortcut-root', 'shortcut-root'], 'shortcut-root',
                        None, True, {}, [True]):
            with self.subTest(shortcut_roots=invalid):
                spec, choices = shortcut_fixture()
                spec['provenance']['shortcut_roots'] = invalid
                provider = shortcut_provider()
                with self.assertRaises(ValueError):
                    self.run_selector(provider, tree=PublicCapabilityDirectory(spec, choices))
                self.assertEqual(provider.calls, [])

    def test_shortcut_property_is_optional_and_copied_from_provenance(self):
        self.assertEqual(directory().shortcut_root_ids, [])
        spec, choices = shortcut_fixture()
        tree = PublicCapabilityDirectory(spec, choices)
        spec['provenance']['shortcut_roots'].append('root-b')
        ids = tree.shortcut_root_ids
        ids.append('root-a')
        self.assertEqual(tree.shortcut_root_ids, ['shortcut-root'])
        spec, choices = shortcut_fixture()
        spec['provenance']['shortcut_roots'] = ('shortcut-root',)
        self.assertEqual(PublicCapabilityDirectory(spec, choices).shortcut_root_ids,
                         ['shortcut-root'])

    def test_shared_selector_copies_are_identical(self):
        for name in ('hierarchical_choice_routing.py', 'public_capability_directory.py'):
            self.assertEqual((ROOT / 'core' / name).read_bytes(),
                             (ROOT / 'src/catmaster_backpack/routing' / name).read_bytes())


if __name__ == '__main__':
    unittest.main()
