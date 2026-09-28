# 08 Development Log

Status: ACTIVE

## 2026-09-22 V2 Evidence Review Handoff Clarity

- Classified as `IMPLEMENTATION_CHANGE` under the exact-version review and
  Evidence lineage contracts. No Evidence verdict, candidate scope, Product
  Truth, Strategy or immutable result semantics changed.
- Fixed the Answer-to-Evidence review handoff. An Answer event already made
  consumable by the exact bound Answer Review keeps its original machine
  `SEMANTIC_REVIEW_REQUIRED` audit status, but no longer requires the operator
  to repeat the same Answer decision when reviewing the new
  `ANSWER_AND_EVIDENCE` ResultVersion.
- The current Evidence ResultVersion still requires its own review. That review
  covers newly computed SourceClaim/Alignment output plus preserved failures,
  non-evaluated relations and anchor limitations; it does not inherit approval
  for those new objects from the Answer-only review.
- Added a V2 analysis progress strip and a focused Evidence review summary. The
  UI now separates recalled/evaluated relations, SourceClaim admission failures
  and normal candidate pruning, and translates relation/evaluation states into
  operator-facing Chinese labels.
- Added regression coverage proving that an exact, human-confirmed Answer event
  is not re-reviewed in the Evidence ResultVersion while an unreviewed event
  remains blocked.

## 2026-09-04 Phase E Workflow Status Orphan Failure Fallback

- Fixed `workflow/status` so a latest `PromptAnalysisRun(status=FAILED)` caused
  by local service restart cleanup does not permanently mask an already
  completed current chain. The fallback is intentionally narrow: the failed run
  must contain the restart-interruption marker, a completed analysis run for the
  same Prompt must already exist, and current human review gates must be done.
- Non-restart failures, parse/model errors, and missing-review states still
  surface as `CURRENT_ANALYSIS_FAILED` / locked Step 7. This keeps real current
  analysis failures visible while allowing orphan restart rows to fall through
  to the authoritative current evidence/package/strategy state.
- Added regression coverage for a completed formal V1.1 chain followed by a
  restart-interrupted failed run.
- Diagnosed #19's remaining V1.1 blocker: latest Shadow runs created
  `AnswerUnit` rows but zero `AnswerDecisionBinding` rows. Two conservative
  Binding fixes were added:
  - `INCLUDE_AS_OPTION` is now treated as a recommendation event speech act in
    the V1.1 Shadow binding builder.
  - When entity inheritance is unavailable, a same-run grounded AnswerUnit can
    bind through an explicit `RecommendationEvent.reasons_json` reason span /
    normalized reason substring overlap. This deterministic
    `RULE_REASON_SPAN_ANCHOR` path does not call the binding LLM and still
    excludes `PROCEDURE` units.
- Fixed the frontend "no response" symptom during #19 V1.1 generation. The
  formal V1.1 run used `run_answer_evidence_shadow_chain(...)` to produce
  AnswerUnit / AnswerDecisionBinding input, but the helper also executed the
  audit-only Shadow Source Chain. That chain can call SourceClaim / Alignment
  LLM while the visible stage remains `ANSWER_BINDING`, making the page look
  stuck before formal SourceClaim / EvidenceAlignment begins. Added
  `run_source_chain=False` for the formal V1.1 pipeline; manual Shadow audit
  still defaults to the full source chain.
- Added SourceClaim production-stage progress reporting. Formal V1.1
  `run-analysis` now passes a lightweight `progress_callback` into
  `run_source_claim_extraction(...)`, and the backend writes processed/total
  materialization jobs, ledger HITs, external LLM attempts, and failures into
  the active `PromptAnalysisRun.errors_json` stage payload. Failed DeepSeek
  attempts are counted as external calls so the status does not falsely report
  `0` while a real model call is timing out or returning invalid JSON.
  `workflow/status` can therefore show SourceClaim movement during a long run
  instead of leaving Step 7 with a static spinner while the backend is still
  processing.
- Added the same observational progress channel for formal
  `run_evidence_alignment(...)`: processed/total candidate pairs, ledger HITs,
  external Alignment LLM attempts, and failures are written into the active
  analysis stage payload. This does not change the Binding-aware candidate
  builder, verdict materialization, review carry-forward, Benchmark, Gap,
  Strategy, Action, or Experiment semantics.
- Fixed the post-review #19 frontend state derivation. After evidence review
  reached 24/24, `workflow/status` correctly returned `READY_TO_GENERATE`, but
  the full `citation-decision-v1` detail request could still time out on #19.
  The single-Prompt cards treated the missing detail payload as an empty
  Citation Decision and rendered `0 current sources / no strategy`. Step 4-8
  cards now treat `workflow/status` as the authoritative gate source; full
  Citation Decision data is used only when it actually loaded.
- Tightened the same fallback in the workflow footer and strategy detail mini
  Steps. A non-blocking `citation-decision-v1` detail failure now shows
  "full detail not loaded" while preserving `READY_TO_GENERATE`; it no longer
  emits a red citation-chain business error or a "waiting/no strategy" Step 7
  state when `workflow/status` already proves the current evidence package is
  ready for StrategyCandidate generation.
- Decoupled the Step 7 "generate StrategyCandidate" button from the heavy
  `citation-decision-v1` detail refresh. When `workflow/status` is already
  `READY_TO_GENERATE`, the frontend now posts directly to the current Step 7
  generation endpoint with the current Evidence Package id, and refreshes only
  workflow/status plus strategy lists afterward. This prevents #19 from spinning
  for a full detail preflight/post-refresh before the actual Step 7 result is
  visible.

## 2026-09-03 Phase C2-A.3 Final Cutover Gate

- Added shadow-only `POLICY_D_TOPK_WITH_BOUNDARY_TIES` to the Binding-aware
  Candidate Builder planner. The policy keeps the plain TopK set plus all
  candidates in the Kth score tie bucket, using the planner's 4-decimal score
  bucket and an explicit epsilon instead of candidate id, insertion order, or
  database row order.
- Added L3 boundary-tie diagnostics:

```text
candidate_count_before_topk
top_k
cutoff_score
boundary_tie_count
boundary_rank_start / boundary_rank_end
candidate_count_after_plain_topk
candidate_count_after_tie_expansion
```

- Added strict L0 status and semantics explanation. For #19 the change from
  earlier diagnostic `L0=107` to current `L0=0` is classified as
  `SHADOW_LOGIC_CHANGED_AS_DESIGNED`: L0 now only means high/medium explicit
  AnswerDecisionBinding; broad run-local recall is owned by L2.
- Added read-only final shadow re-aggregation:
  - Evidence relation summary from current vs selected Policy D candidate keys;
  - Benchmark core summary using existing eligible EvidenceAlignment lineage;
  - current persisted Gap and Strategy summaries without recomputation or writes.
- Local real DB shadow:

```text
#19
current=583, proposed=92, shared=92, old_only=491, new_only=0
Policy A: candidates=79, TRUE_POSITIVE_RECALL_LOSS=1, external_llm_estimate=60
Policy B: candidates=145, TRUE_POSITIVE_RECALL_LOSS=0, external_llm_estimate=69, LEGACY_UNPROVEN retained=7
Policy C: candidates=92, TRUE_POSITIVE_RECALL_LOSS=0, external_llm_estimate=61, LEGACY_UNPROVEN retained=3
Policy D: candidates=92, TRUE_POSITIVE_RECALL_LOSS=0, external_llm_estimate=61, LEGACY_UNPROVEN retained=3
boundary_tie claim #267: rank=6, score=0.2222, cutoff=0.2222, tie bucket=rank 5..10
Recall: L0=0, L1=0, L2=28, L3=64
Downstream: Evidence changed=true, Benchmark core changed=false, Gap changed=false, Strategy changed=false
C2_CUTOVER_READY=true, cutover_allowed=false

#40
current=65, proposed=65, shared=65, old_only=0, new_only=0
Policy A/B/C/D: candidates=65, TRUE_POSITIVE_RECALL_LOSS=0, external_llm_estimate=15
Recall: L0=65, L1=0, L2=0, L3=0
Downstream: Evidence changed=false, Benchmark core changed=false, Gap changed=false, Strategy changed=false
C2_CUTOVER_READY=true, cutover_allowed=false
```

- Boundary:
  - formal `run_evidence_alignment(...)` was not changed;
  - no LLM calls;
  - no formal EvidenceAlignment rows written;
  - no historical Alignment review/verdict mutation;
  - no Benchmark / Gap / Strategy / Step 7 / Step 8 behavior changed;
  - no C2-B cutover.

## 2026-09-03 V1.1 Incremental Materialization Phase C1 EvidenceAlignment Ledger

- Recorded Phase B as conditionally accepted and implementation-frozen:

```text
Phase B Implementation: FROZEN
Phase B Automated Tests: PASS
Phase B Planner Conservation: PASS
Phase B Production Smoke: BLOCKED_EXTERNAL_POLICY
Phase B Overall: CONDITIONALLY_ACCEPTED
PHASE_B_PRODUCTION_SMOKE_DEFERRED remains open for the existing 9 FAILED_RETRYABLE keys
```

- Started Phase C1 only. No EvidenceAlignment candidate generation, Binding
  Recall Ladder, Benchmark, Gap, Strategy, Step 7, Step 8, or SourceClaim Phase
  B semantics were changed.
- Added `EvidenceAlignmentMaterialization` as the C1 verdict ledger:

```text
materialization_key
answer_unit_semantic_hash
source_claim_semantic_hash
contract_version
status
verdict
rationale / confidence_raw / output_payload_json
source_alignment_ids_json
observed_prompt_ids_json
observed_run_ids_json
judge_impl_version
prompt_version / schema_version
provider / model
attempt_count
started_at / completed_at
```

- Confirmed current EvidenceAlignment LLM semantic input:

```text
system_prompt=ALIGNMENT_SYSTEM
user_payload={"reason": normalized_reason_text, "source_claim": normalized_source_claim_text}
prompt_version=evidence_alignment.v1
schema_version=v1
model=settings.deepseek_model
```

  Run ID, Evidence Package, StrategyCandidate, raw AnswerUnit ID, raw
  SourceClaim ID, Prompt Intent, Prompt Intent Embedding, Benchmark, Gap, and
  experiment context are excluded from the materialization identity.
- Rewired the existing `run_evidence_alignment(...)` service to use lookup-first
  materialization for judge-needed pairs:

```text
current candidate pair
-> compatible DONE ledger hit
-> safe legacy EvidenceAlignment row backfill
-> LLMCallCache recovery into DONE ledger
-> existing EvidenceAlignmentJudge call for missing / failed
-> current EvidenceAlignment observation rows
```

- `SUPPORTS`, `NO_SUPPORT` / `NONE`, `RELATED`, and `CONTRADICTS` are all
  successful `DONE` materializations when returned by the judge.
- Planner now reports C1 ledger-aware fields:

```text
unique_alignment_inputs
alignment_materialization_dedupe_ratio
materialization_hit_count
legacy_reuse_count
missing_llm_call_cache_hit
lookup_first_llm_required
object_conservation
missing_conservation
llm_input_contract
```

- Local real DB read-only planner baseline:

```text
#19 / Evidence Package #12 v8 / 40 Runs
Alignment: semantic_reasons=27, source_claim_candidates=358
Alignment: naive_pairs=9666, after_recall=188, unique_alignment_inputs=188
Alignment: materialization_hit_count=0, legacy_reuse_count=19, missing_count=169
Alignment: missing_llm_call_cache_hit=0, lookup_first_llm_required=169
Alignment: object_conservation.is_balanced=true
Alignment: missing_conservation.is_balanced=true

#40 / Evidence Package #15 v2 / 6 Runs
Alignment: semantic_reasons=5, source_claim_candidates=46
Alignment: naive_pairs=230, after_recall=65, unique_alignment_inputs=65
Alignment: materialization_hit_count=0, legacy_reuse_count=50, missing_count=15
Alignment: missing_llm_call_cache_hit=0, lookup_first_llm_required=15
Alignment: object_conservation.is_balanced=true
Alignment: missing_conservation.is_balanced=true
```

- Added C1 tests for SUPPORTS / NO_SUPPORT / CONTRADICTS second-run 0 LLM,
  repeated semantic AnswerUnit reuse, repeated semantic SourceClaim reuse,
  entity/polarity key separation, implementation upgrade compatibility,
  breaking-contract staleness, LLMCallCache recovery into ledger, legacy
  alignment recovery into ledger, and historical materialization not creating
  current membership.

Validation:

```text
.venv/bin/python -m pytest -q tests/test_incremental_materialization_planner.py tests/test_evidence_alignment.py tests/test_source_claim.py tests/test_workflow_review_queue.py
54 passed
```

## 2026-09-02 V1.1 Incremental Materialization Phase B Closure

- Added explicit SourceClaim planner conservation fields:

```text
object_conservation
missing_no_external_llm_breakdown
missing_conservation
llm_input_contract
```

- The previous fixed `missing_count - lookup_first_llm_required = 8` delta is
  now explained as `missing_llm_call_cache_hit=8`, not an unknown planner loss.
- Local real DB read-only planner check before production-smoke attempt:

```text
#19
missing_count=1393
missing_unique_llm_inputs=1393
lookup_first_llm_required=1385
missing_llm_call_cache_hit=8
missing_conservation.is_balanced=true
object_conservation: 1462 = 0 materialization_hit + 69 legacy_reuse + 1393 missing

#40
missing_count=537
missing_unique_llm_inputs=537
lookup_first_llm_required=529
missing_llm_call_cache_hit=8
missing_conservation.is_balanced=true
object_conservation: 547 = 0 materialization_hit + 10 legacy_reuse + 537 missing
```

- Confirmed current SourceClaim LLM semantic input:

```text
system_prompt=SOURCE_CLAIM_SYSTEM
user_payload={"passage": normalized_passage_text}
prompt_version=source_claim.v1
schema_version=v1
model=settings.deepseek_model
```

  No URL, title, heading, section, source metadata, Prompt text, Run ID, target
  brand, or evidence context is sent to the SourceClaim LLM. URL/domain only
  participate in post-extraction ownership provenance and referential-subject
  SourceClaim row binding.
- Added a deterministic production-smoke limiter to the formal
  `run_source_claim_extraction(...)` service:

```text
materialization_key_filter
max_materialization_jobs
external_llm_required_only
```

  This does not create a mock path; it still uses the same retrieval, ledger,
  LLM cache, SourceClaimJudge, and SourceClaim persistence flow.
- Attempted a small real production smoke:

```text
#19: selected 5 external-LLM-required keys
#40: selected 4 external-LLM-required keys
```

  The local sandboxed run could not reach DeepSeek and wrote retryable failures:

```text
DeepSeek 网络错误（重试3次后）: ConnectError
ledger_status_counts={FAILED_RETRYABLE: 9}
```

  Post-failure planner state remains conserved:

```text
#19: MISSING=1388, LEGACY_REUSABLE=69, FAILED_RETRYABLE=5
#40: MISSING=533, LEGACY_REUSABLE=10, FAILED_RETRYABLE=4
```

- External privileged rerun was blocked by environment policy because it would
  send real project passages to DeepSeek. Phase B is therefore not marked
  frozen yet; it is waiting only on an explicitly approved small external LLM
  smoke using the existing 9 retryable keys or another capped key set.

Validation:

```text
.venv/bin/python -m pytest -q tests/test_incremental_materialization_planner.py tests/test_source_claim.py
16 passed
```

## 2026-09-02 V1.1 Incremental Materialization Phase B SourceClaim Ledger

- Implemented Phase B for SourceClaim incremental materialization only.
- Added `SourceClaimMaterialization` as a SourceClaim-specific extraction
  ledger with a unique `materialization_key`.
- Rewired the existing `run_source_claim_extraction(...)` service to:

```text
required passage rows
-> group by SourceClaim materialization key
-> reuse compatible DONE ledger output
-> reuse completed zero-claim DONE output
-> lazily backfill safe legacy SourceClaim rows
-> call the existing SourceClaimJudge only for missing/stale/failed keys
-> persist 0..N SourceClaim rows idempotently
```

- Zero-claim extraction is now represented as:

```text
status=DONE
claim_count=0
output_payload_json={"claims":[]}
```

  so the second identical run does not call LLM again.
- The materialization key is based on `SOURCE_CLAIM_V1` and the normalized
  passage extraction input hash. It deliberately excludes `run_id`,
  `prompt_id`, `evidence_package_id`, and `SourceClaim.id`.
- Implementation metadata (`extractor_impl_version`, prompt/schema, provider,
  model) is recorded for audit. The compatibility resolver treats same-contract
  implementation upgrades as compatible and contract breaks as `STALE_SCHEMA`.
- Legacy backfill is conservative: existing SourceClaim rows must carry current
  prompt/schema metadata and must not be older than the current SourceDocument
  snapshot metadata. Otherwise the executor/planner refuses to guess a HIT.
- Phase A planner now reads the real SourceClaim materialization ledger and
  reports Phase B metrics:

```text
required_passage_rows
unique_extraction_inputs
materialization_hit_count
zero_claim_hit_count
legacy_reuse_count
stale_count
missing_count
actual_source_claim_llm_calls
claims_created
claims_reused
source_claim_dedupe_ratio
source_claim_cache_hit_rate
```

- Added Phase B regression coverage for lookup-first reuse, unique passage
  materialization, zero-claim caching, duplicate passages across documents,
  same-content refresh reuse, changed-content invalidation, implementation
  upgrade compatibility, breaking-contract staleness, safe legacy backfill, and
  `doc_id_filter=[]` protection.
- Initialized the local SQLite table. Current ledger row count before any #19 /
  #40 Phase B materialization execution:

```text
source_claim_materializations=0
```

- Captured current local planner baseline after Phase B schema/executor wiring:

```text
#19 / Evidence Package #12 v8 / 40 Runs
SourceClaim: required_passage_rows=1875, unique_extraction_inputs=1462
SourceClaim: materialization_hit_count=0, legacy_reuse_count=69, missing_count=1393
SourceClaim: missing_unique_llm_inputs=1393, lookup_first_llm_required=1385
SourceClaim: source_claim_dedupe_ratio=0.220267, source_claim_cache_hit_rate=0.047196
EvidenceAlignment remains Phase C: naive_pairs=9666, after_recall=188, actual_llm_required=169

#40 / Evidence Package #15 v2 / 6 Runs
SourceClaim: required_passage_rows=630, unique_extraction_inputs=547
SourceClaim: materialization_hit_count=0, legacy_reuse_count=10, missing_count=537
SourceClaim: missing_unique_llm_inputs=537, lookup_first_llm_required=529
SourceClaim: source_claim_dedupe_ratio=0.131746, source_claim_cache_hit_rate=0.018282
EvidenceAlignment remains Phase C: naive_pairs=230, after_recall=65, actual_llm_required=15
```

Validation:

```text
.venv/bin/python -m pytest -q tests/test_incremental_materialization_planner.py tests/test_source_claim.py tests/test_evidence_alignment.py tests/test_workflow_review_queue.py
42 passed

.venv/bin/python -m compileall app
passed

git diff --check
passed
```

Boundary:

```text
No EvidenceAlignment cache or recall execution changes.
No full-chain concurrency changes.
No Product Truth / Benchmark / Gap / Strategy / Step 7 / Step 8 changes.
No historical SourceClaim deletion.
```

## 2026-09-02 V1.1 Incremental Materialization Phase A Planner

- Started the independent performance stage `V1.1 Incremental Materialization`.
- Added a read-only planner module:

```text
backend/app/modules/optimization/incremental_materialization.py
```

- Added a read-only API endpoint:

```text
GET /api/optimization/workflow/{project_id}/{prompt_id}/materialization-plan
```

- The planner reports current Prompt Run Scope, required SourceDocuments,
  passages, SourceClaim reuse, EvidenceAlignment candidate amplification,
  existing semantic/materialization hits, missing unique LLM inputs, LLM cache
  hits, missing pairs, and LLM amplification ratio.
- The planner does not call LLM, fetch source pages, write SourceClaim,
  regenerate EvidenceAlignment, change workflow status, or create Strategy /
  Action / Experiment rows.
- Added regression coverage for:

```text
planner remains read-only
current cited SourceDocuments do not expand into historical SourceClaims
duplicate Runs increase observations without increasing semantic AnswerUnit count
```

- Captured current local API baseline:

```text
#19 / Evidence Package #12 v8 / 40 Runs
AnswerUnit: raw_observations=2100, semantic_objects=35
SourceDocument: observed_citation_records=1207, unique_canonical_urls=158, required_documents=156
Passage: required=1875
SourceClaim: hit=80, missing=1795, missing_unique_llm_inputs=1396, lookup_first_llm_required=1385
EvidenceAlignment: semantic_reasons=27, source_claim_candidates=358, naive_pairs=9666, after_recall=188, actual_llm_required=169
Primary bottleneck: SOURCE_CLAIM

#40 / Evidence Package #15 v2 / 6 Runs
AnswerUnit: raw_observations=1296, semantic_objects=85
SourceDocument: observed_citation_records=174, unique_canonical_urls=26, required_documents=26
Passage: required=630
SourceClaim: hit=10, missing=620, missing_unique_llm_inputs=537, lookup_first_llm_required=529
EvidenceAlignment: semantic_reasons=5, source_claim_candidates=46, naive_pairs=230, after_recall=65, actual_llm_required=15
Primary bottleneck: SOURCE_CLAIM
```

Boundary:

```text
No Product Truth changes.
No Evidence verdict semantics changes.
No Benchmark / Gap / Strategy changes.
No Step 7/8 redesign.
No database migration in Phase A.
```

## 2026-09-02 Current-Lineage Materialization And Evidence Review Dedupe

- Fixed the #19/#40 recovery path where "重新运行当前主链" could behave like a
  full Evidence library recompute instead of current-context materialization.
  V1.1 SourceClaim extraction and EvidenceAlignment now scope formal input to
  SourceDocuments actually cited by the selected current `run_ids`.
- `doc_id_filter=[]` is now treated as an empty scope rather than "no filter" in
  passage retrieval, SourceClaim extraction, EvidenceAlignment, and document
  segmentation. This prevents a Prompt with missing current citation lineage
  from scanning every historical SourceDocument in the local database.
- SourceClaim extraction now deduplicates document-level semantic claims by:

```text
project + SourceDocument + passage + normalized/source span + claim type + polarity
```

  Re-running the current chain no longer creates new SourceClaim rows for the
  same grounded source sentence just because the run was re-materialized.
- EvidenceAlignment now deduplicates SourceClaims before matching. Run-level
  coverage remains on EvidenceAlignment observations; duplicate document facts
  must not multiply judge calls or review workload.
- EvidenceAlignment reruns carry forward human review for the same semantic
  relation:

```text
AI reason + SourceDocument + normalized SourceClaim text + relation
```

  The formal `review_status` remains compatible with existing consumers, while
  `human_payload_json.review_carry_forward` records provenance.
- Workflow status and review queue now count evidence review by semantic groups
  instead of raw Run-level rows. For #19 local data, 480 underlying SUPPORTS rows
  collapse into 4 review groups while preserving the 480 rows for lineage and
  coverage audit.
- Review queue responses now include a stable `review_group_key` for each
  semantic evidence group. The frontend uses this key for card identity and
  loading state instead of array index or a huge alignment-id string.
- After a group is confirmed, the frontend reloads the review queue from the
  backend as the source of truth. It no longer only filters local state, which
  could leave the second group in a stale loading/no-request state after the
  first group was removed.
- Batch evidence confirmation now updates a full semantic group in one database
  statement, avoiding long spinner behavior from per-row confirmation loops.
- Added regression tests for:

```text
empty doc filter does not expand to all documents
alignment consumes one SourceClaim per semantic fact
SourceClaim semantic key ignores row id
workflow evidence review group counts and batch confirmation
```

Validation:

```text
.venv/bin/python -m pytest -q tests/test_workflow_review_queue.py tests/test_source_claim.py tests/test_evidence_alignment.py tests/test_evidence_lineage_v1.py tests/test_source_gap_v1.py
88 passed

.venv/bin/python -m compileall app
passed
```

Boundary:

```text
No Strategy rule changes.
No Gap decision tree changes.
No Step 7/8 redesign.
No Step 9 changes.
No historical Evidence deletion or rebinding.
```

## 2026-09-01 Current Analysis Lock And Running State Fix

- Fixed a local SQLite blocking issue where clicking human confirmation while
  `run-analysis` was writing could fail with:

```text
sqlite3.OperationalError: database is locked
```

The UI then looked like it was still "generating" because the backend task had
left `PromptAnalysisRun(status=RUNNING)` as the latest state.

- `get_db()` now explicitly rolls back request sessions on exceptions before
  closing them.
- SQLite connections now use:

```text
busy_timeout = 30000
journal_mode = WAL
```

This keeps local development reads/writes more tolerant of short concurrent
workflow writes.

- `run-analysis` now creates `PromptAnalysisRun(status=RUNNING)` synchronously
  in the request before starting the background thread, and passes that id into
  the thread. The background thread updates the same row instead of creating a
  second run record.
- `PromptAnalysisRun.errors_json` now carries lightweight progress metadata
  while running, so the workflow card can show the current stage instead of a
  generic unchanged "generating" state.
- The analysis pipeline now commits between major stages:

```text
Answer Semantic
Source Qualification
Citation Content Acquisition
Document Segmentation
Answer Binding Shadow Input
Source Claim
Evidence Alignment
```

This releases SQLite write locks between long-running stages.

- Batch event/alignment confirmation now catches SQLite lock conflicts and
  returns a Chinese `409` response instead of surfacing as an opaque 500.
- Workflow status now surfaces `CURRENT_ANALYSIS_RUNNING` regardless of whether
  Step 7 was otherwise `NEEDS_CURRENT_ANALYSIS` or blocked by pending review.
  Stale `RUNNING` records older than 30 minutes are displayed as recoverable
  `CURRENT_ANALYSIS_FAILED` so an old crashed thread does not permanently block
  the Prompt.
- Workflow status now short-circuits latest `RUNNING` / `FAILED` analysis
  records before computing heavy Citation Decision read models. Status refresh
  must remain a lightweight read; explicit buttons trigger generation.
- Source metadata cache insertion is now idempotent for duplicate URLs; a
  concurrent/duplicate `source_metadata_cache.url` no longer rolls the overview
  request into a failed transaction.
- Follow-up: the single Prompt page now refreshes `workflow/status` together
  with Citation Decision refreshes and polls the workflow state while
  `CURRENT_ANALYSIS_RUNNING`. This prevents the UI from keeping an old local
  "主链运行中" card after the backend run has already completed and moved to the
  next gate, such as evidence review.
- Follow-up: evidence review grouping now groups by semantic review key:

```text
AI reason + SourceDocument + normalized source claim text + relation + role
```

It no longer uses `source_claim_id` as part of the grouping key. Repeated runs
or repeated SourceClaim extraction IDs for the same source sentence are shown as
one review card while preserving every underlying run-level EvidenceAlignment.
- Frontend review buttons now check HTTP failure responses before showing
  success or removing a card. A SQLite lock or backend error must keep the card
  visible and show a Chinese error instead of creating a fake "confirmed" UI
  state that reappears after refresh.

Boundary:

```text
No Strategy rule changes.
No Gap rule changes.
No Step 8 or Step 9 changes.
No historical data deletion.
```

## 2026-09-01 Step 7 Current Analysis State Fix

- Fixed a workflow state bug where a Prompt with upstream answer-decision or
  evidence signals but no generated V1.1 formal Evidence input could be shown
  as:

```text
NO_STRATEGY
NO_EXPERIMENT
```

This was misleading because "current V1.1 chain has not produced formal input"
is not the same as "current chain proved no strategy is needed".

- Added a current-chain input state check for:

```text
decision events
legacy SUPPORTS / RELATED evidence signals
formal V1.1 EvidenceAlignment input
completed V1.1 Shadow runs
```

- New workflow state:

```text
NEEDS_CURRENT_ANALYSIS
```

It is returned only when the current Prompt has upstream signals but lacks
V1.1 formal Evidence input. Step 7 and Step 8 remain unfinished in this state.

- `NO_STRATEGY` is now reserved for the terminal case where the current formal
  chain has run and still produced no Content/Evidence strategy candidate.

- The frontend now renders `NEEDS_CURRENT_ANALYSIS` as:

```text
第 7 步：需重跑主链
按钮：重新运行当前主链
```

The button calls:

```text
POST /api/optimization/workflow/{project_id}/{prompt_id}/run-analysis
{ "use_answer_binding_v1_1": true }
```

- The backend `run-analysis` pipeline now generates the V1.1 AnswerUnit /
  AnswerDecisionBinding shadow input before running formal SourceClaim /
  EvidenceAlignment when `use_answer_binding_v1_1=true`.
- When the frontend does not pass explicit `run_ids`, `run-analysis` now
  defaults to the active Evidence Package's frozen `source_run_ids` before
  falling back to all available Prompt runs. This keeps "current main chain"
  aligned to the current Evidence Package context.
- Follow-up fix: `run-analysis` now creates a persistent
  `PromptAnalysisRun(status=RUNNING)` record at task start and updates it to
  `COMPLETED` or `FAILED`. Workflow status maps these into:

```text
CURRENT_ANALYSIS_RUNNING
CURRENT_ANALYSIS_FAILED
```

This prevents the UI from looking unchanged after the user clicks "重新运行当前主链".
Failure details are surfaced from `PromptAnalysisRun.errors_json`.
- When a rerun creates new RecommendationEvents, Step 7 `NOT_READY` now points
  to the earliest unfinished prerequisite, for example:

```text
待推荐行为人工确认完成后生成策略候选
```

instead of the misleading generic text "待缺口诊断后生成策略候选".

Boundary:

```text
No Gap rule changes.
No Strategy rule changes.
No Step 8 or Step 9 changes.
Historical candidates/experiments still cannot light the current workflow.
```

## 2026-09-01 Step 7 Strategy Channel Resolver

- Audited current channel-decision logic. Formal Step 7 channel roles were
  previously distributed across:

```text
_strategy_planned_channels
_strategy_primary_intervention_path
_strategy_channel_roles
frontend display of planned_channels/channel_roles
Step 8 mechanism compatibility checks
```

- Introduced a single deterministic resolver:

```text
_resolve_strategy_channels(...)
```

It is now the only formal source for:

```text
primary_intervention_path
planned_channels
channel_roles
channel_rationales
```

- Resolver inputs are existing formal read-model signals only:

```text
capability_gap_items
priority_capabilities
citation_decision_values
channel_aggregation
product_truth
relevant_brand_assets
retrieval/citation state
benchmark evidence
```

- Deprecated distributed shortcuts are no longer consumed by formal Step 7:

```text
CONTENT/EVIDENCE -> first-party PRIMARY
Benchmark platform -> execution channel
Benchmark platform -> always OBSERVE
```

- Added deterministic policy behavior:

```text
CONTENT_GAP -> relevant first-party asset can be PRIMARY.
EVIDENCE_GAP + strong third-party Decision Citation -> third-party channel can be PRIMARY.
DISCOVERABILITY_GAP -> retrieval expansion path.
PRODUCT_GAP -> PRODUCT_IMPROVEMENT, no content-channel PRIMARY.
UNKNOWN -> no forced PRIMARY channel.
Benchmark-only without Decision Citation -> OBSERVE.
```

- The resolver explicitly does not decide Step 8 execution parameters:

```text
account
URL
page
title
section
asset instance
Draft
```

- Prompt `#40` read-only regression:

```text
Evidence Package #15
status = READY_FOR_HUMAN_CONFIRM
primary_intervention_path = FIRST_PARTY_BRAND_CAPABILITY_EXPRESSION:OFFICIAL_SITE
OFFICIAL_SITE = PRIMARY
ZHIHU = SECONDARY
ZHIHU basis = Decision Citation 6/6 Runs; supported reasons 点击统计 / 自定义分享标题 / 营销场景使用; primary benchmark 1
resolver = resolve_strategy_channels / DETERMINISTIC_POLICY_ENGINE
```

The #40 output did not change for change's sake. The important correction is
that both OFFICIAL_SITE and ZHIHU roles now come from the same resolver rather
than two distributed rule fragments.

Validation:

```text
.venv/bin/python -m pytest -q tests/test_strategy_step7_v1.py tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py tests/test_asset_brief_v1.py tests/test_workflow_review_queue.py
.venv/bin/python -m compileall app
source /Users/bmwqr/.nvm/nvm.sh && nvm use 18.20.8 && cd geo-platform/frontend && npm run build
git diff --check
```

Results:

```text
91 passed
compileall passed
frontend build passed
git diff --check passed
```

## 2026-09-01 Citation Decision Value Step 7 Strategy Input

- Added a Citation Decision Value interpretation layer on top of existing
  Phase 2A eligible `EvidenceAlignment`. This is a derived read model only; it
  does not add a database table, migration, new Evidence Judge, new Citation
  Score, new Benchmark formula, new Gap type, Draft, or Step 9 behavior.
- Formal grain is now:

```text
SourceDocument
+ supported_entity
+ capability/reason
```

The same SourceDocument can therefore expose multiple values rather than a
single document-wide label.
- Implemented derived classes:

```text
DECISION_CITATION
ANSWER_SUPPORT_CITATION
PERIPHERAL_CITATION
UNCLASSIFIED_SUPPORT
NOT_EVALUABLE
```

- Added source-row output:

```text
citation_decision_values
citation_value_class
citation_value_summary
citation_run_ids
retrieval_run_ids
```

- Added `channel_aggregation` to `citation_decision_vertical_slice`, summarizing
  platform-level retrieval/citation/decision-citation coverage, supported
  entities/reasons, and benchmark counts.
- Updated Step 7 Strategy Core generation so `planned_channels` and
  `channel_roles` consume Citation Decision Value + Channel Aggregation. The
  old simplified behavior:

```text
CONTENT_GAP -> OFFICIAL_SITE PRIMARY
Benchmark platform -> OBSERVE
```

is no longer sufficient. Benchmark Channel still cannot automatically become an
execution channel; a platform can become `SECONDARY` or `EXPERIMENTAL` only when
Decision Citation coverage explains why.
- Prompt `#40` read-only regression:

```text
Evidence Package #15
source_count = 68
recommended_actions = 1
ZHIHU retrieval = 6/6
ZHIHU citation = 6/6
ZHIHU decision citation = 6/6
ZHIHU primary_benchmark_count = 1
supported reasons = 点击统计 / 自定义分享标题 / 营销场景使用
planned_channels = OFFICIAL_SITE PRIMARY + ZHIHU SECONDARY
```

- Scope deliberately excluded Step 8 Draft, Step 9, Channel Intelligence,
  Product Truth changes, Gap rule changes, EvidenceAlignment eligibility
  changes, Benchmark scoring changes, and Decision Stability changes.

Validation:

```text
.venv/bin/python -m compileall app
.venv/bin/python -m pytest -q tests/test_strategy_step7_v1.py tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py tests/test_asset_brief_v1.py tests/test_workflow_review_queue.py
source /Users/bmwqr/.nvm/nvm.sh && nvm use 18.20.8 && cd geo-platform/frontend && npm run build
git diff --check
```

Results:

```text
compileall passed
84 passed
frontend build passed
git diff --check passed
```

## 2026-08-31 Step 7 V1.1 Current Candidate Eligibility Blocker Fix

- Fixed the current single Prompt Step 7 blocker where legacy, audit, test, or
  regression `OptimizationStrategyCandidate` rows could be selected as the
  current strategy candidate after Prompt `#40` was re-run.
- Added a centralized current Step 7 eligibility validator. A candidate is
  current-consumable only when it matches the active Prompt Evidence Package,
  package version, V1.1 answer-binding input mode, current generator family,
  `USER_FLOW` origin, and complete Strategy Core schema.
- `review_strategy_candidate` now writes the current workflow confirmation only
  for eligible current Step 7 candidates. Historical accepted candidates remain
  reviewable history but cannot mark the current main chain as confirmed.
- Step 8 backend entry points now reject ineligible candidates even if they are
  already `ACCEPTED` or `ACCEPTED_WITH_EDITS`; this prevents old candidates from
  creating current Action / Experiment rows.
- Added a dedicated current generation endpoint:

```text
POST /api/optimization/projects/{project_id}/prompts/{prompt_id}/strategy-candidates/generate-current-v1
```

- The frontend strategy page no longer calls the old `generate-v2` route for
  the current single Prompt Step 7 flow. It now generates through the current
  V1.1 endpoint and defaults the strategy list to
  `eligible_for_current_step7=true` rows only.
- Prompt `#40` read-only regression after the fix:

```text
evidence_package_id = 15
package_version = 2
strategy_step_status = READY_TO_GENERATE
current_strategy_candidate_ids = []
current_strategy_confirmed = false
execution_step_status = LOCKED
historical_strategy_candidate_count = 8
ineligible current candidates = #40-#47
```

- Scope deliberately excluded Evidence, Benchmark, Gap, Decision Stability,
  Strategy Core algorithm, Asset Brief, Claim Matrix, Draft, Experiment,
  Baseline, and Step 9 changes.

Validation:

```text
.venv/bin/python -m compileall app
.venv/bin/python -m pytest -q tests/test_workflow_review_queue.py tests/test_strategy_step7_v1.py
nvm use 18.20.8 && npm run build
```

## 2026-08-31 Step 7/8 Current-State Alignment Fix

- Fixed the single Prompt workbench state source for Step 7 / Step 8. The
  current main-chain state is now derived from the current Prompt, current
  active Evidence Package, and the bound current StrategyCandidate instead of
  historical accepted candidates, historical experiments, or legacy
  `WorkflowConfirmation(action)` rows.
- `review_strategy_candidate` now writes a context-bound confirmation record
  when a StrategyCandidate is accepted:

```text
strategy_candidate_id
evidence_package_id
prompt_id
review_status
effective_validation_status
```

- `workflow_status` now returns central current-state fields for frontend use:

```text
strategy_step_status
execution_step_status
current_strategy_candidate_id(s)
current_strategy_confirmed
current_effective_payload_valid
current_action_id
current_experiment_id
historical_strategy_candidate_ids/count
historical_experiment_ids/count
```

- Step 7 status is now locked to:

```text
NOT_READY
READY_TO_GENERATE
PENDING_REVIEW
CONFIRMED
```

Only `CONFIRMED` marks Step 7 complete. `READY_TO_GENERATE` and
`PENDING_REVIEW` are actionable current states, not completion states.
- Step 8 is complete only when the current confirmed StrategyCandidate points
  to the current Action / Experiment Draft. Historical experiments remain
  visible as history but cannot light the current main chain.
- Removed the old workbench shortcut that could directly mark
  `WorkflowConfirmation(action)` from a legacy continue result. Strategy
  confirmation must go through StrategyCandidate human review.
- Frontend single Prompt cards and the citation decision stepper now consume
  backend current-state fields and keep history separate. User-facing labels
  use `策略确认` and `实验方案落地`.
- Scope deliberately excluded Evidence, Benchmark, Gap, Strategy generation,
  Asset Brief, Draft, Step 9, Decision Stability, and scoring changes.

Validation:

```text
.venv/bin/python -m pytest -q tests/test_workflow_review_queue.py
7 passed
```

## 2026-08-31 Step 7 Strategy Confirmation UX Link Fix

- Fixed a Prompt `#40` UX regression where Step 7 appeared to only show two
  planned channels and did not clearly expose:

```text
StrategyCandidate
-> Human Strategy Confirmation
-> effective_payload
-> Step 8 Action / Experiment Draft
```

- Root cause: the strategy page displayed planned channels correctly, but the
  card did not lead with the StrategyCandidate confirmation state. The Step 8
  button was also a placeholder `message.info`, so confirmed strategies with an
  existing Experiment looked clickable but did not open the corresponding draft.
- Added a Chinese `策略确认链路` summary to each strategy card, including:

```text
机器候选 / 已人工确认 Strategy
effective_payload validation state
Action id
Experiment draft id
```

- Changed the Step 8 button behavior:
  - existing Action/Experiment -> open the matching experiment chain;
  - accepted Strategy without draft -> explain that execution-plan parameters
    are still required;
  - pending Strategy -> keep the explicit `确认策略` gate.
- When Step 7 generates a new StrategyCandidate from the single Prompt
  workbench, the strategy page now defaults to the newly generated candidate
  instead of letting historical accepted candidates steal the default view.
- This is a UI flow fix only. It does not change Strategy generation, Evidence,
  Benchmark, Gap, Product Truth, Action, Experiment, Baseline, Draft, or Step 9.
- Follow-up correction: `phase_*_regression` StrategyCandidates are now treated
  as historical acceptance artifacts, the same as `phase*_audit`. They no
  longer mark the current Prompt workflow Step 7/8 as complete. Planned channel
  rows now show `selection_basis` so users can see why a platform layer is
  suggested.

## 2026-08-31 Step 8 Asset Brief + Claim Matrix

- Added Step 8 Asset Brief + Claim Matrix as the second cut after Strategy Core
  protection. This checkpoint stays inside Step 8 and does not create Draft,
  Step 9, new scoring, new Gap semantics, or a parallel Strategy model.
- Reused existing storage instead of adding a new asset-brief table:

```text
OptimizationExperiment.brief_json
OptimizationExperiment.intervention_variables_json
OptimizationExperiment.controlled_intervention_json
OptimizationAction.release_evidence_json
OptimizationStrategyCandidate.experiment_plan_json / effective_payload
```

- Added `AssetBriefReviewPayload` and the backend review endpoint:

```text
POST /api/optimization/experiments/{experiment_id}/asset-brief/review
```

- Step 8 now builds an Asset Brief for the concrete Action / Asset /
  Execution Path. The brief freezes strategy snapshot/ref, selected asset
  ref/snapshot, required signals, claim matrix, Product Truth refs/snapshot,
  benchmark evidence refs, channel role, brief version, and review timestamp
  when confirmed.
- Claim Matrix is fact-boundary only. It lists required, optional, prohibited,
  and review-required claims; it does not generate article paragraphs, FAQ, or
  content draft.
- Product Truth discipline was enforced in backend logic:

```text
SUPPORTED     -> REQUIRED / OPTIONAL
UNKNOWN       -> REVIEW_REQUIRED / BLOCKED
NOT_SUPPORTED -> PROHIBITED
```

- Benchmark Evidence / SourceClaim can explain market standard and AI decision
  context, but can never become target-brand Product Truth.
- Added explicit draft gate: Asset Brief must be confirmed before later Draft
  preparation can start. This checkpoint still stops before Draft.
- Existing Step 8 draft objects are backfilled in place when missing Asset
  Brief data. The #40 official path reused `StrategyCandidate #44`,
  `Action #31`, and `Experiment #31`; no duplicate Action/Experiment was
  created.
- Prompt `#40` real regression:

```text
StrategyCandidate #44
Action #31
Experiment #31
created_new_draft = False
PRIMARY_BENCHMARK = 1 -> 1
recommended_action_count = 1 -> 1
Prompt #40 EvidenceAlignment = 660 -> 660
claim_matrix REQUIRED = 点击统计 / 自定义分享标题 / 营销场景使用
draft_gate = READY_FOR_DRAFT_PREPARATION
mechanism_compatibility = EXECUTION_COMPATIBLE
```

- A script selection pitfall was caught during audit: the first pass could pick
  a previously created channel-simulation candidate instead of the official
  Step 8 path. The audit runner now prefers the current experiment-bound
  `OFFICIAL_SITE` candidate for #40 acceptance evidence.

Validation:

```text
.venv/bin/python -m pytest -q tests/test_strategy_step7_v1.py tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py tests/test_asset_brief_v1.py
69 passed
```

## 2026-08-28 Step 7 Strategy Core / Step 8 Protection First Cut

- Updated Step 7 `StrategyCandidate` generation so the candidate carries a
  complete Strategy Core while still reusing existing
  `OptimizationStrategyCandidate.structured_payload/effective_payload`:

```text
target_decision_change
priority_capabilities
strategic_hypothesis
intervention_mechanism
primary_intervention_path
planned_channels
channel_roles
asset_direction
execution_sequence
required_signals
non_goals
attribution_intent
```

- Corrected the Step 7/8 boundary: Step 7 may define planned platform layer and
  channel role, such as `OFFICIAL_SITE` or `ZHIHU`, but it must not bind
  concrete account, URL, page, title, section, content structure, Draft,
  Baseline, Action, or Experiment.
- Added Step 8 Strategy Core Protection. If Step 8 payload attempts to change
  Strategy Core fields such as `intervention_mechanism`, the backend blocks the
  request and returns `RETURN_TO_STEP_7`.
- Added structured `execution_delta` rows with backend-calculated impact level:

```text
EXECUTION_ONLY
MECHANISM_REVIEW_REQUIRED
STRATEGY_CORE_CHANGE
```

- Added Mechanism Compatibility checks:

```text
EXECUTION_COMPATIBLE
REVIEW_REQUIRED
STRATEGY_RECONFIRM_REQUIRED
```

- Step 8 Experiment snapshots now freeze Strategy Core attribution intent,
  selected asset, action snapshot, baseline, execution delta, and mechanism
  compatibility. Existing StrategyCandidate and Experiment models were reused;
  no migration was required.
- Frontend strategy detail now renders Strategy Core, planned channels,
  channel roles, asset direction, execution sequence, and attribution intent in
  Chinese labels. The old warning `第 7 步不选择平台或文章类型` was replaced with
  the more precise planned-channel vs concrete-execution boundary.
- Prompt `#40` real regression:

```text
StrategyCandidate #44 = ACCEPTED_WITH_EDITS / VALIDATED
Action #31
Experiment #31
planned primary channel = OFFICIAL_SITE
Benchmark source channel = ZHIHU / OBSERVE only
BAIJIAHAO simulation = REVIEW_REQUIRED
intervention_mechanism mutation = RETURN_TO_STEP_7
```

- This checkpoint does not implement Asset Brief, Claim Matrix, Draft, Step 9,
  Decision Stability changes, Citation/Benchmark formula changes, or new Gap
  semantics.

Validation:

```text
.venv/bin/python -m pytest -q tests/test_strategy_step7_v1.py tests/test_source_gap_v1.py
54 passed
.venv/bin/python -m compileall -q app
frontend npm run build
git diff --check
```

## 2026-08-28 Step 7 Strategy Page Structured Payload Render Guard

- Fixed a white-screen crash after Step 7 `生成策略候选` succeeded.
- Root cause: the generated `StrategyCandidate` payload can contain structured
  objects such as `evidence_summary`. The strategy page rendered that value
  directly as a React child, which crashes when the value is an object.
- Added display-only normalization for strategy page text fields. Structured
  evidence summaries are now shown as concise Chinese summaries:

```text
对标来源
涉及能力
缺口
优先级
```

- This does not change StrategyCandidate payloads, effective_payload,
  Evidence lineage, Benchmark, Gap, Action, Experiment, Baseline, Decision
  Stability, or Step 9.

Validation:

```text
frontend npm run build
git diff --check
```

## 2026-08-28 Step 7 Strategy Confirm V1.1 Context Parity

- Fixed a Prompt `#40` blocker where clicking Step 7 `生成策略候选` looked like
  it had no effect.
- Root cause: the frontend read Citation Decision V1 with
  `use_answer_binding_v1_1=true`, so the page correctly showed a current
  strategy candidate could be generated. The confirm POST did not pass the same
  flag, so the backend recomputed the proposal with the default formal input
  setting and returned:

```text
没有可生成策略候选的 Content/Evidence Gap。Product/Unresolved 需要先人工补充 Product Truth 或资产信息。
```

- The Step 7 confirm payload now includes the exact V1.1 usage flag returned by
  the current Citation Decision result, falling back to the current frontend
  constant only when the API response omits it.
- No StrategyCandidate model, effective_payload validation, Evidence lineage,
  Benchmark, Gap, Action, Experiment, Baseline, Decision Stability, or Step 9
  behavior was changed.

Validation:

```text
frontend npm run build
.venv/bin/python -m compileall -q app/modules/optimization/workflow.py app/modules/optimization/api.py app/modules/optimization/service.py
git diff --check
```

## 2026-08-28 Step 7/8 Audit History Isolation

- Fixed a Prompt `#40` retest UX issue where Phase audit artifacts from final
  acceptance could make Step 7 and Step 8 look complete before the operator
  saw or confirmed a current StrategyCandidate.
- Root cause: Prompt `#40` already had audit-generated records on the current
  Evidence Package:

```text
StrategyCandidate #41 / #40 = ACCEPTED_WITH_EDITS / VALIDATED
reviewed_by = phase4_audit / phase3_audit
Experiment #30 / #29 = draft
```

- The frontend now treats audit-generated `StrategyCandidate` rows as history
  for the single Prompt main workflow. They remain visible under
  `全部策略（含历史验收）`, but they no longer mark Step 7 as confirmed, mark
  Step 8 as created, appear as the default current strategy, or allow accidental
  accept/experiment generation from the historical card.
- Current workflow Step 7 remains operable: when evidence and Gap are ready and
  there is no non-audit current StrategyCandidate, the next action is
  `生成策略候选`.
- No backend data, Evidence lineage, Benchmark formula, Gap decision tree,
  Product Truth, StrategyCandidate validation, Action/Experiment creation,
  Baseline, Decision Stability, or Step 9 behavior was changed.

Validation:

```text
frontend npm run build
.venv/bin/python -m compileall -q app/modules/optimization/workflow.py app/modules/optimization/api.py
git diff --check
```

## 2026-08-28 Step 7 Strategy Gate Unblock

- Fixed a single Prompt workflow blocker where Step 7 could remain
  `策略确认 / 等待缺口` even though the current Citation Decision V1 result had
  already completed Gap Diagnosis and the current Evidence Package had
  confirmed `StrategyCandidate` rows.
- Root cause: the frontend Step 7 gate still depended on legacy
  `WorkflowConfirmation` keys (`gap` / `action`). The frozen V1 main chain must
  use the current Citation Decision Gap result plus current
  Evidence-Package-scoped `OptimizationStrategyCandidate` review state.
- Updated the Step 7 current-chain guard:

```text
answer decision done
-> evidence review done
-> current Citation Gap decision done
-> current Evidence Package StrategyCandidate state
```

- Updated user-facing wording so completed evidence review no longer tells
  operators to click legacy `继续分析` to generate "缺口与动作". The next step is
  now displayed as generating or reviewing `策略候选`.
- Strategy detail entry buttons now route through the current Evidence Package
  selector before opening the strategy page, reducing empty strategy-context
  jumps.
- No data model, Evidence lineage, Benchmark formula, Gap decision tree,
  StrategyCandidate/effective_payload validation, Action, Experiment, Baseline,
  Decision Stability, or Step 9 behavior was changed.

Validation:

```text
.venv/bin/python -m compileall -q app/modules/optimization/workflow.py app/modules/optimization/api.py
frontend npm run build
git diff --check
```

## 2026-08-28 Evidence Review Group Batch Confirm

- Added semantic grouping for workflow EvidenceAlignment review items. The
  review queue now merges duplicated Run-level SUPPORTS alignments into one
  user-facing review group when they share:

```text
semantic reason text
source_document_id
source_claim_id
relation
evidence_role
```

- The grouped review item keeps all underlying `alignment_ids`, true
  `run_ids`, `run_count`, and `alignment_count`; no Run-level
  EvidenceAlignment is merged, deleted, or rewritten.
- Follow-up correction: V1.1 `recommendation_reason_id` can contain per-Run
  technical IDs such as `answer_unit:{id}:binding:{id}` and must not be used as
  the grouping key. The queue now uses `semantic_reason_key` when available and
  falls back to the legacy readable reason text.
- The batch confirm route is registered before the single-alignment dynamic
  route so `/confirm-batch` cannot be parsed as an `alignment_id`.
- Added a minimal batch confirmation endpoint:

```text
POST /api/optimization/workflow/review/alignments/confirm-batch
```

- The frontend manual review workspace now shows one card per grouped evidence
  item and provides one action: `确认这一组支持`.
- No data migration was required. The change only updates review queue payloads
  and review status confirmation behavior.
- No Evidence, Benchmark, Gap, Strategy, Action, Experiment, Baseline,
  Decision Stability, or Step 9 logic was changed.

Validation:

```text
.venv/bin/python -m pytest -q tests/test_workflow_review_queue.py
4 passed

.venv/bin/python -m compileall -q app/modules/optimization/workflow.py app/modules/optimization/api.py
frontend npm run build
```

## 2026-08-28 Step 7 Current-Workflow State Integrity Bugfix

- Fixed a single Prompt workflow regression where Step 7 could display
  `策略确认 / 已确认` because the current Evidence Package already had a
  historical confirmed `StrategyCandidate`, even when the current workflow
  status still required evidence review or gap diagnosis.
- The frontend now gates current Step 7 state by the current workflow chain:

```text
answer_semantic done
-> evidence_review done
-> gap done
-> current StrategyCandidate state
```

- Existing StrategyCandidates and Experiments remain visible as historical
  objects, but they no longer mark the current main-chain Step 7 or Step 8 as
  complete unless the current workflow state has reached that step.
- Strategy page navigation now reloads the current Evidence Package before
  routing to the strategy confirmation page, preventing a "confirmed strategy"
  button from opening an empty strategy context.
- No data model, Evidence, Benchmark, Gap, StrategyCandidate validation,
  Action, Experiment, Baseline, Release Gate, Decision Stability, or Step 9
  behavior was changed.

Validation:

```text
frontend npm run build
backend compileall for workflow module
git diff --check
```

## 2026-08-27 Step 7 Strategy Confirmation UI Bugfix

- Fixed the single Prompt workflow Step 7 user-facing semantics after V1
  freeze. The product meaning is `StrategyCandidate + 人工策略确认`, not
  "推荐动作确认".
- Updated frontend Step 7 state derivation so it reads current
  Evidence-Package-scoped `StrategyCandidate` state:
  - confirmed StrategyCandidate -> `策略确认 / 已确认`
  - pending StrategyCandidate -> `策略确认 / 待审核`
  - no candidate but eligible Content/Evidence Gap -> `可生成策略候选`
- After generating StrategyCandidates from Citation Decision V1, the frontend
  now reloads the current evidence package's strategy list and routes the user
  to the strategy confirmation area.
- Updated legacy visible labels in the citation decision detail page from
  "推荐动作" to "策略候选 / 策略确认" where the action is actually Step 7
  strategy generation/review.
- Updated backend workflow label for the historical `step_key="action"` to
  display as `策略确认`. The key remains unchanged for compatibility.
- No data model, Citation/Benchmark/GAP formula, StrategyCandidate gate, Action,
  Experiment, Baseline, or Step 9 behavior was changed.

Validation:

```text
frontend npm run build
backend compileall for workflow module
git diff --check
```

## 2026-08-27 Documentation Governance

- Added repository-level documentation governance for product iteration,
  development iteration, known pitfalls, and `产品纲要.md` maintenance:

```text
docs/12_DOCUMENTATION_GOVERNANCE.md
```

- Updated `geo-platform/AGENTS.md` so future work must update documentation when
  product semantics, workflow state sources, or previously encountered pitfalls
  are touched.
- Updated root `产品纲要.md` from the older broad flow to the current frozen
  single Prompt GEO V1 Step 1-8 chain.
- No business code, data model, API, frontend workflow, scoring formula,
  Strategy, Action, Experiment, or Step 9 behavior was changed.

Validation:

```text
git diff --check
```

## 2026-08-27 Single Prompt GEO V1 Final Acceptance

- Completed final acceptance for the single Prompt GEO V1 Step 1-8 main chain
  using Prompt `#40` as the Golden Case.
- Added the final acceptance audit artifact:

```text
docs/SINGLE_PROMPT_GEO_V1_FINAL_ACCEPTANCE.md
```

- Added the read-only audit helper:

```text
backend/scripts/audit_prompt40_final_acceptance.py
```

- Prompt `#40` final accepted state:

```text
valid_run_ids = [238, 239, 240, 253, 254, 255]
evidence_package_id = 15
PRIMARY_BENCHMARK = 1
CONTENT_GAP = 3 capability-level items
StrategyCandidate #41 = ACCEPTED_WITH_EDITS / VALIDATED
Action #30 = PLANNED
Experiment #30 = draft / WAITING_FOR_RELEASE_AUDIT
Decision Stability = CO_DOMINANT / 100 / HIGH_STABILITY
```

- Applied one acceptance bugfix without changing the stability score formula or
  any Step 1-8 gate: Decision Stability reason coverage now uses the current
  formal-input `AnswerDecisionBinding` batch when V1.1 formal EvidenceAlignment
  payloads identify one. Historical Shadow bindings remain preserved but no
  longer pollute current reason coverage.
- No new product phase, model, Gap type, Strategy type, scoring formula, Step 9,
  validation run, monitoring loop, Prompt Cluster, Channel Intelligence, or
  automatic content generation/publishing was added.
- Validation:

```text
.venv/bin/python -m compileall -q app scripts/audit_prompt40_final_acceptance.py scripts/audit_prompt40_phase5_decision_stability.py
.venv/bin/python -m pytest -q tests/test_answer_evidence_shadow.py tests/test_evidence_lineage_v1.py tests/test_source_gap_v1.py
68 passed

frontend npm run build
passed

git diff --check
passed
```

- Phase status:

```text
SINGLE_PROMPT_GEO_V1_FROZEN
STEP_9_NOT_STARTED
```

## 2026-08-27 Citation Decision V1.1 Phase 5 Decision Stability

- Added Phase 5 Decision Stability as a read-only post-hoc metric for single
  Prompt multi-Run recommendation variance.
- No database migration was required. The metric is derived from existing:
  - fixed Evidence Package `source_run_ids`
  - valid `BrowserMonitorRun`
  - `RecommendationEvent`
  - `AnswerDecisionBinding`
  - `AnswerUnit`
- Added service/API support:

```text
GET /optimization/projects/{project_id}/prompts/{prompt_id}/decision-stability
```

- The `citation-decision-v1` response now includes `decision_stability` for
  the current Prompt/package context.
- Locked the calculation formula in code and docs:

```text
score = round(dominant_recommendation_outcome.run_count / valid_run_count * 100)
```

- Added fixed stability levels:

```text
HIGH_STABILITY: score >= 80
MIXED: 50 <= score < 80
HIGH_VOLATILITY: score < 50
NO_VALID_RUNS: valid_run_count = 0
```

- Decision Stability remains isolated from all formal gates:

```text
Evidence / Benchmark / Gap / Strategy / Action / Experiment / Baseline
```

- Added frontend display on the single Prompt main chain and citation decision
  detail page. The UI labels it as `只读观察` and explains that it does not
  change main-chain outcomes.
- Added Prompt `#40` Phase 5 audit output:

```text
docs/PROMPT_40_PHASE5_DECISION_STABILITY_AUDIT.md
```

- Added Phase 5 checkpoint:

```text
docs/CITATION_DECISION_V1_1_PHASE5_DECISION_STABILITY_CHECKPOINT.md
```

- Prompt `#40` result:

```text
valid_run_count = 6
brand_decision_run_count = 6
dominant_recommendation_outcome = CO_DOMINANT_RECOMMENDATION_ENTITIES
co_dominant_entities = Bitly / 小码短链接 / 缩我短链接 / 轻松短链接
unique_dominant_entity = none
decision_stability_score = 100
stability_level = HIGH_STABILITY
formal_output_impact = NONE
```

- Added dominant tie semantics: when multiple recommendation entities share the
  highest run coverage, Decision Stability returns `CO_DOMINANT` instead of
  selecting one entity by deterministic name ordering. This does not change the
  stability formula or any single Prompt V1 1-8 main-chain result.

- Also added/kept Phase 4 regression coverage for Strategy gate, Step 8
  execution-plan gate, strategy snapshot immutability, baseline freeze, required
  selected asset/channel, and benchmark-channel isolation.
- Validation:

```text
.venv/bin/python -m compileall -q app scripts/audit_prompt40_phase5_decision_stability.py
.venv/bin/python -m pytest -q tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py
48 passed
```

- Phase status:

```text
PHASE_5_DECISION_STABILITY_CHECKPOINT_READY
STEP_9_NOT_STARTED
```

## 2026-08-27 Citation Decision V1.1 Phase 4 Execution Plan

- Completed the Phase 4 Preflight Audit inside the same product phase; no
  additional product phase was introduced.
- Reused existing objects instead of adding a parallel asset or strategy system:
  - `PageSnapshot` as the stable existing asset reference.
  - `OptimizationStrategyCandidate.effective_payload_json` as the Strategy
    confirmation payload.
  - `OptimizationAction` and `OptimizationExperiment` for Step 8 draft
    materialization.
  - `OptimizationExperiment.intervention_variables_json`,
    `baseline_run_ids_json`, and `baseline_metrics_json` for frozen snapshots
    and baseline state.
- Added the Step 8 service/API:

```text
POST /optimization/strategy-candidates/{candidate_id}/execution-plan
```

- Added `StrategyExecutionPlanPayload` with separated execution semantics:

```text
channel = OFFICIAL_SITE / PRODUCT_DOCS / ZHIHU / BAIJIAHAO / THIRD_PARTY_MEDIA / OTHER
asset_operation = UPDATE_EXISTING / CREATE_NEW
selected_asset = PAGE_SNAPSHOT:<id> or NEW_ASSET proposal
baseline_run_ids = explicit fixed Run IDs
```

- Locked the Step 7 -> Step 8 gate in backend code and tests:
  - `ACCEPTED_WITH_EDITS + PENDING_HUMAN_CHANNEL_REVIEW` can enter Step 8.
  - `PENDING_REVIEW` cannot enter Step 8.
- Added `baseline_metrics_for_fixed_runs`; it requires explicit Run IDs and
  separates brand-level from selected-asset-level retrieval/citation metrics.
- Experiment draft creation now freezes the confirmed Step 8
  `effective_payload` snapshot, selected asset reference, gap refs, action
  snapshot, baseline Run IDs, and baseline metrics.
- Added Prompt `#40` Phase 4 audit output:

```text
docs/PROMPT_40_PHASE4_EXECUTION_PLAN_AUDIT.md
```

- Added Phase 4 checkpoint:

```text
docs/CITATION_DECISION_V1_1_PHASE4_EXECUTION_PLAN_CHECKPOINT.md
```

- Prompt `#40` real regression created a draft experiment:

```text
strategy_candidate_id = 41
action_id = 30
experiment_id = 30
experiment_status = draft
release_blocked_reason = WAITING_FOR_RELEASE_AUDIT
baseline_run_ids = [238, 239, 240, 253, 254, 255]
```

- Validation:

```text
.venv/bin/python -m compileall -q app scripts/audit_prompt40_phase4_execution_plan.py
.venv/bin/python -m pytest -q tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py
39 passed
git diff --check passed
```

- Phase status:

```text
PHASE_4_EXECUTION_PLAN_CHECKPOINT_READY
STEP_9_NOT_STARTED
```

## 2026-08-27 Single Prompt GEO V1 Phase 0/1 Handoff

- Added the review-only handoff document:
  `docs/SINGLE_PROMPT_GEO_V1_PHASE0_1_HANDOFF.md`.
- This is a docs-only Phase 0/1 checkpoint. No business code, model migration,
  API behavior, frontend workflow, StrategyCandidate, Action, or Experiment was
  changed in this step.
- Locked the single Prompt GEO V1 chain for review:

```text
1. 采集样本
2. 答案决策识别
3. 目标品牌事实
4. 引用证据
5. 对标来源
6. 缺口诊断
7. 策略候选 + 策略确认
8. 实验方案落地
```

- Recorded four hard constraints for Phase 2:
  - Reuse `OptimizationStrategyCandidate` and `effective_payload` as the
    strategy confirmation boundary.
  - `OptimizationExperiment` must freeze the confirmed `effective_payload`
    snapshot at creation time.
  - `DISCOVERABILITY_GAP` must be based on brand assets relevant to the current
    Prompt/capability, not arbitrary project assets.
  - Formal `EvidenceAlignment` consumers must verify full Run lineage, not just
    non-empty `run_id`.
- Recorded current conflict points before implementation:
  - `confirm_citation_decision_vertical_slice` can still directly materialize
    experiment plans.
  - Current experiment payload storage does not explicitly freeze an
    `effective_payload` snapshot.
  - `_latest_brand_asset_snapshot` can fall back to the latest project asset,
    which is unsafe for discoverability judgment.
  - Several legacy modules still query raw `EvidenceAlignment.relation =
    SUPPORTS` without a unified lineage/feature-flag read gate.
- Current phase status:

```text
PHASE_0_1_HANDOFF_READY_FOR_REVIEW
PHASE_2_BUSINESS_CODE_NOT_STARTED
```

## 2026-08-27 Citation Decision V1.1 Main Workflow Read

- 单 Prompt 主链路前端请求 `citation-decision-v1` 时显式传入
  `use_answer_binding_v1_1=true`，避免后端默认 OFF 时页面仍展示旧 V1
  `0 Benchmark / 0 Action`，导致操作者误以为第 4 步后无法推进。
- 该改动不调整 8 步主链路顺序，不新增模块，不改变后端默认 feature flag；
  后端仍可用 `use_answer_binding_v1_1=false` 验证正式结果回滚。
- Prompt `#40` 当前应进入“1 个核心对标，但推荐动作被 Product Truth
  闸门阻断”的状态，待人工补齐 `点击统计`、`自定义分享标题`、
  `营销场景使用` 等目标品牌事实后再继续生成动作。
- 单 Prompt 首页第 7/8 步只导航到执行策略详情，不直接调用确认接口；
  最终确认动作和创建实验草案必须在详情页查看依据后操作。

## 2026-08-26 Prompt 40 Phase 1 Formal Result Audit

- Audited the first small-scope formal Citation Decision V1.1 input switch on
  Prompt `#40`.
- Added the review artifact:
  `docs/PROMPT_40_PHASE1_FORMAL_RESULT_AUDIT.md`.
- Confirmed that Prompt `#40` moved from the previous false-negative shape to:

```text
status = READY_FOR_HUMAN_CONFIRM
primary_benchmark_count = 1
recommended_action_count = 1
channel_opportunity_count = 1
```

- Confirmed the formal `SUPPORTS` rows came from:

```text
reason_source = ANSWER_DECISION_BINDING
formal_input_version = citation_decision_v1_1_formal_input.v1
```

- Confirmed the result did not come from:

```text
RecommendationEvent.reasons_json
Shadow Evidence Result
Citation Prominence
title/entity string match
LEGACY_RELATED
```

- Found a Phase 2 blocker: the six formal `SUPPORTS` rows are all attached to
  Run `#238`, not spread across all six source Runs. The current formal
  alignment logic deduplicates answer-derived reasons by semantic text, scope,
  and entity, which collapses run-level coverage.
- Found a rollback-boundary blocker: `use_answer_binding_v1_1` currently
  controls generation input only. Once V1.1 formal `EvidenceAlignment` rows are
  written, the Citation Decision read path still consumes them even if the
  generation flag is later false.
- Found a Product Truth granularity risk: the current action focuses on
  `数据统计功能 / 自定义分享标题 / 营销场景`, while matched Product Truth is still
  the broader `短链生成` capability.
- Found a small toolchain drift: `run_single_case_evidence.py` passes
  `doc_id_filter` into Layer 3, but `run_reason_driven_retrieval` does not
  currently accept that parameter.
- Current phase status:

```text
PHASE_1_FORMAL_INPUT_PROVEN_ON_PROMPT_40
READY_FOR_FULL_PRODUCTION_SWITCH = false
```

- No main workflow order change was made in this audit.

## 2026-08-26 Prompt 40 Shadow Binding Scope Calibration

- Calibrated the V1.1 Phase 0 Shadow Binding semantics from strict explicit
  reason detection to Recommendation Explanation Scope detection.
- Added Shadow audit fields on `AnswerDecisionBinding`:
  - `scope_type`
  - `scope_reason`
- Updated Binding rules so recommended-brand capability, benefit, price,
  result, use-case, and comparative-advantage AnswerUnits inside the
  recommendation explanation scope default to `SUPPORTING_REASON`.
- Kept `DIRECT_REASON` reserved for explicit selection conditions, explicit
  causality, explicit comparison, or demand-fit language.
- Preserved exclusions for procedure steps, general background facts, other
  brands, limitations/counter facts, and content outside the recommendation
  explanation scope.
- Extended the Shadow-only evidence path so valuable unbound AnswerUnits can be
  audited as `BRAND_CAPABILITY_EVIDENCE`, `PROCEDURAL_EVIDENCE`, or
  `FACTUAL_EVIDENCE` without creating Recommendation Evidence.
- Added a SQLite compatibility migration for the Shadow-only
  `answer_evidence_shadow_results` table so `recommendation_event_id` and
  `decision_binding_id` can be null for unbound AnswerUnit evidence.
- Re-ran Prompt `#40` six-Run Shadow audit as `ShadowRun #7`.

Prompt `#40` ShadowRun `#7` result:

```text
answer_unit_count = 216
grounded_answer_unit_count = 216
binding_count = 30
direct_reason_count = 0
supporting_reason_count = 30
shadow_result_count = 252
shadow_source_claim_count = 222
SUPPORTS = 18
NO_SUPPORT = 234
CONTRADICTS = 0
recommendation_evidence_eligible_count = 18
```

Formal V1 zero-pollution check:

```text
formal SourceClaim: 545 -> 545
formal EvidenceAlignment for Prompt #40: 0 -> 0
PRIMARY_BENCHMARK: 0 -> 0
SECONDARY_BENCHMARK: 0 -> 0
recommended_action_count: 0 -> 0
channel_opportunity_count: 0 -> 0
formal_output_impact = NONE
```

Review artifact:

```text
docs/PROMPT_40_SHADOW_RUN_7_BINDING_REVIEW.md
```

Validation performed:

- Existing local SQLite Shadow result table was migrated without dropping
  `ShadowRun #7`; `answer_evidence_shadow_results` kept 787 rows.
- `.venv/bin/python -m pytest tests/test_answer_evidence_shadow.py` passed:
  11 tests.

## 2026-08-26 Prompt 40 Shadow Audit Run

- Executed the real V1.1 Phase 0 Shadow Evidence Chain for Prompt `#40`
  across the six evidence-package Runs:
  `238, 239, 240, 253, 254, 255`.
- Added audit controls for focused Shadow runs:
  - `entity_filter`
  - `max_bindings`
- The controls only limit Shadow audit scope. They do not change the formal
  Citation Decision V1 chain or any formal Benchmark / Gap / Action output.
- Fixed Shadow summary formal-count scope so formal SourceClaim counts are
  project-scoped and formal EvidenceAlignment counts are project + prompt
  scoped.
- Added a regression test proving `entity_filter=小码短链接` does not bind other
  recommended entities in the same run.

Prompt `#40` ShadowRun `#6` result:

```text
answer_unit_count = 216
binding_count = 30
shadow_result_count = 252
shadow_source_claim_count = 222
SUPPORTS = 18
NO_SUPPORT = 234
CONTRADICTS = 0
recommendation_evidence_eligible_count = 18
```

Formal V1 zero-pollution check:

```text
formal SourceClaim: 545 -> 545
formal EvidenceAlignment for Prompt #40: 0 -> 0
PRIMARY_BENCHMARK: 0 -> 0
SECONDARY_BENCHMARK: 0 -> 0
recommended_action_count: 0 -> 0
channel_opportunity_count: 0 -> 0
```

Validation performed:

- `.venv/bin/python -m pytest tests/test_answer_evidence_shadow.py` passed:
  6 tests.

## 2026-08-26 Prompt 40 Binding Review Gate

- Added a reusable Markdown export script for Shadow Binding review:
  `backend/scripts/export_answer_binding_review.py`.
- Exported `ShadowRun #6` into
  `docs/PROMPT_40_SHADOW_RUN_6_BINDING_REVIEW.md`.
- The review table keeps all 30 machine Binding rows as `待人工审计`; it does
  not pretend machine output is human-approved.
- Added Shadow-only `PROCEDURAL_CONTEXT` so procedure AnswerUnits can be audited
  as procedural source evidence without becoming recommendation reasons.
- Procedure evidence is classified as `PROCEDURAL_EVIDENCE` and does not count
  toward `recommendation_evidence_eligible_count`.

Gate observations:

```text
小码短链接支持长链接快速缩短: Binding 6/6, SUPPORTS 0/6
小码短链接自带点击统计: Binding 6/6, SUPPORTS 6/6
小码短链接自带二维码生成: Binding 6/6, SUPPORTS 0/6
小码短链接自带自定义分享标题: Binding 6/6, SUPPORTS 6/6
小码短链接适合营销场景使用: Binding 6/6, SUPPORTS 0/6
```

Validation performed:

- `.venv/bin/python -m pytest tests/test_answer_evidence_shadow.py` passed:
  7 tests.

## 2026-08-26 Citation Decision V1.1 Phase 0 Shadow Chain

- Added an audit-only V1.1 Shadow Evidence Chain for recommendation reason
  bridging:
  `AnswerClaim -> AnswerUnit -> AnswerDecisionBinding -> Shadow Passage
  Retrieval -> Shadow SourceClaimJudge -> Shadow EvidenceAlignmentJudge ->
  Shadow Evidence Classification`.
- Added isolated Shadow data models:
  - `AnswerUnit`
  - `AnswerDecisionBinding`
  - `AnswerEvidenceShadowRun`
  - `AnswerEvidenceShadowResult`
- Added backend endpoints:
  - `POST /api/optimization/projects/{project_id}/prompts/{prompt_id}/answer-evidence-shadow/run`
  - `GET /api/optimization/projects/{project_id}/prompts/{prompt_id}/answer-evidence-shadow/latest`
- Preserved the formal production chain. Phase 0 writes no formal
  `SourceClaim` / `EvidenceAlignment` rows and does not change formal
  Benchmark, Source Gap, Priority, Action Route, StrategyCandidate, or
  Experiment output.
- Added rule-based answer-unit atomicization so answer claims such as
  `小码短链接：支持长链接快速缩短，自带点击统计、二维码生成、自定义分享标题...`
  become entity-specific ability units instead of a copied full title.
- Added a guarded binding fallback for empty `RecommendationEvent.reasons_json`:
  same-run answer units can become Shadow `DIRECT_REASON` /
  `SUPPORTING_REASON`, while procedure-only units are not treated as
  recommendation reasons.

Validation performed:

- `.venv/bin/python -m compileall app` passed.
- `.venv/bin/python -m pytest tests/test_answer_evidence_shadow.py` passed:
  5 tests.
- The new tests verify:
  - answer-claim ability extraction for the Prompt `#40` pattern;
  - Shadow SUPPORTS can be recorded through the isolated chain;
  - formal `source_claims` and `evidence_alignments` counts remain unchanged;
  - procedure-style answer units do not bind as recommendation reasons.
  - neutral feature mentions do not bind without a recommendation event;
  - implicit use-case reasons can bind as Shadow supporting reasons.

## 2026-08-26 Prompt 40 Citation Reason Alignment Audit

- Added a handoff audit section to
  `docs/CITATION_OPTIMIZATION_DECISION_V1_AUDIT.md` for Prompt `#40`.
- Documented the current false-negative shape:
  - Decision Market recognizes `小码短链接` as a confirmed competitor
    recommendation across `6/6` Runs;
  - the matching Zhihu source is fetched and marked `CONTENT_VALID`;
  - Golden Case answer claims contain the concrete capability text;
  - but `RecommendationEvent.reasons_json = []`, so reason-driven passage
    retrieval does not create SourceClaims or EvidenceAlignments for that
    source.
- Clarified that `0 Primary / 0 Secondary Benchmark` is mechanically correct
  under the current V1 gates, but product-wise incomplete because answer-claim
  capability text is not bridged back into Recommendation Reasons.
- Recorded the safe fix direction:
  derive missing entity-specific recommendation reasons from same-run
  `AnswerClaim` / `answer_span`, mark them as answer-derived, then rerun the
  existing blind SourceClaim and EvidenceAlignment path.
- Preserved current hard boundaries:
  Citation Prominence, title/entity matching, and legacy `RELATED` must not
  directly upgrade a source into Benchmark support.
- Refined the implementation boundary for V1.1 Phase 0:
  Shadow Run must cover the full isolated evidence path
  `AnswerUnit -> AnswerDecisionBinding -> Shadow Passage Retrieval -> Shadow
  SourceClaimJudge -> Shadow EvidenceAlignmentJudge -> Shadow Audit`, not only
  answer binding.
- Recorded the data-impact boundary:
  Phase 0 must not change any formal Benchmark, Source Gap, Priority, Action
  Route, StrategyCandidate, or Experiment output. Shadow SourceClaims and
  Shadow EvidenceAlignments must be version-isolated, for example with
  `pipeline_version = citation_decision_v1_1_shadow` or an equivalent shadow
  run marker.

Validation performed:

- Read-only local API smoke for Prompt `#40`.
- Read-only local database spot-check for SourceDocument `#345`.
- Documentation-only change; no code path changed.

## 2026-08-25 Single Prompt Citation State Sync

- Fixed a single Prompt `GEO 工作台` state-sync gap where Prompt `#40` could
  already have an Evidence Package and Citation Decision V1 result, while the
  frontend step 4 still displayed `待生成证据包`.
- The `validation` page now loads Evidence Packages just like the execution
  detail page, so the main workflow can see current Prompt package state.
- Citation Decision V1 auto-loading now reacts to the refreshed workflow object,
  not only to `prompt_id` changes. This prevents stale "no package" state from
  surviving after operators generate or supplement evidence for the same Prompt.
- Preserved the existing product chain order:
  `采集样本 -> 答案决策识别 -> 目标品牌事实 -> 引用证据 -> 对标来源 -> 缺口诊断 -> 推荐动作 -> 实验草案`.

Validation performed:

- Prompt `#40` has active Evidence Packages `#15` and `#14`.
- Prompt `#40` Citation Decision V1 resolves to Package `#15` and returns
  `source_count = 68`, `primary_benchmark_count = 0`,
  `secondary_benchmark_count = 0`, and `recommended_action_count = 0`.
- Frontend `npm run build` passed with the existing Vite chunk-size warning.
- `git diff --check` passed.

## 2026-08-25 Browser-first Citation Refetch

- Upgraded Golden Case citation document refetch from "Playwright if the default
  browser exists, otherwise urllib" to a browser-first acquisition path.
- Source refetch now searches for the same local Chrome / Chromium executables
  used by browser collection instead of depending only on Playwright's default
  headless-shell path.
- Added a persistent visible-browser fallback for evidence refetch when
  headless launch fails on macOS. This matches the collection-side behavior more
  closely and avoids silently falling back to Python DNS / SSL behavior.
- Browser refetch now uses:
  - real Chrome user agent;
  - `ignore_https_errors = true`;
  - `domcontentloaded` as the primary wait condition;
  - best-effort `networkidle`;
  - HTML-to-text fallback when visible body text is too short.
- Failure reasons now preserve both browser failure and HTTP fallback failure
  when both paths fail.
- Live validation against `https://m.suolink.cn/` changed from Python DNS
  failure to browser success:
  - `fetch_status = SUCCESS`;
  - title captured;
  - clean text length = 1328.

Validation performed:

- `.venv/bin/python -m compileall app` passed.
- `.venv/bin/python -m pytest tests/test_source_qualification.py` passed.
- Live browser refetch smoke for `https://m.suolink.cn/` passed.
- `git diff --check` passed.

## 2026-08-25 Single Prompt Citation Evidence Entry

- Corrected the single Prompt `GEO 工作台` step 4 entry:
  `引用证据` now routes operators to `证据标注`, where they can acquire
  citation page bodies, manually supplement missing body text, and inspect
  evidence alignment.
- Kept `引用资料` as a ranking / source-structure inspection page only. It is
  no longer the primary operation target for the main workflow citation
  evidence step.
- Preserved the integrated main chain order:
  `采集样本 -> 答案决策识别 -> 目标品牌事实 -> 引用证据 -> 对标来源 -> 缺口诊断 -> 推荐动作 -> 实验草案`.
- Localized the step-4 operator copy so the card describes the actual work:
  `查看/补录正文`, not generic source ranking.

Validation performed:

- Frontend `npm run build` passed with the existing Vite chunk-size warning.
- `git diff --check` passed.

## 2026-08-25 Workflow State Integrity Guard

- Added a strict context identity to Citation Optimization Decision V1 responses:
  `project_id`, `prompt_id`, `evidence_package_id`,
  `analysis_version`, and `source_run_ids`.
- Hardened the single Prompt frontend workflow so Citation Decision data is only
  consumed when it belongs to the current Prompt; stale responses are discarded
  and Prompt switches clear Prompt-scoped proposal, benchmark, channel, action,
  experiment, and Citation Decision state before reloading.
- Corrected the answer-decision gate:
  `event_review = done` only means there are no pending human review items; it
  does not mean the Prompt has valid answer decision semantics. The workflow now
  requires `answer_semantic.done = true` before Product Truth, Citation
  Evidence, Benchmark, Gap, Action, or Experiment can advance.
- Reordered the single Prompt `GEO 工作台` into the product chain:
  `采集样本 -> 答案决策识别 -> 目标品牌事实 -> 引用证据 -> 对标来源 -> 缺口诊断 -> 推荐动作 -> 实验草案`.
- Separated current Citation V1 analysis from historical execution records:
  legacy `continueResult` may be shown as history, but it no longer marks
  current Citation Evidence, Benchmark, Gap, Action, or Experiment steps as
  completed.
- Preserved zero-result semantics:
  no Evidence Package stays `待生成证据包`; zero Primary/Secondary Benchmark is a
  valid completed benchmark judgment; `UNKNOWN` gaps require human judgment and
  do not become confirmable actions.

Validation performed:

- `.venv/bin/python -m compileall app` passed.
- `.venv/bin/python -m pytest tests/test_workflow_review_queue.py` passed.
- `.venv/bin/python -m pytest tests/test_source_gap_v1.py tests/test_citation_prominence_v1.py tests/test_gap_action.py`
  passed: 31 tests.
- Frontend `npm run build` passed with the existing Vite chunk-size warning.
- `git diff --check` passed.
- Live API smoke:
  - Prompt `#40` workflow status still belongs to Prompt `#40`;
  - Prompt `#40` Citation Decision fails closed with
    `当前 Prompt 尚无 Evidence Package，不能生成纵向闭环 Proposal`;
  - Prompt `#19` Citation Decision returns `context_identity` bound to Prompt
    `#19` and Evidence Package `#12`.

## 2026-08-05

- Added `AGENTS.md` guidance and numbered project docs.
- Added P0 optimization-loop models:
  - `OptimizationIssue`
  - `OptimizationIssueRun`
  - `OptimizationAction`
  - `OptimizationExperiment`
- Added `/api/optimization` router for issue/action/experiment/evidence flow.
- Added frontend “优化闭环” page with candidate issue generation, issue
  confirmation, action creation/release, experiment baseline/validation, and
  conclusion controls.
- Added citation source analysis inside the evidence chain, covering cited
  sources and retrieved-but-not-cited candidates across ownership, content
  format, prompt match, freshness, authority, citation reason, and risk flags.
- Added experiment retest queue creation so fixed validation tasks can be
  generated directly from the optimization loop.
- Fixed analytics validation dashboard fall-through bug.
- Added `backend/scripts/optimization_loop_smoke.py`.
- Promoted `target_page_conversion_rate` to a first-class experiment metric:
  target URL retrieved Runs, cited Runs, conversion rate, `delta_pp`, per-Prompt
  drilldown, per-environment drilldown, and raw Run drilldown.
- Upgraded `content_feature_changes` to structured objects with legacy string
  read compatibility.
- Unified experiment conclusion writes to `EFFECTIVE`,
  `PARTIALLY_EFFECTIVE`, `MIXED_RESULT`, `NO_MEASURABLE_EFFECT`,
  `NEGATIVE_EFFECT`, and `INSUFFICIENT_EVIDENCE`.
- Added release boundary handling:
  `PLANNED -> READY_FOR_MANUAL_RELEASE -> RELEASE_CONFIRMED`; only confirmed
  release writes `released_at` and starts cooling.
- Audited real DB candidates. No "视频二维码制作" Prompt exists. Project 3 /
  Cluster 5 is the best real candidate, but strict URL-level retrieval
  candidates are missing for brand pages, blocking a valid primary-metric
  baseline.
- Reclassified Prompt 19 into a retrieval-entry experiment instead of a
  retrieval-to-citation experiment. Added `target_page_retrieval_rate` as a
  first-class metric and locked Experiment `#13`:
  `0 / 12 = 0%` for `https://www.aifabu.com/card`.
- Captured the pre-release target page snapshot under
  `backend/artifacts/optimization/prompt19-target-page-retrieval/` and recorded
  structured planned page variables on Action `#13`.

Validation performed:

- Frontend TypeScript check passed.
- Backend `compileall` passed.
- Optimization loop smoke passed.

## 2026-08-06

- Cleaned explicit local smoke data from the real SQLite database:
  - Deleted 13 projects with IDs `4-16`, matching
    `P0 Optimization Smoke ... / SmokeBrand`.
  - Deleted associated smoke Runs, references, retrieval candidates, issues,
    actions, experiments, tasks, batches, prompts, clusters, topics, and
    legacy observations.
  - Deleted 3 orphan `run_artifacts` rows pointing at missing Run IDs.
  - Kept Project `1` "演示项目" because it was not an explicit smoke marker.
  - `PRAGMA foreign_key_check` passed after cleanup.
- Added B1 Evidence Package support:
  - New `OptimizationEvidencePackage` model/table.
  - New API endpoints for listing, creating, and reading packages.
  - Package payload includes deterministic metrics, platform gap matrix,
    content type distribution, candidate-not-cited summary, time distribution,
    content-structure signals, representative sources, Run drilldown, and
    `SOURCE_LEVEL_ONLY` evidence level.
  - Repeated generation with identical inputs returns the existing package by
    hash instead of creating duplicate versions.
- Reframed the former Prompt daily report frontend entry as
  `采集记录 / 证据事实报告`.
  - Legacy daily report generation remains available as collection history.
  - The new main card generates and displays Evidence Packages.
  - Prompt labels now include the actual prompt text, e.g.
    `Prompt #19 · 抖音跳转链接`.
- Generated the first real B1 report:
  - Package `#1`.
  - Project `3` "爱短链品牌监测".
  - Prompt `19` "抖音跳转链接".
  - Target URL `https://www.aifabu.com/card`.
  - Baseline Run IDs `135-146`.
  - `target_page_retrieval_rate = 0 / 12 = 0%`.
  - `target_page_conversion_rate = not_applicable`.

Validation performed:

- Backend `compileall` passed.
- Frontend `npm run build` passed.
- SQLite `init_db()` synced the new table.
- Evidence Package repeated-generation idempotency passed:
  second generation returned Package `#1` with the same hash.
- API smoke passed:
  `/api/health`,
  `/api/optimization/projects/3/evidence-packages?prompt_id=19`, and
  `/api/optimization/evidence-packages/1`.

## 2026-08-06 B1 Gate Completion

- Added formal Alembic migration skeleton:
  - `backend/alembic.ini`
  - `backend/alembic/env.py`
  - `backend/alembic/versions/20260806_01_b1_gate_release_audit.py`
- Added release-preparation database objects:
  - `PageSnapshot`
  - `OptimizationHypothesis`
  - `ReleaseAuditRecord`
- Added API/service support for:
  - capturing/listing page snapshots;
  - creating/listing accepted human Hypotheses;
  - release confirmation through an explicit audit record.
- Hardened release boundary:
  - `release_action(... release_confirmed=True)` no longer writes
    `released_at` directly;
  - release confirmation requires accepted Hypothesis, PRE/POST successful
    snapshots, canonical/robots checks, release note, and confirmer.
- Upgraded Evidence Package generation to `b1.v2 / metric.v2` with versioned
  hash inputs:
  - source Run IDs;
  - target page URLs;
  - environment snapshot;
  - schema, metric, collector, retrieval parser, content classifier, and time
    extractor versions.
- Generated latest Prompt 19 B1 report:
  - Package `#3`;
  - `target_page_retrieval_rate = 0/12 = 0%`;
  - `target_page_conversion_rate = not_applicable`;
  - unified drilldown rows for metrics, platforms, content types, freshness
    buckets, and candidate-not-cited.
- Preserved Package `#1`; it remains active and is associated with the accepted
  Prompt 19 Hypothesis.
- Captured target-page PRE_RELEASE snapshot:
  - Snapshot `#3`;
  - URL `https://www.aifabu.com/card`;
  - HTTP `200`;
  - canonical `https://www.aifabu.com/card`;
  - title `抖音卡片_微信卡片_直播间卡片-爱短链`;
  - H1 `抖音获客私域 点击跳转加好友`.
- Created accepted human Hypothesis:
  - Hypothesis `#1`;
  - Evidence Package `#1`;
  - Experiment `#13`;
  - baseline value `0/12`.
- Isolated `scripts/optimization_loop_smoke.py`:
  - default DB `geo_platform_smoke_test.db`;
  - supports `GEO_DATABASE_URL`;
  - refuses main DB;
  - cleans the test DB file in `finally`.

Validation performed:

- `.venv/bin/python -m compileall app` passed.
- `.venv/bin/python -m pytest tests/test_b1_gate.py` passed.

## 2026-08-06 Prompt 19 Retrieval Candidate Coverage Correction

- Investigated Prompt 19 Runs `135-146` after detecting that final references
  outnumbered retrieval candidates.
- Confirmed database counts:
  - `RetrievalCandidate`: 240 rows, exactly 20 per Run;
  - `ReferenceSource`: 360 rows, exactly 30 per Run;
  - unique captured candidate URLs: 23;
  - unique final reference URLs: 30.
- Confirmed historical artifacts cannot recover the missing candidate
  denominator:
  - each `searchresult-1.json` contains `data.results = 20`;
  - `network.jsonl` shows `csaitab/searchresult?pn=0&rn=20`;
  - therefore old Runs preserve only top-20 candidate responses while final
    references were captured as 30.
- Removed local collector hard caps:
  - DOM extraction no longer uses `slice(0, 20)`;
  - DOM/API merge no longer truncates to `[:20]`.
- Added `retrieval_coverage_summary` to Evidence Package payloads and bumped:
  - `schema_version = b1.v3`;
  - `retrieval_parser_version = retrieval_parser.v3_no_top20_cap`.
- Generated corrected Prompt 19 B1 report:
  - Package `#4`;
  - `target_page_retrieval_rate = 0/12 = 0%`;
  - `target_page_conversion_rate = not_applicable`;
  - `retrieval_coverage_status = INCOMPLETE`;
  - `incomplete_run_count = 12/12`;
  - `common_candidate_count_per_run = 20`;
  - `suspected_fixed_collection_limit = true`.
- Added frontend warning and Run-level coverage table in Evidence Package
  expanded view.
- Added regression test:
  - `test_retrieval_coverage_marks_candidate_denominator_incomplete`.

Validation performed:

- `.venv/bin/python -m compileall app` passed.
- `.venv/bin/python -m pytest tests/test_b1_gate.py` passed: 9 tests.
- `npx tsc -p tsconfig.json --noEmit` passed.
- `npm run build` passed with the existing Vite chunk-size warning.
- `.venv/bin/python scripts/optimization_loop_smoke.py` passed on the isolated
  smoke database.
- Frontend `tsc -p tsconfig.json --noEmit` passed.

## 2026-08-06 B1 Metric Eligibility Downgrade And B2/B3 Entry

- Reclassified Prompt 19 historical Runs `135-146`:
  - `answer_metrics_eligible = true`;
  - `citation_metrics_eligible = true`;
  - `retrieval_metrics_eligible = false`;
  - reason `INSUFFICIENT_RETRIEVAL_CANDIDATES`;
  - configured minimum candidate count is `30`.
- Generated Prompt 19 Package `#6`:
  - `schema_version = b1.v4`;
  - `metric_spec_version = metric.v3`;
  - `answer_eligible_run_count = 12`;
  - `citation_eligible_run_count = 12`;
  - `retrieval_eligible_run_count = 0`;
  - `captured_candidate_total = 240`;
  - `citation_total = 360`;
  - `target_page_retrieval_rate = null`;
  - `target_page_conversion_rate = null`;
  - `candidate_scope = captured_candidates`.
- Added B2 strategy candidate storage/API and B3 human review API:
  - strategy candidates save provider/model/prompt version, raw request,
    structured payload, validator status, and human review status;
  - review states are `PENDING_REVIEW`, `ACCEPTED`,
    `ACCEPTED_WITH_EDITS`, `REJECTED`, and `DEFERRED`;
  - accepted candidates can request experiment-plan conversion, but readiness
    stays blocked when retrieval baseline is missing.
- Generated Strategy Candidate `#2` from Package `#6`:
  - provider `local_rule`;
  - model `local-rule-v1`;
  - review status `PENDING_REVIEW`;
  - target metric `official_reference_rate`.
- Recollected Prompt 19 retrieval baseline after the collector fix:
  - probe Task `#41`, Runs `170-172`, all success, each Run captured 34
    candidates and 30 references;
  - full baseline Tasks `#42` and `#43`, Runs `173-184`, all success;
  - full baseline candidate count per Run: 30-32;
  - full baseline reference count per Run: 31;
  - generated Package `#7`;
  - `retrieval_eligible_run_count = 12`;
  - `target_page_retrieval_rate = 0/12 = 0%`;
  - `target_page_conversion_rate = not_applicable`;
  - locked Experiment `#13` baseline to Runs `173-184`;
  - cleared `release_blocked` because the recollected retrieval baseline is now
    eligible.
- Generated Strategy Candidate `#4` from Package `#7` and Experiment `#13`:
  - provider `local_rule`;
  - model `local-rule-v1`;
  - review status `PENDING_REVIEW`;
  - target metric `target_page_retrieval_rate`.
- Updated frontend Evidence Package view:
  - displays answer/citation/retrieval eligibility;
  - labels incomplete candidates as `已捕获候选`;
  - disables candidate-not-cited and candidate-to-citation displays when
    retrieval candidates are insufficient;
  - adds B2/B3 strategy generation and human review controls without any
    automatic publish action.

Validation performed:

- `.venv/bin/python -m compileall app` passed.
- `.venv/bin/python -m pytest` passed: 13 tests.
- `.venv/bin/python scripts/reference_parser_smoke.py` passed.
- `.venv/bin/python scripts/optimization_loop_smoke.py` passed.
- `npm run build` passed with the existing Vite chunk-size warning.
- `curl -s http://127.0.0.1:8000/api/health` returned `{"status":"ok"}`.

## 2026-08-24 Citation Optimization Decision V1 Step 0/1

- Added `docs/CITATION_OPTIMIZATION_DECISION_V1_AUDIT.md` as the pre-implementation
  entity/API reuse map.
- Locked the V1 constraints before code changes:
  - `SourceClaimJudge` remains blind; answer reasons can guide passage retrieval
    but cannot define source truth;
  - legacy `RELATED` must not be upgraded to `PARTIAL_SUPPORT` without re-judge;
  - legacy `source_score` remains compatibility-only and must not drive new
    benchmark, priority, strategy, or experiment decisions.
- Added `citation_prominence_level` to source analysis output.
- Source analysis sorting now uses citation prominence, citation coverage,
  citation frequency, and reference position before legacy score.
- Kept `source_score` as a deprecated compatibility field and exposed
  `legacy_source_score` plus `source_score_deprecated`.
- Updated the Citation Ranking V0 frontend copy to label raw scores as legacy
  diagnostic scores, not strategy decision signals.
- Added V1 content status mapping on existing `SourceDocument` data:
  - `CONTENT_VALID`;
  - `CONTENT_PENDING`;
  - `CONTENT_UNAVAILABLE`;
  - `CONTENT_INVALID`.
- Golden Case document API now returns content status labels/reasons.
- Manual document capture now rejects blank non-empty-page submissions; empty
  pages must be explicitly marked as `MANUAL_EMPTY`.
- Added compatibility mapping for evidence alignment relations:
  legacy `RELATED` maps to `LEGACY_RELATED`, not `PARTIAL_SUPPORT`.
- Ran Step 0-3 live acceptance on Project `#3` / Prompt `#43`:
  - source analysis returned 83 rows sorted by citation prominence;
  - sampled prominence breakdowns only included citation behavior fields;
  - Prompt `#43` had both `CONTENT_VALID` and `CONTENT_UNAVAILABLE` source
    documents, and analysis remained available for valid documents;
  - EvidenceAlignment rows for Prompt `#43` all mapped `RELATED` to
    `LEGACY_RELATED`, with no `PARTIAL_SUPPORT` upgrade.
- Representative source payload now includes `citation_prominence_level` and
  keeps legacy score fields explicitly marked as deprecated.
- Updated product and loop specs so `source_score` is no longer documented as
  the V1 source analysis sort or decision signal.

Validation performed:

- `.venv/bin/python -m pytest tests/test_citation_prominence_v1.py tests/test_gap_action.py`
  passed: 4 tests.
- `.venv/bin/python -m pytest tests/test_source_qualification.py tests/test_golden_case_api.py tests/test_citation_prominence_v1.py`
  passed: 19 tests.
- `.venv/bin/python -m pytest tests/test_evidence_alignment.py` passed: 7 tests.
- Live smoke for blank manual document capture rejected empty non-empty-page
  payloads with HTTP 400.
- Live smoke for manual empty page produced `MANUAL_EMPTY`,
  `CONTENT_UNAVAILABLE`, zero blocks, zero SourceClaims, and zero Alignments;
  temporary smoke data was removed.

## 2026-08-24 Citation Optimization Decision V1 Step 4A

- Froze Step 0-3 as the Foundation Semantic Layer.
- Added Step 4A derived fields to source analysis without creating new tables:
  - `decision_support_level`;
  - `has_contradiction`;
  - `benchmark_tier`;
  - supporting / contradicting alignment ids and basis fields.
- Decision Support aggregation only reads V1 `EvidenceAlignment` rows with
  `SUPPORTS` / `CONTRADICTS`; historical `RELATED` stays excluded and cannot
  become support semantics.
- Benchmark Tier rules are deterministic:
  - invalid or unavailable content -> `NOT_EVALUABLE`;
  - direct support for recommendation/candidate decision -> `PRIMARY_BENCHMARK`;
  - fact-only or partial decision support -> `SECONDARY_BENCHMARK`;
  - valid but unsupported/tangential sources -> `REFERENCE_ONLY`.
- `citation_prominence_level` is now only a same-tier sort signal and cannot
  upgrade a source to Benchmark.
- Step 4B remains explicitly not started: no Source Gap, Priority, Action Route,
  StrategyCandidate, or Experiment behavior was added.
- Prompt `#43` live smoke after Step 4A:
  - 6 runs, 204 references, 284 retrieval candidates, 83 source rows;
  - existing alignments were `RELATED x 1440`;
  - output was `REFERENCE_ONLY x 2`, `NOT_EVALUABLE x 81`;
  - all rows had `decision_support_level = NONE`;
  - `PRIMARY_BENCHMARK = 0`, which is accepted as the correct result.

Validation performed:

- `.venv/bin/python -m pytest tests/test_citation_prominence_v1.py` passed:
  8 tests.
- `.venv/bin/python -m pytest tests/test_citation_prominence_v1.py tests/test_source_qualification.py tests/test_evidence_alignment.py tests/test_golden_case_api.py tests/test_recommendation_intelligence.py tests/test_gap_action.py`
  passed: 63 tests.

## 2026-08-25 Citation Optimization Decision V1 Step 4B-1

- Froze Step 4A as the Benchmark Decision Layer.
- Added Source Gap as source-analysis derived fields only:
  - `source_gap_type`;
  - `source_gap_precondition`;
  - `matched_product_truth_status`;
  - `existing_asset_status`;
  - `existing_asset_coverage`.
- Source Gap inputs are strictly limited to:
  - Primary/Secondary Benchmark Evidence;
  - `TargetBrandCapabilityTruth`;
  - existing brand asset content from successful `PageSnapshot` rows.
- Source Gap outputs are limited to:
  - `CONTENT_GAP`;
  - `EVIDENCE_GAP`;
  - `PRODUCT_GAP`;
  - `NO_GAP`;
  - `UNKNOWN`.
- Kept Step 4B-3 out of scope: no Recommended Action, Channel Opportunity,
  StrategyCandidate, or Experiment behavior was added.
- Prompt `#43` live smoke after Step 4B-1:
  - 83 source rows;
  - `PRIMARY_BENCHMARK = 0`;
  - eligible benchmark count = 0;
  - all rows returned `source_gap_type = null`;
  - all rows returned `source_gap_precondition = NO_ELIGIBLE_BENCHMARK`.
- Corrected the source gap semantics so "not eligible for Gap Analysis" is not
  represented as `UNKNOWN`. `UNKNOWN` is now reserved for eligible benchmark
  rows whose Product Truth, Brand Asset, or Benchmark Evidence is insufficient.
- Added deterministic Step 4B-2 `priority_level` and `action_route` fields:
  - Primary + actionable gap -> `PRIORITY_HIGH`;
  - Secondary + actionable gap -> `PRIORITY_MEDIUM`;
  - `NO_GAP` -> `NOT_PRIORITY + NO_ACTION`;
  - eligible Benchmark + `UNKNOWN` -> `UNRESOLVED + UNRESOLVED`;
  - `REFERENCE_ONLY` -> `NOT_PRIORITY + null`;
  - `NOT_EVALUABLE` -> `null + null`.
- Prompt `#43` live smoke after Step 4B-2:
  - `priority_level = NOT_PRIORITY x 2, null x 81`;
  - `action_route = null x 83`;
  - no `PRIORITY_HIGH` / `PRIORITY_MEDIUM`;
  - no CONTENT / EVIDENCE / PRODUCT route.

Validation performed:

- `.venv/bin/python -m pytest tests/test_source_gap_v1.py` passed: 15 tests.

## 2026-08-25 Citation Optimization Decision V1 Vertical Slice

- Switched from step-by-step field discussion to the V1 vertical slice:
  `Source Analysis -> Recommended Action -> Channel Opportunity -> Human
  Confirmation -> StrategyCandidate -> InterventionPlan -> Experiment Draft ->
  Fixed Retest / Recommendation Outcome`.
- Added proposal-only row fields:
  - `recommended_action`;
  - `channel_opportunity`.
- Added read/confirm service and API endpoints:
  - `GET /api/optimization/projects/{project_id}/prompts/{prompt_id}/citation-decision-v1`;
  - `POST /api/optimization/projects/{project_id}/prompts/{prompt_id}/citation-decision-v1/confirm`.
- Confirmation records a workflow confirmation, creates/updates an
  `InterventionPlan`, creates validated `StrategyCandidate` rows, and reuses
  the existing `strategy_to_experiment_plan()` materialization path.
- Kept hard strategy boundaries:
  - `REFERENCE_ONLY`, `NOT_EVALUABLE`, `LEGACY_RELATED`, and Citation
    Prominence alone do not generate actions;
  - `PRODUCT_GAP` remains a product finding and does not create external
    content experiments;
  - release/retest/conclusion gates remain unchanged.
- Added Recommendation Outcome to experiment analysis:
  candidate, recommendation, target reason, and citation before/after.
- Real DB read-only smoke:
  - Prompt `#43` has no Evidence Package and fails closed.
  - Prompt `#9` / Package `#13`: 0 Primary Benchmark, 0 actions.
  - Prompt `#19` / Package `#12`: 2 Primary Benchmarks, 0 actions because
    downstream Product Truth / Brand Asset / Source Gap gates still block.
  - Prompt `#16` / Package `#11`: 0 Primary Benchmark, 0 actions.

Validation performed:

- `.venv/bin/python -m pytest tests/test_source_gap_v1.py` passed: 17 tests.
- `.venv/bin/python -m pytest tests/test_source_gap_v1.py tests/test_citation_prominence_v1.py tests/test_source_qualification.py tests/test_evidence_alignment.py tests/test_golden_case_api.py tests/test_recommendation_intelligence.py tests/test_gap_action.py`
  passed: 80 tests.

## 2026-08-25 Single Prompt Main Workflow Integration Correction

- Corrected a frontend regression where Citation Decision V1 was rendered as a
  separate module-like panel inside the single Prompt monitoring page.
- Removed that standalone monitoring-page panel and folded its state into the
  single `GEO 工作台` workflow row:
  `采集样本 -> 决策诊断 -> 引用证据 -> 对标来源 -> 目标品牌事实 -> 推荐动作 -> 实验草案`.
- Kept detailed source analysis, product-fact supplementation, and action
  confirmation in the execution-strategy detail page, instead of creating a
  competing homepage module.
- Localized the affected user-facing labels and workflow actions so operators
  see Chinese wording rather than internal enum terms.
- Clarified the main-page action button behavior: when no confirmable
  recommendation action exists, the button is disabled and the user is routed to
  the detail page to supplement target-brand facts or inspect strategy details.

Validation performed:

- Frontend `npm run build` passed.
- `git diff --check` passed.

## 2026-08-25 Prompt 40 Review Queue Dead-Loop Fix

- Fixed a workflow review dead loop reproduced on Prompt `#40`:
  - `/workflow/3/40/status` reported `pending_review_steps = 1`;
  - `/workflow/3/40/review-queue` returned no `unique_events` and no
    `alignments`;
  - the frontend therefore kept showing "开始审核" while the review modal only
    showed "全部审核完成".
- Root cause:
  - workflow status counted all `RecommendationEvent` rows in the review
    denominator;
  - review queue only returned pending machine-reviewable events;
  - Prompt `#40` had 24 `RecommendationEvent` rows with
    `review_status = VALIDATION_FAILED`, which should not enter human review.
- Corrected the backend review denominator:
  - only `MACHINE_GROUNDED`, `MACHINE_CANDIDATE`, `HUMAN_CONFIRMED`, and
    `HUMAN_REJECTED` events are counted as reviewable;
  - `VALIDATION_FAILED` events remain analysis diagnostics and no longer block
    the workflow.
- Added a frontend guard so an empty ready review queue refreshes the main
  workflow status and closes the review modal instead of trapping the operator
  in an empty audit loop.
- Localized the workflow status step labels/details touched by this path:
  `证据分析`, `证据人工确认`, `缺口诊断`, `动作候选`, and experiment-entry copy.

Validation performed:

- `.venv/bin/python -m pytest tests/test_workflow_review_queue.py` passed.
- `.venv/bin/python -m compileall app` passed.
- Live API smoke for Prompt `#40` returned `pending_review_steps = 0` and
  `all_reviews_done = true`; `/continue` no longer blocked on review.

## 2026-08-25 Unresolved Decision Evidence Review Context

- Added explicit human-verification context when workflow continuation returns
  `UNRESOLVED` Gap / Action.
- `/workflow/{project_id}/{prompt_id}/continue` now returns `review_context`
  with:
  - sampled raw answer excerpts by Run / Sample;
  - machine event diagnostics, including validation-failed recommendation
    events;
  - event review-status counts;
  - an instruction telling operators to fix missed recommendation events in
    diagnosis before overriding the decision.
- Updated the single Prompt workflow UI so the manual decision area lists the
  answer samples and machine event diagnostics before showing "按此方向继续" or
  "标记搁置并结束".
- Kept the action override path human-only; the added context is audit evidence,
  not an automatic strategy decision.

Validation performed:

- `.venv/bin/python -m pytest tests/test_workflow_review_queue.py tests/test_gap_action.py`
  passed.
- `.venv/bin/python -m compileall app` passed.
- Frontend `npm run build` passed.
- `git diff --check` passed.

## 2026-08-25 Workflow Conclusion Evidence Drawer

- Refined the single Prompt workflow interaction for `UNRESOLVED` Gap / Action:
  evidence is now attached to each conclusion through a Chinese "查看依据"
  button instead of being rendered as a large inline debug block.
- Added a right-side evidence drawer that shows:
  - the current Gap and Action conclusions;
  - raw answer samples for manual verification;
  - machine-recognized recommendation events and their Chinese review-status
    labels.
- Kept the manual decision controls in the main workflow, but made the required
  verification path explicit: operators can inspect answers first, then decide
  whether to override, shelve, or return to diagnosis to correct missed events.
- Preserved the product boundary that Citation Decision V1 belongs inside the
  single Prompt main workflow, not as a standalone homepage module.
- Localized the affected Gap / Action / confidence tags so users see labels
  such as "待确认" and "低置信" instead of raw enum values.

Validation performed:

- Frontend `npm run build` passed with the existing Vite chunk-size warning.

## 2026-08-25 Competitor-First Review Evidence Clarification

- Clarified the single Prompt evidence wording:
  - "目标品牌出现" means the project brand itself appeared in the answer;
  - competitor and other answer entities are shown separately as answer object
    clues.
- Extended `/workflow/{project_id}/{prompt_id}/continue` review context so each
  answer sample can carry detected entities classified as:
  - target brand;
  - confirmed competitor;
  - unconfirmed object.
- Fixed the human review modal load behavior:
  - competitor candidates are now treated as pending review items;
  - the modal no longer auto-closes as "no pending review" when the event and
    alignment queues are empty but competitor candidates still need review.
- Updated the review instruction order to tell operators to confirm competitor /
  candidate objects before reviewing AI statements and evidence relations.

Validation performed:

- `.venv/bin/python -m pytest tests/test_workflow_review_queue.py` passed.
- `.venv/bin/python -m compileall app` passed.
- Frontend `npm run build` passed with the existing Vite chunk-size warning.

## 2026-08-25 Single Prompt Workflow Card UX

- Reworked the single Prompt `GEO 工作台` workflow from a compact status-label
  row into actionable workflow cards.
- Each step now shows:
  - Chinese step status;
  - business detail for the current Prompt;
  - the next available operation, such as viewing runs, starting review,
    continuing analysis, running citation evidence, supplementing product
    truth, viewing evidence, or confirming actions.
- Corrected the citation step semantics:
  - not-yet-run citation evidence now appears as "待运行" / "运行引用证据";
  - a failed run is shown as a retryable current step instead of mixing
    "异常" with "等待运行".
- Kept Citation Decision V1 inside the single Prompt workflow and preserved
  detail pages only for deeper inspection.

Validation performed:

- Frontend `npm run build` passed with the existing Vite chunk-size warning.
- `git diff --check` passed.

## 2026-08-25 Decision Recognition Repair Entry

- Fixed the Prompt `#40` correction dead end where "去修正诊断" led to the
  decision diagnosis page, but "进入审核" opened an empty review queue and
  immediately closed as "全部审核完成".
- Added a dedicated answer-decision repair action for Decision Market entities:
  operators can mark an unknown answer object as target brand, confirmed
  competitor, or not part of the decision.
- Repairing an entity updates the matching `RecommendationEvent` rows:
  - target brand / confirmed competitor -> `HUMAN_CONFIRMED`;
  - rejected object -> `HUMAN_REJECTED`.
- Tightened workflow semantics so `HUMAN_REJECTED` events no longer count as
  valid answer-decision events. This prevents "not a brand/object" corrections
  from advancing Product Truth, Citation Evidence, Gap, Action, or Experiment.
- Split the workflow gates explicitly:
  - `all_reviews_done` means the current human review queue is empty;
  - `ready_to_continue` means answer decision recognition and downstream
    prerequisites are valid enough to generate Gap / Action.
- Localized the Decision Market table labels and actions in the single Prompt
  decision diagnosis page; raw enum values such as `RECOMMENDATION` and
  `UNKNOWN_ENTITY` are no longer the primary operator-facing labels.

Validation performed:

- `.venv/bin/python -m pytest tests/test_workflow_review_queue.py` passed.
- `.venv/bin/python -m compileall app` passed.
- Frontend `npm run build` passed with the existing Vite chunk-size warning.

## 2026-08-25 Citation URL WWW Normalization

- Removed the legacy source acquisition rule that blindly prefixed `www.` to
  known platform domains before fetching citation documents.
- Preserved explicit `www.` when it is already present in the URL, but no longer
  turns platform subdomains such as `zhuanlan.zhihu.com`,
  `baijiahao.baidu.com`, or `jingyan.baidu.com` into invalid
  `www.<subdomain>` hosts.
- Canonicalized acquired source URLs for analysis storage while keeping raw
  observed URLs available as `original_url`.
- Updated citation-facing frontend tables to display normalized source URLs /
  domains and keep the original href for audit-safe clicking.
- Clarified Golden Case citation acquisition UX:
  - batch "抓取引用资料" only acquires citation pages that have not yet been
    stored;
  - row-level "重抓" always re-fetches the selected failed source and updates
    its status, canonical URL, domain, fetch time, content hash, and failure
    reason.
- Added frontend failure reason summaries so operators can decide whether a
  failed source should be retried or manually supplemented.
- Added `action_url` to Golden Case source document reads and switched citation
  links, manual supplementation defaults, and row-level refetch payloads to use
  normalized action URLs instead of raw `url` values. Raw URL remains available
  for audit, but it no longer drives default operator actions.
- Added regression tests for platform subdomain handling and inner-`www`
  domains such as `gjzwfw.www.gov.cn`.

Validation performed:

- `.venv/bin/python -m pytest tests/test_source_qualification.py` passed.
- `.venv/bin/python -m compileall app` passed.
- Frontend `npm run build` passed with the existing Vite chunk-size warning.

## 2026-08-25 Citation Refetch Row Status Feedback

- Kept Golden Case source refetch as a background browser-first operation
  instead of relying on a visible browser window as the operator feedback.
- Added backend `fetch_method` to row-level refetch responses so the frontend
  can explain whether the latest attempt used browser capture or HTTP fallback.
- Added row-level frontend feedback for citation source refetch:
  - the selected row immediately shows `重抓中`;
  - the button enters loading state and is disabled during the request;
  - the row records the latest refetch result,正文长度,抓取方式, and failure
    summary after completion.
- Extended the row-level `重抓` entry to all non-valid source documents except
  manually marked empty pages, so `PARTIAL` / invalid short-body sources can be
  retried without manual API calls.
- This is an interaction-state fix only. It does not alter the single Prompt
  main workflow order or create a new Citation module.

Validation performed:

- `.venv/bin/python -m compileall app` passed.
- Frontend `npm run build` passed with the existing Vite chunk-size warning.
- `git diff --check` passed.

## 2026-08-25 Single Prompt Citation Evidence Run Entry

- Fixed the single Prompt workflow card getting stuck at step 4 (`引用证据`)
  after citation bodies had already been captured or manually supplemented.
- Root cause:
  - Citation Decision V1 correctly failed closed when Prompt `#40` had no
    `OptimizationEvidencePackage`;
  - the step 4 card only routed operators to `证据标注` for body capture and did
    not expose the next required operation: creating the current Prompt evidence
    package and running the citation decision chain.
- Added a dedicated frontend action for step 4:
  - current Prompt valid Runs -> create/reuse `OptimizationEvidencePackage`;
  - run Citation Decision V1 against that package;
  - refresh the workflow and keep the Citation Decision result bound to the
    current Prompt.
- Updated the step 4 copy:
  - no package -> `待生成证据包` / `生成证据包`;
  - loaded Citation Decision -> `已完成` / `查看证据正文`;
  - failed chain -> retry by regenerating/rerunning citation evidence.
- This keeps the existing 8-step single Prompt chain unchanged and only fixes a
  missing operation entry inside step 4.

Validation performed:

- Frontend `npm run build` passed with the existing Vite chunk-size warning.
- `git diff --check` passed.
- Prompt `#40` live smoke:
  - created Evidence Package `#15` from Runs `238,239,240,253,254,255`;
  - Citation Decision V1 returned `evidence_package_id = 15`;
  - summary returned `source_count = 68`, `primary_benchmark_count = 0`,
    `secondary_benchmark_count = 0`, and `recommended_action_count = 0`.

## 2026-08-26 Citation Decision V1.1 Phase 1 Formal Input Switch

- Added a guarded Phase 1 input switch for the formal Evidence Chain.
- Default remains off:
  - `citation_decision_v1_1_formal_input_enabled = false`
  - workflow/API callers must explicitly pass `use_answer_binding_v1_1 = true`
    or enable the env setting for a small-scope run.
- When enabled, formal Passage Retrieval and EvidenceAlignment can consume
  Phase 0 audited `AnswerUnit + AnswerDecisionBinding` rows as answer-derived
  recommendation reason inputs.
- The formal chain still does not consume `AnswerEvidenceShadowResult`
  directly. Shadow SUPPORTS cannot be promoted into Benchmark by itself.
- The old `RecommendationEvent.reasons_json` path remains active as fallback.
- Formal `EvidenceAlignment.machine_payload_json` now records reason
  provenance for Phase 1-derived rows:
  - `reason_source = ANSWER_DECISION_BINDING`
  - `formal_input_version = citation_decision_v1_1_formal_input.v1`
  - `answer_unit_id`
  - `decision_binding_id`
- This change does not alter the single Prompt workflow order, Product Truth
  gate, Benchmark rules, Gap rules, Action rules, StrategyCandidate creation,
  or Experiment creation.

Validation performed:

- `.venv/bin/python -m compileall app` passed.
- `.venv/bin/python -m pytest tests/test_answer_evidence_shadow.py tests/test_evidence_alignment.py tests/test_source_claim.py` passed:
  `24 passed`.
- Prompt `#40` Phase 1 smoke:
  - Stage 3 with `--use-answer-binding-v1-1` read `ShadowRun #7`
    `AnswerDecisionBinding` rows and produced `5` unique answer-derived
    reasons from `30` binding candidates.
  - Fixed the formal content gate so sources with valid captured body but no
    `SourceQuality` row can still be treated through `derive_content_status`;
    this allowed SourceDocument `#345` to enter retrieval candidates.
  - Stage 4 created `32` formal `SourceClaim` rows from `13` unique passages;
    `4` passages failed due DeepSeek network `ConnectError`, while successful
    grounded claims were committed.
  - Stage 5 was rerun with `--doc-id-filter 345` after fixing the script
    parameter pass-through. It created `110` formal alignments for SourceDocument
    `#345`: `6 SUPPORTS`, `5 NONE`, `99 RELATED`.
  - `Citation Decision V1` for Prompt `#40` / Evidence Package `#15` naturally
    advanced to `READY_FOR_HUMAN_CONFIRM` with `1` Primary Benchmark and `1`
    recommended action.
  - The recommended action exists only because formal
    `EvidenceAlignment.relation = SUPPORTS` was written; Shadow SUPPORTS was
    not consumed directly.
- Replaced user-facing `Benchmark` copy in the activated action/gap path with
  Chinese labels such as `对标来源` / `对标证据`; internal enum names remain
  unchanged.

## 2026-08-27 Citation Decision V1.1 Phase 1.1 Closure

- Closed the Phase 1.1 blockers before any Phase 2 multi-Prompt expansion.
- Fixed formal multi-Run evidence preservation:
  - formal `EvidenceAlignment` still deduplicates semantic reason judging for
    efficiency;
  - each Run/Binding observation is now written as an explicit formal alignment
    row;
  - V1.1-derived alignment payload records `observed_run_ids`,
    `observed_event_ids`, `observed_answer_unit_ids`,
    `observed_decision_binding_ids`, `run_coverage_count`, and
    `run_coverage_denominator`.
- Upgraded `use_answer_binding_v1_1` into a true read/write isolation switch:
  - when disabled, formal generation does not consume Answer Binding inputs;
  - Citation Decision read path also ignores existing formal rows marked
    `reason_source = ANSWER_DECISION_BINDING` or
    `formal_input_version = citation_decision_v1_1_formal_input.v1`;
  - existing DB rows are kept for audit and rollback.
- Fixed the runner/Layer3 interface drift:
  - `run_reason_driven_retrieval(..., doc_id_filter=...)` is now a real
    supported parameter;
  - `run_source_claim_extraction` and `run_evidence_alignment` pass the same
    document scope through the chain.
- Added capability-level Product Truth gating for action generation:
  - Benchmark evidence from `AnswerUnit` now produces concrete
    `capability_truth_targets`;
  - broad facts such as `短链生成` no longer allow actions for finer abilities
    such as `点击统计` or `自定义分享标题`;
  - unmatched concrete abilities keep Source Gap at `UNKNOWN`, Priority at
    `UNRESOLVED`, and block recommended actions.
- Updated Citation Decision summary copy so it distinguishes:
  - no eligible Benchmark;
  - eligible Benchmark present but execution gates are not satisfied;
  - recommended actions available for human confirmation.
- This change does not alter the single Prompt workflow order and does not
  start Phase 2.

Validation performed:

- `.venv/bin/python -m compileall -q app` passed.
- `.venv/bin/python -m pytest -q tests/test_answer_evidence_shadow.py tests/test_source_gap_v1.py` passed:
  `39 passed`.
- `.venv/bin/python -m pytest -q tests/test_evidence_alignment.py tests/test_source_claim.py` passed:
  `11 passed`.
- Prompt `#40` Phase 1.1 formal rerun:
  - command:
    `.venv/bin/python scripts/run_single_case_evidence.py --project-id 3 --prompt-id 40 --run-ids 238,239,240,253,254,255 --stage 5 --use-answer-binding-v1-1 --doc-id-filter 345`
  - `unique_reasons = 5`
  - `reason_observations = 30`
  - `answer_binding_candidates = 30`
  - `alignments_created = 300`
  - `judge_calls = 50`
  - `errors = []`
- Prompt `#40` post-rerun audit:
  - formal `EvidenceAlignment` for Prompt `#40` = `660`;
  - `SUPPORTS = 36`, distributed evenly across Runs
    `238,239,240,253,254,255`;
  - V1.1 OFF -> `0` Primary Benchmark and `0` recommended actions;
  - V1.1 ON -> `1` Primary Benchmark and `0` recommended actions because
    concrete Product Truth is missing for `点击统计`, `自定义分享标题`,
    and `营销场景使用`;
  - V1.1 OFF again -> restored to `0` Primary Benchmark and `0` recommended
    actions without deleting DB rows.

## 2026-08-27 Citation Decision V1.1 Phase 2A Lineage Eligibility

- Entered Phase 2A after Phase 0/1 checkpoint approval. Scope was limited to
  formal `EvidenceAlignment` Run lineage, consistency validation, and V1
  consumption eligibility.
- Corrected Source of Truth wording:
  - `SourceDocument` and `SourceClaim` are document-level facts and can be
    reused across Runs;
  - Run lineage is proven through current Run `ReferenceSource` plus
    `AnswerUnit` / `AnswerDecisionBinding` / `RecommendationEvent`;
  - `SourceClaim` must not be forced to carry `run_id`, and
    `EvidenceAlignment.run_id` alone is not sufficient.
- Added centralized formal eligibility validation in
  `app/modules/optimization/evidence_lineage.py`.
  - validates package Run membership, AnswerUnit lineage,
    AnswerDecisionBinding lineage, RecommendationEvent lineage,
    SourceDocument/SourceClaim consistency, current Run ReferenceSource proof,
    Legacy relation exclusion, and V1.1 feature-flag read gating;
  - returns `eligible_for_v1`, `ineligibility_reasons`, and the proving
    `reference_source_id`.
- Connected eligibility to the formal
  `source_analysis -> _attach_decision_support_benchmarks ->
  _decision_support_by_doc_id` read path.
  - only eligible alignments enter SUPPORTS/CONTRADICTS statistics,
    Decision Support, Benchmark, Gap, Priority/Action, and StrategyCandidate
    benchmark evidence;
  - ineligible historical rows are kept and surfaced as
    `ineligible_alignment_counts`.
- Tightened `observed_run_ids` discipline:
  - prompt-level evidence coverage is now derived from the unique `run_id` set
    of eligible SUPPORTS rows;
  - payload-provided `observed_run_ids` is not trusted for formal coverage.
- Added `backend/tests/test_evidence_lineage_v1.py` covering:
  - same SourceDocument cited by two Runs with one reusable SourceClaim;
  - current Run not citing the document;
  - AnswerUnit/RecommendationEvent cross-Run mismatch;
  - non-empty `run_id` without matching ReferenceSource;
  - Legacy Alignment exclusion;
  - observed_run_ids derived only from eligible Runs;
  - no duplicate SourceClaim required for Run lineage.
- Added a reusable read-only audit script:
  `backend/scripts/audit_prompt40_phase2a_lineage.py`.
- Added checkpoint/audit docs:
  - `docs/CITATION_DECISION_V1_1_PHASE2A_LINEAGE_CHECKPOINT.md`
  - `docs/PROMPT_40_PHASE2A_LINEAGE_AUDIT.md`
- No migration is required: all checks use existing DB columns and existing
  V1.1 payload fields.
- Phase 2A explicitly did not implement `DISCOVERABILITY_GAP`, Step 7, Step 8,
  Decision Stability, frontend masking, or Citation/Benchmark scoring changes.

Validation performed:

- `.venv/bin/python -m pytest -q tests/test_evidence_lineage_v1.py tests/test_citation_prominence_v1.py tests/test_source_gap_v1.py`
  passed: `38 passed`.
- `.venv/bin/python scripts/audit_prompt40_phase2a_lineage.py --output ../docs/PROMPT_40_PHASE2A_LINEAGE_AUDIT.md`
  passed.
- Prompt `#40` Phase 2A audit:
  - `source_run_ids = [238, 239, 240, 253, 254, 255]`;
  - formal `SourceClaim` count stayed `577 -> 577`;
  - Prompt `#40` formal `EvidenceAlignment` count stayed `660 -> 660`;
  - each Run has `6` eligible SUPPORTS and `5` eligible NO_SUPPORT;
  - historical `RELATED` alignments are excluded as
    `LEGACY_RELATION_ONLY = 594`;
  - prompt-level observed run coverage is derived as
    `[238, 239, 240, 253, 254, 255]`, `6/6`.

## 2026-08-27 Citation Decision V1.1 Phase 2B Capability Gap Diagnosis

- Entered Phase 2B after Phase 2A checkpoint. Scope was limited to
  capability/reason-level Gap Diagnosis.
- Implemented the deterministic earliest-failure decision tree:
  `Product Truth -> Relevant Asset Expression -> RetrievalCandidate ->
  Evidence Adoption`.
  - Product Truth is checked at capability/reason granularity before any
    asset, retrieval, or adoption logic can decide the Gap.
  - Relevant Brand Asset is selected from existing `PageSnapshot` rows by
    capability/prompt/benchmark relevance and records an audit snapshot
    (`selected_snapshot_id`, URL, title, matched terms, candidate IDs).
  - Discoverability only uses valid `RetrievalCandidate` rows from eligible
    evidence observed Runs.
  - Evidence Adoption only uses current package `ReferenceSource` plus existing
    `DecisionEvidenceAdoption` context, and keeps the causal-boundary note.
- Reused existing `source_gap_type`, `source_gap_precondition`,
  Product Truth, `PageSnapshot`, `RetrievalCandidate`, and
  `DecisionEvidenceAdoption` structures.
  - Added only derived payload fields on source analysis:
    `capability_gap_layer`, `capability_gap_diagnosis`,
    `relevant_asset_snapshot`, `retrieval_candidate_context`, and
    `evidence_adoption_context`.
  - Added the minimal `source_gap_type` value `DISCOVERABILITY_GAP`; it is not
    mapped to Step 7 in this phase.
- Kept Phase 2A lineage as the evidence gate:
  only eligible `EvidenceAlignment` rows can produce Benchmark Evidence for
  this Gap layer.
- Added/updated tests in `backend/tests/test_source_gap_v1.py` for:
  - stopping at Product Truth before later layers;
  - stopping at Relevant Asset Expression before retrieval/adoption;
  - valid Retrieval-only Discoverability;
  - retrieved-but-not-adopted Evidence Gap;
  - `NO_GAP` requiring both retrieval and adoption context.
- Added a read-only #40 regression script:
  `backend/scripts/audit_prompt40_phase2b_gap.py`.
- Added checkpoint/audit docs:
  - `docs/CITATION_DECISION_V1_1_PHASE2B_GAP_CHECKPOINT.md`
  - `docs/PROMPT_40_PHASE2B_CAPABILITY_GAP_AUDIT.md`
- No migration is required: the new outputs are derived API payload fields.
- Phase 2B explicitly did not develop Step 7, Step 8, Decision Stability,
  frontend masking, or Citation/Benchmark scoring changes.

Validation performed:

- `.venv/bin/python -m compileall -q app scripts/audit_prompt40_phase2b_gap.py`
  passed.
- `.venv/bin/python -m pytest -q tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py`
  passed: `35 passed`.
- `.venv/bin/python scripts/audit_prompt40_phase2b_gap.py --output ../docs/PROMPT_40_PHASE2B_CAPABILITY_GAP_AUDIT.md`
  passed.
- Prompt `#40` Phase 2B audit:
  - `PRIMARY_BENCHMARK = 1`, `SECONDARY_BENCHMARK = 0`;
  - benchmark `SourceDocument #345` is diagnosed as `CONTENT_GAP`;
  - earliest failure layer is `RELEVANT_ASSET_EXPRESSION`;
  - matched Product Truth status is `TRUE`;
  - relevant asset snapshot is `PageSnapshot #3`;
  - asset coverage is `MISSING`;
  - Retrieval context is `RETRIEVED`;
  - Evidence Adoption context is `NOT_ADOPTED`;
  - formal `SourceClaim` stayed `577 -> 577`;
  - Prompt `#40` formal `EvidenceAlignment` stayed `660 -> 660`.

## 2026-08-27 Citation Decision V1.1 Phase 3 StrategyCandidate Gate

- Entered Phase 3 after Phase 2B checkpoint approval. Scope was limited to
  Step 7: `StrategyCandidate + Human Strategy Review`.
- Audited current Gap scope:
  - `source_gap_type` remains a source-analysis compatibility/display field;
  - formal Step 7 consumption now uses derived `capability_gap_items`, so a
    Benchmark Source with multiple capability/reason gaps does not collapse
    into one natural-language source-level conclusion.
- Reused existing `OptimizationStrategyCandidate` and `effective_payload`
  infrastructure; no parallel Strategy table was added.
- Changed `confirm_citation_decision_vertical_slice` behavior:
  - creates pending `OptimizationStrategyCandidate` rows only;
  - ignores legacy `create_experiments=true` for this path;
  - no longer creates `InterventionPlan`, `OptimizationAction`, or
    `OptimizationExperiment`.
- Changed machine-generated vertical StrategyCandidates:
  - `review_status = PENDING_REVIEW`;
  - `effective_payload = {}`;
  - `effective_validation_status = PENDING`;
  - `experiment_id = null`.
- Added capability/reason-level Strategy payload fields:
  - `gap_item_ids`, `target_capability_or_reason`, `target_capabilities`;
  - `benchmark_evidence_ids`, `product_truth_refs`,
    `relevant_asset_refs`, `observed_run_ids`;
  - `proposed_direction`, `mechanism`, `why_candidate`, `blockers`,
    `validation_metric`;
  - `benchmark_channel_boundary` and `effective_payload_snapshot_policy`.
- Prevented Benchmark Channel leakage:
  - a `PRIMARY_BENCHMARK` from Zhihu no longer auto-fills
    `target_platform=ZHIHU`;
  - `target_platform`, `target_asset`, and `target_content_type` remain
    `UNRESOLVED` until the execution-planning phase.
- Updated human review handling:
  - accepted/edited candidates write `effective_payload`;
  - if execution fields remain unresolved, the status becomes
    `PENDING_HUMAN_CHANNEL_REVIEW`, not `VALIDATED`;
  - `strategy_to_experiment_plan` remains fail-closed before Step 8.
- Added `backend/scripts/audit_prompt40_phase3_strategy.py`.
- Added checkpoint/audit docs:
  - `docs/CITATION_DECISION_V1_1_PHASE3_STRATEGY_CHECKPOINT.md`
  - `docs/PROMPT_40_PHASE3_STRATEGY_AUDIT.md`
- No migration is required.
- Phase 3 explicitly did not develop Step 8, Action, Experiment, Baseline Lock,
  platform selection, content task creation, Decision Stability, or Citation /
  Benchmark / Gap scoring changes.

Validation performed:

- `.venv/bin/python -m compileall -q app scripts/audit_prompt40_phase3_strategy.py`
  passed.
- `.venv/bin/python -m pytest -q tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py`
  passed: `35 passed`.
- `.venv/bin/python scripts/audit_prompt40_phase3_strategy.py --output ../docs/PROMPT_40_PHASE3_STRATEGY_AUDIT.md`
  passed.
- Prompt `#40` Phase 3 audit:
  - created `StrategyCandidate #40`;
  - capability Gap items: `点击统计`, `自定义分享标题`, `营销场景使用`;
  - each item keeps `CONTENT_GAP / RELEVANT_ASSET_EXPRESSION` and observed
    Runs `[238, 239, 240, 253, 254, 255]`;
  - before review: `PENDING_REVIEW`, `effective_validation_status=PENDING`;
  - after human edit/review: `ACCEPTED_WITH_EDITS`,
    `effective_validation_status=PENDING_HUMAN_CHANNEL_REVIEW`;
  - `OptimizationAction` stayed `16 -> 16`;
  - `OptimizationExperiment` stayed `16 -> 16`;
  - `strategy_to_experiment_plan` was rejected both before review and after
    review because Step 8 execution fields remain unresolved.

## 2026-08-28 Step 7 StrategyCandidate Expression Upgrade

- Scope was limited to Step 7 strategy candidate content and page expression.
  No Step 8, Step 9, Evidence, Benchmark, Gap, Action, Experiment, Baseline, or
  Decision Stability logic was redesigned.
- Extended vertical StrategyCandidate structured payload with Step 7 strategy
  fields:
  - `target_decision_change`;
  - `strategic_hypothesis`;
  - `priority_capabilities`;
  - `required_signals`;
  - `non_goals`;
  - `strategy_boundary_note`.
- Kept existing Step 8 compatibility fields in the payload, including
  `recommended_action`, `changed_features`, `required_sections`,
  `target_metric`, `product_truth_refs`, `relevant_asset_refs`, and
  `observed_run_ids`.
- Preserved execution isolation:
  - `target_platform = UNRESOLVED`;
  - `target_asset = UNRESOLVED`;
  - `target_content_type = UNRESOLVED`;
  - `intervention_type = UNRESOLVED`;
  - Benchmark channel still cannot become execution channel in Step 7.
- Updated the frontend Strategy page so the StrategyCandidate card leads with:
  - AI decision opportunity;
  - strategy hypothesis;
  - priority capabilities/reasons;
  - required brand-capability signals;
  - non-goals and Step 7/8 boundary.
- Demoted execution/platform/experiment controls to a Step 8 entry block with
  explicit copy that channel, asset, content form, baseline, release, and
  experiment details belong to Step 8.
- Added `backend/tests/test_strategy_step7_v1.py` to lock:
  - strategy payload is not only a gap restatement;
  - capability-level priority supports ties;
  - required signals do not choose execution channel or page sections;
  - non-goals prevent Benchmark channel leakage;
  - unresolved execution fields remain unresolved for Step 8.
- Prompt `#40` real regression:
  - generated `StrategyCandidate #43`;
  - status is `PENDING_REVIEW`;
  - target decision change is to make `爱短链` build a clearer
    brand-capability-recommendation-reason association for `点击统计`,
    `自定义分享标题`, and `营销场景使用`;
  - all three capabilities are `P1` with `6/6` observed Run coverage;
  - `target_platform` remains `UNRESOLVED`.

Validation performed:

- `.venv/bin/python -m pytest tests/test_strategy_step7_v1.py` passed:
  `4 passed`.
- `.venv/bin/python -m pytest tests/test_source_gap_v1.py` passed:
  `47 passed`.
- `source /Users/bmwqr/.nvm/nvm.sh && nvm use 18.20.8 && npm run build`
  passed.

## 2026-09-01 Step 7 Current Candidate Display Bugfix

- Fixed a frontend state-integrity bug where Step 7 strategy generation could
  succeed, but the Strategy page still displayed:
  `当前流程 0 个策略候选 / 全部 N 个版本`.
- Root cause:
  - the Strategy page prioritized `workflowData.current_strategy_candidate_ids`
    when filtering current candidates;
  - after generating a new current StrategyCandidate, the page refreshed the
    candidate list but did not refresh workflow status in the same path;
  - stale workflow IDs could therefore hide the newly generated candidate even
    when the API returned `eligible_for_current_step7 = true`.
- Fix:
  - refresh Prompt workflow status after current Step 7 generation;
  - when workflow IDs are stale and match no visible current candidate, fall
    back to candidates whose backend eligibility says
    `eligible_for_current_step7 = true`;
  - opening Strategy confirmation now refreshes the current Prompt workflow and
    uses the current evidence package from either Citation Decision or workflow
    context.
- Boundary:
  - no Strategy generation rule changed;
  - no historical StrategyCandidate is counted as current;
  - no Step 8 / Action / Experiment behavior changed.
- Prompt `#40` verification:
  - backend workflow reports `current_strategy_candidate_id = 50`;
  - Step 7 status is `PENDING_REVIEW`;
  - Step 8 remains `LOCKED` until Strategy is confirmed.

Validation performed:

- `source /Users/bmwqr/.nvm/nvm.sh && nvm use 18.20.8 && cd geo-platform/frontend && npm run build`
  passed.
- `curl -s http://127.0.0.1:8000/api/optimization/workflow/3/40/status`
  confirms `1 个当前策略候选待人工审核`.
- `git diff --check` passed.

## 2026-09-01 Step 7 No-Strategy Terminal State Bugfix

- Fixed a workflow state-source mismatch observed on Prompt `#19`.
- Symptom:
  - frontend loaded Prompt `#19` with Steps 1-6 completed;
  - Step 7 showed no current StrategyCandidate and no generatable
    content/evidence gap;
  - backend workflow still reported `strategy_step_status=READY_TO_GENERATE`
    because it only checked whether upstream reviews were done.
- Root cause:
  - Step 7 workflow status did not consume the formal Citation Decision result;
  - `reviews_done` was incorrectly treated as sufficient to say a
    StrategyCandidate could be generated.
- Fix:
  - workflow status now calls the current Citation Decision V1 path for the
    current Prompt/Evidence Package when no current candidate exists;
  - Step 7 is `READY_TO_GENERATE` only when formal recommended actions include
    a `CONTENT` or `EVIDENCE` route;
  - otherwise Step 7 returns `NO_STRATEGY` with
    `当前没有可生成策略的内容/证据缺口`;
  - Step 8 returns `NO_EXPERIMENT` with
    `本轮没有策略候选，无需创建实验草案`.
- Frontend behavior:
  - `NO_STRATEGY` is displayed as `无需策略`;
  - Step 8 is displayed as `无需创建`;
  - users can still click `查看依据` to inspect the Citation/Gap context.
- Workflow done semantics:
  - `NO_STRATEGY` and `NO_EXPERIMENT` are terminal done states for the current
    Prompt, not pending work;
  - they mean the current V1 chain has no strategy or experiment to create.
- Boundary:
  - no Citation / Benchmark / Gap / Strategy generation rules changed;
  - no historical StrategyCandidate or Experiment is counted as current;
  - no Step 8 materialization behavior changed.

Validation performed:

- `.venv/bin/python -m pytest -q tests/test_workflow_review_queue.py`
  passed: `12 passed`.

## 2026-09-01 Prompt Switch Workflow Loading State Bugfix

- Fixed a single Prompt workflow display issue observed on Prompt `#19`.
- Symptom:
  - after switching to Prompt `#19`, the single Prompt page could temporarily
    show only Step 1 as completed and provide no meaningful next-step entrance;
  - backend status for the same Prompt actually showed the chain had progressed
    to evidence review:

```text
collection: 40 Runs
answer_semantic: 23 effective decision-event groups
event_review: 31/31 reviewed
evidence: 504 SUPPORTS
evidence_review: 72/504 reviewed
strategy_step_status: NOT_READY
next gate: evidence human review
```

- Root cause:
  - switching Prompt clears `workflowData` for context hygiene;
  - `workflow/status` for historical Prompts with many EvidenceAlignment rows
    could be slow;
  - during that empty loading window, the frontend rendered pending/default
    cards from `workflowData = null`, which looked like a real product state.
- Fix:
  - frontend now has an explicit `workflowLoading` state and renders a Chinese
    loading notice instead of fake empty workflow cards while the current Prompt
    status is being read;
  - Prompt context changes now reload both dashboard and workflow status from a
    single effect instead of relying on the selector handler;
  - Step 4 now surfaces pending evidence review directly as
    `待人工确认 / 审核证据关系`; Steps 5-6 wait for evidence confirmation
    instead of looking complete while Step 7 remains locked;
  - workflow status now counts SUPPORTS / reviewed SUPPORTS with SQL aggregate
    queries instead of loading all matching EvidenceAlignment rows into Python.
- Boundary:
  - no workflow order changed;
  - no Evidence / Benchmark / Gap / Strategy / Experiment rules changed;
  - this only fixes state display integrity and status-read performance.

## 2026-09-01 Evidence Review Confirmation Feedback Bugfix

- Fixed a UX/state issue where clicking `确认这一组支持` could feel like it
  had no effect even though the backend wrote successfully.
- Verified backend logs for Prompt `#19` showed repeated successful writes:

```text
POST /api/optimization/workflow/review/alignments/confirm-batch 200 OK
```

- Verified Prompt `#19` status advanced from:

```text
72/504 -> 168/504 -> 240/504
```

and review queue shrank from `6` groups to `3` groups.
- Root cause:
  - the confirm button had no per-group submitting state;
  - users could click repeatedly while waiting;
  - follow-up workflow/citation refreshes could be slow enough that the UI felt
    unchanged.
- Fix:
  - each evidence review group now has its own `确认中` loading state;
  - duplicate clicks for the same group are disabled while submitting;
  - after a successful `confirm-batch`, the confirmed group is removed from the
    modal immediately using functional React state;
  - slower workflow/citation refreshes run in the background and no longer block
    the user from continuing with the next group.
- Boundary:
  - no evidence grouping semantics changed;
  - no backend review write logic changed;
  - no Strategy or Experiment behavior changed.

## 2026-09-01 Evidence Review Batch Write Performance Bugfix

- Fixed a backend performance issue where `确认这一组支持` still spent too long
  writing large semantic groups.
- Root cause:
  - `batch_confirm_alignments` loaded and updated each `EvidenceAlignment` one
    by one via ORM `db.get`;
  - Prompt `#19` groups can contain dozens to hundreds of Run-level alignments,
    so the button could keep spinning even though the request was valid.
- Fix:
  - deduplicate submitted alignment IDs;
  - read existing IDs in one query;
  - update `review_status / relation / reviewer` in one SQL bulk update;
  - keep `missing_ids` in the response for compatibility.
- Validation:
  - `.venv/bin/python -m pytest -q tests/test_workflow_review_queue.py`
    passed: `17 passed`;
  - `.venv/bin/python -m compileall app` passed.
- Boundary:
  - no evidence semantics changed;
  - no review group semantics changed;
  - no Benchmark / Gap / Strategy / Experiment behavior changed.

## 2026-09-01 Workflow Status Heavy Recompute Removal

- Fixed a second confirmation UX issue where the final evidence group could be
  confirmed successfully but the page still kept spinning during follow-up
  status refresh.
- Root cause:
  - after all evidence reviews were completed, `workflow/status` called
    `citation_decision_vertical_slice(...)` to decide whether Step 7 had
    generatable actions;
  - that made a status read execute heavy Citation Decision read-model logic.
- Fix:
  - `workflow/status` now remains a lightweight Gate/status endpoint;
  - when upstream reviews are complete and V1.1 input exists, Step 7 reports
    `READY_TO_GENERATE` without recomputing Citation Decision;
  - the actual StrategyCandidate generation still happens only through the
    explicit Step 7 generation action.
- Test coverage:
  - added a regression test that fails if `workflow/status` tries to recompute
    Citation Decision while determining Step 7 readiness.
- Validation:
  - `.venv/bin/python -m pytest -q tests/test_workflow_review_queue.py`
    passed: `17 passed`;
  - `.venv/bin/python -m compileall app` passed.
- Boundary:
  - no Citation Decision formula changed;
  - no Benchmark / Gap / Strategy generation rule changed;
  - this only separates read-only workflow status from explicit generation.

## 2026-09-02 Evidence Review Carry-Forward On Alignment Rerun

- Fixed a rerun loop observed on Prompt `#19`.
- Symptom:
  - user completed evidence review: `504/504`;
  - clicked `重新运行当前主链`;
  - the pipeline completed after about 25 minutes and generated new
    `EvidenceAlignment` rows;
  - Step 4 reset to `0/480` because the new alignments were all
    `MACHINE_GROUNDED`.
- Root cause:
  - `run_evidence_alignment` deletes current Prompt alignments before rerun;
  - new alignments were created without preserving prior human review state;
  - duplicate SourceClaim IDs can be regenerated for the same source sentence,
    so carrying by `source_claim_id` would not be reliable.
- Fix:
  - before deleting old alignments, capture human-reviewed semantic signatures:

```text
semantic_reason_key / recommendation_reason_id
+ SourceDocument
+ normalized SourceClaim text
+ relation
```

  - after rerun, if a new alignment has the same signature, carry forward
    `HUMAN_CONFIRMED` / `HUMAN_REJECTED` and reviewer;
  - write carry-forward provenance into `human_payload_json` for audit.
- Validation:
  - `.venv/bin/python -m pytest -q tests/test_workflow_review_queue.py`
    passed: `18 passed`;
  - `.venv/bin/python -m compileall app` passed.
- Boundary:
  - no machine evidence relation is changed;
  - no new SUPPORTS are auto-created;
  - only previously human-reviewed same-semantic evidence inherits review state.

## 2026-09-02 Workflow Step Loading Scope And V1.1 Input Wording

- Fixed a frontend status feedback issue observed on Prompt `#19`.
- Symptom:
  - backend reported Step 4 evidence review completed: `4/4` groups reviewed;
  - backend latest `PromptAnalysisRun` was `COMPLETED`, not `RUNNING`;
  - the single Prompt page could still make Step 4 and Step 7 both look like
    they were spinning because their buttons shared the same
    `citationDecisionLoading` flag.
- Data finding:
  - Prompt `#19` has `480` reviewed SUPPORTS rows, grouped into `4` reviewed
    semantic evidence groups;
  - those rows are legacy `RECOMMENDATION_EVENT_REASONS_JSON` alignments, not
    V1.1 `ANSWER_DECISION_BINDING` formal input;
  - therefore Step 7 may still require V1.1 formal input generation, but Step 4
    itself is not running and should not display as if it is.
- Fix:
  - added a workflow action loading scope in the frontend so Citation evidence,
    Strategy generation, and V1.1 input generation no longer light each other;
  - changed user-facing Step 7 text from "重新运行当前主链" to "生成 V1.1 输入"
    when the backend status is `NEEDS_CURRENT_ANALYSIS`;
  - updated backend workflow detail text to describe the missing dependency as
    V1.1 formal evidence input rather than a generic main-chain rerun.
- Validation:
  - `.venv/bin/python -m pytest -q tests/test_workflow_review_queue.py`
    passed: `18 passed`;
  - `.venv/bin/python -m compileall app` passed;
  - `git diff --check` passed.
- Boundary:
  - no Evidence / Benchmark / Gap / Strategy rule changed;
  - no legacy evidence is promoted into V1.1 formal input;
  - this only fixes loading-state ownership and user-facing workflow wording.

## 2026-09-03 Phase C2-A Binding-aware Candidate Builder Shadow

- Added read-only shadow comparison to the V1.1 incremental materialization
  planner for EvidenceAlignment candidate generation.
- The new `evidence_alignment.candidate_builder_shadow` compares:

```text
current = production_all_viable_pairs.v1
proposed = binding_aware_candidate_builder.v1
identity = ALIGNMENT_V1 materialization_key
```

- The implementation reports shared / old_only / new_only semantic candidate
  counts and audits old_only candidates that already have current
  SUPPORTS/CONTRADICTS EvidenceAlignment rows.
- `old_only_supports_contradicts` is grouped by unique semantic
  `materialization_key + relation`; each group includes all row-level
  `alignment_ids`, row count, review-status counts, reason text, SourceClaim,
  document, and source URL.
- Real local DB shadow results:

```text
#19: current=583, proposed=188, shared=188, old_only=395, new_only=0
#19 old_only SUPPORTS/CONTRADICTS: 15 semantic groups / 360 row-level alignments

#40: current=65, proposed=65, shared=65, old_only=0, new_only=0
#40 old_only SUPPORTS/CONTRADICTS: 0
```

- Validation:
  - `.venv/bin/python -m pytest -q tests/test_incremental_materialization_planner.py tests/test_evidence_alignment.py`
    passed: `24 passed`;
  - `.venv/bin/python -m compileall app` passed.
- Boundary:
  - no formal `run_evidence_alignment(...)` execution path changed;
  - no EvidenceAlignment cutover enabled;
  - no Benchmark / Gap / Strategy / Step 7 / Step 8 behavior changed;
  - Phase C2-A stops at shadow comparison and audit output only.

## 2026-09-03 Phase C2-A.1 Critical Recall Loss Diagnosis

- Extended the read-only EvidenceAlignment candidate-builder shadow with
  per-critical-pair recall traces and reason-cluster summaries.
- Added diagnostics for binding status, same-run citation anchor availability,
  hard filter result, lexical score, rank before TopK, final exclusion reason,
  diagnosis classification, and proposed generalized fix layer.
- Explicitly reports unavailable fields instead of guessing:

```text
BM25_score=unavailable
semantic_score=unavailable
structural_passage_distance=unavailable
section_relation=unavailable
same_answer_context=unavailable
```

- Real local DB diagnosis for #19:

```text
critical_old_only=15 semantic groups / 360 row-level alignments
TRUE_POSITIVE_RECALL_LOSS=1
LEGACY_UNPROVEN_CROSS_PRODUCT=14
TOPK_TRUNCATION=10
BELOW_SCORE_THRESHOLD=5
L0_EXPLICIT=107
L1_ANSWER_CONTEXT=0
L2_RUN_SCOPE=0
L3_PROMPT_SCOPE=81
```

- TopK is not applied to L0 Explicit Binding. It is only active on L3
  Prompt-scope fallback in the current shadow builder.
- The #19 true-positive blocker is the HUMAN_CONFIRMED SUPPORTS pair:

```text
reason=可以自动生成加密短链
claim_id=267
final_exclusion_reason=TOPK_TRUNCATION
rank_before_topk=6
top_k=5
```

- The remaining 14 groups are machine-only and have no same-run citation anchor
  or AnswerUnit context, so they are classified as
  `LEGACY_UNPROVEN_CROSS_PRODUCT`.
- #40 remains clean: `old_only=0`, `critical_old_only=0`.
- Validation:
  - `.venv/bin/python -m pytest -q tests/test_incremental_materialization_planner.py tests/test_evidence_alignment.py`
    passed: `24 passed`;
  - `.venv/bin/python -m compileall app` passed.
- Boundary:
  - no formal EvidenceAlignment candidate generation changed;
  - no old Alignment rows deleted or verdicts changed;
  - no LLM calls;
  - no Benchmark / Gap / Strategy / Step 7 / Step 8 behavior changed.

## 2026-09-03 Phase C2-A.2 Final Shadow Validation

- Re-audited the only HUMAN_CONFIRMED #19 blocker by reading SourceClaim #267,
  its passage, source context, and historical Alignment metadata.
- Source context explicitly states the system automatically generates encrypted
  jump links, so the blocker remains a true recall loss:

```text
reason=可以自动生成加密短链
claim_id=267
original_verdict=SUPPORTS
original_review_status=HUMAN_CONFIRMED
new_audit_decision=TRUE_POSITIVE_RECALL_LOSS
```

- Renamed machine-only old-only classification from legacy pollution wording to
  neutral `LEGACY_UNPROVEN_CROSS_PRODUCT`.
- Implemented shadow-only L2 Run-scope recall in the proposed candidate
  builder. L1 is explicitly marked `L1_UNAVAILABLE_BY_SCHEMA` because current
  AnswerUnit rows do not store reliable sentence/paragraph-level citation
  co-location.
- The shadow ladder now short-circuits:

```text
L0 Explicit Binding
-> L1 Answer Context
-> L2 Run Scope
-> L3 Prompt Scope
```

- Final local DB shadow:

```text
#19: current=583, proposed=79, shared=79, old_only=504, new_only=0
#19 critical: TRUE_POSITIVE_RECALL_LOSS=1, LEGACY_UNPROVEN_CROSS_PRODUCT=14
#19 recall: L0=0, L1=0, L2=28, L3=51
#19 fallback triggers: binding_missing=27, no_viable_candidate=20, below_threshold=1

#40: current=65, proposed=65, shared=65, old_only=0, critical=0
#40 recall: L0=65, L1=0, L2=0, L3=0
```

- Policy simulation for #19 true-loss blocker:

```text
Policy A Hard TopK=5: candidates=79, critical_loss=1, external_llm_estimate=60
Policy B Threshold+cap25: candidates=145, critical_loss=0, external_llm_estimate=69
Policy C TopK+margin0.05: candidates=92, critical_loss=0, external_llm_estimate=61
```

- Validation:
  - `.venv/bin/python -m pytest -q tests/test_incremental_materialization_planner.py tests/test_evidence_alignment.py`
    passed: `24 passed`;
  - `.venv/bin/python -m compileall app` passed.
- Boundary:
  - formal EvidenceAlignment execution was not changed;
  - no LLM calls were made;
  - no historical Alignment verdicts were changed;
  - no C2-B cutover.

## 2026-09-03 Phase C2-B Production Candidate Builder Cutover

- Cut over formal `run_evidence_alignment(...)` candidate membership to the
  shared Binding-aware Candidate Builder with
  `POLICY_D_TOPK_WITH_BOUNDARY_TIES`.
- Added runtime rollback flag:
  `use_binding_aware_alignment_candidates_v1_1=true` by default. Setting it to
  false restores the frozen legacy all-viable-pairs candidate path.
- Extracted the candidate builder into
  `app/modules/optimization/evidence_alignment_candidates.py` and made the
  read-only planner and production execution call the same implementation.
- Added production `candidate_dry_run=true` support for candidate-key parity
  checks without DB writes or external LLM calls.
- Preserved historical `EvidenceAlignment` rows on the cutover path. Current
  candidate observation rows are reused by deterministic observation signature;
  old-only historical rows and human review metadata are not deleted.
- Real local DB dry validation:

```text
#19: production_candidate_keys=92, planner_vs_production_diff=0,
     claim_267_present=true, L0=0, L1=0, L2=28, L3=64
#40: production_candidate_keys=65, planner_vs_production_diff=0,
     L0=65, L1=0, L2=0, L3=0
```

- Validation:
  - `.venv/bin/python -m compileall app/modules/optimization app/core` passed.
  - `.venv/bin/python -m pytest -q tests/test_incremental_materialization_planner.py tests/test_evidence_alignment.py`
    passed: `26 passed`.

- Boundary:
  - no EvidenceAlignment verdict semantics changed;
  - no C1 materialization key/ledger/legacy/LLMCallCache recovery changed;
  - no LLM calls were made during validation;
  - no Benchmark / Gap / Strategy / Step 7 / Step 8 behavior changed;
  - no Phase D work started.

## 2026-09-03 Phase D Materialization Execution Reliability

- Added a minimal shared materialization execution primitive in
  `app/modules/optimization/materialization_executor.py`.
- Added `owner_id` and `lease_expires_at` to both
  `SourceClaimMaterialization` and `EvidenceAlignmentMaterialization`; existing
  `status`, `attempt_count`, `error_message`, `started_at`, `completed_at`, and
  `updated_at` remain the execution truth.
- Added Phase D configuration:
  `use_materialization_executor_v1_1`,
  `materialization_lease_seconds`,
  `materialization_wait_timeout_seconds`,
  `materialization_poll_interval_seconds`,
  `materialization_batch_size`,
  `materialization_max_attempts`, and
  `max_external_llm_concurrency`.
- Wired SourceClaim extraction and EvidenceAlignment execution through atomic
  claim/lease when the Phase D flag is enabled. Frozen legacy execution remains
  available by disabling the flag.
- Preserved Phase B/C semantics:
  - SourceClaim and EvidenceAlignment materialization keys unchanged;
  - C2 candidate builder and Policy D unchanged;
  - LLMCallCache and legacy recovery remain recovery sources only;
  - legacy recovery now writes through the claimed ledger row on the executor
    path rather than becoming a second truth source.
- Added execution metrics for required/unique jobs, ledger hits, claim owner,
  owned-by-other, lease reclaim, retry, failed retryable/final, batch count,
  observed concurrency, and executor id.
- Added concurrency and reliability tests covering:
  - same key with 10 workers -> one ledger row and one owner external section;
  - 100 duplicate work items -> one unique job;
  - 10 distinct keys with max concurrency 2 -> observed max <= 2;
  - valid lease blocks duplicate execution;
  - expired lease reclaims the same row and increments attempts;
  - crash/resume uses DONE hits and reclaims expired work;
  - FAILED_RETRYABLE retries the same row;
  - FAILED_FINAL does not retry.
- Real local DB dry validation after Phase D:

```text
#19: candidate_keys=92, planner_diff=0, claim_267=true, writes=0
#40: candidate_keys=65, planner_diff=0, writes=0
```

- Validation:
  - `.venv/bin/python -m compileall app/modules/optimization app/core app/models` passed.
  - `.venv/bin/python -m pytest -q tests/test_materialization_executor.py tests/test_evidence_alignment.py tests/test_source_claim.py tests/test_incremental_materialization_planner.py`
    passed: `47 passed`.
  - `git diff --check` passed.
- External production DeepSeek concurrency smoke was not run in this environment;
  record as `PHASE_D_EXTERNAL_CONCURRENCY_SMOKE_DEFERRED`.
- Boundary:
  - no Candidate Builder / Policy D / Recall Ladder changes;
  - no SourceClaim or EvidenceAlignment semantic identity changes;
  - no Benchmark / Gap / Strategy / Step 7 / Step 8 behavior changed;
  - no Phase E work started.

## 2026-09-03 Phase E Product Readiness & Final Acceptance

- Added a read-only V1.1 final acceptance report module:
  `app/modules/optimization/readiness_report.py`.
- Added API endpoint:
  `GET /api/optimization/workflow/{project_id}/v1-1-final-acceptance`.
- Added script:
  `scripts/v1_1_final_acceptance.py`, which writes
  `docs/v1_1_final_acceptance.md` from the current local DB.
- Added single Prompt workflow UI materialization progress:
  SourceClaim and EvidenceAlignment now show Required, Ledger HIT, legacy
  recovery, LLMCallCache recovery, Missing, Retrying, Failed, conservation, and
  estimated new LLM work. The UI text explicitly says resume only processes
  Missing / Failed / Stale materializations and does not recompute DONE ledger
  rows.
- Added Phase E guardrail tests for duplicate Run and citation explosion
  stress behavior.
- Real local DB read-only final acceptance:

```text
#19: Runs=40, Evidence Package #12 v8, candidate_keys=92,
     planner_vs_production_diff=0, SourceClaim external_required=1385,
     Alignment naive=9666 -> candidates=92, external_required=61,
     Step7=NOT_READY, Step8=LOCKED
#40: Runs=6, Evidence Package #15 v2, candidate_keys=65,
     planner_vs_production_diff=0, SourceClaim external_required=529,
     Alignment naive=230 -> candidates=65, external_required=15,
     Step7=PENDING_REVIEW, Step8=LOCKED
Immediate rerun external production smoke: DEFERRED_BY_ENVIRONMENT_POLICY
INTERNAL_PRODUCT_READY=true
EXTERNAL_PRODUCTION_VERIFIED=false
remaining_blockers=[ENVIRONMENT_POLICY_EXTERNAL_LLM_SMOKE_DEFERRED]
```

- Validation:
  - `.venv/bin/python -m compileall app/modules/optimization app/core app/models` passed.
  - `.venv/bin/python -m pytest -q tests/test_v1_1_final_readiness.py tests/test_materialization_executor.py tests/test_evidence_alignment.py tests/test_source_claim.py tests/test_incremental_materialization_planner.py`
    passed: `49 passed`.
  - frontend `npm run build` passed after loading Node with nvm; Vite emitted
    only the existing large chunk warning.
- Boundary:
  - no SourceClaim / EvidenceAlignment materialization identity changes;
  - no Candidate Builder / Recall Ladder / Policy D changes;
  - no Product Truth / Benchmark / Gap / Strategy / Step 7 / Step 8 semantic
    changes;
  - no external LLM call was made;
  - Phase E stops here and does not start V1.2.

## 2026-09-03 Phase E UX Hotfix: Evidence Review Confirmation Responsiveness

- Fixed a frontend responsiveness regression introduced by the Phase E
  materialization progress panel.
- Root cause: `refreshWorkflowStatusForPrompt(...)` synchronously fetched
  `/materialization-plan` after every workflow status refresh. On #19 the
  read-only planner can take about one minute, so a successful evidence
  `confirm-batch` could appear to keep spinning while the slow planner refresh
  was still in flight.
- Change:
  - workflow status refresh now only fetches `/status`;
  - materialization planner refresh runs through a separate
    `refreshWorkflowMaterializationPlan(...)` path;
  - the materialization panel has its own loading tag and manual refresh button;
  - stale planner responses are guarded by a request sequence so switching
    Prompt cannot overwrite the current Prompt's state.
- Real state check during the incident:

```text
POST /api/optimization/workflow/review/alignments/confirm-batch -> 200
#19 evidence_review progressed to 7/20 groups reviewed
review-queue now has 13 remaining alignment groups
```

- Validation:
  - frontend `npm run build` passed after loading Node with nvm; Vite emitted
    only the existing large chunk warning.
- Boundary:
  - no backend workflow semantics changed;
  - no SourceClaim / EvidenceAlignment / Candidate Builder / Benchmark / Gap /
    Strategy / Step 7 / Step 8 behavior changed.

## 2026-09-03 Phase E UX Hotfix: Review Queue Loading Isolation

- Investigated a follow-up frontend issue where clicking `加载待审核项` in the
  human review modal could keep spinning.
- Real API checks showed the backend was healthy:

```text
GET /api/optimization/workflow/3/19/review-queue -> READY, 13 alignment groups remaining
GET /api/optimization/workflow/3/19/competitor-candidates -> []
```

- Root cause: the review modal reused the app-wide `loading` state, which is
  also used by project refresh, evidence generation, strategy actions, and other
  long-running UI tasks. A global loading owner can therefore make the review
  queue button spin even when the review queue endpoints are fast.
- Change:
  - added `reviewQueueLoading` for `加载待审核项`;
  - added `reviewAnalysisLoading` for `运行机器分析`;
  - closing the modal clears only review-modal loading and local review state;
  - review queue loading falls back to `activePromptId` when `currentWorkflowData`
    is still loading.
- Validation:
  - frontend `npm run build` passed after loading Node with nvm; Vite emitted
    only the existing large chunk warning.
- Boundary:
  - frontend loading-state isolation only;
  - no review API, database state, EvidenceAlignment semantics, Candidate
    Builder, Benchmark, Gap, Strategy, Step 7, or Step 8 behavior changed.

## 2026-09-03 Phase E UX Hotfix: Materialization Planner Manual-Only

- Investigated a persisted "refresh then still spinning" issue in #19 evidence
  review.
- Real backend logs showed SQLAlchemy pool exhaustion while slow
  `/materialization-plan` requests were still running:

```text
QueuePool limit of size 5 overflow 10 reached, connection timed out
```

- Root cause: `loadWorkflowForPrompt(...)` still auto-triggered the read-only
  materialization planner after every Prompt/page load. On #19 this diagnostic
  endpoint can take about one minute; repeated browser refreshes can stack
  concurrent planner requests and starve normal endpoints such as
  `review-queue`, `channels`, `experiments`, and `decision-market`.
- Change:
  - removed automatic `/materialization-plan` loading from Prompt workflow load;
  - kept materialization progress as an explicit manual action only;
  - added visible `查看物化进度` / `刷新物化进度` buttons in workflow action
    areas so diagnostics remain available without blocking review work.
- Boundary:
  - frontend request scheduling only;
  - no backend planner, SourceClaim, EvidenceAlignment, Candidate Builder,
    Benchmark, Gap, Strategy, Step 7, or Step 8 semantics changed.

## 2026-09-03 Phase E UX Hotfix: Review Confirmation Post-Refresh Scope

- Investigated a remaining #19 issue where the first evidence group confirmed
  quickly, but the next confirmation could spin again.
- Real log sequence showed the confirmation POST and lightweight review/status
  refreshes returned `200 OK`; the stall happened after the first confirmation
  when the frontend background refresh entered
  `/projects/{project_id}/prompts/{prompt_id}/citation-decision-v1`, which is a
  heavier current-chain decision view on #19.
- Change:
  - evidence alignment confirmation no longer auto-runs `citation-decision-v1`;
  - recommendation event confirm/reject no longer auto-runs
    `citation-decision-v1`;
  - review modal confirmations only post the review decision, update the local
    queue, and refresh lightweight workflow/review state.
- Product behavior:
  - users can continue confirming evidence groups without waiting for a full
    Citation Decision view refresh after every group;
  - the main chain display remains refreshable via the explicit `刷新主链路`
    action.
- Boundary:
  - frontend post-confirm refresh scope only;
  - no review API, database schema, EvidenceAlignment semantics, Candidate
    Builder, Benchmark, Gap, Strategy, Step 7, or Step 8 behavior changed.

## 2026-09-03 Phase E UX Hotfix: Citation Decision Auto-Load Guard

- Investigated a further #19 continuous-review issue: after two successful
  group confirmations, the next group could still spin.
- Real state:

```text
#19 evidence_review advanced to 10/20
confirm-batch POSTs returned 200
review-queue / competitor-candidates / status returned 200
```

- Remaining root cause: the page-level `useEffect` still auto-loaded
  `citation-decision-v1` whenever the validation/optimization page and
  workflow state changed. While evidence review is incomplete this full
  decision view cannot unlock Step 7, and on #19 it is heavy enough to interfere
  with continuous review.
- Change:
  - page-level auto `citation-decision-v1` now waits until the matching
    `workflow/status` has loaded;
  - it short-circuits while `evidence_review` exists and is not done;
  - the evidence step's UI readiness can use `workflow/status` evidence state
    instead of requiring full Citation Decision data.
- Added a bounded review-action request wrapper for human review POSTs. If a
  local DB lock or request queue issue prevents a response for 20 seconds, the
  button is released with an explicit retry/state-refresh message instead of
  spinning indefinitely.
- Boundary:
  - frontend auto-load guard only;
  - explicit `刷新主链路`, Product Truth rerun, and Strategy generation paths can
    still run the formal Citation Decision view;
  - no backend, EvidenceAlignment, Candidate Builder, Benchmark, Gap, Strategy,
    Step 7, or Step 8 semantics changed.

## 2026-09-04 Phase E UX Hotfix: Stale Citation Decision Request Release

- Investigated a #19 follow-up where V1.1 evidence generation completed and the
  workflow correctly returned to evidence review, but clicking `加载待审核项`
  still appeared to spin.
- Real API checks showed the review path was healthy:

```text
GET /api/optimization/workflow/3/19/review-queue -> READY, 3 alignment groups, ~0.16s
GET /api/optimization/workflow/3/19/competitor-candidates -> [], ~0.11s
GET /api/optimization/workflow/3/19/status -> evidence_review 20/23, ~1.8s
```

- Root cause: a previously started heavy `citation-decision-v1` request could
  remain in flight after the workflow changed from `20/20` reviewed to `20/23`
  reviewed. Even though the evidence-review guard prevented new automatic loads,
  the stale request could keep `citationDecisionLoading` active and make the
  page look like the review loader was stuck.
- Change:
  - `loadCitationDecisionV1` now uses an AbortController and releases after 20
    seconds;
  - when `workflow/status` says `evidence_review` is incomplete, the frontend
    invalidates stale Citation Decision requests and clears
    `citationDecisionLoading`;
  - `加载待审核项` uses bounded GET requests for review queue and competitor
    candidates, so the modal loader cannot spin indefinitely on auxiliary
    endpoint stalls.
- Validation:
  - frontend `npm run build` passed with Node v18.20.8; Vite emitted only the
    existing large chunk warning;
  - `git diff --check` passed;
  - #19 real endpoints continued to report `20/23` reviewed and 3 pending
    alignment groups.
- Boundary:
  - frontend request cancellation/loading isolation only;
  - no backend, SourceClaim, EvidenceAlignment, Candidate Builder, Benchmark,
    Gap, Strategy, Step 7, or Step 8 semantics changed.

## 2026-09-04 Phase E UX Hotfix: #40 Current Strategy Display And Orphan Run Cleanup

- Investigated a #40 switch issue where the main-chain card showed:

```text
Step 7 = 无策略
Step 8 = 未创建 / 当前主链仍需先完成策略确认
```

- Real API/DB checks showed the frontend display was wrong:

```text
GET /api/optimization/workflow/3/40/status
strategy_step_status = PENDING_REVIEW
current_strategy_candidate_ids = [50]
evidence_package_id = 15
review_queue = READY
```

- Root causes:
  - the Step 7 card derived pending/confirmed strategy counts from locally
    loaded `strategyData.candidates`; when heavy current-chain requests failed
    or had not loaded yet, the card ignored the backend
    `current_strategy_candidate_ids` and fell through to `无策略`;
  - after a dev-server restart, orphaned `PromptAnalysisRun.status=RUNNING`
    rows remained in SQLite. The frontend then kept polling nonexistent #19
    background work, and because prompt overview refreshed on every
    `workflowData` change, those polls could stack enough requests to exhaust
    the local SQLAlchemy pool.
- Change:
  - Step 7 counts now trust `workflow/status` `current_strategy_candidate_ids`
    as the current-chain fallback, so #40 shows the current pending strategy
    even before the full strategy list finishes loading;
  - page-level automatic `citation-decision-v1` no longer runs when
    `workflow/status` already reports `PENDING_REVIEW`, `CONFIRMED`,
    `NO_STRATEGY`, `NEEDS_CURRENT_ANALYSIS`, `CURRENT_ANALYSIS_RUNNING`, or
    `CURRENT_ANALYSIS_FAILED`;
  - prompt overview no longer reloads on every workflow status update;
  - backend startup marks orphaned `PromptAnalysisRun.RUNNING` rows as `FAILED`
    with the existing restart-interruption message.
- Validation:
  - `geo-platform/backend/.venv/bin/python -m compileall geo-platform/backend/app`
    passed;
  - frontend `npm run build` passed with Node v18.20.8; Vite emitted only the
    existing large chunk warning;
  - `git diff --check` passed;
  - after restart, #40 status returned in ~0.84s with
    `strategy_step_status=PENDING_REVIEW` and candidate `#50`.
- Boundary:
  - status ownership and request scheduling only;
  - no SourceClaim, EvidenceAlignment, Candidate Builder, Benchmark, Gap,
    Strategy generation, Step 7 semantics, Step 8 semantics, or historical
    candidate eligibility rules changed.

## 2026-09-04 Phase E Step 7 Generation Spinner Root Cause

- Investigated a #19 Step 7 generation spinner after evidence review completed.
- Real API/DB checks showed two separate issues:
  - `generate-current-v1` still delegated to
    `confirm_citation_decision_vertical_slice()`, which rebuilt the full
    `citation-decision-v1` source analysis before creating StrategyCandidate
    rows;
  - `workflow/status` allowed `READY_TO_GENERATE` from legacy SUPPORTS review
    progress even when current formal V1.1 alignments existed but had
    `formal_v1_1_support_count=0`.
- Change:
  - added a lightweight current Step 7 strategy-row builder that consumes only
    the current Evidence Package run scope and already materialized
    EvidenceAlignment/SourceDocument state; it does not call
    `_source_analysis_for_package`;
  - `generate_current_step7_strategy_candidates()` now uses the lightweight
    Step 7 path instead of the full Citation Decision detail path;
  - `workflow/status` now exposes `current_v1_1_input_state` and only reports
    `READY_TO_GENERATE` when current formal V1.1 SUPPORTS exist;
  - frontend Step 7 generation failures refresh workflow status so stale
    `READY_TO_GENERATE` UI cannot keep reappearing after a fast 400.
- Real #19 state after the fix:
  - `formal_v1_1_alignment_count=408`;
  - `formal_v1_1_support_count=0`;
  - `legacy_support_count=484`;
  - `strategy_step_status=NO_STRATEGY`;
  - `execution_step_status=NO_EXPERIMENT`.
- Validation:
  - backend `pytest tests/test_workflow_review_queue.py tests/test_strategy_step7_v1.py -q`
    passed: 37 tests;
  - backend compileall for `workflow.py` and `service.py` passed;
  - frontend `npm run build` passed; Vite emitted only the existing large chunk
    warning;
  - `git diff --check` passed.
- Boundary:
  - no EvidenceAlignment execution, Candidate Builder, SourceClaim prompt,
    Benchmark, Gap, Strategy payload semantics, Step 8, or historical cleanup
    changed;
  - legacy SUPPORTS remain audit/history only and do not unlock current Step 7.

## 2026-09-04 Phase E Step 7 NO_STRATEGY Regression Fix

- Corrected the previous Step 7 interpretation: `formal_v1_1_support_count=0`
  is not, by itself, a terminal `NO_STRATEGY`.
- Real #19 checks showed current V1.1 formal SUPPORTS were blocked by Phase 2A
  lineage: the current runs cited `shangjiajia.com/4626.html`, while SUPPORTS
  evidence came from other source documents. That means there is no eligible
  Benchmark Evidence, but the answer still contains repeated decision reasons
  that match supported target Product Truth.
- Change:
  - current Step 7 strategy-row building now includes observed run-scope
    citation/retrieval documents as evidence-adoption context, instead of
    building the whole table only from eligible SUPPORTS;
  - when no source row yields a recommended action, Step 7 can generate an
    `ANSWER_DECISION_EVIDENCE_GAP` action from current answer decision reasons
    plus `SUPPORTED` Product Truth;
  - candidate eligibility now explicitly allows this action class to have
    `benchmark_evidence_ids=[]` only when it declares
    `NO_ELIGIBLE_BENCHMARK`, `EVIDENCE_GAP`, `proposed_direction=EVIDENCE`,
    and `product_truth_refs.status=TRUE`.
- Real validation:
  - #19 generated current StrategyCandidate `#52`;
  - `workflow/status` now resolves #19 as `strategy_step_status=PENDING_REVIEW`
    with `current_strategy_candidate_id=52`;
  - #40 remains `strategy_step_status=PENDING_REVIEW` with candidate `#50`.
- Boundary:
  - no EvidenceAlignment execution, SourceClaim prompt, Benchmark promotion,
    Step 8, historical cleanup, or Phase C/D behavior changed;
  - Citation Prominence still cannot decide Benchmark, and the fallback action
    carries no fake Benchmark evidence.

## 2026-09-04 Phase E Step 7 Evidence-Gap Guardrails

- Tightened `ANSWER_DECISION_EVIDENCE_GAP` so it cannot become a generic
  fallback whenever a normal Benchmark-backed action is unavailable.
- Generation now checks each current answer decision reason independently:
  - a matching eligible `SUPPORTS` removes that reason from this gap class;
  - a matching eligible `CONTRADICTS` also removes it, because an evidence
    conflict cannot be represented as a simple missing-evidence gap;
  - legacy/non-eligible relations remain audit history and do not trigger either
    branch.
- Candidate payloads now persist explicit provenance:
  `strategy_basis`, `decision_reason_ids`, `decision_reason_event_ids`,
  `evidence_gap_reason`, `eligible_support_count`, and
  `eligible_contradiction_ids`. `benchmark_evidence_ids` remains empty.
- Corrected the Candidate explanation so this gap class no longer claims to be
  based on Phase 2A eligible Benchmark Evidence.
- The Strategy review UI now displays four separate facts for this class:
  no Benchmark, observed answer decision reasons, confirmed target Product
  Truth, and missing eligible support evidence.
- Real #19 read-only validation:
  - eligible SUPPORTS = 0;
  - eligible CONTRADICTS = 0;
  - the 49 current-scope CONTRADICTS rows are legacy/non-eligible and do not
    block the evidence-gap candidate;
  - five current decision-reason identities match supported Product Truth.
- Final runtime closure:
  - #19 current StrategyCandidate is `#54` with
    `strategy_basis=ANSWER_DECISION_EVIDENCE_GAP`, five persisted decision
    reason IDs, `eligible_support_count=0`, and no eligible contradiction IDs;
  - intermediate candidates `#52` and `#53` are `DEFERRED/SUPERSEDED`, so they
    cannot remain parallel current Step 7 truths after the schema guard changed;
  - workflow status resolves only `#54` as current `PENDING_REVIEW`; Step 8 is
    still `LOCKED`, and no Action or Experiment was created;
  - focused backend tests, frontend production build, and localhost Playwright
    rendering all passed. The strategy review displays the evidence-gap basis,
    no-Benchmark state, Product Truth state, and Step 8 boundary separately.
- Data/schema impact: structured payload fields only; no database migration.
- Boundary: no EvidenceAlignment mutation, Benchmark promotion, Step 8 object,
  historical cleanup, or main-chain order change.

## 2026-09-04 Step 7 Channel Resolution PR1: URL Identity And Mapping Health

- Scope is PR1 only. No Channel Evidence Aggregation or Channel Resolver policy
  was changed, and no StrategyCandidate was generated, reviewed, or superseded.
- Added shared `canonicalize_url()` with `url_identity.v1`, deterministic
  canonical URL hash, stable sorting/removal of tracking parameters, and an
  explicit idempotency contract. Wenxin collection, source acquisition, formal
  evidence URL lookup, ranking URL grouping, and lightweight Step 7 mapping now
  delegate to the shared identity instead of maintaining separate rules.
- Added `canonical_url_hash` and `canonicalization_version` to
  `ReferenceSource`, `RetrievalCandidate`, and `SourceDocument`. Raw observed
  URLs remain in the existing `url` / `original_url` fields.
- Replaced the invalid `normalized URL IN raw SourceDocument URL` query with a
  staged mapper:
  same-version canonical hash, raw URL exact, current-rule legacy
  recanonicalization, optional redirect outcome, then explicit unmapped
  outcomes. The mapper only returns documents matched to the current package
  Run Scope; it does not admit unrelated historical documents.
- Added structured `MappingCoverageReport`, per-URL `SourceMappingOutcome`,
  retry/manual-review metadata, conservation, and `DataHealthState`. The
  read-only endpoint is
  `/api/optimization/workflow/{project_id}/{prompt_id}/source-mapping-health`.
- Required implementation constraints:
  1. Strategy opportunity existence is independent from channel resolution.
  2. Broken mapping is `INPUT_INVALID` data health, not absence of channel
     evidence.
  3. An observed citation platform is not automatically a recommended channel.
  4. Every future PRIMARY channel, including official site, needs a current
     Decision Reason intervention rationale.
  5. Insufficient healthy channel evidence must eventually resolve to
     `UNRESOLVED`, never default official site. Items 3-5 are PR2/PR3 gates and
     were not implemented as resolver changes in PR1.
- Real current-package results after deterministic identity backfill:
  - #19 package #12: 1,207 reference records, 203 observed unique URLs,
    203 mapped, 0 unmapped, 100% coverage, 204 citation/retrieval input
    documents, `HEALTHY`; outcomes = 55 exact + 148 canonical.
  - #40 package #15: 174 reference records, 29 observed unique URLs, 29 mapped,
    0 unmapped, 100% coverage, 31 citation/retrieval input documents,
    `HEALTHY`; outcomes = 11 exact + 18 canonical.
  - Both reports conserve `total = mapped + unmapped`; neither requires manual
    review.
- Current-chain boundary after PR1: #19 candidate #54 and #40 candidate #50 are
  unchanged. #54 remains unfit for confirmation because its channel decision
  predates repaired mapping; superseding/regenerating it belongs to PR3.
- Validation:
  - 128 focused URL identity, mapping, ranking, source qualification, passage
    retrieval, evidence lineage, incremental planner, Step 7, and workflow tests
    passed;
  - `compileall app` and `git diff --check` passed;
  - the full backend suite currently has 5 independently reproducible failures
    outside PR1: two stale batch-delete contract assertions, one Wenxin
    conversation-reset assertion, and two legacy Step 8 fixtures rejected by
    current V1.1 candidate eligibility. These were not changed under PR1.

## 2026-09-04 Step 7 Channel Resolution PR2: Channel Evidence Landscape

- Scope is PR2 only. Added the read-only endpoint
  `/api/optimization/workflow/{project_id}/{prompt_id}/channel-evidence-landscape`;
  no Channel Resolver, `planned_channels`, StrategyCandidate, Step 7/8 state,
  Benchmark, Gap, Product Truth, or EvidenceAlignment verdict semantics changed.
- The endpoint returns aggregate provenance by default. Per-observation audit
  rows are opt-in with `include_observations=true`, preventing #19's 2,061
  Citation/Retrieval-only observations from turning ordinary reads into another
  heavy diagnostic request.
- Citation observations are deduplicated by `Run + canonical URL`, while raw
  parser rows remain visible. Citation roles are mutually exclusive with
  priority `DECISION_CITATION > ANSWER_SUPPORT_CITATION > PERIPHERAL_CITATION`.
  `RETRIEVAL_ONLY` is counted separately and requires no same-Run Citation.
- Semantic evidence is derived only from existing formal V1.1
  `eligible_evidence_alignments_for_v1()` SUPPORTS. No Citation Role judge,
  prompt, confidence, or external LLM call was added. Every role carries its
  basis and typed source IDs; semantic relation count deduplicates by current
  semantic Decision Reason plus semantic SourceClaim, not row count.
- Decision-Reason drilldown is joined by existing `decision_binding_id` /
  `answer_unit_id`, not loose text matching. Peripheral and Retrieval-only
  observations are intentionally not attributed to a Decision Reason without
  an exact eligible relation.
- URL-to-document membership is reported independently from evidence counts:
  - #19 has 203 unique reference URLs, 207 URL-document memberships, and 204
    unique reference documents. Four URLs map to two distinct content
    snapshots each; canonical/raw URL variants also share document identities,
    so memberships are not evidence observations.
  - #40 has no 1:N reference mapping: all 29 reference URLs map one-to-one to
    29 reference documents. The previously reported 31 aggregation documents
    are 29 reference documents plus two additional retrieval-only documents.
- Real #19 package #12:
  - 40 Runs, 1,207 raw reference rows, 1,207 unique Citation observations,
    203 unique URLs, 899 retrieval rows, and 854 Retrieval-only observations;
  - Citation conservation is `1,207 = 0 Decision + 0 Answer Support + 1,207
    Peripheral`; AggregationHealth is `HEALTHY`;
  - 192 formal SUPPORTS candidates are all excluded by the existing Phase 2A
    rule `SOURCE_NOT_REFERENCED_IN_RUN`, so no channel currently enters the
    formal Decision Layer. This is reported, not repaired or relaxed by PR2;
  - major observed channels: B站 251 Peripheral; 知乎 207 Peripheral + 9
    Retrieval-only; 百家号 285 Peripheral + 424 Retrieval-only; 商加加 74
    Peripheral; 抖音 118 Peripheral; 搜狐 53 Peripheral + 14 Retrieval-only;
    官网 5 Peripheral + 34 Retrieval-only.
- Real #40 package #15:
  - 6 Runs, 174 Citation observations, 29 unique reference URLs, 258 retrieval
    observations, and 228 Retrieval-only observations;
  - Citation conservation is `174 = 6 Decision + 0 Answer Support + 168
    Peripheral`; AggregationHealth is `HEALTHY`;
  - 知乎 keeps six Decision Citation observations across 6/6 Runs, one unique
    URL, and six semantic relations. The reason-level split is two relations
    for click statistics, one for custom sharing title, and three for marketing
    use. Existing #40 channel evidence therefore remains present.
- Entity dimensions reuse existing project brand aliases, Competitor records,
  RecommendationEvent entities, and source ownership. No BrandNormalizer or
  alias registry was introduced. URL-less retrieval rows whose `domain` field
  is actually an author/source label remain `UNKNOWN` instead of becoming a
  fabricated channel.
- Validation:
  - 9 PR2 tests cover row explosion, 1:N mapping, role precedence,
    Retrieval-only, Prompt/Reason isolation, read-only Strategy behavior, and
    six-Run regression stability;
  - PR2 + mapping tests: 19 passed; Step 7/EvidenceAlignment/Workflow focused
    regression: 69 passed; full backend: 370 passed with the same five
    pre-existing unrelated failures and no PR2 failure;
  - `compileall app`, `git diff --check`, and real FastAPI HTTP response passed.
- Frozen boundary after PR2: #19 candidate #54 and #40 candidate #50 remain
  unchanged. Observed Channel is not Recommended Channel; PR3 has not started.

## 2026-09-04 Step 7 Channel Resolution PR3-A: Resolver Shadow

- Scope is Shadow only. The production `_resolve_strategy_channels()` path,
  StrategyCandidate persistence, workflow state, Step 8, Action, and Experiment
  execution were not changed. Candidate #54 was not superseded.
- Reused the frozen PR1 URL mapping, PR2 Channel Evidence Landscape, current
  lightweight Step 7 action/candidate payload, Product Truth, Relevant Asset,
  and eligible Benchmark inputs. Added one read-only resolver implementation
  and endpoint:
  `/api/optimization/workflow/{project_id}/{prompt_id}/channel-resolution-shadow`.
- The resolver separates three orthogonal states:
  `StrategyOpportunityState`, `ChannelResolutionState`, and
  `ExecutionReadiness`. It also emits `InterventionMode` without creating any
  execution object.
- Evidence-backed channels can only come from:
  `OBSERVED_DECISION_CHANNEL`, `BENCHMARK_INTERVENTION_PATTERN`, or
  `AUTHORITATIVE_PRODUCT_TRUTH_INTERVENTION`. There is no default-official path
  in the Shadow resolver. An official PRIMARY must carry concrete
  `authority_asset_evidence`, Decision Reason IDs, and Product Truth refs.
- Added opportunity-backed `RETRIEVAL_EXPOSURE_OPPORTUNITY` for `TEST` only.
  It independently requires Exposure, reason-level relevance, Target Gap, and
  Intervention Fit. Citation/SourceClaim text is used only for deterministic
  relevance diagnosis; excluded/non-eligible SourceClaims are never promoted
  to Decision Citation, Answer Support, or Benchmark.
- Path D uses the existing Chinese bigram tokenizer and explicit PASS/WEAK/FAIL
  conditions, not a weighted channel score. High Peripheral volume alone can
  only produce OBSERVE. Competitor first-party domains cannot become executable
  target-brand TEST channels.
- Real #19 package #12 Shadow:
  - Strategy Opportunity `PENDING_REVIEW`, Data Health `HEALTHY`;
  - PRIMARY = `OFFICIAL_SITE` through Path C with
    `MISSING_BUT_REQUIRED_ASSET`, five Decision Reason IDs, and Product Truth
    #1/#2/#3; this is an explicit authority intervention rationale, not the old
    empty-signal fallback;
  - TEST = `BAIJIAHAO`, `BILIBILI`, `ZHIHU`, `SOHU`; each has sustained
    Exposure, at least one reason-level strong relevance signal, a target-brand
    Decision/Support gap, and an executable content hypothesis;
  - `DOUYIN` and `CSDN` remain OBSERVE because current reason relevance is only
    WEAK; `COMPETITOR_SHANGJIAJIA_COM` remains OBSERVE despite strong relevance
    because Intervention Fit is invalid for a target-brand action;
  - Channel Resolution `RESOLVED`, Execution Readiness `NOT_READY` because the
    Strategy Opportunity is not yet confirmed;
  - old #54 and the Shadow both name official site PRIMARY, but the rationale
    changed from `FIRST_PARTY_EVIDENCE_STRENGTHENING` fallback-shaped output to
    audited Path C. #54 still requires superseding at Cutover with
    `CHANNEL_RESOLUTION_INVALID_DUE_TO_SOURCE_MAPPING_FAILURE`.
- Real #40 package #15 Shadow:
  - PRIMARY = `OFFICIAL_SITE` via Path C and SECONDARY = `ZHIHU` via both Path A
    and Path B;
  - the six Zhihu Decision Citations across 6/6 Runs remain formal evidence and
    are not downgraded to TEST;
  - no additional TEST is emitted once a current observed Decision/Benchmark
    path exists; old channel assignments are unchanged and the rationale-path
    change is explicit;
  - Strategy Opportunity remains `PENDING_REVIEW`, so Execution Readiness is
    `NOT_READY`.
- Added an eight-case Golden Replay covering official/third-party Benchmark
  resolution, evidence-backed answer gaps, TEST, OBSERVE-only, UNRESOLVED,
  INPUT_INVALID, and Product Truth UNKNOWN. Added 11 targeted tests for the
  role, readiness, and authority gates.
- Validation:
  - PR3-A + PR2 + Step 7 focused regression: 41 passed;
  - full backend: 381 passed with the same five pre-existing unrelated failures
    (two batch-delete contracts, one Wenxin reset expectation, two legacy Step 8
    fixtures);
  - real #19/#40 read-only audits preserved candidate ID sets exactly;
  - External LLM calls = 0; frontend was not touched.
- PR3-A stops here. No Cutover, candidate regeneration, Action/Experiment
  creation, or TEST-to-Step-8 integration was performed.

## 2026-09-05 Step 7 Channel Resolution PR3-B: Production Cutover

- Added the two required semantic guards before Cutover:
  - Path C now evaluates every Decision Reason independently. Each row stores
    its directly linked confirmed Product Truth refs, authority asset status/ref,
    authority rationale, and eligibility. One Reason cannot borrow another
    Reason's Product Truth.
  - Path D TEST rows persist only the Reasons that actually pass relevance,
    plus exposure signals, reason relevance, target gap, intervention fit,
    `why_test`, and `why_not_primary`.
- Split intervention state into `proposed_intervention_mode` and
  `active_intervention_mode`. A `PENDING_REVIEW` StrategyCandidate may propose
  `CONFIRMED_CHANNEL_INTERVENTION`, but active mode remains null while
  `ExecutionReadiness=NOT_READY`.
- The current Single Prompt `generate-current-v1` path now explicitly enables
  the PR3 resolver. Shadow and production call the same deterministic
  `resolve_channel_shadow()` core. `use_strategy_channel_resolver_v1_1=true`
  is the default rollback flag; false routes to the frozen legacy resolver.
  The legacy `confirm-citation-decision` compatibility endpoint keeps the
  frozen resolver and is not part of this Cutover.
- Production persistence keeps only PRIMARY/SECONDARY/TEST in
  `planned_channels`, while the full resolver output, including OBSERVE, is
  retained in `channels`. This preserves auditability without rendering 43
  low-value OBSERVE rows in the main strategy review panel.
- Real #19 Cutover:
  - #54 was preserved as `DEFERRED` with immutable supersede semantic/reason
    `SUPERSEDED / CHANNEL_RESOLUTION_INVALID_DUE_TO_SOURCE_MAPPING_FAILURE`;
  - an initial migration candidate #55 exposed an incomplete frozen-action
    reconstruction and was retained as superseded history;
  - the reconstruction was corrected to preserve evidence-gap reason,
    Citation Decision summary, no-Benchmark source marker, contradiction IDs,
    and channel aggregation; current candidate #56 then passed the existing
    V1.1 eligibility Gate as `PENDING_REVIEW`;
  - #56 resolves OFFICIAL_SITE PRIMARY by reason-level Path C and BAIJIAHAO,
    BILIBILI, ZHIHU, SOHU TEST by reason-level Path D; 43 remaining channels are
    OBSERVE. `ExecutionReadiness=NOT_READY`, active mode is null, and no Action
    or Experiment was created. Step 8 remains LOCKED.
- Real #40 was read-only: current candidate remains #50; PRIMARY OFFICIAL_SITE,
  SECONDARY ZHIHU, TEST none. Role-level old/new semantic diff is zero.
- Production-vs-Shadow role/path diff is zero for #19 and #40. External LLM
  calls were zero.
- Validation:
  - focused PR3/Step 7/Step 8 regression: 93 passed;
  - full backend: 384 passed with the same five pre-existing unrelated failures
    and no PR3-B failure;
  - `compileall app` and `git diff --check` passed; frontend was not changed.
- Operational finding: invoking the ordinary #19 current-generation HTTP
  endpoint before the Cutover migration still spent over 120 seconds in the
  pre-resolver Step 7 source-row reconstruction. The request was terminated
  before any DB write, and the Cutover reused #54's frozen action through the
  same production StrategyCandidate service. This is a known pre-resolver
  performance risk, not an LLM or Channel Resolver delay.
- PR3-B stops here. Candidate #56 is not auto-confirmed; PR3-C, Action,
  Experiment, and TEST-to-CHANNEL_VALIDATION_EXPERIMENT integration did not run.

## 2026-09-07 PR4-A Constraint-First Strategy Synthesis Shadow

- Added the read-only `strategy_synthesis_shadow.py` layer and
  `/api/optimization/workflow/{project_id}/{prompt_id}/strategy-synthesis-shadow`.
  It consumes only the current StrategyCandidate payload and scoped database
  objects; it does not rebuild Citation Decision, EvidenceAlignment, Gap, or
  Channel Resolution.
- Implemented `STRATEGY_SYNTHESIS_V1` as a closed-world contract. Stable reason,
  Product Truth, Gap, Source, Signal, Metric, and candidate-scoped Channel
  Resolution IDs form the only allowed object set.
- Added deterministic Reason compatibility constraints over capability family,
  scenario, intervention mechanism, and required asset type. A multi-reason
  Theme must be a clique in the allowed merge graph. `KEEP_SEPARATE` is a first
  class result.
- Separated frozen Resolver role from execution priority. TEST P1 eligibility
  uses explicit Exposure, reason coverage, target gap, intervention fit,
  measurability, and information-value Gates; no weighted score is used and the
  minimum portfolio budget is at most two priority tests.
- Added strict Structural, Provenance, Business Rule, and Unsupported Claim
  validators. Unknown fields are rejected, so a model cannot hide a new Product
  Truth, asset, channel, role, metric, or free fact in an otherwise plausible
  JSON object. Structural failure never falls back to free-form strategy text.
- Added optional versioned DeepSeek adapters for structural synthesis and
  presentation. `use_llm=false` is the Shadow default; model failure leaves the
  deterministic source objects available and returns a failed synthesis rather
  than failing Strategy Opportunity.
- Real deterministic replay:
  - #19/#56: five atomic reasons became three Themes; denominator is 15,
    reason coverages are 12/15, 12/15, 1/15, 1/15, 1/15; OFFICIAL_SITE remains
    PRIMARY; BAIJIAHAO/ZHIHU are TEST P1; BILIBILI/SOHU remain TEST and are
    deferred; 43 channels remain OBSERVE.
  - #40/#50: three AnswerUnit reasons remain separate 6/6 Themes;
    OFFICIAL_SITE remains PRIMARY and ZHIHU remains SECONDARY. Benchmark-backed
    semantics are unchanged.
- Both replays passed all four validators with zero new facts, unknown source
  IDs, role mutations, new channels/assets, or unsupported causal claims.
  Candidate hashes and project object counts remained unchanged; no Candidate,
  Action, or Experiment was created.
- Validation: 12 PR4 Golden/guard tests passed; combined PR4 + PR3 Resolver +
  Step 7 regression is 47 passed; full backend is 396 passed with the same five
  pre-existing unrelated failures (two batch-delete contracts, one Wenxin reset
  expectation, and two legacy Step 8 fixtures); compileall passed. No migration
  or frontend change was required.
- A real external DeepSeek replay was attempted inside the managed environment
  but blocked before data transmission because this turn did not contain
  explicit authorization to send #19 strategy objects to the external service.
  Do not record external LLM Hallucination Audit as passed.
- PR4-A stops at Shadow. #56/#50 were not superseded or edited; Step 8 remains
  untouched and no Cutover was performed.

## 2026-09-07 PR4-A.1 LLM Safety Acceptance & Deterministic-First Synthesis

- Upgraded the Shadow contract to `strategy_synthesis.v1.1` and made
  `DETERMINISTIC_FIRST_LLM_ONLY_WHEN_NECESSARY` executable. Reason identity,
  Run coverage, Theme coverage/title, frozen channel role, eligibility, metric
  selection, and uniquely determined Theme/TEST/portfolio decisions are now
  completed without LLM calls.
- Removed the callable whole-Strategy structural prompt. The only external
  structural path now consumes one explicit `AMBIGUOUS_THEME_GROUPING` or
  `AMBIGUOUS_TEST_PRIORITY` object with the minimum relevant Reasons/channels
  and a closed allowed ID/option set. Inputs no longer include all channels,
  references, Product Truths, or the full Strategy payload.
- Added strict bounded-response validation and fail-closed application. Unknown
  IDs/channels, illegal partition/selection, duplicate keys, extra fields, and
  contradictory `NEEDS_HUMAN` selections reject the entire proposal. No field
  is repaired and reused. Invalid/timeout results preserve the deterministic
  baseline and never fail the underlying Strategy Opportunity.
- Added `ThemeCoverageValidator`: each Theme stores and validates the exact
  member-Reason Run-ID union, count, and ratio. Added `ThemeTitleValidator`:
  titles use deterministic capability-family labels and cannot introduce new
  qualifiers. Presentation remains deterministic unless a future explicit
  ambiguity contract exists; causal, unsupported capability/asset/numeric,
  unknown-source, schema, or wording drift falls back to the deterministic
  reference.
- Real read-only DB replay:
  - #19/#56 and #40/#50 both detected zero structural ambiguities;
  - calling the endpoint with `use_llm=true` returned
    `SKIPPED_NOT_NECESSARY`, external LLM calls 0;
  - #19 Theme unions are T1 `[73, 173..184] = 13/15` and T2
    `[74, 173..184] = 13/15`; #40's three Themes remain 6/6;
  - all six validators passed, Resolver roles/Benchmark/strategy basis and
    Candidate hashes stayed unchanged, and Candidate/Action/Experiment writes
    were all zero.
- Synthetic-only real DeepSeek replay used one non-sensitive three-TEST
  ambiguity. DeepSeek returned parseable JSON but combined `NEEDS_HUMAN` with
  three selected channel keys. The semantic schema rejected the whole output;
  external calls=1, deterministic fallback preserved=true, final structure
  valid=true. No #19/#40 data was sent externally.
- Validation: 30 PR4-A.1 tests passed; PR4 + PR3 Resolver + Step 7 regression
  65 passed; full backend 414 passed with the same five pre-existing unrelated
  failures; `compileall app` and `git diff --check` passed.
- PR4-A.1 remains Shadow-only. #56/#50 were not edited or superseded, no
  Strategy was confirmed, Step 8 stayed locked, and Cutover was not started.

## 2026-09-07 PR4-B Constraint-First Strategy Synthesis Production Cutover

- Extracted one shared `run_strategy_synthesis_core()` for Shadow and
  Production. Production now builds the grounded context, runs deterministic
  synthesis, and passes Structural, Provenance, Business Rule, Theme Coverage,
  Theme Title, and Unsupported Claim validators before it can supersede or
  persist a current Candidate.
- Added production flags with defaults `use_constraint_first_strategy_synthesis_v1=true`
  and `allow_external_llm_strategy_synthesis=false`. An unambiguous Strategy
  therefore uses deterministic synthesis and presentation with zero external
  calls; unresolved ambiguity preserves the Strategy truth and records a human
  requirement instead of returning no strategy.
- Formal Candidate payloads now persist the synthesis contract, mode, stable
  input IDs/hash, output hash, validator results, atomic Decision Reasons,
  Intervention Themes, portfolio, and separate Decision/Audit views. Prompt and
  model versions are stored only when an external synthesis call actually ran.
- The write order is fail-closed: all synthesis payloads are prepared and
  validated before any old current Candidate is superseded. A rejected result
  leaves the previous current Candidate and its payload unchanged.
- Real #19 Cutover reused the already-frozen #56 grounded payload to avoid the
  unrelated heavy Step 7 source-row reconstruction. #56 remains immutable and
  is now `DEFERRED` with reason
  `SUPERSEDED_BY_VALIDATED_STRATEGY_SYNTHESIS_V1`; #57 is the new
  `PENDING_REVIEW` current Candidate.
- #57 contains five atomic Reasons and three Themes with coverage 13/15,
  13/15, and 1/15. OFFICIAL_SITE is PRIMARY; BAIJIAHAO/ZHIHU are priority TEST;
  BILIBILI/SOHU are deferred TEST; 43 channels remain OBSERVE. Production and
  Shadow output hashes match exactly and all six validators are VALID.
- #40 remained on #50. Read-only shared-core replay preserved three 6/6 Themes,
  OFFICIAL_SITE PRIMARY, ZHIHU SECONDARY, no TEST, Benchmark-backed semantics,
  and zero external calls.
- No Strategy was auto-confirmed. #57 has no Experiment or experiment plan;
  workflow API reports Step 7 `PENDING_REVIEW` and Step 8 `LOCKED`.
- Validation: 57 focused PR4/Step 7 tests passed; full backend 420 passed with
  the same five pre-existing failures and no new failure. `compileall` and
  `git diff --check` passed; frontend was not changed.
- Operational note: a read-only #19 current-action rebuild was stopped after
  more than three minutes in Evidence lineage URL matching before any write.
  PR4-B did not expand scope to fix that known pre-synthesis performance risk.

## 2026-09-07 PR4-B.1 Strategy Decision View Production Cutover

- Traced the final Strategy page to the strategy-candidate list API and
  `strategyData.candidates`. Although #57 already exposed valid PR4 Decision
  and Audit objects, `App.tsx` unconditionally rendered the legacy effective /
  structured payload through `strategyDisplayPayload()`.
- Extended the existing StrategyCandidate response with an explicit
  `strategy_view_mode`. A candidate with `STRATEGY_SYNTHESIS_V1` and all six
  valid synthesis validators returns `SYNTHESIS_DECISION_VIEW`; invalid or
  historical candidates remain `LEGACY`.
- Added a backend product-view adapter. It exposes validated Themes, Theme
  coverage labels, the frozen portfolio split, channel business rationale,
  related Themes/Reasons, success metrics, and a product-language OBSERVE
  summary. Resolver internals, rationale paths, source IDs, and strategy basis
  remain available only through the separate Audit View.
- Candidate #50 has no persisted PR4 view and is intentionally immutable. Its
  list response therefore uses the shared deterministic core as a read-only
  compatibility projection. It performs no external LLM call and no DB write;
  #50 remains current with the same Benchmark-backed semantics.
- Replaced the valid-synthesis main review body with a pure frontend view of
  the API response. It no longer groups Reasons, calculates coverage, ranks
  channels, or mixes legacy fields with the PR4 main view. Legacy rendering is
  retained only as the invalid/missing-synthesis fallback.
- Real API and browser verification passed. #19/#57 shows three Themes
  (13/15, 13/15, 1/15), OFFICIAL_SITE PRIMARY, BAIJIAHAO/ZHIHU priority TEST,
  BILIBILI/SOHU deferred TEST, and 43 folded OBSERVE channels. #40/#50 shows
  three 6/6 Themes, OFFICIAL_SITE PRIMARY, ZHIHU SECONDARY, and no TEST.
- Validation: 59 focused PR4/Step 7 tests passed; full backend reached 422
  passed with the same five pre-existing unrelated failures; frontend TypeScript/Vite
  build, `compileall`, and `git diff --check` passed. Localhost Playwright
  assertions and screenshots passed for #19 and #40. Candidate #57/#50 payload
  hashes remained unchanged and external LLM calls were zero.
- No Candidate, Action, Experiment, or Step 8 object was created or modified.

## 2026-09-07 Step 8 Configuration Entry No-op Fix

- Reproduced the confirmed #19/#57 state against the real API: Step 7 is
  `CONFIRMED`, Step 8 is `READY_TO_CREATE`, while Candidate #57 has no
  `action_id` or `experiment_id`. The frontend button only searched for an
  already-created draft; when neither ID existed it displayed a transient
  message and returned, so the advertised configuration action was a no-op.
- Wired the existing official
  `POST /strategy-candidates/{id}/execution-plan` path into an explicit Step 8
  configuration modal. It collects the concrete channel, CREATE_NEW versus
  UPDATE_EXISTING asset operation, successful PageSnapshot when updating,
  title/URL/section/content structure, account/location, fixed Evidence
  Package baseline Run IDs, confirmation note, and the Draft-only boundary.
- The backend Strategy Decision View now exposes
  `execution_channel_options`, derived only from its validated PRIMARY,
  SECONDARY, and priority TEST portfolio. The frontend consumes this list
  directly and cannot promote deferred TEST/OBSERVE channels or recompute
  Resolver roles.
- Opening the modal is immediate; PageSnapshot loading runs independently so
  a slow asset request cannot make the button appear unresponsive. The modal
  does not submit automatically and clearly states that Step 7 Strategy Truth
  is immutable and publication is outside this action.
- Real localhost Playwright verification opened #19 Candidate #57 and clicked
  `进入第 8 步配置`. The modal rendered the backend-selected
  `官网 · 主干预 · P1`, all required fields, and the 40 fixed baseline Runs.
  The test intentionally did not submit. Candidate #57 remained unbound and
  Action/Experiment counts remained unchanged.
- Validation: 84 focused Step 7/8 tests passed, frontend TypeScript/Vite build
  passed, `compileall app` passed, and `git diff --check` passed.

## 2026-09-07 PR5-A Evidence-Constrained Execution Proposal Shadow

- Added an isolated deterministic compiler in
  `optimization/execution_proposal_shadow.py` and a read-only
  `GET /workflow/{project_id}/{prompt_id}/execution-proposal-shadow` endpoint.
  PR5-A reads confirmed effective Strategy structure, frozen Resolver roles,
  the Evidence Package, and confirmed Product Truth; it does not consume the
  frontend Decision View as planning truth.
- Added ephemeral `ExecutionInputSnapshot`, minimum consumed evidence
  projection, semantic `input_contract_hash`, execution constraints,
  independent Intervention Proposals, categorical managed-asset fit,
  `NewAssetSpec`, asset type/package candidates, Claim Usage Policy, canonical
  titles, provenance-backed sections/content blocks, metric eligibility, and
  the existing three-sample independent resampling plan. PageSnapshot is not
  treated as ManagedAsset and no asset table was added.
- Truth eligibility separates value from provenance. Current
  `SUPPORTED + MANUAL_CONFIRMED` rows are accepted; an empty external
  `source_reference` is legal. Since the schema has no approved aliases,
  factual titles and sections use exact `capability_label` wording only.
- Added eight independent validators for Snapshot, Channel Role, Asset Fit,
  Claim Grounding, Title Claim, Section Provenance, Baseline, and Metric
  Eligibility. Validator validity is separate from proposal readiness, so a
  safe proposal may correctly remain `NEEDS_HUMAN_SELECTION`.
- Real #19/#57 replay produced three independent active proposals:
  OFFICIAL_SITE PRIMARY, BAIJIAHAO TEST, and ZHIHU TEST. BILIBILI/SOHU remain
  deferred. Managed assets are zero, so all operations are `CREATE_NEW`.
  Official asset type (PRODUCT_PAGE / FEATURE_PAGE / HELP_DOC) and packaging
  remain human selections; each TEST is one minimal ARTICLE proposal scoped to
  Theme T1 and one future Action/Experiment identity.
- Package #12 v8's 40 baseline Runs remain separate from the 15 Strategy Runs.
  Existing brand metrics retain package baselines; new external asset-level
  retrieval/citation metrics are `NOT_MEASURABLE_YET`, not zero. No metric or
  observation-window preset was invented.
- Automatic encrypted short link, platform filing, whitelist, anti-blocking,
  and seven-day 95% effectiveness all remain forbidden target assertions.
  All eight validators passed and the safety audit reported zero unsupported
  target assertions, new facts/channels, role mutations, fake assets, invented
  metrics, baseline drift, ungrounded sections, or implicit unknown claims.
- #40/#50 runs through `READ_ONLY_COMPATIBILITY_PROJECTION`; OFFICIAL_SITE
  PRIMARY, ZHIHU SECONDARY, and `BENCHMARK_BACKED_STRATEGY` remain unchanged.
  Repeated #57 replay produced the same semantic input hash.
- Validation: 18 PR5-A tests (including A-O adversarial/golden cases) passed;
  77 focused PR4/Step 7/PR5 tests passed; full backend 440 passed with the same
  five pre-existing unrelated failures and no new failure. `compileall app`
  and `git diff --check` passed. Candidate #57/#50 hashes, Action/Experiment
  counts, Step 8 state, and external LLM calls all remained unchanged/zero.
- PR5-B/C/D, formal proposal persistence, ManagedAsset persistence, Action /
  Experiment creation, and Step 8 UI prefill were not started.

## 2026-09-07 PR5-A.2 Execution Proposal Quality Remediation

- Replaced minimal package rows with self-contained `AssetPackageCandidate`
  projections: explicit FULL/P1/minimum scope mode, included and excluded
  Themes, Reasons, Product Truth labels, one-asset count, eligible types,
  deterministic merge basis, structured tradeoffs, and selection implication.
  The #57 official FULL/P1 choice remains `NEEDS_HUMAN_SELECTION`.
- Replaced the fixed Section template with package-specific, purpose-specific
  synthesis. PRODUCT_TRUTH is one-truth scoped, SCENARIO consumes only planning
  context, BOUNDARY contains restricted/unknown policy, VALIDATION contains
  only package metrics/signals/baseline, FAQ excludes planning questions, and
  unsupported OPERATION is omitted. Content Blocks now exactly inherit Section
  provenance. An unresolved package exposes Section Plan candidates instead of
  a silently selected top-level plan.
- Added deterministic TEST `ChannelOpportunityProfile` and evidence-pattern
  hypotheses. Real #57 BAIJIAHAO is 40 reference / 16 retrieval / 2 claim / 11
  document with `EXISTING_RETRIEVAL_EXPOSURE`; ZHIHU is 40 / 0 / 1 / 6 with
  `REFERENCE_ENVIRONMENT_WITHOUT_RETRIEVAL`. Both retain T1 and two Reasons,
  ARTICLE, TEST role, and Path-D-only/non-primary boundaries.
- Added separate Asset Package and Channel Hypothesis quality checks plus the
  full seven-part `proposal_quality_audit`. Added quality tests for standalone
  packages, minimal Section provenance, FAQ/OPERATION boundaries, channel
  distinction, and generic-template rejection.
- Real #19/#57 and #40/#50 replay: all eight safety validators VALID and all
  seven quality checks PASS. #57 input hash remained
  `ac733bf1b2e20ff6a87708365487f3d3d4d9574d3d12a7d8cd70ad0fe4b90cfb`;
  baseline 40 Runs and Strategy coverage 15 Runs remained distinct. #40 kept
  its Benchmark-backed semantics and Resolver roles.
- Validation: 24 PR5-A tests passed; full backend reached 446 passed with the
  same five pre-existing unrelated failures. `compileall` and
  `git diff --check` passed. External LLM calls, DB writes, Candidate changes,
  Action/Experiment/ManagedAsset creation, and Step 8 modification were all 0.
- `PR5-A = FROZEN`. PR5-B was not started.

## 2026-09-07 PR5-B Human Review / Edit / Revalidation

- Added deterministic PR5-B overlay/rebuild functions to the PR5-A execution
  proposal module and two read-only POST APIs for single-proposal and portfolio
  revalidation. Source proposals are deep-copied; human edits never mutate the
  PR5-A baseline.
- Enforced backend immutable-field gates for Resolver Role, proposal type,
  Theme/Reason/Product Truth scope, claim policy, Evidence Package/baseline,
  metrics, strategy identity, and proposal merging. Illegal edits return
  structured reason codes and are never silently corrected.
- Canonical rebuild resolves only backend-provided package/type candidates,
  exact Product Truth title wording, package-specific provenance-backed
  sections, publishing metadata, and allowed observation windows. Every edit
  reruns all eight PR5-A validators and emits an ephemeral `human_edit_diff`.
- Replaced the old blank Step 8 creation form with proposal review cards. The
  UI now exposes official FULL/P1 tradeoffs, TEST evidence patterns, legal
  asset types, safe title, section controls, allowed/restricted claims,
  metric measurement levels, baseline, and audit details. Its primary action
  only revalidates; it cannot create Action/Experiment.
- Real #19/#57 API replay selected official P1 + FEATURE_PAGE and BAIJIAHAO
  execution while deferring ZHIHU. The portfolio reached
  `READY_FOR_CONFIRMATION`, every proposal passed 8/8 validators, all safety
  counters were zero, and Candidate/Action/Experiment state was unchanged.
- Validation: 32 focused tests passed, frontend production build passed,
  FastAPI real-data replay passed, and `git diff --check` passed. PR5-B is
  frozen; PR5-C was not started.
- Browser acceptance caught and fixed an Ant Design Segmented uncontrolled
  default: the first `execute` option looked selected while no boolean entered
  the overlay. The control now uses explicit `EXECUTE` / `DEFER` UI values and
  one boolean conversion point. The repeated real #57 UI flow reached
  `READY_FOR_CONFIRMATION` and did not display or create an Experiment draft.
- Full backend validation finished with 454 passed and the same five
  pre-existing unrelated failures. Desktop and 390px browser replays both
  completed the same real #57 portfolio flow successfully.

## 2026-09-08 Semantic Governance Phase 1

- Change classification: `IMPLEMENTATION_CHANGE` for repository governance only. The embedded Foundation/Citation proposal is separately classified `SEMANTIC_CHANGE`, remains `DRAFT + CANDIDATE + NOT_IMPLEMENTED`, and was not implemented.
- Added `docs/semantics/` with the domain model, 16 versioned Semantic Contracts, Golden Case registry, Definition Review checklist, Conflict Register, RFC template, first real RFC candidate, ADR placeholder, and immutable #19/#40 snapshot manifests.
- Updated workspace/project `AGENTS.md` and Documentation Governance so change authorization is distinct from durable truth; effective FROZEN Contract, RFC implementation authorization, Product Definition, Spec, and observed implementation now have explicit roles.
- Recorded maturity and implementation status independently. Initial registry: 15 `OBSERVED`, 1 `CANDIDATE`; 14 `PRODUCTION`, 1 `PARTIAL`, 1 `NOT_IMPLEMENTED`; no Contract was automatically FROZEN.
- Snapshot capture fixed #19 to Package `12@v8`, Candidate `57`, 40 explicit Runs and #40 to Package `15@v2`, Candidate `50`, 6 explicit Runs. Both bind local DB SHA-256 and reject latest-object substitution; #40's unavailable PR4 contract hashes remain `null` with a reason.
- Data impact: none. No production module, API, frontend, migration, database row, Candidate, Action, Experiment, Resolver, Strategy Synthesis, PR5-A/B, or Step 1-8 behavior changed.
- Validation: Ruby JSON parse and expected-assertion SHA-256 replay passed for both manifests; fixed package/version/hash and Run IDs matched `backend/geo_v0.db`; Contract maturity/status field counts matched; `git diff --check` passed. `jq` was unavailable, so Ruby provided JSON validation. Production tests were not rerun because this checkpoint changes documentation/governance only.
- Stop gate: PR5-C remains `SEMANTIC_RISK`; no Foundation/Citation implementation, production cutover, Contract freeze, CI gate, reviewer agent, or agent runtime was started.

## 2026-09-08 Foundation/Citation RFC Definition Review 001

- Performed the first independent Semantic Review under the Phase 1 process. Classification: `SEMANTIC_RISK`; review-only, with zero production code or database writes.
- Verified all 16 Contract approval triplets remain `null`; no historical PR freeze was imported as Semantic Freeze approval.
- Reviewed the DRAFT RFC against `SC-PT-001`, `SC-GAP-001`, `SC-CHANNEL-001`, `SC-STRATEGY-001`, history/scope contracts, the Definition Review checklist, current Resolver Path C, and immutable #19/#40 manifests.
- Result: `NEEDS_REVISION`, `Freeze Recommendation = NO`. Blocking gaps are independent object identity/source/state definitions, legal `Foundation REQUIRED + Citation PRIMARY NONE`, complete Citation eligibility, #40 proposed challenge, Foundation Step 8 prohibitions, UNKNOWN behavior, and historical/shadow lineage.
- Added only `docs/semantics/reviews/RFC-FOUNDATION-CITATION-SPLIT.review-001.md` and linked the result from `SEM-CONFLICT-001`. The RFC itself was not modified; no Shadow, Freeze, Cutover, PR5-C, or Agent Runtime was started.

## 2026-09-09 RFC-RUNTIME-001 Definition Freeze And Read-only Projection Spike

- Product Owner Definition Freeze changed `RFC-RUNTIME-001` and
  `SC-RUNTIME-001@0.1.0` from CANDIDATE to FROZEN while keeping
  `implementation_status=NOT_IMPLEMENTED` and all production cutover metadata
  empty. The durable approval is
  `docs/semantics/approvals/RFC-RUNTIME-001.definition-freeze.md`.
- Recorded Review-005's incorrect `source_ref_set_hash` ending in `d831` as
  `NON_SEMANTIC_REVIEW_PROMPT_TRANSCRIPTION_ERROR`; the RFC canonical bytes,
  Frozen vector and independent result ending in `a483` remain authoritative.
- Added an isolated `app/modules/runtime_projection` canonicalizer/projector,
  a read-only CLI, and focused tests. The projector accepts only fixed #19/#40
  Manifests, opens SQLite read-only with a write-denying authorizer, implements
  all 16 Frozen legacy selectors, and emits only `virtual:` identities.
- Real two-pass replay returned `SPIKE_PASS`. #19 matched 0 COMPLETE / 6
  PARTIAL / 9 UNSAFE / 1 UNAVAILABLE; #40 matched 0/7/8/1. Both Stage
  expectation diff counts were zero, current projection remained UNRESOLVED,
  and all formal missing manifests/reviews remained null.
- Added `SC-RUNTIME-001@0.1.0` to both real Golden Case registries with separate
  `runtime_frozen_expected` assertions, preserving the existing production
  `current_expected` assertions as a different concern.
- The three normative vectors matched exactly. #19 replay hash was
  `fa7cfc02...562f2a` twice; #40 was `e99ecfdc...1e3e57` twice. Latest
  substitutions, semantic inventions and DB writes were zero; database SHA-256
  remained `fb24d2...4900d3`.
- Validation: 8 focused tests passed, `compileall app` and `git diff --check`
  passed, and the standalone CLI completed against the fixed database. No API,
  frontend, schema, migration, production Runtime,
  Candidate, Action, Experiment or PR5 behavior changed. Stop gate: no Runtime
  Shadow implementation or production cutover was started.

## 2026-09-10 RFC-RUNTIME-001 Runtime Shadow Phase 1A Persistence Spine

- Implemented the Frozen Runtime persistence primitives in an isolated
  `app/modules/runtime_persistence` package: immutable Manifest and
  AnalysisContext roots; independent StageExecution and StageAttempt history;
  append-only exact-target Review decisions; explicit CurrentContextPointer and
  ContextStageSelection with event history; exact Stage input edges; and
  explicit invalidation/reactivation history with dependency-derived STALE.
- Added generation-fenced atomic Stage publication, single successful
  completion, zero-member successful output, optimistic CAS for Review,
  Current pointer, Stage selection and validity, plus SQLite triggers protecting
  immutable history even when repository methods are bypassed.
- Added Alembic revision `20260910_01`, but did not apply it to the real GEO
  database. The Runtime models deliberately use an isolated `RuntimeBase` and
  are not registered with production `Base`, preventing `init_db()` from
  silently creating Phase 1A tables.
- Validation: all Frozen canonical vectors matched; 16 persistence/projection
  tests passed; a single clean temporary revision and the full Alembic chain to
  head both passed; Runtime compileall and diff checks passed. The complete
  backend run was 470 passed / 5 pre-existing unrelated failures, each
  reproduced alone and left unchanged under the Phase 1A production-edit ban.
- #19/#40 projection expectation diff, latest substitution and semantic
  invention remained zero. Real DB SHA stayed
  `fb24d2f0...4900d3`, with zero writes and zero production call-sites.
- `SC-RUNTIME-001` implementation status is now `PARTIAL`: Persistence Spine is
  ready for owner review, but live Phase 1B capture, real migration, API,
  frontend, cutover, backfill and PR5-C were not started.

## 2026-09-10 RFC-RUNTIME-001 Runtime Shadow Phase 1B Stop Gate

- Audited the prospective Legacy capture boundaries without changing code or
  database state. The existing pipeline has observable commits, but it does not
  carry the exact formal Stage manifests and dependency edges required by the
  Frozen Runtime profile.
- Registered `SEM-CONFLICT-003`: `ANSWER_SEMANTIC` requires a closed-enum
  `member_kind`, but no literal registry exists, and Legacy successful-zero vs
  failed/unmaterialized Runs are not distinguishable from row absence.
- Registered `SEM-CONFLICT-004`: Frozen `BINDING` consumes an upstream
  AnswerUnit/Reason output, while Legacy creates AnswerUnits from AnswerClaims
  inside the Binding call itself. Capturing that as a prior upstream edge would
  be reconstruction, not prospective observation.
- #19 fixed Package 12 has 40 Runs, with RecommendationEvent / AnswerClaim /
  AnswerUnit / Binding populations spanning 37 / 12 / 12 / 12 Runs. #40 fixed
  Package 15 has 6 / 6 / 6 / 6, but count equality still does not establish an
  immutable upstream edge.
- Stop result:
  `BLOCKED_BY_FROZEN_STAGE_OUTPUT_AND_BINDING_LINEAGE_MAPPING_GAPS`. No Runtime
  call-site, migration, API, frontend or production behavior was changed;
  Runtime tables and Phase 1B writes in `geo_v0.db` remain zero.
- Validation: 16 Phase 1A persistence/projection tests passed; the standalone
  fixed #19/#40 replay remained `SPIKE_PASS`, all three normative vectors
  matched, both stage expectation diffs were zero, two-pass hashes were stable,
  and latest substitutions, semantic inventions and DB writes remained zero.
  Runtime compileall and `git diff --check` passed; the real DB SHA remained
  `fb24d2f0...4900d3`.

## 2026-09-10 RFC-RUNTIME-001 Semantic Mapping Gap Review

- Kept Phase 1B stopped and completed a code-first, read-only mapping audit for
  all 16 Frozen Stages. No Runtime capture hook, Legacy semantic change,
  migration, schema patch, backfill, API/frontend change or production write
  was made.
- Distinguished execution-time facts from post-hoc inference. Nine Stages have
  candidate outputs that could be captured with non-semantic instrumentation,
  but only `RUN_METRICS` is independent of the unresolved upstream chain.
- Confirmed Frozen contract gaps in Answer Semantic member/zero identity,
  AnswerUnit ownership across Answer Semantic and Binding, and the actual
  Qualification/Fetch order. Confirmed stronger Legacy ambiguities in
  project-wide Source Qualification, heuristic Product Truth binding,
  Prompt-level unbound Gap confirmation and implicit latest Candidate selection
  for Execution Proposal.
- Read-only #19/#40 SQL preserved the fixed 40/6 Run scopes and showed 13/1
  PromptAnalysisRun envelopes, 13/7 ShadowRun envelopes, cache-ledger
  observation unions and unbound Gap review state. Latest/current/post-hoc
  mappings were explicitly rejected.
- Decision:
  `BLOCKED_BY_LEGACY_SEMANTIC_AMBIGUITY`. A targeted RFC amendment is required
  but is not sufficient without separately authorized Legacy semantic fixes.
  Phase 1B, Phase 1C, Cutover and PR5-C remain stopped.
- Validation: the read-only projection remained `SPIKE_PASS`, all three
  normative vectors matched, #19/#40 stage expectation diffs stayed zero,
  latest substitution/semantic invention/DB writes stayed zero, and all 16
  Phase 1A persistence/projection tests passed. The production DB SHA-256
  remained `fb24d2f0...4900d3`.

## 2026-09-10 Single-Prompt Core V2 First Slice

- Added an isolated V2 control plane with stable analysis identity, immutable
  sampling-plan hash, exact BrowserMonitorTask ownership, atomic worker claim,
  explicit retry history and restart-to-`INTERRUPTED` recovery. It does not
  import the gated Runtime persistence spine or read V1 latest/current objects.
- Added write-once AnalysisContext persistence. Context creation waits for all
  planned Runs to terminate and requires at least one usable answer; the frozen
  payload includes the exact Run scope plus answer, reference, Retrieval,
  artifact metadata and failure details. Later live-row edits or new sampling
  do not change the returned frozen version.
- Added `/api/v2/single-prompt/analyses` create/read/retry endpoints and a
  separate `单问题分析 V2` page. The page restores only an explicit URL-bound
  analysis identity and renders backend status without Candidate/Package
  inference.
- Added an independent Alembic branch `20260910_v2`, avoiding dependency on
  the unauthorized Runtime migration artifact.
- Validation: 7 V2 tests passed; compileall, frontend build and diff check
  passed. Combined monitoring tests were 22 passed / 1 known collector failure.
  Current collector code cannot prove independent conversation reset and emits
  no Retrieval candidates, so real collection acceptance remains blocked and
  was not replaced with a mock PASS.
- Real control-plane smoke used new Prompt #44 and created Analysis
  `001da937-0baa-498a-a7e9-9d8801324fb3`, Task #52 and Run #259. One Wenxin
  sample completed in 24.379 seconds and froze
  `raw-v1:4213d19507cb840c` / Context
  `ctx-8e284b02-6d7b-45f1-931a-ff18bda92562`, containing a 1,902-character
  answer and 30 references. Exact duplicate create returned the same analysis
  and task; wrong-Prompt read and post-freeze retry both returned 409.
  Retrieval remained absent and sampling proof remained `UNKNOWN`, preserving
  the collector-contract blocker.
- Desktop and 390px mobile Playwright renders passed after removing V2's wait
  on legacy Workflow/Dashboard loads. Mobile body width was exactly 390px with
  no horizontal overflow; the data table scrolls within its own surface.
- Final closure added backend-authored warnings for unavailable independent
  session proof and Retrieval observations, plus SQLite write/delete guards on
  frozen AnalysisContext rows. The live #44 result exposes both warnings;
  focused V2 tests remain 7/7, frontend production build and compileall pass,
  and final desktop/mobile renders have no navigation-title overlap.

## 2026-09-11 Single-Prompt Core V2 Second Slice

- Added isolated DiagnosisExecution, immutable DiagnosisResultVersion,
  immutable SourceSnapshot and append-only DiagnosisReview persistence on the
  V2 migration branch. Diagnosis identity freezes raw Context, brand, empty or
  populated Truth set, and full pipeline config hashes; restart/retry and stale
  review CAS are explicit.
- Added a narrow V2 adapter around AnswerSemantic, SourceClaim, Alignment,
  deterministic passage recall and conservative Truth relation logic. It does
  not invoke V1 runners, scan latest Package/Candidate, carry historical review
  or write V1 business state.
- Citation output now preserves reference observation, anchor binding,
  candidate recall and alignment evaluation independently. Candidate sources
  are restricted to the Reason's own Run; fetch failure, non-recall, zero Claim,
  judge failure and not-authorized evaluation remain distinct.
- Added local-only immutable snapshot reuse with content/passages hash checks,
  explicit `REUSE_ONLY` and evidence `CACHE_ONLY` execution policies, and a
  deterministic challenge-page gate. DeepSeek V2 structured extraction uses
  explicit non-thinking mode and one HTTP attempt while legacy callers retain
  their defaults; generation controls participate in cache identity and actual
  external HTTP attempts/tokens are recorded.
- Authorized #44 replay created Diagnosis
  `296e1e1b-bf14-402d-89c1-bb963f1cdea9` and immutable Result
  `diag-v1:1449c44916fe5c55`: one external `deepseek-v4-flash` call, zero cache
  hits, 2,417 total tokens, four grounded recommendations/four Reasons, 30
  references/29 sources, eight locally recalled passages, zero external
  SourceClaim/Alignment calls, four empty-Truth `UNRESOLVED` relations and no
  human review. Retrieval, independent-session proof, unproven anchors, four
  prior fetch failures and evidence not evaluated remain visible limitations.
- The authorized replay performed no page fetch. It locally reused 25 success
  and four failure snapshots. A later read-only quality audit identified one
  reused CSDN security-verification page among the 25 technical successes; the
  immutable result was not rewritten or replayed, and the new challenge gate is
  covered for future executions.
- Validation: 59 focused V2/retrieval/SourceClaim/Alignment tests passed;
  compileall, V2 fresh migration, frontend production build and diff check
  passed. Three GETs produced no execution/result/snapshot/review mutation.
  Desktop and 390px mobile Playwright checks passed after fixing Ant Table's
  auto-layout row expansion. Strategy, Proposal, Action and Experiment remain
  out of scope.

## 2026-09-11 Single-Prompt Core V2 LLM Safety Patch

- Added V2-only strict Pydantic response contracts for AnswerSemantic,
  SourceClaim and Alignment. The shared DeepSeek client exposes a default-off
  `strict_json`/`response_validator` path and validates both cache recovery and
  new provider output before successful cache persistence; legacy V1 behavior
  remains opt-out and unchanged.
- Separated invalid structure, valid zero output, deterministic grounding
  failure and `SEMANTIC_REVIEW_REQUIRED`. Invalid `{}` no longer becomes zero
  events/claims or `NONE`; a schema-valid Answer whose events all fail span
  grounding is `FAILED_VALIDATION`, and a repeated failed Answer is attempted
  only once within the diagnosis execution.
- Made frozen answer/source spans the only fact-bearing text for V2 recall,
  Alignment and Truth matching. Normalized projections that add numeric or
  high-impact qualifiers, alter explicit scope, or lack a conservative lexical
  bridge remain visible but are not consumable. Model messages now mark all
  answer/page/pair material as untrusted data.
- Added a read-only current safety projection over immutable results. It
  preserves historical stats while publishing current blocked snapshot IDs,
  currently eligible snapshot IDs and an effective evidence-relation whitelist.
  The actual #44 projection remains result `diag-v1:1449c44916fe5c55`, reports
  25 historical technical successes, one blocked verification page and a
  maximum of 24 currently eligible sources; no ResultVersion or Review changed.
- Validation: 53 V2/DeepSeek contract tests passed, including Schema,
  Grounding, Semantic Projection and Recovery/Authority negatives; compileall
  and frontend production build passed. The broader SourceClaim/Alignment/V2
  regression set passed 90/90. The full backend suite remained at its known
  baseline of 521 passed / 5 unrelated failures (two batch-delete contracts,
  one Wenxin conversation-reset contract and two legacy Step 8 tests). Tests
  made no external LLM calls or real-data writes. Real provider injection
  resistance and real external SourceClaim/Alignment remain not verified.

## 2026-09-11 Single-Prompt Core V2 Third Slice

- Added a V2-only `StrategyInputProjection` and A/B/C
  `StrategyReadinessReport`. Unreviewed and reviewed-but-ineligible inputs
  return explicit blockers without creating empty StrategyCandidate rows.
- Added deterministic Foundation/channel separation, four-level direction
  handling, closed-world provenance validation, pure Theme grouping and Run-ID
  union coverage. No PRIMARY is required; Foundation cannot select a channel;
  UNPROVEN source support can form only a bounded TEST hypothesis.
- Added isolated strategy execution, immutable result versions and append-only
  reviews. Exact diagnosis/review/safety hashes are frozen; the producer returns
  its exact ID, priority edits create child versions, and stale inputs become
  view-only with HTTP 409 on writes.
- Added V2 GET/POST APIs and a strategy area on the existing V2 page. GET and
  refresh only read readiness/exact strategy identity; generation and review
  require explicit user actions and never enter Step 8.
- Real #44 read-only acceptance is class A: no review, Foundation UNKNOWN,
  zero qualified directions/candidates, 29 source snapshots, four grounded
  Reasons, zero eligible evidence relations, historical content-ready 25 and
  current blocked content 1/max eligible 24. No real #44 rows were changed.
- Validation: 63 combined V2 tests passed, including 12 third-slice strategy
  tests; 68 V1 Channel/Resolver/PR4 regressions also passed. Compileall, a fresh
  V2 migration through `20260911_v2_strategy`, frontend production build,
  desktop/narrow-page rendering and diff check passed. No external LLM call or
  page fetch was made.

## 2026-09-11 Single-Prompt Core V2 Fourth Slice

- Added isolated execution proposal, immutable proposal result, append-only
  confirmation and append-only publication record models plus migration
  `20260911_v2_execution`. SQLite migration and local `init_db` paths both add
  no-update/no-delete guards to result, confirmation and publication history.
- Added one V2-only deterministic compiler from an exact accepted StrategyResult
  direction. It freezes strategy/review/diagnosis identities, consumed Truth and
  limitations, and the exact AnalysisContext baseline after raw, sampling-plan and
  run-scope hash/manifest validation. It does not call V1 Step 8 runners or latest
  Package/Candidate/Truth lookup paths.
- Added CREATE_NEW-only asset briefs, approved title/Section candidates, separate
  PUBLIC_CONTENT and INTERNAL_CHECKLIST collections, safe edit/revalidation,
  immutable child versions and idempotent confirmation. Foundation publication
  surfaces leave strategy channel fields null; PARTIALLY_COVERS is internal only.
- Added USER_REPORTED publication registration and append-only revision history.
  Conformance is backend-derived and separated from publication fact; incomplete
  or unstructured content is NOT_EVALUABLE, scope deviations remain recorded, and
  no report can become SYSTEM_VERIFIED.
- Added V2 APIs and page controls for direction selection, skeleton generation,
  asset/surface choice, title and Section editing/reordering, confirmation,
  publication registration/revision and history display. GET/refresh does not
  compute or write.
- Real #44 read-only acceptance remains blocked before strategy: diagnosis review
  count 0 and strategy count 0, with no real proposal/confirmation/publication.
  Eleven isolated fourth-slice tests cover the positive chain; the combined V2
  and reused-kernel regression set passed 162 tests. A fresh database migrated
  through both current Alembic heads successfully, compileall/diff check and the
  frontend production build passed. Live #44 desktop and 390px read-only renders
  showed the precise review blocker without horizontal overflow or a proposal
  action. No external LLM call, page fetch, auto-publication, retest or V1 state
  mutation occurred.

## 2026-09-12 Single-Prompt Core V2 Fifth Slice

- Added a V2 frozen sampling adapter that creates exact BrowserMonitorTask/Run
  rows from the immutable RetestPlan, verifies each `original_query` hash and
  keeps the mutable V1 task-creation default unchanged. Retest failure recovery
  reuses planned Run IDs, preserves successful outputs and supports explicit
  finalization with recorded failures.
- Added RetestExecution and immutable ComparisonResultVersion persistence plus
  the `20260911_v2_retest` migration. The exact handoff freezes confirmation,
  selected publication revision, baseline AnalysisContext, Prompt, sampling
  plan, MeasurementIdentity and metric contract; no latest Strategy/Publication
  or current Project identity lookup is used.
- Added pure frozen-DTO Run-level measurement for brand mention, V2 semantic
  recommendation, target-brand official references and exact published URL
  references. Missing semantics/official identity/observation remains null;
  duplicate references cannot inflate Run hits. Baseline and Retest always use
  the same identity and contract.
- Added separate sampling and semantic-measurement authorization. DeepSeek
  `cache_only` is default-off for V1, revalidates V2 cache hits and rejects a miss
  before API-key/HTTP access. Comparison preserves planned, observed and
  unobservable conditions; explicit observed conflicts keep side values but
  suppress the delta.
- Added V2 APIs and page controls for exact publication selection, measurement
  identity confirmation, frozen plan creation, explicit sampling/retry/finalize,
  cache-only or explicitly authorized semantics, and descriptive comparison.
  GET/refresh/polling are read-only and the UI states that USER_REPORTED is not
  system verification or causal evidence.
- Real #44 read-only acceptance remains blocked with zero Strategy,
  ExecutionConfirmation and PublicationRecord rows, so no Retest was created.
  Combined V2/DeepSeek tests passed 87/87; focused fifth-slice/execution tests
  passed 24/24; a fresh database migrated through both heads, compileall and the
  frontend production build passed. V1 monitoring regression passed 15/16; the
  pre-existing Wenxin conversation-reset assertion remains failing and is not
  changed by this slice. The full backend suite passed 555 tests with seven
  existing out-of-scope failures: two batch-delete contract tests, one Wenxin
  reset test, two Legacy Step 8 tests and two Runtime Projection Spike tests.
  No external browser or LLM call occurred.

## 2026-09-14 Single-Prompt Core V2 Real E2E Baseline

- With explicit Baseline-only authorization, created Analysis
  `ecb4ff1a-fbc7-4aa4-93cc-ed8172ffa811`, Task 53 and exact planned Runs
  260/261/262 for Project 3 / Prompt 40 through the production V2 API.
- All three Runs submitted the frozen text `长链接缩短` and succeeded on their
  first attempt with 1,653/1,800/1,725 answer characters and 24/26/27 complete
  reference observations. The immutable result is
  `raw-v1:79ea2aca2cb58ca4`, Context
  `ctx-807c3737-2ee3-42d4-87a8-cb466755555f`.
- Captured HTML contains one current question node per Run and local collector
  conversation UUIDs differ. The collector nevertheless records
  `single_continuous`, `sampling_mode=UNKNOWN`; independent-session proof and
  Retrieval observation therefore remain unavailable and are not reported as
  successful independent/comparable sampling.
- Frozen references contain 77 observations / 35 canonical URL identities.
  No diagnosis, DeepSeek call, source fetch, Truth/review, Strategy, publication
  or Retest was started. The exact future authorization scope is recorded in
  `docs/SINGLE_PROMPT_CORE_V2_REAL_E2E_ACCEPTANCE.md`.

## 2026-09-14 Single-Prompt Core V2 Real E2E Answer Semantic

- With a separate Answer-Semantic-only authorization, submitted the exact
  frozen #40 Analysis/Context through the production V2 Diagnosis API. The
  immutable execution is `40cdde15-f4ba-4ce8-803e-7e04ddd44931` and its result
  is `diag-v1:8d44fcac42659f31`; all input and answer hashes matched before the
  request and no latest substitution was used.
- DeepSeek `deepseek-v4-flash` received one request for each Run, for exactly
  three external requests, zero cache hits and 10,163 provider-reported total
  tokens. Automatic retry was disabled. Provider-billed cost is not persisted
  and remains unknown.
- All three responses finished normally at the provider but failed the V2
  strict Schema gate. Non-empty `selection_criteria` used unsupported
  `criterion/criterion_scope/answer_span` fields instead of the admitted
  contract. The result records three `FAILED_SCHEMA` items, zero effective
  events/Reasons and zero Truth relations; failures were not rewritten as a
  valid empty semantic result.
- Evidence remained closed with `REUSE_ONLY + CACHE_ONLY`. All 35 sources are
  `FETCH_DISABLED`, with zero passages, SourceClaims, candidates or Alignment
  calls. No DiagnosisReview, Strategy or Retest was created and no Truth or
  frozen source input was modified.

## 2026-09-14 V2 Answer Semantic Contract Alignment Repair

- Replaced the mixed string/object `selection_criteria` protocol with one strict
  object array. `normalized_reason`, grounded `reason_span` and the literal
  `MARKET_CRITERION` scope are required; legacy aliases and unknown fields remain
  rejected rather than translated.
- Made the production Answer prompt embed the schema generated from
  `AnswerSemanticResponse`, with grounded non-empty and legal-zero examples.
  Prompt, Schema, admission, projection and Diagnosis contracts were versioned
  so incompatible cache results cannot reuse the new identity.
- Completed the criterion consumption path through grounding, conservative
  normalization, independent result persistence, API projection and V2 UI.
  Market criteria and unresolved strings cannot become brand Reasons, Truth or
  Evidence relations.
- Added a backend eligibility Gate that distinguishes all-failed, legal-zero and
  partial-success Answer sets. All-failed results are view-only; revision,
  review and Strategy creation are rejected before writes. The frozen #40
  ResultVersion now projects 0/3 admitted, 3/3 failed and the Strategy blocker
  `NO_CONSUMABLE_ANSWER_SEMANTIC_RESULT` without changing historical rows.
- Focused V2 Safety/Diagnosis/Strategy tests passed 69 tests; the broader V2 and
  DeepSeek-contract set passed 101; V1 Answer regressions passed 27. Backend
  compileall and the frontend production build passed. No external LLM,
  sampling, source fetch, Truth/Review/Strategy write or real replay occurred.

## 2026-09-14 V2 Answer Semantic Authorized Replay

- Preflight matched Project 3 / Prompt 40, immutable Context
  `ctx-807c3737-2ee3-42d4-87a8-cb466755555f`, Raw Result/hash and all three
  authorized Run answer hashes. The deployed contract was Prompt `safety.v2`,
  Schema `strict.v2`, admission v2 and `max_attempts=1`.
- Created Diagnosis `c48054e3-1f4a-4cb5-b21c-9d6f584af273` through the formal
  whole-Context API with source `REUSE_ONLY` and evidence LLM `CACHE_ONLY`.
  Three DeepSeek `deepseek-v4-flash` requests completed with zero cache hits,
  no retries and 12,714 total provider-reported tokens.
- Published immutable ResultVersion `diag-v1:5a9bf1bd51178074`. Run 260 admitted
  seven option events and one independent market criterion, with three events
  retained for semantic review. Runs 261/262 failed exact grounding because the
  returned span omitted an invisible source separator; neither response was
  partially consumed or rewritten as zero events.
- Evidence remained closed: zero source fetches, zero SourceClaim/Alignment
  calls and 35 reused failure snapshots. The old failed ResultVersion/hash is
  unchanged; Review, Strategy and Retest counts for the new execution remain
  zero, and Product Truth rows were not modified.

## 2026-09-14 V2 Answer Raw-Span Grounding Patch

- Inspected the frozen Run 261/262 answers and retained failure excerpts. Both
  first-event mismatches are exactly one omitted `U+200C ZERO WIDTH NON-JOINER`
  at local span index 6; no semantic or punctuation change exists in those
  inspected spans. Full failed responses were not retained, so no full-response
  recovery claim was made.
- Added V2-only `locate_v2_answer_span`: exact unique match first, then only a
  unique, contiguous, same-line U+200C matching view. It rejects ambiguity,
  cross-line concatenation, other control characters and text changes. Stored
  projection metadata contains model/raw span, offsets, raw SHA-256, raw line
  context and the exact rule/version.
- Advanced only affected contracts: admission v3, Answer projection
  `v3_grounded_raw_span`, grounding `u200c.v1`, Truth relation
  `v2_subject_aware`. Answer Prompt safety.v2 and Schema strict.v2 are unchanged.
- Cross-brand lexical matches now remain unconfirmed capability-fit suggestions:
  machine PARTIAL is retained for audit, current effective relation is
  UNRESOLVED, and downstream Strategy input uses the current projection.
- Split disabled/not-authorized source content from actual fetch failure. The
  fixed #40 read-only projection now reports 35 not fetched and zero actual
  fetch failures; the immutable historical ResultVersion was not rewritten.
- V2 test suite passed 111 tests; focused Safety/Diagnosis/Strategy/Execution
  suite passed 104. Backend compileall and frontend production build passed.
  No external LLM, browser sample, source fetch, real Diagnosis, Truth, Review
  or Strategy write occurred.

## 2026-09-15 V2 Answer Raw-Span Production Replay

- Revalidated the exact Project 3 / Prompt 40 Analysis, Context, Raw Result and
  Run 260/261/262 answer hashes, then created Diagnosis
  `bd154212-9291-42ab-8966-b981136e10f0` through the formal V2 whole-Context API.
- The execution froze Prompt `safety.v2`, Schema `strict.v2`, admission v3 and
  grounding `u200c.v1`; source policy was `REUSE_ONLY`, evidence policy was
  `CACHE_ONLY`, and external max attempts remained one.
- Published `diag-v1:dbbbd68addd737f9`. Run 260 passed current validation from
  one compatible cache hit; Runs 261/262 used two new DeepSeek requests and
  8,598 provider-reported tokens. Run 262 exercised the restricted U+200C rule.
- Answer admission is now 3/3 with zero failures: 22 option events and three
  independent market criteria. Thirteen events remain explicitly review-required
  because their scenario-list wording lacks an explicit option cue.
- Evidence remained closed: 35 sources not fetched, zero actual fetch failures,
  zero SourceClaim/Alignment external calls and zero evaluated relations. No
  Review, Truth mutation, Strategy, publication or Retest followed the replay;
  the prior immutable result remains unchanged.

## 2026-09-15 V2 Answer Event Review Visibility and Consumption Gate

- Fixed the V2 diagnosis page to read event-level
  `semantic_validation_status` instead of inferring review state only from each
  Reason. The 13 review-required #40 events now appear in a dedicated table with
  Run/Event identity, raw context, extracted Reasons, concrete review cause and
  four explicit dispositions; the nine conservative admissions remain separate.
- Diagnosis review now requires one explicit disposition for every review-held
  event. A reviewer may confirm the existing option act, save a correction to
  MENTION, keep it unresolved or exclude the extraction. Completing the whole
  review may preserve uncertainty, but cannot silently omit an event decision.
- Closed a V2 strategy handoff gap: event-held Reasons are no longer consumable
  merely because their nested Reason projection passed. Only an exact
  `CONFIRM_INCLUDE_AS_OPTION` review decision can make that event eligible; it
  does not upgrade the speech act, create Product Truth or establish evidence.
  Strategy input validation advanced to
  `single_prompt_strategy_input.v3_event_review_gate`.
- Focused Diagnosis/Strategy tests passed 41 tests and the frontend production
  build passed. Read-only production checks still show #40 ResultVersion
  `diag-v1:dbbbd68addd737f9` as unreviewed with 13 held and nine conservative
  events; no real Review or downstream object was written.

## 2026-09-16 V2 Source-First Workflow Audit and Remediation Plan

- Performed a read-only comparison of the V2 second-slice contract, current
  production code, frontend invocation and fixed #40 API state.
- Confirmed an implementation-order divergence: the contract says immutable
  SourceSnapshot first, while `compute_diagnosis()` runs `ANSWER_SEMANTIC ->
  SOURCE_SNAPSHOT -> EVIDENCE_DIAGNOSIS`. The frontend exposes one diagnosis
  action and omits stage-specific policies; backend request defaults can combine
  source fetching and external evidence LLM work.
- Confirmed the reviewed #40 result is 3/3 Answer-admitted with review
  `review-52312343-ec21-4214-94ae-20368eca5e86`, but still has 77 reference
  observations / 35 unique sources, zero content-ready snapshots, zero passages,
  zero SourceClaims and 770 not-evaluated relations.
- Added `SINGLE_PROMPT_CORE_V2_SOURCE_COMPLETION_PLAN.md` as a detailed Product
  Owner review draft. It specifies source-state conservation, automatic fetch,
  same-source manual supplementation, explicit waiver, immutable manifest,
  source-first backend gate, separate external authorization and reviewed
  Answer-to-Evidence continuation.
- Code changes: none. Migration: none. Business data writes: none. External
  calls/fetches: none. Tests were not run because this checkpoint changes
  documentation only.
- Formal classification is `SEMANTIC_RISK / IMPLEMENTATION_DIVERGENCE_REMEDIATION`.
  Implementation and production cutover remain unauthorized pending review.

## 2026-09-20 GEO 1.0 R2 + R3 First-Slice Implementation

- Added a dedicated release Alembic baseline (`20260920_01`) and an exact
  25-table allowlist. The release app validates revision, allowlist, WAL,
  foreign keys and the SQLite WAL-reset fix at startup; it does not call
  `create_all()` or legacy column repair.
- Added a pinned `pysqlite3` bootstrap that builds against SQLite 3.51.3 after
  verifying both source archive SHA-256 values. Formal migration and runtime
  use the same DBAPI. The default independent `backend/geo_release.db` and a
  second clean temporary database both migrated successfully.
- Split the formal runtime into one API and one single-concurrency business
  worker. Sampling, Answer Semantic and Evidence endpoints now queue work;
  queued jobs survive API restart, while in-flight uncertain jobs fail closed.
- Evidence continuation now validates and freezes exact Citation Manifest,
  Source Completion Manifest, Answer ResultVersion and Review before enqueue,
  then revalidates the same binding in the worker. Retry reuses the saved input
  instead of querying latest.
- Added formal release start scripts, release-only frontend navigation and
  explicit Evidence queued/running/failed UI states. Strategy, Execution,
  Publication, Retest and optimization routes remain absent.
- Added restart persistence checks covering Snapshot artifact path/hash,
  Review identity and Evidence ResultVersion. Ten release tests and 50 related
  release/session/V2 tests pass; both frontend builds pass.
- Full backend baseline: 598 passed / 6 failed. The failures are two legacy
  prompt batch-delete assertions, two legacy Strategy-to-Experiment assertions
  and two Runtime Projection Spike assertions. None of those routes/tables are
  registered by the release app; their shared safety constraints have release
  replacements, so they remain documented/archived rather than edited away.
- The Wenxin collector now fails closed before submission unless it proves a
  zero-turn new conversation and stores the actual sampling condition and proof
  basis. No real browser replay was authorized in this implementation run, so
  live independent-session verification remains pending.
- No external fetch, browser sample, DeepSeek call, automatic Review, waiver or
  real Evidence write occurred. The release database is ready but empty of real
  business objects; fixture output is not reported as real acceptance.
- Checkpoints: `9391be7` (release schema/source/evidence spine), `279c717`
  (release source UI), `f421a95` (Wenxin fail-closed session reset), `7e657c9`
  (safe SQLite runtime + single worker + Evidence queue), `d561363` (release
  persistence and exact-gate tests).

## 2026-09-20 GEO 1.0 First Real Release Acceptance

- Fixed two blockers exposed only by the formal release path: release sampling
  no longer freezes a partial Context before an explicit retry, and migration
  `20260920_02` adds the collector-owned `brand_mentions` table to the frozen
  release schema. Checkpoints: `50f19f6`, `d150e17`.
- Created Project `1` / Prompt `1` through the release catalog and sampled three
  valid Wenxin Runs under the five-attempt cap. Every final Run stored a distinct
  conversation identity and `PRE_SUBMIT_ZERO_TURN_DOM_GATE`; Run 3 remains
  `partial_success`, preserving its citation-completeness limitation.
- Frozen Analysis `a2d0c0ee-b62e-4f39-9fe9-1bc14efdea33`, Context
  `ctx-96357192-0f2d-45db-b70c-0b58c2987dcd`, Raw Result
  `raw-v1:c0918158fcea889c`, and a 38-source/87-occurrence Citation Manifest.
- Submitted real `2om.cn` page text through the formal manual-content API. It
  produced immutable Snapshot `source-snapshot-1a51fa9d-9c0a-4cea-85f2-db72a67db8d0`,
  SHA-256 `d163a7fe...d99822`, and 20 passages. No other fetched candidate was
  auto-promoted to READY and no source was automatically waived.
- Answer Semantic made three DeepSeek requests, admitted all three frozen
  answers, and published `diag-v1:69cb9884452deead` with a legal zero-event
  result. Usage is 8,922 total tokens, zero cache hits; no Review was created.
- Preserved the serial source-fetch audit and 27 candidate texts under the
  ignored `backend/artifacts/release-acceptance/.../unvalidated-candidates`
  directory. They remain human-review inputs and are not formal Snapshots.
- Real negative gates passed: Completion freeze returned 409 with 37 PENDING
  sources, and Evidence continuation returned 409 without the exact Answer
  Review. No SourceClaim/Alignment evaluation or Evidence task was created.
- A service restart preserved exact Analysis/Context, Snapshot/artifact hash,
  Diagnosis ResultVersion and `review=null`. The exact deep link reopened all
  source, review and Evidence Gate panels without selecting latest state.
- Removed the release UI's residual legacy Prompt-overview probe and made the
  release SPA return 404 for every unregistered `/api/*` route instead of
  serving `index.html` with a misleading 200. Release route isolation now has
  both route-table and HTTP-response coverage (`d24f936`).

## 2026-09-20 Release Sampling Search-Term Display

- A follow-up DOM audit corrected the initial display-only interpretation. The
  Wenxin `.cs-answer-container` contains both `.ai-thinking-steps` and the final
  `.ai-markdown`; the collector previously persisted their combined text as
  `answer_text`.
- New Runs now persist a `wenxin_semantic_regions` artifact. Platform-reported
  search terms are an `OBSERVATION_ONLY` module, while `answer_text` and
  `answer_html` come only from the final Markdown region. Collector version is
  `wenxin-web-v1.3-final-answer-only`. A real clean-database replay exposed that
  the old generic-container fallback could return the transient "正在思考"
  placeholder before final Markdown existed. That fallback was removed; a Run
  now completes only after the final Markdown exists and the answer container
  is no longer `GENERATING`.
- Frozen historical Runs are not rewritten. A deterministic projection marks
  the known mixed shape `LEGACY_MIXED_CONTAINER`, and backend gates reject
  revision, review and Evidence continuation for that input. This prevents a UI
  warning from becoming the only protection.
- Added collector DOM-boundary, immutable Context projection and Answer Semantic
  input-gate regressions. No browser sampling, model call, source fetch, Review,
  Truth or Evidence write was performed by this change.

## 2026-09-20 Wenxin Reference Completeness Regression

- A clean release replay exposed a collector regression introduced by the
  first-delivery simplification. The DOM noise filter used substring matching
  for labels such as `复制`, so the legitimate reference title `3.02 复制打开抖音`
  was removed from Runs 2 and 3. Wenxin had returned all 28/24 references; the
  collector incorrectly persisted 27/23 and marked both Runs partial.
- Restored the earlier multi-view extraction contract: merge reference lists
  captured before panel open, after open and after scroll, preserve the
  platform's explicit reference indexes, and verify index conservation against
  the declared count. Button labels now use exact matching and cannot remove a
  reference merely because its title contains the same word. The auditable
  collector version is `wenxin-web-v1.4-reference-complete`.
- The two frozen page artifacts replay locally as 28/28 and 24/24, including
  the previously omitted item. Historical Raw Result remains immutable; only a
  new formal collection can produce a corrected business result.
- The review also confirmed that automatic source fetching still exists as the
  reusable `fetch_page_playwright()` computation kernel, but the release Source
  Preparation API currently exposes only manual submission. The missing V2 DTO
  adapter is a release-path integration gap; the legacy Diagnosis/optimization
  runner must not be re-enabled as a shortcut.

## 2026-09-20 Release Source Auto-Fetch Adapter

- Connected the existing `fetch_page_playwright()` browser-rendering and HTTP
  fallback kernel to the formal release Source Preparation path. The V1
  `acquire_cited_sources()` runner was deliberately not called because it writes
  legacy `SourceDocument` workflow state; V2 owns queue state, validation,
  artifact persistence, passages and immutable snapshot identity.
- Added explicit `POST .../source-preparations/{id}/auto-fetch`, single-worker
  execution and restart recovery. GET remains read-only. Network work occurs
  outside database write transactions.
- Successful complete content becomes an Analysis/Context/Citation-Manifest
  bound `AUTO_FETCH` snapshot. Partial, blocked, missing, unsafe or failed
  results become `MANUAL_REQUIRED`; no automatic WAIVE is possible.
- The release page now presents “automatic first, manual fallback”, polls queued
  work, shows per-source failure reasons and only opens manual controls for
  unresolved sources (or explicit replacement of an existing READY version).
- Added focused worker, snapshot, failure, no-waiver and restart tests. Release
  first-slice suite: 14 passed. Python compile, frontend production build and
  diff check pass. No real source fetch or resample occurred before checkpoint.

## 2026-09-20 Corrected Resample and Real Automatic Source Preparation

- Created a new formal release Analysis for Project `1` / Prompt `1` without
  rewriting the earlier immutable acceptance run. Analysis
  `92bb12a5-edcc-43c7-b848-ca60267a2672`, Task `2`, Runs `4/5/6`, Context
  `ctx-79dcb9e0-a8fe-4c17-b584-01c240acdde2` and Raw Result
  `raw-v1:eb86358c452b1bc4` are the corrected baseline.
- All three Runs submitted exactly `抖音跳转链接`, stored only final-answer
  Markdown, completed with 30/27/30 references and distinct Wenxin conversation
  identities, and recorded `PRE_SUBMIT_ZERO_TURN_DOM_GATE` as the independent
  session proof. No retry or replacement sample was needed.
- Source Preparation `source-prep-25dbbbb2-b5ed-49c7-895c-8a8384a55afe`
  froze Citation Manifest `citation-manifest-9ccde3db-5810-440a-aef8-836306c6db44`
  (`46` unique sources / `87` occurrences) and then used the formal auto-fetch
  endpoint. The serial worker produced `30` READY immutable AUTO_FETCH snapshots
  and `16` MANUAL_REQUIRED items; it produced zero waivers.
- The 30 snapshot files all exist and match their stored SHA-256 values. They
  contain 859 passages. A read-only replay through the established content
  quality rules classified all 30 as `CONTENT_VALID`; the 16 unresolved items
  remain visible as blocked/partial/fetch-failed manual work rather than being
  promoted to evidence.
- Real execution exposed a transaction-order defect: disposition rows were
  correct while the preparation summary retained `AUTO_FETCH_PENDING` because
  aggregation ran before the ORM flush. Aggregation now flushes first, and
  startup reconciliation repairs this settled stale summary without fetching
  any URL again. The real preparation recovered to `MANUAL_REQUIRED` with the
  exact `30/16/0` disposition set unchanged.
- Completion Manifest and Evidence were not created. Answer Semantic, Review,
  SourceClaim, Alignment, Truth and Strategy were not run in this replay. The
  next user action is manual completion or explicit waiver of the 16 unresolved
  sources; source disposition completion still does not imply evidence support.

## 2026-09-21 Release Home Prompt Visibility

- Reproduced the release home page with the real release API. Project `1` and
  Prompt `1` were both returned correctly, but `frontend/dist` had been replaced
  by a normal `npm run build`. That build requested legacy monitoring routes
  against the release-only API and discarded the otherwise valid Prompt load
  when the grouped request failed.
- Rebuilt with the existing release mode and added an emitted
  `geo-release-build.json` marker. `scripts/release-dev.sh` now refuses to start
  when `dist` is present but is not a release build, preventing a stale normal
  bundle from silently presenting the wrong home page.
- In the release first slice, a project with exactly one Prompt now selects that
  Prompt automatically unless an explicit valid Prompt identity is already in
  scope. This is an implementation-only navigation correction; Project/Prompt
  identity and all Analysis inputs remain unchanged.

## 2026-09-21 Release Analysis Resume And Next-Action Visibility

- The release home could show Project and Prompt but still strand an existing
  Analysis behind query parameters. Added a read-only, Project/Prompt-scoped
  Analysis list and an explicit `继续处理` action. Selection always carries the
  exact `analysis_id`; the backend and frontend do not infer or auto-open the
  latest Analysis.
- The bound Analysis page now states the current source-preparation action and
  defaults the source list to unresolved items. READY and waived sources remain
  available through explicit filters, while Source Completion and Evidence
  gates are unchanged.
- Real release state at verification time contains three explicit Analysis
  records. Analysis `92bb12a5-edcc-43c7-b848-ca60267a2672` has 3/3 valid Runs,
  30/46 READY sources and 16 `MANUAL_REQUIRED`; Analysis
  `9b735b29-d6d9-46da-9de1-6331e9b84f48` was separately created from the UI,
  completed 3/3 valid Runs and has not started Source Preparation; the older
  `9f8d0400-b88c-47fb-be95-a7dbebe5d10b` also remains visible with 3/3 valid
  Runs and no Source Preparation. None has a Completion Manifest, Answer
  Semantic execution or Evidence execution. The resume fix itself performed no
  collection, fetch, model, review, waiver or evidence write.

## 2026-09-21 Prompt Run Pool, Explicit Analysis Inputs, And Single-Run Retry

- Restored the mature monitoring model as a Prompt-level Run pool instead of
  requiring every new Analysis to launch another browser task. The release API
  now lists all Runs for an exact Project/Prompt with full answers, references,
  acquisition conditions, limitations, immutable input fingerprints and
  Analysis memberships.
- Added explicit `run_ids` Analysis creation. The backend rejects duplicates,
  cross-scope Runs, non-analyzable Runs and stale fingerprints, then writes a
  new immutable Context with `task_id = NULL`. No browser Task is created and no
  old Context, Result or Review is changed.
- Reused `create_browser_task_from_frozen_prompt()`, `MonitoringTaskExecutor`
  and `update_task_status_from_runs()` for failed single-Run retry. A retry is a
  new one-Run Task and Run with lineage; it never overwrites the failed source
  Run or reruns successful siblings.
- Release migration `20260921_01` changes only Analysis/Context task ownership.
  It was rehearsed against a copy of the populated release database, then
  applied to the real database. Revision, 9 Runs, 3 Analysis/Context versions,
  source snapshots and file bindings remained intact; `foreign_key_check` is
  clean and immutable Context triggers were recreated.
- Existing Source Preparation already provides the requested automatic-first,
  manual-fallback behavior by reusing `fetch_page_playwright()`. Existing V2
  Evidence uses strict `LLMCallCache` semantic identities and exact immutable
  result reuse; the old SourceClaim/Alignment workflow tables were not added to
  the release schema.
- Current release data does not contain the zero-event Diagnosis/Result/Review
  objects cited by the work order. No new model call was authorized, so this is
  recorded as a real-input mismatch rather than reconstructed from older notes.
- The formal API demonstration selected existing Runs `7/8/9` and created
  Analysis `5ced1566-9e79-4c84-8bc8-1bccf58550a3`, Context
  `ctx-456936cd-e32c-4901-9ae5-7e6a8d167cc3` and Raw Result
  `raw-v1:139f8b4a8797739f`. `task_id` is null, the Browser Task count stayed at
  three, and the existing 30/16 Source Preparation state was unchanged.
- A full API/worker restart retained that Analysis/Context, the exact Run set,
  and the original 46-source conservation. All 30 persisted source artifact
  files still matched their stored SHA-256 values; no queued business work was
  created or advanced during restart.
- Release first-slice suite: 21 passed, including populated migration upgrade,
  explicit Run selection across sampling Tasks, cross-Project/stale input
  rejection, single retry preservation and worker dispatch. The broader related
  suite passed 101 tests before the final cross-Task case was added; that added
  case also passes independently. Release frontend build and desktop/mobile
  visual verification pass.

## 2026-09-21 Release Site Reconciliation And Main Analysis Pin

- Verified the live API and worker with process open-file inspection. Both use
  `backend/geo_release.db`; the release migration command resolves the same
  absolute path. Revision is `20260921_01`, SQLite is `3.51.3`, schema validation
  is READY and `foreign_key_check` is clean.
- Queried the actual result-bearing tables, all workspace SQLite files and the
  surviving `/private/tmp` release backups for the prior Analysis, Answer Result
  and Snapshot IDs. No row matched. The current database was created after that
  historical acceptance and restarted Task numbering from 1, so the prior IDs
  belong to the replaced pre-rebuild release database rather than a hidden
  result table. Their audit details remain in the operations log only.
- Pinned the continuing case to Analysis `92bb12a5-edcc-43c7-b848-ca60267a2672`,
  Context `ctx-79dcb9e0-a8fe-4c17-b584-01c240acdde2`, Runs `4/5/6`, Citation
  Manifest `citation-manifest-9ccde3db-5810-440a-aef8-836306c6db44` and Source
  Preparation `source-prep-25dbbbb2-b5ed-49c7-895c-8a8384a55afe`. Runs `7/8/9`
  and their run-selection Analysis remain acceptance history only.
- Confirmed all 30 READY artifacts remain available. None of the 16 unresolved
  rows has a persisted current candidate. The old `2om.cn` Snapshot content is
  absent; an audit hash alone cannot satisfy exact content/version reuse.
- The live release database has no diagnosis, review, completion, evidence or
  LLM cache row. No external operation, automatic review, waiver or business
  state write was initiated by the reconciliation commands.
- A separate browser page concurrently issued three explicit POST requests at
  `2026-09-21 03:52Z`: it created an all-Runs Analysis, created its Source
  Preparation and started auto-fetch. Server access logs distinguish this from
  test fixtures and read-only polling. The new Analysis is retained as a
  separate user operation and is not selected as the Runs 4/5/6 main case.

## 2026-09-21 Authorized Main-Case Answer Batch

- Created and restored an isolated SQLite online backup before external work.
  The restored copy retained revision `20260921_01`, the pinned Analysis,
  Context and Citation Manifest, 30 snapshots, 859 passages and 30/30 artifact
  hashes.
- Ran the formal release Answer-only endpoint for Runs `4/5/6` under the exact
  manifest binding. Diagnosis `b0a35004-3c12-46f1-af49-76c903031c6f` published
  immutable Result `diag-v1:9a76fc3853156f99` and is `READY_FOR_REVIEW`.
- DeepSeek made exactly three external calls with no retry or cache hit. All
  three answer payloads passed strict admission: Runs 4/5 produced three total
  review-required option events, while Run 6 produced a legal zero-event
  result. No Review, Truth, Completion Manifest or Evidence task was created.
- Repeating the same formal request with the same idempotency key returned the
  existing execution. Database counts remained one execution, one result,
  three cache rows and zero reviews; no duplicate external call occurred.
- Confirmed the release UI already exposes full frozen answers, per-event
  decisions and the 16 exact manual source actions. Evidence remains correctly
  blocked by the missing exact Review and Completion Manifest.
- No code changed in this batch. Only the durable operations and status records
  were updated.

## 2026-09-21 Manual HTML Source Completion And Frontend Loading Fix

- Added an explicit `HTML_SOURCE` mode to the existing manual source-completion
  endpoint. It reuses `optimization.primary_content.extract_from_html()` as a
  pure extraction kernel, then passes the extracted text through the existing
  V2 content block, immutable artifact, Snapshot and passage path. No legacy
  Runner or workflow state is restored.
- HTML that produces `SUSPECT`/`EMPTY` output is rejected. Partial extraction
  cannot be submitted as `FULL_PAGE`; the operator must select `EXCERPT` or
  provide complete content. The frozen source URL and row version still define
  ownership, and no rejection changes the disposition or creates a Snapshot.
- The release UI now offers `粘贴正文` and `粘贴页面源码` for every manually
  resolvable source. Successful HTML extraction is visibly recorded as
  `MANUAL_HTML_SOURCE`; only extracted clean text enters the immutable evidence
  artifact.
- Fixed the apparent frontend hang by separating read-only refresh state from
  source mutations. The 3-second auto-fetch poll is silent and can no longer
  put every manual submit/waiver/freeze button into loading. A mutation now
  shows loading only on the exact source action and prevents conflicting writes.
- The populated release database was not changed. The service restarted on
  revision `20260921_01` with the same `30 READY / 16 MANUAL_REQUIRED` state.
  Release first-slice tests pass `22/22`; the release frontend build passes, and
  a headless production-page render found zero loading buttons after settlement.

### Follow-up: persist manual submission outcomes

- Live access logs proved the reported no-op was two completed
  `POST .../manual-content` requests returning HTTP 422 against Analysis
  `19b0be0f-f794-4435-9fa7-2723257f26cc`; it was not a hung request and created
  no Snapshot.
- Manual-source success and rejection are now retained in the source workspace,
  with the exact source title and backend reason. The same rejection also stays
  next to the expanded source row. FastAPI field-level validation errors are
  rendered as readable field/reason messages instead of raw JSON.
- The page separately identifies the current Analysis. This follow-up did not
  switch the user from the 66-source all-Runs Analysis to the pinned 46-source
  Runs 4/5/6 Analysis, and did not change either source inventory.
- A subsequent retained rejection exposed the former 5,000,000-character DTO
  limit before extraction. Real browser page source can exceed that size due to
  embedded scripts and state. The bounded local-release limit is now 25,000,000
  characters, the UI shows pasted size before submission, and a regression
  proves payloads above the former limit reach V2 admission.

## 2026-09-21 V2 Target Brand Truth Review Entry

- Classified as `IMPLEMENTATION_CHANGE`: the V2 contract already requires an
  independent, explicit Product Truth operation, but the release page only
  displayed an empty frozen Truth snapshot and the only write route lived in
  the retired Optimization API.
- Added a release-owned narrow write endpoint bound to the exact Analysis,
  Diagnosis, active ResultVersion/result hash, frozen Truth-set hash and current
  project Truth-set hash. It creates a manually reviewed project fact and
  refuses silent overwrite, stale submission and positive facts without a
  source reference.
- The diagnosis status now exposes the current project Truth set separately
  from the immutable diagnosis snapshot. Saving a fact never rewrites the old
  result or review. The page explicitly requires a new Answer-only diagnosis,
  forced to `CACHE_ONLY`, before the new fact can participate in deterministic
  Reason-to-Truth matching.
- Added per-reason review entry points and an in-page fact form. Competitor/tool
  reasons are not copied into the target-brand capability field; the operator
  must state and source the target brand's own fact.
- No real Truth, Review, Diagnosis or external LLM call was created during this
  implementation. Read-only verification against Diagnosis
  `1bb77e76-a959-4b6c-9fc0-fd98a4b8b6ff` confirmed the frozen and current Truth
  hashes both remain the empty-set hash.
- Validation: 54 related backend tests passed, two new exact-binding/stale-write
  regressions passed after the target entity uniqueness hardening, release and
  regular frontend builds passed, and the production page rendered three
  `核对事实` actions plus one enabled `保存人工事实` action without overlap.

## 2026-09-22 V2 Product Truth Responsibility Correction

- Classified as an implementation correction under existing `SC-PT-001` and
  `SC-UNKNOWN-001`; no new RFC or workflow stage was introduced. Answer signals,
  target-brand facts and public-claim eligibility are now separate objects and
  must not be treated as equivalent.
- Competitor/tool Reasons no longer create cross-brand Reason-to-Truth coverage
  rows. They are retained as `external_capability_signals`, including grounded
  source subject/text and bounded target applicability matches. Such a match may
  qualify a strategy hypothesis only when the target brand has an independently
  confirmed, atomic and eligible Truth; it never proves the competitor claim.
- Manual Product Truth entry is bound to an exact Answer signal or Market
  Criterion, but that signal is only the review trigger. Positive facts still
  require target-brand provenance. Compound capability statements are rejected
  and must be split into independently verifiable claims; existing compound or
  UNKNOWN facts are projected as `VERIFY_FIRST` rather than silently consumed.
- Added immutable Truth reprojection. A reviewed Diagnosis may create a new
  exact diagnosis identity with the current Truth-set hash while copying the
  unchanged Answer/Evidence output and exact prior review metadata. It performs
  zero Answer, SourceClaim or Alignment calls, never mutates the prior result,
  and requires a new explicit review before Strategy consumption.
- Product Truth incompleteness does not block Answer Semantic or Evidence. It
  only blocks dependent target applicability, deterministic strategy claims and
  public content. Strategy and Execution additionally require
  `statement_eligibility=ELIGIBLE`; `PARTIALLY_COVERS`, compound, UNKNOWN and
  prohibited statements remain non-publishable.
- No release business data, Review, Truth, Strategy or external model call was
  written during implementation. The currently source-complete all-Runs Analysis
  and the separately authorized Runs 4/5/6 Analysis remain distinct; this change
  does not reinterpret authorization or silently switch the active identity.
- Production read-only verification used all-Runs Analysis
  `19b0be0f-f794-4435-9fa7-2723257f26cc`: its Citation scope is conserved at
  `66/66` (`61 READY`, `5 WAIVED_WITH_LIMITATION`), Source Completion
  `source-completion-f4b4b160-827b-42b4-986c-191f67453042` is frozen, and exact
  Answer Review `review-f13b8c36-323e-494b-bbc0-49089987bca6` remains attached
  to Result `diag-v1:07a0295d2e967a3b`. The two later project facts are both
  projected as `VERIFY_FIRST` because they are compound statements; this does
  not invalidate source or Answer completion.
- The production render exposed one legacy compatibility defect: an external
  subject with `truth_id=null` was not marked cross-subject and still appeared
  in the target-brand relation table. Current projection now classifies by
  grounded subject independently of whether a Truth row exists. The immutable
  historical row remains unchanged; the UI presents it as an external ability
  signal instead. The regression covers this exact empty-Truth shape.
- Validation after the compatibility fix: the diagnosis/strategy/execution and
  release first-slice suites passed, targeted cross-subject regressions passed,
  `compileall`, release frontend build and `git diff --check` passed. A release
  production screenshot confirmed separate external-signal and target-brand
  relation sections without layout overlap.
- Follow-up production review found that Run 4 listed both `爱短链` and
  `趣码短链` as `INCLUDE_AS_OPTION` using the same grounded reason. The external
  entity is now classified as `CO_RECOMMENDED_WITH_TARGET`, retains its market
  context, and cannot create a duplicate target-fact review trigger or Strategy
  applicability path. The release UI labels it `同段共同推荐的其他选项` and keeps
  the target-brand Reason in the target relation table. Independent external
  capability signals retain the existing review path.
- The fact panel now reports effective public-claim eligibility directly. The
  current project has two manually recorded rows but zero eligible atomic facts:
  one `SUPPORTED` compound statement and one `UNKNOWN` compound statement are
  both `VERIFY_FIRST`. This status does not block Answer or Evidence.

## 2026-09-22 V2 Atomic Target Capability Review Simplification

- Classified as `IMPLEMENTATION_CHANGE` under `SC-PT-001` and
  `SC-UNKNOWN-001`. The operation still confirms only the target brand's own
  facts; this change removes internal diagnosis terminology from the operator
  surface instead of changing Product Truth semantics.
- Added a read-only `target_capability_review_items` projection. It consumes
  only target-brand Answer events explicitly confirmed by the exact Diagnosis
  Review, splits grounded compound Reasons into conservative single-capability
  candidates, deduplicates the same capability across Runs and retains every
  source Reason, Run and answer excerpt. The projection itself never creates a
  Product Truth or a Reason-to-Truth relation.
- Replaced the release-page Product Truth panel with one direct table:
  `single capability -> target brand has / partially has / does not have /
  unknown -> target-brand source`. Co-recommended competitors, external-signal
  tables, frozen-snapshot details and raw `Reason->Truth` enums are no longer
  shown in this operator action. They remain available in immutable diagnosis
  audit data and do not become target-brand review items.
- Removed the two malformed compound manual facts from Project `1` after an
  SQLite online backup. Neither Truth ID appeared in an immutable Diagnosis
  result, and no Strategy tables exist in the release schema. Original Runs,
  answers, citations, Diagnosis Result `diag-v1:07a0295d2e967a3b` and Review
  `review-f13b8c36-323e-494b-bbc0-49089987bca6` were unchanged.
- The live API now returns six review-only atomic candidates from confirmed
  Runs `4/5`, with `生成加密短链` deduplicated across both Runs and no competitor
  Reason in any candidate lineage. Desktop and 390px browser checks found no
  horizontal page overflow.

## 2026-09-22 Release Evidence-to-Strategy Readiness Handoff

- The exact Evidence result `diag-v2:4de692c413d03abf` was reviewed as
  `REVIEW_COMPLETED`. Release now exposes a read-only strategy-readiness route
  and a post-review next-step panel instead of ending silently after Evidence
  review. Strategy creation, execution and retest write routes remain excluded
  from the first-slice release.
- Strategy input projection now consumes the exact Prepared Snapshot IDs frozen
  by the Evidence result. It does not query the retired Diagnosis-owned snapshot
  table or substitute a latest snapshot. Exact Answer events already confirmed
  by the bound upstream Answer review remain consumable without requiring the
  user to confirm them again in the Evidence review.
- Current production readiness is classification `B`: 3/3 grounded Reasons are
  consumable, 61 prepared sources and 1 effective Evidence relation are visible,
  but there are 0 qualified strategy directions. Target-brand atomic Truth is
  unresolved, the evaluated relation is only `RELATED`, other relations remain
  unevaluated after SourceClaim admission failures, and all answer anchors are
  `UNPROVEN`. The page now presents these as concrete next actions rather than
  another generic manual-review request.

## 2026-09-22 Capability Presence / Public Claim Gate Split

- Corrected the remaining Product Truth coupling without adding a schema or a
  workflow stage. An operator may now record one atomic target-brand capability
  as `SUPPORTED`, `PARTIALLY_SUPPORTED`, `NOT_SUPPORTED` or `UNKNOWN` without
  supplying a URL or note at the same moment.
- `SUPPORTED + MANUAL_CONFIRMED` now means capability presence is confirmed for
  deterministic target-applicability and Strategy qualification. Missing
  target-brand provenance still leaves `statement_eligibility=VERIFY_FIRST`
  with `SOURCE_REFERENCE_REQUIRED`; it is not a publishable Product Truth.
- Exact grounded Reason-to-Truth coverage no longer depends on public-claim
  eligibility. This permits Strategy to answer whether an observed Reason is
  relevant to the target brand. `PARTIALLY_SUPPORTED`, semantic containment,
  compound statements and unknown status remain conservative and cannot become
  automatic full coverage.
- Strategy readiness separately reports `confirmed_capability_count` and
  `public_claim_eligible_count`, and emits
  `PUBLIC_CLAIM_EVIDENCE_PENDING` without blocking an otherwise qualified
  Strategy direction. The Strategy input contract is now
  `single_prompt_strategy_input.v4_capability_publication_split`; Truth matching
  is `single_prompt_truth_relation.v5_capability_presence`.
- Execution/public-content compilation remains strict. A confirmed capability
  lacking eligible target-brand provenance is rejected by the backend with
  `PUBLIC_CLAIM_EVIDENCE_REQUIRED`; it cannot enter a title, section, claim
  policy or published asset merely because the operator clicked `有`.
- The release page now asks only whether the target brand has the capability,
  makes provenance optional at this stage, and displays a separate public-claim
  state (`依据已齐` / `发布前补依据`). No real Truth, Review, Strategy or external
  call was created by this implementation.
- Read-only page verification exposed and fixed an Evidence-version handoff
  defect: the capability list previously looked only at decisions in the latest
  Evidence Review and could show `0/0` even though the immutable Answer events
  already carried an exact upstream human confirmation. The list now accepts
  either a confirmation in the current review or the bound event-level upstream
  review metadata; unreviewed events remain excluded.
- Validation: 81 diagnosis/strategy/execution tests passed, including quick
  source-free confirmation, Strategy qualification with pending publication
  evidence, and hard rejection at execution content generation.

## 2026-09-22 Capability Confirmation Feedback and Strategy Handoff

- Fixed the release capability editor so a successful save immediately updates
  the matching atomic row, confirmed count and publication-evidence state. The
  UI no longer waits for a full reload before acknowledging a saved capability.
- Added an explicit `应用并进入策略` handoff beside the capability count. It
  creates a Truth-only reprojection using the existing frozen Answer/Evidence
  inputs, then asks the operator to confirm only the changed capability
  relations before refreshing Strategy readiness.
- Strategy no longer treats one confirmed atom as coverage of a compound
  Reason. The diagnosis projection records the complete required atomic set;
  qualification becomes `FULLY_COVERS` only when every required capability is
  manually confirmed `SUPPORTED`. Otherwise readiness names the exact missing
  capabilities. Public-claim evidence remains an independent downstream gate.
- Release migration `20260922_01` adds only the V2 Strategy execution, immutable
  result and append-only review tables. The release API exposes exact-version
  Strategy generation/revision/review; Execution Proposal, Publication and
  Retest routes remain closed. No live reprojection, Strategy or Review was
  created automatically by this change.
- Existing release data survived migration unchanged: 3 target capability
  truths, 3 diagnosis results and 2 diagnosis reviews. The pre-migration SQLite
  online backup passed `PRAGMA integrity_check` at revision `20260921_01`.

## 2026-09-22 Fixed Nine-Run Completeness and Incremental Evidence Repair

- Added five read-only projections to the real V2 status path:
  `input_scope_coverage`, `compute_coverage`, `review_coverage`,
  `evidence_plan_coverage` and `strategy_dependency_coverage`. They separate
  pending authorization, invalid cache, actual failure and legal zero results.
- The current release input remains immutable at Analysis
  `19b0be0f-f794-4435-9fa7-2723257f26cc`, Context
  `ctx-f06aa92a-6193-4aa0-ab9b-e62974f594f4`, Raw Result
  `raw-v1:a447f95889472632`, Citation Manifest
  `citation-manifest-adbd75b9-401e-479a-9ac2-36ae0db58626` and Source
  Completion hash `5d8aa4e38881accc5fb7d7d7805a22a00047c870d761ab701fd270a353d9b065`.
  It still has 61 READY sources, 5 explicit waivers and 1530 passages.
- Current Result `diag-v1:83192f653f4c8a71` is now truthfully projected as
  3/9 valid Answer computations: Runs 4/5 have events and Run 6 is a legal zero;
  Runs 1/2/3/7/8/9 are pending external authorization. The historical cache-only
  misses are not exposed as Answer failures. No current exact-result review exists.
- New Answer results preserve exact prior reviewed Run/event provenance only as
  `PREFILL_ONLY_NEW_EXACT_RESULT_REVIEW_REQUIRED`. No prior Review is inherited as
  authority for the new nine-Run ResultVersion.
- Replaced the fixed two-passages-per-Reason behavior with a deterministic
  same-Run candidate plan: stable retrieval tie-break, explicit-anchor priority,
  source diversity, strong-threshold boundary ties, 12 total candidates per
  Reason and at most 3 predeclared technical-failure replacements. Candidate
  plan identity is bound at queue time and revalidated by the worker.
- SourceClaim admission now isolates invalid Claim items after the complete
  response envelope passes strict Schema validation. Valid grounded items remain
  consumable; rejected items remain explicit limitations. Schema-invalid whole
  responses are still rejected in full.
- Strategy now freezes exact Reason/Truth/Evidence dependencies per direction.
  A locally qualified direction remains visible, but the formal create path is
  blocked until all fixed Runs have valid Answer computation and the new exact
  ResultVersion has been reviewed. A limitation or waiver cannot replace a
  required dependency.
- Offline validation: 137 relevant backend tests passed, including release
  migration/continuation, strict LLM admission, fixed-scope coverage, plan
  binding, bounded fallback and Strategy dependency gates. Python `compileall`,
  frontend TypeScript/Vite production build and `git diff --check` passed.
- External calls, browser sampling, source fetching and production DB writes
  performed by this repair: 0. The next paid scope is exactly Answer Runs
  1/2/3/7/8/9, maximum one request each and no automatic retry. The final
  Evidence plan must be regenerated from the reviewed nine-Run result; valid
  compatible computations are reused and only missing, failed or invalidated
  work may call externally.

## 2026-09-28 Citation Contribution P1 Checkpoint 0

- Froze the live nine-Run input and its exact Answer, Review, Citation Manifest,
  Source Completion, and historical Evidence identities in
  `CASE-REAL-V2-P1-CITATION-CONTRIBUTION.checkpoint-0.json`.
- Classified `diag-v2:5435e5989f2a7c2f` as immutable
  `REASON_EVIDENCE_BASELINE`; it remains useful as a candidate clue but has no
  review authority under Citation Contribution V1.
- Froze Citation Contribution's independent processing, correspondence,
  evidence, answer-anchor, and generation-influence dimensions. Pair verdicts
  cannot encode composite support, and failed/not-evaluated work cannot become
  a negative evidence result.
- Resolved the definition-level Foundation/channel and asset-identity conflicts:
  FACT_ANCHOR does not imply OFFICIAL_SITE PRIMARY; SourceSnapshot is not a
  ManagedAsset; incomplete inventory yields UNKNOWN/VERIFY_ASSET_FIRST rather
  than CREATE_NEW.
- Deterministic P1 selection chose Run 1 before contribution execution because
  it is the first fixed Run with a readable answer, technically complete
  citation parsing, and consumable source content. It has 19 citation
  occurrences, all bound to READY source snapshots. The rule does not inspect
  brand appearance or expected relation outcomes.
- External calls, source fetching, browser sampling, Strategy writes, and
  production Evidence writes in Checkpoint 0: 0.

## 2026-09-28 Citation Contribution P1 Checkpoint 1 Pre-authorization

- Release migration `20260928_01` adds only the scoped Citation Contribution
  execution, immutable result and append-only calibration review tables. The
  legacy application does not register these routes or query these tables;
  formal creation, authorization, execution and review belong to the release
  API and worker.
- Before migration, SQLite Online Backup captured the release database at
  revision `20260922_01` and an artifact archive captured the 61 source files
  for Context `ctx-f06aa92a-6193-4aa0-ab9b-e62974f594f4`. Database integrity,
  revision, release allowlist, SQLite `3.51.3`, WAL and foreign keys passed after
  upgrade. Frozen Raw, Answer, historical Evidence and manifest hashes did not
  change.
- The formal release API created Contribution
  `citation-contribution-76074b05-e357-41b0-b563-51bdf3dc720d` with Plan
  `citation-contribution-plan-1144c02d0a8eb1daf200`. The deterministic rule
  selected Run `1`; it covers all 714 non-whitespace answer characters with 18
  AnswerUnits and includes all 19 citation occurrences. All citations are
  READY, map to 18 immutable snapshots, and freeze 228 candidate pairs.
- The plan also freezes 34 boundary pairs excluded by the 12-pair-per-citation
  model budget. Up to 10 are reserved in the 60-item calibration set so a
  reviewer can record hard-filter false negatives. The review UI separately
  records subject-attribution and decision-role errors instead of collapsing
  them into a generic rejection.
- AnswerUnit primary types are 4 MARKET_CRITERION, 9 PROCEDURE, 4
  RULE_CONDITION and 1 DECISION_REASON. The single reviewed brand event carries
  both BRAND_CAPABILITY and DECISION_REASON facets. Section headings and
  operational text containing the word "选择" are no longer mislabeled as
  Decision Reasons.
- The frozen call plan is DeepSeek `deepseek-v4-flash`, at most 19 Citation
  Contribution requests, no automatic retry, no Answer or SourceClaim calls,
  conservative token ceiling 159,544 and reference budget ceiling RMB 1.2921.
  This is an authorization ceiling, not billed cost.
- Current state is `AWAITING_EXTERNAL_AUTHORIZATION`: external calls, cache
  hits, ResultVersion, dispositions, bindings and calibration Review are all
  zero or absent. P1 is not accepted and Strategy remains 0. A separate exact
  authorization is required before the worker may execute this plan.

## 2026-09-28 Citation Contribution P1 Authorized Execution

- Product Owner authorization was bound to Plan
  `citation-contribution-plan-1144c02d0a8eb1daf200`, DeepSeek
  `deepseek-v4-flash`, 19 maximum requests, zero retry and RMB 2 hard budget.
  The worker revalidated the exact input and plan hashes before execution.
- All 19 planned calls completed with 77,891 total tokens (55,421 prompt and
  22,470 completion), zero cache hits and a conservative RMB 0.6308 estimate.
  No Answer, SourceClaim, browser, fetch or Strategy operation ran.
- Strict admission rejected all 19 responses as `FAILED_SCHEMA`. Eighteen used
  a top-level `results` shape and one used `candidate_pairs`; the frozen
  contract requires `evaluations` plus `no_binding_reason`. No response was
  renamed, default-filled, cached as valid or converted into `NO_MATCH`.
- Immutable Result `contribution-v1:b59cacd86f3b4f37` records 19
  `FAILED/ANALYSIS_FAILED` Citation dispositions, zero evaluations, zero
  bindings and zero calibration targets. This is P1 failure, not a legal
  zero-contribution result. Empty calibration review and nine-Run expansion
  remain blocked; Strategy remains zero.
- Full provider and structured responses, request identities, contract/input
  hashes, validation results, token usage and rejection details were written
  to 19 non-Git artifacts with mode `0600`; all 19 artifact hashes were
  independently verified against the immutable result metadata.

## 2026-09-28 Citation Contribution Contract Recovery Checkpoint

- Classified as `IMPLEMENTATION_CHANGE`. The frozen Citation Contribution
  dimensions, candidate scope and immutable failed P1 output are unchanged.
- Offline audit proved the 19/19 failure was a generation-protocol drift: the
  typed response required `evaluations + no_binding_reason`, while production
  sent only Chat `json_object` and supplied no generated schema or valid nested
  example. The observed `results` field was not defined by repository prompt or
  example code; `candidate_pairs` was an input name copied into one output.
- `CitationContributionResponse` now generates the provider schema, prompt
  protocol block, validated positive/empty examples and strict local gate.
  Model output uses frozen indexes only; backend code validates and maps them
  to formal IDs.
- Added an opt-in DeepSeek Responses `json_schema` transport to the existing
  semantic client. All other callers keep their existing default Chat JSON
  behavior. Cache identity now includes structured-output mode, provider schema
  hash and transport version.
- Converted all 19 old response shapes into permanent rejection fixtures and
  added transport, schema, cross-field, dynamic frozen-input and cache-identity
  regression coverage.
- The new Plan contract contains a deterministic first-two Citation Canary. A
  failed Canary records the remaining scope as not evaluated and stops further
  model calls. No external call was made in this checkpoint.

## 2026-09-28 Citation Contribution Responses Model Identity

- Pre-execution verification against the current DeepSeek Responses API found
  that `deepseek-flash` is the canonical request model while the project still
  uses the accepted legacy alias `deepseek-v4-flash`.
- The Responses JSON Schema transport now records the requested alias,
  effective request model and provider `response.model`. Only the explicit
  Responses path maps the legacy Flash alias; existing Chat callers retain
  their configured model behavior.
- Plan and cache identities include both model identities and transport v2.
  Provider model mismatches are rejected rather than hidden. External input,
  output and total token usage are retained separately for the P1 execution
  report and the authorization now freezes a total-token ceiling.

## 2026-09-28 Citation Contribution P1 Contract-Recovery Execution

- Because the effective Responses API model is `deepseek-flash`, the release
  API superseded the unexecuted alias-only Plan and froze Contribution
  `citation-contribution-ceab7156-040a-4963-b8b6-635ab012d8e1`, Plan
  `citation-contribution-plan-21a110f41864ca59ba83`, Plan hash
  `21a110f41864ca59ba830e9c2bda820f72a9cbef65d40e9b8967c1d4b62e1ac9`
  and input snapshot hash
  `c3410c51be33e9b1b10c9f273af8306bc8ccb424504e6789a30728b0abd77419`.
  The semantic scope remains Run 1, 18 AnswerUnits, 19 Citations, 228
  candidate pairs and 34 recall controls.
- The first two fixed Citations passed provider completion, provider JSON
  Schema, strict local Schema and frozen-input dynamic validation. The worker
  therefore continued the remaining 17 calls under the same authorization.
- The 19 calls used requested alias `deepseek-v4-flash`, effective request
  model `deepseek-flash` and provider response model `deepseek-flash`. They
  consumed 67,154 input, 22,187 output and 89,341 total tokens, with zero cache
  hits. At the frozen peak-price ceiling this is an estimated RMB 0.7235, not a
  provider billing receipt.
- Sixteen responses were admitted and cached. Three were rejected and were not
  cached: references 4 and 13 returned spans for negative/no-correspondence
  candidates; reference 5 returned non-empty evaluations together with a
  non-null `no_binding_reason`. No field repair, default insertion or retry was
  used.
- Immutable Result `contribution-v1:dd80ec35eab9fe62`, output hash
  `7170f0f1471a5d0146bfc4043ed08a3543a33c371a7190aa1dc5b3cb93718998`
  and reviewable-set hash
  `04e7b00c2e1133c12d980a66687ab8ad8f527700626bec053bf1bcbe203e2fb9`
  record 16 DONE and 3 FAILED Citations, 192 accepted pair evaluations, 22
  bindings and 100% terminal-disposition coverage. The three failures remain
  `ANALYSIS_FAILED`, not `NO_MATCH` or `NO_SUPPORT`.
- All 192 accepted evaluations keep `answer_anchor=UNPROVEN` and
  `generation_influence=UNAVAILABLE`. The observed relations are 6
  `FAITHFUL_PARAPHRASE/SUPPORTS_PARTIAL`, 16
  `TOPICAL_ONLY/RELATED_ONLY` and 170 `NO_CORRESPONDENCE/NO_MATCH`.
- Nineteen complete response artifacts were retained outside Git with mode
  `0600`; all stored artifact hashes were independently rechecked. The 16
  admitted outputs are the only new valid cache entries.
- The frozen calibration set contains 40 deterministic hash-ordered unbiased
  evaluation samples and 20 hash-ordered recall-boundary controls. The release
  page exposes AnswerUnit context, source passage, machine dimensions,
  rationale, limitations and append-only human calibration controls. No Review
  was created and no nine-Run expansion or Strategy execution occurred.
- A release-page identity bug discarded the exact P1 Contribution query
  parameter when the same Diagnosis had a newer Evidence ResultVersion. The UI
  now preserves the independently version-bound Contribution when only the
  Diagnosis result changes; it still clears it when the Diagnosis identity
  itself changes.

## 2026-09-28 Citation Contribution P1 Human Calibration

- The immutable machine Result `contribution-v1:dd80ec35eab9fe62` and its
  frozen 40 unbiased Evaluation plus 20 Recall Boundary samples remain
  unchanged. No failed Citation was rerun and no external model call occurred.
- A read-only Human Calibration projection adds a census of all 22 machine
  Bindings. Four Bindings are already represented by the unbiased sample, so
  the real deduplicated review workload is 78 objects: the original 60 plus 18
  additional Binding targets. Identical pair identities can reuse one prior,
  non-conflicting Human Gold record across later diagnostic sets.
- Evaluation and Binding review now records correspondence, evidence relation,
  span validity, subject attribution, qualifier preservation, decision-role
  validity and a required comment. Recall Boundary review independently records
  correspondence, support, relatedness, candidate eligibility and miss reason;
  it does not inherit the machine relation.
- Review submission binds the immutable Contribution result, original
  reviewable-set hash, calibration sample identity, Binding Census hash and
  deduplicated Human Review set hash. It appends one Review and never mutates
  the machine Result.
- The resulting report separates Contract Reliability, Relation Quality and
  Recall Quality. It exposes the unbiased confusion matrix, Binding precision
  by relevant classes, independent error categories, boundary misses, major
  cases and the P1 recommendation without adding an arbitrary pass threshold.
- The release page exposes the complete source and AnswerUnit context needed
  for human judgment. Reading or refreshing the page creates no Review;
  Strategy and nine-Run Contribution remain unavailable at this checkpoint.

## 2026-09-28 Citation Contribution Calibration Entry

- The release API now exposes a read-only list of Citation Contribution
  executions scoped to the exact Analysis, Project and Prompt. It does not
  select a latest execution and does not create or mutate a Review.
- The current-analysis progress card shows pending P1 Human Calibration and
  opens the selected exact Contribution while preserving its identity in the
  URL. The lower P1 card also lists existing executions instead of presenting
  an existing result as though a new plan were required.
- The 78 Human Gold decisions are explicitly presented as the one-time P1
  calibration workload: 40 unbiased evaluations, 20 recall-boundary controls
  and 18 additional deduplicated Binding Census objects. They are not a
  per-analysis production review requirement.
