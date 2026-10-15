"""Synthetic scheduled batches exercise the real handoff, never external services."""
from datetime import datetime, timedelta
import json

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models import BrowserMonitorRun, Project, SinglePromptAnalysis, SinglePromptOptimizationTask, SinglePromptSamplingSchedule
from app.modules.single_prompt_v2.scheduling import create_schedule, tick, pause_schedule
from app.modules.single_prompt_v2.service import claim_analysis, finalize_analysis
from test_release_first_slice import _migrated_session, _seed_frozen_analysis


@pytest.fixture
def scene(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    _seed_frozen_analysis(db, reference_urls=[])
    now = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    settings = {'every_batches': 1, 'max_tasks': 1, 'source_fetch_authorized': False,
        'authorization': {'max_requests': 4, 'max_tokens': 300000, 'max_cost_cny': 3,
            'conservative_cny_per_million_tokens': 10, 'pricing_source': 'synthetic-price-not-provider-bill',
            'pricing_checked_at': now.date().isoformat(), 'authorized_by': 'isolated-test'}}
    yield db, engine, now, settings
    db.close(); engine.dispose()


def schedule(db, now, settings):
    source = db.query(SinglePromptAnalysis).filter(SinglePromptAnalysis.task_id.is_not(None)).order_by(
        SinglePromptAnalysis.id
    ).first()
    binding = json.loads(source.sampling_plan_json)['prompt_version']
    return create_schedule(db, project_id=1, prompt_id=44,
        prompt_version_id=binding['prompt_version_id'], snapshot_hash=binding['snapshot_hash'],
        timezone_name='UTC', local_time='09:00',
        sample_count=1, max_attempts=3, authorization_note='synthetic scheduler, no browser', optimization=settings, now=now)


def finish_batch(db, analysis_id):
    analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=analysis_id).one()
    token = claim_analysis(db, analysis_id)
    run = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).one()
    run.status = 'success'; run.stage = 'success'; run.answer_text = '按实际资料核对使用条件。'
    run.reference_complete = True
    db.commit()
    assert finalize_analysis(db, analysis_id, token)


def test_sampling_handoff_reserves_once_survives_reopen_and_never_spends_more(scene):
    db, engine, now, settings = scene
    row = schedule(db, now, settings)
    plan = json.loads(row.plan_json)
    assert plan['optimization']['total_authorization'] == {'max_requests': 4, 'max_tokens': 300000, 'max_cost_cny': 3}
    first = tick(db, now + timedelta(hours=9))[0]
    finish_batch(db, first)
    tick(db, now + timedelta(hours=10))
    task = db.query(SinglePromptOptimizationTask).one()
    frozen = task.input_json
    authority = task.authorization_json
    assert task.analysis_id == first and json.loads(authority)['policy'] == 'ALLOW_EXTERNAL'
    assert json.loads(frozen)['run_ids'] == [2] and json.loads(frozen)['source_fetch_authorized'] is False
    db.close()
    with Session(engine) as reopened:
        tick(reopened, now + timedelta(hours=11))
        restored = reopened.query(SinglePromptOptimizationTask).one()
        assert restored.input_json == frozen and restored.authorization_json == authority
        second = tick(reopened, now + timedelta(days=1, hours=9))[0]
        finish_batch(reopened, second)
        tick(reopened, now + timedelta(days=1, hours=10))
        assert reopened.query(SinglePromptOptimizationTask).count() == 1
        row = reopened.query(SinglePromptSamplingSchedule).one()
        assert json.loads(row.optimization_progress_json)['status'] == 'EXHAUSTED'
        assert row.status == 'ACTIVE'  # Sampling remains independent of Optimize budget.


def test_changed_brand_blocks_only_optimize_not_next_monitor_batch(scene):
    db, _, now, settings = scene
    row = schedule(db, now, settings)
    first = tick(db, now + timedelta(hours=9))[0]
    finish_batch(db, first)
    db.get(Project, 1).brand_name = 'Changed brand'
    db.commit()
    tick(db, now + timedelta(hours=10))
    db.refresh(row)
    assert json.loads(row.optimization_progress_json)['status'] == 'BLOCKED'
    assert db.query(SinglePromptOptimizationTask).count() == 0
    assert len(tick(db, now + timedelta(days=1, hours=9))) == 1
    assert db.query(SinglePromptOptimizationTask).count() == 0


def test_pause_cancels_queued_handoff_without_rewriting_finished_data(scene):
    db, _, now, settings = scene
    row = schedule(db, now, settings)
    first = tick(db, now + timedelta(hours=9))[0]
    finish_batch(db, first)
    tick(db, now + timedelta(hours=10))
    task = db.query(SinglePromptOptimizationTask).one()
    frozen = task.input_json
    db.refresh(row)
    pause_schedule(db, row, row.revision)
    db.refresh(task)
    assert task.status == 'CANCELLED' and task.input_json == frozen
    assert len(json.loads(task.progress_json)['requests']) == 0
    assert tick(db, now + timedelta(days=1, hours=9)) == []


def test_trigger_frequency_and_immutable_plan(scene):
    db, _, now, settings = scene
    settings['every_batches'] = 2
    row = schedule(db, now, settings)
    first = tick(db, now + timedelta(hours=9))[0]
    finish_batch(db, first)
    tick(db, now + timedelta(hours=10))
    assert db.query(SinglePromptOptimizationTask).count() == 0
    second = tick(db, now + timedelta(days=1, hours=9))[0]
    finish_batch(db, second)
    tick(db, now + timedelta(days=1, hours=10))
    assert db.query(SinglePromptOptimizationTask).one().analysis_id == second
    with pytest.raises(Exception, match='SAMPLING_PLAN_IMMUTABLE'):
        db.execute(text("UPDATE single_prompt_sampling_schedules SET plan_json='{}'"))
    db.rollback()


def test_pause_during_authorization_cancels_unrecorded_child(scene, monkeypatch):
    from app.modules.single_prompt_v2 import scheduled_optimization as handoff
    db, _, now, settings = scene
    row = schedule(db, now, settings)
    first = tick(db, now + timedelta(hours=9))[0]
    finish_batch(db, first)
    original = handoff.authorize_task

    def pause_after_authorizing(*args, **kwargs):
        result = original(*args, **kwargs)
        db.refresh(row)
        pause_schedule(db, row, row.revision)
        return result

    monkeypatch.setattr(handoff, 'authorize_task', pause_after_authorizing)
    assert tick(db, now + timedelta(days=1, hours=9)) == []
    db.refresh(row)
    task = db.query(SinglePromptOptimizationTask).one()
    assert row.status == 'PAUSED'
    assert task.status == 'CANCELLED'
    assert json.loads(task.progress_json)['requests'] == []


def test_total_authorization_is_bounded_at_creation(scene):
    db, _, now, settings = scene
    settings['max_tasks'] = 30
    settings['authorization']['max_cost_cny'] = 100
    with pytest.raises(HTTPException, match='整份计划'):
        schedule(db, now, settings)
    assert db.query(SinglePromptSamplingSchedule).count() == 0
