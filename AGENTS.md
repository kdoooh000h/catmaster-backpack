# CatMaster Backpack

This project packages CatMaster Backpack assets: Tool Backpack routing, Skill Backpack gateway routing, installer skill assets, adapter notes, fixtures, and benchmark records.

## Boundaries

- Treat this folder as a standalone packaging workspace, not the Hermes upstream repo.
- Do not copy API keys, local session logs, or `.hermes` runtime homes into this project.
- Keep host-specific code under `adapters/<host>/`.
- Keep reusable protocol and catalog assets under `core/`.
- Keep reusable skills under `skills/`.
- Keep Tool Backpack and Skill Backpack as coordinated subdomains of this one project.
- Keep benchmark fixtures deterministic and secret-free.

## Verification

- `test -f README.md`
- `test -f core/protocol.md`
- `test -f skills/skill-backpack/SKILL.md`
- `test -f adapters/hermes/skill_backpack/tools/skill_backpack.py`
- `python -m json.tool core/capability-catalog.json >/dev/null`
