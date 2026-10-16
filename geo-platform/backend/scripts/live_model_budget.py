"""Persistent guard for the explicitly authorized GEO 1.0 live-model batch.

This is an acceptance-time safety guard, not a scheduler.  A reservation is
written with ``BEGIN IMMEDIATE`` before provider I/O.  Once reserved it counts
against the batch even when the request later fails, times out, or has unknown
delivery.  The guard deliberately permits only one in-flight request.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "geo-v1-live-model-budget.v1"
COUNTED_STATUSES = {"RESERVED", "FINISHED", "FAILED", "TIMEOUT", "DELIVERY_UNKNOWN"}
FINAL_STATUSES = COUNTED_STATUSES - {"RESERVED"}


class BudgetDenied(RuntimeError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(config).encode("utf-8")).hexdigest()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS budget_config (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        contract_version TEXT NOT NULL,
        config_json TEXT NOT NULL,
        config_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS model_requests (
        request_id TEXT PRIMARY KEY,
        task_scope TEXT NOT NULL,
        provider TEXT NOT NULL,
        requested_model_alias TEXT NOT NULL,
        effective_request_model TEXT NOT NULL,
        provider_payload_hash TEXT NOT NULL UNIQUE,
        input_hash TEXT NOT NULL,
        token_ceiling INTEGER NOT NULL,
        reserved_cost_cny REAL NOT NULL,
        status TEXT NOT NULL,
        reserved_at TEXT NOT NULL,
        finished_at TEXT,
        outcome_json TEXT NOT NULL
        )"""
    )
    return connection


def initialize(
    path: Path,
    *,
    total_request_limit: int = 12,
    total_cost_limit_cny: float = 50.0,
    conservative_cny_per_million_tokens: float = 10.0,
    task_request_limits: dict[str, int] | None = None,
    task_cost_limits_cny: dict[str, float] | None = None,
    pricing_source: str,
    pricing_checked_at: str,
) -> dict[str, Any]:
    task_request_limits = task_request_limits or {"T09": 3, "T23": 9}
    task_cost_limits_cny = task_cost_limits_cny or {"T09": 10.0, "T23": 40.0}
    if (
        total_request_limit != 12
        or total_cost_limit_cny != 50.0
        or task_request_limits != {"T09": 3, "T23": 9}
        or sum(task_request_limits.values()) != total_request_limit
        or set(task_cost_limits_cny) != {"T09", "T23"}
        or any(value <= 0 for value in task_cost_limits_cny.values())
        or sum(task_cost_limits_cny.values()) > total_cost_limit_cny
        or not math.isfinite(total_cost_limit_cny)
        or not math.isfinite(conservative_cny_per_million_tokens)
        or any(not math.isfinite(value) for value in task_cost_limits_cny.values())
        or conservative_cny_per_million_tokens < 10.0
        or not pricing_source.strip()
        or not pricing_checked_at.strip()
    ):
        raise BudgetDenied("AUTHORIZED_BATCH_CONFIG_MISMATCH")
    config = {
        "contract_version": CONTRACT_VERSION,
        "total_request_limit": total_request_limit,
        "total_cost_limit_cny": total_cost_limit_cny,
        "conservative_cny_per_million_tokens": conservative_cny_per_million_tokens,
        "task_request_limits": task_request_limits,
        "task_cost_limits_cny": task_cost_limits_cny,
        "pricing_source": pricing_source,
        "pricing_checked_at": pricing_checked_at,
        "automatic_retries": 0,
        "provider": "deepseek",
        "requested_model_alias": "deepseek-v4-flash",
        "effective_request_model": "deepseek-flash",
    }
    encoded = _canonical(config)
    digest = _config_hash(config)
    connection = _connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute("SELECT config_hash FROM budget_config WHERE singleton=1").fetchone()
        if existing and existing["config_hash"] != digest:
            raise BudgetDenied("BUDGET_LEDGER_CONFIG_IMMUTABLE")
        if not existing:
            connection.execute(
                "INSERT INTO budget_config VALUES(1,?,?,?,?)",
                (CONTRACT_VERSION, encoded, digest, datetime.now(timezone.utc).isoformat()),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {**config, "config_hash": digest}


def _load_config(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute("SELECT config_json,config_hash FROM budget_config WHERE singleton=1").fetchone()
    if not row:
        raise BudgetDenied("BUDGET_LEDGER_NOT_INITIALIZED")
    config = json.loads(row["config_json"])
    if _config_hash(config) != row["config_hash"]:
        raise BudgetDenied("BUDGET_LEDGER_CONFIG_HASH_MISMATCH")
    return config


def reserve(path: Path, *, task_scope: str, request_id: str, identity: dict[str, Any]) -> dict[str, Any]:
    connection = _connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        config = _load_config(connection)
        if task_scope not in config["task_request_limits"]:
            raise BudgetDenied("TASK_SCOPE_NOT_AUTHORIZED")
        if (
            identity.get("provider") != config["provider"]
            or identity.get("requested_model_alias") != config["requested_model_alias"]
            or identity.get("effective_request_model") != config["effective_request_model"]
        ):
            raise BudgetDenied("PROVIDER_OR_MODEL_NOT_AUTHORIZED")
        if int(identity.get("attempt") or 0) != 1:
            raise BudgetDenied("AUTOMATIC_RETRY_FORBIDDEN")
        payload_hash = str(identity.get("provider_payload_hash") or "")
        input_hash = str(identity.get("input_hash") or "")
        raw_input_ceiling = identity.get("input_token_upper_bound")
        raw_output_ceiling = identity.get("max_output_tokens")
        if (
            not isinstance(raw_input_ceiling, int)
            or isinstance(raw_input_ceiling, bool)
            or not isinstance(raw_output_ceiling, int)
            or isinstance(raw_output_ceiling, bool)
            or raw_input_ceiling < 0
            or raw_output_ceiling <= 0
            or raw_input_ceiling > 2_000_000
            or raw_output_ceiling > 2_000_000
        ):
            raise BudgetDenied("TOKEN_CEILING_INVALID")
        token_ceiling = raw_input_ceiling + raw_output_ceiling
        if not request_id.strip() or len(payload_hash) != 64 or len(input_hash) != 64 or token_ceiling <= 0:
            raise BudgetDenied("REQUEST_IDENTITY_INCOMPLETE")
        if connection.execute("SELECT 1 FROM model_requests WHERE status='RESERVED'").fetchone():
            raise BudgetDenied("ANOTHER_REQUEST_IS_ALREADY_RESERVED")
        if connection.execute(
            "SELECT 1 FROM model_requests WHERE request_id=? OR provider_payload_hash=?",
            (request_id, payload_hash),
        ).fetchone():
            raise BudgetDenied("REQUEST_ALREADY_RESERVED_NO_RETRY")
        rows = connection.execute(
            "SELECT task_scope,reserved_cost_cny,status FROM model_requests"
        ).fetchall()
        counted = [row for row in rows if row["status"] in COUNTED_STATUSES]
        task_counted = [row for row in counted if row["task_scope"] == task_scope]
        cost = round(token_ceiling * float(config["conservative_cny_per_million_tokens"]) / 1_000_000, 6)
        if not math.isfinite(cost) or cost <= 0:
            raise BudgetDenied("RESERVED_COST_INVALID")
        if len(counted) + 1 > int(config["total_request_limit"]):
            raise BudgetDenied("GLOBAL_REQUEST_LIMIT_EXHAUSTED")
        if len(task_counted) + 1 > int(config["task_request_limits"][task_scope]):
            raise BudgetDenied("TASK_REQUEST_LIMIT_EXHAUSTED")
        if sum(float(row["reserved_cost_cny"]) for row in counted) + cost > float(config["total_cost_limit_cny"]):
            raise BudgetDenied("GLOBAL_COST_LIMIT_EXHAUSTED")
        if sum(float(row["reserved_cost_cny"]) for row in task_counted) + cost > float(config["task_cost_limits_cny"][task_scope]):
            raise BudgetDenied("TASK_COST_LIMIT_EXHAUSTED")
        now = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """INSERT INTO model_requests(
            request_id,task_scope,provider,requested_model_alias,effective_request_model,
            provider_payload_hash,input_hash,token_ceiling,reserved_cost_cny,status,
            reserved_at,finished_at,outcome_json
            ) VALUES(?,?,?,?,?,?,?,?,?,'RESERVED',?,NULL,'{}')""",
            (
                request_id,
                task_scope,
                "deepseek",
                str(identity.get("requested_model_alias") or ""),
                "deepseek-flash",
                payload_hash,
                input_hash,
                token_ceiling,
                cost,
                now,
            ),
        )
        connection.commit()
        return {"request_id": request_id, "task_scope": task_scope, "token_ceiling": token_ceiling, "reserved_cost_cny": cost}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def finish(path: Path, *, request_id: str, status: str, outcome: dict[str, Any]) -> None:
    if status not in FINAL_STATUSES:
        raise BudgetDenied("INVALID_FINAL_STATUS")
    connection = _connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT status FROM model_requests WHERE request_id=?", (request_id,)).fetchone()
        if not row or row["status"] != "RESERVED":
            raise BudgetDenied("REQUEST_NOT_ACTIVE")
        connection.execute(
            "UPDATE model_requests SET status=?,finished_at=?,outcome_json=? WHERE request_id=?",
            (status, datetime.now(timezone.utc).isoformat(), _canonical(outcome), request_id),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def summary(path: Path) -> dict[str, Any]:
    connection = _connect(path)
    try:
        config = _load_config(connection)
        rows = [dict(row) for row in connection.execute(
            """SELECT request_id,task_scope,provider,requested_model_alias,effective_request_model,
            token_ceiling,reserved_cost_cny,status,reserved_at,finished_at,outcome_json
            FROM model_requests ORDER BY reserved_at,request_id"""
        )]
        counted = [row for row in rows if row["status"] in COUNTED_STATUSES]
        return {
            "contract_version": CONTRACT_VERSION,
            "config": config,
            "used_requests": len(counted),
            "reserved_cost_cny": round(sum(float(row["reserved_cost_cny"]) for row in counted), 6),
            "by_task": {
                task: len([row for row in counted if row["task_scope"] == task])
                for task in sorted(config["task_request_limits"])
            },
            "requests": rows,
        }
    finally:
        connection.close()
