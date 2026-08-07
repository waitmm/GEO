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
    score_breakdown: Record<string, any>;
    score_explanation: string[];
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
