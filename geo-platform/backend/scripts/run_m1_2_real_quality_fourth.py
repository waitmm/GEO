"""One-shot controller for the authorized M1.2 fourth real quality check.

The controller intentionally uses a fresh ledger and a copied acceptance
database. ``prepare`` performs no provider I/O. ``execute`` may admit at most
one RESPONSES_TEXT request for the exact frozen operation. Reports contain
identity, accounting and validation metadata only; generated text remains in
the protected database and response-audit directory supplied by the operator.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any


BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

PROJECT_ID = 1
PROMPT_ID = 1
ANALYSIS_ID = "62fb5e6e-055f-434e-99ba-fb8dccafb1f3"
CONTEXT_ID = "ctx-b24989e8-3359-4b78-8f9b-698619925a29"
RUN_IDS = [
    "10", "11", "12", "14", "15", "16", "17", "18", "19", "20", "21",
    "22", "23", "24", "25", "26", "27", "28", "31", "32", "33", "34",
]
INPUT_SCOPE_HASH = "d35c80424f6985da93b16a037542e88d3a12e5ad6988dafeb19dfc83cc688e5a"
EVIDENCE_PACK_HASH = "b8bdee0e6bcb8aa58f07a8463effd5c6956016fe09739a6d008ebb532e1ebbbc"
EVIDENCE_SET_ID = "4183afd013860c9c8632e01bbe91b296c75b0eb9aeae5aae1872208a973bd7fb"
OBSERVATION_ID = "581c39bb2e5bfca8273679d99ab9b09bf1b3ce6f3b5de5c6f9437f1c071c8546"
PROMPT_VERSION = "geo-evidence-pack-synthesis.v10"
EXECUTION_CONTRACT = "geo.evidence-pack.execution.v12"
VALIDATION_CONTRACT = "geo.evidence-pack.validation.v5"
TRANSPORT_KIND = "RESPONSES_TEXT"
MAX_REQUESTS = 1
MAX_TOTAL_TOKENS = 300_000
MAX_COST_CNY = 3.0
CONSERVATIVE_CNY_PER_MILLION = 10.0
PRICING_CHECKED_AT = "2026-11-11"
BATCH_ID = "m1-2-real-quality-fourth-20261111"
AUTHORIZED_BY = "explicit-user-fourth-real-quality-authorization-20261111"
RUN_KEY = "m1-2-dual-content-quality-fourth-20261111"


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _imports(database: Path) -> dict[str, Any]:
    os.environ["GEO_RELEASE_DATABASE_URL"] = f"sqlite:///{database.resolve()}"
    from app.core.config import get_settings
    from app.core.release_database import ReleaseSessionLocal
    from app.models import (
        AgentDraftArtifactVersion,
        AgentExperimentRun,
        AgentResultVersion,
        SinglePromptAnalysis,
        SinglePromptAnalysisContext,
    )
    from app.modules.agent_experiment.evidence_pack import (
        EVIDENCE_PACK_EXECUTION_CONTRACT,
        EVIDENCE_PACK_PROMPT_VERSION,
        EVIDENCE_PACK_RESULT_CONTRACT,
        EVIDENCE_PACK_TRANSPORT_VERSION,
        _aggregate_pack_integrity_issues,
        build_evidence_pack,
        render_evidence_pack_prompt,
    )
    from app.modules.agent_experiment.response_audit import SecureResponseAuditArchive
    from app.modules.agent_experiment.runner import execute_agent_run
    from app.modules.agent_experiment.service import authorize_agent_run, create_agent_run
    from app.services.internal_beta_model_budget import hooks_for_run
    from app.services.serialization import loads
    from app.services.shared_model_budget import (
        PRICING_SOURCE,
        append_transport_authorization,
        initialize,
        summary,
    )
    return locals()


def _projection(pack: dict[str, Any], render_prompt) -> dict[str, Any]:
    max_output_tokens = 16_384
    body = {
        "model": "deepseek-flash",
        "instructions": render_prompt(
            prompt_version=PROMPT_VERSION,
            requested_artifact_types=["HELP_DOC", "FAQ"],
        ),
        # Mirror DeepSeekClient.text_generate_sync exactly: the evidence-pack
        # object is serialized once into the Responses API ``input`` string.
        "input": json.dumps(pack, ensure_ascii=False),
        "temperature": 0.0,
        "max_output_tokens": max_output_tokens,
        "reasoning": {"effort": "none"},
    }
    request_bytes = len(json.dumps(body, ensure_ascii=False).encode("utf-8"))
    input_upper = request_bytes + 4_096
    reservation = input_upper + max_output_tokens
    return {
        "request_body_utf8_bytes": request_bytes,
        "input_token_upper_bound": input_upper,
        "max_output_tokens": max_output_tokens,
        "total_token_reservation": reservation,
        "conservative_cost_cny": round(
            reservation * CONSERVATIVE_CNY_PER_MILLION / 1_000_000, 8
        ),
    }


def _extension(state: dict[str, Any], run_id: str) -> dict[str, Any]:
    rows = [
        row for row in state.get("authorization_extensions", [])
        if row.get("operation_id") == run_id
    ]
    if len(rows) != 1:
        raise RuntimeError("FOURTH_AUTHORIZATION_EXTENSION_MISSING")
    return rows[0]


def _issue_codes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({
        str(row.get("code") or "UNKNOWN") for row in value if isinstance(row, dict)
    })


def _pack_checks(pack: dict[str, Any], symbols: dict[str, Any]) -> dict[str, Any]:
    if pack.get("evidence_pack_hash") != EVIDENCE_PACK_HASH:
        raise RuntimeError("FOURTH_EVIDENCE_PACK_HASH_MISMATCH")
    if [str(value) for value in pack.get("coverage", {}).get("run_ids", [])] != RUN_IDS:
        raise RuntimeError("FOURTH_EVIDENCE_PACK_RUN_SCOPE_MISMATCH")
    sets = pack.get("aggregate_evidence_sets") or []
    observations = pack.get("verified_brand_observations") or []
    if len(sets) != 1 or len(observations) != 1:
        raise RuntimeError("FOURTH_AGGREGATE_OBJECT_COUNT_MISMATCH")
    evidence_set, observation = sets[0], observations[0]
    if (
        evidence_set.get("evidence_set_id") != EVIDENCE_SET_ID
        or evidence_set.get("observation_status") != "SERVER_VERIFIED_ABSENCE"
        or len(evidence_set.get("members") or []) != 22
        or evidence_set.get("excluded_members")
        or evidence_set.get("unresolved_reasons")
        or evidence_set.get("matched_run_ids")
        or observation.get("observation_id") != OBSERVATION_ID
        or observation.get("verification") != "SERVER_VERIFIED"
        or int(observation.get("valid_run_count", 0)) != 22
        or int(observation.get("matched_count", -1)) != 0
    ):
        raise RuntimeError("FOURTH_AGGREGATE_OBSERVATION_MISMATCH")
    issues = symbols["_aggregate_pack_integrity_issues"](pack)
    if issues:
        raise RuntimeError("FOURTH_AGGREGATE_PACK_INTEGRITY_FAILED")
    return {
        "evidence_set_id": EVIDENCE_SET_ID,
        "observation_id": OBSERVATION_ID,
        "member_count": 22,
        "matched_count": 0,
        "unresolved_count": 0,
        "integrity_issue_count": 0,
    }


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    if not args.database.is_file():
        raise RuntimeError("FOURTH_DATABASE_NOT_FOUND")
    symbols = _imports(args.database)
    if (
        symbols["EVIDENCE_PACK_PROMPT_VERSION"] != PROMPT_VERSION
        or symbols["EVIDENCE_PACK_EXECUTION_CONTRACT"] != EXECUTION_CONTRACT
    ):
        raise RuntimeError("FOURTH_CURRENT_CONTRACT_MISMATCH")
    symbols["initialize"](
        args.ledger,
        batch_id=BATCH_ID,
        pricing_checked_at=PRICING_CHECKED_AT,
        pricing_source=symbols["PRICING_SOURCE"],
        total_request_limit=MAX_REQUESTS,
        total_token_limit=MAX_TOTAL_TOKENS,
        total_cost_limit_cny=MAX_COST_CNY,
        conservative_cny_per_million_tokens=CONSERVATIVE_CNY_PER_MILLION,
    )
    db = symbols["ReleaseSessionLocal"]()
    try:
        analysis = db.query(symbols["SinglePromptAnalysis"]).filter_by(
            analysis_id=ANALYSIS_ID, project_id=PROJECT_ID, prompt_id=PROMPT_ID,
            status="READY",
        ).one()
        context = db.query(symbols["SinglePromptAnalysisContext"]).filter_by(
            context_id=CONTEXT_ID, analysis_id=ANALYSIS_ID,
            project_id=PROJECT_ID, prompt_id=PROMPT_ID,
        ).one()
        row, created = symbols["create_agent_run"](
            db,
            project_id=PROJECT_ID,
            prompt_id=PROMPT_ID,
            analysis_id=ANALYSIS_ID,
            context_id=CONTEXT_ID,
            idempotency_key=RUN_KEY,
            requested_by=AUTHORIZED_BY,
            regenerate_nonce="m1-2-real-quality-fourth-20261111",
            execution_mode="EVIDENCE_PACK",
            requested_artifact_types=["HELP_DOC", "FAQ"],
            budget={
                "max_model_calls": 1,
                "max_tool_calls": 0,
                "max_total_tokens": MAX_TOTAL_TOKENS,
                "max_elapsed_seconds": 300,
                "max_repairs": 0,
                "max_cost_cny": MAX_COST_CNY,
            },
        )
        if not created:
            raise RuntimeError("FOURTH_RUN_ALREADY_EXISTS")
        if row.status != "QUEUED" or symbols["loads"](
            row.authorization_json, {}
        ).get("mode") != "CACHE_ONLY":
            raise RuntimeError("FOURTH_RUN_NOT_CACHE_ONLY_QUEUED")
        execution = symbols["loads"](row.agent_execution_json, {})
        if (
            execution.get("contract_version") != EXECUTION_CONTRACT
            or execution.get("model_profile", {}).get("prompt_version") != PROMPT_VERSION
            or execution.get("model_profile", {}).get("reasoning_effort") != "none"
            or execution.get("model_profile", {}).get("automatic_retries") != 0
            or execution.get("requested_artifact_types") != ["HELP_DOC", "FAQ"]
        ):
            raise RuntimeError("FOURTH_EXECUTION_PROFILE_MISMATCH")
        scope = symbols["loads"](row.input_scope_json, {})
        actual_run_ids = [
            str(value) for value in scope.get("run_scope", {}).get("run_ids", [])
        ]
        if actual_run_ids != RUN_IDS or row.input_scope_hash != INPUT_SCOPE_HASH:
            raise RuntimeError("FOURTH_FROZEN_SCOPE_MISMATCH")
        if int(scope.get("monitor_metrics", {}).get("valid_answer_count", 0)) != 22:
            raise RuntimeError("FOURTH_VALID_ANSWER_COUNT_MISMATCH")
        pack = symbols["build_evidence_pack"](
            scope, execution_contract=EXECUTION_CONTRACT
        )
        aggregate = _pack_checks(pack, symbols)
        projection = _projection(pack, symbols["render_evidence_pack_prompt"])
        if projection["total_token_reservation"] > MAX_TOTAL_TOKENS:
            raise RuntimeError("FOURTH_TOKEN_CAP_EXCEEDED")
        if projection["conservative_cost_cny"] > MAX_COST_CNY:
            raise RuntimeError("FOURTH_COST_CAP_EXCEEDED")
        authorization = symbols["append_transport_authorization"](
            args.ledger,
            authorization_id=f"{BATCH_ID}:{row.run_id}",
            batch_id=BATCH_ID,
            lane="AGENT_EXPERIMENT",
            operation_id=row.run_id,
            scope={
                "authorization_scope": "M1_2_REAL_QUALITY_FOURTH_20261111",
                "project_id": PROJECT_ID,
                "prompt_id": PROMPT_ID,
                "analysis_id": ANALYSIS_ID,
                "context_id": CONTEXT_ID,
                "run_ids": RUN_IDS,
                "input_scope_hash": INPUT_SCOPE_HASH,
                "evidence_pack_hash": EVIDENCE_PACK_HASH,
                "evidence_set_id": EVIDENCE_SET_ID,
                "observation_id": OBSERVATION_ID,
                "validation_contract": VALIDATION_CONTRACT,
                "requested_artifact_types": ["HELP_DOC", "FAQ"],
            },
            transport_kind=TRANSPORT_KIND,
            transport_version=symbols["EVIDENCE_PACK_TRANSPORT_VERSION"],
            prompt_version=PROMPT_VERSION,
            schema_version=symbols["EVIDENCE_PACK_RESULT_CONTRACT"],
            execution_contract=EXECUTION_CONTRACT,
            pricing_checked_at=PRICING_CHECKED_AT,
            max_requests=MAX_REQUESTS,
            max_tokens=MAX_TOTAL_TOKENS,
            max_cost_cny=MAX_COST_CNY,
            authorized_by=AUTHORIZED_BY,
        )
        row = symbols["authorize_agent_run"](
            db,
            run_id=row.run_id,
            project_id=PROJECT_ID,
            prompt_id=PROMPT_ID,
            revision=row.revision,
            max_requests=MAX_REQUESTS,
            max_total_tokens=MAX_TOTAL_TOKENS,
            max_cost_cny=MAX_COST_CNY,
            conservative_cny_per_million_tokens=CONSERVATIVE_CNY_PER_MILLION,
            pricing_source=symbols["PRICING_SOURCE"],
            pricing_checked_at=PRICING_CHECKED_AT,
            authorized_by=AUTHORIZED_BY,
        )
        archive = symbols["SecureResponseAuditArchive"](args.audit_dir, retention_days=7)
        archive.prepare()
        state = symbols["summary"](args.ledger)
        extension = _extension(state, row.run_id)
        if (
            state["used_requests"] != 0
            or state["in_flight"] != 0
            or extension["used_requests"] != 0
            or extension["remaining_requests"] != 1
            or extension["max_tokens"] != MAX_TOTAL_TOKENS
            or float(extension["max_cost_cny"]) != MAX_COST_CNY
        ):
            raise RuntimeError("FOURTH_AUTHORIZATION_NOT_FRESH")
        report = {
            "status": "READY_FOR_ONE_REAL_M1_2_FOURTH_REQUEST",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "external_calls": 0,
            "run_id": row.run_id,
            "analysis_id": analysis.analysis_id,
            "context_id": context.context_id,
            "run_ids": actual_run_ids,
            "input_scope_hash": row.input_scope_hash,
            "agent_execution_hash": row.agent_execution_hash,
            "evidence_pack_hash": EVIDENCE_PACK_HASH,
            "aggregate_observation": aggregate,
            "contracts": {
                "prompt": PROMPT_VERSION,
                "execution": EXECUTION_CONTRACT,
                "validation": VALIDATION_CONTRACT,
                "transport": TRANSPORT_KIND,
                "reasoning_effort": "none",
            },
            "request_projection": projection,
            "authorization": {
                "authorization_hash": authorization["authorization_hash"],
                "max_requests": 1,
                "max_tokens": MAX_TOTAL_TOKENS,
                "max_cost_cny": MAX_COST_CNY,
                "automatic_retries": 0,
                "max_repairs": 0,
            },
            "protected_storage": {
                "database": str(args.database.resolve()),
                "ledger": str(args.ledger.resolve()),
                "audit_dir": str(args.audit_dir.resolve()),
            },
        }
        _write_json(args.output, report)
        return report
    finally:
        db.close()


def execute(args: argparse.Namespace) -> dict[str, Any]:
    os.environ["GEO_AGENT_BETA_DAILY_MODEL_CALLS"] = "1"
    os.environ["GEO_AGENT_BETA_BUDGET_LEDGER_PATH"] = str(args.ledger.resolve())
    os.environ["GEO_AGENT_BETA_BUDGET_BATCH_ID"] = BATCH_ID
    symbols = _imports(args.database)
    if not symbols["get_settings"]().deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY_NOT_CONFIGURED")
    db = symbols["ReleaseSessionLocal"]()
    try:
        row = db.query(symbols["AgentExperimentRun"]).filter_by(
            project_id=PROJECT_ID, prompt_id=PROMPT_ID, idempotency_key=RUN_KEY
        ).one()
        if row.status != "QUEUED" or row.input_scope_hash != INPUT_SCOPE_HASH:
            raise RuntimeError(f"FOURTH_RUN_NOT_EXECUTABLE:{row.status}")
        run_id = row.run_id
        execution = symbols["loads"](row.agent_execution_json, {})
        scope = symbols["loads"](row.input_scope_json, {})
        pack = symbols["build_evidence_pack"](
            scope, execution_contract=execution.get("contract_version")
        )
        _pack_checks(pack, symbols)
        hooks = symbols["hooks_for_run"](row)
    finally:
        db.close()
    before = symbols["summary"](args.ledger)
    extension_before = _extension(before, run_id)
    if before["used_requests"] != 0 or extension_before["used_requests"] != 0:
        raise RuntimeError("FOURTH_REQUEST_ALREADY_CONSUMED")
    archive = symbols["SecureResponseAuditArchive"](args.audit_dir, retention_days=7)
    archive.prepare()
    started = time.monotonic()
    execution_error_type = None
    try:
        symbols["execute_agent_run"](
            run_id,
            session_factory=symbols["ReleaseSessionLocal"],
            shared_budget_hooks=hooks,
            response_audit_archive=archive,
        )
    except Exception as exc:  # provider payloads and exception text stay out of the report
        execution_error_type = exc.__class__.__name__
    elapsed = time.monotonic() - started
    after = symbols["summary"](args.ledger)
    extension_after = _extension(after, run_id)
    request_delta = int(after["used_requests"]) - int(before["used_requests"])
    if request_delta > 1 or extension_after["used_requests"] > 1:
        raise RuntimeError("FOURTH_EXTERNAL_REQUEST_LIMIT_BREACHED")
    db = symbols["ReleaseSessionLocal"]()
    try:
        row = db.query(symbols["AgentExperimentRun"]).filter_by(run_id=run_id).one()
        parent = db.query(symbols["AgentResultVersion"]).filter_by(
            agent_run_id=run_id
        ).order_by(symbols["AgentResultVersion"].version_number.desc()).first()
        artifacts = db.query(symbols["AgentDraftArtifactVersion"]).filter_by(
            agent_run_id=run_id
        ).order_by(symbols["AgentDraftArtifactVersion"].artifact_type).all()
        validation = symbols["loads"](parent.validation_report_json, {}) if parent else {}
        safe_artifacts = []
        for artifact in artifacts:
            qa = symbols["loads"](artifact.qa_json, {})
            artifact_validation = qa.get("artifact_validation") or {}
            safe_artifacts.append({
                "artifact_type": artifact.artifact_type,
                "artifact_version": artifact.artifact_version,
                "status": artifact.status,
                "failure_code": artifact.failure_code,
                "failure_issue_codes": _issue_codes(
                    artifact_validation.get("issues")
                ),
                "artifact_hash": artifact.artifact_hash,
                "evidence_hash": artifact.evidence_hash,
                "qa_hash": artifact.qa_hash,
                "body_characters": len(artifact.body_markdown or ""),
            })
        report = {
            "status": "REAL_M1_2_FOURTH_FINISHED_AND_EXTERNAL_CALLS_STOPPED",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 3),
            "execution_error_type": execution_error_type,
            "external_request_consumed": request_delta == 1,
            "run": {
                "run_id": row.run_id,
                "status": row.status,
                "blocker_code": row.blocker_code,
                "input_scope_hash": row.input_scope_hash,
                "agent_execution_hash": row.agent_execution_hash,
                "model_call_count": row.model_call_count,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "cost_cny": row.cost_cny,
            },
            "parent_result": ({
                "result_version": parent.result_version,
                "result_hash": parent.result_hash,
                "validation_status": validation.get("status"),
                "validation_contract": validation.get("contract_version"),
                "validation_issue_codes": _issue_codes(validation.get("issues")),
                "artifact_pass_count": validation.get("artifact_pass_count"),
                "artifact_total_count": validation.get("artifact_total_count"),
                "shared_issue_count": validation.get("shared_issue_count"),
            } if parent else None),
            "artifacts": safe_artifacts,
            "usage_delta": {
                "requests": request_delta,
                "tokens": int(after["used_tokens"]) - int(before["used_tokens"]),
                "cost_cny": round(
                    float(after["used_cost_cny"]) - float(before["used_cost_cny"]), 8
                ),
            },
            "authorization_after": {
                "used_requests": extension_after["used_requests"],
                "remaining_requests": extension_after["remaining_requests"],
                "used_tokens": extension_after["used_tokens"],
                "used_cost_cny": extension_after["used_cost_cny"],
                "in_flight": after["in_flight"],
            },
            "response_audit_file_count": len(list(archive.root.glob("agent-response-*.json"))),
            "external_calls_stopped": True,
        }
        _write_json(args.output, report)
        return report
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "execute"))
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args) if args.mode == "prepare" else execute(args)
    print(json.dumps({
        "status": report["status"],
        "run_id": report.get("run_id") or report.get("run", {}).get("run_id"),
        "external_calls": report.get(
            "external_calls", report.get("usage_delta", {}).get("requests", 0)
        ),
        "output": str(args.output),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
