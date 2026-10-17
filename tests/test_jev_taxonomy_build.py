from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmarks/directory-depth'))
import jev_taxonomy_build as B


def taxonomy(count=2):
    return {'version': 1, 'roots': [
        {'id': f'r{i}', 'name': f'Functional domain {i}',
         'description': f'Authored complete functional scope {i}.',
         'children': [{'id': f'l{j}', 'name': f'Child {i}-{j}',
                       'description': f'Authored child scope {i}-{j}.'} for j in range(2)]}
        for i in range(count)]}


def rows(count=1):
    return [{'id': f'canonical/plugin/{i:03}', 'name': f'Entity {i}', 'kind': 'plugin',
             'description': 'One whole package with stated functions.', 'publisher_labels': ['Weak label'],
             'topics': ['SECRET_TOPIC'], 'classification_basis': 'SECRET_BASIS',
             'source_domains': ['SECRET_DOMAIN'], 'markets': ['SECRET_MARKET'],
             'query': 'SECRET_QUERY', 'gold': 'SECRET_GOLD', 'case': 'SECRET_CASE'}
            for i in range(count)]


def choice(question, selected, confidence=.9):
    options = list(question['criteria'])
    return {'type': 'choice', 'choice': selected, 'confidence': confidence,
            'probabilities': {key: 1.0 if key == selected else 0.0 for key in options}}


class MockJev:
    def __init__(self, primary='r0', multi=.1, cross=None, leaf='l0', root_conf=.9, leaf_conf=.9):
        self.primary, self.multi, self.cross, self.leaf = primary, multi, cross or {}, leaf
        self.root_conf, self.leaf_conf, self.calls = root_conf, leaf_conf, []

    def __call__(self, stage, spec, state):
        self.calls.append(deepcopy((stage, spec, state)))
        answers = {}
        for wire, question in spec['questions'].items():
            if stage.startswith('class-root'):
                answers[wire] = (choice(question, self.primary, self.root_conf)
                                 if question['type'] == 'choice' else {'type': 'noul', 'noul': self.multi})
            elif stage.startswith('class-cross'):
                root = question['instructions']['root']
                answers[wire] = {'type': 'noul', 'noul': self.cross.get(root, .1)}
            else:
                answers[wire] = choice(question, self.leaf, self.leaf_conf)
        return {'answers': answers}


class JevTaxonomyBuildTests(unittest.TestCase):
    def test_multiple_memberships_keep_primary_despite_cross_disagreement_and_deduplicate(self):
        source, tree = rows(), taxonomy(8)
        saved_rows, saved_tree = deepcopy(source), deepcopy(tree)
        call = MockJev(multi=.5, cross={f'r{i}': .5 for i in range(1, 8)})
        result = B.classify(source, tree, call)
        assignment = result['assignments'][source[0]['id']]
        self.assertEqual(assignment['supported_roots'], [f'r{i}' for i in range(8)])
        self.assertEqual(len(assignment['leaf_paths']), 8)
        self.assertEqual(len(assignment['cross']), 8)
        self.assertEqual(assignment['primary']['confidence'], .9)
        self.assertEqual(assignment['cross']['r0']['noul'], .1)
        self.assertEqual(result['nodes']['n']['members'], [source[0]['id']])
        for node in result['nodes'].values():
            self.assertEqual(len(node['members']), len(set(node['members'])))
        stats = B.validate(result['nodes'], source)
        self.assertEqual(stats['candidate_count'], 1)
        self.assertEqual(stats['leaf_memberships'], 8)
        self.assertEqual(stats['overlapping_candidates'], 1)
        self.assertEqual(source, saved_rows)
        self.assertEqual(tree, saved_tree)

    def test_single_domain_never_gets_cross_probe_and_global_unknown_is_explicit_leaf(self):
        call = MockJev(primary=B.UNRESOLVED, multi=.499)
        result = B.classify(rows(), taxonomy(), call)
        self.assertEqual([entry[0] for entry in call.calls], ['class-root-1'])
        assignment = next(iter(result['assignments'].values()))
        self.assertEqual(assignment['supported_roots'], [])
        self.assertEqual(assignment['leaf_paths'], [['n', B.UNKNOWN]])
        self.assertEqual(result['nodes'][B.UNKNOWN]['children'], [])
        self.assertIn('Metadata insufficient', result['nodes'][B.UNKNOWN]['description'])

    def test_unresolved_primary_stays_reachable_alongside_explicit_cross_support(self):
        call = MockJev(primary=B.UNRESOLVED, multi=.9, cross={'r1': .5})
        result = B.classify(rows(), taxonomy(), call)
        assignment = next(iter(result['assignments'].values()))
        self.assertEqual(assignment['supported_roots'], ['r1'])
        self.assertIn(['n', B.UNKNOWN], assignment['leaf_paths'])
        self.assertEqual(len(assignment['leaf_paths']), 2)

    def test_low_confidence_adds_fallback_without_erasing_chosen_paths_or_raw_signals(self):
        result = B.classify(rows(2), taxonomy(), MockJev(root_conf=.49, leaf_conf=.3), split_above=1)
        assignment = next(iter(result['assignments'].values()))
        self.assertEqual(assignment['primary_root'], 'r0')
        self.assertEqual(assignment['supported_roots'], ['r0'])
        self.assertEqual(assignment['leaves']['r0'], ['l0', B.UNRESOLVED_LEAF])
        self.assertEqual(assignment['leaf']['r0']['choice'], 'l0')
        self.assertEqual(assignment['leaf']['r0']['confidence'], .3)
        self.assertEqual(assignment['primary']['probabilities']['r0'], 1)
        self.assertTrue(assignment['uncertain'])
        self.assertEqual(len(assignment['leaf_paths']), 3)

    def test_floor_boundary_does_not_add_unknown_and_explicit_child_unknown_is_kept(self):
        result = B.classify(rows(2), taxonomy(), MockJev(root_conf=.5, leaf_conf=.5), split_above=1)
        assignment = next(iter(result['assignments'].values()))
        self.assertFalse(assignment['global_unknown'])
        self.assertEqual(assignment['leaves']['r0'], ['l0'])
        result = B.classify(rows(2), taxonomy(), MockJev(leaf=B.UNRESOLVED_LEAF, leaf_conf=.2),
                            split_above=1)
        assignment = next(iter(result['assignments'].values()))
        self.assertEqual(assignment['leaves']['r0'], [B.UNRESOLVED_LEAF])
        self.assertEqual(len(assignment['leaf_paths']), 1)

    def test_only_allowed_metadata_and_aliases_are_in_every_model_payload(self):
        source = rows(2)
        call = MockJev(multi=.8, cross={'r1': .8})
        B.classify(source, taxonomy(), call, split_above=1)
        forbidden = {'id', 'topics', 'classification_basis', 'source_domains', 'canonicalID',
                     'markets', 'query', 'task', 'gold', 'ref', 'reference', 'case'}
        def inspect(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for item in value.values():
                    inspect(item)
            elif isinstance(value, list):
                for item in value:
                    inspect(item)
        for _, spec, state in call.calls:
            inspect(spec)
            for question in spec['questions'].values():
                instructions = question['instructions']
                alias = instructions['candidate']
                self.assertIn(alias, state['candidates'])
                self.assertEqual(instructions['candidate_path'], f'state.candidates.{alias}')
            # Taxonomy children have authored IDs, so inspect only catalog data
            # and require the state to expose exactly the documented three keys.
            self.assertEqual(set(state), {'policy', 'candidates', 'roots'})
            inspect(state['candidates'])
            for candidate in state['candidates'].values():
                self.assertEqual(set(candidate), {'name', 'kind', 'description', 'publisher_labels'})
            payload = json.dumps([spec, state])
            self.assertNotIn(source[0]['id'], payload)
            self.assertNotIn('SECRET_', payload)
            self.assertIn('Weak label', payload)

    def test_unknown_unsupported_metadata_is_not_dropped_or_program_classified(self):
        source = rows(2)
        source[0]['description'] = ''
        source[1]['description'] = 'Unclear metadata; publisher labels alone are not support.'
        result = B.classify(source, taxonomy(), MockJev(primary=B.UNRESOLVED))
        self.assertEqual(set(result['nodes'][B.UNKNOWN]['members']), {row['id'] for row in source})
        self.assertEqual(B.validate(result['nodes'], source)['candidate_count'], 2)

    def test_batch_limits_stage_names_all_roots_and_shared_definitions(self):
        call = MockJev(multi=.9, cross={f'r{i}': .8 for i in range(8)})
        result = B.classify(rows(33), taxonomy(8), call, split_above=1)
        self.assertEqual(len(set(entry[0] for entry in call.calls)), len(call.calls))
        self.assertEqual(len(result['calls']), len(call.calls))
        cross_questions = 0
        for stage, spec, state in call.calls:
            self.assertRegex(stage, r'^class-(root|cross|leaf)-[1-9][0-9]*$')
            count = len(spec['questions'])
            self.assertLessEqual(count, 32 if stage.startswith('class-leaf') else 64)
            if stage.startswith('class-root'):
                self.assertLessEqual(len(state['candidates']), 32)
                self.assertEqual(len(state['roots']), 8)
            if stage.startswith('class-cross'):
                cross_questions += count
            if stage.startswith('class-leaf'):
                present = {q['instructions']['root'] for q in spec['questions'].values()}
                self.assertEqual(set(state['roots']), present)
            self.assertLessEqual(B.payload_bytes(spec, state), B.MAX_PAYLOAD_BYTES)
        self.assertEqual(cross_questions, 33 * 8)
        self.assertEqual(len([entry for entry in call.calls if entry[0].startswith('class-root')]), 2)

    def test_utf8_budget_splits_batches_and_oversize_single_item_fails_before_send(self):
        source = rows(3)
        for row in source:
            row['description'] = '明确功能' * 400
        singleton = MockJev()
        B.classify(source, taxonomy(), singleton, batch_size=1, split_above=1)
        limit = max(B.payload_bytes(spec, state) for _, spec, state in singleton.calls) + 20
        call = MockJev()
        B.classify(source, taxonomy(), call, max_payload_bytes=limit, split_above=1)
        self.assertEqual(len([stage for stage, _, _ in call.calls if stage.startswith('class-root')]), 3)
        for _, spec, state in call.calls:
            self.assertLessEqual(B.payload_bytes(spec, state), limit)
        blocked = MockJev()
        with self.assertRaisesRegex(ValueError, 'item_exceeds_payload_budget'):
            B.classify(source, taxonomy(), blocked, max_payload_bytes=100)
        self.assertEqual(blocked.calls, [])

    def test_cards_use_all_authored_scope_not_member_tokens_and_drop_only_empty_nodes(self):
        source, tree = rows(), taxonomy()
        source[0]['name'] = 'UNIQUE_MEMBER_NAME'
        source[0]['description'] = 'UNIQUE_MEMBER_TERMS'
        result = B.classify(source, tree, MockJev())
        cards = '\n'.join(node['description'] for node in result['nodes'].values())
        self.assertNotIn('UNIQUE_MEMBER', cards)
        root_node = next(node for key, node in result['nodes'].items() if key.startswith('n.root/'))
        self.assertIn(tree['roots'][0]['description'], root_node['description'])
        self.assertIn(tree['roots'][0]['children'][1]['description'], root_node['description'])
        self.assertNotIn(B._root_id('r1'), result['nodes'])
        self.assertNotIn(B._leaf_id('r0', 'l1'), result['nodes'])
        self.assertEqual(len(result['nodes']['n']['children']), 1)

    def test_semantic_node_ids_are_stable_under_row_order_and_escape_ambiguous_ids(self):
        tree = taxonomy()
        tree['roots'][0]['id'] = 'r/a'
        tree['roots'][0]['children'][0]['id'] = 'l/b'
        source = rows(2)
        first = B.classify(source, tree, MockJev(primary='r/a', leaf='l/b'), split_above=1)
        second = B.classify(list(reversed(source)), tree, MockJev(primary='r/a', leaf='l/b'),
                            split_above=1)
        self.assertEqual(first, second)
        self.assertIn('n.root/r%2Fa', first['nodes'])
        self.assertIn('n.leaf/r%2Fa/l%2Fb', first['nodes'])

    def test_malformed_maps_types_probabilities_confidence_and_sums_fail(self):
        def mutate(drop=None, change=None):
            model = MockJev()
            def call(stage, spec, state):
                raw = model(stage, spec, state)
                if drop is not None:
                    raw['answers'].pop(drop)
                if change:
                    change(raw['answers'])
                return raw
            return call
        changes = [
            lambda a: a.update(extra={'type': 'noul', 'noul': .1}),
            lambda a: a['q1'].update(type='noul'),
            lambda a: a['q1'].update(choice=[]),
            lambda a: a['q1'].update(choice='foreign'),
            lambda a: a['q1'].update(confidence=True),
            lambda a: a['q1'].update(confidence=float('nan')),
            lambda a: a['q1'].update(probabilities={'r0': 1}),
            lambda a: a['q1']['probabilities'].update(r1=float('inf')),
            lambda a: a['q1']['probabilities'].update(r1=.5),
            lambda a: a['q1']['probabilities'].update(r0=.1, r1=.9),
            lambda a: a['m1'].update(noul=True),
            lambda a: a['m1'].update(noul=float('nan')),
            lambda a: a['m1'].update(noul=1.01),
            lambda a: a['m1'].update(confidence=-.1),
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                B.classify(rows(), taxonomy(), mutate(change=change))
        with self.assertRaisesRegex(ValueError, 'answer_map'):
            B.classify(rows(), taxonomy(), mutate(drop='m1'))

    def test_cross_and_leaf_answers_are_validated_too(self):
        for bad_stage in ('cross', 'leaf'):
            model = MockJev(multi=.8)
            def call(stage, spec, state):
                raw = model(stage, spec, state)
                if stage.startswith('class-' + bad_stage):
                    raw['answers'][next(iter(raw['answers']))]['type'] = 'wrong'
                return raw
            with self.subTest(stage=bad_stage), self.assertRaisesRegex(ValueError, 'answer_type'):
                B.classify(rows(2), taxonomy(), call, split_above=1)

    def test_caller_failure_propagates_once_without_retry_or_fallback(self):
        for failure in (TimeoutError('unknown_no_replay'), RuntimeError('caller_stopped')):
            calls = []
            def call(*args):
                calls.append(args)
                raise failure
            with self.subTest(failure=failure), self.assertRaises(type(failure)) as context:
                B.classify(rows(), taxonomy(), call)
            self.assertIs(context.exception, failure)
            self.assertEqual(len(calls), 1)

    def test_invalid_inputs_fail_before_call_and_empty_catalog_is_complete(self):
        for source, tree, kwargs in [
            (rows() * 2, taxonomy(), {}),
            ([{**rows()[0], 'kind': None}], taxonomy(), {}),
            ([{**rows()[0], 'publisher_labels': 'not-a-list'}], taxonomy(), {}),
            (rows(), {**taxonomy(), 'version': True}, {}),
            (rows(), taxonomy(), {'batch_size': True}),
            (rows(), taxonomy(), {'batch_size': 33}),
            (rows(), taxonomy(), {'max_payload_bytes': 0}),
            (rows(), taxonomy(), {'split_above': 0}),
            (rows(), taxonomy(), {'split_above': True}),
            (rows(), taxonomy(), {'split_above': 1.5}),
        ]:
            model = MockJev()
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                B.classify(source, tree, model, **kwargs)
            self.assertEqual(model.calls, [])
        model = MockJev()
        empty = B.classify([], taxonomy(), model)
        self.assertEqual(empty['assignments'], {})
        self.assertEqual(empty['nodes']['n']['members'], [])
        self.assertEqual(B.validate(empty['nodes'], [])['candidate_count'], 0)
        self.assertEqual(model.calls, [])

    def test_validator_rejects_cycles_missing_rows_children_duplicates_and_unreachable(self):
        source = rows(2)
        base = B.classify(source, taxonomy(), MockJev())['nodes']
        def cycle(nodes):
            leaf = next(key for key, node in nodes.items() if not node['children'])
            nodes[leaf]['children'] = ['n']
        def missing_row(nodes):
            nodes['n']['members'].pop()
        def missing_child(nodes):
            nodes['n']['children'].append('missing')
        def duplicate_member(nodes):
            nodes['n']['members'].append(nodes['n']['members'][0])
        def unreachable(nodes):
            nodes['extra'] = {**deepcopy(nodes['n']), 'id': 'extra'}
        def bad_union(nodes):
            leaf = next(node for node in nodes.values() if not node['children'])
            leaf['members'].pop()
        for change in (cycle, missing_row, missing_child, duplicate_member, unreachable, bad_union):
            broken = deepcopy(base)
            change(broken)
            with self.subTest(change=change.__name__), self.assertRaises(ValueError):
                B.validate(broken, source)

    def test_validator_rejects_shared_node_alias_but_allows_distinct_overlapping_leaves(self):
        source = rows(2)
        nodes = B.classify(source, taxonomy(), MockJev(multi=.8, cross={'r1': .8}),
                           split_above=1)['nodes']
        self.assertEqual(B.validate(nodes, source)['leaf_memberships'], 4)
        shared_leaf = nodes[B._root_id('r0')]['children'][0]
        other_leaf = nodes[B._root_id('r1')]['children'][0]
        nodes[B._root_id('r1')]['children'] = [shared_leaf]
        del nodes[other_leaf]
        with self.assertRaisesRegex(ValueError, 'shared_classification_node'):
            B.validate(nodes, source)

    def test_adaptive_split_boundary_128_is_terminal_and_129_receives_child_classification(self):
        for count in (128, 129):
            with self.subTest(count=count):
                source, model = rows(count), MockJev()
                result = B.classify(source, taxonomy(), model)
                root = result['nodes'][B._root_id('r0')]
                leaf_calls = [entry for entry in model.calls if entry[0].startswith('class-leaf')]
                if count == 128:
                    self.assertEqual(result['split_roots'], [])
                    self.assertEqual(root['children'], [])
                    self.assertEqual(leaf_calls, [])
                    self.assertIn('Child classification is deferred', root['description'])
                else:
                    self.assertEqual(result['split_roots'], ['r0'])
                    self.assertTrue(root['children'])
                    self.assertEqual(sum(len(spec['questions']) for _, spec, _ in leaf_calls), 129)
                for assignment in result['assignments'].values():
                    self.assertEqual(assignment['leaves']['r0'], ['l0'] if count > 128 else [])
                    self.assertEqual(assignment['deferred_roots'], [] if count > 128 else ['r0'])
                    self.assertEqual(len(assignment['leaf_paths'][0]), 3 if count > 128 else 2)
                stats = B.validate(result['nodes'], source)
                self.assertEqual(stats['candidate_count'], count)
                self.assertEqual(stats['split_roots'], ['r0'] if count > 128 else [])
                self.assertEqual(stats['deferred_roots'], [] if count > 128 else ['r0'])

    def test_cross_membership_counts_toward_split_without_duplicating_primary_members(self):
        source, model = rows(3), MockJev()
        def call(stage, spec, state):
            raw = model(stage, spec, state)
            for wire, question in spec['questions'].items():
                alias = question['instructions']['candidate']
                is_third = state['candidates'][alias]['name'] == 'Entity 2'
                if stage.startswith('class-root'):
                    if question['type'] == 'choice':
                        raw['answers'][wire] = choice(question, 'r1' if is_third else 'r0')
                    else:
                        raw['answers'][wire]['noul'] = .9 if is_third else .1
                elif stage.startswith('class-cross'):
                    raw['answers'][wire]['noul'] = .9
            return raw
        result = B.classify(source, taxonomy(), call, split_above=2)
        self.assertEqual(result['split_roots'], ['r0'])
        self.assertEqual(result['nodes'][B._root_id('r0')]['members'], [row['id'] for row in source])
        self.assertEqual(result['nodes'][B._root_id('r1')]['members'], [source[2]['id']])
        self.assertEqual(result['nodes'][B._root_id('r1')]['children'], [])
        leaf_questions = [question for stage, spec, _ in model.calls
                          if stage.startswith('class-leaf') for question in spec['questions'].values()]
        self.assertEqual(len(leaf_questions), 3)
        self.assertEqual({question['instructions']['root'] for question in leaf_questions}, {'r0'})
        assignment = result['assignments'][source[2]['id']]
        self.assertEqual(assignment['deferred_roots'], ['r1'])
        self.assertEqual(assignment['leaves'], {'r0': ['l0'], 'r1': []})

    def test_unknown_paths_remain_reachable_when_supported_roots_are_deferred(self):
        for primary, confidence in ((B.UNRESOLVED, .9), ('r0', .49)):
            with self.subTest(primary=primary):
                source = rows()
                model = MockJev(primary=primary, root_conf=confidence, multi=.9, cross={'r1': .8})
                result = B.classify(source, taxonomy(), model)
                assignment = result['assignments'][source[0]['id']]
                self.assertEqual(result['split_roots'], [])
                self.assertIn(['n', B.UNKNOWN], assignment['leaf_paths'])
                self.assertIn(['n', B._root_id('r1')], assignment['leaf_paths'])
                self.assertEqual(assignment['leaf'], {})
                self.assertTrue(all(not leaves for leaves in assignment['leaves'].values()))
                self.assertFalse(any(stage.startswith('class-leaf') for stage, _, _ in model.calls))
                B.validate(result['nodes'], source)


if __name__ == '__main__':
    unittest.main()
