# Host Adapter Verification Notes

As of 2026-05-12:

- OpenCode, Claude Code, Codex, and OpenClaw have packaged adapter assets and portable protocol guidance.
- These hosts have not been validated with real runtime E2E smoke tests yet.
- Current verification covers packaging, installer behavior, MCP gateway unit/smoke tests, and documentation boundaries.
- Non-Hermes hosts must not be described as Hermes-equivalent dynamic native tool-hiding runtimes.
- OpenClaw real testing is blocked because the local CLI command/path is currently unknown or unavailable.
- Future work: run host-specific baseline vs Backpack/MCP smoke tests for OpenCode, Claude Code, Codex, and OpenClaw when desired.
