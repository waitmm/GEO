# RFC-EVIDENCE-PACK-MULTI-BATCH-MERGE-001: Frozen-Scope Multi-Batch Findings And Merge

```yaml
rfc_id: RFC-EVIDENCE-PACK-MULTI-BATCH-MERGE-001
status: APPROVED
semantic_maturity: FROZEN
implementation_status: SHADOW_CONTRACT_IMPLEMENTED_NOT_CUT_OVER
authors: [Codex D-line]
created_at: 2026-11-18
definition_approved_by: Product Owner + independent geo_supervisor
definition_approved_at: 2026-11-18
definition_approval_reference: GEO Platform 1.0 全项目持续并行开发指令
production_cutover_approved_by: null
production_cutover_approved_at: null
production_cutover_approval_reference: null
affected_contracts:
  - SC-GRADED-DELIVERY-001@1.0.0
  - SC-MULTI-DRAFT-ARTIFACT-001@1.0.0
  - SC-AGGREGATE-OBSERVATION-001@1.0.0
  - SC-SERVER-COMPOSED-QA-001@1.0.0
supersedes: null
```

The Product Owner authorized the goal of a narrow Definition Freeze and offline
implementation for `GEO-CAP-001`. Independent geo_supervisor review returned
`APPROVED` on 2026-11-18 and the accompanying freeze record fixes this
definition. It does not authorize provider
calls, production cutover, M1.1 database changes, or reinterpretation of prior
single-pack results.

## Problem

One immutable Optimize scope may contain more complete answers and evidence than
one Evidence Pack request can carry. The current shadow planner proves that the
frozen inputs can be partitioned without losing Run, Citation occurrence,
SourceSnapshot or SourceDisposition identity. It does not define what several
model outputs mean, how conflicting findings are handled, or when they may
produce one final `AgentResultVersion`.

Concatenating prose, silently dropping failed batches, or voting across batches
would change the evidence denominator and could turn UNKNOWN into a claim. The
result semantics therefore require an explicit contract before production use.

## Current Semantics

- One `AgentExperimentRun` freezes one exact Project, Prompt, version and Run
  scope. It currently uses one `geo.evidence-pack.v3` and at most one model call.
- One immutable `AgentResultVersion` represents the Optimize result for that
  exact scope. `DraftArtifactVersion` children do not change the parent scope.
- Complete-scope aggregate observations are computed and verified by the server
  against the full frozen Evidence Set. A model cannot choose its members.
- UNKNOWN, failed parsing, missing identity and cross-version evidence do not
  become zero or absence.
- Existing capacity planning is shadow-only and carries the blocker
  `SEMANTIC_CONTRACT_REVIEW_REQUIRED:MULTI_BATCH_RESULT_MERGE`.

## Current Production Behavior

`backend/app/modules/agent_experiment/evidence_pack.py::execute_evidence_pack_run`
builds one pack, performs one request under Execution v15, validates it and
persists one result. It does not import or call the capacity planner.

Observed implementation references:

- `backend/app/modules/agent_experiment/evidence_pack_capacity.py`
- `backend/tests/test_evidence_pack_capacity.py`
- `backend/tests/test_evidence_pack_capacity_scaling.py`
- `docs/geo-v1.0/EVIDENCE_PACK_CAPACITY_ACCEPTANCE.md`

## Observed Failure

The fixed 90,000-character request boundary is exceeded under several legitimate
frozen-scope distributions:

- many complete answers even when URLs repeat;
- many unique Citation catalog entries;
- long Source passages and multiple content versions.

The 22/50/100/300/1,000-Run shadow matrix proves deterministic partitioning but
explicitly does not prove that independently generated findings can be merged.
No real-model or business-quality claim is derived from the synthetic matrix.

## Proposed Semantics

### 1. Frozen scope and plan

One `AgentExperimentRun` continues to own exactly one complete frozen scope.
`MultiBatchPlan` is an immutable execution projection over that scope, not a new
AnalysisContext, sample pool, denominator or business result.

Plan identity binds:

- exact frozen scope hash and planner/contract version;
- ordered batch numbers;
- every batch's Run IDs, Citation occurrence IDs, SourceSnapshot IDs and
  SourceDisposition identities;
- Evidence Pack hash and batch hash;
- request-size projection and whole-task request/Token/cost reservation.

Every Run and Citation occurrence belongs to exactly one batch. A SourceSnapshot
may be read by more than one batch when occurrences in those batches reference
the same immutable content version; final support counts it by original identity,
not by number of batch appearances.

The current shadow validator proves only that a plan is internally
self-consistent and hash-stable. Before any production execution or final
aggregation, the server must reload the authoritative original frozen scope and
revalidate every Project/Prompt/version, Run, answer hash, Citation occurrence,
SourceSnapshot and SourceDisposition identity against it. Plan self-consistency
alone is never production authority.

### 2. Batch result

A successful batch produces an append-only `BatchEvidenceFindingVersion`. It may
contain scoped observations, diagnosis candidates and action candidates with
original Evidence locators. It is not a diagnosis, Strategy, final draft,
`AgentResultVersion`, Evidence Set replacement or new Product Truth.

Each locator must belong to the exact batch and original frozen scope. Cross-batch,
cross-Project, cross-Prompt, stale hash or unknown locator identity is rejected.
Batch prose cannot upgrade evidence or create a full-scope observation.

The first narrow typed observation is `BRAND_LITERAL_PRESENCE`, with
`subject=TARGET_BRAND`, `scope=BATCH_VALID_SCOPE`,
`quantifier=ANY_VALID_RUN`, exact batch hash, `matched_count`,
`valid_run_count` and `unresolved_run_count`. The server computes those counts
from authoritative batch answers and frozen brand configuration; a model cannot
supply or alter them. `PRESENT` in one batch and `ABSENT` in another are
compatible local observations, not a conflict. Other model findings remain
scoped candidates and cannot directly create an aggregate Observation.

### 3. Completion, failure and retry

The first production-capable version is all-or-nothing for business delivery:

- all planned batches must succeed and validate before aggregate synthesis;
- failed/cancelled/missing batches remain auditable but produce no deliverable
  `AgentResultVersion` or child Draft;
- a failed batch may be retried through an append-only Attempt under the same
  batch identity;
- a successful batch result is immutable and cannot be overwritten;
- partial batch completion is operational progress, not a smaller business
  denominator and not `PARTIAL_SUCCESS` content delivery.

This narrow rule avoids silently redefining the selected analysis range. A future
partial-range business delivery requires a separate semantic change.

### 4. Conflict and UNKNOWN

Batch findings with the same claim identity and incompatible known values form
an explicit `CONFLICT`. They are not resolved by majority vote, batch order,
latest timestamp, adjacent disclaimer or model preference. UNKNOWN stays UNKNOWN
and never contributes a zero/absence value.

The aggregate synthesizer may present unresolved alternatives with their exact
locators, but cannot promote them to verified fact or qualified action. Aggregate
scope observations remain server-computed over the full frozen Evidence Set.
Any aggregate input containing UNKNOWN is explicitly
`REVIEW_REQUIRED_UNKNOWN`, including a known value and UNKNOWN for the same
claim. `READY_FOR_SHADOW_REVIEW` means only that the shadow input has no known
conflict or UNKNOWN; it is not content qualification and cannot create a
business result.

### 5. Aggregate and final result

Aggregate synthesis consumes only validated batch findings, the exact plan,
server-owned aggregate Observations/Evidence Sets and applicable Product Truth.
It must preserve original locators; a batch ID alone is not evidence.

A final `AgentResultVersion` is allowed only after:

1. complete validated batch set;
2. no unresolved blocking conflict for the asserted conclusion;
3. aggregate response validation under the applicable Evidence, Truth, QA and
   graded-delivery contracts;
4. binding plan hash, every batch-result hash, aggregate-response hash and final
   result hash.

HELP_DOC/FAQ remain append-only `DraftArtifactVersion` children of that one final
parent. Batch results can never become Draft parents.

### 6. Budget, cancellation and recovery

Before the first external call, the server atomically reserves the maximum number
of batch calls plus the aggregate call and their total Token/cost upper bounds.
Insufficient request, Token or cost allowance blocks with zero calls. Clients do
not provide or enlarge those limits.

Cancellation prevents new calls. A response already in flight may be archived
for audit but cannot bypass cancellation to create a final result. Resume uses
the same plan and successful immutable batch results; identity drift requires a
new run rather than fallback to latest.

`max_attempts_per_batch` includes the first attempt and is fixed before
reservation. Reservation is therefore
`batch_count * max_attempts_per_batch + 1 aggregate call`, including every
attempt's Token/cost upper bound. Exhausting a batch's attempts is terminal and
cannot be resumed. `READY_FOR_SHADOW_AGGREGATE` is not terminal because the
aggregate call has not occurred; cancellation at that point must prevent it.

### 7. Frozen aggregate input schema

The proposed aggregate input contains exactly: contract/mode/status; frozen
scope and plan hashes; ordered complete batch result hashes and validated typed
batch results; server-derived aggregate observations with predicate, subject,
`FROZEN_VALID_SCOPE`, quantifier, matched/valid/unresolved counts and
verification state; unresolved UNKNOWN identities and explicit candidate
conflicts; finding count, production-result flag, cutover blocker and aggregate
hash.

For `BRAND_LITERAL_PRESENCE`, the server sums disjoint batch counts. Any
unresolved member yields UNKNOWN; otherwise any match yields PRESENT and zero
matches yields ABSENT. No generic candidate is promoted to this schema. Any
future predicate requires its own frozen server aggregation rule.

The implementation must recompute that Observation once from every member of
the complete authoritative frozen Run manifest. Batch findings are validation
and audit material only: omitting the finding cannot shrink the denominator,
and repeating it cannot increase counts. Duplicate semantic finding identity in
one batch is rejected. Missing brand terms or an ineligible/blank answer yields
UNKNOWN under the same valid-answer eligibility v2 rule used by the current
Evidence Pack profile; it never becomes literal absence.

### 8. Aggregate response and final binding schema

Only an aggregate input with status `READY_FOR_SHADOW_REVIEW` may later become
eligible for an explicitly authorized aggregate request. `REVIEW_REQUIRED_UNKNOWN`
and `REVIEW_REQUIRED_CONFLICT` stop before generation and can never receive
content or qualification merely by being serialized.

The aggregate response binding contains exactly:

- `frozen_scope_hash`, `plan_hash` and `aggregate_input_hash`;
- the same ordered `batch_result_hashes` from the aggregate input;
- immutable `aggregate_response_hash` over the raw provider response;
- independent candidate execution identity
  `geo.evidence-pack.multibatch-execution.candidate.v1`, plus the explicitly
  bound validation profile and validation status;
- final `agent_result_version_hash`, computed by the existing result owner with
  the above binding included in immutable execution lineage;
- each existing child Draft binding as parent result hash, artifact role,
  artifact version/hash and its independent QA/qualification status.

The candidate may reuse the existing Validation v6 validation logic and current
diagnosis/Strategy/Draft business schema, but it does not claim Execution v15:
v15 remains frozen as the single-request profile and its historical meaning is
unchanged. The candidate adds no new business assertion field, Truth meaning,
delivery level or Draft role. Ordered batch and aggregate hashes are provenance
binding, not Evidence locators. Existing parent/child Draft immutability and
partial-success rules remain unchanged.

## Non-Goals

- No second Optimize chain, sampling path, crawler or workflow engine.
- No change to current single-pack Execution v15, Validation v6 or Prompt v11.
- No automatic Product Truth, Review, publication or formal V2 writes.
- No silent answer/source summarization, source-version merge or evidence drop.
- No real provider call, price/budget authorization or production cutover.
- No M1.1 database migration or history backfill.

## Affected Domain Objects

| Object | Identity / scope | Source of Truth | Owner | Allowed consumers |
|---|---|---|---|---|
| MultiBatchPlan | scope hash + planner version + ordered batch identities + plan hash | server deterministic planner | Evidence Pack execution preflight | batch executor, budget guard, audit |
| BatchAttempt | plan + batch hash + append-only attempt number | server task runtime | execution runtime | recovery/audit only |
| BatchEvidenceFindingVersion | plan + batch + attempt + response/result hash | validated provider response projection | batch validation | aggregate preflight/audit |
| AggregateInput | plan + complete ordered batch-result hashes + server observations | server composer | aggregate preflight | aggregate synthesizer/validator |
| AgentResultVersion | existing exact run/scope/execution identity plus multi-batch binding | validated aggregate output | existing Agent experiment result owner | existing Draft/feedback/history consumers |

`MultiBatchPlan`, batch Attempt and batch findings are not aliases for Run,
AnalysisContext, Evidence Set, Strategy, ResultVersion or DraftArtifactVersion.

## Contract Diff

```text
old contract/version: single Evidence Pack request -> one validated AgentResultVersion
new contract/version: candidate SC-EVIDENCE-PACK-MULTI-BATCH-001@1.0.0
allowed inference diff: a complete validated batch set may be aggregate input for the same frozen scope
forbidden inference diff: no prose concatenation, majority vote, partial-range delivery or batch-ID-as-evidence
unknown behavior diff: batch UNKNOWN/conflict/missing identity remains explicit and blocks unsupported conclusions
step boundary diff: internal Evidence Pack execution/validation only; sampling, formal V2, Truth and publication unchanged
```

## Golden Cases

### MULTIBATCH-NORMAL-COMPLETE

Given one exact frozen scope and a deterministic full-coverage plan, all batches
succeed with valid original locators and compatible findings. The complete hash
set may enter aggregate validation. No final result exists before that validation.

### MULTIBATCH-BOUNDARY-SHARED-SNAPSHOT

The same immutable SourceSnapshot is referenced from occurrences assigned to two
batches. Both batches may read it, but aggregate evidence counts one snapshot
identity and preserves every occurrence relationship.

### MULTIBATCH-UNKNOWN-CONFLICT

One batch returns UNKNOWN and two batches return incompatible known values for
the same claim. UNKNOWN remains UNKNOWN, the known values form CONFLICT, and no
verified aggregate assertion or content qualification is created.

### MULTIBATCH-FAILURE-RECOVERY

One batch fails after prior batches succeed. There is no final business result.
Retry appends an Attempt; it does not rewrite successful batches. Aggregation is
eligible only after the retried batch succeeds under the same identity.

### MULTIBATCH-BUDGET-ZERO-CALL

The total `N * max_attempts_per_batch + 1` request or Token/cost reservation exceeds server policy. The run
is blocked before any provider call; no partial spend or batch result is created.

### MULTIBATCH-HISTORY-COMPAT

Historical single-pack v3/v15 Pack, hash, result, usage and status remain
byte-for-byte interpreted by their original contracts.

## Counterexamples

1. **Partial denominator fallacy**: 9 of 10 batches succeeded and all omit the
   brand. It is forbidden to state the full selected range omitted the brand.
2. **Majority vote**: 8 batches produce A and 2 produce B. It is forbidden to
   call A verified without a separate server-verifiable predicate.
3. **Batch ID as evidence**: a finding cites only `batch-3`. It is forbidden to
   treat this as a Run/Citation/Source/Truth locator.
4. **Latest fallback**: resume cannot rebuild a changed plan from current/latest
   configuration, source snapshots or Product Truth.
5. **Shared-source inflation**: one snapshot appears in five batch inputs. It is
   forbidden to count this as five independent sources.

## Identity / Scope Impact

The business scope is unchanged. New identities are append-only execution and
validation lineage under that exact scope. The plan hash changes whenever batch
membership, source version identity, planner version or request projection
changes. A changed plan cannot resume another plan's results.

## UNKNOWN Semantics

Missing/invalid Run membership, locator, source content hash, response hash,
batch result, conflict resolution, Truth qualification or budget reservation is
fail-closed. UNKNOWN is not false, zero, absence, unsupported or permission to
omit a batch.

## Step Boundary And Allowed Consumers

Producer and consumers stay inside the isolated Agent Experiment Evidence Pack
execution/validation lane. Batch artifacts may be consumed only by the exact
plan's aggregate preflight and audit. They cannot update Monitor metrics,
AnalysisContext, formal V2 tables, Product Truth, Review, publication or existing
historical results.

## Implementation Plan

1. **Current authorized shadow slice**: typed plan/result validators, conflict and
   UNKNOWN preservation, pure in-memory state/retry/cancel audit, all-calls budget
   preflight and synthetic fault injection. No provider call or DB write.
2. After Definition Freeze: additive append-only persistence for plan, batch
   attempt and finding identities; still offline/shadow until cutover approval.
3. After separate external-call authorization: isolated fake/replay executor,
   then specifically authorized real multi-call acceptance.
4. Production cutover requires an independent Product Owner approval.

## Historical Compatibility And Migration

No migration is part of the current shadow slice. Historical Pack/result rows
are not backfilled, revalidated, relabelled or inferred as multi-batch. Future
tables must be additive and may not change existing uniqueness or foreign-key
meaning.

## Shadow Plan

Use synthetic 22/50/100/300/1,000-Run distributions and fixed protected replays.
Verify deterministic membership and hashes, complete identity coverage, shared
snapshot handling, cross-scope rejection, failure/retry/cancel recovery,
conflict/UNKNOWN preservation, budget zero-call behavior and unchanged single-
pack output. Synthetic success is not business-quality or production acceptance.

## Cutover Gate

- Independent Definition Review returns APPROVED and a freeze record exists.
- Golden normal/boundary/unknown/failure cases are automated.
- No OPEN semantic conflict blocks this RFC.
- Additive persistence, recovery and rollback pass on an isolated database.
- Existing single-pack regression and historical hashes remain unchanged.
- Specifically authorized model-call acceptance proves usage accounting and
  aggregate validation; synthetic tests do not substitute for it.
- Product Owner separately approves production cutover.

## Risks And Conflicts

No current Conflict Register entry resolves multi-batch merge semantics. Until
production cutover approval, any production wiring would be a `SHADOW_PRODUCTION_LEAK` and
`PARTIAL_PREMISE_FALLACY`. A future Definition Review must register any conflict
found with SC-GRADED-DELIVERY, aggregate Observation or multi-Draft contracts.

## Rollback

Current shadow code is removable without changing production behavior. After a
future cutover, rollback restores the single-pack implementation for new tasks;
it must retain already written plan/attempt/result audit and cannot delete or
reinterpret the approved Contract.

## Approval Gates

1. Definition Freeze approval: approved by Product Owner and independent geo_supervisor.
2. Implementation/Shadow approval: current owner instruction authorizes only the
   shadow typed-contract and offline verification slice.
3. Production Cutover approval: not granted.

## Definition Review

```text
Status: APPROVED
Contracts Referenced: SC-GRADED-DELIVERY-001, SC-MULTI-DRAFT-ARTIFACT-001,
  SC-AGGREGATE-OBSERVATION-001, SC-SERVER-COMPOSED-QA-001
Golden Snapshot IDs: synthetic cases above; no Real Manifest claimed
Blocking Issues: none for Definition Freeze; production cutover remains unapproved
Non-blocking Issues: persistence table design and UI progress projection are post-freeze implementation details
Category Error Audit: proposed objects explicitly are not Run/Analysis/Evidence Set/Result/Draft aliases
Causal Audit: batch findings cannot prove aggregate cause or business outcome
Identity / Scope Audit: exact scope, plan, batch, attempt, locator and result hashes required
Forbidden Inference Audit: partial denominator, voting, latest fallback and shared-source inflation forbidden
Golden Cases: normal, shared snapshot, unknown/conflict, recovery, budget, history
Counterexamples: five complete counterexamples above
Step Boundary: Agent Experiment Evidence Pack execution/validation only
Historical Compatibility: old Pack/results/usage/status unchanged
Contract Gaps: none in the proposed definition; persistence and UI projection are implementation details
Freeze Recommendation: APPROVED
```

## Product Owner Approval

The 2026-11-18 “GEO Platform 1.0 全项目持续并行开发指令” authorized this
narrow Definition Freeze and non-production shadow work. The independent
geo_supervisor approved the exact definition after three review rounds. No
production cutover, paid call or company-database approval is inferred.
