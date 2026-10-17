# Typed final selection and reversible compression

The compact treatment reduces mean reported Jev tokens by **29.52%** versus
the unchanged current-step selector, from 6,146.3 to 4,332 on the same three
dispatched needs. It does **not** improve strict success: all three arms pass
2/4 frozen needs. Warm selector time is 0.675 versus 0.692 seconds (+2.50%),
so this trial does not show an overall speedup. The candidate remains isolated;
daily promotion is not accepted.

## Change and comparison

The previous final question calls every option a Skill and describes selection
as guidance-only, despite the merged catalog containing 682 Skills, 628 whole
plugins and 44,015 MCP entries. The typed treatment corrects this mismatch and
asks Jev to compare all operations, outputs and constraints of the current step
together, preferring explicit support over broad topic overlap.

One shared legend explains the observed modes: Skill guidance, whole plugin
with package requirements unverified, and MCP with execution requirements
unverified. Readiness is unobserved for every option; unverified does not mean
unavailable. Type is not an automatic preference. Selection never grants
permission or proves a capability can execute. Later candidates remain in the
complete retained pool, including after abstention.

The three arms are:

1. `current_full`: unchanged final question, canonical IDs and full descriptions.
2. `typed_full`: corrected question plus kind/mode labels, otherwise unchanged.
3. `typed_compact`: the same typed question and labels, with reversible short
   option IDs and conservative leading boilerplate compression.

Compression maps opaque option IDs to `c1`, `c2`, etc. in unchanged catalog
order, then restores returned choices and distribution keys to canonical IDs.
Confidence and probabilities are never changed. No candidate is merged or
removed. Only recognized generic leading trigger prose can be shortened;
the remainder of each description, including restrictions, formats, examples
and platform requirements, survives byte-for-byte. Across the three live
pools, short IDs save 1,176 / 1,528 / 1,929 request characters; description
rewrites save only 37 / 0 / 74. The major text reduction is identifier encoding,
not deleting operational detail. Individual token effects are not isolated.

## Frozen cases and outcomes

The only previous failure is reused with its exact request, reference labels,
48-candidate pool and query duration. Three author-written new needs are frozen
before recall, with one whole-plugin, one MCP and one Skill current reference.
They are ordinary requests without capability identities, but are development
examples informed by public metadata, not blind independent evaluation.

Retrieval, catalog ordering, raw requests and the final **0.7 gate** are fixed
across all arms. New pools use the unchanged structured retrieval. No market
fetch, installation or daily-runtime change occurs. Arm order rotates; every
eligible arm makes one independent Choice call, with no retry or rewrite.

| Need | Shared pool | Current full | Typed full | Typed compact |
| --- | ---: | --- | --- | --- |
| Original: editable presentation with speaker notes, then Word handout | 48 | Correct raw first choice; abstain 0.56 | Correct raw first choice; abstain 0.61 | Correct raw first choice; abstain 0.65 |
| New: read-only reference/layout workflow, then Word manual | 42 | Offline failure | Offline failure | Offline failure |
| New: OpenAPI/GraphQL to typed SDK, CLI and MCP, then code review | 62 | Pass 1.00 | Pass 1.00 | Pass 1.00 |
| New: Word template revisions, then PDF forms/password protection | 75 | Pass 0.92 | Pass 0.87 | Pass 0.90 |

The presentation reference remains first in all three distributions. Competing
presentation descriptions still receive probability mass. A higher confidence
on one observation is not improved accuracy, and 0.65 remains a failure. The
earlier 0.51 observation is historical; the fresh control is 0.56.

The new plugin workflow retains the correct current plugin but misses the later
Word reference. It remains a failure in every denominator and receives **zero
model calls**. The frozen object recognizer accepts `Word 文档` and `Word
template`, but misses `Word 操作手册` and `Word 模板`; the saved request facets
contain only `slides`. Therefore the Word supplemental/format path never runs,
and lexical recall also lacks the frozen reference. This identifies a concrete
mixed-language retrieval gap, not a Jev final-selection failure. The code and
case are not modified after seeing this result. A future repair must preserve
the negative `Word Counter` distinction instead of matching every `word`.

Seven of eight current/later reference occurrences survive; three of four
later references survive. All four current references are recalled. These are
strict reference metrics, not proof that other candidates are incapable or that
every equivalent capability survives. Only the new MCP and Skill selections
are accepted; no actual capability task is executed, and no live whole-plugin
selection is claimed.

## Measured cost

Cost means below use the same **three dispatched needs** per arm. The skipped
need stays in the 2/4 success denominator and is not counted as a free success.

| Measure | Current full | Typed full | Typed compact |
| --- | ---: | ---: | ---: |
| Strict success, all frozen needs | 2/4 | 2/4 | 2/4 |
| Complete reference coverage | 3/4 | 3/4 | 3/4 |
| Calls per eligible need | 1 | 1 | 1 |
| Mean total tokens | 6,146.3 | 6,309.3 | 4,332.0 |
| Mean input tokens | 4,581.7 | 4,744.7 | 3,760.7 |
| Mean output tokens | 1,564.7 | 1,564.7 | 571.3 |
| Mean Jev CLI seconds | 0.608 | 0.659 | 0.596 |
| Mean final-dispatch seconds | 0.630 | 0.707 | 0.647 |
| Mean warm selector seconds | 0.675 | 0.752 | 0.692 |
| Mean candidates | 61.67 | 61.67 | 61.67 |

Compact versus current saves 29.52% total tokens: input falls 17.92% and output
63.49%. Compact versus typed-full saves 31.34%. Jev returns option-keyed
distributions, so short IDs reduce both request and response text. The full
typed treatment alone adds tokens without a strict pass gain on this sample.

Warm time includes the shared local query and final assembly. Typed assembly
also builds a catalog ID map and validates/maps the answer. Its observed
dispatch-minus-CLI time is about 51 ms versus 22 ms for current-full; these are
local aggregate overheads, not individually profiled function timings. A single
pass cannot establish stable latency differences. The unchanged indexes take
0.491 + 3.918 = 4.409 seconds to construct, excluded from warm measurements.
The old failure's query duration is historical; new query durations are fresh.
Root-Agent work, monetary cost and actual backend model revision are unobserved.

## Verification and decision

All nine actual pending/done pairs reconcile against frozen sources, catalog,
inputs, raw requests, option order, canonical mapping, confidence, complete
retained pools and usage. Total reported usage is **50,363 tokens**, within the
12-call/140,000-token cap. No retry, unknown send, missing usage or transport
error occurs. The unused call allowance does not trigger extra experiments.

Twenty-eight affected offline checks pass: 12 final/runner checks and the
unchanged 16 structured-recall checks. They cover exact baseline preservation,
constraints, ID/distribution round trips, the 0.7 boundary, complete later-pool
retention, unknown modes/IDs, one-call limits, zero-call preflight failures,
budgets and no replay after unknown outcomes. Actual receipt analysis is
separate from these synthetic checks.

All 459 protected files and both other worktrees' HEAD/status match the fresh
starting observations at the post-test check. Daily installation and the
concurrent lifecycle upgrade are untouched. Previously passing requests are
not replayed, so their final confidence under the new question is untested.

Retain reversible short IDs as a promising cost optimization. Do not claim
the typing change resolves presentation ambiguity or promote this candidate.
The remaining issues are the below-0.7 presentation final and the newly observed
Word manual/template recall gap. Preserve both failed records for the next
bounded repair.

Artifacts: [sanitized results](../benchmarks/results/backpack-final-contrast-2026-10-16.json),
[final selector](../benchmarks/directory-depth/final_contrast.py),
[new cases](../benchmarks/directory-depth/final_contrast_cases.json),
[runner](../benchmarks/directory-depth/final_contrast_experiment.py),
[receipt analyzer](../benchmarks/directory-depth/analyze_final_contrast.py),
[offline checks](../tests/test_final_contrast.py).
