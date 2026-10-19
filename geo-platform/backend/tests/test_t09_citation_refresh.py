from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from fastapi import Depends, FastAPI
from sqlalchemy.orm import sessionmaker

from app.core.release_access import install_access, require_project_access
from app.models import (
    SinglePromptCitationRefresh,
    SinglePromptPreparedSourceSnapshot,
    SinglePromptSourceCompletionManifest,
    SinglePromptSourceDisposition,
)
from app.modules.optimization.passage_service import _acquisition_receipt
from app.modules.single_prompt_v2 import release_api, source_preparation as sources
from app.modules.single_prompt_v2.release_api import get_db, router
from release_test_client import TestClient
from test_release_first_slice import (
    _configure_artifacts,
    _create_preparation,
    _seed_frozen_analysis,
    _session,
)


URL = "https://example.com/docs"
FIRST_TEXT = "第一版真实公开正文，说明短链接批量创建、统计查看和安全边界。" * 5
SECOND_TEXT = "第二版真实公开正文，补充短链接失效控制、批量创建、统计查看和安全边界。" * 5
FIRST_AT = datetime(2026, 10, 19, 9, 0, 0)


def _receipt(text: str, when: datetime, *, requested_url: str = URL) -> dict:
    result = {
        "url": requested_url,
        "final_url": requested_url,
        "fetch_time": when,
        "fetch_method": "HTTP兜底抓取",
        "network_policy": "PUBLIC_DNS_PINNED_TLS_VERIFIED_V1",
        "fetch_status": "SUCCESS",
        "clean_text": text,
    }
    document = {
        "url": requested_url,
        "status": 200,
        "tls_verified": True,
        "public_address_pinned": True,
        "response_body_hash": sources._hash({"transport": text}),
        "content_type": "text/html; charset=utf-8",
        "last_modified": "",
    }
    return _acquisition_receipt(result, [document])


def _seed_ready(db):
    analysis = _seed_frozen_analysis(db, reference_urls=[URL])
    preparation, _ = _create_preparation(db, analysis)
    disposition = db.query(SinglePromptSourceDisposition).one()
    snapshot = sources._snapshot_from_content(
        db,
        preparation=preparation,
        disposition=disposition,
        title="产品说明",
        clean_text=FIRST_TEXT,
        coverage_scope="FULL_PAGE",
        acquisition_method="AUTO_FETCH",
        submitted_by="seed",
        acquired_at=FIRST_AT,
        acquisition_receipt=_receipt(FIRST_TEXT, FIRST_AT),
    )
    sources._refresh_preparation_status(db, preparation)
    db.commit()
    completion = sources.freeze_completion_manifest(
        db, preparation_id=preparation.preparation_id, created_by="seed"
    )
    return analysis, preparation, disposition, snapshot, completion


def _request(preparation, snapshot, completion, **overrides):
    values = {
        "preparation_id": preparation.preparation_id,
        "analysis_id": preparation.analysis_id,
        "context_id": preparation.context_id,
        "project_id": preparation.project_id,
        "prompt_id": preparation.prompt_id,
        "citation_manifest_id": preparation.citation_manifest_id,
        "citation_manifest_hash": preparation.citation_manifest_hash,
        "source_key": snapshot.source_key,
        "canonical_url": snapshot.canonical_url,
        "base_completion_manifest_id": completion.manifest_id,
        "base_completion_version": completion.version_number,
        "base_completion_manifest_hash": completion.payload_hash,
        "base_snapshot_id": snapshot.snapshot_id,
        "base_snapshot_hash": snapshot.content_hash,
        "idempotency_key": "citation-refresh-0001",
        "requested_by": "authenticated-reviewer",
    }
    values.update(overrides)
    return values


def _fetch_result(text: str, when: datetime, *, requested_url: str = URL) -> dict:
    return {
        "canonical_url": requested_url,
        "fetch_status": "SUCCESS",
        "title": "更新后的产品说明",
        "clean_text": text,
        "fetch_time": when,
        "acquisition_receipt": _receipt(text, when, requested_url=requested_url),
    }


def test_changed_refresh_is_append_only_exact_and_idempotent(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        _, preparation, _, snapshot, completion = _seed_ready(db)
        old_snapshot = (snapshot.snapshot_id, snapshot.clean_text, snapshot.content_hash, snapshot.acquisition_receipt_json)
        old_manifest = (completion.manifest_id, completion.payload_json, completion.payload_hash)
        row, created = sources.request_citation_refresh(db, **_request(preparation, snapshot, completion))
        assert created is True
        calls = []

        def fetcher(urls):
            calls.append(urls)
            return [_fetch_result(SECOND_TEXT, FIRST_AT + timedelta(hours=1))]

        result = sources.execute_citation_refresh(row.refresh_id, session_factory=factory, fetcher=fetcher)
        assert result["status"] == "SUCCEEDED"
        assert calls == [[URL]]
        db.expire_all()
        snapshots = db.query(SinglePromptPreparedSourceSnapshot).order_by(
            SinglePromptPreparedSourceSnapshot.id
        ).all()
        manifests = db.query(SinglePromptSourceCompletionManifest).order_by(
            SinglePromptSourceCompletionManifest.version_number
        ).all()
        assert len(snapshots) == 2
        assert len(manifests) == 2
        assert (snapshots[0].snapshot_id, snapshots[0].clean_text, snapshots[0].content_hash,
                snapshots[0].acquisition_receipt_json) == old_snapshot
        assert (manifests[0].manifest_id, manifests[0].payload_json, manifests[0].payload_hash) == old_manifest
        assert snapshots[1].submitted_by == "AUTO_REFRESH:authenticated-reviewer"
        assert json.loads(snapshots[1].acquisition_receipt_json) == _receipt(
            SECOND_TEXT, FIRST_AT + timedelta(hours=1)
        )
        assert manifests[1].version_number == completion.version_number + 1
        assert manifests[1].payload_hash == result["result_completion_manifest_hash"]
        same, created_again = sources.request_citation_refresh(
            db, **_request(preparation, snapshot, completion)
        )
        assert created_again is False
        assert same.refresh_id == row.refresh_id
        assert sources.execute_citation_refresh(
            row.refresh_id, session_factory=factory, fetcher=lambda _: pytest.fail("duplicate send")
        )["status"] == "SUCCEEDED"
    finally:
        db.close()
        engine.dispose()


def test_unchanged_refresh_preserves_receipt_without_fake_version(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        _, preparation, _, snapshot, completion = _seed_ready(db)
        row, _ = sources.request_citation_refresh(
            db, **_request(preparation, snapshot, completion, idempotency_key="no-content-change")
        )
        result = sources.execute_citation_refresh(
            row.refresh_id,
            session_factory=factory,
            fetcher=lambda urls: [_fetch_result(FIRST_TEXT, FIRST_AT + timedelta(hours=2))],
        )
        assert result["status"] == "NO_CONTENT_CHANGE"
        assert result["failure_code"] == "NO_CONTENT_CHANGE"
        assert result["outcome"]["acquisition_receipt"]["content_hash"] == snapshot.content_hash
        assert db.query(SinglePromptPreparedSourceSnapshot).count() == 1
        assert db.query(SinglePromptSourceCompletionManifest).count() == 1
        db.expire_all()
        assert db.query(SinglePromptCitationRefresh).one().outcome_hash == result["outcome_hash"]
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("field", "value"),
    (("project_id", 2), ("prompt_id", 45), ("analysis_id", "foreign-analysis"),
     ("context_id", "foreign-context"),
     ("citation_manifest_hash", "a" * 64),
     ("canonical_url", "https://www.tencent.com/zh-cn/"),
     ("source_key", "f" * 64),
     ("base_completion_version", 999),
     ("base_completion_manifest_hash", "b" * 64),
     ("base_snapshot_hash", "c" * 64)),
)
def test_plan_rejects_cross_scope_url_and_non_citation_identity(tmp_path, monkeypatch, field, value):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    try:
        _, preparation, _, snapshot, completion = _seed_ready(db)
        with pytest.raises(Exception) as error:
            sources.request_citation_refresh(
                db, **_request(preparation, snapshot, completion, **{field: value})
            )
        assert getattr(error.value, "status_code", None) == 409
        assert db.query(SinglePromptCitationRefresh).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_scope_drift_after_plan_blocks_before_fetch(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        _, preparation, disposition, snapshot, completion = _seed_ready(db)
        row, _ = sources.request_citation_refresh(db, **_request(preparation, snapshot, completion))
        disposition.active_snapshot_id = "drifted-after-preview"
        disposition.row_version += 1
        db.commit()
        result = sources.execute_citation_refresh(
            row.refresh_id, session_factory=factory, fetcher=lambda _: pytest.fail("must not send")
        )
        assert result["status"] == "BLOCKED"
        assert result["outcome"] == {"request_sent": False}
        assert db.query(SinglePromptPreparedSourceSnapshot).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_url_preflight_blocks_and_repeat_does_not_fetch(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        _, preparation, _, snapshot, completion = _seed_ready(db)
        row, _ = sources.request_citation_refresh(db, **_request(preparation, snapshot, completion))
        original_public_url = sources._is_fetchable_public_url
        original_scope = sources._require_refresh_scope

        def verified_scope(*args, **kwargs):
            sources._is_fetchable_public_url = original_public_url
            try:
                return original_scope(*args, **kwargs)
            finally:
                sources._is_fetchable_public_url = lambda _: False

        monkeypatch.setattr(sources, "_require_refresh_scope", verified_scope)
        monkeypatch.setattr(sources, "_is_fetchable_public_url", lambda _: False)
        fetcher = lambda _: pytest.fail("URL preflight must block before fetch")
        result = sources.execute_citation_refresh(row.refresh_id, session_factory=factory, fetcher=fetcher)
        assert result["status"] == "BLOCKED"
        assert result["failure_code"] == "CITATION_REFRESH_URL_NOT_FETCHABLE"
        assert result["outcome"] == {"request_sent": False}
        repeated = sources.execute_citation_refresh(row.refresh_id, session_factory=factory, fetcher=fetcher)
        assert repeated["status"] == "BLOCKED"
        db.expire_all()
        assert db.query(SinglePromptCitationRefresh).one().status == "BLOCKED"
    finally:
        db.close()
        engine.dispose()


def test_freeze_exception_rolls_back_and_repeat_does_not_fetch(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        _, preparation, _, snapshot, completion = _seed_ready(db)
        row, _ = sources.request_citation_refresh(db, **_request(preparation, snapshot, completion))
        calls = []

        def fetcher(urls):
            calls.append(urls)
            return [_fetch_result(SECOND_TEXT, FIRST_AT + timedelta(hours=4))]

        def fail_freeze(*args, **kwargs):
            raise RuntimeError("injected freeze failure")

        monkeypatch.setattr(sources, "freeze_completion_manifest", fail_freeze)
        result = sources.execute_citation_refresh(row.refresh_id, session_factory=factory, fetcher=fetcher)
        assert result["status"] == "BLOCKED"
        assert result["failure_code"] == "CITATION_REFRESH_PERSISTENCE_CONFLICT"
        assert result["outcome"]["request_sent"] is True
        assert result["outcome"]["exception_type"] == "RuntimeError"
        assert calls == [[URL]]
        db.expire_all()
        assert db.query(SinglePromptPreparedSourceSnapshot).count() == 1
        assert db.query(SinglePromptSourceCompletionManifest).count() == 1
        repeated = sources.execute_citation_refresh(
            row.refresh_id, session_factory=factory, fetcher=lambda _: pytest.fail("duplicate send")
        )
        assert repeated["status"] == "BLOCKED"
    finally:
        db.close()
        engine.dispose()


def test_manifest_version_conflict_reports_committed_materialization(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        _, preparation, _, snapshot, completion = _seed_ready(db)
        row, _ = sources.request_citation_refresh(db, **_request(preparation, snapshot, completion))
        original_freeze = sources.freeze_completion_manifest

        def committed_wrong_version(*args, **kwargs):
            committed = original_freeze(*args, **kwargs)
            committed.version_number = 99
            return committed

        monkeypatch.setattr(sources, "freeze_completion_manifest", committed_wrong_version)
        result = sources.execute_citation_refresh(
            row.refresh_id,
            session_factory=factory,
            fetcher=lambda _: [_fetch_result(SECOND_TEXT, FIRST_AT + timedelta(hours=5))],
        )
        assert result["status"] == "BLOCKED"
        assert result["failure_code"] == "CITATION_REFRESH_MANIFEST_VERSION_MISMATCH"
        assert result["outcome"]["materialization_committed"] is True
        assert result["result_snapshot_id"]
        assert result["result_completion_manifest_id"]
        db.expire_all()
        assert db.query(SinglePromptPreparedSourceSnapshot).count() == 2
        assert db.query(SinglePromptSourceCompletionManifest).count() == 2
        repeated = sources.execute_citation_refresh(
            row.refresh_id, session_factory=factory, fetcher=lambda _: pytest.fail("duplicate send")
        )
        assert repeated["status"] == "BLOCKED"
    finally:
        db.close()
        engine.dispose()


def test_http_uses_authenticated_actor_and_persists_mock_refresh(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        _, preparation, _, snapshot, completion = _seed_ready(db)
        monkeypatch.setattr(release_api, "ReleaseSessionLocal", factory)
        monkeypatch.setattr(
            sources,
            "fetch_page_playwright",
            lambda urls: [_fetch_result(SECOND_TEXT, FIRST_AT + timedelta(hours=3))],
        )
        app = FastAPI()
        install_access(app, ["http://127.0.0.1:5173"])
        app.include_router(router, dependencies=[Depends(require_project_access)])
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 8000))
        path = f"/api/v2/single-prompt/source-preparations/{preparation.preparation_id}/citation-refreshes"
        body = _request(preparation, snapshot, completion)
        body.pop("preparation_id")
        body.pop("requested_by")
        forged = client.post(path, json={**body, "requested_by": "forged"})
        assert forged.status_code == 422
        response = client.post(path, json=body)
        assert response.status_code == 202, response.text
        db.expire_all()
        persisted = db.query(SinglePromptCitationRefresh).one()
        assert persisted.requested_by == "local-owner"
        assert persisted.status == "SUCCEEDED"
        read = client.get(
            f"/api/v2/single-prompt/citation-refreshes/{persisted.refresh_id}?project_id=1&prompt_id=44"
        )
        assert read.status_code == 200
        assert read.json()["requested_by"] == "local-owner"
        assert read.json()["result_completion_manifest_id"]
    finally:
        db.close()
        engine.dispose()
