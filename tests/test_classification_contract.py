"""Offline mixed Choice/Noul membership contract and persisted no-replay stops."""

from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from catmaster_backpack import plugin_directory as directory
from catmaster_backpack.plugin_pipeline import atomic_json, init_store


ENTRY = {'kind': 'skill', 'name': 'backend', 'plugin': 'fixture',
         'description': 'Implement, design, debug, and review a backend.'}
SKILL_IDS = ('implementation', 'architecture', 'debugging', 'git_review')
CARDS = [
    {'id': key, 'label': key, 'description': 'Documented ' + key,
     'kinds': ['skill', 'command']} for key in SKILL_IDS
] + [{'id': 'code_execution', 'label': 'Execute code',
      'description': 'Return a code execution result.', 'kinds': ['tool', 'resource']}]


class Provider:
    def __init__(self, *, primary='implementation', confidence=.9, scores=None, alter=None):
        self.primary, self.confidence = primary, confidence
        self.scores = {} if scores is None else scores
        self.alter = alter
        self.calls, self.inputs = [], []

    def noul(self, spec, state):
        self.calls.append({'input_tokens': 10, 'output_tokens': 2})
        self.inputs.append((deepcopy(spec), deepcopy(state)))
        answer = {'answers': {
            key: ({'type': 'choice', 'choice': self.primary, 'confidence': self.confidence}
                  if key == 'primary' else {'type': 'noul', 'noul': self.scores.get(key, 0)})
            for key in spec['questions']}}
        if self.alter is not None:
            self.alter(answer)
        return answer


def actual_cards():
    template = directory.template()
    kinds = template['provenance']['leaf_kinds']
    return [{**leaf, 'kinds': kinds[leaf['id']]} for leaf in template['leaves']]


class ClassificationContractTests(unittest.TestCase):
    def classify(self, provider, *, entry=None, cards=None):
        return directory.classify(entry or deepcopy(ENTRY),
                                  cards if cards is not None else deepcopy(CARDS), provider)

    def assert_invalid(self, provider):
        with self.assertRaisesRegex(ValueError, '^invalid_membership_response$'):
            self.classify(provider)
        self.assertEqual(len(provider.calls), 1)

    def test_primary_and_secondary_decisions_share_one_typed_spec(self):
        provider = Provider()
        self.assertEqual(self.classify(provider), ['implementation'])
        self.assertEqual(len(provider.calls), 1)
        spec, state = provider.inputs[0]
        self.assertEqual(set(spec['questions']), {'primary', *SKILL_IDS})
        self.assertEqual(spec['questions']['primary']['type'], 'choice')
        self.assertEqual(set(spec['questions']['primary']['criteria']), {'none', *SKILL_IDS})
        self.assertTrue(all(spec['questions'][key]['type'] == 'noul' for key in SKILL_IDS))
        self.assertEqual(set(state['scopes']), {'none', *SKILL_IDS})
        self.assertEqual(state['capability_metadata']['kind'], 'skill')

    def test_primary_missing_wrong_type_and_outside_pool_are_invalid(self):
        invalid_answers = (
            None, [], {'choice': 'implementation', 'confidence': .9},
            {'type': 'noul', 'choice': 'implementation', 'confidence': .9},
            {'type': 'choice', 'confidence': .9},
            {'type': 'choice', 'choice': 'code_execution', 'confidence': .9},
            {'type': 'choice', 'choice': 'unknown', 'confidence': .9},
        )
        for invalid in invalid_answers:
            with self.subTest(primary=invalid):
                def alter(raw, invalid=invalid):
                    raw['answers']['primary'] = invalid
                self.assert_invalid(Provider(scores={'architecture': 1}, alter=alter))

    def test_primary_confidence_is_a_finite_typed_probability(self):
        for confidence in (True, False, None, '.9', -1, 1.01, 10**1000,
                           float('nan'), float('inf'), -float('inf')):
            with self.subTest(confidence=repr(confidence)):
                self.assert_invalid(Provider(confidence=confidence, scores={'architecture': 1}))
        self.assert_invalid(Provider(alter=lambda raw: raw['answers']['primary'].pop('confidence')))

    def test_answer_keys_must_match_entire_submitted_question_set(self):
        def missing_primary(raw):
            raw['answers'].pop('primary')
        def missing_secondary(raw):
            raw['answers'].pop(SKILL_IDS[-1])
        def extra_answer(raw):
            raw['answers']['unsolicited'] = {'type': 'noul', 'noul': 1}
        def none_answer(raw):
            raw['answers']['none'] = {'type': 'noul', 'noul': 1}
        def wrong_answer_container(raw):
            raw['answers'] = list(raw['answers'].values())
        def missing_answers(raw):
            raw.pop('answers')
        for alter in (missing_primary, missing_secondary, extra_answer, none_answer,
                      wrong_answer_container, missing_answers):
            with self.subTest(shape=alter.__name__):
                self.assert_invalid(Provider(alter=alter))

    def test_primary_confidence_boundary_qualifies_with_zero_noul(self):
        self.assertEqual(directory.MEMBERSHIP_GATE, .40)
        provider = Provider(confidence=.40)
        self.assertEqual(self.classify(provider), ['implementation'])
        with self.assertRaisesRegex(ValueError, '^unclassified_capability$'):
            self.classify(Provider(confidence=math.nextafter(.40, 0)))
        self.assertEqual(self.classify(Provider(confidence=1)), ['implementation'])

    def test_secondary_boundary_is_inclusive_independently_of_primary(self):
        self.assertEqual(directory.SECONDARY_MEMBERSHIP_GATE, .40)
        self.assertEqual(self.classify(Provider(primary='none', confidence=0,
                                              scores={'architecture': .40})), ['architecture'])
        with self.assertRaisesRegex(ValueError, '^unclassified_capability$'):
            self.classify(Provider(primary='none', confidence=1,
                                  scores={'architecture': math.nextafter(.40, 0)}))
        # A named primary below its own floor still qualifies through its Noul.
        self.assertEqual(self.classify(Provider(confidence=.39,
                                              scores={'implementation': .40})), ['implementation'])

    def test_primary_none_does_not_veto_documented_secondary_operations(self):
        provider = Provider(primary='none', confidence=.30,
                            scores={'implementation': .58, 'architecture': .41})
        self.assertEqual(self.classify(provider, cards=actual_cards()),
                         ['implementation', 'architecture'])
        self.assertEqual(len(provider.calls), 1)

    def test_multiple_qualifying_memberships_are_not_capped(self):
        provider = Provider(primary='none', confidence=.3,
                            scores={key: .40 for key in SKILL_IDS})
        self.assertEqual(self.classify(provider), list(SKILL_IDS))
        # Preserve card order rather than promoting the primary or ranking scores.
        provider = Provider(primary='git_review', confidence=.9,
                            scores={key: .99 for key in SKILL_IDS[:-1]})
        self.assertEqual(self.classify(provider), list(SKILL_IDS))

    def test_invalid_last_noul_discards_every_earlier_valid_membership(self):
        for invalid in (None, {'noul': .9}, {'type': 'choice', 'noul': .9},
                        {'type': 'noul', 'noul': True}, {'type': 'noul', 'noul': '.9'},
                        {'type': 'noul', 'noul': float('nan')},
                        {'type': 'noul', 'noul': float('inf')},
                        {'type': 'noul', 'noul': -1}, {'type': 'noul', 'noul': 1.01}):
            with self.subTest(last_answer=invalid):
                def alter(raw, invalid=invalid):
                    raw['answers'][SKILL_IDS[-1]] = invalid
                self.assert_invalid(Provider(scores={key: 1 for key in SKILL_IDS}, alter=alter))

    def test_invalid_last_noul_persists_pending_and_never_replays(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / 'project'
            project.mkdir()
            store = root / 'store'
            init_store(store, project)
            _, _, registry = directory.load_registry(store)
            registry['plugins'] = {'fixture': {
                'name': 'fixture', 'root': str(project), 'indexes': {},
                'library': [{'kind': 'skill', 'path': 'backend/SKILL.md',
                             'name': ENTRY['name'], 'description': ENTRY['description']}],
            }}
            atomic_json(store / 'registry.json', registry)
            def invalidate_last(raw):
                key = next(reversed(raw['answers']))
                raw['answers'][key] = {'type': 'noul', 'noul': True,
                                       'private': 'RAW_PRIVATE_RESPONSE'}
            provider = Provider(scores={card['id']: 1 for card in actual_cards()},
                                alter=invalidate_last)
            first = directory.refresh(store, provider_factory=lambda: provider)
            self.assertEqual((first['status'], first['pending'], first['classification_calls']),
                             ('pending', 1, 1))
            cached = directory.read_cache(store)
            row = next(iter(cached['entries'].values()))
            self.assertEqual((row['status'], row['leaves'], row['reason']),
                             ('pending', [], 'classification_failed_or_unknown'))
            self.assertIsNone(cached['directory'])
            self.assertNotIn('RAW_PRIVATE_RESPONSE', json.dumps(cached))
            factory_attempts = []
            def forbidden_factory():
                factory_attempts.append('attempted')
                raise AssertionError('pending outcome must not be replayed')
            second = directory.refresh(store, provider_factory=forbidden_factory)
            self.assertEqual((second['status'], second['pending'], second['classification_calls']),
                             ('pending', 1, 0))
            self.assertEqual(directory.read_cache(store)['entries'], cached['entries'])
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(factory_attempts, [])

    def test_actual_template_filters_disjoint_kinds_before_provider_call(self):
        cards = actual_cards()
        instruction_ids = {card['id'] for card in cards if 'skill' in card['kinds']}
        executable_ids = {card['id'] for card in cards if 'tool' in card['kinds']}
        self.assertTrue(instruction_ids)
        self.assertTrue(executable_ids)
        self.assertTrue(instruction_ids.isdisjoint(executable_ids))
        for kind in ('skill', 'command', 'tool', 'resource'):
            with self.subTest(kind=kind):
                expected = [card['id'] for card in cards if kind in card['kinds']]
                provider = Provider(primary=expected[0], confidence=.4,
                                    scores={card['id']: 1 for card in cards})
                retained = self.classify(provider, entry={**ENTRY, 'kind': kind}, cards=cards)
                self.assertEqual(retained, expected)
                spec, state = provider.inputs[0]
                self.assertEqual(list(spec['questions']), ['primary', *expected])
                self.assertEqual(list(spec['questions']['primary']['criteria']), [*expected, 'none'])
                self.assertEqual(list(state['scopes']), [*expected, 'none'])
                forbidden = executable_ids if kind in ('skill', 'command') else instruction_ids
                self.assertTrue(forbidden.isdisjoint(spec['questions']))
                self.assertTrue(forbidden.isdisjoint(state['scopes']))
                self.assertEqual(len(provider.calls), 1)

    def test_unsupported_kind_stops_before_provider_call(self):
        provider = Provider()
        with self.assertRaisesRegex(ValueError, '^unsupported_capability_kind$'):
            self.classify(provider, entry={**ENTRY, 'kind': 'unknown'}, cards=actual_cards())
        self.assertEqual(provider.calls, [])


if __name__ == '__main__':
    unittest.main()
