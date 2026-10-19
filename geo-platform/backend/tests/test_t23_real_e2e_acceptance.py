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
    _verify_delivery,
    validate_manifest,
)
from scripts.live_model_budget import finish, initialize, reserve, summary
from scripts.run_t23_delivery_live import (
    _assert_ledger,
    _checkpoint_dir,
    _checkpoint_events,
    _execute_planned_scenarios,
    _extract_low_match,
    _freeze_manifest_value,
    _hooks,
    _write_initial_database_snapshot,
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
    planned = [{"revision": 1, "input_hash": case["input_hash"]} for case in value["scenarios"]]

    results = _execute_planned_scenarios(db, object, value, tmp_path / "unused.sqlite3", planned)

    assert calls == ["task-E2E-01", "task-E2E-02", "task-E2E-03"]
    assert [row["status"] for row in results] == ["BLOCKED", "PASS", "PASS"]
    assert db.rollbacks == 1


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
