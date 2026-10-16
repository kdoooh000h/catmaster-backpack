"""Public, query-independent operation groups for an adaptive-directory pilot.

These are benchmark fixtures, not a private catalog or installed capability.
The compiler rejects uncovered/unknown members rather than dropping them.
"""
from experiment import semantic_tree, human_tree, union

# scope, complete source membership. No requests, expected answers or scores.
TOPICS = {
 'domain:engineering': [
  ('Coordinate competing agents, isolated worktrees, shared boards, evaluation and result merging.',
   'agenthub board eval hub-init hub-status merge engineering--run spawn hivemind'),
  ('Design agent orchestration, bounded workflows, automatic research experiments and human review loops.',
   'agent-harness ar-resume ar-status autoresearch-agent loop engineering--skills--run setup agent-designer agent-workflow-designer workflow-builder human-gate'),
  ('Engineer LLM applications: inference cost, prompt registries, retrieval pipelines, persistent memory and knowledge bases.',
   'llm-cost-optimizer prompt-governance rag-architect agent-memory llm-wiki memory-engineering'),
  ('Create, extract, test, audit and improve reusable agent skills and their lifecycle.',
   'book-to-skill skill-doctor skillopt-sleep skill-security-auditor skill-tester write-a-skill sample-text-processor'),
  ('Implement container, Kubernetes controller and Helm infrastructure, Terraform, delivery pipelines, resilience, observability and service objectives.',
   'docker-development helm-chart-builder kubernetes-operator terraform-patterns ci-cd-pipeline-builder chaos-engineering observability-designer slo-architect runbook-generator'),
  ('Design and test APIs, MCP servers, database schemas, SQL, migrations, data quality and statistical analyses.',
   'api-design-reviewer api-test-suite-builder mcp-server-builder database-designer database-schema-designer sql-database-assistant migration-architect data-quality-auditor statistical-analyst'),
  ('Implement and review code, debug a specific feature, profile performance, manage worktrees, monorepos, flags and technical debt.',
   'boost-asio-pro feature-flags-architect karpathy-coder minimalist focused-fix git-worktree-manager monorepo-navigator performance-profiler pr-review-expert tech-debt-tracker strict-api zero-hallucination-coder'),
  ('Audit dependencies and unsafe code patterns; manage environment secrets and vault infrastructure; verify release readiness.',
   'dependency-auditor security-guidance env-secrets-manager secrets-vault-manager ship-gate'),
  ('Read and manipulate browser pages, take full-page screenshots, scrape data and produce demonstration videos.',
   'browser-automation full-page-screenshot universal-scraping-architect demo-video'),
  ('Document code and decisions, prepare handoffs and release notes, interview requirements and design hiring processes.',
   'code-tour codebase-onboarding changelog-generator engineering--handoff tc-tracker spec-driven-workflow grill-me grill-with-docs interview-system-designer'),
  ('Learn AI methods or agent usage, adjust response style and evaluate collaboration or work quality; browse the engineering bundle.',
   'deep-learning-book spinning-up-deep-rl claude-coach behuman caveman collab-proof self-eval engineering-advanced-skills'),
 ],
 'domain:engineering-team': [
  ('Implement frontend, backend, full-stack applications, software architecture, cinematic websites and transactional emails; compare technology stacks.',
   'senior-architect senior-backend senior-frontend senior-fullstack epic-design email-template-builder tech-stack-evaluator engineering-skills'),
  ('Set up, generate, fix, migrate and review browser tests; cross-browser testing, coverage, reports, test management, TDD and accessibility audits.',
   'a11y-audit browserstack coverage fix generate migrate pw-init pw-review playwright-pro report testrail senior-qa tdd-guide'),
  ('Design AWS, Azure and GCP infrastructure, DevOps, data pipelines and Snowflake workloads; coordinate service incidents.',
   'aws-solution-architect azure-cloud-architect gcp-cloud-architect senior-devops senior-data-engineer snowflake-development incident-commander'),
  ('Develop computer vision, machine learning, data science and prompt engineering.',
   'senior-computer-vision senior-data-scientist senior-ml-engineer senior-prompt-engineer'),
  ('Review code and security: adversarial reviews, AI/cloud threats, penetration tests, red teams, threat hunting and incident response.',
   'adversarial-reviewer named-persona-adversarial-review code-reviewer ai-security cloud-security incident-response red-team security-pen-testing senior-secops senior-security threat-detection'),
  ('Save and curate agent memory, review memory health, promote learned patterns and extract reusable guidance.',
   'extract memory-review memory-status promote remember self-improving-agent'),
  ('Administer Google Workspace and Microsoft 365, integrate payment systems and develop embedded or IoT hardware.',
   'google-workspace-cli ms365-tenant-manager stripe-integration-expert embedded-iot-mentor'),
 ],
 'domain:marketing-skill': [
  ('Create and edit brand messages, written content, copy, video, email sequences, and social-media publications.',
   'ad-creative brand-guidelines business-name-fit content-creator content-humanizer content-production content-strategy copy-editing copywriting email-sequence social-content social-media-manager x-twitter-growth youtube-full video-content-strategist'),
  ('Improve conversion at public pages, forms, signup, onboarding, popups, in-product paywalls and upgrade moments; retain customers and test experiments.',
   'ab-test-setup churn-prevention form-cro onboarding-cro page-cro paywall-upgrade-cro popup-cro signup-flow-cro'),
  ('Improve search and app-store visibility through SEO, answer-engine optimization, structured markup, site structure and programmatic or local search.',
   'aeo app-store-optimization local-seo-manager programmatic-seo schema-markup seo-audit site-architecture'),
  ('Plan launches, paid acquisition, referrals, outreach, webinars, competitor positioning, pricing and growth campaigns.',
   'cold-email competitor-alternatives free-tool-strategy launch-strategy marketing-demand-acquisition marketing-ideas marketing-psychology marketing-strategy-pmm paid-ads pricing-strategy referral-program webinar-marketing'),
  ('Measure campaign and social results, implement tracking, manage marketing operations and context, and use prompt tooling or the marketing index.',
   'analytics-tracking campaign-analytics social-media-analyzer marketing-context marketing-ops marketing-skills prompt-engineer-toolkit'),
 ],
 'domain:c-level-advisor': [
  ('Provide functional executive advice across AI, customers, data, finance, legal, people, security, marketing, operations, product, revenue, technology and engineering.',
   'chief-ai-officer-advisor chief-customer-officer-advisor chief-data-officer-advisor general-counsel-advisor ceo-advisor cfo-advisor chro-advisor ciso-advisor cmo-advisor coo-advisor cpo-advisor cro-advisor cto-advisor vpe-advisor'),
  ('Prepare board materials, coordinate executive deliberation, load company context and record approved decisions.',
   'board-prep agent-protocol board-deck-builder board-meeting chief-of-staff context-engine cs-onboard decision-logger c-level-skills'),
  ('Stress-test strategic assumptions, handle difficult decisions, analyze failed outcomes and coach founder leadership.',
   'challenge executive-mentor hard-call postmortem stress-test founder-coach scenario-war-room'),
  ('Build company operations, culture, alignment and narratives; assess organizational health, competition, international expansion and acquisitions.',
   'arquiteto-de-empresa change-management company-os competitive-intel culture-architect internal-narrative intl-expansion ma-playbook org-health-diagnostic strategic-alignment'),
 ],
 'domain:c-level-agents': [
  ('Review executive plans from AI, customer, data, finance, security, marketing, product, revenue, technology, legal and engineering perspectives.',
   'caio-review cco-review cdo-review cfo-review ciso-review cmo-review cpo-review cro-review cto-review gc-review vpe-review'),
  ('Intake founder context, frame strategy briefs, convene board reviews and independently cross-evaluate proposals.',
   'boardroom brief c-level-agents cross-eval founder-mode office-hours onboard'),
  ('Record and freeze approved decisions, translate them to execution plans and review outcomes.',
   'decide execute freeze post-mortem'),
 ],
 'domain:product-team': [
  ('Research users and markets, synthesize evidence, investigate competitors, and measure product experiments and analytics.',
   'research-summarizer competitive-teardown experiment-designer product-analytics product-discovery ux-researcher-designer'),
  ('Set product strategy, prioritize and communicate roadmaps, manage agile requirements and derive product specifications from code.',
   'agile-product-owner code-to-prd product-manager-toolkit product-skills product-strategist roadmap-communicator'),
  ('Design interface systems using platform guidelines, generate landing pages, scaffold SaaS and translate specifications into repositories.',
   'apple-hig-expert landing-page-generator saas-scaffolder spec-to-repo ui-design-system'),
 ],
 'domain:ra-qm-team': [
  ('Implement medical-device quality systems, control documents, assign quality responsibilities, audit QMS, manage CAPA and lifecycle risk.',
   'capa-officer qms-audit-expert quality-documentation-manager quality-manager-qmr quality-manager-qms-iso13485 risk-management-specialist'),
  ('Plan medical-device regulatory submissions and market access under FDA and European MDR; navigate regulatory and quality guidance.',
   'fda-consultant-specialist mdr-745-specialist regulatory-affairs-head ra-qm-skills'),
  ('Implement privacy, information-security and AI governance frameworks, audits and traceable agent decision records.',
   'eu-ai-act-specialist iso42001-specialist agent-decision-receipts gdpr-dsgvo-expert information-security-manager-iso27001 isms-audit-expert soc2-compliance'),
 ],
}


def build(rows, taxonomy):
    nodes = human_tree(taxonomy)
    ids = {row['id'] for row in rows}
    for parent, definitions in TOPICS.items():
        seen = set()
        children = []
        for index, (scope, members) in enumerate(definitions):
            members = members.split()
            if seen.intersection(members) or not set(members) <= set(nodes[parent]['members']):
                raise ValueError('invalid_topic_members:' + parent)
            seen.update(members)
            key = parent + ':topic' + str(index)
            nodes[key] = {'id': key, 'depth': 3, 'members': members, 'children': [], 'description': scope}
            children.append(key)
        if seen != set(nodes[parent]['members']):
            raise ValueError('incomplete_topics:' + parent + ':' + ','.join(set(nodes[parent]['members']) - seen))
        nodes[parent]['children'] = children
        # A compact list of actual action scopes; no decorative source-domain union.
        nodes[parent]['description'] += ' Operations: ' + ' '.join(nodes[key]['description'] for key in children)
    # Further small, optional subdivisions: source titles disclose every member,
    # not just centroid keywords. Final choice still sees untouched full text.
    by_id = {row['id']: row for row in rows}
    for key, node in list(nodes.items()):
        if node['children'] or len(node['members']) <= 4:
            continue
        height = min(6 - node['depth'], 3)
        subset = [row for row in rows if row['id'] in node['members']]
        split = semantic_tree(subset, taxonomy, height)
        def add(local_key, parent_key):
            for child in split[local_key]['children']:
                record = split[child]
                child_key = key + ':' + child
                names = [by_id[item]['name'].replace('-', ' ') for item in record['members']]
                nodes[child_key] = {'id': child_key, 'depth': node['depth'] + record['depth'],
                    'members': record['members'], 'children': [],
                    'description': node['description'] + ' Subscopes (complete list): ' + '; '.join(names) + '.'}
                nodes[parent_key]['children'].append(child_key)
                if len(record['members']) > 4:
                    add(child, child_key)
        add('n', key)
    if union(nodes, ['n']) != ids:
        raise ValueError('catalog_not_covered')
    for node in nodes.values():
        if node['children'] and union(nodes, node['children']) != set(node['members']):
            raise ValueError('child_coverage_changed')
        if node['depth'] > 6:
            raise ValueError('depth_limit')
    return nodes
