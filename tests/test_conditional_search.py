"""Recall and execution boundaries for the isolated conditional-find experiment."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'benchmarks/directory-depth'))
from conditional_search import SearchIndex
from conditional_experiment import final_spec, grade


def row(identifier, description, kind='skill'):
    return {'id': identifier, 'name': identifier, 'description': description, 'kind': kind}


class ConditionalSearchTests(unittest.TestCase):
    def index(self, rows):
        index = SearchIndex(rows); self.addCleanup(index.close); return index

    def test_mandatory_later_chinese_topic_has_independent_recall_slot(self):
        rows = [row(str(i), 'Review package vulnerabilities and dependencies.') for i in range(15)]
        rows.append(row('later', 'Company culture values rituals behaviors assessment'))
        result = self.index(rows).search('当前先审查开源包漏洞；后续必须设计文化仪式与价值观行为准则。')
        self.assertIn('later', result['pool'])

    def test_chinese_synonym_and_mixed_language_match(self):
        index = self.index([row('a', 'Audit transitive dependency vulnerabilities license conflicts'),
                            row('b', 'Calculate recurring revenue saas financial health mrr nrr')])
        result = index.search('先查借来的开源包授权条款；随后计算收入和 MRR。')
        self.assertEqual(set(result['pool']), {'a', 'b'})

    def test_typo_expansion_adds_without_replacing_exact_terms(self):
        result = self.index([row('a', 'Observability instrumentation'), row('b', 'Payroll')]).search('observabilty')
        self.assertIn('a', result['pool'])

    def test_unverified_mcp_is_not_inferred_to_violate_no_connection(self):
        result = self.index([row('a', 'Offline financial revenue analysis', 'mcp')]).search('只分析财务收入，不连接真实系统。')
        self.assertIn('a', result['pool'])
        self.assertEqual(result['hard_conditions'], {})

    def test_explicit_kind_filter_applies_before_recall_slots(self):
        rows = [row(str(i), 'Review financial revenue mrr nrr', 'mcp') for i in range(20)]
        rows.append(row('wanted', 'Financial revenue analysis'))
        result = self.index(rows).search('financial revenue', per_clause=1, allowed_kinds=['skill'])
        self.assertEqual(result['pool'], ['wanted'])

    def test_boundary_ties_and_global_overflow_never_silently_truncate(self):
        result = self.index([{**row(str(i), 'Identical capabilities revenue'), 'name': 'same'}
                             for i in range(120)]).search('revenue')
        self.assertEqual(result['status'], 'widen_required')
        self.assertEqual(result['pool_size'], 120)
        self.assertGreater(result['boundary_ties'], 0)

    def test_alias_descriptions_retained_and_plugin_not_split(self):
        item = {**row('whole', 'Package', 'plugin'), 'descriptions': ['Culture rituals planning']}
        result = self.index([item]).search('文化仪式')
        self.assertEqual(result['pool'], ['whole'])

    def test_cancellation_is_preserved_for_jev_not_naively_hard_filtered(self):
        result = self.index([row('a', 'Financial revenue'), row('b', 'Product discovery rice')]).search('财务收入取消；当前做 RICE 产品发现。')
        self.assertIn('a', result['pool']); self.assertIn('b', result['pool'])

    def test_source_popularity_and_gold_fields_do_not_change_recall(self):
        rows = [row('a', 'Culture rituals'), row('b', 'Revenue mrr')]
        changed = [{**r, 'source': 'other', 'measurements': {'stars': 999999}, 'expected_ids': ['fake']} for r in rows]
        self.assertEqual(self.index(rows).search('文化')['pool'], self.index(changed).search('文化')['pool'])

    def test_no_lexical_match_is_not_a_confirmed_semantic_no_match(self):
        result = self.index([row('a', 'Revenue')]).search('astronomy')
        self.assertEqual(result['status'], 'no_lexical_match')
        self.assertEqual(result['semantic_completeness'], 'unproven')

    def test_final_choice_keeps_complete_description_and_baseline_order(self):
        rows = [row('a', 'Full details about first'), row('b', 'Full details about second')]
        spec = final_spec(rows, ['b', 'a'], 'Original question')
        choices = spec['questions']['answer']['criteria']
        self.assertEqual(list(choices), ['a', 'b', 'none'])
        self.assertEqual(choices['b'], rows[1]['description'])

    def test_correct_current_is_failure_if_later_reference_was_lost(self):
        case = {'expected_ids': ['a'], 'pending_ids': ['b']}
        result = {'status': 'selected', 'choice': 'a', 'traces': [{'pool': ['a']}]}
        self.assertFalse(grade(case, result)['omission_safe_pass'])
        self.assertEqual(grade(case, result)['first_lost']['b'], 1)


if __name__ == '__main__':
    unittest.main()
