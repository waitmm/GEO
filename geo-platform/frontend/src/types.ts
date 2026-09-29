export type Competitor = {
  id?: number;
  name: string;
  aliases?: string[];
  website_url?: string;
};

export type Project = {
  id: number;
  organization_id: number;
  name: string;
  brand_name: string;
  brand_aliases: string[];
  website_url: string;
  industry: string;
  region: string;
  language: string;
  status: string;
  competitors: Competitor[];
};

export type Prompt = {
  id: number;
  project_id: number;
  title: string;
  prompt_text: string;
  prompt_group: string;
  intent_type: string;
  importance: number;
  enabled: boolean;
  topic_id?: number | null;
  cluster_id?: number | null;
  sample_count?: number;
  daily_tracking_enabled: boolean;
  daily_schedule_time: string;
  daily_sample_count: number;
  last_scheduled_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type Topic = {
  id: number;
  project_id: number;
  name: string;
  description: string;
  sort_order: number;
  enabled: boolean;
};

export type PromptCluster = {
  id: number;
  project_id: number;
  topic_id: number | null;
  name: string;
  description: string;
  sample_count: number;
  sort_order: number;
  enabled: boolean;
};

export type Metrics = {
  prompt_count: number;
  observation_count: number;
  platform_success_rate: number;
  brand_mention_rate: number;
  competitor_mention_rate: number;
  official_citation_rate: number;
};

export type MonitorRun = {
  id: number;
  project_id: number;
  status: string;
  platform_keys: string[];
  prompt_count: number;
  repeat_count: number;
  success_count: number;
  failure_count: number;
  started_at: string | null;
  finished_at: string | null;
};

export type Observation = {
  id: number;
  run_id: number;
  prompt_id: number;
  platform_key: string;
  entry_type: string;
  model: string;
  sample_index: number;
  status: string;
  answer_text: string;
  queried_at: string;
  citations: Array<{ id: number; url: string; title: string; domain: string; position: number }>;
  mention: {
    brand_mentioned: boolean;
    brand_recommended: boolean;
    cited_official_domain: boolean;
    competitors: Array<{ name: string; first_position: number; count: number }>;
  } | null;
};

export type Platform = {
  platform_key: string;
  platform_name: string;
  status: "ready" | "needs_config" | "placeholder" | string;
};

export type BrowserMonitorTask = {
  id: number;
  project_id: number;
  platform: string;
  source_type: string;
  adapter: string;
  question_ids: number[];
  run_count: number;
  schedule_type: string;
  status: string;
  created_at: string;
  updated_at: string;
  queued_run_count: number;
};

export type MonitoringBatch = {
  id: number;
  project_id: number;
  name: string;
  platform: string;
  collection_mode: "single_continuous" | "single_independent" | string;
  sample_count: number;
  status: string;
  notes: string;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
};

export type BrowserMonitorRun = {
  id: number;
  task_id: number;
  project_id: number;
  batch_id?: number | null;
  prompt_id: number;
  platform: string;
  source_type: string;
  adapter: string;
  run_sequence: number;
  sample_index: number;
  collection_mode: string;
  status: string;
  stage: string;
  original_query: string;
  page_query: string;
  retrieval_query: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number;
  answer_text: string;
  answer_char_count: number;
  expected_reference_count: number;
  detected_reference_count: number;
  resolved_reference_count: number;
  ui_declared_count?: number;
  dom_reference_count?: number;
  parsed_reference_count?: number;
  resolved_url_count?: number;
  unresolved_reference_count: number;
  reference_complete: boolean;
  brand_mentioned: boolean;
  brand_mention_count: number;
  brand_first_position: number;
  brand_recommendation_level: number;
  error_stage: string;
  error_type: string;
  error_message: string;
  retry_count: number;
  created_at: string;
  updated_at: string;
};

export type BrowserQueueSummary = {
  project_id: number | null;
  queued: number;
  pending: number;
  running: number;
  success: number;
  partial_success: number;
  failed: number;
  blocked: number;
  total: number;
  latest_run_id: number | null;
  latest_status: string;
  latest_stage: string;
  latest_error_type: string;
};

export type SinglePromptV2Run = {
  run_id: number;
  run_sequence: number;
  sample_index: number;
  status: string;
  stage: string;
  answer_text: string;
  answer_char_count: number;
  reference_complete: boolean;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number;
  observed_conditions: {
    original_query: { value: string | null; source: string };
    page_query: { value: string | null; source: string };
    retrieval_query: { value: string | null; source: string };
    [key: string]: { value: unknown; source: string };
  };
  platform_reported_search: {
    status: "MODEL_REPORTED" | "NOT_REPORTED" | string;
    terms: string[];
    reported_count: number | null;
    count_consistent: boolean | null;
    source: "ANSWER_TEXT" | string;
    verification_status: "UNVERIFIED_RETRIEVAL_TRACE" | string;
    evidence_line: string | null;
  };
  references: Array<{ reference_id: number; index: number; title: string; url: string; canonical_url: string; domain: string }>;
  retrieval_candidates: Array<{ candidate_id: number; rank: number; title: string; url: string; canonical_url: string; domain: string; snippet: string }>;
  error: { stage: string; type: string; message: string; blocked_type: string; blocked_reason: string } | null;
};

export type SinglePromptV2Status = {
  analysis: {
    analysis_id: string;
    project_id: number;
    prompt_id: number;
    task_id: number | null;
    prompt_text: string;
    sampling_plan_hash: string;
  };
  sampling: {
    status: string;
    planned_run_count: number;
    terminal_run_count: number;
    valid_run_count: number;
    failed_run_count: number;
    attempt_count: number;
  };
  result_version: string | null;
  context_id: string | null;
  result_source: "LIVE_TASK_PROGRESS" | "FROZEN_ANALYSIS_CONTEXT" | string;
  blocker: { code: string; detail: string } | null;
  allowed_operations: string[];
  active_task: { task_id: number; status: string; active_attempt_token: string | null } | null;
  runs: SinglePromptV2Run[];
  failures: Array<{ run_id: number; status: string; error: SinglePromptV2Run["error"] }>;
  warnings: Array<{ code: string; detail: string }>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type SinglePromptV2RunPoolItem = SinglePromptV2Run & {
  input_fingerprint: string;
  analysis_memberships: Array<{ analysis_id: string; context_id: string }>;
};

export type SinglePromptV2RunPool = {
  project_id: number;
  prompt_id: number;
  page: number;
  page_size: number;
  total: number;
  items: SinglePromptV2RunPoolItem[];
};

export type SinglePromptV2AnalysisListItem = {
  analysis: SinglePromptV2Status["analysis"];
  sampling: SinglePromptV2Status["sampling"];
  result_version: string | null;
  context_id: string | null;
  created_at: string;
  finished_at: string | null;
  source_preparation_summary: {
    preparation_id: string;
    status: string;
    required_source_count: number;
    ready_source_count: number;
    waived_source_count: number;
    nonterminal_source_count: number;
    completion_manifest_id: string | null;
  } | null;
};

export type SinglePromptV2SourcePreparation = {
  preparation: {
    preparation_id: string;
    analysis_id: string;
    context_id: string;
    project_id: number;
    prompt_id: number;
    status: string;
    created_by: string;
  };
  citation_manifest: {
    manifest_id: string;
    version_number: number;
    payload_hash: string;
    raw_output_hash: string;
    source_count: number;
    occurrence_count: number;
  };
  conservation: {
    required_unique_sources: number;
    terminal: number;
    nonterminal: number;
    by_state: Record<string, number>;
    conserved: boolean;
  };
  sources: Array<{
    source_key: string;
    canonical_url: string;
    original_urls: string[];
    reference_observations: Array<Record<string, any>>;
    occurrence_count: number;
    state: "PENDING" | "READY" | "WAIVED_WITH_LIMITATION" | string;
    row_version: number;
    failure: null | { code: string; detail: string };
    waiver: null | { reason: string; impact: string; waived_by: string; waived_at: string | null };
    snapshot: null | {
      snapshot_id: string;
      title: string;
      content_hash: string;
      artifact_hash: string;
      artifact_path: string;
      passages_hash: string;
      passage_count: number;
      coverage_scope: "FULL_PAGE" | "EXCERPT" | string;
      acquisition_method: "AUTO_FETCH" | "MANUAL" | string;
      acquired_at: string;
      submitted_by: string;
      created_at: string;
    };
  }>;
  completion_manifest: null | {
    manifest_id: string;
    version_number: number;
    status: "FROZEN" | "NO_USABLE_SOURCE" | string;
    payload_hash: string;
    required_source_count: number;
    ready_source_count: number;
    waived_source_count: number;
    created_at: string;
  };
  allowed_operations: string[];
};

export type SinglePromptV2DiagnosisEdit = {
  target_type: "RECOMMENDATION_EVENT" | "EVIDENCE_RELATION" | "TRUTH_RELATION";
  target_id: string;
  value: string;
  reason: string;
};

export type SinglePromptV2DiagnosisStatus = {
  diagnosis: {
    diagnosis_id: string;
    analysis_id: string;
    context_id: string;
    project_id: number;
    prompt_id: number;
    input_fingerprint: string;
    raw_output_hash: string;
    brand_snapshot_hash: string;
    truth_set_hash: string;
    contract_config_hash: string;
  };
  compute_status: string;
  overall_status: string;
  progress: { stage?: string; completed?: number; total?: number; detail?: string };
  blocker: { code: string; detail: string } | null;
  attempt_count: number;
  usage: { external_llm_calls: number; llm_cache_hits: number; external_token_usage: number };
  current_safety_advisories: Array<{
    code: string;
    count?: number;
    historical_content_ready?: number;
    maximum_currently_eligible?: number;
    message?: string;
    detail?: string;
    affected_run_ids?: number[];
  }>;
  effective_evidence_eligibility: {
    contract_version: string;
    historical_content_ready: number;
    content_blocked_current: number;
    maximum_currently_eligible: number;
    all_remaining_sources_quality_verified: boolean;
    eligible_snapshot_ids: string[];
    blocked_snapshots: Array<{ snapshot_id: string; source_key: string; title: string; reason: string }>;
    effective_evidence_relation_ids: string[];
    blocked_historical_relation_ids: string[];
    effective_relation_count: number;
  };
  source_content_status_summary: {
    reference_records: number;
    unique_sources: number;
    content_ready: number;
    not_fetched: number;
    fetch_failed: number;
    content_blocked: number;
    passage_count: number;
  };
  current_truth_relation_eligibility: null | {
    contract_version: string;
    effective_relationships: any[];
    cross_subject_relation_ids: string[];
    cross_subject_relation_count: number;
  };
  project_truth_state: {
    truths: Array<{
      truth_id: number;
      brand_id: number | null;
      capability_key: string;
      capability_label: string;
      product_truth_status: "SUPPORTED" | "PARTIALLY_SUPPORTED" | "NOT_SUPPORTED" | "UNKNOWN";
      truth_source: string;
      source_reference: string;
      reviewed_by: string;
      reviewed_at: string | null;
      note: string;
      row_updated_at: string | null;
      statement_eligibility: { status: "ELIGIBLE" | "VERIFY_FIRST" | "PROHIBITED"; issues: string[] };
    }>;
    truth_set_hash: string;
    differs_from_frozen_diagnosis: boolean;
  };
  target_capability_review_items: Array<{
    candidate_id: string;
    capability_key: string;
    capability_label: string;
    source_signal_ids: string[];
    source_event_ids: string[];
    source_run_ids: number[];
    answer_excerpts: string[];
    current_truth: SinglePromptV2DiagnosisStatus["project_truth_state"]["truths"][number] | null;
  }>;
  answer_semantic_eligibility: null | {
    contract_version: string;
    total_answer_count: number;
    admitted_answer_count: number;
    failed_answer_count: number;
    pending_answer_count?: number;
    invalid_cache_answer_count?: number;
    valid_zero_answer_count: number;
    failure_record_count: number;
    no_consumable_answer_semantic_result: boolean;
    partial_failure: boolean;
    partial_compute?: boolean;
    status: "NO_CONSUMABLE_RESULT" | "PARTIAL" | "ADMITTED" | string;
    mixed_answer_run_ids?: number[];
  };
  coverage_projections: null | {
    input_scope_coverage: {
      expected_run_ids: number[];
      bound_run_ids: number[];
      missing_run_ids: number[];
      readable_answer_count: number;
      expected_run_count: number;
      scope_complete: boolean;
    };
    compute_coverage: {
      expected_run_ids: number[];
      success_with_events_run_ids: number[];
      success_zero_events_run_ids: number[];
      actual_failure_run_ids: number[];
      pending_compute_run_ids: number[];
      pending_external_authorization_run_ids: number[];
      invalid_cache_run_ids: number[];
      valid_compute_run_ids: number[];
      valid_compute_count: number;
      expected_run_count: number;
      all_runs_validly_understood: boolean;
    };
    review_coverage: {
      reviewed_run_ids: number[];
      unreviewed_valid_run_ids: number[];
      pending_review_event_ids: string[];
      prefilled_event_ids: string[];
      prefilled_run_ids: number[];
      reviewed_run_count: number;
      expected_run_count: number;
      exact_result_review_present: boolean;
      full_scope_review_complete: boolean;
    };
    evidence_plan_coverage: {
      plan_status: string;
      plan_id: string | null;
      plan_hash: string | null;
      eligible_reason_ids: string[];
      planned_reason_ids: string[];
      unplanned_reason_ids: string[];
      base_candidate_count: number;
      fallback_candidate_count: number;
      evaluated_relation_count: number;
      technical_failure_count: number;
      not_evaluated_relation_count: number;
      execution_complete: boolean;
    };
    strategy_dependency_coverage: {
      global_nine_run_conclusion_eligible: boolean;
      reason_level_direction_evaluation_required: boolean;
      boundary: string;
    };
  };
  result: null | {
    result_version: string;
    version_number: number;
    parent_result_version: string | null;
    output_hash: string;
    reviewable_set_hash: string;
    output: {
      result_scope?: "ANSWER_ONLY" | "ANSWER_AND_EVIDENCE" | string;
      input: Record<string, any>;
      answer_diagnosis: { events: any[]; market_criteria?: any[]; unresolved_items: any[]; failures: any[]; answer_jobs?: any[] };
      source_diagnosis: { summary: Record<string, number>; snapshots: any[] };
      evidence_diagnosis: { source_claim_jobs: any[]; source_claims: any[]; source_claim_failures: any[]; source_relations: any[]; alignment_failures: any[]; reason_inputs_requiring_review: any[] };
      truth_diagnosis: { truth_snapshot: any[]; relationships: any[]; external_capability_signals?: any[] };
      truth_reprojection?: { prior_review?: { review_id: string; decisions: any[] }; answer_semantic_recomputed: boolean; evidence_recomputed: boolean; external_llm_calls: number };
      limitations: any[];
      stats: Record<string, number>;
      usage: Record<string, number>;
    };
    limitations: any[];
    stats: Record<string, number>;
    created_at: string;
  };
  review: null | {
    review_id: string;
    decision: string;
    result_version: string;
    result_hash: string;
    reviewable_set_hash: string;
    decisions: any[];
    reviewer: string;
    note: string;
    created_at: string;
  };
  allowed_operations: string[];
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type SinglePromptV2CitationContributionStatus = {
  execution: {
    contribution_id: string;
    analysis_id: string;
    context_id: string;
    project_id: number;
    prompt_id: number;
    selected_run_id: number;
    input_snapshot_hash: string;
    contract_version: string;
    status: string;
    plan_hash: string;
    plan: {
      selection: Record<string, any>;
      answer_units: Array<Record<string, any>>;
      answer_semantic_char_coverage: { covered: number; total: number; rate: number };
      citations: Array<Record<string, any>>;
      call_plan: Record<string, any>;
    };
    authorization: Record<string, any>;
    progress: Record<string, any>;
    blocker: { code: string; detail: string } | null;
    usage: { external_llm_calls: number; llm_cache_hits: number; external_token_usage: number };
    created_at: string;
    started_at: string | null;
    finished_at: string | null;
  };
  result: null | {
    result_version: string;
    output_hash: string;
    reviewable_set_hash: string;
    output: Record<string, any>;
    limitations: Array<Record<string, any>>;
    stats: Record<string, any>;
    created_at: string;
  };
  review: null | {
    review_id: string;
    result_version: string;
    metrics: Record<string, any>;
    decisions: Array<Record<string, any>>;
    missed_bindings: Array<Record<string, any>>;
    reviewer: string;
    note: string;
    created_at: string;
  };
  human_calibration: null | {
    version: string;
    calibration_sample_identity: string;
    frozen_sample_count: number;
    unbiased_evaluation_count: number;
    recall_boundary_count: number;
    binding_census: Array<Record<string, any>>;
    binding_census_count: number;
    binding_census_hash: string;
    review_targets: Array<Record<string, any>>;
    human_review_set_hash: string;
    deduplicated_target_count: number;
    new_human_review_count: number;
    reused_human_gold_count: number;
    human_gold_conflict_count: number;
  };
  allowed_operations: string[];
};

export type SinglePromptV2CitationContributionListItem = {
  contribution_id: string;
  context_id: string;
  selected_run_id: number;
  status: string;
  result_version: string | null;
  result_hash: string | null;
  reviewable_set_hash: string | null;
  review_id: string | null;
  deduplicated_target_count: number;
  new_human_review_count: number;
  created_at: string;
};

export type SinglePromptV2StrategyDirection = {
  direction_id: string;
  direction_type: "FOUNDATION" | "CHANNEL";
  channel_key: string | null;
  channel_label: string | null;
  channel_role: "PRIMARY" | "TEST" | null;
  level: "ACTIONABLE" | "VERIFY_FIRST" | "OBSERVE" | "BLOCKED";
  reason_ids: string[];
  truth_ids: number[];
  evidence_relation_ids: string[];
  rationale: string;
  hypothesis: string | null;
  effect_status: string;
  priority_order: number | null;
  priority_basis: string;
};

export type SinglePromptV2StrategyReadiness = {
  contract_version: string;
  classification: "A" | "B" | "C";
  can_create_strategy: boolean;
  blocker: { code: string; detail: string } | null;
  legal_next_steps: string[];
  input_identity: Record<string, any>;
  input_projection_hash: string;
  review_id: string | null;
  review_snapshot_hash: string | null;
  validation_contract_version: string;
  current_observation: Record<string, number>;
  foundation: { state: "REQUIRED" | "NOT_REQUIRED" | "UNKNOWN"; assessment_id: string | null; basis_ids: string[]; reason: string };
  channel_assessments: Array<Record<string, any>>;
  observed_themes: Array<Record<string, any>>;
  actionable_themes: Array<Record<string, any>>;
  qualified_directions: SinglePromptV2StrategyDirection[];
  qualified_direction_count: number;
  blocked_directions: Array<Record<string, any>>;
  verification_items: Array<{ code: string; detail: string }>;
  needs_human_prioritization: boolean;
  limitations: any[];
  advisories: any[];
  effective_evidence_eligibility: Record<string, any>;
  strategy_dependency_coverage: Record<string, any>;
  boundary: Record<string, boolean | number>;
};

export type SinglePromptV2QualificationProjection = {
  contract_version: string;
  projection_hash: string;
  input_identity: Record<string, any>;
  input_projection_hash: string;
  analysis_scope: { run_ids: number[]; label: string };
  evidence_scope: {
    run_ids: number[];
    label: string;
    status: string;
    result: null | {
      contribution_id: string;
      result_version: string;
      result_hash: string;
      processing: { done: number; failed: number; binding_count: number; evaluation_count: number };
      answer_anchor: string;
      generation_influence: string;
    };
  };
  scope_limitations: string[];
  object_qualifications: Array<Record<string, any>>;
  directions: Array<{
    strategy_id: string;
    direction_type: "MECHANISM";
    mechanism_gap: string;
    intervention_goal: string;
    reason_id: string;
    reason_text: string;
    reason_run_ids: number[];
    truth_ids: number[];
    dependencies: Array<Record<string, any>>;
    eligibility_by_use: Record<string, string>;
    strategy_direction_eligibility: string;
    execution_draft_eligibility: string;
    public_claim_eligibility: string;
    limiting_dependencies: string[];
    scope_limitations: string[];
    reasoning_trace: Array<Record<string, any>>;
  }>;
  execution_drafts: Array<{
    draft_id: string;
    direction_id: string;
    title: string;
    goal: string;
    asset_role: string;
    asset_operation: "CREATE_NEW";
    asset_type_candidates: string[];
    channel_candidate: Record<string, any>;
    sections: Array<Record<string, any>>;
    claims: Array<Record<string, any>>;
    required_truth_ids: number[];
    required_evidence_ids: string[];
    eligibility_by_use: Record<string, string>;
    limiting_dependencies: string[];
    internal_checklist: string[];
    boundary: Record<string, boolean | string>;
  }>;
  final_plan: {
    analysis_completed: boolean;
    machine_direction_count: number;
    execution_draft_count: number;
    execution_ready_count: number;
    draftable_verify_first_count: number;
    human_review_global_blocker: boolean;
    external_action_authorized: boolean;
  };
  boundary: Record<string, boolean | number>;
};

export type SinglePromptV2QualificationCriticStatus = {
  execution: {
    critic_id: string;
    status: "QUEUED" | "RUNNING" | "SHADOW_COMPLETED" | "SHADOW_COMPLETED_WITH_LIMITATIONS" | "FAILED";
    analysis_id: string;
    context_id: string;
    diagnosis_id: string;
    diagnosis_result_version: string;
    baseline_projection_hash: string;
    plan_hash: string;
    candidate_count: number;
    provider: string;
    requested_model: string;
    progress: { completed: number; total: number; stage: string };
    external_llm_calls: number;
    llm_cache_hits: number;
    external_token_usage: number;
    blocker: null | { code: string; detail: string };
    created_at: string;
    started_at: string | null;
    finished_at: string | null;
  };
  result: null | {
    result_version: string;
    result_hash: string;
    output: {
      model_identity: { provider: string; requested_model: string };
      signals: Array<{
        candidate_id: string;
        candidate_type: "CITATION_RELATION" | "STRATEGY_DIRECTION";
        object_id: string;
        impact_reasons: string[];
        impact_level: "HIGH";
        required_for: string[];
        input_hash: string;
        processing_status: "DONE" | "FAILED" | "NOT_EVALUATED";
        critic_verdict?: "AGREE" | "DISAGREE" | "INSUFFICIENT_CONTEXT";
        issue_types?: string[];
        counterexample?: string | null;
        rationale?: string;
        latency_ms?: number;
        failure_code?: string;
        failure_detail?: string;
      }>;
      summary: {
        candidate_count: number;
        processing_status: Record<string, number>;
        critic_verdict: Record<string, number>;
        issue_types: Record<string, number>;
        external_calls: number;
        cache_hits: number;
        external_tokens: number;
        external_input_tokens: number;
        external_output_tokens: number;
        estimated_cost_cny: number;
        pricing_status: string;
        pricing_basis: string;
        latency_ms: { total: number; average: number; maximum: number };
        schema_failure_count: number;
      };
      shadow_comparison: {
        formal_qualification_changed: false;
        formal_strategy_changed: false;
        disagreement_count: number;
        insufficient_context_count: number;
        gain_against_human_gold: string;
      };
      boundary: Record<string, boolean>;
    };
    created_at: string;
  };
  allowed_actions: string[];
};

export type SinglePromptV2QualificationCriticGoldDecision = {
  object_id: string;
  gold_identity: string;
  gold_model_a_correct: boolean;
  gold_qwen_challenge_valid: "YES" | "NO" | "NOT_APPLICABLE" | "INSUFFICIENT_CONTEXT";
  gold_issue_type: string;
  gold_effective_relation_or_strategy_judgment: string;
  should_change_qualification: boolean;
  should_change_strategy_or_claim: "NONE" | "STRATEGY_DIRECTION" | "PUBLIC_CLAIM" | "BOTH";
  review_note: string;
  challenge_classification?: "TRUE_POSITIVE" | "FALSE_CHALLENGE" | "NEUTRAL";
  simulated_qualification_effect?: "IMPROVES" | "DEGRADES" | "NO_CHANGE" | "UNCERTAIN";
};

export type SinglePromptV2QualificationCriticGoldStatus = {
  phase: "SHADOW_PHASE_B1_INCREMENTAL_VALUE_HUMAN_GOLD";
  contract_version: string;
  analysis_id: string;
  phase_a_critic_id: string;
  phase_a_result_version: string;
  phase_a_result_hash: string;
  supplemental_result_versions: string[];
  reviewable_set_hash: string;
  candidate_count: number;
  candidates: Array<{
    analysis_id: string;
    machine_result_version: string;
    machine_result_hash: string;
    critic_result_version: string;
    critic_result_hash: string;
    object_id: string;
    input_hash: string;
    gold_identity: string;
    cohort: "PHASE_A_ORIGINAL" | "SUPPLEMENTAL";
    candidate_type: "CITATION_RELATION" | "STRATEGY_DIRECTION";
    task_id: string;
    model_a_judgment: Record<string, any>;
    rule_signals: Record<string, any>;
    qwen_signal: {
      critic_verdict: "AGREE" | "DISAGREE" | "INSUFFICIENT_CONTEXT";
      primary_issue: string;
      issue_types: string[];
      counterexample: string | null;
      rationale: string;
    };
    review_context: Record<string, any>;
  }>;
  reviews: Array<{
    review_id: string;
    version_number: number;
    parent_review_id: string | null;
    reviewer: string;
    note: string;
    decisions: SinglePromptV2QualificationCriticGoldDecision[];
    metrics: Record<string, any>;
    created_at: string;
  }>;
  allowed_actions: Array<"COMPLETE_HUMAN_GOLD" | "REVISE_HUMAN_GOLD">;
  boundary: {
    external_llm_calls: 0;
    formal_qualification_effect: "NONE";
    formal_strategy_effect: "NONE";
    production_critic_enabled: false;
    overall_qwen_accuracy_claim_allowed: false;
  };
};

export type SinglePromptV2StrategyStatus = {
  strategy: {
    strategy_id: string;
    analysis_id: string;
    context_id: string;
    diagnosis_id: string;
    project_id: number;
    prompt_id: number;
    input_fingerprint: string;
    diagnosis_result_version: string;
    diagnosis_result_hash: string;
    diagnosis_review_id: string;
    review_snapshot_hash: string;
    validation_contract_version: string;
    input_snapshot_hash: string;
    status: string;
  };
  result: null | {
    result_version: string;
    version_number: number;
    parent_result_version: string | null;
    output_hash: string;
    reviewable_set_hash: string;
    output: {
      input_identity: Record<string, any>;
      current_observation: Record<string, number>;
      themes: Array<Record<string, any>>;
      directions: SinglePromptV2StrategyDirection[];
      foundation: SinglePromptV2StrategyReadiness["foundation"];
      needs_human_prioritization: boolean;
      unresolved: { blocked_directions: Array<Record<string, any>>; verification_items: Array<{ code: string; detail: string }> };
      limitations: any[];
      advisories: any[];
      effective_evidence_eligibility: Record<string, any>;
      provenance: Record<string, any>;
      boundary: Record<string, boolean | number>;
    };
    limitations: any[];
    created_at: string;
  };
  review: null | { review_id: string; review_snapshot_hash: string; decision: string; reviewer: string; note: string; result_version: string; created_at: string };
  applicability: { is_current_input: boolean; checks: Record<string, boolean> };
  allowed_operations: string[];
  created_at: string;
};

export type SinglePromptV2ExecutionStatus = {
  proposal: {
    proposal_id: string;
    strategy_id: string;
    analysis_id: string;
    context_id: string;
    diagnosis_id: string;
    project_id: number;
    prompt_id: number;
    direction_id: string;
    strategy_result_version: string;
    strategy_result_hash: string;
    strategy_review_id: string;
    strategy_review_snapshot_hash: string;
    input_snapshot_hash: string;
    status: string;
  };
  result: null | {
    result_version: string;
    version_number: number;
    parent_result_version: string | null;
    output_hash: string;
    reviewable_set_hash: string;
    output: {
      direction: SinglePromptV2StrategyDirection;
      strategy_channel: { channel_key: string | null; channel_label: string | null; channel_role: string | null; immutable: boolean };
      asset_operation: "CREATE_NEW";
      asset_type_candidates: Array<{ asset_type: string; label: string }>;
      publication_surface_candidates: Array<{ surface_key: string; label: string; asset_type: string }>;
      package_candidates: Array<{ package_key: string; label: string; direction_id: string; truth_ids: number[] }>;
      title_candidates: Array<{ title_id: string; title: string; truth_ids: number[] }>;
      public_content_candidates: Array<Record<string, any>>;
      selected_public_content: Array<Record<string, any>>;
      internal_checklist: Array<{ code: string; detail: any }>;
      selection: {
        asset_operation: "CREATE_NEW";
        asset_type: string | null;
        package_key: string;
        publication_surface: string | null;
        publishing_account: string;
        publishing_location: string;
        account_control_status: "UNVERIFIED" | "USER_REPORTED_CONTROL";
        title: string;
        section_order: string[];
        execution_note: string;
      };
      baseline: Record<string, any>;
      limitations: any[];
      advisories: any[];
      validation: { status: "READY_FOR_CONFIRMATION" | "NEEDS_HUMAN_SELECTION"; errors: string[]; validators: Record<string, string> };
      boundary: Record<string, any>;
    };
    created_at: string;
  };
  confirmations: Array<{ confirmation_id: string; result_version: string; confirmation_snapshot_hash: string; confirmer: string; note: string; created_at: string }>;
  publications: Array<{
    publication_id: string;
    confirmation_id: string;
    prior_publication_id: string | null;
    revision_number: number;
    publication_status: "USER_REPORTED";
    conformance: "MATCHED" | "VALIDATED_VARIATION" | "OUTSIDE_CONFIRMED_SCOPE" | "NOT_EVALUABLE";
    report_hash: string;
    report: Record<string, any>;
    conformance_detail: Record<string, any>;
    recorder: string;
    created_at: string;
  }>;
  applicability: { is_current_input: boolean; checks: Record<string, boolean> };
  allowed_operations: string[];
  boundary: Record<string, any>;
};

export type SinglePromptV2RetestReadiness = {
  contract_version: string;
  sampling_eligible: boolean;
  comparison_eligible?: { temporal_order: boolean; status: string };
  pre_post_temporal_order_verified?: boolean;
  blocker: { code: string; detail: string } | null;
  publication?: Record<string, any>;
  baseline?: Record<string, any>;
  identity_default?: {
    canonical_brand_name: string;
    accepted_aliases: string[];
    official_domains: string[];
    official_urls: string[];
    identity_source: string;
  };
  allowed_actions: string[];
  boundary?: Record<string, any>;
};

export type SinglePromptV2Metric = {
  metric_key: string;
  planned_count: number;
  valid_raw_count: number;
  evaluable_run_ids: number[];
  evaluable_count: number;
  hit_run_ids: number[];
  hit_count: number;
  unevaluated: Array<{ run_id: number; reason: string }>;
  unevaluated_count: number;
  value: number | null;
  status: "COMPLETE" | "PARTIAL" | "NOT_COMPUTABLE";
};

export type SinglePromptV2RetestStatus = {
  contract_version: string;
  retest: {
    retest_id: string;
    confirmation_id: string;
    publication_id: string;
    proposal_id: string;
    project_id: number;
    prompt_id: number;
    baseline_analysis_id: string;
    baseline_context_id: string;
    retest_analysis_id: string;
    input_fingerprint: string;
    status: string;
    retest_plan_hash: string;
    measurement_identity_hash: string;
    measurement_contract_hash: string;
  };
  baseline: Record<string, any>;
  retest_plan: Record<string, any>;
  measurement_identity: Record<string, any>;
  measurement_contract: Record<string, any>;
  planned_conditions: Record<string, any>;
  observed_conditions: Record<string, any>;
  unobservable_conditions: any[];
  authorization: Record<string, any>;
  semantic_measurement: Record<string, any>;
  sampling: SinglePromptV2Status;
  comparison_result: null | {
    result_version: string;
    version_number: number;
    output_hash: string;
    baseline_measurement: { metrics: Record<string, SinglePromptV2Metric> };
    retest_measurement: { metrics: Record<string, SinglePromptV2Metric> };
    comparison: {
      temporal_order: Record<string, any>;
      publication: Record<string, any>;
      metrics: Record<string, { comparison_eligible: boolean; comparison_mode: string; delta_percentage_points: number | null; reasons: string[]; causal_conclusion: null }>;
      limitations: any[];
      conclusion_policy: string;
    };
    limitations: any[];
    created_at: string;
  };
  blocker: { code: string; detail: string } | null;
  allowed_actions: string[];
  boundary: Record<string, any>;
};

export type BrowserMonitorRunDetail = BrowserMonitorRun & {
  references: Array<{
    id: number;
    reference_index: number;
    display_title: string;
    matched_title: string;
    url: string;
    domain: string;
    resolution_method: string;
    match_confidence: number;
    relevance_label: string;
    quality_label: string;
  }>;
  retrieval_candidates: Array<{
    id: number;
    rank: number;
    title: string;
    url: string;
    domain: string;
    snippet: string;
  }>;
  artifacts: Array<{
    id: number;
    artifact_type: string;
    storage_path: string;
    mime_type: string;
    size_bytes: number;
  }>;
};

export type RunArtifactContent = {
  id: number;
  run_id: number;
  artifact_type: string;
  storage_path: string;
  mime_type: string;
  size_bytes: number;
  content: string;
  truncated: boolean;
};

export type ValidationPresence = {
  name: string;
  kind: "brand" | "competitor";
  appeared_runs: number;
  sample_runs: number;
  recommended_runs?: number;
  mentioned_runs?: number;
};

export type ValidationSource = {
  value: string;
  title?: string;
  domain?: string;
  run_count: number;
  prompt_count?: number;
};

export type ValidationDashboard = {
  project_id: number;
  sample_label: string;
  environment_label?: string;
  prompts: {
    total: number;
    executed: number;
    clusters: number;
    valid_runs: number;
    sample_runs: number;
  };
  presence: ValidationPresence[];
  recommendation: {
    explicit: number;
    mentioned: number;
    absent: number;
    sample_runs: number;
  };
  top_domains: ValidationSource[];
  top_urls: ValidationSource[];
  quality: {
    total_runs: number;
    successful_runs: number;
    blocked_runs: number;
    collector_failed_runs: number;
    complete_reference_runs: number;
    eligible_reference_runs: number;
    parsed_references: number;
    resolved_urls: number;
  };
};

export type OptimizationIssue = {
  id: number;
  project_id: number;
  prompt_id?: number | null;
  prompt_text: string;
  cluster_id?: number | null;
  issue_type: string;
  status: string;
  severity: number;
  confidence_level: string;
  observation_start?: string | null;
  observation_end?: string | null;
  analyzable_sample_count: number;
  observed_facts: Record<string, any>;
  possible_causes: string[];
  diagnosis_summary: string;
  rejected_reason: string;
  run_ids: number[];
  created_at: string;
  updated_at: string;
  confirmed_at?: string | null;
  resolved_at?: string | null;
};

export type OptimizationAction = {
  id: number;
  issue_id: number;
  action_type: string;
  target_type: string;
  target_url: string;
  status: string;
  priority: number;
  owner: string;
  action_summary: string;
  action_detail: string;
  content_feature_changes: Array<{
    feature: string;
    before?: any;
    after?: any;
    description: string;
    location?: string;
  }>;
  planned_at?: string | null;
  released_at?: string | null;
  release_note: string;
  release_evidence: Record<string, any>;
  created_at: string;
  updated_at: string;
};

export type OptimizationExperiment = {
  id: number;
  action_id: number;
  status: string;
  hypothesis: string;
  target_prompt_scope: number[];
  control_prompt_scope: number[];
  sentinel_prompt_scope: number[];
  environment_scope: Record<string, any>;
  sample_plan: Record<string, any>;
  primary_metric: string;
  secondary_metrics: string[];
  baseline_run_ids: number[];
  validation_run_ids: number[];
  baseline_metrics: Record<string, any>;
  release_blocked: boolean;
  release_blocked_reason: string;
  result_metrics: Record<string, any>;
  comparison: Record<string, any>;
  per_prompt_results: Array<Record<string, any>>;
  per_environment_results: Array<Record<string, any>>;
  conclusion: string;
  conclusion_reason: string;
  confounders: string[];
  post_run_ids: number[];
  outcome_summary: Record<string, any>;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
};

export type OptimizationEvidenceChain = {
  issue: OptimizationIssue;
  actions: OptimizationAction[];
  experiments: OptimizationExperiment[];
  runs: Array<{
    id: number;
    prompt_id: number;
    status: string;
    run_sequence: number;
    sample_index: number;
    original_query: string;
    answer_text: string;
    brand_mentioned: boolean;
    brand_recommendation_level: number;
    reference_complete: boolean;
    parsed_reference_count: number;
    resolved_url_count: number;
    created_at: string;
  }>;
  references: Array<{
    id: number;
    run_id: number;
    reference_index: number;
    display_title: string;
    url: string;
    domain: string;
    is_official_domain: boolean;
    is_competitor_domain: boolean;
    occurrence_count: number;
    run_ids: number[];
    reference_indices: number[];
  }>;
  retrieval_candidates: Array<{
    id: number;
    run_id: number;
    rank: number;
    title: string;
    url: string;
    domain: string;
    snippet: string;
    occurrence_count: number;
    run_ids: number[];
    ranks: number[];
  }>;
  source_analysis: Array<{
    source_kind: string;
    source_id: number;
    run_id: number;
    run_ids: number[];
    run_count: number;
    cited: boolean;
    retrieval_rank?: number | null;
    title: string;
    url: string;
    domain: string;
    ownership: string;
    source_role: string;
    content_format: string;
    prompt_overlap_score: number;
    brand_signal: string;
    freshness_signal: string;
    authority_signal: string;
    platform: string;
    author_name: string;
    published_date: string;
    source_score: number;
    legacy_source_score: number;
    source_score_deprecated: boolean;
    score_breakdown: Record<string, any>;
    score_explanation: string[];
    citation_prominence_level: string;
    citation_prominence_basis: string[];
    citation_prominence_breakdown: Record<string, any>;
    source_document_id?: number | null;
    content_status: string;
    content_status_label: string;
    content_status_reason: string;
    blocks_alignment: boolean;
    decision_support_level: string;
    has_contradiction: boolean;
    benchmark_relevance: string;
    benchmark_tier: string;
    benchmark_basis: string[];
    supporting_alignment_ids: number[];
    contradicting_alignment_ids: number[];
    decision_support_basis: string[];
    source_gap_type?: string | null;
    source_gap_label: string;
    source_gap_reason: string;
    source_gap_basis: string[];
    source_gap_precondition: string;
    gap_analysis_status: string;
    matched_product_truth_ids: number[];
    matched_product_truth_status: string;
    existing_asset_status: string;
    existing_asset_snapshot_id?: number | null;
    existing_asset_coverage: string;
    priority_level?: string | null;
    priority_label: string;
    priority_reason: string;
    priority_basis: string[];
    action_route?: string | null;
    action_route_label: string;
    action_route_reason: string;
    recommended_action?: Record<string, any> | null;
    channel_opportunity?: Record<string, any> | null;
    citation_occurrence_count: number;
    cited_run_count: number;
    answer_citation_rate: number;
    avg_reference_position: number;
    account_platform: string;
    account_identity: string;
    account_identity_reason: string;
    answer_usage: string;
    answer_usage_reason: string;
    citation_reason: string;
    citation_basis: string[];
    content_structure_signals: string[];
    time_signal_detail: string;
    cross_source_comparison: Record<string, any>;
    diagnostic_angles: Array<{ angle: string; value: any; note: string }>;
    risk_flags: string[];
    comparison_note: string;
  }>;
  hypotheses: Array<{
    id: number;
    project_id: number;
    issue_id: number;
    experiment_id: number;
    evidence_package_id: number;
    status: string;
    observed_problem: string;
    hypothesized_cause: string;
    core_mechanism: string;
    target_metric: string;
    baseline_value: string;
    expected_direction: string;
    changed_features: string[];
    controlled_variables: string[];
    accepted_by: string;
    accepted_at?: string | null;
  }>;
  page_snapshots: Array<{
    id: number;
    project_id: number;
    experiment_id?: number | null;
    url: string;
    http_status?: number | null;
    final_url: string;
    canonical_url: string;
    title: string;
    h1: string;
    main_text_hash: string;
    snapshot_type: string;
    capture_status: string;
    captured_at: string;
  }>;
  release_audits: Array<Record<string, any>>;
  strategy_candidates: StrategyCandidate[];
};

export type StrategyCandidate = {
  id: number;
  project_id: number;
  experiment_id?: number | null;
  evidence_package_id: number;
  target_url: string;
  provider: string;
  model: string;
  prompt_version: string;
  prompt_text: string;
  generated_at: string;
  generation_status: string;
  original_llm_payload: Record<string, any>;
  structured_payload: Record<string, any>;
  human_edited_payload: Record<string, any>;
  evidence_validation_status: string;
  evidence_validation_errors: string[];
  evidence_validation_warnings: string[];
  evidence_validator_version: string;
  hypothesis_validation_status: string;
  hypothesis_validation_errors: string[];
  hypothesis_validation_warnings: string[];
  hypothesis_validator_version: string;
  review_status: string;
  reviewed_by: string;
  reviewed_at?: string | null;
  review_note: string;
  converted_hypothesis_id?: number | null;
  experiment_plan: Record<string, any>;
  candidate_origin?: string;
  strategy_context?: Record<string, any>;
  strategy_decision_view?: Record<string, any>;
  strategy_audit_view?: Record<string, any>;
  strategy_synthesis?: Record<string, any>;
  strategy_view_mode?: "SYNTHESIS_DECISION_VIEW" | "LEGACY";
  strategy_schema_complete?: boolean;
  eligible_for_current_step7?: boolean;
  current_step7_ineligibility_reasons?: string[];
  created_at: string;
  updated_at: string;
};

export type EvidencePackage = {
  id: number;
  project_id: number;
  prompt_id?: number | null;
  prompt_text: string;
  version: number;
  schema_version: string;
  metric_spec_version: string;
  source_run_ids: number[];
  target_page_urls: string[];
  environment_snapshot: Record<string, any>;
  package_payload: Record<string, any>;
  package_hash: string;
  status: string;
  superseded_by_id?: number | null;
  created_at: string;
  updated_at: string;
};

export type PromptDailyReport = {
  id: number;
  project_id: number;
  prompt_id: number;
  report_date: string;
  run_ids: number[];
  sample_count: number;
  success_count: number;
  brand_mention_count: number;
  brand_mention_rate: number;
  avg_reference_count: number;
  top_reference_domains: Array<{ domain: string; count: number }>;
  top_retrieval_domains: Array<{ domain: string; count: number }>;
  summary: string;
  recommendations: string[];
  created_at: string;
  updated_at: string;
};
