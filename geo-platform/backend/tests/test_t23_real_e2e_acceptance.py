from datetime import datetime, timezone
import copy
import hashlib
import json

import pytest
from sqlalchemy.orm import sessionmaker

from scripts.t23_real_e2e_acceptance import (
    CONTRACT,
    _authorization,
    _low_match_summary,
    _verify_delivery,
    validate_manifest,
)
from scripts.live_model_budget import initialize, summary
from scripts.run_t23_delivery_live import _hooks
from test_automatic_delivery import identity, scene, simulated_delivery_transport
from app.modules.single_prompt_v2.automatic_delivery import (
    authorize_task,
    execute_task,
    scoped_client,
    shared_live_budget_hooks,
    task_view,
)
from app.services.semantic_llm.base import SemanticLLMError
from app.modules.single_prompt_v2.delivery_text import digest


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
            "prompt_id": index,
            "analysis_id": f"analysis-{index}",
            "context_id": f"context-{index}",
            "input_hash": str(index) * 64,
            "run_ids": [index],
            "max_requests": {"E2E-01": 4, "E2E-02": 3, "E2E-03": 2}[scenario],
            "max_tokens": 300_000,
            "max_cost_cny": 10,
            **({"low_match_evidence": {
                "contribution_id": "contribution-low-match",
                "result_version": "contribution-v1:low-match",
                "result_hash": "b" * 64,
                "selected_run_id": 2,
                "citation_id": "citation-real-2",
                "reference_id": 22,
                "source_key": "source-real-2",
                "canonical_url_hash": "c" * 64,
                "citation_disposition": "NO_BINDING_FOUND_AFTER_SEARCH",
                "evaluation_id": "evaluation-low-match",
                "evaluation_hash": "d" * 64,
                "evidence_relation": "NO_MATCH",
            }} if scenario == "E2E-02" else {}),
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


def test_authorization_payload_is_exact_task_revision_and_controller_allocation():
    value = manifest()
    payload = _authorization(value["scenarios"][0], {"revision": 7, "input_hash": "f" * 64}, value["shared_budget"])
    assert payload == {
        "expected_revision": 7,
        "input_hash": "f" * 64,
        "max_requests": 4,
        "max_tokens": 300_000,
        "max_cost_cny": 10,
        "conservative_cny_per_million_tokens": 10,
        "pricing_source": "operator-verified-provider-pricing",
        "pricing_checked_at": datetime.now(timezone.utc).date().isoformat(),
        "authorized_by": "acceptance-controller",
    }


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
        reference.canonical_url_hash = hashlib.sha256(reference.canonical_url.encode()).hexdigest()
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
        "low_match_evidence": low_match}
    assert _low_match_summary(db, case, json.loads(row.input_json))["evaluation_id"] == evaluation["evaluation_id"]

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
