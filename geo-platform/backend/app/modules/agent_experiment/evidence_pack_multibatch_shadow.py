"""Typed, offline-only contracts for multi-batch Evidence Pack investigation.

Nothing in this module performs a provider call, writes a production result, or
changes the single-pack execution profile.  It validates the existing capacity
planner output, records an in-memory execution audit, and builds a shadow
aggregate input whose conflicts and UNKNOWN values remain explicit.

Production execution and result merge remain blocked by
``SEMANTIC_CONTRACT_REVIEW_REQUIRED:MULTI_BATCH_RESULT_MERGE``.
"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.single_prompt_v2.delivery_text import digest

from .evidence_pack_capacity import CAPACITY_PLAN_CONTRACT
from .evidence_pack import _VALID_RUN_RULE_V2, _eligible_answer


SHADOW_BATCH_RESULT_CONTRACT = "geo.evidence-pack.batch-finding.shadow.v1"
SHADOW_AGGREGATE_INPUT_CONTRACT = "geo.evidence-pack.aggregate-input.shadow.v1"
SHADOW_EXECUTION_STATE_CONTRACT = "geo.evidence-pack.multibatch-state.shadow.v1"


class ShadowContractError(ValueError):
    """Raised when a shadow object loses frozen identity or scope."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ShadowEvidenceLocator(_StrictModel):
    kind: Literal[
        "ANSWER_SPAN", "CITATION_OCCURRENCE", "SOURCE_SNAPSHOT", "SOURCE_DISPOSITION",
    ]
    run_id: str | None = None
    answer_hash: str | None = None
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=1)
    citation_occurrence_id: str | None = None
    source_snapshot_id: str | None = None
    source_disposition_id: str | None = None

    @model_validator(mode="after")
    def require_exact_locator(self):
        if self.kind == "ANSWER_SPAN":
            if (self.run_id is None or self.answer_hash is None
                    or self.start is None or self.end is None):
                raise ValueError("ANSWER_SPAN requires run_id/answer_hash/start/end")
            if self.end <= self.start:
                raise ValueError("ANSWER_SPAN end must be greater than start")
        elif self.kind == "CITATION_OCCURRENCE" and not self.citation_occurrence_id:
            raise ValueError("CITATION_OCCURRENCE requires citation_occurrence_id")
        elif self.kind == "SOURCE_SNAPSHOT" and not self.source_snapshot_id:
            raise ValueError("SOURCE_SNAPSHOT requires source_snapshot_id")
        elif self.kind == "SOURCE_DISPOSITION" and not self.source_disposition_id:
            raise ValueError("SOURCE_DISPOSITION requires source_disposition_id")
        allowed = {
            "ANSWER_SPAN": {"run_id", "answer_hash", "start", "end"},
            "CITATION_OCCURRENCE": {"citation_occurrence_id"},
            "SOURCE_SNAPSHOT": {"source_snapshot_id"},
            "SOURCE_DISPOSITION": {"source_disposition_id"},
        }[self.kind]
        populated = {
            name for name in (
                "run_id", "answer_hash", "start", "end", "citation_occurrence_id",
                "source_snapshot_id", "source_disposition_id",
            ) if getattr(self, name) is not None
        }
        if populated - allowed:
            raise ValueError("locator kind cannot carry foreign identity fields")
        return self


class ShadowBatchFinding(_StrictModel):
    finding_id: str = Field(min_length=1)
    finding_kind: Literal["OBSERVATION", "DIAGNOSIS_CANDIDATE", "ACTION_CANDIDATE"]
    predicate: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    scope: Literal["BATCH_VALID_SCOPE"]
    scope_batch_hash: str = Field(min_length=1)
    quantifier: Literal["ANY_VALID_RUN", "EXACT_BATCH"]
    claim_identity_hash: str = Field(min_length=1)
    claim_value: str | None
    matched_count: int | None = Field(default=None, ge=0)
    valid_run_count: int | None = Field(default=None, ge=0)
    unresolved_run_count: int | None = Field(default=None, ge=0)
    statement: str = Field(min_length=1)
    classification: Literal["OBSERVED", "INFERENCE", "HYPOTHESIS", "UNKNOWN"]
    evidence_locators: list[ShadowEvidenceLocator]

    @model_validator(mode="after")
    def preserve_unknown_and_evidence(self):
        if self.classification == "UNKNOWN":
            if self.claim_value is not None:
                raise ValueError("UNKNOWN finding cannot carry a known claim_value")
        elif not self.claim_value:
            raise ValueError("known finding requires claim_value")
        if self.classification in {"OBSERVED", "INFERENCE"} and not self.evidence_locators:
            raise ValueError("OBSERVED/INFERENCE finding requires evidence")
        identity_payload = {
            "finding_kind": self.finding_kind,
            "predicate": self.predicate,
            "subject": self.subject,
            "quantifier": self.quantifier,
        }
        if self.predicate != "BRAND_LITERAL_PRESENCE":
            identity_payload["scope_batch_hash"] = self.scope_batch_hash
        expected_identity = digest(identity_payload)
        if self.claim_identity_hash != expected_identity:
            raise ValueError("claim_identity_hash does not match typed identity")
        if self.predicate == "BRAND_LITERAL_PRESENCE":
            if self.finding_kind != "OBSERVATION" or self.subject != "TARGET_BRAND":
                raise ValueError("brand presence requires OBSERVATION/TARGET_BRAND")
            if self.quantifier != "ANY_VALID_RUN":
                raise ValueError("brand presence requires ANY_VALID_RUN")
            if self.claim_value not in {None, "PRESENT", "ABSENT"}:
                raise ValueError("brand presence value must be PRESENT/ABSENT/UNKNOWN")
            if None in (self.matched_count, self.valid_run_count, self.unresolved_run_count):
                raise ValueError("brand presence requires server-verifiable counts")
        return self


class ShadowBatchFindingResult(_StrictModel):
    contract_version: Literal["geo.evidence-pack.batch-finding.shadow.v1"]
    frozen_scope_hash: str = Field(min_length=1)
    plan_hash: str = Field(min_length=1)
    batch_hash: str = Field(min_length=1)
    batch_number: int = Field(ge=1)
    batch_result_id: str = Field(min_length=1)
    attempt_number: int = Field(ge=1)
    status: Literal["SUCCESS", "FAILED", "CANCELLED"]
    response_hash: str | None
    findings: list[ShadowBatchFinding]
    failure_code: str | None
    result_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def status_payload_matches(self):
        if self.status == "SUCCESS":
            if not self.response_hash or self.failure_code is not None:
                raise ValueError("SUCCESS requires response_hash and no failure_code")
        elif self.findings or self.response_hash:
            raise ValueError("FAILED/CANCELLED cannot carry findings or response_hash")
        elif self.status == "FAILED" and not self.failure_code:
            raise ValueError("FAILED requires failure_code")
        return self


def _without_hash(payload: dict[str, Any], field: str) -> dict[str, Any]:
    value = deepcopy(payload)
    value.pop(field, None)
    return value


def _batch_identity(batch: dict[str, Any], scope_hash: str) -> dict[str, Any]:
    return {
        "frozen_scope_hash": scope_hash,
        "batch_number": batch["batch_number"],
        "run_ids": batch["run_ids"],
        "citation_occurrence_ids": batch["citation_occurrence_ids"],
        "source_snapshot_ids": batch["source_snapshot_ids"],
        "source_disposition_ids": batch["source_disposition_ids"],
        "evidence_pack_hash": batch["evidence_pack_hash"],
    }


def bind_shadow_plan_to_frozen_scope(
    plan: dict[str, Any], frozen_scope: dict[str, Any],
) -> dict[str, Any]:
    """Bind answer identity needed by shadow span validation.

    This is still not production authority: production must reload the frozen
    object from its authoritative store and repeat the comparison.
    """
    value = deepcopy(plan)
    if digest(frozen_scope) != value.get("frozen_scope_hash"):
        raise ShadowContractError("SHADOW_BINDING_FROZEN_SCOPE_HASH_MISMATCH")
    brand = (frozen_scope.get("project_configuration") or {}).get("brand") or {}
    brand_terms = [
        str(value).strip().casefold() for value in [
            brand.get("brand_name"), *(brand.get("brand_aliases") or []),
        ] if str(value or "").strip()
    ]
    manifest = {}
    for run in frozen_scope.get("runs") or []:
        run_id = str(run.get("run_id"))
        answer = str(run.get("answer_text") or "")
        valid = _eligible_answer(run, eligibility_rule_version=_VALID_RUN_RULE_V2)
        manifest[run_id] = {
            "answer_hash": digest(answer),
            "answer_length": len(answer),
            "brand_literal_matched": (
                any(term in answer.casefold() for term in brand_terms)
                if valid and brand_terms else None
            ),
        }
    expected = {str(run_id) for batch in value.get("batches") or [] for run_id in batch["run_ids"]}
    if set(manifest) != expected:
        raise ShadowContractError("SHADOW_BINDING_RUN_SET_MISMATCH")
    value["shadow_run_manifest"] = manifest
    value["shadow_eligibility_rule_version"] = _VALID_RUN_RULE_V2
    value["plan_hash"] = digest(_without_hash(value, "plan_hash"))
    return value


def validate_shadow_capacity_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Validate shadow plan self-consistency without executing it.

    Production cutover must additionally reload the authoritative frozen scope
    and compare every Run/Citation/Source identity and hash.  A self-consistent
    shadow plan is never sufficient production authority by itself.
    """
    if plan.get("contract_version") != CAPACITY_PLAN_CONTRACT:
        raise ShadowContractError("SHADOW_PLAN_CONTRACT_MISMATCH")
    if plan.get("mode") != "SHADOW_ONLY_NO_MODEL_EXECUTION_NO_RESULT_MERGE":
        raise ShadowContractError("SHADOW_PLAN_MODE_MISMATCH")
    if plan.get("plan_hash") != digest(_without_hash(plan, "plan_hash")):
        raise ShadowContractError("SHADOW_PLAN_HASH_MISMATCH")
    if plan.get("status") != "READY" or plan.get("partition_status") != "READY":
        raise ShadowContractError("SHADOW_PLAN_NOT_READY")
    if plan.get("aggregate_budget_status") != "WITHIN_TASK_CAP":
        raise ShadowContractError("SHADOW_PLAN_BUDGET_NOT_READY")

    batches = list(plan.get("batches") or [])
    if int(plan.get("batch_count", -1)) != len(batches) or not batches:
        raise ShadowContractError("SHADOW_PLAN_BATCH_COUNT_MISMATCH")
    run_ids: list[str] = []
    occurrence_ids: list[str] = []
    snapshot_ids: set[str] = set()
    disposition_ids: set[str] = set()
    for expected_number, batch in enumerate(batches, start=1):
        if int(batch.get("batch_number", 0)) != expected_number:
            raise ShadowContractError("SHADOW_PLAN_BATCH_SEQUENCE_MISMATCH")
        if batch.get("batch_hash") != digest(_batch_identity(batch, plan["frozen_scope_hash"])):
            raise ShadowContractError("SHADOW_PLAN_BATCH_HASH_MISMATCH")
        if int(batch.get("actual_model_input_characters", 0)) > int(plan["text_budget"]):
            raise ShadowContractError("SHADOW_PLAN_BATCH_TEXT_BUDGET_EXCEEDED")
        if int(batch.get("total_token_reservation", 0)) > int(plan["task_token_cap"]):
            raise ShadowContractError("SHADOW_PLAN_BATCH_TOKEN_BUDGET_EXCEEDED")
        run_ids.extend(str(value) for value in batch.get("run_ids") or [])
        occurrence_ids.extend(str(value) for value in batch.get("citation_occurrence_ids") or [])
        snapshot_ids.update(str(value) for value in batch.get("source_snapshot_ids") or [])
        disposition_ids.update(str(value) for value in batch.get("source_disposition_ids") or [])

    if len(run_ids) != len(set(run_ids)):
        raise ShadowContractError("SHADOW_PLAN_RUN_DUPLICATED")
    if len(occurrence_ids) != len(set(occurrence_ids)):
        raise ShadowContractError("SHADOW_PLAN_CITATION_DUPLICATED")
    coverage = plan.get("coverage") or {}
    missing_fields = (
        "missing_run_ids", "missing_citation_occurrence_ids", "missing_source_snapshot_ids",
        "missing_source_disposition_ids", "unassigned_source_snapshot_ids",
    )
    if any(coverage.get(field) for field in missing_fields):
        raise ShadowContractError("SHADOW_PLAN_COVERAGE_INCOMPLETE")
    expected = {
        "run_total": len(set(run_ids)),
        "run_planned": len(run_ids),
        "citation_occurrence_total": len(set(occurrence_ids)),
        "citation_occurrence_covered": len(occurrence_ids),
        "source_snapshot_covered": len(snapshot_ids),
        "source_disposition_covered": len(disposition_ids),
    }
    if any(int(coverage.get(key, -1)) != value for key, value in expected.items()):
        raise ShadowContractError("SHADOW_PLAN_COVERAGE_COUNT_MISMATCH")
    if int(plan.get("aggregate_total_token_reservation", -1)) != sum(
        int(batch["total_token_reservation"]) for batch in batches
    ):
        raise ShadowContractError("SHADOW_PLAN_AGGREGATE_BUDGET_MISMATCH")
    manifest = plan.get("shadow_run_manifest") or {}
    if plan.get("shadow_eligibility_rule_version") != _VALID_RUN_RULE_V2:
        raise ShadowContractError("SHADOW_PLAN_ELIGIBILITY_RULE_MISMATCH")
    if set(manifest) != set(run_ids):
        raise ShadowContractError("SHADOW_PLAN_RUN_MANIFEST_MISMATCH")
    if any(
        not row.get("answer_hash") or int(row.get("answer_length", -1)) < 0
        for row in manifest.values()
    ):
        raise ShadowContractError("SHADOW_PLAN_RUN_MANIFEST_INVALID")
    return deepcopy(plan)


def make_shadow_batch_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach a deterministic result hash before plan-aware validation."""
    candidate = deepcopy(payload)
    candidate["contract_version"] = SHADOW_BATCH_RESULT_CONTRACT
    candidate["result_hash"] = digest(candidate)
    return candidate


def validate_shadow_batch_result(
    plan: dict[str, Any], payload: dict[str, Any],
) -> ShadowBatchFindingResult:
    plan = validate_shadow_capacity_plan(plan)
    result = ShadowBatchFindingResult.model_validate(payload)
    if result.result_hash != digest(_without_hash(payload, "result_hash")):
        raise ShadowContractError("SHADOW_BATCH_RESULT_HASH_MISMATCH")
    if result.frozen_scope_hash != plan["frozen_scope_hash"] or result.plan_hash != plan["plan_hash"]:
        raise ShadowContractError("SHADOW_BATCH_RESULT_SCOPE_MISMATCH")
    batches = {row["batch_hash"]: row for row in plan["batches"]}
    batch = batches.get(result.batch_hash)
    if batch is None or result.batch_number != int(batch["batch_number"]):
        raise ShadowContractError("SHADOW_BATCH_RESULT_IDENTITY_MISMATCH")

    allowed_runs = {str(value) for value in batch["run_ids"]}
    run_manifest = plan["shadow_run_manifest"]
    allowed_citations = {str(value) for value in batch["citation_occurrence_ids"]}
    allowed_snapshots = {str(value) for value in batch["source_snapshot_ids"]}
    allowed_dispositions = {str(value) for value in batch["source_disposition_ids"]}
    finding_ids: set[str] = set()
    finding_identities: set[str] = set()
    for finding in result.findings:
        if finding.finding_id in finding_ids:
            raise ShadowContractError("SHADOW_BATCH_FINDING_ID_DUPLICATED")
        finding_ids.add(finding.finding_id)
        if finding.claim_identity_hash in finding_identities:
            raise ShadowContractError("SHADOW_BATCH_FINDING_IDENTITY_DUPLICATED")
        finding_identities.add(finding.claim_identity_hash)
        if finding.scope_batch_hash != result.batch_hash:
            raise ShadowContractError("SHADOW_BATCH_FINDING_SCOPE_MISMATCH")
        if finding.predicate == "BRAND_LITERAL_PRESENCE":
            observations = [run_manifest[run_id]["brand_literal_matched"] for run_id in allowed_runs]
            expected_matched = sum(value is True for value in observations)
            expected_valid = sum(value is not None for value in observations)
            expected_unresolved = sum(value is None for value in observations)
            expected_value = (
                None if expected_unresolved else "PRESENT" if expected_matched else "ABSENT"
            )
            expected_classification = "UNKNOWN" if expected_unresolved else "OBSERVED"
            if (
                finding.matched_count != expected_matched
                or finding.valid_run_count != expected_valid
                or finding.unresolved_run_count != expected_unresolved
                or finding.claim_value != expected_value
                or finding.classification != expected_classification
            ):
                raise ShadowContractError("SHADOW_BATCH_BRAND_OBSERVATION_MISMATCH")
        for locator in finding.evidence_locators:
            if locator.kind == "ANSWER_SPAN" and locator.run_id not in allowed_runs:
                raise ShadowContractError("SHADOW_BATCH_LOCATOR_CROSS_BATCH_RUN")
            if locator.kind == "ANSWER_SPAN":
                answer_identity = run_manifest[locator.run_id]
                if locator.answer_hash != answer_identity["answer_hash"]:
                    raise ShadowContractError("SHADOW_BATCH_LOCATOR_ANSWER_HASH_MISMATCH")
                if int(locator.end) > int(answer_identity["answer_length"]):
                    raise ShadowContractError("SHADOW_BATCH_LOCATOR_SPAN_OUT_OF_BOUNDS")
            if (locator.kind == "CITATION_OCCURRENCE"
                    and locator.citation_occurrence_id not in allowed_citations):
                raise ShadowContractError("SHADOW_BATCH_LOCATOR_CROSS_BATCH_CITATION")
            if locator.kind == "SOURCE_SNAPSHOT" and locator.source_snapshot_id not in allowed_snapshots:
                raise ShadowContractError("SHADOW_BATCH_LOCATOR_CROSS_BATCH_SNAPSHOT")
            if (locator.kind == "SOURCE_DISPOSITION"
                    and locator.source_disposition_id not in allowed_dispositions):
                raise ShadowContractError("SHADOW_BATCH_LOCATOR_CROSS_BATCH_DISPOSITION")
    return result


def build_shadow_aggregate_input(
    plan: dict[str, Any], results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build an auditable shadow input; never create a business result."""
    plan = validate_shadow_capacity_plan(plan)
    validated = [validate_shadow_batch_result(plan, row) for row in results]
    success_by_batch: dict[str, ShadowBatchFindingResult] = {}
    result_ids: set[str] = set()
    finding_ids: set[str] = set()
    for result in validated:
        # A business batch collision is the primary scope error.  Check it
        # before the internal result identifier so replaying the same object
        # cannot obscure the violated batch-membership invariant.
        if result.batch_hash in success_by_batch:
            raise ShadowContractError("SHADOW_AGGREGATE_BATCH_DUPLICATED")
        if result.batch_result_id in result_ids:
            raise ShadowContractError("SHADOW_BATCH_RESULT_ID_DUPLICATED")
        result_ids.add(result.batch_result_id)
        if result.status != "SUCCESS":
            raise ShadowContractError("SHADOW_AGGREGATE_REQUIRES_ALL_BATCHES_SUCCESS")
        success_by_batch[result.batch_hash] = result
        for finding in result.findings:
            if finding.finding_id in finding_ids:
                raise ShadowContractError("SHADOW_AGGREGATE_FINDING_ID_DUPLICATED")
            finding_ids.add(finding.finding_id)
    expected_batches = {row["batch_hash"] for row in plan["batches"]}
    if set(success_by_batch) != expected_batches:
        raise ShadowContractError("SHADOW_AGGREGATE_BATCH_SET_MISMATCH")

    values_by_claim: dict[str, set[str]] = {}
    unknown_claims: set[str] = set()
    identity_by_hash: dict[str, dict[str, str]] = {}
    ordered_results = [success_by_batch[row["batch_hash"]] for row in plan["batches"]]
    for result in ordered_results:
        for finding in result.findings:
            identity_by_hash.setdefault(finding.claim_identity_hash, {
                "predicate": finding.predicate,
                "subject": finding.subject,
                "quantifier": finding.quantifier,
            })
            if finding.predicate == "BRAND_LITERAL_PRESENCE":
                # Audit only. The complete-scope observation is recomputed once
                # from the authoritative manifest below, never from findings.
                continue
            if finding.classification == "UNKNOWN":
                unknown_claims.add(finding.claim_identity_hash)
                continue
            values_by_claim.setdefault(finding.claim_identity_hash, set()).add(
                str(finding.claim_value)
            )
    brand_identity = {
        "finding_kind": "OBSERVATION",
        "predicate": "BRAND_LITERAL_PRESENCE",
        "subject": "TARGET_BRAND",
        "quantifier": "ANY_VALID_RUN",
    }
    brand_identity_hash = digest(brand_identity)
    manifest_values = [
        row["brand_literal_matched"] for row in plan["shadow_run_manifest"].values()
    ]
    counts = {
        "matched_count": sum(value is True for value in manifest_values),
        "valid_run_count": sum(value is not None for value in manifest_values),
        "unresolved_run_count": sum(value is None for value in manifest_values),
    }
    aggregate_value = (
        "UNKNOWN" if counts["unresolved_run_count"]
        else "PRESENT" if counts["matched_count"] else "ABSENT"
    )
    if aggregate_value == "UNKNOWN":
        unknown_claims.add(brand_identity_hash)
    aggregate_observations = [{
        **brand_identity,
        "claim_identity_hash": brand_identity_hash,
        "scope": "FROZEN_VALID_SCOPE",
        "claim_value": aggregate_value,
        **counts,
        "verification": "SHADOW_DERIVED_NOT_PRODUCTION_VERIFIED",
    }]
    conflicts = []
    for identity_hash, values in sorted(values_by_claim.items()):
        identity = identity_by_hash[identity_hash]
        if len(values) > 1:
            conflicts.append({
                "claim_identity_hash": identity_hash,
                **identity,
                "claim_values": sorted(values),
            })
    aggregate_status = "READY_FOR_SHADOW_REVIEW"
    if conflicts:
        aggregate_status = "REVIEW_REQUIRED_CONFLICT"
    elif unknown_claims:
        aggregate_status = "REVIEW_REQUIRED_UNKNOWN"
    body = {
        "contract_version": SHADOW_AGGREGATE_INPUT_CONTRACT,
        "mode": "SHADOW_ONLY_NO_PROVIDER_CALL_NO_AGENT_RESULT_VERSION",
        "status": aggregate_status,
        "frozen_scope_hash": plan["frozen_scope_hash"],
        "plan_hash": plan["plan_hash"],
        "batch_result_hashes": [result.result_hash for result in ordered_results],
        "batch_results": [result.model_dump(mode="json") for result in ordered_results],
        "aggregate_observations": aggregate_observations,
        "conflicts": conflicts,
        "unknown_claim_keys": sorted(unknown_claims),
        "finding_count": sum(len(result.findings) for result in ordered_results),
        "production_result_created": False,
        "cutover_blocker": "SEMANTIC_CONTRACT_REVIEW_REQUIRED:MULTI_BATCH_RESULT_MERGE",
    }
    body["aggregate_input_hash"] = digest(body)
    return body


def preflight_shadow_multibatch_budget(
    plan: dict[str, Any], *, aggregate_call_token_reservation: int,
    max_requests: int, max_total_tokens: int, max_cost_cny: float,
    conservative_cny_per_million_tokens: float, max_attempts_per_batch: int = 2,
) -> dict[str, Any]:
    """Preflight all calls atomically; this function cannot authorize them."""
    plan = validate_shadow_capacity_plan(plan)
    numeric_values = (
        aggregate_call_token_reservation, max_requests, max_total_tokens,
        max_cost_cny, conservative_cny_per_million_tokens,
    )
    if any(not math.isfinite(float(value)) or float(value) < 0 for value in numeric_values):
        raise ShadowContractError("SHADOW_BUDGET_VALUE_INVALID")
    if type(max_attempts_per_batch) is not int or not 1 <= max_attempts_per_batch <= 5:
        raise ShadowContractError("SHADOW_BUDGET_MAX_ATTEMPTS_INVALID")
    required_requests = int(plan["batch_count"]) * max_attempts_per_batch + 1
    required_tokens = int(plan["aggregate_total_token_reservation"]) * max_attempts_per_batch + int(
        aggregate_call_token_reservation
    )
    required_cost = required_tokens / 1_000_000 * float(conservative_cny_per_million_tokens)
    reasons = []
    if max_requests < required_requests:
        reasons.append("REQUEST_CAP_EXCEEDED")
    if max_total_tokens < required_tokens:
        reasons.append("TOKEN_CAP_EXCEEDED")
    if max_cost_cny < required_cost:
        reasons.append("COST_CAP_EXCEEDED")
    body = {
        "mode": "SHADOW_PREFLIGHT_ONLY_NO_RESERVATION_NO_CALL",
        "status": "READY_FOR_EXPLICIT_AUTHORIZATION" if not reasons else "BLOCKED_ZERO_CALLS",
        "plan_hash": plan["plan_hash"],
        "required_requests": required_requests,
        "required_tokens": required_tokens,
        "required_cost_cny": required_cost,
        "max_attempts_per_batch": max_attempts_per_batch,
        "block_reasons": reasons,
        "external_calls": 0,
    }
    body["reservation_identity_hash"] = digest(body)
    return body


def _seal_state(state: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(state)
    value["state_hash"] = digest(_without_hash(value, "state_hash"))
    return value


def _verify_state(state: dict[str, Any]) -> None:
    if state.get("contract_version") != SHADOW_EXECUTION_STATE_CONTRACT:
        raise ShadowContractError("SHADOW_STATE_CONTRACT_MISMATCH")
    if state.get("state_hash") != digest(_without_hash(state, "state_hash")):
        raise ShadowContractError("SHADOW_STATE_HASH_MISMATCH")


def initialize_shadow_execution(
    plan: dict[str, Any], *, budget_reservation: dict[str, Any],
) -> dict[str, Any]:
    plan = validate_shadow_capacity_plan(plan)
    reservation = deepcopy(budget_reservation)
    reservation_hash = reservation.pop("reservation_identity_hash", None)
    if reservation_hash != digest(reservation):
        raise ShadowContractError("SHADOW_STATE_RESERVATION_HASH_MISMATCH")
    if reservation.get("plan_hash") != plan["plan_hash"]:
        raise ShadowContractError("SHADOW_STATE_RESERVATION_PLAN_MISMATCH")
    if reservation.get("status") != "READY_FOR_EXPLICIT_AUTHORIZATION":
        raise ShadowContractError("SHADOW_STATE_RESERVATION_NOT_READY")
    max_attempts_per_batch = reservation.get("max_attempts_per_batch")
    if type(max_attempts_per_batch) is not int or not 1 <= max_attempts_per_batch <= 5:
        raise ShadowContractError("SHADOW_STATE_MAX_ATTEMPTS_INVALID")
    return _seal_state({
        "contract_version": SHADOW_EXECUTION_STATE_CONTRACT,
        "mode": "SHADOW_ONLY_NO_PROVIDER_CALL_NO_DB_WRITE",
        "plan_hash": plan["plan_hash"],
        "status": "PLANNED",
        "cancel_requested": False,
        "max_attempts_per_batch": max_attempts_per_batch,
        "reservation_identity_hash": reservation_hash,
        "batches": {
            row["batch_hash"]: {"status": "PENDING", "attempts": []}
            for row in plan["batches"]
        },
    })


def record_shadow_batch_attempt(
    state: dict[str, Any], *, batch_hash: str,
    outcome: Literal["SUCCESS", "FAILED"], result_hash: str | None = None,
    failure_code: str | None = None,
) -> dict[str, Any]:
    _verify_state(state)
    value = deepcopy(state)
    if value["status"] in {
        "CANCEL_REQUESTED", "CANCELLED", "FAILED_TERMINAL",
        "READY_FOR_SHADOW_AGGREGATE",
    }:
        raise ShadowContractError("SHADOW_STATE_TERMINAL_OR_CANCELLING")
    batch = value["batches"].get(batch_hash)
    if batch is None:
        raise ShadowContractError("SHADOW_STATE_BATCH_UNKNOWN")
    if batch["status"] == "SUCCESS":
        raise ShadowContractError("SHADOW_STATE_SUCCESS_IMMUTABLE")
    if batch["status"] == "FAILED":
        raise ShadowContractError("SHADOW_STATE_RETRY_REQUIRES_RESUME")
    if len(batch["attempts"]) >= int(value["max_attempts_per_batch"]):
        raise ShadowContractError("SHADOW_STATE_MAX_ATTEMPTS_EXHAUSTED")
    if outcome == "SUCCESS" and not result_hash:
        raise ShadowContractError("SHADOW_STATE_SUCCESS_REQUIRES_RESULT_HASH")
    if outcome == "FAILED" and not failure_code:
        raise ShadowContractError("SHADOW_STATE_FAILURE_REQUIRES_CODE")
    batch["attempts"].append({
        "attempt_number": len(batch["attempts"]) + 1,
        "outcome": outcome,
        "result_hash": result_hash if outcome == "SUCCESS" else None,
        "failure_code": failure_code if outcome == "FAILED" else None,
    })
    batch["status"] = outcome
    if outcome == "FAILED":
        value["status"] = (
            "FAILED_TERMINAL"
            if len(batch["attempts"]) >= int(value["max_attempts_per_batch"])
            else "FAILED_RECOVERABLE"
        )
    elif any(row["status"] == "FAILED" for row in value["batches"].values()):
        value["status"] = (
            "FAILED_TERMINAL"
            if any(
                row["status"] == "FAILED"
                and len(row["attempts"]) >= int(value["max_attempts_per_batch"])
                for row in value["batches"].values()
            ) else "FAILED_RECOVERABLE"
        )
    elif all(row["status"] == "SUCCESS" for row in value["batches"].values()):
        value["status"] = "READY_FOR_SHADOW_AGGREGATE"
    else:
        value["status"] = "RUNNING"
    return _seal_state(value)


def resume_shadow_execution(state: dict[str, Any]) -> dict[str, Any]:
    _verify_state(state)
    if state["status"] != "FAILED_RECOVERABLE":
        raise ShadowContractError("SHADOW_STATE_NOT_RECOVERABLE")
    value = deepcopy(state)
    for batch in value["batches"].values():
        if batch["status"] == "FAILED":
            batch["status"] = "PENDING"
    value["status"] = "RUNNING"
    return _seal_state(value)


def request_shadow_cancellation(state: dict[str, Any]) -> dict[str, Any]:
    _verify_state(state)
    if state["status"] == "CANCELLED":
        raise ShadowContractError("SHADOW_STATE_ALREADY_TERMINAL")
    value = deepcopy(state)
    value["cancel_requested"] = True
    value["status"] = "CANCEL_REQUESTED"
    return _seal_state(value)


def acknowledge_shadow_cancellation(state: dict[str, Any]) -> dict[str, Any]:
    _verify_state(state)
    if state["status"] != "CANCEL_REQUESTED":
        raise ShadowContractError("SHADOW_STATE_CANCEL_NOT_REQUESTED")
    value = deepcopy(state)
    for batch in value["batches"].values():
        if batch["status"] != "SUCCESS":
            batch["status"] = "CANCELLED"
    value["status"] = "CANCELLED"
    return _seal_state(value)
