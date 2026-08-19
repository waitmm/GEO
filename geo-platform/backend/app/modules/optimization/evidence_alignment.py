"""Layer 5 — Evidence Alignment：Entity Scope Precheck + EvidenceAlignmentJudge。

关键纪律：
- 调用 Alignment Judge 前先做确定性 Entity Scope Precheck：
  竞品第一方 Claim 不得 SUPPORT 目标品牌的 ENTITY_SPECIFIC Reason。
- Judge 只看到 SourceClaim + RecommendationReason + entity scope 元数据；
  禁止看到 Strategy/Action/Experiment Outcome。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import EvidenceAlignment, Project, RecommendationEvent, SourceClaim
from app.services.semantic_llm.base import SemanticLLMError
from app.services.semantic_llm.deepseek import DeepSeekClient
from app.services.serialization import dumps, loads

ALIGNMENT_PROMPT_VERSION = "evidence_alignment.v1"
ALIGNMENT_SCHEMA_VERSION = "v1"

ALIGNMENT_SYSTEM = """你是一个严格的语义证据关系判断器。

你会得到：

A. 一个 Recommendation Reason
B. 一个已经 Grounded 的 Source Claim

你的任务只判断 B 与 A 的语义关系。

禁止：
- 使用外部知识；
- 补充源文本没有的能力；
- 因为品牌知名而推断关系；
- 因为两个句子关键词相似就判断 SUPPORTS；
- 把 RELATED 当成 SUPPORTS。

SUPPORTS：
Source Claim 提供了足以支持 Recommendation Reason 的事实或评价。

CONTRADICTS：
Source Claim 明确与 Recommendation Reason 相反。

RELATED：
主题相关，但不能证明 Reason。

NONE：
没有实质关系。

如果无法确定，优先 RELATED 或 NONE，而不是 SUPPORTS。

输出格式（纯 JSON 对象）：
{
  "relation": "SUPPORTS",
  "rationale": "Source Claim 明确描述了对应能力，该能力与 Reason 中的选择理由一致。",
  "confidence_raw": 0.91
}

必须输出纯 JSON 对象（DeepSeek JSON mode 要求）。
"""


class EvidenceAlignmentJudge:
    def __init__(self, client: DeepSeekClient | None = None) -> None:
        self.client = client or DeepSeekClient()
        self.settings = get_settings()

    def judge(self, reason_text: str, source_claim_text: str, db: Session | None = None) -> dict:
        return self.client.structured_generate_sync(
            system_prompt=ALIGNMENT_SYSTEM,
            user_payload={
                "reason": reason_text,
                "source_claim": source_claim_text,
            },
            response_schema=dict,
            prompt_version=ALIGNMENT_PROMPT_VERSION,
            schema_version=ALIGNMENT_SCHEMA_VERSION,
            max_tokens=2048,
            db=db,
        )


def entity_scope_precheck(reason_scope: str, reason_entity: str, claim: SourceClaim) -> str:
    """确定性 Entity Scope Precheck。

    返回：
    - "PASS"：允许进入 Judge
    - "COMPETITOR_CONTEXT"：竞品实体冲突，确定性归类，不调 LLM
    - "PASS_MARKET"：MARKET_CRITERION 允许竞品 Claim 参与（验证市场标准存在性）
    """
    subject = (claim.subject_entity or "").strip()
    owner = (claim.source_owner_entity or "").strip()

    if reason_scope == "MARKET_CRITERION":
        return "PASS_MARKET"

    # ENTITY_SPECIFIC：Reason 绑定某实体，Source Claim 主体必须是同一实体
    if not reason_entity:
        return "PASS"

    def _same_entity(a: str, b: str) -> bool:
        if not a or not b:
            return False
        # 实体归一：包含关系（"商加加外链后台" 指 商加加）或精确相等
        return a == b or a in b or b in a

    if _same_entity(subject, reason_entity):
        return "PASS"

    # 语义主体未识别时，以 owner 弱匹配一次
    if subject in {"UNKNOWN", ""} and _same_entity(owner, reason_entity):
        return "PASS"

    return "COMPETITOR_CONTEXT"


def run_evidence_alignment(db: Session, project: Project, prompt_id: int, run_ids: list[int]) -> dict:
    """Layer 5 主流程：Reason × SourceClaim → relation。"""
    # 幂等：清理该 prompt 的历史 alignment 后重跑（不累积爆炸）
    db.query(EvidenceAlignment).filter(
        EvidenceAlignment.project_id == project.id,
        EvidenceAlignment.prompt_id == prompt_id,
    ).delete()
    db.commit()

    events = db.query(RecommendationEvent).filter(
        RecommendationEvent.project_id == project.id,
        RecommendationEvent.prompt_id == prompt_id,
        RecommendationEvent.run_id.in_(run_ids),
        RecommendationEvent.review_status.in_(["MACHINE_GROUNDED", "HUMAN_CONFIRMED"]),
    ).all()
    claims = db.query(SourceClaim).filter(
        SourceClaim.project_id == project.id,
        SourceClaim.review_status == "MACHINE_GROUNDED",
    ).all()

    # 去重：按 unique (reason_text, reason_scope, reason_entity) 遍历，而非 12 个重复 event
    unique_reasons: dict[tuple, dict] = {}
    for event in events:
        for reason in loads(event.reasons_json, []):
            reason_text = reason.get("normalized_reason") or ""
            if not reason_text:
                continue
            reason_scope = reason.get("reason_scope", "ENTITY_SPECIFIC")
            reason_entity = event.entity_text if reason_scope == "ENTITY_SPECIFIC" else ""
            key = (reason_text, reason_scope, reason_entity)
            if key not in unique_reasons:
                unique_reasons[key] = {
                    "text": reason_text,
                    "scope": reason_scope,
                    "entity": reason_entity,
                    "event_id": event.id,
                    "run_id": event.run_id,
                }

    judge = EvidenceAlignmentJudge()
    created = 0
    competitor_context = 0
    skipped_unknown = 0
    errors: list[str] = []

    for key, reason in unique_reasons.items():
        reason_text, reason_scope, reason_entity = key
        for claim in claims:
            # subject UNKNOWN 的 claim 无法判断实体关系 → 跳过（不制造噪声记录）
            if claim.subject_entity in {"", "UNKNOWN"}:
                skipped_unknown += 1
                continue

            precheck = entity_scope_precheck(reason_scope, reason_entity, claim)
            if precheck == "COMPETITOR_CONTEXT":
                db.add(EvidenceAlignment(
                    project_id=project.id, prompt_id=prompt_id, run_id=reason["run_id"],
                    recommendation_event_id=reason["event_id"],
                    recommendation_reason_id=f"reason:{reason_text[:60]}",
                    source_document_id=claim.source_document_id,
                    source_claim_id=claim.id,
                    relation="RELATED",
                    scope_relation="COMPETITOR_CONTEXT",
                    provider="deterministic",
                    model="scope_precheck",
                    prompt_version="entity_scope_precheck.v1",
                    schema_version="v1",
                    machine_payload_json=dumps({"precheck": precheck}),
                    review_status="MACHINE_GROUNDED",
                ))
                competitor_context += 1
                continue

            try:
                result = judge.judge(reason_text, claim.normalized_claim, db=db)
            except SemanticLLMError as e:
                errors.append(str(e)[:120])
                continue

            relation = (result or {}).get("relation", "NONE")
            db.add(EvidenceAlignment(
                project_id=project.id, prompt_id=prompt_id, run_id=reason["run_id"],
                recommendation_event_id=reason["event_id"],
                recommendation_reason_id=f"reason:{reason_text[:60]}",
                source_document_id=claim.source_document_id,
                source_claim_id=claim.id,
                relation=relation,
                scope_relation=precheck,
                provider=judge.client.provider,
                model=judge.settings.deepseek_model,
                prompt_version=ALIGNMENT_PROMPT_VERSION,
                schema_version=ALIGNMENT_SCHEMA_VERSION,
                machine_payload_json=dumps(result or {}),
                review_status="MACHINE_GROUNDED",
            ))
            created += 1

    db.commit()
    return {
        "status": "OK",
        "unique_reasons": len(unique_reasons),
        "alignments_created": created,
        "competitor_context": competitor_context,
        "skipped_unknown_subject": skipped_unknown,
        "errors": errors[:5],
    }
