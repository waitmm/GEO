"""Lifecycle and read models for the isolated Agent experiment."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AgentCheckpoint, AgentDraftArtifactFeedback, AgentDraftArtifactRegeneration,
    AgentDraftArtifactVersion, AgentEvent, AgentExperimentRun, AgentResultFeedback,
    AgentResultVersion,
    SinglePromptAnalysis, SinglePromptAnalysisContext, SinglePromptOptimizationTask,
)
from app.modules.single_prompt_v2.delivery_text import digest
from app.services.serialization import loads

from .scope import freeze_scope


DEFAULT_BUDGET = {"max_model_calls": 10, "max_tool_calls": 12, "max_total_tokens": 100_000,
                  "max_elapsed_seconds": 300, "max_repairs": 1, "max_cost_cny": 5.0}
EVIDENCE_PACK_BUDGET = {"max_model_calls": 1, "max_tool_calls": 0, "max_total_tokens": 300_000,
                        "max_elapsed_seconds": 300, "max_repairs": 0, "max_cost_cny": 5.0}
EXECUTION_MODES = frozenset({"TOOL_LOOP", "EVIDENCE_PACK"})
TERMINAL_STATUSES = frozenset({"SUCCEEDED", "PARTIAL", "NEEDS_INPUT", "BLOCKED", "FAILED", "CANCELLED"})
FEEDBACK_RATINGS = frozenset({"USABLE", "NEEDS_CHANGES", "UNUSABLE"})
FEEDBACK_REASONS = frozenset({
    "BRAND_ASSOCIATION", "FACTUAL_ACCURACY", "STRATEGY_TOO_GENERIC", "DRAFT_QUALITY",
    "EVIDENCE_LIMITATION", "OPERABILITY", "OTHER",
})
ADOPTION_STATUSES = frozenset({"ADOPTED", "PARTIALLY_ADOPTED", "NOT_ADOPTED", "UNKNOWN"})
MODIFICATION_LEVELS = frozenset({"NONE", "LIGHT", "MEDIUM", "HEAVY", "NOT_RECORDED"})
ARTIFACT_TYPES = frozenset({"HELP_DOC", "FAQ"})
ARTIFACT_STATUSES = frozenset({"SUCCESS", "FAILED"})


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _instruction_bundle() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[4] / "docs" / "geo-agent-v1" / "frozen" / "agent"
    names = ("AGENT_SYSTEM.md", "GEO_PLAYBOOK.md", "DELIVERY_QA.md")
    files = []
    for name in names:
        text = (root / name).read_text(encoding="utf-8")
        files.append({"name": name, "content": text, "content_hash": digest(text)})
    return {"contract_version": "geo.agent.instructions.v1", "files": files,
            "bundle_hash": digest([{key: row[key] for key in ("name", "content_hash")} for row in files])}


def _requested_artifact_types(values: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized = []
    for value in values or ["HELP_DOC"]:
        item = str(value).upper()
        if item not in ARTIFACT_TYPES:
            raise HTTPException(422, {"code": "AGENT_ARTIFACT_TYPE_INVALID", "value": item})
        if item not in normalized:
            normalized.append(item)
    if not normalized or len(normalized) > 2:
        raise HTTPException(422, {"code": "AGENT_ARTIFACT_SELECTION_INVALID"})
    return [value for value in ("HELP_DOC", "FAQ") if value in normalized]


def _execution_profile(*, regenerate_nonce: str | None = None,
                       execution_mode: str = "TOOL_LOOP",
                       requested_artifact_types: list[str] | None = None) -> dict[str, Any]:
    if execution_mode not in EXECUTION_MODES:
        raise HTTPException(422, {"code": "AGENT_EXECUTION_MODE_INVALID"})
    if execution_mode == "EVIDENCE_PACK":
        return {
            "contract_version": "geo.evidence-pack.execution.v10",
            "execution_mode": "EVIDENCE_PACK",
            "decision_contract": "ONE_MARKDOWN_SYNTHESIS_NO_TOOLS",
            "model_profile": {
                "provider": "deepseek", "model": "deepseek-flash", "mode": "CACHE_ONLY",
                "prompt_version": "geo-evidence-pack-synthesis.v8",
                "response_transport": "geo.deepseek.responses-text.no-thinking.v2",
                "reasoning_effort": "none",
                "max_model_calls": 1, "automatic_retries": 0,
            },
            "evidence_pack_contract": "geo.evidence-pack.v3",
            "result_contract": "geo.evidence-pack.markdown-result.v2",
            "requested_artifact_types": _requested_artifact_types(requested_artifact_types),
            "tool_allowlist": [],
            "regenerate_nonce": regenerate_nonce,
        }
    return {
        "contract_version": "geo.agent.execution.v3",
        "execution_mode": "TOOL_LOOP",
        "decision_contract": "MODEL_CHOOSES_TOOL_OR_FINAL_EACH_TURN",
        "model_profile": {"provider": "deepseek", "model": "deepseek-flash", "mode": "CACHE_ONLY",
                          "response_recovery": "EXACT_TOP_LEVEL_DECISION_THEN_STRICT_VALIDATE",
                          "provider_schema_strict": True,
                          "single_decision_prompt_contract": "geo.agent.single-decision.v2",
                          "response_transport":
                              "geo.agent.deepseek.responses-json-schema.single-decision.v1",
                          "tool_transport_adapter": "geo.agent.deepseek-dsml-agent-decision.v2",
                          "stateless_context_replay": "geo.agent.loop-input.v3",
                          "observation_deduplication": "geo.agent.observation-key.v1",
                          "finalization_reserved_calls": 2},
        "instructions": _instruction_bundle(),
        "tool_allowlist": ["get_scope_summary", "list_runs", "read_answer", "list_citations", "read_source",
                           "read_brand_context", "read_product_truth", "read_monitor_metrics", "save_working_note"],
        "regenerate_nonce": regenerate_nonce,
    }


def create_agent_run(
    db: Session, *, project_id: int, prompt_id: int, analysis_id: str, context_id: str,
    idempotency_key: str, requested_by: str, citation_manifest_id: str | None = None,
    citation_manifest_hash: str | None = None, completion_manifest_id: str | None = None,
    completion_manifest_hash: str | None = None, brand_context_version_id: str | None = None,
    regenerate_nonce: str | None = None, budget: dict[str, Any] | None = None,
    execution_mode: str = "TOOL_LOOP",
    requested_artifact_types: list[str] | None = None,
) -> tuple[AgentExperimentRun, bool]:
    if execution_mode not in EXECUTION_MODES:
        raise HTTPException(422, {"code": "AGENT_EXECUTION_MODE_INVALID"})
    requested_artifacts = _requested_artifact_types(requested_artifact_types)
    request_identity = {
        "project_id": project_id, "prompt_id": prompt_id, "analysis_id": analysis_id, "context_id": context_id,
        "citation_manifest_id": citation_manifest_id, "citation_manifest_hash": citation_manifest_hash,
        "completion_manifest_id": completion_manifest_id, "completion_manifest_hash": completion_manifest_hash,
        "brand_context_version_id": brand_context_version_id, "regenerate_nonce": regenerate_nonce,
        "execution_mode": execution_mode,
        "requested_artifact_types": requested_artifacts,
    }
    request_hash = digest(request_identity)
    existing = db.query(AgentExperimentRun).filter_by(project_id=project_id, idempotency_key=idempotency_key).one_or_none()
    if existing:
        if loads(existing.progress_json, {}).get("request_hash") != request_hash:
            raise HTTPException(409, {"code": "AGENT_IDEMPOTENCY_MISMATCH", "message": "幂等键已用于不同实验输入"})
        return existing, False

    execution = _execution_profile(
        regenerate_nonce=regenerate_nonce, execution_mode=execution_mode,
        requested_artifact_types=requested_artifacts)
    defaults = EVIDENCE_PACK_BUDGET if execution_mode == "EVIDENCE_PACK" else DEFAULT_BUDGET
    effective_budget = {**defaults, **(budget or {})}
    if execution_mode == "EVIDENCE_PACK" and (
        effective_budget["max_model_calls"] != 1
        or effective_budget["max_tool_calls"] != 0
        or effective_budget["max_repairs"] != 0
    ):
        raise HTTPException(422, {"code": "EVIDENCE_PACK_SINGLE_CALL_BUDGET_REQUIRED"})
    for key, upper in (("max_model_calls", 12), ("max_tool_calls", 30), ("max_total_tokens", 300_000),
                       ("max_elapsed_seconds", 900), ("max_repairs", 2)):
        value = effective_budget.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > upper:
            raise HTTPException(422, {"code": "AGENT_BUDGET_INVALID", "field": key})
    if not isinstance(effective_budget.get("max_cost_cny"), (int, float)) or not 0 <= effective_budget["max_cost_cny"] <= 50:
        raise HTTPException(422, {"code": "AGENT_BUDGET_INVALID", "field": "max_cost_cny"})

    try:
        scope, qualification_hash = freeze_scope(
            db, project_id=project_id, prompt_id=prompt_id, analysis_id=analysis_id, context_id=context_id,
            citation_manifest_id=citation_manifest_id, citation_manifest_hash=citation_manifest_hash,
            completion_manifest_id=completion_manifest_id, completion_manifest_hash=completion_manifest_hash,
            brand_context_version_id=brand_context_version_id,
        )
    except HTTPException as exc:
        # Record same-project identity/hash failures as a terminal audit row. A
        # missing or cross-project anchor is still rejected without disclosing it.
        analysis = db.query(SinglePromptAnalysis).filter_by(
            analysis_id=analysis_id, project_id=project_id, prompt_id=prompt_id).one_or_none()
        context = db.query(SinglePromptAnalysisContext).filter_by(
            context_id=context_id, analysis_id=analysis_id,
            project_id=project_id, prompt_id=prompt_id).one_or_none()
        if exc.status_code != 409 or not analysis or not context:
            raise
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "AGENT_IDENTITY_BLOCKED", "message": str(exc.detail)}
        qualification = {"contract_version": "SC-GRADED-DELIVERY-001", "state": "BLOCKED_IDENTITY",
                         "error_code": str(detail.get("code") or "AGENT_IDENTITY_BLOCKED")}
        scope = {"contract_version": "geo.agent.blocked-input.v1", "requested_identity": request_identity,
                 "qualification": qualification, "error": detail}
        scope_hash = digest(scope)
        execution_hash = digest(execution)
        row = AgentExperimentRun(
            run_id=f"agent-run-{uuid4()}", project_id=project_id, prompt_id=prompt_id,
            analysis_id=analysis_id, context_id=context_id, idempotency_key=idempotency_key,
            requested_by=requested_by, input_scope_json=_canonical(scope), input_scope_hash=scope_hash,
            agent_execution_json=_canonical(execution), agent_execution_hash=execution_hash,
            qualification_hash=digest(qualification), authorization_json=_canonical({"mode": "CACHE_ONLY"}),
            budget_json=_canonical(effective_budget), progress_json=_canonical({
                "request_hash": request_hash, "phase": "BLOCKED", "last_checkpoint_sequence": 0,
            }), status="BLOCKED", blocker_code=qualification["error_code"],
            blocker_detail=str(detail.get("message") or detail), finished_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row, True
    scope = {**scope, "requested_artifact_types": requested_artifacts}
    scope_hash = digest(scope)
    execution_hash = digest(execution)
    exact = db.query(AgentExperimentRun).filter_by(
        project_id=project_id, input_scope_hash=scope_hash, agent_execution_hash=execution_hash,
    ).one_or_none()
    if exact:
        return exact, False
    row = AgentExperimentRun(
        run_id=f"agent-run-{uuid4()}", project_id=project_id, prompt_id=prompt_id,
        analysis_id=analysis_id, context_id=context_id, idempotency_key=idempotency_key,
        requested_by=requested_by, input_scope_json=_canonical(scope), input_scope_hash=scope_hash,
        agent_execution_json=_canonical(execution), agent_execution_hash=execution_hash,
        qualification_hash=qualification_hash, authorization_json=_canonical({"mode": "CACHE_ONLY"}),
        budget_json=_canonical(effective_budget), progress_json=_canonical({
            "request_hash": request_hash, "phase": "QUEUED", "last_checkpoint_sequence": 0,
        }), status="QUEUED",
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.query(AgentExperimentRun).filter_by(project_id=project_id, idempotency_key=idempotency_key).one_or_none()
        if concurrent and loads(concurrent.progress_json, {}).get("request_hash") == request_hash:
            return concurrent, False
        raise
    db.refresh(row)
    return row, True


def run_view(row: AgentExperimentRun, *, include_scope: bool = False) -> dict[str, Any]:
    execution = loads(row.agent_execution_json, {})
    value = {
        "run_id": row.run_id, "project_id": row.project_id, "prompt_id": row.prompt_id,
        "analysis_id": row.analysis_id, "context_id": row.context_id,
        "input_scope_hash": row.input_scope_hash, "agent_execution_hash": row.agent_execution_hash,
        "qualification_hash": row.qualification_hash,
        "execution_mode": execution.get("execution_mode", "TOOL_LOOP"),
        "status": row.status, "revision": row.revision,
        "blocker": ({"code": row.blocker_code, "detail": row.blocker_detail} if row.blocker_code else None),
        "usage": {"model_calls": row.model_call_count, "tool_calls": row.tool_call_count,
                  "input_tokens": row.input_tokens, "output_tokens": row.output_tokens, "cost_cny": row.cost_cny,
                  "reserved_requests": int(loads(row.authorization_json, {}).get("reserved_requests", 0)),
                  "reserved_tokens": int(loads(row.authorization_json, {}).get("reserved_tokens", 0)),
                  "reserved_cost_cny": float(loads(row.authorization_json, {}).get("reserved_cost_cny", 0.0))},
        "budget": loads(row.budget_json, {}), "authorization": loads(row.authorization_json, {}),
        "progress": loads(row.progress_json, {}), "created_at": row.created_at.isoformat(),
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "allowed_operations": (["VIEW", "CANCEL"] if row.status in {"QUEUED", "RUNNING"}
                               else ["VIEW", "AUTHORIZE"] if row.status == "WAITING_AUTHORIZATION" else ["VIEW"]),
    }
    if include_scope:
        value["input_scope"] = loads(row.input_scope_json, {})
        value["agent_execution"] = loads(row.agent_execution_json, {})
    return value


def get_agent_run(db: Session, *, run_id: str, project_id: int, prompt_id: int) -> dict[str, Any]:
    row = db.query(AgentExperimentRun).filter_by(
        run_id=run_id, project_id=project_id, prompt_id=prompt_id).one_or_none()
    if not row:
        raise HTTPException(404, "Agent 实验运行不存在")
    result = db.query(AgentResultVersion).filter_by(agent_run_id=run_id).order_by(
        AgentResultVersion.version_number.desc()).first()
    events = db.query(AgentEvent).filter_by(agent_run_id=run_id).order_by(AgentEvent.sequence_number).all()
    return {**run_view(row, include_scope=True),
            "result": (result_view(result, db=db) if result else None),
            "events": [{"event_id": event.event_id, "sequence_number": event.sequence_number,
                        "event_type": event.event_type, "payload": loads(event.payload_json, {}),
                        "payload_hash": event.payload_hash, "created_at": event.created_at.isoformat()} for event in events]}


def list_agent_results(db: Session, *, run_id: str, project_id: int, prompt_id: int) -> list[dict[str, Any]]:
    run = db.query(AgentExperimentRun).filter_by(
        run_id=run_id, project_id=project_id, prompt_id=prompt_id).one_or_none()
    if not run:
        raise HTTPException(404, "AI 优化任务不存在")
    rows = db.query(AgentResultVersion).filter_by(agent_run_id=run_id).order_by(
        AgentResultVersion.version_number.desc()).all()
    return [result_view(row, db=db) for row in rows]


def feedback_view(row: AgentResultFeedback) -> dict[str, Any]:
    return {
        "feedback_id": row.feedback_id, "agent_run_id": row.agent_run_id,
        "result_version": row.result_version, "project_id": row.project_id,
        "prompt_id": row.prompt_id, "submitted_by": row.submitted_by,
        "rating": row.rating, "reason_tags": loads(row.reason_tags_json, []),
        "suggestion": row.suggestion, "adoption_status": row.adoption_status,
        "modification_level": row.modification_level,
        "modification_summary": row.modification_summary,
        "payload_hash": row.payload_hash, "created_at": row.created_at.isoformat(),
    }


def list_result_feedback(db: Session, *, run_id: str, project_id: int, prompt_id: int,
                         result_version: str | None = None) -> list[dict[str, Any]]:
    run = db.query(AgentExperimentRun).filter_by(
        run_id=run_id, project_id=project_id, prompt_id=prompt_id).one_or_none()
    if not run:
        raise HTTPException(404, "AI 优化任务不存在")
    query = db.query(AgentResultFeedback).filter_by(
        agent_run_id=run_id, project_id=project_id, prompt_id=prompt_id)
    if result_version:
        result = db.query(AgentResultVersion).filter_by(
            agent_run_id=run_id, result_version=result_version).one_or_none()
        if not result:
            raise HTTPException(404, "结果版本不存在或不属于当前任务")
        query = query.filter_by(result_version=result_version)
    return [feedback_view(row) for row in query.order_by(AgentResultFeedback.created_at.desc()).all()]


def add_result_feedback(
    db: Session, *, run_id: str, project_id: int, prompt_id: int, result_version: str,
    submitted_by: str, rating: str, reason_tags: list[str], suggestion: str,
    adoption_status: str, modification_level: str, modification_summary: str,
) -> AgentResultFeedback:
    run = db.query(AgentExperimentRun).filter_by(
        run_id=run_id, project_id=project_id, prompt_id=prompt_id).one_or_none()
    if not run:
        raise HTTPException(404, "AI 优化任务不存在")
    result = db.query(AgentResultVersion).filter_by(
        agent_run_id=run_id, result_version=result_version).one_or_none()
    if not result:
        raise HTTPException(404, "结果版本不存在或不属于当前任务")
    normalized_reasons = sorted(set(reason_tags))
    if rating not in FEEDBACK_RATINGS or any(value not in FEEDBACK_REASONS for value in normalized_reasons):
        raise HTTPException(422, "反馈结论或原因标签无效")
    if adoption_status not in ADOPTION_STATUSES or modification_level not in MODIFICATION_LEVELS:
        raise HTTPException(422, "采用状态或修改量无效")
    payload = {
        "contract_version": "geo.internal-beta.result-feedback.v1",
        "agent_run_id": run_id, "result_version": result_version,
        "project_id": project_id, "prompt_id": prompt_id,
        "submitted_by": submitted_by, "rating": rating,
        "reason_tags": normalized_reasons, "suggestion": suggestion.strip(),
        "adoption_status": adoption_status, "modification_level": modification_level,
        "modification_summary": modification_summary.strip(),
    }
    row = AgentResultFeedback(
        feedback_id=f"agent-feedback-{uuid4()}", agent_run_id=run_id,
        result_version=result_version, project_id=project_id, prompt_id=prompt_id,
        submitted_by=submitted_by, rating=rating,
        reason_tags_json=_canonical(normalized_reasons), suggestion=payload["suggestion"],
        adoption_status=adoption_status, modification_level=modification_level,
        modification_summary=payload["modification_summary"], payload_hash=digest(payload),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_agent_runs(db: Session, *, project_id: int, prompt_id: int, analysis_id: str | None = None) -> list[dict[str, Any]]:
    query = db.query(AgentExperimentRun).filter_by(project_id=project_id, prompt_id=prompt_id)
    if analysis_id:
        query = query.filter_by(analysis_id=analysis_id)
    return [run_view(row) for row in query.order_by(AgentExperimentRun.created_at.desc()).limit(100)]


def compare_with_workflow(db: Session, *, run_id: str, project_id: int, prompt_id: int) -> dict[str, Any]:
    agent = db.query(AgentExperimentRun).filter_by(
        run_id=run_id, project_id=project_id, prompt_id=prompt_id).one_or_none()
    if not agent:
        raise HTTPException(404, "Agent 实验运行不存在")
    scope = loads(agent.input_scope_json, {})
    identity = scope.get("identity") or {}
    run_ids = [int(value) for value in (scope.get("run_scope") or {}).get("run_ids", [])]
    rows = db.query(SinglePromptOptimizationTask).filter_by(
        analysis_id=agent.analysis_id, context_id=agent.context_id,
        project_id=project_id, prompt_id=prompt_id,
    ).order_by(SinglePromptOptimizationTask.created_at.desc()).all()
    workflow = []
    for row in rows:
        frozen = loads(row.input_json, {})
        formal_run_ids = [int(value) for value in frozen.get("run_ids", [])]
        formal_raw_hash = str(frozen.get("raw_output_hash") or "")
        workflow.append({
            "task_id": row.task_id, "status": row.status, "input_hash": row.input_hash,
            "run_ids": formal_run_ids, "raw_output_hash": formal_raw_hash,
            "same_frozen_input": formal_run_ids == run_ids and formal_raw_hash == identity.get("raw_output_hash"),
            "usage": loads(row.progress_json, {}).get("usage") or {},
            "objects": loads(row.progress_json, {}).get("objects") or {},
        })
    result = db.query(AgentResultVersion).filter_by(agent_run_id=run_id).order_by(
        AgentResultVersion.version_number.desc()).first()
    return {
        "comparison_contract": "geo.agent.same-input-comparison.v1",
        "agent": {"run_id": agent.run_id, "status": agent.status, "run_ids": run_ids,
                  "raw_output_hash": identity.get("raw_output_hash"),
                  "usage": run_view(agent)["usage"], "result": result_view(result, db=db) if result else None},
        "workflow": workflow,
        "same_input_workflow_count": sum(bool(row["same_frozen_input"]) for row in workflow),
        "limitations": ["该视图只比较同一冻结输入的过程、交付和用量，不把单次差异解释为因果效果。"],
    }


def result_view(row: AgentResultVersion, *, db: Session | None = None) -> dict[str, Any]:
    artifacts = list_draft_artifacts_for_result(db, row.result_version) if db is not None else []
    delivery_status = draft_delivery_status(artifacts)
    return {"result_version": row.result_version, "version_number": row.version_number,
            "input_scope_hash": row.input_scope_hash, "agent_execution_hash": row.agent_execution_hash,
            "qualification_hash": row.qualification_hash, "plan_hash": row.plan_hash,
            "result_hash": row.result_hash, "binding": loads(row.plan_result_binding_json, {}),
            "evidence_grade": row.evidence_grade, "public_claim_eligibility": row.public_claim_eligibility,
            "publication_eligibility": row.publication_eligibility, "result": loads(row.result_json, {}),
            "deliverable_markdown": row.deliverable_markdown,
            "validation": loads(row.validation_report_json, {}),
            "draft_delivery_status": delivery_status, "draft_artifacts": artifacts,
            "legacy_single_draft": delivery_status == "LEGACY_SINGLE_DRAFT",
            "created_at": row.created_at.isoformat()}


def draft_delivery_status(artifacts: list[dict[str, Any]]) -> str:
    """Derive the parent delivery state without mutating its frozen result."""
    if not artifacts:
        return "LEGACY_SINGLE_DRAFT"
    latest: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        current = latest.get(str(artifact["artifact_id"]))
        if current is None or int(artifact["version_number"]) > int(current["version_number"]):
            latest[str(artifact["artifact_id"])] = artifact
    statuses = {str(row["status"]) for row in latest.values()}
    if statuses == {"SUCCESS"}:
        return "SUCCESS"
    if "SUCCESS" in statuses:
        return "PARTIAL_SUCCESS"
    return "FAILED"


def draft_artifact_view(row: AgentDraftArtifactVersion) -> dict[str, Any]:
    return {
        "artifact_version": row.artifact_version, "artifact_id": row.artifact_id,
        "parent_result_version": row.parent_result_version, "agent_run_id": row.agent_run_id,
        "project_id": row.project_id, "prompt_id": row.prompt_id,
        "source_deliverable_id": row.source_deliverable_id,
        "version_number": row.version_number,
        "previous_artifact_version": row.previous_artifact_version,
        "artifact_type": row.artifact_type, "status": row.status,
        "title": row.title, "body_markdown": row.body_markdown,
        "action_ids": loads(row.action_ids_json, []),
        "editorial_notes": loads(row.editorial_notes_json, []),
        "evidence": loads(row.evidence_json, {}), "evidence_hash": row.evidence_hash,
        "qa": loads(row.qa_json, {}), "qa_hash": row.qa_hash,
        "input_hash": row.input_hash, "artifact_hash": row.artifact_hash,
        "failure": ({"code": row.failure_code, "detail": row.failure_detail}
                    if row.failure_code else None),
        "created_by": row.created_by, "created_at": row.created_at.isoformat(),
    }


def list_draft_artifacts_for_result(db: Session, result_version: str) -> list[dict[str, Any]]:
    rows = db.query(AgentDraftArtifactVersion).filter_by(
        parent_result_version=result_version).order_by(
        AgentDraftArtifactVersion.artifact_id,
        AgentDraftArtifactVersion.version_number.desc()).all()
    return [draft_artifact_view(row) for row in rows]


def _artifact_evidence(
    result: dict[str, Any], action_ids: list[str], artifact_type: str,
) -> dict[str, Any]:
    actions = {str(row.get("id")): row for row in (result.get("actions") or [])
               if isinstance(row, dict) and row.get("id") is not None}
    action_refs = []
    for action_id in action_ids:
        action = actions.get(str(action_id)) or {}
        action_refs.extend(action.get("evidence_refs") or [])
    artifact_sections = {"HELP_DOC": "帮助文档", "FAQ": "常见问题"}
    own_section = artifact_sections.get(str(artifact_type).upper())
    result_refs = [
        row for row in (result.get("evidence_references") or [])
        if not isinstance(row, dict)
        or row.get("section") not in set(artifact_sections.values())
        or row.get("section") == own_section
    ]
    return {
        "contract_version": "geo.draft-artifact.evidence.v1",
        "action_ids": action_ids,
        "action_evidence_refs": action_refs,
        "result_evidence_references": result_refs,
        "evidence_pack_hash": ((result.get("evidence_pack") or {}).get("evidence_pack_hash")),
    }


def _new_artifact_row(
    *, parent: AgentResultVersion, run: AgentExperimentRun, deliverable: dict[str, Any],
    version_number: int, artifact_id: str, previous_artifact_version: str | None,
    created_by: str, input_hash: str,
) -> AgentDraftArtifactVersion:
    artifact_type = str(deliverable.get("asset_type") or "").upper()
    action_ids = [str(value) for value in (deliverable.get("action_ids") or [])]
    evidence = deliverable.get("evidence") or {}
    qa = deliverable.get("qa") or {}
    body = str(deliverable.get("body_markdown") or "")
    title = str(deliverable.get("title") or "")
    failure_code = ""
    failure_detail = ""
    if artifact_type not in ARTIFACT_TYPES:
        failure_code, failure_detail = "ARTIFACT_TYPE_NOT_ALLOWED", artifact_type or "MISSING"
    elif not body.strip():
        failure_code, failure_detail = "ARTIFACT_BODY_REQUIRED", "稿件正文为空"
    elif (deliverable.get("artifact_validation") or {}).get("status") == "FAIL":
        failure_code = "ARTIFACT_VALIDATION_FAILED"
        failure_detail = _canonical((deliverable.get("artifact_validation") or {}).get("issues") or [])
    status = "FAILED" if failure_code else "SUCCESS"
    payload = {
        "contract_version": "geo.draft-artifact.version.v1",
        "artifact_id": artifact_id, "parent_result_version": parent.result_version,
        "version_number": version_number, "previous_artifact_version": previous_artifact_version,
        "artifact_type": artifact_type, "status": status, "title": title,
        "body_markdown": body, "action_ids": action_ids,
        "editorial_notes": deliverable.get("editorial_notes") or [],
        "evidence": evidence, "qa": qa, "failure_code": failure_code,
    }
    return AgentDraftArtifactVersion(
        artifact_version=f"{artifact_id}:v{version_number}", artifact_id=artifact_id,
        parent_result_version=parent.result_version, agent_run_id=run.run_id,
        project_id=run.project_id, prompt_id=run.prompt_id,
        source_deliverable_id=str(deliverable.get("id") or artifact_id),
        version_number=version_number, previous_artifact_version=previous_artifact_version,
        artifact_type=artifact_type or "UNKNOWN", status=status, title=title,
        body_markdown=body, action_ids_json=_canonical(action_ids),
        editorial_notes_json=_canonical(deliverable.get("editorial_notes") or []),
        evidence_json=_canonical(evidence), evidence_hash=digest(evidence),
        qa_json=_canonical(qa), qa_hash=digest(qa), input_hash=input_hash,
        artifact_hash=digest(payload), failure_code=failure_code,
        failure_detail=failure_detail, created_by=created_by,
    )


def materialize_result_draft_artifacts(
    db: Session, *, parent: AgentResultVersion, run: AgentExperimentRun,
    result: dict[str, Any], validation: dict[str, Any],
) -> list[AgentDraftArtifactVersion]:
    """Persist explicit typed deliverables; untyped historical results stay legacy-readable."""
    created: list[AgentDraftArtifactVersion] = []
    for index, raw in enumerate(result.get("deliverables") or [], start=1):
        if not isinstance(raw, dict) or not raw.get("asset_type"):
            continue
        source_id = str(raw.get("id") or f"deliverable-{index}")
        artifact_id = f"draft-artifact-{digest({'parent': parent.result_version, 'slot': source_id})[:40]}"
        action_ids = [str(value) for value in (raw.get("action_ids") or [])]
        artifact_validation = raw.get("artifact_validation") or {
            "status": "FAIL",
            "issues": [{"code": "ARTIFACT_VALIDATION_MISSING",
                        "detail": "生成结果缺少单资产服务端校验"}],
        }
        deliverable = {
            **raw,
            "id": source_id,
            "evidence": _artifact_evidence(result, action_ids, str(raw.get("asset_type") or "")),
            "artifact_validation": artifact_validation,
            "qa": {"result_qa": result.get("qa_self_check", result.get("qa", {})),
                   "artifact_validation": artifact_validation,
                   "parent_validation": validation},
        }
        input_hash = digest({"parent_result_hash": parent.result_hash,
                             "source_deliverable_id": source_id,
                             "artifact_type": raw.get("asset_type"),
                             "action_ids": action_ids})
        child = _new_artifact_row(
            parent=parent, run=run, deliverable=deliverable, version_number=1,
            artifact_id=artifact_id, previous_artifact_version=None,
            created_by=run.requested_by, input_hash=input_hash)
        db.add(child)
        created.append(child)
    return created


def get_draft_artifact(
    db: Session, *, artifact_version: str, project_id: int, prompt_id: int,
) -> AgentDraftArtifactVersion:
    row = db.query(AgentDraftArtifactVersion).filter_by(
        artifact_version=artifact_version, project_id=project_id, prompt_id=prompt_id).one_or_none()
    if not row:
        raise HTTPException(404, "稿件版本不存在或不属于当前项目范围")
    return row


def list_draft_artifacts(
    db: Session, *, run_id: str, project_id: int, prompt_id: int,
    result_version: str | None = None,
) -> list[dict[str, Any]]:
    run = db.query(AgentExperimentRun).filter_by(
        run_id=run_id, project_id=project_id, prompt_id=prompt_id).one_or_none()
    if not run:
        raise HTTPException(404, "AI 优化任务不存在")
    query = db.query(AgentDraftArtifactVersion).filter_by(
        agent_run_id=run_id, project_id=project_id, prompt_id=prompt_id)
    if result_version:
        parent = db.query(AgentResultVersion).filter_by(
            agent_run_id=run_id, result_version=result_version).one_or_none()
        if not parent:
            raise HTTPException(404, "结果版本不存在或不属于当前任务")
        query = query.filter_by(parent_result_version=result_version)
    return [draft_artifact_view(row) for row in query.order_by(
        AgentDraftArtifactVersion.created_at.desc()).all()]


def draft_artifact_export(
    db: Session, *, artifact_version: str, project_id: int, prompt_id: int,
) -> dict[str, Any]:
    row = get_draft_artifact(db, artifact_version=artifact_version,
                             project_id=project_id, prompt_id=prompt_id)
    if row.status != "SUCCESS":
        raise HTTPException(409, {"code": "DRAFT_ARTIFACT_NOT_EXPORTABLE", "status": row.status})
    return {
        "artifact_version": row.artifact_version, "artifact_hash": row.artifact_hash,
        "media_type": "text/markdown; charset=utf-8",
        "filename": f"{row.artifact_type.lower()}-{row.artifact_version.replace(':', '-')}.md",
        "content": row.body_markdown,
    }


def draft_artifact_feedback_view(row: AgentDraftArtifactFeedback) -> dict[str, Any]:
    return {
        "feedback_id": row.feedback_id, "artifact_version": row.artifact_version,
        "parent_result_version": row.parent_result_version, "agent_run_id": row.agent_run_id,
        "project_id": row.project_id, "prompt_id": row.prompt_id,
        "submitted_by": row.submitted_by, "rating": row.rating,
        "reason_tags": loads(row.reason_tags_json, []), "suggestion": row.suggestion,
        "adoption_status": row.adoption_status, "modification_level": row.modification_level,
        "modification_summary": row.modification_summary, "payload_hash": row.payload_hash,
        "created_at": row.created_at.isoformat(),
    }


def add_draft_artifact_feedback(
    db: Session, *, artifact_version: str, project_id: int, prompt_id: int,
    submitted_by: str, rating: str, reason_tags: list[str], suggestion: str,
    adoption_status: str, modification_level: str, modification_summary: str,
) -> AgentDraftArtifactFeedback:
    artifact = get_draft_artifact(db, artifact_version=artifact_version,
                                  project_id=project_id, prompt_id=prompt_id)
    normalized_reasons = sorted(set(reason_tags))
    if rating not in FEEDBACK_RATINGS or any(value not in FEEDBACK_REASONS for value in normalized_reasons):
        raise HTTPException(422, "反馈结论或原因标签无效")
    if adoption_status not in ADOPTION_STATUSES or modification_level not in MODIFICATION_LEVELS:
        raise HTTPException(422, "采用状态或修改量无效")
    payload = {
        "contract_version": "geo.internal-beta.draft-artifact-feedback.v1",
        "artifact_version": artifact_version, "parent_result_version": artifact.parent_result_version,
        "project_id": project_id, "prompt_id": prompt_id, "submitted_by": submitted_by,
        "rating": rating, "reason_tags": normalized_reasons, "suggestion": suggestion.strip(),
        "adoption_status": adoption_status, "modification_level": modification_level,
        "modification_summary": modification_summary.strip(),
    }
    row = AgentDraftArtifactFeedback(
        feedback_id=f"draft-feedback-{uuid4()}", artifact_version=artifact_version,
        parent_result_version=artifact.parent_result_version, agent_run_id=artifact.agent_run_id,
        project_id=project_id, prompt_id=prompt_id, submitted_by=submitted_by,
        rating=rating, reason_tags_json=_canonical(normalized_reasons),
        suggestion=payload["suggestion"], adoption_status=adoption_status,
        modification_level=modification_level,
        modification_summary=payload["modification_summary"], payload_hash=digest(payload))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_draft_artifact_feedback(
    db: Session, *, artifact_version: str, project_id: int, prompt_id: int,
) -> list[dict[str, Any]]:
    get_draft_artifact(db, artifact_version=artifact_version,
                       project_id=project_id, prompt_id=prompt_id)
    rows = db.query(AgentDraftArtifactFeedback).filter_by(
        artifact_version=artifact_version, project_id=project_id, prompt_id=prompt_id).order_by(
        AgentDraftArtifactFeedback.created_at.desc()).all()
    return [draft_artifact_feedback_view(row) for row in rows]


def queue_draft_artifact_regeneration(
    db: Session, *, artifact_version: str, project_id: int, prompt_id: int,
    idempotency_key: str, requested_by: str, server_policy: dict[str, Any],
) -> tuple[AgentDraftArtifactRegeneration, bool]:
    source = get_draft_artifact(db, artifact_version=artifact_version,
                                project_id=project_id, prompt_id=prompt_id)
    execution = _execution_profile(
        execution_mode="EVIDENCE_PACK",
        requested_artifact_types=[source.artifact_type],
    )
    generation_profile = {
        "execution_contract": execution["contract_version"],
        "prompt_version": execution["model_profile"]["prompt_version"],
        "validation_contract": "geo.evidence-pack.validation.v4",
    }
    frozen_policy = {**server_policy, "generation_profile": generation_profile}
    request_payload = {
        "contract_version": "geo.draft-artifact.regeneration-request.v1",
        "source_artifact_version": artifact_version,
        "parent_result_version": source.parent_result_version,
        "project_id": project_id, "prompt_id": prompt_id,
        "server_policy": frozen_policy,
    }
    request_hash = digest(request_payload)
    existing = db.query(AgentDraftArtifactRegeneration).filter_by(
        project_id=project_id, idempotency_key=idempotency_key).one_or_none()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, {"code": "DRAFT_REGENERATION_IDEMPOTENCY_MISMATCH"})
        return existing, False
    row = AgentDraftArtifactRegeneration(
        request_id=f"draft-regeneration-{uuid4()}", idempotency_key=idempotency_key,
        source_artifact_version=artifact_version,
        parent_result_version=source.parent_result_version, agent_run_id=source.agent_run_id,
        project_id=project_id, prompt_id=prompt_id, requested_by=requested_by,
        request_hash=request_hash, server_policy_json=_canonical(frozen_policy), status="QUEUED")
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.query(AgentDraftArtifactRegeneration).filter_by(
            project_id=project_id, idempotency_key=idempotency_key).one_or_none()
        if concurrent and concurrent.request_hash == request_hash:
            return concurrent, False
        raise
    db.refresh(row)
    return row, True


def draft_artifact_regeneration_view(row: AgentDraftArtifactRegeneration) -> dict[str, Any]:
    return {
        "request_id": row.request_id, "source_artifact_version": row.source_artifact_version,
        "target_artifact_version": row.target_artifact_version,
        "parent_result_version": row.parent_result_version, "agent_run_id": row.agent_run_id,
        "project_id": row.project_id, "prompt_id": row.prompt_id,
        "status": row.status, "attempt_count": row.attempt_count,
        "usage": loads(row.usage_json, {}), "audit": loads(row.audit_json, {}),
        "cancel_requested": row.cancel_requested_at is not None,
        "failure": ({"code": row.failure_code, "detail": row.failure_detail}
                    if row.failure_code else None),
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "updated_at": row.updated_at.isoformat(),
        "created_at": row.created_at.isoformat(),
    }


def get_draft_artifact_regeneration(
    db: Session, *, request_id: str, project_id: int, prompt_id: int,
) -> AgentDraftArtifactRegeneration:
    row = db.query(AgentDraftArtifactRegeneration).filter_by(
        request_id=request_id, project_id=project_id, prompt_id=prompt_id).one_or_none()
    if not row:
        raise HTTPException(404, "稿件重生成任务不存在或不属于当前项目范围")
    return row


def cancel_draft_artifact_regeneration(
    db: Session, *, request_id: str, project_id: int, prompt_id: int,
) -> AgentDraftArtifactRegeneration:
    row = get_draft_artifact_regeneration(
        db, request_id=request_id, project_id=project_id, prompt_id=prompt_id)
    if row.status in {"COMPLETED", "FAILED", "CANCELLED"}:
        return row
    row.cancel_requested_at = datetime.utcnow()
    audit = loads(row.audit_json, {})
    if row.status == "QUEUED":
        row.status = "CANCELLED"
        row.finished_at = datetime.utcnow()
        row.audit_json = _canonical({**audit, "external_request_state": "NOT_SENT",
                                     "cancelled_before_provider": True})
    else:
        row.audit_json = _canonical({**audit, "cancel_requested_while_running": True})
    db.commit()
    db.refresh(row)
    return row


def complete_draft_artifact_regeneration(
    db: Session, *, request_id: str, generated: dict[str, Any], completed_by: str = "worker",
) -> AgentDraftArtifactVersion:
    """Worker-side completion hook; provider execution remains in the existing model lane."""
    request = db.query(AgentDraftArtifactRegeneration).filter_by(request_id=request_id).one_or_none()
    if not request:
        raise HTTPException(404, "稿件重生成请求不存在")
    if request.status == "COMPLETED" and request.target_artifact_version:
        return db.query(AgentDraftArtifactVersion).filter_by(
            artifact_version=request.target_artifact_version).one()
    if request.status not in {"QUEUED", "RUNNING"}:
        raise HTTPException(409, {"code": "DRAFT_REGENERATION_NOT_ACTIVE", "status": request.status})
    source = get_draft_artifact(db, artifact_version=request.source_artifact_version,
                                project_id=request.project_id, prompt_id=request.prompt_id)
    parent = db.query(AgentResultVersion).filter_by(
        result_version=request.parent_result_version, agent_run_id=request.agent_run_id).one()
    run = db.query(AgentExperimentRun).filter_by(
        run_id=request.agent_run_id, project_id=request.project_id,
        prompt_id=request.prompt_id).one()
    if str(generated.get("asset_type") or "").upper() != source.artifact_type:
        raise HTTPException(422, {"code": "DRAFT_REGENERATION_TYPE_MISMATCH"})
    version = db.query(AgentDraftArtifactVersion).filter_by(
        artifact_id=source.artifact_id).count() + 1
    deliverable = {
        **generated, "id": source.source_deliverable_id,
        "asset_type": source.artifact_type,
        "evidence": generated.get("evidence") or loads(source.evidence_json, {}),
        "qa": generated.get("qa") or {},
    }
    child = _new_artifact_row(
        parent=parent, run=run, deliverable=deliverable, version_number=version,
        artifact_id=source.artifact_id, previous_artifact_version=source.artifact_version,
        created_by=completed_by,
        input_hash=digest({"request_hash": request.request_hash,
                           "source_artifact_hash": source.artifact_hash}))
    db.add(child)
    db.flush()
    request.target_artifact_version = child.artifact_version
    request.status = "COMPLETED" if child.status == "SUCCESS" else "FAILED"
    request.failure_code = child.failure_code
    request.failure_detail = child.failure_detail
    request.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(child)
    return child


def cancel_agent_run(db: Session, *, run_id: str, project_id: int, prompt_id: int) -> AgentExperimentRun:
    row = db.query(AgentExperimentRun).filter_by(run_id=run_id, project_id=project_id, prompt_id=prompt_id).one_or_none()
    if not row:
        raise HTTPException(404, "Agent 实验运行不存在")
    if row.status in TERMINAL_STATUSES:
        return row
    row.cancel_requested_at = datetime.utcnow()
    if row.status in {"QUEUED", "WAITING_AUTHORIZATION"}:
        row.status = "CANCELLED"
        row.finished_at = datetime.utcnow()
    row.revision += 1
    db.commit()
    db.refresh(row)
    return row


def authorize_agent_run(db: Session, *, run_id: str, project_id: int, prompt_id: int,
                        revision: int, max_requests: int, max_total_tokens: int, max_cost_cny: float,
                        conservative_cny_per_million_tokens: float, pricing_source: str,
                        pricing_checked_at: str, authorized_by: str) -> AgentExperimentRun:
    row = db.query(AgentExperimentRun).filter_by(run_id=run_id, project_id=project_id, prompt_id=prompt_id).one_or_none()
    if not row:
        raise HTTPException(404, "Agent 实验运行不存在")
    current_authorization = loads(row.authorization_json, {})
    if (row.status not in {"QUEUED", "WAITING_AUTHORIZATION"}
            or current_authorization.get("mode") != "CACHE_ONLY"
            or row.revision != revision):
        raise HTTPException(409, "Agent 状态或 revision 已变化")
    budget = loads(row.budget_json, {})
    if (max_cost_cny <= 0 or max_cost_cny > float(budget.get("max_cost_cny", 0))
            or max_requests <= 0 or max_requests > int(budget.get("max_model_calls", 0))
            or max_total_tokens <= 0 or max_total_tokens > int(budget.get("max_total_tokens", 0))):
        raise HTTPException(422, "模型授权次数、Token 或金额必须在冻结预算内")
    row.authorization_json = _canonical({
        "mode": "EXTERNAL_ALLOWED", "max_requests": max_requests,
        "max_total_tokens": max_total_tokens, "max_cost_cny": max_cost_cny,
        "conservative_cny_per_million_tokens": conservative_cny_per_million_tokens,
        "pricing_source": pricing_source.strip(), "pricing_checked_at": pricing_checked_at,
        "reserved_requests": 0, "reserved_tokens": 0, "reserved_cost_cny": 0.0,
        "authorized_by": authorized_by, "authorized_at": datetime.utcnow().isoformat(),
    })
    row.status = "QUEUED"
    row.blocker_code = ""
    row.blocker_detail = ""
    row.revision += 1
    db.commit()
    db.refresh(row)
    return row
