# Public directory depth/width pilot

The [same-14 description repair and boundary-review experiment](../../docs/backpack-adaptive-repair-2026-10-15.md)
recovers the three known omission targets but costs substantially more. It stopped
at its frozen token budget with 12 complete three-arm cases, one incomplete case
and one unrun case. It is not a 14/14 result or a daily promotion. All completed
receipts and the budget stop are preserved; continuation requires additional user
budget and never resends a completed request. Daily 0.3.73 is unchanged.

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
