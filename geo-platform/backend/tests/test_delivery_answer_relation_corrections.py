"""Formal Optimize entry for append-only answer and evaluated-relation corrections."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from pydantic import ValidationError

from app.models import (
    SinglePromptCitationContributionResult,
    SinglePromptDiagnosisExecution,
    SinglePromptDiagnosisResult,
    SinglePromptExecutionProposal,
    SinglePromptExecutionProposalResult,
    SinglePromptStrategyResult,
)
from app.modules.single_prompt_v2 import answer_relation_corrections as corrections
from app.core.release_access import authenticated_actor
from app.release_main import create_release_app
from app.modules.single_prompt_v2.answer_relation_corrections import (
    correction_status, preview_correction, save_correction,
)
from app.modules.single_prompt_v2.automatic_delivery import task_view
from app.modules.single_prompt_v2.schemas import AnswerRelationCorrectionCreate
from test_delivery_truth_corrections import fact_delivery
from test_automatic_delivery import scene
from test_single_prompt_v2_diagnosis import _compute, _ready_analysis, _seed, _session


def _snapshot(rows):
    return {row.result_version: (row.output_json, row.output_hash) for row in rows}


def _event_values(db, task):
    status = correction_status(db, task_id=task.task_id, project_id=1, prompt_id=44)
    target = next(row for row in status["targets"] if row["target_type"] == "RECOMMENDATION_EVENT")
    return status, target, dict(
        task_id=task.task_id, project_id=1, prompt_id=44,
        base_result_version=status["base_result_version"], base_result_hash=status["base_result_hash"],
        reviewable_set_hash=status["reviewable_set_hash"], target_type=target["target_type"],
        target_id=target["target_id"], target_hash=target["target_hash"],
        value=next(value for value in target["allowed_values"] if value != target["current_value"]),
        reason="明确的人工核对依据",
    )


def test_answer_behavior_correction_is_task_scoped_append_only_and_preserves_delivery(fact_delivery):
    db, task, _, calls, _, _ = fact_delivery
    status = correction_status(db, task_id=task.task_id, project_id=1, prompt_id=44)
    event = next(row for row in status["targets"] if row["target_type"] == "RECOMMENDATION_EVENT")
    replacement = next(value for value in event["allowed_values"] if value != event["current_value"])
    values = dict(
        task_id=task.task_id, project_id=1, prompt_id=44,
        base_result_version=status["base_result_version"], base_result_hash=status["base_result_hash"],
        reviewable_set_hash=status["reviewable_set_hash"], target_type=event["target_type"],
        target_id=event["target_id"], target_hash=event["target_hash"], value=replacement,
        reason="人工核对原回答后，确认机器识别的推荐行为不准确",
    )
    task_bytes = (task.input_json, task.progress_json)
    original_result = db.query(SinglePromptDiagnosisResult).filter_by(
        result_version=status["frozen_result_version"]).one()
    original_bytes = (original_result.output_json, original_result.output_hash)
    strategies = _snapshot(db.query(SinglePromptStrategyResult).all())
    deliveries = _snapshot(db.query(SinglePromptExecutionProposalResult).all())
    contributions = _snapshot(db.query(SinglePromptCitationContributionResult).all())
    request_count = len(calls)

    preview = preview_correction(db, **values)
    assert preview["impact"]["affected_reason_ids"] == event["reason_ids"]
    assert set(preview["impact"]["affected_strategy_ids"] + preview["impact"]["unaffected_strategy_ids"])
    assert preview["impact"]["recompute_task_created"] is False
    assert preview["impact"]["external_calls"] == 0
    saved = save_correction(db, **values, actor="actual-release-operator", preview_hash=preview["preview_hash"])

    assert saved["parent_result_version"] == status["base_result_version"]
    assert saved["actor"] == "actual-release-operator"
    assert db.query(SinglePromptDiagnosisResult).count() >= 2
    db.refresh(original_result); db.refresh(task)
    assert (original_result.output_json, original_result.output_hash) == original_bytes
    assert (task.input_json, task.progress_json) == task_bytes
    assert _snapshot(db.query(SinglePromptStrategyResult).all()) == strategies
    assert _snapshot(db.query(SinglePromptExecutionProposalResult).all()) == deliveries
    assert _snapshot(db.query(SinglePromptCitationContributionResult).all()) == contributions
    assert len(calls) == request_count
    refreshed = correction_status(db, task_id=task.task_id, project_id=1, prompt_id=44)
    assert refreshed["base_result_version"] == saved["result_version"]
    assert refreshed["history"][-1]["actor"] == "actual-release-operator"
    assert refreshed["history"][-1]["impact"] == preview["impact"]


def test_formal_entry_rejects_wrong_scope_stale_hash_target_and_empty_basis(fact_delivery):
    db, task, _, _, _, _ = fact_delivery
    _, _, base = _event_values(db, task)
    for change in (
        {"project_id": 999}, {"prompt_id": 999}, {"base_result_hash": "0" * 64},
        {"reviewable_set_hash": "0" * 64}, {"target_id": "wrong-object"},
        {"target_hash": "0" * 64}, {"reason": "   "},
    ):
        with pytest.raises(HTTPException):
            preview_correction(db, **{**base, **change})
    preview = preview_correction(db, **base)
    with pytest.raises(HTTPException, match="预览已变化"):
        save_correction(db, **base, actor="actual-release-operator", preview_hash="0" * 64)
    assert correction_status(db, task_id=task.task_id, project_id=1, prompt_id=44)["history"] == []


def test_non_success_terminal_task_rejects_read_preview_and_save(fact_delivery):
    db, task, _, _, _, _ = fact_delivery
    _, _, values = _event_values(db, task)
    preview = preview_correction(db, **values)
    for task_status in ("QUEUED", "RUNNING", "WAITING_AUTHORIZATION", "INTERRUPTED", "BLOCKED", "CANCELLED"):
        task.status = task_status
        task.revision += 1
        db.commit()
        calls = (
            lambda: correction_status(db, task_id=task.task_id, project_id=1, prompt_id=44),
            lambda: preview_correction(db, **values),
            lambda: save_correction(db, **values, actor="actual-release-operator", preview_hash=preview["preview_hash"]),
        )
        for call in calls:
            with pytest.raises(HTTPException, match="成功完成"):
                call()


def test_success_terminal_task_requires_a_nonempty_valid_fixed_delivery_set(fact_delivery):
    db, task, _, _, _, _ = fact_delivery
    _, _, values = _event_values(db, task)
    preview = preview_correction(db, **values)
    progress = json.loads(task.progress_json)
    progress["objects"].pop("deliveries")
    task.progress_json = json.dumps(progress, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    task.revision += 1
    db.commit()

    calls = (
        lambda: correction_status(db, task_id=task.task_id, project_id=1, prompt_id=44),
        lambda: preview_correction(db, **values),
        lambda: save_correction(db, **values, actor="actual-release-operator", preview_hash=preview["preview_hash"]),
    )
    for call in calls:
        with pytest.raises(HTTPException, match="固定稿件集合"):
            call()


def test_preview_rejects_save_after_success_terminal_task_revision_changes(fact_delivery):
    db, task, _, _, _, _ = fact_delivery
    _, _, values = _event_values(db, task)
    preview = preview_correction(db, **values)
    task.status = ("COMPLETED_WITH_LIMITATIONS" if task.status == "COMPLETED" else "COMPLETED")
    task.revision += 1
    db.commit()

    with pytest.raises(HTTPException, match="预览已变化"):
        save_correction(db, **values, actor="actual-release-operator", preview_hash=preview["preview_hash"])


def test_completed_task_evaluated_relation_uses_the_same_fixed_delivery_guard(fact_delivery):
    from app.modules.single_prompt_v2.diagnosis import _reviewable_set

    db, task, _, _, _, _ = fact_delivery
    objects = json.loads(task.progress_json)["objects"]
    result = db.query(SinglePromptDiagnosisResult).filter_by(
        result_version=objects["answer_result_version"]).one()
    output = json.loads(result.output_json)
    relations = output["evidence_diagnosis"]["source_relations"]
    if relations:
        relations[0].update(alignment_evaluation="EVALUATED", machine_relation="RELATED",
                            effective_relation="RELATED")
    else:
        reason_id = output["answer_diagnosis"]["events"][0]["reasons"][0]["reason_id"]
        relations.append({"relation_id": "evr-completed-fixture", "reason_id": reason_id,
                          "source_snapshot_id": "source-completed-fixture",
                          "alignment_evaluation": "EVALUATED", "machine_relation": "RELATED",
                          "effective_relation": "RELATED"})
    output_hash = corrections.digest(output)
    result_version = f"diag-evaluated-fixture:{output_hash[:16]}"
    db.add(SinglePromptDiagnosisResult(
        diagnosis_id=result.diagnosis_id, result_version=result_version,
        version_number=result.version_number + 100, parent_result_version=result.result_version,
        output_json=json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        output_hash=output_hash, reviewable_set_hash=corrections.digest(_reviewable_set(output)),
        limitations_json=result.limitations_json, stats_json=result.stats_json,
    ))
    execution = db.query(SinglePromptDiagnosisExecution).filter_by(
        diagnosis_id=result.diagnosis_id).one()
    execution.active_result_version = result_version
    progress = json.loads(task.progress_json)
    progress["objects"].update(answer_result_version=result_version, answer_result_hash=output_hash)
    task.progress_json = json.dumps(progress, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    task.revision += 1
    db.commit()

    status = correction_status(db, task_id=task.task_id, project_id=1, prompt_id=44)
    target = next(row for row in status["targets"]
                  if row["target_type"] == "EVIDENCE_RELATION" and row["alignment_evaluation"] == "EVALUATED")
    values = dict(
        task_id=task.task_id, project_id=1, prompt_id=44,
        base_result_version=status["base_result_version"], base_result_hash=status["base_result_hash"],
        reviewable_set_hash=status["reviewable_set_hash"], target_type=target["target_type"],
        target_id=target["target_id"], target_hash=target["target_hash"],
        value=next(value for value in target["allowed_values"] if value != target["current_value"]),
        reason="逐项核对来源和理由后确认关系应调整",
    )
    preview = preview_correction(db, **values)
    saved = save_correction(db, **values, actor="actual-release-operator", preview_hash=preview["preview_hash"])
    assert saved["impact"] == preview["impact"]
    assert saved["parent_result_version"] == status["base_result_version"]


def test_multiple_directions_and_deliveries_are_partitioned_exactly(fact_delivery):
    db, task, _, _, _, _ = fact_delivery
    status, target, values = _event_values(db, task)
    objects = json.loads(task.progress_json)["objects"]
    old_strategy = db.query(SinglePromptStrategyResult).filter_by(
        result_version=objects["strategy_result_version"]).one()
    strategy_output = json.loads(old_strategy.output_json)
    affected_direction = deepcopy(strategy_output["directions"][0])
    unaffected_direction = deepcopy(affected_direction)
    unaffected_id = f'{affected_direction["strategy_id"]}-unaffected'
    unaffected_direction.update(strategy_id=unaffected_id, direction_id=unaffected_id,
                                reason_id=None, reason_ids=[])
    strategy_output["directions"] = [affected_direction, unaffected_direction]
    strategy_hash = corrections.digest(strategy_output)
    strategy_version = f"strategy-partition:{strategy_hash[:16]}"
    db.add(SinglePromptStrategyResult(
        strategy_id=old_strategy.strategy_id, result_version=strategy_version,
        version_number=old_strategy.version_number + 100, parent_result_version=old_strategy.result_version,
        output_json=json.dumps(strategy_output, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        output_hash=strategy_hash, reviewable_set_hash=old_strategy.reviewable_set_hash,
        limitations_json=old_strategy.limitations_json,
    ))
    old_binding = objects["deliveries"][0]
    old_proposal = db.query(SinglePromptExecutionProposal).filter_by(
        proposal_id=old_binding["proposal_id"]).one()
    old_result = db.query(SinglePromptExecutionProposalResult).filter_by(
        proposal_id=old_binding["proposal_id"], result_version=old_binding["result_version"]).one()
    bindings = []
    for suffix, direction in (("affected", affected_direction["strategy_id"]), ("unaffected", unaffected_id)):
        proposal_id = f"proposal-partition-{suffix}"
        result_version = f"execution-partition-{suffix}-v1"
        proposal_values = {column.name: getattr(old_proposal, column.name)
                           for column in old_proposal.__table__.columns
                           if column.name not in {"id", "created_at", "updated_at"}}
        proposal_values.update(
            proposal_id=proposal_id, direction_id=direction, idempotency_key=proposal_id,
            strategy_result_version=strategy_version, strategy_result_hash=strategy_hash,
            active_result_version=result_version,
        )
        result_values = {column.name: getattr(old_result, column.name)
                         for column in old_result.__table__.columns
                         if column.name not in {"id", "created_at"}}
        result_values.update(proposal_id=proposal_id, result_version=result_version)
        db.add(SinglePromptExecutionProposal(**proposal_values))
        db.add(SinglePromptExecutionProposalResult(**result_values))
        bindings.append({"proposal_id": proposal_id, "result_version": result_version,
                         "result_hash": old_result.output_hash})
    objects.update(strategy_result_version=strategy_version, strategy_result_hash=strategy_hash,
                   deliveries=bindings)
    progress = json.loads(task.progress_json)
    progress["objects"] = objects
    task.progress_json = json.dumps(progress, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    task.revision += 1
    db.commit()

    refreshed, refreshed_target, values = _event_values(db, task)
    assert refreshed_target["target_id"] == target["target_id"]
    preview = preview_correction(db, **values)
    impact = preview["impact"]
    assert impact["affected_reason_ids"] == target["reason_ids"]
    assert impact["affected_strategy_ids"] == [affected_direction["strategy_id"]]
    assert impact["unaffected_strategy_ids"] == [unaffected_id]
    assert [row["proposal_id"] for row in impact["affected_deliveries"]] == ["proposal-partition-affected"]
    assert [row["proposal_id"] for row in impact["unaffected_deliveries"]] == ["proposal-partition-unaffected"]
    assert refreshed["base_result_version"] == status["base_result_version"]

    progress = json.loads(task.progress_json)
    progress["objects"]["deliveries"] = bindings[:1]
    task.progress_json = json.dumps(progress, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    task.revision += 1
    db.commit()
    with pytest.raises(HTTPException, match="稿件集合不完整"):
        correction_status(db, task_id=task.task_id, project_id=1, prompt_id=44)


def test_evaluated_relation_positive_and_unknown_states_never_upgrade(tmp_path, monkeypatch):
    db, engine = _session(tmp_path)
    try:
        _seed(db)
        analysis = _ready_analysis(db)
        execution, result = _compute(db, analysis)
        output = json.loads(result.output_json)
        evaluated = next(row for row in output["evidence_diagnosis"]["source_relations"]
                         if row["alignment_evaluation"] == "EVALUATED")
        task = SimpleNamespace(task_id="formal-task", input_hash="a" * 64,
                               revision=1, status="COMPLETED")
        objects = {"diagnosis_id": execution.diagnosis_id}
        monkeypatch.setattr(corrections, "_task_binding", lambda *args, **kwargs: (task, objects, result, result))
        manifest = {
            "affected_reason_ids": [evaluated["reason_id"]], "unaffected_reason_ids": [],
            "affected_strategy_ids": [], "unaffected_strategy_ids": [],
            "affected_deliveries": [], "unaffected_deliveries": [],
            "fixed_strategy": {"strategy_id": "fixed", "result_version": "fixed-v1", "result_hash": "b" * 64},
            "unchanged_objects": ["CitationContribution", "既有策略版本", "既有稿件版本"],
            "recompute_task_created": False, "external_calls": 0,
        }
        monkeypatch.setattr(corrections, "_identity_manifest", lambda *args, **kwargs: deepcopy(manifest))
        values = dict(
            task_id=task.task_id, project_id=1, prompt_id=44,
            base_result_version=result.result_version, base_result_hash=result.output_hash,
            reviewable_set_hash=result.reviewable_set_hash, target_type="EVIDENCE_RELATION",
            target_id=evaluated["relation_id"], target_hash=corrections.digest(evaluated),
            value="NONE", reason="逐项核对来源和理由后确认没有证据关系",
        )
        preview = preview_correction(db, **values)
        saved = save_correction(db, **values, actor="actual-release-operator", preview_hash=preview["preview_hash"])
        revised = db.query(SinglePromptDiagnosisResult).filter_by(result_version=saved["result_version"]).one()
        revised_relation = next(row for row in json.loads(revised.output_json)["evidence_diagnosis"]["source_relations"]
                                if row["relation_id"] == evaluated["relation_id"])
        assert revised_relation["effective_relation"] == "NONE"
        assert json.loads(result.output_json)["evidence_diagnosis"]["source_relations"][0] == output["evidence_diagnosis"]["source_relations"][0]

        unknown = deepcopy(evaluated)
        unknown.update(relation_id="not-evaluated", alignment_evaluation="NOT_EVALUATED",
                       machine_relation=None, effective_relation=None)
        output["evidence_diagnosis"]["source_relations"].append(unknown)
        # Validation is exercised directly against a fixed synthetic base; it must fail before any revision write.
        fake = SimpleNamespace(result_version="fake-v1", output_hash=corrections.digest(output),
            reviewable_set_hash=result.reviewable_set_hash, output_json=json.dumps(output))
        monkeypatch.setattr(corrections, "_task_binding", lambda *args, **kwargs: (task, objects, fake, fake))
        with pytest.raises(HTTPException, match="不能升级"):
            preview_correction(db, **{**values, "base_result_version": fake.result_version,
                "base_result_hash": fake.output_hash, "target_id": unknown["relation_id"],
                "target_hash": corrections.digest(unknown)})
        unknown["alignment_evaluation"] = "FAILED"
        fake.output_json = json.dumps(output)
        with pytest.raises(HTTPException, match="不能升级"):
            preview_correction(db, **{**values, "base_result_version": fake.result_version,
                "base_result_hash": fake.output_hash, "target_id": unknown["relation_id"],
                "target_hash": corrections.digest(unknown)})
    finally:
        db.close(); engine.dispose()


def test_task_view_keeps_correction_out_of_automatic_recompute_kinds(fact_delivery):
    _, task, _, _, _, _ = fact_delivery
    assert task_view(task)["task_kind"] == "AUTOMATIC_OPTIMIZE"


def test_release_route_uses_authenticated_actor_and_rejects_form_actor():
    route = next(row for row in create_release_app(validate_on_startup=False).routes
        if isinstance(row, APIRoute) and row.endpoint.__name__ == "create_answer_relation_correction")
    assert any(dependency.call is authenticated_actor for dependency in route.dependant.dependencies)
    body = {
        "project_id": 1, "prompt_id": 44, "base_result_version": "diag-v1",
        "base_result_hash": "a" * 64, "reviewable_set_hash": "b" * 64,
        "target_type": "RECOMMENDATION_EVENT", "target_id": "event-1", "target_hash": "c" * 64,
        "value": "MENTION", "reason": "人工核对依据", "preview_hash": "d" * 64,
        "human_confirmed": True, "actor": "forged-form-actor",
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AnswerRelationCorrectionCreate.model_validate(body)


def test_release_http_persists_authenticated_actor_and_append_only_history(fact_delivery):
    from fastapi import Depends, FastAPI
    from app.core.release_access import install_access, require_project_access
    from app.modules.single_prompt_v2.release_api import get_db, router
    from release_test_client import TestClient

    db, task, _, _, _, _ = fact_delivery
    status, _, body = _event_values(db, task)
    original = db.query(SinglePromptDiagnosisResult).filter_by(
        result_version=status["base_result_version"]).one()
    original_bytes = (original.output_json, original.output_hash)
    app = FastAPI()
    install_access(app, ["http://127.0.0.1:5173"])
    app.include_router(router, dependencies=[Depends(require_project_access)])
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 8000))
    base = f"/api/v2/single-prompt/optimization-tasks/{task.task_id}/answer-relation-corrections"

    response = client.post(base + "/preview", json={k: v for k, v in body.items() if k != "task_id"})
    assert response.status_code == 200, response.text
    payload = {k: v for k, v in body.items() if k != "task_id"}
    payload.update(preview_hash=response.json()["preview_hash"], human_confirmed=True)
    assert client.post(base, json={**payload, "actor": "forged-form-actor"}).status_code == 422
    saved = client.post(base, json=payload)
    assert saved.status_code == 201, saved.text
    assert saved.json()["actor"] == "local-owner"
    history = client.get(base + "?project_id=1&prompt_id=44")
    assert history.status_code == 200, history.text
    assert history.json()["history"][-1]["actor"] == "local-owner"
    assert history.json()["history"][-1]["parent_result_version"] == status["base_result_version"]
    db.refresh(original)
    assert (original.output_json, original.output_hash) == original_bytes
