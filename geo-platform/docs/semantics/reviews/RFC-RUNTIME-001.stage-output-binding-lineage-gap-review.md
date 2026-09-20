# RFC-RUNTIME-001 Semantic Mapping Gap Review

```yaml
rfc_id: RFC-RUNTIME-001
review_type: SEMANTIC_MAPPING_GAP_REVIEW
phase_1a_status: ACCEPTED
phase_1b_status: BLOCKED
review_date: 2026-09-10
production_cutover: NOT_AUTHORIZED
legacy_semantic_changes: 0
runtime_capture_changes: 0
schema_changes: 0
production_database_writes: 0
decision: BLOCKED_BY_LEGACY_SEMANTIC_AMBIGUITY
```

## Review Question

This review answers only:

1. What is the candidate canonical execution output of each Legacy Stage?
2. What persisted fact proves each output's exact binding and dependency
   lineage?

The review inspected production call-sites, model relationships, read-only SQL
against `backend/geo_v0.db`, the fixed Package `12@v8` / Package `15@v2`
scopes, tests and fixtures. It did not implement Phase 1B, alter the Frozen
RFC, backfill lineage, or accept a latest/current inference as proof.

## Classification Rules

```text
A = IMPLEMENTATION_GAP
B = OBSERVABILITY_GAP
C = HISTORICAL_DATA_GAP
D = FROZEN_CONTRACT_GAP
E = LEGACY_SEMANTIC_AMBIGUITY
```

Several rows have independent gaps, so the matrix lists all applicable
classes. `D` and `E` are never treated as instrumentation work. A mapping is
"reconstructable" only when the complete canonical output and every exact
dependency edge can be proven without latest, fallback, current-state or
post-hoc matching.

## Stage Matrix

| Stage | Legacy execution boundary | Legacy write objects | Candidate canonical output | Output identity source | Output immutability | Explicit upstream bindings | Binding identity source | Lineage persisted | Reconstructable without latest | Mapping unambiguous | Gap classification | Mapping result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `RUN_METRICS` | `create_evidence_package()` builds report then commits Package | `OptimizationEvidencePackage` | `RunMetricsManifest`: one member per metric/scope/denominator | Package payload metric paths plus exact metric config; new output hash required | PARTIAL: Package persists payload, but `package_hash` excludes report payload and Root rows are mutable | Run, Reference, Retrieval, TargetUrl Root members | `source_run_ids_json` and in-memory rows at package creation | PARTIAL: Run IDs persist; observation IDs and consumed hashes do not | NO for full lineage; fixed Package can recover only a partial projection | YES prospectively at package builder boundary | A, B, C | `MAPPABLE_WITH_NON_SEMANTIC_INSTRUMENTATION` |
| `ANSWER_SEMANTIC` | `run_answer_semantic()` commits event rows; outer pipeline later updates `PromptAnalysisRun` | `RecommendationEvent`; aggregate `PromptAnalysisRun` envelope | `AnswerSemanticManifest`: recommendation/decision members plus a terminal result for every Run | Run + answer snapshot + span + ordinal, but Frozen `member_kind` literals are undefined | NO: review fields mutate rows; successful zero is not a row | Prompt snapshot, Run answer snapshot, extractor config | `run_id`, `answer_hash`, prompt/model/version fields | PARTIAL for nonzero events; zero and failure both leave no member; no execution FK | NO | NO under the Frozen output contract | D, B, C | `REQUIRES_RFC_AMENDMENT` |
| `PRODUCT_TRUTH_PROJECTION` | `_current_answer_decision_evidence_gap_action()` / Strategy context text-match Reasons to current truth rows | No independent write; truth IDs/hints later enter Candidate JSON | `ProductTruthProjectionManifest`: per-Reason BOUND fact-version, UNRESOLVED or CONFLICT | Reason identity + formal binding + immutable fact-value version | NO: `TargetBrandCapabilityTruth` is mutable and has no fact-value version; Candidate stores only a later projection | Answer Semantic Reason, target-brand version, binding manifest, fact-value version, authoritative review | Legacy has only text match + mutable truth row ID/status | NO formal Reason/Truth binding or fact/review version | NO | NO: Legacy cannot prove that a heuristic match is the reviewed binding required by Frozen Runtime | D, E, C | `REQUIRES_LEGACY_SEMANTIC_CHANGE` |
| `BINDING` | `run_answer_evidence_shadow_chain()` creates one ShadowRun, then units and bindings | `AnswerEvidenceShadowRun`, `AnswerUnit`, `AnswerDecisionBinding` | `BindingManifest`: binding or explicit NONE/LOW for every eligible AnswerUnit | AnswerUnit + RecommendationEvent + scope/ordinal | PARTIAL: child rows persist but reviews mutate and no output manifest/hash exists | Frozen: prior Answer Semantic AnswerUnit/Reason output; Root observations; config | Legacy FKs bind a row to the same ShadowRun's newly created AnswerUnit and an Event | LOCAL ROW LINKS only; no upstream Stage output ref/hash | NO | NO: AnswerUnit is produced inside the would-be Binding execution, not by the required upstream Stage | D, C | `REQUIRES_RFC_AMENDMENT` |
| `SOURCE_QUALIFICATION` | Main pipeline calls `run_source_qualification(db, project)` with no `doc_ids`; function queries every SourceDocument | `SourceQuality`; ownership remains computed only | `SourceQualificationManifest`: qualification per Root observation/canonical source | Root observation + canonical source + content hash + rule key | PARTIAL for quality row; ownership and Root binding are not persisted | Root Reference/Retrieval observation and canonical source identity | None in the call; `project` does not constrain the document query | NO Root-to-document/output edge | NO | NO: a global invocation cannot identify a unique Prompt/Run output partition | D, E, C | `REQUIRES_LEGACY_SEMANTIC_CHANGE` |
| `SOURCE_FETCH` | `acquire_cited_sources(run_ids)` commits only newly fetched URLs and silently reuses existing documents | `SourceDocument` for new URLs only | `SourceFetchManifest`: one immutable content/failure version per canonical source | Canonical source identity + exact fetched content hash/version | NO: one mutable SourceDocument row; stored acquisition hash is truncated; reused content has no consumption record | Frozen Source Qualification output plus acquisition config/environment | Run-scoped refs are visible in memory; no persisted observation-to-content-version edge | NO | NO | NO: new documents are created after the preceding qualification call, so Frozen `SOURCE_QUALIFICATION -> SOURCE_FETCH` cannot be true for them | D, B, C | `REQUIRES_RFC_AMENDMENT` |
| `SEGMENTATION` | `segment_all_documents(doc_ids=...)` mutates blocks and commits | `SourceDocument.content_blocks_json` in place | `SegmentationManifest`: source content-version + passage ordinal members | Exact input content hash + block ordinal + segmentation config | NO in Legacy; blocks are overwritten | Exact Source Fetch output/content version | Explicit `doc_ids` argument at the call boundary only | NO Stage edge or immutable content version | NO historically | YES prospectively if the Source Fetch dependency is first made legal | A, B, C | `MAPPABLE_WITH_NON_SEMANTIC_INSTRUMENTATION` |
| `SOURCE_CLAIM` | `run_source_claim_extraction()` commits ledger state and per-passage claims | `SourceClaimMaterialization`, `SourceClaim` | `SourceClaimManifest`: claim ordinal members and explicit successful zero/failure per passage | Passage member identity + ordered materialization payload | PARTIAL: output hash/zero exist; observed document/passage IDs and linked claim IDs are appended across executions | Segmentation passage and Source Qualification output | In-memory materialization jobs; ledger stores semantic cache identity and accumulated observations | CACHE lineage only, not Stage execution lineage | NO: ledger unions multiple observations and passages are mutable | YES prospectively at the materialization job boundary, conditional on legal upstream refs | A, B, C | `MAPPABLE_WITH_NON_SEMANTIC_INSTRUMENTATION` |
| `ALIGNMENT_CANDIDATE_BUILD` | `build_evidence_alignment_candidates()` returns inside `run_evidence_alignment()` | None | `AlignmentCandidateManifest`: every selected and omitted Reason/Claim pair with decision reason | Reason semantic hash + SourceClaim semantic hash + policy/config | EPHEMERAL | Binding, SourceClaim, Source Qualification outputs | In-memory Reason observations, claims, Run/document maps | NO; dry-run exposes selected keys but no durable complete omission manifest | NO historically | YES prospectively, but hard-filtered pairs need per-pair observer records instead of aggregate counters | A, B, C | `MAPPABLE_WITH_NON_SEMANTIC_INSTRUMENTATION` |
| `EVIDENCE_ALIGNMENT` | `run_evidence_alignment()` consumes candidate set, commits materialization and observation rows | `EvidenceAlignmentMaterialization`, `EvidenceAlignment` | `EvidenceAlignmentManifest`: verdict per selected Reason/Claim pair, including negative/zero terminal outcomes | Same pair identity as Candidate output | PARTIAL: materialized verdict has hash; observed Run/Prompt/row IDs accumulate; review fields mutate | Candidate output plus exact Reason and SourceClaim outputs | In-memory selected key; row FKs; semantic ledger key | Observation/cache links only; no Stage dependency edge | NO | YES prospectively at the selected candidate/materialization boundary, conditional on legal upstream refs | A, B, C | `MAPPABLE_WITH_NON_SEMANTIC_INSTRUMENTATION` |
| `BENCHMARK` | Step 7 helper chain annotates source rows before action/Candidate creation | No independent write; selected fields later enter Candidate JSON | `BenchmarkManifest`: Reason + canonical source outcome, including no-benchmark | Reason identity + canonical source identity + benchmark rules | EPHEMERAL until embedded in mutable Candidate payload | Evidence Alignment and Source Qualification outputs | In-memory row plus supporting Alignment IDs | PARTIAL JSON projection only; no independent manifest or Stage refs | NO | YES prospectively at the helper checkpoint, conditional on legal upstream refs | A, B, C | `MAPPABLE_WITH_NON_SEMANTIC_INSTRUMENTATION` |
| `GAP` | Step 7 helper chain builds `gap_items`; separate API upserts one Prompt-level confirmation | `WorkflowConfirmation` singleton; gap JSON later enters Candidate | `GapManifest`: one outcome per Reason plus exact authoritative review target | Deterministic `gap_item_id` / Reason identity | NO independent output; confirmation is overwritten | Metrics, Answer Semantic, Product Truth, Alignment, Benchmark and authoritative Gap review | Candidate JSON contains some IDs; confirmation has only project/prompt/`step_key=gap` | NO output-target reference on confirmation | NO | NO for reviewed Gap: the confirmation cannot identify which generated Gap set it approved | E, C | `REQUIRES_LEGACY_SEMANTIC_CHANGE` |
| `CHANNEL_EVIDENCE` | `build_channel_evidence_landscape()` / Step 7 aggregation returns deterministic landscape | No independent write; landscape/signals later enter Candidate JSON | `ChannelEvidenceManifest`: signal members with channel and source provenance | Channel + signal type + source ref/hash | EPHEMERAL until Candidate JSON | Source Qualification, SourceClaim and Alignment outputs | In-memory source/alignment IDs and run observations | PARTIAL JSON projection only | NO | YES prospectively with explicit Package and upstream Stage refs | A, B, C | `MAPPABLE_WITH_NON_SEMANTIC_INSTRUMENTATION` |
| `CHANNEL_RESOLUTION` | `build_channel_resolution_context()` then `resolve_channel_shadow()` | No independent write; resolver result later enters Candidate JSON | `ChannelResolutionManifest`: Role/OBSERVE/exclusion/UNKNOWN per channel | `channel_key` + resolver config/version | EPHEMERAL until Candidate JSON | Product Truth projection, Gap and Channel Evidence outputs | In-memory context and signal IDs | PARTIAL result/version in Candidate; no dependency refs | NO | YES prospectively with explicit Package/action and legal upstream refs | A, B, C | `MAPPABLE_WITH_NON_SEMANTIC_INSTRUMENTATION` |
| `STRATEGY_SYNTHESIS` | constraint-first core validates structure; `_create_vertical_strategy_candidate()` commits Candidate | `OptimizationStrategyCandidate`; Prompt-level strategy confirmation is also updated | `StrategyManifest`: header, Themes and channel portfolio | Candidate ID plus validated input/output hashes and member identities | PARTIAL: machine/effective payloads coexist in one mutable row; exact Candidate is persisted | Metrics, Answer Semantic, Product Truth, Benchmark, Gap, Channel Resolution | Package/Candidate IDs and synthesis audit IDs/hashes | PARTIAL; upstream Stage refs absent and review is not append-only | NO for full lineage | YES prospectively at validated synthesis and exact Candidate review boundaries, conditional on legal upstream refs | A, B, C | `MAPPABLE_WITH_NON_SEMANTIC_INSTRUMENTATION` |
| `EXECUTION_PROPOSAL` | `run_execution_proposal_shadow()` returns an ephemeral portfolio | None | `ExecutionProposalManifest`: header, per-channel asset proposal and portfolio decision | Explicit accepted Strategy candidate + proposal key/ordinal + compiler config | EPHEMERAL | accepted Strategy review, baseline Metrics, Product Truth projection, exact asset snapshot | Explicit `candidate_id` can identify Candidate; omitted ID invokes latest/current fallback; mutable truths are reread | NO | NO | NO for the Stage as exposed: omitted Candidate and current truth/asset reads are allowed and no durable output exists | E, B, C | `UNMAPPABLE` |

## Canonical Output Findings

### Outputs with a real prospective boundary

The following Legacy functions have enough information at the moment they run
to derive their candidate output without rerunning domain logic:

```text
RUN_METRICS
SEGMENTATION
SOURCE_CLAIM
ALIGNMENT_CANDIDATE_BUILD
EVIDENCE_ALIGNMENT
BENCHMARK
CHANNEL_EVIDENCE
CHANNEL_RESOLUTION
STRATEGY_SYNTHESIS
```

They are not `MAPPABLE_AS_IS`: none persists a Frozen Stage output manifest and
exact Stage dependency set. They are only candidates for non-semantic observer
instrumentation, and every downstream item remains blocked until its upstream
Stage references are legal.

`SOURCE_CLAIM` and `EVIDENCE_ALIGNMENT` ledgers are semantic computation
ledgers, not Stage output ledgers. In the real database, 5 of 91 SourceClaim
materializations contain multiple observed document IDs and 47 of 119
Alignment materializations contain multiple observed Run IDs. This is expected
for cache reuse, but proves the accumulated observation arrays cannot identify
one execution's exact input or output partition.

### Frozen contract decisions required

`ANSWER_SEMANTIC` cannot be encoded without defining the closed
`member_kind` set and a per-Run terminal zero/failure representation.

`BINDING` cannot consume a prior AnswerUnit output because Legacy creates the
AnswerUnit inside the same ShadowRun that creates the Binding. Definition
Review must choose whether AnswerUnit belongs to `ANSWER_SEMANTIC`, whether a
separate Stage is required, or whether the Binding input contract changes.

`SOURCE_FETCH` exposes the inverse production fact from the Frozen dependency:
the main pipeline qualifies the existing global document table, then fetches
new documents. A new document therefore cannot be proven to consume that
invocation's Source Qualification output. The RFC must decide the canonical
meaning/order before any code change.

`PRODUCT_TRUTH_PROJECTION` also conflicts with the Frozen formal binding
requirement: current code text-matches Reasons to mutable project truth rows.
The Candidate's IDs are useful hints, but they are not an authoritative
Reason/ProductTruth binding or immutable fact-value version.

### Legacy semantic ambiguity

These are not observer omissions:

- `SOURCE_QUALIFICATION` processes all SourceDocuments because the production
  call omits `doc_ids`. The invocation has no unique Prompt/Run partition and
  no Root observation binding.
- `PRODUCT_TRUTH_PROJECTION` has no formal reviewed binding object. A heuristic
  text match cannot be relabeled as BOUND.
- `GAP` review upserts one `(project_id, prompt_id, step_key)` row. The request
  carries no Gap output identity, hash or member set, so the row cannot answer
  which Gap execution it confirmed.
- `EXECUTION_PROPOSAL` permits omitted `candidate_id`, resolves a current/latest
  Candidate, rereads mutable Product Truth rows, and has no persisted proposal
  output. Only an explicitly identified Candidate invocation could later be
  considered for a reduced mapping.

Resolving these facts requires a real Legacy contract/API boundary change or a
new authoritative object. A Runtime observer cannot supply the missing answer.

## Illegal Mapping Pattern Audit

| Forbidden pattern | Observed Legacy location | Review decision |
| --- | --- | --- |
| latest Package substitution | workflow/package resolvers order active Packages by version/ID when ID omitted | REJECTED as lineage |
| latest Snapshot substitution | historical snapshot/read models have current/latest readers but no selected Stage edge | REJECTED as lineage |
| latest StrategyCandidate substitution | `_candidate_and_mode(..., candidate_id=None)` orders Candidates newest first | REJECTED; makes general `EXECUTION_PROPOSAL` unmappable |
| project-level fallback | `run_source_qualification()` queries all SourceDocuments; Product Truth selection is project-scoped | REJECTED |
| prompt-level fallback without binding | `WorkflowConfirmation(step_key="gap")` and current workflow state | REJECTED |
| post-hoc DB reconstruction | matching source observations to current SourceDocument or Candidate JSON slices | Audit hint only; never exact lineage |
| timestamp-nearest matching | no exact contract permits it | REJECTED |
| ID-max matching | latest Package/Candidate/ShadowRun readers use descending IDs | REJECTED |
| current-state inference | mutable Product Truth, review and document rows | REJECTED |

No row selected by one of these patterns is promoted to an exact dependency.

## Read-only Database Evidence

Database identity before review:

```text
backend/geo_v0.db
SHA-256 = fb24d2f074912415219397e7325007439644432cbfa6250b694137d1834900d3
```

Fixed execution-envelope evidence:

| Package | Prompt | Runs | Event Runs | AnswerClaim Runs | AnswerUnit Runs | Binding Runs | PromptAnalysisRun envelopes | ShadowRun envelopes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `12@v8` | 19 | 40 | 37 | 12 | 12 | 12 | 13 | 13 |
| `15@v2` | 40 | 6 | 6 | 6 | 6 | 6 | 1 | 7 |

Equal #40 counts do not establish an upstream edge. #19 demonstrates why a
shared Run scope cannot substitute for object lineage.

Source identity diagnostic, using only stored canonical URL hashes from the
fixed Run observations:

| Package | Observation identities | Matched identities | Missing | Multiple document matches | Matched document rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| 12 | 272 | 148 | 124 | 4 | 152 |
| 15 | 68 | 21 | 47 | 0 | 21 |

This query is diagnostic only. It is not used to reconstruct Source
Qualification or Fetch lineage. The missing and multiple matches demonstrate
why post-hoc URL matching cannot become exact binding proof.

Candidate/review facts:

```text
Candidate #57 -> Package 12, ACCEPTED, mutable row updated after creation
Candidate #50 -> Package 15, PENDING_REVIEW, no effective payload version
#19 Gap confirmation -> one Prompt-level CONFIRMED row, no target output ref
#40 Gap confirmation -> no row
```

All SQL was executed with `sqlite3 -readonly`. No production row was written.

## Validation

```text
runtime_projection_spike.py = SPIKE_PASS
normative vectors = 3/3 MATCH
#19 completeness = 0 COMPLETE / 6 PARTIAL / 9 UNSAFE / 1 UNAVAILABLE
#40 completeness = 0 COMPLETE / 7 PARTIAL / 8 UNSAFE / 1 UNAVAILABLE
#19/#40 stage expectation diff = 0 / 0
latest substitution = 0
semantic invention = 0
projection DB writes = 0
Phase 1A persistence/projection tests = 16 passed
git diff --check = PASS
production DB SHA-256 after = fb24d2f074912415219397e7325007439644432cbfa6250b694137d1834900d3
```

## Required Disposition

### 1. Stages that can continue Phase 1B as-is

```text
NONE
```

No Stage already exposes a complete immutable canonical output plus exact
dependency edge set.

### 2. Stages whose own gap is only instrumentation

```text
RUN_METRICS
SEGMENTATION
SOURCE_CLAIM
ALIGNMENT_CANDIDATE_BUILD
EVIDENCE_ALIGNMENT
BENCHMARK
CHANNEL_EVIDENCE
CHANNEL_RESOLUTION
STRATEGY_SYNTHESIS
```

Only `RUN_METRICS` is dependency-independent enough to be a possible isolated
reduced capture. The others may not start while their required upstream Stage
outputs remain unresolved.

### 3. Stages requiring targeted RFC amendment

```text
ANSWER_SEMANTIC
BINDING
SOURCE_FETCH
PRODUCT_TRUTH_PROJECTION migration/compatibility treatment
```

The amendment must define output membership, zero/failure identity, AnswerUnit
ownership, Fetch/Qualification order and how non-formal legacy truth hints are
represented. It must not bless current/latest inference.

### 4. Stages exposing Legacy semantic ambiguity

```text
PRODUCT_TRUTH_PROJECTION
SOURCE_QUALIFICATION
GAP review lineage
EXECUTION_PROPOSAL when candidate_id is omitted
```

These need explicit Legacy semantic/API changes after Definition Review; an
observer-only implementation cannot repair them.

### 5. Can Phase 1B continue with reduced scope?

Only a `RUN_METRICS`-only technical slice is independently mappable. It does
not exercise Stage dependency capture, Review lineage, downstream STALE, or a
complete Step 1-8 chain, and therefore does not satisfy the authorized Phase
1B acceptance objective. It must not be started under the current authorization
merely to claim Phase 1B progress.

### 6. Must the RFC reopen?

```text
YES
```

A targeted amendment is required for the Frozen contract gaps. It is necessary
but not sufficient: the Product Truth, global qualification, Gap review and
implicit execution-proposal selection ambiguities also require separately
authorized Legacy semantic changes. No amendment may manufacture historical
lineage.

## Decision

```text
BLOCKED_BY_LEGACY_SEMANTIC_AMBIGUITY
```

Phase 1B remains stopped. Phase 1C, Cutover, historical backfill, production
Runtime writes and PR5-C remain forbidden.
