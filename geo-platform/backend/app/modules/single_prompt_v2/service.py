from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
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
    ProjectConfigurationVersion,
    Prompt,
    PromptVersion,
    ReferenceSource,
    RetrievalCandidate,
    RunArtifact,
    SinglePromptAnalysis,
    SinglePromptAnalysisContext,
    SinglePromptExecutionProposal,
    SinglePromptExecutionProposalResult,
    SinglePromptStrategyExecution,
    SinglePromptSourceDisposition,
    SinglePromptSourcePreparation,
)
from app.modules.monitoring.enums import (
    BROWSER_AUDIT_ENTRY_TYPE,
    NON_RETRYABLE_ERRORS,
    WENXIN_PLATFORM,
    WENXIN_WEB_ADAPTER,
)
from app.modules.monitoring.executor import MonitoringTaskExecutor
from app.modules.monitoring.collectors.wenxin.search_process import (
    legacy_mixed_answer_boundary,
    normalize_answer_content_boundary,
    normalize_platform_search_observation,
    project_platform_search_observation,
)
from app.modules.monitoring.services import (
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


def project_platform_reported_search(answer_text: str | None) -> dict[str, Any]:
    """Legacy projection for immutable Runs captured before semantic-region separation."""

    return project_platform_search_observation(
        answer_text,
        source="LEGACY_MIXED_ANSWER_TEXT_PROJECTION",
    )


def _with_platform_reported_search(run: dict[str, Any]) -> dict[str, Any]:
    projected = dict(run)
    if not normalize_platform_search_observation(projected.get("platform_reported_search")):
        projected["platform_reported_search"] = project_platform_reported_search(run.get("answer_text"))
    if not normalize_answer_content_boundary(projected.get("answer_content_boundary")):
        projected["answer_content_boundary"] = legacy_mixed_answer_boundary(run.get("answer_text"))
    return projected


def _semantic_region_projection(rows: list[RunArtifact]) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    for row in reversed(rows):
        if row.artifact_type != "wenxin_semantic_regions":
            continue
        try:
            payload = json.loads(Path(row.storage_path).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        search = normalize_platform_search_observation(payload.get("platform_reported_search"))
        boundary = normalize_answer_content_boundary(payload.get("answer_content_boundary"))
        if search and boundary:
            return search, boundary
    return None, None


def _require_sampling_enabled(db: Session, project_id: int, prompt_id: int) -> None:
    prompt = db.get(Prompt, prompt_id)
    if not prompt or prompt.project_id != project_id:
        raise HTTPException(status_code=404, detail="Prompt 不存在或不属于当前项目")
    if not prompt.enabled:
        raise HTTPException(status_code=409, detail="问题已停用，不能发起新采样；历史样本和已有分析仍可使用")


def _configuration_brand(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "brand_name": snapshot.get("brand_name") or "",
        "brand_aliases": snapshot.get("brand_aliases") or [],
        "website_url": snapshot.get("website_url") or "",
        "industry": snapshot.get("industry") or "",
        "region": snapshot.get("region") or "",
        "language": snapshot.get("language") or "",
    }


def _current_analysis_configuration(db: Session, project_id: int) -> dict[str, Any]:
    row = db.query(ProjectConfigurationVersion).filter_by(project_id=project_id).order_by(
        ProjectConfigurationVersion.version_number.desc(), ProjectConfigurationVersion.id.desc(),
    ).first()
    if not row:
        raise HTTPException(status_code=409, detail="当前项目没有可绑定的配置版本")
    snapshot = loads(row.snapshot_json, {})
    if (not isinstance(snapshot, dict) or snapshot.get("project_id") != project_id
            or _hash(snapshot) != row.snapshot_hash):
        raise HTTPException(status_code=409, detail="当前项目配置版本 snapshot 归属或 hash 不匹配")
    return {
        "binding_status": "BOUND",
        "configuration_version_id": row.configuration_version_id,
        "version_number": row.version_number,
        "snapshot_hash": row.snapshot_hash,
        "brand": _configuration_brand(snapshot),
    }


def _validate_configuration_binding(db: Session, project_id: int,
                                    binding: Any) -> dict[str, Any]:
    if not isinstance(binding, dict) or binding.get("binding_status") not in {"BOUND", "LEGACY_UNBOUND"}:
        raise HTTPException(status_code=409, detail="Analysis 项目配置绑定无效")
    if binding.get("binding_status") == "LEGACY_UNBOUND":
        if set(binding) != {"binding_status"}:
            raise HTTPException(status_code=409, detail="Legacy Analysis 不能携带伪造的配置版本")
        return binding
    required = {"binding_status", "configuration_version_id", "version_number", "snapshot_hash", "brand"}
    if set(binding) != required:
        raise HTTPException(status_code=409, detail="Analysis 项目配置绑定不完整")
    version_number = binding["version_number"]
    snapshot_hash = binding["snapshot_hash"]
    if (not isinstance(binding["configuration_version_id"], str)
            or not binding["configuration_version_id"]
            or not isinstance(version_number, int) or isinstance(version_number, bool) or version_number <= 0
            or not isinstance(snapshot_hash, str) or len(snapshot_hash) != 64
            or any(char not in "0123456789abcdef" for char in snapshot_hash)):
        raise HTTPException(status_code=409, detail="Analysis 项目配置绑定字段无效")
    row = db.query(ProjectConfigurationVersion).filter_by(
        project_id=project_id,
        configuration_version_id=binding["configuration_version_id"],
        version_number=binding["version_number"],
        snapshot_hash=binding["snapshot_hash"],
    ).one_or_none()
    snapshot = loads(row.snapshot_json, {}) if row else {}
    if (not row or not isinstance(snapshot, dict) or snapshot.get("project_id") != project_id
            or _hash(snapshot) != row.snapshot_hash
            or binding["brand"] != _configuration_brand(snapshot)):
        raise HTTPException(status_code=409, detail="Analysis 项目、配置版本、hash 或品牌快照不匹配")
    return binding


def _validate_analysis_configuration(db: Session, analysis: SinglePromptAnalysis,
                                     plan: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = plan if plan is not None else loads(analysis.sampling_plan_json, {})
    if not isinstance(plan, dict) or _hash(plan) != analysis.sampling_plan_hash:
        raise HTTPException(status_code=409, detail="Analysis 冻结采样计划 hash 不匹配")
    binding = plan.get("project_configuration")
    if binding is None:
        return {"binding_status": "LEGACY_UNBOUND"}
    return _validate_configuration_binding(db, analysis.project_id, binding)


def _load_prompt_version_binding(
    db: Session,
    *,
    project_id: int,
    prompt_id: int,
    prompt_version_id: str,
    snapshot_hash: str,
) -> dict[str, Any]:
    row = db.query(PromptVersion).filter_by(
        project_id=project_id,
        prompt_id=prompt_id,
        prompt_version_id=prompt_version_id,
        snapshot_hash=snapshot_hash,
    ).one_or_none()
    snapshot = loads(row.snapshot_json, {}) if row else {}
    if (
        not row
        or not isinstance(snapshot, dict)
        or snapshot.get("project_id") != project_id
        or snapshot.get("prompt_id") != prompt_id
        or not isinstance(snapshot.get("prompt_text"), str)
        or not snapshot["prompt_text"].strip()
        or _hash(snapshot) != row.snapshot_hash
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "PROMPT_VERSION_BINDING_MISMATCH", "message": "Prompt 版本的项目、Prompt、ID 或 hash 不匹配"},
        )
    return {
        "binding_status": "BOUND",
        "prompt_version_id": row.prompt_version_id,
        "version_number": row.version_number,
        "snapshot_hash": row.snapshot_hash,
        "snapshot": snapshot,
    }


def _validate_analysis_prompt_version(
    db: Session,
    analysis: SinglePromptAnalysis,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = plan if plan is not None else loads(analysis.sampling_plan_json, {})
    if not isinstance(plan, dict) or _hash(plan) != analysis.sampling_plan_hash:
        raise HTTPException(status_code=409, detail="Analysis 冻结采样计划 hash 不匹配")
    binding = plan.get("prompt_version")
    if binding is None:
        return {"binding_status": "LEGACY_UNBOUND"}
    if not isinstance(binding, dict) or binding.get("binding_status") != "BOUND":
        raise HTTPException(status_code=409, detail="Analysis Prompt 版本绑定无效")
    required = {"binding_status", "prompt_version_id", "version_number", "snapshot_hash", "snapshot"}
    if set(binding) != required:
        raise HTTPException(status_code=409, detail="Analysis Prompt 版本绑定不完整")
    validated = _load_prompt_version_binding(
        db,
        project_id=analysis.project_id,
        prompt_id=analysis.prompt_id,
        prompt_version_id=binding["prompt_version_id"],
        snapshot_hash=binding["snapshot_hash"],
    )
    if binding != validated or analysis.prompt_text_snapshot != validated["snapshot"]["prompt_text"]:
        raise HTTPException(status_code=409, detail="Analysis Prompt 版本冻结快照不匹配")
    return binding


def prompt_version_binding_for_runs(
    db: Session,
    *,
    run_ids: list[int],
) -> dict[str, Any]:
    rows = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.id.in_(run_ids)).all()
    task_ids = {row.task_id for row in rows}
    source_analyses = db.query(SinglePromptAnalysis).filter(SinglePromptAnalysis.task_id.in_(task_ids)).all()
    source_by_task = {row.task_id: row for row in source_analyses}
    bindings: list[dict[str, Any]] = []
    for row in rows:
        source = source_by_task.get(row.task_id)
        if not source:
            return {"binding_status": "LEGACY_UNBOUND"}
        source_binding = _validate_analysis_prompt_version(db, source)
        if source_binding.get("binding_status") != "BOUND":
            return {"binding_status": "LEGACY_UNBOUND"}
        bindings.append(source_binding)
    if not bindings:
        return {"binding_status": "LEGACY_UNBOUND"}
    first = bindings[0]
    if any(binding != first for binding in bindings[1:]):
        return {"binding_status": "UNSAFE", "reason": "MIXED_PROMPT_VERSIONS"}
    return first


def _require_runs_bound_to_prompt_version(
    db: Session,
    *,
    run_ids: list[int],
    prompt_version: dict[str, Any],
) -> None:
    proven = prompt_version_binding_for_runs(db, run_ids=run_ids)
    if proven != prompt_version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RUN_PROMPT_VERSION_UNPROVEN",
                "message": "所选 Run 无法证明属于指定 Prompt 冻结版本",
                "run_ids": sorted(run_ids),
            },
        )


def create_analysis(
    db: Session,
    *,
    project_id: int,
    prompt_id: int,
    prompt_version_id: str,
    snapshot_hash: str,
    sample_count: int,
    idempotency_key: str,
) -> tuple[SinglePromptAnalysis, bool]:
    project = db.get(Project, project_id)
    prompt = db.get(Prompt, prompt_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not prompt or prompt.project_id != project_id:
        raise HTTPException(status_code=404, detail="Prompt 不存在或不属于当前项目")

    prompt_version = _load_prompt_version_binding(
        db,
        project_id=project_id,
        prompt_id=prompt_id,
        prompt_version_id=prompt_version_id,
        snapshot_hash=snapshot_hash,
    )
    prompt_snapshot = prompt_version["snapshot"]

    plan = {
        "contract_version": "single-prompt-sampling-plan-v1",
        "project_id": project_id,
        "prompt_id": prompt_id,
        "prompt_text": prompt_snapshot["prompt_text"],
        "prompt_configuration": {
            "intent_type": prompt_snapshot.get("intent_type", ""),
            "prompt_group": prompt_snapshot.get("prompt_group", ""),
        },
        "prompt_version": prompt_version,
        "sample_count": sample_count,
        "platform": WENXIN_PLATFORM,
        "source_type": BROWSER_AUDIT_ENTRY_TYPE,
        "adapter": WENXIN_WEB_ADAPTER,
        "collection_mode": "single_independent",
        "project_configuration": _current_analysis_configuration(db, project_id),
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

    _require_sampling_enabled(db, project_id, prompt_id)
    analysis_id = str(uuid4())
    task = create_browser_task_from_frozen_prompt(
        db,
        project_id=project_id,
        prompt_id=prompt_id,
        prompt_text=prompt_snapshot["prompt_text"],
        run_count=sample_count,
        execute_now=True,
        platform=WENXIN_PLATFORM,
        source_type=BROWSER_AUDIT_ENTRY_TYPE,
        adapter=WENXIN_WEB_ADAPTER,
        collection_mode="single_independent",
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
        prompt_text_snapshot=prompt_snapshot["prompt_text"],
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


def queue_run_retry(
    db: Session,
    *,
    run_id: int,
    project_id: int,
    prompt_id: int,
    idempotency_key: str,
) -> tuple[BrowserMonitorRun, bool]:
    """Queue a new immutable Run attempt without overwriting the failed Run."""

    source = db.get(BrowserMonitorRun, run_id)
    if not source:
        raise HTTPException(status_code=404, detail="Run 不存在")
    if source.project_id != project_id or source.prompt_id != prompt_id:
        raise HTTPException(status_code=409, detail="Run 与当前 Project/Prompt 不匹配")

    existing_run = (
        db.query(BrowserMonitorRun)
        .filter_by(
            logical_run_id=source.logical_run_id,
            retry_idempotency_key=idempotency_key,
        )
        .one_or_none()
    )
    if existing_run:
        if existing_run.retry_of_run_id == source.id:
            return existing_run, False
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RETRY_IDEMPOTENCY_PARENT_MISMATCH",
                "message": "该幂等键已用于同一逻辑 Run 的另一父 attempt",
                "retry_run_id": existing_run.id,
                "retry_of_run_id": existing_run.retry_of_run_id,
            },
        )

    if source.status != "failed":
        raise HTTPException(status_code=409, detail=f"当前状态 {source.status} 不支持重试，仅 failed 可重试")
    if source.error_type in NON_RETRYABLE_ERRORS:
        raise HTTPException(status_code=422, detail="该错误类型不支持自动重试")

    latest_attempt = (
        db.query(BrowserMonitorRun)
        .filter_by(logical_run_id=source.logical_run_id)
        .order_by(BrowserMonitorRun.attempt_no.desc(), BrowserMonitorRun.id.desc())
        .first()
    )
    if not latest_attempt or latest_attempt.id != source.id:
        raise HTTPException(status_code=409, detail="仅允许从当前最新失败 attempt 重试")

    _require_sampling_enabled(db, project_id, prompt_id)
    created_by = f"single_prompt_v2:run_retry:{source.logical_run_id}:{idempotency_key}"
    task = create_browser_task_from_frozen_prompt(
        db,
        project_id=project_id,
        prompt_id=prompt_id,
        prompt_text=source.original_query,
        run_count=1,
        execute_now=True,
        platform=source.platform,
        source_type=source.source_type,
        adapter=source.adapter,
        collection_mode=source.collection_mode,
        schedule_type="single_prompt_v2_run_retry",
        created_by=created_by,
        commit=False,
    )
    retry_run = db.query(BrowserMonitorRun).filter_by(task_id=task.id).one()
    retry_run.retry_count = source.retry_count + 1
    retry_run.logical_run_id = source.logical_run_id
    retry_run.attempt_no = source.attempt_no + 1
    retry_run.retry_of_run_id = source.id
    retry_run.retry_idempotency_key = idempotency_key
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_run = (
            db.query(BrowserMonitorRun)
            .filter_by(
                logical_run_id=source.logical_run_id,
                retry_idempotency_key=idempotency_key,
            )
            .one_or_none()
        )
        if existing_run:
            if existing_run.retry_of_run_id == source.id:
                return existing_run, False
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "RETRY_IDEMPOTENCY_PARENT_MISMATCH",
                    "message": "该幂等键已用于同一逻辑 Run 的另一父 attempt",
                    "retry_run_id": existing_run.id,
                    "retry_of_run_id": existing_run.retry_of_run_id,
                },
            )
        raise HTTPException(status_code=409, detail="该逻辑 Run 已产生更新的 attempt，请刷新后重试")
    db.refresh(retry_run)
    return retry_run, True


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

    sampling_plan = dict(sampling_plan)
    prompt_version = sampling_plan.get("prompt_version")
    if not isinstance(prompt_version, dict) or prompt_version.get("binding_status") != "BOUND":
        raise HTTPException(status_code=409, detail="新 Analysis 必须绑定 Prompt 版本")
    validated_prompt_version = _load_prompt_version_binding(
        db,
        project_id=project_id,
        prompt_id=prompt_id,
        prompt_version_id=prompt_version.get("prompt_version_id"),
        snapshot_hash=prompt_version.get("snapshot_hash"),
    )
    if prompt_version != validated_prompt_version:
        raise HTTPException(status_code=409, detail="冻结计划 Prompt 版本绑定不匹配")
    if prompt_text != validated_prompt_version["snapshot"]["prompt_text"]:
        raise HTTPException(status_code=409, detail="冻结计划 Prompt 文本与绑定版本不匹配")
    if "project_configuration" not in sampling_plan:
        sampling_plan["project_configuration"] = _current_analysis_configuration(db, project_id)
    else:
        if (not isinstance(sampling_plan["project_configuration"], dict)
                or sampling_plan["project_configuration"].get("binding_status") != "BOUND"):
            raise HTTPException(status_code=409, detail="新 Analysis 必须绑定项目配置版本")
        _validate_configuration_binding(db, project_id, sampling_plan["project_configuration"])
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

    _require_sampling_enabled(db, project_id, prompt_id)
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
    _require_sampling_enabled(db, analysis.project_id, analysis.prompt_id)
    plan = loads(analysis.sampling_plan_json, {})
    _validate_analysis_configuration(db, analysis, plan)
    _validate_analysis_prompt_version(db, analysis, plan)
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
    task = db.get(BrowserMonitorTask, analysis.task_id) if analysis.task_id is not None else None
    if not task:
        raise HTTPException(status_code=409, detail="复测采样 Task 不存在")
    task.status = "queued"
    analysis.status = "QUEUED"
    db.commit()
    db.refresh(analysis)
    return analysis


def claim_analysis(db: Session, analysis_id: str) -> str | None:
    analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=analysis_id).one_or_none()
    if not analysis:
        return None
    _validate_analysis_configuration(db, analysis)
    _validate_analysis_prompt_version(db, analysis)
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


def _snapshot_run_rows(db: Session, runs: list[BrowserMonitorRun]) -> list[dict[str, Any]]:
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
    semantic_regions = {
        run_id: _semantic_region_projection(artifacts[run_id])
        for run_id in run_ids
    }

    return [
        {
            "run_id": run.id,
            "logical_run_id": run.logical_run_id,
            "attempt_id": run.attempt_id,
            "attempt_no": run.attempt_no,
            "retry_of_run_id": run.retry_of_run_id,
            "run_sequence": run.run_sequence,
            "sample_index": run.sample_index,
            "status": run.status,
            "stage": run.stage,
            "answer_text": run.answer_text,
            "answer_char_count": run.answer_char_count,
            "platform_reported_search": semantic_regions[run.id][0],
            "answer_content_boundary": semantic_regions[run.id][1],
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


def _snapshot_runs(db: Session, analysis: SinglePromptAnalysis) -> list[dict[str, Any]]:
    if analysis.task_id is None:
        return []
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
    return _snapshot_run_rows(db, runs)


def _run_input_fingerprint(run: dict[str, Any]) -> str:
    return _hash(_with_platform_reported_search(run))


def _selected_run_snapshots(
    db: Session,
    *,
    project_id: int,
    prompt_id: int,
    run_ids: list[int],
) -> list[dict[str, Any]]:
    if len(run_ids) != len(set(run_ids)):
        raise HTTPException(status_code=422, detail="run_ids 不能包含重复项")
    ordered_ids = sorted(run_ids)
    rows = (
        db.query(BrowserMonitorRun)
        .filter(BrowserMonitorRun.id.in_(ordered_ids))
        .all()
    )
    by_id = {row.id: row for row in rows}
    missing = [run_id for run_id in ordered_ids if run_id not in by_id]
    if missing:
        raise HTTPException(status_code=422, detail={"code": "RUN_NOT_FOUND", "run_ids": missing})
    wrong_scope = [
        row.id for row in rows
        if row.project_id != project_id or row.prompt_id != prompt_id
    ]
    if wrong_scope:
        raise HTTPException(status_code=409, detail={"code": "RUN_SCOPE_MISMATCH", "run_ids": sorted(wrong_scope)})
    attempts_by_logical_run: dict[str, list[int]] = {}
    for row in rows:
        attempts_by_logical_run.setdefault(row.logical_run_id, []).append(row.id)
    duplicate_logical_runs = {
        logical_run_id: sorted(selected_ids)
        for logical_run_id, selected_ids in attempts_by_logical_run.items()
        if len(selected_ids) > 1
    }
    if duplicate_logical_runs:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DUPLICATE_LOGICAL_RUN",
                "message": "同一逻辑 Run 只能选择一个物理 attempt",
                "logical_runs": duplicate_logical_runs,
                "run_ids": sorted(
                    run_id
                    for selected_ids in duplicate_logical_runs.values()
                    for run_id in selected_ids
                ),
            },
        )
    invalid = [
        row.id for row in rows
        if row.status not in VALID_RUN_STATUSES or not str(row.answer_text or "").strip()
    ]
    if invalid:
        raise HTTPException(status_code=409, detail={"code": "RUN_NOT_ANALYZABLE", "run_ids": sorted(invalid)})
    return _snapshot_run_rows(db, [by_id[run_id] for run_id in ordered_ids])


def create_analysis_from_runs(
    db: Session,
    *,
    project_id: int,
    prompt_id: int,
    prompt_version_id: str,
    snapshot_hash: str,
    run_ids: list[int],
    run_fingerprints: dict[int, str],
    base_context_id: str | None,
    idempotency_key: str,
    origin_monitor_scope: dict[str, Any] | None = None,
) -> tuple[SinglePromptAnalysis, bool]:
    project = db.get(Project, project_id)
    prompt = db.get(Prompt, prompt_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not prompt or prompt.project_id != project_id:
        raise HTTPException(status_code=404, detail="Prompt 不存在或不属于当前项目")
    prompt_version = _load_prompt_version_binding(
        db,
        project_id=project_id,
        prompt_id=prompt_id,
        prompt_version_id=prompt_version_id,
        snapshot_hash=snapshot_hash,
    )
    prompt_snapshot = prompt_version["snapshot"]
    if base_context_id:
        base = db.query(SinglePromptAnalysisContext).filter_by(context_id=base_context_id).one_or_none()
        if not base or base.project_id != project_id or base.prompt_id != prompt_id:
            raise HTTPException(status_code=409, detail="基准 Context 与当前 Project/Prompt 不匹配")

    snapshots = _selected_run_snapshots(
        db,
        project_id=project_id,
        prompt_id=prompt_id,
        run_ids=run_ids,
    )
    _require_runs_bound_to_prompt_version(
        db,
        run_ids=[int(row["run_id"]) for row in snapshots],
        prompt_version=prompt_version,
    )
    actual_fingerprints = {
        int(row["run_id"]): _run_input_fingerprint(row)
        for row in snapshots
    }
    supplied = {int(key): str(value) for key, value in run_fingerprints.items()}
    if supplied != actual_fingerprints:
        changed = sorted(
            set(actual_fingerprints) ^ set(supplied)
            | {run_id for run_id in actual_fingerprints if supplied.get(run_id) != actual_fingerprints[run_id]}
        )
        raise HTTPException(status_code=409, detail={"code": "RUN_INPUT_CHANGED", "run_ids": changed})

    ordered_ids = [int(row["run_id"]) for row in snapshots]
    plan = {
        "contract_version": "single-prompt-explicit-run-selection-v1",
        "project_id": project_id,
        "prompt_id": prompt_id,
        "prompt_text": prompt_snapshot["prompt_text"],
        "prompt_configuration": {
            "intent_type": prompt_snapshot.get("intent_type", ""),
            "prompt_group": prompt_snapshot.get("prompt_group", ""),
        },
        "prompt_version": prompt_version,
        "sample_count": len(ordered_ids),
        "input_mode": "EXPLICIT_RUN_SELECTION",
        "run_ids": ordered_ids,
        "run_fingerprints": actual_fingerprints,
        "base_context_id": base_context_id,
        "project_configuration": _current_analysis_configuration(db, project_id),
    }
    if origin_monitor_scope is not None:
        plan['origin_monitor_scope'] = origin_monitor_scope
    plan_hash = _hash(plan)
    existing = (
        db.query(SinglePromptAnalysis)
        .filter_by(project_id=project_id, idempotency_key=idempotency_key)
        .one_or_none()
    )
    if existing:
        if existing.sampling_plan_hash != plan_hash:
            raise HTTPException(status_code=409, detail="幂等键已用于不同的 Run 选择")
        return existing, False

    analysis_id = str(uuid4())
    run_scope = {
        "contract_version": "single-prompt-run-scope-v2",
        "source": "EXPLICIT_RUN_SELECTION",
        "run_ids": ordered_ids,
        "run_fingerprints": actual_fingerprints,
        "base_context_id": base_context_id,
        "planned_run_count": len(ordered_ids),
    }
    output = {
        "contract_version": "single-prompt-raw-output-v1",
        "analysis_id": analysis_id,
        "project_id": project_id,
        "prompt_id": prompt_id,
        "prompt_text": prompt_snapshot["prompt_text"],
        "sampling_plan": plan,
        "runs": snapshots,
    }
    run_scope_hash = _hash(run_scope)
    output_hash = _hash(output)
    now = datetime.utcnow()
    analysis = SinglePromptAnalysis(
        analysis_id=analysis_id,
        project_id=project_id,
        prompt_id=prompt_id,
        task_id=None,
        idempotency_key=idempotency_key,
        prompt_text_snapshot=prompt_snapshot["prompt_text"],
        sampling_plan_json=_canonical_json(plan),
        sampling_plan_hash=plan_hash,
        status="READY",
        blocker_code="",
        blocker_detail="",
        finished_at=now,
    )
    context = SinglePromptAnalysisContext(
        context_id=f"ctx-{uuid4()}",
        analysis_id=analysis_id,
        project_id=project_id,
        prompt_id=prompt_id,
        task_id=None,
        result_version=f"raw-v1:{output_hash[:16]}",
        run_scope_json=_canonical_json(run_scope),
        run_scope_hash=run_scope_hash,
        raw_output_json=_canonical_json(output),
        raw_output_hash=output_hash,
        valid_run_count=len(snapshots),
        failed_run_count=0,
    )
    db.add_all([analysis, context])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = (
            db.query(SinglePromptAnalysis)
            .filter_by(project_id=project_id, idempotency_key=idempotency_key)
            .one_or_none()
        )
        if concurrent and concurrent.sampling_plan_hash == plan_hash:
            return concurrent, False
        raise
    db.refresh(analysis)
    return analysis, True


def list_prompt_run_pool(
    db: Session,
    *,
    project_id: int,
    prompt_id: int,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    prompt = db.get(Prompt, prompt_id)
    if not prompt or prompt.project_id != project_id:
        raise HTTPException(status_code=404, detail="Prompt 不存在或不属于当前项目")
    query = db.query(BrowserMonitorRun).filter_by(project_id=project_id, prompt_id=prompt_id)
    total = query.count()
    rows = (
        query.order_by(BrowserMonitorRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    snapshots = _snapshot_run_rows(db, rows)
    context_membership: dict[int, list[dict[str, str]]] = {}
    for context in db.query(SinglePromptAnalysisContext).filter_by(project_id=project_id, prompt_id=prompt_id).all():
        scope = loads(context.run_scope_json, {})
        for run_id in scope.get("run_ids") or []:
            context_membership.setdefault(int(run_id), []).append({
                "analysis_id": context.analysis_id,
                "context_id": context.context_id,
            })
    items = []
    for row in snapshots:
        projected = _with_platform_reported_search(row)
        projected["input_fingerprint"] = _run_input_fingerprint(row)
        projected["analysis_memberships"] = context_membership.get(int(row["run_id"]), [])
        items.append(projected)
    return {
        "project_id": project_id,
        "prompt_id": prompt_id,
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": items,
    }


def finalize_analysis(db: Session, analysis_id: str, token: str) -> bool:
    analysis = db.query(SinglePromptAnalysis).filter(SinglePromptAnalysis.analysis_id == analysis_id).one_or_none()
    if not analysis or analysis.status != "COLLECTING" or analysis.active_attempt_token != token:
        return False
    if db.query(SinglePromptAnalysisContext).filter(SinglePromptAnalysisContext.analysis_id == analysis_id).first():
        return False

    plan = loads(analysis.sampling_plan_json, {})
    _validate_analysis_configuration(db, analysis, plan)
    _validate_analysis_prompt_version(db, analysis, plan)
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
    analysis.blocker_code = ""
    analysis.blocker_detail = ""
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
    _validate_analysis_configuration(db, analysis)
    _validate_analysis_prompt_version(db, analysis)
    _require_sampling_enabled(db, analysis.project_id, analysis.prompt_id)

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
    analyses = db.query(SinglePromptAnalysis).filter(SinglePromptAnalysis.status == "COLLECTING").all()
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
    configuration = _validate_analysis_configuration(db, analysis)
    prompt_version = _validate_analysis_prompt_version(db, analysis)
    task = db.get(BrowserMonitorTask, analysis.task_id) if analysis.task_id is not None else None
    context = db.query(SinglePromptAnalysisContext).filter(SinglePromptAnalysisContext.analysis_id == analysis_id).one_or_none()
    if context:
        output = loads(context.raw_output_json, {})
        runs = output.get("runs", [])
        result_source = "FROZEN_ANALYSIS_CONTEXT"
    else:
        runs = _snapshot_runs(db, analysis)
        result_source = "LIVE_TASK_PROGRESS"
    runs = [_with_platform_reported_search(run) for run in runs]

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
            "prompt_version": prompt_version,
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
        "raw_output_hash": context.raw_output_hash if context else None,
        "context_id": context.context_id if context else None,
        "result_source": result_source,
        "origin_monitor_scope": plan.get('origin_monitor_scope'),
        "project_configuration": configuration,
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


def list_analysis_statuses(
    db: Session,
    *,
    project_id: int,
    prompt_id: int,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List explicit analysis identities for user selection; never choose one implicitly."""
    analyses = (
        db.query(SinglePromptAnalysis)
        .filter(
            SinglePromptAnalysis.project_id == project_id,
            SinglePromptAnalysis.prompt_id == prompt_id,
        )
        .order_by(SinglePromptAnalysis.id.desc())
        .limit(limit)
        .all()
    )
    statuses = []
    for analysis in analyses:
        status = get_analysis_status(db, analysis.analysis_id)
        statuses.append({
            "analysis": status["analysis"],
            "sampling": status["sampling"],
            "result_version": status["result_version"],
            "context_id": status["context_id"],
            "created_at": status["created_at"],
            "finished_at": status["finished_at"],
        })
    if not analyses:
        return statuses

    analysis_ids = [analysis.analysis_id for analysis in analyses]
    # Navigation lists explicit saved identities, never selecting a latest execution.
    deliveries = (
        db.query(SinglePromptExecutionProposal, SinglePromptExecutionProposalResult, SinglePromptStrategyExecution)
        .join(SinglePromptExecutionProposalResult,
              (SinglePromptExecutionProposalResult.proposal_id == SinglePromptExecutionProposal.proposal_id)
              & (SinglePromptExecutionProposalResult.result_version == SinglePromptExecutionProposal.active_result_version))
        .join(SinglePromptStrategyExecution,
              SinglePromptStrategyExecution.strategy_id == SinglePromptExecutionProposal.strategy_id)
        .filter(
            SinglePromptExecutionProposal.analysis_id.in_(analysis_ids),
            SinglePromptExecutionProposal.project_id == project_id,
            SinglePromptExecutionProposal.prompt_id == prompt_id,
            SinglePromptStrategyExecution.analysis_id == SinglePromptExecutionProposal.analysis_id,
            SinglePromptStrategyExecution.context_id == SinglePromptExecutionProposal.context_id,
            SinglePromptStrategyExecution.diagnosis_id == SinglePromptExecutionProposal.diagnosis_id,
            SinglePromptStrategyExecution.project_id == project_id,
            SinglePromptStrategyExecution.prompt_id == prompt_id,
        )
        .order_by(SinglePromptExecutionProposal.created_at, SinglePromptExecutionProposal.proposal_id)
        .all()
    )
    deliveries_by_analysis: dict[str, list[dict[str, Any]]] = {}
    for proposal, result, strategy in deliveries:
        deliveries_by_analysis.setdefault(proposal.analysis_id, []).append({
            "proposal_id": proposal.proposal_id,
            "result_version": result.result_version,
            "result_hash": result.output_hash,
            "strategy_id": proposal.strategy_id,
            "strategy_result_version": proposal.strategy_result_version,
            "diagnosis_id": proposal.diagnosis_id,
            "diagnosis_result_version": strategy.diagnosis_result_version,
        })
    for status in statuses:
        status["saved_deliveries"] = deliveries_by_analysis.get(status["analysis"]["analysis_id"], [])

    preparations = (
        db.query(SinglePromptSourcePreparation)
        .filter(SinglePromptSourcePreparation.analysis_id.in_(analysis_ids))
        .all()
    )
    preparation_by_analysis = {row.analysis_id: row for row in preparations}
    preparation_ids = [row.preparation_id for row in preparations]
    dispositions = (
        db.query(SinglePromptSourceDisposition)
        .filter(SinglePromptSourceDisposition.preparation_id.in_(preparation_ids))
        .all()
        if preparation_ids
        else []
    )
    states_by_preparation: dict[str, dict[str, int]] = {}
    for row in dispositions:
        counts = states_by_preparation.setdefault(row.preparation_id, {})
        counts[row.state] = counts.get(row.state, 0) + 1

    for status in statuses:
        preparation = preparation_by_analysis.get(status["analysis"]["analysis_id"])
        if not preparation:
            status["source_preparation_summary"] = None
            continue
        counts = states_by_preparation.get(preparation.preparation_id, {})
        required = sum(counts.values())
        terminal = counts.get("READY", 0) + counts.get("WAIVED_WITH_LIMITATION", 0)
        status["source_preparation_summary"] = {
            "preparation_id": preparation.preparation_id,
            "status": preparation.status,
            "required_source_count": required,
            "ready_source_count": counts.get("READY", 0),
            "waived_source_count": counts.get("WAIVED_WITH_LIMITATION", 0),
            "nonterminal_source_count": required - terminal,
            "completion_manifest_id": preparation.current_completion_manifest_id,
        }
    return statuses
