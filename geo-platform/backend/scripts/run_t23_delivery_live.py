"""Sole guarded executor for the three authorized T23 real delivery scenarios.

The controller must have initialized the existing shared T09/T23 ledger.  This
entry point never initializes, resets or enlarges it.  It preflights all three
frozen tasks, authorizes each task immediately before execution, and wraps every
Answer/Citation/Draft/Text-QA provider send in the shared reserve/finish guard.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.release_sqlite import get_release_sqlite_dbapi  # noqa: E402
from app.models import SinglePromptOptimizationTask  # noqa: E402
from app.services.semantic_llm.base import SemanticLLMError  # noqa: E402
from app.modules.single_prompt_v2.automatic_delivery import (  # noqa: E402
    authorize_task,
    execute_task,
    shared_live_budget_hooks,
)
from scripts.live_model_budget import finish, reserve, summary  # noqa: E402
from scripts.t23_real_e2e_acceptance import (  # noqa: E402
    _authorization,
    _inspect_task,
    _read_json,
    _sha256_file,
    _write_evidence,
    validate_manifest,
)


def _assert_ledger(manifest: dict[str, Any], state: dict[str, Any]) -> None:
    config = state.get("config") or {}
    budget = manifest["shared_budget"]
    expected = {
        "total_request_limit": 12,
        "total_cost_limit_cny": 50.0,
        "conservative_cny_per_million_tokens": budget["conservative_cny_per_million_tokens"],
        "task_request_limits": {"T09": 3, "T23": 9},
        "task_cost_limits_cny": {"T09": 10.0, "T23": 40.0},
        "pricing_source": budget["pricing_source"],
        "pricing_checked_at": budget["pricing_checked_at"],
        "automatic_retries": 0,
        "provider": "deepseek",
        "requested_model_alias": "deepseek-v4-flash",
        "effective_request_model": "deepseek-flash",
    }
    if any(config.get(key) != value for key, value in expected.items()):
        raise ValueError("shared ledger configuration does not match the frozen T09/T23 authorization")
    if any(row.get("status") == "RESERVED" for row in state.get("requests") or []):
        raise ValueError("shared ledger contains an unresolved in-flight request")
    allocations = manifest["scenarios"]
    used_t23 = int((state.get("by_task") or {}).get("T23") or 0)
    used_total = int(state.get("used_requests") or 0)
    allocated_requests = sum(row["max_requests"] for row in allocations)
    allocated_cost = sum(float(row["max_cost_cny"]) for row in allocations)
    used_t23_cost = sum(float(row["reserved_cost_cny"]) for row in state.get("requests") or []
        if row.get("task_scope") == "T23")
    if allocated_requests > 9 - used_t23 or allocated_requests > 12 - used_total:
        raise ValueError("T23 task caps exceed the remaining shared request budget")
    if allocated_cost > 40.0 - used_t23_cost or allocated_cost > 50.0 - float(state.get("reserved_cost_cny") or 0):
        raise ValueError("T23 task caps exceed the remaining shared cost budget")


def _hooks(ledger: Path, *, scenario_id: str, task_id: str):
    active: dict[str, str] = {}
    finished: set[str] = set()

    def request_guard(identity: dict[str, Any]) -> None:
        if (identity.get("provider") != "deepseek"
                or identity.get("requested_model_alias") != "deepseek-v4-flash"
                or identity.get("effective_request_model") != "deepseek-flash"):
            error = SemanticLLMError(
                "SEMANTIC_CONTRACT_REVIEW_REQUIRED:ANSWER_TRANSPORT_IDENTITY_UNFROZEN")
            error.code = "ANSWER_TRANSPORT_IDENTITY_UNFROZEN"
            raise error
        input_hash = str(identity.get("input_hash") or "")
        if input_hash in active and active[input_hash] not in finished:
            raise RuntimeError("T23_REQUEST_ALREADY_ACTIVE_NO_RETRY")
        payload_hash = str(identity.get("provider_payload_hash") or "")
        request_id = f"T23:{scenario_id}:{task_id}:{payload_hash[:24]}"
        reserve(ledger, task_scope="T23", request_id=request_id, identity=identity)
        active[input_hash] = request_id

    def audit_sink(event: dict[str, Any]) -> None:
        identity = event.get("request_identity") or {}
        request_id = active.get(str(identity.get("input_hash") or ""))
        if not request_id or request_id in finished or event.get("response_source") == "LLM_CALL_CACHE":
            return
        validation = str(event.get("validation_status") or "")
        if validation == "ACCEPTED":
            status = "FINISHED"
        elif validation == "TRANSPORT_FAILED":
            code = str(event.get("rejection_code") or "").lower()
            status = "TIMEOUT" if "timeout" in code else "DELIVERY_UNKNOWN"
        else:
            status = "FAILED"
        finish(ledger, request_id=request_id, status=status, outcome={
            "scenario_id": scenario_id,
            "task_id": task_id,
            "validation_status": validation,
            "finish_reason": event.get("finish_reason"),
            "response_model": event.get("response_model"),
            "raw_response_hash": event.get("raw_response_hash"),
            "token_usage": event.get("token_usage") or {},
            "rejection_code": event.get("rejection_code"),
        })
        finished.add(request_id)

    def settle_unknown(exc: Exception) -> None:
        for request_id in set(active.values()) - finished:
            finish(ledger, request_id=request_id, status="DELIVERY_UNKNOWN",
                outcome={"scenario_id": scenario_id, "task_id": task_id,
                    "exception_type": exc.__class__.__name__})
            finished.add(request_id)

    return request_guard, audit_sink, settle_unknown


def execute(*, database: Path, ledger: Path, manifest_path: Path, report_path: Path) -> dict[str, Any]:
    manifest = validate_manifest(_read_json(manifest_path))
    if _sha256_file(database) != manifest["source_database_sha256"]:
        raise ValueError("isolated database changed after T23 scenario freeze")
    before_budget = summary(ledger)
    _assert_ledger(manifest, before_budget)

    engine = create_engine(f"sqlite:///{database.resolve()}", module=get_release_sqlite_dbapi(),
        connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    results: list[dict[str, Any]] = []
    try:
        # Validate every scenario before granting the first task any authority.
        planned = [_inspect_task(db, case, phase="plan") for case in manifest["scenarios"]]
        for case, state in zip(manifest["scenarios"], planned, strict=True):
            row = db.query(SinglePromptOptimizationTask).filter_by(task_id=case["task_id"]).one()
            payload = _authorization(case, state, manifest["shared_budget"])
            authorize_task(db, row, **payload)
            request_guard, audit_sink, settle_unknown = _hooks(
                ledger, scenario_id=case["id"], task_id=row.task_id)
            try:
                with shared_live_budget_hooks(request_guard=request_guard, response_audit_sink=audit_sink):
                    execute_task(row.task_id, session_factory=Session)
            except Exception as exc:
                settle_unknown(exc)
                raise
            db.expire_all()
            results.append(_inspect_task(db, case, phase="verify"))
        report = {"status": "PASS", "contract_version": manifest["contract_version"],
            "database": str(database.resolve()), "manifest_sha256": _sha256_file(manifest_path),
            "scenarios": results, "budget_before": before_budget, "budget_after": summary(ledger),
            "external_requests_by_harness": 0}
        exit_code = 0
    except Exception as exc:
        db.rollback()
        report = {"status": "BLOCKED", "contract_version": manifest["contract_version"],
            "database": str(database.resolve()), "manifest_sha256": _sha256_file(manifest_path),
            "completed_scenarios": results, "error_type": exc.__class__.__name__,
            "error": str(exc)[:500], "budget_before": before_budget, "budget_after": summary(ledger),
            "external_requests_by_harness": 0}
        exit_code = 2
    finally:
        db.close()
        engine.dispose()
    _write_evidence(report_path, report)
    return {**report, "exit_code": exit_code}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--confirm-isolated-database", action="store_true")
    args = parser.parse_args()
    if not args.confirm_isolated_database:
        raise SystemExit("REFUSED: --confirm-isolated-database is required")
    if not args.database.is_file():
        raise SystemExit("REFUSED: isolated database does not exist")
    report = execute(database=args.database, ledger=args.ledger,
        manifest_path=args.manifest, report_path=args.report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
