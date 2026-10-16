# Broader recall and independent suitability: partial gains, excessive cost

The experimental candidate improves strict success from **1/15 to 5/15** on
ten previously failed requests plus five new ones. All **10/10 later reference
requirements** survive, up from 7/10. However, seven requests still lose a
primary current reference, and token cost on the same three live pairs rises
to **7.96 times** baseline. **Do not promote this candidate to daily runtime.**

Three additional selected capabilities appear relevant on post-hoc metadata
review but were outside the frozen accepted sets. They remain failures in the
published strict score. This reveals a limitation in the reference sets as well
as the retrieval/selection problems; it does not justify rewriting the test
after seeing answers or claiming those capabilities executed the task.

## Changes tested

The baseline is the prior Word-alias and coverage-final strategy. Existing
sources and fixtures remain unchanged. The candidate adds general mechanisms,
with no new task-specific keyword list or reference-ID injection:

1. **Open lexical search.** Every raw clause can search names, descriptions and
   existing category labels across Skill, whole-plugin and MCP kinds. A request
   no longer needs to match one of the predefined object categories first.
   Exact short catalog-name matches get an additive path; this recovers literal
   product mentions such as GitHub without a manually curated name list.
2. **Local multilingual semantic search.** A pinned sentence encoder searches
   the full raw request and each clause independently. Three neighbors per kind
   and query, including boundary ties, join the existing pool. Original and
   later-step candidates are never removed. The larger experimental pool has a
   256-entry stop, compared with the baseline's 96; it is not silently truncated.
3. **Independent current-step judgments.** One Jev request contains a separate
   Choice for each retained candidate: explicit current support, partial/unknown,
   or later/unrelated/conflicting support. Each selected candidate must receive
   the provider's current-support choice at confidence **at least 0.7**. Among
   eligible candidates, provider confidence, current-support probability and
   original retrieval order determine the returned choice. All other candidates
   remain available. No probabilities are summed, and no second Jev call is made.

The numerical threshold stays 0.7, but its meaning changes: independent
suitability is different from being the unique best option among many
alternatives. This is not evidence of equal calibration. The
[TypeSafe primitive documentation](https://docs.typesafe.ai/primitives) supports
independent questions in a shared request, while its
[confidence documentation](https://docs.typesafe.ai/confidence) explains that
Choice confidence reflects the distribution across the supplied options.

The local model is
[paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2),
pinned at `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`, with 384-dimensional
normalized embeddings. It receives original text, with no task-specific English
summary. Embeddings use the model's 128-token window; full descriptions still
reach Jev. Its
[documented semantic-search use](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html)
motivates the experiment, not a guarantee that it preserves all relevant items.

## Low-cost checks and rejected approaches

Before any Jev calls, the ten known failures were used as development cases.
The five new scored requests were withheld from this tuning. Their strings were
written before reference inspection, and references were fixed before recall.

- `intfloat/multilingual-e5-small` was tried first. Its local development recall
  remained poor at 3, 6 and 12 neighbors per kind. Some unrelated Chinese
  descriptions outranked appropriate English descriptions. This observation is
  specific to this snapshot, model revision and setup; it is not a claim that
  the model always fails cross-language retrieval.
- The selected model passed two of three simple alignment probes. One repository
  probe marginally preferred enterprise content over GitHub content. That failed
  probe is preserved. Actual full-catalog checks gave better coverage than the
  first model. Increasing neighbors from 3 to 6 or 12 added many candidates but
  no further completely covered development cases, so 3 was retained.
- A local Chinese-to-English translation branch using the documented
  [OPUS-MT model](https://huggingface.co/Helsinki-NLP/opus-mt-zh-en) produced
  concrete mistranslations, including an unrelated temporary-folder error
  sentence for a meeting prohibition. It is rejected, not used in the live
  candidate, and never sent as a substitute task to Jev.

The first model's index build took 136.373 seconds; the selected index took
115.508 seconds. These are one-time local setup costs and are not hidden inside
the warm latency comparison. Models and optional dependencies were installed
only in the task evidence environment, without adding a service or modifying
daily Agent connections. No external embedding or translation API was used.

## Frozen comparison and outcome

The catalog is unchanged at 45,325 public entries: 682 Skills, 628 whole plugins
and 44,015 MCPs, including the already-declared 376 historical control Skills.
Markets remain merged and deduplicated. Plugins are not split into Skills.

The ten failures from the previous twelve-request run are reused verbatim;
the two passing requests are excluded. Five new needs cover financial runway,
API contracts, incident response, academic search and weather forecasts. A sixth
authored localization request is retained in the request file but was withheld
before recall because the inspected metadata did not provide a defensible
full-scope reference. It is not counted as a pass, failure or executed test.

Success requires a predeclared acceptable current selection at 0.7 or higher,
all required later reference groups and **every primary reference anchor** to
survive. This conservative anchor requirement is also used for preflight: a
known omission receives no Jev call but remains in the denominator. That is a
benchmark safeguard using reference labels, not a production mechanism that can
detect every unknown omission. References describe metadata relevance, not
readiness or verified execution, and are not an exhaustive list of equivalents.

| Scored request | Baseline | Candidate |
| --- | --- | --- |
| Local browser/modal tests, then code review | Current/later omitted | Pass 0.95 |
| Distinctive responsive dashboard | Abstain 0.36 | Unlisted frontend-design alternative, 0.98 |
| Accessibility review, then Word handbook | Abstain 0.26 | Pass 0.80 |
| Root-cause workflow, then Word findings | Current omitted | Current omitted |
| Kubernetes release plan, then dependency review | Current omitted | Pass 0.86 |
| Search-friendly article | Current omitted | Current omitted |
| Current library docs, then code review | Current/later omitted | Current omitted; later restored |
| Public page navigation/screenshots, then spreadsheet | Current omitted | Current omitted |
| Public GitHub inventory, then code review | Current omitted | Unlisted read-only GitHub alternative, 0.95 |
| Date-aware time-zone conversion | Current omitted | Current omitted |
| **New:** financial runway, then slides | Current omitted | Unlisted cfo-advisor alternative, 0.85 |
| **New:** API contract review, then Word handbook | Later omitted | Pass 0.85 |
| **New:** incident response plan | Pass 0.95 | Pass 0.98 |
| **New:** scholarly paper lookup | Current omitted | An alternative survives; primary omitted |
| **New:** weather forecast, then spreadsheet | Current omitted | Current omitted |

Both strategies run fresh; the earlier failures are not substituted for fresh
baseline responses. All fifteen needs remain in the score:

| Measure | Baseline | Candidate |
| --- | ---: | ---: |
| Strict total success | 1/15 (6.7%) | 5/15 (33.3%) |
| Previously failed subset | 0/10 | 3/10 |
| New subset | 1/5 | 2/5 |
| Completely retained reference groups | 3/15 | 9/15 |
| Completely retained primary anchors | 3/15 | 8/15 |
| Required group occurrences retained | 11/25 | 19/25 |
| Primary anchor occurrences retained | 11/25 | 18/25 |
| Later requirements retained | 7/10 | 10/10 |

The new-case result is bounded evidence of some generalization, not a robust
accuracy estimate. Two new current anchors and one accepted incident alternative
are explicitly historical control Skills. Capability kinds describe reference
strata, not forced selection types; the incident request selects the accepted
incident-commander Skill in both arms.

## Three unlisted alternatives

These remain outside the frozen score:

- The dashboard selection is another `frontend-design` entry whose description
  explicitly promises distinctive, polished frontend interface code. The frozen
  Skill reference also survives and receives 0.72 suitability confidence, while
  the selected alternative receives 0.98.
- The repository selection describes read-only GitHub repositories, issues,
  pull requests and commits. The original GitHub reference survives and itself
  receives 0.76; the read-only alternative receives 0.95.
- The finance selection explicitly describes cash management, runway and
  financial models. Its metadata plausibly supports the need, but the accepted
  set only named financial-analyst.

This is an author post-hoc metadata review, not an independent review or a new
execution test. It explains why a strict reference miss is not automatically
proof of a functionally wrong selection. Future tests need broader equivalence
sets fixed **before** calls; this run does not inflate its result to 8/15.

## Token and time comparison

All **11 actual calls**, **222,596 tokens** and 30 result rows reconcile, with
no retries, missing usage, errors or unknown sends. The predeclared ceiling was
30 calls, 400,000 tokens, 240 seconds and 20 seconds per call. Each eligible
need uses one request, but the independent candidate packs many judgments into
that request. One request is therefore not the same as low token cost.

Costs below compare only the **same three needs dispatched in both arms**:
dashboard, accessibility and the new incident response plan.

| Mean per paired need | Baseline | Candidate | Change |
| --- | ---: | ---: | ---: |
| Tokens | 2,809 | 22,354.3 | +695.81% (7.96x) |
| Input tokens | 2,465.3 | 19,062.3 | +673.22% |
| Output tokens | 343.7 | 3,292 | +857.90% |
| Retained candidates | 36.3 | 89 | +144.95% |
| Local retrieval seconds | 0.038 | 0.119 | +213.42% |
| Final-dispatch seconds | 0.569 | 0.738 | +29.72% |
| Warm selector seconds | 0.606 | 0.856 | +41.22% |

The cost increase has two observed sources: a larger candidate pool and repeated
per-candidate question criteria/answer distributions. The whole candidate arm
uses 214,169 tokens for eight dispatched needs; baseline uses 8,427 for three.
Those totals are not presented as equal-coverage cost comparisons. Known offline
failures are never treated as successful zero-cost model calls.

Warm timing combines fresh local retrieval with each final dispatch. The pinned
local model/index load and checks take 6.593 seconds, separately from the index
build above. Embedding input is limited to 128 tokens, a retrieval limitation
for longer descriptions even though Jev sees full metadata. No claim
is made about full Agent-task time/tokens, monetary cost, actual task execution,
or the unobservable Jev backend revision. One run does not establish stable
latency.

## Acceptance and preservation

Thirteen focused offline checks pass: additive recall, all-clause/later coverage,
kind filtering, literal-name and unknown-domain search, boundary ties, over-wide
stops, raw task/full metadata retention, independent judgments, the 0.7 boundary,
one-call behavior, budget-before-send and unknown-send no-replay. An initial
synthetic runner fixture omitted candidate names; it was corrected before
freezing or live calls. The receipt analyzer locally revalidates all saved
responses and checks source/input/model/index locks, mapping, grades and usage.

All 459 protected files and both other worktrees' HEAD/status match fresh
post-test snapshots. Daily installation, lifecycle features and the concurrent
upgrade are unchanged. No capabilities were installed or executed by the
benchmark. The candidate remains isolated and **fails the no-omission and cost
requirements**. Retain the retrieval and evaluation findings for further work;
do not replace daily selection with this full-pool independent-judgment design.

Artifacts: [results](../benchmarks/results/backpack-semantic-recall-2026-10-16.json),
[offline exploration, including rejected methods](../benchmarks/results/backpack-semantic-prechecks-2026-10-16.json),
[new requests](../benchmarks/directory-depth/semantic_new_requests.json),
[references and pre-test exclusion](../benchmarks/directory-depth/semantic_new_references.json),
[retrieval](../benchmarks/directory-depth/semantic_recall.py),
[independent final](../benchmarks/directory-depth/independent_current.py),
[runner](../benchmarks/directory-depth/semantic_experiment.py),
[receipt analyzer](../benchmarks/directory-depth/analyze_semantic_experiment.py),
[optional isolated dependencies](../benchmarks/directory-depth/semantic-requirements.txt).
