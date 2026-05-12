# Codex Adapter

This adapter targets Codex desktop and Codex-style runtimes conservatively.

## Initial Compatibility Target

- Install Skill Backpack as `.codex/skills/skill-backpack/`.
- Keep managed child modules under `.codex/skill-backpack-tree/`.
- Append `adapters/codex/AGENTS.md` to project `AGENTS.md` for portable protocol guidance.
- Use optional MCP gateway or plugin integration only when the target Codex client documents that surface.

## Limitation

Do not treat Codex hosts as Hermes-equivalent lazy native tool runtimes. Dynamic native tool visibility depends on the specific Codex client or plugin surface.
