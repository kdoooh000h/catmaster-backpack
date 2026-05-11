# CatMaster Backpack Protocol

Tool Backpack starts with one visible gateway tool. Hosts should provide a compact tool index outside the tool call path when their runtime supports prompt injection, so the model can select tools directly. Canonical selection is `select <id|tool_name>[,<id|tool_name>...]`, but host adapters may normalize bare ids or bare tool names to the same selection result. Hermes uses prompt-index selection: non-selection requests are blocked with selection guidance; the host then exposes exactly the selected tool or tools.

Skill Backpack uses the same rule: gateway returns an index, the model chooses, and the gateway loads only the selected skill. The gateway should not semantically route or auto-select the best skill.

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

## Prompt Index

Hermes injects the index into the model prompt instead of making the model call `tool_backpack` for an index:

```text
Tool Backpack index:
101: search_files - search names/content
102: read_file - read paged text
201: patch - apply file patch
Select all anticipated tools in one call by calling tool_backpack with: select <id|tool_name>[,<id|tool_name>...].
```

## Optional `tool_index` Response

Portable adapters without prompt-index injection may return a compact index for explicit list/index requests:

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

`tools` is a compact fixed-id index. IDs are stable within the installed catalog. Host adapters may filter this index to tools available in the current runtime surface. Hermes currently blocks non-selection requests because the index is already visible in the prompt.

## `select_tool` Response

Tool selection accepts `select <id>`, `select <tool_name>`, or multiple ids/names. Hermes normalizes bare `<id>`, bare `<tool_name>`, and comma/space-separated bare selections before returning this response.

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
- In prompt-index mode, block non-selection requests instead of returning a second index.
- Do not expose indexed tools after an optional `tool_index` response.
- Do not turn `tool_backpack` into a tool executor unless the host adapter explicitly owns that boundary.
- Treat bare id/name support as selection normalization only; do not use it for semantic routing or management requests.
- Let agents choose from inline or returned tool indexes; selection returns the tool name, then the agent calls that tool directly.
- Keep responses compact and machine-readable.
- Future expansion should use layered indexes rather than semantic routing.

## Skill Gateway Pattern

Current experimental Hermes target:

```json
{"request":"index"}
```

returns:

```json
{
  "status": "ok",
  "decision": "skill_index",
  "d": "index",
  "skills": [
    [1, "api-auth", "Implement or debug API authentication, authorization headers, tokens, sessions, and 401/403 errors."],
    [2, "pytest-debugging", "Diagnose failing Python pytest tests, fixture errors, assertions, and regressions."]
  ],
  "next": "select <number>"
}
```

Then:

```json
{"request":"select 1"}
```

returns:

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

- Return compact indexes and let the model choose by number.
- Do not return legacy refs or hash fields in the lightweight gateway protocol.
- Do not verify content hashes in the lightweight runtime path.
- Still reject path escapes, symlinks, non-`SKILL.md` targets, disabled entries, and unknown selection numbers.
- Remove old multi-tool skill runtime surfaces from active profiles.
