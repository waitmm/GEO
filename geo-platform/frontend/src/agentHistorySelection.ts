export type AgentHistorySelection = {
  selectedRunId?: string;
  loadedRunId?: string;
  loading: boolean;
  error: string;
};

export function beginAgentHistorySelection(runId: string): AgentHistorySelection {
  return { selectedRunId: runId, loadedRunId: undefined, loading: true, error: "" };
}

export function completeAgentHistorySelection(state: AgentHistorySelection, runId: string): AgentHistorySelection {
  return state.selectedRunId === runId ? { ...state, loadedRunId: runId, loading: false, error: "" } : state;
}

export function failAgentHistorySelection(state: AgentHistorySelection, runId: string, error: string): AgentHistorySelection {
  return state.selectedRunId === runId ? { ...state, loadedRunId: undefined, loading: false, error } : state;
}

export function isCurrentAgentHistoryResult(state: AgentHistorySelection, runId: string | undefined): boolean {
  return Boolean(runId && state.selectedRunId === runId && state.loadedRunId === runId);
}

export function isCurrentAgentHistoryLoad(selectedRunId: string | undefined, attemptedRunId: string | undefined): boolean {
  return Boolean(attemptedRunId && selectedRunId === attemptedRunId);
}

export function isCurrentAgentHistoryRequest(requestEpoch: number, currentEpoch: number): boolean {
  return requestEpoch === currentEpoch;
}

export function agentHistoryTaskControls(status: string | undefined): { restart: boolean; stop: boolean } {
  return {
    restart: status === "WAITING_AUTHORIZATION",
    stop: Boolean(status && ["QUEUED", "RUNNING", "WAITING_AUTHORIZATION"].includes(status)),
  };
}

export type AgentHistoryOperation = {
  generation: number;
  scopeKey: string;
  runId?: string;
  resultVersion?: string;
};

export function isCurrentAgentHistoryOperation(
  operation: AgentHistoryOperation,
  current: { generation: number; scopeKey: string; runId?: string; resultVersion?: string },
): boolean {
  return operation.generation === current.generation
    && operation.scopeKey === current.scopeKey
    && (operation.runId === undefined || operation.runId === current.runId)
    && (operation.resultVersion === undefined || operation.resultVersion === current.resultVersion);
}
