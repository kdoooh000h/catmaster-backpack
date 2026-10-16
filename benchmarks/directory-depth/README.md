# Public directory depth/width pilot

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
