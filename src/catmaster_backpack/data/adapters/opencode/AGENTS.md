# CatMaster Backpack For OpenCode

Use this snippet in a project `AGENTS.md` after installing the portable Skill Backpack package.

## Skill Backpack

- Keep the parent skill at `.opencode/skills/skill-backpack/`.
- Keep hidden child modules under `.opencode/skill-backpack-tree/`.
- Use the Skill Backpack protocol as `index -> select -> execute`.
- Load only the selected skill guidance for the current task stage.

## Tool Backpack

- Keep the portable Tool Backpack custom tool at `.opencode/tools/tool_backpack.ts`.
- Use `tool_backpack` for compact index and explicit selection responses before calling the selected native OpenCode tool.
- Treat `tool_backpack` as a protocol gateway, not a tool executor.

## Advisor Hints

- Treat deterministic grouped advisor hints as compact guidance only.
- Let the model explicitly select the skill or tool candidate; do not semantically route on its behalf.

## Runtime Boundary

- This OpenCode adapter is portable protocol guidance, not Hermes-equivalent runtime integration.
- Do not claim dynamic native tool hiding or selected-tool exposure unless OpenCode provides stable host hooks for it.
