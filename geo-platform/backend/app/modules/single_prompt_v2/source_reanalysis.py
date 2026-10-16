"""Append-only source reanalysis after an immutable source version changes.

The planner binds exact old/new completion manifests and creates a new
Diagnosis execution.  It never moves a current pointer on the old Diagnosis,
Strategy, or Delivery objects.  Production execution remains authorization
gated; tests and offline gates may inject deterministic judges explicitly.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    SinglePromptAnalysisContext,
    SinglePromptDiagnosisExecution,
    SinglePromptDiagnosisResult,
    SinglePromptDiagnosisReview,
    SinglePromptExecutionProposal,
    SinglePromptExecutionProposalResult,
    SinglePromptSourceCompletionManifest,
    SinglePromptStrategyExecution,
    SinglePromptStrategyResult,
)
from app.services.serialization import loads

from .source_preparation import validate_completion_for_evidence


CONTRACT_VERSION = "single_prompt_source_reanalysis.v1"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _source_rows(manifest: SinglePromptSourceCompletionManifest) -> dict[str, dict[str, Any]]:
    payload = loads(manifest.payload_json, {})
    if _hash(payload) != manifest.payload_hash:
        raise HTTPException(409, detail={"code": "SOURCE_MANIFEST_CONTENT_HASH_MISMATCH"})
    return {str(row.get("source_key")): row for row in payload.get("sources") or []}


def _affected_downstream(
    db: Session,
    *,
    analysis_id: str,
    prior_manifest_id: str,
    changed_old_snapshot_ids: set[str],
) -> list[dict[str, Any]]:
    affected: list[dict[str, Any]] = []
    results = (
        db.query(SinglePromptDiagnosisResult, SinglePromptDiagnosisExecution)
        .join(
            SinglePromptDiagnosisExecution,
            SinglePromptDiagnosisExecution.diagnosis_id == SinglePromptDiagnosisResult.diagnosis_id,
        )
        .filter(SinglePromptDiagnosisExecution.analysis_id == analysis_id)
        .all()
    )
    for result, diagnosis in results:
        output = loads(result.output_json, {})
        inputs = output.get("input") or {}
        if inputs.get("completion_manifest_id") != prior_manifest_id:
            continue
        bound_snapshots = set(inputs.get("source_snapshot_ids") or [])
        if changed_old_snapshot_ids and not bound_snapshots.intersection(changed_old_snapshot_ids):
            continue
        item: dict[str, Any] = {
            "object_type": "DIAGNOSIS_RESULT",
            "diagnosis_id": diagnosis.diagnosis_id,
            "result_version": result.result_version,
            "result_hash": result.output_hash,
        }
        strategies = db.query(SinglePromptStrategyExecution).filter_by(
            analysis_id=analysis_id,
            diagnosis_result_version=result.result_version,
        ).all()
        item["strategies"] = []
        for strategy in strategies:
            strategy_result = db.query(SinglePromptStrategyResult).filter_by(
                strategy_id=strategy.strategy_id,
                result_version=strategy.active_result_version,
            ).one_or_none()
            proposals = db.query(SinglePromptExecutionProposal).filter_by(
                strategy_id=strategy.strategy_id,
                analysis_id=analysis_id,
            ).all()
            deliveries = []
            for proposal in proposals:
                proposal_result = None
                if proposal.active_result_version:
                    proposal_result = db.query(SinglePromptExecutionProposalResult).filter_by(
                        proposal_id=proposal.proposal_id,
                        result_version=proposal.active_result_version,
                    ).one_or_none()
                deliveries.append({
                    "proposal_id": proposal.proposal_id,
                    "result_version": proposal.active_result_version,
                    "result_hash": proposal_result.output_hash if proposal_result else "",
                })
            item["strategies"].append({
                "strategy_id": strategy.strategy_id,
                "result_version": strategy.active_result_version,
                "result_hash": strategy_result.output_hash if strategy_result else "",
                "deliveries": deliveries,
            })
        affected.append(item)
    return sorted(affected, key=lambda row: (row["diagnosis_id"], row["result_version"]))


def plan_source_reanalysis(
    db: Session,
    *,
    preparation_id: str,
    project_id: int,
    prompt_id: int,
    prior_completion_manifest_id: str,
    prior_completion_manifest_hash: str,
    new_completion_manifest_id: str,
    new_completion_manifest_hash: str,
    idempotency_key: str,
    requested_by: str,
) -> tuple[list[SinglePromptDiagnosisExecution], bool]:
    if not idempotency_key.strip() or not requested_by.strip():
        raise HTTPException(422, detail={"code": "SOURCE_REANALYSIS_AUDIT_IDENTITY_REQUIRED"})
    prior = db.query(SinglePromptSourceCompletionManifest).filter_by(
        manifest_id=prior_completion_manifest_id,
        preparation_id=preparation_id,
    ).one_or_none()
    current = db.query(SinglePromptSourceCompletionManifest).filter_by(
        manifest_id=new_completion_manifest_id,
        preparation_id=preparation_id,
    ).one_or_none()
    if not prior or prior.payload_hash != prior_completion_manifest_hash:
        raise HTTPException(409, detail={"code": "PRIOR_SOURCE_COMPLETION_INPUT_MISMATCH"})
    if not current or current.payload_hash != new_completion_manifest_hash:
        raise HTTPException(409, detail={"code": "NEW_SOURCE_COMPLETION_INPUT_MISMATCH"})
    if (
        prior.analysis_id != current.analysis_id
        or prior.context_id != current.context_id
        or prior.citation_manifest_id != current.citation_manifest_id
        or prior.citation_manifest_hash != current.citation_manifest_hash
        or current.version_number <= prior.version_number
    ):
        raise HTTPException(409, detail={"code": "SOURCE_REANALYSIS_LINEAGE_MISMATCH"})
    context = db.query(SinglePromptAnalysisContext).filter_by(
        context_id=current.context_id,
        analysis_id=current.analysis_id,
        project_id=project_id,
        prompt_id=prompt_id,
    ).one_or_none()
    if not context:
        raise HTTPException(409, detail={"code": "SOURCE_REANALYSIS_PROJECT_PROMPT_MISMATCH"})
    validate_completion_for_evidence(
        db,
        analysis_id=current.analysis_id,
        context_id=current.context_id,
        citation_manifest_id=current.citation_manifest_id,
        citation_manifest_hash=current.citation_manifest_hash,
        completion_manifest_id=current.manifest_id,
        completion_manifest_hash=current.payload_hash,
        allow_partial=True,
    )
    old_rows, new_rows = _source_rows(prior), _source_rows(current)
    if set(old_rows) != set(new_rows):
        raise HTTPException(409, detail={"code": "SOURCE_REANALYSIS_SCOPE_CHANGED"})
    changed_keys = sorted(key for key in old_rows if old_rows[key] != new_rows[key])
    if not changed_keys:
        raise HTTPException(409, detail={"code": "SOURCE_REANALYSIS_NO_CONTENT_CHANGE"})
    old_snapshot_ids = {
        str(old_rows[key].get("snapshot_id"))
        for key in changed_keys
        if old_rows[key].get("snapshot_id")
    }
    affected = _affected_downstream(
        db,
        analysis_id=current.analysis_id,
        prior_manifest_id=prior.manifest_id,
        changed_old_snapshot_ids=old_snapshot_ids,
    )
    created = False
    plans: list[SinglePromptDiagnosisExecution] = []
    for downstream in affected:
        old_execution = db.query(SinglePromptDiagnosisExecution).filter_by(
            diagnosis_id=downstream["diagnosis_id"]
        ).one()
        base_output = loads(
            db.query(SinglePromptDiagnosisResult).filter_by(
                result_version=downstream["result_version"]
            ).one().output_json,
            {},
        )
        base_input = base_output.get("input") or {}
        answer_version = str(base_input.get("answer_result_version") or "")
        answer_hash = str(base_input.get("answer_result_hash") or "")
        answer_review_id = str(base_input.get("answer_review_id") or "")
        answer = db.query(SinglePromptDiagnosisResult).filter_by(
            diagnosis_id=old_execution.diagnosis_id,
            result_version=answer_version,
        ).one_or_none()
        review = db.query(SinglePromptDiagnosisReview).filter_by(
            diagnosis_id=old_execution.diagnosis_id,
            review_id=answer_review_id,
            result_version=answer_version,
        ).one_or_none()
        executable = bool(
            answer
            and answer.output_hash == answer_hash
            and review
            and review.result_hash == answer_hash
            and review.decision == "REVIEW_COMPLETED"
        )
        frozen = {
            "contract_version": CONTRACT_VERSION,
            "analysis_id": current.analysis_id,
            "context_id": current.context_id,
            "project_id": project_id,
            "prompt_id": prompt_id,
            "raw_output_hash": context.raw_output_hash,
            "citation_manifest_id": current.citation_manifest_id,
            "citation_manifest_hash": current.citation_manifest_hash,
            "prior_completion_manifest_id": prior.manifest_id,
            "prior_completion_manifest_hash": prior.payload_hash,
            "new_completion_manifest_id": current.manifest_id,
            "new_completion_manifest_hash": current.payload_hash,
            "changed_source_keys": changed_keys,
            "changed_snapshots": [
                {
                    "source_key": key,
                    "prior_snapshot_id": old_rows[key].get("snapshot_id"),
                    "prior_content_hash": old_rows[key].get("content_hash"),
                    "new_snapshot_id": new_rows[key].get("snapshot_id"),
                    "new_content_hash": new_rows[key].get("content_hash"),
                }
                for key in changed_keys
            ],
            "base_downstream": downstream,
            "answer_result_version": answer_version,
            "answer_result_hash": answer_hash,
            "answer_review_id": answer_review_id,
            "local_gate": "PASSED" if executable else "BLOCKED",
            "local_gate_code": "EXACT_ANSWER_REVIEW_BOUND" if executable else "EXACT_ANSWER_REVIEW_REQUIRED",
        }
        input_hash = _hash(frozen)
        plan_key = f"{idempotency_key}:{downstream['result_version']}"[:120]
        existing = db.query(SinglePromptDiagnosisExecution).filter_by(
            analysis_id=current.analysis_id,
            idempotency_key=plan_key,
        ).one_or_none()
        if existing:
            if existing.input_fingerprint != input_hash:
                raise HTTPException(409, detail={"code": "SOURCE_REANALYSIS_IDEMPOTENCY_CONFLICT"})
            plans.append(existing)
            continue
        config = loads(old_execution.contract_config_json, {})
        config.update({
            "diagnosis_mode": "SOURCE_REANALYSIS",
            "source_reanalysis_contract_version": CONTRACT_VERSION,
        })
        status = "AWAITING_EXTERNAL_AUTHORIZATION" if executable else "BLOCKED"
        plan = SinglePromptDiagnosisExecution(
            diagnosis_id=f"source-reanalysis-{uuid4()}",
            analysis_id=current.analysis_id,
            context_id=current.context_id,
            project_id=project_id,
            prompt_id=prompt_id,
            idempotency_key=plan_key,
            input_fingerprint=input_hash,
            raw_output_hash=context.raw_output_hash,
            brand_snapshot_json=old_execution.brand_snapshot_json,
            brand_snapshot_hash=old_execution.brand_snapshot_hash,
            truth_snapshot_json=old_execution.truth_snapshot_json,
            truth_set_hash=old_execution.truth_set_hash,
            contract_config_json=_json(config),
            contract_config_hash=_hash(config),
            status=status,
            progress_json=_json({
                "stage": "SOURCE_REANALYSIS_PLANNED",
                "input": frozen,
                "input_hash": input_hash,
                "result_creation": "PENDING",
                "requested_by": requested_by,
            }),
            blocker_code=("EXTERNAL_MODEL_AUTHORIZATION_REQUIRED" if executable else "EXACT_ANSWER_REVIEW_REQUIRED"),
            blocker_detail=(
                "精确范围和本地 Gate 已固定；正式证据重分析需要新的显式模型授权，未发起外部调用。"
                if executable else "旧结果缺少可复用的精确 Answer Review，不能建立证据重分析。"
            ),
        )
        db.add(plan)
        plans.append(plan)
        created = True
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, detail={"code": "SOURCE_REANALYSIS_CONCURRENT_CONFLICT"})
    for plan in plans:
        db.refresh(plan)
    return plans, created


def source_reanalysis_view(row: SinglePromptDiagnosisExecution) -> dict[str, Any]:
    progress = loads(row.progress_json, {})
    return {
        "reanalysis_id": row.diagnosis_id,
        "analysis_id": row.analysis_id,
        "context_id": row.context_id,
        "project_id": row.project_id,
        "prompt_id": row.prompt_id,
        "status": row.status,
        "input_hash": row.input_fingerprint,
        "input": progress.get("input") or {},
        "result_creation": progress.get("result_creation"),
        "result_version": row.active_result_version or None,
        "blocker_code": row.blocker_code,
        "blocker_detail": row.blocker_detail,
        "external_usage": {
            "calls": row.external_llm_calls,
            "tokens": row.external_token_usage,
        },
    }


def execute_source_reanalysis_with_local_judges(
    db: Session,
    *,
    reanalysis_id: str,
    source_claim_judge: Any,
    alignment_judge: Any,
) -> SinglePromptDiagnosisResult:
    """Run the frozen plan only with explicitly injected offline/test judges."""
    from .diagnosis import (
        DIAGNOSIS_CONTRACT_VERSION,
        _build_candidate_plan_for_evidence,
        _diagnose_evidence,
        _diagnose_truths,
        _limitations,
        _reviewable_set,
        _reviewed_answer_for_evidence,
        _snapshot_reads,
        _source_summary,
        answer_semantic_eligibility,
    )

    if source_claim_judge is None or alignment_judge is None:
        raise HTTPException(409, detail={"code": "LOCAL_JUDGES_REQUIRED"})
    row = db.query(SinglePromptDiagnosisExecution).filter_by(diagnosis_id=reanalysis_id).one_or_none()
    if not row:
        raise HTTPException(404, detail={"code": "SOURCE_REANALYSIS_NOT_FOUND"})
    progress = loads(row.progress_json, {})
    frozen = progress.get("input") or {}
    if progress.get("input_hash") != row.input_fingerprint or _hash(frozen) != row.input_fingerprint:
        raise HTTPException(409, detail={"code": "SOURCE_REANALYSIS_INPUT_HASH_MISMATCH"})
    existing = db.query(SinglePromptDiagnosisResult).filter_by(diagnosis_id=row.diagnosis_id).one_or_none()
    if existing:
        if row.active_result_version != existing.result_version:
            raise HTTPException(409, detail={"code": "SOURCE_REANALYSIS_RESULT_POINTER_MISMATCH"})
        return existing
    if frozen.get("local_gate") != "PASSED":
        raise HTTPException(409, detail={"code": frozen.get("local_gate_code") or "SOURCE_REANALYSIS_GATE_BLOCKED"})
    old_diagnosis_id = (frozen.get("base_downstream") or {}).get("diagnosis_id")
    answer = db.query(SinglePromptDiagnosisResult).filter_by(
        diagnosis_id=old_diagnosis_id,
        result_version=frozen.get("answer_result_version"),
    ).one_or_none()
    review = db.query(SinglePromptDiagnosisReview).filter_by(
        diagnosis_id=old_diagnosis_id,
        review_id=frozen.get("answer_review_id"),
        result_version=frozen.get("answer_result_version"),
    ).one_or_none()
    if (
        not answer
        or answer.output_hash != frozen.get("answer_result_hash")
        or not review
        or review.result_hash != answer.output_hash
        or review.decision != "REVIEW_COMPLETED"
    ):
        raise HTTPException(409, detail={"code": "EXACT_ANSWER_REVIEW_REQUIRED"})
    context = db.query(SinglePromptAnalysisContext).filter_by(context_id=row.context_id).one()
    if context.raw_output_hash != frozen.get("raw_output_hash"):
        raise HTTPException(409, detail={"code": "SOURCE_REANALYSIS_RAW_INPUT_MISMATCH"})
    completion, snapshots, waiver_limitations = validate_completion_for_evidence(
        db,
        analysis_id=row.analysis_id,
        context_id=row.context_id,
        citation_manifest_id=frozen["citation_manifest_id"],
        citation_manifest_hash=frozen["citation_manifest_hash"],
        completion_manifest_id=frozen["new_completion_manifest_id"],
        completion_manifest_hash=frozen["new_completion_manifest_hash"],
        allow_partial=True,
    )
    answer_output = loads(answer.output_json, {})
    reviewed_answer = _reviewed_answer_for_evidence(answer_output, review)
    candidate_plan, _ = _build_candidate_plan_for_evidence(reviewed_answer, snapshots)
    usage = {"external_llm_calls": 0, "llm_cache_hits": 0, "external_token_usage": 0}
    row.status = "RUNNING_LOCAL_GATE"
    row.blocker_code = ""
    row.blocker_detail = ""
    db.commit()
    try:
        evidence = _diagnose_evidence(
            db,
            answer_diagnosis=reviewed_answer,
            snapshots=snapshots,
            usage=usage,
            source_claim_judge=source_claim_judge,
            alignment_judge=alignment_judge,
            config=loads(row.contract_config_json, {}),
        )
        if (evidence.get("candidate_plan") or {}).get("plan_hash") != candidate_plan.get("plan_hash"):
            raise RuntimeError("EVIDENCE_PLAN_BINDING_MISMATCH")
        truths = _diagnose_truths(
            reviewed_answer,
            loads(row.truth_snapshot_json, []),
            target_brand=loads(row.brand_snapshot_json, {}),
        )
        limitations = [
            item for item in (answer_output.get("limitations") or [])
            if item.get("code") != "EVIDENCE_AWAITS_SOURCE_COMPLETION_AND_EXACT_REVIEW"
        ]
        limitations.extend(waiver_limitations)
        limitations.extend(_limitations(loads(context.raw_output_json, {}), reviewed_answer, snapshots, evidence, truths))
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in limitations:
            key = _hash(item)
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        source_summary = _source_summary(snapshots)
        source_summary.update({
            "unique_sources": completion.required_source_count,
            "content_ready": completion.ready_source_count,
            "waived_with_limitation": completion.waived_source_count,
        })
        stats = {
            **(answer_output.get("stats") or {}),
            **source_summary,
            "candidate_recalled": sum(
                item["candidate_recall"] == "RECALLED" for item in evidence["source_relations"]
            ),
            "alignment_evaluated": sum(
                item["alignment_evaluation"] == "EVALUATED" for item in evidence["source_relations"]
            ),
            "alignment_not_evaluated": sum(
                item["alignment_evaluation"] != "EVALUATED" for item in evidence["source_relations"]
            ),
            "truth_relationships": len(truths["relationships"]),
        }
        evidence_binding = {
            "analysis_id": row.analysis_id,
            "context_id": row.context_id,
            "citation_manifest_id": frozen["citation_manifest_id"],
            "citation_manifest_hash": frozen["citation_manifest_hash"],
            "completion_manifest_id": frozen["new_completion_manifest_id"],
            "completion_manifest_hash": frozen["new_completion_manifest_hash"],
            "answer_result_version": answer.result_version,
            "answer_result_hash": answer.output_hash,
            "answer_review_id": review.review_id,
            "answer_reviewable_set_hash": review.reviewable_set_hash,
            "evidence_plan_id": candidate_plan["plan_id"],
            "evidence_plan_hash": candidate_plan["plan_hash"],
            "evidence_plan_policy_version": candidate_plan["policy_version"],
            "source_reanalysis_input_hash": row.input_fingerprint,
        }
        output = {
            "contract_version": DIAGNOSIS_CONTRACT_VERSION,
            "result_scope": "ANSWER_AND_EVIDENCE",
            "input": {
                **(answer_output.get("input") or {}),
                "source_reanalysis_contract_version": CONTRACT_VERSION,
                "source_reanalysis_input_hash": row.input_fingerprint,
                "prior_completion_manifest_id": frozen["prior_completion_manifest_id"],
                "prior_completion_manifest_hash": frozen["prior_completion_manifest_hash"],
                "completion_manifest_id": frozen["new_completion_manifest_id"],
                "completion_manifest_hash": frozen["new_completion_manifest_hash"],
                "answer_result_version": answer.result_version,
                "answer_result_hash": answer.output_hash,
                "answer_review_id": review.review_id,
                "answer_reviewable_set_hash": review.reviewable_set_hash,
                "evidence_plan_id": candidate_plan["plan_id"],
                "evidence_plan_hash": candidate_plan["plan_hash"],
                "evidence_plan_policy_version": candidate_plan["policy_version"],
                "evidence_binding_hash": _hash(evidence_binding),
                "source_snapshot_ids": sorted(snapshot.snapshot_id for snapshot in snapshots),
                "changed_source_keys": frozen["changed_source_keys"],
            },
            "answer_diagnosis": reviewed_answer,
            "source_diagnosis": {
                "status": "SOURCE_COMPLETION_CONSUMED",
                "summary": source_summary,
                "snapshots": _snapshot_reads(snapshots),
            },
            "evidence_diagnosis": evidence,
            "truth_diagnosis": truths,
            "limitations": deduped,
            "stats": stats,
            "usage": usage,
        }
        output["answer_semantic_eligibility"] = answer_semantic_eligibility(output)
        output_hash = _hash(output)
        result = SinglePromptDiagnosisResult(
            result_version=f"source-reanalysis-v1:{output_hash[:16]}",
            diagnosis_id=row.diagnosis_id,
            version_number=1,
            parent_result_version=(frozen.get("base_downstream") or {}).get("result_version"),
            output_json=_json(output),
            output_hash=output_hash,
            reviewable_set_hash=_hash(_reviewable_set(output)),
            limitations_json=_json(deduped),
            stats_json=_json(stats),
        )
        db.add(result)
        db.flush()
        row.active_result_version = result.result_version
        row.status = "READY_FOR_REVIEW"
        row.finished_at = datetime.utcnow()
        row.progress_json = _json({
            **progress,
            "stage": "SOURCE_REANALYSIS_RESULT_PUBLISHED",
            "result_creation": "COMPLETED_LOCAL_GATE",
            "result_version": result.result_version,
            "result_hash": result.output_hash,
        })
        db.commit()
        db.refresh(result)
        return result
    except Exception:
        db.rollback()
        row = db.query(SinglePromptDiagnosisExecution).filter_by(diagnosis_id=reanalysis_id).one()
        row.status = "BLOCKED"
        row.blocker_code = "SOURCE_REANALYSIS_LOCAL_GATE_FAILED"
        row.blocker_detail = "本地重分析 Gate 失败；未覆盖旧结果，也未发起外部调用。"
        db.commit()
        raise
