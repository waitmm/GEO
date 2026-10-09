from __future__ import annotations

from app.modules.single_prompt_v2.qualification import evaluate_qualification_projection


def _projection(*, public_ready: bool = False, full_coverage: bool = True) -> dict:
    statement = {"status": "ELIGIBLE", "issues": []} if public_ready else {
        "status": "VERIFY_FIRST",
        "issues": ["SOURCE_REFERENCE_REQUIRED"],
    }
    return {
        "identity": {
            "analysis_id": "analysis-1",
            "context_id": "context-1",
            "diagnosis_id": "diagnosis-1",
            "diagnosis_result_version": "diag-v2:fixture",
        },
        "input_snapshot_hash": "a" * 64,
        "analyzable_run_ids": list(range(1, 10)),
        "brand_snapshot": {"brand_name": "目标品牌"},
        "reasons": [{
            "reason_id": "reason-target",
            "event_id": "event-target",
            "run_id": 4,
            "entity_text": "目标品牌",
            "grounded_text": "通过中转页完成跳转并支持数据追踪",
            "fact_consumption_eligible": True,
        }],
        "truth_snapshot": [{
            "truth_id": 7,
            "brand_id": 1,
            "capability_label": "通过中转页完成跳转",
            "product_truth_status": "SUPPORTED",
            "truth_source": "MANUAL_CONFIRMED",
            "statement_eligibility": statement,
        }],
        "reason_capability_coverage": [{
            "reason_id": "reason-target",
            "effective_relation": "FULLY_COVERS" if full_coverage else "PARTIALLY_COVERS",
            "fact_consumption_eligible": True,
            "truth_ids": [7],
        }],
    }


def _contribution_scope() -> dict:
    return {
        "status": "PARTIAL_SCOPE",
        "run_ids": [1],
        "scope_limitations": ["CITATION_CONTRIBUTION_RUN_1_ONLY"],
        "result": {
            "contribution_id": "contribution-1",
            "result_version": "contribution-v1:fixture",
            "result_hash": "b" * 64,
        },
    }


def test_machine_direction_and_draft_do_not_require_diagnosis_review():
    result = evaluate_qualification_projection(_projection(), _contribution_scope())

    assert result["final_plan"] == {
        "analysis_completed": True,
        "machine_direction_count": 1,
        "execution_draft_count": 1,
        "execution_ready_count": 0,
        "draftable_verify_first_count": 1,
        "human_review_global_blocker": False,
        "external_action_authorized": False,
    }
    direction = result["directions"][0]
    assert direction["strategy_direction_eligibility"] == "CONSUMABLE"
    assert direction["execution_draft_eligibility"] == "CONSUMABLE"
    assert direction["public_claim_eligibility"] == "VERIFY_FIRST"


def test_first_party_assertion_supports_direction_but_not_public_claim():
    result = evaluate_qualification_projection(_projection(), _contribution_scope())

    truth = next(row for row in result["object_qualifications"] if row["object_type"] == "PRODUCT_TRUTH")
    assert truth["quality_state"] == "FIRST_PARTY_ASSERTED"
    assert truth["eligibility_by_use"]["strategy_direction"] == "CONSUMABLE"
    assert truth["eligibility_by_use"]["execution_draft"] == "CONSUMABLE"
    assert truth["eligibility_by_use"]["public_claim"] == "VERIFY_FIRST"
    claim = result["execution_drafts"][0]["claims"][0]
    assert claim["claim_eligibility"] == "VERIFY_FIRST"
    assert claim["public_claim_eligibility"] == "NOT_CONSUMABLE"
    assert claim["limiting_dependencies"]


def test_officially_eligible_statement_removes_public_claim_blocker_only():
    result = evaluate_qualification_projection(_projection(public_ready=True), _contribution_scope())

    direction = result["directions"][0]
    claim = result["execution_drafts"][0]["claims"][0]
    assert direction["public_claim_eligibility"] == "CONSUMABLE"
    assert claim["public_claim_eligibility"] == "CONSUMABLE"
    boundary = result["execution_drafts"][0]["boundary"]
    assert boundary["public_claims_ready"] is True
    assert boundary["publication_eligibility"] == "ELIGIBLE_PENDING_BUSINESS_APPROVAL"
    assert boundary["external_action_authorized"] is False
    assert result["final_plan"]["human_review_global_blocker"] is False


def test_partial_truth_coverage_creates_only_non_claim_discovery_direction():
    result = evaluate_qualification_projection(
        _projection(full_coverage=False),
        _contribution_scope(),
    )

    assert len(result["directions"]) == 1
    direction = result["directions"][0]
    assert direction["direction_type"] == "DISCOVERY"
    assert direction["mechanism_gap"] == "QUESTION_CONTENT_COVERAGE_HYPOTHESIS"
    assert direction["truth_ids"] == []
    assert direction["public_claim_eligibility"] == "NOT_CONSUMABLE"
    assert len(result["execution_drafts"]) == 1
    assert result["execution_drafts"][0]["claims"] == []
    assert result["final_plan"]["machine_direction_count"] == 1
    assert result["final_plan"]["execution_ready_count"] == 0


def test_run_one_contribution_never_becomes_nine_run_evidence_scope():
    result = evaluate_qualification_projection(_projection(), _contribution_scope())

    assert result["analysis_scope"]["run_ids"] == list(range(1, 10))
    assert result["evidence_scope"]["run_ids"] == [1]
    assert result["evidence_scope"]["label"] == "Citation Contribution: Run 1 only"
    assert "CITATION_CONTRIBUTION_RUN_1_ONLY" in result["directions"][0]["scope_limitations"]
    citation_dependency = next(
        row for row in result["directions"][0]["dependencies"]
        if row["object_type"] == "CITATION_CONTRIBUTION_SCOPE"
    )
    assert citation_dependency["dependency_role"] == "ENRICHING"
    assert citation_dependency["eligibility"] == "OBSERVE_ONLY"


def test_projection_is_deterministic_and_read_only_by_contract():
    first = evaluate_qualification_projection(_projection(), _contribution_scope())
    second = evaluate_qualification_projection(_projection(), _contribution_scope())

    assert first == second
    assert first["boundary"]["read_only"] is True
    assert first["boundary"]["database_writes"] == 0
    assert first["boundary"]["external_llm_calls"] == 0


def test_concept_intent_without_brand_recommendation_is_not_recommendation_gap():
    projection = _projection(full_coverage=False)
    projection['prompt_snapshot'] = {'text': '什么是雨水花园', 'configuration': {'intent_type': 'category_awareness'}}
    result = evaluate_qualification_projection(projection, _contribution_scope(), '什么是雨水花园')
    direction = result['directions'][0]
    assert direction['mechanism_gap'] == 'EXPLANATION_CONTENT_OPPORTUNITY'
    assert '不以是否推荐品牌' in direction['intervention_goal']
    assert direction['observed_or_hypothesis'] == 'CONTENT_OPPORTUNITY_HYPOTHESIS'
    assert all(row['result'] != 'TARGET_BRAND_NOT_OBSERVED' for row in direction['reasoning_trace'])


def test_all_failed_answers_do_not_create_successful_exploration_plan():
    projection = _projection()
    projection['answer_semantic_eligibility'] = {'no_consumable_answer_semantic_result': True}
    result = evaluate_qualification_projection(projection, _contribution_scope())
    assert result['directions'] == [] and result['execution_drafts'] == []
    assert result['final_plan']['analysis_completed'] is False
