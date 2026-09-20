from __future__ import annotations

import copy
import hashlib
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    OptimizationAction,
    OptimizationExperiment,
    OptimizationStrategyCandidate,
    SinglePromptAnalysisContext,
    SinglePromptDiagnosisExecution,
    SinglePromptDiagnosisResult,
    SinglePromptDiagnosisReview,
    SinglePromptSourceSnapshot,
    SinglePromptStrategyExecution,
    SinglePromptStrategyResult,
    SinglePromptStrategyReview,
)
from app.modules.single_prompt_v2.strategy import (
    STRATEGY_INPUT_VALIDATION_VERSION,
    _candidate_output,
    _reason_rows,
    _validate_candidate_output,
    build_strategy_input_projection,
    build_strategy_readiness,
    complete_strategy_review,
    create_strategy_candidate,
    evaluate_strategy_readiness,
    get_strategy_status,
    revise_strategy_priority,
)


def _hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _projection(*, reviewed=True, foundation=None, anchor="UNPROVEN", include_truth=True, evaluated=True):
    reason = {
        "reason_id": "reason-1",
        "event_id": "event-1",
        "run_id": 101,
        "entity_text": "竞品甲",
        "effective_speech_act": "RECOMMEND",
        "grounded_text": "支持批量生成二维码",
        "normalized_display_text": "支持批量生成二维码",
        "fact_consumption_eligible": True,
        "local_revalidation": {"status": "VERIFIED_CONSERVATIVE"},
    }
    review = {
        "review_id": "review-1",
        "diagnosis_id": "diagnosis-1",
        "result_version": "diag-v1:fixture",
        "result_hash": "a" * 64,
        "reviewable_set_hash": "b" * 64,
        "prior_review_id": None,
        "decision": "REVIEW_COMPLETED",
        "decisions": [{"scope": "ENTIRE_REVIEWABLE_SET", "decision": "REVIEW_COMPLETED_WITH_LIMITATIONS_PRESERVED"}],
    } if reviewed else None
    truth_snapshot = [{
        "truth_id": 7,
        "capability_key": "batch_qr",
        "capability_label": "批量生成二维码",
        "product_truth_status": "SUPPORTED",
        "truth_source": "MANUAL_CONFIRMED",
    }] if include_truth else []
    truth_relationships = [{
        "relationship_id": "truth-rel-1",
        "reason_id": "reason-1",
        "truth_id": 7,
        "effective_relation": "FULLY_COVERS",
    }] if include_truth else [{
        "relationship_id": "truth-rel-1",
        "reason_id": "reason-1",
        "truth_id": None,
        "effective_relation": "UNRESOLVED",
    }]
    relation = {
        "relation_id": "evidence-rel-1",
        "reason_id": "reason-1",
        "source_snapshot_id": "source-1",
        "reference_observation": "OBSERVED",
        "anchor_binding": anchor,
        "candidate_recall": "RECALLED",
        "alignment_evaluation": "EVALUATED" if evaluated else "NOT_EVALUATED",
        "effective_relation": "SOURCE_SUPPORTS_REASON" if evaluated else None,
    }
    projection = {
        "contract_version": STRATEGY_INPUT_VALIDATION_VERSION,
        "identity": {
            "analysis_id": "analysis-1",
            "context_id": "context-1",
            "diagnosis_id": "diagnosis-1",
            "project_id": 1,
            "prompt_id": 44,
            "diagnosis_result_version": "diag-v1:fixture",
            "diagnosis_result_hash": "a" * 64,
            "reviewable_set_hash": "b" * 64,
            "raw_output_hash": "c" * 64,
            "diagnosis_contract_config_hash": "d" * 64,
        },
        "diagnosis_review": review,
        "review_snapshot_hash": _hash(review) if review else None,
        "reasons": [reason],
        "truth_snapshot": truth_snapshot,
        "truth_relationships": truth_relationships,
        "evidence_relations": [relation],
        "source_claim_jobs": [],
        "source_snapshots": [{
            "snapshot_id": "source-1",
            "source_key": "source-key-1",
            "canonical_url": "https://www.zhihu.com/question/1",
            "title": "知乎来源",
            "content_hash": "e" * 64,
            "passages_hash": "f" * 64,
            "fetch_status": "SUCCESS",
            "reference_observations": [{"run_id": 101, "domain": "zhihu.com"}],
            "source_role": None,
            "channel": {"channel_key": "ZHIHU", "channel_label": "知乎", "recognized_execution_channel": True},
        }],
        "foundation_assessment": foundation or {},
        "effective_evidence_eligibility": {
            "contract_version": "single_prompt_source_content_gate.v1",
            "eligible_snapshot_ids": ["source-1"],
            "blocked_snapshots": [],
            "effective_evidence_relation_ids": ["evidence-rel-1"] if evaluated else [],
            "content_blocked_current": 0,
        },
        "limitations": ([{"code": "REFERENCE_ANCHOR_UNPROVEN", "count": 1}] if anchor == "UNPROVEN" else []),
        "advisories": [],
        "validation_versions": {"strategy_input": STRATEGY_INPUT_VALIDATION_VERSION},
        "consumed_object_ids": {
            "event_ids": ["event-1"],
            "reason_ids": ["reason-1"],
            "truth_ids": ["7"] if include_truth else [],
            "truth_relationship_ids": ["truth-rel-1"],
            "evidence_relation_ids": ["evidence-rel-1"],
            "source_snapshot_ids": ["source-1"],
        },
        "is_active_result": True,
    }
    projection["input_snapshot_hash"] = _hash({key: value for key, value in projection.items() if key != "input_snapshot_hash"})
    return projection


def _session(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{(tmp_path / 'v2-strategy.db').as_posix()}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


def test_partially_covers_is_not_a_strategy_qualification_gate():
    projection = _projection()
    projection["truth_relationships"][0]["effective_relation"] = "PARTIALLY_COVERS"

    readiness = evaluate_strategy_readiness(projection)

    assert readiness["classification"] == "B"
    assert readiness["qualified_direction_count"] == 0
    assert readiness["blocker"]["code"] == "NO_ELIGIBLE_STRATEGY_DIRECTION"


def test_event_level_review_gate_controls_reason_consumption_without_role_upgrade():
    context = SinglePromptAnalysisContext(
        raw_output_json=json.dumps({"runs": [{"run_id": 101, "answer_text": "工具甲适合批量短链。"}]})
    )
    output = {
        "answer_diagnosis": {
            "events": [{
                "event_id": "event-review",
                "run_id": 101,
                "entity_text": "工具甲",
                "machine_speech_act": "INCLUDE_AS_OPTION",
                "effective_speech_act": "INCLUDE_AS_OPTION",
                "semantic_validation_status": "SEMANTIC_REVIEW_REQUIRED",
                "fact_consumption_eligible": False,
                "reasons": [{
                    "reason_id": "reason-review",
                    "reason_span": "批量短链",
                    "effective_grounded_text": "批量短链",
                    "normalized_reason": "批量短链",
                    "fact_consumption_eligible": True,
                }],
            }]
        }
    }

    assert _reason_rows(output, context)[0]["fact_consumption_eligible"] is False
    confirmed = _reason_rows(output, context, {
        "decisions": [{
            "scope": "ANSWER_SEMANTIC_EVENT",
            "event_id": "event-review",
            "decision": "CONFIRM_INCLUDE_AS_OPTION",
        }]
    })[0]
    assert confirmed["fact_consumption_eligible"] is True
    assert confirmed["effective_speech_act"] == "INCLUDE_AS_OPTION"
    assert confirmed["event_review_decision"] == "CONFIRM_INCLUDE_AS_OPTION"

    unresolved = _reason_rows(output, context, {
        "decisions": [{
            "scope": "ANSWER_SEMANTIC_EVENT",
            "event_id": "event-review",
            "decision": "KEEP_UNRESOLVED",
        }]
    })[0]
    assert unresolved["fact_consumption_eligible"] is False


def _seed_strategy_input(db, *, reviewed=True, include_truth=True, anchor="UNPROVEN", foundation=None):
    answer = "竞品甲值得推荐，因为支持批量生成二维码。"
    output = {
        "contract_version": "single_prompt_diagnosis.v2_second_slice",
        "answer_diagnosis": {"events": [{
            "event_id": "event-1",
            "run_id": 101,
            "entity_text": "竞品甲",
            "effective_speech_act": "RECOMMEND",
            "reasons": [{
                "reason_id": "reason-1",
                "reason_span": "支持批量生成二维码",
                "normalized_reason": "支持批量生成二维码",
                "fact_consumption_eligible": True,
            }],
        }], "unresolved_items": [], "failures": []},
        "source_diagnosis": {"snapshots": [{"snapshot_id": "source-1"}]},
        "evidence_diagnosis": {"source_relations": [{
            "relation_id": "evidence-rel-1",
            "reason_id": "reason-1",
            "source_snapshot_id": "source-1",
            "reference_observation": "OBSERVED",
            "anchor_binding": anchor,
            "candidate_recall": "RECALLED",
            "alignment_evaluation": "EVALUATED",
            "effective_relation": "SOURCE_SUPPORTS_REASON",
        }], "source_claim_jobs": []},
        "truth_diagnosis": {
            "truth_snapshot": [{
                "truth_id": 7,
                "capability_key": "batch_qr",
                "capability_label": "批量生成二维码",
                "product_truth_status": "SUPPORTED",
                "truth_source": "MANUAL_CONFIRMED",
            }] if include_truth else [],
            "relationships": [{
                "relationship_id": "truth-rel-1",
                "reason_id": "reason-1",
                "truth_id": 7 if include_truth else None,
                "effective_relation": "FULLY_COVERS" if include_truth else "UNRESOLVED",
            }],
        },
        "foundation_assessment": foundation or {},
        "limitations": [],
        "stats": {"content_ready": 1},
    }
    result_hash = _hash(output)
    context = SinglePromptAnalysisContext(
        context_id="context-1", analysis_id="analysis-1", project_id=1, prompt_id=44, task_id=52,
        result_version="raw-v1:fixture", run_scope_json="[101]", run_scope_hash="r" * 64,
        raw_output_json=json.dumps({"runs": [{"run_id": 101, "answer_text": answer}]}),
        raw_output_hash="c" * 64, valid_run_count=1, failed_run_count=0,
    )
    execution = SinglePromptDiagnosisExecution(
        diagnosis_id="diagnosis-1", analysis_id="analysis-1", context_id="context-1", project_id=1, prompt_id=44,
        idempotency_key="diagnosis-fixture", input_fingerprint="i" * 64, raw_output_hash="c" * 64,
        brand_snapshot_json="{}", brand_snapshot_hash="b" * 64, truth_snapshot_json="[]", truth_set_hash="t" * 64,
        contract_config_json="{}", contract_config_hash="d" * 64, status="READY_FOR_REVIEW",
        progress_json="{}", active_result_version="diag-v1:fixture",
    )
    result = SinglePromptDiagnosisResult(
        result_version="diag-v1:fixture", diagnosis_id="diagnosis-1", version_number=1,
        output_json=json.dumps(output, ensure_ascii=False), output_hash=result_hash,
        reviewable_set_hash="q" * 64, limitations_json="[]", stats_json=json.dumps({"content_ready": 1}),
    )
    source = SinglePromptSourceSnapshot(
        snapshot_id="source-1", diagnosis_id="diagnosis-1", source_key="source-key-1",
        canonical_url="https://www.zhihu.com/question/1", original_urls_json="[]",
        reference_observations_json=json.dumps([{"run_id": 101, "domain": "zhihu.com"}]), occurrence_count=1,
        fetch_status="SUCCESS", title="知乎来源", content_hash="e" * 64, clean_text="正文支持批量生成二维码",
        passages_json="[]", passages_hash="f" * 64, parser_version="fixture",
    )
    db.add_all([context, execution, result, source])
    if reviewed:
        db.add(SinglePromptDiagnosisReview(
            review_id="review-1", diagnosis_id="diagnosis-1", result_version="diag-v1:fixture",
            result_hash=result_hash, reviewable_set_hash="q" * 64, decision="REVIEW_COMPLETED",
            decisions_json=json.dumps([{"scope": "ENTIRE_REVIEWABLE_SET", "decision": "REVIEW_COMPLETED_WITH_LIMITATIONS_PRESERVED"}]),
            reviewer="owner",
        ))
    db.commit()
    return result_hash


def test_a_class_requires_exact_review_and_has_no_candidate():
    readiness = evaluate_strategy_readiness(_projection(reviewed=False, include_truth=False, evaluated=False))
    assert readiness["classification"] == "A"
    assert readiness["blocker"]["code"] == "DIAGNOSIS_REVIEW_REQUIRED"
    assert readiness["can_create_strategy"] is False
    assert readiness["foundation"]["state"] == "UNKNOWN"
    assert readiness["qualified_directions"] == []
    assert readiness["legal_next_steps"] == ["COMPLETE_DIAGNOSIS_REVIEW"]


def test_b_class_returns_concrete_work_without_empty_strategy():
    readiness = evaluate_strategy_readiness(_projection(include_truth=False, evaluated=False))
    assert readiness["classification"] == "B"
    assert readiness["qualified_direction_count"] == 0
    assert readiness["blocker"]["code"] == "NO_ELIGIBLE_STRATEGY_DIRECTION"
    assert {row["code"] for row in readiness["verification_items"]} >= {
        "TARGET_BRAND_TRUTH_UNRESOLVED", "EVIDENCE_RELATION_NOT_EVALUATED", "FOUNDATION_REQUIREMENT_UNKNOWN",
    }


def test_foundation_can_be_actionable_without_primary_channel():
    foundation = {
        "assessment_id": "asset-gap-1",
        "state": "CONFIRMED_MISSING",
        "truth_ids": [7],
        "evidence_ids": ["asset-audit-1"],
    }
    projection = _projection(foundation=foundation, evaluated=False)
    readiness = evaluate_strategy_readiness(projection)
    assert readiness["classification"] == "C"
    assert readiness["foundation"]["state"] == "REQUIRED"
    assert [row["direction_type"] for row in readiness["qualified_directions"]] == ["FOUNDATION"]
    assert not any(row.get("channel_role") == "PRIMARY" for row in readiness["qualified_directions"])


def test_foundation_unknown_does_not_block_independent_channel_test():
    readiness = evaluate_strategy_readiness(_projection(anchor="UNPROVEN"))
    assert readiness["classification"] == "C"
    assert readiness["foundation"]["state"] == "UNKNOWN"
    assert [(row["channel_key"], row["channel_role"]) for row in readiness["qualified_directions"]] == [("ZHIHU", "TEST")]
    assert readiness["qualified_directions"][0]["effect_status"] == "NOT_PROVEN"


def test_explicit_anchor_can_form_primary_but_review_does_not_upgrade_bad_relation():
    primary = evaluate_strategy_readiness(_projection(anchor="EXPLICIT"))
    assert primary["qualified_directions"][0]["channel_role"] == "PRIMARY"
    blocked = evaluate_strategy_readiness(_projection(anchor="EXPLICIT", evaluated=False))
    assert blocked["classification"] == "B"
    assert blocked["qualified_directions"] == []


def test_same_level_directions_require_human_priority_without_score():
    foundation = {
        "assessment_id": "asset-gap-1", "state": "CONFIRMED_MISSING",
        "truth_ids": [7], "evidence_ids": ["asset-audit-1"],
    }
    readiness = evaluate_strategy_readiness(_projection(foundation=foundation))
    assert readiness["qualified_direction_count"] == 2
    assert readiness["needs_human_prioritization"] is True
    assert {row["priority_order"] for row in readiness["qualified_directions"]} == {None}
    assert not any("score" in row for row in readiness["qualified_directions"])


def test_closed_world_validator_rejects_unknown_reason_and_foundation_channel():
    projection = _projection()
    readiness = evaluate_strategy_readiness(projection)
    output = _candidate_output("strategy-fixture", projection, readiness)
    output["directions"][0]["reason_ids"] = ["reason-outside-input"]
    with pytest.raises(HTTPException) as unknown:
        _validate_candidate_output(output, projection)
    assert unknown.value.status_code == 422

    foundation = {
        "assessment_id": "asset-gap-1", "state": "CONFIRMED_MISSING",
        "truth_ids": [7], "evidence_ids": ["asset-audit-1"],
    }
    projection = _projection(foundation=foundation, evaluated=False)
    readiness = evaluate_strategy_readiness(projection)
    output = _candidate_output("strategy-fixture", projection, readiness)
    output["directions"][0]["channel_key"] = "OFFICIAL_SITE"
    with pytest.raises(HTTPException) as channel:
        _validate_candidate_output(output, projection)
    assert channel.value.status_code == 422


def test_review_snapshot_hash_is_stable_and_ignores_display_metadata():
    first = _projection()
    second = copy.deepcopy(first)
    second["display_loaded_at"] = "tomorrow"
    second["display_copy"] = "different wording"
    assert first["review_snapshot_hash"] == second["review_snapshot_hash"]
    second["diagnosis_review"]["decision"] = "OTHER"
    assert _hash(second["diagnosis_review"]) != first["review_snapshot_hash"]


def test_db_generation_returns_exact_identity_and_preserves_v1_tables(tmp_path):
    db, engine = _session(tmp_path)
    try:
        result_hash = _seed_strategy_input(db)
        readiness = build_strategy_readiness(
            db, analysis_id="analysis-1", diagnosis_id="diagnosis-1", result_version="diag-v1:fixture",
            project_id=1, prompt_id=44,
        )
        execution, result, created = create_strategy_candidate(
            db, analysis_id="analysis-1", diagnosis_id="diagnosis-1", result_version="diag-v1:fixture",
            project_id=1, prompt_id=44, idempotency_key="strategy-request-0001",
            diagnosis_result_hash=result_hash, reviewable_set_hash="q" * 64,
            review_id="review-1", review_snapshot_hash=readiness["review_snapshot_hash"],
            input_projection_hash=readiness["input_projection_hash"],
        )
        assert created is True
        assert execution.active_result_version == result.result_version
        status = get_strategy_status(
            db, strategy_id=execution.strategy_id, analysis_id="analysis-1", diagnosis_id="diagnosis-1",
            project_id=1, prompt_id=44,
        )
        assert status["strategy"]["strategy_id"] == execution.strategy_id
        assert status["result"]["result_version"] == result.result_version
        assert db.query(OptimizationStrategyCandidate).count() == 0
        assert db.query(OptimizationAction).count() == 0
        assert db.query(OptimizationExperiment).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_a_and_b_generation_create_no_strategy_rows(tmp_path):
    for reviewed, include_truth in ((False, False), (True, False)):
        db, engine = _session(tmp_path / ("a" if not reviewed else "b"))
        try:
            result_hash = _seed_strategy_input(db, reviewed=reviewed, include_truth=include_truth)
            readiness = build_strategy_readiness(
                db, analysis_id="analysis-1", diagnosis_id="diagnosis-1", result_version="diag-v1:fixture",
                project_id=1, prompt_id=44,
            )
            with pytest.raises(HTTPException) as caught:
                create_strategy_candidate(
                    db, analysis_id="analysis-1", diagnosis_id="diagnosis-1", result_version="diag-v1:fixture",
                    project_id=1, prompt_id=44, idempotency_key="strategy-request-0001",
                    diagnosis_result_hash=result_hash, reviewable_set_hash="q" * 64,
                    review_id=readiness.get("review_id") or "missing-review",
                    review_snapshot_hash=readiness.get("review_snapshot_hash") or "0" * 64,
                    input_projection_hash=readiness["input_projection_hash"],
                )
            assert caught.value.status_code == 409
            assert caught.value.detail["code"] == ("DIAGNOSIS_REVIEW_REQUIRED" if not reviewed else "NO_ELIGIBLE_STRATEGY_DIRECTION")
            assert db.query(SinglePromptStrategyExecution).count() == 0
            assert db.query(SinglePromptStrategyResult).count() == 0
        finally:
            db.close()
            engine.dispose()


def test_stale_input_rejected_and_revision_review_are_append_only(tmp_path):
    db, engine = _session(tmp_path)
    try:
        foundation = {
            "assessment_id": "asset-gap-1", "state": "CONFIRMED_MISSING",
            "truth_ids": [7], "evidence_ids": ["asset-audit-1"],
        }
        result_hash = _seed_strategy_input(db, foundation=foundation)
        readiness = build_strategy_readiness(
            db, analysis_id="analysis-1", diagnosis_id="diagnosis-1", result_version="diag-v1:fixture",
            project_id=1, prompt_id=44,
        )
        with pytest.raises(HTTPException) as stale:
            create_strategy_candidate(
                db, analysis_id="analysis-1", diagnosis_id="diagnosis-1", result_version="diag-v1:fixture",
                project_id=1, prompt_id=44, idempotency_key="strategy-stale-0001",
                diagnosis_result_hash=result_hash, reviewable_set_hash="q" * 64,
                review_id="review-1", review_snapshot_hash="0" * 64,
                input_projection_hash=readiness["input_projection_hash"],
            )
        assert stale.value.status_code == 409
        execution, result, _ = create_strategy_candidate(
            db, analysis_id="analysis-1", diagnosis_id="diagnosis-1", result_version="diag-v1:fixture",
            project_id=1, prompt_id=44, idempotency_key="strategy-good-0001",
            diagnosis_result_hash=result_hash, reviewable_set_hash="q" * 64,
            review_id="review-1", review_snapshot_hash=readiness["review_snapshot_hash"],
            input_projection_hash=readiness["input_projection_hash"],
        )
        output = json.loads(result.output_json)
        direction_ids = [row["direction_id"] for row in output["directions"]]
        with pytest.raises(HTTPException) as unresolved_priority:
            complete_strategy_review(
                db, strategy_id=execution.strategy_id, result_version=result.result_version,
                result_hash=result.output_hash, reviewable_set_hash=result.reviewable_set_hash,
                decision="ACCEPTED", reviewer="owner", note="尚未排序",
            )
        assert unresolved_priority.value.status_code == 409
        revised = revise_strategy_priority(
            db, strategy_id=execution.strategy_id, base_result_version=result.result_version,
            base_result_hash=result.output_hash, reviewable_set_hash=result.reviewable_set_hash,
            ordered_direction_ids=list(reversed(direction_ids)), editor="owner", reason="先验证渠道",
        )
        assert revised.parent_result_version == result.result_version
        assert json.loads(revised.output_json)["needs_human_prioritization"] is False
        review = complete_strategy_review(
            db, strategy_id=execution.strategy_id, result_version=revised.result_version,
            result_hash=revised.output_hash, reviewable_set_hash=revised.reviewable_set_hash,
            decision="ACCEPTED", reviewer="owner", note="接受当前策略",
        )
        assert review.decision == "ACCEPTED"
        assert db.query(SinglePromptStrategyResult).count() == 2
        assert db.query(SinglePromptStrategyReview).count() == 1
        with pytest.raises(HTTPException) as old:
            complete_strategy_review(
                db, strategy_id=execution.strategy_id, result_version=result.result_version,
                result_hash=result.output_hash, reviewable_set_hash=result.reviewable_set_hash,
                decision="ACCEPTED", reviewer="owner", note="过期",
            )
        assert old.value.status_code == 409
    finally:
        db.close()
        engine.dispose()


def test_created_strategy_becomes_view_only_when_exact_diagnosis_input_is_stale(tmp_path):
    db, engine = _session(tmp_path)
    try:
        result_hash = _seed_strategy_input(db)
        readiness = build_strategy_readiness(
            db, analysis_id="analysis-1", diagnosis_id="diagnosis-1", result_version="diag-v1:fixture",
            project_id=1, prompt_id=44,
        )
        execution, result, _ = create_strategy_candidate(
            db, analysis_id="analysis-1", diagnosis_id="diagnosis-1", result_version="diag-v1:fixture",
            project_id=1, prompt_id=44, idempotency_key="strategy-current-0001",
            diagnosis_result_hash=result_hash, reviewable_set_hash="q" * 64,
            review_id="review-1", review_snapshot_hash=readiness["review_snapshot_hash"],
            input_projection_hash=readiness["input_projection_hash"],
        )
        diagnosis = db.query(SinglePromptDiagnosisExecution).filter_by(diagnosis_id="diagnosis-1").one()
        diagnosis.active_result_version = "diag-v2:other"
        db.commit()
        status = get_strategy_status(
            db, strategy_id=execution.strategy_id, analysis_id="analysis-1", diagnosis_id="diagnosis-1",
            project_id=1, prompt_id=44,
        )
        assert status["applicability"]["is_current_input"] is False
        assert status["allowed_operations"] == ["VIEW"]
        with pytest.raises(HTTPException) as stale:
            complete_strategy_review(
                db, strategy_id=execution.strategy_id, result_version=result.result_version,
                result_hash=result.output_hash, reviewable_set_hash=result.reviewable_set_hash,
                decision="ACCEPTED", reviewer="owner", note="stale",
            )
        assert stale.value.status_code == 409
    finally:
        db.close()
        engine.dispose()
