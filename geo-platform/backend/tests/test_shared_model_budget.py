from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import hashlib

import pytest

from app.services.shared_model_budget import (
    PRICING_SOURCE,
    SharedBudgetDenied,
    SharedBudgetHooks,
    initialize,
    reserve,
    settle,
    summary,
)


TODAY = date(2026, 10, 19)


def identity(seed: str = "a", *, input_ceiling: int = 10_000, output_ceiling: int = 8_000,
             attempt: int = 1):
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return {
        "provider": "deepseek",
        "requested_model_alias": "deepseek-flash",
        "effective_request_model": "deepseek-flash",
        "endpoint": "https://api.deepseek.com/responses",
        "endpoint_path": "/responses",
        "transport_kind": "RESPONSES_JSON_SCHEMA",
        "provider_payload_hash": digest,
        "input_hash": hashlib.sha256(f"input:{seed}".encode()).hexdigest(),
        "input_token_upper_bound": input_ceiling,
        "max_output_tokens": output_ceiling,
        "attempt": attempt,
    }


def ledger(tmp_path):
    path = tmp_path / "shared-budget.sqlite3"
    initialize(path, batch_id="geo-agent-comparison-20261019",
               pricing_checked_at=TODAY.isoformat(), today=TODAY)
    return path


def test_authorized_batch_is_exact_and_pricing_must_be_current(tmp_path):
    path = ledger(tmp_path)
    state = summary(path)
    assert state["config"]["pricing_source"] == PRICING_SOURCE
    assert state["config"]["total_request_limit"] == 36
    assert state["config"]["total_token_limit"] == 3_000_000
    assert state["config"]["total_cost_limit_cny"] == 30
    assert state["config"]["automatic_retries"] == 0
    assert state["config"]["max_concurrency"] == 1
    assert state["config"]["effective_request_model"] == "deepseek-flash"
    with pytest.raises(SharedBudgetDenied, match="PRICING_EVIDENCE_STALE"):
        initialize(tmp_path / "stale.sqlite3", batch_id="x",
                   pricing_checked_at=(TODAY - timedelta(days=8)).isoformat(), today=TODAY)
    with pytest.raises(SharedBudgetDenied, match="AUTHORIZED_BATCH_CONFIG_MISMATCH"):
        initialize(tmp_path / "cheap.sqlite3", batch_id="x", pricing_checked_at=TODAY.isoformat(),
                   conservative_cny_per_million_tokens=9.99, today=TODAY)


def test_success_settles_to_actual_usage_and_restart_keeps_state(tmp_path):
    path = ledger(tmp_path)
    reserve(path, lane="AGENT_EXPERIMENT", operation_id="agent-1", request_id="request-1",
            identity=identity())
    before = summary(path)
    assert before["used_tokens"] == 18_000
    assert before["used_cost_cny"] == 0.18
    settle(path, request_id="request-1", status="FINISHED", outcome={
        "token_usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}
    })
    after_restart = summary(path)
    assert after_restart["used_requests"] == 1
    assert after_restart["used_tokens"] == 1500
    assert after_restart["used_cost_cny"] == 0.015
    assert after_restart["requests"][0]["actual_peak_price_cost_cny"] == 0.006


def test_unknown_delivery_holds_full_reservation_and_no_retry(tmp_path):
    path = ledger(tmp_path)
    request = identity()
    reserve(path, lane="AGENT_EXPERIMENT", operation_id="agent-1", request_id="request-1",
            identity=request)
    settle(path, request_id="request-1", status="DELIVERY_UNKNOWN", outcome={"token_usage": {}})
    state = summary(path)
    assert state["used_tokens"] == 18_000
    assert state["used_cost_cny"] == 0.18
    with pytest.raises(SharedBudgetDenied, match="REQUEST_ALREADY_RESERVED_NO_RETRY"):
        reserve(path, lane="AGENT_EXPERIMENT", operation_id="agent-1", request_id="request-2",
                identity=request)
    with pytest.raises(SharedBudgetDenied, match="AUTOMATIC_RETRY_FORBIDDEN"):
        reserve(path, lane="AGENT_EXPERIMENT", operation_id="agent-1", request_id="request-3",
                identity=identity("retry", attempt=2))


def test_concurrent_reservations_fail_closed(tmp_path):
    path = ledger(tmp_path)

    def attempt(number):
        try:
            reserve(path, lane="AGENT_EXPERIMENT", operation_id=f"agent-{number}",
                    request_id=f"request-{number}", identity=identity(str(number)))
            return "ADMITTED"
        except SharedBudgetDenied as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, (1, 2)))
    assert outcomes.count("ADMITTED") == 1
    assert outcomes.count("CONCURRENCY_LIMIT_EXCEEDED") == 1
    assert summary(path)["in_flight"] == 1


def test_shared_limits_cover_agent_and_workflow_lanes(tmp_path):
    path = ledger(tmp_path)
    agent = SharedBudgetHooks(path, lane="AGENT_EXPERIMENT", operation_id="agent-1")
    agent_request = identity("agent", input_ceiling=1_000_000, output_ceiling=500_000)
    agent.request_guard(agent_request)
    agent.audit_sink({"request_identity": agent_request, "validation_status": "ACCEPTED",
                      "response_source": "EXTERNAL_LLM",
                      "token_usage": {"prompt_tokens": 900_000, "completion_tokens": 400_000,
                                      "total_tokens": 1_300_000}})
    workflow = SharedBudgetHooks(path, lane="WORKFLOW_BASELINE", operation_id="workflow-1")
    workflow_request = identity("workflow", input_ceiling=1_000_000, output_ceiling=700_001)
    with pytest.raises(SharedBudgetDenied, match="GLOBAL_TOKEN_LIMIT_EXHAUSTED"):
        workflow.request_guard(workflow_request)
    state = summary(path)
    assert state["by_lane"] == {"AGENT_EXPERIMENT": 1, "WORKFLOW_BASELINE": 0}


def test_cost_and_request_overages_are_denied(tmp_path):
    path = ledger(tmp_path)
    for number in range(36):
        request = identity(f"request-{number}", input_ceiling=1, output_ceiling=1)
        request_id = f"request-{number}"
        reserve(path, lane="WORKFLOW_BASELINE", operation_id="baseline",
                request_id=request_id, identity=request)
        settle(path, request_id=request_id, status="FINISHED", outcome={
            "token_usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
        })
    with pytest.raises(SharedBudgetDenied, match="GLOBAL_REQUEST_LIMIT_EXHAUSTED"):
        reserve(path, lane="AGENT_EXPERIMENT", operation_id="agent", request_id="request-over",
                identity=identity("over", input_ceiling=1, output_ceiling=1))


def test_hooks_mark_unhandled_send_as_delivery_unknown(tmp_path):
    path = ledger(tmp_path)
    hooks = SharedBudgetHooks(path, lane="AGENT_EXPERIMENT", operation_id="agent-1")
    request = identity("unknown")
    hooks.request_guard(request)
    hooks.settle_unknown(TimeoutError("unknown"))
    state = summary(path)
    assert state["requests"][0]["status"] == "DELIVERY_UNKNOWN"
    assert state["remaining_tokens"] == 3_000_000 - 18_000
