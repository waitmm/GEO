# RFC-RUNTIME-001 Runtime Shadow Phase 1B Prospective Capture

```yaml
rfc_id: RFC-RUNTIME-001
phase: RUNTIME_SHADOW_PHASE_1B
target: PROSPECTIVE_SHADOW_CAPTURE
status: BLOCKED
decision: BLOCKED_BY_FROZEN_STAGE_OUTPUT_AND_BINDING_LINEAGE_MAPPING_GAPS
review_date: 2026-09-10
production_cutover: NOT_AUTHORIZED
runtime_read_cutover: NOT_STARTED
historical_backfill: 0
production_call_sites_instrumented: 0
real_database_writes: 0
```

## Scope

Phase 1B audited the future-facing Legacy execution boundaries that could feed
the isolated Phase 1A persistence spine. The audit followed the required order:

```text
Legacy execution
-> existing commit/result boundary
-> exact fact mapping
-> Shadow-only Runtime capture
```

The audit stopped before instrumentation because two required Frozen mappings
cannot be produced without inventing Stage semantics. No observer, production
dual write, Runtime reader, API, frontend, scheduler, executor, historical
reconstruction or PR5-C path was added.

## Call-sites Audited

| Legacy call-site | Existing boundary | Prospective mapping result |
| --- | --- | --- |
| `optimization/api.py::_run_analysis_pipeline` | Independent commits after Answer Semantic, qualification, acquisition, segmentation, Binding, SourceClaim and Alignment | The commit points are observable, but the function does not retain exact formal Stage input/output manifests or dependency edges. |
| `optimization/api.py::workflow_run_analysis` | Creates one `PromptAnalysisRun` and starts the background pipeline with explicit final `run_ids` | The resolved package identity is not passed to the background function. Runtime must not repeat the existing active/latest selection to recover it. This is an implementation mapping gap, not permission to select a package. |
| `optimization/answer_semantic.py::run_answer_semantic` | Commits `RecommendationEvent` rows and returns aggregate counts | The result does not persist a terminal member for every Run. A successful zero-event Run and an unmaterialized/failed Run can both have no row. Existing rows are skipped and reused without an execution-consumption edge. |
| `optimization/answer_evidence_shadow.py::run_answer_evidence_shadow_chain` | Creates one `AnswerEvidenceShadowRun`, then AnswerUnits and Bindings, and commits a terminal run | `AnswerUnit` is created inside the would-be `BINDING` execution from `AnswerClaim`, while Frozen `BINDING` requires AnswerUnit/Reason members from an upstream `ANSWER_SEMANTIC` StageExecution. No exact upstream Stage output ref/hash exists. |
| `optimization/source_qualification.py` | Mutates qualification/source state before pipeline commit | Current project-wide source processing does not return the complete exact per-execution output set or immutable source-mapping input version. |
| `optimization/passage_service.py` | Returns acquisition summary; segmentation mutates documents before commit | Legacy rows lack the immutable content-version and passage-output lineage required by `SOURCE_FETCH` and `SEGMENTATION`. |
| `optimization/source_claim.py` | Materialization ledger plus claim persistence | The materialization ledger is useful execution evidence, but the required upstream `SEGMENTATION` and qualification Stage output refs/hashes do not exist. |
| `optimization/evidence_alignment.py` | Candidate execution and alignment materialization | The current path cannot supply the full Frozen upstream Stage chain when Binding/Answer Semantic cannot be captured. |
| `optimization/workflow.py` review functions | Mutate exact legacy row groups and commit | A formal immutable Stage output/partition target does not yet exist, so a mutable legacy review cannot be promoted to `StageReviewDecision`. No review mapping was instrumented. |

## Blocking Mapping Gaps

### 1. ANSWER_SEMANTIC output contract is not executable as written

The Frozen identity registry requires:

```text
run_id
+ member_kind
+ source_span_start
+ source_span_end
+ member_ordinal
```

It also states that `member_kind` is a closed enum and that an unknown value is
invalid. The repository contains no Frozen literal registry for that enum.
Inventing values such as `RECOMMENDATION_EVENT`, `DECISION_REASON`,
`ANSWER_UNIT` or `NO_EVENT` would silently revise the Frozen contract.

The Legacy runner also records no immutable per-Run terminal result for a
successful zero-event answer. It only increments `runs_associated`. Because an
LLM failure also leaves no RecommendationEvent row, absence cannot safely be
converted into a deterministic zero member after the fact.

Required Definition Review:

```text
define the exact ANSWER_SEMANTIC member_kind literal set;
define the exact terminal zero/skip member and identity;
define whether RecommendationEvent reasons and AnswerUnits are members of one
Stage output or separate outputs;
define how a reused pre-Phase-1B zero result proves its terminal identity.
```

### 2. BINDING has a circular/missing upstream boundary in Legacy

Frozen Runtime requires:

```text
ANSWER_SEMANTIC AnswerUnit/Reason output
-> BINDING input
```

Current Legacy execution does this instead:

```text
run_answer_semantic
-> RecommendationEvent rows

run_answer_evidence_shadow_chain
-> build AnswerUnit from AnswerClaim inside the Binding call
-> combine AnswerUnit with RecommendationEvent
-> create AnswerDecisionBinding
```

Therefore the object required as `BINDING` input is created during the same
Legacy function that would be captured as `BINDING`. Assigning it to a prior
`ANSWER_SEMANTIC` output would be a reconstructed edge, not an observed edge.

Required Definition/implementation decision:

```text
either establish a real committed ANSWER_SEMANTIC output boundary containing
the exact AnswerUnit/Reason members before Binding starts;

or revise the Frozen Stage split and dependency contract through Definition
Review.
```

The Phase 1B implementer is not authorized to choose between those options.

## Capture Mapping

The following Root facts appear prospectively capturable from an explicit
EvidencePackage and fixed Run set:

```text
stored Package prompt snapshot;
fixed Run ids and Run rows;
Reference/Retrieval observations for those exact Runs;
target URLs and acquisition environment;
RunArtifact rows when the exact bytes remain readable.
```

This partial feasibility was not converted into production writes. A legal
Context must be atomically visible with a legal executable Stage boundary; a
Root-only row would not satisfy the Phase 1B acceptance gate and would create a
misleading partially live lineage.

## Database And Migration State

```text
production DB identity = backend/geo_v0.db
production DB SHA-256 before = fb24d2f074912415219397e7325007439644432cbfa6250b694137d1834900d3
production DB SHA-256 after  = fb24d2f074912415219397e7325007439644432cbfa6250b694137d1834900d3
runtime_* tables in production DB = 0
Phase 1B migration added = none
Phase 1B rows written = 0
rollback required = no
```

Phase 1A revision `20260910_01` remains unapplied to the real database.

## Golden Cases

### Prompt #19

```text
fixed EvidencePackage = 12@v8
fixed Run scope = 40
Runs with RecommendationEvent rows = 37
Runs with AnswerClaim rows = 12
Runs with AnswerUnit rows = 12
Runs with AnswerDecisionBinding rows = 12
```

The unequal source populations are valid Legacy facts, but they prove that an
exact `ANSWER_SEMANTIC -> BINDING` member edge cannot be recovered merely from
the shared 40-Run scope. No latest ShadowRun or missing row was substituted.

### Prompt #40

```text
fixed EvidencePackage = 15@v2
fixed Run scope = 6
Runs with RecommendationEvent rows = 6
Runs with AnswerClaim rows = 6
Runs with AnswerUnit rows = 6
Runs with AnswerDecisionBinding rows = 6
```

Equal counts do not prove lineage. AnswerUnits still originate inside the
Binding call from AnswerClaims, and no immutable upstream output ref/hash binds
them to the prior Answer Semantic execution. The #40 mapping is therefore also
blocked rather than accepted by count coincidence.

```text
#19 prospective Stage semantic diff = NOT_COMPUTABLE_WITHOUT_INVENTION
#40 prospective Stage semantic diff = NOT_COMPUTABLE_WITHOUT_INVENTION
latest substitution = 0
semantic invention = 0
historical backfill = 0
```

## Required Tests

Phase 1B positive/negative capture tests were not added because there is no
legal Frozen Stage output to persist. Testing invented enum literals or a
reconstructed Binding edge would only make an invalid implementation look
stable.

The accepted Phase 1A persistence and projection tests remain the regression
baseline. They are rerun in this checkpoint to ensure the blocked audit did not
change canonical vectors or persistence invariants.

```text
pytest test_runtime_persistence_spine.py + test_runtime_projection_spike.py
= 16 passed

runtime_projection_spike.py
= SPIKE_PASS
= normative vectors 3/3 MATCH
= #19 stage expectation diff 0
= #40 stage expectation diff 0
= deterministic two-pass hashes MATCH
= latest substitution 0
= semantic invention 0
= DB writes 0

compileall Runtime persistence/projection = PASS
git diff --check = PASS
```

## Production Behavior Proof

```text
legacy output before / after = unchanged by Phase 1B
legacy selector before / after = unchanged by Phase 1B
legacy API before / after = unchanged by Phase 1B
legacy workflow gate before / after = unchanged by Phase 1B
frontend before / after = unchanged by Phase 1B
production semantic diff = 0 by zero instrumentation and zero DB writes
automatic promotion = 0
runtime read cutover = 0
```

## Decision

```text
BLOCKED_BY_FROZEN_STAGE_OUTPUT_AND_BINDING_LINEAGE_MAPPING_GAPS
```

Return `RFC-RUNTIME-001` to independent Definition Review. Phase 1B is not
complete and Phase 1C, Runtime API/frontend, real migration, backfill,
dual-authoritative write, cutover, persistent executor and PR5-C remain
forbidden.
