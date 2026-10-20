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
  if (status === "WAITING_AUTHORIZATION") return "待管理员授权的新任务";
  return "历史任务记录";
}
