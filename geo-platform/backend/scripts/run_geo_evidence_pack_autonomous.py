"""Controlled autonomous Evidence Pack batch for the exact P1/P1/R1 comparison.

``prepare`` is zero-provider-call: it freezes one new v2 Agent run, performs the
cache-only gate, authorizes that run locally, and appends/reuses one shared
10-request / 1M-token / CNY10 transport authorization. ``execute`` consumes at
most one request for the selected run. Repeated attempts therefore share one
persistent sub-budget and the historical global ledger.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any

from scripts.run_geo_agent_real_comparison import (
    ANALYSIS_ID, BASELINE_RESULT_HASH, BASELINE_RESULT_VERSION, BATCH_ID,
    CITATION_HASH, CITATION_ID, COMPLETION_HASH, COMPLETION_ID, CONTEXT_ID,
    EXPECTED_SCOPE_HASH, PROJECT_ID, PROMPT_ID, RAW_HASH, _baseline, _canonical,
    _write_json,
)


PRICING_CHECKED_AT = "2026-10-20"
AUTHORIZATION_ID = "evidence-pack-autonomous-p1-p1-r1-20261020"
OPERATION_ID = "evidence-pack-autonomous-p1-p1-r1-20261020"
RUN_KEY_PREFIX = "evidence-pack-autonomous-p1-p1-r1-20261020"
EXPECTED_PACK_HASH = "21260f1074248ead7939be0161c9e9a2b500d82aa185a09fa99bff3e3335c515"
RESPONSE_AUDIT_RETENTION_DAYS = 7
LOCAL_RUN_BUDGET = {
    "max_model_calls": 1,
    "max_tool_calls": 0,
    "max_total_tokens": 300_000,
    "max_elapsed_seconds": 300,
    "max_repairs": 0,
    "max_cost_cny": 3.0,
}


def _imports(database: Path) -> dict[str, Any]:
    os.environ["GEO_RELEASE_DATABASE_URL"] = f"sqlite:///{database.resolve()}"
    from app.core.config import get_settings
    from app.core.release_database import ReleaseSessionLocal
    from app.models import AgentExperimentRun
    from app.modules.agent_experiment.evidence_pack import (
        EVIDENCE_PACK_EXECUTION_CONTRACT,
        EVIDENCE_PACK_PROMPT_VERSION,
        EVIDENCE_PACK_RESULT_CONTRACT,
        EVIDENCE_PACK_TRANSPORT_VERSION,
        build_evidence_pack,
        render_evidence_pack_prompt,
    )
    from app.modules.agent_experiment.response_audit import SecureResponseAuditArchive
    from app.modules.agent_experiment.runner import execute_agent_run
    from app.modules.agent_experiment.service import authorize_agent_run, create_agent_run, get_agent_run
    from app.services.serialization import loads
    from app.services.shared_model_budget import (
        SharedBudgetHooks, append_transport_authorization, summary,
    )
    from app.models import (
        SinglePromptCitationContributionExecution,
        SinglePromptCitationContributionResult,
        SinglePromptDiagnosisExecution,
        SinglePromptDiagnosisResult,
        SinglePromptExecutionProposal,
        SinglePromptExecutionProposalResult,
        SinglePromptStrategyExecution,
        SinglePromptStrategyResult,
    )
    from app.modules.single_prompt_v2.delivery_text import digest
    return locals()


def _assert_shared_budget(state: dict[str, Any]) -> None:
    if state["config"].get("batch_id") != BATCH_ID:
        raise RuntimeError("SHARED_LEDGER_BATCH_MISMATCH")
    if state["in_flight"] != 0:
        raise RuntimeError("SHARED_LEDGER_HAS_IN_FLIGHT_REQUEST")
    if (
        state["remaining_requests"] < 1
        or state["remaining_tokens"] <= 0
        or float(state["remaining_cost_cny"]) <= 0
    ):
        raise RuntimeError("SHARED_LEDGER_GLOBAL_HEADROOM_INSUFFICIENT")


def _extension(state: dict[str, Any]) -> dict[str, Any]:
    rows = [row for row in state.get("authorization_extensions", [])
            if row.get("authorization_id") == AUTHORIZATION_ID]
    if len(rows) != 1:
        raise RuntimeError("AUTONOMOUS_AUTHORIZATION_EXTENSION_MISSING")
    return rows[0]


def _scope_checks(row, symbols: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if row.input_scope_hash != EXPECTED_SCOPE_HASH:
        raise RuntimeError("AGENT_SCOPE_HASH_MISMATCH")
    scope = symbols["loads"](row.input_scope_json, {})
    if (
        scope["identity"]["raw_output_hash"] != RAW_HASH
        or scope["run_scope"].get("run_ids") != [1]
        or len(scope["source_snapshots"]) != 18
        or sum(len(item["passages"]) for item in scope["source_snapshots"]) != 451
    ):
        raise RuntimeError("AGENT_SCOPE_CONTENT_MISMATCH")
    execution = symbols["loads"](row.agent_execution_json, {})
    profile = execution.get("model_profile") or {}
    if (
        execution.get("contract_version") != symbols["EVIDENCE_PACK_EXECUTION_CONTRACT"]
        or execution.get("execution_mode") != "EVIDENCE_PACK"
        or execution.get("tool_allowlist") != []
        or profile.get("max_model_calls") != 1
        or profile.get("automatic_retries") != 0
        or profile.get("reasoning_effort") != "none"
        or profile.get("prompt_version") != symbols["EVIDENCE_PACK_PROMPT_VERSION"]
        or profile.get("response_transport") != symbols["EVIDENCE_PACK_TRANSPORT_VERSION"]
    ):
        raise RuntimeError("EVIDENCE_PACK_V2_EXECUTION_PROFILE_MISMATCH")
    return scope, execution


def _prepare(database: Path, ledger: Path, output: Path, audit_dir: Path,
             *, attempt: int) -> dict[str, Any]:
    if attempt < 1 or attempt > 10:
        raise RuntimeError("AUTONOMOUS_ATTEMPT_OUT_OF_RANGE")
    symbols = _imports(database)
    budget_before = symbols["summary"](ledger)
    _assert_shared_budget(budget_before)
    db = symbols["ReleaseSessionLocal"]()
    try:
        baseline = _baseline(db, symbols)
        if (
            baseline["workflow_result_version"] != BASELINE_RESULT_VERSION
            or baseline["workflow_result_hash"] != BASELINE_RESULT_HASH
        ):
            raise RuntimeError("WORKFLOW_BASELINE_DRIFT")
        run_key = f"{RUN_KEY_PREFIX}-attempt-{attempt}"
        row, _ = symbols["create_agent_run"](
            db,
            project_id=PROJECT_ID,
            prompt_id=PROMPT_ID,
            analysis_id=ANALYSIS_ID,
            context_id=CONTEXT_ID,
            citation_manifest_id=CITATION_ID,
            citation_manifest_hash=CITATION_HASH,
            completion_manifest_id=COMPLETION_ID,
            completion_manifest_hash=COMPLETION_HASH,
            idempotency_key=run_key,
            requested_by="explicit-user-autonomous-authorization-20261020",
            regenerate_nonce=f"autonomous-evidence-pack-{attempt}",
            budget=LOCAL_RUN_BUDGET,
            execution_mode="EVIDENCE_PACK",
        )
        scope, execution = _scope_checks(row, symbols)
        if row.status == "QUEUED" and symbols["loads"](
            row.authorization_json, {},
        ).get("mode") == "CACHE_ONLY":
            run_id = row.run_id
            db.close()
            symbols["execute_agent_run"](
                run_id, session_factory=symbols["ReleaseSessionLocal"],
            )
            db = symbols["ReleaseSessionLocal"]()
            row = db.query(symbols["AgentExperimentRun"]).filter_by(run_id=run_id).one()
        if row.status == "WAITING_AUTHORIZATION":
            row = symbols["authorize_agent_run"](
                db,
                run_id=row.run_id,
                project_id=PROJECT_ID,
                prompt_id=PROMPT_ID,
                revision=row.revision,
                max_requests=1,
                max_total_tokens=300_000,
                max_cost_cny=3.0,
                conservative_cny_per_million_tokens=10.0,
                pricing_source="https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
                pricing_checked_at=PRICING_CHECKED_AT,
                authorized_by="explicit-user-autonomous-authorization-20261020",
            )
        if row.status != "QUEUED" or symbols["loads"](
            row.authorization_json, {},
        ).get("mode") != "EXTERNAL_ALLOWED":
            raise RuntimeError(f"EVIDENCE_PACK_NOT_READY:{row.status}")
        scope, execution = _scope_checks(row, symbols)
        pack = symbols["build_evidence_pack"](scope)
        if pack["evidence_pack_hash"] != EXPECTED_PACK_HASH:
            raise RuntimeError("EVIDENCE_PACK_HASH_DRIFT")
        request_body = {
            "model": "deepseek-flash",
            "instructions": symbols["render_evidence_pack_prompt"](),
            "input": json.dumps(pack, ensure_ascii=False),
            "temperature": 0.0,
            "max_output_tokens": 16_384,
            "reasoning": {"effort": "none"},
        }
        input_upper_bound = len(json.dumps(
            request_body, ensure_ascii=False,
        ).encode("utf-8")) + 4096
        token_ceiling = input_upper_bound + 16_384
        if token_ceiling > 300_000:
            raise RuntimeError("EVIDENCE_PACK_LOCAL_TOKEN_CEILING_EXCEEDED")
        archive = symbols["SecureResponseAuditArchive"](
            audit_dir, retention_days=RESPONSE_AUDIT_RETENTION_DAYS,
        )
        archive.prepare()
        authorization = symbols["append_transport_authorization"](
            ledger,
            authorization_id=AUTHORIZATION_ID,
            batch_id=BATCH_ID,
            lane="AGENT_EXPERIMENT",
            operation_id=OPERATION_ID,
            scope={
                "project_id": PROJECT_ID,
                "prompt_id": PROMPT_ID,
                "run_ids": [1],
                "analysis_id": ANALYSIS_ID,
                "context_id": CONTEXT_ID,
                "raw_output_hash": RAW_HASH,
                "input_scope_hash": row.input_scope_hash,
                "evidence_pack_hash": pack["evidence_pack_hash"],
                "allowed_regeneration": "SAME_FROZEN_SCOPE_ONLY",
            },
            transport_kind="RESPONSES_TEXT",
            transport_version=symbols["EVIDENCE_PACK_TRANSPORT_VERSION"],
            prompt_version=symbols["EVIDENCE_PACK_PROMPT_VERSION"],
            schema_version=symbols["EVIDENCE_PACK_RESULT_CONTRACT"],
            execution_contract=execution["contract_version"],
            pricing_checked_at=PRICING_CHECKED_AT,
            max_requests=10,
            max_tokens=1_000_000,
            max_cost_cny=10.0,
            authorized_by="explicit-user-autonomous-authorization-20261020",
        )
        budget_after = symbols["summary"](ledger)
        extension = _extension(budget_after)
        if extension["remaining_requests"] < 1:
            raise RuntimeError("AUTONOMOUS_AUTHORIZATION_EXHAUSTED")
        report = {
            "status": "READY_FOR_AUTONOMOUS_EVIDENCE_PACK_REQUEST",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "external_calls": 0,
            "attempt": attempt,
            "database": str(database.resolve()),
            "ledger": str(ledger.resolve()),
            "agent": symbols["get_agent_run"](
                db, run_id=row.run_id, project_id=PROJECT_ID, prompt_id=PROMPT_ID,
            ),
            "workflow_baseline": baseline,
            "pairing": {
                "project_id": PROJECT_ID,
                "prompt_id": PROMPT_ID,
                "run_ids": [1],
                "input_scope_hash": row.input_scope_hash,
                "strict_pairing": True,
            },
            "evidence_pack": {
                "hash": pack["evidence_pack_hash"],
                "coverage": pack["coverage"],
                "input_upper_bound": input_upper_bound,
                "max_output_tokens": 16_384,
                "token_ceiling": token_ceiling,
                "reasoning_effort": "none",
            },
            "authorization": authorization,
            "authorization_extension": extension,
            "shared_budget": budget_after,
            "response_audit": {
                "directory": str(archive.root),
                "retention_days": archive.retention_days,
                "directory_mode": "0700",
                "file_mode": "0600",
            },
        }
        _write_json(output, report)
        return report
    finally:
        db.close()


def _execute(database: Path, ledger: Path, output: Path, audit_dir: Path,
             *, run_id: str) -> dict[str, Any]:
    symbols = _imports(database)
    if not symbols["get_settings"]().deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY_NOT_CONFIGURED")
    budget_before = symbols["summary"](ledger)
    _assert_shared_budget(budget_before)
    extension_before = _extension(budget_before)
    if extension_before["remaining_requests"] < 1:
        raise RuntimeError("AUTONOMOUS_AUTHORIZATION_EXHAUSTED")
    db = symbols["ReleaseSessionLocal"]()
    try:
        row = db.query(symbols["AgentExperimentRun"]).filter_by(run_id=run_id).one_or_none()
        if not row or not row.idempotency_key.startswith(RUN_KEY_PREFIX):
            raise RuntimeError("AUTONOMOUS_AGENT_RUN_NOT_FOUND")
        _scope_checks(row, symbols)
        if row.status != "QUEUED":
            raise RuntimeError(f"EVIDENCE_PACK_NOT_EXECUTABLE:{row.status}")
    finally:
        db.close()
    archive = symbols["SecureResponseAuditArchive"](
        audit_dir, retention_days=RESPONSE_AUDIT_RETENTION_DAYS,
    )
    archive.prepare()
    audit_before = set(archive.root.glob("agent-response-*.json"))
    hooks = symbols["SharedBudgetHooks"](
        ledger, lane="AGENT_EXPERIMENT", operation_id=OPERATION_ID,
    )
    started = time.monotonic()
    symbols["execute_agent_run"](
        run_id,
        session_factory=symbols["ReleaseSessionLocal"],
        shared_budget_hooks=hooks,
        response_audit_archive=archive,
    )
    elapsed = time.monotonic() - started
    db = symbols["ReleaseSessionLocal"]()
    try:
        agent = symbols["get_agent_run"](
            db, run_id=run_id, project_id=PROJECT_ID, prompt_id=PROMPT_ID,
        )
        baseline = _baseline(db, symbols)
        budget_after = symbols["summary"](ledger)
        extension_after = _extension(budget_after)
        request_delta = budget_after["used_requests"] - budget_before["used_requests"]
        if request_delta != 1:
            raise RuntimeError(f"AUTONOMOUS_REQUEST_DELTA_INVALID:{request_delta}")
        audit_after = set(archive.root.glob("agent-response-*.json"))
        report = {
            "status": "AUTONOMOUS_EVIDENCE_PACK_ATTEMPT_FINISHED",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 3),
            "agent": agent,
            "workflow_baseline": baseline,
            "shared_budget": budget_after,
            "shared_budget_delta": {
                "requests": request_delta,
                "tokens": budget_after["used_tokens"] - budget_before["used_tokens"],
                "cost_cny": round(
                    float(budget_after["used_cost_cny"])
                    - float(budget_before["used_cost_cny"]), 8,
                ),
            },
            "authorization_extension": extension_after,
            "response_audit": {
                "directory": str(archive.root),
                "new_files": sorted(str(path) for path in audit_after - audit_before),
                "retention_days": archive.retention_days,
            },
        }
        _write_json(output, report)
        return report
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "execute"))
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--response-audit-dir", type=Path, required=True)
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--agent-run-id")
    args = parser.parse_args()
    if args.mode == "execute" and not args.agent_run_id:
        parser.error("--agent-run-id is required for execute")
    result = (
        _prepare(
            args.database, args.ledger, args.output, args.response_audit_dir,
            attempt=args.attempt,
        )
        if args.mode == "prepare"
        else _execute(
            args.database, args.ledger, args.output, args.response_audit_dir,
            run_id=args.agent_run_id,
        )
    )
    print(_canonical({
        "status": result["status"],
        "output": str(args.output.resolve()),
        "agent_run_id": (result.get("agent") or {}).get("run_id"),
        "used_requests": result.get("shared_budget", {}).get("used_requests", 0),
        "used_tokens": result.get("shared_budget", {}).get("used_tokens", 0),
        "used_cost_cny": result.get("shared_budget", {}).get("used_cost_cny", 0),
    }))


if __name__ == "__main__":
    main()
