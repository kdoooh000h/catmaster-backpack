# Current Hermes Real Benchmark - 2026-05-11

## Purpose

Measure standard `hm` Backpack behavior against a standard-config full direct-tools baseline using real Hermes `AIAgent.run_conversation` calls on the deterministic accuracy fixture.

This run uses `HERMES_HOME=/home/k/.hermes`, the same model/provider configuration as `/home/k/.local/bin/hermes-main`. The full direct-tools arm overrides only the enabled toolsets so it exposes direct tools instead of Backpack gateways.

## Commands

Backpack arm:

```bash
cd /home/k/cccx/tool/catmaster-backpack/benchmarks/accuracy-fixture
HERMES_HOME=/home/k/.hermes \
PYTHONPATH=/home/k/cccx/hermes/repos/hermes-agent \
/home/k/cccx/hermes/repos/hermes-agent/.venv/bin/python \
/home/k/cccx/tool/catmaster-backpack/benchmarks/run-simple-tool-round.py \
--env hm-backpack \
--output /home/k/cccx/tool/experiments/hermes-advisor-ab/results/hm-backpack-real-llm-20260511.jsonl
```

Full direct-tools arm:

```bash
cd /home/k/cccx/tool/catmaster-backpack/benchmarks/accuracy-fixture
HERMES_HOME=/home/k/.hermes \
PYTHONPATH=/home/k/cccx/hermes/repos/hermes-agent \
/home/k/cccx/hermes/repos/hermes-agent/.venv/bin/python \
/home/k/cccx/tool/catmaster-backpack/benchmarks/run-simple-tool-round.py \
--env hm-full \
--output /home/k/cccx/tool/experiments/hermes-advisor-ab/results/hm-full-real-llm-20260511.jsonl
```

## Result

| Metric | Standard hm Backpack | Standard hm full direct tools |
| --- | ---: | ---: |
| Correct answers | 12/12 | 12/12 |
| Initial visible tools | 2 | 25 |
| Initial visible tool names | `skill_backpack`, `tool_backpack` | 25 direct tools |
| API calls | 36 | 24 |
| Prompt tokens | 61,313 | 196,667 |
| Completion tokens | 990 | 594 |
| Total tokens | 62,303 | 197,261 |
| Avg init time | 39.57 ms | 38.73 ms |
| Avg total time | 8,407.90 ms | 5,698.68 ms |
| Irrelevant tool use | 0/12 | 0/12 |

## Interpretation

Standard hm Backpack preserved the intended lazy surface and selected tools explicitly on every task:

```text
initial_visible_tools: ["skill_backpack", "tool_backpack"]
first tool call: tool_backpack on 12/12 tasks
task file tool used after selection: 12/12 tasks
```

Token/context results:

```text
Backpack total tokens: 62,303
Full direct-tools total tokens: 197,261
Backpack used 68.4% fewer total tokens.

Backpack prompt tokens: 61,313
Full direct-tools prompt tokens: 196,667
Backpack used 68.8% fewer prompt tokens.
```

Latency/call tradeoff:

```text
Backpack API calls: 36
Full direct-tools API calls: 24
Backpack made 50.0% more API calls.

Backpack avg total time: 8,407.90 ms
Full direct-tools avg total time: 5,698.68 ms
Backpack was 47.5% slower on average.
```

Initial tool surface:

```text
Backpack initial visible tools: 2
Full direct-tools initial visible tools: 25
92.0% fewer initially visible tools
```

For serialized schema size, use `current-hermes-surface-2026-05-11.md`, which measured 655 Backpack tool-schema chars versus 25,514 direct common-tool schema chars, or 97.4% fewer initial tool-schema chars.

## Raw Artifacts

Raw JSONL files are stored outside this repository:

```text
/home/k/cccx/tool/experiments/hermes-advisor-ab/results/hm-backpack-real-llm-20260511.jsonl
/home/k/cccx/tool/experiments/hermes-advisor-ab/results/hm-full-real-llm-20260511.jsonl
```
