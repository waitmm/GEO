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
from app.core.config import get_settings  # noqa: E402
from app.models import (SinglePromptCitationContributionExecution,
    SinglePromptCitationContributionResult, SinglePromptDiagnosisResult,
    SinglePromptOptimizationTask, ReferenceSource)  # noqa: E402
from app.services.semantic_llm.base import SemanticLLMError  # noqa: E402
from app.services.semantic_llm.deepseek import (  # noqa: E402
    DEEPSEEK_JSON_SCHEMA_TRANSPORT_VERSION, DeepSeekClient, derive_deepseek_call_contract,
)
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
from app.modules.single_prompt_v2.citation_contribution import (  # noqa: E402
    CITATION_CONTRIBUTION_PROMPT_VERSION, CITATION_CONTRIBUTION_SCHEMA_VERSION,
    CitationContributionJudge, CitationContributionResponse, authorize_citation_contribution,
    build_citation_contribution_system_prompt, create_citation_contribution_plan,
    execute_citation_contribution,
)
from app.modules.single_prompt_v2.delivery_text import digest  # noqa: E402
from app.modules.single_prompt_v2.diagnosis import (  # noqa: E402
    claim_diagnosis, compute_answer_diagnosis, create_answer_diagnosis,
)
from app.modules.single_prompt_v2.llm_safety import V2AnswerSemanticJudge  # noqa: E402
from app.services.serialization import loads  # noqa: E402
from app.services.url_identity import build_url_identity  # noqa: E402


def _assert_ledger(manifest: dict[str, Any], state: dict[str, Any], *, include_prepare: bool = False) -> None:
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
    allocated_requests = sum(row.get("execute_max_requests", row["max_requests"]) for row in allocations)
    if include_prepare:
        allocated_requests += sum(row.get("prepare_max_requests", 0) for row in allocations)
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


def _extract_low_match(db, case: dict[str, Any], execution, result) -> dict[str, Any]:
    output = loads(result.output_json, {})
    if digest(output) != result.output_hash or execution.selected_run_id != case["prepare_input"]["selected_run_id"]:
        raise ValueError("E2E-02 prepared Contribution result identity/hash drifted")
    citations = {row.get("citation_id"): row for row in output.get("citations") or []
        if row.get("processing_status") == "DONE"
        and row.get("disposition") == "NO_BINDING_FOUND_AFTER_SEARCH"
        and row.get("run_id") == execution.selected_run_id}
    candidates = sorted((row for row in output.get("evaluations") or []
        if row.get("processing_status") == "DONE"
        and row.get("evidence_relation") in {"NO_MATCH", "INSUFFICIENT_EVIDENCE"}
        and row.get("citation_id") in citations), key=lambda row: (str(row.get("citation_id")), str(row.get("evaluation_id"))))
    if not candidates:
        raise ValueError("E2E-02 prepare produced no formal low-match result")
    evaluation = candidates[0]
    citation = citations[evaluation["citation_id"]]
    shared = {key: citation.get(key) for key in ("reference_id", "source_key")}
    if any(evaluation.get(key) != value for key, value in shared.items()):
        raise ValueError("E2E-02 prepare citation/evaluation identity mismatch")
    reference = db.query(ReferenceSource).filter_by(
        id=citation["reference_id"], run_id=execution.selected_run_id).one_or_none()
    if (not reference or not reference.canonical_url or not reference.canonical_url_hash
            or build_url_identity(reference.canonical_url).canonical_url_hash != reference.canonical_url_hash):
        raise ValueError("E2E-02 prepare lacks a hash-valid real citation URL")
    return {"contribution_id": execution.contribution_id, "result_version": result.result_version,
        "result_hash": result.output_hash, "selected_run_id": execution.selected_run_id,
        "citation_id": citation["citation_id"], "reference_id": citation["reference_id"],
        "source_key": citation["source_key"], "canonical_url_hash": reference.canonical_url_hash,
        "citation_disposition": citation["disposition"], "evaluation_id": evaluation["evaluation_id"],
        "evaluation_hash": digest(evaluation), "evidence_relation": evaluation["evidence_relation"]}


def _write_frozen_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise ValueError("frozen manifest path already contains different evidence")
        return
    with path.open("x", encoding="utf-8") as stream:
        stream.write(encoded)


def _freeze_manifest_value(manifest: dict[str, Any], low: dict[str, Any], database_hash: str) -> dict[str, Any]:
    frozen = json.loads(json.dumps(manifest))
    case = next(row for row in frozen["scenarios"] if row["id"] == "E2E-02")
    if case.get("low_match_evidence") not in (None, low):
        raise ValueError("E2E-02 repeated prepare produced different immutable low-match evidence")
    case["low_match_evidence"] = low
    frozen["source_database_sha256"] = database_hash
    return validate_manifest(frozen)


def prepare_and_freeze(*, database: Path, ledger: Path, manifest_path: Path,
                       frozen_manifest_path: Path, report_path: Path) -> dict[str, Any]:
    manifest = validate_manifest(_read_json(manifest_path), allow_unprepared_e2e02=True)
    if _sha256_file(database) != manifest["source_database_sha256"]:
        raise ValueError("isolated database changed before E2E-02 prepare")
    case = next(row for row in manifest["scenarios"] if row["id"] == "E2E-02")
    before = summary(ledger)
    # A fresh prepare must leave room for all 9 requests.  A replay of an
    # already-frozen manifest is read/idempotency verification only, so it
    # must not demand the two already-consumed prepare reservations again.
    prepared_manifest = json.loads(json.dumps(manifest))
    _assert_ledger(prepared_manifest, before, include_prepare=not bool(case.get("low_match_evidence")))
    engine = create_engine(f"sqlite:///{database.resolve()}", module=get_release_sqlite_dbapi(),
        connect_args={"check_same_thread": False, "timeout": 30})
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    try:
        answer_case = next(row for row in manifest["scenarios"] if row["id"] == "E2E-01")
        answer_prepare = answer_case["answer_prepare_input"]
        diagnosis, _answer_created = create_answer_diagnosis(db,
            analysis_id=answer_case["analysis_id"], project_id=answer_case["project_id"],
            prompt_id=answer_case["prompt_id"],
            citation_manifest_id=answer_prepare["citation_manifest_id"],
            citation_manifest_hash=answer_prepare["citation_manifest_hash"],
            answer_llm_policy="ALLOW_EXTERNAL",
            idempotency_key=f"{manifest['shared_budget']['budget_id']}:E2E-01:prepare-answer")
        answer_result = db.query(SinglePromptDiagnosisResult).filter_by(
            diagnosis_id=diagnosis.diagnosis_id, result_version=diagnosis.active_result_version).one_or_none()
        if not answer_result:
            if diagnosis.status != "QUEUED":
                raise ValueError(f"E2E-01 Answer prepare is not safely resumable: {diagnosis.status}")
            token = claim_diagnosis(db, diagnosis.diagnosis_id)
            if not token:
                raise ValueError("E2E-01 Answer prepare could not acquire its formal execution")
            request_guard, audit_sink, settle_unknown = _hooks(
                ledger, scenario_id="E2E-01", task_id=f"prepare-answer:{diagnosis.diagnosis_id}")
            config = loads(diagnosis.contract_config_json, {})
            client = DeepSeekClient(thinking_mode="disabled", max_attempts=1,
                request_guard=request_guard, response_audit_sink=audit_sink,
                frozen_call_contracts=config.get("derived_model_call_contracts"))
            try:
                answer_result = compute_answer_diagnosis(db, diagnosis, token,
                    answer_judge=V2AnswerSemanticJudge(client))
            except Exception as exc:
                settle_unknown(exc)
                raise
        if digest(loads(answer_result.output_json, {})) != answer_result.output_hash:
            raise ValueError("E2E-01 prepared Answer result hash drifted")
        prepare = case["prepare_input"]
        prepare["answer_result_version"] = answer_result.result_version
        prepare["answer_result_hash"] = answer_result.output_hash
        execution, _created = create_citation_contribution_plan(db,
            analysis_id=case["analysis_id"], project_id=case["project_id"], prompt_id=case["prompt_id"],
            answer_result_version=prepare["answer_result_version"], answer_result_hash=prepare["answer_result_hash"],
            answer_review_id=None, citation_manifest_id=prepare["citation_manifest_id"],
            citation_manifest_hash=prepare["citation_manifest_hash"],
            completion_manifest_id=prepare["completion_manifest_id"], completion_manifest_hash=prepare["completion_manifest_hash"],
            fixed_run_ids=case["run_ids"], selected_run_id=prepare["selected_run_id"],
            input_authority="MACHINE_ADMISSION",
            idempotency_key=f"{manifest['shared_budget']['budget_id']}:E2E-02:prepare-low-match")
        plan = loads(execution.plan_json, {})
        planned_requests = int((plan.get("call_plan") or {}).get("max_new_external_requests") or 0)
        if planned_requests != case["prepare_max_requests"]:
            raise ValueError("E2E-02 formal Contribution plan does not fit prepare_max_requests")
        if int(plan["call_plan"]["conservative_token_ceiling"]) > int(case["max_tokens"]):
            raise ValueError("E2E-02 formal Contribution plan exceeds the frozen token allocation")
        existing = db.query(SinglePromptCitationContributionResult).filter_by(
            contribution_id=execution.contribution_id, result_version=execution.active_result_version).one_or_none()
        if existing:
            low = _extract_low_match(db, case, execution, existing)
        else:
            if execution.status == "AWAITING_EXTERNAL_AUTHORIZATION":
                call_plan = plan["call_plan"]
                authorize_citation_contribution(db, contribution_id=execution.contribution_id,
                    project_id=case["project_id"], prompt_id=case["prompt_id"], plan_hash=execution.plan_hash,
                    provider="deepseek", model=call_plan["requested_model_alias"],
                    max_external_requests=planned_requests, max_total_tokens=int(case["max_tokens"]),
                    max_budget_cny=float(case["max_cost_cny"]),
                    cost_upper_bound_cny=float(call_plan["budget_upper_bound_cny"]),
                    pricing_basis=str(call_plan["pricing_basis"]), authorized_by=manifest["shared_budget"]["authorized_by"])
            elif execution.status != "QUEUED":
                raise ValueError(f"E2E-02 prepare is not safely resumable: {execution.status}")
            request_guard, audit_sink, settle_unknown = _hooks(
                ledger, scenario_id="E2E-02", task_id=f"prepare:{execution.contribution_id}")
            settings = get_settings()
            contract = derive_deepseek_call_contract(system_prompt=build_citation_contribution_system_prompt(),
                response_schema=CitationContributionResponse, prompt_version=CITATION_CONTRIBUTION_PROMPT_VERSION,
                schema_version=CITATION_CONTRIBUTION_SCHEMA_VERSION, requested_model_alias=settings.deepseek_model,
                thinking_mode="disabled", max_tokens=4096, structured_output_mode="JSON_SCHEMA",
                transport_version=DEEPSEEK_JSON_SCHEMA_TRANSPORT_VERSION,
                endpoint_base_url=settings.deepseek_base_url)
            judge = CitationContributionJudge(DeepSeekClient(thinking_mode="disabled", max_attempts=1,
                request_guard=request_guard, response_audit_sink=audit_sink,
                frozen_call_contracts={CITATION_CONTRIBUTION_PROMPT_VERSION: contract}))
            try:
                execute_citation_contribution(execution.contribution_id, session_factory=Session, judge=judge)
            except Exception as exc:
                settle_unknown(exc)
                raise
            db.expire_all()
            execution = db.query(SinglePromptCitationContributionExecution).filter_by(
                contribution_id=execution.contribution_id).one()
            result = db.query(SinglePromptCitationContributionResult).filter_by(
                contribution_id=execution.contribution_id, result_version=execution.active_result_version).one_or_none()
            if not result:
                raise ValueError(f"E2E-02 prepare did not persist a formal result: {execution.status}")
            low = _extract_low_match(db, case, execution, result)
        db.commit()
    finally:
        db.close()
        engine.dispose()
    # Force WAL content into the isolated database before freezing its new hash.
    connection = get_release_sqlite_dbapi().connect(str(database.resolve()))
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    frozen = _freeze_manifest_value(manifest, low, _sha256_file(database))
    _write_frozen_manifest(frozen_manifest_path, frozen)
    report = {"status": "PASS", "phase": "prepare-freeze", "scenario_id": "E2E-02",
        "low_match_evidence": low, "source_database_sha256": frozen["source_database_sha256"],
        "budget_before": before, "budget_after": summary(ledger),
        "frozen_manifest": str(frozen_manifest_path.resolve())}
    _write_evidence(report_path, report)
    return report


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
    parser.add_argument("phase", nargs="?", choices=("execute", "prepare-freeze"), default="execute")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--frozen-manifest", type=Path)
    parser.add_argument("--confirm-isolated-database", action="store_true")
    args = parser.parse_args()
    if not args.confirm_isolated_database:
        raise SystemExit("REFUSED: --confirm-isolated-database is required")
    if not args.database.is_file():
        raise SystemExit("REFUSED: isolated database does not exist")
    if args.phase == "prepare-freeze":
        if args.frozen_manifest is None:
            raise SystemExit("REFUSED: --frozen-manifest is required for prepare-freeze")
        report = prepare_and_freeze(database=args.database, ledger=args.ledger,
            manifest_path=args.manifest, frozen_manifest_path=args.frozen_manifest,
            report_path=args.report)
        report = {**report, "exit_code": 0}
    else:
        report = execute(database=args.database, ledger=args.ledger,
            manifest_path=args.manifest, report_path=args.report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
