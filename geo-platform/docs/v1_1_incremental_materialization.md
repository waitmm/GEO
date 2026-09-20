# V1.1 Incremental Materialization

Status: PHASE_C1_ALIGNMENT_MATERIALIZATION
Date: 2026-09-02

## Goal

V1.1 Incremental Materialization changes expensive analysis from Run-driven
recomputation to semantic-object-driven materialization:

```text
CURRENT PROMPT RUN SCOPE
-> REQUIRED_OBJECT_SET
-> EXISTING_OBJECT / VERSION / CONTRACT CHECK
-> MISSING / STALE ONLY
-> CHEAP RE-AGGREGATION
```

The performance target is that repeated Runs increase observation and lineage
coverage, but do not linearly increase SourceClaim or EvidenceAlignment LLM
work.

## Non-Goals

This phase must not change Product Truth, SUPPORTS / NO_SUPPORT /
CONTRADICTS semantics, AnswerUnit semantics, Evidence Package scope, Benchmark,
Gap, Citation Decision Value, Strategy Channel Resolver, Step 7, Step 8,
StrategyCandidate business meaning, human review rules, or historical object
immutability.

Performance optimization is not semantic migration.

## Principles

1. Compute by semantic object, not by Run.
2. Binding first, recall fallback.
3. Reuse by materialization contract, not raw implementation version.
4. Source freshness is not semantic staleness.
5. Single-flight materialization for each expensive key.
6. Performance optimization must not change evidence semantics.

## Semantic Object vs Observation

Run-level rows remain observation and lineage. Expensive outputs should be keyed
by semantic identity:

```text
Observation -> Semantic Object -> Materialized Result
```

Examples:

- repeated AnswerUnits with the same resolved proposition share one semantic
  identity;
- repeated SourceClaims for the same document passage and grounded claim text
  share one semantic identity;
- repeated AnswerUnit + SourceClaim pairs share one alignment materialization.

Run IDs, citation IDs, observed coverage, and Evidence Package membership are
still bound back to the current context. Semantic reuse is allowed; scope reuse
is not.

## Materialization Contracts

Phase A introduces read-only contract names:

```text
ANSWER_UNIT_SEMANTIC_V1
SOURCE_CLAIM_V1
ALIGNMENT_V1
```

Implementation version, prompt version, and model remain observable metadata.
Only a true semantic contract change should make historical materialization
stale. Parser/logging/retry changes that do not change the required semantic
fields should remain reusable.

## Source Snapshot Freshness

Source freshness is checked before downstream semantic staleness:

```text
snapshot stale
-> refetch / revalidate
-> compare content_hash
```

If the content hash is unchanged, Passage, SourceClaim, and EvidenceAlignment
should remain reusable. Phase A only reports snapshot status; it does not fetch
or update pages.

## Planner

Phase A implements a read-only planner:

```text
GET /api/optimization/workflow/{project_id}/{prompt_id}/materialization-plan
```

Optional query parameters:

```text
run_ids=<id>&run_ids=<id>
top_k=5
```

The planner reports:

- Run Scope from the active Evidence Package, or explicit run IDs when passed;
- AnswerUnit raw observations and semantic objects;
- observed citation records, unique canonical URLs, required SourceDocuments,
  missing documents, and snapshot state;
- required passages derived from current SourceDocuments;
- SourceClaim hits, misses, duplicate rows, missing unique LLM inputs, and LLM
  cache hits;
- EvidenceAlignment naive pairs, bound pairs, fallback pairs, hard-filtered
  pairs, recall candidates, cache hits, missing pairs, and LLM required;
- reuse rates and LLM amplification ratio.

Planner states include:

```text
HIT
MISSING
IN_PROGRESS
STALE_CONTENT
STALE_SCHEMA
STALE_MODEL
STALE_PROMPT
STALE_SOURCE_SNAPSHOT
FAILED_RETRYABLE
FAILED_FINAL
INVALID
```

Phase A does not call LLM, mutate rows, fetch sources, regenerate claims,
regenerate alignments, or create StrategyCandidate / Action / Experiment rows.

`source_claims.missing` is a passage-row count. `missing_unique_llm_inputs` and
`lookup_first_llm_required` are the performance planning counts; these are the
fields to use when estimating external SourceClaim LLM work.

## Recall Ladder

The target Alignment candidate builder is:

```text
L0 EXPLICIT_BINDING
L1 ANSWER_CONTEXT
L2 RUN_SCOPE_RECALL
L3 PROMPT_SCOPE_RECALL
```

Phase A only reports a deterministic planner estimate. Production
EvidenceAlignment generation is not rewired until Phase C.

Query intent and embeddings must not become EvidenceAlignment semantic keys.
Embeddings may later rank recall candidates, but they are not stable business
identity.

## Single-Flight / Lease

Later phases should use database-first single-flight:

```text
materialization_key
status
owner_id
started_at
lease_expires_at
attempt_count
```

Phase A does not add these columns or locks. It only exposes how many expensive
keys would be eligible for de-duplication.

## Regression Standards

#19 is the primary regression case for current-scope materialization:

- no full-library SourceClaim scan;
- no `doc_id_filter=[]` expansion into all documents;
- evidence review remains semantic-group based;
- repeated reruns should not significantly increase LLM work.

#40 is the primary regression case for current-vs-history isolation:

- current Prompt consumes only current Run Scope;
- semantic cache hits may be reused, but Evidence Package and StrategyCandidate
  membership are rebound to the current context;
- historical audit/regression candidates do not light Step 7/8.

## Phase A Verification

The first implementation checkpoint adds the read-only planner and tests. Real
#19 / #40 numbers must be captured from the API before entering Phase B.

Current local baseline captured on 2026-09-02:

```text
#19: run_count=40
     SourceClaim lookup_first_llm_required=1385
     EvidenceAlignment naive_pairs=9666
     EvidenceAlignment after_recall=188
     EvidenceAlignment actual_llm_required=169
     primary_bottleneck=SOURCE_CLAIM

#40: run_count=6
     SourceClaim lookup_first_llm_required=529
     EvidenceAlignment naive_pairs=230
     EvidenceAlignment after_recall=65
     EvidenceAlignment actual_llm_required=15
     primary_bottleneck=SOURCE_CLAIM
```

## Phase B SourceClaim Materialization

Phase B rewires the real SourceClaim execution path, and only that path, from
passage-row-driven extraction to lookup-first materialization.

The new ledger is:

```text
source_claim_materializations
```

It is a SourceClaim-specific extraction ledger, not a generic cache framework.
It has a unique `materialization_key` and records:

```text
passage_content_hash
contract_version
status
claim_count
output_payload_json
source_claim_ids_json
observed_source_document_ids_json
observed_passage_ids_json
extractor_impl_version
prompt_version
schema_version
provider / model
attempt_count
started_at / completed_at
```

The materialization key is based on the exact semantic input currently sent to
the SourceClaim extractor:

```text
hash(SOURCE_CLAIM_V1 + normalized passage text hash)
```

It must not include `run_id`, `prompt_id`, `evidence_package_id`, or
`SourceClaim.id`.

The current real SourceClaim LLM input is:

```text
system_prompt = SOURCE_CLAIM_SYSTEM
user_payload = {"passage": normalize_source_claim_extraction_input(passage_text)}
prompt_version = source_claim.v1
schema_version = v1
model = settings.deepseek_model
```

`normalize_source_claim_extraction_input(...)` currently applies only
`strip()`. The LLM is not given `document.title`, URL, heading, section, source
metadata, Prompt text, Run ID, target brand, or evidence context.

Document URL/domain are used after extraction for ownership provenance and
referential subject normalization, for example mapping `该工具` to the current
source owner. That post-processing can vary per document and belongs to
SourceClaim row binding, not to the extraction materialization identity.

Execution now follows:

```text
required passage rows
-> group by materialization_key
-> compatible DONE ledger hit: reuse output
-> completed zero-claim ledger hit: reuse empty output
-> safe legacy row: backfill DONE ledger and reuse
-> missing / stale / failed: call existing SourceClaimJudge once
-> persist DONE ledger and 0..N SourceClaims idempotently
```

Zero-claim results are first-class DONE materializations:

```text
status=DONE
claim_count=0
output_payload_json={"claims":[]}
```

Legacy SourceClaim rows can be backfilled only when the existing rows carry the
current SourceClaim prompt/schema metadata and are not older than the current
SourceDocument snapshot metadata. If that cannot be established, the planner and
executor must treat the passage as requiring materialization rather than guess a
false HIT.

Legacy detection is a migration bridge, not a permanent second cache. The
runtime rule is:

```text
safe legacy SourceClaim rows
-> deterministic compatibility validation
-> backfill source_claim_materializations as DONE
-> future reuse comes through ledger HIT
```

Implementation metadata such as `extractor_impl_version` is recorded for audit
but does not invalidate a compatible `SOURCE_CLAIM_V1` ledger. A contract break
must return `STALE_SCHEMA` / incompatible behavior and materialize under a new
key while preserving old records for audit.

## Phase B Closure Check

Captured from the local real database on 2026-09-02 before the attempted
production LLM smoke:

```text
#19
missing_total=1393
missing_llm_required=1385
missing_llm_call_cache_hit=8
missing_no_external_llm_breakdown={
  llm_call_cache_hit: 8,
  invalid_input: 0,
  empty_content: 0,
  deduped_elsewhere: 0
}
object_conservation: 1462 = 0 materialization_hit + 69 legacy_reuse + 1393 missing
is_balanced=true

#40
missing_total=537
missing_llm_required=529
missing_llm_call_cache_hit=8
missing_no_external_llm_breakdown={
  llm_call_cache_hit: 8,
  invalid_input: 0,
  empty_content: 0,
  deduped_elsewhere: 0
}
object_conservation: 547 = 0 materialization_hit + 10 legacy_reuse + 537 missing
is_balanced=true
```

The fixed `8` delta for both prompts is therefore explained: these keys are
missing from the SourceClaim materialization ledger but already have matching
`LLMCallCache` entries for the same SourceClaim LLM input hash, so they do not
require a new external LLM call.

After a production-smoke attempt without external network approval, the service
created 9 retryable ledger rows rather than silently dropping objects:

```text
#19: MISSING=1388, LEGACY_REUSABLE=69, FAILED_RETRYABLE=5
#40: MISSING=533, LEGACY_REUSABLE=10, FAILED_RETRYABLE=4
ledger_status_counts={FAILED_RETRYABLE: 9}
```

This keeps object conservation balanced. Phase B is conditionally accepted and
implementation-frozen because the only missing check was blocked by environment
policy rather than by a product or code failure:

```text
Phase B Implementation: FROZEN
Phase B Automated Tests: PASS
Phase B Planner Conservation: PASS
Phase B Production Smoke: BLOCKED_EXTERNAL_POLICY
Phase B Overall: CONDITIONALLY_ACCEPTED
```

The deferred verification item remains open and must not be deleted:

```text
PHASE_B_PRODUCTION_SMOKE_DEFERRED
```

Final production-smoke closure still requires an approved small external LLM
check:

```text
#19 and #40 each choose up to 5 current external-LLM-required keys
first run: DONE ledger rows are written through SourceClaimJudge
second run with the same keys: actual_source_claim_llm_calls=0 and ledger HIT
LLMCallCache recovery: cache hit writes SourceClaimMaterialization DONE, then next run is ledger HIT
```

## Phase C1 EvidenceAlignment Materialization

Phase C1 rewires EvidenceAlignment verdict reuse only. It does not change the
candidate generator, Binding-aware Recall execution, Benchmark, Gap, Strategy,
Step 7, or Step 8.

The current real EvidenceAlignment LLM input is:

```text
system_prompt = ALIGNMENT_SYSTEM
user_payload = {
  "reason": normalize_alignment_reason_text(reason_text),
  "source_claim": normalize_alignment_source_claim_text(source_claim_text)
}
prompt_version = evidence_alignment.v1
schema_version = v1
model = settings.deepseek_model
```

The LLM is not given Run ID, Evidence Package ID, StrategyCandidate ID, raw
AnswerUnit row ID, raw SourceClaim row ID, Prompt Intent, Prompt Intent
Embedding, citation prominence, Benchmark, Gap, or experiment context.

`reason_scope / reason_entity` and the resolved SourceClaim proposition fields
are included in the semantic materialization identity because they affect
precheck eligibility or the semantic pair being judged. Prompt Intent remains
excluded:

```text
FACT SUPPORT != QUERY-RELATIVE DECISION RELEVANCE
```

The new ledger is:

```text
evidence_alignment_materializations
```

It records:

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

Execution now follows:

```text
current candidate pair
-> build ALIGNMENT_V1 materialization key
-> compatible DONE ledger hit: reuse verdict
-> safe legacy EvidenceAlignment row: backfill DONE ledger and reuse
-> LLMCallCache hit: recover payload, write DONE ledger, reuse
-> missing / failed: call existing EvidenceAlignmentJudge once
-> persist DONE ledger and current EvidenceAlignment observation rows
```

All judge verdicts are successful materializations when the LLM call succeeds:

```text
SUPPORTS
NO_SUPPORT / NONE
RELATED
CONTRADICTS
```

A non-support verdict must still be `status=DONE`; otherwise reruns would keep
calling LLM merely because the result does not support the reason.

Current local read-only C1 planner baseline captured on 2026-09-03:

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

Phase C2 remains not started. Planner recall numbers are still estimates unless
and until C2 explicitly wires candidate generation.

## Phase C2-A Binding-aware Candidate Builder Shadow

Phase C2-A starts the candidate-builder cutover work in shadow mode only. It
does not change `run_evidence_alignment(...)`, does not alter formal
EvidenceAlignment execution, and does not change Benchmark, Gap, Strategy,
Step 7, or Step 8.

The planner now reports:

```text
evidence_alignment.candidate_builder_shadow
```

It compares two candidate sets at the same semantic identity grain used by C1:

```text
current_builder = production_all_viable_pairs.v1
proposed_builder = binding_aware_candidate_builder.v1
identity = ALIGNMENT_V1 materialization_key
```

`current_builder` models the current production execution candidate set:

```text
all semantic reasons
× all current scoped SourceClaims
minus UNKNOWN subjects
minus deterministic COMPETITOR_CONTEXT pairs
```

`proposed_builder` models the binding-aware plan:

```text
explicit Run/ReferenceSource document binding first
-> hard entity/scope precheck
-> fallback prompt-scope lexical recall only for unbound or weak-bound reasons
-> TopK
```

The output is strictly diagnostic:

```text
cutover_enabled=false
current_candidate_keys
proposed_candidate_keys
shared_candidate_keys
old_only_candidate_keys
new_only_candidate_keys
old_only_existing_verdict_row_counts
old_only_supports_contradicts_row_count
old_only_supports_contradicts
old_only_requires_review_before_cutover
```

`old_only_supports_contradicts` is grouped by unique semantic
`materialization_key + relation`; each item carries all matching row-level
`alignment_ids` so cutover review can audit the full historical impact without
confusing duplicate Run observations for different semantic candidates.

Local shadow comparison captured on 2026-09-03:

```text
#19 / Evidence Package #12 v8 / 40 Runs
current_candidate_keys=583
proposed_candidate_keys=188
shared_candidate_keys=188
old_only_candidate_keys=395
new_only_candidate_keys=0
old_only_existing_verdict_row_counts={
  CONTRADICTS: 24,
  NONE: 1465,
  RELATED: 2220,
  SUPPORTS: 336
}
old_only_supports_contradicts_row_count=360
old_only_supports_contradicts_count=15
old_only_requires_review_before_cutover=true

#40 / Evidence Package #15 v2 / 6 Runs
current_candidate_keys=65
proposed_candidate_keys=65
shared_candidate_keys=65
old_only_candidate_keys=0
new_only_candidate_keys=0
old_only_supports_contradicts_row_count=0
old_only_supports_contradicts_count=0
old_only_requires_review_before_cutover=false
```

Cutover is blocked until #19's 15 old-only SUPPORTS/CONTRADICTS semantic pairs
are reviewed and either accepted as safe removals or promoted into a proposed
recall rule.

## Phase C2-A.1 Critical Recall Loss Diagnosis

Phase C2-A.1 remains shadow-only. It adds diagnostic trace fields for #19's 15
critical old-only semantic pairs without changing formal EvidenceAlignment
execution and without calling LLM.

The trace now records, where available:

```text
reason semantic key
source_claim semantic key
alignment verdict and review status
SourceClaim review status
source_document_id
citation_ids
observed_run_ids
current candidate membership source
binding_status
explicitly_bound_to_answer_unit
same_answer_context
same_run_observed_source
in_current_prompt_scope
citation_anchor_available
hard_filter_result / hard_filter_reason
lexical_score
BM25_score
semantic_score
combined_candidate_score
rank_before_topk
top_k
proposed_recall_level
final_exclusion_reason
diagnosis_classification
proposed_fix_layer
```

Unavailable fields are explicit, not guessed:

```text
BM25_score=unavailable
semantic_score=unavailable
structural_passage_distance=unavailable
section_relation=unavailable
same_answer_context=unavailable
```

Local #19 diagnosis captured on 2026-09-03:

```text
current_candidate_keys=583
proposed_candidate_keys=188
shared=188
old_only=395
new_only=0

critical_old_only=15 semantic groups / 360 row-level alignments
TRUE_POSITIVE_RECALL_LOSS=1
LEGACY_UNPROVEN_CROSS_PRODUCT=14
LEGACY_ALIGNMENT_FALSE_POSITIVE=0
AMBIGUOUS_REQUIRES_HUMAN_REVIEW=0

Exclusion Reasons:
TOPK_TRUNCATION=10
BELOW_SCORE_THRESHOLD=5

Recall Paths:
L0_EXPLICIT=107
L1_ANSWER_CONTEXT=0
L2_RUN_SCOPE=0
L3_PROMPT_SCOPE=81

TopK:
L0_EXPLICIT_topk_applied=false
L1_ANSWER_CONTEXT_topk_applied=false
L2_RUN_SCOPE_topk_applied=false
L3_PROMPT_SCOPE_topk_applied=true
```

Reason-cluster diagnosis:

```text
可以自动生成加密短链:
  current_candidates=61
  proposed_candidates=5
  current_SUPPORTS=96
  current_CONTRADICTS=0
  proposed_retained_SUPPORTS=72
  proposed_retained_CONTRADICTS=0
  critical_old_only=1

可以规避平台拦截:
  current_candidates=61
  proposed_candidates=5
  current_SUPPORTS=168
  current_CONTRADICTS=24
  proposed_retained_SUPPORTS=0
  proposed_retained_CONTRADICTS=0
  critical_old_only=8

支持加粉数据回传优化投放效果:
  current_candidates=61
  proposed_candidates=5
  current_SUPPORTS=216
  current_CONTRADICTS=0
  proposed_retained_SUPPORTS=72
  proposed_retained_CONTRADICTS=0
  critical_old_only=6
```

Interpretation:

- TopK is not being applied to L0 explicit binding.
- Proposed is currently a pruning-only builder: `new_only=0`.
- L1 Answer Context and L2 Run Scope are not active in the shadow candidate set.
- The 14 machine-only critical groups have no same-run citation anchor and no
  AnswerUnit binding context; they are classified as
  `LEGACY_UNPROVEN_CROSS_PRODUCT`.
- The one HUMAN_CONFIRMED group is a real C2-B blocker:

```text
reason=可以自动生成加密短链
claim_id=267
claim=商加加系统生成的加密跳转链接能够避免因为进行导流而触发风控
relation=SUPPORTS
final_exclusion_reason=TOPK_TRUNCATION
rank_before_topk=6
top_k=5
```

Do not enter C2-B cutover until this true-positive recall loss is addressed by
a generalized recall rule or an explicit human decision. Do not fix it with a
pair whitelist or a blind TopK increase.

## Phase C2-A.2 Final Shadow Validation

Phase C2-A.2 keeps the system in shadow mode. It does not change formal
`run_evidence_alignment(...)`, does not call LLM, and does not delete or mutate
historical EvidenceAlignment rows.

Source context re-audit of the only HUMAN_CONFIRMED blocker:

```text
reason=可以自动生成加密短链
SourceClaim #267=商加加系统生成的加密跳转链接能够避免因为进行导流而触发风控
original_verdict=SUPPORTS
original_review_status=HUMAN_CONFIRMED
new_audit_decision=TRUE_POSITIVE_RECALL_LOSS
```

The source passage contains the missing key qualifier:

```text
系统会自动生成加密的跳转链接
```

Therefore #267 is not a legacy false positive. It is a real recall-loss blocker
for C2-B.

The 14 remaining critical old-only groups are renamed to:

```text
LEGACY_UNPROVEN_CROSS_PRODUCT
```

They are machine-only, have no same-run citation anchor, and have no
AnswerUnit context. This is a neutral diagnosis: the planner does not claim the
old verdicts are false, only that they are unproven prompt-scope cross-product
relations and should not force a future candidate-builder rule.

L1 / L2 ladder validation:

```text
L1 status=L1_UNAVAILABLE_BY_SCHEMA
reason=AnswerUnit rows expose normalized unit text and binding ids, but the
current schema does not store reliable sentence/paragraph-level citation
co-location.

L2 status=L2_IMPLEMENTED_MATCH
```

The proposed shadow ladder now short-circuits:

```text
L0 Explicit Binding
-> L1 Answer Context (unavailable by schema)
-> L2 Run Scope
-> L3 Prompt Scope only when L2 has no viable candidate
```

It no longer jumps directly from missing/weak binding into full prompt-scope
recall.

Final #19 shadow captured on 2026-09-03:

```text
current_candidate_keys=583
proposed_candidate_keys=79
shared=79
old_only=504
new_only=0

critical_old_only=15 semantic groups / 360 row-level alignments
TRUE_POSITIVE_RECALL_LOSS=1
LEGACY_ALIGNMENT_FALSE_POSITIVE=0
LEGACY_UNPROVEN_CROSS_PRODUCT=14
LEGACY_SCOPE_ARTIFACT=0
HUMAN_REVIEW_REQUIRED=0

Recall:
L0=0
L1=0
L2=28
L3=51

Fallback triggers:
binding_missing=27
binding_low=0
no_viable_candidate=20
below_threshold=1
```

The true-positive blocker's L3 score details:

```text
rank=6
score=0.2222
rank_5_score=0.2222
score_delta_to_cutoff=0.0
threshold=0.01
number_above_threshold=26
```

Policy simulation:

```text
Policy A: Hard TopK=5
candidate_count=79
critical_recall_loss=1
external_llm_estimate=60

Policy B: keep candidates above threshold with fallback max cap=25
candidate_count=145
critical_recall_loss=0
external_llm_estimate=69

Policy C: TopK + score-margin 0.05 around Kth candidate
candidate_count=92
critical_recall_loss=0
external_llm_estimate=61
```

Final #40 shadow:

```text
current_candidate_keys=65
proposed_candidate_keys=65
shared=65
old_only=0
new_only=0
critical_old_only=0
L1 status=L1_UNAVAILABLE_BY_SCHEMA
L2 status=L2_IMPLEMENTED_NO_TRIGGER
```

C2-B remains blocked because #19 still has one true-positive recall loss. The
right next fix must be generalized, such as a score-margin policy around the
TopK cutoff or another recall-layer rule. Do not use a HUMAN_CONFIRMED
whitelist, pair whitelist, or blind TopK increase.

## Phase C2-A.3 Final Cutover Gate

Phase C2-A.3 remains shadow-only. It does not change formal
`run_evidence_alignment(...)`, does not call LLM, does not write
EvidenceAlignment rows, and does not recompute formal Benchmark / Gap /
Strategy.

The final blocker was diagnosed as a TopK boundary tie, not a ladder failure:

```text
reason=可以自动生成加密短链
claim_id=267
rank=6
score=0.2222
cutoff_score=0.2222
tie_bucket_rank_range=5..10
tie_bucket_size=6
```

The proposed shadow policy is:

```text
POLICY_D_TOPK_WITH_BOUNDARY_TIES
```

It keeps the plain TopK candidates and additionally keeps every candidate in
the same score bucket as the Kth candidate. The score bucket is the current
planner's rounded 4-decimal candidate score with an explicit epsilon. This
avoids using candidate id, insertion order, or database row order to choose
among equal-score candidates.

Real DB final shadow on 2026-09-03:

```text
#19
current_candidate_keys=583
proposed_candidate_keys=92
shared=92
old_only=491
new_only=0

Policy A: candidates=79, TRUE_POSITIVE_RECALL_LOSS=1, external_llm_estimate=60
Policy B: candidates=145, TRUE_POSITIVE_RECALL_LOSS=0, external_llm_estimate=69, LEGACY_UNPROVEN retained=7
Policy C: candidates=92, TRUE_POSITIVE_RECALL_LOSS=0, external_llm_estimate=61, LEGACY_UNPROVEN retained=3
Policy D: candidates=92, TRUE_POSITIVE_RECALL_LOSS=0, external_llm_estimate=61, LEGACY_UNPROVEN retained=3

Recall:
L0=0, L0 status=L0_IMPLEMENTED_NO_MATCH
L1=0, L1 status=L1_UNAVAILABLE_BY_SCHEMA
L2=28, L2 status=L2_IMPLEMENTED_MATCH
L3=64

Boundary ties:
reasons_with_boundary_ties=5
max_tie_bucket=10
p50_tie_bucket=6
p90_tie_bucket=10
coarse_score_tie_risk=false

Shadow downstream:
Evidence changed=true
Benchmark core changed=false
Gap changed=false
Strategy changed=false
C2_CUTOVER_READY=true
cutover_allowed=false
```

`Evidence changed=true` means 11 old-only SUPPORTS/CONTRADICTS semantic groups
remain outside the selected Policy D set and are classified as
`LEGACY_UNPROVEN_CROSS_PRODUCT`. They do not change eligible Benchmark core
fields in this read-only shadow: primary benchmark, secondary benchmark, support
document counts, and tier counts are unchanged.

```text
#40
current_candidate_keys=65
proposed_candidate_keys=65
shared=65
old_only=0
new_only=0

Policy A/B/C/D: candidates=65, TRUE_POSITIVE_RECALL_LOSS=0, external_llm_estimate=15

Recall:
L0=65, L0 status=L0_IMPLEMENTED_MATCH
L1=0, L1 status=L1_UNAVAILABLE_BY_SCHEMA
L2=0, L2 status=L2_IMPLEMENTED_NO_TRIGGER
L3=0

Shadow downstream:
Evidence changed=false
Benchmark core changed=false
Gap changed=false
Strategy changed=false
C2_CUTOVER_READY=true
cutover_allowed=false
```

The earlier `L0=107 -> 0` change for #19 is classified as
`SHADOW_LOGIC_CHANGED_AS_DESIGNED`: the earlier diagnostic bucket counted broad
run-local binding-like candidates, while C2-A.2/C2-A.3 uses strict ladder
ownership where L0 only means high/medium explicit AnswerDecisionBinding.

C2-A.3 passes the shadow cutover gate, but still does not perform cutover.

## Phase C2-B Production Candidate Builder Cutover

Phase C2-B switches formal EvidenceAlignment candidate membership to the shared
Binding-aware Candidate Builder with `POLICY_D_TOPK_WITH_BOUNDARY_TIES`.

Scope of the cutover:

- `run_evidence_alignment(...)` now uses the same deterministic candidate
  builder as the planner when
  `use_binding_aware_alignment_candidates_v1_1=true` (default).
- The rollback path is available by setting
  `use_binding_aware_alignment_candidates_v1_1=false`; it preserves the frozen
  legacy all-viable-pairs behavior.
- Candidate membership changes only. Alignment judge prompt/version,
  materialization key, C1 ledger lookup-first semantics, legacy recovery, and
  LLMCallCache recovery are unchanged.
- Existing `EvidenceAlignment` rows are not prompt-wide deleted on the cutover
  path. Current candidate observation rows are reused by deterministic row
  signature; old-only historical rows and human review metadata are preserved.
- `candidate_dry_run=true` exposes production candidate keys and recall-layer
  counters without writing rows or calling the LLM.

Production dry validation on the real local DB:

```text
#19
planner_mode=PRODUCTION_CUTOVER
planner_policy=POLICY_D_TOPK_WITH_BOUNDARY_TIES
production_candidate_keys=92
planner_vs_production_diff=0
claim_267_present=true
Recall: L0=0, L1=0, L2=28, L3=64
L1 status=L1_UNAVAILABLE_BY_SCHEMA
L2 status=L2_IMPLEMENTED_MATCH

#40
planner_mode=PRODUCTION_CUTOVER
planner_policy=POLICY_D_TOPK_WITH_BOUNDARY_TIES
production_candidate_keys=65
planner_vs_production_diff=0
Recall: L0=65, L1=0, L2=0, L3=0
L1 status=L1_UNAVAILABLE_BY_SCHEMA
L2 status=L2_IMPLEMENTED_NO_TRIGGER
```

Phase C2-B is a production candidate-builder cutover only. It does not start
Phase D and does not modify Benchmark, Gap, Strategy, Step 7, or Step 8.

## Phase D Materialization Execution Reliability

Phase D adds execution guardrails on top of the existing SourceClaim and
EvidenceAlignment materialization ledgers. It does not create a new cache or a
new business materialization model.

Implementation:

- Reuses `source_claim_materializations` and
  `evidence_alignment_materializations` as the only materialization truth.
- Adds minimal execution fields to both ledgers:
  `owner_id` and `lease_expires_at`. Existing `status`, `attempt_count`,
  `error_message`, `started_at`, `completed_at`, and `updated_at` are reused.
- Adds `materialization_executor.py` for shared claim/lease/wait/retry helpers.
  It does not know SourceClaim extraction or EvidenceAlignment verdict
  semantics.
- `use_materialization_executor_v1_1=true` enables the Phase D executor path.
  The frozen legacy execution path remains available as a short rollback.
- `materialization_lease_seconds`,
  `materialization_wait_timeout_seconds`,
  `materialization_poll_interval_seconds`,
  `materialization_batch_size`,
  `materialization_max_attempts`, and
  `max_external_llm_concurrency` are configuration values.

Execution semantics:

```text
DONE -> HIT
FAILED_FINAL -> no retry
IN_PROGRESS + valid lease -> wait / return owned-by-other
MISSING or FAILED_RETRYABLE -> atomic claim
IN_PROGRESS + expired lease -> reclaim same row
```

Legacy SourceClaim and EvidenceAlignment recovery now converges through the
same claimed ledger row when the executor is enabled. LLMCallCache recovery is
still a recovery source only; successful recovery writes DONE to the
materialization ledger and future runs hit the ledger.

Validation:

```text
same materialization_key, 10 workers -> 1 ledger row, 1 owner external section
100 duplicate work items -> 1 unique job, 1 batch
10 distinct keys, max_concurrency=2 -> observed max concurrency <= 2
valid lease -> second worker external calls 0
expired lease -> same row reclaimed, attempt_count += 1
crash/resume -> existing DONE rows hit, expired IN_PROGRESS reclaimed
FAILED_RETRYABLE -> same row retries then DONE
FAILED_FINAL -> no ordinary retry
SourceClaim zero-claim DONE -> second run skips LLM
EvidenceAlignment NO_SUPPORT DONE -> second run skips LLM
```

Real local DB candidate regression after Phase D:

```text
#19: candidate_keys=92, planner_diff=0, claim_267=true, dry_run_writes=0
#40: candidate_keys=65, planner_diff=0, dry_run_writes=0
```

External DeepSeek production concurrency smoke remains deferred when the local
environment disallows external LLM access.
