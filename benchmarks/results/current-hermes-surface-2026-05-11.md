# Current Hermes Surface Measurement - 2026-05-11

## Purpose

Measure the current Hermes Backpack runtime surface separately from the older 2026-04-28 Skill Backpack token comparison. This result is the latest measurement in this repository, but it is a schema/context-surface measurement rather than a completed model-token benchmark.

## Surface Measurement

Measured by instantiating current Hermes `AIAgent` with selected toolset groups and serializing the visible tool schema.

| Runtime surface | Toolsets | Visible tools | Tool schema chars | Rough schema tokens, chars/4 |
| --- | --- | ---: | ---: | ---: |
| Backpack gateways | `skill_backpack`, `tool_backpack` | 2 | 655 | 164 |
| Direct file tools | `file` | 4 | 4,979 | 1,245 |
| Direct file/terminal/web | `file`, `terminal`, `web` | 6 | 10,896 | 2,724 |
| Direct common tools | `file`, `terminal`, `web`, `browser`, `code_execution`, `delegation` | 18 | 25,514 | 6,378 |

Reduction against direct common tools:

```text
(25,514 - 655) / 25,514 = 97.4% fewer initial tool schema chars
```

Reduction against direct file/terminal/web:

```text
(10,896 - 655) / 10,896 = 94.0% fewer initial tool schema chars
```

Reduction against direct file tools only:

```text
(4,979 - 655) / 4,979 = 86.8% fewer initial tool schema chars
```

## Live Blind Smoke

Current wrapper-based live checks passed through `/home/k/.local/bin/hermes-main -z`.

Read task:

```text
Prompt omitted Backpack/gateway/tool/select.
Output: CURRENT_READ_RESULT CURRENT_READ_SENTINEL_20260511_A
Session: /home/k/.hermes/sessions/session_20260511_052751_0f6ef2.json
Evidence: tool_backpack {"request":"select read_file"} -> read_file
No "Tool Backpack index:" found.
```

Search task:

```text
Prompt omitted Backpack/gateway/tool/select.
Output: CURRENT_SEARCH_RESULT target.txt
Session: /home/k/.hermes/sessions/session_20260511_052751_46f404.json
Evidence: tool_backpack {"request":"select search_files"} -> search_files
No "Tool Backpack index:" found.
```

## Token Benchmark Status

The latest direct `AIAgent` token benchmark attempt was not valid because raw `AIAgent` calls hit HTTP 403 from the Codex backend and recorded zero token usage. Wrapper-based `hermes-main -z` calls succeeded, but the saved session JSON did not include prompt/completion token usage fields.

Do not treat this file as a fresh total-token benchmark. Treat it as current evidence for:

```text
initial visible tool count
initial tool schema/context size
live gateway behavior
absence of full Tool Backpack index injection
```

The older total-token number remains historical evidence from `skill-backpack-comparison-2026-04-28.md`.
