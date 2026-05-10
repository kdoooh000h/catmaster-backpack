---
name: skill-backpack
description: Use when software engineering workflows need hidden local skill modules, compact skill indexes, controlled skill loading, or explicit management of local skill trees.
---

# Skill Backpack

## Overview

Skill Backpack keeps child modules invisible to global skill discovery while allowing the current agent to load selected modules at runtime through a controlled gateway.

Core protocol: `index -> select -> execute`.

## Runtime Mode

Use Runtime Mode for ordinary development tasks.

1. Call the native Hermes tool `skill_backpack` with `request="index"`.
2. Choose one skill number from the returned index.
3. Call `skill_backpack` with `request="select <number>"`.
4. Execute the loaded module text directly.
5. If a new task stage needs different guidance, call `skill_backpack` again with `request="index"`.
6. Do not load paths, URLs, disabled modules, unrelated modules, or multiple modules from one index.
7. Do not modify modules in Runtime Mode.

## Management Mode

Use Management Mode when users need to inspect or manage hidden child skills through the parent skill.

- `tools/skill_backpack.py index` lists available modules without loading full content.
- `tools/skill_backpack.py select <number-or-skill-id>` displays one module for inspection.
- `tools/skill_backpack.py install --source <skill-dir-or-SKILL.md>` installs a local skill source into the tree.
- `tools/skill_backpack.py update <skill-id> --source <skill-dir-or-SKILL.md>` replaces a managed module.
- `tools/skill_backpack.py uninstall <skill-id>` removes a managed module from the tree.

After install, update, or uninstall, run `tools/skill_backpack.py verify` before using the tree.

## Plugin Install

Use `tools/skill_backpack_plugin.py` to install Skill Backpack as a project parent-skill plugin.

Supported project installs:

- OpenCode: `.opencode/skills/skill-backpack/` plus `.opencode/skill-backpack-tree/`
- Claude Code: `.claude/skills/skill-backpack/` plus `.claude/skill-backpack-tree/`
- Hermes: `.hermes/skills/skill-backpack/` plus `.hermes/skill-backpack-tree/`

Default migration mode is copy, not move. Original skill files remain in place unless a future explicit move mode is added.

Examples:

```bash
tools/skill_backpack_plugin.py install --agent opencode --scope project --project-root . --source .opencode/skills
tools/skill_backpack_plugin.py install --agent claude-code --scope project --project-root . --source .claude/skills
```

## Safety Contract

Runtime `select` accepts only a number from the current compact index. It must reject unknown numbers, direct paths, URLs, disabled modules, non-`SKILL.md` targets, symlinks, and paths outside the tree root.

## Quick Reference

| Command | Use |
| --- | --- |
| `skill_backpack({"request":"index"})` | Return a numbered module index |
| `skill_backpack({"request":"select <number>"})` | Return selected module text |
| `tools/skill_backpack.py verify` | Check manifest paths |
| `tools/skill_backpack.py index` | List skill ids, status, keywords |
| `tools/skill_backpack.py select <number-or-skill-id>` | Display one skill |
| `tools/skill_backpack.py install --source <path>` | Install a local skill source |
| `tools/skill_backpack.py update <skill-id> --source <path>` | Update a managed skill |
| `tools/skill_backpack.py uninstall <skill-id>` | Remove a managed skill |
| `tools/skill_backpack_plugin.py install --agent opencode --scope project --project-root . --source .opencode/skills` | Install project plugin |
