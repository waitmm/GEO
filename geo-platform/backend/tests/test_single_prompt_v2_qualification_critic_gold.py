from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import (
    Base,
    SinglePromptQualificationCriticExecution,
    SinglePromptQualificationCriticGoldReview,
    SinglePromptQualificationCriticResult,
)
from app.modules.single_prompt_v2 import qualification_critic_gold as gold
from app.services.serialization import dumps


def _signal(object_id: str, candidate_type: str, verdict: str, issue: str) -> dict:
    return {
        "task_id": f"task-{object_id}",
        "candidate_type": candidate_type,
        "object_id": object_id,
        "input_hash": (object_id[-1] * 64),
        "processing_status": "DONE",
        "model_a_baseline": (
            {"evidence_relation": "SUPPORTS_PARTIAL", "correspondence_mode": "FAITHFUL_PARAPHRASE"}
            if candidate_type == "CITATION_RELATION"
            else {"strategy_direction_eligibility": "CONSUMABLE", "public_claim_eligibility": "VERIFY_FIRST"}
        ),
        "rule_signals": {"span_validation": {"answer_span_present": True}},
        "critic_verdict": verdict,
        "issue_types": [] if issue == "NONE" else [issue],
        "primary_issue": issue,
        "counterexample": None,
        "rationale": "测试判断。",
        "critic_input": {"object": object_id},
    }


def _execution(critic_id: str, *, status: str = "SHADOW_COMPLETED") -> SinglePromptQualificationCriticExecution:
    return SinglePromptQualificationCriticExecution(
        critic_id=critic_id,
        analysis_id="analysis-1",
        context_id="context-1",
        project_id=1,
        prompt_id=1,
        diagnosis_id="diagnosis-1",
        diagnosis_result_version="diag-v1:test",
        diagnosis_result_hash="d" * 64,
        baseline_projection_hash="p" * 64,
        idempotency_key=f"key-{critic_id}",
        input_snapshot_json="{}",
        input_snapshot_hash="i" * 64,
        plan_json="{}",
        plan_hash="l" * 64,
        contract_version="v3",
        provider="siliconflow",
        requested_model="Qwen/test",
        authorization_json="{}",
        status=status,
    )


def _database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_phase_b1_freezes_exact_candidates_and_saves_append_only_gold():
    factory = _database()
    phase_output = {
        "phase": "SHADOW_PHASE_A_CRITIC_BEHAVIOR_VALIDATION",
        "input_identity": {
            "diagnosis_result_version": "diag-v1:test",
            "diagnosis_result_hash": "d" * 64,
        },
        "single_model_baseline": {
            "evidence_scope": {"result": {"result_version": "contribution-v1:test", "result_hash": "c" * 64}},
        },
        "signals": [
            _signal("binding-a", "CITATION_RELATION", "DISAGREE", "SUBJECT_MISMATCH"),
            _signal("strategy-a", "STRATEGY_DIRECTION", "DISAGREE", "STRATEGY_GAP_MISMATCH"),
        ],
    }
    supplemental_output = {
        "phase": "SHADOW_PHASE_A_CONTRACT_RECOVERY",
        "input_identity": {
            "diagnosis_result_version": "diag-v1:test",
            "diagnosis_result_hash": "d" * 64,
            "parent_critic_id": "critic-phase-a",
            "parent_result_version": "critic-v1:phase-a",
        },
        "single_model_baseline": phase_output["single_model_baseline"],
        "signals": [_signal("binding-b", "CITATION_RELATION", "DISAGREE", "OVERSTATED_SUPPORT")],
    }
    with factory() as db:
        db.add_all([_execution("critic-phase-a"), _execution("critic-supplemental")])
        db.add_all([
            SinglePromptQualificationCriticResult(
                result_version="critic-v1:phase-a",
                critic_id="critic-phase-a",
                version_number=1,
                output_json=dumps(phase_output),
                output_hash=gold._hash(phase_output),
            ),
            SinglePromptQualificationCriticResult(
                result_version="critic-supplemental-v1:test",
                critic_id="critic-supplemental",
                version_number=1,
                output_json=dumps(supplemental_output),
                output_hash=gold._hash(supplemental_output),
            ),
        ])
        db.commit()

        review_set = gold.build_critic_gold_review_set(
            db,
            analysis_id="analysis-1",
            phase_a_critic_id="critic-phase-a",
            phase_a_result_version="critic-v1:phase-a",
            project_id=1,
            prompt_id=1,
        )
        assert review_set["candidate_count"] == 3
        assert review_set["supplemental_result_versions"] == ["critic-supplemental-v1:test"]
        assert db.query(SinglePromptQualificationCriticGoldReview).count() == 0
        candidates = {item["object_id"]: item for item in review_set["candidates"]}
        decisions = [
            {
                "object_id": "binding-a",
                "gold_identity": candidates["binding-a"]["gold_identity"],
                "gold_model_a_correct": False,
                "gold_qwen_challenge_valid": "YES",
                "gold_issue_type": "SUBJECT_MISMATCH",
                "gold_effective_relation_or_strategy_judgment": "RELATED_ONLY",
                "should_change_qualification": True,
                "should_change_strategy_or_claim": "NONE",
                "review_note": "主体不同，Qwen 成功发现错误。",
            },
            {
                "object_id": "binding-b",
                "gold_identity": candidates["binding-b"]["gold_identity"],
                "gold_model_a_correct": True,
                "gold_qwen_challenge_valid": "NO",
                "gold_issue_type": "OVERSTATED_SUPPORT",
                "gold_effective_relation_or_strategy_judgment": "SUPPORTS_PARTIAL",
                "should_change_qualification": False,
                "should_change_strategy_or_claim": "NONE",
                "review_note": "部分支持已经保留范围，质疑过度。",
            },
            {
                "object_id": "strategy-a",
                "gold_identity": candidates["strategy-a"]["gold_identity"],
                "gold_model_a_correct": True,
                "gold_qwen_challenge_valid": "NO",
                "gold_issue_type": "STRATEGY_GAP_MISMATCH",
                "gold_effective_relation_or_strategy_judgment": "PUBLIC_CLAIM_ONLY_BLOCKED",
                "should_change_qualification": False,
                "should_change_strategy_or_claim": "PUBLIC_CLAIM",
                "review_note": "策略方向成立，公开声明仍需来源。",
            },
        ]
        completed = gold.complete_critic_gold_review(
            db,
            analysis_id="analysis-1",
            phase_a_critic_id="critic-phase-a",
            phase_a_result_version="critic-v1:phase-a",
            project_id=1,
            prompt_id=1,
            expected_phase_a_result_hash=review_set["phase_a_result_hash"],
            expected_reviewable_set_hash=review_set["reviewable_set_hash"],
            expected_prior_review_id=None,
            decisions=decisions,
            reviewer="owner",
            note="B1",
        )

        assert len(completed["reviews"]) == 1
        metrics = completed["reviews"][0]["metrics"]
        assert metrics["qwen_true_challenges"] == 1
        assert metrics["qwen_false_challenges"] == 2
        assert metrics["correctly_fixed_object_ids"] == ["binding-a"]
        assert set(metrics["erroneously_downgraded_object_ids"]) == {"binding-b", "strategy-a"}
        assert metrics["qwen_issue_type_distribution"]["SUBJECT_MISMATCH"] == 1
        assert metrics["human_issue_type_distribution"]["SUBJECT_MISMATCH"] == 1
        assert metrics["core_questions"]["brand_subject_extrapolation"]["true_challenge_count"] == 1
        assert metrics["core_questions"]["strategy_direction_vs_public_claim_confusion_object_ids"] == ["strategy-a"]
        assert metrics["core_questions"]["supplemental_overstated_support_rejected_object_ids"] == ["binding-b"]
        assert metrics["overall_accuracy"] == "NOT_COMPUTED_BY_CONTRACT"
        assert db.query(SinglePromptQualificationCriticResult).count() == 2

        revised = gold.complete_critic_gold_review(
            db,
            analysis_id="analysis-1",
            phase_a_critic_id="critic-phase-a",
            phase_a_result_version="critic-v1:phase-a",
            project_id=1,
            prompt_id=1,
            expected_phase_a_result_hash=review_set["phase_a_result_hash"],
            expected_reviewable_set_hash=review_set["reviewable_set_hash"],
            expected_prior_review_id=completed["reviews"][0]["review_id"],
            decisions=decisions,
            reviewer="owner",
            note="B1 revision",
        )
        assert len(revised["reviews"]) == 2
        assert revised["reviews"][1]["version_number"] == 2
        assert revised["reviews"][1]["parent_review_id"] == revised["reviews"][0]["review_id"]
        assert db.query(SinglePromptQualificationCriticResult).count() == 2


def test_phase_b1_rejects_stale_or_incomplete_review_set():
    factory = _database()
    output = {
        "phase": "SHADOW_PHASE_A_CRITIC_BEHAVIOR_VALIDATION",
        "input_identity": {"diagnosis_result_version": "diag-v1:test", "diagnosis_result_hash": "d" * 64},
        "single_model_baseline": {"evidence_scope": {"result": {"result_version": "c", "result_hash": "h"}}},
        "signals": [_signal("binding-a", "CITATION_RELATION", "AGREE", "NONE")],
    }
    with factory() as db:
        db.add(_execution("critic-phase-a"))
        db.add(SinglePromptQualificationCriticResult(
            result_version="critic-v1:phase-a",
            critic_id="critic-phase-a",
            version_number=1,
            output_json=dumps(output),
            output_hash=gold._hash(output),
        ))
        db.commit()
        review_set = gold.build_critic_gold_review_set(
            db,
            analysis_id="analysis-1",
            phase_a_critic_id="critic-phase-a",
            phase_a_result_version="critic-v1:phase-a",
            project_id=1,
            prompt_id=1,
        )
        with pytest.raises(HTTPException) as rejected:
            gold.complete_critic_gold_review(
                db,
                analysis_id="analysis-1",
                phase_a_critic_id="critic-phase-a",
                phase_a_result_version="critic-v1:phase-a",
                project_id=1,
                prompt_id=1,
                expected_phase_a_result_hash=review_set["phase_a_result_hash"],
                expected_reviewable_set_hash="x" * 64,
                expected_prior_review_id=None,
                decisions=[],
                reviewer="owner",
                note="",
            )
        assert rejected.value.detail["code"] == "CRITIC_GOLD_SET_STALE"
        assert db.query(SinglePromptQualificationCriticGoldReview).count() == 0
