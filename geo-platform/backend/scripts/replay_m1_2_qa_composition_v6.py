"""Metadata-only shadow replay for the protected fourth M1.2 result.

The script opens the supplied SQLite database read-only, selects the exact
frozen operation (never ``latest``), replays Validation v5 and v6 in memory,
and emits no Provider or business content. It does not modify historical rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.modules.agent_experiment.evidence_pack import (
    AGGREGATE_SCOPE_EVIDENCE_PACK_EXECUTION_CONTRACT,
    EVIDENCE_PACK_EXECUTION_CONTRACT,
    build_evidence_pack,
    validate_markdown_result,
)


IDEMPOTENCY_KEY = "m1-2-dual-content-quality-fourth-20261111"
EXPECTED_RUN_ID = "agent-run-6d2e5f5d-c6f6-406d-88df-e23576a8d5fe"
EXPECTED_INPUT_SCOPE_HASH = "d35c80424f6985da93b16a037542e88d3a12e5ad6988dafeb19dfc83cc688e5a"
EXPECTED_RESULT_HASH = "6c06e5ceb0515c0a7e43dba62fe1c047801f5557adc7f12ef43ff45582e6b4aa"


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _codes(validation: dict[str, Any]) -> list[str]:
    return sorted({
        str(row.get("code") or "UNKNOWN")
        for row in validation.get("issues") or []
        if isinstance(row, dict)
    })


def replay(database: Path) -> dict[str, Any]:
    if not database.is_file():
        raise RuntimeError("PROTECTED_DATABASE_NOT_FOUND")
    before = _sha256(database)
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    try:
        run = connection.execute(
            "select run_id, status, input_scope_hash, input_scope_json "
            "from agent_experiment_runs where idempotency_key = ?",
            (IDEMPOTENCY_KEY,),
        ).fetchone()
        if run is None or run[0] != EXPECTED_RUN_ID or run[2] != EXPECTED_INPUT_SCOPE_HASH:
            raise RuntimeError("PROTECTED_FROZEN_RUN_IDENTITY_MISMATCH")
        stored = connection.execute(
            "select result_version, result_hash, result_json, validation_report_json "
            "from agent_result_versions where agent_run_id = ? and version_number = 1",
            (EXPECTED_RUN_ID,),
        ).fetchone()
        if stored is None or stored[1] != EXPECTED_RESULT_HASH:
            raise RuntimeError("PROTECTED_RESULT_IDENTITY_MISMATCH")
        scope = json.loads(run[3])
        result = json.loads(stored[2])
        historical = json.loads(stored[3])
        provider_markdown = result.get("raw_markdown")
        if not isinstance(provider_markdown, str) or not provider_markdown.strip():
            raise RuntimeError("PROTECTED_PROVIDER_MARKDOWN_MISSING")

        v5_pack = build_evidence_pack(
            scope,
            execution_contract=AGGREGATE_SCOPE_EVIDENCE_PACK_EXECUTION_CONTRACT,
        )
        v5, _ = validate_markdown_result(
            provider_markdown,
            v5_pack,
            requested_artifact_types=["HELP_DOC", "FAQ"],
            execution_contract=AGGREGATE_SCOPE_EVIDENCE_PACK_EXECUTION_CONTRACT,
        )
        v6_pack = build_evidence_pack(
            scope,
            execution_contract=EVIDENCE_PACK_EXECUTION_CONTRACT,
        )
        v6, _ = validate_markdown_result(
            provider_markdown,
            v6_pack,
            requested_artifact_types=["HELP_DOC", "FAQ"],
            execution_contract=EVIDENCE_PACK_EXECUTION_CONTRACT,
        )
        composition = v6["result"].get("qa_composition") or {}
        report = {
            "replay_contract": "geo.m1-2.qa-composition-v6-shadow.v1",
            "database_sha256_before": before,
            "exact_identity": {
                "run_id": run[0],
                "input_scope_hash": run[2],
                "result_version": stored[0],
                "result_hash": stored[1],
            },
            "historical_stored": {
                "run_status": run[1],
                "validation_status": historical.get("status"),
                "validation_contract": historical.get("contract_version"),
                "issue_codes": _codes(historical),
            },
            "v5_shadow": {
                "status": v5["validation"].get("status"),
                "contract": v5["validation"].get("contract_version"),
                "issue_codes": _codes(v5["validation"]),
            },
            "v6_shadow": {
                "status": v6["validation"].get("status"),
                "contract": v6["validation"].get("contract_version"),
                "issue_codes": _codes(v6["validation"]),
                "qa_composition_contract": composition.get("contract_version"),
                "qa_composition_status": composition.get("status"),
                "excluded_fragment_count": len(composition.get("excluded_fragments") or []),
                "provider_output_hash": composition.get("provider_output_hash"),
                "delivery_projection_hash": composition.get("delivery_projection_hash"),
                "composition_hash": composition.get("composition_hash"),
                "observation_id": (composition.get("server_limitation") or {}).get("observation_id"),
                "evidence_set_id": (composition.get("server_limitation") or {}).get("evidence_set_id"),
            },
        }
    finally:
        connection.close()
    after = _sha256(database)
    if after != before:
        raise RuntimeError("PROTECTED_DATABASE_CHANGED_DURING_REPLAY")
    report["database_sha256_after"] = after
    report["database_unchanged"] = True
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = replay(args.database)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
