import copy
from types import SimpleNamespace

import pytest

from app.modules.single_prompt_v2.delivery_generation import admit_draft, finish_draft, generation_input, segments_of
from app.modules.single_prompt_v2.automatic_delivery import _draft_evidence_qualification
from app.modules.single_prompt_v2.delivery_text import text_digest
from app.modules.single_prompt_v2.graded_delivery import (
    L1, L2, L3, L4, aggregate_results, build_l4_recovery, build_plan, validate_seal,
)


def plan_input(*, evidence=True, limited=False, evidence_relation="SUPPORTS_FULL"):
    selected = []
    binding_ids = []
    if evidence:
        text = "资料说明：操作前需要核对适用条件。"
        selected = [{"section_id": "evidence:1", "binding_id": "binding:1",
            "evidence_relation": evidence_relation, "snapshot_id": "snapshot:1",
            "passage_id": "passage:1", "passage_text": text, "passage_hash": text_digest(text),
            "title": "公开资料", "url": "https://example.com/source"}]
        binding_ids = ["binding:1"]
    delivery = {"identity": {"answer_result_version": "answer-v1", "answer_result_hash": "a" * 64},
        "selected_evidence": selected, "truths": [], "contribution_result_version": "contribution-v1",
        "contribution_result_hash": "b" * 64, "question_topics": [{"raw_text": "待研究的问题"}]}
    if not evidence:
        delivery.update(content_mode="RESEARCH_GUIDE_NOT_FACTUAL_ANSWER",
            limitations=["NO_CONSUMABLE_FACT_EVIDENCE"])
    direction = {"direction_id": "direction-1", "evidence_relation_ids": binding_ids,
        "scope_limitations": ["PARTIAL_SCOPE"] if limited else [], "limiting_dependencies": []}
    return build_plan(task_id="task-1", task_input_hash="c" * 64,
        analysis_id="analysis-1", context_id="context-1", project_id=1, prompt_id=2,
        fixed_run_ids=[7], proposal_id="proposal-1", proposal_result_version="execution-v1",
        proposal_result_hash="d" * 64, strategy_id="strategy-1",
        strategy_result_version="strategy-v1", strategy_result_hash="e" * 64,
        direction=direction, delivery_input=delivery, evidence_binding_ids=binding_ids), delivery


def pass_qa(draft):
    return {"checks": [{"segment_id": row["segment_id"], "verdict": "PASS", "rationale": "未增加事实。"}
        for row in segments_of(draft)]}


def test_plans_are_sealed_and_levels_do_not_change_evidence_identity():
    l1, _ = plan_input()
    l2_partial, _ = plan_input(evidence_relation="SUPPORTS_PARTIAL")
    l2_limited, _ = plan_input(limited=True)
    l3, _ = plan_input(evidence=False)
    assert [l1["planned_delivery_level"], l2_partial["planned_delivery_level"],
        l2_limited["planned_delivery_level"], l3["planned_delivery_level"]] == [L1, L2, L2, L3]
    for plan in (l1, l2_partial, l2_limited, l3):
        validate_seal(plan, prefix="plan")
        validate_seal(plan["qualification"], prefix="qualification")
        assert plan["product_outcome"] == "NONE"
        assert plan["qualification"]["fixed_run_ids"] == [7]
    tampered = copy.deepcopy(l1)
    tampered["qualification"]["strategy_result_version"] = "latest"
    with pytest.raises(ValueError, match="QUALIFICATION_HASH_MISMATCH"):
        validate_seal(tampered["qualification"], prefix="qualification")


def test_l3_admits_only_instruction_and_binds_append_only_result_to_plan():
    plan, delivery = plan_input(evidence=False)
    frozen = {"prompt_text": "如何核验当前能力", "prompt_configuration": {},
        "brand": {"brand_name": "目标品牌"}, "question_topics": [], "strategy_direction": {},
        "brand_context": {"passages": []}, "selected_evidence": [],
        "delivery_qualification_plan": plan}
    inputs = generation_input(frozen)
    draft = {"sections": [{"heading": "核验步骤", "blocks": [{"kind": "INSTRUCTION",
        "text": "先检查公开资料与当前适用条件，再记录待补证项。", "evidence_ids": []}]}]}
    receipt = finish_draft(draft, pass_qa(draft), inputs)
    result = receipt["delivery_qualification_result"]
    assert receipt["title"] == "核验与行动建议"
    assert receipt["segments"][0]["text"] == "核验与行动步骤"
    assert result["plan_hash"] == plan["plan_hash"]
    assert result["admitted_delivery_level"] == L3
    assert result["product_outcome"] == "CONTENT_DELIVERED"
    illegal = copy.deepcopy(draft)
    illegal["sections"][0]["blocks"][0].update(kind="SOURCE_STATEMENT", evidence_ids=["invented"])
    with pytest.raises(ValueError, match="L3_FACT_CLAIM_FORBIDDEN"):
        admit_draft(illegal, inputs)


def test_l4_is_zero_call_recovery_and_never_satisfies_content_dependency():
    plan, result = build_l4_recovery(task_id="task-l4", task_input_hash="a" * 64,
        analysis_id="analysis-l4", context_id="context-l4", project_id=1, prompt_id=2,
        fixed_run_ids=[9], raw_output_hash="b" * 64, missing_objects=["CONSUMABLE_ANSWER"],
        reasons=["回答不可消费"], recovery_actions=["重新采样"])
    assert plan["planned_delivery_level"] == L4 and plan["product_outcome"] == "NONE"
    assert result["product_outcome"] == "RECOVERY_REQUIRED"
    assert result["external_model_calls"] == 0
    assert result["downstream_content_delivery_dependency_satisfied"] is False
    aggregate = aggregate_results([result])
    assert aggregate == {"product_outcome": "RECOVERY_REQUIRED", "highest_level": L4,
        "lowest_level": L4, "all_directions_l1": False, "direction_results": [{
            "direction_id": None, "plan_id": result["plan_id"], "plan_version": result["plan_version"],
            "plan_hash": result["plan_hash"], "result_id": result["result_id"],
            "result_version": result["result_version"], "result_hash": result["result_hash"],
            "admitted_delivery_level": L4, "product_outcome": "RECOVERY_REQUIRED"}]}


def test_integrity_failure_is_blocked_without_creating_plan_or_result():
    row = SimpleNamespace(task_id="task-x", input_hash="a" * 64, analysis_id="analysis-x",
        context_id="context-x", project_id=1, prompt_id=2)
    direction = {"direction_id": "direction-x", "evidence_relation_ids": [], "dependencies": [{
        "object_type": "CITATION_CONTRIBUTION_SCOPE", "object_id": "UNAVAILABLE",
        "required_for": ["EXECUTION_DRAFT"]}]}
    delivery = {"identity": {"analysis_id": "foreign-analysis", "context_id": "context-x",
        "project_id": 1, "prompt_id": 2, "strategy_id": "strategy-x",
        "strategy_result_version": "strategy-v1", "strategy_result_hash": "b" * 64},
        "selected_evidence": [], "content_mode": "RESEARCH_GUIDE_NOT_FACTUAL_ANSWER"}
    gate = _draft_evidence_qualification(row=row, fixed={"run_ids": [1]}, strategy_id="strategy-x",
        strategy_result_version="strategy-v1", strategy_result_hash="b" * 64,
        direction=direction, base_output={"delivery_input": delivery,
            "evidence_processing_audit": {"selected_binding_ids": []}},
        proposal_id="proposal-x", proposal_result_version="execution-v1", proposal_result_hash="c" * 64)
    assert gate["status"] == "BLOCKED"
    assert "EVIDENCE_SCOPE_OR_VERSION_MISMATCH" in gate["gaps"]
    assert "qualification_plan" not in gate
