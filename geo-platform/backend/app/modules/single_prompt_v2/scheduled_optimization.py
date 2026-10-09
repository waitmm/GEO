"""Optional finite handoff from a sampling schedule to existing Optimize tasks."""
from fastapi import HTTPException
from sqlalchemy import update

from app.models import SinglePromptAnalysisContext, SinglePromptOptimizationTask, SinglePromptSamplingSchedule
from app.services.serialization import loads
from .automatic_delivery import configuration_snapshot, create_task, authorize_task, validate_authorization, encode, cancel_task


def freeze_settings(db, project_id, prompt_text, settings):
    if not settings:
        return None
    value = dict(settings)
    authority = value['authorization']
    validate_authorization(**authority)
    if not (1 <= value['every_batches'] <= 30 and 1 <= value['max_tasks'] <= 30):
        raise HTTPException(422, '自动优化频次和总任务数必须在 1 到 30 之间')
    totals = {key: authority[key] * value['max_tasks'] for key in ('max_requests', 'max_tokens', 'max_cost_cny')}
    if totals['max_requests'] > 1000 or totals['max_tokens'] > 10000000 or totals['max_cost_cny'] > 1000:
        raise HTTPException(422, '整份计划的优化总请求/token/费用上限过大')
    value.update(contract='sampling-optimize-handoff.v1', total_authorization=totals,
        configuration=configuration_snapshot(db, project_id, prompt_text, value.get('brand_context_version_id')),
        automatic_retry=0)
    return value


def _save(db, schedule, state):
    revision = schedule.revision
    changed = db.execute(update(SinglePromptSamplingSchedule).where(
        SinglePromptSamplingSchedule.id == schedule.id, SinglePromptSamplingSchedule.revision == revision,
        SinglePromptSamplingSchedule.status == 'ACTIVE',
    ).values(optimization_progress_json=encode(state), revision=revision + 1))
    db.commit()
    if changed.rowcount != 1:
        raise HTTPException(409, '采样计划已变化，停止自动交接')
    db.refresh(schedule)


def handoff(db, schedule, analysis):
    plan = loads(schedule.plan_json, {})
    settings = plan.get('optimization')
    if not settings or not analysis or analysis.status in {'QUEUED', 'PLANNED', 'COLLECTING'}:
        return
    state = loads(schedule.optimization_progress_json, {})
    if state.get('status') in {'BLOCKED', 'EXHAUSTED'}:
        return
    records = state.setdefault('batches', [])
    record = next((r for r in records if r['analysis_id'] == analysis.analysis_id), None)
    if record and record['status'] != 'RESERVED':
        return
    context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis.analysis_id,
        project_id=schedule.project_id, prompt_id=schedule.prompt_id).one_or_none()
    if not record:
        record = {'analysis_id': analysis.analysis_id, 'status': 'OBSERVED'}
        records.append(record)
        if not context or not context.valid_run_count:
            record['status'] = 'NO_VALID_ANSWER'
        elif len(records) % settings['every_batches']:
            record['status'] = 'SKIPPED_TRIGGER'
        elif sum(r.get('reserved') is True for r in records) >= settings['max_tasks']:
            state['status'] = 'EXHAUSTED'
            record['status'] = 'TASK_LIMIT_REACHED'
        else:
            record.update(status='RESERVED', reserved=True, context_id=context.context_id,
                raw_output_hash=context.raw_output_hash)
        _save(db, schedule, state)
    if record['status'] != 'RESERVED':
        return
    key = f"{schedule.schedule_id}:{analysis.analysis_id}"
    try:
        if not context or context.context_id != record['context_id'] or context.raw_output_hash != record['raw_output_hash']:
            raise HTTPException(409, '计划批次的冻结范围已变化')
        if configuration_snapshot(db, schedule.project_id, plan['prompt_text'], settings.get('brand_context_version_id')) != settings['configuration']:
            raise HTTPException(409, '品牌、事实、模型或计算契约已变化，需要新建明确计划；本计划不会使用新配置')
        validate_authorization(**settings['authorization'])
        task, _ = create_task(db, analysis_id=analysis.analysis_id, project_id=schedule.project_id,
            prompt_id=schedule.prompt_id, raw_output_hash=context.raw_output_hash, idempotency_key=key,
            brand_context_version_id=settings.get('brand_context_version_id'),
            source_fetch_authorized=settings.get('source_fetch_authorized', False))
        db.refresh(schedule)
        if schedule.status != 'ACTIVE':
            if task.idempotency_key == key and task.status == 'QUEUED':
                cancel_task(db, task, task.revision)
            return
        if task.idempotency_key != key:
            record.update(status='REUSED_EXISTING', task_id=task.task_id)
        else:
            frozen = loads(task.input_json, {})
            if any(frozen.get(k) != v for k, v in settings['configuration'].items()):
                cancel_task(db, task, task.revision)
                raise HTTPException(409, '创建任务期间配置已变化，已停止该任务，不能扩大计划身份')
            if loads(task.authorization_json, {}).get('policy') == 'CACHE_ONLY':
                authorize_task(db, task, expected_revision=task.revision, input_hash=task.input_hash,
                    **settings['authorization'])
            record.update(status='QUEUED', task_id=task.task_id, input_hash=task.input_hash)
        state['status'] = 'ACTIVE'
        state['last_error'] = ''
        _save(db, schedule, state)
    except HTTPException as exc:
        db.rollback()
        db.refresh(schedule)
        if schedule.status == 'ACTIVE':
            state.update(status='BLOCKED', last_error=str(exc.detail))
            _save(db, schedule, state)
        else:
            # A pause may precede recording the child ID in schedule progress.
            child = db.query(SinglePromptOptimizationTask).filter_by(
                idempotency_key=key, project_id=schedule.project_id,
                prompt_id=schedule.prompt_id).one_or_none()
            if child and child.status == 'QUEUED':
                cancel_task(db, child, child.revision)


def cancel_pending_handoffs(db, schedule):
    state = loads(schedule.optimization_progress_json, {})
    for item in state.get('batches') or []:
        task = db.query(SinglePromptOptimizationTask).filter_by(task_id=item.get('task_id'),
            project_id=schedule.project_id, prompt_id=schedule.prompt_id).one_or_none()
        if task and task.idempotency_key.startswith(schedule.schedule_id + ':') and task.status == 'QUEUED':
            cancel_task(db, task, task.revision)
