from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import hashlib

import pytest

from app.services.shared_model_budget import (
    PRICING_SOURCE,
    SharedBudgetDenied,
    SharedBudgetHooks,
    append_transport_authorization,
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


def authorize_text(path, *, operation_id="evidence-pack-run"):
    return append_transport_authorization(
        path,
        authorization_id="evidence-pack-p1-p1-r1-20261020",
        batch_id="geo-agent-comparison-20261019",
        lane="AGENT_EXPERIMENT",
        operation_id=operation_id,
        scope={"project_id": 1, "prompt_id": 1, "run_ids": [1]},
        transport_kind="RESPONSES_TEXT",
        transport_version="geo.deepseek.responses-text.v1",
        prompt_version="geo-evidence-pack-synthesis.v1",
        schema_version="geo.evidence-pack.markdown-result.v1",
        execution_contract="geo.evidence-pack.execution.v1",
        pricing_checked_at=TODAY.isoformat(),
        max_requests=1,
        max_tokens=300_000,
        max_cost_cny=3.0,
        authorized_by="explicit-user-authorization",
        today=TODAY,
    )


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


def test_existing_authorization_fail_closes_for_unapproved_plain_text_transport(tmp_path):
    path = ledger(tmp_path)
    request = identity("evidence-pack-text")
    request["transport_kind"] = "RESPONSES_TEXT"
    with pytest.raises(SharedBudgetDenied, match="MODEL_OR_TRANSPORT_NOT_AUTHORIZED"):
        reserve(path, lane="AGENT_EXPERIMENT", operation_id="evidence-pack-offline",
                request_id="evidence-pack-text-1", identity=request)
    assert summary(path)["used_requests"] == 0


def test_append_only_text_authorization_is_exact_and_preserves_base_config(tmp_path):
    path = ledger(tmp_path)
    before = summary(path)
    authorization = authorize_text(path)
    after_append = summary(path)
    assert after_append["config_hash"] == before["config_hash"]
    assert after_append["requests"] == before["requests"] == []
    assert authorization["parent_config_hash"] == before["config_hash"]
    assert authorization["max_requests"] == 1
    assert authorization["provider_peak_rates_cny_per_million"] == {
        "input_cache_hit": 0.04, "input_cache_miss": 2.0, "output": 8.0,
    }
    assert after_append["authorization_extensions"][0]["used_requests"] == 0

    request = identity("evidence-pack-authorized", input_ceiling=20_000, output_ceiling=16_384)
    request.update({
        "transport_kind": "RESPONSES_TEXT",
        "transport_version": "geo.deepseek.responses-text.v1",
        "prompt_version": "geo-evidence-pack-synthesis.v1",
        "schema_version": "geo.evidence-pack.markdown-result.v1",
    })
    reserve(path, lane="AGENT_EXPERIMENT", operation_id="evidence-pack-run",
            request_id="evidence-pack-request", identity=request)
    settle(path, request_id="evidence-pack-request", status="FINISHED", outcome={
        "token_usage": {"input_tokens": 10_000, "output_tokens": 4_000,
                        "total_tokens": 14_000},
    })
    restarted = summary(path)
    extension = restarted["authorization_extensions"][0]
    assert restarted["used_requests"] == extension["used_requests"] == 1
    assert extension["used_tokens"] == 14_000
    assert extension["remaining_requests"] == 0
    assert restarted["requests"][0]["authorization_id"] == authorization["authorization_id"]
    with pytest.raises(SharedBudgetDenied, match="AUTHORIZATION_REQUEST_LIMIT_EXHAUSTED"):
        second = {**request, "provider_payload_hash": hashlib.sha256(b"second").hexdigest(),
                  "input_hash": hashlib.sha256(b"second-input").hexdigest()}
        reserve(path, lane="AGENT_EXPERIMENT", operation_id="evidence-pack-run",
                request_id="evidence-pack-request-2", identity=second)


def test_text_authorization_rejects_wrong_scope_versions_and_is_immutable(tmp_path):
    path = ledger(tmp_path)
    authorize_text(path)
    request = identity("wrong-text")
    request.update({
        "transport_kind": "RESPONSES_TEXT",
        "transport_version": "geo.deepseek.responses-text.v1",
        "prompt_version": "geo-evidence-pack-synthesis.v1",
        "schema_version": "geo.evidence-pack.markdown-result.v1",
    })
    for field, wrong in (
        ("transport_version", "other"), ("prompt_version", "other"),
        ("schema_version", "other"),
    ):
        altered = {**request, field: wrong}
        with pytest.raises(SharedBudgetDenied, match="MODEL_OR_TRANSPORT_NOT_AUTHORIZED"):
            reserve(path, lane="AGENT_EXPERIMENT", operation_id="evidence-pack-run",
                    request_id=f"wrong-{field}", identity=altered)
    with pytest.raises(SharedBudgetDenied, match="MODEL_OR_TRANSPORT_NOT_AUTHORIZED"):
        reserve(path, lane="AGENT_EXPERIMENT", operation_id="different-run",
                request_id="wrong-operation", identity=request)
    with pytest.raises(SharedBudgetDenied, match="AUTHORIZATION_EXTENSION_IMMUTABLE"):
        append_transport_authorization(
            path, authorization_id="evidence-pack-p1-p1-r1-20261020",
            batch_id="geo-agent-comparison-20261019", lane="AGENT_EXPERIMENT",
            operation_id="different-run", scope={"project_id": 1},
            transport_kind="RESPONSES_TEXT", transport_version="geo.deepseek.responses-text.v1",
            prompt_version="geo-evidence-pack-synthesis.v1",
            schema_version="geo.evidence-pack.markdown-result.v1",
            execution_contract="geo.evidence-pack.execution.v1",
            pricing_checked_at=TODAY.isoformat(), max_requests=1, max_tokens=300_000,
            max_cost_cny=3.0, authorized_by="explicit-user-authorization", today=TODAY,
        )


def test_text_authorization_token_and_cost_limits_fail_closed(tmp_path):
    path = ledger(tmp_path)
    authorize_text(path)
    request = identity("text-over", input_ceiling=284_000, output_ceiling=16_384)
    request.update({
        "transport_kind": "RESPONSES_TEXT",
        "transport_version": "geo.deepseek.responses-text.v1",
        "prompt_version": "geo-evidence-pack-synthesis.v1",
        "schema_version": "geo.evidence-pack.markdown-result.v1",
    })
    with pytest.raises(SharedBudgetDenied, match="AUTHORIZATION_TOKEN_LIMIT_EXHAUSTED"):
        reserve(path, lane="AGENT_EXPERIMENT", operation_id="evidence-pack-run",
                request_id="text-over", identity=request)
    assert summary(path)["used_requests"] == 0


def test_text_authorization_keeps_legacy_transport_and_concurrency_guard(tmp_path):
    path = ledger(tmp_path)
    authorize_text(path)
    legacy = identity("legacy-after-extension")
    reserve(path, lane="WORKFLOW_BASELINE", operation_id="workflow",
            request_id="legacy-request", identity=legacy)
    text_request = identity("text-while-in-flight")
    text_request.update({
        "transport_kind": "RESPONSES_TEXT",
        "transport_version": "geo.deepseek.responses-text.v1",
        "prompt_version": "geo-evidence-pack-synthesis.v1",
        "schema_version": "geo.evidence-pack.markdown-result.v1",
    })
    with pytest.raises(SharedBudgetDenied, match="CONCURRENCY_LIMIT_EXCEEDED"):
        reserve(path, lane="AGENT_EXPERIMENT", operation_id="evidence-pack-run",
                request_id="text-request", identity=text_request)
    state = summary(path)
    assert state["used_requests"] == 1
    assert state["authorization_extensions"][0]["used_requests"] == 0


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


def test_settlement_replay_after_process_restart_is_idempotent(tmp_path):
    path = ledger(tmp_path)
    request = identity("restart-idempotence")
    first = SharedBudgetHooks(path, lane="AGENT_EXPERIMENT", operation_id="agent-restart")
    first.request_guard(request)
    event = {
        "request_identity": request, "response_source": "EXTERNAL_LLM",
        "validation_status": "REJECTED", "finish_reason": "incomplete",
        "response_model": "deepseek-flash", "provider_response_id": "resp-restart",
        "provider_response_status": "incomplete", "incomplete_reason": "max_output_tokens",
        "provider_output_summary": [{"type": "message", "status": "incomplete"}],
        "partial_output_text": "partial but not publishable",
        "raw_response_hash": "f" * 64, "rejection_code": "PROVIDER_INCOMPLETE",
        "token_usage": {"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500},
    }
    first.audit_sink(event)
    first.audit_sink(event)

    restarted = SharedBudgetHooks(path, lane="AGENT_EXPERIMENT", operation_id="agent-restart")
    restarted.audit_sink(event)
    state = summary(path)
    assert state["used_requests"] == 1 and state["used_tokens"] == 1500
    assert state["requests"][0]["status"] == "FAILED"

    changed = {**event, "incomplete_reason": "content_filter"}
    with pytest.raises(SharedBudgetDenied, match="REQUEST_ALREADY_SETTLED_DIFFERENT_OUTCOME"):
        SharedBudgetHooks(
            path, lane="AGENT_EXPERIMENT", operation_id="agent-restart",
        ).audit_sink(changed)


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
