# Advisor A/B/C Real Benchmark - 2026-05-11

## Purpose

Compare three isolated Hermes experiment homes using real `AIAgent.run_conversation` calls on the deterministic accuracy fixture:

- `advisor-full-latest`: latest Hermes with the full direct-tool surface.
- `advisor-backpack-current`: latest Hermes with only `tool_backpack` and `skill_backpack` visible.
- `advisor-grouped-hints`: grouped deterministic Backpack candidate-hints experiment with only `tool_backpack` and `skill_backpack` visible.

The benchmark prompts were checked for prompt pollution. They do not include gateway names, tool names, skill names, `select`, or `index`.

## Auth Setup

The generated experiment homes use isolated configs and local symlinks to `/home/k/.hermes/auth.json` so they can reuse the existing `openai-codex` device-code login without copying the auth file.

Validation chats returned the expected markers before the benchmark:

```text
advisor-full-latest: HM_OK_full_latest
advisor-backpack-current: HM_OK_backpack_current
advisor-grouped-hints: HM_OK_grouped_hints
```

## Commands

Full direct-tools arm:

```bash
cd /home/k/cccx/tool/catmaster-backpack/benchmarks/accuracy-fixture
PYTHONPATH=/home/k/cccx/hermes/repos/hermes-agent \
/home/k/cccx/hermes/repos/hermes-agent/.venv/bin/python \
/home/k/cccx/tool/catmaster-backpack/benchmarks/run-simple-tool-round.py \
--env advisor-full-latest \
--output /home/k/cccx/tool/experiments/hermes-advisor-ab/results/advisor-full-latest-20260511T1224.jsonl
```

Current Backpack arm:

```bash
cd /home/k/cccx/tool/catmaster-backpack/benchmarks/accuracy-fixture
PYTHONPATH=/home/k/cccx/hermes/repos/hermes-agent \
/home/k/cccx/hermes/repos/hermes-agent/.venv/bin/python \
/home/k/cccx/tool/catmaster-backpack/benchmarks/run-simple-tool-round.py \
--env advisor-backpack-current \
--output /home/k/cccx/tool/experiments/hermes-advisor-ab/results/advisor-backpack-current-20260511T1224.jsonl
```

Grouped-hints Backpack arm:

```bash
cd /home/k/cccx/tool/catmaster-backpack/benchmarks/accuracy-fixture
PYTHONPATH=/home/k/cccx/hermes/repos/hermes-agent/.worktrees/grouped-backpack-hints \
/home/k/cccx/hermes/repos/hermes-agent/.worktrees/grouped-backpack-hints/.venv/bin/python \
/home/k/cccx/tool/catmaster-backpack/benchmarks/run-simple-tool-round.py \
--env advisor-grouped-hints \
--output /home/k/cccx/tool/experiments/hermes-advisor-ab/results/advisor-grouped-hints-20260511T1224.jsonl
```

## Result

| Metric | Full latest | Backpack current | Grouped hints |
| --- | ---: | ---: | ---: |
| Correct answers | 13/13 | 13/13 | 13/13 |
| Prompt-polluted tasks | 0/13 | 0/13 | 0/13 |
| Initial visible tools | 25 | 2 | 2 |
| Initial visible tool names | 25 direct tools | `skill_backpack`, `tool_backpack` | `skill_backpack`, `tool_backpack` |
| API calls | 25 | 33 | 33 |
| Prompt tokens | 204,879 | 55,111 | 53,367 |
| Completion tokens | 886 | 1,087 | 1,029 |
| Total tokens | 205,765 | 56,198 | 54,396 |
| Avg total time | 6.57 s | 11.37 s | 8.19 s |
| Gateway first | 0/13 | 10/13 | 10/13 |
| Explicit select seen | 0/13 | 10/13 | 10/13 |
| Direct tool before gateway | 0/13 | 0/13 | 0/13 |
| Irrelevant tool use | 1/13 | 1/13 | 0/13 |
| Correct capability selected | 9/13 | 9/13 | 10/13 |

## Interpretation

Accuracy and prompt pollution:

```text
All three arms answered 13/13 tasks correctly.
All three arms recorded 0 prompt-polluted tasks.
```

Token/context results:

```text
Full latest total tokens: 205,765
Backpack current total tokens: 56,198
Grouped hints total tokens: 54,396

Backpack current used 72.7% fewer total tokens than full latest.
Grouped hints used 73.6% fewer total tokens than full latest.
Grouped hints used 3.2% fewer total tokens than Backpack current.
```

Tool-surface results:

```text
Full latest initial visible tools: 25
Backpack current initial visible tools: 2
Grouped hints initial visible tools: 2
```

Selection signals:

```text
Backpack current selected a gateway first on 10/13 tasks and never used a direct tool before a gateway.
Grouped hints selected a gateway first on 10/13 tasks and never used a direct tool before a gateway.
```

The three workflow-style tasks were answerable from prompt semantics alone, so the model answered without selecting a skill or tool:

```text
debug-parser-refactor
safe-behavior-change
local-url-parser-fix
```

Those rows should not be treated as proof of skill-routing behavior. They show benchmark prompt weakness for workflow routing, not answer failure.

Irrelevant/capability anomalies:

```text
advisor-full-latest: read-example-domain used terminal instead of an expected web-read tool.
advisor-backpack-current: missing-marker selected terminal instead of an expected file-search tool.
advisor-grouped-hints: no irrelevant tool use recorded.
```

## Raw Artifacts

Raw JSONL files are stored outside this repository:

```text
/home/k/cccx/tool/experiments/hermes-advisor-ab/results/advisor-full-latest-20260511T1224.jsonl
/home/k/cccx/tool/experiments/hermes-advisor-ab/results/advisor-backpack-current-20260511T1224.jsonl
/home/k/cccx/tool/experiments/hermes-advisor-ab/results/advisor-grouped-hints-20260511T1224.jsonl
```
