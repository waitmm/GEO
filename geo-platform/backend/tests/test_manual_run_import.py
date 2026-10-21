"""Approved MANUAL_IMPORT admission stays identity-safe and zero-call."""

from datetime import datetime, timedelta, timezone
import json

from release_test_client import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.core.release_database import get_release_db
from app.models import (
    BrowserMonitorRun, BrowserMonitorTask, ProjectConfigurationVersion, PromptVersion,
    ReferenceSource, SinglePromptAnalysis, SinglePromptAnalysisContext, SinglePromptManualImport,
)
from app.modules.single_prompt_v2.service import prompt_version_binding_for_runs
from app.release_main import create_release_app
from test_release_first_slice import _migrated_session, _seed_frozen_analysis


def _client(db):
    app = create_release_app(validate_on_startup=False)
    app.dependency_overrides[get_release_db] = lambda: db
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


def _payload(db, **overrides):
    prompt = db.query(PromptVersion).filter_by(project_id=1, prompt_id=44).order_by(PromptVersion.version_number.desc()).first()
    config = db.query(ProjectConfigurationVersion).filter_by(project_id=1).order_by(ProjectConfigurationVersion.version_number.desc()).first()
    values = {
        "prompt_version_id": prompt.prompt_version_id,
        "prompt_snapshot_hash": prompt.snapshot_hash,
        "configuration_version_id": config.configuration_version_id,
        "configuration_snapshot_hash": config.snapshot_hash,
        "observed_at": (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
        "source_platform": "wenxin",
        "source_page_url": "https://yiyan.baidu.com/",
        "answer_text": "这是人工在文心助手页面观察并完整复制的回答正文，长度足够用于严格的本地数据准入测试。",
        "citations": [{"title": "观察到的来源", "url": "https://example.com/source"}],
        "citation_observation_status": "COMPLETE",
        "citation_note": "页面完整展示了一条引用。",
        "idempotency_key": "manual-import-test-0001",
    }
    values.update(overrides)
    return values


def test_valid_manual_import_is_bound_range_selectable_and_zero_analysis(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        source = _seed_frozen_analysis(db, reference_urls=[])
        analyses_before = db.query(SinglePromptAnalysis).count()
        contexts_before = db.query(SinglePromptAnalysisContext).count()
        response = _client(db).post("/api/v2/projects/1/prompts/44/manual-imports", json=_payload(db))
        assert response.status_code == 201, response.text
        result = response.json()
        run = db.get(BrowserMonitorRun, result["run_id"])
        record = db.query(SinglePromptManualImport).filter_by(run_id=run.id).one()
        assert result["sampling_mode"] == "MANUAL_IMPORT"
        assert result["source_assertion_status"] == "USER_ATTESTED_UNVERIFIED"
        assert run.source_type == "manual_observation" and run.adapter == "manual_import"
        assert db.query(ReferenceSource).filter_by(run_id=run.id).count() == 1
        assert db.query(SinglePromptAnalysis).count() == analyses_before
        assert db.query(SinglePromptAnalysisContext).count() == contexts_before
        binding = prompt_version_binding_for_runs(db, run_ids=[run.id])
        assert binding["binding_status"] == "BOUND"
        assert binding["prompt_version_id"] == json.loads(record.identity_json)["prompt_version"]["prompt_version_id"]

        base = "/api/v2/projects/1/prompts/44/analysis-ranges"
        preview = _client(db).post(base + "/preview", json={"mode": "RUN_IDS", "run_ids": [run.id]})
        assert preview.status_code == 200, preview.text
        group = preview.json()["groups"][0]
        assert group["selected_run_ids"] == [run.id]
        assert group["identity"]["source_assertion_status"] == "USER_ATTESTED_UNVERIFIED"
        assert group["identity"]["project_configuration_version_id"]
        frozen = _client(db).post(base + "/freeze", json={
            "selector": preview.json()["selector"], "preview_hash": preview.json()["preview_hash"],
            "group_hash": group["group_hash"], "selected_run_ids": [run.id],
        })
        assert frozen.status_code == 201, frozen.text
        plan = json.loads(db.query(SinglePromptAnalysis).filter_by(
            analysis_id=frozen.json()["analysis"]["analysis_id"]).one().sampling_plan_json)
        assert plan["run_ids"] == [run.id]
        assert plan["prompt_version"]["prompt_version_id"] == binding["prompt_version_id"]
        assert plan["project_configuration"]["configuration_version_id"] == group["identity"]["project_configuration_version_id"]
        assert source.analysis_id != frozen.json()["analysis"]["analysis_id"]
    finally:
        db.close(); engine.dispose()


def test_version_time_scope_citation_and_idempotency_guards(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        _seed_frozen_analysis(db, reference_urls=[])
        client = _client(db)
        prompt = db.query(PromptVersion).filter_by(project_id=1, prompt_id=44).one()
        too_early = (prompt.created_at - timedelta(seconds=1)).replace(tzinfo=timezone.utc).isoformat()
        rejected = client.post("/api/v2/projects/1/prompts/44/manual-imports", json=_payload(db, observed_at=too_early))
        assert rejected.status_code == 409 and rejected.json()["detail"]["code"] == "VERSION_NOT_YET_EFFECTIVE"
        assert db.query(SinglePromptManualImport).count() == 0

        bad_scope = client.post("/api/v2/projects/1/prompts/999/manual-imports", json=_payload(db))
        assert bad_scope.status_code == 404
        unknown = _payload(db, citations=[], citation_observation_status="UNKNOWN",
                           citation_note="页面没有稳定展示引用区域，无法确认是否确实为零引用。")
        created = client.post("/api/v2/projects/1/prompts/44/manual-imports", json=unknown)
        assert created.status_code == 201, created.text
        run = db.get(BrowserMonitorRun, created.json()["run_id"])
        assert run.status == "partial_success" and run.reference_complete is False
        assert run.error_type == "unknown"
        assert db.query(ReferenceSource).filter_by(run_id=run.id).count() == 0
        replay = client.post("/api/v2/projects/1/prompts/44/manual-imports", json=unknown)
        assert replay.status_code == 200 and replay.json()["run_id"] == run.id
        assert db.query(SinglePromptManualImport).count() == 1
        conflict = client.post("/api/v2/projects/1/prompts/44/manual-imports", json={**unknown, "answer_text": unknown["answer_text"] + "不同"})
        assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
        invalid_zero = client.post("/api/v2/projects/1/prompts/44/manual-imports", json={
            **_payload(db), "idempotency_key": "manual-import-invalid-zero", "citation_observation_status": "CONFIRMED_NONE",
        })
        assert invalid_zero.status_code == 422
    finally:
        db.close(); engine.dispose()


def test_manual_import_audit_is_append_only_and_legacy_remains_unbound(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        _seed_frozen_analysis(db, reference_urls=[])
        created = _client(db).post("/api/v2/projects/1/prompts/44/manual-imports", json=_payload(db))
        assert created.status_code == 201
        record = db.query(SinglePromptManualImport).one()
        try:
            db.execute(text("UPDATE single_prompt_manual_imports SET imported_by='tampered' WHERE id=:id"), {"id": record.id})
            db.commit()
            raise AssertionError("append-only trigger did not reject update")
        except DatabaseError:
            db.rollback()

        task = BrowserMonitorTask(project_id=1, platform="wenxin", source_type="legacy", adapter="legacy",
                                  question_ids_json="[44]", run_count=1, schedule_type="manual", status="completed")
        db.add(task); db.flush()
        legacy = BrowserMonitorRun(task_id=task.id, project_id=1, prompt_id=44, status="success", stage="success",
                                   answer_text="这是无法证明历史版本身份的旧回答，因此不能被新入口自动补绑。",
                                   original_query="推荐一个短链工具")
        db.add(legacy); db.commit()
        assert prompt_version_binding_for_runs(db, run_ids=[legacy.id]) == {"binding_status": "LEGACY_UNBOUND"}
        assert db.query(SinglePromptManualImport).count() == 1
    finally:
        db.close(); engine.dispose()
