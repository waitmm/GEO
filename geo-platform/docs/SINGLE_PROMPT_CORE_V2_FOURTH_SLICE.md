# Single-Prompt Core V2 Fourth Slice

Status: IMPLEMENTED / SYNTHETICALLY VALIDATED / REAL POSITIVE CHAIN NOT YET AVAILABLE

## User Flow

The fourth slice adds one explicit V2 path:

```text
accepted StrategyResult direction
-> deterministic execution content skeleton
-> human selection/edit/revalidation
-> append-only ExecutionConfirmation
-> append-only USER_REPORTED PublicationRecord
```

The page calls the output an execution content skeleton, asset production brief
and publication plan. It does not claim that an article was generated. GET,
refresh and polling are read-only; each write requires an explicit POST.

## Frozen Input

Every proposal freezes the exact V2 strategy result and review, consumed
diagnosis/safety scope, selected direction and an exact baseline from the
strategy's immutable AnalysisContext. Baseline validation recomputes and checks:

- raw output hash;
- sampling plan hash;
- run-scope hash and exact ordered Run IDs;
- planned, valid and failed Run manifest;
- collector capability limitations;
- available formal metric definition versions.

Theme coverage or a narrower analyzable subset cannot replace the full valid Run
set. Missing or mismatched input returns 409; no latest lookup is used.

## Strategy And Asset Boundaries

Foundation directions keep `channel_key=null` and `channel_role=null`. A user may
select an owned product page, feature page or help center as the publication
surface, but that execution destination never mutates the strategy into
`OFFICIAL_SITE PRIMARY`.

Channel directions inherit their confirmed channel and role without an editing
path. Zero PRIMARY is valid, so a qualified TEST direction can proceed.

The current real path supports only `CREATE_NEW`. `UPDATE_MANAGED` is rejected;
SourceDocument, PageSnapshot, planned specs and caller-provided IDs cannot imply
ownership or editing permission. New-asset confirmation does not require a URL.

## Public And Internal Content

`PUBLIC_CONTENT` and `INTERNAL_CHECKLIST` are separate structures. Public titles,
sections and claim usage are compiled only from manually confirmed target-brand
Truth linked by an eligible `FULLY_COVERS` relation. `PARTIALLY_COVERS`, unknown
qualifiers, planning questions, account checks and measurement limitations remain
internal and cannot become public claims or FAQ content.

Users may choose the deterministic asset/package option, safely edit the title,
select and reorder sections, enter the planned account/location and add notes.
Every edit creates an immutable child result and reruns server validators. Channel
role, strategy scope, claims, baseline and metric definitions are not editable.

## Confirmation And Publication

One confirmation binds one current proposal result, one direction, one asset type,
one package and one publication surface. Confirmation is append-only and means
`confirmed, not published`.

A PublicationRecord requires an exact confirmation and a real user-provided URL
and publication time. It is always `USER_REPORTED`; this slice performs no online
verification. Backend conformance is one of:

- `MATCHED`;
- `VALIDATED_VARIATION`;
- `OUTSIDE_CONFIRMED_SCOPE`;
- `NOT_EVALUABLE`.

The client cannot choose conformance. URL/channel match alone cannot prove content
match, and unstructured content that the current validators cannot fully assess is
`NOT_EVALUABLE`. Deviating publication facts remain recorded. Corrections append a
revision linked through `prior_publication_id`; old reports are immutable.

## Real And Synthetic Acceptance

Fixed #44 remains class A. Read-only inspection on 2026-09-11 found its diagnosis
`296e1e1b-bf14-402d-89c1-bb963f1cdea9` at `READY_FOR_REVIEW`, with zero Diagnosis
Reviews and zero Strategy executions. Therefore no proposal, confirmation or
publication can be created without the user's future diagnosis and strategy
reviews.

Isolated fixtures validate the positive chain, including zero PRIMARY TEST,
Foundation/channel separation, `PARTIALLY_COVERS` exclusion, exact baseline,
CREATE_NEW-only behavior, immutable revisions, idempotent confirmation, publication
history and backend conformance. Fixture success is not a real publication or a
real positive project-chain acceptance.

## Explicit Non-Goals

This slice makes zero external LLM calls, performs zero page fetches and does not
auto-publish, retest, calculate effect, enable managed-asset UPDATE, create a full
experiment platform, modify V1 state or expand Runtime governance.
