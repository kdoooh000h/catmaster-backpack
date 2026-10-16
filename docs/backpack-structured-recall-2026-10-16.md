# Structured metadata recall with one current-step Jev choice

Both original document/spreadsheet omissions are repaired in this trial. The
candidate retains all 12 required current/later reference occurrences across
six needs, versus 1/12 for the unchanged lexical baseline. Strict current-choice
plus full-reference-retention success is 0/6 versus 5/6. One new presentation
need retains the correct candidates but abstains at 0.51, below the unchanged
0.7 gate. The overall all-pass acceptance criterion is therefore not met.

The treatment remains an isolated benchmark candidate. It makes one Jev call
per need and improves coverage, but mean reported tokens increase 47.68% and
warm selector time increases 8.90% in this single paired pass. It is not a daily
runtime promotion, a general completeness guarantee or a cost-reduction result.

## Retrieval change

The original local lexical search remains intact. An additional local index
uses the same bilingual object/action vocabulary on requests and public
metadata. It indexes names, positive description hints, objects, actions, and
existing `topics`/publisher labels in separate weighted FTS5 columns. Thus
categories and specific operations can affect retrieval without another model
call. Full original descriptions, including negative constraints, are still
supplied to Jev unchanged; the positive-hint extraction affects only the added
search path.

The supplemental routes are:

- Generic file-format/object names, such as `docx`, `xlsx`, `pdf`, and `pptx`,
  receive a direct metadata-match path. This is a general format vocabulary,
  not a publisher, gold ID or source-specific allowlist.
- For each recognized object, weighted object/action/category retrieval adds up
  to three entries per capability kind, retaining every boundary tie. Skill,
  whole-plugin and MCP candidates have separate supplemental slots so that a
  large MCP population cannot consume every slot. Markets are not separated.
- The final pool is the union with **every original lexical candidate**. There
  is no global truncation: an over-96 pool stops before dispatch. Unknown
  classifications do not remove candidates. Explicit kind restrictions are
  preserved, and cancellation is left to Jev on the unchanged original need.

These are retrieval hints, not claims of installation, operational readiness,
permission or semantic equivalence. The full recalled pool is preserved for
later work, rather than labeling every candidate as a required later capability.
No new marketplace fetch, private catalog access, installation or provider
change occurs.

The implementation uses documented [SQLite FTS5 weighted columns](https://www.sqlite.org/fts5.html#the_bm25_function).
It avoids relying on rank fusion to recover an item absent from all input lists;
the [RRF documentation](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion)
describes fusion over existing result sets. The experiment tests the combined
facets, generic-name anchors and per-kind supplemental slots; it does not isolate
each factor's contribution.

## Frozen comparison

The two previous failed needs retain their exact requests, gold references and
baseline recall objects. Four author-written new needs are fixed before recall:
PDF OCR/merge followed by a spreadsheet, a presentation followed by a Word
handout, API review followed by a PDF, and code review followed by slides with a
cancelled spreadsheet task. No previously passing request is rerun. Product
names and formats describe ordinary tasks; no Skill or plugin identity is
specified in the requests.

Both arms use the same current-step final instruction, raw request, full original
descriptions, catalog ordering, `none` option and final 0.7 acceptance boundary.
Only the recalled candidate pool differs. The two arms alternate first/second
dispatch. Each has one typed Choice and no intermediate model, retry, task
summary or additional model question.

Low-cost preflight confirms complete candidate reference coverage and bounded
pools for all six. The known-incomplete baseline pools are also sent once to
obtain matched actual latency, usage and answer measurements; their omissions
remain failures. Gold labels never enter either index or Jev payload. The six
current references comprise four public publisher Skills and two historical
control Skills in the unchanged 45,325-entry public snapshot.

| Need | Baseline → candidate pool | Baseline final | Candidate final | Candidate references retained |
| --- | ---: | --- | --- | ---: |
| Original: Word, then spreadsheet | 43 → 58 | Other MCP, 0.71 | Correct Word reference, 0.97 | 2/2 |
| Original: spreadsheet, then wiki | 60 → 80 | Abstain, 0.46 | Correct spreadsheet reference, 0.96 | 2/2 |
| New: PDF OCR/merge, then spreadsheet | 44 → 60 | Abstain, 0.53 | Correct PDF reference, 0.75 | 2/2 |
| New: presentation, then Word handout | 33 → 48 | Abstain, 0.43 | Correct raw reference, abstain at 0.51 | 2/2 |
| New: API review, then PDF | 55 → 72 | Abstain, 0.47 | Correct API reference, 1.00 | 2/2 |
| New: code review, then slides | 42 → 64 | Abstain, 0.63 | Correct code reference, 1.00 | 2/2 |

The original failures improve from 0/2 to 2/2; the new combinations improve from
0/4 to 3/4. All six later reference occurrences are retained, versus one in the
baseline. The baseline's Word MCP alternative was not executed or independently
established equivalent to the frozen reference, so it does not turn that failure
into a pass. These strict-reference results do not prove that all other recalled
tools are incapable.

## Time and token cost

All six paired calls are included. The paired experiment totals 12 Jev requests
and 65,254 reported input/output tokens, within the frozen 12-call/140,000-token
cap. No failed request is retried and no passing request is replayed.

| Measure | Lexical + current-step | Structured + current-step | Change |
| --- | ---: | ---: | ---: |
| Strict current-choice plus all-reference success | 0/6 | 5/6 | +5 needs |
| Complete reference coverage | 0/6 | 6/6 | +6 needs |
| Jev calls per need | 1 | 1 | Unchanged |
| Mean total tokens | 4,391.0 | 6,484.7 | +47.68% |
| Mean input tokens | 3,177.0 | 4,883.5 | +53.71% |
| Mean output tokens | 1,214.0 | 1,601.2 | +31.89% |
| Mean Jev CLI seconds | 0.581 | 0.606 | +4.23% |
| Mean final-dispatch wall seconds | 0.602 | 0.625 | +3.85% |
| Mean warm selector seconds | 0.612 | 0.667 | +8.90% |
| Mean candidate count | 46.17 | 63.67 | +37.91% |

The supplemental local query costs 22–46 ms per need, averaging 31 ms. The union
adds 15–22 candidates with complete descriptions, which increases both request
size and returned Choice distributions. This preserves coverage at higher token
cost; there is no claim of simultaneous accuracy and cost improvement.

Index construction is separate: lexical construction takes 0.532 seconds and
the additional structured index takes 3.914 seconds, for 4.446 seconds to build
both. These in-memory indexes are built once for the comparison. Warm selector
figures exclude construction; no persistent daily cache or installed startup
performance is claimed. The original two lexical query durations are historical
measurements reused equally across arms; supplemental-query and final-dispatch
durations are fresh. One paired pass cannot establish stable latency behavior.
Root-Agent work, monetary cost and the actual backend model revision remain
unobservable; these are selection costs, not full business-task costs.

## Remaining failure and verification

The presentation case has no reference omission. Its raw first choice is the
correct `pptx` reference, with Choice confidence 0.51. The saved distribution
gives it 0.52, while `pptx-deck-creation` and Plus AI each receive 0.19, and Arcdeck
receives 0.09. Those are competing relevant descriptions; their equivalence and
actual readiness were not executed. Choice probabilities and confidence are
distinct fields and neither is measured task accuracy. The 0.7 gate is retained,
so this is an abstention and a recorded failure, not an accepted low-confidence
selection. No further call, threshold change or post-result fixture tuning occurs.

Sixteen affected offline checks pass, including category/action ranking,
bilingual normalization, negative metadata, baseline/later preservation, alias
descriptions, explicit kind conditions, whole-plugin identity, boundary ties,
overflow, and synthetic runner checks for one call, budgets and unknown-outcome
stops. Actual frozen-source/input/executable checks and all twelve pending/done
receipt pairs reconcile, including raw requests, descriptions, pools, 0.7
acceptance, grades and usage totals. There are no retries, transport errors,
unknown sends or missing usage.

At the post-test protection check, all 459 protected files and both other
worktrees' HEAD/status match the fresh starting observations. Daily installation,
private catalogs and the concurrent lifecycle upgrade are untouched. This is
one development trial, not a blind generalization study, and no actual plugin,
MCP or document-production task is executed. Previously passing needs are not
rerun: additive recall preserves their baseline pool in principle, but does not
establish unchanged final-choice confidence for those untested requests.

Artifacts: [sanitized results](../benchmarks/results/backpack-structured-recall-2026-10-16.json),
[retrieval implementation](../benchmarks/directory-depth/structured_recall.py),
[new requests](../benchmarks/directory-depth/structured_recall_cases.json),
[frozen runner](../benchmarks/directory-depth/structured_recall_experiment.py),
[receipt analyzer](../benchmarks/directory-depth/analyze_structured_recall.py),
and [offline checks](../tests/test_structured_recall.py).
The [previous current-step trial](backpack-conditional-current-2026-10-16.md)
remains an unchanged historical comparison.
