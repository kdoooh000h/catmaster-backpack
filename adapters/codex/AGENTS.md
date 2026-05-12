# CatMaster Backpack For Codex

Use this snippet in a project `AGENTS.md` after installing the portable Skill Backpack package for Codex desktop or Codex-style runtimes.

## Skill Backpack

- Keep the parent skill at `.codex/skills/skill-backpack/`.
- Keep hidden child modules under `.codex/skill-backpack-tree/`.
- Use the Skill Backpack protocol as `index -> select -> execute`.
- Load only the selected skill guidance for the current task stage.

## Tool Backpack

- Treat Tool Backpack as a protocol gateway, not a tool executor.
- If Codex desktop needs callable Tool Backpack capabilities, add an optional MCP gateway with explicit index/select responses.
- Add an optional plugin only when the target Codex runtime documents project-local plugin support for that environment.

## Runtime Boundary

- This Codex adapter is portable protocol guidance, not Hermes-equivalent runtime integration.
- Do not claim dynamic native tool hiding or selected-tool exposure unless the target Codex client documents that runtime surface.
