"""Dictionary-derived, additive lexical hints for the local recall benchmark.

The caller supplies a CC-CEDICT text snapshot or path; this module never fetches
or installs one. Matches are evidence about dictionary headwords, not a
translation, task summary, or claim of semantic completeness. Callers must keep
the original need alongside these hints, including ambiguity and cancellation.
"""
from collections import defaultdict
from pathlib import Path
import re


_HAN = r'\u3400-\u9fff\uf900-\ufaff\U00020000-\U0002ebef\U00030000-\U000323af'
_RUN = re.compile('[' + _HAN + ']+')
_ENTRY = re.compile(r'^(\S+)\s+(\S+)\s+\[[^\]]+\]\s+/(.*)/$')
_BRACKETS = re.compile(r'\[[^\]]*\]')
_LABELS = re.compile(r'^(?:\s*\([^()]*\)\s*)+')
_REFERENCE = re.compile(
    r'^(?:(?:[a-z-]+\s+)*variant of|(?:also\s+)?see(?: also)?|same as|equivalent to)(?:\s|$)',
    re.I)
_CLASSIFIER = re.compile(r'^(?:CL\s*:|classifiers?\b|measure words?\b)', re.I)
_PRONUNCIATION = (
    r'(?:(?:also|commonly|usually|often|sometimes|Taiwan|Tw|Mandarin|formerly)\s+)*'
    r'(?:pr\.|pronounced\b|pronunciation\b)\s*(?::|is)?\s*\[')
_PRONUNCIATION_ONLY = re.compile('^' + _PRONUNCIATION, re.I)
_PRONUNCIATION_NOTE = re.compile(
    r'\([^()]*\b(?:pr\.|pronounced\b|pronunciation\b)\s*(?::|is)?\s*\[[^()]*\)', re.I)
_PRONUNCIATION_TAIL = re.compile(r'[,;]\s*' + _PRONUNCIATION + r'.*$', re.I)
_ABBREVIATION = re.compile(r'^(?:abbr\.? for|abbreviation (?:of|for))\s+', re.I)
_PARENTHETICAL = re.compile(r'\(([^()]*)\)')


def _gloss_terms(gloss, tokenize):
    """Discard lexical metadata while leaving the original gloss untouched."""
    value = _LABELS.sub('', gloss).strip()
    if (_REFERENCE.match(value) or _CLASSIFIER.match(value)
            or _PRONUNCIATION_ONLY.match(value)):
        return ()
    value = _PRONUNCIATION_NOTE.sub('', value)
    value = _PARENTHETICAL.sub(
        lambda match: '' if _REFERENCE.match(match.group(1).strip()) else match.group(), value)
    value = _PRONUNCIATION_TAIL.sub('', value)
    value = _BRACKETS.sub('', value)
    value = _ABBREVIATION.sub('', value)
    # conditional_search.terms also emits Chinese bigrams. Only English-side
    # tokens belong in dictionary hints; referenced headwords are not hints.
    return tuple(word for word in tokenize(value) if word.isascii())


class BilingualDictionary:
    """Parse multi-character Han headwords and retain every usable sense.

    Exactly one of ``text`` or ``path`` is required. ``matches`` returns fresh
    dictionaries with the matched spelling, exact per-sense source gloss, and
    English tokens. A supplied vocabulary filters only those tokens; even a
    zero-token match remains auditable and still follows longest-match rules.
    """

    def __init__(self, *, text=None, path=None):
        if (text is None) == (path is None):
            raise ValueError('provide_exactly_one_dictionary_source')
        if path is not None:
            text = Path(path).read_text(encoding='utf-8-sig')
        if not isinstance(text, str):
            raise TypeError('dictionary_text_must_be_string')
        # Lazy import allows conditional_search to import this module before
        # defining terms, while keeping one tokenizer and stop-word policy.
        from conditional_search import terms

        entries = defaultdict(list)
        for line in text.splitlines():
            parsed = _ENTRY.fullmatch(line.strip())
            if parsed is None:
                continue
            traditional, simplified, glosses = parsed.groups()
            senses = []
            for gloss in glosses.split('/'):
                words = _gloss_terms(gloss, terms)
                if words and (gloss, words) not in senses:
                    senses.append((gloss, words))
            if not senses:
                continue
            for headword in dict.fromkeys((traditional, simplified)):
                if len(headword) < 2 or _RUN.fullmatch(headword) is None:
                    continue
                for sense in senses:
                    if sense not in entries[headword]:
                        entries[headword].append(sense)
        self._entries = {word: tuple(senses) for word, senses in entries.items()}
        lengths = defaultdict(set)
        for headword in self._entries:
            lengths[headword[0]].add(len(headword))
        self._lengths = {first: tuple(sorted(values, reverse=True))
                         for first, values in lengths.items()}

    def matches(self, need, *, vocabulary=None):
        """Greedily match each Han run; skip unknown/isolated characters.

        No match crosses punctuation or an English span. Repeated occurrences
        and distinct senses remain in the audit, in source encounter order.
        The input and any caller-owned vocabulary are never modified.
        """
        if not isinstance(need, str):
            raise TypeError('need_must_be_string')
        allowed = None if vocabulary is None else frozenset(vocabulary)
        result = []
        for run in _RUN.finditer(need):
            value = run.group()
            position = 0
            while position < len(value):
                headword = None
                for length in self._lengths.get(value[position], ()):
                    if position + length <= len(value):
                        candidate = value[position:position + length]
                        if candidate in self._entries:
                            headword = candidate
                            break
                if headword is None:
                    position += 1
                    continue
                for gloss, words in self._entries[headword]:
                    result.append({'headword': headword, 'gloss': gloss,
                                   'terms': [word for word in words
                                             if allowed is None or word in allowed]})
                position += len(headword)
        return result

    def expand(self, need, *, vocabulary=None):
        """Return deduplicated additive search hints, preserving encounter order."""
        return list(dict.fromkeys(word for match in self.matches(need, vocabulary=vocabulary)
                                  for word in match['terms']))
