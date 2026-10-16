"""Compose already-authorized guidance setup without changing routing or scope."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adapters/codex'))
import market_protocol as protocol


class ContextEfficiencyTests(unittest.TestCase):
    def setUp(self):
        self.connection = {'_descriptor': 'descriptor', 'data_root': 'store', 'project_root': 'project'}
        self.preview = {'status': 'prepared', 'selection': 'exact-plan', 'name': 'sample'}
        self.plan = {'kind': 'plugin', 'status': 'prepared', 'skills': [{'name': 'sample'}],
                     'servers': [], 'routing': [{'selection_stage': 'plugin-ready', 'status': 'selected',
                                                'minimum_confidence': .7, 'confidence': .98}]}
        self.market = Mock()
        self.market.prepare.return_value = self.preview
        self.market.load.return_value = self.plan
        self.market.connect.return_value = {'status': 'connected', 'components': {'skills': 1},
                                           'market_selection': 'exact-plan'}
        self.market.bound_skill_context.return_value = {'need': '中文同义 original need', 'keys': ['sample']}
        self.reader = Mock()
        self.reader.request.side_effect = [
            {'status': 'selected', 'selection': 'skill-receipt', 'content': 'Full unchanged guidance'},
            {'status': 'selected', 'resources': [{'content': 'Full unchanged resource'}]},
        ]
        self.gateway = SimpleNamespace(load_connection=Mock(return_value={'enabled': True}),
                                       Router=Mock(return_value=self.reader))

    def invoke(self, **changes):
        args = {'kind': 'plugin', 'need': '中文同义 original need', 'connect_guidance': True, **changes}
        return protocol.dispatch(self.gateway, self.connection, self.reader, self.market,
                                 'prepare_market_capability', args)

    def test_one_request_composes_existing_checks_and_preserves_full_content(self):
        result = self.invoke()
        self.market.prepare.assert_called_once_with({'kind': 'plugin', 'need': '中文同义 original need'})
        self.market.load.assert_called_once_with('exact-plan')
        self.market.connect.assert_called_once_with('exact-plan')
        self.market.bound_skill_context.assert_called_with('exact-plan')
        self.assertEqual(result['status'], 'connected')
        self.assertEqual(result['guidance']['content'], 'Full unchanged guidance')
        self.assertEqual(result['resource']['resources'][0]['content'], 'Full unchanged resource')
        self.assertEqual(self.reader.request.call_args_list[0].args[1]['need'], '中文同义 original need')
        self.reader.report.assert_not_called()

    def test_omitted_or_false_flag_retains_preview_only(self):
        for flag in [None, False]:
            self.market.reset_mock()
            args = {'kind': 'plugin', 'need': 'need'}
            if flag is not None: args['connect_guidance'] = flag
            result = protocol.dispatch(self.gateway, self.connection, self.reader, self.market,
                                       'prepare_market_capability', args)
            self.assertEqual(result, self.preview)
            self.market.load.assert_not_called()
            self.market.connect.assert_not_called()

    def test_invalid_flag_or_mcp_shortcut_stops_before_preparation(self):
        for changes in [{'connect_guidance': 'yes'}, {'kind': 'mcp'}]:
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'invalid_arguments'):
                self.invoke(**changes)
        self.market.prepare.assert_not_called()

    def test_uncertain_or_failed_preparation_is_never_connected_or_retried(self):
        for status in ['uncertain', 'none', 'setup_required', 'catalog_unavailable']:
            with self.subTest(status=status):
                self.market.prepare.return_value = {'status': status, 'confidence': .69}
                result = self.invoke()
                self.assertEqual(result['status'], status)
        self.market.load.assert_not_called()
        self.market.connect.assert_not_called()

    def test_mixed_plans_and_final_floor_remain_preview_only(self):
        cases = [{'servers': [{'title': 'requires-runtime'}]}, {'kind': 'mcp'},
                 {'skills': []}, {'skills': [{}, {}]}, {'routing': []}]
        for values in [{'status': 'uncertain'}, {'confidence': .69},
                       {'minimum_confidence': .9, 'confidence': .8}, {'minimum_confidence': .1}]:
            row = {**self.plan['routing'][0], **values}; cases.append({'routing': [row]})
        for changes in cases:
            with self.subTest(changes=changes):
                self.market.load.return_value = {**copy.deepcopy(self.plan), **changes}
                result = self.invoke()
                self.assertEqual(result['guidance_setup'], 'preview_only')
                self.assertEqual(result['selection'], 'exact-plan')
        self.market.connect.assert_not_called()

    def test_failed_plan_read_or_changed_status_retains_receipt_without_connect(self):
        self.market.load.side_effect = ValueError('market_connection_changed')
        result = self.invoke()
        self.assertEqual(result['status'], 'reconciliation_required')
        self.assertEqual(result['market_selection'], 'exact-plan')
        self.market.load.side_effect = None
        self.market.load.return_value = {**self.plan, 'status': 'connecting'}
        self.assertEqual(self.invoke()['status'], 'reconciliation_required')
        self.market.connect.assert_not_called()

    def test_connection_unknown_retains_exact_receipt_without_replay(self):
        self.market.connect.side_effect = RuntimeError('market_interrupted')
        result = self.invoke()
        self.assertEqual(result['status'], 'reconciliation_required')
        self.assertEqual(result['market_selection'], 'exact-plan')
        self.assertEqual(result['execution'], 'unknown')
        self.market.prepare.assert_called_once()
        self.market.connect.assert_called_once()
        self.reader.request.assert_not_called()

    def test_disclosure_failure_preserves_connected_fact_and_does_not_repeat_setup(self):
        self.market.bound_skill_context.side_effect = ValueError('market_guidance_changed')
        result = self.invoke()
        self.assertEqual(result['status'], 'connected')
        self.assertEqual(result['guidance']['reason'], 'market_guidance_changed')
        self.market.connect.assert_called_once()
        self.reader.report.assert_not_called()

    def test_revocation_is_rechecked_before_connection(self):
        self.gateway.load_connection.side_effect = [{'enabled': True}, {'enabled': False}, {'enabled': False}]
        with self.assertRaisesRegex(ValueError, 'connection_disabled'):
            self.invoke()
        self.market.connect.assert_not_called()

    def test_catalog_retains_operations_and_schemas_without_duplicated_long_scope(self):
        rows = [{'name': name, 'description': 'Existing operation boundary.',
                 'inputSchema': {'properties': {}, 'required': []}}
                for name in ['acquire_skill', 'acquire_resource', 'report_skill_use', 'acquire_mcp', 'invoke_mcp']]
        before = copy.deepcopy(rows)
        catalog = protocol.tool_catalog(SimpleNamespace(PERSISTENT_TOOLS=rows))
        self.assertEqual(rows, before)
        self.assertEqual(len(catalog), 7)
        self.assertTrue(all(protocol.APPLICATION_SCOPE not in row['description'] for row in catalog))
        prepare = next(row for row in catalog if row['name'] == 'prepare_market_capability')
        self.assertFalse(prepare['inputSchema']['properties']['connect_guidance']['default'])
        self.assertIn('authorized', prepare['description'])
        self.assertIn('Selection grants no permission', prepare['description'])


if __name__ == '__main__':
    unittest.main()
