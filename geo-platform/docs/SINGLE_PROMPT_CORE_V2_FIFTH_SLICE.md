# Single-Prompt Core V2 Fifth Slice

Status: IMPLEMENTED / SYNTHETICALLY VALIDATED / REAL EXTERNAL RETEST NOT AUTHORIZED

## User Flow

The fifth slice adds one explicit measurement path:

```text
exact ExecutionConfirmation + selected PublicationRecord revision
-> frozen RetestPlan and MeasurementIdentity
-> separately authorized browser sampling
-> separately authorized or cache-only Answer Semantic measurement
-> immutable descriptive ComparisonResultVersion
```

The result reports observed change. It does not determine channel effectiveness,
strategy success, causal lift or the next strategy. GET, refresh and polling are
read-only. Planning, sampling, semantic measurement and comparison each require
an explicit POST.

## Exact Handoff

A RetestExecution binds the exact confirmation, publication revision and report
hash, proposal, original V2 Analysis/Context, raw result, complete baseline Run
manifest, sampling plan, measurement identity and measurement contract. No
`latest` Strategy, Publication, Package, Project configuration or V1 baseline is
read to replace these inputs.

Historical publications remain observable after their strategy stops being
current. This does not reactivate the old strategy. Missing ownership, cross-
project identity or damaged snapshot/hash still returns an explicit conflict.

## Frozen Sampling

The V2 adapter creates a BrowserMonitorTask and exact planned Run rows from the
frozen Prompt text. It does not call the mutable Prompt/Project task-creation
path. Before execution and again inside the worker:

```text
hash(BrowserMonitorRun.original_query) == RetestPlan.prompt_text_hash
```

is required. Failed retries reuse the same planned Run IDs and preserve completed
successes. Partial failures may be retried or explicitly frozen with their
failure records; no retry appends samples until a favorable answer appears.

Planned conditions, per-Run observed conditions and platform-unobservable
conditions are stored separately. Explicit observed conflicts remove the metric
delta while preserving both side values. Historical missing observations remain
`PLAN_DECLARED_ONLY`/unknown limitations rather than being reconstructed from
current rows.

## Measurement

The measurement input is a frozen DTO, never the mutable Project or legacy metric
runner. Baseline and Retest use the same MeasurementIdentity and contract.

- `brand_mention_rate`: explicit frozen brand name/alias occurrence by Run;
- `brand_recommendation_rate`: eligible V2 Answer Semantic `RECOMMEND` events;
- `target_brand_official_reference_rate`: frozen official domain/URL identity;
- `published_url_reference_rate`: exact canonical published URL identity.

All metrics count Run hits, so repeated references in one Run do not inflate the
numerator. Missing semantic evaluation, official identity or reference
observation produces null/unevaluated, not zero. A zero is legal only when an
observable non-zero denominator exists and no Run hits.

Sampling authorization does not authorize DeepSeek. A cache-only semantic run
revalidates compatible V2 cache data and performs zero external calls on a miss.
External semantic measurement has a separate explicit authorization action and
still uses the strict V2 Answer Semantic admission path. SourceClaim, Alignment,
Gap and Strategy are not run for these metrics.

## Comparison

Comparison stores immutable Baseline and Retest measurements, exact input hashes,
per-metric eligibility, temporal order, publication conformance and limitations.
An explicit condition conflict yields `delta_percentage_points=null`. When metric
contracts match but temporal order is unverified, values may be shown only as a
two-sample descriptive difference, never as a verified before/after improvement.

`USER_REPORTED` is not upgraded to `SYSTEM_VERIFIED`. `OUTSIDE_CONFIRMED_SCOPE`
and `NOT_EVALUABLE` publication records may still be observed, but the report
states that the observation is not proof of executing the confirmed plan.

## Acceptance

Fixed #44 remains blocked: its exact diagnosis has no review, strategy,
ExecutionConfirmation or PublicationRecord. Read-only inspection found zero
strategy, confirmation and publication rows, so fifth-slice readiness returns
`EXECUTION_CONFIRMATION_AND_PUBLICATION_REQUIRED` and creates no Retest.

Isolated fixtures validate frozen task creation, exact Prompt hashing, retry on
the same Run IDs, partial-failure finalization, historical publication
observation, cross-project rejection, independent authorization, cache-only zero
external calls, Run-level metrics, null/zero separation, observed-condition
conflicts, immutable comparison and idempotency. No real browser sample or
DeepSeek call was made.

## Explicit Non-Goals

This slice does not auto-publish, fetch the publication page, verify the user-
reported publication, calculate causality or significance, generate Strategy or
Execution content, migrate history, build an Experiment/Agent/Runtime platform,
or modify V1 semantics.
