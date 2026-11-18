from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import (
    AgentExperimentRun, AgentMultiBatchAggregateCandidate, AgentMultiBatchAttempt,
    AgentMultiBatchPlan, AgentMultiBatchResult, AgentResultVersion, Base,
)
from app.modules.agent_experiment.evidence_pack_capacity import CAPACITY_PLAN_CONTRACT
from app.modules.agent_experiment.evidence_pack_multibatch_persistence import (
    acknowledge_offline_multibatch_cancel, create_offline_multibatch_plan,
    persist_offline_aggregate_candidate, record_offline_replay_attempt,
    recover_offline_multibatch_state, request_offline_multibatch_cancel,
    resume_offline_multibatch_plan,
)
from app.modules.agent_experiment.evidence_pack_multibatch_shadow import (
    ShadowContractError, make_shadow_batch_result, preflight_shadow_multibatch_budget,
)
from app.modules.single_prompt_v2.delivery_text import digest


ROOT = Path(__file__).resolve().parents[1]


def _plan() -> dict:
    scope_hash = digest({"scope": "frozen-two-run-scope"})
    batches = []
    manifest = {}
    for number in (1, 2):
        run_id = str(number)
        answer = f"answer-{number}"
        manifest[run_id] = {
            "answer_hash": digest(answer), "answer_length": len(answer),
            "brand_literal_matched": False,
        }
        batch = {
            "batch_number": number, "run_ids": [run_id],
            "citation_occurrence_ids": [], "source_snapshot_ids": [],
            "source_disposition_ids": [], "evidence_pack_hash": digest({"batch": number}),
            "actual_model_input_characters": 100, "total_token_reservation": 1000,
        }
        batch["batch_hash"] = digest({
            "frozen_scope_hash": scope_hash, "batch_number": number,
            "run_ids": [run_id], "citation_occurrence_ids": [],
            "source_snapshot_ids": [], "source_disposition_ids": [],
            "evidence_pack_hash": batch["evidence_pack_hash"],
        })
        batches.append(batch)
    plan = {
        "contract_version": CAPACITY_PLAN_CONTRACT,
        "mode": "SHADOW_ONLY_NO_MODEL_EXECUTION_NO_RESULT_MERGE",
        "status": "READY", "partition_status": "READY",
        "aggregate_budget_status": "WITHIN_TASK_CAP", "frozen_scope_hash": scope_hash,
        "text_budget": 1000, "task_token_cap": 10_000,
        "aggregate_total_token_reservation": 2000, "batch_count": 2,
        "batches": batches,
        "coverage": {
            "run_total": 2, "run_planned": 2,
            "citation_occurrence_total": 0, "citation_occurrence_covered": 0,
            "source_snapshot_covered": 0, "source_disposition_covered": 0,
            "missing_run_ids": [], "missing_citation_occurrence_ids": [],
            "missing_source_snapshot_ids": [], "missing_source_disposition_ids": [],
            "unassigned_source_snapshot_ids": [],
        },
        "shadow_run_manifest": manifest,
        "shadow_eligibility_rule_version": "geo.evidence-pack.valid-run-eligibility.v2",
    }
    plan["plan_hash"] = digest(plan)
    return plan


def _reservation(plan: dict, attempts: int = 2) -> dict:
    return preflight_shadow_multibatch_budget(
        plan, aggregate_call_token_reservation=500,
        max_requests=plan["batch_count"] * attempts + 1,
        max_total_tokens=plan["aggregate_total_token_reservation"] * attempts + 500,
        max_cost_cny=1.0, conservative_cny_per_million_tokens=1.0,
        max_attempts_per_batch=attempts,
    )


def _result(plan: dict, batch: dict, attempt: int = 1) -> dict:
    return make_shadow_batch_result({
        "frozen_scope_hash": plan["frozen_scope_hash"], "plan_hash": plan["plan_hash"],
        "batch_hash": batch["batch_hash"], "batch_number": batch["batch_number"],
        "batch_result_id": f"result-{batch['batch_number']}-{attempt}",
        "attempt_number": attempt, "status": "SUCCESS",
        "response_hash": digest({"batch": batch["batch_hash"], "attempt": attempt}),
        "findings": [], "failure_code": None,
    })


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'offline.db'}")
    Base.metadata.create_all(engine, tables=[
        AgentExperimentRun.__table__, AgentMultiBatchPlan.__table__,
        AgentMultiBatchAttempt.__table__, AgentMultiBatchResult.__table__,
        AgentMultiBatchAggregateCandidate.__table__, AgentResultVersion.__table__,
    ])
    factory = sessionmaker(bind=engine)
    db = factory()
    plan = _plan()
    db.add(AgentExperimentRun(
        run_id="agent-run-1", project_id=1, prompt_id=1, analysis_id="analysis-1",
        context_id="context-1", idempotency_key="agent-key", requested_by="offline-test",
        input_scope_json="{}", input_scope_hash=plan["frozen_scope_hash"],
        agent_execution_json="{}", agent_execution_hash=digest({"execution": 1}),
        qualification_hash=digest({"qualification": 1}), authorization_json="{}",
        budget_json="{}", progress_json="{}", status="COMPLETED",
    ))
    db.commit()
    yield factory, db, plan
    db.close()
    engine.dispose()


def _persist(db, plan, *, key="plan-key", attempts=2):
    row = create_offline_multibatch_plan(
        db, agent_run_id="agent-run-1", plan=plan,
        budget_reservation=_reservation(plan, attempts), idempotency_key=key,
    )
    db.commit()
    return row


def _agent_run(run_id: str, plan: dict) -> AgentExperimentRun:
    return AgentExperimentRun(
        run_id=run_id, project_id=1, prompt_id=1, analysis_id=f"analysis-{run_id}",
        context_id=f"context-{run_id}", idempotency_key=f"agent-key-{run_id}",
        requested_by="offline-test", input_scope_json="{}",
        input_scope_hash=plan["frozen_scope_hash"], agent_execution_json="{}",
        agent_execution_hash=digest({"execution": run_id}),
        qualification_hash=digest({"qualification": run_id}), authorization_json="{}",
        budget_json="{}", progress_json="{}", status="COMPLETED",
    )


def test_plan_is_exactly_bound_and_idempotent(database):
    _factory, db, plan = database
    first = _persist(db, plan)
    second = create_offline_multibatch_plan(
        db, agent_run_id="agent-run-1", plan=plan,
        budget_reservation=_reservation(plan), idempotency_key="plan-key",
    )
    assert second.plan_id == first.plan_id
    assert recover_offline_multibatch_state(db, plan_id=first.plan_id)["external_calls"] == 0

    changed = _reservation(plan, 1)
    with pytest.raises(ShadowContractError, match="IDEMPOTENCY_CONFLICT"):
        create_offline_multibatch_plan(
            db, agent_run_id="agent-run-1", plan=plan,
            budget_reservation=changed, idempotency_key="plan-key",
        )


def test_restart_resume_attempt_limit_and_success_is_immutable(database):
    factory, db, plan = database
    row = _persist(db, plan)
    plan_id = row.plan_id
    first_batch, second_batch = plan["batches"]
    record_offline_replay_attempt(
        db, plan_id=plan_id, batch_hash=first_batch["batch_hash"],
        idempotency_key="attempt-fail", outcome="FAILED", failure_code="REPLAY_FAILURE",
    )
    replay = record_offline_replay_attempt(
        db, plan_id=plan_id, batch_hash=first_batch["batch_hash"],
        idempotency_key="attempt-fail", outcome="FAILED", failure_code="REPLAY_FAILURE",
    )
    assert replay.attempt_number == 1
    db.commit()
    db.close()

    db = factory()
    recovered = recover_offline_multibatch_state(db, plan_id=plan_id)
    assert recovered["status"] == "FAILED_RECOVERABLE"
    with pytest.raises(ShadowContractError, match="RETRY_REQUIRES_RESUME"):
        record_offline_replay_attempt(
            db, plan_id=plan_id, batch_hash=first_batch["batch_hash"],
            idempotency_key="attempt-too-early", outcome="SUCCESS",
            replay_result=_result(plan, first_batch, 2),
        )
    assert resume_offline_multibatch_plan(db, plan_id=plan_id).status == "RUNNING"
    record_offline_replay_attempt(
        db, plan_id=plan_id, batch_hash=first_batch["batch_hash"],
        idempotency_key="attempt-success", outcome="SUCCESS",
        replay_result=_result(plan, first_batch, 2),
    )
    with pytest.raises(ShadowContractError, match="SUCCESS_IMMUTABLE"):
        record_offline_replay_attempt(
            db, plan_id=plan_id, batch_hash=first_batch["batch_hash"],
            idempotency_key="attempt-overwrite", outcome="SUCCESS",
            replay_result=_result(plan, first_batch, 3),
        )
    record_offline_replay_attempt(
        db, plan_id=plan_id, batch_hash=second_batch["batch_hash"],
        idempotency_key="attempt-second", outcome="SUCCESS",
        replay_result=_result(plan, second_batch),
    )
    assert recover_offline_multibatch_state(db, plan_id=plan_id)["status"] == "READY_FOR_SHADOW_AGGREGATE"
    candidate = persist_offline_aggregate_candidate(db, plan_id=plan_id)
    db.commit()
    assert candidate.status == "SHADOW_CANDIDATE_ONLY"
    assert persist_offline_aggregate_candidate(db, plan_id=plan_id).candidate_id == candidate.candidate_id
    assert db.query(AgentResultVersion).count() == 0
    assert db.query(AgentMultiBatchAggregateCandidate).count() == 1


def test_cancel_is_durable_and_prevents_fake_calls(database):
    factory, db, plan = database
    row = _persist(db, plan)
    plan_id = row.plan_id
    assert request_offline_multibatch_cancel(db, plan_id=plan_id).status == "CANCEL_REQUESTED"
    db.commit()
    db.close()
    db = factory()
    assert recover_offline_multibatch_state(db, plan_id=plan_id)["status"] == "CANCEL_REQUESTED"
    with pytest.raises(ShadowContractError, match="BLOCKS_ATTEMPT"):
        record_offline_replay_attempt(
            db, plan_id=plan_id, batch_hash=plan["batches"][0]["batch_hash"],
            idempotency_key="cancelled-attempt", outcome="SUCCESS",
            replay_result=_result(plan, plan["batches"][0]),
        )
    assert acknowledge_offline_multibatch_cancel(db, plan_id=plan_id).status == "CANCELLED"
    db.commit()
    assert recover_offline_multibatch_state(db, plan_id=plan_id)["status"] == "CANCELLED"


def test_bad_hash_and_cross_scope_are_zero_write(database):
    _factory, db, plan = database
    row = _persist(db, plan)
    bad = _result(plan, plan["batches"][0])
    bad["frozen_scope_hash"] = digest({"other": "scope"})
    bad["result_hash"] = digest({key: value for key, value in bad.items() if key != "result_hash"})
    with pytest.raises(ShadowContractError, match="RESULT_SCOPE_MISMATCH"):
        record_offline_replay_attempt(
            db, plan_id=row.plan_id, batch_hash=plan["batches"][0]["batch_hash"],
            idempotency_key="bad-scope", outcome="SUCCESS", replay_result=bad,
        )
    assert db.query(AgentMultiBatchAttempt).count() == 0
    assert db.query(AgentMultiBatchResult).count() == 0


def test_recovery_fails_closed_on_corrupt_attempt_hash(database):
    _factory, db, plan = database
    row = _persist(db, plan)
    attempt = record_offline_replay_attempt(
        db, plan_id=row.plan_id, batch_hash=plan["batches"][0]["batch_hash"],
        idempotency_key="failed", outcome="FAILED", failure_code="REPLAY_FAILURE",
    )
    db.commit()
    attempt.payload_hash = digest({"tampered": True})
    db.commit()
    with pytest.raises(ShadowContractError, match="ATTEMPT_PAYLOAD_HASH_MISMATCH"):
        recover_offline_multibatch_state(db, plan_id=row.plan_id)


def test_attempt_limit_becomes_terminal(database):
    _factory, db, plan = database
    row = _persist(db, plan, attempts=1)
    record_offline_replay_attempt(
        db, plan_id=row.plan_id, batch_hash=plan["batches"][0]["batch_hash"],
        idempotency_key="only-attempt", outcome="FAILED", failure_code="REPLAY_FAILURE",
    )
    assert recover_offline_multibatch_state(db, plan_id=row.plan_id)["status"] == "FAILED_TERMINAL"
    with pytest.raises(ShadowContractError, match="BLOCKS_ATTEMPT"):
        record_offline_replay_attempt(
            db, plan_id=row.plan_id, batch_hash=plan["batches"][0]["batch_hash"],
            idempotency_key="extra-attempt", outcome="FAILED", failure_code="REPLAY_FAILURE",
        )
    with pytest.raises(ShadowContractError, match="ALREADY_TERMINAL"):
        request_offline_multibatch_cancel(db, plan_id=row.plan_id)


def test_success_replay_requires_success_status_and_exact_attempt_number(database):
    _factory, db, plan = database
    row = _persist(db, plan)
    batch = plan["batches"][0]
    wrong_attempt = _result(plan, batch, 99)
    with pytest.raises(ShadowContractError, match="REPLAY_BATCH_MISMATCH"):
        record_offline_replay_attempt(
            db, plan_id=row.plan_id, batch_hash=batch["batch_hash"],
            idempotency_key="wrong-attempt", outcome="SUCCESS",
            replay_result=wrong_attempt,
        )
    failed_payload = {
        "frozen_scope_hash": plan["frozen_scope_hash"], "plan_hash": plan["plan_hash"],
        "batch_hash": batch["batch_hash"], "batch_number": batch["batch_number"],
        "batch_result_id": "failed-as-success", "attempt_number": 1,
        "status": "FAILED", "response_hash": None, "findings": [],
        "failure_code": "REPLAY_FAILURE",
    }
    with pytest.raises(ShadowContractError, match="REPLAY_BATCH_MISMATCH"):
        record_offline_replay_attempt(
            db, plan_id=row.plan_id, batch_hash=batch["batch_hash"],
            idempotency_key="failed-as-success", outcome="SUCCESS",
            replay_result=make_shadow_batch_result(failed_payload),
        )
    assert db.query(AgentMultiBatchAttempt).count() == 0
    assert db.query(AgentMultiBatchResult).count() == 0


def test_recovery_rejects_result_attempt_batch_mismatch(database):
    _factory, db, plan = database
    row = _persist(db, plan)
    batch = plan["batches"][0]
    record_offline_replay_attempt(
        db, plan_id=row.plan_id, batch_hash=batch["batch_hash"],
        idempotency_key="success", outcome="SUCCESS", replay_result=_result(plan, batch),
    )
    db.commit()
    result = db.query(AgentMultiBatchResult).one()
    result.batch_hash = plan["batches"][1]["batch_hash"]
    db.commit()
    with pytest.raises(ShadowContractError, match="RESULT_BINDING_MISMATCH"):
        recover_offline_multibatch_state(db, plan_id=row.plan_id)


def test_release_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    path = tmp_path / "release.db"
    monkeypatch.setenv("GEO_RELEASE_DATABASE_URL", f"sqlite:///{path.as_posix()}")
    config = Config(str(ROOT / "alembic.release.ini"))
    command.upgrade(config, "20261030_02")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    assert "agent_multibatch_plans" not in inspect(engine).get_table_names()
    engine.dispose()
    command.upgrade(config, "20261118_01")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    tables = set(inspect(engine).get_table_names())
    assert {
        "agent_multibatch_plans", "agent_multibatch_attempts",
        "agent_multibatch_results", "agent_multibatch_aggregate_candidates",
    } <= tables
    engine.dispose()
    command.downgrade(config, "20261030_02")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    assert "agent_multibatch_plans" not in inspect(engine).get_table_names()
    engine.dispose()


def test_release_migration_refuses_to_delete_persisted_audit(tmp_path, monkeypatch):
    path = tmp_path / "release-with-audit.db"
    monkeypatch.setenv("GEO_RELEASE_DATABASE_URL", f"sqlite:///{path.as_posix()}")
    config = Config(str(ROOT / "alembic.release.ini"))
    command.upgrade(config, "20261118_01")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO agent_multibatch_plans (
                plan_id, agent_run_id, frozen_scope_hash, plan_hash,
                reservation_identity_hash, idempotency_key, plan_json,
                reservation_json, max_attempts_per_batch, status, revision,
                created_at, updated_at
            ) VALUES (
                'audit-plan', 'missing-parent-is-not-read', 'scope', 'plan',
                'reservation', 'key', '{}', '{}', 1, 'CANCEL_REQUESTED', 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """))
        with pytest.raises(IntegrityError, match="AGENT_MULTIBATCH_PLAN_BLOCKS_ATTEMPT"):
            with connection.begin_nested():
                connection.execute(text("""
                    INSERT INTO agent_multibatch_attempts (
                        attempt_id, plan_id, batch_hash, batch_number, attempt_number,
                        idempotency_key, status, failure_code, result_hash,
                        payload_json, payload_hash, created_at
                    ) VALUES (
                        'blocked-attempt', 'audit-plan', 'batch', 1, 1,
                        'attempt-key', 'FAILED', 'cancelled', NULL,
                        '{}', 'payload', CURRENT_TIMESTAMP
                    )
                """))
    engine.dispose()
    with pytest.raises(RuntimeError, match="AGENT_MULTIBATCH_AUDIT_ROWS_PRESENT"):
        command.downgrade(config, "20261030_02")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    assert "agent_multibatch_plans" in inspect(engine).get_table_names()
    engine.dispose()


def test_migrated_database_state_transitions_do_not_overwrite_concurrent_cancel(
    tmp_path, monkeypatch,
):
    path = tmp_path / "release-cas.db"
    monkeypatch.setenv("GEO_RELEASE_DATABASE_URL", f"sqlite:///{path.as_posix()}")
    config = Config(str(ROOT / "alembic.release.ini"))
    command.upgrade(config, "20261118_01")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    factory = sessionmaker(bind=engine)
    plan = _plan()

    setup = factory()
    setup.add_all([_agent_run("cas-retry", plan), _agent_run("cas-aggregate", plan)])
    setup.commit()
    retry_plan = create_offline_multibatch_plan(
        setup, agent_run_id="cas-retry", plan=plan,
        budget_reservation=_reservation(plan), idempotency_key="retry-plan",
    )
    record_offline_replay_attempt(
        setup, plan_id=retry_plan.plan_id, batch_hash=plan["batches"][0]["batch_hash"],
        idempotency_key="retry-failed", outcome="FAILED", failure_code="REPLAY_FAILURE",
    )
    aggregate_plan = create_offline_multibatch_plan(
        setup, agent_run_id="cas-aggregate", plan=plan,
        budget_reservation=_reservation(plan), idempotency_key="aggregate-plan",
    )
    for batch in plan["batches"]:
        record_offline_replay_attempt(
            setup, plan_id=aggregate_plan.plan_id, batch_hash=batch["batch_hash"],
            idempotency_key=f"success-{batch['batch_number']}", outcome="SUCCESS",
            replay_result=_result(plan, batch),
        )
    setup.commit()
    retry_plan_id, aggregate_plan_id = retry_plan.plan_id, aggregate_plan.plan_id
    setup.close()

    stale_retry, cancel_retry = factory(), factory()
    stale_retry.query(AgentMultiBatchPlan).filter_by(plan_id=retry_plan_id).one()
    request_offline_multibatch_cancel(cancel_retry, plan_id=retry_plan_id)
    cancel_retry.commit()
    with pytest.raises(ShadowContractError, match="NOT_RECOVERABLE"):
        resume_offline_multibatch_plan(stale_retry, plan_id=retry_plan_id)
    stale_retry.rollback()
    assert recover_offline_multibatch_state(stale_retry, plan_id=retry_plan_id)["status"] == "CANCEL_REQUESTED"
    stale_retry.close()
    cancel_retry.close()

    stale_aggregate, cancel_aggregate = factory(), factory()
    stale_aggregate.query(AgentMultiBatchPlan).filter_by(plan_id=aggregate_plan_id).one()
    request_offline_multibatch_cancel(cancel_aggregate, plan_id=aggregate_plan_id)
    cancel_aggregate.commit()
    with pytest.raises(ShadowContractError, match="AGGREGATE_NOT_READY"):
        persist_offline_aggregate_candidate(stale_aggregate, plan_id=aggregate_plan_id)
    stale_aggregate.rollback()
    assert recover_offline_multibatch_state(
        stale_aggregate, plan_id=aggregate_plan_id,
    )["status"] == "CANCEL_REQUESTED"
    assert stale_aggregate.query(AgentMultiBatchAggregateCandidate).count() == 0
    stale_aggregate.close()
    cancel_aggregate.close()
    engine.dispose()
