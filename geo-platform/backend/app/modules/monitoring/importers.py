from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import BrowserMonitorRun, BrowserMonitorTask, Project, Prompt
from app.modules.monitoring.collectors.base import CollectorResult
from app.modules.monitoring.collectors.wenxin.url_normalizer import canonicalize_url, domain_from_url
from app.modules.monitoring.enums import BROWSER_AUDIT_ENTRY_TYPE, WENXIN_PLATFORM, WENXIN_WEB_ADAPTER
from app.modules.monitoring.executor import MonitoringTaskExecutor
from app.services.serialization import dumps


def collector_result_from_wenxin_plugin_payload(payload: dict[str, Any]) -> CollectorResult:
    references = []
    citations = payload.get("explicit_citations") or payload.get("citations") or []
    for index, citation in enumerate(citations, start=1):
        url = str(citation.get("url") or "").strip()
        canonical_url = canonicalize_url(url) if url else ""
        title = str(
            citation.get("display_title")
            or citation.get("title")
            or citation.get("matched_title")
            or ""
        ).strip()
        references.append(
            {
                "reference_index": citation.get("reference_index") or citation.get("order") or index,
                "display_title": title,
                "matched_title": str(citation.get("matched_title") or title).strip(),
                "url": url,
                "canonical_url": canonical_url,
                "domain": str(citation.get("domain") or domain_from_url(url)).strip(),
                "resolution_method": str(citation.get("resolution_method") or ("plugin_direct_url" if url else "plugin_unresolved")),
                "match_confidence": float(citation.get("match_confidence") or (1.0 if url else 0.0)),
                "evidence_path": str(payload.get("page_url") or ""),
            }
        )

    answer = payload.get("answer") or {}
    task = payload.get("task") or {}
    page = payload.get("page") or {}
    return CollectorResult(
        answer_text=str(answer.get("text") or payload.get("answer_text") or ""),
        answer_html=str(answer.get("html") or payload.get("answer_html") or ""),
        references=references,
        retrieval_candidates=[],
        artifacts=[
            {
                "artifact_type": "answer_html",
                "filename": "answer.html",
                "mime_type": "text/html",
                "content": str(answer.get("html") or payload.get("answer_html") or ""),
            },
            {
                "artifact_type": "plugin_payload",
                "filename": "plugin_payload.json",
                "mime_type": "application/json",
                "content": dumps(payload),
            },
        ],
    )


def import_wenxin_plugin_payload(
    db: Session,
    project_id: int,
    payload: dict[str, Any],
    prompt_id: Optional[int] = None,
) -> BrowserMonitorRun:
    project = db.get(Project, project_id)
    if not project:
        raise ValueError(f"Project not found: {project_id}")

    task_payload = payload.get("task") or {}
    page_payload = payload.get("page") or {}
    query = str(task_payload.get("original_query") or payload.get("query") or "").strip()
    prompt = db.get(Prompt, prompt_id) if prompt_id else None
    if prompt_id and not prompt:
        raise ValueError(f"Prompt not found: {prompt_id}")
    if not prompt:
        prompt = Prompt(
            project_id=project.id,
            title=(query[:80] or "文心插件导入问题"),
            prompt_text=query or "插件导入未提供原始问题",
            prompt_group="文心网页审计导入",
            intent_type="supplier_recommendation",
            importance=5,
            enabled=True,
        )
        db.add(prompt)
        db.flush()

    task = BrowserMonitorTask(
        project_id=project.id,
        platform=WENXIN_PLATFORM,
        source_type=BROWSER_AUDIT_ENTRY_TYPE,
        adapter=WENXIN_WEB_ADAPTER,
        question_ids_json=dumps([prompt.id]),
        run_count=1,
        schedule_type="plugin_import",
        status="completed",
        created_by=str((payload.get("collector") or {}).get("type") or "wenxin_plugin_import"),
    )
    db.add(task)
    db.flush()

    collected_at = _parse_datetime(payload.get("collected_at"))
    run = BrowserMonitorRun(
        task_id=task.id,
        project_id=project.id,
        prompt_id=prompt.id,
        platform=WENXIN_PLATFORM,
        source_type=BROWSER_AUDIT_ENTRY_TYPE,
        adapter=WENXIN_WEB_ADAPTER,
        run_sequence=1,
        status="running",
        stage="importing_plugin_payload",
        original_query=query or prompt.prompt_text,
        page_query=str(task_payload.get("page_query") or page_payload.get("url") or payload.get("page_url") or ""),
        retrieval_query=query or prompt.prompt_text,
        started_at=collected_at or datetime.utcnow(),
    )
    db.add(run)
    db.flush()

    result = collector_result_from_wenxin_plugin_payload(payload)
    executor = MonitoringTaskExecutor()
    executor.apply_result(db, run, project, result)
    run.finished_at = collected_at or datetime.utcnow()
    run.duration_ms = 0
    executor.artifacts.save_json(
        db,
        run.id,
        "import_metadata",
        "import_metadata.json",
        {
            "schema_version": payload.get("schema_version"),
            "task_id": payload.get("task_id"),
            "platform": payload.get("platform"),
            "platform_domain": payload.get("platform_domain"),
            "page_title": payload.get("page_title"),
            "page_url": payload.get("page_url"),
            "browser_language": payload.get("browser_language"),
            "viewport": payload.get("viewport"),
            "collector": payload.get("collector"),
        },
    )
    db.commit()
    db.refresh(run)
    return run


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
