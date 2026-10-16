# New-request breadth check: the two-case repair does not generalize

Both the prior compact final and the current coverage final pass only **2/12
(16.7%)** new ordinary requests under the unchanged **0.7** gate. Eight requests
lose required references during local retrieval; two more reach Jev but abstain
below the gate. The previous two-case repair remains a valid regression result,
but this broader check does not support general accuracy or daily promotion.

This is a public-metadata capability-selection experiment. It does not install
capabilities, execute their tasks, or upgrade an Agent connection. All four MCP
requests fail the offline coverage check, so **there are no live MCP-selection
calls in this round**. Those failures remain in the twelve-request denominator.

## Frozen conditions and acceptance

Twelve request strings were written and saved before inspecting reference
capabilities or running retrieval. They do not name a selected Skill, plugin or
MCP. Ordinary product, technology and output-format names remain allowed. Exact
request text and IDs were checked against the preceding experiment chain and
case fixtures; no previously passed request is replayed.

The set contains four Skill, four whole-plugin and four MCP primary targets;
four Chinese, four synonym-oriented and four mixed-language requests; and nine
multitask requests with a required later step. Capability-kind strata describe
the primary references, not a kind filter or a forced model choice. Public
markets remain merged, plugins remain intact, and programmatic deduplication is
unchanged. The frozen catalog contains 45,325 entries: 682 Skills, 628 plugins
and 44,015 MCPs, including 376 explicitly historical control Skills.

References and acceptable alternatives were fixed from public metadata before
recall or model calls. Each need requires a correct current choice and retention
of at least one predeclared reference for every later requirement. Alternative
sets can cross capability kinds. Original primary anchors are also audited
separately: both arms still pass only 2/12 when requiring the exact current
anchor, and only 4/12 retain every primary anchor. Thus the alternative-set
grading does not conceal primary-reference loss or change this verdict.

All twelve primary current references come from enabled public sources. Four
later reference occurrences use historical control Skills. Two accepted current
alternative sets also include historical controls; neither yields a passing
selection. Reference relevance is based on metadata, not verified execution or
an exhaustive equivalence assessment. These are author-written development
requests, not an independently authored blind holdout.

Selectors are unchanged from the two-failure repair. Both arms share freshly
computed alias-repaired retrieval, raw requests, pool order, reversible IDs,
compact descriptions and the 0.7 gate:

- `compact`: the existing compact final question.
- `coverage`: the existing literal matching-detail hints and explicit
  requested-output/detail coverage criterion.

This comparison isolates final selection; it does not compare against the
older adaptive-directory dispatcher. No English summary, gold label, manual
candidate injection, probability rescaling, second question or retry is sent.
Known missing-reference, empty or over-96 pools stop offline. Both arms receive
the same failure record; the reference check is a benchmark safeguard, not an
oracle available in ordinary runtime. All recalled candidates remain available
for later steps. No request, reference or selector is tuned after preflight.

## Results by new request

The pool column shows original structured recall followed by the unchanged
Word-alias repair. A retained reference alone is not a passing selection.

| New ordinary need | Primary type / language | Pool | Compact | Coverage |
| --- | --- | ---: | --- | --- |
| Searchable, rotated scanned contract PDF; later formula-based ledger | Skill / Chinese | 50 → 50 | Pass 0.95 | Pass 0.95 |
| Clean messy ledger and quarterly calculations; later Word report | Skill / synonyms | 42 → 49 | Pass 0.89 | Pass 0.90 |
| Local modal/form/keyboard checks with screenshots and console; later code review | Skill / mixed | 60 → 60 | Current and later references lost | Same |
| Distinctive responsive reading dashboard | Skill / Chinese | 48 → 48 | Abstain 0.37 | Abstain 0.33 |
| Accessibility audit and fixes; later Word handbook | Plugin / Chinese | 34 → 44 | Abstain 0.34 | Abstain 0.27 |
| Reproduction, traces and root-cause workflow; later Word findings | Plugin / synonyms | 56 → 56 | Current reference lost | Same |
| Kubernetes configuration and recoverable rollout; later dependency review | Plugin / mixed | 36 → 36 | Current reference lost | Same |
| Search-friendly original article planning and writing | Plugin / synonyms | 32 → 32 | Current reference lost | Same |
| Current library docs and code examples; later code review | MCP / mixed | 58 → 58 | Current and later references lost | Same |
| Public page navigation and screenshots; later spreadsheet | MCP / Chinese | 50 → 50 | Current reference lost | Same |
| Public repository files, issues and PR inventory; later code review | MCP / mixed | 42 → 42 | Current reference lost | Same |
| Date-aware city time conversion with daylight saving | MCP / synonyms | 11 → 11 | Current reference lost | Same |

Both arms pass 2/4 Skill, 0/4 plugin and 0/4 MCP needs. By language they pass
1/4 Chinese, 1/4 synonym-oriented and 0/4 mixed needs. Multitask success is
2/9; single-task success is 0/3. These tiny overlapping strata are diagnostics,
not estimates of category-wide accuracy.

Across 21 required current/later reference groups, retrieval retains **11/21**:
4/12 current and **7/9 later**. All required groups survive for only 4/12 needs.
Primary-anchor occurrence coverage is also 11/21. The whole pool is retained
after recall, but that does not recover a later capability already omitted by
retrieval.

## Time and token cost

Four eligible needs run once per arm, in alternating arm order: **8 calls and
28,827 reported tokens** total, without retries, missing usage, transport errors
or unknown sends. The predeclared ceiling was 24 calls, 200,000 tokens and 120
seconds, with a 20-second per-call timeout. Known recall failures are not sent
merely to consume the unused allowance.

The means below cover the **same four live pairs**, not all twelve needs.
Skipped failures are not treated as successful zero-cost calls.

| Mean per dispatched need | Compact | Coverage | Change |
| --- | ---: | ---: | ---: |
| Total tokens | 3,551.5 | 3,655.25 | +2.92% |
| Input tokens | 3,105.5 | 3,209 | +3.33% |
| Output tokens | 446 | 446.25 | +0.06% |
| Jev CLI seconds | 0.582 | 0.569 | -2.27% |
| Final-dispatch seconds | 0.619 | 0.629 | +1.76% |
| Warm selector seconds | 0.661 | 0.672 | +1.64% |

Warm selector time combines the common freshly measured retrieval duration and
each arm's final dispatch. Lexical and structured index construction take
0.579 and 3.834 seconds respectively, reported separately. The CLI-only time
decrease is not an overall speedup. Four pairs and one pass do not establish a
stable latency difference. Main-Agent time/tokens, monetary cost and backend
model revision remain unobservable; these measurements cover the selector.

## What the failures establish

The main observed bottleneck precedes Jev. The current object vocabulary
recognizes no object for the Kubernetes, search-friendly article or time-zone
requests. Those requests run zero structured supplemental queries, even when
some category terms are recognized. Other requests recognize only a broad or
later-step object: code instead of local browser testing, observability instead
of debugging, and code instead of library documentation or repository lookup.

Vocabulary expansion alone is not established as a complete repair. The
repository request contains the literal word GitHub, yet none of its four
predeclared GitHub references survives. Code-review references also disappear
despite a recognized code object. Bounded lexical/structured query slots and
ranking need further diagnosis; this run does not isolate the exact rank cause
for every omitted candidate. Negative context can also add recall noise: the
dashboard's exclusion of a database still triggers the database object.

When references do survive, several similar candidates divide the Choice
probability. In the dashboard case, the primary frontend reference is present
but competes with other frontend/artifact descriptions. Accessibility likewise
has multiple audit candidates; the coverage hint does not resolve the tie.
Their returned confidence remains below 0.7 in both arms. This is a final-choice
ambiguity, distinct from retrieval loss; probabilities are not summed or the
gate lowered to turn an abstention into a pass.

The result argues against promoting this candidate or continuing to judge it
only on the two known repaired requests. A later repair should address recall
coverage and distinguish overlapping candidates while preserving later needs.
This round makes no such algorithm change, so the new failures remain honest
regression fixtures for subsequent work.

## Verification and preservation

Ten new offline runner/grading checks pass, covering alternative references,
primary-anchor visibility, mandatory later groups, every-trace retention,
fixture strata, raw-need/one-call contracts, offline no-send, budgets and unknown
outcome no-replay. Prior selector checks remain valid because those files are
unchanged. The receipt analyzer reconciles all 24 result rows and eight
pending/done pairs, frozen requests/references/catalog/source/executable,
additive pools, mappings, locally revalidated responses and usage totals.
It makes no model calls.

A fresh post-test snapshot matches all 459 protected files and both other
worktrees' HEAD/status. Daily installation and the concurrent lifecycle upgrade
are untouched. This branch contains benchmark fixtures, runner/analyzer, tests
and reports; it does not change the frozen selectors or promote them to runtime.

Artifacts: [request strings](../benchmarks/directory-depth/unseen_breadth_requests.json),
[predeclared references](../benchmarks/directory-depth/unseen_breadth_references.json),
[sanitized results](../benchmarks/results/backpack-unseen-breadth-2026-10-16.json),
[runner](../benchmarks/directory-depth/unseen_breadth_experiment.py),
[receipt analyzer](../benchmarks/directory-depth/analyze_unseen_breadth.py),
[offline checks](../tests/test_unseen_breadth.py).
The [preceding two-failure repair](backpack-requirement-coverage-2026-10-16.md)
remains unchanged as historical evidence.
