# Codex market Skill gateway

The native Codex public gateway can use saved Skills and enabled public sources.
Enabling a source stores routing metadata; a selected package is downloaded at
the inspected commit. Collection and installation into native Skill discovery
are not prerequisites. Existing scope, revocation, signed receipts, work copies
and use reports remain owned by the standalone gateway.

`adapters/codex/market_gateway.py` adapts an existing standalone installation:

```sh
python3 adapters/codex/market_gateway.py --runtime-root /path/to/standalone-backpack --connection /path/to/existing-connection.json
```

The runtime root must already contain `scripts/backpack_public_mcp.py` and its
dependencies. This checkout does not bundle that separate runtime. Keep it in
place when upgrading this adapter. Native Codex must load the updated MCP command
before an existing conversation can use the new policy. A fresh-process result
does not prove an old conversation has reloaded.

The adapter retains every candidate and its existing identity, order and group
membership. For public directory choices it adds the publisher, repository and
built-in source's purpose to the existing directory text. The directory threshold
defaults to 0.1; final Skill selection requires at least 0.7 and preserves a
stricter existing `minimum_confidence`. Configuration may set
`directory_minimum_confidence` and increase `skill_minimum_confidence`. This is
the existing source-directory/Skill route, at most two selection levels, not the
separate multi-host semantic directory. It adds no full-catalog fallback.

MCP invocation and Skill reference selection delegate to the existing runtime.
The adapter also exposes receipt-based public plugin/MCP setup; see
[codex-market-connect.md](codex-market-connect.md) for supported components,
dependency preparation, scope and recovery. Setup does not grant account access.

Before activating sources, verify the public repository, current commit,
supported metadata, source/group limits and the destination descriptor. Keep a
recoverable copy of changed configuration. Public-source fetch failures remain
visible; do not remove old entries or silently replace the source.

Verification must distinguish source indexing, selection, resource acquisition,
actual Skill application and the host's use report. Preserve failed attempts.
An Agent report is not independent execution proof. Sample success does not
establish routing accuracy for all marketplace entries.

The upstream [Agent Skills integration guide](https://agentskills.io/client-implementation/adding-skills-support)
describes loading metadata, guidance and resources separately. The
[MCP Registry API](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/api/official-registry-api.md)
provides discovery metadata; service setup still belongs to the client/runtime.
