from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Callable
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    BrowserMonitorRun,
    BrowserMonitorTask,
    Project,
    Prompt,
    ReferenceSource,
    RetrievalCandidate,
    RunArtifact,
    SinglePromptAnalysis,
    SinglePromptAnalysisContext,
)
from app.modules.monitoring.enums import BROWSER_AUDIT_ENTRY_TYPE, WENXIN_PLATFORM, WENXIN_WEB_ADAPTER
from app.modules.monitoring.executor import MonitoringTaskExecutor
from app.modules.monitoring.services import (
    create_browser_task,
    create_browser_task_from_frozen_prompt,
    update_task_status_from_runs,
)
from app.services.serialization import dumps, loads


TERMINAL_RUN_STATUSES = {"success", "partial_success", "failed", "blocked"}
VALID_RUN_STATUSES = {"success", "partial_success"}
ACTIVE_ANALYSIS_STATUSES = {"QUEUED", "COLLECTING"}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return f"{value.isoformat()}Z" if value else None


def create_analysis(
    db: Session,
    *,
    project_id: int,
    prompt_id: int,
    sample_count: int,
    idempotency_key: str,
) -> tuple[SinglePromptAnalysis, bool]:
    project = db.get(Project, project_id)
    prompt = db.get(Prompt, prompt_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not prompt or prompt.project_id != project_id:
        raise HTTPException(status_code=404, detail="Prompt 不存在或不属于当前项目")

    plan = {
        "contract_version": "single-prompt-sampling-plan-v1",
        "project_id": project_id,
        "prompt_id": prompt_id,
        "prompt_text": prompt.prompt_text,
        "sample_count": sample_count,
        "platform": WENXIN_PLATFORM,
        "source_type": BROWSER_AUDIT_ENTRY_TYPE,
        "adapter": WENXIN_WEB_ADAPTER,
        "collection_mode": "single_independent",
    }
    plan_hash = _hash(plan)
    existing = (
        db.query(SinglePromptAnalysis)
        .filter(
            SinglePromptAnalysis.project_id == project_id,
            SinglePromptAnalysis.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing:
        if existing.sampling_plan_hash != plan_hash:
            raise HTTPException(status_code=409, detail="幂等键已用于不同的 Prompt 或采样计划")
        return existing, False

    analysis_id = str(uuid4())
    task = create_browser_task(
        db,
        project,
        [prompt],
        sample_count,
        True,
        platform=WENXIN_PLATFORM,
        source_type=BROWSER_AUDIT_ENTRY_TYPE,
        adapter=WENXIN_WEB_ADAPTER,
        schedule_type="single_prompt_v2",
        created_by=f"single_prompt_v2:{analysis_id}",
        commit=False,
    )
    analysis = SinglePromptAnalysis(
        analysis_id=analysis_id,
        project_id=project_id,
        prompt_id=prompt_id,
        task_id=task.id,
        idempotency_key=idempotency_key,
        prompt_text_snapshot=prompt.prompt_text,
        sampling_plan_json=_canonical_json(plan),
        sampling_plan_hash=plan_hash,
        status="QUEUED",
    )
    db.add(analysis)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = (
            db.query(SinglePromptAnalysis)
            .filter(
                SinglePromptAnalysis.project_id == project_id,
                SinglePromptAnalysis.idempotency_key == idempotency_key,
            )
            .first()
        )
        if concurrent and concurrent.sampling_plan_hash == plan_hash:
            return concurrent, False
        raise
    db.refresh(analysis)
    return analysis, True


def create_frozen_analysis(
    db: Session,
    *,
    project_id: int,
    prompt_id: int,
    prompt_text: str,
    sampling_plan: dict[str, Any],
    idempotency_key: str,
    created_by: str,
) -> tuple[SinglePromptAnalysis, bool]:
    """Create a planned V2 analysis exclusively from an already frozen plan."""

    required = {"sample_count", "platform", "source_type", "adapter", "collection_mode", "prompt_text_hash"}
    missing = sorted(required - set(sampling_plan))
    if missing:
        raise HTTPException(status_code=422, detail=f"冻结采样计划缺少字段：{', '.join(missing)}")
    if _hash(prompt_text) != sampling_plan["prompt_text_hash"]:
        raise HTTPException(status_code=409, detail="冻结 Prompt 文本与采样计划 Hash 不一致")
    if sampling_plan.get("project_id") != project_id or sampling_plan.get("prompt_id") != prompt_id:
        raise HTTPException(status_code=409, detail="冻结采样计划归属不匹配")
    plan_hash = _hash(sampling_plan)
    existing = db.query(SinglePromptAnalysis).filter(
        SinglePromptAnalysis.project_id == project_id,
        SinglePromptAnalysis.idempotency_key == idempotency_key,
    ).one_or_none()
    if existing:
        if existing.sampling_plan_hash != plan_hash:
            raise HTTPException(status_code=409, detail="幂等键已用于不同的冻结采样计划")
        return existing, False

    analysis_id = str(uuid4())
    task = create_browser_task_from_frozen_prompt(
        db,
        project_id=project_id,
        prompt_id=prompt_id,
        prompt_text=prompt_text,
        run_count=int(sampling_plan["sample_count"]),
        execute_now=False,
        platform=str(sampling_plan["platform"]),
        source_type=str(sampling_plan["source_type"]),
        adapter=str(sampling_plan["adapter"]),
        collection_mode=str(sampling_plan["collection_mode"]),
        schedule_type="single_prompt_v2_retest",
        created_by=created_by,
        commit=False,
    )
    analysis = SinglePromptAnalysis(
        analysis_id=analysis_id,
        project_id=project_id,
        prompt_id=prompt_id,
        task_id=task.id,
        idempotency_key=idempotency_key,
        prompt_text_snapshot=prompt_text,
        sampling_plan_json=_canonical_json(sampling_plan),
        sampling_plan_hash=plan_hash,
        status="PLANNED",
    )
    db.add(analysis)
    db.flush()
    return analysis, True


def queue_frozen_analysis(db: Session, analysis_id: str) -> SinglePromptAnalysis:
    analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=analysis_id).one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="冻结复测 Analysis 不存在")
    if analysis.status != "PLANNED":
        raise HTTPException(status_code=409, detail=f"当前状态 {analysis.status} 不能启动采样")
    plan = loads(analysis.sampling_plan_json, {})
    runs = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).order_by(BrowserMonitorRun.id).all()
    if len(runs) != int(plan.get("sample_count") or 0):
        raise HTTPException(status_code=409, detail="复测计划 Run 数与冻结计划不一致")
    if any(_hash(run.original_query) != plan.get("prompt_text_hash") for run in runs):
        raise HTTPException(status_code=409, detail="计划 Run 查询已偏离冻结 Prompt，拒绝启动")
    for run in runs:
        if run.status != "pending":
            raise HTTPException(status_code=409, detail="计划 Run 状态已变化，拒绝重复启动")
        run.status = "queued"
        run.stage = "queued"
    task = db.get(BrowserMonitorTask, analysis.task_id)
    if not task:
        raise HTTPException(status_code=409, detail="复测采样 Task 不存在")
    task.status = "queued"
    analysis.status = "QUEUED"
    db.commit()
    db.refresh(analysis)
    return analysis


def claim_analysis(db: Session, analysis_id: str) -> str | None:
    token = uuid4().hex
    claimed = db.execute(
        update(SinglePromptAnalysis)
        .where(
            SinglePromptAnalysis.analysis_id == analysis_id,
            SinglePromptAnalysis.status == "QUEUED",
        )
        .values(
            status="COLLECTING",
            blocker_code="",
            blocker_detail="",
            active_attempt_token=token,
            attempt_count=SinglePromptAnalysis.attempt_count + 1,
            started_at=datetime.utcnow(),
            finished_at=None,
        )
    )
    db.commit()
    return token if claimed.rowcount == 1 else None


def execute_analysis(
    analysis_id: str,
    executor_factory: Callable[[], MonitoringTaskExecutor] = MonitoringTaskExecutor,
    *,
    freeze_with_failures: bool = True,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    if session_factory is None:
        from app.core.database import SessionLocal

        session_factory = SessionLocal
    db = session_factory()
    executor: MonitoringTaskExecutor | None = None
    token = claim_analysis(db, analysis_id)
    if not token:
        db.close()
        return
    try:
        analysis = db.query(SinglePromptAnalysis).filter(SinglePromptAnalysis.analysis_id == analysis_id).one()
        task = db.get(BrowserMonitorTask, analysis.task_id)
        if not task:
            raise RuntimeError("V2 采集任务不存在")
        plan = loads(analysis.sampling_plan_json, {})
        if plan.get("prompt_text_hash"):
            planned_runs = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).all()
            if len(planned_runs) != int(plan.get("sample_count") or 0):
                raise RuntimeError("复测计划 Run 数与冻结计划不一致")
            if any(_hash(run.original_query) != plan["prompt_text_hash"] for run in planned_runs):
                raise RuntimeError("FROZEN_PROMPT_MISMATCH")
        task.status = "running"
        db.commit()
        executor = executor_factory()
        executor.execute_queued_runs(db, task.id)
        update_task_status_from_runs(db, task)
        if not freeze_with_failures:
            completed_runs = _snapshot_runs(db, analysis)
            if any(run.get("status") in {"failed", "blocked"} for run in completed_runs):
                fail_analysis(
                    db,
                    analysis_id,
                    token,
                    "PARTIAL_RETEST_RETRY_AVAILABLE",
                    "部分计划 Run 失败；成功 Run 已保留，可重试失败 Run 或显式保留失败并冻结结果。",
                    status="INTERRUPTED",
                )
                return
        finalize_analysis(db, analysis_id, token)
    except Exception as exc:
        db.rollback()
        fail_analysis(db, analysis_id, token, "COLLECTION_WORKER_INTERRUPTED", str(exc))
    finally:
        if executor:
            executor.close()
        db.close()


def _snapshot_runs(db: Session, analysis: SinglePromptAnalysis) -> list[dict[str, Any]]:
    runs = (
        db.query(BrowserMonitorRun)
        .filter(
            BrowserMonitorRun.task_id == analysis.task_id,
            BrowserMonitorRun.project_id == analysis.project_id,
            BrowserMonitorRun.prompt_id == analysis.prompt_id,
        )
        .order_by(BrowserMonitorRun.run_sequence.asc(), BrowserMonitorRun.id.asc())
        .all()
    )
    run_ids = [run.id for run in runs]
    references: dict[int, list[ReferenceSource]] = {run_id: [] for run_id in run_ids}
    retrievals: dict[int, list[RetrievalCandidate]] = {run_id: [] for run_id in run_ids}
    artifacts: dict[int, list[RunArtifact]] = {run_id: [] for run_id in run_ids}
    if run_ids:
        for row in db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).order_by(ReferenceSource.run_id, ReferenceSource.reference_index):
            references[row.run_id].append(row)
        for row in db.query(RetrievalCandidate).filter(RetrievalCandidate.run_id.in_(run_ids)).order_by(RetrievalCandidate.run_id, RetrievalCandidate.rank):
            retrievals[row.run_id].append(row)
        for row in db.query(RunArtifact).filter(RunArtifact.run_id.in_(run_ids)).order_by(RunArtifact.run_id, RunArtifact.id):
            artifacts[row.run_id].append(row)

    return [
        {
            "run_id": run.id,
            "run_sequence": run.run_sequence,
            "sample_index": run.sample_index,
            "status": run.status,
            "stage": run.stage,
            "answer_text": run.answer_text,
            "answer_char_count": run.answer_char_count,
            "reference_complete": run.reference_complete,
            "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at),
            "duration_ms": run.duration_ms,
            "environment": {
                "collector_id": run.collector_id,
                "browser": run.browser,
                "browser_version": run.browser_version,
                "os": run.os,
                "profile_identifier": run.profile_identifier,
                "conversation_id": run.conversation_id,
                "sampling_mode": run.sampling_mode,
                "network_region": run.network_region,
                "collector_version": run.collector_version,
                "parser_version": run.parser_version,
                "session_verification": {
                    "status": "VERIFIED" if run.sampling_mode == "single_independent" else "UNVERIFIED",
                    "basis": "PRE_SUBMIT_ZERO_TURN_DOM_GATE" if run.sampling_mode == "single_independent" else "NOT_AVAILABLE",
                    "conversation_id": run.conversation_id or None,
                },
            },
            "observed_conditions": {
                "platform": {"value": run.platform, "source": "RUN_CAPTURE"},
                "source_type": {"value": run.source_type, "source": "RUN_CAPTURE"},
                "adapter": {"value": run.adapter, "source": "RUN_CAPTURE"},
                "original_query": {"value": run.original_query, "source": "RUN_CAPTURE"},
                "collection_mode": {"value": run.collection_mode, "source": "SAMPLING_PLAN"},
                "actual_sampling_mode": {
                    "value": run.sampling_mode if run.sampling_mode not in {None, "", "UNKNOWN"} else None,
                    "source": "COLLECTOR_PRE_SUBMIT_ZERO_TURN_GATE" if run.sampling_mode == "single_independent" else "COLLECTOR_NOT_VERIFIED",
                },
                "page_query": {"value": run.page_query or None, "source": "RUN_CAPTURE" if run.page_query else "PLATFORM_NOT_EXPOSED"},
                "retrieval_query": {"value": run.retrieval_query or None, "source": "RUN_CAPTURE" if run.retrieval_query else "PLATFORM_NOT_EXPOSED"},
                "model_revision": {"value": None, "source": "PLATFORM_NOT_EXPOSED"},
            },
            "references": [
                {
                    "reference_id": row.id,
                    "index": row.reference_index,
                    "title": row.display_title or row.matched_title,
                    "url": row.url,
                    "canonical_url": row.canonical_url,
                    "domain": row.domain,
                    "resolution_method": row.resolution_method,
                }
                for row in references[run.id]
            ],
            "retrieval_candidates": [
                {
                    "candidate_id": row.id,
                    "rank": row.rank,
                    "title": row.title,
                    "url": row.url,
                    "canonical_url": row.canonical_url,
                    "domain": row.domain,
                    "snippet": row.snippet,
                }
                for row in retrievals[run.id]
            ],
            "artifacts": [
                {
                    "artifact_id": row.id,
                    "artifact_type": row.artifact_type,
                    "storage_path": row.storage_path,
                    "mime_type": row.mime_type,
                    "size_bytes": row.size_bytes,
                }
                for row in artifacts[run.id]
            ],
            "error": {
                "stage": run.error_stage,
                "type": run.error_type,
                "message": run.error_message,
                "blocked_type": run.blocked_type,
                "blocked_reason": run.blocked_reason,
            } if run.status in {"failed", "blocked"} else None,
        }
        for run in runs
    ]


def finalize_analysis(db: Session, analysis_id: str, token: str) -> bool:
    analysis = db.query(SinglePromptAnalysis).filter(SinglePromptAnalysis.analysis_id == analysis_id).one_or_none()
    if not analysis or analysis.status != "COLLECTING" or analysis.active_attempt_token != token:
        return False
    if db.query(SinglePromptAnalysisContext).filter(SinglePromptAnalysisContext.analysis_id == analysis_id).first():
        return False

    plan = loads(analysis.sampling_plan_json, {})
    runs = _snapshot_runs(db, analysis)
    planned = int(plan.get("sample_count") or 0)
    if len(runs) != planned or any(run["status"] not in TERMINAL_RUN_STATUSES for run in runs):
        fail_analysis(db, analysis_id, token, "INCOMPLETE_TASK_TERMINATION", "采集 worker 已结束，但计划 Run 尚未全部进入终态", status="INTERRUPTED")
        return False

    valid = [
        run
        for run in runs
        if run["status"] in VALID_RUN_STATUSES and str(run.get("answer_text") or "").strip()
    ]
    failed = [run for run in runs if run not in valid]
    if not valid:
        fail_analysis(db, analysis_id, token, "NO_VALID_RUNS", "本次采样没有产生有效回答，未创建 AnalysisContext")
        return False

    run_scope = {
        "contract_version": "single-prompt-run-scope-v1",
        "task_id": analysis.task_id,
        "run_ids": [run["run_id"] for run in runs],
        "planned_run_count": planned,
    }
    output = {
        "contract_version": plan.get("raw_output_contract_version") or "single-prompt-raw-output-v1",
        "analysis_id": analysis.analysis_id,
        "project_id": analysis.project_id,
        "prompt_id": analysis.prompt_id,
        "prompt_text": analysis.prompt_text_snapshot,
        "sampling_plan": plan,
        "runs": runs,
    }
    run_scope_hash = _hash(run_scope)
    output_hash = _hash(output)
    result_version = f"raw-v1:{output_hash[:16]}"
    context = SinglePromptAnalysisContext(
        context_id=f"ctx-{uuid4()}",
        analysis_id=analysis.analysis_id,
        project_id=analysis.project_id,
        prompt_id=analysis.prompt_id,
        task_id=analysis.task_id,
        result_version=result_version,
        run_scope_json=_canonical_json(run_scope),
        run_scope_hash=run_scope_hash,
        raw_output_json=_canonical_json(output),
        raw_output_hash=output_hash,
        valid_run_count=len(valid),
        failed_run_count=len(failed),
    )
    db.add(context)
    analysis.status = "READY" if not failed else "READY_WITH_FAILURES"
    analysis.blocker_code = "NEXT_STAGE_NOT_IMPLEMENTED"
    analysis.blocker_detail = "采样结果已冻结；诊断阶段不在本次交付范围内"
    analysis.active_attempt_token = ""
    analysis.finished_at = datetime.utcnow()
    db.commit()
    return True


def fail_analysis(
    db: Session,
    analysis_id: str,
    token: str,
    code: str,
    detail: str,
    *,
    status: str = "FAILED",
) -> bool:
    failed = db.execute(
        update(SinglePromptAnalysis)
        .where(
            SinglePromptAnalysis.analysis_id == analysis_id,
            SinglePromptAnalysis.status == "COLLECTING",
            SinglePromptAnalysis.active_attempt_token == token,
        )
        .values(
            status=status,
            blocker_code=code,
            blocker_detail=detail[:2000],
            active_attempt_token="",
            finished_at=datetime.utcnow(),
        )
    )
    db.commit()
    return failed.rowcount == 1


def retry_analysis(db: Session, analysis_id: str) -> SinglePromptAnalysis:
    analysis = db.query(SinglePromptAnalysis).filter(SinglePromptAnalysis.analysis_id == analysis_id).one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="V2 分析不存在")
    if db.query(SinglePromptAnalysisContext).filter(SinglePromptAnalysisContext.analysis_id == analysis_id).first():
        raise HTTPException(status_code=409, detail="AnalysisContext 已冻结，不能原地重采样；请创建一次新分析")
    if analysis.status not in {"FAILED", "INTERRUPTED"}:
        raise HTTPException(status_code=409, detail=f"当前状态 {analysis.status} 不允许重试")

    runs = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.task_id == analysis.task_id).all()
    history = loads(analysis.retry_history_json, [])
    history.append({
        "recorded_at": _iso(datetime.utcnow()),
        "analysis_status": analysis.status,
        "blocker_code": analysis.blocker_code,
        "runs": [
            {"run_id": run.id, "status": run.status, "error_type": run.error_type, "error_message": run.error_message}
            for run in runs
        ],
    })
    analysis.retry_history_json = dumps(history)
    requeued = 0
    for run in runs:
        if run.status in {"failed", "blocked", "running", "queued", "pending"}:
            run.status = "queued"
            run.stage = "queued"
            run.retry_count += 1
            run.error_stage = ""
            run.error_type = ""
            run.error_message = ""
            run.blocked_type = ""
            run.blocked_reason = ""
            run.finished_at = None
            requeued += 1
    if not requeued:
        raise HTTPException(status_code=409, detail="没有可重试的采样 Run")
    task = db.get(BrowserMonitorTask, analysis.task_id)
    if task:
        task.status = "queued"
    analysis.status = "QUEUED"
    analysis.blocker_code = ""
    analysis.blocker_detail = ""
    analysis.active_attempt_token = ""
    analysis.finished_at = None
    db.commit()
    db.refresh(analysis)
    return analysis


def finalize_analysis_with_recorded_failures(db: Session, analysis_id: str) -> SinglePromptAnalysisContext:
    analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=analysis_id).one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="V2 分析不存在")
    existing = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis_id).one_or_none()
    if existing:
        return existing
    if analysis.status != "INTERRUPTED" or analysis.blocker_code != "PARTIAL_RETEST_RETRY_AVAILABLE":
        raise HTTPException(status_code=409, detail="当前分析没有可显式保留的复测失败项")
    token = uuid4().hex
    analysis.status = "COLLECTING"
    analysis.active_attempt_token = token
    db.commit()
    if not finalize_analysis(db, analysis_id, token):
        raise HTTPException(status_code=409, detail="复测结果冻结失败，请重新读取状态")
    return db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis_id).one()


def recover_interrupted_analyses(db: Session) -> int:
    analyses = db.query(SinglePromptAnalysis).filter(SinglePromptAnalysis.status.in_(ACTIVE_ANALYSIS_STATUSES)).all()
    recovered = 0
    for analysis in analyses:
        runs = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.task_id == analysis.task_id).all()
        for run in runs:
            if run.status == "running":
                run.status = "failed"
                run.stage = "failed"
                run.error_stage = "service_restart"
                run.error_type = "service_restart_uncertain"
                run.error_message = "服务重启时外部采集结果不确定；等待用户明确重试"
                run.finished_at = datetime.utcnow()
        analysis.status = "INTERRUPTED"
        analysis.blocker_code = "SERVICE_RESTART_INTERRUPTED"
        analysis.blocker_detail = "服务重启中断了采集；系统未静默重试，请人工确认后重试"
        analysis.active_attempt_token = ""
        analysis.finished_at = datetime.utcnow()
        task = db.get(BrowserMonitorTask, analysis.task_id)
        if task:
            task.status = "interrupted"
        recovered += 1
    if recovered:
        db.commit()
    return recovered


def get_analysis_status(db: Session, analysis_id: str) -> dict[str, Any]:
    analysis = db.query(SinglePromptAnalysis).filter(SinglePromptAnalysis.analysis_id == analysis_id).one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="V2 分析不存在")
    task = db.get(BrowserMonitorTask, analysis.task_id)
    context = db.query(SinglePromptAnalysisContext).filter(SinglePromptAnalysisContext.analysis_id == analysis_id).one_or_none()
    if context:
        output = loads(context.raw_output_json, {})
        runs = output.get("runs", [])
        result_source = "FROZEN_ANALYSIS_CONTEXT"
    else:
        runs = _snapshot_runs(db, analysis)
        result_source = "LIVE_TASK_PROGRESS"

    valid = [run for run in runs if run.get("status") in VALID_RUN_STATUSES and str(run.get("answer_text") or "").strip()]
    terminal = [run for run in runs if run.get("status") in TERMINAL_RUN_STATUSES]
    failures = [
        {
            "run_id": run.get("run_id"),
            "status": run.get("status"),
            "error": run.get("error") or {
                "stage": run.get("stage") or "",
                "type": "invalid_empty_answer",
                "message": "Run 进入终态但没有可用回答",
                "blocked_type": "",
                "blocked_reason": "",
            },
        }
        for run in runs
        if run not in valid and run.get("status") in TERMINAL_RUN_STATUSES
    ]
    warnings: list[dict[str, str]] = []
    if runs and all((run.get("environment") or {}).get("sampling_mode") in {None, "", "UNKNOWN"} for run in runs):
        warnings.append({
            "code": "INDEPENDENT_SESSION_PROOF_UNAVAILABLE",
            "detail": "采集器未返回独立会话证明；配置为 single_independent 不等于浏览器执行已被证明。",
        })
    reference_count = sum(len(run.get("references") or []) for run in runs)
    retrieval_count = sum(len(run.get("retrieval_candidates") or []) for run in runs)
    if reference_count and retrieval_count == 0:
        warnings.append({
            "code": "RETRIEVAL_OBSERVATION_UNAVAILABLE",
            "detail": "本次采集保存了引用，但未获得检索候选输出；该状态不能解释为观测到的检索数量为 0。",
        })
    plan = loads(analysis.sampling_plan_json, {})
    if analysis.status in ACTIVE_ANALYSIS_STATUSES:
        operations = ["VIEW_STATUS"]
    elif context:
        operations = ["VIEW_RESULTS"]
    else:
        operations = ["VIEW_STATUS", "RETRY_COLLECTION"]
    blocker = None
    if analysis.blocker_code:
        blocker = {"code": analysis.blocker_code, "detail": analysis.blocker_detail}

    return {
        "analysis": {
            "analysis_id": analysis.analysis_id,
            "project_id": analysis.project_id,
            "prompt_id": analysis.prompt_id,
            "task_id": analysis.task_id,
            "prompt_text": analysis.prompt_text_snapshot,
            "sampling_plan_hash": analysis.sampling_plan_hash,
        },
        "sampling": {
            "status": analysis.status,
            "planned_run_count": int(plan.get("sample_count") or 0),
            "terminal_run_count": len(terminal),
            "valid_run_count": len(valid),
            "failed_run_count": len(failures),
            "attempt_count": analysis.attempt_count,
        },
        "result_version": context.result_version if context else None,
        "context_id": context.context_id if context else None,
        "result_source": result_source,
        "blocker": blocker,
        "allowed_operations": operations,
        "active_task": {
            "task_id": task.id,
            "status": task.status,
            "active_attempt_token": analysis.active_attempt_token or None,
        } if task else None,
        "runs": runs,
        "failures": failures,
        "warnings": warnings,
        "created_at": _iso(analysis.created_at),
        "started_at": _iso(analysis.started_at),
        "finished_at": _iso(analysis.finished_at),
    }
