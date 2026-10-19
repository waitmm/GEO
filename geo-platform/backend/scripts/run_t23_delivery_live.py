"""Sole guarded executor for the three authorized T23 real delivery scenarios.

The controller must have initialized the existing shared T09/T23 ledger.  This
entry point never initializes, resets or enlarges it.  It preflights all three
frozen tasks, authorizes each task immediately before execution, and wraps every
Answer/Citation/Draft/Text-QA provider send in the shared reserve/finish guard.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
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


def _assert_ledger(manifest: dict[str, Any], state: dict[str, Any], *, include_prepare: bool = False,
                   consumed_prepare_requests: int = 0) -> None:
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
        allocated_requests += max(0,
            sum(row.get("prepare_max_requests", 0) for row in allocations) - consumed_prepare_requests)
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


def _database_state(database: Path) -> dict[str, str]:
    """Bind a checkpoint to both the SQLite main file and durable WAL."""
    files = {"database_sha256": _sha256_file(database)}
    wal = Path(f"{database}-wal")
    files["wal_sha256"] = _sha256_file(wal) if wal.exists() else ""
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {**files, "database_state_hash": hashlib.sha256(encoded).hexdigest()}


def _checkpoint_dir(frozen_manifest_path: Path) -> Path:
    return frozen_manifest_path.parent / f".{frozen_manifest_path.name}.prepare-checkpoints"


def _initial_database_snapshot(directory: Path) -> Path:
    return directory / "initial-database.sqlite3"


def _write_initial_database_snapshot(database: Path, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = _initial_database_snapshot(directory)
    if target.exists():
        raise ValueError("initial database snapshot exists without its immutable checkpoint")
    try:
        with target.open("xb"):
            pass
    except FileExistsError:
        raise ValueError("initial database snapshot was created concurrently")
    source = get_release_sqlite_dbapi().connect(str(database.resolve()))
    destination = get_release_sqlite_dbapi().connect(str(target.resolve()))
    try:
        source.backup(destination)
    except Exception:
        destination.close()
        source.close()
        target.unlink(missing_ok=True)
        raise
    else:
        destination.close()
        source.close()
    with target.open("rb") as stream:
        os.fsync(stream.fileno())
    directory_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return target


def _table_rows(connection, table: str) -> list[tuple[Any, ...]]:
    escaped = table.replace('"', '""')
    return [tuple(row) for row in connection.execute(f'SELECT * FROM "{escaped}" ORDER BY rowid')]


def _validate_pre_send_database_recovery(database: Path, snapshot: Path,
                                         manifest: dict[str, Any]) -> dict[str, Any]:
    """Accept only the fixed Answer create/claim delta before any send."""
    adapter = get_release_sqlite_dbapi()
    current = adapter.connect(str(database.resolve()))
    baseline = adapter.connect(str(snapshot.resolve()))
    current.row_factory = adapter.Row
    baseline.row_factory = adapter.Row
    table = "single_prompt_diagnosis_executions"
    try:
        tables = [row[0] for row in baseline.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        current_tables = [row[0] for row in current.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        if current_tables != tables:
            raise ValueError("prepare recovery database schema drifted")
        for name in tables:
            if name != table and _table_rows(current, name) != _table_rows(baseline, name):
                raise ValueError(f"prepare recovery found unrelated database drift in {name}")
        budget_id = manifest["shared_budget"]["budget_id"]
        key = f"{budget_id}:E2E-01:prepare-answer"
        base_other = [tuple(row) for row in baseline.execute(
            f'SELECT * FROM "{table}" WHERE idempotency_key != ? ORDER BY rowid', (key,))]
        current_other = [tuple(row) for row in current.execute(
            f'SELECT * FROM "{table}" WHERE idempotency_key != ? ORDER BY rowid', (key,))]
        if current_other != base_other:
            raise ValueError("prepare recovery found unrelated diagnosis drift")
        row = current.execute(f'SELECT * FROM "{table}" WHERE idempotency_key=?', (key,)).fetchone()
        if not row:
            raise ValueError("prepare recovery database drift has no harness-owned Answer diagnosis")
        answer_case = next(item for item in manifest["scenarios"] if item["id"] == "E2E-01")
        config = loads(row["contract_config_json"], {})
        if (row["analysis_id"] != answer_case["analysis_id"]
                or row["project_id"] != answer_case["project_id"]
                or row["prompt_id"] != answer_case["prompt_id"]
                or row["status"] not in {"QUEUED", "RUNNING"}
                or int(row["attempt_count"] or 0) not in {0, 1}
                or int(row["external_llm_calls"] or 0) != 0
                or row["active_result_version"]
                or config.get("diagnosis_mode") != "ANSWER_ONLY"
                or config.get("citation_manifest_id") != answer_case["answer_prepare_input"]["citation_manifest_id"]
                or config.get("citation_manifest_hash") != answer_case["answer_prepare_input"]["citation_manifest_hash"]):
            raise ValueError("prepare recovery harness-owned Answer diagnosis drifted")
        return {"diagnosis_id": row["diagnosis_id"], "status": row["status"],
            "active_attempt_token": row["active_attempt_token"]}
    finally:
        current.close()
        baseline.close()


def _checkpoint_events(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    return [_read_json(path) for path in sorted(directory.glob("*.json"))]


def _append_checkpoint(directory: Path, stage: str, payload: dict[str, Any]) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    body = {"contract_version": "t23-prepare-checkpoint.v1", "stage": stage, **payload}
    prior = _checkpoint_events(directory)
    if prior and prior[-1] == body:
        return body
    encoded = json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path = directory / f"{len(prior):03d}-{stage}.json"
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ValueError("prepare checkpoint sequence is not append-only") from exc
    directory_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return body


def _ledger_requests(state: dict[str, Any], request_prefix: str) -> list[dict[str, Any]]:
    return [row for row in state.get("requests") or []
        if str(row.get("request_id") or "").startswith(request_prefix)]


def _checkpoint_payload(*, manifest_sha256: str, initial_database_sha256: str,
                        budget_id: str, database: Path, ledger: Path,
                        answer=None, answer_result=None, contribution=None) -> dict[str, Any]:
    return {
        "original_manifest_sha256": manifest_sha256,
        "initial_database_sha256": initial_database_sha256,
        "budget_id": budget_id,
        "answer_diagnosis_id": getattr(answer, "diagnosis_id", None),
        "answer_attempt_token": getattr(answer, "active_attempt_token", None),
        "answer_result_version": getattr(answer_result, "result_version", None),
        "answer_result_hash": getattr(answer_result, "output_hash", None),
        "contribution_id": getattr(contribution, "contribution_id", None),
        "contribution_plan_hash": getattr(contribution, "plan_hash", None),
        "ledger_requests": [{"request_id": row["request_id"], "status": row["status"]}
            for row in summary(ledger).get("requests") or []],
        **_database_state(database),
    }


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
    case = next(row for row in manifest["scenarios"] if row["id"] == "E2E-02")
    if case.get("low_match_evidence"):
        if _sha256_file(database) != manifest["source_database_sha256"]:
            raise ValueError("isolated database changed after T23 prepare freeze")
        before = summary(ledger)
        _assert_ledger(manifest, before)
        _write_frozen_manifest(frozen_manifest_path, manifest)
        report = {"status": "PASS", "phase": "prepare-freeze", "scenario_id": "E2E-02",
            "low_match_evidence": case["low_match_evidence"],
            "source_database_sha256": manifest["source_database_sha256"],
            "budget_before": before, "budget_after": before,
            "frozen_manifest": str(frozen_manifest_path.resolve()), "idempotent_replay": True}
        _write_evidence(report_path, report)
        return report

    manifest_sha = _sha256_file(manifest_path)
    checkpoint_dir = _checkpoint_dir(frozen_manifest_path)
    checkpoints = _checkpoint_events(checkpoint_dir)
    if checkpoints:
        first, latest = checkpoints[0], checkpoints[-1]
        if (first.get("original_manifest_sha256") != manifest_sha
                or first.get("initial_database_sha256") != manifest["source_database_sha256"]
                or first.get("budget_id") != manifest["shared_budget"]["budget_id"]):
            raise ValueError("prepare checkpoint does not belong to the frozen manifest/budget")
        initial_snapshot = _initial_database_snapshot(checkpoint_dir)
        if (not initial_snapshot.is_file()
                or _sha256_file(initial_snapshot) != first.get("initial_database_snapshot_sha256")):
            raise ValueError("immutable initial database snapshot is missing or drifted")
        if latest.get("database_state_hash") != _database_state(database)["database_state_hash"]:
            ledger_state = summary(ledger)
            relevant = [row for row in ledger_state.get("requests") or []
                if str(row.get("request_id") or "").startswith(("T23:E2E-01:prepare-answer:",
                    "T23:E2E-02:prepare:"))]
            if relevant:
                raise ValueError("isolated database changed after a counted prepare request")
            recovered = _validate_pre_send_database_recovery(
                database, initial_snapshot, manifest)
            payload = _checkpoint_payload(
                manifest_sha256=manifest_sha, initial_database_sha256=manifest["source_database_sha256"],
                budget_id=manifest["shared_budget"]["budget_id"], database=database, ledger=ledger)
            payload["recovered_answer"] = recovered
            payload["answer_diagnosis_id"] = recovered["diagnosis_id"]
            payload["answer_attempt_token"] = recovered["active_attempt_token"]
            _append_checkpoint(checkpoint_dir, "PRE_SEND_DATABASE_RECOVERED", payload)
    else:
        if _sha256_file(database) != manifest["source_database_sha256"]:
            raise ValueError("isolated database changed before E2E-02 prepare")
        snapshot = _write_initial_database_snapshot(database, checkpoint_dir)
        initial_payload = _checkpoint_payload(
            manifest_sha256=manifest_sha, initial_database_sha256=manifest["source_database_sha256"],
            budget_id=manifest["shared_budget"]["budget_id"], database=database, ledger=ledger)
        initial_payload["initial_database_snapshot_sha256"] = _sha256_file(snapshot)
        _append_checkpoint(checkpoint_dir, "INITIAL", initial_payload)
    before = summary(ledger)
    # A fresh prepare must leave room for all 9 requests.  A replay of an
    # already-frozen manifest is read/idempotency verification only, so it
    # must not demand the two already-consumed prepare reservations again.
    prepared_manifest = json.loads(json.dumps(manifest))
    consumed_prepare = len([row for row in before.get("requests") or []
        if str(row.get("request_id") or "").startswith(("T23:E2E-01:prepare-answer:",
            "T23:E2E-02:prepare:"))])
    _assert_ledger(prepared_manifest, before, include_prepare=True,
        consumed_prepare_requests=consumed_prepare)
    engine = create_engine(f"sqlite:///{database.resolve()}", module=get_release_sqlite_dbapi(),
        connect_args={"check_same_thread": False, "timeout": 30})
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    prepare_failure = None
    durable_failure_payload = None
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
            answer_prefix = f"T23:E2E-01:prepare-answer:{diagnosis.diagnosis_id}:"
            counted = _ledger_requests(summary(ledger), answer_prefix)
            if counted:
                raise ValueError("PREPARE_RESUME_BLOCKED_COUNTED_WITHOUT_ANSWER_RESULT")
            latest = _checkpoint_events(checkpoint_dir)[-1]
            if diagnosis.status == "RUNNING" and latest.get("answer_diagnosis_id") == diagnosis.diagnosis_id:
                token = str(latest.get("answer_attempt_token") or "")
                if not token or token != diagnosis.active_attempt_token:
                    raise ValueError("E2E-01 Answer prepare checkpoint token drifted")
            elif diagnosis.status == "QUEUED":
                token = claim_diagnosis(db, diagnosis.diagnosis_id)
            else:
                raise ValueError(f"E2E-01 Answer prepare is not safely resumable: {diagnosis.status}")
            if not token:
                raise ValueError("E2E-01 Answer prepare could not acquire its formal execution")
            db.refresh(diagnosis)
            _append_checkpoint(checkpoint_dir, "ANSWER_READY_TO_SEND", _checkpoint_payload(
                manifest_sha256=manifest_sha, initial_database_sha256=manifest["source_database_sha256"],
                budget_id=manifest["shared_budget"]["budget_id"], database=database, ledger=ledger,
                answer=diagnosis))
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
                db.rollback()
                _append_checkpoint(checkpoint_dir, "ANSWER_BLOCKED", _checkpoint_payload(
                    manifest_sha256=manifest_sha, initial_database_sha256=manifest["source_database_sha256"],
                    budget_id=manifest["shared_budget"]["budget_id"], database=database, ledger=ledger,
                    answer=diagnosis))
                raise
        if digest(loads(answer_result.output_json, {})) != answer_result.output_hash:
            raise ValueError("E2E-01 prepared Answer result hash drifted")
        _append_checkpoint(checkpoint_dir, "ANSWER_RESULT", _checkpoint_payload(
            manifest_sha256=manifest_sha, initial_database_sha256=manifest["source_database_sha256"],
            budget_id=manifest["shared_budget"]["budget_id"], database=database, ledger=ledger,
            answer=diagnosis, answer_result=answer_result))
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
            try:
                low = _extract_low_match(db, case, execution, existing)
            except Exception:
                _append_checkpoint(checkpoint_dir, "CONTRIBUTION_BLOCKED", _checkpoint_payload(
                    manifest_sha256=manifest_sha, initial_database_sha256=manifest["source_database_sha256"],
                    budget_id=manifest["shared_budget"]["budget_id"], database=database, ledger=ledger,
                    answer=diagnosis, answer_result=answer_result, contribution=execution))
                raise
        else:
            contribution_prefix = f"T23:E2E-02:prepare:{execution.contribution_id}:"
            if _ledger_requests(summary(ledger), contribution_prefix):
                raise ValueError("PREPARE_RESUME_BLOCKED_COUNTED_WITHOUT_CONTRIBUTION_RESULT")
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
            db.refresh(execution)
            _append_checkpoint(checkpoint_dir, "CONTRIBUTION_READY_TO_SEND", _checkpoint_payload(
                manifest_sha256=manifest_sha, initial_database_sha256=manifest["source_database_sha256"],
                budget_id=manifest["shared_budget"]["budget_id"], database=database, ledger=ledger,
                answer=diagnosis, answer_result=answer_result, contribution=execution))
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
                db.rollback()
                _append_checkpoint(checkpoint_dir, "CONTRIBUTION_BLOCKED", _checkpoint_payload(
                    manifest_sha256=manifest_sha, initial_database_sha256=manifest["source_database_sha256"],
                    budget_id=manifest["shared_budget"]["budget_id"], database=database, ledger=ledger,
                    answer=diagnosis, answer_result=answer_result, contribution=execution))
                raise
            db.expire_all()
            execution = db.query(SinglePromptCitationContributionExecution).filter_by(
                contribution_id=execution.contribution_id).one()
            result = db.query(SinglePromptCitationContributionResult).filter_by(
                contribution_id=execution.contribution_id, result_version=execution.active_result_version).one_or_none()
            if any(row.get("status") == "RESERVED" for row in
                    _ledger_requests(summary(ledger), contribution_prefix)):
                settle_unknown(RuntimeError("Contribution returned without settling provider delivery"))
            if not result:
                _append_checkpoint(checkpoint_dir, "CONTRIBUTION_BLOCKED", _checkpoint_payload(
                    manifest_sha256=manifest_sha, initial_database_sha256=manifest["source_database_sha256"],
                    budget_id=manifest["shared_budget"]["budget_id"], database=database, ledger=ledger,
                    answer=diagnosis, answer_result=answer_result, contribution=execution))
                raise ValueError(f"E2E-02 prepare did not persist a formal result: {execution.status}")
            try:
                low = _extract_low_match(db, case, execution, result)
            except Exception:
                _append_checkpoint(checkpoint_dir, "CONTRIBUTION_BLOCKED", _checkpoint_payload(
                    manifest_sha256=manifest_sha, initial_database_sha256=manifest["source_database_sha256"],
                    budget_id=manifest["shared_budget"]["budget_id"], database=database, ledger=ledger,
                    answer=diagnosis, answer_result=answer_result, contribution=execution))
                raise
        db.commit()
        _append_checkpoint(checkpoint_dir, "CONTRIBUTION_RESULT", _checkpoint_payload(
            manifest_sha256=manifest_sha, initial_database_sha256=manifest["source_database_sha256"],
            budget_id=manifest["shared_budget"]["budget_id"], database=database, ledger=ledger,
            answer=diagnosis, answer_result=answer_result, contribution=execution))
    except Exception as exc:
        prepare_failure = exc
        durable_failure_payload = _checkpoint_payload(
            manifest_sha256=manifest_sha, initial_database_sha256=manifest["source_database_sha256"],
            budget_id=manifest["shared_budget"]["budget_id"], database=database, ledger=ledger,
            answer=locals().get("diagnosis"), answer_result=locals().get("answer_result"),
            contribution=locals().get("execution"))
    finally:
        db.close()
        engine.dispose()
    if prepare_failure is not None:
        durable_failure_payload.update(_database_state(database))
        durable_failure_payload["ledger_requests"] = [
            {"request_id": row["request_id"], "status": row["status"]}
            for row in summary(ledger).get("requests") or []]
        durable_failure_payload["error_type"] = prepare_failure.__class__.__name__
        durable_failure_payload["error"] = str(prepare_failure)[:500]
        _append_checkpoint(checkpoint_dir, "PREPARE_BLOCKED_DURABLE", durable_failure_payload)
        raise prepare_failure
    # Force WAL content into the isolated database before freezing its new hash.
    connection = get_release_sqlite_dbapi().connect(str(database.resolve()))
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    final_checkpoint = _checkpoint_payload(
        manifest_sha256=manifest_sha, initial_database_sha256=manifest["source_database_sha256"],
        budget_id=manifest["shared_budget"]["budget_id"], database=database, ledger=ledger,
        answer=diagnosis, answer_result=answer_result, contribution=execution)
    final_checkpoint["low_match_evidence"] = low
    _append_checkpoint(checkpoint_dir, "READY_TO_FREEZE", final_checkpoint)
    frozen = _freeze_manifest_value(manifest, low, _sha256_file(database))
    _write_frozen_manifest(frozen_manifest_path, frozen)
    report = {"status": "PASS", "phase": "prepare-freeze", "scenario_id": "E2E-02",
        "low_match_evidence": low, "source_database_sha256": frozen["source_database_sha256"],
        "budget_before": before, "budget_after": summary(ledger),
        "frozen_manifest": str(frozen_manifest_path.resolve())}
    _write_evidence(report_path, report)
    return report


def _execute_planned_scenarios(db, Session, manifest: dict[str, Any], ledger: Path,
                               planned: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case, state in zip(manifest["scenarios"], planned, strict=True):
        settle_unknown = None
        try:
            row = db.query(SinglePromptOptimizationTask).filter_by(task_id=case["task_id"]).one()
            payload = _authorization(case, state, manifest["shared_budget"])
            authorize_task(db, row, **payload)
            request_guard, audit_sink, settle_unknown = _hooks(
                ledger, scenario_id=case["id"], task_id=row.task_id)
            with shared_live_budget_hooks(request_guard=request_guard, response_audit_sink=audit_sink):
                execute_task(row.task_id, session_factory=Session)
            db.expire_all()
            verified = _inspect_task(db, case, phase="verify")
            results.append({"scenario_id": case["id"], "status": "PASS", "evidence": verified})
        except Exception as exc:
            if settle_unknown is not None:
                settle_unknown(exc)
            db.rollback()
            results.append({"scenario_id": case["id"], "status": "BLOCKED",
                "error_type": exc.__class__.__name__, "error": str(exc)[:500]})
    return results


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
        results = _execute_planned_scenarios(db, Session, manifest, ledger, planned)
        blocked = [row for row in results if row["status"] != "PASS"]
        report = {"status": "BLOCKED" if blocked else "PASS",
            "contract_version": manifest["contract_version"],
            "database": str(database.resolve()), "manifest_sha256": _sha256_file(manifest_path),
            "scenarios": results, "budget_before": before_budget, "budget_after": summary(ledger),
            "external_requests_by_harness": 0}
        exit_code = 2 if blocked else 0
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
