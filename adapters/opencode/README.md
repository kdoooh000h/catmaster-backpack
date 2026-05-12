# OpenCode Adapter

This adapter is a design placeholder.

## Initial Compatibility Target

- Package Tool Backpack protocol as `.opencode/skills/` guidance.
- Install the portable `tool_backpack` custom tool template into `.opencode/tools/`.
- Provide `backpack-manager` as the management skill.
- Use `adapters/opencode/AGENTS.md` as the project guidance snippet for portable Skill Backpack and advisor-hint behavior.
- If OpenCode exposes a stable tool manifest or MCP surface, add a `tool_repo` tool adapter that returns Tool Backpack protocol responses.

## Limitation

OpenCode may not allow dynamic hiding and re-exposing of native tools in the same way Hermes does. The first adapter should target protocol compatibility before runtime tool-surface control.
