"""Offline M1.1 protection checks.

These tests deliberately use temporary databases and synthetic/frozen fixtures.
They are acceptance evidence for the local Beta boundary; they do not enable a
provider, create a real sample, or modify a release database.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.release_access import require_project_access
from app.core.release_sqlite import get_release_sqlite_dbapi
from app.core.release_worker_lifecycle import worker_ownership, worker_status
from app.models import AgentExperimentRun
from app.modules.agent_experiment import evidence_pack
from app.modules.agent_experiment.evidence_pack import (
    DeepSeekEvidencePackClient,
    EvidencePackCapacityError,
    build_evidence_pack,
    execute_evidence_pack_run,
)
from app.modules.single_prompt_v2.scheduling import _collection_authorized
from app.services.semantic_llm.base import SemanticLLMError
from app.services.shared_model_budget import (
    SharedBudgetDenied,
    initialize,
    reserve,
    settle,
    summary,
)
from scripts.m1_beta_ops import backup_home, restore_backup
from test_agent_experiment import (
    ScriptedEvidencePackClient,
    _create_from_fixture,
    _evidence_markdown,
)
from test_release_first_slice import _migrated_session, _seed_citation_contribution_fixture


def _request_identity(seed: str) -> dict[str, object]:
    return {
        "provider": "deepseek",
        "requested_model_alias": "deepseek-flash",
        "effective_request_model": "deepseek-flash",
        "endpoint": "https://api.deepseek.com/responses",
        "endpoint_path": "/responses",
        "transport_kind": "RESPONSES_JSON_SCHEMA",
        "provider_payload_hash": hashlib.sha256(seed.encode()).hexdigest(),
        "input_hash": hashlib.sha256(("input:" + seed).encode()).hexdigest(),
        "input_token_upper_bound": 10_000,
        "max_output_tokens": 8_000,
        "attempt": 1,
    }


class _NeverCalledClient:
    calls = 0

    def generate(self, **kwargs):
        self.calls += 1
        raise AssertionError("capacity preflight must run before provider generation")


def test_capacity_failure_is_before_provider_and_is_recorded_as_failed_run(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, created = _create_from_fixture(
        db, fixture, key="m1-capacity-preflight", execution_mode="EVIDENCE_PACK"
    )
    assert created
    scope = json.loads(run.input_scope_json)
    # Keep this test focused on the provider boundary. The capacity planner is
    # exercised separately; this injected hard-stop preserves the immutable
    # run identity while proving that a capacity failure never reaches the
    # provider or creates a result version.
    monkeypatch.setattr(evidence_pack, "revalidate_frozen_scope", lambda _db, _run: scope)
    monkeypatch.setattr(
        evidence_pack,
        "build_evidence_pack",
        lambda _scope: (_ for _ in ()).throw(
            EvidencePackCapacityError("EVIDENCE_PACK_CORE_EXCEEDS_BUDGET:150000:90000")
        ),
    )
    client = _NeverCalledClient()
    execute_evidence_pack_run(
        run.run_id,
        session_factory=sessionmaker(bind=engine, expire_on_commit=False),
        client=client,
    )
    db.expire_all()
    stored = db.query(AgentExperimentRun).filter_by(run_id=run.run_id).one()
    assert client.calls == 0
    assert stored.status == "FAILED"
    # Current v3 preserves the precise capacity detail. This is intentionally
    # asserted as a prefix so a later stable error-code mapping can improve the
    # UI without changing the safety property.
    assert stored.blocker_code.startswith("EVIDENCE_PACK_CORE_EXCEEDS_BUDGET:")
    assert stored.model_call_count == 0
    assert db.query(AgentExperimentRun).count() == 1


def test_repeating_completed_optimize_task_does_not_call_provider_twice(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, created = _create_from_fixture(
        db, fixture, key="m1-idempotent-optimize", execution_mode="EVIDENCE_PACK"
    )
    assert created
    pack = build_evidence_pack(json.loads(run.input_scope_json))
    client = ScriptedEvidencePackClient(_evidence_markdown(pack))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    execute_evidence_pack_run(run.run_id, session_factory=factory, client=client)
    execute_evidence_pack_run(run.run_id, session_factory=factory, client=client)
    db.expire_all()
    stored = db.query(AgentExperimentRun).filter_by(run_id=run.run_id).one()
    assert stored.status == "SUCCEEDED"
    assert client.calls == 1
    assert stored.model_call_count == 1


def test_shared_budget_settlement_is_idempotent_and_rejects_conflicting_replay(tmp_path):
    path = tmp_path / "budget.sqlite3"
    initialize(
        path,
        batch_id="m1-qa",
        pricing_checked_at=date.today().isoformat(),
        today=date.today(),
    )
    identity = _request_identity("m1-idempotent-settlement")
    reserve(path, lane="AGENT_EXPERIMENT", operation_id="qa", request_id="qa-1", identity=identity)
    outcome = {"token_usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}
    settle(path, request_id="qa-1", status="FINISHED", outcome=outcome)
    settle(path, request_id="qa-1", status="FINISHED", outcome=outcome)
    assert summary(path)["used_requests"] == 1
    assert summary(path)["used_tokens"] == 15
    with pytest.raises(SharedBudgetDenied, match="REQUEST_ALREADY_SETTLED_DIFFERENT_OUTCOME"):
        settle(path, request_id="qa-1", status="FAILED", outcome=outcome)


def test_online_backup_captures_active_wal_while_direct_copy_does_not(tmp_path):
    sqlite = get_release_sqlite_dbapi()
    source = tmp_path / "active.db"
    direct = tmp_path / "direct-copy.db"
    online = tmp_path / "online-backup.db"
    with sqlite.connect(source) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)")
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.execute("INSERT INTO sample(value) VALUES ('committed in WAL')")
        writer.commit()
        shutil.copy2(source, direct)
        with sqlite.connect(online) as target:
            writer.backup(target)

    def row_count(path: Path) -> int:
        try:
            with sqlite.connect(path) as db:
                return int(db.execute("SELECT count(*) FROM sample").fetchone()[0])
        except sqlite.Error:
            return 0

    assert row_count(online) == 1
    assert row_count(direct) == 0


def test_worker_lock_enforces_single_instance_and_cleans_heartbeat(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    with worker_ownership(engine):
        assert worker_status(engine)["status"] == "RUNNING"
        with pytest.raises(RuntimeError, match="already owns"):
            with worker_ownership(engine):
                pass
    assert worker_status(engine)["status"] == "NOT_RUNNING"


def test_access_config_requires_owner_only_permissions(tmp_path, monkeypatch):
    from app.core import release_access

    config = tmp_path / "access.json"
    config.write_text(json.dumps({"accounts": [{
        "name": "qa", "key_sha256": "a" * 64, "project_ids": [1], "admin": False,
    }]}))
    config.chmod(0o644)
    monkeypatch.setenv("GEO_RELEASE_ACCESS_CONFIG", str(config))
    with pytest.raises(RuntimeError, match="owner"):
        release_access.configuration()
    config.chmod(0o600)
    assert release_access.configuration()["accounts"][0]["project_ids"] == [1]


def test_project_access_rejects_cross_project_request(monkeypatch):
    from app.core import release_access
    from starlette.requests import Request

    request = Request({
        "type": "http", "method": "GET", "path": "/api/runs",
        "query_string": b"project_id=2", "headers": [],
        "client": ("127.0.0.1", 1234), "server": ("127.0.0.1", 8032),
        "scheme": "http", "root_path": "", "app": None,
    })
    monkeypatch.setattr(release_access, "principal", lambda _request: {
        "name": "qa", "admin": False, "project_ids": [1], "mode": "INVITATION",
    })
    with pytest.raises(HTTPException) as error:
        asyncio.run(require_project_access(request))
    assert error.value.status_code == 403


def test_disabled_sampling_and_cache_only_generation_make_no_external_call(monkeypatch):
    monkeypatch.setenv("GEO_BETA_SCHEDULED_SAMPLING_ENABLED", "0")
    assert _collection_authorized() is False
    client = DeepSeekEvidencePackClient(
        cache_only=True,
        request_guard=lambda _identity: pytest.fail("cache-only path attempted external request"),
        conservative_cny_per_million_tokens=0,
    )
    with pytest.raises(SemanticLLMError) as error:
        client.generate(db=None, system_prompt="offline QA", evidence_pack={}, max_tokens=100)
    assert error.value.code == "CACHE_MISS"


def test_restore_relocates_artifacts_and_keeps_external_capabilities_disabled(tmp_path):
    # This check uses a minimal release-shaped home and the same backup/restore
    # helpers as the local Beta. It proves root relocation without touching the
    # developer's actual database or evidence directory.
    home = tmp_path / "source-home"
    (home / "data").mkdir(parents=True)
    (home / "evidence").mkdir()
    (home / "config").mkdir()
    (home / "run").mkdir()
    (home / "run" / "services-stopped").write_text("offline QA\n")
    (home / "VERSION").write_text("qa\n")
    db_path = home / "data" / "geo-beta.db"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE alembic_version(version_num TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('qa')")
        db.commit()
    backup = tmp_path / "backup"
    # No prepared-source rows are needed to establish the relocation policy;
    # the restore still creates a new root and resets capability flags.
    backup_home(home, backup)
    restored = tmp_path / "restored-home"
    result = restore_backup(backup, restored)
    assert result["status"] == "PASS_RESTORED_TO_NEW_HOME"
    assert result["daily_model_calls"] == 0
    assert result["scheduled_sampling"] == 0
    assert (restored / "config" / "daily-model-calls").read_text().strip() == "0"
    assert (restored / "config" / "scheduled-sampling-enabled").read_text().strip() == "0"
