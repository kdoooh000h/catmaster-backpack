"""Two-level selection preserves full metadata and stable IDs; synthetic provider."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/catmaster_backpack'))
from plugin_runtime import pick, CapabilityEntries, validate_arguments
import plugin_directory as directory
from plugin_pipeline import atomic_json


class Provider:
    def __init__(self, choice='cap_opaque_second', confidence=.9):
        self.choice, self.confidence = choice, confidence
        self.calls = [];self.final_pool = None
    def noul(self, spec, state):
        self.calls.append({'input_tokens': 1, 'output_tokens': 1})
        return {'answers': {k: ({'type':'choice','choice':'either','confidence':.9} if k=='_delivery_mode' else
                                {'type':'noul','noul':.9 if k in ('inventory','stock') else .01}) for k in spec['questions']}}
    def choose(self, question, state, choices):
        self.calls.append({'input_tokens': 1, 'output_tokens': 1});self.final_pool = choices
        return {'type':'choice','choice':self.choice,'confidence':self.confidence}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store = Path(self.temp.name)
        self.entries = CapabilityEntries(self.store)
        self.entries.update({
            'cap_opaque_first': {'kind':'tool','plugin':'inventory','name':'get_stock','description':'Manage inventory.'},
            'cap_opaque_second': {'kind':'tool','plugin':'inventory','name':'set_stock','description':'Manage inventory.'},
            'cap_other': {'kind':'skill','plugin':'writing','name':'write','description':'Write prose.'}})
        self.publish()
    def publish(self):
        template_hash=directory.digest(directory.template())
        tree = {'version':1,'provenance':{'source':'synthetic_registered_fixture','template_sha256':template_hash,'description_sha256':{k:directory.digest(directory.wire(e)) for k,e in self.entries.items()}},
                'roots':[{'id':'inventory','label':'Inventory','description':'Get and set stock','children':['stock']},
                         {'id':'text','label':'Writing','description':'Write prose','children':['prose']}],
                'leaves':[{'id':'stock','label':'Stock','description':'Get and set stock','members':['cap_opaque_first','cap_opaque_second']},
                          {'id':'prose','label':'Prose','description':'Write prose','members':['cap_other']}]}
        atomic_json(self.store / directory.FILE, {'schema':directory.SCHEMA,'template_sha256':template_hash,'directory':tree})
    def select(self, provider):
        with patch('plugin_directory.JevHierarchyProvider', return_value=provider):
            return pick('set the stock count',self.entries)
    def test_names_disambiguate_same_descriptions_with_stable_ids(self):
        provider=Provider();result=self.select(provider)
        self.assertEqual(result['choice'],'cap_opaque_second')
        self.assertEqual(provider.final_pool,{'cap_opaque_first':'[tool] inventory/get_stock: Manage inventory.',
                         'cap_opaque_second':'[tool] inventory/set_stock: Manage inventory.','none':directory.NONE})
        self.assertEqual(len(provider.calls),3)
        self.assertNotIn('cap_other',provider.final_pool)
    def test_short_labels_and_unknown_ids_are_not_valid_choices(self):
        for key in ('0','1','cap_unknown'):
            with self.subTest(key=key):
                result=self.select(Provider(key));self.assertEqual(result['status'],'unavailable')
    def test_confidence_boundary_and_typed_probability(self):
        for confidence,status in ((.69,'unavailable'),(.70,'selected'),(True,'unavailable'),(float('nan'),'unavailable')):
            with self.subTest(confidence=confidence):
                self.assertEqual(self.select(Provider(confidence=confidence))['status'],status)
        self.assertEqual(self.select(Provider('none',1))['status'],'none')
    def test_empty_and_long_descriptions_are_preserved_without_truncation(self):
        self.entries['cap_opaque_first']['description']=''
        self.entries['cap_opaque_second']['description']='x'*1990+' CSV only.';self.publish()
        provider=Provider();self.assertEqual(self.select(provider)['status'],'selected')
        self.assertEqual(provider.final_pool['cap_opaque_second'],directory.wire(self.entries['cap_opaque_second']))
        self.assertTrue(provider.final_pool['cap_opaque_second'].endswith('CSV only.'))
    def test_bounds_and_source_change_prevent_provider_calls(self):
        for field,value in [('name','x'*257),('description','x'*2049),('description','changed')]:
            with self.subTest(field=field,value=value[:20]):
                old=self.entries['cap_opaque_first'][field];self.entries['cap_opaque_first'][field]=value
                provider=Provider();self.assertEqual(self.select(provider)['reason'],'directory_review_required')
                self.assertEqual(provider.calls,[]);self.entries['cap_opaque_first'][field]=old
    def test_maximum_wire_text_preserves_original_budget(self):
        entry=dict(self.entries['cap_opaque_first'],name='n'*256,description='x'*(2048-len('[tool] inventory: ')))
        self.assertEqual(len(directory.wire(entry)),2305)
        entry['description']+='x'
        with self.assertRaises(ValueError):directory.wire(entry)
    def test_missing_directory_and_plain_catalog_never_trigger_full_choice(self):
        self.assertEqual(pick('read',dict(self.entries))['reason'],'directory_review_required')
        (self.store/directory.FILE).rename(self.store/'retained-directory.json')
        provider=Provider();self.assertEqual(self.select(provider)['reason'],'directory_review_required');self.assertEqual(provider.calls,[])

class ArgumentPatternTests(unittest.TestCase):
    def test_pattern_keys_allowed_with_additional_properties_false(self):
        schema = {'type': 'object', 'patternProperties': {'^x-': {'type': 'string'}},
                  'additionalProperties': False}
        validate_arguments({'x-foo': 'ok'}, schema)
        with self.assertRaisesRegex(ValueError, '^unexpected_argument$'):
            validate_arguments({'foo': 'ok'}, schema)
        with self.assertRaisesRegex(ValueError, '^argument_type_mismatch$'):
            validate_arguments({'x-foo': 1}, schema)

    def test_patterns_search_anywhere_in_key(self):
        schema = {'patternProperties': {'x-': {'type': 'string'}}, 'additionalProperties': False}
        validate_arguments({'prefix-x-foo': 'ok'}, schema)

    def test_explicit_property_and_matching_pattern_both_apply(self):
        schema = {'properties': {'x-foo': {'type': 'string', 'minLength': 2}},
                  'patternProperties': {'^x-': {'maxLength': 3}}, 'additionalProperties': False}
        validate_arguments({'x-foo': 'ok'}, schema)
        for value in ('a', 'long'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, '^argument_string_size_mismatch$'):
                validate_arguments({'x-foo': value}, schema)

    def test_every_matching_pattern_applies_in_either_order(self):
        pairs = [('^x-', {'type': 'integer', 'minimum': 2}), ('count$', {'maximum': 4})]
        for ordered in (pairs, list(reversed(pairs))):
            schema = {'patternProperties': dict(ordered), 'additionalProperties': False}
            validate_arguments({'x-count': 3}, schema)
            for value in (1, 5):
                with self.subTest(order=ordered, value=value), self.assertRaisesRegex(ValueError, '^argument_number_bounds_mismatch$'):
                    validate_arguments({'x-count': value}, schema)

    def test_additional_schema_only_applies_to_unmatched_keys(self):
        schema = {'properties': {'builtin': {'type': 'boolean'}},
                  'patternProperties': {'^x-': {'type': 'integer'}},
                  'additionalProperties': {'type': 'string'}}
        validate_arguments({'builtin': True, 'x-count': 3, 'other': 'ok'}, schema)
        with self.assertRaisesRegex(ValueError, '^argument_type_mismatch$'):
            validate_arguments({'other': 3}, schema)

    def test_pattern_subschemas_keep_root_refs_and_nested_validation(self):
        schema = {'$defs': {'payload': {'type': 'object', 'patternProperties': {'^n': {'type': 'integer'}},
                                       'additionalProperties': False}},
                  'patternProperties': {'^x-': {'$ref': '#/$defs/payload'}}, 'additionalProperties': False}
        validate_arguments({'x-foo': {'number': 3}}, schema)
        with self.assertRaisesRegex(ValueError, '^argument_type_mismatch$'):
            validate_arguments({'x-foo': {'number': 'bad'}}, schema)

    def test_boolean_pattern_subschemas(self):
        schema = {'patternProperties': {'^x-': True, 'forbidden$': False}, 'additionalProperties': False}
        validate_arguments({'x-foo': {'any': 'value'}}, schema)
        with self.assertRaisesRegex(ValueError, '^argument_schema_false$'):
            validate_arguments({'x-forbidden': 'bad'}, schema)

    def test_malformed_pattern_maps_fail_even_without_matching_values(self):
        malformed = [None, [], 'bad', {'[': {}}, {'a{999999999999999999999999}': {}},
                     {'(' * 1000 + ')' * 1000: {}}, {1: {}}, {'^x-': None}, {'^x-': []}, {'^x-': 1}]
        for patterns in malformed:
            for value in ({}, {'other': 'ok'}, 'non-object'):
                with self.subTest(patterns=patterns, value=value), self.assertRaisesRegex(ValueError, '^invalid_argument_pattern_properties$'):
                    validate_arguments(value, {'patternProperties': patterns})


if __name__=='__main__':unittest.main()
