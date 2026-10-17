# Word aliases and explicit requirement coverage

Both remaining known failures pass in this bounded repair. The later Word
reference is restored without removing any original candidate. Literal
description hints plus an explicit current-step detail criterion select the
presentation Skill at **0.78** and the whole-plugin workflow at **0.99**, above
the unchanged **0.7** gate. All four current/later reference occurrences survive.

This is a regression result for two known needs, not evidence of general
accuracy or an installed-runtime upgrade. Previously passing needs are not
replayed, no capability is installed or executed, and daily behavior is unchanged.

## Two distinct causes and repairs

The Word omission occurs before Jev. The prior vocabulary recognizes `Word
文档` and `Word template` but misses `Word 操作手册` and `Word 模板`. The repair
recognizes Word followed by document nouns such as manuals, templates, reports,
contracts and handouts, including Chinese variants. It adds `Word document`
only to a supplemental local search. The unchanged raw request still reaches
Jev. Existing original candidates are retained in a union, explicit kind filters
remain effective, and an over-96 pool stops rather than truncating. The pattern
does not match Word Counter, WordPress, password or keyword.

The affected pool grows from 42 to 50 and recovers the later Word reference.
The presentation pool remains exactly 48. This is a bounded vocabulary repair;
unknown expressions can still be missed and no universal recall guarantee is
claimed.

The presentation problem occurs after recall. Several entries describe creating
editable presentations, while the long Skill description explicitly includes
speaker notes and layouts. The repair brings matching details forward as short
literal excerpts. A detail must match both the raw need and positive source
metadata through the same bilingual vocabulary. Excerpts are copied from the
description; they are not new capability claims. Negated request clauses and
negative metadata do not supply positive hints. Full descriptions and the entire
raw request remain available so Jev can resolve current/later steps, exclusions
and constraints. An absent hint means unknown, not inability.

The final `coverage` treatment additionally asks for explicit support for the
requested output and its specific details together, instead of inferring a
detail from a broad output promise. No candidate ranking, source preference,
gold ID, probability rescaling, second question or extra model call is added.
Short IDs remain reversible and all canonical identities are retained.

The [TypeSafe primitive documentation](https://docs.typesafe.ai/primitives)
defines Choice as selecting from supplied options. Its
[confidence documentation](https://docs.typesafe.ai/confidence) distinguishes
the returned confidence from the top probability. This experiment retains the
provider's Choice confidence and the same 0.7 boundary; it does not replace
them with an independent yes/no probability or a recomputed statistic.

## Frozen comparison

Only the two failed needs from the preceding run are included, byte-for-byte,
with unchanged reference labels. Three arms share the same alias-repaired
candidate pools, catalog order, raw requests, original compact descriptions and
short IDs:

- `compact`: the prior final question, now receiving the repaired pool.
- `evidence`: adds literal matching-detail prefixes and their explanation.
- `coverage`: adds the explicit requested-detail criterion to `evidence`.

Thus live comparisons isolate final-selection changes. The alias repair is
common to all live arms and is separately checked against the saved original
recall. The original plugin case was previously blocked offline; there is no
invented historical call or zero-token successful baseline for that case.

| Unchanged need | Original → repaired pool | Compact | Evidence | Coverage |
| --- | ---: | --- | --- | --- |
| Editable presentation with speaker notes/layouts, then Word handout | 48 → 48 | Correct raw choice; abstain 0.62 | Pass 0.71 | Pass 0.78 |
| Read-only reference/layout workflow, then Word manual | 42 → 50 | Pass 0.93 | Pass 0.93 | Pass 0.99 |

All arms preserve both current and both later references after repair. The
original recall had retained three of those four occurrences. Strict success
in the fresh live comparison is **1/2 → 2/2 → 2/2**. Earlier presentation
observations of 0.51/0.56/0.65 are historical and are not substituted for the
fresh 0.62 baseline. Higher confidence in one run does not establish calibration
or stability. The two current targets are one public Skill and one whole plugin;
alternative capabilities are not declared incapable merely because they are
outside the frozen reference set.

## Time and token cost

All six calls complete once, in rotated arm order, with **25,852 reported tokens**
inside the frozen 6-call/60,000-token cap. There are no retries, unknown sends,
missing usage or transport errors. Every eligible need still needs one Jev call.

| Mean per need | Compact | Evidence | Coverage |
| --- | ---: | ---: | ---: |
| Strict pass count | 1/2 | 2/2 | 2/2 |
| Total tokens | 4,226 | 4,319.5 | 4,380.5 |
| Input tokens | 3,769 | 3,862.5 | 3,923.5 |
| Output tokens | 457 | 457 | 457 |
| Jev CLI seconds | 0.648 | 0.618 | 0.592 |
| Final-dispatch seconds | 0.685 | 0.680 | 0.639 |
| Warm selector seconds | 0.721 | 0.716 | 0.674 |

Coverage costs **3.66% more tokens** than compact and **1.41% more** than
evidence. Its measured warm selector time is 6.40% lower than compact, but two
known cases and one pass cannot demonstrate a stable speedup. The evidence-only
variant is slightly cheaper and also passes; coverage is retained as the
working experimental candidate because it expresses the desired selection
criterion explicitly, with only 61 additional tokens per need in this run.
This is a policy/design choice supported by a small regression, not proof of
superiority from confidence alone.

The common structured index takes 3.974 seconds to construct, excluded from
warm time. Shared retrieval includes the saved original query duration plus
fresh alias checking/supplemental search; therefore this is not a fresh cold
end-to-end runtime timing. All live final-dispatch measurements are fresh.
Root-Agent cost, monetary cost and backend model revision remain unobservable.

## Verification and scope

Twenty-four affected offline checks pass: 12 new alias/evidence/runner checks
plus 12 existing final-compression/runner checks. They cover mixed-language
document nouns and counterexamples, additive retention, kind filters, literal
evidence, negative clauses, unchanged descriptions/order, short-ID mapping,
0.7 abstention, one-call bounds, preflight failure, budgets and unknown-outcome
no-replay. One local preflight comparison initially compared canonical map
values with short keys; it was corrected before freezing or any model call.
The original empty attempt and correction are recorded separately.

The receipt analyzer verifies all six original pending/done pairs, unchanged
requests and labels, original and repaired pools, identity mapping, literal
prefixes, final outcomes, usage and source/input/executable locks. It reruns only
local validation of saved responses, never model calls. All 459 protected files
and both other worktrees' HEAD/status match fresh starting snapshots at the
post-test check. Daily installation and the other upgrade remain untouched.

The two requested known failures are resolved in this test. The experimental
candidate keeps alias supplementation, literal detail hints, the explicit
current-step criterion, short IDs and the 0.7 gate. It remains on the test branch;
unseen wording, other previously passed requests under this new question, actual
capability execution and daily lifecycle behavior are not newly validated.

Artifacts: [sanitized results](../benchmarks/results/backpack-requirement-coverage-2026-10-16.json),
[repair implementation](../benchmarks/directory-depth/requirement_coverage.py),
[frozen runner](../benchmarks/directory-depth/requirement_coverage_experiment.py),
[receipt analyzer](../benchmarks/directory-depth/analyze_requirement_coverage.py),
[offline checks](../tests/test_requirement_coverage.py).
The [preceding compression trial](backpack-final-contrast-2026-10-16.md) remains
unchanged, including both original failures.
