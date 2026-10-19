"""Offline, append-only reconciliation of Agent Run usage from the shared ledger."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import AgentEvent, AgentExperimentRun
from app.modules.single_prompt_v2.delivery_text import digest
from app.services.serialization import loads
from app.services.shared_model_budget import COUNTED_STATUSES


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _ledger_rows(ledger_path: Path, run_id: str) -> tuple[list[dict[str, Any]], str]:
    connection = sqlite3.connect(f"file:{ledger_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        config = connection.execute(
            "SELECT config_json,config_hash FROM budget_config WHERE singleton=1"
        ).fetchone()
        rows = [dict(row) for row in connection.execute(
            "SELECT * FROM model_requests WHERE operation_id=? ORDER BY reserved_at,request_id",
            (run_id,),
        )]
    finally:
        connection.close()
    if not config or digest(json.loads(config["config_json"])) != config["config_hash"]:
        raise RuntimeError("SHARED_LEDGER_CONFIG_HASH_MISMATCH")
    if not rows:
        raise RuntimeError("SHARED_LEDGER_AGENT_RUN_NOT_FOUND")
    if any(row["status"] == "RESERVED" for row in rows):
        raise RuntimeError("SHARED_LEDGER_AGENT_RUN_HAS_IN_FLIGHT_REQUEST")
    if any(row["status"] not in COUNTED_STATUSES for row in rows):
        raise RuntimeError("SHARED_LEDGER_AGENT_RUN_STATUS_INVALID")
    snapshot = {
        "config_hash": config["config_hash"],
        "rows": rows,
    }
    return rows, digest(snapshot)


def reconcile_agent_run_usage(
    db: Session, *, ledger_path: Path, run_id: str,
) -> dict[str, Any]:
    """Make the isolated Run projection match its immutable shared-ledger rows."""
    run = db.query(AgentExperimentRun).filter_by(run_id=run_id).one_or_none()
    if run is None:
        raise RuntimeError("AGENT_RUN_NOT_FOUND")
    rows, ledger_snapshot_hash = _ledger_rows(ledger_path, run_id)
    request_count = len(rows)
    input_tokens = sum(int(row["actual_input_tokens"] or 0) for row in rows)
    output_tokens = sum(int(row["actual_output_tokens"] or 0) for row in rows)
    accounted_tokens = sum(int(row["accounted_tokens"]) for row in rows)
    accounted_cost = round(sum(float(row["accounted_cost_cny"]) for row in rows), 8)
    state = "DELIVERY_UNKNOWN" if any(row["status"] == "DELIVERY_UNKNOWN" for row in rows) else "SETTLED"
    after = {
        "model_call_count": request_count,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_cny": accounted_cost,
        "external_request_state": state,
        "reserved_requests": request_count,
        "reserved_tokens": accounted_tokens,
        "reserved_cost_cny": accounted_cost,
        "progress_reserved_tokens": 0,
        "progress_reserved_cost_cny": 0.0,
        "progress_actual_tokens": accounted_tokens,
        "progress_actual_cost_cny": accounted_cost,
    }
    reconciliation_hash = digest({
        "contract_version": "geo.agent.model-usage-reconciliation.v2",
        "run_id": run_id,
        "ledger_snapshot_hash": ledger_snapshot_hash,
        "after": after,
    })
    existing = db.query(AgentEvent).filter_by(
        agent_run_id=run_id, event_type="MODEL_USAGE_RECONCILED",
    ).all()
    for event in existing:
        if loads(event.payload_json, {}).get("reconciliation_hash") == reconciliation_hash:
            return {"changed": False, "reconciliation_hash": reconciliation_hash,
                    "ledger_snapshot_hash": ledger_snapshot_hash, **after}
    before = {
        "model_call_count": run.model_call_count,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "cost_cny": run.cost_cny,
        "progress": loads(run.progress_json, {}),
        "authorization": loads(run.authorization_json, {}),
    }
    authorization = before["authorization"]
    progress = before["progress"]
    run.model_call_count = request_count
    run.input_tokens = input_tokens
    run.output_tokens = output_tokens
    run.cost_cny = accounted_cost
    run.authorization_json = _canonical({
        **authorization,
        "reserved_requests": request_count,
        "reserved_tokens": accounted_tokens,
        "reserved_cost_cny": accounted_cost,
    })
    run.progress_json = _canonical({
        **progress,
        "phase": run.status,
        "external_request_state": state,
        "external_request_reserved_tokens": 0,
        "external_request_reserved_cost_cny": 0.0,
        "external_request_actual_tokens": accounted_tokens,
        "external_request_actual_cost_cny": accounted_cost,
        "model_usage_reconciliation_hash": reconciliation_hash,
        "model_usage_ledger_snapshot_hash": ledger_snapshot_hash,
    })
    run.revision += 1
    sequence = db.query(AgentEvent).filter_by(agent_run_id=run_id).count() + 1
    payload = {
        "contract_version": "geo.agent.model-usage-reconciliation.v2",
        "reconciliation_hash": reconciliation_hash,
        "ledger_snapshot_hash": ledger_snapshot_hash,
        "before": before,
        "after": after,
    }
    db.add(AgentEvent(
        event_id=f"agent-event-{uuid4()}", agent_run_id=run_id,
        sequence_number=sequence, event_type="MODEL_USAGE_RECONCILED",
        payload_json=_canonical(payload), payload_hash=digest(payload),
    ))
    db.commit()
    return {"changed": True, "reconciliation_hash": reconciliation_hash,
            "ledger_snapshot_hash": ledger_snapshot_hash, **after}
