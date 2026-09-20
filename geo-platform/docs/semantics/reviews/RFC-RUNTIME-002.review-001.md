# RFC-RUNTIME-002 Definition Review 001

```yaml
review_id: RFC-RUNTIME-002-REVIEW-001
reviewer_role: INDEPENDENT_SEMANTIC_REVIEWER
reviewed_at: 2026-09-10
reviewed_rfc_status: DRAFT
reviewed_rfc_maturity: CANDIDATE
reviewed_implementation_status: NOT_IMPLEMENTED
change_classification: SEMANTIC_CHANGE
production_code_changes: 0
schema_changes: 0
database_writes: 0
phase_1b_started: false
```

## Status

```text
Status = NEEDS_REVISION
Freeze Recommendation = NO
Phase 1B implementation authorized = NO
```

The RFC correctly establishes producer-bound capture, exact immutable review
targets and no-latest lineage. AnswerUnit, Gap and Strategy ownership are
sufficiently clear at the definition level. Four decisions still require the
RFC Author: Product Truth binding producer/workflow, Product Truth value and
binding-state compatibility, Source Qualification decomposition, and the exact
Execution Proposal Stage target/input boundary.

These are not reasons to redesign Runtime. They are the remaining places where
an Implementer could still choose business semantics.

## Sources Reviewed

```text
docs/semantics/rfcs/RFC-RUNTIME-001.md
docs/semantics/rfcs/RFC-RUNTIME-002.md
docs/semantics/05_RUNTIME_SEMANTIC_MAP.md
docs/semantics/reviews/RFC-RUNTIME-001.stage-output-binding-lineage-gap-review.md
docs/semantics/04_CONFLICT_REGISTER.md
docs/semantics/00_DOMAIN_MODEL.md
docs/semantics/01_SEMANTIC_CONTRACTS.md
docs/semantics/snapshots/CASE-REAL-019.manifest.json
docs/semantics/snapshots/CASE-REAL-040.manifest.json
docs/EXECUTION_PROPOSAL_PR5_A.md
docs/EXECUTION_PROPOSAL_PR5_B.md
backend/app/modules/optimization/answer_semantic.py
backend/app/modules/optimization/answer_evidence_shadow.py
backend/app/modules/optimization/passage_service.py
backend/app/modules/optimization/source_qualification.py
backend/app/modules/optimization/api.py
backend/app/modules/optimization/recommendation.py
backend/app/modules/optimization/service.py
backend/app/modules/optimization/execution_proposal_shadow.py
frontend/src/App.tsx
frontend/src/api/client.ts
```

The fixed #19/#40 manifests were used only as immutable Legacy expectations.
No latest object substitution or database reconstruction was used.

## AnswerUnit

```text
owner = Step 2 ANSWER_SEMANTIC output
producer = prospective Answer Semantic operation; current Legacy producer is
           _build_answer_units() inside the answer-evidence Shadow chain
binding = BINDING consumes exact frozen AnswerUnit and Decision Reason members;
          it does not create or edit them
result = DEFINITION CLOSED; IMPLEMENTATION GAP
```

The domain model already defines AnswerUnit as a Step 2 semantic object. It is
an atomic assertion extracted from an answer, while AnswerDecisionBinding is a
relation between that unit and a Decision Reason/context. This ownership is
semantic, not merely a preference for a tidy DAG.

Current code does not satisfy it: `run_answer_semantic()` creates
RecommendationEvents, while `_build_answer_units()` creates AnswerUnits inside
the later Shadow operation immediately before `_build_decision_bindings()`.
That is an implementation boundary conflict, not a reason to assign AnswerUnit
to BINDING.

The Frozen correction rule also closes successor lineage: editing a Decision
Reason or AnswerUnit creates a new human-authored `ANSWER_SEMANTIC` output;
downstream outputs become stale only through exact consumed edges.

## Product Truth

```text
formal binding owner = a Product Truth/Reason binding business command, not the
                       Runtime observer and not StrategyCandidate hints
producer model = current RFC selects Option A: explicit Step 3 human binding
                 confirmation for each formal binding
runtime reverse-coupling risk = HIGH
definition closed = NO
implementation gap = current Step 3/API persists only mutable Project-level
                     capability truth and has no Reason/output/version binding
```

The current Step 3 UI and endpoint confirm only a target-brand capability fact:

```text
project + brand + capability key/label
+ product_truth_status + provenance
```

They do not present or submit an exact Decision Reason identity/hash, immutable
fact-value version, binding decision or supersession reference. Confirming
"the target brand supports X" is not the same human action as confirming
"Reason R17 binds Product Truth X".

RFC-RUNTIME-002 correctly rejects the current heuristic and Candidate
`product_truth_ids` as formal lineage, but it then declares a new explicit Step
3 Reason-scoped human command without establishing that this manual action is a
required product responsibility. It does not compare:

```text
Option A = every binding is explicitly human-confirmed
Option B = deterministic binding proposal, human review only for ambiguity
Option C = another existing business action already establishes the relation
Option D = no acceptable producer currently exists
```

The Reviewer does not select among these options. The Author must provide the
product basis, manual-burden policy, ambiguity behavior and authoritative actor
for the selected model. Until then, requiring Step 3 manual binding would be
`RUNTIME_TO_PRODUCT_REVERSE_COUPLING` and a `PRODUCT_WORKFLOW_CHANGE`.

There is also a value/state compatibility conflict:

- RFC-RUNTIME-002 limits `ProductTruthFactValueVersion.value` to
  `TRUE | FALSE | UNKNOWN`.
- Frozen RFC-RUNTIME-001 explicitly preserves `PARTIALLY_SUPPORTED` in the
  Product Truth projection.
- Current production stores `SUPPORTED | PARTIALLY_SUPPORTED |
  NOT_SUPPORTED | UNKNOWN`.
- RFC-RUNTIME-002 expands binding status from the Frozen candidate's `BINDS`
  assertion to `BINDS | DOES_NOT_BIND | UNKNOWN`, but does not define how the
  latter two enter the selected binding manifest, review authority or
  projection output.

The RFC says it does not redefine Product Truth semantics, so it must either
preserve the accepted domain or specify an explicit normalization contract. It
must also define whether negative/unknown pair decisions are formal reusable
objects or remove them from this contract.

`PRODUCT_TRUTH_PROJECTION` remains Phase 1B blocked. Legacy matching must not be
used while these definitions are revised.

## Source Qualification

```text
one object or multiple semantic layers = multiple: acquisition eligibility,
                                         content quality, project-relative ownership,
                                         and Context projection
pre-fetch = URL normalization/deduplication/fetchability and acquisition policy;
            current code has no persisted formal qualification output here
post-fetch = content-quality assessment bound to SourceDocument content hash
natural scope = quality by content version; ownership by Project/brand/
                competitor-set/source/config; acquisition by Root source request
context projection = one closed result per exact Root source observation
order = NOT FULLY CLOSED
definition result = NEEDS REVISION
```

The RFC correctly recognizes that content quality and ownership have different
natural scopes. The real code confirms the distinction:

- `acquire_cited_sources()` deduplicates and fetches cited URLs before there is
  any content-quality fact;
- `assess_quality()` requires fetched content and persists `SourceQuality`;
- `resolve_ownership()` needs Project/domain/competitor inputs but not content,
  and is recomputed by multiple downstream consumers rather than persisted by
  `run_source_qualification()`;
- `run_source_qualification()` currently persists only quality rows, despite
  its broad module/docstring terminology.

RFC-RUNTIME-002 describes two reusable fact types but gives the single
"Context-scoped qualification operation after SourceFetch" responsibility for
their production and projection. It does not separately name:

```text
producer of SourceContentQualityFactVersion
producer of SourceOwnershipFactVersion
producer of SOURCE_QUALIFICATION Context projection
ownership of pre-fetch acquisition eligibility/skips
```

Therefore the proposed `SOURCE_FETCH -> SOURCE_QUALIFICATION` edge may be valid
for content qualification, but the RFC has not proved that every pre-fetch
eligibility concept was removed from, or never belonged to, the Stage. Runtime
must not silently change which URLs are fetched merely to make lineage easier.

The Author must decompose these responsibilities and then freeze the exact DAG
edge(s) and terminal members. This does not necessarily require another Runtime
Stage, but the Implementer cannot decide where acquisition eligibility ends and
qualification begins.

## Gap Review

```text
output identity = immutable GapOutput ID + exact member manifest/hash
review target = exact Gap output/hash and immutable member partition
definition closed = YES
current API gap = WorkflowConfirmation carries only Project/Prompt/step and
                  mutates one row; no Gap output identity is submitted
classification = IMPLEMENTATION_GAP
```

The Gap producer can allocate/persist the exact output identity while building
the closed Reason partition. The review request can carry that identity. No
new business decision is needed to add those fields.

The correction distinction is also closed:

```text
confirm/reject/reopen -> append-only ReviewDecision
edit Gap content -> new immutable Gap output + separate review
```

Current `WorkflowConfirmation(step_key="gap")` remains Legacy UNSAFE audit
metadata. Its inability to bind an output does not prevent Definition Freeze;
it prevents Phase 1B implementation until the API/output model is changed.

## StrategyCandidate

```text
producer = _create_vertical_strategy_candidate() create transaction
write-time binding = exact returned Candidate ID plus original machine payload
                     and consumed input/output hashes
post-hoc inference = forbidden
definition closed = YES
```

The function creates the row, commits, refreshes and returns the exact Candidate
while the calling synthesis operation still knows its validated input scope.
It is a valid producer boundary. No latest/pending/accepted Candidate query is
needed or permitted for prospective capture.

Machine Strategy and a validated human edit are correctly modeled as separate
immutable `STRATEGY_SYNTHESIS` outputs under one Candidate lineage. Acceptance
without an edit is only a ReviewDecision.

## effective_payload

```text
semantic role = Legacy compatibility/materialized executable view
immutable/mutable = mutable in current production
runtime output eligibility = INELIGIBLE as output identity or review target
conflict = prospectively closed; current implementation remains incompatible
```

Current `review_strategy_candidate()` mutates the Candidate row and writes
either the machine structure or deterministic merged edit into
`effective_payload_json`. Step 8 consumers then read that mutable field. It has
no independent immutable identity and currently mixes selected view and edited
content.

RFC-RUNTIME-002 selects Interpretation A: retain `effective_payload` only as a
Legacy compatibility/materialized view. Prospective machine and edited outputs
must carry their own immutable IDs/hashes and exact reviews. This definition is
clear. The remaining work is implementation; historical payloads stay UNSAFE
and are not reconstructed.

## Execution Proposal

```text
system proposal = PR5-A deterministic ExecutionProposalPortfolio
human-selected proposal = PR5-B canonical rebuilt/revalidated portfolio;
                          currently ephemeral and semantically a successor output
frozen execution snapshot = PR5-C/later Step 8 lifecycle; NOT DEFINED here

Runtime Stage target = NOT UNIQUELY FROZEN BY RFC-RUNTIME-002
PR5-C dependency = should not be required for a system-generated proposal-set
                   Stage output; required only if target is a frozen selected
                   execution snapshot or downstream Action/Experiment input
```

Frozen RFC-RUNTIME-001 describes `EXECUTION_PROPOSAL` as an immutable proposal
portfolio and explicitly leaves Action/Experiment consumption to a separate
Step 8 lifecycle contract. PR5-A already has a deterministic system portfolio;
PR5-B produces a human-edited canonical rebuild without persistence; PR5-C has
not defined the frozen selected execution snapshot.

RFC-RUNTIME-002 preserves parts of this distinction, but two ambiguities remain:

1. It does not explicitly choose whether the Stage's first output is the PR5-A
   system portfolio, the PR5-B successor output, or a PR5-C frozen snapshot.
2. It requires an exact `ManagedAsset/NewAsset input snapshot`, while PR5-A's
   `NewAssetSpec` is generated output when no compatible ManagedAsset exists.
   A generated new-asset specification cannot simultaneously be a prerequisite
   input snapshot.

The Author must name the exact Stage target and classify ManagedAsset snapshots,
the absence of a compatible asset, and NewAssetSpec as input or output. If the
target is the system-generated proposal set, Phase 1B need not wait for PR5-C;
PR5-B edits can be successor outputs and PR5-C remains a separate consumer. If
the target requires a frozen selection, the RFC must declare
`PHASE_1B_BLOCKED_BY_STEP8_LIFECYCLE` rather than define that lifecycle here.

## Phase 1B

```text
16-stage rule = VALID; all 16 must be expressible, not necessarily successful
capture-eligible = only RUN_METRICS is independently unambiguous in current code,
                   after non-semantic instrumentation
implementation-blocked = all remaining Stages directly or transitively until
                         the revised definitions are frozen and producers exist
dependent-RFC-blocked = only a frozen selected ExecutionSnapshot/Action/Experiment
                        path depends on the future Step 8 lifecycle RFC
```

`SUCCEEDED` with legal zero, `UNRESOLVED`, explicit `BLOCKED` and terminal
failure are valid expressions when their identity, inputs, output/terminal
manifest and blocking reason are exact. Missing or silently skipped Stage rows
are not expressible.

The full 16-Stage gate remains proportionate because its purpose is to prove
cross-stage lineage, review/current selection and dependency-derived STALE.
RUN_METRICS-only capture cannot satisfy that acceptance objective.

## Conflicts

### SEM-CONFLICT-003

```text
Conflict = Frozen ANSWER_SEMANTIC lacks executable member literals and per-Run
           zero/failure representation
affected objects = ANSWER_SEMANTIC, StageExecution, StageAttempt
current behavior = missing RecommendationEvent may mean zero, skip or failure
RFC proposed behavior = closed six-kind member registry and distinct failures
blocks Definition Freeze = NO; RFC-RUNTIME-002 closes the definition
blocks Phase 1B implementation = YES until the new contract is frozen/implemented
can remain OPEN after RFC Freeze = NO as a Definition Conflict; close with a
                                   resolution record while implementation remains PARTIAL
```

### SEM-CONFLICT-004

```text
Conflict = Frozen BINDING expects upstream AnswerUnit, while Legacy creates it
           inside the Binding Shadow operation
affected objects = ANSWER_SEMANTIC, BINDING, AnswerUnit, AnswerDecisionBinding
current behavior = _build_answer_units() and _build_decision_bindings() share one run
RFC proposed behavior = ANSWER_SEMANTIC produces/fixes AnswerUnit first;
                        BINDING only consumes units/reasons and emits relations
blocks Definition Freeze = NO; ownership is semantically justified and closed
blocks Phase 1B implementation = YES until producer boundaries are changed
can remain OPEN after RFC Freeze = NO as a Definition Conflict; record resolution,
                                   retain implementation_status=PARTIAL/BLOCKED
```

## Blocker Classification

| Issue | Classification | Must revise RFC? | Blocks implementation? | Dependent RFC? |
| --- | --- | --- | --- | --- |
| `PROSPECTIVE_BINDING_PRODUCER_GAP` | `DEFINITION_BLOCKER` | YES | YES | NO; Author must justify/choose the producer model |
| `SOURCE_QUALIFICATION_SCOPE_AND_ORDER_CONFLICT` | `DEFINITION_BLOCKER` | YES | YES | NO; acquisition semantics may not be delegated to Implementer |
| `PROSPECTIVE_GAP_REVIEW_CAPTURE_GAP` | `IMPLEMENTATION_GAP` | NO | YES | NO |
| `CANDIDATE_EFFECTIVE_PAYLOAD_CONFLICT` | `IMPLEMENTATION_GAP` with Legacy UNSAFE data retained | NO | YES for prospective edited-output capture | NO |
| `EXECUTION_PROPOSAL_SELECTED_OUTPUT_GAP` | `DEFINITION_BLOCKER` | YES | YES | CONDITIONAL: only if the chosen target is a frozen Step 8 snapshot |
| `SEM-CONFLICT-003` | `NON_BLOCKING_CONFLICT` for Definition Freeze | NO | YES | NO |
| `SEM-CONFLICT-004` | `NON_BLOCKING_CONFLICT` for Definition Freeze | NO | YES | NO |

## New Definition Blockers

### D1. Product Truth producer model and manual burden

The RFC must compare the four producer models, select one with product—not
Runtime—authority, and define when human confirmation is required. It may not
silently add one manual action per Reason.

### D2. Product Truth value and binding-state compatibility

The RFC must reconcile `TRUE/FALSE/UNKNOWN`, Frozen
`PARTIALLY_SUPPORTED`, and production status literals without weakening
UNKNOWN preservation. It must also define the lifecycle/projection effect of
`DOES_NOT_BIND` and binding `UNKNOWN`, or remove those states.

### D3. Source Qualification producer decomposition

The RFC must separately identify acquisition-eligibility ownership, content
quality fact producer, project-relative ownership fact producer and Context
projection producer, then freeze the resulting order and terminal behavior.

### D4. Execution Proposal Stage target and NewAssetSpec direction

The RFC must choose the exact Stage output among system portfolio, human-edited
successor and frozen execution snapshot. It must classify `NewAssetSpec` as a
generated output rather than an already-existing input snapshot unless another
approved object is intended.

## Implementation Gaps

The following definitions are already clear enough and must not be reopened
merely because current code lacks them:

```text
ANSWER_SEMANTIC producer emits exact AnswerUnits and per-Run terminals
BINDING consumes pre-existing AnswerUnit/Reason members
immutable GapOutput persistence and exact Gap review request
Strategy capture at _create_vertical_strategy_candidate() return
append-only Strategy reviews and edit-as-new-output
effective_payload isolation from Runtime output identity
explicit ContextStageSelection and dependency-derived STALE
Stage input/output manifests and producer-bound instrumentation
```

Product Truth, Source Qualification and Execution Proposal also have physical
implementation gaps, but implementation must wait for D1-D4.

## Dependent RFCs

```text
RFC-STEP8-LIFECYCLE / equivalent = required for PR5-C persisted selection,
                                   frozen ExecutionSnapshot and later
                                   Action/Experiment consumption
SEM-CONFLICT-002 = remains the Step 8 CREATE_NEW identity/lifecycle blocker
```

Neither is required merely to define/capture a PR5-A system-generated proposal
set, provided RFC-RUNTIME-002 explicitly chooses that as the Runtime Stage
output. Foundation/Citation work is unrelated to this Review.

## Safety

```text
production code diff = 0
RFC-RUNTIME-002 diff = 0
Schema diff = 0
DB writes = 0
Phase 1B = NOT STARTED
dual-write = NOT STARTED
PR5-C = NOT STARTED
```

## Final Recommendation

```text
REVISE
```

```text
Status = NEEDS_REVISION
Freeze Recommendation = NO
Phase 1B implementation authorized = NO
```

The next RFC revision should address only D1-D4. Gap review,
StrategyCandidate producer capture, effective-payload isolation, AnswerUnit
ownership, no-latest rules and the 16-Stage acceptance objective should remain
unchanged.

Review ends here. No RFC edit, implementation, schema change, database write,
Phase 1B work or PR5-C work is authorized.
