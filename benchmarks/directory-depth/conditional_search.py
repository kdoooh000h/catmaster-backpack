"""Local find-style recall over a caller-owned public metadata snapshot.

No model, market reads, installation, private storage or gold labels. Search
each clause and matched bilingual concept independently so that an early task
cannot consume every recall slot. Cancellation is left to Jev on the raw need.
This is bounded lexical recall, not a proof of semantic completeness.
"""
from collections import defaultdict
import difflib
import re
import sqlite3
import time


STOP = set('a an the and or to of for from in on with please use help request '
           'review check give find skill skills tool tools user users this that '
           'when includes include using can build create supports support'.split())

# General bilingual operation vocabulary, fixed before grading. No candidate
# identities, publishers, gold descriptions or case-specific English summaries.
CONCEPTS = [
    ('无障碍 可访问性 读屏', 'accessibility a11y wcag aria screen reader'),
    ('网页 页面 前端', 'web website frontend html css'),
    ('组件 渲染 卡顿', 'component rendering performance react'),
    ('数据库 数据表 查询', 'database sql query postgres'),
    ('表格 电子表格', 'spreadsheet excel csv xlsx'),
    ('图表 可视化', 'chart visualization plot'),
    ('幻灯片 演示文稿', 'presentation slides powerpoint'),
    ('图片 图像 修图', 'image photo editing'),
    ('视频 剪辑', 'video editing'),
    ('翻译 多语言', 'translation multilingual localization'),
    ('文章 文案 写作', 'writing article copywriting'),
    ('自动化 工作流', 'automation workflow'),
    ('浏览器 网页操作', 'browser navigation playwright'),
    ('测试 测例 验证', 'test testing verification'),
    ('部署 发布 上线', 'deployment release hosting'),
    ('日志 指标 调用链 可观测', 'observability metrics logs traces monitoring'),
    ('告警 黄金信号 服务目标', 'alert golden signals sli slo'),
    ('故障 响应 事后复盘 值班', 'incident response severity postmortem oncall'),
    ('漏洞 安全缺陷', 'vulnerabilities vulnerability cve security'),
    ('许可证 授权条款', 'license licensing compliance conflict'),
    ('依赖 开源包 传递依赖 借来的 再带进来', 'dependency dependencies transitive packages audit'),
    ('升级顺序 升级路径', 'upgrade migration safe'),
    ('收入 订阅 财务 经营健康 客户数字 客户数据', 'saas revenue financial health mrr nrr cac ltv'),
    ('预算 预测 现金流', 'budget forecasting cash flow finance'),
    ('渠道 配比 渠道配比', 'channel direct partner mix economics'),
    ('成本 核算 敏感性', 'cost economics roi sensitivity'),
    ('文化 价值观 行为准则 文化仪式', 'culture values behaviors rituals'),
    ('团队 人员 招聘', 'team people hiring recruitment'),
    ('欢迎邮件 连续邮件 发送间隔 欢迎到激活', 'email sequence drip onboarding welcome lifecycle'),
    ('客户 营销 获客', 'customer marketing acquisition'),
    ('访谈 产品发现 功能排序 产品方案', 'product discovery interview prioritization rice'),
    ('需求文档 产品需求', 'prd requirements product'),
    ('知识库 页面层级 层级权限 模板宏 归档', 'knowledge documentation hierarchy permissions templates macros governance'),
    ('项目 跟踪 看板', 'project tracking dashboard workflow'),
    ('认证 登录 权限', 'authentication login authorization permissions'),
    ('支付 订单 退款', 'payment orders refund billing'),
    ('搜索 检索 排序', 'search retrieval ranking'),
    ('数据分析 统计 预测模型', 'analytics statistics forecasting model'),
    ('机器学习 人工智能 大模型', 'machine learning ai llm'),
    ('接口 集成 服务端', 'api integration backend server'),
    ('移动端 安卓 苹果', 'mobile android ios'),
    ('设计 用户体验 交互', 'design ux ui interaction'),
    ('合同 法律 合规', 'contract legal compliance'),
    ('供应商 采购 供应链', 'vendor procurement supply chain'),
]


def terms(text):
    value = text.casefold()
    result = [w for w in re.findall(r'[a-z0-9]+', value)
              if len(w) > 1 and w not in STOP]
    for span in re.findall(r'[\u3400-\u9fff]+', value):
        result.extend(span[i:i+2] for i in range(len(span)-1))
    return list(dict.fromkeys(result))


def clauses(need):
    # Retain the original order and text, including later and cancelled clauses.
    return [part.strip() for part in re.split(r'[。！？!?；;，,\n]+', need) if part.strip()]


class SearchIndex:
    def __init__(self, rows):
        started = time.monotonic()
        self.rows = list(rows)
        if len({r['id'] for r in rows}) != len(rows):
            raise ValueError('duplicate_catalog_identity')
        self.db = sqlite3.connect(':memory:')
        self.db.execute("CREATE VIRTUAL TABLE metadata USING fts5(text, tokenize='porter unicode61')")
        records = []
        vocabulary = set()
        for number, row in enumerate(rows, 1):
            # Aliased descriptions are retained; source markets and popularity
            # are not relevance features. Whole plugins remain single rows.
            descriptions = list(dict.fromkeys([row['description']] + row.get('descriptions', [])))
            words = terms(row.get('name', '') + ' ' + ' '.join(descriptions))
            vocabulary.update(w for w in words if w.isascii() and w.isalpha())
            records.append((number, ' '.join(words)))
        self.db.executemany('INSERT INTO metadata(rowid,text) VALUES (?,?)', records)
        self.vocabulary = sorted(vocabulary)
        self.vocabulary_set = vocabulary
        self.seconds = time.monotonic() - started

    def close(self):
        self.db.close()

    def _rank(self, words, limit):
        if not words:
            return [], False
        query = ' OR '.join('"' + word + '"' for word in dict.fromkeys(words))
        values = self.db.execute(
            'SELECT rowid, bm25(metadata) FROM metadata WHERE metadata MATCH ? '
            'ORDER BY bm25(metadata),rowid LIMIT ?', (query, limit + 1)).fetchall()
        # A boundary tie must not silently be decided by database row ordering.
        tied = len(values) > limit and values[limit-1][1] == values[limit][1]
        if tied:
            values = self.db.execute(
                'SELECT rowid, bm25(metadata) AS score FROM metadata WHERE metadata MATCH ? '
                'AND score <= ? ORDER BY score,rowid', (query, values[limit-1][1])).fetchall()
        else:
            values = values[:limit]
        return [self.rows[rowid-1]['id'] for rowid, _ in values], tied

    def search(self, need, *, per_clause=8, per_concept=3, max_candidates=96,
               allowed_kinds=None):
        started = time.monotonic()
        if not isinstance(need, str) or not need.strip():
            raise ValueError('empty_need')
        if allowed_kinds is not None and not set(allowed_kinds) <= {'skill', 'plugin', 'mcp'}:
            raise ValueError('unknown_hard_condition')
        # Filter first: excluded rows must never consume a recall slot. No
        # inferred requirement (such as 'MCP always needs a network') is used.
        if allowed_kinds is not None:
            child = SearchIndex([r for r in self.rows if r['kind'] in allowed_kinds])
            try:
                result = child.search(need, per_clause=per_clause, per_concept=per_concept,
                                      max_candidates=max_candidates)
            finally:
                child.close()
            result['hard_conditions'] = {'allowed_kinds': list(allowed_kinds)}
            result['seconds'] = time.monotonic() - started
            return result
        queries = []
        for part in clauses(need):
            words = terms(part)
            expansions = []
            for triggers, english in CONCEPTS:
                if any(trigger in part.casefold() for trigger in triggers.split()):
                    expansions.extend(terms(english))
                    queries.append(('concept', english, terms(english), per_concept))
            # Bounded typo expansion is additive. Never replace an exact term.
            for word in list(words):
                if word.isascii() and word.isalpha() and len(word) >= 5 and word not in self.vocabulary_set:
                    expansions.extend(difflib.get_close_matches(word, self.vocabulary, n=2, cutoff=.84))
            queries.append(('clause', part, words + expansions, per_clause))
        # One program-side search per unique query, no query-model round trip.
        unique = {}; scores = defaultdict(float); origins = defaultdict(list); audits = []
        for kind, text, words, limit in queries:
            identity = (tuple(sorted(set(words))), limit)
            if identity in unique:
                continue
            unique[identity] = True
            ranked, tied = self._rank(words, limit)
            for rank, identifier in enumerate(ranked, 1):
                scores[identifier] += 1 / (60 + rank)
                origins[identifier].append({'kind': kind, 'query': text, 'rank': rank})
            audits.append({'kind': kind, 'query': text, 'hits': ranked, 'boundary_tie': tied})
        ordered = sorted(scores, key=lambda identifier: (-scores[identifier], identifier))
        too_wide = len(ordered) > max_candidates
        # No global top-N truncation: an over-wide pool requests wider handling.
        return {'status': 'widen_required' if too_wide else 'recalled' if ordered else 'no_lexical_match',
                'pool': ordered, 'pool_size': len(ordered), 'catalog_count': len(self.rows),
                'queries': audits, 'origins': dict(origins),
                'seconds': time.monotonic() - started,
                'hard_conditions': {}, 'semantic_completeness': 'unproven',
                'boundary_ties': sum(q['boundary_tie'] for q in audits)}
