"""Strict, zero-external-call admission of user-observed AI answers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    BrowserMonitorRun,
    BrowserMonitorTask,
    Project,
    ProjectConfigurationVersion,
    Prompt,
    PromptVersion,
    ReferenceSource,
    SinglePromptManualImport,
)
from app.services.serialization import loads
from app.services.url_identity import url_identity_fields
from .service import _hash, _load_prompt_version_binding, _validate_configuration_binding, _configuration_brand


SOURCE_ASSERTION = "USER_ATTESTED_UNVERIFIED"
METHOD = "MANUAL_IMPORT"
CITATION_STATES = {"COMPLETE", "CONFIRMED_NONE", "UNKNOWN", "PARSE_FAILED"}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text_sha(value: str) -> str:
    """Hash the immutable answer bytes, independently from JSON serialization."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _require_time_valid_version(db: Session, row: Any, model: Any, scope_filters: dict[str, Any], observed_at: datetime) -> None:
    if observed_at < row.created_at:
        raise HTTPException(409, detail={"code": "VERSION_NOT_YET_EFFECTIVE", "message": "所选版本在实际观察时间尚未创建"})
    next_row = db.query(model).filter_by(**scope_filters).filter(
        model.version_number > row.version_number,
    ).order_by(model.version_number.asc()).first()
    if next_row and observed_at >= next_row.created_at:
        raise HTTPException(409, detail={"code": "VERSION_SUPERSEDED_AT_OBSERVATION", "message": "实际观察时间不属于所选版本的生效区间"})


def _configuration_binding(db: Session, project_id: int, version_id: str, snapshot_hash: str) -> tuple[ProjectConfigurationVersion, dict[str, Any]]:
    row = db.query(ProjectConfigurationVersion).filter_by(
        project_id=project_id,
        configuration_version_id=version_id,
        snapshot_hash=snapshot_hash,
    ).one_or_none()
    snapshot = loads(row.snapshot_json, {}) if row else {}
    if not row or not isinstance(snapshot, dict) or snapshot.get("project_id") != project_id or _hash(snapshot) != row.snapshot_hash:
        raise HTTPException(409, detail={"code": "PROJECT_CONFIGURATION_BINDING_MISMATCH", "message": "项目配置版本、归属或 hash 不匹配"})
    binding = {
        "binding_status": "BOUND",
        "configuration_version_id": row.configuration_version_id,
        "version_number": row.version_number,
        "snapshot_hash": row.snapshot_hash,
        "brand": _configuration_brand(snapshot),
    }
    return row, _validate_configuration_binding(db, project_id, binding)


def _validate_citations(state: str, citations: list[dict[str, str]], note: str) -> list[dict[str, str]]:
    if state not in CITATION_STATES:
        raise HTTPException(422, "引用观察状态无效")
    normalized: list[dict[str, str]] = []
    for item in citations:
        url = str(item.get("url") or "").strip()
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise HTTPException(422, "引用 URL 必须是完整的 http/https 地址")
        normalized.append({"title": str(item.get("title") or "").strip(), "url": url})
    if state == "CONFIRMED_NONE" and normalized:
        raise HTTPException(422, "确认无引用时不能同时提交引用 URL")
    if state == "COMPLETE" and not normalized:
        raise HTTPException(422, "完整引用记录至少需要一条引用；无引用请选择“已确认无引用”")
    if state in {"UNKNOWN", "PARSE_FAILED"} and not note.strip():
        raise HTTPException(422, "引用未知或解析失败时必须填写说明")
    return normalized


def import_manual_observation(
    db: Session,
    *,
    project_id: int,
    prompt_id: int,
    prompt_version_id: str,
    prompt_snapshot_hash: str,
    configuration_version_id: str,
    configuration_snapshot_hash: str,
    observed_at: datetime,
    source_platform: str,
    source_page_url: str,
    answer_text: str,
    citations: list[dict[str, str]],
    citation_observation_status: str,
    citation_note: str,
    imported_by: str,
    idempotency_key: str,
) -> tuple[SinglePromptManualImport, BrowserMonitorRun, bool]:
    project, prompt = db.get(Project, project_id), db.get(Prompt, prompt_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    if not prompt or prompt.project_id != project_id:
        raise HTTPException(404, "Prompt 不存在或不属于当前项目")
    observed = _utc_naive(observed_at)
    if observed > datetime.utcnow() + timedelta(minutes=5):
        raise HTTPException(422, "实际观察时间不能晚于当前时间")
    answer = answer_text.strip()
    if len(answer) < 20:
        raise HTTPException(422, "回答正文过短，不能作为完整人工观测导入")
    if source_platform != "wenxin":
        raise HTTPException(422, "当前最小入口只接受明确标记的文心助手人工观测")
    if source_page_url:
        parts = urlsplit(source_page_url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise HTTPException(422, "来源页面必须是完整的 http/https 地址")

    prompt_binding = _load_prompt_version_binding(
        db, project_id=project_id, prompt_id=prompt_id,
        prompt_version_id=prompt_version_id, snapshot_hash=prompt_snapshot_hash,
    )
    prompt_row = db.query(PromptVersion).filter_by(prompt_version_id=prompt_version_id).one()
    _require_time_valid_version(db, prompt_row, PromptVersion,
                                {"project_id": project_id, "prompt_id": prompt_id}, observed)
    config_row, config_binding = _configuration_binding(
        db, project_id, configuration_version_id, configuration_snapshot_hash,
    )
    _require_time_valid_version(db, config_row, ProjectConfigurationVersion,
                                {"project_id": project_id}, observed)
    normalized_citations = _validate_citations(citation_observation_status, citations, citation_note)

    identity = {
        "contract_version": "manual-observation-run.v1",
        "project_id": project_id,
        "prompt_id": prompt_id,
        "prompt_version": prompt_binding,
        "project_configuration": config_binding,
        "observed_at": observed.isoformat() + "Z",
        "source_platform": source_platform,
        "source_page_url": source_page_url,
        "sampling_mode": METHOD,
        "source_assertion_status": SOURCE_ASSERTION,
        "imported_by": imported_by,
    }
    payload = {
        "identity": identity,
        "answer_text": answer,
        "citations": normalized_citations,
        "citation_observation_status": citation_observation_status,
        "citation_note": citation_note.strip(),
    }
    payload_hash = _sha(payload)
    existing = db.query(SinglePromptManualImport).filter_by(
        project_id=project_id, idempotency_key=idempotency_key,
    ).one_or_none()
    if existing:
        if existing.payload_hash != payload_hash or existing.prompt_id != prompt_id:
            raise HTTPException(409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": "幂等键已用于不同人工观测"})
        return existing, db.get(BrowserMonitorRun, existing.run_id), False
    duplicate = db.query(SinglePromptManualImport).filter_by(
        project_id=project_id, prompt_id=prompt_id, payload_hash=payload_hash,
    ).one_or_none()
    if duplicate:
        raise HTTPException(409, detail={"code": "DUPLICATE_MANUAL_IMPORT", "message": f"相同观测已导入为 Run {duplicate.run_id}"})

    import_id = f"manual-import-{uuid4()}"
    task = BrowserMonitorTask(
        project_id=project_id, platform=source_platform, source_type="manual_observation",
        adapter="manual_import", question_ids_json=json.dumps([prompt_id]), run_count=1,
        schedule_type="manual_import", status="completed", created_by=f"manual_import:{import_id}",
    )
    db.add(task)
    db.flush()
    complete_references = citation_observation_status in {"COMPLETE", "CONFIRMED_NONE"}
    run = BrowserMonitorRun(
        task_id=task.id, project_id=project_id, prompt_id=prompt_id, platform=source_platform,
        source_type="manual_observation", adapter="manual_import", run_sequence=1, sample_index=1,
        collection_mode="manual_observation", collector_id="manual-import", sampling_mode=METHOD,
        collector_version="manual-import.v1", parser_version="manual-citation.v1",
        status="success" if complete_references else "partial_success",
        stage="success" if complete_references else "partial_success",
        original_query=prompt_binding["snapshot"]["prompt_text"], page_query=prompt_binding["snapshot"]["prompt_text"],
        started_at=observed, finished_at=observed, duration_ms=0,
        answer_text=answer, answer_char_count=len(answer),
        expected_reference_count=len(normalized_citations), detected_reference_count=len(normalized_citations),
        resolved_reference_count=len(normalized_citations), parsed_reference_count=len(normalized_citations),
        ui_declared_count=len(normalized_citations), dom_reference_count=len(normalized_citations),
        resolved_url_count=len(normalized_citations), reference_complete=complete_references,
        error_stage="" if complete_references else "reference_observation",
        error_type="" if complete_references else citation_observation_status.lower(),
        error_message="" if complete_references else citation_note.strip(),
        outcome_category="manual_observation_admitted" if complete_references else "manual_observation_partial",
    )
    db.add(run)
    db.flush()
    for index, item in enumerate(normalized_citations, start=1):
        url = item["url"]
        db.add(ReferenceSource(
            run_id=run.id, reference_index=index, display_title=item["title"], matched_title=item["title"],
            url=url, **url_identity_fields(url, url), domain=urlsplit(url).hostname or "",
            platform_name="文心助手", resolution_method="manual_observation",
            match_confidence=1.0, relevance_label="unreviewed", quality_label="unknown",
        ))
    record = SinglePromptManualImport(
        import_id=import_id, project_id=project_id, prompt_id=prompt_id, task_id=task.id, run_id=run.id,
        idempotency_key=idempotency_key, source_platform=source_platform,
        source_assertion_status=SOURCE_ASSERTION, citation_observation_status=citation_observation_status,
        observed_at=observed, imported_by=imported_by,
        identity_json=_canonical(identity), identity_hash=_sha(identity), payload_json=_canonical(payload),
        payload_hash=payload_hash, answer_hash=_text_sha(answer), citations_hash=_sha(normalized_citations),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    db.refresh(run)
    return record, run, True


def manual_import_binding(db: Session, run: BrowserMonitorRun) -> dict[str, Any] | None:
    record = db.query(SinglePromptManualImport).filter_by(run_id=run.id).one_or_none()
    if not record:
        return None
    identity = loads(record.identity_json, {})
    payload = loads(record.payload_json, {})
    if (record.project_id != run.project_id or record.prompt_id != run.prompt_id
            or record.task_id != run.task_id or record.source_assertion_status != SOURCE_ASSERTION
            or _sha(identity) != record.identity_hash or _sha(payload) != record.payload_hash
            or payload.get("identity") != identity
            or not isinstance(payload.get("answer_text"), str)
            or _text_sha(payload["answer_text"]) != record.answer_hash
            or _sha(payload.get("citations")) != record.citations_hash
            or run.sampling_mode != METHOD or run.source_type != "manual_observation"
            or run.adapter != "manual_import" or run.answer_text != payload.get("answer_text")
            or run.original_query != (identity.get("prompt_version") or {}).get("snapshot", {}).get("prompt_text")):
        raise HTTPException(409, detail={"code": "MANUAL_IMPORT_INTEGRITY_FAILURE", "message": "人工导入 Run 身份或内容 hash 不匹配"})
    return identity


def manual_import_view(record: SinglePromptManualImport, run: BrowserMonitorRun, created: bool) -> dict[str, Any]:
    return {
        "created": created, "import_id": record.import_id, "run_id": run.id, "task_id": run.task_id,
        "status": run.status, "sampling_mode": METHOD, "source_type": run.source_type,
        "source_assertion_status": record.source_assertion_status,
        "citation_observation_status": record.citation_observation_status,
        "observed_at": record.observed_at, "imported_at": record.created_at, "imported_by": record.imported_by,
        "identity_hash": record.identity_hash, "payload_hash": record.payload_hash,
        "answer_hash": record.answer_hash, "citations_hash": record.citations_hash,
        "warning": "人工提供的来源信息尚未经系统独立核实；内容 hash 只证明本地记录未变。",
    }
