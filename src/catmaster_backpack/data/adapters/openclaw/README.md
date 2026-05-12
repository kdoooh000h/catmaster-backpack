# OpenClaw Adapter

This adapter targets OpenClaw conservatively through documented project guidance and skill packaging.

## Initial Compatibility Target

- Install Skill Backpack as `.openclaw/skills/skill-backpack/`.
- Keep managed child modules under `.openclaw/skill-backpack-tree/`.
- Append `adapters/openclaw/AGENTS.md` to project `AGENTS.md` for portable protocol guidance.
- Prefer OpenClaw Tool Search, plugin tools, or MCP gateways only when the target runtime exposes those documented surfaces.

## Limitation

OpenClaw can own tool catalogs and plugins, but native sub-runtimes may still own their own tool visibility. Do not advertise Hermes-equivalent dynamic hiding outside documented OpenClaw-controlled surfaces.
