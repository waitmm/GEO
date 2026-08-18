from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import BrowserMonitorRun, BrowserMonitorTask, MonitoringBatch, Project, Prompt, ReferenceSource, RetrievalCandidate, RunArtifact
from app.modules.monitoring.enums import BROWSER_AUDIT_ENTRY_TYPE, NON_RETRYABLE_ERRORS, WENXIN_PLATFORM, WENXIN_WEB_ADAPTER
from app.modules.monitoring.executor import MonitoringTaskExecutor
from app.modules.monitoring.importers import import_wenxin_plugin_payload
from app.modules.monitoring.schemas import (
    BrowserQueueSummaryRead,
    RunArtifactContentRead,
    BrowserRunDetailRead,
    BrowserRunRead,
    BrowserTaskCreate,
    BrowserTaskCreateResponse,
    BrowserTaskRead,
    WenxinPluginImportRequest,
)
from app.modules.monitoring.services import (
    create_browser_task,
    materialize_independent_prompts,
    queue_due_daily_prompt_tasks,
    task_to_read,
    update_task_status_from_runs,
)


router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.post("/tasks", response_model=BrowserTaskCreateResponse)
def create_task(payload: BrowserTaskCreate, db: Session = Depends(get_db)) -> BrowserTaskCreateResponse:
    if payload.platform != WENXIN_PLATFORM or payload.source_type != BROWSER_AUDIT_ENTRY_TYPE or payload.adapter != WENXIN_WEB_ADAPTER:
        raise HTTPException(status_code=400, detail="MVP阶段仅支持 platform=wenxin, source_type=browser_audit, adapter=wenxin_web_audit")
    project = db.get(Project, payload.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    batch = None
    if payload.batch_id is not None:
        batch = db.get(MonitoringBatch, payload.batch_id)
        if not batch or batch.project_id != project.id:
            raise HTTPException(status_code=400, detail="监测批次不属于当前项目")
    prompt_rows = db.query(Prompt).filter(Prompt.project_id == project.id, Prompt.id.in_(payload.question_ids)).all()
    prompt_by_id = {prompt.id: prompt for prompt in prompt_rows}
    prompts = [prompt_by_id[prompt_id] for prompt_id in payload.question_ids if prompt_id in prompt_by_id]
    if not prompts:
        raise HTTPException(status_code=400, detail="未选择有效问题")
    prompts = materialize_independent_prompts(db, prompts)

    run_count = batch.sample_count if batch else payload.run_count
    task = create_browser_task(
        db, project, prompts, run_count, payload.execute_now,
        payload.platform, payload.source_type, payload.adapter, payload.batch_id,
    )
    queued_run_count = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.task_id == task.id).count()
    if payload.execute_now:
        executor = MonitoringTaskExecutor()
        try:
            executor.execute_queued_runs(db, task.id)
        finally:
            executor.close()
        update_task_status_from_runs(db, task)
    return BrowserTaskCreateResponse(task_ids=[task.id], queued_run_count=queued_run_count)


@router.post("/daily-schedules/queue", response_model=BrowserTaskCreateResponse)
def queue_daily_schedules(
    project_id: int = Query(...),
    execute_now: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> BrowserTaskCreateResponse:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    tasks, queued_run_count = queue_due_daily_prompt_tasks(db, project, execute_now=execute_now)
    if execute_now:
        executor = MonitoringTaskExecutor()
        try:
            for task in tasks:
                executor.execute_queued_runs(db, task.id)
                update_task_status_from_runs(db, task)
        finally:
            executor.close()
    return BrowserTaskCreateResponse(task_ids=[task.id for task in tasks], queued_run_count=queued_run_count)


@router.post("/queue/execute")
def execute_queue(
    project_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(BrowserMonitorRun).filter(
        BrowserMonitorRun.status.in_(["queued", "pending"]),
        BrowserMonitorRun.platform == WENXIN_PLATFORM,
        BrowserMonitorRun.source_type == BROWSER_AUDIT_ENTRY_TYPE,
        BrowserMonitorRun.adapter == WENXIN_WEB_ADAPTER,
    )
    if project_id is not None:
        query = query.filter(BrowserMonitorRun.project_id == project_id)
    runs = query.order_by(BrowserMonitorRun.task_id.asc(), BrowserMonitorRun.run_sequence.asc(), BrowserMonitorRun.id.asc()).all()

    # 按 (task_id, run_sequence) 分组；独立模式会在组内每条 Prompt 前强制新对话。
    groups: dict[tuple, list[BrowserMonitorRun]] = {}
    for run in runs:
        key = (run.task_id, run.run_sequence)
        if key not in groups:
            groups[key] = []
        groups[key].append(run)

    executor = MonitoringTaskExecutor()
    executed = 0
    try:
        for group_runs in groups.values():
            executed += executor._execute_run_group(db, group_runs)
    finally:
        executor.close()
    return {"executed": executed}


@router.get("/queue-summary", response_model=BrowserQueueSummaryRead)
def get_queue_summary(project_id: Optional[int] = Query(default=None), db: Session = Depends(get_db)) -> BrowserQueueSummaryRead:
    query = db.query(BrowserMonitorRun).filter(
        BrowserMonitorRun.platform == WENXIN_PLATFORM,
        BrowserMonitorRun.source_type == BROWSER_AUDIT_ENTRY_TYPE,
        BrowserMonitorRun.adapter == WENXIN_WEB_ADAPTER,
    )
    if project_id is not None:
        query = query.filter(BrowserMonitorRun.project_id == project_id)
    runs = query.all()
    counts = {status: 0 for status in ["queued", "pending", "running", "success", "partial_success", "failed", "blocked"]}
    for run in runs:
        if run.status in counts:
            counts[run.status] += 1
    latest = max(runs, key=lambda item: item.id) if runs else None
    return BrowserQueueSummaryRead(
        project_id=project_id,
        queued=counts["queued"],
        pending=counts["pending"],
        running=counts["running"],
        success=counts["success"],
        partial_success=counts["partial_success"],
        failed=counts["failed"],
        blocked=counts["blocked"],
        total=len(runs),
        latest_run_id=latest.id if latest else None,
        latest_status=latest.status if latest else "",
        latest_stage=latest.stage if latest else "",
        latest_error_type=latest.error_type if latest else "",
    )


@router.post("/tasks/{task_id}/execute", response_model=BrowserTaskRead)
def execute_task(task_id: int, db: Session = Depends(get_db)) -> BrowserTaskRead:
    task = db.get(BrowserMonitorTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    executor = MonitoringTaskExecutor()
    try:
        executor.execute_queued_runs(db, task.id)
    finally:
        executor.close()
    update_task_status_from_runs(db, task)
    db.refresh(task)
    return task_to_read(db, task)


@router.get("/tasks", response_model=list[BrowserTaskRead])
def list_tasks(
    project_id: Optional[int] = Query(default=None),
    platform: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> list[BrowserTaskRead]:
    query = db.query(BrowserMonitorTask)
    if project_id is not None:
        query = query.filter(BrowserMonitorTask.project_id == project_id)
    if platform:
        query = query.filter(BrowserMonitorTask.platform == platform)
    if status:
        query = query.filter(BrowserMonitorTask.status == status)
    tasks = query.order_by(BrowserMonitorTask.id.desc()).all()
    return [task_to_read(db, task) for task in tasks]


@router.get("/runs", response_model=list[BrowserRunRead])
def list_runs(
    project_id: Optional[int] = Query(default=None),
    question_id: Optional[int] = Query(default=None),
    platform: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> list[BrowserMonitorRun]:
    query = db.query(BrowserMonitorRun)
    if project_id is not None:
        query = query.filter(BrowserMonitorRun.project_id == project_id)
    if question_id is not None:
        query = query.filter(BrowserMonitorRun.prompt_id == question_id)
    if platform:
        query = query.filter(BrowserMonitorRun.platform == platform)
    if status:
        query = query.filter(BrowserMonitorRun.status == status)
    return (
        query.order_by(
            BrowserMonitorRun.task_id.desc(),
            BrowserMonitorRun.run_sequence.asc(),
            BrowserMonitorRun.id.asc(),
        )
        .limit(200)
        .all()
    )


@router.get("/runs/{run_id}", response_model=BrowserRunDetailRead)
def get_run(run_id: int, db: Session = Depends(get_db)) -> BrowserRunDetailRead:
    run = db.get(BrowserMonitorRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行不存在")
    return _run_detail(db, run)


@router.get("/artifacts/{artifact_id}", response_model=RunArtifactContentRead)
def get_artifact_content(artifact_id: int, db: Session = Depends(get_db)) -> RunArtifactContentRead:
    artifact = db.get(RunArtifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="证据文件不存在")

    path = Path(artifact.storage_path)
    if not path.is_absolute():
        path = Path(get_settings().monitoring_artifact_dir).parent.parent / path
    if not path.exists():
        raise HTTPException(status_code=404, detail="证据文件未找到")

    if artifact.mime_type.startswith("image/") or artifact.artifact_type == "page_screenshot":
        content = f"data:{artifact.mime_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
        return RunArtifactContentRead(
            id=artifact.id,
            run_id=artifact.run_id,
            artifact_type=artifact.artifact_type,
            storage_path=artifact.storage_path,
            mime_type=artifact.mime_type,
            size_bytes=artifact.size_bytes,
            content=content,
            truncated=False,
        )

    max_chars = 10_000_000
    content = path.read_text(encoding="utf-8", errors="replace")
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars]
    return RunArtifactContentRead(
        id=artifact.id,
        run_id=artifact.run_id,
        artifact_type=artifact.artifact_type,
        storage_path=artifact.storage_path,
        mime_type=artifact.mime_type,
        size_bytes=artifact.size_bytes,
        content=content,
        truncated=truncated,
    )


@router.post("/imports/wenxin-plugin", response_model=BrowserRunDetailRead)
def import_wenxin_plugin(payload: WenxinPluginImportRequest, db: Session = Depends(get_db)) -> BrowserRunDetailRead:
    try:
        run = import_wenxin_plugin_payload(db, payload.project_id, payload.payload, payload.prompt_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _run_detail(db, run)


def claim_run_for_retry(db: Session, run_id: int) -> BrowserMonitorRun:
    """原子占用一个 failed run 用于重试（compare-and-set，并发安全）。

    - 仅允许 status == "failed" 的 run 被重试；该约束由 UPDATE 的 WHERE 子句在
      数据库层面保证，两个并发 retry 请求只有第一个能成功，第二个匹配 0 行。
    - queued / pending / running / success / partial_success / blocked 全部拒绝。
    - 直接 CAS 到 running（而非经过 queued），避免在 queued 已提交、execute_run
      尚未切换 running 的窗口里被 queue worker 的 queued/pending 查询重复捞走。
    - 成功后返回已被占用的 run（status=running, retry_count 已 +1）。
    """
    run = db.get(BrowserMonitorRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行不存在")
    if run.error_type in NON_RETRYABLE_ERRORS:
        raise HTTPException(status_code=400, detail="该错误类型不支持自动重试")
    claimed = db.execute(
        update(BrowserMonitorRun)
        .where(BrowserMonitorRun.id == run_id, BrowserMonitorRun.status == "failed")
        .values(
            status="running",
            stage="launching_browser",
            retry_count=BrowserMonitorRun.retry_count + 1,
            error_type="",
            error_message="",
            error_stage="",
            blocked_type="",
            blocked_reason="",
            outcome_category="",
        )
    )
    db.commit()
    if claimed.rowcount == 0:
        # 运行已不存在或已被其他请求/worker 占用，返回当前实际状态供排查。
        db.expire_all()
        current = db.get(BrowserMonitorRun, run_id)
        if not current:
            raise HTTPException(status_code=404, detail="运行不存在")
        raise HTTPException(status_code=409, detail=f"当前状态 {current.status} 不支持重试，仅 failed 状态可重试")
    db.refresh(run)
    return run


@router.post("/runs/{run_id}/retry", response_model=BrowserRunRead)
def retry_run(run_id: int, db: Session = Depends(get_db)) -> BrowserMonitorRun:
    run = claim_run_for_retry(db, run_id)
    executor = MonitoringTaskExecutor()
    try:
        executor.execute_run(db, run.id)
    finally:
        executor.close()
    db.refresh(run)
    return run


def _run_detail(db: Session, run: BrowserMonitorRun) -> BrowserRunDetailRead:
    return BrowserRunDetailRead(
        **BrowserRunRead.model_validate(run).model_dump(),
        references=db.query(ReferenceSource).filter(ReferenceSource.run_id == run.id).order_by(ReferenceSource.reference_index.asc()).all(),
        retrieval_candidates=db.query(RetrievalCandidate).filter(RetrievalCandidate.run_id == run.id).order_by(RetrievalCandidate.rank.asc()).all(),
        artifacts=db.query(RunArtifact).filter(RunArtifact.run_id == run.id).order_by(RunArtifact.id.asc()).all(),
    )
