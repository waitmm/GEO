"""Offline-only aggregate replay candidate execution.

This module has no provider/model import and cannot create AgentResultVersion or
Draft rows.  It consumes only the validated, persisted shadow aggregate input
from the frozen multi-batch contract.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AgentMultiBatchAggregateCandidate, AgentMultiBatchAggregateReplayAttempt,
    AgentMultiBatchAggregateReplayResultCandidate, AgentMultiBatchPlan,
)
from app.modules.single_prompt_v2.delivery_text import digest
from app.services.serialization import dumps, loads

from .evidence_pack import EVIDENCE_PACK_VALIDATION_CONTRACT
from .evidence_pack_multibatch_persistence import recover_offline_multibatch_state
from .evidence_pack_multibatch_shadow import ShadowContractError


MULTIBATCH_EXECUTION_CANDIDATE = "geo.evidence-pack.multibatch-execution.candidate.v1"
_VALIDATION_STATUSES = {"PASS", "FAIL"}
_PROTECTED_REPORT_BINDING_FIELDS = {
    "validation_contract", "status", "raw_response_hash", "protected_fixture_id",
    "frozen_scope_hash", "plan_hash", "aggregate_input_hash",
    "ordered_batch_result_hashes",
}


def _id(prefix: str, *parts: str) -> str:
    return f"{prefix}:{digest(list(parts))[:48]}"


def seal_protected_aggregate_replay(
    *, raw_response: str, validation_status: str,
    validation_report: dict[str, Any],
) -> dict[str, Any]:
    """Seal a protected fake/replay fixture; this does not run Validation v6."""
    if validation_status not in _VALIDATION_STATUSES:
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_VALIDATION_STATUS_INVALID")
    if not isinstance(validation_report, dict):
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_VALIDATION_REPORT_INVALID")
    missing = _PROTECTED_REPORT_BINDING_FIELDS - set(validation_report)
    if missing:
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_REPORT_BINDING_MISSING")
    if (
        validation_report.get("validation_contract") != EVIDENCE_PACK_VALIDATION_CONTRACT
        or validation_report.get("status") != validation_status
        or validation_report.get("raw_response_hash") != digest(raw_response)
        or not str(validation_report.get("protected_fixture_id") or "").strip()
    ):
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_REPORT_BINDING_INVALID")
    body = {
        "raw_response": raw_response,
        "raw_response_hash": digest(raw_response),
        "validation_profile": EVIDENCE_PACK_VALIDATION_CONTRACT,
        "validation_status": validation_status,
        "validation_report": deepcopy(validation_report),
        "validation_report_hash": digest(validation_report),
        "validation_reexecution": "NOT_REEXECUTED_PROTECTED_OFFLINE_REPLAY",
    }
    body["replay_bundle_hash"] = digest(body)
    return body


def _validate_replay_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    required = {
        "raw_response", "raw_response_hash", "validation_profile",
        "validation_status", "validation_report", "validation_report_hash",
        "validation_reexecution", "replay_bundle_hash",
    }
    if set(bundle) != required:
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_BUNDLE_SHAPE_INVALID")
    if not isinstance(bundle["raw_response"], str):
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_RESPONSE_INVALID")
    if bundle["raw_response_hash"] != digest(bundle["raw_response"]):
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_RESPONSE_HASH_MISMATCH")
    if bundle["validation_profile"] != EVIDENCE_PACK_VALIDATION_CONTRACT:
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_VALIDATION_PROFILE_MISMATCH")
    if bundle["validation_status"] not in _VALIDATION_STATUSES:
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_VALIDATION_STATUS_INVALID")
    if not isinstance(bundle["validation_report"], dict):
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_VALIDATION_REPORT_INVALID")
    report = bundle["validation_report"]
    if _PROTECTED_REPORT_BINDING_FIELDS - set(report):
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_REPORT_BINDING_MISSING")
    if (
        report.get("validation_contract") != EVIDENCE_PACK_VALIDATION_CONTRACT
        or report.get("status") != bundle["validation_status"]
        or report.get("raw_response_hash") != bundle["raw_response_hash"]
        or not str(report.get("protected_fixture_id") or "").strip()
    ):
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_REPORT_BINDING_INVALID")
    if bundle["validation_report_hash"] != digest(bundle["validation_report"]):
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_VALIDATION_HASH_MISMATCH")
    if bundle["validation_reexecution"] != "NOT_REEXECUTED_PROTECTED_OFFLINE_REPLAY":
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_REEXECUTION_CLAIM_INVALID")
    body = deepcopy(bundle)
    bundle_hash = body.pop("replay_bundle_hash", None)
    if bundle_hash != digest(body):
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_BUNDLE_HASH_MISMATCH")
    return deepcopy(bundle)


def _load_candidate(
    db: Session, *, aggregate_candidate_id: str,
) -> tuple[AgentMultiBatchAggregateCandidate, AgentMultiBatchPlan, dict[str, Any], list[str]]:
    candidate = db.query(AgentMultiBatchAggregateCandidate).filter_by(
        candidate_id=aggregate_candidate_id,
    ).one_or_none()
    if candidate is None or candidate.status != "SHADOW_CANDIDATE_ONLY":
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_CANDIDATE_NOT_FOUND")
    recover_offline_multibatch_state(db, plan_id=candidate.plan_id)
    plan = db.query(AgentMultiBatchPlan).filter_by(plan_id=candidate.plan_id).one()
    payload = loads(candidate.payload_json, {})
    ordered = loads(candidate.ordered_batch_result_hashes_json, [])
    if (
        payload.get("status") != "READY_FOR_SHADOW_REVIEW"
        or payload.get("mode") != "SHADOW_ONLY_NO_PROVIDER_CALL_NO_AGENT_RESULT_VERSION"
        or payload.get("aggregate_input_hash") != candidate.aggregate_input_hash
        or payload.get("frozen_scope_hash") != plan.frozen_scope_hash
        or payload.get("plan_hash") != plan.plan_hash
        or payload.get("batch_result_hashes") != ordered
    ):
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_INPUT_NOT_ELIGIBLE")
    return candidate, plan, payload, ordered


def _attempt_identity(
    candidate: AgentMultiBatchAggregateCandidate, plan: AgentMultiBatchPlan,
    ordered: list[str],
) -> dict[str, Any]:
    return {
        "execution_identity": MULTIBATCH_EXECUTION_CANDIDATE,
        "aggregate_candidate_id": candidate.candidate_id,
        "plan_id": plan.plan_id,
        "frozen_scope_hash": plan.frozen_scope_hash,
        "plan_hash": plan.plan_hash,
        "aggregate_input_hash": candidate.aggregate_input_hash,
        "ordered_batch_result_hashes": ordered,
        "attempt_number": 1,
        "reserved_aggregate_calls": 1,
        "external_calls": 0,
    }


def _result_binding(
    *, candidate: AgentMultiBatchAggregateCandidate, plan: AgentMultiBatchPlan,
    ordered: list[str], bundle: dict[str, Any],
) -> dict[str, Any]:
    return {
        "execution_identity": MULTIBATCH_EXECUTION_CANDIDATE,
        "frozen_scope_hash": plan.frozen_scope_hash,
        "plan_hash": plan.plan_hash,
        "aggregate_input_hash": candidate.aggregate_input_hash,
        "ordered_batch_result_hashes": ordered,
        "aggregate_response_hash": bundle["raw_response_hash"],
        "validation_profile": bundle["validation_profile"],
        "validation_status": bundle["validation_status"],
        "validation_report_hash": bundle["validation_report_hash"],
        "formal_result_created": False,
    }


def _expected_result_status(bundle: dict[str, Any]) -> str:
    return (
        "REPLAY_REPORT_PASS_CANDIDATE"
        if bundle["validation_status"] == "PASS"
        else "REPLAY_VALIDATION_FAILED_CANDIDATE"
    )


def _validate_attempt_binding(
    attempt: AgentMultiBatchAggregateReplayAttempt, *,
    candidate: AgentMultiBatchAggregateCandidate, plan: AgentMultiBatchPlan,
    ordered: list[str], error_code: str,
) -> dict[str, Any]:
    identity = _attempt_identity(candidate, plan, ordered)
    identity_hash = digest(identity)
    if (
        attempt.attempt_id != _id(
            "mbaggregateattempt", candidate.candidate_id, identity_hash,
        )
        or attempt.aggregate_candidate_id != candidate.candidate_id
        or attempt.plan_id != plan.plan_id
        or attempt.attempt_number != identity["attempt_number"]
        or attempt.execution_identity != identity["execution_identity"]
        or attempt.frozen_scope_hash != identity["frozen_scope_hash"]
        or attempt.plan_hash != identity["plan_hash"]
        or attempt.aggregate_input_hash != identity["aggregate_input_hash"]
        or loads(attempt.ordered_batch_result_hashes_json, []) != ordered
        or loads(attempt.identity_json, {}) != identity
        or attempt.identity_hash != identity_hash
        or attempt.status != "STARTED"
    ):
        raise ShadowContractError(error_code)
    return identity


def _validate_result_binding(
    result: AgentMultiBatchAggregateReplayResultCandidate, *,
    attempt: AgentMultiBatchAggregateReplayAttempt,
    candidate: AgentMultiBatchAggregateCandidate, plan: AgentMultiBatchPlan,
    ordered: list[str],
) -> dict[str, Any]:
    if (
        result.attempt_id != attempt.attempt_id
        or result.aggregate_candidate_id != candidate.candidate_id
        or result.plan_id != plan.plan_id
    ):
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_RESULT_ATTEMPT_MISMATCH")
    bundle = _validate_replay_bundle(loads(result.replay_bundle_json, {}))
    report = loads(result.validation_report_json, {})
    binding = loads(result.binding_json, {})
    expected_binding = _result_binding(
        candidate=candidate, plan=plan, ordered=ordered, bundle=bundle,
    )
    expected_binding_hash = digest(expected_binding)
    expected_prospective_hash = digest({
        "candidate_binding_hash": expected_binding_hash,
        "replay_bundle_hash": bundle["replay_bundle_hash"],
    })
    expected_status = _expected_result_status(bundle)
    expected_result_id = _id(
        "mbaggregateresult", attempt.attempt_id, expected_prospective_hash,
    )
    if (
        result.replay_result_id != expected_result_id
        or bundle["replay_bundle_hash"] != result.replay_bundle_hash
        or result.raw_response_hash != bundle["raw_response_hash"]
        or result.validation_profile != bundle["validation_profile"]
        or result.validation_status != bundle["validation_status"]
        or report != bundle["validation_report"]
        or report.get("frozen_scope_hash") != plan.frozen_scope_hash
        or report.get("plan_hash") != plan.plan_hash
        or report.get("aggregate_input_hash") != candidate.aggregate_input_hash
        or report.get("ordered_batch_result_hashes") != ordered
        or digest(report) != result.validation_report_hash
        or result.validation_report_hash != bundle["validation_report_hash"]
        or binding != expected_binding
        or result.binding_hash != expected_binding_hash
        or result.prospective_result_hash != expected_prospective_hash
        or result.status != expected_status
    ):
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_PERSISTED_RESULT_INVALID")
    return bundle


def claim_offline_aggregate_replay(
    db: Session, *, aggregate_candidate_id: str, idempotency_key: str,
) -> AgentMultiBatchAggregateReplayAttempt:
    """Claim the single reserved aggregate replay attempt with a CAS transition."""
    candidate, plan, _payload, ordered = _load_candidate(
        db, aggregate_candidate_id=aggregate_candidate_id)
    identity = _attempt_identity(candidate, plan, ordered)
    identity_hash = digest(identity)
    existing = db.query(AgentMultiBatchAggregateReplayAttempt).filter_by(
        aggregate_candidate_id=aggregate_candidate_id,
    ).one_or_none()
    if existing is None:
        existing = db.query(AgentMultiBatchAggregateReplayAttempt).filter_by(
            plan_id=plan.plan_id,
        ).one_or_none()
    if existing is not None:
        if existing.idempotency_key != idempotency_key:
            raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_ATTEMPT_EXHAUSTED")
        _validate_attempt_binding(
            existing, candidate=candidate, plan=plan, ordered=ordered,
            error_code="MULTIBATCH_AGGREGATE_REPLAY_IDEMPOTENCY_CONFLICT",
        )
        return existing
    with db.begin_nested():
        changed = db.query(AgentMultiBatchPlan).filter(
            AgentMultiBatchPlan.plan_id == plan.plan_id,
            AgentMultiBatchPlan.status == "AGGREGATE_CANDIDATE_READY",
        ).update({
            AgentMultiBatchPlan.status: "AGGREGATE_REPLAY_RUNNING",
            AgentMultiBatchPlan.revision: AgentMultiBatchPlan.revision + 1,
        }, synchronize_session=False)
        if changed != 1:
            raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_CLAIM_STATE_CONFLICT")
        attempt = AgentMultiBatchAggregateReplayAttempt(
            attempt_id=_id("mbaggregateattempt", aggregate_candidate_id, identity_hash),
            aggregate_candidate_id=aggregate_candidate_id, plan_id=plan.plan_id,
            attempt_number=1, idempotency_key=idempotency_key,
            execution_identity=MULTIBATCH_EXECUTION_CANDIDATE,
            frozen_scope_hash=plan.frozen_scope_hash, plan_hash=plan.plan_hash,
            aggregate_input_hash=candidate.aggregate_input_hash,
            ordered_batch_result_hashes_json=dumps(ordered),
            identity_json=dumps(identity), identity_hash=identity_hash, status="STARTED",
        )
        db.add(attempt)
        try:
            db.flush()
        except IntegrityError as exc:
            raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_CONCURRENT_CONFLICT") from exc
    return attempt


def request_offline_aggregate_replay_cancel(
    db: Session, *, aggregate_candidate_id: str,
) -> AgentMultiBatchPlan:
    candidate, plan, _payload, _ordered = _load_candidate(
        db, aggregate_candidate_id=aggregate_candidate_id)
    del candidate
    changed = db.query(AgentMultiBatchPlan).filter(
        AgentMultiBatchPlan.plan_id == plan.plan_id,
        AgentMultiBatchPlan.status.in_({
            "AGGREGATE_CANDIDATE_READY", "AGGREGATE_REPLAY_RUNNING",
        }),
    ).update({
        AgentMultiBatchPlan.status: "CANCEL_REQUESTED",
        AgentMultiBatchPlan.revision: AgentMultiBatchPlan.revision + 1,
    }, synchronize_session=False)
    if changed != 1:
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_CANCEL_STATE_CONFLICT")
    return db.query(AgentMultiBatchPlan).populate_existing().filter_by(
        plan_id=plan.plan_id).one()


def complete_offline_aggregate_replay(
    db: Session, *, attempt_id: str, protected_replay: dict[str, Any],
) -> AgentMultiBatchAggregateReplayResultCandidate:
    attempt = db.query(AgentMultiBatchAggregateReplayAttempt).filter_by(
        attempt_id=attempt_id).one_or_none()
    if attempt is None:
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_ATTEMPT_NOT_FOUND")
    bundle = _validate_replay_bundle(protected_replay)
    existing = db.query(AgentMultiBatchAggregateReplayResultCandidate).filter_by(
        attempt_id=attempt_id).one_or_none()
    if existing is None:
        existing = db.query(AgentMultiBatchAggregateReplayResultCandidate).filter_by(
            plan_id=attempt.plan_id).one_or_none()
    if existing is not None:
        recover_offline_aggregate_replay(
            db, aggregate_candidate_id=attempt.aggregate_candidate_id,
        )
        if existing.replay_bundle_hash != bundle["replay_bundle_hash"]:
            raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_RESULT_IDEMPOTENCY_CONFLICT")
        return existing
    candidate, plan, _payload, ordered = _load_candidate(
        db, aggregate_candidate_id=attempt.aggregate_candidate_id)
    report = bundle["validation_report"]
    if (
        report.get("frozen_scope_hash") != plan.frozen_scope_hash
        or report.get("plan_hash") != plan.plan_hash
        or report.get("aggregate_input_hash") != candidate.aggregate_input_hash
        or report.get("ordered_batch_result_hashes") != ordered
    ):
        raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_REPORT_SCOPE_MISMATCH")
    _validate_attempt_binding(
        attempt, candidate=candidate, plan=plan, ordered=ordered,
        error_code="MULTIBATCH_AGGREGATE_REPLAY_ATTEMPT_IDENTITY_MISMATCH",
    )
    binding = _result_binding(
        candidate=candidate, plan=plan, ordered=ordered, bundle=bundle,
    )
    binding_hash = digest(binding)
    prospective_result_hash = digest({
        "candidate_binding_hash": binding_hash,
        "replay_bundle_hash": bundle["replay_bundle_hash"],
    })
    status = _expected_result_status(bundle)
    plan_status = (
        "AGGREGATE_REPLAY_CANDIDATE_READY"
        if bundle["validation_status"] == "PASS"
        else "AGGREGATE_REPLAY_FAILED_TERMINAL"
    )
    with db.begin_nested():
        changed = db.query(AgentMultiBatchPlan).filter(
            AgentMultiBatchPlan.plan_id == plan.plan_id,
            AgentMultiBatchPlan.status == "AGGREGATE_REPLAY_RUNNING",
        ).update({
            AgentMultiBatchPlan.status: plan_status,
            AgentMultiBatchPlan.revision: AgentMultiBatchPlan.revision + 1,
        }, synchronize_session=False)
        if changed != 1:
            raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_COMPLETE_STATE_CONFLICT")
        result = AgentMultiBatchAggregateReplayResultCandidate(
            replay_result_id=_id("mbaggregateresult", attempt_id, prospective_result_hash),
            attempt_id=attempt_id, aggregate_candidate_id=candidate.candidate_id,
            plan_id=plan.plan_id, raw_response_hash=bundle["raw_response_hash"],
            validation_profile=bundle["validation_profile"],
            validation_status=bundle["validation_status"],
            validation_report_json=dumps(bundle["validation_report"]),
            validation_report_hash=bundle["validation_report_hash"],
            replay_bundle_json=dumps(bundle), replay_bundle_hash=bundle["replay_bundle_hash"],
            binding_json=dumps(binding), binding_hash=binding_hash,
            prospective_result_hash=prospective_result_hash, status=status,
        )
        db.add(result)
        try:
            db.flush()
        except IntegrityError as exc:
            raise ShadowContractError(
                "MULTIBATCH_AGGREGATE_REPLAY_RESULT_CONCURRENT_CONFLICT") from exc
    return result


def recover_offline_aggregate_replay(
    db: Session, *, aggregate_candidate_id: str,
) -> dict[str, Any]:
    candidate, plan, _payload, ordered = _load_candidate(
        db, aggregate_candidate_id=aggregate_candidate_id)
    attempt = db.query(AgentMultiBatchAggregateReplayAttempt).filter_by(
        aggregate_candidate_id=aggregate_candidate_id).one_or_none()
    if attempt is None:
        attempt = db.query(AgentMultiBatchAggregateReplayAttempt).filter_by(
            plan_id=plan.plan_id).one_or_none()
    result = None
    if attempt is not None:
        result = db.query(AgentMultiBatchAggregateReplayResultCandidate).filter_by(
            attempt_id=attempt.attempt_id).one_or_none()
    if result is None:
        result = db.query(AgentMultiBatchAggregateReplayResultCandidate).filter_by(
            plan_id=plan.plan_id).one_or_none()
    if attempt is not None:
        _validate_attempt_binding(
            attempt, candidate=candidate, plan=plan, ordered=ordered,
            error_code="MULTIBATCH_AGGREGATE_REPLAY_PERSISTED_ATTEMPT_INVALID",
        )
    if result is not None:
        if attempt is None:
            raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_RESULT_ATTEMPT_MISMATCH")
        bundle = _validate_result_binding(
            result, attempt=attempt, candidate=candidate, plan=plan, ordered=ordered,
        )
        expected_plan_status = (
            "AGGREGATE_REPLAY_CANDIDATE_READY"
            if bundle["validation_status"] == "PASS"
            else "AGGREGATE_REPLAY_FAILED_TERMINAL"
        )
        if plan.status != expected_plan_status:
            raise ShadowContractError("MULTIBATCH_AGGREGATE_REPLAY_PERSISTED_RESULT_INVALID")
    return {
        "aggregate_candidate_id": aggregate_candidate_id,
        "plan_id": plan.plan_id,
        "plan_status": plan.status,
        "attempt_id": attempt.attempt_id if attempt else None,
        "result_candidate_id": result.replay_result_id if result else None,
        "result_status": result.status if result else None,
        "external_calls": 0,
        "formal_result_created": False,
    }
