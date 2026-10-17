"""Current-focused local ranking with an intact later-step reservoir.

Dictionary glosses and retrieval scores are hints, not a translation, capability
proof, or permission. A bounded shortlist can miss a valid item; callers must
report its coverage separately from the retained reservoir.
"""
from collections import defaultdict
import re
import sqlite3
import time

import numpy as np

from conditional_search import CONCEPTS, terms
import independent_current as I


LATER = re.compile(r'之后|然后|随后|完成后|结束后|查清后|afterwards\b|subsequently\b|after that\b', re.I)


def current_hint(need):
    """A conservative ordering hint only; Jev always receives the raw need."""
    if not isinstance(need, str) or not need.strip():
        raise ValueError('empty_need')
    split = LATER.search(need)
    return need[:split.start()].strip(' ，,；;。') if split and split.start() else need


class FocusedIndex:
    def __init__(self, rows, dictionary, semantic):
        self.rows = list(rows)
        self.dictionary = dictionary
        self.semantic = semantic
        self.ids = [r['id'] for r in rows]
        if len(set(self.ids)) != len(self.ids) or semantic.ids != self.ids:
            raise ValueError('catalog_mismatch')
        self.db = sqlite3.connect(':memory:')
        self.db.execute("CREATE VIRTUAL TABLE focused USING fts5(name,description,labels,kind UNINDEXED,tokenize='porter unicode61')")
        records = []
        self.vocabulary = set()
        for n, row in enumerate(rows, 1):
            description = ' '.join(dict.fromkeys([row['description']] + row.get('descriptions', [])))
            fields = [terms(row['name']), terms(description), terms(' '.join(row.get('topics', []) + row.get('publisher_labels', [])))]
            self.vocabulary.update(t for field in fields for t in field if t.isascii())
            records.append((n, *[' '.join(f) for f in fields], row['kind']))
        self.db.executemany('INSERT INTO focused(rowid,name,description,labels,kind) VALUES (?,?,?,?,?)', records)

    def close(self):
        self.db.close()

    def search(self, need, baseline, *, per_kind=24, per_route=3, shortlist_size=12,
               strategy='rrf', max_shortlist=48, max_reservoir=384):
        started = time.monotonic()
        if any(type(x) is not int or x < 1 for x in [per_kind, per_route, shortlist_size, max_shortlist, max_reservoir]):
            raise ValueError('invalid_limit')
        if per_route > per_kind or max_shortlist > 48 or strategy not in ['rrf', 'per_route']:
            raise ValueError('invalid_limit')
        kinds = baseline.get('hard_conditions', {}).get('allowed_kinds', ['skill', 'plugin', 'mcp'])
        if not set(kinds) <= {'skill', 'plugin', 'mcp'}:
            raise ValueError('unknown_kind')
        allowed = {r['id'] for r in self.rows if r['kind'] in kinds}
        if baseline['catalog_count'] != len(allowed) or not set(baseline['pool']) <= allowed:
            raise ValueError('baseline_mismatch')
        focus = current_hint(need)
        matches = self.dictionary.matches(focus, vocabulary=self.vocabulary)
        # Compare all dictionary senses with a corpus-independent first-sense
        # variant. Both keep the complete audit and make no translation claim.
        first_senses = {}
        for match in matches:
            first_senses.setdefault(match['headword'], match)
        query_senses = matches if strategy == 'rrf' else first_senses.values()
        gloss_words = list(dict.fromkeys(w for match in query_senses for w in match['terms']))
        words = terms(focus) + gloss_words
        for triggers, english in CONCEPTS:
            if any(t in focus.casefold() for t in triggers.split()):
                words.extend(terms(english))
        query = ' OR '.join('"' + w + '"' for w in dict.fromkeys(words))
        rankings = []
        for kind in kinds:
            weight = 3 if strategy == 'rrf' else 6
            hits = self.db.execute(f'SELECT rowid,bm25(focused,{weight},1,.5) AS score FROM focused WHERE focused MATCH ? AND kind=? ORDER BY score,rowid', (query, kind)).fetchall() if query else []
            if hits:
                boundary = hits[min(per_kind, len(hits))-1][1]
                hits = [(n, score) for n, score in hits if score <= boundary]
            rankings.append({'route': 'dictionary_lexical', 'kind': kind,
                             'hits': [self.ids[n-1] for n, _ in hits], 'scores': [score for _, score in hits]})
        dense_queries = [('current_dense', focus)]
        if gloss_words and strategy == 'per_route':
            dense_queries.append(('gloss_dense', ' '.join(dict.fromkeys([w for w in terms(focus) if w.isascii()] + gloss_words))))
        vector = np.asarray(self.semantic.encode([self.semantic.query_prefix + q for _, q in dense_queries]), dtype=np.float32)
        if (vector.shape != (len(dense_queries), self.semantic.vectors.shape[1]) or not np.isfinite(vector).all()
                or not np.allclose(np.linalg.norm(vector, axis=1), 1, atol=.001)):
            raise ValueError('invalid_query_vector')
        for (route, _), scores in zip(dense_queries, vector @ self.semantic.vectors.T):
            for kind in kinds:
                indices = self.semantic.by_kind.get(kind, np.array([], dtype=int))
                order = indices[np.argsort(-scores[indices], kind='stable')]
                if len(order):
                    boundary = scores[order[min(per_kind, len(order))-1]]
                    order = order[scores[order] >= boundary]
                rankings.append({'route': route, 'kind': kind,
                                 'hits': [self.ids[n] for n in order], 'scores': [float(scores[n]) for n in order]})
        # Reciprocal ranks do not become Jev confidence. Equal retrieval scores
        # receive equal ranks. RRF preserves its fused boundary ties; the
        # alternative per-route variant retains each route's selected items.
        fused = defaultdict(float)
        selected = set()
        for ranking in rankings:
            if ranking['hits']:
                boundary = ranking['scores'][min(per_route, len(ranking['hits']))-1]
                # lexical BM25 is ascending; cosine is descending.
                better = (lambda score: score <= boundary) if ranking['route'] == 'dictionary_lexical' else (lambda score: score >= boundary)
                selected.update(i for i, score in zip(ranking['hits'], ranking['scores']) if better(score))
            last = None
            for n, (identifier, score) in enumerate(zip(ranking['hits'], ranking['scores']), 1):
                if score != last:
                    rank = n
                fused[identifier] += 1 / (60 + rank)
                last = score
        ordered = sorted(fused, key=lambda i: (-fused[i], i))
        if strategy == 'rrf' and ordered:
            boundary = fused[ordered[min(shortlist_size, len(ordered))-1]]
            shortlist = [i for i in ordered if fused[i] >= boundary]
        else:
            shortlist = [i for i in ordered if i in selected]
        pool = list(baseline['pool']) + sorted(set(ordered) - set(baseline['pool']))
        return {'pool': pool, 'pool_size': len(pool), 'shortlist': shortlist,
                'status': 'widen_required' if len(pool) > max_reservoir or len(shortlist) > max_shortlist else 'recalled' if shortlist else 'no_match',
                'catalog_count': len(allowed), 'hard_conditions': baseline.get('hard_conditions', {}),
                'seconds': baseline['seconds'] + time.monotonic() - started,
                'focus_hint': focus, 'dictionary_matches': matches, 'rankings': rankings,
                'shortlist_scores': {i: fused[i] for i in shortlist},
                'baseline_preserved': True, 'semantic_completeness': 'unproven', 'strategy': strategy}


def specification(rows, shortlist, need):
    """Use the same independent suitability definitions, shared once."""
    spec, state, mapping = I.specification(rows, shortlist, need)
    state['fit_definitions'] = dict(I.CRITERIA)
    state['policy'] = I.POLICY
    for wire, question in spec['questions'].items():
        question['instructions'] = {
            'question': 'Apply `policy` and `fit_definitions` to the complete `task`. Judge CURRENT-step support of this candidate independently.',
            'candidate': state['candidates'][wire],
        }
        question['criteria'] = {'current': 'Full current support', 'partial': 'Partial or uncertain support', 'other': 'Later, unrelated or conflicting support'}
    del state['candidates']
    return spec, state, mapping


def select(rows, recall, need, call, *, compressed=True):
    pool, shortlist = recall['pool'], recall['shortlist']
    if not shortlist or not set(shortlist) <= set(pool) or len(shortlist) > 48:
        raise ValueError('invalid_shortlist')
    make_spec = specification if compressed else I.specification
    spec, state, mapping = make_spec(rows, shortlist, need)
    result = I.validate(call('final', spec, state), mapping, shortlist)
    result.update(retained_candidates=list(pool), final_pool_size=len(shortlist),
                  traces=[{'stage': 'current_shortlist', 'pool': list(shortlist)},
                          {'stage': 'later_reservoir', 'pool': list(pool)}])
    return result
