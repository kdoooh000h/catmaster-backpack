"""Coverage, provenance and bounded semantic classification, with no live model."""
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adapters/codex'))
import market_directory as directory


class DirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        def safe(path):
            path = Path(path)
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise ValueError('unsafe_path')
            return path
        def read(path):
            path = safe(path)
            if stat.S_IMODE(path.stat().st_mode) & 0o077:
                raise ValueError('unsafe_record')
            return json.loads(path.read_text())
        def write(path, value):
            path.write_text(json.dumps(value));path.chmod(0o600)
        self.module = SimpleNamespace(public_access=SimpleNamespace(safe=safe, owner_json=read),
                                      runtime=SimpleNamespace(_atomic_json=write))
        self.config = {'provider': 'jev-cli', 'executable': '/unused/jev', 'jev_provider': 'typesafe'}

    def test_reuses_all_declared_labels_and_keeps_cross_membership(self):
        rows = [{'name':'audit', 'description':'review changes', 'entry':{'category':'security','keywords':['testing']}}]
        with patch('market_directory.subprocess.run') as provider:
            memberships = directory.classify(rows, 'plugin', self.data, self.config, self.module)
        self.assertEqual(set(memberships[0]), {'security','software'})
        provider.assert_not_called()
        _, groups, pending = directory.directories(rows, memberships)
        self.assertEqual(groups['software'], rows);self.assertEqual(groups['security'], rows)
        self.assertEqual(pending, [])

    def test_every_row_is_covered_and_pending_accompanies_every_selected_topic(self):
        rows = [{'name':str(i),'description':'publisher facts'} for i in range(4)]
        _, groups, pending = directory.directories(rows, {0:['software'],1:['visual'],2:[],3:['visual','software']})
        self.assertEqual({r['name'] for group in groups.values() for r in group} | {r['name'] for r in pending},
                         {r['name'] for r in rows})
        self.assertEqual(directory.pool(rows, groups['software'], pending), [rows[0],rows[2],rows[3]])
        self.assertEqual(directory.pool(rows, groups['visual'], pending), [rows[1],rows[2],rows[3]])

    def test_description_preserves_original_and_labels_guidance_vs_execution(self):
        row = {'name':'example','description':'publisher exact description','tags':['quality']}
        card = directory.describe(row,'skill')
        self.assertIn(row['description'],card)
        self.assertIn('Guidance',card)
        self.assertIn('schema',directory.describe(row,'mcp'))
        self.assertNotIn('unavailable',directory.describe(row,'plugin'))

    def provider(self, argv, **kwargs):
        spec = json.loads(Path(argv[-1]).read_text())
        state = json.loads(Path(argv[argv.index('--state')+1][1:]).read_text())
        self.assertNotIn('need',state)
        answers = {key:{'choice':'software' if key.endswith('primary') else 'security','confidence':.8}
                   for key in spec['questions']}
        return SimpleNamespace(returncode=0,stdout=json.dumps({'answers':answers}))

    def test_semantic_labels_are_cached_by_exact_metadata_and_low_scores_stay_pending(self):
        rows = [{'name':'example','description':'Review actual local code'}]
        with patch('market_directory.subprocess.run',side_effect=self.provider) as provider:
            first = directory.classify(rows,'plugin',self.data,self.config,self.module)
            second = directory.classify(rows,'plugin',self.data,self.config,self.module)
        self.assertEqual(first,{0:['software','security']});self.assertEqual(first,second)
        self.assertEqual(provider.call_count,1)
        for path in (self.data/'market-classification').glob('*.json'):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
        rows[0]['description'] += ' changed'
        answer = SimpleNamespace(returncode=0,stdout=json.dumps({'answers':{'0_primary':{'choice':'software','confidence':.39}}}))
        with patch('market_directory.subprocess.run',return_value=answer) as provider:
            self.assertEqual(directory.classify(rows,'plugin',self.data,self.config,self.module),{0:[]})
            self.assertEqual(directory.classify(rows,'plugin',self.data,self.config,self.module),{0:[]})
        self.assertEqual(provider.call_count,1)

    def test_unknown_provider_outcome_is_not_replayed_and_unclassified_rows_remain(self):
        rows = [{'name':str(i),'description':'unknown metadata'} for i in range(20)]
        import subprocess
        with patch('market_directory.subprocess.run',side_effect=subprocess.TimeoutExpired('jev',1)) as provider:
            memberships = directory.classify(rows,'plugin',self.data,self.config,self.module)
        self.assertEqual(provider.call_count,1)
        self.assertEqual(len(memberships),20)
        _, groups, pending = directory.directories(rows,memberships)
        self.assertEqual(groups,{});self.assertEqual(pending,rows)

    def test_symlink_and_malformed_cached_classification_stop(self):
        row = {'name':'example','description':'Review code'}
        folder = self.data/'market-classification';folder.mkdir(mode=0o700)
        path = folder/(directory._identity(row,'plugin',self.config)+'.json')
        path.write_text('{}');path.chmod(0o600)
        with self.assertRaisesRegex(ValueError,'invalid_market_classification'):
            directory.classify([row],'plugin',self.data,self.config,self.module)
        other = self.data/'other';other.write_text('{}')
        path.unlink();path.symlink_to(other)
        with self.assertRaisesRegex(ValueError,'unsafe_path'):
            directory.classify([row],'plugin',self.data,self.config,self.module)

    def test_classification_batches_and_per_request_bound_keep_remaining_entries_pending(self):
        rows = [{'name':str(i),'description':'documented function'} for i in range(40)]
        with patch('market_directory.subprocess.run',side_effect=self.provider) as provider:
            memberships = directory.classify(rows,'plugin',self.data,self.config,self.module)
        self.assertEqual(provider.call_count,4)
        self.assertTrue(all(memberships[i] for i in range(32)))
        self.assertTrue(all(not memberships[i] for i in range(32,40)))

    def test_large_complete_catalog_reuses_labels_without_a_full_choice_call(self):
        rows = [{'name':str(i),'description':'documented function','category':'development'} for i in range(400)]
        with patch('market_directory.subprocess.run') as provider:
            memberships=directory.classify(rows,'plugin',self.data,self.config,self.module)
        provider.assert_not_called()
        self.assertEqual(len(memberships),400)
        self.assertTrue(all(value==['software'] for value in memberships.values()))


if __name__ == '__main__':
    unittest.main()
