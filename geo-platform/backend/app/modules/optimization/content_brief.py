"""渠道选择 → Experiment 草案 → 内容大纲 → 详细 Brief。

全部基于已确认的证据链生成，不制造新事实。
- 竞品 SourceClaim 只作市场参照（明确标注），不复制竞品表述。
- 爱短链能力描述只来自 Product Truth + 第一方页面证据。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import (
    EvidenceAlignment,
    OptimizationAction,
    OptimizationExperiment,
    OptimizationIssue,
    Project,
    Prompt,
    RecommendationEvent,
    SourceClaim,
    TargetBrandCapabilityTruth,
)
from app.services.semantic_llm.base import SemanticLLMError
from app.services.semantic_llm.deepseek import DeepSeekClient
from app.services.serialization import dumps, loads

BRIEF_PROMPT_VERSION = "content_brief.v1"
BRIEF_SCHEMA_VERSION = "v1"

OUTLINE_SYSTEM = """你是一个 GEO 内容策略助手。基于给定证据链，为品牌生成内容大纲。

严格规则：
1. 只使用提供的事实：市场选择标准、竞品证据（仅市场参照）、品牌 Product Truth、品牌第一方证据。
2. 禁止编造品牌不具备的能力。
3. 竞品能力描述不得直接复制，只能作为"市场需要什么"的参照。
4. 大纲必须可追溯到证据：每节标注依据来源。
5. 输出纯 JSON 对象。

输出格式：
{
  "title": "内容标题",
  "outline": [
    {
      "section": "章节标题",
      "key_points": ["要点1", "要点2"],
      "evidence_basis": "依据来源（如：市场标准-加密短链能力）"
    }
  ]
}
"""

BRIEF_SYSTEM = """你是一个 GEO 内容策略助手。基于已确认的大纲，生成详细内容 brief。

严格规则：
1. 只展开大纲中的要点，不新增事实。
2. 爱短链能力描述只来自 Product Truth。
3. 不写"全网第一""最好"等无法验证的表述。
4. 每个 section 必须列出写作要求 + 可核验事实来源。
5. 输出纯 JSON 对象。

输出格式：
{
  "title": "标题",
  "sections": [
    {
      "section": "章节标题",
      "writing_requirements": "写作要求",
      "facts_to_include": ["可核验事实"],
      "facts_source": "事实来源",
      "competitor_reference_only": "竞品参照提示（仅市场参照）"
    }
  ]
}
"""


def _collect_evidence_context(db: Session, project: Project, prompt_id: int) -> dict:
    """汇总已确认的证据链上下文。"""
    # 市场标准（Reason，人工确认的事件）
    events = db.query(RecommendationEvent).filter(
        RecommendationEvent.project_id == project.id,
        RecommendationEvent.prompt_id == prompt_id,
        RecommendationEvent.review_status == "HUMAN_CONFIRMED",
    ).all()
    reasons = []
    for e in events:
        for r in loads(e.reasons_json, []):
            reasons.append({"reason": r.get("normalized_reason"), "scope": r.get("reason_scope")})

    # 竞品 SourceClaim（SUPPORTS 且人工确认）
    supports = db.query(EvidenceAlignment).filter(
        EvidenceAlignment.project_id == project.id,
        EvidenceAlignment.prompt_id == prompt_id,
        EvidenceAlignment.relation == "SUPPORTS",
        EvidenceAlignment.review_status == "HUMAN_CONFIRMED",
    ).all()
    competitor_claims = []
    for a in supports:
        claim = db.get(SourceClaim, a.source_claim_id)
        if claim and claim.source_role in {"COMPETITOR_FIRST_PARTY", "UNKNOWN"}:
            competitor_claims.append({
                "claim": claim.normalized_claim,
                "source": claim.source_owner_entity,
            })

    # 品牌 Product Truth
    truths = db.query(TargetBrandCapabilityTruth).filter(
        TargetBrandCapabilityTruth.project_id == project.id,
        TargetBrandCapabilityTruth.product_truth_status == "SUPPORTED",
    ).all()

    return {
        "prompt": prompt_id,
        "brand": project.brand_name,
        "market_criteria": [r["reason"] for r in reasons],
        "competitor_evidence_reference": competitor_claims[:8],
        "brand_product_truth": [t.capability_key for t in truths],
        "brand_first_party_evidence": [],
    }


class ContentBriefGenerator:
    def __init__(self, client: DeepSeekClient | None = None) -> None:
        self.client = client or DeepSeekClient()

    def generate_outline(self, context: dict, db: Session | None = None) -> dict:
        return self.client.structured_generate_sync(
            system_prompt=OUTLINE_SYSTEM,
            user_payload={"evidence_context": context},
            response_schema=dict,
            prompt_version=BRIEF_PROMPT_VERSION,
            schema_version=BRIEF_SCHEMA_VERSION,
            max_tokens=4096,
            db=db,
        )

    def generate_brief(self, outline: dict, context: dict, db: Session | None = None) -> dict:
        return self.client.structured_generate_sync(
            system_prompt=BRIEF_SYSTEM,
            user_payload={"outline": outline, "evidence_context": context},
            response_schema=dict,
            prompt_version=BRIEF_PROMPT_VERSION,
            schema_version=BRIEF_SCHEMA_VERSION,
            max_tokens=8192,
            db=db,
        )


def create_experiment_draft(
    db: Session,
    project: Project,
    prompt: Prompt,
    run_ids: list[int],
    channel: str,
    target_url: str = "",
) -> dict:
    """渠道选择 → 创建新的 Experiment 草案（不碰 #13）。"""
    channel_info = {
        "OWNED_NEW_PAGE": {"target_type": "owned_content", "action_type": "content_create"},
        "OWNED_UPDATE": {"target_type": "owned_content", "action_type": "content_update"},
        "ZHIHU": {"target_type": "external_platform", "action_type": "article_publish"},
        "BAIJIAHAO": {"target_type": "external_platform", "action_type": "article_publish"},
        "BILIBILI": {"target_type": "external_platform", "action_type": "video_publish"},
    }
    info = channel_info.get(channel, {"target_type": "owned_content", "action_type": "content_create"})

    # 创建 Issue（复用现有未关闭 issue 或新建）
    issue = (
        db.query(OptimizationIssue)
        .filter(
            OptimizationIssue.project_id == project.id,
            OptimizationIssue.prompt_id == prompt.id,
            OptimizationIssue.status.in_(["confirmed", "in_action"]),
        )
        .first()
    )
    if not issue:
        issue = OptimizationIssue(
            project_id=project.id,
            prompt_id=prompt.id,
            issue_type="brand_absent",
            status="confirmed",
            severity=4,
            confidence_level="medium",
            analyzable_sample_count=len(run_ids),
            observed_facts_json=dumps({"prompt_text": prompt.prompt_text}),
            diagnosis_summary="EVIDENCE_GAP：能力真实存在但证据未进入 AI 答案",
            confirmed_at=datetime.utcnow(),
        )
        db.add(issue)
        db.flush()

    action = OptimizationAction(
        issue_id=issue.id,
        action_type=info["action_type"],
        target_type=info["target_type"],
        target_url=target_url,
        status="PLANNED",
        priority=4,
        action_summary=f"{channel} 内容干预：爱短链抖音跳转微信能力证据建设",
        action_detail="基于已确认 EVIDENCE_GAP 与人工审核证据链生成",
    )
    db.add(action)
    db.flush()

    experiment = OptimizationExperiment(
        action_id=action.id,
        hypothesis="爱短链具备抖音跳转微信与短链生成能力（Product Truth SUPPORTED），补充该能力的内容证据后，品牌可进入 AI 答案候选",
        target_prompt_scope_json=dumps([prompt.id]),
        primary_metric="brand_mention_rate",
        secondary_metrics_json=dumps(["candidate_capture_rate", "explicit_recommendation_rate"]),
        status="draft",
        release_blocked=True,
        release_blocked_reason="WAITING_FOR_CONTENT_PRODUCTION",
    )
    db.add(experiment)
    db.commit()
    db.refresh(experiment)
    return {
        "experiment_id": experiment.id,
        "action_id": action.id,
        "issue_id": issue.id,
        "channel": channel,
        "status": "draft",
        "release_blocked": True,
    }
