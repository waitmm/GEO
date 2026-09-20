# Single-Prompt Core V2 Third Slice

Date: 2026-09-11
Decision: `SPC-V2-SLICE-003`
Scope: reviewed diagnosis to evidence-constrained strategy candidate.

## Product Boundary

This slice consumes one exact V2 DiagnosisResultVersion plus its exact
DiagnosisReview. It does not reinterpret V1/V1.1 strategy semantics and does
not create Execution Proposal, Action or Experiment objects.

```text
exact DiagnosisResultVersion
+ exact DiagnosisReview snapshot
+ current V2 safety-consumption projection
-> StrategyInputProjection
-> StrategyReadinessReport (A/B/C)
-> optional immutable StrategyCandidate result
-> optional priority child version
-> append-only StrategyReview
```

No candidate is created for an unreviewed diagnosis or for a reviewed input
with zero qualified intervention directions. `StrategyReadinessReport` is a
return contract, not a persisted empty strategy.

## Readiness Classes

- `A`: the exact diagnosis result has no valid review. Preview is read-only and
  returns `DIAGNOSIS_REVIEW_REQUIRED` plus the exact review next step.
- `B`: review is complete, but no direction passes its qualification gate. The
  report retains concrete verification items and blocked directions; no
  candidate row is written.
- `C`: at least one direction is `ACTIONABLE`. A user POST may create a pending
  review candidate containing only qualified directions. Other limitations
  remain frozen with it.

Review completion is an entry gate, not blanket approval of machine output.
`UNRESOLVED`, `UNPROVEN`, `NOT_EVALUATED`, failed and `CONTENT_BLOCKED` inputs
remain ineligible after review.

## Foundation And Channel Independence

Foundation uses `REQUIRED`, `NOT_REQUIRED` or `UNKNOWN`. `REQUIRED` needs both
confirmed target-brand truth and an explicit, evidenced authority-asset gap.
Empty truth or an unobserved official page leaves Foundation `UNKNOWN`.

Foundation never selects a channel. A Foundation direction has null channel
identity and Role. `Foundation=REQUIRED/UNKNOWN` with `Citation PRIMARY=NONE`
is valid.

A qualified channel direction requires a fact-consumable grounded Reason, a
manually confirmed target-brand Truth that fully covers that Reason, an
eligible evaluated source relation, recognized execution fit and a verifiable
intervention. `EXPLICIT` anchor may form `PRIMARY`; `UNPROVEN` anchor can form
only a `TEST` hypothesis and never Decision Citation.

There is no official-site fallback, most-cited PRIMARY, Benchmark-to-execution
promotion or mandatory PRIMARY rule.

## Direction Levels And Themes

Directions use `ACTIONABLE`, `VERIFY_FIRST`, `OBSERVE` or `BLOCKED`. There is
no aggregate score. If multiple `ACTIONABLE` directions have no deterministic
ordering, the candidate records `needs_human_prioritization=true`. A priority
edit creates a child immutable version and must retain exactly the same
closed-world direction set.

Theme grouping reuses pure deterministic compatibility/title helpers. Theme
coverage uses the union of member Reason Run IDs over the frozen analyzable Run
scope, never the sum of member coverage and never an LLM estimate.

## Identity, Validation And Lifecycle

The strategy input freezes analysis/context/diagnosis/result identity, exact
review ID and deterministic review snapshot hash, reviewable-set hash,
validation versions, consumed object IDs, current evidence whitelist,
limitations and advisories. Display wording, load time and reviewer note do not
participate in the review snapshot hash.

The producer returns the exact strategy ID and result version; no latest
Candidate query is used. A closed-world persistence validator rejects unknown
Reasons, Truths or evidence IDs, non-actionable directions, invalid channel
Roles and any channel attached to a Foundation direction.

GET recomputes only the exact input's current applicability. If its active
result, review snapshot, validation contract or safety whitelist changes, the
old candidate remains viewable but cannot be revised or reviewed. Stale writes
return HTTP 409. StrategyResult and StrategyReview rows are immutable;
confirmation appends a review and does not edit machine output.

GET and page refresh are read-only. Only explicit POST actions create, revise
or review a strategy.

## Fixed #44 Acceptance

```text
Project = 1
Prompt = 44
Analysis = 001da937-0baa-498a-a7e9-9d8801324fb3
Diagnosis = 296e1e1b-bf14-402d-89c1-bb963f1cdea9
ResultVersion = diag-v1:1449c44916fe5c55
```

Read-only production inspection returns class `A`, no diagnosis review, no
qualified direction and `Foundation=UNKNOWN`. It sees 29 source snapshots,
four fact-consumable grounded Reasons and zero currently effective evidence
relations. Empty target-brand Truth, not-evaluated evidence, unproven anchors,
unavailable Retrieval/session proof and one blocked verification page remain
visible. Historical technical success is 25; current eligible content is at
most 24, not 24 fully verified evidence sources.

No #44 review or strategy row was created for acceptance. Positive B/C,
Foundation-with-zero-PRIMARY, independent TEST, closed-world rejection,
human-priority versioning and stale HTTP 409 behavior use isolated fixtures.

## Stop Point

This slice stops after strategy preview, explicit generation, constrained
priority revision and strategy review. External LLM calls, page fetches,
Execution Proposal, Action, Experiment, release and retest remain out of scope.
