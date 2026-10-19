"""Release API for the isolated Agent experiment lane."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.release_access import authenticated_actor
from app.core.release_database import get_release_db, read_only_release_session

from .service import (
    authorize_agent_run,
    cancel_agent_run,
    compare_with_workflow,
    create_agent_run,
    get_agent_run,
    list_agent_runs,
    run_view,
)


router = APIRouter(prefix="/api/v2/single-prompt", tags=["geo-agent-experiment-v1"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AgentBudget(StrictModel):
    max_model_calls: int | None = Field(default=None, ge=0, le=12)
    max_tool_calls: int | None = Field(default=None, ge=0, le=30)
    max_total_tokens: int | None = Field(default=None, ge=0, le=100_000)
    max_elapsed_seconds: int | None = Field(default=None, ge=0, le=900)
    max_repairs: int | None = Field(default=None, ge=0, le=2)
    max_cost_cny: float | None = Field(default=None, ge=0, le=50)


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
    budget: AgentBudget | None = None


class AgentScopeAction(StrictModel):
    project_id: int = Field(gt=0)
    prompt_id: int = Field(gt=0)


class AgentAuthorization(AgentScopeAction):
    revision: int = Field(gt=0)
    max_requests: int = Field(gt=0, le=12)
    max_total_tokens: int = Field(gt=0, le=100_000)
    max_cost_cny: float = Field(gt=0, le=50)
    conservative_cny_per_million_tokens: float = Field(gt=0, le=10_000)
    pricing_source: str = Field(min_length=8, max_length=2000)
    pricing_checked_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


def get_read_db(db: Session = Depends(get_release_db)):
    with read_only_release_session(db):
        yield db


@router.post("/analyses/{analysis_id}/agent-experiments", status_code=201)
def start_agent_experiment(analysis_id: str, payload: AgentRunCreate, response: Response,
                           actor: str = Depends(authenticated_actor), db: Session = Depends(get_release_db)) -> dict:
    values = payload.model_dump()
    values["budget"] = payload.budget.model_dump(exclude_none=True) if payload.budget else None
    row, created = create_agent_run(db, analysis_id=analysis_id, requested_by=actor, **values)
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


@router.get("/agent-experiments/{run_id}/comparison")
def read_agent_comparison(run_id: str, project_id: int, prompt_id: int,
                          db: Session = Depends(get_read_db)) -> dict:
    return compare_with_workflow(db, run_id=run_id, project_id=project_id, prompt_id=prompt_id)


@router.post("/agent-experiments/{run_id}/cancel")
def cancel_agent_experiment(run_id: str, payload: AgentScopeAction,
                            db: Session = Depends(get_release_db)) -> dict:
    return run_view(cancel_agent_run(db, run_id=run_id, **payload.model_dump()))


@router.post("/agent-experiments/{run_id}/authorization")
def authorize_agent_experiment(run_id: str, payload: AgentAuthorization,
                               actor: str = Depends(authenticated_actor),
                               db: Session = Depends(get_release_db)) -> dict:
    return run_view(authorize_agent_run(db, run_id=run_id, authorized_by=actor, **payload.model_dump()))
