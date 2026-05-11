# Outreach Notes

Use this page when sharing CatMaster Backpack with agent runtime maintainers or communities.

## Short Description

```text
CatMaster Backpack is a lazy tool and skill gateway protocol for agent runtimes. It exposes compact gateways first, then lets the model explicitly select only the capability needed for the current task.
```

## Maintainer Email

```text
Subject: CatMaster Backpack: lazy tool/skill gateway for agent runtimes

Hi <name>,

I built an open-source prototype for reducing visible agent tool/skill surface area:

https://github.com/kdoooh000h/catmaster-backpack

The core idea is simple:
- expose only tool_backpack / skill_backpack initially
- let the model explicitly select capabilities, e.g. select read_file
- expose the selected tool only after selection
- avoid injecting a full tool catalog at startup

Hermes integration is the most complete so far. Local blind tests showed:
- the prompt did not mention Backpack/gateway/tool/select
- the agent selected tool_backpack -> read_file/search_files
- no full "Tool Backpack index:" was injected

I’m sharing in case this fits your runtime or plugin direction. If useful, I’d be happy to open an issue, PR, or adapt the protocol to your project’s extension surface.

Thanks,
kdoooh000h
```

## GitHub Discussion Post

```text
I’m exploring a lazy capability-surface pattern for agent runtimes:

https://github.com/kdoooh000h/catmaster-backpack

Instead of exposing every tool/skill up front, the runtime exposes compact gateways:

tool_backpack
skill_backpack

The model explicitly selects a capability, and the host exposes only that selected tool or skill. Hermes has a working prototype; OpenCode and Claude Code support is currently protocol/skill packaging only until stable dynamic tool-surface hooks exist.

I’d like feedback on whether this belongs as a native runtime feature, plugin surface, or MCP-style adapter.
```

## Sharing Rules

Do not claim all hosts have Hermes-equivalent dynamic tool hiding. Be precise:

```text
Hermes: working runtime integration prototype
OpenCode: portable protocol and skill package
Claude Code: portable protocol and skill package
Codex-style runtimes: proposal target
```
