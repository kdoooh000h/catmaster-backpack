# CatMaster connector v1

The operator connects one host profile to one project registry. The host receives
two fixed MCP tools (`acquire`, `invoke`), one capability resource, and one native
lifecycle bridge. Registering a package never edits the host configuration.

## Discovery and matching

`backpack://connector/capabilities` is a read-only MCP resource. Hosts that
subscribe receive `notifications/resources/updated` when its document changes.
The stdio process checks only while subscribed; it starts no separate service.
Clients without resource discovery can call `acquire` with
`describe_connection=true` and their native startup token. This returns the
same public capability report, scoped to that session, without a selector or
leaf business call.

Tools and static resources use `acquire(need)` followed by `invoke(selection, arguments)`.
`invoke` performs their operation. A selected
resource advertises a closed empty-object schema and takes `arguments={}`;
the gateway already binds its URI. Skill and command guidance is delivered by
`acquire` and can be applied directly; its optional `invoke` also takes `{}`.
Both already reconcile the connection; a separate capability-report call is
for diagnostics, not a prerequisite for discovering a newly registered plugin.
The selector uses the same two-level engine as Skill routing: task roots, child
operation scopes, then the retained original capability metadata. Classification
runs after operator CLI registration/update, or explicit `refresh-directory`.
Exact metadata/template identities cache membership, including uncertain outcomes;
task decisions are never cached. Acquisition never starts metadata classification.
Unclassified or changed current metadata stops selection, without truncation or a
global Choice fallback. Removed, disabled and host-ineligible components are pruned.
The final threshold remains .65; directory and membership retention is .20.
A one-capability registry uses a final typed yes/no confirmation instead of a global
Choice. Other full-pool unions and pools over 96 capabilities abstain. Maximum three
selection calls share 36 seconds, with no retries. Source, session, permission and
schema checks remain fresh. Original description/name budgets remain unchanged;
a bounded MCP service name is additionally retained to disambiguate same-name tools.

Evidence has separate fields:

- `host_declaration`: adapter-supported receiver modes and lifecycle events.
- `received_host_handshake`: actual MCP client protocol, identity, capability
  offer and observed request methods. Identity does not prove native controls.
- `observed_host_events`: receipts from the bound native session. Events produced
  inside the gateway are not counted as native host events.
- `backpack_offer`: supported delivery modes; it never grants permission.

MCP initialization exchanges standard capabilities. An optional
`experimental.catmasterBackpack` offer can declare `connectorProtocols` and
`disabledDeliveries`. An explicit incompatible version or declined receiver is
rejected. An ordinary client uses the gateway default connector version; this
is reported as `gateway_default`, not an explicit host negotiation. No handshake
means `not_observed`. The connector version is separate from the MCP version.

Plugin MCP discovery records the actual producer initialization result, tool
schemas and static resources. Matching compares exact component kinds, delivery
modes, events, source snapshots and schema revisions. It does not guess adapters
for arbitrary components. Prompts and resource templates are explicit unsupported
producer features. Packages with unsupported components remain unavailable.

Each request reconciles the current registry. Registry and binding revisions
change independently. A new compatible plugin becomes available through the
existing tools on the next request and through the native bridge on future
events. A package with SessionStart initialization remains `pending_activation`
when added mid-session. Only a real subsequent SessionStart runs the applicable
startup handlers and activates that package; no startup event is fabricated.

SessionStart precedes MCP initialization on some hosts. At that boundary only
the adapter declaration is available. A received peer is associated with a
native session only after a valid startup token is supplied to discovery or a
gateway call. Explicit receiver declines then apply to that exact bound session,
including future Hooks; another session's peer cannot supply its capabilities.
Unavailable Hook delivery never removes registered PreToolUse restrictions:
dependent tool/resource bindings are unavailable, and direct execution checks
refuse dispatch. Old token generations cannot affect a resumed generation.
Startup-dependent PreToolUse checks also keep tools unavailable until initialized.
A failed new SessionStart revokes the previous token generation.

## Changes and permissions

`add --replace` explicitly rediscovers and registers a new snapshot, including
when package files are unchanged but the producer index needs a refresh. `unregister` removes its
registration while retaining package files, data and unknown receipts. Each
registration has a new generation, so removal/re-addition and version rollback
cannot restore old selection handles. Unrelated plugin registrations do not
invalidate existing handles. Changed source stops execution until explicitly
re-registered. Selection and cached results are scoped to a native token generation.

Matching is not execution approval. Native wrapper approval remains necessary;
supported leaf deny/ask rules and Hooks are checked separately. A discovery
report, subscription or new registration produces no leaf business RPC. Unknown
operations remain quarantined across tokens and plugin versions. Neither schema
discovery nor a fresh selection authorizes replay.

## Host scope

Adapters cover Claude Code, Pi, Qwen Code, Factory Droid, Hermes and local Codex
CLI/App Server. Local Codex requires native review/trust of the exact connector
Hooks. Configuration does not write trust state or bypass that review. Desktop
and cloud orchestration have separate verification requirements.

Portable support currently covers stdio MCP tools, static resources, Skill and
Markdown command guidance, and synchronous command Hooks for adapter-supported
events. Native menus, agents, LSP, UI, channels, workflows, prompt/agent/async Hooks,
remote/authenticated MCP transports and arbitrary dependency graphs require
specific adapters. Connecting once does not create host APIs that do not exist.
