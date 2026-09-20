# GEO V1.1 Final Acceptance

Generated at: 2026-09-03T12:18:45.801036

Architecture: Phase A/B/C1/C2/D/E

## Prompt #19

- Runs: 40 from ACTIVE_EVIDENCE_PACKAGE (Evidence Package #12 v8)
- Candidate keys: 92
- Planner vs Production candidate diff: 0
- SourceClaim required/hits/external calls: 1462 / 0 ledger hit + 69 legacy / 1385
- SourceClaim recovery: 8 LLMCallCache hits, 5 retryable, 0 final failed
- Alignment naive/candidates/hits/external calls: 9666 / 92 / 0 ledger hit + 31 legacy / 61
- Recall: {'L0_EXPLICIT': 0, 'L1_ANSWER_CONTEXT': 0, 'L2_RUN_SCOPE': 28, 'L3_PROMPT_SCOPE': 64}
- Benchmark: {'eligible_alignment_rows': 0, 'source_documents_with_eligible_evidence': 0, 'source_documents_with_support': 0, 'source_documents_with_contradiction': 0, 'primary_benchmark_count': 0, 'secondary_benchmark_count': 0, 'reference_only_count': 0, 'not_evaluable_count': 0, 'tier_counts': {}, 'ineligible_alignment_counts': {'LEGACY_RELATION_ONLY': 652, 'MISSING_ANSWER_UNIT': 652, 'MISSING_DECISION_BINDING': 652, 'SOURCE_NOT_REFERENCED_IN_RUN': 652}}
- Gap: {'snapshot_id': 10, 'gap_count': 2, 'dominant_gap': 'CANDIDATE_INCLUSION_GAP', 'gap_types': ['CANDIDATE_INCLUSION_GAP', 'RECOMMENDATION_GAP'], 'capability_gaps': [], 'status': 'NOT_RECOMPUTED_READ_ONLY', 'input_evidence_changed': True, 'input_benchmark_changed': False}
- Strategy: {'candidate_exists': True, 'candidate_id': 39, 'strategy_type': 'VIDEO_CONTENT', 'priority_capability': '', 'planned_channel': 'DOUYIN', 'resolver_output': 'DOUYIN', 'state': 'ACCEPTED', 'generation_status': 'GENERATED', 'status': 'NOT_RECOMPUTED_READ_ONLY', 'input_evidence_changed': True, 'input_benchmark_changed': False}
- Workflow: Step 7=NOT_READY, Step 8=LOCKED
- Durations: planner=72026 ms, production dry-run=3802 ms, total=75828 ms

## Prompt #40

- Runs: 6 from ACTIVE_EVIDENCE_PACKAGE (Evidence Package #15 v2)
- Candidate keys: 65
- Planner vs Production candidate diff: 0
- SourceClaim required/hits/external calls: 547 / 0 ledger hit + 10 legacy / 529
- SourceClaim recovery: 8 LLMCallCache hits, 4 retryable, 0 final failed
- Alignment naive/candidates/hits/external calls: 230 / 65 / 0 ledger hit + 50 legacy / 15
- Recall: {'L0_EXPLICIT': 65, 'L1_ANSWER_CONTEXT': 0, 'L2_RUN_SCOPE': 0, 'L3_PROMPT_SCOPE': 0}
- Benchmark: {'eligible_alignment_rows': 66, 'source_documents_with_eligible_evidence': 1, 'source_documents_with_support': 1, 'source_documents_with_contradiction': 0, 'primary_benchmark_count': 1, 'secondary_benchmark_count': 0, 'reference_only_count': 0, 'not_evaluable_count': 0, 'tier_counts': {'PRIMARY_BENCHMARK': 1}, 'ineligible_alignment_counts': {'LEGACY_RELATION_ONLY': 234}}
- Gap: {'snapshot_id': None, 'gap_count': 0, 'dominant_gap': None, 'gap_types': [], 'capability_gaps': [], 'status': 'NOT_RECOMPUTED_READ_ONLY', 'input_evidence_changed': False, 'input_benchmark_changed': False}
- Strategy: {'candidate_exists': True, 'candidate_id': 50, 'strategy_type': 'UNRESOLVED', 'priority_capability': '', 'planned_channel': 'UNRESOLVED', 'resolver_output': 'UNRESOLVED', 'state': 'PENDING_REVIEW', 'generation_status': 'GENERATED', 'status': 'NOT_RECOMPUTED_READ_ONLY', 'input_evidence_changed': False, 'input_benchmark_changed': False}
- Workflow: Step 7=PENDING_REVIEW, Step 8=LOCKED
- Durations: planner=4160 ms, production dry-run=800 ms, total=4960 ms

## Immediate Rerun

- SourceClaim external calls: 1914
- Alignment external calls: 76
- Status: DEFERRED_BY_ENVIRONMENT_POLICY
- Duration: not_run

## Duplicate Run Stress

- 1 Runs: SourceClaim unique jobs=1, Alignment unique jobs=1, expensive semantic work delta=2
- 10 Runs: SourceClaim unique jobs=1, Alignment unique jobs=1, expensive semantic work delta=0
- 100 Runs: SourceClaim unique jobs=1, Alignment unique jobs=1, expensive semantic work delta=0

## Citation Stress

- 50 citations: naive pairs=1000, final candidates=100, LLM amplification ratio=0.1
- 100 citations: naive pairs=2000, final candidates=100, LLM amplification ratio=0.05
- 500 citations: naive pairs=10000, final candidates=100, LLM amplification ratio=0.01

## Reliability

- Single-flight: PASS_BY_PHASE_D_TESTS
- Lease: PASS_BY_PHASE_D_TESTS
- Retry: PASS_BY_PHASE_D_TESTS
- Resume: PASS_BY_PHASE_D_TESTS
- Failed-final: PASS_BY_PHASE_D_TESTS

## UX

- Progress visible: PASS
- Failure visible: PASS
- Remaining work visible: PASS
- Resume available: PASS
- Resume semantics: only Missing / Failed / Stale materializations are retried; DONE ledger rows are not recomputed

## External Smoke

- SourceClaim: DEFERRED_BY_ENVIRONMENT_POLICY
- Alignment: DEFERRED_BY_ENVIRONMENT_POLICY
- Single-flight: PASS_BY_PHASE_D_TESTS
- Concurrency: PASS_BY_PHASE_D_TESTS
- Retry: PASS_BY_PHASE_D_TESTS

## Final Gate

- INTERNAL_PRODUCT_READY: True
- EXTERNAL_PRODUCTION_VERIFIED: False
- Remaining blockers: ['ENVIRONMENT_POLICY_EXTERNAL_LLM_SMOKE_DEFERRED']
