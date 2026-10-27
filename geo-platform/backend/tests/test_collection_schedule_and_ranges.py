"""Collection-only schedules and explicit time-range handoff use no external service."""
from datetime import datetime, timedelta
import json

from release_test_client import TestClient

from app.core.release_database import get_release_db
from app.models import BrowserMonitorRun, BrowserMonitorTask, SinglePromptAnalysis, SinglePromptAnalysisContext
from app.modules.single_prompt_v2.scheduling import create_schedule, executions, queue_immediate, tick
from app.modules.single_prompt_v2.service import prompt_version_binding_for_runs
from app.release_main import create_release_app
from scripts.release_worker import recover_interrupted_collection_tasks
from test_release_first_slice import _migrated_session, _seed_frozen_analysis


def _binding(source):
    return json.loads(source.sampling_plan_json)["prompt_version"]


def _collection_schedule(db, source, now):
    binding = _binding(source)
    return create_schedule(db, project_id=1, prompt_id=44,
        prompt_version_id=binding["prompt_version_id"], snapshot_hash=binding["snapshot_hash"],
        timezone_name="UTC", local_time="09:00", sample_count=2, max_attempts=8,
        authorization_note="isolated test only", collection_only=True, cadence_type="DAILY", now=now)


def test_collection_only_appends_runs_without_analysis_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("GEO_BETA_SCHEDULED_SAMPLING_ENABLED", "1")
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        source = _seed_frozen_analysis(db, reference_urls=[])
        analyses_before = db.query(SinglePromptAnalysis).count()
        contexts_before = db.query(SinglePromptAnalysisContext).count()
        now = datetime(2026, 10, 20)
        schedule = _collection_schedule(db, source, now)
        queued = tick(db, now + timedelta(hours=9))
        assert len(queued) == 1 and queued[0].startswith("collection:")
        task = db.query(BrowserMonitorTask).filter_by(schedule_type="collection_only_schedule").one()
        runs = db.query(BrowserMonitorRun).filter_by(task_id=task.id).order_by(BrowserMonitorRun.id).all()
        assert len(runs) == 2 and all(run.status == "queued" for run in runs)
        assert db.query(SinglePromptAnalysis).count() == analyses_before
        assert db.query(SinglePromptAnalysisContext).count() == contexts_before
        assert tick(db, now + timedelta(hours=9, minutes=1)) == []
        assert db.query(BrowserMonitorTask).filter_by(schedule_type="collection_only_schedule").count() == 1

        for index, run in enumerate(runs):
            run.status = "success"; run.stage = "success"; run.answer_text = f"真实回答 {index}"
            run.finished_at = now + timedelta(hours=9, minutes=2)
            run.reference_complete = True
        task.status = "completed"; db.commit()
        assert prompt_version_binding_for_runs(db, run_ids=[run.id for run in runs]) == _binding(source)
        history = executions(db, schedule)
        assert history[0]["status"] == "SUCCESS" and history[0]["success_count"] == 2
        assert all(run.detected_reference_count == 0 for run in runs)  # 合法零引用，不是失败。
    finally:
        db.close(); engine.dispose()


def test_range_preview_groups_and_freezes_exact_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("GEO_BETA_SCHEDULED_SAMPLING_ENABLED", "1")
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        source = _seed_frozen_analysis(db, reference_urls=[])
        now = datetime(2026, 10, 20)
        schedule = _collection_schedule(db, source, now)
        tick(db, now + timedelta(hours=9))
        task = db.query(BrowserMonitorTask).filter_by(schedule_type="collection_only_schedule").one()
        runs = db.query(BrowserMonitorRun).filter_by(task_id=task.id).order_by(BrowserMonitorRun.id).all()
        runs[0].status = "success"; runs[0].stage = "success"; runs[0].answer_text = "可分析回答"
        runs[0].finished_at = now + timedelta(hours=9)
        runs[1].status = "failed"; runs[1].stage = "failed"; runs[1].error_type = "collector_failed"
        runs[1].finished_at = now + timedelta(hours=9)
        task.status = "partial_success"; db.commit()

        app = create_release_app(validate_on_startup=False)
        app.dependency_overrides[get_release_db] = lambda: db
        client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
        base = "/api/v2/projects/1/prompts/44/analysis-ranges"
        preview = client.post(base + "/preview", json={"mode": "RUN_IDS", "run_ids": [run.id for run in runs]})
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert (body["total_count"], body["valid_count"], body["invalid_count"]) == (2, 1, 1)
        assert len(body["groups"]) == 1
        group = body["groups"][0]
        assert group["selected_run_ids"] == [runs[0].id] and group["excluded_run_ids"] == [runs[1].id]
        frozen = client.post(base + "/freeze", json={"selector": body["selector"],
            "preview_hash": body["preview_hash"], "group_hash": group["group_hash"],
            "selected_run_ids": group["selected_run_ids"]})
        assert frozen.status_code == 201, frozen.text
        analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=frozen.json()["analysis"]["analysis_id"]).one()
        plan = json.loads(analysis.sampling_plan_json)
        assert analysis.task_id is None and plan["run_ids"] == [runs[0].id]
        before = plan["origin_monitor_scope"]
        listed = client.get("/api/v2/single-prompt/analyses?project_id=1&prompt_id=44")
        assert listed.status_code == 200, listed.text
        listed_row = next(item for item in listed.json() if item["analysis"]["analysis_id"] == analysis.analysis_id)
        assert listed_row["origin_monitor_scope"]["selector"] == body["selector"]
        assert listed_row["origin_monitor_scope"]["selected_run_ids"] == [runs[0].id]
        queue_immediate(db, schedule, schedule.revision, "later-run-fixed-scope", now + timedelta(hours=10))
        db.refresh(analysis)
        assert json.loads(analysis.sampling_plan_json)["origin_monitor_scope"] == before
    finally:
        db.close(); engine.dispose()


def test_without_external_authority_plan_is_saved_paused_and_cannot_run(tmp_path, monkeypatch):
    monkeypatch.delenv("GEO_BETA_SCHEDULED_SAMPLING_ENABLED", raising=False)
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        source = _seed_frozen_analysis(db, reference_urls=[])
        row = _collection_schedule(db, source, datetime(2026, 10, 20))
        assert row.status == "PAUSED" and "尚未授权" in row.pause_reason
        assert tick(db, datetime(2026, 10, 21, 9)) == []
        assert db.query(BrowserMonitorTask).filter_by(schedule_type="collection_only_schedule").count() == 0
    finally:
        db.close(); engine.dispose()


def test_missed_slots_are_not_backfilled_and_restart_never_replays_uncertain_call(tmp_path, monkeypatch):
    monkeypatch.setenv("GEO_BETA_SCHEDULED_SAMPLING_ENABLED", "1")
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        source = _seed_frozen_analysis(db, reference_urls=[])
        binding = _binding(source)
        now = datetime(2026, 10, 20)
        row = create_schedule(db, project_id=1, prompt_id=44,
            prompt_version_id=binding["prompt_version_id"], snapshot_hash=binding["snapshot_hash"],
            timezone_name="UTC", local_time="09:00", sample_count=1, max_attempts=8,
            authorization_note="isolated interval test", collection_only=True,
            cadence_type="INTERVAL", interval_hours=6, now=now)
        # Three intervals elapsed while the worker was unavailable. They are audit-only,
        # not three external catch-up calls.
        queued = tick(db, now + timedelta(hours=19))
        assert queued == []
        history = executions(db, row)
        assert [item["status"] for item in history].count("MISSED") == 3
        assert db.query(BrowserMonitorTask).filter_by(schedule_type="collection_only_schedule").count() == 0

        queued = tick(db, now + timedelta(hours=24))
        assert len(queued) == 1
        task = db.query(BrowserMonitorTask).filter_by(schedule_type="collection_only_schedule").one()
        run = db.query(BrowserMonitorRun).filter_by(task_id=task.id).one()
        task.status = "running"; run.status = "running"; run.stage = "running"; db.commit()
        assert recover_interrupted_collection_tasks(db) == 1
        db.refresh(task); db.refresh(run)
        assert task.status == "interrupted"
        assert run.status == "failed" and run.error_type == "worker_restart_delivery_unknown"
        assert db.query(BrowserMonitorTask).filter_by(schedule_type="collection_only_schedule").count() == 1
    finally:
        db.close(); engine.dispose()
