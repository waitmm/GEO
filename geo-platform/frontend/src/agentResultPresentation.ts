export const resultHeadings = [
  "GEO 诊断与依据",
  "品牌表现与证据缺口",
  "优化策略与渠道",
  "完整正文",
  "QA 与事实限制",
  "复测计划",
] as const;

export type ResultHeading = typeof resultHeadings[number];

export function splitAgentResult(markdown: string): Record<ResultHeading, string> {
  const sections = Object.fromEntries(resultHeadings.map(heading => [heading, ""])) as Record<ResultHeading, string>;
  const headingPattern = /^##\s+(.+?)\s*$/gm;
  const matches = [...markdown.matchAll(headingPattern)];
  matches.forEach((match, index) => {
    const heading = match[1].trim() as ResultHeading;
    if (!resultHeadings.includes(heading)) return;
    const start = (match.index || 0) + match[0].length;
    const end = index + 1 < matches.length ? matches[index + 1].index || markdown.length : markdown.length;
    sections[heading] = markdown.slice(start, end).trim();
  });
  return sections;
}

export function savedResultLabel(modelCalls: number, status: string) {
  if (status === "SUCCEEDED" && modelCalls > 0) return "已保存的真实模型结果";
  if (status === "SUCCEEDED") return "已保存结果（来源待核对）";
  if (status === "WAITING_AUTHORIZATION") return "等待服务启动的新任务";
  return "历史任务记录";
}

export type AggregateObservationSummary = {
  status: "VERIFIED_ABSENCE" | "VERIFIED_PRESENCE" | "UNKNOWN";
  statusLabel: string;
  includedCount: number;
  excludedCount: number;
  observationText: string;
  limitation: string;
};

export function aggregateObservationSummary(result: any): AggregateObservationSummary | null {
  const pack = result?.result?.evidence_pack || result?.evidence_pack;
  const sets = Array.isArray(pack?.aggregate_evidence_sets) ? pack.aggregate_evidence_sets : [];
  if (sets.length !== 1) return null;
  const frozenSet = sets[0] || {};
  const observations = Array.isArray(pack?.verified_brand_observations)
    ? pack.verified_brand_observations : [];
  const status = frozenSet.observation_status === "SERVER_VERIFIED_ABSENCE"
    ? "VERIFIED_ABSENCE"
    : frozenSet.observation_status === "SERVER_VERIFIED_PRESENCE"
      ? "VERIFIED_PRESENCE" : "UNKNOWN";
  return {
    status,
    statusLabel: status === "VERIFIED_ABSENCE" ? "已核对：范围内未检测到品牌字面出现"
      : status === "VERIFIED_PRESENCE" ? "已核对：范围内检测到品牌字面出现"
        : "观察范围仍有待核对项",
    includedCount: Array.isArray(frozenSet.members) ? frozenSet.members.length : 0,
    excludedCount: Array.isArray(frozenSet.excluded_members) ? frozenSet.excluded_members.length : 0,
    observationText: String(observations[0]?.canonical_text || ""),
    limitation: "该观察只核对冻结回答中的品牌字面出现，不证明推荐、产品能力、排名或因果关系。",
  };
}
