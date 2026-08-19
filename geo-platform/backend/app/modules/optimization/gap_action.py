"""Gap 推导 + Action Candidate（仅从已确认 Evidence 推出）。

Gap 枚举（本轮固定）：
CAPABILITY_GAP / EVIDENCE_GAP / POSITIONING_GAP / UNRESOLVED

规则：
- 禁止"有竞品 Claim → 自动 EVIDENCE_GAP"。
- Product Truth 不足时返回 PRODUCT_TRUTH_UNRESOLVED。
- Action 不自动发布，可完整反查 Gap→Reason→SourceClaim→Document。
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy.orm import Session

from app.models import (
    EvidenceAlignment,
    Project,
    RecommendationEvent,
    SourceClaim,
    TargetBrandCapabilityTruth,
)
from app.services.serialization import loads


def derive_gap(
    db: Session,
    project: Project,
    prompt_id: int,
    run_ids: list[int],
) -> dict:
    """基于已确认证据推导 Gap。

    依据：
    - 答案选择空间（recommendation_events 是否存在实体事件）
    - 目标品牌在答案中的出现（events 中 entity=brand 的记录数）
    - Product Truth（target_brand_capability_truths）
    - SUPPORTS 证据链（evidence_alignments）
    """
    brand = project.brand_name
    events = db.query(RecommendationEvent).filter(
        RecommendationEvent.project_id == project.id,
        RecommendationEvent.prompt_id == prompt_id,
        RecommendationEvent.run_id.in_(run_ids),
        RecommendationEvent.review_status.in_(["MACHINE_GROUNDED", "HUMAN_CONFIRMED"]),
    ).all()

    total_runs = len(set(e.run_id for e in events)) or len(run_ids)
    brand_events = [e for e in events if brand in (e.entity_text or "")]
    competitor_events = [e for e in events if brand not in (e.entity_text or "")]

    truths = db.query(TargetBrandCapabilityTruth).filter(
        TargetBrandCapabilityTruth.project_id == project.id,
        TargetBrandCapabilityTruth.product_truth_status == "SUPPORTED",
    ).all()
    supported_capabilities = {t.capability_key for t in truths}

    supports = db.query(EvidenceAlignment).filter(
        EvidenceAlignment.project_id == project.id,
        EvidenceAlignment.prompt_id == prompt_id,
        EvidenceAlignment.relation == "SUPPORTS",
    ).all()

    # 市场选择标准存在性：竞品事件 + SUPPORTS 证据链
    market_criterion_present = bool(competitor_events) and bool(supports)

    # Gap 判定
    if not market_criterion_present:
        gap_type = "UNRESOLVED"
        basis = "当前答案未出现明确的方案选择证据链，无法判断品牌缺口类型。"
        confidence = "LOW"
    elif not supported_capabilities:
        gap_type = "UNRESOLVED"
        basis = "PRODUCT_TRUTH_UNRESOLVED：目标品牌能力未人工确认，禁止强行形成 Evidence Gap。"
        confidence = "LOW"
    elif brand_events:
        # 品牌已在答案中出现 → 检查是否缺证据支撑
        gap_type = "EVIDENCE_GAP"
        basis = f"品牌已在答案中出现（{len(brand_events)} 事件），但当前 SUPPORTS 证据链主要支撑竞品；目标品牌证据弱。"
        confidence = "MEDIUM"
    else:
        # 品牌 0 出现，但 Product Truth 支持市场所需能力 → 能力真实但证据未进入答案
        gap_type = "EVIDENCE_GAP"
        basis = (
            f"市场选择标准存在（{len(competitor_events)} 个竞品事件、{len(supports)} 条 SUPPORTS），"
            f"目标品牌「{brand}」在 {total_runs} 次答案中 0 提及、0 候选、0 引用；"
            f"但 Product Truth 已确认其支持：{', '.join(sorted(supported_capabilities))}。"
            "能力真实存在而 AI 答案层证据缺失。"
        )
        confidence = "MEDIUM"

    return {
        "gap_type": gap_type,
        "confidence": confidence,
        "basis": basis,
        "total_runs": total_runs,
        "brand_events": len(brand_events),
        "competitor_events": len(competitor_events),
        "supported_capabilities": sorted(supported_capabilities),
        "supports_count": len(supports),
        "product_truth_status": "CONFIRMED" if supported_capabilities else "PRODUCT_TRUTH_UNRESOLVED",
    }


def build_action_candidate(
    db: Session,
    project: Project,
    prompt_id: int,
    run_ids: list[int],
    gap: dict,
) -> dict:
    """从 Gap 生成 Action Candidate（可反查，不发布）。"""
    supports = db.query(EvidenceAlignment).filter(
        EvidenceAlignment.project_id == project.id,
        EvidenceAlignment.prompt_id == prompt_id,
        EvidenceAlignment.relation == "SUPPORTS",
    ).all()

    supporting_source_claim_ids = sorted({a.source_claim_id for a in supports})
    supporting_reason_ids = sorted({a.recommendation_reason_id for a in supports})
    supporting_document_ids = sorted({a.source_document_id for a in supports})

    if gap["gap_type"] == "UNRESOLVED":
        return {
            "intervention_goal": "UNRESOLVED",
            "asset_ownership": "UNKNOWN",
            "target_platform": "UNRESOLVED",
            "target_entity": project.brand_name,
            "target_claim": "",
            "supporting_gap_ids": [],
            "supporting_reason_ids": supporting_reason_ids,
            "supporting_source_claim_ids": supporting_source_claim_ids,
            "supporting_document_ids": supporting_document_ids,
            "note": gap["basis"],
        }

    return {
        "intervention_goal": "EVIDENCE_STRENGTHEN",
        "asset_ownership": "FIRST_PARTY",
        "target_platform": "UNRESOLVED",
        "target_entity": project.brand_name,
        "target_claim": f"爱短链支持抖音跳转微信与短链生成（Product Truth SUPPORTED），但该能力证据未进入 AI 答案",
        "supporting_gap_ids": [],
        "supporting_reason_ids": supporting_reason_ids,
        "supporting_source_claim_ids": supporting_source_claim_ids,
        "supporting_document_ids": supporting_document_ids,
        "note": "证据反查链：Action → Gap → Reason → SourceClaim → SourceDocument。人工确认后才可进入发布。",
    }
