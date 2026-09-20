from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.runtime_persistence.models import (
    RuntimeAnalysisContext,
    RuntimeContextStageSelection,
    RuntimeCurrentContextPointerEvent,
    RuntimeManifest,
    RuntimeStageAttemptResult,
    RuntimeStageExecution,
    RuntimeStageReviewDecision,
    RuntimeValidityEvent,
)
from app.modules.runtime_persistence.repository import (
    ConcurrencyConflict,
    InvalidTransition,
    ReviewConflict,
    RuntimePersistence,
)
from app.modules.runtime_projection.canonical import EMPTY_COLLECTION, semantic_hash
from app.modules.runtime_projection.projector import RUNTIME_PROFILE_VERSION, normative_vectors


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = BACKEND_ROOT / "alembic/versions/20260910_01_runtime_persistence_spine.py"
RUNTIME_TABLES = {
    "runtime_manifests",
    "runtime_analysis_contexts",
    "runtime_stage_executions",
    "runtime_stage_input_edges",
    "runtime_stage_attempts",
    "runtime_stage_attempt_results",
    "runtime_review_targets",
    "runtime_stage_review_decisions",
    "runtime_current_context_pointers",
    "runtime_current_context_pointer_events",
    "runtime_context_stage_selections",
    "runtime_context_stage_selection_events",
    "runtime_validity_states",
    "runtime_validity_events",
}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _load_migration():
    spec = importlib.util.spec_from_file_location("runtime_phase_1a_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply_migration(connection) -> None:
    vectors = normative_vectors()
    assert all(vector["match"] for vector in vectors.values())
    assert vectors["source_ref_set_hash"]["actual"] == (
        "543fa710799ecc38c9382b3646643a6b8fddcd807fcd8e43cbe1d3f942b5a483"
    )
    migration = _load_migration()
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()


@pytest.fixture
def session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'runtime-phase-1a.db'}")

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as connection:
        _apply_migration(connection)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        yield db
        db.rollback()
    engine.dispose()


def _manifest(
    runtime: RuntimePersistence,
    manifest_id: str,
    manifest_type: str,
    contract: str,
    members: list[dict] | None = None,
):
    members = [] if members is None else members
    payload = {"members": EMPTY_COLLECTION if not members else members}
    return runtime.create_manifest(
        manifest_id=manifest_id,
        manifest_type=manifest_type,
        manifest_contract_version=contract,
        payload=payload,
        member_refs=members,
        created_by="phase-1a-test",
    )


def _context(
    runtime: RuntimePersistence,
    context_id: str,
    *,
    track: str = "SHADOW",
    fingerprint: str | None = None,
):
    root = _manifest(
        runtime,
        f"manifest:root:{context_id}",
        "EvidencePackageRootProjection",
        "evidence_package_root_projection.v1",
    )
    return runtime.create_context(
        context_id=context_id,
        project_id=3,
        prompt_id=19,
        workflow_track=track,
        context_fingerprint=fingerprint or semantic_hash({"root": "same"}),
        root_manifest_id=root.manifest_id,
        root_runtime_contract_profile_version="runtime_root_profile.v1",
        context_manifest_hash=semantic_hash({"context_id": context_id, "track": track}),
        evidence_package_ref="evidence-package:12",
        creation_actor="phase-1a-test",
        creation_reason="isolated acceptance",
    )


def _stage(
    runtime: RuntimePersistence,
    execution_id: str,
    context_id: str,
    stage_type: str = "ANSWER_SEMANTIC",
    upstream: RuntimeStageExecution | None = None,
    supersedes: str | None = None,
):
    contract = f"runtime_stage.{stage_type.lower()}.v1"
    config = _manifest(
        runtime,
        f"manifest:config:{execution_id}",
        f"StageConfigurationManifest/{stage_type}",
        f"{contract}/configuration",
    )
    edges = [
        {
            "input_role": "CONFIGURATION",
            "source_manifest_type": config.manifest_type,
            "source_identity_ref": config.manifest_id,
            "source_contract_version": config.manifest_contract_version,
            "consumed_semantic_hash": config.canonical_hash,
        }
    ]
    if upstream is not None:
        edges.append(
            {
                "input_role": "UPSTREAM_STAGE_OUTPUT",
                "source_manifest_type": f"StageOutputManifest/{upstream.stage_type}",
                "source_identity_ref": upstream.output_manifest_id,
                "source_contract_version": f"{upstream.stage_contract_version}/output",
                "consumed_semantic_hash": upstream.output_set_hash,
                "upstream_stage_execution_id": upstream.stage_execution_id,
            }
        )
    input_manifest = _manifest(
        runtime,
        f"manifest:input:{execution_id}",
        f"StageInputManifest/{stage_type}",
        f"{contract}/input",
        members=edges,
    )
    return runtime.create_stage_execution(
        stage_execution_id=execution_id,
        context_id=context_id,
        stage_type=stage_type,
        input_manifest_id=input_manifest.manifest_id,
        configuration_manifest_id=config.manifest_id,
        input_edges=edges,
        created_by="phase-1a-test",
        creation_reason="isolated execution",
        supersedes_stage_execution_id=supersedes,
    )


def _finish(
    runtime: RuntimePersistence,
    execution: RuntimeStageExecution,
    *,
    output_count: int = 0,
    suffix: str = "1",
):
    now = _now()
    attempt = runtime.claim_attempt(
        attempt_id=f"attempt:{execution.stage_execution_id}:{suffix}",
        stage_execution_id=execution.stage_execution_id,
        trigger_actor="phase-1a-test",
        trigger_reason="complete",
        executor_identity="isolated-worker",
        owner_id=f"owner:{suffix}",
        lease_expires_at=now + timedelta(minutes=5),
        now=now,
    )
    members = [{"ref": f"member:{index}"} for index in range(output_count)]
    output = _manifest(
        runtime,
        f"manifest:output:{execution.stage_execution_id}:{suffix}",
        f"StageOutputManifest/{execution.stage_type}",
        f"{execution.stage_contract_version}/output",
        members=members,
    )
    assert runtime.publish_success(attempt_id=attempt.attempt_id, output_manifest_id=output.manifest_id)
    return output, attempt


def test_migration_from_clean_isolated_database_has_all_constraints(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'clean.db'}")
    with engine.begin() as connection:
        _apply_migration(connection)
        assert RUNTIME_TABLES <= set(inspect(connection).get_table_names())
        checks = inspect(connection).get_check_constraints("runtime_stage_executions")
        assert {item["name"] for item in checks} >= {
            "ck_runtime_stage_compute_outcome",
            "ck_runtime_stage_output_publication",
        }
    engine.dispose()


def test_same_fingerprint_allows_independent_context_ids_and_root_is_immutable(session: Session) -> None:
    runtime = RuntimePersistence(session)
    fingerprint = semantic_hash({"equivalent": True})
    _context(runtime, "context:a", fingerprint=fingerprint)
    _context(runtime, "context:b", fingerprint=fingerprint)
    session.commit()

    assert session.scalar(
        select(RuntimeAnalysisContext).where(RuntimeAnalysisContext.context_fingerprint == fingerprint)
    ) is not None
    assert len(
        session.scalars(
            select(RuntimeAnalysisContext).where(RuntimeAnalysisContext.context_fingerprint == fingerprint)
        ).all()
    ) == 2
    with pytest.raises(DatabaseError):
        session.execute(
            text(
                "UPDATE runtime_analysis_contexts SET root_manifest_hash=:hash "
                "WHERE context_id='context:a'"
            ),
            {"hash": "0" * 64},
        )
        session.commit()
    session.rollback()


def test_zero_output_success_retry_history_and_successful_immutability(session: Session) -> None:
    runtime = RuntimePersistence(session)
    _context(runtime, "context:retry")
    execution = _stage(runtime, "execution:retry", "context:retry")
    now = _now()
    first = runtime.claim_attempt(
        attempt_id="attempt:retry:1",
        stage_execution_id=execution.stage_execution_id,
        trigger_actor="tester",
        trigger_reason="first",
        executor_identity="worker",
        owner_id="owner:1",
        lease_expires_at=now + timedelta(minutes=1),
        now=now,
    )
    runtime.record_attempt_failure(
        attempt_id=first.attempt_id,
        retryable=True,
        error_code="TEMPORARY",
        error_detail="retry",
    )
    output, second = _finish(runtime, execution, output_count=0, suffix="2")
    session.commit()

    session.refresh(execution)
    assert execution.compute_outcome == "SUCCEEDED"
    assert execution.output_count == 0
    assert execution.output_set_hash == output.canonical_hash
    assert execution.completion_attempt_id == second.attempt_id
    assert [attempt.attempt_no for attempt in runtime.attempts_for_execution(execution.stage_execution_id)] == [1, 2]
    assert session.get(RuntimeStageAttemptResult, first.attempt_id).attempt_outcome == "FAILED_RETRYABLE"
    with pytest.raises(DatabaseError):
        session.execute(
            text(
                "UPDATE runtime_stage_executions SET output_set_hash=:hash "
                "WHERE stage_execution_id='execution:retry'"
            ),
            {"hash": "0" * 64},
        )
        session.commit()
    session.rollback()


def test_fencing_rejects_late_attempt_and_allows_one_success(session: Session) -> None:
    runtime = RuntimePersistence(session)
    _context(runtime, "context:fence")
    execution = _stage(runtime, "execution:fence", "context:fence")
    now = _now()
    attempt_a = runtime.claim_attempt(
        attempt_id="attempt:fence:a",
        stage_execution_id=execution.stage_execution_id,
        trigger_actor="tester",
        trigger_reason="generation-4-shape",
        executor_identity="worker-a",
        owner_id="owner-a",
        lease_expires_at=now - timedelta(seconds=1),
        now=now - timedelta(minutes=1),
    )
    attempt_b = runtime.claim_attempt(
        attempt_id="attempt:fence:b",
        stage_execution_id=execution.stage_execution_id,
        trigger_actor="tester",
        trigger_reason="lease reclaim",
        executor_identity="worker-b",
        owner_id="owner-b",
        lease_expires_at=now + timedelta(minutes=5),
        now=now,
    )
    output_b = _manifest(
        runtime,
        "manifest:output:fence:b",
        "StageOutputManifest/ANSWER_SEMANTIC",
        "runtime_stage.answer_semantic.v1/output",
    )
    output_a = _manifest(
        runtime,
        "manifest:output:fence:a",
        "StageOutputManifest/ANSWER_SEMANTIC",
        "runtime_stage.answer_semantic.v1/output",
    )
    assert runtime.publish_success(attempt_id=attempt_b.attempt_id, output_manifest_id=output_b.manifest_id)
    assert not runtime.publish_success(attempt_id=attempt_a.attempt_id, output_manifest_id=output_a.manifest_id)
    session.commit()

    session.refresh(execution)
    assert execution.output_manifest_id == output_b.manifest_id
    results = session.scalars(select(RuntimeStageAttemptResult)).all()
    assert [item.attempt_outcome for item in results].count("SUCCEEDED") == 1
    assert session.get(RuntimeStageAttemptResult, attempt_a.attempt_id).attempt_outcome == (
        "LATE_OR_SUPERSEDED_ATTEMPT"
    )


def test_review_is_append_only_linear_and_rejects_branch_or_cross_target(session: Session) -> None:
    runtime = RuntimePersistence(session)
    _context(runtime, "context:review")
    execution = _stage(runtime, "execution:review", "context:review")
    output, _ = _finish(runtime, execution)
    target = runtime.create_review_target(
        review_target_id="review-target:one",
        target_type="STAGE_OUTPUT",
        context_id="context:review",
        stage_execution_id=execution.stage_execution_id,
        target_identity_ref=execution.stage_execution_id,
        target_version=execution.stage_contract_version,
        reviewed_manifest_id=output.manifest_id,
        review_contract_version="runtime_review.answer_semantic.v1",
    )
    r1 = runtime.append_review_decision(
        review_id="review:1",
        review_target_id=target.review_target_id,
        decision="CONFIRM",
        actor="reviewer",
        review_note="confirmed",
        expected_state_version=0,
        supersedes_review_id=None,
    )
    r2 = runtime.append_review_decision(
        review_id="review:2",
        review_target_id=target.review_target_id,
        decision="REOPEN",
        actor="reviewer",
        review_note="reopen",
        expected_state_version=1,
        supersedes_review_id=r1.review_id,
    )
    with pytest.raises(ReviewConflict):
        runtime.append_review_decision(
            review_id="review:branch",
            review_target_id=target.review_target_id,
            decision="REJECT",
            actor="reviewer",
            review_note="stale branch",
            expected_state_version=1,
            supersedes_review_id=r1.review_id,
        )
    target_two = runtime.create_review_target(
        review_target_id="review-target:two",
        target_type="STAGE_OUTPUT",
        context_id="context:review",
        stage_execution_id=execution.stage_execution_id,
        target_identity_ref="different-review-unit",
        target_version=execution.stage_contract_version,
        reviewed_manifest_id=output.manifest_id,
        review_contract_version="runtime_review.answer_semantic.v1",
    )
    with pytest.raises(ReviewConflict):
        runtime.append_review_decision(
            review_id="review:cross-target",
            review_target_id=target_two.review_target_id,
            decision="CONFIRM",
            actor="reviewer",
            review_note="invalid",
            expected_state_version=0,
            supersedes_review_id=r2.review_id,
        )
    session.commit()

    assert session.scalar(select(RuntimeStageReviewDecision).where(RuntimeStageReviewDecision.review_id == "review:1"))
    assert execution.output_set_hash == output.canonical_hash
    with pytest.raises(DatabaseError):
        session.execute(text("UPDATE runtime_stage_review_decisions SET decision='REJECT' WHERE review_id='review:1'"))
        session.commit()
    session.rollback()


def test_current_pointer_is_explicit_cas_audited_and_track_isolated(session: Session) -> None:
    runtime = RuntimePersistence(session)
    _context(runtime, "context:production", track="PRODUCTION")
    _context(runtime, "context:shadow", track="SHADOW")
    production = runtime.transition_current_context(
        project_id=3,
        prompt_id=19,
        workflow_track="PRODUCTION",
        new_context_id="context:production",
        expected_state_version=0,
        actor="owner",
        reason="explicit production selection",
    )
    with pytest.raises(ConcurrencyConflict):
        runtime.transition_current_context(
            project_id=3,
            prompt_id=19,
            workflow_track="PRODUCTION",
            new_context_id=None,
            expected_state_version=0,
            actor="stale-writer",
            reason="stale",
        )
    with pytest.raises(InvalidTransition):
        runtime.transition_current_context(
            project_id=3,
            prompt_id=19,
            workflow_track="PRODUCTION",
            new_context_id="context:shadow",
            expected_state_version=1,
            actor="owner",
            reason="track leak",
        )
    shadow = runtime.transition_current_context(
        project_id=3,
        prompt_id=19,
        workflow_track="SHADOW",
        new_context_id="context:shadow",
        expected_state_version=0,
        actor="owner",
        reason="explicit shadow selection",
    )
    session.commit()

    assert production.pointer_id != shadow.pointer_id
    events = session.scalars(select(RuntimeCurrentContextPointerEvent)).all()
    assert len(events) == 2


def test_recompute_is_new_execution_without_auto_promotion_and_selection_uses_cas(session: Session) -> None:
    runtime = RuntimePersistence(session)
    _context(runtime, "context:selection")
    first = _stage(runtime, "execution:selected:1", "context:selection")
    _finish(runtime, first, suffix="first")
    selection = runtime.transition_stage_selection(
        context_id="context:selection",
        stage_type="ANSWER_SEMANTIC",
        new_stage_execution_id=first.stage_execution_id,
        expected_state_version=0,
        actor="owner",
        reason="initial selection",
    )
    second = _stage(
        runtime,
        "execution:selected:2",
        "context:selection",
        supersedes=first.stage_execution_id,
    )
    _finish(runtime, second, suffix="second")
    session.flush()
    session.refresh(selection)
    assert selection.selected_stage_execution_id == first.stage_execution_id
    with pytest.raises(ConcurrencyConflict):
        runtime.transition_stage_selection(
            context_id="context:selection",
            stage_type="ANSWER_SEMANTIC",
            new_stage_execution_id=second.stage_execution_id,
            expected_state_version=0,
            actor="stale-writer",
            reason="stale",
        )
    runtime.transition_stage_selection(
        context_id="context:selection",
        stage_type="ANSWER_SEMANTIC",
        new_stage_execution_id=second.stage_execution_id,
        expected_state_version=1,
        actor="owner",
        reason="explicit promotion",
    )
    session.commit()
    selected = session.scalar(
        select(RuntimeContextStageSelection).where(
            RuntimeContextStageSelection.context_id == "context:selection"
        )
    )
    assert selected.selected_stage_execution_id == second.stage_execution_id


def test_stale_is_derived_from_exact_dependency_selection_and_history_is_retained(session: Session) -> None:
    runtime = RuntimePersistence(session)
    _context(runtime, "context:validity")
    upstream_one = _stage(runtime, "execution:upstream:1", "context:validity")
    upstream_one_output, _ = _finish(runtime, upstream_one, suffix="upstream-one")
    runtime.register_output_validity_target(
        target_type="STAGE_OUTPUT",
        context_id="context:validity",
        stage_execution_id=upstream_one.stage_execution_id,
        manifest_id=upstream_one_output.manifest_id,
        manifest_hash=upstream_one_output.canonical_hash,
    )
    runtime.transition_stage_selection(
        context_id="context:validity",
        stage_type="ANSWER_SEMANTIC",
        new_stage_execution_id=upstream_one.stage_execution_id,
        expected_state_version=0,
        actor="owner",
        reason="select dependency",
    )
    dependent = _stage(
        runtime,
        "execution:dependent",
        "context:validity",
        stage_type="BINDING",
        upstream=upstream_one,
    )
    dependent_output, _ = _finish(runtime, dependent, suffix="dependent")
    assert runtime.stage_eligibility(dependent.stage_execution_id) == "ELIGIBLE"

    runtime.transition_validity(
        target_type="STAGE_OUTPUT",
        target_ref=upstream_one_output.manifest_id,
        target_hash=upstream_one_output.canonical_hash,
        decision="INVALIDATE",
        expected_state_version=0,
        reason_code="OUTPUT_INVALIDATION",
        reason_note="exact output invalidated",
        actor="authorized-owner",
        source="phase-1a-test",
        authorization_evidence={"authorized": True},
    )
    assert runtime.stage_eligibility(dependent.stage_execution_id) == "STALE"
    runtime.transition_validity(
        target_type="STAGE_OUTPUT",
        target_ref=upstream_one_output.manifest_id,
        target_hash=upstream_one_output.canonical_hash,
        decision="REACTIVATE",
        expected_state_version=1,
        reason_code="OUTPUT_REACTIVATION",
        reason_note="exact output restored",
        actor="authorized-owner",
        source="phase-1a-test",
        authorization_evidence={"authorized": True},
        compatibility_validation={"output_exists": True, "contract_allowed": True},
    )
    assert runtime.stage_eligibility(dependent.stage_execution_id) == "ELIGIBLE"

    upstream_two = _stage(
        runtime,
        "execution:upstream:2",
        "context:validity",
        supersedes=upstream_one.stage_execution_id,
    )
    _finish(runtime, upstream_two, suffix="upstream-two")
    runtime.transition_stage_selection(
        context_id="context:validity",
        stage_type="ANSWER_SEMANTIC",
        new_stage_execution_id=upstream_two.stage_execution_id,
        expected_state_version=1,
        actor="owner",
        reason="replace dependency branch",
    )
    assert runtime.stage_eligibility(dependent.stage_execution_id) == "STALE"
    assert session.get(RuntimeManifest, dependent_output.manifest_id) is not None

    runtime.transition_stage_selection(
        context_id="context:validity",
        stage_type="ANSWER_SEMANTIC",
        new_stage_execution_id=upstream_one.stage_execution_id,
        expected_state_version=2,
        actor="owner",
        reason="explicit rollback",
    )
    assert runtime.stage_eligibility(dependent.stage_execution_id) == "ELIGIBLE"

    runtime.transition_validity(
        target_type="STAGE_EXECUTION",
        target_ref=dependent.stage_execution_id,
        decision="INVALIDATE",
        expected_state_version=0,
        reason_code="AUDIT_INVALIDATION",
        reason_note="explicit test invalidation",
        actor="authorized-owner",
        source="phase-1a-test",
        authorization_evidence={"authorized": True},
    )
    assert runtime.stage_eligibility(dependent.stage_execution_id) == "INVALIDATED"
    runtime.transition_validity(
        target_type="STAGE_EXECUTION",
        target_ref=dependent.stage_execution_id,
        decision="REACTIVATE",
        expected_state_version=1,
        reason_code="AUDIT_REACTIVATION",
        reason_note="reason resolved",
        actor="authorized-owner",
        source="phase-1a-test",
        authorization_evidence={"authorized": True},
        compatibility_validation={"dependencies_selected": True, "output_exists": True},
    )
    session.commit()

    assert runtime.stage_eligibility(dependent.stage_execution_id) == "ELIGIBLE"
    history = runtime.validity_history("STAGE_EXECUTION", dependent.stage_execution_id)
    assert [event.decision for event in history] == ["INVALIDATE", "REACTIVATE"]
    assert session.scalars(select(RuntimeValidityEvent)).all()
    with pytest.raises(IntegrityError):
        session.delete(dependent_output)
        session.commit()
    session.rollback()
