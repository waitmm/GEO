"""Bounded sampling schedules.

Legacy schedules retain the frozen V2 analysis path. New COLLECTION_ONLY
schedules append raw BrowserMonitorTask/Run rows and never start analysis.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.models import BrowserMonitorRun, BrowserMonitorTask, Prompt, SinglePromptAnalysis, SinglePromptSamplingSchedule
from app.modules.monitoring.enums import BROWSER_AUDIT_ENTRY_TYPE, NON_RETRYABLE_ERRORS, WENXIN_PLATFORM, WENXIN_WEB_ADAPTER
from app.modules.monitoring.services import create_browser_task_from_frozen_prompt
from app.services.serialization import dumps, loads
from .service import _current_analysis_configuration, _hash, _load_prompt_version_binding, create_frozen_analysis


MISSED_SLOT_GRACE = timedelta(minutes=30)
COLLECTION_SCHEDULE_TYPE = "collection_only_schedule"
COLLECTION_PROGRESS_CONTRACT = "collection-schedule-progress-v1"


def _collection_authorized() -> bool:
    return os.getenv("GEO_BETA_SCHEDULED_SAMPLING_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def next_daily(now, zone, local_time):
    try:
        tz = ZoneInfo(zone)
        hour, minute = map(int, local_time.split(":"))
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError()
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, "时区或每日执行时间无效")
    current = now.replace(tzinfo=timezone.utc).astimezone(tz)
    for offset in range(3):
        day = current.date() + timedelta(days=offset)
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
        utc = candidate.astimezone(timezone.utc)
        if utc.astimezone(tz).replace(tzinfo=None) != candidate.replace(tzinfo=None):
            continue
        if utc.replace(tzinfo=None) > now:
            return utc.replace(tzinfo=None)
    raise HTTPException(422, "无法计算下次执行时间")


def next_occurrence(now, zone, cadence):
    kind = str((cadence or {}).get("type") or "DAILY").upper()
    if kind == "DAILY":
        return next_daily(now, zone, str(cadence.get("local_time") or "09:00"))
    if kind == "WEEKLY":
        weekday = cadence.get("weekday")
        if not isinstance(weekday, int) or isinstance(weekday, bool) or not 0 <= weekday <= 6:
            raise HTTPException(422, "每周采样需要 0 至 6 的星期设置")
        candidate = now
        for _ in range(8):
            daily = next_daily(candidate, zone, str(cadence.get("local_time") or "09:00"))
            if daily.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(zone)).weekday() == weekday:
                return daily
            candidate = daily + timedelta(seconds=1)
        raise HTTPException(422, "无法计算每周执行时间")
    if kind == "INTERVAL":
        hours = cadence.get("every_hours")
        if not isinstance(hours, int) or isinstance(hours, bool) or not 1 <= hours <= 168:
            raise HTTPException(422, "固定间隔必须为 1 至 168 小时")
        return now + timedelta(hours=hours)
    raise HTTPException(422, "采样频率仅支持每天、每周或固定小时间隔")


def _cadence(plan, row):
    value = plan.get("cadence")
    return value if isinstance(value, dict) else {"type": "DAILY", "local_time": row.local_time}


def _task_prefix(row) -> str:
    return f"sampling_schedule:{row.schedule_id}:"


def _task_slot(row, task) -> str:
    prefix = _task_prefix(row)
    return task.created_by[len(prefix):] if task.created_by.startswith(prefix) else ""


def execution_view(db, task, row=None):
    if row is None and task.created_by.startswith("sampling_schedule:"):
        schedule_id = task.created_by[len("sampling_schedule:"):].split(":", 1)[0]
        row = db.query(SinglePromptSamplingSchedule).filter_by(schedule_id=schedule_id).one_or_none()
    runs = db.query(BrowserMonitorRun).filter_by(task_id=task.id).order_by(BrowserMonitorRun.id).all()
    success = sum(run.status == "success" and bool((run.answer_text or "").strip()) for run in runs)
    partial = sum(run.status == "partial_success" and bool((run.answer_text or "").strip()) for run in runs)
    failure = sum(run.status in {"failed", "blocked", "cancelled"} for run in runs)
    if any(run.status == "running" for run in runs): status = "RUNNING"
    elif any(run.status in {"pending", "queued"} for run in runs): status = "QUEUED"
    elif runs and success == len(runs): status = "SUCCESS"
    elif success or partial: status = "PARTIAL"
    elif any(run.status == "blocked" for run in runs): status = "BLOCKED"
    elif task.status == "cancelled": status = "CANCELLED"
    else: status = "FAILED" if runs else "QUEUED"
    errors = {str(run.id): {"status": run.status, "type": run.error_type, "message": run.error_message}
              for run in runs if run.status in {"failed", "blocked", "cancelled"}}
    slot = _task_slot(row, task) if row else ""
    finished = max((run.finished_at for run in runs if run.finished_at), default=None)
    return {"execution_id": f"collection-task-{task.id}", "slot_key": slot,
            "trigger_type": "MANUAL" if slot.startswith("manual-") else "SCHEDULED",
            "due_at": task.created_at.isoformat() + "Z", "status": status,
            "analysis_id": None, "task_id": task.id, "sample_count": len(runs),
            "success_count": success, "partial_count": partial, "failure_count": failure,
            "error_summary": errors, "created_at": task.created_at.isoformat() + "Z",
            "finished_at": finished.isoformat() + "Z" if finished else None}


def executions(db, row, limit=100):
    tasks = db.query(BrowserMonitorTask).filter(
        BrowserMonitorTask.project_id == row.project_id,
        BrowserMonitorTask.schedule_type == COLLECTION_SCHEDULE_TYPE,
        BrowserMonitorTask.created_by.like(_task_prefix(row) + "%"),
    ).order_by(BrowserMonitorTask.id.desc()).limit(limit).all()
    values = [execution_view(db, task, row) for task in tasks]
    progress = loads(row.optimization_progress_json, {})
    for item in progress.get("missed_slots", []):
        values.append({"execution_id": f"missed:{item['slot_key']}", "slot_key": item["slot_key"],
            "trigger_type": "SCHEDULED", "due_at": item["due_at"], "status": "MISSED",
            "analysis_id": None, "task_id": None, "sample_count": int(item.get("sample_count") or 0),
            "success_count": 0, "partial_count": 0, "failure_count": 0,
            "error_summary": {"reason": "DEVICE_OFFLINE_OR_WORKER_STOPPED_NO_CATCH_UP"},
            "created_at": item["recorded_at"], "finished_at": item["recorded_at"]})
    return sorted(values, key=lambda item: (item["due_at"], item["execution_id"]), reverse=True)[:limit]


def sync_execution_audit(db):
    """Compatibility hook: Task/Run rows are the authoritative audit."""
    return None


def view(row, db=None):
    plan = loads(row.plan_json, {})
    history = executions(db, row) if db is not None and plan.get("automation_policy") == "COLLECTION_ONLY" else []
    finished = [item for item in history if item["status"] not in {"QUEUED", "RUNNING", "MISSED"}]
    successful = [item for item in finished if item["status"] in {"SUCCESS", "PARTIAL"}]
    return {"schedule_id": row.schedule_id, "revision": row.revision, "status": row.status,
            "timezone": row.timezone, "local_time": row.local_time, "next_due_at": row.next_due_at.isoformat() + "Z",
            "remaining_attempts": row.remaining_attempts, "plan": plan, "plan_hash": row.plan_hash,
            "cadence": _cadence(plan, row), "pause_reason": row.pause_reason,
            "last_analysis_id": row.last_analysis_id,
            "automation_policy": plan.get("automation_policy") or "LEGACY_OPTIONAL_OPTIMIZE",
            "optimization": loads(row.optimization_progress_json, {}), "authorization_note": row.authorization_note,
            "external_collection_authorized": _collection_authorized(), "last_execution": history[0] if history else None,
            "execution_summary": {"total": len(history), "finished": len(finished), "successful": len(successful),
                "missed": sum(item["status"] == "MISSED" for item in history),
                "success_rate": (len(successful) / len(finished)) if finished else None}}


def _current_prompt_snapshot(prompt: Prompt) -> dict:
    return {"project_id": prompt.project_id, "prompt_id": prompt.id, "prompt_text": prompt.prompt_text,
        "title": prompt.title, "intent_type": prompt.intent_type, "prompt_group": prompt.prompt_group,
        "enabled": prompt.enabled, "topic_id": prompt.topic_id, "cluster_id": prompt.cluster_id,
        "importance": prompt.importance, "sample_count": prompt.sample_count,
        "daily_tracking_enabled": prompt.daily_tracking_enabled,
        "daily_schedule_time": prompt.daily_schedule_time, "daily_sample_count": prompt.daily_sample_count}


def create_schedule(db, *, project_id, prompt_id, prompt_version_id, snapshot_hash,
                    timezone_name, local_time, sample_count, max_attempts,
                    authorization_note, optimization=None, collection_only=False,
                    cadence_type="DAILY", weekday=None, interval_hours=None,
                    supersedes_schedule_id=None, now=None):
    now = now or datetime.utcnow()
    prompt = db.get(Prompt, prompt_id)
    if not prompt or prompt.project_id != project_id: raise HTTPException(404, "问题不存在或不属于当前项目")
    if not prompt.enabled: raise HTTPException(409, "问题已停用")
    if not 1 <= sample_count <= 10 or not sample_count <= max_attempts <= 300 or not authorization_note.strip():
        raise HTTPException(422, "需要明确授权、每次采样数量及有限总尝试次数")
    if db.query(SinglePromptSamplingSchedule).filter_by(project_id=project_id, prompt_id=prompt_id, status="ACTIVE").first():
        raise HTTPException(409, "该问题已有运行计划，请先暂停")
    prompt_version = _load_prompt_version_binding(db, project_id=project_id, prompt_id=prompt_id,
        prompt_version_id=prompt_version_id, snapshot_hash=snapshot_hash)
    snapshot = prompt_version["snapshot"]
    if snapshot != _current_prompt_snapshot(prompt):
        raise HTTPException(409, detail={"code": "PROMPT_VERSION_NOT_CURRENT", "message": "所选 Prompt 版本不是当前有效配置，请刷新后重新授权计划"})
    cadence_type = str(cadence_type or "DAILY").upper()
    if not collection_only and cadence_type != "DAILY": raise HTTPException(422, "旧计划仅支持每日频率")
    cadence = {"type": cadence_type}
    if cadence_type in {"DAILY", "WEEKLY"}: cadence["local_time"] = local_time
    if cadence_type == "WEEKLY": cadence["weekday"] = weekday
    if cadence_type == "INTERVAL": cadence["every_hours"] = interval_hours
    next_due_at = next_occurrence(now, timezone_name, cadence)
    plan = {"contract_version": "sampling-schedule-v2" if collection_only else "sampling-schedule-v1",
        "project_id": project_id, "prompt_id": prompt_id, "prompt_text": snapshot["prompt_text"],
        "prompt_text_hash": _hash(snapshot["prompt_text"]), "prompt_version": prompt_version,
        "sample_count": sample_count, "prompt_configuration": {"intent_type": snapshot.get("intent_type", ""), "prompt_group": snapshot.get("prompt_group", "")},
        "platform": WENXIN_PLATFORM, "source_type": BROWSER_AUDIT_ENTRY_TYPE,
        "adapter": WENXIN_WEB_ADAPTER, "collection_mode": "single_independent", "automatic_retry": 0}
    if collection_only:
        if optimization: raise HTTPException(422, detail={"code": "COLLECTION_ONLY_AUTO_ANALYSIS_FORBIDDEN", "message": "持续采集计划不能自动分析"})
        plan.update({"automation_policy": "COLLECTION_ONLY", "missed_slot_policy": "SKIP_NO_CATCH_UP",
            "cadence": cadence, "supersedes_schedule_id": supersedes_schedule_id,
            "project_configuration": _current_analysis_configuration(db, project_id)})
    elif optimization:
        from .scheduled_optimization import freeze_settings
        plan["optimization"] = freeze_settings(db, project_id, snapshot["prompt_text"], optimization)
    authorized = _collection_authorized() if collection_only else True
    row = SinglePromptSamplingSchedule(schedule_id=f"schedule-{uuid4()}", project_id=project_id, prompt_id=prompt_id,
        plan_json=dumps(plan), plan_hash=_hash(plan), timezone=timezone_name, local_time=local_time,
        next_due_at=next_due_at, status="ACTIVE" if authorized else "PAUSED", remaining_attempts=max_attempts,
        authorization_note=authorization_note.strip(), pause_reason="" if authorized else "外部真实采样尚未授权；计划已保存但不会执行",
        optimization_progress_json=dumps({"contract_version": COLLECTION_PROGRESS_CONTRACT, "missed_slots": []}) if collection_only else "{}")
    db.add(row)
    try: db.commit()
    except IntegrityError: db.rollback(); raise HTTPException(409, "计划创建冲突，请刷新后查看已有计划")
    return row


def pause_schedule(db, row, expected_revision):
    changed = db.execute(update(SinglePromptSamplingSchedule).where(SinglePromptSamplingSchedule.id == row.id,
        SinglePromptSamplingSchedule.revision == expected_revision).values(status="PAUSED", pause_reason="用户暂停", revision=expected_revision + 1)).rowcount
    if not changed: db.rollback(); raise HTTPException(409, "计划已变化，请刷新")
    db.commit(); db.refresh(row)
    if loads(row.plan_json, {}).get("automation_policy") == "COLLECTION_ONLY":
        tasks = db.query(BrowserMonitorTask).filter(BrowserMonitorTask.schedule_type == COLLECTION_SCHEDULE_TYPE,
            BrowserMonitorTask.created_by.like(_task_prefix(row) + "%"), BrowserMonitorTask.status == "queued").all()
        for task in tasks:
            task.status = "cancelled"
            for run in db.query(BrowserMonitorRun).filter_by(task_id=task.id, status="queued").all():
                run.status, run.stage, run.finished_at = "cancelled", "cancelled", datetime.utcnow()
        if tasks: db.commit()
    else:
        from .scheduled_optimization import cancel_pending_handoffs
        cancel_pending_handoffs(db, row)
    return row


def resume_schedule(db, row, expected_revision, now=None):
    now = now or datetime.utcnow()
    if row.status != "PAUSED": raise HTTPException(409, "只有已暂停计划可以恢复")
    if loads(row.plan_json, {}).get("automation_policy") == "COLLECTION_ONLY" and not _collection_authorized():
        raise HTTPException(403, detail={"code": "EXTERNAL_COLLECTION_NOT_AUTHORIZED", "message": "本机尚未配置真实采样授权"})
    if row.remaining_attempts <= 0: raise HTTPException(409, "计划授权尝试次数已用完")
    if db.query(SinglePromptSamplingSchedule).filter(SinglePromptSamplingSchedule.project_id == row.project_id,
        SinglePromptSamplingSchedule.prompt_id == row.prompt_id, SinglePromptSamplingSchedule.status == "ACTIVE",
        SinglePromptSamplingSchedule.id != row.id).first(): raise HTTPException(409, "该问题已有其他运行计划")
    plan = loads(row.plan_json, {})
    changed = db.execute(update(SinglePromptSamplingSchedule).where(SinglePromptSamplingSchedule.id == row.id,
        SinglePromptSamplingSchedule.revision == expected_revision, SinglePromptSamplingSchedule.status == "PAUSED")
        .values(status="ACTIVE", pause_reason="", next_due_at=next_occurrence(now, row.timezone, _cadence(plan, row)), revision=expected_revision + 1)).rowcount
    if not changed: db.rollback(); raise HTTPException(409, "计划已变化，请刷新")
    db.commit(); db.refresh(row); return row


def replace_schedule(db, row, expected_revision, **values):
    if row.status not in {"ACTIVE", "PAUSED", "BLOCKED", "EXHAUSTED"}: raise HTTPException(409, "当前计划状态不允许编辑")
    changed = db.execute(update(SinglePromptSamplingSchedule).where(SinglePromptSamplingSchedule.id == row.id,
        SinglePromptSamplingSchedule.revision == expected_revision).values(status="SUPERSEDED", pause_reason="已由新计划替代",
        revision=expected_revision + 1), execution_options={"synchronize_session": False}).rowcount
    if not changed: db.rollback(); raise HTTPException(409, "计划已变化，请刷新")
    try: return create_schedule(db, project_id=row.project_id, prompt_id=row.prompt_id, collection_only=True, supersedes_schedule_id=row.schedule_id, **values)
    except Exception: db.rollback(); raise


def _queue_collection_task(db, row, plan, slot_key):
    created_by = _task_prefix(row) + slot_key
    existing = db.query(BrowserMonitorTask).filter_by(schedule_type=COLLECTION_SCHEDULE_TYPE, created_by=created_by).one_or_none()
    if existing: return existing
    task = create_browser_task_from_frozen_prompt(db, project_id=row.project_id, prompt_id=row.prompt_id,
        prompt_text=plan["prompt_text"], run_count=int(plan["sample_count"]), execute_now=False,
        platform=str(plan["platform"]), source_type=str(plan["source_type"]), adapter=str(plan["adapter"]),
        collection_mode=str(plan["collection_mode"]), schedule_type=COLLECTION_SCHEDULE_TYPE, created_by=created_by, commit=False)
    task.status = "queued"
    for run in db.query(BrowserMonitorRun).filter_by(task_id=task.id).all(): run.status, run.stage = "queued", "queued"
    return task


def queue_immediate(db, row, expected_revision, idempotency_key, now=None):
    if not _collection_authorized(): raise HTTPException(403, detail={"code": "EXTERNAL_COLLECTION_NOT_AUTHORIZED", "message": "本机尚未配置真实采样授权"})
    if row.status != "ACTIVE": raise HTTPException(409, "只有运行中的计划可以立即采集")
    plan = loads(row.plan_json, {})
    if plan.get("automation_policy") != "COLLECTION_ONLY": raise HTTPException(409, "立即采集仅适用于采集与分析解耦计划")
    # BrowserMonitorTask.created_by is bounded; retain idempotency without
    # embedding arbitrary caller text or overflowing the audit field.
    slot = "manual-" + _hash(idempotency_key)[:32]
    existing = db.query(BrowserMonitorTask).filter_by(schedule_type=COLLECTION_SCHEDULE_TYPE, created_by=_task_prefix(row) + slot).one_or_none()
    if existing: return existing
    count = int(plan.get("sample_count") or 0)
    if count <= 0 or row.remaining_attempts < count: raise HTTPException(409, "计划剩余采样授权不足")
    claimed = db.execute(update(SinglePromptSamplingSchedule).where(SinglePromptSamplingSchedule.id == row.id,
        SinglePromptSamplingSchedule.status == "ACTIVE", SinglePromptSamplingSchedule.revision == expected_revision)
        .values(revision=expected_revision + 1, remaining_attempts=row.remaining_attempts - count), execution_options={"synchronize_session": False}).rowcount
    if not claimed: db.rollback(); raise HTTPException(409, "计划已变化，请刷新")
    task = _queue_collection_task(db, row, plan, slot); db.commit(); db.refresh(task); return task


def _record_missed(row, due_at, count, now):
    progress = loads(row.optimization_progress_json, {})
    if progress.get("contract_version") != COLLECTION_PROGRESS_CONTRACT: progress = {"contract_version": COLLECTION_PROGRESS_CONTRACT, "missed_slots": []}
    key = due_at.isoformat()
    if not any(item.get("slot_key") == key for item in progress["missed_slots"]):
        progress["missed_slots"].append({"slot_key": key, "due_at": key + "Z", "recorded_at": now.isoformat() + "Z", "sample_count": count})
        progress["missed_slots"] = progress["missed_slots"][-200:]
    row.optimization_progress_json = dumps(progress)


def tick(db, now=None):
    now = now or datetime.utcnow(); queued = []
    for row in db.query(SinglePromptSamplingSchedule).filter_by(status="ACTIVE").order_by(SinglePromptSamplingSchedule.id).all():
        plan = loads(row.plan_json, {}); collection_only = plan.get("automation_policy") == "COLLECTION_ONLY"
        if collection_only and not _collection_authorized():
            row.status, row.pause_reason, row.revision = "PAUSED", "外部真实采样授权已关闭", row.revision + 1; db.commit(); continue
        prompt = db.get(Prompt, row.prompt_id)
        previous = None if collection_only else (db.query(SinglePromptAnalysis).filter_by(analysis_id=row.last_analysis_id).one_or_none() if row.last_analysis_id else None)
        failure = None
        if previous:
            failure = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.task_id == previous.task_id,
                BrowserMonitorRun.error_type.in_(NON_RETRYABLE_ERRORS | {"session_reset_failed", "session_verification_failed"})).first()
        try:
            frozen = plan.get("prompt_version") or {}
            version_valid = frozen.get("binding_status") == "BOUND" and frozen == _load_prompt_version_binding(db,
                project_id=row.project_id, prompt_id=row.prompt_id, prompt_version_id=frozen.get("prompt_version_id"), snapshot_hash=frozen.get("snapshot_hash"))
        except (HTTPException, TypeError): version_valid = False
        reason = ("登录、验证码或会话隔离受阻，需人工恢复" if failure else
            "问题配置已变化，请重新授权计划" if not prompt or not prompt.enabled or not version_valid or _hash(prompt.prompt_text) != plan.get("prompt_text_hash") else
            "冻结计划校验失败" if _hash(plan) != row.plan_hash else "")
        if reason: row.status, row.pause_reason, row.revision = "BLOCKED", reason, row.revision + 1; db.commit(); continue
        if collection_only:
            active = db.query(BrowserMonitorTask).filter(BrowserMonitorTask.schedule_type == COLLECTION_SCHEDULE_TYPE,
                BrowserMonitorTask.created_by.like(_task_prefix(row) + "%"), BrowserMonitorTask.status.in_(["queued", "running"])).first()
            if active: continue
        else:
            if previous and previous.status in {"PLANNED", "QUEUED", "COLLECTING"}: continue
            from .scheduled_optimization import handoff
            handoff(db, row, previous); db.refresh(row)
            if row.status != "ACTIVE": continue
        if row.next_due_at > now: continue
        count = int(plan["sample_count"])
        if collection_only:
            while row.next_due_at < now - MISSED_SLOT_GRACE:
                _record_missed(row, row.next_due_at, count, now)
                row.next_due_at = next_occurrence(row.next_due_at, row.timezone, _cadence(plan, row)); row.revision += 1
            db.commit(); db.refresh(row)
            if row.next_due_at > now: continue
        if row.remaining_attempts < count: row.status, row.pause_reason, row.revision = "EXHAUSTED", "授权尝试次数已用完", row.revision + 1; db.commit(); continue
        due = row.next_due_at; slot = due.isoformat()
        claimed = db.execute(update(SinglePromptSamplingSchedule).where(SinglePromptSamplingSchedule.id == row.id,
            SinglePromptSamplingSchedule.status == "ACTIVE", SinglePromptSamplingSchedule.revision == row.revision)
            .values(revision=row.revision + 1, remaining_attempts=row.remaining_attempts - count,
                next_due_at=next_occurrence(due, row.timezone, _cadence(plan, row))), execution_options={"synchronize_session": False}).rowcount
        if not claimed: db.rollback(); continue
        if collection_only:
            task = _queue_collection_task(db, row, plan, slot); identity = f"collection:{task.id}"
        else:
            analysis, _ = create_frozen_analysis(db, project_id=row.project_id, prompt_id=row.prompt_id,
                prompt_text=plan["prompt_text"], sampling_plan=plan, idempotency_key=f"{row.schedule_id}:{slot}", created_by=f"sampling_schedule:{row.schedule_id}")
            analysis.status = "QUEUED"; task = db.get(BrowserMonitorTask, analysis.task_id); task.status = "queued"; task.schedule_type = "single_prompt_v2_schedule"
            for run in db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).all(): run.status, run.stage = "queued", "queued"
            row.last_analysis_id = analysis.analysis_id; identity = analysis.analysis_id
        db.commit(); db.expire_all(); queued.append(identity)
    return queued


def allow_scheduled_start(db, analysis):
    task = db.get(BrowserMonitorTask, analysis.task_id)
    if not task or task.schedule_type != "single_prompt_v2_schedule": return True
    row = db.query(SinglePromptSamplingSchedule).filter_by(last_analysis_id=analysis.analysis_id).one_or_none()
    prompt = db.get(Prompt, analysis.prompt_id); plan = loads(row.plan_json, {}) if row else {}
    try:
        frozen = plan.get("prompt_version") or {}; version_valid = frozen.get("binding_status") == "BOUND" and frozen == _load_prompt_version_binding(db,
            project_id=analysis.project_id, prompt_id=analysis.prompt_id, prompt_version_id=frozen.get("prompt_version_id"), snapshot_hash=frozen.get("snapshot_hash"))
    except HTTPException: version_valid = False
    if row and row.status == "ACTIVE" and prompt and prompt.enabled and version_valid and _hash(prompt.prompt_text) == plan.get("prompt_text_hash"): return True
    analysis.status, task.status = "CANCELLED", "cancelled"
    for run in db.query(BrowserMonitorRun).filter_by(task_id=task.id, status="queued").all(): run.status, run.stage = "cancelled", "cancelled"
    db.commit(); return False


def allow_collection_start(db, task):
    if not task or task.schedule_type != COLLECTION_SCHEDULE_TYPE: return True
    if not _collection_authorized(): return _cancel_collection(db, task)
    schedule_id = task.created_by[len("sampling_schedule:"):].split(":", 1)[0] if task.created_by.startswith("sampling_schedule:") else ""
    row = db.query(SinglePromptSamplingSchedule).filter_by(schedule_id=schedule_id).one_or_none()
    plan = loads(row.plan_json, {}) if row else {}; prompt = db.get(Prompt, row.prompt_id) if row else None
    try:
        frozen = plan.get("prompt_version") or {}; version_valid = frozen.get("binding_status") == "BOUND" and frozen == _load_prompt_version_binding(db,
            project_id=row.project_id, prompt_id=row.prompt_id, prompt_version_id=frozen.get("prompt_version_id"), snapshot_hash=frozen.get("snapshot_hash"))
    except (HTTPException, TypeError): version_valid = False
    valid = bool(row and row.status == "ACTIVE" and plan.get("automation_policy") == "COLLECTION_ONLY" and _hash(plan) == row.plan_hash
        and prompt and prompt.enabled and version_valid and _hash(prompt.prompt_text) == plan.get("prompt_text_hash"))
    if valid: return True
    return _cancel_collection(db, task)


def _cancel_collection(db, task):
    task.status = "cancelled"
    for run in db.query(BrowserMonitorRun).filter_by(task_id=task.id, status="queued").all():
        run.status, run.stage, run.finished_at = "cancelled", "cancelled", datetime.utcnow()
    db.commit(); return False
