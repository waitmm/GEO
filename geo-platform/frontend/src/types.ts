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
  prompt_id: number;
  platform: string;
  source_type: string;
  adapter: string;
  run_sequence: number;
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
