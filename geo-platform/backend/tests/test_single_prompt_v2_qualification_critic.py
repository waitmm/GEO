from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, SinglePromptQualificationCriticExecution, SinglePromptQualificationCriticResult
from app.modules.single_prompt_v2 import qualification_critic as critic
from app.services.semantic_llm.base import SemanticLLMError


def _binding(relation: str = "SUPPORTS_PARTIAL") -> dict:
    return {
        "binding_id": "binding-1",
        "evaluation_id": "evaluation-1",
        "answer_unit_id": "answer-unit-1",
        "correspondence_mode": "FAITHFUL_PARAPHRASE",
        "evidence_relation": relation,
        "answer_anchor": "UNPROVEN",
        "generation_influence": "UNAVAILABLE",
        "rationale": "来源只支持部分操作。",
    }


def _contribution(relation: str = "SUPPORTS_PARTIAL") -> dict:
    return {
        "answer_units": [{
            "answer_unit_id": "answer-unit-1",
            "primary_type": "PROCEDURE",
            "raw_text": "在私信自动回复中设置消息卡片。",
            "context_heading": "其他方式",
            "subject_markers": [],
            "condition_markers": [],
            "negation_markers": [],
        }],
        "evaluations": [{
            "evaluation_id": "evaluation-1",
            "citation_id": "citation-1",
            "citation_title": "来源标题",
            "answer_span": "设置消息卡片",
            "source_span": "将跳转卡片与私信自动回复结合",
            "source_passage_text": "可以将跳转卡片与私信自动回复功能相结合。",
            "validation_limitations": ["ANSWER_ANCHOR_UNPROVEN"],
        }],
        "bindings": [_binding(relation)],
    }


def test_critic_selects_positive_binding_but_not_related_only():
    positive = critic._citation_candidates(_contribution())
    related = critic._citation_candidates(_contribution("RELATED_ONLY"))

    assert len(positive) == 1
    assert positive[0]["candidate_type"] == "CITATION_RELATION"
    assert positive[0]["object_id"] == "binding-1"
    assert related == []


def test_critic_response_schema_is_strict_and_closed():
    valid = critic.QualificationCriticResponse.model_validate({
        "critic_verdict": "DISAGREE",
        "issues": ["OVERSTATED_SUPPORT"],
        "counterexample": "来源只支持部分操作。",
        "rationale": "支持范围被扩大。",
    })
    assert valid.critic_verdict == "DISAGREE"

    with pytest.raises(ValidationError):
        critic.QualificationCriticResponse.model_validate({
            "critic_verdict": "AGREE",
            "issues": [],
            "counterexample": None,
            "rationale": "一致。",
            "final_strategy": "官网优先",
        })


def test_critic_dynamic_gate_rejects_cross_field_and_invented_counterexample():
    candidate = critic._citation_candidates(_contribution())[0]
    validate = critic._validator(candidate)

    with pytest.raises(SemanticLLMError, match="AGREE"):
        validate({
            "critic_verdict": "AGREE",
            "issues": ["OTHER"],
            "counterexample": None,
            "rationale": "不合法。",
        })
    with pytest.raises(SemanticLLMError, match="未逐字出现"):
        validate({
            "critic_verdict": "DISAGREE",
            "issues": ["OVERSTATED_SUPPORT"],
            "counterexample": "输入里不存在的能力承诺",
            "rationale": "不合法。",
        })


def test_strategy_critic_is_shadow_only_and_does_not_rewrite_direction():
    direction = {
        "strategy_id": "strategy-1",
        "mechanism_gap": "TARGET_CAPABILITY_ASSOCIATION_UNDERREPRESENTED",
        "intervention_goal": "强化场景能力表达",
        "strategy_direction_eligibility": "CONSUMABLE",
        "public_claim_eligibility": "VERIFY_FIRST",
        "reason_id": "reason-1",
        "reason_text": "目标品牌被作为场景选项",
        "reason_run_ids": [4],
        "truth_ids": [1],
        "dependencies": [],
        "scope_limitations": ["CITATION_CONTRIBUTION_RUN_1_ONLY"],
    }
    candidate = critic._strategy_candidate(direction, {"claims": []})

    assert candidate["candidate_type"] == "STRATEGY_DIRECTION"
    assert candidate["critic_input"]["model_a_judgment"]["mechanism_gap"] == direction["mechanism_gap"]
    assert "final_strategy" not in candidate["critic_input"]
    assert direction["strategy_direction_eligibility"] == "CONSUMABLE"


def test_shadow_execution_persists_signal_without_mutating_baseline(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    candidate = critic._strategy_candidate({
        "strategy_id": "strategy-1",
        "mechanism_gap": "TARGET_CAPABILITY_ASSOCIATION_UNDERREPRESENTED",
        "intervention_goal": "强化场景能力表达",
        "strategy_direction_eligibility": "CONSUMABLE",
        "public_claim_eligibility": "VERIFY_FIRST",
        "reason_id": "reason-1",
        "reason_text": "目标品牌被作为场景选项",
        "reason_run_ids": [4],
        "truth_ids": [1],
        "dependencies": [],
        "scope_limitations": [],
    }, {"claims": []})
    projection = {"projection_hash": "a" * 64, "directions": [{"strategy_id": "strategy-1"}]}
    plan = {
        "contract_version": critic.QUALIFICATION_CRITIC_CONTRACT_VERSION,
        "selection_policy": "test",
        "baseline_projection_hash": projection["projection_hash"],
        "candidate_count": 1,
        "candidates": [candidate],
        "formal_qualification_effect": "SHADOW_ONLY",
    }
    plan["plan_hash"] = critic._hash(plan)
    snapshot = {
        "analysis_id": "analysis-1",
        "context_id": "context-1",
        "project_id": 1,
        "prompt_id": 1,
        "diagnosis_id": "diagnosis-1",
        "diagnosis_result_version": "diag-v1:test",
        "diagnosis_result_hash": "b" * 64,
        "baseline_projection": projection,
        "baseline_projection_hash": projection["projection_hash"],
    }
    with factory() as db:
        db.add(SinglePromptQualificationCriticExecution(
            critic_id="critic-1",
            analysis_id="analysis-1",
            context_id="context-1",
            project_id=1,
            prompt_id=1,
            diagnosis_id="diagnosis-1",
            diagnosis_result_version="diag-v1:test",
            diagnosis_result_hash="b" * 64,
            baseline_projection_hash=projection["projection_hash"],
            idempotency_key="critic-test-key",
            input_snapshot_json=critic.dumps(snapshot),
            input_snapshot_hash=critic._hash(snapshot),
            plan_json=critic.dumps(plan),
            plan_hash=plan["plan_hash"],
            contract_version=critic.QUALIFICATION_CRITIC_CONTRACT_VERSION,
            provider="siliconflow",
            requested_model="Qwen/test",
            authorization_json=critic.dumps({"max_external_requests": 1, "max_total_tokens": 10000}),
            status="QUEUED",
        ))
        db.commit()

    monkeypatch.setattr(
        critic,
        "build_qualification_critic_plan",
        lambda *_args, **_kwargs: {"projection": projection, "plan": plan},
    )

    class FakeClient:
        call_count = 0
        external_call_count = 0
        external_token_count = 0

        def structured_generate_sync(self, **_kwargs):
            self.call_count += 1
            self.external_call_count += 1
            self.external_token_count += 20
            return {
                "critic_verdict": "AGREE",
                "issues": [],
                "counterexample": None,
                "rationale": "冻结输入内未发现明显冲突。",
            }

    critic.execute_qualification_critic("critic-1", session_factory=factory, client=FakeClient())

    with factory() as db:
        execution = db.query(SinglePromptQualificationCriticExecution).filter_by(critic_id="critic-1").one()
        result = db.query(SinglePromptQualificationCriticResult).filter_by(critic_id="critic-1").one()
        output = critic.loads(result.output_json, {})
        assert execution.status == "SHADOW_COMPLETED"
        assert execution.external_llm_calls == 1
        assert output["single_model_baseline"] == projection
        assert output["signals"][0]["critic_verdict"] == "AGREE"
        assert output["shadow_comparison"]["formal_qualification_changed"] is False
        assert output["shadow_comparison"]["formal_strategy_changed"] is False
