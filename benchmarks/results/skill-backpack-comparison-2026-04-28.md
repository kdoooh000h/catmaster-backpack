# Skill Backpack Comparison - 2026-04-28

## Purpose

Record the current lightweight Skill Backpack gateway result on the isolated test skill tree. The old runtime path has been removed from active code and profiles.

## Protocols

| Arm | Runtime protocol |
| --- | --- |
| `skill_backpack` | `index` returns numbered skill list, `select <number>` returns selected `SKILL.md` |

## Fixture

- 8 test skills: `pytest-debugging`, `frontend-ui`, `apple-notes`, `database-migration`, `docker-ops`, `git-commit`, `api-auth`, `poetry-writing`.
- 8 deterministic tasks, one expected skill per task.
- Same Hermes model/config for both arms.
- `skip_context_files=True`, `skip_memory=True` for programmatic usage capture.
- Final answer scored by exact `TOKEN:<skill>` from loaded skill content.

## Result

| Metric | `skill_backpack` |
| --- | ---: |
| Correct skill selections | 8/8 |
| API calls | 24 |
| Avg API calls/task | 3.0 |
| Input tokens | 3,975 |
| Output tokens | 1,643 |
| Cache-read tokens | 7,984 |
| Cache-write tokens | 0 |
| Reasoning tokens | 0 |
| Total tokens | 13,602 |
| Avg tokens/task | 1,700 |

## Interpretation

- Accuracy on this clear small fixture: all 8 expected skills selected.
- API call count: 3 API calls per task.
- The removed old runtime used 28,673 total tokens on the same fixture; `skill_backpack` used 13,602 total tokens.
- The new runtime uses about 52.6% fewer total tokens and about 62.7% fewer non-cache input tokens than the removed old runtime.
- This result supports the lightweight `index -> select -> execute` gateway as the active runtime skill-selection protocol.

## Production Surface Check

The production `hmk` profile was later switched to the new gateway:

```text
toolsets: ['skill_backpack', 'tool_backpack']
tools: ['skill_backpack', 'tool_backpack']
```
