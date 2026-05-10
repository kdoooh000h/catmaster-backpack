# Cat Master Toolkit V2 Tool Indexer

Date: 2026-04-25

Historical note: this document describes the earlier capability-route `choose -> select` design. The active Tool Backpack protocol is now the inline-index `select <tool_name>` flow in `core/protocol.md`.

V2 starts the installed-tool recognition layer for Cat Master Toolkit.

## Goal

Recognize host-installed tools and classify them into the Tool Backpack tool repo so lazy tool routing can expose installed tools by capability.

## Classification Order

1. Exact built-in capability mapping.
2. Installer template metadata, including aliases such as `playwright`.
3. Tool name, schema description, and parameter names.
4. `unknown` bucket when classification is unsafe.

## Current Capability Buckets

```text
repo.search
repo.edit
web.lookup
browser.inspect
unknown
```

## Runtime Behavior

`reconcile_tool_catalog()` returns:

```text
capability_index
unknown_tools
```

`tool_repo(request="reconcile tools")` includes the same compact index in its maintenance response.

Hermes lazy tool surface augments static capability tools with inferred installed tools from loaded tool schemas.

Task routing returns a compact fixed-id candidate index instead of a single prescribed tool. The agent chooses an id, calls `tool_backpack` with `select <id>`, then calls the selected tool directly. Candidate tools stay hidden after `choose` and only the selected tool is exposed after `select <id>`.

Example response:

```json
{
  "d": "choose",
  "cap": "repo.search",
  "tools": [
    [101, "search_files", "search names/content"],
    [102, "read_file", "read paged text"]
  ],
  "next": "select <id>"
}
```

`select <id>` responses include `fmt="exact user format; FILE= uses basename"`. `search_files` results include both `path` and `filename`, plus `answer_format_hint`, so exact user formats such as `FILE=<filename>` use the basename instead of the full path.

Example:

```text
mcp_notes_reader -> repo.search
mcp_repo_writer -> repo.edit
mcp_browser_snapshot -> browser.inspect
playwright -> browser.inspect
mcp_randomizer -> unknown
```

Unknown tools are indexed for review but are not added to known capability surfaces.

## Hermes Runtime Smoke Test

Date: 2026-04-25

Environment:

```text
/home/k/cccx/tool/experiments/hermes-test
HERMES_HOME=/home/k/cccx/tool/experiments/hermes-test/custom-tools/.hermes
Python=/home/k/cccx/tool/experiments/hermes-test/full-tools/.venv/bin/python
Runtime=/home/k/cccx/hermes/repos/hermes-agent/run_agent.py
```

Method:

```text
Instantiate run_agent.AIAgent with enabled_toolsets=['tool_backpack', 'file', 'terminal', 'web', 'no_mcp'].
Call Hermes runtime _invoke_tool('tool_backpack', {'request': ...}).
```

Observed result:

```json
{
  "lazy": true,
  "visible": ["tool_backpack"],
  "show_status": "ok",
  "show_decision": "list_tools",
  "show_tool_count": 67,
  "show_unknown_count": 30,
  "show_has_tool_backpack": true,
  "remove_status": "ok",
  "remove_decision": "use_skill",
  "remove_skill": "tool-installer",
  "remove_template_found": true,
  "remove_template_ref": "skills/mcp/tool-installer/templates/playwright.json",
  "remove_uninstall_mode": "manual",
  "remove_will_execute": false
}
```

Conclusion:

```text
Hermes runtime exposes only tool_backpack initially, lists installed/internal tools on explicit request, and routes remove playwright to tool-installer without executing uninstall.
```

## Hermes Runtime Numbered Index Smoke Test

Date: 2026-04-26

Method:

```text
Instantiate run_agent.AIAgent with enabled_toolsets=['tool_backpack', 'file', 'terminal', 'web', 'no_mcp'].
Call _invoke_tool('tool_backpack', {'request': 'search repo files'}).
Call _invoke_tool('tool_backpack', {'request': 'select 101'}).
Inspect visible runtime tools before and after each call.
```

Observed result:

```json
{
  "lazy": true,
  "initial_visible": ["tool_backpack"],
  "choose_status": "ok",
  "choose_decision": "use_tools",
  "choose_d": "choose",
  "choose_cap": "repo.search",
  "choose_tools": [
    [101, "search_files", "search names/content"],
    [102, "read_file", "read paged text"]
  ],
  "after_choose_visible": ["skill_backpack", "tool_backpack"],
  "select_status": "ok",
  "select_decision": "select_tool",
  "select_d": "selected",
  "select_id": 101,
  "select_tool": "search_files",
  "select_fmt": "exact user format; FILE= uses basename",
  "after_select_visible": ["search_files", "skill_backpack", "tool_backpack"]
}
```

Conclusion:

```text
Tool Backpack can return a compact fixed-id candidate index, keep candidates hidden after choose, accept select <id>, and narrow the Hermes runtime visible surface to the selected tool.
```

## Hermes Runtime Multi-Demand Smoke Test

Date: 2026-04-26

Method:

```text
For each request, instantiate run_agent.AIAgent with Tool Backpack lazy surface enabled.
Call _invoke_tool('tool_backpack', {'request': <request>}).
For use_tools responses, call select <id> and inspect visible tools after selection.
```

Observed summary:

```text
repo_search: search repo files -> choose repo.search -> [101 search_files, 102 read_file] -> select 101 -> search_files visible
repo_edit: edit repo file -> choose repo.edit -> includes 201 patch, 202 terminal and installed repo helpers -> select 201 -> patch visible
web_lookup: search web for official docs -> choose web.lookup -> runtime-available [3350 vision_analyze] -> select 3350 -> vision_analyze visible
browser_inspect: inspect browser page screenshot -> choose browser.inspect -> includes 401 browser_navigate, 402 browser_snapshot, 403 browser_vision and installed browser helpers -> select 401 -> browser_navigate visible
install: install playwright -> use_skill tool-installer, template_found=true
uninstall: remove playwright -> use_skill tool-installer, template_found=true
list_tools: show tools -> list_tools, tool_count=69, unknown_count=32
blocked: brew coffee -> blocked
invalid_select: after web_lookup, select 301 -> blocked because web_search is not available in this runtime
```

Conclusion:

```text
Hermes rewrites candidate tool indexes to tools available in the runtime for the matched capability, but does not expose those candidates until `select <id>`. It then blocks selection of unavailable fixed ids.
```

## Real LLM Accuracy Benchmark

Date: 2026-04-27

Environment:

```text
Runtime=/home/k/cccx/hermes/repos/hermes-agent
Fixture=/home/k/cccx/tool/catmaster-backpack/benchmarks/accuracy-fixture
Old comparison=/home/k/cccx/tool/experiments/hermes-test/tool-repo-vs-full-description-trim-2026-04-25.jsonl
```

Final numbered Tool Backpack result:

```text
strict_correct: 3/3
api_calls: 16
prompt_tokens: 20,540
completion_tokens: 1,097
total_tokens: 21,637
avg_total_time: 14.2s
initial_visible_tools: 1 (tool_backpack)
```

Comparison:

| Surface | Strict Correct | Total Tokens | Avg Total Time | Initial Visible Tools |
| --- | ---: | ---: | ---: | ---: |
| New numbered Tool Backpack | 3/3 | 21,637 | 14.2s | 1 |
| Old Tool Repo | 3/3 | 9,150 | 5.82s | 1 |
| Full tools | 3/3 | 67,612 | 14.83s | 27 |

Notes:

- The `choose -> select` failure was caused by parent runtime state exposing candidate child tools immediately after `choose`; fixed by keeping the visible surface unchanged until selection.
- The `FILE=` formatting failure was caused by `search_files` returning full paths that the model copied; fixed by adding `filename` and `answer_format_hint` to search results.
- Prompt instructions alone were insufficient. The parent runtime surface and child tool output schema both needed hard constraints.
