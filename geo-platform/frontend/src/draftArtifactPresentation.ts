type UnknownRecord = Record<string, unknown>;

export type ArtifactEvidenceQaSummary = {
  evidenceCount: number;
  evidenceTypes: string[];
  evidenceLocations: string[];
  qualification: string;
  qualificationTone: "success" | "warning" | "error";
  issues: string[];
  verifyFirst: boolean;
};

const evidenceTypeLabels: Record<string, string> = {
  source: "来源资料", truth: "已确认事实", citation: "引用观察", answer: "回答记录",
};
const issueLabels: Record<string, string> = {
  ARTIFACT_BODY_REQUIRED: "稿件正文为空",
  ARTIFACT_VALIDATION_FAILED: "稿件未通过独立校验",
  DELIVERABLE_INCOMPLETE: "内容尚未完成，无法作为可编辑成稿",
  DELIVERABLE_PLACEHOLDER: "内容含有待补充的占位文字",
  FAQ_STRUCTURE_REQUIRED: "常见问题至少需要两个明确问题与回答",
  L3_VERIFY_FIRST_REQUIRED: "缺少“先核实”提示",
  NUMERIC_CLAIM_WITHOUT_AUTHORITY: "数字或价格表述缺少可核对来源",
  CITATION_CHANNEL_EVIDENCE_REQUIRED: "渠道分析缺少冻结回答中的引用依据",
};

function record(value: unknown): UnknownRecord | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as UnknownRecord : undefined;
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function issueText(value: unknown): string {
  if (typeof value === "string") return issueLabels[value] || value;
  const item = record(value);
  if (!item) return "发现需要处理的问题";
  const code = text(item.code);
  const detail = text(item.detail);
  return [issueLabels[code] || code, detail && detail !== issueLabels[code] ? detail : ""].filter(Boolean).join("：") || "发现需要处理的问题";
}

function failureIssues(failure: { code: string; detail: string }): string[] {
  const summary = issueText(failure.code);
  if (!failure.detail.trim()) return [summary];
  try {
    const parsed = JSON.parse(failure.detail) as unknown;
    const details = (Array.isArray(parsed) ? parsed : [parsed]).map(issueText).filter(Boolean);
    return [...new Set([summary, ...details])];
  } catch {
    // Provider and validation failures that are not structured JSON still need
    // their useful detail. Structured validation payloads are converted above
    // so operators never have to read raw JSON in the primary result view.
    return [summary, failure.detail];
  }
}

function evidenceLocation(value: unknown): string {
  const item = record(value);
  if (!item) return text(value);
  const location = text(item.section) || text(item.section_id) || text(item.source_title) || text(item.title)
    || text(item.source_url) || text(item.url) || text(item.id) || text(item.evidence_id);
  return location || "已冻结证据（未提供可读定位）";
}

function evidenceType(value: unknown): string {
  const item = record(value);
  const kind = item && (text(item.kind) || text(item.type) || text(item.source_type));
  return evidenceTypeLabels[kind || ""] || (kind ? `其他证据（${kind}）` : "冻结证据");
}

function includesVerifyFirst(value: unknown): boolean {
  if (typeof value === "string") {
    const normalized = value.trim().toUpperCase();
    if (["FALSE", "NO", "NOT_VERIFY_FIRST", "NO_VERIFY_FIRST", "NOT_REQUIRED"].includes(normalized)
      || /(?:无需|不需|不用)(?:核实|核验|VERIFY_FIRST)/i.test(value)) return false;
    return normalized.includes("VERIFY_FIRST") || value.includes("待核实") || value.includes("待核验");
  }
  if (Array.isArray(value)) return value.some(includesVerifyFirst);
  const item = record(value);
  return !!item && Object.entries(item).some(([key, entry]) => {
    // A key merely named verify_first is not itself a warning: the immutable
    // payload must explicitly set it to true. Other qualification/issue text
    // is detected by its actual value during the recursive walk.
    const verificationFlag = key.toLowerCase().includes("verify") || key.toLowerCase().includes("核验");
    return (verificationFlag && entry === true) || includesVerifyFirst(entry);
  });
}

/** Converts the immutable API payload into operator-facing copy without changing it. */
export function summarizeArtifactEvidenceQa(evidence: UnknownRecord, qa: UnknownRecord, status: string, failure?: { code: string; detail: string } | null): ArtifactEvidenceQaSummary {
  const refs = [...list(evidence.action_evidence_refs), ...list(evidence.result_evidence_references)];
  const locations = [...new Set(refs.map(evidenceLocation).filter(Boolean))];
  const validation = record(qa.artifact_validation);
  const validationStatus = text(validation?.status).toUpperCase();
  const issues = [...list(validation?.issues), ...list(qa.issues)].map(issueText);
  if (failure) issues.unshift(...failureIssues(failure));
  const verifyFirst = includesVerifyFirst(qa) || includesVerifyFirst(evidence);
  const failed = status !== "SUCCESS" || validationStatus === "FAIL" || !!failure;
  const qualification = failed ? "未通过独立校验" : validationStatus === "PASS" || status === "SUCCESS" ? "校验通过" : "待核对";
  return {
    evidenceCount: refs.length,
    evidenceTypes: [...new Set(refs.map(evidenceType))],
    evidenceLocations: locations,
    qualification,
    qualificationTone: failed ? "error" : qualification === "校验通过" ? "success" : "warning",
    issues: [...new Set(issues)],
    verifyFirst,
  };
}

export const feedbackRatingLabel: Record<string, string> = {
  USABLE: "可用", NEEDS_CHANGES: "需修改", UNUSABLE: "不可用",
};
