# Cold-capability native Agent pilot

This pilot asks whether a native Codex Agent can discover, acquire and apply a
previously absent public capability through the installed Backpack gateway.
It is not a model-API simulation or a test of every marketplace package.

`run.py` freezes six ordinary Chinese tasks, two per family. The evaluator tells
the Agent only the family (Skill, plugin or MCP), never a capability, publisher,
repository or package name. This tests discovery *within* a requested family;
it does not test automatically deciding which family a user needs.

The [2026-10-14 live report](../../docs/backpack-market-blind-validation-2026-10-14.md)
records one complete new-capability success out of six planned tasks, including
an existing-capability selection, discovery failures and a plugin-resource gap.

Each case starts a fresh native conversation, a separate Agent home and a
separate Backpack store. The existing approved public source **metadata** is
copied; selected package caches, MCP registrations, Skill grants, invocation
receipts, frequent-use history and private Skills are not. By default the launcher and
standalone runtime are the installed versions. `prepare --launcher PATH` and
`--runtime-root PATH` select an isolated candidate and record its identity;
they do not change the daily connection. Passive proxies record exact
gateway traffic and Jev CLI output without changing candidates or decisions.

Known public native installation/cache roots and Backpack public registries are
captured before testing. A selected name already present is flagged. This is a
current installation audit, not proof that no copy has ever existed anywhere on
the disk. No private Skill catalog is enumerated. Artifacts, credentials and raw
receipts stay in owner-only evidence outside this repository.

The Agent uses existing ChatGPT login and the configured native model/effort.
Only the test Backpack server is preapproved for the user's authorized task;
other Apps, remote plugins and host Skill discovery are disabled in the test
profile. The native shell remains in its workspace-write sandbox without shell
network access. The MCP gateway can fetch anonymous public packages as in the
installed product; this is not VM isolation or a code-security audit. Missing
credentials, paid services and unsupported components stop that case.

## Acceptance and accounting

A whole case passes only when all relevant conditions hold:

1. The initial user need and pre-selection requests contain no capability name.
2. Backpack selects a suitable capability absent from the checked baseline.
3. Its actual package/service is acquired through Backpack in the test store.
4. The Agent actually uses it and checks the required artifact or service result.
5. The artifact satisfies the ordinary task and unrelated production state is
   unchanged. Skill use reports alone do not establish output correctness.

The six task artifacts are checked against the facts and explicit requirements
in their frozen prompts. The cart review must reproduce discounted shipping and
shipping charged to empty carts; a demonstrated large-integer precision defect
may also be reported. Quantity is not specified by this ordinary prompt. Time
conversion must use an actual service and return Tokyo 22:00 on 2026-07-01 with
New York UTC-04:00 and Tokyo UTC+09:00. The knowledge task must actually save and
read back its fictional relations. A plausible unaided answer does not pass the
Backpack path. The interactive page needs working controls, formula, reset and
JSON export; source code alone does not establish interaction correctness.

One native attempt per case, 360 seconds and an instructed 12 gateway-call
limit. All actual attempts, abstentions, startup failures and missing receipts
remain in the report. An infrastructure correction requires a distinct batch;
it never overwrites an earlier result. Unknown invocations are not replayed.

`summarize.py` separates native token usage from Jev usage. Cached input is a
subset of input, not additional tokens. Missing usage is unknown, not zero;
known subtotals and coverage remain visible. Native elapsed time includes its
startup, reasoning, discovery, package setup and task work. Corpus preparation
and evaluator review are outside this duration. Cost and server-side model
identity remain unknown unless directly returned.

`snapshot_gateway.py` supports an isolated old/new directory comparison. Both
arms share complete public source/exact-query snapshots, retaining their original
observation time. A previously unseen functional query is read from the normal
public source once and then frozen. This is a fixed-corpus evaluation, not proof
of live marketplace freshness; query differences and cold corpus reads must be
reported. Packages, grants, workspaces and business data stay fresh per case.
The wrapper excludes known installed public leaf names before disclosure and
retains the normal final guidance/schema, permission and execution checks.
Source snapshots are never installed packages or successful execution evidence.

## Run and inspect

Use an **outside-repository**, owner-only output path. Preparation copies the
existing native login locally; never upload that output directory.

```sh
python3 benchmarks/market-blind/run.py prepare --output /absolute/private/output --data /absolute/production/backpack
python3 benchmarks/market-blind/run.py run --output /absolute/private/output --case skill-update
python3 benchmarks/market-blind/summarize.py /absolute/private/output
python3 -m unittest discover -s tests -p test_market_blind_telemetry.py -v
```

Relevant references consulted: the [Codex configuration reference](https://developers.openai.com/codex/config-reference/)
documents per-server tool approval configuration; the [official MCP Registry API](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/api/official-registry-api.md)
documents name substring search, which must not be mistaken for semantic search.
The [native MCP execution issue discussion](https://github.com/openai/codex/issues/24536)
motivates observing actual MCP receipts instead of treating a completed CLI turn
as successful capability execution. These references are context; the local
receipts determine this pilot's results.
