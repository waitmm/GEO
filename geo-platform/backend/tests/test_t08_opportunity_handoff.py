from __future__ import annotations

from release_test_client import TestClient

from app.api.release_catalog import _record_project_configuration
from app.core.release_database import get_release_db
from app.models import (
    BrowserMonitorRun,
    Project,
    Prompt,
    SinglePromptAnalysis,
    SinglePromptAnalysisContext,
    SinglePromptOptimizationTask,
)
from app.modules.single_prompt_v2.observation import opportunity_hint
from app.release_main import create_release_app
from app.services.serialization import loads
from test_release_first_slice import _migrated_session, _seed_frozen_analysis


def _metric(*, evaluable: int, hits: int = 0) -> dict:
    return {
        "evaluable_count": evaluable,
        "hit_count": hits,
        "evaluable_run_ids": list(range(1, evaluable + 1)),
    }


def test_concept_and_instruction_zero_recommendation_are_not_high_opportunities():
    metrics = {
        "brand_mention_rate": _metric(evaluable=2),
        "brand_option_rate": _metric(evaluable=2),
        "brand_recommendation_rate": _metric(evaluable=2),
    }

    for intent in ("category_awareness", "usage_instruction"):
        hint = opportunity_hint(intent, metrics)
        assert hint["state"] == "OBSERVE"
        assert hint["score"] is None
        assert "RECOMMENDATION_NOT_TARGET_OBJECTIVE" in hint["opportunity_reason_codes"]
        assert hint["evaluated_run_ids"] == [1, 2]
        assert "主动分析入口始终保留" in hint["limitation"]

    recommendation = opportunity_hint("supplier_recommendation", metrics)
    assert recommendation["state"] == "INVESTIGATE"
    assert recommendation["opportunity_reason_codes"] == ["TARGET_NOT_OBSERVED_AS_OPTION"]


def test_monitor_handoff_freezes_full_identity_and_only_creates_one_analysis(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        original = _seed_frozen_analysis(db, reference_urls=[])
        app = create_release_app(validate_on_startup=False)
        app.dependency_overrides[get_release_db] = lambda: db
        uri = "/api/v2/projects/1/prompts/44"

        with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50008)) as client:
            first = client.get(uri + "/monitor")
            assert first.status_code == 200, first.text
            stale_selection = first.json()["analysis_selection"]

            project = db.get(Project, 1)
            project.region = "EU"
            _record_project_configuration(db, project)
            db.commit()
            current = client.get(uri + "/monitor").json()["analysis_selection"]
            # Existing Runs retain their observation-time project configuration.
            # A later mutable project edit must not silently rebind or invalidate
            # the already displayed frozen Run selection.
            assert current["scope_hash"] == stale_selection["scope_hash"]
            assert current["project_configuration"] == stale_selection["project_configuration"]
            assert current["project_configuration"]["brand"]["region"] != "EU"

            prompt = db.get(Prompt, 44)
            prompt.prompt_group = "changed-after-display"
            db.commit()
            assert client.post(uri + "/monitor-analysis", json={"scope_hash": current["scope_hash"]}).status_code == 409
            prompt.prompt_group = ""
            db.commit()

            selected = client.get(uri + "/monitor").json()["analysis_selection"]
            analysis_count = db.query(SinglePromptAnalysis).count()
            run_count = db.query(BrowserMonitorRun).count()
            optimize_count = db.query(SinglePromptOptimizationTask).count()

            created = client.post(uri + "/monitor-analysis", json={"scope_hash": selected["scope_hash"]})
            assert created.status_code == 201, created.text
            repeated = client.post(uri + "/monitor-analysis", json={"scope_hash": selected["scope_hash"]})
            assert repeated.status_code == 200
            assert repeated.json()["analysis"]["analysis_id"] == created.json()["analysis"]["analysis_id"]

        assert db.query(SinglePromptAnalysis).count() == analysis_count + 1
        assert db.query(BrowserMonitorRun).count() == run_count
        assert db.query(SinglePromptOptimizationTask).count() == optimize_count

        analysis_id = created.json()["analysis"]["analysis_id"]
        analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=analysis_id).one()
        context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis_id).one()
        plan = loads(analysis.sampling_plan_json, {})
        run_scope = loads(context.run_scope_json, {})
        raw = loads(context.raw_output_json, {})

        assert analysis.task_id is None and analysis.analysis_id != original.analysis_id
        assert plan["project_id"] == selected["project_id"] == 1
        assert plan["prompt_id"] == selected["prompt_id"] == 44
        assert plan["prompt_version"] == selected["prompt_version"]
        assert plan["project_configuration"] == selected["project_configuration"]
        assert plan["origin_monitor_scope"] == selected
        assert plan["run_ids"] == selected["selected_run_ids"]
        assert plan["run_fingerprints"] == selected["run_fingerprints"]
        assert plan["origin_monitor_scope"]["raw_output_hash"] == selected["raw_output_hash"]
        assert plan["origin_monitor_scope"]["scope_hash"] == selected["scope_hash"]
        assert run_scope["run_ids"] == selected["selected_run_ids"]
        assert raw["analysis_id"] == analysis_id and raw["sampling_plan"] == plan
        assert created.json()["context_id"] == context.context_id
        assert created.json()["raw_output_hash"] == context.raw_output_hash
        assert len(context.run_scope_hash) == len(context.raw_output_hash) == 64
    finally:
        db.close()
        engine.dispose()
