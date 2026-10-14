# Benchmarks

This folder stores deterministic Tool Backpack validation assets.

The [market lifecycle retest](../docs/backpack-market-lifecycle-validation-2026-10-14.md)
uses the ordinary requests in `market-blind/` with native Agent execution. Its
failure-inclusive metrics and cumulative coverage are separate from deterministic
fixtures and from a single frozen-version A/B.

## Fixture

`accuracy-fixture/` contains two local text files used by repository/file search tasks.

Expected task outputs:

```text
SENTINEL=violet-otter-731
FILE=beta.txt
NOT_FOUND
```

## Current Hermes Surface Result

See `results/current-hermes-surface-2026-05-11.md`.

## Current Hermes Real Benchmark

See `results/current-hermes-real-benchmark-2026-05-11.md`.

## Hermes Backpack Runtime Update

See `../docs/hermes-backpack-runtime-update-2026-05-01.md` for the current production Backpack surface decisions, official-skill sync behavior, and real `hm`/`hm-full` verification workflow.
