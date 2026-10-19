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


def _preflight(database: Path, ledger: Path, output: Path) -> dict[str, Any]:
    symbols = _imports(database)
    db = symbols["ReleaseSessionLocal"]()
    try:
        baseline = _baseline(db, symbols)
        row, _ = symbols["create_agent_run"](
            db, project_id=PROJECT_ID, prompt_id=PROMPT_ID, analysis_id=ANALYSIS_ID,
            context_id=CONTEXT_ID, citation_manifest_id=CITATION_ID,
            citation_manifest_hash=CITATION_HASH, completion_manifest_id=COMPLETION_ID,
            completion_manifest_hash=COMPLETION_HASH,
            idempotency_key="real-comparison-p1-p1-r1-20261019", requested_by="authorized-operator",
            budget={"max_model_calls": 6, "max_tool_calls": 12, "max_total_tokens": 100_000,
                    "max_elapsed_seconds": 300, "max_repairs": 1, "max_cost_cny": 5.0},
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
            row = symbols["authorize_agent_run"](
                db, run_id=row.run_id, project_id=PROJECT_ID, prompt_id=PROMPT_ID,
                revision=row.revision, max_requests=6, max_total_tokens=100_000, max_cost_cny=1.0,
                conservative_cny_per_million_tokens=10.0,
                pricing_source="https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
                pricing_checked_at=PRICING_CHECKED_AT, authorized_by="explicit-user-authorization-20261019",
            )
        if row.status != "QUEUED" or symbols["loads"](row.authorization_json, {}).get("mode") != "EXTERNAL_ALLOWED":
            raise RuntimeError(f"AGENT_NOT_READY:{row.status}")
        symbols["initialize"](
            ledger, batch_id=BATCH_ID, pricing_checked_at=PRICING_CHECKED_AT,
        )
        budget = symbols["summary"](ledger)
        if budget["used_requests"] != 0 or budget["in_flight"] != 0:
            raise RuntimeError("SHARED_LEDGER_NOT_PRISTINE")
        report = {
            "status": "READY_FOR_ONE_REAL_AGENT_RUN",
            "external_calls": 0,
            "database": str(database.resolve()),
            "ledger": str(ledger.resolve()),
            "agent": symbols["get_agent_run"](
                db, run_id=row.run_id, project_id=PROJECT_ID, prompt_id=PROMPT_ID,
            ),
            "baseline": baseline,
            "shared_budget": budget,
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


def _execute(database: Path, ledger: Path, output: Path) -> dict[str, Any]:
    symbols = _imports(database)
    settings = symbols["get_settings"]()
    if not settings.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY_NOT_CONFIGURED")
    state = symbols["summary"](ledger)
    if state["used_requests"] != 0 or state["in_flight"] != 0:
        raise RuntimeError("SHARED_LEDGER_NOT_PRISTINE")
    db = symbols["ReleaseSessionLocal"]()
    try:
        row = db.query(symbols["AgentExperimentRun"]).filter_by(
            project_id=PROJECT_ID, prompt_id=PROMPT_ID,
            idempotency_key="real-comparison-p1-p1-r1-20261019",
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
    )
    elapsed = time.monotonic() - started
    db = symbols["ReleaseSessionLocal"]()
    try:
        agent = symbols["get_agent_run"](
            db, run_id=run_id, project_id=PROJECT_ID, prompt_id=PROMPT_ID,
        )
        baseline = _baseline(db, symbols)
        budget = symbols["summary"](ledger)
        if budget["by_lane"]["WORKFLOW_BASELINE"] != 0:
            raise RuntimeError("UNEXPECTED_WORKFLOW_MODEL_CALL")
        report = {
            "status": "FIRST_REAL_PAIR_FINISHED_AND_STOPPED",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 3),
            "agent": agent,
            "workflow_baseline": baseline,
            "shared_budget": budget,
            "stopped_before_second_scenario": True,
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
    args = parser.parse_args()
    result = (_preflight(args.database, args.ledger, args.output)
              if args.mode == "prepare" else _execute(args.database, args.ledger, args.output))
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
