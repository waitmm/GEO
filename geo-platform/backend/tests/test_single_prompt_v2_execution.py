from __future__ import annotations

import hashlib
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    BrowserMonitorRun,
    BrowserMonitorTask,
    Organization,
    Project,
    Prompt,
    ReferenceSource,
    SinglePromptAnalysis,
    SinglePromptAnalysisContext,
    SinglePromptDiagnosisExecution,
    SinglePromptDiagnosisResult,
    SinglePromptDiagnosisReview,
    SinglePromptExecutionConfirmation,
    SinglePromptExecutionProposal,
    SinglePromptExecutionProposalResult,
    SinglePromptPublicationRecord,
    SinglePromptRetestExecution,
    SinglePromptComparisonResult,
    SinglePromptSourceSnapshot,
)
from app.modules.single_prompt_v2.execution import (
    confirm_execution_proposal,
    create_execution_proposal,
    get_execution_proposal_status,
    record_publication,
    revise_execution_proposal,
)
from app.modules.single_prompt_v2.strategy import (
    build_strategy_readiness,
    complete_strategy_review,
    create_strategy_candidate,
)
from app.modules.single_prompt_v2.retest import (
    build_retest_readiness,
    create_comparison,
    create_retest,
    finalize_retest_with_failures,
    get_retest_status,
    measure_frozen_runs,
    retry_retest_sampling,
    start_retest_sampling,
)
from app.modules.single_prompt_v2.service import claim_analysis, finalize_analysis


def _hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'v2-execution.db').as_posix()}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


def _seed_accepted_strategy(db, *, foundation=False, include_partial=False, accept_strategy=True, publishable=True,
                            include_sampling_failure=False, complete_semantics=True):
    db.add(Organization(id=1, name="Isolated fixture"))
    db.add(Project(id=1, organization_id=1, name="Fixture", brand_name="Geo"))
    db.add(Prompt(id=44, project_id=1, title="Changed live title",
                  prompt_text="当前配置的问题，不得替换冻结复测问题", enabled=True))
    db.flush()
    plan = {
        "contract_version": "single-prompt-sampling-plan-v1", "project_id": 1, "prompt_id": 44,
        "prompt_text": "哪个二维码工具值得推荐", "sample_count": 3 if include_sampling_failure else 2, "platform": "wenxin",
        "source_type": "browser_audit", "adapter": "wenxin_web_audit", "collection_mode": "single_independent",
    }
    raw = {
        "contract_version": "single-prompt-raw-output-v1", "analysis_id": "analysis-1", "project_id": 1,
        "prompt_id": 44, "prompt_text": plan["prompt_text"], "sampling_plan": plan,
        "runs": [
            {"run_id": 101, "status": "success", "answer_text": "竞品甲值得推荐，因为支持批量生成二维码。",
             "environment": {"sampling_mode": "UNKNOWN"}, "references": [{"reference_id": 1}], "retrieval_candidates": []},
            *([{"run_id": 102, "status": "failed", "answer_text": "", "environment": {"sampling_mode": "UNKNOWN"},
                "references": [], "retrieval_candidates": [], "error": {"type": "blocked"}}] if include_sampling_failure else []),
            {"run_id": 103, "status": "success", "answer_text": "另一个有效回答未包含本方向。",
             "environment": {"sampling_mode": "UNKNOWN"}, "references": [], "retrieval_candidates": []},
        ],
    }
    db.add(SinglePromptAnalysis(
        analysis_id="analysis-1", project_id=1, prompt_id=44, task_id=52,
        idempotency_key="analysis-fixture", prompt_text_snapshot=plan["prompt_text"],
        sampling_plan_json=json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        sampling_plan_hash=_hash(plan), status="READY_WITH_FAILURES" if include_sampling_failure else "READY",
    ))
    run_scope = {
        "contract_version": "single-prompt-run-scope-v1", "task_id": 52,
        "run_ids": [row["run_id"] for row in raw["runs"]], "planned_run_count": len(raw["runs"]),
    }
    db.add(SinglePromptAnalysisContext(
        context_id="context-1", analysis_id="analysis-1", project_id=1, prompt_id=44, task_id=52,
        result_version=f"raw-v1:{_hash(raw)[:16]}",
        run_scope_json=json.dumps(run_scope, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        run_scope_hash=_hash(run_scope),
        raw_output_json=json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        raw_output_hash=_hash(raw), valid_run_count=2, failed_run_count=int(include_sampling_failure),
    ))
    output = {
        "contract_version": "single_prompt_diagnosis.v2_second_slice",
        "answer_diagnosis": {"events": [{
            "event_id": "event-1", "run_id": 101, "entity_text": "竞品甲", "effective_speech_act": "RECOMMEND",
            "reasons": [{"reason_id": "reason-1", "reason_span": "支持批量生成二维码", "normalized_reason": "支持批量生成二维码", "fact_consumption_eligible": True}],
        }], "unresolved_items": [], "failures": [], "answer_jobs": [
            {"answer_hash": hashlib.sha256(row["answer_text"].encode()).hexdigest(),
             "status": "DONE" if row["run_id"] == 101 else "DONE_ZERO_EVENTS"}
            for row in raw["runs"] if row["run_id"] == 101 or (row["run_id"] == 103 and complete_semantics)
        ]},
        "source_diagnosis": {"snapshots": [{"snapshot_id": "source-1"}]},
        "evidence_diagnosis": {"source_relations": [{
            "relation_id": "evidence-rel-1", "reason_id": "reason-1", "source_snapshot_id": "source-1",
            "reference_observation": "OBSERVED", "anchor_binding": "UNPROVEN", "candidate_recall": "RECALLED",
            "alignment_evaluation": "NOT_EVALUATED" if foundation else "EVALUATED",
            "effective_relation": None if foundation else "SOURCE_SUPPORTS_REASON",
        }], "source_claim_jobs": []},
        "truth_diagnosis": {
            "truth_snapshot": [
                {"truth_id": 7, "capability_key": "batch_qr", "capability_label": "批量生成二维码", "product_truth_status": "SUPPORTED", "truth_source": "MANUAL_CONFIRMED", "statement_eligibility": ({"status": "ELIGIBLE", "issues": []} if publishable else {"status": "VERIFY_FIRST", "issues": ["SOURCE_REFERENCE_REQUIRED"]})},
                *([{"truth_id": 8, "capability_key": "encrypted_qr", "capability_label": "加密防封二维码", "product_truth_status": "SUPPORTED", "truth_source": "MANUAL_CONFIRMED", "statement_eligibility": {"status": "ELIGIBLE", "issues": []}}] if include_partial else []),
            ],
            "relationships": [
                {"relationship_id": "truth-rel-1", "reason_id": "reason-1", "truth_id": 7, "effective_relation": "FULLY_COVERS"},
                *([{"relationship_id": "truth-rel-partial", "reason_id": "reason-1", "truth_id": 8, "effective_relation": "PARTIALLY_COVERS"}] if include_partial else []),
            ],
        },
        "foundation_assessment": ({"assessment_id": "gap-1", "state": "CONFIRMED_MISSING", "truth_ids": [7], "evidence_ids": ["audit-1"]} if foundation else {}),
        "limitations": [{"code": "RETRIEVAL_OBSERVATION_UNAVAILABLE"}], "stats": {"content_ready": 1},
    }
    result_hash = _hash(output)
    db.add(SinglePromptDiagnosisExecution(
        diagnosis_id="diagnosis-1", analysis_id="analysis-1", context_id="context-1", project_id=1, prompt_id=44,
        idempotency_key="diagnosis-fixture", input_fingerprint="i" * 64, raw_output_hash=_hash(raw),
        brand_snapshot_json=json.dumps({"project_id": 1, "brand_name": "Geo"}), brand_snapshot_hash="b" * 64,
        truth_snapshot_json="[]", truth_set_hash="t" * 64, contract_config_json="{}", contract_config_hash="d" * 64,
        status="READY_FOR_REVIEW", progress_json="{}", active_result_version="diag-v1:fixture",
    ))
    db.add(SinglePromptDiagnosisResult(
        result_version="diag-v1:fixture", diagnosis_id="diagnosis-1", version_number=1,
        output_json=json.dumps(output, ensure_ascii=False), output_hash=result_hash,
        reviewable_set_hash="q" * 64, limitations_json=json.dumps(output["limitations"]), stats_json=json.dumps({"content_ready": 1}),
    ))
    db.add(SinglePromptDiagnosisReview(
        review_id="review-1", diagnosis_id="diagnosis-1", result_version="diag-v1:fixture", result_hash=result_hash,
        reviewable_set_hash="q" * 64, decision="REVIEW_COMPLETED",
        decisions_json=json.dumps([{"scope": "ENTIRE_REVIEWABLE_SET", "decision": "REVIEW_COMPLETED_WITH_LIMITATIONS_PRESERVED"}]), reviewer="owner",
    ))
    db.add(SinglePromptSourceSnapshot(
        snapshot_id="source-1", diagnosis_id="diagnosis-1", source_key="source-key-1",
        canonical_url="https://www.zhihu.com/question/1", original_urls_json="[]",
        reference_observations_json=json.dumps([{"run_id": 101, "domain": "zhihu.com"}]), occurrence_count=1,
        fetch_status="SUCCESS", title="知乎来源", content_hash="e" * 64, clean_text="正文",
        passages_json="[]", passages_hash="f" * 64, parser_version="fixture",
    ))
    db.commit()
    readiness = build_strategy_readiness(
        db, analysis_id="analysis-1", diagnosis_id="diagnosis-1", result_version="diag-v1:fixture", project_id=1, prompt_id=44,
    )
    execution, result, _ = create_strategy_candidate(
        db, analysis_id="analysis-1", diagnosis_id="diagnosis-1", result_version="diag-v1:fixture",
        project_id=1, prompt_id=44, idempotency_key="strategy-request-1", diagnosis_result_hash=result_hash,
        reviewable_set_hash="q" * 64, review_id="review-1", review_snapshot_hash=readiness["review_snapshot_hash"],
        input_projection_hash=readiness["input_projection_hash"],
    )
    direction = json.loads(result.output_json)["directions"][0]
    if not accept_strategy:
        return execution, result, None, direction
    complete_strategy_review(
        db, strategy_id=execution.strategy_id, result_version=result.result_version, result_hash=result.output_hash,
        reviewable_set_hash=result.reviewable_set_hash, decision="ACCEPTED", reviewer="owner", note="accepted",
    )
    status = __import__("app.modules.single_prompt_v2.strategy", fromlist=["get_strategy_status"]).get_strategy_status(
        db, strategy_id=execution.strategy_id, analysis_id="analysis-1", diagnosis_id="diagnosis-1", project_id=1, prompt_id=44,
    )
    return execution, result, status["review"], direction


def _create_proposal(db, *, foundation=False, include_partial=False):
    strategy, result, review, direction = _seed_accepted_strategy(
        db, foundation=foundation, include_partial=include_partial,
    )
    from app.modules.single_prompt_v2.execution import _hash as execution_hash
    from app.modules.single_prompt_v2.strategy import strategy_review_snapshot
    review_row = db.query(__import__("app.models", fromlist=["SinglePromptStrategyReview"]).SinglePromptStrategyReview).filter_by(review_id=review["review_id"]).one()
    proposal, proposal_result, _ = create_execution_proposal(
        db, strategy_id=strategy.strategy_id, strategy_result_version=result.result_version,
        project_id=1, prompt_id=44, direction_id=direction["direction_id"], idempotency_key="proposal-request-1",
        strategy_result_hash=result.output_hash, strategy_review_id=review["review_id"],
        strategy_review_snapshot_hash=execution_hash(strategy_review_snapshot(review_row)),
    )
    return strategy, direction, proposal, proposal_result


def _ready_edit(output):
    surface = output["publication_surface_candidates"][0]
    return {
        "asset_operation": "CREATE_NEW", "asset_type": surface["asset_type"], "package_key": "FULL_DIRECTION_SCOPE",
        "publication_surface": surface["surface_key"], "publishing_account": "Geo 官方账号",
        "publishing_location": "产品内容栏目", "account_control_status": "USER_REPORTED_CONTROL",
        "title": output["title_candidates"][0]["title"],
        "section_order": [row["section_id"] for row in output["public_content_candidates"]], "execution_note": "fixture",
    }


def test_test_direction_without_primary_generates_create_new_and_exact_baseline(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _, direction, proposal, result = _create_proposal(db)
        output = json.loads(result.output_json)
        assert direction["channel_role"] == "TEST"
        assert output["asset_operation"] == "CREATE_NEW"
        assert output["baseline"]["baseline_run_ids"] == [101, 103]
        observed_theme_run_ids = json.loads(proposal.input_snapshot_json)["themes"][0]["observed_run_ids"]
        assert observed_theme_run_ids == [101]
        assert output["baseline"]["baseline_run_ids"] != observed_theme_run_ids
        assert output["baseline"]["run_manifest"]["failed"] == []
        assert "RETRIEVAL_OBSERVATION_UNAVAILABLE" in output["baseline"]["collector_capability_snapshot"]["warnings"]
        assert output["validation"]["status"] == "NEEDS_HUMAN_SELECTION"
        assert db.query(SinglePromptExecutionProposal).count() == 1
    finally:
        db.close(); engine.dispose()


@pytest.mark.parametrize("sampling_failure", [False, True])
def test_incomplete_fixed_scope_remains_blocked_and_failed_samples_are_preserved(tmp_path, sampling_failure):
    from app.modules.single_prompt_v2.execution import _baseline_snapshot
    db, engine = _session(tmp_path)
    try:
        with pytest.raises(HTTPException) as blocked:
            _seed_accepted_strategy(db, include_sampling_failure=sampling_failure, complete_semantics=False)
        assert blocked.value.status_code == 409
        assert blocked.value.detail["code"] == "FIXED_ANALYSIS_SCOPE_INCOMPLETE"
        assert db.query(SinglePromptExecutionProposal).count() == 0
        baseline = _baseline_snapshot(db.query(SinglePromptAnalysis).one(), db.query(SinglePromptAnalysisContext).one())
        assert baseline["baseline_run_ids"] == [101, 103]
        assert baseline["run_manifest"]["planned_count"] == (3 if sampling_failure else 2)
        assert baseline["run_manifest"]["failed_count"] == int(sampling_failure)
        if sampling_failure:
            assert baseline["run_manifest"]["failed"][0]["run_id"] == 102
    finally:
        db.close(); engine.dispose()


def test_unconfirmed_strategy_cannot_create_proposal(tmp_path):
    db, engine = _session(tmp_path)
    try:
        strategy, result, _, direction = _seed_accepted_strategy(db, accept_strategy=False)
        with pytest.raises(HTTPException) as blocked:
            create_execution_proposal(
                db, strategy_id=strategy.strategy_id, strategy_result_version=result.result_version,
                project_id=1, prompt_id=44, direction_id=direction["direction_id"],
                idempotency_key="unconfirmed", strategy_result_hash=result.output_hash,
                strategy_review_id="missing", strategy_review_snapshot_hash="x" * 64,
            )
        assert blocked.value.status_code == 409
        assert db.query(SinglePromptExecutionProposal).count() == 0
    finally:
        db.close(); engine.dispose()


def test_strategy_capability_without_public_evidence_cannot_generate_public_content(tmp_path):
    db, engine = _session(tmp_path)
    try:
        strategy, result, review, direction = _seed_accepted_strategy(db, publishable=False)
        from app.modules.single_prompt_v2.execution import _hash as execution_hash
        from app.modules.single_prompt_v2.strategy import strategy_review_snapshot
        review_row = db.query(
            __import__("app.models", fromlist=["SinglePromptStrategyReview"]).SinglePromptStrategyReview
        ).filter_by(review_id=review["review_id"]).one()

        with pytest.raises(HTTPException) as blocked:
            create_execution_proposal(
                db,
                strategy_id=strategy.strategy_id,
                strategy_result_version=result.result_version,
                project_id=1,
                prompt_id=44,
                direction_id=direction["direction_id"],
                idempotency_key="missing-public-evidence",
                strategy_result_hash=result.output_hash,
                strategy_review_id=review["review_id"],
                strategy_review_snapshot_hash=execution_hash(strategy_review_snapshot(review_row)),
            )

        assert blocked.value.status_code == 409
        assert blocked.value.detail["code"] == "PUBLIC_CLAIM_EVIDENCE_REQUIRED"
        assert db.query(SinglePromptExecutionProposal).count() == 0
    finally:
        db.close(); engine.dispose()


def test_foundation_surface_does_not_create_strategy_channel_role(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _, direction, proposal, result = _create_proposal(db, foundation=True)
        output = json.loads(result.output_json)
        revised = revise_execution_proposal(
            db, proposal_id=proposal.proposal_id, base_result_version=result.result_version,
            base_result_hash=result.output_hash, reviewable_set_hash=result.reviewable_set_hash,
            editor="owner", edit=_ready_edit(output),
        )
        revised_output = json.loads(revised.output_json)
        assert direction["channel_key"] is None and direction["channel_role"] is None
        assert revised_output["strategy_channel"]["channel_key"] is None
        assert revised_output["strategy_channel"]["channel_role"] is None
        assert revised_output["selection"]["publication_surface"] == "OWNED_PRODUCT_PAGE"
        assert revised_output["validation"]["status"] == "READY_FOR_CONFIRMATION"
    finally:
        db.close(); engine.dispose()


def test_update_and_immutable_field_edits_are_rejected(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _, _, proposal, result = _create_proposal(db)
        with pytest.raises(HTTPException) as update_error:
            revise_execution_proposal(
                db, proposal_id=proposal.proposal_id, base_result_version=result.result_version,
                base_result_hash=result.output_hash, reviewable_set_hash=result.reviewable_set_hash,
                editor="owner", edit={"asset_operation": "UPDATE_MANAGED"},
            )
        assert update_error.value.status_code == 422
        with pytest.raises(HTTPException) as immutable_error:
            revise_execution_proposal(
                db, proposal_id=proposal.proposal_id, base_result_version=result.result_version,
                base_result_hash=result.output_hash, reviewable_set_hash=result.reviewable_set_hash,
                editor="owner", edit={"channel_role": "PRIMARY"},
            )
        assert immutable_error.value.status_code == 422
        with pytest.raises(HTTPException) as forged_asset_error:
            revise_execution_proposal(
                db, proposal_id=proposal.proposal_id, base_result_version=result.result_version,
                base_result_hash=result.output_hash, reviewable_set_hash=result.reviewable_set_hash,
                editor="owner", edit={"eligible_asset_ids": [999], "asset_operation": "UPDATE_MANAGED"},
            )
        assert forged_asset_error.value.status_code == 422
    finally:
        db.close(); engine.dispose()


def test_public_and_internal_content_are_separate_and_no_fake_url(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _, _, _, result = _create_proposal(db)
        output = json.loads(result.output_json)
        assert all(row["content_class"] == "PUBLIC_CONTENT" for row in output["public_content_candidates"])
        assert all(row.get("content_class") != "PUBLIC_CONTENT" for row in output["internal_checklist"])
        assert "url" not in output["selection"]
        assert not any(row["purpose"] in {"FAQ", "OPERATION"} for row in output["public_content_candidates"])
    finally:
        db.close(); engine.dispose()


def test_partially_covers_stays_internal_and_never_becomes_public_claim(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _, _, _, result = _create_proposal(db, include_partial=True)
        output = json.loads(result.output_json)
        public_truth_ids = {
            truth_id
            for section in output["public_content_candidates"]
            for truth_id in section.get("truth_ids") or []
        }
        assert public_truth_ids == {7}
        assert all(row.get("product_truth_id") != 8 for row in output["claim_usage_policy"])
        assert any(
            row["code"] == "PARTIAL_TRUTH_RELATION_NOT_PUBLISHABLE"
            and row["relationship_id"] == "truth-rel-partial"
            for row in output["internal_checklist"]
        )
    finally:
        db.close(); engine.dispose()


def test_baseline_rejects_tampered_run_scope_hash_or_manifest(tmp_path):
    db, engine = _session(tmp_path)
    try:
        strategy, result, review, direction = _seed_accepted_strategy(db)
        context = db.query(SinglePromptAnalysisContext).filter_by(context_id="context-1").one()
        context.run_scope_json = json.dumps({"run_ids": [101], "planned_run_count": 1})
        db.commit()
        from app.modules.single_prompt_v2.execution import _hash as execution_hash
        from app.modules.single_prompt_v2.strategy import strategy_review_snapshot
        review_model = __import__("app.models", fromlist=["SinglePromptStrategyReview"]).SinglePromptStrategyReview
        review_row = db.query(review_model).filter_by(review_id=review["review_id"]).one()
        with pytest.raises(HTTPException) as stale:
            create_execution_proposal(
                db, strategy_id=strategy.strategy_id, strategy_result_version=result.result_version,
                project_id=1, prompt_id=44, direction_id=direction["direction_id"],
                idempotency_key="scope-tamper", strategy_result_hash=result.output_hash,
                strategy_review_id=review["review_id"],
                strategy_review_snapshot_hash=execution_hash(strategy_review_snapshot(review_row)),
            )
        assert stale.value.status_code == 409
    finally:
        db.close(); engine.dispose()


def test_ready_revision_confirmation_and_idempotency_are_separate_from_publication(tmp_path):
    db, engine = _session(tmp_path)
    try:
        strategy, _, proposal, result = _create_proposal(db)
        output = json.loads(result.output_json)
        revised = revise_execution_proposal(
            db, proposal_id=proposal.proposal_id, base_result_version=result.result_version,
            base_result_hash=result.output_hash, reviewable_set_hash=result.reviewable_set_hash,
            editor="owner", edit=_ready_edit(output),
        )
        confirmation, created = confirm_execution_proposal(
            db, proposal_id=proposal.proposal_id, result_version=revised.result_version,
            result_hash=revised.output_hash, reviewable_set_hash=revised.reviewable_set_hash,
            idempotency_key="confirm-request-1", confirmer="owner", note="确认执行",
        )
        again, created_again = confirm_execution_proposal(
            db, proposal_id=proposal.proposal_id, result_version=revised.result_version,
            result_hash=revised.output_hash, reviewable_set_hash=revised.reviewable_set_hash,
            idempotency_key="confirm-request-1", confirmer="owner", note="确认执行",
        )
        assert created is True and created_again is False and again.confirmation_id == confirmation.confirmation_id
        assert db.query(SinglePromptExecutionConfirmation).count() == 1
        assert db.query(SinglePromptPublicationRecord).count() == 0
        status = get_execution_proposal_status(db, proposal_id=proposal.proposal_id, strategy_id=strategy.strategy_id, project_id=1, prompt_id=44)
        assert status["proposal"]["status"] == "CONFIRMED_PENDING_PUBLICATION"
    finally:
        db.close(); engine.dispose()


def test_publication_requires_confirmation_and_insufficient_content_is_not_evaluable(tmp_path):
    db, engine = _session(tmp_path)
    try:
        with pytest.raises(HTTPException) as missing:
            record_publication(
                db, confirmation_id="missing", proposal_id="missing", idempotency_key="publication-1", prior_publication_id=None,
                recorder="owner", report={},
            )
        assert missing.value.status_code == 409
        strategy, _, proposal, result = _create_proposal(db)
        output = json.loads(result.output_json)
        revised = revise_execution_proposal(
            db, proposal_id=proposal.proposal_id, base_result_version=result.result_version,
            base_result_hash=result.output_hash, reviewable_set_hash=result.reviewable_set_hash,
            editor="owner", edit=_ready_edit(output),
        )
        confirmation, _ = confirm_execution_proposal(
            db, proposal_id=proposal.proposal_id, result_version=revised.result_version,
            result_hash=revised.output_hash, reviewable_set_hash=revised.reviewable_set_hash,
            idempotency_key="confirm-request-1", confirmer="owner", note="",
        )
        publication, _ = record_publication(
            db, confirmation_id=confirmation.confirmation_id, proposal_id=proposal.proposal_id, idempotency_key="publication-1", prior_publication_id=None,
            recorder="owner", report={
                "publication_status": "USER_REPORTED", "actual_channel": "ZHIHU", "actual_account": "Geo 官方账号",
                "actual_location": "产品内容栏目", "actual_url": "https://www.zhihu.com/p/1",
                "published_at": "2026-09-11T12:00:00+08:00", "actual_content_version": "",
                "actual_title": "", "actual_section_ids": None, "actual_claim_ids": None,
                "actual_content_excerpt": "", "differences": "未提供实际内容",
            },
        )
        assert publication.publication_status == "USER_REPORTED"
        assert publication.conformance == "NOT_EVALUABLE"
        repeated, created_again = record_publication(
            db, confirmation_id=confirmation.confirmation_id, proposal_id=proposal.proposal_id,
            idempotency_key="publication-1", prior_publication_id=None, recorder="owner",
            report={
                "publication_status": "USER_REPORTED", "actual_channel": "ZHIHU", "actual_account": "Geo 官方账号",
                "actual_location": "产品内容栏目", "actual_url": "https://www.zhihu.com/p/1",
                "published_at": "2026-09-11T12:00:00+08:00", "actual_content_version": "",
                "actual_title": "", "actual_section_ids": None, "actual_claim_ids": None,
                "actual_content_excerpt": "", "differences": "未提供实际内容",
            },
        )
        assert created_again is False and repeated.publication_id == publication.publication_id
        assert db.query(SinglePromptPublicationRecord).count() == 1
        status = get_execution_proposal_status(db, proposal_id=proposal.proposal_id, strategy_id=strategy.strategy_id, project_id=1, prompt_id=44)
        assert status["publications"][0]["conformance_detail"]["system_verified_online"] is False
    finally:
        db.close(); engine.dispose()


def test_exact_content_version_matches_but_channel_deviation_is_preserved(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _, _, proposal, result = _create_proposal(db)
        output = json.loads(result.output_json)
        revised = revise_execution_proposal(
            db, proposal_id=proposal.proposal_id, base_result_version=result.result_version,
            base_result_hash=result.output_hash, reviewable_set_hash=result.reviewable_set_hash,
            editor="owner", edit=_ready_edit(output),
        )
        confirmation, _ = confirm_execution_proposal(
            db, proposal_id=proposal.proposal_id, result_version=revised.result_version,
            result_hash=revised.output_hash, reviewable_set_hash=revised.reviewable_set_hash,
            idempotency_key="confirm-request-1", confirmer="owner", note="",
        )
        matched_report = {
            "publication_status": "USER_REPORTED", "actual_channel": "ZHIHU", "actual_account": "Geo 官方账号",
            "actual_location": "产品内容栏目", "actual_url": "https://www.zhihu.com/p/1",
            "published_at": "2026-09-11T12:00:00+08:00", "actual_content_version": revised.result_version,
            "actual_title": "", "actual_section_ids": None, "actual_claim_ids": None, "actual_content_excerpt": "", "differences": "",
        }
        matched, _ = record_publication(
            db, confirmation_id=confirmation.confirmation_id, proposal_id=proposal.proposal_id, idempotency_key="publication-1",
            prior_publication_id=None, recorder="owner", report=matched_report,
        )
        assert matched.conformance == "MATCHED"
        excerpt_report = dict(matched_report, actual_content_excerpt="这里是用户粘贴的实际内容", differences="提供了未结构化内容")
        excerpt, _ = record_publication(
            db, confirmation_id=confirmation.confirmation_id, proposal_id=proposal.proposal_id,
            idempotency_key="publication-2", prior_publication_id=matched.publication_id,
            recorder="owner", report=excerpt_report,
        )
        assert excerpt.conformance == "NOT_EVALUABLE"
        changed = dict(matched_report, actual_channel="BAIJIAHAO", differences="实际改发百家号")
        outside, _ = record_publication(
            db, confirmation_id=confirmation.confirmation_id, proposal_id=proposal.proposal_id, idempotency_key="publication-3",
            prior_publication_id=excerpt.publication_id, recorder="owner", report=changed,
        )
        assert outside.conformance == "OUTSIDE_CONFIRMED_SCOPE"
        assert outside.prior_publication_id == excerpt.publication_id
        assert db.query(SinglePromptPublicationRecord).count() == 3
    finally:
        db.close(); engine.dispose()


def test_get_is_read_only_and_stale_strategy_blocks_new_confirmation(tmp_path):
    db, engine = _session(tmp_path)
    try:
        strategy, _, proposal, result = _create_proposal(db)
        before = (db.query(SinglePromptExecutionProposalResult).count(), db.query(SinglePromptExecutionConfirmation).count())
        get_execution_proposal_status(db, proposal_id=proposal.proposal_id, strategy_id=strategy.strategy_id, project_id=1, prompt_id=44)
        assert before == (db.query(SinglePromptExecutionProposalResult).count(), db.query(SinglePromptExecutionConfirmation).count())
        output = json.loads(result.output_json)
        revised = revise_execution_proposal(
            db, proposal_id=proposal.proposal_id, base_result_version=result.result_version,
            base_result_hash=result.output_hash, reviewable_set_hash=result.reviewable_set_hash,
            editor="owner", edit=_ready_edit(output),
        )
        diagnosis = db.query(SinglePromptDiagnosisExecution).filter_by(diagnosis_id="diagnosis-1").one()
        diagnosis.active_result_version = "diag-v2:stale"
        db.commit()
        with pytest.raises(HTTPException) as stale:
            confirm_execution_proposal(
                db, proposal_id=proposal.proposal_id, result_version=revised.result_version,
                result_hash=revised.output_hash, reviewable_set_hash=revised.reviewable_set_hash,
                idempotency_key="confirm-stale-1", confirmer="owner", note="",
            )
        assert stale.value.status_code == 409
    finally:
        db.close(); engine.dispose()


def _create_confirmed_publication(db, *, published_at="2026-09-11T12:00:00+08:00"):
    strategy, _, proposal, result = _create_proposal(db)
    output = json.loads(result.output_json)
    revised = revise_execution_proposal(
        db, proposal_id=proposal.proposal_id, base_result_version=result.result_version,
        base_result_hash=result.output_hash, reviewable_set_hash=result.reviewable_set_hash,
        editor="owner", edit=_ready_edit(output),
    )
    confirmation, _ = confirm_execution_proposal(
        db, proposal_id=proposal.proposal_id, result_version=revised.result_version,
        result_hash=revised.output_hash, reviewable_set_hash=revised.reviewable_set_hash,
        idempotency_key="confirm-retest-1", confirmer="owner", note="",
    )
    publication, _ = record_publication(
        db, confirmation_id=confirmation.confirmation_id, proposal_id=proposal.proposal_id,
        idempotency_key="publish-retest-1", prior_publication_id=None, recorder="owner",
        report={
            "publication_status": "USER_REPORTED", "actual_channel": "ZHIHU",
            "actual_account": "Geo 官方账号", "actual_location": "产品内容栏目",
            "actual_url": "https://www.zhihu.com/p/target?utm_source=test",
            "published_at": published_at, "actual_content_version": revised.result_version,
            "actual_title": "", "actual_section_ids": None, "actual_claim_ids": None,
            "actual_content_excerpt": "", "differences": "",
        },
    )
    return strategy, proposal, confirmation, publication


def _create_retest_fixture(db, **identity_overrides):
    strategy, proposal, confirmation, publication = _create_confirmed_publication(db)
    retest, created = create_retest(
        db, project_id=1, prompt_id=44, confirmation_id=confirmation.confirmation_id,
        publication_id=publication.publication_id, publication_report_hash=publication.report_hash,
        confirmation_snapshot_hash=confirmation.confirmation_snapshot_hash,
        idempotency_key="retest-request-1", sample_count=2,
        measurement_identity=identity_overrides or None,
    )
    return strategy, proposal, confirmation, publication, retest, created


def test_retest_requires_exact_publication_and_get_readiness_is_read_only(tmp_path):
    db, engine = _session(tmp_path)
    try:
        before = db.query(SinglePromptRetestExecution).count()
        blocked = build_retest_readiness(db, project_id=1, prompt_id=44)
        assert blocked["sampling_eligible"] is False
        assert blocked["blocker"]["code"] == "EXECUTION_CONFIRMATION_AND_PUBLICATION_REQUIRED"
        assert db.query(SinglePromptRetestExecution).count() == before
        with pytest.raises(HTTPException) as missing:
            build_retest_readiness(
                db, project_id=1, prompt_id=44,
                confirmation_id="missing", publication_id="missing",
            )
        assert missing.value.status_code == 409
    finally:
        db.close(); engine.dispose()


def test_frozen_retest_plan_does_not_read_live_prompt_or_project_and_is_idempotent(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _, _, confirmation, publication, retest, created = _create_retest_fixture(db)
        assert created is True
        plan = json.loads(retest.retest_plan_json)
        runs = db.query(BrowserMonitorRun).filter_by(task_id=db.query(SinglePromptAnalysis).filter_by(analysis_id=retest.retest_analysis_id).one().task_id).all()
        assert len(runs) == 2
        assert all(run.original_query == "哪个二维码工具值得推荐" for run in runs)
        assert all(_hash(run.original_query) == plan["prompt_text_hash"] for run in runs)
        assert json.loads(retest.measurement_identity_json)["accepted_aliases"] == []
        again, created_again = create_retest(
            db, project_id=1, prompt_id=44, confirmation_id=confirmation.confirmation_id,
            publication_id=publication.publication_id, publication_report_hash=publication.report_hash,
            confirmation_snapshot_hash=confirmation.confirmation_snapshot_hash,
            idempotency_key="retest-request-1", sample_count=2, measurement_identity=None,
        )
        assert created_again is False and again.retest_id == retest.retest_id
        assert db.query(SinglePromptRetestExecution).count() == 1
        assert db.query(BrowserMonitorTask).count() == 1
    finally:
        db.close(); engine.dispose()


def test_retest_start_verifies_query_hash_and_does_not_expand_runs(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _, _, _, _, retest, _ = _create_retest_fixture(db)
        analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=retest.retest_analysis_id).one()
        runs = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).order_by(BrowserMonitorRun.id).all()
        original_ids = [run.id for run in runs]
        runs[0].original_query = "后来被修改的问题"
        db.commit()
        with pytest.raises(HTTPException) as mismatch:
            start_retest_sampling(db, retest_id=retest.retest_id, project_id=1, prompt_id=44)
        assert mismatch.value.status_code == 409
        assert [run.id for run in db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).order_by(BrowserMonitorRun.id)] == original_ids
        runs[0].original_query = "哪个二维码工具值得推荐"
        db.commit()
        start_retest_sampling(db, retest_id=retest.retest_id, project_id=1, prompt_id=44)
        assert [run.id for run in db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).order_by(BrowserMonitorRun.id)] == original_ids
    finally:
        db.close(); engine.dispose()


def test_frozen_dto_metrics_separate_zero_unknown_and_run_level_duplicates():
    identity = {
        "canonical_brand_name": "Geo", "accepted_aliases": ["GEO平台"],
        "official_domains": ["geo.example.com"], "official_urls": [],
        "identity_snapshot_hash": "identity",
    }
    raw = {
        "runs": [
            {"run_id": 1, "status": "success", "answer_text": "推荐 Geo。", "reference_complete": True,
             "references": [
                 {"url": "https://geo.example.com/a", "domain": "geo.example.com"},
                 {"url": "https://geo.example.com/a?utm_source=x", "domain": "geo.example.com"},
                 {"url": "https://www.zhihu.com/p/target", "domain": "zhihu.com"},
             ]},
            {"run_id": 2, "status": "success", "answer_text": "没有提及目标品牌。", "reference_complete": True, "references": []},
            {"run_id": 3, "status": "failed", "answer_text": "", "reference_complete": False, "references": []},
        ]
    }
    answer_hash = hashlib.sha256("推荐 Geo。".encode()).hexdigest()
    other_hash = hashlib.sha256("没有提及目标品牌。".encode()).hexdigest()
    semantics = {
        "answer_jobs": [
            {"answer_hash": answer_hash, "status": "DONE"},
            {"answer_hash": other_hash, "status": "SEMANTIC_REVIEW_REQUIRED"},
        ],
        "events": [{"run_id": 1, "entity_text": "Geo", "effective_speech_act": "RECOMMEND", "fact_consumption_eligible": True}],
    }
    measured = measure_frozen_runs(
        raw=raw, identity=identity, answer_diagnosis=semantics,
        published_url="https://www.zhihu.com/p/target?utm_source=publication",
    )["metrics"]
    assert measured["brand_mention_rate"]["hit_run_ids"] == [1]
    assert measured["brand_recommendation_rate"]["value"] == 1.0
    assert measured["brand_recommendation_rate"]["unevaluated"][0]["run_id"] == 2
    assert measured["target_brand_official_reference_rate"]["hit_count"] == 1
    assert measured["published_url_reference_rate"]["hit_count"] == 1
    assert measured["published_url_reference_rate"]["evaluable_count"] == 2


def test_missing_official_identity_and_semantics_are_not_zero(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _, _, _, _, retest, _ = _create_retest_fixture(db)
        raw = {"runs": [{"run_id": 1, "status": "success", "answer_text": "Geo 被提及。", "reference_complete": True, "references": []}]}
        identity = json.loads(retest.measurement_identity_json)
        measured = measure_frozen_runs(raw=raw, identity=identity, answer_diagnosis=None, published_url="https://example.com/new")["metrics"]
        assert measured["brand_mention_rate"]["value"] == 1.0
        assert measured["brand_recommendation_rate"]["value"] is None
        assert measured["target_brand_official_reference_rate"]["value"] is None
        assert measured["published_url_reference_rate"]["value"] == 0.0
    finally:
        db.close(); engine.dispose()


def test_comparison_uses_frozen_context_and_preserves_temporal_limit(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _, _, _, _, retest, _ = _create_retest_fixture(db, canonical_brand_name="Geo", confirmed_by="owner")
        analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=retest.retest_analysis_id).one()
        analysis.status = "QUEUED"
        db.commit()
        token = claim_analysis(db, analysis.analysis_id)
        runs = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).order_by(BrowserMonitorRun.id).all()
        for index, run in enumerate(runs):
            run.status = "success"
            run.stage = "done"
            run.answer_text = "Geo 被提及。" if index == 0 else "未观察到目标品牌。"
            run.answer_char_count = len(run.answer_text)
            run.reference_complete = True
            run.started_at = __import__("datetime").datetime(2026, 9, 12, 1, index)
            run.finished_at = __import__("datetime").datetime(2026, 9, 12, 1, index, 10)
        db.commit()
        assert finalize_analysis(db, analysis.analysis_id, token) is True
        result, created = create_comparison(db, retest_id=retest.retest_id, project_id=1, prompt_id=44)
        assert created is True
        comparison = json.loads(result.comparison_json)
        retest_metrics = json.loads(result.retest_measurement_json)["metrics"]
        assert retest_metrics["brand_mention_rate"]["value"] == 0.5
        assert retest_metrics["brand_recommendation_rate"]["value"] is None
        assert comparison["conclusion_policy"] == "OBSERVED_CHANGE_ONLY_NO_CAUSAL_OR_EFFECTIVENESS_CONCLUSION"
        assert comparison["temporal_order"]["verified"] is False
        again, created_again = create_comparison(db, retest_id=retest.retest_id, project_id=1, prompt_id=44)
        assert created_again is False and again.result_version == result.result_version
        assert db.query(SinglePromptComparisonResult).count() == 1
        before = db.query(SinglePromptComparisonResult).count()
        status = get_retest_status(db, retest_id=retest.retest_id, project_id=1, prompt_id=44)
        assert status["boundary"]["causal_conclusion"] is False
        assert db.query(SinglePromptComparisonResult).count() == before
    finally:
        db.close(); engine.dispose()


def test_retest_retry_reuses_planned_runs_preserves_success_and_can_finalize_failures(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _, _, _, _, retest, _ = _create_retest_fixture(db)
        analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=retest.retest_analysis_id).one()
        runs = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).order_by(BrowserMonitorRun.id).all()
        original_ids = [run.id for run in runs]
        runs[0].status = "success"
        runs[0].stage = "done"
        runs[0].answer_text = "Geo 已在成功样本中出现。"
        runs[0].answer_char_count = len(runs[0].answer_text)
        runs[1].status = "failed"
        runs[1].stage = "failed"
        runs[1].error_type = "timeout"
        analysis.status = "INTERRUPTED"
        analysis.blocker_code = "PARTIAL_RETEST_RETRY_AVAILABLE"
        db.commit()

        retry_retest_sampling(db, retest_id=retest.retest_id, project_id=1, prompt_id=44)
        retried = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).order_by(BrowserMonitorRun.id).all()
        assert [run.id for run in retried] == original_ids
        assert retried[0].status == "success"
        assert retried[0].answer_text == "Geo 已在成功样本中出现。"
        assert retried[1].status == "queued"
        assert retried[1].retry_count == 1

        retried[1].status = "failed"
        retried[1].stage = "failed"
        retried[1].error_type = "timeout"
        analysis.status = "INTERRUPTED"
        analysis.blocker_code = "PARTIAL_RETEST_RETRY_AVAILABLE"
        db.commit()
        finalize_retest_with_failures(db, retest_id=retest.retest_id, project_id=1, prompt_id=44)
        context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis.analysis_id).one()
        frozen = json.loads(context.raw_output_json)
        assert [row["run_id"] for row in frozen["runs"]] == original_ids
        assert context.valid_run_count == 1 and context.failed_run_count == 1
        assert db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).count() == 2
    finally:
        db.close(); engine.dispose()


def test_historical_strategy_publication_remains_observable_but_cross_project_is_rejected(tmp_path):
    db, engine = _session(tmp_path)
    try:
        strategy, _, confirmation, publication = _create_confirmed_publication(db)
        strategy.active_result_version = "strategy-v2:historical"
        db.commit()
        retest, created = create_retest(
            db, project_id=1, prompt_id=44,
            confirmation_id=confirmation.confirmation_id,
            publication_id=publication.publication_id,
            confirmation_snapshot_hash=confirmation.confirmation_snapshot_hash,
            publication_report_hash=publication.report_hash,
            idempotency_key="historical-retest", sample_count=1,
            measurement_identity=None,
        )
        assert created is True
        assert retest.publication_id == publication.publication_id
        with pytest.raises(HTTPException) as cross_project:
            build_retest_readiness(
                db, project_id=2, prompt_id=44,
                confirmation_id=confirmation.confirmation_id,
                publication_id=publication.publication_id,
            )
        assert cross_project.value.status_code == 409
    finally:
        db.close(); engine.dispose()


def test_metric_zero_requires_observable_denominator_and_incomplete_references_remain_unknown():
    identity = {
        "canonical_brand_name": "Geo", "accepted_aliases": [],
        "official_domains": ["geo.example.com"], "official_urls": [],
        "identity_snapshot_hash": "identity",
    }
    empty = measure_frozen_runs(raw={"runs": []}, identity=identity, answer_diagnosis=None, published_url="https://example.com/new")
    assert all(metric["value"] is None for metric in empty["metrics"].values())
    incomplete = measure_frozen_runs(
        raw={"runs": [{
            "run_id": 1, "status": "success", "answer_text": "未提及目标品牌。",
            "reference_complete": False, "references": [],
        }]},
        identity=identity,
        answer_diagnosis={"answer_jobs": [], "events": []},
        published_url="https://example.com/new",
    )["metrics"]
    assert incomplete["target_brand_official_reference_rate"]["value"] is None
    assert incomplete["published_url_reference_rate"]["value"] is None
    assert incomplete["published_url_reference_rate"]["unevaluated_count"] == 1


def test_observed_retest_condition_conflict_keeps_values_but_removes_delta(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _, _, _, _, retest, _ = _create_retest_fixture(db, canonical_brand_name="Geo", confirmed_by="owner")
        analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=retest.retest_analysis_id).one()
        analysis.status = "QUEUED"
        db.commit()
        token = claim_analysis(db, analysis.analysis_id)
        runs = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).order_by(BrowserMonitorRun.id).all()
        for run in runs:
            run.status = "success"
            run.stage = "done"
            run.answer_text = "Geo 被提及。"
            run.answer_char_count = len(run.answer_text)
            run.reference_complete = True
        runs[0].platform = "different-platform"
        db.commit()
        assert finalize_analysis(db, analysis.analysis_id, token) is True

        result, _ = create_comparison(db, retest_id=retest.retest_id, project_id=1, prompt_id=44)
        comparison = json.loads(result.comparison_json)
        mention = comparison["metrics"]["brand_mention_rate"]
        assert json.loads(result.retest_measurement_json)["metrics"]["brand_mention_rate"]["value"] == 1.0
        assert mention["comparison_eligible"] is False
        assert mention["delta_percentage_points"] is None
        assert "RETEST_PLATFORM_MISMATCH" in mention["reasons"]
    finally:
        db.close(); engine.dispose()
