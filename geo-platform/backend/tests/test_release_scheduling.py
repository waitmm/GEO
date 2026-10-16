from datetime import datetime
import json

from fastapi import HTTPException
import pytest

from app.models import BrowserMonitorRun, Prompt, SinglePromptAnalysis, SinglePromptSamplingSchedule
from app.api.release_catalog import _record_prompt_version
from app.modules.single_prompt_v2.scheduling import create_schedule, next_daily, pause_schedule, tick, allow_scheduled_start
from test_release_first_slice import _migrated_session, _seed_frozen_analysis


def _version_kwargs(db):
    source = db.query(SinglePromptAnalysis).filter(SinglePromptAnalysis.task_id.is_not(None)).order_by(
        SinglePromptAnalysis.id
    ).first()
    binding = json.loads(source.sampling_plan_json)['prompt_version']
    return {'prompt_version_id': binding['prompt_version_id'], 'snapshot_hash': binding['snapshot_hash']}


def test_collector_stops_later_samples_after_access_block(tmp_path, monkeypatch):
    from app.modules.monitoring.executor import MonitoringTaskExecutor
    db, engine = _migrated_session(tmp_path, monkeypatch)
    executor = MonitoringTaskExecutor()
    try:
        _seed_frozen_analysis(db, reference_urls=[])
        row = create_schedule(db, project_id=1, prompt_id=44, **_version_kwargs(db), timezone_name='Asia/Shanghai', local_time='09:00',
            sample_count=3, max_attempts=3, authorization_note='offline test only', now=datetime(2026, 10, 9))
        tick(db, datetime(2026, 10, 9, 1))
        analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=row.last_analysis_id).one()
        calls = []
        def blocked_group(db, runs):
            calls.append(runs[0].id)
            runs[0].status, runs[0].error_type = 'blocked', 'captcha_required'
            db.commit()
            return 0
        monkeypatch.setattr(executor, '_execute_run_group', blocked_group)
        assert executor.execute_queued_runs(db, analysis.task_id) == 0
        runs = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).order_by(BrowserMonitorRun.id).all()
        assert len(calls) == 1
        assert [r.status for r in runs] == ['blocked'] * 3
        assert [r.error_type for r in runs[1:]] == ['prior_run_requires_user_recovery'] * 2
        assert all(not r.answer_text for r in runs)
    finally:
        executor.close(); db.close(); engine.dispose()


def test_daily_timezone_dst_does_not_duplicate_or_invent_slot():
    assert next_daily(datetime(2026, 10, 9, 0), 'Asia/Shanghai', '09:00') == datetime(2026, 10, 9, 1)
    assert next_daily(datetime(2026, 3, 8, 0), 'America/New_York', '02:30') == datetime(2026, 3, 9, 6, 30)
    with pytest.raises(HTTPException):
        next_daily(datetime.utcnow(), 'not-a-zone', '09:00')


def test_schedule_rejects_superseded_prompt_version_at_creation(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        _seed_frozen_analysis(db, reference_urls=[])
        v1 = _version_kwargs(db)
        prompt = db.get(Prompt, 44)
        prompt.prompt_group = 'V2 group'
        v2 = _record_prompt_version(db, prompt)
        db.commit()
        arguments = dict(project_id=1, prompt_id=44, timezone_name='Asia/Shanghai', local_time='09:00',
            sample_count=1, max_attempts=1, authorization_note='explicit current-version schedule',
            now=datetime(2026, 10, 9))
        with pytest.raises(HTTPException) as error:
            create_schedule(db, **arguments, **v1)
        assert error.value.status_code == 409
        assert error.value.detail['code'] == 'PROMPT_VERSION_NOT_CURRENT'
        created = create_schedule(db, **arguments,
            prompt_version_id=v2.prompt_version_id, snapshot_hash=v2.snapshot_hash)
        assert json.loads(created.plan_json)['prompt_version']['prompt_version_id'] == v2.prompt_version_id
    finally:
        db.close(); engine.dispose()


def test_schedule_reservation_reopen_pause_and_authorization_bound(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        _seed_frozen_analysis(db, reference_urls=[])
        row = create_schedule(db, project_id=1, prompt_id=44, **_version_kwargs(db), timezone_name='Asia/Shanghai', local_time='09:00',
            sample_count=1, max_attempts=2, authorization_note='isolated scheduler test, never start browser', now=datetime(2026, 10, 9, 0))
        count = db.query(BrowserMonitorRun).count()
        assert tick(db, datetime(2026, 10, 9, 0, 59)) == []
        queued = tick(db, datetime(2026, 10, 9, 1))
        assert len(queued) == 1
        assert db.query(BrowserMonitorRun).count() == count + 1
        assert tick(db, datetime(2026, 10, 9, 1)) == []
        db.close()
        from sqlalchemy.orm import Session
        db = Session(engine)
        row = db.query(SinglePromptSamplingSchedule).one()
        assert row.remaining_attempts == 1
        assert tick(db, datetime(2026, 10, 10, 1)) == []  # no overlapping browser task
        previous = db.query(SinglePromptAnalysis).filter_by(analysis_id=queued[0]).one()
        previous.status = 'FAILED'
        db.commit()
        assert len(tick(db, datetime(2026, 10, 10, 1))) == 1
        db.refresh(row)
        previous = db.query(SinglePromptAnalysis).filter_by(analysis_id=row.last_analysis_id).one()
        previous.status = 'FAILED'; db.commit()
        assert tick(db, datetime(2026, 10, 11, 1)) == []
        db.refresh(row)
        assert row.status == 'EXHAUSTED' and row.remaining_attempts == 0
        second = create_schedule(db, project_id=1, prompt_id=44, **_version_kwargs(db), timezone_name='Asia/Shanghai', local_time='09:00',
            sample_count=1, max_attempts=1, authorization_note='second isolated plan', now=datetime(2026, 10, 12))
        pause_schedule(db, second, second.revision)
        assert tick(db, datetime(2026, 10, 13, 1)) == []
    finally:
        db.close(); engine.dispose()


def test_pause_cancels_only_queued_runs_and_preserves_completed_sample(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        _seed_frozen_analysis(db, reference_urls=[])
        schedule = create_schedule(
            db,
            project_id=1,
            prompt_id=44,
            **_version_kwargs(db),
            timezone_name='Asia/Shanghai',
            local_time='09:00',
            sample_count=3,
            max_attempts=3,
            authorization_note='offline AC-SAM-03 cancellation test',
            now=datetime(2026, 10, 9),
        )
        [analysis_id] = tick(db, datetime(2026, 10, 9, 1))
        analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=analysis_id).one()
        runs = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).order_by(BrowserMonitorRun.id).all()
        runs[0].status, runs[0].stage = 'success', 'success'
        runs[0].answer_text = '已完成样本的原始回答必须保留'
        db.commit()

        pause_schedule(db, schedule, schedule.revision)

        assert allow_scheduled_start(db, analysis) is False
        db.refresh(analysis)
        for run in runs:
            db.refresh(run)
        assert analysis.status == 'CANCELLED'
        assert [run.status for run in runs] == ['success', 'cancelled', 'cancelled']
        assert [run.stage for run in runs] == ['success', 'cancelled', 'cancelled']
        assert runs[0].answer_text == '已完成样本的原始回答必须保留'
    finally:
        db.close(); engine.dispose()


@pytest.mark.parametrize('cause', ['prompt_change', 'captcha_required', 'login_required'])
def test_schedule_stops_when_identity_or_access_changes(tmp_path, monkeypatch, cause):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        _seed_frozen_analysis(db, reference_urls=[])
        row = create_schedule(db, project_id=1, prompt_id=44, **_version_kwargs(db), timezone_name='Asia/Shanghai', local_time='09:00',
            sample_count=1, max_attempts=3, authorization_note='isolated', now=datetime(2026, 10, 9))
        tick(db, datetime(2026, 10, 9, 1))
        if cause == 'prompt_change':
            db.get(Prompt, 44).prompt_text = 'A changed question'
        else:
            analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=row.last_analysis_id).one()
            run = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).one()
            run.status, run.error_type = 'blocked', cause
        db.commit()
        assert tick(db, datetime(2026, 10, 10, 1)) == []
        db.refresh(row)
        assert row.status == 'BLOCKED'
        analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=row.last_analysis_id).one()
        assert not allow_scheduled_start(db, analysis)
        assert analysis.status == 'CANCELLED'
    finally:
        db.close(); engine.dispose()
