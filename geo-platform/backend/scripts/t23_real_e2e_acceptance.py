"""Read-only T23 real-E2E preflight and post-execution evidence gate.

This script never creates/authorizes/runs an Optimize task and never contacts a
provider.  The controller supplies an immutable scenario manifest and its shared
budget allocation.  ``plan`` emits the exact payloads which may subsequently be
passed to the existing ``authorize_task`` entry point; ``verify`` accepts only
persisted real inputs and completed delivery/QA results.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models import (  # noqa: E402
    BrowserMonitorRun,
    ReferenceSource,
    SinglePromptAnalysisContext,
    SinglePromptCitationContributionExecution,
    SinglePromptCitationContributionResult,
    SinglePromptDiagnosisExecution,
    SinglePromptDiagnosisResult,
    SinglePromptDiagnosisReview,
    SinglePromptExecutionProposal,
    SinglePromptExecutionProposalResult,
    SinglePromptOptimizationTask,
    SinglePromptPreparedSourceSnapshot,
    SinglePromptSourceCompletionManifest,
    SinglePromptStrategyExecution,
    SinglePromptStrategyReview,
    TargetBrandCapabilityTruth,
)
from app.modules.single_prompt_v2.automatic_delivery import task_view  # noqa: E402
from app.modules.single_prompt_v2.delivery_text import digest, text_digest  # noqa: E402
from app.services.serialization import loads  # noqa: E402


CONTRACT = "t23-real-e2e-acceptance.v1"
SCENARIOS = ("E2E-01", "E2E-02", "E2E-03")
TERMINAL_SUCCESS = {"COMPLETED", "COMPLETED_WITH_LIMITATIONS"}


def _sha256_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _readonly_session(database: Path) -> tuple[Session, Any]:
    resolved = database.resolve()
    engine = create_engine(
        "sqlite://",
        creator=lambda: sqlite3.connect(f"file:{resolved}?mode=ro", uri=True, check_same_thread=False),
    )
    return sessionmaker(bind=engine, expire_on_commit=False)(), engine


def _bounded_date(value: str) -> str:
    checked = date.fromisoformat(value)
    age = (datetime.now(timezone.utc).date() - checked).days
    if not 0 <= age <= 7:
        raise ValueError("pricing_checked_at must be within the preceding seven days")
    return value


def validate_manifest(value: dict[str, Any], *, allow_unprepared_e2e02: bool = False,
                      allow_unprepared_e2e03: bool = False) -> dict[str, Any]:
    if value.get("contract_version") != CONTRACT:
        raise ValueError("unsupported T23 manifest contract")
    source_hash = value.get("source_database_sha256")
    if not isinstance(source_hash, str) or len(source_hash) != 64 or any(c not in "0123456789abcdef" for c in source_hash):
        raise ValueError("source_database_sha256 must freeze the isolated input database")
    budget = value.get("shared_budget")
    if not isinstance(budget, dict) or not str(budget.get("budget_id") or "").strip():
        raise ValueError("shared_budget with a durable budget_id is required")
    if budget.get("max_requests") != 9 or not 0 < float(budget.get("max_cost_cny") or 0) <= 40:
        raise ValueError("T23 shared allocation must be exactly 9 requests and at most CNY 40")
    if float(budget.get("conservative_cny_per_million_tokens") or 0) != 10:
        raise ValueError("T23 conservative price must be the controller-frozen CNY 10/M tokens")
    if not str(budget.get("pricing_source") or "").strip():
        raise ValueError("pricing_source is required")
    _bounded_date(str(budget.get("pricing_checked_at") or ""))
    if not str(budget.get("authorized_by") or "").strip():
        raise ValueError("authorized_by is required")
    if budget.get("max_attempts") != 1 or budget.get("automatic_retry") != 0:
        raise ValueError("T23 allows one provider attempt and no automatic retry")

    cases = value.get("scenarios")
    if not isinstance(cases, list) or [row.get("id") for row in cases] != list(SCENARIOS):
        raise ValueError("scenarios must contain E2E-01, E2E-02 and E2E-03 exactly once, in order")
    required = {"id", "task_id", "project_id", "prompt_id", "analysis_id", "context_id",
                "input_hash", "run_ids", "max_requests", "max_tokens", "max_cost_cny"}
    for row in cases:
        if not isinstance(row, dict) or not required.issubset(row):
            raise ValueError(f"incomplete scenario identity: {row!r}")
        if (not isinstance(row["task_id"], str) or not row["task_id"]
                or not isinstance(row["input_hash"], str) or len(row["input_hash"]) != 64
                or any(c not in "0123456789abcdef" for c in row["input_hash"])):
            raise ValueError(f"invalid task/input identity for {row['id']}")
        if not isinstance(row["run_ids"], list) or not row["run_ids"]:
            raise ValueError(f"{row['id']} must freeze at least one real Run")
        if not 0 < row["max_requests"] <= 9 or not 0 < row["max_tokens"] <= 10_000_000:
            raise ValueError(f"invalid bounded allocation for {row['id']}")
        if not 0 < float(row["max_cost_cny"]) <= 40:
            raise ValueError(f"invalid cost allocation for {row['id']}")
        if row["id"] == "E2E-01":
            if (row.get("prepare_max_requests") != 1 or row.get("execute_max_requests") != 3
                    or row["prepare_max_requests"] + row["execute_max_requests"] != row["max_requests"]):
                raise ValueError("E2E-01 must freeze the 1 Answer prepare + 3 execute request allocation")
            answer_prepare = row.get("answer_prepare_input")
            if (not isinstance(answer_prepare, dict)
                    or set(answer_prepare) != {"citation_manifest_id", "citation_manifest_hash", "selected_run_id"}
                    or answer_prepare["selected_run_id"] not in row["run_ids"]
                    or not isinstance(answer_prepare["citation_manifest_hash"], str)
                    or len(answer_prepare["citation_manifest_hash"]) != 64):
                raise ValueError("E2E-01 must freeze exact formal Answer prepare inputs")
        if row["id"] == "E2E-02":
            if (row.get("prepare_max_requests") != 1 or row.get("execute_max_requests") != 2
                    or row["prepare_max_requests"] + row["execute_max_requests"] != row["max_requests"]):
                raise ValueError("E2E-02 must freeze the 1 prepare + 2 execute request allocation")
            prepare = row.get("prepare_input")
            prepare_required = {"answer_result_version", "answer_result_hash", "citation_manifest_id",
                "citation_manifest_hash", "completion_manifest_id", "completion_manifest_hash",
                "selected_run_id"}
            if not isinstance(prepare, dict) or set(prepare) != prepare_required:
                if not allow_unprepared_e2e02 or not isinstance(prepare, dict) or set(prepare) != (
                        prepare_required - {"answer_result_version", "answer_result_hash"}):
                    raise ValueError("E2E-02 must freeze exact formal Contribution prepare inputs")
            if prepare["selected_run_id"] not in row["run_ids"]:
                raise ValueError("E2E-02 prepare Run is outside the frozen scenario scope")
            for key in ("answer_result_hash", "citation_manifest_hash", "completion_manifest_hash"):
                if allow_unprepared_e2e02 and key == "answer_result_hash" and key not in prepare:
                    continue
                if not isinstance(prepare[key], str) or len(prepare[key]) != 64:
                    raise ValueError(f"E2E-02 prepare {key} must be sha256")
            low = row.get("low_match_evidence")
            low_required = {"contribution_id", "result_version", "result_hash", "selected_run_id",
                "citation_id", "reference_id", "source_key", "canonical_url_hash",
                "citation_disposition", "evaluation_id", "evaluation_hash", "evidence_relation"}
            if allow_unprepared_e2e02 and low is None:
                continue
            if not isinstance(low, dict) or set(low) != low_required:
                raise ValueError("E2E-02 must freeze one exact real low-match citation diagnosis")
            if (low["selected_run_id"] not in row["run_ids"]
                    or low["citation_disposition"] != "NO_BINDING_FOUND_AFTER_SEARCH"
                    or low["evidence_relation"] not in {"NO_MATCH", "INSUFFICIENT_EVIDENCE"}):
                raise ValueError("E2E-02 frozen evidence is not a formal low-match disposition")
            for key in ("result_hash", "canonical_url_hash", "evaluation_hash"):
                if not isinstance(low[key], str) or len(low[key]) != 64:
                    raise ValueError(f"E2E-02 {key} must be a frozen sha256 identity")
        if row["id"] == "E2E-03":
            pending = row.get("task_pending_truth") is True
            if pending and not allow_unprepared_e2e03:
                raise ValueError("E2E-03 cannot be planned before its formal UNKNOWN truth is frozen")
            if pending:
                unknown = row.get("unknown_prepare_input")
                if (not isinstance(unknown, dict)
                        or set(unknown) != {"signal_selector", "source_reference", "note", "reviewed_by"}
                        or unknown.get("signal_selector") != "UNIQUE_TARGET_BRAND_CAPABILITY"
                        or not all(str(unknown.get(key) or "").strip()
                                   for key in ("source_reference", "note", "reviewed_by"))):
                    raise ValueError("E2E-03 pending task requires a bounded formal UNKNOWN prepare input")
            else:
                evidence = row.get("unknown_truth_evidence")
                required_evidence = {"truth_id", "project_id", "capability_label",
                    "product_truth_status", "source_diagnosis_id", "source_result_version",
                    "source_result_hash", "source_signal_id", "source_prompt_id",
                    "source_analysis_id", "target_prompt_id", "target_analysis_id"}
                if (not isinstance(evidence, dict) or set(evidence) != required_evidence
                        or evidence["product_truth_status"] != "UNKNOWN"
                        or evidence["project_id"] != row["project_id"]
                        or evidence["target_prompt_id"] != row["prompt_id"]
                        or evidence["target_analysis_id"] != row["analysis_id"]
                        or not isinstance(evidence["source_result_hash"], str)
                        or len(evidence["source_result_hash"]) != 64):
                    raise ValueError("E2E-03 must freeze exact project-level UNKNOWN truth provenance")
    if sum(row["max_requests"] for row in cases) > budget["max_requests"]:
        raise ValueError("scenario request caps exceed the shared T23 allocation")
    if [row["max_requests"] for row in cases] != [4, 3, 2]:
        raise ValueError("T23 request plan must preserve the frozen 4+3+2 staged allocation")
    if (cases[0]["analysis_id"] != cases[1]["analysis_id"]
            or cases[0]["context_id"] != cases[1]["context_id"]
            or cases[0]["project_id"] != cases[1]["project_id"]
            or cases[0]["prompt_id"] != cases[1]["prompt_id"]
            or cases[0]["run_ids"] != cases[1]["run_ids"]):
        raise ValueError("E2E-01 Answer prepare and E2E-02 Contribution must share one frozen Analysis/Run scope")
    if len(cases[0]["run_ids"]) != 1:
        raise ValueError("E2E-01/E2E-02 staged prepare requires one exact frozen Run")
    if sum(float(row["max_cost_cny"]) for row in cases) > float(budget["max_cost_cny"]):
        raise ValueError("scenario cost caps exceed the shared T23 allocation")
    return value


def _real_runs(db: Session, inputs: dict[str, Any], expected_run_ids: list[int]) -> list[dict[str, Any]]:
    run_ids = inputs.get("run_ids")
    if run_ids != expected_run_ids or len(set(run_ids or [])) != len(run_ids or []):
        raise ValueError("task Run scope does not match the frozen scenario manifest")
    rows = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.id.in_(run_ids)).order_by(BrowserMonitorRun.id).all()
    if [row.id for row in rows] != sorted(run_ids):
        raise ValueError("one or more frozen Runs are missing")
    result = []
    for row in rows:
        if (row.project_id != inputs["brand"]["project_id"] or row.status != "success"
                or row.platform != "wenxin" or row.source_type != "browser_audit"
                or row.adapter != "wenxin_web_audit" or not row.answer_text.strip()
                or not row.attempt_id or not row.logical_run_id):
            raise ValueError(f"Run {row.id} is not an attributable real Wenxin browser sample")
        if any(marker in " ".join((row.collector_id, row.profile_identifier)).lower()
               for marker in ("fixture", "mock", "simulated", "test-double")):
            raise ValueError(f"Run {row.id} carries a non-real collector marker")
        refs = db.query(ReferenceSource).filter_by(run_id=row.id).count()
        result.append({"run_id": row.id, "attempt_id": row.attempt_id,
            "logical_run_id": row.logical_run_id, "attempt_no": row.attempt_no,
            "answer_sha256": text_digest(row.answer_text), "answer_chars": len(row.answer_text),
            "reference_count": refs, "platform": row.platform, "adapter": row.adapter})
    return result


def _source_summary(db: Session, inputs: dict[str, Any]) -> dict[str, Any] | None:
    source = inputs.get("source_input")
    if not source:
        return None
    completion = db.query(SinglePromptSourceCompletionManifest).filter_by(
        manifest_id=source.get("completion_manifest_id")).one_or_none()
    if (not completion or completion.payload_hash != source.get("completion_manifest_hash")
            or completion.analysis_id != inputs["analysis_id"] or completion.context_id != inputs["context_id"]
            or digest(loads(completion.payload_json, {})) != completion.payload_hash):
        raise ValueError("completion manifest identity/hash/scope mismatch")
    payload = loads(completion.payload_json, {})
    ready_rows = [item for item in payload.get("sources") or [] if item.get("disposition") == "READY"]
    valid = []
    for frozen in ready_rows:
        snapshot = db.query(SinglePromptPreparedSourceSnapshot).filter_by(
            preparation_id=completion.preparation_id, snapshot_id=frozen.get("snapshot_id"),
            source_key=frozen.get("source_key")).one_or_none()
        if (not snapshot or snapshot.content_hash != frozen.get("content_hash")
                or snapshot.passages_hash != frozen.get("passages_hash")):
            raise ValueError("completion manifest READY snapshot identity/hash mismatch")
        if (not snapshot.clean_text.strip() or text_digest(snapshot.clean_text) != snapshot.content_hash
                or digest(loads(snapshot.passages_json, [])) != snapshot.passages_hash):
            raise ValueError(f"prepared source snapshot is invalid: {snapshot.snapshot_id}")
        valid.append({"snapshot_id": snapshot.snapshot_id, "url": snapshot.canonical_url,
            "content_hash": snapshot.content_hash, "passages_hash": snapshot.passages_hash,
            "acquisition_method": snapshot.acquisition_method})
    if len(valid) != completion.ready_source_count or len(ready_rows) != completion.ready_source_count:
        raise ValueError("completion ready count does not match valid immutable snapshots")
    return {"manifest_id": completion.manifest_id, "manifest_hash": completion.payload_hash,
        "status": completion.status, "required": completion.required_source_count,
        "ready": completion.ready_source_count, "waived": completion.waived_source_count,
        "snapshots": valid}


def _low_match_summary(db: Session, case: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    frozen = case["low_match_evidence"]
    execution = db.query(SinglePromptCitationContributionExecution).filter_by(
        contribution_id=frozen["contribution_id"]).one_or_none()
    result = db.query(SinglePromptCitationContributionResult).filter_by(
        contribution_id=frozen["contribution_id"], result_version=frozen["result_version"]).one_or_none()
    if (not execution or not result or result.output_hash != frozen["result_hash"]
            or digest(loads(result.output_json, {})) != result.output_hash
            or execution.analysis_id != case["analysis_id"] or execution.context_id != case["context_id"]
            or execution.project_id != case["project_id"] or execution.prompt_id != case["prompt_id"]
            or execution.selected_run_id != frozen["selected_run_id"]):
        raise ValueError("E2E-02 immutable contribution result identity/hash/scope mismatch")
    output = loads(result.output_json, {})
    citation = next((row for row in output.get("citations") or []
        if row.get("citation_id") == frozen["citation_id"]), None)
    evaluation = next((row for row in output.get("evaluations") or []
        if row.get("evaluation_id") == frozen["evaluation_id"]), None)
    reference = db.query(ReferenceSource).filter_by(
        id=frozen["reference_id"], run_id=frozen["selected_run_id"]).one_or_none()
    if (not reference or reference.canonical_url_hash != frozen["canonical_url_hash"]
            or not reference.canonical_url.strip()):
        raise ValueError("E2E-02 real citation identity/url hash is missing or changed")
    shared = {"reference_id": frozen["reference_id"], "source_key": frozen["source_key"]}
    if (not citation or citation.get("processing_status") != "DONE"
            or citation.get("disposition") != frozen["citation_disposition"]
            or citation.get("run_id") != frozen["selected_run_id"]
            or any(citation.get(key) != value for key, value in shared.items())
            or not evaluation or evaluation.get("processing_status") != "DONE"
            or evaluation.get("citation_id") != frozen["citation_id"]
            or any(evaluation.get(key) != value for key, value in shared.items())
            or evaluation.get("evidence_relation") != frozen["evidence_relation"]
            or digest(evaluation) != frozen["evaluation_hash"]):
        raise ValueError("E2E-02 frozen low-match citation disposition/evaluation changed")
    if any(row.get("citation_id") == frozen["citation_id"]
            and row.get("evidence_relation") in {"SUPPORTS_FULL", "SUPPORTS_PARTIAL"}
            for row in output.get("bindings") or []):
        raise ValueError("E2E-02 high-match binding cannot masquerade as low-match evidence")
    return {**frozen, "result_hash_valid": True, "real_citation_url": reference.canonical_url}


def _validate_unknown_truth_provenance(*, case: dict[str, Any], task,
                                       frozen_truth: dict[str, Any] | None, truth,
                                       source_execution, source_result) -> None:
    evidence = case["unknown_truth_evidence"]
    source_output = loads(source_result.output_json, {}) if source_result else {}
    source_signals = {
        str(reason.get("reason_id") or "")
        for event in (source_output.get("answer_diagnosis") or {}).get("events") or []
        for reason in event.get("reasons") or []
    }
    if (not frozen_truth or not truth or not source_execution or not source_result
            or task.project_id != case["project_id"] or task.prompt_id != evidence["target_prompt_id"]
            or task.analysis_id != evidence["target_analysis_id"]
            or truth.project_id != task.project_id
            or truth.product_truth_status != "UNKNOWN"
            or truth.capability_label != evidence["capability_label"]
            or frozen_truth.get("product_truth_status") != "UNKNOWN"
            or frozen_truth.get("capability_label") != evidence["capability_label"]
            or source_execution.project_id != task.project_id
            or source_execution.prompt_id != evidence["source_prompt_id"]
            or source_execution.analysis_id != evidence["source_analysis_id"]
            or source_result.output_hash != evidence["source_result_hash"]
            or digest(source_output) != source_result.output_hash
            or evidence["source_signal_id"] not in source_signals):
        raise ValueError("E2E-03 frozen UNKNOWN truth provenance drifted or crossed Project scope")


def _inspect_task(db: Session, case: dict[str, Any], *, phase: str) -> dict[str, Any]:
    row = db.query(SinglePromptOptimizationTask).filter_by(task_id=case["task_id"]).one_or_none()
    if not row:
        raise ValueError(f"task not found: {case['task_id']}")
    inputs = loads(row.input_json, {})
    if (digest(inputs) != row.input_hash or row.input_hash != case["input_hash"]
            or row.project_id != case["project_id"] or row.prompt_id != case["prompt_id"]
            or row.analysis_id != case["analysis_id"] or row.context_id != case["context_id"]):
        raise ValueError(f"frozen task identity mismatch: {case['id']}")
    if inputs.get("provider") != "deepseek" or inputs.get("effective_request_model") != "deepseek-flash":
        raise ValueError(f"{case['id']} is not frozen to DeepSeek Flash")
    context = db.query(SinglePromptAnalysisContext).filter_by(context_id=row.context_id).one_or_none()
    if (not context or context.analysis_id != row.analysis_id or context.project_id != row.project_id
            or context.prompt_id != row.prompt_id or context.raw_output_hash != inputs.get("raw_output_hash")
            or digest(loads(context.raw_output_json, {})) != context.raw_output_hash):
        raise ValueError(f"analysis context identity/hash mismatch: {case['id']}")
    runs = _real_runs(db, inputs, case["run_ids"])
    source = _source_summary(db, inputs)
    low_match = _low_match_summary(db, case, inputs) if case["id"] == "E2E-02" else None
    truths = inputs.get("truth_snapshot") or []
    unknown = [{"truth_id": item.get("truth_id"), "capability_label": item.get("capability_label"),
        "status": item.get("product_truth_status")} for item in truths
        if item.get("product_truth_status") == "UNKNOWN"]
    if case["id"] == "E2E-01":
        brand_context = inputs.get("brand_context") or {}
        managed_assets = inputs.get("managed_assets", [])
        if (brand_context.get("mode") != "EMPTY" or brand_context.get("context_version_id") is not None
                or brand_context.get("passages") or managed_assets != []):
            raise ValueError("E2E-01 requires frozen empty brand context and ManagedAsset collection")
        diagnosis_review_count = (db.query(SinglePromptDiagnosisReview)
            .join(SinglePromptDiagnosisExecution,
                SinglePromptDiagnosisReview.diagnosis_id == SinglePromptDiagnosisExecution.diagnosis_id)
            .filter(SinglePromptDiagnosisExecution.analysis_id == row.analysis_id).count())
        strategy_review_count = (db.query(SinglePromptStrategyReview)
            .join(SinglePromptStrategyExecution,
                SinglePromptStrategyReview.strategy_id == SinglePromptStrategyExecution.strategy_id)
            .filter(SinglePromptStrategyExecution.analysis_id == row.analysis_id).count())
        if diagnosis_review_count or strategy_review_count:
            raise ValueError("E2E-01 must not bind a human Diagnosis or Strategy review")
        if not source or source["ready"] < 1:
            raise ValueError("E2E-01 requires at least one real prepared source snapshot")
    if case["id"] == "E2E-02" and not any(run["reference_count"] for run in runs):
        raise ValueError("E2E-02 requires real observed citations before semantic low-match evaluation")
    if case["id"] == "E2E-03" and not unknown:
        raise ValueError("E2E-03 requires an explicit frozen UNKNOWN capability fact")
    if case["id"] == "E2E-03":
        evidence = case["unknown_truth_evidence"]
        frozen_truth = next((item for item in truths
            if item.get("truth_id") == evidence["truth_id"]), None)
        truth = db.query(TargetBrandCapabilityTruth).filter_by(id=evidence["truth_id"]).one_or_none()
        source_execution = db.query(SinglePromptDiagnosisExecution).filter_by(
            diagnosis_id=evidence["source_diagnosis_id"]).one_or_none()
        source_result = db.query(SinglePromptDiagnosisResult).filter_by(
            diagnosis_id=evidence["source_diagnosis_id"],
            result_version=evidence["source_result_version"]).one_or_none()
        _validate_unknown_truth_provenance(case=case, task=row, frozen_truth=frozen_truth,
            truth=truth, source_execution=source_execution, source_result=source_result)

    view = task_view(row)
    common = {"id": case["id"], "task_id": row.task_id, "project_id": row.project_id,
        "prompt_id": row.prompt_id, "analysis_id": row.analysis_id, "context_id": row.context_id,
        "context_result_version": context.result_version, "input_hash": row.input_hash,
        "raw_output_hash": context.raw_output_hash, "status": row.status, "revision": row.revision,
        "runs": runs, "source": source, "low_match_evidence": low_match,
        "unknown_truths": unknown, "usage": view["usage"]}
    if phase == "plan":
        if row.status in TERMINAL_SUCCESS | {"RUNNING", "CANCELLED"}:
            raise ValueError(f"{case['id']} task is not authorizable: {row.status}")
        authorization = loads(row.authorization_json, {})
        if authorization.get("policy") == "ALLOW_EXTERNAL" or view["usage"]["external_requests"]:
            raise ValueError(f"{case['id']} already has authorization or request usage; no reset allowed")
        return common
    return {**common, "acceptance": _verify_delivery(db, row, case["id"], unknown, low_match)}


def _verify_delivery(db: Session, task: SinglePromptOptimizationTask, scenario_id: str,
                     unknown_truths: list[dict[str, Any]],
                     low_match: dict[str, Any] | None = None) -> dict[str, Any]:
    view = task_view(task)
    authorization = view["authorization"]
    if task.status not in TERMINAL_SUCCESS or view["usage"]["unsettled_requests"]:
        raise ValueError(f"{scenario_id} is not a settled successful task")
    if (authorization.get("automatic_retry") != 0
            or view["usage"]["external_requests"] > authorization.get("max_requests", -1)
            or view["usage"]["reserved_cost_cny"] > float(authorization.get("max_cost_cny") or 0)):
        raise ValueError(f"{scenario_id} exceeded or lacks its immutable task authorization")
    deliveries = view["objects"].get("deliveries") or []
    if not deliveries:
        raise ValueError(f"{scenario_id} has no persisted delivery")
    evidence = []
    for item in deliveries:
        result = db.query(SinglePromptExecutionProposalResult).filter_by(
            result_version=item.get("result_version")).one_or_none()
        if not result or result.output_hash != item.get("result_hash"):
            raise ValueError(f"{scenario_id} delivery version/hash mismatch")
        output = loads(result.output_json, {})
        if digest(output) != result.output_hash or output.get("validation", {}).get("content_delivery_status") != "READY":
            raise ValueError(f"{scenario_id} delivery is not a hash-valid READY result")
        proposal = db.query(SinglePromptExecutionProposal).filter_by(proposal_id=result.proposal_id).one()
        if proposal.analysis_id != task.analysis_id or proposal.context_id != task.context_id:
            raise ValueError(f"{scenario_id} delivery escaped its frozen Analysis/Context")
        delivery_input = output.get("delivery_input") or {}
        receipt = output.get("generation_receipt") or {}
        qa = output.get("automatic_qa") or {}
        body = (output.get("publication_draft") or {}).get("body_markdown", "")
        if not body.strip() or qa.get("status") != "READY" or not receipt.get("segments"):
            raise ValueError(f"{scenario_id} lacks actual text or complete QA")
        evidence.append({"proposal_id": proposal.proposal_id, "result_version": result.result_version,
            "result_hash": result.output_hash, "content_hash": text_digest(body),
            "selected_evidence_count": len(delivery_input.get("selected_evidence") or []),
            "question_topic_count": len(delivery_input.get("question_topics") or []),
            "segment_kinds": [segment.get("kind") for segment in receipt["segments"]],
            "limitations": output.get("limitations") or []})

        if scenario_id == "E2E-01" and not delivery_input.get("selected_evidence"):
            raise ValueError("E2E-01 delivery did not consume attributable source evidence")
        if scenario_id == "E2E-02":
            if not low_match:
                raise ValueError("E2E-02 lacks frozen low-match evidence")
            modes = {row.get("kind") for row in receipt["segments"] if row.get("text", "").strip()}
            if "INSTRUCTION" not in modes:
                raise ValueError("E2E-02 lacks a concrete exploratory action")
            direction = output.get("direction") or delivery_input.get("strategy_direction") or {}
            dependency = next((row for row in direction.get("dependencies") or []
                if row.get("object_type") == "CITATION_CONTRIBUTION_SCOPE"
                and row.get("object_id") == low_match["result_version"]), None)
            eligibility = direction.get("eligibility_by_use") or {}
            if (delivery_input.get("contribution_result_version") != low_match["result_version"]
                    or delivery_input.get("contribution_result_hash") != low_match["result_hash"]
                    or delivery_input.get("selected_evidence")
                    or not dependency or dependency.get("state") != "LIMITED"
                    or dependency.get("eligibility") != "OBSERVE_ONLY"
                    or "SOURCE_GROUNDING_INCOMPLETE" not in (dependency.get("reason_codes") or [])
                    or direction.get("observed_or_hypothesis") != "CONTENT_OPPORTUNITY_HYPOTHESIS"
                    or eligibility.get("publication") != "VERIFY_FIRST"
                    or not direction.get("intervention_goal")
                    or not output.get("limitations")):
                raise ValueError("E2E-02 does not preserve low-match limitation, hypothesis and verification conditions")
        if scenario_id == "E2E-03":
            unknown_ids = {f"truth:{row['truth_id']}" for row in unknown_truths}
            used_ids = {key for row in receipt["segments"] for key in row.get("evidence_ids") or []}
            if unknown_ids & used_ids:
                raise ValueError("E2E-03 promoted an UNKNOWN capability into target-brand evidence")
            if not (delivery_input.get("selected_evidence") or delivery_input.get("question_topics")):
                raise ValueError("E2E-03 returned no useful grounded information beyond unknown facts")
    return {"deliveries": evidence, "result": "PASS"}


def _authorization(case: dict[str, Any], inspected: dict[str, Any], budget: dict[str, Any]) -> dict[str, Any]:
    request_cap = case.get("execute_max_requests", case["max_requests"])
    return {"expected_revision": inspected["revision"], "input_hash": inspected["input_hash"],
        "max_requests": request_cap, "max_tokens": case["max_tokens"],
        "max_cost_cny": case["max_cost_cny"],
        "conservative_cny_per_million_tokens": budget["conservative_cny_per_million_tokens"],
        "pricing_source": budget["pricing_source"], "pricing_checked_at": budget["pricing_checked_at"],
        "authorized_by": budget["authorized_by"]}


def _write_evidence(output: Path, report: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with output.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
    sha = hashlib.sha256(encoded.encode()).hexdigest()
    with output.with_suffix(output.suffix + ".sha256").open("x", encoding="utf-8") as stream:
        stream.write(f"{sha}  {output.name}\n")


def run(*, database: Path, manifest_path: Path, output: Path, phase: str) -> dict[str, Any]:
    manifest = validate_manifest(_read_json(manifest_path))
    database_hash = _sha256_file(database)
    if phase == "plan" and database_hash != manifest.get("source_database_sha256"):
        raise ValueError("source database hash changed after scenario freeze")
    db, engine = _readonly_session(database)
    try:
        inspected = [_inspect_task(db, case, phase=phase) for case in manifest["scenarios"]]
    finally:
        db.close()
        engine.dispose()
    report: dict[str, Any] = {"contract_version": CONTRACT, "phase": phase,
        "generated_at": datetime.now(timezone.utc).isoformat(), "status": "PASS",
        "database": str(database.resolve()), "database_sha256": database_hash,
        "manifest": str(manifest_path.resolve()), "manifest_sha256": _sha256_file(manifest_path),
        "shared_budget": manifest["shared_budget"], "scenarios": inspected,
        "external_requests_by_harness": 0}
    if phase == "plan":
        report["authorization_plan"] = [{"scenario_id": case["id"], "task_id": case["task_id"],
            "payload": _authorization(case, state, manifest["shared_budget"])}
            for case, state in zip(manifest["scenarios"], inspected, strict=True)]
        report["allocated_requests"] = sum(row["payload"]["max_requests"] for row in report["authorization_plan"])
        report["allocated_cost_cny"] = round(sum(float(row["payload"]["max_cost_cny"])
            for row in report["authorization_plan"]), 6)
    else:
        report["actual_requests"] = sum(row["usage"]["external_requests"] for row in inspected)
        report["reserved_cost_cny"] = round(sum(row["usage"]["reserved_cost_cny"] for row in inspected), 6)
        if report["actual_requests"] > manifest["shared_budget"]["max_requests"]:
            raise ValueError("persisted tasks exceed the shared T23 request budget")
        if report["reserved_cost_cny"] > float(manifest["shared_budget"]["max_cost_cny"]):
            raise ValueError("persisted tasks exceed the shared T23 cost budget")
    _write_evidence(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("plan", "verify"))
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run(database=args.database, manifest_path=args.manifest, output=args.output, phase=args.phase)
    except Exception as exc:
        report = {"contract_version": CONTRACT, "phase": args.phase,
            "generated_at": datetime.now(timezone.utc).isoformat(), "status": "BLOCKED",
            "blocker": {"type": type(exc).__name__, "detail": str(exc)},
            "database": str(args.database.resolve()),
            "database_sha256": _sha256_file(args.database) if args.database.is_file() else None,
            "manifest": str(args.manifest.resolve()),
            "manifest_sha256": _sha256_file(args.manifest) if args.manifest.is_file() else None,
            "external_requests_by_harness": 0}
        _write_evidence(args.output, report)
        print(json.dumps({"status": "BLOCKED", "phase": args.phase,
            "external_requests_by_harness": 0, "output": str(args.output)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": report["status"], "phase": report["phase"],
        "external_requests_by_harness": 0, "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
