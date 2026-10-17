"""Additive Word aliases and literal evidence hints; no candidate pruning."""
from copy import deepcopy
import re
import time

import final_contrast as F
import conditional_current as V
from structured_recall import positive_metadata

ARMS = ['compact', 'evidence', 'coverage']
WORD_ALIAS = re.compile(
    r'(?<![A-Za-z0-9_])word(?![A-Za-z0-9_])\s*(?:的\s*)?'
    r'(?:(?:操作|培训|产品|用户|使用|技术)\s*)?'
    r'(?:手册|报告|合同|简历|模板|讲义|提案|信函|协议|文书|文件|manuals?\b|reports?\b|contracts?\b|handouts?\b)', re.I)

# Symmetric bilingual hints: a feature must occur in both the request and
# positive metadata. Every displayed excerpt is copied from the original
# description. No scores, publisher preference, target IDs or gold are used.
DETAILS = {
    'speaker_notes': r'speaker notes?|presenter notes?|讲者备注|演讲者备注|讲稿备注',
    'layout': r'layouts?|版式|布局',
    'editable': r'editable|editing|可编辑|修改',
    'read_only_reference': r'read-only reference analysis|参考材料只读分析|只读分析参考',
    'coordinates': r'coordinate-explicit|coordinates?|元素坐标|坐标',
    'quality_gate': r'quality gates?|质量检查|质量门槛',
    'toc': r'table of contents|\bTOC\b|目录',
    'headings': r'headings?|分级标题|标题',
    'page_numbers': r'page numbers?|页码',
    'tracked_changes': r'tracked changes|修订标记',
    'comments': r'comments?|批注',
    'formulas': r'formulas?|公式',
    'charts': r'charts?|图表',
    'ocr': r'\bOCR\b|光学字符识别|扫描文字识别',
    'encryption': r'encrypt\w*|password|加密|密码保护',
    'forms': r'forms?|表单',
    'openapi': r'\bOpenAPI\b|接口规范',
    'graphql': r'\bGraphQL\b',
    'typed_sdk': r'typed SDK|带类型的\s*SDK',
    'cli': r'\bCLI\b|command.line|命令行',
    'code_quality': r'code smells?|SOLID|代码异味|代码复杂度',
}
PATTERNS = {k:re.compile(v,re.I) for k,v in DETAILS.items()}
NEGATIVE = re.compile(r"\b(?:not|never|without|cannot|can't|don't)\b|不要|不需要|取消|不支持|不提供",re.I)
EVIDENCE_NOTE = (
    'Evidence prefixes quote matching details from the unchanged descriptions. '
    'They are lexical hints, not exhaustive requirements or proof of readiness. '
    'An unmentioned detail is unknown, not proof of inability. '
)
COVERAGE_NOTE = (
    'For the current step, choose the candidate whose description most explicitly '
    'covers the requested output AND its requested details together. '
    'Specific required details distinguish otherwise similar outputs. '
    'Do not infer a requested detail from a generic promise to create that output. '
    'Use the full description to resolve hints, constraints, and current versus later work. '
)


def repair_recall(index, need, original):
    began=time.monotonic(); aliases=[m.group(0) for m in WORD_ALIAS.finditer(need)]
    if aliases:
        expanded=need+'\nWord document'
        result=index.search(expanded,original)
    else:
        expanded=need;result=deepcopy(original)
    elapsed=time.monotonic()-began
    result['seconds']=original['seconds']+elapsed
    if not set(original['pool'])<=set(result['pool']):raise ValueError('original_candidate_lost')
    return {'recall':result,'aliases':aliases,'search_text':expanded,'repair_seconds':elapsed,
            'original_query_seconds':original['seconds'],'original_preserved':True}


def evidence(need, description):
    # Discard negated request clauses only from hints. The complete raw task
    # and complete candidate descriptions still reach Jev, unchanged.
    request=' '.join(c for c in re.split(r'[。！？；;,，\n]',need) if not NEGATIVE.search(c))
    positive=positive_metadata(description)
    result=[]
    for key,pattern in PATTERNS.items():
        if pattern.search(request):
            match=pattern.search(positive)
            if match and match.group(0) not in result:result.append(match.group(0))
    return result


def specification(arm,rows,pool,question,need):
    if arm not in ARMS:raise ValueError('unknown_arm')
    spec,mapping=F.specification('typed_compact',rows,pool,question)
    if arm=='compact':return spec,mapping
    by_id={r['id']:r for r in rows}
    target=spec['questions']['answer']
    target['instructions']=EVIDENCE_NOTE+(COVERAGE_NOTE if arm=='coverage' else '')+target['instructions']
    for wire,identifier in mapping.items():
        if identifier=='none':continue
        details=evidence(need,by_id[identifier]['description'])
        if details:target['criteria'][wire]='Evidence: '+ ' | '.join(details)+'. '+target['criteria'][wire]
    return spec,mapping


def select(arm,rows,pool,question,need,call):
    spec,mapping=specification(arm,rows,pool,question,need)
    def invoke(stage,_spec,state):return F.decode(call(stage,spec,state),mapping)
    return V.select('conditional_current',rows,pool,question,need,invoke)
