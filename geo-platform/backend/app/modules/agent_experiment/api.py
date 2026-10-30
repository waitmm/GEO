"""Release API for the isolated Agent experiment lane."""

from __future__ import annotations

import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.release_access import authenticated_actor
from app.core.release_database import get_release_db, read_only_release_session
from app.services.internal_beta_model_budget import (
    append_run_authorization,
    server_task_policy,
)
from app.services.shared_model_budget import SharedBudgetDenied

from .service import (
    add_draft_artifact_feedback,
    add_result_feedback,
    authorize_agent_run,
    cancel_agent_run,
    compare_with_workflow,
    create_agent_run,
    draft_artifact_export,
    draft_artifact_feedback_view,
    draft_artifact_regeneration_view,
    draft_artifact_view,
    get_agent_run,
    get_draft_artifact,
    list_draft_artifact_feedback,
    list_draft_artifacts,
    list_agent_results,
    list_agent_runs,
    list_result_feedback,
    feedback_view,
    queue_draft_artifact_regeneration,
    run_view,
)


router = APIRouter(prefix="/api/v2/single-prompt", tags=["geo-agent-experiment-v1"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AgentRunCreate(StrictModel):
    project_id: int = Field(gt=0)
    prompt_id: int = Field(gt=0)
    context_id: str = Field(min_length=1, max_length=80)
    citation_manifest_id: str | None = Field(default=None, max_length=80)
    citation_manifest_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    completion_manifest_id: str | None = Field(default=None, max_length=80)
    completion_manifest_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    brand_context_version_id: str | None = Field(default=None, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=120)
    regenerate_nonce: str | None = Field(default=None, min_length=8, max_length=80)
    execution_mode: Literal["TOOL_LOOP", "EVIDENCE_PACK"] = "EVIDENCE_PACK"
    requested_artifact_types: list[Literal["HELP_DOC", "FAQ"]] = Field(
        default_factory=lambda: ["HELP_DOC"], min_length=1, max_length=2)


class AgentScopeAction(StrictModel):
    project_id: int = Field(gt=0)
    prompt_id: int = Field(gt=0)


class AgentServerQueue(AgentScopeAction):
    revision: int = Field(gt=0)


class AgentResultFeedbackCreate(AgentScopeAction):
    result_version: str = Field(min_length=1, max_length=96)
    rating: Literal["USABLE", "NEEDS_CHANGES", "UNUSABLE"]
    reason_tags: list[Literal[
        "BRAND_ASSOCIATION", "FACTUAL_ACCURACY", "STRATEGY_TOO_GENERIC", "DRAFT_QUALITY",
        "EVIDENCE_LIMITATION", "OPERABILITY", "OTHER",
    ]] = Field(default_factory=list, max_length=7)
    suggestion: str = Field(default="", max_length=4000)
    adoption_status: Literal["ADOPTED", "PARTIALLY_ADOPTED", "NOT_ADOPTED", "UNKNOWN"] = "UNKNOWN"
    modification_level: Literal["NONE", "LIGHT", "MEDIUM", "HEAVY", "NOT_RECORDED"] = "NOT_RECORDED"
    modification_summary: str = Field(default="", max_length=4000)


class AgentDraftArtifactFeedbackCreate(AgentScopeAction):
    rating: Literal["USABLE", "NEEDS_CHANGES", "UNUSABLE"]
    reason_tags: list[Literal[
        "BRAND_ASSOCIATION", "FACTUAL_ACCURACY", "STRATEGY_TOO_GENERIC", "DRAFT_QUALITY",
        "EVIDENCE_LIMITATION", "OPERABILITY", "OTHER",
    ]] = Field(default_factory=list, max_length=7)
    suggestion: str = Field(default="", max_length=4000)
    adoption_status: Literal["ADOPTED", "PARTIALLY_ADOPTED", "NOT_ADOPTED", "UNKNOWN"] = "UNKNOWN"
    modification_level: Literal["NONE", "LIGHT", "MEDIUM", "HEAVY", "NOT_RECORDED"] = "NOT_RECORDED"
    modification_summary: str = Field(default="", max_length=4000)


class AgentDraftArtifactRegenerate(AgentScopeAction):
    idempotency_key: str = Field(min_length=8, max_length=120)


def get_read_db(db: Session = Depends(get_release_db)):
    with read_only_release_session(db):
        yield db


@router.get("/agent-experiments/capabilities")
def read_agent_capabilities(project_id: int) -> dict:
    configured = os.environ.get("GEO_AGENT_BETA_DAILY_MODEL_CALLS") == "1"
    enabled = configured
    blocker = None
    if enabled:
        try:
            server_task_policy()
        except SharedBudgetDenied as exc:
            enabled = False
            blocker = str(exc)
    response = {
        "project_id": project_id,
        "execution_mode": "EVIDENCE_PACK",
        "new_generation_enabled": enabled,
        "authorization_scope": "INTERNAL_BETA_DAILY" if enabled else "HISTORY_ONLY",
        "message": ("AI 生成已由服务端启用；创建任务后会自动开始，无需设置 Token、金额或计费参数。"
                    if enabled else "AI 生成尚未由服务端启用；当前仍可查看和使用历史结果。"),
    }
    if configured:
        response.update({"blocker": blocker})
        if not enabled:
            response["message"] = "AI 生成服务暂不可用；可查看历史结果，但不会产生外部调用。"
    return response


@router.post("/analyses/{analysis_id}/agent-experiments", status_code=201)
def start_agent_experiment(analysis_id: str, payload: AgentRunCreate, response: Response,
                           actor: str = Depends(authenticated_actor), db: Session = Depends(get_release_db)) -> dict:
    try:
        policy = server_task_policy()
    except SharedBudgetDenied as exc:
        raise HTTPException(409, detail={
            "code": "BETA_SERVER_MODEL_POLICY_UNAVAILABLE", "message": str(exc),
        }) from exc
    values = payload.model_dump()
    row, created = create_agent_run(db, analysis_id=analysis_id, requested_by=actor, **values)
    authorization = run_view(row).get("authorization") or {}
    if (row.status in {"QUEUED", "WAITING_AUTHORIZATION"}
            and authorization.get("mode") == "CACHE_ONLY"):
        try:
            append_run_authorization(
                db, run_id=row.run_id, project_id=row.project_id, prompt_id=row.prompt_id,
                revision=row.revision, authorized_by=f"server-policy:{actor}", **policy,
            )
            row = authorize_agent_run(
                db, run_id=row.run_id, project_id=row.project_id, prompt_id=row.prompt_id,
                revision=row.revision, authorized_by=f"server-policy:{actor}", **policy,
            )
        except SharedBudgetDenied as exc:
            raise HTTPException(409, detail={
                "code": "BETA_SERVER_MODEL_POLICY_DENIED", "message": str(exc),
            }) from exc
    if not created:
        response.status_code = 200
    return run_view(row, include_scope=True)


@router.get("/analyses/{analysis_id}/agent-experiments")
def read_agent_experiments(analysis_id: str, project_id: int, prompt_id: int,
                           db: Session = Depends(get_read_db)) -> list[dict]:
    return list_agent_runs(db, project_id=project_id, prompt_id=prompt_id, analysis_id=analysis_id)


@router.get("/agent-experiments/{run_id}")
def read_agent_experiment(run_id: str, project_id: int, prompt_id: int,
                          db: Session = Depends(get_read_db)) -> dict:
    return get_agent_run(db, run_id=run_id, project_id=project_id, prompt_id=prompt_id)


@router.get("/agent-experiments/{run_id}/results")
def read_agent_results(run_id: str, project_id: int, prompt_id: int,
                       db: Session = Depends(get_read_db)) -> list[dict]:
    return list_agent_results(db, run_id=run_id, project_id=project_id, prompt_id=prompt_id)


@router.get("/agent-experiments/{run_id}/feedback")
def read_agent_feedback(run_id: str, project_id: int, prompt_id: int,
                        result_version: str | None = None,
                        db: Session = Depends(get_read_db)) -> list[dict]:
    return list_result_feedback(db, run_id=run_id, project_id=project_id,
                                prompt_id=prompt_id, result_version=result_version)


@router.post("/agent-experiments/{run_id}/feedback", status_code=201)
def create_agent_feedback(run_id: str, payload: AgentResultFeedbackCreate,
                          actor: str = Depends(authenticated_actor),
                          db: Session = Depends(get_release_db)) -> dict:
    return feedback_view(add_result_feedback(
        db, run_id=run_id, submitted_by=actor, **payload.model_dump()))


@router.get("/agent-experiments/{run_id}/draft-artifacts")
def read_draft_artifacts(run_id: str, project_id: int, prompt_id: int,
                         result_version: str | None = None,
                         db: Session = Depends(get_read_db)) -> list[dict]:
    return list_draft_artifacts(
        db, run_id=run_id, project_id=project_id, prompt_id=prompt_id,
        result_version=result_version)


@router.get("/draft-artifacts/{artifact_version}")
def read_draft_artifact(artifact_version: str, project_id: int, prompt_id: int,
                        db: Session = Depends(get_read_db)) -> dict:
    return draft_artifact_view(get_draft_artifact(
        db, artifact_version=artifact_version, project_id=project_id, prompt_id=prompt_id))


@router.get("/draft-artifacts/{artifact_version}/export")
def export_draft_artifact(artifact_version: str, project_id: int, prompt_id: int,
                          db: Session = Depends(get_read_db)) -> dict:
    return draft_artifact_export(
        db, artifact_version=artifact_version, project_id=project_id, prompt_id=prompt_id)


@router.get("/draft-artifacts/{artifact_version}/feedback")
def read_draft_artifact_feedback(artifact_version: str, project_id: int, prompt_id: int,
                                 db: Session = Depends(get_read_db)) -> list[dict]:
    return list_draft_artifact_feedback(
        db, artifact_version=artifact_version, project_id=project_id, prompt_id=prompt_id)


@router.post("/draft-artifacts/{artifact_version}/feedback", status_code=201)
def create_draft_artifact_feedback(
    artifact_version: str, payload: AgentDraftArtifactFeedbackCreate,
    actor: str = Depends(authenticated_actor), db: Session = Depends(get_release_db),
) -> dict:
    return draft_artifact_feedback_view(add_draft_artifact_feedback(
        db, artifact_version=artifact_version, submitted_by=actor, **payload.model_dump()))


@router.post("/draft-artifacts/{artifact_version}/regenerations", status_code=201)
def regenerate_draft_artifact(
    artifact_version: str, payload: AgentDraftArtifactRegenerate, response: Response,
    actor: str = Depends(authenticated_actor), db: Session = Depends(get_release_db),
) -> dict:
    try:
        policy = server_task_policy()
    except SharedBudgetDenied as exc:
        raise HTTPException(409, detail={
            "code": "BETA_SERVER_MODEL_POLICY_DENIED", "message": str(exc),
        }) from exc
    row, created = queue_draft_artifact_regeneration(
        db, artifact_version=artifact_version, requested_by=actor,
        server_policy=policy, **payload.model_dump())
    if not created:
        response.status_code = 200
    return draft_artifact_regeneration_view(row)


@router.get("/agent-experiments/{run_id}/comparison")
def read_agent_comparison(run_id: str, project_id: int, prompt_id: int,
                          db: Session = Depends(get_read_db)) -> dict:
    return compare_with_workflow(db, run_id=run_id, project_id=project_id, prompt_id=prompt_id)


@router.post("/agent-experiments/{run_id}/cancel")
def cancel_agent_experiment(run_id: str, payload: AgentScopeAction,
                            db: Session = Depends(get_release_db)) -> dict:
    return run_view(cancel_agent_run(db, run_id=run_id, **payload.model_dump()))


@router.post("/agent-experiments/{run_id}/authorization")
def authorize_agent_experiment(run_id: str, payload: AgentServerQueue,
                               actor: str = Depends(authenticated_actor),
                               db: Session = Depends(get_release_db)) -> dict:
    try:
        policy = server_task_policy()
        append_run_authorization(
            db, run_id=run_id, project_id=payload.project_id, prompt_id=payload.prompt_id,
            revision=payload.revision, authorized_by=f"server-policy:{actor}", **policy,
        )
    except SharedBudgetDenied as exc:
        raise HTTPException(409, detail={
            "code": "BETA_SERVER_MODEL_POLICY_DENIED", "message": str(exc),
        }) from exc
    return run_view(authorize_agent_run(
        db, run_id=run_id, project_id=payload.project_id, prompt_id=payload.prompt_id,
        revision=payload.revision, authorized_by=f"server-policy:{actor}", **policy,
    ))
