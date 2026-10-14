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
    SinglePromptDiagnosisResult,
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
    status = correction_status(db, task_id=task.task_id, project_id=1, prompt_id=44)
    target = next(row for row in status["targets"] if row["target_type"] == "RECOMMENDATION_EVENT")
    base = dict(
        task_id=task.task_id, project_id=1, prompt_id=44,
        base_result_version=status["base_result_version"], base_result_hash=status["base_result_hash"],
        reviewable_set_hash=status["reviewable_set_hash"], target_type=target["target_type"],
        target_id=target["target_id"], target_hash=target["target_hash"],
        value=next(value for value in target["allowed_values"] if value != target["current_value"]),
        reason="明确的人工核对依据",
    )
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


def test_evaluated_relation_positive_and_unknown_states_never_upgrade(tmp_path, monkeypatch):
    db, engine = _session(tmp_path)
    try:
        _seed(db)
        analysis = _ready_analysis(db)
        execution, result = _compute(db, analysis)
        output = json.loads(result.output_json)
        evaluated = next(row for row in output["evidence_diagnosis"]["source_relations"]
                         if row["alignment_evaluation"] == "EVALUATED")
        task = SimpleNamespace(task_id="formal-task", input_hash="a" * 64)
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
