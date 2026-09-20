# Single-Prompt Core V2 Second Slice

Date: 2026-09-11
Decision: `SPC-V2-SLICE-002`
Scope: recommendation semantics, citation diagnosis, target-brand truth relation and exact-version review.

> **Implementation divergence notice (2026-09-16):** the flow below correctly
> places the immutable SourceSnapshot set before recommendation diagnosis, but
> the current production implementation executes Answer Semantic first and has
> no Analysis-owned source completion/manual supplementation gate. Do not treat
> this slice as source-first end-to-end accepted. The proposed remediation is
> `SINGLE_PROMPT_CORE_V2_SOURCE_COMPLETION_PLAN.md`; it is not authorized for
> implementation or cutover until Product Owner review.

## Product Boundary

This slice extends the isolated Single-Prompt V2 flow after an immutable
`SinglePromptAnalysisContext`. It does not reinterpret V1/V1.1 Steps 1-8 and
does not create Strategy, Proposal, Action or Experiment objects.

The owned flow is:

```text
exact AnalysisContext
-> DiagnosisExecution with frozen input hashes
-> immutable SourceSnapshot set
-> recommendation event/reason diagnosis
-> four-dimensional citation diagnosis
-> frozen target-brand truth snapshot and Reason-to-Truth relation
-> immutable DiagnosisResultVersion
-> append-only DiagnosisReview
```

## Identity And Snapshot Contract

`DiagnosisExecution` is keyed by an explicit analysis plus caller-supplied
idempotency key. Its fingerprint includes:

- `analysis_id` and `context_id`
- the full frozen raw-output SHA-256
- project/brand snapshot SHA-256
- deterministic truth-set SHA-256, including the empty set
- diagnosis contract/config SHA-256

The execution never substitutes live Prompt/Project fields for the frozen
AnalysisContext and never reads latest Package, Snapshot or StrategyCandidate.
Shared LLM cache identity remains based on each judge's exact semantic input;
it is recorded as a computation receipt, not reused as the diagnosis identity.

Each consumed citation source is copied into an immutable V2 SourceSnapshot.
The snapshot stores canonical/original URL observations, fetch status and
failure, fetch time, complete consumed clean text, its SHA-256, the exact
passage set/hash and parser/split versions. A failed fetch is not represented
as successful empty content. SQLite update/delete triggers protect snapshots,
result versions and reviews.

## Semantic Output

Recommendation events preserve separate speech acts. In particular, `MENTION`
does not become `RECOMMEND`. Every Reason retains its original Run identity;
candidate recall can consume only citations observed in that Run.

Citation diagnosis stores four independent dimensions:

```text
reference_observation
anchor_binding
candidate_recall
alignment_evaluation
```

`SOURCE_SUPPORTS_REASON` says only that the frozen source content supports the
Reason. With `anchor_binding=UNPROVEN`, it must not be described as proof that
the sampled answer used that source for that Reason. `NOT_RECALLED`, fetch
failure, zero claims and judge failure remain distinct from `NONE`/no support.

Target-brand truth is frozen at diagnosis creation. The only relation values
are `FULLY_COVERS`, `PARTIALLY_COVERS`, `CONFLICTS` and `UNRESOLVED`. Empty
truth produces explicit `UNRESOLVED`, never FALSE. A broad positive capability
does not fully cover a stronger qualified Reason, and truths from another
project are never visible.

## Publication And Review

The worker records all planned outcomes, including cache use, successful zero
claims, non-recall, fetch/parse/judge failure and upstream-not-evaluated cases.
Only after the sequential work set has a final disposition is one immutable
DiagnosisResultVersion published.

Review and revision requests bind exact:

```text
diagnosis_id
result_version
result_hash
reviewable_set_hash
```

Stale submissions return HTTP 409. Confirmation appends a DiagnosisReview and
does not mutate machine output. Semantic edits create a child result version;
the original remains immutable and the new version must be reviewed. The
overall state `REVIEW_COMPLETED` retains unresolved, unproven, failed and
not-evaluated limitation snapshots.

All GET endpoints and page polling are read-only. Service restart changes an
active execution to explicit `INTERRUPTED`; retry reuses the same diagnosis
identity and increments its attempt count.

## Fixed Acceptance Fixture

The fixed real fixture is:

```text
Project = 1
Prompt = 44
Analysis = 001da937-0baa-498a-a7e9-9d8801324fb3
Task = 52
Context = ctx-8e284b02-6d7b-45f1-931a-ff18bda92562
Raw result = raw-v1:4213d19507cb840c
Raw SHA-256 = 4213d19507cb840c1adb546d655883e5f211f8aa5fb80663ea8d0376d8d80e89
Brand = Geo
Reference records = 30
Unique sources = 29
TargetBrandCapabilityTruth = 0
Retrieval observation = unavailable
```

These values are fixture assertions, not general business rules. #44 validates
real recommendation semantics, citation deduplication/content handling, empty
truth behavior, missing Retrieval observation and conservative anchor status.
Positive Reason-to-Truth coverage is validated with a synthetic isolated
fixture; no #19/#40 or Project 3 truth is imported.

## Non-Goals

- No Runtime RFC reopening or generic 16-Stage platform.
- No V1 runner, historical review carry-forward or latest fallback.
- No Product Truth creation inside diagnosis review.
- No collector repair or historical migration.
- No Strategy, Proposal, Action, Experiment or next-slice implementation.

## Fixed Fixture Production Acceptance

The authorized production replay used only the frozen #44 Prompt/answer input
and the configured `deepseek-v4-flash` Chat Completions endpoint. V2 explicitly
disabled thinking for this bounded JSON extraction; that generation control is
part of the contract and LLM cache identity. The replay made one external HTTP
call, had zero LLM cache hits and recorded 2,417 total tokens. The provider
billing breakdown and charged amount were not returned or persisted, so cost
is `UNKNOWN`, not estimated as an actual charge.

The immutable result is:

```text
Diagnosis = 296e1e1b-bf14-402d-89c1-bb963f1cdea9
ResultVersion = diag-v1:1449c44916fe5c55
Result hash = 1449c44916fe5c55db93c58b56d395f461038c331ddec4a6eaa9af9b8e6c74d4
Reviewable set hash = 3079a6e657b3181fa0d1646606e7325356733e2173761cbc181c6aa799a71dfb
Review = pending
```

DeepSeek grounded four `RECOMMEND` events and four Reasons: 条码全能王、
草料二维码、互联二维码 and 码上游二维码. It did not turn the target brand
into a recommendation. All four empty-Truth relations are explicitly
`UNRESOLVED`.

The result retains 30 reference observations and 29 unique source identities.
No page was fetched during this authorized replay: 25 immutable content
snapshots and four prior failure snapshots were reused locally. Local recall
selected eight passages, but the authorization excluded sending page content
to an external model, so all eight SourceClaim jobs are `NOT_EVALUATED`; all
116 reason/source relations retain `anchor_binding=UNPROVEN`, and none is
reported as no support.

A post-publication quality audit found that one of the 25 technically successful
snapshots was a CSDN security-verification page. The published result remains
immutable and therefore still reports 25 technically ready snapshots; its
effective evidence-ready count is at most 24. The V2 adapter now applies a
deterministic content challenge gate for future executions, records such pages
as `CONTENT_BLOCKED`, emits `SOURCE_CONTENT_QUALITY_BLOCKED`, and excludes their
passages from recall. This gate was test-verified but was not used to rewrite or
replay the authorized result.

Three repeated GET requests left execution update time, attempt count, result
identity, 29 snapshot rows and zero review rows unchanged. Desktop and 390px
mobile browser checks loaded the exact result without page errors; fixed-layout
audit tables now scroll inside their surface on narrow screens.

## V2 LLM Safety Admission Patch

The V2 AnswerSemantic, SourceClaim and Alignment entries now opt into strict,
versioned response contracts. Full JSON, required fields, strict types, closed
enums and `extra=forbid` are enforced before a new response may enter the
successful LLM cache. `{}`, missing fields, unknown fields, wrong types,
truncated output and non-full JSON are failures; only an explicit protocol
empty list is a successful zero result. V1 callers do not opt into this gate
and retain their existing parsing behavior.

New responses and `LLMCallCache` recovery cross the same admission function.
An incompatible cache entry becomes `CACHE_REJECTED_BY_V2_VALIDATION`; it is
not silently rewritten as zero Claims/`NONE`, and `CACHE_ONLY` does not add an
external call. No SourceClaim or Alignment materialization path was added.

The immutable Answer/passage span is the fact-bearing input. Normalized Reason
and Claim text remains a presentation projection and is excluded from
Evidence/Truth consumption when it adds a numeric commitment, high-impact
qualifier, changes explicit negation/condition/comparison scope, or cannot be
conservatively linked to its span. Clear grounding contradictions fail;
complex recommendation/attribution/conditional ambiguity is retained as
`SEMANTIC_REVIEW_REQUIRED`. Review-required text remains visible but cannot
produce an effective Evidence or Truth relation.

External answer and page text is carried inside an explicit untrusted-data
boundary in each V2 model message. Deterministic guards reject instruction-like
material from SourceClaim/Alignment consumption. This is synthetic malicious-
output validation only; real-provider prompt-injection resistance and real
SourceClaim/Alignment execution remain `NOT VERIFIED`.

The published #44 result and review state were not changed. A read-only safety
projection now exposes `current_safety_advisories` and
`effective_evidence_eligibility`, including an explicit whitelist of currently
consumable historical relation IDs. For #44 it reports historical technical
success 25, one currently blocked verification page and a maximum of 24
currently eligible sources. This is an upper bound, not a claim that all 24
remaining pages passed complete quality review.

## Answer Semantic Prompt/Schema/Consumption Alignment

The V2 Answer contract is now versioned as:

```text
Prompt = single_prompt_v2.answer_semantic.safety.v2
Schema = single_prompt_v2.answer_semantic.strict.v2
Admission = single_prompt_v2_llm_admission.v2
Projection = single_prompt_answer_semantic_projection.v2
Diagnosis = single_prompt_diagnosis.v2_second_slice_safety.v2
```

`selection_criteria` has one accepted wire shape only: an array of strict
objects containing required `normalized_reason`, grounded `reason_span`, and
`reason_scope=MARKET_CRITERION`. String items, null or omitted scope, alternate
field names and unknown fields are rejected. The production prompt embeds the
schema generated from `AnswerSemanticResponse` and includes validated non-empty
and explicit-zero examples, so the invoked prompt and admission model no longer
maintain separate field lists.

Admitted criteria are persisted and returned as independent market criteria
with system identity, Run identity and exact source offsets. They do not attach
to brand events, increase brand recommendation Reasons, enter Truth relations,
or establish citation support. A normalized expansion is retained only as
`NORMALIZATION_REVIEW_REQUIRED`; the grounded span remains the fact-bearing
text. `unresolved_items` remains a string list and has no fact authority.

Answer-level outcomes now distinguish admitted results, legal zero events,
review-required projections and failures. When every Answer job failed and no
admitted or legal-zero result exists, the backend exposes
`no_consumable_answer_semantic_result=true`, permits only `VIEW`, rejects
revision/review writes and blocks Strategy with
`NO_CONSUMABLE_ANSWER_SEMANTIC_RESULT`. Partial success remains reviewable while
failed Runs stay in the immutable limitation snapshot.

The frozen #40 failed ResultVersion was not rewritten. Read-only projection of
that exact version reports 0/3 admitted Answers, 3/3 failures and view-only
operations. No external replay has been performed under the v2 contract; the
formal API would process all fixed Runs 260/261/262 and therefore requires a
new authorization covering that whole Context.

## Restricted Raw-Span Grounding

The repaired-contract replay exposed one confirmed formatting difference in
the first rejected event of each failed response. Run 261's immutable raw
interval `1162:1212` and Run 262's interval `1190:1240` each contain one
`U+200C ZERO WIDTH NON-JOINER` after `日常临时使用`; the corresponding model span
omitted that code point. Removing only `U+200C` makes each pair exactly equal.
There was no text, number, punctuation, negation or condition change in those
two inspected intervals.

V2 Answer grounding now uses `single_prompt_v2.answer_grounding.u200c.v1`.
It first requires one exact match. The only fallback is a one-line, unique,
contiguous match that ignores `U+200C` and nothing else. Ambiguous matches,
cross-line joins, other control characters and semantic edits remain rejected.
The result projection records the model span, immutable raw span, raw offsets,
raw-answer SHA-256, matching rule/version, transformation detail and the raw
line context. Event subject, negation, condition and normalized-projection
checks still run after location; formatting equivalence does not approve the
event's meaning.

The current versions affected by this change are:

```text
Prompt = single_prompt_v2.answer_semantic.safety.v2 (unchanged)
Schema = single_prompt_v2.answer_semantic.strict.v2 (unchanged)
Admission = single_prompt_v2_llm_admission.v3
Grounding = single_prompt_v2.answer_grounding.u200c.v1
Projection = single_prompt_answer_semantic_projection.v3_grounded_raw_span
Truth relation = single_prompt_truth_relation.v2_subject_aware
```

Full failed model responses were not retained. The immutable audit stores a
response hash, finish reason, length and a 240-character excerpt. Therefore
this patch locally verifies the two confirmed first-event differences and
isolated adversarial fixtures only; it does not claim that every event, Reason
or market criterion in Runs 261/262 has been revalidated. A new complete-run
result still requires separately authorized external calls.

Cross-subject lexical containment is now projected as an unconfirmed
`TARGET_CAPABILITY_FIT_SUGGESTION`: the machine candidate may remain
`PARTIALLY_COVERS`, but its current effective relation is `UNRESOLVED`. The
source subject and target brand are both retained. This prevents an 爱短链
Truth from proving an 壹伴助手 statement while still allowing a reviewer to
consider whether the target capability may fit the observed market need.
`PARTIALLY_COVERS` remains ineligible for Strategy qualification and public
content.

Source status now separates `not_fetched` from actual `fetch_failed`. The 35
fixed #40 source snapshots were unavailable because fetching was not authorized
and no immutable content was reusable; their current read-only projection is
`not_fetched=35`, `fetch_failed=0`. The old ResultVersion and its historical
limitation wording remain immutable.
