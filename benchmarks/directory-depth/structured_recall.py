"""Add metadata facets to lexical recall without removing baseline candidates.

The same bilingual vocabulary describes requests and public metadata. Object,
action and existing category fields are search hints, never authorization or
proof of capability. No model, source identity, popularity or gold is used.
"""
from collections import defaultdict
import re
import sqlite3
import time

from conditional_search import terms


# File formats are objects, not publisher/capability identities. Exact generic
# names get their own recall path so long descriptions cannot hide them.
FORMATS = {
    'word': ('docx', 'dotx', 'word document', 'word documents', 'microsoft word'),
    'spreadsheet': ('xlsx', 'xlsm', 'xltx', 'xls', 'csv', 'tsv', 'excel', 'spreadsheet', 'workbook'),
    'slides': ('pptx', 'potx', 'powerpoint', 'slides', 'slide deck', 'presentation'),
    'pdf': ('pdf',), 'image': ('png', 'jpg', 'jpeg', 'webp', 'svg'),
    'video': ('mp4', 'mov', 'webm'),
}
OBJECT_PATTERNS = {
    'word': r'\b(?:docx|dotx|word documents?|word templates?|microsoft word)\b|Word[（(.\s]*\.?(?:docx|文档)|文字处理文档',
    'spreadsheet': r'\b(?:xlsx|xlsm|xltx|xls|csv|tsv|excel|spreadsheets?|workbooks?)\b|电子表格|表格|工作簿',
    'slides': r'\b(?:pptx|potx|powerpoint|slide decks?|slides|presentations?)\b|幻灯片|演示文稿|投影片',
    'pdf': r'\bpdfs?\b|便携式文档',
    'image': r'\b(?:png|jpe?g|webp|svg|images?|photos?)\b|图片|图像|照片',
    'video': r'\b(?:mp4|mov|webm|videos?|footage)\b|视频|影片',
    'database': r'\b(?:sql|sqlite|postgres(?:ql)?|mysql|databases?)\b|数据库|关系型数据',
    'api': r'\b(?:openapi|rest|api endpoints?|api design|api contracts?)\b|接口规范|接口契约|接口设计',
    'code': r'\b(?:source code|code review|pull requests?|code quality|solid)\b|源代码|代码|拉取请求',
    'website': r'\b(?:websites?|webpages?|frontend|html|css)\b|网页|网站|前端',
    'email': r'\b(?:e-?mails?|newsletters?|inbox)\b|邮件|邮箱',
    'knowledge': r'\b(?:confluence|knowledge base|wiki)\b|知识库',
    'observability': r'\b(?:observability|monitoring|traces|slo|sli)\b|可观测|调用链|日志|告警',
    'culture': r'\b(?:culture|rituals)\b|团队文化|文化仪式|价值观',
    'finance': r'\b(?:mrr|nrr|cac|ltv|financial|revenue)\b|财务|订阅收入|经营健康',
}
ACTION_PATTERNS = {
    'create': r'\b(?:creat\w*|generat\w*|build\w*|authoring)\b|创建|生成|制作|编写|产出',
    'edit': r'\b(?:edit\w*|modif\w*|updat\w*)\b|修改|编辑|修订|更新',
    'read': r'\b(?:read\w*|open\w*|pars\w*)\b|读取|打开|解析',
    'extract': r'\b(?:extract\w*|ocr)\b|提取|识别|抽取',
    'convert': r'\b(?:convert\w*|export\w*|import\w*)\b|转换|转成|导出|导入',
    'merge': r'\b(?:merg\w*|combin\w*)\b|合并|拼接',
    'split': r'\b(?:split\w*|separat\w*)\b|拆分|分割',
    'format': r'\b(?:format\w*|layouts?|headings?|page numbers?|tracked changes|speaker notes)\b|排版|格式|标题|页码|修订标记|讲者备注',
    'calculate': r'\b(?:calculat\w*|comput\w*|formulas?)\b|计算|公式|求和',
    'chart': r'\b(?:charts?|charting|visualiz\w*|plots?)\b|图表|可视化|绘图',
    'clean': r'\b(?:clean\w*|restructur\w*|malformed|misplaced headers)\b|清理|清洗|错位|杂乱|规整',
    'review': r'\b(?:review\w*|audit\w*|lint\w*|code smells?)\b|审查|审计|代码异味',
    'compare': r'\b(?:compar\w*|diff\w*|breaking.change)\b|比较|对比|破坏性变更',
    'validate': r'\b(?:validat\w*|verif\w*|check\w*|test\w*)\b|校验|验证|检查|测试',
    'search': r'\b(?:search\w*|retriev\w*|find)\b|搜索|查找|检索',
    'translate': r'\b(?:translat\w*|localiz\w*)\b|翻译|本地化',
    'analyze': r'\b(?:analy\w*|assess\w*|evaluat\w*)\b|分析|评估|评审',
    'plan': r'\b(?:plan\w*|design\w*|strateg\w*)\b|规划|设计|方案',
}
CATEGORY_PATTERNS = {
    'writing': r'\b(?:writing|documents?|copywriting)\b|写作|文档|文字|排版',
    'data': r'\b(?:data|analytics|statistics)\b|数据|统计|计算|表格',
    'visual': r'\b(?:visual|design|images?|slides)\b|视觉|图片|幻灯片|演示文稿',
    'software': r'\b(?:software|coding|development|api)\b|软件|开发|代码|接口',
    'operations': r'\b(?:operations|devops|deployment)\b|运维|部署|监控',
    'security': r'\b(?:security|vulnerabilit\w*|compliance)\b|安全|漏洞|合规',
    'business': r'\b(?:business|finance|marketing)\b|业务|商业|财务|营销',
    'research': r'\b(?:research|science|academic)\b|研究|科研|论文',
}
OBJECT_CATEGORIES = {'word': ['writing'], 'spreadsheet': ['data'], 'slides': ['visual', 'writing'],
                     'pdf': ['writing'], 'image': ['visual'], 'video': ['visual'],
                     'database': ['data', 'software'], 'api': ['software'], 'code': ['software'],
                     'website': ['software', 'visual'], 'email': ['writing'], 'knowledge': ['writing'],
                     'observability': ['operations'], 'culture': ['business'], 'finance': ['business', 'data']}
NEGATIVE = re.compile(r"\b(?:do not|don't|not for|never use|does not support|cannot|can't|not supported)\b|不适用|不支持|不要用于", re.I)
COMPILED = {kind: {k: re.compile(v, re.I) for k, v in patterns.items()}
            for kind, patterns in [('objects', OBJECT_PATTERNS), ('actions', ACTION_PATTERNS), ('categories', CATEGORY_PATTERNS)]}


def matches(text, kind):
    return sorted(k for k, pattern in COMPILED[kind].items() if pattern.search(text))


def positive_metadata(text):
    # Conservative local hints only. Full original text still reaches Jev.
    return ' '.join(s for s in re.split(r'(?<=[.!?。！？])\s+', text) if not NEGATIVE.search(s))


def name_key(name):
    return re.sub(r'[^\w\s]+', ' ', re.split(r'[/\\]', name.casefold())[-1]).strip()


class StructuredIndex:
    def __init__(self, rows):
        began = time.monotonic(); self.rows = list(rows)
        if len({r['id'] for r in rows}) != len(rows): raise ValueError('duplicate_catalog_identity')
        self.ids = {r['id'] for r in rows}; self.anchors = defaultdict(set)
        self.db = sqlite3.connect(':memory:')
        self.db.execute("CREATE VIRTUAL TABLE facets USING fts5(names,text,objects,actions,categories,kind UNINDEXED,tokenize='porter unicode61')")
        records = []
        for n, row in enumerate(rows, 1):
            name = row.get('name', '')
            descriptions = list(dict.fromkeys([row['description']]+row.get('descriptions', [])))
            positive = positive_metadata(' '.join(descriptions))
            obj = set(matches(name+' '+positive, 'objects'))
            for key, aliases in FORMATS.items():
                if name_key(name) in aliases:
                    obj.add(key); self.anchors[key].add(n)
            actions = matches(positive, 'actions')
            labels = ' '.join(str(t) for t in row.get('topics', [])+row.get('publisher_labels', []))
            categories = matches(labels, 'categories')
            records.append((n, ' '.join(terms(name)), ' '.join(terms(positive)), ' '.join(sorted(obj)),
                            ' '.join(actions), ' '.join(categories), row['kind']))
        self.db.executemany('INSERT INTO facets(rowid,names,text,objects,actions,categories,kind) VALUES (?,?,?,?,?,?,?)', records)
        self.seconds = time.monotonic()-began

    def close(self): self.db.close()

    def search(self, need, baseline, *, per_kind=3, max_candidates=96):
        began = time.monotonic()
        if not isinstance(need, str) or not need.strip(): raise ValueError('empty_need')
        if type(per_kind) is not int or per_kind < 1: raise ValueError('invalid_per_kind')
        kinds = baseline.get('hard_conditions', {}).get('allowed_kinds', ['skill', 'plugin', 'mcp'])
        if not set(kinds) <= {'skill', 'plugin', 'mcp'}: raise ValueError('unknown_hard_condition')
        allowed = {r['id'] for r in self.rows if r['kind'] in kinds}
        if baseline['catalog_count'] != len(allowed) or not set(baseline['pool']) <= allowed:
            raise ValueError('baseline_catalog_mismatch')
        objects, actions = matches(need, 'objects'), matches(need, 'actions')
        categories = sorted(set(matches(need, 'categories')) |
                            {c for o in objects for c in OBJECT_CATEGORIES.get(o, [])})
        additions = set(); audits = []
        def field(name, words):
            return name+' : ('+' OR '.join('"'+w+'"' for w in words)+')'
        for obj in objects:
            anchors = [n for n in sorted(self.anchors[obj]) if self.rows[n-1]['kind'] in kinds]
            additions.update(self.rows[n-1]['id'] for n in anchors)
            audits.append({'object': obj, 'route': 'exact_generic_name', 'hits': [self.rows[n-1]['id'] for n in anchors]})
            optional = [field('objects', [obj]), field('text', terms(need))]
            if actions: optional.append(field('actions', actions))
            if categories: optional.append(field('categories', categories))
            if obj in FORMATS: optional.append(field('names', terms(' '.join(FORMATS[obj]))))
            query = field('objects', [obj])+' AND ('+' OR '.join(optional)+')'
            for kind in kinds:
                ranked = self.db.execute('SELECT rowid,bm25(facets,6,1,4,3,0.5) AS score FROM facets '
                                         'WHERE facets MATCH ? AND kind=? ORDER BY score,rowid LIMIT ?',
                                         (query, kind, per_kind+1)).fetchall()
                tied = len(ranked)>per_kind and ranked[per_kind-1][1]==ranked[per_kind][1]
                if tied:
                    ranked = self.db.execute('SELECT rowid,bm25(facets,6,1,4,3,0.5) AS score FROM facets '
                                             'WHERE facets MATCH ? AND kind=? AND score<=? ORDER BY score,rowid',
                                             (query,kind,ranked[per_kind-1][1])).fetchall()
                else: ranked = ranked[:per_kind]
                hits = [self.rows[n-1]['id'] for n, _ in ranked]; additions.update(hits)
                audits.append({'object': obj, 'route': 'weighted_facets', 'kind': kind, 'hits': hits, 'boundary_tie': tied})
        pool = list(baseline['pool'])+sorted(additions-set(baseline['pool']))
        elapsed = time.monotonic()-began
        return {'status': 'widen_required' if len(pool)>max_candidates else 'recalled' if pool else 'no_lexical_match',
                'pool': pool, 'pool_size': len(pool), 'catalog_count': len(allowed),
                'seconds': baseline['seconds']+elapsed, 'augmentation_seconds': elapsed,
                'hard_conditions': baseline.get('hard_conditions', {}),
                'request_facets': {'objects': objects, 'actions': actions, 'categories': categories},
                'queries': audits, 'baseline_preserved': set(baseline['pool'])<=set(pool),
                'semantic_completeness': 'unproven', 'boundary_ties': sum(q.get('boundary_tie',False) for q in audits)}
