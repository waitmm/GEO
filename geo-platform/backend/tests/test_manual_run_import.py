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
from app.modules.single_prompt_v2.service import (
    _run_input_fingerprint,
    _snapshot_run_rows,
    create_analysis_from_runs,
    project_configuration_binding_for_runs,
    prompt_version_binding_for_runs,
)
from app.modules.agent_experiment.evidence_pack import build_evidence_pack
from app.modules.agent_experiment.service import create_agent_run
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


def test_manual_and_source_runs_share_only_the_same_proven_configuration(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        source = _seed_frozen_analysis(db, reference_urls=[])
        source_run = db.query(BrowserMonitorRun).filter_by(task_id=source.task_id).one()
        imported = _client(db).post(
            "/api/v2/projects/1/prompts/44/manual-imports",
            json=_payload(db, idempotency_key="manual-source-compatible"),
        )
        assert imported.status_code == 201, imported.text
        imported_run = db.get(BrowserMonitorRun, imported.json()["run_id"])
        run_ids = [source_run.id, imported_run.id]
        configuration = project_configuration_binding_for_runs(db, run_ids=run_ids)
        assert configuration["binding_status"] == "BOUND"
        assert configuration == json.loads(source.sampling_plan_json)["project_configuration"]
        prompt_version = prompt_version_binding_for_runs(db, run_ids=run_ids)
        snapshots = _snapshot_run_rows(db, [source_run, imported_run])
        analysis, created = create_analysis_from_runs(
            db, project_id=1, prompt_id=44,
            prompt_version_id=prompt_version["prompt_version_id"],
            snapshot_hash=prompt_version["snapshot_hash"], run_ids=run_ids,
            run_fingerprints={int(row["run_id"]): _run_input_fingerprint(row) for row in snapshots},
            base_context_id=None, idempotency_key="manual-source-compatible-analysis",
            project_configuration=configuration,
        )
        assert created is True
        assert json.loads(analysis.sampling_plan_json)["project_configuration"] == configuration
    finally:
        db.close(); engine.dispose()


def test_fresh_project_partial_reference_run_freezes_into_optimize_without_fixed_identity(tmp_path, monkeypatch):
    """A new tenant must not depend on Project 1, Prompt 44, or cached analyses.

    Citation UNKNOWN keeps its uncertainty but does not erase the admitted
    answer when the exact Run is handed from Monitor to Optimize.
    """
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        client = _client(db)
        # Occupy the first identities so this regression cannot accidentally
        # pass by relying on the historical Project 1 / Prompt 44 fixture.
        filler = client.post("/api/projects", json={
            "name": "无关项目", "brand_name": "无关品牌",
        }).json()
        assert client.post(f"/api/projects/{filler['id']}/prompts", json={
            "prompt_text": "这是一条与被测链路无关的问题。",
        }).status_code == 200
        project_response = client.post("/api/projects", json={
            "name": "全新品牌项目",
            "brand_name": "星河工具",
            "brand_aliases": ["星河"],
            "website_url": "https://xinghe.example/",
            "competitors": [{"name": "云端工具", "aliases": ["云端"]}],
        })
        assert project_response.status_code == 200, project_response.text
        project_id = project_response.json()["id"]
        assert project_id != 1

        prompt_response = client.post(f"/api/projects/{project_id}/prompts", json={
            "prompt_text": "如何为团队选择一个可靠的文件协作工具？",
            "intent_type": "product_selection",
        })
        assert prompt_response.status_code == 200, prompt_response.text
        prompt_id = prompt_response.json()["id"]
        assert prompt_id not in {1, 44}

        prompt_version = client.get(
            f"/api/projects/{project_id}/prompts/{prompt_id}/versions"
        ).json()[0]
        project_version = client.get(
            f"/api/projects/{project_id}/configuration-versions"
        ).json()[0]
        imported = client.post(
            f"/api/v2/projects/{project_id}/prompts/{prompt_id}/manual-imports",
            json={
                "prompt_version_id": prompt_version["prompt_version_id"],
                "prompt_snapshot_hash": prompt_version["snapshot_hash"],
                "configuration_version_id": project_version["configuration_version_id"],
                "configuration_snapshot_hash": project_version["snapshot_hash"],
                "observed_at": (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
                "source_platform": "wenxin",
                "source_page_url": "https://yiyan.baidu.com/",
                "answer_text": "这是从真实产品页面人工观察到的完整回答，正文可以用于诊断，但页面引用区域当时无法可靠确认。",
                "citations": [],
                "citation_observation_status": "UNKNOWN",
                "citation_note": "引用区域未稳定显示，不能解释为零引用。",
                "idempotency_key": "fresh-project-import-0001",
            },
        )
        assert imported.status_code == 201, imported.text
        run_id = imported.json()["run_id"]
        assert db.get(BrowserMonitorRun, run_id).status == "partial_success"

        range_base = f"/api/v2/projects/{project_id}/prompts/{prompt_id}/analysis-ranges"
        preview = client.post(range_base + "/preview", json={"mode": "RUN_IDS", "run_ids": [run_id]})
        assert preview.status_code == 200, preview.text
        group = preview.json()["groups"][0]
        assert group["selected_run_ids"] == [run_id]
        frozen = client.post(range_base + "/freeze", json={
            "selector": preview.json()["selector"],
            "preview_hash": preview.json()["preview_hash"],
            "group_hash": group["group_hash"],
            "selected_run_ids": [run_id],
        })
        assert frozen.status_code == 201, frozen.text
        analysis_id = frozen.json()["analysis"]["analysis_id"]
        context_id = frozen.json()["context_id"]

        agent, created = create_agent_run(
            db,
            project_id=project_id,
            prompt_id=prompt_id,
            analysis_id=analysis_id,
            context_id=context_id,
            idempotency_key="fresh-project-optimize-0001",
            requested_by="isolated-test",
            execution_mode="EVIDENCE_PACK",
        )
        assert created is True and agent.status == "QUEUED"
        scope = json.loads(agent.input_scope_json)
        assert scope["identity"]["project_id"] == project_id
        assert scope["identity"]["prompt_id"] == prompt_id
        assert scope["run_scope"]["run_ids"] == [run_id]
        assert scope["runs"][0]["status"] == "partial_success"
        assert scope["runs"][0]["reference_complete"] is False
        assert scope["runs"][0]["references"] == []
        assert scope["runs"][0]["environment"]["manual_observation"]["citation_observation_status"] == "UNKNOWN"
        assert scope["project_entities"]["target_brand"]["brand_name"] == "星河工具"
        assert scope["project_entities"]["competitors"][0]["name"] == "云端工具"
        assert scope["qualification"]["valid_answer_count"] == 1
        assert scope["qualification"]["planned_delivery_level"] == "L3_ACTIONABLE_WITHOUT_FACT_CLAIMS"
        assert scope["qualification"]["evidence_qualification"] == "NOT_EVALUATED"
        pack = build_evidence_pack(scope)
        assert pack["coverage"]["valid_answer_count"] == 1
        assert [member["run_id"] for member in pack["aggregate_evidence_sets"][0]["members"]] == [str(run_id)]
        assert pack["runs"][0]["status"] == "partial_success"
        assert pack["runs"][0]["reference_count"] == 0
        assert pack["runs"][0]["reference_complete"] is False
        assert pack["runs"][0]["collection_method"] == "MANUAL_IMPORT"
        assert pack["runs"][0]["citation_observation_status"] == "UNKNOWN"
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
