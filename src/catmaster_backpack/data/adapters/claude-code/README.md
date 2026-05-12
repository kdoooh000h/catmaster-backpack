# Claude Code Adapter

This adapter is a design placeholder.

## Initial Compatibility Target

- Package Tool Backpack as a Claude skill bundle.
- Use `adapters/claude-code/CLAUDE.md` as the project memory snippet for portable Skill Backpack behavior.
- Expose Tool Backpack through an MCP gateway if tool registration is required.
- Provide `backpack-manager` as the management skill.
- Use Tool Backpack capability catalog for compact routing guidance.

## Limitation

Dynamic tool-surface control depends on host APIs. Until stable hooks exist, this adapter should keep the protocol and skill workflow portable without claiming Hermes-equivalent lazy visibility.
