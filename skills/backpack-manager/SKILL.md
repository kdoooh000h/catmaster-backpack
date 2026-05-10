---
name: backpack-manager
description: Use when managing Tool Backpack or Skill Backpack contents, changing hidden tool or skill availability, verifying backpack indexes, or updating hm/hmk backpack configuration.
---

# Backpack Manager

## Overview

Backpack runtime and backpack management are separate. Runtime tools expose compact selection gateways; management uses explicit CLI, config, and file operations with verification.

Core rule: inspect first, change deliberately, verify before claiming the backpack is usable.

## When To Use

Use this skill when the user asks to:

- inspect or change hidden tools behind `tool_backpack`
- install, upgrade, uninstall, or disable external tools, MCP servers, plugins, or tool capabilities
- inspect or change hidden skills behind `skill_backpack`
- install, update, remove, sync, or verify Skill Backpack modules
- change `hm` or `hmk` backpack configuration
- recover user-visible management while child tools and skills stay hidden by default

Do not use this for ordinary task execution. For ordinary execution, use `tool_backpack` or `skill_backpack` directly.

## Runtime Surface

Expected visible tools for main `hm`, `hmk`, and non-full profiles:

```text
tool_backpack
skill_backpack
```

Do not restore global child tool or child skill exposure just to manage the backpack. Keep management separate from runtime discovery. `hm-full` is the direct-tools control and should remain full direct tools unless explicitly requested.

## Tool Backpack Management

Tool Backpack is runtime selection only. The tool index is injected into the model prompt; do not call `tool_backpack` for an index. Select anticipated tools in one call:

```text
tool_backpack({"request":"select <id|tool_name>[,<id|tool_name>...]"})
```

Hermes normalizes bare ids or bare tool names such as `101`, `write_file`, or `101,102` to the same selection path. Treat that as retry-loop recovery only; management requests like install, remove, enable, disable, and reconcile remain unsupported through `tool_backpack`.

For adding, removing, enabling, or disabling Hermes tools, change Hermes code/config directly: registry, toolset config, catalog descriptions, diagnostic catalog refresh, and tests. Keep `tool_backpack` itself visible after changes.

Unsupported through `tool_backpack` itself: install, uninstall, update, enable, disable, reconcile. Treat those as management tasks, not runtime selection.

## External Tool Management

Use this section when the user asks to install, upgrade, uninstall, or disable an external tool, MCP server, plugin, or tool capability.

Required workflow:

1. Identify the requested tool and the exact host surface it affects: Hermes registry/config, MCP config, CLI dependency, plugin, or Backpack metadata.
2. Verify the official source before changing files or running commands. Prefer upstream docs, release metadata, and official install or uninstall instructions.
3. For unknown tools, stop after discovery until the official install, upgrade, and uninstall paths are clear.
4. Before execution, state the concrete files, config entries, commands, and runtime surface changes that will be modified.
5. Ask for explicit confirmation before any install, upgrade, uninstall, or disable action.
6. After confirmed changes, run post-change verification for the relevant CLI, config, tool registry, and Backpack runtime surface.

Safety rules:

- Do not execute package managers, curl installers, MCP changes, plugin changes, or destructive removals without confirmation.
- Do not use `tool_backpack` to install, uninstall, update, enable, disable, or reconcile tools; it is runtime selection only.
- Keep `tool_backpack` and `skill_backpack` as the visible Backpack gateways unless the user explicitly requests a full-tools control surface.
- Report secrets only as `SET` or `MISSING`; never print credential values while configuring tools.
- If a tool adds a new direct capability behind `tool_backpack`, update the registry/config/catalog path explicitly and verify the gateway can still select it.
- For disabled Hermes toolsets, verify `~/.hermes/tool_backpack_catalog.json` marks matching tools unavailable, unselectable, and `reason="disabled_toolset"`.

## Skill Backpack Management

Skill Backpack runtime loads hidden skills by page, number, or exact skill name:

```text
skill_backpack({"request":"index"})
skill_backpack({"request":"index 2"})
skill_backpack({"request":"select <number|skill-name>"})
```

Use the canonical management CLI for hidden skill tree changes:

```bash
python /home/k/cccx/tool/catmaster-backpack/skills/skill-backpack/tools/skill_backpack.py --tree-root /home/k/cccx/hermes/skill-backpack-tree verify
python /home/k/cccx/tool/catmaster-backpack/skills/skill-backpack/tools/skill_backpack.py --tree-root /home/k/cccx/hermes/skill-backpack-tree index
python /home/k/cccx/tool/catmaster-backpack/skills/skill-backpack/tools/skill_backpack.py --tree-root /home/k/cccx/hermes/skill-backpack-tree select <number-or-skill-id>
python /home/k/cccx/tool/catmaster-backpack/skills/skill-backpack/tools/skill_backpack.py --tree-root /home/k/cccx/hermes/skill-backpack-tree install --source <path> --module-id <skill-id>
python /home/k/cccx/tool/catmaster-backpack/skills/skill-backpack/tools/skill_backpack.py --tree-root /home/k/cccx/hermes/skill-backpack-tree update <skill-id> --source <path>
python /home/k/cccx/tool/catmaster-backpack/skills/skill-backpack/tools/skill_backpack.py --tree-root /home/k/cccx/hermes/skill-backpack-tree uninstall <skill-id>
python /home/k/cccx/tool/catmaster-backpack/skills/skill-backpack/tools/skill_backpack.py --tree-root /home/k/cccx/hermes/skill-backpack-tree sync
```

Canonical management source:

```text
/home/k/cccx/tool/catmaster-backpack/skills/backpack-manager
/home/k/cccx/tool/catmaster-backpack/skills/skill-backpack
```

Active runtime skill tree:

```text
/home/k/cccx/hermes/skill-backpack-tree
```

Installed parent skill locations:

```text
/home/k/.hermes/skills/skill-backpack
/home/k/cccx/hermes/roles/makise-kurisu/.hermes/skills/skill-backpack
```

Safe workflow:

1. Inspect the manifest and target module paths before changes.
2. For removal or replacement, list the affected skill id and path before acting.
3. Use install/update/uninstall only for local skill sources or explicit user requests.
4. Run `tools/skill_backpack.py verify` or the full absolute CLI command above after every tree mutation.
5. Verify `skill_backpack` can still return index and select one module by name.

## Safety Rules

- Default to read-only inspection unless the user clearly asked for a change.
- Ask before destructive removals unless the user already explicitly requested the exact removal.
- Do not print secrets or credential values. Report provider keys only as `SET` or `MISSING`.
- Do not edit historical sessions or caches unless the user explicitly asks.
- Do not bypass path, symlink, or `SKILL.md` safety checks.
- Do not make child tools or child skills globally visible as a workaround.
- Keep management commands explicit; do not hide install or delete actions behind a runtime selection request.

## Required Verification

After management changes, run the smallest relevant checks:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover tests
```

For active Hermes runtime changes:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/agent/test_tool_repo.py tests/run_agent/test_tool_backpack_surface.py tests/tools/test_skill_backpack.py tests/tools/test_skill_runtime_surface.py
```

For Tool Backpack catalog changes, include:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/hermes_cli/test_tool_backpack_catalog.py tests/hermes_cli/test_update_autostash.py tests/agent/test_tool_repo.py tests/run_agent/test_tool_backpack_surface.py
```

For main `hm` and `hmk`, verify visible tools are exactly:

```text
['skill_backpack', 'tool_backpack']
```

Then run a chat smoke for each changed home and require the response `OK`.

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Treating runtime index as management | Use CLI/config management for mutations |
| Calling `tool_backpack` with old index or reconcile requests | Use prompt index for selection or explicit management commands |
| Repeating a blocked bare id/tool call loop | Verify Hermes accepts bare ids/names as selection normalization and keep management requests blocked |
| Making all child tools visible again | Keep gateway-only surface and select on demand |
| Updating installed skill docs but not canonical docs | Update canonical first, then sync installed copies |
| Removing a skill without verifying manifest safety | Run `tools/skill_backpack.py verify` |
| Claiming `hm` or `hmk` is updated from config inspection only | Run surface and smoke checks |
