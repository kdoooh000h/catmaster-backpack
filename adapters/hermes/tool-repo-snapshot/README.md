# Hermes Tool Repo Snapshot

This folder contains the latest Hermes Tool Backpack implementation snapshot used by CatMaster Backpack.

## Files

- `agent/tool_repo.py` - compact prompt-index `tool_backpack(request)` protocol and gateway decisions.
- `agent/tool_repo_catalog.py` - installed-tool catalog, reconcile, capability index, and unknown bucket logic.
- `agent/tool_repo_registry.py` - built-in capability definitions and task-to-capability resolver.

## Runtime Hook

Hermes runtime integration also requires `run_agent.py` changes:

- initial lazy visible surface exposes `tool_backpack` and `skill_backpack`
- `run_agent.py` injects `build_tool_prompt_index(...)` into the system prompt
- `tool_backpack` selection responses expose selected child tools until final answer
- non-selection `tool_backpack` requests are blocked because the index is already visible
- inferred installed tools are added from loaded schemas
- update hooks refresh `~/.hermes/tool_backpack_catalog.json` from the live registry for diagnostics

Those runtime changes are described in `../README.md`. This directory is a source snapshot, not a standalone drop-in package yet.

## Version

Source state in Hermes Agent repo:

```text
2026-05-04 working tree: prompt-index lazy surface plus live-registry catalog refresh
```
