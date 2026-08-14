import type { BrowserMonitorRun, BrowserMonitorRunDetail, BrowserMonitorTask, BrowserQueueSummary, EvidencePackage, Metrics, MonitoringBatch, MonitorRun, Observation, OptimizationAction, OptimizationEvidenceChain, OptimizationExperiment, OptimizationIssue, Platform, Project, Prompt, PromptCluster, PromptDailyReport, RunArtifactContent, StrategyCandidate, Topic, ValidationDashboard } from "../types";

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
      message = parsed.detail || parsed.message || message;
    } catch {
      // Non-JSON error bodies are surfaced as-is.
    }
    if (response.status === 405) {
      message = "接口方法不匹配，请确认后端已重启到最新版本";
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  listProjects: () => request<Project[]>("/api/projects"),
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
  getValidationDashboard: async (projectId: number): Promise<ValidationDashboard> => {
    const data = await request<ValidationDashboardWire>(`/api/analytics/projects/${projectId}/validation-dashboard?citation_limit=10`);
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
