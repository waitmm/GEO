"""Release Monitor / Validate and optional context entrypoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.core.release_database import get_release_db
from app.models import BrandContextVersion, Project, Prompt, BrowserMonitorRun, SinglePromptAnalysis, SinglePromptAnalysisContext, SinglePromptObservationComparison, SinglePromptDiagnosisExecution, SinglePromptDiagnosisResult
from app.services.serialization import loads
from .context_provider import context_view, load_context, save_context
from .observation import fixed_scope, measure_scope, create_observation_comparison, aggregate_prompt_metrics, opportunity_hint
from . import scheduling
from app.models import SinglePromptSamplingSchedule
from .service import _snapshot_run_rows, _hash, _run_input_fingerprint, create_analysis_from_runs, get_analysis_status, VALID_RUN_STATUSES
from urllib.parse import urlsplit

router = APIRouter(prefix='/api/v2', tags=['monitor-validate'])


@router.get('/projects/{project_id}/monitor')
def project_monitor(project_id: int, db: Session = Depends(get_release_db)):
    if not db.get(Project, project_id):
        raise HTTPException(404, '项目不存在')
    prompts = db.query(Prompt).filter_by(project_id=project_id, enabled=True).order_by(Prompt.id).all()
    values = [current_monitor(project_id, prompt.id, db) for prompt in prompts]
    return {'project_id': project_id, 'aggregation': 'PROMPT_MACRO_WITH_SEPARATE_RUN_WEIGHTED',
        'metrics': aggregate_prompt_metrics(values),
        'prompts': [{'prompt': row['prompt'], 'metrics': row['metrics'], 'run_ids': [r['run_id'] for r in row['runs']],
            'pool_count': row['pool_count'], 'identity_hash': row['input']['identity_hash'],
            'raw_output_hash': row['input']['raw_output_hash'], 'opportunity': row['opportunity'],
            'analysis_selection': row['analysis_selection']} for row in values],
        'limitations': ['项目概览仅使用当前问题原文；未明确选择语义版本时，候选和推荐保持未知。',
            '按问题平均与按Run加权分别显示；无有效分母的问题不按零计入。']}


@router.get('/projects/{project_id}/prompts/{prompt_id}/monitor')
def current_monitor(project_id: int, prompt_id: int, db: Session = Depends(get_release_db)):
    project, prompt = db.get(Project, project_id), db.get(Prompt, prompt_id)
    if not project or not prompt or prompt.project_id != project_id:
        raise HTTPException(404, '问题不存在或不属于当前项目')
    runs = db.query(BrowserMonitorRun).filter_by(project_id=project_id, prompt_id=prompt_id).order_by(BrowserMonitorRun.id).all()
    website = project.website_url or ''
    domain = urlsplit(website).hostname
    identity = {'canonical_brand_name': project.brand_name, 'accepted_aliases': loads(project.brand_aliases_json, []),
                'official_domains': [domain] if domain else [], 'official_urls': [website] if website else []}
    matching = [r for r in runs if r.original_query == prompt.prompt_text]
    historical = [r for r in runs if r.original_query != prompt.prompt_text]
    raw = {'runs': _snapshot_run_rows(db, matching), 'prompt_text': prompt.prompt_text}
    result = measure_scope({'raw': raw, 'semantics': None, 'ref': {'scope_type': 'CURRENT_RUN_POOL',
        'run_ids': [r.id for r in matching], 'identity_hash': _hash(identity), 'raw_output_hash': _hash(raw)}}, identity)
    result['historical_query_runs'] = _snapshot_run_rows(db, historical)
    result['pool_count'] = len(runs)
    result['scope_label'] = '当前问题原文的采样尝试，历史问题版本另列；失败不计为品牌缺席'
    result['semantic_selection_required'] = True
    result['prompt'] = {'id': prompt.id, 'text': prompt.prompt_text, 'intent_type': prompt.intent_type, 'group': prompt.prompt_group}
    result['opportunity'] = opportunity_hint(prompt.intent_type, result['metrics'])
    result['identity'] = identity
    selection = {'project_id': project_id, 'prompt_id': prompt_id,
        'observed_run_ids': [r.id for r in matching],
        'raw_output_hash': result['input']['raw_output_hash'], 'identity_hash': _hash(identity),
        'prompt_configuration': {'text': prompt.prompt_text, 'intent_type': prompt.intent_type, 'group': prompt.prompt_group},
        'run_fingerprints': {str(r['run_id']): _run_input_fingerprint(r) for r in raw['runs']
            if r['status'] in VALID_RUN_STATUSES and str(r.get('answer_text') or '').strip()}}
    selection['selected_run_ids'] = sorted(int(key) for key in selection['run_fingerprints'])
    selection['excluded_run_ids'] = [r.id for r in matching if r.id not in selection['selected_run_ids']]
    result['analysis_selection'] = {**selection, 'scope_hash': _hash(selection)}
    result['competitor_observations'] = [{
        'competitor_id': competitor.id, 'name': competitor.name,
        'measurement': measure_scope({'raw': raw, 'semantics': None, 'ref': result['input']},
            {'canonical_brand_name': competitor.name, 'accepted_aliases': loads(competitor.aliases_json, []),
             'official_domains': [], 'official_urls': []})['metrics']['brand_mention_rate'],
        'scope': 'CONFIGURED_COMPETITOR_TEXT_MENTION_ONLY',
    } for competitor in project.competitors]
    return result


class StrictInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class MonitorAnalysisCreate(StrictInput):
    scope_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


@router.post('/projects/{project_id}/prompts/{prompt_id}/monitor-analysis', status_code=201)
def analyze_monitor_scope(project_id: int, prompt_id: int, payload: MonitorAnalysisCreate,
                          response: Response, db: Session = Depends(get_release_db)):
    request_key = f'monitor:{payload.scope_hash}'
    existing = db.query(SinglePromptAnalysis).filter_by(project_id=project_id, idempotency_key=request_key).one_or_none()
    if existing:
        origin = loads(existing.sampling_plan_json, {}).get('origin_monitor_scope', {})
        if existing.prompt_id != prompt_id or origin.get('scope_hash') != payload.scope_hash:
            raise HTTPException(409, '该请求身份已用于其他观察范围')
        response.status_code = 200
        return get_analysis_status(db, existing.analysis_id)
    selected = current_monitor(project_id, prompt_id, db)['analysis_selection']
    if selected['scope_hash'] != payload.scope_hash:
        raise HTTPException(409, '监测范围或配置已变化，请刷新监测后重新确认；没有替换为新样本')
    if not selected['selected_run_ids'] or len(selected['selected_run_ids']) > 500:
        raise HTTPException(422, '本次可分析回答需为1至500条；请到采样记录池明确选择范围')
    analysis, created = create_analysis_from_runs(db, project_id=project_id, prompt_id=prompt_id,
        run_ids=selected['selected_run_ids'], run_fingerprints=selected['run_fingerprints'],
        base_context_id=None, idempotency_key=request_key, origin_monitor_scope=selected)
    if not created:
        response.status_code = 200
    return get_analysis_status(db, analysis.analysis_id)


class ContextCreate(StrictInput):
    expected_version: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=100000)
    source_reference: str = Field(default='', max_length=1000)


class ScheduledAuthority(StrictInput):
    max_requests: int = Field(ge=1, le=1000)
    max_tokens: int = Field(ge=1, le=10000000)
    max_cost_cny: float = Field(gt=0, le=1000)
    conservative_cny_per_million_tokens: float = Field(gt=0, le=1000)
    pricing_source: str = Field(min_length=8, max_length=2000)
    pricing_checked_at: str = Field(max_length=40)
    authorized_by: str = Field(min_length=1, max_length=240)


class ScheduledOptimization(StrictInput):
    every_batches: int = Field(ge=1, le=30)
    max_tasks: int = Field(ge=1, le=30)
    brand_context_version_id: str | None = Field(default=None, max_length=80)
    source_fetch_authorized: bool = False
    authorization: ScheduledAuthority


class ScheduleCreate(StrictInput):
    timezone_name: str = Field(default='Asia/Shanghai', max_length=80)
    local_time: str = Field(pattern=r'^\d{2}:\d{2}$')
    sample_count: int = Field(ge=1, le=10)
    max_attempts: int = Field(ge=1, le=300)
    authorization_note: str = Field(min_length=1, max_length=1000)
    optimization: ScheduledOptimization | None = None


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
    frozen = fixed_scope(db, project_id, prompt_id, payload.scope.model_dump())
    result = measure_scope(frozen, payload.identity.model_dump(), payload.target_url)
    intent = frozen['raw'].get('sampling_plan', {}).get('prompt_configuration', {}).get('intent_type', '')
    result['opportunity'] = opportunity_hint(intent, result['metrics'])
    return result


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
