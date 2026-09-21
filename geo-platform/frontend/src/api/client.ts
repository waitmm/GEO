import type { BrowserMonitorRun, BrowserMonitorRunDetail, BrowserMonitorTask, BrowserQueueSummary, EvidencePackage, Metrics, MonitoringBatch, MonitorRun, Observation, OptimizationAction, OptimizationEvidenceChain, OptimizationExperiment, OptimizationIssue, Platform, Project, Prompt, PromptCluster, PromptDailyReport, RunArtifactContent, SinglePromptV2AnalysisListItem, SinglePromptV2DiagnosisEdit, SinglePromptV2DiagnosisStatus, SinglePromptV2ExecutionStatus, SinglePromptV2RetestReadiness, SinglePromptV2RetestStatus, SinglePromptV2SourcePreparation, SinglePromptV2Status, SinglePromptV2StrategyReadiness, SinglePromptV2StrategyStatus, StrategyCandidate, Topic, ValidationDashboard } from "../types";

const API_BASE = "";

type ValidationDashboardWire = {
  project_id: number;
  sample_label: string;
  prompts: {
    total_prompts: number; total_clusters: number; prompts_with_runs: number;
    configured_samples: number; collected_samples: number; valid_samples: number;
  };
  brand_presence: { entity_type: string; name: string; observed_runs: number; sample_runs: number };
  competitor_presence: Array<{ entity_type: string; name: string; observed_runs: number; sample_runs: number }>;
  recommendation_presence: { explicit_recommendation: number; general_mention: number; not_observed: number; sample_runs: number };
  top_citation_domains: Array<{ domain: string; occurrences: number; run_count: number; prompt_count: number }>;
  top_citation_urls: Array<{ url: string; title: string; domain: string; occurrences: number; run_count: number; prompt_count: number }>;
  data_quality: {
    total_runs: number; success: number; blocked: number; collector_failed: number;
    references: { parsed_reference_count: number; resolved_url_count: number; complete_runs: number; assessed_runs: number };
  };
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init
  });
  if (!response.ok) {
    const detail = await response.text();
    let message = detail || response.statusText;
    try {
      const parsed = JSON.parse(detail);
      const parsedDetail = parsed.detail || parsed.message;
      message = typeof parsedDetail === "string"
        ? parsedDetail
        : parsedDetail?.detail || parsedDetail?.code || JSON.stringify(parsedDetail) || message;
    } catch {
      // Non-JSON error bodies are surfaced as-is.
    }
    if (response.status === 405) {
      message = "接口方法不匹配，请确认后端已重启到最新版本";
    }
    throw new Error(message);
  }
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    const detail = await response.text();
    const looksLikeFrontend = detail.includes("<!doctype html") || detail.includes("<div id=\"root\"");
    throw new Error(looksLikeFrontend
      ? "后端接口没有返回 JSON，可能服务未重启到最新版本或请求被前端兜底页面接管。请重启本地服务后重试。"
      : "后端接口返回格式不是 JSON，请检查服务状态。");
  }
  return response.json() as Promise<T>;
}

export const api = {
  listProjects: () => request<Project[]>("/api/projects"),
  createSinglePromptV2Analysis: (payload: { project_id: number; prompt_id: number; sample_count: number; idempotency_key: string }) =>
    request<SinglePromptV2Status>("/api/v2/single-prompt/analyses", { method: "POST", body: JSON.stringify(payload) }),
  listSinglePromptV2Analyses: (projectId: number, promptId: number) =>
    request<SinglePromptV2AnalysisListItem[]>(`/api/v2/single-prompt/analyses?project_id=${projectId}&prompt_id=${promptId}`),
  getSinglePromptV2Analysis: (analysisId: string, projectId: number, promptId: number) =>
    request<SinglePromptV2Status>(`/api/v2/single-prompt/analyses/${encodeURIComponent(analysisId)}?project_id=${projectId}&prompt_id=${promptId}`),
  retrySinglePromptV2Analysis: (analysisId: string, projectId: number, promptId: number) =>
    request<SinglePromptV2Status>(`/api/v2/single-prompt/analyses/${encodeURIComponent(analysisId)}/retry?project_id=${projectId}&prompt_id=${promptId}`, { method: "POST" }),
  createSinglePromptV2SourcePreparation: (analysisId: string, payload: {
    project_id: number; prompt_id: number; idempotency_key: string; created_by: string;
  }) => request<SinglePromptV2SourcePreparation>(`/api/v2/single-prompt/analyses/${encodeURIComponent(analysisId)}/source-preparation`, { method: "POST", body: JSON.stringify(payload) }),
  getSinglePromptV2SourcePreparation: (analysisId: string, projectId: number, promptId: number) =>
    request<SinglePromptV2SourcePreparation | null>(`/api/v2/single-prompt/analyses/${encodeURIComponent(analysisId)}/source-preparation?project_id=${projectId}&prompt_id=${promptId}`),
  queueSinglePromptV2SourceAutoFetch: (preparationId: string, payload: { project_id: number; prompt_id: number }) =>
    request<SinglePromptV2SourcePreparation>(`/api/v2/single-prompt/source-preparations/${encodeURIComponent(preparationId)}/auto-fetch`, { method: "POST", body: JSON.stringify(payload) }),
  submitSinglePromptV2ManualSource: (preparationId: string, payload: {
    project_id: number; prompt_id: number; source_key: string; expected_row_version: number;
    title: string; clean_text: string; coverage_scope: "FULL_PAGE" | "EXCERPT"; submitted_by: string;
  }) => request<SinglePromptV2SourcePreparation>(`/api/v2/single-prompt/source-preparations/${encodeURIComponent(preparationId)}/manual-content`, { method: "POST", body: JSON.stringify(payload) }),
  waiveSinglePromptV2Source: (preparationId: string, payload: {
    project_id: number; prompt_id: number; source_key: string; expected_row_version: number;
    reason: string; impact: string; waived_by: string;
  }) => request<SinglePromptV2SourcePreparation>(`/api/v2/single-prompt/source-preparations/${encodeURIComponent(preparationId)}/waivers`, { method: "POST", body: JSON.stringify(payload) }),
  freezeSinglePromptV2SourceCompletion: (preparationId: string, payload: {
    project_id: number; prompt_id: number; created_by: string;
  }) => request<SinglePromptV2SourcePreparation>(`/api/v2/single-prompt/source-preparations/${encodeURIComponent(preparationId)}/completion-manifests`, { method: "POST", body: JSON.stringify(payload) }),
  createSinglePromptV2AnswerDiagnosis: (analysisId: string, payload: {
    project_id: number; prompt_id: number; citation_manifest_id: string; citation_manifest_hash: string;
    answer_llm_policy: "ALLOW_EXTERNAL" | "CACHE_ONLY"; idempotency_key: string;
  }) => request<SinglePromptV2DiagnosisStatus>(`/api/v2/single-prompt/analyses/${encodeURIComponent(analysisId)}/answer-diagnoses`, { method: "POST", body: JSON.stringify(payload) }),
  continueSinglePromptV2Evidence: (analysisId: string, diagnosisId: string, payload: {
    project_id: number; prompt_id: number; answer_result_version: string; answer_result_hash: string;
    answer_review_id: string; citation_manifest_id: string; citation_manifest_hash: string;
    completion_manifest_id: string; completion_manifest_hash: string;
    evidence_llm_policy: "ALLOW_EXTERNAL" | "CACHE_ONLY";
  }) => request<SinglePromptV2DiagnosisStatus>(`/api/v2/single-prompt/analyses/${encodeURIComponent(analysisId)}/diagnoses/${encodeURIComponent(diagnosisId)}/evidence-continuations`, { method: "POST", body: JSON.stringify(payload) }),
  createSinglePromptV2Diagnosis: (analysisId: string, payload: { project_id: number; prompt_id: number; idempotency_key: string }) =>
    request<SinglePromptV2DiagnosisStatus>(`/api/v2/single-prompt/analyses/${encodeURIComponent(analysisId)}/diagnoses`, { method: "POST", body: JSON.stringify(payload) }),
  getSinglePromptV2Diagnosis: (analysisId: string, diagnosisId: string, projectId: number, promptId: number) =>
    request<SinglePromptV2DiagnosisStatus>(`/api/v2/single-prompt/analyses/${encodeURIComponent(analysisId)}/diagnoses/${encodeURIComponent(diagnosisId)}?project_id=${projectId}&prompt_id=${promptId}`),
  retrySinglePromptV2Diagnosis: (analysisId: string, diagnosisId: string, projectId: number, promptId: number) =>
    request<SinglePromptV2DiagnosisStatus>(`/api/v2/single-prompt/analyses/${encodeURIComponent(analysisId)}/diagnoses/${encodeURIComponent(diagnosisId)}/retry?project_id=${projectId}&prompt_id=${promptId}`, { method: "POST" }),
  reviseSinglePromptV2Diagnosis: (analysisId: string, diagnosisId: string, resultVersion: string, payload: {
    project_id: number; prompt_id: number; base_result_version: string; base_result_hash: string;
    reviewable_set_hash: string; editor: string; edits: SinglePromptV2DiagnosisEdit[];
  }) => request<SinglePromptV2DiagnosisStatus>(`/api/v2/single-prompt/analyses/${encodeURIComponent(analysisId)}/diagnoses/${encodeURIComponent(diagnosisId)}/results/${encodeURIComponent(resultVersion)}/revisions`, { method: "POST", body: JSON.stringify(payload) }),
  reviewSinglePromptV2Diagnosis: (analysisId: string, diagnosisId: string, resultVersion: string, payload: {
    project_id: number; prompt_id: number; result_hash: string; reviewable_set_hash: string;
    reviewer: string; note: string; decisions: any[];
  }) => request<SinglePromptV2DiagnosisStatus>(`/api/v2/single-prompt/analyses/${encodeURIComponent(analysisId)}/diagnoses/${encodeURIComponent(diagnosisId)}/results/${encodeURIComponent(resultVersion)}/reviews`, { method: "POST", body: JSON.stringify(payload) }),
  getSinglePromptV2StrategyReadiness: (analysisId: string, diagnosisId: string, resultVersion: string, projectId: number, promptId: number) =>
    request<SinglePromptV2StrategyReadiness>(`/api/v2/single-prompt/analyses/${encodeURIComponent(analysisId)}/diagnoses/${encodeURIComponent(diagnosisId)}/results/${encodeURIComponent(resultVersion)}/strategy-readiness?project_id=${projectId}&prompt_id=${promptId}`),
  createSinglePromptV2Strategy: (analysisId: string, diagnosisId: string, resultVersion: string, payload: {
    project_id: number; prompt_id: number; idempotency_key: string; diagnosis_result_hash: string;
    reviewable_set_hash: string; review_id: string; review_snapshot_hash: string; input_projection_hash: string;
  }) => request<SinglePromptV2StrategyStatus>(`/api/v2/single-prompt/analyses/${encodeURIComponent(analysisId)}/diagnoses/${encodeURIComponent(diagnosisId)}/results/${encodeURIComponent(resultVersion)}/strategies`, { method: "POST", body: JSON.stringify(payload) }),
  getSinglePromptV2Strategy: (analysisId: string, diagnosisId: string, strategyId: string, projectId: number, promptId: number) =>
    request<SinglePromptV2StrategyStatus>(`/api/v2/single-prompt/analyses/${encodeURIComponent(analysisId)}/diagnoses/${encodeURIComponent(diagnosisId)}/strategies/${encodeURIComponent(strategyId)}?project_id=${projectId}&prompt_id=${promptId}`),
  reviseSinglePromptV2StrategyPriority: (analysisId: string, diagnosisId: string, strategyId: string, resultVersion: string, payload: {
    project_id: number; prompt_id: number; base_result_version: string; base_result_hash: string;
    reviewable_set_hash: string; ordered_direction_ids: string[]; editor: string; reason: string;
  }) => request<SinglePromptV2StrategyStatus>(`/api/v2/single-prompt/analyses/${encodeURIComponent(analysisId)}/diagnoses/${encodeURIComponent(diagnosisId)}/strategies/${encodeURIComponent(strategyId)}/results/${encodeURIComponent(resultVersion)}/priority-revisions`, { method: "POST", body: JSON.stringify(payload) }),
  reviewSinglePromptV2Strategy: (analysisId: string, diagnosisId: string, strategyId: string, resultVersion: string, payload: {
    project_id: number; prompt_id: number; result_hash: string; reviewable_set_hash: string;
    decision: "ACCEPTED" | "REJECTED"; reviewer: string; note: string;
  }) => request<SinglePromptV2StrategyStatus>(`/api/v2/single-prompt/analyses/${encodeURIComponent(analysisId)}/diagnoses/${encodeURIComponent(diagnosisId)}/strategies/${encodeURIComponent(strategyId)}/results/${encodeURIComponent(resultVersion)}/reviews`, { method: "POST", body: JSON.stringify(payload) }),
  createSinglePromptV2ExecutionProposal: (analysisId: string, diagnosisId: string, strategyId: string, resultVersion: string, payload: {
    project_id: number; prompt_id: number; direction_id: string; idempotency_key: string;
    strategy_result_hash: string; strategy_review_id: string; strategy_review_snapshot_hash: string;
  }) => request<SinglePromptV2ExecutionStatus>(`/api/v2/single-prompt/analyses/${encodeURIComponent(analysisId)}/diagnoses/${encodeURIComponent(diagnosisId)}/strategies/${encodeURIComponent(strategyId)}/results/${encodeURIComponent(resultVersion)}/execution-proposals`, { method: "POST", body: JSON.stringify(payload) }),
  getSinglePromptV2ExecutionProposal: (strategyId: string, proposalId: string, projectId: number, promptId: number) =>
    request<SinglePromptV2ExecutionStatus>(`/api/v2/single-prompt/strategies/${encodeURIComponent(strategyId)}/execution-proposals/${encodeURIComponent(proposalId)}?project_id=${projectId}&prompt_id=${promptId}`),
  reviseSinglePromptV2ExecutionProposal: (strategyId: string, proposalId: string, resultVersion: string, payload: {
    project_id: number; prompt_id: number; base_result_version: string; base_result_hash: string;
    reviewable_set_hash: string; editor: string; edit: Record<string, any>;
  }) => request<SinglePromptV2ExecutionStatus>(`/api/v2/single-prompt/strategies/${encodeURIComponent(strategyId)}/execution-proposals/${encodeURIComponent(proposalId)}/results/${encodeURIComponent(resultVersion)}/revisions`, { method: "POST", body: JSON.stringify(payload) }),
  confirmSinglePromptV2ExecutionProposal: (strategyId: string, proposalId: string, resultVersion: string, payload: {
    project_id: number; prompt_id: number; result_hash: string; reviewable_set_hash: string;
    idempotency_key: string; confirmer: string; note: string;
  }) => request<SinglePromptV2ExecutionStatus>(`/api/v2/single-prompt/strategies/${encodeURIComponent(strategyId)}/execution-proposals/${encodeURIComponent(proposalId)}/results/${encodeURIComponent(resultVersion)}/confirmations`, { method: "POST", body: JSON.stringify(payload) }),
  recordSinglePromptV2Publication: (strategyId: string, proposalId: string, confirmationId: string, payload: Record<string, any>) =>
    request<SinglePromptV2ExecutionStatus>(`/api/v2/single-prompt/strategies/${encodeURIComponent(strategyId)}/execution-proposals/${encodeURIComponent(proposalId)}/confirmations/${encodeURIComponent(confirmationId)}/publications`, { method: "POST", body: JSON.stringify(payload) }),
  getSinglePromptV2RetestReadiness: (projectId: number, promptId: number, confirmationId?: string, publicationId?: string) => {
    const params = new URLSearchParams({ project_id: String(projectId), prompt_id: String(promptId) });
    if (confirmationId) params.set("confirmation_id", confirmationId);
    if (publicationId) params.set("publication_id", publicationId);
    return request<SinglePromptV2RetestReadiness>(`/api/v2/single-prompt/retests/readiness?${params.toString()}`);
  },
  createSinglePromptV2Retest: (payload: Record<string, any>) =>
    request<SinglePromptV2RetestStatus>("/api/v2/single-prompt/retests", { method: "POST", body: JSON.stringify(payload) }),
  getSinglePromptV2Retest: (retestId: string, projectId: number, promptId: number) =>
    request<SinglePromptV2RetestStatus>(`/api/v2/single-prompt/retests/${encodeURIComponent(retestId)}?project_id=${projectId}&prompt_id=${promptId}`),
  startSinglePromptV2RetestSampling: (retestId: string, projectId: number, promptId: number) =>
    request<SinglePromptV2RetestStatus>(`/api/v2/single-prompt/retests/${encodeURIComponent(retestId)}/sampling`, { method: "POST", body: JSON.stringify({ project_id: projectId, prompt_id: promptId }) }),
  retrySinglePromptV2RetestSampling: (retestId: string, projectId: number, promptId: number) =>
    request<SinglePromptV2RetestStatus>(`/api/v2/single-prompt/retests/${encodeURIComponent(retestId)}/sampling/retry`, { method: "POST", body: JSON.stringify({ project_id: projectId, prompt_id: promptId }) }),
  finalizeSinglePromptV2RetestSampling: (retestId: string, projectId: number, promptId: number) =>
    request<SinglePromptV2RetestStatus>(`/api/v2/single-prompt/retests/${encodeURIComponent(retestId)}/sampling/finalize`, { method: "POST", body: JSON.stringify({ project_id: projectId, prompt_id: promptId }) }),
  startSinglePromptV2SemanticMeasurement: (retestId: string, projectId: number, promptId: number, authorizeExternalLlm: boolean) =>
    request<SinglePromptV2RetestStatus>(`/api/v2/single-prompt/retests/${encodeURIComponent(retestId)}/semantic-measurement`, { method: "POST", body: JSON.stringify({ project_id: projectId, prompt_id: promptId, authorize_external_llm: authorizeExternalLlm }) }),
  createSinglePromptV2Comparison: (retestId: string, projectId: number, promptId: number) =>
    request<SinglePromptV2RetestStatus>(`/api/v2/single-prompt/retests/${encodeURIComponent(retestId)}/comparisons`, { method: "POST", body: JSON.stringify({ project_id: projectId, prompt_id: promptId }) }),
  createProject: (payload: unknown) =>
    request<Project>("/api/projects", { method: "POST", body: JSON.stringify(payload) }),
  updateProject: (id: number, payload: unknown) =>
    request<Project>(`/api/projects/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteProject: (id: number) =>
    request<{ deleted: boolean }>(`/api/projects/${id}`, { method: "DELETE" }),
  listPrompts: (projectId: number) => request<Prompt[]>(`/api/projects/${projectId}/prompts`),
  listPlatforms: () => request<Platform[]>("/api/platforms"),
  createPrompt: (projectId: number, payload: unknown) =>
    request<Prompt>(`/api/projects/${projectId}/prompts`, { method: "POST", body: JSON.stringify(payload) }),
  updatePrompt: (projectId: number, promptId: number, payload: unknown) =>
    request<Prompt>(`/api/projects/${projectId}/prompts/${promptId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deletePrompt: (projectId: number, promptId: number) =>
    request<{ deleted: boolean }>(`/api/projects/${projectId}/prompts/${promptId}`, { method: "DELETE" }),
  batchDeletePrompts: (projectId: number, ids: number[]) =>
    request<{ deleted: number }>(`/api/projects/${projectId}/prompts/batch-delete`, { method: "POST", body: JSON.stringify({ ids }) }),
  listTopics: (projectId: number) => request<Topic[]>(`/api/projects/${projectId}/topics`),
  createTopic: (projectId: number, payload: unknown) =>
    request<Topic>(`/api/projects/${projectId}/topics`, { method: "POST", body: JSON.stringify(payload) }),
  listPromptClusters: (projectId: number) =>
    request<PromptCluster[]>(`/api/projects/${projectId}/prompt-clusters`),
  createPromptCluster: (projectId: number, payload: unknown) =>
    request<PromptCluster>(`/api/projects/${projectId}/prompt-clusters`, { method: "POST", body: JSON.stringify(payload) }),
  getMetrics: (projectId: number) => request<Metrics>(`/api/projects/${projectId}/metrics/overview`),
  runMonitor: (projectId: number, payload: unknown) =>
    request<MonitorRun>(`/api/projects/${projectId}/monitor-runs`, { method: "POST", body: JSON.stringify(payload) }),
  listRuns: (projectId: number) => request<MonitorRun[]>(`/api/projects/${projectId}/monitor-runs`),
  listObservations: (projectId: number) => request<Observation[]>(`/api/projects/${projectId}/observations`),
  createBrowserAuditTask: (payload: unknown) =>
    request<{ task_ids: number[]; queued_run_count: number }>("/api/monitoring/tasks", { method: "POST", body: JSON.stringify(payload) }),
  createMonitoringBatch: (projectId: number, payload: unknown) =>
    request<MonitoringBatch>(`/api/projects/${projectId}/monitoring-batches`, { method: "POST", body: JSON.stringify(payload) }),
  listMonitoringBatches: (projectId: number) =>
    request<MonitoringBatch[]>(`/api/projects/${projectId}/monitoring-batches`),
  listBrowserAuditTasks: (projectId: number) =>
    request<BrowserMonitorTask[]>(`/api/monitoring/tasks?project_id=${projectId}`),
  listBrowserAuditRuns: (projectId: number) =>
    request<BrowserMonitorRun[]>(`/api/monitoring/runs?project_id=${projectId}`),
  getBrowserQueueSummary: (projectId: number) =>
    request<BrowserQueueSummary>(`/api/monitoring/queue-summary?project_id=${projectId}`),
  getBrowserAuditRun: (runId: number) =>
    request<BrowserMonitorRunDetail>(`/api/monitoring/runs/${runId}`),
  getRunArtifactContent: (artifactId: number) =>
    request<RunArtifactContent>(`/api/monitoring/artifacts/${artifactId}`),
  importWenxinPluginResult: (payload: unknown) =>
    request<BrowserMonitorRunDetail>("/api/monitoring/imports/wenxin-plugin", { method: "POST", body: JSON.stringify(payload) }),
  retryBrowserAuditRun: (runId: number) =>
    request<BrowserMonitorRun>(`/api/monitoring/runs/${runId}/retry`, { method: "POST" }),
  executeBrowserAuditTask: (taskId: number) =>
    request<BrowserMonitorTask>(`/api/monitoring/tasks/${taskId}/execute`, { method: "POST" }),
  executeQueuedRuns: (projectId: number) =>
    request<{ executed: number }>(`/api/monitoring/queue/execute?project_id=${projectId}`, { method: "POST" }),
  queueDailyPromptSchedules: (projectId: number, executeNow = false) =>
    request<{ task_ids: number[]; queued_run_count: number }>(`/api/monitoring/daily-schedules/queue?project_id=${projectId}&execute_now=${executeNow}`, { method: "POST" }),
  listPromptDailyReports: (projectId: number, promptId?: number) =>
    request<PromptDailyReport[]>(`/api/analytics/projects/${projectId}/prompt-daily-reports${promptId ? `?prompt_id=${promptId}` : ""}`),
  generatePromptDailyReport: (projectId: number, promptId: number, reportDate?: string) =>
    request<PromptDailyReport>(`/api/analytics/projects/${projectId}/prompt-daily-reports/generate?prompt_id=${promptId}${reportDate ? `&report_date=${encodeURIComponent(reportDate)}` : ""}`, { method: "POST" }),
  listOptimizationIssues: (projectId: number) =>
    request<OptimizationIssue[]>(`/api/optimization/projects/${projectId}/issues`),
  listEvidencePackages: (projectId: number, promptId?: number) =>
    request<EvidencePackage[]>(`/api/optimization/projects/${projectId}/evidence-packages${promptId ? `?prompt_id=${promptId}` : ""}`),
  createEvidencePackage: (projectId: number, payload: unknown) =>
    request<EvidencePackage>(`/api/optimization/projects/${projectId}/evidence-packages`, { method: "POST", body: JSON.stringify(payload) }),
  getEvidencePackage: (packageId: number) =>
    request<EvidencePackage>(`/api/optimization/evidence-packages/${packageId}`),
  listStrategyCandidates: (projectId: number, evidencePackageId?: number, experimentId?: number) =>
    request<StrategyCandidate[]>(`/api/optimization/projects/${projectId}/strategy-candidates${[
      evidencePackageId ? `evidence_package_id=${evidencePackageId}` : "",
      experimentId ? `experiment_id=${experimentId}` : "",
    ].filter(Boolean).join("&").replace(/^(.+)/, "?$1")}`),
  generateStrategyCandidates: (projectId: number, payload: unknown) =>
    request<StrategyCandidate[]>(`/api/optimization/projects/${projectId}/strategy-candidates/generate`, { method: "POST", body: JSON.stringify(payload) }),
  generateStrategyCandidatesV2: (projectId: number, payload: unknown) =>
    request<any>(`/api/optimization/projects/${projectId}/strategy-candidates/generate-v2`, { method: "POST", body: JSON.stringify(payload) }),
  generateCurrentStep7StrategyCandidateV1: (projectId: number, promptId: number, payload: unknown) =>
    request<any>(`/api/optimization/projects/${projectId}/prompts/${promptId}/strategy-candidates/generate-current-v1`, { method: "POST", body: JSON.stringify(payload) }),
  getCitationDecisionV1: (projectId: number, promptId: number, evidencePackageId?: number, useAnswerBindingV11?: boolean, init?: RequestInit) =>
    request<any>(`/api/optimization/projects/${projectId}/prompts/${promptId}/citation-decision-v1${[
      evidencePackageId ? `evidence_package_id=${evidencePackageId}` : "",
      typeof useAnswerBindingV11 === "boolean" ? `use_answer_binding_v1_1=${useAnswerBindingV11 ? "true" : "false"}` : "",
    ].filter(Boolean).join("&").replace(/^(.+)/, "?$1")}`, init),
  getDecisionStability: (projectId: number, promptId: number, evidencePackageId?: number) =>
    request<any>(`/api/optimization/projects/${projectId}/prompts/${promptId}/decision-stability${[
      evidencePackageId ? `evidence_package_id=${evidencePackageId}` : "",
    ].filter(Boolean).join("&").replace(/^(.+)/, "?$1")}`),
  confirmCitationDecisionV1: (projectId: number, promptId: number, payload: unknown) =>
    request<any>(`/api/optimization/projects/${projectId}/prompts/${promptId}/citation-decision-v1/confirm`, { method: "POST", body: JSON.stringify(payload) }),
  generateRecommendationAnalysis: (projectId: number, payload: unknown) =>
    request<any>(`/api/optimization/projects/${projectId}/recommendation-analysis`, { method: "POST", body: JSON.stringify(payload) }),
  getRecommendationLandscape: (projectId: number, promptId: number, snapshotId?: number) =>
    request<any>(`/api/optimization/projects/${projectId}/recommendation-landscape?prompt_id=${promptId}${snapshotId ? `&snapshot_id=${snapshotId}` : ""}`),
  listRecommendationSnapshots: (projectId: number, promptId?: number, limit = 30) =>
    request<any[]>(`/api/optimization/projects/${projectId}/recommendation-snapshots?${[
      promptId ? `prompt_id=${promptId}` : "",
      `limit=${limit}`,
    ].filter(Boolean).join("&")}`),
  listRecommendationClaims: (snapshotId: number) =>
    request<any[]>(`/api/optimization/recommendation-claims?snapshot_id=${snapshotId}`),
  reviewRecommendationClaim: (claimId: number, payload: unknown) =>
    request<any>(`/api/optimization/recommendation-claims/${claimId}/review`, { method: "POST", body: JSON.stringify(payload) }),
  listRecommendationEntities: (snapshotId: number) =>
    request<any[]>(`/api/optimization/recommendation-entities?snapshot_id=${snapshotId}`),
  reviewRecommendationEntity: (entityId: number, payload: unknown) =>
    request<any>(`/api/optimization/recommendation-entities/${entityId}/review`, { method: "POST", body: JSON.stringify(payload) }),
  listRecommendationReasons: (snapshotId: number) =>
    request<any[]>(`/api/optimization/recommendation-reasons?snapshot_id=${snapshotId}`),
  reviewRecommendationReason: (reasonId: number, payload: unknown) =>
    request<any>(`/api/optimization/recommendation-reasons/${reasonId}/review`, { method: "POST", body: JSON.stringify(payload) }),
  listDecisionSelectionCriteria: (snapshotId: number) =>
    request<any[]>(`/api/optimization/decision-market/selection-criteria?snapshot_id=${snapshotId}`),
  reviewDecisionSelectionCriterion: (criterionId: number, payload: unknown) =>
    request<any>(`/api/optimization/decision-market/selection-criteria/${criterionId}/review`, { method: "POST", body: JSON.stringify(payload) }),
  listDecisionAnswerSemanticFacts: (snapshotId: number) =>
    request<any[]>(`/api/optimization/decision-market/answer-semantic-facts?snapshot_id=${snapshotId}`),
  getDecisionPassageSupport: (snapshotId: number) =>
    request<any>(`/api/optimization/decision-market/passage-support?snapshot_id=${snapshotId}`),
  reviewDecisionAnswerSemanticFact: (factId: number, payload: unknown) =>
    request<any>(`/api/optimization/decision-market/answer-semantic-facts/${factId}/review`, { method: "POST", body: JSON.stringify(payload) }),
  listDecisionCapabilityClaims: (snapshotId: number) =>
    request<any[]>(`/api/optimization/decision-market/capability-claims?snapshot_id=${snapshotId}`),
  reviewDecisionCapabilityClaim: (claimId: number, payload: unknown) =>
    request<any>(`/api/optimization/decision-market/capability-claims/${claimId}/review`, { method: "POST", body: JSON.stringify(payload) }),
  listDecisionEvidenceAdoptions: (snapshotId: number) =>
    request<any[]>(`/api/optimization/decision-market/evidence-adoptions?snapshot_id=${snapshotId}`),
  reviewDecisionEvidenceAdoption: (adoptionId: number, payload: unknown) =>
    request<any>(`/api/optimization/decision-market/evidence-adoptions/${adoptionId}/review`, { method: "POST", body: JSON.stringify(payload) }),
  listDecisionGaps: (snapshotId: number) =>
    request<any[]>(`/api/optimization/decision-market/gaps?snapshot_id=${snapshotId}`),
  reviewDecisionGap: (gapId: number, payload: unknown) =>
    request<any>(`/api/optimization/decision-market/gaps/${gapId}/review`, { method: "POST", body: JSON.stringify(payload) }),
  listTargetBrandCapabilityTruths: (projectId: number) =>
    request<any[]>(`/api/optimization/projects/${projectId}/target-brand-capability-truths`),
  upsertTargetBrandCapabilityTruth: (projectId: number, payload: unknown) =>
    request<any>(`/api/optimization/projects/${projectId}/target-brand-capability-truths`, { method: "POST", body: JSON.stringify(payload) }),
  createDecisionExperimentDraft: (snapshotId: number, payload: unknown = {}) =>
    request<any>(`/api/optimization/decision-market/snapshots/${snapshotId}/experiment-draft`, { method: "POST", body: JSON.stringify(payload) }),
  reviewStrategyCandidate: (candidateId: number, payload: unknown) =>
    request<StrategyCandidate>(`/api/optimization/strategy-candidates/${candidateId}/review`, { method: "POST", body: JSON.stringify(payload) }),
  strategyToExperimentPlan: (candidateId: number) =>
    request<Record<string, any>>(`/api/optimization/strategy-candidates/${candidateId}/experiment-plan`, { method: "POST" }),
  confirmStrategyExecutionPlan: (candidateId: number, payload: unknown) =>
    request<Record<string, any>>(`/api/optimization/strategy-candidates/${candidateId}/execution-plan`, { method: "POST", body: JSON.stringify(payload) }),
  getExecutionProposalShadow: (projectId: number, promptId: number, candidateId?: number) =>
    request<any>(`/api/optimization/workflow/${projectId}/${promptId}/execution-proposal-shadow${candidateId ? `?candidate_id=${candidateId}` : ""}`),
  revalidateExecutionProposal: (projectId: number, promptId: number, payload: unknown) =>
    request<any>(`/api/optimization/workflow/${projectId}/${promptId}/execution-proposal/revalidate`, { method: "POST", body: JSON.stringify(payload) }),
  revalidateExecutionProposalPortfolio: (projectId: number, promptId: number, payload: unknown) =>
    request<any>(`/api/optimization/workflow/${projectId}/${promptId}/execution-proposal/portfolio/revalidate`, { method: "POST", body: JSON.stringify(payload) }),
  listPageSnapshots: (projectId: number, experimentId?: number) =>
    request<any[]>(`/api/optimization/projects/${projectId}/page-snapshots${experimentId ? `?experiment_id=${experimentId}` : ""}`),
  capturePageSnapshot: (projectId: number, payload: unknown) =>
    request<any>(`/api/optimization/projects/${projectId}/page-snapshots`, { method: "POST", body: JSON.stringify(payload) }),
  generateOptimizationIssues: (projectId: number) =>
    request<OptimizationIssue[]>(`/api/optimization/projects/${projectId}/issues/generate-candidates`, { method: "POST" }),
  confirmOptimizationIssue: (issueId: number) =>
    request<OptimizationIssue>(`/api/optimization/issues/${issueId}/confirm`, { method: "POST" }),
  rejectOptimizationIssue: (issueId: number, note: string) =>
    request<OptimizationIssue>(`/api/optimization/issues/${issueId}/reject`, { method: "POST", body: JSON.stringify({ note }) }),
  getOptimizationEvidenceChain: (issueId: number) =>
    request<OptimizationEvidenceChain>(`/api/optimization/issues/${issueId}/evidence-chain`),
  createOptimizationAction: (issueId: number, payload: unknown) =>
    request<OptimizationAction>(`/api/optimization/issues/${issueId}/actions`, { method: "POST", body: JSON.stringify(payload) }),
  releaseOptimizationAction: (actionId: number, payload: unknown) =>
    request<OptimizationAction>(`/api/optimization/actions/${actionId}/release`, { method: "POST", body: JSON.stringify(payload) }),
  createOptimizationExperiment: (actionId: number, payload: unknown) =>
    request<OptimizationExperiment>(`/api/optimization/actions/${actionId}/experiments`, { method: "POST", body: JSON.stringify(payload) }),
  listOptimizationHypotheses: (experimentId: number) =>
    request<any[]>(`/api/optimization/experiments/${experimentId}/hypotheses`),
  createOptimizationHypothesis: (experimentId: number, payload: unknown) =>
    request<any>(`/api/optimization/experiments/${experimentId}/hypotheses`, { method: "POST", body: JSON.stringify(payload) }),
  lockOptimizationBaseline: (experimentId: number, runIds: number[]) =>
    request<OptimizationExperiment>(`/api/optimization/experiments/${experimentId}/lock-baseline`, { method: "POST", body: JSON.stringify({ run_ids: runIds }) }),
  confirmExperimentRelease: (experimentId: number, payload: unknown) =>
    request<OptimizationExperiment>(`/api/optimization/experiments/${experimentId}/release-confirmation`, { method: "POST", body: JSON.stringify(payload) }),
  startOptimizationValidation: (experimentId: number) =>
    request<OptimizationExperiment>(`/api/optimization/experiments/${experimentId}/start-validation`, { method: "POST" }),
  queueOptimizationRetest: (experimentId: number, payload: unknown) =>
    request<{ experiment_id: number; batch_id: number; task_id: number; run_ids: number[]; queued_run_count: number; status: string }>(
      `/api/optimization/experiments/${experimentId}/queue-retest`,
      { method: "POST", body: JSON.stringify(payload) }
    ),
  attachOptimizationValidationRuns: (experimentId: number, runIds: number[]) =>
    request<OptimizationExperiment>(`/api/optimization/experiments/${experimentId}/attach-validation-runs`, { method: "POST", body: JSON.stringify({ run_ids: runIds }) }),
  analyzeOptimizationExperiment: (experimentId: number) =>
    request<OptimizationExperiment>(`/api/optimization/experiments/${experimentId}/analyze`, { method: "POST" }),
  confirmOptimizationConclusion: (experimentId: number, payload: unknown) =>
    request<OptimizationExperiment>(`/api/optimization/experiments/${experimentId}/confirm-conclusion`, { method: "POST", body: JSON.stringify(payload) }),
  getValidationDashboard: async (projectId: number, promptId?: number): Promise<ValidationDashboard> => {
    const query = promptId ? `citation_limit=10&prompt_id=${promptId}` : "citation_limit=10";
    const data = await request<ValidationDashboardWire>(`/api/analytics/projects/${projectId}/validation-dashboard?${query}`);
    return {
      project_id: data.project_id,
      sample_label: data.sample_label,
      prompts: {
        total: data.prompts.total_prompts,
        executed: data.prompts.prompts_with_runs,
        clusters: data.prompts.total_clusters,
        valid_runs: data.prompts.valid_samples,
        sample_runs: data.prompts.collected_samples
      },
      presence: [data.brand_presence, ...data.competitor_presence].map((row) => ({
        name: row.name,
        kind: row.entity_type === "brand" ? "brand" : "competitor",
        appeared_runs: row.observed_runs,
        sample_runs: row.sample_runs
      })),
      recommendation: {
        explicit: data.recommendation_presence.explicit_recommendation,
        mentioned: data.recommendation_presence.general_mention,
        absent: data.recommendation_presence.not_observed,
        sample_runs: data.recommendation_presence.sample_runs
      },
      top_domains: data.top_citation_domains.map((row) => ({
        value: row.domain, domain: row.domain, run_count: row.run_count, prompt_count: row.prompt_count
      })),
      top_urls: data.top_citation_urls.map((row) => ({
        value: row.url, title: row.title, domain: row.domain, run_count: row.run_count, prompt_count: row.prompt_count
      })),
      quality: {
        total_runs: data.data_quality.total_runs,
        successful_runs: data.data_quality.success,
        blocked_runs: data.data_quality.blocked,
        collector_failed_runs: data.data_quality.collector_failed,
        complete_reference_runs: data.data_quality.references.complete_runs,
        eligible_reference_runs: data.data_quality.references.assessed_runs,
        parsed_references: data.data_quality.references.parsed_reference_count,
        resolved_urls: data.data_quality.references.resolved_url_count
      }
    };
  },

  getCitationRanking: (packageId: number) =>
    request(`/api/optimization/evidence-packages/${packageId}/citation-ranking`),
};
