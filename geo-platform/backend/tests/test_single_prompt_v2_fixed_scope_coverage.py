from __future__ import annotations

import hashlib

from app.modules.single_prompt_v2.coverage import (
    compute_coverage,
    diagnosis_coverage_projections,
)
from app.modules.single_prompt_v2.diagnosis import (
    _technical_claim_failure,
    _validated_source_claims,
)
from app.modules.single_prompt_v2.evidence_plan import build_evidence_candidate_plan
from app.modules.single_prompt_v2.llm_safety import V2SourceClaimJudge


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _raw_runs() -> dict:
    return {
        "runs": [
            {"run_id": run_id, "status": "success", "answer_text": f"回答 {run_id}"}
            for run_id in range(1, 10)
        ]
    }


def test_fixed_nine_run_coverage_separates_valid_pending_and_zero():
    raw = _raw_runs()
    jobs = []
    for run_id in (4, 5):
        jobs.append({"answer_hash": _hash(f"回答 {run_id}"), "run_ids": [run_id], "status": "DONE"})
    jobs.append({"answer_hash": _hash("回答 6"), "run_ids": [6], "status": "DONE_ZERO_EVENTS"})
    for run_id in (1, 2, 3, 7, 8, 9):
        jobs.append({
            "answer_hash": _hash(f"回答 {run_id}"),
            "run_ids": [run_id],
            "status": "PENDING_EXTERNAL_AUTHORIZATION",
            "result_source": "CACHE_MISS_EXTERNAL_NOT_AUTHORIZED",
        })

    coverage = compute_coverage(raw, {"answer_jobs": jobs})

    assert coverage["valid_compute_run_ids"] == [4, 5, 6]
    assert coverage["success_zero_events_run_ids"] == [6]
    assert coverage["pending_external_authorization_run_ids"] == [1, 2, 3, 7, 8, 9]
    assert coverage["actual_failure_run_ids"] == []
    assert coverage["valid_compute_count"] == 3
    assert coverage["expected_run_count"] == 9
    assert coverage["all_runs_validly_understood"] is False


def test_invalid_cache_keeps_rejection_separate_from_next_required_action():
    raw = {"runs": [{"run_id": 1, "status": "success", "answer_text": "回答 1"}]}
    answer = {"answer_jobs": [{
        "answer_hash": _hash("回答 1"),
        "run_ids": [1],
        "status": "CACHE_REJECTED_BY_V2_VALIDATION",
        "result_source": "LLM_CALL_CACHE",
        "audit": {"validation_errors": [{"location": "events.0"}]},
    }]}

    coverage = compute_coverage(raw, answer)

    assert coverage["invalid_cache_run_ids"] == [1]
    assert coverage["pending_external_authorization_run_ids"] == [1]
    assert coverage["actual_failure_run_ids"] == []


def test_unavailable_input_is_preserved_in_denominator_and_excluded_from_compute_groups():
    raw = {
        "runs": [
            {"run_id": 1, "status": "failed", "answer_text": "过期回答"},
            {"run_id": 2, "status": "success", "answer_text": ""},
            {"run_id": 3, "status": "partial_success", "answer_text": "部分回答"},
            {"run_id": 4, "answer_text": "遗留回答"},
        ]
    }
    answer = {
        "answer_jobs": [
            {"answer_hash": _hash("过期回答"), "run_ids": [1], "status": "DONE"},
            {"answer_hash": _hash("部分回答"), "run_ids": [3], "status": "DONE_ZERO_EVENTS"},
            {"answer_hash": _hash("遗留回答"), "run_ids": [4], "status": "DONE"},
        ]
    }

    projections = diagnosis_coverage_projections(
        raw,
        {"answer_diagnosis": answer, "evidence_diagnosis": {}},
        None,
    )
    input_scope = projections["input_scope_coverage"]
    coverage = projections["compute_coverage"]

    assert input_scope["bound_run_ids"] == [3, 4]
    assert input_scope["missing_run_ids"] == [1, 2]
    assert input_scope["input_unavailable_run_ids"] == [1, 2]
    assert "1" not in input_scope["answer_sha256_by_run"]
    assert coverage["input_unavailable_run_ids"] == [1, 2]
    assert coverage["pending_compute_run_ids"] == []
    assert coverage["pending_external_authorization_run_ids"] == []
    assert coverage["actual_failure_run_ids"] == []
    assert coverage["success_zero_events_run_ids"] == [3]
    assert coverage["success_with_events_run_ids"] == [4]
    assert coverage["valid_compute_run_ids"] == [3, 4]
    assert coverage["expected_run_count"] == 4
    assert coverage["all_runs_validly_understood"] is False
    assert coverage["all_runs_have_terminal_disposition"] is False


def test_review_and_strategy_scope_do_not_turn_partial_compute_into_full_completion():
    raw = _raw_runs()
    answer = {
        "events": [],
        "market_criteria": [],
        "failures": [],
        "answer_jobs": [
            {"answer_hash": _hash(f"回答 {run_id}"), "run_ids": [run_id], "status": "DONE_ZERO_EVENTS"}
            if run_id in (4, 5, 6)
            else {
                "answer_hash": _hash(f"回答 {run_id}"),
                "run_ids": [run_id],
                "status": "PENDING_EXTERNAL_AUTHORIZATION",
                "result_source": "CACHE_MISS_EXTERNAL_NOT_AUTHORIZED",
            }
            for run_id in range(1, 10)
        ],
    }
    projections = diagnosis_coverage_projections(
        raw,
        {"answer_diagnosis": answer, "evidence_diagnosis": {}},
        {"decision": "REVIEW_COMPLETED", "decisions": []},
    )

    assert projections["review_coverage"]["reviewed_run_ids"] == [4, 5, 6]
    assert projections["review_coverage"]["full_scope_review_complete"] is False
    assert projections["strategy_dependency_coverage"]["global_nine_run_conclusion_eligible"] is False


def test_candidate_plan_is_same_run_stable_diverse_and_not_fixed_top_two():
    reasons = [{
        "reason_id": "reason-1",
        "run_id": 4,
        "effective_grounded_text": "生成加密短链并追踪数据",
    }]
    passages = [
        {
            "passage_id": f"p-{index}",
            "snapshot_id": f"s-{index}",
            "source_key": f"source-{index}",
            "text": f"生成加密短链并追踪数据，来源内容 {index}",
        }
        for index in range(1, 9)
    ] + [{
        "passage_id": "other-run",
        "snapshot_id": "other-snapshot",
        "source_key": "other-source",
        "text": "生成加密短链并追踪数据",
    }]
    observed = {4: {f"source-{index}" for index in range(1, 9)}, 7: {"other-source"}}

    first = build_evidence_candidate_plan(reasons, passages, observed)
    second = build_evidence_candidate_plan(reasons, list(reversed(passages)), observed)
    plan = first["reason_plans"][0]

    assert first["plan_hash"] == second["plan_hash"]
    assert len(plan["base_candidates"]) >= 5
    assert len(plan["base_candidates"]) != 2
    assert "other-run" not in {row["passage_id"] for row in plan["base_candidates"] + plan["fallback_queue"]}
    assert len({row["source_key"] for row in plan["base_candidates"]}) == len(plan["base_candidates"])
    assert plan["fallback_replacement_cap"] == 3


def test_source_claim_valid_envelope_isolated_per_item_after_schema_gate():
    passage = {"passage_id": "p-1", "text": "爱短链支持生成加密短链，并提供数据追踪。"}
    response = {
        "claims": [
            {
                "normalized_claim": "爱短链支持生成加密短链",
                "subject_text": "爱短链",
                "predicate": "支持",
                "object_text": "生成加密短链",
                "claim_type": "CAPABILITY",
                "polarity": "POSITIVE",
                "source_span": "爱短链支持生成加密短链",
            },
            {
                "normalized_claim": "不存在主体支持数据追踪",
                "subject_text": "不存在主体",
                "predicate": "支持",
                "object_text": "数据追踪",
                "claim_type": "CAPABILITY",
                "polarity": "POSITIVE",
                "source_span": "并提供数据追踪",
            },
        ]
    }

    class Client:
        def structured_generate_sync(self, **kwargs):
            return kwargs["response_validator"](response)

    admitted = V2SourceClaimJudge(Client()).judge_passage(passage["text"])
    accepted, rejected = _validated_source_claims(passage, admitted)

    assert len(accepted) == 1
    assert accepted[0]["subject_text"] == "爱短链"
    assert len(rejected) == 1
    assert rejected[0]["claim_index"] == 1
    assert rejected[0]["status"] == "FAILED_SEMANTIC_SCOPE"
    assert _technical_claim_failure({"status": "FAILED_VALIDATION"}) is True
    assert _technical_claim_failure({"status": "DONE_ZERO_CLAIMS"}) is False
    assert _technical_claim_failure({"status": "DONE"}) is False
