"""Layer 5 — Evidence Alignment：Entity Scope Precheck + EvidenceAlignmentJudge。

关键纪律：
- 调用 Alignment Judge 前先做确定性 Entity Scope Precheck：
  竞品第一方 Claim 不得 SUPPORT 目标品牌的 ENTITY_SPECIFIC Reason。
- Judge 只看到 SourceClaim + RecommendationReason + entity scope 元数据；
  禁止看到 Strategy/Action/Experiment Outcome。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    EvidenceAlignment,
    EvidenceAlignmentMaterialization,
    LLMCallCache,
    Project,
    RecommendationEvent,
    SourceClaim,
    SourceDocument,
)
from app.modules.optimization.materialization_executor import (
    FAILED_FINAL,
    HIT,
    OWNED_BY_OTHER,
    batch_count as materialization_batch_count,
    claim_materialization,
    mark_materialization_failed,
    new_executor_id,
    release_materialization_owner,
    wait_for_materialization,
)
from app.modules.optimization.passage_retrieval import (
    ANSWER_BINDING_REASON_SOURCE,
    EVENT_REASON_SOURCE,
    FORMAL_V1_1_INPUT_VERSION,
    _cited_document_ids_for_runs,
    answer_binding_reason_inputs,
)
from app.modules.optimization.source_claim import _source_claim_row_key
from app.services.semantic_llm.base import SemanticLLMError
from app.services.semantic_llm.deepseek import DeepSeekClient
from app.services.serialization import dumps, loads

ALIGNMENT_PROMPT_VERSION = "evidence_alignment.v1"
ALIGNMENT_SCHEMA_VERSION = "v1"
ALIGNMENT_MATERIALIZATION_CONTRACT = "ALIGNMENT_V1"
ALIGNMENT_JUDGE_IMPL_VERSION = "evidence_alignment_judge.impl.v1"
ALIGNMENT_PROVIDER = "deepseek"

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

REVIEW_CARRY_FORWARD_STATUSES = {"HUMAN_CONFIRMED", "HUMAN_REJECTED"}


def _compact_alignment_text(value: str) -> str:
    return " ".join((value or "").split())


def _stable_alignment_hash(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_alignment_reason_text(reason_text: str) -> str:
    return _compact_alignment_text(reason_text)


def normalize_alignment_source_claim_text(source_claim_text: str) -> str:
    return _compact_alignment_text(source_claim_text)


def alignment_answer_unit_semantic_hash(reason_text: str, reason_scope: str, reason_entity: str) -> str:
    return _stable_alignment_hash({
        "semantic_contract": "ALIGNMENT_ANSWER_PROPOSITION_V1",
        "reason": normalize_alignment_reason_text(reason_text),
        "scope": reason_scope or "ENTITY_SPECIFIC",
        "entity": _compact_alignment_text(reason_entity),
    })


def alignment_source_claim_semantic_hash(claim: SourceClaim) -> str:
    return _stable_alignment_hash({
        "semantic_contract": "ALIGNMENT_SOURCE_CLAIM_PROPOSITION_V1",
        "subject_entity": _compact_alignment_text(claim.subject_entity or claim.subject_text or ""),
        "predicate": _compact_alignment_text(claim.predicate or ""),
        "object_text": _compact_alignment_text(claim.object_text or ""),
        "normalized_claim": normalize_alignment_source_claim_text(claim.normalized_claim or claim.source_span or ""),
        "source_span": _compact_alignment_text(claim.source_span or ""),
        "claim_type": (claim.claim_type or "OTHER").upper(),
        "polarity": (claim.polarity or "NEUTRAL").upper(),
        "schema_version": claim.schema_version or "",
    })


def build_alignment_materialization_key(
    reason_text: str,
    reason_scope: str,
    reason_entity: str,
    claim: SourceClaim,
    contract_version: str = ALIGNMENT_MATERIALIZATION_CONTRACT,
) -> str:
    return _stable_alignment_hash({
        "contract_version": contract_version,
        "answer_unit_semantic_hash": alignment_answer_unit_semantic_hash(reason_text, reason_scope, reason_entity),
        "source_claim_semantic_hash": alignment_source_claim_semantic_hash(claim),
    })


def alignment_llm_input_hash(reason_text: str, source_claim_text: str) -> str:
    payload = {
        "system": ALIGNMENT_SYSTEM,
        "payload": {
            "reason": normalize_alignment_reason_text(reason_text),
            "source_claim": normalize_alignment_source_claim_text(source_claim_text),
        },
        "pv": ALIGNMENT_PROMPT_VERSION,
        "sv": ALIGNMENT_SCHEMA_VERSION,
    }
    return _stable_alignment_hash(payload)


def resolve_alignment_materialization_compatibility(
    materialization: EvidenceAlignmentMaterialization | None,
    contract_version: str = ALIGNMENT_MATERIALIZATION_CONTRACT,
) -> str:
    if materialization is None:
        return "MISSING"
    if materialization.status != "DONE":
        return materialization.status or "UNKNOWN"
    if materialization.contract_version != contract_version:
        return "STALE_SCHEMA"
    if not materialization.answer_unit_semantic_hash or not materialization.source_claim_semantic_hash:
        return "UNKNOWN"
    return "COMPATIBLE"


def _cached_alignment_payload(db: Session, reason_text: str, source_claim_text: str, model: str) -> dict | None:
    row = (
        db.query(LLMCallCache)
        .filter(
            LLMCallCache.provider == ALIGNMENT_PROVIDER,
            LLMCallCache.model == model,
            LLMCallCache.prompt_version == ALIGNMENT_PROMPT_VERSION,
            LLMCallCache.schema_version == ALIGNMENT_SCHEMA_VERSION,
            LLMCallCache.input_hash == alignment_llm_input_hash(reason_text, source_claim_text),
        )
        .first()
    )
    return loads(row.parsed_payload_json, {}) if row else None


def _append_unique_ids(existing_json: str, values: list[int]) -> str:
    existing = loads(existing_json, [])
    seen = {str(item) for item in existing}
    result = list(existing)
    for value in values:
        key = str(value)
        if key in seen:
            continue
        result.append(value)
        seen.add(key)
    return dumps(result)


def _alignment_result_payload(result: dict, relation: str | None = None) -> dict:
    payload = dict(result or {})
    payload["relation"] = (relation or payload.get("relation") or "NONE").upper()
    payload["rationale"] = payload.get("rationale") or ""
    try:
        payload["confidence_raw"] = float(payload.get("confidence_raw") or 0.0)
    except (TypeError, ValueError):
        payload["confidence_raw"] = 0.0
    return payload


def _materialize_alignment_result(
    db: Session,
    *,
    materialization: EvidenceAlignmentMaterialization,
    result: dict,
) -> None:
    payload = _alignment_result_payload(result)
    materialization.status = "DONE"
    materialization.compatibility_status = "COMPATIBLE"
    materialization.verdict = payload["relation"]
    materialization.rationale = payload.get("rationale", "")
    materialization.confidence_raw = payload.get("confidence_raw", 0.0)
    materialization.output_payload_json = dumps(payload)
    materialization.output_hash = _stable_alignment_hash(payload)
    materialization.error_message = ""
    materialization.completed_at = datetime.utcnow()


def _populate_alignment_materialization_from_legacy(
    materialization: EvidenceAlignmentMaterialization,
    *,
    legacy_row: EvidenceAlignment,
    answer_semantic_hash: str,
    source_claim_semantic_hash: str,
    output_payload: dict,
    model: str,
) -> None:
    now = datetime.utcnow()
    materialization.answer_unit_semantic_hash = answer_semantic_hash
    materialization.source_claim_semantic_hash = source_claim_semantic_hash
    materialization.contract_version = ALIGNMENT_MATERIALIZATION_CONTRACT
    materialization.status = "DONE"
    materialization.compatibility_status = "COMPATIBLE"
    materialization.verdict = output_payload["relation"]
    materialization.rationale = output_payload.get("rationale", "")
    materialization.confidence_raw = output_payload.get("confidence_raw", 0.0)
    materialization.output_payload_json = dumps(output_payload)
    materialization.output_hash = _stable_alignment_hash(output_payload)
    materialization.source_alignment_ids_json = dumps([legacy_row.id] if legacy_row.id else [])
    materialization.observed_prompt_ids_json = dumps([legacy_row.prompt_id] if legacy_row.prompt_id else [])
    materialization.observed_run_ids_json = dumps([legacy_row.run_id] if legacy_row.run_id else [])
    materialization.judge_impl_version = ALIGNMENT_JUDGE_IMPL_VERSION
    materialization.prompt_version = ALIGNMENT_PROMPT_VERSION
    materialization.schema_version = ALIGNMENT_SCHEMA_VERSION
    materialization.provider = legacy_row.provider or ALIGNMENT_PROVIDER
    materialization.model = legacy_row.model or model
    materialization.completed_at = now
    materialization.error_message = ""
    release_materialization_owner(materialization)


def _semantic_reason_key_parts(row: EvidenceAlignment) -> tuple[str, str, str] | None:
    payload = loads(row.machine_payload_json, {})
    semantic_key = payload.get("semantic_reason_key") or ""
    parts = semantic_key.split("|")
    if len(parts) >= 3 and parts[0]:
        return parts[0], parts[1] or "ENTITY_SPECIFIC", parts[2] or ""
    return None


def _legacy_alignment_rows_by_materialization_key(
    rows: list[EvidenceAlignment],
    claims_by_id: dict[int, SourceClaim],
) -> dict[str, EvidenceAlignment]:
    result: dict[str, EvidenceAlignment] = {}
    for row in rows:
        if row.prompt_version != ALIGNMENT_PROMPT_VERSION or row.schema_version != ALIGNMENT_SCHEMA_VERSION:
            continue
        claim = claims_by_id.get(int(row.source_claim_id or 0))
        reason_parts = _semantic_reason_key_parts(row)
        if not claim or not reason_parts:
            continue
        key = build_alignment_materialization_key(reason_parts[0], reason_parts[1], reason_parts[2], claim)
        result.setdefault(key, row)
    return result


def _alignment_reason_key(alignment: EvidenceAlignment, payload: dict | None = None) -> str:
    payload = payload or loads(alignment.machine_payload_json, {})
    return _compact_alignment_text(
        payload.get("semantic_reason_key")
        or alignment.recommendation_reason_id
        or ""
    )


def _source_claim_review_key(claim: SourceClaim | None) -> str:
    if not claim:
        return ""
    return _compact_alignment_text(claim.normalized_claim or claim.source_span or "")


def _alignment_review_signature(
    alignment: EvidenceAlignment,
    claim: SourceClaim | None,
    *,
    relation: str | None = None,
    payload: dict | None = None,
) -> tuple[str, int, str, str]:
    return (
        _alignment_reason_key(alignment, payload),
        int(alignment.source_document_id or 0),
        _source_claim_review_key(claim),
        (relation or alignment.relation or "").upper(),
    )


def _review_carry_forward_index(db: Session, project_id: int, prompt_id: int) -> dict[tuple[str, int, str, str], dict]:
    """Capture human-reviewed semantic evidence before idempotent rerun deletes rows."""
    rows = db.query(EvidenceAlignment).filter(
        EvidenceAlignment.project_id == project_id,
        EvidenceAlignment.prompt_id == prompt_id,
        EvidenceAlignment.review_status.in_(REVIEW_CARRY_FORWARD_STATUSES),
    ).all()
    claim_ids = {row.source_claim_id for row in rows if row.source_claim_id}
    claims = {
        claim.id: claim
        for claim in db.query(SourceClaim).filter(SourceClaim.id.in_(claim_ids)).all()
    } if claim_ids else {}
    index: dict[tuple[str, int, str, str], dict] = {}
    for row in rows:
        signature = _alignment_review_signature(row, claims.get(row.source_claim_id))
        if not signature[0] or not signature[2] or not signature[3]:
            continue
        index[signature] = {
            "review_status": row.review_status,
            "reviewer": row.reviewer,
            "source_alignment_id": row.id,
        }
    return index


def _alignment_observation_signature_values(
    *,
    project_id: int,
    prompt_id: int,
    run_id: int | None,
    recommendation_event_id: int | None,
    recommendation_reason_id: str,
    source_document_id: int | None,
    source_claim_id: int | None,
    relation: str,
    prompt_version: str,
    schema_version: str,
) -> tuple:
    return (
        int(project_id or 0),
        int(prompt_id or 0),
        int(run_id or 0),
        int(recommendation_event_id or 0),
        str(recommendation_reason_id or "")[:120],
        int(source_document_id or 0),
        int(source_claim_id or 0),
        (relation or "").upper(),
        prompt_version or "",
        schema_version or "",
    )


def _alignment_observation_signature(row: EvidenceAlignment) -> tuple:
    return _alignment_observation_signature_values(
        project_id=row.project_id,
        prompt_id=row.prompt_id,
        run_id=row.run_id,
        recommendation_event_id=row.recommendation_event_id,
        recommendation_reason_id=row.recommendation_reason_id or "",
        source_document_id=row.source_document_id,
        source_claim_id=row.source_claim_id,
        relation=row.relation or "",
        prompt_version=row.prompt_version or "",
        schema_version=row.schema_version or "",
    )


def _carried_forward_review_payload(carry: dict | None) -> dict:
    if not carry:
        return {}
    return {
        "review_carry_forward": {
            "source_alignment_id": carry.get("source_alignment_id"),
            "source_review_status": carry.get("review_status"),
            "reviewer": carry.get("reviewer"),
            "version": "evidence_review_carry_forward.v1",
        }
    }


def _dedupe_source_claims_for_alignment(claims: list[SourceClaim]) -> tuple[list[SourceClaim], int]:
    """Return one document-level SourceClaim per semantic identity.

    Historical reruns may have inserted duplicate SourceClaim rows for the same
    grounded source sentence. EvidenceAlignment should preserve Run observations
    through its own lineage payload, not multiply formal evidence because a
    document-level claim was re-created with a new row id.
    """
    result: list[SourceClaim] = []
    seen: set[tuple] = set()
    for claim in sorted(claims, key=lambda row: row.id or 0):
        key = _source_claim_row_key(claim)
        if key in seen:
            continue
        seen.add(key)
        result.append(claim)
    return result, len(claims) - len(result)


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
    use_binding_aware_candidates: bool | None = None,
    candidate_dry_run: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict:
    """Layer 5 主流程：Reason × SourceClaim → relation。"""
    settings = get_settings()
    if use_binding_aware_candidates is None:
        use_binding_aware_candidates = settings.use_binding_aware_alignment_candidates_v1_1
    use_binding_aware_candidates = bool(use_binding_aware_candidates)
    use_executor = bool(settings.use_materialization_executor_v1_1)
    executor_id = new_executor_id("evidence_alignment")
    review_carry_forward = _review_carry_forward_index(db, project.id, prompt_id)
    existing_alignment_rows = db.query(EvidenceAlignment).filter(
        EvidenceAlignment.project_id == project.id,
        EvidenceAlignment.prompt_id == prompt_id,
    ).all()
    existing_alignment_claim_ids = {int(row.source_claim_id or 0) for row in existing_alignment_rows if row.source_claim_id}
    existing_alignment_claims = {
        claim.id: claim
        for claim in db.query(SourceClaim).filter(SourceClaim.id.in_(existing_alignment_claim_ids)).all()
    } if existing_alignment_claim_ids else {}
    legacy_alignment_by_key = _legacy_alignment_rows_by_materialization_key(
        existing_alignment_rows,
        existing_alignment_claims,
    )
    existing_observation_signatures = {
        _alignment_observation_signature(row): int(row.id or 0)
        for row in existing_alignment_rows
        if row.id
    }
    if not use_binding_aware_candidates and not candidate_dry_run:
        # Legacy rollback path：旧候选生成仍保持原先“先清理再重跑”的幂等语义。
        db.query(EvidenceAlignment).filter(
            EvidenceAlignment.project_id == project.id,
            EvidenceAlignment.prompt_id == prompt_id,
        ).delete()
        db.commit()
        existing_observation_signatures = {}

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
        claims_query = claims_query.filter(SourceClaim.source_document_id.in_(cited_doc_ids))
    if doc_id_filter is not None:
        claims_query = claims_query.filter(SourceClaim.source_document_id.in_([int(item) for item in doc_id_filter]))
    claims, deduped_source_claims = _dedupe_source_claims_for_alignment(claims_query.all())

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

    candidate_build = None
    candidate_key_filter: set[str] | None = None
    if use_binding_aware_candidates:
        from app.modules.optimization.evidence_alignment_candidates import (
            SELECTED_POLICY,
            build_evidence_alignment_candidates,
            run_doc_ids_from_source_documents,
        )

        source_documents = db.query(SourceDocument).all()
        run_doc_ids = run_doc_ids_from_source_documents(
            db,
            run_ids=run_ids,
            source_documents=source_documents,
        )
        candidate_build = build_evidence_alignment_candidates(
            db,
            project=project,
            prompt_id=prompt_id,
            run_ids=run_ids,
            claims=claims,
            run_doc_ids=run_doc_ids,
            top_k=5,
            selected_policy=SELECTED_POLICY,
            include_answer_binding_reasons=include_answer_binding_reasons,
        )
        unique_reasons = candidate_build["reasons"]
        claims = candidate_build["scoped_claims"]
        candidate_key_filter = set(candidate_build["selected_candidate_items"])
        legacy_reasons_added = sum(
            1 for reason in unique_reasons.values()
            if reason.get("reason_source") == EVENT_REASON_SOURCE
        )
        binding_reasons_added = sum(
            1 for reason in unique_reasons.values()
            if any(
                obs.get("reason_source") == ANSWER_BINDING_REASON_SOURCE
                for obs in reason.get("observations") or []
            )
        )
        if candidate_dry_run:
            recall_layer_counts = {
                layer: len(candidate_build["recall_layer_keys"].get(layer, set()))
                for layer in ["L0_EXPLICIT", "L1_ANSWER_CONTEXT", "L2_RUN_SCOPE", "L3_PROMPT_SCOPE"]
            }
            selected_items = candidate_build["selected_candidate_items"]
            return {
                "status": "OK",
                "candidate_dry_run": True,
                "candidate_builder_mode": candidate_build["builder_mode"],
                "candidate_policy": candidate_build["candidate_policy"],
                "candidate_builder_cutover_enabled": use_binding_aware_candidates,
                "legacy_candidate_builder_rollback_available": True,
                "production_candidate_keys": len(selected_items),
                "candidate_keys": sorted(selected_items.keys()),
                "candidate_key_hash": _stable_alignment_hash(sorted(selected_items.keys())),
                "current_candidate_keys": len(candidate_build["current_candidate_items"]),
                "hard_topk_candidate_keys": len(candidate_build["hard_topk_candidate_items"]),
                "recall_layer_counts": recall_layer_counts,
                "fallback_trigger_counts": candidate_build["fallback_trigger_counts"],
                "l0_status": candidate_build["l0_status"],
                "l1_status": candidate_build["l1_status"],
                "l2_status": candidate_build["l2_status"],
                "l2_attempted_reason_count": candidate_build["l2_attempted_reason_count"],
                "l2_matched_reason_count": candidate_build["l2_matched_reason_count"],
                "l3_attempted_reason_count": candidate_build["l3_attempted_reason_count"],
                "boundary_tie_stats": candidate_build["boundary_tie_stats"],
                "source_claim_ids": sorted({
                    int(item["claim"].id or 0)
                    for item in selected_items.values()
                    if item.get("claim") is not None
                }),
                "deduped_source_claims": candidate_build["deduped_source_claims"],
            }

    judge = EvidenceAlignmentJudge()
    created = 0
    judge_calls = 0
    competitor_context = 0
    carried_forward_reviews = 0
    skipped_unknown = 0
    errors: list[str] = []
    materialization_hit_count = 0
    legacy_reuse_count = 0
    llm_call_cache_hit_count = 0
    actual_alignment_llm_calls = 0
    materializations_created = 0
    failed_retryable_count = 0
    materialization_cache: dict[str, EvidenceAlignmentMaterialization] = {}
    existing_alignment_reused = 0
    claimed_by_current_executor = 0
    owned_by_other_executor = 0
    lease_reclaimed = 0
    retry_count = 0
    failed_final_count = 0
    wait_timeout_count = 0
    max_observed_concurrency = 1 if (candidate_key_filter or claims) else 0
    unique_candidate_jobs = len(candidate_key_filter) if candidate_key_filter is not None else len(unique_reasons) * len(claims)
    processed_candidate_jobs = 0
    last_progress_at = datetime.min

    def _emit_progress(processed: int, *, force: bool = False) -> None:
        nonlocal last_progress_at
        if progress_callback is None:
            return
        now = datetime.utcnow()
        should_throttle = (
            not force
            and processed != unique_candidate_jobs
            and processed % 5 != 0
            and (now - last_progress_at).total_seconds() < 10
        )
        if should_throttle:
            return
        last_progress_at = now
        progress_callback({
            "processed": processed,
            "total": unique_candidate_jobs,
            "materialization_hit_count": materialization_hit_count,
            "legacy_reuse_count": legacy_reuse_count,
            "actual_alignment_llm_calls": actual_alignment_llm_calls,
            "llm_call_cache_hit_count": llm_call_cache_hit_count,
            "failed_retryable": failed_retryable_count,
            "failed_final": failed_final_count,
            "wait_timeout_count": wait_timeout_count,
            "competitor_context": competitor_context,
            "skipped_unknown_subject": skipped_unknown,
            "in_progress": max(0, unique_candidate_jobs - processed),
        })

    def _finish_candidate_job() -> None:
        nonlocal processed_candidate_jobs
        processed_candidate_jobs += 1
        _emit_progress(processed_candidate_jobs)

    _emit_progress(0, force=True)

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
            if candidate_key_filter is not None:
                candidate_materialization_key = build_alignment_materialization_key(
                    reason_text,
                    reason_scope,
                    reason_entity,
                    claim,
                )
                if candidate_materialization_key not in candidate_key_filter:
                    continue
            # subject UNKNOWN 的 claim 无法判断实体关系 → 跳过（不制造噪声记录）
            if claim.subject_entity in {"", "UNKNOWN"}:
                skipped_unknown += len(observations)
                _finish_candidate_job()
                continue

            precheck = entity_scope_precheck(reason_scope, reason_entity, claim)
            if precheck == "COMPETITOR_CONTEXT":
                for observation in observations:
                    reason_payload = _observation_reason_payload(reason, observation, coverage_payload)
                    temp_alignment = EvidenceAlignment(
                        project_id=project.id,
                        prompt_id=prompt_id,
                        run_id=observation["run_id"],
                        recommendation_event_id=observation["event_id"],
                        recommendation_reason_id=str(observation.get("reason_id") or f"reason:{reason_text[:60]}")[:120],
                        source_document_id=claim.source_document_id,
                        source_claim_id=claim.id,
                        relation="RELATED",
                    )
                    carry = review_carry_forward.get(
                        _alignment_review_signature(
                            temp_alignment,
                            claim,
                            relation="RELATED",
                            payload=reason_payload,
                        )
                    )
                    if carry:
                        carried_forward_reviews += 1
                    relation = "RELATED"
                    recommendation_reason_id = str(observation.get("reason_id") or f"reason:{reason_text[:60]}")[:120]
                    signature = _alignment_observation_signature_values(
                        project_id=project.id,
                        prompt_id=prompt_id,
                        run_id=observation["run_id"],
                        recommendation_event_id=observation["event_id"],
                        recommendation_reason_id=recommendation_reason_id,
                        source_document_id=claim.source_document_id,
                        source_claim_id=claim.id,
                        relation=relation,
                        prompt_version="entity_scope_precheck.v1",
                        schema_version="v1",
                    )
                    existing_id = existing_observation_signatures.get(signature)
                    if existing_id:
                        existing_alignment_reused += 1
                        continue
                    row = EvidenceAlignment(
                        project_id=project.id, prompt_id=prompt_id, run_id=observation["run_id"],
                        recommendation_event_id=observation["event_id"],
                        recommendation_reason_id=recommendation_reason_id,
                        source_document_id=claim.source_document_id,
                        source_claim_id=claim.id,
                        relation=relation,
                        scope_relation="COMPETITOR_CONTEXT",
                        provider="deterministic",
                        model="scope_precheck",
                        prompt_version="entity_scope_precheck.v1",
                        schema_version="v1",
                        machine_payload_json=dumps({"precheck": precheck, **reason_payload}),
                        human_payload_json=dumps(_carried_forward_review_payload(carry)),
                        review_status=carry["review_status"] if carry else "MACHINE_GROUNDED",
                        reviewer=carry.get("reviewer", "") if carry else "",
                    )
                    db.add(row)
                    db.flush()
                    existing_observation_signatures[signature] = int(row.id or 0)
                    competitor_context += 1
                _finish_candidate_job()
                continue

            answer_semantic_hash = alignment_answer_unit_semantic_hash(reason_text, reason_scope, reason_entity)
            source_claim_semantic_hash = alignment_source_claim_semantic_hash(claim)
            materialization_key = build_alignment_materialization_key(reason_text, reason_scope, reason_entity, claim)
            materialization = materialization_cache.get(materialization_key)
            if materialization is None:
                materialization = (
                    db.query(EvidenceAlignmentMaterialization)
                    .filter(EvidenceAlignmentMaterialization.materialization_key == materialization_key)
                    .first()
                )
                if materialization is not None:
                    materialization_cache[materialization_key] = materialization
            compatibility = resolve_alignment_materialization_compatibility(materialization)

            if compatibility == "MISSING" and materialization_key in legacy_alignment_by_key and not use_executor:
                legacy_row = legacy_alignment_by_key[materialization_key]
                legacy_payload = loads(legacy_row.machine_payload_json, {})
                output_payload = _alignment_result_payload(legacy_payload, relation=legacy_row.relation)
                now = datetime.utcnow()
                materialization = EvidenceAlignmentMaterialization(
                    materialization_key=materialization_key,
                    answer_unit_semantic_hash=answer_semantic_hash,
                    source_claim_semantic_hash=source_claim_semantic_hash,
                    contract_version=ALIGNMENT_MATERIALIZATION_CONTRACT,
                    status="DONE",
                    compatibility_status="COMPATIBLE",
                    verdict=output_payload["relation"],
                    rationale=output_payload.get("rationale", ""),
                    confidence_raw=output_payload.get("confidence_raw", 0.0),
                    output_payload_json=dumps(output_payload),
                    output_hash=_stable_alignment_hash(output_payload),
                    source_alignment_ids_json=dumps([legacy_row.id] if legacy_row.id else []),
                    observed_prompt_ids_json=dumps([legacy_row.prompt_id] if legacy_row.prompt_id else []),
                    observed_run_ids_json=dumps([legacy_row.run_id] if legacy_row.run_id else []),
                    judge_impl_version=ALIGNMENT_JUDGE_IMPL_VERSION,
                    prompt_version=ALIGNMENT_PROMPT_VERSION,
                    schema_version=ALIGNMENT_SCHEMA_VERSION,
                    provider=legacy_row.provider or ALIGNMENT_PROVIDER,
                    model=legacy_row.model or judge.settings.deepseek_model,
                    attempt_count=0,
                    started_at=now,
                    completed_at=now,
                )
                db.add(materialization)
                db.commit()
                db.refresh(materialization)
                materialization_cache[materialization_key] = materialization
                compatibility = "COMPATIBLE"
                legacy_reuse_count += 1

            if compatibility == "COMPATIBLE" and materialization is not None:
                materialization_hit_count += 1
                result = _alignment_result_payload(loads(materialization.output_payload_json, {}), relation=materialization.verdict)
            else:
                if use_executor:
                    claimed = claim_materialization(
                        db,
                        EvidenceAlignmentMaterialization,
                        materialization_key=materialization_key,
                        create_values={
                            "answer_unit_semantic_hash": answer_semantic_hash,
                            "source_claim_semantic_hash": source_claim_semantic_hash,
                            "contract_version": ALIGNMENT_MATERIALIZATION_CONTRACT,
                            "compatibility_status": "UNKNOWN",
                            "judge_impl_version": ALIGNMENT_JUDGE_IMPL_VERSION,
                            "prompt_version": ALIGNMENT_PROMPT_VERSION,
                            "schema_version": ALIGNMENT_SCHEMA_VERSION,
                            "provider": judge.client.provider,
                            "model": judge.settings.deepseek_model,
                        },
                        owner_id=executor_id,
                        lease_seconds=settings.materialization_lease_seconds,
                        max_attempts=settings.materialization_max_attempts,
                        force_reclaim=compatibility in {"STALE_SCHEMA", "INCOMPATIBLE"},
                    )
                    materialization = claimed.row
                    if claimed.created:
                        materializations_created += 1
                    if claimed.outcome == HIT and materialization is not None:
                        materialization_hit_count += 1
                        result = _alignment_result_payload(
                            loads(materialization.output_payload_json, {}),
                            relation=materialization.verdict,
                        )
                    elif claimed.outcome == FAILED_FINAL:
                        failed_final_count += 1
                        _finish_candidate_job()
                        continue
                    elif claimed.outcome == OWNED_BY_OTHER:
                        owned_by_other_executor += 1
                        waited = wait_for_materialization(
                            db,
                            EvidenceAlignmentMaterialization,
                            materialization_key=materialization_key,
                            timeout_seconds=settings.materialization_wait_timeout_seconds,
                            poll_interval_seconds=settings.materialization_poll_interval_seconds,
                        )
                        if waited.outcome == HIT and waited.row is not None:
                            materialization = waited.row
                            materialization_hit_count += 1
                            result = _alignment_result_payload(
                                loads(materialization.output_payload_json, {}),
                                relation=materialization.verdict,
                            )
                        else:
                            wait_timeout_count += 1
                            _finish_candidate_job()
                            continue
                    else:
                        claimed_by_current_executor += 1
                        if claimed.lease_reclaimed:
                            lease_reclaimed += 1
                        if claimed.retry:
                            retry_count += 1
                        materialization_cache[materialization_key] = materialization
                else:
                    now = datetime.utcnow()
                    if materialization is None:
                        materialization = EvidenceAlignmentMaterialization(
                            materialization_key=materialization_key,
                            answer_unit_semantic_hash=answer_semantic_hash,
                            source_claim_semantic_hash=source_claim_semantic_hash,
                            contract_version=ALIGNMENT_MATERIALIZATION_CONTRACT,
                            status="IN_PROGRESS",
                            compatibility_status="UNKNOWN",
                            judge_impl_version=ALIGNMENT_JUDGE_IMPL_VERSION,
                            prompt_version=ALIGNMENT_PROMPT_VERSION,
                            schema_version=ALIGNMENT_SCHEMA_VERSION,
                            provider=judge.client.provider,
                            model=judge.settings.deepseek_model,
                            attempt_count=1,
                            started_at=now,
                        )
                        db.add(materialization)
                        db.commit()
                        db.refresh(materialization)
                        materialization_cache[materialization_key] = materialization
                        materializations_created += 1
                    else:
                        materialization.status = "IN_PROGRESS"
                        materialization.compatibility_status = compatibility
                        materialization.error_message = ""
                        materialization.attempt_count = int(materialization.attempt_count or 0) + 1
                        materialization.started_at = now
                        db.commit()

                if use_executor and compatibility == "MISSING" and materialization_key in legacy_alignment_by_key:
                    legacy_row = legacy_alignment_by_key[materialization_key]
                    legacy_payload = loads(legacy_row.machine_payload_json, {})
                    result = _alignment_result_payload(legacy_payload, relation=legacy_row.relation)
                    if materialization is not None:
                        _populate_alignment_materialization_from_legacy(
                            materialization,
                            legacy_row=legacy_row,
                            answer_semantic_hash=answer_semantic_hash,
                            source_claim_semantic_hash=source_claim_semantic_hash,
                            output_payload=result,
                            model=judge.settings.deepseek_model,
                        )
                        db.commit()
                        legacy_reuse_count += 1

                if materialization is not None and materialization.status == "IN_PROGRESS":
                    try:
                        cached_payload = _cached_alignment_payload(
                            db,
                            reason_text,
                            claim.normalized_claim,
                            judge.settings.deepseek_model,
                        )
                        if cached_payload is not None:
                            result = cached_payload
                            llm_call_cache_hit_count += 1
                        else:
                            actual_alignment_llm_calls += 1
                            _emit_progress(processed_candidate_jobs, force=True)
                            result = judge.judge(reason_text, claim.normalized_claim, db=db)
                        _materialize_alignment_result(db, materialization=materialization, result=result)
                        if use_executor:
                            release_materialization_owner(materialization)
                        db.commit()
                    except SemanticLLMError as e:
                        status = mark_materialization_failed(
                            db,
                            materialization,
                            error_message=str(e),
                            retryable=True,
                            max_attempts=settings.materialization_max_attempts,
                        ) if use_executor else "FAILED_RETRYABLE"
                        if not use_executor:
                            materialization.status = status
                            materialization.compatibility_status = "UNKNOWN"
                            materialization.error_message = str(e)
                            db.commit()
                        if status == "FAILED_FINAL":
                            failed_final_count += 1
                        else:
                            failed_retryable_count += 1
                        errors.append(str(e)[:120])
                        _finish_candidate_job()
                        continue

            try:
                relation = _alignment_result_payload(result).get("relation", "NONE")
            except (TypeError, ValueError):
                relation = "NONE"
            source_alignment_ids: list[int] = []
            for observation in observations:
                reason_payload = _observation_reason_payload(reason, observation, coverage_payload)
                recommendation_reason_id = str(observation.get("reason_id") or f"reason:{reason_text[:60]}")[:120]
                temp_alignment = EvidenceAlignment(
                    project_id=project.id,
                    prompt_id=prompt_id,
                    run_id=observation["run_id"],
                    recommendation_event_id=observation["event_id"],
                    recommendation_reason_id=recommendation_reason_id,
                    source_document_id=claim.source_document_id,
                    source_claim_id=claim.id,
                    relation=relation,
                )
                carry = review_carry_forward.get(
                    _alignment_review_signature(
                        temp_alignment,
                        claim,
                        relation=relation,
                        payload=reason_payload,
                    )
                )
                if carry:
                    carried_forward_reviews += 1
                signature = _alignment_observation_signature_values(
                    project_id=project.id,
                    prompt_id=prompt_id,
                    run_id=observation["run_id"],
                    recommendation_event_id=observation["event_id"],
                    recommendation_reason_id=recommendation_reason_id,
                    source_document_id=claim.source_document_id,
                    source_claim_id=claim.id,
                    relation=relation,
                    prompt_version=ALIGNMENT_PROMPT_VERSION,
                    schema_version=ALIGNMENT_SCHEMA_VERSION,
                )
                existing_id = existing_observation_signatures.get(signature)
                if existing_id:
                    source_alignment_ids.append(existing_id)
                    existing_alignment_reused += 1
                    continue
                row = EvidenceAlignment(
                    project_id=project.id, prompt_id=prompt_id, run_id=observation["run_id"],
                    recommendation_event_id=observation["event_id"],
                    recommendation_reason_id=recommendation_reason_id,
                    source_document_id=claim.source_document_id,
                    source_claim_id=claim.id,
                    relation=relation,
                    scope_relation=precheck,
                    provider=judge.client.provider,
                    model=judge.settings.deepseek_model,
                    prompt_version=ALIGNMENT_PROMPT_VERSION,
                    schema_version=ALIGNMENT_SCHEMA_VERSION,
                    machine_payload_json=dumps({**(result or {}), **reason_payload}),
                    human_payload_json=dumps(_carried_forward_review_payload(carry)),
                    review_status=carry["review_status"] if carry else "MACHINE_GROUNDED",
                    reviewer=carry.get("reviewer", "") if carry else "",
                )
                db.add(row)
                db.flush()
                source_alignment_ids.append(row.id)
                existing_observation_signatures[signature] = int(row.id or 0)
                created += 1
            if materialization is not None:
                materialization.source_alignment_ids_json = _append_unique_ids(
                    materialization.source_alignment_ids_json,
                    source_alignment_ids,
                )
                materialization.observed_prompt_ids_json = _append_unique_ids(
                    materialization.observed_prompt_ids_json,
                    [prompt_id],
                )
                materialization.observed_run_ids_json = _append_unique_ids(
                    materialization.observed_run_ids_json,
                    [int(obs["run_id"]) for obs in observations if obs.get("run_id")],
                )
                db.commit()
            _finish_candidate_job()

    db.commit()
    _emit_progress(unique_candidate_jobs, force=True)
    judge_calls = actual_alignment_llm_calls
    required_observation_jobs = sum(len(reason.get("observations") or []) for reason in unique_reasons.values()) * len(claims)
    return {
        "status": "OK",
        "required_jobs": required_observation_jobs,
        "unique_jobs": unique_candidate_jobs,
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
        "actual_alignment_llm_calls": actual_alignment_llm_calls,
        "materialization_hit_count": materialization_hit_count,
        "legacy_reuse_count": legacy_reuse_count,
        "llm_call_cache_hit_count": llm_call_cache_hit_count,
        "materializations_created": materializations_created,
        "failed_retryable_count": failed_retryable_count,
        "claimed_by_current_executor": claimed_by_current_executor,
        "owned_by_other_executor": owned_by_other_executor,
        "lease_reclaimed": lease_reclaimed,
        "retry_count": retry_count,
        "failed_retryable": failed_retryable_count,
        "failed_final": failed_final_count,
        "wait_timeout_count": wait_timeout_count,
        "batch_count": materialization_batch_count(unique_candidate_jobs, settings.materialization_batch_size),
        "max_observed_concurrency": min(
            max_observed_concurrency,
            max(1, int(settings.max_external_llm_concurrency or 1)),
        ) if unique_candidate_jobs else 0,
        "materialization_executor_enabled": use_executor,
        "executor_id": executor_id,
        "competitor_context": competitor_context,
        "review_carry_forward_candidates": len(review_carry_forward),
        "carried_forward_reviews": carried_forward_reviews,
        "deduped_source_claims": deduped_source_claims,
        "candidate_builder_mode": candidate_build["builder_mode"] if candidate_build else "LEGACY_ALL_VIABLE_PAIRS",
        "candidate_policy": candidate_build["candidate_policy"] if candidate_build else "LEGACY_NONE",
        "candidate_builder_cutover_enabled": use_binding_aware_candidates,
        "legacy_candidate_builder_rollback_available": True,
        "production_candidate_keys": len(candidate_key_filter or set()),
        "existing_alignment_rows_reused": existing_alignment_reused,
        "recall_layer_counts": {
            layer: len(candidate_build["recall_layer_keys"].get(layer, set()))
            for layer in ["L0_EXPLICIT", "L1_ANSWER_CONTEXT", "L2_RUN_SCOPE", "L3_PROMPT_SCOPE"]
        } if candidate_build else {},
        "boundary_tie_stats": candidate_build["boundary_tie_stats"] if candidate_build else {},
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
