"""Dictionary parsing and lexical-hint boundaries, using a tiny local fixture."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmarks/directory-depth'))
from bilingual_terms import BilingualDictionary
from conditional_search import terms


FIXTURE = '''# A small CC-CEDICT-format test fixture, not a dictionary download.
圖書 图书 [tu2 shu1] /books/
圖書館 图书馆 [tu2 shu1 guan3] /library/CL:家[jia1],個|个[ge4]/
長大 长大 [zhang3 da4] /to grow up/
長大 长大 [chang2 da4] /large; great/
山 山 [shan1] /mountain/
山水 山水 [shan1 shui3] /landscape/
樂隊 乐队 [yue4 dui4] /band (music)/orchestra/
'''


class BilingualDictionaryTests(unittest.TestCase):
    def dictionary(self, extra=''):
        return BilingualDictionary(text=FIXTURE + extra)

    def test_traditional_and_simplified_aliases_keep_matched_spelling(self):
        dictionary = self.dictionary()
        for spelling in ('圖書館', '图书馆'):
            self.assertEqual(dictionary.matches(spelling), [
                {'headword': spelling, 'gloss': 'library', 'terms': ['library']}])

    def test_greedy_longest_match_skips_unknowns_and_resumes(self):
        matches = self.dictionary().matches('去图书馆和图书')
        self.assertEqual([match['headword'] for match in matches], ['图书馆', '图书'])
        self.assertEqual([match['terms'] for match in matches], [['library'], ['books']])

    def test_punctuation_and_english_are_run_boundaries(self):
        self.assertEqual(self.dictionary().matches('图，书馆 图English书馆'), [])

    def test_duplicate_entries_and_multiple_senses_are_additive(self):
        dictionary = self.dictionary('樂隊 乐队 [yue4 dui4] /orchestra/\n')
        self.assertEqual(dictionary.expand('长大和乐队'),
                         ['grow', 'up', 'large', 'great', 'band', 'music', 'orchestra'])
        self.assertEqual([match['gloss'] for match in dictionary.matches('长大')],
                         ['to grow up', 'large; great'])
        self.assertEqual(len(dictionary.matches('乐队')), 2)

    def test_single_characters_are_never_dictionary_expansions(self):
        dictionary = self.dictionary()
        self.assertEqual(dictionary.expand('山，水'), [])
        self.assertEqual(dictionary.expand('山水'), ['landscape'])

    def test_vocabulary_filters_terms_without_shorter_fallback_or_mutation(self):
        vocabulary = {'books', 'music'}
        matches = self.dictionary().matches('图书馆乐队', vocabulary=vocabulary)
        self.assertEqual(matches[0], {'headword': '图书馆', 'gloss': 'library', 'terms': []})
        self.assertEqual(self.dictionary().expand('图书馆乐队', vocabulary=vocabulary), ['music'])
        self.assertEqual(vocabulary, {'books', 'music'})
        self.assertEqual(self.dictionary().expand('乐队', vocabulary=set()), [])

    def test_exact_gloss_is_retained_but_metadata_is_not_a_search_hint(self):
        dictionary = self.dictionary('''樂團 乐团 [yue4 tuan2] /  musical ensemble (also pr. [yue4])  /also pr. [le4]/see 樂隊|乐队[yue4 dui4]/old variant of 樂隊|乐队[yue4 dui4]/CL:個|个[ge4]/
縮寫 缩写 [suo1 xie3] /abbr. for application programming interface/
''')
        matches = dictionary.matches('乐团')
        self.assertEqual(matches, [{'headword': '乐团',
                                   'gloss': '  musical ensemble (also pr. [yue4])  ',
                                   'terms': ['musical', 'ensemble']}])
        self.assertEqual(dictionary.expand('缩写'), ['application', 'programming', 'interface'])

    def test_reference_pinyin_does_not_become_english_tokens(self):
        dictionary = self.dictionary('''音樂 音乐 [yin1 yue4] /music (see also 樂隊|乐队[yue4 dui4])/
''')
        words = dictionary.expand('音乐')
        self.assertEqual(words, ['music'])

    def test_real_pronunciation_and_see_saw_glosses_are_not_metadata(self):
        dictionary = self.dictionary('''發音 发音 [fa1 yin1] /pronunciation/
翹板 翘板 [qiao4 ban3] /see-saw/
''')
        self.assertEqual(dictionary.expand('发音'), ['pronunciation'])
        self.assertEqual(dictionary.expand('翘板'), ['see', 'saw'])

    def test_token_policy_is_shared_and_raw_need_results_are_not_rewritten(self):
        dictionary = self.dictionary()
        need = '先看图书；取消乐队。KEEP this original need!'
        original = need
        result = dictionary.matches(need)
        self.assertEqual(result[0]['terms'], terms('books'))
        result[0]['terms'].append('injected')
        result[0]['gloss'] = 'changed'
        self.assertEqual(dictionary.matches(need)[0],
                         {'headword': '图书', 'gloss': 'books', 'terms': ['books']})
        self.assertEqual(need, original)
        self.assertEqual(dictionary.expand('图书图书'), ['books'])
        self.assertEqual(len(dictionary.matches('图书图书')), 2)

    def test_invalid_lines_and_empty_or_metadata_only_glosses_are_ignored(self):
        dictionary = BilingualDictionary(text='''# comment
this is malformed
空白 空白 [kong1 bai2] //
空白 空白 [kong1 bai2] /   /
空白 空白 [kong1 bai2] /see 圖書|图书[tu2 shu1]/
空白 空白 [kong1 bai2] /nonstandard variant of 圖書|图书[tu2 shu1]/
空白 空白 [kong1 bai2] /CL:個|个[ge4]/
空白 空白 [kong1 bai2] /Taiwan pr. [kong4 bai2]/
空白 空白 [] /blank/
空白 空白 [kong1 bai2] missing delimiters
''')
        self.assertEqual(dictionary.matches('空白'), [])
        self.assertEqual(dictionary.matches(''), [])

    def test_explicit_source_contract_and_local_path(self):
        for arguments in ({}, {'text': FIXTURE, 'path': 'not-read'}):
            with self.assertRaises(ValueError):
                BilingualDictionary(**arguments)
        with self.assertRaises(TypeError):
            BilingualDictionary(text=b'bytes')
        with self.assertRaises(TypeError):
            self.dictionary().matches(None)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cedict.txt'
            path.write_text('\ufeff' + FIXTURE, encoding='utf-8')
            self.assertEqual(BilingualDictionary(path=path).matches('图书馆'),
                             self.dictionary().matches('图书馆'))


if __name__ == '__main__':
    unittest.main()
