"""Fail-closed persistent budget ledger for one authorized model batch.

The ledger is deliberately separate from product persistence.  Both the Agent
experiment and an optional isolated Workflow baseline attach the same hooks to
their existing DeepSeek clients.  A request is reserved under ``BEGIN
IMMEDIATE`` before provider I/O; a delivery-unknown request keeps its worst-case
reservation across process restarts.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Any


CONTRACT_VERSION = "geo-agent-comparison-shared-budget.v1"
PRICING_SOURCE = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"
AUTHORIZED_LANES = frozenset({"AGENT_EXPERIMENT", "WORKFLOW_BASELINE"})
COUNTED_STATUSES = frozenset({"RESERVED", "FINISHED", "FAILED", "DELIVERY_UNKNOWN"})
FINAL_STATUSES = COUNTED_STATUSES - {"RESERVED"}


class SharedBudgetDenied(RuntimeError):
    """A request cannot be admitted under the frozen batch authorization."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS budget_config (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        config_json TEXT NOT NULL, config_hash TEXT NOT NULL, created_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS model_requests (
        request_id TEXT PRIMARY KEY, lane TEXT NOT NULL, operation_id TEXT NOT NULL,
        provider_payload_hash TEXT NOT NULL UNIQUE, input_hash TEXT NOT NULL,
        token_ceiling INTEGER NOT NULL, reserved_cost_cny REAL NOT NULL,
        accounted_tokens INTEGER NOT NULL, accounted_cost_cny REAL NOT NULL,
        actual_input_tokens INTEGER, actual_output_tokens INTEGER, actual_total_tokens INTEGER,
        actual_peak_price_cost_cny REAL, status TEXT NOT NULL,
        reserved_at TEXT NOT NULL, finished_at TEXT, outcome_json TEXT NOT NULL
        )"""
    )
    return connection


def _validate_pricing_date(value: str, *, today: date | None = None) -> None:
    try:
        checked = date.fromisoformat(value)
    except ValueError as exc:
        raise SharedBudgetDenied("PRICING_DATE_INVALID") from exc
    age = ((today or datetime.now(timezone.utc).date()) - checked).days
    if age < 0 or age > 7:
        raise SharedBudgetDenied("PRICING_EVIDENCE_STALE")


def initialize(
    path: Path,
    *,
    batch_id: str,
    pricing_checked_at: str,
    pricing_source: str = PRICING_SOURCE,
    total_request_limit: int = 36,
    total_token_limit: int = 3_000_000,
    total_cost_limit_cny: float = 30.0,
    conservative_cny_per_million_tokens: float = 10.0,
    today: date | None = None,
) -> dict[str, Any]:
    _validate_pricing_date(pricing_checked_at, today=today)
    if (
        not batch_id.strip()
        or pricing_source.rstrip("/") != PRICING_SOURCE.rstrip("/")
        or total_request_limit != 36
        or total_token_limit != 3_000_000
        or total_cost_limit_cny != 30.0
        or not math.isfinite(conservative_cny_per_million_tokens)
        or conservative_cny_per_million_tokens < 10.0
    ):
        raise SharedBudgetDenied("AUTHORIZED_BATCH_CONFIG_MISMATCH")
    config = {
        "contract_version": CONTRACT_VERSION,
        "batch_id": batch_id,
        "provider": "deepseek",
        # The Workflow may carry the historical internal alias, but both aliases
        # are required to resolve to the exact effective provider model below.
        "requested_model_aliases": ["deepseek-flash", "deepseek-v4-flash"],
        "effective_request_model": "deepseek-flash",
        "endpoint": "https://api.deepseek.com/responses",
        "endpoint_path": "/responses",
        "transport_kind": "RESPONSES_JSON_SCHEMA",
        "authorized_lanes": sorted(AUTHORIZED_LANES),
        "total_request_limit": total_request_limit,
        "total_token_limit": total_token_limit,
        "total_cost_limit_cny": total_cost_limit_cny,
        "conservative_cny_per_million_tokens": conservative_cny_per_million_tokens,
        "pricing_source": pricing_source,
        "pricing_checked_at": pricing_checked_at,
        "automatic_retries": 0,
        "max_concurrency": 1,
    }
    digest = _hash(config)
    connection = _connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT config_hash FROM budget_config WHERE singleton=1"
        ).fetchone()
        if existing and existing["config_hash"] != digest:
            raise SharedBudgetDenied("BUDGET_LEDGER_CONFIG_IMMUTABLE")
        if not existing:
            connection.execute(
                "INSERT INTO budget_config VALUES(1,?,?,?)", (_canonical(config), digest, _utcnow())
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {**config, "config_hash": digest}


def _config(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute(
        "SELECT config_json,config_hash FROM budget_config WHERE singleton=1"
    ).fetchone()
    if not row:
        raise SharedBudgetDenied("BUDGET_LEDGER_NOT_INITIALIZED")
    value = json.loads(row["config_json"])
    if _hash(value) != row["config_hash"]:
        raise SharedBudgetDenied("BUDGET_LEDGER_CONFIG_HASH_MISMATCH")
    _validate_pricing_date(value["pricing_checked_at"])
    return value


def _hex64(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def reserve(
    path: Path, *, lane: str, operation_id: str, request_id: str, identity: dict[str, Any]
) -> dict[str, Any]:
    connection = _connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        config = _config(connection)
        if lane not in config["authorized_lanes"]:
            raise SharedBudgetDenied("LANE_NOT_AUTHORIZED")
        if (
            identity.get("provider") != config["provider"]
            or identity.get("requested_model_alias") not in config["requested_model_aliases"]
            or identity.get("effective_request_model") != config["effective_request_model"]
            or identity.get("endpoint") != config["endpoint"]
            or identity.get("endpoint_path") != config["endpoint_path"]
            or identity.get("transport_kind") != config["transport_kind"]
        ):
            raise SharedBudgetDenied("MODEL_OR_TRANSPORT_NOT_AUTHORIZED")
        if int(identity.get("attempt") or 0) != 1:
            raise SharedBudgetDenied("AUTOMATIC_RETRY_FORBIDDEN")
        payload_hash = identity.get("provider_payload_hash")
        input_hash = identity.get("input_hash")
        input_ceiling = identity.get("input_token_upper_bound")
        output_ceiling = identity.get("max_output_tokens")
        if (
            not request_id.strip() or not operation_id.strip()
            or not _hex64(payload_hash) or not _hex64(input_hash)
            or not isinstance(input_ceiling, int) or isinstance(input_ceiling, bool) or input_ceiling < 0
            or not isinstance(output_ceiling, int) or isinstance(output_ceiling, bool) or output_ceiling <= 0
        ):
            raise SharedBudgetDenied("REQUEST_IDENTITY_INCOMPLETE")
        token_ceiling = input_ceiling + output_ceiling
        if token_ceiling <= 0 or token_ceiling > config["total_token_limit"]:
            raise SharedBudgetDenied("TOKEN_CEILING_INVALID")
        if connection.execute("SELECT 1 FROM model_requests WHERE status='RESERVED'").fetchone():
            raise SharedBudgetDenied("CONCURRENCY_LIMIT_EXCEEDED")
        if connection.execute(
            "SELECT 1 FROM model_requests WHERE request_id=? OR provider_payload_hash=?",
            (request_id, payload_hash),
        ).fetchone():
            raise SharedBudgetDenied("REQUEST_ALREADY_RESERVED_NO_RETRY")
        rows = connection.execute(
            "SELECT accounted_tokens,accounted_cost_cny,status FROM model_requests"
        ).fetchall()
        counted = [row for row in rows if row["status"] in COUNTED_STATUSES]
        cost = round(token_ceiling * config["conservative_cny_per_million_tokens"] / 1_000_000, 8)
        if len(counted) + 1 > config["total_request_limit"]:
            raise SharedBudgetDenied("GLOBAL_REQUEST_LIMIT_EXHAUSTED")
        if sum(row["accounted_tokens"] for row in counted) + token_ceiling > config["total_token_limit"]:
            raise SharedBudgetDenied("GLOBAL_TOKEN_LIMIT_EXHAUSTED")
        if sum(row["accounted_cost_cny"] for row in counted) + cost > config["total_cost_limit_cny"]:
            raise SharedBudgetDenied("GLOBAL_COST_LIMIT_EXHAUSTED")
        connection.execute(
            """INSERT INTO model_requests(
            request_id,lane,operation_id,provider_payload_hash,input_hash,token_ceiling,
            reserved_cost_cny,accounted_tokens,accounted_cost_cny,status,reserved_at,
            finished_at,outcome_json
            ) VALUES(?,?,?,?,?,?,?,?,?,'RESERVED',?,NULL,'{}')""",
            (request_id, lane, operation_id, payload_hash, input_hash, token_ceiling,
             cost, token_ceiling, cost, _utcnow()),
        )
        connection.commit()
        return {"request_id": request_id, "token_ceiling": token_ceiling, "reserved_cost_cny": cost}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def settle(path: Path, *, request_id: str, status: str, outcome: dict[str, Any]) -> None:
    if status not in FINAL_STATUSES:
        raise SharedBudgetDenied("INVALID_FINAL_STATUS")
    usage = outcome.get("token_usage") or {}
    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
    total_tokens = usage.get("total_tokens")
    known = all(isinstance(value, int) and not isinstance(value, bool) and value >= 0
                for value in (input_tokens, output_tokens, total_tokens))
    if known and input_tokens + output_tokens > total_tokens:
        raise SharedBudgetDenied("ACTUAL_USAGE_INVALID")
    connection = _connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        config = _config(connection)
        row = connection.execute(
            "SELECT status,token_ceiling FROM model_requests WHERE request_id=?", (request_id,)
        ).fetchone()
        if not row or row["status"] != "RESERVED":
            raise SharedBudgetDenied("REQUEST_NOT_ACTIVE")
        if known and total_tokens > row["token_ceiling"]:
            raise SharedBudgetDenied("ACTUAL_USAGE_EXCEEDS_RESERVATION")
        # Only a definite provider response with complete usage releases the
        # unused reservation.  Unknown delivery remains charged at its ceiling.
        use_actual = known and status in {"FINISHED", "FAILED"}
        accounted_tokens = total_tokens if use_actual else row["token_ceiling"]
        accounted_cost = round(
            accounted_tokens * config["conservative_cny_per_million_tokens"] / 1_000_000, 8
        )
        actual_peak = (round((input_tokens * 2 + output_tokens * 8) / 1_000_000, 8)
                       if known else None)
        connection.execute(
            """UPDATE model_requests SET status=?,finished_at=?,outcome_json=?,
            accounted_tokens=?,accounted_cost_cny=?,actual_input_tokens=?,
            actual_output_tokens=?,actual_total_tokens=?,actual_peak_price_cost_cny=?
            WHERE request_id=?""",
            (status, _utcnow(), _canonical(outcome), accounted_tokens, accounted_cost,
             input_tokens if known else None, output_tokens if known else None,
             total_tokens if known else None, actual_peak, request_id),
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
        config = _config(connection)
        rows = [dict(row) for row in connection.execute(
            "SELECT * FROM model_requests ORDER BY reserved_at,request_id"
        )]
        counted = [row for row in rows if row["status"] in COUNTED_STATUSES]
        used_tokens = sum(row["accounted_tokens"] for row in counted)
        used_cost = round(sum(row["accounted_cost_cny"] for row in counted), 8)
        return {
            "contract_version": CONTRACT_VERSION,
            "config": config,
            "used_requests": len(counted),
            "used_tokens": used_tokens,
            "used_cost_cny": used_cost,
            "remaining_requests": config["total_request_limit"] - len(counted),
            "remaining_tokens": config["total_token_limit"] - used_tokens,
            "remaining_cost_cny": round(config["total_cost_limit_cny"] - used_cost, 8),
            "in_flight": sum(row["status"] == "RESERVED" for row in counted),
            "by_lane": {lane: sum(row["lane"] == lane for row in counted)
                        for lane in config["authorized_lanes"]},
            "requests": rows,
        }
    finally:
        connection.close()


class SharedBudgetHooks:
    """Request/audit hooks accepted by both existing model-client paths."""

    def __init__(self, path: Path, *, lane: str, operation_id: str):
        self.path = path
        self.lane = lane
        self.operation_id = operation_id
        self._active: dict[str, str] = {}
        self._finished: set[str] = set()

    def request_guard(self, identity: dict[str, Any]) -> None:
        payload_hash = str(identity.get("provider_payload_hash") or "")
        request_id = f"{self.lane}:{self.operation_id}:{payload_hash[:24]}"
        reserve(self.path, lane=self.lane, operation_id=self.operation_id,
                request_id=request_id, identity=identity)
        self._active[str(identity.get("input_hash") or "")] = request_id

    def audit_sink(self, event: dict[str, Any]) -> None:
        if event.get("response_source") == "LLM_CALL_CACHE":
            return
        identity = event.get("request_identity") or {}
        request_id = self._active.get(str(identity.get("input_hash") or ""))
        if not request_id or request_id in self._finished:
            return
        validation = str(event.get("validation_status") or "")
        status = "FINISHED" if validation == "ACCEPTED" else "FAILED"
        if validation == "TRANSPORT_FAILED":
            status = "DELIVERY_UNKNOWN"
        settle(self.path, request_id=request_id, status=status, outcome={
            "validation_status": validation,
            "finish_reason": event.get("finish_reason"),
            "response_model": event.get("response_model"),
            "raw_response_hash": event.get("raw_response_hash"),
            "response_excerpt": event.get("response_excerpt"),
            "response_length": event.get("response_length"),
            "http_status": event.get("http_status"),
            "provider_error_category": event.get("provider_error_category"),
            "token_usage": event.get("token_usage") or {},
            "rejection_code": event.get("rejection_code"),
        })
        self._finished.add(request_id)

    def settle_unknown(self, exc: BaseException) -> None:
        for request_id in set(self._active.values()) - self._finished:
            settle(self.path, request_id=request_id, status="DELIVERY_UNKNOWN", outcome={
                "exception_type": exc.__class__.__name__, "token_usage": {},
            })
            self._finished.add(request_id)
