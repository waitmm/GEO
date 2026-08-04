from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import BrowserMonitorRun, BrowserMonitorTask, MonitoringBatch, Project, Prompt
from app.modules.monitoring.enums import BROWSER_AUDIT_ENTRY_TYPE, WENXIN_PLATFORM, WENXIN_WEB_ADAPTER
from app.modules.monitoring.schemas import BrowserTaskRead
from app.services.serialization import dumps, loads


def task_to_read(db: Session, task: BrowserMonitorTask) -> BrowserTaskRead:
    queued_run_count = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.task_id == task.id).count()
    return BrowserTaskRead(
        id=task.id,
        project_id=task.project_id,
        batch_id=task.batch_id,
        platform=task.platform,
        source_type=task.source_type,
        adapter=task.adapter,
        question_ids=loads(task.question_ids_json, []),
        run_count=task.run_count,
        schedule_type=task.schedule_type,
        status=task.status,
        created_at=task.created_at,
        updated_at=task.updated_at,
        queued_run_count=queued_run_count,
    )


def create_browser_task(
    db: Session,
    project: Project,
    prompts: list[Prompt],
    run_count: int,
    execute_now: bool,
    platform: str = WENXIN_PLATFORM,
    source_type: str = BROWSER_AUDIT_ENTRY_TYPE,
    adapter: str = WENXIN_WEB_ADAPTER,
    batch_id: int | None = None,
    schedule_type: str = "manual",
) -> BrowserMonitorTask:
    batch = db.get(MonitoringBatch, batch_id) if batch_id else None
    task = BrowserMonitorTask(
        project_id=project.id,
        batch_id=batch_id,
        platform=platform,
        source_type=source_type,
        adapter=adapter,
        question_ids_json=dumps([prompt.id for prompt in prompts]),
        run_count=run_count,
        schedule_type=schedule_type,
        status="queued" if execute_now else "pending",
    )
    db.add(task)
    db.flush()

    for prompt in prompts:
        for sequence in range(1, run_count + 1):
            db.add(
                BrowserMonitorRun(
                    task_id=task.id,
                    project_id=project.id,
                    batch_id=batch_id,
                    prompt_id=prompt.id,
                    platform=platform,
                    source_type=source_type,
                    adapter=adapter,
                    run_sequence=sequence,
                    sample_index=sequence,
                    collection_mode=batch.collection_mode if batch else "single_continuous",
                    status="queued" if execute_now else "pending",
                    stage="queued",
                    original_query=prompt.prompt_text,
                )
            )

    db.commit()
    db.refresh(task)
    return task


def queue_due_daily_prompt_tasks(
    db: Session,
    project: Project,
    execute_now: bool = False,
) -> tuple[list[BrowserMonitorTask], int]:
    now = datetime.utcnow()
    today_key = now.date().isoformat()
    prompts = (
        db.query(Prompt)
        .filter(
            Prompt.project_id == project.id,
            Prompt.enabled == True,  # noqa: E712
            Prompt.daily_tracking_enabled == True,  # noqa: E712
        )
        .order_by(Prompt.id.asc())
        .all()
    )
    due_prompts = [
        prompt for prompt in prompts
        if not prompt.last_scheduled_at or prompt.last_scheduled_at.date().isoformat() < today_key
    ]
    if not due_prompts:
        return [], 0

    grouped: dict[int, list[Prompt]] = {}
    for prompt in due_prompts:
        sample_count = max(1, int(prompt.daily_sample_count or 1))
        grouped.setdefault(sample_count, []).append(prompt)

    tasks: list[BrowserMonitorTask] = []
    queued_count = 0
    for sample_count, group in grouped.items():
        batch = MonitoringBatch(
            project_id=project.id,
            name=f"每日 Prompt 监测 {today_key} · Sample={sample_count}",
            platform=WENXIN_PLATFORM,
            collection_mode="single_continuous",
            sample_count=sample_count,
            status="queued" if execute_now else "pending",
            notes="daily_prompt_tracking",
        )
        db.add(batch)
        db.flush()
        task = create_browser_task(
            db,
            project,
            group,
            sample_count,
            execute_now,
            platform=WENXIN_PLATFORM,
            source_type=BROWSER_AUDIT_ENTRY_TYPE,
            adapter=WENXIN_WEB_ADAPTER,
            batch_id=batch.id,
            schedule_type="daily",
        )
        tasks.append(task)
        queued_count += db.query(BrowserMonitorRun).filter(BrowserMonitorRun.task_id == task.id).count()

    for prompt in due_prompts:
        prompt.last_scheduled_at = now
    db.commit()
    return tasks, queued_count


def update_task_status_from_runs(db: Session, task: BrowserMonitorTask) -> BrowserMonitorTask:
    runs = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.task_id == task.id).all()
    if not runs:
        task.status = "pending"
    elif all(run.status == "success" for run in runs):
        task.status = "completed"
    elif any(run.status in {"success", "partial_success"} for run in runs):
        task.status = "partial_completed"
    elif all(run.status == "failed" for run in runs):
        task.status = "failed"
    elif all(run.status == "blocked" for run in runs):
        task.status = "blocked"
    elif any(run.status == "running" for run in runs):
        task.status = "running"
    else:
        task.status = "queued"
    db.commit()
    db.refresh(task)
    return task
