"""Run the single authorized GEO Agent/Workflow real-model comparison.

This controller is intentionally fixed to Project 1 / Prompt 1 / Run 1 and the
known immutable formal result chain.  ``prepare`` performs no external call;
``execute`` runs exactly one Agent experiment through the shared persistent
budget ledger.  The existing Workflow v7 result is reused, so this controller
never samples, fetches, publishes, or starts a second scenario.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any


PROJECT_ID = 1
PROMPT_ID = 1
ANALYSIS_ID = "925ef2dc-605f-467d-a025-52033a574d92"
CONTEXT_ID = "ctx-5407fb2f-acd5-41ac-8ac7-41713a08a5aa"
RAW_HASH = "11dca9e4438bdecf66a86472f2e8a498f6f7067c3bcc4f9f3cfd381d2c9ebccb"
CITATION_ID = "citation-manifest-2c54878d-fe08-4781-ae5d-5a733761c67c"
CITATION_HASH = "c0b5ad9c6924e04f117a901059adc4df10b19b9cc57fc05f1be36f833042ef35"
COMPLETION_ID = "source-completion-d49694de-76da-4ebf-a198-efb101fc1224"
COMPLETION_HASH = "444719912b95cea6a03db1cfbf85196c4dd61e5b9b4772486d4b525e54fab1cf"
EXPECTED_SCOPE_HASH = "69a86f8ecdc574e5a7631d6982270e1a25e29485937df4c17d2205ed99a7b2c7"
BASELINE_PROPOSAL_ID = "execution-proposal-43feb8f4-26b1-4eb2-b6c0-74298af17fb4"
BASELINE_RESULT_VERSION = "execution-v7:c2dc55b0d25749c7"
BASELINE_RESULT_HASH = "c2dc55b0d25749c712c4076260f2a1039c021e76ce8569df839ab04d842e9081"
PRICING_CHECKED_AT = "2026-10-19"
BATCH_ID = "geo-agent-workflow-comparison-p1-p1-r1-20261019"
CONTEXT_REPAIR_ATTEMPT = 3
REAL_VALIDATION_ATTEMPT = 4
EXPECTED_PRIOR_REQUESTS = 18
EXPECTED_PRIOR_TOKENS = 137_492
EXPECTED_PRIOR_COST_CNY = 1.37492


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _imports(database: Path):
    os.environ["GEO_RELEASE_DATABASE_URL"] = f"sqlite:///{database.resolve()}"
    from app.core.release_database import ReleaseSessionLocal
    from app.core.config import get_settings
    from app.models import (
        AgentExperimentRun,
        SinglePromptDiagnosisExecution,
        SinglePromptDiagnosisResult,
        SinglePromptCitationContributionExecution,
        SinglePromptCitationContributionResult,
        SinglePromptStrategyExecution,
        SinglePromptStrategyResult,
        SinglePromptExecutionProposal,
        SinglePromptExecutionProposalResult,
    )
    from app.modules.agent_experiment.runner import execute_agent_run
    from app.modules.agent_experiment.response_audit import SecureResponseAuditArchive
    from app.modules.agent_experiment.service import (
        authorize_agent_run, create_agent_run, get_agent_run,
    )
    from app.modules.single_prompt_v2.delivery_text import digest
    from app.services.serialization import loads
    from app.services.shared_model_budget import SharedBudgetHooks, initialize, summary
    return locals()


def _baseline(db, symbols: dict[str, Any]) -> dict[str, Any]:
    digest = symbols["digest"]
    chain = [
        ("diagnosis", symbols["SinglePromptDiagnosisExecution"], "diagnosis_id",
         "11d47cb9-3e56-4228-9101-55fdfec19d15", symbols["SinglePromptDiagnosisResult"],
         "diag-v1:864a6924a61a3e8b"),
        ("contribution", symbols["SinglePromptCitationContributionExecution"], "contribution_id",
         "citation-contribution-ac2945d2-2737-4cc5-9c2e-40dcd906b530",
         symbols["SinglePromptCitationContributionResult"], "contribution-v1:be21567a6d114f4b"),
        ("strategy", symbols["SinglePromptStrategyExecution"], "strategy_id",
         "strategy-ef6ac968-c400-4528-8913-634b4216eada", symbols["SinglePromptStrategyResult"],
         "strategy-v1:178f23f7c8de96a1"),
        ("execution", symbols["SinglePromptExecutionProposal"], "proposal_id",
         BASELINE_PROPOSAL_ID, symbols["SinglePromptExecutionProposalResult"], BASELINE_RESULT_VERSION),
    ]
    verified: dict[str, Any] = {}
    baseline_output: dict[str, Any] = {}
    for name, execution_model, key, object_id, result_model, result_version in chain:
        execution = db.query(execution_model).filter(getattr(execution_model, key) == object_id).one_or_none()
        result = db.query(result_model).filter_by(result_version=result_version).one_or_none()
        if not execution or not result:
            raise RuntimeError(f"BASELINE_{name.upper()}_MISSING")
        output = symbols["loads"](result.output_json, {})
        if (
            execution.analysis_id != ANALYSIS_ID or execution.context_id != CONTEXT_ID
            or execution.project_id != PROJECT_ID or execution.prompt_id != PROMPT_ID
            or digest(output) != result.output_hash
        ):
            raise RuntimeError(f"BASELINE_{name.upper()}_IDENTITY_OR_HASH_MISMATCH")
        if name != "execution" and execution.active_result_version != result_version:
            raise RuntimeError(f"BASELINE_{name.upper()}_NOT_ACTIVE")
        verified[name] = {
            "object_id": object_id, "result_version": result_version,
            "result_hash": result.output_hash, "status": execution.status,
            "hash_valid": True,
        }
        if name == "execution":
            if result.output_hash != BASELINE_RESULT_HASH or execution.active_result_version != BASELINE_RESULT_VERSION:
                raise RuntimeError("BASELINE_EXECUTION_ACTIVE_VERSION_MISMATCH")
            baseline = output.get("baseline") or {}
            if (
                baseline.get("analysis_id") != ANALYSIS_ID
                or baseline.get("context_id") != CONTEXT_ID
                or baseline.get("baseline_run_ids") != [1]
                or baseline.get("raw_output_hash") != RAW_HASH
            ):
                raise RuntimeError("BASELINE_EXECUTION_FROZEN_SCOPE_MISMATCH")
            baseline_output = output
    return {"chain": verified, "result": baseline_output}


def _run_key(attempt: int) -> str:
    if attempt == CONTEXT_REPAIR_ATTEMPT:
        # The first zero-call preflight for this attempt intentionally remains
        # as a BLOCKED audit row: it was executed outside the repository's
        # relative monitoring-artifact root and failed Run revalidation.
        return "real-comparison-p1-p1-r1-20261019-repair-3-artifact-root"
    if attempt == REAL_VALIDATION_ATTEMPT:
        # Preserve the zero-call BLOCKED row created from the wrong relative
        # artifact root; this key is only used from backend/, where Run 1's
        # immutable semantic-region artifacts live.
        return "real-comparison-p1-p1-r1-20261020-validation-5-artifact-root"
    return ("real-comparison-p1-p1-r1-20261019" if attempt == 0
            else f"real-comparison-p1-p1-r1-20261019-repair-{attempt}")


def _attempt_budget(attempt: int) -> dict[str, Any]:
    if attempt in {CONTEXT_REPAIR_ATTEMPT, REAL_VALIDATION_ATTEMPT}:
        return {"max_model_calls": 10, "max_tool_calls": 12, "max_total_tokens": 300_000,
                "max_elapsed_seconds": 300, "max_repairs": 1, "max_cost_cny": 3.0}
    return {"max_model_calls": 6, "max_tool_calls": 12, "max_total_tokens": 100_000,
            "max_elapsed_seconds": 300, "max_repairs": 1, "max_cost_cny": 5.0}


def _preflight(database: Path, ledger: Path, output: Path, *, attempt: int,
               response_audit_dir: Path | None = None) -> dict[str, Any]:
    symbols = _imports(database)
    db = symbols["ReleaseSessionLocal"]()
    try:
        baseline = _baseline(db, symbols)
        row, _ = symbols["create_agent_run"](
            db, project_id=PROJECT_ID, prompt_id=PROMPT_ID, analysis_id=ANALYSIS_ID,
            context_id=CONTEXT_ID, citation_manifest_id=CITATION_ID,
            citation_manifest_hash=CITATION_HASH, completion_manifest_id=COMPLETION_ID,
            completion_manifest_hash=COMPLETION_HASH,
            idempotency_key=_run_key(attempt), requested_by="authorized-operator",
            regenerate_nonce=(f"manual-repair-{attempt}" if attempt else None),
            budget=_attempt_budget(attempt),
        )
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
        if row.status == "QUEUED" and symbols["loads"](row.authorization_json, {}).get("mode") == "CACHE_ONLY":
            db.close()
            symbols["execute_agent_run"](row.run_id, session_factory=symbols["ReleaseSessionLocal"])
            db = symbols["ReleaseSessionLocal"]()
            row = db.query(symbols["AgentExperimentRun"]).filter_by(run_id=row.run_id).one()
        if row.status == "WAITING_AUTHORIZATION":
            authorized = _attempt_budget(attempt)
            row = symbols["authorize_agent_run"](
                db, run_id=row.run_id, project_id=PROJECT_ID, prompt_id=PROMPT_ID,
                revision=row.revision, max_requests=authorized["max_model_calls"],
                max_total_tokens=authorized["max_total_tokens"],
                max_cost_cny=authorized["max_cost_cny"],
                conservative_cny_per_million_tokens=10.0,
                pricing_source="https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
                pricing_checked_at=PRICING_CHECKED_AT, authorized_by="explicit-user-authorization-20261020",
            )
        if row.status != "QUEUED" or symbols["loads"](row.authorization_json, {}).get("mode") != "EXTERNAL_ALLOWED":
            raise RuntimeError(f"AGENT_NOT_READY:{row.status}")
        symbols["initialize"](
            ledger, batch_id=BATCH_ID, pricing_checked_at=PRICING_CHECKED_AT,
        )
        budget = symbols["summary"](ledger)
        if budget["in_flight"] != 0:
            raise RuntimeError("SHARED_LEDGER_HAS_IN_FLIGHT_REQUEST")
        if attempt == 0 and budget["used_requests"] != 0:
            raise RuntimeError("SHARED_LEDGER_NOT_PRISTINE")
        if attempt == REAL_VALIDATION_ATTEMPT and (
            budget["used_requests"] != EXPECTED_PRIOR_REQUESTS
            or budget["used_tokens"] != EXPECTED_PRIOR_TOKENS
            or abs(float(budget["used_cost_cny"]) - EXPECTED_PRIOR_COST_CNY) > 1e-8
        ):
            raise RuntimeError("SHARED_LEDGER_PRIOR_USAGE_MISMATCH")
        response_audit = None
        if attempt == REAL_VALIDATION_ATTEMPT:
            if response_audit_dir is None:
                raise RuntimeError("RESPONSE_AUDIT_DIRECTORY_REQUIRED")
            archive = symbols["SecureResponseAuditArchive"](response_audit_dir, retention_days=7)
            archive.prepare()
            response_audit = {
                "directory": str(archive.root), "directory_mode": "0700",
                "file_mode": "0600", "retention_days": archive.retention_days,
                "stores_request_headers": False, "stores_request_payload": False,
            }
        report = {
            "status": "READY_FOR_ONE_REAL_AGENT_RUN",
            "manual_attempt": attempt,
            "external_calls": 0,
            "database": str(database.resolve()),
            "ledger": str(ledger.resolve()),
            "agent": symbols["get_agent_run"](
                db, run_id=row.run_id, project_id=PROJECT_ID, prompt_id=PROMPT_ID,
            ),
            "baseline": baseline,
            "shared_budget": budget,
            "authorized_sub_budget": {
                "max_requests": 10 if attempt in {CONTEXT_REPAIR_ATTEMPT, REAL_VALIDATION_ATTEMPT} else 6,
                "max_tokens": 300_000 if attempt in {CONTEXT_REPAIR_ATTEMPT, REAL_VALIDATION_ATTEMPT} else 100_000,
                "max_cost_cny": 3.0 if attempt in {CONTEXT_REPAIR_ATTEMPT, REAL_VALIDATION_ATTEMPT} else 1.0,
                "automatic_retries": 0,
            },
            "response_audit": response_audit,
            "pairing": {
                "project_id": PROJECT_ID, "prompt_id": PROMPT_ID, "run_ids": [1],
                "analysis_id": ANALYSIS_ID, "context_id": CONTEXT_ID,
                "raw_output_hash": RAW_HASH, "citation_manifest_id": CITATION_ID,
                "citation_manifest_hash": CITATION_HASH,
                "completion_manifest_id": COMPLETION_ID,
                "completion_manifest_hash": COMPLETION_HASH,
                "agent_input_scope_hash": row.input_scope_hash,
                "truth_set_hash": scope["product_truth"]["set_hash"],
                "project_configuration": scope["project_configuration"],
                "prompt_version": scope["prompt"]["version"],
                "strict_pairing": True,
                "workflow_call_required": False,
            },
        }
        _write_json(output, report)
        return report
    finally:
        db.close()


def _execute(database: Path, ledger: Path, output: Path, *, attempt: int,
             response_audit_dir: Path | None = None) -> dict[str, Any]:
    symbols = _imports(database)
    settings = symbols["get_settings"]()
    if not settings.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY_NOT_CONFIGURED")
    state = symbols["summary"](ledger)
    if state["in_flight"] != 0:
        raise RuntimeError("SHARED_LEDGER_HAS_IN_FLIGHT_REQUEST")
    if attempt == 0 and state["used_requests"] != 0:
        raise RuntimeError("SHARED_LEDGER_NOT_PRISTINE")
    if attempt == REAL_VALIDATION_ATTEMPT and (
        state["used_requests"] != EXPECTED_PRIOR_REQUESTS
        or state["used_tokens"] != EXPECTED_PRIOR_TOKENS
        or abs(float(state["used_cost_cny"]) - EXPECTED_PRIOR_COST_CNY) > 1e-8
    ):
        raise RuntimeError("SHARED_LEDGER_PRIOR_USAGE_MISMATCH")
    if attempt == REAL_VALIDATION_ATTEMPT and response_audit_dir is None:
        raise RuntimeError("RESPONSE_AUDIT_DIRECTORY_REQUIRED")
    archive = (symbols["SecureResponseAuditArchive"](response_audit_dir, retention_days=7)
               if response_audit_dir is not None else None)
    if archive is not None:
        archive.prepare()
    audit_before = set(archive.root.glob("agent-response-*.json")) if archive is not None else set()
    db = symbols["ReleaseSessionLocal"]()
    try:
        row = db.query(symbols["AgentExperimentRun"]).filter_by(
            project_id=PROJECT_ID, prompt_id=PROMPT_ID,
            idempotency_key=_run_key(attempt),
        ).one()
        if row.status != "QUEUED" or row.input_scope_hash != EXPECTED_SCOPE_HASH:
            raise RuntimeError(f"AGENT_NOT_EXECUTABLE:{row.status}")
        run_id = row.run_id
    finally:
        db.close()
    hooks = symbols["SharedBudgetHooks"](
        ledger, lane="AGENT_EXPERIMENT", operation_id=run_id,
    )
    started = time.monotonic()
    symbols["execute_agent_run"](
        run_id, session_factory=symbols["ReleaseSessionLocal"], shared_budget_hooks=hooks,
        response_audit_archive=archive,
    )
    elapsed = time.monotonic() - started
    db = symbols["ReleaseSessionLocal"]()
    try:
        agent = symbols["get_agent_run"](
            db, run_id=run_id, project_id=PROJECT_ID, prompt_id=PROMPT_ID,
        )
        baseline = _baseline(db, symbols)
        budget = symbols["summary"](ledger)
        audit_after = set(archive.root.glob("agent-response-*.json")) if archive is not None else set()
        if budget["by_lane"]["WORKFLOW_BASELINE"] != 0:
            raise RuntimeError("UNEXPECTED_WORKFLOW_MODEL_CALL")
        report = {
            "status": "FIRST_REAL_PAIR_FINISHED_AND_STOPPED",
            "manual_attempt": attempt,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 3),
            "agent": agent,
            "workflow_baseline": baseline,
            "shared_budget": budget,
            "shared_budget_delta": {
                "requests": budget["used_requests"] - state["used_requests"],
                "tokens": budget["used_tokens"] - state["used_tokens"],
                "cost_cny": round(float(budget["used_cost_cny"]) - float(state["used_cost_cny"]), 8),
            },
            "stopped_before_second_scenario": True,
            "response_audit": {
                "directory": str(archive.root) if archive is not None else None,
                "new_files": sorted(str(path) for path in audit_after - audit_before),
                "retention_days": archive.retention_days if archive is not None else None,
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
    parser.add_argument("--attempt", type=int, default=0, choices=range(0, 5))
    parser.add_argument("--response-audit-dir", type=Path)
    args = parser.parse_args()
    result = (_preflight(args.database, args.ledger, args.output, attempt=args.attempt,
                         response_audit_dir=args.response_audit_dir)
              if args.mode == "prepare" else _execute(
                  args.database, args.ledger, args.output, attempt=args.attempt,
                  response_audit_dir=args.response_audit_dir))
    # Never print model content or credentials to the terminal.  The complete
    # comparison is written mode 0600 to the requested artifact path.
    print(_canonical({
        "status": result["status"],
        "output": str(args.output.resolve()),
        "used_requests": result.get("shared_budget", {}).get("used_requests", 0),
        "used_tokens": result.get("shared_budget", {}).get("used_tokens", 0),
        "used_cost_cny": result.get("shared_budget", {}).get("used_cost_cny", 0),
    }))


if __name__ == "__main__":
    main()
