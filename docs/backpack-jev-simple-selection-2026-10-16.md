# Simplified selection pilot — 2026-10-16

The comparative final selector cut measured final-stage tokens by **53.49%**,
but did **not** improve frozen acceptance: **0/3 → 0/3** on the three previously
failed cases. Keep this as an experiment; do not replace the daily selector.
There were exactly three new Jev requests, no retries and no repeated passed cases.

## Controlled comparison

Reuse the exact `.65` directory pools from the
[previous taxonomy experiment](backpack-jev-semantic-taxonomy-2026-10-16.md).
Keep original Chinese/mixed requests, candidate order, original names/types/full
descriptions, the final **0.7** threshold, and the full later-candidate reservoir.
No task keywords, English rewrites, gold IDs or suitability heuristics enter selection.

The old selector asked a separate current/partial/other question for each candidate,
then sorted qualifying independent confidences. The new selector asks one comparative
Choice question over every candidate plus `none`. Metadata appears once per option;
the task and common policy appear once. Raw provider confidence determines acceptance.

This compares two selector packages: the prompt, representation and Choice structure
change together. It does not isolate confidence sorting, prompt wording or serialization.
**Both packages already use one final API request per task.** Only the number of
questions in those requests changes, from 317 total to 3.

| Final-stage measure, same three cases | Previous | Comparative |
|---|---:|---:|
| Frozen omission-safe passes | 0/3 | 0/3 |
| Known current references retained | 3/3 | 3/3 |
| Required later reference groups retained | 1/1 | 1/1 |
| API requests | 3 | 3 |
| Input tokens | 60,202 | 30,522 |
| Output tokens | 11,739 | 2,938 |
| Total tokens | 71,941 | 33,460 |
| Sum of transport durations | 2.564 s | 2.146 s |

Transport duration fell 16.32% in this single paired sample. Root calls were cached;
these are **not fresh end-to-end timings**. Provider model revision is unobservable.
Reported token counts are provider receipts, not estimates or price calculations.

## What prevented acceptance

| Request | Pool | Previous selection | Comparative outcome |
|---|---:|---|---|
| Python API exception design, later code review | 113 | `spec-driven-workflow`, .77 | `senior-backend`, .83; outside frozen current references |
| Access-control design and privilege risks | 113 | `spec-driven-workflow`, .70 | Abstain; `backend-api-security` leads at .51 |
| Test-first red/green/refactor plan | 91 | `spec-driven-workflow`, .94 | Abstain; `tdd-workflows` leads at .62 |

The last two top candidates explicitly describe the requested subjects, but competing
plausible options retain substantial probability: access control assigns .34 to
`senior-backend`, and TDD assigns .31 to `tdd-guide`. Comparative certainty remains
below .7. No probabilities are summed, renormalized or promoted to force acceptance.

Correction from the subsequent reference audit: **both leading plugins are already
in the frozen acceptable lists**. An earlier description of this result incorrectly
read a deduplicated display as missing reference entries. No labels need changing;
both candidates still abstain, and the original **0/3** score is unchanged.
The exception case remains ambiguous: the reference package names error handling, while the selected
Skill names backend/API design; neither short description establishes every requested
retry/logging detail. A failed frozen score is not proof that every alternative is wrong.

## Directory-union repair, offline only

The recorded `.2` root responses select six authored directories plus the unknown
bucket. Each authored directory contains at most 91 items, yet their unique combined
pool contains **211**. The old builder leaves every small root terminal, preventing
further expansion when their union is too large.

`union_directory_refinement.prepare` checks that unique union and, above 128, prepares
real child-membership classification for all selected deferred roots. It reuses the
existing Jev leaf-classification specification and original catalog metadata; it never
invents membership from a child description. It retains previous splits, canonical
memberships, overlapping and unknown paths, and validates whole-catalog reachability.
At or below 128 it makes zero calls. The existing .5 unknown-path enrollment rule is
unchanged and is separate from the .7 final-selection threshold.

Eight injected-response tests passed. Preflight with the real catalog and the same
three recorded root responses requires seven additional classification batches over
195 memberships, reserving 140,040 tokens. **Those real calls were not sent**, because
the cheaper final-selection pilot did not meet acceptance. The structural helper is
not evidence of semantic child-classification quality or a completed live routing flow.

## Evidence and bounds

- New pilot cap, frozen before dispatch: 3 calls, 70,000 tokens, 90 seconds, 20 seconds
  per call, no retry. Pre-send reservations totaled 65,648; actual usage was 33,460.
- Old root and final receipts were replayed without provider calls. New requests,
  responses, grades, usage and stopping state passed exact receipt replay.
- Nine selector tests, eight union tests and twenty existing builder tests passed.
- The source catalog has 45,325 public entries, but this pilot uses the previous
  enriched 240-record sample and three already exposed failures. It is neither a
  blind evaluation nor an estimate of general catalog accuracy.
- Coverage means the fixed known current/later references remain reachable; it does
  not establish that every valid capability was identified.
- No Skill/plugin/MCP was acquired or executed. Direct/frequent shortcut integration
  was not exercised. No daily runtime or parallel-upgrade source was modified.

The [sanitized measurements](../benchmarks/results/backpack-jev-simple-selection-2026-10-16.json)
contain the per-case results and preflight. Raw receipts and frozen inputs remain in
the local `jev-simple-selection-20261016` evidence directory. Reproduce receipt analysis
with `python3 benchmarks/simple_selection_pilot.py analyze <evidence>/final-pilot`;
`run` refuses an existing live directory and is not a retry command.

Official [Choice documentation](https://docs.typesafe.ai/primitives/choice) informed
the single comparative question. This documentation supports the API design, not a
claim that comparative selection improves task accuracy.
