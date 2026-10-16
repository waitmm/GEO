from __future__ import annotations

from pathlib import Path

import pytest

from scripts.live_model_budget import BudgetDenied, finish, initialize, reserve, summary


def _identity(index: int, *, attempt: int = 1, tokens: int = 100_000) -> dict:
    return {
        "provider": "deepseek",
        "requested_model_alias": "deepseek-v4-flash",
        "effective_request_model": "deepseek-flash",
        "provider_payload_hash": f"{index:064x}",
        "input_hash": f"{index + 100:064x}",
        "input_token_upper_bound": tokens - 4096,
        "max_output_tokens": 4096,
        "attempt": attempt,
    }


def _init(path: Path) -> None:
    initialize(
        path,
        pricing_source="https://api-docs.deepseek.com/quick_start/pricing/ checked at peak rate",
        pricing_checked_at="2026-10-16",
    )


def test_live_budget_is_atomic_counted_and_never_refunds_failures(tmp_path):
    ledger = tmp_path / "budget.sqlite3"
    _init(ledger)

    first = reserve(ledger, task_scope="T09", request_id="t09-1", identity=_identity(1))
    assert first["reserved_cost_cny"] == 1.0
    with pytest.raises(BudgetDenied, match="ANOTHER_REQUEST_IS_ALREADY_RESERVED"):
        reserve(ledger, task_scope="T23", request_id="t23-1", identity=_identity(2))
    finish(ledger, request_id="t09-1", status="TIMEOUT", outcome={"request_may_have_been_sent": True})

    reserve(ledger, task_scope="T09", request_id="t09-2", identity=_identity(2))
    finish(ledger, request_id="t09-2", status="FINISHED", outcome={"actual_tokens": 10})
    reserve(ledger, task_scope="T09", request_id="t09-3", identity=_identity(3))
    finish(ledger, request_id="t09-3", status="FAILED", outcome={"provider_status": 500})

    with pytest.raises(BudgetDenied, match="TASK_REQUEST_LIMIT_EXHAUSTED"):
        reserve(ledger, task_scope="T09", request_id="t09-4", identity=_identity(4))
    report = summary(ledger)
    assert report["used_requests"] == 3
    assert report["by_task"] == {"T09": 3, "T23": 0}
    assert report["reserved_cost_cny"] == 3.0


def test_live_budget_rejects_retry_duplicate_model_and_config_drift(tmp_path):
    ledger = tmp_path / "budget.sqlite3"
    _init(ledger)
    with pytest.raises(BudgetDenied, match="AUTOMATIC_RETRY_FORBIDDEN"):
        reserve(ledger, task_scope="T09", request_id="retry", identity=_identity(1, attempt=2))
    wrong = {**_identity(2), "effective_request_model": "deepseek-v4-pro"}
    with pytest.raises(BudgetDenied, match="PROVIDER_OR_MODEL_NOT_AUTHORIZED"):
        reserve(ledger, task_scope="T09", request_id="wrong-model", identity=wrong)

    reserve(ledger, task_scope="T23", request_id="same", identity=_identity(3))
    finish(ledger, request_id="same", status="DELIVERY_UNKNOWN", outcome={})
    with pytest.raises(BudgetDenied, match="REQUEST_ALREADY_RESERVED_NO_RETRY"):
        reserve(ledger, task_scope="T23", request_id="other", identity=_identity(3))
    with pytest.raises(BudgetDenied, match="AUTHORIZED_BATCH_CONFIG_MISMATCH"):
        initialize(
            ledger,
            total_request_limit=11,
            pricing_source="official",
            pricing_checked_at="2026-10-16",
        )


def test_live_budget_enforces_global_cost_before_insert(tmp_path):
    ledger = tmp_path / "budget.sqlite3"
    _init(ledger)
    expensive = _identity(1, tokens=4_100_000)
    with pytest.raises(BudgetDenied, match="TASK_COST_LIMIT_EXHAUSTED"):
        reserve(ledger, task_scope="T09", request_id="too-expensive", identity=expensive)
    assert summary(ledger)["used_requests"] == 0
