"""Isolated directory repair: operation cards and one bounded boundary review.

Only public directory metadata changes. Membership, final descriptions and the
0.7 final gate remain fixed. No task/gold is accepted by the catalog compiler.
"""
import copy
import json
import re

import adaptive_experiment as A

BOUNDARY_MARGIN = .15
REVIEW_CARD_LIMIT = 6
REVIEW_CHAR_LIMIT = 12000
CAPSULE_CHAR_LIMIT = 400

# Editorial corrections grounded in the pinned public capability descriptions.
# These are development-set repairs, not evidence of unseen-query performance.
SCOPE_REPAIRS = {
    'root:build-and-agents': (
        'Build and operate software, infrastructure, data/AI systems, agent capabilities, '
        'memory and workflows; audit dataset quality and perform statistical analysis.'),
    'root:delivery-and-personal-work': (
        'Coordinate projects and teams, organize personal work and communication; '
        'plan meetings and extract owned, dated actions from notes; present documents and slides.'),
    'domain:engineering:topic5': (
        'Design and test APIs and MCP servers, database schemas, SQL and migrations; '
        'audit dataset completeness, consistency, accuracy and validity; profile distributions, '
        'find missing values, structural issues, anomalies and outliers, and plan remediation; '
        'perform statistical analysis.'),
    'domain:product-team:topic0': (
        'Summarize academic papers, articles, reports and documentation; compare sources, '
        'extract findings and citations. Also research users, markets and competitors; '
        'design product experiments and measure product analytics.'),
    'domain:productivity': (
        'Capture ideas, manage inboxes, focus and reviews; assess meeting necessity and cost, '
        'plan agendas, turn notes into owner and due-date checklists and flag missing assignments; '
        'reflect on decisions, hand off conversations, write goal prompts and learn Swedish.'),
}


def capsule(description):
    """An extract, not a claim of exhaustive coverage; final text stays intact."""
    text = ' '.join(description.split())
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    excerpt = ' '.join(sentences[:2])
    if len(excerpt) > CAPSULE_CHAR_LIMIT:
        excerpt = excerpt[:CAPSULE_CHAR_LIMIT].rsplit(' ', 1)[0] + '…'
    return excerpt


def build(original, rows):
    nodes = copy.deepcopy(original)
    by_id = {row['id']: row for row in rows}
    # Change broad scopes first, including all copies embedded in descendants.
    for key, replacement in SCOPE_REPAIRS.items():
        if key not in original:
            raise ValueError('missing_scope:' + key)
        before = original[key]['description']
        for node in nodes.values():
            node['description'] = node['description'].replace(before, replacement)
    for key, node in nodes.items():
        source = original[key]
        if ' Subscopes (complete list): ' in source['description']:
            # Names and inherited broad scopes are replaced by self-contained
            # operation extracts for EVERY member, with no shared-scope indirection.
            node['description'] = 'Operation extracts (not exhaustive): ' + '; '.join(
                by_id[item]['name'] + ': ' + capsule(by_id[item]['description'])
                for item in node['members'])
        elif key.startswith('domain:') and node['depth'] == 2:
            topics = [child for child in node['children'] if ':topic' in child]
            if topics:
                # Child scopes form the complete operation-group list. Avoid
                # repeating the generic source-domain paragraph above it.
                node['description'] = 'Operation groups: ' + ' '.join(
                    nodes[child]['description'] for child in topics)
        if source['members'] != node['members'] or source['children'] != node['children']:
            raise ValueError('membership_changed')
    if A.union(nodes, ['n']) != set(by_id):
        raise ValueError('catalog_not_covered')
    return nodes


def directory(nodes, offered, task, *, choices=None):
    questions = {}
    for key in offered:
        node = nodes[key]
        text = node['description']
        if choices is not None:
            if len(node['members']) <= 8:
                text = json.dumps({item: choices[item] for item in node['members']}, ensure_ascii=False)
            else:
                # One-level lookahead, not the entire capability catalog.
                text = json.dumps({child: nodes[child]['description'] for child in node['children']}, ensure_ascii=False)
        questions[key] = {'type': 'noul',
            'instructions': 'Does this directory contain guidance for ANY explicitly requested operation? Scope: ' + text,
            'criteria': {'true': 'At least one contained capability supports a requested operation.',
                         'false': 'No contained capability supports a requested operation.'}}
    state = {'task': task, 'rules': A.RULES +
        ' A directory is a union of capabilities, not one capability required to do the whole task. '
        'Operation extracts are partial descriptions; missing words alone do not establish irrelevance.'}
    return {'questions': questions}, state


def boundaries(raw, offered, nodes):
    # A.retained validates every answer before these scores are used.
    return [key for key in offered if
            A.gate(nodes[key]['depth']) - BOUNDARY_MARGIN - 1e-9 <= raw['answers'][key]['noul']
            < A.gate(nodes[key]['depth'])]


def route(nodes, task, choices, question, call, *, review=False):
    active, traces, stagnant, reviews = ['n'], [], 0, 0
    try:
        while True:
            pool = A.union(nodes, active)
            carry = [key for key in active if not nodes[key]['children']]
            offered = list(dict.fromkeys(child for key in active if key not in carry
                                         for child in nodes[key]['children']))
            final = A.final_spec(choices, pool, question)
            spec, state = directory(nodes, offered, task)
            reason = None
            if traces and len(pool) <= A.TARGET:
                reason = 'small_pool'
            elif traces and len(pool) <= 48 and A.estimate_chars(spec, state) >= .65 * A.estimate_chars(final, {'task': task}):
                reason = 'estimated_reading_cost'
            elif not offered:
                reason = 'terminal_categories'
            elif len(traces) >= A.MAX_ROUNDS:
                reason = 'round_limit'
            if reason:
                if len(pool) > A.FINAL_LIMIT:
                    return {'status': 'unavailable', 'reason': 'final_limit', 'traces': traces}
                raw = call('final', final, {'task': task})
                answer = raw.get('answers', {}).get('answer') if isinstance(raw, dict) else None
                if not isinstance(answer, dict) or answer.get('type') != 'choice':
                    raise ValueError('invalid_final_answer')
                key, confidence = answer.get('choice'), answer.get('confidence')
                if key not in final['questions']['answer']['criteria'] or not A.probability(confidence):
                    raise ValueError('invalid_final_answer')
                status = 'abstain' if confidence < A.FINAL_GATE else ('none' if key == 'none' else 'selected')
                return {'status': status, 'choice': key if status != 'abstain' else None,
                        'confidence': confidence, 'stop_reason': reason, 'traces': traces,
                        'final_pool_size': len(pool), 'boundary_review_calls': reviews}
            if len(offered) > 96:
                return {'status': 'unavailable', 'reason': 'directory_limit', 'traces': traces}
            raw = call('directory-' + str(len(traces)), spec, state)
            picked = A.retained(raw, offered, nodes)
            boundary = boundaries(raw, offered, nodes)
            audit = {'boundary': boundary, 'reviewed': [], 'recovered': []}
            if review and boundary:
                expanded, expanded_state = directory(nodes, boundary, task, choices=choices)
                if reviews:
                    audit['review_skipped'] = 'one_review_budget_spent'
                elif len(boundary) > REVIEW_CARD_LIMIT or A.estimate_chars(expanded, expanded_state) > REVIEW_CHAR_LIMIT:
                    audit['review_skipped'] = 'review_payload_limit'
                else:
                    # Different evidence (full small-branch metadata or child
                    # scopes), no old scores, gold or preferred answer supplied.
                    reviews += 1
                    reviewed = call('boundary-' + str(len(traces)), expanded, expanded_state)
                    recovered = A.retained(reviewed, boundary, nodes)
                    audit.update(reviewed=boundary, recovered=recovered, review_answers=reviewed['answers'])
                    picked += recovered
            active = list(dict.fromkeys(carry + picked))
            after = A.union(nodes, active)
            traces.append({'offered_count': len(offered), 'retained_count': len(picked),
                           'carried_count': len(carry), 'retained': picked, 'carried': carry,
                           'pool': sorted(after), 'answers': raw['answers'], **audit})
            if not active:
                return {'status': 'none', 'traces': traces, 'boundary_review_calls': reviews}
            stagnant = stagnant + 1 if len(after) >= len(pool) else 0
            if stagnant >= 2 and len(after) > A.FINAL_LIMIT:
                return {'status': 'unavailable', 'reason': 'no_progress', 'traces': traces}
    except Exception as error:
        return {'status': 'unavailable', 'reason': str(error), 'traces': traces}
