# Hermes Adapter

The Hermes adapter is the first validated CatMaster Backpack integration.

## Implemented In Hermes Agent

Current source location:

```text
/home/k/cccx/hermes/repos/hermes-agent
```

Relevant Hermes files:

```text
agent/tool_repo.py
agent/tool_repo_catalog.py
agent/tool_repo_registry.py
hermes_cli/tool_backpack_catalog.py
run_agent.py
tools/skill_backpack.py
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

Tool Backpack prompt-index lazy selection is validated by focused Hermes tests and a real `hermes-main -z` agent-loop smoke. Skill Backpack `skill_backpack` is validated on the 2026-04-28 local 8-skill comparison: 8/8 correct selections, 3 API calls per task, and about 52.6% fewer total tokens than the removed old runtime on the small fixture.
