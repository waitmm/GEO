"""Independent contract for scoped strategy reprojection after answer/relation correction."""
from __future__ import annotations

import json

from fastapi import Depends, FastAPI
from sqlalchemy.orm import sessionmaker

from app.core.release_access import install_access, require_project_access
from app.models import (
    SinglePromptCitationContributionResult,
    SinglePromptDiagnosisResult,
    SinglePromptExecutionProposalResult,
    SinglePromptOptimizationTask,
    SinglePromptStrategyResult,
)
from app.modules.single_prompt_v2.answer_relation_corrections import (
    preview_correction,
    save_correction,
)
from app.modules.single_prompt_v2.automatic_delivery import execute_task, task_view
from app.modules.single_prompt_v2.release_api import get_db, router
from release_test_client import TestClient
from test_automatic_delivery import scene
from test_delivery_answer_relation_corrections import _event_values
from test_delivery_truth_corrections import fact_delivery


def _snapshot(db, model):
    return {
        (getattr(row, "proposal_id", None), row.result_version): (row.output_json, row.output_hash)
        for row in db.query(model).all()
    }


def _save_current_correction(db, parent):
    _, _, values = _event_values(db, parent)
    preview = preview_correction(db, **values)
    return save_correction(
        db, **values, actor="local-owner", preview_hash=preview["preview_hash"],
    )


def _client(db):
    app = FastAPI()
    install_access(app, ["http://127.0.0.1:5173"])
    app.include_router(router, dependencies=[Depends(require_project_access)])
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 8000))


def _queue(client, parent, correction, key="answer-relation-reproject:one"):
    return client.post(
        f"/api/v2/single-prompt/optimization-tasks/{parent.task_id}/answer-relation-reprojections",
        json={
            "project_id": 1,
            "prompt_id": 44,
            "correction_result_version": correction["result_version"],
            "correction_result_hash": correction["result_hash"],
            "idempotency_key": key,
        },
    )


def test_http_queue_freezes_current_correction_impact_and_is_idempotent(fact_delivery):
    db, parent, _, calls, _, _ = fact_delivery
    correction = _save_current_correction(db, parent)
    client = _client(db)

    created = _queue(client, parent, correction)
    assert created.status_code == 201, created.text
    view = created.json()
    assert view["task_kind"] == "ANSWER_RELATION_REPROJECTION"
    assert view["status"] == "QUEUED"
    assert view["authorization"]["policy"] == "CACHE_ONLY"
    assert view["authorization"]["max_requests"] == 0
    assert view["authorization"]["max_tokens"] == 0
    row = db.query(SinglePromptOptimizationTask).filter_by(task_id=view["task_id"]).one()
    fixed = json.loads(row.input_json)
    scope = fixed["answer_relation_correction"]
    assert scope["parent_task_id"] == parent.task_id
    assert scope["parent_input_hash"] == parent.input_hash
    assert scope["correction_result_version"] == correction["result_version"]
    assert scope["correction_result_hash"] == correction["result_hash"]
    assert scope["impact"] == correction["impact"]
    assert fixed["source_fetch_authorized"] is False
    assert len(calls) > 0  # Parent fixture is a real completed simulated delivery.

    repeated = _queue(client, parent, correction)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["task_id"] == view["task_id"]
    forged = client.post(
        f"/api/v2/single-prompt/optimization-tasks/{parent.task_id}/answer-relation-reprojections",
        json={
            "project_id": 1, "prompt_id": 44,
            "correction_result_version": correction["result_version"],
            "correction_result_hash": correction["result_hash"],
            "idempotency_key": "answer-relation-reproject:forged", "actor": "forged-form-actor",
        },
    )
    assert forged.status_code == 422


def test_worker_reprojects_strategy_only_and_preserves_parent_evidence_and_deliveries(fact_delivery):
    db, parent, _, calls, _, _ = fact_delivery
    correction = _save_current_correction(db, parent)
    client = _client(db)
    created = _queue(client, parent, correction)
    assert created.status_code == 201, created.text
    child = db.query(SinglePromptOptimizationTask).filter_by(task_id=created.json()["task_id"]).one()

    parent_bytes = (parent.input_json, parent.progress_json)
    diagnosis = _snapshot(db, SinglePromptDiagnosisResult)
    contributions = _snapshot(db, SinglePromptCitationContributionResult)
    deliveries = _snapshot(db, SinglePromptExecutionProposalResult)
    old_strategies = _snapshot(db, SinglePromptStrategyResult)
    call_count = len(calls)
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)

    execute_task(child.task_id, session_factory=factory)
    db.refresh(child)
    view = task_view(child)
    assert child.status == "COMPLETED_WITH_LIMITATIONS", (child.blocker_code, child.blocker_detail)
    assert len(calls) == call_count
    assert view["usage"]["external_requests"] == 0
    assert view["usage"]["actual_tokens"] == 0
    manifest = view["objects"]["answer_relation_reprojection"]
    assert manifest["correction_result_version"] == correction["result_version"]
    assert manifest["new_strategy_result_version"]
    assert manifest["affected_strategy_ids"] == correction["impact"]["affected_strategy_ids"]
    assert manifest["unaffected_strategy_ids"] == correction["impact"]["unaffected_strategy_ids"]
    assert manifest["pending_delivery_updates"] == correction["impact"]["affected_deliveries"]
    assert manifest["unchanged_deliveries"] == correction["impact"]["unaffected_deliveries"]
    assert manifest["deliveries_regenerated"] is False

    db.refresh(parent)
    assert (parent.input_json, parent.progress_json) == parent_bytes
    assert _snapshot(db, SinglePromptDiagnosisResult) == diagnosis
    assert _snapshot(db, SinglePromptCitationContributionResult) == contributions
    assert _snapshot(db, SinglePromptExecutionProposalResult) == deliveries
    assert set(old_strategies).issubset(_snapshot(db, SinglePromptStrategyResult))


def test_queue_rejects_wrong_scope_hash_idempotency_and_stale_correction(fact_delivery):
    db, parent, _, _, _, _ = fact_delivery
    first = _save_current_correction(db, parent)
    client = _client(db)
    assert _queue(client, parent, first, "answer-relation-reproject:fixed").status_code == 201

    wrong_hash = {**first, "result_hash": "0" * 64}
    assert _queue(client, parent, wrong_hash, "answer-relation-reproject:wrong-hash").status_code == 409
    cross_project = client.post(
        f"/api/v2/single-prompt/optimization-tasks/{parent.task_id}/answer-relation-reprojections",
        json={
            "project_id": 999, "prompt_id": 44,
            "correction_result_version": first["result_version"],
            "correction_result_hash": first["result_hash"],
            "idempotency_key": "answer-relation-reproject:cross-project",
        },
    )
    assert cross_project.status_code in {403, 404}

    second = _save_current_correction(db, parent)
    assert _queue(client, parent, first, "answer-relation-reproject:stale").status_code == 409
    reused_key = _queue(client, parent, second, "answer-relation-reproject:fixed")
    assert reused_key.status_code == 409
