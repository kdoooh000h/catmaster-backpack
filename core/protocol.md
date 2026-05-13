# CatMaster Backpack Protocol

System version: v0

Tool Backpack starts with one visible gateway tool. Ordinary task turns should receive compact advisor-provided selector candidates outside the tool call path, so the model can select tools directly. Canonical selection is `select <id|tool_name>[,<id|tool_name>...]`, but host adapters may normalize bare ids or bare tool names to the same selection result when those selectors were authorized for the current turn. Hermes uses advisor-selector selection: non-selection requests are blocked with selection guidance; the host then exposes exactly the selected tool or tools.

Skill Backpack uses the same rule: the advisor provides current-turn skill selectors, the model chooses, and the gateway loads only the selected skill. The gateway should not semantically route, auto-select the best skill, or return a catalog in ordinary task flow. Compact indexes are reserved for explicit catalog inspection or management mode.

## Entry Tool

```json
{
  "name": "tool_backpack",
  "parameters": {
    "type": "object",
    "properties": {
      "request": {"type": "string"}
    },
    "required": ["request"],
    "additionalProperties": false
  }
}
```

Recommended description:

```text
Tool gateway.
```

Fast path:

`select search_files`

```json
{"request":"select search_files"}
```

The fast path keeps the initial visible surface to one tool while avoiding a separate index-return round. Hermes also accepts bare selection tokens such as `search_files`, `101`, or `101,102` as recovery inputs equivalent to `select search_files`, `select 101`, or `select 101,102`; unknown bare words remain blocked.

## Advisor Selectors

Hermes injects current-turn selectors into the model prompt instead of making the model call `tool_backpack` or `skill_backpack` for an index:

```text
Backpack advisor candidates:
- tool_backpack select search_files - search names/content
- skill_backpack select 1 - systematic debugging guidance

Select only advisor-provided selectors for this turn. Do not call index/list or guess selector names.
```

## Optional `tool_index` Response

Portable adapters may return a compact index only for explicit catalog inspection or administrator requests:

```json
{
  "status": "ok",
  "decision": "tool_index",
  "d": "index",
  "tools": [
    [101, "search_files", "search names/content"],
    [102, "read_file", "read paged text"],
    [201, "patch", "apply file patch"]
  ],
  "next": "select <id|tool_name>",
  "next_action": "Choose a tool id or tool name from the index, then call tool_backpack with select <id|tool_name>."
}
```

`tools` is a compact fixed-id index. IDs are stable within the installed catalog. Host adapters may filter this index to tools available in the current runtime surface. Ordinary task turns must block `index`, `list`, and equivalent catalog requests unless the host has positively identified an explicit catalog inspection or administration request.

## `select_tool` Response

Tool selection accepts `select <id>`, `select <tool_name>`, or multiple ids/names from the current advisor candidates. Hermes normalizes bare `<id>`, bare `<tool_name>`, and comma/space-separated bare selections only after the current turn authorized those selectors.

```json
{
  "status": "ok",
  "decision": "select_tool",
  "d": "selected",
  "id": 101,
  "tool": "search_files",
  "next": "call search_files"
}
```

Multiple selection returns:

```json
{
  "status": "ok",
  "decision": "select_tools",
  "d": "selected",
  "tools": ["search_files", "read_file"],
  "next": "call selected tools"
}
```

## Rules

- Do not expose full tool catalogs at startup.
- Do not semantically route requests inside `tool_backpack`; expose a prompt or compact index and let the model select.
- In advisor-selector mode, block non-selection requests instead of returning a catalog.
- Treat catalog inspection as an explicit management/admin mode, not as fallback discovery for ordinary tasks.
- Do not expose indexed tools after an optional `tool_index` response.
- Do not turn `tool_backpack` into a tool executor unless the host adapter explicitly owns that boundary.
- Treat bare id/name support as selection normalization only; do not use it for semantic routing or management requests.
- Let agents choose from inline or returned tool indexes; selection returns the tool name, then the agent calls that tool directly.
- Keep responses compact and machine-readable.
- Future expansion should use layered indexes rather than semantic routing.

## Skill Gateway Pattern

Current Hermes ordinary task target:

```json
{"request":"select 1"}
```

where `select 1` was provided by the current-turn advisor. The gateway returns:

```json
{
  "status": "ok",
  "decision": "select_skill",
  "d": "loaded",
  "skill": "api-auth",
  "content": "<selected SKILL.md>"
}
```

Skill gateway rules:

- Load only advisor-provided selectors in ordinary task flow.
- Return compact indexes only in explicit catalog inspection or management mode.
- Do not return legacy refs or hash fields in the lightweight gateway protocol.
- Do not verify content hashes in the lightweight runtime path.
- Still reject path escapes, symlinks, non-`SKILL.md` targets, disabled entries, and unknown selection numbers.
- Remove old multi-tool skill runtime surfaces from active profiles.
