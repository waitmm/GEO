import { useEffect, useMemo, useRef, useState } from "react";
import type { Key } from "react";
import {
  Alert, Button, Card, Checkbox, Col, Collapse, Descriptions, Divider, Drawer, Empty, Form, Input, InputNumber,
  Layout, Menu, Modal, Popconfirm, Progress, Radio, Row, Segmented, Select, Space, Statistic, Steps, Table, Tag, Timeline, Tooltip, Typography, message
} from "antd";
import { ArrowDown, ArrowUp, BarChart3, Download, ExternalLink, FileText, ListChecks, Monitor, Play, Plus, RefreshCw, Settings, ShieldCheck } from "lucide-react";
import { api } from "./api/client";
import type {
  BrowserMonitorRun, BrowserMonitorRunDetail, BrowserQueueSummary, Project, Prompt, PromptCluster, RunArtifactContent, Topic,
  SinglePromptV2AnalysisListItem, SinglePromptV2DiagnosisEdit, SinglePromptV2DiagnosisStatus, SinglePromptV2ExecutionStatus, SinglePromptV2RunPool, SinglePromptV2RunPoolItem, SinglePromptV2SourcePreparation, SinglePromptV2Status, SinglePromptV2StrategyReadiness,
  SinglePromptV2RetestReadiness, SinglePromptV2RetestStatus, SinglePromptV2StrategyStatus, ValidationDashboard, ValidationPresence, ValidationSource
} from "./types";

const { Header, Sider, Content } = Layout;
const { Title, Text, Link } = Typography;
const MAX_MANUAL_HTML_CHARACTERS = 25_000_000;
type PageKey = "coreV2" | "validation" | "recommendation" | "optimization" | "config" | "runs" | "ranking" | "golden";
type V2AnswerReviewDecision = "CONFIRM_INCLUDE_AS_OPTION" | "CORRECT_TO_MENTION" | "KEEP_UNRESOLVED" | "EXCLUDE_EXTRACTION";
type V2SourceDraft = {
  title: string;
  inputFormat: "CLEAN_TEXT" | "HTML_SOURCE";
  cleanText: string;
  rawHtml: string;
  coverageScope: "FULL_PAGE" | "EXCERPT";
  waiverReason: string;
  waiverImpact: string;
};
type V2SourceActionNotice = {
  type: "success" | "error";
  sourceKey: string;
  title: string;
  detail: string;
};
type V2TruthDraft = {
  sourceSignalId: string;
  capabilityLabel: string;
  productTruthStatus: "SUPPORTED" | "PARTIALLY_SUPPORTED" | "NOT_SUPPORTED" | "UNKNOWN";
  sourceReference: string;
  note: string;
};

const RELEASE_FIRST_SLICE = import.meta.env.VITE_GEO_RELEASE_FIRST_SLICE === "1";

const PAGE_META: Record<PageKey, { title: string; subtitle: string }> = {
  coreV2: { title: "单问题分析 V2", subtitle: "一次分析、固定采样、可信状态" },
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

function v2AnalysisStatusTag(status?: string) {
  const labels: Record<string, string> = {
    QUEUED: "等待采集", COLLECTING: "采集中", READY: "结果已冻结",
    READY_WITH_FAILURES: "部分结果已冻结", FAILED: "采集失败", INTERRUPTED: "采集中断",
  };
  const colors: Record<string, string> = {
    QUEUED: "blue", COLLECTING: "processing", READY: "green",
    READY_WITH_FAILURES: "gold", FAILED: "red", INTERRUPTED: "volcano",
  };
  return <Tag color={colors[status || ""] || "default"}>{labels[status || ""] || status || "未开始"}</Tag>;
}

function v2BlockerLabel(code?: string) {
  const labels: Record<string, string> = {
    NEXT_STAGE_NOT_IMPLEMENTED: "下一阶段暂未接入",
    NO_VALID_RUNS: "本次没有有效采样结果",
    COLLECTION_WORKER_INTERRUPTED: "采集执行中断",
    INCOMPLETE_TASK_TERMINATION: "采集任务未完整结束",
    SERVICE_RESTART_INTERRUPTED: "服务重启中断采集",
  };
  return labels[code || ""] || code || "当前分析受阻";
}

function v2AnswerReviewReasonLabel(code: string) {
  return ({
    OPTION_ACT_WITHOUT_EXPLICIT_OPTION_CUE: "答案把工具放在场景列表中，但没有明确的‘推荐/可选’措辞，需要确认它是否真的是一个可选方案。",
  } as Record<string, string>)[code] || code;
}

function v2AnswerEventNeedsReview(event: any) {
  return event?.semantic_validation_status === "SEMANTIC_REVIEW_REQUIRED" && !(
    event?.fact_consumption_eligible === true
    && event?.review_status === "HUMAN_CONFIRMED_INCLUDE_AS_OPTION"
    && event?.review_id
  );
}

function v2EvidenceRelationLabel(value?: string | null) {
  return ({
    SOURCE_SUPPORTS_REASON: "来源正文支持该理由",
    SOURCE_CONTRADICTS_REASON: "来源正文与该理由矛盾",
    RELATED: "主题相关，但未形成支持或反驳",
    NONE: "未发现语义关系",
  } as Record<string, string>)[value || ""] || value || "未形成结论";
}

function v2EvidenceEvaluationLabel(value?: string | null) {
  return ({
    EVALUATED: "已完成判断",
    NOT_EVALUATED: "未进入候选",
    UPSTREAM_CLAIM_FAILED: "正文主张提取失败",
    UPSTREAM_CLAIM_NOT_EVALUATED: "正文主张未评估",
    UPSTREAM_CLAIM_REVIEW_REQUIRED: "正文主张待审核",
    DONE_ZERO_CLAIMS: "正文无可用主张",
    SEMANTIC_REVIEW_REQUIRED: "关系待审核",
    HARD_FILTERED: "主体范围不匹配",
    FAILED: "关系判断失败",
  } as Record<string, string>)[value || ""] || value || "未知";
}

const V2_ANSWER_REVIEW_OPTIONS: { label: string; value: V2AnswerReviewDecision }[] = [
  { label: "确认是候选", value: "CONFIRM_INCLUDE_AS_OPTION" },
  { label: "仅为提及", value: "CORRECT_TO_MENTION" },
  { label: "保留不确定", value: "KEEP_UNRESOLVED" },
  { label: "抽取错误", value: "EXCLUDE_EXTRACTION" },
];

function v2ExecutionValidationLabel(code: string) {
  const labels: Record<string, string> = {
    ASSET_TYPE_SELECTION_REQUIRED: "请选择资产类型",
    PUBLICATION_SURFACE_SELECTION_REQUIRED: "请选择发布位置",
    PUBLICATION_SURFACE_ASSET_TYPE_MISMATCH: "资产类型与发布位置不匹配",
    PUBLISHING_ACCOUNT_REQUIRED: "请填写发布账号",
    PUBLISHING_LOCATION_REQUIRED: "请填写具体栏目或页面位置",
    PUBLICATION_AUTHORITY_NOT_CONFIRMED: "请确认账号或位置的可操作性",
    TITLE_CONTAINS_UNAPPROVED_WORDING: "标题包含未获事实授权的表述",
    TITLE_DROPS_CONFIRMED_SCOPE: "标题没有保留本方案的已确认事实",
    PRODUCT_TRUTH_SECTION_REQUIRED: "至少保留一个品牌事实 Section",
    INVALID_PUBLIC_SECTION_SELECTION: "公开内容 Section 选择无效",
    UPDATE_MANAGED_NOT_ENABLED: "当前仅支持新建资产",
  };
  return labels[code] || code;
}

function v2ConformanceLabel(value: string) {
  return ({
    MATCHED: "与确认版本一致",
    VALIDATED_VARIATION: "合法调整",
    OUTSIDE_CONFIRMED_SCOPE: "偏离确认范围",
    NOT_EVALUABLE: "材料不足，无法判断",
  } as Record<string, string>)[value] || value;
}

function v2MetricLabel(value: string) {
  return ({
    brand_mention_rate: "品牌提及率",
    brand_recommendation_rate: "品牌推荐率",
    target_brand_official_reference_rate: "目标品牌官方来源引用率",
    published_url_reference_rate: "已发布 URL 引用率",
  } as Record<string, string>)[value] || value;
}

function v2MetricValue(metric?: { hit_count: number; evaluable_count: number; value: number | null }) {
  if (!metric || metric.value === null) return "不可计算";
  return `${metric.hit_count}/${metric.evaluable_count} · ${(metric.value * 100).toFixed(1)}%`;
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

function capabilityPresenceLabel(status?: string) {
  const labels: Record<string, string> = {
    SUPPORTED: "有",
    PARTIALLY_SUPPORTED: "部分有",
    NOT_SUPPORTED: "没有",
    UNKNOWN: "不确定",
  };
  return labels[status || ""] || "待确认";
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

function v2StrategyVerificationLabel(code?: string) {
  const labels: Record<string, string> = {
    TARGET_BRAND_TRUTH_UNRESOLVED: "目标品牌能力待确认",
    PUBLIC_CLAIM_EVIDENCE_PENDING: "公开声明依据待补",
    REASON_SEMANTIC_REVIEW_REQUIRED: "回答理由仍受限",
    EVIDENCE_RELATION_NOT_EVALUATED: "部分证据尚未评估",
    REFERENCE_ANCHOR_UNPROVEN: "引用锚点未证明",
    FOUNDATION_REQUIREMENT_UNKNOWN: "事实基础需求未知",
    CONTENT_BLOCKED: "正文当前不可消费",
    NO_CONSUMABLE_ANSWER_SEMANTIC_RESULT: "没有可消费的回答语义",
  };
  return labels[code || ""] || code || "待处理";
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
    strategyBasis: executable.strategy_basis || original.strategy_basis || "",
    evidenceGapReason: executable.evidence_gap_reason || original.evidence_gap_reason || "",
    decisionReasonIds:
      Array.isArray(executable.decision_reason_ids)
        ? executable.decision_reason_ids
        : Array.isArray(original.decision_reason_ids)
          ? original.decision_reason_ids
          : [],
    productTruthRefs: executable.product_truth_refs || original.product_truth_refs || {},
    benchmarkSource:
      executable.benchmark_source ||
      executable.evidence_summary?.benchmark_source ||
      original.benchmark_source ||
      original.evidence_summary?.benchmark_source ||
      {},
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

function hasSynthesisDecisionView(candidate: any): boolean {
  return candidate?.strategy_view_mode === "SYNTHESIS_DECISION_VIEW"
    && candidate?.strategy_synthesis?.strategy_synthesis_contract_version === "STRATEGY_SYNTHESIS_V1"
    && candidate?.strategy_synthesis?.validator_status === "VALID"
    && Boolean(candidate?.strategy_decision_view?.view_schema_version);
}

function StrategySynthesisDecisionView({ candidate }: { candidate: any }) {
  const view = candidate.strategy_decision_view || {};
  const audit = candidate.strategy_audit_view || {};
  const synthesis = candidate.strategy_synthesis || {};
  const themes = Array.isArray(view.themes) ? view.themes : [];
  const portfolio = view.portfolio || {};
  const primary = Array.isArray(portfolio.primary_interventions) ? portfolio.primary_interventions : [];
  const secondary = Array.isArray(portfolio.secondary_interventions) ? portfolio.secondary_interventions : [];
  const priorityTests = Array.isArray(portfolio.priority_tests) ? portfolio.priority_tests : [];
  const deferredTests = Array.isArray(portfolio.deferred_tests) ? portfolio.deferred_tests : [];
  const observeChannels = Array.isArray(portfolio.observe_channels) ? portfolio.observe_channels : [];
  const metrics = Array.isArray(view.success_metrics) ? view.success_metrics : [];

  const renderChannel = (item: any, label: string) => <div className="strategy-channel-item" key={item.channel_key}>
    <div className="strategy-channel-heading">
      <div>
        <Text type="secondary" className="strategy-channel-role">{label}</Text>
        <div><Text strong className="strategy-channel-name">{item.channel_label || platformLabel(item.channel_key)}</Text></div>
      </div>
      <Tag color={item.execution_priority === "P1" ? "red" : "default"}>{item.execution_priority || "待定"}</Tag>
    </div>
    <Text>{item.business_rationale}</Text>
    {Array.isArray(item.related_themes) && item.related_themes.length > 0 && <div className="strategy-channel-themes">
      <Text type="secondary">关联主题</Text>
      <Space wrap size={[4, 4]}>{item.related_themes.map((theme: any) => <Tag key={theme.theme_key}>{theme.title}</Tag>)}</Space>
    </div>}
    {Array.isArray(item.related_reasons) && item.related_reasons.length > 0 && <details className="strategy-inline-details">
      <summary>查看关联理由</summary>
      <ul>{item.related_reasons.map((reason: string, index: number) => <li key={`${item.channel_key}-${index}`}>{reason}</li>)}</ul>
    </details>}
    {item.validation_question && <div className="strategy-channel-note"><Text type="secondary">验证问题：{item.validation_question}</Text></div>}
    {item.why_not_primary && <div className="strategy-channel-note"><Text type="secondary">角色边界：{item.why_not_primary}</Text></div>}
  </div>;

  return <div className="strategy-decision-view" data-strategy-view="synthesis">
    <section className="strategy-view-intro">
      <div>
        <Text type="secondary" className="strategy-section-kicker">AI 决策机会</Text>
        <Title level={5}>当前可干预的决策空间</Title>
        <Text>{view.current_ai_decision_opportunity?.text}</Text>
      </div>
      <div>
        <Text type="secondary" className="strategy-section-kicker">本轮目标变化</Text>
        <Title level={5}>验证决策信号是否变化</Title>
        <Text>{view.expected_decision_change?.text}</Text>
      </div>
    </section>

    <section className="strategy-view-section">
      <div className="strategy-section-heading">
        <div>
          <Text type="secondary" className="strategy-section-kicker">本轮干预主题</Text>
          <Title level={5}>{themes.length} 个主题</Title>
        </div>
        {portfolio.needs_human_prioritization && <Tag color="orange">待人工确定优先级</Tag>}
      </div>
      <div className="strategy-theme-grid">
        {themes.map((theme: any) => <article className="strategy-theme-item" key={theme.theme_key}>
          <div className="strategy-theme-heading">
            <Tag color={theme.priority === "P1" ? "red" : "gold"}>{theme.priority}</Tag>
            <Text strong>{theme.title}</Text>
          </div>
          <Text className="strategy-theme-coverage">{theme.coverage_label || theme.coverage} 个有效 Run</Text>
          <details className="strategy-inline-details">
            <summary>查看包含的理由</summary>
            <ul>
              {(theme.original_reasons || []).map((reason: string, index: number) => <li key={`${theme.theme_key}-${index}`}>{reason}</li>)}
            </ul>
          </details>
        </article>)}
      </div>
    </section>

    <section className="strategy-view-section">
      <Text type="secondary" className="strategy-section-kicker">本轮渠道组合</Text>
      <Title level={5}>主干预</Title>
      <div className="strategy-channel-grid">
        {primary.map((item: any) => renderChannel(item, "主干预"))}
        {secondary.map((item: any) => renderChannel(item, "辅助干预"))}
      </div>
    </section>

    <section className="strategy-view-section">
      <Text type="secondary" className="strategy-section-kicker">最小验证组合</Text>
      <Title level={5}>优先验证渠道</Title>
      {priorityTests.length > 0
        ? <div className="strategy-channel-grid">{priorityTests.map((item: any) => renderChannel(item, "验证渠道"))}</div>
        : <Text type="secondary">本轮没有需要单独验证的渠道。</Text>}
    </section>

    {deferredTests.length > 0 && <section className="strategy-view-section">
      <Text type="secondary" className="strategy-section-kicker">后续验证</Text>
      <Title level={5}>暂不进入本轮组合</Title>
      <Text type="secondary">这些渠道有验证价值，但不进入本轮最小实验组合。</Text>
      <div className="strategy-channel-grid strategy-channel-grid-deferred">
        {deferredTests.map((item: any) => renderChannel(item, "后续验证"))}
      </div>
    </section>}

    <section className="strategy-view-section strategy-view-footer-grid">
      <div>
        <Text type="secondary" className="strategy-section-kicker">本轮验证指标</Text>
        <Title level={5}>成功指标</Title>
        <Space wrap>{metrics.map((item: any) => <Tag color="blue" key={item.text}>{metricLabel(item.text)}</Tag>)}</Space>
      </div>
      <details className="strategy-observe-details">
        <summary>观察渠道（{observeChannels.length}）</summary>
        <Text type="secondary">{view.observe_summary?.text}</Text>
        <div className="strategy-observe-list">
          {observeChannels.map((item: any) => <Tag key={item.channel_key}>{item.channel_label || platformLabel(item.channel_key)}</Tag>)}
        </div>
      </details>
    </section>

    <details className="strategy-audit-details">
      <summary>证据与审计详情</summary>
      <Descriptions size="small" column={{ xs: 1, md: 2 }} items={[
        { key: "contract", label: "综合契约", children: synthesis.strategy_synthesis_contract_version || "-" },
        { key: "mode", label: "综合模式", children: synthesis.synthesis_mode || "-" },
        { key: "validation", label: "校验状态", children: synthesis.validator_status || "-" },
        { key: "projection", label: "视图来源", children: synthesis.projection_mode || "PERSISTED_SYNTHESIS" },
      ]} />
      <pre className="strategy-audit-json">{JSON.stringify(audit, null, 2)}</pre>
    </details>
  </div>;
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
  const [page, setPage] = useState<PageKey>(RELEASE_FIRST_SLICE ? "coreV2" : "validation");
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
  const [step8ModalOpen, setStep8ModalOpen] = useState(false);
  const [step8Candidate, setStep8Candidate] = useState<any>(null);
  const [step8ProposalData, setStep8ProposalData] = useState<any>(null);
  const [step8ProposalEdits, setStep8ProposalEdits] = useState<Record<string, any>>({});
  const [step8ValidationResult, setStep8ValidationResult] = useState<any>(null);
  const [step8AssetsLoading, setStep8AssetsLoading] = useState(false);
  const [step8Submitting, setStep8Submitting] = useState(false);
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
  const [workflowMaterializationPlan, setWorkflowMaterializationPlan] = useState<any>(null);
  const [workflowMaterializationLoading, setWorkflowMaterializationLoading] = useState(false);
  const [workflowLoading, setWorkflowLoading] = useState(false);
  const [promptContext, setPromptContext] = useState<number | "ALL" | null>(null); // null=未选, "ALL"=全部, number=具体 prompt
  const [v2Analysis, setV2Analysis] = useState<SinglePromptV2Status | null>(null);
  const [v2AnalysisHistory, setV2AnalysisHistory] = useState<SinglePromptV2AnalysisListItem[]>([]);
  const [v2AnalysisHistoryLoading, setV2AnalysisHistoryLoading] = useState(false);
  const [v2RunPool, setV2RunPool] = useState<SinglePromptV2RunPool | null>(null);
  const [v2RunPoolLoading, setV2RunPoolLoading] = useState(false);
  const [v2SelectedRunIds, setV2SelectedRunIds] = useState<Key[]>([]);
  const [v2SelectedRunFingerprints, setV2SelectedRunFingerprints] = useState<Record<number, string>>({});
  const [v2Loading, setV2Loading] = useState(false);
  const [v2SampleCount, setV2SampleCount] = useState(3);
  const v2PendingIdempotencyKey = useRef<string | null>(null);
  const [v2SourcePreparation, setV2SourcePreparation] = useState<SinglePromptV2SourcePreparation | null>(null);
  const [v2SourceRefreshing, setV2SourceRefreshing] = useState(false);
  const [v2SourceActionKey, setV2SourceActionKey] = useState<string | null>(null);
  const [v2SourceActor, setV2SourceActor] = useState("本地审核人");
  const [v2SourceDrafts, setV2SourceDrafts] = useState<Record<string, V2SourceDraft>>({});
  const [v2SourceActionNotice, setV2SourceActionNotice] = useState<V2SourceActionNotice | null>(null);
  const [v2SourceFilter, setV2SourceFilter] = useState<"ACTION_REQUIRED" | "ALL" | "READY" | "WAIVED_WITH_LIMITATION">("ACTION_REQUIRED");
  const [v2AnswerPolicy, setV2AnswerPolicy] = useState<"CACHE_ONLY" | "ALLOW_EXTERNAL">("CACHE_ONLY");
  const [v2EvidencePolicy, setV2EvidencePolicy] = useState<"CACHE_ONLY" | "ALLOW_EXTERNAL">("CACHE_ONLY");
  const [v2Diagnosis, setV2Diagnosis] = useState<SinglePromptV2DiagnosisStatus | null>(null);
  const [v2DiagnosisLoading, setV2DiagnosisLoading] = useState(false);
  const [v2DiagnosisEdits, setV2DiagnosisEdits] = useState<Record<string, Omit<SinglePromptV2DiagnosisEdit, "reason">>>({});
  const [v2DiagnosisEditor, setV2DiagnosisEditor] = useState("本地审核人");
  const [v2DiagnosisEditReason, setV2DiagnosisEditReason] = useState("");
  const [v2DiagnosisReviewNote, setV2DiagnosisReviewNote] = useState("");
  const [v2AnswerReviewDecisions, setV2AnswerReviewDecisions] = useState<Record<string, V2AnswerReviewDecision>>({});
  const [v2TruthDraft, setV2TruthDraft] = useState<V2TruthDraft>({
    sourceSignalId: "", capabilityLabel: "", productTruthStatus: "SUPPORTED", sourceReference: "", note: "",
  });
  const [v2TruthSaving, setV2TruthSaving] = useState(false);
  const v2PendingDiagnosisKey = useRef<string | null>(null);
  const [v2StrategyReadiness, setV2StrategyReadiness] = useState<SinglePromptV2StrategyReadiness | null>(null);
  const [v2Strategy, setV2Strategy] = useState<SinglePromptV2StrategyStatus | null>(null);
  const [v2StrategyLoading, setV2StrategyLoading] = useState(false);
  const [v2StrategyEditor, setV2StrategyEditor] = useState("本地审核人");
  const [v2StrategyNote, setV2StrategyNote] = useState("");
  const [v2StrategyPriorityReason, setV2StrategyPriorityReason] = useState("");
  const [v2StrategyDirectionOrder, setV2StrategyDirectionOrder] = useState<string[]>([]);
  const v2PendingStrategyKey = useRef<string | null>(null);
  const [v2Execution, setV2Execution] = useState<SinglePromptV2ExecutionStatus | null>(null);
  const [v2ExecutionLoading, setV2ExecutionLoading] = useState(false);
  const [v2ExecutionDirectionId, setV2ExecutionDirectionId] = useState("");
  const [v2ExecutionEditor, setV2ExecutionEditor] = useState("本地执行人");
  const [v2ExecutionEdit, setV2ExecutionEdit] = useState<Record<string, any>>({});
  const [v2ExecutionNote, setV2ExecutionNote] = useState("");
  const [v2Publication, setV2Publication] = useState<Record<string, any>>({
    actual_channel: "", actual_account: "", actual_location: "", actual_url: "",
    published_at: "", actual_content_version: "", actual_title: "", differences: "",
  });
  const v2PendingExecutionKey = useRef<string | null>(null);
  const v2PendingConfirmationKey = useRef<string | null>(null);
  const v2PendingPublicationKey = useRef<string | null>(null);
  const [v2RetestReadiness, setV2RetestReadiness] = useState<SinglePromptV2RetestReadiness | null>(null);
  const [v2Retest, setV2Retest] = useState<SinglePromptV2RetestStatus | null>(null);
  const [v2RetestLoading, setV2RetestLoading] = useState(false);
  const [v2RetestPublicationId, setV2RetestPublicationId] = useState("");
  const [v2RetestSampleCount, setV2RetestSampleCount] = useState(3);
  const [v2MeasurementIdentity, setV2MeasurementIdentity] = useState({
    canonical_brand_name: "", accepted_aliases: "", official_domains: "", official_urls: "", confirmed_by: "",
  });
  const v2PendingRetestKey = useRef<string | null>(null);
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
  const [workflowActionLoadingKey, setWorkflowActionLoadingKey] = useState<string | null>(null);
  const [citationDecisionError, setCitationDecisionError] = useState<string | null>(null);
  const citationDecisionRequestSeq = useRef(0);
  const [decisionMarketEntities, setDecisionMarketEntities] = useState<any[]>([]);
  const [workflowReviewOpen, setWorkflowReviewOpen] = useState(false);
  const [workflowEvidenceDrawerOpen, setWorkflowEvidenceDrawerOpen] = useState(false);
  const [workflowEvidenceDrawerFocus, setWorkflowEvidenceDrawerFocus] = useState<"gap" | "action" | "review">("gap");
  const [reviewQueue, setReviewQueue] = useState<any>(null);
  const [reviewQueueLoading, setReviewQueueLoading] = useState(false);
  const [reviewAnalysisLoading, setReviewAnalysisLoading] = useState(false);
  const [confirmingAlignmentGroupKeys, setConfirmingAlignmentGroupKeys] = useState<Set<string>>(new Set());
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
    setWorkflowMaterializationPlan(null);
    setWorkflowMaterializationLoading(false);
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
    const params = new URLSearchParams(window.location.search);
    const requestedProjectId = Number(params.get("v2_project"));
    if (params.get("v2_analysis") && next.some((item) => item.id === requestedProjectId)) {
      setPage("coreV2");
      setProjectId(requestedProjectId);
    } else if (!projectId && next.length) {
      setProjectId(next[0].id);
    }
  }

  function persistV2Identity(status: SinglePromptV2Status) {
    const params = new URLSearchParams(window.location.search);
    params.set("v2_analysis", status.analysis.analysis_id);
    params.set("v2_project", String(status.analysis.project_id));
    params.set("v2_prompt", String(status.analysis.prompt_id));
    window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
  }

  function persistV2DiagnosisIdentity(status: SinglePromptV2DiagnosisStatus) {
    const params = new URLSearchParams(window.location.search);
    const nextResultVersion = status.result?.result_version || null;
    const diagnosisChanged = Boolean(params.get("v2_diagnosis") && params.get("v2_diagnosis") !== status.diagnosis.diagnosis_id);
    const resultChanged = Boolean(params.get("v2_diagnosis_result") && params.get("v2_diagnosis_result") !== nextResultVersion);
    if (diagnosisChanged || resultChanged) {
      params.delete("v2_strategy");
      params.delete("v2_strategy_result");
      params.delete("v2_execution_proposal");
      params.delete("v2_execution_result");
      params.delete("v2_retest");
      params.delete("v2_execution_proposal");
      params.delete("v2_execution_result");
      params.delete("v2_retest");
      setV2Strategy(null);
      setV2Execution(null);
      setV2RetestReadiness(null);
      setV2Retest(null);
      setV2RetestReadiness(null);
      setV2Retest(null);
    }
    params.set("v2_diagnosis", status.diagnosis.diagnosis_id);
    if (nextResultVersion) params.set("v2_diagnosis_result", nextResultVersion);
    else params.delete("v2_diagnosis_result");
    window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
  }

  function persistV2StrategyIdentity(status: SinglePromptV2StrategyStatus) {
    const params = new URLSearchParams(window.location.search);
    const changed = Boolean(
      (params.get("v2_strategy") && params.get("v2_strategy") !== status.strategy.strategy_id)
      || (params.get("v2_strategy_result") && params.get("v2_strategy_result") !== status.result?.result_version)
    );
    if (changed) {
      params.delete("v2_execution_proposal");
      params.delete("v2_execution_result");
      params.delete("v2_retest");
      params.delete("v2_retest");
      setV2Execution(null);
      setV2RetestReadiness(null);
      setV2Retest(null);
    }
    params.set("v2_strategy", status.strategy.strategy_id);
    if (status.result) params.set("v2_strategy_result", status.result.result_version);
    else params.delete("v2_strategy_result");
    window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
  }

  function persistV2ExecutionIdentity(status: SinglePromptV2ExecutionStatus) {
    const params = new URLSearchParams(window.location.search);
    params.set("v2_execution_proposal", status.proposal.proposal_id);
    if (status.result) params.set("v2_execution_result", status.result.result_version);
    window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
  }

  function persistV2RetestIdentity(status: SinglePromptV2RetestStatus) {
    const params = new URLSearchParams(window.location.search);
    params.set("v2_retest", status.retest.retest_id);
    window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
  }

  function hydrateV2ExecutionEdit(status: SinglePromptV2ExecutionStatus) {
    const selection = status.result?.output.selection;
    if (!selection) return;
    setV2ExecutionEdit({ ...selection });
    const confirmation = status.confirmations.find(
      (row) => row.result_version === status.result?.result_version,
    );
    setV2Publication((current) => ({
      ...current,
      actual_channel: status.result?.output.strategy_channel.channel_key || current.actual_channel || "OFFICIAL_SITE",
      actual_account: selection.publishing_account,
      actual_location: selection.publishing_location,
      actual_content_version: confirmation?.result_version || "",
      actual_title: selection.title,
    }));
  }

  async function refreshV2Analysis() {
    const params = new URLSearchParams(window.location.search);
    const analysisId = v2Analysis?.analysis.analysis_id || params.get("v2_analysis");
    if (!analysisId || !projectId || !activePromptId) return;
    setV2Loading(true);
    try {
      const status = await api.getSinglePromptV2Analysis(analysisId, projectId, activePromptId);
      setV2Analysis(status);
      setV2SampleCount(status.sampling.planned_run_count);
      persistV2Identity(status);
    } catch (error: any) {
      setV2Analysis(null);
      message.error(error.message || "读取 V2 分析状态失败");
    } finally {
      setV2Loading(false);
    }
  }

  async function refreshV2AnalysisHistory() {
    if (!projectId || !activePromptId) return;
    setV2AnalysisHistoryLoading(true);
    try {
      setV2AnalysisHistory(await api.listSinglePromptV2Analyses(projectId, activePromptId));
    } catch (error: any) {
      setV2AnalysisHistory([]);
      message.error(error.message || "读取已有分析失败");
    } finally {
      setV2AnalysisHistoryLoading(false);
    }
  }

  async function refreshV2RunPool(page = v2RunPool?.page || 1) {
    if (!projectId || !activePromptId) return;
    setV2RunPoolLoading(true);
    try {
      setV2RunPool(await api.listSinglePromptV2RunPool(projectId, activePromptId, page, 20));
    } catch (error: any) {
      message.error(error.message || "读取采样记录池失败");
    } finally {
      setV2RunPoolLoading(false);
    }
  }

  function selectV2Run(row: SinglePromptV2RunPoolItem, selected: boolean) {
    setV2SelectedRunIds((current) => selected
      ? [...new Set([...current.map(Number), row.run_id])]
      : current.filter((value) => Number(value) !== row.run_id));
    setV2SelectedRunFingerprints((current) => {
      const next = { ...current };
      if (selected) next[row.run_id] = row.input_fingerprint;
      else delete next[row.run_id];
      return next;
    });
  }

  async function createV2AnalysisFromSelectedRuns() {
    if (!projectId || !activePromptId || !v2SelectedRunIds.length) return;
    const runIds = v2SelectedRunIds.map(Number).sort((a, b) => a - b);
    const missingFingerprint = runIds.find((runId) => !v2SelectedRunFingerprints[runId]);
    if (missingFingerprint) {
      message.error(`Run #${missingFingerprint} 缺少当前输入指纹，请刷新记录池后重新选择`);
      return;
    }
    setV2Loading(true);
    try {
      const status = await api.createSinglePromptV2AnalysisFromRuns({
        project_id: projectId,
        prompt_id: activePromptId,
        run_ids: runIds,
        run_fingerprints: Object.fromEntries(runIds.map((runId) => [runId, v2SelectedRunFingerprints[runId]])),
        base_context_id: v2Analysis?.context_id || null,
        idempotency_key: crypto.randomUUID(),
      });
      setV2Analysis(status);
      setV2SourcePreparation(null);
      setV2Diagnosis(null);
      setV2StrategyReadiness(null);
      setV2Strategy(null);
      setV2Execution(null);
      setV2RetestReadiness(null);
      setV2Retest(null);
      persistV2Identity(status);
      await refreshV2AnalysisHistory();
      message.success(`已用 ${runIds.length} 个明确 Run 创建新的不可变分析版本`);
    } catch (error: any) {
      message.error(error.message || "按所选 Run 创建分析失败");
    } finally {
      setV2Loading(false);
    }
  }

  async function retryV2Run(row: SinglePromptV2RunPoolItem) {
    if (!projectId || !activePromptId) return;
    setV2RunPoolLoading(true);
    try {
      const result = await api.retrySinglePromptV2Run(row.run_id, {
        project_id: projectId,
        prompt_id: activePromptId,
        idempotency_key: crypto.randomUUID(),
      });
      message.success(`已保留 Run #${row.run_id}，新重试为 Run #${result.retry_run_id}`);
      await refreshV2RunPool();
    } catch (error: any) {
      message.error(error.message || "单 Run 重试排队失败");
    } finally {
      setV2RunPoolLoading(false);
    }
  }

  async function openV2Analysis(summary: SinglePromptV2AnalysisListItem) {
    if (!projectId || !activePromptId) return;
    setV2Loading(true);
    try {
      const status = await api.getSinglePromptV2Analysis(summary.analysis.analysis_id, projectId, activePromptId);
      const params = new URLSearchParams(window.location.search);
      params.set("v2_project", String(status.analysis.project_id));
      params.set("v2_prompt", String(status.analysis.prompt_id));
      params.set("v2_analysis", status.analysis.analysis_id);
      params.delete("v2_diagnosis");
      params.delete("v2_diagnosis_result");
      params.delete("v2_strategy");
      params.delete("v2_strategy_result");
      params.delete("v2_execution");
      params.delete("v2_execution_result");
      params.delete("v2_retest");
      window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
      setV2Analysis(status);
      setV2SampleCount(status.sampling.planned_run_count);
      setV2SourcePreparation(null);
      setV2Diagnosis(null);
      setV2StrategyReadiness(null);
      setV2Strategy(null);
      setV2Execution(null);
      setV2RetestReadiness(null);
      setV2Retest(null);
      persistV2Identity(status);
    } catch (error: any) {
      message.error(error.message || "打开 V2 分析失败");
    } finally {
      setV2Loading(false);
    }
  }

  function showV2AnalysisHistory() {
    const params = new URLSearchParams(window.location.search);
    ["v2_analysis", "v2_diagnosis", "v2_diagnosis_result", "v2_strategy", "v2_strategy_result", "v2_execution", "v2_execution_result", "v2_retest"].forEach((key) => params.delete(key));
    window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
    setV2Analysis(null);
    setV2SourcePreparation(null);
    setV2Diagnosis(null);
    setV2StrategyReadiness(null);
    setV2Strategy(null);
    setV2Execution(null);
    setV2RetestReadiness(null);
    setV2Retest(null);
    void refreshV2AnalysisHistory();
  }

  async function startV2Analysis() {
    if (!projectId || !activePromptId) {
      message.warning("请先选择一个 Prompt");
      return;
    }
    setV2Loading(true);
    const key = v2PendingIdempotencyKey.current || crypto.randomUUID();
    v2PendingIdempotencyKey.current = key;
    try {
      const params = new URLSearchParams(window.location.search);
      params.delete("v2_diagnosis");
      params.delete("v2_diagnosis_result");
      params.delete("v2_strategy");
      params.delete("v2_strategy_result");
      window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
      setV2Diagnosis(null);
      setV2DiagnosisEdits({});
      setV2SourcePreparation(null);
      setV2SourceDrafts({});
      setV2SourceActionNotice(null);
      setV2StrategyReadiness(null);
      setV2Strategy(null);
      setV2Execution(null);
      setV2RetestReadiness(null);
      setV2Retest(null);
      const status = await api.createSinglePromptV2Analysis({
        project_id: projectId,
        prompt_id: activePromptId,
        sample_count: v2SampleCount,
        idempotency_key: key,
      });
      v2PendingIdempotencyKey.current = null;
      setV2Analysis(status);
      await refreshV2AnalysisHistory();
      setV2SampleCount(status.sampling.planned_run_count);
      persistV2Identity(status);
      message.success("V2 分析已创建，采样计划已经固定");
    } catch (error: any) {
      message.error(error.message || "创建 V2 分析失败");
    } finally {
      setV2Loading(false);
    }
  }

  async function retryV2Analysis() {
    if (!v2Analysis || !projectId || !activePromptId) return;
    setV2Loading(true);
    try {
      const status = await api.retrySinglePromptV2Analysis(v2Analysis.analysis.analysis_id, projectId, activePromptId);
      setV2Analysis(status);
      message.success("已明确重试未完成的采样");
    } catch (error: any) {
      message.error(error.message || "重试失败");
    } finally {
      setV2Loading(false);
    }
  }

  async function refreshV2SourcePreparation(silent = false) {
    if (!v2Analysis?.context_id || !projectId || !activePromptId) return;
    if (!silent) setV2SourceRefreshing(true);
    try {
      const status = await api.getSinglePromptV2SourcePreparation(
        v2Analysis.analysis.analysis_id,
        projectId,
        activePromptId,
      );
      setV2SourcePreparation(status);
    } catch (error: any) {
      message.error(error.message || "读取来源准备状态失败");
    } finally {
      if (!silent) setV2SourceRefreshing(false);
    }
  }

  async function startV2SourcePreparation() {
    if (!v2Analysis?.context_id || !projectId || !activePromptId) return;
    setV2SourceActionKey("create-preparation");
    try {
      const status = await api.createSinglePromptV2SourcePreparation(
        v2Analysis.analysis.analysis_id,
        {
          project_id: projectId,
          prompt_id: activePromptId,
          idempotency_key: `source-preparation:${v2Analysis.context_id}`,
          created_by: v2SourceActor.trim() || "本地审核人",
        },
      );
      setV2SourcePreparation(status);
      message.success("引用范围已冻结，请先自动获取正文");
    } catch (error: any) {
      message.error(error.message || "冻结引用范围失败");
    } finally {
      setV2SourceActionKey(null);
    }
  }

  async function startV2SourceAutoFetch() {
    if (!v2SourcePreparation || !projectId || !activePromptId) return;
    setV2SourceActionKey("auto-fetch");
    try {
      const status = await api.queueSinglePromptV2SourceAutoFetch(
        v2SourcePreparation.preparation.preparation_id,
        { project_id: projectId, prompt_id: activePromptId },
      );
      setV2SourcePreparation(status);
      message.success("正文自动获取已进入单 worker 队列");
    } catch (error: any) {
      message.error(error.message || "自动获取正文失败");
    } finally {
      setV2SourceActionKey(null);
    }
  }

  function updateV2SourceDraft(sourceKey: string, values: Partial<V2SourceDraft>) {
    setV2SourceDrafts((current) => ({
      ...current,
      [sourceKey]: {
        ...(current[sourceKey] || {
          title: "",
          inputFormat: "CLEAN_TEXT",
          cleanText: "",
          rawHtml: "",
          coverageScope: "FULL_PAGE",
          waiverReason: "",
          waiverImpact: "",
        }),
        ...values,
      },
    }));
  }

  async function submitV2ManualSource(source: SinglePromptV2SourcePreparation["sources"][number]) {
    if (!v2SourcePreparation || !projectId || !activePromptId) return;
    const draft = v2SourceDrafts[source.source_key];
    const inputFormat = draft?.inputFormat || "CLEAN_TEXT";
    const submittedContent = inputFormat === "HTML_SOURCE" ? draft?.rawHtml : draft?.cleanText;
    if (!submittedContent?.trim() || submittedContent.trim().length < 50) {
      message.warning(inputFormat === "HTML_SOURCE" ? "请粘贴完整的页面 HTML 源码" : "请补录至少 50 个字符的正文");
      return;
    }
    if (inputFormat === "HTML_SOURCE" && submittedContent.length > MAX_MANUAL_HTML_CHARACTERS) {
      message.error(`页面源码共 ${submittedContent.length.toLocaleString()} 个字符，超过 25,000,000 字符上限`);
      return;
    }
    const actionKey = `manual:${source.source_key}`;
    const sourceTitle = String(source.reference_observations?.[0]?.title || source.canonical_url);
    setV2SourceActionNotice(null);
    setV2SourceActionKey(actionKey);
    try {
      const status = await api.submitSinglePromptV2ManualSource(
        v2SourcePreparation.preparation.preparation_id,
        {
          project_id: projectId,
          prompt_id: activePromptId,
          source_key: source.source_key,
          expected_row_version: source.row_version,
          title: draft.title || source.reference_observations?.[0]?.title || "",
          input_format: inputFormat,
          clean_text: inputFormat === "CLEAN_TEXT" ? draft.cleanText : "",
          raw_html: inputFormat === "HTML_SOURCE" ? draft.rawHtml : "",
          coverage_scope: draft.coverageScope,
          submitted_by: v2SourceActor.trim() || "本地审核人",
        },
      );
      setV2SourcePreparation(status);
      updateV2SourceDraft(source.source_key, { cleanText: "", rawHtml: "" });
      const detail = inputFormat === "HTML_SOURCE" ? "页面源码已提取正文并生成不可变快照" : "正文与 passages 已生成不可变快照";
      setV2SourceActionNotice({ type: "success", sourceKey: source.source_key, title: sourceTitle, detail });
      message.success({ content: detail, duration: 6 });
    } catch (error: any) {
      const detail = error.message || "正文补录失败";
      setV2SourceActionNotice({ type: "error", sourceKey: source.source_key, title: sourceTitle, detail });
      message.error({ content: detail, duration: 8 });
    } finally {
      setV2SourceActionKey(null);
    }
  }

  async function waiveV2Source(source: SinglePromptV2SourcePreparation["sources"][number]) {
    if (!v2SourcePreparation || !projectId || !activePromptId) return;
    const draft = v2SourceDrafts[source.source_key];
    if (!draft?.waiverReason?.trim() || !draft?.waiverImpact?.trim()) {
      message.warning("人工放弃必须填写原因和对结论的影响");
      return;
    }
    const actionKey = `waive:${source.source_key}`;
    setV2SourceActionKey(actionKey);
    try {
      const status = await api.waiveSinglePromptV2Source(
        v2SourcePreparation.preparation.preparation_id,
        {
          project_id: projectId,
          prompt_id: activePromptId,
          source_key: source.source_key,
          expected_row_version: source.row_version,
          reason: draft.waiverReason,
          impact: draft.waiverImpact,
          waived_by: v2SourceActor.trim() || "本地审核人",
        },
      );
      setV2SourcePreparation(status);
      message.success("已记录人工放弃及限制；该来源不会产生证据结论");
    } catch (error: any) {
      message.error(error.message || "记录人工放弃失败");
    } finally {
      setV2SourceActionKey(null);
    }
  }

  async function freezeV2SourceCompletion() {
    if (!v2SourcePreparation || !projectId || !activePromptId) return;
    setV2SourceActionKey("freeze-completion");
    try {
      const status = await api.freezeSinglePromptV2SourceCompletion(
        v2SourcePreparation.preparation.preparation_id,
        {
          project_id: projectId,
          prompt_id: activePromptId,
          created_by: v2SourceActor.trim() || "本地审核人",
        },
      );
      setV2SourcePreparation(status);
      message.success(status.completion_manifest?.status === "FROZEN"
        ? "Source Completion Manifest 已冻结"
        : "来源处置已关闭，但没有可供 Evidence 使用的正文");
    } catch (error: any) {
      message.error(error.message || "冻结来源完成清单失败");
    } finally {
      setV2SourceActionKey(null);
    }
  }

  async function refreshV2Diagnosis() {
    if (!v2Analysis || !projectId || !activePromptId) return;
    const params = new URLSearchParams(window.location.search);
    const diagnosisId = v2Diagnosis?.diagnosis.diagnosis_id || params.get("v2_diagnosis");
    if (!diagnosisId) return;
    setV2DiagnosisLoading(true);
    try {
      const status = await api.getSinglePromptV2Diagnosis(v2Analysis.analysis.analysis_id, diagnosisId, projectId, activePromptId);
      setV2Diagnosis(status);
      persistV2DiagnosisIdentity(status);
    } catch (error: any) {
      setV2Diagnosis(null);
      message.error(error.message || "读取诊断状态失败");
    } finally {
      setV2DiagnosisLoading(false);
    }
  }

  async function startV2Diagnosis() {
    if (!v2Analysis?.context_id || !projectId || !activePromptId || !v2SourcePreparation) return;
    const key = v2PendingDiagnosisKey.current || crypto.randomUUID();
    v2PendingDiagnosisKey.current = key;
    setV2DiagnosisLoading(true);
    try {
      const params = new URLSearchParams(window.location.search);
      params.delete("v2_strategy");
      params.delete("v2_strategy_result");
      params.delete("v2_execution_proposal");
      params.delete("v2_execution_result");
      window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
      setV2StrategyReadiness(null);
      setV2Strategy(null);
      setV2Execution(null);
      const status = await api.createSinglePromptV2AnswerDiagnosis(v2Analysis.analysis.analysis_id, {
        project_id: projectId,
        prompt_id: activePromptId,
        citation_manifest_id: v2SourcePreparation.citation_manifest.manifest_id,
        citation_manifest_hash: v2SourcePreparation.citation_manifest.payload_hash,
        answer_llm_policy: v2AnswerPolicy,
        idempotency_key: key,
      });
      v2PendingDiagnosisKey.current = null;
      setV2Diagnosis(status);
      persistV2DiagnosisIdentity(status);
      message.success("Answer Semantic 执行已创建，Citation Manifest 已精确绑定");
    } catch (error: any) {
      message.error(error.message || "创建诊断失败");
    } finally {
      setV2DiagnosisLoading(false);
    }
  }

  async function continueV2Evidence() {
    if (
      !v2Analysis || !v2Diagnosis?.result || !v2Diagnosis.review
      || !v2SourcePreparation?.completion_manifest || !projectId || !activePromptId
    ) return;
    setV2DiagnosisLoading(true);
    try {
      const status = await api.continueSinglePromptV2Evidence(
        v2Analysis.analysis.analysis_id,
        v2Diagnosis.diagnosis.diagnosis_id,
        {
          project_id: projectId,
          prompt_id: activePromptId,
          answer_result_version: v2Diagnosis.result.result_version,
          answer_result_hash: v2Diagnosis.result.output_hash,
          answer_review_id: v2Diagnosis.review.review_id,
          citation_manifest_id: v2SourcePreparation.citation_manifest.manifest_id,
          citation_manifest_hash: v2SourcePreparation.citation_manifest.payload_hash,
          completion_manifest_id: v2SourcePreparation.completion_manifest.manifest_id,
          completion_manifest_hash: v2SourcePreparation.completion_manifest.payload_hash,
          evidence_llm_policy: v2EvidencePolicy,
        },
      );
      setV2Diagnosis(status);
      persistV2DiagnosisIdentity(status);
      message.success("Evidence 双输入 Gate 已通过，等待串行业务 worker 执行");
    } catch (error: any) {
      message.error(error.message || "Evidence 双输入校验或执行失败");
    } finally {
      setV2DiagnosisLoading(false);
    }
  }

  async function retryV2DiagnosisExecution() {
    if (!v2Analysis || !v2Diagnosis || !projectId || !activePromptId) return;
    setV2DiagnosisLoading(true);
    try {
      const status = await api.retrySinglePromptV2Diagnosis(
        v2Analysis.analysis.analysis_id,
        v2Diagnosis.diagnosis.diagnosis_id,
        projectId,
        activePromptId,
      );
      setV2Diagnosis(status);
      message.success("已明确重试同一次诊断执行");
    } catch (error: any) {
      message.error(error.message || "重试诊断失败");
    } finally {
      setV2DiagnosisLoading(false);
    }
  }

  function stageV2DiagnosisEdit(targetType: SinglePromptV2DiagnosisEdit["target_type"], targetId: string, value: string) {
    const key = `${targetType}:${targetId}`;
    setV2DiagnosisEdits((current) => ({ ...current, [key]: { target_type: targetType, target_id: targetId, value } }));
  }

  function clearV2DiagnosisEdit(targetType: SinglePromptV2DiagnosisEdit["target_type"], targetId: string) {
    const key = `${targetType}:${targetId}`;
    setV2DiagnosisEdits((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  function setV2AnswerReviewDecision(event: any, decision: V2AnswerReviewDecision) {
    setV2AnswerReviewDecisions((current) => ({ ...current, [event.event_id]: decision }));
    if (decision === "CORRECT_TO_MENTION") {
      stageV2DiagnosisEdit("RECOMMENDATION_EVENT", event.event_id, "MENTION");
    } else {
      clearV2DiagnosisEdit("RECOMMENDATION_EVENT", event.event_id);
    }
  }

  async function saveV2DiagnosisRevision() {
    if (!v2Analysis || !v2Diagnosis?.result || !projectId || !activePromptId) return;
    const edits = Object.values(v2DiagnosisEdits);
    if (!edits.length) return;
    if (!v2DiagnosisEditReason.trim()) {
      message.warning("请填写本次语义修改原因");
      return;
    }
    setV2DiagnosisLoading(true);
    try {
      const result = v2Diagnosis.result;
      const status = await api.reviseSinglePromptV2Diagnosis(
        v2Analysis.analysis.analysis_id,
        v2Diagnosis.diagnosis.diagnosis_id,
        result.result_version,
        {
          project_id: projectId,
          prompt_id: activePromptId,
          base_result_version: result.result_version,
          base_result_hash: result.output_hash,
          reviewable_set_hash: result.reviewable_set_hash,
          editor: v2DiagnosisEditor.trim(),
          edits: edits.map((edit) => ({ ...edit, reason: v2DiagnosisEditReason.trim() })),
        },
      );
      setV2Diagnosis(status);
      persistV2DiagnosisIdentity(status);
      setV2DiagnosisEdits({});
      setV2DiagnosisEditReason("");
      message.success("修改已保存为新的不可变结果版本");
    } catch (error: any) {
      message.error(error.message || "保存诊断修改失败");
    } finally {
      setV2DiagnosisLoading(false);
    }
  }

  async function completeV2DiagnosisReview() {
    if (!v2Analysis || !v2Diagnosis?.result || !projectId || !activePromptId) return;
    if (!v2DiagnosisEditor.trim()) {
      message.warning("请填写审核人");
      return;
    }
    if (Object.keys(v2DiagnosisEdits).length) {
      message.warning("存在尚未保存的语义修改，请先生成新结果版本");
      return;
    }
    const pendingEvents = (v2Diagnosis.result.output.answer_diagnosis?.events || []).filter(
      v2AnswerEventNeedsReview,
    );
    const undecidedEvents = pendingEvents.filter(
      (event: any) => !v2AnswerReviewDecisions[event.event_id] && !v2StoredAnswerReviewDecisions.has(event.event_id),
    );
    if (undecidedEvents.length) {
      message.warning(`还有 ${undecidedEvents.length} 个候选判断未处理`);
      document.getElementById("v2-answer-semantic-review")?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    setV2DiagnosisLoading(true);
    try {
      const result = v2Diagnosis.result;
      const status = await api.reviewSinglePromptV2Diagnosis(
        v2Analysis.analysis.analysis_id,
        v2Diagnosis.diagnosis.diagnosis_id,
        result.result_version,
        {
          project_id: projectId,
          prompt_id: activePromptId,
          result_hash: result.output_hash,
          reviewable_set_hash: result.reviewable_set_hash,
          reviewer: v2DiagnosisEditor.trim(),
          note: v2DiagnosisReviewNote.trim(),
          decisions: [
            ...pendingEvents.map((event: any) => ({
              scope: "ANSWER_SEMANTIC_EVENT",
              event_id: event.event_id,
              run_id: event.run_id,
              decision: v2AnswerReviewDecisions[event.event_id] || v2StoredAnswerReviewDecisions.get(event.event_id),
              machine_speech_act: event.machine_speech_act,
              effective_speech_act: event.effective_speech_act,
              review_reasons: event.semantic_admission?.review_reasons || [],
            })),
            { scope: "ENTIRE_REVIEWABLE_SET", decision: "REVIEW_COMPLETED_WITH_LIMITATIONS_PRESERVED" },
          ],
        },
      );
      setV2Diagnosis(status);
      persistV2DiagnosisIdentity(status);
      message.success("本版诊断审核已完成；未解决项和限制仍被保留");
    } catch (error: any) {
      message.error(error.message || "完成诊断审核失败");
    } finally {
      setV2DiagnosisLoading(false);
    }
  }

  function prepareV2TargetCapabilityReview(item: SinglePromptV2DiagnosisStatus["target_capability_review_items"][number]) {
    setV2TruthDraft((current) => ({
      ...current,
      sourceSignalId: item.source_signal_ids[0] || "",
      capabilityLabel: item.capability_label,
      productTruthStatus: "SUPPORTED",
      sourceReference: "",
      note: "",
    }));
    document.getElementById("v2-truth-review-form")?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function prepareV2TruthReviewFromCriterion(criterion: any) {
    setV2TruthDraft((current) => ({
      ...current,
      sourceSignalId: String(criterion.criterion_id || ""),
      capabilityLabel: String(criterion.effective_grounded_text || criterion.reason_span || ""),
    }));
    document.getElementById("v2-truth-review-form")?.scrollIntoView({ behavior: "smooth", block: "center" });
    message.info("市场选择标准只用于发起目标品牌事实核对，不会自动成为品牌推荐理由");
  }

  async function submitV2TargetBrandTruth() {
    if (!v2Analysis || !v2Diagnosis?.result || !projectId || !activePromptId) return;
    if (!v2TruthDraft.capabilityLabel.trim()) {
      message.warning("请填写目标品牌自身的真实能力");
      return;
    }
    if (!v2TruthDraft.sourceSignalId) {
      message.warning("请先从一条答案能力信号发起事实核对");
      return;
    }
    if (!v2DiagnosisEditor.trim()) {
      message.warning("请填写核对人");
      return;
    }
    setV2TruthSaving(true);
    try {
      const response = await api.createSinglePromptV2TargetBrandTruth(
        v2Analysis.analysis.analysis_id,
        v2Diagnosis.diagnosis.diagnosis_id,
        v2Diagnosis.result.result_version,
        {
          project_id: projectId,
          prompt_id: activePromptId,
          result_hash: v2Diagnosis.result.output_hash,
          frozen_truth_set_hash: v2Diagnosis.diagnosis.truth_set_hash,
          expected_project_truth_set_hash: v2Diagnosis.project_truth_state.truth_set_hash,
          source_signal_id: v2TruthDraft.sourceSignalId,
          capability_label: v2TruthDraft.capabilityLabel.trim(),
          product_truth_status: v2TruthDraft.productTruthStatus,
          source_reference: v2TruthDraft.sourceReference.trim(),
          note: v2TruthDraft.note.trim(),
          reviewed_by: v2DiagnosisEditor.trim(),
        },
      );
      setV2Diagnosis((current) => current ? { ...current, project_truth_state: response.project_truth_state } : current);
      setV2TruthDraft({ sourceSignalId: "", capabilityLabel: "", productTruthStatus: "SUPPORTED", sourceReference: "", note: "" });
      message.success(v2TruthDraft.sourceReference.trim()
        ? "能力与公开依据已保存；请更新本次分析"
        : "能力已确认，可参与策略判断；公开内容使用前仍需补依据");
    } catch (error: any) {
      message.error(error.message || "保存目标品牌事实失败");
    } finally {
      setV2TruthSaving(false);
    }
  }

  async function createV2DiagnosisForUpdatedTruths() {
    if (!v2Analysis?.context_id || !v2Diagnosis?.result || !v2Diagnosis.review || !projectId || !activePromptId) return;
    if (!v2Diagnosis.project_truth_state.differs_from_frozen_diagnosis) {
      message.info("项目事实集合与当前诊断快照一致，无需创建新诊断");
      return;
    }
    setV2DiagnosisLoading(true);
    try {
      const status = await api.createSinglePromptV2TruthReprojection(
        v2Analysis.analysis.analysis_id,
        v2Diagnosis.diagnosis.diagnosis_id,
        v2Diagnosis.result.result_version,
        {
        project_id: projectId,
        prompt_id: activePromptId,
        source_result_hash: v2Diagnosis.result.output_hash,
        source_review_id: v2Diagnosis.review.review_id,
        expected_project_truth_set_hash: v2Diagnosis.project_truth_state.truth_set_hash,
        idempotency_key: crypto.randomUUID(),
      });
      const params = new URLSearchParams(window.location.search);
      params.set("v2_diagnosis", status.diagnosis.diagnosis_id);
      params.delete("v2_strategy");
      params.delete("v2_strategy_result");
      params.delete("v2_execution_proposal");
      params.delete("v2_execution_result");
      window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
      setV2DiagnosisEdits({});
      setV2AnswerReviewDecisions({});
      setV2StrategyReadiness(null);
      setV2Strategy(null);
      setV2Execution(null);
      setV2Diagnosis(status);
      persistV2DiagnosisIdentity(status);
      message.success("事实关系已刷新；Answer 与 Evidence 未重算，请复核新的事实关系");
    } catch (error: any) {
      message.error(error.message || "创建新诊断失败");
    } finally {
      setV2DiagnosisLoading(false);
    }
  }

  async function refreshV2StrategyContext(diagnosisStatus: SinglePromptV2DiagnosisStatus | null = v2Diagnosis) {
    if (!v2Analysis || !diagnosisStatus?.result || !projectId || !activePromptId) return;
    setV2StrategyLoading(true);
    try {
      const readiness = await api.getSinglePromptV2StrategyReadiness(
        v2Analysis.analysis.analysis_id,
        diagnosisStatus.diagnosis.diagnosis_id,
        diagnosisStatus.result.result_version,
        projectId,
        activePromptId,
      );
      setV2StrategyReadiness(readiness);
      if (RELEASE_FIRST_SLICE) {
        setV2Strategy(null);
        setV2StrategyDirectionOrder([]);
        return;
      }
      const params = new URLSearchParams(window.location.search);
      const strategyId = params.get("v2_strategy");
      if (!strategyId) {
        setV2Strategy(null);
        setV2StrategyDirectionOrder([]);
        return;
      }
      const status = await api.getSinglePromptV2Strategy(
        v2Analysis.analysis.analysis_id,
        diagnosisStatus.diagnosis.diagnosis_id,
        strategyId,
        projectId,
        activePromptId,
      );
      setV2Strategy(status);
      persistV2StrategyIdentity(status);
      setV2StrategyDirectionOrder(
        [...(status.result?.output.directions || [])]
          .sort((left, right) => (left.priority_order || Number.MAX_SAFE_INTEGER) - (right.priority_order || Number.MAX_SAFE_INTEGER))
          .map((row) => row.direction_id),
      );
      if ((status.result?.output.directions || []).length === 1) setV2ExecutionDirectionId(status.result!.output.directions[0].direction_id);
    } catch (error: any) {
      message.error(error.message || "读取 V2 策略状态失败");
    } finally {
      setV2StrategyLoading(false);
    }
  }

  async function createV2Strategy() {
    if (!v2Analysis || !v2Diagnosis?.result || !v2StrategyReadiness || !projectId || !activePromptId) return;
    if (!v2StrategyReadiness.can_create_strategy || !v2StrategyReadiness.review_id || !v2StrategyReadiness.review_snapshot_hash) {
      message.warning(v2StrategyReadiness.blocker?.detail || "当前输入尚不能生成正式策略候选");
      return;
    }
    const key = v2PendingStrategyKey.current || crypto.randomUUID();
    v2PendingStrategyKey.current = key;
    setV2StrategyLoading(true);
    try {
      const status = await api.createSinglePromptV2Strategy(
        v2Analysis.analysis.analysis_id,
        v2Diagnosis.diagnosis.diagnosis_id,
        v2Diagnosis.result.result_version,
        {
          project_id: projectId,
          prompt_id: activePromptId,
          idempotency_key: key,
          diagnosis_result_hash: v2Diagnosis.result.output_hash,
          reviewable_set_hash: v2Diagnosis.result.reviewable_set_hash,
          review_id: v2StrategyReadiness.review_id,
          review_snapshot_hash: v2StrategyReadiness.review_snapshot_hash,
          input_projection_hash: v2StrategyReadiness.input_projection_hash,
        },
      );
      v2PendingStrategyKey.current = null;
      setV2Strategy(status);
      persistV2StrategyIdentity(status);
      setV2StrategyDirectionOrder((status.result?.output.directions || []).map((row) => row.direction_id));
      if ((status.result?.output.directions || []).length === 1) setV2ExecutionDirectionId(status.result!.output.directions[0].direction_id);
      message.success("策略候选已按当前审核版本生成，未创建执行方案");
    } catch (error: any) {
      message.error(error.message || "生成 V2 策略候选失败");
    } finally {
      setV2StrategyLoading(false);
    }
  }

  function moveV2StrategyDirection(directionId: string, delta: -1 | 1) {
    setV2StrategyDirectionOrder((current) => {
      const index = current.indexOf(directionId);
      const target = index + delta;
      if (index < 0 || target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  async function saveV2StrategyPriority() {
    if (!v2Analysis || !v2Diagnosis || !v2Strategy?.result || !projectId || !activePromptId) return;
    if (!v2StrategyEditor.trim() || !v2StrategyPriorityReason.trim()) {
      message.warning("请填写优先级调整人和原因");
      return;
    }
    setV2StrategyLoading(true);
    try {
      const result = v2Strategy.result;
      const status = await api.reviseSinglePromptV2StrategyPriority(
        v2Analysis.analysis.analysis_id,
        v2Diagnosis.diagnosis.diagnosis_id,
        v2Strategy.strategy.strategy_id,
        result.result_version,
        {
          project_id: projectId,
          prompt_id: activePromptId,
          base_result_version: result.result_version,
          base_result_hash: result.output_hash,
          reviewable_set_hash: result.reviewable_set_hash,
          ordered_direction_ids: v2StrategyDirectionOrder,
          editor: v2StrategyEditor.trim(),
          reason: v2StrategyPriorityReason.trim(),
        },
      );
      setV2Strategy(status);
      persistV2StrategyIdentity(status);
      setV2StrategyPriorityReason("");
      message.success("优先顺序已保存为新的不可变策略版本");
    } catch (error: any) {
      message.error(error.message || "保存策略优先顺序失败");
    } finally {
      setV2StrategyLoading(false);
    }
  }

  async function reviewV2Strategy(decision: "ACCEPTED" | "REJECTED") {
    if (!v2Analysis || !v2Diagnosis || !v2Strategy?.result || !projectId || !activePromptId) return;
    if (!v2StrategyEditor.trim()) {
      message.warning("请填写策略审核人");
      return;
    }
    if (decision === "ACCEPTED" && v2Strategy.result.output.needs_human_prioritization) {
      message.warning("请先明确同层方向的人工优先顺序");
      return;
    }
    setV2StrategyLoading(true);
    try {
      const result = v2Strategy.result;
      const status = await api.reviewSinglePromptV2Strategy(
        v2Analysis.analysis.analysis_id,
        v2Diagnosis.diagnosis.diagnosis_id,
        v2Strategy.strategy.strategy_id,
        result.result_version,
        {
          project_id: projectId,
          prompt_id: activePromptId,
          result_hash: result.output_hash,
          reviewable_set_hash: result.reviewable_set_hash,
          decision,
          reviewer: v2StrategyEditor.trim(),
          note: v2StrategyNote.trim(),
        },
      );
      setV2Strategy(status);
      if (decision === "ACCEPTED" && (status.result?.output.directions || []).length === 1) setV2ExecutionDirectionId(status.result!.output.directions[0].direction_id);
      message.success(decision === "ACCEPTED" ? "策略候选已确认" : "策略候选已拒绝");
    } catch (error: any) {
      message.error(error.message || "策略审核失败");
    } finally {
      setV2StrategyLoading(false);
    }
  }

  async function refreshV2Execution() {
    if (!v2Strategy || !projectId || !activePromptId) return;
    const proposalId = v2Execution?.proposal.proposal_id || new URLSearchParams(window.location.search).get("v2_execution_proposal");
    if (!proposalId) return;
    setV2ExecutionLoading(true);
    try {
      const status = await api.getSinglePromptV2ExecutionProposal(
        v2Strategy.strategy.strategy_id, proposalId, projectId, activePromptId,
      );
      setV2Execution(status);
      persistV2ExecutionIdentity(status);
      hydrateV2ExecutionEdit(status);
    } catch (error: any) {
      setV2Execution(null);
      message.error(error.message || "读取 V2 执行方案失败");
    } finally {
      setV2ExecutionLoading(false);
    }
  }

  async function createV2ExecutionProposal() {
    if (!v2Strategy?.result || !v2Strategy.review || !projectId || !activePromptId || !v2ExecutionDirectionId) return;
    if (v2Strategy.review.decision !== "ACCEPTED") {
      message.warning("只有已确认的精确策略版本可以生成执行方案");
      return;
    }
    const key = v2PendingExecutionKey.current || crypto.randomUUID();
    v2PendingExecutionKey.current = key;
    setV2ExecutionLoading(true);
    try {
      const status = await api.createSinglePromptV2ExecutionProposal(
        v2Strategy.strategy.analysis_id,
        v2Strategy.strategy.diagnosis_id,
        v2Strategy.strategy.strategy_id,
        v2Strategy.result.result_version,
        {
          project_id: projectId,
          prompt_id: activePromptId,
          direction_id: v2ExecutionDirectionId,
          idempotency_key: key,
          strategy_result_hash: v2Strategy.result.output_hash,
          strategy_review_id: v2Strategy.review.review_id,
          strategy_review_snapshot_hash: v2Strategy.review.review_snapshot_hash,
        },
      );
      v2PendingExecutionKey.current = null;
      setV2Execution(status);
      persistV2ExecutionIdentity(status);
      hydrateV2ExecutionEdit(status);
      message.success("执行内容骨架已生成；尚未确认，也尚未发布");
    } catch (error: any) {
      message.error(error.message || "生成执行方案失败");
    } finally {
      setV2ExecutionLoading(false);
    }
  }

  async function saveV2ExecutionRevision() {
    if (!v2Execution?.result || !v2Strategy || !projectId || !activePromptId || !v2ExecutionEditor.trim()) return;
    setV2ExecutionLoading(true);
    try {
      const result = v2Execution.result;
      const status = await api.reviseSinglePromptV2ExecutionProposal(
        v2Strategy.strategy.strategy_id,
        v2Execution.proposal.proposal_id,
        result.result_version,
        {
          project_id: projectId,
          prompt_id: activePromptId,
          base_result_version: result.result_version,
          base_result_hash: result.output_hash,
          reviewable_set_hash: result.reviewable_set_hash,
          editor: v2ExecutionEditor.trim(),
          edit: { ...v2ExecutionEdit, asset_operation: "CREATE_NEW" },
        },
      );
      setV2Execution(status);
      persistV2ExecutionIdentity(status);
      hydrateV2ExecutionEdit(status);
      message.success(status.result?.output.validation.status === "READY_FOR_CONFIRMATION" ? "执行方案已保存并通过校验" : "执行方案已保存，请继续补齐校验项");
    } catch (error: any) {
      message.error(error.message || "保存执行方案失败");
    } finally {
      setV2ExecutionLoading(false);
    }
  }

  function moveV2ExecutionSection(sectionId: string, delta: number) {
    setV2ExecutionEdit((current) => {
      const sectionOrder = [...(current.section_order || [])];
      const index = sectionOrder.indexOf(sectionId);
      const nextIndex = index + delta;
      if (index < 0 || nextIndex < 0 || nextIndex >= sectionOrder.length) return current;
      [sectionOrder[index], sectionOrder[nextIndex]] = [sectionOrder[nextIndex], sectionOrder[index]];
      return { ...current, section_order: sectionOrder };
    });
  }

  async function confirmV2ExecutionProposal() {
    if (!v2Execution?.result || !v2Strategy || !projectId || !activePromptId || !v2ExecutionEditor.trim()) return;
    const key = v2PendingConfirmationKey.current || crypto.randomUUID();
    v2PendingConfirmationKey.current = key;
    setV2ExecutionLoading(true);
    try {
      const result = v2Execution.result;
      const status = await api.confirmSinglePromptV2ExecutionProposal(
        v2Strategy.strategy.strategy_id,
        v2Execution.proposal.proposal_id,
        result.result_version,
        {
          project_id: projectId,
          prompt_id: activePromptId,
          result_hash: result.output_hash,
          reviewable_set_hash: result.reviewable_set_hash,
          idempotency_key: key,
          confirmer: v2ExecutionEditor.trim(),
          note: v2ExecutionNote.trim(),
        },
      );
      v2PendingConfirmationKey.current = null;
      setV2Execution(status);
      persistV2ExecutionIdentity(status);
      hydrateV2ExecutionEdit(status);
      message.success("执行方案已确认，当前仍是待人工发布状态");
    } catch (error: any) {
      message.error(error.message || "确认执行方案失败");
    } finally {
      setV2ExecutionLoading(false);
    }
  }

  async function recordV2Publication() {
    if (!v2Execution || !v2Strategy || !projectId || !activePromptId || !v2ExecutionEditor.trim()) return;
    const confirmation = v2Execution.confirmations.find(
      (row) => row.result_version === v2Execution.result?.result_version,
    );
    if (!confirmation) {
      message.warning("请先确认执行方案");
      return;
    }
    if (!v2Publication.actual_url || !v2Publication.published_at) {
      message.warning("请填写实际发布 URL 和发布时间");
      return;
    }
    const key = v2PendingPublicationKey.current || crypto.randomUUID();
    const priorPublication = [...v2Execution.publications]
      .reverse()
      .find((row) => row.confirmation_id === confirmation.confirmation_id);
    v2PendingPublicationKey.current = key;
    setV2ExecutionLoading(true);
    try {
      const status = await api.recordSinglePromptV2Publication(
        v2Strategy.strategy.strategy_id,
        v2Execution.proposal.proposal_id,
        confirmation.confirmation_id,
        {
          project_id: projectId,
          prompt_id: activePromptId,
          idempotency_key: key,
          prior_publication_id: priorPublication?.publication_id || null,
          recorder: v2ExecutionEditor.trim(),
          publication_status: "USER_REPORTED",
          actual_channel: v2Publication.actual_channel,
          actual_account: v2Publication.actual_account,
          actual_location: v2Publication.actual_location,
          actual_url: v2Publication.actual_url,
          published_at: v2Publication.published_at,
          actual_content_version: v2Publication.actual_content_version || "",
          actual_title: v2Publication.actual_title || "",
          actual_section_ids: v2Publication.actual_content_version ? null : (v2Execution.result?.output.selection.section_order || null),
          actual_claim_ids: null,
          actual_content_excerpt: "",
          differences: v2Publication.differences || "",
        },
      );
      v2PendingPublicationKey.current = null;
      setV2Execution(status);
      message.success("实际发布信息已按人工报告登记，未标记为系统验证");
    } catch (error: any) {
      message.error(error.message || "登记发布信息失败");
    } finally {
      setV2ExecutionLoading(false);
    }
  }

  function parseV2IdentityList(value: string) {
    return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
  }

  async function refreshV2RetestReadiness(publicationId: string = v2RetestPublicationId) {
    if (!projectId || !activePromptId) return;
    const publication = v2Execution?.publications.find((row) => row.publication_id === publicationId);
    setV2RetestLoading(true);
    try {
      const readiness = await api.getSinglePromptV2RetestReadiness(
        projectId, activePromptId, publication?.confirmation_id, publication?.publication_id,
      );
      setV2RetestReadiness(readiness);
      if (readiness.identity_default) {
        setV2MeasurementIdentity({
          canonical_brand_name: readiness.identity_default.canonical_brand_name || "",
          accepted_aliases: (readiness.identity_default.accepted_aliases || []).join("，"),
          official_domains: (readiness.identity_default.official_domains || []).join("，"),
          official_urls: (readiness.identity_default.official_urls || []).join("\n"),
          confirmed_by: "",
        });
      }
      const planned = Number(readiness.baseline?.sampling_configuration?.sample_count || readiness.baseline?.run_manifest?.planned_count || 3);
      setV2RetestSampleCount(Math.min(10, Math.max(1, planned)));
    } catch (error: any) {
      setV2RetestReadiness(null);
      message.error(error.message || "读取复测资格失败");
    } finally {
      setV2RetestLoading(false);
    }
  }

  async function createV2RetestPlan() {
    if (!projectId || !activePromptId || !v2RetestReadiness?.sampling_eligible) return;
    const publication = v2Execution?.publications.find((row) => row.publication_id === v2RetestPublicationId);
    const confirmation = v2Execution?.confirmations.find((row) => row.confirmation_id === publication?.confirmation_id);
    if (!publication || !confirmation) {
      message.warning("请选择一条精确发布记录");
      return;
    }
    const key = v2PendingRetestKey.current || crypto.randomUUID();
    v2PendingRetestKey.current = key;
    setV2RetestLoading(true);
    try {
      const status = await api.createSinglePromptV2Retest({
        project_id: projectId,
        prompt_id: activePromptId,
        confirmation_id: confirmation.confirmation_id,
        publication_id: publication.publication_id,
        confirmation_snapshot_hash: confirmation.confirmation_snapshot_hash,
        publication_report_hash: publication.report_hash,
        idempotency_key: key,
        sample_count: v2RetestSampleCount,
        measurement_identity: {
          canonical_brand_name: v2MeasurementIdentity.canonical_brand_name.trim(),
          accepted_aliases: parseV2IdentityList(v2MeasurementIdentity.accepted_aliases),
          official_domains: parseV2IdentityList(v2MeasurementIdentity.official_domains),
          official_urls: parseV2IdentityList(v2MeasurementIdentity.official_urls),
          confirmed_by: v2MeasurementIdentity.confirmed_by.trim(),
        },
      });
      v2PendingRetestKey.current = null;
      setV2Retest(status);
      persistV2RetestIdentity(status);
      message.success("复测计划和测量身份已冻结，尚未启动外部采样");
    } catch (error: any) {
      message.error(error.message || "创建复测计划失败");
    } finally {
      setV2RetestLoading(false);
    }
  }

  async function refreshV2Retest() {
    if (!projectId || !activePromptId) return;
    const retestId = v2Retest?.retest.retest_id || new URLSearchParams(window.location.search).get("v2_retest");
    if (!retestId) return;
    setV2RetestLoading(true);
    try {
      const status = await api.getSinglePromptV2Retest(retestId, projectId, activePromptId);
      setV2Retest(status);
      setV2RetestPublicationId(status.retest.publication_id);
      persistV2RetestIdentity(status);
    } catch (error: any) {
      setV2Retest(null);
      message.error(error.message || "读取复测状态失败");
    } finally {
      setV2RetestLoading(false);
    }
  }

  async function runV2RetestAction(action: "START" | "RETRY" | "FINALIZE" | "CACHE_ONLY" | "EXTERNAL_LLM" | "COMPARE") {
    if (!projectId || !activePromptId || !v2Retest) return;
    setV2RetestLoading(true);
    try {
      const id = v2Retest.retest.retest_id;
      const status = action === "START" ? await api.startSinglePromptV2RetestSampling(id, projectId, activePromptId)
        : action === "RETRY" ? await api.retrySinglePromptV2RetestSampling(id, projectId, activePromptId)
        : action === "FINALIZE" ? await api.finalizeSinglePromptV2RetestSampling(id, projectId, activePromptId)
        : action === "CACHE_ONLY" ? await api.startSinglePromptV2SemanticMeasurement(id, projectId, activePromptId, false)
        : action === "EXTERNAL_LLM" ? await api.startSinglePromptV2SemanticMeasurement(id, projectId, activePromptId, true)
        : await api.createSinglePromptV2Comparison(id, projectId, activePromptId);
      setV2Retest(status);
      persistV2RetestIdentity(status);
      message.success(action === "START" ? "复测采样已显式启动" : action === "COMPARE" ? "描述性变化报告已生成" : "操作已提交");
    } catch (error: any) {
      message.error(error.message || "复测操作失败");
    } finally {
      setV2RetestLoading(false);
    }
  }

  const workflowMaterializationRequestSeq = useRef(0);
  async function refreshWorkflowMaterializationPlan(promptId?: number | null, targetProjectId: number = projectId!) {
    const targetPromptId = promptId || workflowData?.prompt_id;
    if (!targetProjectId || !targetPromptId) return null;
    const seq = ++workflowMaterializationRequestSeq.current;
    setWorkflowMaterializationLoading(true);
    try {
      const matPlan = await fetch(`/api/optimization/workflow/${targetProjectId}/${targetPromptId}/materialization-plan`).then((r) => r.json());
      if (seq !== workflowMaterializationRequestSeq.current) return null;
      setWorkflowMaterializationPlan(matPlan);
      return matPlan;
    } catch {
      return null;
    } finally {
      if (seq === workflowMaterializationRequestSeq.current) setWorkflowMaterializationLoading(false);
    }
  }

  const workflowRequestSeq = useRef(0);
  async function loadWorkflowForPrompt(pid: number | null, targetProjectId: number = projectId!) {
    if (!targetProjectId) return;
    const seq = ++workflowRequestSeq.current;
    // 切换 Prompt 上下文时重置该 Prompt 专属的执行策略状态
    setWorkflowLoading(true);
    setWorkflowData(null);
    workflowMaterializationRequestSeq.current += 1;
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
    } finally {
      if (seq === workflowRequestSeq.current) setWorkflowLoading(false);
    }
  }

  async function refreshWorkflowStatusForPrompt(promptId?: number | null) {
    const targetPromptId = promptId || workflowData?.prompt_id;
    if (!projectId || !targetPromptId) return null;
    try {
      const wf = await (await fetch(`/api/optimization/workflow/${projectId}/${targetPromptId}/status`)).json();
      setWorkflowData(wf);
      return wf;
    } catch {
      // 状态刷新失败不影响当前页面；下一次轮询或手动刷新会继续校正。
      return null;
    }
  }

  async function refreshWorkflowStatus() {
    return refreshWorkflowStatusForPrompt(workflowData?.prompt_id);
  }

  async function refreshCurrentMainChainDisplay(promptId?: number | null, silent = false) {
    const targetPromptId = promptId || currentCitationDecisionPromptId();
    if (!targetPromptId) return;
    await Promise.allSettled([
      loadCitationDecisionV1(targetPromptId, silent),
      refreshWorkflowStatusForPrompt(targetPromptId),
    ]);
  }

  async function fetchReviewAction(path: string, init: RequestInit, timeoutMs = 20000) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(path, { ...init, signal: controller.signal });
    } catch (error: any) {
      if (error?.name === "AbortError") {
        throw new Error("审核请求超过 20 秒未返回，请稍后点击「加载待审核项」校正当前状态。");
      }
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function fetchReviewJson<T = any>(path: string, timeoutMs = 10000): Promise<T> {
    const response = await fetchReviewAction(path, {}, timeoutMs);
    await assertWorkflowResponse(response, "审核数据加载失败");
    return response.json();
  }

  async function assertWorkflowResponse(response: Response, fallbackMessage: string) {
    if (response.ok) return;
    let detail = "";
    try {
      const payload = await response.json();
      detail = payload?.detail || payload?.message || "";
    } catch {
      detail = await response.text().catch(() => "");
    }
    throw new Error(detail || fallbackMessage);
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
      const [nextPrompts, nextRuns, nextQueue, nextTopics, nextClusters] = RELEASE_FIRST_SLICE
        ? await Promise.all([
          api.listPrompts(id), Promise.resolve([] as BrowserMonitorRun[]), Promise.resolve(emptyQueue),
          api.listTopics(id), api.listPromptClusters(id),
        ])
        : await Promise.all([
          api.listPrompts(id), api.listBrowserAuditRuns(id), api.getBrowserQueueSummary(id),
          api.listTopics(id), api.listPromptClusters(id),
        ]);
      setPrompts(nextPrompts);
      setRuns(nextRuns);
      setQueue(nextQueue);
      setTopics(nextTopics);
      setClusters(nextClusters);
      const params = new URLSearchParams(window.location.search);
      const requestedProjectId = Number(params.get("v2_project"));
      const requestedPromptId = Number(params.get("v2_prompt"));
      if (params.get("v2_analysis") && requestedProjectId === id && nextPrompts.some((item) => item.id === requestedPromptId)) {
        setPromptContext(requestedPromptId);
      } else if (
        RELEASE_FIRST_SLICE
        && nextPrompts.length === 1
        && (!keep || typeof promptContext !== "number" || !nextPrompts.some((item) => item.id === promptContext))
      ) {
        setPromptContext(nextPrompts[0].id);
      }
      // V2 has its own explicit analysis identity and authoritative status.
      if (page !== "coreV2") {
        await loadWorkflowForPrompt(promptFilter, id);
        await loadDashboard(id, promptFilter, nextRuns, nextPrompts);
      }
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
    const promptFilter = typeof promptContext === "number" ? promptContext : null;
    if (page !== "coreV2") {
      loadDashboard(projectId, promptFilter).catch(() => {});
      loadWorkflowForPrompt(promptFilter, projectId).catch(() => {});
    }
  }, [projectId, promptContext, page]);
  useEffect(() => {
    if (page !== "coreV2" || !projectId || !activePromptId) return;
    void refreshV2AnalysisHistory();
    void refreshV2RunPool(1);
    const params = new URLSearchParams(window.location.search);
    if (Number(params.get("v2_project")) !== projectId || Number(params.get("v2_prompt")) !== activePromptId) {
      setV2Analysis(null);
      setV2SelectedRunIds([]);
      setV2SelectedRunFingerprints({});
      setV2Diagnosis(null);
      setV2DiagnosisEdits({});
      setV2SourcePreparation(null);
      setV2SourceDrafts({});
      setV2StrategyReadiness(null);
      setV2Strategy(null);
      setV2Execution(null);
      setV2RetestReadiness(null);
      setV2Retest(null);
      return;
    }
    if (!params.get("v2_analysis")) return;
    void refreshV2Analysis();
  }, [page, projectId, activePromptId]);
  useEffect(() => {
    if (!v2Analysis || !["QUEUED", "COLLECTING"].includes(v2Analysis.sampling.status)) return;
    const timer = window.setInterval(() => { void refreshV2Analysis(); }, 3000);
    return () => window.clearInterval(timer);
  }, [v2Analysis?.analysis.analysis_id, v2Analysis?.sampling.status, projectId, activePromptId]);
  useEffect(() => {
    if (page !== "coreV2" || !v2Analysis?.context_id) return;
    void refreshV2SourcePreparation();
  }, [page, v2Analysis?.analysis.analysis_id, v2Analysis?.context_id, projectId, activePromptId]);
  useEffect(() => {
    if (!v2SourcePreparation || !["AUTO_FETCH_QUEUED", "AUTO_FETCHING"].includes(v2SourcePreparation.preparation.status)) return;
    const timer = window.setInterval(() => { void refreshV2SourcePreparation(true); }, 3000);
    return () => window.clearInterval(timer);
  }, [v2SourcePreparation?.preparation.preparation_id, v2SourcePreparation?.preparation.status, projectId, activePromptId]);
  useEffect(() => {
    if (page !== "coreV2" || !v2Analysis?.context_id) return;
    const params = new URLSearchParams(window.location.search);
    if (!params.get("v2_diagnosis")) return;
    if (v2Diagnosis?.diagnosis.analysis_id === v2Analysis.analysis.analysis_id) return;
    void refreshV2Diagnosis();
  }, [page, v2Analysis?.analysis.analysis_id, v2Analysis?.context_id, projectId, activePromptId]);
  useEffect(() => {
    if (!v2Diagnosis || !["QUEUED", "RUNNING", "EVIDENCE_QUEUED", "EVIDENCE_RUNNING"].includes(v2Diagnosis.compute_status)) return;
    const timer = window.setInterval(() => { void refreshV2Diagnosis(); }, 3000);
    return () => window.clearInterval(timer);
  }, [v2Diagnosis?.diagnosis.diagnosis_id, v2Diagnosis?.compute_status, projectId, activePromptId]);
  useEffect(() => {
    setV2AnswerReviewDecisions({});
  }, [v2Diagnosis?.diagnosis.diagnosis_id]);
  useEffect(() => {
    if (page !== "coreV2" || !v2Diagnosis?.result || v2Diagnosis.compute_status !== "READY_FOR_REVIEW") return;
    void refreshV2StrategyContext(v2Diagnosis);
  }, [page, v2Diagnosis?.diagnosis.diagnosis_id, v2Diagnosis?.result?.result_version, v2Diagnosis?.review?.review_id, projectId, activePromptId]);
  useEffect(() => {
    if (RELEASE_FIRST_SLICE) return;
    if (page !== "coreV2" || !v2Strategy?.result || !v2Strategy.review) return;
    const proposalId = new URLSearchParams(window.location.search).get("v2_execution_proposal");
    if (!proposalId || v2Execution?.proposal.strategy_id === v2Strategy.strategy.strategy_id) return;
    void refreshV2Execution();
  }, [page, v2Strategy?.strategy.strategy_id, v2Strategy?.result?.result_version, v2Strategy?.review?.review_id, projectId, activePromptId]);
  useEffect(() => {
    if (RELEASE_FIRST_SLICE) return;
    if (page !== "coreV2" || !projectId || !activePromptId || !v2Diagnosis?.result) return;
    const retestId = new URLSearchParams(window.location.search).get("v2_retest");
    if (retestId) {
      if (v2Retest?.retest.retest_id !== retestId) void refreshV2Retest();
      return;
    }
    if (!v2RetestReadiness) void refreshV2RetestReadiness("");
  }, [page, projectId, activePromptId, v2Diagnosis?.result?.result_version, v2Execution?.publications.length]);
  useEffect(() => {
    if (RELEASE_FIRST_SLICE) return;
    if (!v2Retest || !["SAMPLING", "SEMANTIC_MEASURING"].includes(v2Retest.retest.status)) return;
    const timer = window.setInterval(() => { void refreshV2Retest(); }, 3000);
    return () => window.clearInterval(timer);
  }, [v2Retest?.retest.retest_id, v2Retest?.retest.status, projectId, activePromptId]);
  useEffect(() => {
    const status = workflowData?.strategy_step_status || workflowData?.strategy_step?.status;
    if (!projectId || !workflowData?.prompt_id || status !== "CURRENT_ANALYSIS_RUNNING") return;
    const timer = window.setInterval(() => {
      void refreshWorkflowStatusForPrompt(workflowData.prompt_id);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [projectId, workflowData?.prompt_id, workflowData?.strategy_step_status, workflowData?.strategy_step?.status]);
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
    if (RELEASE_FIRST_SLICE) return;
    if (!projectId || activePromptId) { setPromptOverview(null); return; }
    fetch(`/api/optimization/workflow/${projectId}/prompt-overview`)
      .then((r) => r.json()).then(setPromptOverview).catch(() => { /* 概览失败不影响页面 */ });
  }, [projectId, activePromptId]);
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
    if (!workflowData || Number(workflowData.prompt_id) !== Number(targetPromptId)) {
      return;
    }
    if (
      !workflowData.steps?.some((step: any) => step.key === "answer_semantic" && step.done)
    ) {
      setCitationDecisionData(null);
      setCitationDecisionError(null);
      return;
    }
    const workflowSteps = workflowData?.steps || [];
    const evidenceReviewStep = workflowSteps.find((step: any) => step.key === "evidence_review");
    if (evidenceReviewStep && !evidenceReviewStep.done) {
      citationDecisionRequestSeq.current += 1;
      setCitationDecisionLoading(false);
      setCitationDecisionData(null);
      setCitationDecisionError(null);
      return;
    }
    const strategyStatus = workflowData?.strategy_step_status || workflowData?.strategy_step?.status || "";
    if (
      [
        "PENDING_REVIEW",
        "CONFIRMED",
        "NO_STRATEGY",
        "NEEDS_CURRENT_ANALYSIS",
        "CURRENT_ANALYSIS_RUNNING",
        "CURRENT_ANALYSIS_FAILED",
      ].includes(strategyStatus)
    ) {
      citationDecisionRequestSeq.current += 1;
      setCitationDecisionLoading(false);
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

  function initialStep8Edit(proposal: any) {
    const packageKey = proposal.selected_asset_package_key || undefined;
    const selectedPlan = (proposal.section_plan_candidates || []).find((item: any) => item.asset_package_key === packageKey);
    return {
      execute_this_proposal: undefined,
      selected_asset_package_key: packageKey,
      selected_asset_type: proposal.recommended_asset_type || undefined,
      title: proposal.title_candidates?.[0]?.title || "",
      section_order: (selectedPlan?.section_plan || []).map((item: any) => item.section_id),
      publishing_metadata: {
        publishing_account: "",
        publishing_location: "",
        url_slug: "",
        channel_specific_posting_metadata: {},
      },
      selected_observation_window_index: proposal.validation_plan?.observation_window_candidates?.length === 1 ? 0 : undefined,
    };
  }

  function updateStep8Edit(proposalKey: string, patch: Record<string, any>) {
    setStep8ProposalEdits((previous) => ({
      ...previous,
      [proposalKey]: { ...(previous[proposalKey] || {}), ...patch },
    }));
    setStep8ValidationResult(null);
  }

  async function openStep8ExecutionConfig(candidate: any) {
    if (!projectId) {
      message.warning("请先选择项目");
      return;
    }
    const promptId = currentCitationDecisionPromptId();
    if (!promptId) {
      message.warning("请先进入具体 Prompt 的工作台");
      return;
    }
    setStep8Candidate(candidate);
    setStep8ProposalData(null);
    setStep8ProposalEdits({});
    setStep8ValidationResult(null);
    setStep8ModalOpen(true);
    setStep8AssetsLoading(true);
    try {
      const result = await api.getExecutionProposalShadow(projectId, promptId, candidate.id);
      const edits = Object.fromEntries(
        (result.active_proposals || []).map((proposal: any) => [proposal.proposal_key, initialStep8Edit(proposal)])
      );
      setStep8ProposalData(result);
      setStep8ProposalEdits(edits);
    } catch (error: any) {
      message.error(error.message || "执行方案建议加载失败");
    } finally {
      setStep8AssetsLoading(false);
    }
  }

  async function revalidateStep8Proposal(proposal: any) {
    if (!step8Candidate || !projectId) return;
    const promptId = currentCitationDecisionPromptId();
    if (!promptId) return;
    try {
      const result = await api.revalidateExecutionProposal(projectId, promptId, {
        strategy_candidate_id: step8Candidate.id,
        proposal_key: proposal.proposal_key,
        edited_by: "human",
        human_edits: step8ProposalEdits[proposal.proposal_key] || {},
      });
      setStep8ValidationResult((previous: any) => ({
        ...(previous || {}),
        single_results: { ...(previous?.single_results || {}), [proposal.proposal_key]: result },
      }));
    } catch (error: any) {
      message.error(error.message || "执行方案校验失败");
    }
  }

  async function submitStep8ExecutionPlan() {
    if (!step8Candidate || !projectId || !step8ProposalData) return;
    const promptId = currentCitationDecisionPromptId();
    if (!promptId) return;
    setStep8Submitting(true);
    try {
      const result = await api.revalidateExecutionProposalPortfolio(projectId, promptId, {
        strategy_candidate_id: step8Candidate.id,
        edited_by: "human",
        proposal_edits: (step8ProposalData.active_proposals || []).map((proposal: any) => ({
          proposal_key: proposal.proposal_key,
          human_edits: step8ProposalEdits[proposal.proposal_key] || {},
        })),
      });
      setStep8ValidationResult(result);
      if (result.ready_for_freeze) {
        message.success("执行方案已通过重校验，已具备进入 PR5-C 冻结的条件");
      } else if (result.portfolio_readiness === "HAS_INVALID_EDIT") {
        message.error("存在非法编辑，请按卡片中的具体原因修正");
      } else {
        message.warning("执行方案仍有必选项未完成");
      }
    } catch (error: any) {
      message.error(error.message || "执行方案组合校验失败");
    } finally {
      setStep8Submitting(false);
    }
  }

  async function openExperimentDraftForStrategy(candidate: any) {
    const plan = experimentPlanPayload(candidate?.experiment_plan);
    const actionId = Number(plan?.action_id || plan?.action_snapshot?.action_id || candidate?.action_id);
    const experimentId = Number(plan?.experiment_id || candidate?.experiment_id);
    if (!actionId && !experimentId) {
      openStep8ExecutionConfig(candidate);
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
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 20000);
    setCitationDecisionLoading(true);
    setCitationDecisionError(null);
    setCitationDecisionData(null);
    try {
      const data = await api.getCitationDecisionV1(
        projectId,
        targetPromptId,
        undefined,
        CURRENT_CITATION_DECISION_USE_ANSWER_BINDING_V1_1,
        { signal: controller.signal },
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
      const errorMessage = error?.name === "AbortError"
        ? "引用资料优化决策超过 20 秒未返回，已停止等待；证据待确认时可继续审核。"
        : error.message || "引用资料优化决策运行失败";
      setCitationDecisionData(null);
      setCitationDecisionError(errorMessage);
      if (!silent) message.error(errorMessage);
      return null;
    } finally {
      window.clearTimeout(timeout);
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
    setWorkflowActionLoadingKey("citation");
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
      setWorkflowActionLoadingKey(null);
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
    setWorkflowActionLoadingKey("strategy");
    try {
      const workflowPackageId = currentWorkflowData?.current_state_context?.evidence_package_id || selectedPkgId;
      const latest = citationDecisionBelongsToPrompt(currentCitationDecisionData, targetPromptId)
        ? currentCitationDecisionData
        : (!currentReadyToGenerateStrategy || !workflowPackageId)
          ? await loadCitationDecisionV1(targetPromptId, true)
          : null;
      if (!latest && (!currentReadyToGenerateStrategy || !workflowPackageId)) {
        message.warning("当前主链详情未加载完成，请先点击「刷新主链路」或稍后重试");
        return;
      }
      const actionKeys = (latest?.recommended_actions || [])
        .filter((item: any) => item.route === "CONTENT" || item.route === "EVIDENCE")
        .map((item: any) => item.action_key)
        .filter(Boolean);
      if (latest && actionKeys.length === 0) {
        const blockedCount = (latest.source_analysis || []).filter((row: any) =>
          (row.benchmark_tier === "PRIMARY_BENCHMARK" || row.benchmark_tier === "SECONDARY_BENCHMARK") &&
          row.source_gap_precondition === "PRODUCT_TRUTH_UNKNOWN"
        ).length;
        message.warning(blockedCount > 0
          ? `还有 ${blockedCount} 条对标来源缺少目标品牌产品事实，暂不能生成策略候选`
          : "当前没有可生成策略候选的内容/证据缺口；可能没有真实缺口，或只剩产品评估/不需要动作");
        return;
      }
      const result = await api.generateCurrentStep7StrategyCandidateV1(projectId, targetPromptId, {
        evidence_package_id: latest?.evidence_package_id || workflowPackageId,
        use_answer_binding_v1_1: typeof latest?.use_answer_binding_v1_1 === "boolean"
          ? latest?.use_answer_binding_v1_1
          : CURRENT_CITATION_DECISION_USE_ANSWER_BINDING_V1_1,
        action_keys: actionKeys,
        reviewer: "human",
        review_note: "前端生成引用证据链路策略候选",
      });
      const createdIds = (result.created || [])
        .map((item: any) => item.strategy_candidate?.id)
        .filter(Boolean);
      const generatedPackageId = latest?.evidence_package_id || workflowPackageId;
      if (generatedPackageId) {
        await selectEvidencePackage(generatedPackageId, true);
      }
      setPage("optimization");
      message.success(`已生成 ${createdIds.length || actionKeys.length} 个待审核策略候选，请在下方审核确认`);
      await Promise.allSettled([
        loadWorkflowForPrompt(targetPromptId, projectId),
        loadOptimizationIssues(),
      ]);
      setLatestGeneratedStrategyIds(createdIds);
      setStrategyCandidateFilter(createdIds.length ? `candidate:${createdIds[0]}` : "latest");
    } catch (error: any) {
      message.error(error.message || "生成策略候选失败");
      if (projectId && targetPromptId) {
        await loadWorkflowForPrompt(targetPromptId, projectId).catch(() => {});
      }
    } finally {
      setCitationDecisionLoading(false);
      setWorkflowActionLoadingKey(null);
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
    setWorkflowActionLoadingKey("analysis");
    try {
      const response = await fetch(`/api/optimization/workflow/${projectId}/${targetPromptId}/run-analysis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ use_answer_binding_v1_1: true }),
      });
      if (!response.ok) throw new Error(await response.text());
      const result = await response.json();
      message.success(result.already_running
        ? "V1.1 正式证据输入已在后台生成中，完成后刷新状态"
        : "已开始生成 V1.1 正式证据输入，完成后再生成策略候选");
      const wf = await (await fetch(`/api/optimization/workflow/${projectId}/${targetPromptId}/status`)).json();
      setWorkflowData(wf);
    } catch (error: any) {
      message.error(error.message || "生成 V1.1 正式证据输入失败");
    } finally {
      setCitationDecisionLoading(false);
      setWorkflowActionLoadingKey(null);
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
      const workflowReadyForTarget = Boolean(
        Number(currentWorkflowData?.prompt_id) === Number(targetPromptId) &&
        currentReadyToGenerateStrategy
      );
      const workflowPackageId = workflowReadyForTarget
        ? currentWorkflowData?.current_state_context?.evidence_package_id
        : null;
      const latest = citationDecisionBelongsToPrompt(currentCitationDecisionData, targetPromptId)
        ? currentCitationDecisionData
        : null;
      if (!latest && !workflowReadyForTarget) {
        throw new Error("当前主链状态未确认可生成，请先刷新当前 Prompt 工作流状态。");
      }
      const actionKeys = (latest?.recommended_actions || [])
        .filter((item: any) => item.route === "CONTENT" || item.route === "EVIDENCE")
        .map((item: any) => item.action_key)
        .filter(Boolean);
      if (latest && actionKeys.length === 0) {
        throw new Error("当前没有可生成策略候选的内容/证据缺口；历史策略不会计入当前第 7 步。");
      }
      const generated = await api.generateCurrentStep7StrategyCandidateV1(projectId, targetPromptId, {
        evidence_package_id: workflowPackageId || selectedPkgId,
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
      const selectedPackage = (evidencePackages || []).find((item: any) => Number(item.id) === Number(selectedPkgId));
      const targetPromptId = Number(selectedPackage?.prompt_id || currentCitationDecisionPromptId());
      if (projectId && targetPromptId) {
        await loadWorkflowForPrompt(targetPromptId, projectId).catch(() => {});
      }
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
  const currentReadyToGenerateStrategy = backendStrategyStepStatus === "READY_TO_GENERATE";
  const workflowStepButtonLoading = (stepKey: string) => {
    if (stepKey === "citation") return workflowActionLoadingKey === "citation";
    if (stepKey === "action") return workflowActionLoadingKey === "strategy" || workflowActionLoadingKey === "analysis";
    return false;
  };
  const backendCurrentStrategyIds = new Set(
    (currentWorkflowData?.current_strategy_candidate_ids || backendStrategyStep.current_strategy_candidate_ids || [])
      .map((id: any) => Number(id))
      .filter(Boolean)
  );
  const backendCurrentStrategyIdList = Array.from(backendCurrentStrategyIds);
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
  const backendCurrentStrategyCandidateCount = backendCurrentStrategyIds.size;
  const strategyCandidateCount = Math.max(workflowCurrentPackageStrategies.length, backendCurrentStrategyCandidateCount);
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
  const evidenceStep = workflowStepByKey("evidence");
  const evidenceReviewStep = workflowStepByKey("evidence_review");
  const gapWorkflowStep = workflowStepByKey("gap");
  const strategyWorkflowStep = workflowStepByKey("strategy") || workflowStepByKey("strategy_candidate") || workflowStepByKey("action");
  const backendStrategyStepDetail = currentWorkflowData?.strategy_step_detail || backendStrategyStep.detail || strategyWorkflowStep?.detail || "";
  const backendExecutionStepDetail = currentWorkflowData?.execution_step_detail || backendExecutionStep.detail || "";
  const evidenceReviewDone = Boolean(answerStepDone && evidenceReviewStep?.done);
  const evidenceAvailable = Boolean(answerStepDone && (citationLoaded || evidenceStep?.done));
  const evidenceNeedsHumanReview = Boolean(answerStepDone && evidenceAvailable && evidenceReviewStep && !evidenceReviewDone);
  const strategyWorkflowDone = Boolean(answerStepDone && strategyWorkflowStep?.done);
  const currentEvidenceDone = Boolean(answerStepDone && evidenceStep?.done);
  const currentCitationLoaded = Boolean(answerStepDone && citationLoaded);
  const currentWorkflowEvidenceLoaded = Boolean(answerStepDone && evidenceAvailable);
  const currentCitationNeedsEvidencePackage = Boolean(answerStepDone && citationNeedsEvidencePackage);
  const citationGapDecisionDone = Boolean(
    currentWorkflowEvidenceLoaded &&
    evidenceReviewDone &&
    !citationProductTruthBlockedRows.length &&
    (currentReadyToGenerateStrategy || currentNoStrategyNeeded || unknownGapCount === 0)
  );
  const backendStrategyGateReady = [
    "READY_TO_GENERATE",
    "PENDING_REVIEW",
    "CONFIRMED",
    "NO_STRATEGY",
  ].includes(backendStrategyStepStatus);
  const strategyCurrentChainReady = Boolean(
    (currentWorkflowEvidenceLoaded && evidenceReviewDone && citationGapDecisionDone) ||
    backendStrategyGateReady
  );
  const currentConfirmedStrategies = strategyCurrentChainReady ? confirmedStrategies : [];
  const currentPendingStrategies = strategyCurrentChainReady ? pendingStrategies : [];
  const currentStrategyCandidateCount = strategyCurrentChainReady ? strategyCandidateCount : 0;
  const currentConfirmedStrategyCount = backendStrategyStepStatus === "CONFIRMED"
    ? Math.max(currentConfirmedStrategies.length, backendCurrentStrategyCandidateCount)
    : currentConfirmedStrategies.length;
  const currentPendingStrategyCount = backendStrategyStepStatus === "PENDING_REVIEW"
    ? Math.max(currentPendingStrategies.length, backendCurrentStrategyCandidateCount)
    : currentPendingStrategies.length;
  const currentLatestStrategyCandidate = strategyCurrentChainReady ? latestStrategyCandidate : null;
  const currentCitationCanConfirm = Boolean(answerStepDone && evidenceReviewDone && currentReadyToGenerateStrategy);
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
      description: citationLoaded ? `${citationSummary.source_count ?? 0} 个来源` : currentEvidenceDone ? (evidenceStep?.detail || "证据已确认") : "等待加载",
      status: citationLoaded || currentEvidenceDone ? "finish" : citationDecisionError ? "error" : "wait",
    },
    {
      title: "对标来源",
      description: citationLoaded ? `核心 ${citationSummary.primary_benchmark_count ?? 0} / 辅助 ${citationSummary.secondary_benchmark_count ?? 0}` : currentWorkflowEvidenceLoaded && evidenceReviewDone ? "证据已确认，详情可刷新" : "等待来源资格判断",
      status: citationLoaded ? ((citationSummary.primary_benchmark_count || citationSummary.secondary_benchmark_count) ? "finish" : "process") : currentWorkflowEvidenceLoaded && evidenceReviewDone ? "finish" : "wait",
    },
    {
      title: "缺口",
      description: citationProductTruthBlockedRows.length ? `${citationProductTruthBlockedRows.length} 条卡在产品事实` : citationLoaded ? "已完成资格判断" : gapWorkflowStep?.done ? (gapWorkflowStep.detail || "已完成缺口判断") : "等待对标结果",
      status: citationProductTruthBlockedRows.length ? "error" : currentCitationDecisionData || gapWorkflowStep?.done ? "finish" : "wait",
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
          ? "有上游线索，待生成 V1.1 输入"
        : currentNoStrategyNeeded
          ? "本轮无需策略候选"
        : currentCitationCanConfirm
          ? (backendStrategyStepDetail || "证据审核完成，可生成策略候选")
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
          ? "先重新生成 V1.1 输入"
        : currentNeedsCurrentAnalysis
          ? "等待 V1.1 输入生成策略候选"
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
  const mainChainStatusTagLabel = currentCitationDecisionData
    ? citationDecisionStatusLabel(currentCitationDecisionData.status)
    : currentWorkflowData
      ? "主链状态已同步"
      : citationDecisionStatusLabel(undefined);
  const mainChainStatusTagColor = currentCitationDecisionData
    ? citationDecisionStatusColor(currentCitationDecisionData.status)
    : currentWorkflowData
      ? "blue"
      : citationDecisionStatusColor(undefined);
  const citationDetailNonBlockingError = Boolean(answerStepDone && citationDecisionError && (currentWorkflowEvidenceLoaded || backendStrategyGateReady));
  const citationDetailBlockingError = Boolean(answerStepDone && citationDecisionError && !citationDetailNonBlockingError);
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
      statusText: !answerStepDone ? "未开始" : evidenceNeedsHumanReview ? "待人工确认" : currentCitationLoaded || currentEvidenceDone ? "已完成" : citationDecisionLoading ? "运行中" : currentCitationNeedsEvidencePackage ? "待生成证据包" : citationDecisionError ? "待重试" : "待运行",
      detail: !answerStepDone ? "先完成答案决策识别" : evidenceNeedsHumanReview ? (evidenceReviewStep?.detail || "证据关系待人工确认") : currentCitationLoaded ? `${citationSummary.source_count ?? 0} 个当前来源，正文和证据关系已确认` : currentEvidenceDone ? (evidenceStep?.detail || "引用证据已生成并确认，完整详情可手动刷新") : currentCitationNeedsEvidencePackage ? "当前问题尚无证据包；正文已补齐后可直接生成并运行" : citationDecisionError ? "当前链路运行失败，可重试或核对引用正文" : "生成当前问题的证据包，并运行引用正文和证据对齐",
      tone: evidenceNeedsHumanReview ? "current" : currentCitationLoaded || currentEvidenceDone ? "done" : answerStepDone && citationDecisionLoading ? "current" : "pending",
      actionLabel: answerStepDone ? (evidenceNeedsHumanReview ? "审核证据关系" : currentCitationLoaded || currentEvidenceDone ? "查看证据正文" : currentCitationNeedsEvidencePackage || citationDecisionError ? "生成证据包" : "运行引用证据") : "",
      onAction: answerStepDone
        ? evidenceNeedsHumanReview
          ? () => setWorkflowReviewOpen(true)
          : currentCitationLoaded || currentEvidenceDone
          ? () => openGoldenCaseWorkspaceForPrompt(citationTargetPromptId)
          : () => runCitationEvidenceForPrompt(citationTargetPromptId)
        : undefined,
    },
    {
      key: "benchmark",
      label: "对标来源",
      statusText: !currentWorkflowEvidenceLoaded ? "未开始" : !evidenceReviewDone ? "等待证据确认" : "已判断",
      detail: !currentWorkflowEvidenceLoaded ? "等待引用证据" : !evidenceReviewDone ? "先确认来源原文是否支持 AI 理由" : currentCitationLoaded ? (eligibleBenchmarkCount > 0 ? `核心 ${citationSummary.primary_benchmark_count ?? 0} / 辅助 ${citationSummary.secondary_benchmark_count ?? 0}` : "0 个可信对标（允许）") : "证据已确认，完整对标详情可手动刷新",
      tone: currentWorkflowEvidenceLoaded && evidenceReviewDone ? "done" : "pending",
      actionLabel: currentWorkflowEvidenceLoaded && evidenceReviewDone ? "查看对标" : "",
      onAction: currentWorkflowEvidenceLoaded && evidenceReviewDone ? () => setPage("optimization") : undefined,
    },
    {
      key: "gap",
      label: "缺口诊断",
      statusText: !currentWorkflowEvidenceLoaded ? "未开始" : !evidenceReviewDone ? "等待证据确认" : currentCitationLoaded ? (eligibleBenchmarkCount === 0 ? "暂无缺口" : unknownGapCount > 0 ? "待人工判断" : "已完成") : (gapWorkflowStep?.done ? "已完成" : "待加载"),
      detail: !currentWorkflowEvidenceLoaded ? "等待对标来源" : !evidenceReviewDone ? "先完成引用证据人工确认" : currentCitationLoaded ? (eligibleBenchmarkCount === 0 ? "暂无可分析 Benchmark，不生成竞争缺口" : unknownGapCount > 0 ? `${unknownGapCount} 条缺口需要人工判断` : "已基于对标来源完成缺口判断") : (gapWorkflowStep?.detail || "证据已确认，完整缺口详情可手动刷新"),
      tone: !currentWorkflowEvidenceLoaded || !evidenceReviewDone ? "pending" : unknownGapCount > 0 ? "current" : "done",
      actionLabel: currentWorkflowEvidenceLoaded && evidenceReviewDone ? "查看缺口" : "",
      onAction: currentWorkflowEvidenceLoaded && evidenceReviewDone ? () => setPage("optimization") : undefined,
    },
    {
      key: "action",
      label: "策略确认",
      statusText: currentConfirmedStrategyCount ? "已确认" : currentPendingStrategyCount ? "待审核" : currentCitationCanConfirm ? "可生成" : currentAnalysisRunning ? "主链运行中" : currentAnalysisFailed ? "运行失败" : currentNeedsCurrentAnalysis ? "待生成输入" : currentNoStrategyNeeded ? "无需策略" : !currentCitationLoaded ? "未开始" : !evidenceReviewDone ? "待证据审核" : !citationGapDecisionDone ? "等待缺口" : unresolvedAction || unknownGapCount > 0 ? "待人工判断" : "无策略",
      detail: currentConfirmedStrategyCount
        ? `已确认策略 #${currentConfirmedStrategies[0]?.id || currentLatestStrategyCandidate?.id || backendCurrentStrategyIdList[0] || "-"}`
        : currentPendingStrategyCount
          ? `${currentPendingStrategyCount} 个当前策略候选待人工审核`
          : currentCitationCanConfirm
            ? (backendStrategyStepDetail || `${citationConfirmableActions.length} 个缺口可生成策略候选`)
          : currentAnalysisRunning
            ? (backendStrategyStepDetail || "当前主链正在后台运行")
          : currentAnalysisFailed
            ? (backendStrategyStepDetail || "当前主链运行失败，请重试或查看日志")
          : currentNeedsCurrentAnalysis
            ? (backendStrategyStepDetail || "当前有答案决策/证据线索，但尚未生成 V1.1 正式证据输入")
            : currentNoStrategyNeeded
              ? "本轮没有可生成策略的内容/证据缺口"
            : !currentCitationLoaded
              ? (strategyWorkflowStep?.detail || "等待缺口诊断")
              : !evidenceReviewDone
                ? (evidenceReviewStep?.detail || "先完成人工证据审核，历史策略不计入当前主链")
                : !citationGapDecisionDone
                  ? (gapWorkflowStep?.detail || "先生成当前缺口诊断")
                  : unresolvedAction || unknownGapCount > 0
                    ? "请查看依据后人工判断，不自动生成策略"
                    : "没有可生成策略的内容/证据缺口",
      tone: currentConfirmedStrategyCount || currentNoStrategyNeeded ? "done" : currentAnalysisFailed ? "error" : currentPendingStrategyCount || currentCitationCanConfirm || currentAnalysisRunning || currentNeedsCurrentAnalysis || unresolvedAction ? "current" : "pending",
      actionLabel: currentConfirmedStrategyCount ? "查看已确认策略" : currentPendingStrategyCount ? "审核策略候选" : currentCitationCanConfirm ? "生成策略候选" : currentAnalysisRunning ? "运行中" : currentAnalysisFailed ? "重新生成 V1.1 输入" : currentNeedsCurrentAnalysis ? "生成 V1.1 输入" : currentNoStrategyNeeded || unresolvedAction ? "查看依据" : "",
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
      statusText: currentExperimentCount ? "已创建" : currentConfirmedStrategyCount ? "待创建" : currentAnalysisRunning ? "等待主链" : currentAnalysisFailed ? "等待输入" : currentNeedsCurrentAnalysis ? "等待输入" : currentNoStrategyNeeded ? "无需创建" : currentWorkflowEvidenceLoaded ? "未创建" : "未开始",
      detail: currentExperimentCount
        ? `${currentExperimentCount} 个当前草案/实验，等待发布闸门`
        : ignoredHistoricalExperimentCount && !currentConfirmedStrategyCount
          ? "存在历史草案/实验，但当前主链仍需先完成策略确认"
        : currentAnalysisRunning
            ? (backendExecutionStepDetail || "当前主链运行完成后，再进入策略确认")
          : currentAnalysisFailed
            ? (backendExecutionStepDetail || "先修复并重新生成 V1.1 正式证据输入")
          : currentNeedsCurrentAnalysis
            ? (backendExecutionStepDetail || "先生成 V1.1 正式证据输入，再进入策略确认")
          : currentNoStrategyNeeded
            ? "本轮没有策略候选，无需实验草案"
          : currentConfirmedStrategyCount
            ? "策略确认后，进入执行方案和实验草案"
            : currentWorkflowEvidenceLoaded
              ? "等待策略确认"
              : "等待策略候选",
      tone: currentExperimentCount || currentNoStrategyNeeded ? "done" : currentAnalysisFailed ? "error" : currentConfirmedStrategyCount || currentAnalysisRunning || currentNeedsCurrentAnalysis || currentCitationCanConfirm ? "current" : "pending",
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
  const materializationPartSummary = (part: any, fallbackRequiredKey: string, fallbackLlmKey: string) => {
    const conservation = part?.object_conservation || {};
    const missingConservation = part?.missing_conservation || {};
    const required = Number(conservation.required_unique_inputs ?? part?.[fallbackRequiredKey] ?? 0);
    const ledgerHit = Number(conservation.materialization_hit ?? part?.materialization_hit_count ?? part?.hit ?? 0);
    const legacy = Number(conservation.legacy_reuse ?? part?.legacy_reuse_count ?? 0);
    const missing = Number(conservation.missing ?? part?.missing_count ?? 0);
    const stale = Number(conservation.stale ?? part?.stale_count ?? 0);
    const inProgress = Number(conservation.in_progress ?? part?.in_progress_count ?? 0);
    const failedRetryable = Number(conservation.failed_retryable ?? part?.failed_retryable_count ?? 0);
    const failedFinal = Number(conservation.failed_final ?? part?.failed_final_count ?? 0);
    const llmCache = Number(part?.missing_llm_call_cache_hit ?? part?.llm_call_cache_hit_pairs ?? 0);
    const external = Number(part?.[fallbackLlmKey] ?? part?.lookup_first_llm_required ?? 0);
    const doneLike = ledgerHit + legacy;
    return {
      required,
      ledgerHit,
      legacy,
      missing,
      stale,
      inProgress,
      failedRetryable,
      failedFinal,
      llmCache,
      external,
      conservationOk: Boolean(conservation.is_balanced ?? missingConservation.is_balanced ?? true),
      progress: required ? Math.round((doneLike / required) * 100) : 100,
    };
  };
  const sourceClaimMat = materializationPartSummary(workflowMaterializationPlan?.source_claims, "required_semantic_passages", "lookup_first_llm_required");
  const alignmentMat = materializationPartSummary(workflowMaterializationPlan?.evidence_alignment, "unique_alignment_inputs", "actual_llm_required");
  const materializationRemaining = sourceClaimMat.missing + sourceClaimMat.stale + sourceClaimMat.failedRetryable + alignmentMat.missing + alignmentMat.stale + alignmentMat.failedRetryable;
  const materializationFailedFinal = sourceClaimMat.failedFinal + alignmentMat.failedFinal;
  const unresolvedReviewContext = currentContinueResult?.review_context || {};
  const unresolvedAnswerSamples = unresolvedReviewContext.answer_samples || [];
  const unresolvedEventDiagnostics = unresolvedReviewContext.event_diagnostics || [];
  const unresolvedEventStatusCounts = unresolvedReviewContext.event_status_counts || {};
  const decisionMarketUnknownEntities = decisionMarketEntities.filter((item: any) => item.relationship === "UNKNOWN_ENTITY");
  const v2DiagnosisOutput = v2Diagnosis?.result?.output;
  const v2DiagnosisEvents = v2DiagnosisOutput?.answer_diagnosis?.events || [];
  const v2PendingSemanticEvents = v2DiagnosisEvents
    .filter(v2AnswerEventNeedsReview)
    .sort((left: any, right: any) => {
      const brandName = String(project?.brand_name || "").trim();
      const leftTarget = brandName && String(left.entity_text || "").includes(brandName) ? 0 : 1;
      const rightTarget = brandName && String(right.entity_text || "").includes(brandName) ? 0 : 1;
      return leftTarget - rightTarget || Number(left.run_id || 0) - Number(right.run_id || 0) || String(left.entity_text || "").localeCompare(String(right.entity_text || ""));
    });
  const v2VerifiedSemanticEvents = v2DiagnosisEvents.filter((event: any) => !v2AnswerEventNeedsReview(event));
  const v2PriorAnswerReviewDecisions = v2DiagnosisOutput?.truth_reprojection?.prior_review?.decisions || [];
  const v2StoredAnswerReviewDecisions = new Map(
    (v2Diagnosis?.review?.decisions || v2PriorAnswerReviewDecisions)
      .filter((row: any) => row.scope === "ANSWER_SEMANTIC_EVENT" && row.event_id)
      .map((row: any) => [row.event_id, row.decision]),
  );
  const v2AnsweredSemanticReviewCount = v2PendingSemanticEvents.filter(
    (event: any) => v2AnswerReviewDecisions[event.event_id] || v2StoredAnswerReviewDecisions.has(event.event_id),
  ).length;
  const v2MarketCriteria = v2DiagnosisOutput?.answer_diagnosis?.market_criteria || [];
  const v2AnswerJobs = v2DiagnosisOutput?.answer_diagnosis?.answer_jobs || [];
  const v2AnswerEligibility = v2Diagnosis?.answer_semantic_eligibility;
  const v2NoConsumableAnswerSemantic = Boolean(v2AnswerEligibility?.no_consumable_answer_semantic_result);
  const v2MixedAnswerBoundary = v2AnswerEligibility?.status === "BLOCKED_MIXED_ANSWER_BOUNDARY";
  const v2DiagnosisReasons = v2DiagnosisEvents.flatMap((event: any) => event.reasons || []);
  const v2DiagnosisReasonById = new Map(v2DiagnosisReasons.map((reason: any) => [reason.reason_id, reason]));
  const v2DiagnosisSnapshots = v2DiagnosisOutput?.source_diagnosis?.snapshots || [];
  const v2DiagnosisSnapshotById = new Map(v2DiagnosisSnapshots.map((source: any) => [source.snapshot_id, source]));
  const v2DiagnosisRelations = v2DiagnosisOutput?.evidence_diagnosis?.source_relations || [];
  const v2EvidenceClaimJobs = v2DiagnosisOutput?.evidence_diagnosis?.source_claim_jobs || [];
  const v2EvidenceEvaluatedRelations = v2DiagnosisRelations.filter((row: any) => row.alignment_evaluation === "EVALUATED");
  const v2EvidenceRecalledRelations = v2DiagnosisRelations.filter((row: any) => row.candidate_recall === "RECALLED");
  const v2EvidenceUpstreamFailedRelations = v2DiagnosisRelations.filter((row: any) => row.alignment_evaluation === "UPSTREAM_CLAIM_FAILED");
  const v2EvidenceNotRecalledRelations = v2DiagnosisRelations.filter((row: any) => row.candidate_recall !== "RECALLED");
  const v2EvidenceFailedClaimJobs = v2EvidenceClaimJobs.filter((row: any) => String(row.status || "").startsWith("FAILED") || row.status === "CACHE_REJECTED_BY_V2_VALIDATION");
  const v2IsEvidenceResult = v2DiagnosisOutput?.result_scope === "ANSWER_AND_EVIDENCE";
  const v2AnswerReviewConsumed = Boolean(v2DiagnosisOutput?.input?.answer_review_id) || (!v2IsEvidenceResult && Boolean(v2Diagnosis?.review));
  const v2EvidenceReviewComplete = Boolean(v2IsEvidenceResult && v2Diagnosis?.review?.result_version === v2Diagnosis?.result?.result_version);
  const v2AnalysisFlowItems = [
    { title: "采样冻结", status: v2Analysis?.context_id ? "finish" : "wait" },
    { title: "引用与正文", status: v2SourcePreparation?.completion_manifest?.status === "FROZEN" ? "finish" : v2SourcePreparation ? "process" : "wait" },
    { title: "回答分析", status: v2Diagnosis?.result ? "finish" : v2Diagnosis ? "process" : "wait" },
    { title: "回答审核", status: v2AnswerReviewConsumed ? "finish" : v2Diagnosis?.result ? "process" : "wait" },
    { title: "证据计算", status: v2IsEvidenceResult ? "finish" : v2AnswerReviewConsumed ? "process" : "wait" },
    { title: "证据审核", status: v2EvidenceReviewComplete ? "finish" : v2IsEvidenceResult ? "process" : "wait" },
    { title: "策略", status: v2Strategy?.result ? "finish" : v2EvidenceReviewComplete ? "process" : "wait" },
  ] as any[];
  const v2AnalysisFlowCurrent = Math.max(0, v2AnalysisFlowItems.findIndex((item) => item.status === "process"));
  const v2TargetCapabilityReviewItems = v2Diagnosis?.target_capability_review_items || [];
  const v2ConfirmedTargetCapabilityCount = v2TargetCapabilityReviewItems.filter((row) => Boolean(row.current_truth)).length;
  const v2EvidenceEligibility = v2Diagnosis?.effective_evidence_eligibility;
  const v2SourceStatus = v2Diagnosis?.source_content_status_summary;
  const v2StrategyOutput = v2Strategy?.result?.output;
  const v2ExecutionOutput = v2Execution?.result?.output;
  const v2ExecutionConfirmation = v2Execution?.confirmations.find(
    (row) => row.result_version === v2Execution.result?.result_version,
  );
  const v2ExecutionCurrentPublications = v2ExecutionConfirmation
    ? v2Execution?.publications.filter((row) => row.confirmation_id === v2ExecutionConfirmation.confirmation_id) || []
    : [];
  const v2RetestPublicationOptions = (v2Execution?.publications || []).map((row) => ({
    value: row.publication_id,
    label: `修订 ${row.revision_number} · ${row.report.actual_url || row.publication_id} · ${v2ConformanceLabel(row.conformance)}`,
  }));
  const v2ComparisonRows = Object.entries(v2Retest?.comparison_result?.comparison.metrics || {}).map(([metricKey, comparison]) => ({
    metricKey,
    comparison,
    baseline: v2Retest?.comparison_result?.baseline_measurement.metrics[metricKey],
    retest: v2Retest?.comparison_result?.retest_measurement.metrics[metricKey],
  }));
  const v2StrategyDirectionById = new Map((v2StrategyOutput?.directions || []).map((row) => [row.direction_id, row]));
  const v2OrderedStrategyDirections = v2StrategyDirectionOrder
    .map((directionId) => v2StrategyDirectionById.get(directionId))
    .filter((row): row is NonNullable<typeof row> => Boolean(row));
  const v2BlockedHistoricalRelations = new Set(v2EvidenceEligibility?.blocked_historical_relation_ids || []);
  const v2FilteredSources = (v2SourcePreparation?.sources || []).filter((source) => {
    if (v2SourceFilter === "ALL") return true;
    if (v2SourceFilter === "ACTION_REQUIRED") {
      return !["READY", "WAIVED_WITH_LIMITATION"].includes(source.state);
    }
    return source.state === v2SourceFilter;
  });
  const stagedDiagnosisValue = (targetType: string, targetId: string, fallbackValue: string | null | undefined) =>
    v2DiagnosisEdits[`${targetType}:${targetId}`]?.value ?? fallbackValue ?? "";

  return <Layout className="app-shell">
    <Sider width={228} className="side-nav" breakpoint="md" collapsedWidth={0} collapsible>
      <div className="brand-block"><Title level={4}>生成式搜索决策平台</Title><Text type="secondary">监测 · 诊断 · 策略 · 复测</Text></div>
        <Menu mode="inline" selectedKeys={[page]} onClick={({ key }) => setPage(key as PageKey)} items={RELEASE_FIRST_SLICE ? [
          { type: "group", label: "GEO 1.0 首批交付", children: [
            { key: "coreV2", icon: <Play size={18} />, label: "来源与证据主链" },
          ] },
        ] : [
        { type: "group", label: "业务闭环", children: [
          { key: "coreV2", icon: <Play size={18} />, label: "单问题分析 V2" },
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
            onChange={(v)=>{
              setPromptContext(v);
            }}
          />}
          <Button icon={<Plus size={16} />} onClick={() => openProjectModal()}>新建项目</Button>
          <Button icon={<Settings size={16} />} onClick={() => projectId && openProjectModal(projectId)} disabled={!projectId}>编辑项目</Button>
          <Button icon={<RefreshCw size={16} />} loading={loading} onClick={() => projectId && loadProject(projectId)}>刷新</Button>
        </Space>
      </Header>
      <Content className="workspace">
        {!project ? <Card loading={loading}><Empty description="请选择项目" /></Card> : page === "coreV2" ? <Space direction="vertical" size={16} className="page-stack">
          {!activePromptId ? <Card><Empty description="请在顶部选择一个 Prompt" /></Card> : <>
            <Card size="small" title={<Space><Play size={18} />Single-Prompt Core V2 · Prompt #{activePromptId}</Space>} extra={<Space wrap>
              <Text type="secondary">采样次数</Text>
              <InputNumber min={1} max={10} value={v2SampleCount} onChange={(value) => setV2SampleCount(Number(value || 1))} disabled={v2Loading || ["QUEUED", "COLLECTING"].includes(v2Analysis?.sampling.status || "")} />
              <Popconfirm
                title={v2AnalysisHistory.length ? "新增一批浏览器采样？" : "开始首次浏览器采样？"}
                description={v2AnalysisHistory.length ? "这会新增 Run，不会修改或重算已有分析。采样完成后可在下方选择是否纳入新分析。" : "采样完成后会形成第一份不可变分析输入。"}
                okText="确认采样"
                cancelText="取消"
                onConfirm={startV2Analysis}
              >
                <Tooltip title="只新增采样记录；继续历史分析请使用下方已有分析">
                  <Button icon={<Play size={15} />} loading={v2Loading} disabled={v2Loading || ["QUEUED", "COLLECTING"].includes(v2Analysis?.sampling.status || "")}>
                    {v2AnalysisHistory.length ? "新增采样" : "开始首次采样"}
                  </Button>
                </Tooltip>
              </Popconfirm>
              <Tooltip title="读取这次分析的后端权威状态">
                <Button icon={<RefreshCw size={15} />} loading={v2Loading} disabled={!v2Analysis} onClick={refreshV2Analysis} aria-label="刷新分析状态" />
              </Tooltip>
            </Space>}>
              <Text>{scopedPrompt?.prompt_text}</Text>
            </Card>

            <Card size="small" title={<Space><Monitor size={18} />采样记录池<Tag>{v2RunPool?.total || 0} Runs</Tag></Space>} extra={<Space>
              <Text type="secondary">新增采样不会改变已有分析</Text>
              <Button icon={<RefreshCw size={15} />} loading={v2RunPoolLoading} onClick={() => refreshV2RunPool()}>刷新</Button>
            </Space>}>
              <Alert
                type="info"
                showIcon
                message="先选择 Run，再决定是否建立新的分析版本"
                description="可以只选新增样本，也可以选择历史加新增样本。旧 Analysis、Context、审核和正文准备不会被修改。"
                style={{ marginBottom: 12 }}
              />
              <Table<SinglePromptV2RunPoolItem>
                rowKey="run_id"
                size="small"
                loading={v2RunPoolLoading}
                dataSource={v2RunPool?.items || []}
                rowSelection={{
                  selectedRowKeys: v2SelectedRunIds,
                  preserveSelectedRowKeys: true,
                  onSelect: (row, selected) => selectV2Run(row, selected),
                  onSelectAll: (selected, rows) => rows.forEach((row) => selectV2Run(row, selected)),
                }}
                pagination={{
                  current: v2RunPool?.page || 1,
                  pageSize: v2RunPool?.page_size || 20,
                  total: v2RunPool?.total || 0,
                  showSizeChanger: false,
                  onChange: (nextPage) => refreshV2RunPool(nextPage),
                }}
                scroll={{ x: 980 }}
                expandable={{ expandedRowRender: (row) => <Space direction="vertical" style={{ width: "100%" }}>
                  <Text strong>实际回答正文</Text>
                  <Typography.Paragraph className="v2-answer-text">{row.answer_text || "无可用回答"}</Typography.Paragraph>
                  <Text type="secondary">引用 {row.references?.length || 0} 条 · 输入指纹 <Text code copyable>{row.input_fingerprint}</Text></Text>
                </Space> }}
                columns={[
                  { title: "Run", width: 82, render: (_: unknown, row) => <Text code>#{row.run_id}</Text> },
                  { title: "状态", width: 110, render: (_: unknown, row) => statusTag(row.status) },
                  { title: "采样时间", width: 170, render: (_: unknown, row) => formatDateTime(row.finished_at || row.started_at) },
                  { title: "回答", width: 110, render: (_: unknown, row) => row.answer_text ? `${row.answer_char_count || row.answer_text.length} 字` : "无" },
                  { title: "引用", width: 80, render: (_: unknown, row) => row.references?.length || 0 },
                  { title: "引用完整", width: 100, render: (_: unknown, row) => row.reference_complete ? <Tag color="green">完整</Tag> : <Tag color="gold">有限制</Tag> },
                  { title: "已用于分析", width: 210, render: (_: unknown, row) => row.analysis_memberships?.length
                    ? <Text ellipsis={{ tooltip: row.analysis_memberships.map((item) => item.analysis_id).join("、") }}>{row.analysis_memberships.length} 个版本</Text>
                    : <Text type="secondary">尚未纳入</Text> },
                  { title: "操作", width: 100, fixed: "right", render: (_: unknown, row) => row.status === "failed" ? <Popconfirm title={`重试 Run #${row.run_id}？`} description="原 Run 保留不变，系统会创建一个新的 Run 尝试。" onConfirm={() => retryV2Run(row)}><Button size="small">重试</Button></Popconfirm> : null },
                ]}
              />
              <Row justify="space-between" align="middle" gutter={[12, 12]}>
                <Col><Text>已选择 <Text strong>{v2SelectedRunIds.length}</Text> 个 Run：{v2SelectedRunIds.length ? v2SelectedRunIds.map(Number).sort((a, b) => a - b).join("、") : "尚未选择"}</Text></Col>
                <Col><Button type="primary" icon={<ListChecks size={15} />} disabled={!v2SelectedRunIds.length} loading={v2Loading} onClick={createV2AnalysisFromSelectedRuns}>用所选 Run 建立分析版本</Button></Col>
              </Row>
            </Card>

            {!v2Analysis ? <Card title="已有分析" loading={v2AnalysisHistoryLoading} extra={<Button icon={<RefreshCw size={15} />} onClick={refreshV2AnalysisHistory}>刷新</Button>}>
              {v2AnalysisHistory.length === 0 ? <Empty description="当前 Prompt 还没有分析，可从上方开始一次新分析" /> : <Table<SinglePromptV2AnalysisListItem>
                rowKey={(row) => row.analysis.analysis_id}
                size="small"
                pagination={false}
                dataSource={v2AnalysisHistory}
                columns={[
                  { title: "状态", width: 120, render: (_: unknown, row) => v2AnalysisStatusTag(row.sampling.status) },
                  { title: "采样", width: 150, render: (_: unknown, row) => `${row.sampling.valid_run_count}/${row.sampling.planned_run_count} 有效` },
                  { title: "Analysis", render: (_: unknown, row: SinglePromptV2AnalysisListItem) => <Text code copyable>{row.analysis.analysis_id}</Text> },
                  { title: "当前进度", width: 230, render: (_: unknown, row: SinglePromptV2AnalysisListItem) => row.source_preparation_summary
                    ? `${row.source_preparation_summary.ready_source_count}/${row.source_preparation_summary.required_source_count} 正文就绪，${row.source_preparation_summary.nonterminal_source_count} 待处理`
                    : row.context_id ? "采样已冻结，待准备正文" : "采样尚未冻结" },
                  { title: "创建时间", width: 180, render: (_: unknown, row) => formatDateTime(row.created_at) },
                  { title: "操作", width: 110, render: (_: unknown, row) => <Button type="primary" size="small" onClick={() => openV2Analysis(row)}>继续处理</Button> },
                ]}
              />}
            </Card> : <>
              <Card size="small" title={<Space>{v2AnalysisStatusTag(v2Analysis.sampling.status)}<Text code>{v2Analysis.analysis.analysis_id}</Text></Space>} extra={<Space><Tag color={v2Analysis.result_source === "FROZEN_ANALYSIS_CONTEXT" ? "green" : "blue"}>{v2Analysis.result_source === "FROZEN_ANALYSIS_CONTEXT" ? "固定分析输入" : "实时采样状态"}</Tag><Button size="small" onClick={showV2AnalysisHistory}>切换已有分析</Button></Space>}>
                <div className="v2-status-grid">
                  <Statistic title="计划采样" value={v2Analysis.sampling.planned_run_count} suffix="次" />
                  <Statistic title="已进入终态" value={v2Analysis.sampling.terminal_run_count} suffix="次" />
                  <Statistic title="有效结果" value={v2Analysis.sampling.valid_run_count} suffix="次" />
                  <Statistic title="失败" value={v2Analysis.sampling.failed_run_count} suffix="次" />
                  <Statistic title="执行尝试" value={v2Analysis.sampling.attempt_count} suffix="次" />
                </div>
                <Descriptions size="small" column={{ xs: 1, md: 2 }} style={{ marginTop: 18 }}>
                  <Descriptions.Item label="输入来源">{v2Analysis.analysis.task_id ? `采集任务 #${v2Analysis.analysis.task_id} · ${v2Analysis.active_task?.status || "-"}` : "显式选择历史 Run"}</Descriptions.Item>
                  <Descriptions.Item label="结果版本">{v2Analysis.result_version || "采集完成后生成"}</Descriptions.Item>
                  <Descriptions.Item label="AnalysisContext">{v2Analysis.context_id || "尚未冻结"}</Descriptions.Item>
                  <Descriptions.Item label="开始时间">{formatDateTime(v2Analysis.started_at)}</Descriptions.Item>
                </Descriptions>
                {v2Analysis.blocker && v2Analysis.blocker.code !== "NEXT_STAGE_NOT_IMPLEMENTED" && <Alert style={{ marginTop: 14 }} type={v2Analysis.context_id ? "info" : "error"} showIcon message={v2BlockerLabel(v2Analysis.blocker.code)} description={v2Analysis.blocker.detail} action={v2Analysis.allowed_operations.includes("RETRY_COLLECTION") ? <Button size="small" danger loading={v2Loading} onClick={retryV2Analysis}>明确重试</Button> : undefined} />}
                {v2Analysis.warnings.map((warning) => <Alert key={warning.code} style={{ marginTop: 10 }} type="warning" showIcon message={warning.code === "RETRIEVAL_OBSERVATION_UNAVAILABLE" ? "检索观测不可用" : "独立会话证明不可用"} description={warning.detail} />)}
              </Card>

              <Card size="small" title="本次分析的原始采样结果" extra={<Text type="secondary">只读取 Task #{v2Analysis.analysis.task_id}</Text>}>
                <Alert
                  className="v2-sampling-explanation"
                  type="info"
                  showIcon
                  message="每行是一轮独立回答"
                  description="每轮只提交一次当前 Prompt，并保存一条最终回答正文。文心生成过程中的平台搜索词单独保存为只读观察，暂不进入回答语义、证据判断或策略，也不是系统已验证的 Retrieval 轨迹。"
                />
                <Table
                  rowKey="run_id"
                  size="small"
                  pagination={false}
                  dataSource={v2Analysis.runs}
                  locale={{ emptyText: "采样任务尚未产生结果" }}
                  scroll={{ x: 720 }}
                  columns={[
                    { title: "样本", width: 76, render: (_: unknown, row: any) => `第 ${row.run_sequence} 次` },
                    { title: "状态", dataIndex: "status", width: 100, render: statusTag },
                    { title: "平台搜索词（观察）", width: 330, render: (_: unknown, row: any) => {
                      const terms = row.platform_reported_search?.terms || [];
                      return terms.length ? <Space size={6}>
                        <Tag>{terms.length} 个</Tag>
                        <Text ellipsis={{ tooltip: terms.join(" / ") }} style={{ maxWidth: 250 }}>{terms.join(" / ")}</Text>
                      </Space> : <Text type="secondary">本轮未单独采集</Text>;
                    } },
                    { title: "回答正文", width: 180, render: (_: unknown, row: any) => row.answer_content_boundary?.status === "LEGACY_MIXED_CONTAINER"
                      ? <Tag color="gold">需重新采样</Tag>
                      : row.answer_text ? <Space size={6}><Tag color="blue">独立 1 条</Tag><Text type="secondary">{row.answer_char_count || row.answer_text.length} 字</Text></Space>
                        : <Text type="secondary">尚无回答</Text> },
                    { title: "引用", width: 72, render: (_: unknown, row: any) => row.references?.length || 0 },
                    { title: "检索", width: 72, render: (_: unknown, row: any) => row.retrieval_candidates?.length || 0 },
                    { title: "耗时", width: 92, render: (_: unknown, row: any) => row.duration_ms ? `${Math.round(row.duration_ms / 1000)} 秒` : "-" },
                  ]}
                  expandable={{ expandedRowRender: (row: any) => <div className="v2-run-detail">
                    {row.error && <Alert type="error" showIcon message={row.error.type || row.status} description={row.error.message || row.error.blocked_reason || "采集未完成"} />}
                    <div className="v2-reported-search">
                      <Text strong>本轮实际提交 Prompt</Text>
                      <div><Text>{row.observed_conditions?.original_query?.value || v2Analysis.analysis.prompt_text}</Text></div>
                      <Space wrap size={[6, 6]}>
                        <Text strong>平台搜索词观察</Text>
                        <Tag color="default">暂不处理</Tag>
                        <Tag color="gold">未验证检索轨迹</Tag>
                        {(row.platform_reported_search?.terms || []).map((term: string) => <Tag key={term}>{term}</Tag>)}
                        {!row.platform_reported_search?.terms?.length && <Text type="secondary">本轮未单独采集</Text>}
                      </Space>
                    </div>
                    {row.answer_content_boundary?.status === "LEGACY_MIXED_CONTAINER" && <Alert
                      type="warning"
                      showIcon
                      message="历史回答边界未分离"
                      description="该冻结 Run 的回答文本包含平台搜索过程，不再展开显示；请使用修复后的采集器重新采样。"
                    />}
                    {row.answer_text && row.answer_content_boundary?.status !== "LEGACY_MIXED_CONTAINER" && <div><Text strong>实际回答正文</Text><Typography.Paragraph className="v2-answer-text">{row.answer_text}</Typography.Paragraph></div>}
                    <div className="v2-output-columns">
                      <div><Text strong>引用资料 · {row.references?.length || 0}</Text>{(row.references || []).map((item: any) => <div key={item.reference_id}><Link href={item.canonical_url || item.url} target="_blank">{item.index}. {item.title || item.domain || item.url}</Link></div>)}</div>
                      <div><Text strong>检索观测 · {row.retrieval_candidates?.length || 0}</Text>{(row.retrieval_candidates || []).map((item: any) => <div key={item.candidate_id}><Link href={item.canonical_url || item.url} target="_blank">{item.rank}. {item.title || item.domain || item.url}</Link></div>)}</div>
                    </div>
                  </div> }}
                />
              </Card>

              {v2Analysis.context_id && <Card id="v2-source-preparation" size="small" title={<Space><FileText size={18} />引用范围与正文准备</Space>} extra={<Space wrap>
                {v2SourcePreparation && <Tag color={v2SourcePreparation.completion_manifest?.status === "FROZEN" ? "green" : v2SourcePreparation.completion_manifest?.status === "NO_USABLE_SOURCE" ? "red" : "gold"}>
                  {v2SourcePreparation.completion_manifest?.status || `${v2SourcePreparation.conservation.terminal}/${v2SourcePreparation.conservation.required_unique_sources} 已处置`}
                </Tag>}
                {v2SourcePreparation && <Tooltip title="只读取当前来源准备状态，不抓取网页"><Button icon={<RefreshCw size={15} />} loading={v2SourceRefreshing} disabled={Boolean(v2SourceActionKey)} onClick={() => refreshV2SourcePreparation()} aria-label="刷新来源准备" /></Tooltip>}
              </Space>}>
                {!v2SourcePreparation ? <Space direction="vertical" size={12} style={{ width: "100%" }}>
                  <Alert type="info" showIcon message="先冻结本次分析的引用范围" description="Citation Manifest 只固定哪些引用属于本次 Context；不会抓取正文，也不会自动放弃任何来源。" />
                  <Row gutter={[12, 12]} align="middle">
                    <Col xs={24} md={8}><Input value={v2SourceActor} onChange={(event) => setV2SourceActor(event.target.value)} placeholder="操作人" /></Col>
                    <Col><Button type="primary" icon={<ListChecks size={15} />} loading={v2SourceActionKey === "create-preparation"} disabled={Boolean(v2SourceActionKey)} onClick={startV2SourcePreparation}>冻结引用范围并开始准备</Button></Col>
                  </Row>
                </Space> : <Space direction="vertical" size={14} style={{ width: "100%" }}>
                  {v2SourceActionNotice && <Alert
                    type={v2SourceActionNotice.type}
                    showIcon
                    closable
                    onClose={() => setV2SourceActionNotice(null)}
                    message={v2SourceActionNotice.type === "success" ? "来源正文处理成功" : "来源正文未生成快照"}
                    description={<Space direction="vertical" size={2}><Text strong>{v2SourceActionNotice.title}</Text><Text>{v2SourceActionNotice.detail}</Text></Space>}
                  />}
                  {v2SourcePreparation.conservation.nonterminal > 0 && <Alert
                    type="warning"
                    showIcon
                    message={`当前下一步：处置 ${v2SourcePreparation.conservation.nonterminal} 条待处理来源`}
                    description={`已有 ${v2SourcePreparation.conservation.by_state.READY || 0} 条正文通过校验。请逐条人工补录真实正文，或在明确知道其不影响结论时记录人工放弃与限制；全部处置后才能冻结 Source Completion Manifest。Answer Semantic 可在下方独立启动，不需要等待正文补完。`}
                    action={<Button onClick={() => setV2SourceFilter("ACTION_REQUIRED")}>只看待处理</Button>}
                  />}
                  <Descriptions size="small" column={{ xs: 1, md: 3 }}>
                    <Descriptions.Item label="Citation Manifest"><Text code copyable>{v2SourcePreparation.citation_manifest.manifest_id}</Text></Descriptions.Item>
                    <Descriptions.Item label="唯一来源 / 引用记录">{v2SourcePreparation.citation_manifest.source_count} / {v2SourcePreparation.citation_manifest.occurrence_count}</Descriptions.Item>
                    <Descriptions.Item label="Manifest SHA-256"><Text code copyable>{v2SourcePreparation.citation_manifest.payload_hash}</Text></Descriptions.Item>
                    <Descriptions.Item label="READY">{v2SourcePreparation.conservation.by_state.READY || 0}</Descriptions.Item>
                    <Descriptions.Item label="需人工补录">{v2SourcePreparation.conservation.by_state.MANUAL_REQUIRED || 0}</Descriptions.Item>
                    <Descriptions.Item label="人工放弃">{v2SourcePreparation.conservation.by_state.WAIVED_WITH_LIMITATION || 0}</Descriptions.Item>
                    <Descriptions.Item label="待处置">{v2SourcePreparation.conservation.nonterminal}</Descriptions.Item>
                  </Descriptions>
                  {v2SourcePreparation.allowed_operations.includes("QUEUE_AUTO_FETCH") && <Alert
                    type="info"
                    showIcon
                    message="先自动获取，再人工补充"
                    description="系统只抓取当前 Citation Manifest 内的 URL。合格正文会直接形成不可变 Snapshot；抓取失败、验证页或内容不完整的来源会进入人工补录，不会自动放弃。"
                    action={<Button type="primary" icon={<Download size={15} />} loading={v2SourceActionKey === "auto-fetch"} disabled={Boolean(v2SourceActionKey)} onClick={startV2SourceAutoFetch}>自动获取正文</Button>}
                  />}
                  {["AUTO_FETCH_QUEUED", "AUTO_FETCHING"].includes(v2SourcePreparation.preparation.status) && <Alert
                    type="info"
                    showIcon
                    message={v2SourcePreparation.preparation.status === "AUTO_FETCH_QUEUED" ? "正文获取正在排队" : "正在逐条获取正文"}
                    description="页面会自动刷新。抓取期间不会占用数据库写事务，也不会自动触发 Evidence。"
                  />}
                  <Alert type="warning" showIcon message="来源处置完成不等于证据充分" description="人工放弃只记录限制，不产生 SUPPORTS 或 NO_SUPPORT。仍有 PENDING 时 Evidence 必须阻断；全部来源被放弃也不能取得证据资格。" />
                  <Row gutter={[12, 12]} align="middle">
                    <Col xs={24} md={8}><Input value={v2SourceActor} onChange={(event) => setV2SourceActor(event.target.value)} placeholder="操作人" /></Col>
                    <Col><Text type="secondary">正文补录会创建新的不可变 Snapshot，不改写历史版本。</Text></Col>
                  </Row>
                  <Segmented
                    value={v2SourceFilter}
                    onChange={(value) => setV2SourceFilter(value as typeof v2SourceFilter)}
                    options={[
                      { value: "ACTION_REQUIRED", label: `待处理 ${v2SourcePreparation.conservation.nonterminal}` },
                      { value: "ALL", label: `全部 ${v2SourcePreparation.sources.length}` },
                      { value: "READY", label: `已就绪 ${v2SourcePreparation.conservation.by_state.READY || 0}` },
                      { value: "WAIVED_WITH_LIMITATION", label: `已放弃 ${v2SourcePreparation.conservation.by_state.WAIVED_WITH_LIMITATION || 0}` },
                    ]}
                  />
                  {v2FilteredSources.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前筛选下没有来源" /> : <Collapse items={v2FilteredSources.map((source) => {
                    const draft = v2SourceDrafts[source.source_key] || { title: "", inputFormat: "CLEAN_TEXT", cleanText: "", rawHtml: "", coverageScope: "FULL_PAGE", waiverReason: "", waiverImpact: "" };
                    const sourceTitle = String(source.reference_observations?.[0]?.title || source.canonical_url);
                    return {
                      key: source.source_key,
                      label: <Space wrap><Tag color={source.state === "READY" ? "green" : source.state === "MANUAL_REQUIRED" ? "red" : source.state === "WAIVED_WITH_LIMITATION" ? "gold" : "default"}>{source.state}</Tag><Text ellipsis style={{ maxWidth: 660 }}>{sourceTitle}</Text><Text type="secondary">{source.occurrence_count} 次引用</Text></Space>,
                      children: <Space direction="vertical" size={12} style={{ width: "100%" }}>
                        <Link href={source.canonical_url} target="_blank" ellipsis>{source.canonical_url}</Link>
                        {source.failure && <Alert type="error" showIcon message={source.failure.code} description={source.failure.detail} />}
                        {source.snapshot && <Descriptions size="small" column={{ xs: 1, md: 3 }}>
                          <Descriptions.Item label="Snapshot"><Text code>{source.snapshot.snapshot_id}</Text></Descriptions.Item>
                          <Descriptions.Item label="正文 / passages">{source.snapshot.content_hash.slice(0, 12)} / {source.snapshot.passage_count}</Descriptions.Item>
                          <Descriptions.Item label="覆盖范围">{source.snapshot.coverage_scope}</Descriptions.Item>
                          <Descriptions.Item label="获取方式">{source.snapshot.acquisition_method === "AUTO_FETCH" ? "自动获取" : source.snapshot.acquisition_method === "MANUAL_HTML_SOURCE" ? "人工源码提取" : "人工正文补录"}</Descriptions.Item>
                        </Descriptions>}
                        {source.waiver && <Alert type="warning" showIcon message={`已由 ${source.waiver.waived_by} 明确放弃`} description={`${source.waiver.reason}；影响：${source.waiver.impact}`} />}
                        {(source.state === "MANUAL_REQUIRED" || source.state === "READY") && <>
                          <Divider orientation="left">{source.state === "READY" ? "人工替换正文版本" : "自动获取未完成，请人工补录"}</Divider>
                          <Row gutter={[12, 12]}>
                            <Col xs={24} md={16}><Input value={draft.title} onChange={(event) => updateV2SourceDraft(source.source_key, { title: event.target.value })} placeholder="来源标题（可选）" /></Col>
                            <Col xs={24} md={8}><Select style={{ width: "100%" }} value={draft.coverageScope} onChange={(value) => updateV2SourceDraft(source.source_key, { coverageScope: value })} options={[{ value: "FULL_PAGE", label: "完整正文" }, { value: "EXCERPT", label: "明确摘录" }]} /></Col>
                            <Col xs={24}><Segmented value={draft.inputFormat} onChange={(value) => updateV2SourceDraft(source.source_key, { inputFormat: value as V2SourceDraft["inputFormat"] })} options={[{ value: "CLEAN_TEXT", label: "粘贴正文" }, { value: "HTML_SOURCE", label: "粘贴页面源码" }]} /></Col>
                            <Col xs={24}>{draft.inputFormat === "HTML_SOURCE"
                              ? <Space direction="vertical" size={4} style={{ width: "100%" }}><Input.TextArea rows={9} value={draft.rawHtml} onChange={(event) => updateV2SourceDraft(source.source_key, { rawHtml: event.target.value })} placeholder="粘贴页面 HTML 源代码。系统只提取正文；验证页、登录墙和空壳页面会被拒绝。" /><Text type={draft.rawHtml.length > MAX_MANUAL_HTML_CHARACTERS ? "danger" : "secondary"}>已粘贴 {draft.rawHtml.length.toLocaleString()} / 25,000,000 字符</Text></Space>
                              : <Input.TextArea rows={7} value={draft.cleanText} onChange={(event) => updateV2SourceDraft(source.source_key, { cleanText: event.target.value })} placeholder="粘贴真实正文。验证页、登录墙、错误提示不得作为正文提交。" />}</Col>
                            <Col><Button type="primary" loading={v2SourceActionKey === `manual:${source.source_key}`} disabled={Boolean(v2SourceActionKey)} onClick={() => submitV2ManualSource(source)}>{source.snapshot ? "提交新正文版本" : draft.inputFormat === "HTML_SOURCE" ? "提取并生成正文快照" : "校验并生成正文快照"}</Button></Col>
                            {v2SourceActionNotice?.sourceKey === source.source_key && v2SourceActionNotice.type === "error" && <Col xs={24}><Alert type="error" showIcon message="本次提交被拒绝" description={v2SourceActionNotice.detail} /></Col>}
                          </Row>
                        </>}
                        {source.state === "MANUAL_REQUIRED" && <>
                          <Divider orientation="left">明确人工放弃</Divider>
                          <Row gutter={[12, 12]}>
                            <Col xs={24} md={10}><Input value={draft.waiverReason} onChange={(event) => updateV2SourceDraft(source.source_key, { waiverReason: event.target.value })} placeholder="放弃原因" /></Col>
                            <Col xs={24} md={10}><Input value={draft.waiverImpact} onChange={(event) => updateV2SourceDraft(source.source_key, { waiverImpact: event.target.value })} placeholder="对结论和适用范围的影响" /></Col>
                            <Col><Popconfirm title="明确放弃该来源？" description="放弃不会产生证据资格，也不能由系统自动撤销。" okText="记录放弃" cancelText="取消" onConfirm={() => waiveV2Source(source)}><Button danger loading={v2SourceActionKey === `waive:${source.source_key}`} disabled={Boolean(v2SourceActionKey)}>记录放弃与限制</Button></Popconfirm></Col>
                          </Row>
                        </>}
                      </Space>,
                    };
                  })} />}
                  {!v2SourcePreparation.completion_manifest && <Button type="primary" icon={<ShieldCheck size={15} />} disabled={v2SourcePreparation.conservation.nonterminal > 0 || Boolean(v2SourceActionKey)} loading={v2SourceActionKey === "freeze-completion"} onClick={freezeV2SourceCompletion}>冻结 Source Completion Manifest</Button>}
                  {v2SourcePreparation.completion_manifest && <Alert type={v2SourcePreparation.completion_manifest.status === "FROZEN" ? "success" : "error"} showIcon message={`Source Completion Manifest · ${v2SourcePreparation.completion_manifest.status}`} description={<Text code copyable>{v2SourcePreparation.completion_manifest.payload_hash}</Text>} />}
                </Space>}
              </Card>}

              {v2Analysis.context_id && <Card id="v2-answer-semantic" size="small" title={<Space><ShieldCheck size={18} />回答语义与证据诊断</Space>} extra={<Space wrap>
                {v2Diagnosis && <Tag color={v2NoConsumableAnswerSemantic ? "red" : v2Diagnosis.overall_status === "REVIEW_COMPLETED" ? "green" : ["QUEUED", "RUNNING", "EVIDENCE_QUEUED", "EVIDENCE_RUNNING"].includes(v2Diagnosis.compute_status) ? "blue" : ["FAILED", "EVIDENCE_FAILED"].includes(v2Diagnosis.compute_status) ? "red" : "gold"}>
                  {v2MixedAnswerBoundary ? "回答边界不合格" : v2NoConsumableAnswerSemantic ? "回答语义失败" : v2Diagnosis.compute_status === "EVIDENCE_QUEUED" ? "等待证据计算" : v2Diagnosis.compute_status === "EVIDENCE_RUNNING" ? "证据计算中" : v2Diagnosis.compute_status === "EVIDENCE_FAILED" ? "证据计算失败" : v2Diagnosis.overall_status === "REVIEW_COMPLETED" ? "审核完成" : v2Diagnosis.compute_status === "READY_FOR_REVIEW" ? "待审核" : v2Diagnosis.compute_status === "RUNNING" ? "诊断中" : v2Diagnosis.compute_status === "QUEUED" ? "等待诊断" : v2Diagnosis.compute_status === "INTERRUPTED" ? "诊断中断" : v2Diagnosis.compute_status}
                </Tag>}
                {!v2Diagnosis ? <Space wrap><Select value={v2AnswerPolicy} onChange={setV2AnswerPolicy} options={[{ value: "CACHE_ONLY", label: "仅兼容缓存" }, { value: "ALLOW_EXTERNAL", label: "授权 Answer LLM" }]} /><Button type="primary" icon={<Play size={15} />} loading={v2DiagnosisLoading} disabled={!v2SourcePreparation} onClick={startV2Diagnosis}>开始 Answer Semantic</Button></Space> : <>
                  <Tooltip title="只读取当前诊断执行状态">
                    <Button icon={<RefreshCw size={15} />} loading={v2DiagnosisLoading} onClick={refreshV2Diagnosis} aria-label="刷新诊断状态" />
                  </Tooltip>
                  {v2Diagnosis.allowed_operations.includes("RETRY") && <Button danger loading={v2DiagnosisLoading} onClick={retryV2DiagnosisExecution}>明确重试</Button>}
                </>}
              </Space>}>
                {!v2Diagnosis ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={v2SourcePreparation ? "Citation Manifest 已冻结，尚未创建 Answer Semantic 执行" : "请先冻结本次 Context 的 Citation Manifest"} /> : <>
                  <Descriptions size="small" column={{ xs: 1, md: 3 }}>
                    <Descriptions.Item label="执行身份"><Text code>{v2Diagnosis.diagnosis.diagnosis_id}</Text></Descriptions.Item>
                    <Descriptions.Item label="结果版本">{v2Diagnosis.result?.result_version || "尚未发布"}</Descriptions.Item>
                    <Descriptions.Item label="执行尝试">{v2Diagnosis.attempt_count} 次</Descriptions.Item>
                    <Descriptions.Item label="外部模型调用">{v2Diagnosis.usage.external_llm_calls}</Descriptions.Item>
                    <Descriptions.Item label="兼容缓存复用">{v2Diagnosis.usage.llm_cache_hits}</Descriptions.Item>
                    <Descriptions.Item label="完成时间">{formatDateTime(v2Diagnosis.finished_at)}</Descriptions.Item>
                  </Descriptions>
                  {["QUEUED", "RUNNING", "EVIDENCE_QUEUED", "EVIDENCE_RUNNING"].includes(v2Diagnosis.compute_status) && <div style={{ marginTop: 16 }}>
                    <Progress percent={Math.round(100 * Number(v2Diagnosis.progress.completed || 0) / Math.max(Number(v2Diagnosis.progress.total || 1), 1))} status="active" />
                    <Text type="secondary">{v2Diagnosis.progress.detail || v2Diagnosis.progress.stage || "正在处理"}</Text>
                  </div>}
                  {v2Diagnosis.blocker && <Alert style={{ marginTop: 14 }} type="error" showIcon message={v2Diagnosis.blocker.code} description={v2Diagnosis.blocker.detail} />}
                </>}
              </Card>}

              {v2Diagnosis?.result && <>
                <Card size="small" title="当前分析进度" extra={<Tag color={v2EvidenceReviewComplete ? "green" : "blue"}>{v2EvidenceReviewComplete ? "证据审核已完成" : v2IsEvidenceResult ? "当前：审核证据结果" : v2AnswerReviewConsumed ? "当前：生成证据" : "当前：审核回答"}</Tag>}>
                  <Steps size="small" responsive current={v2AnalysisFlowCurrent} items={v2AnalysisFlowItems} />
                  {v2IsEvidenceResult && !v2EvidenceReviewComplete && <Alert
                    style={{ marginTop: 16 }}
                    type="warning"
                    showIcon
                    message="Evidence 已完成计算，当前只需审核新增的证据结果"
                    description={`先前的 Answer 审核 ${v2DiagnosisOutput?.input?.answer_review_id || "已绑定"} 已作为本次输入生效，不需要重复确认答案候选。本次请核对 ${v2EvidenceEvaluatedRelations.length} 条已形成结论的关系，并确认是否接受 ${v2EvidenceFailedClaimJobs.length} 个正文主张提取失败等限制。`}
                    action={<Button onClick={() => document.getElementById("v2-evidence-review-focus")?.scrollIntoView({ behavior: "smooth", block: "start" })}>查看本次审核内容</Button>}
                  />}
                  {v2EvidenceReviewComplete && <Alert style={{ marginTop: 16 }} type="success" showIcon message="当前 Evidence ResultVersion 已审核" description="下一步可以查看策略资格；目标品牌能力核对仍只影响依赖这些事实的策略声明和公开内容。" />}
                </Card>

                {RELEASE_FIRST_SLICE && v2EvidenceReviewComplete && <Card
                  id="v2-strategy-readiness"
                  size="small"
                  title={<Space><ListChecks size={18} />下一步：策略资格</Space>}
                  extra={<Button icon={<RefreshCw size={14} />} loading={v2StrategyLoading} onClick={() => refreshV2StrategyContext()} aria-label="刷新策略资格">刷新</Button>}
                >
                  {!v2StrategyReadiness ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={v2StrategyLoading ? "正在检查当前结果能否进入策略" : "尚未取得策略资格报告"} /> : <Space direction="vertical" size={14} style={{ width: "100%" }}>
                    <Alert
                      type={v2StrategyReadiness.classification === "C" ? "success" : "warning"}
                      showIcon
                      message={v2StrategyReadiness.classification === "C" ? `${v2StrategyReadiness.qualified_direction_count} 个方向已具备策略资格` : "当前诊断已审核，但还没有可直接生成的策略方向"}
                      description={v2StrategyReadiness.blocker?.detail || "策略只会消费已通过事实、关系和干预依据 Gate 的方向。"}
                    />
                    <Descriptions size="small" column={{ xs: 1, md: 3 }}>
                      <Descriptions.Item label="可消费理由">{v2StrategyReadiness.current_observation.fact_consumable_reason_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="合格正文来源">{v2StrategyReadiness.current_observation.source_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="有效证据关系">{v2StrategyReadiness.current_observation.effective_evidence_relation_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="已确认能力">{v2StrategyReadiness.current_observation.confirmed_capability_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="公开可写事实">{v2StrategyReadiness.current_observation.public_claim_eligible_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="合格策略方向">{v2StrategyReadiness.qualified_direction_count}</Descriptions.Item>
                    </Descriptions>
                    <div className="v2-strategy-band">
                      <Space wrap><Text strong>目标品牌事实基础</Text><Tag color={v2StrategyReadiness.foundation.state === "REQUIRED" ? "green" : v2StrategyReadiness.foundation.state === "UNKNOWN" ? "gold" : "default"}>{v2StrategyReadiness.foundation.state}</Tag></Space>
                      <Text type="secondary">{v2StrategyReadiness.foundation.reason}</Text>
                    </div>
                    {v2StrategyReadiness.verification_items.length > 0 && <div>
                      <Text strong>接下来需要处理</Text>
                      <div className="v2-strategy-list" style={{ marginTop: 8 }}>
                        {v2StrategyReadiness.verification_items.map((item) => <div key={item.code} className="v2-strategy-list-row"><Tag color="gold">{v2StrategyVerificationLabel(item.code)}</Tag><Text>{item.detail}</Text></div>)}
                      </div>
                    </div>}
                    {v2StrategyReadiness.classification === "B" && <Space wrap>
                      <Button onClick={() => document.getElementById("v2-target-brand-truth")?.scrollIntoView({ behavior: "smooth", block: "start" })}>核对目标品牌能力</Button>
                      <Button onClick={() => document.getElementById("v2-evidence-review-focus")?.scrollIntoView({ behavior: "smooth", block: "start" })}>查看 Evidence 限制</Button>
                    </Space>}
                    {v2StrategyReadiness.classification === "C" && <Alert type="info" showIcon message="策略写入尚未在当前 release 开放" description="资格已经明确；当前页面不会调用旧 Strategy Runner 或写入旧工作流。正式策略生成需要下一发布切片接入 V2 策略表和写入路由。" />}
                  </Space>}
                </Card>}

                {v2MixedAnswerBoundary && <Alert
                  type="error"
                  showIcon
                  message="历史回答文本未与平台搜索过程分离"
                  description={`受影响 Run：${(v2AnswerEligibility?.mixed_answer_run_ids || []).join("、") || "未知"}。旧结果保持不可变，仅供审计；不能审核、修订或进入 Evidence。请用修复后的采集器发起新分析。`}
                />}
                {v2NoConsumableAnswerSemantic && !v2MixedAnswerBoundary && <Alert
                  type="error"
                  showIcon
                  message={`回答语义分析失败 ${v2AnswerEligibility?.failed_answer_count || 0}/${v2AnswerEligibility?.total_answer_count || 0}`}
                  description="没有任何回答通过当前准入契约。以下 0 条事件不是‘回答没有推荐’，本结果只能查看失败报告，不能审核、修订或进入策略。"
                />}
                {v2AnswerEligibility?.partial_failure && <Alert
                  type="warning"
                  showIcon
                  message={`回答语义部分完成：通过 ${v2AnswerEligibility.admitted_answer_count}，失败 ${v2AnswerEligibility.failed_answer_count}`}
                  description="仅审核通过准入的结果；失败 Run 及限制会随本版永久保留。"
                />}
                {(v2Diagnosis.current_safety_advisories || []).map((advisory) => <Alert
                  key={advisory.code}
                  type="warning"
                  showIcon
                  message={advisory.code === "ANSWER_CONTENT_BOUNDARY_NOT_INDEPENDENT" ? "当前回答安全限制" : "当前正文安全限制"}
                  description={advisory.code === "ANSWER_CONTENT_BOUNDARY_NOT_INDEPENDENT"
                    ? advisory.detail
                    : `${advisory.message} 历史技术成功 ${advisory.historical_content_ready}，当前有效正文最多 ${advisory.maximum_currently_eligible}。`}
                />)}
                <Card size="small" title="诊断概览" extra={<Text type="secondary">输入、结果和审核版本均绑定当前 AnalysisContext</Text>}>
                  <div className="v2-status-grid">
                    <Statistic title="推荐/提及事件" value={v2NoConsumableAnswerSemantic ? "不可用" : v2Diagnosis.result.stats.recommendation_events || 0} />
                    <Statistic title="推荐理由" value={v2NoConsumableAnswerSemantic ? "不可用" : v2Diagnosis.result.stats.reasons || 0} />
                    <Statistic title="市场选择标准" value={v2NoConsumableAnswerSemantic ? "不可用" : v2Diagnosis.result.stats.market_criteria || 0} />
                    <Statistic title="引用记录" value={v2Diagnosis.result.stats.reference_records || 0} />
                    <Statistic title="唯一来源" value={v2Diagnosis.result.stats.unique_sources || 0} />
                    <Statistic title="历史正文技术成功" value={v2EvidenceEligibility?.historical_content_ready ?? v2Diagnosis.result.stats.content_ready ?? 0} />
                    <Statistic title="当前正文拦截" value={v2EvidenceEligibility?.content_blocked_current || 0} />
                    <Statistic title="当前最多可用" value={v2EvidenceEligibility?.maximum_currently_eligible ?? v2Diagnosis.result.stats.content_ready ?? 0} />
                    <Statistic title="本次未抓取" value={v2SourceStatus?.not_fetched || 0} />
                    <Statistic title="实际抓取失败" value={v2SourceStatus?.fetch_failed || 0} />
                  </div>
                  {v2EvidenceEligibility && <Text type="secondary" style={{ display: "block", marginTop: 12 }}>
                    “当前最多可用”只表示通过当前拦截规则的上限，不表示其余正文均已完成质量核验。
                  </Text>}
                  {Boolean(v2SourceStatus?.not_fetched) && <Alert
                    style={{ marginTop: 12 }}
                    type="info"
                    showIcon
                    message={`${v2SourceStatus?.not_fetched || 0} 个来源本次未抓取`}
                    description="原因是本次未获正文抓取授权且没有可复用正文，不是网络抓取失败。旧 ResultVersion 中的失败标签属于不可变历史口径。"
                  />}
                  <Space wrap className="v2-code-tags" style={{ marginTop: 16 }}>
                    {(v2Diagnosis.result.limitations || []).map((item: any) => <Tag key={item.code} color="gold">{item.code === "SOURCE_CONTENT_PARTIAL_FAILURE" && v2SourceStatus?.not_fetched && !v2SourceStatus?.fetch_failed ? "历史口径：SOURCE_CONTENT_PARTIAL_FAILURE" : item.code}{typeof item.count === "number" ? ` · ${item.count}` : ""}</Tag>)}
                  </Space>
                </Card>

                {v2PendingSemanticEvents.length > 0 && !v2Diagnosis.review && <Alert
                  type="warning"
                  showIcon
                  message={`${v2PendingSemanticEvents.length} 个候选判断需要人工确认`}
                  description="这是对答案表达方式的复核，不是让你确认品牌能力或渠道效果。逐项处理后才能完成本版审核。"
                  action={<Button onClick={() => document.getElementById("v2-answer-semantic-review")?.scrollIntoView({ behavior: "smooth", block: "start" })}>前往审核</Button>}
                />}

                <Card
                  id="v2-answer-semantic-review"
                  size="small"
                  title="待人工确认的候选判断"
                  extra={<Space wrap><Tag color={v2PendingSemanticEvents.length ? "gold" : "green"}>{v2AnsweredSemanticReviewCount}/{v2PendingSemanticEvents.length} 已处理</Tag><Text type="secondary">确认候选不等于推荐或品牌事实</Text></Space>}
                >
                  {v2PendingSemanticEvents.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有待人工确认的候选判断" /> : <>
                    <Alert
                      style={{ marginBottom: 12 }}
                      type="info"
                      showIcon
                      message="只判断：答案是否把这个工具作为当前场景下的可选方案"
                      description="没有‘推荐’二字不一定只是提及；确认后仍保持 INCLUDE_AS_OPTION，不会升级为 RECOMMEND，也不会写入 Product Truth。"
                    />
                    <Table
                      rowKey="event_id"
                      size="small"
                      pagination={false}
                      dataSource={v2PendingSemanticEvents}
                      scroll={{ x: 920 }}
                      columns={[
                        { title: "Run", dataIndex: "run_id", width: 72 },
                        { title: "对象", dataIndex: "entity_text", width: 140, render: (value: string) => <Text strong>{value}</Text> },
                        { title: "当前判断", width: 160, render: (_: unknown, row: any) => <Space direction="vertical" size={2}><Tag color="blue">{row.effective_speech_act}</Tag><Text type="secondary">{row.recommendation_strength}</Text></Space> },
                        { title: "答案原文", dataIndex: "answer_span", ellipsis: true },
                        { title: "你的判断", width: 190, render: (_: unknown, row: any) => v2Diagnosis.review ? <Tag>{v2Diagnosis.review.decisions?.find((item: any) => item.scope === "ANSWER_SEMANTIC_EVENT" && item.event_id === row.event_id)?.decision || "未记录"}</Tag> : <Select
                          style={{ width: 175 }}
                          placeholder="请选择"
                          value={v2AnswerReviewDecisions[row.event_id] || v2StoredAnswerReviewDecisions.get(row.event_id)}
                          options={V2_ANSWER_REVIEW_OPTIONS}
                          onChange={(value) => setV2AnswerReviewDecision(row, value)}
                        /> },
                      ]}
                      expandable={{
                        expandedRowRender: (row: any) => <Space direction="vertical" size={8} style={{ width: "100%" }}>
                          <Text type="secondary">Event ID：<Text code>{row.event_id}</Text></Text>
                          <div><Text strong>判断上下文</Text><div style={{ marginTop: 4, whiteSpace: "pre-wrap" }}>{row.grounding?.raw_line_context || row.grounding?.context_span || row.answer_span}</div></div>
                          <div><Text strong>模型抽取理由</Text><Space direction="vertical" size={2} style={{ display: "flex", marginTop: 4 }}>{(row.reasons || []).length ? (row.reasons || []).map((reason: any) => <Text key={reason.reason_id}>{reason.effective_grounded_text || reason.reason_span}</Text>) : <Text type="secondary">没有独立理由</Text>}</Space></div>
                          <div><Text strong>为什么待审</Text><Space direction="vertical" size={2} style={{ display: "flex", marginTop: 4 }}>{(row.semantic_admission?.review_reasons || ["SEMANTIC_REVIEW_REQUIRED"]).map((reason: string) => <Text key={reason}>{v2AnswerReviewReasonLabel(reason)}</Text>)}</Space></div>
                        </Space>,
                      }}
                    />
                  </>}
                </Card>

                <Card size="small" title="回答中的推荐语义">
                  {v2AnswerJobs.some((row: any) => String(row.status || "").startsWith("FAILED")) && <Table
                    style={{ marginBottom: 14 }}
                    rowKey="answer_hash"
                    size="small"
                    pagination={false}
                    dataSource={v2AnswerJobs.filter((row: any) => String(row.status || "").startsWith("FAILED"))}
                    columns={[
                      { title: "回答", dataIndex: "answer_hash", width: 220, render: (value: string) => <Text code>{value.slice(0, 16)}</Text> },
                      { title: "状态", dataIndex: "status", width: 150, render: (value: string) => <Tag color="red">{value}</Tag> },
                      { title: "失败原因", dataIndex: "error", render: (value: string) => value || "未通过回答语义准入" },
                    ]}
                  />}
                  <Table
                    rowKey="event_id"
                    size="small"
                    pagination={false}
                    dataSource={v2VerifiedSemanticEvents}
                    scroll={{ x: 900 }}
                    locale={{ emptyText: "没有机器保守准入事件；待审项请在上方逐项处理" }}
                    columns={[
                      { title: "Run", dataIndex: "run_id", width: 72 },
                      { title: "对象", dataIndex: "entity_text", width: 140, render: (value: string) => <Text strong>{value}</Text> },
                      { title: "语义", width: 190, render: (_: unknown, row: any) => v2Diagnosis.allowed_operations.includes("REVISE") ? <Select
                        style={{ width: 170 }}
                        value={stagedDiagnosisValue("RECOMMENDATION_EVENT", row.event_id, row.effective_speech_act)}
                        onChange={(value) => stageV2DiagnosisEdit("RECOMMENDATION_EVENT", row.event_id, value)}
                        options={["RECOMMEND", "INCLUDE_AS_OPTION", "PRAISE", "COMPARE", "MENTION", "DISCOURAGE", "REJECT"].map((value) => ({ label: value, value }))}
                      /> : <Tag>{row.effective_speech_act}</Tag> },
                      { title: "强度", dataIndex: "recommendation_strength", width: 100, render: (value: string) => <Tag>{value}</Tag> },
                      { title: "原文", dataIndex: "answer_span", ellipsis: true },
                      { title: "理由", width: 300, render: (_: unknown, row: any) => <Space direction="vertical" size={2}>{(row.reasons || []).map((reason: any) => <Text key={reason.reason_id}>{reason.effective_grounded_text || reason.reason_span}</Text>)}</Space> },
                    ]}
                  />
                  {v2MarketCriteria.length > 0 && <div style={{ marginTop: 16 }}>
                    <Text strong>独立市场选择标准</Text>
                    <Table
                      style={{ marginTop: 8 }}
                      rowKey="criterion_id"
                      size="small"
                      pagination={false}
                      dataSource={v2MarketCriteria}
                      columns={[
                        { title: "Run", dataIndex: "run_id", width: 80 },
                        { title: "原文标准", dataIndex: "effective_grounded_text" },
                        { title: "展示概括", dataIndex: "normalized_reason" },
                        { title: "状态", width: 220, render: (_: unknown, row: any) => <Tag color={row.normalization_eligible ? "green" : "gold"}>{row.semantic_validation_status}</Tag> },
                        { title: "操作", width: 150, render: (_: unknown, row: any) => <Button size="small" onClick={() => prepareV2TruthReviewFromCriterion(row)}>核对目标品牌能力</Button> },
                      ]}
                    />
                    <Text type="secondary">市场选择标准独立于品牌推荐理由，不会自动进入品牌事实或 Reason→Truth 关系。</Text>
                  </div>}
                  {(v2DiagnosisOutput?.answer_diagnosis?.unresolved_items?.length || 0) > 0 && <Alert
                    style={{ marginTop: 12 }}
                    type="warning"
                    showIcon
                    message={`${v2DiagnosisOutput?.answer_diagnosis?.unresolved_items?.length || 0} 个未解决问题`}
                    description={<Space direction="vertical" size={2}>{v2DiagnosisOutput?.answer_diagnosis?.unresolved_items?.map((row: any, index: number) => <Text key={`${row.run_id || "unknown"}-${index}`}>{`Run ${row.run_id || "-"}：${typeof row.item === "string" ? row.item : row.reason || "需要人工核对"}`}</Text>)}</Space>}
                  />}
                </Card>

                {v2IsEvidenceResult && <Card id="v2-evidence-review-focus" size="small" title="本次 Evidence 结果" extra={<Text type="secondary">审核当前结果版本，不重复审核 Answer</Text>}>
                  <div className="v2-status-grid">
                    <Statistic title="召回候选关系" value={v2EvidenceRecalledRelations.length} />
                    <Statistic title="已完成关系判断" value={v2EvidenceEvaluatedRelations.length} />
                    <Statistic title="正文主张提取失败" value={v2EvidenceFailedClaimJobs.length} />
                    <Statistic title="未召回（正常裁剪）" value={v2EvidenceNotRecalledRelations.length} />
                    <Statistic title="外部模型调用" value={v2DiagnosisOutput?.usage?.external_llm_calls || 0} />
                    <Statistic title="缓存复用" value={v2DiagnosisOutput?.usage?.llm_cache_hits || 0} />
                  </div>
                  {v2EvidenceFailedClaimJobs.length > 0 && <Alert
                    style={{ marginTop: 14 }}
                    type="warning"
                    showIcon
                    message={`${v2EvidenceFailedClaimJobs.length} 个候选 passage 的 SourceClaim 未通过安全准入`}
                    description={`${v2EvidenceUpstreamFailedRelations.length} 条候选关系因此没有完成判断。它们保留为失败限制，不会被写成“不支持”，也不能靠完成审核自动变成有效证据。`}
                  />}
                  <Divider orientation="left" plain>需要核对的已评估关系</Divider>
                  {v2EvidenceEvaluatedRelations.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本次没有形成可审核的 Evidence 关系；只能审核并保留当前失败和未评估限制" /> : <Table
                    rowKey="relation_id"
                    size="small"
                    pagination={false}
                    dataSource={v2EvidenceEvaluatedRelations}
                    scroll={{ x: 980 }}
                    columns={[
                      { title: "答案理由", width: 260, render: (_: unknown, row: any) => (v2DiagnosisReasonById.get(row.reason_id) as any)?.effective_grounded_text || (v2DiagnosisReasonById.get(row.reason_id) as any)?.reason_span || row.reason_id },
                      { title: "来源", width: 260, render: (_: unknown, row: any) => { const source: any = v2DiagnosisSnapshotById.get(row.source_snapshot_id); return source?.canonical_url ? <Link href={source.canonical_url} target="_blank" ellipsis>{source.title || displaySourceDomain("", source.canonical_url)}</Link> : <Text type="secondary">来源地址不可用</Text>; } },
                      { title: "锚点", width: 110, render: (_: unknown, row: any) => <Tag color={row.anchor_binding === "EXPLICIT" ? "green" : "gold"}>{row.anchor_binding === "EXPLICIT" ? "回答明确绑定" : "未证明回答使用"}</Tag> },
                      { title: "机器结论", width: 230, render: (_: unknown, row: any) => <Text>{v2EvidenceRelationLabel(row.machine_relation)}</Text> },
                      { title: "审核结论", width: 250, render: (_: unknown, row: any) => v2Diagnosis.allowed_operations.includes("REVISE") ? <Select
                        style={{ width: 235 }}
                        value={stagedDiagnosisValue("EVIDENCE_RELATION", row.relation_id, row.effective_relation)}
                        onChange={(value) => stageV2DiagnosisEdit("EVIDENCE_RELATION", row.relation_id, value)}
                        options={["SOURCE_SUPPORTS_REASON", "SOURCE_CONTRADICTS_REASON", "RELATED", "NONE"].map((value) => ({ label: v2EvidenceRelationLabel(value), value }))}
                      /> : <Text>{v2EvidenceRelationLabel(row.effective_relation)}</Text> },
                    ]}
                    expandable={{
                      expandedRowRender: (row: any) => <Space direction="vertical" size={8} style={{ width: "100%" }}>
                        {(row.claim_relations || []).filter((item: any) => item.evaluation === "EVALUATED").map((item: any) => <div key={item.claim_id}><Text strong>判断依据：</Text><Text>{item.rationale || "未提供"}</Text></div>)}
                        <Text type="secondary">关系 ID：<Text code>{row.relation_id}</Text></Text>
                      </Space>,
                    }}
                  />}
                  <Alert style={{ marginTop: 14 }} type="info" showIcon message="为什么还要人工审核？" description="模型只负责提出 SourceClaim 和关系结论。人工审核用于确认新增关系是否可进入后续策略，并接受仍然存在的失败、未评估和 UNPROVEN 锚点限制；不会让失败项自动通过。" />
                </Card>}

                <Card size="small" title="全部引用与理由关系" extra={<Text type="secondary">来源出现、原文锚点、候选召回、关系判断分别记录</Text>}>
                  <Table
                    className="v2-evidence-table"
                    rowKey="relation_id"
                    size="small"
                    dataSource={v2DiagnosisRelations}
                    pagination={{ pageSize: 10, showSizeChanger: false }}
                    scroll={{ x: 1160 }}
                    tableLayout="fixed"
                    columns={[
                      { title: "理由", width: 210, render: (_: unknown, row: any) => (v2DiagnosisReasonById.get(row.reason_id) as any)?.normalized_reason || row.reason_id },
                      { title: "引用来源", width: 260, render: (_: unknown, row: any) => { const source: any = v2DiagnosisSnapshotById.get(row.source_snapshot_id); return source?.canonical_url ? <Link href={source.canonical_url} target="_blank" ellipsis>{source.title || displaySourceDomain("", source.canonical_url)}</Link> : <Text type="secondary">来源地址不可用</Text>; } },
                      { title: "回答中出现", width: 110, render: (_: unknown, row: any) => <Tag color={row.reference_observation === "OBSERVED" ? "green" : "default"}>{row.reference_observation}</Tag> },
                      { title: "原文锚点", width: 110, render: (_: unknown, row: any) => <Tag color={row.anchor_binding === "EXPLICIT" ? "green" : "gold"}>{row.anchor_binding}</Tag> },
                      { title: "候选召回", width: 120, render: (_: unknown, row: any) => <Tag color={row.candidate_recall === "RECALLED" ? "blue" : "default"}>{row.candidate_recall}</Tag> },
                      { title: "判断状态", width: 180, render: (_: unknown, row: any) => <Space size={4} wrap><Tag color={row.alignment_evaluation === "EVALUATED" ? "green" : ["FAILED", "UPSTREAM_CLAIM_FAILED"].includes(row.alignment_evaluation) ? "red" : "gold"}>{v2EvidenceEvaluationLabel(row.alignment_evaluation)}</Tag>{v2BlockedHistoricalRelations.has(row.relation_id) && <Tag color="red">当前不可消费</Tag>}</Space> },
                      { title: "关系结论", width: 230, render: (_: unknown, row: any) => v2Diagnosis.allowed_operations.includes("REVISE") && row.alignment_evaluation === "EVALUATED" ? <Select
                        style={{ width: 215 }}
                        value={stagedDiagnosisValue("EVIDENCE_RELATION", row.relation_id, row.effective_relation)}
                        onChange={(value) => stageV2DiagnosisEdit("EVIDENCE_RELATION", row.relation_id, value)}
                        options={["SOURCE_SUPPORTS_REASON", "SOURCE_CONTRADICTS_REASON", "RELATED", "NONE"].map((value) => ({ label: v2EvidenceRelationLabel(value), value }))}
                      /> : <Text>{v2EvidenceRelationLabel(row.effective_relation)}</Text> },
                    ]}
                  />
                  <Alert type="info" showIcon message="SOURCE_SUPPORTS_REASON 只表示来源正文支持该理由；锚点为 UNPROVEN 时，不代表本次回答实际使用了该来源作为推荐依据。" />
                </Card>

                <Card id="v2-target-brand-truth" size="small" title={`核对${project?.brand_name || "目标品牌"}的能力`} extra={<Text type="secondary">已确认 {v2ConfirmedTargetCapabilityCount}/{v2TargetCapabilityReviewItems.length}</Text>}>
                  <Alert
                    type="info"
                    showIcon
                    message="逐项确认目标品牌是否具备这些能力"
                    description="能力来自已经审核的目标品牌答案片段。这里只快速确认目标品牌有没有，不核对竞品；依据可以稍后在公开内容制作前补充。"
                  />
                  <Table
                    className="v2-capability-desktop"
                    style={{ marginTop: 12 }}
                    rowKey="candidate_id"
                    size="small"
                    pagination={false}
                    dataSource={v2TargetCapabilityReviewItems}
                    expandable={{
                      expandedRowRender: (row) => <Space direction="vertical" size={4} style={{ width: "100%" }}>
                        <Text type="secondary">答案原文</Text>
                        {row.answer_excerpts.map((excerpt) => <Text key={excerpt}>{excerpt}</Text>)}
                      </Space>,
                      rowExpandable: (row) => row.answer_excerpts.length > 0,
                    }}
                    columns={[
                      { title: "单一能力", dataIndex: "capability_label", width: 320 },
                      { title: "来自回答", width: 150, render: (_: unknown, row: SinglePromptV2DiagnosisStatus["target_capability_review_items"][number]) => <Space wrap>{row.source_run_ids.map((runId) => <Tag key={runId}>Run {runId}</Tag>)}</Space> },
                      { title: "目标品牌是否具备", width: 170, render: (_: unknown, row: SinglePromptV2DiagnosisStatus["target_capability_review_items"][number]) => row.current_truth ? <Tag color={row.current_truth.product_truth_status === "SUPPORTED" ? "green" : row.current_truth.product_truth_status === "NOT_SUPPORTED" ? "red" : "gold"}>{capabilityPresenceLabel(row.current_truth.product_truth_status)}</Tag> : <Tag>待确认</Tag> },
                      { title: "公开声明资格", render: (_: unknown, row: SinglePromptV2DiagnosisStatus["target_capability_review_items"][number]) => row.current_truth ? (row.current_truth.statement_eligibility?.status === "ELIGIBLE" ? <Tag color="green">依据已齐</Tag> : <Tag color="gold">发布前补依据</Tag>) : <Text type="secondary">待确认能力</Text> },
                      { title: "操作", width: 120, render: (_: unknown, row: SinglePromptV2DiagnosisStatus["target_capability_review_items"][number]) => row.current_truth ? <Text type="secondary">已确认</Text> : <Button size="small" onClick={() => prepareV2TargetCapabilityReview(row)}>确认</Button> },
                    ]}
                  />
                  <div className="v2-capability-mobile">
                    {v2TargetCapabilityReviewItems.map((row) => <div className="v2-capability-mobile-row" key={row.candidate_id}>
                      <Space direction="vertical" size={8} style={{ width: "100%" }}>
                        <Text strong>{row.capability_label}</Text>
                        <Space wrap>{row.source_run_ids.map((runId) => <Tag key={runId}>Run {runId}</Tag>)}</Space>
                        <Space wrap>
                          {row.current_truth
                            ? <Tag color={row.current_truth.product_truth_status === "SUPPORTED" ? "green" : row.current_truth.product_truth_status === "NOT_SUPPORTED" ? "red" : "gold"}>{capabilityPresenceLabel(row.current_truth.product_truth_status)}</Tag>
                            : <Tag>待确认能力</Tag>}
                          {row.current_truth && <Tag color={row.current_truth.statement_eligibility?.status === "ELIGIBLE" ? "green" : "gold"}>{row.current_truth.statement_eligibility?.status === "ELIGIBLE" ? "依据已齐" : "发布前补依据"}</Tag>}
                        </Space>
                        {row.current_truth
                          ? <Text type="secondary">能力已确认</Text>
                          : <Button size="small" onClick={() => prepareV2TargetCapabilityReview(row)}>确认这项能力</Button>}
                      </Space>
                    </div>)}
                  </div>
                  {v2TargetCapabilityReviewItems.length === 0 && <Alert style={{ marginTop: 12 }} type="warning" showIcon message="当前没有可核对的目标品牌能力" description="这可能是答案没有提到目标品牌，或目标品牌事件尚未完成人工审核；不会自动解释为目标品牌没有能力。" />}
                  {v2Diagnosis.project_truth_state.differs_from_frozen_diagnosis && <Alert
                    style={{ marginTop: 14 }}
                    type="info"
                    showIcon
                    message="能力核对结果已更新"
                    description="点击更新后，本次分析会使用刚确认的能力；答案与引用证据不会重跑，也不会调用外部模型。"
                    action={<Button type="primary" icon={<RefreshCw size={15} />} loading={v2DiagnosisLoading} disabled={!v2Diagnosis.review} onClick={createV2DiagnosisForUpdatedTruths}>更新本次分析</Button>}
                  />}
                  <div id="v2-truth-review-form" style={{ marginTop: 16 }}>
                    <Divider orientation="left" plain>确认一项能力</Divider>
                    <Alert
                      type="info"
                      showIcon
                      message="现在只确认有没有；依据可稍后补"
                      description="选择“有”后即可参与策略适用性判断。未提供依据时不能进入公开标题、正文或产品声明，执行内容阶段仍会被后端拦截。"
                    />
                    <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
                      <Col xs={24} md={10}><Input value={v2TruthDraft.capabilityLabel} onChange={(event) => setV2TruthDraft((current) => ({ ...current, capabilityLabel: event.target.value }))} placeholder="先点击上方一项能力" maxLength={160} /></Col>
                      <Col xs={24} md={6}><Select style={{ width: "100%" }} value={v2TruthDraft.productTruthStatus} onChange={(value) => setV2TruthDraft((current) => ({ ...current, productTruthStatus: value }))} options={[
                        { value: "SUPPORTED", label: "有" },
                        { value: "PARTIALLY_SUPPORTED", label: "部分有" },
                        { value: "NOT_SUPPORTED", label: "没有" },
                        { value: "UNKNOWN", label: "不确定" },
                      ]} /></Col>
                      <Col xs={24} md={8}><Input value={v2TruthDraft.sourceReference} onChange={(event) => setV2TruthDraft((current) => ({ ...current, sourceReference: event.target.value }))} placeholder="目标品牌依据（可选，发布前补齐）" /></Col>
                      <Col xs={24} md={18}><Input value={v2TruthDraft.note} onChange={(event) => setV2TruthDraft((current) => ({ ...current, note: event.target.value }))} placeholder="补充说明（可选）" /></Col>
                      <Col xs={24} md={6}><Button block type="primary" icon={<ShieldCheck size={15} />} loading={v2TruthSaving} onClick={submitV2TargetBrandTruth}>保存核对结果</Button></Col>
                    </Row>
                  </div>
                </Card>

                <Card id="v2-diagnosis-review" size="small" title="审核与版本" extra={v2NoConsumableAnswerSemantic ? <Tag color="red">不可审核</Tag> : v2Diagnosis.review ? <Tag color="green">REVIEW_COMPLETED</Tag> : <Tag color="gold">待审核</Tag>}>
                  {v2NoConsumableAnswerSemantic ? <Alert type="error" showIcon message="当前结果不能完成审核" description="所有回答语义均未通过准入。审核不能把 Schema 失败升级为有效推荐、理由或策略输入。" /> : v2Diagnosis.review ? <Descriptions size="small" column={{ xs: 1, md: 2 }}>
                    <Descriptions.Item label="审核记录"><Text code>{v2Diagnosis.review.review_id}</Text></Descriptions.Item>
                    <Descriptions.Item label="审核人">{v2Diagnosis.review.reviewer}</Descriptions.Item>
                    <Descriptions.Item label="绑定结果">{v2Diagnosis.review.result_version}</Descriptions.Item>
                    <Descriptions.Item label="审核时间">{formatDateTime(v2Diagnosis.review.created_at)}</Descriptions.Item>
                    <Descriptions.Item label="说明" span={2}>{v2Diagnosis.review.note || "未填写"}</Descriptions.Item>
                  </Descriptions> : <Space direction="vertical" size={12} style={{ width: "100%" }}>
                    <Row gutter={[12, 12]}>
                      <Col xs={24} md={8}><Input value={v2DiagnosisEditor} onChange={(event) => setV2DiagnosisEditor(event.target.value)} placeholder="审核人" /></Col>
                      <Col xs={24} md={16}><Input value={v2DiagnosisEditReason} onChange={(event) => setV2DiagnosisEditReason(event.target.value)} placeholder="有语义修改时填写修改原因" /></Col>
                    </Row>
                    {v2PendingSemanticEvents.length > 0 && <Alert
                      type={v2AnsweredSemanticReviewCount === v2PendingSemanticEvents.length ? "success" : "warning"}
                      showIcon
                      message={`候选判断已处理 ${v2AnsweredSemanticReviewCount}/${v2PendingSemanticEvents.length}`}
                      description="可以保留不确定，但每个待审事件都必须有明确处置。只有“确认是候选”可进入后续消费；它仍不是 RECOMMEND、品牌事实或证据结论。"
                    />}
                    {Object.keys(v2DiagnosisEdits).length > 0 && <Alert type="warning" showIcon message={`${Object.keys(v2DiagnosisEdits).length} 项修改尚未保存为新版本`} action={<Button type="primary" loading={v2DiagnosisLoading} onClick={saveV2DiagnosisRevision}>保存为新版本</Button>} />}
                    <Input.TextArea value={v2DiagnosisReviewNote} onChange={(event) => setV2DiagnosisReviewNote(event.target.value)} rows={2} placeholder="审核说明，可记录仍待补充的事实或来源限制" />
                    <Popconfirm title="完成当前结果版本审核？" description="审核完成不会把 UNRESOLVED、UNPROVEN 或失败项改成已确认事实。" onConfirm={completeV2DiagnosisReview} okText="完成审核" cancelText="取消">
                      <Button type="primary" icon={<ShieldCheck size={15} />} loading={v2DiagnosisLoading} disabled={Object.keys(v2DiagnosisEdits).length > 0 || v2AnsweredSemanticReviewCount < v2PendingSemanticEvents.length}>完成本版审核</Button>
                    </Popconfirm>
                  </Space>}
                  <Collapse ghost style={{ marginTop: 12 }} items={[{
                    key: "audit",
                    label: "查看输入与版本审计",
                    children: <Descriptions size="small" column={1}>
                      <Descriptions.Item label="AnalysisContext">{v2Diagnosis.diagnosis.context_id}</Descriptions.Item>
                      <Descriptions.Item label="Raw output SHA-256"><Text code copyable>{v2Diagnosis.diagnosis.raw_output_hash}</Text></Descriptions.Item>
                      <Descriptions.Item label="品牌快照 SHA-256"><Text code copyable>{v2Diagnosis.diagnosis.brand_snapshot_hash}</Text></Descriptions.Item>
                      <Descriptions.Item label="事实集合 SHA-256"><Text code copyable>{v2Diagnosis.diagnosis.truth_set_hash}</Text></Descriptions.Item>
                      <Descriptions.Item label="结果 SHA-256"><Text code copyable>{v2Diagnosis.result?.output_hash}</Text></Descriptions.Item>
                      <Descriptions.Item label="审核集合 SHA-256"><Text code copyable>{v2Diagnosis.result?.reviewable_set_hash}</Text></Descriptions.Item>
                    </Descriptions>,
                  }]} />
                </Card>

                <Card size="small" title={<Space><ShieldCheck size={18} />Evidence 双输入 Gate</Space>}>
                  <Space direction="vertical" size={12} style={{ width: "100%" }}>
                    <Descriptions size="small" column={{ xs: 1, md: 3 }}>
                      <Descriptions.Item label="诊断范围"><Tag>{v2Diagnosis.result.output.result_scope || "LEGACY_RESULT"}</Tag></Descriptions.Item>
                      <Descriptions.Item label="Answer Result"><Text code>{v2Diagnosis.result.result_version}</Text></Descriptions.Item>
                      <Descriptions.Item label="Answer Review">{v2Diagnosis.review ? <Text code>{v2Diagnosis.review.review_id}</Text> : <Tag color="gold">尚未审核</Tag>}</Descriptions.Item>
                      <Descriptions.Item label="Citation Manifest">{v2SourcePreparation ? <Text code>{v2SourcePreparation.citation_manifest.manifest_id}</Text> : <Tag color="red">缺失</Tag>}</Descriptions.Item>
                      <Descriptions.Item label="Source Completion">{v2SourcePreparation?.completion_manifest ? <Tag color={v2SourcePreparation.completion_manifest.status === "FROZEN" ? "green" : "red"}>{v2SourcePreparation.completion_manifest.status}</Tag> : <Tag color="gold">尚未冻结</Tag>}</Descriptions.Item>
                      <Descriptions.Item label="Evidence 外部策略">{v2Diagnosis.result.output.result_scope === "ANSWER_ONLY" ? <Select style={{ minWidth: 150 }} value={v2EvidencePolicy} onChange={setV2EvidencePolicy} options={[{ value: "CACHE_ONLY", label: "仅兼容缓存" }, { value: "ALLOW_EXTERNAL", label: "授权 Evidence LLM" }]} /> : "已形成结果"}</Descriptions.Item>
                    </Descriptions>
                    {v2Diagnosis.result.output.result_scope === "ANSWER_AND_EVIDENCE" ? <Alert type="success" showIcon message="Evidence 已消费精确双输入版本" description="当前 Evidence 结果是新的不可变 ResultVersion；若需人工确认，应审核这个新版本，不能继承 Answer-only 版本的审核。" /> : v2Diagnosis.result.output.result_scope !== "ANSWER_ONLY" ? <Alert type="info" showIcon message="历史诊断结果不具备本切片的显式 Evidence 交接身份" description="系统不会通过 latest Snapshot 或旧工作流状态补齐。" /> : <>
                      {!v2Diagnosis.review && <Alert type="warning" showIcon message="Answer Result 尚未完成精确版本审核" description="Evidence 不会把机器输出或其他结果版本的审核当成本次授权。" />}
                      {!v2SourcePreparation?.completion_manifest && <Alert type="warning" showIcon message="来源处置范围尚未冻结" description="请先逐条处置 Citation Manifest 中全部来源，再冻结 Source Completion Manifest。" />}
                      {v2SourcePreparation?.completion_manifest?.status === "NO_USABLE_SOURCE" && <Alert type="error" showIcon message="没有可消费的正文来源" description="全部来源被放弃只能关闭处置清单，不能获得来源证据资格。" />}
                      <Popconfirm title="执行 Evidence 消费？" description="将严格绑定当前 Answer Result/Review 与 Source Completion Manifest；选择外部 LLM 时必须已有明确授权。" okText="执行" cancelText="取消" onConfirm={continueV2Evidence}>
                        <Button type="primary" icon={<Play size={15} />} loading={v2DiagnosisLoading} disabled={!v2Diagnosis.review || v2SourcePreparation?.completion_manifest?.status !== "FROZEN"}>通过 Gate 并执行 Evidence</Button>
                      </Popconfirm>
                    </>}
                  </Space>
                </Card>

                {!RELEASE_FIRST_SLICE && <>
                <Card
                  id="v2-strategy"
                  size="small"
                  title={<Space><ListChecks size={18} />审核后诊断 → 有依据的策略候选</Space>}
                  extra={<Space wrap>
                    {v2StrategyReadiness && <Tag color={v2StrategyReadiness.classification === "C" ? "green" : v2StrategyReadiness.classification === "B" ? "gold" : "blue"}>{`输入类型 ${v2StrategyReadiness.classification}`}</Tag>}
                    <Button icon={<RefreshCw size={14} />} loading={v2StrategyLoading} onClick={() => refreshV2StrategyContext()} aria-label="刷新策略状态" />
                  </Space>}
                >
                  {!v2StrategyReadiness ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={v2StrategyLoading ? "正在读取策略资格" : "尚未形成策略输入投影"} /> : <Space direction="vertical" size={14} style={{ width: "100%" }}>
                    <Descriptions size="small" column={{ xs: 1, md: 3 }}>
                      <Descriptions.Item label="可消费理由">{v2StrategyReadiness.current_observation.fact_consumable_reason_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="来源快照">{v2StrategyReadiness.current_observation.source_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="有效证据关系">{v2StrategyReadiness.current_observation.effective_evidence_relation_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="已确认能力">{v2StrategyReadiness.current_observation.confirmed_capability_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="公开可写事实">{v2StrategyReadiness.current_observation.public_claim_eligible_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="合格方向">{v2StrategyReadiness.qualified_direction_count}</Descriptions.Item>
                    </Descriptions>

                    <div className="v2-strategy-band">
                      <Space wrap><Text strong>权威事实基础</Text><Tag color={v2StrategyReadiness.foundation.state === "REQUIRED" ? "green" : v2StrategyReadiness.foundation.state === "UNKNOWN" ? "gold" : "default"}>{v2StrategyReadiness.foundation.state}</Tag></Space>
                      <Text type="secondary">{v2StrategyReadiness.foundation.reason}</Text>
                      <Text type="secondary">Foundation 只说明事实承载基础需求，不选择渠道，也不要求必须存在 PRIMARY。</Text>
                    </div>

                    {v2StrategyReadiness.observed_themes.length > 0 && <div>
                      <Text strong>当前观察主题</Text>
                      <Space wrap className="v2-theme-tags" style={{ marginTop: 8 }}>
                        {v2StrategyReadiness.observed_themes.map((theme: any) => <Tag key={theme.theme_id}>{theme.title}</Tag>)}
                      </Space>
                    </div>}

                    <Table
                      size="small"
                      rowKey="channel_key"
                      pagination={false}
                      dataSource={v2StrategyReadiness.channel_assessments}
                      locale={{ emptyText: "当前没有可识别的渠道环境" }}
                      scroll={{ x: 760 }}
                      columns={[
                        { title: "渠道环境", width: 150, render: (_: unknown, row: any) => <Text strong>{row.channel_label}</Text> },
                        { title: "处理层级", width: 110, render: (_: unknown, row: any) => <Tag color={row.level === "ACTIONABLE" ? "green" : row.level === "BLOCKED" ? "red" : "gold"}>{row.level}</Tag> },
                        { title: "渠道 Role", width: 100, render: (_: unknown, row: any) => <Tag>{row.channel_role}</Tag> },
                        { title: "依据", dataIndex: "rationale" },
                        { title: "未解决", width: 230, render: (_: unknown, row: any) => <Space wrap>{(row.blocking_signals || []).map((value: string) => <Tag key={value} color="gold">{value}</Tag>)}</Space> },
                      ]}
                    />

                    {v2StrategyReadiness.blocker && <Alert
                      type={v2StrategyReadiness.classification === "A" ? "info" : "warning"}
                      showIcon
                      message={v2StrategyReadiness.blocker.code === "DIAGNOSIS_REVIEW_REQUIRED" ? "请先完成当前诊断版本审核" : "当前没有通过资格 Gate 的策略方向"}
                      description={v2StrategyReadiness.blocker.detail}
                      action={v2StrategyReadiness.classification === "A" ? <Button size="small" onClick={() => document.getElementById("v2-diagnosis-review")?.scrollIntoView({ behavior: "smooth", block: "center" })}>前往诊断审核</Button> : undefined}
                    />}

                    {v2StrategyReadiness.verification_items.length > 0 && <div>
                      <Text strong>限制与合法下一步</Text>
                      <div className="v2-strategy-list">
                        {v2StrategyReadiness.verification_items.map((item) => <div key={item.code} className="v2-strategy-list-row"><Tag color="gold">{v2StrategyVerificationLabel(item.code)}</Tag><Text>{item.detail}</Text></div>)}
                      </div>
                    </div>}

                    {v2StrategyReadiness.can_create_strategy && !v2Strategy && <Alert
                      type="success"
                      showIcon
                      message={`${v2StrategyReadiness.qualified_direction_count} 个方向通过资格 Gate`}
                      description="只会冻结并保存这些合格方向；其余未知、未评估和受限项继续随候选保留。"
                      action={<Button type="primary" icon={<Play size={15} />} loading={v2StrategyLoading} onClick={createV2Strategy}>生成策略候选</Button>}
                    />}

                    {v2Strategy?.result && <>
                      <Divider orientation="left">策略候选</Divider>
                      <Descriptions size="small" column={{ xs: 1, md: 3 }}>
                        <Descriptions.Item label="策略 ID"><Text code copyable>{v2Strategy.strategy.strategy_id}</Text></Descriptions.Item>
                        <Descriptions.Item label="结果版本"><Text code>{v2Strategy.result.result_version}</Text></Descriptions.Item>
                        <Descriptions.Item label="审核状态">{v2Strategy.review ? <Tag color={v2Strategy.review.decision === "ACCEPTED" ? "green" : "red"}>{v2Strategy.review.decision}</Tag> : <Tag color="gold">待审核</Tag>}</Descriptions.Item>
                        <Descriptions.Item label="消费诊断版本"><Text code>{v2Strategy.strategy.diagnosis_result_version}</Text></Descriptions.Item>
                        <Descriptions.Item label="消费诊断审核"><Text code>{v2Strategy.strategy.diagnosis_review_id}</Text></Descriptions.Item>
                        <Descriptions.Item label="验证契约"><Text code>{v2Strategy.strategy.validation_contract_version}</Text></Descriptions.Item>
                      </Descriptions>
                      {!v2Strategy.applicability.is_current_input && <Alert type="warning" showIcon message="该策略候选已成为历史版本" description="诊断结果、审核快照或当前安全消费范围已经变化；本候选保留可查，但不能继续修改或审核。" />}

                      <div className="v2-strategy-list">
                        {v2OrderedStrategyDirections.map((direction, index) => <div key={direction.direction_id} className="v2-strategy-direction">
                          <div className="v2-strategy-direction-order"><Text strong>{v2Strategy.result?.output.needs_human_prioritization ? "同层" : index + 1}</Text></div>
                          <div className="v2-strategy-direction-body">
                            <Space wrap>
                              <Text strong>{direction.direction_type === "FOUNDATION" ? "权威事实基础" : direction.channel_label}</Text>
                              <Tag color="green">{direction.level}</Tag>
                              {direction.channel_role && <Tag color={direction.channel_role === "PRIMARY" ? "blue" : "purple"}>{direction.channel_role}</Tag>}
                              <Tag>{direction.effect_status}</Tag>
                            </Space>
                            <Text>{direction.rationale}</Text>
                            {direction.hypothesis && <Text type="secondary">测试假设：{direction.hypothesis}</Text>}
                            <Text type="secondary">Reason {direction.reason_ids.join("、") || "无"} · Truth {direction.truth_ids.join("、") || "无"} · Evidence {direction.evidence_relation_ids.join("、") || "无"}</Text>
                          </div>
                          {!v2Strategy.review && v2Strategy.allowed_operations.includes("REVISE") && v2Strategy.result?.output.needs_human_prioritization && <Space size={4}>
                            <Tooltip title="上移"><Button icon={<ArrowUp size={14} />} disabled={index === 0} onClick={() => moveV2StrategyDirection(direction.direction_id, -1)} aria-label="上移策略方向" /></Tooltip>
                            <Tooltip title="下移"><Button icon={<ArrowDown size={14} />} disabled={index === v2OrderedStrategyDirections.length - 1} onClick={() => moveV2StrategyDirection(direction.direction_id, 1)} aria-label="下移策略方向" /></Tooltip>
                          </Space>}
                        </div>)}
                      </div>

                      {v2Strategy.result.output.needs_human_prioritization && !v2Strategy.review && v2Strategy.allowed_operations.includes("REVISE") && <Alert type="warning" showIcon message="多个同层方向无法由确定性规则唯一排序" description="调整顺序并写明人工判断依据；系统不会用引用次数或隐藏分数制造 P1。" />}

                      {!v2Strategy.review && v2Strategy.allowed_operations.includes("REVIEW") ? <Space direction="vertical" size={10} style={{ width: "100%" }}>
                        <Row gutter={[12, 12]}>
                          <Col xs={24} md={8}><Input value={v2StrategyEditor} onChange={(event) => setV2StrategyEditor(event.target.value)} placeholder="策略审核人" /></Col>
                          <Col xs={24} md={16}><Input value={v2StrategyPriorityReason} onChange={(event) => setV2StrategyPriorityReason(event.target.value)} placeholder="调整优先顺序时填写判断依据" /></Col>
                        </Row>
                        {v2Strategy.result.output.needs_human_prioritization && <Button icon={<ListChecks size={15} />} loading={v2StrategyLoading} onClick={saveV2StrategyPriority}>保存优先顺序为新版本</Button>}
                        <Input.TextArea value={v2StrategyNote} onChange={(event) => setV2StrategyNote(event.target.value)} rows={2} placeholder="策略审核说明；未知和限制不会因确认而消失" />
                        <Space wrap>
                          <Popconfirm title="确认当前策略候选？" description="确认只追加审核记录，不修改机器结果，也不会创建执行方案。" onConfirm={() => reviewV2Strategy("ACCEPTED")} okText="确认" cancelText="取消">
                            <Button type="primary" icon={<ShieldCheck size={15} />} disabled={v2Strategy.result.output.needs_human_prioritization} loading={v2StrategyLoading}>确认策略</Button>
                          </Popconfirm>
                          <Popconfirm title="拒绝当前策略候选？" onConfirm={() => reviewV2Strategy("REJECTED")} okText="拒绝" cancelText="取消">
                            <Button danger loading={v2StrategyLoading}>拒绝</Button>
                          </Popconfirm>
                        </Space>
                      </Space> : v2Strategy.review ? <Alert type={v2Strategy.review.decision === "ACCEPTED" ? "success" : "warning"} showIcon message={`策略审核：${v2Strategy.review.decision}`} description={v2Strategy.review.note || "未填写审核说明"} /> : null}

                      <Collapse ghost items={[{
                        key: "strategy-audit",
                        label: "查看策略输入、限制与版本审计",
                        children: <Space direction="vertical" size={10} style={{ width: "100%" }}>
                          <Descriptions size="small" column={1}>
                            <Descriptions.Item label="诊断审核快照 SHA-256"><Text code copyable>{v2Strategy.strategy.review_snapshot_hash}</Text></Descriptions.Item>
                            <Descriptions.Item label="策略输入 SHA-256"><Text code copyable>{v2Strategy.strategy.input_snapshot_hash}</Text></Descriptions.Item>
                            <Descriptions.Item label="策略结果 SHA-256"><Text code copyable>{v2Strategy.result.output_hash}</Text></Descriptions.Item>
                            <Descriptions.Item label="审核集合 SHA-256"><Text code copyable>{v2Strategy.result.reviewable_set_hash}</Text></Descriptions.Item>
                          </Descriptions>
                          <Space wrap>{(v2Strategy.result.output.limitations || []).map((item: any, index: number) => <Tag color="gold" key={`${item.code || "LIMITATION"}-${index}`}>{item.code || "LIMITATION"}</Tag>)}</Space>
                          <Alert type="info" showIcon message="边界保持" description="测试方向只是假设；CONTENT_BLOCKED、UNPROVEN、UNRESOLVED 与 NOT_EVALUATED 不会因策略审核被升级或清除。" />
                        </Space>,
                      }]} />
                    </>}
                  </Space>}
                </Card>

                <Card size="small" title={<Space><FileText size={18} />执行内容骨架、确认与发布登记</Space>} extra={v2Execution && <Tooltip title="只读取当前执行方案、确认和发布记录"><Button icon={<RefreshCw size={15} />} loading={v2ExecutionLoading} onClick={refreshV2Execution} aria-label="刷新执行方案" /></Tooltip>}>
                  {!v2Strategy?.result ? <Alert type="info" showIcon message="尚无策略候选" description="当前诊断需要先形成合法策略方向。" />
                  : !v2Strategy.review || v2Strategy.review.decision !== "ACCEPTED" ? <Alert type="warning" showIcon message="策略尚未确认" description="执行方案只能消费已确认的精确策略结果版本；人工排序不等于确认。" />
                  : !v2Execution ? <Space direction="vertical" size={12} style={{ width: "100%" }}>
                    <Alert type="info" showIcon message="选择一个已确认方向" description="一次方案只承接一个方向和一个新资产，不会合并多个渠道或页面。" />
                    <Select
                      style={{ width: "100%", maxWidth: 620 }}
                      placeholder="选择执行方向"
                      value={v2ExecutionDirectionId || undefined}
                      onChange={setV2ExecutionDirectionId}
                      options={(v2Strategy.result.output.directions || []).map((row) => ({
                        value: row.direction_id,
                        label: row.direction_type === "FOUNDATION" ? "权威事实基础" : `${row.channel_label} · ${row.channel_role}`,
                      }))}
                    />
                    <Button type="primary" icon={<FileText size={15} />} disabled={!v2ExecutionDirectionId} loading={v2ExecutionLoading} onClick={createV2ExecutionProposal}>生成执行内容骨架</Button>
                  </Space> : v2ExecutionOutput ? <Space direction="vertical" size={14} style={{ width: "100%" }}>
                    <Descriptions size="small" column={{ xs: 1, md: 3 }}>
                      <Descriptions.Item label="方案 ID"><Text code copyable>{v2Execution.proposal.proposal_id}</Text></Descriptions.Item>
                      <Descriptions.Item label="结果版本"><Text code>{v2Execution.result?.result_version}</Text></Descriptions.Item>
                      <Descriptions.Item label="状态"><Tag color={v2ExecutionConfirmation ? "green" : v2ExecutionOutput.validation.status === "READY_FOR_CONFIRMATION" ? "blue" : "gold"}>{v2ExecutionConfirmation ? "已确认，待发布" : v2ExecutionOutput.validation.status === "READY_FOR_CONFIRMATION" ? "可确认" : "待补充"}</Tag></Descriptions.Item>
                      <Descriptions.Item label="策略方向">{v2ExecutionOutput.direction.direction_type === "FOUNDATION" ? "权威事实基础" : v2ExecutionOutput.direction.channel_label}</Descriptions.Item>
                      <Descriptions.Item label="策略渠道 Role">{v2ExecutionOutput.strategy_channel.channel_role || "无（Foundation 独立）"}</Descriptions.Item>
                      <Descriptions.Item label="资产操作"><Tag color="blue">新建资产</Tag></Descriptions.Item>
                    </Descriptions>
                    {v2ExecutionOutput.direction.direction_type === "FOUNDATION" && <Alert type="info" showIcon message="Foundation 与渠道 Role 保持分离" description="下面选择的官网产品页、功能页或帮助中心只是执行目的地，不会把策略改成 OFFICIAL_SITE PRIMARY。" />}
                    {!v2Execution.applicability.is_current_input && <Alert type="warning" showIcon message="执行输入已经过期" description="历史方案和发布记录仍保留，但该版本不能继续授权新编辑或确认。" />}

                    <Divider orientation="left">资产制作简报</Divider>
                    <Row gutter={[12, 12]}>
                      <Col xs={24} md={8}><Text type="secondary">资产类型</Text><Select style={{ width: "100%", marginTop: 5 }} value={v2ExecutionEdit.asset_type || undefined} options={v2ExecutionOutput.asset_type_candidates.map((row) => ({ label: row.label, value: row.asset_type }))} onChange={(value) => setV2ExecutionEdit((current) => ({ ...current, asset_type: value, publication_surface: null }))} /></Col>
                      <Col xs={24} md={8}><Text type="secondary">计划发布位置</Text><Select style={{ width: "100%", marginTop: 5 }} value={v2ExecutionEdit.publication_surface || undefined} options={v2ExecutionOutput.publication_surface_candidates.filter((row) => row.asset_type === v2ExecutionEdit.asset_type).map((row) => ({ label: row.label, value: row.surface_key }))} onChange={(value) => setV2ExecutionEdit((current) => ({ ...current, publication_surface: value }))} /></Col>
                      <Col xs={24} md={8}><Text type="secondary">方案范围</Text><Input style={{ marginTop: 5 }} value="完整承接已确认方向" disabled /></Col>
                      <Col xs={24} md={8}><Text type="secondary">发布账号</Text><Input style={{ marginTop: 5 }} value={v2ExecutionEdit.publishing_account || ""} onChange={(event) => setV2ExecutionEdit((current) => ({ ...current, publishing_account: event.target.value }))} /></Col>
                      <Col xs={24} md={8}><Text type="secondary">栏目或拟建页面位置</Text><Input style={{ marginTop: 5 }} value={v2ExecutionEdit.publishing_location || ""} onChange={(event) => setV2ExecutionEdit((current) => ({ ...current, publishing_location: event.target.value }))} /></Col>
                      <Col xs={24} md={8}><Text type="secondary">账号可操作性</Text><div style={{ marginTop: 9 }}><Checkbox checked={v2ExecutionEdit.account_control_status === "USER_REPORTED_CONTROL"} onChange={(event) => setV2ExecutionEdit((current) => ({ ...current, account_control_status: event.target.checked ? "USER_REPORTED_CONTROL" : "UNVERIFIED" }))}>用户确认可操作</Checkbox></div></Col>
                    </Row>

                    <Divider orientation="left">公开内容骨架</Divider>
                    <Input value={v2ExecutionEdit.title || ""} onChange={(event) => setV2ExecutionEdit((current) => ({ ...current, title: event.target.value }))} addonBefore="安全标题" />
                    <Checkbox.Group
                      style={{ width: "100%" }}
                      value={v2ExecutionEdit.section_order || []}
                      onChange={(values) => setV2ExecutionEdit((current) => ({ ...current, section_order: values }))}
                    >
                      <div className="v2-execution-sections">
                        {v2ExecutionOutput.public_content_candidates.map((section) => {
                          const selectedIndex = (v2ExecutionEdit.section_order || []).indexOf(section.section_id);
                          return <div key={section.section_id} className="v2-execution-section">
                            <Checkbox value={section.section_id} />
                            <div><Text strong>{section.title}</Text><div><Text type="secondary">{section.purpose} · Truth {(section.truth_ids || []).join("、")}</Text></div></div>
                            <Space size={4} className="v2-execution-section-order">
                              <Tooltip title="上移"><Button size="small" icon={<ArrowUp size={14} />} disabled={selectedIndex <= 0} onClick={() => moveV2ExecutionSection(section.section_id, -1)} aria-label="上移公开 Section" /></Tooltip>
                              <Tooltip title="下移"><Button size="small" icon={<ArrowDown size={14} />} disabled={selectedIndex < 0 || selectedIndex >= (v2ExecutionEdit.section_order || []).length - 1} onClick={() => moveV2ExecutionSection(section.section_id, 1)} aria-label="下移公开 Section" /></Tooltip>
                            </Space>
                          </div>;
                        })}
                      </div>
                    </Checkbox.Group>
                    <Input.TextArea rows={2} value={v2ExecutionEdit.execution_note || ""} onChange={(event) => setV2ExecutionEdit((current) => ({ ...current, execution_note: event.target.value }))} placeholder="执行备注" />

                    <Divider orientation="left">内部待确认清单</Divider>
                    <div className="v2-strategy-list">{v2ExecutionOutput.internal_checklist.map((item, index) => <div className="v2-strategy-list-row" key={`${item.code}-${index}`}><Tag color="gold">{item.code}</Tag><Text type="secondary">{typeof item.detail === "string" ? item.detail : JSON.stringify(item.detail)}</Text></div>)}</div>
                    <Descriptions size="small" column={{ xs: 1, md: 3 }}>
                      <Descriptions.Item label="固定 Baseline">{v2ExecutionOutput.baseline.baseline_run_ids?.length || 0} 个有效 Run</Descriptions.Item>
                      <Descriptions.Item label="计划/有效/失败">{v2ExecutionOutput.baseline.run_manifest?.planned_count || 0} / {v2ExecutionOutput.baseline.run_manifest?.valid_count || 0} / {v2ExecutionOutput.baseline.run_manifest?.failed_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="测量状态">仅冻结输入，尚未比较</Descriptions.Item>
                    </Descriptions>
                    <Space wrap>{(v2ExecutionOutput.baseline.collector_capability_snapshot?.warnings || []).map((code: string) => <Tag color="gold" key={code}>{code}</Tag>)}</Space>

                    {v2ExecutionOutput.validation.errors.length > 0 && <Alert type="warning" showIcon message="方案尚不能确认" description={v2ExecutionOutput.validation.errors.map(v2ExecutionValidationLabel).join("；")} />}
                    {v2Execution.allowed_operations.includes("REVISE") && <Row gutter={[12, 12]} align="middle">
                      <Col xs={24} md={8}><Input value={v2ExecutionEditor} onChange={(event) => setV2ExecutionEditor(event.target.value)} placeholder="执行人/确认人" /></Col>
                      <Col xs={24} md={16}><Space wrap><Button icon={<ListChecks size={15} />} loading={v2ExecutionLoading} onClick={saveV2ExecutionRevision}>保存并重新校验</Button>{v2Execution.allowed_operations.includes("CONFIRM") && <Popconfirm title="确认当前执行方案？" description="确认后仍需人工发布并单独登记。" okText="确认" cancelText="取消" onConfirm={confirmV2ExecutionProposal}><Button type="primary" icon={<ShieldCheck size={15} />} loading={v2ExecutionLoading}>确认执行方案</Button></Popconfirm>}</Space></Col>
                    </Row>}
                    {v2ExecutionConfirmation && <Alert type="success" showIcon message="执行方案已确认，尚未报告发布" description={`Confirmation ${v2ExecutionConfirmation.confirmation_id} · ${formatDateTime(v2ExecutionConfirmation.created_at)}`} />}

                    {v2ExecutionConfirmation && <>
                      <Divider orientation="left">登记实际发布</Divider>
                      <Row gutter={[12, 12]}>
                        <Col xs={24} md={8}><Input value={v2Publication.actual_channel || ""} onChange={(event) => setV2Publication((current) => ({ ...current, actual_channel: event.target.value }))} placeholder="实际渠道" /></Col>
                        <Col xs={24} md={8}><Input value={v2Publication.actual_account || ""} onChange={(event) => setV2Publication((current) => ({ ...current, actual_account: event.target.value }))} placeholder="实际账号" /></Col>
                        <Col xs={24} md={8}><Input value={v2Publication.actual_location || ""} onChange={(event) => setV2Publication((current) => ({ ...current, actual_location: event.target.value }))} placeholder="实际栏目/位置" /></Col>
                        <Col xs={24} md={12}><Input value={v2Publication.actual_url || ""} onChange={(event) => setV2Publication((current) => ({ ...current, actual_url: event.target.value }))} placeholder="实际发布 URL" /></Col>
                        <Col xs={24} md={12}><Input value={v2Publication.published_at || ""} onChange={(event) => setV2Publication((current) => ({ ...current, published_at: event.target.value }))} placeholder="实际发布时间，例如 2026-09-11T12:00:00+08:00" /></Col>
                        <Col xs={24}><Checkbox checked={v2Publication.actual_content_version === v2ExecutionConfirmation.result_version} onChange={(event) => setV2Publication((current) => ({ ...current, actual_content_version: event.target.checked ? v2ExecutionConfirmation.result_version : "" }))}>实际采用该确认版本的内容骨架</Checkbox></Col>
                        <Col xs={24}><Input.TextArea rows={2} value={v2Publication.differences || ""} onChange={(event) => setV2Publication((current) => ({ ...current, differences: event.target.value }))} placeholder="与确认方案的差异；材料不足时将标记为无法判断" /></Col>
                      </Row>
                      <Button type="primary" icon={<ExternalLink size={15} />} loading={v2ExecutionLoading} onClick={recordV2Publication}>{v2ExecutionCurrentPublications.length ? "修订人工发布报告" : "登记人工发布报告"}</Button>
                    </>}

                    {v2Execution.publications.length > 0 && <>
                      <Divider orientation="left">发布记录</Divider>
                      <Table rowKey="publication_id" size="small" pagination={false} dataSource={v2Execution.publications} columns={[
                        { title: "状态", dataIndex: "publication_status", render: () => <Tag color="blue">用户报告</Tag> },
                        { title: "符合性", dataIndex: "conformance", render: (value: string) => <Tag color={value === "MATCHED" ? "green" : value === "OUTSIDE_CONFIRMED_SCOPE" ? "red" : "gold"}>{v2ConformanceLabel(value)}</Tag> },
                        { title: "实际 URL", render: (_: unknown, row: any) => <Link href={row.report.actual_url} target="_blank">{row.report.actual_url}</Link> },
                        { title: "记录时间", dataIndex: "created_at", render: formatDateTime },
                      ]} />
                      <Alert type="info" showIcon message="发布记录为人工报告" description="系统未抓取或验证线上页面；方案符合性与发布是否真实发生分别展示。" />
                    </>}

                    <Collapse ghost items={[{ key: "execution-audit", label: "查看执行输入与版本审计", children: <Descriptions size="small" column={1}>
                      <Descriptions.Item label="策略结果"><Text code>{v2Execution.proposal.strategy_result_version}</Text></Descriptions.Item>
                      <Descriptions.Item label="策略审核"><Text code>{v2Execution.proposal.strategy_review_id}</Text></Descriptions.Item>
                      <Descriptions.Item label="执行输入 SHA-256"><Text code copyable>{v2Execution.proposal.input_snapshot_hash}</Text></Descriptions.Item>
                      <Descriptions.Item label="Baseline Raw Result"><Text code>{v2ExecutionOutput.baseline.raw_result_version}</Text></Descriptions.Item>
                    </Descriptions> }]} />
                  </Space> : <Empty description="执行方案结果不可用" />}
                </Card>

                <Card id="v2-retest" size="small" title={<Space><BarChart3 size={18} />固定复测与前后变化</Space>} extra={v2Retest && <Tooltip title="只读取复测状态，不触发采样或计算"><Button icon={<RefreshCw size={15} />} loading={v2RetestLoading} onClick={refreshV2Retest} aria-label="刷新复测状态" /></Tooltip>}>
                  {!v2Retest ? <Space direction="vertical" size={14} style={{ width: "100%" }}>
                    {v2RetestPublicationOptions.length === 0 ? <Alert
                      type="info"
                      showIcon
                      message="尚不能创建发布后复测"
                      description={v2RetestReadiness?.blocker?.detail || "需要已确认的执行方案和一条明确的人工发布记录；查看本页不会自动补齐这些对象。"}
                    /> : <>
                      <Alert type="info" showIcon message="先选择精确发布记录" description="历史发布记录也可复测；系统不会自动采用 latest，也不会把用户报告升级为系统验证。" />
                      <Select
                        style={{ width: "100%" }}
                        placeholder="选择要观察的发布记录"
                        value={v2RetestPublicationId || undefined}
                        options={v2RetestPublicationOptions}
                        onChange={(value) => {
                          setV2RetestPublicationId(value);
                          setV2RetestReadiness(null);
                          void refreshV2RetestReadiness(value);
                        }}
                      />
                    </>}
                    {v2RetestReadiness?.sampling_eligible && <>
                      <Descriptions size="small" column={{ xs: 1, md: 3 }}>
                        <Descriptions.Item label="固定 Baseline">{v2RetestReadiness.baseline?.baseline_run_ids?.length || 0} 个有效 Run</Descriptions.Item>
                        <Descriptions.Item label="发布状态"><Tag color="blue">用户报告</Tag></Descriptions.Item>
                        <Descriptions.Item label="发布时间校验">{v2RetestReadiness.publication?.published_at_parse_status === "TIMEZONE_AWARE" ? "已记录时区" : "顺序待核实"}</Descriptions.Item>
                      </Descriptions>
                      <Divider orientation="left">冻结本次测量身份</Divider>
                      <Row gutter={[12, 12]}>
                        <Col xs={24} md={8}><Text type="secondary">目标品牌</Text><Input style={{ marginTop: 5 }} value={v2MeasurementIdentity.canonical_brand_name} onChange={(event) => setV2MeasurementIdentity((current) => ({ ...current, canonical_brand_name: event.target.value }))} /></Col>
                        <Col xs={24} md={8}><Text type="secondary">确认人</Text><Input style={{ marginTop: 5 }} value={v2MeasurementIdentity.confirmed_by} onChange={(event) => setV2MeasurementIdentity((current) => ({ ...current, confirmed_by: event.target.value }))} placeholder="确认别名和官方身份时填写" /></Col>
                        <Col xs={24} md={8}><Text type="secondary">计划采样</Text><InputNumber style={{ width: "100%", marginTop: 5 }} min={1} max={10} value={v2RetestSampleCount} onChange={(value) => setV2RetestSampleCount(Number(value || 1))} /></Col>
                        <Col xs={24} md={8}><Text type="secondary">可接受品牌别名</Text><Input.TextArea rows={2} style={{ marginTop: 5 }} value={v2MeasurementIdentity.accepted_aliases} onChange={(event) => setV2MeasurementIdentity((current) => ({ ...current, accepted_aliases: event.target.value }))} placeholder="逗号或换行分隔" /></Col>
                        <Col xs={24} md={8}><Text type="secondary">官方域名</Text><Input.TextArea rows={2} style={{ marginTop: 5 }} value={v2MeasurementIdentity.official_domains} onChange={(event) => setV2MeasurementIdentity((current) => ({ ...current, official_domains: event.target.value }))} placeholder="未确认时留空，指标将不可计算" /></Col>
                        <Col xs={24} md={8}><Text type="secondary">官方精确 URL</Text><Input.TextArea rows={2} style={{ marginTop: 5 }} value={v2MeasurementIdentity.official_urls} onChange={(event) => setV2MeasurementIdentity((current) => ({ ...current, official_urls: event.target.value }))} placeholder="未确认时留空" /></Col>
                      </Row>
                      <Button type="primary" icon={<ListChecks size={15} />} loading={v2RetestLoading} onClick={createV2RetestPlan}>冻结复测计划</Button>
                    </>}
                  </Space> : <Space direction="vertical" size={14} style={{ width: "100%" }}>
                    <Descriptions size="small" column={{ xs: 1, md: 3 }}>
                      <Descriptions.Item label="复测 ID"><Text code copyable>{v2Retest.retest.retest_id}</Text></Descriptions.Item>
                      <Descriptions.Item label="状态"><Tag color={["COMPARISON_READY", "READY_FOR_COMPARISON"].includes(v2Retest.retest.status) ? "green" : ["SAMPLING", "SEMANTIC_MEASURING"].includes(v2Retest.retest.status) ? "blue" : "gold"}>{v2Retest.retest.status}</Tag></Descriptions.Item>
                      <Descriptions.Item label="复测 Analysis"><Text code>{v2Retest.retest.retest_analysis_id}</Text></Descriptions.Item>
                      <Descriptions.Item label="固定 Baseline">{v2Retest.baseline.baseline_run_ids?.length || 0} 个有效 Run</Descriptions.Item>
                      <Descriptions.Item label="计划/终态/有效">{v2Retest.sampling.sampling.planned_run_count} / {v2Retest.sampling.sampling.terminal_run_count} / {v2Retest.sampling.sampling.valid_run_count}</Descriptions.Item>
                      <Descriptions.Item label="外部语义调用">{v2Retest.boundary.external_llm_calls || 0}</Descriptions.Item>
                    </Descriptions>
                    <Alert type="info" showIcon message="只报告观察变化" description="人工发布记录未经过系统抓取验证；本报告不会输出渠道有效、策略成功或因果提升结论。" />
                    {v2Retest.blocker && <Alert type="warning" showIcon message={v2Retest.blocker.code} description={v2Retest.blocker.detail} />}
                    <Space wrap>
                      {v2Retest.allowed_actions.includes("START_RETEST_SAMPLING") && <Popconfirm title="启动真实复测采样？" description="这会按冻结 Prompt 和计划执行外部浏览器采样，不会扩大样本数。" okText="启动" cancelText="取消" onConfirm={() => runV2RetestAction("START")}><Button type="primary" icon={<Play size={15} />} loading={v2RetestLoading}>启动复测采样</Button></Popconfirm>}
                      {v2Retest.allowed_actions.includes("RETRY_RETEST_SAMPLING") && <Button danger loading={v2RetestLoading} onClick={() => runV2RetestAction("RETRY")}>重试失败样本</Button>}
                      {v2Retest.allowed_actions.includes("FINALIZE_RETEST_WITH_FAILURES") && <Popconfirm title="保留已记录失败并冻结结果？" okText="冻结" cancelText="取消" onConfirm={() => runV2RetestAction("FINALIZE")}><Button loading={v2RetestLoading}>带失败冻结</Button></Popconfirm>}
                      {v2Retest.allowed_actions.includes("START_SEMANTIC_MEASUREMENT") && <Button loading={v2RetestLoading} onClick={() => runV2RetestAction("CACHE_ONLY")}>仅用兼容缓存识别推荐</Button>}
                      {v2Retest.allowed_actions.includes("START_SEMANTIC_MEASUREMENT") && <Popconfirm title="授权本次 DeepSeek 推荐语义判断？" description="只发送本次冻结回答；这是与浏览器采样分开的外部调用授权。" okText="授权并执行" cancelText="取消" onConfirm={() => runV2RetestAction("EXTERNAL_LLM")}><Button loading={v2RetestLoading}>授权语义测量</Button></Popconfirm>}
                      {v2Retest.allowed_actions.includes("CREATE_COMPARISON") && <Button type="primary" icon={<BarChart3 size={15} />} loading={v2RetestLoading} onClick={() => runV2RetestAction("COMPARE")}>生成描述性比较</Button>}
                    </Space>
                    {v2Retest.comparison_result && <>
                      <Divider orientation="left">前后指标</Divider>
                      <Table rowKey="metricKey" size="small" pagination={false} dataSource={v2ComparisonRows} scroll={{ x: 780 }} columns={[
                        { title: "指标", dataIndex: "metricKey", render: v2MetricLabel },
                        { title: "Baseline", dataIndex: "baseline", render: (value: any) => v2MetricValue(value) },
                        { title: "复测", dataIndex: "retest", render: (value: any) => v2MetricValue(value) },
                        { title: "观察差值", render: (_: unknown, row: any) => row.comparison.delta_percentage_points === null ? "不可比较" : `${row.comparison.delta_percentage_points > 0 ? "+" : ""}${row.comparison.delta_percentage_points.toFixed(1)} 个百分点` },
                        { title: "可比性", render: (_: unknown, row: any) => <Tag color={row.comparison.comparison_eligible ? "green" : "gold"}>{row.comparison.comparison_mode}</Tag> },
                      ]} />
                      <Space wrap>{(v2Retest.comparison_result.comparison.limitations || []).map((item: any, index: number) => <Tag color="gold" key={`${item.code || "LIMITATION"}-${index}`}>{item.code || "LIMITATION"}</Tag>)}</Space>
                    </>}
                    <Collapse ghost items={[{ key: "retest-audit", label: "查看复测输入、授权与版本审计", children: <Descriptions size="small" column={1}>
                      <Descriptions.Item label="Publication"><Text code>{v2Retest.retest.publication_id}</Text></Descriptions.Item>
                      <Descriptions.Item label="Confirmation"><Text code>{v2Retest.retest.confirmation_id}</Text></Descriptions.Item>
                      <Descriptions.Item label="复测计划 SHA-256"><Text code copyable>{v2Retest.retest.retest_plan_hash}</Text></Descriptions.Item>
                      <Descriptions.Item label="测量身份 SHA-256"><Text code copyable>{v2Retest.retest.measurement_identity_hash}</Text></Descriptions.Item>
                      <Descriptions.Item label="测量契约 SHA-256"><Text code copyable>{v2Retest.retest.measurement_contract_hash}</Text></Descriptions.Item>
                    </Descriptions> }]} />
                  </Space>}
                </Card>
                </>}
              </>}
            </>}
          </>}
        </Space> : !dashboard ? <Card loading={loading}><Empty description="正在加载项目数据" /></Card> : page === "validation" ? <Space direction="vertical" size={16} className="page-stack">
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
            {workflowLoading && !currentWorkflowData
              ? <Tag color="blue">正在加载当前 Prompt 工作流</Tag>
              : currentWorkflowData ? (currentWorkflowData.shelved
              ? <Tag color="volcano">已人工搁置</Tag>
              : currentWorkflowData.ready_to_continue
                ? <Tag color="green">答案识别已完成</Tag>
                : answerStepBlocked
                  ? <Tag color="gold">答案识别需修正</Tag>
                : <Button type="primary" size="small" danger onClick={()=>setWorkflowReviewOpen(true)}>开始审核（{currentWorkflowData.pending_review_steps} 步待处理）</Button>)
              : <Tag color="blue">等待当前 Prompt 状态</Tag>}
          </Space>}>
            {workflowLoading && !currentWorkflowData ? <Alert
              type="info"
              showIcon
              message="正在读取当前 Prompt 工作流状态"
              description="正在同步答案识别、证据审核、缺口和策略状态；加载完成前不展示旧 Prompt 或空状态，避免误判为只完成采集。"
            /> : <div className="single-prompt-flow">
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
                    loading={workflowStepButtonLoading(step.key)}
                    onClick={step.onAction}
                  >
                    {step.actionLabel}
                  </Button>}
                </div>;
              })}
            </div>}
            <Space wrap style={{ marginTop: 12 }}>
              <Tag color={mainChainStatusTagColor}>{mainChainStatusTagLabel}</Tag>
              {citationDetailBlockingError && <Tag color="red">引用链路异常</Tag>}
              {citationDetailNonBlockingError && <Tag color="gold">完整引用详情未加载</Tag>}
              <Button size="small" icon={<RefreshCw size={14} />} loading={citationDecisionLoading} disabled={!answerStepDone} onClick={() => refreshCurrentMainChainDisplay(citationTargetPromptId, false)}>刷新主链路</Button>
              <Button size="small" icon={<RefreshCw size={14} />} loading={workflowMaterializationLoading} disabled={!answerStepDone} onClick={() => refreshWorkflowMaterializationPlan(currentWorkflowData?.prompt_id || activePromptId)}>
                {workflowMaterializationPlan ? "刷新物化进度" : "查看物化进度"}
              </Button>
              <Button
                size="small"
                type="primary"
                disabled={currentAnalysisRunning || (!currentCitationCanConfirm && !currentStrategyCandidateCount && !currentNeedsCurrentAnalysis && !currentAnalysisFailed)}
                loading={workflowActionLoadingKey === "strategy" || workflowActionLoadingKey === "analysis"}
                onClick={currentStrategyCandidateCount ? openStrategyConfirmationPage : currentAnalysisFailed || currentNeedsCurrentAnalysis ? runCurrentWorkflowAnalysis : confirmCitationDecisionV1}
              >
                {currentConfirmedStrategyCount ? "查看已确认策略" : currentPendingStrategyCount ? "审核策略候选" : currentCitationCanConfirm ? "生成策略候选" : currentAnalysisRunning ? "主链运行中" : currentAnalysisFailed ? "重新生成 V1.1 输入" : currentNeedsCurrentAnalysis ? "生成 V1.1 输入" : "等待策略确认"}
              </Button>
              <Button size="small" onClick={openStrategyConfirmationPage}>{citationProductTruthBlockedRows.length ? "补目标品牌事实" : "策略确认详情"}</Button>
              {citationProductTruthBlockedRows.length > 0 && <Text type="secondary">这里确认的是{project?.brand_name || "目标品牌"}自己的能力，不是竞品或对标文章的能力。</Text>}
              {legacyContinueResult && <Tag color="default">存在历史缺口/动作结果，不计入当前引用决策进度</Tag>}
            </Space>
            {(workflowMaterializationPlan || workflowMaterializationLoading) && <div className="materialization-progress-panel">
              <Space wrap style={{ width: "100%", justifyContent: "space-between" }}>
                <Space wrap>
                  <Text strong>V1.1 物化进度</Text>
                  {workflowMaterializationLoading && <Tag color="processing">Planner 更新中</Tag>}
                  {workflowMaterializationPlan && <Tag color={materializationFailedFinal ? "red" : materializationRemaining ? "gold" : "green"}>
                    {materializationFailedFinal ? "存在最终失败" : materializationRemaining ? "可继续处理" : "已完成"}
                  </Tag>}
                  <Tag color="default">只读 Planner</Tag>
                  <Button size="small" loading={workflowMaterializationLoading} onClick={() => refreshWorkflowMaterializationPlan(currentWorkflowData?.prompt_id || activePromptId)}>刷新物化进度</Button>
                </Space>
                <Text type="secondary">恢复执行只补 Missing / Failed / Stale，DONE ledger 不重算。</Text>
              </Space>
              {workflowMaterializationPlan && <Row gutter={[12, 10]} style={{ marginTop: 8 }}>
                <Col xs={24} lg={12}>
                  <Space direction="vertical" size={4} style={{ width: "100%" }}>
                    <Space wrap>
                      <Text strong>SourceClaim</Text>
                      <Tag>Required {sourceClaimMat.required}</Tag>
                      <Tag color="green">Ledger HIT {sourceClaimMat.ledgerHit}</Tag>
                      <Tag color="blue">Legacy {sourceClaimMat.legacy}</Tag>
                      <Tag color={sourceClaimMat.external ? "gold" : "green"}>预计新增 LLM {sourceClaimMat.external}</Tag>
                    </Space>
                    <Progress percent={Math.min(100, sourceClaimMat.progress)} size="small" status={sourceClaimMat.failedFinal ? "exception" : sourceClaimMat.conservationOk ? "normal" : "exception"} />
                    <Text type="secondary">Missing {sourceClaimMat.missing} · LLMCallCache {sourceClaimMat.llmCache} · Retrying {sourceClaimMat.inProgress} · Failed {sourceClaimMat.failedRetryable}/{sourceClaimMat.failedFinal}</Text>
                  </Space>
                </Col>
                <Col xs={24} lg={12}>
                  <Space direction="vertical" size={4} style={{ width: "100%" }}>
                    <Space wrap>
                      <Text strong>EvidenceAlignment</Text>
                      <Tag>Required {alignmentMat.required}</Tag>
                      <Tag color="green">Ledger HIT {alignmentMat.ledgerHit}</Tag>
                      <Tag color="blue">Legacy {alignmentMat.legacy}</Tag>
                      <Tag color={alignmentMat.external ? "gold" : "green"}>预计新增 LLM {alignmentMat.external}</Tag>
                    </Space>
                    <Progress percent={Math.min(100, alignmentMat.progress)} size="small" status={alignmentMat.failedFinal ? "exception" : alignmentMat.conservationOk ? "normal" : "exception"} />
                    <Text type="secondary">Naive {workflowMaterializationPlan.evidence_alignment?.naive_pairs ?? 0} → Candidate {workflowMaterializationPlan.evidence_alignment?.after_recall ?? 0} · Missing {alignmentMat.missing} · Failed {alignmentMat.failedRetryable}/{alignmentMat.failedFinal}</Text>
                  </Space>
                </Col>
              </Row>}
              {workflowMaterializationPlan && <Space wrap style={{ marginTop: 8 }}>
                <Tag color={sourceClaimMat.conservationOk && alignmentMat.conservationOk ? "green" : "red"}>守恒{sourceClaimMat.conservationOk && alignmentMat.conservationOk ? "通过" : "异常"}</Tag>
                <Tag color="default">候选策略 {workflowMaterializationPlan.evidence_alignment?.candidate_builder_shadow?.selected_shadow_policy || workflowMaterializationPlan.evidence_alignment?.candidate_builder_shadow?.selected_shadow_policy_key || "Policy D"}</Tag>
                <Tag color="default">全库 fallback：{workflowMaterializationPlan.evidence_alignment?.candidate_builder_shadow?.c2b_cutover_gate?.no_full_library_fallback === false ? "需检查" : "未启用"}</Tag>
              </Space>}
            </div>}
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
              <Tag color={mainChainStatusTagColor}>{mainChainStatusTagLabel}</Tag>
              {citationDetailNonBlockingError && <Tag color="gold">完整引用详情未加载</Tag>}
              {citationDetailBlockingError && <Tag color="red">引用链路异常</Tag>}
              <Button size="small" icon={<RefreshCw size={14} />} loading={citationDecisionLoading} disabled={!answerStepDone} onClick={() => refreshCurrentMainChainDisplay(citationTargetPromptId, false)}>刷新主链路</Button>
              <Button size="small" icon={<RefreshCw size={14} />} loading={workflowMaterializationLoading} disabled={!answerStepDone} onClick={() => refreshWorkflowMaterializationPlan(currentWorkflowData?.prompt_id || activePromptId)}>
                {workflowMaterializationPlan ? "刷新物化进度" : "查看物化进度"}
              </Button>
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
                  <Button size="small" icon={<RefreshCw size={14} />} loading={citationDecisionLoading} disabled={!answerStepDone} onClick={() => refreshCurrentMainChainDisplay(citationTargetPromptId, false)}>刷新主链路</Button>
                  <Button size="small" icon={<RefreshCw size={14} />} loading={workflowMaterializationLoading} disabled={!answerStepDone} onClick={() => refreshWorkflowMaterializationPlan(currentWorkflowData?.prompt_id || activePromptId)}>
                    {workflowMaterializationPlan ? "刷新物化进度" : "查看物化进度"}
                  </Button>
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
                const useSynthesisDecisionView = hasSynthesisDecisionView(c);
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
                {useSynthesisDecisionView && <StrategySynthesisDecisionView candidate={c} />}
                {!useSynthesisDecisionView && strategyView.strategyBasis === "ANSWER_DECISION_EVIDENCE_GAP" && <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 12 }}
                  message={<Space wrap>
                    <Text strong>策略依据：答案决策理由证据缺口</Text>
                    <Tag>对标来源：无</Tag>
                    <Tag color="blue">答案决策理由：有</Tag>
                    <Tag color={strategyView.productTruthRefs?.status === "TRUE" ? "green" : "orange"}>
                      目标品牌事实：{strategyView.productTruthRefs?.status === "TRUE" ? "已确认" : "待确认"}
                    </Tag>
                    <Tag color="orange">合格支撑证据：无</Tag>
                  </Space>}
                  description={`当前 ${strategyView.decisionReasonIds.length} 个决策理由没有形成满足 Phase 2A lineage 的合格支撑证据；该候选不计入 Benchmark，也不代表已选定第 8 步的具体渠道或资产。`}
                />}
                {!useSynthesisDecisionView && strategyView.decisionSpace && <Alert
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
                  {!useSynthesisDecisionView && <>
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
                              key={`${item.capability_label || "signal"}-${index}`}
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
                  </>}
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
      title="第 8 步：执行方案审核"
      open={step8ModalOpen}
      onCancel={() => {
        if (step8Submitting) return;
        setStep8ModalOpen(false);
        setStep8Candidate(null);
        setStep8ProposalData(null);
        setStep8ProposalEdits({});
        setStep8ValidationResult(null);
      }}
      footer={null}
      width={1080}
      destroyOnHidden
      maskClosable={!step8Submitting}
      closable={!step8Submitting}
    >
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          message={`Strategy Candidate #${step8Candidate?.id || "-"} 已确认，执行方案待选择/确认`}
          description="本页只审核 PR5-A 已生成的合法执行建议。策略事实、渠道 Role、Reason Scope、Baseline 和指标均为只读；本轮不会创建 Action 或 Experiment。"
        />
        {step8AssetsLoading && <div style={{ padding: 32, textAlign: "center" }}><Progress type="circle" percent={65} size={56} status="active" /></div>}
        {!step8AssetsLoading && !step8ProposalData && <Empty description="执行建议未加载" />}
        {(step8ProposalData?.active_proposals || []).map((proposal: any) => {
          const edit = step8ProposalEdits[proposal.proposal_key] || {};
          const packageKey = edit.selected_asset_package_key;
          const selectedPlan = (proposal.section_plan_candidates || []).find((item: any) => item.asset_package_key === packageKey);
          const eligibleSections = selectedPlan?.section_plan || [];
          const selectedSectionIds: string[] = edit.section_order || [];
          const portfolioDraft = (step8ValidationResult?.proposal_drafts || []).find((item: any) => item.canonical_proposal?.proposal_key === proposal.proposal_key);
          const singleDraft = step8ValidationResult?.single_results?.[proposal.proposal_key];
          const draft = portfolioDraft || singleDraft;
          const allowedClaims = (proposal.claim_usage_policy || []).filter((item: any) => item.policy === "TARGET_ASSERTION_ALLOWED");
          const restrictedClaims = (proposal.claim_usage_policy || []).filter((item: any) => ["TARGET_ASSERTION_FORBIDDEN", "UNKNOWN_MUST_REMAIN_UNKNOWN", "COMPARISON_RESTRICTED"].includes(item.policy));
          const disabled = edit.execute_this_proposal === false;
          const moveSection = (sectionId: string, delta: number) => {
            const current = [...selectedSectionIds];
            const index = current.indexOf(sectionId);
            const target = index + delta;
            if (index < 0 || target < 0 || target >= current.length) return;
            [current[index], current[target]] = [current[target], current[index]];
            updateStep8Edit(proposal.proposal_key, { section_order: current });
          };
          return <Card
            key={proposal.proposal_key}
            size="small"
            title={<Space wrap><Text strong>{proposal.channel_label || proposal.channel}</Text><Tag color={proposal.channel_role === "PRIMARY" ? "green" : "gold"}>{proposal.channel_role}</Tag><Tag>{proposal.proposal_type === "AUTHORITATIVE_ASSET_INTERVENTION" ? "官方权威资产干预" : "渠道验证实验"}</Tag></Space>}
            extra={<Segmented
              value={edit.execute_this_proposal === true ? "EXECUTE" : edit.execute_this_proposal === false ? "DEFER" : ""}
              options={[{ label: "本轮执行", value: "EXECUTE" }, { label: "暂缓", value: "DEFER" }]}
              onChange={(value) => updateStep8Edit(proposal.proposal_key, { execute_this_proposal: value === "EXECUTE" })}
            />}
          >
            <Space direction="vertical" size={14} style={{ width: "100%" }}>
              <Descriptions size="small" column={{ xs: 1, sm: 3 }}>
                <Descriptions.Item label="资产操作">{proposal.asset_operation === "CREATE_NEW" ? "新建资产" : "更新已有资产"}</Descriptions.Item>
                <Descriptions.Item label="方案目标">{(proposal.asset_purpose || proposal.execution_constraint?.asset_purpose) === "AUTHORITATIVE_PRODUCT_TRUTH" ? "权威产品事实承载" : "最小渠道验证"}</Descriptions.Item>
                <Descriptions.Item label="Baseline">{proposal.baseline_ref?.baseline_run_ids?.length || 0} Runs（只读）</Descriptions.Item>
              </Descriptions>

              {proposal.channel_role === "TEST" && <Alert
                type="warning"
                showIcon
                message={proposal.intervention_hypothesis?.pattern || "渠道验证"}
                description={proposal.intervention_hypothesis?.text}
              />}

              <div>
                <Text strong>资产覆盖方案</Text>
                <Radio.Group
                  value={packageKey}
                  disabled={disabled}
                  onChange={(event) => {
                    const nextKey = event.target.value;
                    const nextPlan = (proposal.section_plan_candidates || []).find((item: any) => item.asset_package_key === nextKey);
                    updateStep8Edit(proposal.proposal_key, {
                      selected_asset_package_key: nextKey,
                      section_order: (nextPlan?.section_plan || []).map((item: any) => item.section_id),
                    });
                  }}
                  style={{ display: "grid", gap: 8, marginTop: 8 }}
                >
                  {(proposal.asset_package_candidates || []).map((item: any) => <Radio key={item.package_key} value={item.package_key}>
                    <Text strong>{item.package_scope_mode}</Text>
                    <Text type="secondary"> · Theme {item.theme_titles?.join(" / ") || "-"} · Reason {item.reason_ids?.length || 0} · Product Truth {item.product_truth_labels?.join(" / ") || "-"}</Text>
                    {!!item.excluded_theme_titles?.length && <Text type="secondary"> · 暂不覆盖 {item.excluded_theme_titles.join(" / ")}</Text>}
                  </Radio>)}
                </Radio.Group>
              </div>

              <div>
                <Text strong>资产类型</Text>
                <Radio.Group
                  value={edit.selected_asset_type}
                  disabled={disabled}
                  options={(proposal.asset_type_candidates || []).map((value: string) => ({ label: value, value }))}
                  onChange={(event) => updateStep8Edit(proposal.proposal_key, { selected_asset_type: event.target.value })}
                  style={{ display: "block", marginTop: 8 }}
                />
              </div>

              <div>
                <Text strong>安全标题</Text>
                <Input
                  value={edit.title}
                  disabled={disabled}
                  style={{ marginTop: 8 }}
                  onChange={(event) => updateStep8Edit(proposal.proposal_key, { title: event.target.value })}
                  onBlur={() => void revalidateStep8Proposal(proposal)}
                />
              </div>

              <div>
                <Text strong>内容 Sections</Text>
                {!packageKey && <Alert style={{ marginTop: 8 }} type="warning" message="请先选择资产覆盖方案" />}
                <Space direction="vertical" size={6} style={{ width: "100%", marginTop: 8 }}>
                  {eligibleSections.map((section: any) => {
                    const checked = selectedSectionIds.includes(section.section_id);
                    const selectedIndex = selectedSectionIds.indexOf(section.section_id);
                    return <div key={section.section_id} style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 8, alignItems: "center", padding: "8px 0", borderBottom: "1px solid #f0f0f0" }}>
                      <Checkbox
                        checked={checked}
                        disabled={disabled}
                        onChange={(event) => {
                          const next = event.target.checked
                            ? [...selectedSectionIds, section.section_id]
                            : selectedSectionIds.filter((value) => value !== section.section_id);
                          updateStep8Edit(proposal.proposal_key, { section_order: next });
                        }}
                      >
                        <Text strong>{section.display_title}</Text>
                        <Text type="secondary"> · {section.section_purpose} · {section.section_rationale_code}</Text>
                      </Checkbox>
                      <Space size={4}>
                        <Tooltip title="上移"><Button aria-label="上移 Section" size="small" icon={<ArrowUp size={15} />} disabled={disabled || !checked || selectedIndex <= 0} onClick={() => moveSection(section.section_id, -1)} /></Tooltip>
                        <Tooltip title="下移"><Button aria-label="下移 Section" size="small" icon={<ArrowDown size={15} />} disabled={disabled || !checked || selectedIndex < 0 || selectedIndex >= selectedSectionIds.length - 1} onClick={() => moveSection(section.section_id, 1)} /></Tooltip>
                      </Space>
                    </div>;
                  })}
                </Space>
              </div>

              <Row gutter={12}>
                <Col xs={24} md={8}><Text strong>发布账号</Text><Input disabled={disabled} value={edit.publishing_metadata?.publishing_account} placeholder="发布主体" onChange={(event) => updateStep8Edit(proposal.proposal_key, { publishing_metadata: { ...edit.publishing_metadata, publishing_account: event.target.value } })} /></Col>
                <Col xs={24} md={8}><Text strong>发布位置</Text><Input disabled={disabled} value={edit.publishing_metadata?.publishing_location} placeholder="栏目或目录" onChange={(event) => updateStep8Edit(proposal.proposal_key, { publishing_metadata: { ...edit.publishing_metadata, publishing_location: event.target.value } })} /></Col>
                <Col xs={24} md={8}><Text strong>URL slug</Text><Input disabled={disabled} value={edit.publishing_metadata?.url_slug} placeholder="content-slug" onChange={(event) => updateStep8Edit(proposal.proposal_key, { publishing_metadata: { ...edit.publishing_metadata, url_slug: event.target.value } })} /></Col>
              </Row>

              <div>
                <Text strong>观察窗口</Text>
                <Select
                  value={edit.selected_observation_window_index}
                  disabled={disabled}
                  style={{ width: "100%", marginTop: 8 }}
                  options={(proposal.validation_plan?.observation_window_candidates || []).map((item: any, index: number) => ({
                    value: index,
                    label: `${item.default_sample_count || "-"} 次独立采集 · ${item.collection_mode || "观察计划"}`,
                  }))}
                  onChange={(value) => updateStep8Edit(proposal.proposal_key, { selected_observation_window_index: value })}
                />
              </div>

              <Row gutter={12}>
                <Col xs={24} md={12}>
                  <Text strong>可写入事实</Text>
                  <div style={{ marginTop: 6 }}>{allowedClaims.length ? allowedClaims.map((item: any) => <Tag color="green" key={item.claim_id}>{item.proposition?.object}</Tag>) : <Text type="secondary">无可肯定写入的目标品牌事实</Text>}</div>
                </Col>
                <Col xs={24} md={12}>
                  <Text strong>限制事实</Text>
                  <div style={{ marginTop: 6 }}>{restrictedClaims.map((item: any) => <Tag color="red" key={item.claim_id}>{item.proposition?.object}</Tag>)}</div>
                </Col>
              </Row>

              <div>
                <Text strong>成功指标</Text>
                <div style={{ marginTop: 6 }}>{(proposal.eligible_metrics || []).map((item: any) => <Tag key={item.metric_key} color={item.baseline_status === "NOT_MEASURABLE_YET" ? "default" : "blue"}>{item.metric_key} · {item.measurement_level} · {item.baseline_status}</Tag>)}</div>
              </div>

              {draft && <Alert
                type={draft.draft_status === "VALID" ? "success" : "error"}
                showIcon
                message={draft.proposal_readiness || draft.draft_status}
                description={(draft.edit_errors || []).map((item: any) => `${item.error_code}: ${item.message}${item.offending_phrase ? `（${item.offending_phrase}）` : ""}`).join("；") || "8 个硬校验器均已通过"}
              />}

              <Collapse size="small" items={[{
                key: "audit",
                label: "审计详情",
                children: <Descriptions size="small" column={1}>
                  <Descriptions.Item label="Proposal ID">{proposal.proposal_key}</Descriptions.Item>
                  <Descriptions.Item label="Theme IDs">{proposal.theme_ids?.join(", ") || "-"}</Descriptions.Item>
                  <Descriptions.Item label="Reason IDs">{proposal.reason_ids?.join(", ") || "-"}</Descriptions.Item>
                  <Descriptions.Item label="Product Truth IDs">{proposal.product_truth_ids?.join(", ") || "-"}</Descriptions.Item>
                  <Descriptions.Item label="Channel Signals">{proposal.channel_signal_ids?.join(", ") || "-"}</Descriptions.Item>
                  <Descriptions.Item label="Validators">{draft ? Object.entries(draft.validator_results || {}).map(([key, value]: [string, any]) => <Tag color={value.status === "VALID" ? "green" : "red"} key={key}>{key}: {value.status}</Tag>) : "待重校验"}</Descriptions.Item>
                </Descriptions>,
              }]} />
            </Space>
          </Card>;
        })}

        {step8ValidationResult?.portfolio_readiness && <Alert
          type={step8ValidationResult.ready_for_freeze ? "success" : step8ValidationResult.portfolio_readiness === "HAS_INVALID_EDIT" ? "error" : "warning"}
          showIcon
          message={`Portfolio：${step8ValidationResult.portfolio_readiness}`}
          description={step8ValidationResult.ready_for_freeze ? "已具备进入 PR5-C 冻结的条件；本页仍未写入数据库。" : "请完成必选项或修复卡片中的非法编辑。"}
        />}
        <Divider style={{ margin: 0 }} />
        <Space style={{ justifyContent: "flex-end", width: "100%" }}>
          <Button disabled={step8Submitting} onClick={() => {
            setStep8ModalOpen(false);
            setStep8Candidate(null);
            setStep8ProposalData(null);
            setStep8ProposalEdits({});
            setStep8ValidationResult(null);
          }}>关闭</Button>
          <Button type="primary" icon={<ShieldCheck size={16} />} loading={step8Submitting} disabled={!step8ProposalData} onClick={() => void submitStep8ExecutionPlan()}>重新校验执行方案</Button>
        </Space>
      </Space>
    </Modal>
    <Modal
      title="人工审核工作台"
      open={workflowReviewOpen}
      onCancel={()=>{setWorkflowReviewOpen(false);setReviewQueue(null);setReviewQueueLoading(false);setReviewAnalysisLoading(false);setConfirmingAlignmentGroupKeys(new Set());setCompetitorCandidates([]);}}
      footer={null}
      width={820}
    >
      <Space direction="vertical" size={12} style={{width:"100%"}}>
        {reviewQueue?.status !== "NOT_ANALYZED" && <Alert type="info" showIcon message="机器分析已完成，请按顺序人工确认：先确认答案中的竞品/候选对象，再校验 AI 说法和证据关系。相同答案只审核一次，确认后自动应用到全部采集样本。" />}
        {!reviewQueue && <Button type="primary" loading={reviewQueueLoading} onClick={async()=>{
          const pid = currentWorkflowData?.prompt_id || activePromptId;
          if (!projectId || !pid) {
            message.warning("请先选择一个具体 Prompt");
            return;
          }
          setReviewQueueLoading(true);
          setConfirmingAlignmentGroupKeys(new Set());
          try{
            const [q, cc] = await Promise.all([
              fetchReviewJson(`/api/optimization/workflow/${projectId}/${pid}/review-queue`, 10000),
              fetchReviewJson(`/api/optimization/workflow/${projectId}/${pid}/competitor-candidates`, 10000),
            ]);
            setReviewQueue(q); setCompetitorCandidates(cc);
            if (q?.status !== "NOT_ANALYZED" && (q?.unique_events || []).length === 0 && (q?.alignments || []).length === 0 && (cc || []).length === 0) {
              await refreshWorkflowStatusForPrompt(pid);
              message.info("当前没有待审核项，主链路状态已刷新");
              setWorkflowReviewOpen(false);
              setReviewQueue(null);
              setCompetitorCandidates([]);
            }
          }catch(e:any){message.error(e.message)}
          finally{setReviewQueueLoading(false)}
        }}>加载待审核项</Button>}
        {reviewQueue?.status==="NOT_ANALYZED" && <Space direction="vertical" size={8} style={{width:"100%"}}>
          <Alert type="warning" showIcon message="该 Prompt 尚未执行机器分析——不是「审核完成」，而是还没有可审核的数据。" />
          <Button type="primary" loading={reviewAnalysisLoading} onClick={async()=>{
            setReviewAnalysisLoading(true);
            try{
              const pid = currentWorkflowData?.prompt_id || activePromptId;
              if (!projectId || !pid) {
                message.warning("请先选择一个具体 Prompt");
                return;
              }
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
            finally{setReviewAnalysisLoading(false)}
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
                try {
                  const response = await fetchReviewAction("/api/optimization/workflow/review/events/confirm-batch",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({event_ids:e.event_ids})});
                  await assertWorkflowResponse(response, "确认 AI 说法失败");
                  message.success("已确认 AI 说法无误");
                  setReviewQueue({...reviewQueue, unique_events: reviewQueue.unique_events.filter((x:any)=>x!==e)});
                  const pid = currentWorkflowData?.prompt_id || citationTargetPromptId;
                  if (pid) void refreshWorkflowStatusForPrompt(pid);
                } catch (error: any) {
                  message.error(error.message || "确认 AI 说法失败，请稍后重试");
                }
              }}>AI 确实这样说了</Button>
              <Button size="small" onClick={async()=>{
                try {
                  const response = await fetchReviewAction("/api/optimization/workflow/review/events/reject-batch",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({event_ids:e.event_ids})});
                  await assertWorkflowResponse(response, "标记 AI 说法失败");
                  message.success("已标记错误");
                  setReviewQueue({...reviewQueue, unique_events: reviewQueue.unique_events.filter((x:any)=>x!==e)});
                  const pid = currentWorkflowData?.prompt_id || citationTargetPromptId;
                  if (pid) void refreshWorkflowStatusForPrompt(pid);
                } catch (error: any) {
                  message.error(error.message || "标记 AI 说法失败，请稍后重试");
                }
              }}>判断有误</Button>
            </Space>
          </Card>)}
          {/* Evidence 对齐审核：同一语义证据组只展示一张卡，底层 Run-level Alignment 仍逐条保留。 */}
          {reviewQueue.alignments.map((a:any, idx:number)=>{
            const alignmentIds = a.alignment_ids || [a.alignment_id];
            const alignmentGroupKey = a.review_group_key || alignmentIds.join(",");
            const confirmingGroup = confirmingAlignmentGroupKeys.has(alignmentGroupKey);
            const sourceClaimCount = (a.source_claim_ids || []).length || (a.source_claim_id ? 1 : 0);
            return <Card key={`al-${alignmentGroupKey}`} size="small" title={<Space wrap><Tag color="purple">证据语义关系校验 {idx+1}/{reviewQueue.alignments.length}</Tag><Tag>{a.alignment_count || alignmentIds.length} 条同组证据</Tag><Tag>{sourceClaimCount} 条同义来源主张</Tag><Tag>{a.run_count || (a.run_ids || []).length} 个 Runs</Tag></Space>}>
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
              <Button size="small" type="primary" loading={confirmingGroup} disabled={confirmingGroup} onClick={async()=>{
                if (confirmingGroup) return;
                setConfirmingAlignmentGroupKeys((prev) => new Set(prev).add(alignmentGroupKey));
                try {
                  const response = await fetchReviewAction("/api/optimization/workflow/review/alignments/confirm-batch",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({alignment_ids:alignmentIds,relation:"SUPPORTS"})});
                  await assertWorkflowResponse(response, "确认这一组支持证据失败");
                  message.success(`已确认这一组 ${alignmentIds.length} 条支持证据`);
                  const pid = currentWorkflowData?.prompt_id || citationTargetPromptId;
                  setReviewQueue((prevQueue:any) => prevQueue ? {
                    ...prevQueue,
                    alignments: (prevQueue.alignments || []).filter((row:any) => row.review_group_key !== alignmentGroupKey),
                  } : prevQueue);
                  if (pid) void refreshWorkflowStatusForPrompt(pid);
                } catch (error: any) {
                  message.error(error.message || "确认这一组支持证据失败，请稍后重试");
                } finally {
                  setConfirmingAlignmentGroupKeys((prev) => {
                    const next = new Set(prev);
                    next.delete(alignmentGroupKey);
                    return next;
                  });
                }
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
