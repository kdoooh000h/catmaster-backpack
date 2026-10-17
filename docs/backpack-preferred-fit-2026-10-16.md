# Highest probability, then suitability — 2026-10-16

The experimental selector now uses Jev's highest-probability candidate without
requiring it to dominate similar alternatives. Only that candidate receives the
existing independent current/partial/other suitability check. It must still be
`current` at raw confidence **>=0.7** before selection. No thresholds, probabilities
or candidate memberships are rescaled or combined.

This changes the two previously blocked requests from **0/2 to 1/2 under the original
frozen references**, with no label edits. It is a two-case repair check, not general
accuracy or execution validation. The daily version remains unchanged.

## Behavior

1. Compare the complete recalled pool using the unchanged comparative Choice.
2. Use Jev's maximum-probability option. Equal maxima keep Jev's returned choice.
3. Check only that option against the complete original request and its full original
   description, reusing the old independent suitability definitions and 0.7 gate.
4. Retain the complete pool for later work regardless of acceptance. If the winner
   fails qualification, stop without trying another candidate. This does not imply
   that no remaining candidate could help. A leading `none` starts no qualification.

There is no programmatic relevance/similarity filter, rewritten English task, new
rank weighting, capability acquisition or execution. A high ranking confidence also
cannot bypass the suitability check. Plugin packages remain whole.

The standalone runtime path has two requests, with a small second payload. This trial
reused the exact recorded ranking requests/responses, so only two fresh qualification
requests were sent. It did not repeat roots, rankings or passed cases.

## Actual results

| Original ordinary request | Highest-probability candidate | Ranking confidence | Suitability confidence | Outcome |
|---|---|---:|---:|---|
| Access-control planning and privilege risks | `backend-api-security` | .51 | **.70** (`current`) | Selected, original-reference pass |
| Test-first red/green/refactor planning | `tdd-workflows` | .62 | **.58** (`current`) | Abstained below .7 |

The TDD response assigns .72 probability to current support, .26 to partial support
and .02 to other support. Its raw three-option Choice confidence is .58. Using the
.72 probability as if it were confidence would change the old gate's meaning; this
experiment does not do that. The response establishes uncertainty but does not
identify its underlying semantic cause. No further prompt changes or retries ran.

Both winners are in the original acceptable-reference lists. This corrects the
[previous report's](backpack-jev-simple-selection-2026-10-16.md) mistaken commentary
about missing references, caused by misreading a deduplicated display. The previous
0/3 result remains correct: both then failed the comparative confidence gate.

| Cost for the same two cases | Comparative selector alone | Ranking plus qualification |
|---|---:|---:|
| Original-reference passes | 0/2 | 1/2 |
| Logical final-selection requests | 2 | 4 |
| Tokens | 21,745 | 23,179 |
| Sum of recorded transport durations | 1.426 s | 3.320 s |

The addition costs **1,434 tokens (+6.59%)** and **1.894 seconds** in two new requests.
Ranking plus qualification uses cached ranking receipts plus fresh qualification;
these sums are composite accounting, **not fresh end-to-end latency**. The extra
request increases transport time in this small observation; no speedup is claimed.
The fresh runner wall time is 9.735 seconds, including repeated frozen-file integrity
checks. That verification overhead is separate from the 1.894 seconds of provider
transport and is not measured production selector latency. Backend model revision
and execution readiness remain unobservable.

## Verification and limits

- Eight focused offline tests cover below-gate ranking acceptance, inclusive .7 fit
  gate, partial/other rejection, ties, `none`, complete-pool retention, unchanged raw
  task/metadata, invalid responses and unknown-outcome propagation without retry.
- Exact cached ranking and new fit receipts replay to the same selection, original
  reference grade, token counts and stop state.
- The frozen pilot cap was two calls / 10,000 tokens / 60 seconds, with a 20-second
  call timeout and no retries. Estimated reservations totaled 6,921 tokens; actual
  usage was 1,434 tokens. Every send completed with known usage.
- These two exposed cases have no separate later-requirement groups. Full original
  reservoirs of 113 and 91 candidates are retained; later behavior is not newly
  established by these two real calls.
- No production installation, direct/frequent shortcut integration or real
  Skill/plugin/MCP execution was performed. This only changes the isolated selector.

[Sanitized measurements](../benchmarks/results/backpack-preferred-fit-2026-10-16.json)
include per-case results and qualifications. Raw receipts remain in the local
`jev-preferred-fit-20261016` evidence directory. Replay with
`python3 benchmarks/preferred_fit_pilot.py analyze <evidence>/pilot`.

The official [Skill suggestion cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion)
also separates ranking from a later fit check. This experiment keeps the project's
existing three-way suitability question and .7 confidence gate; it does not adopt
the cookbook's lower Noul thresholds or claim its benchmark results.
