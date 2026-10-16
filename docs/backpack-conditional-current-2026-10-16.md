# Conditional retrieval: one-call current-step selection

The current-step instruction repairs all three original final-selection failures
in this paired trial. It retains every recalled candidate and still makes one
Jev call per eligible need with a final confidence threshold of 0.7. Overall
strict success rises from 2/7 to 5/7. Two new document/spreadsheet needs fail
offline reference coverage before final selection, so the complete strategy
does **not** meet the no-omission acceptance criterion and is not promoted to the
daily connection.

## Change and fixed conditions

The previous conditional-retrieval experiment used the generic final question
from the merged catalog. It had not incorporated the existing
`current_step.CURRENT_LEAD`, previously tested on the smaller directory. This
candidate reuses that instruction: choose for the explicitly current step or
stated execution order, rather than the entire workflow or mere mention order.
Do not invent an order if none is specified. Later-useful capabilities remain
available.

Only this instruction lead differs between arms. Both receive the same raw
Chinese/mixed-language request, identical full descriptions, candidate IDs and
ordering, and `none` option. No English task summary, extra judgment question,
confidence adjustment, extraction model, retry or second Jev call is added.
The program returns the complete recalled pool even on abstention; it does not
claim that all retained candidates are relevant later capabilities.

The frozen public catalog still contains 45,325 entries: 682 standalone Skills,
628 whole plugins and 44,015 MCP records. The 376 historical control Skills are
explicitly included within those counts, not newly enabled sources. Markets
remain merged and plugins are not split into constituent Skills. Source ranking,
retrieval, deduplication and descriptions are unchanged.

## Scope and preflight

The three old failures retain their exact original needs, references and recall
objects. The two previously passing needs are excluded. Four new author-written
combinations were fixed before checking retrieval: culture then observability,
Jira then finance with a cancelled dependency review, Word then spreadsheet, and
spreadsheet then Confluence with a cancelled Word task. Product names and file
formats appear as ordinary requirements; no Skill identifier is requested.

All five eligible needs retain their complete references. The two file-oriented
needs omit the frozen Anthropic `docx`/`xlsx` references. They count as failures
for both arms and receive no live request. Gold IDs are used only to grade and
decide whether a known-incomplete pool should consume test calls; they are never
passed to retrieval or Jev. This gold-based preflight is an evaluation mechanism,
not an available production completeness detector.

| Need | Pool | Baseline final | Current-step final | Required references retained |
| --- | ---: | --- | --- | --- |
| Original: finance, then dependency review and wiki | 56 | Abstain, 0.22 | Correct, 0.88 | 3/3 |
| Original: observability, then finance and culture | 55 | Abstain, 0.50 | Correct, 0.93 | 3/3 |
| Original: cancel finance, keep discovery then Jira | 66 | Abstain, 0.55 | Correct, 0.98 | 2/2 |
| New: culture now, observability later | 37 | Correct, 1.00 | Correct, 1.00 | 2/2 |
| New: Jira now, finance later | 42 | Correct, 0.98 | Correct, 0.99 | 2/2 |
| New: Word now, spreadsheet later | 43 | Preflight failure | Preflight failure | 0/2 |
| New: spreadsheet now, wiki later | 60 | Preflight failure | Preflight failure | 1/2 |

The original failures improve from 0/3 to 3/3. New-case strict success is 2/4 in
both arms. All seven retain 13/16 required reference occurrences, including 8/9
later-reference occurrences. The terminal question introduces no additional
candidate loss, but cannot recover a reference already omitted by retrieval.

## Measured cost

These means cover the **same five live pairs**. The two skipped failures remain
in the seven-case success denominator but do not artificially lower mean model
cost or latency. Each pair alternates which arm runs first. One live paired pass
does not establish a stable latency difference.

| Measure | Baseline | Current-step | Change |
| --- | ---: | ---: | ---: |
| Strict current selection plus full reference retention | 2/7 (28.6%) | 5/7 (71.4%) | +3 needs |
| Jev calls per live need | 1 | 1 | 0 |
| Mean reported input + output tokens | 4,792.6 | 4,874.2 | +1.70% |
| Mean Jev CLI seconds | 0.566 | 0.638 | +12.71% |
| Mean final-dispatch wall seconds | 0.585 | 0.658 | +12.46% |
| Mean selector seconds including query time | 0.600 | 0.673 | +12.14% |

The instruction costs about 82 extra reported tokens per live need. This is an
accuracy improvement at slightly higher measured token cost, **not** a time or
token reduction. All ten requests total 48,334 reported tokens, below the frozen
14-call/120,000-token cap; the three old failed needs consume 33,302 of those
tokens across both arms. No request is automatically retried and no previously
passing need is retested.

Index construction is separately measured at 0.485 seconds. Query times for the
three reused recall objects are historical measurements, identical in both
arms; the final-dispatch and CLI times are freshly observed. Full main-Agent
time/tokens, monetary cost and actual backend model revision are unobservable.
Reported costs measure selection, not capability installation or task execution.

## Remaining retrieval issue

Read-only diagnostics reproduce the lexical ranking without another model call.
The unchanged search takes eight results per clause and three per bilingual
concept, retaining boundary ties. The required `xlsx` reference ranks 72nd for
`spreadsheet excel csv xlsx`; the required `docx` reference ranks 418th for the
Word clause after its generic project/interview expansions. Neither reaches
the recall union. Other document/spreadsheet MCP candidates are recalled, but
their equivalence and actual execution were not tested, so they cannot silently
replace the predeclared references or turn these failures into passes.

This identifies a retrieval cutoff failure, rather than a 0.7 final-threshold
failure. The next isolated retrieval experiment should protect explicit file
formats and concrete operations from broad concept competition, without
hard-coding publishers or dropping later clauses. The present paired experiment
is not changed after observing these failures.

## Verification and limits

Twenty-two affected offline checks pass, covering raw-request preservation,
one-call behavior, malformed/unknown answers, strict 0.699/0.7 acceptance,
retained pools, recall behavior and exclusion of previously passed needs.
Frozen input/source/executable hashes, all ten pending/completed receipt pairs,
the raw answers, candidate pools and reported usage reconcile. There are no
retries, unknown sends, transport errors or missing usage.

At the post-test protection check, all 459 protected files and both other
worktrees' HEAD/status match the fresh starting snapshot. This experiment writes
only the isolated test branch: no daily installation, private-catalog change,
dispatcher replacement or concurrent lifecycle upgrade is performed.

This is a single author-written development trial, not blind generalization
evidence. All five live current references are historical control Skills; the
new public-publisher references fail retrieval. No real business task is
executed, and no claim of plugin/MCP execution accuracy follows from this test.
Retain the current-step final as an experimental improvement while keeping the
overall strategy unpromoted until retrieval coverage is repaired and verified.

Artifacts: [sanitized results](../benchmarks/results/backpack-conditional-current-2026-10-16.json),
[selector](../benchmarks/directory-depth/conditional_current.py),
[new cases](../benchmarks/directory-depth/conditional_current_cases.json),
[frozen runner](../benchmarks/directory-depth/conditional_current_experiment.py),
[receipt reconciliation](../benchmarks/directory-depth/analyze_conditional_current.py),
and [affected checks](../tests/test_conditional_current.py).

The earlier [find-style comparison](backpack-conditional-find-2026-10-16.md)
and [small-directory current-step trial](backpack-current-step-2026-10-16.md)
remain separate historical results. The bounded Choice shape is consistent with
the [official Jev CLI documentation](https://github.com/okooo5km/jev/blob/main/README.en.md);
the documentation itself is not evidence of this experiment's accuracy.
