# Outreach Notes

Use this page when sharing CatMaster Backpack with agent runtime maintainers or communities.

## Short Description

```text
CatMaster Backpack is a lazy tool and skill gateway protocol for agent runtimes. It exposes compact gateways first, then lets the model explicitly select only the capability needed for the current task.
```

## Benchmark Summary

```text
Standard Hermes hm configuration, 12 deterministic file/search tasks:

hm-backpack: 12/12 correct, 62,303 total tokens
hm-full:     12/12 correct, 197,261 total tokens

Result:
- 68.4% fewer total tokens
- 68.8% fewer prompt tokens
- 2 vs 25 initial visible tools
- 97.4% fewer initial tool-schema chars

Tradeoff:
- 50.0% more API calls
- 47.5% slower average total time on this fixture
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

The fresh standard hm configuration benchmark showed:
- 12/12 correct answers for both Backpack and full direct-tools arms
- 68.4% fewer total tokens
- 68.8% fewer prompt tokens
- 2 vs 25 initial visible tools
- tradeoff: 50.0% more API calls and 47.5% slower average total time

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

Fresh standard hm configuration benchmark:
- 12/12 correct on both Backpack and full direct-tools arms
- 62,303 vs 197,261 total tokens
- 68.4% fewer total tokens
- 68.8% fewer prompt tokens
- 2 vs 25 initial visible tools
- tradeoff: 47.5% slower average total time due to the explicit selection round

I’d like feedback on whether this belongs as a native runtime feature, plugin surface, or MCP-style adapter.
```

## Show HN Draft

```text
Show HN: CatMaster Backpack, a lazy tool gateway for agent runtimes

Agent tools are eating the context window. CatMaster Backpack is a protocol/prototype that starts an agent with compact gateways (`tool_backpack`, `skill_backpack`) and lets the model explicitly select only the capability it needs.

Fresh standard Hermes benchmark:
- 12/12 correct vs 12/12 full direct tools
- 62,303 vs 197,261 total tokens
- 68.4% fewer total tokens
- 68.8% fewer prompt tokens
- 2 vs 25 initial visible tools
- Tradeoff: 47.5% slower average total time on this fixture because selection is explicit

Repo: https://github.com/kdoooh000h/catmaster-backpack

I’m interested in feedback from agent runtime maintainers: should lazy capability surfaces be a native runtime feature, plugin hook, or MCP-style adapter?
```

## Sharing Rules

Do not claim all hosts have Hermes-equivalent dynamic tool hiding. Be precise:

```text
Hermes: working runtime integration prototype
OpenCode: portable protocol and skill package
Claude Code: portable protocol and skill package
Codex-style runtimes: proposal target
```
