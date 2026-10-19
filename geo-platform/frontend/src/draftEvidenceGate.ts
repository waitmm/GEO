export type DraftEligibility = {
  status?: string; code?: string; direction_id?: string; evidence_ids?: string[];
  requirements?: Record<string, boolean>; gaps?: string[]; next_actions?: string[];
};

type DraftEligibilityTask = {
  blocker_code?: string; blocker_detail?: string; objects?: Record<string, unknown>;
};

export function draftEligibility(task: DraftEligibilityTask): DraftEligibility | undefined {
  const value = task.objects?.draft_eligibility;
  return value && typeof value === "object" && !Array.isArray(value) ? value as DraftEligibility : undefined;
}

export function draftRequestBlocked(task: DraftEligibilityTask, eligibility = draftEligibility(task)) {
  const legacyInvalidDraftEvidence = task.blocker_code === "FAILED_PARSE"
    && /(?:^|\b)INVALID_DRAFT_EVIDENCE(?:\b|$)/.test(task.blocker_detail || "");
  return eligibility?.status === "BLOCKED"
    || ["DRAFT_EVIDENCE_NOT_QUALIFIED", "INVALID_DRAFT_EVIDENCE"].includes(eligibility?.code || task.blocker_code || "")
    || legacyInvalidDraftEvidence;
}
