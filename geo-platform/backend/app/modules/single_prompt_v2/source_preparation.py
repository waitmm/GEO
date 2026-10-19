"""Analysis-owned citation inventory and immutable source preparation.

This module is the V2 control plane for source content. It deliberately does
not call legacy diagnosis runners or discover a latest snapshot.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    SinglePromptAnalysis,
    SinglePromptAnalysisContext,
    SinglePromptCitationManifest,
    SinglePromptCitationRefresh,
    SinglePromptPreparedSourceSnapshot,
    SinglePromptSourceCompletionManifest,
    SinglePromptSourceDisposition,
    SinglePromptSourcePreparation,
)
from app.services.serialization import loads
from app.services.url_identity import canonicalize_url
from app.modules.optimization.passage_service import fetch_page_playwright
from app.modules.optimization.primary_content import extract_from_html


CITATION_MANIFEST_CONTRACT_VERSION = "single_prompt_citation_manifest.v1"
URL_IDENTITY_VERSION = "single_prompt_source_identity.v1"
SOURCE_PREPARATION_CONTRACT_VERSION = "single_prompt_source_preparation.v2_explicit_partial"
SOURCE_CONTENT_GATE_VERSION = "single_prompt_source_content_gate.v3_auto_then_manual"
PASSAGE_SPLIT_VERSION = "single_prompt_passage_split.v1"
CITATION_REFRESH_CONTRACT_VERSION = "single_prompt_citation_refresh.v1"


class _TransportDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    url: str = Field(min_length=1, max_length=8192)
    status: int = Field(ge=100, le=599)
    tls_verified: bool
    public_address_pinned: Literal[True]
    response_body_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_type: str = Field(max_length=1000)
    last_modified: str = Field(max_length=1000)


class _AcquisitionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    contract_version: Literal["source-acquisition.v1"]
    requested_url: str = Field(min_length=1, max_length=8192)
    final_url: str = Field(min_length=1, max_length=8192)
    acquired_at: str
    method: str = Field(min_length=1, max_length=120)
    network_policy: Literal["PUBLIC_DNS_PINNED_TLS_VERIFIED_V1"]
    documents: list[_TransportDocument] = Field(min_length=1, max_length=64)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    scope: Literal["TRANSPORT_AND_EXTRACTED_CONTENT_ONLY"]


def _validate_acquisition_receipt(receipt: dict, *, text_hash: str, source_url: str,
                                  acquired_at: datetime, method: str) -> None:
    if receipt == {}:
        return
    try:
        parsed = _AcquisitionReceipt.model_validate(receipt)
        final = next((d for d in reversed(parsed.documents) if d.url == parsed.final_url), None)
        urls = [parsed.requested_url, parsed.final_url, *(d.url for d in parsed.documents)]
        valid = (method in {"AUTO_FETCH", "EXACT_SNAPSHOT_REUSE"}
                 and parsed.content_hash == text_hash
                 and canonicalize_url(parsed.requested_url) == canonicalize_url(source_url)
                 and datetime.fromisoformat(parsed.acquired_at) == acquired_at
                 and final is not None and 200 <= final.status < 300
                 and all(_is_fetchable_public_url(url) for url in urls)
                 and all(d.tls_verified == (urlparse(d.url).scheme == 'https') for d in parsed.documents))
        if not valid:
            raise ValueError("binding")
    except (ValueError, TypeError, ValidationError) as exc:
        raise ValueError("SOURCE_ACQUISITION_RECEIPT_INVALID") from exc

READY_STATE = "READY"
WAIVED_STATE = "WAIVED_WITH_LIMITATION"
TERMINAL_STATES = {READY_STATE, WAIVED_STATE}
AUTO_FETCH_PENDING_STATUS = "AUTO_FETCH_PENDING"
AUTO_FETCH_QUEUED_STATUS = "AUTO_FETCH_QUEUED"
AUTO_FETCHING_STATUS = "AUTO_FETCHING"
MANUAL_REQUIRED_STATUS = "MANUAL_REQUIRED"
AUTO_FETCH_QUEUED_STATE = "AUTO_FETCH_QUEUED"
AUTO_FETCHING_STATE = "AUTO_FETCHING"
MANUAL_REQUIRED_STATE = "MANUAL_REQUIRED"
ACTIVE_AUTO_FETCH_STATUSES = {AUTO_FETCH_QUEUED_STATUS, AUTO_FETCHING_STATUS}

_CONTENT_BLOCK_MARKERS = (
    "验证码",
    "安全验证",
    "请完成验证",
    "人机验证",
    "登录后继续",
    "请先登录",
    "访问过于频繁",
    "security verification",
    "access denied",
    "are you a robot",
    "enable javascript and cookies to continue",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _analysis_context(
    db: Session,
    *,
    analysis_id: str,
    project_id: int,
    prompt_id: int,
) -> tuple[SinglePromptAnalysis, SinglePromptAnalysisContext]:
    analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=analysis_id).one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="V2 分析不存在")
    if analysis.project_id != project_id or analysis.prompt_id != prompt_id:
        raise HTTPException(status_code=409, detail="分析身份与当前 Project/Prompt 不匹配")
    context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis_id).one_or_none()
    if not context:
        raise HTTPException(status_code=409, detail="采样结果尚未冻结，不能冻结引用范围")
    return analysis, context


def _source_identity(reference: dict[str, Any]) -> tuple[str, str]:
    canonical = canonicalize_url(str(reference.get("canonical_url") or reference.get("url") or ""))
    fallback = "|".join([
        str(reference.get("domain") or "").strip().lower(),
        str(reference.get("title") or "").strip(),
        str(reference.get("url") or "").strip(),
    ])
    identity = canonical or fallback
    return _hash({"version": URL_IDENTITY_VERSION, "source_identity": identity}), canonical


def build_citation_manifest_payload(context: SinglePromptAnalysisContext) -> dict[str, Any]:
    raw_output = loads(context.raw_output_json, {})
    grouped: dict[str, dict[str, Any]] = {}
    occurrences: list[dict[str, Any]] = []
    for run in raw_output.get("runs") or []:
        run_id = int(run.get("run_id") or 0)
        for reference in run.get("references") or []:
            source_key, canonical_url = _source_identity(reference)
            occurrence = {
                "run_id": run_id,
                "reference_id": reference.get("reference_id"),
                "reference_index": reference.get("index"),
                "title": str(reference.get("title") or ""),
                "url": str(reference.get("url") or ""),
                "canonical_url": canonical_url,
                "domain": str(reference.get("domain") or ""),
                "source_key": source_key,
            }
            occurrences.append(occurrence)
            row = grouped.setdefault(source_key, {
                "source_key": source_key,
                "canonical_url": canonical_url,
                "original_urls": set(),
                "observations": [],
            })
            if reference.get("url"):
                row["original_urls"].add(str(reference["url"]))
            row["observations"].append({
                key: occurrence[key]
                for key in ("run_id", "reference_id", "reference_index", "title", "domain")
            })
    sources = [
        {**row, "original_urls": sorted(row["original_urls"]), "occurrence_count": len(row["observations"])}
        for _, row in sorted(grouped.items())
    ]
    occurrences.sort(key=lambda row: (row["run_id"], int(row["reference_index"] or 0), str(row["reference_id"] or "")))
    return {
        "contract_version": CITATION_MANIFEST_CONTRACT_VERSION,
        "analysis_id": context.analysis_id,
        "context_id": context.context_id,
        "raw_output_hash": context.raw_output_hash,
        "url_identity_version": URL_IDENTITY_VERSION,
        "occurrences": occurrences,
        "sources": sources,
        "source_count": len(sources),
        "occurrence_count": len(occurrences),
    }


def create_source_preparation(
    db: Session,
    *,
    analysis_id: str,
    project_id: int,
    prompt_id: int,
    idempotency_key: str,
    created_by: str,
) -> tuple[SinglePromptSourcePreparation, bool]:
    _, context = _analysis_context(
        db,
        analysis_id=analysis_id,
        project_id=project_id,
        prompt_id=prompt_id,
    )
    payload = build_citation_manifest_payload(context)
    payload_hash = _hash(payload)
    manifest = (
        db.query(SinglePromptCitationManifest)
        .filter_by(analysis_id=analysis_id, version_number=1)
        .one_or_none()
    )
    if manifest:
        if manifest.context_id != context.context_id or manifest.payload_hash != payload_hash:
            raise HTTPException(status_code=409, detail="已冻结的 Citation Manifest 与当前 Context 不一致")
    else:
        manifest = SinglePromptCitationManifest(
            manifest_id=f"citation-manifest-{uuid4()}",
            analysis_id=analysis_id,
            context_id=context.context_id,
            project_id=project_id,
            prompt_id=prompt_id,
            version_number=1,
            raw_output_hash=context.raw_output_hash,
            url_identity_version=URL_IDENTITY_VERSION,
            payload_json=_canonical_json(payload),
            payload_hash=payload_hash,
            source_count=payload["source_count"],
            occurrence_count=payload["occurrence_count"],
            created_by=created_by,
        )
        db.add(manifest)
        db.flush()

    existing = db.query(SinglePromptSourcePreparation).filter_by(citation_manifest_id=manifest.manifest_id).one_or_none()
    if existing:
        if existing.idempotency_key != idempotency_key:
            # Citation Manifest has one authoritative preparation. A second key
            # reads that identity instead of creating a parallel mutable truth.
            return existing, False
        return existing, False

    preparation = SinglePromptSourcePreparation(
        preparation_id=f"source-prep-{uuid4()}",
        analysis_id=analysis_id,
        context_id=context.context_id,
        citation_manifest_id=manifest.manifest_id,
        citation_manifest_hash=manifest.payload_hash,
        project_id=project_id,
        prompt_id=prompt_id,
        idempotency_key=idempotency_key,
        status=AUTO_FETCH_PENDING_STATUS if payload["source_count"] else "READY_TO_FREEZE",
        created_by=created_by,
    )
    db.add(preparation)
    db.flush()
    for source in payload["sources"]:
        db.add(SinglePromptSourceDisposition(
            disposition_id=f"source-disposition-{uuid4()}",
            preparation_id=preparation.preparation_id,
            source_key=source["source_key"],
            canonical_url=source["canonical_url"],
            original_urls_json=_canonical_json(source["original_urls"]),
            reference_observations_json=_canonical_json(source["observations"]),
            occurrence_count=source["occurrence_count"],
            state="PENDING",
        ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.query(SinglePromptSourcePreparation).filter_by(citation_manifest_id=manifest.manifest_id).one_or_none()
        if concurrent:
            return concurrent, False
        raise
    db.refresh(preparation)
    return preparation, True


def _content_block_reason(title: str, clean_text: str) -> str:
    sample = f"{title}\n{clean_text[:3000]}".lower()
    marker = next((item for item in _CONTENT_BLOCK_MARKERS if item.lower() in sample), "")
    return f"疑似验证、登录或拦截页面（marker={marker}）" if marker else ""


def _split_passages(clean_text: str, source_key: str) -> list[dict[str, Any]]:
    passages: list[dict[str, Any]] = []
    paragraphs = [part.strip() for part in re.split(r"\n+", clean_text) if len(part.strip()) >= 20]
    for paragraph in paragraphs:
        for start in range(0, len(paragraph), 1500):
            text = paragraph[start:start + 1500]
            content_hash = _text_hash(text)
            passages.append({
                "passage_id": f"psg-{source_key[:10]}-{len(passages) + 1}-{content_hash[:10]}",
                "text": text,
                "content_hash": content_hash,
            })
    return passages


def _artifact_path(snapshot_id: str, context_id: str, preparation_id: str, source_key: str) -> Path:
    root = Path(get_settings().evidence_artifact_dir).resolve()
    path = root / context_id / preparation_id / source_key / f"{snapshot_id}.txt"
    if root not in path.resolve().parents:
        raise HTTPException(status_code=400, detail="正文文件路径越界")
    return path


def _write_immutable_artifact(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise HTTPException(status_code=409, detail="不可变正文文件已存在")
    temporary = path.with_suffix(f".tmp-{uuid4().hex}")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _is_fetchable_public_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host or host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
    )


def _snapshot_from_content(
    db: Session,
    *,
    preparation: SinglePromptSourcePreparation,
    disposition: SinglePromptSourceDisposition,
    title: str,
    clean_text: str,
    coverage_scope: str,
    acquisition_method: str,
    submitted_by: str,
    acquired_at: datetime | None = None,
    acquisition_receipt: dict | None = None,
) -> SinglePromptPreparedSourceSnapshot:
    text = clean_text.strip()
    acquired_at = acquired_at or datetime.utcnow()
    receipt = acquisition_receipt if acquisition_receipt is not None else {}
    _validate_acquisition_receipt(receipt, text_hash=_text_hash(text), source_url=disposition.canonical_url,
                                  acquired_at=acquired_at, method=acquisition_method)
    block_reason = _content_block_reason(title, text)
    if block_reason:
        raise ValueError(block_reason)
    passages = _split_passages(text, disposition.source_key)
    if not passages:
        raise ValueError("正文没有形成任何合格 passage")
    snapshot_id = f"source-snapshot-{uuid4()}"
    artifact_path = _artifact_path(
        snapshot_id,
        preparation.context_id,
        preparation.preparation_id,
        disposition.source_key,
    )
    _write_immutable_artifact(artifact_path, text)
    content_hash = _text_hash(text)
    snapshot = SinglePromptPreparedSourceSnapshot(
        snapshot_id=snapshot_id,
        preparation_id=preparation.preparation_id,
        context_id=preparation.context_id,
        citation_manifest_id=preparation.citation_manifest_id,
        source_key=disposition.source_key,
        canonical_url=disposition.canonical_url,
        original_urls_json=disposition.original_urls_json,
        reference_observations_json=disposition.reference_observations_json,
        occurrence_count=disposition.occurrence_count,
        title=title.strip()[:500],
        content_hash=content_hash,
        clean_text=text,
        artifact_path=str(artifact_path),
        artifact_hash=content_hash,
        passages_json=_canonical_json(passages),
        passages_hash=_hash(passages),
        parser_version=PASSAGE_SPLIT_VERSION,
        acquisition_method=acquisition_method,
        acquisition_receipt_json=_canonical_json(receipt),
        coverage_scope=coverage_scope,
        acquired_at=acquired_at,
        submitted_by=submitted_by,
    )
    db.add(snapshot)
    disposition.state = READY_STATE
    disposition.active_snapshot_id = snapshot_id
    disposition.failure_code = ""
    disposition.failure_detail = ""
    disposition.waiver_reason = ""
    disposition.waiver_impact = ""
    disposition.waived_by = ""
    disposition.waived_at = None
    disposition.row_version += 1
    return snapshot


def _refresh_preparation_status(
    db: Session,
    preparation: SinglePromptSourcePreparation,
) -> None:
    # Status aggregation must observe disposition changes made in this unit of
    # work, not the pre-fetch values still stored in the database.
    db.flush()
    states = [
        row[0]
        for row in db.query(SinglePromptSourceDisposition.state)
        .filter_by(preparation_id=preparation.preparation_id)
        .all()
    ]
    if states and all(state in TERMINAL_STATES for state in states):
        preparation.status = "READY_TO_FREEZE"
    elif any(state == MANUAL_REQUIRED_STATE for state in states):
        preparation.status = MANUAL_REQUIRED_STATUS
    elif states:
        preparation.status = AUTO_FETCH_PENDING_STATUS
    else:
        preparation.status = "READY_TO_FREEZE"
    preparation.current_completion_manifest_id = None


def queue_auto_fetch(
    db: Session,
    *,
    preparation_id: str,
    project_id: int,
    prompt_id: int,
) -> SinglePromptSourcePreparation:
    preparation = db.query(SinglePromptSourcePreparation).filter_by(preparation_id=preparation_id).one_or_none()
    if not preparation:
        raise HTTPException(status_code=404, detail="来源准备不存在")
    if preparation.project_id != project_id or preparation.prompt_id != prompt_id:
        raise HTTPException(status_code=409, detail="来源准备与当前 Project/Prompt 不匹配")
    if preparation.status in {AUTO_FETCH_QUEUED_STATUS, AUTO_FETCHING_STATUS}:
        return preparation
    candidates = (
        db.query(SinglePromptSourceDisposition)
        .filter(
            SinglePromptSourceDisposition.preparation_id == preparation_id,
            SinglePromptSourceDisposition.state.notin_(TERMINAL_STATES),
        )
        .all()
    )
    if not candidates:
        raise HTTPException(status_code=409, detail="没有需要自动获取的来源")
    for row in candidates:
        row.state = AUTO_FETCH_QUEUED_STATE
        row.row_version += 1
    preparation.status = AUTO_FETCH_QUEUED_STATUS
    preparation.current_completion_manifest_id = None
    db.commit()
    db.refresh(preparation)
    return preparation


def execute_auto_fetch(
    preparation_id: str,
    *,
    session_factory: Callable[[], Session],
    fetcher: Callable[..., list[dict[str, Any]]] = fetch_page_playwright,
) -> dict[str, int]:
    db = session_factory()
    try:
        preparation = db.query(SinglePromptSourcePreparation).filter_by(preparation_id=preparation_id).one_or_none()
        if not preparation or preparation.status != AUTO_FETCH_QUEUED_STATUS:
            return {"requested": 0, "ready": 0, "manual_required": 0}
        rows = (
            db.query(SinglePromptSourceDisposition)
            .filter_by(preparation_id=preparation_id, state=AUTO_FETCH_QUEUED_STATE)
            .order_by(SinglePromptSourceDisposition.source_key)
            .all()
        )
        preparation.status = AUTO_FETCHING_STATUS
        requests: list[dict[str, Any]] = []
        for row in rows:
            row.state = AUTO_FETCHING_STATE
            urls = loads(row.original_urls_json, [])
            url = row.canonical_url or (str(urls[0]) if urls else "")
            requests.append({"disposition_id": row.disposition_id, "url": url})
        db.commit()
    finally:
        db.close()

    fetchable = [item for item in requests if _is_fetchable_public_url(item["url"])]
    fetched_results: list[dict[str, Any]] = []
    if fetchable:
        try:
            fetched_results = fetcher([item["url"] for item in fetchable])
        except Exception as exc:
            fetched_results = [
                {"fetch_status": "FETCH_FAILED", "failure_reason": str(exc)[:500]}
                for _ in fetchable
            ]
    result_by_disposition = {
        item["disposition_id"]: (
            fetched_results[index]
            if index < len(fetched_results)
            else {"fetch_status": "FETCH_FAILED", "failure_reason": "正文抓取器未返回对应结果"}
        )
        for index, item in enumerate(fetchable)
    }

    ready = 0
    manual_required = 0
    db = session_factory()
    try:
        preparation = db.query(SinglePromptSourcePreparation).filter_by(preparation_id=preparation_id).one()
        rows = (
            db.query(SinglePromptSourceDisposition)
            .filter_by(preparation_id=preparation_id, state=AUTO_FETCHING_STATE)
            .order_by(SinglePromptSourceDisposition.source_key)
            .all()
        )
        for row in rows:
            request = next(item for item in requests if item["disposition_id"] == row.disposition_id)
            result = result_by_disposition.get(row.disposition_id)
            failure_code = ""
            failure_detail = ""
            if not _is_fetchable_public_url(request["url"]):
                failure_code = "UNSAFE_OR_MISSING_SOURCE_URL"
                failure_detail = "来源 URL 缺失或不符合公网 HTTP(S) 访问限制"
            elif not result:
                failure_code = "FETCH_FAILED"
                failure_detail = "正文抓取器没有返回结果"
            else:
                status = str(result.get("fetch_status") or "FETCH_FAILED").upper()
                text = str(result.get("clean_text") or "").strip()
                final_url = str(result.get("canonical_url") or request["url"])
                if not _is_fetchable_public_url(final_url):
                    failure_code = "UNSAFE_REDIRECT_TARGET"
                    failure_detail = "抓取后的最终 URL 不符合公网 HTTP(S) 访问限制"
                elif status != "SUCCESS":
                    failure_code = status
                    failure_detail = str(result.get("failure_reason") or "自动获取未得到完整正文")[:2000]
                elif len(text) < 50:
                    failure_code = "CONTENT_TOO_SHORT"
                    failure_detail = "自动获取正文过短，需人工补录"
                else:
                    block_reason = _content_block_reason(str(result.get("title") or ""), text)
                    if block_reason:
                        failure_code = "CONTENT_BLOCKED"
                        failure_detail = block_reason
                    else:
                        try:
                            _snapshot_from_content(
                                db,
                                preparation=preparation,
                                disposition=row,
                                title=str(result.get("title") or ""),
                                clean_text=text,
                                coverage_scope="FULL_PAGE",
                                acquisition_method="AUTO_FETCH",
                                submitted_by=f"AUTO:{preparation.created_by}",
                                acquired_at=result.get("fetch_time") if isinstance(result.get("fetch_time"), datetime) else None,
                                acquisition_receipt=result.get("acquisition_receipt"),
                            )
                            ready += 1
                            continue
                        except ValueError as exc:
                            failure_code = "CONTENT_BLOCKED"
                            failure_detail = str(exc)[:2000]
            row.state = MANUAL_REQUIRED_STATE
            row.active_snapshot_id = None
            row.failure_code = failure_code or "FETCH_FAILED"
            row.failure_detail = failure_detail or "自动获取失败，需人工补录"
            row.row_version += 1
            manual_required += 1
        _refresh_preparation_status(db, preparation)
        db.commit()
    finally:
        db.close()
    return {"requested": len(requests), "ready": ready, "manual_required": manual_required}


def _refresh_input(row: SinglePromptCitationRefresh) -> dict[str, Any]:
    return {
        "contract_version": CITATION_REFRESH_CONTRACT_VERSION,
        "preparation_id": row.preparation_id,
        "analysis_id": row.analysis_id,
        "context_id": row.context_id,
        "project_id": row.project_id,
        "prompt_id": row.prompt_id,
        "citation_manifest_id": row.citation_manifest_id,
        "citation_manifest_hash": row.citation_manifest_hash,
        "source_key": row.source_key,
        "canonical_url": row.canonical_url,
        "base_completion_manifest_id": row.base_completion_manifest_id,
        "base_completion_version": row.base_completion_version,
        "base_completion_manifest_hash": row.base_completion_manifest_hash,
        "base_snapshot_id": row.base_snapshot_id,
        "base_snapshot_hash": row.base_snapshot_hash,
        "idempotency_key": row.idempotency_key,
        "requested_by": row.requested_by,
    }


def citation_refresh_view(row: SinglePromptCitationRefresh) -> dict[str, Any]:
    return {
        "contract_version": CITATION_REFRESH_CONTRACT_VERSION,
        "refresh_id": row.refresh_id,
        "status": row.status,
        "input": _refresh_input(row),
        "input_hash": row.input_hash,
        "requested_by": row.requested_by,
        "outcome": loads(row.outcome_json, {}),
        "outcome_hash": row.outcome_hash,
        "result_snapshot_id": row.result_snapshot_id,
        "result_completion_manifest_id": row.result_completion_manifest_id,
        "result_completion_manifest_hash": row.result_completion_manifest_hash,
        "failure_code": row.failure_code,
        "failure_detail": row.failure_detail,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


def _require_refresh_scope(db: Session, row: SinglePromptCitationRefresh) -> tuple[
    SinglePromptSourcePreparation,
    SinglePromptSourceDisposition,
    SinglePromptPreparedSourceSnapshot,
    SinglePromptSourceCompletionManifest,
]:
    preparation = db.query(SinglePromptSourcePreparation).filter_by(
        preparation_id=row.preparation_id,
        analysis_id=row.analysis_id,
        context_id=row.context_id,
        project_id=row.project_id,
        prompt_id=row.prompt_id,
        citation_manifest_id=row.citation_manifest_id,
        citation_manifest_hash=row.citation_manifest_hash,
        current_completion_manifest_id=row.base_completion_manifest_id,
    ).one_or_none()
    citation = db.query(SinglePromptCitationManifest).filter_by(
        manifest_id=row.citation_manifest_id,
        analysis_id=row.analysis_id,
        context_id=row.context_id,
        project_id=row.project_id,
        prompt_id=row.prompt_id,
        payload_hash=row.citation_manifest_hash,
    ).one_or_none()
    completion = db.query(SinglePromptSourceCompletionManifest).filter_by(
        manifest_id=row.base_completion_manifest_id,
        preparation_id=row.preparation_id,
        analysis_id=row.analysis_id,
        context_id=row.context_id,
        citation_manifest_id=row.citation_manifest_id,
        citation_manifest_hash=row.citation_manifest_hash,
        version_number=row.base_completion_version,
        payload_hash=row.base_completion_manifest_hash,
    ).one_or_none()
    disposition = db.query(SinglePromptSourceDisposition).filter_by(
        preparation_id=row.preparation_id,
        source_key=row.source_key,
        canonical_url=row.canonical_url,
        state=READY_STATE,
        active_snapshot_id=row.base_snapshot_id,
    ).one_or_none()
    snapshot = db.query(SinglePromptPreparedSourceSnapshot).filter_by(
        snapshot_id=row.base_snapshot_id,
        preparation_id=row.preparation_id,
        context_id=row.context_id,
        citation_manifest_id=row.citation_manifest_id,
        source_key=row.source_key,
        canonical_url=row.canonical_url,
        content_hash=row.base_snapshot_hash,
    ).one_or_none()
    if not all((preparation, citation, completion, disposition, snapshot)):
        raise HTTPException(409, detail={"code": "CITATION_REFRESH_SCOPE_CHANGED"})
    citation_payload = loads(citation.payload_json, {})
    if _hash(citation_payload) != citation.payload_hash:
        raise HTTPException(409, detail={"code": "CITATION_REFRESH_CITATION_MANIFEST_TAMPERED"})
    citation_sources = {
        (str(item.get("source_key") or ""), str(item.get("canonical_url") or ""))
        for item in citation_payload.get("sources") or []
    }
    if (row.source_key, row.canonical_url) not in citation_sources:
        raise HTTPException(409, detail={"code": "CITATION_REFRESH_NOT_CITATION_SOURCE"})
    completion_payload = loads(completion.payload_json, {})
    if _hash(completion_payload) != completion.payload_hash:
        raise HTTPException(409, detail={"code": "CITATION_REFRESH_COMPLETION_MANIFEST_TAMPERED"})
    completion_rows = {
        str(item.get("source_key") or ""): item
        for item in completion_payload.get("sources") or []
    }
    bound = completion_rows.get(row.source_key) or {}
    if (
        bound.get("disposition") != READY_STATE
        or bound.get("snapshot_id") != row.base_snapshot_id
        or bound.get("content_hash") != row.base_snapshot_hash
    ):
        raise HTTPException(409, detail={"code": "CITATION_REFRESH_COMPLETION_BINDING_CHANGED"})
    _verify_snapshot(snapshot)
    return preparation, disposition, snapshot, completion


def request_citation_refresh(
    db: Session,
    *,
    preparation_id: str,
    analysis_id: str,
    context_id: str,
    project_id: int,
    prompt_id: int,
    citation_manifest_id: str,
    citation_manifest_hash: str,
    source_key: str,
    canonical_url: str,
    base_completion_manifest_id: str,
    base_completion_version: int,
    base_completion_manifest_hash: str,
    base_snapshot_id: str,
    base_snapshot_hash: str,
    idempotency_key: str,
    requested_by: str,
) -> tuple[SinglePromptCitationRefresh, bool]:
    if not requested_by.strip():
        raise HTTPException(422, detail={"code": "CITATION_REFRESH_ACTOR_REQUIRED"})
    values = {
        "contract_version": CITATION_REFRESH_CONTRACT_VERSION,
        "preparation_id": preparation_id,
        "analysis_id": analysis_id,
        "context_id": context_id,
        "project_id": project_id,
        "prompt_id": prompt_id,
        "citation_manifest_id": citation_manifest_id,
        "citation_manifest_hash": citation_manifest_hash,
        "source_key": source_key,
        "canonical_url": canonical_url,
        "base_completion_manifest_id": base_completion_manifest_id,
        "base_completion_version": base_completion_version,
        "base_completion_manifest_hash": base_completion_manifest_hash,
        "base_snapshot_id": base_snapshot_id,
        "base_snapshot_hash": base_snapshot_hash,
        "idempotency_key": idempotency_key,
        "requested_by": requested_by.strip(),
    }
    input_hash = _hash(values)
    existing = db.query(SinglePromptCitationRefresh).filter_by(
        preparation_id=preparation_id, idempotency_key=idempotency_key
    ).one_or_none()
    if existing:
        if existing.input_hash != input_hash:
            raise HTTPException(409, detail={"code": "CITATION_REFRESH_IDEMPOTENCY_CONFLICT"})
        return existing, False
    row = SinglePromptCitationRefresh(
        refresh_id=f"citation-refresh-{uuid4()}",
        input_hash=input_hash,
        status="PENDING",
        outcome_json="{}",
        outcome_hash="",
        result_completion_manifest_hash="",
        failure_code="",
        failure_detail="",
        **{key: value for key, value in values.items() if key != "contract_version"},
    )
    db.add(row)
    try:
        db.flush()
        _require_refresh_scope(db, row)
    except Exception:
        db.rollback()
        raise
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.query(SinglePromptCitationRefresh).filter_by(
            preparation_id=preparation_id, idempotency_key=idempotency_key
        ).one()
        if concurrent.input_hash != input_hash:
            raise HTTPException(409, detail={"code": "CITATION_REFRESH_IDEMPOTENCY_CONFLICT"})
        return concurrent, False
    db.refresh(row)
    return row, True


def _finish_citation_refresh(
    db: Session,
    row: SinglePromptCitationRefresh,
    *,
    status: str,
    outcome: dict[str, Any],
    failure_code: str = "",
    failure_detail: str = "",
) -> SinglePromptCitationRefresh:
    row.status = status
    row.outcome_json = _canonical_json(outcome)
    row.outcome_hash = _hash(outcome)
    row.failure_code = failure_code
    row.failure_detail = failure_detail[:2000]
    row.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def execute_citation_refresh(
    refresh_id: str,
    *,
    session_factory: Callable[[], Session],
    fetcher: Callable[..., list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    db = session_factory()
    try:
        claimed = db.query(SinglePromptCitationRefresh).filter_by(
            refresh_id=refresh_id, status="PENDING"
        ).update({"status": "RUNNING", "started_at": datetime.utcnow()}, synchronize_session=False)
        db.commit()
        row = db.query(SinglePromptCitationRefresh).filter_by(refresh_id=refresh_id).one_or_none()
        if not row:
            raise HTTPException(404, detail={"code": "CITATION_REFRESH_NOT_FOUND"})
        if claimed != 1:
            return citation_refresh_view(row)
        try:
            _, _, _, _ = _require_refresh_scope(db, row)
        except HTTPException as exc:
            return citation_refresh_view(_finish_citation_refresh(
                db, row, status="BLOCKED", outcome={"request_sent": False},
                failure_code=str((exc.detail or {}).get("code") if isinstance(exc.detail, dict) else "CITATION_REFRESH_SCOPE_CHANGED"),
                failure_detail=str(exc.detail),
            ))
        try:
            results = (fetcher or fetch_page_playwright)([row.canonical_url])
            result = results[0] if len(results) == 1 else {}
        except Exception as exc:
            return citation_refresh_view(_finish_citation_refresh(
                db, row, status="FAILED", outcome={"request_sent": True, "fetch_status": "FETCH_FAILED"},
                failure_code="CITATION_REFRESH_FETCH_FAILED", failure_detail=str(exc),
            ))
        fetch_status = str(result.get("fetch_status") or "FETCH_FAILED").upper()
        text = str(result.get("clean_text") or "").strip()
        receipt = result.get("acquisition_receipt") or {}
        outcome = {
            "request_sent": True,
            "fetch_status": fetch_status,
            "failure_reason": str(result.get("failure_reason") or "")[:2000],
            "acquisition_receipt": receipt,
        }
        if fetch_status != "SUCCESS" or len(text) < 50:
            return citation_refresh_view(_finish_citation_refresh(
                db, row, status="FAILED", outcome=outcome,
                failure_code=(fetch_status if fetch_status != "SUCCESS" else "CONTENT_TOO_SHORT"),
                failure_detail=outcome["failure_reason"] or "刷新未取得合格正文",
            ))
        block_reason = _content_block_reason(str(result.get("title") or ""), text)
        if block_reason:
            return citation_refresh_view(_finish_citation_refresh(
                db, row, status="FAILED", outcome=outcome,
                failure_code="CONTENT_BLOCKED", failure_detail=block_reason,
            ))
        if not receipt:
            return citation_refresh_view(_finish_citation_refresh(
                db, row, status="FAILED", outcome=outcome,
                failure_code="SOURCE_ACQUISITION_RECEIPT_INVALID",
                failure_detail="刷新结果没有真实获取记录",
            ))
        try:
            acquired_at = datetime.fromisoformat(str(receipt.get("acquired_at") or ""))
            _validate_acquisition_receipt(
                receipt, text_hash=_text_hash(text), source_url=row.canonical_url,
                acquired_at=acquired_at, method="AUTO_FETCH",
            )
        except (ValueError, TypeError):
            return citation_refresh_view(_finish_citation_refresh(
                db, row, status="FAILED", outcome=outcome,
                failure_code="SOURCE_ACQUISITION_RECEIPT_INVALID",
                failure_detail="刷新结果缺少与固定 Citation URL 和正文 hash 一致的获取记录",
            ))
        try:
            preparation, disposition, base_snapshot, base_completion = _require_refresh_scope(db, row)
        except HTTPException as exc:
            return citation_refresh_view(_finish_citation_refresh(
                db, row, status="BLOCKED", outcome=outcome,
                failure_code=str((exc.detail or {}).get("code") if isinstance(exc.detail, dict) else "CITATION_REFRESH_SCOPE_CHANGED"),
                failure_detail=str(exc.detail),
            ))
        if _text_hash(text) == base_snapshot.content_hash:
            return citation_refresh_view(_finish_citation_refresh(
                db, row, status="NO_CONTENT_CHANGE", outcome=outcome,
                failure_code="NO_CONTENT_CHANGE",
                failure_detail="真实采集已记录，但正文 hash 未变化，未创建伪造的新正文版本",
            ))
        snapshot = _snapshot_from_content(
            db,
            preparation=preparation,
            disposition=disposition,
            title=str(result.get("title") or ""),
            clean_text=text,
            coverage_scope="FULL_PAGE",
            acquisition_method="AUTO_FETCH",
            submitted_by=f"AUTO_REFRESH:{row.requested_by}",
            acquired_at=acquired_at,
            acquisition_receipt=receipt,
        )
        _refresh_preparation_status(db, preparation)
        db.flush()
        completion = freeze_completion_manifest(
            db,
            preparation_id=row.preparation_id,
            created_by=row.requested_by,
            allow_partial=base_completion.status == "PARTIAL",
        )
        if completion.version_number != row.base_completion_version + 1:
            raise HTTPException(409, detail={"code": "CITATION_REFRESH_MANIFEST_VERSION_MISMATCH"})
        row = db.query(SinglePromptCitationRefresh).filter_by(refresh_id=refresh_id).one()
        row.result_snapshot_id = snapshot.snapshot_id
        row.result_completion_manifest_id = completion.manifest_id
        row.result_completion_manifest_hash = completion.payload_hash
        outcome.update({
            "result_snapshot_id": snapshot.snapshot_id,
            "result_snapshot_hash": snapshot.content_hash,
            "result_completion_manifest_id": completion.manifest_id,
            "result_completion_manifest_hash": completion.payload_hash,
            "result_completion_version": completion.version_number,
        })
        return citation_refresh_view(_finish_citation_refresh(db, row, status="SUCCEEDED", outcome=outcome))
    finally:
        db.close()


def get_citation_refresh(db: Session, *, refresh_id: str, project_id: int, prompt_id: int) -> dict[str, Any]:
    row = db.query(SinglePromptCitationRefresh).filter_by(
        refresh_id=refresh_id, project_id=project_id, prompt_id=prompt_id
    ).one_or_none()
    if not row:
        raise HTTPException(404, detail={"code": "CITATION_REFRESH_NOT_FOUND"})
    return citation_refresh_view(row)


def submit_manual_content(
    db: Session,
    *,
    preparation_id: str,
    source_key: str,
    expected_row_version: int,
    title: str,
    clean_text: str,
    input_format: str = "CLEAN_TEXT",
    raw_html: str = "",
    coverage_scope: str,
    submitted_by: str,
) -> SinglePromptPreparedSourceSnapshot:
    if coverage_scope not in {"FULL_PAGE", "EXCERPT"}:
        raise HTTPException(status_code=422, detail="coverage_scope 只能是 FULL_PAGE 或 EXCERPT")
    if not submitted_by.strip():
        raise HTTPException(status_code=422, detail="必须记录正文提交人")
    disposition = (
        db.query(SinglePromptSourceDisposition)
        .filter_by(preparation_id=preparation_id, source_key=source_key)
        .one_or_none()
    )
    if not disposition:
        raise HTTPException(status_code=404, detail="固定引用范围中不存在该来源")
    if disposition.row_version != expected_row_version:
        raise HTTPException(status_code=409, detail="来源处置版本已变化，请刷新后重试")
    preparation = db.query(SinglePromptSourcePreparation).filter_by(preparation_id=preparation_id).one()
    if preparation.status in ACTIVE_AUTO_FETCH_STATUSES:
        raise HTTPException(status_code=409, detail="自动获取正在排队或执行，请等待完成后再人工补录")
    if input_format == "CLEAN_TEXT":
        if raw_html.strip():
            raise HTTPException(status_code=422, detail="粘贴正文模式不能同时提交页面源码")
        text = clean_text.strip()
        acquisition_method = "MANUAL"
    elif input_format == "HTML_SOURCE":
        if clean_text.strip():
            raise HTTPException(status_code=422, detail="粘贴页面源码模式不能同时提交清洗正文")
        html = raw_html.strip()
        if len(html) < 50:
            raise HTTPException(status_code=422, detail="页面源码过短，无法提取正文")
        extraction = extract_from_html(html, disposition.canonical_url)
        extraction_status = str(extraction.get("extraction_status") or "EMPTY")
        text = str(extraction.get("primary_content") or "").strip()
        if extraction_status not in {"FULL", "PARTIAL", "DESCRIPTION_ONLY"} or len(text) < 50:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "HTML_PRIMARY_CONTENT_REJECTED",
                    "detail": f"页面源码未提取出合格正文（status={extraction_status}）",
                },
            )
        if coverage_scope == "FULL_PAGE" and extraction_status != "FULL":
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "HTML_PRIMARY_CONTENT_PARTIAL",
                    "detail": f"页面源码只提取到部分内容（status={extraction_status}），请选择明确摘录或补充完整正文",
                },
            )
        acquisition_method = "MANUAL_HTML_SOURCE"
    else:
        raise HTTPException(status_code=422, detail="input_format 只能是 CLEAN_TEXT 或 HTML_SOURCE")
    if len(text) < 50:
        raise HTTPException(status_code=422, detail="正文过短，不能形成可审计 passage")
    block_reason = _content_block_reason(title, text)
    if block_reason:
        raise HTTPException(status_code=422, detail={"code": "CONTENT_BLOCKED", "detail": block_reason})
    try:
        snapshot = _snapshot_from_content(
            db,
            preparation=preparation,
            disposition=disposition,
            title=title,
            clean_text=text,
            coverage_scope=coverage_scope,
            acquisition_method=acquisition_method,
            submitted_by=submitted_by.strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _refresh_preparation_status(db, preparation)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def reuse_completed_sources(
    db: Session,
    *,
    preparation_id: str,
    project_id: int,
    prompt_id: int,
    source_completion_manifest_id: str,
    source_completion_manifest_hash: str,
    reused_by: str,
) -> dict[str, Any]:
    """Copy exact immutable source content into a new analysis-owned preparation."""
    preparation = db.query(SinglePromptSourcePreparation).filter_by(preparation_id=preparation_id).one_or_none()
    if not preparation:
        raise HTTPException(status_code=404, detail="来源准备不存在")
    if preparation.project_id != project_id or preparation.prompt_id != prompt_id:
        raise HTTPException(status_code=409, detail="来源准备与当前 Project/Prompt 不匹配")
    if preparation.status in ACTIVE_AUTO_FETCH_STATUSES:
        raise HTTPException(status_code=409, detail="自动获取正在执行，不能同时复用历史正文")
    source_manifest = db.query(SinglePromptSourceCompletionManifest).filter_by(
        manifest_id=source_completion_manifest_id
    ).one_or_none()
    if not source_manifest or source_manifest.payload_hash != source_completion_manifest_hash:
        raise HTTPException(status_code=409, detail="指定 Source Completion Manifest 不存在或 hash 不匹配")
    source_preparation = db.query(SinglePromptSourcePreparation).filter_by(
        preparation_id=source_manifest.preparation_id
    ).one_or_none()
    if (
        not source_preparation
        or source_preparation.project_id != project_id
        or source_preparation.prompt_id != prompt_id
    ):
        raise HTTPException(status_code=409, detail="来源复用禁止跨 Project/Prompt")
    source_payload = loads(source_manifest.payload_json, {})
    source_rows = {
        str(row.get("source_key")): row
        for row in source_payload.get("sources") or []
        if row.get("disposition") == READY_STATE and row.get("snapshot_id")
    }
    dispositions = (
        db.query(SinglePromptSourceDisposition)
        .filter_by(preparation_id=preparation_id)
        .order_by(SinglePromptSourceDisposition.source_key)
        .all()
    )
    reused: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for disposition in dispositions:
        if disposition.state == READY_STATE:
            skipped.append({"source_key": disposition.source_key, "reason": "ALREADY_READY"})
            continue
        source_row = source_rows.get(disposition.source_key)
        if not source_row:
            skipped.append({"source_key": disposition.source_key, "reason": "NOT_READY_IN_SOURCE_MANIFEST"})
            continue
        prior = db.query(SinglePromptPreparedSourceSnapshot).filter_by(
            snapshot_id=str(source_row["snapshot_id"])
        ).one_or_none()
        if not prior:
            raise HTTPException(status_code=409, detail=f"复用 Snapshot 不存在：{source_row['snapshot_id']}")
        prior_passages = _verify_snapshot(prior)
        if (
            prior.source_key != disposition.source_key
            or prior.canonical_url != disposition.canonical_url
            or prior.content_hash != source_row.get("content_hash")
            or prior.artifact_hash != source_row.get("artifact_hash")
            or prior.passages_hash != source_row.get("passages_hash")
            or _receipt_binding(prior) != {k: source_row[k] for k in ("acquisition_receipt_hash",) if k in source_row}
            or [row["passage_id"] for row in prior_passages] != list(source_row.get("passage_ids") or [])
        ):
            raise HTTPException(status_code=409, detail=f"复用来源身份或正文版本不一致：{disposition.source_key}")
        snapshot = _snapshot_from_content(
            db,
            preparation=preparation,
            disposition=disposition,
            title=prior.title,
            clean_text=prior.clean_text,
            coverage_scope=prior.coverage_scope,
            acquisition_method="EXACT_SNAPSHOT_REUSE",
            submitted_by=reused_by.strip(),
            acquired_at=prior.acquired_at,
            acquisition_receipt=loads(prior.acquisition_receipt_json, {}),
        )
        snapshot.reused_from_snapshot_id = prior.snapshot_id
        if (
            snapshot.content_hash != prior.content_hash
            or snapshot.artifact_hash != prior.artifact_hash
            or snapshot.passages_hash != prior.passages_hash
        ):
            raise HTTPException(status_code=409, detail=f"复用后正文 hash 不守恒：{disposition.source_key}")
        reused.append({
            "source_key": disposition.source_key,
            "snapshot_id": snapshot.snapshot_id,
            "reused_from_snapshot_id": prior.snapshot_id,
            "content_hash": snapshot.content_hash,
            "passages_hash": snapshot.passages_hash,
        })
    _refresh_preparation_status(db, preparation)
    db.commit()
    return {
        "preparation_id": preparation_id,
        "source_completion_manifest_id": source_completion_manifest_id,
        "source_completion_manifest_hash": source_completion_manifest_hash,
        "reused": reused,
        "skipped": skipped,
    }


def waive_source(
    db: Session,
    *,
    preparation_id: str,
    source_key: str,
    expected_row_version: int,
    reason: str,
    impact: str,
    waived_by: str,
) -> None:
    if not reason.strip() or not impact.strip() or not waived_by.strip():
        raise HTTPException(status_code=422, detail="人工放弃必须记录原因、影响和操作者")
    disposition = (
        db.query(SinglePromptSourceDisposition)
        .filter_by(preparation_id=preparation_id, source_key=source_key)
        .one_or_none()
    )
    if not disposition:
        raise HTTPException(status_code=404, detail="固定引用范围中不存在该来源")
    if disposition.row_version != expected_row_version:
        raise HTTPException(status_code=409, detail="来源处置版本已变化，请刷新后重试")
    preparation = db.query(SinglePromptSourcePreparation).filter_by(preparation_id=preparation_id).one()
    if preparation.status in ACTIVE_AUTO_FETCH_STATUSES:
        raise HTTPException(status_code=409, detail="自动获取正在排队或执行，请等待完成后再记录人工放弃")
    disposition.state = WAIVED_STATE
    disposition.active_snapshot_id = None
    disposition.waiver_reason = reason.strip()
    disposition.waiver_impact = impact.strip()
    disposition.waived_by = waived_by.strip()
    disposition.waived_at = datetime.utcnow()
    disposition.row_version += 1
    _refresh_preparation_status(db, preparation)
    db.commit()


def recover_interrupted_source_preparations(db: Session) -> int:
    interrupted = (
        db.query(SinglePromptSourcePreparation)
        .filter_by(status=AUTO_FETCHING_STATUS)
        .all()
    )
    for preparation in interrupted:
        rows = (
            db.query(SinglePromptSourceDisposition)
            .filter_by(preparation_id=preparation.preparation_id, state=AUTO_FETCHING_STATE)
            .all()
        )
        for row in rows:
            row.state = MANUAL_REQUIRED_STATE
            row.failure_code = "AUTO_FETCH_INTERRUPTED"
            row.failure_detail = "服务在自动获取正文期间重启；未确认抓取完成，需人工补录或明确再次自动获取"
            row.row_version += 1
        _refresh_preparation_status(db, preparation)
    settled_with_stale_summary = (
        db.query(SinglePromptSourcePreparation)
        .filter_by(status=AUTO_FETCH_PENDING_STATUS)
        .all()
    )
    reconciled = 0
    for preparation in settled_with_stale_summary:
        states = [
            row[0]
            for row in db.query(SinglePromptSourceDisposition.state)
            .filter_by(preparation_id=preparation.preparation_id)
            .all()
        ]
        if states and not any(state in {"PENDING", AUTO_FETCH_QUEUED_STATE, AUTO_FETCHING_STATE} for state in states):
            _refresh_preparation_status(db, preparation)
            reconciled += 1
    if interrupted or reconciled:
        db.commit()
    return len(interrupted) + reconciled


def _verify_snapshot(snapshot: SinglePromptPreparedSourceSnapshot) -> list[dict[str, Any]]:
    path = Path(snapshot.artifact_path)
    if not path.is_file():
        raise HTTPException(status_code=409, detail=f"正文文件缺失：{snapshot.snapshot_id}")
    artifact = path.read_text(encoding="utf-8")
    if _text_hash(artifact) != snapshot.artifact_hash or snapshot.artifact_hash != snapshot.content_hash:
        raise HTTPException(status_code=409, detail=f"正文文件 hash 不匹配：{snapshot.snapshot_id}")
    if artifact != snapshot.clean_text:
        raise HTTPException(status_code=409, detail=f"正文文件与快照内容不一致：{snapshot.snapshot_id}")
    try:
        receipt = json.loads(snapshot.acquisition_receipt_json or '{}')
        _validate_acquisition_receipt(receipt, text_hash=snapshot.content_hash, source_url=snapshot.canonical_url,
                                      acquired_at=snapshot.acquired_at, method=snapshot.acquisition_method)
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, detail=f"获取来源记录与快照不一致：{snapshot.snapshot_id}") from exc
    passages = loads(snapshot.passages_json, [])
    if not passages or _hash(passages) != snapshot.passages_hash:
        raise HTTPException(status_code=409, detail=f"passage hash 不匹配：{snapshot.snapshot_id}")
    return passages


def _receipt_binding(snapshot: SinglePromptPreparedSourceSnapshot) -> dict:
    receipt = loads(snapshot.acquisition_receipt_json, {})
    return {"acquisition_receipt_hash": _hash(receipt)} if receipt else {}


def freeze_completion_manifest(
    db: Session,
    *,
    preparation_id: str,
    created_by: str,
    allow_partial: bool = False,
) -> SinglePromptSourceCompletionManifest:
    preparation = db.query(SinglePromptSourcePreparation).filter_by(preparation_id=preparation_id).one_or_none()
    if not preparation:
        raise HTTPException(status_code=404, detail="来源准备不存在")
    citation = db.query(SinglePromptCitationManifest).filter_by(manifest_id=preparation.citation_manifest_id).one()
    if citation.payload_hash != preparation.citation_manifest_hash:
        raise HTTPException(status_code=409, detail="来源准备绑定的 Citation Manifest hash 不一致")
    dispositions = (
        db.query(SinglePromptSourceDisposition)
        .filter_by(preparation_id=preparation_id)
        .order_by(SinglePromptSourceDisposition.source_key)
        .all()
    )
    nonterminal = [row.source_key for row in dispositions if row.state not in TERMINAL_STATES]
    if nonterminal and not allow_partial:
        raise HTTPException(status_code=409, detail={
            "code": "SOURCE_SCOPE_INCOMPLETE",
            "detail": "仍有引用来源未完成处置",
            "pending_source_keys": nonterminal,
        })
    rows: list[dict[str, Any]] = []
    ready_count = 0
    waived_count = 0
    for disposition in dispositions:
        if disposition.state == READY_STATE:
            snapshot = db.query(SinglePromptPreparedSourceSnapshot).filter_by(
                snapshot_id=disposition.active_snapshot_id
            ).one_or_none()
            if not snapshot:
                raise HTTPException(status_code=409, detail=f"READY 来源缺少指定 Snapshot：{disposition.source_key}")
            if (
                snapshot.preparation_id != preparation_id
                or snapshot.context_id != preparation.context_id
                or snapshot.citation_manifest_id != citation.manifest_id
                or snapshot.source_key != disposition.source_key
            ):
                raise HTTPException(status_code=409, detail=f"Snapshot 归属不一致：{snapshot.snapshot_id}")
            passages = _verify_snapshot(snapshot)
            rows.append({
                "source_key": disposition.source_key,
                "disposition": READY_STATE,
                "snapshot_id": snapshot.snapshot_id,
                "content_hash": snapshot.content_hash,
                "artifact_hash": snapshot.artifact_hash,
                "passages_hash": snapshot.passages_hash,
                "passage_ids": [row["passage_id"] for row in passages],
                "coverage_scope": snapshot.coverage_scope,
                **_receipt_binding(snapshot),
            })
            ready_count += 1
        elif disposition.state == WAIVED_STATE:
            if not disposition.waiver_reason or not disposition.waiver_impact or not disposition.waived_by:
                raise HTTPException(status_code=409, detail=f"WAIVED 来源缺少完整人工处置：{disposition.source_key}")
            rows.append({
                "source_key": disposition.source_key,
                "disposition": WAIVED_STATE,
                "waiver_reason": disposition.waiver_reason,
                "waiver_impact": disposition.waiver_impact,
                "waived_by": disposition.waived_by,
                "waived_at": disposition.waived_at.isoformat() if disposition.waived_at else None,
            })
            waived_count += 1
        else:
            if disposition.state not in {"PENDING", MANUAL_REQUIRED_STATE, AUTO_FETCH_PENDING_STATUS}:
                raise HTTPException(409, detail="正文正在获取或状态非法，不能冻结来源输入")
            rows.append({
                "source_key": disposition.source_key,
                "disposition": disposition.state,
                "limitation": "SOURCE_NOT_CONSUMABLE_NOT_NEGATIVE_EVIDENCE",
            })
    if len(rows) != citation.source_count:
        raise HTTPException(status_code=409, detail="来源处置数量不守恒")
    prior = db.query(SinglePromptSourceCompletionManifest).filter_by(preparation_id=preparation_id).all()
    version = max((row.version_number for row in prior), default=0) + 1
    status = "PARTIAL" if nonterminal else ("FROZEN" if ready_count else "NO_USABLE_SOURCE")
    payload = {
        "contract_version": SOURCE_PREPARATION_CONTRACT_VERSION,
        "analysis_id": preparation.analysis_id,
        "context_id": preparation.context_id,
        "citation_manifest_id": citation.manifest_id,
        "citation_manifest_hash": citation.payload_hash,
        "version_number": version,
        "status": status,
        "sources": rows,
        "required_source_count": len(rows),
        "ready_source_count": ready_count,
        "waived_source_count": waived_count,
    }
    payload_hash = _hash(payload)
    # Version numbers must not make an otherwise identical freeze non-idempotent.
    comparable = {key: value for key, value in payload.items() if key != "version_number"}
    for existing in prior:
        previous = loads(existing.payload_json, {})
        if _hash(previous) != existing.payload_hash:
            raise HTTPException(409, detail="历史正文清单 hash 不匹配")
        if {key: value for key, value in previous.items() if key != "version_number"} == comparable:
            return existing
    manifest = SinglePromptSourceCompletionManifest(
        manifest_id=f"source-completion-{uuid4()}",
        preparation_id=preparation_id,
        analysis_id=preparation.analysis_id,
        context_id=preparation.context_id,
        citation_manifest_id=citation.manifest_id,
        citation_manifest_hash=citation.payload_hash,
        version_number=version,
        status=status,
        payload_json=_canonical_json(payload),
        payload_hash=payload_hash,
        required_source_count=len(rows),
        ready_source_count=ready_count,
        waived_source_count=waived_count,
        created_by=created_by.strip(),
    )
    db.add(manifest)
    db.flush()
    preparation.current_completion_manifest_id = manifest.manifest_id
    preparation.status = MANUAL_REQUIRED_STATUS if nonterminal else status
    db.commit()
    db.refresh(manifest)
    return manifest


def get_source_preparation_status(db: Session, *, preparation_id: str) -> dict[str, Any]:
    preparation = db.query(SinglePromptSourcePreparation).filter_by(preparation_id=preparation_id).one_or_none()
    if not preparation:
        raise HTTPException(status_code=404, detail="来源准备不存在")
    citation = db.query(SinglePromptCitationManifest).filter_by(manifest_id=preparation.citation_manifest_id).one()
    dispositions = (
        db.query(SinglePromptSourceDisposition)
        .filter_by(preparation_id=preparation_id)
        .order_by(SinglePromptSourceDisposition.source_key)
        .all()
    )
    counts: dict[str, int] = {}
    sources = []
    for row in dispositions:
        counts[row.state] = counts.get(row.state, 0) + 1
        snapshot = None
        if row.active_snapshot_id:
            snapshot_row = db.query(SinglePromptPreparedSourceSnapshot).filter_by(snapshot_id=row.active_snapshot_id).one_or_none()
            if snapshot_row:
                snapshot = {
                    "snapshot_id": snapshot_row.snapshot_id,
                    "title": snapshot_row.title,
                    "content_hash": snapshot_row.content_hash,
                    "artifact_hash": snapshot_row.artifact_hash,
                    "artifact_path": snapshot_row.artifact_path,
                    "passages_hash": snapshot_row.passages_hash,
                    "passage_count": len(loads(snapshot_row.passages_json, [])),
                    "coverage_scope": snapshot_row.coverage_scope,
                    "acquisition_method": snapshot_row.acquisition_method,
                    "acquisition_receipt": loads(snapshot_row.acquisition_receipt_json, {}),
                    "acquired_at": snapshot_row.acquired_at.isoformat(),
                    "submitted_by": snapshot_row.submitted_by,
                    "created_at": snapshot_row.created_at.isoformat(),
                }
        sources.append({
            "source_key": row.source_key,
            "canonical_url": row.canonical_url,
            "original_urls": loads(row.original_urls_json, []),
            "reference_observations": loads(row.reference_observations_json, []),
            "occurrence_count": row.occurrence_count,
            "state": row.state,
            "row_version": row.row_version,
            "failure": {"code": row.failure_code, "detail": row.failure_detail} if row.failure_code else None,
            "waiver": {
                "reason": row.waiver_reason,
                "impact": row.waiver_impact,
                "waived_by": row.waived_by,
                "waived_at": row.waived_at.isoformat() if row.waived_at else None,
            } if row.state == WAIVED_STATE else None,
            "snapshot": snapshot,
        })
    completion = None
    if preparation.current_completion_manifest_id:
        row = db.query(SinglePromptSourceCompletionManifest).filter_by(
            manifest_id=preparation.current_completion_manifest_id
        ).one_or_none()
        if row:
            completion = {
                "manifest_id": row.manifest_id,
                "version_number": row.version_number,
                "status": row.status,
                "payload_hash": row.payload_hash,
                "required_source_count": row.required_source_count,
                "ready_source_count": row.ready_source_count,
                "waived_source_count": row.waived_source_count,
                "created_at": row.created_at.isoformat(),
            }
    terminal_count = sum(counts.get(state, 0) for state in TERMINAL_STATES)
    if preparation.status in {"FROZEN", "NO_USABLE_SOURCE"}:
        allowed_operations = ["VIEW"]
    else:
        allowed_operations = [
            *(
                ["QUEUE_AUTO_FETCH"]
                if citation.source_count
                and preparation.status not in ACTIVE_AUTO_FETCH_STATUSES
                and terminal_count < citation.source_count
                else []
            ),
            *(
                ["SUBMIT_MANUAL_CONTENT", "WAIVE_SOURCE"]
                if citation.source_count and preparation.status not in ACTIVE_AUTO_FETCH_STATUSES
                else []
            ),
            *(["FREEZE_COMPLETION"] if terminal_count == citation.source_count else []),
        ]
    return {
        "preparation": {
            "preparation_id": preparation.preparation_id,
            "analysis_id": preparation.analysis_id,
            "context_id": preparation.context_id,
            "project_id": preparation.project_id,
            "prompt_id": preparation.prompt_id,
            "status": preparation.status,
            "created_by": preparation.created_by,
        },
        "citation_manifest": {
            "manifest_id": citation.manifest_id,
            "version_number": citation.version_number,
            "payload_hash": citation.payload_hash,
            "raw_output_hash": citation.raw_output_hash,
            "source_count": citation.source_count,
            "occurrence_count": citation.occurrence_count,
        },
        "conservation": {
            "required_unique_sources": citation.source_count,
            "terminal": terminal_count,
            "nonterminal": citation.source_count - terminal_count,
            "by_state": counts,
            "conserved": sum(counts.values()) == citation.source_count,
        },
        "sources": sources,
        "completion_manifest": completion,
        "allowed_operations": allowed_operations,
    }


def get_source_preparation_for_analysis(
    db: Session,
    *,
    analysis_id: str,
    project_id: int,
    prompt_id: int,
) -> dict[str, Any] | None:
    _analysis_context(db, analysis_id=analysis_id, project_id=project_id, prompt_id=prompt_id)
    preparation = db.query(SinglePromptSourcePreparation).filter_by(analysis_id=analysis_id).one_or_none()
    return get_source_preparation_status(db, preparation_id=preparation.preparation_id) if preparation else None


def validate_completion_for_evidence(
    db: Session,
    *,
    analysis_id: str,
    context_id: str,
    citation_manifest_id: str,
    citation_manifest_hash: str,
    completion_manifest_id: str,
    completion_manifest_hash: str,
    allow_partial: bool = False,
) -> tuple[SinglePromptSourceCompletionManifest, list[SinglePromptPreparedSourceSnapshot], list[dict[str, Any]]]:
    citation = db.query(SinglePromptCitationManifest).filter_by(manifest_id=citation_manifest_id).one_or_none()
    if not citation:
        raise HTTPException(status_code=409, detail={"code": "CITATION_MANIFEST_NOT_FOUND"})
    if (
        citation.analysis_id != analysis_id
        or citation.context_id != context_id
        or citation.payload_hash != citation_manifest_hash
    ):
        raise HTTPException(status_code=409, detail={"code": "CITATION_MANIFEST_INPUT_MISMATCH"})
    completion = db.query(SinglePromptSourceCompletionManifest).filter_by(
        manifest_id=completion_manifest_id
    ).one_or_none()
    if not completion:
        raise HTTPException(status_code=409, detail={"code": "SOURCE_COMPLETION_MANIFEST_NOT_FOUND"})
    if (
        completion.analysis_id != analysis_id
        or completion.context_id != context_id
        or completion.citation_manifest_id != citation_manifest_id
        or completion.citation_manifest_hash != citation_manifest_hash
        or completion.payload_hash != completion_manifest_hash
    ):
        raise HTTPException(status_code=409, detail={"code": "SOURCE_COMPLETION_INPUT_MISMATCH"})
    payload = loads(completion.payload_json, {})
    citation_payload = loads(citation.payload_json, {})
    if _hash(payload) != completion.payload_hash or _hash(citation_payload) != citation.payload_hash:
        raise HTTPException(409, detail={"code": "SOURCE_MANIFEST_CONTENT_HASH_MISMATCH"})
    if payload.get("status") != completion.status:
        raise HTTPException(409, detail={"code": "SOURCE_COMPLETION_STATUS_MISMATCH"})
    rows = payload.get("sources") or []
    if (completion.status not in {"FROZEN", "PARTIAL", "NO_USABLE_SOURCE"}
            or (completion.status == "PARTIAL" and not allow_partial)
            or sum(row.get("disposition") == READY_STATE for row in rows) != completion.ready_source_count
            or sum(row.get("disposition") == WAIVED_STATE for row in rows) != completion.waived_source_count):
        raise HTTPException(409, detail={"code": "SOURCE_COMPLETION_STATE_MISMATCH"})
    expected_keys = {row['source_key'] for row in citation_payload.get('sources') or []}
    if (len(rows) != citation.source_count or completion.required_source_count != citation.source_count
            or {row.get('source_key') for row in rows} != expected_keys or len(expected_keys) != len(rows)):
        raise HTTPException(status_code=409, detail={"code": "SOURCE_COMPLETION_SCOPE_MISMATCH"})
    snapshots: list[SinglePromptPreparedSourceSnapshot] = []
    limitations: list[dict[str, Any]] = []
    for row in rows:
        disposition = row.get("disposition")
        if disposition == READY_STATE:
            snapshot = db.query(SinglePromptPreparedSourceSnapshot).filter_by(
                snapshot_id=row.get("snapshot_id")
            ).one_or_none()
            if not snapshot:
                raise HTTPException(status_code=409, detail={"code": "SOURCE_SNAPSHOT_NOT_FOUND", "source_key": row.get("source_key")})
            if (
                snapshot.context_id != context_id
                or snapshot.preparation_id != completion.preparation_id
                or snapshot.citation_manifest_id != citation_manifest_id
                or snapshot.source_key != row.get("source_key")
                or snapshot.content_hash != row.get("content_hash")
                or snapshot.artifact_hash != row.get("artifact_hash")
                or snapshot.passages_hash != row.get("passages_hash")
                or _receipt_binding(snapshot) != {k: row[k] for k in ("acquisition_receipt_hash",) if k in row}
            ):
                raise HTTPException(status_code=409, detail={"code": "SOURCE_SNAPSHOT_BINDING_MISMATCH", "snapshot_id": snapshot.snapshot_id})
            _verify_snapshot(snapshot)
            snapshots.append(snapshot)
        elif disposition == WAIVED_STATE:
            if not row.get("waiver_reason") or not row.get("waiver_impact") or not row.get("waived_by"):
                raise HTTPException(409, detail={"code": "SOURCE_WAIVER_INCOMPLETE"})
            limitations.append({
                "code": "SOURCE_WAIVED_WITH_LIMITATION",
                "source_key": row.get("source_key"),
                "reason": row.get("waiver_reason"),
                "impact": row.get("waiver_impact"),
            })
        elif allow_partial and completion.status == "PARTIAL" and disposition in {"PENDING", MANUAL_REQUIRED_STATE, AUTO_FETCH_PENDING_STATUS}:
            limitations.append({"code": "SOURCE_NOT_CONSUMABLE", "source_key": row.get("source_key"),
                "disposition": disposition, "negative_evidence": False})
        else:
            raise HTTPException(status_code=409, detail={"code": "SOURCE_COMPLETION_NONTERMINAL_ENTRY", "source_key": row.get("source_key")})
    if not allow_partial and (completion.status == "NO_USABLE_SOURCE" or not snapshots):
        raise HTTPException(status_code=409, detail={
            "code": "NO_USABLE_SOURCE",
            "detail": "来源处置已关闭，但没有可供 Evidence 消费的正文快照",
            "limitations": limitations,
        })
    return completion, snapshots, limitations
