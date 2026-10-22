"""Persistent, deployment-scoped model budget for the local internal Beta.

This adapter deliberately keeps the daily-use ledger separate from historical
experiment ledgers. It only authorizes the frozen Evidence Pack execution
profile and reuses the shared atomic reserve/settle implementation.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import AgentExperimentRun
from app.modules.agent_experiment.evidence_pack import (
    EVIDENCE_PACK_EXECUTION_CONTRACT,
    EVIDENCE_PACK_PROMPT_VERSION,
    EVIDENCE_PACK_RESULT_CONTRACT,
    EVIDENCE_PACK_TRANSPORT_VERSION,
)
from app.services.serialization import loads
from app.services.shared_model_budget import (
    PRICING_SOURCE,
    SharedBudgetDenied,
    SharedBudgetHooks,
    append_transport_authorization,
    initialize,
    summary,
)


DAILY_AUTHORIZATION_SCOPE = "INTERNAL_BETA_DAILY"


def _enabled() -> bool:
    return os.environ.get("GEO_AGENT_BETA_DAILY_MODEL_CALLS") == "1"


def _ledger_path() -> Path:
    value = os.environ.get("GEO_AGENT_BETA_BUDGET_LEDGER_PATH", "").strip()
    if not value:
        raise SharedBudgetDenied("BETA_DAILY_BUDGET_LEDGER_NOT_CONFIGURED")
    return Path(value)


def _batch_id() -> str:
    value = os.environ.get("GEO_AGENT_BETA_BUDGET_BATCH_ID", "").strip()
    if not value:
        raise SharedBudgetDenied("BETA_DAILY_BUDGET_ID_NOT_CONFIGURED")
    return value


def initialize_daily_budget() -> dict[str, Any]:
    if not _enabled():
        raise SharedBudgetDenied("BETA_DAILY_MODEL_CALLS_DISABLED")
    pricing_checked_at = os.environ.get(
        "GEO_AGENT_BETA_BUDGET_PRICING_CHECKED_AT", ""
    ).strip()
    return initialize(
        _ledger_path(), batch_id=_batch_id(),
        pricing_checked_at=pricing_checked_at, pricing_source=PRICING_SOURCE,
        total_request_limit=36, total_token_limit=3_000_000,
        total_cost_limit_cny=30.0,
        conservative_cny_per_million_tokens=10.0,
    )


def daily_budget_summary() -> dict[str, Any]:
    if not _enabled():
        raise SharedBudgetDenied("BETA_DAILY_MODEL_CALLS_DISABLED")
    return summary(_ledger_path())


def append_run_authorization(
    db: Session, *, run_id: str, project_id: int, prompt_id: int,
    revision: int, max_requests: int, max_total_tokens: int,
    max_cost_cny: float, conservative_cny_per_million_tokens: float,
    pricing_source: str, pricing_checked_at: str, authorized_by: str,
) -> dict[str, Any]:
    if not _enabled():
        raise SharedBudgetDenied("BETA_DAILY_MODEL_CALLS_DISABLED")
    row = db.query(AgentExperimentRun).filter_by(
        run_id=run_id, project_id=project_id, prompt_id=prompt_id,
    ).one_or_none()
    if not row:
        raise SharedBudgetDenied("BETA_AGENT_RUN_NOT_FOUND")
    if row.status != "WAITING_AUTHORIZATION" or row.revision != revision:
        raise SharedBudgetDenied("BETA_AGENT_RUN_AUTHORIZATION_STATE_CHANGED")
    execution = loads(row.agent_execution_json, {})
    if execution.get("contract_version") != EVIDENCE_PACK_EXECUTION_CONTRACT:
        raise SharedBudgetDenied("BETA_DAILY_ONLY_SUPPORTS_CURRENT_EVIDENCE_PACK")
    if max_requests != 1 or max_total_tokens > 300_000 or max_cost_cny > 5.0:
        raise SharedBudgetDenied("BETA_DAILY_TASK_LIMIT_EXCEEDED")
    if conservative_cny_per_million_tokens < 10.0:
        raise SharedBudgetDenied("BETA_DAILY_CONSERVATIVE_PRICE_TOO_LOW")
    if pricing_source.rstrip("/") != PRICING_SOURCE.rstrip("/"):
        raise SharedBudgetDenied("BETA_DAILY_PRICING_SOURCE_MISMATCH")
    return append_transport_authorization(
        _ledger_path(), authorization_id=f"{_batch_id()}:{run_id}",
        batch_id=_batch_id(), lane="AGENT_EXPERIMENT", operation_id=run_id,
        scope={
            "authorization_scope": DAILY_AUTHORIZATION_SCOPE,
            "project_id": project_id, "prompt_id": prompt_id,
            "analysis_id": row.analysis_id, "context_id": row.context_id,
            "input_scope_hash": row.input_scope_hash,
            "agent_execution_hash": row.agent_execution_hash,
            "task_limits": {
                "max_requests": max_requests,
                "max_total_tokens": max_total_tokens,
                "max_cost_cny": max_cost_cny,
                "conservative_cny_per_million_tokens":
                    conservative_cny_per_million_tokens,
            },
        },
        transport_kind="RESPONSES_TEXT",
        transport_version=EVIDENCE_PACK_TRANSPORT_VERSION,
        prompt_version=EVIDENCE_PACK_PROMPT_VERSION,
        schema_version=EVIDENCE_PACK_RESULT_CONTRACT,
        execution_contract=EVIDENCE_PACK_EXECUTION_CONTRACT,
        pricing_checked_at=pricing_checked_at,
        max_requests=1, max_tokens=300_000, max_cost_cny=5.0,
        authorized_by=authorized_by,
    )


def hooks_for_run(run: AgentExperimentRun) -> SharedBudgetHooks:
    if not _enabled():
        raise SharedBudgetDenied("BETA_DAILY_MODEL_CALLS_DISABLED")
    daily_budget_summary()
    return SharedBudgetHooks(
        _ledger_path(), lane="AGENT_EXPERIMENT", operation_id=run.run_id,
    )
