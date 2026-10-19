from datetime import datetime, timezone
import copy
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from scripts.t23_real_e2e_acceptance import (
    CONTRACT,
    _authorization,
    _low_match_summary,
    _validate_unknown_truth_provenance,
    _verify_delivery,
    validate_manifest,
)
from scripts.live_model_budget import finish, initialize, reserve, summary
from scripts.run_t23_delivery_live import (
    _assert_ledger,
    _checkpoint_dir,
    _checkpoint_events,
    _execute_planned_scenarios,
    _e3_pre_send_failure_provenance,
    _extract_low_match,
    _freeze_e2e03_unknown,
    _freeze_manifest_value,
    _hooks,
    _prepare_e3_answer,
    _require_prepared_answer_admission,
    _write_initial_database_snapshot,
    execute,
    prepare_and_freeze,
)
from test_automatic_delivery import identity, scene, simulated_delivery_transport
from app.modules.single_prompt_v2.automatic_delivery import (
    authorize_task,
    execute_task,
    scoped_client,
    shared_live_budget_hooks,
    task_view,
)
from app.services.semantic_llm.base import SemanticLLMError
from app.core.release_sqlite import get_release_sqlite_dbapi
from app.modules.single_prompt_v2.delivery_text import digest
from app.services.url_identity import build_url_identity
from app.models import SinglePromptCitationContributionExecution
from app.models import SinglePromptAnalysisContext, SinglePromptDiagnosisExecution, SinglePromptDiagnosisResult


def manifest():
    return {
        "contract_version": CONTRACT,
        "source_database_sha256": "a" * 64,
        "shared_budget": {
            "budget_id": "t23-live-acceptance-20261016",
            "max_requests": 9,
            "max_cost_cny": 40,
            "conservative_cny_per_million_tokens": 10,
            "pricing_source": "operator-verified-provider-pricing",
            "pricing_checked_at": datetime.now(timezone.utc).date().isoformat(),
            "authorized_by": "acceptance-controller",
            "max_attempts": 1,
            "automatic_retry": 0,
        },
        "scenarios": [{
            "id": scenario,
            "task_id": f"task-{scenario}",
            "project_id": 1,
            "prompt_id": 1 if scenario == "E2E-02" else index,
            "analysis_id": f"analysis-{1 if scenario == 'E2E-02' else index}",
            "context_id": f"context-{1 if scenario == 'E2E-02' else index}",
            "input_hash": str(index) * 64,
            "run_ids": [1 if scenario == "E2E-02" else index],
            "max_requests": {"E2E-01": 4, "E2E-02": 3, "E2E-03": 2}[scenario],
            "max_tokens": 300_000,
            "max_cost_cny": 10,
            **({
                "prepare_max_requests": 1,
                "execute_max_requests": 3,
                "answer_prepare_input": {
                    "citation_manifest_id": "citation-manifest-e2e01",
                    "citation_manifest_hash": "7" * 64,
                    "selected_run_id": 1,
                },
            } if scenario == "E2E-01" else {}),
            **({
                "prepare_max_requests": 1,
                "execute_max_requests": 2,
                "prepare_input": {
                    "answer_result_version": "diagnosis-v1:answer",
                    "answer_result_hash": "e" * 64,
                    "citation_manifest_id": "citation-manifest-e2e02",
                    "citation_manifest_hash": "f" * 64,
                    "completion_manifest_id": "completion-manifest-e2e02",
                    "completion_manifest_hash": "1" * 64,
                    "selected_run_id": 1,
                },
            } if scenario == "E2E-02" else {}),
            **({"low_match_evidence": {
                "contribution_id": "contribution-low-match",
                "result_version": "contribution-v1:low-match",
                "result_hash": "b" * 64,
                "selected_run_id": 1,
                "citation_id": "citation-real-2",
                "reference_id": 22,
                "source_key": "source-real-2",
                "canonical_url_hash": "c" * 64,
                "citation_disposition": "NO_BINDING_FOUND_AFTER_SEARCH",
                "evaluation_id": "evaluation-low-match",
                "evaluation_hash": "d" * 64,
                "evidence_relation": "NO_MATCH",
            }} if scenario == "E2E-02" else {}),
            **({"unknown_truth_evidence": {
                "truth_id": 7, "project_id": 1, "capability_label": "支持离线备份",
                "product_truth_status": "UNKNOWN", "source_diagnosis_id": "diagnosis-answer",
                "source_result_version": "diagnosis-v1:answer", "source_result_hash": "6" * 64,
                "source_signal_id": "reason-target", "source_prompt_id": 1,
                "source_analysis_id": "analysis-1", "target_prompt_id": 3,
                "target_analysis_id": "analysis-3",
            }} if scenario == "E2E-03" else {}),
        } for index, scenario in enumerate(("E2E-01", "E2E-02", "E2E-03"), 1)],
    }


def test_manifest_requires_one_shared_non_retrying_budget_for_all_three_scenarios():
    value = manifest()
    assert validate_manifest(value) is value

    value = manifest()
    value["scenarios"][2]["max_requests"] = 3
    with pytest.raises(ValueError, match="request caps exceed"):
        validate_manifest(value)

    value = manifest()
    value["shared_budget"]["max_attempts"] = 2
    with pytest.raises(ValueError, match="one provider attempt"):
        validate_manifest(value)

    value = manifest()
    value["scenarios"][1]["low_match_evidence"]["evidence_relation"] = "SUPPORTS_FULL"
    with pytest.raises(ValueError, match="not a formal low-match"):
        validate_manifest(value)

    value = manifest()
    value["scenarios"][1]["id"] = "E2E-01"
    with pytest.raises(ValueError, match="exactly once"):
        validate_manifest(value)

    value = manifest()
    del value["scenarios"][1]["low_match_evidence"]
    with pytest.raises(ValueError, match="freeze one exact real low-match"):
        validate_manifest(value)

    del value["scenarios"][1]["prepare_input"]["answer_result_version"]
    del value["scenarios"][1]["prepare_input"]["answer_result_hash"]
    assert validate_manifest(value, allow_unprepared_e2e02=True) is value
    with pytest.raises(ValueError, match="exact formal Contribution prepare inputs"):
        validate_manifest(value)

    value = manifest()
    value["scenarios"][1]["execute_max_requests"] = 3
    with pytest.raises(ValueError, match=r"1 prepare \+ 2 execute"):
        validate_manifest(value)


def test_pending_e2e03_is_prepare_only_and_requires_bounded_unknown_input():
    value = manifest()
    value["scenarios"][2].update({
        "task_id": "PENDING_AFTER_FORMAL_UNKNOWN",
        "input_hash": "0" * 64,
        "task_pending_truth": True,
        "unknown_prepare_input": {
            "signal_selector": "UNIQUE_TARGET_BRAND_CAPABILITY",
            "source_reference": "isolated acceptance",
            "note": "unknown until independently verified",
            "reviewed_by": "acceptance-controller",
        },
    })
    with pytest.raises(ValueError, match="cannot be planned"):
        validate_manifest(value)
    assert validate_manifest(value, allow_unprepared_e2e03=True) is value
    value["scenarios"][2]["unknown_prepare_input"]["signal_selector"] = "FIRST_REASON"
    with pytest.raises(ValueError, match="bounded formal UNKNOWN"):
        validate_manifest(value, allow_unprepared_e2e03=True)


def test_pending_e2e03_refuses_to_invent_a_missing_answer_signal():
    value = manifest()
    value["scenarios"][2].update({
        "task_pending_truth": True,
        "unknown_prepare_input": {
            "signal_selector": "UNIQUE_TARGET_BRAND_CAPABILITY",
            "source_reference": "isolated acceptance",
            "note": "unknown until independently verified",
            "reviewed_by": "acceptance-controller",
        },
    })
    result = SimpleNamespace(output_json=json.dumps({
        "input": {"brand_snapshot": {"brand_name": "Target", "aliases": []}},
        "answer_diagnosis": {"events": []},
    }))
    db = SimpleNamespace(query=lambda *_: SimpleNamespace(filter_by=lambda **_:
        SimpleNamespace(one_or_none=lambda: object())))
    with pytest.raises(ValueError, match="E2E-03_UNKNOWN_SIGNAL_REVIEW_REQUIRED"):
        _freeze_e2e03_unknown(db, value, SimpleNamespace(project_id=1), result)


def test_prepare_refuses_persisted_failed_answer_before_contribution_plan():
    answer = "real frozen provider answer"
    raw = {"runs": [{"run_id": 2, "status": "success", "answer_text": answer}]}
    output = {"answer_diagnosis": {"answer_jobs": [{
        "answer_hash": hashlib.sha256(answer.encode()).hexdigest(), "run_ids": [2],
        "status": "FAILED", "result_source": "UNKNOWN",
        "error": "provider configuration unavailable",
    }]}}
    with pytest.raises(ValueError, match="ANSWER_PREPARE_NOT_MACHINE_ADMITTED.*actual_failure=True"):
        _require_prepared_answer_admission(raw_output=raw, answer_output=output, selected_run_id=2)


def test_unknown_truth_provenance_allows_same_project_cross_prompt_and_rejects_drift():
    case = manifest()["scenarios"][2]
    output = {"answer_diagnosis": {"events": [{"reasons": [
        {"reason_id": case["unknown_truth_evidence"]["source_signal_id"]}]}]}}
    source_result = SimpleNamespace(output_json=json.dumps(output), output_hash=digest(output))
    case["unknown_truth_evidence"]["source_result_hash"] = source_result.output_hash
    task = SimpleNamespace(project_id=1, prompt_id=3, analysis_id="analysis-3")
    truth = SimpleNamespace(project_id=1, product_truth_status="UNKNOWN",
        capability_label="支持离线备份")
    source = SimpleNamespace(project_id=1, prompt_id=1, analysis_id="analysis-1")
    frozen = {"truth_id": 7, "product_truth_status": "UNKNOWN",
        "capability_label": "支持离线备份"}

    _validate_unknown_truth_provenance(case=case, task=task, frozen_truth=frozen,
        truth=truth, source_execution=source, source_result=source_result)

    with pytest.raises(ValueError, match="crossed Project"):
        _validate_unknown_truth_provenance(case=case, task=task, frozen_truth=frozen,
            truth=truth, source_execution=SimpleNamespace(project_id=2, prompt_id=1,
                analysis_id="analysis-1"), source_result=source_result)
    case["unknown_truth_evidence"]["source_result_hash"] = "0" * 64
    with pytest.raises(ValueError, match="provenance drifted"):
        _validate_unknown_truth_provenance(case=case, task=task, frozen_truth=frozen,
            truth=truth, source_execution=source, source_result=source_result)

def test_initial_database_snapshot_uses_sqlite_backup_and_includes_wal(tmp_path):
    database = tmp_path / "wal-source.sqlite3"
    writer = sqlite3.connect(database)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("CREATE TABLE evidence(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
    writer.commit()
    writer.execute("INSERT INTO evidence(value) VALUES('durable-wal-row')")
    writer.commit()
    assert Path(f"{database}-wal").exists()

    snapshot = _write_initial_database_snapshot(database, tmp_path / "checkpoints")

    copied = sqlite3.connect(snapshot)
    assert copied.execute("SELECT value FROM evidence").fetchone()[0] == "durable-wal-row"
    copied.close()
    writer.close()


def test_authorization_payload_is_exact_task_revision_and_controller_allocation():
    value = manifest()
    payload = _authorization(value["scenarios"][0], {"revision": 7, "input_hash": "f" * 64}, value["shared_budget"])
    assert payload == {
        "expected_revision": 7,
        "input_hash": "f" * 64,
        "max_requests": 3,
        "max_tokens": 300_000,
        "max_cost_cny": 10,
        "conservative_cny_per_million_tokens": 10,
        "pricing_source": "operator-verified-provider-pricing",
        "pricing_checked_at": datetime.now(timezone.utc).date().isoformat(),
        "authorized_by": "acceptance-controller",
    }
    e2e02 = _authorization(value["scenarios"][1], {"revision": 8, "input_hash": "e" * 64}, value["shared_budget"])
    assert e2e02["max_requests"] == 2


def test_post_execution_gate_requires_persisted_ready_text_qa_and_hashes(scene, monkeypatch, tmp_path):
    db, row, _, _ = scene
    authorize_task(db, row, expected_revision=row.revision, input_hash=row.input_hash,
        max_requests=4, max_tokens=400_000, max_cost_cny=4,
        conservative_cny_per_million_tokens=10, pricing_source="offline-contract-test",
        pricing_checked_at=datetime.now(timezone.utc).date().isoformat(), authorized_by="offline-test")
    simulated_delivery_transport(monkeypatch)
    execute_task(row.task_id, session_factory=sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    db.refresh(row)

    from app.models import ReferenceSource, SinglePromptCitationContributionResult
    contribution_ref = task_view(row)["objects"]["citation_results"][0]
    contribution = db.query(SinglePromptCitationContributionResult).filter_by(
        result_version=contribution_ref["result_version"]).one()
    contribution_output = json.loads(contribution.output_json)
    evaluation = contribution_output["evaluations"][0]
    citation = next(item for item in contribution_output["citations"]
        if item["citation_id"] == evaluation["citation_id"])
    reference = db.query(ReferenceSource).filter_by(
        id=citation["reference_id"], run_id=citation["run_id"]).one()
    if not reference.canonical_url:
        reference.canonical_url = "https://example.test/real-citation"
        reference.canonical_url_hash = build_url_identity(reference.canonical_url).canonical_url_hash
        db.commit()
    low_match = {
        "contribution_id": contribution.contribution_id,
        "result_version": contribution.result_version,
        "result_hash": contribution.output_hash,
        "selected_run_id": citation["run_id"],
        "citation_id": citation["citation_id"],
        "reference_id": citation["reference_id"],
        "source_key": citation["source_key"],
        "canonical_url_hash": reference.canonical_url_hash,
        "citation_disposition": citation["disposition"],
        "evaluation_id": evaluation["evaluation_id"],
        "evaluation_hash": digest(evaluation),
        "evidence_relation": evaluation["evidence_relation"],
    }
    case = {"id": "E2E-02", "analysis_id": row.analysis_id, "context_id": row.context_id,
        "project_id": row.project_id, "prompt_id": row.prompt_id,
        "prepare_input": {"selected_run_id": citation["run_id"]},
        "low_match_evidence": low_match}
    assert _low_match_summary(db, case, json.loads(row.input_json))["evaluation_id"] == evaluation["evaluation_id"]
    contribution_execution = db.query(SinglePromptCitationContributionExecution).filter_by(
        contribution_id=contribution.contribution_id).one()
    assert _extract_low_match(db, case, contribution_execution, contribution) == low_match

    high_match = copy.deepcopy(contribution_output)
    high_match["evaluations"][0]["evidence_relation"] = "SUPPORTS_FULL"
    high_result = SimpleNamespace(output_json=json.dumps(high_match), output_hash=digest(high_match))
    with pytest.raises(ValueError, match="no formal low-match"):
        _extract_low_match(db, case, contribution_execution, high_result)

    wrong_run = copy.deepcopy(contribution_output)
    next(item for item in wrong_run["citations"]
        if item["citation_id"] == evaluation["citation_id"])["run_id"] += 999
    wrong_run_result = SimpleNamespace(output_json=json.dumps(wrong_run), output_hash=digest(wrong_run))
    with pytest.raises(ValueError, match="no formal low-match"):
        _extract_low_match(db, case, contribution_execution, wrong_run_result)

    drifted_result = SimpleNamespace(output_json=contribution.output_json, output_hash="0" * 64)
    with pytest.raises(ValueError, match="identity/hash drifted"):
        _extract_low_match(db, case, contribution_execution, drifted_result)

    cross_run_contribution = copy.deepcopy(contribution_output)
    cross_run_citation = next(item for item in cross_run_contribution["citations"]
        if item["citation_id"] == citation["citation_id"])
    cross_run_citation["run_id"] = citation["run_id"] + 999
    contribution.output_json = json.dumps(cross_run_contribution, ensure_ascii=False)
    contribution.output_hash = digest(cross_run_contribution)
    cross_run_low = {**low_match, "result_hash": contribution.output_hash}
    with db.no_autoflush:
        with pytest.raises(ValueError, match="disposition/evaluation changed"):
            _low_match_summary(db, {**case, "low_match_evidence": cross_run_low}, json.loads(row.input_json))
    db.rollback()
    db.refresh(row)
    contribution = db.query(SinglePromptCitationContributionResult).filter_by(
        result_version=contribution_ref["result_version"]).one()

    result = _verify_delivery(db, row, "E2E-02", [], low_match)
    assert result["result"] == "PASS"
    assert result["deliveries"][0]["segment_kinds"] == ["HEADING", "INSTRUCTION"]
    usage = task_view(row)["usage"]
    assert usage["external_requests"] == 4
    assert usage["cache_hits"] == 0
    assert 0 < usage["reserved_tokens"] <= 400_000
    assert 0 < usage["reserved_cost_cny"] <= 4
    assert usage["actual_tokens"] == 600
    assert usage["unsettled_requests"] == 0

    forged_contribution = copy.deepcopy(contribution_output)
    forged_contribution["bindings"].append({"citation_id": citation["citation_id"],
        "evidence_relation": "SUPPORTS_FULL"})
    contribution.output_json = json.dumps(forged_contribution, ensure_ascii=False)
    contribution.output_hash = digest(forged_contribution)
    forged_low = {**low_match, "result_hash": contribution.output_hash}
    with db.no_autoflush:
        with pytest.raises(ValueError, match="high-match binding cannot masquerade"):
            _low_match_summary(db, {**case, "low_match_evidence": forged_low}, json.loads(row.input_json))
    db.rollback()
    db.refresh(row)

    delivery = task_view(row)["objects"]["deliveries"][0]
    from app.models import SinglePromptExecutionProposalResult
    saved = db.query(SinglePromptExecutionProposalResult).filter_by(result_version=delivery["result_version"]).one()
    saved.output_json = json.dumps({"forged": True})
    with db.no_autoflush:
        with pytest.raises(ValueError, match="hash-valid READY"):
            _verify_delivery(db, row, "E2E-02", [])
    db.rollback()


def test_shared_ledger_reservation_and_accepted_audit_are_persisted(scene, tmp_path):
    db, row, _, _ = scene
    authorize_task(db, row, expected_revision=row.revision, input_hash=row.input_hash,
        max_requests=1, max_tokens=10_000, max_cost_cny=1,
        conservative_cny_per_million_tokens=10, pricing_source="offline-contract-test",
        pricing_checked_at=datetime.now(timezone.utc).date().isoformat(), authorized_by="offline-test")
    row.status = "RUNNING"
    db.commit()
    ledger = tmp_path / "model-budget-v2.sqlite3"
    initialize(ledger, pricing_source="operator-verified-provider-pricing",
        pricing_checked_at=datetime.now(timezone.utc).date().isoformat())
    request_guard, audit_sink, _settle_unknown = _hooks(
        ledger, scenario_id="E2E-01", task_id=row.task_id)
    request = {**identity(row), "input_hash": "a" * 64,
        "provider_payload_hash": "b" * 64, "attempt": 1}
    client = None
    with shared_live_budget_hooks(request_guard=request_guard, response_audit_sink=audit_sink):
        client = scoped_client(db, row)
        client.request_guard(request)
        client.response_audit_sink({"request_identity": request, "response_source": "PROVIDER",
            "validation_status": "ACCEPTED", "token_usage": {"total_tokens": 1}})
    state = summary(ledger)
    assert state["used_requests"] == 1
    assert state["requests"][0]["status"] == "FINISHED"


def test_shared_ledger_reservation_is_finished_when_local_task_guard_rejects(scene, tmp_path):
    db, row, _, _ = scene
    ledger = tmp_path / "model-budget-v2.sqlite3"
    initialize(ledger, pricing_source="operator-verified-provider-pricing",
        pricing_checked_at=datetime.now(timezone.utc).date().isoformat())
    request_guard, audit_sink, _settle_unknown = _hooks(
        ledger, scenario_id="E2E-01", task_id=row.task_id)
    request = {**identity(row), "input_hash": "a" * 64,
        "provider_payload_hash": "b" * 64, "attempt": 1}

    # The task is still QUEUED, so its local guard rejects after the shared
    # reservation.  The composite hook must finish that reservation as FAILED.
    with shared_live_budget_hooks(request_guard=request_guard, response_audit_sink=audit_sink):
        with pytest.raises(SemanticLLMError, match="OPTIMIZATION_NOT_RUNNING"):
            scoped_client(db, row).request_guard(request)

    state = summary(ledger)
    assert state["used_requests"] == 1
    assert state["by_task"]["T23"] == 1
    assert state["requests"][0]["status"] == "FAILED"


def test_prepare_budget_is_counted_once_and_execute_only_receives_remaining_allocation(scene, tmp_path):
    _, row, _, _ = scene
    ledger = tmp_path / "model-budget-v2.sqlite3"
    value = manifest()
    initialize(ledger, pricing_source=value["shared_budget"]["pricing_source"],
        pricing_checked_at=value["shared_budget"]["pricing_checked_at"])
    _assert_ledger(value, summary(ledger), include_prepare=True)
    request_guard, _audit_sink, settle_unknown = _hooks(
        ledger, scenario_id="E2E-02", task_id=f"prepare:{row.task_id}")
    request = {**identity(row), "input_hash": "a" * 64,
        "provider_payload_hash": "b" * 64, "attempt": 1}
    request_guard(request)
    settle_unknown(TimeoutError("provider delivery unknown"))
    state = summary(ledger)
    assert state["used_requests"] == 1
    assert state["requests"][0]["status"] == "DELIVERY_UNKNOWN"
    _assert_ledger(value, state)
    with pytest.raises(ValueError, match="remaining shared request budget"):
        _assert_ledger(value, state, include_prepare=True)
    assert _authorization(value["scenarios"][1], {"revision": 1, "input_hash": "a" * 64},
        value["shared_budget"])["max_requests"] == 2


def test_repeated_prepare_freeze_is_idempotent_but_identity_drift_is_rejected():
    value = manifest()
    case = value["scenarios"][1]
    low = case.pop("low_match_evidence")
    first = _freeze_manifest_value(value, low, "9" * 64)
    second = _freeze_manifest_value(first, low, "9" * 64)
    assert second == first
    with pytest.raises(ValueError, match="different immutable low-match"):
        _freeze_manifest_value(first, {**low, "evaluation_hash": "8" * 64}, "9" * 64)


def test_prepare_freeze_uses_formal_answer_and_contribution_with_one_shared_ledger(
        scene, monkeypatch, tmp_path):
    from app.models import ReferenceSource, SinglePromptCitationManifest, SinglePromptSourceCompletionManifest

    db, row, _, _ = scene
    citation = db.query(SinglePromptCitationManifest).filter_by(analysis_id=row.analysis_id).one()
    completion = db.query(SinglePromptSourceCompletionManifest).filter_by(
        analysis_id=row.analysis_id, context_id=row.context_id).one()
    inputs = json.loads(row.input_json)
    run_id = inputs["run_ids"][0]
    for reference in db.query(ReferenceSource).filter_by(run_id=run_id).all():
        reference.canonical_url = reference.canonical_url or "https://example.test/real-citation"
        reference.canonical_url_hash = build_url_identity(reference.canonical_url).canonical_url_hash
    database = Path(str(db.get_bind().url.database))
    db.commit()
    db.close()
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()

    value = manifest()
    for case in value["scenarios"][:2]:
        case.update(task_id=row.task_id, project_id=row.project_id, prompt_id=row.prompt_id,
            analysis_id=row.analysis_id, context_id=row.context_id, input_hash=row.input_hash,
            run_ids=[run_id])
    value["scenarios"][0]["answer_prepare_input"] = {
        "citation_manifest_id": citation.manifest_id,
        "citation_manifest_hash": citation.payload_hash,
        "selected_run_id": run_id,
    }
    value["scenarios"][1]["prepare_input"] = {
        "citation_manifest_id": citation.manifest_id,
        "citation_manifest_hash": citation.payload_hash,
        "completion_manifest_id": completion.manifest_id,
        "completion_manifest_hash": completion.payload_hash,
        "selected_run_id": run_id,
    }
    value["scenarios"][1].pop("low_match_evidence")
    value["source_database_sha256"] = hashlib.sha256(database.read_bytes()).hexdigest()
    input_manifest = tmp_path / "t23-prepare.json"
    input_manifest.write_text(json.dumps(value), encoding="utf-8")
    ledger = tmp_path / "model-budget-v2.sqlite3"
    initialize(ledger, pricing_source=value["shared_budget"]["pricing_source"],
        pricing_checked_at=value["shared_budget"]["pricing_checked_at"])
    calls = simulated_delivery_transport(monkeypatch)

    frozen_path = tmp_path / "t23-frozen.json"
    import scripts.run_t23_delivery_live as runner
    real_claim = runner.claim_diagnosis
    def crash_after_claim(*args, **kwargs):
        token = real_claim(*args, **kwargs)
        assert token
        raise KeyboardInterrupt("simulated process loss after claim and before provider send")
    monkeypatch.setattr(runner, "claim_diagnosis", crash_after_claim)
    with pytest.raises(KeyboardInterrupt, match="after claim"):
        prepare_and_freeze(database=database, ledger=ledger, manifest_path=input_manifest,
            frozen_manifest_path=frozen_path, report_path=tmp_path / "crashed-report.json")
    assert calls == []
    assert summary(ledger)["used_requests"] == 0
    assert [row["stage"] for row in _checkpoint_events(_checkpoint_dir(frozen_path))] == ["INITIAL"]
    monkeypatch.setattr(runner, "claim_diagnosis", real_claim)

    connection = get_release_sqlite_dbapi().connect(str(database))
    original_project_name = connection.execute(
        "SELECT name FROM projects WHERE id=?", (row.project_id,)).fetchone()[0]
    connection.execute("UPDATE projects SET name=? WHERE id=?",
        (f"{original_project_name}-unrelated-drift", row.project_id))
    connection.commit()
    connection.close()
    with pytest.raises(ValueError, match="unrelated database drift in projects"):
        prepare_and_freeze(database=database, ledger=ledger, manifest_path=input_manifest,
            frozen_manifest_path=frozen_path, report_path=tmp_path / "drift-report.json")
    connection = get_release_sqlite_dbapi().connect(str(database))
    connection.execute("UPDATE projects SET name=? WHERE id=?", (original_project_name, row.project_id))
    connection.commit()
    connection.close()

    report = prepare_and_freeze(database=database, ledger=ledger, manifest_path=input_manifest,
        frozen_manifest_path=frozen_path, report_path=tmp_path / "prepare-report.json")
    assert report["status"] == "PASS"
    frozen = validate_manifest(json.loads(frozen_path.read_text()))
    assert frozen["scenarios"][1]["low_match_evidence"]["selected_run_id"] == run_id
    assert frozen["source_database_sha256"] == hashlib.sha256(database.read_bytes()).hexdigest()
    assert summary(ledger)["used_requests"] == 2
    checkpoints = _checkpoint_events(_checkpoint_dir(frozen_path))
    assert checkpoints[0]["stage"] == "INITIAL"
    assert "PRE_SEND_DATABASE_RECOVERED" in {row["stage"] for row in checkpoints}
    assert checkpoints[-1]["stage"] == "READY_TO_FREEZE"
    assert checkpoints[-1]["answer_result_hash"]
    assert checkpoints[-1]["contribution_id"]
    assert {row["status"] for row in checkpoints[-1]["ledger_requests"]} == {"FINISHED"}
    assert all(row["original_manifest_sha256"] == checkpoints[0]["original_manifest_sha256"]
        for row in checkpoints)

    second_path = tmp_path / "t23-frozen-repeat.json"
    repeated = prepare_and_freeze(database=database, ledger=ledger, manifest_path=frozen_path,
        frozen_manifest_path=second_path, report_path=tmp_path / "prepare-repeat-report.json")
    assert repeated["low_match_evidence"] == report["low_match_evidence"]
    assert summary(ledger)["used_requests"] == 2


def test_execute_continues_independent_scenarios_and_aggregates_blocked(monkeypatch, tmp_path):
    import scripts.run_t23_delivery_live as runner

    rows = {case["task_id"]: SimpleNamespace(task_id=case["task_id"]) for case in manifest()["scenarios"]}
    class Query:
        def __init__(self): self.task_id = ""
        def filter_by(self, **values): self.task_id = values["task_id"]; return self
        def one(self): return rows[self.task_id]
    class DB:
        def __init__(self): self.rollbacks = 0
        def query(self, _model): return Query()
        def expire_all(self): pass
        def rollback(self): self.rollbacks += 1
    db = DB()
    calls = []
    monkeypatch.setattr(runner, "authorize_task", lambda db, row, **payload: None)
    monkeypatch.setattr(runner, "_hooks", lambda *args, **kwargs: (lambda value: None,
        lambda value: None, lambda exc: None))
    def fake_execute(task_id, **kwargs):
        calls.append(task_id)
        if task_id == "task-E2E-01":
            raise RuntimeError("scenario one failed")
    monkeypatch.setattr(runner, "execute_task", fake_execute)
    monkeypatch.setattr(runner, "_inspect_task", lambda db, case, phase: {"revision": 1,
        "input_hash": case["input_hash"], "verified": case["id"]})
    value = manifest()

    results = _execute_planned_scenarios(db, object, value, tmp_path / "unused.sqlite3")

    assert calls == ["task-E2E-01", "task-E2E-02", "task-E2E-03"]
    assert [row["status"] for row in results] == ["BLOCKED", "PASS", "PASS"]
    assert db.rollbacks == 1


def test_execute_reports_plan_failure_and_runs_later_scenarios(scene, monkeypatch, tmp_path):
    import scripts.run_t23_delivery_live as runner

    db, row, _, _ = scene
    database = Path(str(db.get_bind().url.database))
    db.commit()
    db.close()
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()
    value = manifest()
    for case in value["scenarios"]:
        case.update(task_id=row.task_id, project_id=row.project_id, prompt_id=row.prompt_id,
            analysis_id=row.analysis_id, context_id=row.context_id, input_hash=row.input_hash,
            run_ids=[json.loads(row.input_json)["run_ids"][0]])
    value["scenarios"][2]["unknown_truth_evidence"].update(
        project_id=row.project_id, target_prompt_id=row.prompt_id,
        target_analysis_id=row.analysis_id)
    value["scenarios"][0]["answer_prepare_input"]["selected_run_id"] = value["scenarios"][0]["run_ids"][0]
    value["scenarios"][1]["prepare_input"]["selected_run_id"] = value["scenarios"][1]["run_ids"][0]
    value["scenarios"][1]["low_match_evidence"]["selected_run_id"] = value["scenarios"][1]["run_ids"][0]
    value["source_database_sha256"] = hashlib.sha256(database.read_bytes()).hexdigest()
    manifest_path = tmp_path / "frozen-execute.json"
    manifest_path.write_text(json.dumps(value), encoding="utf-8")
    ledger = tmp_path / "model-budget-v2.sqlite3"
    initialize(ledger, pricing_source=value["shared_budget"]["pricing_source"],
        pricing_checked_at=value["shared_budget"]["pricing_checked_at"])
    calls = []
    def inspect(_db, case, phase):
        if phase == "plan" and case["id"] == "E2E-01":
            raise ValueError("scenario plan rejected")
        return {"revision": 1, "input_hash": case["input_hash"], "verified": case["id"]}
    monkeypatch.setattr(runner, "_inspect_task", inspect)
    monkeypatch.setattr(runner, "authorize_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "_hooks", lambda *args, **kwargs: (lambda value: None,
        lambda value: None, lambda exc: None))
    monkeypatch.setattr(runner, "execute_task", lambda task_id, **kwargs: calls.append(task_id))

    report = execute(database=database, ledger=ledger, manifest_path=manifest_path,
        report_path=tmp_path / "execute-report.json")

    assert report["status"] == "BLOCKED" and report["exit_code"] == 2
    assert [item["status"] for item in report["scenarios"]] == ["BLOCKED", "PASS", "PASS"]
    assert len(calls) == 2


def test_partial_manifest_blocks_e2_without_authorization_and_runs_e1_e3(scene, monkeypatch):
    import scripts.run_t23_delivery_live as runner

    db, row, _, _ = scene
    value = manifest()
    blocker = {"code": "NO_FORMAL_LOW_MATCH", "detail": "accepted result had no low match",
        "contribution_id": "contribution-real", "result_version": "contribution-v1:real",
        "result_hash": "a" * 64, "selected_run_id": 1,
        "consumed_requests": 1, "forfeited_execute_requests": 2,
        "ledger_request_id": "T23:E2E-02:prepare:contribution-real:payload",
        "reserved_cost_cny": 0.25}
    value["scenarios"][1]["scenario_blocker"] = blocker
    value["scenarios"][1]["execute_max_requests"] = 0
    value["scenarios"][1].pop("low_match_evidence")
    value["scenarios"][2].update(max_requests=3, prepare_max_requests=1,
        execute_max_requests=2, answer_prepare_input={"citation_manifest_id": "citation-e3",
            "citation_manifest_hash": "b" * 64, "selected_run_id": 3})
    assert validate_manifest(value) is value

    rows = {case["task_id"]: SimpleNamespace(task_id=case["task_id"])
        for case in value["scenarios"]}
    db.query = lambda *_: SimpleNamespace(filter_by=lambda **kwargs:
        SimpleNamespace(one=lambda: rows[kwargs["task_id"]]))
    inspected = []
    authorized = []
    executed = []
    monkeypatch.setattr(runner, "_inspect_task", lambda _db, case, phase:
        inspected.append(case["id"]) or {"revision": 1, "input_hash": case["input_hash"]})
    monkeypatch.setattr(runner, "authorize_task", lambda _db, task, **kwargs:
        authorized.append(task.task_id))
    monkeypatch.setattr(runner, "_hooks", lambda *args, **kwargs:
        (lambda value: None, lambda value: None, lambda exc: None))
    monkeypatch.setattr(runner, "execute_task", lambda task_id, **kwargs: executed.append(task_id))

    results = _execute_planned_scenarios(db, None, value, Path("unused-ledger"))
    assert [item["status"] for item in results] == ["PASS", "BLOCKED", "PASS"]
    assert inspected == ["E2E-01", "E2E-01", "E2E-03", "E2E-03"]
    assert authorized == executed == ["task-E2E-01", "task-E2E-03"]


def test_e3_own_answer_prepare_freezes_identity_and_uses_one_guarded_request(
        scene, monkeypatch, tmp_path):
    db, row, _, _ = scene
    inputs = json.loads(row.input_json)
    value = manifest()
    e3 = value["scenarios"][2]
    e3.update(project_id=row.project_id, prompt_id=row.prompt_id,
        analysis_id=row.analysis_id, context_id=row.context_id,
        run_ids=inputs["run_ids"], task_pending_truth=True)
    e3["unknown_prepare_input"] = {"signal_selector": "UNIQUE_TARGET_BRAND_CAPABILITY",
        "source_reference": "isolated acceptance", "note": "verify independently",
        "reviewed_by": "acceptance-controller"}
    database = Path(str(db.get_bind().url.database))
    ledger = tmp_path / "model-budget-v2.sqlite3"
    initialize(ledger, pricing_source=value["shared_budget"]["pricing_source"],
        pricing_checked_at=value["shared_budget"]["pricing_checked_at"])
    simulated_delivery_transport(monkeypatch)

    diagnosis, result = _prepare_e3_answer(db=db, manifest=value, ledger=ledger,
        checkpoint_dir=tmp_path / "checkpoints", manifest_sha="f" * 64,
        database=database, e1_answer=SimpleNamespace(result_version="e1-result"),
        contribution=SimpleNamespace(contribution_id="e2-contribution", plan_hash="a" * 64))

    assert diagnosis.analysis_id == row.analysis_id and result.output_hash
    assert e3["prepare_max_requests"] == 1 and e3["execute_max_requests"] == 2
    assert e3["answer_prepare_input"]["selected_run_id"] == inputs["run_ids"][0]
    state = summary(ledger)
    assert state["by_task"]["T23"] == 1
    assert [event["stage"] for event in _checkpoint_events(tmp_path / "checkpoints")] == [
        "E3_ANSWER_READY_TO_SEND", "E3_ANSWER_RESULT"]


def test_e3_pre_send_recovery_creates_one_new_execution_and_is_idempotent(
        scene, monkeypatch, tmp_path):
    import scripts.run_t23_delivery_live as runner

    db, row, _, _ = scene
    inputs = json.loads(row.input_json)
    run_id = inputs["run_ids"][0]
    value = manifest()
    e3 = value["scenarios"][2]
    e3.update(project_id=row.project_id, prompt_id=row.prompt_id,
        analysis_id=row.analysis_id, context_id=row.context_id,
        run_ids=[run_id], task_pending_truth=True)
    e3["unknown_prepare_input"] = {"signal_selector": "UNIQUE_TARGET_BRAND_CAPABILITY",
        "source_reference": "isolated acceptance", "note": "verify independently",
        "reviewed_by": "acceptance-controller"}
    context = db.query(SinglePromptAnalysisContext).filter_by(context_id=row.context_id).one()
    raw = json.loads(context.raw_output_json)
    frozen_run = next(item for item in raw["runs"] if item["run_id"] == run_id)
    preparation, _ = runner.create_source_preparation(db, analysis_id=row.analysis_id,
        project_id=row.project_id, prompt_id=row.prompt_id,
        idempotency_key=f"{value['shared_budget']['budget_id']}:E2E-03:answer-sources",
        created_by="t23-acceptance-controller")
    citation = db.query(runner.SinglePromptCitationManifest).filter_by(
        manifest_id=preparation.citation_manifest_id).one()
    old, _ = runner.create_answer_diagnosis(db, analysis_id=row.analysis_id,
        project_id=row.project_id, prompt_id=row.prompt_id,
        citation_manifest_id=citation.manifest_id, citation_manifest_hash=citation.payload_hash,
        answer_llm_policy="ALLOW_EXTERNAL",
        idempotency_key=f"{value['shared_budget']['budget_id']}:E2E-03:prepare-answer")
    failure = "DEEPSEEK_API_KEY 未配置。请在 backend/.env 设置（代码与日志禁止输出该值）。"
    output = {"answer_diagnosis": {"answer_jobs": [{
        "answer_hash": hashlib.sha256(frozen_run["answer_text"].encode()).hexdigest(),
        "run_ids": [run_id], "status": "FAILED", "result_source": "UNKNOWN",
        "error": failure, "audit": {"response_source": "UNKNOWN",
            "raw_response_hash": "", "finish_reason": "unknown",
            "response_excerpt": "", "response_length": 0, "validation_errors": []},
        "semantic_input_hash": "f" * 64}], "events": []}}
    old_result = SinglePromptDiagnosisResult(result_version="diag-v1:pre-send-failed",
        diagnosis_id=old.diagnosis_id, version_number=1, parent_result_version=None,
        output_json=json.dumps(output), output_hash=digest(output),
        reviewable_set_hash=digest([]), limitations_json="[]", stats_json="{}")
    old.status = "READY_FOR_REVIEW"
    old.active_result_version = old_result.result_version
    old.external_llm_calls = 0
    old.llm_cache_hits = 0
    db.add(old_result)
    db.commit()
    ledger = tmp_path / "model-budget-v2.sqlite3"
    initialize(ledger, pricing_source=value["shared_budget"]["pricing_source"],
        pricing_checked_at=value["shared_budget"]["pricing_checked_at"])
    claimed = []

    class StopBeforeSend(Exception):
        pass

    def stop_before_send(_db, diagnosis_id):
        claimed.append(diagnosis_id)
        raise StopBeforeSend

    monkeypatch.setattr(runner, "claim_diagnosis", stop_before_send)
    kwargs = dict(db=db, manifest=value, ledger=ledger,
        checkpoint_dir=tmp_path / "checkpoints", manifest_sha="f" * 64,
        database=Path(str(db.get_bind().url.database)),
        e1_answer=SimpleNamespace(result_version="e1-result"),
        contribution=SimpleNamespace(contribution_id="e2", plan_hash="a" * 64))
    for _ in range(2):
        with pytest.raises(StopBeforeSend):
            _prepare_e3_answer(**kwargs)

    replacements = db.query(SinglePromptDiagnosisExecution).filter(
        SinglePromptDiagnosisExecution.analysis_id == row.analysis_id,
        SinglePromptDiagnosisExecution.idempotency_key.like("%:pre-send-recovery-v1:%")).all()
    db.refresh(old)
    assert len(replacements) == 1 and claimed == [replacements[0].diagnosis_id] * 2
    assert old.status == "READY_FOR_REVIEW" and old.active_result_version == old_result.result_version
    assert db.query(SinglePromptDiagnosisResult).filter_by(
        diagnosis_id=old.diagnosis_id).count() == 1
    assert e3["answer_prepare_recovery"]["supersedes_diagnosis_id"] == old.diagnosis_id
    assert e3["answer_prepare_recovery"]["superseding_diagnosis_id"] == replacements[0].diagnosis_id
    assert summary(ledger)["used_requests"] == 0


def test_e3_pre_send_recovery_rejects_any_delivery_or_non_configuration_failure(
        monkeypatch, tmp_path):
    import scripts.run_t23_delivery_live as runner

    ledger = tmp_path / "model-budget-v2.sqlite3"
    value = manifest()
    initialize(ledger, pricing_source=value["shared_budget"]["pricing_source"],
        pricing_checked_at=value["shared_budget"]["pricing_checked_at"])
    failure = "DEEPSEEK_API_KEY 未配置。请在 backend/.env 设置（代码与日志禁止输出该值）。"

    def evidence(**overrides):
        audit = {"response_source": "UNKNOWN", "raw_response_hash": ""}
        audit.update(overrides.pop("audit", {}))
        job = {"status": "FAILED", "run_ids": [3], "result_source": "UNKNOWN",
            "error": failure, "audit": audit}
        job.update(overrides.pop("job", {}))
        output = {"answer_diagnosis": {"answer_jobs": [job]}}
        diagnosis = SimpleNamespace(diagnosis_id="old-e3", status="READY_FOR_REVIEW",
            active_result_version="diag-v1:old", external_llm_calls=0, llm_cache_hits=0)
        for key, item in overrides.items():
            setattr(diagnosis, key, item)
        result = SimpleNamespace(result_version="diag-v1:old", output_json=json.dumps(output),
            output_hash=digest(output))
        return diagnosis, result

    diagnosis, result = evidence()
    assert _e3_pre_send_failure_provenance(diagnosis=diagnosis, result=result,
        selected_run_id=3, ledger=ledger)["ledger_request_count"] == 0
    rejected = [
        evidence(external_llm_calls=1),
        evidence(llm_cache_hits=1),
        evidence(audit={"response_source": "PROVIDER"}),
        evidence(audit={"raw_response_hash": "a" * 64}),
        evidence(job={"error": "provider timeout"}),
    ]
    for bad_diagnosis, bad_result in rejected:
        with pytest.raises(ValueError, match="PROVENANCE_NOT_PROVEN"):
            _e3_pre_send_failure_provenance(diagnosis=bad_diagnosis, result=bad_result,
                selected_run_id=3, ledger=ledger)
    monkeypatch.setattr(runner, "summary", lambda _ledger: {"requests": [{
        "request_id": "T23:E2E-03:prepare-answer:old-e3:sent", "status": "FINISHED"}]})
    with pytest.raises(ValueError, match="PROVENANCE_NOT_PROVEN"):
        _e3_pre_send_failure_provenance(diagnosis=diagnosis, result=result,
            selected_run_id=3, ledger=ledger)


def test_prepare_freezes_auditable_e3_no_signal_blocker_without_task_or_retry(
        scene, monkeypatch, tmp_path):
    from app.models import ReferenceSource, SinglePromptCitationManifest, SinglePromptSourceCompletionManifest
    import scripts.run_t23_delivery_live as runner

    db, row, _, _ = scene
    citation = db.query(SinglePromptCitationManifest).filter_by(analysis_id=row.analysis_id).one()
    completion = db.query(SinglePromptSourceCompletionManifest).filter_by(
        analysis_id=row.analysis_id, context_id=row.context_id).one()
    inputs = json.loads(row.input_json)
    run_id = inputs["run_ids"][0]
    for reference in db.query(ReferenceSource).filter_by(run_id=run_id).all():
        reference.canonical_url = reference.canonical_url or "https://example.test/real-citation"
        reference.canonical_url_hash = build_url_identity(reference.canonical_url).canonical_url_hash
    database = Path(str(db.get_bind().url.database))
    db.commit()
    db.close()
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()

    value = manifest()
    for case in value["scenarios"][:2]:
        case.update(task_id=row.task_id, project_id=row.project_id, prompt_id=row.prompt_id,
            analysis_id=row.analysis_id, context_id=row.context_id, input_hash=row.input_hash,
            run_ids=[run_id])
    value["scenarios"][0]["answer_prepare_input"] = {
        "citation_manifest_id": citation.manifest_id,
        "citation_manifest_hash": citation.payload_hash,
        "selected_run_id": run_id,
    }
    value["scenarios"][1]["prepare_input"] = {
        "citation_manifest_id": citation.manifest_id,
        "citation_manifest_hash": citation.payload_hash,
        "completion_manifest_id": completion.manifest_id,
        "completion_manifest_hash": completion.payload_hash,
        "selected_run_id": run_id,
    }
    value["scenarios"][1].pop("low_match_evidence")
    e3 = value["scenarios"][2]
    e3.update(project_id=row.project_id, prompt_id=row.prompt_id,
        analysis_id=row.analysis_id, context_id=row.context_id, run_ids=[run_id],
        task_pending_truth=True,
        unknown_prepare_input={"signal_selector": "UNIQUE_TARGET_BRAND_CAPABILITY",
            "source_reference": "isolated acceptance", "note": "verify independently",
            "reviewed_by": "acceptance-controller"})
    e3.pop("unknown_truth_evidence")
    value["source_database_sha256"] = hashlib.sha256(database.read_bytes()).hexdigest()
    input_manifest = tmp_path / "t23-no-e3-signal.json"
    input_manifest.write_text(json.dumps(value), encoding="utf-8")
    ledger = tmp_path / "model-budget-v2.sqlite3"
    initialize(ledger, pricing_source=value["shared_budget"]["pricing_source"],
        pricing_checked_at=value["shared_budget"]["pricing_checked_at"])
    simulated_delivery_transport(monkeypatch)
    monkeypatch.setattr(runner, "_extract_low_match", lambda *_:
        (_ for _ in ()).throw(ValueError("E2E-02 prepare produced no formal low-match result")))
    monkeypatch.setattr(runner, "_freeze_e2e03_unknown", lambda *_:
        (_ for _ in ()).throw(ValueError(
            "E2E-03_UNKNOWN_SIGNAL_REVIEW_REQUIRED: expected one exact target-brand capability signal, found 0")))

    def prepare_e3_without_signal(*, manifest, ledger, **_kwargs):
        case = next(item for item in manifest["scenarios"] if item["id"] == "E2E-03")
        case.update(max_requests=3, prepare_max_requests=1, execute_max_requests=2,
            answer_prepare_input={"citation_manifest_id": "citation-e3",
                "citation_manifest_hash": "b" * 64, "selected_run_id": run_id},
            answer_prepare_recovery={
                "contract_version": "t23-e3-pre-send-failure.v1",
                "supersedes_diagnosis_id": "diagnosis-e3-old",
                "superseded_result_version": "diagnosis-v1:e3-old",
                "superseded_result_hash": "e" * 64, "selected_run_id": run_id,
                "external_llm_calls": 0, "llm_cache_hits": 0, "ledger_request_count": 0,
                "job_status": "FAILED", "result_source": "UNKNOWN",
                "response_source": "UNKNOWN", "raw_response_hash": "",
                "error": "DEEPSEEK_API_KEY 未配置。请在 backend/.env 设置（代码与日志禁止输出该值）。",
                "superseding_diagnosis_id": "diagnosis-e3-no-signal",
                "superseding_idempotency_key":
                    f"{manifest['shared_budget']['budget_id']}:E2E-03:pre-send-recovery-v1:diagnosis-e3-old",
            })
        diagnosis = SimpleNamespace(diagnosis_id="diagnosis-e3-no-signal",
            project_id=row.project_id, prompt_id=row.prompt_id, analysis_id=row.analysis_id)
        output = {"input": {"brand_snapshot": {"brand_name": "Target", "aliases": []}},
            "answer_diagnosis": {"events": []}}
        result = SimpleNamespace(result_version="diagnosis-v1:e3-no-signal",
            output_json=json.dumps(output), output_hash=digest(output))
        guard, audit, _ = _hooks(ledger, scenario_id="E2E-03",
            task_id=f"prepare-answer:{diagnosis.diagnosis_id}")
        identity_value = {**identity(row), "input_hash": "c" * 64,
            "provider_payload_hash": "d" * 64, "attempt": 1}
        guard(identity_value)
        audit({"request_identity": identity_value, "validation_status": "ACCEPTED",
            "response_source": "PROVIDER", "response_model": "deepseek-flash"})
        return diagnosis, result

    monkeypatch.setattr(runner, "_prepare_e3_answer", prepare_e3_without_signal)
    frozen_path = tmp_path / "t23-partial-no-e3.json"
    report_path = tmp_path / "t23-partial-no-e3-report.json"
    report = prepare_and_freeze(database=database, ledger=ledger,
        manifest_path=input_manifest, frozen_manifest_path=frozen_path,
        report_path=report_path)

    frozen = validate_manifest(json.loads(frozen_path.read_text()))
    frozen_e3 = frozen["scenarios"][2]
    assert report["status"] == "PARTIAL_READY"
    assert report["scenario_blockers"]["E2E-02"]["code"] == "NO_FORMAL_LOW_MATCH"
    assert report["scenario_blockers"]["E2E-03"]["code"] == "NO_FORMAL_UNKNOWN_SIGNAL"
    assert "task_id" not in frozen_e3 and "input_hash" not in frozen_e3
    assert frozen_e3["answer_prepare_recovery"]["ledger_request_count"] == 0
    assert summary(ledger)["used_requests"] == 3
    assert len([item for item in summary(ledger)["requests"]
        if item["request_id"].startswith("T23:E2E-03:prepare-answer:")]) == 1
    checkpoint = _checkpoint_events(_checkpoint_dir(frozen_path))[-2]
    assert checkpoint["stage"] == "E2E03_UNKNOWN_FROZEN"
    assert checkpoint["e2e03_task_id"] is None and checkpoint["e2e03_input_hash"] is None
    assert checkpoint["e3_answer_prepare_recovery"]["supersedes_diagnosis_id"] == "diagnosis-e3-old"

    calls = []
    fake_db = SimpleNamespace()
    monkeypatch.setattr(runner, "_inspect_task", lambda _db, case, phase:
        {"revision": 1, "input_hash": case["input_hash"]})
    fake_db.query = lambda *_: SimpleNamespace(filter_by=lambda **kwargs:
        SimpleNamespace(one=lambda: SimpleNamespace(task_id=kwargs["task_id"])))
    fake_db.expire_all = lambda: None
    fake_db.rollback = lambda: None
    monkeypatch.setattr(runner, "authorize_task", lambda _db, task, **kwargs:
        calls.append(("authorize", task.task_id)))
    monkeypatch.setattr(runner, "execute_task", lambda task_id, **kwargs:
        calls.append(("execute", task_id)))
    results = _execute_planned_scenarios(fake_db, None, frozen, ledger)
    assert [item["status"] for item in results] == ["PASS", "BLOCKED", "BLOCKED"]
    assert all(task_id == frozen["scenarios"][0]["task_id"] for _, task_id in calls)
    assert summary(ledger)["used_requests"] == 3


def test_prepare_resume_blocks_counted_contribution_without_repeating_send(scene, monkeypatch, tmp_path):
    from app.models import ReferenceSource, SinglePromptCitationManifest, SinglePromptSourceCompletionManifest

    db, row, _, _ = scene
    citation = db.query(SinglePromptCitationManifest).filter_by(analysis_id=row.analysis_id).one()
    completion = db.query(SinglePromptSourceCompletionManifest).filter_by(
        analysis_id=row.analysis_id, context_id=row.context_id).one()
    run_id = json.loads(row.input_json)["run_ids"][0]
    for reference in db.query(ReferenceSource).filter_by(run_id=run_id).all():
        reference.canonical_url = reference.canonical_url or "https://example.test/real-citation"
        reference.canonical_url_hash = build_url_identity(reference.canonical_url).canonical_url_hash
    database = Path(str(db.get_bind().url.database))
    db.commit()
    db.close()
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()

    value = manifest()
    for case in value["scenarios"][:2]:
        case.update(task_id=row.task_id, project_id=row.project_id, prompt_id=row.prompt_id,
            analysis_id=row.analysis_id, context_id=row.context_id, input_hash=row.input_hash,
            run_ids=[run_id])
    value["scenarios"][0]["answer_prepare_input"] = {"citation_manifest_id": citation.manifest_id,
        "citation_manifest_hash": citation.payload_hash, "selected_run_id": run_id}
    value["scenarios"][1]["prepare_input"] = {"citation_manifest_id": citation.manifest_id,
        "citation_manifest_hash": citation.payload_hash, "completion_manifest_id": completion.manifest_id,
        "completion_manifest_hash": completion.payload_hash, "selected_run_id": run_id}
    value["scenarios"][1].pop("low_match_evidence")
    value["source_database_sha256"] = hashlib.sha256(database.read_bytes()).hexdigest()
    input_manifest = tmp_path / "t23-prepare-failure.json"
    input_manifest.write_text(json.dumps(value), encoding="utf-8")
    ledger = tmp_path / "model-budget-v2.sqlite3"
    initialize(ledger, pricing_source=value["shared_budget"]["pricing_source"],
        pricing_checked_at=value["shared_budget"]["pricing_checked_at"])
    sends = []
    def fail_contribution(payload):
        sends.append(payload)
        if "frozen_candidate_pairs" in payload:
            raise TimeoutError("simulated unknown delivery")
    simulated_delivery_transport(monkeypatch, on_request=fail_contribution)
    import scripts.run_t23_delivery_live as runner
    def provider_send_without_persisting_result(_contribution_id, *, session_factory, judge):
        judge.judge(
            [{"answer_unit_id": "answer-1", "raw_text": "测试答案", "primary_type": "OTHER",
              "semantic_facets": []}],
            [{"passage_id": "passage-1", "text": "测试来源"}],
            [{"answer_unit_id": "answer-1", "passage_id": "passage-1"}],
        )
    monkeypatch.setattr(runner, "execute_citation_contribution", provider_send_without_persisting_result)
    frozen_path = tmp_path / "never-frozen.json"

    with pytest.raises(Exception) as first_failure:
        prepare_and_freeze(database=database, ledger=ledger, manifest_path=input_manifest,
            frozen_manifest_path=frozen_path, report_path=tmp_path / "failure-report.json")
    assert len(sends) == 2
    state = summary(ledger)
    assert state["used_requests"] == 2
    assert state["requests"][-1]["status"] in {"TIMEOUT", "DELIVERY_UNKNOWN", "FAILED"}
    checkpoints = _checkpoint_events(_checkpoint_dir(frozen_path))
    assert checkpoints[-1]["stage"] == "PREPARE_BLOCKED_DURABLE", str(first_failure.value)
    assert checkpoints[-1]["answer_result_hash"]
    assert checkpoints[-1]["contribution_id"]

    with pytest.raises(ValueError, match="PREPARE_RESUME_BLOCKED_COUNTED_WITHOUT_CONTRIBUTION_RESULT"):
        prepare_and_freeze(database=database, ledger=ledger, manifest_path=input_manifest,
            frozen_manifest_path=frozen_path, report_path=tmp_path / "resume-report.json")
    assert len(sends) == 2
    assert summary(ledger)["used_requests"] == 2


def test_shared_guard_refuses_unfrozen_answer_transport_identity(scene, tmp_path):
    _, row, _, _ = scene
    ledger = tmp_path / "model-budget-v2.sqlite3"
    initialize(ledger, pricing_source="operator-verified-provider-pricing",
        pricing_checked_at=datetime.now(timezone.utc).date().isoformat())
    request_guard, _audit_sink, _settle_unknown = _hooks(
        ledger, scenario_id="E2E-01", task_id=row.task_id)
    request = {**identity(row), "effective_request_model": "deepseek-v4-flash",
        "input_hash": "a" * 64, "provider_payload_hash": "b" * 64, "attempt": 1}
    with pytest.raises(SemanticLLMError,
            match="SEMANTIC_CONTRACT_REVIEW_REQUIRED:ANSWER_TRANSPORT_IDENTITY_UNFROZEN"):
        request_guard(request)
    assert summary(ledger)["used_requests"] == 0
