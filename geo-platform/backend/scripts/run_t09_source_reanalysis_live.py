"""Run one authorized T09 source reanalysis against an isolated release DB.

The script never initializes or enlarges the shared budget.  Every possible
DeepSeek send is atomically reserved through ``live_model_budget`` first, and
the T09 executor itself forbids provider retries.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.release_sqlite import get_release_sqlite_dbapi
from app.models import SinglePromptDiagnosisExecution
from app.modules.single_prompt_v2.source_reanalysis import (
    execute_source_reanalysis,
    source_reanalysis_view,
)
from scripts.live_model_budget import finish, reserve, summary


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--reanalysis-id", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--confirm-isolated-database", action="store_true")
    args = parser.parse_args()
    if not args.confirm_isolated_database:
        raise SystemExit("REFUSED: --confirm-isolated-database is required")
    if not args.database.is_file():
        raise SystemExit("REFUSED: isolated database does not exist")

    # Fails closed when the main controller has not already initialized the
    # immutable 12-call/50-CNY shared ledger.
    before_budget = summary(args.ledger)
    engine = create_engine(
        f"sqlite:///{args.database.resolve()}",
        module=get_release_sqlite_dbapi(),
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Session = sessionmaker(bind=engine, expire_on_commit=False)
    active: dict[str, str] = {}
    finished: set[str] = set()

    def request_guard(identity: dict[str, Any]) -> None:
        input_hash = str(identity.get("input_hash") or "")
        request_id = f"T09:{args.reanalysis_id}:{input_hash[:24]}"
        reserve(
            args.ledger,
            task_scope="T09",
            request_id=request_id,
            identity=identity,
        )
        active[input_hash] = request_id

    def audit_sink(event: dict[str, Any]) -> None:
        identity = event.get("request_identity") or {}
        request_id = active.get(str(identity.get("input_hash") or ""))
        if not request_id or request_id in finished:
            return
        validation = str(event.get("validation_status") or "")
        if validation == "ACCEPTED":
            status = "FINISHED"
        elif validation == "TRANSPORT_FAILED":
            status = "TIMEOUT" if "timeout" in str(event.get("rejection_code") or "").lower() else "DELIVERY_UNKNOWN"
        else:
            status = "FAILED"
        finish(
            args.ledger,
            request_id=request_id,
            status=status,
            outcome={
                "validation_status": validation,
                "finish_reason": event.get("finish_reason"),
                "response_model": event.get("response_model"),
                "raw_response_hash": event.get("raw_response_hash"),
                "token_usage": event.get("token_usage") or {},
                "rejection_code": event.get("rejection_code"),
            },
        )
        finished.add(request_id)

    report: dict[str, Any]
    db = Session()
    try:
        result = execute_source_reanalysis(
            db,
            reanalysis_id=args.reanalysis_id,
            request_guard=request_guard,
            response_audit_sink=audit_sink,
            max_attempts=1,
        )
        row = db.query(SinglePromptDiagnosisExecution).filter_by(
            diagnosis_id=result.diagnosis_id
        ).one()
        report = {
            "status": "PASS",
            "database": str(args.database.resolve()),
            "reanalysis": source_reanalysis_view(row),
            "result": {
                "result_version": result.result_version,
                "result_hash": result.output_hash,
                "parent_result_version": result.parent_result_version,
            },
            "budget_before": before_budget,
            "budget_after": summary(args.ledger),
        }
        exit_code = 0
    except Exception as exc:
        # A reservation with no provider audit means delivery cannot safely be
        # disproved.  Count it and block automatic replay.
        for request_id in set(active.values()) - finished:
            finish(
                args.ledger,
                request_id=request_id,
                status="DELIVERY_UNKNOWN",
                outcome={"exception_type": exc.__class__.__name__},
            )
            finished.add(request_id)
        db.rollback()
        report = {
            "status": "BLOCKED",
            "database": str(args.database.resolve()),
            "reanalysis_id": args.reanalysis_id,
            "error_type": exc.__class__.__name__,
            "error": str(exc)[:500],
            "budget_before": before_budget,
            "budget_after": summary(args.ledger),
        }
        exit_code = 2
    finally:
        db.close()
        engine.dispose()

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(_canonical(report) + "\n", encoding="utf-8")
    print(_canonical(report))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
