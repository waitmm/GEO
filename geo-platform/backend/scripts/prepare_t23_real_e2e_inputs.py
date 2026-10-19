"""Build an isolated, staged T23 manifest without making external requests."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.release_sqlite import get_release_sqlite_dbapi  # noqa: E402
from app.models import (SinglePromptAnalysisContext, SinglePromptCitationManifest,
    SinglePromptSourceCompletionManifest)  # noqa: E402
from app.modules.single_prompt_v2.automatic_delivery import create_task  # noqa: E402
from app.services.serialization import loads  # noqa: E402
from scripts.live_model_budget import summary  # noqa: E402
from scripts.t23_real_e2e_acceptance import CONTRACT, validate_manifest  # noqa: E402


def _sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _backup(source: Path, target: Path) -> None:
    if target.exists():
        raise ValueError("isolated target already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    adapter = get_release_sqlite_dbapi()
    source_db = adapter.connect(str(source.resolve()))
    target_db = adapter.connect(str(target.resolve()))
    try:
        source_db.backup(target_db)
    finally:
        target_db.close()
        source_db.close()


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def prepare(*, source_database: Path, database: Path, ledger: Path, manifest_path: Path,
            shared_analysis_id: str, unknown_analysis_id: str, authorized_by: str) -> dict:
    ledger_state = summary(ledger)
    config = ledger_state.get("config") or {}
    if (ledger_state.get("used_requests") != 0 or config.get("task_request_limits") != {"T09": 3, "T23": 9}
            or config.get("task_cost_limits_cny") != {"T09": 10.0, "T23": 40.0}):
        raise ValueError("shared ledger is not the unused immutable T09/T23 authorization")
    _backup(source_database, database)
    engine = create_engine(f"sqlite:///{database.resolve()}", module=get_release_sqlite_dbapi(),
        connect_args={"check_same_thread": False, "timeout": 30})
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    try:
        shared = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=shared_analysis_id).one()
        unknown = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=unknown_analysis_id).one()
        shared_raw = loads(shared.raw_output_json, {})
        unknown_raw = loads(unknown.raw_output_json, {})
        shared_runs = [int(row["run_id"]) for row in shared_raw.get("runs") or []]
        unknown_runs = [int(row["run_id"]) for row in unknown_raw.get("runs") or []]
        if len(shared_runs) != 1 or len(unknown_runs) != 1:
            raise ValueError("T23 staged acceptance requires one exact Run per frozen Analysis")
        completion = db.query(SinglePromptSourceCompletionManifest).filter_by(
            analysis_id=shared.analysis_id, context_id=shared.context_id).one()
        citation = db.query(SinglePromptCitationManifest).filter_by(
            manifest_id=completion.citation_manifest_id).one()
        first, _ = create_task(db, analysis_id=shared.analysis_id, project_id=shared.project_id,
            prompt_id=shared.prompt_id, raw_output_hash=shared.raw_output_hash,
            completion_manifest_id=completion.manifest_id, completion_manifest_hash=completion.payload_hash,
            idempotency_key="t23-live-acceptance-20261019:E2E-01")
        second, _ = create_task(db, analysis_id=shared.analysis_id, project_id=shared.project_id,
            prompt_id=shared.prompt_id, raw_output_hash=shared.raw_output_hash,
            idempotency_key="t23-live-acceptance-20261019:E2E-02")
        connection = get_release_sqlite_dbapi().connect(str(database.resolve()))
        try:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            connection.close()
        budget = {"budget_id": "t23-live-acceptance-20261019", "max_requests": 9,
            "max_cost_cny": 40, "conservative_cny_per_million_tokens": 10,
            "pricing_source": config["pricing_source"], "pricing_checked_at": config["pricing_checked_at"],
            "authorized_by": authorized_by, "max_attempts": 1, "automatic_retry": 0}
        common = {"max_tokens": 300_000, "max_cost_cny": 10}
        manifest = {"contract_version": CONTRACT, "source_database_sha256": _sha(database),
            "shared_budget": budget, "scenarios": [
                {"id": "E2E-01", "task_id": first.task_id, "project_id": first.project_id,
                    "prompt_id": first.prompt_id, "analysis_id": first.analysis_id,
                    "context_id": first.context_id, "input_hash": first.input_hash,
                    "run_ids": shared_runs, "max_requests": 4, **common,
                    "prepare_max_requests": 1, "execute_max_requests": 3,
                    "answer_prepare_input": {"citation_manifest_id": citation.manifest_id,
                        "citation_manifest_hash": citation.payload_hash, "selected_run_id": shared_runs[0]}},
                {"id": "E2E-02", "task_id": second.task_id, "project_id": second.project_id,
                    "prompt_id": second.prompt_id, "analysis_id": second.analysis_id,
                    "context_id": second.context_id, "input_hash": second.input_hash,
                    "run_ids": shared_runs, "max_requests": 3, **common,
                    "prepare_max_requests": 1, "execute_max_requests": 2,
                    "prepare_input": {"citation_manifest_id": citation.manifest_id,
                        "citation_manifest_hash": citation.payload_hash,
                        "completion_manifest_id": completion.manifest_id,
                        "completion_manifest_hash": completion.payload_hash,
                        "selected_run_id": shared_runs[0]}},
                {"id": "E2E-03", "task_id": "PENDING_AFTER_FORMAL_UNKNOWN",
                    "project_id": unknown.project_id, "prompt_id": unknown.prompt_id,
                    "analysis_id": unknown.analysis_id, "context_id": unknown.context_id,
                    "input_hash": "0" * 64, "run_ids": unknown_runs, "max_requests": 2, **common,
                    "task_pending_truth": True, "unknown_prepare_input": {
                        "signal_selector": "UNIQUE_TARGET_BRAND_CAPABILITY",
                        "source_reference": "T23 isolated acceptance; requires independent verification",
                        "note": "Explicit UNKNOWN acceptance boundary; never eligible as positive evidence",
                        "reviewed_by": authorized_by}},
            ]}
        validate_manifest(manifest, allow_unprepared_e2e02=True, allow_unprepared_e2e03=True)
        _write(manifest_path, manifest)
        return {"status": "STAGED", "database": str(database.resolve()),
            "database_sha256": manifest["source_database_sha256"],
            "manifest": str(manifest_path.resolve()), "manifest_sha256": _sha(manifest_path),
            "task_ids": [first.task_id, second.task_id, "PENDING_AFTER_FORMAL_UNKNOWN"],
            "external_requests": 0}
    finally:
        db.close()
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-database", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--shared-analysis-id", required=True)
    parser.add_argument("--unknown-analysis-id", required=True)
    parser.add_argument("--authorized-by", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(source_database=args.source_database, database=args.database,
        ledger=args.ledger, manifest_path=args.manifest, shared_analysis_id=args.shared_analysis_id,
        unknown_analysis_id=args.unknown_analysis_id, authorized_by=args.authorized_by),
        ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
