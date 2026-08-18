from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import re
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    AnswerClaim,
    AnswerSemanticFact,
    BrandCapabilityClaim,
    BrowserMonitorRun,
    Competitor,
    DecisionEvidenceAdoption,
    DecisionGapDiagnosis,
    DecisionSelectionCriterion,
    OptimizationAction,
    OptimizationEvidencePackage,
    OptimizationExperiment,
    OptimizationIssue,
    OptimizationIssueRun,
    OptimizationStrategyCandidate,
    PassageAlignment,
    Project,
    Prompt,
    RecommendationClaim,
    RecommendationEvidenceLink,
    RecommendationEntity,
    RecommendationIntelligenceSnapshot,
    RecommendationReasonClaim,
    ReferenceSource,
    RetrievalCandidate,
    SourceDocument,
    TargetBrandCapabilityTruth,
)
from app.modules.optimization.service import strategy_candidate_to_read
from app.services.serialization import dumps, loads


RECOMMENDATION_SCHEMA_VERSION = "recommendation_schema.v1"
ENTITY_RESOLVER_VERSION = "entity_resolver.v1_rule_alias"
RECOMMENDATION_EXTRACTOR_VERSION = "recommendation_extractor.v1_rule_zh"
DECISION_MARKET_SCHEMA_VERSION = "decision_market_schema.v2_choice_gate"
PROMPT_RUN_ELIGIBILITY_VERSION = "prompt_run_eligibility.v1_single_prompt"
PROMPT_DECISION_SPACE_VERSION = "prompt_decision_space.v1_single_prompt"
PROMPT_DRIVER_AGGREGATION_VERSION = "prompt_driver_aggregation.v1"
PROMPT_SOURCE_PATTERN_VERSION = "prompt_source_pattern.v1"
PROMPT_INTERVENTION_CANDIDATE_VERSION = "prompt_intervention_candidate.v1"
ANSWER_SEMANTIC_FACT_EXTRACTOR_VERSION = "answer_semantic_fact.v1_rule_zh"
RECOMMENDATION_REASON_EXTRACTOR_VERSION = "recommendation_reason.v1_rule_zh"
SELECTION_CRITERION_EXTRACTOR_VERSION = "selection_criterion.v1_rule_zh"
BRAND_CAPABILITY_EXTRACTOR_VERSION = "brand_capability.v1_rule_zh"
EVIDENCE_ADOPTION_ATTRIBUTION_VERSION = "evidence_adoption.v1_rule_zh"
GAP_DIAGNOSIS_RULE_VERSION = "gap_diagnosis.v2_choice_gate"

VALID_RUN_STATUSES = {"success", "partial_success"}

DECISION_MODE_LABELS = {
    "PRODUCT_SELECTION": "产品选型",
    "COMPARISON": "对比选择",
    "HOW_TO": "操作方法",
    "TROUBLESHOOTING": "故障排查",
    "INFORMATIONAL": "信息了解",
    "NAVIGATIONAL": "导航查找",
    "MIXED": "混合意图",
}

RECOMMENDATION_TYPE_LABELS = {
    "MENTION_ONLY": "仅提及",
    "CANDIDATE": "候选方案",
    "POSITIVE_RECOMMENDATION": "明确推荐",
    "TOP_RECOMMENDATION": "第一推荐",
    "NEGATIVE_RECOMMENDATION": "负面推荐",
}

CONDITION_TYPE_LABELS = {
    "BUDGET": "预算",
    "SKILL_LEVEL": "使用门槛",
    "USE_CASE": "使用场景",
    "FEATURE_REQUIREMENT": "功能要求",
    "SCALE": "规模",
    "PLATFORM": "平台",
    "SECURITY": "安全",
    "ENTERPRISE_NEED": "企业需求",
    "OTHER": "其他条件",
}

OPPORTUNITY_SIGNAL_RULES = [
    ("COMPLIANCE_TOOL_NEED", "合规工具需求", ["合规工具", "第三方工具", "正规", "官方", "白名单", "安全链接", "无风险"]),
    ("PRODUCTION_WORKFLOW", "制作流程需求", ["制作", "生成", "后台", "设置", "上传", "封面图", "主标题", "副标题"]),
    ("PRIVATE_TRAFFIC", "私域引流场景", ["私域", "引流", "微信", "公众号", "企业微信", "粉丝群", "私信"]),
    ("CONVERSION_VALUE", "转化价值", ["转化", "添加率", "留资", "成交", "点击", "直达", "跳转路径"]),
    ("DATA_OPTIMIZATION", "数据追踪优化", ["追踪", "点击数据", "后台", "数据", "优化", "投放"]),
    ("RISK_AND_BOUNDARY", "风险与边界", ["违规", "风险", "处罚", "诈骗", "不要扫码", "避免违规", "判定违规"]),
]

INTENT_LABELS = {
    "INFORMATIONAL": "信息了解",
    "HOW_TO": "操作方法",
    "SOLUTION_SEEKING": "方案寻找",
    "COMMERCIAL_INVESTIGATION": "商业调研",
    "COMPARISON": "对比选择",
    "BRAND_NAVIGATION": "品牌导航",
    "TRANSACTIONAL": "交易意图",
    "UNKNOWN": "未知",
}

SOLUTION_REQUIRED_LABELS = {
    "NONE": "不需要方案",
    "OPTIONAL": "可选方案",
    "REQUIRED": "需要方案",
    "UNKNOWN": "无法判断",
}

CHOICE_SLOT_LABELS = {
    "NONE": "没有品牌选择空间",
    "LOW": "低品牌机会",
    "MEANINGFUL": "存在品牌选择空间",
    "STRONG": "强品牌决策市场",
    "UNKNOWN": "无法判断",
}

PRODUCT_TRUTH_STATUS_LABELS = {
    "SUPPORTED": "真实支持",
    "PARTIALLY_SUPPORTED": "部分支持",
    "NOT_SUPPORTED": "不支持",
    "UNKNOWN": "未确认",
}

RUN_ELIGIBILITY_LABELS = {
    "ELIGIBLE": "可用于正式分析",
    "PARTIAL": "可用于部分分析",
    "INELIGIBLE": "不可用于正式分析",
    "UNKNOWN": "需要人工确认",
}

DECISION_SPACE_LABELS = {
    "NO_BRAND_DECISION_SPACE": "没有品牌决策空间",
    "SOLUTION_CHOICE_SPACE": "存在方案选择空间",
    "BRAND_CANDIDATE_SPACE": "存在品牌候选空间",
    "BRAND_RECOMMENDATION_PRESENT": "已有品牌推荐",
    "BRAND_COMPARISON_PRESENT": "已有品牌对比",
}

INTERVENTION_TYPE_LABELS = {
    "CONTENT_CREATE": "新建内容",
    "CONTENT_UPDATE": "更新内容",
    "PLATFORM_PUBLISH": "平台发布",
    "TECHNICAL_INDEXABILITY": "技术可索引性",
    "STRUCTURED_DATA": "结构化数据",
    "ENTITY_CONSISTENCY": "实体一致性",
    "INTERNAL_INFORMATION_ARCHITECTURE": "内部信息架构",
    "PLATFORM_AUTHORITY_BUILD": "平台权威建设",
    "RECRAWL_OR_REFRESH": "重抓/刷新",
    "NO_ACTION": "暂不行动",
    "UNRESOLVED": "待人工确认",
}

INTERVENTION_PREREQUISITES = {
    "CONTENT_CREATE": ["已确认 Product Truth", "明确目标问题和目标能力", "可公开访问的发布位置"],
    "CONTENT_UPDATE": ["已确认 Product Truth", "已有人工作为目标资产的页面/内容", "修改前后内容快照"],
    "PLATFORM_PUBLISH": ["已确认 Product Truth", "人工确认目标平台和账号", "平台内容可被公开访问"],
    "TECHNICAL_INDEXABILITY": ["目标 URL 已确认", "canonical/robots/index 状态可检查", "修改前后技术快照"],
    "STRUCTURED_DATA": ["目标 URL 已确认", "结构化数据字段可被页面真实支撑", "发布后可验证"],
    "ENTITY_CONSISTENCY": ["目标品牌实体和别名已确认", "官网/第三方资料口径一致", "不能编造未确认能力"],
    "INTERNAL_INFORMATION_ARCHITECTURE": ["目标内容资产已确认", "内部链接和锚文本可修改", "不改变采集 Prompt"],
    "PLATFORM_AUTHORITY_BUILD": ["目标平台和账号已确认", "发布主体身份可审计", "内容事实可核验"],
    "RECRAWL_OR_REFRESH": ["目标 URL 已确认", "内容已实际发布或更新", "刷新动作和时间可记录"],
    "NO_ACTION": ["当前没有可执行缺口，继续观察或补样本"],
}

EVIDENCE_STATUS_LABELS = {
    "LINKED": "已建立引用关联",
    "PARTIALLY_LINKED": "部分引用关联",
    "UNLINKED": "未找到外显引用关联",
    "UNCERTAIN": "存在引用但关系不确定",
}

SOLUTION_SPECIFICITY_LABELS = {
    "GENERIC_METHOD": "通用方法",
    "CATEGORY": "方案类别",
    "PRODUCT_TYPE": "产品类型",
    "BRAND": "具体品牌",
    "UNKNOWN": "无法判断",
}

CRITERION_RULES = [
    ("COMPLIANCE", "合规", ["合规", "正规", "白名单", "规则", "平台规范", "审核"]),
    ("STABILITY", "稳定性", ["稳定", "长期", "失效", "打不开", "拦截", "风控"]),
    ("EASE_OF_USE", "操作简单", ["简单", "方便", "快速", "一键", "步骤", "教程", "新手"]),
    ("PLATFORM_SUPPORT", "平台支持", ["抖音", "微信", "企业微信", "公众号", "私信", "直播间"]),
    ("WECHAT_COMPATIBILITY", "微信兼容", ["微信", "企业微信", "加好友", "客服", "二维码"]),
    ("CUSTOMIZATION", "可修改", ["可修改", "自定义", "封面", "标题", "样式", "落地页"]),
    ("DATA_TRACKING", "数据统计", ["数据", "统计", "追踪", "点击", "回传", "转化"]),
    ("SAFETY", "安全", ["安全", "风险", "违规", "诈骗", "处罚", "规避"]),
    ("PRICE", "价格", ["价格", "费用", "免费", "成本", "套餐"]),
    ("BRAND_TRUST", "品牌可信度", ["官方", "可信", "资质", "备案", "口碑"]),
]

NEED_RULES = [
    ("抖音跳转微信", ["抖音", "微信", "跳转"]),
    ("私域引流", ["私域", "引流"]),
    ("卡片制作", ["卡片", "制作"]),
    ("合规获客", ["合规", "获客"]),
    ("数据追踪", ["数据", "追踪"]),
    ("风险边界", ["风险", "违规"]),
]

SOLUTION_OBJECT_RULES = [
    ("official_operation", "官方操作", ["官方组件", "官方入口", "企业号", "蓝V"]),
    ("manual_method", "手工方法", ["手动", "复制", "私信", "评论区"]),
    ("jump_link_tool", "跳转链接工具", ["跳转链接", "外链", "跳转工具"]),
    ("short_link_platform", "短链平台", ["短链", "加密短链"]),
    ("card_generator", "卡片生成器", ["卡片", "生成器"]),
    ("landing_page", "落地页", ["落地页", "中间页"]),
    ("enterprise_wechat", "企业微信", ["企业微信"]),
    ("third_party_provider", "第三方服务商", ["第三方", "服务商"]),
    ("saas_tool", "SaaS 工具", ["平台", "工具", "后台"]),
]

_SENTENCE_SPLIT = re.compile(r"[。！？?!；;\n]+")
_PRODUCT_HINT = re.compile(r"([\u4e00-\u9fa5A-Za-z0-9]{2,20}(?:外链|短链|卡片|二维码|企业号|Scheme))")

_GENERIC_ENTITY_NAMES = {
    "第三方工具",
    "加密短链",
    "普通分享链接",
    "分享链接",
    "抖音跳转链接",
    "抖音跳转微信",
    "抖音跳转官网",
    "深度唤醒链接",
}

_NOISY_ENTITY_PREFIXES = (
    "使用",
    "必须",
    "进入",
    "上传",
    "创建",
    "可通过",
    "帮你",
    "如",
    "仅",
    "做",
    "同时",
    "违规",
    "遇到",
    "链接",
    "自定义",
)

_NOISY_ENTITY_PARTS = ("是", "的", "就会", "容易", "年平台", "平台合规", "平台认可")


def infer_prompt_decision_mode(prompt_text: str) -> dict:
    text = prompt_text or ""
    selection = any(kw in text for kw in ["哪个", "哪一个", "哪家", "哪个好", "推荐", "用什么工具", "选择", "选"])
    comparison = any(kw in text for kw in ["对比", "比较", "区别", "优缺点"])
    how_to = any(kw in text for kw in ["怎么", "如何", "教程", "步骤", "设置", "制作", "方法"])
    troubleshooting = any(kw in text for kw in ["失败", "报错", "不能", "无法", "问题", "解决"])
    navigational = any(kw in text for kw in ["官网", "入口", "地址", "下载", "登录"])

    if comparison:
        mode = "COMPARISON"
    elif selection:
        mode = "PRODUCT_SELECTION"
    elif troubleshooting:
        mode = "TROUBLESHOOTING"
    elif how_to:
        mode = "HOW_TO"
    elif navigational:
        mode = "NAVIGATIONAL"
    else:
        mode = "INFORMATIONAL"

    recommendation_expected = mode in {"PRODUCT_SELECTION", "COMPARISON"}
    return {
        "decision_mode": mode,
        "decision_mode_label": DECISION_MODE_LABELS[mode],
        "recommendation_expected": recommendation_expected,
    }


def metric_eligibility_for_mode(decision_mode: str) -> dict:
    recommendation = decision_mode in {"PRODUCT_SELECTION", "COMPARISON"}
    task_completion = decision_mode in {"HOW_TO", "TROUBLESHOOTING", "NAVIGATIONAL"}
    return {
        "recommendation_metrics_eligible": recommendation,
        "recommendation_metrics_label": "可作为核心指标" if recommendation else "仅作诊断观察",
        "citation_metrics_eligible": True,
        "citation_metrics_label": "可用于解释证据来源",
        "retrieval_metrics_eligible": True,
        "retrieval_metrics_label": "取决于采集候选完整度",
        "task_completion_metrics_eligible": task_completion,
        "task_completion_metrics_label": "可作为核心指标" if task_completion else "暂不作为核心指标",
    }


def _assess_prompt_run_eligibility(prompt: Prompt, runs: list[BrowserMonitorRun]) -> dict:
    conversation_counts: dict[str, int] = defaultdict(int)
    for run in runs:
        if run.conversation_id:
            conversation_counts[run.conversation_id] += 1

    rows = []
    analysis_run_ids = []
    answer_analysis_run_ids = []
    citation_analysis_run_ids = []
    for run in runs:
        status, reasons, warnings = _run_eligibility_status(prompt, run, conversation_counts)
        answer_analysis_usable = status in {"ELIGIBLE", "PARTIAL"}
        citation_analysis_usable = status == "ELIGIBLE"
        analysis_usable = answer_analysis_usable
        if analysis_usable:
            analysis_run_ids.append(run.id)
        if answer_analysis_usable:
            answer_analysis_run_ids.append(run.id)
        if citation_analysis_usable:
            citation_analysis_run_ids.append(run.id)
        rows.append({
            "run_id": run.id,
            "sample_index": run.sample_index,
            "run_sequence": run.run_sequence,
            "collection_status": run.status,
            "collection_mode": run.collection_mode,
            "sampling_mode": run.sampling_mode,
            "conversation_id": run.conversation_id,
            "status": status,
            "status_label": RUN_ELIGIBILITY_LABELS.get(status, status),
            "analysis_usable": analysis_usable,
            "answer_analysis_usable": answer_analysis_usable,
            "citation_analysis_usable": citation_analysis_usable,
            "reasons": reasons,
            "warnings": warnings,
        })

    total = len(rows)
    eligible_ids = [row["run_id"] for row in rows if row["status"] == "ELIGIBLE"]
    partial_ids = [row["run_id"] for row in rows if row["status"] == "PARTIAL"]
    ineligible_ids = [row["run_id"] for row in rows if row["status"] == "INELIGIBLE"]
    unknown_ids = [row["run_id"] for row in rows if row["status"] == "UNKNOWN"]
    return {
        "schema_version": PROMPT_RUN_ELIGIBILITY_VERSION,
        "analysis_unit": "SINGLE_PROMPT",
        "prompt_id": prompt.id,
        "prompt_text": prompt.prompt_text,
        "total_runs": total,
        "eligible_runs": len(eligible_ids),
        "partial_runs": len(partial_ids),
        "ineligible_runs": len(ineligible_ids),
        "unknown_runs": len(unknown_ids),
        "analysis_usable_runs": len(analysis_run_ids),
        "answer_analysis_usable_runs": len(answer_analysis_run_ids),
        "citation_analysis_usable_runs": len(citation_analysis_run_ids),
        "eligible_run_ids": eligible_ids,
        "partial_run_ids": partial_ids,
        "analysis_run_ids": analysis_run_ids,
        "answer_analysis_run_ids": answer_analysis_run_ids,
        "citation_analysis_run_ids": citation_analysis_run_ids,
        "ineligible_run_ids": ineligible_ids,
        "unknown_run_ids": unknown_ids,
        "metrics": {
            "eligible_run_rate": _metric("eligible_run_rate", len(eligible_ids), total, total),
            "analysis_usable_run_rate": _metric("analysis_usable_run_rate", len(analysis_run_ids), total, total),
            "answer_analysis_usable_run_rate": _metric("answer_analysis_usable_run_rate", len(answer_analysis_run_ids), total, total),
            "citation_analysis_usable_run_rate": _metric("citation_analysis_usable_run_rate", len(citation_analysis_run_ids), total, total),
        },
        "rows": rows,
        "boundary_note": "正式 GEO 分析以单 Prompt 的独立新会话采样为单位；partial_success 只能进入答案理解等非引用分析，不能进入 Citation/Source/检索重合指标分母。",
    }


def _run_eligibility_status(
    prompt: Prompt,
    run: BrowserMonitorRun,
    conversation_counts: dict[str, int],
) -> tuple[str, list[str], list[str]]:
    reasons: list[str] = []
    warnings: list[str] = []

    if run.status not in VALID_RUN_STATUSES:
        reasons.append("COLLECTION_STATUS_NOT_ANALYZABLE")
    if not (run.answer_text or "").strip():
        reasons.append("EMPTY_ANSWER")
    if not _run_prompt_matches(prompt, run):
        reasons.append("PROMPT_MISMATCH")
    collection_mode = (run.collection_mode or "").strip()
    if collection_mode != "single_independent":
        if collection_mode == "single_continuous":
            reasons.append("CONTEXT_CONTAMINATION")
        elif collection_mode:
            warnings.append("UNKNOWN_COLLECTION_MODE")
        else:
            warnings.append("MISSING_COLLECTION_MODE")
    if run.conversation_id and conversation_counts.get(run.conversation_id, 0) > 1:
        reasons.append("CONVERSATION_ID_REUSED")

    if reasons:
        return "INELIGIBLE", reasons, warnings
    if run.status == "partial_success":
        warnings.append("PARTIAL_COLLECTION_STATUS")
        return "PARTIAL", ["PARTIAL_BUT_USABLE_FOR_NON_CITATION_ANALYSIS"], warnings
    if warnings:
        return "UNKNOWN", ["NEEDS_HUMAN_RUN_ELIGIBILITY_REVIEW"], warnings
    return "ELIGIBLE", ["FRESH_INDEPENDENT_PROMPT_RUN"], warnings


def _run_prompt_matches(prompt: Prompt, run: BrowserMonitorRun) -> bool:
    expected = (prompt.prompt_text or "").strip()
    if not expected:
        return True
    observed_values = [
        (run.original_query or "").strip(),
        (run.page_query or "").strip(),
        (run.retrieval_query or "").strip(),
    ]
    observed_values = [value for value in observed_values if value]
    if not observed_values:
        return True
    expected_key = _normalize_key(expected)
    for value in observed_values:
        value_key = _normalize_key(value)
        if not value_key:
            continue
        if expected_key == value_key or expected_key in value_key or value_key in expected_key:
            return True
    return False


def run_recommendation_analysis(
    db: Session,
    project_id: int,
    prompt_id: int,
    run_ids: list[int] | None = None,
) -> dict:
    project = db.get(Project, project_id)
    prompt = db.get(Prompt, prompt_id)
    if not project or not prompt or prompt.project_id != project_id:
        raise HTTPException(status_code=404, detail="项目或问题不存在")

    query = db.query(BrowserMonitorRun).filter(
        BrowserMonitorRun.project_id == project_id,
        BrowserMonitorRun.prompt_id == prompt_id,
    )
    if run_ids:
        query = query.filter(BrowserMonitorRun.id.in_(run_ids))
    runs = query.order_by(BrowserMonitorRun.id).all()
    if not runs:
        raise HTTPException(status_code=400, detail="该问题没有可分析的采集记录")

    run_eligibility = _assess_prompt_run_eligibility(prompt, runs)
    analysis_run_ids = set(run_eligibility["answer_analysis_run_ids"])
    citation_analysis_run_ids = set(run_eligibility["citation_analysis_run_ids"])
    analysis_runs = [run for run in runs if run.id in analysis_run_ids]
    citation_analysis_runs = [run for run in runs if run.id in citation_analysis_run_ids]
    if not analysis_runs:
        raise HTTPException(status_code=400, detail="该问题没有符合独立新会话要求的可分析记录；请先补充 single_independent 采样。")

    decision = infer_prompt_decision_mode(prompt.prompt_text)
    eligibility = metric_eligibility_for_mode(decision["decision_mode"])
    eligibility["run_eligibility"] = run_eligibility
    entities = _resolve_entities(db, project, analysis_runs)

    snapshot = RecommendationIntelligenceSnapshot(
        project_id=project_id,
        prompt_id=prompt_id,
        source_run_ids_json=dumps([run.id for run in analysis_runs]),
        recommendation_schema_version=RECOMMENDATION_SCHEMA_VERSION,
        entity_resolver_version=ENTITY_RESOLVER_VERSION,
        recommendation_extractor_version=RECOMMENDATION_EXTRACTOR_VERSION,
        decision_mode=decision["decision_mode"],
        recommendation_expected=decision["recommendation_expected"],
        metric_eligibility_json=dumps(eligibility),
        status="active",
    )
    db.add(snapshot)
    db.flush()

    claims = []
    for run in analysis_runs:
        claims.extend(_extract_claims_for_run(db, snapshot, project_id, prompt_id, run, entities))
    db.flush()
    semantic_facts = _create_answer_semantic_facts(db, snapshot, project, prompt, analysis_runs, claims)
    db.flush()

    landscape = _build_landscape(analysis_runs, claims)
    reason_claims = _create_reason_claims(db, snapshot, claims)
    db.flush()
    citation_claims = [claim for claim in claims if claim.run_id in citation_analysis_run_ids]
    citation_reason_claims = [reason for reason in reason_claims if reason.run_id in citation_analysis_run_ids]
    evidence_links = _create_evidence_links(db, snapshot, citation_claims, citation_reason_claims)
    db.flush()
    selection_criteria = _create_selection_criteria(db, snapshot, project, prompt, analysis_runs, entities)
    db.flush()
    capability_claims = _create_brand_capability_claims(db, snapshot, project, prompt, analysis_runs, entities)
    db.flush()
    citation_selection_criteria = [criterion for criterion in selection_criteria if criterion.run_id in citation_analysis_run_ids]
    evidence_adoptions = _create_evidence_adoptions(db, snapshot, citation_claims, citation_selection_criteria, evidence_links)
    db.flush()
    positioning = _build_positioning(claims, reason_claims)
    decision_market = _build_decision_market(
        db=db,
        project=project,
        prompt=prompt,
        runs=analysis_runs,
        landscape=landscape,
        claims=claims,
        reason_claims=reason_claims,
        semantic_facts=semantic_facts,
        selection_criteria=selection_criteria,
        capability_claims=capability_claims,
        evidence_adoptions=evidence_adoptions,
        run_eligibility=run_eligibility,
        citation_runs=citation_analysis_runs,
    )
    decision_gaps = _create_decision_gap_diagnoses(db, snapshot, project, prompt, decision_market, claims, evidence_adoptions)
    db.flush()
    gaps = _diagnose_competitive_gaps(project, landscape, positioning, eligibility)
    interventions = decision_market.get("intervention_candidates") or _build_intervention_candidates(project, prompt, analysis_runs, landscape, positioning, gaps)
    snapshot.landscape_json = dumps(landscape)
    snapshot.positioning_json = dumps(positioning)
    snapshot.evidence_links_json = dumps([evidence_link_to_read(link) for link in evidence_links])
    snapshot.gap_diagnosis_json = dumps(decision_market.get("gap_diagnosis") or gaps)
    snapshot.intervention_candidates_json = dumps(interventions)
    db.commit()
    db.refresh(snapshot)

    return snapshot_to_read(db, snapshot)


def get_recommendation_landscape(db: Session, project_id: int, prompt_id: int, snapshot_id: int | None = None) -> dict:
    snapshot = _get_snapshot(db, project_id, prompt_id, snapshot_id)
    return snapshot_to_read(db, snapshot)


def list_recommendation_snapshots(db: Session, project_id: int, prompt_id: int | None = None, limit: int = 30) -> list[dict]:
    query = db.query(RecommendationIntelligenceSnapshot).filter(
        RecommendationIntelligenceSnapshot.project_id == project_id,
    )
    if prompt_id is not None:
        query = query.filter(RecommendationIntelligenceSnapshot.prompt_id == prompt_id)
    rows = query.order_by(
        RecommendationIntelligenceSnapshot.created_at.desc(),
        RecommendationIntelligenceSnapshot.id.desc(),
    ).limit(max(1, min(limit, 100))).all()
    return [snapshot_summary_to_read(row) for row in rows]


def list_recommendation_claims(db: Session, snapshot_id: int) -> list[dict]:
    claims = db.query(RecommendationClaim).filter(
        RecommendationClaim.snapshot_id == snapshot_id,
    ).order_by(RecommendationClaim.run_id, RecommendationClaim.position, RecommendationClaim.id).all()
    return [claim_to_read(claim) for claim in claims]


def list_recommendation_reason_claims(db: Session, snapshot_id: int) -> list[dict]:
    reasons = db.query(RecommendationReasonClaim).filter(
        RecommendationReasonClaim.snapshot_id == snapshot_id,
    ).order_by(RecommendationReasonClaim.run_id, RecommendationReasonClaim.entity_name, RecommendationReasonClaim.id).all()
    return [reason_claim_to_read(reason) for reason in reasons]


def list_recommendation_entities(db: Session, snapshot_id: int) -> list[dict]:
    snapshot = db.get(RecommendationIntelligenceSnapshot, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="决策诊断快照不存在")
    claims = db.query(RecommendationClaim).filter(RecommendationClaim.snapshot_id == snapshot_id).all()
    entity_ids = {claim.entity_id for claim in claims if claim.entity_id}
    if not entity_ids:
        return []
    entities = db.query(RecommendationEntity).filter(
        RecommendationEntity.id.in_(entity_ids),
    ).order_by(RecommendationEntity.canonical_name).all()
    claims_by_entity: dict[int, list[RecommendationClaim]] = defaultdict(list)
    for claim in claims:
        if claim.entity_id:
            claims_by_entity[claim.entity_id].append(claim)
    return [_entity_to_read(entity, claims_by_entity.get(entity.id, [])) for entity in entities]


def review_recommendation_claim(db: Session, claim_id: int, payload: dict) -> dict:
    claim = db.get(RecommendationClaim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="推荐判断不存在")
    claim.review_status = payload.get("review_status", claim.review_status)
    claim.human_payload_json = dumps({
        "entity_name": payload.get("entity_name", claim.entity_name),
        "recommendation_type": payload.get("recommendation_type", claim.recommendation_type),
        "rank": payload.get("rank", claim.rank),
        "condition_text": payload.get("condition_text", claim.condition_text),
        "reason_texts": payload.get("reason_texts", loads(claim.reason_texts_json, [])),
        "reviewer": payload.get("reviewer", "human"),
        "reviewed_at": datetime.utcnow().isoformat(),
    })
    db.commit()
    db.refresh(claim)
    return claim_to_read(claim)


def review_recommendation_reason_claim(db: Session, reason_id: int, payload: dict) -> dict:
    reason = db.get(RecommendationReasonClaim, reason_id)
    if not reason:
        raise HTTPException(status_code=404, detail="推荐理由不存在")
    reason.review_status = payload.get("review_status", reason.review_status)
    if "reason_type" in payload:
        reason.reason_type = payload.get("reason_type") or reason.reason_type
    if "reason_text" in payload:
        reason.reason_text = payload.get("reason_text") or reason.reason_text
    if "reason_span" in payload:
        reason.reason_span = payload.get("reason_span") or reason.reason_span
    if "polarity" in payload:
        reason.polarity = payload.get("polarity") or reason.polarity
    reason.human_labels_json = dumps({
        "reason_type": reason.reason_type,
        "reason_text": reason.reason_text,
        "reason_span": reason.reason_span,
        "polarity": reason.polarity,
        "reviewer": payload.get("reviewer", "human"),
        "reviewed_at": datetime.utcnow().isoformat(),
        "note": payload.get("note", ""),
    })
    db.commit()
    db.refresh(reason)
    return reason_claim_to_read(reason)


def review_recommendation_entity(db: Session, entity_id: int, payload: dict) -> dict:
    entity = db.get(RecommendationEntity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="推荐实体不存在")
    if "entity_type" in payload:
        entity.entity_type = payload.get("entity_type") or entity.entity_type
    if "entity_role" in payload:
        entity.entity_role = payload.get("entity_role") or entity.entity_role
    if "is_choice_candidate" in payload:
        entity.is_choice_candidate = bool(payload.get("is_choice_candidate"))
    entity.source = "HUMAN_REVIEWED"
    entity.confidence = max(float(entity.confidence or 0), 0.95)
    db.commit()
    db.refresh(entity)
    return _entity_to_read(entity, [])


def list_selection_criteria(db: Session, snapshot_id: int) -> list[dict]:
    rows = db.query(DecisionSelectionCriterion).filter(
        DecisionSelectionCriterion.snapshot_id == snapshot_id,
    ).order_by(DecisionSelectionCriterion.run_id, DecisionSelectionCriterion.id).all()
    return [selection_criterion_to_read(row) for row in rows]


def review_selection_criterion(db: Session, criterion_id: int, payload: dict) -> dict:
    row = db.get(DecisionSelectionCriterion, criterion_id)
    if not row:
        raise HTTPException(status_code=404, detail="选择标准不存在")
    row.review_status = payload.get("review_status", row.review_status)
    row.human_label_json = dumps({
        "criterion_label": payload.get("criterion_label", row.criterion_label),
        "criterion_used_for_selection": payload.get("criterion_used_for_selection", row.criterion_used_for_selection),
        "related_brand_name": payload.get("related_brand_name", row.related_brand_name),
        "reviewer": payload.get("reviewer", "human"),
        "reviewed_at": datetime.utcnow().isoformat(),
    })
    db.commit()
    db.refresh(row)
    return selection_criterion_to_read(row)


def list_capability_claims(db: Session, snapshot_id: int) -> list[dict]:
    rows = db.query(BrandCapabilityClaim).filter(
        BrandCapabilityClaim.snapshot_id == snapshot_id,
    ).order_by(BrandCapabilityClaim.run_id, BrandCapabilityClaim.id).all()
    return [capability_claim_to_read(row) for row in rows]


def review_capability_claim(db: Session, claim_id: int, payload: dict) -> dict:
    row = db.get(BrandCapabilityClaim, claim_id)
    if not row:
        raise HTTPException(status_code=404, detail="能力识别不存在")
    row.review_status = payload.get("review_status", row.review_status)
    row.human_label_json = dumps({
        "predicate": payload.get("predicate", row.predicate),
        "capability_label": payload.get("capability_label", row.capability_label),
        "polarity": payload.get("polarity", row.polarity),
        "reviewer": payload.get("reviewer", "human"),
        "reviewed_at": datetime.utcnow().isoformat(),
    })
    db.commit()
    db.refresh(row)
    return capability_claim_to_read(row)


def list_evidence_adoptions(db: Session, snapshot_id: int) -> list[dict]:
    rows = db.query(DecisionEvidenceAdoption).filter(
        DecisionEvidenceAdoption.snapshot_id == snapshot_id,
    ).order_by(DecisionEvidenceAdoption.run_id, DecisionEvidenceAdoption.id).all()
    return [evidence_adoption_to_read(row) for row in rows]


def list_answer_semantic_facts(db: Session, snapshot_id: int) -> list[dict]:
    rows = db.query(AnswerSemanticFact).filter(
        AnswerSemanticFact.snapshot_id == snapshot_id,
    ).order_by(AnswerSemanticFact.run_id, AnswerSemanticFact.fact_type).all()
    return [answer_semantic_fact_to_read(row) for row in rows]


def list_passage_support_summary(db: Session, snapshot_id: int) -> dict:
    snapshot = db.get(RecommendationIntelligenceSnapshot, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="决策诊断快照不存在")

    run_ids = loads(snapshot.source_run_ids_json, [])
    if not run_ids:
        return _empty_passage_support_summary(snapshot_id)

    claims = db.query(AnswerClaim).filter(AnswerClaim.run_id.in_(run_ids)).order_by(AnswerClaim.run_id, AnswerClaim.claim_index).all()
    if not claims:
        return {
            **_empty_passage_support_summary(snapshot_id),
            "run_ids": run_ids,
            "eligibility": "NEEDS_CLAIM_EXTRACTION",
            "eligibility_label": "需要先提取回答主张",
        }

    claim_ids = [claim.id for claim in claims]
    alignments = db.query(PassageAlignment).filter(PassageAlignment.answer_claim_id.in_(claim_ids)).order_by(PassageAlignment.run_id, PassageAlignment.id).all()
    docs_by_id = {
        doc.id: doc
        for doc in db.query(SourceDocument).filter(SourceDocument.id.in_([a.source_document_id for a in alignments if a.source_document_id])).all()
    }
    alignments_by_claim: dict[int, list[PassageAlignment]] = defaultdict(list)
    for alignment in alignments:
        alignments_by_claim[alignment.answer_claim_id].append(alignment)

    rows = []
    for claim in claims:
        claim_alignments = alignments_by_claim.get(claim.id, [])
        best = _best_passage_alignment(claim_alignments)
        doc = docs_by_id.get(best.source_document_id) if best and best.source_document_id else None
        rows.append(_passage_support_row_to_read(claim, best, doc))

    directly_aligned = [row for row in rows if row["alignment_status"] == "DIRECT_TEXT_MATCH"]
    near_aligned = [row for row in rows if row["alignment_status"] == "NEAR_TEXT_MATCH"]
    unresolved = [row for row in rows if row["alignment_status"] == "UNRESOLVED"]
    eligible = len(rows)
    return {
        "snapshot_id": snapshot_id,
        "run_ids": run_ids,
        "eligibility": "PASSAGE_ALIGNMENT_AVAILABLE" if alignments else "NEEDS_PASSAGE_ALIGNMENT",
        "eligibility_label": "已有正文对齐结果" if alignments else "需要先抓取引用正文并运行段落对齐",
        "boundary_note": "这里展示 Answer Claim 与引用页面正文的文本对齐状态。精确/近似对齐可以作为正文支撑的候选证据，但仍需人工确认语义是否真的支撑；未对齐不等于模型来自训练语料。",
        "metrics": {
            "claim_count": _metric("claim_count", eligible, eligible, eligible),
            "direct_text_match_rate": _metric("direct_text_match_rate", len(directly_aligned), eligible, eligible),
            "near_text_match_rate": _metric("near_text_match_rate", len(near_aligned), eligible, eligible),
            "unresolved_rate": _metric("unresolved_rate", len(unresolved), eligible, eligible),
        },
        "rows": rows,
    }


def review_answer_semantic_fact(db: Session, fact_id: int, payload: dict) -> dict:
    row = db.get(AnswerSemanticFact, fact_id)
    if not row:
        raise HTTPException(status_code=404, detail="答案语义事实不存在")
    if "fact_value" in payload:
        row.fact_value = bool(payload["fact_value"])
    row.review_status = payload.get("review_status", row.review_status)
    row.human_labels_json = dumps({
        "fact_value": row.fact_value,
        "evidence_span": payload.get("evidence_span", row.evidence_span),
        "reviewer": payload.get("reviewer", "human"),
        "reviewed_at": datetime.utcnow().isoformat(),
        "note": payload.get("note", ""),
    })
    db.commit()
    db.refresh(row)
    return answer_semantic_fact_to_read(row)


def list_target_brand_capability_truths(db: Session, project_id: int) -> list[dict]:
    rows = db.query(TargetBrandCapabilityTruth).filter(
        TargetBrandCapabilityTruth.project_id == project_id,
    ).order_by(TargetBrandCapabilityTruth.capability_label, TargetBrandCapabilityTruth.id).all()
    return [product_truth_to_read(row) for row in rows]


def upsert_target_brand_capability_truth(db: Session, project_id: int, payload: dict) -> dict:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    capability_label = (payload.get("capability_label") or "").strip()
    if not capability_label:
        raise HTTPException(status_code=400, detail="请提供能力名称")
    capability_key = payload.get("capability_key") or _normalize_key(capability_label)
    brand_id = payload.get("brand_id")
    if brand_id is None:
        target = db.query(RecommendationEntity).filter(
            RecommendationEntity.project_id == project_id,
            RecommendationEntity.canonical_name == project.brand_name,
        ).first()
        brand_id = target.id if target else None
    row = db.query(TargetBrandCapabilityTruth).filter(
        TargetBrandCapabilityTruth.project_id == project_id,
        TargetBrandCapabilityTruth.brand_id == brand_id,
        TargetBrandCapabilityTruth.capability_key == capability_key,
    ).first()
    if not row:
        row = TargetBrandCapabilityTruth(
            project_id=project_id,
            brand_id=brand_id,
            capability_key=capability_key,
        )
        db.add(row)
    row.capability_label = capability_label
    row.product_truth_status = payload.get("product_truth_status", row.product_truth_status or "UNKNOWN")
    row.truth_source = payload.get("truth_source", row.truth_source or "MANUAL_CONFIRMED")
    row.source_reference = payload.get("source_reference", row.source_reference or "")
    row.reviewed_by = payload.get("reviewed_by", payload.get("reviewer", row.reviewed_by or "human"))
    row.reviewed_at = datetime.utcnow()
    row.note = payload.get("note", row.note or "")
    db.commit()
    db.refresh(row)
    return product_truth_to_read(row)


def review_evidence_adoption(db: Session, adoption_id: int, payload: dict) -> dict:
    row = db.get(DecisionEvidenceAdoption, adoption_id)
    if not row:
        raise HTTPException(status_code=404, detail="证据采用关系不存在")
    row.review_status = payload.get("review_status", row.review_status)
    row.human_label_json = dumps({
        "support_role": payload.get("support_role", row.support_role),
        "support_strength": payload.get("support_strength", row.support_strength),
        "supports_claim": payload.get("supports_claim", row.supports_claim),
        "reviewer": payload.get("reviewer", "human"),
        "reviewed_at": datetime.utcnow().isoformat(),
    })
    db.commit()
    db.refresh(row)
    return evidence_adoption_to_read(row)


def list_gap_diagnoses(db: Session, snapshot_id: int) -> list[dict]:
    rows = db.query(DecisionGapDiagnosis).filter(
        DecisionGapDiagnosis.snapshot_id == snapshot_id,
    ).order_by(DecisionGapDiagnosis.id).all()
    return [gap_diagnosis_to_read(row) for row in rows]


def review_gap_diagnosis(db: Session, gap_id: int, payload: dict) -> dict:
    row = db.get(DecisionGapDiagnosis, gap_id)
    if not row:
        raise HTTPException(status_code=404, detail="差距诊断不存在")
    row.review_status = payload.get("review_status", row.review_status)
    row.human_label_json = dumps({
        "gap_type": payload.get("gap_type", row.gap_type),
        "severity": payload.get("severity", row.severity),
        "diagnosis_text": payload.get("diagnosis_text", row.diagnosis_text),
        "reviewer": payload.get("reviewer", "human"),
        "reviewed_at": datetime.utcnow().isoformat(),
    })
    db.commit()
    db.refresh(row)
    return gap_diagnosis_to_read(row)


def _latest_evidence_package_for_decision_snapshot(
    db: Session,
    project_id: int,
    prompt_id: int,
    run_ids: list[int],
) -> OptimizationEvidencePackage | None:
    query = (
        db.query(OptimizationEvidencePackage)
        .filter(
            OptimizationEvidencePackage.project_id == project_id,
            OptimizationEvidencePackage.prompt_id == prompt_id,
        )
        .order_by(OptimizationEvidencePackage.version.desc(), OptimizationEvidencePackage.id.desc())
    )
    rows = query.limit(20).all()
    if not rows:
        return None
    run_id_set = {int(run_id) for run_id in run_ids if run_id is not None}
    if run_id_set:
        for package in rows:
            package_run_ids = {int(run_id) for run_id in loads(package.source_run_ids_json, []) if run_id is not None}
            if run_id_set <= package_run_ids:
                return package
    return rows[0]


def create_decision_market_experiment_draft(db: Session, snapshot_id: int, payload: dict | None = None) -> dict:
    snapshot = db.get(RecommendationIntelligenceSnapshot, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="决策市场快照不存在")
    project = db.get(Project, snapshot.project_id)
    prompt = db.get(Prompt, snapshot.prompt_id)
    if not project or not prompt:
        raise HTTPException(status_code=404, detail="项目或问题不存在")

    run_ids = loads(snapshot.source_run_ids_json, [])
    runs = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.id.in_(run_ids)).order_by(BrowserMonitorRun.id).all() if run_ids else []
    market = _decision_market_to_read(db, snapshot, project, prompt, runs, loads(snapshot.landscape_json, []))
    gaps = market.get("gap_diagnosis", [])
    actionable_gaps = [gap for gap in gaps if gap.get("gap_type") not in {"INTENT_FIT_GAP"}]
    primary_gap = actionable_gaps[0] if actionable_gaps else (gaps[0] if gaps else None)
    action_package = market.get("action_package", {})
    experiment_proposal = action_package.get("experiment_proposal", {})
    intervention_candidates = market.get("intervention_candidates", [])
    selected_intervention = intervention_candidates[0] if intervention_candidates else {}
    owner = (payload or {}).get("owner") or "待分配"

    if not primary_gap:
        raise HTTPException(status_code=400, detail="当前快照没有可转为实验的结构化差距")

    evidence_package = _latest_evidence_package_for_decision_snapshot(db, project.id, prompt.id, run_ids)
    if not evidence_package:
        raise HTTPException(status_code=400, detail="Decision Market 只能先生成策略候选；请先为该问题生成 Evidence Package，再进入人工审核和 effective_payload 执行链。")

    content_brief = action_package.get("content_brief", {})
    baseline_metric = experiment_proposal.get("baseline") or primary_gap.get("metric") or {}
    product_truth_gate = action_package.get("product_truth_gate", {})
    product_truth_ready = product_truth_gate.get("status") == "READY_FOR_STRATEGY_REVIEW"
    validation_status = "PENDING_HUMAN_CHANNEL_REVIEW" if product_truth_ready else "BLOCKED_PRODUCT_TRUTH"
    validation_errors = [
        "目标渠道、资产类型和 target_url 必须在人工审核后的 effective_payload 中确认。",
    ]
    if not product_truth_ready:
        validation_errors.insert(0, "Product Truth UNKNOWN：目标品牌能力尚未人工确认，不能物化 Action/Experiment。")

    proposal_payload = {
        "source": "DECISION_MARKET",
        "source_snapshot_id": snapshot.id,
        "source_evidence_package_id": evidence_package.id,
        "owner": owner,
        "observed_problem": primary_gap.get("diagnosis_text", ""),
        "hypothesized_cause": primary_gap.get("action_hint") or "可能是目标品牌与用户选择标准之间缺少已确认的事实和可引用证据。",
        "core_mechanism": experiment_proposal.get("mechanism") or primary_gap.get("action_hint", ""),
        "intervention_type": "UNRESOLVED",
        "target_platform": "UNRESOLVED",
        "target_object": "UNRESOLVED",
        "target_url": "",
        "proposed_target_url": (payload or {}).get("target_url") or "",
        "target_metric": experiment_proposal.get("primary_metric") or _primary_metric_for_gap(primary_gap.get("gap_type", "UNKNOWN")),
        "baseline": baseline_metric,
        "expected_direction": "increase",
        "recommended_action": "先完成 Product Truth 与渠道/资产人工审核，再通过 effective_payload 物化 Action/Experiment。",
        "changed_features": [],
        "required_sections": content_brief.get("sections", []),
        "controlled_variables": ["product_truth", "target_channel", "target_asset", "target_url", "collection_prompt"],
        "validation_plan": {
            "entry_observed_condition": "人工审核通过 effective_payload 后，再生成 Action/Experiment 并固定复采。",
            "sustained_improvement_condition": f"{experiment_proposal.get('primary_metric') or 'candidate_capture_rate'} 出现可复核提升。",
            "minimum_sample_count": experiment_proposal.get("sample_size_target") or max(12, len(runs) or 12),
        },
        "invalidating_result": "Product Truth 无法确认，或人工审核后没有可执行的渠道/资产方案。",
        "product_truth_gate": product_truth_gate,
        "decision_market": {
            "gap_type": primary_gap.get("gap_type"),
            "gap_type_label": primary_gap.get("gap_type_label"),
            "metric": primary_gap.get("metric"),
            "asset_decision": action_package.get("asset_decision"),
            "must_answer": action_package.get("must_answer", []),
            "evidence_requirements": action_package.get("evidence_requirements", []),
            "content_brief": content_brief,
            "intervention_candidate": selected_intervention,
            "intervention_feasibility": market.get("intervention_feasibility", {}),
            "target_brand_position": market.get("target_brand_position", {}),
            "recommendation_drivers": market.get("recommendation_drivers", {}).get("rows", [])[:5],
            "source_content_pattern": market.get("source_content_pattern", {}).get("rows", [])[:5],
            "solution_slot": market.get("solution_slot"),
            "prompt_intents": market.get("prompt_intents"),
        },
        "execution_gate": {
            "status": validation_status,
            "required_path": "StrategyCandidate -> human review -> effective_payload=VALIDATED -> Action -> Experiment",
            "blocked_materialization": True,
            "errors": validation_errors,
        },
        "forbidden_changes": [
            "不得编造产品能力",
            "不得默认官网、外部平台或新页面为执行渠道",
            "不得绕过 StrategyCandidate/effective_payload 直接创建 Action/Experiment",
        ],
        "evidence_run_ids": run_ids,
        "hypothesis_type": experiment_proposal.get("hypothesis_type") or primary_gap.get("gap_type", "UNKNOWN"),
        "intervention_family": "UNRESOLVED",
        "primary_metric": experiment_proposal.get("primary_metric") or _primary_metric_for_gap(primary_gap.get("gap_type", "UNKNOWN")),
    }

    candidate = OptimizationStrategyCandidate(
        project_id=project.id,
        experiment_id=None,
        evidence_package_id=evidence_package.id,
        target_url="",
        provider="decision_market",
        model="rule_snapshot",
        prompt_version=DECISION_MARKET_SCHEMA_VERSION,
        prompt_text=f"Decision Market Snapshot #{snapshot.id} · {prompt.prompt_text}",
        generated_at=datetime.utcnow(),
        generation_status="PROPOSED",
        intervention_type="UNRESOLVED",
        target_platform="UNRESOLVED",
        target_asset="UNRESOLVED",
        target_content_type="UNRESOLVED",
        expected_primary_metric=proposal_payload["target_metric"],
        source_package_id=evidence_package.id,
        original_llm_payload_json=dumps(proposal_payload),
        structured_payload_json=dumps(proposal_payload),
        human_edited_payload_json=dumps({}),
        effective_payload_json=dumps({}),
        effective_payload_version="",
        effective_validation_status=validation_status,
        evidence_validation_status=validation_status,
        evidence_validation_errors_json=dumps(validation_errors),
        evidence_validation_warnings_json=dumps(["Decision Market 只生成非执行策略候选；Action/Experiment 必须由已审核且 VALIDATED 的 effective_payload 物化。"]),
        evidence_validated_at=None,
        evidence_validator_version=EVIDENCE_ADOPTION_ATTRIBUTION_VERSION,
        hypothesis_validation_status=validation_status,
        hypothesis_validation_errors_json=dumps(validation_errors),
        hypothesis_validation_warnings_json=dumps([]),
        hypothesis_validated_at=None,
        hypothesis_validator_version=GAP_DIAGNOSIS_RULE_VERSION,
        review_status="PENDING_REVIEW",
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)

    return {
        "status": "STRATEGY_CANDIDATE_CREATED",
        "status_label": "已生成待审核策略候选",
        "snapshot_id": snapshot.id,
        "strategy_candidate": strategy_candidate_to_read(candidate),
        "blocked_materialization": True,
        "blocking_reasons": validation_errors,
        "next_step": "请先完成人工审核和 Product Truth / 渠道 / 资产确认；只有 effective_payload=VALIDATED 后才能生成 Action/Experiment。",
    }


def snapshot_to_read(db: Session, snapshot: RecommendationIntelligenceSnapshot) -> dict:
    prompt = db.get(Prompt, snapshot.prompt_id)
    project = db.get(Project, snapshot.project_id)
    run_ids = loads(snapshot.source_run_ids_json, [])
    runs = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.id.in_(run_ids)).order_by(BrowserMonitorRun.id).all() if run_ids else []
    landscape = loads(snapshot.landscape_json, [])
    positioning = loads(snapshot.positioning_json, [])
    evidence_links = loads(snapshot.evidence_links_json, [])
    metric_eligibility = loads(snapshot.metric_eligibility_json, {})
    brand_opportunity = _analyze_brand_opportunity(project, prompt, runs, landscape)
    decision_market = _decision_market_to_read(db, snapshot, project, prompt, runs, landscape)
    return {
        "id": snapshot.id,
        "project_id": snapshot.project_id,
        "prompt_id": snapshot.prompt_id,
        "prompt_text": prompt.prompt_text if prompt else "",
        "run_ids": run_ids,
        "run_count": len(run_ids),
        "decision_mode": snapshot.decision_mode,
        "decision_mode_label": DECISION_MODE_LABELS.get(snapshot.decision_mode, snapshot.decision_mode),
        "recommendation_expected": snapshot.recommendation_expected,
        "metric_eligibility": metric_eligibility,
        "run_eligibility": metric_eligibility.get("run_eligibility", {}),
        "landscape_scope_label": "仅统计项目品牌和竞品品牌",
        "landscape": landscape,
        "positioning": positioning,
        "brand_opportunity": brand_opportunity,
        "decision_market": decision_market,
        "answer_samples": _build_answer_samples(project, runs, landscape),
        "citation_sources": _build_citation_sources(db, runs, evidence_links),
        "action_brief": _build_action_brief(project, prompt, landscape, brand_opportunity),
        "evidence_links": evidence_links,
        "gap_diagnosis": loads(snapshot.gap_diagnosis_json, []),
        "intervention_candidates": loads(snapshot.intervention_candidates_json, []),
        "recommendation_schema_version": snapshot.recommendation_schema_version,
        "entity_resolver_version": snapshot.entity_resolver_version,
        "recommendation_extractor_version": snapshot.recommendation_extractor_version,
        "generated_at": snapshot.created_at,
        "created_at": snapshot.created_at,
        "updated_at": snapshot.updated_at,
        "status": snapshot.status,
    }


def snapshot_summary_to_read(snapshot: RecommendationIntelligenceSnapshot) -> dict:
    run_ids = loads(snapshot.source_run_ids_json, [])
    return {
        "id": snapshot.id,
        "project_id": snapshot.project_id,
        "prompt_id": snapshot.prompt_id,
        "run_count": len(run_ids),
        "source_run_ids": run_ids,
        "decision_mode": snapshot.decision_mode,
        "decision_mode_label": DECISION_MODE_LABELS.get(snapshot.decision_mode, snapshot.decision_mode),
        "recommendation_expected": snapshot.recommendation_expected,
        "recommendation_schema_version": snapshot.recommendation_schema_version,
        "recommendation_extractor_version": snapshot.recommendation_extractor_version,
        "status": snapshot.status,
        "generated_at": snapshot.created_at,
        "created_at": snapshot.created_at,
        "updated_at": snapshot.updated_at,
    }


def claim_to_read(claim: RecommendationClaim) -> dict:
    return {
        "id": claim.id,
        "snapshot_id": claim.snapshot_id,
        "run_id": claim.run_id,
        "prompt_id": claim.prompt_id,
        "entity_id": claim.entity_id,
        "entity_name": claim.entity_name,
        "recommendation_type": claim.recommendation_type,
        "recommendation_type_label": RECOMMENDATION_TYPE_LABELS.get(claim.recommendation_type, claim.recommendation_type),
        "position": claim.position,
        "rank": claim.rank,
        "is_conditional": claim.is_conditional,
        "condition_type": claim.condition_type,
        "condition_type_label": CONDITION_TYPE_LABELS.get(claim.condition_type, claim.condition_type),
        "condition_text": claim.condition_text,
        "recommendation_text": claim.recommendation_text,
        "recommendation_span": claim.recommendation_span or claim.answer_span,
        "start_offset": claim.start_offset,
        "end_offset": claim.end_offset,
        "recommendation_strength": claim.recommendation_strength,
        "recommendation_strength_label": _recommendation_strength_label(claim.recommendation_strength),
        "is_choice_candidate": claim.is_choice_candidate,
        "answer_span": claim.answer_span,
        "polarity": claim.polarity,
        "reason_texts": loads(claim.reason_texts_json, []),
        "extraction_method": claim.extraction_method,
        "extraction_confidence": claim.extraction_confidence,
        "review_status": claim.review_status,
        "human_payload": loads(claim.human_payload_json, {}),
    }


def _entity_to_read(entity: RecommendationEntity, claims: list[RecommendationClaim]) -> dict:
    candidate_runs = {
        claim.run_id
        for claim in claims
        if claim.is_choice_candidate or claim.recommendation_type in {"CANDIDATE", "POSITIVE_RECOMMENDATION", "TOP_RECOMMENDATION"}
    }
    mention_runs = {claim.run_id for claim in claims}
    return {
        "id": entity.id,
        "project_id": entity.project_id,
        "canonical_name": entity.canonical_name,
        "entity_type": entity.entity_type,
        "entity_type_label": _entity_type_label(entity.entity_type),
        "entity_role": entity.entity_role,
        "entity_role_label": _entity_role_label(entity.entity_role),
        "is_choice_candidate": entity.is_choice_candidate,
        "aliases": loads(entity.aliases_json, []),
        "domain": entity.domain,
        "official_urls": loads(entity.official_urls_json, []),
        "normalized_key": entity.normalized_key,
        "confidence": entity.confidence,
        "source": entity.source,
        "source_label": "人工审核" if entity.source == "HUMAN_REVIEWED" else "规则抽取",
        "mention_run_count": len(mention_runs),
        "choice_candidate_run_count": len(candidate_runs),
        "representative_spans": [claim.answer_span for claim in claims[:3]],
    }


def reason_claim_to_read(reason: RecommendationReasonClaim) -> dict:
    return {
        "id": reason.id,
        "recommendation_claim_id": reason.recommendation_claim_id,
        "run_id": reason.run_id,
        "entity_id": reason.entity_id,
        "entity_name": reason.entity_name,
        "reason_type": reason.reason_type,
        "reason_type_label": _reason_type_label(reason.reason_type),
        "reason_text": reason.reason_text,
        "reason_span": reason.reason_span or reason.reason_text,
        "start_offset": reason.start_offset,
        "end_offset": reason.end_offset,
        "claim_span": reason.claim_span,
        "polarity": reason.polarity,
        "is_limitation": reason.is_limitation,
        "is_comparison": reason.is_comparison,
        "confidence": reason.confidence,
        "extractor": reason.extractor,
        "extractor_version": reason.extractor_version,
        "review_status": reason.review_status,
        "human_labels": loads(reason.human_labels_json, {}),
    }


def evidence_link_to_read(link: RecommendationEvidenceLink) -> dict:
    return {
        "id": link.id,
        "recommendation_claim_id": link.recommendation_claim_id,
        "reason_claim_id": link.reason_claim_id,
        "citation_id": link.citation_id,
        "supported_entity_id": link.supported_entity_id,
        "supported_entity_name": link.supported_entity_name,
        "evidence_roles": loads(link.evidence_roles_json, []),
        "primary_evidence_role": link.primary_evidence_role,
        "primary_evidence_role_label": _evidence_role_label(link.primary_evidence_role),
        "role_confidence": link.role_confidence,
        "role_reason": link.role_reason,
        "attribution_method": link.attribution_method,
        "attribution_confidence": link.attribution_confidence,
        "answer_span": link.answer_span,
        "source_passage": link.source_passage,
        "match_method": link.match_method,
        "match_score": link.match_score,
    }


def selection_criterion_to_read(criterion: DecisionSelectionCriterion) -> dict:
    return {
        "id": criterion.id,
        "snapshot_id": criterion.snapshot_id,
        "run_id": criterion.run_id,
        "criterion_type": criterion.criterion_type,
        "criterion_label": criterion.criterion_label,
        "normalized_criterion": criterion.normalized_criterion,
        "answer_span": criterion.answer_span,
        "start_offset": criterion.start_offset,
        "end_offset": criterion.end_offset,
        "criterion_present": criterion.criterion_present,
        "criterion_used_for_selection": criterion.criterion_used_for_selection,
        "related_brand_id": criterion.related_brand_id,
        "related_brand_name": criterion.related_brand_name,
        "related_solution_object": criterion.related_solution_object,
        "polarity": criterion.polarity,
        "confidence": criterion.confidence,
        "extractor": criterion.extractor,
        "extractor_version": criterion.extractor_version,
        "review_status": criterion.review_status,
        "human_label": loads(criterion.human_label_json, {}),
    }


def capability_claim_to_read(claim: BrandCapabilityClaim) -> dict:
    return {
        "id": claim.id,
        "snapshot_id": claim.snapshot_id,
        "run_id": claim.run_id,
        "brand_entity_id": claim.brand_entity_id,
        "brand_name": claim.brand_name,
        "need_label": claim.need_label,
        "capability_label": claim.capability_label,
        "subject_text": claim.subject_text,
        "predicate": claim.predicate,
        "object_text": claim.object_text,
        "claim_text": claim.claim_text,
        "answer_span": claim.answer_span,
        "start_offset": claim.start_offset,
        "end_offset": claim.end_offset,
        "polarity": claim.polarity,
        "negation": claim.negation,
        "epistemic_status": claim.epistemic_status,
        "confidence": claim.confidence,
        "extractor_version": claim.extractor_version,
        "review_status": claim.review_status,
        "human_label": loads(claim.human_label_json, {}),
    }


def evidence_adoption_to_read(adoption: DecisionEvidenceAdoption) -> dict:
    return {
        "id": adoption.id,
        "snapshot_id": adoption.snapshot_id,
        "run_id": adoption.run_id,
        "document_id": adoption.document_id,
        "chunk_id": adoption.chunk_id,
        "citation_id": adoption.citation_id,
        "retrieval_candidate_id": adoption.retrieval_candidate_id,
        "answer_claim_id": adoption.answer_claim_id,
        "recommendation_claim_id": adoption.recommendation_claim_id,
        "selection_criterion_id": adoption.selection_criterion_id,
        "retrieval_eligible": adoption.retrieval_eligible,
        "retrieved": adoption.retrieved,
        "cited": adoption.cited,
        "supports_claim": adoption.supports_claim,
        "associated_with_selection_reason": adoption.associated_with_selection_reason,
        "evidence_status": adoption.evidence_status,
        "evidence_status_label": EVIDENCE_STATUS_LABELS.get(adoption.evidence_status, adoption.evidence_status),
        "support_role": adoption.support_role,
        "support_role_label": _adoption_role_label(adoption.support_role),
        "support_strength": adoption.support_strength,
        "support_strength_label": _support_strength_label(adoption.support_strength),
        "confidence": adoption.confidence,
        "attribution_method": adoption.attribution_method,
        "attribution_version": adoption.attribution_version,
        "review_status": adoption.review_status,
        "human_label": loads(adoption.human_label_json, {}),
        "answer_span": adoption.answer_span,
        "evidence_span": adoption.evidence_span,
        "source_url": adoption.source_url,
        "source_domain": adoption.source_domain,
        "source_title": adoption.source_title,
    }


def answer_semantic_fact_to_read(fact: AnswerSemanticFact) -> dict:
    return {
        "id": fact.id,
        "snapshot_id": fact.snapshot_id,
        "run_id": fact.run_id,
        "fact_type": fact.fact_type,
        "fact_type_label": _semantic_fact_label(fact.fact_type),
        "fact_value": fact.fact_value,
        "evidence_span": fact.evidence_span,
        "start_offset": fact.start_offset,
        "end_offset": fact.end_offset,
        "confidence": fact.confidence,
        "extractor": fact.extractor,
        "extractor_version": fact.extractor_version,
        "review_status": fact.review_status,
        "human_labels": loads(fact.human_labels_json, {}),
    }


def _empty_passage_support_summary(snapshot_id: int) -> dict:
    return {
        "snapshot_id": snapshot_id,
        "run_ids": [],
        "eligibility": "NO_RUNS",
        "eligibility_label": "没有可分析采样",
        "boundary_note": "这里展示回答主张与引用页面正文的文本对齐状态。精确/近似对齐可以作为正文支撑的候选证据，但仍需人工确认语义是否真的支撑；未对齐不等于模型来自训练语料。",
        "metrics": {
            "claim_count": _metric("claim_count", 0, 0, 0),
            "direct_text_match_rate": _metric("direct_text_match_rate", 0, 0, 0),
            "near_text_match_rate": _metric("near_text_match_rate", 0, 0, 0),
            "unresolved_rate": _metric("unresolved_rate", 0, 0, 0),
        },
        "rows": [],
    }


def _best_passage_alignment(alignments: list[PassageAlignment]) -> PassageAlignment | None:
    if not alignments:
        return None
    priority = {
        "L1_EXACT_OVERLAP": 0,
        "L2_NEAR_DUPLICATE": 1,
        "L5_UNRESOLVED": 5,
    }
    return sorted(alignments, key=lambda item: (priority.get(item.alignment_level, 9), -float(item.score or 0), item.id))[0]


def _passage_alignment_status(alignment: PassageAlignment | None) -> tuple[str, str]:
    if not alignment:
        return "UNRESOLVED", "未建立正文对齐"
    labels = {
        "L1_EXACT_OVERLAP": ("DIRECT_TEXT_MATCH", "原文精确对齐"),
        "L2_NEAR_DUPLICATE": ("NEAR_TEXT_MATCH", "原文近似对齐"),
        "L5_UNRESOLVED": ("UNRESOLVED", "未建立正文对齐"),
    }
    return labels.get(alignment.alignment_level, ("UNCERTAIN", "需要人工判断"))


def _passage_support_row_to_read(claim: AnswerClaim, alignment: PassageAlignment | None, doc: SourceDocument | None) -> dict:
    status, label = _passage_alignment_status(alignment)
    return {
        "answer_claim_id": claim.id,
        "run_id": claim.run_id,
        "claim_index": claim.claim_index,
        "claim_text": claim.raw_text,
        "claim_type": claim.claim_type,
        "citation_ids": loads(claim.citation_ids_json, []),
        "alignment_id": alignment.id if alignment else None,
        "citation_id": alignment.citation_id if alignment else claim.citation_anchor,
        "source_document_id": alignment.source_document_id if alignment else None,
        "source_title": doc.title if doc else "",
        "source_url": doc.url if doc else "",
        "source_domain": doc.domain if doc else "",
        "passage_index": alignment.passage_index if alignment else None,
        "alignment_level": alignment.alignment_level if alignment else "UNRESOLVED",
        "alignment_status": status,
        "alignment_status_label": label,
        "alignment_method": alignment.alignment_method if alignment else "",
        "score": alignment.score if alignment else 0,
        "evidence": alignment.evidence if alignment else "当前没有找到可对齐的引用正文段落。",
        "review_status": alignment.review_status if alignment else claim.review_status,
        "support_boundary": "文本对齐不是因果证明；需要人工确认正文语义是否支撑该回答主张。",
    }


def product_truth_to_read(row: TargetBrandCapabilityTruth) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "brand_id": row.brand_id,
        "capability_key": row.capability_key,
        "capability_label": row.capability_label,
        "product_truth_status": row.product_truth_status,
        "product_truth_status_label": PRODUCT_TRUTH_STATUS_LABELS.get(row.product_truth_status, row.product_truth_status),
        "truth_source": row.truth_source,
        "source_reference": row.source_reference,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at,
        "note": row.note,
    }


def gap_diagnosis_to_read(gap: DecisionGapDiagnosis) -> dict:
    return {
        "id": gap.id,
        "snapshot_id": gap.snapshot_id,
        "gap_type": gap.gap_type,
        "gap_type_label": _gap_type_label(gap.gap_type),
        "severity": gap.severity,
        "severity_label": _severity_label(gap.severity),
        "confidence": gap.confidence,
        "metric": _metric(gap.metric_name, gap.numerator, gap.denominator, gap.eligible_denominator),
        "metric_value": gap.metric_value,
        "supporting_run_ids": loads(gap.supporting_run_ids_json, []),
        "counterexample_run_ids": loads(gap.counterexample_run_ids_json, []),
        "supporting_claim_ids": loads(gap.supporting_claim_ids_json, []),
        "supporting_evidence_ids": loads(gap.supporting_evidence_ids_json, []),
        "diagnosis_basis": loads(gap.diagnosis_basis_json, {}),
        "rule_version": gap.rule_version,
        "llm_version": gap.llm_version,
        "review_status": gap.review_status,
        "human_label": loads(gap.human_label_json, {}),
        "diagnosis_text": gap.diagnosis_text,
        "action_hint": gap.action_hint,
    }


def _decision_market_to_read(
    db: Session,
    snapshot: RecommendationIntelligenceSnapshot,
    project: Project | None,
    prompt: Prompt | None,
    runs: list[BrowserMonitorRun],
    landscape: list[dict],
) -> dict:
    criteria = db.query(DecisionSelectionCriterion).filter(
        DecisionSelectionCriterion.snapshot_id == snapshot.id,
    ).order_by(DecisionSelectionCriterion.run_id, DecisionSelectionCriterion.id).all()
    capabilities = db.query(BrandCapabilityClaim).filter(
        BrandCapabilityClaim.snapshot_id == snapshot.id,
    ).order_by(BrandCapabilityClaim.run_id, BrandCapabilityClaim.id).all()
    adoptions = db.query(DecisionEvidenceAdoption).filter(
        DecisionEvidenceAdoption.snapshot_id == snapshot.id,
    ).order_by(DecisionEvidenceAdoption.run_id, DecisionEvidenceAdoption.id).all()
    gaps = db.query(DecisionGapDiagnosis).filter(
        DecisionGapDiagnosis.snapshot_id == snapshot.id,
    ).order_by(DecisionGapDiagnosis.id).all()
    claims = db.query(RecommendationClaim).filter(
        RecommendationClaim.snapshot_id == snapshot.id,
    ).order_by(RecommendationClaim.run_id, RecommendationClaim.position, RecommendationClaim.id).all()
    reasons = db.query(RecommendationReasonClaim).filter(
        RecommendationReasonClaim.snapshot_id == snapshot.id,
    ).order_by(RecommendationReasonClaim.run_id, RecommendationReasonClaim.entity_name, RecommendationReasonClaim.id).all()
    semantic_facts = db.query(AnswerSemanticFact).filter(
        AnswerSemanticFact.snapshot_id == snapshot.id,
    ).order_by(AnswerSemanticFact.run_id, AnswerSemanticFact.fact_type).all()
    metric_eligibility = loads(snapshot.metric_eligibility_json, {})
    run_eligibility = metric_eligibility.get("run_eligibility") or {}
    citation_run_ids = set(run_eligibility.get("citation_analysis_run_ids") or [])
    citation_runs = [run for run in runs if run.id in citation_run_ids] if citation_run_ids else None

    return _build_decision_market(
        db=db,
        project=project,
        prompt=prompt,
        runs=runs,
        landscape=landscape,
        claims=claims,
        reason_claims=reasons,
        semantic_facts=semantic_facts,
        selection_criteria=criteria,
        capability_claims=capabilities,
        evidence_adoptions=adoptions,
        run_eligibility=run_eligibility,
        persisted_gaps=gaps,
        citation_runs=citation_runs,
    )


def _get_snapshot(db: Session, project_id: int, prompt_id: int, snapshot_id: int | None):
    query = db.query(RecommendationIntelligenceSnapshot).filter(
        RecommendationIntelligenceSnapshot.project_id == project_id,
        RecommendationIntelligenceSnapshot.prompt_id == prompt_id,
    )
    if snapshot_id:
        query = query.filter(RecommendationIntelligenceSnapshot.id == snapshot_id)
    snapshot = query.order_by(RecommendationIntelligenceSnapshot.id.desc()).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail="暂无推荐市场分析，请先生成")
    return snapshot


def _resolve_entities(db: Session, project: Project, runs: list[BrowserMonitorRun]) -> list[RecommendationEntity]:
    seeds: list[dict] = []
    project_aliases = [project.brand_name, *loads(project.brand_aliases_json, [])]
    domain = urlparse(project.website_url or "").netloc.lower()
    seeds.append({
        "canonical_name": project.brand_name,
        "entity_type": "BRAND",
        "aliases": [alias for alias in project_aliases if alias],
        "domain": domain,
        "official_urls": [project.website_url] if project.website_url else [],
        "confidence": 0.95,
        "source": "PROJECT_ALIAS",
    })

    competitors = db.query(Competitor).filter(Competitor.project_id == project.id).all()
    for competitor in competitors:
        seeds.append({
            "canonical_name": competitor.name,
            "entity_type": "BRAND",
            "aliases": [competitor.name, *loads(competitor.aliases_json, [])],
            "domain": urlparse(competitor.website_url or "").netloc.lower(),
            "official_urls": [competitor.website_url] if competitor.website_url else [],
            "confidence": 0.9,
            "source": "COMPETITOR_ALIAS",
        })

    entities = []
    seen = set()
    for seed in seeds:
        key = _normalize_key(seed["canonical_name"])
        dedupe = (seed["entity_type"], key)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        entity = db.query(RecommendationEntity).filter(
            RecommendationEntity.project_id == project.id,
            RecommendationEntity.entity_type == seed["entity_type"],
            RecommendationEntity.normalized_key == key,
        ).first()
        if not entity:
            entity = RecommendationEntity(
                project_id=project.id,
                canonical_name=seed["canonical_name"],
                entity_type=seed["entity_type"],
                normalized_key=key,
            )
            db.add(entity)
            db.flush()
        entity.aliases_json = dumps(sorted(set(seed["aliases"])))
        entity.domain = seed["domain"]
        entity.official_urls_json = dumps(seed["official_urls"])
        entity.confidence = seed["confidence"]
        if entity.source != "HUMAN_REVIEWED":
            entity.entity_role = "BRAND"
            entity.is_choice_candidate = False
            entity.source = seed["source"]
        entities.append(entity)
    return entities


def _is_noisy_entity_name(name: str) -> bool:
    if name in _GENERIC_ENTITY_NAMES or len(name) < 3:
        return True
    if re.search(r"\d{4}年", name):
        return True
    if any(name.startswith(prefix) for prefix in _NOISY_ENTITY_PREFIXES):
        return True
    if any(part in name for part in _NOISY_ENTITY_PARTS):
        return True
    # Long extracted spans are usually sentence fragments rather than product names.
    if len(name) > 12 and not any(marker in name for marker in ["二维码", "企业号"]):
        return True
    return False


def _extract_claims_for_run(
    db: Session,
    snapshot: RecommendationIntelligenceSnapshot,
    project_id: int,
    prompt_id: int,
    run: BrowserMonitorRun,
    entities: list[RecommendationEntity],
) -> list[RecommendationClaim]:
    claims = []
    position = 0
    answer = run.answer_text or ""
    for sentence in _split_answer(answer):
        offset = answer.find(sentence)
        for entity in entities:
            alias = _matched_alias(sentence, entity)
            if not alias:
                continue
            position += 1
            recommendation_type = _classify_recommendation(sentence)
            condition_type, condition_text = _extract_condition(sentence)
            reasons = _extract_reasons(sentence, recommendation_type)
            is_choice_candidate = recommendation_type in {"CANDIDATE", "POSITIVE_RECOMMENDATION", "TOP_RECOMMENDATION"}
            claim = RecommendationClaim(
                snapshot_id=snapshot.id,
                project_id=project_id,
                prompt_id=prompt_id,
                run_id=run.id,
                entity_id=entity.id,
                entity_name=entity.canonical_name,
                recommendation_type=recommendation_type,
                position=position,
                rank=_extract_rank(sentence),
                is_conditional=bool(condition_text),
                condition_type=condition_type,
                condition_text=condition_text,
                recommendation_text=sentence,
                recommendation_span=sentence,
                start_offset=offset,
                end_offset=offset + len(sentence) if offset >= 0 else -1,
                recommendation_strength=_recommendation_strength(recommendation_type, sentence),
                is_choice_candidate=is_choice_candidate,
                answer_span=sentence,
                polarity="NEGATIVE" if recommendation_type == "NEGATIVE_RECOMMENDATION" else "POSITIVE" if recommendation_type in {"POSITIVE_RECOMMENDATION", "TOP_RECOMMENDATION"} else "NEUTRAL",
                reason_texts_json=dumps(reasons),
                extraction_method="RULE_DERIVED",
                extraction_confidence=_confidence_for_claim(recommendation_type, entity.source),
                prompt_version=RECOMMENDATION_EXTRACTOR_VERSION,
            )
            db.add(claim)
            claims.append(claim)
    return claims


def _create_answer_semantic_facts(
    db: Session,
    snapshot: RecommendationIntelligenceSnapshot,
    project: Project,
    prompt: Prompt,
    runs: list[BrowserMonitorRun],
    claims: list[RecommendationClaim],
) -> list[AnswerSemanticFact]:
    claims_by_run: dict[int, list[RecommendationClaim]] = defaultdict(list)
    for claim in claims:
        claims_by_run[claim.run_id].append(claim)

    rows: list[AnswerSemanticFact] = []
    for run in runs:
        run_claims = claims_by_run.get(run.id, [])
        facts = [
            _semantic_fact_payload("has_choice_slot", prompt.prompt_text, run.answer_text or "", run_claims),
            _semantic_fact_payload("has_brand_mention", prompt.prompt_text, run.answer_text or "", run_claims),
            _semantic_fact_payload("has_explicit_recommendation", prompt.prompt_text, run.answer_text or "", run_claims),
            _semantic_fact_payload("has_comparison", prompt.prompt_text, run.answer_text or "", run_claims),
            _semantic_fact_payload("has_brand_comparison", prompt.prompt_text, run.answer_text or "", run_claims),
        ]
        for payload in facts:
            row = AnswerSemanticFact(
                snapshot_id=snapshot.id,
                project_id=project.id,
                prompt_id=prompt.id,
                run_id=run.id,
                fact_type=payload["fact_type"],
                fact_value=payload["fact_value"],
                evidence_span=payload["evidence_span"],
                start_offset=payload["start_offset"],
                end_offset=payload["end_offset"],
                confidence=payload["confidence"],
                extractor="RULE_DERIVED",
                extractor_version=ANSWER_SEMANTIC_FACT_EXTRACTOR_VERSION,
                review_status="UNREVIEWED",
            )
            db.add(row)
            rows.append(row)
    return rows


def _build_landscape(runs: list[BrowserMonitorRun], claims: list[RecommendationClaim]) -> list[dict]:
    run_count = len({run.id for run in runs})
    by_entity: dict[str, list[RecommendationClaim]] = defaultdict(list)
    for claim in claims:
        by_entity[claim.entity_name].append(claim)

    recommendation_events = [
        claim for claim in claims
        if claim.recommendation_type in {"POSITIVE_RECOMMENDATION", "TOP_RECOMMENDATION"}
    ]
    top_events = [claim for claim in claims if claim.recommendation_type == "TOP_RECOMMENDATION"]
    recommendation_denominator = len(recommendation_events)
    top_denominator = len(top_events)

    rows = []
    for entity_name, entity_claims in by_entity.items():
        mentioned_runs = {claim.run_id for claim in entity_claims}
        candidate_runs = {
            claim.run_id for claim in entity_claims
            if claim.recommendation_type in {"CANDIDATE", "POSITIVE_RECOMMENDATION", "TOP_RECOMMENDATION"}
        }
        recommendation_runs = {
            claim.run_id for claim in entity_claims
            if claim.recommendation_type in {"POSITIVE_RECOMMENDATION", "TOP_RECOMMENDATION"}
        }
        top_runs = {claim.run_id for claim in entity_claims if claim.recommendation_type == "TOP_RECOMMENDATION"}
        negative_runs = {claim.run_id for claim in entity_claims if claim.recommendation_type == "NEGATIVE_RECOMMENDATION"}
        ranks = [claim.rank for claim in entity_claims if claim.rank is not None]
        rec_event_count = sum(1 for claim in entity_claims if claim.recommendation_type in {"POSITIVE_RECOMMENDATION", "TOP_RECOMMENDATION"})
        top_event_count = sum(1 for claim in entity_claims if claim.recommendation_type == "TOP_RECOMMENDATION")
        rows.append({
            "entity_name": entity_name,
            "mention_run_count": len(mentioned_runs),
            "candidate_run_count": len(candidate_runs),
            "recommendation_run_count": len(recommendation_runs),
            "top1_run_count": len(top_runs),
            "negative_run_count": len(negative_runs),
            "mention_rate": _rate(len(mentioned_runs), run_count),
            "candidate_rate": _rate(len(candidate_runs), run_count),
            "recommendation_rate": _rate(len(recommendation_runs), run_count),
            "top1_rate": _rate(len(top_runs), run_count),
            "negative_rate": _rate(len(negative_runs), run_count),
            "recommendation_event_count": rec_event_count,
            "top1_event_count": top_event_count,
            "ai_recommendation_share": _rate(rec_event_count, recommendation_denominator),
            "ai_top1_share": _rate(top_event_count, top_denominator),
            "average_recommendation_position": round(sum(ranks) / len(ranks), 2) if ranks else None,
            "recommendation_stability": _stability(len(recommendation_runs), run_count),
            "representative_claims": [claim.answer_span for claim in entity_claims[:3]],
            "representative_run_ids": sorted(list(mentioned_runs))[:5],
        })
    return sorted(rows, key=lambda row: (-row["recommendation_run_count"], -row["candidate_run_count"], row["entity_name"]))


def _create_reason_claims(
    db: Session,
    snapshot: RecommendationIntelligenceSnapshot,
    claims: list[RecommendationClaim],
) -> list[RecommendationReasonClaim]:
    reasons = []
    for claim in claims:
        for text in loads(claim.reason_texts_json, []):
            reason_type = _classify_reason_type(text)
            offset = (claim.answer_span or "").find(text)
            reason = RecommendationReasonClaim(
                snapshot_id=snapshot.id,
                recommendation_claim_id=claim.id,
                project_id=claim.project_id,
                prompt_id=claim.prompt_id,
                run_id=claim.run_id,
                entity_id=claim.entity_id,
                entity_name=claim.entity_name,
                reason_type=reason_type,
                reason_text=text,
                reason_span=text,
                start_offset=claim.start_offset + offset if claim.start_offset >= 0 and offset >= 0 else -1,
                end_offset=claim.start_offset + offset + len(text) if claim.start_offset >= 0 and offset >= 0 else -1,
                claim_span=claim.answer_span,
                polarity=claim.polarity,
                is_limitation=any(kw in text for kw in ["限制", "风险", "不能", "无法", "警惕", "避免"]),
                is_comparison=any(kw in text for kw in ["相比", "对比", "更", "优于", "不如"]),
                confidence=max(0.4, claim.extraction_confidence - 0.05),
                extractor="RULE_DERIVED",
                extractor_version=RECOMMENDATION_REASON_EXTRACTOR_VERSION,
                review_status="UNREVIEWED",
            )
            db.add(reason)
            reasons.append(reason)
    return reasons


def _create_evidence_links(
    db: Session,
    snapshot: RecommendationIntelligenceSnapshot,
    claims: list[RecommendationClaim],
    reason_claims: list[RecommendationReasonClaim],
) -> list[RecommendationEvidenceLink]:
    reasons_by_claim = defaultdict(list)
    for reason in reason_claims:
        reasons_by_claim[reason.recommendation_claim_id].append(reason)

    refs_by_run = defaultdict(list)
    run_ids = sorted({claim.run_id for claim in claims})
    refs = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all() if run_ids else []
    for ref in refs:
        refs_by_run[ref.run_id].append(ref)

    links = []
    for claim in claims:
        roles = _evidence_roles_for_claim(claim)
        if not roles:
            continue
        best_ref, source_passage, score, method = _best_reference_match(db, claim, refs_by_run.get(claim.run_id, []))
        reason = reasons_by_claim.get(claim.id, [None])[0]
        if not best_ref:
            continue
        link = RecommendationEvidenceLink(
            snapshot_id=snapshot.id,
            recommendation_claim_id=claim.id,
            reason_claim_id=reason.id if reason else None,
            citation_id=best_ref.id,
            supported_entity_id=claim.entity_id,
            supported_entity_name=claim.entity_name,
            evidence_roles_json=dumps(roles),
            primary_evidence_role=roles[0],
            role_confidence=score,
            role_reason=_role_reason_for_claim(claim, roles[0]),
            attribution_method="RULE_URL_TITLE_TEXT_MATCH",
            attribution_confidence=score,
            answer_span=claim.answer_span,
            source_passage=source_passage[:1200],
            match_method=method,
            match_score=score,
        )
        db.add(link)
        links.append(link)
    return links


def _create_selection_criteria(
    db: Session,
    snapshot: RecommendationIntelligenceSnapshot,
    project: Project,
    prompt: Prompt,
    runs: list[BrowserMonitorRun],
    entities: list[RecommendationEntity],
) -> list[DecisionSelectionCriterion]:
    rows: list[DecisionSelectionCriterion] = []
    seen: set[tuple[int, str, str]] = set()
    for run in runs:
        answer = run.answer_text or ""
        for sentence in _split_answer(answer):
            offset = answer.find(sentence)
            related_entity = _matched_entity(sentence, entities)
            solution_object = _solution_object_for_sentence(sentence)
            used_for_selection = _is_selection_context(sentence)
            polarity = "NEGATIVE" if any(kw in sentence for kw in ["不能", "无法", "风险", "违规", "处罚", "不建议"]) else "POSITIVE" if used_for_selection else "NEUTRAL"
            for criterion_type, label, keywords in CRITERION_RULES:
                matched = [keyword for keyword in keywords if keyword in sentence]
                if not matched:
                    continue
                key = (run.id, criterion_type, sentence[:120])
                if key in seen:
                    continue
                seen.add(key)
                row = DecisionSelectionCriterion(
                    snapshot_id=snapshot.id,
                    project_id=project.id,
                    prompt_id=prompt.id,
                    run_id=run.id,
                    criterion_type=criterion_type,
                    criterion_label=label,
                    normalized_criterion=_normalize_key(label),
                    answer_span=sentence,
                    start_offset=offset,
                    end_offset=offset + len(sentence) if offset >= 0 else -1,
                    criterion_present=True,
                    criterion_used_for_selection=used_for_selection,
                    related_brand_id=related_entity.id if related_entity else None,
                    related_brand_name=related_entity.canonical_name if related_entity else "",
                    related_solution_object=solution_object.get("label", ""),
                    polarity=polarity,
                    confidence=0.72 if used_for_selection else 0.62,
                    extractor="RULE_DERIVED",
                    extractor_version=SELECTION_CRITERION_EXTRACTOR_VERSION,
                    review_status="UNREVIEWED",
                )
                db.add(row)
                rows.append(row)
    return rows


def _create_brand_capability_claims(
    db: Session,
    snapshot: RecommendationIntelligenceSnapshot,
    project: Project,
    prompt: Prompt,
    runs: list[BrowserMonitorRun],
    entities: list[RecommendationEntity],
) -> list[BrandCapabilityClaim]:
    rows: list[BrandCapabilityClaim] = []
    seen: set[tuple[int, int, str]] = set()
    for run in runs:
        answer = run.answer_text or ""
        for sentence in _split_answer(answer):
            offset = answer.find(sentence)
            for entity in entities:
                alias = _matched_alias(sentence, entity)
                if not alias:
                    continue
                predicate = _capability_predicate(sentence)
                need_label = _need_label_for_sentence(sentence, prompt.prompt_text)
                capability_label = _capability_label_for_sentence(sentence)
                if predicate == "UNKNOWN" and not capability_label:
                    continue
                key = (run.id, entity.id, sentence[:140])
                if key in seen:
                    continue
                seen.add(key)
                negation = predicate in {"DOES_NOT_SUPPORT", "CONSTRAINED_FOR"} or any(kw in sentence for kw in ["不能", "无法", "不支持"])
                row = BrandCapabilityClaim(
                    snapshot_id=snapshot.id,
                    project_id=project.id,
                    prompt_id=prompt.id,
                    run_id=run.id,
                    brand_entity_id=entity.id,
                    brand_name=entity.canonical_name,
                    need_label=need_label,
                    capability_label=capability_label or need_label,
                    subject_text=alias,
                    predicate=predicate,
                    object_text=capability_label or need_label,
                    claim_text=sentence,
                    answer_span=sentence,
                    start_offset=offset,
                    end_offset=offset + len(sentence) if offset >= 0 else -1,
                    polarity="NEGATIVE" if negation else "POSITIVE",
                    negation=negation,
                    epistemic_status="OBSERVED",
                    confidence=0.74 if predicate != "UNKNOWN" else 0.58,
                    extractor_version=BRAND_CAPABILITY_EXTRACTOR_VERSION,
                    review_status="UNREVIEWED",
                )
                db.add(row)
                rows.append(row)
    return rows


def _create_evidence_adoptions(
    db: Session,
    snapshot: RecommendationIntelligenceSnapshot,
    claims: list[RecommendationClaim],
    criteria: list[DecisionSelectionCriterion],
    links: list[RecommendationEvidenceLink],
) -> list[DecisionEvidenceAdoption]:
    criteria_by_run = defaultdict(list)
    for criterion in criteria:
        criteria_by_run[criterion.run_id].append(criterion)
    claims_by_id = {claim.id: claim for claim in claims if claim.id}
    rows: list[DecisionEvidenceAdoption] = []
    run_ids = sorted({claim.run_id for claim in claims})
    candidates_by_run = defaultdict(list)
    candidates = db.query(RetrievalCandidate).filter(RetrievalCandidate.run_id.in_(run_ids)).all() if run_ids else []
    for candidate in candidates:
        candidates_by_run[candidate.run_id].append(candidate)
    for link in links:
        claim = claims_by_id.get(link.recommendation_claim_id)
        if not claim or not link.citation_id:
            continue
        ref = db.get(ReferenceSource, link.citation_id)
        doc = _document_for_ref(db, ref) if ref else None
        criterion = _best_criterion_for_claim(claim, criteria_by_run.get(claim.run_id, []))
        role = _adoption_role_from_link(link, criterion)
        candidate = _candidate_for_ref(ref, candidates_by_run.get(claim.run_id, [])) if ref else None
        row = DecisionEvidenceAdoption(
            snapshot_id=snapshot.id,
            project_id=claim.project_id,
            prompt_id=claim.prompt_id,
            run_id=claim.run_id,
            document_id=doc.id if doc else None,
            citation_id=ref.id if ref else None,
            retrieval_candidate_id=candidate.id if candidate else None,
            recommendation_claim_id=claim.id,
            selection_criterion_id=criterion.id if criterion else None,
            retrieval_eligible=True,
            retrieved=bool(candidate),
            cited=True,
            supports_claim=False,
            associated_with_selection_reason=bool(criterion and criterion.criterion_used_for_selection),
            evidence_status=_evidence_status_for_context(link, criterion),
            support_role=role,
            support_strength="UNKNOWN",
            confidence=link.attribution_confidence,
            attribution_method=link.attribution_method,
            attribution_version=EVIDENCE_ADOPTION_ATTRIBUTION_VERSION,
            review_status="UNREVIEWED",
            answer_span=link.answer_span,
            evidence_span=(link.source_passage or "")[:1200],
            source_url=(ref.url or ref.canonical_url) if ref else "",
            source_domain=ref.domain if ref else "",
            source_title=(ref.display_title or ref.matched_title) if ref else "",
        )
        db.add(row)
        rows.append(row)
    return rows


def _build_positioning(
    claims: list[RecommendationClaim],
    reason_claims: list[RecommendationReasonClaim],
) -> list[dict]:
    reason_by_entity = defaultdict(list)
    condition_by_entity = defaultdict(list)
    limitation_by_entity = defaultdict(list)
    claim_by_entity = defaultdict(list)
    for claim in claims:
        claim_by_entity[claim.entity_name].append(claim)
        if claim.condition_text:
            condition_by_entity[claim.entity_name].append(claim.condition_text)
    for reason in reason_claims:
        reason_by_entity[reason.entity_name].append(reason)
        if reason.is_limitation:
            limitation_by_entity[reason.entity_name].append(reason.reason_text)

    rows = []
    for entity_name, entity_claims in claim_by_entity.items():
        rec_claims = [c for c in entity_claims if c.recommendation_type in {"POSITIVE_RECOMMENDATION", "TOP_RECOMMENDATION"}]
        rows.append({
            "entity_name": entity_name,
            "positioning_label": "AI 当前认知",
            "dominant_recommendation_scenarios": _top_texts(condition_by_entity[entity_name], fallback=["暂无稳定条件"]),
            "dominant_reason_clusters": _top_reason_labels(reason_by_entity[entity_name]),
            "dominant_conditions": _top_texts(condition_by_entity[entity_name]),
            "dominant_limitations": _top_texts(limitation_by_entity[entity_name]),
            "recommendation_event_count": len(rec_claims),
            "recommendation_stability": _stability(len({c.run_id for c in rec_claims}), len({c.run_id for c in entity_claims})),
            "reason_consistency": _reason_consistency(reason_by_entity[entity_name]),
            "representative_claims": [claim.answer_span for claim in entity_claims[:3]],
            "representative_run_ids": sorted({claim.run_id for claim in entity_claims})[:5],
        })
    return sorted(rows, key=lambda row: (-row["recommendation_event_count"], row["entity_name"]))


def _diagnose_competitive_gaps(project: Project, landscape: list[dict], positioning: list[dict], eligibility: dict) -> list[dict]:
    target = next((row for row in landscape if row["entity_name"] == project.brand_name), None)
    leaders = [row for row in landscape if row["entity_name"] != project.brand_name and row["recommendation_run_count"] > 0]
    gaps = []
    if not target:
        gaps.append({
            "gap_type": "RECOMMENDATION_ASSOCIATION_GAP",
            "gap_type_label": "推荐关联缺口",
            "severity": "HIGH",
            "diagnosis": f"AI 当前回答中没有稳定建立「{project.brand_name}」与该问题场景的关联。",
            "evidence_basis": "目标品牌未进入推荐市场分析结果。",
        })
    elif target["recommendation_run_count"] == 0 and leaders:
        gaps.append({
            "gap_type": "RECOMMENDATION_GAP",
            "gap_type_label": "推荐缺口",
            "severity": "HIGH",
            "diagnosis": f"竞品已经出现推荐判断，但「{project.brand_name}」仅提及或未被推荐。",
            "evidence_basis": f"目标品牌推荐采样 {target['recommendation_run_count']} 次；竞品最高 {leaders[0]['entity_name']} 为 {leaders[0]['recommendation_run_count']} 次。",
        })
    elif target and target["candidate_run_count"] > 0 and target["recommendation_run_count"] == 0:
        gaps.append({
            "gap_type": "RECOMMENDATION_EVIDENCE_GAP",
            "gap_type_label": "推荐证据缺口",
            "severity": "MEDIUM",
            "diagnosis": f"「{project.brand_name}」已进入候选或提及，但缺少能支撑选择判断的外显证据。",
            "evidence_basis": "候选出现但明确推荐为 0。",
        })

    target_position = next((row for row in positioning if row["entity_name"] == project.brand_name), None)
    if not target_position or target_position["reason_consistency"] == "INSUFFICIENT_DATA":
        gaps.append({
            "gap_type": "POSITIONING_GAP",
            "gap_type_label": "定位缺口",
            "severity": "MEDIUM",
            "diagnosis": f"AI 尚未形成「{project.brand_name}」在该决策场景中的稳定定位。",
            "evidence_basis": "推荐理由和条件不足，无法形成稳定 AI 当前认知。",
        })

    if not eligibility.get("recommendation_metrics_eligible"):
        gaps.append({
            "gap_type": "INTENT_FIT_GAP",
            "gap_type_label": "意图匹配提醒",
            "severity": "LOW",
            "diagnosis": "当前问题更偏操作或信息获取，推荐率不应直接作为核心成败指标。",
            "evidence_basis": "问题决策模式的指标资格判定。",
        })
    return gaps


def _build_intervention_candidates(
    project: Project,
    prompt: Prompt,
    runs: list[BrowserMonitorRun],
    landscape: list[dict],
    positioning: list[dict],
    gaps: list[dict],
) -> list[dict]:
    if not gaps:
        return [{
            "intervention_type": "NO_ACTION",
            "intervention_type_label": "暂不行动",
            "priority": "LOW",
            "reason": "当前推荐市场没有足够明确的竞争缺口。",
            "target_metric": "人工复核",
        }]

    primary_gap = gaps[0]
    leaders = [row for row in landscape if row["entity_name"] != project.brand_name and row["recommendation_run_count"] > 0]
    leader_names = [row["entity_name"] for row in leaders[:3]]
    target_position = next((row for row in positioning if row["entity_name"] in leader_names), None)
    required_claims = []
    if target_position:
        for reason in target_position.get("dominant_reason_clusters", [])[:3]:
            required_claims.append(f"建立「{project.brand_name}」也能支撑「{reason}」的真实证据")
    if not required_claims:
        required_claims = [f"说明「{project.brand_name}」适合当前问题「{prompt.prompt_text}」的真实使用场景"]

    return [{
        "target_decision_position": "先建立可被 AI 引用的场景与推荐理由关联",
        "target_brand": project.brand_name,
        "target_product": project.brand_name,
        "competitive_gap_type": primary_gap["gap_type"],
        "competitive_gap_type_label": primary_gap["gap_type_label"],
        "observed_market_problem": primary_gap["diagnosis"],
        "target_competitor_patterns": leader_names,
        "required_claims": required_claims,
        "required_evidence": ["可公开访问的页面正文", "明确操作步骤或能力说明", "可被引用的 FAQ 或对比说明"],
        "recommended_content_type": "教程/问答型内容",
        "recommended_channel": "UNRESOLVED",
        "recommended_channel_reason": "渠道必须最后决定，不能仅凭引用数量自动选择。",
        "intervention_type": "UNRESOLVED",
        "intervention_type_label": "待人工确认渠道与资产",
        "recommended_topic": prompt.prompt_text,
        "recommended_title": f"{prompt.prompt_text}：{project.brand_name} 使用场景与操作说明",
        "required_sections": ["直接回答", "适用场景", "操作步骤", "能力边界", "常见问题"],
        "target_metric": "推荐关联出现率",
        "baseline": f"基于 {len(runs)} 次当前采样",
        "expected_direction": "提升",
        "evidence_run_ids": [run.id for run in runs],
        "controllability": "MEDIUM",
        "effort": "MEDIUM",
        "external_dependency": "需要人工确认产品事实和发布渠道",
        "priority": primary_gap["severity"],
        "validation_plan": "发布后固定复采同一问题，观察目标品牌是否出现候选、推荐理由或明确推荐。",
        "invalidating_result": "复采后仍没有出现品牌与场景/理由的稳定关联。",
    }]


def _build_decision_market(
    db: Session,
    project: Project | None,
    prompt: Prompt | None,
    runs: list[BrowserMonitorRun],
    landscape: list[dict],
    claims: list[RecommendationClaim],
    reason_claims: list[RecommendationReasonClaim],
    semantic_facts: list[AnswerSemanticFact],
    selection_criteria: list[DecisionSelectionCriterion],
    capability_claims: list[BrandCapabilityClaim],
    evidence_adoptions: list[DecisionEvidenceAdoption],
    run_eligibility: dict | None = None,
    persisted_gaps: list[DecisionGapDiagnosis] | None = None,
    citation_runs: list[BrowserMonitorRun] | None = None,
) -> dict:
    run_count = len({run.id for run in runs})
    citation_scope_runs = citation_runs if citation_runs is not None else runs
    citation_run_count = len({run.id for run in citation_scope_runs})
    prompt_text = prompt.prompt_text if prompt else ""
    intents = _classify_prompt_intents(prompt_text, runs)
    choice_slot = _build_choice_slot(prompt_text, runs, landscape, semantic_facts)
    need_market = _build_need_market(prompt_text, runs)
    solution_market = _build_solution_object_market(runs)
    criteria_market = _build_selection_criteria_market(project, selection_criteria, run_count)
    brand_funnel = _build_brand_funnel(project, landscape, claims, capability_claims, choice_slot, run_count)
    capability_market = _build_capability_market(capability_claims)
    citation_source_analysis = _build_citation_source_analysis(db, citation_scope_runs)
    evidence_market = _build_evidence_adoption_market(evidence_adoptions, citation_run_count)
    brand_opportunity_gate = _build_brand_opportunity_gate(project, runs, claims, semantic_facts)
    product_truth = _build_product_truth_summary(db, project, capability_market)
    gaps = [gap_diagnosis_to_read(gap) for gap in persisted_gaps] if persisted_gaps is not None else _derive_gap_reads(project, brand_funnel, criteria_market, evidence_market, choice_slot, brand_opportunity_gate, product_truth)
    decision_space = _build_prompt_decision_space(runs, claims, semantic_facts, choice_slot)
    recommendation_market = _build_prompt_recommendation_market(project, landscape, run_count)
    target_brand_position = _build_target_brand_position(project, brand_funnel, gaps)
    drivers = _build_prompt_recommendation_drivers(
        project=project,
        run_count=run_count,
        claims=claims,
        reason_claims=reason_claims,
        selection_criteria=selection_criteria,
        capability_claims=capability_claims,
        product_truth=product_truth,
    )
    source_pattern = _build_prompt_source_content_pattern(db, citation_scope_runs, evidence_adoptions)
    feasibility = _build_prompt_intervention_feasibility(run_eligibility or {}, gaps, product_truth)
    prompt_interventions = _build_prompt_intervention_candidates(
        project=project,
        prompt=prompt,
        gaps=gaps,
        target_brand_position=target_brand_position,
        drivers=drivers,
        source_pattern=source_pattern,
        feasibility=feasibility,
    )

    return {
        "schema_version": DECISION_MARKET_SCHEMA_VERSION,
        "scope_note": "所有结论仅代表当前 Prompt、当前采样窗口和已保存答案，不代表模型永久认知或真实市场份额。",
        "analysis_unit": "SINGLE_PROMPT",
        "run_eligibility": run_eligibility or {},
        "prompt_intents": intents,
        "primary_metric_note": _primary_metric_note(intents),
        "decision_space": decision_space,
        "answer_semantic_facts": _build_answer_semantic_summary(semantic_facts, run_count),
        "brand_opportunity_gate": brand_opportunity_gate,
        "choice_slot": choice_slot,
        "solution_slot": choice_slot,
        "recommendation_market": recommendation_market,
        "need_market": need_market,
        "solution_object_market": solution_market,
        "selection_criteria_market": criteria_market,
        "brand_funnel": brand_funnel,
        "target_brand_position": target_brand_position,
        "capability_recognition": capability_market,
        "recommendation_drivers": drivers,
        "citation_source_analysis": citation_source_analysis,
        "source_content_pattern": source_pattern,
        "citation_context": evidence_market,
        "evidence_adoption": evidence_market,
        "product_truth": product_truth,
        "gap_diagnosis": gaps,
        "primary_gap": gaps[0] if gaps else None,
        "contributing_gaps": gaps[1:3],
        "intervention_feasibility": feasibility,
        "intervention_candidates": prompt_interventions,
        "action_package": _build_action_package(project, prompt, choice_slot, criteria_market, brand_funnel, evidence_market, gaps, product_truth),
    }


def _create_decision_gap_diagnoses(
    db: Session,
    snapshot: RecommendationIntelligenceSnapshot,
    project: Project,
    prompt: Prompt,
    decision_market: dict,
    claims: list[RecommendationClaim],
    evidence_adoptions: list[DecisionEvidenceAdoption],
) -> list[DecisionGapDiagnosis]:
    created: list[DecisionGapDiagnosis] = []
    for gap in decision_market.get("gap_diagnosis", []):
        metric = gap.get("metric", {})
        row = DecisionGapDiagnosis(
            snapshot_id=snapshot.id,
            project_id=project.id,
            prompt_id=prompt.id,
            gap_type=gap.get("gap_type", "UNKNOWN"),
            severity=gap.get("severity", "UNKNOWN"),
            confidence=gap.get("confidence", 0.0),
            numerator=metric.get("numerator", 0),
            denominator=metric.get("denominator", 0),
            eligible_denominator=metric.get("eligible_denominator", metric.get("denominator", 0)),
            metric_name=metric.get("metric", ""),
            metric_value=metric.get("value"),
            supporting_run_ids_json=dumps(gap.get("supporting_run_ids", [])),
            counterexample_run_ids_json=dumps(gap.get("counterexample_run_ids", [])),
            supporting_claim_ids_json=dumps(gap.get("supporting_claim_ids", [])),
            supporting_evidence_ids_json=dumps(gap.get("supporting_evidence_ids", [])),
            diagnosis_basis_json=dumps(gap.get("diagnosis_basis", {})),
            rule_version=GAP_DIAGNOSIS_RULE_VERSION,
            llm_version="",
            review_status="UNREVIEWED",
            diagnosis_text=gap.get("diagnosis_text", ""),
            action_hint=gap.get("action_hint", ""),
        )
        db.add(row)
        created.append(row)
    return created


def _decision_issue_to_read(issue: OptimizationIssue) -> dict:
    return {
        "id": issue.id,
        "project_id": issue.project_id,
        "prompt_id": issue.prompt_id,
        "issue_type": issue.issue_type,
        "status": issue.status,
        "severity": issue.severity,
        "confidence_level": issue.confidence_level,
        "analyzable_sample_count": issue.analyzable_sample_count,
        "observed_facts": loads(issue.observed_facts_json, {}),
        "possible_causes": loads(issue.possible_causes_json, []),
        "diagnosis_summary": issue.diagnosis_summary,
        "created_at": issue.created_at,
    }


def _decision_action_to_read(action: OptimizationAction) -> dict:
    return {
        "id": action.id,
        "issue_id": action.issue_id,
        "action_type": action.action_type,
        "target_type": action.target_type,
        "target_url": action.target_url,
        "status": action.status,
        "priority": action.priority,
        "owner": action.owner,
        "action_summary": action.action_summary,
        "action_detail": loads(action.action_detail, {"raw": action.action_detail}),
        "content_feature_changes": loads(action.content_feature_changes_json, []),
        "created_at": action.created_at,
    }


def _decision_experiment_to_read(experiment: OptimizationExperiment) -> dict:
    return {
        "id": experiment.id,
        "action_id": experiment.action_id,
        "status": experiment.status,
        "hypothesis": experiment.hypothesis,
        "hypothesis_type": experiment.hypothesis_type,
        "mechanism": experiment.mechanism,
        "intervention_family": experiment.intervention_family,
        "intervention_variables": loads(experiment.intervention_variables_json, {}),
        "allowed_changes": loads(experiment.allowed_changes_json, []),
        "forbidden_changes": loads(experiment.forbidden_changes_json, []),
        "target_prompt_scope": loads(experiment.target_prompt_scope_json, []),
        "primary_metric": experiment.primary_metric,
        "secondary_metrics": loads(experiment.secondary_metrics_json, []),
        "baseline_run_ids": loads(experiment.baseline_run_ids_json, []),
        "baseline_metrics": loads(experiment.baseline_metrics_json, {}),
        "baseline_numerator": experiment.baseline_numerator,
        "baseline_denominator": experiment.baseline_denominator,
        "baseline_metric_value": experiment.baseline_metric_value,
        "success_threshold": experiment.success_threshold,
        "sample_size_target": experiment.sample_size_target,
        "recollection_strategy": loads(experiment.recollection_strategy_json, {}),
        "confounders": loads(experiment.confounders_json, []),
        "known_environment_audit": loads(experiment.known_environment_audit_json, {}),
        "comparability_status": experiment.comparability_status,
        "comparability_note": experiment.comparability_note,
        "controlled_intervention": loads(experiment.controlled_intervention_json, {}),
        "created_at": experiment.created_at,
    }


def _content_feature_changes_from_action_package(action_package: dict) -> list[dict]:
    brief = action_package.get("content_brief", {})
    changes = []
    for criterion in brief.get("target_selection_criteria", [])[:5]:
        changes.append({
            "feature": "SELECTION_CRITERION_EVIDENCE",
            "before": "缺少可引用证据",
            "after": criterion,
            "description": f"补齐「{criterion}」对应的公开中文证据",
            "location": "产品说明页/FAQ/教程正文",
        })
    for claim in brief.get("target_capability_claims", [])[:5]:
        changes.append({
            "feature": "CAPABILITY_EXPLICITNESS",
            "before": "AI 回答中未稳定识别",
            "after": claim,
            "description": claim,
            "location": "直接回答和能力说明模块",
        })
    if not changes:
        changes.append({
            "feature": "DECISION_MARKET_GAP_REPAIR",
            "before": "缺少结构化事实",
            "after": action_package.get("selection_reason_gap", "补齐决策市场缺口"),
            "description": "根据决策市场 gap 补齐可审计内容事实",
            "location": "待人工指定",
        })
    return changes


def _semantic_fact_payload(fact_type: str, prompt_text: str, answer: str, run_claims: list[RecommendationClaim]) -> dict:
    if fact_type == "has_choice_slot":
        value, span, confidence = _answer_has_choice_slot(prompt_text, answer, run_claims)
    elif fact_type == "has_brand_mention":
        value = bool(run_claims)
        span = (run_claims[0].answer_span if run_claims else "")
        confidence = 0.9 if value else 0.7
    elif fact_type == "has_explicit_recommendation":
        explicit = [claim for claim in run_claims if claim.recommendation_type in {"POSITIVE_RECOMMENDATION", "TOP_RECOMMENDATION"}]
        value = bool(explicit)
        span = explicit[0].answer_span if explicit else ""
        confidence = 0.82 if value else 0.68
    elif fact_type == "has_comparison":
        sentences = [sentence for sentence in _split_answer(answer) if _sentence_has_comparison(sentence)]
        value = bool(sentences)
        span = sentences[0] if sentences else ""
        confidence = 0.76 if value else 0.62
    elif fact_type == "has_brand_comparison":
        value, span, confidence = _answer_has_brand_comparison(answer, run_claims)
    else:
        value, span, confidence = False, "", 0.0
    offset = answer.find(span) if span else -1
    return {
        "fact_type": fact_type,
        "fact_value": value,
        "evidence_span": span,
        "start_offset": offset,
        "end_offset": offset + len(span) if offset >= 0 else -1,
        "confidence": confidence,
    }


def _build_answer_semantic_summary(facts: list[AnswerSemanticFact], run_count: int) -> dict:
    grouped: dict[str, list[AnswerSemanticFact]] = defaultdict(list)
    for fact in facts:
        grouped[fact.fact_type].append(fact)
    metrics = {}
    for fact_type in ["has_choice_slot", "has_brand_mention", "has_explicit_recommendation", "has_comparison", "has_brand_comparison"]:
        positives = [fact for fact in grouped.get(fact_type, []) if fact.fact_value]
        metrics[fact_type] = _metric(f"{fact_type}_rate", len({fact.run_id for fact in positives}), run_count, run_count)
    return {
        "metrics": metrics,
        "facts": [answer_semantic_fact_to_read(fact) for fact in facts[:80]],
        "boundary_note": "三个核心布尔事实独立判断：品牌提及不推出选择空间，明确推荐也不自动推出整条回答存在稳定选择空间。",
    }


def _build_brand_opportunity_gate(
    project: Project | None,
    runs: list[BrowserMonitorRun],
    claims: list[RecommendationClaim],
    facts: list[AnswerSemanticFact],
) -> dict:
    run_count = len({run.id for run in runs})
    choice_runs = {fact.run_id for fact in facts if fact.fact_type == "has_choice_slot" and fact.fact_value}
    brand_mention_runs = {claim.run_id for claim in claims}
    recommendation_runs = {
        claim.run_id for claim in claims
        if claim.recommendation_type in {"POSITIVE_RECOMMENDATION", "TOP_RECOMMENDATION"}
    }
    choice_rate = len(choice_runs) / run_count if run_count else 0
    if run_count == 0:
        level = "INSUFFICIENT_SAMPLE"
    elif choice_rate == 0:
        level = "NO_BRAND_OPPORTUNITY"
    elif choice_rate < 0.25:
        level = "LOW_BRAND_OPPORTUNITY"
    elif choice_rate < 0.6:
        level = "MEANINGFUL_BRAND_OPPORTUNITY"
    else:
        level = "STRONG_BRAND_DECISION_MARKET"
    labels = {
        "INSUFFICIENT_SAMPLE": "样本不足",
        "NO_BRAND_OPPORTUNITY": "没有品牌选择空间",
        "LOW_BRAND_OPPORTUNITY": "低品牌机会",
        "MEANINGFUL_BRAND_OPPORTUNITY": "存在品牌选择空间",
        "STRONG_BRAND_DECISION_MARKET": "强品牌决策市场",
    }
    return {
        "brand_name": project.brand_name if project else "",
        "opportunity_level": level,
        "opportunity_level_label": labels.get(level, level),
        "choice_slot_runs": sorted(choice_runs),
        "brand_mention_runs": sorted(brand_mention_runs),
        "recommendation_runs": sorted(recommendation_runs),
        "metrics": {
            "choice_slot_rate": _metric("choice_slot_rate", len(choice_runs), run_count, run_count),
            "brand_mention_rate": _metric("brand_mention_rate", len(brand_mention_runs), run_count, run_count),
            "explicit_recommendation_rate": _metric("explicit_recommendation_rate", len(recommendation_runs), run_count, run_count),
        },
        "gate_passed": level in {"MEANINGFUL_BRAND_OPPORTUNITY", "STRONG_BRAND_DECISION_MARKET"},
        "boundary_note": "必须先判断是否存在可替代选择空间；没有选择空间时，不输出目标品牌关联/候选/推荐缺口。",
    }


def _build_product_truth_summary(db: Session, project: Project | None, capability_market: dict) -> dict:
    if not project:
        return {"truths": [], "boundary_note": "项目不存在，无法判断产品事实。"}
    target_rows = [row for row in capability_market.get("claims", []) if row.get("brand_name") == project.brand_name]
    capability_labels = {row.get("capability_label") for row in target_rows if row.get("capability_label")}
    if not capability_labels:
        for row in capability_market.get("claims", [])[:8]:
            label = row.get("capability_label")
            if label:
                capability_labels.add(label)
    existing = db.query(TargetBrandCapabilityTruth).filter(
        TargetBrandCapabilityTruth.project_id == project.id,
    ).all()
    existing_by_key = {row.capability_key: row for row in existing}
    truths = []
    for label in sorted(capability_labels):
        key = _normalize_key(label)
        row = existing_by_key.get(key)
        truths.append(product_truth_to_read(row) if row else {
            "id": None,
            "project_id": project.id,
            "brand_id": None,
            "capability_key": key,
            "capability_label": label,
            "product_truth_status": "UNKNOWN",
            "product_truth_status_label": PRODUCT_TRUTH_STATUS_LABELS["UNKNOWN"],
            "truth_source": "",
            "source_reference": "",
            "reviewed_by": "",
            "reviewed_at": None,
            "note": "",
        })
    return {
        "truths": truths,
        "metrics": {
            "confirmed_truth_rate": _metric(
                "confirmed_truth_rate",
                len([row for row in truths if row["product_truth_status"] in {"SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_SUPPORTED"}]),
                len(truths),
                len(truths),
            ),
        },
        "boundary_note": "Product Truth 必须来自人工确认或明确官方事实源；系统不会因为竞品具备某能力就自动假设目标品牌也具备。",
    }


def _build_prompt_decision_space(
    runs: list[BrowserMonitorRun],
    claims: list[RecommendationClaim],
    semantic_facts: list[AnswerSemanticFact],
    choice_slot: dict,
) -> dict:
    run_count = len({run.id for run in runs})
    choice_runs = {fact.run_id for fact in semantic_facts if fact.fact_type == "has_choice_slot" and fact.fact_value}
    mention_runs = {claim.run_id for claim in claims}
    candidate_runs = {
        claim.run_id for claim in claims
        if claim.recommendation_type in {"CANDIDATE", "POSITIVE_RECOMMENDATION", "TOP_RECOMMENDATION"}
    }
    recommendation_runs = {
        claim.run_id for claim in claims
        if claim.recommendation_type in {"POSITIVE_RECOMMENDATION", "TOP_RECOMMENDATION"}
    }
    comparison_runs = {fact.run_id for fact in semantic_facts if fact.fact_type == "has_brand_comparison" and fact.fact_value}

    if comparison_runs:
        status = "BRAND_COMPARISON_PRESENT"
    elif recommendation_runs:
        status = "BRAND_RECOMMENDATION_PRESENT"
    elif candidate_runs:
        status = "BRAND_CANDIDATE_SPACE"
    elif choice_runs or choice_slot.get("solution_required") in {"OPTIONAL", "REQUIRED"}:
        status = "SOLUTION_CHOICE_SPACE"
    else:
        status = "NO_BRAND_DECISION_SPACE"
    return {
        "schema_version": PROMPT_DECISION_SPACE_VERSION,
        "status": status,
        "status_label": DECISION_SPACE_LABELS.get(status, status),
        "eligible_run_count": run_count,
        "metrics": {
            "choice_slot_rate": _metric("choice_slot_rate", len(choice_runs), run_count, run_count),
            "brand_mention_rate": _metric("brand_mention_rate", len(mention_runs), run_count, run_count),
            "brand_candidate_rate": _metric("brand_candidate_rate", len(candidate_runs), run_count, run_count),
            "explicit_recommendation_rate": _metric("explicit_recommendation_rate", len(recommendation_runs), run_count, run_count),
            "comparison_rate": _metric("comparison_rate", len(comparison_runs), run_count, run_count),
        },
        "run_ids": {
            "choice_slot": sorted(choice_runs),
            "brand_mention": sorted(mention_runs),
            "brand_candidate": sorted(candidate_runs),
            "explicit_recommendation": sorted(recommendation_runs),
            "comparison": sorted(comparison_runs),
        },
        "boundary_note": "决策空间按单 Prompt 的合格独立样本判断；提及、候选、明确推荐和对比是独立事实，不能互相推出。",
    }


def _build_prompt_recommendation_market(project: Project | None, landscape: list[dict], run_count: int) -> dict:
    rows = []
    for row in landscape:
        rows.append({
            "entity_name": row.get("entity_name"),
            "is_target_brand": bool(project and row.get("entity_name") == project.brand_name),
            "mention": _metric("mention_share_of_runs", row.get("mention_run_count", 0), run_count, run_count),
            "candidate": _metric("candidate_share_of_runs", row.get("candidate_run_count", 0), run_count, run_count),
            "positive_recommendation": _metric("positive_recommendation_share_of_runs", row.get("recommendation_run_count", 0), run_count, run_count),
            "top_recommendation": _metric("top_recommendation_share_of_runs", row.get("top1_run_count", 0), run_count, run_count),
            "negative_recommendation": _metric("negative_recommendation_share_of_runs", row.get("negative_run_count", 0), run_count, run_count),
            "recommendation_event_count": row.get("recommendation_event_count", 0),
            "top_recommendation_event_count": row.get("top1_event_count", 0),
            "ai_recommendation_share": row.get("ai_recommendation_share"),
            "ai_top1_share": row.get("ai_top1_share"),
            "average_recommendation_position": row.get("average_recommendation_position"),
            "representative_claims": row.get("representative_claims", []),
            "representative_run_ids": row.get("representative_run_ids", []),
        })
    return {
        "schema_version": "prompt_recommendation_market.v1",
        "eligible_runs": run_count,
        "rows": rows,
        "metric_format_note": "每行同时展示 mention/candidate/positive/top/negative 的分子分母；品牌提及不等于推荐。",
    }


def _build_target_brand_position(project: Project | None, brand_funnel: dict, gaps: list[dict]) -> dict:
    target = next((row for row in brand_funnel.get("rows", []) if row.get("is_target_brand")), None)
    primary_gap = gaps[0] if gaps else None
    if not project:
        return {"status": "UNKNOWN", "status_label": "项目不存在", "target": None, "primary_gap": primary_gap}
    if not target:
        return {
            "status": "ABSENT",
            "status_label": "目标品牌未进入当前回答事实",
            "brand_name": project.brand_name,
            "target": None,
            "primary_gap": primary_gap,
            "contributing_gaps": gaps[1:3],
            "strengths": [],
        }
    strengths = []
    facts = target.get("atomic_facts", {})
    if facts.get("brand_mentioned"):
        strengths.append("已被提及")
    if facts.get("need_associated"):
        strengths.append("已与需求场景关联")
    if facts.get("capability_recognized"):
        strengths.append("已有能力识别")
    if facts.get("solution_candidate"):
        strengths.append("已进入候选")
    if facts.get("explicitly_recommended"):
        strengths.append("已有明确推荐")
    if facts.get("top_recommended"):
        strengths.append("已有第一推荐")
    return {
        "status": target.get("derived_stage", "UNKNOWN"),
        "status_label": _target_stage_label(target.get("derived_stage", "UNKNOWN")),
        "brand_name": project.brand_name,
        "target": target,
        "primary_gap": primary_gap,
        "contributing_gaps": gaps[1:3],
        "strengths": strengths,
        "boundary_note": "目标品牌位置只表示 AI 当前回答里的观察事实，不表示真实产品能力。",
    }


def _build_prompt_recommendation_drivers(
    project: Project | None,
    run_count: int,
    claims: list[RecommendationClaim],
    reason_claims: list[RecommendationReasonClaim],
    selection_criteria: list[DecisionSelectionCriterion],
    capability_claims: list[BrandCapabilityClaim],
    product_truth: dict,
) -> dict:
    target_name = project.brand_name if project else ""
    competitor_names = {competitor.name for competitor in project.competitors} if project and project.competitors else set()
    groups: dict[str, dict] = {}

    for criterion in selection_criteria:
        key = criterion.normalized_criterion or _normalize_key(criterion.criterion_label or criterion.criterion_type)
        item = groups.setdefault(key, _empty_driver_row(key, criterion.criterion_label or criterion.criterion_type))
        item["selection_criterion_ids"].add(criterion.id)
        item["run_ids"].add(criterion.run_id)
        if criterion.criterion_used_for_selection:
            item["used_for_selection_run_ids"].add(criterion.run_id)
        if criterion.related_brand_name == target_name:
            item["target_brand_run_ids"].add(criterion.run_id)
        if criterion.related_brand_name in competitor_names:
            item["competitor_run_ids"].add(criterion.run_id)
        if len(item["examples"]) < 3 and criterion.answer_span:
            item["examples"].append(criterion.answer_span[:240])

    for reason in reason_claims:
        label = _reason_type_label(reason.reason_type)
        key = _normalize_key(label or reason.reason_type)
        item = groups.setdefault(key, _empty_driver_row(key, label))
        item["reason_claim_ids"].add(reason.id)
        item["run_ids"].add(reason.run_id)
        if reason.entity_name == target_name:
            item["target_brand_run_ids"].add(reason.run_id)
        if reason.entity_name in competitor_names:
            item["competitor_run_ids"].add(reason.run_id)
        if reason.entity_name:
            item["winner_entities"].add(reason.entity_name)
        if len(item["examples"]) < 3 and reason.reason_span:
            item["examples"].append(reason.reason_span[:240])

    capability_by_label: dict[str, list[BrandCapabilityClaim]] = defaultdict(list)
    for claim in capability_claims:
        label = claim.capability_label or claim.need_label
        if label:
            capability_by_label[_normalize_key(label)].append(claim)

    truth_by_key = {
        row.get("capability_key") or _normalize_key(row.get("capability_label", "")): row
        for row in product_truth.get("truths", [])
    }
    rows = []
    for key, item in groups.items():
        matching_capabilities = capability_by_label.get(key, [])
        target_capability_runs = {claim.run_id for claim in matching_capabilities if claim.brand_name == target_name and not claim.negation}
        competitor_capability_runs = {claim.run_id for claim in matching_capabilities if claim.brand_name in competitor_names and not claim.negation}
        item["target_brand_run_ids"].update(target_capability_runs)
        item["competitor_run_ids"].update(competitor_capability_runs)
        truth = truth_by_key.get(key) or _best_truth_for_driver(item["display_name"], truth_by_key)
        product_truth_status = truth.get("product_truth_status", "UNKNOWN") if truth else "UNKNOWN"
        ai_target_recognized = bool(item["target_brand_run_ids"])
        rows.append({
            "driver_key": key,
            "driver_label": item["display_name"],
            "supporting_run_count": len(item["run_ids"]),
            "supporting_runs": sorted(item["run_ids"])[:12],
            "used_for_selection": _metric("driver_used_for_selection_rate", len(item["used_for_selection_run_ids"]), run_count, run_count),
            "target_brand_observed": _metric("driver_target_brand_observed_rate", len(item["target_brand_run_ids"]), run_count, run_count),
            "competitor_observed": _metric("driver_competitor_observed_rate", len(item["competitor_run_ids"]), run_count, run_count),
            "winner_entities": sorted(item["winner_entities"])[:8],
            "selection_criterion_ids": sorted(item["selection_criterion_ids"])[:20],
            "reason_claim_ids": sorted(item["reason_claim_ids"])[:20],
            "examples": item["examples"][:3],
            "driver_strength": _driver_strength(len(item["run_ids"]), run_count),
            "product_truth_status": product_truth_status,
            "product_truth_status_label": PRODUCT_TRUTH_STATUS_LABELS.get(product_truth_status, product_truth_status),
            "product_truth": truth or None,
            "ai_observed_target_status": "RECOGNIZED" if ai_target_recognized else "NOT_RECOGNIZED",
            "diagnostic_signal": _driver_diagnostic_signal(product_truth_status, ai_target_recognized),
        })
    return {
        "schema_version": PROMPT_DRIVER_AGGREGATION_VERSION,
        "rows": sorted(rows, key=lambda row: (-row["supporting_run_count"], row["driver_label"]))[:20],
        "raw_reason_count": len(reason_claims),
        "raw_selection_criterion_count": len(selection_criteria),
        "boundary_note": "驱动来自推荐理由、选择标准和能力识别的聚合，不是词频榜；Product Truth 只用于目标品牌事实闸门。",
    }


def _empty_driver_row(key: str, display_name: str) -> dict:
    return {
        "driver_key": key,
        "display_name": display_name,
        "run_ids": set(),
        "used_for_selection_run_ids": set(),
        "target_brand_run_ids": set(),
        "competitor_run_ids": set(),
        "winner_entities": set(),
        "selection_criterion_ids": set(),
        "reason_claim_ids": set(),
        "examples": [],
    }


def _build_prompt_source_content_pattern(
    db: Session,
    runs: list[BrowserMonitorRun],
    evidence_adoptions: list[DecisionEvidenceAdoption],
) -> dict:
    run_ids = [run.id for run in runs]
    run_count = len(run_ids)
    refs = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).order_by(ReferenceSource.run_id, ReferenceSource.reference_index).all() if run_ids else []
    grouped: dict[str, dict] = {}
    cited_run_ids = set()
    for ref in refs:
        cited_run_ids.add(ref.run_id)
        content_type = _source_content_type(ref)
        row = grouped.setdefault(content_type, {
            "content_type": content_type,
            "content_type_label": _source_content_type_label(content_type),
            "occurrence_count": 0,
            "run_ids": set(),
            "domains": set(),
            "representative_sources": [],
        })
        row["occurrence_count"] += 1
        row["run_ids"].add(ref.run_id)
        if ref.domain:
            row["domains"].add(ref.domain)
        if len(row["representative_sources"]) < 3:
            row["representative_sources"].append({
                "reference_id": ref.id,
                "title": ref.display_title or ref.matched_title or ref.url,
                "url": ref.canonical_url or ref.url,
                "domain": ref.domain,
                "run_id": ref.run_id,
            })
    rows = []
    for row in grouped.values():
        rows.append({
            "content_type": row["content_type"],
            "content_type_label": row["content_type_label"],
            "occurrence_count": row["occurrence_count"],
            "citation_run_count": len(row["run_ids"]),
            "citation_coverage": _metric(f"source_pattern_{row['content_type']}_coverage", len(row["run_ids"]), run_count, run_count),
            "domains": sorted(row["domains"])[:10],
            "representative_sources": row["representative_sources"],
        })
    cited_context_runs = {item.run_id for item in evidence_adoptions if item.cited}
    selection_context_runs = {item.run_id for item in evidence_adoptions if item.associated_with_selection_reason}
    return {
        "schema_version": PROMPT_SOURCE_PATTERN_VERSION,
        "metrics": {
            "citation_presence_rate": _metric("citation_presence_rate", len(cited_run_ids), run_count, run_count),
            "citation_context_rate": _metric("citation_context_rate", len(cited_context_runs), run_count, run_count),
            "selection_reason_context_rate": _metric("selection_reason_context_rate", len(selection_context_runs), run_count, run_count),
            "citation_occurrence_count": len(refs),
        },
        "rows": sorted(rows, key=lambda row: (-row["citation_run_count"], -row["occurrence_count"], row["content_type_label"])),
        "boundary_note": "这里只描述最终引用来源和正文/段落证据形态；RetrievalCandidate 不是 ReferenceSource 的上游漏斗，除非候选覆盖完整且另行声明。",
    }


def _build_prompt_intervention_feasibility(
    run_eligibility: dict,
    gaps: list[dict],
    product_truth: dict,
) -> dict:
    unknown_truths = [row for row in product_truth.get("truths", []) if row.get("product_truth_status") == "UNKNOWN"]
    if (run_eligibility or {}).get("analysis_usable_runs", 0) == 0:
        status = "BLOCKED_RUN_ELIGIBILITY"
        reasons = ["没有符合单 Prompt 独立采样要求的可分析记录。"]
    elif unknown_truths:
        status = "BLOCKED_PRODUCT_TRUTH"
        reasons = ["Product Truth 未确认，不能生成确定性执行策略。"]
    elif not gaps:
        status = "NO_ACTION"
        reasons = ["当前没有结构化缺口支撑干预。"]
    else:
        status = "READY_FOR_HUMAN_REVIEW"
        reasons = ["可以生成待审核策略候选，但仍需人工确认渠道、资产和 target_url。"]
    return {
        "status": status,
        "status_label": {
            "BLOCKED_RUN_ELIGIBILITY": "采样资格不足",
            "BLOCKED_PRODUCT_TRUTH": "产品事实未确认",
            "NO_ACTION": "暂不行动",
            "READY_FOR_HUMAN_REVIEW": "可进入人工策略审核",
        }.get(status, status),
        "reasons": reasons,
        "unknown_capabilities": unknown_truths[:8],
        "boundary_note": "干预候选不是执行命令；只有人工审核后的 effective_payload=VALIDATED 才能物化 Action/Experiment。",
    }


def _build_prompt_intervention_candidates(
    project: Project | None,
    prompt: Prompt | None,
    gaps: list[dict],
    target_brand_position: dict,
    drivers: dict,
    source_pattern: dict,
    feasibility: dict,
) -> list[dict]:
    brand_name = project.brand_name if project else "目标品牌"
    prompt_text = prompt.prompt_text if prompt else "当前问题"
    if feasibility.get("status") == "NO_ACTION" or not gaps:
        return [{
            "schema_version": PROMPT_INTERVENTION_CANDIDATE_VERSION,
            "intervention_type": "NO_ACTION",
            "intervention_type_label": INTERVENTION_TYPE_LABELS["NO_ACTION"],
            "feasibility_status": feasibility.get("status"),
            "priority": "LOW",
            "reason": "当前单 Prompt 没有足够明确的结构化缺口。",
            "evidence_prerequisites": INTERVENTION_PREREQUISITES["NO_ACTION"],
            "target_platform": "UNRESOLVED",
            "target_asset": "UNRESOLVED",
            "target_url": "",
        }]
    primary_gap = gaps[0]
    intervention_type = _intervention_type_for_gap(primary_gap.get("gap_type", "UNKNOWN"))
    top_drivers = drivers.get("rows", [])[:5]
    top_source_patterns = source_pattern.get("rows", [])[:3]
    return [{
        "schema_version": PROMPT_INTERVENTION_CANDIDATE_VERSION,
        "intervention_type": intervention_type,
        "intervention_type_label": INTERVENTION_TYPE_LABELS.get(intervention_type, intervention_type),
        "feasibility_status": feasibility.get("status"),
        "priority": primary_gap.get("severity", "MEDIUM"),
        "target_brand": brand_name,
        "prompt_id": prompt.id if prompt else None,
        "prompt_text": prompt_text,
        "primary_gap_type": primary_gap.get("gap_type"),
        "primary_gap_type_label": primary_gap.get("gap_type_label"),
        "observed_problem": primary_gap.get("diagnosis_text", ""),
        "recommended_direction": primary_gap.get("action_hint", ""),
        "target_platform": "UNRESOLVED",
        "target_asset": "UNRESOLVED",
        "target_url": "",
        "suggested_target_url": "",
        "suggested_target_url_note": "不因项目配置了官网就默认选择官网；target_url 需由人工基于证据、渠道和资产确认。",
        "evidence_basis": {
            "target_brand_position": target_brand_position.get("status"),
            "drivers": [{
                "driver_key": row.get("driver_key"),
                "driver_label": row.get("driver_label"),
                "supporting_run_count": row.get("supporting_run_count"),
                "product_truth_status": row.get("product_truth_status"),
                "diagnostic_signal": row.get("diagnostic_signal"),
            } for row in top_drivers],
            "source_patterns": [{
                "content_type": row.get("content_type"),
                "content_type_label": row.get("content_type_label"),
                "citation_run_count": row.get("citation_run_count"),
            } for row in top_source_patterns],
            "gap_metric": primary_gap.get("metric"),
        },
        "evidence_prerequisites": INTERVENTION_PREREQUISITES.get(intervention_type, []),
        "execution_boundary": "StrategyCandidate -> 人工审核 -> effective_payload=VALIDATED -> Action -> Experiment；平台短名单只来自证据线索，尚未完成可控性、平台执行性、内容适配和边际机会评估。",
    }]


def _best_truth_for_driver(display_name: str, truth_by_key: dict[str, dict]) -> dict | None:
    key = _normalize_key(display_name)
    for truth_key, truth in truth_by_key.items():
        if not truth_key:
            continue
        if truth_key in key or key in truth_key:
            return truth
    return None


def _driver_strength(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "UNKNOWN"
    rate = numerator / denominator
    if denominator < 3:
        return "INSUFFICIENT_SAMPLE"
    if rate >= 0.6:
        return "HIGH"
    if rate >= 0.3:
        return "MEDIUM"
    if rate > 0:
        return "LOW"
    return "UNKNOWN"


def _driver_diagnostic_signal(product_truth_status: str, ai_target_recognized: bool) -> str:
    if product_truth_status in {"SUPPORTED", "PARTIALLY_SUPPORTED"} and not ai_target_recognized:
        return "TRUE_CAPABILITY_NOT_RECOGNIZED_BY_AI"
    if product_truth_status == "NOT_SUPPORTED":
        return "DO_NOT_CLAIM_UNSUPPORTED_CAPABILITY"
    if product_truth_status == "UNKNOWN":
        return "NEEDS_PRODUCT_TRUTH_REVIEW"
    return "NO_GAP_ON_THIS_DRIVER" if ai_target_recognized else "NO_TARGET_AI_ASSOCIATION"


def _source_content_type(ref: ReferenceSource) -> str:
    text = " ".join([ref.display_title or "", ref.matched_title or "", ref.url or ""])
    lowered = text.lower()
    if any(keyword in text for keyword in ["教程", "步骤", "怎么", "如何", "设置"]):
        return "TUTORIAL"
    if any(keyword in text for keyword in ["常见问题", "FAQ", "问答"]):
        return "FAQ"
    if any(keyword in text for keyword in ["对比", "比较", "区别", "哪个好"]):
        return "COMPARISON"
    if any(keyword in text for keyword in ["文档", "帮助中心", "说明"]):
        return "DOCUMENTATION"
    if any(keyword in text for keyword in ["首页", "官网"]) or lowered.rstrip("/").endswith((".com", ".cn", ".net")):
        return "HOMEPAGE"
    if any(keyword in text for keyword in ["新闻", "公告", "资讯"]):
        return "NEWS"
    return "ARTICLE_OR_PAGE"


def _source_content_type_label(content_type: str) -> str:
    return {
        "TUTORIAL": "教程/步骤",
        "FAQ": "FAQ/问答",
        "COMPARISON": "对比内容",
        "DOCUMENTATION": "文档/帮助中心",
        "HOMEPAGE": "首页/官网",
        "NEWS": "新闻/公告",
        "ARTICLE_OR_PAGE": "文章/普通页面",
    }.get(content_type, content_type)


def _intervention_type_for_gap(gap_type: str) -> str:
    if gap_type in {"ASSOCIATION_GAP", "CAPABILITY_RECOGNITION_GAP", "CANDIDATE_INCLUSION_GAP", "RECOMMENDATION_GAP", "TOP_RECOMMENDATION_GAP"}:
        return "CONTENT_CREATE"
    if gap_type in {"ENTITY_GAP"}:
        return "ENTITY_CONSISTENCY"
    if gap_type in {"RETRIEVAL_GAP"}:
        return "TECHNICAL_INDEXABILITY"
    if gap_type in {"CITATION_GAP", "SOURCE_TOPOLOGY_GAP"}:
        return "PLATFORM_AUTHORITY_BUILD"
    return "CONTENT_CREATE"


def _target_stage_label(stage: str) -> str:
    return {
        "TOP_RECOMMENDED": "第一推荐",
        "EXPLICITLY_RECOMMENDED": "明确推荐",
        "SOLUTION_CANDIDATE": "进入候选",
        "CAPABILITY_RECOGNIZED": "能力被识别",
        "NEED_ASSOCIATED": "需求已关联",
        "MENTIONED": "仅被提及",
        "ABSENT": "未出现",
        "UNKNOWN": "未知",
    }.get(stage, stage)


def _prioritize_primary_gap(gaps: list[dict], product_truth: dict) -> list[dict]:
    if not gaps:
        return []
    priority = {
        "INTENT_FIT_GAP": 0,
        "ASSOCIATION_GAP": 1,
        "CAPABILITY_RECOGNITION_GAP": 2,
        "CANDIDATE_INCLUSION_GAP": 3,
        "RECOMMENDATION_GAP": 4,
        "TOP_RECOMMENDATION_GAP": 5,
        "SELECTION_REASON_GAP": 20,
        "EVIDENCE_GAP": 21,
    }
    sorted_gaps = sorted(gaps, key=lambda gap: priority.get(gap.get("gap_type"), 99))
    for index, gap in enumerate(sorted_gaps):
        is_primary = index == 0 and gap.get("gap_type") in {
            "INTENT_FIT_GAP",
            "ASSOCIATION_GAP",
            "CAPABILITY_RECOGNITION_GAP",
            "CANDIDATE_INCLUSION_GAP",
            "RECOMMENDATION_GAP",
            "TOP_RECOMMENDATION_GAP",
        }
        gap["gap_role"] = "PRIMARY" if is_primary else "CONTRIBUTING"
        gap["gap_role_label"] = "最前置缺口" if is_primary else "辅助缺口"
        if index == 0:
            gap.setdefault("diagnosis_basis", {})["product_truth_boundary"] = product_truth.get("boundary_note", "")
    return sorted_gaps[:3]


def _issue_severity_from_gap(severity: str) -> int:
    return {"HIGH": 4, "MEDIUM": 3, "LOW": 2}.get(severity, 3)


def _confidence_level(confidence: float) -> str:
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.55:
        return "medium"
    return "low"


def _derive_gap_reads(
    project: Project | None,
    brand_funnel: dict,
    criteria_market: dict,
    evidence_market: dict,
    solution_slot: dict,
    brand_opportunity_gate: dict,
    product_truth: dict,
) -> list[dict]:
    if not project:
        return []
    target = next((row for row in brand_funnel.get("rows", []) if row.get("brand_name") == project.brand_name), None)
    if not target:
        return []

    gaps: list[dict] = []
    solution_metric = solution_slot.get("solution_slot_metric", _metric("solution_slot_rate", 0, 0, 0))
    if brand_opportunity_gate.get("opportunity_level") in {"NO_BRAND_OPPORTUNITY", "LOW_BRAND_OPPORTUNITY"}:
        gaps.append(_gap_read(
            "INTENT_FIT_GAP",
            "LOW",
            0.62,
            solution_metric,
            "当前问题没有稳定品牌选择空间，停止输出后续品牌差距，避免误诊。",
            "先补更多样本，或把问题拆成更明确的工具/平台/品牌选择问题。",
            diagnosis_basis={"brand_opportunity_gate": brand_opportunity_gate},
        ))
        return gaps

    association_metric = target["metrics"]["need_association_rate"]
    capability_metric = target["metrics"]["capability_recognition_rate"]
    candidate_metric = target["metrics"]["candidate_capture_rate"]
    recommendation_metric = target["metrics"]["explicit_recommendation_rate"]
    evidence_metric = evidence_market.get("metrics", {}).get("evidence_link_rate", _metric("evidence_link_rate", 0, 0, 0))
    target_criteria_runs = criteria_market.get("target_used_selection_run_count", 0)

    if association_metric["numerator"] == 0:
        gaps.append(_gap_read(
            "ASSOCIATION_GAP",
            "HIGH",
            0.78,
            association_metric,
            f"「{project.brand_name}」没有稳定绑定到当前问题的核心需求。",
            "优先补品牌与需求场景的中文说明，而不是直接写推荐榜单。",
            supporting_run_ids=target.get("brand_mention_run_ids", []),
            counterexample_run_ids=target.get("need_association_run_ids", []),
        ))
    if association_metric["numerator"] > 0 and capability_metric["numerator"] == 0:
        gaps.append(_gap_read(
            "CAPABILITY_RECOGNITION_GAP",
            "HIGH",
            0.76,
            capability_metric,
            f"「{project.brand_name}」即使被提到，也没有被稳定识别出可承接能力。",
            "补充明确能力句：支持什么场景、怎么做、边界是什么、凭什么可信。",
            supporting_run_ids=target.get("need_association_run_ids", []),
            counterexample_run_ids=target.get("capability_recognized_run_ids", []),
        ))
    if candidate_metric["numerator"] == 0 and solution_slot.get("solution_required") in {"REQUIRED", "OPTIONAL"}:
        gaps.append(_gap_read(
            "CANDIDATE_INCLUSION_GAP",
            "HIGH",
            0.72,
            candidate_metric,
            f"当前回答存在方案槽位，但「{project.brand_name}」没有稳定进入候选。",
            "先争取进入候选集合，再讨论明确推荐或第一推荐。",
            supporting_run_ids=solution_slot.get("solution_slot_run_ids", []),
            counterexample_run_ids=target.get("candidate_run_ids", []),
        ))
    if criteria_market.get("criteria") and target_criteria_runs == 0:
        gaps.append(_gap_read(
            "SELECTION_REASON_GAP",
            "MEDIUM",
            0.68,
            _metric("target_selection_reason_usage_rate", 0, len(criteria_market.get("criteria", [])), len(criteria_market.get("criteria", []))),
            f"答案已经出现选择标准，但这些标准没有稳定落到「{project.brand_name}」。",
            "围绕高频选择标准补充可核验证据，例如合规、稳定、微信兼容、数据追踪。",
        ))
    if evidence_metric["numerator"] == 0:
        gaps.append(_gap_read(
            "EVIDENCE_GAP",
            "MEDIUM",
            0.64,
            evidence_metric,
            "当前引用资料与品牌能力/选择理由的可审核关联不足。",
            "以引用资料分析为主，先补可公开访问、可引用、可抽取的产品事实页和 FAQ；检索候选只看重合度，不当作上游漏斗。",
        ))
    if recommendation_metric["numerator"] == 0:
        gaps.append(_gap_read(
            "RECOMMENDATION_GAP",
            "LOW" if not brand_funnel.get("recommendation_primary_metric") else "MEDIUM",
            0.58,
            recommendation_metric,
            "当前没有形成明确推荐；对当前这类信息/操作问题，这不是首要失败点。",
            "先完成前置链路：需求关联、能力识别、候选进入。",
        ))
    top_metric = target["metrics"].get("top_recommendation_rate", _metric("top_recommendation_rate", 0, 0, 0))
    if recommendation_metric["numerator"] > 0 and top_metric["numerator"] == 0:
        gaps.append(_gap_read(
            "TOP_RECOMMENDATION_GAP",
            "LOW",
            0.52,
            top_metric,
            f"「{project.brand_name}」已经出现明确推荐，但尚未稳定成为第一推荐。",
            "只有在候选进入和明确推荐稳定后，再优化第一推荐位置。",
        ))
    return _prioritize_primary_gap(gaps, product_truth)


def _gap_read(
    gap_type: str,
    severity: str,
    confidence: float,
    metric: dict,
    diagnosis_text: str,
    action_hint: str,
    supporting_run_ids: list[int] | None = None,
    counterexample_run_ids: list[int] | None = None,
    supporting_claim_ids: list[int] | None = None,
    supporting_evidence_ids: list[int] | None = None,
    diagnosis_basis: dict | None = None,
) -> dict:
    return {
        "gap_type": gap_type,
        "gap_type_label": _gap_type_label(gap_type),
        "severity": severity,
        "severity_label": _severity_label(severity),
        "confidence": confidence,
        "metric": metric,
        "supporting_run_ids": supporting_run_ids or [],
        "counterexample_run_ids": counterexample_run_ids or [],
        "supporting_claim_ids": supporting_claim_ids or [],
        "supporting_evidence_ids": supporting_evidence_ids or [],
        "diagnosis_basis": diagnosis_basis or {},
        "diagnosis_text": diagnosis_text,
        "action_hint": action_hint,
    }


def _classify_prompt_intents(prompt_text: str, runs: list[BrowserMonitorRun]) -> list[dict]:
    prompt_only = prompt_text or ""
    text = " ".join([prompt_only, *[(run.answer_text or "")[:600] for run in runs[:8]]])
    rules = [
        ("HOW_TO", ["怎么", "如何", "步骤", "教程", "设置", "制作", "方法", "操作"], text),
        ("SOLUTION_SEEKING", ["工具", "方案", "平台", "第三方", "短链", "外链", "卡片"], text),
        ("COMMERCIAL_INVESTIGATION", ["哪家", "哪个好", "推荐", "价格", "收费", "对比"], prompt_only),
        ("COMPARISON", ["对比", "比较", "区别", "优缺点"], prompt_only),
        ("BRAND_NAVIGATION", ["官网", "入口", "登录", "下载"], prompt_only),
        ("TRANSACTIONAL", ["购买", "下单", "开通", "套餐"], prompt_only),
    ]
    matched = []
    for intent, keywords, source_text in rules:
        hits = sorted({keyword for keyword in keywords if keyword in source_text})
        if hits:
            matched.append({
                "intent": intent,
                "intent_label": INTENT_LABELS[intent],
                "matched_keywords": hits,
                "confidence": 0.72 if intent in {"HOW_TO", "SOLUTION_SEEKING"} else 0.62,
            })
    if not matched:
        matched.append({
            "intent": "INFORMATIONAL",
            "intent_label": INTENT_LABELS["INFORMATIONAL"],
            "matched_keywords": [],
            "confidence": 0.66,
        })
    elif not any(item["intent"] == "INFORMATIONAL" for item in matched):
        matched.insert(0, {
            "intent": "INFORMATIONAL",
            "intent_label": INTENT_LABELS["INFORMATIONAL"],
            "matched_keywords": [],
            "confidence": 0.55,
        })
    return matched[:4]


def _primary_metric_note(intents: list[dict]) -> str:
    values = {item["intent"] for item in intents}
    if values & {"COMMERCIAL_INVESTIGATION", "COMPARISON"}:
        return "当前问题包含商业/对比意图，可观察候选进入、明确推荐和第一推荐。"
    if values & {"HOW_TO", "SOLUTION_SEEKING", "INFORMATIONAL"}:
        return "当前问题偏信息、操作和方案寻找；主指标应优先看方案槽位、需求关联、能力识别和候选进入，推荐率仅作诊断。"
    return "当前意图不足以稳定指定主指标，需补样本或人工复核。"


def _build_choice_slot(
    prompt_text: str,
    runs: list[BrowserMonitorRun],
    landscape: list[dict],
    semantic_facts: list[AnswerSemanticFact],
) -> dict:
    fact_run_ids = {fact.run_id for fact in semantic_facts if fact.fact_type == "has_choice_slot" and fact.fact_value}
    run_ids = []
    specificity_counts = defaultdict(int)
    recommendation_runs = set()
    for run in runs:
        answer = run.answer_text or ""
        if run.id in fact_run_ids or _answer_has_choice_slot(prompt_text, answer, [])[0]:
            run_ids.append(run.id)
        specificity_counts[_solution_specificity(answer, landscape)] += 1
        if any(kw in answer for kw in ["推荐", "建议使用", "首选", "优先考虑"]):
            recommendation_runs.add(run.id)

    run_count = len(runs)
    if not run_count:
        required = "UNKNOWN"
    elif len(run_ids) / run_count >= 0.5:
        required = "REQUIRED"
    elif run_ids:
        required = "OPTIONAL"
    else:
        required = "NONE"
    specificity = max(specificity_counts.items(), key=lambda item: item[1])[0] if specificity_counts else "UNKNOWN"
    return {
        "choice_slot_status": required,
        "choice_slot_status_label": SOLUTION_REQUIRED_LABELS[required],
        "solution_required": required,
        "solution_required_label": SOLUTION_REQUIRED_LABELS[required],
        "solution_specificity": specificity,
        "solution_specificity_label": SOLUTION_SPECIFICITY_LABELS.get(specificity, specificity),
        "recommendation_present": bool(recommendation_runs),
        "recommendation_run_ids": sorted(recommendation_runs),
        "choice_slot_run_ids": run_ids,
        "solution_slot_run_ids": run_ids,
        "choice_slot_metric": _metric("choice_slot_rate", len(run_ids), run_count, run_count),
        "solution_slot_metric": _metric("choice_slot_rate", len(run_ids), run_count, run_count),
        "basis": "严格按可替代选择性判断：答案中需要存在多个可替代实体、产品、品牌、服务、平台或方案之间的主动选择空间。",
    }


def _build_need_market(prompt_text: str, runs: list[BrowserMonitorRun]) -> list[dict]:
    rows = []
    for label, keywords in NEED_RULES:
        run_ids = []
        examples = []
        for run in runs:
            for sentence in _split_answer(" ".join([prompt_text or "", run.answer_text or ""])):
                if all(keyword in sentence for keyword in keywords) or any(keyword in sentence for keyword in keywords):
                    run_ids.append(run.id)
                    if len(examples) < 3 and sentence not in examples:
                        examples.append(sentence[:220])
                    break
        if run_ids:
            rows.append({
                "need_label": label,
                "need_type": "NEED",
                "run_count": len(set(run_ids)),
                "run_ids": sorted(set(run_ids))[:12],
                "coverage": _metric(f"need_{_normalize_key(label)}_coverage", len(set(run_ids)), len(runs), len(runs)),
                "examples": examples,
            })
    return sorted(rows, key=lambda row: (-row["run_count"], row["need_label"]))


def _build_solution_object_market(runs: list[BrowserMonitorRun]) -> list[dict]:
    rows = []
    for key, label, keywords in SOLUTION_OBJECT_RULES:
        run_ids = set()
        examples = []
        for run in runs:
            for sentence in _split_answer(run.answer_text or ""):
                if any(keyword in sentence for keyword in keywords):
                    run_ids.add(run.id)
                    if len(examples) < 3:
                        examples.append(sentence[:220])
                    break
        if run_ids:
            rows.append({
                "solution_object": key,
                "solution_object_label": label,
                "run_count": len(run_ids),
                "run_ids": sorted(run_ids)[:12],
                "coverage": _metric(f"solution_object_{key}_coverage", len(run_ids), len(runs), len(runs)),
                "examples": examples,
            })
    return sorted(rows, key=lambda row: (-row["run_count"], row["solution_object_label"]))


def _build_selection_criteria_market(
    project: Project | None,
    criteria: list[DecisionSelectionCriterion],
    run_count: int,
) -> dict:
    target_name = project.brand_name if project else ""
    competitor_names = {competitor.name for competitor in project.competitors} if project and project.competitors else set()
    grouped: dict[str, list[DecisionSelectionCriterion]] = defaultdict(list)
    for criterion in criteria:
        grouped[criterion.normalized_criterion or criterion.criterion_type].append(criterion)

    rows = []
    target_used_runs = set()
    for _, items in grouped.items():
        appearing_runs = {item.run_id for item in items if item.criterion_present}
        used_runs = {item.run_id for item in items if item.criterion_used_for_selection}
        target_runs = {item.run_id for item in items if item.related_brand_name == target_name}
        competitor_runs = {item.run_id for item in items if item.related_brand_name in competitor_names}
        target_used_runs.update(target_runs & used_runs)
        rows.append({
            "criterion_type": items[0].criterion_type,
            "criterion_label": items[0].criterion_label,
            "appearing_run_count": len(appearing_runs),
            "appearing_run_ids": sorted(appearing_runs)[:12],
            "used_for_selection_run_count": len(used_runs),
            "used_for_selection_run_ids": sorted(used_runs)[:12],
            "usage_rate": _metric(f"criterion_{items[0].criterion_type.lower()}_usage_rate", len(used_runs), run_count, run_count),
            "related_brands": sorted({item.related_brand_name for item in items if item.related_brand_name}),
            "target_coverage": _metric(f"target_{items[0].criterion_type.lower()}_coverage", len(target_runs), run_count, run_count),
            "competitor_coverage": _metric(f"competitor_{items[0].criterion_type.lower()}_coverage", len(competitor_runs), run_count, run_count),
            "examples": [item.answer_span for item in items[:3]],
            "items": [selection_criterion_to_read(item) for item in items[:8]],
        })
    return {
        "criteria": sorted(rows, key=lambda row: (-row["used_for_selection_run_count"], -row["appearing_run_count"], row["criterion_label"])),
        "raw_count": len(criteria),
        "target_used_selection_run_count": len(target_used_runs),
        "review_status_note": "选择标准为规则抽取，关键标准需要人工确认。",
    }


def _build_brand_funnel(
    project: Project | None,
    landscape: list[dict],
    claims: list[RecommendationClaim],
    capability_claims: list[BrandCapabilityClaim],
    solution_slot: dict,
    run_count: int,
) -> dict:
    if not project:
        return {"rows": [], "recommendation_primary_metric": False}
    brand_names = [project.brand_name]
    brand_names.extend([row["entity_name"] for row in landscape if row["entity_name"] != project.brand_name])
    seen_names = []
    for name in brand_names:
        if name and name not in seen_names:
            seen_names.append(name)

    landscape_by_name = {row["entity_name"]: row for row in landscape}
    claims_by_brand = defaultdict(list)
    for claim in claims:
        claims_by_brand[claim.entity_name].append(claim)
    capability_by_brand = defaultdict(list)
    for claim in capability_claims:
        capability_by_brand[claim.brand_name].append(claim)

    eligible_denominator = len(solution_slot.get("solution_slot_run_ids", [])) or run_count
    rows = []
    for brand_name in seen_names:
        row = landscape_by_name.get(brand_name, {})
        brand_claims = claims_by_brand.get(brand_name, [])
        mention_runs = {claim.run_id for claim in brand_claims} or set(row.get("representative_run_ids", []))
        need_assoc_runs = {claim.run_id for claim in brand_claims if _sentence_has_need(claim.answer_span)}
        capability_runs = {claim.run_id for claim in capability_by_brand.get(brand_name, []) if not claim.negation}
        candidate_runs = {claim.run_id for claim in brand_claims if claim.recommendation_type in {"CANDIDATE", "POSITIVE_RECOMMENDATION", "TOP_RECOMMENDATION"}}
        explicit_runs = {claim.run_id for claim in brand_claims if claim.recommendation_type in {"POSITIVE_RECOMMENDATION", "TOP_RECOMMENDATION"}}
        top_runs = {claim.run_id for claim in brand_claims if claim.recommendation_type == "TOP_RECOMMENDATION"}
        negative_runs = {claim.run_id for claim in brand_claims if claim.recommendation_type == "NEGATIVE_RECOMMENDATION"}
        rows.append({
            "brand_name": brand_name,
            "is_target_brand": brand_name == project.brand_name,
            "brand_mention_run_ids": sorted(mention_runs),
            "need_association_run_ids": sorted(need_assoc_runs),
            "capability_recognized_run_ids": sorted(capability_runs),
            "candidate_run_ids": sorted(candidate_runs),
            "explicit_recommendation_run_ids": sorted(explicit_runs),
            "top_recommendation_run_ids": sorted(top_runs),
            "negative_recommendation_run_ids": sorted(negative_runs),
            "metrics": {
                "mention_rate": _metric("mention_rate", len(mention_runs), run_count, run_count),
                "need_association_rate": _metric("need_association_rate", len(need_assoc_runs), run_count, run_count),
                "capability_recognition_rate": _metric("capability_recognition_rate", len(capability_runs), run_count, run_count),
                "candidate_overall_rate": _metric("candidate_overall_rate", len(candidate_runs), run_count, run_count),
                "candidate_capture_rate": _metric("candidate_capture_rate", len(candidate_runs), eligible_denominator, eligible_denominator, sample_size=run_count),
                "recognized_to_candidate_rate": _metric("recognized_to_candidate_rate", len(candidate_runs & capability_runs), len(capability_runs), len(capability_runs), sample_size=run_count),
                "explicit_recommendation_rate": _metric("explicit_recommendation_rate", len(explicit_runs), run_count, run_count),
                "top_recommendation_rate": _metric("top_recommendation_rate", len(top_runs), run_count, run_count),
                "negative_recommendation_rate": _metric("negative_recommendation_rate", len(negative_runs), run_count, run_count),
            },
            "atomic_facts": {
                "brand_mentioned": bool(mention_runs),
                "need_associated": bool(need_assoc_runs),
                "capability_recognized": bool(capability_runs),
                "solution_candidate": bool(candidate_runs),
                "explicitly_recommended": bool(explicit_runs),
                "top_recommended": bool(top_runs),
                "negative_recommendation": bool(negative_runs),
                "constraint_present": any(claim.negation for claim in capability_by_brand.get(brand_name, [])),
            },
            "derived_stage": _derive_funnel_stage(mention_runs, need_assoc_runs, capability_runs, candidate_runs, explicit_runs, top_runs),
        })
    return {
        "recommendation_primary_metric": bool(solution_slot.get("recommendation_present")),
        "rows": rows,
        "metric_format_note": "所有 rate 均保留 numerator、denominator、eligible_denominator、sample_size，避免裸百分比误导。",
    }


def _build_capability_market(capability_claims: list[BrandCapabilityClaim]) -> dict:
    rows = []
    grouped: dict[tuple[str, str], list[BrandCapabilityClaim]] = defaultdict(list)
    for claim in capability_claims:
        grouped[(claim.brand_name, claim.capability_label or claim.need_label)].append(claim)
    for (brand_name, capability), items in grouped.items():
        run_ids = {item.run_id for item in items}
        rows.append({
            "brand_name": brand_name,
            "capability_label": capability,
            "need_labels": sorted({item.need_label for item in items if item.need_label}),
            "predicate": items[0].predicate,
            "run_count": len(run_ids),
            "run_ids": sorted(run_ids)[:12],
            "examples": [item.answer_span for item in items[:3]],
            "claims": [capability_claim_to_read(item) for item in items[:8]],
        })
    return {
        "claims": sorted(rows, key=lambda row: (-row["run_count"], row["brand_name"], row["capability_label"])),
        "raw_count": len(capability_claims),
        "review_status_note": "能力识别为回答样本中的观察事实，不等同于产品真实能力。",
    }


def _build_citation_source_analysis(db: Session, runs: list[BrowserMonitorRun]) -> dict:
    run_ids = [run.id for run in runs]
    run_count = len(run_ids)
    if not run_ids:
        return {
            "metrics": {},
            "top_domains": [],
            "top_sources": [],
            "boundary_note": "当前没有可分析的引用资料。",
        }

    refs = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).order_by(ReferenceSource.run_id, ReferenceSource.reference_index).all()
    candidates = db.query(RetrievalCandidate).filter(RetrievalCandidate.run_id.in_(run_ids)).all()
    candidate_urls_by_run: dict[int, set[str]] = defaultdict(set)
    for candidate in candidates:
        url = _canonical_compare_url(candidate.canonical_url or candidate.url)
        if url:
            candidate_urls_by_run[candidate.run_id].add(url)

    domains: dict[str, dict] = {}
    sources: dict[str, dict] = {}
    cited_run_ids = set()
    overlap_run_ids = set()
    all_refs_subset_run_ids = set()
    refs_by_run: dict[int, list[ReferenceSource]] = defaultdict(list)
    for ref in refs:
        refs_by_run[ref.run_id].append(ref)

    for run_id, run_refs in refs_by_run.items():
        ref_urls = {_canonical_compare_url(ref.canonical_url or ref.url) for ref in run_refs if _canonical_compare_url(ref.canonical_url or ref.url)}
        candidate_urls = candidate_urls_by_run.get(run_id, set())
        if ref_urls:
            cited_run_ids.add(run_id)
        if ref_urls & candidate_urls:
            overlap_run_ids.add(run_id)
        if ref_urls and candidate_urls and ref_urls.issubset(candidate_urls):
            all_refs_subset_run_ids.add(run_id)

    for ref in refs:
        url = _canonical_compare_url(ref.canonical_url or ref.url)
        display_url = ref.canonical_url or ref.url
        if display_url:
            key = url or display_url
            source = sources.setdefault(key, {
                "url": display_url,
                "title": ref.display_title or ref.matched_title or display_url,
                "domain": ref.domain,
                "occurrence_count": 0,
                "run_ids": set(),
                "reference_indices": [],
                "retrieval_overlap_run_ids": set(),
            })
            source["occurrence_count"] += 1
            source["run_ids"].add(ref.run_id)
            source["reference_indices"].append(ref.reference_index)
            if url and url in candidate_urls_by_run.get(ref.run_id, set()):
                source["retrieval_overlap_run_ids"].add(ref.run_id)

        domain_key = ref.domain or urlparse(display_url or "").netloc.lower() or "未知来源"
        domain = domains.setdefault(domain_key, {
            "domain": domain_key,
            "occurrence_count": 0,
            "run_ids": set(),
            "retrieval_overlap_run_ids": set(),
        })
        domain["occurrence_count"] += 1
        domain["run_ids"].add(ref.run_id)
        if url and url in candidate_urls_by_run.get(ref.run_id, set()):
            domain["retrieval_overlap_run_ids"].add(ref.run_id)

    top_domains = [{
        "domain": item["domain"],
        "occurrence_count": item["occurrence_count"],
        "run_count": len(item["run_ids"]),
        "run_ids": sorted(item["run_ids"])[:12],
        "retrieval_overlap_run_count": len(item["retrieval_overlap_run_ids"]),
    } for item in domains.values()]
    top_sources = [{
        "url": item["url"],
        "title": item["title"],
        "domain": item["domain"],
        "occurrence_count": item["occurrence_count"],
        "run_count": len(item["run_ids"]),
        "run_ids": sorted(item["run_ids"])[:12],
        "reference_indices": item["reference_indices"][:20],
        "retrieval_overlap_run_count": len(item["retrieval_overlap_run_ids"]),
    } for item in sources.values()]

    return {
        "metrics": {
            "cited_run_rate": _metric("cited_run_rate", len(cited_run_ids), run_count, run_count),
            "retrieval_overlap_rate": _metric("retrieval_overlap_rate", len(overlap_run_ids), run_count, run_count),
            "full_reference_in_retrieval_rate": _metric("full_reference_in_retrieval_rate", len(all_refs_subset_run_ids), run_count, run_count),
            "unique_citation_url_count": len(sources),
            "unique_citation_domain_count": len(domains),
            "citation_occurrence_count": len(refs),
        },
        "top_domains": sorted(top_domains, key=lambda row: (-row["run_count"], -row["occurrence_count"], row["domain"]))[:12],
        "top_sources": sorted(top_sources, key=lambda row: (-row["run_count"], -row["occurrence_count"], row["domain"], row["title"]))[:20],
        "boundary_note": "引用资料是主分析对象；检索候选只用于观察 URL 重合度。二者不是包含关系，不能硬画成检索到引用的漏斗。",
    }


def _build_evidence_adoption_market(adoptions: list[DecisionEvidenceAdoption], run_count: int) -> dict:
    linked_rows = [item for item in adoptions if item.evidence_status in {"LINKED", "PARTIALLY_LINKED"}]
    uncertain_rows = [item for item in adoptions if item.evidence_status == "UNCERTAIN"]
    selection_rows = [item for item in adoptions if item.associated_with_selection_reason]
    return {
        "metrics": {
            "retrieval_overlap_rate": _metric("retrieval_overlap_rate", len({item.run_id for item in adoptions if item.retrieved}), run_count, run_count),
            "retrieved_rate": _metric("retrieval_overlap_rate", len({item.run_id for item in adoptions if item.retrieved}), run_count, run_count),
            "citation_context_rate": _metric("citation_context_rate", len({item.run_id for item in adoptions if item.cited}), run_count, run_count),
            "evidence_link_rate": _metric("evidence_link_rate", len({item.run_id for item in linked_rows}), run_count, run_count),
            "evidence_uncertain_rate": _metric("evidence_uncertain_rate", len({item.run_id for item in uncertain_rows}), run_count, run_count),
            "selection_reason_context_rate": _metric("selection_reason_context_rate", len({item.run_id for item in selection_rows}), run_count, run_count),
        },
        "adoptions": [evidence_adoption_to_read(item) for item in adoptions[:30]],
        "raw_count": len(adoptions),
        "boundary_note": "这里是 Citation Context，不是证据支撑结论。Recommendation / Reason 与 Citation 在同一回答中共现，不等于 Citation 支撑该推荐理由；正文抓取并验证前只能标记 LINKED、PARTIALLY_LINKED、UNLINKED 或 UNCERTAIN。",
    }


def _build_action_package(
    project: Project | None,
    prompt: Prompt | None,
    solution_slot: dict,
    criteria_market: dict,
    brand_funnel: dict,
    evidence_market: dict,
    gaps: list[dict],
    product_truth: dict | None = None,
) -> dict:
    brand_name = project.brand_name if project else "目标品牌"
    prompt_text = prompt.prompt_text if prompt else "当前问题"
    primary_gap = gaps[0] if gaps else None
    criteria = [row["criterion_label"] for row in criteria_market.get("criteria", [])[:5]]
    target = next((row for row in brand_funnel.get("rows", []) if row.get("is_target_brand")), {})
    if solution_slot.get("solution_required") == "NONE":
        opportunity_type = "CONTENT_INFORMATION_OPPORTUNITY"
        asset_decision = "NO_CONTENT_ACTION"
    elif primary_gap and primary_gap.get("gap_type") == "ASSOCIATION_GAP":
        opportunity_type = "BRAND_ASSOCIATION_OPPORTUNITY"
        asset_decision = "UNRESOLVED"
    elif primary_gap and primary_gap.get("gap_type") in {"CAPABILITY_GAP", "CAPABILITY_RECOGNITION_GAP"}:
        opportunity_type = "CAPABILITY_RECOGNITION_OPPORTUNITY"
        asset_decision = "UNRESOLVED"
    elif primary_gap and primary_gap.get("gap_type") == "EVIDENCE_GAP":
        opportunity_type = "EVIDENCE_OPPORTUNITY"
        asset_decision = "UNRESOLVED"
    elif primary_gap:
        opportunity_type = "CANDIDATE_ENTRY_OPPORTUNITY"
        asset_decision = "UNRESOLVED"
    else:
        opportunity_type = "NO_ACTIONABLE_OPPORTUNITY"
        asset_decision = "NEED_MORE_EVIDENCE"

    must_answer = [
        f"{prompt_text} 这个问题下，用户到底需要通用方法、方案类别，还是具体品牌？",
        f"{brand_name} 能承接哪些真实场景，不能承接哪些边界？",
        "AI 回答里高频选择标准是什么，哪些标准必须有可引用证据？",
    ]
    if criteria:
        must_answer.append(f"围绕「{'、'.join(criteria[:4])}」补齐可核验事实。")

    unknown_truths = [item for item in (product_truth or {}).get("truths", []) if item.get("product_truth_status") == "UNKNOWN"]
    faq_items = _build_action_package_faq(prompt_text, criteria)
    return {
        "opportunity_type": opportunity_type,
        "opportunity_type_label": _opportunity_type_label(opportunity_type),
        "asset_decision": asset_decision,
        "asset_decision_label": _asset_decision_label(asset_decision),
        "must_answer": must_answer,
        "selection_reason_gap": primary_gap.get("diagnosis_text") if primary_gap else "暂无明确选择理由缺口。",
        "product_truth_gate": {
            "status": "NEEDS_HUMAN_CONFIRMATION" if unknown_truths else "READY_FOR_STRATEGY_REVIEW",
            "status_label": "需要先人工确认产品事实" if unknown_truths else "产品事实已可用于策略审核",
            "unknown_capabilities": unknown_truths[:8],
            "boundary_note": "竞品被推荐的理由不能自动套给目标品牌；目标品牌是否真实具备该能力，必须由人工或官方事实源确认。",
        },
        "evidence_requirements": [
            "公开可访问的中文页面正文",
            "明确能力句：支持什么、如何操作、适用边界",
            "围绕高频选择标准的 FAQ 或教程段落",
            "能进入最终引用资料的来源标题、正文片段和稳定 URL",
        ],
        "content_brief": {
            "page_goal": f"让 AI 在回答「{prompt_text}」时能把「{brand_name}」识别为相关候选或能力提供方。",
            "answer_intent": "、".join([item["intent_label"] for item in _classify_prompt_intents(prompt_text, [])]),
            "target_need": prompt_text,
            "target_selection_criteria": criteria,
            "target_capability_claims": [
                f"待人工确认：{brand_name} 是否支持「{prompt_text}」对应的核心能力、场景和使用方式。",
                f"待人工确认：{brand_name} 是否提供清晰步骤、适用边界、风险说明和效果验证方式。",
            ],
            "allowed_claims": ["必须来自真实产品能力、已发布页面或人工确认事实。"],
            "forbidden_claims": ["不能写无法验证的最强、唯一、官方授权、绝对安全等表述。"],
            "sections": ["直接回答", "适用场景", "操作步骤", "能力证据", "合规边界", "常见问题", "验证指标"],
            "faq": faq_items,
            "evidence_bindings": evidence_market.get("metrics", {}),
            "internal_links": [project.website_url] if project and project.website_url else [],
        },
        "experiment_proposal": {
            "hypothesis_type": primary_gap.get("gap_type") if primary_gap else "UNKNOWN",
            "mechanism": primary_gap.get("action_hint") if primary_gap else "暂无足够 gap 支撑实验假设。",
            "intervention_family": "UNRESOLVED",
            "primary_metric": _primary_metric_for_gap(primary_gap.get("gap_type") if primary_gap else "UNKNOWN"),
            "baseline": target.get("metrics", {}).get(_metric_key_for_gap(primary_gap.get("gap_type") if primary_gap else "UNKNOWN")),
            "success_threshold": "人工确认后设置；建议先以候选进入或能力识别提升作为阈值。",
            "sample_size_target": max(12, len(solution_slot.get("solution_slot_run_ids", [])) or 12),
        },
    }


def _analyze_brand_opportunity(
    project: Project | None,
    prompt: Prompt | None,
    runs: list[BrowserMonitorRun],
    landscape: list[dict],
) -> dict:
    if not project:
        return {
            "status": "UNKNOWN",
            "status_label": "无法判断",
            "opportunity_detected": False,
            "summary": "项目不存在，无法判断品牌露出机会。",
            "signals": [],
        }

    target = next((row for row in landscape if row["entity_name"] == project.brand_name), None)
    brand_mention_count = target["mention_run_count"] if target else 0
    brand_recommendation_count = target["recommendation_run_count"] if target else 0
    any_brand_recommendation = any(row["recommendation_run_count"] > 0 for row in landscape)
    signals = _extract_opportunity_signals(runs)
    signal_labels = [signal["signal_label"] for signal in signals[:4]]

    if any_brand_recommendation:
        status = "BRAND_RECOMMENDATION_EXISTS"
        status_label = "已有品牌推荐"
        summary = "当前回答已经出现品牌推荐，可继续核验证据来源和推荐稳定性。"
        opportunity_detected = False
    elif brand_mention_count > 0:
        status = "BRAND_MENTIONED_NOT_RECOMMENDED"
        status_label = "品牌被提及但未被推荐"
        summary = f"「{project.brand_name}」已被提及，但没有形成明确推荐。下一步应补强能让 AI 给出选择判断的场景、能力和证据。"
        opportunity_detected = True
    elif signals:
        status = "NO_BRAND_RECOMMENDATION_WITH_OPPORTUNITY"
        status_label = "当前没有品牌推荐，但存在品牌露出机会"
        joined = "、".join(signal_labels)
        summary = f"当前回答没有推荐任何品牌，但答案反复讨论「{joined}」等可承接场景，适合让「{project.brand_name}」以合规工具/教程/案例证据进入答案。"
        opportunity_detected = True
    else:
        status = "NO_BRAND_RECOMMENDATION_NO_CLEAR_OPPORTUNITY"
        status_label = "当前没有品牌推荐，暂未发现明确露出机会"
        summary = "当前回答没有推荐任何品牌，也没有稳定出现可由品牌承接的工具、流程、风险或转化场景。"
        opportunity_detected = False

    prompt_text = prompt.prompt_text if prompt else "当前问题"
    return {
        "status": status,
        "status_label": status_label,
        "opportunity_detected": opportunity_detected,
        "brand_name": project.brand_name,
        "prompt_text": prompt_text,
        "brand_mention_count": brand_mention_count,
        "brand_recommendation_count": brand_recommendation_count,
        "any_brand_recommendation": any_brand_recommendation,
        "summary": summary,
        "signals": signals,
        "recommended_next_action": _recommended_next_action(project.brand_name, prompt_text, signals, brand_mention_count),
    }


def _extract_opportunity_signals(runs: list[BrowserMonitorRun]) -> list[dict]:
    matches: dict[str, dict] = {}
    for run in runs:
        for sentence in _split_answer(run.answer_text or ""):
            for signal_type, label, keywords in OPPORTUNITY_SIGNAL_RULES:
                matched_keywords = [keyword for keyword in keywords if keyword in sentence]
                if not matched_keywords:
                    continue
                current = matches.setdefault(signal_type, {
                    "signal_type": signal_type,
                    "signal_label": label,
                    "count": 0,
                    "run_ids": set(),
                    "matched_keywords": set(),
                    "examples": [],
                })
                current["count"] += 1
                current["run_ids"].add(run.id)
                current["matched_keywords"].update(matched_keywords)
                if len(current["examples"]) < 3:
                    current["examples"].append(sentence[:240])

    signals = []
    for item in matches.values():
        signals.append({
            "signal_type": item["signal_type"],
            "signal_label": item["signal_label"],
            "count": item["count"],
            "run_count": len(item["run_ids"]),
            "run_ids": sorted(item["run_ids"])[:8],
            "matched_keywords": sorted(item["matched_keywords"]),
            "examples": item["examples"],
        })
    return sorted(signals, key=lambda signal: (-signal["run_count"], -signal["count"], signal["signal_label"]))


def _recommended_next_action(brand_name: str, prompt_text: str, signals: list[dict], brand_mention_count: int) -> str:
    if brand_mention_count > 0:
        return f"围绕「{prompt_text}」补充「为什么选择{brand_name}」的真实证据，把已有提及推进为候选或明确推荐。"
    if not signals:
        return "先补充更多采样或换成更接近选型/工具选择的问题，再判断是否适合做品牌露出。"
    top_signal = signals[0]["signal_label"]
    return f"优先制作一页面向「{prompt_text}」的中文说明页，把{brand_name}与「{top_signal}」绑定起来，并提供操作步骤、能力边界和真实案例。"


def _build_action_package_faq(prompt_text: str, criteria: list[str]) -> list[str]:
    prompt_label = f"「{prompt_text}」" if prompt_text else "当前问题"
    faq = [
        f"做 {prompt_label} 前，需要先确认哪些前置条件？",
        f"{prompt_label} 的适用边界和风险点是什么？",
    ]
    if criteria:
        faq.append(f"如果重点比较「{'、'.join(criteria[:2])}」，应该怎么判断是否合适？")
    else:
        faq.append(f"{prompt_label} 的不同实现路径分别适合什么情况？")
    faq.append("上线后用什么指标验证是否真的有效？")
    return faq


def _build_answer_samples(project: Project | None, runs: list[BrowserMonitorRun], landscape: list[dict]) -> list[dict]:
    brand_name = project.brand_name if project else ""
    visible_entities = {row["entity_name"] for row in landscape[:6]}
    scored = []
    for run in runs:
        answer = (run.answer_text or "").strip()
        if not answer:
            continue
        score = 0
        if brand_name and brand_name in answer:
            score += 100
        score += 20 * sum(1 for entity in visible_entities if entity and entity in answer)
        if run.status == "success":
            score += 8
        if run.resolved_reference_count:
            score += min(run.resolved_reference_count, 20)
        if any(keyword in answer for keyword in ["推荐", "选择", "工具", "方案", "步骤", "合规"]):
            score += 12
        scored.append((score, run.id, run))

    samples = []
    for _, _, run in sorted(scored, key=lambda item: (-item[0], item[1]))[:6]:
        answer = (run.answer_text or "").strip()
        samples.append({
            "run_id": run.id,
            "status": run.status,
            "status_label": "成功" if run.status == "success" else "部分成功" if run.status == "partial_success" else run.status,
            "brand_mentioned": run.brand_mentioned,
            "brand_mention_count": run.brand_mention_count,
            "reference_count": run.resolved_reference_count or run.detected_reference_count or run.expected_reference_count,
            "why_selected": _answer_sample_reason(project, answer, visible_entities),
            "answer_excerpt": answer[:1200],
            "key_sentences": _key_sentences(answer),
        })
    return samples


def _answer_sample_reason(project: Project | None, answer: str, visible_entities: set[str]) -> str:
    if project and project.brand_name in answer:
        return f"包含目标品牌「{project.brand_name}」"
    matched_entities = [entity for entity in visible_entities if entity and entity in answer]
    if matched_entities:
        return f"包含竞品/候选品牌：{'、'.join(matched_entities[:3])}"
    if "合规" in answer or "风险" in answer:
        return "包含合规与风险判断"
    if "步骤" in answer or "制作" in answer or "后台" in answer:
        return "包含操作流程"
    return "代表性回答样本"


def _key_sentences(answer: str) -> list[str]:
    keywords = ["爱短链", "外链", "跳转", "微信", "合规", "风险", "工具", "推荐", "数据", "回传", "步骤"]
    sentences = []
    for sentence in _split_answer(answer):
        if any(keyword in sentence for keyword in keywords):
            sentences.append(sentence[:220])
        if len(sentences) >= 5:
            break
    return sentences


def _build_citation_sources(db: Session, runs: list[BrowserMonitorRun], evidence_links: list[dict]) -> list[dict]:
    run_ids = [run.id for run in runs]
    if not run_ids:
        return []

    linked_citation_ids = [link.get("citation_id") for link in evidence_links if link.get("citation_id")]
    sources: list[ReferenceSource] = []
    if linked_citation_ids:
        sources.extend(
            db.query(ReferenceSource)
            .filter(ReferenceSource.id.in_(linked_citation_ids))
            .order_by(ReferenceSource.run_id, ReferenceSource.reference_index)
            .all()
        )

    if len(sources) < 12:
        supplemental = (
            db.query(ReferenceSource)
            .filter(ReferenceSource.run_id.in_(run_ids))
            .filter(ReferenceSource.url != "")
            .order_by(ReferenceSource.run_id, ReferenceSource.reference_index)
            .limit(80)
            .all()
        )
        seen_ids = {source.id for source in sources}
        for source in supplemental:
            if source.id not in seen_ids:
                sources.append(source)
                seen_ids.add(source.id)
            if len(sources) >= 12:
                break

    link_by_citation = {link.get("citation_id"): link for link in evidence_links if link.get("citation_id")}
    rows = []
    for source in sources[:12]:
        link = link_by_citation.get(source.id, {})
        doc = _document_for_ref(db, source)
        rows.append({
            "citation_id": source.id,
            "run_id": source.run_id,
            "reference_index": source.reference_index,
            "title": source.display_title or source.matched_title or (doc.title if doc else "") or source.url,
            "domain": source.domain or (doc.domain if doc else ""),
            "url": source.url or source.canonical_url,
            "source_passage": (link.get("source_passage") or _source_passage_from_doc(doc))[:700],
            "related_entity": link.get("supported_entity_name", ""),
            "evidence_role_label": link.get("primary_evidence_role_label", "参考资料"),
            "why_matters": _citation_why_matters(source, link),
        })
    return rows


def _source_passage_from_doc(doc: SourceDocument | None) -> str:
    if not doc or not doc.clean_text:
        return ""
    return doc.clean_text[:700].strip()


def _citation_why_matters(source: ReferenceSource, link: dict) -> str:
    if link.get("supported_entity_name"):
        return f"支撑「{link['supported_entity_name']}」相关回答判断。"
    title = source.display_title or source.matched_title or ""
    if any(keyword in title for keyword in ["教程", "实操", "步骤", "方法"]):
        return "可参考其操作流程结构。"
    if any(keyword in title for keyword in ["合规", "风险", "规则"]):
        return "可参考其合规与风险表达。"
    return "可作为当前回答引用来源线索。"


def _build_action_brief(
    project: Project | None,
    prompt: Prompt | None,
    landscape: list[dict],
    brand_opportunity: dict,
) -> dict:
    brand_name = project.brand_name if project else "目标品牌"
    prompt_text = prompt.prompt_text if prompt else "当前问题"
    target = next((row for row in landscape if row["entity_name"] == brand_name), None)
    competitor_rows = [row for row in landscape if row["entity_name"] != brand_name]
    competitor_names = [row["entity_name"] for row in competitor_rows[:3]]
    signal_labels = [signal["signal_label"] for signal in brand_opportunity.get("signals", [])[:5]]

    if target and target.get("mention_run_count", 0) > 0:
        situation = f"{brand_name} 已出现 {target['mention_run_count']} 次，但没有明确推荐。"
    else:
        situation = f"{brand_name} 尚未稳定进入「{prompt_text}」回答。"
    if competitor_names:
        situation += f" 当前出现的竞品/候选品牌包括：{'、'.join(competitor_names)}。"

    return {
        "title": f"{prompt_text}：{brand_name} 品牌露出行动说明",
        "situation": situation,
        "goal": f"让 AI 在回答「{prompt_text}」时，不只讲通用方法，而能把「{brand_name}」作为合规工具候选提及。",
        "must_answer": [
            f"{brand_name} 是否有真实能力承接「{prompt_text}」对应的需求场景？",
            f"{brand_name} 的操作流程、前置条件和完成路径是什么？",
            f"{brand_name} 的适用边界、风险点和不适用场景是什么？",
            f"用户最关心的证据是什么，{brand_name} 如何提供可引用的中文页面与事实？",
        ],
        "content_sections": [
            f"直接回答：先回答「{prompt_text}」，再说明适用边界和完成条件",
            f"{brand_name} 操作流程：从进入页面到完成配置的关键步骤",
            f"能力证据：围绕「{prompt_text}」补足可被引用的能力句、截图、案例或 FAQ",
            "限制与风险：哪些条件下会失败、受限或需要人工确认",
            f"方案对比：{brand_name} 与其它候选路径分别适合什么场景",
            "验证方式：上线后看哪些采样信号、引用情况和候选进入变化",
        ],
        "evidence_to_collect": [
            "产品后台截图或流程截图",
            "真实功能说明页 URL",
            "合规边界说明",
            "数据追踪/转化回传能力说明",
            "1-2 个真实使用场景案例",
        ],
        "priority_signals": signal_labels,
        "validation": "发布后固定复采同一问题，观察爱短链是否从仅提及进入候选，或是否出现明确推荐理由。",
    }


def _answer_has_choice_slot(prompt_text: str, answer: str, run_claims: list[RecommendationClaim]) -> tuple[bool, str, float]:
    candidate_claims = [
        claim for claim in run_claims
        if claim.recommendation_type in {"CANDIDATE", "POSITIVE_RECOMMENDATION", "TOP_RECOMMENDATION"}
    ]
    if candidate_claims:
        return True, candidate_claims[0].answer_span, 0.84

    alternative_markers = ["或", "也可以", "可选", "选择", "优先", "更适合", "推荐", "例如", "等第三方", "多种", "多个"]
    choice_objects = ["工具", "平台", "服务商", "短链", "外链", "卡片", "落地页", "方案", "产品", "品牌"]
    for sentence in _split_answer(answer or ""):
        has_object = any(keyword in sentence for keyword in choice_objects)
        has_alternative = any(keyword in sentence for keyword in alternative_markers)
        pure_operation = any(keyword in sentence for keyword in ["进入", "点击", "复制", "粘贴", "上传"]) and not has_alternative
        if has_object and has_alternative and not pure_operation:
            return True, sentence, 0.72

    prompt_choice = any(keyword in (prompt_text or "") for keyword in ["哪个", "哪家", "哪个好", "用什么工具", "选择", "推荐"])
    if prompt_choice and any(keyword in (answer or "") for keyword in choice_objects):
        span = next((sentence for sentence in _split_answer(answer or "") if any(keyword in sentence for keyword in choice_objects)), "")
        return True, span, 0.62
    return False, "", 0.66


def _sentence_has_comparison(sentence: str) -> bool:
    return any(keyword in sentence for keyword in ["对比", "比较", "相比", "更适合", "优于", "不如", "区别", "vs", "VS"])


def _answer_has_brand_comparison(answer: str, run_claims: list[RecommendationClaim]) -> tuple[bool, str, float]:
    brand_names = sorted({claim.entity_name for claim in run_claims if claim.entity_name}, key=len, reverse=True)
    if len(brand_names) < 2:
        return False, "", 0.7

    for sentence in _split_answer(answer or ""):
        if not _sentence_has_comparison(sentence):
            continue
        mentioned = {name for name in brand_names if name and name in sentence}
        if len(mentioned) >= 2:
            return True, sentence, 0.82
    return False, "", 0.7


def _solution_specificity(answer: str, landscape: list[dict]) -> str:
    if any(row.get("entity_name") and row["entity_name"] in answer for row in landscape):
        return "BRAND"
    if any(keyword in answer for keyword in ["短链", "外链", "卡片", "落地页", "企业微信"]):
        return "PRODUCT_TYPE"
    if any(keyword in answer for keyword in ["第三方", "工具", "平台", "方案", "服务商"]):
        return "CATEGORY"
    if any(keyword in answer for keyword in ["步骤", "方法", "设置", "操作"]):
        return "GENERIC_METHOD"
    return "UNKNOWN"


def _matched_entity(sentence: str, entities: list[RecommendationEntity]) -> RecommendationEntity | None:
    for entity in entities:
        if _matched_alias(sentence, entity):
            return entity
    return None


def _solution_object_for_sentence(sentence: str) -> dict:
    for key, label, keywords in SOLUTION_OBJECT_RULES:
        if any(keyword in sentence for keyword in keywords):
            return {"key": key, "label": label}
    return {"key": "", "label": ""}


def _is_selection_context(sentence: str) -> bool:
    return any(keyword in sentence for keyword in ["推荐", "选择", "建议", "适合", "优先", "可通过", "可以使用", "可选", "方案", "工具", "平台"])


def _capability_predicate(sentence: str) -> str:
    if any(keyword in sentence for keyword in ["不支持", "不能", "无法"]):
        return "DOES_NOT_SUPPORT"
    if any(keyword in sentence for keyword in ["受限", "限制", "谨慎", "风险"]):
        return "CONSTRAINED_FOR"
    if any(keyword in sentence for keyword in ["适合", "适用于"]):
        return "SUITABLE_FOR"
    if any(keyword in sentence for keyword in ["提供", "具备", "带有"]):
        return "PROVIDES"
    if any(keyword in sentence for keyword in ["支持", "可支持"]):
        return "SUPPORTS"
    if any(keyword in sentence for keyword in ["可以", "能够", "可通过", "能"]):
        return "CAN_DO"
    if any(keyword in sentence for keyword in ["连接", "接入", "对接", "跳转", "集成"]):
        return "INTEGRATES_WITH"
    return "UNKNOWN"


def _need_label_for_sentence(sentence: str, prompt_text: str) -> str:
    text = " ".join([prompt_text or "", sentence or ""])
    for label, keywords in NEED_RULES:
        if all(keyword in text for keyword in keywords):
            return label
    for label, keywords in NEED_RULES:
        if any(keyword in text for keyword in keywords):
            return label
    return "当前问题需求"


def _capability_label_for_sentence(sentence: str) -> str:
    rules = [
        ("抖音跳转微信", ["抖音", "微信", "跳转"]),
        ("企业微信承接", ["企业微信", "客服", "加好友"]),
        ("短链生成", ["短链", "生成"]),
        ("卡片制作", ["卡片", "制作"]),
        ("数据追踪", ["数据", "追踪", "点击", "回传"]),
        ("合规风控", ["合规", "风控", "风险", "违规"]),
        ("落地页承接", ["落地页", "中间页"]),
    ]
    for label, keywords in rules:
        if all(keyword in sentence for keyword in keywords):
            return label
    for label, keywords in rules:
        if any(keyword in sentence for keyword in keywords):
            return label
    return ""


def _sentence_has_need(sentence: str) -> bool:
    return any(any(keyword in sentence for keyword in keywords) for _, keywords in NEED_RULES)


def _best_criterion_for_claim(claim: RecommendationClaim, criteria: list[DecisionSelectionCriterion]) -> DecisionSelectionCriterion | None:
    for criterion in criteria:
        if criterion.related_brand_name and criterion.related_brand_name == claim.entity_name:
            return criterion
    for criterion in criteria:
        if criterion.criterion_used_for_selection:
            return criterion
    return criteria[0] if criteria else None


def _adoption_role_from_link(link: RecommendationEvidenceLink, criterion: DecisionSelectionCriterion | None) -> str:
    if criterion and criterion.criterion_used_for_selection:
        return "SELECTION_REASON_CONTEXT"
    roles = loads(link.evidence_roles_json, [])
    if "CAPABILITY_SUPPORT" in roles:
        return "CAPABILITY_CONTEXT"
    if "RECOMMENDATION_SUPPORT" in roles:
        return "RECOMMENDATION_CONTEXT"
    if "LIMITATION_SUPPORT" in roles:
        return "LIMITATION_CONTEXT"
    if "DECISION_CRITERIA" in roles:
        return "SELECTION_REASON_CONTEXT"
    return "CITATION_CONTEXT"


def _evidence_status_for_context(link: RecommendationEvidenceLink, criterion: DecisionSelectionCriterion | None) -> str:
    if not link.citation_id:
        return "UNLINKED"
    if link.attribution_confidence >= 0.75 and criterion and criterion.criterion_used_for_selection:
        return "LINKED"
    if link.attribution_confidence >= 0.55:
        return "PARTIALLY_LINKED"
    return "UNCERTAIN"


def _support_strength(score: float | None) -> str:
    value = score or 0
    if value >= 0.75:
        return "STRONG"
    if value >= 0.55:
        return "MEDIUM"
    if value > 0:
        return "WEAK"
    return "UNKNOWN"


def _derive_funnel_stage(
    mention_runs: set[int],
    need_assoc_runs: set[int],
    capability_runs: set[int],
    candidate_runs: set[int],
    explicit_runs: set[int],
    top_runs: set[int],
) -> str:
    if top_runs:
        return "TOP_RECOMMENDED"
    if explicit_runs:
        return "EXPLICITLY_RECOMMENDED"
    if candidate_runs:
        return "SOLUTION_CANDIDATE"
    if capability_runs:
        return "CAPABILITY_RECOGNIZED"
    if need_assoc_runs:
        return "NEED_ASSOCIATED"
    if mention_runs:
        return "MENTIONED"
    return "ABSENT"


def _metric(metric_name: str, numerator: int, denominator: int, eligible_denominator: int | None = None, sample_size: int | None = None) -> dict:
    eligible = denominator if eligible_denominator is None else eligible_denominator
    return {
        "metric": metric_name,
        "numerator": numerator,
        "denominator": denominator,
        "eligible_denominator": eligible,
        "value": round(numerator / denominator, 4) if denominator else None,
        "sample_size": sample_size if sample_size is not None else denominator,
    }


def _gap_type_label(gap_type: str) -> str:
    labels = {
        "VISIBILITY_GAP": "可见性缺口",
        "ASSOCIATION_GAP": "需求关联缺口",
        "CAPABILITY_GAP": "能力识别缺口",
        "CAPABILITY_RECOGNITION_GAP": "能力识别缺口",
        "CANDIDATE_GAP": "候选进入缺口",
        "CANDIDATE_INCLUSION_GAP": "候选进入缺口",
        "SELECTION_REASON_GAP": "选择理由缺口",
        "EVIDENCE_GAP": "证据缺口",
        "RETRIEVAL_GAP": "检索缺口",
        "CITATION_GAP": "引用缺口",
        "INTENT_FIT_GAP": "意图匹配提醒",
        "ENTITY_GAP": "实体识别缺口",
        "SOURCE_TOPOLOGY_GAP": "来源结构缺口",
        "RECOMMENDATION_GAP": "明确推荐缺口",
        "TOP_RECOMMENDATION_GAP": "第一推荐缺口",
        "UNKNOWN": "无法判断",
    }
    return labels.get(gap_type, gap_type)


def _severity_label(severity: str) -> str:
    return {"HIGH": "高", "MEDIUM": "中", "LOW": "低", "UNKNOWN": "未知"}.get(severity, severity)


def _adoption_role_label(role: str) -> str:
    labels = {
        "DIRECT_SUPPORT": "直接支撑",
        "PARTIAL_SUPPORT": "部分支撑",
        "ENTITY_SUPPORT": "实体支撑",
        "CAPABILITY_SUPPORT": "能力支撑",
        "SELECTION_REASON_SUPPORT": "选择理由支撑",
        "RECOMMENDATION_CONTEXT": "推荐引用上下文",
        "CAPABILITY_CONTEXT": "能力引用上下文",
        "SELECTION_REASON_CONTEXT": "选择理由引用上下文",
        "LIMITATION_CONTEXT": "限制引用上下文",
        "CITATION_CONTEXT": "引用上下文",
        "BACKGROUND": "背景资料",
        "CONTRADICTS": "相反证据",
        "UNRELATED": "无关",
        "UNKNOWN": "未知",
    }
    return labels.get(role, role)


def _support_strength_label(strength: str) -> str:
    return {"STRONG": "强", "MEDIUM": "中", "WEAK": "弱", "UNKNOWN": "未知"}.get(strength, strength)


def _opportunity_type_label(opportunity_type: str) -> str:
    labels = {
        "NO_ACTIONABLE_OPPORTUNITY": "暂无可行动机会",
        "CONTENT_INFORMATION_OPPORTUNITY": "信息内容机会",
        "SOLUTION_CATEGORY_OPPORTUNITY": "方案类别机会",
        "BRAND_ASSOCIATION_OPPORTUNITY": "品牌关联机会",
        "CAPABILITY_RECOGNITION_OPPORTUNITY": "能力识别机会",
        "CANDIDATE_ENTRY_OPPORTUNITY": "候选进入机会",
        "RECOMMENDATION_OPPORTUNITY": "明确推荐机会",
        "EVIDENCE_OPPORTUNITY": "证据机会",
        "RETRIEVAL_OPPORTUNITY": "检索机会",
    }
    return labels.get(opportunity_type, opportunity_type)


def _asset_decision_label(decision: str) -> str:
    labels = {
        "UPDATE_EXISTING": "更新现有资产",
        "CREATE_NEW": "新建资产",
        "MERGE": "合并资产",
        "EXTERNAL_DISTRIBUTION": "外部分发",
        "UNRESOLVED": "待人工确认",
        "NO_CONTENT_ACTION": "暂不做内容动作",
        "NEED_MORE_EVIDENCE": "需要更多证据",
    }
    return labels.get(decision, decision)


def _intervention_family_for_gap(gap_type: str) -> str:
    return {
        "ASSOCIATION_GAP": "BRAND_NEED_ASSOCIATION",
        "CAPABILITY_GAP": "CAPABILITY_EXPLICITNESS",
        "CAPABILITY_RECOGNITION_GAP": "CAPABILITY_EXPLICITNESS",
        "SELECTION_REASON_GAP": "SELECTION_REASON_EVIDENCE",
        "EVIDENCE_GAP": "CITABILITY",
        "RETRIEVAL_GAP": "RETRIEVAL_ELIGIBILITY",
        "CITATION_GAP": "SOURCE_DISTRIBUTION",
        "ENTITY_GAP": "ENTITY_CONSISTENCY",
        "CANDIDATE_GAP": "CONTENT_STRUCTURE",
        "CANDIDATE_INCLUSION_GAP": "CONTENT_STRUCTURE",
    }.get(gap_type, "OTHER")


def _primary_metric_for_gap(gap_type: str) -> str:
    return {
        "ASSOCIATION_GAP": "need_association_rate",
        "CAPABILITY_GAP": "capability_recognition_rate",
        "CAPABILITY_RECOGNITION_GAP": "capability_recognition_rate",
        "CANDIDATE_GAP": "candidate_capture_rate",
        "CANDIDATE_INCLUSION_GAP": "candidate_capture_rate",
        "SELECTION_REASON_GAP": "target_selection_reason_usage_rate",
        "EVIDENCE_GAP": "evidence_link_rate",
        "RETRIEVAL_GAP": "target_page_retrieval_rate",
        "CITATION_GAP": "target_page_conversion_rate",
        "RECOMMENDATION_GAP": "explicit_recommendation_rate",
        "TOP_RECOMMENDATION_GAP": "top_recommendation_rate",
    }.get(gap_type, "manual_review")


def _metric_key_for_gap(gap_type: str) -> str:
    return {
        "ASSOCIATION_GAP": "need_association_rate",
        "CAPABILITY_GAP": "capability_recognition_rate",
        "CAPABILITY_RECOGNITION_GAP": "capability_recognition_rate",
        "CANDIDATE_GAP": "candidate_capture_rate",
        "CANDIDATE_INCLUSION_GAP": "candidate_capture_rate",
        "RECOMMENDATION_GAP": "explicit_recommendation_rate",
        "TOP_RECOMMENDATION_GAP": "top_recommendation_rate",
    }.get(gap_type, "candidate_capture_rate")


def _split_answer(text: str) -> list[str]:
    parts = []
    for raw in _SENTENCE_SPLIT.split(text):
        raw = raw.strip(" \t\r\n-—")
        if len(raw) >= 4:
            parts.append(raw[:1200])
    return parts


def _matched_alias(sentence: str, entity: RecommendationEntity) -> str:
    aliases = [entity.canonical_name, *loads(entity.aliases_json, [])]
    for alias in sorted(set(filter(None, aliases)), key=len, reverse=True):
        if alias and alias in sentence:
            return alias
    return ""


def _classify_recommendation(sentence: str) -> str:
    if any(kw in sentence for kw in ["没有形成推荐", "未形成推荐", "不是推荐", "并非推荐"]):
        return "MENTION_ONLY"
    if any(kw in sentence for kw in ["网上很多人推荐", "很多人推荐", "有人推荐", "别人推荐"]) and any(kw in sentence for kw in ["风险", "不建议", "警惕", "违规", "谨慎"]):
        return "MENTION_ONLY"
    if any(kw in sentence for kw in ["不推荐", "不建议", "不要使用", "避免使用", "警惕"]):
        return "NEGATIVE_RECOMMENDATION"
    if any(kw in sentence for kw in ["首选", "最推荐", "第一选择", "优先级最高", "最佳选择"]):
        return "TOP_RECOMMENDATION"
    if any(kw in sentence for kw in ["推荐", "更适合", "更合适", "优先考虑", "值得选择", "建议使用", "可以优先", "适合优先"]):
        return "POSITIVE_RECOMMENDATION"
    if any(kw in sentence for kw in ["可通过", "可以使用", "可使用", "可选", "方案", "工具", "平台"]):
        return "CANDIDATE"
    return "MENTION_ONLY"


def _recommendation_strength(recommendation_type: str, sentence: str) -> str:
    if recommendation_type == "TOP_RECOMMENDATION":
        return "TOP_CHOICE"
    if recommendation_type == "POSITIVE_RECOMMENDATION":
        if any(keyword in sentence for keyword in ["强烈", "最", "首选", "优先级最高"]):
            return "STRONGLY_RECOMMENDED"
        if any(keyword in sentence for keyword in ["优先", "更适合", "更合适"]):
            return "RECOMMENDED"
        return "WEAK_PREFERENCE"
    if recommendation_type == "CANDIDATE":
        return "WEAK_PREFERENCE"
    return "UNKNOWN"


def _recommendation_strength_label(value: str) -> str:
    return {
        "WEAK_PREFERENCE": "弱偏好",
        "RECOMMENDED": "推荐",
        "STRONGLY_RECOMMENDED": "强推荐",
        "TOP_CHOICE": "第一选择",
        "UNKNOWN": "未知",
    }.get(value, value)


def _entity_type_label(entity_type: str) -> str:
    return {
        "BRAND": "品牌",
        "PRODUCT": "产品",
        "CATEGORY": "品类",
        "PLATFORM": "平台",
        "METHOD": "方法",
        "FEATURE": "功能",
        "SOURCE": "来源",
        "OTHER": "其他",
    }.get(entity_type, entity_type or "未知")


def _entity_role_label(entity_role: str) -> str:
    return {
        "SOLUTION_PROVIDER": "解决方案提供者",
        "BRAND": "品牌",
        "CATEGORY": "品类",
        "PLATFORM": "平台",
        "CHANNEL": "渠道",
        "AUTHORITY": "规则/权威方",
        "SOURCE": "来源",
        "FEATURE": "功能",
        "METHOD": "方法",
        "OTHER": "其他",
    }.get(entity_role, entity_role or "未知")


def _semantic_fact_label(value: str) -> str:
    return {
        "has_choice_slot": "存在品牌选择空间",
        "has_brand_mention": "出现真实品牌",
        "has_explicit_recommendation": "答案作者执行明确推荐",
        "has_comparison": "存在对比",
        "has_brand_comparison": "存在品牌对比",
    }.get(value, value)


def _extract_rank(sentence: str) -> int | None:
    if any(kw in sentence for kw in ["首选", "第一选择", "最推荐", "优先级最高"]):
        return 1
    if any(kw in sentence for kw in ["其次", "第二"]):
        return 2
    if any(kw in sentence for kw in ["第三"]):
        return 3
    return None


def _extract_condition(sentence: str) -> tuple[str, str]:
    if not any(kw in sentence for kw in ["如果", "若", "当", "适用于", "适合", "针对", "预算", "企业", "安全", "平台"]):
        return "", ""
    condition_type = "OTHER"
    if "预算" in sentence or "免费" in sentence:
        condition_type = "BUDGET"
    elif "新手" in sentence or "简单" in sentence:
        condition_type = "SKILL_LEVEL"
    elif "场景" in sentence or "适用" in sentence or "适合" in sentence or "针对" in sentence:
        condition_type = "USE_CASE"
    elif "功能" in sentence or "支持" in sentence:
        condition_type = "FEATURE_REQUIREMENT"
    elif "企业" in sentence or "公司" in sentence:
        condition_type = "ENTERPRISE_NEED"
    elif "平台" in sentence or "抖音" in sentence or "微信" in sentence:
        condition_type = "PLATFORM"
    elif "安全" in sentence or "风险" in sentence:
        condition_type = "SECURITY"
    return condition_type, sentence[:160]


def _extract_reasons(sentence: str, recommendation_type: str) -> list[str]:
    if recommendation_type == "MENTION_ONLY":
        return []
    reason_keywords = ["支持", "规避", "适合", "简单", "自动", "回传", "优化", "合规", "直达", "加密"]
    if any(keyword in sentence for keyword in reason_keywords):
        return [sentence[:240]]
    return []


def _classify_reason_type(text: str) -> str:
    rules = [
        ("EASE_OF_USE", ["简单", "方便", "快速", "上手"]),
        ("FUNCTIONAL_CAPABILITY", ["支持", "功能", "能够", "可以", "自动"]),
        ("SECURITY", ["安全", "风险", "规避", "加密", "拦截"]),
        ("SCENARIO_FIT", ["适合", "适用", "场景", "针对"]),
        ("INTEGRATION", ["微信", "抖音", "跨端", "跳转"]),
        ("SPEED", ["快速", "直达", "唤醒"]),
        ("SERVICE", ["服务", "回传", "投放", "优化"]),
    ]
    for reason_type, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return reason_type
    return "OTHER"


def _best_reference_match(db: Session, claim: RecommendationClaim, refs: list[ReferenceSource]):
    best = (None, "", 0.0, "")
    needle_values = [claim.entity_name, *loads(claim.reason_texts_json, []), claim.answer_span]
    needles = [_normalize_key(value) for value in needle_values if value]
    for ref in refs:
        doc = _document_for_ref(db, ref)
        haystack_text = " ".join([
            ref.display_title or "",
            ref.url or "",
            ref.domain or "",
            doc.title if doc else "",
            (doc.clean_text or "")[:5000] if doc else "",
        ])
        haystack = _normalize_key(haystack_text)
        score = 0.0
        method = ""
        for needle in needles:
            if not needle:
                continue
            if needle and needle in haystack:
                score = max(score, 0.8 if len(needle) >= 4 else 0.55)
                method = "entity_or_reason_text_match"
        if not score and claim.entity_name and claim.entity_name in (ref.display_title or ""):
            score = 0.7
            method = "citation_title_match"
        if score > best[2]:
            best = (ref, _source_passage_for_match(doc, claim), score, method or "weak_reference_match")
    return best


def _document_for_ref(db: Session, ref: ReferenceSource) -> SourceDocument | None:
    ref_url = ref.canonical_url or ref.url
    if not ref_url:
        return None
    return db.query(SourceDocument).filter(
        (SourceDocument.url == ref_url) |
        (SourceDocument.original_url == ref_url) |
        (SourceDocument.canonical_url == ref_url)
    ).first()


def _candidate_for_ref(ref: ReferenceSource | None, candidates: list[RetrievalCandidate]) -> RetrievalCandidate | None:
    if not ref:
        return None
    ref_urls = {_canonical_compare_url(ref.url), _canonical_compare_url(ref.canonical_url)}
    ref_urls.discard("")
    ref_domain = (ref.domain or "").lower()
    ref_title = _normalize_key(ref.display_title or ref.matched_title or "")
    for candidate in candidates:
        candidate_urls = {_canonical_compare_url(candidate.url), _canonical_compare_url(candidate.canonical_url)}
        candidate_urls.discard("")
        if ref_urls & candidate_urls:
            return candidate
    for candidate in candidates:
        if ref_domain and ref_domain == (candidate.domain or "").lower():
            candidate_title = _normalize_key(candidate.title or "")
            if ref_title and candidate_title and (ref_title in candidate_title or candidate_title in ref_title):
                return candidate
    return None


def _canonical_compare_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value.strip())
    host = (parsed.netloc or "").lower().removeprefix("www.")
    path = re.sub(r"/+$", "", parsed.path or "")
    return f"{host}{path}"


def _source_passage_for_match(doc: SourceDocument | None, claim: RecommendationClaim) -> str:
    if not doc or not doc.clean_text:
        return ""
    text = doc.clean_text
    for needle in [claim.entity_name, *loads(claim.reason_texts_json, [])]:
        if not needle:
            continue
        index = text.find(needle[:20])
        if index >= 0:
            start = max(0, index - 120)
            end = min(len(text), index + 360)
            return text[start:end].strip()
    return text[:360].strip()


def _evidence_roles_for_claim(claim: RecommendationClaim) -> list[str]:
    if claim.recommendation_type in {"POSITIVE_RECOMMENDATION", "TOP_RECOMMENDATION"}:
        roles = ["RECOMMENDATION_SUPPORT"]
    elif claim.recommendation_type == "CANDIDATE":
        roles = ["DECISION_CRITERIA"]
    elif claim.recommendation_type == "NEGATIVE_RECOMMENDATION":
        roles = ["LIMITATION_SUPPORT"]
    else:
        return []
    if loads(claim.reason_texts_json, []):
        roles.append("CAPABILITY_SUPPORT")
    if any(kw in claim.answer_span for kw in ["步骤", "点击", "填写", "生成", "打开"]):
        roles.append("PROCEDURAL_SUPPORT")
    return roles


def _role_reason_for_claim(claim: RecommendationClaim, role: str) -> str:
    labels = {
        "RECOMMENDATION_SUPPORT": "回答中出现明确选择判断，需要外显证据支撑。",
        "DECISION_CRITERIA": "回答中把该对象列为可选方案或决策条件。",
        "LIMITATION_SUPPORT": "回答中出现风险或限制判断。",
        "CAPABILITY_SUPPORT": "回答中出现能力、适用场景或效果理由。",
        "PROCEDURAL_SUPPORT": "回答中出现操作步骤或流程支撑。",
    }
    return labels.get(role, "规则归因生成的证据角色。")


def _reason_type_label(reason_type: str) -> str:
    labels = {
        "FUNCTIONAL_CAPABILITY": "功能能力",
        "EASE_OF_USE": "易用性",
        "PRICE": "价格",
        "FREE_USAGE": "免费使用",
        "RELIABILITY": "可靠性",
        "PLATFORM_SUPPORT": "平台支持",
        "CUSTOMIZATION": "定制能力",
        "ENTERPRISE_FIT": "企业适配",
        "SECURITY": "安全合规",
        "POPULARITY": "流行度",
        "SERVICE": "服务能力",
        "INTEGRATION": "集成互通",
        "SPEED": "速度效率",
        "CONTENT_QUALITY": "内容质量",
        "SCENARIO_FIT": "场景适配",
        "OTHER": "其他理由",
    }
    return labels.get(reason_type, reason_type)


def _evidence_role_label(role: str) -> str:
    labels = {
        "RECOMMENDATION_SUPPORT": "推荐支撑",
        "CAPABILITY_SUPPORT": "能力支撑",
        "DECISION_CRITERIA": "决策依据",
        "COMPARISON_SUPPORT": "对比支撑",
        "LIMITATION_SUPPORT": "限制支撑",
        "PROCEDURAL_SUPPORT": "流程支撑",
        "BACKGROUND_SUPPORT": "背景支撑",
    }
    return labels.get(role, role)


def _top_texts(values: list[str], fallback: list[str] | None = None) -> list[str]:
    if not values:
        return fallback or []
    counts = defaultdict(int)
    for value in values:
        if value:
            counts[value[:160]] += 1
    return [item[0] for item in sorted(counts.items(), key=lambda item: -item[1])[:3]]


def _top_reason_labels(reasons: list[RecommendationReasonClaim]) -> list[str]:
    if not reasons:
        return ["暂无稳定推荐理由"]
    counts = defaultdict(int)
    for reason in reasons:
        counts[_reason_type_label(reason.reason_type)] += 1
    return [item[0] for item in sorted(counts.items(), key=lambda item: -item[1])[:4]]


def _reason_consistency(reasons: list[RecommendationReasonClaim]) -> str:
    if len(reasons) < 2:
        return "INSUFFICIENT_DATA"
    counts = defaultdict(int)
    for reason in reasons:
        counts[reason.reason_type] += 1
    top = max(counts.values())
    rate = top / len(reasons)
    if rate >= 0.75:
        return "HIGH"
    if rate >= 0.45:
        return "MEDIUM"
    return "LOW"


def _confidence_for_claim(recommendation_type: str, entity_source: str) -> float:
    base = 0.7 if recommendation_type in {"POSITIVE_RECOMMENDATION", "TOP_RECOMMENDATION", "NEGATIVE_RECOMMENDATION"} else 0.6
    if entity_source == "ANSWER_PATTERN":
        base -= 0.1
    return round(max(0.3, min(base, 0.95)), 2)


def _normalize_key(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", (value or "").lower())


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _stability(numerator: int, denominator: int) -> str:
    if denominator < 3:
        return "INSUFFICIENT_DATA"
    rate = numerator / denominator
    if rate >= 0.75:
        return "HIGH"
    if rate >= 0.33:
        return "MEDIUM"
    if rate > 0:
        return "LOW"
    return "INSUFFICIENT_DATA"
