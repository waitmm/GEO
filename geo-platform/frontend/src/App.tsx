import { useEffect, useMemo, useState } from "react";
import type { Key } from "react";
import {
  Alert, Button, Card, Checkbox, Col, Descriptions, Divider, Drawer, Empty, Form, Input, InputNumber,
  Layout, Menu, Modal, Popconfirm, Progress, Row, Select, Space, Statistic, Table, Tag, Typography, message
} from "antd";
import { BarChart3, ExternalLink, FileText, ListChecks, Monitor, Play, Plus, RefreshCw, Settings, ShieldCheck } from "lucide-react";
import { api } from "./api/client";
import type {
  BrowserMonitorRun, BrowserMonitorRunDetail, BrowserQueueSummary, Project, Prompt, PromptCluster, RunArtifactContent, Topic,
  ValidationDashboard, ValidationPresence, ValidationSource
} from "./types";

const { Header, Sider, Content } = Layout;
const { Title, Text, Link } = Typography;
type PageKey = "validation" | "recommendation" | "optimization" | "config" | "runs" | "ranking" | "golden";

const PAGE_META: Record<PageKey, { title: string; subtitle: string }> = {
  validation: { title: "监测总览", subtitle: "看品牌当前表现，不在这里下最终策略" },
  recommendation: { title: "决策诊断", subtitle: "解释单个问题为什么没进入候选/推荐，并送入最终策略" },
  optimization: { title: "最终策略", subtitle: "统一承接证据、策略、实验和人工确认" },
  config: { title: "问题配置", subtitle: "维护问题、主题、采样计划和项目基础信息" },
  runs: { title: "采集记录", subtitle: "查看每次采集、原答案、引用和检索候选" },
  ranking: { title: "引用资料", subtitle: "以最终引用资料为主分析来源结构和页面价值" },
  golden: { title: "证据标注", subtitle: "底层 claim、引用片段、证据对齐与人工标注" },
};

const emptyQueue: BrowserQueueSummary = {
  project_id: null, queued: 0, pending: 0, running: 0, success: 0,
  partial_success: 0, failed: 0, blocked: 0, total: 0, latest_run_id: null,
  latest_status: "", latest_stage: "", latest_error_type: ""
};

function statusTag(status: string) {
  const labels: Record<string, string> = {
    success: "成功", partial_success: "部分成功", failed: "采集失败",
    blocked: "被拦截", running: "运行中", pending: "等待中", queued: "队列中"
  };
  const colors: Record<string, string> = {
    success: "green", partial_success: "gold", failed: "red", blocked: "volcano",
    running: "processing", pending: "default", queued: "blue"
  };
  return <Tag color={colors[status]}>{labels[status] || status || "未知"}</Tag>;
}

function formatDateTime(v: string | null | undefined) {
  if (!v) return "-";
  try {
    const raw = String(v).trim();
    const normalized = raw.includes("T") ? raw : raw.replace(" ", "T");
    const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(normalized);
    const date = new Date(hasTimezone ? normalized : `${normalized}Z`);
    return new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(date);
  }
  catch { return v; }
}
function safeRate(n: number, d: number) {
  return d ? Math.round((n / d) * 1000) / 10 : 0;
}
function formatMetric(metric?: { numerator?: number; denominator?: number; value?: number | null }) {
  if (!metric) return "-";
  const value = typeof metric.value === "number" ? `，${Math.round(metric.value * 1000) / 10}%` : "";
  return `${metric.numerator ?? 0}/${metric.denominator ?? 0}${value}`;
}

function reviewStatusLabel(status?: string) {
  const labels: Record<string, string> = {
    UNREVIEWED: "待审核",
    PENDING_REVIEW: "待审核",
    ACCEPTED: "已接受",
    ACCEPTED_WITH_EDITS: "编辑后接受",
    DEFERRED: "暂缓",
    CONFIRMED: "已确认",
    EDITED: "已编辑",
    REFINED: "已修正",
    REJECTED: "已拒绝",
    MISLABELED: "分类错误",
    AMBIGUOUS: "存在歧义",
  };
  return labels[status || ""] || status || "待审核";
}

function evidenceStatusLabel(status?: string, fallback?: string) {
  const labels: Record<string, string> = {
    LINKED: "已关联引用",
    PARTIALLY_LINKED: "部分关联引用",
    UNLINKED: "未关联引用",
  };
  return fallback || labels[status || ""] || status || "未判断";
}

function passageAlignmentColor(status?: string) {
  const colors: Record<string, string> = {
    DIRECT_TEXT_MATCH: "green",
    NEAR_TEXT_MATCH: "blue",
    UNRESOLVED: "orange",
    UNCERTAIN: "gold",
  };
  return colors[status || ""] || "default";
}

function brandStageLabel(stage?: string) {
  const labels: Record<string, string> = {
    TOP_RECOMMENDED: "第一推荐",
    EXPLICITLY_RECOMMENDED: "明确推荐",
    SOLUTION_CANDIDATE: "进入候选",
    CAPABILITY_RECOGNIZED: "能力被识别",
    NEED_ASSOCIATED: "需求已关联",
    MENTIONED: "仅被提及",
    ABSENT: "未出现",
  };
  return labels[stage || ""] || stage || "-";
}

function truthSourceLabel(source?: string) {
  const labels: Record<string, string> = {
    MANUAL_CONFIRMED: "人工确认",
    OFFICIAL_PAGE: "官方页面",
    PRODUCT_DOC: "产品文档",
    INTERNAL_SYSTEM: "内部系统",
    OTHER: "其他来源",
  };
  return labels[source || ""] || source || "未确认";
}

function truthStatusLabel(status?: string) {
  const labels: Record<string, string> = {
    SUPPORTED: "真实支持",
    PARTIALLY_SUPPORTED: "部分支持",
    NOT_SUPPORTED: "不支持",
    UNKNOWN: "未知，待人工确认",
  };
  return labels[status || ""] || status || "未知，待人工确认";
}

function entityRoleLabel(role?: string) {
  const labels: Record<string, string> = {
    SOLUTION_PROVIDER: "解决方案提供者",
    BRAND: "品牌",
    CATEGORY: "品类",
    PLATFORM: "平台",
    CHANNEL: "渠道",
    AUTHORITY: "规则/权威方",
    SOURCE: "来源",
    FEATURE: "功能",
    METHOD: "方法",
    OTHER: "其他",
  };
  return labels[role || ""] || role || "未知";
}

function metricLabel(metric?: string) {
  const labels: Record<string, string> = {
    target_page_retrieval_rate: "目标页进入检索候选率",
    target_page_conversion_rate: "目标页引用转化率",
    brand_mention_rate: "品牌提及率",
    brand_recommendation_rate: "品牌明确推荐率",
    official_reference_rate: "官方来源引用率",
    avg_reference_count: "平均引用数量",
    need_association_rate: "需求关联率",
    capability_recognition_rate: "能力识别率",
    candidate_capture_rate: "候选进入率",
    evidence_link_rate: "证据关联率",
    explicit_recommendation_rate: "明确推荐率",
    manual_review: "人工审核",
  };
  return labels[metric || ""] || metric || "-";
}

function directionLabel(direction?: string) {
  const labels: Record<string, string> = {
    increase: "提升",
    decrease: "降低",
    maintain: "保持",
  };
  return labels[direction || ""] || direction || "-";
}

function interventionFamilyLabel(value?: string) {
  const labels: Record<string, string> = {
    OFFICIAL_PAGE_UPDATE: "更新官网现有页面",
    OFFICIAL_NEW_PAGE: "新建官网页面",
    OWNED_CONTENT_EXTENSION: "扩展自有内容",
    EXTERNAL_PLATFORM_ARTICLE: "外部平台文章",
    EXTERNAL_PLATFORM_QA: "外部问答内容",
    EXTERNAL_PLATFORM_CONTENT: "外部平台内容",
    VIDEO_CONTENT: "视频内容",
    THIRD_PARTY_REVIEW: "第三方评测",
    THIRD_PARTY_COMPARISON: "第三方对比",
    CONTENT_REFRESH: "内容刷新",
    UNRESOLVED: "待确认",
    NO_ACTION: "不建议干预",
  };
  return labels[value || ""] || value || "-";
}

function runEligibilityColor(status?: string) {
  const colors: Record<string, string> = {
    ELIGIBLE: "green",
    PARTIAL: "gold",
    INELIGIBLE: "red",
    UNKNOWN: "orange",
  };
  return colors[status || ""] || "default";
}

function decisionSpaceColor(status?: string) {
  const colors: Record<string, string> = {
    NO_BRAND_DECISION_SPACE: "default",
    SOLUTION_CHOICE_SPACE: "blue",
    BRAND_CANDIDATE_SPACE: "geekblue",
    BRAND_RECOMMENDATION_PRESENT: "green",
    BRAND_COMPARISON_PRESENT: "purple",
  };
  return colors[status || ""] || "default";
}

function feasibilityColor(status?: string) {
  const colors: Record<string, string> = {
    READY_FOR_HUMAN_REVIEW: "green",
    BLOCKED_PRODUCT_TRUTH: "gold",
    BLOCKED_RUN_ELIGIBILITY: "red",
    NO_ACTION: "default",
  };
  return colors[status || ""] || "default";
}

function experimentStatusLabel(status?: string) {
  const labels: Record<string, string> = {
    draft: "草案",
    baseline_locked: "基线已锁定",
    cooling: "发布冷却中",
    validating: "复测中",
    analyzing: "分析中",
    completed: "已完成",
  };
  return labels[status || ""] || status || "未知";
}

function issueStatusLabel(status?: string) {
  const labels: Record<string, string> = {
    candidate: "候选问题",
    confirmed: "已确认",
    in_action: "行动中",
    validating: "复测中",
    resolved: "已解决",
    rejected: "已拒绝",
  };
  return labels[status || ""] || status || "未知";
}

function strategyDecisionStatusLabel(status?: string) {
  const labels: Record<string, string> = {
    OPTIONS_AVAILABLE: "已有策略",
    NEEDS_MORE_EVIDENCE: "证据不足",
  };
  return labels[status || ""] || status || "未判断";
}

function strategyCapabilityLabel(capability?: string) {
  const labels: Record<string, string> = {
    CONTENT_DIRECTION_ONLY: "只给内容方向",
    EXPERIMENT_DRAFT_READY: "可生成实验草案",
  };
  return labels[capability || ""] || capability || "未判断";
}

function strategyContentTypeLabel(contentType?: string) {
  const labels: Record<string, string> = {
    VIDEO: "视频教程",
    Q_AND_A: "问答内容",
    TUTORIAL: "操作教程",
    RULE_EXPLANATION: "规则说明",
    TROUBLESHOOTING: "排障说明",
    COMPARISON: "对比评测",
    TOOL_PAGE: "工具说明页",
    NEWS: "新闻资讯",
    OTHER: "其他内容",
  };
  return labels[contentType || ""] || contentType || "-";
}

function readinessStatusLabel(status?: string) {
  const labels: Record<string, string> = {
    READY: "可进入实验",
    BLOCKED: "暂不可实验",
    NO_ACTION: "不建议干预",
  };
  return labels[status || ""] || status || "尚未生成";
}

function readinessStatusColor(status?: string) {
  const colors: Record<string, string> = {
    READY: "green",
    BLOCKED: "orange",
    NO_ACTION: "default",
  };
  return colors[status || ""] || "default";
}

function comparabilityStatusLabel(status?: string) {
  const labels: Record<string, string> = {
    COMPARABLE: "未发现显著已知混杂因素",
    POTENTIALLY_CONFOUNDED: "存在潜在混杂因素",
    MATERIALLY_CONFOUNDED: "存在实质混杂因素",
    INSUFFICIENT_CONTEXT: "复采上下文不足",
  };
  return labels[status || ""] || status || "复采上下文不足";
}

function comparabilityStatusColor(status?: string) {
  const colors: Record<string, string> = {
    COMPARABLE: "green",
    POTENTIALLY_CONFOUNDED: "orange",
    MATERIALLY_CONFOUNDED: "red",
    INSUFFICIENT_CONTEXT: "default",
  };
  return colors[status || ""] || "default";
}

function experimentPlanPayload(plan?: Record<string, any>) {
  if (!plan) return {};
  return plan.plan_payload && typeof plan.plan_payload === "object" ? plan.plan_payload : plan;
}

function listText(value: unknown, fallback = "-") {
  if (Array.isArray(value)) return value.length ? value.map((item) => {
    const row = item as any;
    return typeof item === "string" ? item : row?.feature || row?.description || JSON.stringify(item);
  }).join("；") : fallback;
  if (typeof value === "string") return value || fallback;
  if (value && typeof value === "object") return JSON.stringify(value);
  return fallback;
}

function strategyDisplayPayload(candidate: any) {
  const executable =
    candidate?.effective_payload && Object.keys(candidate.effective_payload).length > 0
      ? candidate.effective_payload
      : candidate?.human_edited_payload && Object.keys(candidate.human_edited_payload).length > 0
        ? candidate.human_edited_payload
        : candidate?.structured_payload || {};
  const original = candidate?.original_llm_payload || {};
  const decisionMarket = original.decision_market || executable.decision_market || {};
  const contentBrief = decisionMarket.content_brief || executable.content_brief || {};
  const interventionCandidate = decisionMarket.intervention_candidate || executable.intervention_candidate || {};
  const executionGate = original.execution_gate || executable.execution_gate || {};
  const actionText =
    typeof executable.recommended_action === "string"
      ? executable.recommended_action
      : executable.recommended_action?.content_direction ||
        executable.recommended_action?.asset_direction ||
        original.recommended_action ||
        decisionMarket.intervention_candidate?.recommended_direction ||
        decisionMarket.primary_gap?.action_hint ||
        "";
  return {
    payload: executable,
    decisionMarket,
    contentBrief,
    interventionCandidate,
    executionGate,
    evidenceSummary:
      executable.evidence_summary ||
      decisionMarket.primary_gap?.diagnosis_text ||
      interventionCandidate.observed_problem ||
      original.observed_problem ||
      "",
    cause:
      executable.hypothesized_cause ||
      original.hypothesized_cause ||
      decisionMarket.primary_gap?.action_hint ||
      interventionCandidate.recommended_direction ||
      "",
    actionText,
    interventionType:
      executable.intervention_type ||
      interventionCandidate.intervention_type ||
      original.intervention_type,
    targetPlatform:
      executable.target_platform ||
      interventionCandidate.target_platform ||
      original.target_platform,
    targetContentType:
      executable.target_content_type ||
      contentBrief.target_content_type,
    targetMetric:
      executable.target_metric ||
      original.target_metric ||
      decisionMarket.primary_gap?.metric?.metric,
    metricAvailability: executable.metric_availability || original.metric_availability || "",
    platformRecommendations:
      executable.platform_recommendations ||
      original.platform_recommendations ||
      [],
    mustAnswer: decisionMarket.must_answer || [],
    evidenceRequirements: decisionMarket.evidence_requirements || [],
    requiredSections: original.required_sections || contentBrief.sections || [],
    decisionSpace:
      executable.decision_space ||
      original.decision_space ||
      null,
  };
}

function interventionTypeLabel(type?: string) {
  const labels: Record<string, string> = {
    CONTENT_ASSET: "内容资产",
    CITATION_ASSET: "引用资产",
    PRODUCT_PROOF: "产品证明",
    BRAND_POSITIONING: "品牌定位",
    ANSWER_PATTERN: "回答结构",
    CONTENT_CREATE: "新建内容",
    CONTENT_UPDATE: "更新内容",
    PLATFORM_PUBLISH: "平台发布",
    TECHNICAL_INDEXABILITY: "技术可索引性",
    STRUCTURED_DATA: "结构化数据",
    ENTITY_CONSISTENCY: "实体一致性",
    INTERNAL_INFORMATION_ARCHITECTURE: "内部信息架构",
    PLATFORM_AUTHORITY_BUILD: "平台权威建设",
    RECRAWL_OR_REFRESH: "重抓/刷新",
    UNRESOLVED: "待人工确认",
    NO_ACTION: "暂不行动",
  };
  return labels[type || ""] || type || "待判断";
}

function platformLabel(platform?: string) {
  const labels: Record<string, string> = {
    UNRESOLVED: "待确认",
    BAIDU: "百度",
    WENXIN: "文心",
    ZHIHU: "知乎",
    WECHAT: "微信",
    OFFICIAL_SITE: "官网",
  };
  return labels[platform || ""] || platform || "待确认";
}

function claimTypeLabel(type?: string) {
  const labels: Record<string, string> = {
    STEP: "操作步骤",
    OPERATION_STEP: "操作步骤",
    CAPABILITY: "能力",
    FUNCTIONAL_CAPABILITY: "功能能力",
    EVIDENCE: "证据",
    RECOMMENDATION: "推荐",
    WARNING: "风险提醒",
    CONDITION: "适用条件",
    OTHER: "其他",
  };
  return labels[type || ""] || type || "-";
}

function speechActLabel(act?: string) {
  const labels: Record<string, string> = {
    ASSERTION: "陈述",
    INSTRUCTION: "指令",
    RECOMMENDATION: "推荐",
    WARNING: "警告",
  };
  return labels[act || ""] || act || "-";
}

function deriveDashboard(project: Project, prompts: Prompt[], runs: BrowserMonitorRun[], details: BrowserMonitorRunDetail[]): ValidationDashboard {
  const valid = runs.filter((run) => run.status === "success" || run.status === "partial_success");
  const brandRuns = valid.filter((run) => run.brand_mentioned).length;
  const recommended = valid.filter((run) => run.brand_recommendation_level > 0).length;
  const domains = new Map<string, Set<number>>();
  const urls = new Map<string, { title: string; domain: string; runs: Set<number> }>();
  details.forEach((detail) => detail.references.forEach((ref) => {
    if (ref.domain) {
      if (!domains.has(ref.domain)) domains.set(ref.domain, new Set());
      domains.get(ref.domain)!.add(detail.id);
    }
    if (ref.url) {
      if (!urls.has(ref.url)) urls.set(ref.url, { title: ref.display_title, domain: ref.domain, runs: new Set() });
      urls.get(ref.url)!.runs.add(detail.id);
    }
  }));
  const presence: ValidationPresence[] = [{
    name: project.brand_name,
    kind: "brand",
    appeared_runs: brandRuns,
    sample_runs: valid.length,
    recommended_runs: recommended,
    mentioned_runs: Math.max(0, brandRuns - recommended)
  }];
  project.competitors.forEach((competitor) => presence.push({
    name: competitor.name, kind: "competitor", appeared_runs: 0, sample_runs: valid.length
  }));
  return {
    project_id: project.id,
    sample_label: "验证样本",
    environment_label: "本机 · 文心网页端 · 单一采集环境",
    prompts: {
      total: prompts.length,
      executed: new Set(valid.map((run) => run.prompt_id)).size,
      clusters: new Set(prompts.map((prompt) => prompt.prompt_group).filter(Boolean)).size,
      valid_runs: valid.length,
      sample_runs: runs.length
    },
    presence,
    recommendation: {
      explicit: recommended,
      mentioned: Math.max(0, brandRuns - recommended),
      absent: Math.max(0, valid.length - brandRuns),
      sample_runs: valid.length
    },
    top_domains: [...domains].map(([value, ids]) => ({ value, run_count: ids.size })).sort((a, b) => b.run_count - a.run_count).slice(0, 8),
    top_urls: [...urls].map(([value, item]) => ({ value, title: item.title, domain: item.domain, run_count: item.runs.size })).sort((a, b) => b.run_count - a.run_count).slice(0, 8),
    quality: {
      total_runs: runs.length,
      successful_runs: valid.length,
      blocked_runs: runs.filter((run) => run.error_type?.includes("captcha") || run.error_type?.includes("blocked")).length,
      collector_failed_runs: runs.filter((run) => run.status === "failed" && !run.error_type?.includes("captcha") && !run.error_type?.includes("blocked")).length,
      complete_reference_runs: valid.filter((run) => run.reference_complete).length,
      eligible_reference_runs: valid.length,
      parsed_references: valid.reduce((sum, run) => sum + run.detected_reference_count, 0),
      resolved_urls: valid.reduce((sum, run) => sum + run.resolved_reference_count, 0)
    }
  };
}

function PresenceTable({ data }: { data: ValidationPresence[] }) {
  return <Table size="small" rowKey={(row) => `${row.kind}-${row.name}`} pagination={false} dataSource={data} columns={[
    { title: "对象", render: (_, row) => <Space><Tag color={row.kind === "brand" ? "blue" : "orange"}>{row.kind === "brand" ? "品牌" : "竞品"}</Tag><Text strong>{row.name}</Text></Space> },
    { title: "观察结果", width: 180, render: (_, row) => <><Text strong>{row.appeared_runs} / {row.sample_runs}</Text><Text type="secondary"> 次出现</Text></> },
    { title: "说明", render: (_, row) => row.sample_runs ? <Text type="secondary">观察提及率 {safeRate(row.appeared_runs, row.sample_runs)}%，样本 n={row.sample_runs}</Text> : <Text type="secondary">暂无有效样本</Text> }
  ]} />;
}

function SourceTable({ data, url }: { data: ValidationSource[]; url?: boolean }) {
  return <Table size="small" rowKey="value" pagination={false} dataSource={data} locale={{ emptyText: "尚无可聚合的引用数据" }} columns={[
    { title: url ? "引用页面" : "域名", render: (_, row) => url ? <Space direction="vertical" size={0}><Text>{row.title || row.value}</Text><Link href={row.value} target="_blank" ellipsis><ExternalLink size={12} /> {row.domain || row.value}</Link></Space> : <Text>{row.value}</Text> },
    { title: "出现次数", dataIndex: "run_count", width: 100, render: (value) => <Tag>{value} 次</Tag> }
  ]} />;
}

export default function App() {
  const [page, setPage] = useState<PageKey>("validation");
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number>();
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [clusters, setClusters] = useState<PromptCluster[]>([]);
  const [runs, setRuns] = useState<BrowserMonitorRun[]>([]);
  const [queue, setQueue] = useState<BrowserQueueSummary>(emptyQueue);
  const [selectedPrompts, setSelectedPrompts] = useState<Key[]>([]);
  const [dashboard, setDashboard] = useState<ValidationDashboard>();
  const [detail, setDetail] = useState<BrowserMonitorRunDetail>();
  const [artifact, setArtifact] = useState<RunArtifactContent>();
  const [rankingData, setRankingData] = useState<any>(null);
  const [rankingLoading, setRankingLoading] = useState(false);
  const [strategyData, setStrategyData] = useState<any>(null);
  const [strategyLoading, setStrategyLoading] = useState(false);
  const [strategyNotice, setStrategyNotice] = useState<{ type: "success" | "info" | "warning" | "error"; message: string; description?: string } | null>(null);
  const [latestGeneratedStrategyIds, setLatestGeneratedStrategyIds] = useState<number[]>([]);
  const [strategyCandidateFilter, setStrategyCandidateFilter] = useState("latest");
  const [optimizationIssues, setOptimizationIssues] = useState<any[]>([]);
  const [optimizationChain, setOptimizationChain] = useState<any>(null);
  const [selectedOptimizationIssueId, setSelectedOptimizationIssueId] = useState<number | null>(null);
  const [optimizationLoading, setOptimizationLoading] = useState(false);
  const [recommendationData, setRecommendationData] = useState<any>(null);
  const [recommendationClaims, setRecommendationClaims] = useState<any[]>([]);
  const [recommendationEntities, setRecommendationEntities] = useState<any[]>([]);
  const [recommendationReasons, setRecommendationReasons] = useState<any[]>([]);
  const [recommendationSemanticFacts, setRecommendationSemanticFacts] = useState<any[]>([]);
  const [recommendationPassageSupport, setRecommendationPassageSupport] = useState<any>(null);
  const [recommendationPromptId, setRecommendationPromptId] = useState<number | null>(null);
  const [recommendationSnapshots, setRecommendationSnapshots] = useState<any[]>([]);
  const [recommendationAutoLoadedProjectId, setRecommendationAutoLoadedProjectId] = useState<number | null>(null);
  const [recommendationLoading, setRecommendationLoading] = useState(false);
  const [evidencePackages, setEvidencePackages] = useState<any[]>([]);
  const [evidencePackageNotice, setEvidencePackageNotice] = useState<{ type: "success" | "info" | "warning" | "error"; message: string; description?: string } | null>(null);
  const [selectedPkgId, setSelectedPkgId] = useState<number | null>(null);
  const [selectedPromptId, setSelectedPromptId] = useState<number | null>(null);
  const [goldenData, setGoldenData] = useState<any>(null);
  const [workflowData, setWorkflowData] = useState<any>(null);
  const [workflowReviewOpen, setWorkflowReviewOpen] = useState(false);
  const [reviewQueue, setReviewQueue] = useState<any>(null);
  const [competitorCandidates, setCompetitorCandidates] = useState<any[]>([]);
  const [goldenLoading, setGoldenLoading] = useState(false);
  const [manualUrl, setManualUrl] = useState("");
  const [manualText, setManualText] = useState("");
  const [manualHtml, setManualHtml] = useState("");
  const [manualEmptyPage, setManualEmptyPage] = useState(false);

  async function prepareGoldenCaseWorkspace(promptId: number, options?: { skipAcquire?: boolean }) {
    const promptRuns = runs.filter((r: any) => r.prompt_id === promptId && (r.status === "success" || r.status === "partial_success"));
    if (promptRuns.length === 0) {
      message.warning("该问题没有可用采集记录");
      return null;
    }
    const runIds = promptRuns.map((r: any) => r.id).join(",");
    const runIdList = promptRuns.map((r: any) => r.id);
    const prepareResp = await fetch("/api/optimization/golden-case/prepare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_ids: runIdList, skip_acquire: Boolean(options?.skipAcquire) }),
    });
    if (!prepareResp.ok) {
      const detail = await prepareResp.text();
      throw new Error(detail || "自动准备证据标注数据失败");
    }
    const prepare = await prepareResp.json();
    const [s, nm, claims, audit, docs, als] = await Promise.all([
      (await fetch(`/api/optimization/golden-case/summary?run_ids=${runIds}`)).json(),
      (await fetch(`/api/optimization/golden-case/need-map-validated?run_ids=${runIds}`)).json(),
      (await fetch(`/api/optimization/golden-case/claims?run_ids=${runIds}`)).json(),
      (await fetch(`/api/optimization/golden-case/url-audit?run_ids=${runIds}`)).json(),
      (await fetch(`/api/optimization/golden-case/documents?run_ids=${runIds}`)).json(),
      (await fetch(`/api/optimization/golden-case/alignments?run_ids=${runIds}`)).json(),
    ]);
    const data = { summary: s, needMap: nm, claims, urlAudit: audit, docs, alignments: als, promptId, runIds, prepare };
    setGoldenData(data);
    return data;
  }
  const [loading, setLoading] = useState(false);
  const [retryingRuns, setRetryingRuns] = useState<Set<number>>(new Set());
  const [fallback, setFallback] = useState(false);
  const [promptForm] = Form.useForm();
  const [auditForm] = Form.useForm();
  const [projectForm] = Form.useForm();
  const [projectModalOpen, setProjectModalOpen] = useState(false);
  const [editingProjectId, setEditingProjectId] = useState<number | null>(null);
  const project = projects.find((item) => item.id === projectId);

  function openProjectModal(id?: number) {
    if (id) {
      const target = projects.find((item) => item.id === id);
      if (target) {
        projectForm.setFieldsValue({
          name: target.name,
          brand_name: target.brand_name,
          brand_aliases: target.brand_aliases.join(", "),
          website_url: target.website_url,
          industry: target.industry,
          competitors: target.competitors.map((item) => `${item.name}:${item.aliases?.join(";") || ""}:${item.website_url || ""}`).join("\n"),
        });
        setEditingProjectId(id);
      }
    } else {
      projectForm.resetFields();
      setEditingProjectId(null);
    }
    setProjectModalOpen(true);
  }

  async function deleteCurrentProject() {
    if (!editingProjectId) return;
    await api.deleteProject(editingProjectId);
    message.success("项目已删除");
    setProjectModalOpen(false);
    setEditingProjectId(null);
    if (projectId === editingProjectId) setProjectId(undefined);
    await loadProjects();
  }

  async function submitProject(values: Record<string, string>) {
    const aliases = values.brand_aliases ? values.brand_aliases.split(",").map((item: string) => item.trim()).filter(Boolean) : [];
    const compLines = values.competitors ? values.competitors.split("\n").filter((line: string) => line.trim()) : [];
    const competitors = compLines.map((line: string) => {
      const parts = line.split(":");
      const name = (parts[0] || "").trim();
      const aliasesStr = parts[1] || "";
      const url = parts.slice(2).join(":").trim(); // URL 含 "://"，重新拼接
      return { name, aliases: aliasesStr.split(";").map((item: string) => item.trim()).filter(Boolean), website_url: url };
    });
    const payload = { ...values, brand_aliases: aliases, competitors };
    if (editingProjectId) {
      const updated = await api.updateProject(editingProjectId, payload);
      message.success("项目已更新");
      if (projectId === editingProjectId) setProjectId(updated.id);
    } else {
      const created = await api.createProject(payload);
      message.success("项目已创建");
      setProjectId(created.id);
    }
    setProjectModalOpen(false);
    setEditingProjectId(null);
    await loadProjects();
  }

  async function loadProjects() {
    const next = await api.listProjects();
    setProjects(next);
    if (!projectId && next.length) setProjectId(next[0].id);
  }

  async function loadProject(id: number) {
    setLoading(true);
    try {
      const [nextPrompts, nextRuns, nextQueue, nextTopics, nextClusters] = await Promise.all([
        api.listPrompts(id), api.listBrowserAuditRuns(id), api.getBrowserQueueSummary(id),
        api.listTopics(id), api.listPromptClusters(id)
      ]);
      setPrompts(nextPrompts);
      setRuns(nextRuns);
      setQueue(nextQueue);
      setTopics(nextTopics);
      setClusters(nextClusters);
      // 加载分析工作流状态：后端直接返回机器分析进度最好的 Prompt
      try {
        const def = await (await fetch(`/api/optimization/workflow/${id}/default-prompt`)).json();
        if (def.prompt_id) {
          const wf = await (await fetch(`/api/optimization/workflow/${id}/${def.prompt_id}/status`)).json();
          setWorkflowData(wf);
        }
      } catch { /* 工作流数据加载失败不影响主页面 */ }
      try {
        setDashboard(await api.getValidationDashboard(id));
        setFallback(false);
      } catch {
        const selected = projects.find((item) => item.id === id);
        const successful = nextRuns.filter((run) => run.status === "success" || run.status === "partial_success");
        const nextDetails = (await Promise.all(successful.slice(0, 40).map((run) => api.getBrowserAuditRun(run.id).catch(() => null))))
          .filter((item): item is BrowserMonitorRunDetail => Boolean(item));
        if (selected) setDashboard(deriveDashboard(selected, nextPrompts, nextRuns, nextDetails));
        setFallback(true);
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadProjects().catch((error) => message.error(error.message)); }, []);
  useEffect(() => { if (projectId) loadProject(projectId).catch((error) => message.error(error.message)); }, [projectId, projects.length]);
  useEffect(() => {
    setRecommendationPromptId(null);
    setRecommendationData(null);
    setRecommendationClaims([]);
    setRecommendationSnapshots([]);
    setRecommendationAutoLoadedProjectId(null);
  }, [projectId]);
  useEffect(() => {
    if (page !== "recommendation" || !projectId || recommendationData || recommendationLoading || recommendationAutoLoadedProjectId === projectId) return;
    setRecommendationAutoLoadedProjectId(projectId);
    loadLatestRecommendation(projectId).catch((error) => message.error(error.message || "加载已有决策诊断失败"));
  }, [page, projectId, recommendationData, recommendationLoading, recommendationAutoLoadedProjectId]);
  useEffect(() => {
    if (page !== "optimization" || !projectId) return;
    loadOptimizationIssues().catch((error) => message.error(error.message || "加载实验闭环失败"));
    loadEvidencePackages(projectId).catch((error) => message.error(error.message || "加载证据失败"));
  }, [page, projectId]);

  async function openRun(id: number) {
    setArtifact(undefined);
    setDetail(await api.getBrowserAuditRun(id));
  }

  async function openArtifact(id: number) {
    try {
      setArtifact(await api.getRunArtifactContent(id));
    } catch (err: any) {
      message.error(err.message || "无法加载证据内容，可能文件已丢失");
    }
  }

  async function retryRun(runId: number) {
    if (!projectId) return;
    setRetryingRuns((prev) => new Set(prev).add(runId));
    try {
      await api.retryBrowserAuditRun(runId);
      message.success("已重新采集该 Run");
      await loadProject(projectId);
    } catch (err: any) {
      message.error(err.message || "重新采集失败");
    } finally {
      setRetryingRuns((prev) => { const next = new Set(prev); next.delete(runId); return next; });
    }
  }

  async function createPrompt(values: { topic?: string; prompt_group: string; prompt_text: string; importance?: number }) {
    if (!projectId) return;
    setLoading(true);
    try {
      const topicName = values.topic?.trim() || "未分类";
      let topic = topics.find((item) => item.name === topicName);
      if (!topic) {
        topic = await api.createTopic(projectId, { name: topicName, description: "", enabled: true });
      }
      let cluster = clusters.find((item) => item.topic_id === topic!.id && item.name === values.prompt_group.trim());
      if (!cluster) {
        cluster = await api.createPromptCluster(projectId, {
          topic_id: topic.id,
          name: values.prompt_group.trim(),
          sample_count: 3,
          enabled: true
        });
      }
      // 将换行输入拆分为多个独立的问题，每个问题单独提问
      const lines = values.prompt_text
        .split("\n")
        .map((line: string) => line.trim())
        .filter((line: string) => line.length > 0);
      for (const line of lines) {
        await api.createPrompt(projectId, {
          topic_id: topic.id,
          cluster_id: cluster.id,
          title: line.slice(0, 60),
          prompt_text: line,
          prompt_group: values.prompt_group,
          intent_type: "supplier_recommendation",
          importance: values.importance || 3,
          sample_count: 3,
          enabled: true
        });
      }
      promptForm.resetFields();
      message.success(lines.length > 1 ? `已创建 ${lines.length} 个问题` : "问题已创建");
      await loadProject(projectId);
    } finally {
      setLoading(false);
    }
  }

  async function createAudit(values: { batch_name: string; collection_mode: string; run_count: number; execute_now: boolean }) {
    if (!projectId || !selectedPrompts.length) return;
    setLoading(true);
    try {
      const batch = await api.createMonitoringBatch(projectId, {
        name: values.batch_name,
        platform: "wenxin",
        collection_mode: values.collection_mode,
        sample_count: values.run_count,
        status: "queued",
        notes: values.collection_mode === "single_independent"
          ? "验证采样；每个 Prompt 采样前强制开启新对话，避免复用上一个问题的上下文。"
          : "兼容模式；允许同一文心对话连续采集，仅用于人工明确需要连续上下文时。"
      });
      const result = await api.createBrowserAuditTask({
        project_id: projectId,
        batch_id: batch.id,
        platform: "wenxin",
        source_type: "browser_audit",
        adapter: "wenxin_web_audit",
        question_ids: selectedPrompts.map(Number),
        run_count: values.run_count,
        sample_count: values.run_count,
        execute_now: values.execute_now
      });
      if (values.execute_now) {
        message.success(`已创建采集批次并开始采集，共 ${result.queued_run_count} 条采样记录`);
      } else {
        message.success(`已创建采集批次，共排队 ${result.queued_run_count} 条采样记录`);
      }
      setSelectedPrompts([]);
      await loadProject(projectId);
    } finally {
      setLoading(false);
    }
  }

  async function runRecommendationAnalysis(promptId?: number | null) {
    const targetPromptId = promptId || recommendationPromptId;
    if (!projectId || !targetPromptId) {
      message.warning("请先选择一个问题");
      return;
    }
    setRecommendationLoading(true);
    message.loading({ content: "正在生成决策诊断...", key: "recommendation-analysis", duration: 0 });
    try {
      const promptRuns = runs
        .filter((run) => run.prompt_id === targetPromptId)
        .map((run) => run.id);
      if (promptRuns.length === 0) {
        message.warning({ content: "该问题还没有采集记录，暂时不能生成决策诊断", key: "recommendation-analysis" });
        return;
      }
      const data = await api.generateRecommendationAnalysis(projectId, { prompt_id: targetPromptId, run_ids: promptRuns });
      setRecommendationData(data);
      setRecommendationClaims(await api.listRecommendationClaims(data.id).catch(() => []));
      setRecommendationEntities(await api.listRecommendationEntities(data.id).catch(() => []));
      setRecommendationReasons(await api.listRecommendationReasons(data.id).catch(() => []));
      setRecommendationSemanticFacts(await api.listDecisionAnswerSemanticFacts(data.id).catch(() => []));
      setRecommendationPassageSupport(await api.getDecisionPassageSupport(data.id).catch(() => null));
      await loadRecommendationHistory(projectId, targetPromptId, data);
      message.success({ content: "决策诊断已生成", key: "recommendation-analysis" });
    } catch (error: any) {
      message.error({ content: error.message || "决策诊断失败", key: "recommendation-analysis" });
    } finally {
      setRecommendationLoading(false);
    }
  }

  async function loadRecommendationHistory(targetProjectId: number, promptId: number, fallbackData?: any) {
    try {
      const history = await api.listRecommendationSnapshots(targetProjectId, promptId);
      setRecommendationSnapshots(history);
    } catch {
      setRecommendationSnapshots(fallbackData ? [{
        id: fallbackData.id,
        prompt_id: fallbackData.prompt_id,
        run_count: fallbackData.run_count,
        decision_mode_label: fallbackData.decision_mode_label,
        generated_at: fallbackData.generated_at || fallbackData.created_at,
        created_at: fallbackData.created_at,
        status: fallbackData.status,
      }] : []);
    }
  }

  async function loadRecommendationSnapshot(promptId: number, snapshotId?: number) {
    if (!projectId) return;
    setRecommendationLoading(true);
    try {
      const data = await api.getRecommendationLandscape(projectId, promptId, snapshotId);
      setRecommendationPromptId(promptId);
      setRecommendationData(data);
      setRecommendationClaims(await api.listRecommendationClaims(data.id).catch(() => []));
      setRecommendationEntities(await api.listRecommendationEntities(data.id).catch(() => []));
      setRecommendationReasons(await api.listRecommendationReasons(data.id).catch(() => []));
      setRecommendationSemanticFacts(await api.listDecisionAnswerSemanticFacts(data.id).catch(() => []));
      setRecommendationPassageSupport(await api.getDecisionPassageSupport(data.id).catch(() => null));
      await loadRecommendationHistory(projectId, promptId, data);
    } finally {
      setRecommendationLoading(false);
    }
  }

  async function loadLatestRecommendation(targetProjectId: number) {
    setRecommendationLoading(true);
    try {
      const projectHistory = await api.listRecommendationSnapshots(targetProjectId, undefined, 50);
      if (!projectHistory.length) return;
      const latest = projectHistory[0];
      const [promptHistory, data] = await Promise.all([
        api.listRecommendationSnapshots(targetProjectId, latest.prompt_id),
        api.getRecommendationLandscape(targetProjectId, latest.prompt_id, latest.id),
      ]);
      setRecommendationPromptId(latest.prompt_id);
      setRecommendationSnapshots(promptHistory);
      setRecommendationData(data);
      setRecommendationClaims(await api.listRecommendationClaims(data.id).catch(() => []));
      setRecommendationEntities(await api.listRecommendationEntities(data.id).catch(() => []));
      setRecommendationReasons(await api.listRecommendationReasons(data.id).catch(() => []));
      setRecommendationSemanticFacts(await api.listDecisionAnswerSemanticFacts(data.id).catch(() => []));
      setRecommendationPassageSupport(await api.getDecisionPassageSupport(data.id).catch(() => null));
    } catch {
      setRecommendationSnapshots([]);
    } finally {
      setRecommendationLoading(false);
    }
  }

  async function reloadRecommendationSnapshot(snapshotId?: number) {
    if (!projectId || !recommendationData) return;
    await loadRecommendationSnapshot(recommendationData.prompt_id, snapshotId || recommendationData.id);
  }

  async function loadOptimizationIssues() {
    if (!projectId) return;
    setOptimizationLoading(true);
    try {
      const issues = await api.listOptimizationIssues(projectId);
      setOptimizationIssues(issues);
      if (selectedOptimizationIssueId && !issues.some((item: any) => item.id === selectedOptimizationIssueId)) {
        setSelectedOptimizationIssueId(null);
        setOptimizationChain(null);
      }
    } finally {
      setOptimizationLoading(false);
    }
  }

  async function loadOptimizationChain(issueId: number) {
    setOptimizationLoading(true);
    try {
      setSelectedOptimizationIssueId(issueId);
      setOptimizationChain(await api.getOptimizationEvidenceChain(issueId));
    } finally {
      setOptimizationLoading(false);
    }
  }

  async function refreshOptimizationChain() {
    if (selectedOptimizationIssueId) await loadOptimizationChain(selectedOptimizationIssueId);
    if (projectId) await loadOptimizationIssues();
  }

  async function loadEvidencePackages(targetProjectId = projectId!) {
    if (!targetProjectId) return [];
    const packages = await api.listEvidencePackages(targetProjectId);
    setEvidencePackages(packages);
    if (selectedPkgId && !packages.some((item: any) => item.id === selectedPkgId)) {
      setSelectedPkgId(null);
      setStrategyData(null);
    }
    return packages;
  }

  async function selectEvidencePackage(packageId: number, silent = false) {
    if (!projectId || !packageId) return;
    setSelectedPkgId(packageId);
    setStrategyNotice(null);
    setLatestGeneratedStrategyIds([]);
    setStrategyLoading(true);
    try {
      const existing = await api.listStrategyCandidates(projectId, packageId);
      if (existing.length > 0) {
        setStrategyData({
          decision_status: "OPTIONS_AVAILABLE",
          decision_capability: "CONTENT_DIRECTION_ONLY",
          strategy_options_count: existing.length,
          candidates: sortStrategyCandidates(existing)
        });
        setStrategyCandidateFilter("latest");
        if (!silent) message.success(`已加载 ${existing.length} 个已有策略`);
      } else {
        setStrategyData(null);
        setStrategyCandidateFilter("latest");
        if (!silent) message.info("证据已选中，当前还没有策略");
      }
    } catch {
      setStrategyData(null);
      setStrategyCandidateFilter("latest");
    } finally {
      setStrategyLoading(false);
    }
  }

  function strategyStatusRank(status?: string) {
    const ranks: Record<string, number> = {
      ACCEPTED: 0,
      ACCEPTED_WITH_EDITS: 0,
      PENDING_REVIEW: 1,
      DEFERRED: 2,
      VALIDATION_FAILED: 3,
      REJECTED: 4,
    };
    return ranks[status || ""] ?? 2;
  }

  function sortStrategyCandidates(candidates: any[]) {
    return [...(candidates || [])].sort((a, b) => {
      const statusDiff = strategyStatusRank(a.review_status) - strategyStatusRank(b.review_status);
      if (statusDiff) return statusDiff;
      return (new Date(b.generated_at || b.created_at).getTime() || 0) - (new Date(a.generated_at || a.created_at).getTime() || 0);
    });
  }

  function sortStrategyCandidatesByTime(candidates: any[]) {
    return [...(candidates || [])].sort((a, b) => {
      const timeDiff = (new Date(b.generated_at || b.created_at).getTime() || 0) - (new Date(a.generated_at || a.created_at).getTime() || 0);
      if (timeDiff) return timeDiff;
      return (b.id || 0) - (a.id || 0);
    });
  }

  function strategyVersionMap(candidates: any[]) {
    return new Map(
      [...(candidates || [])]
        .sort((a, b) => {
          const timeDiff = (new Date(a.generated_at || a.created_at).getTime() || 0) - (new Date(b.generated_at || b.created_at).getTime() || 0);
          if (timeDiff) return timeDiff;
          return (a.id || 0) - (b.id || 0);
        })
        .map((item: any, index: number) => [item.id, index + 1])
    );
  }

  function strategyVersionLabel(candidate: any, candidates: any[]) {
    return `V${strategyVersionMap(candidates).get(candidate?.id) || "?"}`;
  }

  function currentStrategySummary(candidates: any[]) {
    const sorted = sortStrategyCandidatesByTime(candidates);
    const current = sorted[0];
    if (!current) return "暂无策略版本";
    return `${strategyVersionLabel(current, candidates)} · 策略 #${current.id} · 生成时间 ${formatDateTime(current.generated_at || current.created_at)} · ${reviewStatusLabel(current.review_status)}`;
  }

  function filterStrategyCandidates(candidates: any[], filter: string) {
    const sorted = sortStrategyCandidatesByTime(candidates);
    if (filter === "all") return sorted;
    if (filter.startsWith("candidate:")) {
      const candidateId = Number(filter.replace("candidate:", ""));
      const matched = sorted.filter((item: any) => item.id === candidateId);
      return matched.length ? matched : sorted.slice(0, 1);
    }
    return sorted.slice(0, 1);
  }

  function strategyErrorSummary(candidate: any) {
    const errors = [
      ...(candidate?.evidence_validation_errors || []),
      ...(candidate?.hypothesis_validation_errors || []),
    ];
    return errors.length ? errors.join("；") : "未通过策略校验";
  }

  async function regenerateStrategies() {
    if (!projectId || !selectedPkgId) {
      message.warning("请先选择证据");
      return;
    }
    setStrategyLoading(true);
    setStrategyNotice(null);
    message.loading({ content: "正在生成策略...", key: "strategy-generate", duration: 0 });
    try {
      const generated = await api.generateStrategyCandidatesV2(projectId, { evidence_package_id: selectedPkgId, max_hypotheses: 3 });
      const generatedCandidates = generated?.candidates || [];
      const generatedIds = generatedCandidates.map((item: any) => item.id).filter(Boolean);
      setLatestGeneratedStrategyIds(generatedIds);
      const existing = await api.listStrategyCandidates(projectId, selectedPkgId);
      const sorted = sortStrategyCandidates(existing);
      const reviewable = sorted.filter((item: any) => item.review_status === "PENDING_REVIEW" || item.review_status === "ACCEPTED" || item.review_status === "ACCEPTED_WITH_EDITS");
      const generatedVersionMap = strategyVersionMap(existing);
      setStrategyData({
        ...(generated || {}),
        decision_status: sorted.length ? "OPTIONS_AVAILABLE" : generated?.decision_status,
        decision_capability: generated?.decision_capability || "CONTENT_DIRECTION_ONLY",
        strategy_options_count: sorted.length,
        candidates: sorted,
      });
      setStrategyCandidateFilter("latest");
      if (generatedCandidates.length && generatedCandidates.every((item: any) => item.review_status === "VALIDATION_FAILED")) {
        const first = generatedCandidates[0];
        setStrategyNotice({
          type: reviewable.length ? "warning" : "error",
          message: `本次生成的策略 #${first.id} 未通过校验`,
          description: `${strategyVersionLabel(first, existing)} · 生成时间 ${formatDateTime(first.generated_at || first.created_at)}；${strategyErrorSummary(first)}${reviewable.length ? `；如需继续使用上一条可审核策略，可在筛选中选择 ${strategyVersionLabel(reviewable[0], existing)} · 策略 #${reviewable[0].id}。` : ""}`
        });
        message.warning({ content: "本次生成未通过校验，已展示原因", key: "strategy-generate" });
      } else if (generatedCandidates.length) {
        const ids = generatedCandidates.map((item: any) => `${generatedVersionMap.get(item.id) ? `V${generatedVersionMap.get(item.id)} ` : ""}#${item.id}`).join("、");
        setStrategyNotice({
          type: "success",
          message: `策略已生成：${ids}`,
          description: reviewable.length ? `当前优先展示 ${strategyVersionLabel(reviewable[0], existing)} · 策略 #${reviewable[0].id} · 生成时间 ${formatDateTime(reviewable[0].generated_at || reviewable[0].created_at)}。` : undefined,
        });
        message.success({ content: `策略已生成：${ids}`, key: "strategy-generate" });
      } else {
        setStrategyNotice({
          type: "warning",
          message: "当前证据不足，未生成新策略",
          description: generated?.missing_evidence?.map((item: any) => item.reason || item.category).slice(0, 3).join("；"),
        });
        message.warning({ content: "当前证据不足，未生成新策略", key: "strategy-generate" });
      }
    } catch (error: any) {
      setStrategyNotice({ type: "error", message: "策略生成失败", description: error.message || String(error) });
      message.error({ content: error.message || "策略生成失败", key: "strategy-generate" });
    } finally {
      setStrategyLoading(false);
    }
  }

  function evidenceRunsForPrompt(promptId: number) {
    return runs.filter((run) => run.prompt_id === promptId && (run.status === "success" || run.status === "partial_success"));
  }

  function evidenceRunStats(promptId: number) {
    const allRuns = runs.filter((run) => run.prompt_id === promptId);
    const validRuns = evidenceRunsForPrompt(promptId);
    const citationRuns = validRuns.filter((run) => run.reference_complete || (run.detected_reference_count || 0) > 0 || (run.parsed_reference_count || 0) > 0);
    return {
      total: allRuns.length,
      valid: validRuns.length,
      citation: citationRuns.length,
      references: validRuns.reduce((sum, run) => sum + (run.parsed_reference_count || run.detected_reference_count || 0), 0),
      runIds: validRuns.map((run) => run.id),
    };
  }

  function latestEvidencePackageForPrompt(promptId: number) {
    return [...evidencePackages]
      .filter((item: any) => item.prompt_id === promptId)
      .sort((a: any, b: any) => (new Date(b.created_at).getTime() || 0) - (new Date(a.created_at).getTime() || 0))[0];
  }

  function evidencePackageSummary(pkg: any) {
    const payload = pkg?.package_payload || {};
    const metrics = payload.metric_snapshot || {};
    const status = payload.retrieval_metrics_status === "ok" ? "检索候选充足" : "检索候选不足，已降级为引用资料主分析";
    return `证据 #${pkg.id}，版本 ${pkg.version}，采样 ${pkg.source_run_ids?.length || metrics.valid_run_count || 0} 条；${status}。`;
  }

  async function createEvidencePackagesForSelectedPrompts() {
    if (!projectId) {
      message.error("请先选择项目");
      return;
    }
    const promptIds = selectedPrompts.map(Number);
    if (!promptIds.length) return;
    setLoading(true);
    setEvidencePackageNotice(null);
    const generated: any[] = [];
    const errors: string[] = [];
    try {
      for (const pid of promptIds) {
        const stats = evidenceRunStats(pid);
        if (!stats.valid) {
          errors.push(`#${pid}：没有成功或部分成功的采集记录，不能生成证据`);
          continue;
        }
        try {
          const pkg = await api.createEvidencePackage(projectId, {
            prompt_id: pid,
            run_ids: stats.runIds
          });
          generated.push(pkg);
        } catch (error: any) {
          errors.push(`#${pid}：${error.message || "生成失败"}`);
        }
      }
      const packages = await loadEvidencePackages(projectId);
      const firstPackage = generated[0] || (promptIds.length === 1 ? packages.find((item: any) => item.prompt_id === promptIds[0]) : null);
      if (firstPackage) await selectEvidencePackage(firstPackage.id, true);
      if (generated.length) {
        setEvidencePackageNotice({
          type: errors.length ? "warning" : "success",
          message: `已处理 ${generated.length}/${promptIds.length} 个问题的证据`,
          description: generated.map(evidencePackageSummary).join("；") + (errors.length ? `；失败：${errors.join("；")}` : "")
        });
        message.success(`已生成/加载 ${generated.length}/${promptIds.length} 份证据`);
      } else {
        setEvidencePackageNotice({
          type: "error",
          message: "证据没有生成成功",
          description: errors.join("；") || "没有可用于生成证据的有效采样"
        });
        message.error("证据没有生成成功");
      }
    } finally {
      setLoading(false);
    }
  }

  async function createDecisionExperimentDraft() {
    if (!recommendationData?.id) {
      message.warning("请先生成决策诊断");
      return;
    }
    setRecommendationLoading(true);
    try {
      const result = await api.createDecisionExperimentDraft(recommendationData.id, { owner: "待分配" });
      const candidateId = result.strategy_candidate?.id;
      message.success(candidateId
        ? `已生成待审核策略候选 #${candidateId}，请到「最终策略」完成人工审核`
        : result.status_label || "已生成待审核策略候选");
    } catch (error: any) {
      message.error(error.message || "生成实验草案失败");
    } finally {
      setRecommendationLoading(false);
    }
  }

  const q = dashboard?.quality;
  const referenceResolution = q ? safeRate(q.resolved_urls, q.parsed_references) : 0;
  const referenceComplete = q ? safeRate(q.complete_reference_runs, q.eligible_reference_runs) : 0;
  const recommendationRows = useMemo(() => dashboard ? [
    { key: "explicit", label: "明确推荐", count: dashboard.recommendation.explicit, color: "#1677ff" },
    { key: "mentioned", label: "一般提及", count: dashboard.recommendation.mentioned, color: "#faad14" },
    { key: "absent", label: "未出现", count: dashboard.recommendation.absent, color: "#bfbfbf" }
  ] : [], [dashboard]);
  const decisionMarket = recommendationData?.decision_market;
  const runEligibility = recommendationData?.run_eligibility || decisionMarket?.run_eligibility || {};
  const decisionSpace = decisionMarket?.decision_space || {};
  const targetBrandPosition = decisionMarket?.target_brand_position || {};
  const interventionFeasibility = decisionMarket?.intervention_feasibility || {};
  const promptInterventionCandidates = decisionMarket?.intervention_candidates || recommendationData?.intervention_candidates || [];
  const latestRecommendationSnapshotId = recommendationSnapshots[0]?.id;
  const isLatestRecommendationSnapshot = Boolean(recommendationData?.id && latestRecommendationSnapshotId === recommendationData.id);
  const recommendationMarketRows = useMemo(() => {
    return decisionMarket?.recommendation_market?.rows || [];
  }, [decisionMarket]);
  const driverRows = useMemo(() => {
    return decisionMarket?.recommendation_drivers?.rows || [];
  }, [decisionMarket]);
  const sourcePatternRows = useMemo(() => {
    return decisionMarket?.source_content_pattern?.rows || [];
  }, [decisionMarket]);
  const decisionAuditRows = useMemo(() => {
    if (!recommendationData) return [];
    const adoptions = decisionMarket?.citation_context?.adoptions || [];
    const sampleByRun = new Map<number, any>((recommendationData.answer_samples || []).map((sample: any) => [sample.run_id, sample]));
    const primaryGap = decisionMarket?.primary_gap || (decisionMarket?.gap_diagnosis || [])[0] || {};
    const actionPackage = decisionMarket?.action_package || {};
    return (recommendationClaims || [])
      .filter((claim: any) => claim.entity_name)
      .map((claim: any) => {
        const relatedAdoptions = adoptions.filter((item: any) =>
          item.recommendation_claim_id === claim.id ||
          (item.run_id === claim.run_id && (!item.answer_span || claim.answer_span?.includes(item.answer_span) || item.answer_span?.includes(claim.entity_name)))
        );
        return {
          ...claim,
          answer_excerpt: sampleByRun.get(claim.run_id)?.answer_excerpt || "",
          citation_contexts: relatedAdoptions,
          primary_gap: primaryGap,
          recommended_action: actionPackage.content_brief?.page_goal || actionPackage.selection_reason_gap || actionPackage.asset_decision_label || "-",
          validation_metric: actionPackage.experiment_proposal?.primary_metric || "-",
        };
      });
  }, [recommendationData, decisionMarket, recommendationClaims]);
  const reasonMarketRows = useMemo(() => {
    const groups = new Map<string, any>();
    (recommendationReasons || []).forEach((reason: any) => {
      const key = `${reason.entity_name || "未知对象"}-${reason.reason_type || "OTHER"}-${reason.reason_text || ""}`;
      if (!groups.has(key)) {
        groups.set(key, {
          key,
          entity_name: reason.entity_name || "未知对象",
          reason_type: reason.reason_type,
          reason_type_label: reason.reason_type_label || reason.reason_type || "其他",
          reason_text: reason.reason_text || reason.reason_span || "未抽取到理由文本",
          run_ids: new Set<number>(),
          items: [],
        });
      }
      const row = groups.get(key);
      row.run_ids.add(reason.run_id);
      row.items.push(reason);
    });
    return [...groups.values()].map((row) => ({
      ...row,
      run_count: row.run_ids.size,
      run_ids: [...row.run_ids],
    })).sort((a, b) => b.run_count - a.run_count);
  }, [recommendationReasons]);
  const sortedStrategyCandidates = sortStrategyCandidatesByTime(strategyData?.candidates || []);
  const visibleStrategyCandidates = filterStrategyCandidates(sortedStrategyCandidates, strategyCandidateFilter);
  const strategyFilterOptions = [
    { label: "最新策略", value: "latest" },
    { label: "全部策略", value: "all" },
    ...sortedStrategyCandidates.map((candidate: any) => ({
      label: `${strategyVersionLabel(candidate, sortedStrategyCandidates)} · 策略 #${candidate.id} · ${reviewStatusLabel(candidate.review_status)}`,
      value: `candidate:${candidate.id}`,
    })),
  ];

  return <Layout className="app-shell">
    <Sider width={228} className="side-nav">
      <div className="brand-block"><Title level={4}>生成式搜索决策平台</Title><Text type="secondary">监测 · 诊断 · 策略 · 复测</Text></div>
        <Menu mode="inline" selectedKeys={[page]} onClick={({ key }) => setPage(key as PageKey)} items={[
        { type: "group", label: "业务闭环", children: [
          { key: "validation", icon: <BarChart3 size={18} />, label: "监测总览" },
          { key: "recommendation", icon: <ShieldCheck size={18} />, label: "决策诊断" },
          { key: "optimization", icon: <ShieldCheck size={18} />, label: "最终策略" },
        ] },
        { type: "group", label: "证据工作台", children: [
          { key: "ranking", icon: <BarChart3 size={18} />, label: "引用资料" },
          { key: "golden", icon: <ShieldCheck size={18} />, label: "证据标注" },
          { key: "runs", icon: <Monitor size={18} />, label: "采集记录" },
        ] },
        { type: "group", label: "系统配置", children: [
          { key: "config", icon: <ListChecks size={18} />, label: "问题配置" },
        ] },
      ]} />
    </Sider>
    <Layout>
      <Header className="topbar">
        <div><Title level={3}>{PAGE_META[page].title}</Title><Text type="secondary">{PAGE_META[page].subtitle}</Text></div>
        <Space>
          <Select className="project-select" value={projectId} placeholder="选择项目" onChange={setProjectId} options={projects.map((item) => ({ label: item.name, value: item.id }))} />
          <Button icon={<Plus size={16} />} onClick={() => openProjectModal()}>新建项目</Button>
          <Button icon={<Settings size={16} />} onClick={() => projectId && openProjectModal(projectId)} disabled={!projectId}>编辑项目</Button>
          <Button icon={<RefreshCw size={16} />} loading={loading} onClick={() => projectId && loadProject(projectId)}>刷新</Button>
        </Space>
      </Header>
      <Content className="workspace">
        {!project || !dashboard ? <Card loading={loading}><Empty description="请选择包含采集数据的项目" /></Card> : page === "validation" ? <Space direction="vertical" size={16} className="page-stack">
          <Card size="small" className="audit-hero">
            <Row align="middle" justify="space-between" gutter={[16, 16]}>
              <Col><Space direction="vertical" size={4}><Space><Title level={4}>{project.name}</Title><Tag color="blue">{dashboard.sample_label || "验证样本"}</Tag></Space><Text type="secondary">{dashboard.environment_label || "单一采集环境，仅表示当前验证样本"}</Text></Space></Col>
              <Col><Alert type="info" showIcon message="以下为验证样本观察值，不代表总体品牌曝光概率。" /></Col>
            </Row>
          </Card>
          {projectId && workflowData && <Card size="small" title={<Space><ShieldCheck size={18} />Prompt #{workflowData.prompt_id} 分析工作流</Space>} extra={
            workflowData.all_reviews_done
              ? <Button type="primary" size="small" loading={loading} onClick={async()=>{
                  setLoading(true);
                  try{
                    const result = await (await fetch(`/api/optimization/workflow/${projectId}/${workflowData.prompt_id}/continue`,{method:"POST"})).json();
                    setWorkflowData({...workflowData, continueResult: result});
                    message.success("Gap 与 Action 已生成");
                    // 刷新工作流状态
                    const wf = await (await fetch(`/api/optimization/workflow/${projectId}/${workflowData.prompt_id}/status`)).json();
                    setWorkflowData({...wf, continueResult: result});
                  }catch(e:any){message.error(e.message||"继续分析失败，请确认审核已全部完成")}
                  finally{setLoading(false)}
                }}>继续分析</Button>
              : <Button type="primary" size="small" danger onClick={()=>setWorkflowReviewOpen(true)}>开始审核（{workflowData.pending_review_steps} 步待处理）</Button>
          }>
            <Row gutter={[8,8]}>
              {workflowData.steps.map((s:any)=><Col key={s.key} xs={12} md={8} lg={4}>
                <Space size={4}>
                  <Tag color={s.done ? "green" : s.key==="gap"||s.key==="action"||s.key==="experiment" ? "default" : "orange"}>{s.done ? "✓" : s.key==="gap"||s.key==="action"||s.key==="experiment" ? "·" : "!"}</Tag>
                  <Text type={s.done ? undefined : "secondary"} style={{fontSize:12}}>{s.label}</Text>
                </Space>
                <div style={{fontSize:11, color:"#999", marginLeft:24}}>{s.detail}</div>
              </Col>)}
            </Row>
            {workflowData.continueResult && <Space direction="vertical" size={4} style={{width:"100%", marginTop:8}}>
              <Alert type={workflowData.continueResult.gap?.gap_type==="UNRESOLVED" ? "warning" : "success"} showIcon
                message={<Space><Text strong>Gap：{workflowData.continueResult.gap?.gap_type}</Text><Tag>{workflowData.continueResult.gap?.confidence}</Tag>
                  {!workflowData.steps.find((s:any)=>s.key==="gap")?.done && <Button size="small" type="primary" onClick={async()=>{
                    await fetch(`/api/optimization/workflow/${projectId}/${workflowData.prompt_id}/confirm-decision`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({step_key:"gap",decision_status:"CONFIRMED"})});
                    message.success("Gap 已确认");
                    const wf = await (await fetch(`/api/optimization/workflow/${projectId}/${workflowData.prompt_id}/status`)).json();
                    setWorkflowData({...wf, continueResult: workflowData.continueResult});
                  }}>确认此 Gap</Button>}
                </Space>}
                description={workflowData.continueResult.gap?.basis} />
              <Alert type="info" showIcon
                message={<Space><Text strong>Action：{workflowData.continueResult.action?.intervention_goal}</Text><Tag>{workflowData.continueResult.action?.asset_ownership}</Tag><Tag>{workflowData.continueResult.action?.target_platform}</Tag>
                  {!workflowData.steps.find((s:any)=>s.key==="action")?.done && <Button size="small" type="primary" onClick={async()=>{
                    await fetch(`/api/optimization/workflow/${projectId}/${workflowData.prompt_id}/confirm-decision`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({step_key:"action",decision_status:"CONFIRMED"})});
                    message.success("Action 已确认");
                    const wf = await (await fetch(`/api/optimization/workflow/${projectId}/${workflowData.prompt_id}/status`)).json();
                    setWorkflowData({...wf, continueResult: workflowData.continueResult});
                  }}>确认此 Action</Button>}
                </Space>}
                description={workflowData.continueResult.action?.target_claim} />
            </Space>}
          </Card>}
          {fallback && <Alert type="warning" showIcon message="聚合接口尚未返回数据，当前看板由已有采集记录实时兼容汇总。" />}
          <Row gutter={[16, 16]}>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="配置问题数" value={dashboard.prompts.total} /></Card></Col>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="已采集" value={dashboard.prompts.executed} /></Card></Col>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="问题组" value={dashboard.prompts.clusters} /></Card></Col>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="成功采集" value={dashboard.prompts.valid_runs} /></Card></Col>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="总采集次数" value={dashboard.prompts.sample_runs} suffix="次" /></Card></Col>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="引用URL解析率" value={referenceResolution} suffix="%" precision={1} /></Card></Col>
          </Row>
          <Row gutter={[16, 16]}>
            <Col xs={24} xl={14}><Card title="品牌与竞品在智能回答中的出现情况" extra={<Tag>样本量 n={dashboard.prompts.valid_runs}</Tag>}><PresenceTable data={dashboard.presence} /></Card></Col>
            <Col xs={24} xl={10}><Card title="智能回答推荐情况" extra={<Text type="secondary">仅统计明确推荐</Text>}>
              <Space direction="vertical" className="page-stack">
                {recommendationRows.map((row) => <div key={row.key}><Space style={{ justifyContent: "space-between", width: "100%" }}><Text>{row.label}</Text><Text strong>{row.count} / {dashboard.recommendation.sample_runs}</Text></Space><Progress percent={safeRate(row.count, dashboard.recommendation.sample_runs)} showInfo={false} strokeColor={row.color} /></div>)}
              </Space>
            </Card></Col>
          </Row>
          <Row gutter={[16, 16]}>
            <Col xs={24} xl={10}><Card title="高频域名"><SourceTable data={dashboard.top_domains} /></Card></Col>
            <Col xs={24} xl={14}><Card title="高频页面"><SourceTable data={dashboard.top_urls} url /></Card></Col>
          </Row>
          <Card title={<Space><ShieldCheck size={18} />数据质量</Space>} extra={<Text type="secondary">公开采集可信度</Text>}>
            <Row gutter={[16, 16]}>
              <Col xs={12} md={4}><Statistic title="成功采集" value={q!.successful_runs} suffix={`/ ${q!.total_runs}`} /></Col>
              <Col xs={12} md={4}><Statistic title="被拦截" value={q!.blocked_runs} /></Col>
              <Col xs={12} md={4}><Statistic title="采集失败" value={q!.collector_failed_runs} /></Col>
              <Col xs={12} md={4}><Statistic title="引用完整度" value={referenceComplete} suffix="%" precision={1} /></Col>
              <Col xs={12} md={4}><Statistic title="已解析标题" value={q!.parsed_references} /></Col>
              <Col xs={12} md={4}><Statistic title="已解析链接" value={q!.resolved_urls} /></Col>
            </Row>
          </Card>
        </Space> : page === "recommendation" ? <Space direction="vertical" size={16} className="page-stack">
          <Card title="决策诊断工作台" extra={<Tag color="blue">诊断，不是最终策略</Tag>}>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message="这里负责解释单个问题的答案结构、引用资料、品牌状态和差距来源；最终策略统一在「最终策略」页面确认。"
              description="诊断页可以生成实验草案并送入优化闭环，但不直接发布策略、不宣称效果。"
            />
            <Space wrap style={{ marginBottom: 12 }}>
              <Select
                placeholder="选择问题"
                style={{ width: 420 }}
                value={recommendationPromptId || undefined}
                onChange={async (value) => {
                  setRecommendationData(null);
                  setRecommendationClaims([]);
                  setRecommendationEntities([]);
                  setRecommendationReasons([]);
                  setRecommendationSemanticFacts([]);
                  setRecommendationPassageSupport(null);
                  setRecommendationSnapshots([]);
                  setRecommendationPromptId(value);
                  if (!projectId) return;
                  try {
                    await loadRecommendationSnapshot(value);
                    message.success("已加载最新决策诊断");
                  } catch (error: any) {
                    message.warning(error?.message || "该问题还没有已生成的决策诊断，请点击「生成诊断」创建第一版");
                  }
                }}
                options={prompts.map((prompt) => ({ value: prompt.id, label: `#${prompt.id} ${prompt.prompt_text}` }))}
              />
              <Button type="primary" loading={recommendationLoading} onClick={() => runRecommendationAnalysis()}>
                生成诊断
              </Button>
              {recommendationData && <Button loading={recommendationLoading} onClick={() => runRecommendationAnalysis(recommendationData.prompt_id)}>
                重新生成
              </Button>}
              {recommendationSnapshots.length > 0 && <Select
                placeholder="查看历史版本"
                style={{ width: 360 }}
                value={recommendationData?.id}
                onChange={(snapshotId) => reloadRecommendationSnapshot(snapshotId)}
                options={recommendationSnapshots.map((snapshot, index) => ({
                  value: snapshot.id,
                  label: `版本 #${snapshot.id} · ${formatDateTime(snapshot.generated_at || snapshot.created_at)} · ${snapshot.run_count} 次采样${index === 0 ? " · 最新" : ""}`,
                }))}
              />}
            </Space>
            {!recommendationData ? <Empty description="选择一个已有采集记录的问题，然后生成决策诊断" /> : <Space direction="vertical" size={12} style={{ width: "100%" }}>
              <Alert
                type={isLatestRecommendationSnapshot ? "success" : "warning"}
                showIcon
                message={`当前查看：诊断版本 #${recommendationData.id}，生成时间 ${formatDateTime(recommendationData.generated_at || recommendationData.created_at)}`}
                description={isLatestRecommendationSnapshot
                  ? "这是该问题当前最新生成结果。"
                  : `这不是最新结果；最新版本是 #${latestRecommendationSnapshotId}。你可以在「查看历史版本」中切回最新版本。`}
              />
              <Row gutter={[12, 12]}>
                <Col xs={12} md={4}><Card size="small"><Statistic title="分析采样" value={recommendationData.run_count} suffix="次" /></Card></Col>
                <Col xs={12} md={5}><Card size="small"><Statistic title="决策模式" value={recommendationData.decision_mode_label} /></Card></Col>
                <Col xs={12} md={5}><Card size="small"><Statistic title="推荐指标" value={recommendationData.metric_eligibility?.recommendation_metrics_label || "-"} /></Card></Col>
                <Col xs={12} md={5}><Card size="small"><Statistic title="任务完成指标" value={recommendationData.metric_eligibility?.task_completion_metrics_label || "-"} /></Card></Col>
                <Col xs={12} md={5}><Card size="small"><Statistic title="抽取版本" value={recommendationData.recommendation_extractor_version} /></Card></Col>
              </Row>
              {decisionMarket && <Row gutter={[12, 12]}>
                <Col xs={24} xl={12}>
                  <Card size="small" title="A. 单 Prompt 样本资格门" extra={<Tag color="blue">{runEligibility.analysis_unit || "SINGLE_PROMPT"}</Tag>}>
                    <Alert
                      type={runEligibility.ineligible_runs > 0 ? "warning" : "success"}
                      showIcon
                      style={{ marginBottom: 8 }}
                      message={`可分析样本：${runEligibility.analysis_usable_runs ?? recommendationData.run_count} / ${runEligibility.total_runs ?? recommendationData.run_count}`}
                      description={runEligibility.boundary_note || "正式 GEO 分析以单 Prompt 的独立新会话采样为单位；采集成功不自动等于分析合格。"}
                    />
                    <Row gutter={[8, 8]} style={{ marginBottom: 8 }}>
                      <Col xs={12} md={6}><Statistic title="合格" value={runEligibility.eligible_runs ?? recommendationData.run_count} /></Col>
                      <Col xs={12} md={6}><Statistic title="部分" value={runEligibility.partial_runs ?? 0} /></Col>
                      <Col xs={12} md={6}><Statistic title="不合格" value={runEligibility.ineligible_runs ?? 0} /></Col>
                      <Col xs={12} md={6}><Statistic title="待确认" value={runEligibility.unknown_runs ?? 0} /></Col>
                    </Row>
                    <Table
                      size="small"
                      rowKey="run_id"
                      pagination={{ pageSize: 5 }}
                      dataSource={runEligibility.rows || []}
                      locale={{ emptyText: "当前快照没有样本资格明细" }}
                      columns={[
                        { title: "采集", dataIndex: "run_id", width: 70, render: (value) => <Tag>#{value}</Tag> },
                        { title: "状态", width: 110, render: (_, row: any) => <Tag color={runEligibilityColor(row.status)}>{row.status_label || row.status}</Tag> },
                        { title: "采集模式", dataIndex: "collection_mode", width: 140, render: (value) => <Tag>{value || "未知"}</Tag> },
                        { title: "Sample", dataIndex: "sample_index", width: 80 },
                        { title: "原因", render: (_, row: any) => <Space wrap>{(row.reasons || []).map((item: string) => <Tag key={item}>{item}</Tag>)}</Space> },
                      ]}
                    />
                  </Card>
                </Col>
                <Col xs={24} xl={12}>
                  <Card size="small" title="B. 单 Prompt 决策空间与目标品牌位置">
                    <Alert
                      type={decisionSpace.status === "NO_BRAND_DECISION_SPACE" ? "warning" : "info"}
                      showIcon
                      style={{ marginBottom: 8 }}
                      message={<Space wrap><Tag color={decisionSpaceColor(decisionSpace.status)}>{decisionSpace.status_label || "决策空间待判断"}</Tag><Text>{decisionSpace.boundary_note || "提及、候选、明确推荐和对比是独立事实。"}</Text></Space>}
                    />
                    <Descriptions size="small" column={1}>
                      <Descriptions.Item label="选择空间">{formatMetric(decisionSpace.metrics?.choice_slot_rate)}</Descriptions.Item>
                      <Descriptions.Item label="品牌候选">{formatMetric(decisionSpace.metrics?.brand_candidate_rate)}</Descriptions.Item>
                      <Descriptions.Item label="明确推荐">{formatMetric(decisionSpace.metrics?.explicit_recommendation_rate)}</Descriptions.Item>
                      <Descriptions.Item label="目标品牌阶段"><Tag color={targetBrandPosition.status === "ABSENT" ? "red" : "blue"}>{targetBrandPosition.status_label || brandStageLabel(targetBrandPosition.status)}</Tag></Descriptions.Item>
                      <Descriptions.Item label="Primary Gap">{targetBrandPosition.primary_gap?.gap_type_label || decisionMarket.primary_gap?.gap_type_label || "-"}</Descriptions.Item>
                      <Descriptions.Item label="已具备信号">{(targetBrandPosition.strengths || []).length > 0 ? <Space wrap>{targetBrandPosition.strengths.map((item: string) => <Tag key={item} color="green">{item}</Tag>)}</Space> : <Text type="secondary">暂无稳定目标品牌信号</Text>}</Descriptions.Item>
                    </Descriptions>
                  </Card>
                </Col>
              </Row>}
              {decisionMarket && <Card size="small" title="决策市场总览" extra={<Tag>结构化诊断规则</Tag>}>
                <Alert type="info" showIcon style={{ marginBottom: 12 }} message={decisionMarket.primary_metric_note} description={decisionMarket.scope_note} />
                <Row gutter={[12, 12]}>
                  <Col xs={24} md={8}>
                    <Card size="small" title="问题意图">
                      <Space wrap>{(decisionMarket.prompt_intents || []).map((item: any) => <Tag color="blue" key={item.intent}>{item.intent_label}</Tag>)}</Space>
                    </Card>
                  </Col>
                  <Col xs={24} md={8}>
                    <Card size="small" title="品牌选择空间">
                      <Descriptions size="small" column={1}>
                        <Descriptions.Item label="机会等级">{decisionMarket.brand_opportunity_gate?.opportunity_level_label || "-"}</Descriptions.Item>
                        <Descriptions.Item label="选择空间">{decisionMarket.choice_slot?.choice_slot_status_label || "-"}</Descriptions.Item>
                        <Descriptions.Item label="覆盖采样">{formatMetric(decisionMarket.choice_slot?.choice_slot_metric)}</Descriptions.Item>
                        <Descriptions.Item label="品牌提及">{formatMetric(decisionMarket.brand_opportunity_gate?.metrics?.brand_mention_rate)}</Descriptions.Item>
                        <Descriptions.Item label="明确推荐">{formatMetric(decisionMarket.brand_opportunity_gate?.metrics?.explicit_recommendation_rate)}</Descriptions.Item>
                      </Descriptions>
                    </Card>
                  </Col>
                  <Col xs={24} md={8}>
                    <Card size="small" title="行动判断">
                      <Descriptions size="small" column={1}>
                        <Descriptions.Item label="机会类型">{decisionMarket.action_package?.opportunity_type_label || "-"}</Descriptions.Item>
                        <Descriptions.Item label="资产决策">{decisionMarket.action_package?.asset_decision_label || "-"}</Descriptions.Item>
                      </Descriptions>
                    </Card>
                  </Col>
                </Row>
              </Card>}
              {decisionMarket && <Card size="small" title="C. 单 Prompt Recommendation Market">
                <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 8 }}
                  message={decisionMarket.recommendation_market?.metric_format_note || "提及、候选、明确推荐、第一推荐分别计算，不能互相替代。"}
                  description={`当前分母为合格独立样本：${decisionMarket.recommendation_market?.eligible_runs ?? recommendationData.run_count} 次。`}
                />
                <Table
                  size="small"
                  rowKey="entity_name"
                  pagination={{ pageSize: 8 }}
                  dataSource={recommendationMarketRows}
                  locale={{ emptyText: "当前没有品牌/实体进入推荐市场" }}
                  columns={[
                    { title: "实体", dataIndex: "entity_name", width: 150, render: (value, row: any) => <Space><Text strong>{value}</Text>{row.is_target_brand && <Tag color="blue">目标品牌</Tag>}</Space> },
                    { title: "提及", width: 105, render: (_, row: any) => formatMetric(row.mention) },
                    { title: "候选", width: 105, render: (_, row: any) => formatMetric(row.candidate) },
                    { title: "明确推荐", width: 120, render: (_, row: any) => formatMetric(row.positive_recommendation) },
                    { title: "第一推荐", width: 120, render: (_, row: any) => formatMetric(row.top_recommendation) },
                    { title: "负面", width: 105, render: (_, row: any) => formatMetric(row.negative_recommendation) },
                    { title: "推荐事件", width: 90, render: (_, row: any) => <Tag>{row.recommendation_event_count || 0}</Tag> },
                    { title: "典型片段", dataIndex: "representative_claims", render: (value: string[]) => <Text type="secondary">{(value || [])[0] || "-"}</Text> },
                  ]}
                />
              </Card>}
              {decisionMarket && <Card size="small" title="答案语义事实">
                <Alert type="info" showIcon style={{ marginBottom: 8 }} message={decisionMarket.answer_semantic_facts?.boundary_note || "品牌提及、选择空间、明确推荐相互独立判断。"} />
                <Row gutter={[12, 12]}>
                  <Col xs={12} md={6}><Statistic title="有选择空间" value={formatMetric(decisionMarket.answer_semantic_facts?.metrics?.has_choice_slot)} /></Col>
                  <Col xs={12} md={6}><Statistic title="有品牌出现" value={formatMetric(decisionMarket.answer_semantic_facts?.metrics?.has_brand_mention)} /></Col>
                  <Col xs={12} md={6}><Statistic title="明确推荐" value={formatMetric(decisionMarket.answer_semantic_facts?.metrics?.has_explicit_recommendation)} /></Col>
                  <Col xs={12} md={6}><Statistic title="存在对比" value={formatMetric(decisionMarket.answer_semantic_facts?.metrics?.has_comparison)} /></Col>
                </Row>
                <Divider />
                <Table
                  size="small"
                  rowKey="id"
                  pagination={{ pageSize: 8 }}
                  dataSource={recommendationSemanticFacts}
                  locale={{ emptyText: "当前没有可审核的答案语义事实" }}
                  columns={[
                    { title: "采集", dataIndex: "run_id", width: 70, render: (value) => <Tag>#{value}</Tag> },
                    { title: "事实", dataIndex: "fact_type_label", width: 150, render: (value) => <Tag color="blue">{value}</Tag> },
                    { title: "判断", width: 90, render: (_, row: any) => row.fact_value ? <Tag color="green">是</Tag> : <Tag>否</Tag> },
                    { title: "证据片段", dataIndex: "evidence_span", ellipsis: true },
                    { title: "置信度", width: 80, render: (_, row: any) => <Tag>{Math.round((row.confidence || 0) * 100)}%</Tag> },
                    { title: "状态", width: 95, render: (_, row: any) => <Tag>{reviewStatusLabel(row.review_status)}</Tag> },
                    { title: "审核", width: 150, render: (_, row: any) => <Space size={4}>
                      <Button size="small" onClick={async () => {
                        const next = await api.reviewDecisionAnswerSemanticFact(row.id, { review_status: "CONFIRMED", fact_value: row.fact_value, reviewer: "human" });
                        setRecommendationSemanticFacts(recommendationSemanticFacts.map((item) => item.id === row.id ? next : item));
                        message.success("语义事实已确认");
                      }}>确认</Button>
                      <Button size="small" danger onClick={async () => {
                        const next = await api.reviewDecisionAnswerSemanticFact(row.id, { review_status: "REJECTED", fact_value: false, reviewer: "human" });
                        setRecommendationSemanticFacts(recommendationSemanticFacts.map((item) => item.id === row.id ? next : item));
                        message.success("语义事实已拒绝");
                      }}>拒绝</Button>
                    </Space> },
                  ]}
                />
              </Card>}
              {decisionMarket && <Card size="small" title="实体 / 候选边界审核">
                <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 8 }}
                  message="品牌、品类、平台、方法不能混在一起；是否进入 Choice Candidate 必须按上下文人工可审。"
                  description="例如「抖音」可能是规则/权威方，不一定是可选择品牌；「短链工具」是品类，不等于具体品牌。"
                />
                {recommendationEntities.length === 0
                  ? <Empty description="当前没有可审核实体" />
                  : <Table
                      size="small"
                      rowKey="id"
                      pagination={{ pageSize: 8 }}
                      dataSource={recommendationEntities}
                      columns={[
                        { title: "实体", dataIndex: "canonical_name", width: 130, render: (value, row: any) => <Space direction="vertical" size={0}><Text strong>{value}</Text><Text type="secondary">{row.source_label}</Text></Space> },
                        { title: "类型", dataIndex: "entity_type_label", width: 90, render: (value) => <Tag>{value}</Tag> },
                        { title: "角色", width: 150, render: (_, row: any) => <Tag color="blue">{row.entity_role_label || entityRoleLabel(row.entity_role)}</Tag> },
                        { title: "选择候选", width: 100, render: (_, row: any) => row.is_choice_candidate ? <Tag color="green">可作为候选</Tag> : <Tag>非候选</Tag> },
                        { title: "出现", width: 90, render: (_, row: any) => <Tag>{row.mention_run_count} 次</Tag> },
                        { title: "操作", width: 260, render: (_, row: any) => <Space size={4} wrap>
                          <Button size="small" onClick={async () => {
                            const next = await api.reviewRecommendationEntity(row.id, { entity_role: "BRAND", is_choice_candidate: row.is_choice_candidate });
                            setRecommendationEntities(recommendationEntities.map((item) => item.id === row.id ? next : item));
                            message.success("已标记为品牌");
                          }}>品牌</Button>
                          <Button size="small" onClick={async () => {
                            const next = await api.reviewRecommendationEntity(row.id, { entity_role: "AUTHORITY", is_choice_candidate: false });
                            setRecommendationEntities(recommendationEntities.map((item) => item.id === row.id ? next : item));
                            message.success("已标记为规则/权威方");
                          }}>规则方</Button>
                          <Button size="small" type={row.is_choice_candidate ? "default" : "primary"} onClick={async () => {
                            const next = await api.reviewRecommendationEntity(row.id, { entity_role: row.entity_role || "BRAND", is_choice_candidate: !row.is_choice_candidate });
                            setRecommendationEntities(recommendationEntities.map((item) => item.id === row.id ? next : item));
                            message.success(next.is_choice_candidate ? "已标记为可选择候选" : "已标记为非候选");
                          }}>{row.is_choice_candidate ? "设为非候选" : "设为候选"}</Button>
                        </Space> },
                      ]}
                      expandable={{
                        expandedRowRender: (row: any) => <Space direction="vertical" size={6} style={{ width: "100%" }}>
                          <Text type="secondary">别名：{(row.aliases || []).join("，") || "无"}</Text>
                          {(row.representative_spans || []).map((span: string, index: number) => <Alert key={index} type="info" message={span} />)}
                        </Space>
                      }}
                    />}
              </Card>}
              {decisionMarket && <Row gutter={[12, 12]}>
                <Col xs={24} xl={12}>
                  <Card size="small" title="需求 / 方案对象市场">
                    <Row gutter={[12, 12]}>
                      <Col xs={24} md={12}>
                        <Table
                          size="small"
                          rowKey="need_label"
                          pagination={false}
                          dataSource={decisionMarket.need_market || []}
                          columns={[
                            { title: "需求", dataIndex: "need_label", render: (value) => <Tag color="blue">{value}</Tag> },
                            { title: "覆盖", width: 100, render: (_, row: any) => formatMetric(row.coverage) },
                          ]}
                        />
                      </Col>
                      <Col xs={24} md={12}>
                        <Table
                          size="small"
                          rowKey="solution_object"
                          pagination={false}
                          dataSource={decisionMarket.solution_object_market || []}
                          columns={[
                            { title: "方案对象", dataIndex: "solution_object_label", render: (value) => <Tag color="green">{value}</Tag> },
                            { title: "覆盖", width: 100, render: (_, row: any) => formatMetric(row.coverage) },
                          ]}
                        />
                      </Col>
                    </Row>
                  </Card>
                </Col>
                <Col xs={24} xl={12}>
                  <Card size="small" title="选择标准市场">
                    {(decisionMarket.selection_criteria_market?.criteria || []).length === 0
                      ? <Empty description="当前样本没有抽取到稳定选择标准" />
                      : <Table
                          size="small"
                          rowKey="criterion_type"
                          pagination={{ pageSize: 6 }}
                          dataSource={decisionMarket.selection_criteria_market.criteria || []}
                          columns={[
                            { title: "标准", dataIndex: "criterion_label", width: 110, render: (value) => <Tag color="blue">{value}</Tag> },
                            { title: "出现", width: 95, render: (_, row: any) => `${row.appearing_run_count} 次` },
                            { title: "用于选择", width: 95, render: (_, row: any) => formatMetric(row.usage_rate) },
                            { title: "关联品牌", render: (_, row: any) => <Space wrap>{(row.related_brands || []).map((name: string) => <Tag key={name}>{name}</Tag>)}</Space> },
                          ]}
                          expandable={{
                            expandedRowRender: (row: any) => <Space direction="vertical" size={6} style={{ width: "100%" }}>
                              {(row.items || []).map((item: any) => <Alert
                                key={item.id}
                                type={item.review_status === "CONFIRMED" ? "success" : item.review_status === "REJECTED" ? "error" : "info"}
                                message={<Space><Tag>采集 #{item.run_id}</Tag><Text>{item.answer_span}</Text></Space>}
                                description={<Space wrap>
                                  <Tag>{reviewStatusLabel(item.review_status)}</Tag>
                                  <Button size="small" onClick={async () => {
                                    await api.reviewDecisionSelectionCriterion(item.id, { review_status: "CONFIRMED", reviewer: "human" });
                                    await reloadRecommendationSnapshot();
                                    message.success("选择标准已确认");
                                  }}>确认标准</Button>
                                  <Button size="small" danger onClick={async () => {
                                    await api.reviewDecisionSelectionCriterion(item.id, { review_status: "REJECTED", reviewer: "human" });
                                    await reloadRecommendationSnapshot();
                                    message.success("选择标准已拒绝");
                                  }}>拒绝</Button>
                                </Space>}
                              />)}
                            </Space>
                          }}
                        />}
                  </Card>
                </Col>
              </Row>}
              {decisionMarket && <Row gutter={[12, 12]}>
                <Col xs={24} xl={14}>
                  <Card size="small" title="D. Prompt Recommendation Drivers">
                    <Alert
                      type="info"
                      showIcon
                      style={{ marginBottom: 8 }}
                      message={decisionMarket.recommendation_drivers?.boundary_note || "Driver 来自推荐理由、选择标准和能力识别，不是词频榜。"}
                    />
                    <Table
                      size="small"
                      rowKey="driver_key"
                      pagination={{ pageSize: 6 }}
                      scroll={{ x: 980 }}
                      dataSource={driverRows}
                      locale={{ emptyText: "当前没有可聚合的推荐驱动" }}
                      columns={[
                        { title: "驱动", dataIndex: "driver_label", width: 140, render: (value) => <Tag color="blue">{value}</Tag> },
                        { title: "覆盖", width: 95, render: (_, row: any) => <Tag>{row.supporting_run_count} 次</Tag> },
                        { title: "用于选择", width: 120, render: (_, row: any) => formatMetric(row.used_for_selection) },
                        { title: "目标品牌", width: 120, render: (_, row: any) => formatMetric(row.target_brand_observed) },
                        { title: "竞品", width: 120, render: (_, row: any) => formatMetric(row.competitor_observed) },
                        { title: "Product Truth", width: 150, render: (_, row: any) => <Tag color={row.product_truth_status === "SUPPORTED" ? "green" : row.product_truth_status === "NOT_SUPPORTED" ? "red" : "gold"}>{row.product_truth_status_label || truthStatusLabel(row.product_truth_status)}</Tag> },
                        { title: "诊断信号", dataIndex: "diagnostic_signal", width: 235, render: (value) => <Tag style={{ whiteSpace: "nowrap" }}>{value || "-"}</Tag> },
                      ]}
                      expandable={{
                        expandedRowRender: (row: any) => <Space direction="vertical" size={6} style={{ width: "100%" }}>
                          <Space wrap>{(row.winner_entities || []).map((name: string) => <Tag key={name}>{name}</Tag>)}</Space>
                          {(row.examples || []).map((example: string, index: number) => <Alert key={index} type="info" message={example} />)}
                        </Space>
                      }}
                    />
                  </Card>
                </Col>
                <Col xs={24} xl={10}>
                  <Card size="small" title="E. Source / Content Pattern">
                    <Alert
                      type="info"
                      showIcon
                      style={{ marginBottom: 8 }}
                      message={decisionMarket.source_content_pattern?.boundary_note || "这里只描述最终引用来源形态，不把检索候选当作引用漏斗。"}
                    />
                    <Descriptions size="small" column={1} style={{ marginBottom: 8 }}>
                      <Descriptions.Item label="引用出现">{formatMetric(decisionMarket.source_content_pattern?.metrics?.citation_presence_rate)}</Descriptions.Item>
                      <Descriptions.Item label="选择理由上下文">{formatMetric(decisionMarket.source_content_pattern?.metrics?.selection_reason_context_rate)}</Descriptions.Item>
                      <Descriptions.Item label="引用次数">{decisionMarket.source_content_pattern?.metrics?.citation_occurrence_count ?? 0}</Descriptions.Item>
                    </Descriptions>
                    <Table
                      size="small"
                      rowKey="content_type"
                      pagination={false}
                      dataSource={sourcePatternRows}
                      locale={{ emptyText: "当前没有可识别的来源内容形态" }}
                      columns={[
                        { title: "内容形态", dataIndex: "content_type_label", render: (value) => <Tag color="green">{value}</Tag> },
                        { title: "覆盖", width: 95, render: (_, row: any) => formatMetric(row.citation_coverage) },
                        { title: "出现", width: 70, render: (_, row: any) => <Tag>{row.occurrence_count}</Tag> },
                      ]}
                      expandable={{
                        expandedRowRender: (row: any) => <Space direction="vertical" size={4} style={{ width: "100%" }}>
                          {(row.representative_sources || []).map((source: any) => <a key={source.reference_id} href={source.url} target="_blank" rel="noreferrer">{source.title || source.url}</a>)}
                        </Space>
                      }}
                    />
                  </Card>
                </Col>
              </Row>}
              {decisionMarket && <Card size="small" title="品牌决策阶段">
                <Alert type="info" showIcon style={{ marginBottom: 8 }} message="这里不是严格漏斗，只按回答里能观察到的阶段信号归类；没有进入品牌推荐时，会直接显示当前未形成品牌推荐。" />
                <Table
                  size="small"
                  rowKey="brand_name"
                  pagination={{ pageSize: 8 }}
                  dataSource={decisionMarket.brand_funnel?.rows || []}
                  columns={[
                    { title: "品牌", dataIndex: "brand_name", width: 140, render: (value, row: any) => <Space><Text strong>{value}</Text>{row.is_target_brand && <Tag color="blue">目标品牌</Tag>}</Space> },
                    { title: "阶段", dataIndex: "derived_stage", width: 145, render: (value) => <Tag>{brandStageLabel(value)}</Tag> },
                    { title: "提及", width: 95, render: (_, row: any) => formatMetric(row.metrics?.mention_rate) },
                    { title: "需求关联", width: 105, render: (_, row: any) => formatMetric(row.metrics?.need_association_rate) },
                    { title: "能力识别", width: 105, render: (_, row: any) => formatMetric(row.metrics?.capability_recognition_rate) },
                    { title: "候选进入", width: 105, render: (_, row: any) => formatMetric(row.metrics?.candidate_capture_rate) },
                    { title: "明确推荐", width: 105, render: (_, row: any) => formatMetric(row.metrics?.explicit_recommendation_rate) },
                  ]}
                />
              </Card>}
              {decisionMarket && <Card size="small" title="可审计决策链：品牌 → 理由 → 引用上下文 → 动作">
                <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 8 }}
                  message="这张表把原答案里的品牌信号、推荐/候选理由、伴随引用资料和下一步动作放在一起；引用上下文只代表外显来源伴随出现，不代表来源已经支撑该理由。"
                  description={decisionMarket.primary_gap
                    ? `当前 Primary Gap：${decisionMarket.primary_gap.gap_type_label || decisionMarket.primary_gap.gap_type}。${decisionMarket.primary_gap.diagnosis_text || ""}`
                    : "若没有 Primary Gap，说明当前品牌选择空间或产品事实还不足以支持明确策略判断。"}
                />
                {decisionAuditRows.length === 0
                  ? <Empty description="当前没有可审计的品牌候选或推荐记录" />
                  : <Table
                      size="small"
                      rowKey="id"
                      pagination={{ pageSize: 8 }}
                      dataSource={decisionAuditRows}
                      columns={[
                        { title: "采集", dataIndex: "run_id", width: 70, render: (value) => <Tag>#{value}</Tag> },
                        { title: "品牌", dataIndex: "entity_name", width: 120, render: (value, row: any) => <Space direction="vertical" size={0}><Text strong>{value}</Text>{row.is_choice_candidate ? <Tag color="blue">进入候选</Tag> : <Tag>仅提及</Tag>}</Space> },
                        { title: "阶段", width: 120, render: (_, row: any) => <Tag color={row.recommendation_type === "POSITIVE_RECOMMENDATION" || row.recommendation_type === "TOP_RECOMMENDATION" ? "green" : row.recommendation_type === "CANDIDATE" ? "blue" : "default"}>{row.recommendation_type_label}</Tag> },
                        { title: "原答案片段", dataIndex: "recommendation_span", ellipsis: true },
                        { title: "理由", width: 220, render: (_, row: any) => (row.reason_texts || []).length > 0
                          ? <Space wrap>{row.reason_texts.map((item: string) => <Tag key={item} color="geekblue">{item}</Tag>)}</Space>
                          : <Text type="secondary">未抽取到明确理由</Text> },
                        { title: "伴随引用资料", width: 260, render: (_, row: any) => row.citation_contexts?.length > 0
                          ? <Space direction="vertical" size={2}>{row.citation_contexts.slice(0, 2).map((item: any) => <Space key={item.id} direction="vertical" size={0}>
                              <a href={item.source_url} target="_blank" rel="noreferrer">{item.source_title || item.source_url || "未知来源"}</a>
                              <Space size={4}><Tag color={item.evidence_status === "LINKED" ? "green" : item.evidence_status === "UNLINKED" ? "red" : "gold"}>{evidenceStatusLabel(item.evidence_status, item.evidence_status_label)}</Tag><Text type="secondary">{item.source_domain}</Text></Space>
                            </Space>)}</Space>
                          : <Text type="secondary">当前无可关联外显引用</Text> },
                        { title: "下一步", width: 220, render: (_, row: any) => <Space direction="vertical" size={2}><Text>{row.recommended_action}</Text><Text type="secondary">验证指标：{metricLabel(row.validation_metric)}</Text></Space> },
                      ]}
                      expandable={{
                        expandedRowRender: (row: any) => <Space direction="vertical" size={8} style={{ width: "100%" }}>
                          <Alert type="info" message="完整原答案片段" description={<pre className="content-preview">{row.answer_excerpt || row.answer_span || "暂无原答案"}</pre>} />
                          <Descriptions size="small" column={1}>
                            <Descriptions.Item label="推荐原文">{row.recommendation_span || row.answer_span || "-"}</Descriptions.Item>
                            <Descriptions.Item label="证据状态">{row.citation_contexts?.length > 0 ? row.citation_contexts.map((item: any) => `${item.evidence_status_label || item.evidence_status}：${item.source_title || item.source_domain || "未知来源"}`).join("；") : "当前可观测数据中未建立引用上下文"}</Descriptions.Item>
                            <Descriptions.Item label="策略边界">{decisionMarket.action_package?.product_truth_gate?.status_label || "产品事实未确认前，不自动生成确定性内容策略。"}</Descriptions.Item>
                          </Descriptions>
                        </Space>
                      }}
                    />}
              </Card>}
              {decisionMarket && <Card size="small" title="品牌能力识别">
                {(decisionMarket.capability_recognition?.claims || []).length === 0
                  ? <Alert type="warning" showIcon message="当前样本没有抽取到品牌能力识别 claim。品牌被提及不等于能力被识别，需要继续补齐可验证能力表达。" />
                  : <Table
                      size="small"
                      rowKey={(row: any) => `${row.brand_name}-${row.capability_label}`}
                      pagination={{ pageSize: 6 }}
                      dataSource={decisionMarket.capability_recognition.claims || []}
                      columns={[
                        { title: "品牌", dataIndex: "brand_name", width: 130, render: (value) => <Text strong>{value}</Text> },
                        { title: "能力", dataIndex: "capability_label", width: 150, render: (value) => <Tag color="blue">{value}</Tag> },
                        { title: "需求", width: 180, render: (_, row: any) => <Space wrap>{(row.need_labels || []).map((item: string) => <Tag key={item}>{item}</Tag>)}</Space> },
                        { title: "覆盖", width: 80, render: (_, row: any) => <Tag>{row.run_count} 次</Tag> },
                        { title: "谓词", dataIndex: "predicate", width: 120 },
                      ]}
                      expandable={{
                        expandedRowRender: (row: any) => <Space direction="vertical" size={6} style={{ width: "100%" }}>
                          {(row.claims || []).map((claim: any) => <Alert
                            key={claim.id}
                            type={claim.review_status === "CONFIRMED" ? "success" : claim.review_status === "REJECTED" ? "error" : "info"}
                            message={<Space><Tag>采集 #{claim.run_id}</Tag><Text>{claim.answer_span}</Text></Space>}
                            description={<Space wrap>
                              <Tag>{reviewStatusLabel(claim.review_status)}</Tag>
                              <Button size="small" onClick={async () => {
                                await api.reviewDecisionCapabilityClaim(claim.id, { review_status: "CONFIRMED", reviewer: "human" });
                                await reloadRecommendationSnapshot();
                                message.success("能力识别已确认");
                              }}>确认能力</Button>
                              <Button size="small" danger onClick={async () => {
                                await api.reviewDecisionCapabilityClaim(claim.id, { review_status: "REJECTED", reviewer: "human" });
                                await reloadRecommendationSnapshot();
                                message.success("能力识别已拒绝");
                              }}>拒绝</Button>
                            </Space>}
                          />)}
                        </Space>
                      }}
                    />}
              </Card>}
              {decisionMarket && <Card size="small" title="目标品牌产品事实核对">
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 8 }}
                  message={decisionMarket.product_truth?.boundary_note || "产品事实必须人工确认，不能由系统自动猜。"}
                  description={decisionMarket.action_package?.product_truth_gate?.status_label || "请先核对目标品牌是否真实具备这些能力。"}
                />
                <Table
                  size="small"
                  rowKey={(row: any) => row.capability_key}
                  pagination={false}
                  dataSource={decisionMarket.product_truth?.truths || []}
                  locale={{ emptyText: "当前没有待核对的产品能力" }}
                  columns={[
                    { title: "能力", dataIndex: "capability_label", render: (value) => <Text strong>{value}</Text> },
                    { title: "事实状态", width: 110, render: (_, row: any) => <Tag color={row.product_truth_status === "SUPPORTED" ? "green" : row.product_truth_status === "NOT_SUPPORTED" ? "red" : "gold"}>{row.product_truth_status_label || truthStatusLabel(row.product_truth_status)}</Tag> },
                    { title: "来源", dataIndex: "truth_source", width: 130, render: (value) => <Text type={value ? undefined : "secondary"}>{truthSourceLabel(value)}</Text> },
                    { title: "人工核对", width: 220, render: (_, row: any) => <Space size={4} wrap>
                      <Button size="small" onClick={async () => {
                        await api.upsertTargetBrandCapabilityTruth(projectId!, { capability_label: row.capability_label, product_truth_status: "SUPPORTED", truth_source: "MANUAL_CONFIRMED", reviewed_by: "human" });
                        await reloadRecommendationSnapshot();
                        message.success("已确认真实支持");
                      }}>支持</Button>
                      <Button size="small" onClick={async () => {
                        await api.upsertTargetBrandCapabilityTruth(projectId!, { capability_label: row.capability_label, product_truth_status: "PARTIALLY_SUPPORTED", truth_source: "MANUAL_CONFIRMED", reviewed_by: "human" });
                        await reloadRecommendationSnapshot();
                        message.success("已标记部分支持");
                      }}>部分</Button>
                      <Button size="small" danger onClick={async () => {
                        await api.upsertTargetBrandCapabilityTruth(projectId!, { capability_label: row.capability_label, product_truth_status: "NOT_SUPPORTED", truth_source: "MANUAL_CONFIRMED", reviewed_by: "human" });
                        await reloadRecommendationSnapshot();
                        message.success("已标记不支持");
                      }}>不支持</Button>
                    </Space> },
                  ]}
                />
              </Card>}
              {decisionMarket && <Row gutter={[12, 12]}>
                <Col xs={24} xl={12}>
                  <Card size="small" title="引用资料分析（主）">
                    <Alert type="info" showIcon style={{ marginBottom: 8 }} message={decisionMarket.citation_source_analysis?.boundary_note || "引用资料是主分析对象；检索候选只作为重合度旁证。"} />
                    <Descriptions size="small" column={1} style={{ marginBottom: 8 }}>
                      <Descriptions.Item label="引用覆盖">{formatMetric(decisionMarket.citation_source_analysis?.metrics?.cited_run_rate)}</Descriptions.Item>
                      <Descriptions.Item label="检索重合">{formatMetric(decisionMarket.citation_source_analysis?.metrics?.retrieval_overlap_rate)}</Descriptions.Item>
                      <Descriptions.Item label="引用全包含于检索">{formatMetric(decisionMarket.citation_source_analysis?.metrics?.full_reference_in_retrieval_rate)}</Descriptions.Item>
                    </Descriptions>
                    <Table
                      size="small"
                      rowKey="url"
                      pagination={{ pageSize: 5 }}
                      dataSource={decisionMarket.citation_source_analysis?.top_sources || []}
                      locale={{ emptyText: "当前没有引用资料" }}
                      columns={[
                        { title: "引用页面", render: (_, row: any) => <Space direction="vertical" size={0}><a href={row.url} target="_blank" rel="noreferrer">{row.title || row.url}</a><Text type="secondary">{row.domain}</Text></Space> },
                        { title: "覆盖采样", width: 90, render: (_, row: any) => <Tag>{row.run_count} 次</Tag> },
                        { title: "出现", width: 70, render: (_, row: any) => <Tag>{row.occurrence_count}</Tag> },
                        { title: "检索重合", width: 90, render: (_, row: any) => <Tag>{row.retrieval_overlap_run_count} 次</Tag> },
                      ]}
                    />
                  </Card>
                </Col>
                <Col xs={24} xl={12}>
                  <Card size="small" title="引用上下文：推荐理由伴随来源">
                    <Alert type="info" showIcon style={{ marginBottom: 8 }} message={decisionMarket.citation_context?.boundary_note || "这里只展示推荐/理由与引用资料的上下文关联，不代表引用支撑推荐。"} />
                    <Table
                      size="small"
                      rowKey="id"
                      pagination={{ pageSize: 5 }}
                      dataSource={decisionMarket.citation_context?.adoptions || []}
                      locale={{ emptyText: "当前还没有可审计的引用上下文" }}
                      columns={[
                        { title: "来源", width: 220, render: (_, row: any) => <Space direction="vertical" size={0}><a href={row.source_url} target="_blank" rel="noreferrer">{row.source_title || row.source_url || "未知来源"}</a><Text type="secondary">{row.source_domain}</Text></Space> },
                        { title: "状态", width: 120, render: (_, row: any) => <Tag color={row.evidence_status === "LINKED" ? "green" : row.evidence_status === "UNLINKED" ? "red" : "gold"}>{evidenceStatusLabel(row.evidence_status, row.evidence_status_label)}</Tag> },
                        { title: "关系", width: 130, render: (_, row: any) => <Tag>{row.support_role_label}</Tag> },
                        { title: "回答片段", dataIndex: "answer_span", ellipsis: true },
                        { title: "审核", width: 130, render: (_, row: any) => <Space size={4}>
                          <Button size="small" onClick={async () => {
                            await api.reviewDecisionEvidenceAdoption(row.id, { review_status: "CONFIRMED", reviewer: "human" });
                            await reloadRecommendationSnapshot();
                            message.success("引用关联已确认");
                          }}>确认</Button>
                          <Button size="small" danger onClick={async () => {
                            await api.reviewDecisionEvidenceAdoption(row.id, { review_status: "REJECTED", reviewer: "human" });
                            await reloadRecommendationSnapshot();
                            message.success("引用关联已拒绝");
                          }}>拒绝</Button>
                        </Space> },
                      ]}
                    />
                  </Card>
                </Col>
              </Row>}
              {decisionMarket && <Card size="small" title="引用正文对齐：回答主张 ↔ 来源段落">
                <Alert
                  type={recommendationPassageSupport?.eligibility === "PASSAGE_ALIGNMENT_AVAILABLE" ? "success" : "warning"}
                  showIcon
                  style={{ marginBottom: 8 }}
                  message={recommendationPassageSupport?.eligibility_label || "需要先抓取引用正文并运行段落对齐"}
                  description={recommendationPassageSupport?.boundary_note || "这里展示回答主张与引用页面正文的文本对齐状态。精确/近似对齐可以作为正文支撑的候选证据，但仍需人工确认语义是否真的支撑。"}
                />
                {recommendationPassageSupport?.rows?.length > 0
                  ? <Space direction="vertical" size={8} style={{ width: "100%" }}>
                      <Row gutter={[12, 12]}>
                        <Col xs={12} md={6}><Statistic title="回答主张" value={recommendationPassageSupport.metrics?.claim_count?.numerator || 0} /></Col>
                        <Col xs={12} md={6}><Statistic title="精确对齐" value={formatMetric(recommendationPassageSupport.metrics?.direct_text_match_rate)} /></Col>
                        <Col xs={12} md={6}><Statistic title="近似对齐" value={formatMetric(recommendationPassageSupport.metrics?.near_text_match_rate)} /></Col>
                        <Col xs={12} md={6}><Statistic title="未对齐" value={formatMetric(recommendationPassageSupport.metrics?.unresolved_rate)} /></Col>
                      </Row>
                      <Table
                        size="small"
                        rowKey="answer_claim_id"
                        pagination={{ pageSize: 8 }}
                        dataSource={recommendationPassageSupport.rows || []}
                        columns={[
                          { title: "采集", dataIndex: "run_id", width: 70, render: (value) => <Tag>#{value}</Tag> },
                          { title: "回答主张", dataIndex: "claim_text", ellipsis: true },
                          { title: "对齐状态", width: 130, render: (_, row: any) => <Tag color={passageAlignmentColor(row.alignment_status)}>{row.alignment_status_label}</Tag> },
                          { title: "来源", width: 260, render: (_, row: any) => row.source_url ? <Space direction="vertical" size={0}><a href={row.source_url} target="_blank" rel="noreferrer">{row.source_title || row.source_url}</a><Text type="secondary">{row.source_domain}</Text></Space> : <Text type="secondary">暂无来源段落</Text> },
                          { title: "证据", dataIndex: "evidence", ellipsis: true },
                        ]}
                        expandable={{
                          expandedRowRender: (row: any) => <Space direction="vertical" size={6} style={{ width: "100%" }}>
                            <Alert type="info" message="判断边界" description={row.support_boundary} />
                            <Descriptions size="small" column={1}>
                              <Descriptions.Item label="回答主张">{row.claim_text}</Descriptions.Item>
                              <Descriptions.Item label="对齐方法">{row.alignment_method || "暂无"}</Descriptions.Item>
                              <Descriptions.Item label="分数">{row.score}</Descriptions.Item>
                              <Descriptions.Item label="引用编号">{(row.citation_ids || []).join("，") || row.citation_id || "-"}</Descriptions.Item>
                            </Descriptions>
                          </Space>
                        }}
                      />
                    </Space>
                  : <Empty description="当前诊断快照没有正文对齐结果。请到「证据标注」页选择同一问题，先抓取引用正文并加载段落对齐。" />}
              </Card>}
              {decisionMarket && <Row gutter={[12, 12]}>
                <Col xs={24} xl={12}>
                  <Card size="small" title="结构化差距诊断">
                    {(decisionMarket.gap_diagnosis || []).length === 0
                      ? <Empty description="暂无结构化差距" />
                      : <Space direction="vertical" size={8} style={{ width: "100%" }}>
                          {(decisionMarket.gap_diagnosis || []).map((gap: any) => <Alert
                            key={gap.gap_type}
                            type={gap.severity === "HIGH" ? "error" : gap.severity === "MEDIUM" ? "warning" : "info"}
                            showIcon
                            message={<Space><Tag>{gap.gap_type_label}</Tag><Text strong>{gap.diagnosis_text}</Text></Space>}
                            description={<Space direction="vertical" size={4}>
                              <Text>{gap.action_hint}</Text>
                              <Text type="secondary">指标：{formatMetric(gap.metric)}</Text>
                              {gap.id && <Space wrap>
                                <Tag>{reviewStatusLabel(gap.review_status)}</Tag>
                                <Button size="small" onClick={async () => {
                                  await api.reviewDecisionGap(gap.id, { review_status: "CONFIRMED", reviewer: "human" });
                                  await reloadRecommendationSnapshot();
                                  message.success("差距诊断已确认");
                                }}>确认诊断</Button>
                                <Button size="small" danger onClick={async () => {
                                  await api.reviewDecisionGap(gap.id, { review_status: "REJECTED", reviewer: "human" });
                                  await reloadRecommendationSnapshot();
                                  message.success("差距诊断已拒绝");
                                }}>拒绝</Button>
                              </Space>}
                            </Space>}
                          />)}
                        </Space>}
                  </Card>
                </Col>
              </Row>}
              <Card size="small" title="品牌推荐状态" extra={<Tag>{recommendationData.landscape_scope_label || "仅统计品牌"}</Tag>}>
                {(recommendationData.landscape || []).length === 0
                  ? <Alert
                      type="warning"
                      showIcon
                      message="当前没有品牌推荐"
                      description="智能回答里没有出现项目品牌或竞品品牌的候选、提及或明确推荐。下方会根据回答内容判断是否存在品牌露出机会。"
                    />
                  : <Table
                      size="small"
                      rowKey="entity_name"
                      pagination={{ pageSize: 8 }}
                      dataSource={recommendationData.landscape || []}
                      columns={[
                        { title: "品牌", dataIndex: "entity_name", width: 170, render: (value) => <Text strong>{value}</Text> },
                        { title: "提及", width: 80, render: (_, row: any) => <Tag>{row.mention_run_count}/{recommendationData.run_count}</Tag> },
                        { title: "候选", width: 80, render: (_, row: any) => <Tag color="blue">{row.candidate_run_count}/{recommendationData.run_count}</Tag> },
                        { title: "明确推荐", width: 95, render: (_, row: any) => <Tag color="green">{row.recommendation_run_count}/{recommendationData.run_count}</Tag> },
                        { title: "第一推荐", width: 95, render: (_, row: any) => <Tag color="gold">{row.top1_run_count}/{recommendationData.run_count}</Tag> },
                        { title: "推荐份额", width: 90, render: (_, row: any) => `${Math.round((row.ai_recommendation_share || 0) * 100)}%` },
                        { title: "稳定度", width: 90, render: (_, row: any) => <Tag>{row.recommendation_stability === "HIGH" ? "高" : row.recommendation_stability === "MEDIUM" ? "中" : row.recommendation_stability === "LOW" ? "低" : "样本不足"}</Tag> },
                      ]}
                      expandable={{
                        expandedRowRender: (row: any) => <Space direction="vertical" size={6}>
                          <Text type="secondary">典型回答片段</Text>
                          {(row.representative_claims || []).map((claim: string, index: number) => <Alert key={index} type="info" message={claim} />)}
                        </Space>
                      }}
                    />}
              </Card>
              <Card size="small" title="为什么品牌进入选择：推荐理由审核">
                <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 8 }}
                  message="推荐理由必须绑定到具体品牌和具体推荐判断，不能只看答案级理由词池。"
                  description="确认理由前，系统只把它作为规则抽取结果；确认后才能更稳妥地用于 Product Truth 核对和策略路由。"
                />
                {reasonMarketRows.length === 0
                  ? <Empty description="当前没有抽取到品牌级推荐理由" />
                  : <Table
                      size="small"
                      rowKey="key"
                      pagination={{ pageSize: 8 }}
                      dataSource={reasonMarketRows}
                      columns={[
                        { title: "品牌", dataIndex: "entity_name", width: 130, render: (value) => <Text strong>{value}</Text> },
                        { title: "理由类型", dataIndex: "reason_type_label", width: 120, render: (value) => <Tag color="blue">{value}</Tag> },
                        { title: "理由原文", dataIndex: "reason_text", ellipsis: true },
                        { title: "覆盖采样", width: 95, render: (_, row: any) => <Tag>{row.run_count} 次</Tag> },
                      ]}
                      expandable={{
                        expandedRowRender: (row: any) => <Table
                          size="small"
                          rowKey="id"
                          pagination={false}
                          dataSource={row.items || []}
                          columns={[
                            { title: "采集", dataIndex: "run_id", width: 70, render: (value) => <Tag>#{value}</Tag> },
                            { title: "理由片段", dataIndex: "reason_span", ellipsis: true },
                            { title: "推荐片段", dataIndex: "claim_span", ellipsis: true },
                            { title: "状态", width: 95, render: (_, item: any) => <Tag>{reviewStatusLabel(item.review_status)}</Tag> },
                            { title: "审核", width: 150, render: (_, item: any) => <Space size={4}>
                              <Button size="small" onClick={async () => {
                                const next = await api.reviewRecommendationReason(item.id, { review_status: "CONFIRMED", reviewer: "human" });
                                setRecommendationReasons(recommendationReasons.map((reason) => reason.id === item.id ? next : reason));
                                message.success("推荐理由已确认");
                              }}>确认</Button>
                              <Button size="small" danger onClick={async () => {
                                const next = await api.reviewRecommendationReason(item.id, { review_status: "REJECTED", reviewer: "human" });
                                setRecommendationReasons(recommendationReasons.map((reason) => reason.id === item.id ? next : reason));
                                message.success("推荐理由已拒绝");
                              }}>拒绝</Button>
                            </Space> },
                          ]}
                        />
                      }}
                    />}
              </Card>
              <Card size="small" title="品牌露出机会判断">
                <Alert
                  type={recommendationData.brand_opportunity?.opportunity_detected ? "success" : "info"}
                  showIcon
                  message={recommendationData.brand_opportunity?.status_label || "暂无判断"}
                  description={recommendationData.brand_opportunity?.summary || "生成后会根据回答内容判断品牌是否有机会露出。"}
                />
                {recommendationData.brand_opportunity?.recommended_next_action && <Alert
                  type="info"
                  showIcon
                  style={{ marginTop: 8 }}
                  message="建议动作"
                  description={recommendationData.brand_opportunity.recommended_next_action}
                />}
                {(recommendationData.brand_opportunity?.signals || []).length > 0 && <Table
                  style={{ marginTop: 8 }}
                  size="small"
                  rowKey="signal_type"
                  pagination={false}
                  dataSource={recommendationData.brand_opportunity.signals}
                  columns={[
                    { title: "机会信号", dataIndex: "signal_label", width: 150, render: (value) => <Tag color="blue">{value}</Tag> },
                    { title: "覆盖采样", width: 90, render: (_, row: any) => <Tag>{row.run_count} 次</Tag> },
                    { title: "关键词", width: 220, render: (_, row: any) => <Space wrap>{(row.matched_keywords || []).slice(0, 6).map((item: string) => <Tag key={item}>{item}</Tag>)}</Space> },
                    { title: "典型回答", render: (_, row: any) => <Text type="secondary">{(row.examples || [])[0] || "-"}</Text> },
                  ]}
                />}
              </Card>
              <Card size="small" title="原答案样本">
                {(recommendationData.answer_samples || []).length === 0
                  ? <Empty description="暂无可展示的原答案样本" />
                  : <Table
                      size="small"
                      rowKey="run_id"
                      pagination={{ pageSize: 6 }}
                      dataSource={recommendationData.answer_samples || []}
                      columns={[
                        { title: "采集", dataIndex: "run_id", width: 70, render: (value) => <Tag>#{value}</Tag> },
                        { title: "选择原因", dataIndex: "why_selected", width: 190 },
                        { title: "引用数", dataIndex: "reference_count", width: 70, render: (value) => <Tag>{value || 0}</Tag> },
                        { title: "关键句", render: (_, row: any) => <Space direction="vertical" size={4}>{(row.key_sentences || []).slice(0, 3).map((item: string, index: number) => <Text key={index} type="secondary">{item}</Text>)}</Space> },
                      ]}
                      expandable={{
                        expandedRowRender: (row: any) => <pre className="content-preview">{row.answer_excerpt}</pre>
                      }}
                    />}
              </Card>
              <Card size="small" title="引用资料线索">
                {(recommendationData.citation_sources || []).length === 0
                  ? <Alert type="warning" showIcon message="当前没有可展示的引用资料线索。需要先补齐引用抓取或证据归因。" />
                  : <Table
                      size="small"
                      rowKey="citation_id"
                      pagination={{ pageSize: 8 }}
                      dataSource={recommendationData.citation_sources || []}
                      columns={[
                        { title: "来源", width: 260, render: (_, row: any) => <Space direction="vertical" size={2}><a href={row.url} target="_blank" rel="noreferrer">{row.title || row.url}</a><Text type="secondary">{row.domain}</Text></Space> },
                        { title: "角色", width: 110, render: (_, row: any) => <Tag color="green">{row.evidence_role_label}</Tag> },
                        { title: "关联对象", dataIndex: "related_entity", width: 100, render: (value) => value ? <Tag>{value}</Tag> : <Text type="secondary">待判断</Text> },
                        { title: "为什么重要", dataIndex: "why_matters", width: 220 },
                        { title: "来源片段", dataIndex: "source_passage", ellipsis: true },
                      ]}
                    />}
              </Card>
              <Card size="small" title="诊断结论：送入最终策略">
                {decisionMarket?.action_package
                  ? <Space direction="vertical" size={12} style={{ width: "100%" }}>
                      <Alert
                        type={interventionFeasibility.status === "READY_FOR_HUMAN_REVIEW" ? "success" : "warning"}
                        showIcon
                        message={<Space wrap><Tag color={feasibilityColor(interventionFeasibility.status)}>{interventionFeasibility.status_label || "待人工审核"}</Tag><Text>{(interventionFeasibility.reasons || [])[0] || "只能生成待审核策略候选。"}</Text></Space>}
                        description={interventionFeasibility.boundary_note || "干预候选不是执行命令；只有人工审核后的 effective_payload=VALIDATED 才能物化 Action/Experiment。"}
                      />
                      <Descriptions size="small" column={1}>
                        <Descriptions.Item label="机会类型">{decisionMarket.action_package.opportunity_type_label}</Descriptions.Item>
                        <Descriptions.Item label="资产决策">{decisionMarket.action_package.asset_decision_label}</Descriptions.Item>
                        <Descriptions.Item label="推荐干预">{promptInterventionCandidates[0]
                          ? `${interventionTypeLabel(promptInterventionCandidates[0].intervention_type)}，执行字段：${promptInterventionCandidates[0].target_platform || "UNRESOLVED"} / ${promptInterventionCandidates[0].target_asset || "UNRESOLVED"}`
                          : "暂无干预候选"}</Descriptions.Item>
                        <Descriptions.Item label="必须回答">{(decisionMarket.action_package.must_answer || []).map((item: string, index: number) => <div key={index}>问题{index + 1}：{item}</div>)}</Descriptions.Item>
                        <Descriptions.Item label="选择理由缺口">{decisionMarket.action_package.selection_reason_gap}</Descriptions.Item>
                        <Descriptions.Item label="证据要求">{(decisionMarket.action_package.evidence_requirements || []).join("；")}</Descriptions.Item>
                        <Descriptions.Item label="内容简报">{decisionMarket.action_package.content_brief?.page_goal}</Descriptions.Item>
                        <Descriptions.Item label="建议模块">{(decisionMarket.action_package.content_brief?.sections || []).join(" / ")}</Descriptions.Item>
                        <Descriptions.Item label="实验提案">{interventionFamilyLabel(decisionMarket.action_package.experiment_proposal?.intervention_family)}，主指标：{metricLabel(decisionMarket.action_package.experiment_proposal?.primary_metric)}</Descriptions.Item>
                        <Descriptions.Item label="验证边界">
                          一次实验只验证一个主要机制假设；发布后需固定复采，并记录模型版本、引用格局、竞品来源、品牌市场等已知变化。
                        </Descriptions.Item>
                        <Descriptions.Item label="可比性提醒">
                          草案阶段默认为「上下文不足」，不能声称环境完全不变；结论页只能表达当前观察窗口内是否发现显著已知混杂因素。
                        </Descriptions.Item>
                      </Descriptions>
                      <Alert type="warning" showIcon message="这里不产出最终策略。点击下方按钮只会生成待审核 StrategyCandidate；不会直接创建 Action / Experiment。" />
                      <Button type="primary" loading={recommendationLoading} onClick={createDecisionExperimentDraft}>送入最终策略：生成待审核策略候选</Button>
                    </Space>
                  : !recommendationData.action_brief
                  ? <Empty description="暂无行动说明" />
                  : <Descriptions size="small" column={1}>
                      <Descriptions.Item label="目标">{recommendationData.action_brief.goal}</Descriptions.Item>
                      <Descriptions.Item label="现状">{recommendationData.action_brief.situation}</Descriptions.Item>
                      <Descriptions.Item label="必须回答">{(recommendationData.action_brief.must_answer || []).map((item: string, index: number) => <div key={index}>第{index + 1}步：{item}</div>)}</Descriptions.Item>
                      <Descriptions.Item label="页面结构">{(recommendationData.action_brief.content_sections || []).map((item: string, index: number) => <div key={index}>模块{index + 1}：{item}</div>)}</Descriptions.Item>
                      <Descriptions.Item label="需要证据">{(recommendationData.action_brief.evidence_to_collect || []).join("；")}</Descriptions.Item>
                      <Descriptions.Item label="验证方式">{recommendationData.action_brief.validation}</Descriptions.Item>
                    </Descriptions>}
              </Card>
              <Row gutter={[12, 12]}>
                <Col xs={24} xl={12}>
                  <Card size="small" title="智能回答当前认知">
                    <Table
                      size="small"
                      rowKey="entity_name"
                      pagination={{ pageSize: 5 }}
                      dataSource={recommendationData.positioning || []}
                      columns={[
                        { title: "对象", dataIndex: "entity_name", width: 120 },
                        { title: "推荐理由", render: (_, row: any) => <Space wrap>{(row.dominant_reason_clusters || []).map((item: string) => <Tag key={item} color="blue">{item}</Tag>)}</Space> },
                        { title: "稳定度", width: 80, render: (_, row: any) => <Tag>{row.reason_consistency === "HIGH" ? "高" : row.reason_consistency === "MEDIUM" ? "中" : row.reason_consistency === "LOW" ? "低" : "样本不足"}</Tag> },
                      ]}
                      expandable={{
                        expandedRowRender: (row: any) => <Space direction="vertical" size={6}>
                          <Text type="secondary">这表示智能回答里的认知结构，不代表产品真实事实。</Text>
                          {(row.representative_claims || []).map((claim: string, index: number) => <Alert key={index} type="info" message={claim} />)}
                        </Space>
                      }}
                    />
                  </Card>
                </Col>
                <Col xs={24} xl={12}>
                  <Card size="small" title="竞争差距诊断">
                    {(recommendationData.gap_diagnosis || []).length === 0
                      ? <Empty description="暂无明确差距" />
                      : <Space direction="vertical" size={8} style={{ width: "100%" }}>
                          {(recommendationData.gap_diagnosis || []).map((gap: any, index: number) => <Alert
                            key={`${gap.gap_type}-${index}`}
                            type={gap.severity === "HIGH" ? "error" : gap.severity === "MEDIUM" ? "warning" : "info"}
                            showIcon
                            message={<Space><Tag>{gap.gap_type_label}</Tag><Text strong>{gap.diagnosis}</Text></Space>}
                            description={gap.evidence_basis}
                          />)}
                        </Space>}
                  </Card>
                </Col>
              </Row>
              <Card size="small" title="推荐证据归因">
                {(recommendationData.evidence_links || []).length === 0
                  ? <Alert type="warning" showIcon message="当前外显引用证据还没有可靠归因。这里只能说明证据链未建立，不能推断为模型训练语料或内部偏好。" />
                  : <Table
                      size="small"
                      rowKey="id"
                      pagination={{ pageSize: 6 }}
                      dataSource={recommendationData.evidence_links || []}
                      columns={[
                        { title: "对象", dataIndex: "supported_entity_name", width: 120 },
                        { title: "证据角色", width: 120, render: (_, row: any) => <Tag color="green">{row.primary_evidence_role_label}</Tag> },
                        { title: "置信度", width: 80, render: (_, row: any) => <Tag>{Math.round((row.attribution_confidence || 0) * 100)}%</Tag> },
                        { title: "回答片段", dataIndex: "answer_span", ellipsis: true },
                        { title: "来源片段", dataIndex: "source_passage", ellipsis: true },
                      ]}
                    />}
              </Card>
              <Card size="small" title="干预候选">
                {promptInterventionCandidates.length === 0
                  ? <Empty description="当前没有干预候选" />
                  : <Space direction="vertical" size={8} style={{ width: "100%" }}>
                    {promptInterventionCandidates.map((item: any, index: number) => <Card key={index} size="small">
                      <Descriptions size="small" column={1}>
                        <Descriptions.Item label="干预类型"><Tag color={item.intervention_type === "NO_ACTION" ? "default" : "blue"}>{item.intervention_type_label || interventionTypeLabel(item.intervention_type)}</Tag></Descriptions.Item>
                        <Descriptions.Item label="可行性"><Tag color={feasibilityColor(item.feasibility_status)}>{interventionFeasibility.status_label || item.feasibility_status || "-"}</Tag></Descriptions.Item>
                        <Descriptions.Item label="Primary Gap">{item.primary_gap_type_label || item.competitive_gap_type_label || "-"}</Descriptions.Item>
                        <Descriptions.Item label="当前问题">{item.observed_problem || item.observed_market_problem || "-"}</Descriptions.Item>
                        <Descriptions.Item label="建议方向">{item.recommended_direction || item.target_decision_position || "-"}</Descriptions.Item>
                        <Descriptions.Item label="执行字段">平台：{item.target_platform || "UNRESOLVED"}；资产：{item.target_asset || "UNRESOLVED"}；URL：{item.target_url || "未确认"}</Descriptions.Item>
                        <Descriptions.Item label="候选 URL">{item.suggested_target_url ? `${item.suggested_target_url}（${item.suggested_target_url_note || "仅供人工审核"}）` : "待人工确认"}</Descriptions.Item>
                        <Descriptions.Item label="证据前提">{(item.evidence_prerequisites || item.required_evidence || []).join("；") || "待补充"}</Descriptions.Item>
                        <Descriptions.Item label="执行边界">{item.execution_boundary || "StrategyCandidate -> 人工审核 -> effective_payload=VALIDATED -> Action -> Experiment"}</Descriptions.Item>
                      </Descriptions>
                    </Card>)}
                  </Space>}
              </Card>
              <Card size="small" title="推荐判断人工审核">
                <Table
                  size="small"
                  rowKey="id"
                  pagination={{ pageSize: 10 }}
                  dataSource={recommendationClaims}
                  columns={[
                    { title: "采集记录", dataIndex: "run_id", width: 80 },
                    { title: "对象", dataIndex: "entity_name", width: 140 },
                    { title: "类型", width: 100, render: (_, row: any) => <Tag color={row.recommendation_type === "POSITIVE_RECOMMENDATION" || row.recommendation_type === "TOP_RECOMMENDATION" ? "green" : row.recommendation_type === "CANDIDATE" ? "blue" : row.recommendation_type === "NEGATIVE_RECOMMENDATION" ? "red" : "default"}>{row.recommendation_type_label}</Tag> },
                    { title: "条件", width: 100, render: (_, row: any) => row.is_conditional ? <Tag color="orange">{row.condition_type_label || "有条件"}</Tag> : <Text type="secondary">无</Text> },
                    { title: "回答原文", dataIndex: "answer_span", ellipsis: true },
                    { title: "审核", width: 150, render: (_, row: any) => <Space size={4}>
                      <Button size="small" onClick={async () => {
                        const next = await api.reviewRecommendationClaim(row.id, { review_status: "CONFIRMED", reviewer: "human" });
                        setRecommendationClaims(recommendationClaims.map((claim) => claim.id === row.id ? next : claim));
                        message.success("已确认");
                      }}>确认</Button>
                      <Button size="small" danger onClick={async () => {
                        const next = await api.reviewRecommendationClaim(row.id, { review_status: "REJECTED", reviewer: "human" });
                        setRecommendationClaims(recommendationClaims.map((claim) => claim.id === row.id ? next : claim));
                        message.success("已拒绝");
                      }}>拒绝</Button>
                    </Space> },
                  ]}
                />
              </Card>
            </Space>}
          </Card>
        </Space> : page === "optimization" ? <Space direction="vertical" size={16} className="page-stack">
          <Card size="small" title="生成证据" extra={<Space>
            <Button size="small" onClick={async()=>{try{await loadEvidencePackages(projectId!);message.success("列表已刷新")}catch(e:any){message.error(e.message)}}}>刷新列表</Button>
            {selectedPrompts.length>0 && <Button type="primary" size="small" loading={loading} onClick={createEvidencePackagesForSelectedPrompts}>生成选中证据 ({selectedPrompts.length})</Button>}
          </Space>}>
            {evidencePackageNotice && <Alert
              showIcon
              type={evidencePackageNotice.type}
              style={{ marginBottom: 12 }}
              message={evidencePackageNotice.message}
              description={evidencePackageNotice.description}
              closable
              onClose={() => setEvidencePackageNotice(null)}
            />}
            <Table size="small" rowKey="id" pagination={{pageSize:8}}
              dataSource={[...prompts].sort((a,b)=>(b.id as number)-(a.id as number))}
              rowSelection={{
                selectedRowKeys:selectedPrompts,
                onChange:setSelectedPrompts,
                getCheckboxProps:(row:any)=>({ disabled: evidenceRunStats(row.id).valid === 0 })
              }}
              columns={[
                {title:"编号",dataIndex:"id",width:50},
                {title:"问题内容",dataIndex:"prompt_text",ellipsis:true},
                {title:"有效采样",width:110,render:(_,row:any)=>{
                  const stats = evidenceRunStats(row.id);
                  return stats.valid ? <Tag color="green">{stats.valid}/{stats.total}</Tag> : <Tag color="red">无有效采样</Tag>;
                }},
                {title:"引用资料",width:120,render:(_,row:any)=>{
                  const stats = evidenceRunStats(row.id);
                  return stats.citation ? <Text>{stats.citation} 条采样 · {stats.references} 条引用</Text> : <Text type="secondary">暂无引用</Text>;
                }},
                {title:"证据状态",width:180,render:(_,row:any)=>{
                  const pkg = latestEvidencePackageForPrompt(row.id);
                  return pkg ? <Button size="small" type="link" onClick={() => selectEvidencePackage(pkg.id)}>已生成 #{pkg.id} · {formatDateTime(pkg.created_at)}</Button> : <Text type="secondary">未生成</Text>;
                }},
              ]}
            />
          </Card>
          <Card title="最终策略" extra={<Tag color="green">人工确认后进入实验</Tag>}>
            <Alert type="info" showIcon style={{marginBottom:12}}
              message="这里是唯一策略确认页：承接证据、诊断、策略和实验计划。其他页面只提供监测、诊断或证据。"
              description="策略由客观证据推导，不预设方案；真实业务效果必须经过发布确认、固定复测和人工结论后才能关闭。"
            />
            <Space direction="vertical" style={{width:"100%"}}>
              <Text>选择证据查看已有策略，或生成新的待审核策略。</Text>
              <Space>
                <Select placeholder="选证据" style={{width:360}} value={selectedPkgId}
                  onChange={(v)=>selectEvidencePackage(v)}
                  notFoundContent={evidencePackages?.length===0?"暂无证据，请先在上方生成":undefined}
                  options={(evidencePackages||[]).map((p:any)=>({label:`证据 #${p.id} · ${formatDateTime(p.created_at)} ·「${p.prompt_text||'#'+(p.prompt_id||'?')}」· 版本 ${p.version}`,value:p.id}))}
                />
                <Button onClick={async()=>{try{await loadEvidencePackages(projectId!)}catch{}}}>刷新列表</Button>
                <Button type="primary" loading={strategyLoading} disabled={!selectedPkgId}
                  onClick={regenerateStrategies}>重新生成策略</Button>
              </Space>
            </Space>
            {strategyNotice && <Alert
              showIcon
              closable
              type={strategyNotice.type}
              style={{ marginTop: 12 }}
              message={strategyNotice.message}
              description={strategyNotice.description}
              onClose={() => setStrategyNotice(null)}
            />}
            {!strategyData ? <Empty description="选择证据后自动加载已有策略，或点「重新生成策略」创建新的方案" /> : strategyData.decision_status === "NEEDS_MORE_EVIDENCE" ? <Alert type="warning" showIcon
              message="证据不足，无法生成策略"
              description={strategyData.missing_evidence?.length > 0
                ? (strategyData.missing_evidence as any[]).slice(0,3).map((m:any)=>m.reason||m.category).join("；")
                : "当前证据的数据量或维度不足以支持策略生成，建议使用数据更丰富的证据。"}
            /> : <Space direction="vertical" size={12} style={{ width: "100%" }}>
              <Alert
                type="success"
                showIcon
                message={<Space><Tag color="green">{strategyDecisionStatusLabel(strategyData.decision_status)}</Tag><Tag>{strategyCapabilityLabel(strategyData.decision_capability)}</Tag><Text>共 {strategyData.strategy_options_count} 个策略版本</Text></Space>}
                description={currentStrategySummary(strategyData.candidates || [])}
              />
              {sortedStrategyCandidates.length > 1 && <Card size="small" style={{ background: "#fafafa" }}>
                <Space wrap>
                  <Text type="secondary">策略筛选</Text>
                  <Select
                    size="small"
                    style={{ minWidth: 260 }}
                    value={strategyCandidateFilter}
                    options={strategyFilterOptions}
                    onChange={(value) => setStrategyCandidateFilter(value)}
                  />
                  <Text type="secondary">当前显示 {visibleStrategyCandidates.length}/{sortedStrategyCandidates.length} 个版本；默认展示最新可审核策略。</Text>
                </Space>
              </Card>}
              {visibleStrategyCandidates.map((c:any)=>{
                const allCandidates = strategyData.candidates || [];
                const plan = experimentPlanPayload(c.experiment_plan);
                const strategyView = strategyDisplayPayload(c);
                const planPayload = plan.payload || strategyView.payload || c.structured_payload || {};
                const controlled = plan.controlled_intervention || {};
                const audit = plan.known_environment_audit || {};
                const isAccepted = c.review_status === "ACCEPTED" || c.review_status === "ACCEPTED_WITH_EDITS";
                const isCurrent = allCandidates[0]?.id === c.id;
                const isJustGenerated = latestGeneratedStrategyIds.includes(c.id);
                const updateCandidate = (next: any) => setStrategyData((prev: any) => prev ? {
                  ...prev,
                  candidates: (prev.candidates || []).map((item: any) => item.id === c.id ? { ...item, ...next } : item),
                } : prev);
                return <Card
                  key={c.id}
                  size="small"
                  title={<Space wrap>
                    <Tag color="geekblue">{strategyVersionLabel(c, allCandidates)}</Tag>
                    <Tag color="blue">策略 #{c.id}</Tag>
                    {isCurrent && <Tag color="cyan">当前优先</Tag>}
                    {isJustGenerated && <Tag color="green">本次生成</Tag>}
                    <Text strong>{interventionTypeLabel(strategyView.interventionType)}</Text>
                  </Space>}
                  extra={<Space wrap>
                    <Text type="secondary">生成 {formatDateTime(c.generated_at || c.created_at)}</Text>
                    <Text type="secondary">更新 {formatDateTime(c.updated_at || c.created_at)}</Text>
                    <Tag color={isAccepted?"green":c.review_status==="PENDING_REVIEW"?"default":"orange"}>{reviewStatusLabel(c.review_status)}</Tag>
                  </Space>}
                >
                {strategyView.decisionSpace && <Alert
                  type={strategyView.decisionSpace.worth_level === "WORTH_PURSUING" ? "success" : strategyView.decisionSpace.worth_level === "LOW_WORTH" ? "warning" : "info"}
                  showIcon
                  style={{ marginBottom: 12 }}
                  message={<Space wrap>
                    <Text strong>值不值得做：</Text>
                    <Tag color={strategyView.decisionSpace.worth_level === "WORTH_PURSUING" ? "green" : strategyView.decisionSpace.worth_level === "LOW_WORTH" ? "volcano" : "orange"}>
                      {strategyView.decisionSpace.worth_level === "WORTH_PURSUING" ? "值得投入" : strategyView.decisionSpace.worth_level === "LOW_WORTH" ? "收益有限" : "值得观察"}
                    </Tag>
                    <Tag>{strategyView.decisionSpace.has_choice_slot_label} {strategyView.decisionSpace.has_choice_slot}</Tag>
                    <Tag>{strategyView.decisionSpace.has_brand_mention_label} {strategyView.decisionSpace.has_brand_mention}</Tag>
                    <Tag>{strategyView.decisionSpace.has_explicit_recommendation_label} {strategyView.decisionSpace.has_explicit_recommendation}</Tag>
                    <Tag>{strategyView.decisionSpace.has_comparison_label} {strategyView.decisionSpace.has_comparison}</Tag>
                  </Space>}
                  description={strategyView.decisionSpace.worth_note}
                />}
                <Row gutter={[12,12]}>
                  <Col xs={24} md={8}>
                    <Card size="small" title="📊 证据事实" style={{background:"#f6ffed"}}>
                      <Text>{strategyView.evidenceSummary || "无"}</Text>
                      {c.structured_payload?.evidence_fact_ids?.length>0 && <div style={{marginTop:8}}><Text type="secondary">引用事实ID: {(c.structured_payload.evidence_fact_ids as string[]).join(", ")}</Text></div>}
                      {strategyView.decisionMarket?.primary_gap?.metric && <div style={{marginTop:8}}>
                        <Text type="secondary">主指标：{metricLabel(strategyView.decisionMarket.primary_gap.metric.metric)} · {strategyView.decisionMarket.primary_gap.metric.numerator}/{strategyView.decisionMarket.primary_gap.metric.denominator}</Text>
                      </div>}
                    </Card>
                  </Col>
                  <Col xs={24} md={8}>
                    <Card size="small" title="🔍 推断" style={{background:"#fff7e6"}}>
                      {(c.structured_payload?.inferences||[]).length>0
                        ? (c.structured_payload.inferences as any[]).map((inf:any)=><Alert key={inf.inference_id} type="warning" style={{marginBottom:4}} message={<Text>{inf.statement}</Text>} />)
                        : <Text type="secondary">基于当前证据推导的有限判断</Text>}
                      <div style={{marginTop:8}}><Text strong>推断原因：</Text><Text>{strategyView.cause || "-"}</Text></div>
                      {strategyView.mustAnswer.length > 0 && <div style={{marginTop:8}}>
                        <Text strong>审核前必须回答：</Text>
                        <ul style={{margin:"6px 0 0 18px", padding:0}}>
                          {strategyView.mustAnswer.slice(0, 4).map((item: string, index: number) => <li key={index}><Text>{item}</Text></li>)}
                        </ul>
                      </div>}
                    </Card>
                  </Col>
                  <Col xs={24} md={8}>
                    <Card size="small" title="🎯 策略建议" style={{background:"#e6f7ff"}}>
                      <Descriptions size="small" column={1} items={[
                        {key:"type",label:"干预类型",children:<Tag color={strategyView.interventionType==="UNRESOLVED"?"orange":"blue"}>{interventionTypeLabel(strategyView.interventionType)}</Tag>},
                        {key:"plat",label:"目标平台",children:<Tag color={strategyView.targetPlatform==="UNRESOLVED"?"orange":"blue"}>{platformLabel(strategyView.targetPlatform)}</Tag>},
                        {key:"ct",label:"内容类型",children:<Tag>{strategyContentTypeLabel(strategyView.targetContentType)}</Tag>},
                        {key:"fit",label:"证据匹配度 / 执行可行性",children:<Space><Tag>{c.structured_payload?.evidence_fit||"-"}</Tag><Tag>{c.structured_payload?.execution_feasibility||"未评估"}</Tag></Space>},
                      ]}/>
                      {c.structured_payload?.recommended_action && typeof c.structured_payload.recommended_action === "object"
                          ? <Space direction="vertical" size={4} style={{marginTop:8}}>
                            <Text strong>内容方向：</Text><Text>{(c.structured_payload.recommended_action as any).content_direction||"-"}</Text>
                            <Text strong>平台方向：</Text><Text>{(c.structured_payload.recommended_action as any).platform_direction||"-"}</Text>
                            {strategyView.platformRecommendations.length > 0 && <Space direction="vertical" size={6} style={{width:"100%"}}>
                              <Text strong>推荐平台组合：</Text>
                              {strategyView.platformRecommendations.map((item: any, index: number) => <Alert
                                key={`${item.platform || item.platform_label}-${index}`}
                                type="info"
                                showIcon
                                message={`${index + 1}. ${item.platform_label || platformLabel(item.platform)} · ${item.signal_level_label || "普通引用分布"} · ${(item.content_type_labels || []).join("、") || "内容待确认"}`}
                                description={<Space direction="vertical" size={2}>
                                  <Text>{item.recommended_action || "-"}</Text>
                                  <Text type="secondary">{item.evidence_basis || `引用覆盖 ${item.citation_run_count || 0} 个 Run`}</Text>
                                </Space>}
                              />)}
                            </Space>}
                            <Text strong>资产方向：</Text><Text>{(c.structured_payload.recommended_action as any).asset_direction||"-"}</Text>
                            {strategyView.metricAvailability && <Alert type="warning" showIcon message="指标边界" description={strategyView.metricAvailability} />}
                          </Space>
                        : <Space direction="vertical" size={6} style={{marginTop:8, width:"100%"}}>
                            <Text>{strategyView.actionText || "-"}</Text>
                            {strategyView.contentBrief.page_goal && <Alert type="info" showIcon message="内容目标" description={strategyView.contentBrief.page_goal} />}
                            {strategyView.metricAvailability && <Alert type="warning" showIcon message="指标边界" description={strategyView.metricAvailability} />}
                            {strategyView.requiredSections.length > 0 && <Text type="secondary">建议结构：{strategyView.requiredSections.join(" / ")}</Text>}
                            {strategyView.evidenceRequirements.length > 0 && <Text type="secondary">证据要求：{strategyView.evidenceRequirements.join("；")}</Text>}
                          </Space>}
                    </Card>
                  </Col>
                  <Col xs={24}>
                    <Card
                      size="small"
                      title="验证边界与实验计划"
                      style={{background:"#fff"}}
                      extra={<Space>
                        {!isAccepted && <Button size="small" loading={strategyLoading} onClick={async()=>{
                          setStrategyLoading(true);
                          try{
                            const reviewed = await api.reviewStrategyCandidate(c.id,{review_status:"ACCEPTED",reviewed_by:"human",review_note:"最终策略页人工接受"});
                            updateCandidate(reviewed);
                            message.success("策略已接受，可以生成实验计划");
                          }catch(e:any){message.error(e.message)}
                          finally{setStrategyLoading(false)}
                        }}>接受策略</Button>}
                        <Button type="primary" size="small" loading={strategyLoading} disabled={!isAccepted} onClick={async()=>{
                          setStrategyLoading(true);
                          try{
                            const generatedPlan = await api.strategyToExperimentPlan(c.id);
                            updateCandidate({
                              experiment_id: generatedPlan.experiment_id ?? c.experiment_id,
                              converted_hypothesis_id: generatedPlan.hypothesis_id ?? c.converted_hypothesis_id,
                              experiment_plan: generatedPlan.plan_payload || generatedPlan,
                            });
                            message.success("实验计划已生成");
                          }catch(e:any){message.error(e.message)}
                          finally{setStrategyLoading(false)}
                        }}>{isAccepted ? "生成实验计划" : "先接受后生成"}</Button>
                      </Space>}
                    >
                      <Descriptions size="small" column={{xs:1, md:2}} items={[
                        {key:"ready",label:"计划状态",children:<Tag color={readinessStatusColor(plan.readiness_status)}>{readinessStatusLabel(plan.readiness_status)}</Tag>},
                        {key:"experiment",label:"实验编号",children:plan.experiment_id || c.experiment_id ? <Tag color="blue">#{plan.experiment_id || c.experiment_id}</Tag> : <Text type="secondary">尚未生成</Text>},
                        {key:"metric",label:"主指标",children:<Text>{metricLabel(controlled.primary_metric || plan.target_metric || planPayload.target_metric || strategyView.targetMetric)}</Text>},
                        {key:"compare",label:"可比性边界",children:<Tag color={comparabilityStatusColor(plan.comparability_status)}>{comparabilityStatusLabel(plan.comparability_status)}</Tag>},
                        {key:"allowed",label:"允许改动",children:<Text>{listText(controlled.allowed_changes || planPayload.changed_features, "按策略中声明的同一机制内容改动")}</Text>},
                        {key:"forbidden",label:"禁止混改",children:<Text>{listText(controlled.forbidden_changes || planPayload.controlled_variables || c.original_llm_payload?.forbidden_changes, "不得同时改采集 Prompt、目标 URL、产品能力、外部平台投放等变量")}</Text>},
                      ]}/>
                      <Alert
                        type={plan.readiness_status === "BLOCKED" || strategyView.executionGate?.blocked_materialization ? "warning" : "info"}
                        showIcon
                        style={{marginTop:8}}
                        message={strategyView.executionGate?.blocked_materialization ? "待人工审核：当前只是 StrategyCandidate，不能直接生成 Action / Experiment。" : plan.comparability_note || "复采结论只能说明当前观察窗口内的变化，不能声称黑盒 AI 环境严格不变。"}
                        description={
                          <Space direction="vertical" size={2}>
                            <Text type="secondary">环境审计：模型版本变化 {audit.model_version_known_changed ? "是" : "否"}；引用格局变化 {audit.citation_landscape_changed ? "是" : "否"}；竞品来源变化 {audit.competitor_source_changed ? "是" : "否"}；品牌市场变化 {audit.brand_market_changed ? "是" : "否"}。</Text>
                            {strategyView.executionGate?.errors?.length > 0 && <Text type="danger">阻塞项：{strategyView.executionGate.errors.join("；")}</Text>}
                            {plan.readiness_errors?.length > 0 && <Text type="danger">阻塞项：{plan.readiness_errors.join("；")}</Text>}
                            {plan.readiness_warnings?.length > 0 && <Text type="secondary">提醒：{plan.readiness_warnings.join("；")}</Text>}
                          </Space>
                        }
                      />
                    </Card>
                  </Col>
                </Row>
              </Card>;
              })}
              <Button icon={<RefreshCw size={14}/>} loading={strategyLoading} onClick={regenerateStrategies}>重新生成</Button>
            </Space>}
          </Card>
          <Card title="实验闭环控制台" extra={<Space><Tag color="blue">VERIFY</Tag><Button size="small" loading={optimizationLoading} onClick={loadOptimizationIssues}>刷新草案</Button></Space>}>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message="这里承接最终策略后的真实验证闭环：确认问题、锁定基线、人工确认发布、固定复采、分析结果、人工结论。"
              description="系统不会自动宣称有效；只有发布、复采和人工结论都记录后，实验才算完成。"
            />
            <Row gutter={[12, 12]}>
              <Col xs={24} xl={9}>
                <Table
                  size="small"
                  rowKey="id"
                  loading={optimizationLoading}
                  pagination={{ pageSize: 8 }}
                  dataSource={optimizationIssues}
                  locale={{ emptyText: "暂无实验草案。可先在决策诊断页点击「送入最终策略」生成草案。" }}
                  columns={[
                    { title: "问题", dataIndex: "id", width: 70, render: (value) => <Tag>#{value}</Tag> },
                    { title: "状态", width: 90, render: (_, row: any) => <Tag>{issueStatusLabel(row.status)}</Tag> },
                    { title: "诊断", dataIndex: "diagnosis_summary", ellipsis: true },
                    { title: "操作", width: 80, render: (_, row: any) => <Button size="small" type={selectedOptimizationIssueId === row.id ? "primary" : "default"} onClick={() => loadOptimizationChain(row.id)}>查看</Button> },
                  ]}
                />
              </Col>
              <Col xs={24} xl={15}>
                {!optimizationChain
                  ? <Empty description="选择左侧问题后查看 Action / Experiment / Retest 链路" />
                  : <Space direction="vertical" size={12} style={{ width: "100%" }}>
                      <Descriptions size="small" bordered column={1}>
                        <Descriptions.Item label="问题">{optimizationChain.issue?.diagnosis_summary || "-"}</Descriptions.Item>
                        <Descriptions.Item label="状态"><Tag>{issueStatusLabel(optimizationChain.issue?.status)}</Tag></Descriptions.Item>
                        <Descriptions.Item label="证据采样">{(optimizationChain.issue?.run_ids || []).join("，") || "无"}</Descriptions.Item>
                      </Descriptions>
                      <Card size="small" title="行动记录">
                        {(optimizationChain.actions || []).length === 0
                          ? <Empty description="暂无行动记录" />
                          : <Table
                              size="small"
                              rowKey="id"
                              pagination={false}
                              dataSource={optimizationChain.actions || []}
                              columns={[
                                { title: "行动", dataIndex: "id", width: 70, render: (value) => <Tag>#{value}</Tag> },
                                { title: "状态", dataIndex: "status", width: 130, render: (value) => <Tag>{value === "draft" ? "草案" : value === "PLANNED" ? "已计划" : value === "READY_FOR_MANUAL_RELEASE" ? "待人工发布" : value === "RELEASE_CONFIRMED" ? "发布已确认" : value}</Tag> },
                                { title: "目标", dataIndex: "target_url", ellipsis: true },
                                { title: "摘要", dataIndex: "action_summary", ellipsis: true },
                              ]}
                            />}
                      </Card>
                      <Card size="small" title="实验记录">
                        {(optimizationChain.experiments || []).length === 0
                          ? <Empty description="暂无实验记录" />
                          : <Table
                              size="small"
                              rowKey="id"
                              pagination={false}
                              dataSource={optimizationChain.experiments || []}
                              columns={[
                                { title: "实验", dataIndex: "id", width: 70, render: (value) => <Tag>#{value}</Tag> },
                                { title: "状态", width: 110, render: (_, row: any) => <Tag>{experimentStatusLabel(row.status)}</Tag> },
                                { title: "主指标", width: 150, render: (_, row: any) => metricLabel(row.primary_metric) },
                                { title: "基线", width: 130, render: (_, row: any) => (row.baseline_run_ids || []).length ? <Tag color="green">{row.baseline_run_ids.length} 条</Tag> : <Tag>未锁定</Tag> },
                                { title: "复测", width: 130, render: (_, row: any) => (row.validation_run_ids || []).length ? <Tag color="blue">{row.validation_run_ids.length} 条</Tag> : <Tag>未挂载</Tag> },
                                { title: "可比性", width: 135, render: (_, row: any) => <Tag color={comparabilityStatusColor(row.comparability_status)}>{comparabilityStatusLabel(row.comparability_status)}</Tag> },
                                { title: "操作", width: 360, render: (_, row: any) => <Space size={4} wrap>
                                  <Button size="small" onClick={async () => {
                                    const runIds = optimizationChain.issue?.run_ids || [];
                                    if (!runIds.length) { message.warning("该问题没有可锁定的基线采样"); return; }
                                    await api.lockOptimizationBaseline(row.id, runIds);
                                    message.success("基线已锁定");
                                    await refreshOptimizationChain();
                                  }}>锁定基线</Button>
                                  <Button size="small" onClick={async () => {
                                    await api.queueOptimizationRetest(row.id, { sample_count: 3, execute_now: false });
                                    message.success("已创建固定复采队列");
                                    await refreshOptimizationChain();
                                  }}>排队复采</Button>
                                  <Button size="small" onClick={async () => {
                                    const input = window.prompt("请输入复采 Run ID，多个用逗号分隔");
                                    const runIds = (input || "").split(",").map((item) => Number(item.trim())).filter(Boolean);
                                    if (!runIds.length) return;
                                    await api.attachOptimizationValidationRuns(row.id, runIds);
                                    message.success("复采样本已挂载");
                                    await refreshOptimizationChain();
                                  }}>挂载复采</Button>
                                  <Button size="small" onClick={async () => {
                                    await api.analyzeOptimizationExperiment(row.id);
                                    message.success("实验分析已更新");
                                    await refreshOptimizationChain();
                                  }}>分析</Button>
                                  <Button size="small" type="primary" onClick={async () => {
                                    const reason = window.prompt("请输入人工结论说明");
                                    if (!reason) return;
                                    await api.confirmOptimizationConclusion(row.id, {
                                      conclusion: "INSUFFICIENT_EVIDENCE",
                                      conclusion_reason: reason,
                                      confounders: [],
                                      known_environment_audit: {},
                                      comparability_status: "INSUFFICIENT_CONTEXT",
                                      resolved: false,
                                    });
                                    message.success("人工结论已记录");
                                    await refreshOptimizationChain();
                                  }}>记录结论</Button>
                                </Space> },
                              ]}
                              expandable={{
                                expandedRowRender: (row: any) => <Space direction="vertical" size={6} style={{ width: "100%" }}>
                                  <Text type="secondary">假设：{row.hypothesis || "-"}</Text>
                                  <Text type="secondary">受控边界：{row.controlled_intervention?.boundary_note || "未记录"}</Text>
                                  <Text type="secondary">可比性说明：{row.comparability_note || "未记录"}</Text>
                                  {row.release_blocked && <Alert type="warning" showIcon message={`发布/复测被阻塞：${row.release_blocked_reason || "等待必要证据"}`} />}
                                </Space>
                              }}
                            />}
                      </Card>
                    </Space>}
              </Col>
            </Row>
          </Card>
        </Space> : page === "config" ? <Space direction="vertical" size={16} className="page-stack">
          <Alert
            type="info"
            showIcon
            message="管理人工智能搜索问题，按主题和问题簇组织"
            description="同一用户意图可以有多个变体问法，每次独立采集验证。"
          />
          <Row gutter={[16, 16]}>
            <Col xs={24} xl={8}>
              <Card title="新增问题" extra={<Plus size={17} />}>
                <Form form={promptForm} layout="vertical" onFinish={createPrompt} initialValues={{ importance: 3 }}>
                  <Form.Item name="topic" label="主题">
                    <Input placeholder="例如：二维码平台选择" />
                  </Form.Item>
                  <Form.Item name="prompt_group" label="问题组" rules={[{ required: true, message: "请输入问题组" }]}>
                    <Input placeholder="例如：企业选型" />
                  </Form.Item>
                  <Form.Item name="prompt_text" label="问题内容" rules={[{ required: true, message: "请输入问题" }]}>
                    <Input.TextArea rows={4} placeholder="例如：企业二维码平台哪一个好？" />
                  </Form.Item>
                  <Form.Item name="importance" label="重要度">
                    <InputNumber min={1} max={5} />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" loading={loading} icon={<Plus size={16} />}>创建问题</Button>
                </Form>
              </Card>
              <Card title="创建采集批次" style={{ marginTop: 16 }}>
                <Form form={auditForm} layout="vertical" onFinish={createAudit} initialValues={{
                  batch_name: `${new Date().toLocaleDateString("zh-CN")} 文心基线监测`,
                  collection_mode: "single_independent",
                  run_count: 3,
                  execute_now: true
                }}>
                  <Form.Item label="已选问题"><Text strong>{selectedPrompts.length}</Text><Text type="secondary"> 条</Text></Form.Item>
                  <Form.Item name="batch_name" label="采集批次名称" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                  <Form.Item name="collection_mode" label="采集模式" rules={[{ required: true }]}>
                    <Select options={[
                      { value: "single_independent", label: "每个 Prompt 独立新对话（推荐）" },
                      { value: "single_continuous", label: "同一对话连续采集（兼容模式）" }
                    ]} />
                  </Form.Item>
                  <Form.Item
                    name="run_count"
                    label="每个问题的采样次数"
                    extra="每次采样是一条独立采集记录；只代表当前验证样本，不表述为总体曝光概率。"
                    rules={[{ required: true }]}
                  >
                    <InputNumber min={1} max={10} />
                  </Form.Item>
                  <Form.Item name="execute_now" valuePropName="checked">
                    <label><input type="checkbox" style={{ marginRight: 8 }} />创建后立即执行</label>
                  </Form.Item>
                  <Space>
                    <Button type="primary" htmlType="submit" loading={loading} disabled={!selectedPrompts.length} icon={<Play size={16} />}>
                      创建并采集
                    </Button>
                    <Button loading={loading} disabled={!selectedPrompts.length} onClick={() => {
                      auditForm.setFieldsValue({ execute_now: false });
                      setTimeout(() => auditForm.submit(), 0);
                    }}>
                      仅加入队列
                    </Button>
                  </Space>
                </Form>
              </Card>
            </Col>
            <Col xs={24} xl={16}>
              <Card title="问题列表" extra={<Space><Tag>{prompts.length} 条</Tag>{selectedPrompts.length>0 && <Popconfirm title={`确定删除选中的 ${selectedPrompts.length} 个问题？`} onConfirm={async()=>{
                try{await api.batchDeletePrompts(projectId!,selectedPrompts.map(Number));message.success(`已删除`);setSelectedPrompts([]);loadProject(projectId!)}
                catch(e:any){message.error(e.message)}
              }}><Button danger size="small">批量删除 ({selectedPrompts.length})</Button></Popconfirm>}</Space>}>
                <Table
                  size="small"
                  rowKey="id"
                  pagination={{ pageSize: 10 }}
                  dataSource={[...prompts].sort((a, b) => `${a.topic_id}/${a.cluster_id}`.localeCompare(`${b.topic_id}/${b.cluster_id}`, "zh-CN"))}
                  rowSelection={{ selectedRowKeys: selectedPrompts, onChange: setSelectedPrompts }}
                  columns={[
                    { title: "主题", width: 120, render: (_, row) => <Tag color="geekblue">{topics.find((item) => item.id === row.topic_id)?.name || "未分类"}</Tag> },
                    { title: "问题组", width: 120, render: (_, row) => <Tag color="cyan">{clusters.find((item) => item.id === row.cluster_id)?.name || row.prompt_group || "-"}</Tag> },
                    { title: "问题内容", dataIndex: "prompt_text", ellipsis: true },
                    { title: "操作", width: 80, render: (_, row) => <Popconfirm title="确定删除？" onConfirm={async()=>{
                      try{await api.deletePrompt(projectId!,row.id);message.success("已删除");loadProject(projectId!)}
                      catch(e:any){message.error(e.message)}
                    }}><Button danger size="small">删除</Button></Popconfirm> }
                  ]}
                />
              </Card>
              <Card title="采集队列" style={{ marginTop: 16 }} extra={
                <Space>
                  {queue.latest_run_id ? <Tag>最新采集 #{queue.latest_run_id}</Tag> : null}
                  <Button
                    type="primary"
                    size="small"
                    icon={<Play size={14} />}
                    loading={loading}
                    disabled={queue.queued + queue.pending === 0}
                    onClick={async () => {
                      setLoading(true);
                      try {
                        const result = await api.executeQueuedRuns(projectId!);
                        message.success(`已执行 ${result.executed} 条采集记录`);
                        await loadProject(projectId!);
                      } catch (err: any) { message.error(err.message); }
                      finally { setLoading(false); }
                    }}
                  >
                    一键执行队列
                  </Button>
                </Space>
              }>
                <Row gutter={[12, 12]}>
                  <Col xs={8} md={4}><Statistic title="待采集" value={queue.queued + queue.pending} /></Col>
                  <Col xs={8} md={4}><Statistic title="运行中" value={queue.running} /></Col>
                  <Col xs={8} md={4}><Statistic title="成功" value={queue.success} /></Col>
                  <Col xs={8} md={4}><Statistic title="部分成功" value={queue.partial_success} /></Col>
                  <Col xs={8} md={4}><Statistic title="被拦截" value={queue.blocked} /></Col>
                  <Col xs={8} md={4}><Statistic title="失败" value={queue.failed} /></Col>
                  <Col xs={8} md={4}><Statistic title="总采集记录" value={queue.total} /></Col>
                </Row>
              </Card>
            </Col>
          </Row>
        </Space> : page === "ranking" ? <Space direction="vertical" size={16} className="page-stack">
          <Card title={<Space>引用资料分析<Tag color="blue">引用评分规则</Tag></Space>} extra={<Text type="secondary">证据 #{rankingData?.package_id} · 规则指纹 {rankingData?.scoring_spec_fingerprint?.slice(0,8)}</Text>}>
            <Alert type="info" showIcon style={{marginBottom:12}}
              message={<span><strong>引用资料分析</strong>展示当前证据内各域名/平台的相对引用信号强度。<strong>不代表</strong>平台有效性、成功概率或因果关系，分数仅在同一份证据内可比较。</span>}
            />
            <Space style={{marginBottom:12}}>
              <Button type="primary" loading={rankingLoading} onClick={()=>{
                setRankingLoading(true);
                api.getCitationRanking(7).then(data=>{setRankingData(data);message.success("已加载")}).catch(e=>{message.error(String(e.message||e))}).finally(()=>setRankingLoading(false));
              }}>加载排名数据</Button>
              {rankingData && <Button onClick={()=>setRankingData(null)}>清除</Button>}
            </Space>
            {!rankingData ? <Empty description="点击「加载排名数据」查看默认引用资料分析" /> : <Space direction="vertical" size={12}>
              <Row gutter={12}>
                <Col span={8}><Statistic title="引用总数" value={rankingData.total_references}/></Col>
                <Col span={8}><Statistic title="独立域名" value={rankingData.unique_domains}/></Col>
                <Col span={8}><Statistic title="独立链接" value={rankingData.unique_urls_global}/></Col>
              </Row>
              <Card size="small" title={<Space>域名排名<Tag>范围={rankingData.ranking_scope}</Tag></Space>}>
                <Table size="small" rowKey="source_domain" pagination={{pageSize:10}} dataSource={rankingData.domain_ranking||[]}
                  columns={[
                    {title:"排名",dataIndex:"evidence_rank_raw",width:55},
                    {title:"域名",dataIndex:"source_domain",width:170},
                    {title:"平台",width:90,render:(_:any,r:any)=><Tag>{r.inferred_platform}</Tag>},
                    {title:"分数",width:65,render:(_:any,r:any)=>(r.raw_evidence_score as number)?.toFixed(1)},
                    {title:"置信度",width:60,render:(_:any,r:any)=><Tag color={r.confidence==="HIGH"?"green":r.confidence==="MEDIUM"?"gold":"orange"}>{r.confidence_zh||r.confidence}</Tag>},
                    {title:"次数",dataIndex:"citation_occurrence_count",width:55},
                    {title:"独立URL",dataIndex:"unique_citation_urls",width:50},
                    {title:"Top1占比",width:55,render:(_:any,r:any)=>r.top1_url_share?Math.round((r.top1_url_share as number)*100)+"%":"-"},
                  ]}
                  expandable={{expandedRowRender:(row:any)=><Space direction="vertical" size={6}>
                    <Text strong>因子分解（总分：{row._decomposition?.total_score}）</Text>
                    {(Object.entries(row._decomposition||{})as[string,any][]).filter(([k])=>k!=="total_score").map(([fn,fd])=>(
                      <Card key={fn} size="small" title={<Space><Text strong>{fd.factor_name_zh||fn}</Text><Tag color={fd.factor_status==="ACTIVE"?"green":fd.factor_status==="DIAGNOSTIC_ONLY"?"gold":"default"}>{fd.factor_status_zh||fd.factor_status}</Tag></Space>}>
                        <Row gutter={[8,4]}>
                          <Col span={6}><Text type="secondary">配置权重: {((fd.configured_weight as number)*100).toFixed(0)}%</Text></Col>
                          <Col span={6}><Text type="secondary">实际权重: {((fd.active_weight as number)*100).toFixed(1)}%</Text></Col>
                          <Col span={6}><Text type="secondary">贡献: {(fd.weighted_contribution as number)?.toFixed(3)}</Text></Col>
                          <Col span={6}><Text>原始: {fd.raw_factor_score}</Text></Col>
                        </Row>
                        <Space wrap>{(fd.primary_dimensions_zh||fd.primary_dimensions||[])?.map((d:string)=><Tag key={d} color="blue">{d}</Tag>)}
                        {(fd.auxiliary_dimensions_zh||fd.auxiliary_dimensions||[])?.map((d:string)=><Tag key={d} color="gold">{d}</Tag>)}
                        {(fd.excluded_dimensions_zh||fd.excluded_dimensions||[])?.map((d:string)=><Tag key={d} color="default">{d}</Tag>)}</Space>
                        {fd.reason?<Alert type={fd.factor_status==="DIAGNOSTIC_ONLY"?"warning":"info"} style={{marginTop:4}} message={fd.reason}/>:null}
                      </Card>
                    ))}
                  </Space>}}
                />
              </Card>
              <Card size="small" title={<Space>平台排名<Tag color="gold">{rankingData.platform_ranking?.[0]?.platform_semantics_zh||"基于域名推断"}</Tag></Space>}>
                <Table size="small" rowKey="inferred_platform" pagination={false} dataSource={rankingData.platform_ranking||[]}
                  columns={[
                    {title:"排名",dataIndex:"platform_rank",width:55},
                    {title:"平台",dataIndex:"inferred_platform",width:100},
                    {title:"分数",width:65,render:(_:any,r:any)=>(r.avg_raw_evidence_score as number)?.toFixed(1)},
                    {title:"域名数",dataIndex:"domain_count",width:65},
                    {title:"引用次数",dataIndex:"total_citation_occurrences",width:90},
                  ]}
                  expandable={{expandedRowRender:(row:any)=><Space direction="vertical" size={4}>
                    <Text strong>构成域名</Text>
                    {(row.domains as string[])?.map((d:string)=><Tag key={d} color="blue">{d}</Tag>)}
                  </Space>}}
                />
              </Card>
              <Card size="small" title="已知局限">
                {(rankingData.known_limitations||[]).map((lim:any)=><Alert key={lim.code} type="warning" showIcon style={{marginBottom:6}}
                  message={<Space><Tag>{lim.code}</Tag><Text strong>{lim.title}</Text></Space>} description={lim.description}/>)}
              </Card>
              <Button icon={<RefreshCw size={14}/>} loading={rankingLoading} onClick={()=>{
                setRankingLoading(true);
                api.getCitationRanking(7).then(data=>{setRankingData(data);message.success("已刷新")}).catch(e=>{message.error(String(e.message||e))}).finally(()=>setRankingLoading(false));
              }}>刷新</Button>
            </Space>}
          </Card>
        </Space> : page === "golden" ? <Space direction="vertical" size={16} className="page-stack">
          <Card title="证据标注工作台" extra={<Space>
            <Select placeholder="选择问题" style={{width:220}} value={selectedPromptId} onChange={async(v)=>{
              setSelectedPromptId(v);
              setGoldenLoading(true);
              try{
                message.loading({content:"正在自动补齐主张、引用正文和段落对齐...",duration:0,key:"golden-prepare"});
                const prepared = await prepareGoldenCaseWorkspace(v);
                message.destroy("golden-prepare");
                if(prepared?.prepare?.manual_todos?.length){
                  message.warning("已自动补齐可自动处理项；如仍有空白，请先完成补录。");
                }else{
                  message.success("证据标注数据已自动补齐");
                }
              }catch(e:any){message.destroy("golden-prepare");message.error(e.message)}
              finally{setGoldenLoading(false)}
            }}
              options={[...new Map(runs.filter((r:any)=>r.status==="success"||r.status==="partial_success").map((r:any)=>[r.prompt_id,{id:r.prompt_id,text:r.original_query}])).values()].map((p:any)=>({label:`#${p.id} ${p.text}`,value:p.id}))}
            />
            <Tag color="orange">仅引用证据</Tag>
            <Button type="primary" loading={goldenLoading} disabled={!selectedPromptId} onClick={async()=>{
              if(!selectedPromptId)return;
              setGoldenLoading(true);
              try{
                message.loading({content:"正在重新自动补齐证据数据...",duration:0,key:"golden-refresh"});
                const prepared = await prepareGoldenCaseWorkspace(selectedPromptId);
                message.destroy("golden-refresh");
                if(prepared?.prepare?.manual_todos?.length){
                  message.warning("已自动补齐可自动处理项；如仍有空白，请先完成补录。");
                }else{
                  message.success("已重新自动补齐");
                }
              }catch(e:any){message.error(e.message)}
              finally{setGoldenLoading(false)}
            }}>自动补齐数据</Button>
          </Space>}>
            <Alert type="warning" showIcon style={{marginBottom:12}} message="当前问题的多次采样可能出现重复主张。各采集记录可独立审核，也可先审核代表性记录后批量应用。第三方平台抓取受限，候选来源与引用来源重叠偏低时，负样本不可用。" />
            {!goldenData ? <Empty description="点击「加载全部数据」开始" /> : <Space direction="vertical" size={12}>
              {(goldenData.prepare?.manual_todos || []).length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  message="已自动补齐可自动处理项；如仍有空白，请先完成补录。"
                />
              )}
              <Row gutter={12}>
                <Col span={4}><Statistic title="主张总数" value={goldenData.summary?.answer_claims}/></Col>
                <Col span={4}><Statistic title="已审核" value={goldenData.summary?.claims_reviewed||goldenData.needMap?.reviewed||0}/></Col>
                <Col span={4}><Statistic title="确认" value={goldenData.needMap?.confirmed||0}/></Col>
                <Col span={4}><Statistic title="修正" value={goldenData.needMap?.refined||0}/></Col>
                <Col span={4}><Statistic title="错误" value={goldenData.needMap?.mislabeled||0}/></Col>
                <Col span={4}><Statistic title="模糊" value={goldenData.needMap?.ambiguous||0}/></Col>
              </Row>
              {/* Source Documents + Manual Capture (merged) */}
              <Card size="small" title="引用资料" extra={<Space>
                {goldenData?.docs?.length < 5 && goldenData?.runIds && <Button size="small" type="primary" loading={goldenLoading} onClick={async()=>{
                  setGoldenLoading(true);
                  try{
                    const runIdList = (goldenData.runIds as string).split(",").map(Number);
                    message.loading({content:"正在使用浏览器抓取引用页面...",duration:0,key:"acquire"});
                    await fetch("/api/optimization/golden-case/acquire",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({run_ids:runIdList})});
                    message.destroy("acquire");
                    if(goldenData?.promptId){
                      const prepared = await prepareGoldenCaseWorkspace(goldenData.promptId, { skipAcquire: true });
                      message.success(`抓取完成，当前引用资料 ${prepared?.docs?.length || 0} 条`);
                    }
                  }catch(e:any){message.destroy("acquire");message.error(e.message)}
                  finally{setGoldenLoading(false)}
                }}>抓取引用资料</Button>}
                <Button size="small" onClick={async()=>{
                  try{setGoldenData({...goldenData, docs:await (await fetch(`/api/optimization/golden-case/documents?run_ids=${goldenData?.runIds||""}`)).json()})}
                  catch(e:any){message.error(e.message)}
                }}>刷新</Button>
              </Space>}>
                <Row gutter={12} style={{marginBottom:8}}>
                  <Col span={6}><Tag color="green">成功: {goldenData?.docs?.filter((d:any)=>d.fetch_status==="SUCCESS").length||0}</Tag></Col>
                  <Col span={6}><Tag color="gold">部分: {goldenData?.docs?.filter((d:any)=>d.fetch_status==="PARTIAL").length||0}</Tag></Col>
                  <Col span={6}><Tag color="blue">空页: {goldenData?.docs?.filter((d:any)=>d.fetch_status==="MANUAL_EMPTY").length||0}</Tag></Col>
                  <Col span={6}><Tag color="red">待补: {goldenData?.docs?.filter((d:any)=>!["SUCCESS","PARTIAL","MANUAL_EMPTY"].includes(d.fetch_status)).length||0}</Tag></Col>
                </Row>
                {goldenData.docs && <Table size="small" rowKey="id" pagination={{pageSize:8}} dataSource={goldenData.docs} columns={[
                  {title:"状态",width:70,render:(_,r:any)=><Tag color={r.fetch_status==="SUCCESS"?"green":r.fetch_status==="PARTIAL"?"gold":r.fetch_status==="MANUAL_EMPTY"?"blue":"red"}>{r.fetch_status==="SUCCESS"?"成功":r.fetch_status==="PARTIAL"?"部分":r.fetch_status==="MANUAL_EMPTY"?"空页":"失败"}</Tag>},
                  {title:"域名",dataIndex:"domain",width:100},
                  {title:"链接 / 标题",ellipsis:true,render:(_,r:any)=><a href={r.url} target="_blank" rel="noreferrer" style={{fontSize:12}}>{r.title||r.url}</a>},
                  {title:"字数",width:60,render:(_,r:any)=><Tag>{r.clean_text_len||0}</Tag>},
                  {title:"操作",width:120,render:(_,r:any)=><Space size={2}>
                    {r.fetch_status!=="SUCCESS"&&<Button size="small" onClick={()=>{
                      setManualUrl(r.url);
                      setManualEmptyPage(r.fetch_status==="MANUAL_EMPTY");
                    }}>{r.fetch_status==="MANUAL_EMPTY" ? "修改" : "补录"}</Button>}
                    {r.fetch_status==="FETCH_FAILED"&&<Button size="small" danger onClick={async()=>{
                      message.loading({content:"重新抓取中...",duration:0,key:"refetch"});
                      try{
                        await fetch("/api/optimization/golden-case/refetch",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({urls:[r.url]})});
                        message.destroy("refetch");
                        if(goldenData?.promptId){ await prepareGoldenCaseWorkspace(goldenData.promptId, { skipAcquire: true }); }
                        message.success("已重新抓取");
                      }catch(e:any){message.destroy("refetch");message.error(e.message)}
                    }}>重抓</Button>}
                  </Space>},
                ]} />}
                <Divider />
                <Input placeholder="页面链接" value={manualUrl} onChange={e=>setManualUrl(e.target.value)} style={{width:"100%",marginBottom:6}}/>
                <Checkbox checked={manualEmptyPage} onChange={e=>{
                  const checked = e.target.checked;
                  setManualEmptyPage(checked);
                  if(checked){
                    setManualText("");
                    setManualHtml("");
                  }
                }} style={{marginBottom:6}}>
                  空页面 / 页面已删除
                </Checkbox>
                <Input.TextArea value={manualText} disabled={manualEmptyPage} onChange={e=>setManualText(e.target.value)} rows={4} placeholder={manualEmptyPage ? "已标记为空页面，无需填写正文" : "粘贴正文..."} />
                <Input.TextArea value={manualHtml} disabled={manualEmptyPage} onChange={e=>setManualHtml(e.target.value)} rows={4} placeholder={manualEmptyPage ? "已标记为空页面，无需填写页面源码" : "或粘贴页面源码..."} style={{marginTop:6}}/>
                <Button type="primary" style={{marginTop:6}} onClick={async()=>{
                  if(!manualUrl){message.warning("请输入页面链接");return;}
                  if(!manualEmptyPage&&!manualText&&!manualHtml){message.warning("请输入正文或页面源码，或勾选空页面");return;}
                  const body:any={url:manualUrl,source_type:"CITED"};
                  if(manualEmptyPage)body.is_empty_page=true;
                  if(manualHtml)body.raw_html=manualHtml;
                  if(manualText)body.clean_text=manualText;
                  await fetch("/api/optimization/golden-case/documents/manual",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
                  message.success(manualEmptyPage ? "已标记为空页面" : "已录入");
                  setManualUrl("");setManualText("");setManualHtml("");setManualEmptyPage(false);
                  if(goldenData?.promptId){ await prepareGoldenCaseWorkspace(goldenData.promptId, { skipAcquire: true }); }
                }}>录入</Button>
              </Card>
              {/* Passage Alignments */}
              <Card size="small" title="回答主张 → 引用来源 → 原文段落对齐" extra={<Button size="small" onClick={async()=>{
                try{
                  if(goldenData?.promptId){
                    message.loading({content:"正在重新运行正文对齐...",duration:0,key:"golden-align"});
                    await prepareGoldenCaseWorkspace(goldenData.promptId, { skipAcquire: true });
                    message.destroy("golden-align");
                    message.success("正文对齐已刷新");
                  }
                }
                catch(e:any){message.error(e.message)}
              }}>重新自动对齐</Button>}>
                {goldenData.alignments ? <>
                  {goldenData.alignments.filter((a:any)=>a.alignment_level!=="L5_UNRESOLVED").length===0
                    ? <Alert type="warning" showIcon message="当前无有效对齐。AI回答与引用页面正文之间无直接文本重叠，需要人工辅助建立语义对齐。" />
                    : <Table size="small" rowKey="id" pagination={{pageSize:10}}
                        dataSource={goldenData.alignments.filter((a:any)=>a.alignment_level!=="L5_UNRESOLVED")}
                        columns={[
                          {title:"级别",width:60,render:(_:any,r:any)=><Tag color={r.alignment_level==="L1_EXACT_OVERLAP"?"green":"blue"}>{r.alignment_level==="L1_EXACT_OVERLAP"?"精确匹配":"近重复"}</Tag>},
                          {title:"回答主张",ellipsis:true,render:(_:any,r:any)=><Text style={{fontSize:12}}>{r.claim_text}</Text>},
                          {title:"引用来源",width:150,render:(_:any,r:any)=><a href={r.doc_url} target="_blank" style={{fontSize:11}}>{r.doc_title||r.doc_url}</a>},
                          {title:"证据",ellipsis:true,render:(_:any,r:any)=><Text type="secondary" style={{fontSize:11}}>{r.evidence}</Text>},
                        ]}
                      />}
                  <div style={{marginTop:8}}><Text type="secondary">
                    已对齐: {goldenData.alignments.filter((a:any)=>a.alignment_level!=="L5_UNRESOLVED").length} 条 /
                    未对齐: {goldenData.alignments.filter((a:any)=>a.alignment_level==="L5_UNRESOLVED").length} 条
                  </Text></div>
                </> : <Text type="secondary">系统会自动准备对齐数据；如果这里仍为空，请先完成补录。</Text>}
              </Card>
              {/* URL Audit */}
              {goldenData.urlAudit && <Card size="small" title="链接身份审计">
                <Descriptions size="small" bordered column={2}>
                  <Descriptions.Item label="原始链接重叠">{goldenData.urlAudit.raw?.overlap_rate}</Descriptions.Item>
                  <Descriptions.Item label="规范化后重叠">{goldenData.urlAudit.normalized?.overlap_rate}</Descriptions.Item>
                  <Descriptions.Item label="资格判定" span={2}><Tag color="orange">{goldenData.urlAudit.eligibility}</Tag> — {goldenData.urlAudit.note}</Descriptions.Item>
                </Descriptions>
              </Card>}
              {/* Answer Need Map */}
              {goldenData.needMap?.validated_needs && <Card size="small" title="智能回答信息需求图谱（人工验证后）">
                <Table size="small" rowKey="need_name" pagination={false} dataSource={goldenData.needMap.validated_needs||[]} columns={[
                  {title:"信息需求",dataIndex:"need_name",width:100},
                  {title:"规则次数",dataIndex:"rule_count",width:70},
                  {title:"人工确认",dataIndex:"human_count",width:70},
                  {title:"采样覆盖",dataIndex:"run_coverage",width:70},
                ]} />
              </Card>}
              {/* Atomic Claims Review */}
              <Card size="small" title="原子主张审核" extra={<Space>
                <Button size="small" type="primary" loading={goldenLoading} onClick={async()=>{
                  if(!goldenData?.runIds)return;
                  setGoldenLoading(true);
                  try{
                    await fetch("/api/optimization/golden-case/extract-atomic-claims",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({run_ids:goldenData.runIds.split(",").map(Number)})});
                    const acs=await(await fetch(`/api/optimization/golden-case/atomic-claims?run_ids=${goldenData.runIds}`)).json();
                    setGoldenData({...goldenData, atomicClaims:acs});
                    message.success(`已提取 ${acs.length} 条原子主张`);
                  }catch(e:any){message.error(e.message)}
                  finally{setGoldenLoading(false)}
                }}>提取原子主张</Button>
                <Button size="small" onClick={async()=>{
                  try{setGoldenData({...goldenData, atomicClaims:await(await fetch(`/api/optimization/golden-case/atomic-claims?run_ids=${goldenData?.runIds||""}`)).json()})}
                  catch(e:any){message.error(e.message)}
                }}>加载已有</Button>
              </Space>}>
                {goldenData.atomicClaims ? <>
                  <Row gutter={12} style={{marginBottom:8}}>
                    <Col span={6}><Tag>总数: {goldenData.atomicClaims.length}</Tag></Col>
                    <Col span={6}><Tag color="green">已确认: {goldenData.atomicClaims.filter((c:any)=>c.review_status==="CONFIRMED").length}</Tag></Col>
                    <Col span={6}><Tag color="blue">已编辑: {goldenData.atomicClaims.filter((c:any)=>c.review_status==="EDITED").length}</Tag></Col>
                    <Col span={6}><Tag color="red">已拒绝: {goldenData.atomicClaims.filter((c:any)=>c.review_status==="REJECTED").length}</Tag></Col>
                  </Row>
                  <Table size="small" rowKey="id" pagination={{pageSize:20}}
                    dataSource={goldenData.atomicClaims}
                    columns={[
                      {title:"主张",ellipsis:true,render:(_:any,r:any)=><Text style={{fontSize:12}}>{r.claim_text}</Text>},
                      {title:"类型",width:80,render:(_:any,r:any)=><Space size={2}>{(r.claim_types||[]).slice(0,2).map((t:string)=><Tag key={t} color="blue" style={{fontSize:10}}>{claimTypeLabel(t)}</Tag>)}</Space>},
                      {title:"语义",width:65,render:(_:any,r:any)=><Tag style={{fontSize:10}}>{speechActLabel(r.speech_act)}</Tag>},
                      {title:"极性",width:55,render:(_:any,r:any)=><Tag color={r.polarity==="POSITIVE"?"green":"red"} style={{fontSize:10}}>{r.polarity==="POSITIVE"?"正面":"负面"}</Tag>},
                      {title:"优化价值",width:70,render:(_:any,r:any)=><Tag color={r.geo_importance==="HIGH"?"red":"default"} style={{fontSize:10}}>{r.geo_importance==="HIGH"?"高":"低"}</Tag>},
                      {title:"状态",width:65,render:(_:any,r:any)=><Tag color={r.review_status==="CONFIRMED"?"green":r.review_status==="EDITED"?"blue":"default"} style={{fontSize:10}}>{r.review_status==="CONFIRMED"?"已确认":r.review_status==="EDITED"?"已编辑":r.review_status==="REJECTED"?"已拒绝":"待审"}</Tag>},
                      {title:"操作",width:120,render:(_:any,r:any)=><Space size={1}>
                        <Button size="small" onClick={async()=>{await fetch(`/api/optimization/golden-case/atomic-claims/${r.id}/review`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({review_status:"CONFIRMED",reviewer:"human"})});message.success("已确认");setGoldenData({...goldenData,atomicClaims:goldenData.atomicClaims.map((c:any)=>c.id===r.id?{...c,review_status:"CONFIRMED"}:c)});}}>确认</Button>
                        <Button size="small" danger onClick={async()=>{await fetch(`/api/optimization/golden-case/atomic-claims/${r.id}/review`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({review_status:"REJECTED",reviewer:"human"})});message.success("已拒绝");setGoldenData({...goldenData,atomicClaims:goldenData.atomicClaims.map((c:any)=>c.id===r.id?{...c,review_status:"REJECTED"}:c)});}}>拒绝</Button>
                      </Space>},
                    ]}
                  />
                </> : <Text type="secondary">点击「提取原子主张」运行第一版规则提取器，或「加载已有」查看之前结果</Text>}
              </Card>
              {/* Claims Review Table */}
              <Card size="small" title="回答主张审核">
                <Table size="small" rowKey="id" pagination={{pageSize:15}}
                  dataSource={(goldenData.claims||[]).slice(0,60)}
                  columns={[
                    {title:"采集",dataIndex:"run_id",width:50},
                    {title:"#",dataIndex:"claim_index",width:35},
                    {title:"内容",dataIndex:"raw_text",ellipsis:true,render:(v:string)=><Text style={{fontSize:12}}>{v}</Text>},
                    {title:"分类",width:75,render:(_,r:any)=><Tag>{claimTypeLabel(r.claim_type)}</Tag>},
                    {title:"审核",width:70,render:(_,r:any)=><Tag color={r.review_status==="CONFIRMED"?"green":r.review_status==="REFINED"?"blue":r.review_status==="MISLABELED"?"red":r.review_status==="AMBIGUOUS"?"orange":"default"}>{r.review_status==="CONFIRMED"?"已确认":r.review_status==="REFINED"?"已修正":r.review_status==="MISLABELED"?"分类错误":r.review_status==="AMBIGUOUS"?"存在歧义":"待审核"}</Tag>},
                    {title:"操作",width:120,render:(_,r:any)=><Space size={1}>
                      <Button size="small" onClick={async()=>{
                        await fetch(`/api/optimization/golden-case/claims/${r.id}/review`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({review_status:"CONFIRMED",human_labels:[r.claim_type],reviewer:"human"})});
                        message.success("已确认");
                        setGoldenData({...goldenData,claims:goldenData.claims.map((c:any)=>c.id===r.id?{...c,review_status:"CONFIRMED"}:c)});
                      }}>确认</Button>
                      <Button size="small" danger onClick={async()=>{
                        await fetch(`/api/optimization/golden-case/claims/${r.id}/review`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({review_status:"MISLABELED",human_labels:[],reviewer:"human"})});
                        message.success("已标记错误");
                        setGoldenData({...goldenData,claims:goldenData.claims.map((c:any)=>c.id===r.id?{...c,review_status:"MISLABELED"}:c)});
                      }}>错误</Button>
                    </Space>},
                  ]}
                />
              </Card>
              <Alert type="info" showIcon message={<span><strong>当前状态</strong>：规则分类结果仍需人工验证。引用正文证据和段落对齐需要按当前问题继续补齐；策略继续保持暂缓决策，待段落证据与品牌页面证据补齐后重新评估。</span>} />
            </Space>}
          </Card>
        </Space> : <Card title="采集记录" extra={<Tag>每行是一次独立采样</Tag>}>
          <Table rowKey="id" loading={loading} dataSource={runs} pagination={{ pageSize: 12 }} onRow={(row) => ({ onClick: () => openRun(row.id) })} columns={[
            { title: "编号", dataIndex: "id", width: 70, render: (id) => `#${id}` },
            { title: "采集时间", width: 150, render: (_, row: any) => formatDateTime(row.finished_at || row.started_at || row.created_at) },
            { title: "问题", dataIndex: "original_query", ellipsis: true },
            { title: "状态", dataIndex: "status", width: 100, render: statusTag },
            { title: "样本", dataIndex: "run_sequence", width: 70, render: (value) => `第${value}次` },
            { title: "品牌", width: 110, render: (_, row) => row.brand_mentioned ? <Tag color="blue">出现 {row.brand_mention_count} 次</Tag> : <Tag>未出现</Tag> },
            { title: "引用解析", width: 230, render: (_, row) => <Space size={4}><Tag>界面 {row.expected_reference_count}</Tag><Tag>结构 {row.detected_reference_count}</Tag><Tag>标题 {row.detected_reference_count}</Tag><Tag color={row.resolved_reference_count === row.detected_reference_count ? "green" : "gold"}>链接 {row.resolved_reference_count}</Tag></Space> },
            { title: "操作", width: 170, render: (_, row) => <Space size={4}>
              <Button size="small" onClick={(event) => { event.stopPropagation(); openRun(row.id); }}>查看</Button>
              {row.status === "failed" && (
                <Button size="small" type="primary" ghost danger icon={<RefreshCw size={12} />} loading={retryingRuns.has(row.id)} onClick={(event) => { event.stopPropagation(); retryRun(row.id); }}>重新采集</Button>
              )}
            </Space> }
          ]} />
        </Card>}
      </Content>
    </Layout>
    <Modal
      title="人工审核工作台"
      open={workflowReviewOpen}
      onCancel={()=>{setWorkflowReviewOpen(false);setReviewQueue(null);setCompetitorCandidates([]);}}
      footer={null}
      width={820}
    >
      <Space direction="vertical" size={12} style={{width:"100%"}}>
        <Alert type="info" showIcon message="机器分析已完成，请逐项人工确认。相同答案只审核一次，确认后自动应用到全部 Run。" />
        {!reviewQueue && <Button type="primary" loading={loading} onClick={async()=>{
          setLoading(true);
          try{
            const [q, cc] = await Promise.all([
              (await fetch(`/api/optimization/workflow/${projectId}/${workflowData?.prompt_id}/review-queue`)).json(),
              (await fetch(`/api/optimization/workflow/${projectId}/${workflowData?.prompt_id}/competitor-candidates`)).json(),
            ]);
            setReviewQueue(q); setCompetitorCandidates(cc);
          }catch(e:any){message.error(e.message)}
          finally{setLoading(false)}
        }}>加载待审核项</Button>}
        {reviewQueue && <Space direction="vertical" size={12} style={{width:"100%"}}>
          {/* 竞品候选确认 */}
          {competitorCandidates.length>0 && <Card size="small" title={<Space><Tag color="volcano">待确认竞品</Tag><Text>发现 {competitorCandidates.length} 个潜在竞品</Text></Space>}>
            {competitorCandidates.map((c:any)=><Row key={c.entity} align="middle" style={{marginBottom:8}}>
              <Col span={16}><Space direction="vertical" size={0}>
                <Text strong>{c.entity}</Text>
                <Text type="secondary" style={{fontSize:12}}>出现于 {c.run_coverage} Runs · {c.speech_acts.join("/")}</Text>
                <Text type="secondary" style={{fontSize:12}}>原文：{c.answer_span?.slice(0,80)}</Text>
              </Space></Col>
              <Col span={8}><Space>
                <Button size="small" type="primary" onClick={async()=>{
                  await fetch(`/api/optimization/workflow/${projectId}/competitor-candidates/confirm`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:c.entity})});
                  message.success(`已确认竞品：${c.entity}`);
                  setCompetitorCandidates(competitorCandidates.filter((x:any)=>x.entity!==c.entity));
                }}>确认竞品</Button>
                <Button size="small" onClick={()=>setCompetitorCandidates(competitorCandidates.filter((x:any)=>x.entity!==c.entity))}>不是</Button>
              </Space></Col>
            </Row>)}
          </Card>}
          {/* 推荐事件审核（一屏一判断） */}
          {reviewQueue.unique_events.map((e:any, idx:number)=><Card key={`ev-${idx}`} size="small" title={<Space><Tag color="blue">AI 说法校验 {idx+1}/{reviewQueue.unique_events.length}</Tag><Tag>{e.run_count} 个 Runs 相同答案</Tag></Space>}>
            <Alert type="warning" showIcon style={{marginBottom:8}} message="这里校验的是「AI 是否真的这样说了」，不是竞品能力的真实性——竞品能力真假不影响本品牌的干预决策。" />
            <Text>机器判断：AI 把 <strong>{e.entity_text}</strong> <Tag>{e.speech_act==="INCLUDE_AS_OPTION"?"纳入方案候选":e.speech_act}</Tag>（{e.recommendation_strength}）</Text>
            <Alert type="info" style={{marginTop:8}} message={`原答案："${e.answer_span}"`} />
            <Text type="secondary" style={{display:"block",marginTop:4}}>AI 给出的理由（仅参考，无需校验其能力真假）：</Text>
            {(e.reasons||[]).map((r:any,ri:number)=><Text key={ri} type="secondary" style={{display:"block",marginTop:2}}>理由{ri+1}：{r.normalized_reason}</Text>)}
            <Space style={{marginTop:8}}>
              <Button size="small" type="primary" onClick={async()=>{
                await fetch("/api/optimization/workflow/review/events/confirm-batch",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({event_ids:e.event_ids})});
                message.success("已确认 AI 说法无误");
                setReviewQueue({...reviewQueue, unique_events: reviewQueue.unique_events.filter((x:any)=>x!==e)});
              }}>AI 确实这样说了</Button>
              <Button size="small" onClick={async()=>{
                await fetch("/api/optimization/workflow/review/events/reject-batch",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({event_ids:e.event_ids})});
                message.success("已标记错误");
                setReviewQueue({...reviewQueue, unique_events: reviewQueue.unique_events.filter((x:any)=>x!==e)});
              }}>判断有误</Button>
            </Space>
          </Card>)}
          {/* Evidence 对齐审核 */}
          {reviewQueue.alignments.map((a:any, idx:number)=><Card key={`al-${idx}`} size="small" title={<Tag color="purple">证据语义关系校验 {idx+1}/{reviewQueue.alignments.length}</Tag>}>
            <Alert type="warning" showIcon style={{marginBottom:8}} message="这里校验的是「来源原文是否真的支持这条 AI 理由」的语义关系，不判断竞品能力真伪。竞品证据只用于建立市场标准基线。" />
            <Text strong>AI 选择理由：</Text><Text>{a.reason_text}</Text>
            <Divider style={{margin:6}}/>
            <Text strong>来源原文：</Text><Alert type="info" message={a.claim_span || a.claim_text} style={{marginTop:4}}/>
            <Text type="secondary" style={{display:"block",marginTop:4}}>机器判断：<Tag color={a.relation==="SUPPORTS"?"green":"gold"}>{a.relation}</Tag></Text>
            <Space style={{marginTop:8}}>
              <Button size="small" type="primary" onClick={async()=>{
                await fetch(`/api/optimization/workflow/review/alignments/${a.alignment_id}/confirm`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({relation:"SUPPORTS"})});
                message.success("已确认 SUPPORTS");
                setReviewQueue({...reviewQueue, alignments: reviewQueue.alignments.filter((x:any)=>x.alignment_id!==a.alignment_id)});
              }}>确认 SUPPORTS</Button>
              <Button size="small" onClick={async()=>{
                await fetch(`/api/optimization/workflow/review/alignments/${a.alignment_id}/confirm`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({relation:"RELATED"})});
                message.success("已改为 RELATED");
                setReviewQueue({...reviewQueue, alignments: reviewQueue.alignments.filter((x:any)=>x.alignment_id!==a.alignment_id)});
              }}>改为 RELATED</Button>
              <Button size="small" onClick={async()=>{
                await fetch(`/api/optimization/workflow/review/alignments/${a.alignment_id}/confirm`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({relation:"NONE"})});
                message.success("已改为 NONE");
                setReviewQueue({...reviewQueue, alignments: reviewQueue.alignments.filter((x:any)=>x.alignment_id!==a.alignment_id)});
              }}>NONE</Button>
            </Space>
          </Card>)}
          {reviewQueue.unique_events.length===0 && reviewQueue.alignments.length===0 && <Alert type="success" showIcon message="全部审核完成！关闭窗口后点「继续分析」生成 Gap 与 Action。" />}
        </Space>}
      </Space>
    </Modal>
    <Modal
      title={editingProjectId ? "编辑项目" : "新建项目"}
      open={projectModalOpen}
      onCancel={() => { setProjectModalOpen(false); setEditingProjectId(null); }}
      footer={null}
      width={640}
      destroyOnClose
    >
      <Form form={projectForm} layout="vertical" onFinish={submitProject} initialValues={{ region: "CN", language: "zh-CN" }}>
        <Form.Item name="name" label="项目名称" rules={[{ required: true, message: "请输入项目名称" }]}>
          <Input placeholder="例如：八木屋二维码生成式搜索监测" />
        </Form.Item>
        <Form.Item name="brand_name" label="品牌名称" rules={[{ required: true, message: "请输入品牌名称" }]}>
          <Input placeholder="例如：八木屋" />
        </Form.Item>
        <Form.Item name="brand_aliases" label="品牌别名（逗号分隔）">
          <Input placeholder="例如：八木屋二维码, Bamuwu" />
        </Form.Item>
        <Form.Item name="website_url" label="品牌官网">
          <Input placeholder="https://www.bamuwu.com" />
        </Form.Item>
        <Form.Item name="industry" label="行业">
          <Input placeholder="例如：二维码/企业服务" />
        </Form.Item>
        <Row gutter={12}>
          <Col span={12}><Form.Item name="region" label="地区"><Input placeholder="CN" /></Form.Item></Col>
          <Col span={12}><Form.Item name="language" label="语言"><Input placeholder="zh-CN" /></Form.Item></Col>
        </Row>
        <Form.Item
          name="competitors"
          label="竞品（每行一个，格式：名称:别名1;别名2:官网URL）"
          extra="示例：草料二维码:草料;cli.im:https://cli.im"
        >
          <Input.TextArea rows={5} placeholder="草料二维码:草料;cli.im:https://cli.im&#10;二维斑马:二维斑马二维码:&#10;微微二维码::" />
        </Form.Item>
        <Space style={{ justifyContent: "flex-end", width: "100%" }}>
          {editingProjectId && (
            <Popconfirm title="确定删除该项目？所有数据将丢失" onConfirm={deleteCurrentProject} okText="确定删除" cancelText="取消">
              <Button danger>删除项目</Button>
            </Popconfirm>
          )}
          <Button onClick={() => { setProjectModalOpen(false); setEditingProjectId(null); }}>取消</Button>
          <Button type="primary" htmlType="submit">{editingProjectId ? "保存" : "创建"}</Button>
        </Space>
      </Form>
    </Modal>
    <Drawer width={760} open={Boolean(detail)} onClose={() => { setDetail(undefined); setArtifact(undefined); }} title={detail ? `采样详情 #${detail.id}` : ""}>
      {detail && <Space direction="vertical" className="page-stack" size={16}>
        <Descriptions bordered size="small" column={2} items={[
          { key: "status", label: "状态", children: statusTag(detail.status) },
          { key: "sample", label: "轮次", children: detail.run_sequence },
          { key: "duration", label: "耗时", children: `${detail.duration_ms} ms` },
          { key: "brand", label: "品牌", children: detail.brand_mentioned ? `出现 ${detail.brand_mention_count} 次` : "未出现" }
        ]} />
        <Card size="small" title="四层引用计数">
          <Row gutter={12}><Col span={6}><Statistic title="界面声明" value={detail.expected_reference_count} /></Col><Col span={6}><Statistic title="页面结构条目" value={detail.detected_reference_count} /></Col><Col span={6}><Statistic title="解析标题" value={detail.references.filter((r) => r.display_title).length} /></Col><Col span={6}><Statistic title="解析链接" value={detail.resolved_reference_count} /></Col></Row>
        </Card>
        <Card size="small" title="原始问题"><Text>{detail.original_query}</Text></Card>
        <Card size="small" title="回答正文"><pre className="content-preview">{detail.answer_text || "无回答正文"}</pre></Card>
        <Card size="small" title="引用详情"><Table size="small" rowKey="id" pagination={{ pageSize: 8 }} dataSource={detail.references} columns={[
          { title: "#", dataIndex: "reference_index", width: 50 }, { title: "标题", dataIndex: "display_title" },
          { title: "域名", dataIndex: "domain", width: 150 }, { title: "链接", width: 70, render: (_, row) => row.url ? <Link href={row.url} target="_blank"><ExternalLink size={15} /></Link> : <Tag color="gold">未解析</Tag> }
        ]} /></Card>
        <Card size="small" title="证据"><Table size="small" rowKey="id" pagination={false} dataSource={detail.artifacts} columns={[
          { title: "证据类型", dataIndex: "artifact_type", render: (value) => <Space><FileText size={15} />{value}</Space> },
          { title: "文件", dataIndex: "storage_path", ellipsis: true }, { title: "大小", dataIndex: "size_bytes", width: 100 },
          { title: "操作", width: 90, render: (_, row) => <Button size="small" disabled={(row.mime_type || "").startsWith("image/")} onClick={() => openArtifact(row.id)}>预览</Button> }
        ]} /></Card>
        {artifact && <Card size="small" title={`证据预览 · ${artifact.artifact_type}`} extra={artifact.truncated ? <Tag color="gold">已截断</Tag> : <Tag color="green">完整</Tag>}><pre className="artifact-preview">{artifact.content}</pre></Card>}
      </Space>}
    </Drawer>
  </Layout>;
}
