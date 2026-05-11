<p align="center"><sub>FOR RUNTIME MAINTAINERS, AGENT TOOLING AUTHORS, AND CONTEXT BUDGET NERDS</sub></p>

<h1 align="center">CatMaster Backpack</h1>

<p align="center"><strong>Lazy capability surface for agent runtimes.</strong></p>

<p align="center">
  Start with <code>tool_backpack</code> / <code>skill_backpack</code>, then expose only the tool or skill the model explicitly selects.
</p>

<p align="center">
  <img alt="Status: Hermes prototype" src="https://img.shields.io/badge/status-Hermes%20prototype-1f6feb" />
  <img alt="Backpack System: v0" src="https://img.shields.io/badge/backpack-v0-0969da" />
  <img alt="Benchmark: 68.4% fewer tokens" src="https://img.shields.io/badge/benchmark-68.4%25%20fewer%20tokens-238636" />
  <img alt="Surface: 97.4% fewer schema chars" src="https://img.shields.io/badge/surface-97.4%25%20fewer%20schema%20chars-8957e5" />
</p>

<p align="center">
  <a href="#signal-board">Signal Board</a> | <a href="#quick-demo">Quick Demo</a> | <a href="#public-install">Install</a> | <a href="docs/outreach.md">Share</a>
</p>

CatMaster Backpack reduces visible agent capability surface area by exposing compact gateways first, then letting the model explicitly select the tool or skill it needs.

Current published runtime version:

```text
Backpack System: v0
```

<table>
  <tr>
    <th align="left">Metric</th>
    <th align="left">Measured Signal</th>
  </tr>
  <tr>
    <td><strong>Token budget</strong></td>
    <td><strong>68.4% fewer total tokens</strong><br />standard hm Backpack vs hm-full on the 12-task fixture</td>
  </tr>
  <tr>
    <td><strong>Prompt pressure</strong></td>
    <td><strong>68.8% fewer prompt tokens</strong><br />less context spent describing capabilities up front</td>
  </tr>
  <tr>
    <td><strong>Visible surface</strong></td>
    <td><strong>92.0% fewer initially visible tools</strong><br />2 Backpack gateways vs 25 full direct tools</td>
  </tr>
  <tr>
    <td><strong>Schema surface</strong></td>
    <td><strong>97.4% fewer initial tool-schema chars</strong><br />655 chars vs 25,514 chars in the schema surface check</td>
  </tr>
</table>

<p align="center"><sup>Measured on standard hm configuration against a full direct-tools tool surface. See benchmark records for methodology and tradeoffs.</sup></p>

It contains two coordinated backpacks:

- **Tool Backpack** - manages tool discovery and activation while keeping most tools hidden until selected.
- **Skill Backpack** - manages skill discovery and loading through compact skill indexes, keeping child skills hidden until selected.

The current validated adapter is the Hermes `Cat Master Toolkit` implementation.

## Signal Board

| Signal | Standard hm Backpack | Standard hm full direct tools |
| --- | ---: | ---: |
| Correct answers | 12/12 | 12/12 |
| Total tokens | 62,303 | 197,261 |
| Prompt tokens | 61,313 | 196,667 |
| Initial visible tools | 2 | 25 |
| Avg total time | 8,407.90 ms | 5,698.68 ms |

```text
user request
  -> optional advisor hints
  -> tool_backpack / skill_backpack
  -> selected tool / selected skill
  -> task execution
```

## Latest Local Experiment Conclusion

The latest standard Hermes benchmark shows both context reduction and real token savings. On the deterministic 12-task fixture, standard `hm` Backpack matched `hm-full` accuracy at 12/12 while using 62,303 total tokens versus 197,261 total tokens, or **68.4% fewer total tokens**.

The tradeoff is latency: Backpack made 50.0% more API calls and was 47.5% slower on this fixture because it adds an explicit gateway-selection round.

## Why Share It

Agent tools are eating the context window. CatMaster Backpack demonstrates a concrete alternative: keep the initial capability surface small, let the model explicitly select the needed tool or skill, and expose only that selected capability.

Current standard Hermes evidence:

```text
12/12 correct answers on both arms
68.4% fewer total tokens
68.8% fewer prompt tokens
92.0% fewer initially visible tools
97.4% fewer initial tool-schema chars
Tradeoff: 50.0% more API calls and 47.5% slower average total time
```

This is useful for runtime maintainers exploring lazy capability surfaces, plugin hooks, or MCP-style adapters for large tool and skill catalogs.

## Use It When

- tool catalogs are crowding the prompt before the agent knows what it needs.
- skill catalogs are useful, but too large to inject into every turn.
- the host runtime can hide and reveal native tools dynamically.
- you want explicit model selection rather than a semantic router choosing tools silently.

## Tradeoff

The explicit gateway-selection round buys a smaller starting context at the cost of more calls. In the current standard Hermes benchmark, Backpack made 50.0% more API calls and was 47.5% slower on average while using 68.4% fewer total tokens.

## Why It Exists

Large agent runtimes often expose too many tools and skills at once. That increases prompt size, makes tool choice noisier, and can leak implementation details into every turn.

CatMaster Backpack keeps the initial surface small:

```text
visible first:   tool_backpack, skill_backpack
selected later:  read_file, search_files, terminal, debugging skill, TDD skill, ...
```

The gateway does not semantically route requests. It exposes compact candidates or indexes, the model chooses explicitly, and the host exposes only the selected capability.

## What It Saves

CatMaster Backpack reduces visible tool and skill surface area, so the model spends less context describing capabilities it will not use. The intended savings are:

```text
less startup/tool-schema context
less repeated skill text in global prompts
less noisy capability selection
more room for task-specific context
```

Current Hermes surface measurement, 2026-05-11:

| Runtime surface | Visible tools | Tool schema chars | Rough schema tokens |
| --- | ---: | ---: | ---: |
| Backpack gateways | 2 | 655 | 164 |
| Direct file tools | 4 | 4,979 | 1,245 |
| Direct file/terminal/web | 6 | 10,896 | 2,724 |
| Direct common tools | 18 | 25,514 | 6,378 |

Against the direct common-tools surface, Backpack reduced initial tool schema text by about **97.4%** in this measurement. See `benchmarks/results/current-hermes-surface-2026-05-11.md`.

Fresh standard Hermes benchmark, 2026-05-11:

| Runtime surface | Correct answers | Total tokens | Avg total time |
| --- | ---: | ---: | ---: |
| Standard hm Backpack | 12/12 | 62,303 | 8,407.90 ms |
| Standard hm full direct tools | 12/12 | 197,261 | 5,698.68 ms |

This live run validates gateway behavior and token savings: Backpack used **68.4% fewer total tokens** and **68.8% fewer prompt tokens** on this fixture. The tradeoff is latency: Backpack made 50.0% more API calls and was 47.5% slower on average because it adds the explicit gateway selection round. See `benchmarks/results/current-hermes-real-benchmark-2026-05-11.md`.

## Quick Demo

Blind local Hermes tests did not mention `Backpack`, `gateway`, `tool`, or `select` in the user prompt.

```text
Prompt:
  Under /tmp/opencode/hm-blind-search-test/main,
  find the file containing HM_MAIN_SEARCH_SENTINEL_20260510_E.

Observed session path:
  tool_backpack -> search_files/read_file

Evidence:
  tool_backpack {"request":"select search_files"}
  search_files found target-main.txt
  no "Tool Backpack index:" full catalog injection
```

See `docs/demo.md` for the longer transcript-style record.

## Community Sharing

Use `docs/outreach.md` for maintainer email, GitHub Discussion, and community post templates. The templates intentionally describe Hermes as the working runtime prototype and describe OpenCode, Claude Code, and Codex-style runtimes as adapter targets unless their host APIs support dynamic tool visibility.

## Supported Hosts

| Host | Status | Notes |
| --- | --- | --- |
| Hermes Agent | Working runtime integration prototype | Supports `tool_backpack`, `skill_backpack`, advisor hints, and selected-tool exposure. |
| OpenCode | Portable skill/protocol package | Dynamic native tool hiding depends on host hooks. |
| Claude Code | Portable skill/protocol package | Skill bundle is portable; dynamic tool visibility depends on host APIs. |
| Codex-style runtimes | Proposal target | Needs a stable extension or tool-surface API. |

## Architecture

```text
                    user turn
                       |
                       v
              backpack_advisor
              optional compact hints
                       |
                       v
       +---------------+---------------+
       |                               |
       v                               v
 tool_backpack                    skill_backpack
 select read_file                 index / select debugging
       |                               |
       v                               v
 selected tool schema             selected SKILL.md content
       |                               |
       +---------------+---------------+
                       |
                       v
                  agent loop
```

## Limitations

Hermes full runtime integration is not a pure plugin. It requires host runtime wiring for lazy tool visibility, selected-tool exposure, advisor hints, TUI guards, and skill sync behavior.

OpenCode and Claude Code currently receive the portable protocol and skill packaging. They should not be advertised as Hermes-equivalent lazy native tool runtimes until those hosts expose stable hooks.

## Contents

- `core/` - shared lazy-surface protocol, capability catalog, and description style rules.
- `adapters/` - host-specific integration notes for Hermes, OpenCode, and Claude Code.
- `adapters/hermes/tool-repo-snapshot/` - Tool Backpack Hermes `tool_backpack` source snapshot and dependencies.
- `adapters/hermes/skill_backpack/` - Skill Backpack Hermes `skill_backpack` gateway source.
- `skills/backpack-manager/` - Backpack management skill for Tool Backpack, Skill Backpack, and external tool changes.
- `skills/skill-backpack/` - Skill Backpack parent skill and management CLI.
- `fixtures/` - deterministic Skill Backpack tree fixtures.
- `benchmarks/` - deterministic fixtures, runners, and current benchmark summaries.
- `docs/` - Backpack runtime notes and demo records.
- `src/catmaster_backpack/` - public package and installer CLI.

## Public Install

Clone the repository, then install the CLI from the checkout:

```bash
git clone https://github.com/kdoooh000h/catmaster-backpack.git
cd catmaster-backpack
python -m pip install -e .
```

Install the portable Skill Backpack parent skill into a project:

```bash
catmaster-backpack install-skill-plugin --agent opencode --project-root /path/to/project --source /path/to/project/.opencode/skills
catmaster-backpack install-skill-plugin --agent claude-code --project-root /path/to/project --source /path/to/project/.claude/skills
```

Preview without writing files:

```bash
catmaster-backpack install-skill-plugin --agent opencode --project-root /path/to/project --source /path/to/skills --dry-run
```

Hermes full runtime integration is not a pure plugin. It requires host runtime wiring for lazy tool visibility, selected-tool exposure, advisor hints, TUI guards, and skill sync behavior. Inspect the required runtime files before patching a Hermes checkout:

```bash
catmaster-backpack hermes-plan --hermes-agent-root /path/to/hermes-agent --hermes-home ~/.hermes
```

## Current Strategy

Current version labels:

```text
Backpack System: v0
```

Tool Backpack and Skill Backpack both use compact candidate hints or indexes, let the model choose, then load or expose exactly the selected target. Do not semantically route inside the gateway. The current Hermes path keeps `tool_backpack` and `skill_backpack` visible, injects compact candidate hints when useful, and accepts only explicit selection calls through the gateways.

Current Tool Backpack target protocol:

```text
prompt -> optional Tool Backpack candidate hints
tool_backpack("select <id|tool_name>[,<id|tool_name>...]") -> selected tool name(s)
execute selected tool(s) directly
```

Current Skill Backpack target protocol:

```text
skill_backpack("index") -> numbered skill index
skill_backpack("select <number|skill-name>") -> selected SKILL.md content
execute loaded skill guidance
```

`skill_backpack` is now the active Hermes Skill Backpack runtime gateway. Standard Hermes surfaces expose `tool_backpack` and `skill_backpack`; `hm-full` remains the full direct-tools control.

Runtime update record: `docs/hermes-backpack-runtime-update-2026-05-01.md`.

## Current Validated Result

The current published measurements are the Hermes surface result in `benchmarks/results/current-hermes-surface-2026-05-11.md` and the fresh real benchmark in `benchmarks/results/current-hermes-real-benchmark-2026-05-11.md`. The fresh run showed 12/12 correct Backpack answers with explicit `tool_backpack` selection on every task.

## Adapter Roadmap

CatMaster Backpack is currently validated on Hermes Agent.

| Host | Current status | Next step |
| --- | --- | --- |
| Hermes Agent | Working runtime integration prototype | Continue hardening Tool Backpack and Skill Backpack runtime behavior. |
| OpenCode | Portable protocol and skill package only | Add native lazy tool-surface support only if OpenCode exposes stable tool hooks. |
| Claude Code | Portable protocol and skill package only | Keep Skill Backpack portable; add dynamic tool visibility only if host APIs support it. |
| OpenClaw | Not implemented | Investigate host extension and tool APIs before claiming support. |
| Codex-style runtimes | Proposal target | Needs a stable extension or tool-surface API. |

Do not treat non-Hermes hosts as Hermes-equivalent lazy native tool runtimes yet. The portable assets are useful as protocol, skill-tree, and adapter starting points; runtime-level dynamic tool hiding still depends on each host.

## Security Boundary

CatMaster Backpack does not execute installs or uninstalls by default. Tool changes use `backpack-manager`, require official-source verification, and ask for confirmation. Skill changes go through managed skill-tree commands and should run verification before use. Explicit list/index requests can return compact catalogs without exposing every tool or skill at startup.
