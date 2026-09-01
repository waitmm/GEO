import { useEffect, useMemo, useRef, useState } from "react";
import type { Key } from "react";
import {
  Alert, Button, Card, Checkbox, Col, Descriptions, Divider, Drawer, Empty, Form, Input, InputNumber,
  Layout, Menu, Modal, Popconfirm, Progress, Row, Select, Space, Statistic, Steps, Table, Tag, Timeline, Typography, message
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
  optimization: { title: "执行策略", subtitle: "知道为什么以后，具体怎么干" },
  config: { title: "问题配置", subtitle: "维护问题、主题、采样计划和项目基础信息" },
  runs: { title: "采集记录", subtitle: "查看每次采集、原答案、引用和检索候选" },
  ranking: { title: "引用资料", subtitle: "以最终引用资料为主分析来源结构和页面价值" },
  golden: { title: "证据标注", subtitle: "底层 claim、引用片段、证据对齐与人工标注" },
};

const CURRENT_CITATION_DECISION_USE_ANSWER_BINDING_V1_1 = true;

const emptyQueue: BrowserQueueSummary = {
  project_id: null, queued: 0, pending: 0, running: 0, success: 0,
  partial_success: 0, failed: 0, blocked: 0, total: 0, latest_run_id: null,
  latest_status: "", latest_stage: "", latest_error_type: ""
};

const CHANNEL_BUTTONS: [string, string][] = [
  ["OWNED_NEW_PAGE", "官网新建教程页"], ["OWNED_UPDATE", "官网更新现有页"],
  ["ZHIHU", "知乎"], ["BAIJIAHAO", "百家号"], ["BILIBILI", "B站视频"], ["DOUYIN", "抖音"],
];

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

function displaySourceUrl(url?: string, canonicalUrl?: string) {
  const raw = String(canonicalUrl || url || "").trim();
  if (!raw) return "";
  return raw.replace(/^([a-z][a-z0-9+.-]*:\/\/)?www\./i, "$1");
}

function sourceActionUrl(url?: string, canonicalUrl?: string, actionUrl?: string) {
  return displaySourceUrl(actionUrl || canonicalUrl || url);
}

function displaySourceDomain(domain?: string, url?: string, canonicalUrl?: string) {
  const raw = String(domain || canonicalUrl || url || "").trim();
  if (!raw) return "";
  const withoutScheme = raw.replace(/^[a-z][a-z0-9+.-]*:\/\//i, "");
  const host = withoutScheme.split(/[/?#]/)[0];
  return host.replace(/^www\./i, "");
}

function sourceFailureSummary(row: any) {
  return row?.content_status_reason || row?.failure_summary || row?.failure_reason || "";
}

function citationDecisionBelongsToPrompt(data: any, promptId?: number | null) {
  if (!data || !promptId) return false;
  const identity = data.context_identity || data;
  return Number(identity.prompt_id) === Number(promptId);
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
    MACHINE_GROUNDED: "机器待确认",
    MACHINE_CANDIDATE: "机器候选",
    HUMAN_CONFIRMED: "人工已确认",
    HUMAN_REJECTED: "人工已拒绝",
    VALIDATION_FAILED: "机器校验未通过",
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

function semanticRelationLabel(status?: string) {
  const labels: Record<string, string> = {
    SUPPORTS: "支持",
    PARTIAL_SUPPORT: "部分支持",
    CONTRADICTS: "矛盾",
    NO_SUPPORT: "不支持",
    RELATED: "历史相关",
    NONE: "无支持",
  };
  return labels[status || ""] || status || "未判断";
}

function decisionEntityRelationshipLabel(status?: string) {
  const labels: Record<string, string> = {
    TARGET: "目标品牌",
    TARGET_BRAND: "目标品牌",
    CONFIRMED_COMPETITOR: "已确认竞品",
    UNKNOWN_ENTITY: "待确认对象",
  };
  return labels[status || ""] || status || "待确认对象";
}

function decisionEntityRelationshipColor(status?: string) {
  const colors: Record<string, string> = {
    TARGET: "blue",
    TARGET_BRAND: "blue",
    CONFIRMED_COMPETITOR: "volcano",
    UNKNOWN_ENTITY: "gold",
  };
  return colors[status || ""] || "default";
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

function citationDecisionStatusLabel(status?: string) {
  const labels: Record<string, string> = {
    READY_FOR_HUMAN_CONFIRM: "可人工确认",
    NO_EXECUTABLE_RECOMMENDATION: "暂无可执行动作",
  };
  return labels[status || ""] || status || "未加载";
}

function decisionSupportLabel(value?: string) {
  const labels: Record<string, string> = {
    RECOMMENDATION_REASON: "推荐理由支撑",
    CANDIDATE_OR_EVALUATION: "候选/评价支撑",
    FACT_ONLY: "事实信息",
    NONE: "未形成决策支撑",
  };
  return labels[value || ""] || value || "-";
}

function benchmarkTierLabel(value?: string) {
  const labels: Record<string, string> = {
    PRIMARY_BENCHMARK: "核心对标",
    SECONDARY_BENCHMARK: "辅助对标",
    REFERENCE_ONLY: "仅引用参考",
    NOT_EVALUABLE: "不可评估",
  };
  return labels[value || ""] || value || "-";
}

function gapPreconditionLabel(value?: string) {
  const labels: Record<string, string> = {
    READY: "可分析",
    NO_ELIGIBLE_BENCHMARK: "未进入缺口分析",
    PRODUCT_TRUTH_UNKNOWN: "产品事实未匹配/未确认",
    BRAND_ASSET_INCOMPLETE: "品牌资产不完整",
    BENCHMARK_EVIDENCE_INSUFFICIENT: "对标证据不足",
  };
  return labels[value || ""] || value || "-";
}

function sourceGapLabel(value?: string | null) {
  const labels: Record<string, string> = {
    CONTENT_GAP: "内容缺口",
    EVIDENCE_GAP: "证据缺口",
    PRODUCT_GAP: "产品缺口",
    NO_GAP: "暂无缺口",
    UNKNOWN: "已进入分析但无法判断",
  };
  return value ? labels[value] || value : "未进入缺口分析";
}

function priorityLevelLabel(value?: string | null) {
  const labels: Record<string, string> = {
    PRIORITY_HIGH: "高优先级",
    PRIORITY_MEDIUM: "中优先级",
    NOT_PRIORITY: "非优先",
    UNRESOLVED: "待人工补充",
  };
  return value ? labels[value] || value : "不进入队列";
}

function actionRouteLabel(value?: string | null) {
  const labels: Record<string, string> = {
    CONTENT: "内容动作",
    EVIDENCE: "证据动作",
    PRODUCT: "产品评估",
    NO_ACTION: "无需动作",
    UNRESOLVED: "待人工补充",
  };
  return value ? labels[value] || value : "不生成动作";
}

function contentStatusLabel(value?: string) {
  const labels: Record<string, string> = {
    CONTENT_VALID: "正文可用",
    CONTENT_UNAVAILABLE: "正文不可用",
    CONTENT_EMPTY: "空正文",
    CONTENT_PENDING: "待补正文",
  };
  return labels[value || ""] || value || "-";
}

function citationProminenceLabel(value?: string | null) {
  const labels: Record<string, string> = {
    HIGH: "高",
    MEDIUM: "中",
    LOW: "低",
  };
  return value ? labels[value] || value : "-";
}

function decisionStabilityLevelColor(value?: string | null) {
  if (value === "HIGH_STABILITY") return "green";
  if (value === "MIXED") return "gold";
  if (value === "HIGH_VOLATILITY") return "red";
  return "default";
}

function dominantOutcomeText(outcome?: any) {
  if (!outcome) return "暂无";
  if (outcome.outcome_type === "CO_DOMINANT_RECOMMENDATION_ENTITIES") {
    const count = outcome.co_dominant_count || outcome.co_dominant_entities?.length || 0;
    return `${count} 个并列，均为 ${outcome.run_count || 0}/${outcome.denominator || 0}`;
  }
  if (outcome.outcome_type === "RECOMMENDATION_ENTITY") {
    return outcome.entity_text || "未知推荐对象";
  }
  if (outcome.outcome_type === "NO_RECOMMENDATION") return "无明确推荐";
  return "无有效样本";
}

function existingAssetStatusLabel(value?: string | null) {
  const labels: Record<string, string> = {
    AVAILABLE: "已有可用品牌资产",
    INCOMPLETE: "品牌资产不完整",
    UNKNOWN: "未知",
  };
  return value ? labels[value] || value : "-";
}

function existingAssetCoverageLabel(value?: string | null) {
  const labels: Record<string, string> = {
    MISSING: "未覆盖",
    CLAIM_ONLY: "只声明，缺少证明",
    SUFFICIENT: "覆盖充分",
    NOT_APPLICABLE: "不适用",
    UNKNOWN: "未知",
  };
  return value ? labels[value] || value : "-";
}

function citationDecisionStatusColor(status?: string) {
  if (status === "READY_FOR_HUMAN_CONFIRM") return "green";
  if (status === "NO_EXECUTABLE_RECOMMENDATION") return "orange";
  return "default";
}

function productTruthMatchLabel(status?: string) {
  const labels: Record<string, string> = {
    TRUE: "已匹配支持",
    FALSE: "已匹配不支持",
    UNKNOWN: "未匹配/未知",
  };
  return labels[status || ""] || status || "未匹配/未知";
}

function entityRelationTag(relation?: string, label?: string) {
  const colors: Record<string, string> = {
    TARGET_BRAND: "blue",
    CONFIRMED_COMPETITOR: "volcano",
    UNCONFIRMED_ENTITY: "gold",
  };
  const labels: Record<string, string> = {
    TARGET_BRAND: "目标品牌",
    CONFIRMED_COMPETITOR: "已确认竞品",
    UNCONFIRMED_ENTITY: "待确认对象",
  };
  return <Tag color={colors[relation || ""] || "default"}>{label || labels[relation || ""] || "未知对象"}</Tag>;
}

function decisionDisplayText(value?: string) {
  const replacements: [string, string][] = [
    ["Citation Prominence", "引用显著性"],
    ["LEGACY_RELATED", "历史相关标记"],
    ["Product Truth", "产品事实"],
    ["Benchmark Evidence", "对标证据"],
    ["Primary/Secondary Benchmark", "核心/辅助对标来源"],
    ["Decision Support", "决策支撑"],
    ["Source Gap", "来源缺口"],
    ["Primary", "核心"],
    ["Secondary", "辅助"],
    ["Benchmark", "对标来源"],
    ["Content/Evidence Action", "内容/证据动作"],
    ["Citation", "引用"],
    ["Gap", "缺口"],
    ["Action", "动作"],
    ["Experiment", "实验"],
    ["EVIDENCE_STRENGTHEN", "证据强化"],
    ["CONTENT_GAP", "内容缺口"],
    ["EVIDENCE_GAP", "证据缺口"],
    ["PRODUCT_GAP", "产品缺口"],
    ["NO_GAP", "暂无缺口"],
    ["UNRESOLVED", "待确认"],
    ["UNKNOWN", "未知"],
    ["HIGH", "高置信"],
    ["MEDIUM", "中置信"],
    ["LOW", "低置信"],
  ];
  return replacements.reduce((text, [from, to]) => text.split(from).join(to), value || "");
}

function citationCapabilityDraftFromRow(row: any) {
  const serverSuggestion = String(row?.suggested_capability_label || "").trim();
  if (serverSuggestion) return serverSuggestion;
  const rawTitle = String(row?.title || row?.url || "").trim();
  const withoutBrandSuffix = rawTitle
    .replace(/[-_｜|].*$/, "")
    .replace(/商加加外链工具/g, "")
    .replace(/20\d{2}\s*版?/g, "")
    .replace(/(教程|手把手教学流程|零技术入门|三种方法|完整教程)/g, "")
    .replace(/[：:，,。；;、（）()【】\[\]"'“”]+/g, " ")
    .trim();
  const compact = withoutBrandSuffix.split(/\s+/).filter(Boolean).join("");
  return (compact || "请改成目标品牌真实能力").slice(0, 36);
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
    RELEASED: "已发布",
    DRAFT: "草案",
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

function effectiveValidationStatusLabel(status?: string) {
  const labels: Record<string, string> = {
    VALIDATED: "已形成可执行策略",
    PENDING: "待校验",
    PENDING_HUMAN_CHANNEL_REVIEW: "策略已确认，待第 8 步确认执行方案",
    VALIDATION_FAILED: "校验失败",
    BLOCKED_PRODUCT_TRUTH: "产品事实阻塞",
  };
  return labels[status || ""] || status || "待确认";
}

function effectiveValidationStatusColor(status?: string) {
  const colors: Record<string, string> = {
    VALIDATED: "green",
    PENDING: "default",
    PENDING_HUMAN_CHANNEL_REVIEW: "blue",
    VALIDATION_FAILED: "red",
    BLOCKED_PRODUCT_TRUTH: "orange",
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

function textValue(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value || fallback;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.length ? value.map((item) => textValue(item, "")).filter(Boolean).join("；") : fallback;
  if (value && typeof value === "object") {
    const row = value as Record<string, any>;
    const candidate =
      row.summary ||
      row.description ||
      row.reason ||
      row.note ||
      row.title ||
      row.content_direction ||
      row.asset_direction ||
      row.platform_direction;
    if (candidate) return textValue(candidate, fallback);
  }
  return fallback;
}

function strategyEvidenceSummaryText(value: unknown, fallback = ""): string {
  if (!value) return fallback;
  if (typeof value !== "object" || Array.isArray(value)) return textValue(value, fallback);
  const row = value as Record<string, any>;
  const sourceTitle = row.benchmark_source?.title;
  const capabilities = Array.isArray(row.gap_items)
    ? row.gap_items.map((item: any) => item?.capability_label).filter(Boolean)
    : [];
  const parts = [
    sourceTitle ? `对标来源「${sourceTitle}」` : "",
    capabilities.length ? `涉及能力：${Array.from(new Set(capabilities)).join("、")}` : "",
    row.gap_type ? `缺口：${sourceGapLabel(row.gap_type)}` : "",
    row.priority_level ? `优先级：${priorityLevelLabel(row.priority_level)}` : "",
  ].filter(Boolean);
  return parts.join("；") || textValue(row, fallback);
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
    targetDecisionChange:
      textValue(executable.target_decision_change || original.target_decision_change, ""),
    strategicHypothesis:
      textValue(executable.strategic_hypothesis || original.strategic_hypothesis || executable.mechanism || original.mechanism, ""),
    priorityCapabilities:
      Array.isArray(executable.priority_capabilities)
        ? executable.priority_capabilities
        : Array.isArray(original.priority_capabilities)
          ? original.priority_capabilities
          : [],
    requiredSignals:
      Array.isArray(executable.required_signals)
        ? executable.required_signals
        : Array.isArray(original.required_signals)
          ? original.required_signals
          : [],
    interventionMechanism:
      textValue(executable.intervention_mechanism || original.intervention_mechanism || executable.mechanism || original.mechanism, ""),
    primaryInterventionPath:
      textValue(executable.primary_intervention_path || original.primary_intervention_path, ""),
    plannedChannels:
      Array.isArray(executable.planned_channels)
        ? executable.planned_channels
        : Array.isArray(original.planned_channels)
          ? original.planned_channels
          : [],
    channelRoles:
      executable.channel_roles || original.channel_roles || {},
    assetDirection:
      executable.asset_direction || original.asset_direction || null,
    executionSequence:
      Array.isArray(executable.execution_sequence)
        ? executable.execution_sequence
        : Array.isArray(original.execution_sequence)
          ? original.execution_sequence
          : [],
    attributionIntent:
      executable.attribution_intent || original.attribution_intent || null,
    nonGoals:
      Array.isArray(executable.non_goals)
        ? executable.non_goals
        : Array.isArray(original.non_goals)
          ? original.non_goals
          : [],
    strategyBoundaryNote:
      textValue(executable.strategy_boundary_note || original.strategy_boundary_note || executable.recommended_action_boundary, ""),
    evidenceSummary:
      strategyEvidenceSummaryText(
        executable.evidence_summary ||
        decisionMarket.primary_gap?.diagnosis_text ||
        interventionCandidate.observed_problem ||
        original.observed_problem,
        ""
      ),
    cause:
      textValue(
        executable.hypothesized_cause ||
        original.hypothesized_cause ||
        decisionMarket.primary_gap?.action_hint ||
        interventionCandidate.recommended_direction,
        ""
      ),
    actionText: textValue(actionText, ""),
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
    metricAvailability: textValue(executable.metric_availability || original.metric_availability, ""),
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
    BAIJIAHAO: "百家号",
    PRODUCT_DOCS: "产品文档",
    THIRD_PARTY_MEDIA: "第三方媒体",
    WECHAT: "微信",
    OFFICIAL_SITE: "官网",
    OTHER: "其他",
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
    RECOMMEND: "推荐",
    INCLUDE_AS_OPTION: "纳入候选",
    COMPARE: "对比",
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
    { title: url ? "引用页面" : "域名", render: (_, row) => url ? <Space direction="vertical" size={0}><Text>{row.title || displaySourceUrl(row.value)}</Text><Link href={sourceActionUrl(row.value)} target="_blank" ellipsis><ExternalLink size={12} /> {displaySourceDomain(row.domain, row.value) || displaySourceUrl(row.value)}</Link></Space> : <Text>{displaySourceDomain(row.value)}</Text> },
    { title: "出现次数", dataIndex: "run_count", width: 100, render: (value) => <Tag>{value} 次</Tag> }
  ]} />;
}

function PromptScopeAlert({ prompt, description }: { prompt: Prompt; description?: string }) {
  return <Alert type="info" showIcon style={{ marginBottom: -8 }}
    message={<Space><Text>当前视图：Prompt #{prompt.id}</Text><Text type="secondary">{prompt.prompt_text}</Text></Space>}
    description={description || "以下内容仅展示该 Prompt 的数据；切回「全部 Prompt」查看项目整体。"} />;
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
  const [refetchingSourceUrls, setRefetchingSourceUrls] = useState<Set<string>>(new Set());
  const [sourceRefetchResults, setSourceRefetchResults] = useState<Record<string, any>>({});
  const [workflowData, setWorkflowData] = useState<any>(null);
  const [promptContext, setPromptContext] = useState<number | "ALL" | null>(null); // null=未选, "ALL"=全部, number=具体 prompt
  const [channelStrategy, setChannelStrategy] = useState<any>(null); // V3 平台×内容方向（数据分层推导）
  const [resolveGoal, setResolveGoal] = useState<string>("EVIDENCE_STRENGTHEN"); // UNRESOLVED 人工指定方向
  const [resolveReason, setResolveReason] = useState<string>(""); // UNRESOLVED 人工理由
  const [draftChannels, setDraftChannels] = useState<string[]>([]); // 渠道多选（待确认）
  const [promptOverview, setPromptOverview] = useState<any>(null); // 项目视图的 Prompt 概览统计
  const [strategyPlan, setStrategyPlan] = useState<any>(null);
  const [channelOptions, setChannelOptions] = useState<any[]>([]);
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);
  const [strategyExperiments, setStrategyExperiments] = useState<any[]>([]);
  const [strategyBenchmarks, setStrategyBenchmarks] = useState<any>({});
  const [strategyOutcomes, setStrategyOutcomes] = useState<any>({});
  const [citationDecisionData, setCitationDecisionData] = useState<any>(null);
  const [citationDecisionLoading, setCitationDecisionLoading] = useState(false);
  const [citationDecisionError, setCitationDecisionError] = useState<string | null>(null);
  const citationDecisionRequestSeq = useRef(0);
  const [decisionMarketEntities, setDecisionMarketEntities] = useState<any[]>([]);
  const [workflowReviewOpen, setWorkflowReviewOpen] = useState(false);
  const [workflowEvidenceDrawerOpen, setWorkflowEvidenceDrawerOpen] = useState(false);
  const [workflowEvidenceDrawerFocus, setWorkflowEvidenceDrawerFocus] = useState<"gap" | "action" | "review">("gap");
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

  async function openGoldenCaseWorkspaceForPrompt(promptId?: number | null) {
    if (!promptId) {
      message.warning("请先选择一个具体问题");
      return;
    }
    setSelectedPromptId(promptId);
    setPage("golden");
    setGoldenLoading(true);
    try {
      message.loading({ content: "正在进入证据标注，准备引用正文和证据对齐...", duration: 0, key: "golden-workflow-entry" });
      const prepared = await prepareGoldenCaseWorkspace(promptId);
      message.destroy("golden-workflow-entry");
      if (prepared?.prepare?.manual_todos?.length) {
        message.warning("已准备证据标注数据；仍缺正文的来源请在表格中补录或重抓。");
      } else {
        message.success("已进入证据标注工作台");
      }
    } catch (error: any) {
      message.destroy("golden-workflow-entry");
      message.error(error.message || "证据标注数据准备失败");
    } finally {
      setGoldenLoading(false);
    }
  }
  const [loading, setLoading] = useState(false);
  const [retryingRuns, setRetryingRuns] = useState<Set<number>>(new Set());
  const [fallback, setFallback] = useState(false);
  const [promptForm] = Form.useForm();
  const [auditForm] = Form.useForm();
  const [projectForm] = Form.useForm();
  const [citationTruthForm] = Form.useForm();
  const [projectModalOpen, setProjectModalOpen] = useState(false);
  const [editingProjectId, setEditingProjectId] = useState<number | null>(null);
  const project = projects.find((item) => item.id === projectId);
  // promptContext：null=未显式选择（等同项目视图），"ALL"=全部 Prompt（项目视图），number=单 Prompt 视图
  const activePromptId = typeof promptContext === "number" ? promptContext : null;
  const scopedPrompt = activePromptId ? prompts.find((item) => item.id === activePromptId) : undefined;
  const visibleRuns = activePromptId ? runs.filter((item) => item.prompt_id === activePromptId) : runs;

  function resetPromptScopedAnalysisState() {
    citationDecisionRequestSeq.current += 1;
    setStrategyPlan(null);
    setSelectedChannels([]);
    setStrategyBenchmarks({});
    setStrategyOutcomes({});
    setChannelOptions([]);
    setStrategyExperiments([]);
    setCitationDecisionData(null);
    setCitationDecisionError(null);
    setDecisionMarketEntities([]);
    setDraftChannels([]);
    setRefetchingSourceUrls(new Set());
    setSourceRefetchResults({});
  }

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

  const workflowRequestSeq = useRef(0);
  async function loadWorkflowForPrompt(pid: number | null, targetProjectId: number = projectId!) {
    if (!targetProjectId) return;
    const seq = ++workflowRequestSeq.current;
    // 切换 Prompt 上下文时重置该 Prompt 专属的执行策略状态
    setWorkflowData(null);
    resetPromptScopedAnalysisState();
    try {
      // pid 为 null 时由后端返回机器分析进度最好的 Prompt（项目视图默认）
      const target = pid ?? (await (await fetch(`/api/optimization/workflow/${targetProjectId}/default-prompt`)).json())?.prompt_id;
      if (seq !== workflowRequestSeq.current) return; // 已被更新的切换取代
      if (!target) { setWorkflowData(null); return; }
      const wf = await (await fetch(`/api/optimization/workflow/${targetProjectId}/${target}/status`)).json();
      if (seq !== workflowRequestSeq.current) return;
      setWorkflowData(wf);
      // 同步加载执行策略上下文（渠道/实验/决策市场）
      const [channels, exps, dm] = await Promise.all([
        fetch(`/api/optimization/workflow/${targetProjectId}/${target}/channels`).then((r) => r.json()).catch(() => []),
        fetch(`/api/optimization/workflow/${targetProjectId}/${target}/experiments`).then((r) => r.json()).catch(() => []),
        fetch(`/api/optimization/workflow/${targetProjectId}/${target}/decision-market`).then((r) => r.json()).catch(() => null),
      ]);
      if (seq !== workflowRequestSeq.current) return;
      setChannelOptions(channels);
      setStrategyExperiments(exps);
      if (dm?.entities) setDecisionMarketEntities(dm.entities);
    } catch {
      // 工作流数据加载失败不影响主页面
      if (pid === null && seq === workflowRequestSeq.current) setWorkflowData(null);
    }
  }

  async function refreshWorkflowStatus() {
    if (!projectId || !workflowData?.prompt_id) return;
    try {
      const wf = await (await fetch(`/api/optimization/workflow/${projectId}/${workflowData.prompt_id}/status`)).json();
      setWorkflowData(wf);
    } catch { /* 状态刷新失败不影响当前页面 */ }
  }

  async function resolveDecisionMarketEntity(entityText: string, resolution: "CONFIRMED_COMPETITOR" | "TARGET_BRAND" | "REJECTED") {
    const pid = currentWorkflowData?.prompt_id;
    if (!projectId || !pid || !entityText) return;
    const label = resolution === "CONFIRMED_COMPETITOR" ? "竞品" : resolution === "TARGET_BRAND" ? "目标品牌/别名" : "不进入决策";
    setLoading(true);
    try {
      const resp = await fetch(`/api/optimization/workflow/${projectId}/${pid}/decision-market/entities/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_text: entityText, resolution }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      const result = await resp.json();
      message.success(`已把「${entityText}」标记为${label}，更新 ${result.updated_events || 0} 条答案事件`);
      await loadWorkflowForPrompt(pid, projectId);
    } catch (e: any) {
      message.error(e.message || "修正失败");
    } finally {
      setLoading(false);
    }
  }

  const dashboardRequestSeq = useRef(0);
  async function loadDashboard(id: number, promptId: number | null, freshRuns?: BrowserMonitorRun[], freshPrompts?: Prompt[]) {
    const seq = ++dashboardRequestSeq.current;
    try {
      const data = await api.getValidationDashboard(id, promptId ?? undefined);
      if (seq !== dashboardRequestSeq.current) return; // 已被更新的请求取代
      setDashboard(data);
      setFallback(false);
    } catch {
      if (seq !== dashboardRequestSeq.current) return;
      const selected = projects.find((item) => item.id === id);
      const baseRuns = freshRuns ?? runs;
      const basePrompts = freshPrompts ?? prompts;
      const scopedRuns = promptId ? baseRuns.filter((run) => run.prompt_id === promptId) : baseRuns;
      const scopedPrompts = promptId ? basePrompts.filter((item) => item.id === promptId) : basePrompts;
      const successful = scopedRuns.filter((run) => run.status === "success" || run.status === "partial_success");
      const nextDetails = (await Promise.all(successful.slice(0, 40).map((run) => api.getBrowserAuditRun(run.id).catch(() => null))))
        .filter((item): item is BrowserMonitorRunDetail => Boolean(item));
      if (seq !== dashboardRequestSeq.current) return;
      if (selected) setDashboard(deriveDashboard(selected, scopedPrompts, scopedRuns, nextDetails));
      setFallback(true);
    }
  }

  async function loadProject(id: number, opts?: { keepPromptContext?: boolean }) {
    const keep = opts?.keepPromptContext ?? true;
    const promptFilter = keep && typeof promptContext === "number" ? promptContext : null;
    if (!keep) setPromptContext(null);
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
      // 加载分析工作流状态：pid=null 时后端返回机器分析进度最好的 Prompt
      await loadWorkflowForPrompt(promptFilter, id);
      await loadDashboard(id, promptFilter, nextRuns, nextPrompts);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadProjects().catch((error) => message.error(error.message)); }, []);
  const prevProjectIdRef = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (!projectId) return;
    // 项目切换时回到项目视图；同项目刷新（如 projects.length 变化）保持当前 Prompt 上下文
    const isSwitch = prevProjectIdRef.current !== undefined && prevProjectIdRef.current !== projectId;
    prevProjectIdRef.current = projectId;
    loadProject(projectId, { keepPromptContext: !isSwitch }).catch((error) => message.error(error.message));
  }, [projectId, projects.length]);
  // 切换 Prompt 上下文时重新拉取监测看板（"ALL"=项目视图）
  useEffect(() => {
    if (!projectId || promptContext === null) return;
    loadDashboard(projectId, typeof promptContext === "number" ? promptContext : null).catch(() => {});
  }, [promptContext]);
  // Action 确认后加载 V3 平台×内容方向分析（渠道选择数据参考）
  useEffect(() => {
    const actionDone = Boolean(workflowData?.steps?.find((s: any) => s.key === "action")?.done);
    if (!projectId || !workflowData?.prompt_id || !actionDone) { setChannelStrategy(null); return; }
    if (channelStrategy?.prompt_id === workflowData.prompt_id) return;
    fetch(`/api/optimization/workflow/${projectId}/${workflowData.prompt_id}/channel-strategy`)
      .then((r) => r.json()).then(setChannelStrategy).catch(() => { /* 分析失败不阻塞渠道选择 */ });
  }, [projectId, workflowData]);
  // 项目视图加载 Prompt 概览（单 Prompt 视图不显示概览）
  useEffect(() => {
    if (!projectId || activePromptId) { setPromptOverview(null); return; }
    fetch(`/api/optimization/workflow/${projectId}/prompt-overview`)
      .then((r) => r.json()).then(setPromptOverview).catch(() => { /* 概览失败不影响页面 */ });
  }, [projectId, activePromptId, workflowData]);
  useEffect(() => {
    setRecommendationPromptId(null);
    setRecommendationData(null);
    setRecommendationClaims([]);
    setRecommendationSnapshots([]);
    setRecommendationAutoLoadedProjectId(null);
  }, [projectId]);
  useEffect(() => {
    if (page !== "recommendation" || !projectId || recommendationData || recommendationLoading || recommendationAutoLoadedProjectId === projectId) return;
    if (typeof promptContext === "number") return; // 单 Prompt 视图由下方 promptContext 效果加载
    setRecommendationAutoLoadedProjectId(projectId);
    loadLatestRecommendation(projectId).catch((error) => message.error(error.message || "加载已有决策诊断失败"));
  }, [page, projectId, recommendationData, recommendationLoading, recommendationAutoLoadedProjectId]);
  // 决策诊断跟随 Prompt 上下文：单 Prompt 加载该 Prompt 最新诊断；切回全部则回到项目视图
  useEffect(() => {
    if (!projectId || promptContext === null) return;
    if (typeof promptContext === "number") {
      if (page !== "recommendation" || recommendationPromptId === promptContext) return;
      setRecommendationData(null);
      loadRecommendationSnapshot(promptContext).catch(() => {
        message.info("该问题还没有已生成的决策诊断，点击「生成诊断」创建第一版");
      });
    } else if (recommendationPromptId !== null) {
      // 清掉单 Prompt 视图的残留数据；进入诊断页时自动加载项目最新
      setRecommendationData(null);
      setRecommendationPromptId(null);
      setRecommendationSnapshots([]);
      setRecommendationAutoLoadedProjectId(0);
    }
  }, [page, projectId, promptContext]);
  useEffect(() => {
    if ((page !== "optimization" && page !== "validation") || !projectId) return;
    loadOptimizationIssues().catch((error) => message.error(error.message || "加载实验闭环失败"));
    loadEvidencePackages(projectId).catch((error) => message.error(error.message || "加载证据失败"));
  }, [page, projectId]);
  useEffect(() => {
    if ((page !== "optimization" && page !== "validation") || !projectId) return;
    const targetPromptId = activePromptId || workflowData?.prompt_id;
    if (!targetPromptId) {
      setCitationDecisionData(null);
      return;
    }
    if (
      workflowData &&
      Number(workflowData.prompt_id) === Number(targetPromptId) &&
      !workflowData.steps?.some((step: any) => step.key === "answer_semantic" && step.done)
    ) {
      setCitationDecisionData(null);
      setCitationDecisionError(null);
      return;
    }
    loadCitationDecisionV1(targetPromptId, true).catch(() => {});
  }, [page, projectId, activePromptId, workflowData]);

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

  const recommendationLoadToken = useRef(0);
  async function loadRecommendationSnapshot(promptId: number, snapshotId?: number) {
    if (!projectId) return;
    const token = ++recommendationLoadToken.current;
    setRecommendationLoading(true);
    try {
      const data = await api.getRecommendationLandscape(projectId, promptId, snapshotId);
      if (token !== recommendationLoadToken.current) return; // 已被更新的加载取代
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

  async function openExperimentDraftForStrategy(candidate: any) {
    const plan = experimentPlanPayload(candidate?.experiment_plan);
    const actionId = Number(plan?.action_id || plan?.action_snapshot?.action_id || candidate?.action_id);
    const experimentId = Number(plan?.experiment_id || candidate?.experiment_id);
    if (!actionId && !experimentId) {
      message.info("该策略已确认，但尚未完成第 8 步执行方案配置；需要先选择具体资产、URL、内容结构和 Baseline。");
      return;
    }
    if (!projectId) return;
    setOptimizationLoading(true);
    try {
      const issues = optimizationIssues.length ? optimizationIssues : await api.listOptimizationIssues(projectId);
      setOptimizationIssues(issues);
      for (const issue of issues) {
        const chain = await api.getOptimizationEvidenceChain(issue.id);
        const matchedAction = (chain.actions || []).some((action: any) => Number(action.id) === actionId);
        const matchedExperiment = (chain.experiments || []).some((experiment: any) => Number(experiment.id) === experimentId);
        if (matchedAction || matchedExperiment) {
          setSelectedOptimizationIssueId(issue.id);
          setOptimizationChain(chain);
          setPage("optimization");
          message.success(`已打开实验草案 #${experimentId || "?"}`);
          return;
        }
      }
      message.warning("已找到策略记录，但没有在实验闭环中找到对应 Action/Experiment，请刷新后重试。");
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

  function currentCitationDecisionPromptId() {
    return activePromptId || workflowData?.prompt_id || null;
  }

  async function loadCitationDecisionV1(promptId?: number | null, silent = true) {
    const targetPromptId = promptId || currentCitationDecisionPromptId();
    if (!projectId || !targetPromptId) {
      setCitationDecisionData(null);
      setCitationDecisionError(null);
      return null;
    }
    const seq = ++citationDecisionRequestSeq.current;
    setCitationDecisionLoading(true);
    setCitationDecisionError(null);
    setCitationDecisionData(null);
    try {
      const data = await api.getCitationDecisionV1(
        projectId,
        targetPromptId,
        undefined,
        CURRENT_CITATION_DECISION_USE_ANSWER_BINDING_V1_1,
      );
      if (seq !== citationDecisionRequestSeq.current) return null;
      if (!citationDecisionBelongsToPrompt(data, targetPromptId)) {
        throw new Error("引用资料优化决策返回的 Prompt 与当前页面不一致，已丢弃旧结果");
      }
      setCitationDecisionData(data);
      if (data.evidence_package_id) {
        await selectEvidencePackage(data.evidence_package_id, true);
      }
      if (!silent) message.success("引用资料优化决策已重新运行");
      return data;
    } catch (error: any) {
      if (seq !== citationDecisionRequestSeq.current) return null;
      const errorMessage = error.message || "引用资料优化决策运行失败";
      setCitationDecisionData(null);
      setCitationDecisionError(errorMessage);
      if (!silent) message.error(errorMessage);
      return null;
    } finally {
      if (seq === citationDecisionRequestSeq.current) setCitationDecisionLoading(false);
    }
  }

  async function runCitationEvidenceForPrompt(promptId?: number | null) {
    const targetPromptId = promptId || currentCitationDecisionPromptId();
    if (!projectId || !targetPromptId) {
      message.warning("请先选择一个具体问题");
      return null;
    }
    const promptRuns = runs.filter((run: any) =>
      Number(run.prompt_id) === Number(targetPromptId) &&
      ["success", "partial_success"].includes(run.status)
    );
    if (!promptRuns.length) {
      message.warning("当前问题没有可用于生成证据包的采集样本");
      return null;
    }
    const runIds = promptRuns.map((run: any) => run.id);
    setCitationDecisionLoading(true);
    setCitationDecisionError(null);
    try {
      message.loading({ content: "正在生成证据包并运行引用证据链路...", duration: 0, key: "citation-evidence-run" });
      const evidencePackage = await api.createEvidencePackage(projectId, {
        prompt_id: targetPromptId,
        run_ids: runIds,
        source_note: "单 Prompt 主链路生成",
      });
      setSelectedPkgId(evidencePackage.id);
      await loadEvidencePackages(projectId).catch(() => []);
      const data = await api.getCitationDecisionV1(
        projectId,
        targetPromptId,
        evidencePackage.id,
        CURRENT_CITATION_DECISION_USE_ANSWER_BINDING_V1_1,
      );
      if (!citationDecisionBelongsToPrompt(data, targetPromptId)) {
        throw new Error("引用证据结果与当前 Prompt 不一致，已阻止渲染");
      }
      await selectEvidencePackage(evidencePackage.id, true);
      await loadWorkflowForPrompt(targetPromptId, projectId);
      setCitationDecisionData(data);
      message.destroy("citation-evidence-run");
      message.success(`已生成证据包 #${evidencePackage.id}，引用证据链路已运行`);
      return data;
    } catch (error: any) {
      message.destroy("citation-evidence-run");
      const errorMessage = error.message || "引用证据链路运行失败";
      setCitationDecisionData(null);
      setCitationDecisionError(errorMessage);
      message.error(errorMessage);
      return null;
    } finally {
      setCitationDecisionLoading(false);
    }
  }

  async function submitCitationProductTruth(values: any) {
    if (!projectId) return;
    const targetPromptId = currentCitationDecisionPromptId();
    setCitationDecisionLoading(true);
    try {
      await api.upsertTargetBrandCapabilityTruth(projectId, {
        capability_label: values.capability_label,
        product_truth_status: values.product_truth_status,
        truth_source: "MANUAL_CONFIRMED",
        source_reference: values.source_reference || "",
        note: values.note || "",
        reviewed_by: "human",
      });
      citationTruthForm.resetFields(["capability_label", "source_reference", "note"]);
      message.success("产品事实已补充，正在重新运行引用资料优化决策");
      await loadCitationDecisionV1(targetPromptId, true);
      if (recommendationData?.prompt_id === targetPromptId) {
        await reloadRecommendationSnapshot().catch(() => {});
      }
    } catch (error: any) {
      message.error(error.message || "产品事实补充失败");
    } finally {
      setCitationDecisionLoading(false);
    }
  }

  async function confirmCitationRowProductTruth(row: any, productTruthStatus: string) {
    if (!projectId) return;
    const targetPromptId = currentCitationDecisionPromptId();
    const capabilityLabel = citationCapabilityDraftFromRow(row);
    const brandName = project?.brand_name || "目标品牌";
    setCitationDecisionLoading(true);
    try {
      await api.upsertTargetBrandCapabilityTruth(projectId, {
        capability_label: capabilityLabel,
        product_truth_status: productTruthStatus,
        truth_source: "MANUAL_CONFIRMED",
        source_reference: "",
        note: `行内人工确认：确认对象是${brandName}，不是对标文章或竞品。触发来源：${row.url || row.title || "未知来源"}`,
        reviewed_by: "human",
      });
      message.success(`已记录${brandName}产品事实，正在重新运行链路`);
      await loadCitationDecisionV1(targetPromptId, true);
      if (recommendationData?.prompt_id === targetPromptId) {
        await reloadRecommendationSnapshot().catch(() => {});
      }
    } catch (error: any) {
      message.error(error.message || "目标品牌产品事实确认失败");
    } finally {
      setCitationDecisionLoading(false);
    }
  }

  async function confirmCitationDecisionV1() {
    const targetPromptId = currentCitationDecisionPromptId();
    if (!projectId || !targetPromptId) {
      message.warning("请先选择一个 Prompt");
      return;
    }
    setCitationDecisionLoading(true);
    try {
      const latest = await loadCitationDecisionV1(targetPromptId, true);
      if (!latest) return;
      const actionKeys = (latest.recommended_actions || [])
        .filter((item: any) => item.route === "CONTENT" || item.route === "EVIDENCE")
        .map((item: any) => item.action_key)
        .filter(Boolean);
      if (actionKeys.length === 0) {
        const blockedCount = (latest.source_analysis || []).filter((row: any) =>
          (row.benchmark_tier === "PRIMARY_BENCHMARK" || row.benchmark_tier === "SECONDARY_BENCHMARK") &&
          row.source_gap_precondition === "PRODUCT_TRUTH_UNKNOWN"
        ).length;
        message.warning(blockedCount > 0
          ? `还有 ${blockedCount} 条对标来源缺少目标品牌产品事实，暂不能生成策略候选`
          : "当前没有可生成策略候选的内容/证据缺口；可能没有真实缺口，或只剩产品评估/不需要动作");
        return;
      }
      const result = await api.confirmCitationDecisionV1(projectId, targetPromptId, {
        evidence_package_id: latest.evidence_package_id,
        use_answer_binding_v1_1: typeof latest.use_answer_binding_v1_1 === "boolean"
          ? latest.use_answer_binding_v1_1
          : CURRENT_CITATION_DECISION_USE_ANSWER_BINDING_V1_1,
        action_keys: actionKeys,
        reviewer: "human",
        review_note: "前端生成引用证据链路策略候选",
      });
      const createdIds = (result.created || [])
        .map((item: any) => item.strategy_candidate?.id)
        .filter(Boolean);
      if (latest.evidence_package_id) {
        await selectEvidencePackage(latest.evidence_package_id, true);
      }
      setPage("optimization");
      message.success(`已生成 ${createdIds.length || actionKeys.length} 个待审核策略候选，请在下方审核确认`);
      await Promise.all([
        loadCitationDecisionV1(targetPromptId, true),
        loadOptimizationIssues(),
      ]);
      setLatestGeneratedStrategyIds(createdIds);
      setStrategyCandidateFilter(createdIds.length ? `candidate:${createdIds[0]}` : "latest");
    } catch (error: any) {
      message.error(error.message || "生成策略候选失败");
    } finally {
      setCitationDecisionLoading(false);
    }
  }

  async function continueWorkflowAnalysis() {
    if (!projectId || !workflowData?.prompt_id) {
      message.warning("请先选择一个 Prompt");
      return;
    }
    setLoading(true);
    try {
      const response = await fetch(`/api/optimization/workflow/${projectId}/${workflowData.prompt_id}/continue`, { method: "POST" });
      if (!response.ok) throw new Error(await response.text());
      const result = await response.json();
      setWorkflowData({ ...workflowData, continueResult: result });
      message.success("旧缺口分析结果已生成");
      const wf = await (await fetch(`/api/optimization/workflow/${projectId}/${workflowData.prompt_id}/status`)).json();
      setWorkflowData({ ...wf, continueResult: result });
    } catch (error: any) {
      message.error(error.message || "旧缺口分析失败，请确认审核已全部完成");
    } finally {
      setLoading(false);
    }
  }

  async function runCurrentWorkflowAnalysis() {
    const targetPromptId = currentCitationDecisionPromptId() || workflowData?.prompt_id;
    if (!projectId || !targetPromptId) {
      message.warning("请先选择一个 Prompt");
      return;
    }
    setCitationDecisionLoading(true);
    try {
      const response = await fetch(`/api/optimization/workflow/${projectId}/${targetPromptId}/run-analysis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ use_answer_binding_v1_1: true }),
      });
      if (!response.ok) throw new Error(await response.text());
      const result = await response.json();
      message.success(result.already_running
        ? "当前主链已经在后台运行，完成后刷新状态"
        : "已开始重新运行当前主链，完成后会生成正式证据与策略候选状态");
      const wf = await (await fetch(`/api/optimization/workflow/${projectId}/${targetPromptId}/status`)).json();
      setWorkflowData(wf);
    } catch (error: any) {
      message.error(error.message || "重新运行当前主链失败");
    } finally {
      setCitationDecisionLoading(false);
    }
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

  function isAuditGeneratedStrategyCandidate(candidate: any) {
    const origin = String(candidate?.candidate_origin || "").toUpperCase();
    if (origin && origin !== "USER_FLOW") return true;
    if (candidate?.eligible_for_current_step7 === false) return true;
    const reviewer = String(candidate?.reviewed_by || "").toLowerCase();
    const note = String(candidate?.review_note || "").toLowerCase();
    return (
      reviewer.includes("audit") ||
      reviewer.includes("regression") ||
      /^phase[\w-]*_(audit|regression)$/.test(reviewer) ||
      note.includes("phase")
    );
  }

  function isCurrentStep7StrategyCandidate(candidate: any) {
    return candidate?.eligible_for_current_step7 === true;
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
      const selectedPackage = (evidencePackages || []).find((item: any) => Number(item.id) === Number(selectedPkgId));
      const targetPromptId = Number(selectedPackage?.prompt_id || currentCitationDecisionPromptId());
      if (!targetPromptId) {
        throw new Error("当前策略生成必须绑定一个单 Prompt 证据包，请先选择具体 Prompt 的证据。");
      }
      const latest = await loadCitationDecisionV1(targetPromptId, true);
      const actionKeys = (latest?.recommended_actions || [])
        .filter((item: any) => item.route === "CONTENT" || item.route === "EVIDENCE")
        .map((item: any) => item.action_key)
        .filter(Boolean);
      if (actionKeys.length === 0) {
        throw new Error("当前没有可生成策略候选的内容/证据缺口；历史策略不会计入当前第 7 步。");
      }
      const generated = await api.generateCurrentStep7StrategyCandidateV1(projectId, targetPromptId, {
        evidence_package_id: selectedPkgId,
        use_answer_binding_v1_1: typeof latest?.use_answer_binding_v1_1 === "boolean"
          ? latest.use_answer_binding_v1_1
          : CURRENT_CITATION_DECISION_USE_ANSWER_BINDING_V1_1,
        action_keys: actionKeys,
        reviewer: "human",
        review_note: "当前单 Prompt V1.1 Step 7 生成待审核策略候选",
      });
      const generatedCandidates = (generated?.created || [])
        .map((item: any) => item.strategy_candidate || item)
        .filter(Boolean);
      const generatedIds = generatedCandidates.map((item: any) => item.id).filter(Boolean);
      setLatestGeneratedStrategyIds(generatedIds);
      const existing = await api.listStrategyCandidates(projectId, selectedPkgId);
      const sorted = sortStrategyCandidates(existing);
      const reviewable = sorted.filter((item: any) => isCurrentStep7StrategyCandidate(item) && (item.review_status === "PENDING_REVIEW" || item.review_status === "ACCEPTED" || item.review_status === "ACCEPTED_WITH_EDITS"));
      await loadWorkflowForPrompt(targetPromptId, projectId);
      const generatedVersionMap = strategyVersionMap(existing);
      setStrategyData({
        ...(generated || {}),
        decision_status: reviewable.length ? "OPTIONS_AVAILABLE" : generated?.decision_status,
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
        ? `已生成待审核策略候选 #${candidateId}，请到「执行策略」完成人工审核`
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
  const citationTargetPromptId = currentCitationDecisionPromptId();
  const currentWorkflowData = workflowData && (!citationTargetPromptId || Number(workflowData.prompt_id) === Number(citationTargetPromptId))
    ? workflowData
    : null;
  const currentCitationDecisionData = citationDecisionBelongsToPrompt(citationDecisionData, citationTargetPromptId)
    ? citationDecisionData
    : null;
  const sortedStrategyCandidates = sortStrategyCandidatesByTime(strategyData?.candidates || []);
  const workflowStrategyIdSet = new Set(
    (currentWorkflowData?.current_strategy_candidate_ids || [])
      .map((id: any) => Number(id))
      .filter(Boolean)
  );
  const eligibleCurrentStep7StrategyCandidates = sortedStrategyCandidates.filter((candidate: any) => isCurrentStep7StrategyCandidate(candidate));
  const workflowMatchedStrategyCandidates = workflowStrategyIdSet.size
    ? eligibleCurrentStep7StrategyCandidates.filter((candidate: any) => workflowStrategyIdSet.has(Number(candidate.id)))
    : [];
  const workflowStrategyCandidates = workflowStrategyIdSet.size && workflowMatchedStrategyCandidates.length
    ? workflowMatchedStrategyCandidates
    : eligibleCurrentStep7StrategyCandidates;
  const strategyCandidatesForDefaultView = workflowStrategyCandidates.length ? workflowStrategyCandidates : [];
  const visibleStrategyCandidates = filterStrategyCandidates(
    strategyCandidateFilter === "latest" ? strategyCandidatesForDefaultView : sortedStrategyCandidates,
    strategyCandidateFilter
  );
  const strategyFilterOptions = [
    { label: "当前流程策略", value: "latest" },
    { label: "全部策略（含历史验收）", value: "all" },
    ...sortedStrategyCandidates.map((candidate: any) => ({
      label: `${strategyVersionLabel(candidate, sortedStrategyCandidates)} · 策略 #${candidate.id} · ${reviewStatusLabel(candidate.review_status)}`,
      value: `candidate:${candidate.id}`,
    })),
  ];
  const citationRows = currentCitationDecisionData?.source_analysis || [];
  const citationSummary = currentCitationDecisionData?.summary || {};
  const citationBenchmarkRows = citationRows.filter((row: any) => row.benchmark_tier === "PRIMARY_BENCHMARK" || row.benchmark_tier === "SECONDARY_BENCHMARK");
  const citationProductTruthBlockedRows = citationBenchmarkRows.filter((row: any) => row.source_gap_precondition === "PRODUCT_TRUTH_UNKNOWN");
  const citationRecommendedActions = currentCitationDecisionData?.recommended_actions || [];
  const citationConfirmableActions = citationRecommendedActions.filter((item: any) => item.route === "CONTENT" || item.route === "EVIDENCE");
  const citationChannelOpportunities = currentCitationDecisionData?.channel_opportunities || [];
  const decisionStability = currentCitationDecisionData?.decision_stability || null;
  const topRecommendationEntity = decisionStability?.recommendation_entities?.[0];
  const topRecommendationReason = decisionStability?.recommendation_reasons?.[0];
  const citationCanConfirm = citationConfirmableActions.length > 0;
  const citationLoaded = Boolean(currentCitationDecisionData);
  const backendStrategyStep = currentWorkflowData?.strategy_step || {};
  const backendExecutionStep = currentWorkflowData?.execution_step || {};
  const backendStrategyStepStatus = currentWorkflowData?.strategy_step_status || backendStrategyStep.status || "";
  const backendExecutionStepStatus = currentWorkflowData?.execution_step_status || backendExecutionStep.status || "";
  const currentNoStrategyNeeded = backendStrategyStepStatus === "NO_STRATEGY";
  const currentNeedsCurrentAnalysis = backendStrategyStepStatus === "NEEDS_CURRENT_ANALYSIS";
  const currentAnalysisRunning = backendStrategyStepStatus === "CURRENT_ANALYSIS_RUNNING";
  const currentAnalysisFailed = backendStrategyStepStatus === "CURRENT_ANALYSIS_FAILED";
  const backendCurrentStrategyIds = new Set(
    (currentWorkflowData?.current_strategy_candidate_ids || backendStrategyStep.current_strategy_candidate_ids || [])
      .map((id: any) => Number(id))
      .filter(Boolean)
  );
  const backendHistoricalStrategyIds = new Set(
    (currentWorkflowData?.historical_strategy_candidate_ids || [])
      .map((id: any) => Number(id))
      .filter(Boolean)
  );
  const backendCurrentExperimentId = Number(currentWorkflowData?.current_experiment_id || backendExecutionStep.current_experiment_id || 0);
  const currentPackageStrategyCandidates =
    currentCitationDecisionData?.evidence_package_id &&
    Number(selectedPkgId) === Number(currentCitationDecisionData.evidence_package_id)
      ? (strategyData?.candidates || [])
      : [];
  const workflowCurrentPackageStrategies = backendCurrentStrategyIds.size
    ? currentPackageStrategyCandidates.filter((item: any) => backendCurrentStrategyIds.has(Number(item.id)))
    : [];
  const backendHistoricalStrategyCount = currentWorkflowData?.historical_strategy_candidate_count ?? backendHistoricalStrategyIds.size;
  const sortedCurrentPackageStrategies = sortStrategyCandidatesByTime(workflowCurrentPackageStrategies);
  const confirmedStrategies = backendStrategyStepStatus === "CONFIRMED"
    ? workflowCurrentPackageStrategies.filter((item: any) => item.review_status === "ACCEPTED" || item.review_status === "ACCEPTED_WITH_EDITS")
    : [];
  const pendingStrategies = backendStrategyStepStatus === "PENDING_REVIEW"
    ? workflowCurrentPackageStrategies.filter((item: any) => item.review_status === "PENDING_REVIEW")
    : [];
  const strategyCandidateCount = workflowCurrentPackageStrategies.length;
  const latestStrategyCandidate = sortedCurrentPackageStrategies[0];
  const rawExperimentCount = backendCurrentExperimentId
    ? (strategyExperiments || []).filter((item: any) => Number(item.id) === backendCurrentExperimentId).length
    : 0;
  const historicalExperimentCount = Math.max((strategyExperiments?.length || 0) - rawExperimentCount, 0);
  const citationNeedsEvidencePackage = Boolean(citationDecisionError?.includes("尚无 Evidence Package") || citationDecisionError?.includes("尚无证据包"));
  const eligibleBenchmarkCount = (citationSummary.primary_benchmark_count || 0) + (citationSummary.secondary_benchmark_count || 0);
  const unknownGapCount = citationRows.filter((row: any) => row.source_gap_type === "UNKNOWN").length;
  const currentContinueResult = citationLoaded ? currentWorkflowData?.continueResult : null;
  const legacyContinueResult = !citationLoaded ? currentWorkflowData?.continueResult : null;
  const workflowStepByKey = (key: string) => currentWorkflowData?.steps?.find((step: any) => step.key === key);
  const answerSemanticStep = workflowStepByKey("answer_semantic");
  const eventReviewStep = workflowStepByKey("event_review");
  const answerStepDone = Boolean(answerSemanticStep?.done);
  const answerReviewDone = Boolean(eventReviewStep?.done);
  const answerStepBlocked = Boolean(currentWorkflowData && !answerStepDone && answerReviewDone);
  const productTruthStep = workflowStepByKey("product_truth");
  const productTruthDone = Boolean(answerStepDone && productTruthStep?.done);
  const evidenceReviewStep = workflowStepByKey("evidence_review");
  const gapWorkflowStep = workflowStepByKey("gap");
  const strategyWorkflowStep = workflowStepByKey("strategy") || workflowStepByKey("strategy_candidate") || workflowStepByKey("action");
  const evidenceReviewDone = Boolean(answerStepDone && evidenceReviewStep?.done);
  const strategyWorkflowDone = Boolean(answerStepDone && strategyWorkflowStep?.done);
  const currentCitationLoaded = Boolean(answerStepDone && citationLoaded);
  const currentCitationNeedsEvidencePackage = Boolean(answerStepDone && citationNeedsEvidencePackage);
  const citationGapDecisionDone = Boolean(
    currentCitationLoaded &&
    evidenceReviewDone &&
    !citationProductTruthBlockedRows.length &&
    unknownGapCount === 0
  );
  const strategyCurrentChainReady = Boolean(currentCitationLoaded && evidenceReviewDone && citationGapDecisionDone);
  const currentConfirmedStrategies = strategyCurrentChainReady ? confirmedStrategies : [];
  const currentPendingStrategies = strategyCurrentChainReady ? pendingStrategies : [];
  const currentStrategyCandidateCount = strategyCurrentChainReady ? strategyCandidateCount : 0;
  const currentConfirmedStrategyCount = currentConfirmedStrategies.length;
  const currentPendingStrategyCount = currentPendingStrategies.length;
  const currentLatestStrategyCandidate = strategyCurrentChainReady ? latestStrategyCandidate : null;
  const currentCitationCanConfirm = strategyCurrentChainReady && citationCanConfirm && backendStrategyStepStatus === "READY_TO_GENERATE";
  const ignoredHistoricalStrategyCount = backendHistoricalStrategyCount || Math.max(currentPackageStrategyCandidates.length - currentStrategyCandidateCount, 0);
  const currentExperimentCount = currentConfirmedStrategyCount && backendExecutionStepStatus === "CREATED" ? rawExperimentCount : 0;
  const ignoredHistoricalExperimentCount = currentWorkflowData?.historical_experiment_count ?? (!currentConfirmedStrategyCount ? (strategyExperiments?.length || 0) : historicalExperimentCount);
  const openStrategyConfirmationPage = () => {
    const packageId = currentCitationDecisionData?.evidence_package_id || currentWorkflowData?.current_state_context?.evidence_package_id || selectedPkgId;
    const targetPromptId = currentCitationDecisionData?.prompt_id || currentWorkflowData?.prompt_id || activePromptId;
    if (targetPromptId && projectId) void loadWorkflowForPrompt(Number(targetPromptId), projectId);
    if (packageId) void selectEvidencePackage(Number(packageId), true);
    setPage("optimization");
  };
  const citationStepItems = [
    {
      title: "引用来源",
      description: citationLoaded ? `${citationSummary.source_count ?? 0} 个来源` : "等待加载",
      status: citationLoaded ? "finish" : citationDecisionError ? "error" : "wait",
    },
    {
      title: "对标来源",
      description: citationLoaded ? `核心 ${citationSummary.primary_benchmark_count ?? 0} / 辅助 ${citationSummary.secondary_benchmark_count ?? 0}` : "等待来源资格判断",
      status: citationLoaded ? ((citationSummary.primary_benchmark_count || citationSummary.secondary_benchmark_count) ? "finish" : "process") : "wait",
    },
    {
      title: "缺口",
      description: citationProductTruthBlockedRows.length ? `${citationProductTruthBlockedRows.length} 条卡在产品事实` : citationLoaded ? "已完成资格判断" : "等待对标结果",
      status: citationProductTruthBlockedRows.length ? "error" : currentCitationDecisionData ? "finish" : "wait",
    },
    {
      title: "策略确认",
      description: currentStrategyCandidateCount
        ? `${currentStrategyCandidateCount} 个当前候选`
        : currentAnalysisRunning
          ? "当前主链后台运行中"
        : currentAnalysisFailed
          ? "当前主链运行失败，可重试"
        : currentNeedsCurrentAnalysis
          ? "有上游线索，需重新运行当前主链"
        : currentNoStrategyNeeded
          ? "本轮无需策略候选"
        : ignoredHistoricalStrategyCount
          ? `已有 ${ignoredHistoricalStrategyCount} 个历史候选，不计入当前主链`
          : citationLoaded
          ? `${citationSummary.recommended_action_count ?? 0} 个可生成线索`
          : "等待缺口判断",
      status: currentConfirmedStrategyCount || currentNoStrategyNeeded ? "finish" : currentAnalysisFailed ? "error" : currentAnalysisRunning || currentNeedsCurrentAnalysis || currentPendingStrategyCount || currentCitationCanConfirm ? "process" : currentCitationDecisionData ? "wait" : "wait",
    },
    {
      title: "实验方案",
      description: currentExperimentCount
        ? `${currentExperimentCount} 个当前草案/实验`
        : currentAnalysisRunning
          ? "等待当前主链运行完成"
        : currentAnalysisFailed
          ? "先重新运行当前主链"
        : currentNeedsCurrentAnalysis
          ? "等待当前主链生成策略候选"
        : currentNoStrategyNeeded
          ? "本轮无需实验草案"
        : ignoredHistoricalExperimentCount
          ? `已有 ${ignoredHistoricalExperimentCount} 个历史草案/实验，不计入当前步骤`
          : currentConfirmedStrategyCount
            ? "待创建实验草案"
            : "等待策略确认",
      status: currentExperimentCount || currentNoStrategyNeeded ? "finish" : currentConfirmedStrategyCount ? "process" : "wait",
    },
  ] as any[];
  const collectedRunCount = visibleRuns.filter((run: any) => ["success", "partial_success"].includes(run.status)).length;
  const unresolvedAction = currentContinueResult?.action?.intervention_goal === "UNRESOLVED";
  const mainWorkflowSteps = [
    {
      key: "collect",
      label: "采集样本",
      statusText: collectedRunCount > 0 ? "已完成" : "待采集",
      detail: collectedRunCount > 0 ? `${collectedRunCount} 次可观察采集` : "等待采集",
      tone: collectedRunCount > 0 ? "done" : "pending",
      actionLabel: "查看采集",
      onAction: () => setPage("runs"),
    },
    {
      key: "answer",
      label: "答案决策识别",
      statusText: answerStepDone ? "已完成" : answerStepBlocked ? "需修正识别" : currentWorkflowData ? "待审核" : "待分析",
      detail: answerStepDone ? (answerSemanticStep?.detail || "已识别答案里的品牌/方案选择事件") : answerStepBlocked ? (answerSemanticStep?.detail || "没有有效选择事件，不能进入后续链路") : currentWorkflowData ? `${currentWorkflowData.pending_review_steps || 0} 步待审核` : "进入详情生成机器诊断",
      tone: answerStepDone ? "done" : answerStepBlocked ? "warning" : currentWorkflowData ? "current" : "pending",
      actionLabel: !currentWorkflowData ? "进入诊断" : answerStepDone ? "查看依据" : answerStepBlocked ? "去修正诊断" : "开始审核",
      onAction: !currentWorkflowData
        ? () => setPage("recommendation")
        : answerStepDone
          ? () => { setWorkflowEvidenceDrawerFocus("review"); setWorkflowEvidenceDrawerOpen(true); }
          : answerStepBlocked
            ? () => setPage("recommendation")
            : () => setWorkflowReviewOpen(true),
    },
    {
      key: "truth",
      label: "目标品牌事实",
      statusText: !answerStepDone ? "等待识别" : citationProductTruthBlockedRows.length ? "待补充" : productTruthDone ? "已完成" : "可补充",
      detail: citationProductTruthBlockedRows.length
        ? `${citationProductTruthBlockedRows.length} 条目标品牌能力待确认`
        : productTruthDone
          ? "已有目标品牌事实，可后续增量补充"
          : answerStepDone
            ? "先确认目标品牌真实能力，后续对标可追加"
            : "先完成答案决策识别",
      tone: !answerStepDone ? "pending" : citationProductTruthBlockedRows.length || !productTruthDone ? "current" : "done",
      actionLabel: answerStepDone ? (citationProductTruthBlockedRows.length ? "补充事实" : "查看事实") : "",
      onAction: answerStepDone ? () => setPage("optimization") : undefined,
    },
    {
      key: "citation",
      label: "引用证据",
      statusText: !answerStepDone ? "未开始" : currentCitationLoaded ? "已完成" : citationDecisionLoading ? "运行中" : currentCitationNeedsEvidencePackage ? "待生成证据包" : citationDecisionError ? "待重试" : "待运行",
      detail: !answerStepDone ? "先完成答案决策识别" : currentCitationLoaded ? `${citationSummary.source_count ?? 0} 个当前来源，去补正文和证据对齐` : currentCitationNeedsEvidencePackage ? "当前问题尚无证据包；正文已补齐后可直接生成并运行" : citationDecisionError ? "当前链路运行失败，可重试或核对引用正文" : "生成当前问题的证据包，并运行引用正文和证据对齐",
      tone: currentCitationLoaded ? "done" : answerStepDone && citationDecisionLoading ? "current" : "pending",
      actionLabel: answerStepDone ? (currentCitationLoaded ? "查看证据正文" : currentCitationNeedsEvidencePackage || citationDecisionError ? "生成证据包" : "运行引用证据") : "",
      onAction: answerStepDone
        ? currentCitationLoaded
          ? () => openGoldenCaseWorkspaceForPrompt(citationTargetPromptId)
          : () => runCitationEvidenceForPrompt(citationTargetPromptId)
        : undefined,
    },
    {
      key: "benchmark",
      label: "对标来源",
      statusText: currentCitationLoaded ? "已判断" : "未开始",
      detail: currentCitationLoaded ? (eligibleBenchmarkCount > 0 ? `核心 ${citationSummary.primary_benchmark_count ?? 0} / 辅助 ${citationSummary.secondary_benchmark_count ?? 0}` : "0 个可信对标（允许）") : "等待引用证据",
      tone: currentCitationLoaded ? "done" : "pending",
      actionLabel: currentCitationLoaded ? "查看对标" : "",
      onAction: currentCitationLoaded ? () => setPage("optimization") : undefined,
    },
    {
      key: "gap",
      label: "缺口诊断",
      statusText: !currentCitationLoaded ? "未开始" : eligibleBenchmarkCount === 0 ? "暂无缺口" : unknownGapCount > 0 ? "待人工判断" : "已完成",
      detail: !currentCitationLoaded ? "等待对标来源" : eligibleBenchmarkCount === 0 ? "暂无可分析 Benchmark，不生成竞争缺口" : unknownGapCount > 0 ? `${unknownGapCount} 条缺口需要人工判断` : "已基于对标来源完成缺口判断",
      tone: !currentCitationLoaded ? "pending" : unknownGapCount > 0 ? "current" : "done",
      actionLabel: currentCitationLoaded ? "查看缺口" : "",
      onAction: currentCitationLoaded ? () => setPage("optimization") : undefined,
    },
    {
      key: "action",
      label: "策略确认",
      statusText: currentConfirmedStrategyCount ? "已确认" : currentPendingStrategyCount ? "待审核" : currentCitationCanConfirm ? "可生成" : currentAnalysisRunning ? "主链运行中" : currentAnalysisFailed ? "运行失败" : currentNeedsCurrentAnalysis ? "需重跑主链" : currentNoStrategyNeeded ? "无需策略" : !currentCitationLoaded ? "未开始" : !evidenceReviewDone ? "待证据审核" : !citationGapDecisionDone ? "等待缺口" : unresolvedAction || unknownGapCount > 0 ? "待人工判断" : "无策略",
      detail: currentConfirmedStrategyCount
        ? `已确认策略 #${currentConfirmedStrategies[0]?.id || currentLatestStrategyCandidate?.id}`
        : currentPendingStrategyCount
          ? `${currentPendingStrategyCount} 个当前策略候选待人工审核`
          : currentCitationCanConfirm
            ? `${citationConfirmableActions.length} 个缺口可生成策略候选`
            : currentAnalysisRunning
              ? (currentWorkflowData?.strategy_step_detail || "当前主链正在后台运行")
            : currentAnalysisFailed
              ? (currentWorkflowData?.strategy_step_detail || "当前主链运行失败，请重试或查看日志")
            : currentNeedsCurrentAnalysis
              ? (currentWorkflowData?.strategy_step_detail || "当前有答案决策/证据线索，但尚未生成 V1.1 正式证据与缺口")
            : currentNoStrategyNeeded
              ? "本轮没有可生成策略的内容/证据缺口"
            : !currentCitationLoaded
              ? "等待缺口诊断"
              : !evidenceReviewDone
                ? (evidenceReviewStep?.detail || "先完成人工证据审核，历史策略不计入当前主链")
                : !citationGapDecisionDone
                  ? (gapWorkflowStep?.detail || "先生成当前缺口诊断")
                  : unresolvedAction || unknownGapCount > 0
                    ? "请查看依据后人工判断，不自动生成策略"
                    : "没有可生成策略的内容/证据缺口",
      tone: currentConfirmedStrategyCount || currentNoStrategyNeeded ? "done" : currentAnalysisFailed ? "error" : currentPendingStrategyCount || currentCitationCanConfirm || currentAnalysisRunning || currentNeedsCurrentAnalysis || unresolvedAction ? "current" : "pending",
      actionLabel: currentConfirmedStrategyCount ? "查看已确认策略" : currentPendingStrategyCount ? "审核策略候选" : currentCitationCanConfirm ? "生成策略候选" : currentAnalysisRunning ? "运行中" : currentAnalysisFailed ? "重新运行当前主链" : currentNeedsCurrentAnalysis ? "重新运行当前主链" : currentNoStrategyNeeded || unresolvedAction ? "查看依据" : "",
      onAction: currentConfirmedStrategyCount || currentPendingStrategyCount
        ? openStrategyConfirmationPage
        : currentCitationCanConfirm
          ? confirmCitationDecisionV1
          : currentAnalysisRunning
            ? undefined
          : currentAnalysisFailed
            ? runCurrentWorkflowAnalysis
          : currentNeedsCurrentAnalysis
            ? runCurrentWorkflowAnalysis
          : currentNoStrategyNeeded
            ? () => setPage("optimization")
          : unresolvedAction
            ? () => { setWorkflowEvidenceDrawerFocus("action"); setWorkflowEvidenceDrawerOpen(true); }
            : undefined,
    },
    {
      key: "experiment",
      label: "实验方案落地",
      statusText: currentExperimentCount ? "已创建" : currentConfirmedStrategyCount ? "待创建" : currentAnalysisRunning ? "等待主链" : currentAnalysisFailed ? "等待重跑" : currentNeedsCurrentAnalysis ? "等待主链" : currentNoStrategyNeeded ? "无需创建" : currentCitationLoaded ? "未创建" : "未开始",
      detail: currentExperimentCount
        ? `${currentExperimentCount} 个当前草案/实验，等待发布闸门`
        : ignoredHistoricalExperimentCount && !currentConfirmedStrategyCount
          ? "存在历史草案/实验，但当前主链仍需先完成策略确认"
          : currentAnalysisRunning
            ? "当前主链运行完成后，再进入策略确认"
          : currentAnalysisFailed
            ? "先修复并重新运行当前主链"
          : currentNeedsCurrentAnalysis
            ? "先重新运行当前主链，生成正式证据与策略候选"
          : currentNoStrategyNeeded
            ? "本轮没有策略候选，无需实验草案"
          : currentConfirmedStrategyCount
            ? "策略确认后，进入执行方案和实验草案"
            : currentCitationLoaded
              ? "等待策略确认"
              : "等待策略候选",
      tone: currentExperimentCount || currentNoStrategyNeeded ? "done" : currentAnalysisFailed ? "error" : currentConfirmedStrategyCount || currentAnalysisRunning || currentNeedsCurrentAnalysis ? "current" : "pending",
      actionLabel: currentExperimentCount ? "查看实验草案" : currentConfirmedStrategyCount ? "去创建草案" : "",
      onAction: currentExperimentCount || currentConfirmedStrategyCount ? openStrategyConfirmationPage : undefined,
    },
  ];
  const workflowToneMeta: Record<string, { color: string; text: string; className: string }> = {
    done: { color: "green", text: "完成", className: "done" },
    current: { color: "blue", text: "当前", className: "current" },
    warning: { color: "gold", text: "待补", className: "warning" },
    error: { color: "red", text: "异常", className: "error" },
    pending: { color: "default", text: "等待", className: "pending" },
  };
  const unresolvedReviewContext = currentContinueResult?.review_context || {};
  const unresolvedAnswerSamples = unresolvedReviewContext.answer_samples || [];
  const unresolvedEventDiagnostics = unresolvedReviewContext.event_diagnostics || [];
  const unresolvedEventStatusCounts = unresolvedReviewContext.event_status_counts || {};
  const decisionMarketUnknownEntities = decisionMarketEntities.filter((item: any) => item.relationship === "UNKNOWN_ENTITY");

  return <Layout className="app-shell">
    <Sider width={228} className="side-nav">
      <div className="brand-block"><Title level={4}>生成式搜索决策平台</Title><Text type="secondary">监测 · 诊断 · 策略 · 复测</Text></div>
        <Menu mode="inline" selectedKeys={[page]} onClick={({ key }) => setPage(key as PageKey)} items={[
        { type: "group", label: "业务闭环", children: [
          { key: "validation", icon: <BarChart3 size={18} />, label: "监测总览" },
          { key: "recommendation", icon: <ShieldCheck size={18} />, label: "决策诊断" },
          { key: "optimization", icon: <ShieldCheck size={18} />, label: "执行策略" },
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
          {projectId && prompts.length>0 && <Select size="small" style={{minWidth:240}} placeholder="选择 Prompt"
            value={promptContext ?? "ALL"}
            options={[{label:"全部 Prompt（项目视图）",value:"ALL"},...prompts.map((p:any)=>({label:`#${p.id} ${p.prompt_text}`,value:p.id}))]}
            onChange={async(v)=>{
              setPromptContext(v);
              // "ALL"=项目视图：展示机器分析进度最好的 Prompt 的工作流；单 Prompt 则展示该 Prompt 的
              await loadWorkflowForPrompt(typeof v === "number" ? v : null);
            }}
          />}
          <Button icon={<Plus size={16} />} onClick={() => openProjectModal()}>新建项目</Button>
          <Button icon={<Settings size={16} />} onClick={() => projectId && openProjectModal(projectId)} disabled={!projectId}>编辑项目</Button>
          <Button icon={<RefreshCw size={16} />} loading={loading} onClick={() => projectId && loadProject(projectId)}>刷新</Button>
        </Space>
      </Header>
      <Content className="workspace">
        {!project || !dashboard ? <Card loading={loading}><Empty description="请选择包含采集数据的项目" /></Card> : page === "validation" ? <Space direction="vertical" size={16} className="page-stack">
          {scopedPrompt && <PromptScopeAlert prompt={scopedPrompt} description="以下指标仅统计该 Prompt 的采集记录；切回「全部 Prompt」查看项目整体。" />}
          <Card size="small" className="audit-hero">
            <Row align="middle" justify="space-between" gutter={[16, 16]}>
              <Col><Space direction="vertical" size={4}><Space><Title level={4}>{project.name}</Title><Tag color="blue">{dashboard.sample_label || "验证样本"}</Tag></Space><Text type="secondary">{dashboard.environment_label || "单一采集环境，仅表示当前验证样本"}</Text></Space></Col>
              <Col><Alert type="info" showIcon message="以下为验证样本观察值，不代表总体品牌曝光概率。" /></Col>
            </Row>
          </Card>
          {projectId && !activePromptId && promptOverview && <Card size="small" title={<Space><ShieldCheck size={18} />GEO 工作台 · Prompt 概览（项目视图）</Space>} extra={<Text type="secondary">选择单个 Prompt 查看其工作流</Text>}>
            <Row gutter={[16, 16]}>
              <Col xs={12} md={8} lg={4}><Statistic title="Prompt 总数" value={promptOverview.total_prompts} /></Col>
              <Col xs={12} md={8} lg={4}><Statistic title="已采集" value={promptOverview.prompts_with_runs} suffix="个" /></Col>
              <Col xs={12} md={8} lg={4}><Statistic title="已机器分析" value={promptOverview.prompts_analyzed} suffix="个" /></Col>
              <Col xs={12} md={8} lg={4}><Statistic title="品牌被推荐" value={promptOverview.prompts_brand_recommended} suffix="个" /></Col>
              <Col xs={12} md={8} lg={4}><Statistic title="答案含推荐（任意品牌）" value={promptOverview.prompts_any_recommended} suffix="个" /></Col>
              <Col xs={12} md={8} lg={4}><Statistic title="品牌被提及" value={promptOverview.prompts_brand_mentioned} suffix="个" /></Col>
              <Col xs={12} md={8} lg={4}><Statistic title="已审核完成" value={promptOverview.prompts_reviews_done} suffix="个" /></Col>
            </Row>
          </Card>}
          {projectId && activePromptId && <Card size="small" title={<Space><ShieldCheck size={18} />GEO 工作台 · Prompt #{currentWorkflowData?.prompt_id || activePromptId}</Space>} extra={<Space>
            <Button size="small" onClick={()=>setPage("recommendation")}>决策诊断详情</Button>
            <Button size="small" onClick={openStrategyConfirmationPage}>策略确认详情</Button>
            {currentWorkflowData ? (currentWorkflowData.shelved
              ? <Tag color="volcano">已人工搁置</Tag>
              : currentWorkflowData.ready_to_continue
                ? <Tag color="green">答案识别已完成</Tag>
                : answerStepBlocked
                  ? <Tag color="gold">答案识别需修正</Tag>
                : <Button type="primary" size="small" danger onClick={()=>setWorkflowReviewOpen(true)}>开始审核（{currentWorkflowData.pending_review_steps} 步待处理）</Button>)
              : <Tag color="blue">等待当前 Prompt 状态</Tag>}
          </Space>}>
            <div className="single-prompt-flow">
              {mainWorkflowSteps.map((step: any, index: number) => {
                const tone = workflowToneMeta[step.tone] || workflowToneMeta.pending;
                return <div key={step.key} className={`workflow-step-card ${tone.className}`}>
                  <div className="workflow-step-head">
                    <span className="workflow-step-index">{index + 1}</span>
                    <Space size={6} wrap>
                      <Text strong>{step.label}</Text>
                      <Tag color={tone.color}>{step.statusText || tone.text}</Tag>
                    </Space>
                  </div>
                  <Text type="secondary" className="workflow-step-detail">{step.detail}</Text>
                  {step.actionLabel && <Button
                    size="small"
                    type={step.tone === "current" ? "primary" : "default"}
                    loading={(step.key === "citation" || step.key === "action" || step.key === "experiment") && citationDecisionLoading}
                    onClick={step.onAction}
                  >
                    {step.actionLabel}
                  </Button>}
                </div>;
              })}
            </div>
            <Space wrap style={{ marginTop: 12 }}>
              <Tag color={citationDecisionStatusColor(currentCitationDecisionData?.status)}>{citationDecisionStatusLabel(currentCitationDecisionData?.status)}</Tag>
              {answerStepDone && citationDecisionError && <Tag color="red">引用链路异常</Tag>}
              <Button size="small" icon={<RefreshCw size={14} />} loading={citationDecisionLoading} disabled={!answerStepDone} onClick={() => loadCitationDecisionV1(citationTargetPromptId, false)}>刷新主链路</Button>
              <Button
                size="small"
                type="primary"
                disabled={currentAnalysisRunning || (!currentCitationCanConfirm && !currentStrategyCandidateCount && !currentNeedsCurrentAnalysis && !currentAnalysisFailed)}
                loading={citationDecisionLoading}
                onClick={currentStrategyCandidateCount ? openStrategyConfirmationPage : currentAnalysisFailed || currentNeedsCurrentAnalysis ? runCurrentWorkflowAnalysis : confirmCitationDecisionV1}
              >
                {currentConfirmedStrategyCount ? "查看已确认策略" : currentPendingStrategyCount ? "审核策略候选" : currentCitationCanConfirm ? "生成策略候选" : currentAnalysisRunning ? "主链运行中" : currentAnalysisFailed || currentNeedsCurrentAnalysis ? "重新运行当前主链" : "等待策略确认"}
              </Button>
              <Button size="small" onClick={openStrategyConfirmationPage}>{citationProductTruthBlockedRows.length ? "补目标品牌事实" : "策略确认详情"}</Button>
              {citationProductTruthBlockedRows.length > 0 && <Text type="secondary">这里确认的是{project?.brand_name || "目标品牌"}自己的能力，不是竞品或对标文章的能力。</Text>}
              {legacyContinueResult && <Tag color="default">存在历史缺口/动作结果，不计入当前引用决策进度</Tag>}
            </Space>
            {decisionStability && <Card size="small" style={{ marginTop: 12 }} title={<Space wrap><Text strong>决策稳定性观察</Text><Tag color={decisionStabilityLevelColor(decisionStability.stability_level)}>{decisionStability.stability_level_label}</Tag><Tag>旁路指标</Tag></Space>}>
              <Row gutter={[12, 12]}>
                <Col xs={12} md={6}><Statistic title="有效样本" value={decisionStability.valid_run_count ?? 0} suffix="Runs" /></Col>
                <Col xs={12} md={6}><Statistic title="品牌决策发生" value={`${decisionStability.brand_decision_run_count ?? 0}/${decisionStability.valid_run_count ?? 0}`} /></Col>
                <Col xs={12} md={6}><Statistic title="主要推荐对象" value={dominantOutcomeText(decisionStability.dominant_recommendation_outcome)} /></Col>
                <Col xs={12} md={6}><Statistic title="稳定性" value={decisionStability.decision_stability_score ?? 0} suffix="/100" /></Col>
              </Row>
              <Text type="secondary">
                {topRecommendationEntity ? `主要推荐覆盖：${dominantOutcomeText(decisionStability.dominant_recommendation_outcome)}。` : "当前没有明确推荐对象覆盖。"}
                {topRecommendationReason ? ` 代表理由覆盖：${decisionDisplayText(topRecommendationReason.reason_text)} ${topRecommendationReason.reason_observed_run_count}/${topRecommendationReason.denominator}。` : ""}
                {" "}该指标只描述多次采样里的推荐波动，不影响证据、对标、缺口、策略、动作或实验。
              </Text>
            </Card>}
            {currentWorkflowData && currentContinueResult && <Space direction="vertical" size={4} style={{width:"100%", marginTop:8}}>
              <Alert type={currentContinueResult.gap?.gap_type==="UNRESOLVED" ? "warning" : "success"} showIcon
                message={<Space wrap><Text strong>缺口：{decisionDisplayText(currentContinueResult.gap?.gap_type)}</Text><Tag>{decisionDisplayText(currentContinueResult.gap?.confidence)}</Tag>
                  <Button size="small" onClick={() => { setWorkflowEvidenceDrawerFocus("gap"); setWorkflowEvidenceDrawerOpen(true); }}>查看依据</Button>
                </Space>}
                description={currentContinueResult.gap?.basis} />
              <Alert type={currentContinueResult.action?.intervention_goal==="UNRESOLVED" ? "warning" : "info"} showIcon
                message={<Space wrap><Text strong>动作：{decisionDisplayText(currentContinueResult.action?.intervention_goal)}</Text><Tag>{decisionDisplayText(currentContinueResult.action?.asset_ownership)}</Tag><Tag>{decisionDisplayText(currentContinueResult.action?.target_platform)}</Tag>
                  <Button size="small" onClick={() => { setWorkflowEvidenceDrawerFocus("action"); setWorkflowEvidenceDrawerOpen(true); }}>查看依据</Button>
                  {currentContinueResult.action?.intervention_goal!=="UNRESOLVED" && <Button size="small" type="primary" onClick={openStrategyConfirmationPage}>进入策略确认</Button>}
                </Space>}
                description={currentContinueResult.action?.intervention_goal==="UNRESOLVED"
                  ? (currentContinueResult.action?.note || "")
                  : currentContinueResult.action?.target_claim} />
            </Space>}
            {currentWorkflowData?.shelved && <Alert type="warning" showIcon
              message={`该 Prompt 已人工搁置：${currentWorkflowData.shelved_note || "机器无法确定缺口类型"}`}
              description="补充采集数据后可重新运行机器分析。" />}
            {currentContinueResult?.action?.intervention_goal==="UNRESOLVED" && !currentWorkflowData?.shelved && <Space direction="vertical" size={8} style={{ width: "100%", marginTop: 8 }}>
              <Alert
                type="warning"
                showIcon
                message="人工决策：机器无法确定干预方向"
                description={<Space direction="vertical" size={6}>
                  <Text>{unresolvedReviewContext.review_instruction || "请先核对答案样本，再决定是否人工指定方向或搁置。"}</Text>
                  <Button size="small" onClick={() => { setWorkflowEvidenceDrawerFocus("review"); setWorkflowEvidenceDrawerOpen(true); }}>查看答案和机器识别依据</Button>
                </Space>}
              />
              <Card size="small" title="人工决策入口">
                <Space direction="vertical" size={8} style={{width:"100%"}}>
                  <Space wrap>
                    <Text>干预方向：</Text>
                    <Select size="small" style={{minWidth:220}} value={resolveGoal} onChange={setResolveGoal}
                      options={[{value:"EVIDENCE_STRENGTHEN",label:"证据强化"}]} />
                    <Input size="small" style={{width:320}} placeholder="理由（必填，记录在案）" value={resolveReason} onChange={(e)=>setResolveReason(e.target.value)} />
                  </Space>
                  <Space>
                    <Button size="small" type="primary" onClick={async()=>{
                      if (!resolveReason.trim()) { message.warning("请填写人工指定方向的理由"); return; }
                      try {
                        await fetch(`/api/optimization/workflow/${projectId}/${currentWorkflowData.prompt_id}/resolve-unresolved`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({decision:"OVERRIDE",intervention_goal:resolveGoal,reason:resolveReason.trim()})});
                        message.success(`已按人工指定方向「${decisionDisplayText(resolveGoal)}」继续`);
                        const wf = await (await fetch(`/api/optimization/workflow/${projectId}/${currentWorkflowData.prompt_id}/status`)).json();
                        setWorkflowData({...wf, continueResult: {...currentContinueResult, action: {...currentContinueResult.action, intervention_goal: resolveGoal, target_claim: `人工指定方向：${resolveGoal}。理由：${resolveReason.trim()}`}}});
                      } catch(e:any) { message.error(e.message || "操作失败"); }
                    }}>按此方向继续</Button>
                    <Button size="small" onClick={async()=>{
                      try {
                        await fetch(`/api/optimization/workflow/${projectId}/${currentWorkflowData.prompt_id}/resolve-unresolved`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({decision:"SHELVE",reason:resolveReason.trim()})});
                        message.success("已标记搁置");
                        const wf = await (await fetch(`/api/optimization/workflow/${projectId}/${currentWorkflowData.prompt_id}/status`)).json();
                        setWorkflowData({...wf, continueResult: currentContinueResult});
                      } catch(e:any) { message.error(e.message || "操作失败"); }
                    }}>标记搁置并结束</Button>
                  </Space>
                </Space>
              </Card>
            </Space>}
            {/* 渠道选择 + 内容大纲（Action 确认后） */}
            {currentWorkflowData?.steps.find((s:any)=>s.key==="action")?.done && currentContinueResult && <Card size="small" title="渠道选择与内容大纲">
              {!workflowData.channelDrafts ? <Space direction="vertical" size={8} style={{width:"100%"}}>
                <Text>选择发布渠道（可多选，人工决策，系统不代选）：</Text>
                {channelStrategy && <Card size="small" style={{ background: "#fafafa" }}>
                  <Space direction="vertical" size={6} style={{ width: "100%" }}>
                    <Text strong>内容方向</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>{channelStrategy.content_direction}</Text>
                    <Text strong>平台方向（按信号分层排序）</Text>
                    {channelStrategy.platforms.map((p: any) => <div key={p.key}>
                      <Space size={4} wrap>
                        <Tag color={p.tier === 1 ? "red" : p.tier === 2 ? "orange" : "blue"}>{p.tier_label}</Tag>
                        <Text strong>{p.label}</Text>
                        {(p.content_types || []).length > 0 && <Text type="secondary" style={{ fontSize: 12 }}>适合发{p.content_types.join("、")}</Text>}
                        {p.citation_count > 0 && <Text type="secondary" style={{ fontSize: 12 }}>(引用 {p.citation_count} 次 / {p.citation_run_count} 个 Run，计分 {p.citation_score})</Text>}
                        {p.recommended_answer_citation_count > 0 && <Tag color="green" style={{ fontSize: 11 }}>含推荐答案引用 {p.recommended_answer_citation_count} 次</Tag>}
                      </Space>
                    </div>)}
                    <Text strong>建议执行组合</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>{channelStrategy.combination}</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>排序规则：{channelStrategy.sorting_rule}</Text>
                    {channelStrategy.citation_scoring_rule && <Text type="secondary" style={{ fontSize: 12 }}>{channelStrategy.citation_scoring_rule}</Text>}
                    {(channelStrategy.notes || []).map((n: string, i: number) => <Text key={i} type="secondary" style={{ fontSize: 12 }}>· {n}</Text>)}
                  </Space>
                </Card>}
                <Space wrap>
                  {CHANNEL_BUTTONS.map(([key,label]) =>
                    <Checkbox key={key} checked={draftChannels.includes(key)}
                      onChange={(e)=>setDraftChannels((prev)=>e.target.checked ? [...prev,key] : prev.filter((x:string)=>x!==key))}>
                      {label}
                    </Checkbox>)}
                </Space>
                <Button size="small" type="primary" disabled={draftChannels.length===0} loading={loading} onClick={async()=>{
                  setLoading(true);
                  try{
                    const r = await (await fetch(`/api/optimization/workflow/${projectId}/${currentWorkflowData.prompt_id}/select-channels`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({channels:draftChannels})})).json();
                    const labelMap = Object.fromEntries(CHANNEL_BUTTONS);
                    setWorkflowData({...workflowData, channelDrafts: (r.drafts||[]).map((d:any)=>({...d, channelLabel: labelMap[d.channel] || d.channel}))});
                  message.success(`已为 ${r.drafts?.length||0} 个渠道创建实验草案，逐平台生成内容`);
                  }catch(e:any){message.error(e.message)}
                  finally{setLoading(false)}
                }}>确认选择（{draftChannels.length} 个渠道）</Button>
              </Space> : <Space direction="vertical" size={8} style={{width:"100%"}}>
                {workflowData.channelDrafts.map((d:any)=> <Card key={d.experiment_id} size="small"
                  title={<Space><Tag color="geekblue">{d.channelLabel || d.channel}</Tag><Text strong>实验草案 #{d.experiment_id}</Text><Tag color="orange">等待内容生产</Tag></Space>}>
                  {!d.outline ? <Button size="small" type="primary" loading={loading} onClick={async()=>{
                    setLoading(true);
                    try{
                      const outline = await (await fetch(`/api/optimization/workflow/${projectId}/${currentWorkflowData.prompt_id}/generate-outline`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({channel:d.channel})})).json();
                      setWorkflowData({...workflowData, channelDrafts: workflowData.channelDrafts.map((x:any)=>x.experiment_id===d.experiment_id ? {...x, outline} : x)});
                    }catch(e:any){message.error(e.message)}
                    finally{setLoading(false)}
                  }}>生成内容大纲</Button> : <Space direction="vertical" size={4} style={{width:"100%"}}>
                    <Alert type="success" showIcon message={<Space><Text strong>内容大纲</Text><Tag>{d.outline.title}</Tag></Space>} />
                    {(d.outline.outline||[]).map((sec:any,i:number)=><div key={i}>
                      <Text strong>{i+1}. {sec.section}</Text>
                      <Text type="secondary" style={{display:"block",fontSize:12}}>依据：{sec.evidence_basis}</Text>
                      <Space wrap>{(sec.key_points||[]).map((kp:string,ki:number)=><Tag key={ki} style={{fontSize:11}}>{kp}</Tag>)}</Space>
                    </div>)}
                    {!d.brief ? <Button size="small" type="primary" loading={loading} onClick={async()=>{
                      setLoading(true);
                      try{
                        const brief = await (await fetch(`/api/optimization/workflow/${projectId}/${currentWorkflowData.prompt_id}/generate-brief`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({channel:d.channel,outline:d.outline})})).json();
                        setWorkflowData({...workflowData, channelDrafts: workflowData.channelDrafts.map((x:any)=>x.experiment_id===d.experiment_id ? {...x, brief} : x)});
                      }catch(e:any){message.error(e.message)}
                      finally{setLoading(false)}
                    }}>生成详细内容 Brief</Button> : <Space direction="vertical" size={4} style={{width:"100%"}}>
                      <Alert type="success" showIcon message={<Text strong>详细内容 Brief</Text>} />
                      {(d.brief.sections||[]).map((sec:any,i:number)=><Card key={i} size="small" title={sec.section}>
                        <Text type="secondary" style={{display:"block"}}>写作要求：{sec.writing_requirements}</Text>
                        <Text type="secondary" style={{display:"block"}}>可核验事实：{(sec.facts_to_include||[]).join("；")}</Text>
                        <Text type="secondary" style={{display:"block"}}>事实来源：{sec.facts_source}</Text>
                        {sec.competitor_reference_only && <Tag color="orange" style={{marginTop:4}}>竞品参照（仅市场参照）：{sec.competitor_reference_only}</Tag>}
                      </Card>)}
                    </Space>}
                  </Space>}
                </Card>)}
              </Space>}
            </Card>}
          </Card>}
          {fallback && <Alert type="warning" showIcon message="聚合接口尚未返回数据，当前看板由已有采集记录实时兼容汇总。" />}
          <Row gutter={[16, 16]}>
            <Col xs={12} lg={4}><Card size="small"><Statistic title={activePromptId ? "当前问题" : "配置问题数"} value={dashboard.prompts.total} /></Card></Col>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="已采集的问题" value={dashboard.prompts.executed} suffix={`/ ${dashboard.prompts.total} 个`} /></Card></Col>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="问题组" value={activePromptId ? (scopedPrompt?.prompt_group || "未分组") : dashboard.prompts.clusters} /></Card></Col>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="成功采集" value={dashboard.prompts.valid_runs} suffix="次" /></Card></Col>
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
          {scopedPrompt && <PromptScopeAlert prompt={scopedPrompt} description="以下仅展示该 Prompt 的决策诊断；切回「全部 Prompt」查看项目整体。" />}
          {projectId && currentWorkflowData && <Card size="small" title={<Space><Text strong>决策诊断主路径</Text><Tag>{currentWorkflowData.prompt_id ? `Prompt #${currentWorkflowData.prompt_id}` : ""}</Tag></Space>} extra={answerStepBlocked ? <Tag color="gold">需要先修正识别对象</Tag> : <Button size="small" onClick={()=>setWorkflowReviewOpen(true)}>进入审核</Button>}>
            <Space direction="vertical" size={8} style={{width:"100%"}}>
              {answerStepBlocked && <Alert
                type="warning"
                showIcon
                message="答案里有推荐对象，但机器没有形成有效的答案决策识别"
                description="请先在下方确认这些对象是目标品牌、竞品，还是不进入决策。确认后系统会刷新当前 Prompt 的主链路；不要再进入空审核工作台。"
              />}
              {/* Section 1: Decision Market */}
              <Text strong>答案决策对象</Text>
              {decisionMarketUnknownEntities.length > 0 && <Alert
                type="info"
                showIcon
                message={`有 ${decisionMarketUnknownEntities.length} 个推荐对象待确认`}
                description="一般先确认竞品/候选品牌；如果是你自己的品牌或别名，选择「设为目标品牌」；明显不是品牌或方案对象时选择「不进入决策」。"
              />}
              <Table size="small" rowKey="entity_text" pagination={false}
                dataSource={decisionMarketEntities}
                columns={[
                  {title:"实体",dataIndex:"entity_text",width:120,render:(v:string)=><Text strong>{v}</Text>},
                  {title:"关系",width:130,render:(_:any,r:any)=><Tag color={decisionEntityRelationshipColor(r.relationship)}>{r.relationship_label || decisionEntityRelationshipLabel(r.relationship)}</Tag>},
                  {title:"行为",width:120,render:(_:any,r:any)=><Tag>{r.speech_act_label || speechActLabel(r.speech_act)}</Tag>},
                  {title:"覆盖",width:80,render:(_:any,r:any)=><Text>{r.run_coverage}</Text>},
                  {title:"机器状态",width:190,render:(_:any,r:any)=><Space wrap size={4}>{Object.entries(r.review_status_counts || {}).map(([status,count]:any)=><Tag key={status}>{reviewStatusLabel(status)}：{count}</Tag>)}</Space>},
                  {title:"理由数",width:70,render:(_:any,r:any)=><Text>{r.reasons.length}</Text>},
                  {title:"修正",width:260,render:(_:any,r:any)=>(r.relationship==="UNKNOWN_ENTITY" || answerStepBlocked) ? <Space wrap size={4}>
                    <Button size="small" type="primary" loading={loading} onClick={()=>resolveDecisionMarketEntity(r.entity_text, "CONFIRMED_COMPETITOR")}>确认为竞品</Button>
                    <Button size="small" loading={loading} onClick={()=>resolveDecisionMarketEntity(r.entity_text, "TARGET_BRAND")}>设为目标品牌</Button>
                    <Button size="small" danger loading={loading} onClick={()=>resolveDecisionMarketEntity(r.entity_text, "REJECTED")}>不进入决策</Button>
                  </Space> : <Text type="secondary">已确认</Text>},
                ]} />
              {/* Section 2/3: Winning Reasons + Evidence */}
              {decisionMarketEntities.filter((e:any)=>e.reasons.length>0).map((e:any)=><Card key={e.entity_text} size="small" title={<Space><Text strong>{e.entity_text} 为什么进入答案？</Text><Tag>{e.speech_act_label || speechActLabel(e.speech_act)}</Tag></Space>}>
                {e.reasons.map((r:any,ri:number)=><div key={ri} style={{marginBottom:8}}>
                  <Space><Text strong>R{ri+1}：{r.normalized_reason}</Text><Tag color={r.review_status==="HUMAN_CONFIRMED"?"green":"orange"}>{r.review_status==="HUMAN_CONFIRMED"?"已确认":"待审"}</Tag></Space>
                  <Text type="secondary" style={{display:"block",fontSize:12}}>原文：{r.reason_span}</Text>
                  <Space wrap>{(r.supporting_claims||[]).map((sc:any,i:number)=><Tag key={i} color="green" style={{fontSize:11}}>SUPPORTS: {sc.normalized_claim?.slice(0,40)}</Tag>)}</Space>
                </div>)}
              </Card>)}
              {/* Section 4: Target Gap */}
              {currentContinueResult?.gap && <Alert type="warning" showIcon
                message={<Space wrap><Text strong>目标品牌缺口</Text><Tag>{decisionDisplayText(currentContinueResult.gap.gap_type)}</Tag><Tag>{decisionDisplayText(currentContinueResult.gap.confidence)}</Tag><Button size="small" onClick={() => { setWorkflowEvidenceDrawerFocus("gap"); setWorkflowEvidenceDrawerOpen(true); }}>查看依据</Button></Space>}
                description={currentContinueResult.gap.basis} />}
              <Button size="small" type="primary" onClick={()=>setPage("optimization")}>查看执行策略</Button>
            </Space>
          </Card>}
          <Card title="历史分析（V1 规则版）" extra={<Tag color="default">只读 · 已弃用于当前决策</Tag>}>
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
                options={(activePromptId ? prompts.filter((prompt) => prompt.id === activePromptId) : prompts).map((prompt) => ({ value: prompt.id, label: `#${prompt.id} ${prompt.prompt_text}` }))}
              />
              <Button type="primary" loading={recommendationLoading} onClick={() => runRecommendationAnalysis(activePromptId ?? null)}>
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
            {!recommendationData ? <Empty description={activePromptId ? "该 Prompt 还没有决策诊断，点击「生成诊断」创建第一版" : "选择一个已有采集记录的问题，然后生成决策诊断"} /> : <Space direction="vertical" size={12} style={{ width: "100%" }}>
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
                      <Descriptions.Item label="主要缺口">{targetBrandPosition.primary_gap?.gap_type_label || decisionMarket.primary_gap?.gap_type_label || "-"}</Descriptions.Item>
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
                        { title: "产品事实", width: 150, render: (_, row: any) => <Tag color={row.product_truth_status === "SUPPORTED" ? "green" : row.product_truth_status === "NOT_SUPPORTED" ? "red" : "gold"}>{row.product_truth_status_label || truthStatusLabel(row.product_truth_status)}</Tag> },
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
                          {(row.representative_sources || []).map((source: any) => <a key={source.reference_id} href={sourceActionUrl(source.url, source.canonical_url, source.action_url)} target="_blank" rel="noreferrer">{source.title || displaySourceUrl(source.url, source.canonical_url)}</a>)}
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
                    ? `当前主要缺口：${decisionMarket.primary_gap.gap_type_label || decisionMarket.primary_gap.gap_type}。${decisionMarket.primary_gap.diagnosis_text || ""}`
                    : "若没有主要缺口，说明当前品牌选择空间或产品事实还不足以支持明确策略判断。"}
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
                              <a href={sourceActionUrl(item.source_url, item.source_canonical_url, item.source_action_url)} target="_blank" rel="noreferrer">{item.source_title || displaySourceUrl(item.source_url, item.source_canonical_url) || "未知来源"}</a>
                              <Space size={4}><Tag color={item.evidence_status === "LINKED" ? "green" : item.evidence_status === "UNLINKED" ? "red" : "gold"}>{evidenceStatusLabel(item.evidence_status, item.evidence_status_label)}</Tag><Text type="secondary">{displaySourceDomain(item.source_domain, item.source_url, item.source_canonical_url)}</Text></Space>
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
                        { title: "引用页面", render: (_, row: any) => <Space direction="vertical" size={0}><a href={sourceActionUrl(row.url, row.canonical_url, row.action_url)} target="_blank" rel="noreferrer">{row.title || displaySourceUrl(row.url, row.canonical_url)}</a><Text type="secondary">{displaySourceDomain(row.domain, row.url, row.canonical_url)}</Text></Space> },
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
                        { title: "来源", width: 220, render: (_, row: any) => <Space direction="vertical" size={0}><a href={sourceActionUrl(row.source_url, row.source_canonical_url, row.source_action_url)} target="_blank" rel="noreferrer">{row.source_title || displaySourceUrl(row.source_url, row.source_canonical_url) || "未知来源"}</a><Text type="secondary">{displaySourceDomain(row.source_domain, row.source_url, row.source_canonical_url)}</Text></Space> },
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
                          { title: "来源", width: 260, render: (_, row: any) => row.source_url ? <Space direction="vertical" size={0}><a href={sourceActionUrl(row.source_url, row.source_canonical_url, row.source_action_url)} target="_blank" rel="noreferrer">{row.source_title || displaySourceUrl(row.source_url, row.source_canonical_url)}</a><Text type="secondary">{displaySourceDomain(row.source_domain, row.source_url, row.source_canonical_url)}</Text></Space> : <Text type="secondary">暂无来源段落</Text> },
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
                  description="确认理由前，系统只把它作为规则抽取结果；确认后才能更稳妥地用于产品事实核对和策略路由。"
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
                        { title: "来源", width: 260, render: (_, row: any) => <Space direction="vertical" size={2}><a href={sourceActionUrl(row.url, row.canonical_url, row.action_url)} target="_blank" rel="noreferrer">{row.title || displaySourceUrl(row.url, row.canonical_url)}</a><Text type="secondary">{displaySourceDomain(row.domain, row.url, row.canonical_url)}</Text></Space> },
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
                        description={interventionFeasibility.boundary_note || "干预候选不是执行命令；只有人工审核后的有效执行内容通过校验，才能物化为动作和实验。"}
                      />
                      <Descriptions size="small" column={1}>
                        <Descriptions.Item label="机会类型">{decisionMarket.action_package.opportunity_type_label}</Descriptions.Item>
                        <Descriptions.Item label="资产决策">{decisionMarket.action_package.asset_decision_label}</Descriptions.Item>
                        <Descriptions.Item label="推荐干预">{promptInterventionCandidates[0]
                          ? `${interventionTypeLabel(promptInterventionCandidates[0].intervention_type)}，执行字段：${decisionDisplayText(promptInterventionCandidates[0].target_platform) || "待确认"} / ${decisionDisplayText(promptInterventionCandidates[0].target_asset) || "待确认"}`
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
                      <Alert type="warning" showIcon message="这里不产出最终策略。点击下方按钮只会生成待审核策略候选；不会直接创建动作或实验。" />
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
                        <Descriptions.Item label="主要缺口">{item.primary_gap_type_label || item.competitive_gap_type_label || "-"}</Descriptions.Item>
                        <Descriptions.Item label="当前问题">{item.observed_problem || item.observed_market_problem || "-"}</Descriptions.Item>
                        <Descriptions.Item label="建议方向">{item.recommended_direction || item.target_decision_position || "-"}</Descriptions.Item>
                        <Descriptions.Item label="执行字段">平台：{decisionDisplayText(item.target_platform) || "待确认"}；资产：{decisionDisplayText(item.target_asset) || "待确认"}；URL：{item.target_url || "未确认"}</Descriptions.Item>
                        <Descriptions.Item label="候选 URL">{item.suggested_target_url ? `${item.suggested_target_url}（${item.suggested_target_url_note || "仅供人工审核"}）` : "待人工确认"}</Descriptions.Item>
                        <Descriptions.Item label="证据前提">{(item.evidence_prerequisites || item.required_evidence || []).join("；") || "待补充"}</Descriptions.Item>
                        <Descriptions.Item label="执行边界">{decisionDisplayText(item.execution_boundary) || "策略候选 -> 人工审核 -> 有效执行内容通过校验 -> 动作 -> 实验"}</Descriptions.Item>
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
          {scopedPrompt && <PromptScopeAlert prompt={scopedPrompt} description="以下仅展示该 Prompt 的执行策略；切回「全部 Prompt」查看项目整体。" />}
          {projectId && citationTargetPromptId && <Card
            size="small"
            title={<Space wrap><ShieldCheck size={16} /><Text strong>引用证据与策略确认详情</Text><Tag>问题 #{citationTargetPromptId}</Tag>{currentCitationDecisionData?.evidence_package_id && <Tag color="blue">证据 #{currentCitationDecisionData.evidence_package_id}</Tag>}</Space>}
            extra={<Space wrap>
              <Tag color={citationDecisionStatusColor(currentCitationDecisionData?.status)}>{citationDecisionStatusLabel(currentCitationDecisionData?.status)}</Tag>
              <Button size="small" icon={<RefreshCw size={14} />} loading={citationDecisionLoading} disabled={!answerStepDone} onClick={() => loadCitationDecisionV1(citationTargetPromptId, false)}>重新运行链路</Button>
              <Button size="small" type="primary" disabled={!currentCitationCanConfirm} loading={citationDecisionLoading} onClick={confirmCitationDecisionV1}>生成策略候选</Button>
            </Space>}
          >
            <Space direction="vertical" size={12} style={{ width: "100%" }}>
              {!answerStepDone && <Alert
                type={answerStepBlocked ? "warning" : "info"}
                showIcon
                message={answerStepBlocked ? "请先修正答案决策识别" : "请先完成答案决策识别"}
                description={answerStepBlocked
                  ? (answerSemanticStep?.detail || "当前 Prompt 没有形成有效的品牌/方案选择事件，不能继续进入引用证据、对标来源、缺口和动作。")
                  : "引用证据链路必须基于当前 Prompt 已成立的答案决策识别结果运行。"}
              />}
              <Alert
                type={citationProductTruthBlockedRows.length ? "warning" : currentCitationCanConfirm ? "success" : "info"}
                showIcon
                message={citationProductTruthBlockedRows.length
                  ? "链路已跑到对标来源，但产品事实未匹配，暂不生成策略候选"
                  : currentCitationCanConfirm
                    ? "已有可生成策略候选的内容/证据缺口"
                    : !evidenceReviewDone
                      ? "当前证据仍需人工审核，暂不进入策略确认"
                      : !citationGapDecisionDone
                        ? "当前缺口诊断尚未完成，暂不进入策略确认"
                        : "当前没有可生成策略候选的缺口，系统不会用引用显著性或历史相关标记强行生成策略"}
                description={decisionDisplayText(citationSummary.boundary_note) || "这里展示 引用来源 → 对标来源 → 缺口 → 策略确认 → 实验草案 的纵向链路；目标品牌事实未确认前只允许人工补事实，不允许自动出执行策略。"}
              />
              {citationDecisionError && <Alert
                type="error"
                showIcon
                message="引用资料优化决策未能加载"
                description={citationDecisionError}
              />}
              <Steps size="small" current={currentCitationCanConfirm || currentStrategyCandidateCount ? 4 : citationProductTruthBlockedRows.length ? 2 : currentCitationDecisionData ? 3 : 0} items={citationStepItems} />
              <Row gutter={[12, 12]}>
                <Col xs={12} md={6}><Statistic title="来源数" value={citationLoaded ? citationSummary.source_count ?? 0 : "-"} /></Col>
                <Col xs={12} md={6}><Statistic title="核心对标" value={citationLoaded ? citationSummary.primary_benchmark_count ?? 0 : "-"} /></Col>
                <Col xs={12} md={6}><Statistic title="策略候选线索" value={citationLoaded ? citationSummary.recommended_action_count ?? 0 : "-"} /></Col>
                <Col xs={12} md={6}><Statistic title="渠道机会" value={citationLoaded ? citationSummary.channel_opportunity_count ?? 0 : "-"} /></Col>
              </Row>
              {decisionStability && <Alert
                type={decisionStability.stability_level === "HIGH_VOLATILITY" ? "warning" : "info"}
                showIcon
                message={<Space wrap><Text strong>决策稳定性：{decisionStability.decision_stability_score}/100</Text><Tag color={decisionStabilityLevelColor(decisionStability.stability_level)}>{decisionStability.stability_level_label}</Tag><Tag>只读观察</Tag></Space>}
                description={`有效样本 ${decisionStability.valid_run_count} Runs；品牌决策发生 ${decisionStability.brand_decision_run_count}/${decisionStability.valid_run_count}；主要推荐对象：${dominantOutcomeText(decisionStability.dominant_recommendation_outcome)}。该指标不改变当前证据、对标、缺口、策略、动作或实验结果。`}
              />}
              <Card
                size="small"
                title={<Space wrap><Text strong>操作台</Text>{citationProductTruthBlockedRows.length > 0 && <Tag color="gold">{citationProductTruthBlockedRows.length} 条需要产品事实</Tag>}</Space>}
                extra={<Space wrap>
                  <Button size="small" icon={<RefreshCw size={14} />} loading={citationDecisionLoading} disabled={!answerStepDone} onClick={() => loadCitationDecisionV1(citationTargetPromptId, false)}>重新运行</Button>
                  <Button size="small" type="primary" disabled={!currentCitationCanConfirm} loading={citationDecisionLoading} onClick={confirmCitationDecisionV1}>生成策略候选</Button>
                </Space>}
              >
                <Alert
                  type={citationProductTruthBlockedRows.length > 0 ? "warning" : currentCitationCanConfirm ? "success" : "info"}
                  showIcon
                  style={{ marginBottom: 12 }}
                  message={citationProductTruthBlockedRows.length > 0
                    ? `下一步：确认${project?.brand_name || "目标品牌"}是否真实具备同等能力`
                    : currentCitationCanConfirm
                      ? "下一步：生成策略候选并人工审核"
                      : !evidenceReviewDone
                        ? "下一步：先完成人工证据审核"
                        : !citationGapDecisionDone
                          ? "下一步：先生成当前缺口诊断"
                          : "当前没有可生成策略候选的缺口，可补产品事实后重新运行"}
                  description={`这里确认的是${project?.brand_name || "目标品牌"}自己的产品能力，不是确认对标文章或竞品是否具备能力。若事实来源需要写官网/文档 URL，请用下方表单补充；补完后系统会自动重跑链路。`}
                />
                <Form
                  form={citationTruthForm}
                  layout="vertical"
                  onFinish={submitCitationProductTruth}
                  initialValues={{ product_truth_status: "SUPPORTED" }}
                >
                  <Row gutter={[12, 0]}>
                    <Col xs={24} md={8}>
                      <Form.Item name="capability_label" label="目标品牌真实能力" rules={[{ required: true, message: "请填写真实能力名称" }]}>
                        <Input placeholder={`例如：${project?.brand_name || "目标品牌"}支持抖音跳转微信完整路径搭建`} />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={5}>
                      <Form.Item name="product_truth_status" label="支持状态" rules={[{ required: true }]}>
                        <Select options={[
                          { label: "真实支持", value: "SUPPORTED" },
                          { label: "部分支持", value: "PARTIALLY_SUPPORTED" },
                          { label: "不支持", value: "NOT_SUPPORTED" },
                          { label: "未知，待确认", value: "UNKNOWN" },
                        ]} />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={6}>
                      <Form.Item name="source_reference" label="事实来源">
                        <Input placeholder="官网 URL / 文档 / 人工说明" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={5}>
                      <Form.Item name="note" label="备注">
                        <Input placeholder="可选" />
                      </Form.Item>
                    </Col>
                    <Col xs={24}>
                      <Space wrap>
                        <Button type="primary" htmlType="submit" loading={citationDecisionLoading}>补充产品事实并重跑</Button>
                        <Button onClick={() => citationTruthForm.resetFields(["capability_label", "source_reference", "note"])}>清空表单</Button>
                        <Text type="secondary">也可以在下方对标来源表格点「带入表单」先填草稿，或直接点行内按钮确认。</Text>
                      </Space>
                    </Col>
                  </Row>
                </Form>
              </Card>
              <Table
                size="small"
                rowKey={(row: any) => `${row.url || row.title}-${row.benchmark_tier}`}
                loading={citationDecisionLoading}
                pagination={{ pageSize: 5 }}
                dataSource={citationBenchmarkRows}
                locale={{ emptyText: currentCitationDecisionData ? "当前没有核心/辅助对标来源；这是允许的，不会强行挑选来源。" : "当前 Prompt 尚未加载引用资料优化决策，或缺少 Evidence Package" }}
                columns={[
                  { title: "对标来源", render: (_, row: any) => <Space direction="vertical" size={0}><a href={sourceActionUrl(row.url, row.canonical_url, row.action_url)} target="_blank" rel="noreferrer">{row.title || displaySourceUrl(row.url, row.canonical_url) || "未知来源"}</a><Text type="secondary">{displaySourceDomain(row.domain, row.url, row.canonical_url)}</Text></Space> },
                  { title: "待确认能力", width: 180, render: (_, row: any) => <Text>{citationCapabilityDraftFromRow(row)}</Text> },
                  { title: "层级", width: 110, render: (_, row: any) => <Tag color={row.benchmark_tier === "PRIMARY_BENCHMARK" ? "green" : "blue"}>{benchmarkTierLabel(row.benchmark_tier)}</Tag> },
                  { title: "决策支撑", width: 140, render: (_, row: any) => <Tag>{decisionSupportLabel(row.decision_support_level)}</Tag> },
                  { title: "缺口状态", width: 180, render: (_, row: any) => <Space direction="vertical" size={0}><Tag color={row.gap_analysis_status === "BLOCKED" ? "orange" : row.source_gap_type ? "blue" : "default"}>{sourceGapLabel(row.source_gap_type)}</Tag><Text type="secondary">{gapPreconditionLabel(row.source_gap_precondition)}</Text></Space> },
                  { title: "目标品牌事实", width: 135, render: (_, row: any) => <Tag color={row.matched_product_truth_status === "TRUE" ? "green" : row.matched_product_truth_status === "FALSE" ? "red" : "gold"}>{productTruthMatchLabel(row.matched_product_truth_status)}</Tag> },
                  { title: "优先级", width: 115, render: (_, row: any) => <Tag color={row.priority_level === "PRIORITY_HIGH" ? "red" : row.priority_level === "PRIORITY_MEDIUM" ? "orange" : row.priority_level === "UNRESOLVED" ? "gold" : "default"}>{priorityLevelLabel(row.priority_level)}</Tag> },
                  { title: "动作路径", width: 115, render: (_, row: any) => <Tag>{actionRouteLabel(row.action_route)}</Tag> },
                  { title: "确认目标品牌", width: 330, render: (_, row: any) => {
                    const capabilityLabel = citationCapabilityDraftFromRow(row);
                    const matchedStatus = row.matched_product_truth_status;
                    const fillForm = (status?: string) => {
                      citationTruthForm.setFieldsValue({
                        capability_label: capabilityLabel,
                        product_truth_status: status || (row.source_gap_type === "PRODUCT_GAP" ? "NOT_SUPPORTED" : "SUPPORTED"),
                        source_reference: "",
                        note: `由对标来源带入，请人工改成${project?.brand_name || "目标品牌"}真实能力后提交。触发来源：${row.url || row.title || "未知来源"}`,
                      });
                      message.info(`已带入表单，请确认这是${project?.brand_name || "目标品牌"}真实能力后再提交`);
                    };
                    if (matchedStatus === "TRUE" || matchedStatus === "FALSE") {
                      return <Space wrap size={4}>
                        <Tag color={matchedStatus === "TRUE" ? "green" : "red"}>{matchedStatus === "TRUE" ? "已确认支持" : "已确认不支持"}</Tag>
                        <Button size="small" onClick={() => fillForm(matchedStatus === "TRUE" ? "SUPPORTED" : "NOT_SUPPORTED")}>修改事实</Button>
                      </Space>;
                    }
                    return <Space wrap size={4}>
                      <Button size="small" onClick={() => fillForm()}>带入表单</Button>
                      <Popconfirm
                        title={`确认${project?.brand_name || "目标品牌"}真实支持这项能力？`}
                        description={`将写入目标品牌事实：${capabilityLabel}。如需补事实来源，请先点「带入表单」。`}
                        okText="确认支持"
                        cancelText="取消"
                        onConfirm={() => confirmCitationRowProductTruth(row, "SUPPORTED")}
                      >
                        <Button size="small" type="primary">支持</Button>
                      </Popconfirm>
                      <Popconfirm
                        title={`确认${project?.brand_name || "目标品牌"}只部分支持这项能力？`}
                        description={`将写入目标品牌事实：${capabilityLabel}。`}
                        okText="确认部分支持"
                        cancelText="取消"
                        onConfirm={() => confirmCitationRowProductTruth(row, "PARTIALLY_SUPPORTED")}
                      >
                        <Button size="small">部分支持</Button>
                      </Popconfirm>
                      <Popconfirm
                        title={`确认${project?.brand_name || "目标品牌"}不支持这项能力？`}
                        description={`将写入目标品牌事实：${capabilityLabel}。产品缺口后续会走产品评估，不会生成虚假内容。`}
                        okText="确认不支持"
                        cancelText="取消"
                        onConfirm={() => confirmCitationRowProductTruth(row, "NOT_SUPPORTED")}
                      >
                        <Button size="small" danger>不支持</Button>
                      </Popconfirm>
                    </Space>;
                  } },
                ]}
                expandable={{
                  expandedRowRender: (row: any) => <Space direction="vertical" size={8} style={{ width: "100%" }}>
                    <Descriptions size="small" column={{ xs: 1, md: 2 }}>
                      <Descriptions.Item label="待确认能力">{citationCapabilityDraftFromRow(row)}</Descriptions.Item>
                      <Descriptions.Item label="正文状态">{contentStatusLabel(row.content_status)}</Descriptions.Item>
                      <Descriptions.Item label="引用显著性">{citationProminenceLabel(row.citation_prominence_level)}</Descriptions.Item>
                      <Descriptions.Item label="支撑对齐记录">{(row.supporting_alignment_ids || []).join("，") || "-"}</Descriptions.Item>
                      <Descriptions.Item label="矛盾证据">{row.has_contradiction ? "存在" : "未发现"}</Descriptions.Item>
                      <Descriptions.Item label="品牌资产状态">{existingAssetStatusLabel(row.existing_asset_status)}</Descriptions.Item>
                      <Descriptions.Item label="品牌资产覆盖">{existingAssetCoverageLabel(row.existing_asset_coverage)}</Descriptions.Item>
                    </Descriptions>
                    {row.source_gap_reason && <Alert type="info" showIcon message="缺口说明" description={decisionDisplayText(row.source_gap_reason)} />}
                    {(row.decision_support_basis || []).length > 0 && <Text type="secondary">决策支撑依据：{row.decision_support_basis.map((item: string) => decisionDisplayText(item)).join("；")}</Text>}
                    {(row.benchmark_basis || []).length > 0 && <Text type="secondary">对标依据：{row.benchmark_basis.map((item: string) => decisionDisplayText(item)).join("；")}</Text>}
                  </Space>
                }}
              />
              {citationRecommendedActions.length > 0 && <Card size="small" title="可生成策略候选的干预线索">
                <Space direction="vertical" size={8} style={{ width: "100%" }}>
                  {citationRecommendedActions.map((action: any) => <Alert
                    key={action.action_key || action.summary}
                    type={action.route === "CONTENT" || action.route === "EVIDENCE" ? "success" : "warning"}
                    showIcon
                    message={<Space wrap><Tag>{actionRouteLabel(action.route)}</Tag><Text strong>{decisionDisplayText(action.summary)}</Text></Space>}
                    description={<Space direction="vertical" size={2}><Text>{decisionDisplayText(action.rationale)}</Text><Text type="secondary">内容要求：{(action.content_requirements || []).map((item: string) => decisionDisplayText(item)).join("；") || "-"}</Text></Space>}
                  />)}
                </Space>
              </Card>}
              {citationChannelOpportunities.length > 0 && <Card size="small" title="渠道机会（证据 shortlist）">
                <Space wrap>
                  {citationChannelOpportunities.map((item: any) => <Tag key={item.platform || item.channel || item.label} color="blue">{item.platform_label || item.platform || item.channel || item.label}</Tag>)}
                </Space>
              </Card>}
            </Space>
          </Card>}
          {projectId && !currentWorkflowData && <Alert type="info" showIcon
            message={activePromptId ? `Prompt #${activePromptId} 暂无执行策略主路径数据` : "暂无执行策略主路径数据"}
            description={activePromptId ? "该 Prompt 还没有完成机器分析（或尚未开始审核流程），请先在监测总览推进该 Prompt 的工作流。" : "项目还没有机器分析进度；选择具体 Prompt 或在监测总览推进工作流后，这里会展示对应内容。"} />}
          {projectId && currentWorkflowData && <Card size="small" title={<Space><ShieldCheck size={16}/><Text strong>历史执行记录</Text><Tag>{currentWorkflowData.prompt_id ? `Prompt #${currentWorkflowData.prompt_id}` : "未选择"}</Tag><Tag color="default">不计入当前 Citation V1 进度</Tag></Space>}>
            <Space direction="vertical" size={8} style={{width:"100%"}}>
              {/* Confirmed Gap */}
              {currentWorkflowData.continueResult?.gap && <Alert type="warning" showIcon
                message={<Space wrap><Text strong>历史缺口：{decisionDisplayText(currentWorkflowData.continueResult.gap.gap_type)}</Text><Tag>{decisionDisplayText(currentWorkflowData.continueResult.gap.confidence)}</Tag><Button size="small" onClick={() => { setWorkflowEvidenceDrawerFocus("gap"); setWorkflowEvidenceDrawerOpen(true); }}>查看依据</Button></Space>}
                description={currentWorkflowData.continueResult.gap.basis} />}
              {/* Intervention Plan */}
              {!strategyPlan ? <Button size="small" type="primary" loading={loading} onClick={async()=>{
                setLoading(true);
                try{
                  const plan = await (await fetch(`/api/optimization/workflow/${projectId}/${currentWorkflowData.prompt_id}/plan`,{method:"POST"})).json();
                  setStrategyPlan(plan);
                  message.success("Intervention Plan 已创建");
                }catch(e:any){message.error(e.message)}
                finally{setLoading(false)}
              }}>创建执行计划</Button> : <Space direction="vertical" size={8} style={{width:"100%"}}>
                <Alert type="info" showIcon message={<Text strong>执行计划</Text>} description={strategyPlan.objective} />
                {/* 渠道多选 */}
                <Text>选择干预渠道（可多选，每个渠道生成独立实验）：</Text>
                <Space wrap>
                  {channelOptions.map((c:any)=><Button key={c.key} size="small"
                    type={selectedChannels.includes(c.key)?"primary":"default"}
                    onClick={()=>{
                      setSelectedChannels(prev=>prev.includes(c.key)?prev.filter((x:string)=>x!==c.key):[...prev,c.key]);
                    }}>
                    {c.label}（证据 {c.evidence_source_count}）
                  </Button>)}
                </Space>
                {selectedChannels.length>0 && <Button size="small" type="primary" loading={loading} onClick={async()=>{
                  setLoading(true);
                  try{
                    for (const ch of selectedChannels) {
                      await fetch(`/api/optimization/workflow/${projectId}/${currentWorkflowData.prompt_id}/experiments`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({channel:ch})});
                    }
                    const exps = await (await fetch(`/api/optimization/workflow/${projectId}/${currentWorkflowData.prompt_id}/experiments`)).json();
                    setStrategyExperiments(exps);
                    message.success(`已为 ${selectedChannels.length} 个渠道创建实验`);
                  }catch(e:any){message.error(e.message)}
                  finally{setLoading(false)}
                }}>为选中渠道创建实验（{selectedChannels.length}）</Button>}
              </Space>}
              {/* Experiments 列表 */}
              {strategyExperiments.length>0 && <Space direction="vertical" size={8} style={{width:"100%"}}>
                <Text strong>实验列表（一个渠道一个）</Text>
                {strategyExperiments.map((e:any)=><Card key={e.id} size="small" title={<Space><Tag color="geekblue">{e.channel}</Tag><Text>实验 #{e.id}</Text><Tag color={e.status==="RELEASED"?"green":"orange"}>{experimentStatusLabel(e.status)}</Tag></Space>} extra={<Space>
                  <Button size="small" onClick={async()=>{
                    const bm = await (await fetch(`/api/optimization/workflow/experiments/${e.id}/benchmark`)).json();
                    setStrategyBenchmarks({...strategyBenchmarks, [e.id]: bm});
                  }}>对标内容</Button>
                  {e.status==="draft" && <Button size="small" type="primary" onClick={async()=>{
                    const r = await (await fetch(`/api/optimization/workflow/experiments/${e.id}/release`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({release_url:prompt("请填写真实发布 URL：")||""})})).json();
                    if (r.status) {
                      const exps = await (await fetch(`/api/optimization/workflow/${projectId}/${currentWorkflowData.prompt_id}/experiments`)).json();
                      setStrategyExperiments(exps);
                      message.success("已确认发布，进入复测阶段");
                    }
                  }}>确认已发布</Button>}
                  {e.status==="RELEASED" && <Button size="small" type="primary" onClick={async()=>{
                    const raw = prompt("请填写复测 Run IDs（逗号分隔）：")||"";
                    const ids = raw.split(",").map((s:string)=>Number(s.trim())).filter(Boolean);
                    const r = await (await fetch(`/api/optimization/workflow/experiments/${e.id}/retest`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({post_run_ids:ids})})).json();
                    if (r.status) {
                      const exps = await (await fetch(`/api/optimization/workflow/${projectId}/${currentWorkflowData.prompt_id}/experiments`)).json();
                      setStrategyExperiments(exps);
                      message.success("复测 Runs 已挂载");
                    }
                  }}>挂载复测 Runs</Button>}
                  {e.status==="RETESTED" && <Button size="small" type="primary" onClick={async()=>{
                    const o = await (await fetch(`/api/optimization/workflow/experiments/${e.id}/outcome`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({})})).json();
                    setStrategyOutcomes({...strategyOutcomes, [e.id]: o});
                    message.success("Outcome 已生成");
                  }}>生成 Outcome</Button>}
                </Space>}>
                  <Text type="secondary" style={{display:"block"}}>{e.hypothesis}</Text>
                  {strategyBenchmarks[e.id] && <Space direction="vertical" size={4} style={{marginTop:8, width:"100%"}}>
                    <Text strong>对标内容（定性 Checklist，不评分）：</Text>
                    <Text type="secondary">已覆盖：{(strategyBenchmarks[e.id].benchmark_covered||[]).map((x:any)=>x.text).join("；")}</Text>
                    <Text type="secondary">观察到不足：{(strategyBenchmarks[e.id].observed_gaps||[]).map((x:any)=>x.text).join("；")}</Text>
                    <Text type="secondary">目标品牌真实增量：{(strategyBenchmarks[e.id].product_truth_advantages||[]).map((x:any)=>x.text).join("；")}</Text>
                    <Text strong>Brief 要求：</Text>
                    {(strategyBenchmarks[e.id].brief_requirements||[]).map((x:any,i:number)=><Text key={i} type="secondary">[ ] {x.text}</Text>)}
                  </Space>}
                  {strategyOutcomes[e.id] && <Alert type="success" showIcon style={{marginTop:8}}
                    message={<Space><Text strong>Outcome</Text><Tag>{strategyOutcomes[e.id].mention_direction}</Tag><Tag>{strategyOutcomes[e.id].recommendation_direction}</Tag></Space>}
                    description={`基线 提及 ${strategyOutcomes[e.id].baseline.mentioned}/${strategyOutcomes[e.id].baseline.total} → 复测 ${strategyOutcomes[e.id].post.mentioned}/${strategyOutcomes[e.id].post.total}。${strategyOutcomes[e.id].sample_note}`} />}
                </Card>)}
              </Space>}
            </Space>
          </Card>}
          <Card size="small" title={<Space><Text strong>历史策略与证据（高级）</Text><Tag color="default">只读</Tag></Space>} extra={<Space>
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
              dataSource={[...prompts].filter((p) => !activePromptId || p.id === activePromptId).sort((a,b)=>(b.id as number)-(a.id as number))}
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
                  options={(evidencePackages||[]).filter((p:any)=>!activePromptId || p.prompt_id===activePromptId).map((p:any)=>({label:`证据 #${p.id} · ${formatDateTime(p.created_at)} ·「${p.prompt_text||'#'+(p.prompt_id||'?')}」· 版本 ${p.version}`,value:p.id}))}
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
                type={workflowStrategyCandidates.length ? "success" : "info"}
                showIcon
                message={<Space><Tag color={workflowStrategyCandidates.length ? "green" : "default"}>{strategyDecisionStatusLabel(strategyData.decision_status)}</Tag><Tag>{strategyCapabilityLabel(strategyData.decision_capability)}</Tag><Text>当前流程 {workflowStrategyCandidates.length} 个策略候选 / 全部 {strategyData.strategy_options_count} 个版本</Text></Space>}
                description={workflowStrategyCandidates.length
                  ? currentStrategySummary(workflowStrategyCandidates)
                  : "当前流程还没有新的策略候选；历史验收策略不计入当前第 7 步。请回到单 Prompt 主链第 7 步点击「生成策略候选」。"}
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
                  <Text type="secondary">当前显示 {visibleStrategyCandidates.length}/{sortedStrategyCandidates.length} 个版本；默认只展示当前流程策略，历史验收策略需切到全部策略查看。</Text>
                </Space>
              </Card>}
              {strategyCandidateFilter === "latest" && visibleStrategyCandidates.length === 0 && <Alert
                type="warning"
                showIcon
                message="当前流程暂无策略候选"
                description="这里只有历史验收留下的策略/实验记录。它们不会让本次主链第 7/8 步自动完成；请回到单 Prompt 工作台第 7 步生成策略候选后再人工确认。"
              />}
              {visibleStrategyCandidates.map((c:any)=>{
                const allCandidates = strategyData.candidates || [];
                const plan = experimentPlanPayload(c.experiment_plan);
                const strategyView = strategyDisplayPayload(c);
                const planPayload = plan.payload || strategyView.payload || c.structured_payload || {};
                const controlled = plan.controlled_intervention || {};
                const audit = plan.known_environment_audit || {};
                const isAccepted = c.review_status === "ACCEPTED" || c.review_status === "ACCEPTED_WITH_EDITS";
                const isAuditHistory = isAuditGeneratedStrategyCandidate(c);
                const isCurrent = !isAuditHistory && workflowStrategyCandidates[0]?.id === c.id;
                const isJustGenerated = latestGeneratedStrategyIds.includes(c.id);
                const planActionId = plan.action_id || plan.action_snapshot?.action_id;
                const planExperimentId = plan.experiment_id || c.experiment_id;
                const hasExperimentDraft = Boolean(planExperimentId || c.experiment_id);
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
                    {isAuditHistory && <Tag color="default">历史验收</Tag>}
                    <Text strong>{interventionTypeLabel(strategyView.interventionType)}</Text>
                  </Space>}
                  extra={<Space wrap>
                    <Text type="secondary">生成 {formatDateTime(c.generated_at || c.created_at)}</Text>
                    <Text type="secondary">更新 {formatDateTime(c.updated_at || c.created_at)}</Text>
                    <Tag color={isAccepted?"green":c.review_status==="PENDING_REVIEW"?"default":"orange"}>{reviewStatusLabel(c.review_status)}</Tag>
                  </Space>}
                >
                <Alert
                  type={isAccepted ? "success" : c.review_status === "PENDING_REVIEW" ? "warning" : "info"}
                  showIcon
                  style={{ marginBottom: 12 }}
                  message={<Space wrap>
                    <Text strong>策略确认链路</Text>
                    <Tag color={isAccepted ? "green" : "orange"}>{isAccepted ? "已人工确认 Strategy" : "机器候选，待人工确认"}</Tag>
                    <Tag color={effectiveValidationStatusColor(c.effective_validation_status)}>{effectiveValidationStatusLabel(c.effective_validation_status)}</Tag>
                    {hasExperimentDraft ? <Tag color="blue">实验草案 #{planExperimentId}</Tag> : <Tag>尚未创建实验草案</Tag>}
                  </Space>}
                  description={isAccepted
                    ? "该策略已经过人工确认并形成 effective_payload；下一步只是在第 8 步确认具体资产、URL、内容结构、Baseline 和 Asset Brief。"
                    : "请先审核这条 StrategyCandidate。确认前它只是机器策略候选，不会创建 Action 或 Experiment。"}
                />
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
                    <Card size="small" title="AI 决策机会" style={{background:"#f6ffed", height:"100%"}}>
                      <Space direction="vertical" size={8} style={{width:"100%"}}>
                        <Text strong>目标变化</Text>
                        <Text>{strategyView.targetDecisionChange || strategyView.actionText || "待确认 AI 决策变化"}</Text>
                        <Text strong>策略假设</Text>
                        <Text type="secondary">{strategyView.strategicHypothesis || strategyView.cause || "待补充策略假设"}</Text>
                        <Text strong>干预机制</Text>
                        <Text type="secondary">{strategyView.interventionMechanism || "待确认干预机制"}</Text>
                      </Space>
                    </Card>
                  </Col>
                  <Col xs={24} md={8}>
                    <Card size="small" title="本轮策略重点" style={{background:"#fff7e6", height:"100%"}}>
                      <Space direction="vertical" size={8} style={{width:"100%"}}>
                        <Text strong>优先能力/理由</Text>
                        {strategyView.priorityCapabilities.length > 0
                          ? strategyView.priorityCapabilities.map((item:any, index:number) => <div key={`${item.gap_item_id || item.capability_label || index}`} style={{borderBottom:"1px solid #f0f0f0", paddingBottom:6}}>
                              <Space wrap>
                                <Tag color={item.priority_band === "P1" ? "red" : "orange"}>{item.priority_band || "待定"}</Tag>
                                <Text>{item.capability_label || "待确认能力"}</Text>
                                <Tag>{sourceGapLabel(item.gap_type)}</Tag>
                                <Tag>{item.reason_run_coverage || `${item.run_coverage_count || 0} Runs`}</Tag>
                              </Space>
                              <div><Text type="secondary">{item.priority_basis || "来自已确认缺口和合格证据链。"}</Text></div>
                            </div>)
                          : <Text type="secondary">旧策略暂无能力级拆解；请重新生成策略候选。</Text>}
                      </Space>
                    </Card>
                  </Col>
                  <Col xs={24} md={8}>
                    <Card size="small" title="计划平台与信号" style={{background:"#e6f7ff", height:"100%"}}>
                      <Space direction="vertical" size={8} style={{width:"100%"}}>
                        {strategyView.primaryInterventionPath && <div>
                          <Text strong>主路径</Text>
                          <div><Text type="secondary">{strategyView.primaryInterventionPath}</Text></div>
                        </div>}
                        {strategyView.plannedChannels.length > 0 && <div>
                          <Text strong>计划平台层</Text>
                          <Space direction="vertical" size={6} style={{width:"100%", marginTop:6}}>
                            {strategyView.plannedChannels.map((item:any, index:number) => <div key={`${item.channel || index}`} style={{borderBottom:"1px solid #f0f0f0", paddingBottom:6}}>
                              <Space wrap>
                                <Tag color={item.intervention_priority === "PRIMARY" ? "blue" : item.intervention_priority === "OBSERVE" ? "default" : "geekblue"}>{item.intervention_priority || "计划"}</Tag>
                                <Text>{item.channel_label || platformLabel(item.channel)}</Text>
                              </Space>
                              <div><Text type="secondary">{item.channel_role || "待确认渠道角色"}</Text></div>
                              <div style={{ marginTop: 4 }}>
                                <Text type="secondary">推荐依据：{item.selection_basis || "由缺口、AI 推荐理由、对标证据、目标品牌事实、品牌资产和检索/引用状态共同判断；不是直接复制对标来源平台。"}</Text>
                              </div>
                            </div>)}
                          </Space>
                        </div>}
                        {strategyView.requiredSignals.length > 0
                          ? strategyView.requiredSignals.map((item:any, index:number) => <Alert
                              key={`${item.capability_label || index}`}
                              type="info"
                              showIcon
                              message={item.signal || `目标品牌明确支持「${item.capability_label || "该能力"}」`}
                              description={item.evidence_requirement || "必须来自目标品牌事实和可摘录资产表达。"}
                            />)
                          : <Text type="secondary">旧策略暂无信号拆解；请重新生成策略候选。</Text>}
                        {strategyView.nonGoals.length > 0 && <div>
                          <Text strong>本步不做</Text>
                          <ul style={{margin:"6px 0 0 18px", padding:0}}>
                            {strategyView.nonGoals.slice(0, 5).map((item: string, index: number) => <li key={index}><Text type="secondary">{item}</Text></li>)}
                          </ul>
                        </div>}
                      </Space>
                    </Card>
                  </Col>
                  <Col xs={24}>
                    <Card size="small" title="第 8 步执行边界（尚未生成 Draft）" style={{background:"#fff"}}>
                      <Descriptions size="small" column={{xs:1, md:2}} items={[
                        {key:"asset",label:"资产方向",children:<Text>{strategyView.assetDirection?.asset_operation === "UPDATE_EXISTING" ? "更新已有资产" : strategyView.assetDirection?.asset_operation === "CREATE_NEW" ? "新建资产 proposal" : "待第 8 步确认"}</Text>},
                        {key:"asset-channel",label:"计划承载平台",children:<Text>{platformLabel(strategyView.assetDirection?.channel)}</Text>},
                        {key:"attr",label:"归因范围",children:<Text>{strategyView.attributionIntent?.attribution_scope === "CAPABILITY_BUNDLE" ? "能力组合" : strategyView.attributionIntent?.attribution_scope === "SINGLE_CAPABILITY" ? "单能力" : "待确认"}</Text>},
                        {key:"primary-capability",label:"主观察能力",children:<Text>{strategyView.attributionIntent?.primary_capability || "待确认"}</Text>},
                      ]}/>
                      {strategyView.executionSequence.length > 0 && <Timeline
                        style={{marginTop:12}}
                        items={strategyView.executionSequence.map((item:any) => ({
                          color: "blue",
                          children: <Space direction="vertical" size={2}>
                            <Text strong>{item.name || `步骤 ${item.step}`}</Text>
                            <Text type="secondary">{item.description || ""}</Text>
                          </Space>
                        }))}
                      />}
                    </Card>
                  </Col>
                  <Col xs={24}>
                    <Card size="small" title="证据依据（用于审计，不等于执行平台）" style={{background:"#fafafa"}}>
                      <Space direction="vertical" size={6} style={{width:"100%"}}>
                        <Text>{strategyView.evidenceSummary || "无"}</Text>
                        <Text type="secondary">推导依据：{strategyView.cause || strategyView.strategicHypothesis || "-"}</Text>
                        {strategyView.strategyBoundaryNote && <Alert type="info" showIcon message="第 7 步边界" description={strategyView.strategyBoundaryNote} />}
                        {c.structured_payload?.evidence_fact_ids?.length>0 && <Text type="secondary">引用事实 ID：{(c.structured_payload.evidence_fact_ids as string[]).join(", ")}</Text>}
                        {strategyView.decisionMarket?.primary_gap?.metric && <Text type="secondary">主指标：{metricLabel(strategyView.decisionMarket.primary_gap.metric.metric)} · {strategyView.decisionMarket.primary_gap.metric.numerator}/{strategyView.decisionMarket.primary_gap.metric.denominator}</Text>}
                      </Space>
                    </Card>
                  </Col>
                  <Col xs={24}>
                    <Card
                      size="small"
                      title="第 8 步入口：执行方案与实验草案"
                      style={{background:"#fff"}}
                      extra={<Space>
                        {!isAccepted && <Button size="small" loading={strategyLoading} disabled={isAuditHistory} onClick={async()=>{
                          setStrategyLoading(true);
                          try{
                            const reviewed = await api.reviewStrategyCandidate(c.id,{review_status:"ACCEPTED",reviewed_by:"human",review_note:"最终策略页人工接受"});
                            updateCandidate(reviewed);
                            await refreshWorkflowStatus();
                            message.success("策略已确认，下一步可配置执行方案");
                          }catch(e:any){message.error(e.message)}
                          finally{setStrategyLoading(false)}
                        }}>确认策略</Button>}
                        <Button type="primary" size="small" loading={strategyLoading || optimizationLoading} disabled={!isAccepted || isAuditHistory} onClick={async()=>{
                          await openExperimentDraftForStrategy(c);
                        }}>{hasExperimentDraft ? "查看实验草案" : isAccepted ? "进入第 8 步配置" : "先确认策略"}</Button>
                      </Space>}
                    >
                      <Alert
                        type="info"
                        showIcon
                        style={{marginBottom:8}}
                        message="第 7 步确认策略候选；第 8 步确认具体执行参数"
                        description={hasExperimentDraft
                          ? "该策略已经创建实验草案。点击「查看实验草案」会打开实验闭环控制台中的对应 Action/Experiment。"
                          : "第 8 步才会人工选择具体账号、URL、资产、标题、段落、内容结构、Baseline 和发布 Gate；没有这些参数时不会假装已创建草案。"}
                      />
                      <Descriptions size="small" column={{xs:1, md:2}} items={[
                        {key:"ready",label:"计划状态",children:<Tag color={readinessStatusColor(plan.readiness_status)}>{readinessStatusLabel(plan.readiness_status)}</Tag>},
                        {key:"experiment",label:"实验编号",children:plan.experiment_id || c.experiment_id ? <Tag color="blue">#{plan.experiment_id || c.experiment_id}</Tag> : <Text type="secondary">尚未生成</Text>},
                        {key:"action",label:"行动编号",children:planActionId ? <Tag color="geekblue">#{planActionId}</Tag> : <Text type="secondary">尚未生成</Text>},
                        {key:"metric",label:"主指标",children:<Text>{metricLabel(controlled.primary_metric || plan.target_metric || planPayload.target_metric || strategyView.targetMetric)}</Text>},
                        {key:"compare",label:"可比性边界",children:<Tag color={comparabilityStatusColor(plan.comparability_status)}>{comparabilityStatusLabel(plan.comparability_status)}</Tag>},
                        {key:"allowed",label:"允许改动",children:<Text>{listText(controlled.allowed_changes || planPayload.changed_features, "按策略中声明的同一机制内容改动")}</Text>},
                        {key:"forbidden",label:"禁止混改",children:<Text>{listText(controlled.forbidden_changes || planPayload.controlled_variables || c.original_llm_payload?.forbidden_changes, "不得同时改采集 Prompt、目标 URL、产品能力、外部平台投放等变量")}</Text>},
                      ]}/>
                      <Alert
                        type={plan.readiness_status === "BLOCKED" || strategyView.executionGate?.blocked_materialization ? "warning" : "info"}
                        showIcon
                        style={{marginTop:8}}
                        message={strategyView.executionGate?.blocked_materialization ? "待人工审核：当前只是策略候选，不能直接生成动作或实验。" : plan.comparability_note || "复采结论只能说明当前观察窗口内的变化，不能声称黑盒 AI 环境严格不变。"}
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
                  dataSource={optimizationIssues.filter((i:any)=>!activePromptId || i.prompt_id===activePromptId)}
                  locale={{ emptyText: activePromptId ? "该 Prompt 暂无实验草案。可先在决策诊断页点击「送入最终策略」生成草案。" : "暂无实验草案。可先在决策诊断页点击「送入最终策略」生成草案。" }}
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
                  ? <Empty description="选择左侧问题后查看动作、实验和复测链路" />
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
                    { title: "操作", width: 80, render: (_, row) => <Popconfirm title="确定删除？该问题的全部采集 Run、引用、事件与关联分析数据将一并删除，不可恢复。" onConfirm={async()=>{
                      try{const r:any = await api.deletePrompt(projectId!,row.id);message.success(`已删除（含 ${r?.runs_deleted ?? 0} 条采集 Run）`);loadProject(projectId!)}
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
          <Card title={<Space>引用资料分析<Tag color="gold">V0 旧诊断分</Tag></Space>} extra={<Text type="secondary">证据 #{rankingData?.package_id} · 规则指纹 {rankingData?.scoring_spec_fingerprint?.slice(0,8)}</Text>}>
            <Alert type="info" showIcon style={{marginBottom:12}}
              message={<span><strong>引用资料分析</strong>展示当前证据内各域名/平台的历史诊断分。<strong>不代表</strong>平台有效性、成功概率或因果关系，也不作为新版策略决策信号。</span>}
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
                    {title:"域名",width:170,render:(_:any,r:any)=><Text>{displaySourceDomain(r.source_domain)}</Text>},
                    {title:"平台",width:90,render:(_:any,r:any)=><Tag>{r.inferred_platform}</Tag>},
                    {title:"旧分",width:65,render:(_:any,r:any)=>(r.raw_evidence_score as number)?.toFixed(1)},
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
                    {title:"旧分",width:65,render:(_:any,r:any)=>(r.avg_raw_evidence_score as number)?.toFixed(1)},
                    {title:"域名数",dataIndex:"domain_count",width:65},
                    {title:"引用次数",dataIndex:"total_citation_occurrences",width:90},
                  ]}
                  expandable={{expandedRowRender:(row:any)=><Space direction="vertical" size={4}>
                    <Text strong>构成域名</Text>
                    {(row.domains as string[])?.map((d:string)=><Tag key={d} color="blue">{displaySourceDomain(d)}</Tag>)}
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
                <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 8 }}
                  message="抓取规则：批量抓取只补抓尚未入库的引用页面；单行「重抓」会重新请求该失败来源并更新失败原因。"
                />
                <Row gutter={12} style={{marginBottom:8}}>
                  <Col span={6}><Tag color="green">正文可用: {goldenData?.docs?.filter((d:any)=>(d.content_status||"")==="CONTENT_VALID").length||0}</Tag></Col>
                  <Col span={6}><Tag color="gold">待补正文: {goldenData?.docs?.filter((d:any)=>(d.content_status||"")==="CONTENT_PENDING").length||0}</Tag></Col>
                  <Col span={6}><Tag color="blue">正文不可用: {goldenData?.docs?.filter((d:any)=>(d.content_status||"")==="CONTENT_UNAVAILABLE").length||0}</Tag></Col>
                  <Col span={6}><Tag color="red">质量不足: {goldenData?.docs?.filter((d:any)=>(d.content_status||"")==="CONTENT_INVALID").length||0}</Tag></Col>
                </Row>
                {goldenData.docs && <Table size="small" rowKey="id" pagination={{pageSize:8}} dataSource={goldenData.docs} columns={[
                  {title:"正文状态",width:95,render:(_,r:any)=>{
                    const actionUrl = sourceActionUrl(r.url, r.canonical_url, r.action_url);
                    if (refetchingSourceUrls.has(actionUrl)) return <Tag color="processing">重抓中</Tag>;
                    return <Tag color={r.content_status==="CONTENT_VALID"?"green":r.content_status==="CONTENT_PENDING"?"gold":r.content_status==="CONTENT_UNAVAILABLE"?"blue":"red"}>{r.content_status_label || (r.fetch_status==="SUCCESS"?"成功":r.fetch_status==="PARTIAL"?"部分":r.fetch_status==="MANUAL_EMPTY"?"空页":"失败")}</Tag>;
                  }},
                  {title:"域名",width:100,render:(_,r:any)=><Text>{displaySourceDomain(r.domain, r.url, r.canonical_url)}</Text>},
                  {title:"链接 / 标题",ellipsis:true,render:(_,r:any)=><a href={sourceActionUrl(r.url, r.canonical_url, r.action_url)} target="_blank" rel="noreferrer" style={{fontSize:12}}>{r.title||displaySourceUrl(r.url, r.canonical_url)}</a>},
                  {title:"字数",width:60,render:(_,r:any)=><Tag>{r.clean_text_len||0}</Tag>},
                  {title:"抓取结果",width:260,render:(_,r:any)=>{
                    const actionUrl = sourceActionUrl(r.url, r.canonical_url, r.action_url);
                    const reason = sourceFailureSummary(r);
                    const latest = sourceRefetchResults[actionUrl];
                    const latestStatus = latest?.status;
                    const latestText = latestStatus === "RUNNING"
                      ? "正在后台浏览器重抓，请稍候..."
                      : latest
                        ? `${latest.fetch_method || "后台抓取"}：${latest.failure_summary || latest.failure_reason || "已完成"}${typeof latest.clean_text_len === "number" ? `（正文 ${latest.clean_text_len} 字）` : ""}`
                        : reason;
                    if (!latestText) return <Text type="secondary">-</Text>;
                    return <Space direction="vertical" size={2}>
                      {reason && latest ? <Text type="secondary" ellipsis={{ tooltip: reason }}>上次：{reason}</Text> : null}
                      <Tag color={latestStatus === "SUCCESS" ? "green" : latestStatus === "RUNNING" ? "processing" : latest ? "gold" : "default"}>
                        {latestStatus === "SUCCESS" ? "本次成功" : latestStatus === "RUNNING" ? "本次进行中" : latest ? "本次结果" : "当前原因"}
                      </Tag>
                      <Text type="secondary" ellipsis={{ tooltip: latestText }}>{latestText}</Text>
                    </Space>;
                  }},
                  {title:"操作",width:140,render:(_,r:any)=>{
                    const actionUrl = sourceActionUrl(r.url, r.canonical_url, r.action_url);
                    const canRefetch = r.content_status !== "CONTENT_VALID" && r.fetch_status !== "MANUAL_EMPTY";
                    const isRefetching = refetchingSourceUrls.has(actionUrl);
                    return <Space size={2}>
                    {r.content_status!=="CONTENT_VALID"&&<Button size="small" onClick={()=>{
                      setManualUrl(sourceActionUrl(r.url, r.canonical_url, r.action_url));
                      setManualEmptyPage(r.fetch_status==="MANUAL_EMPTY");
                    }}>{r.fetch_status==="MANUAL_EMPTY" ? "修改" : "补录"}</Button>}
                    {canRefetch&&<Button size="small" danger loading={isRefetching} disabled={isRefetching} onClick={async()=>{
                      setRefetchingSourceUrls((prev) => new Set(prev).add(actionUrl));
                      setSourceRefetchResults((prev) => ({...prev, [actionUrl]: {status:"RUNNING", failure_summary:"正在后台浏览器重抓，请稍候..."}}));
                      try{
                        const response = await fetch("/api/optimization/golden-case/refetch",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({urls:[actionUrl]})});
                        const payload = await response.json();
                        if (!response.ok) throw new Error(payload?.detail || "重抓失败");
                        const first = payload?.results?.[0];
                        setSourceRefetchResults((prev) => ({...prev, [actionUrl]: first || {status:"UNKNOWN", failure_summary:"重抓完成，但没有返回明细"}}));
                        if(goldenData?.promptId){ await prepareGoldenCaseWorkspace(goldenData.promptId, { skipAcquire: true }); }
                        if (first?.status === "SUCCESS") {
                          message.success(first.failure_summary || "已重新抓取并获得正文");
                        } else {
                          message.warning(first?.failure_summary || "已重新抓取，但仍未获得可分析正文");
                        }
                      }catch(e:any){
                        setSourceRefetchResults((prev) => ({...prev, [actionUrl]: {status:"ERROR", failure_summary:e.message || "重抓请求失败"}}));
                        message.error(e.message);
                      }finally{
                        setRefetchingSourceUrls((prev) => {
                          const next = new Set(prev);
                          next.delete(actionUrl);
                          return next;
                        });
                      }
                    }}>重抓</Button>}
                  </Space>}},
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
                          {title:"引用来源",width:150,render:(_:any,r:any)=><a href={sourceActionUrl(r.doc_url, r.doc_canonical_url, r.doc_action_url)} target="_blank" style={{fontSize:11}}>{r.doc_title||displaySourceUrl(r.doc_url, r.doc_canonical_url)}</a>},
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
        </Space> : <Space direction="vertical" size={16} className="page-stack">
          {scopedPrompt && <PromptScopeAlert prompt={scopedPrompt} description="以下仅展示该 Prompt 的采集记录；切回「全部 Prompt」查看项目全部采样。" />}
          <Card title="采集记录" extra={<Tag>{activePromptId ? `Prompt #${activePromptId} · 每行是一次独立采样` : "每行是一次独立采样"}</Tag>}>
          <Table rowKey="id" loading={loading} dataSource={visibleRuns} locale={{ emptyText: activePromptId ? "该 Prompt 还没有采集记录" : "暂无采集记录" }} pagination={{ pageSize: 12 }} onRow={(row) => ({ onClick: () => openRun(row.id) })} columns={[
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
          </Card>
        </Space>}
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
        {reviewQueue?.status !== "NOT_ANALYZED" && <Alert type="info" showIcon message="机器分析已完成，请按顺序人工确认：先确认答案中的竞品/候选对象，再校验 AI 说法和证据关系。相同答案只审核一次，确认后自动应用到全部采集样本。" />}
        {!reviewQueue && <Button type="primary" loading={loading} onClick={async()=>{
          setLoading(true);
          try{
            const [q, cc] = await Promise.all([
              (await fetch(`/api/optimization/workflow/${projectId}/${currentWorkflowData?.prompt_id}/review-queue`)).json(),
              (await fetch(`/api/optimization/workflow/${projectId}/${currentWorkflowData?.prompt_id}/competitor-candidates`)).json(),
            ]);
            setReviewQueue(q); setCompetitorCandidates(cc);
            if (q?.status !== "NOT_ANALYZED" && (q?.unique_events || []).length === 0 && (q?.alignments || []).length === 0 && (cc || []).length === 0) {
              await refreshWorkflowStatus();
              message.info("当前没有待审核项，主链路状态已刷新");
              setWorkflowReviewOpen(false);
              setReviewQueue(null);
              setCompetitorCandidates([]);
            }
          }catch(e:any){message.error(e.message)}
          finally{setLoading(false)}
        }}>加载待审核项</Button>}
        {reviewQueue?.status==="NOT_ANALYZED" && <Space direction="vertical" size={8} style={{width:"100%"}}>
          <Alert type="warning" showIcon message="该 Prompt 尚未执行机器分析——不是「审核完成」，而是还没有可审核的数据。" />
          <Button type="primary" loading={loading} onClick={async()=>{
            setLoading(true);
            try{
              const pid = currentWorkflowData?.prompt_id;
              const r = await (await fetch(`/api/optimization/workflow/${projectId}/${pid}/run-analysis`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({use_answer_binding_v1_1:true})})).json();
              if (r.started === false) {
                message.info("该 Prompt 的机器分析已在后台运行中，稍后点击「加载待审核项」查看进度");
                return;
              }
              message.info("机器分析已在后台开始（逐条 LLM 比对，约 2-10 分钟），完成后自动刷新");
              // 轮询：事件产出后自动载入队列并刷新工作流状态（不阻塞页面）
              (async()=>{
                for (let i = 0; i < 120; i++) {
                  await new Promise((res) => setTimeout(res, 5000));
                  try {
                    const q = await (await fetch(`/api/optimization/workflow/${projectId}/${pid}/review-queue`)).json();
                    if (q.status && q.status !== "NOT_ANALYZED") {
                      setReviewQueue(q);
                      const wf = await (await fetch(`/api/optimization/workflow/${projectId}/${pid}/status`)).json();
                      setWorkflowData(wf);
                      if ((q.unique_events || []).length === 0 && (q.alignments || []).length === 0) {
                        message.info("机器分析完成：该 Prompt 的答案中没有推荐内容，无审核项；Claims 与对齐仍在后台继续");
                      } else {
                        message.success("机器分析已产出审核项，可开始审核；Claims 与对齐仍在后台继续");
                      }
                      return;
                    }
                  } catch { /* 网络抖动继续轮询 */ }
                }
                try {
                  const q = await (await fetch(`/api/optimization/workflow/${projectId}/${pid}/review-queue`)).json();
                  if (!q.status || q.status === "NOT_ANALYZED") {
                    message.warning("分析仍在后台进行（比对量大时较慢），稍后点击「加载待审核项」查看进度");
                  }
                } catch { /* 忽略 */ }
              })();
            }catch(e:any){message.error(e.message)}
            finally{setLoading(false)}
          }}>运行机器分析（后台运行，约 2-10 分钟）</Button>
        </Space>}
        {reviewQueue && reviewQueue.status !== "NOT_ANALYZED" && <Space direction="vertical" size={12} style={{width:"100%"}}>
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
                <Button size="small" onClick={async()=>{
                  try {
                    await fetch(`/api/optimization/workflow/${projectId}/competitor-candidates/reject`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:c.entity})});
                  } catch (e:any) { message.error(e.message || "记录失败"); return; }
                  message.success(`已记录「不是竞品」：${c.entity}，之后不会再出现`);
                  setCompetitorCandidates(competitorCandidates.filter((x:any)=>x.entity!==c.entity));
                }}>不是</Button>
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
                await refreshWorkflowStatus();
                const pid = currentWorkflowData?.prompt_id || citationTargetPromptId;
                if (pid) await loadCitationDecisionV1(pid, true);
              }}>AI 确实这样说了</Button>
              <Button size="small" onClick={async()=>{
                await fetch("/api/optimization/workflow/review/events/reject-batch",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({event_ids:e.event_ids})});
                message.success("已标记错误");
                setReviewQueue({...reviewQueue, unique_events: reviewQueue.unique_events.filter((x:any)=>x!==e)});
                await refreshWorkflowStatus();
                const pid = currentWorkflowData?.prompt_id || citationTargetPromptId;
                if (pid) await loadCitationDecisionV1(pid, true);
              }}>判断有误</Button>
            </Space>
          </Card>)}
          {/* Evidence 对齐审核：同一语义证据组只展示一张卡，底层 Run-level Alignment 仍逐条保留。 */}
          {reviewQueue.alignments.map((a:any, idx:number)=>{
            const alignmentIds = a.alignment_ids || [a.alignment_id];
            return <Card key={`al-${idx}`} size="small" title={<Space wrap><Tag color="purple">证据语义关系校验 {idx+1}/{reviewQueue.alignments.length}</Tag><Tag>{a.alignment_count || alignmentIds.length} 条同组证据</Tag><Tag>{a.run_count || (a.run_ids || []).length} 个 Runs</Tag></Space>}>
            <Alert type="warning" showIcon style={{marginBottom:8}} message="这里校验的是「来源原文是否真的支持这条 AI 理由」的语义关系，不判断竞品能力真伪。竞品证据只用于建立市场标准基线。" />
            <Text strong>AI 选择理由：</Text><Text>{a.reason_text}</Text>
            <Divider style={{margin:6}}/>
            <Text strong>来源原文：</Text><Alert type="info" message={a.claim_span || a.claim_text} style={{marginTop:4}}/>
            <Text type="secondary" style={{display:"block",marginTop:4}}>
              机器判断：<Tag color={a.relation==="SUPPORTS"?"green":"gold"}>{semanticRelationLabel(a.relation)}</Tag>
              本组待审 Runs：{(a.run_ids || []).join("、") || "未知"}
            </Text>
            {a.semantic_observed_run_count > (a.run_count || 0) && <Text type="secondary" style={{display:"block",marginTop:4}}>该理由在 {(a.semantic_observed_run_ids || []).join("、")} 中出现；当前按钮只确认本组待审证据。</Text>}
            {a.evidence_role && <Text type="secondary" style={{display:"block",marginTop:4}}>证据角色：{a.evidence_role}</Text>}
            <Space style={{marginTop:8}}>
              <Button size="small" type="primary" onClick={async()=>{
                await fetch("/api/optimization/workflow/review/alignments/confirm-batch",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({alignment_ids:alignmentIds,relation:"SUPPORTS"})});
                message.success(`已确认这一组 ${alignmentIds.length} 条支持证据`);
                setReviewQueue({...reviewQueue, alignments: reviewQueue.alignments.filter((x:any)=>x!==a)});
                await refreshWorkflowStatus();
                const pid = currentWorkflowData?.prompt_id || citationTargetPromptId;
                if (pid) await loadCitationDecisionV1(pid, true);
              }}>确认这一组支持</Button>
            </Space>
          </Card>})}
          {reviewQueue.unique_events.length===0 && reviewQueue.alignments.length===0 && competitorCandidates.length===0 && <Alert type="success" showIcon message="全部审核完成！关闭窗口后在主链第 7 步生成或审核策略候选。" />}
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
    <Drawer
      width={920}
      open={workflowEvidenceDrawerOpen}
      onClose={() => setWorkflowEvidenceDrawerOpen(false)}
      title={workflowEvidenceDrawerFocus === "action" ? "动作依据" : workflowEvidenceDrawerFocus === "review" ? "人工决策依据" : "缺口依据"}
    >
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          message="先看答案，再决定是否确认"
          description={unresolvedReviewContext.review_instruction || "这里展示当前 Prompt 的答案样本和机器识别事件，用于判断机器结论是否可信。"}
        />
        {currentContinueResult && <Descriptions bordered size="small" column={2} items={[
          { key: "gap", label: "缺口结论", children: <Space wrap><Tag>{decisionDisplayText(currentContinueResult.gap?.gap_type)}</Tag><Tag>{decisionDisplayText(currentContinueResult.gap?.confidence)}</Tag></Space> },
          { key: "gap_basis", label: "缺口说明", children: currentContinueResult.gap?.basis || "暂无说明" },
          { key: "action", label: "动作结论", children: <Space wrap><Tag>{decisionDisplayText(currentContinueResult.action?.intervention_goal)}</Tag><Tag>{decisionDisplayText(currentContinueResult.action?.asset_ownership)}</Tag><Tag>{decisionDisplayText(currentContinueResult.action?.target_platform)}</Tag></Space> },
          { key: "action_basis", label: "动作说明", children: currentContinueResult.action?.note || currentContinueResult.action?.target_claim || "暂无说明" },
        ]} />}
        <Card
          size="small"
          title={<Space wrap><Text strong>答案样本</Text><Tag>{unresolvedAnswerSamples.length} 条</Tag></Space>}
        >
          <Table
            size="small"
            rowKey="run_id"
            pagination={{ pageSize: 6 }}
            dataSource={unresolvedAnswerSamples}
            locale={{ emptyText: "当前没有可展示的答案样本，请先检查采集记录。" }}
            columns={[
              { title: "采集样本", width: 120, render: (_, row: any) => <Space direction="vertical" size={0}><Text>采集 #{row.run_id}</Text><Text type="secondary">第 {row.sample_index || row.run_sequence || "-"} 样本</Text></Space> },
              { title: "采集状态", width: 100, render: (_, row: any) => statusTag(row.status) },
              { title: "目标品牌出现", width: 110, render: (_, row: any) => row.brand_mentioned ? <Tag color="green">有</Tag> : <Tag>无</Tag> },
              { title: "答案对象线索", width: 220, render: (_, row: any) => {
                const entities = row.detected_entities || [];
                if (!entities.length) return <Text type="secondary">未识别到品牌/候选对象</Text>;
                return <Space direction="vertical" size={2}>
                  {entities.slice(0, 6).map((item: any) => <Space key={`${item.entity_text}-${item.relation}`} size={2} wrap>
                    {entityRelationTag(item.relation, item.relation_label)}
                    <Text>{item.entity_text}</Text>
                  </Space>)}
                  {entities.length > 6 && <Text type="secondary">另有 {entities.length - 6} 个对象</Text>}
                </Space>;
              } },
              { title: "答案摘录", render: (_, row: any) => <pre className="content-preview">{row.answer_excerpt || "无回答正文"}</pre> },
            ]}
          />
        </Card>
        <Card
          size="small"
          title={<Space wrap><Text strong>机器识别事件</Text><Tag>{unresolvedEventDiagnostics.length} 条</Tag>{Object.entries(unresolvedEventStatusCounts).map(([status, count]: any) => <Tag key={status}>{reviewStatusLabel(status)}：{count}</Tag>)}</Space>}
        >
          <Table
            size="small"
            rowKey="event_id"
            pagination={{ pageSize: 6 }}
            dataSource={unresolvedEventDiagnostics}
            locale={{ emptyText: "当前没有机器识别出的可核对推荐事件。" }}
            columns={[
              { title: "采集", dataIndex: "run_id", width: 90, render: (value: number) => `采集 #${value}` },
              { title: "状态", width: 130, render: (_, row: any) => <Tag color={row.review_status === "VALIDATION_FAILED" ? "red" : "blue"}>{reviewStatusLabel(row.review_status)}</Tag> },
              { title: "对象", dataIndex: "entity_text", width: 140, render: (value: string) => value || "-" },
              { title: "行为", width: 140, render: (_, row: any) => speechActLabel(row.speech_act) },
              { title: "答案片段", dataIndex: "answer_span", render: (value: string) => value || "-" },
            ]}
          />
        </Card>
      </Space>
    </Drawer>
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
          { title: "域名", width: 150, render: (_, row) => <Text>{displaySourceDomain(row.domain, row.url)}</Text> }, { title: "链接", width: 70, render: (_, row) => row.url ? <Link href={sourceActionUrl(row.url)} target="_blank"><ExternalLink size={15} /></Link> : <Tag color="gold">未解析</Tag> }
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
