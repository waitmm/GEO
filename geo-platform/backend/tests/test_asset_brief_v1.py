from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    OptimizationAction,
    OptimizationExperiment,
    OptimizationStrategyCandidate,
    PageSnapshot,
    TargetBrandCapabilityTruth,
)
from app.modules.optimization.service import (
    _asset_brief_for_step8,
    _claim_matrix_for_asset_brief,
    _mechanism_compatibility_for_step8,
    _strategy_snapshot_for_experiment,
    _step8_execution_parameters,
    confirm_citation_decision_vertical_slice,
    confirm_strategy_execution_plan,
    review_experiment_asset_brief,
    review_strategy_candidate,
    citation_decision_vertical_slice,
)
from app.services.serialization import dumps, loads
from tests.test_source_gap_v1 import _vertical_slice_fixture


def _db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _accepted_candidate(db):
    project, prompt, package = _vertical_slice_fixture(db)
    proposal = citation_decision_vertical_slice(db, project.id, prompt.id, package.id, use_answer_binding_v1_1=True)
    confirmed = confirm_citation_decision_vertical_slice(
        db,
        project.id,
        prompt.id,
        {
            "evidence_package_id": package.id,
            "action_keys": [proposal["recommended_actions"][0]["action_key"]],
            "reviewer": "human",
            "use_answer_binding_v1_1": True,
        },
    )
    candidate_id = confirmed["created"][0]["strategy_candidate"]["id"]
    review_strategy_candidate(
        db,
        candidate_id,
        type(
            "Payload",
            (),
            {
                "review_status": "ACCEPTED_WITH_EDITS",
                "reviewed_by": "human",
                "review_note": "确认策略机制，等待第 8 步资产简报。",
                "human_edited_payload": {"review_summary": "能力表达缺口成立"},
            },
        )(),
    )
    return project, prompt, package, candidate_id


def _confirm_step8(db, candidate_id: int, channel: str = "OFFICIAL_SITE", selected_asset_id: int | None = 901):
    payload = {
        "channel": channel,
        "asset_operation": "UPDATE_EXISTING" if selected_asset_id else "CREATE_NEW",
        "selected_asset_id": selected_asset_id,
        "selected_asset_type": "ARTICLE",
        "target_content_type": "ARTICLE",
        "target_object": "CONTENT_ASSET",
        "baseline_run_ids": [101],
        "confirmed_by": "human",
        "confirmation_note": "确认执行资产，生成资产简报。",
        "new_asset_proposal": {} if selected_asset_id else {"title": "爱短链能力说明", "url": "https://example.com/new"},
    }
    return confirm_strategy_execution_plan(db, candidate_id, payload)


def test_step8_generates_asset_brief_and_claim_matrix_before_draft():
    db = _db()
    try:
        project, prompt, package, candidate_id = _accepted_candidate(db)

        result = _confirm_step8(db, candidate_id)
        brief = result["plan_payload"]["asset_brief"]
        matrix = brief["claim_matrix"]

        assert brief["brief_version"] == "asset_brief.step8.v1"
        assert brief["status"] == "PENDING_REVIEW"
        assert brief["draft_gate"]["status"] == "BLOCKED_UNTIL_BRIEF_CONFIRMED"
        assert brief["channel"] == "OFFICIAL_SITE"
        assert matrix["matrix_version"] == "asset_brief.claim_matrix.v1"
        assert matrix["target_brand_claims"][0]["subject_entity"] == "爱短链"
        assert matrix["target_brand_claims"][0]["support_basis"] == "PRODUCT_TRUTH"
        assert matrix["target_brand_claims"][0]["requirement_level"] == "REQUIRED"
        assert matrix["benchmark_context_claims"][0]["support_basis"] == "ELIGIBLE_BENCHMARK_EVIDENCE"
        assert "不得改写为目标品牌事实" in matrix["benchmark_context_claims"][0]["source_entity_boundary"]

        experiment = db.get(OptimizationExperiment, result["experiment_id"])
        variables = loads(experiment.intervention_variables_json, {})
        assert variables["asset_brief"]["draft_gate"]["status"] == "BLOCKED_UNTIL_BRIEF_CONFIRMED"
        assert loads(experiment.brief_json, {})["asset_brief"]["claim_matrix"]["target_brand_claims"]
    finally:
        db.close()


def test_asset_brief_review_confirms_gate_without_creating_new_action_or_experiment():
    db = _db()
    try:
        project, prompt, package, candidate_id = _accepted_candidate(db)
        result = _confirm_step8(db, candidate_id)
        action_count = db.query(OptimizationAction).count()
        experiment_count = db.query(OptimizationExperiment).count()

        reviewed = review_experiment_asset_brief(
            db,
            result["experiment_id"],
            {
                "review_status": "CONFIRMED",
                "reviewed_by": "human",
                "review_note": "确认资产事实边界。",
            },
        )

        brief = reviewed["intervention_variables"]["asset_brief"]
        assert brief["status"] == "CONFIRMED"
        assert brief["draft_gate"]["status"] == "READY_FOR_DRAFT_PREPARATION"
        assert db.query(OptimizationAction).count() == action_count
        assert db.query(OptimizationExperiment).count() == experiment_count
    finally:
        db.close()


def test_existing_step8_draft_gets_asset_brief_backfilled_without_recreating_objects():
    db = _db()
    try:
        project, prompt, package, candidate_id = _accepted_candidate(db)
        result = _confirm_step8(db, candidate_id)
        experiment = db.get(OptimizationExperiment, result["experiment_id"])
        variables = loads(experiment.intervention_variables_json, {})
        variables.pop("asset_brief", None)
        experiment.intervention_variables_json = dumps(variables)
        brief_payload = loads(experiment.brief_json, {})
        brief_payload.pop("asset_brief", None)
        experiment.brief_json = dumps(brief_payload)
        candidate = db.get(OptimizationStrategyCandidate, candidate_id)
        plan_payload = loads(candidate.experiment_plan_json, {})
        plan_payload.pop("asset_brief", None)
        candidate.experiment_plan_json = dumps(plan_payload)
        db.commit()
        action_count = db.query(OptimizationAction).count()
        experiment_count = db.query(OptimizationExperiment).count()

        second = _confirm_step8(db, candidate_id)

        assert second["readiness_status"] == "DRAFT_ALREADY_EXISTS"
        assert second["plan_payload"]["asset_brief"]["claim_matrix"]["target_brand_claims"]
        assert db.query(OptimizationAction).count() == action_count
        assert db.query(OptimizationExperiment).count() == experiment_count
    finally:
        db.close()


def test_claim_matrix_blocks_unknown_product_truth_from_required_claim():
    db = _db()
    try:
        project, prompt, package, candidate_id = _accepted_candidate(db)
        candidate = db.get(OptimizationStrategyCandidate, candidate_id)
        effective = loads(candidate.effective_payload_json, {})
        effective["priority_capabilities"][0]["capability_label"] = "高级实时点击画像"
        effective["priority_capabilities"][0]["product_truth_ids"] = []
        effective["priority_capabilities"][0]["product_truth_status"] = "UNKNOWN"
        strategy_snapshot = _strategy_snapshot_for_experiment(candidate, package)
        selected_asset_ref = {
            "asset_ref_type": "PAGE_SNAPSHOT",
            "asset_id": 901,
            "canonical_url": "https://www.aifabu.com",
            "url": "https://www.aifabu.com",
            "asset_type": "ARTICLE",
            "channel": "OFFICIAL_SITE",
            "asset_operation": "UPDATE_EXISTING",
        }
        execution = _step8_execution_parameters(
            {"channel": "OFFICIAL_SITE", "asset_operation": "UPDATE_EXISTING"},
            selected_asset_ref,
            "OFFICIAL_SITE",
            "UPDATE_EXISTING",
        )
        brief = _asset_brief_for_step8(
            db,
            project,
            prompt,
            package,
            candidate,
            effective,
            strategy_snapshot,
            selected_asset_ref,
            execution,
            _mechanism_compatibility_for_step8(effective, execution),
        )

        assert brief["status"] == "BLOCKED"
        claim = brief["claim_matrix"]["target_brand_claims"][0]
        assert claim["requirement_level"] == "REVIEW_REQUIRED"
        assert "PRODUCT_TRUTH_REVIEW_REQUIRED" in claim["risk_flags"]
    finally:
        db.close()


def test_claim_matrix_marks_not_supported_capability_as_prohibited():
    db = _db()
    try:
        project, prompt, package = _vertical_slice_fixture(db)
        truth = db.get(TargetBrandCapabilityTruth, 801)
        truth.product_truth_status = "NOT_SUPPORTED"
        db.commit()
        effective = {
            "priority_capabilities": [{
                "gap_item_id": "gap-1",
                "capability_label": "批量短链生成",
                "product_truth_ids": [801],
                "product_truth_status": "FALSE",
                "benchmark_evidence_ids": [701],
                "observed_run_ids": [101],
            }],
            "required_signals": [{"capability_label": "批量短链生成", "signal": "爱短链 支持 批量短链生成"}],
        }
        matrix = _claim_matrix_for_asset_brief(
            project,
            effective,
            effective["priority_capabilities"],
            {801: {
                "product_truth_id": 801,
                "capability_label": "批量短链生成",
                "product_truth_status": "NOT_SUPPORTED",
            }},
        )

        assert matrix["target_brand_claims"][0]["requirement_level"] == "PROHIBITED"
        assert matrix["prohibited_claims"][0]["capability_label"] == "批量短链生成"
    finally:
        db.close()


def test_claim_matrix_keeps_claim_boundary_for_supported_truth():
    db = _db()
    try:
        project, prompt, package = _vertical_slice_fixture(db)
        matrix = _claim_matrix_for_asset_brief(
            project,
            {
                "required_signals": [{"capability_label": "点击统计", "signal": "爱短链 支持 点击统计"}],
            },
            [{
                "gap_item_id": "gap-click",
                "capability_label": "点击统计",
                "product_truth_ids": [801],
                "product_truth_status": "TRUE",
                "benchmark_evidence_ids": [701],
                "observed_run_ids": [101],
            }],
            {801: {
                "product_truth_id": 801,
                "capability_label": "点击统计",
                "product_truth_status": "SUPPORTED",
            }},
        )

        boundary = matrix["target_brand_claims"][0]["claim_boundary"]
        assert "点击统计" in boundary["allowed_scope"]
        assert "实时用户画像" in boundary["prohibited_expansions"]
        assert "全渠道归因" in boundary["prohibited_expansions"]
    finally:
        db.close()


def test_required_signal_mapping_is_traceable_to_claim_matrix():
    db = _db()
    try:
        project, prompt, package, candidate_id = _accepted_candidate(db)
        result = _confirm_step8(db, candidate_id)
        mappings = result["plan_payload"]["asset_brief"]["claim_matrix"]["required_signal_mappings"]

        assert mappings
        assert all(mapping["claim_ids"] for mapping in mappings)
        assert all(mapping["status"] == "MAPPED" for mapping in mappings)
    finally:
        db.close()


def test_mechanism_review_required_must_be_explicitly_approved_before_brief_confirm():
    db = _db()
    try:
        project, prompt, package, candidate_id = _accepted_candidate(db)
        result = _confirm_step8(db, candidate_id, channel="BAIJIAHAO", selected_asset_id=None)
        assert result["plan_payload"]["mechanism_compatibility"]["status"] == "REVIEW_REQUIRED"

        with pytest.raises(Exception):
            review_experiment_asset_brief(
                db,
                result["experiment_id"],
                {"review_status": "CONFIRMED", "reviewed_by": "human"},
            )

        reviewed = review_experiment_asset_brief(
            db,
            result["experiment_id"],
            {
                "review_status": "CONFIRMED",
                "reviewed_by": "human",
                "approved_mechanism_review": True,
                "review_note": "确认百家号仍可承载同一证明机制。",
            },
        )
        assert reviewed["intervention_variables"]["asset_brief"]["status"] == "CONFIRMED"
    finally:
        db.close()


def test_asset_brief_snapshot_immutable_after_truth_and_asset_change():
    db = _db()
    try:
        project, prompt, package, candidate_id = _accepted_candidate(db)
        result = _confirm_step8(db, candidate_id)
        reviewed = review_experiment_asset_brief(
            db,
            result["experiment_id"],
            {"review_status": "CONFIRMED", "reviewed_by": "human"},
        )
        frozen = reviewed["intervention_variables"]["asset_brief"]

        truth = db.get(TargetBrandCapabilityTruth, 801)
        truth.product_truth_status = "NOT_SUPPORTED"
        snapshot = db.get(PageSnapshot, 901)
        snapshot.main_text = "后续全局资产池发生变化。"
        db.commit()
        experiment = db.get(OptimizationExperiment, result["experiment_id"])
        still_frozen = loads(experiment.intervention_variables_json, {})["asset_brief"]

        assert still_frozen == frozen
        assert still_frozen["claim_matrix"]["target_brand_claims"][0]["product_truth_status"] == "SUPPORTED"
        assert "后续全局资产池发生变化" not in str(still_frozen)
    finally:
        db.close()
