import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmarks/directory-depth'))
import breadth_experiment as B


class BreadthDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.cases = B.read(B.FIXTURES)['cases']
        folder = B.FIXTURES.parent
        self.old = B.read(folder / 'expanded_cases.json')['cases'] + B.read(folder / 'large_public_cases.json')['cases']
        tax = B.read(folder / 'large_public_directory.json')
        leaves = {leaf['id']: leaf for leaf in tax['leaves']}
        members = {key for leaf in leaves.values() for key in leaf['members']}
        self.catalog = [{'id': key, 'source_domains': [leaf['id'] for leaf in leaves.values() if key in leaf['members']]} for key in members]
        self.nodes = {root['id']: {'depth': 1, 'members': sorted({key for child in root['children'] for key in leaves[child]['members']})} for root in tax['roots']}

    def check(self, cases=None, old=None):
        return B.validate_cases(cases or self.cases, self.old if old is None else old, self.catalog, self.nodes)

    def test_unseen_targets_span_all_roots_and_fourteen_domains(self):
        result = self.check()
        self.assertEqual(len(result['new_target_ids']), 20)
        self.assertEqual(len(result['roots']), 6)
        self.assertEqual(len(result['source_domains']), 14)
        self.assertEqual(result['cross_root_multi_cases'], 4)
        self.assertEqual(result['positive_cases'], 24)

    def test_previously_tested_target_rejected(self):
        old = self.old + [copy.deepcopy(self.cases[4])]
        with self.assertRaisesRegex(ValueError, 'targets_not_new'):
            self.check(old=old)

    def test_capability_name_in_request_rejected(self):
        cases = copy.deepcopy(self.cases)
        cases[4]['need'] += ' dependency-auditor'
        with self.assertRaisesRegex(ValueError, 'named_target'):
            self.check(cases)

    def test_same_root_multi_task_rejected(self):
        cases = copy.deepcopy(self.cases)
        cases[-1]['pending_ids'] = ['capacity-planner']
        with self.assertRaisesRegex(ValueError, 'multi_task_not_cross_root'):
            self.check(cases)

    def test_duplicate_needs_rejected(self):
        cases = copy.deepcopy(self.cases)
        cases[-1]['need'] = cases[-2]['need']
        with self.assertRaisesRegex(ValueError, 'invalid_case_set'):
            self.check(cases)


if __name__ == '__main__':
    unittest.main()
