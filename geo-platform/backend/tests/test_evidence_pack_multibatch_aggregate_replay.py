from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.models import (
    AgentExperimentRun, AgentMultiBatchAggregateCandidate,
    AgentMultiBatchAggregateReplayAttempt, AgentMultiBatchAggregateReplayResultCandidate,
    AgentMultiBatchAttempt, AgentMultiBatchPlan, AgentMultiBatchResult,
    AgentResultVersion, Base,
)
from app.modules.agent_experiment.evidence_pack import EVIDENCE_PACK_VALIDATION_CONTRACT
from app.modules.agent_experiment.evidence_pack_capacity import CAPACITY_PLAN_CONTRACT
from app.modules.agent_experiment.evidence_pack_multibatch_aggregate_replay import (
    claim_offline_aggregate_replay, complete_offline_aggregate_replay,
    recover_offline_aggregate_replay, request_offline_aggregate_replay_cancel,
    seal_protected_aggregate_replay,
)
from app.modules.agent_experiment.evidence_pack_multibatch_persistence import (
    create_offline_multibatch_plan, persist_offline_aggregate_candidate,
    record_offline_replay_attempt,
)
from app.modules.agent_experiment.evidence_pack_multibatch_shadow import (
    ShadowContractError, make_shadow_batch_result, preflight_shadow_multibatch_budget,
)
from app.modules.single_prompt_v2.delivery_text import digest
from app.services.serialization import loads


ROOT = Path(__file__).resolve().parents[1]


def _plan() -> dict:
    scope_hash = digest({"scope": "aggregate-replay-two-runs"})
    batches, manifest = [], {}
    for number in (1, 2):
        run_id, answer = str(number), f"answer-{number}"
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
    value = {
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
    value["plan_hash"] = digest(value)
    return value


def _batch_result(plan: dict, batch: dict) -> dict:
    return make_shadow_batch_result({
        "frozen_scope_hash": plan["frozen_scope_hash"], "plan_hash": plan["plan_hash"],
        "batch_hash": batch["batch_hash"], "batch_number": batch["batch_number"],
        "batch_result_id": f"result-{batch['batch_number']}", "attempt_number": 1,
        "status": "SUCCESS", "response_hash": digest({"batch": batch["batch_hash"]}),
        "findings": [], "failure_code": None,
    })


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'aggregate-replay.db'}")
    Base.metadata.create_all(engine, tables=[
        AgentExperimentRun.__table__, AgentMultiBatchPlan.__table__,
        AgentMultiBatchAttempt.__table__, AgentMultiBatchResult.__table__,
        AgentMultiBatchAggregateCandidate.__table__,
        AgentMultiBatchAggregateReplayAttempt.__table__,
        AgentMultiBatchAggregateReplayResultCandidate.__table__,
        AgentResultVersion.__table__,
    ])
    factory = sessionmaker(bind=engine)
    db, plan = factory(), _plan()
    db.add(AgentExperimentRun(
        run_id="agent-run-aggregate", project_id=1, prompt_id=1,
        analysis_id="analysis-aggregate", context_id="context-aggregate",
        idempotency_key="agent-key", requested_by="offline-test",
        input_scope_json="{}", input_scope_hash=plan["frozen_scope_hash"],
        agent_execution_json="{}", agent_execution_hash=digest({"execution": 1}),
        qualification_hash=digest({"qualification": 1}), authorization_json="{}",
        budget_json="{}", progress_json="{}", status="COMPLETED",
    ))
    db.commit()
    yield factory, db, plan
    db.close()
    engine.dispose()


def _ready_candidate(db, plan):
    reservation = preflight_shadow_multibatch_budget(
        plan, aggregate_call_token_reservation=500, max_requests=5,
        max_total_tokens=4500, max_cost_cny=1.0,
        conservative_cny_per_million_tokens=1.0, max_attempts_per_batch=2,
    )
    persisted = create_offline_multibatch_plan(
        db, agent_run_id="agent-run-aggregate", plan=plan,
        budget_reservation=reservation, idempotency_key="plan-key",
    )
    for batch in plan["batches"]:
        record_offline_replay_attempt(
            db, plan_id=persisted.plan_id, batch_hash=batch["batch_hash"],
            idempotency_key=f"batch-{batch['batch_number']}", outcome="SUCCESS",
            replay_result=_batch_result(plan, batch),
        )
    candidate = persist_offline_aggregate_candidate(db, plan_id=persisted.plan_id)
    db.commit()
    return candidate


def _replay(db, candidate_id, plan, status="PASS", suffix="ok"):
    candidate = db.query(AgentMultiBatchAggregateCandidate).filter_by(
        candidate_id=candidate_id,
    ).one()
    raw_response = f"protected aggregate markdown {suffix}"
    return seal_protected_aggregate_replay(
        raw_response=raw_response,
        validation_status=status,
        validation_report={
            "validation_contract": EVIDENCE_PACK_VALIDATION_CONTRACT,
            "status": status,
            "raw_response_hash": digest(raw_response),
            "protected_fixture_id": f"fixture-{suffix}",
            "frozen_scope_hash": plan["frozen_scope_hash"],
            "plan_hash": plan["plan_hash"],
            "aggregate_input_hash": candidate.aggregate_input_hash,
            "ordered_batch_result_hashes": loads(
                candidate.ordered_batch_result_hashes_json, [],
            ),
            "issues": [] if status == "PASS" else ["fixture"],
        },
    )


def test_restart_completion_is_idempotent_and_never_writes_formal_result(database):
    factory, db, plan = database
    candidate = _ready_candidate(db, plan)
    candidate_id = candidate.candidate_id
    attempt = claim_offline_aggregate_replay(
        db, aggregate_candidate_id=candidate_id, idempotency_key="aggregate-once")
    attempt_id = attempt.attempt_id
    db.commit()
    db.close()

    db = factory()
    running = recover_offline_aggregate_replay(db, aggregate_candidate_id=candidate_id)
    assert running["plan_status"] == "AGGREGATE_REPLAY_RUNNING"
    assert running["external_calls"] == 0
    replay = _replay(db, candidate_id, plan)
    result = complete_offline_aggregate_replay(
        db, attempt_id=attempt_id, protected_replay=replay)
    db.commit()
    assert result.status == "REPLAY_REPORT_PASS_CANDIDATE"
    assert complete_offline_aggregate_replay(
        db, attempt_id=attempt_id, protected_replay=replay).replay_result_id == result.replay_result_id
    recovered = recover_offline_aggregate_replay(db, aggregate_candidate_id=candidate_id)
    assert recovered["plan_status"] == "AGGREGATE_REPLAY_CANDIDATE_READY"
    assert recovered["formal_result_created"] is False
    assert db.query(AgentResultVersion).count() == 0
    with pytest.raises(ShadowContractError, match="RESULT_IDEMPOTENCY_CONFLICT"):
        complete_offline_aggregate_replay(
            db, attempt_id=attempt_id,
            protected_replay=_replay(db, candidate_id, plan, suffix="different"))


def test_single_reserved_aggregate_attempt_and_failure_is_terminal(database):
    _factory, db, plan = database
    candidate = _ready_candidate(db, plan)
    attempt = claim_offline_aggregate_replay(
        db, aggregate_candidate_id=candidate.candidate_id, idempotency_key="aggregate-once")
    same = claim_offline_aggregate_replay(
        db, aggregate_candidate_id=candidate.candidate_id, idempotency_key="aggregate-once")
    assert same.attempt_id == attempt.attempt_id
    with pytest.raises(ShadowContractError, match="ATTEMPT_EXHAUSTED"):
        claim_offline_aggregate_replay(
            db, aggregate_candidate_id=candidate.candidate_id, idempotency_key="aggregate-twice")
    result = complete_offline_aggregate_replay(
        db, attempt_id=attempt.attempt_id,
        protected_replay=_replay(db, candidate.candidate_id, plan, "FAIL"))
    assert result.status == "REPLAY_VALIDATION_FAILED_CANDIDATE"
    assert recover_offline_aggregate_replay(
        db, aggregate_candidate_id=candidate.candidate_id)["plan_status"] \
        == "AGGREGATE_REPLAY_FAILED_TERMINAL"


def test_cancellation_cas_blocks_claim_and_inflight_completion(database):
    _factory, db, plan = database
    candidate = _ready_candidate(db, plan)
    request_offline_aggregate_replay_cancel(db, aggregate_candidate_id=candidate.candidate_id)
    with pytest.raises(ShadowContractError, match="CLAIM_STATE_CONFLICT"):
        claim_offline_aggregate_replay(
            db, aggregate_candidate_id=candidate.candidate_id, idempotency_key="blocked")


def test_inflight_cancel_blocks_result_candidate(database):
    _factory, db, plan = database
    candidate = _ready_candidate(db, plan)
    attempt = claim_offline_aggregate_replay(
        db, aggregate_candidate_id=candidate.candidate_id, idempotency_key="claimed")
    request_offline_aggregate_replay_cancel(db, aggregate_candidate_id=candidate.candidate_id)
    with pytest.raises(ShadowContractError, match="COMPLETE_STATE_CONFLICT"):
        complete_offline_aggregate_replay(
            db, attempt_id=attempt.attempt_id,
            protected_replay=_replay(db, candidate.candidate_id, plan))
    assert db.query(AgentMultiBatchAggregateReplayResultCandidate).count() == 0


def test_tampered_persisted_binding_fails_closed(database):
    _factory, db, plan = database
    candidate = _ready_candidate(db, plan)
    attempt = claim_offline_aggregate_replay(
        db, aggregate_candidate_id=candidate.candidate_id, idempotency_key="claimed")
    result = complete_offline_aggregate_replay(
        db, attempt_id=attempt.attempt_id,
        protected_replay=_replay(db, candidate.candidate_id, plan))
    db.commit()
    result.binding_hash = digest({"tampered": True})
    db.commit()
    with pytest.raises(ShadowContractError, match="PERSISTED_RESULT_INVALID"):
        recover_offline_aggregate_replay(db, aggregate_candidate_id=candidate.candidate_id)


@pytest.mark.parametrize(("field", "tampered"), [
    ("attempt_id", "foreign-attempt"),
    ("aggregate_candidate_id", "foreign-candidate"),
    ("plan_id", "foreign-plan-row"),
    ("attempt_number", 2),
    ("execution_identity", "foreign-execution"),
    ("frozen_scope_hash", "foreign-scope"),
    ("plan_hash", "foreign-plan-hash"),
    ("aggregate_input_hash", "foreign-aggregate-input"),
    ("status", "FINISHED"),
])
def test_tampered_attempt_scalar_identity_fails_closed(database, field, tampered):
    _factory, db, plan = database
    candidate = _ready_candidate(db, plan)
    attempt = claim_offline_aggregate_replay(
        db, aggregate_candidate_id=candidate.candidate_id, idempotency_key="claimed")
    db.commit()
    setattr(attempt, field, tampered)
    db.flush()
    with pytest.raises(ShadowContractError, match="PERSISTED_ATTEMPT_INVALID"):
        recover_offline_aggregate_replay(db, aggregate_candidate_id=candidate.candidate_id)


@pytest.mark.parametrize(("field", "tampered"), [
    ("replay_result_id", "foreign-result"),
    ("attempt_id", "foreign-attempt"),
    ("aggregate_candidate_id", "foreign-candidate"),
    ("plan_id", "foreign-plan-row"),
    ("status", "REPLAY_VALIDATION_FAILED_CANDIDATE"),
])
def test_tampered_result_scalar_identity_fails_closed(database, field, tampered):
    _factory, db, plan = database
    candidate = _ready_candidate(db, plan)
    attempt = claim_offline_aggregate_replay(
        db, aggregate_candidate_id=candidate.candidate_id, idempotency_key="claimed")
    result = complete_offline_aggregate_replay(
        db, attempt_id=attempt.attempt_id,
        protected_replay=_replay(db, candidate.candidate_id, plan),
    )
    db.commit()
    setattr(result, field, tampered)
    db.flush()
    with pytest.raises(
        ShadowContractError,
        match="PERSISTED_RESULT_INVALID|RESULT_ATTEMPT_MISMATCH",
    ):
        recover_offline_aggregate_replay(db, aggregate_candidate_id=candidate.candidate_id)


def test_fail_bundle_cannot_be_relabelled_as_pass_candidate(database):
    _factory, db, plan = database
    candidate = _ready_candidate(db, plan)
    attempt = claim_offline_aggregate_replay(
        db, aggregate_candidate_id=candidate.candidate_id, idempotency_key="claimed")
    result = complete_offline_aggregate_replay(
        db, attempt_id=attempt.attempt_id,
        protected_replay=_replay(db, candidate.candidate_id, plan, "FAIL"),
    )
    db.commit()
    result.status = "REPLAY_REPORT_PASS_CANDIDATE"
    db.flush()
    with pytest.raises(ShadowContractError, match="PERSISTED_RESULT_INVALID"):
        recover_offline_aggregate_replay(db, aggregate_candidate_id=candidate.candidate_id)


def test_protected_report_status_and_scope_must_match(database):
    _factory, db, plan = database
    candidate = _ready_candidate(db, plan)
    raw = "protected aggregate markdown mismatch"
    base_report = {
        "validation_contract": EVIDENCE_PACK_VALIDATION_CONTRACT,
        "status": "FAIL", "raw_response_hash": digest(raw),
        "protected_fixture_id": "fixture-mismatch",
        "frozen_scope_hash": plan["frozen_scope_hash"],
        "plan_hash": plan["plan_hash"],
        "aggregate_input_hash": candidate.aggregate_input_hash,
        "ordered_batch_result_hashes": loads(
            candidate.ordered_batch_result_hashes_json, [],
        ),
        "issues": [],
    }
    with pytest.raises(ShadowContractError, match="REPORT_BINDING_INVALID"):
        seal_protected_aggregate_replay(
            raw_response=raw, validation_status="PASS", validation_report=base_report,
        )
    attempt = claim_offline_aggregate_replay(
        db, aggregate_candidate_id=candidate.candidate_id,
        idempotency_key="scope-mismatch",
    )
    wrong_scope = dict(base_report)
    wrong_scope.update({"status": "PASS", "aggregate_input_hash": digest("other")})
    replay = seal_protected_aggregate_replay(
        raw_response=raw, validation_status="PASS", validation_report=wrong_scope,
    )
    with pytest.raises(ShadowContractError, match="REPORT_SCOPE_MISMATCH"):
        complete_offline_aggregate_replay(
            db, attempt_id=attempt.attempt_id, protected_replay=replay,
        )
    assert db.query(AgentMultiBatchAggregateReplayResultCandidate).count() == 0


def test_unknown_aggregate_input_cannot_be_claimed(database):
    _factory, db, _plan_value = database
    plan = _plan()
    plan["shadow_run_manifest"]["1"]["brand_literal_matched"] = None
    plan["plan_hash"] = digest({key: value for key, value in plan.items() if key != "plan_hash"})
    reservation = preflight_shadow_multibatch_budget(
        plan, aggregate_call_token_reservation=500, max_requests=5,
        max_total_tokens=4500, max_cost_cny=1.0,
        conservative_cny_per_million_tokens=1.0, max_attempts_per_batch=2,
    )
    persisted = create_offline_multibatch_plan(
        db, agent_run_id="agent-run-aggregate", plan=plan,
        budget_reservation=reservation, idempotency_key="unknown-plan",
    )
    for batch in plan["batches"]:
        record_offline_replay_attempt(
            db, plan_id=persisted.plan_id, batch_hash=batch["batch_hash"],
            idempotency_key=f"unknown-{batch['batch_number']}", outcome="SUCCESS",
            replay_result=_batch_result(plan, batch),
        )
    candidate = persist_offline_aggregate_candidate(db, plan_id=persisted.plan_id)
    assert candidate.status == "SHADOW_CANDIDATE_ONLY"
    with pytest.raises(ShadowContractError, match="INPUT_NOT_ELIGIBLE"):
        claim_offline_aggregate_replay(
            db, aggregate_candidate_id=candidate.candidate_id, idempotency_key="blocked")


def test_release_migration_upgrade_and_empty_downgrade(tmp_path, monkeypatch):
    path = tmp_path / "release.db"
    monkeypatch.setenv("GEO_RELEASE_DATABASE_URL", f"sqlite:///{path.as_posix()}")
    config = Config(str(ROOT / "alembic.release.ini"))
    command.upgrade(config, "20261118_01")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    assert "agent_multibatch_aggregate_replay_attempts" not in inspect(engine).get_table_names()
    engine.dispose()
    command.upgrade(config, "20261118_02")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    assert {
        "agent_multibatch_aggregate_replay_attempts",
        "agent_multibatch_aggregate_replay_result_candidates",
    } <= set(inspect(engine).get_table_names())
    engine.dispose()
    command.downgrade(config, "20261118_01")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    assert "agent_multibatch_aggregate_replay_attempts" not in inspect(engine).get_table_names()
    engine.dispose()


def test_release_migration_refuses_to_delete_aggregate_audit(tmp_path, monkeypatch):
    path = tmp_path / "release-with-aggregate-audit.db"
    monkeypatch.setenv("GEO_RELEASE_DATABASE_URL", f"sqlite:///{path.as_posix()}")
    config = Config(str(ROOT / "alembic.release.ini"))
    command.upgrade(config, "20261118_02")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO agent_multibatch_aggregate_replay_result_candidates (
                replay_result_id, attempt_id, aggregate_candidate_id, plan_id,
                raw_response_hash, validation_profile, validation_status,
                validation_report_json, validation_report_hash,
                replay_bundle_json, replay_bundle_hash, binding_json,
                binding_hash, prospective_result_hash, status, created_at
            ) VALUES (
                'audit-result', 'audit-attempt', 'audit-candidate', 'audit-plan',
                'raw', 'validation', 'FAIL', '{}', 'report', '{}', 'bundle',
                '{}', 'binding', 'prospective', 'REPLAY_VALIDATION_FAILED_CANDIDATE',
                CURRENT_TIMESTAMP
            )
        """))
    engine.dispose()
    with pytest.raises(
        RuntimeError, match="AGENT_MULTIBATCH_AGGREGATE_REPLAY_AUDIT_ROWS_PRESENT",
    ):
        command.downgrade(config, "20261118_01")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    assert "agent_multibatch_aggregate_replay_result_candidates" in inspect(
        engine,
    ).get_table_names()
    engine.dispose()
