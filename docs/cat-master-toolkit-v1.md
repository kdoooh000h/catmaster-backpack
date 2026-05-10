# Cat Master Toolkit V1

Date: 2026-04-25

Historical note: this document describes the earlier `tool_repo` semantic routing contract. The active Tool Backpack protocol is now the inline-index `select <tool_name>` flow in `core/protocol.md`.

`Cat Master Toolkit` is the V1 name for the Hermes `tool_repo` + `tool-installer` pairing.

## Positioning

Cat Master Toolkit is a lazy tool-surface pattern for Hermes Agent:

- Start with one visible router tool: `tool_repo`.
- Keep installed Hermes tools loaded underneath, but hidden from the model until needed.
- Let `tool_repo` activate the smallest useful capability surface.
- Let `tool-installer` handle external tool install/upgrade workflows from official sources.
- Reconcile installed/builtin tools through `tool_repo(request="reconcile tools")`.

## Compact Tool Repo Contract

```json
{
  "status": "ok",
  "decision": "use_tools",
  "capability_id": "repo.search",
  "next_tools": ["search_files", "read_file"],
  "next_action": "Use search_files/read_file not tool_repo"
}
```

Read-only shell-like repository requests route to `repo.search`:

```text
ls
find
grep
rg
fd
cat
```

## Final V1 Benchmark

See `benchmarks/results/cat-master-toolkit-v1-final.md`.

## Tradeoff

Cat Master Toolkit V1 reduces visible tools and prompt tokens while preserving accuracy on the current fixture.

The cost is one extra routing step per repository task:

```text
Cat Master Toolkit V1: tool_repo -> search_files
Full tools:            search_files
```
