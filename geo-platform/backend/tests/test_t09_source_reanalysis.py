from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import Response

from app.models import Prompt, SinglePromptDiagnosisExecution, SinglePromptDiagnosisResult
from app.modules.single_prompt_v2 import source_preparation
from app.modules.single_prompt_v2.diagnosis import (
    claim_diagnosis,
    complete_diagnosis_review,
    compute_answer_diagnosis,
    continue_evidence_diagnosis,
    create_answer_diagnosis,
)
from app.modules.single_prompt_v2.source_reanalysis import (
    _hash,
    _require_answer_scope,
    execute_source_reanalysis,
    execute_source_reanalysis_with_local_judges,
    plan_source_reanalysis,
    source_reanalysis_view,
)
from app.modules.single_prompt_v2.release_api import SourceReanalysisCreate, plan_prepared_source_reanalysis
from scripts.check_t09_source_reanalysis_readiness import assess_readiness
from test_release_first_slice import (
    _AlignmentJudge,
    _AnswerJudge,
    _SourceClaimJudge,
    _configure_artifacts,
    _create_preparation,
    _seed_frozen_analysis,
    _session,
    _submit,
)


def test_manual_content_reanalysis_is_exact_append_only_idempotent_and_locally_executable(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    try:
        analysis = _seed_frozen_analysis(db, reference_urls=["https://example.com/only"])
        preparation, status = _create_preparation(db, analysis)
        source = status["sources"][0]
        old_text = "旧版真实正文明确说明甲工具支持批量生成短链，并保留完整上下文与适用边界。" * 2
        old_snapshot = _submit(db, preparation.preparation_id, source, old_text)
        old_manifest = source_preparation.freeze_completion_manifest(
            db, preparation_id=preparation.preparation_id, created_by="qa"
        )
        citation = source_preparation.get_source_preparation_status(
            db, preparation_id=preparation.preparation_id
        )["citation_manifest"]

        diagnosis, _ = create_answer_diagnosis(
            db,
            analysis_id=analysis.analysis_id,
            project_id=1,
            prompt_id=44,
            citation_manifest_id=citation["manifest_id"],
            citation_manifest_hash=citation["payload_hash"],
            answer_llm_policy="ALLOW_EXTERNAL",
            idempotency_key="t09-answer-diagnosis",
        )
        answer = compute_answer_diagnosis(
            db, diagnosis, claim_diagnosis(db, diagnosis.diagnosis_id), answer_judge=_AnswerJudge()
        )
        review = complete_diagnosis_review(
            db,
            diagnosis_id=diagnosis.diagnosis_id,
            result_version=answer.result_version,
            result_hash=answer.output_hash,
            reviewable_set_hash=answer.reviewable_set_hash,
            reviewer="qa",
            note="固定 Answer Review",
            decisions=[],
        )
        old_result = continue_evidence_diagnosis(
            db,
            analysis_id=analysis.analysis_id,
            diagnosis_id=diagnosis.diagnosis_id,
            project_id=1,
            prompt_id=44,
            answer_result_version=answer.result_version,
            answer_result_hash=answer.output_hash,
            answer_review_id=review.review_id,
            citation_manifest_id=citation["manifest_id"],
            citation_manifest_hash=citation["payload_hash"],
            completion_manifest_id=old_manifest.manifest_id,
            completion_manifest_hash=old_manifest.payload_hash,
            evidence_llm_policy="ALLOW_EXTERNAL",
            source_claim_judge=_SourceClaimJudge(),
            alignment_judge=_AlignmentJudge(),
        )
        old_result_json = old_result.output_json
        old_active_result = diagnosis.active_result_version

        refreshed = source_preparation.get_source_preparation_status(
            db, preparation_id=preparation.preparation_id
        )["sources"][0]
        new_text = "新版真实正文修正为甲工具支持批量生成短链，并补充新的限制条件和适用上下文。" * 2
        new_snapshot = _submit(db, preparation.preparation_id, refreshed, new_text)
        new_manifest = source_preparation.freeze_completion_manifest(
            db, preparation_id=preparation.preparation_id, created_by="qa"
        )

        # Planning must not accept a globally unique Answer result whose
        # owning Diagnosis has drifted into another Prompt scope.
        db.add(Prompt(id=45, project_id=1, title="Foreign Prompt", prompt_text="另一个问题"))
        db.commit()
        diagnosis.prompt_id = 45
        db.commit()
        with pytest.raises(Exception) as scope_error:
            plan_source_reanalysis(
                db,
                preparation_id=preparation.preparation_id,
                project_id=1,
                prompt_id=44,
                prior_completion_manifest_id=old_manifest.manifest_id,
                prior_completion_manifest_hash=old_manifest.payload_hash,
                new_completion_manifest_id=new_manifest.manifest_id,
                new_completion_manifest_hash=new_manifest.payload_hash,
                idempotency_key="t09-source-reanalysis-cross-prompt",
                requested_by="qa",
            )
        assert getattr(scope_error.value, "detail", {}) == {
            "code": "SOURCE_REANALYSIS_ANSWER_SCOPE_MISMATCH"
        }
        diagnosis.prompt_id = 44
        db.commit()

        plans, created = plan_source_reanalysis(
            db,
            preparation_id=preparation.preparation_id,
            project_id=1,
            prompt_id=44,
            prior_completion_manifest_id=old_manifest.manifest_id,
            prior_completion_manifest_hash=old_manifest.payload_hash,
            new_completion_manifest_id=new_manifest.manifest_id,
            new_completion_manifest_hash=new_manifest.payload_hash,
            idempotency_key="t09-source-reanalysis",
            requested_by="qa",
        )
        assert created is True
        assert len(plans) == 1
        plan = plans[0]
        view = source_reanalysis_view(plan)
        assert view["status"] == "AWAITING_EXTERNAL_AUTHORIZATION"
        assert view["blocker_code"] == "EXTERNAL_MODEL_AUTHORIZATION_REQUIRED"
        assert view["external_usage"] == {"calls": 0, "tokens": 0}
        assert view["input"]["answer_scope"] == {
            "diagnosis_id": diagnosis.diagnosis_id,
            "analysis_id": analysis.analysis_id,
            "context_id": view["input"]["context_id"],
            "project_id": 1,
            "prompt_id": 44,
            "raw_output_hash": view["input"]["raw_output_hash"],
        }
        assert view["input"]["changed_source_keys"] == [source["source_key"]]
        assert view["input"]["changed_snapshots"] == [{
            "source_key": source["source_key"],
            "prior_snapshot_id": old_snapshot.snapshot_id,
            "prior_content_hash": old_snapshot.content_hash,
            "new_snapshot_id": new_snapshot.snapshot_id,
            "new_content_hash": new_snapshot.content_hash,
        }]

        db.refresh(diagnosis)
        db.refresh(old_result)
        assert diagnosis.active_result_version == old_active_result
        assert old_result.output_json == old_result_json
        assert Path(old_snapshot.artifact_path).read_text(encoding="utf-8") == old_text
        assert Path(new_snapshot.artifact_path).read_text(encoding="utf-8") == new_text

        api_response = Response(status_code=201)
        api_view = plan_prepared_source_reanalysis(
            preparation.preparation_id,
            SourceReanalysisCreate(
                project_id=1,
                prompt_id=44,
                prior_completion_manifest_id=old_manifest.manifest_id,
                prior_completion_manifest_hash=old_manifest.payload_hash,
                new_completion_manifest_id=new_manifest.manifest_id,
                new_completion_manifest_hash=new_manifest.payload_hash,
                idempotency_key="t09-source-reanalysis",
            ),
            api_response,
            actor="qa",
            db=db,
        )
        assert api_response.status_code == 200
        assert api_view["affected_count"] == 1
        assert api_view["reanalyses"][0]["reanalysis_id"] == plan.diagnosis_id

        # Even a self-consistent rewritten plan hash cannot inject an Answer
        # from another Project, Prompt, or Context at execution time.
        original_progress = json.loads(plan.progress_json)
        original_fingerprint = plan.input_fingerprint
        for field, foreign_value in (
            ("project_id", 2),
            ("prompt_id", 45),
            ("context_id", "ctx-foreign-injection"),
        ):
            tampered = json.loads(json.dumps(original_progress))
            tampered["input"]["answer_scope"][field] = foreign_value
            tampered_hash = _hash(tampered["input"])
            tampered["input_hash"] = tampered_hash
            plan.progress_json = json.dumps(
                tampered, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            plan.input_fingerprint = tampered_hash
            db.commit()
            with pytest.raises(Exception) as execution_scope_error:
                execute_source_reanalysis_with_local_judges(
                    db,
                    reanalysis_id=plan.diagnosis_id,
                    source_claim_judge=_SourceClaimJudge(),
                    alignment_judge=_AlignmentJudge(),
                )
            assert getattr(execution_scope_error.value, "detail", {}) == {
                "code": "SOURCE_REANALYSIS_ANSWER_SCOPE_MISMATCH"
            }
        plan.progress_json = json.dumps(
            original_progress, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        plan.input_fingerprint = original_fingerprint
        db.commit()

        result = execute_source_reanalysis_with_local_judges(
            db,
            reanalysis_id=plan.diagnosis_id,
            source_claim_judge=_SourceClaimJudge(),
            alignment_judge=_AlignmentJudge(),
        )
        output = json.loads(result.output_json)
        assert result.parent_result_version == old_result.result_version
        assert output["input"]["prior_completion_manifest_id"] == old_manifest.manifest_id
        assert output["input"]["completion_manifest_id"] == new_manifest.manifest_id
        assert output["input"]["source_snapshot_ids"] == [new_snapshot.snapshot_id]
        assert output["usage"]["external_llm_calls"] == 0
        assert db.query(SinglePromptDiagnosisResult).filter_by(
            diagnosis_id=diagnosis.diagnosis_id, result_version=old_result.result_version
        ).one().output_json == old_result_json

        repeated, repeated_created = plan_source_reanalysis(
            db,
            preparation_id=preparation.preparation_id,
            project_id=1,
            prompt_id=44,
            prior_completion_manifest_id=old_manifest.manifest_id,
            prior_completion_manifest_hash=old_manifest.payload_hash,
            new_completion_manifest_id=new_manifest.manifest_id,
            new_completion_manifest_hash=new_manifest.payload_hash,
            idempotency_key="t09-source-reanalysis",
            requested_by="qa",
        )
        assert repeated_created is False
        assert [row.diagnosis_id for row in repeated] == [plan.diagnosis_id]
        assert execute_source_reanalysis_with_local_judges(
            db,
            reanalysis_id=plan.diagnosis_id,
            source_claim_judge=_SourceClaimJudge(),
            alignment_judge=_AlignmentJudge(),
        ).result_version == result.result_version
        assert db.query(SinglePromptDiagnosisExecution).filter_by(
            analysis_id=analysis.analysis_id
        ).count() == 2

        # A later immutable source version can use the formal V2 production
        # judges.  The executor shares one guarded client, performs no hidden
        # retry, and persists provider usage without moving either old result.
        latest = source_preparation.get_source_preparation_status(
            db, preparation_id=preparation.preparation_id
        )["sources"][0]
        third_text = "第三版真实正文继续说明甲工具支持批量生成短链，同时保留明确适用范围。" * 2
        third_snapshot = _submit(db, preparation.preparation_id, latest, third_text)
        third_manifest = source_preparation.freeze_completion_manifest(
            db, preparation_id=preparation.preparation_id, created_by="qa"
        )
        production_plans, production_created = plan_source_reanalysis(
            db,
            preparation_id=preparation.preparation_id,
            project_id=1,
            prompt_id=44,
            prior_completion_manifest_id=new_manifest.manifest_id,
            prior_completion_manifest_hash=new_manifest.payload_hash,
            new_completion_manifest_id=third_manifest.manifest_id,
            new_completion_manifest_hash=third_manifest.payload_hash,
            idempotency_key="t09-source-reanalysis-production",
            requested_by="qa",
        )
        assert production_created is True
        assert len(production_plans) == 1

        from app.services.semantic_llm import deepseek

        network_calls = []

        class ProviderResponse:
            status_code = 200
            text = json.dumps({
                "model": "deepseek-flash",
                "status": "completed",
                "output": [{"type": "message", "content": [{
                    "type": "output_text",
                    "text": json.dumps({"claims": []}, ensure_ascii=False),
                }]}],
                "usage": {"input_tokens": 17, "output_tokens": 3, "total_tokens": 20},
            }, ensure_ascii=False)

            def json(self):
                return json.loads(self.text)

        class ProviderHttp:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def post(self, url, headers, json):
                network_calls.append({"url": url, "body": json})
                return ProviderResponse()

        monkeypatch.setattr(deepseek.httpx, "Client", ProviderHttp)
        monkeypatch.setattr(deepseek.get_settings(), "deepseek_api_key", "isolated-test-key")
        reservations = []
        audits = []
        production_result = execute_source_reanalysis(
            db,
            reanalysis_id=production_plans[0].diagnosis_id,
            request_guard=reservations.append,
            response_audit_sink=audits.append,
            max_attempts=1,
        )
        production_output = json.loads(production_result.output_json)
        assert production_result.parent_result_version == result.result_version
        assert production_output["input"]["completion_manifest_id"] == third_manifest.manifest_id
        assert production_output["input"]["source_snapshot_ids"] == [third_snapshot.snapshot_id]
        assert production_output["usage"]["provider"] == "deepseek"
        assert production_output["usage"]["max_attempts"] == 1
        assert production_output["usage"]["external_llm_calls"] == 1
        assert production_output["usage"]["external_token_usage"] == 20
        assert len(reservations) == len(network_calls) == len(audits) == 1
        assert reservations[0]["attempt"] == 1
        assert reservations[0]["provider"] == "deepseek"
        db.refresh(production_plans[0])
        assert production_plans[0].external_llm_calls == 1
        assert production_plans[0].external_token_usage == 20
        progress = json.loads(production_plans[0].progress_json)
        assert progress["result_creation"] == "COMPLETED_EXTERNAL_V2"
        assert "raw_provider_response" not in json.dumps(progress)
        assert db.query(SinglePromptDiagnosisResult).filter_by(
            diagnosis_id=diagnosis.diagnosis_id, result_version=old_result.result_version
        ).one().output_json == old_result_json
    finally:
        db.close()
        engine.dispose()


def test_formal_executor_requires_shared_guard_and_forbids_hidden_retry():
    try:
        execute_source_reanalysis(object(), reanalysis_id="r", request_guard=None)  # type: ignore[arg-type]
        assert False, "missing guard must be rejected before touching the database"
    except Exception as exc:
        assert getattr(exc, "detail", {}) == {"code": "SOURCE_REANALYSIS_REQUEST_GUARD_REQUIRED"}

    try:
        execute_source_reanalysis(
            object(),  # type: ignore[arg-type]
            reanalysis_id="r",
            request_guard=lambda _: None,
            max_attempts=2,
        )
        assert False, "the T09 executor must never enable an implicit retry"
    except Exception as exc:
        assert getattr(exc, "detail", {}) == {"code": "SOURCE_REANALYSIS_SINGLE_ATTEMPT_REQUIRED"}


@pytest.mark.parametrize(
    ("field", "foreign_value"),
    (("project_id", 2), ("prompt_id", 45), ("context_id", "ctx-foreign")),
)
def test_answer_scope_guard_rejects_cross_scope_identity(field, foreign_value):
    expected = {
        "diagnosis_id": "diagnosis-1",
        "analysis_id": "analysis-1",
        "context_id": "context-1",
        "project_id": 1,
        "prompt_id": 44,
        "raw_output_hash": "a" * 64,
    }
    injected = {**expected, field: foreign_value}
    with pytest.raises(Exception) as exc:
        _require_answer_scope(injected, expected)
    assert getattr(exc.value, "detail", {}) == {
        "code": "SOURCE_REANALYSIS_ANSWER_SCOPE_MISMATCH"
    }


def _readiness_connection(*, include_base: bool, include_review: bool = False) -> tuple[sqlite3.Connection, dict]:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE single_prompt_analysis_contexts (
          context_id TEXT, analysis_id TEXT, project_id INTEGER, prompt_id INTEGER,
          raw_output_hash TEXT
        );
        CREATE TABLE single_prompt_source_completion_manifests (
          manifest_id TEXT, preparation_id TEXT, analysis_id TEXT, context_id TEXT,
          citation_manifest_id TEXT, version_number INTEGER, payload_json TEXT, payload_hash TEXT
        );
        CREATE TABLE single_prompt_diagnosis_executions (
          diagnosis_id TEXT, analysis_id TEXT, context_id TEXT, project_id INTEGER,
          prompt_id INTEGER, raw_output_hash TEXT
        );
        CREATE TABLE single_prompt_diagnosis_results (
          diagnosis_id TEXT, result_version TEXT, output_json TEXT, output_hash TEXT,
          reviewable_set_hash TEXT
        );
        CREATE TABLE single_prompt_diagnosis_reviews (
          diagnosis_id TEXT, review_id TEXT, result_version TEXT, result_hash TEXT,
          reviewable_set_hash TEXT, decision TEXT
        );
        """
    )
    connection.execute(
        "INSERT INTO single_prompt_analysis_contexts VALUES (?,?,?,?,?)",
        ("ctx-1", "analysis-1", 1, 44, "raw-hash"),
    )
    old_payload = {
        "sources": [{"source_key": "source-1", "snapshot_id": "snapshot-old", "content_hash": "old"}]
    }
    new_payload = {
        "sources": [{"source_key": "source-1", "snapshot_id": "snapshot-new", "content_hash": "new"}]
    }
    from scripts.check_t09_source_reanalysis_readiness import _canonical, _hash as readiness_hash

    inputs = {
        "project_id": 1,
        "prompt_id": 44,
        "prior_manifest_id": "manifest-old",
        "prior_manifest_hash": readiness_hash(old_payload),
        "new_manifest_id": "manifest-new",
        "new_manifest_hash": readiness_hash(new_payload),
    }
    for manifest_id, version, payload in (
        (inputs["prior_manifest_id"], 1, old_payload),
        (inputs["new_manifest_id"], 2, new_payload),
    ):
        connection.execute(
            "INSERT INTO single_prompt_source_completion_manifests VALUES (?,?,?,?,?,?,?,?)",
            (
                manifest_id, "prep-1", "analysis-1", "ctx-1", "citation-1", version,
                _canonical(payload), readiness_hash(payload),
            ),
        )
    if include_base:
        connection.execute(
            "INSERT INTO single_prompt_diagnosis_executions VALUES (?,?,?,?,?,?)",
            ("diagnosis-1", "analysis-1", "ctx-1", 1, 44, "raw-hash"),
        )
        answer_output = {"answer_diagnosis": {"events": []}}
        answer_hash = readiness_hash(answer_output)
        connection.execute(
            "INSERT INTO single_prompt_diagnosis_results VALUES (?,?,?,?,?)",
            ("diagnosis-1", "answer-v1", _canonical(answer_output), answer_hash, "reviewable-1"),
        )
        evidence_output = {"input": {
            "completion_manifest_id": "manifest-old",
            "source_snapshot_ids": ["snapshot-old"],
            "answer_result_version": "answer-v1",
            "answer_result_hash": answer_hash,
            "answer_review_id": "review-1",
        }}
        connection.execute(
            "INSERT INTO single_prompt_diagnosis_results VALUES (?,?,?,?,?)",
            ("diagnosis-1", "evidence-v1", _canonical(evidence_output), readiness_hash(evidence_output), "reviewable-2"),
        )
        if include_review:
            connection.execute(
                "INSERT INTO single_prompt_diagnosis_reviews VALUES (?,?,?,?,?,?)",
                ("diagnosis-1", "review-1", "answer-v1", answer_hash, "reviewable-1", "REVIEW_COMPLETED"),
            )
    connection.commit()
    return connection, inputs


def test_t09_readiness_reports_exact_missing_objects_without_creating_review():
    connection, inputs = _readiness_connection(include_base=False)
    try:
        report = assess_readiness(connection, **inputs)
    finally:
        connection.close()
    assert report["status"] == "BLOCKED"
    assert report["t09_status"] == "BLOCKED"
    assert report["gate_code"] == "T09_REVIEWED_DOWNSTREAM_BASE_REQUIRED"
    assert report["root_cause_classification"] == "MISSING_FORMAL_OBJECTS_NOT_SELECTOR_DEFECT"
    assert report["external_model_calls"] == 0
    assert report["safety"] == {
        "database_writes": 0,
        "reviews_created": 0,
        "provider_client_loaded": False,
    }
    assert report["observed_counts"] == {
        "exact_scope_diagnosis_executions": 0,
        "exact_scope_diagnosis_results": 0,
        "eligible_reviewed_downstream_bases": 0,
    }
    assert {item["object"] for item in report["missing_objects"]} == {
        "SinglePromptDiagnosisExecution",
        "SinglePromptDiagnosisResult",
        "SinglePromptDiagnosisReview",
    }
    assert [item["actor"] for item in report["required_actions"]] == [
        "SYSTEM", "AUTHORIZED_HUMAN_REVIEWER", "SYSTEM"
    ]


def test_t09_readiness_requires_exact_review_then_accepts_eligible_base():
    connection, inputs = _readiness_connection(include_base=True, include_review=False)
    try:
        blocked = assess_readiness(connection, **inputs)
        assert blocked["status"] == "BLOCKED"
        assert blocked["rejected_bases"][0]["reason"] == "EXACT_ANSWER_REVIEW_NOT_FOUND"
        answer_hash = connection.execute(
            "SELECT output_hash FROM single_prompt_diagnosis_results WHERE result_version='answer-v1'"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO single_prompt_diagnosis_reviews VALUES (?,?,?,?,?,?)",
            ("diagnosis-1", "review-1", "answer-v1", answer_hash, "reviewable-1", "REVIEW_COMPLETED"),
        )
        connection.commit()
        ready = assess_readiness(connection, **inputs)
    finally:
        connection.close()
    assert ready["status"] == "READY"
    assert ready["t09_status"] == "READY_FOR_REANALYSIS_PLANNING"
    assert ready["external_model_calls"] == 0
    assert ready["observed_counts"]["eligible_reviewed_downstream_bases"] == 1
    assert ready["missing_objects"] == []
    assert ready["required_actions"] == []
