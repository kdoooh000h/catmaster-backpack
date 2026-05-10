# Benchmarks

This folder stores deterministic Tool Backpack validation assets.

## Fixture

`accuracy-fixture/` contains two local text files used by repository/file search tasks.

Expected task outputs:

```text
SENTINEL=violet-otter-731
FILE=beta.txt
NOT_FOUND
```

## Final Hermes V1 Result

See `results/cat-master-toolkit-v1-final.md`.

The raw local run was recorded in the source Hermes experiment folder as `tool-repo-vs-full-description-trim-2026-04-25.jsonl`. This project keeps the secret-free summary rather than local runtime session homes.

## Hermes Runtime Smoke Tests

The V2 installed-tool listing and uninstall-routing smoke test is recorded in `docs/cat-master-toolkit-v2-tool-indexer.md`.

## Skill Backpack Result

See `results/skill-backpack-comparison-2026-04-28.md` for the current Skill Backpack gateway comparison.

## Hermes Backpack Runtime Update

See `../docs/hermes-backpack-runtime-update-2026-05-01.md` for the current production Backpack surface decisions, official-skill sync behavior, and real `hm`/`hm-full` verification workflow.
