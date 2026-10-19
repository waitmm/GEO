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
    AgentCheckpoint, AgentEvent, AgentExperimentRun, AgentResultVersion,
    SinglePromptAnalysis, SinglePromptAnalysisContext, SinglePromptOptimizationTask,
)
from app.modules.single_prompt_v2.delivery_text import digest
from app.services.serialization import loads

from .scope import freeze_scope


DEFAULT_BUDGET = {"max_model_calls": 6, "max_tool_calls": 12, "max_total_tokens": 32_000,
                  "max_elapsed_seconds": 300, "max_repairs": 1, "max_cost_cny": 5.0}
TERMINAL_STATUSES = frozenset({"SUCCEEDED", "PARTIAL", "NEEDS_INPUT", "BLOCKED", "FAILED", "CANCELLED"})


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


def _execution_profile(*, regenerate_nonce: str | None = None) -> dict[str, Any]:
    return {
        "contract_version": "geo.agent.execution.v1",
        "decision_contract": "MODEL_CHOOSES_TOOL_OR_FINAL_EACH_TURN",
        "model_profile": {"provider": "deepseek", "model": "deepseek-v4-flash", "mode": "CACHE_ONLY"},
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
) -> tuple[AgentExperimentRun, bool]:
    request_identity = {
        "project_id": project_id, "prompt_id": prompt_id, "analysis_id": analysis_id, "context_id": context_id,
        "citation_manifest_id": citation_manifest_id, "citation_manifest_hash": citation_manifest_hash,
        "completion_manifest_id": completion_manifest_id, "completion_manifest_hash": completion_manifest_hash,
        "brand_context_version_id": brand_context_version_id, "regenerate_nonce": regenerate_nonce,
    }
    request_hash = digest(request_identity)
    existing = db.query(AgentExperimentRun).filter_by(project_id=project_id, idempotency_key=idempotency_key).one_or_none()
    if existing:
        if loads(existing.progress_json, {}).get("request_hash") != request_hash:
            raise HTTPException(409, {"code": "AGENT_IDEMPOTENCY_MISMATCH", "message": "幂等键已用于不同实验输入"})
        return existing, False

    execution = _execution_profile(regenerate_nonce=regenerate_nonce)
    effective_budget = {**DEFAULT_BUDGET, **(budget or {})}
    for key, upper in (("max_model_calls", 12), ("max_tool_calls", 30), ("max_total_tokens", 100_000),
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
    value = {
        "run_id": row.run_id, "project_id": row.project_id, "prompt_id": row.prompt_id,
        "analysis_id": row.analysis_id, "context_id": row.context_id,
        "input_scope_hash": row.input_scope_hash, "agent_execution_hash": row.agent_execution_hash,
        "qualification_hash": row.qualification_hash, "status": row.status, "revision": row.revision,
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
            "result": (result_view(result) if result else None),
            "events": [{"event_id": event.event_id, "sequence_number": event.sequence_number,
                        "event_type": event.event_type, "payload": loads(event.payload_json, {}),
                        "payload_hash": event.payload_hash, "created_at": event.created_at.isoformat()} for event in events]}


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
                  "usage": run_view(agent)["usage"], "result": result_view(result) if result else None},
        "workflow": workflow,
        "same_input_workflow_count": sum(bool(row["same_frozen_input"]) for row in workflow),
        "limitations": ["该视图只比较同一冻结输入的过程、交付和用量，不把单次差异解释为因果效果。"],
    }


def result_view(row: AgentResultVersion) -> dict[str, Any]:
    return {"result_version": row.result_version, "version_number": row.version_number,
            "input_scope_hash": row.input_scope_hash, "agent_execution_hash": row.agent_execution_hash,
            "qualification_hash": row.qualification_hash, "plan_hash": row.plan_hash,
            "result_hash": row.result_hash, "binding": loads(row.plan_result_binding_json, {}),
            "evidence_grade": row.evidence_grade, "public_claim_eligibility": row.public_claim_eligibility,
            "publication_eligibility": row.publication_eligibility, "result": loads(row.result_json, {}),
            "deliverable_markdown": row.deliverable_markdown,
            "validation": loads(row.validation_report_json, {}), "created_at": row.created_at.isoformat()}


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
    if row.status != "WAITING_AUTHORIZATION" or row.revision != revision:
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
