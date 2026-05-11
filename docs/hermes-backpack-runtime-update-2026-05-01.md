# Hermes Backpack Runtime Update - 2026-05-01

## Purpose

Record the current Hermes Backpack runtime decisions and verification assets after the Tool Backpack and Skill Backpack optimization work.

## Runtime Decisions

- Standard Hermes surfaces (`hm`, `kurisu`, `senku`, `haibara`, `rick`, `hmk`) use `tool_backpack` and `skill_backpack` as the compact visible gateway surface.
- `hm-full` remains the full direct-tools control environment and should not be switched to Backpack unless explicitly requested.
- Tool Backpack uses prompt-index selection. Canonical calls use `select <id|tool_name>[,<id|tool_name>...]`; Hermes also normalizes bare ids or tool names such as `101`, `write_file`, or `101,102` to the same selection path to avoid blocked-call retry loops.
- Tool Backpack selected tools stay visible until the final answer, then the surface returns to the gateway tools.
- Skill Backpack uses paged index selection. The model calls `skill_backpack` with `index`, `index <page>`, `index all`, or `select <number|skill-name>`.
- Skill Backpack ranks selected skills higher over time by root-namespaced usage counts.
- Neither Backpack uses semantic routing inside the gateway; the model receives an index and chooses.

## Tool Backpack Catalog Refresh - 2026-05-04

- Hermes now writes a diagnostic Tool Backpack catalog cache after update at `~/.hermes/tool_backpack_catalog.json`.
- The runtime source of truth remains the live Hermes tool registry; the cache is diagnostic metadata, not a copied tool manifest.
- The catalog records `available`, `selectable`, `source`, `toolset`, and `reason` for each registered tool.
- `disabled_toolsets` are passed into live tool-definition discovery and force matching tools to `available=false`, `selectable=false`, and `reason="disabled_toolset"`.
- Dynamic official toolsets that are registered outside the static `TOOLSETS` mapping, currently `browser-cdp`, are still classified as `official`.
- Current verified catalog summary: `registered=78`, `selectable=31`, `unavailable=42`, `official=76`, `plugin=2`, `mcp=0`.

## Real Tool Backpack Smoke - 2026-05-04

- Real non-interactive command used `/home/k/.local/bin/hermes-main -z`, which runs the normal Hermes agent loop with the configured model, not a direct Python call or mock.
- Session evidence: `/home/k/.hermes/sessions/session_20260504_113656_af340a.json`.
- Tool call sequence in that session:

```text
tool_backpack {"request":"select 101"}
search_files {"pattern":"run_agent.py","target":"files"}
TOOL_BACKPACK_SMOKE_OK
```

- Initial session tools were only `skill_backpack` and `tool_backpack`; `search_files` appeared after Tool Backpack selection.

## Official Update Sync

- `hermes update` now has an official-skill sync hook guarded by `skills.auto_sync_official_skills`.
- The runtime source of truth remains `/home/k/cccx/hermes/skill-backpack-tree`.
- Official skills tracked by the Hermes repo under `skills/` and `optional-skills/` are copied into the active Backpack tree after update when `skill_backpack_enabled` and `skill_backpack_root` are configured.
- New official skills are added enabled and become visible through the Skill Backpack index.
- Existing local same-name skills are replaced by the official copy; local customizations should use a distinct skill name.
- Previously synced official skills are replaced by the tracked official copy on sync.
- Previously synced entries whose source path is no longer tracked by Hermes are kept as local skills.
- Sync failures warn and do not fail the Hermes update.

## Management Skill

- `backpack-manager` is the management entry point for changing hidden Tool Backpack or Skill Backpack availability and for external tool/MCP/plugin install, upgrade, uninstall, or disable workflows.
- It is installed in the active tree and in the main/Kurisu skill homes.
- Runtime gateway requests are not used for installs, updates, removals, or reconciliation.
- `tool-installer` is no longer an active Skill Backpack index entry; its installer responsibilities are folded into `backpack-manager`.
- Skill mutations should use the management CLI:

```bash
python /home/k/cccx/tool/catmaster-backpack/skills/skill-backpack/tools/skill_backpack.py --tree-root /home/k/cccx/hermes/skill-backpack-tree <command>
```

## Real Testing Skill

- `hermes-real-benchmark-testing` is now the unified skill for real Hermes verification after Tool Backpack or Skill Backpack optimization.
- Canonical source: `/home/k/cccx/tool/catmaster-backpack/skills/hermes/hermes-real-benchmark-testing/SKILL.md`
- Active tree copy: `/home/k/cccx/hermes/skill-backpack-tree/modules/hermes-real-benchmark-testing/SKILL.md`
- It covers:
  - production `hm` smoke through `/home/k/.local/bin/hm`
  - non-interactive `hermes-main` fallback
  - `hm-full` baseline through `/home/k/cccx/tool/experiments/hermes-advisor-ab/full-latest/bin/hermes-full-latest`
  - Tool Backpack smoke requiring `tool_backpack select`
  - Skill Backpack smoke requiring `skill_backpack select`
  - session JSON inspection for visible tools, tool calls, final markers, and rough token estimates

## Verification Evidence

- Tool Backpack and Skill Backpack focused Hermes tests passed after runtime changes.
- Tool Backpack catalog focused tests passed after disabled-toolset and `browser-cdp` source fixes.
- Tool Backpack regression suite passed: `53 passed` across catalog, update autostash, tool repo, and runtime surface tests.
- Real `hermes-main -z` Tool Backpack smoke returned `TOOL_BACKPACK_SMOKE_OK`.
- CatMaster Backpack skill documentation tests passed after updating `hermes-real-benchmark-testing`.
- Active tree verification after installing `hermes-real-benchmark-testing` returned `{"checked": 78, "ok": true}`.
- `hermes-main tools list` showed only `tool_backpack` and `skill_backpack` enabled for the standard CLI surface.

## Verification Gap

The 2026-05-04 update ran a real non-interactive `hermes-main -z` smoke and inspected session JSON. It did not run a fresh interactive `hm`/`hm-full` benchmark. Use `hermes-real-benchmark-testing` before claiming broader production benchmark behavior for future Backpack optimizations.
