# Hermes Adapter

The Hermes adapter is the first validated CatMaster Backpack integration.

## Implemented In Hermes Agent

Current source location:

```text
/home/k/cccx/hermes/repos/hermes-agent
```

Runtime manifest packaged in this repository:

```text
adapters/hermes/runtime-manifest.json
```

Validated GitHub runtime source:

```text
repository: https://github.com/kdoooh000h/hermes-agent.git
branch: backpack-advisor-gateway
commit: d8e7b8be8e2ae1a41020a9d8ce518eb580dfd069
```

Relevant Hermes files:

```text
agent/backpack_advisor.py
tools/tool_backpack.py
tools/skill_backpack.py
run_agent.py
toolsets.py
hermes_cli/tools_config.py
tools/skills_sync.py
tui_gateway/server.py
```

## Behavior

- Initial visible Tool Backpack tool: `tool_backpack`.
- Loaded underlying tools remain available to the runtime.
- Hermes injects the Tool Backpack index into the model prompt and blocks non-selection `tool_backpack` requests with guidance.
- `tool_backpack` returns selected tool name(s) from canonical `select <id|tool_name>[,<id|tool_name>...]` requests and may normalize bare ids or bare tool names to the same selection path.
- Hermes runtime rebuilds visible tools from the gateway tools plus selected child tools until the final answer, then returns to gateway-only visibility.
- Installed tools are classified from live registry schema/name metadata.
- A diagnostic catalog cache is written to `~/.hermes/tool_backpack_catalog.json` after update; live registry remains the source of truth.
- Disabled toolsets are passed into availability checks and force matching tools unavailable/unselectable in the diagnostic catalog.
- Active Skill Backpack tool: `skill_backpack`, returns a numbered skill index and selected `SKILL.md` content.

## Installed Tool Diagnostics

Historical `tool_repo(request="reconcile tools")` behavior is no longer the runtime management path. Current diagnostics use the live-registry catalog snapshot:

```text
~/.hermes/tool_backpack_catalog.json
```

## Status

Tool Backpack prompt-index lazy selection is validated by focused Hermes tests and a real `hermes-main -z` agent-loop smoke. Skill Backpack `skill_backpack` is the active Hermes skill gateway, and the current published measurement is the 2026-05-11 Hermes surface result.
