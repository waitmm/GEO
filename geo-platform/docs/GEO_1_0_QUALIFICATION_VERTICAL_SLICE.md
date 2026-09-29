# GEO 1.0 Qualification Vertical Slice

Status: IMPLEMENTED READ-ONLY CHECKPOINT

Date: 2026-09-29

## Product Decision

This is a Product Owner implementation decision, not a new Runtime RFC.

The main computation path does not wait for a global human review. Machine
results may continue when the exact object is qualified for the requested use.
Human review is an optional correction overlay. Business approval remains a
hard requirement for external actions such as publication.

Eligibility is evaluated per object and per use:

```text
Diagnosis -> Strategy Direction -> Execution Draft -> Public Claim -> Publication
```

An object can therefore be consumable for a Strategy Direction and internal
Execution Draft while remaining `VERIFY_FIRST` or `NOT_CONSUMABLE` for a public
claim. No review action can bypass a claim or publication gate.

## Phase 0 Gate Audit

| Existing boundary | Real implementation | Current decision |
| --- | --- | --- |
| Diagnosis review | `strategy.evaluate_strategy_readiness()` requires an exact `REVIEW_COMPLETED` Diagnosis Review | Retained for the legacy persisted StrategyCandidate path; removed as a global blocker from this read-only automatic projection |
| Full-scope review | Existing strategy readiness requires all fixed Runs computed and reviewed | Exact Run scope remains visible; review is not required to calculate a direction from already admitted machine objects |
| Answer semantic admission | `fact_consumption_eligible` and grounded spans in Diagnosis output | Hard object-level gate |
| Product Truth applicability | `reason_capability_coverage` plus manually confirmed `SUPPORTED` Truth | Required for a target-brand Strategy Direction |
| Public claim | `statement_eligibility` and `build_claim_usage_policy()` | Hard claim-level gate; first-party confirmation without a source remains `VERIFY_FIRST` |
| Strategy persistence | `SinglePromptStrategyExecution` requires Diagnosis Review identity and snapshot hash | Not reused by this checkpoint; no schema workaround or fake Review |
| Execution persistence | Existing Execution Proposal requires accepted Strategy Review | Not reused by this checkpoint; the new output is an internal read-only draft |
| Publication | Existing confirmation/publication path requires explicit user actions | Always blocked here; `external_action_authorized=false` |
| Citation Contribution | Current real Contribution covers Run 1 only | `ENRICHING/OBSERVE_ONLY`; never expanded into 9-Run evidence |

## Reused Capabilities

- Exact Analysis/Context/DiagnosisResult identity and active-version checks.
- Grounded Answer Reasons and `fact_consumption_eligible` admission.
- Target-brand Truth snapshot, atomic capability status and
  `reason_capability_coverage`.
- Existing statement eligibility and source-reference issues.
- Current immutable Citation Contribution identity and explicit Run scope.
- Deterministic hashing and closed input identity.

No legacy Runner, latest Candidate, latest Package, strategy write path or
external model call is used.

## Projection Contract

The read-only endpoint returns:

```text
object_qualifications[]
directions[]
execution_drafts[]
analysis_scope
evidence_scope
final_plan
boundary
projection_hash
```

Each dependency declares:

```text
BLOCKING | SUPPORTING | ENRICHING
required_for
state
eligibility
provenance
reason_codes
```

Each draft Claim declares its target-brand Truth, provenance, limiting
dependencies and separate public-claim eligibility. The draft never grants
publication authority.

## Current Real Result

For Analysis `19b0be0f-f794-4435-9fa7-2723257f26cc` and Diagnosis Result
`diag-v2:5435e5989f2a7c2f`, the projection deterministically produces one real
Strategy Direction and one internal Execution Draft.

The direction is based on the grounded Run 4 target-brand Reason and four
manually confirmed target-brand atomic capabilities. Those facts are sufficient
for target applicability and draft planning. They are not yet eligible public
claims because their target-brand source references are missing.

The Answer scope is Runs 1-9. Citation Contribution covers Run 1 only and does
not cover the Run 4 Reason. It is therefore retained as a visible scope
limitation, not used to select a publication channel, and not allowed to block
the independent internal direction.

## Checkpoint Boundary

- Database migrations: 0
- Business writes: 0
- External LLM calls: 0
- New StrategyCandidate rows: 0
- New Review rows: 0
- Publication authorization: false

The next implementation checkpoint may persist an automatic direction only
after its ownership and immutable version identity are made explicit. It must
not fake a Diagnosis Review to satisfy the historical Strategy table contract.
