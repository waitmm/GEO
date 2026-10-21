"""Release Monitor / Validate and optional context entrypoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.core.release_database import get_release_db
from app.core.release_access import authenticated_actor
from app.models import BrandContextVersion, Project, Prompt, BrowserMonitorRun, SinglePromptAnalysis, SinglePromptAnalysisContext, SinglePromptObservationComparison, SinglePromptDiagnosisExecution, SinglePromptDiagnosisResult
from app.services.serialization import loads
from .context_provider import context_view, load_context, save_context
from .observation import fixed_scope, measure_scope, create_observation_comparison, aggregate_prompt_metrics, opportunity_hint
from . import scheduling
from app.models import SinglePromptSamplingSchedule
from .service import (_snapshot_run_rows, _hash, _run_input_fingerprint, create_analysis_from_runs,
    get_analysis_status, prompt_version_binding_for_runs, VALID_RUN_STATUSES,
    _current_analysis_configuration)
from urllib.parse import urlsplit
from .manual_import import import_manual_observation, manual_import_view

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
        'project_configuration': _current_analysis_configuration(db, project_id),
        'prompt_configuration': {'text': prompt.prompt_text, 'intent_type': prompt.intent_type, 'group': prompt.prompt_group},
        'run_fingerprints': {str(r['run_id']): _run_input_fingerprint(r) for r in raw['runs']
            if r['status'] in VALID_RUN_STATUSES and str(r.get('answer_text') or '').strip()}}
    selection['selected_run_ids'] = sorted(int(key) for key in selection['run_fingerprints'])
    selection['excluded_run_ids'] = [r.id for r in matching if r.id not in selection['selected_run_ids']]
    try:
        selection['prompt_version'] = prompt_version_binding_for_runs(
            db, run_ids=selection['selected_run_ids'])
    except HTTPException:
        selection['prompt_version'] = {'binding_status': 'UNSAFE', 'reason': 'PROMPT_VERSION_BINDING_INVALID'}
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


class ManualCitationInput(StrictInput):
    title: str = Field(default='', max_length=500)
    url: str = Field(min_length=8, max_length=1200)


class ManualObservationImportCreate(StrictInput):
    prompt_version_id: str = Field(min_length=1, max_length=80)
    prompt_snapshot_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    configuration_version_id: str = Field(min_length=1, max_length=80)
    configuration_snapshot_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    observed_at: datetime
    source_platform: str = Field(pattern=r'^wenxin$')
    source_page_url: str = Field(default='', max_length=1200)
    answer_text: str = Field(min_length=20, max_length=500000)
    citations: list[ManualCitationInput] = Field(default_factory=list, max_length=200)
    citation_observation_status: str = Field(pattern=r'^(COMPLETE|CONFIRMED_NONE|UNKNOWN|PARSE_FAILED)$')
    citation_note: str = Field(default='', max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=120)


@router.post('/projects/{project_id}/prompts/{prompt_id}/manual-imports', status_code=201)
def create_manual_import(project_id: int, prompt_id: int, payload: ManualObservationImportCreate,
                         request: Request, response: Response, db: Session = Depends(get_release_db)):
    record, run, created = import_manual_observation(
        db, project_id=project_id, prompt_id=prompt_id,
        prompt_version_id=payload.prompt_version_id, prompt_snapshot_hash=payload.prompt_snapshot_hash,
        configuration_version_id=payload.configuration_version_id,
        configuration_snapshot_hash=payload.configuration_snapshot_hash,
        observed_at=payload.observed_at, source_platform=payload.source_platform,
        source_page_url=payload.source_page_url, answer_text=payload.answer_text,
        citations=[item.model_dump() for item in payload.citations],
        citation_observation_status=payload.citation_observation_status,
        citation_note=payload.citation_note, imported_by=authenticated_actor(request),
        idempotency_key=payload.idempotency_key,
    )
    if not created:
        response.status_code = 200
    return manual_import_view(record, run, created)


class RangePreviewCreate(StrictInput):
    mode: str = Field(pattern=r'^(LAST_7_DAYS|LAST_14_DAYS|LAST_30_DAYS|CUSTOM|RUN_IDS)$')
    start_at: datetime | None = None
    end_at: datetime | None = None
    run_ids: list[int] = Field(default_factory=list, max_length=500)

    @model_validator(mode='after')
    def valid_range(self):
        if self.mode == 'CUSTOM' and (not self.start_at or not self.end_at):
            raise ValueError('自定义范围必须提供开始和结束时间')
        if self.mode == 'RUN_IDS' and not self.run_ids:
            raise ValueError('指定 Run 模式至少需要一个 Run ID')
        if self.mode != 'RUN_IDS' and self.run_ids:
            raise ValueError('只有指定 Run 模式可以提交 Run IDs')
        return self


class RangeFreezeCreate(StrictInput):
    selector: RangePreviewCreate
    preview_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    group_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    selected_run_ids: list[int] = Field(min_length=1, max_length=500)


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _range_preview(project_id: int, prompt_id: int, payload: RangePreviewCreate, db: Session):
    prompt = db.get(Prompt, prompt_id)
    if not prompt or prompt.project_id != project_id:
        raise HTTPException(404, '问题不存在或不属于当前项目')
    now = datetime.utcnow()
    if payload.mode.startswith('LAST_'):
        days = int(payload.mode.split('_')[1])
        start_at, end_at = now - timedelta(days=days), now
        resolved = {'mode': 'CUSTOM', 'start_at': start_at.isoformat() + 'Z', 'end_at': end_at.isoformat() + 'Z', 'run_ids': []}
    elif payload.mode == 'CUSTOM':
        start_at, end_at = _utc_naive(payload.start_at), _utc_naive(payload.end_at)
        if start_at >= end_at:
            raise HTTPException(422, '自定义范围的结束时间必须晚于开始时间')
        resolved = {'mode': 'CUSTOM', 'start_at': start_at.isoformat() + 'Z', 'end_at': end_at.isoformat() + 'Z', 'run_ids': []}
    else:
        start_at = end_at = None
        resolved = {'mode': 'RUN_IDS', 'start_at': None, 'end_at': None, 'run_ids': sorted(set(payload.run_ids))}
    query = db.query(BrowserMonitorRun).filter_by(project_id=project_id, prompt_id=prompt_id)
    if payload.mode == 'RUN_IDS':
        query = query.filter(BrowserMonitorRun.id.in_(resolved['run_ids']))
    candidates = query.order_by(BrowserMonitorRun.id).all()
    if payload.mode != 'RUN_IDS':
        candidates = [run for run in candidates if start_at <= (run.finished_at or run.started_at or run.created_at) <= end_at]
    if len(candidates) > 5000:
        raise HTTPException(422, '该时间范围超过 5000 条采样，请缩小范围')
    grouped = {}
    for run in candidates:
        try:
            binding = prompt_version_binding_for_runs(db, run_ids=[run.id])
        except HTTPException:
            binding = {'binding_status': 'UNSAFE', 'reason': 'PROMPT_VERSION_BINDING_INVALID'}
        manual_identity = None
        if run.sampling_mode == 'MANUAL_IMPORT':
            from .manual_import import manual_import_binding
            manual_identity = manual_import_binding(db, run)
        project_configuration = (manual_identity or {}).get('project_configuration')
        identity = {'platform': run.platform, 'source_type': run.source_type, 'adapter': run.adapter,
            'collection_mode': run.collection_mode, 'original_query': run.original_query,
            'prompt_version_id': binding.get('prompt_version_id'), 'snapshot_hash': binding.get('snapshot_hash'),
            'binding_status': binding.get('binding_status'), 'binding_reason': binding.get('reason'),
            'project_configuration_version_id': (project_configuration or {}).get('configuration_version_id'),
            'project_configuration_snapshot_hash': (project_configuration or {}).get('snapshot_hash'),
            'source_assertion_status': (manual_identity or {}).get('source_assertion_status')}
        key = _hash(identity)
        group = grouped.setdefault(key, {'group_hash': key, 'identity': identity, 'prompt_version': binding,
            'project_configuration': project_configuration,
            'run_ids': [], 'selected_run_ids': [], 'excluded_run_ids': [], 'status_counts': {}})
        group['run_ids'].append(run.id)
        group['status_counts'][run.status] = group['status_counts'].get(run.status, 0) + 1
        if run.status in VALID_RUN_STATUSES and str(run.answer_text or '').strip():
            group['selected_run_ids'].append(run.id)
        else:
            group['excluded_run_ids'].append(run.id)
    groups = sorted(grouped.values(), key=lambda item: item['group_hash'])
    preview_basis = {'contract_version': 'monitor-analysis-range-preview-v1', 'project_id': project_id,
        'prompt_id': prompt_id, 'selector': resolved, 'groups': groups}
    return {**preview_basis, 'preview_hash': _hash(preview_basis), 'total_count': len(candidates),
        'valid_count': sum(len(group['selected_run_ids']) for group in groups),
        'invalid_count': sum(len(group['excluded_run_ids']) for group in groups),
        'mixed_groups': len(groups) > 1,
        'limitations': ['失败采样不会按品牌未提及或零引用计入。', '不同 Prompt 版本、平台或采集配置不会静默合并。',
            'MANUAL_IMPORT 只验证身份、完整性与 hash，不独立证明第三方平台真实性。']}


@router.post('/projects/{project_id}/prompts/{prompt_id}/analysis-ranges/preview')
def preview_analysis_range(project_id: int, prompt_id: int, payload: RangePreviewCreate,
                           db: Session = Depends(get_release_db)):
    return _range_preview(project_id, prompt_id, payload, db)


@router.post('/projects/{project_id}/prompts/{prompt_id}/analysis-ranges/freeze', status_code=201)
def freeze_analysis_range(project_id: int, prompt_id: int, payload: RangeFreezeCreate,
                          response: Response, db: Session = Depends(get_release_db)):
    preview = _range_preview(project_id, prompt_id, payload.selector, db)
    if preview['preview_hash'] != payload.preview_hash:
        raise HTTPException(409, detail={'code': 'RANGE_PREVIEW_CHANGED', 'message': '采样范围已变化，请重新预览确认'})
    group = next((item for item in preview['groups'] if item['group_hash'] == payload.group_hash), None)
    if not group:
        raise HTTPException(409, '所选采样分组已不存在')
    selected = sorted(set(payload.selected_run_ids))
    if not selected or not set(selected).issubset(set(group['selected_run_ids'])):
        raise HTTPException(409, '提交的 Run 不属于当前可分析分组')
    binding = group['prompt_version']
    if binding.get('binding_status') != 'BOUND':
        raise HTTPException(409, detail={'code': 'RUN_PROMPT_VERSION_UNPROVEN', 'message': '所选 Run 没有单一可证明的 Prompt 冻结版本'})
    snapshots = _snapshot_run_rows(db, db.query(BrowserMonitorRun).filter(BrowserMonitorRun.id.in_(selected)).order_by(BrowserMonitorRun.id).all())
    fingerprints = {int(item['run_id']): _run_input_fingerprint(item) for item in snapshots}
    selection_hash = _hash({'preview_hash': payload.preview_hash, 'group_hash': payload.group_hash, 'run_ids': selected})
    origin = {'contract_version': 'monitor-analysis-range-v1', 'preview_hash': payload.preview_hash,
        'group_hash': payload.group_hash, 'selector': preview['selector'], 'selected_run_ids': selected,
        'excluded_run_ids': sorted(set(group['run_ids']) - set(selected)), 'selection_hash': selection_hash}
    analysis, created = create_analysis_from_runs(db, project_id=project_id, prompt_id=prompt_id,
        prompt_version_id=binding['prompt_version_id'], snapshot_hash=binding['snapshot_hash'],
        run_ids=selected, run_fingerprints=fingerprints, base_context_id=None,
        idempotency_key=f'range:{selection_hash}', origin_monitor_scope=origin,
        project_configuration=group.get('project_configuration'))
    if not created: response.status_code = 200
    return get_analysis_status(db, analysis.analysis_id)


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
    prompt_version = selected.get('prompt_version') or {}
    if prompt_version.get('binding_status') != 'BOUND':
        raise HTTPException(409, detail={
            'code': 'RUN_PROMPT_VERSION_UNPROVEN',
            'message': '当前监测范围包含历史未绑定或混合 Prompt 版本，不能创建不安全的新 Analysis',
        })
    analysis, created = create_analysis_from_runs(db, project_id=project_id, prompt_id=prompt_id,
        prompt_version_id=prompt_version['prompt_version_id'],
        snapshot_hash=prompt_version['snapshot_hash'],
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
    prompt_version_id: str = Field(min_length=1, max_length=80)
    snapshot_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    timezone_name: str = Field(default='Asia/Shanghai', max_length=80)
    local_time: str = Field(pattern=r'^\d{2}:\d{2}$')
    sample_count: int = Field(ge=1, le=10)
    max_attempts: int = Field(ge=1, le=300)
    authorization_note: str = Field(min_length=1, max_length=1000)
    collection_only: bool = False
    cadence_type: str = Field(default="DAILY", pattern=r"^(DAILY|WEEKLY|INTERVAL)$")
    weekday: int | None = Field(default=None, ge=0, le=6)
    interval_hours: int | None = Field(default=None, ge=1, le=168)
    optimization: ScheduledOptimization | None = None

    @model_validator(mode="after")
    def cadence_and_automation(self):
        if self.collection_only and self.optimization is not None:
            raise ValueError("COLLECTION_ONLY 计划不能自动分析")
        if self.cadence_type == "WEEKLY" and self.weekday is None:
            raise ValueError("每周计划必须选择星期")
        if self.cadence_type == "INTERVAL" and self.interval_hours is None:
            raise ValueError("固定间隔计划必须填写小时间隔")
        if not self.collection_only and self.cadence_type != "DAILY":
            raise ValueError("旧计划仅支持每日频率")
        return self


class SchedulePause(StrictInput):
    expected_revision: int = Field(ge=1)


class ScheduleRunNow(SchedulePause):
    idempotency_key: str = Field(min_length=8, max_length=120)


@router.get('/projects/{project_id}/prompts/{prompt_id}/sampling-schedules')
def schedules(project_id: int, prompt_id: int, db: Session = Depends(get_release_db)):
    return [scheduling.view(r, db) for r in db.query(SinglePromptSamplingSchedule).filter_by(project_id=project_id, prompt_id=prompt_id).order_by(SinglePromptSamplingSchedule.id.desc()).all()]


@router.post('/projects/{project_id}/prompts/{prompt_id}/sampling-schedules', status_code=201)
def new_schedule(project_id: int, prompt_id: int, payload: ScheduleCreate, db: Session = Depends(get_release_db)):
    return scheduling.view(scheduling.create_schedule(db, project_id=project_id, prompt_id=prompt_id, **payload.model_dump()), db)


@router.post('/projects/{project_id}/prompts/{prompt_id}/sampling-schedules/{schedule_id}/pause')
def pause_schedule(project_id: int, prompt_id: int, schedule_id: str, payload: SchedulePause, db: Session = Depends(get_release_db)):
    row = db.query(SinglePromptSamplingSchedule).filter_by(project_id=project_id, prompt_id=prompt_id, schedule_id=schedule_id).one_or_none()
    if not row:
        raise HTTPException(404, '计划不存在或归属不符')
    return scheduling.view(scheduling.pause_schedule(db, row, payload.expected_revision), db)


@router.post('/projects/{project_id}/prompts/{prompt_id}/sampling-schedules/{schedule_id}/resume')
def resume_schedule(project_id: int, prompt_id: int, schedule_id: str, payload: SchedulePause,
                    db: Session = Depends(get_release_db)):
    row = db.query(SinglePromptSamplingSchedule).filter_by(project_id=project_id, prompt_id=prompt_id, schedule_id=schedule_id).one_or_none()
    if not row:
        raise HTTPException(404, '计划不存在或归属不符')
    return scheduling.view(scheduling.resume_schedule(db, row, payload.expected_revision), db)


@router.post('/projects/{project_id}/prompts/{prompt_id}/sampling-schedules/{schedule_id}/run-now', status_code=202)
def run_schedule_now(project_id: int, prompt_id: int, schedule_id: str, payload: ScheduleRunNow,
                     db: Session = Depends(get_release_db)):
    row = db.query(SinglePromptSamplingSchedule).filter_by(project_id=project_id, prompt_id=prompt_id, schedule_id=schedule_id).one_or_none()
    if not row:
        raise HTTPException(404, '计划不存在或归属不符')
    return scheduling.execution_view(db, scheduling.queue_immediate(
        db, row, payload.expected_revision, payload.idempotency_key))


@router.put('/projects/{project_id}/prompts/{prompt_id}/sampling-schedules/{schedule_id}', status_code=201)
def edit_schedule(project_id: int, prompt_id: int, schedule_id: str, payload: ScheduleCreate,
                  expected_revision: int, db: Session = Depends(get_release_db)):
    row = db.query(SinglePromptSamplingSchedule).filter_by(project_id=project_id, prompt_id=prompt_id, schedule_id=schedule_id).one_or_none()
    if not row:
        raise HTTPException(404, '计划不存在或归属不符')
    values = payload.model_dump()
    values.pop("collection_only", None)
    return scheduling.view(scheduling.replace_schedule(db, row, expected_revision, **values), db)


@router.get('/projects/{project_id}/prompts/{prompt_id}/sampling-schedules/{schedule_id}/executions')
def schedule_executions(project_id: int, prompt_id: int, schedule_id: str, db: Session = Depends(get_release_db)):
    row = db.query(SinglePromptSamplingSchedule).filter_by(project_id=project_id, prompt_id=prompt_id, schedule_id=schedule_id).one_or_none()
    if not row:
        raise HTTPException(404, '计划不存在或归属不符')
    return scheduling.executions(db, row, limit=100)


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


class SupplementalSourceCreate(StrictInput):
    url: str = Field(min_length=8, max_length=1200)
    idempotency_key: str = Field(min_length=8, max_length=120)
    fetch_authorized: bool


@router.get('/projects/{project_id}/supplemental-sources')
def supplemental_sources(project_id: int, db: Session = Depends(get_release_db)):
    from app.models import SupplementalSourceAcquisition
    from .supplemental_sources import source_view
    if not db.get(Project, project_id):
        raise HTTPException(404, '项目不存在')
    return [source_view(row) for row in db.query(SupplementalSourceAcquisition).filter_by(project_id=project_id)
        .order_by(SupplementalSourceAcquisition.id.desc()).all()]


@router.post('/projects/{project_id}/supplemental-sources', status_code=201)
def new_supplemental_source(project_id: int, payload: SupplementalSourceCreate,
                           response: Response, db: Session = Depends(get_release_db)):
    from .supplemental_sources import queue_source, source_view
    row, created = queue_source(db, project_id=project_id, **payload.model_dump())
    if not created:
        response.status_code = 200
    return source_view(row)


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
    result['identity'] = payload.identity.model_dump()
    result['target_url'] = payload.target_url
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
