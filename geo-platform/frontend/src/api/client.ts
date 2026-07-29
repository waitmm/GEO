import type { BrowserMonitorRun, BrowserMonitorRunDetail, BrowserMonitorTask, BrowserQueueSummary, Metrics, MonitoringBatch, MonitorRun, Observation, Platform, Project, Prompt, PromptCluster, RunArtifactContent, Topic, ValidationDashboard } from "../types";

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
    throw new Error(detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

export const api = {
  listProjects: () => request<Project[]>("/api/projects"),
  createProject: (payload: unknown) =>
    request<Project>("/api/projects", { method: "POST", body: JSON.stringify(payload) }),
  listPrompts: (projectId: number) => request<Prompt[]>(`/api/projects/${projectId}/prompts`),
  listPlatforms: () => request<Platform[]>("/api/platforms"),
  createPrompt: (projectId: number, payload: unknown) =>
    request<Prompt>(`/api/projects/${projectId}/prompts`, { method: "POST", body: JSON.stringify(payload) }),
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
  }
};
