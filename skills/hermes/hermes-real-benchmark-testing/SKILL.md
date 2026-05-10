---
name: hermes-real-benchmark-testing
description: Use when optimizing Hermes Tool Backpack, Skill Backpack, tool_backpack, skill_backpack, lazy tool surface, tool routing, search_files output, hm/hm-full production smoke behavior, or benchmark accuracy behavior
---

# Hermes Real Benchmark Testing

## Overview

Hermes Tool Backpack optimizations need a fresh real Hermes LLM benchmark before completion claims. Unit tests prove routing contracts; only the real benchmark proves the model still chooses tools and answers correctly.

Core principle: historical JSONL is comparison evidence only, not fresh verification.

## When To Use

Use this for changes touching:

- Hermes `tool_backpack` or legacy `tool_repo`
- Hermes `skill_backpack`, Skill Backpack index/select behavior, or hidden skill loading
- lazy tool surface, visible tool filtering, inline index, `select <tool_name>`, numbered fallback ids
- `search_files`, `read_file`, answer formatting, `FILE=<filename>` behavior
- production `hm` vs `hm-full` smoke/comparison behavior
- benchmark prompts, fixture data, accuracy scoring, prompt/token optimization

Do not use for docs-only edits that do not claim runtime or benchmark behavior.

## Required Gate

Do not claim Hermes optimization is complete until you have either:

- run a fresh real Hermes LLM benchmark against the current code and read the new JSONL results, or
- explicitly report that real benchmark verification was not run and the optimization remains end-to-end unverified.

Passing `py_compile`, `unittest`, or `pytest` is required but not enough for Hermes optimization claims.

## Comparison Group Selection

Before every benchmark, inspect the experiment project for comparison groups under `/home/k/cccx/tool/experiments`. Use experiment Hermes homes by default, not the hmk role home.

Known groups:

| Group | Hermes home | Use when |
| --- | --- | --- |
| Tool Backpack file benchmark | `/home/k/cccx/tool/experiments/hermes-test/custom-tools/.hermes` | testing lazy `tool_backpack` against file-search fixtures |
| Full tools baseline | `/home/k/cccx/tool/experiments/hermes-test/full-tools/.hermes` | comparing against all visible tools |
| Skill Backpack surface | `/home/k/cccx/tool/experiments/hermes-skill-ab/skill-backpack/.hermes` | testing the active Skill Backpack gateway |
| Visible skills control | `/home/k/cccx/tool/experiments/hermes-skill-ab/control-visible-skills/.hermes` | testing visible-skill control behavior |

Workflow:

- choose existing comparison groups that match the user request.
- If no existing group matches, create the missing comparison group by copying the nearest `.hermes` shape, syncing provider config with `benchmarks/sync-hmk-hermes-config.py`, and setting only the intended toolsets/skills difference.
- validate each new Hermes home with a real chat response before using it in a benchmark.
- ask before deleting comparison groups. Do not delete experiment groups silently.
- Do not run benchmark comparisons against mismatched groups. If the requested comparison group is absent or ambiguous, stop and ask whether to create it.

Validation command for any new or changed Hermes home:

```bash
HERMES_HOME=<experiment/.hermes> HERMES_ACCEPT_HOOKS=1 \
PYTHONPATH=/home/k/cccx/hermes/repos/hermes-agent \
/home/k/cccx/hermes/repos/hermes-agent/.venv/bin/hermes \
chat -Q -q "Reply exactly HM_OK_<group>" --source tool
```

## Production hm Smoke

Use this when the user asks whether the real user surface still works after Backpack changes. Prefer the real wrapper when a TTY/tmux check is required:

```bash
/home/k/.local/bin/hm
```

For non-interactive smoke, use the wrapper target while preserving the same home:

```bash
HERMES_HOME=/home/k/.hermes HERMES_ACCEPT_HOOKS=1 \
PYTHONPATH=/home/k/cccx/hermes/repos/hermes-agent \
/home/k/.local/bin/hermes-main -z "Reply exactly HM_BACKPACK_SMOKE_OK"
```

Tool Backpack smoke must require a gateway selection and a final marker:

```text
Use local repository tools. First call tool_backpack({"request":"select <id|tool_name>"}) for the needed tool. Reply exactly TOOL_BACKPACK_SMOKE_OK.
```

Skill Backpack smoke must require a selected skill and a final marker:

```text
Load the named skill by calling skill_backpack({"request":"select <skill-name>"}). Reply exactly SKILL_BACKPACK_SMOKE_OK after using it.
```

Do not accept final text alone. Inspect the session JSON and verify the expected tool calls happened: `tool_backpack select` for Tool Backpack smoke, `skill_backpack select` for Skill Backpack smoke, followed by the task-relevant tool or skill use.

## hm vs hm-full Comparison

Use this when comparing the production Backpack surface against a full direct-tools baseline.

| Arm | Command/home | Required signal |
| --- | --- | --- |
| `hm` | `/home/k/.local/bin/hm` or `/home/k/.local/bin/hermes-main` with `HERMES_HOME=/home/k/.hermes` | hm should start Backpack-only; initial visible tools are `tool_backpack` and `skill_backpack` |
| `hm-full` | `/home/k/cccx/tool/experiments/hermes-test/full-hm/bin/hm-full` | hm-full should not use Backpack gateways; it should expose full direct tools |

For each arm, capture and report:

- session path
- visible tool count and visible tool names
- tool calls from session JSON
- final marker
- rough schema tokens and rough message tokens when available

Do not compare against stale sessions as proof. Historical sessions are context only; run fresh smoke or report that real production verification was not run.

## Canonical Custom-Tools Command

Run from the accuracy fixture so file search tasks inspect deterministic data:

```bash
cd /home/k/cccx/tool/catmaster-backpack/benchmarks/accuracy-fixture && \
HERMES_HOME=/home/k/cccx/tool/experiments/hermes-test/custom-tools/.hermes \
PYTHONPATH=/home/k/cccx/hermes/repos/hermes-agent \
/home/k/cccx/tool/experiments/hermes-test/full-tools/.venv/bin/python \
/home/k/cccx/tool/catmaster-backpack/benchmarks/run-simple-tool-round.py \
--env custom-tools \
--output /home/k/cccx/tool/experiments/hermes-test/tool-backpack-real-llm-$(date +%Y%m%d%H%M%S).jsonl
```

This uses real LLM calls through Hermes `AIAgent.run_conversation` with `model="gemma-26b"` and `provider="custom"`.
The runner fixes the custom-tools surface to `file`, `terminal`, `web`, `no_mcp`, and `tool_backpack`; the experiment `HERMES_HOME` supplies provider credentials and model config.

## Optional Full-Tools Comparison

Use this only when comparing against full visible tools:

```bash
cd /home/k/cccx/tool/catmaster-backpack/benchmarks/accuracy-fixture && \
HERMES_HOME=/home/k/cccx/tool/experiments/hermes-test/full-tools/.hermes \
PYTHONPATH=/home/k/cccx/hermes/repos/hermes-agent \
/home/k/cccx/tool/experiments/hermes-test/full-tools/.venv/bin/python \
/home/k/cccx/tool/catmaster-backpack/benchmarks/run-simple-tool-round.py \
--env full-tools \
--output /home/k/cccx/tool/experiments/hermes-test/tool-backpack-full-tools-$(date +%Y%m%d%H%M%S).jsonl
```

## Result Review

Open the fresh JSONL and check every row:

| Field | Required signal |
| --- | --- |
| `answer_correct` | `true` for each fixture task |
| `tool_calls` | starts with `tool_backpack` for custom-tools runs |
| `used_repo_file_tool` | `true` |
| `used_irrelevant_tool` | `false` |
| `initial_visible_tool_count` | `1` for Tool Backpack lazy runs |
| `initial_visible_tools` | includes only `tool_backpack` for lazy runs |
| `prompt_tokens`, `completion_tokens`, `total_tokens` | record totals for comparison |
| `total_ms` | record average runtime |

If any row fails, use systematic debugging before changing code. Do not average away a failed fixture.

## Reporting Format

Report fresh benchmark evidence separately from historical comparison:

```text
Fresh real Hermes LLM benchmark: <correct>/<total>
Output: <jsonl path>
API calls: <sum>
Prompt tokens: <sum>
Completion tokens: <sum>
Total tokens: <sum>
Avg total_ms: <avg seconds>
Initial visible tools: <count and names>
```

Then compare old JSONL only as context.

## Common Rationalizations

| Excuse | Reality |
| --- | --- |
| "Unit tests cover the routing." | Unit tests do not prove model tool choice or exact final answers. |
| "A previous JSONL already showed 3/3." | historical JSONL is comparison evidence only. Current code needs a fresh run. |
| "Only prompt/docs changed." | If you claim benchmark or runtime behavior, run the benchmark or say unverified. |
| "Real LLM calls are slow." | Then report the benchmark was not run; do not claim completion. |

## Red Flags

- Saying `3/3` without a fresh output path.
- Using old benchmark results as proof for current code.
- Reporting `pytest`/`unittest` as sufficient for Hermes optimization.
- Not checking `tool_calls` and `initial_visible_tool_count`.
- Ignoring exact output format regressions such as `FILE=<filename>`.

These mean: stop and run the fresh real Hermes LLM benchmark or state the gap.
