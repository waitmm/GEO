# RFC-RUNTIME-001 Runtime Shadow Phase 1A Persistence Spine

```yaml
rfc_id: RFC-RUNTIME-001
semantic_maturity: FROZEN
implementation_status_before: NOT_IMPLEMENTED
implementation_status_after: PARTIAL
phase: RUNTIME_SHADOW_PHASE_1A
result: PASS
completed_at: 2026-09-10
production_cutover: NOT_STARTED
real_database_migration_applied: false
```

## Classification And Boundary

```text
classification = IMPLEMENTATION_CHANGE
semantic contract change = 0
production call-sites = 0
live shadow capture = NOT_STARTED
```

Phase 1A implements only the Frozen Runtime persistence primitives. The models
use an isolated `RuntimeBase` and are deliberately absent from `app.models.Base`,
so the existing production `init_db()` cannot create these tables. The migration
is an unapplied artifact tested only against temporary SQLite databases.

## Persistence Objects

```text
AnalysisContext = runtime_analysis_contexts
StageExecution = runtime_stage_executions
StageAttempt = runtime_stage_attempts + immutable runtime_stage_attempt_results
StageReviewDecision = runtime_review_targets + runtime_stage_review_decisions
CurrentContextPointer = runtime_current_context_pointers + append-only events
ContextStageSelection = runtime_context_stage_selections + append-only events
validity/audit = runtime_validity_states + append-only runtime_validity_events
immutable manifests = runtime_manifests
exact dependency lineage = runtime_stage_input_edges
```

`StageAttempt` separates the immutable claim/lease identity from its one
immutable terminal result. This preserves every attempt without overwriting an
aggregate counter while still allowing an active physical attempt to finish.

## Canonicalization

The persistence service reuses the Spike-proven
`semantic_manifest_canonicalization.v1` implementation and persists both full
audit payload/member refs and exact canonical bytes. A hash never replaces the
retrievable manifest.

```text
input_set_hash = dba2155c917c74e7f297ad0e5fe9a8639ef3f2f8289e3511fcc84e0d96cce10e
fixed_scope_hash = d361f0132ee1ab4ba8a89d5a6793d6f291b6bf8b413d51d5c91da2e47e24be66
source_ref_set_hash = 543fa710799ecc38c9382b3646643a6b8fddcd807fcd8e43cbe1d3f942b5a483
normative vectors = MATCH
```

## Invariant Results

```text
same fingerprint / multiple Context IDs = PASS
Context root immutable = PASS
zero-output Stage SUCCEEDED = PASS
RETRY same Execution / new Attempts = PASS
RECOMPUTE new Execution = PASS
late fenced Attempt rejected = PASS
exactly one authoritative success = PASS
successful output immutable = PASS
Review append-only = PASS
Review linear chain = PASS
Review branch conflict = PASS
Review self-cycle impossible = PASS
Review cross-target supersession rejected = PASS
CurrentContextPointer CAS/history = PASS
ContextStageSelection CAS/history = PASS
RECOMPUTE no automatic promotion = PASS
SHADOW / PRODUCTION pointer isolation = PASS
INVALIDATE history retained = PASS
REACTIVATE history retained = PASS
STALE derived from exact selected dependency edges = PASS
historical output retained/readable = PASS
```

SQLite migration triggers independently protect immutable manifests, Context
roots, input edges, Attempt history/results, Review decisions and audit events.
They also require the publishing Attempt to match the Stage's current fencing
generation and prevent successful StageExecution mutation.

## Migration

```text
artifact = alembic/versions/20260910_01_runtime_persistence_spine.py
single-revision clean temporary DB = PASS
full Alembic chain clean temporary DB -> head = PASS
real DB applied = NO
```

## Golden Projection Regression

The existing read-only projection suite remained unchanged:

```text
#19 Stage expectation diff = 0
#40 Stage expectation diff = 0
latest substitution = 0
semantic invention = 0
projection DB writes = 0
```

## Validation

```text
focused persistence + projection tests = 16 passed
compileall Runtime package/test = PASS
git diff --check (Phase 1A files) = PASS
```

The full backend suite was also run and returned `470 passed, 5 failed`. Each
failure reproduced when run alone and is outside the Runtime package:

```text
tests/test_b2_gate.py::test_batch_delete_preflight_rejects_if_any_has_runs
tests/test_b2_gate.py::test_batch_delete_succeeds_when_all_clean
tests/test_monitoring_collection_mode.py::test_prepare_collection_mode_raises_when_conversation_cannot_reset
tests/test_recommendation_intelligence.py::test_unresolved_effective_payload_cannot_materialize_experiment
tests/test_recommendation_intelligence.py::test_strategy_experiment_plan_exposes_p2_verification_boundary
```

Phase 1A did not edit or import the production modules implicated by those five
pre-existing regressions. They are reported rather than repaired because this
phase expressly forbids production behavior changes.

## Safety

```text
production call-sites = 0
real DB writes = 0
real DB SHA before = fb24d2f074912415219397e7325007439644432cbfa6250b694137d1834900d3
real DB SHA after = fb24d2f074912415219397e7325007439644432cbfa6250b694137d1834900d3
frontend changes = 0
production behavior change = 0
```

## Recommendation

```text
READY_FOR_PHASE_1B
```

This recommendation means only that the persistence spine is ready for Product
Owner review and a separately authorized live Shadow capture phase. It does not
authorize migration of the real database, production dual-write, Runtime API,
frontend work, workflow cutover, legacy backfill or PR5-C.
