from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import Base, BrowserMonitorRun, BrowserMonitorTask, Project, Prompt
from app.modules.single_prompt_v2.service import list_prompt_run_pool, queue_run_retry


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


def test_retry_appends_attempt_lineage_and_is_idempotent(tmp_path):
    db, engine, source = _db(tmp_path)
    try:
        original_attempt_id = source.attempt_id
        retry, created = queue_run_retry(
            db,
            run_id=source.id,
            project_id=1,
            prompt_id=11,
            idempotency_key="retry-key-1",
        )
        assert created is True
        assert (retry.logical_run_id, retry.attempt_no, retry.retry_of_run_id) == (
            source.logical_run_id,
            2,
            source.id,
        )
        assert retry.attempt_id != original_attempt_id
        assert (source.status, source.error_message, source.attempt_no, source.retry_of_run_id) == (
            "failed",
            "kept failure",
            1,
            None,
        )

        duplicate, duplicate_created = queue_run_retry(
            db,
            run_id=source.id,
            project_id=1,
            prompt_id=11,
            idempotency_key="retry-key-1",
        )
        assert duplicate_created is False
        assert duplicate.id == retry.id

        with pytest.raises(HTTPException, match="最新失败 attempt"):
            queue_run_retry(
                db,
                run_id=source.id,
                project_id=1,
                prompt_id=11,
                idempotency_key="retry-key-2",
            )

        retry.status = "failed"
        retry.stage = "failed"
        retry.error_type = "network_error"
        db.commit()
        third, third_created = queue_run_retry(
            db,
            run_id=retry.id,
            project_id=1,
            prompt_id=11,
            idempotency_key="retry-key-2",
        )
        assert third_created is True
        assert (third.logical_run_id, third.attempt_no, third.retry_of_run_id) == (
            source.logical_run_id,
            3,
            retry.id,
        )

        pool = list_prompt_run_pool(db, project_id=1, prompt_id=11, page=1, page_size=20)
        lineage = {
            item["run_id"]: (
                item["logical_run_id"],
                item["attempt_id"],
                item["attempt_no"],
                item["retry_of_run_id"],
            )
            for item in pool["items"]
        }
        assert lineage[source.id][2:] == (1, None)
        assert lineage[retry.id][2:] == (2, source.id)
        assert lineage[third.id][2:] == (3, retry.id)
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
