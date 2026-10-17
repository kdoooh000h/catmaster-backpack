"""Add multilingual dense recall to the unchanged lexical pool.

The caller supplies a pinned local encoder and public metadata embeddings. No
case labels, vocabulary extensions, source rankings or task-specific summaries
enter retrieval. Every raw clause gets its own search across each usage kind.
"""
import time
import sqlite3
import re
import numpy as np

from conditional_search import clauses, terms, CONCEPTS


class OpenLexicalIndex:
    """Search every clause across kinds without a predefined object prerequisite."""
    def __init__(self,rows):
        self.rows=list(rows);self.db=sqlite3.connect(':memory:')
        self.names={}
        for row in rows:
            name=row['name'].strip()
            if re.fullmatch(r'[A-Za-z][A-Za-z0-9 ._-]{3,39}',name) and len(name.split())<=4:
                self.names.setdefault(' '.join(name.casefold().split()),[]).append(row)
        self.db.execute("CREATE VIRTUAL TABLE entries USING fts5(name,description,labels,kind UNINDEXED,tokenize='porter unicode61')")
        self.db.executemany('INSERT INTO entries(rowid,name,description,labels,kind) VALUES (?,?,?,?,?)',
            [(n,' '.join(terms(r['name'])),' '.join(terms(' '.join(dict.fromkeys([r['description']]+r.get('descriptions',[]))))),
              ' '.join(terms(' '.join(r.get('topics',[])+r.get('publisher_labels',[])))),r['kind']) for n,r in enumerate(rows,1)])

    def search(self,need,baseline,per_kind=3):
        if not isinstance(need,str) or not need.strip():raise ValueError('empty_need')
        if type(per_kind) is not int or per_kind<1:raise ValueError('invalid_limit')
        started=time.monotonic();additions=set();audits=[]
        kinds=baseline.get('hard_conditions',{}).get('allowed_kinds',['skill','plugin','mcp'])
        if not set(kinds)<={'skill','plugin','mcp'}:raise ValueError('unknown_kind')
        allowed={r['id'] for r in self.rows if r['kind'] in kinds}
        if baseline['catalog_count']!=len(allowed) or not set(baseline['pool'])<=allowed:raise ValueError('baseline_mismatch')
        names=set()
        for span in re.findall(r'[A-Za-z0-9._ -]+',need):
            words=span.casefold().split()
            for start in range(len(words)):
                for count in range(1,5):
                    phrase=' '.join(words[start:start+count])
                    names.update([phrase,phrase.rstrip('.')])
        for name in sorted(names&self.names.keys()):
            for row in self.names[name]:
                if row['id'] in allowed:
                    additions.add(row['id'])
                    audits.append({'query':name,'kind':row['kind'],'hits':[row['id']],'route':'literal_name','boundary_tie':False})
        for query_text in dict.fromkeys([need]+clauses(need)):
            words=terms(query_text)
            for triggers,english in CONCEPTS:
                if any(t in query_text.casefold() for t in triggers.split()):words.extend(terms(english))
            if not words:continue
            query=' OR '.join('"'+w+'"' for w in dict.fromkeys(words))
            for kind in kinds:
                hits=self.db.execute('SELECT rowid,bm25(entries,6,1,.5) AS score FROM entries WHERE entries MATCH ? AND kind=? ORDER BY score,rowid LIMIT ?',
                                     (query,kind,per_kind+1)).fetchall()
                tied=len(hits)>per_kind and hits[per_kind-1][1]==hits[per_kind][1]
                if tied:
                    hits=self.db.execute('SELECT rowid,bm25(entries,6,1,.5) AS score FROM entries WHERE entries MATCH ? AND kind=? AND score<=? ORDER BY score,rowid',
                                         (query,kind,hits[per_kind-1][1])).fetchall()
                else:hits=hits[:per_kind]
                ids=[self.rows[n-1]['id'] for n,_ in hits];additions.update(ids)
                audits.append({'query':query_text,'kind':kind,'hits':ids,'boundary_tie':tied})
        pool=list(baseline['pool'])+sorted(additions-set(baseline['pool']))
        return {**baseline,'pool':pool,'pool_size':len(pool),'seconds':baseline['seconds']+time.monotonic()-started,
                'open_lexical_queries':audits}

    def close(self):self.db.close()


class SemanticIndex:
    def __init__(self, rows, vectors, encode, *, query_prefix='query: '):
        self.rows=list(rows);self.encode=encode
        self.query_prefix=query_prefix
        self.ids=[r['id'] for r in rows]
        self.vectors=np.asarray(vectors,dtype=np.float32)
        if (len(set(self.ids))!=len(self.ids) or self.vectors.ndim!=2
                or len(self.vectors)!=len(rows) or not np.isfinite(self.vectors).all()):
            raise ValueError('invalid_semantic_index')
        norms=np.linalg.norm(self.vectors,axis=1)
        if not np.allclose(norms,1,atol=.001):raise ValueError('unnormalized_index')
        self.kinds=sorted({r['kind'] for r in rows})
        if not set(self.kinds)<={'skill','plugin','mcp'}:raise ValueError('unknown_kind')
        self.by_kind={k:np.array([i for i,r in enumerate(rows) if r['kind']==k]) for k in self.kinds}

    def search(self, need, baseline, *, per_kind=3, max_candidates=256):
        if not isinstance(need,str) or not need.strip():raise ValueError('empty_need')
        if type(per_kind) is not int or per_kind<1:raise ValueError('invalid_limit')
        started=time.monotonic()
        kinds=baseline.get('hard_conditions',{}).get('allowed_kinds',self.kinds)
        if not set(kinds)<=set(self.kinds):raise ValueError('unknown_kind')
        allowed={r['id'] for r in self.rows if r['kind'] in kinds}
        if baseline['catalog_count']!=len(allowed) or not set(baseline['pool'])<=allowed:
            raise ValueError('baseline_mismatch')
        queries=list(dict.fromkeys([need]+clauses(need)))
        vectors=np.asarray(self.encode([self.query_prefix+q for q in queries]),dtype=np.float32)
        if vectors.shape!=(len(queries),self.vectors.shape[1]) or not np.isfinite(vectors).all():
            raise ValueError('invalid_query_vectors')
        if not np.allclose(np.linalg.norm(vectors,axis=1),1,atol=.001):
            raise ValueError('unnormalized_queries')
        scores=vectors@self.vectors.T
        additions=set();audits=[]
        for query,values in zip(queries,scores):
            for kind in kinds:
                indices=self.by_kind[kind]
                ordered=indices[np.argsort(-values[indices],kind='stable')]
                if not len(ordered):continue
                boundary=values[ordered[min(per_kind,len(ordered))-1]]
                # Preserve exact score ties rather than dropping by row order.
                selected=ordered[values[ordered]>=boundary].tolist()
                hits=[self.ids[i] for i in selected];additions.update(hits)
                audits.append({'query':query,'kind':kind,'hits':hits,
                               'scores':[float(values[i]) for i in selected],
                               'boundary_tie':len(selected)>per_kind})
        pool=list(baseline['pool'])+sorted(additions-set(baseline['pool']))
        elapsed=time.monotonic()-started
        return {'status':'widen_required' if len(pool)>max_candidates else 'recalled' if pool else 'no_match',
                'pool':pool,'pool_size':len(pool),'catalog_count':len(allowed),
                'seconds':baseline['seconds']+elapsed,'semantic_seconds':elapsed,
                'hard_conditions':baseline.get('hard_conditions',{}),'queries':audits,
                'open_lexical_queries':baseline.get('open_lexical_queries',[]),
                'baseline_preserved':True,'semantic_completeness':'unproven',
                'per_kind':per_kind,'max_candidates':max_candidates}
