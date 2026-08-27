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
from app.models import EvidenceAlignment, Project, RecommendationEvent, SourceClaim, SourceDocument
from app.modules.optimization.passage_retrieval import (
    ANSWER_BINDING_REASON_SOURCE,
    EVENT_REASON_SOURCE,
    FORMAL_V1_1_INPUT_VERSION,
    _cited_document_ids_for_runs,
    answer_binding_reason_inputs,
)
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


def decision_support_level_from_relation(relation: str) -> str:
    """Compatibility mapping from legacy alignment relation to V1 support level."""
    normalized = (relation or "").upper()
    if normalized == "SUPPORTS":
        return "SUPPORTS"
    if normalized == "CONTRADICTS":
        return "CONTRADICTS"
    if normalized == "RELATED":
        return "LEGACY_RELATED"
    return "NO_SUPPORT"


def run_evidence_alignment(
    db: Session,
    project: Project,
    prompt_id: int,
    run_ids: list[int],
    include_answer_binding_reasons: bool = False,
    doc_id_filter: list[int] | None = None,
) -> dict:
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
    claims_query = db.query(SourceClaim).filter(
        SourceClaim.project_id == project.id,
        SourceClaim.review_status == "MACHINE_GROUNDED",
    )
    cited_doc_ids: set[int] = set()
    if include_answer_binding_reasons:
        docs = db.query(SourceDocument).all()
        cited_doc_ids = _cited_document_ids_for_runs(db, run_ids, docs)
        if cited_doc_ids:
            claims_query = claims_query.filter(SourceClaim.source_document_id.in_(cited_doc_ids))
    if doc_id_filter:
        claims_query = claims_query.filter(SourceClaim.source_document_id.in_([int(item) for item in doc_id_filter]))
    claims = claims_query.all()

    # 语义理由可以去重以复用判断，但每个 Run/Binding observation 必须保留。
    # 否则 6 个稳定样本会被无声折叠成第一个 Run 的单次事实。
    unique_reasons: dict[tuple, dict] = {}
    legacy_reasons_added = 0
    binding_reasons_added = 0
    for event in events:
        for reason in loads(event.reasons_json, []):
            reason_text = reason.get("normalized_reason") or ""
            if not reason_text:
                continue
            reason_scope = reason.get("reason_scope", "ENTITY_SPECIFIC")
            reason_entity = event.entity_text if reason_scope == "ENTITY_SPECIFIC" else ""
            key = (reason_text, reason_scope, reason_entity)
            observation = {
                "event_id": event.id,
                "run_id": event.run_id,
                "reason_id": f"reason:{reason_text[:60]}",
                "reason_source": EVENT_REASON_SOURCE,
            }
            if key not in unique_reasons:
                unique_reasons[key] = {
                    "text": reason_text,
                    "scope": reason_scope,
                    "entity": reason_entity,
                    "reason_source": EVENT_REASON_SOURCE,
                    "observations": [],
                }
                legacy_reasons_added += 1
            unique_reasons[key]["observations"].append(observation)

    binding_reasons = answer_binding_reason_inputs(db, project, prompt_id, run_ids) if include_answer_binding_reasons else []
    for reason in binding_reasons:
        reason_text = reason.get("text") or ""
        if not reason_text:
            continue
        reason_scope = reason.get("scope") or "ENTITY_SPECIFIC"
        reason_entity = reason.get("entity") or ""
        key = (reason_text, reason_scope, reason_entity)
        observation = {
            "event_id": reason["event_id"],
            "run_id": reason["run_id"],
            "reason_id": reason.get("reason_id") or f"answer_unit:{reason_text[:40]}",
            "reason_source": ANSWER_BINDING_REASON_SOURCE,
            "decision_role": reason.get("decision_role"),
            "binding_strength": reason.get("binding_strength"),
            "shadow_run_id": reason.get("shadow_run_id"),
            "answer_unit_id": reason.get("answer_unit_id"),
            "decision_binding_id": reason.get("decision_binding_id"),
        }
        if key not in unique_reasons:
            unique_reasons[key] = {
                "text": reason_text,
                "scope": reason_scope,
                "entity": reason_entity,
                "reason_source": ANSWER_BINDING_REASON_SOURCE,
                "observations": [],
            }
            binding_reasons_added += 1
        unique_reasons[key]["observations"].append(observation)

    judge = EvidenceAlignmentJudge()
    created = 0
    judge_calls = 0
    competitor_context = 0
    skipped_unknown = 0
    errors: list[str] = []
    judge_cache: dict[tuple[str, int], dict] = {}

    for key, reason in unique_reasons.items():
        reason_text, reason_scope, reason_entity = key
        observations = reason.get("observations") or []
        coverage_payload = {
            "semantic_reason_key": "|".join(str(part or "") for part in key),
            "observed_run_ids": sorted({int(obs["run_id"]) for obs in observations if obs.get("run_id")}),
            "observed_event_ids": sorted({int(obs["event_id"]) for obs in observations if obs.get("event_id")}),
            "observed_answer_unit_ids": sorted({
                int(obs["answer_unit_id"]) for obs in observations if obs.get("answer_unit_id")
            }),
            "observed_decision_binding_ids": sorted({
                int(obs["decision_binding_id"]) for obs in observations if obs.get("decision_binding_id")
            }),
            "run_coverage_count": len({int(obs["run_id"]) for obs in observations if obs.get("run_id")}),
            "run_coverage_denominator": len({int(run_id) for run_id in run_ids}),
        }
        for claim in claims:
            # subject UNKNOWN 的 claim 无法判断实体关系 → 跳过（不制造噪声记录）
            if claim.subject_entity in {"", "UNKNOWN"}:
                skipped_unknown += len(observations)
                continue

            precheck = entity_scope_precheck(reason_scope, reason_entity, claim)
            if precheck == "COMPETITOR_CONTEXT":
                for observation in observations:
                    reason_payload = _observation_reason_payload(reason, observation, coverage_payload)
                    db.add(EvidenceAlignment(
                        project_id=project.id, prompt_id=prompt_id, run_id=observation["run_id"],
                        recommendation_event_id=observation["event_id"],
                        recommendation_reason_id=str(observation.get("reason_id") or f"reason:{reason_text[:60]}")[:120],
                        source_document_id=claim.source_document_id,
                        source_claim_id=claim.id,
                        relation="RELATED",
                        scope_relation="COMPETITOR_CONTEXT",
                        provider="deterministic",
                        model="scope_precheck",
                        prompt_version="entity_scope_precheck.v1",
                        schema_version="v1",
                        machine_payload_json=dumps({"precheck": precheck, **reason_payload}),
                        review_status="MACHINE_GROUNDED",
                    ))
                    competitor_context += 1
                continue

            try:
                cache_key = (reason_text, claim.id)
                if cache_key not in judge_cache:
                    judge_cache[cache_key] = judge.judge(reason_text, claim.normalized_claim, db=db)
                    judge_calls += 1
                result = judge_cache[cache_key]
            except SemanticLLMError as e:
                errors.append(str(e)[:120])
                continue

            relation = (result or {}).get("relation", "NONE")
            for observation in observations:
                reason_payload = _observation_reason_payload(reason, observation, coverage_payload)
                db.add(EvidenceAlignment(
                    project_id=project.id, prompt_id=prompt_id, run_id=observation["run_id"],
                    recommendation_event_id=observation["event_id"],
                    recommendation_reason_id=str(observation.get("reason_id") or f"reason:{reason_text[:60]}")[:120],
                    source_document_id=claim.source_document_id,
                    source_claim_id=claim.id,
                    relation=relation,
                    scope_relation=precheck,
                    provider=judge.client.provider,
                    model=judge.settings.deepseek_model,
                    prompt_version=ALIGNMENT_PROMPT_VERSION,
                    schema_version="v1",
                    machine_payload_json=dumps({**(result or {}), **reason_payload}),
                    review_status="MACHINE_GROUNDED",
                ))
                created += 1

    db.commit()
    return {
        "status": "OK",
        "unique_reasons": len(unique_reasons),
        "reason_observations": sum(len(reason.get("observations") or []) for reason in unique_reasons.values()),
        "legacy_event_reasons": legacy_reasons_added,
        "answer_binding_reasons": binding_reasons_added,
        "answer_binding_candidates": len(binding_reasons) if include_answer_binding_reasons else 0,
        "include_answer_binding_reasons": include_answer_binding_reasons,
        "phase1_cited_source_claim_scope": len(cited_doc_ids) if include_answer_binding_reasons else 0,
        "doc_id_filter": doc_id_filter or [],
        "alignments_created": created,
        "judge_calls": judge_calls,
        "competitor_context": competitor_context,
        "skipped_unknown_subject": skipped_unknown,
        "errors": errors[:5],
    }


def _observation_reason_payload(reason: dict, observation: dict, coverage_payload: dict) -> dict:
    reason_source = observation.get("reason_source") or reason.get("reason_source")
    return {
        "reason_source": reason_source,
        "formal_input_version": FORMAL_V1_1_INPUT_VERSION
        if reason_source == ANSWER_BINDING_REASON_SOURCE else "",
        "answer_unit_id": observation.get("answer_unit_id"),
        "decision_binding_id": observation.get("decision_binding_id"),
        "decision_role": observation.get("decision_role"),
        "binding_strength": observation.get("binding_strength"),
        "shadow_run_id": observation.get("shadow_run_id"),
        **coverage_payload,
    }
