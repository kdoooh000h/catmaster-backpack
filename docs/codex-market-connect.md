# On-demand market components in Codex

The public Backpack gateway now exposes `prepare_market_capability` and
`connect_market_capability`. Preparation sends public metadata to Jev and creates
one pinned, owner-only setup preview. Connection applies that receipt within the
user-authorized task. It does not invoke a business tool or grant account access.
The Agent need not ask the user again for setup already covered by their request.

## Flow

1. Try the connected Backpack capability for the concrete need.
2. If a suitable capability is missing, prepare a public market plugin or MCP.
3. Inspect the selected source, components, startup configuration and requirements.
4. Connect the exact receipt within the authorized task.
5. For plugin guidance, call `acquire_skill` with `market_selection` from connection.
   Jev selects only among that plugin's connected Skills. Without this argument,
   normal Backpack routing remains available. For MCP, use `acquire_mcp`, followed
   by the existing receipt-bound `invoke_mcp` after normal execution authorization.

Market lookup has at most source → publisher category → plugin selection. Sources
may be explicit. Publisher categories preserve every candidate; leaves are bounded
at 192 entries. An oversized or incomplete result asks for a more specific public
search instead of silently truncating. Subsequent Skill/tool acquisition is a
separate use request; it is not another market search. The public Skill directory
continues to use the previously verified source-directory/Skill policy.

## Supported sources and components

- The official MCP Registry and its official reference example. Public npm stdio
  packages resolve to a specific version; public Streamable HTTP is supported.
  The Registry search must fit one complete bounded page. Missing required fields
  return `setup_required`; secrets are not accepted in routing/setup tool arguments.
- Anthropic's public plugin marketplace, including its supplied categories.
  Repository-local plugin subtrees are downloaded at the inspected commit.
- OpenAI's directory through the installed Codex CLI, when its validated package
  files are locally available and native policy permits access.
- Portable plugin Skills and compatible MCP components. An absent plugin manifest
  may use standard component locations. Inherited license/notice files accompany
  copied Skills. Plugin MCP support covers credential-free HTTP and pinned npm
  commands; local scripts require native-host handling until the shared runtime
  can enforce package integrity at invocation.

Native apps, hooks, commands, agents, dependency plugins, settings, channels,
experimental components, marketplace component overrides, unsupported transports,
unpinned commands and missing login/configuration remain explicit requirements.
No partial plugin is reported as connected when these declarations are present.
This adapter does not emulate host events or implement OAuth.

## State and recovery

Plans bind the exact connection, project scope, package digest and pre-resolution
registry markers; previews expire in 15 minutes. Public Skill grants retain the
existing project scope. MCP grants are specific to the current connection.
The original registries are backed up before mutation. Packages and receipts stay
in the owner-only Backpack data root, not in the Git repository.

A durable `connecting` record precedes dependency setup and grant mutation.
An interrupted setup requires reconciliation rather than replay. Existing active
services are reused only with matching configuration/grants. Stable service
identity and setup history prevent new previews from sidestepping revocation or
unknown outcomes. A removed service requires management reconciliation. Completed
receipts only inspect their result, and they never restore revoked grants.

For npm, connection downloads dependencies with lifecycle scripts disabled, using
an isolated runtime home and a fixed argv command. This precedes the shared MCP
client's 30-second protocol startup limit. Setup has a 150-second bound; installed
package identity and lock metadata are checked before reuse. This is an installation
boundary, not an OS sandbox or a review of third-party code. Actual tool calls
retain the existing durable at-most-once invocation receipts.

The two registries cannot be atomically published together. If setup stops between
them, the plan remains `connecting`; inspect the backups and actual grants before
recovery. No automatic rollback hides partial state. The manager retains caches
and receipts; the gateway does not delete user data or install native hooks.
There are bounded plan, package, Skill and MCP limits. An owner can reconcile and
archive finished state through maintenance when these limits are reached.

## Installation and verification

Keep all six `market_*.py` adapter modules together: `market_gateway.py`,
`market_protocol.py`, `market_connect.py`, `market_routing.py`,
`market_resources.py` and `market_registry.py`.
The launcher still requires the separate existing standalone runtime via
`--runtime-root`. The runtime source is not bundled in this task branch.
Only the selected public MCP command changes; private routing and other Agent
connections are unchanged. A fresh process can verify the updated command before
Codex restarts, but does not prove the old chat has refreshed its tool inventory.

Run the adapter tests with:

```sh
CATMASTER_STANDALONE_RUNTIME=/path/to/standalone-backpack \
  python3 -m unittest discover -s tests -p 'test_codex_market*.py'
```

Without the environment variable, installed-runtime checks explicitly skip.

Protocol references: the [official MCP Registry API](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/api/official-registry-api.md),
[Claude plugin manifest specification](https://code.claude.com/docs/en/plugins-reference),
and [OpenAI plugin packaging guide](https://developers.openai.com/plugins/build/plugins).
Their catalogs/manifests describe availability and components, not successful task
execution. See the dated validation record for the tested scope.

## Discovery repair adapter

Source directories are judged as indexes that may contain useful children,
with the existing 0.1 directory threshold; final selection still requires at
least 0.7. Plugins have a plugin-specific question. No `none` result is converted
into a positive match and no capability names are inserted into user requests.

Public MCP discovery uses the official Registry only. Its name-substring API
receives one to four functional keywords combined with OR; all pages are read
and duplicate name/version pairs are reconciled. Limits remain explicit: six
pages per term, 192 distinct active candidates, an 80-second discovery budget,
35 seconds per read, one retry only for a failed anonymous GET. Native curl
negotiates HTTP/2 when available, disables curlrc, enforces HTTPS/TLS and a
response size limit; Python HTTPS is the fallback when curl is unavailable. Incomplete or
oversized results stop before final selection. This is bounded name discovery,
not a guarantee of semantic recall over the whole marketplace. Redirects and
TLS bypass remain prohibited. Dependency setup and business operations keep
their existing receipt and no-replay rules.

A selected market plugin may disclose a template or other file from its pinned
package through `acquire_resource`. It must pass current scope/grant, package
fingerprint, selected-path and work-copy checks. The adapter does not fabricate
an external Skill source registration or expose files from another package.
