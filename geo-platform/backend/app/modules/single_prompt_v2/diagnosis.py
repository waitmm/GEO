"""V2 second-slice diagnosis with explicit frozen input and append-only review.

This module deliberately reuses narrow semantic judges and deterministic
retrieval helpers. It does not call the V1 Package/Shadow/Workflow runners.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from typing import Any, Callable
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    LLMCallCache,
    Project,
    RecommendationEntity,
    SinglePromptAnalysis,
    SinglePromptAnalysisContext,
    SinglePromptCitationManifest,
    SinglePromptDiagnosisExecution,
    SinglePromptDiagnosisResult,
    SinglePromptDiagnosisReview,
    SinglePromptPreparedSourceSnapshot,
    SinglePromptSourceCompletionManifest,
    SinglePromptSourceSnapshot,
    TargetBrandCapabilityTruth,
)
from app.modules.optimization.answer_semantic import (
    locate_span,
)
from app.modules.optimization.passage_retrieval import RETRIEVAL_VERSION, tokenize_zh
from app.modules.optimization.passage_service import fetch_page_playwright
from app.modules.monitoring.collectors.wenxin.search_process import legacy_mixed_answer_boundary
from app.modules.single_prompt_v2.llm_safety import (
    V2_ADMISSION_CONTRACT_VERSION,
    V2_ANSWER_GROUNDING_VERSION,
    V2_ALIGNMENT_PROMPT_VERSION,
    V2_ALIGNMENT_SCHEMA_VERSION,
    V2_ALIGNMENT_SYSTEM,
    V2_ANSWER_PROMPT_VERSION,
    V2_ANSWER_SCHEMA_VERSION,
    V2_ANSWER_SYSTEM,
    V2_SOURCE_CLAIM_PROMPT_VERSION,
    V2_SOURCE_CLAIM_SCHEMA_VERSION,
    V2_SOURCE_CLAIM_SYSTEM,
    V2AlignmentJudge,
    V2AnswerSemanticJudge,
    V2ResponseAdmissionError,
    V2SourceClaimJudge,
    admit_alignment_response,
    admit_answer_for_input,
    admit_source_claim_response,
    alignment_user_payload,
    answer_user_payload,
    assess_alignment_relation,
    assess_answer_event,
    assess_normalized_projection,
    contains_untrusted_instruction,
    locate_v2_answer_span,
    source_claim_user_payload,
    source_subject_is_grounded,
)
from app.modules.single_prompt_v2.coverage import diagnosis_coverage_projections
from app.modules.single_prompt_v2.evidence_plan import (
    EVIDENCE_FALLBACK_REPLACEMENTS_PER_REASON,
    EVIDENCE_PLAN_POLICY_VERSION,
    build_evidence_candidate_plan,
)
from app.modules.single_prompt_v2.source_preparation import validate_completion_for_evidence
from app.services.semantic_llm.base import SemanticLLMError
from app.services.semantic_llm.deepseek import DeepSeekClient
from app.services.url_identity import canonicalize_url
from app.services.serialization import dumps, loads


DIAGNOSIS_CONTRACT_VERSION = "single_prompt_diagnosis.v2_second_slice_safety.v3_fixed_scope"
ANSWER_RESULT_PROJECTION_VERSION = "single_prompt_answer_semantic_projection.v4_fixed_scope_coverage"
SOURCE_SNAPSHOT_PARSER_VERSION = "single_prompt_source_snapshot.v1"
SOURCE_CONTENT_GATE_VERSION = "single_prompt_source_content_gate.v1"
PASSAGE_SPLIT_VERSION = "single_prompt_passage_split.v1"
TRUTH_MATCH_VERSION = "single_prompt_truth_relation.v5_capability_presence"
REVIEW_CONTRACT_VERSION = "single_prompt_diagnosis_review.v1"
V2_LLM_THINKING_MODE = "disabled"

_SPEECH_ACTS = {"RECOMMEND", "INCLUDE_AS_OPTION", "PRAISE", "COMPARE", "MENTION", "DISCOURAGE", "REJECT"}
_RECOMMENDATION_STRENGTHS = {"STRONG", "MODERATE", "WEAK", "NONE"}
_POLARITIES = {"POSITIVE", "NEUTRAL", "NEGATIVE"}
_REASON_SCOPES = {"ENTITY_SPECIFIC", "MARKET_CRITERION"}
_CLAIM_TYPES = {"CAPABILITY", "LIMITATION", "SCENARIO", "PRICE", "POLICY", "COMPARISON", "EVALUATION", "USAGE", "OTHER"}
_ALIGNMENT_RELATIONS = {"SUPPORTS", "CONTRADICTS", "RELATED", "NONE"}
_TRUTH_RELATIONS = {"FULLY_COVERS", "PARTIALLY_COVERS", "CONFLICTS", "UNRESOLVED"}
_ADMITTED_ANSWER_JOB_STATUSES = {
    "DONE",
    "DONE_ZERO_EVENTS",
    "DONE_WITH_FAILURES",
    "DONE_WITH_REVIEW_REQUIRED",
    "SEMANTIC_REVIEW_REQUIRED",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return f"{value.isoformat()}Z" if value else None


def answer_semantic_eligibility(output: dict[str, Any]) -> dict[str, Any]:
    diagnosis = output.get("answer_diagnosis") or {}
    jobs = diagnosis.get("answer_jobs") or []
    if not jobs:
        projected_objects = [
            *(diagnosis.get("events") or []),
            *(diagnosis.get("market_criteria") or []),
        ]
        projected_run_ids = {
            row.get("run_id") for row in projected_objects if row.get("run_id") is not None
        }
        admitted_count = len(projected_run_ids) or (1 if projected_objects else 0)
        return {
            "contract_version": ANSWER_RESULT_PROJECTION_VERSION,
            "total_answer_count": admitted_count,
            "admitted_answer_count": admitted_count,
            "failed_answer_count": 0,
            "valid_zero_answer_count": 0,
            "failure_record_count": len(diagnosis.get("failures") or []),
            "no_consumable_answer_semantic_result": not projected_objects,
            "partial_failure": False,
            "status": "ADMITTED_LEGACY_PROJECTION" if projected_objects else "NO_CONSUMABLE_RESULT",
        }
    admitted = [row for row in jobs if row.get("status") in _ADMITTED_ANSWER_JOB_STATUSES]
    pending = [
        row for row in jobs
        if str(row.get("status") or "").startswith("PENDING")
        or row.get("result_source") == "CACHE_MISS_EXTERNAL_NOT_AUTHORIZED"
    ]
    invalid_cache = [
        row for row in jobs
        if row.get("status") == "CACHE_REJECTED_BY_V2_VALIDATION"
    ]
    failed = [
        row for row in jobs
        if row not in admitted and row not in pending and row not in invalid_cache
    ]
    zero = [row for row in admitted if row.get("status") == "DONE_ZERO_EVENTS"]
    def covered_count(rows: list[dict[str, Any]]) -> int:
        return sum(max(len(row.get("run_ids") or []), 1) for row in rows)
    total = sum(max(len(row.get("run_ids") or []), 1) for row in jobs)
    no_consumable = total == 0 or not admitted
    return {
        "contract_version": ANSWER_RESULT_PROJECTION_VERSION,
        "total_answer_count": total,
        "admitted_answer_count": covered_count(admitted),
        "failed_answer_count": covered_count(failed),
        "valid_zero_answer_count": covered_count(zero),
        "failure_record_count": len(diagnosis.get("failures") or []),
        "no_consumable_answer_semantic_result": no_consumable,
        "partial_failure": bool(admitted and failed),
        "status": (
            "NO_CONSUMABLE_RESULT" if no_consumable
            else "PARTIAL" if failed or pending or invalid_cache
            else "ADMITTED"
        ),
    }


def _require_consumable_answer_semantic(output: dict[str, Any], operation: str) -> None:
    eligibility = answer_semantic_eligibility(output)
    if eligibility["no_consumable_answer_semantic_result"]:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "NO_CONSUMABLE_ANSWER_SEMANTIC_RESULT",
                "operation": operation,
                "detail": "回答语义没有任何通过当前准入契约的结果；失败不能通过审核或修订升级为有效输入。",
                "answer_semantic_eligibility": eligibility,
            },
        )


def _mixed_answer_boundary_run_ids(db: Session, execution: SinglePromptDiagnosisExecution) -> list[int]:
    context = db.query(SinglePromptAnalysisContext).filter(
        SinglePromptAnalysisContext.context_id == execution.context_id,
        SinglePromptAnalysisContext.raw_output_hash == execution.raw_output_hash,
    ).one_or_none()
    if not context:
        return []
    raw_output = loads(context.raw_output_json, {})
    mixed: list[int] = []
    for run in raw_output.get("runs") or []:
        answer = str(run.get("answer_text") or "")
        status = str((run.get("answer_content_boundary") or {}).get("status") or "")
        if status == "LEGACY_MIXED_CONTAINER" or (
            status != "FINAL_ANSWER_ONLY"
            and legacy_mixed_answer_boundary(answer)["status"] == "LEGACY_MIXED_CONTAINER"
        ):
            mixed.append(int(run.get("run_id") or 0))
    return [run_id for run_id in mixed if run_id]


def _require_independent_answer_boundary(
    db: Session,
    execution: SinglePromptDiagnosisExecution,
    operation: str,
) -> None:
    mixed_run_ids = _mixed_answer_boundary_run_ids(db, execution)
    if mixed_run_ids:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ANSWER_CONTENT_BOUNDARY_NOT_INDEPENDENT",
                "operation": operation,
                "run_ids": mixed_run_ids,
                "detail": "历史 Run 的回答文本混入平台搜索过程；该结果只保留审计，不能完成审核或进入后续证据消费。",
            },
        )


def _truth_statement_issues(label: str) -> list[str]:
    value = str(label or "").strip()
    issues: list[str] = []
    if any(marker in value for marker in ("，", ",", "；", ";", "、", "/", "／", "以及", "并且", "同时", "还支持", "且支持")):
        issues.append("COMPOUND_STATEMENT_REQUIRES_SPLIT")
    if value.count("支持") > 1:
        issues.append("MULTIPLE_CAPABILITY_PREDICATES")
    return sorted(set(issues))


def _truth_statement_eligibility(
    *,
    capability_label: str,
    product_truth_status: str,
    source_reference: str,
) -> dict[str, Any]:
    status = str(product_truth_status or "UNKNOWN").upper()
    issues = _truth_statement_issues(capability_label)
    if status in {"FALSE", "NOT_SUPPORTED", "UNSUPPORTED"}:
        return {"status": "PROHIBITED", "issues": issues or ["CONFIRMED_NOT_SUPPORTED"]}
    if status not in {"TRUE", "SUPPORTED"}:
        return {"status": "VERIFY_FIRST", "issues": issues or ["TRUTH_NOT_CONFIRMED_POSITIVE"]}
    if not str(source_reference or "").strip():
        issues.append("SOURCE_REFERENCE_REQUIRED")
    return {
        "status": "ELIGIBLE" if not issues else "VERIFY_FIRST",
        "issues": sorted(set(issues)),
    }


def _split_target_capability_candidates(text: str) -> list[str]:
    """Build conservative, review-only capability labels from grounded answer text."""
    value = re.sub(r"\s+", " ", str(text or "")).strip(" ，,；;。")
    if not value:
        return []

    # Shared recommendations often begin with a tool list. That list is
    # context, not part of the target capability the operator must verify.
    value = re.sub(r"^使用.+?等[^，,；;。]{0,16}工具(?=(?:可|能|支持|提供|生成|实现|通过))", "", value)
    clauses = [part.strip() for part in re.split(r"[，,；;。]+", value) if part.strip()]
    candidates: list[str] = []
    inherited_verb = ""

    def add(label: str) -> None:
        normalized = re.sub(r"\s+", " ", label).strip(" ，,；;。")
        normalized = re.sub(r"^(?:还|并|且)(?=支持|提供|实现|可)", "", normalized)
        normalized = re.sub(r"^可(?=降低|减少|避免|提升|提高)", "", normalized)
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    for clause in clauses:
        clause = re.sub(r"^(?:还|并|且)(?=支持|提供|实现|可)", "", clause)
        embedded = re.match(r"^(生成.+?)(?:并)?嵌入(.+)$", clause)
        if embedded:
            generated = embedded.group(1).strip()
            add(generated)
            object_text = re.sub(r"^生成", "", generated, count=1)
            add(f"支持将{object_text}嵌入{embedded.group(2).strip()}")
            inherited_verb = "支持"
            continue

        supported = re.match(r"^(支持|提供)(.+)$", clause)
        if supported:
            inherited_verb = supported.group(1)
            items = [item.strip() for item in re.split(r"[、]", supported.group(2)) if item.strip()]
            for item in items:
                add(f"{inherited_verb}{item}")
            continue

        if "、" in clause and inherited_verb:
            for item in [item.strip() for item in clause.split("、") if item.strip()]:
                add(f"{inherited_verb}{item}")
            continue

        add(clause)
        inherited_verb = ""

    return candidates


def _target_capability_review_items(
    output: dict[str, Any],
    review_decisions: list[dict[str, Any]],
    project_truths: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    brand_snapshot = (output.get("input") or {}).get("brand_snapshot") or {}
    target_names = {
        str(value).strip()
        for value in [brand_snapshot.get("brand_name"), *(brand_snapshot.get("aliases") or [])]
        if str(value or "").strip()
    }
    accepted_events = {
        str(row.get("event_id") or "")
        for row in review_decisions
        if row.get("scope") == "ANSWER_SEMANTIC_EVENT"
        and str(row.get("decision") or "").startswith("CONFIRM_")
    }
    accepted_events.update(
        str(event.get("event_id") or "")
        for event in (output.get("answer_diagnosis") or {}).get("events") or []
        if event.get("fact_consumption_eligible") is True
        and str(event.get("review_status") or "").startswith("HUMAN_CONFIRMED_")
        and bool(event.get("review_id"))
    )
    if not accepted_events:
        return []
    truth_by_key = {
        str(row.get("capability_key") or ""): row
        for row in project_truths
    }
    grouped: dict[str, dict[str, Any]] = {}

    for event in (output.get("answer_diagnosis") or {}).get("events") or []:
        event_id = str(event.get("event_id") or "")
        entity = str(event.get("entity_text") or "").strip()
        if entity not in target_names or event_id not in accepted_events:
            continue
        for reason in event.get("reasons") or []:
            reason_id = str(reason.get("reason_id") or "")
            grounded_text = str(reason.get("effective_grounded_text") or reason.get("reason_span") or "").strip()
            for capability_label in _split_target_capability_candidates(grounded_text):
                capability_key = re.sub(r"[\s\W_]+", "", capability_label.lower())
                if not capability_key:
                    continue
                item = grouped.setdefault(capability_key, {
                    "candidate_id": f"cap-{_hash({'capability_key': capability_key})[:20]}",
                    "capability_key": capability_key,
                    "capability_label": capability_label,
                    "source_signal_ids": [],
                    "source_event_ids": [],
                    "source_run_ids": [],
                    "answer_excerpts": [],
                    "current_truth": truth_by_key.get(capability_key),
                })
                if reason_id and reason_id not in item["source_signal_ids"]:
                    item["source_signal_ids"].append(reason_id)
                if event_id and event_id not in item["source_event_ids"]:
                    item["source_event_ids"].append(event_id)
                run_id = event.get("run_id")
                if run_id is not None and run_id not in item["source_run_ids"]:
                    item["source_run_ids"].append(run_id)
                if grounded_text and grounded_text not in item["answer_excerpts"]:
                    item["answer_excerpts"].append(grounded_text)

    return list(grouped.values())


def _snapshot_truth(row: TargetBrandCapabilityTruth) -> dict[str, Any]:
    statement_eligibility = _truth_statement_eligibility(
        capability_label=row.capability_label,
        product_truth_status=row.product_truth_status,
        source_reference=row.source_reference,
    )
    return {
        "truth_id": row.id,
        "brand_id": row.brand_id,
        "capability_key": row.capability_key,
        "capability_label": row.capability_label,
        "product_truth_status": row.product_truth_status,
        "truth_source": row.truth_source,
        "source_reference": row.source_reference,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": _iso(row.reviewed_at),
        "note": row.note,
        "row_updated_at": _iso(row.updated_at),
        "statement_eligibility": statement_eligibility,
    }


def _project_truth_state(db: Session, project_id: int, frozen_truth_set_hash: str = "") -> dict[str, Any]:
    rows = (
        db.query(TargetBrandCapabilityTruth)
        .filter(TargetBrandCapabilityTruth.project_id == project_id)
        .order_by(TargetBrandCapabilityTruth.id)
        .all()
    )
    truths = [_snapshot_truth(row) for row in rows]
    current_hash = _hash(truths)
    return {
        "truths": truths,
        "truth_set_hash": current_hash,
        "differs_from_frozen_diagnosis": bool(frozen_truth_set_hash and current_hash != frozen_truth_set_hash),
    }


def record_target_brand_truth(
    db: Session,
    *,
    analysis_id: str,
    diagnosis_id: str,
    result_version: str,
    project_id: int,
    prompt_id: int,
    result_hash: str,
    frozen_truth_set_hash: str,
    expected_project_truth_set_hash: str,
    capability_label: str,
    product_truth_status: str,
    source_reference: str,
    note: str,
    reviewed_by: str,
    source_signal_id: str,
) -> dict[str, Any]:
    execution = db.query(SinglePromptDiagnosisExecution).filter_by(
        diagnosis_id=diagnosis_id,
        analysis_id=analysis_id,
    ).one_or_none()
    if not execution:
        raise HTTPException(status_code=404, detail="诊断执行不存在")
    if execution.project_id != project_id or execution.prompt_id != prompt_id:
        raise HTTPException(status_code=409, detail="诊断身份与当前 Project/Prompt 不匹配")
    if execution.active_result_version != result_version:
        raise HTTPException(status_code=409, detail="诊断结果版本已变化，请重新加载")
    result = db.query(SinglePromptDiagnosisResult).filter_by(
        diagnosis_id=diagnosis_id,
        result_version=result_version,
    ).one_or_none()
    if not result or result.output_hash != result_hash:
        raise HTTPException(status_code=409, detail="诊断结果身份或 hash 不匹配")
    if execution.truth_set_hash != frozen_truth_set_hash:
        raise HTTPException(status_code=409, detail="提交的冻结事实集合与当前诊断不匹配")

    current_state = _project_truth_state(db, project_id, execution.truth_set_hash)
    if current_state["truth_set_hash"] != expected_project_truth_set_hash:
        raise HTTPException(status_code=409, detail="项目事实集合已变化，请重新加载后再提交")

    result_output = loads(result.output_json, {})
    target_brand_name = str((result_output.get("input") or {}).get("brand_snapshot", {}).get("brand_name") or "").strip()
    selected_signal = next(
        (
            {"event": event, "reason": reason}
            for event in (result_output.get("answer_diagnosis") or {}).get("events") or []
            for reason in event.get("reasons") or []
            if str(reason.get("reason_id") or "") == source_signal_id
        ),
        None,
    )
    if not selected_signal:
        criterion = next(
            (
                row for row in (result_output.get("answer_diagnosis") or {}).get("market_criteria") or []
                if str(row.get("criterion_id") or "") == source_signal_id
            ),
            None,
        )
        if criterion:
            selected_signal = {
                "event": {"entity_text": "MARKET_CRITERION"},
                "reason": criterion,
            }
    if not selected_signal:
        raise HTTPException(status_code=422, detail="事实核验必须绑定当前诊断中的准确能力信号")

    label = capability_label.strip()
    key = re.sub(r"[\s\W_]+", "", label.lower())
    if not key:
        raise HTTPException(status_code=422, detail="能力名称不能只包含空白或标点")
    if product_truth_status not in {"SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_SUPPORTED", "UNKNOWN"}:
        raise HTTPException(status_code=422, detail="目标品牌事实状态非法")
    statement_issues = _truth_statement_issues(label)
    if statement_issues:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "COMPOUND_TARGET_BRAND_TRUTH_REQUIRES_SPLIT",
                "detail": "请一次只确认一项可以独立判真或判假的目标品牌能力；适用条件请写入核对说明。",
                "issues": statement_issues,
            },
        )
    source = source_reference.strip()
    reviewed_note = note.strip()
    existing = db.query(TargetBrandCapabilityTruth).filter(
        TargetBrandCapabilityTruth.project_id == project_id,
        TargetBrandCapabilityTruth.capability_key == key,
    ).one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="该目标品牌事实已存在；本入口不会覆盖既有人工事实")

    project = db.get(Project, project_id)
    brand_entity = db.query(RecommendationEntity).filter(
        RecommendationEntity.project_id == project_id,
        RecommendationEntity.canonical_name == project.brand_name,
    ).order_by(RecommendationEntity.id).first()
    if not brand_entity:
        brand_key = re.sub(r"[\s\W_]+", "", project.brand_name.lower())
        brand_entity = RecommendationEntity(
            project_id=project_id,
            canonical_name=project.brand_name,
            entity_type="BRAND",
            entity_role="BRAND",
            is_choice_candidate=False,
            normalized_key=brand_key,
            source="MANUAL_CONFIRMED",
        )
        db.add(brand_entity)
        db.flush()

    row = TargetBrandCapabilityTruth(
        project_id=project_id,
        brand_id=brand_entity.id,
        capability_key=key,
        capability_label=label,
        product_truth_status=product_truth_status,
        truth_source="MANUAL_CONFIRMED",
        source_reference=source,
        reviewed_by=reviewed_by.strip(),
        reviewed_at=datetime.utcnow(),
        note=reviewed_note,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="目标品牌事实已被其他操作写入，请重新加载")
    db.refresh(row)
    updated_state = _project_truth_state(db, project_id, execution.truth_set_hash)
    return {
        "truth": _snapshot_truth(row),
        "trigger_signal": {
            "signal_id": source_signal_id,
            "source_subject": str(selected_signal["event"].get("entity_text") or ""),
            "target_subject": target_brand_name,
            "boundary": "REVIEW_TRIGGER_ONLY_NOT_FACT_PROVENANCE",
        },
        "project_truth_state": updated_state,
        "frozen_diagnosis": {
            "diagnosis_id": diagnosis_id,
            "result_version": result_version,
            "truth_set_hash": execution.truth_set_hash,
            "unchanged": True,
        },
        "requires_new_diagnosis": True,
        "next_action": "REPROJECT_TARGET_BRAND_TRUTHS",
    }


def _contract_config(
    *,
    source_snapshot_policy: str = "REUSE_OR_FETCH",
    evidence_llm_policy: str = "ALLOW_EXTERNAL",
    diagnosis_mode: str = "LEGACY_BUNDLED",
    answer_llm_policy: str = "ALLOW_EXTERNAL",
    citation_manifest_id: str = "",
    citation_manifest_hash: str = "",
) -> dict[str, Any]:
    settings = get_settings()
    return {
        "diagnosis_contract": DIAGNOSIS_CONTRACT_VERSION,
        "llm_admission_contract_version": V2_ADMISSION_CONTRACT_VERSION,
        "answer_result_projection_version": ANSWER_RESULT_PROJECTION_VERSION,
        "answer_grounding_version": V2_ANSWER_GROUNDING_VERSION,
        "answer_semantic_prompt_version": V2_ANSWER_PROMPT_VERSION,
        "answer_semantic_schema_version": V2_ANSWER_SCHEMA_VERSION,
        "source_snapshot_parser_version": SOURCE_SNAPSHOT_PARSER_VERSION,
        "source_content_gate_version": SOURCE_CONTENT_GATE_VERSION,
        "passage_split_version": PASSAGE_SPLIT_VERSION,
        "passage_retrieval_version": RETRIEVAL_VERSION,
        "source_claim_prompt_version": V2_SOURCE_CLAIM_PROMPT_VERSION,
        "source_claim_schema_version": V2_SOURCE_CLAIM_SCHEMA_VERSION,
        "alignment_prompt_version": V2_ALIGNMENT_PROMPT_VERSION,
        "alignment_schema_version": V2_ALIGNMENT_SCHEMA_VERSION,
        "truth_match_version": TRUTH_MATCH_VERSION,
        "review_contract_version": REVIEW_CONTRACT_VERSION,
        "model_provider": "deepseek",
        "model": settings.deepseek_model,
        "llm_thinking_mode": V2_LLM_THINKING_MODE,
        "llm_max_attempts": 1,
        "source_snapshot_policy": source_snapshot_policy,
        "evidence_llm_policy": evidence_llm_policy,
        "diagnosis_mode": diagnosis_mode,
        "answer_llm_policy": answer_llm_policy,
        "citation_manifest_id": citation_manifest_id,
        "citation_manifest_hash": citation_manifest_hash,
        "evidence_candidate_plan_version": EVIDENCE_PLAN_POLICY_VERSION,
        "evidence_fallback_replacements_per_reason": EVIDENCE_FALLBACK_REPLACEMENTS_PER_REASON,
        "alignment_claims_per_source_reason": 3,
    }


def create_diagnosis(
    db: Session,
    *,
    analysis_id: str,
    project_id: int,
    prompt_id: int,
    idempotency_key: str,
    source_snapshot_policy: str = "REUSE_OR_FETCH",
    evidence_llm_policy: str = "ALLOW_EXTERNAL",
    diagnosis_mode: str = "LEGACY_BUNDLED",
    answer_llm_policy: str = "ALLOW_EXTERNAL",
    citation_manifest_id: str = "",
    citation_manifest_hash: str = "",
    automatic_task_id: str | None = None,
) -> tuple[SinglePromptDiagnosisExecution, bool]:
    analysis = db.query(SinglePromptAnalysis).filter(SinglePromptAnalysis.analysis_id == analysis_id).one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="V2 分析不存在")
    if analysis.project_id != project_id or analysis.prompt_id != prompt_id:
        raise HTTPException(status_code=409, detail="分析身份与当前 Project/Prompt 不匹配")
    context = db.query(SinglePromptAnalysisContext).filter(SinglePromptAnalysisContext.analysis_id == analysis_id).one_or_none()
    if not context:
        raise HTTPException(status_code=409, detail="采样结果尚未冻结，不能开始诊断")
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    truths = (
        db.query(TargetBrandCapabilityTruth)
        .filter(TargetBrandCapabilityTruth.project_id == project_id)
        .order_by(TargetBrandCapabilityTruth.id)
        .all()
    )
    brand_snapshot = {
        "project_id": project.id,
        "brand_name": project.brand_name,
        "brand_aliases": loads(project.brand_aliases_json, []),
        "website_url": project.website_url,
        "project_updated_at": _iso(project.updated_at),
    }
    truth_snapshot = [_snapshot_truth(row) for row in truths]
    if automatic_task_id:
        from .automatic_delivery import require_task
        parent = require_task(db, automatic_task_id, project_id, prompt_id)
        fixed = loads(parent.input_json, {})
        if parent.status != "RUNNING" or parent.analysis_id != analysis_id or fixed["raw_output_hash"] != context.raw_output_hash:
            raise HTTPException(409, "自动任务与 Answer 输入不一致")
        if diagnosis_mode != "ANSWER_ONLY":
            raise HTTPException(409, "自动任务只允许独立 Answer 计算")
        brand_snapshot = fixed["brand"]
        truth_snapshot = fixed["truth_snapshot"]
    config = _contract_config(
        source_snapshot_policy=source_snapshot_policy,
        evidence_llm_policy=evidence_llm_policy,
        diagnosis_mode=diagnosis_mode,
        answer_llm_policy=answer_llm_policy,
        citation_manifest_id=citation_manifest_id,
        citation_manifest_hash=citation_manifest_hash,
    )
    if automatic_task_id:
        config["automatic_task_id"] = automatic_task_id
    identity = {
        "analysis_id": analysis_id,
        "context_id": context.context_id,
        "raw_output_hash": context.raw_output_hash,
        "brand_snapshot_hash": _hash(brand_snapshot),
        "truth_set_hash": _hash(truth_snapshot),
        "contract_config_hash": _hash(config),
    }
    fingerprint = _hash(identity)
    existing = (
        db.query(SinglePromptDiagnosisExecution)
        .filter(
            SinglePromptDiagnosisExecution.analysis_id == analysis_id,
            SinglePromptDiagnosisExecution.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing:
        if existing.input_fingerprint != fingerprint:
            raise HTTPException(status_code=409, detail="幂等键已用于不同的诊断输入")
        return existing, False

    execution = SinglePromptDiagnosisExecution(
        diagnosis_id=str(uuid4()),
        analysis_id=analysis_id,
        context_id=context.context_id,
        project_id=project_id,
        prompt_id=prompt_id,
        idempotency_key=idempotency_key,
        input_fingerprint=fingerprint,
        raw_output_hash=context.raw_output_hash,
        brand_snapshot_json=_canonical_json(brand_snapshot),
        brand_snapshot_hash=identity["brand_snapshot_hash"],
        truth_snapshot_json=_canonical_json(truth_snapshot),
        truth_set_hash=identity["truth_set_hash"],
        contract_config_json=_canonical_json(config),
        contract_config_hash=identity["contract_config_hash"],
        status="OPTIMIZE_OWNED" if automatic_task_id else "QUEUED",
        progress_json=_canonical_json({"stage": "QUEUED", "completed": 0, "total": 1}),
    )
    db.add(execution)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = (
            db.query(SinglePromptDiagnosisExecution)
            .filter(
                SinglePromptDiagnosisExecution.analysis_id == analysis_id,
                SinglePromptDiagnosisExecution.idempotency_key == idempotency_key,
            )
            .first()
        )
        if concurrent and concurrent.input_fingerprint == fingerprint:
            return concurrent, False
        raise
    db.refresh(execution)
    return execution, True


def create_answer_diagnosis(
    db: Session,
    *,
    analysis_id: str,
    project_id: int,
    prompt_id: int,
    citation_manifest_id: str,
    citation_manifest_hash: str,
    answer_llm_policy: str,
    idempotency_key: str,
    automatic_task_id: str | None = None,
) -> tuple[SinglePromptDiagnosisExecution, bool]:
    if answer_llm_policy not in {"ALLOW_EXTERNAL", "CACHE_ONLY"}:
        raise HTTPException(status_code=422, detail="Answer Semantic 授权策略非法")
    manifest = db.query(SinglePromptCitationManifest).filter_by(manifest_id=citation_manifest_id).one_or_none()
    if not manifest:
        raise HTTPException(status_code=409, detail={"code": "CITATION_MANIFEST_REQUIRED"})
    if (
        manifest.analysis_id != analysis_id
        or manifest.project_id != project_id
        or manifest.prompt_id != prompt_id
        or manifest.payload_hash != citation_manifest_hash
    ):
        raise HTTPException(status_code=409, detail={"code": "CITATION_MANIFEST_INPUT_MISMATCH"})
    return create_diagnosis(
        db,
        analysis_id=analysis_id,
        project_id=project_id,
        prompt_id=prompt_id,
        idempotency_key=idempotency_key,
        source_snapshot_policy="SOURCE_PREPARATION_ONLY",
        evidence_llm_policy="CACHE_ONLY",
        diagnosis_mode="ANSWER_ONLY",
        answer_llm_policy=answer_llm_policy,
        citation_manifest_id=citation_manifest_id,
        citation_manifest_hash=citation_manifest_hash,
        automatic_task_id=automatic_task_id,
    )


def claim_diagnosis(db: Session, diagnosis_id: str, *, automatic_task_id: str | None = None) -> str | None:
    if automatic_task_id:
        from .automatic_delivery import require_task
        target = db.query(SinglePromptDiagnosisExecution).filter_by(diagnosis_id=diagnosis_id).one_or_none()
        if not target or loads(target.contract_config_json, {}).get("automatic_task_id") != automatic_task_id:
            raise HTTPException(409, "Answer 不属于当前自动优化任务")
        parent = require_task(db, automatic_task_id, target.project_id, target.prompt_id)
        if parent.status != "RUNNING":
            raise HTTPException(409, "自动任务已停止")
    token = uuid4().hex
    claimed = db.execute(
        update(SinglePromptDiagnosisExecution)
        .where(
            SinglePromptDiagnosisExecution.diagnosis_id == diagnosis_id,
            SinglePromptDiagnosisExecution.status == ("OPTIMIZE_OWNED" if automatic_task_id else "QUEUED"),
        )
        .values(
            status="RUNNING",
            blocker_code="",
            blocker_detail="",
            active_attempt_token=token,
            attempt_count=SinglePromptDiagnosisExecution.attempt_count + 1,
            started_at=datetime.utcnow(),
            finished_at=None,
        )
    )
    db.commit()
    return token if claimed.rowcount == 1 else None


def _set_progress(db: Session, execution: SinglePromptDiagnosisExecution, stage: str, completed: int, total: int, detail: str = "") -> None:
    execution.progress_json = _canonical_json({
        "stage": stage,
        "completed": completed,
        "total": total,
        "detail": detail,
    })
    db.commit()


def _llm_input_hash(
    system_prompt: str,
    user_payload: dict,
    prompt_version: str,
    schema_version: str,
    thinking_mode: str | None = None,
) -> str:
    identity: dict[str, Any] = {
        "system": system_prompt,
        "payload": user_payload,
        "pv": prompt_version,
        "sv": schema_version,
    }
    if thinking_mode:
        identity["generation"] = {"thinking": {"type": thinking_mode}}
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_row(db: Session, input_hash: str, prompt_version: str, schema_version: str) -> LLMCallCache | None:
    settings = get_settings()
    return (
        db.query(LLMCallCache)
        .filter(
            LLMCallCache.provider == "deepseek",
            LLMCallCache.model == settings.deepseek_model,
            LLMCallCache.prompt_version == prompt_version,
            LLMCallCache.schema_version == schema_version,
            LLMCallCache.input_hash == input_hash,
        )
        .order_by(LLMCallCache.id.desc())
        .first()
    )


def _call_with_usage(
    db: Session,
    usage: dict[str, int],
    *,
    input_hash: str,
    prompt_version: str,
    schema_version: str,
    call: Callable[[], dict],
) -> tuple[dict, str]:
    before = _cache_row(db, input_hash, prompt_version, schema_version)
    if before:
        usage["llm_cache_hits"] += 1
    else:
        usage["external_llm_calls"] += 1
    result = call()
    if not before:
        after = _cache_row(db, input_hash, prompt_version, schema_version)
        if after:
            usage["external_token_usage"] += int(after.token_usage or 0)
    return result, "LLM_CALL_CACHE" if before else "EXTERNAL_LLM"


def _llm_failure(exc: SemanticLLMError, *, default_code: str = "FAILED") -> dict[str, Any]:
    audit = dict(getattr(exc, "audit", {}) or {})
    code = str(getattr(exc, "code", "") or default_code)
    if audit.get("response_source") == "LLM_CALL_CACHE":
        code = "CACHE_REJECTED_BY_V2_VALIDATION"
    return {
        "status": code,
        "error": str(exc)[:500],
        "audit": {
            "raw_response_hash": audit.get("raw_response_hash", ""),
            "finish_reason": audit.get("finish_reason", "unknown"),
            "response_length": int(audit.get("response_length") or 0),
            "response_excerpt": str(audit.get("response_excerpt") or "")[:240],
            "validation_errors": list(audit.get("validation_errors") or []),
            "response_source": audit.get("response_source", "UNKNOWN"),
        },
    }


def _event_identity(run_id: int, event: dict, located: dict) -> str:
    raw_identity = {
        "raw_text_sha256": located.get("raw_text_sha256"),
        "raw_start": located.get("raw_start"),
        "raw_end": located.get("raw_end"),
    }
    return f"evt-{_hash({'run_id': run_id, 'entity': event.get('entity_text'), 'span': raw_identity})[:20]}"


def _diagnose_answers(
    db: Session,
    *,
    raw_output: dict,
    prompt_text: str,
    brand_name: str,
    usage: dict[str, int],
    judge: Any,
    thinking_mode: str | None,
    answer_llm_policy: str = "ALLOW_EXTERNAL",
) -> dict:
    events: list[dict] = []
    market_criteria: list[dict] = []
    failures: list[dict] = []
    unresolved_items: list[dict] = []
    answer_cache: dict[str, dict] = {}
    answer_jobs: dict[str, dict] = {}
    for run in raw_output.get("runs") or []:
        answer = str(run.get("answer_text") or "")
        if run.get("status") not in {"success", "partial_success"} or not answer.strip():
            continue
        answer_hash = hashlib.sha256(answer.encode("utf-8")).hexdigest()
        boundary_status = str((run.get("answer_content_boundary") or {}).get("status") or "")
        if boundary_status == "LEGACY_MIXED_CONTAINER" or (
            boundary_status != "FINAL_ANSWER_ONLY"
            and legacy_mixed_answer_boundary(answer)["status"] == "LEGACY_MIXED_CONTAINER"
        ):
            failure = {
                "run_id": run.get("run_id"),
                "stage": "ANSWER_INPUT_BOUNDARY",
                "status": "NOT_EVALUATED",
                "error": "历史采集文本混入平台搜索过程，不能作为独立最终回答进入语义分析",
            }
            failures.append(failure)
            answer_jobs.setdefault(
                answer_hash,
                {
                    "answer_hash": answer_hash,
                    "run_ids": [int(run.get("run_id") or 0)],
                    "semantic_input_hash": "",
                    "status": "NOT_EVALUATED_MIXED_ANSWER_BOUNDARY",
                    "result_source": "INPUT_GATE",
                },
            )
            continue
        if answer_hash not in answer_cache and answer_hash not in answer_jobs:
            payload = answer_user_payload(prompt_text, answer, brand_name)
            input_hash = _llm_input_hash(
                V2_ANSWER_SYSTEM,
                payload,
                V2_ANSWER_PROMPT_VERSION,
                V2_ANSWER_SCHEMA_VERSION,
                thinking_mode,
            )
            if answer_llm_policy != "ALLOW_EXTERNAL" and not _cache_row(
                db, input_hash, V2_ANSWER_PROMPT_VERSION, V2_ANSWER_SCHEMA_VERSION
            ):
                answer_jobs[answer_hash] = {
                    "answer_hash": answer_hash,
                    "run_ids": [int(run.get("run_id") or 0)],
                    "semantic_input_hash": input_hash,
                    "status": "PENDING_EXTERNAL_AUTHORIZATION",
                    "result_source": "CACHE_MISS_EXTERNAL_NOT_AUTHORIZED",
                    "error": "当前没有兼容缓存，需获得本固定回答的外部计算授权",
                }
                continue
            try:
                raw_result, result_source = _call_with_usage(
                    db,
                    usage,
                    input_hash=input_hash,
                    prompt_version=V2_ANSWER_PROMPT_VERSION,
                    schema_version=V2_ANSWER_SCHEMA_VERSION,
                    call=lambda: judge.judge_answer(answer, prompt_text, brand_name, db=db),
                )
                answer_cache[answer_hash] = admit_answer_for_input(raw_result, answer)
                answer_jobs[answer_hash] = {
                    "answer_hash": answer_hash,
                    "run_ids": [int(run.get("run_id") or 0)],
                    "semantic_input_hash": input_hash,
                    "status": "ADMITTED_PENDING_PROJECTION",
                    "result_source": result_source,
                }
            except SemanticLLMError as exc:
                failure = _llm_failure(exc)
                answer_jobs[answer_hash] = {
                    "answer_hash": answer_hash,
                    "run_ids": [int(run.get("run_id") or 0)],
                    "semantic_input_hash": input_hash,
                    **failure,
                    "result_source": failure["audit"].get("response_source") or "EXTERNAL_LLM_OR_PROVIDER_FAILURE",
                }
                failures.append({"run_id": run.get("run_id"), "stage": "ANSWER_SEMANTIC", **failure})
                continue
        elif int(run.get("run_id") or 0) not in answer_jobs[answer_hash].setdefault("run_ids", []):
            answer_jobs[answer_hash]["run_ids"].append(int(run.get("run_id") or 0))
        if answer_hash not in answer_cache:
            continue
        result = answer_cache[answer_hash]
        accepted_event_count = 0
        failed_event_count = 0
        review_required_event_count = 0
        accepted_criterion_count = 0
        review_required_criterion_count = 0
        unresolved_items.extend({"run_id": run.get("run_id"), "item": item} for item in result.get("unresolved_items") or [])
        for criterion_index, criterion in enumerate(result.get("selection_criteria") or []):
            reason_text = str(criterion.get("normalized_reason") or "").strip()
            reason_span = str(criterion.get("reason_span") or "")
            located = locate_v2_answer_span(answer, reason_span)
            if not located:
                failures.append({
                    "run_id": run.get("run_id"),
                    "stage": "ANSWER_SEMANTIC_VALIDATION",
                    "criterion_index": criterion_index,
                    "status": "FAILED_GROUNDING",
                    "error": "市场选择标准原文定位失败",
                })
                continue
            projection = assess_normalized_projection(reason_text, located["raw_span"])
            criterion_id = f"mkt-{_hash({'run_id': run.get('run_id'), 'index': criterion_index, 'text': reason_text, 'span': {'raw_text_sha256': located['raw_text_sha256'], 'raw_start': located['raw_start'], 'raw_end': located['raw_end']}})[:20]}"
            requires_review = not projection["fact_consumption_eligible"]
            market_criteria.append({
                "criterion_id": criterion_id,
                "run_id": run.get("run_id"),
                "normalized_reason": reason_text,
                "effective_grounded_text": located["raw_span"],
                "reason_span": located["raw_span"],
                "raw_start": located["raw_start"],
                "raw_end": located["raw_end"],
                "grounding": located,
                "reason_scope": "MARKET_CRITERION",
                "normalization_admission": projection,
                "semantic_validation_status": (
                    "NORMALIZATION_REVIEW_REQUIRED" if requires_review else "VERIFIED_CONSERVATIVE"
                ),
                "normalization_eligible": not requires_review,
                "brand_reason_eligible": False,
                "truth_relation_eligible": False,
            })
            accepted_criterion_count += 1
            if requires_review:
                review_required_criterion_count += 1
                unresolved_items.append({
                    "run_id": run.get("run_id"),
                    "criterion_id": criterion_id,
                    "item": criterion,
                    "reason": "市场选择标准的模型概括超出可确定性验证的原文范围",
                    "admission": projection,
                })
        for index, event in enumerate(result.get("events") or []):
            located = locate_v2_answer_span(answer, str(event.get("answer_span") or ""))
            enums_valid = (
                str(event.get("speech_act") or "") in _SPEECH_ACTS
                and str(event.get("recommendation_strength") or "") in _RECOMMENDATION_STRENGTHS
                and str(event.get("polarity") or "") in _POLARITIES
            )
            if not located or not enums_valid:
                failures.append({
                    "run_id": run.get("run_id"),
                    "stage": "ANSWER_SEMANTIC_VALIDATION",
                    "event_index": index,
                    "error": "事件原文定位失败或枚举越界",
                })
                failed_event_count += 1
                continue
            event_admission = assess_answer_event(event, located["context_span"])
            if event_admission["status"] == "FAILED_SEMANTIC_SCOPE":
                failures.append({
                    "run_id": run.get("run_id"),
                    "stage": "ANSWER_SEMANTIC_VALIDATION",
                    "event_index": index,
                    "status": "FAILED_SEMANTIC_SCOPE",
                    "error": ";".join(event_admission["failures"]),
                })
                failed_event_count += 1
                continue
            event_id = _event_identity(int(run.get("run_id") or 0), event, located)
            reasons: list[dict] = []
            for reason_index, reason in enumerate(event.get("reasons") or []):
                reason_text = str(reason.get("normalized_reason") or "").strip()
                reason_span = str(reason.get("reason_span") or "")
                reason_located = locate_v2_answer_span(answer, reason_span)
                scope = str(reason.get("reason_scope") or "")
                if not reason_text or not reason_located or scope not in _REASON_SCOPES:
                    unresolved_items.append({
                        "run_id": run.get("run_id"),
                        "event_id": event_id,
                        "item": reason,
                        "reason": "理由原文定位失败或 scope 越界",
                    })
                    continue
                projection = assess_normalized_projection(reason_text, reason_located["raw_span"])
                reason_id = f"rsn-{_hash({'event_id': event_id, 'index': reason_index, 'text': reason_text, 'span': {'raw_text_sha256': reason_located['raw_text_sha256'], 'raw_start': reason_located['raw_start'], 'raw_end': reason_located['raw_end']}})[:20]}"
                reasons.append({
                    "reason_id": reason_id,
                    "run_id": run.get("run_id"),
                    "normalized_reason": reason_text,
                    "effective_grounded_text": reason_located["raw_span"],
                    "reason_scope": scope,
                    "reason_span": reason_located["raw_span"],
                    "raw_start": reason_located["raw_start"],
                    "raw_end": reason_located["raw_end"],
                    "grounding": reason_located,
                    "entity": str(event.get("entity_text") or "") if scope == "ENTITY_SPECIFIC" else "",
                    "normalization_admission": projection,
                    "semantic_validation_status": projection["status"],
                    "fact_consumption_eligible": projection["fact_consumption_eligible"],
                })
                if not projection["fact_consumption_eligible"]:
                    unresolved_items.append({
                        "run_id": run.get("run_id"),
                        "event_id": event_id,
                        "reason_id": reason_id,
                        "item": reason,
                        "reason": "模型概括超出可确定性验证的原文范围",
                        "admission": projection,
                    })
            event_requires_review = (
                event_admission["status"] == "SEMANTIC_REVIEW_REQUIRED"
                or any(not reason["fact_consumption_eligible"] for reason in reasons)
            )
            events.append({
                "event_id": event_id,
                "run_id": run.get("run_id"),
                "entity_text": str(event.get("entity_text") or ""),
                "entity_type": str(event.get("entity_type") or "UNKNOWN"),
                "machine_speech_act": event.get("speech_act"),
                "effective_speech_act": event.get("speech_act"),
                "recommendation_strength": event.get("recommendation_strength"),
                "polarity": event.get("polarity"),
                "answer_span": located["raw_span"],
                "raw_start": located["raw_start"],
                "raw_end": located["raw_end"],
                "grounding": located,
                "reasons": reasons,
                "semantic_admission": event_admission,
                "semantic_validation_status": "SEMANTIC_REVIEW_REQUIRED" if event_requires_review else "VERIFIED_CONSERVATIVE",
                "fact_consumption_eligible": not event_requires_review,
                "review_status": "SEMANTIC_REVIEW_REQUIRED" if event_requires_review else "MACHINE_GROUNDED",
            })
            accepted_event_count += 1
            if event_requires_review:
                review_required_event_count += 1
        accepted_item_count = accepted_event_count + accepted_criterion_count
        review_required_count = (
            review_required_event_count
            + review_required_criterion_count
            + len(result.get("unresolved_items") or [])
        )
        if failed_event_count and not accepted_item_count:
            status = "FAILED_VALIDATION"
        elif failed_event_count:
            status = "DONE_WITH_FAILURES"
        elif review_required_count and not accepted_item_count:
            status = "SEMANTIC_REVIEW_REQUIRED"
        elif review_required_count:
            status = "DONE_WITH_REVIEW_REQUIRED"
        elif accepted_item_count:
            status = "DONE"
        else:
            status = "DONE_ZERO_EVENTS"
        answer_jobs[answer_hash].update({
            "status": status,
            "accepted_event_count": accepted_event_count,
            "failed_event_count": failed_event_count,
            "review_required_event_count": review_required_event_count,
            "accepted_market_criterion_count": accepted_criterion_count,
            "review_required_market_criterion_count": review_required_criterion_count,
            "unresolved_item_count": len(result.get("unresolved_items") or []),
        })
    return {
        "events": events,
        "market_criteria": market_criteria,
        "unresolved_items": unresolved_items,
        "failures": failures,
        "answer_jobs": sorted(
            answer_jobs.values(),
            key=lambda row: (min(row.get("run_ids") or [0]), str(row.get("answer_hash") or "")),
        ),
        "unique_answers_judged": len(answer_jobs),
    }


def _source_key(reference: dict) -> tuple[str, str]:
    canonical = canonicalize_url(str(reference.get("canonical_url") or reference.get("url") or ""))
    fallback = "|".join([str(reference.get("domain") or ""), str(reference.get("title") or "")])
    identity = canonical or fallback
    return _hash({"source_identity": identity}), canonical


def _attach_prior_review_provenance(
    db: Session,
    execution: SinglePromptDiagnosisExecution,
    answer_diagnosis: dict[str, Any],
) -> None:
    """Annotate exact reusable judgments without granting review authority."""
    current_events = {
        str(row.get("event_id")): row
        for row in answer_diagnosis.get("events") or []
        if row.get("event_id")
    }
    prior_rows = (
        db.query(SinglePromptDiagnosisResult, SinglePromptDiagnosisExecution)
        .join(
            SinglePromptDiagnosisExecution,
            SinglePromptDiagnosisExecution.diagnosis_id == SinglePromptDiagnosisResult.diagnosis_id,
        )
        .filter(
            SinglePromptDiagnosisExecution.analysis_id == execution.analysis_id,
            SinglePromptDiagnosisExecution.context_id == execution.context_id,
            SinglePromptDiagnosisExecution.diagnosis_id != execution.diagnosis_id,
        )
        .order_by(SinglePromptDiagnosisResult.created_at.desc())
        .all()
    )
    reused_events: dict[str, dict[str, Any]] = {}
    reused_run_ids: set[int] = set()
    source_reviews: set[str] = set()
    context = db.query(SinglePromptAnalysisContext).filter_by(
        context_id=execution.context_id,
        analysis_id=execution.analysis_id,
    ).one_or_none()
    run_ids_by_answer_hash = {
        hashlib.sha256(str(row.get("answer_text") or "").encode("utf-8")).hexdigest(): int(row.get("run_id") or 0)
        for row in (loads(context.raw_output_json, {}).get("runs") or []) if context and row.get("run_id")
    }
    for prior_result, _prior_execution in prior_rows:
        review = db.query(SinglePromptDiagnosisReview).filter_by(
            diagnosis_id=prior_result.diagnosis_id,
            result_version=prior_result.result_version,
        ).one_or_none()
        if not review or review.decision != "REVIEW_COMPLETED":
            continue
        prior_output = loads(prior_result.output_json, {})
        prior_events = {
            str(row.get("event_id")): row
            for row in (prior_output.get("answer_diagnosis") or {}).get("events") or []
            if row.get("event_id")
        }
        decisions = {
            str(row.get("event_id")): str(row.get("decision"))
            for row in loads(review.decisions_json, [])
            if row.get("scope") == "ANSWER_SEMANTIC_EVENT" and row.get("event_id")
        }
        for event_id, current in current_events.items():
            if event_id in reused_events:
                continue
            prior = prior_events.get(event_id)
            if not prior:
                continue
            comparable_fields = (
                "run_id", "entity_text", "machine_speech_act", "effective_speech_act",
                "recommendation_strength", "polarity", "answer_span", "raw_start", "raw_end",
            )
            if any(current.get(field) != prior.get(field) for field in comparable_fields):
                continue
            current_reason_ids = sorted(str(row.get("reason_id")) for row in current.get("reasons") or [])
            prior_reason_ids = sorted(str(row.get("reason_id")) for row in prior.get("reasons") or [])
            if current_reason_ids != prior_reason_ids:
                continue
            reused_events[event_id] = {
                "event_id": event_id,
                "run_id": int(current.get("run_id") or 0),
                "source_review_id": review.review_id,
                "source_result_version": prior_result.result_version,
                "prior_decision": decisions.get(event_id) or "CONFIRMED_BY_RESULT_REVIEW",
                "identity_match": "EXACT_EVENT_AND_REASON_IDENTITY",
            }
            reused_run_ids.add(int(current.get("run_id") or 0))
            source_reviews.add(review.review_id)
        prior_jobs = (prior_output.get("answer_diagnosis") or {}).get("answer_jobs") or []
        for job in prior_jobs:
            if job.get("status") == "DONE_ZERO_EVENTS":
                prior_run_ids = [int(value) for value in job.get("run_ids") or []]
                if not prior_run_ids and job.get("answer_hash") in run_ids_by_answer_hash:
                    prior_run_ids = [run_ids_by_answer_hash[str(job.get("answer_hash"))]]
                reused_run_ids.update(prior_run_ids)
                source_reviews.add(review.review_id)
    answer_diagnosis["review_reuse_provenance"] = {
        "events": sorted(reused_events.values(), key=lambda row: (row["run_id"], row["event_id"])),
        "run_ids": sorted(value for value in reused_run_ids if value),
        "source_review_ids": sorted(source_reviews),
        "authority": "PREFILL_ONLY_NEW_EXACT_RESULT_REVIEW_REQUIRED",
    }


def _group_references(raw_output: dict) -> list[dict]:
    grouped: dict[str, dict] = {}
    for run in raw_output.get("runs") or []:
        for reference in run.get("references") or []:
            key, canonical = _source_key(reference)
            row = grouped.setdefault(key, {
                "source_key": key,
                "canonical_url": canonical,
                "original_urls": set(),
                "observations": [],
            })
            if reference.get("url"):
                row["original_urls"].add(str(reference["url"]))
            row["observations"].append({
                "run_id": run.get("run_id"),
                "reference_id": reference.get("reference_id"),
                "reference_index": reference.get("index"),
                "title": reference.get("title") or "",
                "domain": reference.get("domain") or "",
            })
    return [
        {**row, "original_urls": sorted(row["original_urls"])}
        for _, row in sorted(grouped.items())
    ]


def _split_passages(clean_text: str, source_key: str) -> list[dict]:
    passages: list[dict] = []
    paragraphs = [part.strip() for part in re.split(r"\n+", clean_text or "") if len(part.strip()) >= 20]
    for paragraph in paragraphs:
        chunks = [paragraph[i:i + 1500] for i in range(0, len(paragraph), 1500)]
        for chunk in chunks:
            content_hash = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
            passages.append({
                "passage_id": f"psg-{source_key[:10]}-{len(passages) + 1}-{content_hash[:10]}",
                "text": chunk,
                "content_hash": content_hash,
            })
    return passages


_SOURCE_CHALLENGE_MARKERS = (
    "验证码",
    "安全验证",
    "请完成验证",
    "人机验证",
    "security verification",
    "access denied",
    "are you a robot",
)


def _source_content_block_reason(title: str, clean_text: str) -> str:
    sample = f"{title}\n{clean_text[:2000]}".lower()
    marker = next((item for item in _SOURCE_CHALLENGE_MARKERS if item.lower() in sample), "")
    return f"疑似验证/拦截页面（marker={marker}）" if marker else ""


def _load_or_fetch_snapshots(
    db: Session,
    execution: SinglePromptDiagnosisExecution,
    grouped_references: list[dict],
    fetcher: Callable[[list[str]], list[dict]],
    source_snapshot_policy: str = "REUSE_OR_FETCH",
) -> list[SinglePromptSourceSnapshot]:
    existing = {
        row.source_key: row
        for row in db.query(SinglePromptSourceSnapshot).filter(
            SinglePromptSourceSnapshot.diagnosis_id == execution.diagnosis_id
        ).all()
    }
    missing = [row for row in grouped_references if row["source_key"] not in existing]
    reusable_by_key: dict[str, SinglePromptSourceSnapshot] = {}
    reusable_failure_by_key: dict[str, SinglePromptSourceSnapshot] = {}
    if missing:
        missing_keys = [row["source_key"] for row in missing]
        reusable_rows = (
            db.query(SinglePromptSourceSnapshot)
            .filter(
                SinglePromptSourceSnapshot.diagnosis_id != execution.diagnosis_id,
                SinglePromptSourceSnapshot.source_key.in_(missing_keys),
                SinglePromptSourceSnapshot.parser_version == SOURCE_SNAPSHOT_PARSER_VERSION,
            )
            .order_by(SinglePromptSourceSnapshot.created_at.desc())
            .all()
        )
        for prior in reusable_rows:
            block_reason = _source_content_block_reason(prior.title, prior.clean_text)
            if block_reason and prior.fetch_status in {"SUCCESS", "PARTIAL"}:
                if source_snapshot_policy == "REUSE_ONLY" and prior.source_key not in reusable_failure_by_key:
                    reusable_failure_by_key[prior.source_key] = prior
                continue
            if prior.fetch_status not in {"SUCCESS", "PARTIAL"}:
                if source_snapshot_policy == "REUSE_ONLY" and prior.source_key not in reusable_failure_by_key:
                    reusable_failure_by_key[prior.source_key] = prior
                continue
            if prior.source_key in reusable_by_key:
                continue
            content_hash = hashlib.sha256((prior.clean_text or "").encode("utf-8")).hexdigest()
            passages = loads(prior.passages_json, [])
            if not prior.clean_text or content_hash != prior.content_hash or _hash(passages) != prior.passages_hash:
                continue
            reusable_by_key[prior.source_key] = prior

    still_missing: list[dict] = []
    for row in missing:
        prior = reusable_by_key.get(row["source_key"])
        if not prior and source_snapshot_policy == "REUSE_ONLY":
            prior = reusable_failure_by_key.get(row["source_key"])
        if not prior:
            still_missing.append(row)
            continue
        block_reason = _source_content_block_reason(prior.title, prior.clean_text)
        is_content_reuse = prior.fetch_status in {"SUCCESS", "PARTIAL"} and not block_reason
        effective_status = prior.fetch_status if is_content_reuse else (
            "CONTENT_BLOCKED" if block_reason else prior.fetch_status
        )
        passages_json = prior.passages_json if is_content_reuse else "[]"
        db.add(SinglePromptSourceSnapshot(
            snapshot_id=f"src-{uuid4()}",
            diagnosis_id=execution.diagnosis_id,
            source_key=row["source_key"],
            canonical_url=row["canonical_url"],
            original_urls_json=_canonical_json(row["original_urls"]),
            reference_observations_json=_canonical_json(row["observations"]),
            occurrence_count=len(row["observations"]),
            fetch_status=effective_status,
            failure_reason="" if is_content_reuse else (block_reason or prior.failure_reason),
            fetched_at=prior.fetched_at,
            title=prior.title,
            content_hash=prior.content_hash,
            clean_text=prior.clean_text,
            passages_json=passages_json,
            passages_hash=prior.passages_hash if is_content_reuse else _hash([]),
            parser_version=prior.parser_version,
            fetch_source="V2_SNAPSHOT_REUSE" if is_content_reuse else "V2_FAILURE_SNAPSHOT_REUSE",
            reused_from_snapshot_id=prior.snapshot_id,
        ))
    if len(still_missing) != len(missing):
        db.commit()
    missing = still_missing
    if source_snapshot_policy == "REUSE_ONLY":
        for row in missing:
            db.add(SinglePromptSourceSnapshot(
                snapshot_id=f"src-{uuid4()}",
                diagnosis_id=execution.diagnosis_id,
                source_key=row["source_key"],
                canonical_url=row["canonical_url"],
                original_urls_json=_canonical_json(row["original_urls"]),
                reference_observations_json=_canonical_json(row["observations"]),
                occurrence_count=len(row["observations"]),
                fetch_status="FETCH_FAILED",
                failure_reason="本次执行禁止外部正文抓取，且没有可复用的不可变快照",
                fetched_at=None,
                title=str(row["observations"][0].get("title") if row["observations"] else "")[:500],
                content_hash="",
                clean_text="",
                passages_json="[]",
                passages_hash=_hash([]),
                parser_version=SOURCE_SNAPSHOT_PARSER_VERSION,
                fetch_source="FETCH_DISABLED",
                reused_from_snapshot_id=None,
            ))
        if missing:
            db.commit()
        missing = []
    urls = [row["canonical_url"] or (row["original_urls"][0] if row["original_urls"] else "") for row in missing]
    fetchable_positions = [index for index, url in enumerate(urls) if url]
    fetched_by_position: dict[int, dict] = {}
    if fetchable_positions:
        requested = [urls[index] for index in fetchable_positions]
        try:
            if fetcher is fetch_page_playwright:
                fetched = fetcher(
                    requested,
                    progress_callback=lambda completed, total: _set_progress(
                        db,
                        execution,
                        "SOURCE_SNAPSHOT",
                        completed,
                        total,
                        f"已处理 {completed}/{total} 个唯一引用来源",
                    ),
                )
            else:
                fetched = fetcher(requested)
        except Exception as exc:
            fetched = [{"fetch_status": "FETCH_FAILED", "failure_reason": str(exc)[:500]} for _ in requested]
        for requested_index, position in enumerate(fetchable_positions):
            fetched_by_position[position] = fetched[requested_index] if requested_index < len(fetched) else {
                "fetch_status": "FETCH_FAILED",
                "failure_reason": "正文抓取器未返回对应结果",
            }

    for position, row in enumerate(missing):
        result = fetched_by_position.get(position) or {
            "fetch_status": "FETCH_FAILED",
            "failure_reason": "引用缺少可抓取 URL",
        }
        status = str(result.get("fetch_status") or "FETCH_FAILED").upper()
        clean_text = str(result.get("clean_text") or "")
        if status in {"SUCCESS", "PARTIAL"} and not clean_text.strip():
            status = "FETCH_FAILED"
            result = {**result, "failure_reason": "抓取结果没有可用正文"}
        block_reason = _source_content_block_reason(str(result.get("title") or ""), clean_text)
        if status in {"SUCCESS", "PARTIAL"} and block_reason:
            status = "CONTENT_BLOCKED"
            result = {**result, "failure_reason": block_reason}
        passages = _split_passages(clean_text, row["source_key"]) if status in {"SUCCESS", "PARTIAL"} else []
        fetched_at = result.get("fetch_time")
        if isinstance(fetched_at, str):
            try:
                fetched_at = datetime.fromisoformat(fetched_at.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                fetched_at = None
        snapshot = SinglePromptSourceSnapshot(
            snapshot_id=f"src-{uuid4()}",
            diagnosis_id=execution.diagnosis_id,
            source_key=row["source_key"],
            canonical_url=row["canonical_url"],
            original_urls_json=_canonical_json(row["original_urls"]),
            reference_observations_json=_canonical_json(row["observations"]),
            occurrence_count=len(row["observations"]),
            fetch_status=status,
            failure_reason=str(result.get("failure_reason") or "")[:2000],
            fetched_at=fetched_at or datetime.utcnow(),
            title=str(result.get("title") or (row["observations"][0].get("title") if row["observations"] else ""))[:500],
            content_hash=hashlib.sha256(clean_text.encode("utf-8")).hexdigest() if clean_text else "",
            clean_text=clean_text,
            passages_json=_canonical_json(passages),
            passages_hash=_hash(passages),
            parser_version=SOURCE_SNAPSHOT_PARSER_VERSION,
            fetch_source="EXTERNAL_FETCH",
            reused_from_snapshot_id=None,
        )
        db.add(snapshot)
    if missing:
        db.commit()
    return (
        db.query(SinglePromptSourceSnapshot)
        .filter(SinglePromptSourceSnapshot.diagnosis_id == execution.diagnosis_id)
        .order_by(SinglePromptSourceSnapshot.source_key)
        .all()
    )


def _reference_anchor_status(reason: dict, snapshot: SinglePromptSourceSnapshot) -> str:
    span = str(reason.get("reason_span") or "")
    for observation in loads(snapshot.reference_observations_json, []):
        if int(observation.get("run_id") or 0) != int(reason.get("run_id") or 0):
            continue
        index = observation.get("reference_index")
        if index and re.search(rf"\[{int(index)}\]", span):
            return "EXPLICIT"
    return "UNPROVEN"


def _validated_source_claims(passage: dict, result: dict) -> tuple[list[dict], list[dict]]:
    claims: list[dict] = []
    failures: list[dict] = []
    for index, claim in enumerate(result.get("claims") or []):
        claim_type = str(claim.get("claim_type") or "OTHER").upper()
        polarity = str(claim.get("polarity") or "NEUTRAL").upper()
        span = str(claim.get("source_span") or "")
        located = locate_span(passage["text"], span)
        if not located or claim_type not in _CLAIM_TYPES or polarity not in _POLARITIES:
            failures.append({"claim_index": index, "error": "SourceClaim 原文定位失败或枚举越界"})
            continue
        normalized = str(claim.get("normalized_claim") or "").strip()
        if not normalized:
            failures.append({"claim_index": index, "error": "SourceClaim 缺少 normalized_claim"})
            continue
        if contains_untrusted_instruction(located["raw_span"]):
            failures.append({
                "claim_index": index,
                "status": "FAILED_SEMANTIC_SCOPE",
                "error": "外部正文中的指令文本不能物化为 SourceClaim",
            })
            continue
        if not source_subject_is_grounded(str(claim.get("subject_text") or ""), located["raw_span"]):
            failures.append({
                "claim_index": index,
                "status": "FAILED_SEMANTIC_SCOPE",
                "error": "SourceClaim 主体无法在原文片段中定位",
            })
            continue
        projection = assess_normalized_projection(normalized, located["raw_span"])
        claims.append({
            "claim_id": f"clm-{_hash({'passage': passage['passage_id'], 'claim': claim, 'located': located})[:20]}",
            "normalized_claim": normalized,
            "effective_grounded_text": located["raw_span"],
            "subject_text": str(claim.get("subject_text") or ""),
            "predicate": str(claim.get("predicate") or ""),
            "object_text": str(claim.get("object_text") or ""),
            "claim_type": claim_type,
            "polarity": polarity,
            "source_span": located["raw_span"],
            "passage_id": passage["passage_id"],
            "normalization_admission": projection,
            "semantic_validation_status": projection["status"],
            "fact_consumption_eligible": projection["fact_consumption_eligible"],
            "review_status": "MACHINE_GROUNDED" if projection["fact_consumption_eligible"] else "SEMANTIC_REVIEW_REQUIRED",
        })
    return claims, failures


def _claim_score(reason_text: str, claim: dict) -> float:
    reason_tokens = set(tokenize_zh(reason_text))
    claim_tokens = set(tokenize_zh(" ".join([
        claim.get("effective_grounded_text") or "",
        claim.get("source_span") or "",
    ])))
    return len(reason_tokens & claim_tokens) / max(len(reason_tokens), 1) if reason_tokens and claim_tokens else 0.0


def _entity_precheck(reason: dict, claim: dict) -> str:
    if reason.get("reason_scope") == "MARKET_CRITERION":
        return "PASS_MARKET"
    entity = str(reason.get("entity") or "").strip()
    subject = str(claim.get("subject_text") or "").strip()
    if not entity:
        return "PASS"
    if subject and subject not in {"UNKNOWN", "该工具", "该产品", "该平台", "它", "其"}:
        return "PASS" if entity in subject or subject in entity else "ENTITY_SCOPE_MISMATCH"
    source_text = str(claim.get("effective_grounded_text") or claim.get("source_span") or "")
    return "PASS_INFERRED_FROM_SPAN" if entity in source_text else "ENTITY_SCOPE_UNRESOLVED"


def _source_claim_job(
    db: Session,
    *,
    passage: dict[str, Any],
    usage: dict[str, int],
    source_claim_judge: Any,
    config: dict[str, Any],
) -> tuple[list[dict], list[dict], dict]:
    input_hash = _llm_input_hash(
        V2_SOURCE_CLAIM_SYSTEM,
        source_claim_user_payload(passage["text"]),
        V2_SOURCE_CLAIM_PROMPT_VERSION,
        V2_SOURCE_CLAIM_SCHEMA_VERSION,
        str(config.get("llm_thinking_mode") or "") or None,
    )
    base_job = {
        "passage_id": passage["passage_id"],
        "source_snapshot_id": passage["snapshot_id"],
        "semantic_input_hash": input_hash,
    }
    if config.get("evidence_llm_policy") == "CACHE_ONLY" and not _cache_row(
        db, input_hash, V2_SOURCE_CLAIM_PROMPT_VERSION, V2_SOURCE_CLAIM_SCHEMA_VERSION
    ):
        return [], [], {
            **base_job,
            "status": "PENDING_EXTERNAL_AUTHORIZATION",
            "result_source": "CACHE_MISS_EXTERNAL_NOT_AUTHORIZED",
            "claim_count": 0,
            "accepted_claim_count": 0,
            "rejected_claim_count": 0,
            "empty_result": False,
        }
    try:
        result, result_source = _call_with_usage(
            db,
            usage,
            input_hash=input_hash,
            prompt_version=V2_SOURCE_CLAIM_PROMPT_VERSION,
            schema_version=V2_SOURCE_CLAIM_SCHEMA_VERSION,
            call=lambda: source_claim_judge.judge_passage(passage["text"], db=db),
        )
        # Envelope/schema admission is atomic. Grounding and semantic scope are
        # isolated below so independent valid claims survive a bad sibling item.
        result = admit_source_claim_response(result)
        claims, failures = _validated_source_claims(passage, result)
        review_required_count = sum(not claim["fact_consumption_eligible"] for claim in claims)
        valid_count = sum(claim["fact_consumption_eligible"] for claim in claims)
        if not result["claims"]:
            status = "DONE_ZERO_CLAIMS"
        elif failures and not claims:
            status = "FAILED_VALIDATION"
        elif failures:
            status = "DONE_WITH_FAILURES"
        elif review_required_count and not valid_count:
            status = "SEMANTIC_REVIEW_REQUIRED"
        elif review_required_count:
            status = "DONE_WITH_REVIEW_REQUIRED"
        else:
            status = "DONE"
        return claims, failures, {
            **base_job,
            "status": status,
            "result_source": result_source,
            "claim_count": len(claims),
            "accepted_claim_count": len(claims),
            "rejected_claim_count": len(failures),
            "consumable_claim_count": valid_count,
            "review_required_count": review_required_count,
            "empty_result": not result["claims"],
        }
    except SemanticLLMError as exc:
        failure = _llm_failure(exc)
        return [], [{"passage_id": passage["passage_id"], **failure}], {
            **base_job,
            "status": failure["status"],
            "result_source": failure["audit"].get("response_source") or "EXTERNAL_LLM_OR_PROVIDER_FAILURE",
            "claim_count": 0,
            "accepted_claim_count": 0,
            "rejected_claim_count": 0,
            "consumable_claim_count": 0,
            "review_required_count": 0,
            "empty_result": False,
            "error": failure["error"],
            "audit": failure["audit"],
        }


def _technical_claim_failure(job: dict[str, Any]) -> bool:
    status = str(job.get("status") or "")
    return status.startswith("FAILED") or status == "CACHE_REJECTED_BY_V2_VALIDATION"


def _build_candidate_plan_for_evidence(
    answer_diagnosis: dict,
    snapshots: list[SinglePromptSourceSnapshot],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    all_reasons = [reason for event in answer_diagnosis["events"] for reason in event["reasons"]]
    reasons = [reason for reason in all_reasons if reason.get("fact_consumption_eligible") is True]
    all_passages = [
        {**passage, "snapshot_id": snapshot.snapshot_id, "source_key": snapshot.source_key}
        for snapshot in snapshots
        if snapshot.fetch_status in {"SUCCESS", "PARTIAL"}
        and not _source_content_block_reason(snapshot.title, snapshot.clean_text)
        for passage in loads(snapshot.passages_json, [])
    ]
    observed_source_keys_by_run: dict[int, set[str]] = {}
    for snapshot in snapshots:
        for observation in loads(snapshot.reference_observations_json, []):
            observed_source_keys_by_run.setdefault(int(observation.get("run_id") or 0), set()).add(snapshot.source_key)
    explicit_source_keys_by_reason = {
        str(reason["reason_id"]): {
            snapshot.source_key
            for snapshot in snapshots
            if _reference_anchor_status(reason, snapshot) == "EXPLICIT"
        }
        for reason in reasons
    }
    plan = build_evidence_candidate_plan(
        reasons,
        all_passages,
        observed_source_keys_by_run,
        explicit_source_keys_by_reason,
    )
    passages_by_id = plan.pop("passages_by_id")
    return plan, passages_by_id


def _diagnose_evidence(
    db: Session,
    *,
    answer_diagnosis: dict,
    snapshots: list[SinglePromptSourceSnapshot],
    usage: dict[str, int],
    source_claim_judge: Any,
    alignment_judge: Any,
    config: dict,
) -> dict:
    all_reasons = [reason for event in answer_diagnosis["events"] for reason in event["reasons"]]
    reasons = [reason for reason in all_reasons if reason.get("fact_consumption_eligible") is True]
    review_required_reasons = [
        {
            "reason_id": reason["reason_id"],
            "status": reason.get("semantic_validation_status") or "SEMANTIC_REVIEW_REQUIRED",
            "admission": reason.get("normalization_admission") or {},
        }
        for reason in all_reasons
        if reason.get("fact_consumption_eligible") is not True
    ]
    candidate_plan, passages_by_id = _build_candidate_plan_for_evidence(answer_diagnosis, snapshots)
    selected: dict[str, list[dict]] = {
        row["reason_id"]: [
            passages_by_id[item["passage_id"]]
            for item in row.get("base_candidates") or []
            if item["passage_id"] in passages_by_id
        ]
        for row in candidate_plan["reason_plans"]
    }
    selected_passages = {
        passage["passage_id"]: passage
        for passages in selected.values()
        for passage in passages
    }
    claims_by_passage: dict[str, list[dict]] = {}
    extracted_claims: list[dict] = []
    claim_failures: list[dict] = []
    claim_jobs_by_passage: dict[str, dict] = {}

    def evaluate_passage(passage: dict[str, Any]) -> dict[str, Any]:
        passage_id = str(passage["passage_id"])
        if passage_id in claim_jobs_by_passage:
            return claim_jobs_by_passage[passage_id]
        claims, failures, job = _source_claim_job(
            db,
            passage=passage,
            usage=usage,
            source_claim_judge=source_claim_judge,
            config=config,
        )
        claims_by_passage[passage_id] = claims
        extracted_claims.extend(claims)
        claim_failures.extend({**failure, "passage_id": passage_id} for failure in failures)
        claim_jobs_by_passage[passage_id] = job
        return job

    for passage in selected_passages.values():
        evaluate_passage(passage)

    fallback_trace: list[dict[str, Any]] = []
    for reason_plan in candidate_plan["reason_plans"]:
        reason_id = str(reason_plan["reason_id"])
        queue = list(reason_plan.get("fallback_queue") or [])
        consumed = 0
        for base in list(reason_plan.get("base_candidates") or []):
            base_job = claim_jobs_by_passage.get(str(base["passage_id"]))
            if not base_job or not _technical_claim_failure(base_job):
                continue
            if consumed >= int(reason_plan.get("fallback_replacement_cap") or 0) or not queue:
                fallback_trace.append({
                    "reason_id": reason_id,
                    "failed_passage_id": base["passage_id"],
                    "failure_status": base_job.get("status"),
                    "replacement_passage_id": None,
                    "outcome": "FALLBACK_CAP_OR_QUEUE_EXHAUSTED",
                })
                continue
            prior_failed_id = base["passage_id"]
            prior_failure_status = base_job.get("status")
            while consumed < int(reason_plan.get("fallback_replacement_cap") or 0) and queue:
                replacement = queue.pop(0)
                passage = passages_by_id[str(replacement["passage_id"])]
                selected.setdefault(reason_id, []).append(passage)
                replacement_job = evaluate_passage(passage)
                consumed += 1
                replacement_failed = _technical_claim_failure(replacement_job)
                fallback_trace.append({
                    "reason_id": reason_id,
                    "failed_passage_id": prior_failed_id,
                    "failure_status": prior_failure_status,
                    "replacement_passage_id": replacement["passage_id"],
                    "replacement_status": replacement_job.get("status"),
                    "outcome": (
                        "PREDECLARED_TECHNICAL_FALLBACK_FAILED"
                        if replacement_failed
                        else "PREDECLARED_TECHNICAL_FALLBACK_CONSUMED"
                    ),
                })
                if not replacement_failed:
                    break
                prior_failed_id = replacement["passage_id"]
                prior_failure_status = replacement_job.get("status")
        reason_plan["fallback_consumed"] = consumed
        reason_plan["remaining_fallback_count"] = len(queue)

    claim_jobs = list(claim_jobs_by_passage.values())
    candidate_plan["fallback_trace"] = fallback_trace

    snapshot_by_id = {row.snapshot_id: row for row in snapshots}
    source_relations: list[dict] = []
    alignment_failures: list[dict] = []
    for reason in reasons:
        selected_for_reason = selected.get(reason["reason_id"], [])
        selected_by_source: dict[str, list[dict]] = {}
        for passage in selected_for_reason:
            selected_by_source.setdefault(passage["snapshot_id"], []).append(passage)
        for snapshot in snapshots:
            passages = selected_by_source.get(snapshot.snapshot_id, [])
            observed_in_reason_run = any(
                int(observation.get("run_id") or 0) == int(reason.get("run_id") or 0)
                for observation in loads(snapshot.reference_observations_json, [])
            )
            relation_id = f"evr-{_hash({'reason': reason['reason_id'], 'source': snapshot.source_key})[:20]}"
            row = {
                "relation_id": relation_id,
                "reason_id": reason["reason_id"],
                "source_snapshot_id": snapshot.snapshot_id,
                "reference_observation": "OBSERVED" if observed_in_reason_run else "NOT_OBSERVED_IN_REASON_RUN",
                "anchor_binding": _reference_anchor_status(reason, snapshot),
                "candidate_recall": "RECALLED" if passages else "NOT_RECALLED",
                "alignment_evaluation": "NOT_EVALUATED",
                "machine_relation": None,
                "effective_relation": None,
                "claim_relations": [],
            }
            if not observed_in_reason_run or not passages:
                source_relations.append(row)
                continue
            if snapshot.fetch_status not in {"SUCCESS", "PARTIAL"}:
                row["alignment_evaluation"] = "UPSTREAM_FETCH_FAILED"
                source_relations.append(row)
                continue
            all_candidate_claims = [claim for passage in passages for claim in claims_by_passage.get(passage["passage_id"], [])]
            candidate_claims = [claim for claim in all_candidate_claims if claim.get("fact_consumption_eligible") is True]
            if not candidate_claims:
                failed_passage_ids = {
                    job["passage_id"]
                    for job in claim_jobs
                    if str(job["status"]).startswith("FAILED") or job["status"] == "CACHE_REJECTED_BY_V2_VALIDATION"
                }
                not_evaluated_passage_ids = {
                    job["passage_id"]
                    for job in claim_jobs
                    if job["status"] in {"NOT_EVALUATED", "PENDING_EXTERNAL_AUTHORIZATION", "PENDING_COMPUTE"}
                }
                if any(p["passage_id"] in failed_passage_ids for p in passages):
                    row["alignment_evaluation"] = "UPSTREAM_CLAIM_FAILED"
                elif any(p["passage_id"] in not_evaluated_passage_ids for p in passages):
                    row["alignment_evaluation"] = "UPSTREAM_CLAIM_NOT_EVALUATED"
                elif all_candidate_claims:
                    row["alignment_evaluation"] = "UPSTREAM_CLAIM_REVIEW_REQUIRED"
                else:
                    row["alignment_evaluation"] = "DONE_ZERO_CLAIMS"
                source_relations.append(row)
                continue
            ranked_claims = sorted(
                candidate_claims,
                key=lambda claim: (-_claim_score(reason["normalized_reason"], claim), claim["claim_id"]),
            )[:int(config["alignment_claims_per_source_reason"])]
            evaluated = 0
            for claim in ranked_claims:
                precheck = _entity_precheck(reason, claim)
                claim_relation = {
                    "claim_id": claim["claim_id"],
                    "precheck": precheck,
                    "evaluation": "NOT_EVALUATED",
                    "relation": None,
                    "rationale": "",
                }
                if precheck in {"ENTITY_SCOPE_MISMATCH", "ENTITY_SCOPE_UNRESOLVED"}:
                    row["claim_relations"].append(claim_relation)
                    continue
                input_hash = _llm_input_hash(
                    V2_ALIGNMENT_SYSTEM,
                    alignment_user_payload(reason["effective_grounded_text"], claim["effective_grounded_text"]),
                    V2_ALIGNMENT_PROMPT_VERSION,
                    V2_ALIGNMENT_SCHEMA_VERSION,
                    str(config.get("llm_thinking_mode") or "") or None,
                )
                if config.get("evidence_llm_policy") == "CACHE_ONLY" and not _cache_row(
                    db, input_hash, V2_ALIGNMENT_PROMPT_VERSION, V2_ALIGNMENT_SCHEMA_VERSION
                ):
                    claim_relation["semantic_input_hash"] = input_hash
                    claim_relation["result_source"] = "CACHE_MISS_EXTERNAL_NOT_AUTHORIZED"
                    row["claim_relations"].append(claim_relation)
                    continue
                try:
                    result, result_source = _call_with_usage(
                        db,
                        usage,
                        input_hash=input_hash,
                        prompt_version=V2_ALIGNMENT_PROMPT_VERSION,
                        schema_version=V2_ALIGNMENT_SCHEMA_VERSION,
                        call=lambda r=reason, c=claim: alignment_judge.judge(r["effective_grounded_text"], c["effective_grounded_text"], db=db),
                    )
                    result = admit_alignment_response(result)
                    relation = str(result["relation"]).upper()
                    relation_admission = assess_alignment_relation(
                        relation,
                        reason["effective_grounded_text"],
                        claim["effective_grounded_text"],
                    )
                    if not relation_admission["fact_consumption_eligible"]:
                        claim_relation.update({
                            "evaluation": "SEMANTIC_REVIEW_REQUIRED",
                            "relation": None,
                            "machine_proposal": relation,
                            "rationale": str(result["rationale"]),
                            "semantic_admission": relation_admission,
                            "semantic_input_hash": input_hash,
                            "result_source": result_source,
                        })
                        row["claim_relations"].append(claim_relation)
                        continue
                    claim_relation.update({
                        "evaluation": "EVALUATED",
                        "relation": relation,
                        "rationale": str(result["rationale"]),
                        "confidence_raw": result["confidence_raw"],
                        "semantic_admission": relation_admission,
                        "semantic_input_hash": input_hash,
                        "result_source": result_source,
                    })
                    evaluated += 1
                except SemanticLLMError as exc:
                    failure = _llm_failure(exc)
                    claim_relation["evaluation"] = failure["status"]
                    claim_relation["semantic_input_hash"] = input_hash
                    claim_relation["result_source"] = failure["audit"].get("response_source") or "EXTERNAL_LLM_OR_PROVIDER_FAILURE"
                    claim_relation["error"] = failure["error"]
                    claim_relation["audit"] = failure["audit"]
                    alignment_failures.append({
                        "relation_id": relation_id,
                        "claim_id": claim["claim_id"],
                        **failure,
                    })
                row["claim_relations"].append(claim_relation)
            relations = [item["relation"] for item in row["claim_relations"] if item["evaluation"] == "EVALUATED"]
            if evaluated:
                aggregate = (
                    "SOURCE_SUPPORTS_REASON" if "SUPPORTS" in relations
                    else "SOURCE_CONTRADICTS_REASON" if "CONTRADICTS" in relations
                    else "RELATED" if "RELATED" in relations
                    else "NONE"
                )
                row["alignment_evaluation"] = "EVALUATED"
                row["machine_relation"] = aggregate
                row["effective_relation"] = aggregate
            elif any(
                str(item["evaluation"]).startswith("FAILED")
                or item["evaluation"] == "CACHE_REJECTED_BY_V2_VALIDATION"
                for item in row["claim_relations"]
            ):
                row["alignment_evaluation"] = "FAILED"
            elif any(item["evaluation"] == "SEMANTIC_REVIEW_REQUIRED" for item in row["claim_relations"]):
                row["alignment_evaluation"] = "SEMANTIC_REVIEW_REQUIRED"
            else:
                row["alignment_evaluation"] = "HARD_FILTERED"
            source_relations.append(row)
    candidate_plan["execution_complete"] = all(
        str(job.get("status") or "") not in {
            "NOT_EVALUATED", "PENDING_EXTERNAL_AUTHORIZATION", "PENDING_COMPUTE", "RUNNING",
        }
        for job in claim_jobs
    )
    return {
        "candidate_plan": candidate_plan,
        "source_claim_jobs": claim_jobs,
        "source_claims": extracted_claims,
        "source_claim_failures": claim_failures,
        "source_relations": source_relations,
        "alignment_failures": alignment_failures,
        "reason_inputs_requiring_review": review_required_reasons,
    }


def _normalize_truth_text(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (value or "").lower())


def _truth_relation(reason: dict, truth: dict) -> tuple[str, str]:
    status = str(truth.get("product_truth_status") or "UNKNOWN").upper()
    reason_text = _normalize_truth_text(reason.get("effective_grounded_text") or reason.get("reason_span") or "")
    normalized_reason = _normalize_truth_text(reason.get("normalized_reason") or "")
    label = _normalize_truth_text(truth.get("capability_label") or truth.get("capability_key") or "")
    if not reason_text or not label:
        return "UNRESOLVED", "MISSING_SEMANTIC_LABEL"
    if reason_text == label:
        match_method = "EXACT_GROUNDED_CAPABILITY_LABEL"
    elif label in reason_text or reason_text in label:
        match_method = "GROUNDED_LEXICAL_CONTAINMENT"
    elif normalized_reason and normalized_reason == label:
        match_method = "NORMALIZED_CANDIDATE_EXACT"
    elif normalized_reason and (label in normalized_reason or normalized_reason in label):
        match_method = "NORMALIZED_CANDIDATE_CONTAINMENT"
    else:
        return "UNRESOLVED", "NO_APPROVED_MAPPING"
    if status in {"FALSE", "NOT_SUPPORTED", "UNSUPPORTED"} and match_method == "EXACT_GROUNDED_CAPABILITY_LABEL":
        return "CONFLICTS", "EXACT_REVIEWED_FALSE"
    if status not in {"TRUE", "SUPPORTED"}:
        return "UNRESOLVED", "TRUTH_NOT_POSITIVE"
    if match_method == "EXACT_GROUNDED_CAPABILITY_LABEL":
        return "FULLY_COVERS", match_method
    if match_method == "GROUNDED_LEXICAL_CONTAINMENT":
        return "PARTIALLY_COVERS", "LEXICAL_CONTAINMENT_REQUIRES_REVIEW"
    return "UNRESOLVED", f"{match_method}_REQUIRES_REVIEW"


def _atomic_capability_coverage(reason: dict, truth_snapshot: list[dict]) -> dict[str, Any]:
    """Project a compound grounded reason onto explicitly reviewed atomic capabilities."""
    grounded_text = str(reason.get("effective_grounded_text") or reason.get("reason_span") or "").strip()
    required_labels = _split_target_capability_candidates(grounded_text)
    required = [
        {
            "capability_key": re.sub(r"[\s\W_]+", "", label.lower()),
            "capability_label": label,
        }
        for label in required_labels
        if re.sub(r"[\s\W_]+", "", label.lower())
    ]
    truths_by_key = {
        str(row.get("capability_key") or ""): row
        for row in truth_snapshot
        if row.get("capability_key")
    }
    covered: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for item in required:
        truth = truths_by_key.get(item["capability_key"])
        if (
            truth
            and truth.get("product_truth_status") in {"TRUE", "SUPPORTED"}
            and truth.get("truth_source") == "MANUAL_CONFIRMED"
        ):
            covered.append({
                **item,
                "truth_id": truth.get("truth_id"),
                "statement_eligibility": copy.deepcopy(truth.get("statement_eligibility") or {}),
            })
        else:
            missing.append(item)
    relation = (
        "FULLY_COVERS" if required and not missing
        else "PARTIALLY_COVERS" if covered
        else "UNRESOLVED"
    )
    return {
        "coverage_id": f"trc-{_hash({'reason': reason.get('reason_id'), 'required': required})[:20]}",
        "reason_id": reason.get("reason_id"),
        "effective_relation": relation,
        "method": "ATOMIC_CAPABILITY_SET_EXACT",
        "required_capabilities": required,
        "covered_capabilities": covered,
        "missing_capabilities": missing,
        "truth_ids": sorted(
            int(row["truth_id"])
            for row in covered
            if row.get("truth_id") is not None
        ),
        "fact_consumption_eligible": reason.get("fact_consumption_eligible") is True,
    }


def _diagnose_truths(
    answer_diagnosis: dict,
    truth_snapshot: list[dict],
    *,
    target_brand: dict[str, Any] | None = None,
) -> dict:
    reasons = [reason for event in answer_diagnosis["events"] for reason in event["reasons"]]
    target_brand = target_brand or {}
    target_subject_labels = {
        _normalize_truth_text(str(value))
        for value in [target_brand.get("brand_name"), *(target_brand.get("aliases") or [])]
        if str(value or "").strip()
    }
    target_reasons = [
        reason
        for reason in reasons
        if _normalize_truth_text(str(reason.get("entity") or "")) in target_subject_labels
    ]
    reason_capability_coverage = [
        _atomic_capability_coverage(reason, truth_snapshot)
        for reason in target_reasons
        if reason.get("fact_consumption_eligible") is True
    ]
    relationships: list[dict] = []
    external_capability_signals: list[dict] = []
    for reason in reasons:
        source_subject = str(reason.get("entity") or "").strip()
        source_subject_key = _normalize_truth_text(source_subject)
        is_target_subject = bool(source_subject_key and source_subject_key in target_subject_labels)
        if not is_target_subject:
            reason_text_key = _normalize_truth_text(
                str(reason.get("effective_grounded_text") or reason.get("reason_span") or "")
            )
            target_peer_reason_ids = sorted({
                str(peer.get("reason_id"))
                for peer in target_reasons
                if reason.get("run_id") is not None
                and peer.get("run_id") == reason.get("run_id")
                and reason_text_key
                and _normalize_truth_text(
                    str(peer.get("effective_grounded_text") or peer.get("reason_span") or "")
                ) == reason_text_key
            })
            signal_context = (
                "CO_RECOMMENDED_WITH_TARGET"
                if target_peer_reason_ids
                else "EXTERNAL_ONLY"
            )
            target_truth_matches: list[dict[str, Any]] = []
            if reason.get("fact_consumption_eligible") is True and not target_peer_reason_ids:
                for truth in truth_snapshot:
                    relation, method = _truth_relation(reason, truth)
                    if relation == "UNRESOLVED" and method == "NO_APPROVED_MAPPING":
                        continue
                    target_truth_matches.append({
                        "truth_id": truth.get("truth_id"),
                        "applicability": (
                            "ELIGIBLE"
                            if relation == "FULLY_COVERS" and method == "EXACT_GROUNDED_CAPABILITY_LABEL"
                            else "VERIFY_FIRST"
                        ),
                        "match_relation": relation,
                        "method": method,
                        "boundary": "TARGET_APPLICABILITY_ONLY_NOT_SOURCE_FACT_PROOF",
                    })
            external_capability_signals.append({
                "signal_id": f"ext-{_hash({'reason': reason['reason_id'], 'subject': source_subject})[:20]}",
                "reason_id": reason["reason_id"],
                "source_subject": source_subject,
                "capability_text": str(reason.get("effective_grounded_text") or reason.get("reason_span") or ""),
                "normalized_capability": str(reason.get("normalized_reason") or ""),
                "fact_consumption_eligible": reason.get("fact_consumption_eligible") is True,
                "target_truth_matches": target_truth_matches,
                "signal_context": signal_context,
                "target_peer_reason_ids": target_peer_reason_ids,
                "target_review_trigger_eligible": not target_peer_reason_ids,
                "use_boundary": (
                    "CO_RECOMMENDED_CONTEXT_ONLY"
                    if target_peer_reason_ids
                    else "EXTERNAL_SIGNAL_ONLY"
                ),
            })
            continue
        if reason.get("fact_consumption_eligible") is not True:
            relationships.append({
                "relationship_id": f"trl-{_hash({'reason': reason['reason_id'], 'truth': 'semantic-review'})[:20]}",
                "reason_id": reason["reason_id"],
                "truth_id": None,
                "machine_relation": "UNRESOLVED",
                "effective_relation": "UNRESOLVED",
                "method": "SEMANTIC_INPUT_REVIEW_REQUIRED",
                "review_status": "SEMANTIC_REVIEW_REQUIRED",
            })
            continue
        if not truth_snapshot:
            relationships.append({
                "relationship_id": f"trl-{_hash({'reason': reason['reason_id'], 'truth': None})[:20]}",
                "reason_id": reason["reason_id"],
                "truth_id": None,
                "machine_relation": "UNRESOLVED",
                "effective_relation": "UNRESOLVED",
                "method": "EMPTY_TRUTH_SET",
                "review_status": "NEEDS_FACT_INPUT",
            })
            continue
        matched_truth = False
        for truth in truth_snapshot:
            relation, method = _truth_relation(reason, truth)
            if relation == "UNRESOLVED" and method == "NO_APPROVED_MAPPING":
                continue
            matched_truth = True
            requires_review = method.endswith("REQUIRES_REVIEW") or method == "TRUTH_STATEMENT_NOT_CLAIM_ELIGIBLE"
            effective_relation = "UNRESOLVED" if requires_review else relation
            relationships.append({
                "relationship_id": f"trl-{_hash({'reason': reason['reason_id'], 'truth': truth['truth_id']})[:20]}",
                "reason_id": reason["reason_id"],
                "truth_id": truth["truth_id"],
                "machine_relation": relation,
                "effective_relation": effective_relation,
                "method": method,
                "review_status": "SEMANTIC_REVIEW_REQUIRED" if requires_review else "MACHINE_SUGGESTION",
                "relation_purpose": "REASON_TRUTH_COVERAGE",
                "source_subject": source_subject,
                "target_subject": str(target_brand.get("brand_name") or ""),
                "source_reason_span": str(
                    reason.get("effective_grounded_text") or reason.get("reason_span") or ""
                ),
                "cross_subject": False,
            })
        if not matched_truth:
            relationships.append({
                "relationship_id": f"trl-{_hash({'reason': reason['reason_id'], 'truth': 'no-match'})[:20]}",
                "reason_id": reason["reason_id"],
                "truth_id": None,
                "machine_relation": "UNRESOLVED",
                "effective_relation": "UNRESOLVED",
                "method": "NO_MATCHING_TARGET_BRAND_TRUTH",
                "review_status": "NEEDS_FACT_INPUT",
                "relation_purpose": "REASON_TRUTH_COVERAGE",
                "source_subject": source_subject,
                "target_subject": str(target_brand.get("brand_name") or ""),
                "cross_subject": False,
            })
    return {
        "truth_snapshot": truth_snapshot,
        "relationships": relationships,
        "external_capability_signals": external_capability_signals,
        "reason_capability_coverage": reason_capability_coverage,
    }


def current_truth_relation_eligibility(output: dict[str, Any]) -> dict[str, Any]:
    answer = output.get("answer_diagnosis") or {}
    truth_diagnosis = output.get("truth_diagnosis") or {}
    brand = (output.get("input") or {}).get("brand_snapshot") or {}
    target_subject_labels = {
        _normalize_truth_text(str(value))
        for value in [brand.get("brand_name"), *(brand.get("aliases") or [])]
        if str(value or "").strip()
    }
    reasons = {
        str(reason.get("reason_id")): reason
        for event in answer.get("events") or []
        for reason in event.get("reasons") or []
        if reason.get("reason_id")
    }
    effective_relationships: list[dict[str, Any]] = []
    blocked_relation_ids: list[str] = []
    for historical in truth_diagnosis.get("relationships") or []:
        row = copy.deepcopy(historical)
        reason = reasons.get(str(row.get("reason_id"))) or {}
        source_subject = str(reason.get("entity") or "").strip()
        source_subject_key = _normalize_truth_text(source_subject)
        is_cross_subject = bool(
            source_subject_key
            and target_subject_labels
            and source_subject_key not in target_subject_labels
        )
        row["historical_effective_relation"] = historical.get("effective_relation")
        row["current_effective_relation"] = (
            "UNRESOLVED" if is_cross_subject else historical.get("effective_relation")
        )
        row["effective_relation"] = row["current_effective_relation"]
        row["source_subject"] = source_subject
        row["target_subject"] = str(brand.get("brand_name") or "")
        row["cross_subject"] = is_cross_subject
        if is_cross_subject:
            row["method"] = "CROSS_SUBJECT_TARGET_CAPABILITY_FIT_REQUIRES_REVIEW"
            row["review_status"] = "SEMANTIC_REVIEW_REQUIRED"
            row["relation_purpose"] = "TARGET_CAPABILITY_FIT_SUGGESTION"
            blocked_relation_ids.append(str(row.get("relationship_id") or ""))
        else:
            row.setdefault("relation_purpose", "REASON_TRUTH_COVERAGE")
        effective_relationships.append(row)
    return {
        "contract_version": TRUTH_MATCH_VERSION,
        "effective_relationships": effective_relationships,
        "cross_subject_relation_ids": sorted(value for value in blocked_relation_ids if value),
        "cross_subject_relation_count": len(blocked_relation_ids),
    }


def _source_was_not_fetched(row: SinglePromptSourceSnapshot) -> bool:
    if row.fetch_source == "FETCH_DISABLED":
        return True
    if row.fetch_source != "V2_FAILURE_SNAPSHOT_REUSE":
        return False
    reason = str(row.failure_reason or "")
    return "禁止外部正文抓取" in reason or "未授权" in reason


def _source_summary(snapshots: list[SinglePromptSourceSnapshot]) -> dict:
    not_fetched = sum(_source_was_not_fetched(row) for row in snapshots)
    content_blocked = sum(row.fetch_status == "CONTENT_BLOCKED" for row in snapshots)
    fetch_failed = sum(
        row.fetch_status not in {"SUCCESS", "PARTIAL", "CONTENT_BLOCKED"}
        and not _source_was_not_fetched(row)
        for row in snapshots
    )
    return {
        "reference_records": sum(row.occurrence_count for row in snapshots),
        "unique_sources": len(snapshots),
        "content_ready": sum(row.fetch_status in {"SUCCESS", "PARTIAL"} for row in snapshots),
        "not_fetched": not_fetched,
        "fetch_failed": fetch_failed,
        "content_blocked": content_blocked,
        "passage_count": sum(len(loads(row.passages_json, [])) for row in snapshots),
    }


def current_evidence_eligibility(
    snapshots: list[SinglePromptSourceSnapshot],
    *,
    historical_content_ready: int,
    historical_output: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    blocked: list[dict[str, Any]] = []
    eligible_ids: list[str] = []
    for snapshot in snapshots:
        current_block_reason = _source_content_block_reason(snapshot.title, snapshot.clean_text)
        if snapshot.fetch_status == "CONTENT_BLOCKED" or current_block_reason:
            blocked.append({
                "snapshot_id": snapshot.snapshot_id,
                "source_key": snapshot.source_key,
                "title": snapshot.title,
                "reason": current_block_reason or snapshot.failure_reason or "CONTENT_BLOCKED",
            })
            continue
        if snapshot.fetch_status in {"SUCCESS", "PARTIAL"}:
            eligible_ids.append(snapshot.snapshot_id)

    advisories: list[dict[str, Any]] = []
    if blocked:
        advisories.append({
            "code": "CURRENT_CONTENT_QUALITY_BLOCKED",
            "count": len(blocked),
            "historical_content_ready": historical_content_ready,
            "maximum_currently_eligible": len(eligible_ids),
            "message": "历史技术成功数保持不变；当前识别出的验证/拦截页不得作为有效正文证据。",
        })
    eligible_snapshot_ids = set(eligible_ids)
    blocked_snapshot_ids = {row["snapshot_id"] for row in blocked}
    historical_relations = (
        ((historical_output or {}).get("evidence_diagnosis") or {}).get("source_relations") or []
    )
    effective_relation_ids = sorted(
        str(row.get("relation_id"))
        for row in historical_relations
        if row.get("source_snapshot_id") in eligible_snapshot_ids
        and row.get("effective_relation") is not None
    )
    blocked_relation_ids = sorted(
        str(row.get("relation_id"))
        for row in historical_relations
        if row.get("source_snapshot_id") in blocked_snapshot_ids
    )
    return advisories, {
        "contract_version": SOURCE_CONTENT_GATE_VERSION,
        "historical_content_ready": historical_content_ready,
        "content_blocked_current": len(blocked),
        "maximum_currently_eligible": len(eligible_ids),
        "all_remaining_sources_quality_verified": False,
        "eligible_snapshot_ids": sorted(eligible_ids),
        "blocked_snapshots": blocked,
        "effective_evidence_relation_ids": effective_relation_ids,
        "blocked_historical_relation_ids": blocked_relation_ids,
        "effective_relation_count": len(effective_relation_ids),
    }


def _snapshot_reads(snapshots: list[SinglePromptSourceSnapshot]) -> list[dict]:
    return [{
        "snapshot_id": row.snapshot_id,
        "source_key": row.source_key,
        "canonical_url": row.canonical_url,
        "reference_observations": loads(row.reference_observations_json, []),
        "occurrence_count": row.occurrence_count,
        "fetch_status": row.fetch_status,
        "failure_reason": row.failure_reason,
        "fetched_at": _iso(row.fetched_at),
        "title": row.title,
        "content_hash": row.content_hash,
        "passages_hash": row.passages_hash,
        "passage_count": len(loads(row.passages_json, [])),
        "parser_version": row.parser_version,
        "fetch_source": row.fetch_source,
        "reused_from_snapshot_id": row.reused_from_snapshot_id,
    } for row in snapshots]


def _limitations(raw_output: dict, answer: dict, snapshots: list[SinglePromptSourceSnapshot], evidence: dict, truths: dict) -> list[dict]:
    limitations: list[dict] = []
    runs = raw_output.get("runs") or []
    if runs and all((run.get("environment") or {}).get("sampling_mode") in {None, "", "UNKNOWN"} for run in runs):
        limitations.append({"code": "INDEPENDENT_SESSION_PROOF_UNAVAILABLE", "impact": "不能声称独立采样或推荐稳定性已验证"})
    reference_count = sum(len(run.get("references") or []) for run in runs)
    retrieval_count = sum(len(run.get("retrieval_candidates") or []) for run in runs)
    if reference_count and retrieval_count == 0:
        limitations.append({"code": "RETRIEVAL_OBSERVATION_UNAVAILABLE", "impact": "不能把 Retrieval 记为 0 或计算 Retrieval→Citation 转化"})
    if answer["failures"]:
        limitations.append({"code": "ANSWER_SEMANTIC_PARTIAL_FAILURE", "count": len(answer["failures"])})
    answer_review_required = sum(
        reason.get("fact_consumption_eligible") is not True
        for event in answer["events"]
        for reason in event["reasons"]
    )
    if answer_review_required:
        limitations.append({
            "code": "ANSWER_SEMANTIC_REVIEW_REQUIRED",
            "count": answer_review_required,
            "impact": "相关原文保留，但不会进入 Evidence Alignment 或 Product Truth 覆盖判断",
        })
    criterion_review_required = sum(
        row.get("normalization_eligible") is not True
        for row in answer.get("market_criteria") or []
    )
    if criterion_review_required:
        limitations.append({
            "code": "MARKET_CRITERIA_NORMALIZATION_REVIEW_REQUIRED",
            "count": criterion_review_required,
            "impact": "市场选择标准保留原文，但其规范化投影不能作为召回辅助或品牌事实消费",
        })
    external_not_authorized = sum(
        job.get("result_source") == "CACHE_MISS_EXTERNAL_NOT_AUTHORIZED"
        for job in evidence["source_claim_jobs"]
    )
    if external_not_authorized:
        limitations.append({
            "code": "EVIDENCE_EXTERNAL_PROCESSING_NOT_AUTHORIZED",
            "count": external_not_authorized,
            "impact": "候选正文未发送给外部模型，相关 SourceClaim/Alignment 保持未评估",
        })
    rejected_claim_jobs = sum(
        job.get("status") in {
            "FAILED_SCHEMA", "FAILED_PARSE", "FAILED_VALIDATION", "CACHE_REJECTED_BY_V2_VALIDATION",
        }
        for job in evidence["source_claim_jobs"]
    )
    if rejected_claim_jobs:
        limitations.append({"code": "SOURCE_CLAIM_ADMISSION_FAILED", "count": rejected_claim_jobs})
    claim_review_required = sum(
        claim.get("fact_consumption_eligible") is not True
        for claim in evidence.get("source_claims") or []
    )
    if claim_review_required:
        limitations.append({
            "code": "SOURCE_CLAIM_SEMANTIC_REVIEW_REQUIRED",
            "count": claim_review_required,
            "impact": "相关原文片段未进入 Alignment 正向结论",
        })
    not_fetched_sources = sum(_source_was_not_fetched(row) for row in snapshots)
    if not_fetched_sources:
        limitations.append({
            "code": "SOURCE_CONTENT_NOT_FETCHED",
            "count": not_fetched_sources,
            "impact": "本次未获正文抓取授权且没有可复用正文；这不是抓取失败，也不能据此形成证据结论",
        })
    failed_sources = sum(
        row.fetch_status not in {"SUCCESS", "PARTIAL", "CONTENT_BLOCKED"}
        and not _source_was_not_fetched(row)
        for row in snapshots
    )
    if failed_sources:
        limitations.append({"code": "SOURCE_CONTENT_PARTIAL_FAILURE", "count": failed_sources})
    blocked_sources = sum(row.fetch_status == "CONTENT_BLOCKED" for row in snapshots)
    if blocked_sources:
        limitations.append({"code": "SOURCE_CONTENT_QUALITY_BLOCKED", "count": blocked_sources})
    not_evaluated = sum(row["alignment_evaluation"] != "EVALUATED" for row in evidence["source_relations"])
    if not_evaluated:
        limitations.append({"code": "EVIDENCE_RELATIONS_NOT_EVALUATED", "count": not_evaluated})
    unproven = sum(row["anchor_binding"] == "UNPROVEN" for row in evidence["source_relations"])
    if unproven:
        limitations.append({"code": "REFERENCE_ANCHOR_UNPROVEN", "count": unproven})
    if not truths["truth_snapshot"]:
        limitations.append({"code": "TARGET_BRAND_TRUTH_MISSING", "impact": "不能推断目标品牌具备或不具备这些能力"})
    return limitations


def _reviewable_set(output: dict) -> dict:
    return {
        "event_ids": sorted(event["event_id"] for event in output["answer_diagnosis"]["events"]),
        "market_criterion_ids": sorted(
            criterion["criterion_id"]
            for criterion in output["answer_diagnosis"].get("market_criteria") or []
        ),
        "reason_ids": sorted(
            reason["reason_id"]
            for event in output["answer_diagnosis"]["events"]
            for reason in event["reasons"]
        ),
        "evidence_relation_ids": sorted(row["relation_id"] for row in output["evidence_diagnosis"]["source_relations"]),
        "truth_relationship_ids": sorted(row["relationship_id"] for row in output["truth_diagnosis"]["relationships"]),
    }


def reproject_target_brand_truths(
    db: Session,
    *,
    analysis_id: str,
    diagnosis_id: str,
    result_version: str,
    project_id: int,
    prompt_id: int,
    source_result_hash: str,
    source_review_id: str,
    expected_project_truth_set_hash: str,
    idempotency_key: str,
) -> tuple[SinglePromptDiagnosisExecution, bool]:
    """Create a new immutable diagnosis identity while recomputing only Truth relations."""
    source_execution = db.query(SinglePromptDiagnosisExecution).filter_by(
        diagnosis_id=diagnosis_id,
        analysis_id=analysis_id,
    ).one_or_none()
    if not source_execution:
        raise HTTPException(status_code=404, detail="诊断执行不存在")
    if source_execution.project_id != project_id or source_execution.prompt_id != prompt_id:
        raise HTTPException(status_code=409, detail="诊断身份与当前 Project/Prompt 不匹配")
    if source_execution.active_result_version != result_version:
        raise HTTPException(status_code=409, detail="诊断结果版本已变化，请重新加载")
    source_result = db.query(SinglePromptDiagnosisResult).filter_by(
        diagnosis_id=diagnosis_id,
        result_version=result_version,
    ).one_or_none()
    if not source_result or source_result.output_hash != source_result_hash:
        raise HTTPException(status_code=409, detail="诊断结果身份或 hash 不匹配")
    source_review = db.query(SinglePromptDiagnosisReview).filter_by(
        review_id=source_review_id,
        diagnosis_id=diagnosis_id,
        result_version=result_version,
    ).one_or_none()
    if not source_review or source_review.result_hash != source_result_hash:
        raise HTTPException(status_code=409, detail="事实关系重投影需要当前结果的有效审核")
    _require_independent_answer_boundary(db, source_execution, "REPROJECT_TARGET_BRAND_TRUTHS")

    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    truth_rows = (
        db.query(TargetBrandCapabilityTruth)
        .filter(TargetBrandCapabilityTruth.project_id == project_id)
        .order_by(TargetBrandCapabilityTruth.id)
        .all()
    )
    truth_snapshot = [_snapshot_truth(row) for row in truth_rows]
    truth_set_hash = _hash(truth_snapshot)
    if truth_set_hash != expected_project_truth_set_hash:
        raise HTTPException(status_code=409, detail="项目事实集合已变化，请重新加载后再提交")
    if truth_set_hash == source_execution.truth_set_hash:
        raise HTTPException(status_code=409, detail="项目事实集合未变化，无需刷新事实关系")

    source_output = loads(source_result.output_json, {})
    _require_consumable_answer_semantic(source_output, "REPROJECT_TARGET_BRAND_TRUTHS")
    brand_snapshot = loads(source_execution.brand_snapshot_json, {})
    source_config = loads(source_execution.contract_config_json, {})
    contract_config = {
        **source_config,
        "diagnosis_mode": "TRUTH_REPROJECTION",
        "truth_match_version": TRUTH_MATCH_VERSION,
        "source_diagnosis_id": diagnosis_id,
        "source_result_version": result_version,
        "source_result_hash": source_result_hash,
        "source_review_id": source_review_id,
    }
    identity = {
        "analysis_id": analysis_id,
        "context_id": source_execution.context_id,
        "raw_output_hash": source_execution.raw_output_hash,
        "brand_snapshot_hash": source_execution.brand_snapshot_hash,
        "truth_set_hash": truth_set_hash,
        "contract_config_hash": _hash(contract_config),
    }
    fingerprint = _hash(identity)
    existing = db.query(SinglePromptDiagnosisExecution).filter_by(
        analysis_id=analysis_id,
        idempotency_key=idempotency_key,
    ).one_or_none()
    if existing:
        if existing.input_fingerprint != fingerprint:
            raise HTTPException(status_code=409, detail="幂等键已用于不同的事实关系输入")
        return existing, False

    execution = SinglePromptDiagnosisExecution(
        diagnosis_id=str(uuid4()),
        analysis_id=analysis_id,
        context_id=source_execution.context_id,
        project_id=project_id,
        prompt_id=prompt_id,
        idempotency_key=idempotency_key,
        input_fingerprint=fingerprint,
        raw_output_hash=source_execution.raw_output_hash,
        brand_snapshot_json=source_execution.brand_snapshot_json,
        brand_snapshot_hash=source_execution.brand_snapshot_hash,
        truth_snapshot_json=_canonical_json(truth_snapshot),
        truth_set_hash=truth_set_hash,
        contract_config_json=_canonical_json(contract_config),
        contract_config_hash=identity["contract_config_hash"],
        status="READY_FOR_REVIEW",
        progress_json=_canonical_json({"stage": "TRUTH_REPROJECTED", "completed": 1, "total": 1}),
        attempt_count=1,
        external_llm_calls=0,
        llm_cache_hits=0,
        external_token_usage=0,
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
    )
    db.add(execution)
    db.flush()

    output = copy.deepcopy(source_output)
    output.setdefault("input", {})["truth_set_hash"] = truth_set_hash
    output["input"]["contract_config"] = contract_config
    output["input"]["contract_config_hash"] = identity["contract_config_hash"]
    output["truth_diagnosis"] = _diagnose_truths(
        output.get("answer_diagnosis") or {"events": []},
        truth_snapshot,
        target_brand=brand_snapshot,
    )
    prior_review_payload = {
        "review_id": source_review.review_id,
        "result_version": source_review.result_version,
        "result_hash": source_review.result_hash,
        "reviewable_set_hash": source_review.reviewable_set_hash,
        "decision": source_review.decision,
        "decisions": loads(source_review.decisions_json, []),
        "reviewer": source_review.reviewer,
        "note": source_review.note,
        "created_at": _iso(source_review.created_at),
    }
    output["truth_reprojection"] = {
        "contract_version": TRUTH_MATCH_VERSION,
        "source_diagnosis_id": diagnosis_id,
        "source_result_version": result_version,
        "source_result_hash": source_result_hash,
        "prior_review": prior_review_payload,
        "answer_semantic_recomputed": False,
        "evidence_recomputed": False,
        "external_llm_calls": 0,
    }
    limitations = [
        row for row in (output.get("limitations") or [])
        if row.get("code") != "TARGET_BRAND_TRUTH_MISSING"
    ]
    unresolved_truths = sum(
        row.get("effective_relation") == "UNRESOLVED"
        for row in output["truth_diagnosis"]["relationships"]
    )
    if unresolved_truths:
        limitations.append({
            "code": "TARGET_BRAND_TRUTH_RELATION_REVIEW_REQUIRED",
            "count": unresolved_truths,
            "impact": "不阻断 Answer/Evidence；依赖这些事实的策略声明仍需核对。",
        })
    output["limitations"] = limitations
    output.setdefault("stats", {})["truth_facts"] = len(truth_snapshot)
    output["stats"]["truth_relationships"] = len(output["truth_diagnosis"]["relationships"])
    output["usage"] = {"external_llm_calls": 0, "llm_cache_hits": 0, "external_token_usage": 0}
    output["answer_semantic_eligibility"] = answer_semantic_eligibility(output)

    output_hash = _hash(output)
    result = SinglePromptDiagnosisResult(
        result_version=f"diag-v1:{output_hash[:16]}",
        diagnosis_id=execution.diagnosis_id,
        version_number=1,
        parent_result_version=None,
        output_json=_canonical_json(output),
        output_hash=output_hash,
        reviewable_set_hash=_hash(_reviewable_set(output)),
        limitations_json=_canonical_json(limitations),
        stats_json=_canonical_json(output["stats"]),
    )
    db.add(result)
    db.flush()
    execution.active_result_version = result.result_version
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.query(SinglePromptDiagnosisExecution).filter_by(
            analysis_id=analysis_id,
            idempotency_key=idempotency_key,
        ).one_or_none()
        if concurrent and concurrent.input_fingerprint == fingerprint:
            return concurrent, False
        raise
    db.refresh(execution)
    return execution, True


def _publish_result(db: Session, execution: SinglePromptDiagnosisExecution, token: str, output: dict) -> SinglePromptDiagnosisResult:
    db.refresh(execution)
    if execution.status != "RUNNING" or execution.active_attempt_token != token:
        raise RuntimeError("诊断执行租约已失效")
    existing = (
        db.query(SinglePromptDiagnosisResult)
        .filter(SinglePromptDiagnosisResult.diagnosis_id == execution.diagnosis_id)
        .order_by(SinglePromptDiagnosisResult.version_number)
        .first()
    )
    if existing:
        return existing
    output_hash = _hash(output)
    reviewable_set_hash = _hash(_reviewable_set(output))
    result = SinglePromptDiagnosisResult(
        result_version=f"diag-v1:{output_hash[:16]}",
        diagnosis_id=execution.diagnosis_id,
        version_number=1,
        parent_result_version=None,
        output_json=_canonical_json(output),
        output_hash=output_hash,
        reviewable_set_hash=reviewable_set_hash,
        limitations_json=_canonical_json(output["limitations"]),
        stats_json=_canonical_json(output["stats"]),
    )
    db.add(result)
    db.flush()
    execution.active_result_version = result.result_version
    execution.status = "READY_FOR_REVIEW"
    execution.blocker_code = ""
    execution.blocker_detail = ""
    execution.active_attempt_token = ""
    execution.external_llm_calls = int(output["usage"]["external_llm_calls"])
    execution.llm_cache_hits = int(output["usage"]["llm_cache_hits"])
    execution.external_token_usage = int(output["usage"]["external_token_usage"])
    execution.finished_at = datetime.utcnow()
    execution.progress_json = _canonical_json({"stage": "RESULT_PUBLISHED", "completed": 1, "total": 1})
    db.commit()
    db.refresh(result)
    return result


def compute_answer_diagnosis(
    db: Session,
    execution: SinglePromptDiagnosisExecution,
    token: str,
    *,
    answer_judge: Any | None = None,
) -> SinglePromptDiagnosisResult:
    context = db.query(SinglePromptAnalysisContext).filter_by(context_id=execution.context_id).one_or_none()
    if not context or context.raw_output_hash != execution.raw_output_hash:
        raise RuntimeError("冻结的 AnalysisContext 与 Answer 诊断输入不一致")
    raw_output = loads(context.raw_output_json, {})
    brand = loads(execution.brand_snapshot_json, {})
    truths = loads(execution.truth_snapshot_json, [])
    config = loads(execution.contract_config_json, {})
    if config.get("diagnosis_mode") != "ANSWER_ONLY":
        raise RuntimeError("当前执行不是 Answer-only 诊断")
    citation = db.query(SinglePromptCitationManifest).filter_by(
        manifest_id=str(config.get("citation_manifest_id") or "")
    ).one_or_none()
    if not citation or (
        citation.analysis_id != execution.analysis_id
        or citation.context_id != execution.context_id
        or citation.payload_hash != config.get("citation_manifest_hash")
        or citation.raw_output_hash != execution.raw_output_hash
    ):
        raise RuntimeError("Citation Manifest 与 Answer 诊断输入不一致")

    usage = {"external_llm_calls": 0, "llm_cache_hits": 0, "external_token_usage": 0}
    if answer_judge is None:
        answer_judge = V2AnswerSemanticJudge(DeepSeekClient(
            thinking_mode=V2_LLM_THINKING_MODE,
            max_attempts=int(config.get("llm_max_attempts") or 1),
            cache_only=config.get("answer_llm_policy") != "ALLOW_EXTERNAL",
        ))
    _set_progress(db, execution, "ANSWER_SEMANTIC", 0, 1, "识别推荐对象、理由和市场标准")
    answer = _diagnose_answers(
        db,
        raw_output=raw_output,
        prompt_text=str(raw_output.get("prompt_text") or ""),
        brand_name=str(brand.get("brand_name") or ""),
        usage=usage,
        judge=answer_judge,
        thinking_mode=str(config.get("llm_thinking_mode") or "") or None,
        answer_llm_policy=str(config.get("answer_llm_policy") or "ALLOW_EXTERNAL"),
    )
    _attach_prior_review_provenance(db, execution, answer)
    client = getattr(answer_judge, "client", None)
    if isinstance(client, DeepSeekClient):
        usage["external_llm_calls"] = client.external_call_count
        usage["external_token_usage"] = client.external_token_count

    truth_diagnosis = _diagnose_truths(answer, truths, target_brand=brand)
    evidence = {
        "status": "NOT_STARTED",
        "source_claims": [],
        "source_claim_jobs": [],
        "alignment_jobs": [],
        "source_relations": [],
        "failures": [],
    }
    limitations = _limitations(raw_output, answer, [], evidence, truth_diagnosis)
    limitations.append({
        "code": "EVIDENCE_AWAITS_SOURCE_COMPLETION_AND_EXACT_REVIEW",
        "impact": "Answer 结果不包含 SourceClaim/Alignment；Evidence 必须使用完成清单和本结果的精确审核继续。",
    })
    valid_runs = sum(
        run.get("status") in {"success", "partial_success"} and bool(str(run.get("answer_text") or "").strip())
        for run in raw_output.get("runs") or []
    )
    stats = {
        "valid_runs": valid_runs,
        "recommendation_events": len(answer["events"]),
        "reasons": sum(len(event["reasons"]) for event in answer["events"]),
        "market_criteria": len(answer.get("market_criteria") or []),
        "reference_records": citation.occurrence_count,
        "unique_sources": citation.source_count,
        "content_ready": 0,
        "not_fetched": citation.source_count,
        "fetch_failed": 0,
        "content_blocked": 0,
        "passage_count": 0,
        "candidate_recalled": 0,
        "alignment_evaluated": 0,
        "alignment_not_evaluated": 0,
        "truth_facts": len(truths),
        "truth_relationships": len(truth_diagnosis["relationships"]),
    }
    output = {
        "contract_version": DIAGNOSIS_CONTRACT_VERSION,
        "result_scope": "ANSWER_ONLY",
        "input": {
            "analysis_id": execution.analysis_id,
            "context_id": execution.context_id,
            "raw_output_hash": execution.raw_output_hash,
            "citation_manifest_id": citation.manifest_id,
            "citation_manifest_hash": citation.payload_hash,
            "brand_snapshot": brand,
            "brand_snapshot_hash": execution.brand_snapshot_hash,
            "truth_set_hash": execution.truth_set_hash,
            "contract_config": config,
            "contract_config_hash": execution.contract_config_hash,
        },
        "answer_diagnosis": answer,
        "source_diagnosis": {
            "status": "SEPARATE_SOURCE_PREPARATION",
            "summary": {
                "reference_records": citation.occurrence_count,
                "unique_sources": citation.source_count,
                "content_ready": 0,
                "not_fetched": citation.source_count,
                "fetch_failed": 0,
                "content_blocked": 0,
                "passage_count": 0,
            },
            "snapshots": [],
        },
        "evidence_diagnosis": evidence,
        "truth_diagnosis": truth_diagnosis,
        "limitations": limitations,
        "stats": stats,
        "usage": usage,
    }
    output["answer_semantic_eligibility"] = answer_semantic_eligibility(output)
    return _publish_result(db, execution, token, output)


def compute_diagnosis(
    db: Session,
    execution: SinglePromptDiagnosisExecution,
    token: str,
    *,
    answer_judge: Any | None = None,
    source_claim_judge: Any | None = None,
    alignment_judge: Any | None = None,
    fetcher: Callable[[list[str]], list[dict]] | None = None,
) -> SinglePromptDiagnosisResult:
    context = db.query(SinglePromptAnalysisContext).filter(
        SinglePromptAnalysisContext.context_id == execution.context_id
    ).one_or_none()
    if not context or context.raw_output_hash != execution.raw_output_hash:
        raise RuntimeError("冻结的 AnalysisContext 与诊断输入不一致")
    raw_output = loads(context.raw_output_json, {})
    brand = loads(execution.brand_snapshot_json, {})
    truths = loads(execution.truth_snapshot_json, [])
    config = loads(execution.contract_config_json, {})
    usage = {"external_llm_calls": 0, "llm_cache_hits": 0, "external_token_usage": 0}
    if answer_judge is None:
        answer_judge = V2AnswerSemanticJudge(DeepSeekClient(
            thinking_mode=V2_LLM_THINKING_MODE,
            max_attempts=int(config.get("llm_max_attempts") or 1),
        ))
    if source_claim_judge is None:
        source_claim_judge = V2SourceClaimJudge(DeepSeekClient(
            thinking_mode=V2_LLM_THINKING_MODE,
            max_attempts=int(config.get("llm_max_attempts") or 1),
        ))
    if alignment_judge is None:
        alignment_judge = V2AlignmentJudge(DeepSeekClient(
            thinking_mode=V2_LLM_THINKING_MODE,
            max_attempts=int(config.get("llm_max_attempts") or 1),
        ))

    _set_progress(db, execution, "ANSWER_SEMANTIC", 0, 1, "识别推荐对象与理由")
    answer = _diagnose_answers(
        db,
        raw_output=raw_output,
        prompt_text=str(raw_output.get("prompt_text") or ""),
        brand_name=str(brand.get("brand_name") or ""),
        usage=usage,
        judge=answer_judge,
        thinking_mode=str(config.get("llm_thinking_mode") or "") or None,
        answer_llm_policy=str(config.get("answer_llm_policy") or "ALLOW_EXTERNAL"),
    )
    _attach_prior_review_provenance(db, execution, answer)

    grouped_references = _group_references(raw_output)
    _set_progress(db, execution, "SOURCE_SNAPSHOT", 0, len(grouped_references), "冻结引用正文版本")
    snapshots = _load_or_fetch_snapshots(
        db,
        execution,
        grouped_references,
        fetcher or fetch_page_playwright,
        source_snapshot_policy=str(config.get("source_snapshot_policy") or "REUSE_OR_FETCH"),
    )

    _set_progress(db, execution, "EVIDENCE_DIAGNOSIS", 0, 1, "候选召回、SourceClaim 与证据关系判断")
    evidence = _diagnose_evidence(
        db,
        answer_diagnosis=answer,
        snapshots=snapshots,
        usage=usage,
        source_claim_judge=source_claim_judge,
        alignment_judge=alignment_judge,
        config=config,
    )
    truth_diagnosis = _diagnose_truths(answer, truths, target_brand=brand)
    limitations = _limitations(raw_output, answer, snapshots, evidence, truth_diagnosis)
    source_summary = _source_summary(snapshots)
    real_clients = {
        id(client): client
        for client in (
            getattr(answer_judge, "client", None),
            getattr(source_claim_judge, "client", None),
            getattr(alignment_judge, "client", None),
        )
        if isinstance(client, DeepSeekClient)
    }
    if real_clients:
        usage["external_llm_calls"] = sum(client.external_call_count for client in real_clients.values())
        usage["external_token_usage"] = sum(client.external_token_count for client in real_clients.values())
    stats = {
        "valid_runs": sum(
            run.get("status") in {"success", "partial_success"} and bool(str(run.get("answer_text") or "").strip())
            for run in raw_output.get("runs") or []
        ),
        "recommendation_events": len(answer["events"]),
        "reasons": sum(len(event["reasons"]) for event in answer["events"]),
        "market_criteria": len(answer.get("market_criteria") or []),
        **source_summary,
        "candidate_recalled": sum(row["candidate_recall"] == "RECALLED" for row in evidence["source_relations"]),
        "alignment_evaluated": sum(row["alignment_evaluation"] == "EVALUATED" for row in evidence["source_relations"]),
        "alignment_not_evaluated": sum(row["alignment_evaluation"] != "EVALUATED" for row in evidence["source_relations"]),
        "truth_facts": len(truths),
        "truth_relationships": len(truth_diagnosis["relationships"]),
    }
    output = {
        "contract_version": DIAGNOSIS_CONTRACT_VERSION,
        "input": {
            "analysis_id": execution.analysis_id,
            "context_id": execution.context_id,
            "raw_output_hash": execution.raw_output_hash,
            "brand_snapshot": brand,
            "brand_snapshot_hash": execution.brand_snapshot_hash,
            "truth_set_hash": execution.truth_set_hash,
            "contract_config": config,
            "contract_config_hash": execution.contract_config_hash,
        },
        "answer_diagnosis": answer,
        "source_diagnosis": {"summary": source_summary, "snapshots": _snapshot_reads(snapshots)},
        "evidence_diagnosis": evidence,
        "truth_diagnosis": truth_diagnosis,
        "limitations": limitations,
        "stats": stats,
        "usage": usage,
    }
    output["answer_semantic_eligibility"] = answer_semantic_eligibility(output)
    return _publish_result(db, execution, token, output)


def _reviewed_answer_for_evidence(output: dict[str, Any], review: SinglePromptDiagnosisReview) -> dict[str, Any]:
    reviewed = copy.deepcopy(output.get("answer_diagnosis") or {})
    decisions = {
        str(row.get("event_id")): str(row.get("decision"))
        for row in loads(review.decisions_json, [])
        if row.get("scope") == "ANSWER_SEMANTIC_EVENT" and row.get("event_id")
    }
    eligible_events: list[dict[str, Any]] = []
    for event in reviewed.get("events") or []:
        if event.get("fact_consumption_eligible") is True:
            eligible_events.append(event)
            continue
        if (
            event.get("semantic_validation_status") == "SEMANTIC_REVIEW_REQUIRED"
            and decisions.get(str(event.get("event_id"))) == "CONFIRM_INCLUDE_AS_OPTION"
        ):
            event["fact_consumption_eligible"] = True
            event["review_status"] = "HUMAN_CONFIRMED_INCLUDE_AS_OPTION"
            event["review_id"] = review.review_id
            eligible_events.append(event)
    reviewed["events"] = eligible_events
    reviewed["evidence_event_scope"] = {
        "source_result_version": review.result_version,
        "source_review_id": review.review_id,
        "eligible_event_ids": sorted(str(row.get("event_id")) for row in eligible_events),
        "excluded_event_ids": sorted(
            str(row.get("event_id"))
            for row in (output.get("answer_diagnosis") or {}).get("events") or []
            if str(row.get("event_id")) not in {str(item.get("event_id")) for item in eligible_events}
        ),
    }
    return reviewed


def _evidence_continuation_inputs(
    db: Session,
    *,
    analysis_id: str,
    diagnosis_id: str,
    project_id: int,
    prompt_id: int,
    answer_result_version: str,
    answer_result_hash: str,
    answer_review_id: str,
    citation_manifest_id: str,
    citation_manifest_hash: str,
    completion_manifest_id: str,
    completion_manifest_hash: str,
    evidence_llm_policy: str,
):
    if evidence_llm_policy not in {"ALLOW_EXTERNAL", "CACHE_ONLY"}:
        raise HTTPException(status_code=422, detail="Evidence LLM 授权策略非法")
    execution = db.query(SinglePromptDiagnosisExecution).filter_by(
        diagnosis_id=diagnosis_id,
        analysis_id=analysis_id,
    ).one_or_none()
    if not execution:
        raise HTTPException(status_code=404, detail="Answer 诊断执行不存在")
    if execution.project_id != project_id or execution.prompt_id != prompt_id:
        raise HTTPException(status_code=409, detail={"code": "EVIDENCE_PROJECT_PROMPT_MISMATCH"})
    if execution.context_id == "":
        raise HTTPException(status_code=409, detail={"code": "EVIDENCE_CONTEXT_MISSING"})
    _require_independent_answer_boundary(db, execution, "EVIDENCE_CONTINUATION")
    answer_result = db.query(SinglePromptDiagnosisResult).filter_by(
        diagnosis_id=diagnosis_id,
        result_version=answer_result_version,
    ).one_or_none()
    if not answer_result or answer_result.output_hash != answer_result_hash:
        raise HTTPException(status_code=409, detail={"code": "ANSWER_RESULT_INPUT_MISMATCH"})
    answer_output = loads(answer_result.output_json, {})
    if answer_output.get("result_scope") != "ANSWER_ONLY":
        raise HTTPException(status_code=409, detail={"code": "ANSWER_ONLY_RESULT_REQUIRED"})
    if (
        (answer_output.get("input") or {}).get("analysis_id") != analysis_id
        or (answer_output.get("input") or {}).get("context_id") != execution.context_id
        or (answer_output.get("input") or {}).get("citation_manifest_id") != citation_manifest_id
        or (answer_output.get("input") or {}).get("citation_manifest_hash") != citation_manifest_hash
    ):
        raise HTTPException(status_code=409, detail={"code": "ANSWER_RESULT_CONTEXT_MISMATCH"})
    _require_consumable_answer_semantic(answer_output, "EVIDENCE_CONTINUATION")
    review = db.query(SinglePromptDiagnosisReview).filter_by(
        review_id=answer_review_id,
        diagnosis_id=diagnosis_id,
        result_version=answer_result_version,
    ).one_or_none()
    if not review or (
        review.result_hash != answer_result_hash
        or review.reviewable_set_hash != answer_result.reviewable_set_hash
        or review.decision != "REVIEW_COMPLETED"
    ):
        raise HTTPException(status_code=409, detail={"code": "EXACT_ANSWER_REVIEW_REQUIRED"})
    completion, snapshots, waiver_limitations = validate_completion_for_evidence(
        db,
        analysis_id=analysis_id,
        context_id=execution.context_id,
        citation_manifest_id=citation_manifest_id,
        citation_manifest_hash=citation_manifest_hash,
        completion_manifest_id=completion_manifest_id,
        completion_manifest_hash=completion_manifest_hash,
    )
    reviewed_answer = _reviewed_answer_for_evidence(answer_output, review)
    candidate_plan, _ = _build_candidate_plan_for_evidence(reviewed_answer, snapshots)
    binding = {
        "analysis_id": analysis_id,
        "context_id": execution.context_id,
        "citation_manifest_id": citation_manifest_id,
        "citation_manifest_hash": citation_manifest_hash,
        "completion_manifest_id": completion_manifest_id,
        "completion_manifest_hash": completion_manifest_hash,
        "answer_result_version": answer_result_version,
        "answer_result_hash": answer_result_hash,
        "answer_review_id": answer_review_id,
        "answer_reviewable_set_hash": review.reviewable_set_hash,
        "evidence_plan_id": candidate_plan["plan_id"],
        "evidence_plan_hash": candidate_plan["plan_hash"],
        "evidence_plan_policy_version": candidate_plan["policy_version"],
        "evidence_llm_policy": evidence_llm_policy,
    }
    binding_hash = _hash(binding)
    for row in db.query(SinglePromptDiagnosisResult).filter_by(diagnosis_id=diagnosis_id).all():
        prior = loads(row.output_json, {})
        if prior.get("result_scope") == "ANSWER_AND_EVIDENCE" and (prior.get("input") or {}).get("evidence_binding_hash") == binding_hash:
            return {
                "execution": execution,
                "answer_result": answer_result,
                "answer_output": answer_output,
                "review": review,
                "completion": completion,
                "snapshots": snapshots,
                "waiver_limitations": waiver_limitations,
                "binding": binding,
                "binding_hash": binding_hash,
                "existing_result": row,
            }
    return {
        "execution": execution,
        "answer_result": answer_result,
        "answer_output": answer_output,
        "review": review,
        "completion": completion,
        "snapshots": snapshots,
        "waiver_limitations": waiver_limitations,
        "binding": binding,
        "binding_hash": binding_hash,
        "existing_result": None,
    }


def queue_evidence_continuation(
    db: Session,
    **kwargs,
) -> tuple[SinglePromptDiagnosisResult | None, bool]:
    gate = _evidence_continuation_inputs(db, **kwargs)
    if gate["existing_result"] is not None:
        return gate["existing_result"], False
    execution = gate["execution"]
    progress = loads(execution.progress_json, {})
    if execution.status in {"EVIDENCE_QUEUED", "EVIDENCE_RUNNING"}:
        if progress.get("input_binding_hash") == gate["binding_hash"]:
            return None, False
        raise HTTPException(status_code=409, detail={"code": "OTHER_EVIDENCE_INPUT_ALREADY_ACTIVE"})
    execution.status = "EVIDENCE_QUEUED"
    execution.blocker_code = ""
    execution.blocker_detail = ""
    execution.finished_at = None
    execution.progress_json = _canonical_json({
        "stage": "EVIDENCE_QUEUED",
        "completed": 0,
        "total": 1,
        "detail": "双输入 Gate 已通过，等待 release worker 消费精确版本",
        "input_binding_hash": gate["binding_hash"],
        "request": gate["binding"],
    })
    db.commit()
    return None, True


def continue_evidence_diagnosis(
    db: Session,
    *,
    analysis_id: str,
    diagnosis_id: str,
    project_id: int,
    prompt_id: int,
    answer_result_version: str,
    answer_result_hash: str,
    answer_review_id: str,
    citation_manifest_id: str,
    citation_manifest_hash: str,
    completion_manifest_id: str,
    completion_manifest_hash: str,
    evidence_llm_policy: str,
    source_claim_judge: Any | None = None,
    alignment_judge: Any | None = None,
) -> SinglePromptDiagnosisResult:
    gate = _evidence_continuation_inputs(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        project_id=project_id,
        prompt_id=prompt_id,
        answer_result_version=answer_result_version,
        answer_result_hash=answer_result_hash,
        answer_review_id=answer_review_id,
        citation_manifest_id=citation_manifest_id,
        citation_manifest_hash=citation_manifest_hash,
        completion_manifest_id=completion_manifest_id,
        completion_manifest_hash=completion_manifest_hash,
        evidence_llm_policy=evidence_llm_policy,
    )
    if gate["existing_result"] is not None:
        return gate["existing_result"]
    execution = gate["execution"]
    answer_result = gate["answer_result"]
    answer_output = gate["answer_output"]
    review = gate["review"]
    completion = gate["completion"]
    snapshots = gate["snapshots"]
    waiver_limitations = gate["waiver_limitations"]
    binding = gate["binding"]
    binding_hash = gate["binding_hash"]

    raw_context = db.query(SinglePromptAnalysisContext).filter_by(context_id=execution.context_id).one()
    raw_output = loads(raw_context.raw_output_json, {})
    brand = loads(execution.brand_snapshot_json, {})
    truths = loads(execution.truth_snapshot_json, [])
    config = loads(execution.contract_config_json, {})
    config = {**config, "evidence_llm_policy": evidence_llm_policy}
    reviewed_answer = _reviewed_answer_for_evidence(answer_output, review)
    usage = {"external_llm_calls": 0, "llm_cache_hits": 0, "external_token_usage": 0}
    if source_claim_judge is None:
        source_claim_judge = V2SourceClaimJudge(DeepSeekClient(
            thinking_mode=V2_LLM_THINKING_MODE,
            max_attempts=1,
            cache_only=evidence_llm_policy != "ALLOW_EXTERNAL",
        ))
    if alignment_judge is None:
        alignment_judge = V2AlignmentJudge(DeepSeekClient(
            thinking_mode=V2_LLM_THINKING_MODE,
            max_attempts=1,
            cache_only=evidence_llm_policy != "ALLOW_EXTERNAL",
        ))
    execution.status = "EVIDENCE_RUNNING"
    execution.progress_json = _canonical_json({
        "stage": "EVIDENCE_DIAGNOSIS",
        "completed": 0,
        "total": 1,
        "detail": "使用精确 Answer Review 与 Source Completion Manifest 计算证据关系",
        "input_binding_hash": binding_hash,
        "request": binding,
    })
    db.commit()
    try:
        evidence = _diagnose_evidence(
            db,
            answer_diagnosis=reviewed_answer,
            snapshots=snapshots,
            usage=usage,
            source_claim_judge=source_claim_judge,
            alignment_judge=alignment_judge,
            config=config,
        )
        actual_plan = evidence.get("candidate_plan") or {}
        if actual_plan.get("plan_hash") != binding.get("evidence_plan_hash"):
            raise RuntimeError("EVIDENCE_PLAN_BINDING_MISMATCH")
        real_clients = {
            id(client): client
            for client in (getattr(source_claim_judge, "client", None), getattr(alignment_judge, "client", None))
            if isinstance(client, DeepSeekClient)
        }
        if real_clients:
            usage["external_llm_calls"] = sum(client.external_call_count for client in real_clients.values())
            usage["external_token_usage"] = sum(client.external_token_count for client in real_clients.values())
        truth_diagnosis = _diagnose_truths(reviewed_answer, truths, target_brand=brand)
        limitations = [
            row for row in (answer_output.get("limitations") or [])
            if row.get("code") != "EVIDENCE_AWAITS_SOURCE_COMPLETION_AND_EXACT_REVIEW"
        ]
        limitations.extend(waiver_limitations)
        limitations.extend(_limitations(raw_output, reviewed_answer, snapshots, evidence, truth_diagnosis))
        # Preserve order while preventing duplicate generic limitations.
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in limitations:
            key = _hash(row)
            if key not in seen:
                seen.add(key)
                deduped.append(row)
        source_summary = _source_summary(snapshots)
        source_summary.update({
            "unique_sources": completion.required_source_count,
            "content_ready": completion.ready_source_count,
            "waived_with_limitation": completion.waived_source_count,
        })
        stats = {
            **(answer_output.get("stats") or {}),
            **source_summary,
            "candidate_recalled": sum(row["candidate_recall"] == "RECALLED" for row in evidence["source_relations"]),
            "alignment_evaluated": sum(row["alignment_evaluation"] == "EVALUATED" for row in evidence["source_relations"]),
            "alignment_not_evaluated": sum(row["alignment_evaluation"] != "EVALUATED" for row in evidence["source_relations"]),
            "truth_relationships": len(truth_diagnosis["relationships"]),
        }
        output = {
            "contract_version": DIAGNOSIS_CONTRACT_VERSION,
            "result_scope": "ANSWER_AND_EVIDENCE",
            "input": {
                **(answer_output.get("input") or {}),
                **binding,
                "evidence_binding_hash": binding_hash,
                "source_snapshot_ids": sorted(snapshot.snapshot_id for snapshot in snapshots),
            },
            "answer_diagnosis": reviewed_answer,
            "source_diagnosis": {
                "status": "SOURCE_COMPLETION_CONSUMED",
                "summary": source_summary,
                "snapshots": _snapshot_reads(snapshots),
            },
            "evidence_diagnosis": evidence,
            "truth_diagnosis": truth_diagnosis,
            "limitations": deduped,
            "stats": stats,
            "usage": usage,
        }
        output["answer_semantic_eligibility"] = answer_semantic_eligibility(output)
        output_hash = _hash(output)
        version_number = max(
            row.version_number for row in db.query(SinglePromptDiagnosisResult).filter_by(diagnosis_id=diagnosis_id).all()
        ) + 1
        result = SinglePromptDiagnosisResult(
            result_version=f"diag-v{version_number}:{output_hash[:16]}",
            diagnosis_id=diagnosis_id,
            version_number=version_number,
            parent_result_version=answer_result_version,
            output_json=_canonical_json(output),
            output_hash=output_hash,
            reviewable_set_hash=_hash(_reviewable_set(output)),
            limitations_json=_canonical_json(deduped),
            stats_json=_canonical_json(stats),
        )
        db.add(result)
        db.flush()
        execution.active_result_version = result.result_version
        execution.status = "READY_FOR_REVIEW"
        execution.blocker_code = ""
        execution.blocker_detail = ""
        execution.external_llm_calls += int(usage["external_llm_calls"])
        execution.llm_cache_hits += int(usage["llm_cache_hits"])
        execution.external_token_usage += int(usage["external_token_usage"])
        execution.finished_at = datetime.utcnow()
        execution.progress_json = _canonical_json({"stage": "EVIDENCE_RESULT_PUBLISHED", "completed": 1, "total": 1})
        db.commit()
        db.refresh(result)
        return result
    except Exception as exc:
        db.rollback()
        execution = db.query(SinglePromptDiagnosisExecution).filter_by(diagnosis_id=diagnosis_id).one()
        execution.status = "EVIDENCE_FAILED"
        execution.blocker_code = "EVIDENCE_EXECUTION_FAILED"
        execution.blocker_detail = str(exc)[:2000]
        execution.finished_at = datetime.utcnow()
        db.commit()
        raise


def execute_diagnosis(
    diagnosis_id: str,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    if session_factory is None:
        from app.core.database import SessionLocal

        session_factory = SessionLocal
    db = session_factory()
    token = claim_diagnosis(db, diagnosis_id)
    if not token:
        db.close()
        return
    try:
        execution = db.query(SinglePromptDiagnosisExecution).filter(
            SinglePromptDiagnosisExecution.diagnosis_id == diagnosis_id
        ).one()
        config = loads(execution.contract_config_json, {})
        if config.get("diagnosis_mode") == "ANSWER_ONLY":
            compute_answer_diagnosis(db, execution, token)
        else:
            compute_diagnosis(db, execution, token)
    except Exception as exc:
        db.rollback()
        db.execute(
            update(SinglePromptDiagnosisExecution)
            .where(
                SinglePromptDiagnosisExecution.diagnosis_id == diagnosis_id,
                SinglePromptDiagnosisExecution.status == "RUNNING",
                SinglePromptDiagnosisExecution.active_attempt_token == token,
            )
            .values(
                status="FAILED",
                blocker_code="DIAGNOSIS_EXECUTION_FAILED",
                blocker_detail=str(exc)[:2000],
                active_attempt_token="",
                finished_at=datetime.utcnow(),
            )
        )
        db.commit()
    finally:
        db.close()


def execute_queued_evidence(
    diagnosis_id: str,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    if session_factory is None:
        from app.core.database import SessionLocal

        session_factory = SessionLocal
    db = session_factory()
    try:
        execution = db.query(SinglePromptDiagnosisExecution).filter_by(diagnosis_id=diagnosis_id).one_or_none()
        if not execution or execution.status != "EVIDENCE_QUEUED":
            return
        progress = loads(execution.progress_json, {})
        request = progress.get("request") or {}
        required = {
            "analysis_id", "citation_manifest_id", "citation_manifest_hash",
            "completion_manifest_id", "completion_manifest_hash", "answer_result_version",
            "answer_result_hash", "answer_review_id", "evidence_llm_policy",
        }
        if not required.issubset(request):
            raise RuntimeError("EVIDENCE_QUEUE_REQUEST_INCOMPLETE")
        execution.status = "EVIDENCE_RUNNING"
        execution.attempt_count += 1
        db.commit()
        continue_evidence_diagnosis(
            db,
            analysis_id=request["analysis_id"],
            diagnosis_id=diagnosis_id,
            project_id=execution.project_id,
            prompt_id=execution.prompt_id,
            answer_result_version=request["answer_result_version"],
            answer_result_hash=request["answer_result_hash"],
            answer_review_id=request["answer_review_id"],
            citation_manifest_id=request["citation_manifest_id"],
            citation_manifest_hash=request["citation_manifest_hash"],
            completion_manifest_id=request["completion_manifest_id"],
            completion_manifest_hash=request["completion_manifest_hash"],
            evidence_llm_policy=request["evidence_llm_policy"],
        )
    except Exception as exc:
        db.rollback()
        execution = db.query(SinglePromptDiagnosisExecution).filter_by(diagnosis_id=diagnosis_id).one_or_none()
        if execution and execution.status != "EVIDENCE_FAILED":
            execution.status = "EVIDENCE_FAILED"
            execution.blocker_code = "EVIDENCE_EXECUTION_FAILED"
            execution.blocker_detail = str(exc)[:2000]
            execution.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def retry_diagnosis(db: Session, diagnosis_id: str) -> SinglePromptDiagnosisExecution:
    execution = db.query(SinglePromptDiagnosisExecution).filter(
        SinglePromptDiagnosisExecution.diagnosis_id == diagnosis_id
    ).one_or_none()
    if not execution:
        raise HTTPException(status_code=404, detail="诊断执行不存在")
    if loads(execution.contract_config_json, {}).get("automatic_task_id"):
        raise HTTPException(409, "该 Answer 属于自动优化任务，须沿所属任务恢复，不能绕过累计调用预算")
    if execution.status == "EVIDENCE_FAILED":
        progress = loads(execution.progress_json, {})
        if not progress.get("request"):
            raise HTTPException(status_code=409, detail="Evidence 重试输入不存在")
        execution.status = "EVIDENCE_QUEUED"
        execution.blocker_code = ""
        execution.blocker_detail = ""
        execution.finished_at = None
        progress["stage"] = "EVIDENCE_QUEUED"
        progress["detail"] = "等待 release worker 重试相同 Evidence 输入"
        execution.progress_json = _canonical_json(progress)
        db.commit()
        db.refresh(execution)
        return execution
    if execution.active_result_version:
        raise HTTPException(status_code=409, detail="诊断结果已经发布；重跑请创建新的诊断执行")
    if execution.status not in {"FAILED", "INTERRUPTED"}:
        raise HTTPException(status_code=409, detail=f"当前状态 {execution.status} 不允许重试")
    execution.status = "QUEUED"
    execution.blocker_code = ""
    execution.blocker_detail = ""
    execution.active_attempt_token = ""
    execution.finished_at = None
    execution.progress_json = _canonical_json({"stage": "QUEUED", "completed": 0, "total": 1})
    db.commit()
    db.refresh(execution)
    return execution


def _active_result(db: Session, execution: SinglePromptDiagnosisExecution) -> SinglePromptDiagnosisResult | None:
    if not execution.active_result_version:
        return None
    return db.query(SinglePromptDiagnosisResult).filter(
        SinglePromptDiagnosisResult.result_version == execution.active_result_version,
        SinglePromptDiagnosisResult.diagnosis_id == execution.diagnosis_id,
    ).one_or_none()


def get_diagnosis_status(
    db: Session,
    *,
    analysis_id: str,
    diagnosis_id: str,
    project_id: int,
    prompt_id: int,
) -> dict[str, Any]:
    execution = db.query(SinglePromptDiagnosisExecution).filter(
        SinglePromptDiagnosisExecution.diagnosis_id == diagnosis_id,
        SinglePromptDiagnosisExecution.analysis_id == analysis_id,
    ).one_or_none()
    if not execution:
        raise HTTPException(status_code=404, detail="诊断执行不存在")
    if execution.project_id != project_id or execution.prompt_id != prompt_id:
        raise HTTPException(status_code=409, detail="诊断身份与当前 Project/Prompt 不匹配")
    result = _active_result(db, execution)
    review = None
    if result:
        review = db.query(SinglePromptDiagnosisReview).filter(
            SinglePromptDiagnosisReview.result_version == result.result_version
        ).one_or_none()
    result_stats = loads(result.stats_json, {}) if result else {}
    result_output = loads(result.output_json, {}) if result else {}
    context = db.query(SinglePromptAnalysisContext).filter_by(
        context_id=execution.context_id,
        analysis_id=execution.analysis_id,
    ).one_or_none()
    raw_output = loads(context.raw_output_json, {}) if context else {}
    result_scope = str(result_output.get("result_scope") or "")
    prepared_snapshot_ids = list((result_output.get("input") or {}).get("source_snapshot_ids") or [])
    if prepared_snapshot_ids:
        snapshots = (
            db.query(SinglePromptPreparedSourceSnapshot)
            .filter(SinglePromptPreparedSourceSnapshot.snapshot_id.in_(prepared_snapshot_ids))
            .order_by(SinglePromptPreparedSourceSnapshot.source_key)
            .all()
        )
    elif result_scope == "ANSWER_ONLY":
        snapshots = []
    elif result_scope == "ANSWER_AND_EVIDENCE":
        raise HTTPException(
            status_code=409,
            detail={"code": "EVIDENCE_SOURCE_SNAPSHOT_BINDING_MISSING"},
        )
    else:
        snapshots = (
            db.query(SinglePromptSourceSnapshot)
            .filter(SinglePromptSourceSnapshot.diagnosis_id == execution.diagnosis_id)
            .order_by(SinglePromptSourceSnapshot.source_key)
            .all()
        ) if result else []
    safety_advisories, evidence_eligibility = current_evidence_eligibility(
        snapshots,
        historical_content_ready=int(result_stats.get("content_ready") or 0),
        historical_output=result_output,
    )
    answer_eligibility = answer_semantic_eligibility(result_output) if result else None
    mixed_answer_run_ids = _mixed_answer_boundary_run_ids(db, execution) if result else []
    if answer_eligibility and mixed_answer_run_ids:
        answer_eligibility = {
            **answer_eligibility,
            "no_consumable_answer_semantic_result": True,
            "status": "BLOCKED_MIXED_ANSWER_BOUNDARY",
            "mixed_answer_run_ids": mixed_answer_run_ids,
        }
        safety_advisories = [
            *safety_advisories,
            {
                "code": "ANSWER_CONTENT_BOUNDARY_NOT_INDEPENDENT",
                "detail": "历史回答文本包含平台搜索过程，不能作为独立最终回答进入审核或 Evidence。",
                "affected_run_ids": mixed_answer_run_ids,
            },
        ]
    source_content_status_summary = _source_summary(snapshots)
    truth_relation_eligibility = current_truth_relation_eligibility(result_output) if result else None
    project_truth_state = _project_truth_state(db, execution.project_id, execution.truth_set_hash)
    target_capability_review_items = _target_capability_review_items(
        result_output,
        loads(review.decisions_json, []) if review else [],
        project_truth_state["truths"],
    ) if result else []
    review_projection = ({
        "review_id": review.review_id,
        "decision": review.decision,
        "result_version": review.result_version,
        "result_hash": review.result_hash,
        "reviewable_set_hash": review.reviewable_set_hash,
        "decisions": loads(review.decisions_json, []),
    } if review else None)
    coverage_projections = diagnosis_coverage_projections(
        raw_output,
        result_output,
        review_projection,
    ) if result else None
    overall_status = "REVIEW_COMPLETED" if review else execution.status
    return {
        "diagnosis": {
            "diagnosis_id": execution.diagnosis_id,
            "analysis_id": execution.analysis_id,
            "context_id": execution.context_id,
            "project_id": execution.project_id,
            "prompt_id": execution.prompt_id,
            "input_fingerprint": execution.input_fingerprint,
            "raw_output_hash": execution.raw_output_hash,
            "brand_snapshot_hash": execution.brand_snapshot_hash,
            "truth_set_hash": execution.truth_set_hash,
            "contract_config_hash": execution.contract_config_hash,
        },
        "compute_status": execution.status,
        "overall_status": overall_status,
        "progress": loads(execution.progress_json, {}),
        "blocker": {"code": execution.blocker_code, "detail": execution.blocker_detail} if execution.blocker_code else None,
        "attempt_count": execution.attempt_count,
        "usage": {
            "external_llm_calls": execution.external_llm_calls,
            "llm_cache_hits": execution.llm_cache_hits,
            "external_token_usage": execution.external_token_usage,
        },
        "current_safety_advisories": safety_advisories,
        "effective_evidence_eligibility": evidence_eligibility,
        "source_content_status_summary": source_content_status_summary,
        "current_truth_relation_eligibility": truth_relation_eligibility,
        "project_truth_state": project_truth_state,
        "target_capability_review_items": target_capability_review_items,
        "answer_semantic_eligibility": answer_eligibility,
        "coverage_projections": coverage_projections,
        "result": {
            "result_version": result.result_version,
            "version_number": result.version_number,
            "parent_result_version": result.parent_result_version,
            "output_hash": result.output_hash,
            "reviewable_set_hash": result.reviewable_set_hash,
            "output": result_output,
            "limitations": loads(result.limitations_json, []),
            "stats": loads(result.stats_json, {}),
            "created_at": _iso(result.created_at),
        } if result else None,
        "review": {
            "review_id": review.review_id,
            "decision": review.decision,
            "result_version": review.result_version,
            "result_hash": review.result_hash,
            "reviewable_set_hash": review.reviewable_set_hash,
            "decisions": loads(review.decisions_json, []),
            "reviewer": review.reviewer,
            "note": review.note,
            "created_at": _iso(review.created_at),
        } if review else None,
        "allowed_operations": (
            ["VIEW"] if result and answer_eligibility and answer_eligibility["no_consumable_answer_semantic_result"]
            else ["VIEW", "REVISE", "COMPLETE_REVIEW"] if result and not review
            else ["VIEW"] if result
            else ["VIEW", "RETRY"] if execution.status in {"FAILED", "INTERRUPTED", "EVIDENCE_FAILED"}
            else ["VIEW"]
        ),
        "created_at": _iso(execution.created_at),
        "started_at": _iso(execution.started_at),
        "finished_at": _iso(execution.finished_at),
    }


def revise_diagnosis_result(
    db: Session,
    *,
    diagnosis_id: str,
    base_result_version: str,
    base_result_hash: str,
    reviewable_set_hash: str,
    edits: list[dict],
    editor: str,
) -> SinglePromptDiagnosisResult:
    execution = db.query(SinglePromptDiagnosisExecution).filter(
        SinglePromptDiagnosisExecution.diagnosis_id == diagnosis_id
    ).one_or_none()
    if not execution:
        raise HTTPException(status_code=404, detail="诊断执行不存在")
    _require_independent_answer_boundary(db, execution, "REVISE")
    if execution.active_result_version != base_result_version:
        raise HTTPException(status_code=409, detail="诊断结果版本已变化，请重新加载")
    base = db.query(SinglePromptDiagnosisResult).filter(
        SinglePromptDiagnosisResult.result_version == base_result_version,
        SinglePromptDiagnosisResult.diagnosis_id == diagnosis_id,
    ).one_or_none()
    if not base or base.output_hash != base_result_hash or base.reviewable_set_hash != reviewable_set_hash:
        raise HTTPException(status_code=409, detail="审核目标集合已变化，请重新加载")
    _require_consumable_answer_semantic(loads(base.output_json, {}), "REVISE")
    if db.query(SinglePromptDiagnosisReview).filter(SinglePromptDiagnosisReview.result_version == base_result_version).first():
        raise HTTPException(status_code=409, detail="已审核结果不可修改；请发起新的诊断执行")

    output = copy.deepcopy(loads(base.output_json, {}))
    applied: list[dict] = []
    for edit in edits:
        target_type = str(edit.get("target_type") or "")
        target_id = str(edit.get("target_id") or "")
        value = str(edit.get("value") or "")
        reason = str(edit.get("reason") or "").strip()
        if not reason:
            raise HTTPException(status_code=422, detail="每项语义修改都必须填写原因")
        target = None
        allowed: set[str] = set()
        field = ""
        if target_type == "RECOMMENDATION_EVENT":
            target = next((row for row in output["answer_diagnosis"]["events"] if row["event_id"] == target_id), None)
            allowed, field = _SPEECH_ACTS, "effective_speech_act"
        elif target_type == "EVIDENCE_RELATION":
            target = next((row for row in output["evidence_diagnosis"]["source_relations"] if row["relation_id"] == target_id), None)
            allowed, field = {"SOURCE_SUPPORTS_REASON", "SOURCE_CONTRADICTS_REASON", "RELATED", "NONE"}, "effective_relation"
            if target and target.get("alignment_evaluation") != "EVALUATED":
                raise HTTPException(status_code=422, detail="未完成判断的证据关系不能被编辑成 verdict")
        elif target_type == "TRUTH_RELATION":
            target = next((row for row in output["truth_diagnosis"]["relationships"] if row["relationship_id"] == target_id), None)
            allowed, field = _TRUTH_RELATIONS, "effective_relation"
            if target and target.get("truth_id") is None and value != "UNRESOLVED":
                raise HTTPException(status_code=422, detail="空品牌事实不能被编辑成已覆盖或冲突")
            if target and target.get("truth_id") is not None and value in {"FULLY_COVERS", "PARTIALLY_COVERS"}:
                truth = next(
                    (
                        row for row in output["truth_diagnosis"].get("truth_snapshot") or []
                        if row.get("truth_id") == target.get("truth_id")
                    ),
                    None,
                )
                if not truth or truth.get("product_truth_status") not in {"TRUE", "SUPPORTED"}:
                    raise HTTPException(status_code=422, detail="该目标品牌能力尚未确认为具备，不能确认覆盖关系")
        if not target or value not in allowed:
            raise HTTPException(status_code=422, detail=f"非法诊断修改：{target_type}/{target_id}/{value}")
        before = target.get(field)
        target[field] = value
        target["human_override"] = {"editor": editor, "reason": reason, "before": before, "after": value}
        applied.append({"target_type": target_type, "target_id": target_id, "field": field, "before": before, "after": value, "reason": reason})

    version_number = base.version_number + 1
    output["revision"] = {
        "parent_result_version": base.result_version,
        "editor": editor,
        "applied_edits": applied,
    }
    output_hash = _hash(output)
    new_result = SinglePromptDiagnosisResult(
        result_version=f"diag-v{version_number}:{output_hash[:16]}",
        diagnosis_id=diagnosis_id,
        version_number=version_number,
        parent_result_version=base.result_version,
        output_json=_canonical_json(output),
        output_hash=output_hash,
        reviewable_set_hash=_hash(_reviewable_set(output)),
        limitations_json=base.limitations_json,
        stats_json=base.stats_json,
    )
    db.add(new_result)
    db.flush()
    updated = db.execute(
        update(SinglePromptDiagnosisExecution)
        .where(
            SinglePromptDiagnosisExecution.diagnosis_id == diagnosis_id,
            SinglePromptDiagnosisExecution.active_result_version == base_result_version,
        )
        .values(active_result_version=new_result.result_version)
    )
    if updated.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="诊断结果版本已变化，请重新加载")
    db.commit()
    db.refresh(new_result)
    return new_result


def complete_diagnosis_review(
    db: Session,
    *,
    diagnosis_id: str,
    result_version: str,
    result_hash: str,
    reviewable_set_hash: str,
    reviewer: str,
    note: str,
    decisions: list[dict],
) -> SinglePromptDiagnosisReview:
    execution = db.query(SinglePromptDiagnosisExecution).filter(
        SinglePromptDiagnosisExecution.diagnosis_id == diagnosis_id
    ).one_or_none()
    if not execution:
        raise HTTPException(status_code=404, detail="诊断执行不存在")
    _require_independent_answer_boundary(db, execution, "COMPLETE_REVIEW")
    if execution.active_result_version != result_version:
        raise HTTPException(status_code=409, detail="诊断结果版本已变化，请重新加载")
    result = db.query(SinglePromptDiagnosisResult).filter(
        SinglePromptDiagnosisResult.result_version == result_version,
        SinglePromptDiagnosisResult.diagnosis_id == diagnosis_id,
    ).one_or_none()
    if not result or result.output_hash != result_hash or result.reviewable_set_hash != reviewable_set_hash:
        raise HTTPException(status_code=409, detail="审核目标集合已变化，请重新加载")
    result_output = loads(result.output_json, {})
    _require_consumable_answer_semantic(result_output, "COMPLETE_REVIEW")
    validate_answer_event_review_decisions(result_output, decisions)
    if db.query(SinglePromptDiagnosisReview).filter(SinglePromptDiagnosisReview.result_version == result_version).first():
        raise HTTPException(status_code=409, detail="该诊断结果已经完成审核")
    prior_review_id = str(
        (((result_output.get("truth_reprojection") or {}).get("prior_review") or {}).get("review_id")) or ""
    ) or None
    review = SinglePromptDiagnosisReview(
        review_id=f"review-{uuid4()}",
        diagnosis_id=diagnosis_id,
        result_version=result_version,
        result_hash=result_hash,
        reviewable_set_hash=reviewable_set_hash,
        prior_review_id=prior_review_id,
        decision="REVIEW_COMPLETED",
        decisions_json=_canonical_json(decisions),
        reviewer=reviewer,
        note=note,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


_ANSWER_EVENT_REVIEW_DECISIONS = {
    "CONFIRM_INCLUDE_AS_OPTION",
    "CORRECT_TO_MENTION",
    "KEEP_UNRESOLVED",
    "EXCLUDE_EXTRACTION",
}


def validate_answer_event_review_decisions(output: dict[str, Any], decisions: list[dict]) -> dict[str, str]:
    """Require an explicit disposition for every event held for semantic review."""
    pending = {
        str(event.get("event_id")): event
        for event in (output.get("answer_diagnosis") or {}).get("events") or []
        if (
            event.get("event_id")
            and event.get("semantic_validation_status") == "SEMANTIC_REVIEW_REQUIRED"
            and not (
                event.get("fact_consumption_eligible") is True
                and event.get("review_status") == "HUMAN_CONFIRMED_INCLUDE_AS_OPTION"
                and event.get("review_id")
            )
        )
    }
    if not pending:
        return {}

    reviewed: dict[str, str] = {}
    for row in decisions:
        if row.get("scope") != "ANSWER_SEMANTIC_EVENT":
            continue
        event_id = str(row.get("event_id") or "")
        decision = str(row.get("decision") or "")
        if event_id not in pending:
            raise HTTPException(status_code=422, detail=f"审核决定引用了非待审事件：{event_id or 'EMPTY'}")
        if event_id in reviewed:
            raise HTTPException(status_code=422, detail=f"待审事件存在重复决定：{event_id}")
        if decision not in _ANSWER_EVENT_REVIEW_DECISIONS:
            raise HTTPException(status_code=422, detail=f"待审事件决定非法：{event_id}/{decision or 'EMPTY'}")
        event = pending[event_id]
        if row.get("run_id") is not None and int(row["run_id"]) != int(event.get("run_id") or 0):
            raise HTTPException(status_code=422, detail=f"待审事件 Run 不匹配：{event_id}")
        speech_act = str(event.get("effective_speech_act") or event.get("machine_speech_act") or "")
        if decision == "CONFIRM_INCLUDE_AS_OPTION" and speech_act != "INCLUDE_AS_OPTION":
            raise HTTPException(status_code=422, detail=f"只有当前 INCLUDE_AS_OPTION 事件可以确认候选：{event_id}")
        if decision == "CORRECT_TO_MENTION" and speech_act != "MENTION":
            raise HTTPException(status_code=422, detail=f"更正为仅提及前必须先保存 MENTION 结果版本：{event_id}")
        reviewed[event_id] = decision

    missing = sorted(set(pending) - set(reviewed))
    if missing:
        raise HTTPException(status_code=422, detail={
            "code": "ANSWER_SEMANTIC_EVENT_REVIEW_INCOMPLETE",
            "detail": "每个待审候选都必须确认、修正、保留不确定或排除后，才能完成本版审核。",
            "missing_event_ids": missing,
        })
    return reviewed


def recover_interrupted_diagnoses(db: Session) -> int:
    rows = db.query(SinglePromptDiagnosisExecution).filter(
        SinglePromptDiagnosisExecution.status.in_(["RUNNING", "EVIDENCE_RUNNING"])
    ).all()
    for row in rows:
        row.status = "EVIDENCE_FAILED" if row.status == "EVIDENCE_RUNNING" else "INTERRUPTED"
        row.blocker_code = "SERVICE_RESTART_INTERRUPTED"
        row.blocker_detail = "服务重启中断了诊断执行；未静默重算，请人工确认后重试"
        row.active_attempt_token = ""
        row.finished_at = datetime.utcnow()
    if rows:
        db.commit()
    return len(rows)
