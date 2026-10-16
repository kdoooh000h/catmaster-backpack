# Public directory depth/width pilot

The [dependency-scope/cost follow-up](../../docs/backpack-dependency-cost-2026-10-16.md)
keeps adaptive traversal, current-step selection and all confidence gates. It
clarifies package-audit operations in one third-layer scope and its parent copy,
then separately tests a 0.35 versus 0.65 reading-cost stop at pools <=48. Seven
needs (one old failure, six new) pass 5/7 baseline, 7/7 description-only and 6/7
earlier-stop. Keep description-only as the isolated follow-up baseline: time is
flat, tokens rise 9.11%, and overall omission-safe cost reduction is not achieved.
The earlier-stop failure comes from a 99-candidate pool exceeding the 96 limit;
that path never triggers early stopping. An exact offline receipt replay isolates
score variation without adding model calls or replacing the live failure.
Nine offline checks and all 102 receipt pairs reconcile. Use
`dependency_experiment.py freeze/run` with the culture-scope bundle; the fixed cap
is 147 calls / 420,000 tokens / 360 seconds, one pass, no retries. No daily change.

The [culture-scope follow-up](../../docs/backpack-culture-scope-2026-10-16.md)
adds source-grounded culture operations to one first-layer description, retaining
current-step final selection, all memberships and the 0.7 gate. It retests the one
failed need and six new combinations. Culture survives all stages in 6/6 required
cases (previously 4/6), and strict complete passes improve 3/7 to 6/7. A new
third-layer later-dependency omission remains in both arms, so no daily promotion
occurs. Mean tokens rise 13.30% and time 8.18%; extra retained work has a cost.
Eight offline checks and all 68 receipt pairs reconcile. Use
`culture_scope_experiment.py freeze/run` with the current-step bundle as source;
the frozen cap is 98 calls / 300,000 tokens / 300 seconds, one pass, no retries.
Passed needs, installed versions and the other workspaces are left untouched.

The [current-step follow-up](../../docs/backpack-current-step-2026-10-16.md)
retests only the two failed multi-task needs and adds six new combinations.
Only final-dispatch instructions prioritize the explicit current step; raw needs,
directory policy, full candidates, later-target retention and the 0.7 gate remain.
Fresh paired runs improve complete selection/retention from 4/8 to 7/8, including
both original failures. A new reversed-order case loses its later culture target
at the first directory level in both arms, so the all-pass gate remains unmet.
Mean time is 2.875/2.796 seconds, tokens 13,378/13,481 and calls 4.875/4.875.
This is a selection improvement with nearly unchanged cost, not daily promotion.
Use `current_step_experiment.py freeze/run` with the breadth bundle as source;
the frozen limit is 112 calls / 350,000 tokens / 360 seconds, one pass, no retries.
Eight offline checks and all 78 live receipt pairs reconcile. Other passed needs
are not replayed; concurrent lifecycle-worktree changes are left untouched.

The [28-new-case breadth test](../../docs/backpack-adaptive-breadth-2026-10-16.md)
freezes both selectors and corrected metadata from the same-14 follow-up. Twenty
new targets span six roots and fourteen source domains, with four cross-root
combinations and four controls. Slim passes 20/20 single tasks and preserves all
required targets in 24/24 positive requests, but both arms abstain below 0.7 on
two combinations. Frozen overall scoring is 24/28 versus 26/28; one quotation
control is ambiguous, so the report also shows 24/27 versus 25/27 without it.
Mean tokens fall 34.75% and time 20.48%, with latency variability documented.
The all-pass gate is **not met**; no daily promotion or runtime change occurs.
Concurrent lifecycle-worktree changes are observed and preserved, not overwritten.

Use `breadth_experiment.py freeze/run` with the same command shape below and the
slim bundle as source. It delegates execution to the unchanged slim runner. The
plan freezes 28 new cases, one pass, no retries, 392 calls / 800,000 known tokens /
600 seconds. All failures stay in the denominator. New requests were written
after code freeze but have no independent blind review; no population accuracy
or stable speedup claim is supported.

The [same-14 slim follow-up](../../docs/backpack-adaptive-slim-2026-10-16.md)
preserves the corrected directory bytes and full final descriptions, removes
boundary review from the candidate, and reuses the original explicit-request
adaptive selector with whole-small-branch retention. Both fresh arms pass 14/14.
Mean reported tokens fall from 13,483 to 6,560 (51.35%), selector time from 3.563
to 2.498 seconds (29.89%), and calls from 4.71 to 3.57. Positive-only savings are
48.52% tokens and 23.11% time. This is one known-case regression pass, not unseen
validation or a daily promotion. Final confidence stays 0.7; daily 0.3.73 and the
other worktrees remain unchanged. Neither arm invokes boundary review, so the
comparison isolates the combined prompt/carry treatment after review removal.

```sh
python3 benchmarks/directory-depth/slim_experiment.py freeze \
  --source /path/to/repair/bundle --output /path/to/slim/bundle
python3 benchmarks/directory-depth/slim_experiment.py run \
  --source /path/to/slim/bundle --output /path/to/slim/live
python3 benchmarks/directory-depth/analyze_repair.py \
  --bundle /path/to/slim/bundle --live /path/to/slim/live \
  --output /path/to/slim/result.json
```

Freeze checks the original source and repaired bundle hashes. The plan permits
196 calls / 450,000 known tokens / 360 seconds, with no retries or in-run tuning.
Transport failure, missing usage, malformed output or budget exhaustion stops
the whole run; semantic failures remain in the denominator. Reuse passing
execution tests rather than rerunning other business tasks. The analysis helper
expects an owner-supplied `protected-before.json` in the evidence parent.

The [same-14 description repair and boundary-review experiment](../../docs/backpack-adaptive-repair-2026-10-15.md)
recovers the three known omission targets but costs substantially more. After an
explicit user budget extension, all 14 three-arm cases complete: baseline 13/14,
description repair 14/14 and boundary review 14/14. Mean tokens are 7,075 / 13,182 /
14,712; time is 2.22 / 2.63 / 3.12 seconds. Thirteen boundary reviews recover no
required target. Only 17 new requests completed the missing work; original receipts
and the budget stop remain preserved, with no completed request resent. This is
known-case regression evidence, not a daily promotion. Daily 0.3.73 is unchanged.

The [expanded new-task check](../../docs/backpack-adaptive-expanded-2026-10-15.md)
finds regressions: the unchanged baseline passes 13/14 new requests and the
compact candidate passes 11/14. Candidate data-quality and meeting tasks omit
their expected capability; both arms omit the research-summary target. The
compact candidate is **not eligible for daily promotion**, despite lower token
usage. Three selected public Skill artifacts were exercised locally, with an
API example-argument correction; this does not test installed acquisition,
plugin setup or MCP invocation. Run `expanded_experiment.py freeze/run` with
the same arguments as the cost runner below, using its frozen cost bundle as
the source. Inputs and selector bytes are frozen; semantic failures remain in
the denominator without tuning or retries. See `expanded_cases.json`.

The [adaptive cost follow-up](../../docs/backpack-adaptive-cost-2026-10-15.md)
compares the original adaptive arm with compact shared scope text and aggregate
candidate stopping. Two fresh repetitions complete all eight original requests,
including both negative controls: 16/16 omission-safe passes for each arm.
Average measured tokens fall 44.84% overall (40.86% on positive requests), while
elapsed selection time falls 11.70% overall (6.42% on positives). This is a
combined, familiar-case selector experiment, not a daily runtime promotion or
an end-to-end capability execution test. Original source and evidence remain.

```sh
python3 benchmarks/directory-depth/adaptive_cost_experiment.py freeze \
  --source /path/to/adaptive/bundle --output /path/to/cost/bundle \
  --executable /path/to/configured/jev
python3 benchmarks/directory-depth/adaptive_cost_experiment.py run \
  --source /path/to/cost/bundle --output /path/to/cost/live
```

The cost plan freezes two repetitions, alternating arm order, controls first,
160 calls / 260,000 known tokens / 300 seconds, and a candidate acceptance gate
after each result. A stopped run cannot be resumed under another output name.
The analysis entry `analyze_adaptive_cost.py` consumes bundle/live directories
and the evidence parent's `protected-before.json`, and writes one sanitized
result with `--output`. Keep raw payloads and protection paths outside Git.

The later [adaptive pilot](../../docs/backpack-adaptive-directory-2026-10-15.md)
adds operation-based source subdivisions and per-branch stopping. It selected
all six measured positive targets without observed omissions; the five common
cases used fewer calls and less time than full-depth traversal. Token savings
are not established after checking directory-score variation. Negative controls
remain unrun because the fixed budget stopped the experiment. This does not
promote a daily runtime or replace the earlier failed evidence below.

Adaptive entry points (use the original frozen bundle as `--source` for freeze):

```sh
python3 benchmarks/directory-depth/adaptive_experiment.py freeze \
  --source /path/to/original/frozen/bundle --output /path/to/adaptive/bundle
python3 benchmarks/directory-depth/adaptive_experiment.py run \
  --source /path/to/adaptive/bundle --output /path/to/adaptive/live
```

The parent directory must already exist. Freeze binds source metadata, the
operation groups, requests, thresholds, budget and runner bytes. Two pilot
adaptive cases must retain all required targets and select correctly before
remaining cases start. A stopped run is not resumed or replayed under a new
directory name. The analysis helper also checks an owner-supplied
`protected-before.json` hash manifest in the evidence parent; it never reads
configuration values into the exported report. Raw evidence stays local.

This is an isolated selector experiment, not a Backpack runtime or lifecycle
change. It never installs or executes capabilities. The 2026-10-15 pilot found
**no eligible winner**: broad summaries and a permissive early retention gate
left too many candidates, so the budget stopped the run before final selection.
See [the report](../../docs/backpack-directory-depth-2026-10-15.md).

## Controlled comparison

- Frozen 376-capability public snapshot of `alirezarezvani/claude-skills`, commit
  `19392f7a08264ed00486a251f5b2098321771f94`. Original descriptions and order stay
  unchanged. The snapshot and original/raw equality are checked before calls.
- The supplied source-domain taxonomy is a structural baseline. It is **not**
  an execution of the installed daily Backpack selector.
- Balanced TF-IDF trees use only catalog metadata, never test requests or gold.
  Node cards list 12 centroid terms and every represented source-domain label.
  This is a cheap lexical construction, not semantic embeddings or RAPTOR.
- Height-6 trees are identical for 2/3/4/6 directory steps. They disclose levels
  `[3,6]`, `[2,4,6]`, `[2,3,5,6]`, or `[1,2,3,4,5,6]`. A separate height-4 arm
  discloses `[2,4]` and changes the ideal final list from 5–6 to 23–24 items.
- All arms use early Noul retention `>= 0.1` and final Choice confidence `>= 0.7`.
  The early value proved too permissive in this pilot; it is not a recommended
  default. Raising it on stored scores is diagnostic only, not live validation.
- Multiple branches are allowed. Nothing is silently truncated. More than 192
  cards or 96 final candidates produces an explicit unavailable result. No full
  catalog fallback, retry, or provider switch.
- Eight fixed requests: two Chinese, two synonym, two mixed-language, two
  negative controls. Gold IDs never enter model state/specs. Pending requirements
  are scored separately from the current-first final answer.
- One attempt per stage; arms rotate by case. Caps: 200 calls, 900 seconds, and
  300,000 **known** tokens checked before each call (one response can exceed the
  token cap). Transport, malformed result, or budget stop ends the pilot.

## Commands

Use the previously frozen public input folder containing `CATALOG.json`,
`CATALOG-RAW.json`, `QUESTION.json`, `PUBLIC-CATALOG-PROFILE.json` and
`PUBLIC-SOURCE.zip`. No credentials or private catalog files belong there.
The source zip hash is pinned in `prepare.py`; this runner does not fetch a new
market version. Use a new evidence destination only for an independently
authorized experiment; never rename an interrupted run to replay it.

```sh
python3 benchmarks/directory-depth/prepare.py \
  --source /path/to/frozen-public-input \
  --output /path/to/experiment/bundle \
  --executable /path/to/configured/jev
python3 -m unittest discover -s tests -p 'test_directory_depth_experiment.py'
python3 benchmarks/directory-depth/experiment.py \
  --bundle /path/to/experiment/bundle --output /path/to/experiment/live
python3 benchmarks/directory-depth/analyze.py \
  --bundle /path/to/experiment/bundle --live /path/to/experiment/live \
  --output /path/to/experiment/result.json
```

The parent evidence directory must already exist. Inputs, tree identities and
runner bytes are frozen before live calls. Pending receipts are written and
synced before dispatch; done/error receipts retain outcome and measured usage.
An existing output directory cannot be reused. Unknown outcomes are never
replayed. Only sanitized aggregates and public fixtures are committed here.

The oracle structure sweep is an ideal path calculation, not measured model
accuracy or latency. Stored-score threshold replay may differ from a fresh
smaller-batch model call. No mixed-language, negative-control, pending-action or
final-choice claim is supported by this budget-stopped pilot. Do not tune on
these requests and then describe them as unseen validation.
