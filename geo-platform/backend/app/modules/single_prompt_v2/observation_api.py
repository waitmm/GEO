"""Release Monitor / Validate and optional context entrypoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.core.release_database import get_release_db
from app.models import BrandContextVersion, Project, SinglePromptAnalysisContext, SinglePromptObservationComparison, SinglePromptDiagnosisExecution, SinglePromptDiagnosisResult
from app.services.serialization import loads
from .context_provider import context_view, load_context, save_context
from .observation import fixed_scope, measure_scope, create_observation_comparison
from . import scheduling
from app.models import SinglePromptSamplingSchedule

router = APIRouter(prefix='/api/v2', tags=['monitor-validate'])


class StrictInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class ContextCreate(StrictInput):
    expected_version: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=100000)
    source_reference: str = Field(default='', max_length=1000)


class ScheduleCreate(StrictInput):
    timezone_name: str = Field(default='Asia/Shanghai', max_length=80)
    local_time: str = Field(pattern=r'^\d{2}:\d{2}$')
    sample_count: int = Field(ge=1, le=10)
    max_attempts: int = Field(ge=1, le=300)
    authorization_note: str = Field(min_length=1, max_length=1000)


class SchedulePause(StrictInput):
    expected_revision: int = Field(ge=1)


@router.get('/projects/{project_id}/prompts/{prompt_id}/sampling-schedules')
def schedules(project_id: int, prompt_id: int, db: Session = Depends(get_release_db)):
    return [scheduling.view(r) for r in db.query(SinglePromptSamplingSchedule).filter_by(project_id=project_id, prompt_id=prompt_id).order_by(SinglePromptSamplingSchedule.id.desc()).all()]


@router.post('/projects/{project_id}/prompts/{prompt_id}/sampling-schedules', status_code=201)
def new_schedule(project_id: int, prompt_id: int, payload: ScheduleCreate, db: Session = Depends(get_release_db)):
    return scheduling.view(scheduling.create_schedule(db, project_id=project_id, prompt_id=prompt_id, **payload.model_dump()))


@router.post('/projects/{project_id}/prompts/{prompt_id}/sampling-schedules/{schedule_id}/pause')
def pause_schedule(project_id: int, prompt_id: int, schedule_id: str, payload: SchedulePause, db: Session = Depends(get_release_db)):
    row = db.query(SinglePromptSamplingSchedule).filter_by(project_id=project_id, prompt_id=prompt_id, schedule_id=schedule_id).one_or_none()
    if not row:
        raise HTTPException(404, '计划不存在或归属不符')
    return scheduling.view(scheduling.pause_schedule(db, row, payload.expected_revision))


class ScopeReference(StrictInput):
    context_id: str = Field(min_length=1, max_length=80)
    raw_output_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    answer_result_version: str | None = None
    answer_result_hash: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def semantic_identity(self):
        if bool(self.answer_result_version) != bool(self.answer_result_hash):
            raise ValueError('回答结果必须同时提供版本和hash')
        return self


class MeasurementIdentity(StrictInput):
    canonical_brand_name: str = Field(min_length=1, max_length=160)
    accepted_aliases: list[str] = Field(default_factory=list, max_length=50)
    official_domains: list[str] = Field(default_factory=list, max_length=50)
    official_urls: list[str] = Field(default_factory=list, max_length=50)


class MeasurementCreate(StrictInput):
    scope: ScopeReference
    identity: MeasurementIdentity
    target_url: str = Field(default='', max_length=2000)


class ComparisonCreate(StrictInput):
    baseline: ScopeReference
    comparison: ScopeReference
    identity: MeasurementIdentity
    target_url: str = Field(default='', max_length=2000)


@router.get('/projects/{project_id}/brand-contexts')
def contexts(project_id: int, db: Session = Depends(get_release_db)):
    if not db.get(Project, project_id):
        raise HTTPException(404, '项目不存在')
    return [context_view(row) for row in db.query(BrandContextVersion).filter_by(project_id=project_id).order_by(BrandContextVersion.version_number.desc()).all()]


@router.post('/projects/{project_id}/brand-contexts', status_code=201)
def new_context(project_id: int, payload: ContextCreate, db: Session = Depends(get_release_db)):
    return context_view(save_context(db, project_id=project_id, **payload.model_dump()))


@router.get('/projects/{project_id}/brand-contexts/{context_version_id}')
def exact_context(project_id: int, context_version_id: str, db: Session = Depends(get_release_db)):
    return load_context(db, project_id=project_id, context_version_id=context_version_id)


@router.get('/projects/{project_id}/prompts/{prompt_id}/observation-scopes')
def scopes(project_id: int, prompt_id: int, db: Session = Depends(get_release_db)):
    rows = db.query(SinglePromptAnalysisContext).filter_by(project_id=project_id, prompt_id=prompt_id).order_by(SinglePromptAnalysisContext.id.desc()).all()
    results = db.query(SinglePromptDiagnosisResult, SinglePromptDiagnosisExecution.context_id).join(SinglePromptDiagnosisExecution, SinglePromptDiagnosisExecution.diagnosis_id == SinglePromptDiagnosisResult.diagnosis_id).filter(SinglePromptDiagnosisExecution.project_id == project_id, SinglePromptDiagnosisExecution.prompt_id == prompt_id).all()
    return [{'context_id': row.context_id, 'analysis_id': row.analysis_id, 'raw_result_version': row.result_version,
             'raw_output_hash': row.raw_output_hash, 'run_scope': loads(row.run_scope_json, {}),
             'answer_results': [{'result_version': result.result_version, 'output_hash': result.output_hash} for result, context_id in results if context_id == row.context_id],
             'created_at': row.created_at.isoformat()} for row in rows]


@router.post('/projects/{project_id}/prompts/{prompt_id}/measurements')
def measurement(project_id: int, prompt_id: int, payload: MeasurementCreate, db: Session = Depends(get_release_db)):
    return measure_scope(fixed_scope(db, project_id, prompt_id, payload.scope.model_dump()), payload.identity.model_dump(), payload.target_url)


def comparison_view(row):
    return {'result_version': row.result_version, 'input_hash': row.input_hash, 'output_hash': row.output_hash,
            'created_at': row.created_at.isoformat(), 'input': loads(row.input_snapshot_json, {}), 'output': loads(row.output_json, {})}


@router.post('/projects/{project_id}/prompts/{prompt_id}/observation-comparisons', status_code=201)
def create_comparison(project_id: int, prompt_id: int, payload: ComparisonCreate, response: Response, db: Session = Depends(get_release_db)):
    row, created = create_observation_comparison(db, project_id=project_id, prompt_id=prompt_id, **payload.model_dump())
    if not created:
        response.status_code = 200
    return comparison_view(row)


@router.get('/projects/{project_id}/prompts/{prompt_id}/observation-comparisons')
def comparisons(project_id: int, prompt_id: int, db: Session = Depends(get_release_db)):
    return [comparison_view(row) for row in db.query(SinglePromptObservationComparison).filter_by(project_id=project_id, prompt_id=prompt_id).order_by(SinglePromptObservationComparison.id.desc()).all()]


@router.get('/projects/{project_id}/prompts/{prompt_id}/observation-comparisons/{result_version}')
def exact_comparison(project_id: int, prompt_id: int, result_version: str, db: Session = Depends(get_release_db)):
    row = db.query(SinglePromptObservationComparison).filter_by(project_id=project_id, prompt_id=prompt_id, result_version=result_version).one_or_none()
    if not row:
        raise HTTPException(404, '比较结果不存在或不属于当前项目')
    return comparison_view(row)
