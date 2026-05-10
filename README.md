# CatMaster Backpack

CatMaster Backpack is an open-source toolkit for reducing visible tool and skill surface area through compact indexes, explicit gateway selection, host adapters, and deterministic benchmarks.

It contains two coordinated backpacks:

- **Tool Backpack** - manages tool discovery and activation while keeping most tools hidden until selected.
- **Skill Backpack** - manages skill discovery and loading through compact skill indexes, keeping child skills hidden until selected.

The current validated adapter is the Hermes `Cat Master Toolkit` implementation.

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
