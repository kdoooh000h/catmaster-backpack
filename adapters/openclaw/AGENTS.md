# CatMaster Backpack For OpenClaw

Use this snippet in a project `AGENTS.md` after installing the portable Skill Backpack package for OpenClaw.

## Skill Backpack

- Keep the parent skill at `.openclaw/skills/skill-backpack/`.
- Keep hidden child modules under `.openclaw/skill-backpack-tree/`.
- Use the Skill Backpack protocol as `index -> select -> execute`.
- Load only the selected skill guidance for the current task stage.

## Tool Backpack

- Treat Tool Backpack as a protocol gateway, not a tool executor.
- Prefer OpenClaw Tool Search or effective tool policy when the host runtime exposes those surfaces.
- Add an optional plugin only when the project is ready to register OpenClaw-owned tools or MCP gateways.

## Runtime Boundary

- This OpenClaw adapter is portable protocol guidance, not Hermes-equivalent runtime integration.
- Do not claim dynamic native tool hiding or selected-tool exposure for non-OpenClaw-owned runtime tools unless the selected OpenClaw runtime documents that surface.
