# On-demand market components in Codex

The public Backpack gateway now exposes `prepare_market_capability` and
`connect_market_capability`. Preparation sends bounded public metadata and selected component instructions to Jev and creates
one pinned, owner-only setup preview. Connection applies that receipt within the
user-authorized task. It does not invoke a business tool or grant account access.
The Agent need not ask the user again for setup already covered by their request.

Standalone Skills are read on demand through `acquire_skill`; their selected
instructions and resources may be cached, without installing a plugin in the
host Agent. A Skill that uses scripts still needs its declared runtime. Plugins
must first be installed and registered in Backpack before their components can
be acquired. MCP must first be registered in Backpack: local services have their
dependencies installed there, while remote services have their connection saved.
Registration alone does not establish a successful handshake or business call.

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

- The official MCP Registry and its official reference example. Public npm and
  supported PyPI stdio packages use specific versions; public Streamable HTTP is
  supported. A Registry search must fit the complete bounded pagination limits. Missing required fields
  return `setup_required`; secrets are not accepted in routing/setup tool arguments.
- Anthropic's public plugin marketplace, including its supplied categories.
  Repository-local subtrees and external public GitHub sources (`github`, `url`,
  `git-subdir`) are downloaded at an inspected commit. A supplied SHA takes
  precedence over a branch/tag; catalog and package commits are recorded
  separately. Unsupported hosts/source types and native components remain
  explicit requirements. No marketplace installer or repository script runs.
- The publisher marketplaces `wshobson/agents` and `trailofbits/skills`, plus
  registered public Claude-format community markets. They use the same pinned
  package, manifest, independent-component and grant checks. The adapter adds its
  two public indexes only in its own process; it does not rewrite user source
  registrations. Agent setup arguments cannot add arbitrary repositories.
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
A mixed package can expose an independently usable Skill while its hooks,
commands, agents, LSP and output-style extras remain explicitly unavailable.
Preparation reads the full selected Skill and its explicitly linked local Markdown
references before a strict fit decision. Only that validated Skill is granted;
uninspected siblings are not enabled. The result labels `portable_components`,
lists `unavailable_components` and records the unvalidated Skill count. Dependency
plugins, credentials, settings and required app integrations still block setup.
Root contributor `CLAUDE.md` alone is not a runtime dependency. This adapter does
not emulate host events, native subagents, commands or OAuth.
An explicit diagnosis-only request can use applicable diagnosis phases while
omitting later edits or commits; it cannot omit a mandatory unavailable runtime
dependency. Archive extraction materializes a direct in-subtree regular-file
alias as a regular copy. It creates no filesystem symlink and rejects absolute
or parent paths, link chains, missing targets, directories and expanded-size
overflow; inherited notices remain present.

## State and recovery

Plans bind the exact connection, project scope, package digest and pre-resolution
registry markers; previews expire in 15 minutes. Public Skill grants retain the
existing project scope. MCP grants are specific to the current connection.
The original registries are backed up before mutation. Packages and receipts stay
in the owner-only Backpack data root, not in the Git repository.

For the same connected plugin task, `acquire_skill` can omit `need` and retain
the exact prepared need. A single selected component's successful full-content
fit is reused only after package, entrypoint, grants, project scope and current
threshold checks. A changed need or stricter threshold receives a fresh actual
guidance check; it is not reranked from a lone metadata summary. This does not
authorize execution or turn a prior negative decision into a positive one.

A durable `connecting` record precedes dependency setup and grant mutation.
An interrupted setup requires reconciliation rather than replay. Existing active
services are reused only with matching configuration/grants. Stable service
identity and setup history prevent new previews from sidestepping revocation or
unknown outcomes. A removed service requires management reconciliation. Completed
receipts only inspect their result, and they never restore revoked grants.

For npm, connection downloads dependencies with lifecycle scripts disabled, using
an isolated runtime home and a fixed argv command. This precedes the shared MCP
client's 30-second protocol startup limit. Setup has a 150-second bound; installed
package identity and lock metadata are checked before reuse. The pinned package's
unique declared Node entrypoint runs by its real path, without an npx symlink or
runtime download. This supports packages whose main-module guard otherwise exits
before MCP initialization. Changed identity, undeclared/escaping entrypoints and
non-Node executables stop explicitly. Existing service configurations are not
silently rewritten. This is an installation
boundary, not an OS sandbox or a review of third-party code. Actual tool calls
retain the existing durable at-most-once invocation receipts.

For PyPI, an existing `uv` and Python are required. Only fixed versions on the
public PyPI index, standard stdio, no publisher runtime/package arguments and
one installed console entrypoint are supported. A declared uvx form
`--from SAME_PACKAGE[extras] ENTRYPOINT` is also supported: bounded extras are
applied to that same pinned distribution and the entrypoint must belong to its
installed metadata. These fields never become arbitrary installer flags.
Connection creates a dedicated
virtual environment under Backpack, installs wheels only (no source builds or
Python downloads), and checks package identity and entrypoint metadata without
importing the package. A clean task home and environment are used. Each process
start verifies the environment fingerprint before executing the entrypoint;
Python bytecode writes are disabled. Setup has a 150-second bound and existing
incomplete environments require reconciliation, not reinstall. No system Python,
global host configuration or shared Agent installation is changed. These checks
do not constitute a security review of third-party code or an OS sandbox.
If the selected distribution's installed source imports v1-only
`mcp.server.fastmcp` and dependency resolution installed MCP SDK 2+, the adapter
re-resolves the same fixed package inside its own environment with `mcp<2`.
Conflicting publisher requirements fail explicitly; package source and global
Python are not rewritten. This targeted compatibility rule does not establish
that an arbitrary package will start or perform the task.

The two registries cannot be atomically published together. If setup stops between
them, the plan remains `connecting`; inspect the backups and actual grants before
recovery. No automatic rollback hides partial state. The manager retains caches
and receipts; the gateway does not delete user data or install native hooks.
There are bounded plan, package, Skill and MCP limits. An owner can reconcile and
archive finished state through maintenance when these limits are reached.

## Installation and verification

Keep all eleven `market_*.py` adapter modules together: `market_gateway.py`,
`market_protocol.py`, `market_connect.py`, `market_routing.py`,
`market_resources.py`, `market_registry.py`, `market_packages.py`, `market_python.py`,
`market_node.py`, `market_registry_cache.py` and `market_mcp_runtime.py`.
The launcher still requires the separate existing standalone runtime via
`--runtime-root`. The runtime source is not bundled in this task branch.
Only the selected public MCP command changes; private routing and other Agent
connections are unchanged. A fresh process can verify the updated command before
Codex restarts, but does not prove the old chat has refreshed its tool inventory.

Run the adapter tests with:

```sh
CATMASTER_STANDALONE_RUNTIME=/path/to/standalone-backpack \
  python3 -m unittest discover -s tests -p '*market*.py'
```

Without the environment variable, installed-runtime checks explicitly skip.

Protocol references: the [official MCP Registry API](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/api/official-registry-api.md),
[Claude plugin manifest specification](https://code.claude.com/docs/en/plugins-reference),
and [OpenAI plugin packaging guide](https://developers.openai.com/plugins/build/plugins).
Their catalogs/manifests describe availability and components, not successful task
execution. See the dated validation record for the tested scope.

## Discovery repair adapter

Source directories are judged as indexes that may contain useful children,
with the existing 0.1 directory threshold. MCP setup-candidate ranking uses that
same disclosure threshold: it chooses a bounded setup preview, not a usable tool.
Every candidate retains its supported setup/required-fields context; unavailable
entries are labeled, not silently dropped. Connection validates and installs the
selected configuration within the task's existing authorization.

After connection, newly started market runtimes rank connected services and tools
with the provisional directory threshold. Tool ranking reuses the actual complete
schemas from the same `tools/list` response (at most 96,000 characters), without
an extra listing or a truncated candidate prefix. Then `acquire_mcp` checks the selected **actual tool description and full input schema** with Jev.
This final fit must reach at least 0.7, or the stricter configured value, before
creating the normal staged selection receipt. A completed negative fit removes
only that leaf and reranks all remaining candidates, within three leaves and a
40-second selection budget. Rejected and unexhausted candidates remain explicit.
Provider errors and unknown outcomes stop without selecting another leaf.
The legacy no-captured-schema fallback validates after receipt creation; a
rejected fallback receipt remains inspectable but expires immediately and is not
returned to the Agent.
The gateway reuses matching staged validation bound to the need, selection and
actual schema while checking the current threshold; it does not call Jev twice.
Healthy legacy services are reused and still receive gateway final validation.
The adapter does not silently stop or replace them. An identity mismatch stops
for reconciliation. The original runtime still owns invocation and receipts.
Fit means a reliable useful operation toward the task, including a documented
read-only prerequisite such as learning stored vocabulary or identifiers; a
single tool need not cover every step or requested output. The Agent must obtain valid inputs and
complete the remaining steps before reporting success.
Oversized schemas stop explicitly instead of silently truncating. Existing
invocation grants, at-most-once receipts and unknown-outcome handling remain.
This distinguishes willingness to inspect/install from confidence in the actual
operation. It does not claim that setup or a selection score proves task success.
Plugins retain their plugin-specific question and final threshold. No `none`
result is converted into a positive match and no capability names are inserted
into user requests.

Public MCP discovery uses the official Registry only. Its name-substring API
starts with one precise functional keyword. Up to four alternatives use OR.
Selectable results require complete pagination and reconciled name/version pairs.
A term already exceeding 192 active identities stops early with an explicit
broad-search result; no truncated prefix is passed to Jev. Limits remain explicit: six
pages per term, 192 distinct active candidates, a 26-second live search budget,
12 seconds per read, one retry only for a failed anonymous GET. Native curl
negotiates HTTP/2 when available, disables curlrc, enforces HTTPS/TLS and a
response size limit; Python HTTPS is the fallback when curl is unavailable. Incomplete or
oversized results stop before final selection. This is bounded name discovery,
not a guarantee of semantic recall over the whole marketplace. Redirects and
TLS bypass remain prohibited. Dependency setup and business operations keep
their existing receipt and no-replay rules.

Complete query snapshots are stored owner-only and can be reused for five minutes.
On a confirmed Registry read outage, an exact-query snapshot up to 24 hours old
can be used only after refreshing every cached service against its official latest
detail endpoint (at most 12 names, four workers, a separate 30-second budget).
If any detail cannot be checked, selection stops. The result exposes its original
snapshot time, age, exclusions and `complete_at_snapshot` coverage: newly added
services may be absent. A cache never claims a fresh complete market scan. Other
cached functional query labels may be offered as explicitly historical hints;
capability names are not injected into the user's request.

Plugin preparation inspects at most three publisher categories and 16 packages;
a 90-second deadline is checked between operations, not a hard cancellation of
an in-progress network/model call. Known incompatible packages can be skipped
with explicit reasons, while network/unknown failures stop. Pinned archives are
reused within the preview. Low-confidence metadata abstention may inspect all
positive alternatives only when the entire set fits the remaining bound; final
actual-content validation still requires at least 0.7. Unexhausted candidates
remain explicitly unexhausted.

With multiple public markets and automatic source choice, preparation can probe
up to four sources, eight packages each, within one shared 90-second budget
checked between operations. Explicit source requests stay in that source.
Confirmed anonymous catalog rate rejection is recorded without retrying that
source; another registered index may still be usable. Other source/provider
errors stop. A successful metadata ranking retains every candidate in the same
call's order for subsequent package inspection, avoiding repeated full-catalog
requests; actual component fit still needs at least 0.7.

Complete Claude-format catalog snapshots are owner-only, bound to the registered
source ID/repository/commit, and usable for 15 minutes without changing their
original timestamp. Cached results expose `complete_at_snapshot` and may omit
newly added entries. Expired, malformed, mismatched or symlinked snapshots are
not used. There is no stale-cache or network-error success claim.

Python environment mechanics follow the [uv environment documentation](https://docs.astral.sh/uv/pip/environments/)
and [CLI flags](https://docs.astral.sh/uv/reference/cli/). Package descriptions
and registry entries are not proof of successful invocation.

A selected market plugin may disclose a template or other file from its pinned
package through `acquire_resource`. It must pass current scope/grant, package
fingerprint, selected-path and work-copy checks. The adapter does not fabricate
an external Skill source registration or expose files from another package.
