export type OptimizationSelection =
  | { kind: "TASK"; taskId: string }
  | { kind: "DELIVERY"; proposalId: string; resultVersion: string }
  | null;

type VersionedTask = {
  task_id: string;
  objects: { deliveries?: { proposal_id: string; result_version: string }[] };
};

export function readOptimizationSelection(search: string, analysisId: string): OptimizationSelection {
  const params = new URLSearchParams(search);
  if (params.get("v2_analysis") !== analysisId) return null;
  if (params.has("optimization_task")) return { kind: "TASK", taskId: params.get("optimization_task") || "" };
  if (params.has("v2_execution_proposal") || params.has("v2_execution_result")) {
    return { kind: "DELIVERY", proposalId: params.get("v2_execution_proposal") || "",
      resultVersion: params.get("v2_execution_result") || "" };
  }
  return null;
}

export function resolveOptimizationSelection<T extends VersionedTask>(tasks: T[], selected: OptimizationSelection): T | undefined {
  if (!selected) return tasks[0];
  if (selected.kind === "TASK") return tasks.find(t => t.task_id === selected.taskId);
  if (!selected.proposalId || !selected.resultVersion) return undefined;
  return tasks.find(t => t.objects.deliveries?.some(d =>
    d.proposal_id === selected.proposalId && d.result_version === selected.resultVersion));
}
