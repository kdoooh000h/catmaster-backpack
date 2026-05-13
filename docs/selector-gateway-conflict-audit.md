# Selector-Gateway Conflict Audit

Date: 2026-05-13

## Decision

Backpack gateways are selector executors, not discovery tools.

For ordinary agent turns, `tool_backpack` and `skill_backpack` must only execute selectors produced by the first-layer advisor for that same turn. Models must not use Backpack gateways to explore indexes, guess tool names, guess skill names, or recover from missing candidates.

`index` and `list` behavior remains available only for explicit user/admin catalog inspection or Backpack management tasks.

## Target Contract

1. The first-layer advisor analyzes the user request before the model calls Backpack gateways.
2. The advisor may inject explicit current-turn selectors, for example:
   - `tool_backpack select read_file,search_files`
   - `skill_backpack select credential-intake`
3. The runtime records the exact allowed selectors for the current user turn.
4. Backpack gateway calls are allowed only when the normalized request matches a recorded selector.
5. No advisor selector means no Backpack gateway call.
6. `skill_backpack index`, `tool_backpack index`, `list`, `show skills`, and equivalent catalog requests are blocked unless the current user/admin request explicitly asks to inspect or manage the catalog.
7. Unknown or unauthorized selections return a hard blocked result that tells the model not to retry or guess names.
8. Tool-loop guardrails remain as a defense-in-depth safety net, not the primary routing mechanism.

## Current Conflicts

### Hermes Runtime

- `tools/tool_backpack.py` accepts any globally installed tool name or id that matches the catalog.
- `tools/skill_backpack.py` accepts any globally installed skill name or number that matches the catalog.
- `tools/skill_backpack.py` converts an empty request into `index`.
- `tools/skill_backpack.py` allows `index`, `list`, `show skills`, and `skills` as normal requests.
- `tools/skill_backpack.py` schema currently says to use `index` when discovering unknown skills.
- `run_agent.py` injects candidate hint text but does not enforce that later gateway calls match the injected selectors.
- `agent/backpack_advisor.py` can produce explicit selectors, but its output is advisory only.
- `agent/backpack_advisor.py` still has broad ranked fallback candidates. This can be acceptable only if those fallback selectors are treated as explicit advisor authorization.
- Runtime tests verify hints are injected, but do not yet verify unauthorized gateway calls are blocked.

### CatMaster Backpack Package

- `core/protocol.md` describes Tool Backpack as accepting name/id selections from prompt indexes and describes Skill Backpack as index-first.
- `README.md` says Skill Backpack uses `skill_backpack("index")` followed by `select <number|skill-name>`.
- `skills/skill-backpack/SKILL.md` instructs agents to call `skill_backpack` with `request="index"`.
- `adapters/hermes/skill_backpack/tools/skill_backpack.py` defaults to index-like behavior and describes `Use index, then select <number>`.
- `src/catmaster_backpack/mcp_gateway.py` exposes `skill_index` as normal gateway behavior.
- `adapters/opencode/tools/tool_backpack.ts` describes `Use index or select <id|tool_name>`.
- Tests currently encode index-first and global name/id selection behavior.

### Password Manager Role

- `roles/password-manager/.hermes/config.yaml` exposes both `skill_backpack` and `tool_backpack` in CLI toolsets.
- Credential requests should primarily use `credential-intake` or `wrapped-api-capability`.
- The role instructions identify these skills but do not explicitly forbid Backpack discovery or guessed tool names.
- The observed failure loop came from a credential/token request with no advisor selector injected. The model then called `skill_backpack index` and guessed `tool_backpack select secrets-manager`, `list-secrets`, `read-vault`, and similar non-existent tools.

## Root Cause

The implementation is a hybrid of two incompatible designs:

- Old design: the model can call Backpack indexes, inspect catalogs, then select by name or number.
- New design: the advisor supplies explicit selectors and the gateways only execute authorized selections.

Because both designs are still present, the model can fall back to index/discovery when advisor hints are missing. That violates the intended selector-gateway contract and enables guessing loops.

## Required Runtime Changes

1. Add a structured advisor result alongside rendered hint text.
   - Include normalized allowed selector tuples such as `("skill_backpack", "select credential-intake")`.
   - Preserve rendered hints for prompt readability.
2. Store allowed selectors per user turn in the agent runtime.
   - Clear them at the start of each user turn.
   - Record only selectors generated for that turn.
3. Gate `tool_backpack` and `skill_backpack` calls before executing handlers.
   - Normalize whitespace and case consistently with gateway parsers.
   - Allow only exact current-turn selector matches.
   - Allow catalog inspection only when explicit user/admin list/index intent is detected.
4. Change `skill_backpack` request handling.
   - Empty request must be blocked.
   - `index` and synonyms must require explicit catalog-inspection authorization.
   - Schema must remove automatic discovery guidance.
5. Change gateway blocked responses.
   - Unauthorized gateway calls should say: `No advisor selector authorized this Backpack call. Do not guess names or retry with variants; ask the user or proceed without Backpack.`
6. Keep blocked-result failure detection.
   - `{"status":"blocked"}` and `{"decision":"blocked"}` should count as tool failures for loop guardrails.
7. Consider role-specific exposure.
   - For password-manager, remove `tool_backpack` from default toolsets or require advisor authorization before it is callable.

## Required Advisor Changes

1. Credential and token requests should produce skill selectors directly.
   - `credential-intake` for storing/checking/revealing/copying/rotating credentials.
   - `wrapped-api-capability` for giving another agent project/API access without exposing a secret.
2. Credential requests should not produce `tool_backpack` candidates unless the user explicitly asks to inspect local files or run a local command.
3. If no safe selector exists, advisor should produce no Backpack selector. The model should then answer or ask a clarifying question without Backpack.
4. Broad fallback candidates are allowed only if they are explicit current-turn authorization and are safe for the request class.

## Required Package Changes

1. Rewrite `core/protocol.md` around current-turn advisor authorization.
2. Update `README.md` to remove normal `skill_backpack index` flow.
3. Update Skill Backpack skill docs so they no longer instruct models to call `index` first.
4. Update Hermes adapter snapshots to match runtime behavior.
5. Update MCP gateway docs or implementation to distinguish admin catalog mode from ordinary agent mode.
6. Update OpenCode adapter descriptions to avoid `Use index` in ordinary agent flow.

## Test Plan

### Hermes Runtime Tests

- No advisor selector plus `tool_backpack select read_file` returns blocked.
- No advisor selector plus `skill_backpack select credential-intake` returns blocked.
- No advisor selector plus `skill_backpack index` returns blocked unless explicit list/index intent exists.
- Advisor selector `skill_backpack select credential-intake` allows that exact request.
- Advisor selector does not authorize nearby guesses such as `select credentials`, `select secrets-manager`, or `select 30`.
- Valid globally installed tool/skill names are blocked when not current-turn authorized.
- Empty `skill_backpack` request is blocked.
- Explicit user request to list/manage Backpack skills allows index/list catalog inspection.
- Blocked Backpack results are classified as tool failures and feed guardrails.
- Credential/token prompt generates `credential-intake` or `wrapped-api-capability` selector and no `tool_backpack` selector.

### CatMaster Package Tests

- Protocol docs mention current-turn advisor authorization.
- README no longer documents normal `skill_backpack index` flow.
- Skill Backpack docs do not instruct automatic index-first loading.
- Hermes adapter snapshot blocks empty skill requests and unauthorized index calls.
- MCP gateway separates explicit catalog inspection from ordinary selection execution.
- Old index-first tests are updated or moved to admin/catalog mode tests.

### Integration Checks

- `hmp` credential/token requests do not call `tool_backpack` for guessed credential tools.
- A prompt with no Backpack candidates produces no Backpack gateway call.
- A prompt with advisor candidates uses only the listed selector.
- Repeated blocked gateway calls halt quickly and do not reach max iteration limits.

## Migration Order

1. Add tests that capture the new policy in Hermes runtime.
2. Implement runtime selector authorization.
3. Remove automatic `skill_backpack index` fallback.
4. Update advisor credential/token routing.
5. Update CatMaster protocol/docs/adapters/tests.
6. Update password-manager role rules/tool exposure.
7. Run Hermes targeted tests and CatMaster package tests.
8. Manually verify `hmp` with a credential/token request and confirm no guessing loop.

## Non-Goals

- Do not remove Backpack gateways entirely.
- Do not make gateways semantically route requests.
- Do not expose full tool or skill catalogs at startup.
- Do not use guardrails as the main routing enforcement mechanism.
- Do not reveal or copy live secrets during verification.
