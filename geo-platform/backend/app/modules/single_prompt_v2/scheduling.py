"""Daily, bounded sampling using the existing frozen V2 execution path."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.models import BrowserMonitorRun, BrowserMonitorTask, Prompt, SinglePromptAnalysis, SinglePromptSamplingSchedule
from app.modules.monitoring.enums import NON_RETRYABLE_ERRORS, WENXIN_PLATFORM, WENXIN_WEB_ADAPTER, BROWSER_AUDIT_ENTRY_TYPE
from app.services.serialization import dumps, loads
from .service import _hash, create_frozen_analysis


def next_daily(now, zone, local_time):
    try:
        tz = ZoneInfo(zone)
        hour, minute = map(int, local_time.split(":"))
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError()
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, "时区或每日执行时间无效")
    current = now.replace(tzinfo=timezone.utc).astimezone(tz)
    # Round-trip excludes nonexistent DST times; fold=0 triggers at most once/day.
    for offset in range(3):
        day = current.date() + timedelta(days=offset)
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
        utc = candidate.astimezone(timezone.utc)
        if utc.astimezone(tz).replace(tzinfo=None) != candidate.replace(tzinfo=None):
            continue
        if utc.replace(tzinfo=None) > now:
            return utc.replace(tzinfo=None)
    raise HTTPException(422, "无法计算下次执行时间")


def view(row):
    return {"schedule_id": row.schedule_id, "revision": row.revision, "status": row.status,
            "timezone": row.timezone, "local_time": row.local_time, "next_due_at": row.next_due_at.isoformat() + "Z",
            "remaining_attempts": row.remaining_attempts, "plan": loads(row.plan_json, {}), "plan_hash": row.plan_hash,
            "pause_reason": row.pause_reason, "last_analysis_id": row.last_analysis_id,
            "authorization_note": row.authorization_note}


def create_schedule(db, *, project_id, prompt_id, timezone_name, local_time, sample_count, max_attempts, authorization_note, now=None):
    now = now or datetime.utcnow()
    prompt = db.get(Prompt, prompt_id)
    if not prompt or prompt.project_id != project_id:
        raise HTTPException(404, "问题不存在或不属于当前项目")
    if not prompt.enabled:
        raise HTTPException(409, "问题已停用")
    if not 1 <= sample_count <= 10 or not sample_count <= max_attempts <= 300 or not authorization_note.strip():
        raise HTTPException(422, "需要明确授权、每次采样数量及有限总尝试次数")
    if db.query(SinglePromptSamplingSchedule).filter_by(project_id=project_id, prompt_id=prompt_id, status="ACTIVE").first():
        raise HTTPException(409, "该问题已有运行计划，请先暂停")
    plan = {"contract_version": "sampling-schedule-v1", "project_id": project_id, "prompt_id": prompt_id,
            "prompt_text": prompt.prompt_text, "prompt_text_hash": _hash(prompt.prompt_text), "sample_count": sample_count,
            "prompt_configuration": {"intent_type": prompt.intent_type, "prompt_group": prompt.prompt_group},
            "platform": WENXIN_PLATFORM, "source_type": BROWSER_AUDIT_ENTRY_TYPE, "adapter": WENXIN_WEB_ADAPTER,
            "collection_mode": "single_independent", "automatic_retry": 0}
    row = SinglePromptSamplingSchedule(schedule_id=f"schedule-{uuid4()}", project_id=project_id, prompt_id=prompt_id,
        plan_json=dumps(plan), plan_hash=_hash(plan), timezone=timezone_name, local_time=local_time,
        next_due_at=next_daily(now, timezone_name, local_time), status="ACTIVE", remaining_attempts=max_attempts,
        authorization_note=authorization_note.strip())
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "计划创建冲突，请刷新后查看已有计划")
    return row


def pause_schedule(db, row, expected_revision):
    changed = db.execute(update(SinglePromptSamplingSchedule).where(SinglePromptSamplingSchedule.id == row.id,
        SinglePromptSamplingSchedule.revision == expected_revision).values(status="PAUSED", pause_reason="用户暂停",
        revision=expected_revision + 1)).rowcount
    if not changed:
        db.rollback()
        raise HTTPException(409, "计划已变化，请刷新")
    # Do not interrupt a browser operation mid-flight or pretend it was cancelled.
    db.commit()
    db.refresh(row)
    return row


def tick(db, now=None):
    now = now or datetime.utcnow()
    queued = []
    for row in db.query(SinglePromptSamplingSchedule).filter_by(status="ACTIVE").order_by(SinglePromptSamplingSchedule.id).all():
        plan = loads(row.plan_json, {})
        prompt = db.get(Prompt, row.prompt_id)
        previous = db.query(SinglePromptAnalysis).filter_by(analysis_id=row.last_analysis_id).one_or_none() if row.last_analysis_id else None
        failure = None
        if previous:
            failure = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.task_id == previous.task_id,
                BrowserMonitorRun.error_type.in_(NON_RETRYABLE_ERRORS | {"session_reset_failed", "session_verification_failed"})).first()
        reason = ("登录、验证码或会话隔离受阻，需人工恢复" if failure else
                  "问题配置已变化，请重新授权计划" if not prompt or not prompt.enabled or _hash(prompt.prompt_text) != plan.get("prompt_text_hash") else
                  "冻结计划校验失败" if _hash(plan) != row.plan_hash else "")
        if reason:
            row.status, row.pause_reason = "BLOCKED", reason
            row.revision += 1
            db.commit()
            continue
        if previous and previous.status in {"PLANNED", "QUEUED", "COLLECTING"}:
            continue
        if row.next_due_at > now:
            continue
        count = int(plan["sample_count"])
        if row.remaining_attempts < count:
            row.status, row.pause_reason = "EXHAUSTED", "授权尝试次数已用完"
            row.revision += 1
            db.commit()
            continue
        slot = row.next_due_at.isoformat()
        claimed = db.execute(update(SinglePromptSamplingSchedule).where(SinglePromptSamplingSchedule.id == row.id,
            SinglePromptSamplingSchedule.status == "ACTIVE", SinglePromptSamplingSchedule.revision == row.revision).values(
            revision=row.revision + 1, remaining_attempts=row.remaining_attempts - count,
            next_due_at=next_daily(now, row.timezone, row.local_time)), execution_options={"synchronize_session": False}).rowcount
        if not claimed:
            db.rollback()
            continue
        # Slot claim, finite attempt reservation, Run creation and enqueue commit together.
        analysis, _ = create_frozen_analysis(db, project_id=row.project_id, prompt_id=row.prompt_id,
            prompt_text=plan["prompt_text"], sampling_plan=plan, idempotency_key=f"{row.schedule_id}:{slot}",
            created_by=f"sampling_schedule:{row.schedule_id}")
        analysis.status = "QUEUED"
        task = db.get(BrowserMonitorTask, analysis.task_id)
        task.status = "queued"
        task.schedule_type = "single_prompt_v2_schedule"
        for run in db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).all():
            run.status, run.stage = "queued", "queued"
        row.last_analysis_id = analysis.analysis_id
        db.commit()
        db.expire_all()
        queued.append(analysis.analysis_id)
    return queued


def allow_scheduled_start(db, analysis):
    task = db.get(BrowserMonitorTask, analysis.task_id)
    if not task or task.schedule_type != "single_prompt_v2_schedule":
        return True
    row = db.query(SinglePromptSamplingSchedule).filter_by(last_analysis_id=analysis.analysis_id).one_or_none()
    prompt = db.get(Prompt, analysis.prompt_id)
    valid = row and row.status == "ACTIVE" and prompt and prompt.enabled and _hash(prompt.prompt_text) == loads(row.plan_json, {}).get("prompt_text_hash")
    if valid:
        return True
    analysis.status, task.status = "CANCELLED", "cancelled"
    for run in db.query(BrowserMonitorRun).filter_by(task_id=task.id, status="queued").all():
        run.status, run.stage = "cancelled", "cancelled"
    db.commit()
    return False
