from __future__ import annotations

from copy import deepcopy

import pytest

from app.modules.agent_experiment.evidence_pack import build_evidence_pack
from app.modules.agent_experiment.evidence_pack_capacity import plan_evidence_pack_batches
from app.modules.agent_experiment.evidence_pack_multibatch_shadow import (
    ShadowContractError,
    acknowledge_shadow_cancellation,
    bind_shadow_plan_to_frozen_scope,
    build_shadow_aggregate_input,
    initialize_shadow_execution,
    make_shadow_batch_result,
    preflight_shadow_multibatch_budget,
    record_shadow_batch_attempt,
    request_shadow_cancellation,
    resume_shadow_execution,
    validate_shadow_batch_result,
    validate_shadow_capacity_plan,
)
from app.modules.single_prompt_v2.delivery_text import digest


def _scope(run_count: int = 22) -> dict:
    urls = [f"https://evidence.example/source/{index}" for index in range(run_count * 2)]
    runs = []
    snapshots = []
    dispositions = []
    for index in range(run_count):
        references = []
        for offset in range(2):
            url_index = index * 2 + offset
            url = urls[url_index]
            references.append({
                "reference_id": offset + 1,
                "index": offset + 1,
                "canonical_url": url,
                "url": url,
                "title": f"来源 {url_index}",
            })
            text = (f"来源 {url_index} 的冻结正文。" + "证据正文") * 48
            snapshots.append({
                "snapshot_id": f"snapshot-{url_index}",
                "source_key": f"source-{url_index}",
                "canonical_url": url,
                "title": f"来源 {url_index}",
                "content_hash": digest(text),
                "passages": [{
                    "passage_id": "passage-1",
                    "content_hash": digest(text),
                    "text": text,
                }],
            })
            dispositions.append({
                "source_key": f"source-{url_index}", "status": "AVAILABLE",
            })
        runs.append({
            "run_id": index + 1,
            "status": "success",
            "answer_text": f"第 {index + 1} 次回答。" + ("回答观察内容" * 35),
            "references": references,
            "brand_mentioned": False,
            "competitors": [],
        })
    return {
        "identity": {"project_id": 1, "prompt_id": 1},
        "prompt": {"prompt_id": 1, "prompt_text": "推荐一个合适的工具"},
        "project_configuration": {
            "brand": {"brand_name": "目标品牌", "brand_aliases": [], "website_url": ""},
        },
        "project_entities": {"competitors": []},
        "runs": runs,
        "citation_manifest": None,
        "source_snapshots": snapshots,
        "source_dispositions": dispositions,
        "product_truth": {"set_hash": digest([]), "facts": []},
        "brand_context": {"mode": "EMPTY"},
        "monitor_metrics": {"valid_answer_count": run_count},
        "qualification": {"delivery_level": "L3"},
    }


@pytest.fixture(scope="module")
def plan() -> dict:
    scope = _scope()
    value = bind_shadow_plan_to_frozen_scope(plan_evidence_pack_batches(scope), scope)
    assert value["status"] == "READY"
    assert value["batch_count"] >= 2
    return value


def _success_result(
    plan: dict, batch: dict, *, claim_value: str = "ABSENT",
    classification: str = "OBSERVED", predicate: str = "BRAND_LITERAL_PRESENCE",
) -> dict:
    finding_kind = "OBSERVATION"
    subject = "TARGET_BRAND"
    quantifier = "ANY_VALID_RUN"
    claim_identity_hash = digest({
        "finding_kind": finding_kind,
        "predicate": predicate,
        "subject": subject,
        "quantifier": quantifier,
    })
    batch_observations = [
        plan["shadow_run_manifest"][str(run_id)]["brand_literal_matched"]
        for run_id in batch["run_ids"]
    ]
    matched_count = sum(value is True for value in batch_observations)
    valid_run_count = sum(value is not None for value in batch_observations)
    unresolved_run_count = sum(value is None for value in batch_observations)
    if predicate == "BRAND_LITERAL_PRESENCE":
        classification = "UNKNOWN" if unresolved_run_count else "OBSERVED"
        claim_value = (
            None if unresolved_run_count else "PRESENT" if matched_count else "ABSENT"
        )
    finding = {
        "finding_id": f"finding-{batch['batch_number']}-{predicate}-{claim_value}",
        "finding_kind": finding_kind,
        "predicate": predicate,
        "subject": subject,
        "scope": "BATCH_VALID_SCOPE",
        "scope_batch_hash": batch["batch_hash"],
        "quantifier": quantifier,
        "claim_identity_hash": claim_identity_hash,
        "claim_value": None if classification == "UNKNOWN" else claim_value,
        "matched_count": matched_count if predicate == "BRAND_LITERAL_PRESENCE" else None,
        "valid_run_count": valid_run_count if predicate == "BRAND_LITERAL_PRESENCE" else None,
        "unresolved_run_count": (
            unresolved_run_count if predicate == "BRAND_LITERAL_PRESENCE" else None
        ),
        "statement": "批次内未发现目标品牌字面出现。",
        "classification": classification,
        "evidence_locators": [] if classification == "UNKNOWN" else [{
            "kind": "ANSWER_SPAN",
            "run_id": str(batch["run_ids"][0]),
            "answer_hash": plan["shadow_run_manifest"][str(batch["run_ids"][0])][
                "answer_hash"
            ],
            "start": 0,
            "end": 5,
        }],
    }
    return make_shadow_batch_result({
        "frozen_scope_hash": plan["frozen_scope_hash"],
        "plan_hash": plan["plan_hash"],
        "batch_hash": batch["batch_hash"],
        "batch_number": batch["batch_number"],
        "batch_result_id": f"batch-result-{batch['batch_number']}",
        "attempt_number": 1,
        "status": "SUCCESS",
        "response_hash": digest({"batch": batch["batch_hash"]}),
        "findings": [finding],
        "failure_code": None,
    })


def _failed_result(plan: dict, batch: dict) -> dict:
    return make_shadow_batch_result({
        "frozen_scope_hash": plan["frozen_scope_hash"],
        "plan_hash": plan["plan_hash"],
        "batch_hash": batch["batch_hash"],
        "batch_number": batch["batch_number"],
        "batch_result_id": f"batch-result-{batch['batch_number']}",
        "attempt_number": 1,
        "status": "FAILED",
        "response_hash": None,
        "findings": [],
        "failure_code": "MODEL_TRANSPORT_FAILED",
    })


def _reservation(plan: dict, max_attempts_per_batch: int = 2) -> dict:
    aggregate_reservation = 20_000
    return preflight_shadow_multibatch_budget(
        plan,
        aggregate_call_token_reservation=aggregate_reservation,
        max_requests=plan["batch_count"] * max_attempts_per_batch + 1,
        max_total_tokens=(
            plan["aggregate_total_token_reservation"] * max_attempts_per_batch
            + aggregate_reservation
        ),
        max_cost_cny=10.0,
        conservative_cny_per_million_tokens=1.0,
        max_attempts_per_batch=max_attempts_per_batch,
    )


def _state(plan: dict, max_attempts_per_batch: int = 2) -> dict:
    return initialize_shadow_execution(
        plan, budget_reservation=_reservation(plan, max_attempts_per_batch),
    )


def test_plan_and_batch_identity_are_fail_closed(plan):
    assert validate_shadow_capacity_plan(plan)["plan_hash"] == plan["plan_hash"]
    result = _success_result(plan, plan["batches"][0])
    assert validate_shadow_batch_result(plan, result).status == "SUCCESS"

    tampered_plan = deepcopy(plan)
    tampered_plan["batches"][0]["run_ids"].append("999")
    with pytest.raises(ShadowContractError, match="PLAN_HASH_MISMATCH"):
        validate_shadow_capacity_plan(tampered_plan)

    cross_scope = deepcopy(result)
    cross_scope["frozen_scope_hash"] = "foreign-scope"
    cross_scope["result_hash"] = digest({
        key: value for key, value in cross_scope.items() if key != "result_hash"
    })
    with pytest.raises(ShadowContractError, match="RESULT_SCOPE_MISMATCH"):
        validate_shadow_batch_result(plan, cross_scope)


def test_scope_binding_uses_v15_eligibility_and_empty_brand_is_unknown():
    scope = {
        "project_configuration": {"brand": {"brand_name": "", "brand_aliases": []}},
        "runs": [{
            "run_id": 1, "status": "partial_success", "answer_text": "完整但部分成功的回答",
        }],
    }
    raw_plan = {
        "frozen_scope_hash": digest(scope),
        "batches": [{"run_ids": ["1"]}],
    }
    bound = bind_shadow_plan_to_frozen_scope(raw_plan, scope)
    assert bound["shadow_eligibility_rule_version"].endswith("v2")
    assert bound["shadow_run_manifest"]["1"]["answer_length"] > 0
    assert bound["shadow_run_manifest"]["1"]["brand_literal_matched"] is None


def test_cross_batch_locator_and_result_hash_are_rejected(plan):
    result = _success_result(plan, plan["batches"][0])
    result["findings"][0]["evidence_locators"][0]["run_id"] = str(
        plan["batches"][1]["run_ids"][0]
    )
    result["result_hash"] = digest({
        key: value for key, value in result.items() if key != "result_hash"
    })
    with pytest.raises(ShadowContractError, match="CROSS_BATCH_RUN"):
        validate_shadow_batch_result(plan, result)

    for mutation, expected in (
        ({"answer_hash": "stale"}, "ANSWER_HASH_MISMATCH"),
        ({"end": 999_999}, "SPAN_OUT_OF_BOUNDS"),
        ({"citation_occurrence_id": "foreign-kind"}, "ValidationError"),
    ):
        result = _success_result(plan, plan["batches"][0])
        result["findings"][0]["evidence_locators"][0].update(mutation)
        result["result_hash"] = digest({
            key: value for key, value in result.items() if key != "result_hash"
        })
        error = Exception if expected == "ValidationError" else ShadowContractError
        with pytest.raises(error, match=expected if error is ShadowContractError else None):
            validate_shadow_batch_result(plan, result)

    result = _success_result(plan, plan["batches"][0])
    result["findings"][0]["statement"] = "tampered"
    with pytest.raises(ShadowContractError, match="RESULT_HASH_MISMATCH"):
        validate_shadow_batch_result(plan, result)


def test_complete_batches_build_shadow_input_without_business_result(plan):
    results = [_success_result(plan, batch) for batch in plan["batches"]]
    aggregate = build_shadow_aggregate_input(plan, results)
    assert aggregate["status"] == "READY_FOR_SHADOW_REVIEW"
    assert aggregate["conflicts"] == []
    assert aggregate["production_result_created"] is False
    assert aggregate["cutover_blocker"].endswith("MULTI_BATCH_RESULT_MERGE")
    assert aggregate["aggregate_input_hash"] == digest({
        key: value for key, value in aggregate.items() if key != "aggregate_input_hash"
    })

    missing_finding = deepcopy(results)
    missing_finding[0]["findings"] = []
    missing_finding[0]["result_hash"] = digest({
        key: value for key, value in missing_finding[0].items() if key != "result_hash"
    })
    recomputed = build_shadow_aggregate_input(plan, missing_finding)
    assert recomputed["aggregate_observations"] == aggregate["aggregate_observations"]

    duplicated = deepcopy(results)
    repeated = deepcopy(duplicated[0]["findings"][0])
    repeated["finding_id"] = "duplicate-semantic-finding"
    duplicated[0]["findings"].append(repeated)
    duplicated[0]["result_hash"] = digest({
        key: value for key, value in duplicated[0].items() if key != "result_hash"
    })
    with pytest.raises(ShadowContractError, match="FINDING_IDENTITY_DUPLICATED"):
        build_shadow_aggregate_input(plan, duplicated)


def test_conflict_and_unknown_are_preserved_not_voted_away(plan):
    present_plan = deepcopy(plan)
    present_run = str(present_plan["batches"][0]["run_ids"][0])
    present_plan["shadow_run_manifest"][present_run]["brand_literal_matched"] = True
    present_plan["plan_hash"] = digest({
        key: value for key, value in present_plan.items() if key != "plan_hash"
    })
    results = [
        _success_result(present_plan, batch)
        for batch in present_plan["batches"]
    ]
    aggregate = build_shadow_aggregate_input(present_plan, results)
    assert aggregate["status"] == "READY_FOR_SHADOW_REVIEW"
    assert aggregate["conflicts"] == []
    assert aggregate["aggregate_observations"][0]["claim_value"] == "PRESENT"

    unknown_plan = deepcopy(plan)
    unknown_run = str(unknown_plan["batches"][0]["run_ids"][0])
    unknown_plan["shadow_run_manifest"][unknown_run]["brand_literal_matched"] = None
    unknown_plan["plan_hash"] = digest({
        key: value for key, value in unknown_plan.items() if key != "plan_hash"
    })
    results = [_success_result(unknown_plan, batch) for batch in unknown_plan["batches"]]
    aggregate = build_shadow_aggregate_input(unknown_plan, results)
    assert aggregate["status"] == "REVIEW_REQUIRED_UNKNOWN"
    expected_identity = digest({
        "finding_kind": "OBSERVATION", "predicate": "BRAND_LITERAL_PRESENCE",
        "subject": "TARGET_BRAND", "quantifier": "ANY_VALID_RUN",
    })
    assert aggregate["unknown_claim_keys"] == [expected_identity]

    aggregate = build_shadow_aggregate_input(unknown_plan, results)
    assert aggregate["status"] == "REVIEW_REQUIRED_UNKNOWN"
    assert aggregate["unknown_claim_keys"] == [expected_identity]
    assert aggregate["conflicts"] == []
    assert aggregate["aggregate_observations"][0]["claim_value"] == "UNKNOWN"


def test_missing_failed_or_duplicate_batch_never_builds_aggregate(plan):
    success = [_success_result(plan, batch) for batch in plan["batches"]]
    with pytest.raises(ShadowContractError, match="BATCH_SET_MISMATCH"):
        build_shadow_aggregate_input(plan, success[:-1])
    failed = success[:-1] + [_failed_result(plan, plan["batches"][-1])]
    with pytest.raises(ShadowContractError, match="REQUIRES_ALL_BATCHES_SUCCESS"):
        build_shadow_aggregate_input(plan, failed)
    with pytest.raises(ShadowContractError, match="BATCH_DUPLICATED"):
        build_shadow_aggregate_input(plan, success + [success[0]])


def test_failure_retry_and_success_are_append_only_in_shadow_state(plan):
    first, second = plan["batches"][:2]
    state = _state(plan)
    state = record_shadow_batch_attempt(
        state, batch_hash=first["batch_hash"], outcome="FAILED",
        failure_code="TRANSIENT_FAILURE",
    )
    assert state["status"] == "FAILED_RECOVERABLE"
    assert state["batches"][first["batch_hash"]]["attempts"][0]["outcome"] == "FAILED"
    with pytest.raises(ShadowContractError, match="RETRY_REQUIRES_RESUME"):
        record_shadow_batch_attempt(
            state, batch_hash=first["batch_hash"], outcome="SUCCESS", result_hash="result-1",
        )
    state = resume_shadow_execution(state)
    state = record_shadow_batch_attempt(
        state, batch_hash=first["batch_hash"], outcome="SUCCESS", result_hash="result-1",
    )
    attempts = state["batches"][first["batch_hash"]]["attempts"]
    assert [row["attempt_number"] for row in attempts] == [1, 2]
    assert [row["outcome"] for row in attempts] == ["FAILED", "SUCCESS"]
    with pytest.raises(ShadowContractError, match="SUCCESS_IMMUTABLE"):
        record_shadow_batch_attempt(
            state, batch_hash=first["batch_hash"], outcome="SUCCESS", result_hash="rewrite",
        )
    for batch in plan["batches"][1:]:
        state = record_shadow_batch_attempt(
            state, batch_hash=batch["batch_hash"], outcome="SUCCESS",
            result_hash=f"result-{batch['batch_number']}",
        )
    assert state["status"] == "READY_FOR_SHADOW_AGGREGATE"
    assert second["batch_hash"] in state["batches"]

    exhausted = _state(plan, max_attempts_per_batch=1)
    exhausted = record_shadow_batch_attempt(
        exhausted, batch_hash=first["batch_hash"], outcome="FAILED",
        failure_code="FINAL_FAILURE",
    )
    assert exhausted["status"] == "FAILED_TERMINAL"
    with pytest.raises(ShadowContractError, match="NOT_RECOVERABLE"):
        resume_shadow_execution(exhausted)

    mixed_state = _state(plan)
    mixed_state = record_shadow_batch_attempt(
        mixed_state, batch_hash=first["batch_hash"], outcome="FAILED",
        failure_code="TRANSIENT_FAILURE",
    )
    mixed_state = record_shadow_batch_attempt(
        mixed_state, batch_hash=second["batch_hash"], outcome="SUCCESS",
        result_hash="second-success",
    )
    assert mixed_state["status"] == "FAILED_RECOVERABLE"


def test_cancellation_keeps_success_and_blocks_new_attempts(plan):
    state = _state(plan)
    first = plan["batches"][0]
    state = record_shadow_batch_attempt(
        state, batch_hash=first["batch_hash"], outcome="SUCCESS", result_hash="result-1",
    )
    state = request_shadow_cancellation(state)
    assert state["status"] == "CANCEL_REQUESTED"
    with pytest.raises(ShadowContractError, match="TERMINAL_OR_CANCELLING"):
        record_shadow_batch_attempt(
            state, batch_hash=plan["batches"][1]["batch_hash"],
            outcome="SUCCESS", result_hash="late-result",
        )
    state = acknowledge_shadow_cancellation(state)
    assert state["status"] == "CANCELLED"
    assert state["batches"][first["batch_hash"]]["status"] == "SUCCESS"
    assert all(
        row["status"] in {"SUCCESS", "CANCELLED"} for row in state["batches"].values()
    )

    ready = _state(plan)
    for batch in plan["batches"]:
        ready = record_shadow_batch_attempt(
            ready, batch_hash=batch["batch_hash"], outcome="SUCCESS",
            result_hash=f"ready-{batch['batch_number']}",
        )
    assert ready["status"] == "READY_FOR_SHADOW_AGGREGATE"
    ready = request_shadow_cancellation(ready)
    assert ready["status"] == "CANCEL_REQUESTED"


def test_budget_preflight_is_all_calls_or_zero_calls(plan):
    aggregate_reservation = 20_000
    enough_tokens = plan["aggregate_total_token_reservation"] * 2 + aggregate_reservation
    ready = preflight_shadow_multibatch_budget(
        plan,
        aggregate_call_token_reservation=aggregate_reservation,
        max_requests=plan["batch_count"] * 2 + 1,
        max_total_tokens=enough_tokens,
        max_cost_cny=10.0,
        conservative_cny_per_million_tokens=1.0,
    )
    assert ready["status"] == "READY_FOR_EXPLICIT_AUTHORIZATION"
    assert ready["external_calls"] == 0
    assert ready["max_attempts_per_batch"] == 2

    blocked = preflight_shadow_multibatch_budget(
        plan,
        aggregate_call_token_reservation=aggregate_reservation,
        max_requests=plan["batch_count"],
        max_total_tokens=enough_tokens - 1,
        max_cost_cny=0.0,
        conservative_cny_per_million_tokens=1.0,
    )
    assert blocked["status"] == "BLOCKED_ZERO_CALLS"
    assert blocked["block_reasons"] == [
        "REQUEST_CAP_EXCEEDED", "TOKEN_CAP_EXCEEDED", "COST_CAP_EXCEEDED",
    ]
    assert blocked["external_calls"] == 0
    for invalid in (-1, float("nan")):
        with pytest.raises(ShadowContractError, match="BUDGET_VALUE_INVALID"):
            preflight_shadow_multibatch_budget(
                plan, aggregate_call_token_reservation=invalid,
                max_requests=plan["batch_count"] * 2 + 1,
                max_total_tokens=enough_tokens, max_cost_cny=10.0,
                conservative_cny_per_million_tokens=1.0,
            )
    for invalid_attempts in (True, 1.5, float("nan"), 0, 6):
        with pytest.raises(ShadowContractError, match="MAX_ATTEMPTS_INVALID"):
            preflight_shadow_multibatch_budget(
                plan, aggregate_call_token_reservation=aggregate_reservation,
                max_requests=100, max_total_tokens=enough_tokens,
                max_cost_cny=10.0, conservative_cny_per_million_tokens=1.0,
                max_attempts_per_batch=invalid_attempts,
            )


def test_shadow_contract_does_not_change_single_pack_or_scope(plan):
    scope = _scope()
    original = deepcopy(scope)
    pack_before = build_evidence_pack(scope)
    validate_shadow_capacity_plan(plan)
    _state(plan)
    pack_after = build_evidence_pack(scope)
    assert scope == original
    assert pack_after == pack_before
    assert pack_after["evidence_pack_hash"] == pack_before["evidence_pack_hash"]
