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
    assert positive[0]["task_id"] == positive[0]["candidate_id"]
    assert positive[0]["impact_level"] == "HIGH"
    assert positive[0]["critic_mode"] == "FALSIFICATION"
    assert positive[0]["model_a_baseline"]["evidence_relation"] == "SUPPORTS_PARTIAL"
    assert "binding-1" in positive[0]["input_object_ids"]
    assert positive[0]["semantic_input_hash"] == critic._hash(positive[0]["critic_input"])
    assert positive[0]["input_hash"] == critic._hash({
        key: value
        for key, value in positive[0].items()
        if key not in {"input_hash", "provider_payload_hash"}
    })
    system_prompt, provider_payload = critic._prompt(positive[0])
    assert positive[0]["provider_payload_hash"] == critic._hash({
        "system_prompt": system_prompt,
        "user_payload": provider_payload,
        "prompt_version": critic.QUALIFICATION_CRITIC_PROMPT_VERSION,
        "schema_version": critic.QUALIFICATION_CRITIC_SCHEMA_VERSION,
        "provider_payload_version": critic.QUALIFICATION_CRITIC_PROVIDER_PAYLOAD_VERSION,
    })
    assert related == []


def test_critic_response_schema_is_strict_and_closed():
    provider_schema = critic.QualificationCriticResponse.model_json_schema(mode="validation")
    assert provider_schema["additionalProperties"] is False
    assert provider_schema["properties"]["issue_types"]["maxItems"] == 3
    assert provider_schema["properties"]["counterexample"]["anyOf"][0]["maxLength"] == 200
    assert provider_schema["properties"]["rationale"]["maxLength"] == 300
    assert "primary_issue" in provider_schema["required"]

    valid = critic.QualificationCriticResponse.model_validate({
        "critic_verdict": "DISAGREE",
        "issue_types": ["OVERSTATED_SUPPORT"],
        "primary_issue": "OVERSTATED_SUPPORT",
        "counterexample": "来源只支持部分操作。",
        "rationale": "支持范围被扩大。",
    })
    assert valid.critic_verdict == "DISAGREE"

    with pytest.raises(ValidationError):
        critic.QualificationCriticResponse.model_validate({
            "critic_verdict": "AGREE",
            "issue_types": [],
            "primary_issue": "NONE",
            "counterexample": None,
            "rationale": "一致。",
            "final_strategy": "官网优先",
        })
    with pytest.raises(ValidationError):
        critic.QualificationCriticResponse.model_validate({
            "critic_verdict": "AGREE",
            "issues": [],
            "primary_issue": "NONE",
            "counterexample": None,
            "rationale": "旧字段不得通过。",
        })


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rationale", "理" * 301),
        ("counterexample", "证" * 201),
        ("issue_types", ["OTHER", "SUBJECT_MISMATCH", "QUALIFIER_LOSS", "SPAN_INSUFFICIENT"]),
    ],
)
def test_critic_response_schema_rejects_bounded_field_overflow(field, value):
    payload = {
        "critic_verdict": "DISAGREE",
        "issue_types": ["OTHER"],
        "primary_issue": "OTHER",
        "counterexample": None,
        "rationale": "存在一个明确问题。",
    }
    payload[field] = value
    with pytest.raises(ValidationError):
        critic.QualificationCriticResponse.model_validate(payload)


def test_critic_dynamic_gate_rejects_cross_field_and_invented_counterexample():
    candidate = critic._citation_candidates(_contribution())[0]
    validate = critic._validator(candidate)

    with pytest.raises(SemanticLLMError, match="AGREE"):
        validate({
            "critic_verdict": "AGREE",
            "issue_types": ["OTHER"],
            "primary_issue": "OTHER",
            "counterexample": None,
            "rationale": "不合法。",
        })
    with pytest.raises(SemanticLLMError, match="未逐字出现"):
        validate({
            "critic_verdict": "DISAGREE",
            "issue_types": ["OVERSTATED_SUPPORT"],
            "primary_issue": "OVERSTATED_SUPPORT",
            "counterexample": "输入里不存在的能力承诺",
            "rationale": "不合法。",
        })


def test_critic_dynamic_gate_accepts_short_terminal_contracts():
    candidate = critic._citation_candidates(_contribution())[0]
    validate = critic._validator(candidate)

    assert validate({
        "critic_verdict": "AGREE",
        "issue_types": [],
        "primary_issue": "NONE",
        "counterexample": None,
        "rationale": "未发现足以推翻当前判断的反例。",
    })["critic_verdict"] == "AGREE"
    assert validate({
        "critic_verdict": "DISAGREE",
        "issue_types": ["SPAN_INSUFFICIENT"],
        "primary_issue": "SPAN_INSUFFICIENT",
        "counterexample": "设置消息卡片",
        "rationale": "来源片段没有支持当前判断的核心对象。",
    })["critic_verdict"] == "DISAGREE"
    assert validate({
        "critic_verdict": "INSUFFICIENT_CONTEXT",
        "issue_types": [],
        "primary_issue": "INSUFFICIENT_CONTEXT",
        "counterexample": None,
        "rationale": "冻结输入不足以判断。",
    })["critic_verdict"] == "INSUFFICIENT_CONTEXT"


def test_critic_dynamic_gate_rejects_padding_and_more_than_two_sentences():
    candidate = critic._citation_candidates(_contribution())[0]
    validate = critic._validator(candidate)

    with pytest.raises(SemanticLLMError, match="空白填充"):
        validate({
            "critic_verdict": "AGREE",
            "issue_types": [],
            "primary_issue": "NONE",
            "counterexample": None,
            "rationale": "判断一致。    ",
        })
    with pytest.raises(SemanticLLMError, match="最多两句话"):
        validate({
            "critic_verdict": "AGREE",
            "issue_types": [],
            "primary_issue": "NONE",
            "counterexample": None,
            "rationale": "第一句。第二句。第三句。",
        })


def test_provider_payload_deduplicates_audit_metadata_without_losing_semantics():
    candidate = critic._citation_candidates(_contribution())[0]
    system_prompt, payload = critic._prompt(candidate)
    serialized = critic._canonical_json(payload)

    assert "不是主分析器" in system_prompt
    assert payload["semantic_input"] == candidate["critic_input"]
    assert payload["semantic_input_hash"] == candidate["semantic_input_hash"]
    assert "model_a_baseline" not in payload
    assert "rule_signals" not in payload
    assert serialized.count('"model_a_judgment"') == 1
    assert serialized.count('"rule_signals"') == 1
    assert payload["semantic_input"]["answer_unit"]["raw_text"] == "在私信自动回复中设置消息卡片。"
    assert payload["semantic_input"]["source_evidence"]["source_passage_text"] == "可以将跳转卡片与私信自动回复功能相结合。"


def test_supplemental_plan_freezes_only_exact_failed_object(monkeypatch):
    source = critic._citation_candidates(_contribution())[0]
    projection = {"projection_hash": "a" * 64}
    full_plan = {"tasks": [source], "plan_hash": "b" * 64}
    monkeypatch.setattr(
        critic,
        "build_qualification_critic_plan",
        lambda *_args, **_kwargs: {"projection": projection, "plan": full_plan},
    )

    built = critic.build_qualification_critic_supplemental_plan(
        object(),
        analysis_id="analysis-1",
        diagnosis_id="diagnosis-1",
        result_version="diag-v1:test",
        project_id=1,
        prompt_id=1,
        object_id="binding-1",
        parent_critic_id="critic-parent",
        parent_result_version="critic-v1:parent",
    )
    plan = built["plan"]
    task = plan["tasks"][0]

    assert plan["phase"] == "SHADOW_PHASE_A_CONTRACT_RECOVERY"
    assert plan["candidate_count"] == 1
    assert plan["max_external_requests"] == 1
    assert plan["automatic_retries"] == 0
    assert task["object_id"] == "binding-1"
    assert task["task_id"].startswith("critic-supplemental-")
    assert task["task_id"] != source["task_id"]
    assert task["supplements_task_id"] == source["task_id"]
    assert task["semantic_input_hash"] == source["semantic_input_hash"]
    assert task["provider_payload_hash"] != source["provider_payload_hash"]
    assert plan["plan_hash"] == critic._hash({key: value for key, value in plan.items() if key != "plan_hash"})


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
    projection = {
        "analysis_scope": {"run_ids": list(range(1, 10))},
        "evidence_scope": {
            "run_ids": [1],
            "result": {
                "result_version": "contribution-v1:test",
                "result_hash": "c" * 64,
                "processing": {"binding_count": 2},
            },
        },
        "scope_limitations": ["CITATION_CONTRIBUTION_RUN_1_ONLY"],
        "object_qualifications": [{
            "object_id": "1",
            "object_type": "PRODUCT_TRUTH",
            "quality_state": "FIRST_PARTY_ASSERTED",
            "provenance": {"source": "MANUAL_CONFIRMED"},
            "eligibility_by_use": {"strategy_direction": "CONSUMABLE", "public_claim": "VERIFY_FIRST"},
            "scope_limitation": ["SOURCE_REFERENCE_REQUIRED"],
        }],
    }
    candidate = critic._strategy_candidate(direction, {"claims": [{
        "truth_id": 1,
        "text": "支持活码更新",
        "scope": "TARGET_BRAND_ONLY",
        "conditions": [],
        "truth_provenance": "FIRST_PARTY_ASSERTED",
    }]}, projection)

    assert candidate["candidate_type"] == "STRATEGY_DIRECTION"
    assert candidate["critic_input"]["strategy"]["mechanism_gap"] == direction["mechanism_gap"]
    assert candidate["impact_level"] == "HIGH"
    assert candidate["critic_mode"] == "FALSIFICATION"
    assert candidate["input_hash"] == critic._hash({
        key: value
        for key, value in candidate.items()
        if key not in {"input_hash", "provider_payload_hash"}
    })
    assert candidate["semantic_input_hash"] == critic._hash(candidate["critic_input"])
    assert candidate["critic_input"]["truth_dependencies"][0]["statement"] == "支持活码更新"
    assert candidate["critic_input"]["truth_dependencies"][0]["verification_state"] == "FIRST_PARTY_ASSERTED"
    assert candidate["critic_input"]["scope_contract"]["answer_intelligence"]["run_ids"] == list(range(1, 10))
    assert candidate["critic_input"]["scope_contract"]["citation_contribution"]["run_ids"] == [1]
    assert candidate["critic_input"]["evidence_dependency"]["eligibility"] == "OBSERVE_ONLY"
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
        "tasks": [candidate],
        "estimated_token_ceiling": critic._estimated_task_tokens(candidate),
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
        seen_max_tokens: list[int] = []

        def structured_generate_sync(self, **kwargs):
            self.call_count += 1
            self.external_call_count += 1
            self.external_token_count += 20
            self.seen_max_tokens.append(kwargs["max_tokens"])
            return {
                "critic_verdict": "AGREE",
                "issue_types": [],
                "primary_issue": "NONE",
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
        assert FakeClient.seen_max_tokens == [1600]
