# CatMaster Backpack

Lazy tool and skill gateway protocol for agent runtimes.

CatMaster Backpack reduces visible agent capability surface area by exposing compact gateways first, then letting the model explicitly select the tool or skill it needs.

```text
user request
  -> optional advisor hints
  -> tool_backpack / skill_backpack
  -> selected tool / selected skill
  -> task execution
```

It contains two coordinated backpacks:

- **Tool Backpack** - manages tool discovery and activation while keeping most tools hidden until selected.
- **Skill Backpack** - manages skill discovery and loading through compact skill indexes, keeping child skills hidden until selected.

The current validated adapter is the Hermes `Cat Master Toolkit` implementation.

## Latest Local Experiment Conclusion

The latest measured win is initial schema/context-surface reduction, not a fresh end-to-end total-token benchmark. Current Hermes showed 2 Backpack gateway tools and 655 tool-schema chars versus 18 direct common tools and 25,514 tool-schema chars, a 97.4% smaller initial tool-schema surface.

The raw AIAgent token benchmark hit HTTP 403 before it could produce comparable fresh token totals. The wrapper-based live blind checks passed for read and search prompts, and those sessions selected `read_file` and `search_files` through `tool_backpack` without full catalog injection.

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

Historical token benchmark on the same 8-task fixture:

| Runtime | Total tokens | Result |
| --- | ---: | --- |
| Old direct/visible skill runtime | 28,673 | 8-task baseline |
| `skill_backpack` gateway runtime | 13,602 | 8/8 correct selections |

That historical run showed about **52.6% fewer total tokens** on the small fixture, with about **62.7% fewer non-cache input tokens**. These numbers are not universal guarantees; savings depend on host runtime, model, tool count, skill count, cache behavior, and task mix. The practical goal is less context spent describing capabilities before the agent knows which ones it needs.

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
- `benchmarks/` - deterministic fixtures, runners, and benchmark summaries.
- `docs/` - Tool Backpack records and Skill Backpack benchmark notes.
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

Latest local Hermes comparison, 2026-04-28: 8 test skills, 8 deterministic skill-selection tasks, same model/config, context files and memory disabled.

| Metric | `skill_backpack` |
| --- | ---: |
| Correct skill selections | 8/8 |
| API calls | 24 |
| Avg API calls/task | 3.0 |
| Input tokens | 3,975 |
| Output tokens | 1,643 |
| Cache-read tokens | 7,984 |
| Total tokens | 13,602 |
| Avg tokens/task | 1,700 |

Result: the new skill gateway is the active strategy. The removed old runtime used 28,673 total tokens on the same fixture.

Detailed record: `benchmarks/results/skill-backpack-comparison-2026-04-28.md`.

## Package Direction

The package should split into a portable core plus tool, skill, and host adapter packages:

```text
catmaster-backpack-core
catmaster-backpack-tools
catmaster-backpack-skills
catmaster-backpack-hermes
catmaster-backpack-opencode
catmaster-backpack-claude-code
```

The Hermes adapter currently requires Hermes Agent runtime integration for lazy visible tools. OpenCode and Claude Code adapters should initially expose the protocol and skills, then add dynamic tool-surface control only if the host exposes stable hooks.

## Security Boundary

CatMaster Backpack does not execute installs or uninstalls by default. Tool changes use `backpack-manager`, require official-source verification, and ask for confirmation. Skill changes go through managed skill-tree commands and should run verification before use. Explicit list/index requests can return compact catalogs without exposing every tool or skill at startup.
