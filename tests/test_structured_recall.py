from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'benchmarks/directory-depth'))
from structured_recall import StructuredIndex, matches, positive_metadata
from conditional_search import SearchIndex
import structured_recall_experiment as X
from current_step import ORIGINAL_LEAD


def row(identifier, name, description, kind='skill', topics=None):
    return {'id': identifier, 'name': name, 'description': description, 'kind': kind, 'topics': topics or []}


class StructuredRecallTests(unittest.TestCase):
    def search(self, rows, need, pool=None, **kw):
        index = StructuredIndex(rows)
        try:
            base = {'pool': pool or [], 'catalog_count': len(rows), 'seconds': 0, 'hard_conditions': {}}
            return index.search(need, base, **kw)
        finally: index.close()

    def test_bilingual_objects_and_actions_share_vocabulary(self):
        self.assertEqual(matches('清洗工作簿，生成公式和图表', 'objects'), ['spreadsheet'])
        self.assertEqual(matches('clean spreadsheet, create formulas and charts', 'objects'), ['spreadsheet'])
        self.assertEqual(matches('清洗工作簿，生成公式和图表', 'actions'),
                         matches('clean spreadsheet, create formulas and charts', 'actions'))

    def test_explicit_format_anchor_preserves_long_original_description(self):
        rows = [row('long', 'docx', 'Create Word documents. '+'General documentation. '*100),
                row('short', 'Word service', 'Create Word documents.')]
        result = self.search(rows, '创建 Word 文档，带页码', per_kind=1)
        self.assertIn('long', result['pool'])
        self.assertIn('long', result['queries'][0]['hits'])

    def test_existing_category_affects_facet_ranking(self):
        rows = [row('wrong', 'Alpha', 'Read Word documents.', topics=['data']),
                row('right', 'Bravo', 'Read Word documents.', topics=['writing'])]
        result = self.search(rows, '读取 Word 文档', per_kind=1)
        self.assertIn('right', result['pool']); self.assertNotIn('wrong', result['pool'])

    def test_action_affects_facet_ranking(self):
        rows = [row('create', 'Alpha', 'Create Word documents.'), row('read', 'Bravo', 'Read Word documents.')]
        result = self.search(rows, '读取 Word 文档', per_kind=1)
        self.assertIn('read', result['pool']); self.assertNotIn('create', result['pool'])

    def test_negative_metadata_is_not_a_positive_object_hint(self):
        text = 'Create spreadsheets. Do NOT use for Word documents.'
        self.assertNotIn('word', matches(positive_metadata(text), 'objects'))
        self.assertIn('spreadsheet', matches(positive_metadata(text), 'objects'))

    def test_whole_plugins_and_all_kinds_keep_independent_slots(self):
        rows = [row('skill', 'guide', 'Create PDF files.'), row('plugin', 'bundle', 'Create PDF files.', 'plugin')]
        rows += [row('mcp'+str(i), 'server '+str(i), 'Create PDF files.', 'mcp') for i in range(12)]
        result = self.search(rows, '生成 PDF', per_kind=1)
        self.assertIn('skill', result['pool']); self.assertIn('plugin', result['pool'])
        self.assertEqual(len(result['pool']), len(set(result['pool'])))
        self.assertFalse(any('child' in i for i in result['pool']))

    def test_boundary_ties_are_not_cut_to_fit(self):
        rows = [row(str(i), 'server '+str(i), 'Create PDF files.', 'mcp') for i in range(6)]
        result = self.search(rows, '生成 PDF', per_kind=1, max_candidates=3)
        self.assertEqual(set(result['pool']), {r['id'] for r in rows})
        self.assertEqual(result['status'], 'widen_required')
        self.assertGreater(result['boundary_ties'], 0)

    def test_baseline_candidates_and_later_objects_are_never_pruned(self):
        rows = [row('old', 'legacy', 'Unrelated old recall.'), row('now', 'docx', 'Create Word documents.'),
                row('later', 'xlsx', 'Create spreadsheets.')]
        result = self.search(rows, '当前创建 Word 文档，后续也要生成工作簿', pool=['old'])
        self.assertEqual(set(result['pool']), {'old', 'now', 'later'})
        self.assertTrue(result['baseline_preserved'])

    def test_explicit_kind_condition_is_respected(self):
        rows = [row('skill', 'pdf', 'Create PDF files.'), row('mcp', 'pdf', 'Create PDF files.', 'mcp')]
        lexical = SearchIndex(rows); index = StructuredIndex(rows)
        try:
            base = lexical.search('PDF', allowed_kinds=['skill'])
            result = index.search('PDF', base)
            self.assertEqual(result['pool'], ['skill']); self.assertEqual(result['catalog_count'], 1)
        finally: lexical.close(); index.close()

    def test_alias_description_and_publisher_label_are_indexed(self):
        rows = [row('a', 'Alpha', 'General file support.')]
        rows[0].update(descriptions=['Create Word documents.'], publisher_labels=['writing'])
        result = self.search(rows, '创建 Word 文档')
        self.assertIn('a', result['pool'])

    def test_popularity_identity_and_gold_cannot_change_results(self):
        rows = [row('a', 'Alpha', 'Create PDF files.'), row('b', 'Bravo', 'Read PDF files.')]
        changed = deepcopy(rows)
        changed[0].update(rank=999999, growth=-100, expected_ids=['a'], source='preferred market')
        self.assertEqual(self.search(rows, '读取 PDF', per_kind=1)['pool'],
                         self.search(changed, '读取 PDF', per_kind=1)['pool'])

    def test_unknown_topic_does_not_erase_old_recall(self):
        rows = [row('a', 'Alpha', 'A niche operation.')]
        self.assertEqual(self.search(rows, '做一个独特任务', pool=['a'])['pool'], ['a'])

    def test_word_counter_is_not_a_word_document_hint(self):
        self.assertNotIn('word', matches('Word Counter API: count words in text.', 'objects'))


class StructuredRunnerTests(unittest.TestCase):
    def run_fake(self, failure=False, token_cap=140000):
        seen=[]
        class Provider:
            def __init__(self, *a, **kw): self.calls=[]
            def noul(self,spec,state):
                seen.append((spec,state))
                if failure:
                    self.calls.append({'outcome':'unknown_no_replay','seconds':.1})
                    raise TimeoutError('unknown_no_replay')
                self.calls.append({'outcome':'completed','seconds':.1,'input_tokens':10,'output_tokens':2})
                return {'answers':{'answer':{'type':'choice','choice':'current','confidence':.7}}}
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp); bundle=out/'bundle'; bundle.mkdir()
            def save(path,value): path.write_text(json.dumps(value))
            save(bundle/'catalog.json',[row('current','one','Current step.'),row('later','two','Later step.')])
            save(bundle/'question.json',{'question':ORIGINAL_LEAD+'Respect raw task.'})
            save(out/'cases.json',[{'id':'synthetic','need':'先做当前步骤，再做后续步骤','expected_ids':['current'],'pending_ids':['later']}])
            save(out/'preflight.json',{'ready':True,'candidate_reference_coverage':True})
            save(out/'synthetic.recall.json',{'basis':'synthetic','recalls':{
                X.ARMS[0]:{'pool':['current'],'seconds':.01}, X.ARMS[1]:{'pool':['current','later'],'seconds':.02}}})
            plan={'executable':'unused','max_seconds':120,'max_calls':2,'max_tokens':token_cap}
            with patch.object(X,'verify_frozen',return_value=(plan,bundle)), patch.object(X.C.E,'JevHierarchyProvider',Provider), contextlib.redirect_stdout(io.StringIO()):
                X.run(out)
            result=json.loads((out/'live/summary.json').read_text())
        return result,seen

    def test_actual_runner_keeps_one_call_and_raw_need_per_arm(self):
        result,seen=self.run_fake()
        self.assertEqual(result['stop'],'completed');self.assertEqual(result['calls'],2)
        self.assertEqual(result['known_tokens'],24)
        self.assertTrue(all(s=={'task':'先做当前步骤，再做后续步骤'} for _,s in seen))
        by_arm={r['arm']:r for r in result['rows']}
        self.assertFalse(by_arm[X.ARMS[0]]['omission_safe_pass'])
        self.assertTrue(by_arm[X.ARMS[1]]['omission_safe_pass'])
        self.assertTrue(all(len(spec['questions'])==1 for spec,_ in seen))

    def test_actual_runner_unknown_outcome_stops_without_retry(self):
        result,seen=self.run_fake(failure=True)
        self.assertEqual(result['stop'],'unknown_no_replay');self.assertEqual(len(seen),1)
        self.assertEqual(result['calls'],1);self.assertFalse(result['rows'])

    def test_actual_runner_budget_stops_before_send(self):
        result,seen=self.run_fake(token_cap=0)
        self.assertEqual(result['stop'],'budget_stop');self.assertEqual(seen,[])


if __name__ == '__main__': unittest.main()
