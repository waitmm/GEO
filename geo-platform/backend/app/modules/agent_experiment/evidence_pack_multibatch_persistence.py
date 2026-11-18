"""Offline persistence for the frozen multi-batch shadow contract.

This module accepts replay/fake results only.  It never invokes a provider and
never creates AgentResultVersion or DraftArtifactVersion rows.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models import (
    AgentExperimentRun, AgentMultiBatchAggregateCandidate, AgentMultiBatchAttempt,
    AgentMultiBatchPlan, AgentMultiBatchResult,
)
from app.modules.single_prompt_v2.delivery_text import digest
from app.services.serialization import dumps, loads

from .evidence_pack_multibatch_shadow import (
    ShadowContractError, build_shadow_aggregate_input, initialize_shadow_execution,
    validate_shadow_batch_result, validate_shadow_capacity_plan,
)


def _id(prefix: str, *parts: str) -> str:
    return f"{prefix}:{digest(list(parts))[:48]}"


def create_offline_multibatch_plan(
    db: Session, *, agent_run_id: str, plan: dict[str, Any],
    budget_reservation: dict[str, Any], idempotency_key: str,
) -> AgentMultiBatchPlan:
    """Persist exact plan/reservation identity before any replay attempt."""
    checked = validate_shadow_capacity_plan(plan)
    initialize_shadow_execution(checked, budget_reservation=budget_reservation)
    run = db.query(AgentExperimentRun).filter_by(run_id=agent_run_id).one_or_none()
    if run is None:
        raise ShadowContractError("MULTIBATCH_AGENT_RUN_NOT_FOUND")
    if run.input_scope_hash != checked["frozen_scope_hash"]:
        raise ShadowContractError("MULTIBATCH_AGENT_RUN_SCOPE_MISMATCH")
    existing = db.query(AgentMultiBatchPlan).filter_by(
        agent_run_id=agent_run_id, idempotency_key=idempotency_key,
    ).one_or_none()
    if existing is not None:
        if (
            existing.plan_hash != checked["plan_hash"]
            or existing.reservation_identity_hash
            != budget_reservation["reservation_identity_hash"]
        ):
            raise ShadowContractError("MULTIBATCH_IDEMPOTENCY_CONFLICT")
        return existing
    row = AgentMultiBatchPlan(
        plan_id=_id("mbplan", agent_run_id, checked["plan_hash"]),
        agent_run_id=agent_run_id,
        frozen_scope_hash=checked["frozen_scope_hash"],
        plan_hash=checked["plan_hash"],
        reservation_identity_hash=budget_reservation["reservation_identity_hash"],
        idempotency_key=idempotency_key,
        plan_json=dumps(checked),
        reservation_json=dumps(budget_reservation),
        max_attempts_per_batch=budget_reservation["max_attempts_per_batch"],
        status="PLANNED",
    )
    db.add(row)
    db.flush()
    return row


def _plan(db: Session, row: AgentMultiBatchPlan) -> dict[str, Any]:
    plan = loads(row.plan_json, {})
    checked = validate_shadow_capacity_plan(plan)
    if checked["plan_hash"] != row.plan_hash or checked["frozen_scope_hash"] != row.frozen_scope_hash:
        raise ShadowContractError("MULTIBATCH_PERSISTED_PLAN_HASH_MISMATCH")
    reservation = loads(row.reservation_json, {})
    initialize_shadow_execution(checked, budget_reservation=reservation)
    if reservation.get("reservation_identity_hash") != row.reservation_identity_hash:
        raise ShadowContractError("MULTIBATCH_PERSISTED_RESERVATION_HASH_MISMATCH")
    run = db.query(AgentExperimentRun).filter_by(run_id=row.agent_run_id).one_or_none()
    if run is None or run.input_scope_hash != row.frozen_scope_hash:
        raise ShadowContractError("MULTIBATCH_PERSISTED_AGENT_RUN_SCOPE_MISMATCH")
    return checked


def recover_offline_multibatch_state(db: Session, *, plan_id: str) -> dict[str, Any]:
    row = db.query(AgentMultiBatchPlan).filter_by(plan_id=plan_id).one()
    plan = _plan(db, row)
    attempts = db.query(AgentMultiBatchAttempt).filter_by(plan_id=plan_id).order_by(
        AgentMultiBatchAttempt.id,
    ).all()
    results = db.query(AgentMultiBatchResult).filter_by(plan_id=plan_id).all()
    result_by_attempt = {result.attempt_id: result for result in results}
    for attempt in attempts:
        payload = loads(attempt.payload_json, {})
        if digest(payload) != attempt.payload_hash:
            raise ShadowContractError("MULTIBATCH_PERSISTED_ATTEMPT_PAYLOAD_HASH_MISMATCH")
        if attempt.status == "SUCCESS":
            result = result_by_attempt.get(attempt.attempt_id)
            if (
                result is None
                or attempt.result_hash != result.result_hash
                or result.batch_hash != attempt.batch_hash
                or loads(result.payload_json, {}) != payload
            ):
                raise ShadowContractError("MULTIBATCH_PERSISTED_ATTEMPT_RESULT_BINDING_MISMATCH")
        elif attempt.status != "FAILED" or payload != {"failure_code": attempt.failure_code}:
            raise ShadowContractError("MULTIBATCH_PERSISTED_ATTEMPT_PAYLOAD_INVALID")
    for result in results:
        payload = loads(result.payload_json, {})
        checked = validate_shadow_batch_result(plan, payload)
        attempt = next(
            (item for item in attempts if item.attempt_id == result.attempt_id), None,
        )
        if (
            attempt is None
            or checked.status != "SUCCESS"
            or checked.result_hash != result.result_hash
            or checked.batch_hash != result.batch_hash
            or checked.batch_hash != attempt.batch_hash
            or checked.batch_number != attempt.batch_number
            or checked.attempt_number != attempt.attempt_number
        ):
            raise ShadowContractError("MULTIBATCH_PERSISTED_RESULT_HASH_MISMATCH")
    candidate = db.query(AgentMultiBatchAggregateCandidate).filter_by(plan_id=plan_id).one_or_none()
    if candidate is not None:
        payload = loads(candidate.payload_json, {})
        ordered = loads(candidate.ordered_batch_result_hashes_json, [])
        results_by_batch = {
            result.batch_hash: loads(result.payload_json, {}) for result in results
        }
        try:
            expected_results = [
                results_by_batch[batch["batch_hash"]] for batch in plan["batches"]
            ]
        except KeyError as exc:
            raise ShadowContractError("MULTIBATCH_PERSISTED_AGGREGATE_RESULT_MISSING") from exc
        expected = build_shadow_aggregate_input(plan, expected_results)
        if (
            digest(payload) != candidate.payload_hash
            or payload.get("aggregate_input_hash") != candidate.aggregate_input_hash
            or payload.get("batch_result_hashes") != ordered
            or payload != expected
            or len(results_by_batch) != len(plan["batches"])
        ):
            raise ShadowContractError("MULTIBATCH_PERSISTED_AGGREGATE_HASH_MISMATCH")
    return {
        "plan_id": row.plan_id,
        "plan_hash": row.plan_hash,
        "frozen_scope_hash": row.frozen_scope_hash,
        "reservation_identity_hash": row.reservation_identity_hash,
        "status": row.status,
        "cancel_requested": row.status == "CANCEL_REQUESTED",
        "attempt_count": len(attempts),
        "successful_batch_hashes": sorted(result.batch_hash for result in results),
        "required_batch_hashes": [batch["batch_hash"] for batch in plan["batches"]],
        "external_calls": 0,
    }


def resume_offline_multibatch_plan(db: Session, *, plan_id: str) -> AgentMultiBatchPlan:
    changed = db.query(AgentMultiBatchPlan).filter(
        AgentMultiBatchPlan.plan_id == plan_id,
        AgentMultiBatchPlan.status == "FAILED_RECOVERABLE",
    ).update({
        AgentMultiBatchPlan.status: "RUNNING",
        AgentMultiBatchPlan.revision: AgentMultiBatchPlan.revision + 1,
    }, synchronize_session=False)
    if changed != 1:
        raise ShadowContractError("MULTIBATCH_PLAN_NOT_RECOVERABLE")
    db.flush()
    return db.query(AgentMultiBatchPlan).populate_existing().filter_by(plan_id=plan_id).one()


def request_offline_multibatch_cancel(db: Session, *, plan_id: str) -> AgentMultiBatchPlan:
    changed = db.query(AgentMultiBatchPlan).filter(
        AgentMultiBatchPlan.plan_id == plan_id,
        AgentMultiBatchPlan.status.in_({
            "PLANNED", "RUNNING", "FAILED_RECOVERABLE",
            "READY_FOR_SHADOW_AGGREGATE",
        }),
    ).update({
        AgentMultiBatchPlan.status: "CANCEL_REQUESTED",
        AgentMultiBatchPlan.cancel_requested_at: datetime.utcnow(),
        AgentMultiBatchPlan.revision: AgentMultiBatchPlan.revision + 1,
    }, synchronize_session=False)
    if changed != 1:
        raise ShadowContractError("MULTIBATCH_PLAN_ALREADY_TERMINAL")
    db.flush()
    return db.query(AgentMultiBatchPlan).populate_existing().filter_by(plan_id=plan_id).one()


def acknowledge_offline_multibatch_cancel(
    db: Session, *, plan_id: str,
) -> AgentMultiBatchPlan:
    changed = db.query(AgentMultiBatchPlan).filter(
        AgentMultiBatchPlan.plan_id == plan_id,
        AgentMultiBatchPlan.status == "CANCEL_REQUESTED",
    ).update({
        AgentMultiBatchPlan.status: "CANCELLED",
        AgentMultiBatchPlan.revision: AgentMultiBatchPlan.revision + 1,
    }, synchronize_session=False)
    if changed != 1:
        raise ShadowContractError("MULTIBATCH_CANCEL_NOT_REQUESTED")
    db.flush()
    return db.query(AgentMultiBatchPlan).populate_existing().filter_by(plan_id=plan_id).one()


def record_offline_replay_attempt(
    db: Session, *, plan_id: str, batch_hash: str, idempotency_key: str,
    outcome: str, replay_result: dict[str, Any] | None = None,
    failure_code: str = "",
) -> AgentMultiBatchAttempt:
    """Record one fake/replay attempt; no external provider is reachable here."""
    row = db.query(AgentMultiBatchPlan).filter_by(plan_id=plan_id).one()
    plan = _plan(db, row)
    batch = next((item for item in plan["batches"] if item["batch_hash"] == batch_hash), None)
    if batch is None:
        raise ShadowContractError("MULTIBATCH_BATCH_UNKNOWN")
    existing = db.query(AgentMultiBatchAttempt).filter_by(
        plan_id=plan_id, idempotency_key=idempotency_key,
    ).one_or_none()
    if existing is not None:
        incoming_payload: dict[str, Any]
        incoming_result_hash: str | None
        if outcome == "SUCCESS" and replay_result is not None:
            incoming = validate_shadow_batch_result(plan, replay_result)
            if (
                incoming.status != "SUCCESS"
                or incoming.batch_hash != existing.batch_hash
                or incoming.batch_number != existing.batch_number
                or incoming.attempt_number != existing.attempt_number
            ):
                raise ShadowContractError("MULTIBATCH_ATTEMPT_IDEMPOTENCY_PAYLOAD_INVALID")
            incoming_payload = incoming.model_dump(mode="json")
            incoming_result_hash = incoming.result_hash
        elif outcome == "FAILED" and failure_code:
            incoming_payload = {"failure_code": failure_code}
            incoming_result_hash = None
        else:
            raise ShadowContractError("MULTIBATCH_ATTEMPT_IDEMPOTENCY_PAYLOAD_INVALID")
        if (
            existing.batch_hash != batch_hash or existing.status != outcome
            or existing.payload_hash != digest(incoming_payload)
            or existing.result_hash != incoming_result_hash
        ):
            raise ShadowContractError("MULTIBATCH_ATTEMPT_IDEMPOTENCY_CONFLICT")
        return existing
    if row.status in {"CANCEL_REQUESTED", "CANCELLED", "FAILED_TERMINAL",
                      "AGGREGATE_CANDIDATE_READY"}:
        raise ShadowContractError("MULTIBATCH_PLAN_BLOCKS_ATTEMPT")
    if row.status == "FAILED_RECOVERABLE":
        raise ShadowContractError("MULTIBATCH_RETRY_REQUIRES_RESUME")
    if db.query(AgentMultiBatchResult).filter_by(plan_id=plan_id, batch_hash=batch_hash).count():
        raise ShadowContractError("MULTIBATCH_SUCCESS_IMMUTABLE")
    count = db.query(AgentMultiBatchAttempt).filter_by(
        plan_id=plan_id, batch_hash=batch_hash,
    ).count()
    if count >= row.max_attempts_per_batch:
        raise ShadowContractError("MULTIBATCH_MAX_ATTEMPTS_EXHAUSTED")
    attempt_number = count + 1
    if outcome == "SUCCESS":
        if replay_result is None:
            raise ShadowContractError("MULTIBATCH_SUCCESS_REQUIRES_REPLAY_RESULT")
        checked_result = validate_shadow_batch_result(plan, replay_result)
        if (
            checked_result.status != "SUCCESS"
            or checked_result.batch_hash != batch_hash
            or checked_result.batch_number != batch["batch_number"]
            or checked_result.attempt_number != attempt_number
        ):
            raise ShadowContractError("MULTIBATCH_REPLAY_BATCH_MISMATCH")
        payload = checked_result.model_dump(mode="json")
        result_hash = checked_result.result_hash
        failure_code = ""
    elif outcome == "FAILED":
        if not failure_code:
            raise ShadowContractError("MULTIBATCH_FAILURE_REQUIRES_CODE")
        payload, result_hash = {"failure_code": failure_code}, None
    else:
        raise ShadowContractError("MULTIBATCH_ATTEMPT_OUTCOME_INVALID")
    claimed = db.query(AgentMultiBatchPlan).filter(
        AgentMultiBatchPlan.plan_id == plan_id,
        AgentMultiBatchPlan.status.in_({"PLANNED", "RUNNING"}),
    ).update({
        AgentMultiBatchPlan.status: "RUNNING",
        AgentMultiBatchPlan.revision: AgentMultiBatchPlan.revision + 1,
    }, synchronize_session=False)
    if claimed != 1:
        fresh_status = db.query(AgentMultiBatchPlan.status).filter_by(
            plan_id=plan_id,
        ).scalar()
        if fresh_status == "FAILED_RECOVERABLE":
            raise ShadowContractError("MULTIBATCH_RETRY_REQUIRES_RESUME")
        raise ShadowContractError("MULTIBATCH_PLAN_BLOCKS_ATTEMPT")
    db.refresh(row)
    attempt = AgentMultiBatchAttempt(
        attempt_id=_id("mbattempt", plan_id, batch_hash, str(attempt_number)),
        plan_id=plan_id, batch_hash=batch_hash, batch_number=batch["batch_number"],
        attempt_number=attempt_number, idempotency_key=idempotency_key,
        status=outcome, failure_code=failure_code, result_hash=result_hash,
        payload_json=dumps(payload), payload_hash=digest(payload),
    )
    try:
        with db.begin_nested():
            db.add(attempt)
            db.flush()
    except IntegrityError as exc:
        concurrent = db.query(AgentMultiBatchAttempt).filter_by(
            plan_id=plan_id, idempotency_key=idempotency_key,
        ).one_or_none()
        if concurrent is not None and (
            concurrent.batch_hash == batch_hash and concurrent.status == outcome
            and concurrent.payload_hash == digest(payload)
            and concurrent.result_hash == result_hash
        ):
            return concurrent
        raise ShadowContractError("MULTIBATCH_ATTEMPT_CONCURRENT_CONFLICT") from exc
    if outcome == "SUCCESS":
        db.add(AgentMultiBatchResult(
            result_id=_id("mbresult", plan_id, batch_hash, result_hash),
            plan_id=plan_id, attempt_id=attempt.attempt_id, batch_hash=batch_hash,
            result_hash=result_hash, payload_json=dumps(payload),
        ))
        db.flush()
    results = db.query(AgentMultiBatchResult).filter_by(plan_id=plan_id).all()
    successful = {item.batch_hash for item in results}
    result_count = len(results)
    if result_count == len(plan["batches"]):
        row.status = "READY_FOR_SHADOW_AGGREGATE"
    elif any(
        batch["batch_hash"] not in successful
        and db.query(AgentMultiBatchAttempt).filter_by(
            plan_id=plan_id, batch_hash=batch["batch_hash"], status="FAILED",
        ).count() >= row.max_attempts_per_batch
        for batch in plan["batches"]
    ):
        row.status = "FAILED_TERMINAL"
    elif outcome == "FAILED":
        row.status = "FAILED_RECOVERABLE"
    else:
        row.status = "RUNNING"
    row.revision += 1
    db.flush()
    return attempt


def persist_offline_aggregate_candidate(
    db: Session, *, plan_id: str,
) -> AgentMultiBatchAggregateCandidate:
    row = db.query(AgentMultiBatchPlan).filter_by(plan_id=plan_id).one()
    existing = db.query(AgentMultiBatchAggregateCandidate).filter_by(plan_id=plan_id).one_or_none()
    if existing is not None:
        recover_offline_multibatch_state(db, plan_id=plan_id)
        return existing
    with db.begin_nested():
        claimed = db.query(AgentMultiBatchPlan).filter(
            AgentMultiBatchPlan.plan_id == plan_id,
            AgentMultiBatchPlan.status == "READY_FOR_SHADOW_AGGREGATE",
        ).update({
            AgentMultiBatchPlan.status: "AGGREGATE_CANDIDATE_READY",
            AgentMultiBatchPlan.revision: AgentMultiBatchPlan.revision + 1,
        }, synchronize_session=False)
        if claimed != 1:
            raise ShadowContractError("MULTIBATCH_AGGREGATE_NOT_READY")
        db.refresh(row)
        plan = _plan(db, row)
        persisted = db.query(AgentMultiBatchResult).filter_by(plan_id=plan_id).all()
        by_batch = {item.batch_hash: loads(item.payload_json, {}) for item in persisted}
        try:
            results = [by_batch[batch["batch_hash"]] for batch in plan["batches"]]
        except KeyError as exc:
            raise ShadowContractError("MULTIBATCH_AGGREGATE_RESULT_MISSING") from exc
        if len(by_batch) != len(plan["batches"]):
            raise ShadowContractError("MULTIBATCH_AGGREGATE_RESULT_SET_MISMATCH")
        aggregate = build_shadow_aggregate_input(plan, results)
        candidate = AgentMultiBatchAggregateCandidate(
            candidate_id=_id("mbaggregate", plan_id, aggregate["aggregate_input_hash"]),
            plan_id=plan_id,
            aggregate_input_hash=aggregate["aggregate_input_hash"],
            ordered_batch_result_hashes_json=dumps(aggregate["batch_result_hashes"]),
            payload_json=dumps(aggregate), payload_hash=digest(aggregate),
            status="SHADOW_CANDIDATE_ONLY",
        )
        db.add(candidate)
        db.flush()
    return candidate
