# Codex public-market activation evidence

Local date: 2026-10-13. Policy: `market-descriptions-v1`.

## Scope and source state

The existing native Codex public connection had no whole-source activation
registry. Seven existing built-in public sources were enabled through the
standalone source manager after anonymous, commit-pinned metadata inspection:

| Source | Supported Skill entries |
| --- | ---: |
| Anthropic | 19 |
| Microsoft | 207 |
| Vercel | 9 |
| Cloudflare | 18 |
| Expo | 25 |
| Hugging Face | 26 |
| Supabase | 2 |
| Total | 306 |

Microsoft had three unsupported metadata entries, retained as source issues.
The OpenAI repository fetch was rate-limited and was not activated. Enabling
sources created no full package caches; selected packages were fetched later.
Ranking entries and arbitrary marketplace sources were not globally enabled.
This rollout does not install all market plugins or configure arbitrary MCP
services. The MCP example below acquired development guidance, not a service.

## Problem and checks

The former first-stage directory labels contained path fragments and member
names but omitted publisher and purpose. Three requests (Chinese React review,
English React review, Chinese MCP development) stopped as uncertain at 0.58,
0.45 and 0.56. A threshold-only isolated experiment selected a webpage runtime
performance Skill for a code-review request; that was not accepted as success.
Adding source descriptions selected suitable guidance in two isolated cases.
These small trials do not establish superiority or omission-free accuracy.

Eight adapter checks passed. Another 63 existing standalone checks passed with
the adapter class substituted: public routing, source revocation, project scope,
resource access, connection behavior, work copies and use reports. An initial
fresh-process startup failed before initialization because the imported runtime's
sibling script directory was absent from the module search path. The adapter
now includes that path; a startup regression and real protocol run pass.

## Installed, fresh-process results

The tests invoked the exact updated command from the native Codex configuration,
using the existing connection descriptor and real Jev routing. No model selection
was mocked in these rows.

| Request | Selected market Skill | Directory / final confidence | Complete acquisition |
| --- | --- | --- | ---: |
| English React review | Vercel React best practices | 0.95 / 1.0 | 2.554 s |
| Chinese React review | Vercel React best practices | 0.89 / 1.0 | 4.959 s |
| Chinese MCP example | Microsoft MCP builder | 0.65 / 1.0 | 58.927 s |

Acquisition times include package retrieval and process startup, not completion
of the business task. The Microsoft first acquisition was slow despite 2.147 s
of reported Jev selection time. Full token/cost totals were not collected.
The installed three-case sample selected suitable guidance 3/3; it is not an
estimate for all 306 entries. Earlier unsuccessful attempts remain in the local
evidence. The provider's actual remote model identity is unobservable.

The Vercel entrypoint and its parallel-request reference were actually acquired.
An optional memoization reference request abstained; no alternate file was read
to bypass that decision. Codex applied the selected guidance to a synthetic local
example. Node checks verified concurrent request starts, stable result ordering
and four equivalent filter results. No external HTTP calls were made. React
browser rendering was not tested. The same stable run recorded `started` and
`completed` through Backpack; these are Agent reports supported by the separate
local output check, not independently attested runtime events.

## Activation, recovery and remaining limits

Only the selected MCP server's argument array changed in native configuration.
The previous bytes were backed up privately. The new launcher was copied into a
versioned local release directory and verified against source. The old standalone
runtime remains a dependency; none of its existing files or the dirty main
checkout were edited. Saved/private Skill authorization and the MCP service
implementation remain with their existing gateways.

The already-running conversation still answered through the old gateway, without
the new routing-policy marker. Its post-config check abstained at 0.48. Restarting
Codex is required before claiming this conversation loaded the new entrypoint.
Fresh-process verification above does not establish an in-app reload.

Recovery can restore only the original server argument array from the private
backup after checking for concurrent edits. The seven added source grants can
be disabled through the source manager; package caches and outputs remain.
Do not overwrite the whole native config if it has since changed. No background
test service was created. Source snapshots, raw receipts and config backups stay
outside Git because receipts/configuration can contain credentials.
