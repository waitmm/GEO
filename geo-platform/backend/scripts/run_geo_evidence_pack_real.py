"""Prepare and execute the one authorized Evidence Pack real-model validation.

This controller is fixed to Project 1 / Prompt 1 / Run 1 and the existing
strictly paired Workflow baseline. ``prepare`` performs no provider call and
appends one immutable RESPONSES_TEXT authorization to the historical shared
ledger. ``execute`` can consume that authorization exactly once.
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
RUN_KEY = "evidence-pack-p1-p1-r1-20261020-real-1"
AUTHORIZATION_ID = "evidence-pack-p1-p1-r1-20261020-real-1"
RESPONSE_AUDIT_RETENTION_DAYS = 7
EXPECTED_PRIOR_USAGE = {"requests": 20, "tokens": 176_174, "cost_cny": 1.76174}
EVIDENCE_BUDGET = {
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
        EVIDENCE_PACK_RESULT_CONTRACT,
        LEGACY_EVIDENCE_PACK_PROMPT_VERSION,
        LEGACY_EVIDENCE_PACK_TRANSPORT_VERSION,
        build_evidence_pack,
        render_evidence_pack_prompt,
    )
    from app.modules.agent_experiment.response_audit import SecureResponseAuditArchive
    from app.modules.agent_experiment.runner import execute_agent_run
    from app.modules.agent_experiment.service import (
        authorize_agent_run,
        create_agent_run,
        get_agent_run,
    )
    from app.services.serialization import loads
    from app.services.shared_model_budget import (
        SharedBudgetHooks,
        append_transport_authorization,
        summary,
    )
    # Models/helpers consumed by the pre-existing, frozen baseline verifier.
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


def _assert_prior_budget(state: dict[str, Any]) -> None:
    if state["in_flight"] != 0:
        raise RuntimeError("SHARED_LEDGER_HAS_IN_FLIGHT_REQUEST")
    if (
        state["used_requests"] != EXPECTED_PRIOR_USAGE["requests"]
        or state["used_tokens"] != EXPECTED_PRIOR_USAGE["tokens"]
        or abs(float(state["used_cost_cny"]) - EXPECTED_PRIOR_USAGE["cost_cny"]) > 1e-8
    ):
        raise RuntimeError("SHARED_LEDGER_PRIOR_USAGE_MISMATCH")
    if state["remaining_requests"] < 1 or state["remaining_tokens"] < 300_000 \
            or float(state["remaining_cost_cny"]) < 3.0:
        raise RuntimeError("SHARED_LEDGER_GLOBAL_HEADROOM_INSUFFICIENT")


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
    if (
        execution.get("contract_version") != "geo.evidence-pack.execution.v1"
        or execution.get("execution_mode") != "EVIDENCE_PACK"
        or execution.get("tool_allowlist") != []
        or execution.get("model_profile", {}).get("max_model_calls") != 1
        or execution.get("model_profile", {}).get("automatic_retries") != 0
    ):
        raise RuntimeError("EVIDENCE_PACK_EXECUTION_PROFILE_MISMATCH")
    return scope, execution


def _extension(state: dict[str, Any]) -> dict[str, Any]:
    rows = [row for row in state.get("authorization_extensions", [])
            if row.get("authorization_id") == AUTHORIZATION_ID]
    if len(rows) != 1:
        raise RuntimeError("EVIDENCE_PACK_AUTHORIZATION_EXTENSION_MISSING")
    return rows[0]


def _prepare(database: Path, ledger: Path, output: Path, audit_dir: Path) -> dict[str, Any]:
    symbols = _imports(database)
    budget_before = symbols["summary"](ledger)
    _assert_prior_budget(budget_before)
    db = symbols["ReleaseSessionLocal"]()
    try:
        baseline = _baseline(db, symbols)
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
            idempotency_key=RUN_KEY,
            requested_by="explicit-user-authorization-20261020",
            regenerate_nonce="evidence-pack-real-1",
            budget=EVIDENCE_BUDGET,
            execution_mode="EVIDENCE_PACK",
        )
        scope, execution = _scope_checks(row, symbols)
        if row.status == "QUEUED" and symbols["loads"](row.authorization_json, {}).get("mode") == "CACHE_ONLY":
            db.close()
            symbols["execute_agent_run"](row.run_id, session_factory=symbols["ReleaseSessionLocal"])
            db = symbols["ReleaseSessionLocal"]()
            row = db.query(symbols["AgentExperimentRun"]).filter_by(run_id=row.run_id).one()
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
                authorized_by="explicit-user-authorization-20261020",
            )
        if row.status != "QUEUED" or symbols["loads"](row.authorization_json, {}).get("mode") != "EXTERNAL_ALLOWED":
            raise RuntimeError(f"EVIDENCE_PACK_NOT_READY:{row.status}")
        scope, execution = _scope_checks(row, symbols)
        pack = symbols["build_evidence_pack"](scope)
        system_prompt = symbols["render_evidence_pack_prompt"]()
        request_body = {
            "model": "deepseek-flash",
            "instructions": system_prompt,
            "input": json.dumps(pack, ensure_ascii=False),
            "temperature": 0.0,
            "max_output_tokens": 16_384,
            "reasoning": {"effort": "high"},
        }
        input_upper_bound = len(json.dumps(request_body, ensure_ascii=False).encode("utf-8")) + 4096
        token_ceiling = input_upper_bound + 16_384
        reserved_cost = round(token_ceiling * 10.0 / 1_000_000, 8)
        if token_ceiling > 300_000 or reserved_cost > 3.0:
            raise RuntimeError("EVIDENCE_PACK_WORST_CASE_EXCEEDS_SUB_BUDGET")
        archive = symbols["SecureResponseAuditArchive"](
            audit_dir, retention_days=RESPONSE_AUDIT_RETENTION_DAYS,
        )
        archive.prepare()
        authorization = symbols["append_transport_authorization"](
            ledger,
            authorization_id=AUTHORIZATION_ID,
            batch_id=BATCH_ID,
            lane="AGENT_EXPERIMENT",
            operation_id=row.run_id,
            scope={
                "project_id": PROJECT_ID,
                "prompt_id": PROMPT_ID,
                "run_ids": [1],
                "analysis_id": ANALYSIS_ID,
                "context_id": CONTEXT_ID,
                "raw_output_hash": RAW_HASH,
                "input_scope_hash": row.input_scope_hash,
                "agent_execution_hash": row.agent_execution_hash,
                "evidence_pack_hash": pack["evidence_pack_hash"],
            },
            transport_kind="RESPONSES_TEXT",
            transport_version=symbols["LEGACY_EVIDENCE_PACK_TRANSPORT_VERSION"],
            prompt_version=symbols["LEGACY_EVIDENCE_PACK_PROMPT_VERSION"],
            schema_version=symbols["EVIDENCE_PACK_RESULT_CONTRACT"],
            execution_contract=execution["contract_version"],
            pricing_checked_at=PRICING_CHECKED_AT,
            max_requests=1,
            max_tokens=300_000,
            max_cost_cny=3.0,
            authorized_by="explicit-user-authorization-20261020",
        )
        budget_after = symbols["summary"](ledger)
        extension = _extension(budget_after)
        if extension["used_requests"] != 0 or extension["remaining_requests"] != 1:
            raise RuntimeError("EVIDENCE_PACK_AUTHORIZATION_ALREADY_CONSUMED")
        report = {
            "status": "READY_FOR_ONE_EVIDENCE_PACK_REAL_REQUEST",
            "external_calls": 0,
            "database": str(database.resolve()),
            "ledger": str(ledger.resolve()),
            "agent": symbols["get_agent_run"](
                db, run_id=row.run_id, project_id=PROJECT_ID, prompt_id=PROMPT_ID,
            ),
            "baseline": baseline,
            "pairing": {
                "project_id": PROJECT_ID,
                "prompt_id": PROMPT_ID,
                "run_ids": [1],
                "analysis_id": ANALYSIS_ID,
                "context_id": CONTEXT_ID,
                "raw_output_hash": RAW_HASH,
                "input_scope_hash": row.input_scope_hash,
                "strict_pairing": True,
                "workflow_result_version": BASELINE_RESULT_VERSION,
                "workflow_result_hash": BASELINE_RESULT_HASH,
            },
            "evidence_pack": {
                "hash": pack["evidence_pack_hash"],
                "coverage": pack["coverage"],
                "estimated_request_input_upper_bound": input_upper_bound,
                "max_output_tokens": 16_384,
                "worst_case_token_ceiling": token_ceiling,
                "worst_case_reserved_cost_cny": reserved_cost,
            },
            "authorization": authorization,
            "shared_budget": budget_after,
            "response_audit": {
                "directory": str(archive.root),
                "directory_mode": "0700",
                "file_mode": "0600",
                "retention_days": archive.retention_days,
                "stores_request_headers": False,
            },
        }
        _write_json(output, report)
        return report
    finally:
        db.close()


def _execute(database: Path, ledger: Path, output: Path, audit_dir: Path) -> dict[str, Any]:
    symbols = _imports(database)
    if not symbols["get_settings"]().deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY_NOT_CONFIGURED")
    budget_before = symbols["summary"](ledger)
    _assert_prior_budget(budget_before)
    extension_before = _extension(budget_before)
    if extension_before["used_requests"] != 0 or extension_before["remaining_requests"] != 1:
        raise RuntimeError("EVIDENCE_PACK_AUTHORIZATION_NOT_AVAILABLE")
    db = symbols["ReleaseSessionLocal"]()
    try:
        row = db.query(symbols["AgentExperimentRun"]).filter_by(
            project_id=PROJECT_ID, prompt_id=PROMPT_ID, idempotency_key=RUN_KEY,
        ).one()
        _scope_checks(row, symbols)
        if row.status != "QUEUED":
            raise RuntimeError(f"EVIDENCE_PACK_NOT_EXECUTABLE:{row.status}")
        run_id = row.run_id
    finally:
        db.close()
    archive = symbols["SecureResponseAuditArchive"](
        audit_dir, retention_days=RESPONSE_AUDIT_RETENTION_DAYS,
    )
    archive.prepare()
    audit_before = set(archive.root.glob("agent-response-*.json"))
    hooks = symbols["SharedBudgetHooks"](
        ledger, lane="AGENT_EXPERIMENT", operation_id=run_id,
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
        if budget_after["used_requests"] - budget_before["used_requests"] != 1:
            raise RuntimeError("EVIDENCE_PACK_REAL_REQUEST_DELTA_NOT_ONE")
        if extension_after["used_requests"] != 1 or extension_after["remaining_requests"] != 0:
            raise RuntimeError("EVIDENCE_PACK_AUTHORIZATION_NOT_EXACTLY_CONSUMED")
        audit_after = set(archive.root.glob("agent-response-*.json"))
        report = {
            "status": "EVIDENCE_PACK_REAL_REQUEST_FINISHED_AND_STOPPED",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 3),
            "agent": agent,
            "workflow_baseline": baseline,
            "shared_budget": budget_after,
            "shared_budget_delta": {
                "requests": 1,
                "tokens": budget_after["used_tokens"] - budget_before["used_tokens"],
                "cost_cny": round(
                    float(budget_after["used_cost_cny"]) - float(budget_before["used_cost_cny"]), 8
                ),
            },
            "authorization_extension": extension_after,
            "response_audit": {
                "directory": str(archive.root),
                "new_files": sorted(str(path) for path in audit_after - audit_before),
                "retention_days": archive.retention_days,
            },
            "external_calls_stopped": True,
            "second_scenario_started": False,
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
    args = parser.parse_args()
    result = (
        _prepare(args.database, args.ledger, args.output, args.response_audit_dir)
        if args.mode == "prepare"
        else _execute(args.database, args.ledger, args.output, args.response_audit_dir)
    )
    print(_canonical({
        "status": result["status"],
        "output": str(args.output.resolve()),
        "used_requests": result.get("shared_budget", {}).get("used_requests", 0),
        "used_tokens": result.get("shared_budget", {}).get("used_tokens", 0),
        "used_cost_cny": result.get("shared_budget", {}).get("used_cost_cny", 0),
    }))


if __name__ == "__main__":
    main()
