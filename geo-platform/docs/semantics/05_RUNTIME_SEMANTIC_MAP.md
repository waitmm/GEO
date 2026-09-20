# GEO Runtime Semantic Map

```yaml
document_id: GEO-RUNTIME-SEMANTIC-MAP
status: ACTIVE
fact_status: OBSERVED
proposal_status: NONE
created_at: 2026-09-08
source_investigation: Runtime Integrity Phase 0
database_identity: backend/geo_v0.db@fb24d2f074912415219397e7325007439644432cbfa6250b694137d1834900d3
```

## 1. Purpose And Boundary

This document is the Golden Runtime Definition for `RFC-RUNTIME-001`. It records
what the current system actually does. It does not approve a future runtime
model and does not turn observed implementation into a FROZEN contract.

```text
CURRENT OBSERVED RUNTIME
!=
PROPOSED RUNTIME CONTRACT
```

Sources:

- `backend/app/models/db.py`
- `backend/app/modules/optimization/api.py`
- `backend/app/modules/optimization/workflow.py`
- `backend/app/modules/optimization/service.py`
- `backend/app/modules/optimization/source_claim.py`
- `backend/app/modules/optimization/evidence_alignment.py`
- `backend/app/modules/optimization/evidence_alignment_candidates.py`
- `backend/app/modules/optimization/execution_proposal_shadow.py`
- `frontend/src/App.tsx`
- `docs/semantics/snapshots/CASE-REAL-019.manifest.json`
- `docs/semantics/snapshots/CASE-REAL-040.manifest.json`

## 2. Phase 0 Fact Summary

```text
UNIFIED_RUNTIME_IDENTITY = NONE
PACKAGE_FREEZE = PARTIAL
REVIEW_HISTORY = OVERWRITE_RISK
DOWNSTREAM_INVALIDATION = MOSTLY_MISSING
CANDIDATE_BUILDER_REPLAYABILITY = PARTIAL
PARTIAL_WRITE_AFTER_RUN_FAILURE = YES
OPTIMISTIC_CONCURRENCY = NONE / LAST_WRITE_WINS
```

## 3. Current Analysis Identity Candidates

| Object | Current identity | Scope | Mutable | Versioned | Multiple coexist | Current selection | Frontend use |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `PromptAnalysisRun` | row id | project + prompt | status/error mutable | no runtime-input version | yes | greatest id | running/failure overlay |
| `OptimizationEvidencePackage` | row id + package version/hash | project + prompt + run list | row mostly stable; referenced state mutable | partial | yes; old packages remain active | greatest version/id | package context and baseline |
| `AnswerEvidenceShadowRun` | row id + run list + pipeline version | project + prompt + optional package | status mutable; outputs appended | partial | yes | latest completed row with exact run-set equality | indirect through Binding/Alignment |
| `OptimizationStrategyCandidate` | row id + evidence package | project + package | review/effective payload mutable | partial | yes | pending first; otherwise accepted candidate matching mutable confirmation | Step 7 and Step 8 entry |
| Candidate effective payload | field on Candidate | Candidate | mutable | field version only | no independent identity | follows selected Candidate | executable Strategy view |
| Workflow status | computed response | project + prompt | recomputed | no response identity | many responses | current database reads | main workflow authority plus client recomputation |

No object uniquely identifies one Step 2-8 analysis lineage.

## 4. Current Timeline And Freeze Points

```text
Prompt
-> collection request
-> BrowserMonitorRun rows and collection artifacts
-> ReferenceSource / RetrievalCandidate rows
-> EvidencePackage may be created from currently valid Runs
-> background analysis starts
-> Answer Semantic
-> Source Qualification
-> Source Fetch
-> Segmentation
-> AnswerUnit / Binding
-> SourceClaim
-> EvidenceAlignment
-> explicit Benchmark / Gap / Channel / Strategy reads or writes
-> PR5 Execution Proposal read/revalidation
```

Observed freeze quality:

| Input | Current freeze point | Quality |
| --- | --- | --- |
| Package run ids | Package creation | fixed list |
| Run answer/reference/retrieval payload | not independently frozen by Package | current-row dependent |
| Package report payload | Package creation | stored, but excluded from package hash |
| Prompt text returned by Package API | Package read | current Prompt row preferred |
| SourceDocument content | source fetch/refetch | mutable row; overwrite possible |
| Passage | segmentation | positional JSON block; overwrite possible |
| Product Truth | manual upsert | mutable project-wide row |
| AnswerUnit/Binding | each ShadowRun | append-only rows, but latest completed exact-scope run is selected |
| SourceClaim/Alignment materialization | ledger completion | semantic cache identity, not Package lineage |
| Benchmark/Gap/Channel read models | request time | current-state dependent |
| Strategy | Candidate creation/review | partial snapshot |
| Experiment | legacy Step 8 creation | strongest current immutable snapshot set |

`OptimizationEvidencePackage.package_hash` covers run ids, target URLs,
environment snapshot and selected version manifest fields. It does not cover the
stored report payload, source content, semantic objects, reviews, Product Truth,
candidate policy or runtime feature flags.

## 5. Package #12 And #15 Current-State Evidence

Read-only database audit against the fixed database identity found:

```text
Package #12:
  deterministic canonical-hash mapped SourceDocuments = at least 152
  mapped documents updated after Package creation = 152
  run-scoped EvidenceAlignments = 32997
  alignments created/updated after Package creation = 32997
  Product Truth rows visible now = 4
  Product Truth rows updated after Package creation = 4

Package #15:
  deterministic canonical-hash mapped SourceDocuments = at least 18
  mapped documents updated after Package creation = 18
  run-scoped EvidenceAlignments = 660
  alignments created/updated after Package creation = 660
  Product Truth rows visible now = 4
  Product Truth rows updated after Package creation = 1
```

Therefore Package `12@v8` and Package `15@v2` can observe semantic state that
did not exist when the Package row was created.

## 6. Document And Passage Identity

```text
document_content_identity = mutable SourceDocument row + current clean_text_hash
passage_content_identity = positional content_blocks_json member
refetch_semantics = overwrite existing SourceDocument row when matched
historical_content_replayability = NOT_REPLAYABLE for legacy rows; PARTIAL for ledger outputs
```

Passage identity such as `doc{id}:b{block_index}` identifies a current position,
not an immutable body version. A SourceClaim keeps `source_document_id`,
`passage_id` and extracted spans, but legacy rows do not retain the full old
passage input. The Phase 0 database contained 1,290 SourceClaims across 63
documents whose creation preceded the current document `updated_at`. This is
evidence of mutable source lineage, not proof that every body changed.

## 7. Current Runtime DAG

The product Steps and runtime stages are not one-to-one.

| Runtime stage | Main reads | Main writes | Current completion signal | Can overlap |
| --- | --- | --- | --- | --- |
| Collection | Prompt/task config | Runs, references, retrievals, artifacts | Run status | separate acquisition tasks |
| Answer Semantic | current Run answer + Prompt/project | RecommendationEvent | function return / rows | no within current pipeline |
| Source Qualification | project SourceDocuments | SourceQuality | function return | no within current pipeline |
| Source Fetch | package/run references + current documents | SourceDocument | function return | external fetch may be slow |
| Segmentation | current document body | content blocks on same document row | function return | no |
| AnswerUnit/Binding | Runs, events, current config | ShadowRun, AnswerUnit, Binding | ShadowRun status | old completed runs coexist |
| SourceClaim | current passages + ledger/cache | materialization + claims | loop return; per-key failures may remain | implementation is serial |
| Candidate Builder | latest exact-scope Binding, claims, source mappings, current policy | no durable candidate manifest | function return | no |
| EvidenceAlignment | candidate set + ledger/cache | materialization + alignments | loop return; per-key failures may remain | implementation is serial |
| Benchmark/Gap | current eligible evidence/truth/package state | read model and legacy diagnosis/confirmation rows | request result / mutable confirmation | later HTTP requests |
| Channel/Resolver/Synthesis | current reconstructed strategy inputs | Candidate payload | Candidate persistence/review | explicit Step 7 action |
| Execution Proposal | accepted Candidate + current PR5 compiler inputs | ephemeral response only | response validity/readiness | explicit Step 8 read/revalidation |

The main analysis thread wraps the pipeline in one outer exception handler, but
stages and progress updates commit independently. A final `FAILED` analysis row
does not roll back earlier committed outputs.

## 8. Review Binding And History

| Review | Current binding | Output hash/version binding | History behavior |
| --- | --- | --- | --- |
| Recommendation/Decision | RecommendationEvent row id | absent | same row updated |
| Evidence | EvidenceAlignment row id/group submitted by client | absent | relation/review fields overwritten |
| Product Truth | project/brand/capability unique row | absent | same row updated |
| Gap | project/prompt/step unique WorkflowConfirmation | absent | same row updated |
| Strategy | Candidate + Package with structured/effective payload | partial | review metadata/effective payload updated on same row |
| PR5-B proposal | response payload | no persisted review object | ephemeral/unbound |

Observed review timestamp gap:

```text
#19 RecommendationEvent HUMAN_* rows = 99; reviewed_at missing = 99
#19 EvidenceAlignment HUMAN_CONFIRMED rows = 676; reviewed_at missing = 676
#40 EvidenceAlignment HUMAN_CONFIRMED rows = 36; reviewed_at missing = 36
```

Current review state cannot consistently prove which immutable output set was
reviewed. Re-confirm, correction and rejection can replace prior row state.

## 9. Current Invalidation Behavior

| Human/runtime change | Current automatic downstream invalidation |
| --- | --- |
| Product Truth correction | none for existing Gap/Strategy/Experiment |
| Recommendation/Decision correction | none for AnswerUnit/Binding/Alignment/Gap/Strategy |
| Evidence relation correction | none for Benchmark/Gap/Strategy |
| Gap confirmation change | none for Candidate |
| Strategy review change | none for an already-created Action/Experiment |
| SourceDocument refetch | materialization compatibility is local and incomplete; no DAG invalidation |

Historical outputs generally remain, but current eligibility is reconstructed
without a durable dependency graph.

## 10. Rerun And Failure Semantics

| Layer | Existing success | Existing failed/invalid | Current rerun behavior |
| --- | --- | --- | --- |
| Answer Semantic | any Event row causes skip | `VALIDATION_FAILED` also causes skip | only missing Run-event rows are considered |
| Binding | old completed ShadowRun retained | interrupted/running rows retained | create new ShadowRun; consumer selects latest completed exact run scope |
| Source fetch | any matching document causes skip | `FETCH_FAILED` also causes normal skip | explicit refetch/manual path required |
| SourceClaim | DONE ledger hit | retryable retries same ledger; final skips | missing/stale work only; legacy/cache may backfill ledger |
| EvidenceAlignment | DONE ledger hit | retryable retries; final skips | candidate-scoped incremental work; legacy rollback path can delete prompt rows |
| Benchmark/Gap | derived result can be rebuilt | older rows remain | current-state recomputation |
| Strategy | Candidate retained | pending candidates may be deferred | new Candidate; accepted/history can coexist |

```text
PARTIAL_WRITE_AFTER_RUN_FAILURE = YES
```

## 11. Version And Cache Lineage

| Layer | Current classification | Missing lineage/compatibility facts |
| --- | --- | --- |
| Answer Semantic | PARTIAL | no normalized input/output hash or stale check on existing Event |
| Binding LLM | CURRENT_CONFIG_DEPENDENT | ShadowRun summary omits top-k/use-LLM/model/prompt/schema details |
| SourceClaim materialization | PARTIAL | fields record versions; compatibility mainly checks contract + passage hash |
| Alignment materialization | PARTIAL | fields record versions; compatibility mainly checks contract + semantic hashes |
| Candidate Builder | PARTIAL | policy/top-k/tie/flag not bound to Package or persisted candidate-set manifest |
| Strategy #57 | PARTIAL_TO_STRONG | structural input/output hashes exist; no unified Runtime Context |
| Strategy #50 | LEGACY_COMPATIBILITY | PR4 contract/input/output hashes are null |

`LLMCallCache` includes provider, model, prompt version, schema version and a
hash of system prompt plus user payload. A materialization contract change alone
does not necessarily force an LLM cache miss.

## 12. Concurrency And Auditability

Current local database configuration uses SQLite WAL, a 30-second busy timeout,
`check_same_thread=false`, request-scoped sessions and a separate background
session. SQLite still has one writer at a time.

```text
review optimistic concurrency = NONE
Product Truth optimistic concurrency = NONE
Strategy review optimistic concurrency = NONE
PR5 persisted edit concurrency = NOT_APPLICABLE; edits are ephemeral
lost-update behavior = LAST_WRITE_WINS
```

Materialization provides useful local primitives: unique semantic key,
conditional claim, owner, lease expiry, retry cap, wait and zero-result DONE.
It does not provide a durable stage dependency graph, StageAttempt history,
heartbeat, cancellation, human actor identity or atomic stage output manifest.

## 13. Frontend Authority And Fallbacks

Static audit of the top-level main-chain block found:

```text
CLIENT_BUSINESS_STATE_DERIVATION_COUNT = 50
= 42 current/ready/done/history selectors and predicates
+ 8 top-level Product Step state decision trees
```

This excludes ordinary presentation/loading state and the secondary Citation
sub-step visualization.

Observed fallback classes include:

- backend Candidate ids do not match loaded candidates, then local eligible
  Candidate rows become the view source;
- missing Citation context falls back through workflow context and selected
  local package;
- PR5 without explicit Candidate id chooses a recent accepted current-origin
  Candidate across packages, then can fall back to a recent current-origin row;
- current workflow state is assembled from status, Citation detail, package,
  Candidate list and Experiment list responses with different refresh times.

## 14. Step 8 Reachable Paths

| Path | Current user reachable | Writes DB | Action | Experiment | Snapshot semantics |
| --- | --- | --- | --- | --- | --- |
| PR5-A Shadow GET + PR5-B revalidation | yes | no | no | no | ephemeral input/proposal/diff |
| legacy `POST /strategy-candidates/{id}/execution-plan` | API reachable; current UI does not submit it | yes | yes | yes | Strategy/action/asset/baseline snapshots |
| existing Experiment console | yes when Experiment already linked | status-dependent later writes | existing | existing | reads legacy snapshots |
| tests/scripts calling legacy service | developer-only | yes unless transaction isolated | yes | yes | legacy snapshots |

No background Step 8 job exists. The legacy service already expresses useful
Candidate/Package binding, fixed baseline, snapshot and release-gate behavior,
but conflicts with PR5 portfolio cardinality and new-asset lifecycle semantics.

## 15. Current Selection Registry

Business-significant current selection currently includes:

```text
EvidencePackage        -> active + greatest version/id
PromptAnalysisRun      -> greatest id
completed analysis     -> greatest completed id
Binding input          -> latest completed exact-run-scope ShadowRun
StrategyCandidate      -> newest eligible pending, else accepted matching mutable confirmation
Experiment             -> confirmed Candidate.experiment_id
PR5 default Candidate  -> newest accepted current-origin across packages, then newest current-origin
frontend package       -> Citation context, workflow context, then selectedPkgId fallback
```

Old EvidencePackages are not marked superseded in the current database. #19 has
8 active Packages; #40 has 2. #19 has 13 PromptAnalysisRuns (5 completed, 8
failed). #40 has one completed PromptAnalysisRun. Multiple Candidate and
Experiment generations coexist under the same Package.

## 16. Golden Runtime Scope

### CASE-REAL-019 Runtime Baseline

```yaml
manifest: docs/semantics/snapshots/CASE-REAL-019.manifest.json
fixed_project_id: 3
fixed_prompt_id: 19
fixed_evidence_package: 12@v8
fixed_strategy_candidate_id: 57
fixed_run_count: 40
fixed_object_id_count: 42
runtime_expectations:
  - Replay must use the 40 manifest Run ids, Package 12 and Candidate 57.
  - Latest Package, AnalysisRun, ShadowRun, Candidate or Experiment may not substitute for a fixed manifest object.
  - Package 12 alone is insufficient to freeze current SourceDocument, Product Truth, Binding and Alignment versions.
  - Candidate 57 remains historical fixed evidence even if a future current pointer targets another Context.
  - PR5-B readiness does not imply Action or Experiment creation.
```

### CASE-REAL-040 Runtime Baseline

```yaml
manifest: docs/semantics/snapshots/CASE-REAL-040.manifest.json
fixed_project_id: 3
fixed_prompt_id: 40
fixed_evidence_package: 15@v2
fixed_strategy_candidate_id: 50
fixed_run_count: 6
fixed_object_id_count: 8
runtime_expectations:
  - Replay must use the 6 manifest Run ids, Package 15 and Candidate 50.
  - Candidate 50 remains PENDING_REVIEW in the fixed observed snapshot.
  - Missing PR4 contract/input/output hashes remain null and cannot be reconstructed from latest code.
  - No #19, historical accepted Candidate or historical Experiment may become current through fallback.
  - Step 8 remains locked for the fixed current observed state.
```

Common static critical read-site summary for the audited status, Binding,
Candidate Builder and PR5 paths:

```text
latest/current selector classes = 5
project-wide read classes = 3
prompt-wide read classes = 5
package/run-scope read classes = 5
candidate-scope read classes = 2
frontend derived business states = 50
```

These counts describe audited selector/read classes, not SQL statement counts.

## 17. Historical Incident Classification

```text
SQLite database locked = OBSERVED_ONCE
review/load/strategy spinner = REPEATEDLY_OBSERVED
incorrect READY or NO_STRATEGY = REPEATEDLY_OBSERVED
historical/local Candidate display mismatch = OBSERVED_ONCE
Alignment rerun resetting review progress = OBSERVED_ONCE
planner/detail request pool exhaustion = REPEATEDLY_OBSERVED
Step 7 reconstruction over 120 seconds / 3 minutes = REPEATEDLY_OBSERVED
```

## 18. Direct Fix Candidates Outside RFC Cutover

```text
RT-FIX-001
zero Runs false complete
reason: EvidencePackage and run-analysis already reject zero valid Runs; workflow currently substitutes one.

RT-FIX-002
reviewed_at not written by confirmation paths
reason: the review timestamp field and human-confirmation meaning already exist.
```

Neither candidate is implemented or authorized by this document.

## 19. Runtime RFC Input

The observed system cannot safely answer current lineage, immutable review
target, exact replay, dependency invalidation or current authority from one
source. These are definition questions for `RFC-RUNTIME-001`, not facts that
this map resolves.
