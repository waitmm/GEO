"""Affected-only delivery regeneration after answer/relation strategy reprojection."""
from __future__ import annotations

import copy
from datetime import datetime
import json

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.models import (
    SinglePromptExecutionProposal,
    SinglePromptExecutionProposalResult,
    SinglePromptOptimizationTask,
    SinglePromptStrategyResult,
)
from app.modules.single_prompt_v2.answer_relation_corrections import (
    _affected_delivery_regeneration_plan,
    create_reprojection_task,
    preview_correction,
    save_correction,
)
from app.modules.single_prompt_v2.automatic_delivery import authorize_task, execute_task, task_view
from app.modules.single_prompt_v2.delivery_text import digest
from test_automatic_delivery import scene
from test_delivery_answer_relation_corrections import _event_values
from test_delivery_answer_relation_reprojection import _client
from test_delivery_truth_corrections import fact_delivery


def _completed_reprojection(db, parent, factory):
    _, _, values = _event_values(db, parent)
    preview = preview_correction(db, **values)
    correction = save_correction(
        db, **values, actor="local-owner", preview_hash=preview["preview_hash"],
    )
    task, created = create_reprojection_task(
        db, parent_task_id=parent.task_id, project_id=1, prompt_id=44,
        correction_result_version=correction["result_version"],
        correction_result_hash=correction["result_hash"],
        idempotency_key="answer-relation-strategy-reprojection",
        requested_by="local-owner",
    )
    assert created
    execute_task(task.task_id, session_factory=factory)
    db.refresh(task)
    assert task.status == "COMPLETED_WITH_LIMITATIONS", task.blocker_detail
    manifest = task_view(task)["objects"]["answer_relation_reprojection"]
    assert manifest["affected_delivery_set_hash"] == digest(manifest["pending_delivery_updates"])
    assert manifest["affected_delivery_regeneration_plan"]
    return task, manifest


def _payload(task, manifest, key="affected-delivery-regeneration:one"):
    affected = sorted(manifest["pending_delivery_updates"],
        key=lambda row: (row["strategy_id"], row["proposal_id"], row["result_version"], row["result_hash"]))
    return {
        "project_id": 1,
        "prompt_id": 44,
        "expected_revision": task.revision,
        "strategy_result_version": manifest["new_strategy_result_version"],
        "strategy_result_hash": manifest["new_strategy_result_hash"],
        "affected_delivery_set_hash": manifest["affected_delivery_set_hash"],
        "idempotency_key": key,
    }


def test_affected_regeneration_waits_without_delivery_write_then_uses_new_strategy(fact_delivery):
    db, original, _, calls, _, _ = fact_delivery
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    reprojection, projected = _completed_reprojection(db, original, factory)
    client = _client(db)
    url = f"/api/v2/single-prompt/optimization-tasks/{reprojection.task_id}/affected-draft-regenerations"

    created = client.post(url, json=_payload(reprojection, projected))
    assert created.status_code == 201, created.text
    view = created.json()
    assert view["task_kind"] == "ANSWER_RELATION_DELIVERY_REGENERATION"
    assert view["authorization"] == {
        "max_cost_cny": 0, "max_requests": 0, "max_tokens": 0, "policy": "CACHE_ONLY",
    }
    duplicate = client.post(url, json=_payload(reprojection, projected))
    assert duplicate.status_code == 200
    assert duplicate.json()["task_id"] == view["task_id"]
    forged = client.post(url, json={**_payload(reprojection, projected), "actor": "forged"})
    assert forged.status_code == 422

    child = db.query(SinglePromptOptimizationTask).filter_by(task_id=view["task_id"]).one()
    parent_bytes = (original.input_json, original.progress_json, reprojection.input_json, reprojection.progress_json)
    old_results = {
        (row.proposal_id, row.result_version): (row.output_json, row.output_hash)
        for row in db.query(SinglePromptExecutionProposalResult)
    }
    old_proposals = {row.proposal_id for row in db.query(SinglePromptExecutionProposal)}
    call_count = len(calls)
    # execute_task owns claim/error mapping; the public assertion below verifies that mapping.
    execute_task(child.task_id, session_factory=factory)
    db.refresh(child)
    assert child.status == "WAITING_AUTHORIZATION", child.blocker_detail
    assert child.blocker_code == "CACHE_MISS"
    assert len(calls) == call_count
    assert {row.proposal_id for row in db.query(SinglePromptExecutionProposal)} == old_proposals
    assert {(row.proposal_id, row.result_version) for row in db.query(SinglePromptExecutionProposalResult)} == set(old_results)

    authorize_task(
        db, child, expected_revision=child.revision, input_hash=child.input_hash,
        max_requests=2, max_tokens=400000, max_cost_cny=4,
        conservative_cny_per_million_tokens=10,
        pricing_source="isolated-fixture-not-real-billing",
        pricing_checked_at=datetime.utcnow().date().isoformat(), authorized_by="local-owner",
    )
    execute_task(child.task_id, session_factory=factory)
    db.refresh(child)
    view = task_view(child)
    assert child.status == "COMPLETED", (child.blocker_code, child.blocker_detail)
    manifest = view["objects"]["answer_relation_delivery_regeneration"]
    assert manifest["strategy_result_version"] == projected["new_strategy_result_version"]
    assert manifest["strategy_result_hash"] == projected["new_strategy_result_hash"]
    assert manifest["affected_deliveries"] == sorted(projected["pending_delivery_updates"],
        key=lambda row: (row["strategy_id"], row["proposal_id"], row["result_version"], row["result_hash"]))
    assert manifest["unchanged_deliveries"] == sorted(projected["unchanged_deliveries"],
        key=lambda row: (row["strategy_id"], row["proposal_id"], row["result_version"], row["result_hash"]))
    assert manifest["pending_deliveries"] == []
    assert manifest["failed_deliveries"] == []
    assert manifest["deliveries_regenerated"] is True
    assert manifest["regenerated_deliveries"]
    for binding in manifest["regenerated_deliveries"]:
        proposal = db.query(SinglePromptExecutionProposal).filter_by(
            proposal_id=binding["proposal_id"], strategy_id=projected["new_strategy_id"],
            strategy_result_version=projected["new_strategy_result_version"],
            strategy_result_hash=projected["new_strategy_result_hash"],
        ).one()
        result = db.query(SinglePromptExecutionProposalResult).filter_by(
            proposal_id=proposal.proposal_id, result_version=binding["result_version"],
            output_hash=binding["result_hash"],
        ).one()
        output = json.loads(result.output_json)
        assert output["delivery_input"]["identity"]["strategy_id"] == projected["new_strategy_id"]
    assert view["usage"]["external_requests"] == 2
    assert view["usage"]["actual_tokens"] > 0

    db.refresh(original); db.refresh(reprojection)
    assert (original.input_json, original.progress_json, reprojection.input_json, reprojection.progress_json) == parent_bytes
    for identity, previous in old_results.items():
        row = db.query(SinglePromptExecutionProposalResult).filter_by(
            proposal_id=identity[0], result_version=identity[1],
        ).one()
        assert (row.output_json, row.output_hash) == previous


def test_http_authorization_is_principal_owned_and_bounded_by_frozen_affected_set(fact_delivery):
    db, original, _, calls, _, _ = fact_delivery
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    reprojection, projected = _completed_reprojection(db, original, factory)
    client = _client(db)
    queue_url = f"/api/v2/single-prompt/optimization-tasks/{reprojection.task_id}/affected-draft-regenerations"
    created = client.post(queue_url, json=_payload(
        reprojection, projected, "affected-delivery-regeneration:authorization",
    ))
    assert created.status_code == 201, created.text
    child = db.query(SinglePromptOptimizationTask).filter_by(task_id=created.json()["task_id"]).one()
    frozen = json.loads(child.input_json)["answer_relation_delivery_regeneration"]
    affected_count = len(frozen["affected_deliveries"])
    assert affected_count > 0
    assert len(frozen["delivery_regeneration_plan"]) == affected_count

    historical_bytes = (original.input_json, original.progress_json,
                        reprojection.input_json, reprojection.progress_json)
    result_bytes = {
        (row.proposal_id, row.result_version): (row.output_json, row.output_hash)
        for row in db.query(SinglePromptExecutionProposalResult)
    }
    call_count = len(calls)
    authorization_url = f"/api/v2/single-prompt/optimization-tasks/{child.task_id}/authorization"
    payload = {
        "project_id": 1,
        "prompt_id": 44,
        "expected_revision": child.revision,
        "input_hash": child.input_hash,
        "max_requests": 2 * affected_count,
        "max_tokens": 400000,
        "max_cost_cny": 4,
        "conservative_cny_per_million_tokens": 10,
        "pricing_source": "isolated-fixture-not-real-billing",
        "pricing_checked_at": datetime.utcnow().date().isoformat(),
    }
    zero = client.post(authorization_url, json={**payload, "max_requests": 0})
    assert zero.status_code == 422, zero.text
    excessive = client.post(authorization_url, json={
        **payload, "max_requests": 2 * affected_count + 1,
    })
    assert excessive.status_code == 422, excessive.text
    stale_revision = client.post(authorization_url, json={
        **payload, "expected_revision": child.revision + 1,
    })
    assert stale_revision.status_code == 409, stale_revision.text
    stale_hash = client.post(authorization_url, json={**payload, "input_hash": "0" * 64})
    assert stale_hash.status_code == 409, stale_hash.text
    forged = client.post(authorization_url, json={**payload, "actor": "forged-owner"})
    assert forged.status_code == 422, forged.text

    initial_status = child.status
    for forbidden_status in ("RUNNING", "CANCELLED"):
        child.status = forbidden_status
        db.commit()
        forbidden = client.post(authorization_url, json=payload)
        assert forbidden.status_code == 409, forbidden.text
    child.status = initial_status
    db.commit()

    authorized = client.post(authorization_url, json=payload)
    assert authorized.status_code == 200, authorized.text
    view = authorized.json()
    assert view["authorization"]["max_requests"] == 2 * affected_count
    assert view["authorization"]["authorized_by"]
    assert view["authorization"]["authorized_by"] != "forged-owner"
    db.refresh(child)
    repeated = client.post(authorization_url, json={**payload, "expected_revision": child.revision})
    assert repeated.status_code == 409, repeated.text

    assert len(calls) == call_count
    db.refresh(original); db.refresh(reprojection)
    assert (original.input_json, original.progress_json,
            reprojection.input_json, reprojection.progress_json) == historical_bytes
    assert {
        (row.proposal_id, row.result_version): (row.output_json, row.output_hash)
        for row in db.query(SinglePromptExecutionProposalResult)
    } == result_bytes


def test_queue_rejects_stale_strategy_revision_set_hash_scope_and_idempotency(fact_delivery):
    db, original, _, _, _, _ = fact_delivery
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    reprojection, projected = _completed_reprojection(db, original, factory)
    client = _client(db)
    url = f"/api/v2/single-prompt/optimization-tasks/{reprojection.task_id}/affected-draft-regenerations"
    body = _payload(reprojection, projected, "affected-delivery-regeneration:fixed")
    assert client.post(url, json=body).status_code == 201
    invalid = [
        {"expected_revision": reprojection.revision + 1},
        {"strategy_result_version": "stale-version"},
        {"strategy_result_hash": "0" * 64},
        {"affected_delivery_set_hash": digest(projected["pending_delivery_updates"][:0])},
        {"project_id": 999},
    ]
    for index, change in enumerate(invalid):
        response = client.post(url, json={**body, **change,
            "idempotency_key": f"affected-delivery-regeneration:invalid:{index}"})
        assert response.status_code in {403, 404, 409}, response.text
    conflict = client.post(url, json={**body, "strategy_result_hash": "0" * 64})
    assert conflict.status_code == 409


def test_multi_affected_delivery_plan_is_exact_one_to_one(fact_delivery):
    db, original, _, _, _, _ = fact_delivery
    objects = task_view(original)["objects"]
    old = db.query(SinglePromptStrategyResult).filter_by(
        strategy_id=objects["strategy_id"], result_version=objects["strategy_result_version"],
    ).one()
    template = json.loads(old.output_json)["directions"][0]
    old_directions, new_directions, affected = [], [], []
    for index in range(2):
        reason_id = f"reason-{index}"
        prior = copy.deepcopy(template)
        prior.update(strategy_id=f"old-{index}", direction_id=f"old-{index}",
                     reason_id=reason_id, reason_ids=[reason_id])
        projected = copy.deepcopy(template)
        projected.update(strategy_id=f"new-{index}", direction_id=f"new-{index}",
                         reason_id=reason_id, reason_ids=[reason_id])
        old_directions.append(prior)
        new_directions.append(projected)
        affected.append({"proposal_id": f"proposal-{index}", "strategy_id": f"old-{index}",
                         "result_version": f"result-{index}", "result_hash": str(index) * 64})
    old_output = {**json.loads(old.output_json), "directions": old_directions}
    old_hash = digest(old_output)
    synthetic = SinglePromptStrategyResult(
        result_version=f"strategy-plan-test:{old_hash[:16]}", strategy_id=old.strategy_id,
        version_number=old.version_number + 50, parent_result_version=old.result_version,
        output_json=json.dumps(old_output, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        output_hash=old_hash, reviewable_set_hash=old.reviewable_set_hash,
        limitations_json=old.limitations_json,
    )
    db.add(synthetic); db.commit()
    ref = {"fixed_strategy": {"strategy_id": old.strategy_id,
        "result_version": synthetic.result_version, "result_hash": synthetic.output_hash},
        "impact": {"affected_deliveries": affected}}
    plan = _affected_delivery_regeneration_plan(db, ref, {"directions": new_directions})
    assert [(row["affected_delivery"]["proposal_id"], row["new_direction_id"]) for row in plan] == [
        ("proposal-0", "new-0"), ("proposal-1", "new-1"),
    ]
    with pytest.raises(HTTPException, match="数量不一致"):
        _affected_delivery_regeneration_plan(db, ref, {"directions": new_directions[:1]})
    with pytest.raises(HTTPException, match="额外方向|唯一"):
        mismatched = copy.deepcopy(new_directions)
        mismatched[1]["reason_id"] = mismatched[1]["reason_ids"] = "different"
        _affected_delivery_regeneration_plan(db, ref, {"directions": mismatched})
