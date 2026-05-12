# CatMaster Backpack For Claude Code

Use this snippet in a project `CLAUDE.md` after installing the portable Skill Backpack package.

## Skill Backpack

- Keep the parent skill at `.claude/skills/skill-backpack/`.
- Keep hidden child modules under `.claude/skill-backpack-tree/`.
- Treat index/select as an agent/runtime protocol flow, not a user-facing step.
- Do not present index/select as an end-user workflow.
- Load only the selected skill guidance for the current task stage.

## Tool Backpack

- Treat Tool Backpack as a protocol gateway, not a tool executor.
- If Claude Code needs callable Tool Backpack capabilities, add an optional MCP gateway with explicit index/select responses.
- Add optional hook guards and permissions only when a project has configured those Claude Code surfaces; this package does not install runtime enforcement.

## Runtime Boundary

- This Claude Code adapter is portable protocol guidance, not Hermes-equivalent runtime integration.
- Do not claim dynamic native tool hiding or selected-tool exposure unless Claude Code provides stable host hooks or MCP tool-search behavior for that surface.
