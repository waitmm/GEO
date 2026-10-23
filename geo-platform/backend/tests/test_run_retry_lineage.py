from __future__ import annotations

from pathlib import Path
import importlib.util

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base, BrowserMonitorRun, BrowserMonitorRunAttempt, BrowserMonitorTask,
    Project, Prompt, ReferenceSource,
)
from app.modules.single_prompt_v2.service import (
    _selected_run_snapshots,
    list_prompt_run_pool,
    queue_run_retry,
)
from scripts.reconcile_legacy_run_retry import audit_pair, reconcile_pair


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'retry-lineage.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    db.add(Project(id=1, organization_id=1, name="Project", brand_name="Brand"))
    db.add(Prompt(id=11, project_id=1, prompt_text="Question"))
    task = BrowserMonitorTask(
        project_id=1,
        question_ids_json="[11]",
        run_count=1,
        status="failed",
        created_by="test:source",
    )
    db.add(task)
    db.flush()
    source = BrowserMonitorRun(
        task_id=task.id,
        project_id=1,
        prompt_id=11,
        status="failed",
        stage="failed",
        original_query="Question",
        error_type="network_error",
        error_message="kept failure",
    )
    db.add(source)
    db.commit()
    return db, engine, source


def test_retry_updates_one_business_run_and_audits_attempts_idempotently(tmp_path):
    db, engine, source = _db(tmp_path)
    try:
        original_attempt_id = source.attempt_id
        retry, attempt, created = queue_run_retry(
            db,
            run_id=source.id,
            project_id=1,
            prompt_id=11,
            idempotency_key="retry-key-1",
        )
        assert created is True
        assert retry.id == source.id
        assert (retry.logical_run_id, retry.attempt_no, retry.retry_of_run_id) == (
            source.logical_run_id,
            2,
            None,
        )
        assert retry.attempt_id != original_attempt_id
        assert (retry.status, retry.error_message, retry.attempt_no, retry.retry_of_run_id) == (
            "retrying",
            "",
            2,
            None,
        )
        assert attempt.run_id == source.id
        assert attempt.previous_status == "failed"
        assert attempt.previous_error_message == "kept failure"
        assert db.query(BrowserMonitorRun).count() == 1

        duplicate, duplicate_attempt, duplicate_created = queue_run_retry(
            db,
            run_id=source.id,
            project_id=1,
            prompt_id=11,
            idempotency_key="retry-key-1",
        )
        assert duplicate_created is False
        assert duplicate.id == retry.id
        assert duplicate_attempt.id == attempt.id

        retry.status, retry.stage = "failed", "failed"
        retry.error_type, retry.error_message = "network_error", "failed again"
        db.commit()
        third, third_attempt, third_created = queue_run_retry(
            db,
            run_id=retry.id,
            project_id=1,
            prompt_id=11,
            idempotency_key="retry-key-2",
        )
        assert third_created is True
        assert third.id == source.id
        assert (third.logical_run_id, third.attempt_no, third.retry_of_run_id) == (
            source.logical_run_id,
            3,
            None,
        )
        assert third_attempt.previous_error_message == "failed again"
        assert db.query(BrowserMonitorRun).count() == 1
        assert db.query(BrowserMonitorRunAttempt).count() == 2

        pool = list_prompt_run_pool(db, project_id=1, prompt_id=11, page=1, page_size=20)
        assert pool["total"] == pool["logical_sample_total"] == 1
        assert pool["attempt_total"] == 3
        assert len(pool["items"]) == 1
        assert pool["items"][0]["run_id"] == source.id
        assert pool["items"][0]["attempt_no"] == 3
    finally:
        db.close()
        engine.dispose()


def test_rate_limited_business_run_allows_only_explicit_in_place_retry(tmp_path):
    db, engine, source = _db(tmp_path)
    try:
        source.status = "blocked"
        source.stage = "failed"
        source.error_type = "rate_limited"
        source.blocked_type = "rate_limited"
        source.blocked_reason = "今日提问次数已用完；恢复操作：确认配额恢复后人工重试。"
        db.commit()

        retry, attempt, created = queue_run_retry(
            db,
            run_id=source.id,
            project_id=1,
            prompt_id=11,
            idempotency_key="rate-limit-recovery-confirmed",
        )

        assert created is True
        assert retry.id == source.id
        assert retry.status == "retrying"
        assert retry.retry_of_run_id is None
        assert retry.attempt_no == 2
        assert attempt.previous_status == "blocked"

        retry.status = "blocked"
        retry.error_type = "captcha_required"
        db.commit()
        with pytest.raises(HTTPException) as rejected:
            queue_run_retry(
                db,
                run_id=retry.id,
                project_id=1,
                prompt_id=11,
                idempotency_key="captcha-must-stay-blocked",
            )
        assert rejected.value.status_code == 409
    finally:
        db.close()
        engine.dispose()


def test_run_selection_rejects_multiple_attempts_of_one_logical_run(tmp_path):
    db, engine, source = _db(tmp_path)
    try:
        source.status = "success"
        source.stage = "success"
        source.answer_text = "First physical attempt"
        task = BrowserMonitorTask(
            project_id=1,
            question_ids_json="[11]",
            run_count=1,
            status="success",
            created_by="test:second-attempt",
        )
        db.add(task)
        db.flush()
        second = BrowserMonitorRun(
            task_id=task.id,
            project_id=1,
            prompt_id=11,
            status="success",
            stage="success",
            original_query="Question",
            answer_text="Second physical attempt",
            logical_run_id=source.logical_run_id,
            attempt_no=2,
            retry_of_run_id=source.id,
        )
        db.add(second)
        db.commit()

        with pytest.raises(HTTPException) as duplicate_logical_run:
            _selected_run_snapshots(
                db,
                project_id=1,
                prompt_id=11,
                run_ids=[source.id, second.id],
            )
        assert duplicate_logical_run.value.status_code == 409
        assert duplicate_logical_run.value.detail == {
            "code": "DUPLICATE_LOGICAL_RUN",
            "message": "同一逻辑 Run 只能选择一个物理 attempt",
            "logical_runs": {source.logical_run_id: [source.id, second.id]},
            "run_ids": [source.id, second.id],
        }
    finally:
        db.close()
        engine.dispose()


def test_database_rejects_duplicate_attempt_number(tmp_path):
    db, engine, source = _db(tmp_path)
    try:
        task = BrowserMonitorTask(
            project_id=1,
            question_ids_json="[11]",
            run_count=1,
            status="queued",
            created_by="test:duplicate",
        )
        db.add(task)
        db.flush()
        db.add(BrowserMonitorRun(
            task_id=task.id,
            project_id=1,
            prompt_id=11,
            original_query="Question",
            logical_run_id=source.logical_run_id,
            attempt_no=1,
        ))
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()
        engine.dispose()


def test_legacy_retry_pair_reconciles_to_one_business_run(tmp_path):
    db, engine, source = _db(tmp_path)
    try:
        retry_task = BrowserMonitorTask(
            project_id=1,
            question_ids_json="[11]",
            run_count=1,
            status="success",
            schedule_type="single_prompt_v2_run_retry",
            created_by="test:legacy-retry",
        )
        db.add(retry_task)
        db.flush()
        result = BrowserMonitorRun(
            task_id=retry_task.id,
            project_id=1,
            prompt_id=11,
            status="success",
            stage="success",
            original_query="Question",
            answer_text="A complete real answer that is long enough for analysis.",
            answer_char_count=56,
            logical_run_id=source.logical_run_id,
            attempt_id="legacy-success-attempt",
            attempt_no=2,
            retry_of_run_id=source.id,
            retry_idempotency_key="legacy-retry-key",
            resolved_reference_count=1,
            reference_complete=True,
        )
        db.add(result)
        db.flush()
        db.add(ReferenceSource(
            run_id=result.id,
            reference_index=1,
            display_title="Observed source",
            url="https://example.com/source",
        ))
        db.commit()

        audit = audit_pair(db, source_run_id=source.id, result_run_id=result.id)
        assert audit["status"] == "SAFE_TO_RECONCILE"
        reconciled = reconcile_pair(db, source_run_id=source.id, result_run_id=result.id)
        assert reconciled["status"] == "RECONCILED"
        assert db.get(BrowserMonitorRun, result.id) is None
        business_run = db.get(BrowserMonitorRun, source.id)
        assert business_run.status == "success"
        assert business_run.answer_text.startswith("A complete real answer")
        assert business_run.retry_of_run_id is None
        assert business_run.attempt_no == 2
        assert db.query(ReferenceSource).filter_by(run_id=source.id).count() == 1
        attempt = db.query(BrowserMonitorRunAttempt).filter_by(run_id=source.id).one()
        assert attempt.previous_status == "failed"
        assert attempt.status == "SUCCESS"
    finally:
        db.close()
        engine.dispose()


def test_release_migration_backfills_each_historical_run_as_its_own_root(tmp_path, monkeypatch):
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('20261015_02')"))
        connection.execute(text(
            "CREATE TABLE browser_monitor_runs ("
            "id INTEGER PRIMARY KEY, retry_count INTEGER NOT NULL DEFAULT 0)"
        ))
        connection.execute(text(
            "INSERT INTO browser_monitor_runs (id, retry_count) VALUES (10, 0), (11, 4)"
        ))
    engine.dispose()

    monkeypatch.setenv("GEO_RELEASE_DATABASE_URL", database_url)
    command.upgrade(Config(str(BACKEND_ROOT / "alembic.release.ini")), "head")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        rows = connection.execute(text(
            "SELECT id, logical_run_id, attempt_id, attempt_no, retry_of_run_id "
            "FROM browser_monitor_runs ORDER BY id"
        )).mappings().all()
        assert rows == [
            {
                "id": 10,
                "logical_run_id": "legacy-logical-run-10",
                "attempt_id": "legacy-run-attempt-10",
                "attempt_no": 1,
                "retry_of_run_id": None,
            },
            {
                "id": 11,
                "logical_run_id": "legacy-logical-run-11",
                "attempt_id": "legacy-run-attempt-11",
                "attempt_no": 1,
                "retry_of_run_id": None,
            },
        ]
        with pytest.raises(IntegrityError):
            connection.execute(text(
                "INSERT INTO browser_monitor_runs "
                "(id, retry_count, logical_run_id, attempt_id, attempt_no) "
                "VALUES (12, 0, 'legacy-logical-run-10', 'new-attempt', 1)"
            ))
    engine.dispose()


def test_release_migration_preserves_existing_valid_lineage_on_replayed_upgrade(tmp_path):
    db, engine, source = _db(tmp_path)
    try:
        task = BrowserMonitorTask(
            project_id=1,
            question_ids_json="[11]",
            run_count=1,
            status="failed",
            created_by="test:existing-lineage",
        )
        db.add(task)
        db.flush()
        child = BrowserMonitorRun(
            task_id=task.id,
            project_id=1,
            prompt_id=11,
            status="failed",
            original_query="Question",
            logical_run_id=source.logical_run_id,
            attempt_id="existing-attempt-id",
            attempt_no=2,
            retry_of_run_id=source.id,
            retry_idempotency_key="existing-idempotency-key",
        )
        db.add(child)
        db.commit()
        before = (
            child.logical_run_id,
            child.attempt_id,
            child.attempt_no,
            child.retry_of_run_id,
            child.retry_idempotency_key,
        )

        migration_path = BACKEND_ROOT / "alembic_release/versions/20261015_03_run_retry_lineage.py"
        spec = importlib.util.spec_from_file_location("replayed_run_lineage_migration", migration_path)
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        connection = db.connection()
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        db.expire_all()

        preserved = db.get(BrowserMonitorRun, child.id)
        assert (
            preserved.logical_run_id,
            preserved.attempt_id,
            preserved.attempt_no,
            preserved.retry_of_run_id,
            preserved.retry_idempotency_key,
        ) == before
    finally:
        db.close()
        engine.dispose()
