# 00 Project Brief

Status: ACTIVE

## 2026-09-29 Model B Qualification Critic Shadow

SiliconFlow Qwen is now enabled locally as the bounded Model B Critic. The
single-model Qualification Projection is frozen unchanged as the baseline;
Model B receives only deterministically selected high-impact objects and writes
an independent immutable Shadow Result. It cannot mutate Qualification,
Product Truth, Claims, Strategy or external-action authority.

The current fixed nine-Run case deterministically selects seven Shadow objects:
six positive `SUPPORTS_PARTIAL` Citation bindings from Run 1 and the one current
Strategy Direction. Ordinary `RELATED_ONLY`, `NO_MATCH`, background facts and
ineligible public Claims are excluded. The release API and worker path are
implemented and the release database is migrated to `20260929_01`.

No real business payload has yet been sent to SiliconFlow. The attempted formal
start was stopped before task creation because external-data authorization must
explicitly cover the frozen Answer/source excerpts and Strategy dependency
payload. This is an authorization blocker, not a provider or implementation
failure.

A one-request synthetic canary used no project or customer data and passed the
configured endpoint, Qwen model identity and strict JSON Schema path (72 total
tokens). This proves transport connectivity only; it does not validate the
seven-object business Shadow or Model B judgment quality.

## 2026-09-29 Optional Model B Provider

The optional second semantic model is now configured as SiliconFlow Qwen. Its
default identity is `Qwen/Qwen3.6-35B-A3B` through SiliconFlow's OpenAI-compatible
Chat Completions API. DeepSeek remains Model A and no existing semantic stage is
rerouted.

The strict provider transport and bounded Shadow Critic contract are now
implemented. Model B remains unable to affect Qualification, Strategy, public
Claims or external actions until a later quality-based cutover decision.
See `docs/GEO_MODEL_B_SILICONFLOW_QWEN.md`.

## 2026-09-29 Automatic Qualification Checkpoint

The release path now has a read-only, exact-version qualification projection.
It evaluates admitted machine objects per intended use instead of treating a
global human Review as permission to continue all computation. Human Review is
an optional correction overlay; public claims and external actions retain their
own hard gates.

For the current real nine-Run case, the projection produces one grounded
Strategy Direction and one internal Execution Draft. The Answer scope remains
Runs 1-9 while Citation Contribution remains Run 1 only. Four manually
confirmed target-brand capabilities establish strategy applicability but still
need target-brand source references before they may appear as public claims.
No Strategy, Review, publication or other business row is written by this
checkpoint. See `docs/GEO_1_0_QUALIFICATION_VERTICAL_SLICE.md`.

## 2026-09-28 Current Delivery Baseline

- Fixed case: Analysis `19b0be0f-f794-4435-9fa7-2723257f26cc`, Context `ctx-f06aa92a-6193-4aa0-ab9b-e62974f594f4`, Runs 1-9.
- Answer Semantic: 9/9 valid, Result `diag-v1:cf81b3afcff72813`, Review `review-de74bccb-ad81-47e9-83e5-323baf1f147c`.
- Source Completion: 61 READY snapshots, 1530 passages, and 5 `WAIVED_WITH_LIMITATION` sources.
- Evidence Result `diag-v2:5435e5989f2a7c2f` is retained as `REASON_EVIDENCE_BASELINE`; it is not review authority for Citation Contribution.
- Current delivery is one deterministically selected real-Run P1: full AnswerUnit coverage, all-citation disposition, Citation Contribution, and human calibration. Strategy remains empty.
- P1 does not prove generation causality, does not treat SourceSnapshot as ManagedAsset, and does not infer OFFICIAL_SITE PRIMARY from Foundation.

GEO Platform is a local Alpha tool for auditing AI answer visibility, brand
presence, recommendation quality, and citation-source behavior.

The current production-like path is Wenxin web audit:

```text
Project -> Prompt -> Batch/Task -> BrowserMonitorRun -> ReferenceSource/RetrievalCandidate -> Analytics/Optimization
```

The product should help answer:

- Is the brand mentioned for a specific user question?
- Is the brand merely mentioned or explicitly recommended?
- Which sources are retrieved and cited?
- What concrete optimization action should be taken?
- Did a fixed retest show a measurable change after the action?

P0 is not a generic analytics BI system. P0 is the first trustworthy optimization
loop using existing real collection data.

## Single-Prompt Core V2 Delivery State

V2 is an isolated, incremental replacement path; it does not reinterpret V1
history or activate the generic Runtime RFC work.

```text
Slice 1: explicit Analysis/Task ownership + immutable AnalysisContext = delivered
Slice 2: recommendation/citation/truth diagnosis components + exact-version review = delivered
Slice 2 safety: strict V2 LLM admission + grounded consumption + read-only current eligibility = delivered
Slice 3: reviewed diagnosis -> evidence-constrained strategy candidate = delivered
Slice 4: confirmed strategy -> execution skeleton -> confirmation -> user-reported publication = delivered
Slice 5: exact publication -> frozen retest -> descriptive before/after comparison = delivered
Effect attribution / Experiment = not in V2 scope
```

Delivery status above describes implemented code slices, not a completed real
end-to-end workflow. A 2026-09-16 production-path audit found that the V2
second-slice implementation runs Answer Semantic before source content
completion and exposes no pre-diagnosis manual source-completion gate, despite
the second-slice contract placing the immutable SourceSnapshot set first.
Therefore V2 evidence diagnosis is currently:

```text
component implementation = delivered
source-first product workflow = NOT DELIVERED
real evidence E2E acceptance = BLOCKED
```

The source-first repair was approved through the R2 + R3 delivery contract and
is now implemented as the GEO 1.0 first-slice release path. Its dedicated app,
release migration, source-preparation workspace, immutable manifests and exact
Evidence gate are engineering-accepted. The formal release database is separate
from the legacy development database and contains only the approved first-slice
allowlist.

Source Preparation now reuses the established rendered-page/HTTP-fallback fetch
kernel through an explicit V2 adapter. The kernel does not own workflow state:
only the exact Analysis/Context/Citation Manifest can queue work, and only V2 can
admit fetched text into immutable snapshots. Automatic acquisition runs first;
failed, partial or blocked pages become visible manual-completion items and are
never automatically waived. The corrected real resample has now accepted this
integration: 46 frozen sources produced 30 immutable AUTO_FETCH snapshots and
16 MANUAL_REQUIRED items, with zero automatic waivers. The remaining manual
items still block Source Completion and Evidence.

Sampling is now a Prompt-level record pool rather than an implicit one-time
Analysis prerequisite. The release UI pages through every Run for the exact
Project/Prompt, and a user may freeze an explicit `run_ids` set into a new
immutable AnalysisContext without starting a browser task. New sampling does not
rewrite existing analyses; an existing analysis remains resumable at its source,
answer-review or evidence gate. Failed Runs can be retried as a new Run attempt,
while the original Run and every Context that references it remain unchanged.
This restores the mature monitoring executor and source fetcher behind explicit
V2 ownership instead of duplicating their behavior or restoring legacy workflow
control.

This does not mean the real positive evidence chain is complete. The first
release acceptance remains immutable and ineligible because its answer text
mixed Wenxin search/thinking content. Corrected Analysis
`92bb12a5-edcc-43c7-b848-ca60267a2672` stores only final Markdown, freezes a new
46-source Citation Manifest and has 30 qualified source snapshots. Its remaining
16 sources still require human disposition; no Answer Review, Completion
Manifest or Evidence result was created by the resample/source-fetch run.
See `docs/GEO_1_0_FIRST_SLICE_OPERATIONS.md` for the executable workflow and
`docs/GEO_1_0_R3_EXECUTION_CONTRACT.md` for the frozen boundary.

As of 2026-09-21 the current release database has 9 real Runs and 4 immutable
Analysis/Context versions. It has no current DiagnosisExecution, ResultVersion
or Review row. Earlier acceptance notes that reference three zero-event Answer
results describe an older release state and cannot be used as the current
Evidence input. The active blocker remains 16 unresolved source dispositions
plus creation and exact-version review of a current Answer Result.

The fixed #44 production result is
`diag-v1:1449c44916fe5c55`. It has four grounded recommendation Reasons, 30
reference observations / 29 source identities, an empty target-brand Truth
snapshot with four `UNRESOLVED` relations, and no human review. Retrieval and
independent-session proof remain unavailable. The one-time external authorization
covered only Prompt/answer semantic extraction; page-content SourceClaim and
Alignment work remains explicitly not evaluated.

The immutable #44 result continues to report 25 technically successful content
snapshots. A current read-only safety projection blocks one verification page,
so effective evidence-ready content is at most 24; this upper bound does not
claim that all remaining content is quality verified. Strict V2 LLM admission
is locally validated, while real-provider injection resistance and external
SourceClaim/Alignment remain not verified.

The third slice introduces an A/B/C readiness contract before strategy
creation. Unreviewed or reviewed-but-ineligible input produces an explicit
readiness report and no empty candidate. Foundation and channel intervention
are independent; zero PRIMARY is valid; TEST remains a non-causal hypothesis.
The fixed #44 result is currently class A with no review, Foundation UNKNOWN
and zero qualified directions, so no real #44 strategy was created. Positive
B/C behavior is fixture-validated only.

The fourth slice adds deterministic execution content skeletons, asset production
briefs, immutable proposal revisions, append-only confirmations and user-reported
publication history. Foundation publication surfaces never create a channel Role;
only FULLY_COVERS confirmed Truth may enter PUBLIC_CONTENT; the current real asset
path is CREATE_NEW only. Baseline comes exclusively from the exact immutable V2
AnalysisContext. #44 remains blocked before strategy and has zero fourth-slice
objects; the complete positive execution/publication chain is fixture-validated,
not yet verified on a real accepted V2 strategy.

The fifth slice adds an exact historical-publication retest path with frozen
Prompt, planned Run identities, a separate measurement identity and independent
browser/LLM authorization. It reports Run-level brand mention, V2 semantic
recommendation, target official-reference and exact published-URL reference
metrics with explicit denominators, unknowns and per-metric comparability. Values
are descriptive observations only; no result can claim causal lift, channel
effectiveness or strategy success. #44 remains blocked before strategy and has no
retest object. The positive fifth-slice chain is fixture-validated; no real
external retest or semantic call was authorized.

Target-brand capability presence and public-claim eligibility are separate
gates. An atomic `SUPPORTED` capability may be manually confirmed without an
immediate source reference and may be used to test target applicability during
Strategy qualification. It remains `statement_eligibility=VERIFY_FIRST` until
target-brand provenance is supplied, and Execution must reject it from titles,
public sections and asset claims. `PARTIALLY_SUPPORTED`, unknown, compound or
semantically broader statements do not receive full coverage automatically.

The release flow now continues through V2 Strategy Candidate generation and
append-only Strategy Review. A compound grounded Reason is strategy-eligible
only when every atomic capability in that Reason has an exact manually confirmed
`SUPPORTED` fact; partial confirmation stays `UNRESOLVED` and reports the missing
capabilities. This aggregate eligibility does not make any source-free capability
publishable. Execution Proposal, Publication and Retest remain outside the active
release route surface.

As of 2026-09-22 the fixed nine-Run analysis has explicit completeness
projections for input scope, Answer computation, exact-result review, Evidence
planning and Strategy dependencies. The immutable input contains Runs 1-9, but
the currently selected result has valid Answer semantics only for Runs 4/5/6;
Runs 1/2/3/7/8/9 are pending external authorization, not model failures and not
zero-event results. Prior exact judgments may be shown as provenance-prefill,
but a new complete ResultVersion still requires an exact review.

Evidence candidate planning is now deterministic and same-Run scoped. It uses a
stable BM25 order, explicit-anchor priority, source diversity, boundary ties, a
12-candidate per-Reason cap and a predeclared technical-failure fallback queue.
The plan ID/hash/version is frozen in the Evidence input binding before worker
execution and rechecked by the worker. Legal zero results, pending authorization
and semantic uncertainty do not trigger fallback. Strategy continues to expose
locally qualified directions for inspection, but no partial direction may be
presented as a conclusion over all nine Runs or create a formal candidate under
the current full-scope creation contract.
