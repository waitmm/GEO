from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from app.core.release_database import get_release_db
from app.models import (
    Base,
    BrowserMonitorRun,
    BrowserMonitorTask,
    Organization,
    Project,
    Prompt,
    ReferenceSource,
    SinglePromptAnalysisContext,
    SinglePromptCitationContributionExecution,
    SinglePromptCitationContributionResult,
    SinglePromptCitationContributionReview,
    SinglePromptCitationManifest,
    SinglePromptDiagnosisExecution,
    SinglePromptDiagnosisResult,
    SinglePromptDiagnosisReview,
    SinglePromptPreparedSourceSnapshot,
    SinglePromptSourceCompletionManifest,
)
from app.modules.single_prompt_v2.diagnosis import (
    claim_diagnosis,
    complete_diagnosis_review,
    compute_answer_diagnosis,
    continue_evidence_diagnosis,
    create_answer_diagnosis,
    get_diagnosis_status,
    queue_evidence_continuation,
    recover_interrupted_diagnoses,
)
from app.modules.single_prompt_v2.citation_contribution import (
    CitationContributionResponse,
    CitationContributionJudge,
    _build_calibration_set,
    _rank_candidate_passages,
    authorize_citation_contribution,
    build_answer_units,
    complete_citation_contribution_review,
    create_citation_contribution_plan,
    execute_citation_contribution,
    get_citation_contribution_status,
    recover_interrupted_citation_contributions,
    select_p1_run,
)
from app.modules.single_prompt_v2 import source_preparation
from app.modules.single_prompt_v2.schemas import SinglePromptManualSourceContentCreate
from app.modules.single_prompt_v2.service import (
    claim_analysis,
    create_analysis,
    create_analysis_from_runs,
    finalize_analysis,
    get_analysis_status,
    list_prompt_run_pool,
    queue_run_retry,
    recover_interrupted_analyses,
)
from app.release_main import create_release_app
from app.release_schema import (
    RELEASE_SCHEMA_REVISION,
    RELEASE_TABLE_ALLOWLIST,
    inspect_release_database,
    sqlite_has_wal_reset_fix,
    validate_release_database,
)
from scripts import release_worker


ROOT = Path(__file__).resolve().parents[1]


def _configure_artifacts(monkeypatch, tmp_path: Path) -> Path:
    root = tmp_path / "evidence-artifacts"
    monkeypatch.setattr(
        source_preparation,
        "get_settings",
        lambda: SimpleNamespace(evidence_artifact_dir=str(root)),
    )
    return root


def _session(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'release-first-slice.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)(), engine


def _migrated_session(tmp_path: Path, monkeypatch):
    database_path = tmp_path / "migrated-release-first-slice.db"
    monkeypatch.setenv("GEO_RELEASE_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    command.upgrade(Config(str(ROOT / "alembic.release.ini")), "head")
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _pragmas(connection, record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    return sessionmaker(bind=engine, expire_on_commit=False)(), engine


def _seed_frozen_analysis(db, *, reference_urls: list[str]):
    db.add(Organization(id=1, name="Release Org", plan_type="release-1.0"))
    db.add(Project(id=1, organization_id=1, name="Release", brand_name="Target"))
    db.add(Prompt(id=44, project_id=1, title="Prompt", prompt_text="推荐一个短链工具"))
    db.commit()
    analysis, _ = create_analysis(
        db,
        project_id=1,
        prompt_id=44,
        sample_count=1,
        idempotency_key="release-sampling-0001",
    )
    token = claim_analysis(db, analysis.analysis_id)
    run = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).one()
    run.status = "success"
    run.stage = "success"
    run.answer_text = "甲工具值得推荐，因为支持批量生成短链。"
    run.answer_char_count = len(run.answer_text)
    run.reference_complete = True
    for index, url in enumerate(reference_urls, start=1):
        db.add(ReferenceSource(
            run_id=run.id,
            reference_index=index,
            display_title=f"来源 {index}",
            url=url,
        ))
    db.commit()
    assert token and finalize_analysis(db, analysis.analysis_id, token)
    return analysis


def _create_preparation(db, analysis):
    preparation, created = source_preparation.create_source_preparation(
        db,
        analysis_id=analysis.analysis_id,
        project_id=1,
        prompt_id=44,
        idempotency_key="source-preparation-0001",
        created_by="qa",
    )
    assert created is True
    return preparation, source_preparation.get_source_preparation_status(
        db,
        preparation_id=preparation.preparation_id,
    )


def _submit(db, preparation_id: str, source: dict, text: str, *, title: str = "真实正文"):
    return source_preparation.submit_manual_content(
        db,
        preparation_id=preparation_id,
        source_key=source["source_key"],
        expected_row_version=source["row_version"],
        title=title,
        clean_text=text,
        coverage_scope="FULL_PAGE",
        submitted_by="qa",
    )


def _seed_citation_contribution_fixture(db, monkeypatch, tmp_path: Path):
    _configure_artifacts(monkeypatch, tmp_path)
    analysis = _seed_frozen_analysis(
        db,
        reference_urls=["https://example.com/ready", "https://example.com/waived"],
    )
    run = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).one()
    context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis.analysis_id).one()
    preparation, status = _create_preparation(db, analysis)
    ready_source, waived_source = status["sources"]
    _submit(
        db,
        preparation.preparation_id,
        ready_source,
        "甲工具支持批量生成短链。该能力适用于需要批量处理链接的业务场景。"
        "使用者可以在明确的业务范围内创建和管理短链，并查看每条短链的处理结果。",
    )
    refreshed = source_preparation.get_source_preparation_status(
        db,
        preparation_id=preparation.preparation_id,
    )
    waived_source = next(item for item in refreshed["sources"] if item["source_key"] == waived_source["source_key"])
    source_preparation.waive_source(
        db,
        preparation_id=preparation.preparation_id,
        source_key=waived_source["source_key"],
        expected_row_version=waived_source["row_version"],
        reason="测试来源无法取得",
        impact="该来源不参与 Contribution 判断",
        waived_by="qa",
    )
    completion = source_preparation.freeze_completion_manifest(
        db,
        preparation_id=preparation.preparation_id,
        created_by="qa",
    )
    manifest = db.query(SinglePromptCitationManifest).filter_by(analysis_id=analysis.analysis_id).one()

    raw_start = run.answer_text.index("甲工具")
    raw_end = len(run.answer_text)
    answer_output = {
        "answer_diagnosis": {
            "events": [{
                "event_id": "evt-fixture",
                "run_id": run.id,
                "entity_text": "甲工具",
                "raw_start": raw_start,
                "raw_end": raw_end,
            }],
        },
    }
    answer_output_json = json.dumps(answer_output, ensure_ascii=False, sort_keys=True)
    answer_hash = hashlib.sha256(answer_output_json.encode()).hexdigest()
    diagnosis = SinglePromptDiagnosisExecution(
        diagnosis_id="diagnosis-contribution-fixture",
        analysis_id=analysis.analysis_id,
        context_id=context.context_id,
        project_id=analysis.project_id,
        prompt_id=analysis.prompt_id,
        idempotency_key="diagnosis-contribution-fixture-key",
        input_fingerprint="d" * 64,
        raw_output_hash=context.raw_output_hash,
        brand_snapshot_json="{}",
        brand_snapshot_hash="b" * 64,
        truth_snapshot_json="[]",
        truth_set_hash="t" * 64,
        contract_config_json="{}",
        contract_config_hash="c" * 64,
        status="REVIEW_COMPLETED",
        active_result_version="diag-v1:contribution-fixture",
    )
    result = SinglePromptDiagnosisResult(
        result_version="diag-v1:contribution-fixture",
        diagnosis_id=diagnosis.diagnosis_id,
        version_number=1,
        output_json=answer_output_json,
        output_hash=answer_hash,
        reviewable_set_hash="r" * 64,
    )
    review = SinglePromptDiagnosisReview(
        review_id="review-contribution-fixture",
        diagnosis_id=diagnosis.diagnosis_id,
        result_version=result.result_version,
        result_hash=answer_hash,
        reviewable_set_hash=result.reviewable_set_hash,
        reviewer="qa",
    )
    db.add_all([diagnosis, result, review])
    db.commit()
    return {
        "analysis": analysis,
        "run": run,
        "context": context,
        "manifest": manifest,
        "completion": completion,
        "result": result,
        "review": review,
    }


def _create_contribution_fixture_plan(db, fixture, *, idempotency_key="citation-contribution-fixture-plan"):
    return create_citation_contribution_plan(
        db,
        analysis_id=fixture["analysis"].analysis_id,
        project_id=fixture["analysis"].project_id,
        prompt_id=fixture["analysis"].prompt_id,
        answer_result_version=fixture["result"].result_version,
        answer_result_hash=fixture["result"].output_hash,
        answer_review_id=fixture["review"].review_id,
        citation_manifest_id=fixture["manifest"].manifest_id,
        citation_manifest_hash=fixture["manifest"].payload_hash,
        completion_manifest_id=fixture["completion"].manifest_id,
        completion_manifest_hash=fixture["completion"].payload_hash,
        fixed_run_ids=[fixture["run"].id],
        idempotency_key=idempotency_key,
    )


def test_manual_html_payload_accepts_source_larger_than_legacy_five_million_limit():
    raw_html = "<main>" + ("页面源码内容" * 833_334) + "</main>"
    payload = SinglePromptManualSourceContentCreate(
        project_id=1,
        prompt_id=44,
        source_key="a" * 64,
        expected_row_version=1,
        title="大型页面源码",
        input_format="HTML_SOURCE",
        clean_text="",
        raw_html=raw_html,
        coverage_scope="FULL_PAGE",
        submitted_by="qa",
    )
    assert len(payload.raw_html) > 5_000_000


def test_release_migration_is_explicit_allowlisted_and_runtime_version_is_checked(tmp_path, monkeypatch):
    database_path = tmp_path / "geo-release.db"
    monkeypatch.setenv("GEO_RELEASE_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    config = Config(str(ROOT / "alembic.release.ini"))
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")

    @event.listens_for(engine, "connect")
    def _pragmas(connection, record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    status = inspect_release_database(engine)
    assert status["revision"] == RELEASE_SCHEMA_REVISION
    assert set(status["tables"]) == RELEASE_TABLE_ALLOWLIST
    assert status["missing_tables"] == []
    assert status["unexpected_tables"] == []
    assert status["journal_mode"] == "wal"
    assert status["foreign_keys"] == 1
    assert "optimization_evidence_packages" not in status["tables"]
    assert "runtime_stage_executions" not in status["tables"]
    assert "single_prompt_strategy_executions" in status["tables"]
    assert "single_prompt_strategy_results" in status["tables"]
    assert "single_prompt_strategy_reviews" in status["tables"]
    assert "single_prompt_citation_contribution_executions" in status["tables"]
    assert "single_prompt_citation_contribution_results" in status["tables"]
    assert "single_prompt_citation_contribution_reviews" in status["tables"]
    assert "single_prompt_execution_proposals" not in status["tables"]

    if sqlite_has_wal_reset_fix(status["sqlite_version"]):
        assert validate_release_database(engine)["status"] == "READY"
    else:
        with pytest.raises(RuntimeError, match="RELEASE_SQLITE_VERSION_UNSAFE"):
            validate_release_database(engine)
    engine.dispose()


def test_run_selection_migration_preserves_populated_release_history(tmp_path, monkeypatch):
    database_path = tmp_path / "populated-release.db"
    monkeypatch.setenv("GEO_RELEASE_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    config = Config(str(ROOT / "alembic.release.ini"))
    command.upgrade(config, "20260920_02")

    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _old_pragmas(connection, record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    db = sessionmaker(bind=engine, expire_on_commit=False)()
    analysis = _seed_frozen_analysis(db, reference_urls=["https://example.com/history"])
    context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis.analysis_id).one()
    frozen = {
        "analysis_id": analysis.analysis_id,
        "task_id": analysis.task_id,
        "context_id": context.context_id,
        "raw_output_hash": context.raw_output_hash,
    }
    db.close()
    engine.dispose()

    command.upgrade(config, "head")
    migrated_engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(migrated_engine, "connect")
    def _new_pragmas(connection, record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    migrated_db = sessionmaker(bind=migrated_engine, expire_on_commit=False)()
    try:
        persisted = migrated_db.query(SinglePromptAnalysisContext).filter_by(
            context_id=frozen["context_id"]
        ).one()
        assert persisted.analysis_id == frozen["analysis_id"]
        assert persisted.task_id == frozen["task_id"]
        assert persisted.raw_output_hash == frozen["raw_output_hash"]
        assert migrated_engine.connect().execute(text("PRAGMA foreign_key_check")).fetchall() == []
        with pytest.raises(Exception, match="RELEASE_HISTORY_IMMUTABLE"):
            persisted.raw_output_hash = "0" * 64
            migrated_db.commit()
        migrated_db.rollback()
    finally:
        migrated_db.close()
        migrated_engine.dispose()


def test_release_startup_contract_rejects_unmigrated_database(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'unmigrated.db').as_posix()}")
    with pytest.raises(RuntimeError, match="RELEASE_SCHEMA_REVISION_MISMATCH:UNMIGRATED"):
        validate_release_database(engine)
    engine.dispose()


def test_release_routes_include_strategy_but_exclude_execution_and_legacy_workflows():
    app = create_release_app(validate_on_startup=False)
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/v2/single-prompt/analyses" in paths
    assert any("source-preparation" in path for path in paths)
    assert any("evidence-continuations" in path for path in paths)
    assert any("citation-contributions" in path for path in paths)
    assert any(path.endswith("/strategy-readiness") for path in paths)
    assert any(path.endswith("/strategies") for path in paths)
    assert any(path.endswith("/priority-revisions") for path in paths)
    assert any("/strategies/" in path and path.endswith("/reviews") for path in paths)
    assert not any("execution-proposal" in path for path in paths)
    assert not any("retest" in path for path in paths)
    assert not any(path.startswith("/api/optimization") for path in paths)

    response = TestClient(app).get("/api/optimization/workflow/1/prompt-overview")
    assert response.status_code == 404
    assert response.json() == {"detail": "Release API route not found"}


def test_release_lists_explicit_prompt_analyses_without_latest_substitution(tmp_path):
    db, engine = _session(tmp_path)
    app = create_release_app(validate_on_startup=False)

    def override_release_db():
        yield db

    app.dependency_overrides[get_release_db] = override_release_db
    try:
        db.add(Organization(id=1, name="Release Org", plan_type="release-1.0"))
        db.add(Project(id=1, organization_id=1, name="Release", brand_name="Target"))
        db.add(Prompt(id=44, project_id=1, title="Prompt A", prompt_text="Prompt A"))
        db.add(Prompt(id=45, project_id=1, title="Prompt B", prompt_text="Prompt B"))
        db.commit()
        first, _ = create_analysis(
            db,
            project_id=1,
            prompt_id=44,
            sample_count=1,
            idempotency_key="analysis-list-first",
        )
        second, _ = create_analysis(
            db,
            project_id=1,
            prompt_id=44,
            sample_count=2,
            idempotency_key="analysis-list-second",
        )
        other_prompt, _ = create_analysis(
            db,
            project_id=1,
            prompt_id=45,
            sample_count=1,
            idempotency_key="analysis-list-other",
        )

        response = TestClient(app).get(
            "/api/v2/single-prompt/analyses?project_id=1&prompt_id=44"
        )

        assert response.status_code == 200
        rows = response.json()
        assert [row["analysis"]["analysis_id"] for row in rows] == [
            second.analysis_id,
            first.analysis_id,
        ]
        assert all(row["analysis"]["prompt_id"] == 44 for row in rows)
        assert all(row["source_preparation_summary"] is None for row in rows)
        assert other_prompt.analysis_id not in {
            row["analysis"]["analysis_id"] for row in rows
        }
        assert TestClient(app).get(
            "/api/v2/single-prompt/analyses?project_id=1&prompt_id=44&limit=0"
        ).status_code == 422
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_release_run_pool_creates_exact_analysis_without_sampling_or_mutating_history(tmp_path):
    db, engine = _session(tmp_path)
    try:
        original = _seed_frozen_analysis(
            db,
            reference_urls=["https://example.com/a", "https://example.com/b"],
        )
        original_context = db.query(SinglePromptAnalysisContext).filter_by(
            analysis_id=original.analysis_id
        ).one()
        original_hash = original_context.raw_output_hash
        task_count = db.query(BrowserMonitorTask).count()

        pool = list_prompt_run_pool(db, project_id=1, prompt_id=44, page=1, page_size=20)
        assert pool["total"] == 1
        run = pool["items"][0]
        assert run["run_id"] == 1
        assert run["references"]
        assert run["analysis_memberships"] == [{
            "analysis_id": original.analysis_id,
            "context_id": original_context.context_id,
        }]

        selected, created = create_analysis_from_runs(
            db,
            project_id=1,
            prompt_id=44,
            run_ids=[run["run_id"]],
            run_fingerprints={run["run_id"]: run["input_fingerprint"]},
            base_context_id=original_context.context_id,
            idempotency_key="explicit-run-selection-0001",
        )

        assert created is True
        assert selected.task_id is None
        assert db.query(BrowserMonitorTask).count() == task_count
        assert db.query(SinglePromptAnalysisContext).filter_by(
            analysis_id=original.analysis_id
        ).one().raw_output_hash == original_hash
        selected_status = get_analysis_status(db, selected.analysis_id)
        assert selected_status["analysis"]["task_id"] is None
        assert selected_status["active_task"] is None
        assert [row["run_id"] for row in selected_status["runs"]] == [run["run_id"]]

        preparation, created_preparation = source_preparation.create_source_preparation(
            db,
            analysis_id=selected.analysis_id,
            project_id=1,
            prompt_id=44,
            idempotency_key="selected-analysis-source-prep",
            created_by="qa",
        )
        assert created_preparation is True
        status = source_preparation.get_source_preparation_status(
            db, preparation_id=preparation.preparation_id
        )
        assert status["citation_manifest"]["source_count"] == 2

        with pytest.raises(HTTPException) as stale:
            create_analysis_from_runs(
                db,
                project_id=1,
                prompt_id=44,
                run_ids=[run["run_id"]],
                run_fingerprints={run["run_id"]: "0" * 64},
                base_context_id=original_context.context_id,
                idempotency_key="explicit-run-selection-stale",
            )
        assert stale.value.status_code == 409
        assert stale.value.detail["code"] == "RUN_INPUT_CHANGED"

        with pytest.raises(HTTPException, match="重复"):
            create_analysis_from_runs(
                db,
                project_id=1,
                prompt_id=44,
                run_ids=[run["run_id"], run["run_id"]],
                run_fingerprints={run["run_id"]: run["input_fingerprint"]},
                base_context_id=None,
                idempotency_key="explicit-run-selection-duplicate",
            )
    finally:
        db.close()
        engine.dispose()


def test_release_run_selection_combines_tasks_and_rejects_cross_project_runs(tmp_path):
    db, engine = _session(tmp_path)
    try:
        original = _seed_frozen_analysis(db, reference_urls=["https://example.com/history"])
        original_context = db.query(SinglePromptAnalysisContext).filter_by(
            analysis_id=original.analysis_id
        ).one()
        additional, _ = create_analysis(
            db,
            project_id=1,
            prompt_id=44,
            sample_count=1,
            idempotency_key="additional-sampling-task",
        )
        token = claim_analysis(db, additional.analysis_id)
        additional_run = db.query(BrowserMonitorRun).filter_by(task_id=additional.task_id).one()
        additional_run.status = "success"
        additional_run.stage = "success"
        additional_run.answer_text = "新增采样回答"
        additional_run.answer_char_count = len(additional_run.answer_text)
        additional_run.reference_complete = True
        db.commit()
        assert token and finalize_analysis(db, additional.analysis_id, token)

        pool = list_prompt_run_pool(db, project_id=1, prompt_id=44, page=1, page_size=20)
        assert pool["total"] == 2
        by_id = {row["run_id"]: row for row in pool["items"]}
        selected_ids = sorted(by_id)
        combined, created = create_analysis_from_runs(
            db,
            project_id=1,
            prompt_id=44,
            run_ids=selected_ids,
            run_fingerprints={run_id: by_id[run_id]["input_fingerprint"] for run_id in selected_ids},
            base_context_id=original_context.context_id,
            idempotency_key="history-plus-additional-runs",
        )
        assert created is True
        assert combined.task_id is None
        assert [
            row["run_id"] for row in get_analysis_status(db, combined.analysis_id)["runs"]
        ] == selected_ids

        db.add(Project(id=2, organization_id=1, name="Other", brand_name="Other"))
        db.add(Prompt(id=45, project_id=2, title="Other Prompt", prompt_text="其他问题"))
        db.commit()
        foreign, _ = create_analysis(
            db,
            project_id=2,
            prompt_id=45,
            sample_count=1,
            idempotency_key="cross-project-sampling",
        )
        foreign_token = claim_analysis(db, foreign.analysis_id)
        foreign_run = db.query(BrowserMonitorRun).filter_by(task_id=foreign.task_id).one()
        foreign_run.status = "success"
        foreign_run.stage = "success"
        foreign_run.answer_text = "跨项目回答"
        foreign_run.answer_char_count = len(foreign_run.answer_text)
        foreign_run.reference_complete = True
        db.commit()
        assert foreign_token and finalize_analysis(db, foreign.analysis_id, foreign_token)

        with pytest.raises(HTTPException) as mismatch:
            create_analysis_from_runs(
                db,
                project_id=1,
                prompt_id=44,
                run_ids=[foreign_run.id],
                run_fingerprints={foreign_run.id: "irrelevant-before-scope-check"},
                base_context_id=original_context.context_id,
                idempotency_key="cross-project-run-selection",
            )
        assert mismatch.value.status_code == 409
        assert mismatch.value.detail == {"code": "RUN_SCOPE_MISMATCH", "run_ids": [foreign_run.id]}
    finally:
        db.close()
        engine.dispose()


def test_release_single_run_retry_creates_new_attempt_and_preserves_source_run(tmp_path):
    db, engine = _session(tmp_path)
    try:
        db.add(Organization(id=1, name="Release Org", plan_type="release-1.0"))
        db.add(Project(id=1, organization_id=1, name="Release", brand_name="Target"))
        db.add(Prompt(id=44, project_id=1, title="Prompt", prompt_text="推荐一个短链工具"))
        db.commit()
        analysis, _ = create_analysis(
            db,
            project_id=1,
            prompt_id=44,
            sample_count=1,
            idempotency_key="failed-run-analysis",
        )
        source = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).one()
        source.status = "failed"
        source.stage = "failed"
        source.error_type = "temporary_browser_error"
        source.error_message = "temporary"
        source.answer_text = "保留的失败现场"
        db.add(ReferenceSource(
            run_id=source.id,
            reference_index=1,
            display_title="保留来源",
            url="https://example.com/source",
        ))
        db.commit()
        source_id = source.id
        original_task_id = source.task_id

        retry_run, created = queue_run_retry(
            db,
            run_id=source_id,
            project_id=1,
            prompt_id=44,
            idempotency_key="run-retry-request-0001",
        )

        assert created is True
        assert retry_run.id != source_id
        assert retry_run.task_id != original_task_id
        assert retry_run.status == "queued"
        assert retry_run.original_query == "推荐一个短链工具"
        db.expire_all()
        preserved = db.get(BrowserMonitorRun, source_id)
        assert preserved.status == "failed"
        assert preserved.answer_text == "保留的失败现场"
        assert db.query(ReferenceSource).filter_by(run_id=source_id).count() == 1

        same_retry, created_again = queue_run_retry(
            db,
            run_id=source_id,
            project_id=1,
            prompt_id=44,
            idempotency_key="run-retry-request-0001",
        )
        assert created_again is False
        assert same_retry.id == retry_run.id
    finally:
        db.close()
        engine.dispose()


def test_release_worker_keeps_failed_runs_retryable_before_context_freeze(tmp_path, monkeypatch):
    db, engine = _session(tmp_path)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        db.add(Organization(id=1, name="Release Org", plan_type="release-1.0"))
        db.add(Project(id=1, organization_id=1, name="Release", brand_name="Target"))
        db.add(Prompt(id=44, project_id=1, title="Prompt", prompt_text="推荐一个短链工具"))
        db.commit()
        analysis, _ = create_analysis(
            db,
            project_id=1,
            prompt_id=44,
            sample_count=3,
            idempotency_key="release-worker-retryable",
        )
        called = {}

        def fake_execute_analysis(identity, **kwargs):
            called.update({"identity": identity, **kwargs})

        monkeypatch.setattr(release_worker, "ReleaseSessionLocal", factory)
        monkeypatch.setattr(release_worker, "execute_analysis", fake_execute_analysis)

        assert release_worker.run_once() == f"analysis:{analysis.analysis_id}"
        assert called["identity"] == analysis.analysis_id
        assert called["freeze_with_failures"] is False
        assert called["session_factory"] is factory
    finally:
        db.close()
        engine.dispose()


def test_release_worker_executes_only_the_queued_single_run_retry(tmp_path, monkeypatch):
    db, engine = _session(tmp_path)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        db.add(Organization(id=1, name="Release Org", plan_type="release-1.0"))
        db.add(Project(id=1, organization_id=1, name="Release", brand_name="Target"))
        db.add(Prompt(id=44, project_id=1, title="Prompt", prompt_text="推荐一个短链工具"))
        db.commit()
        analysis, _ = create_analysis(
            db,
            project_id=1,
            prompt_id=44,
            sample_count=2,
            idempotency_key="release-worker-single-retry",
        )
        runs = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).order_by(BrowserMonitorRun.id).all()
        failed, successful = runs
        failed.status = "failed"
        failed.stage = "failed"
        failed.error_type = "temporary_browser_error"
        successful.status = "success"
        successful.stage = "success"
        successful.answer_text = "保留成功回答"
        db.commit()
        retry, _ = queue_run_retry(
            db,
            run_id=failed.id,
            project_id=1,
            prompt_id=44,
            idempotency_key="worker-retry-one-run",
        )
        calls: list[tuple[str, int]] = []

        class FakeExecutor:
            def execute_queued_runs(self, session, task_id):
                calls.append(("execute", task_id))

            def close(self):
                calls.append(("close", 0))

        def fake_update_task_status(session, task):
            calls.append(("update", task.id))

        monkeypatch.setattr(release_worker, "ReleaseSessionLocal", factory)
        monkeypatch.setattr(release_worker, "MonitoringTaskExecutor", FakeExecutor)
        monkeypatch.setattr(release_worker, "update_task_status_from_runs", fake_update_task_status)

        assert release_worker.run_once() == f"run_retry:{retry.task_id}"
        assert calls == [("execute", retry.task_id), ("update", retry.task_id), ("close", 0)]
        db.expire_all()
        assert db.get(BrowserMonitorRun, successful.id).answer_text == "保留成功回答"
        assert db.get(BrowserMonitorRun, failed.id).status == "failed"
    finally:
        db.close()
        engine.dispose()


def test_release_worker_executes_queued_source_fetch(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        analysis = _seed_frozen_analysis(db, reference_urls=["https://example.com/source"])
        preparation, _ = _create_preparation(db, analysis)
        source_preparation.queue_auto_fetch(
            db,
            preparation_id=preparation.preparation_id,
            project_id=1,
            prompt_id=44,
        )
        called = {}

        def fake_execute_source(identity, **kwargs):
            called.update({"identity": identity, **kwargs})

        monkeypatch.setattr(release_worker, "ReleaseSessionLocal", factory)
        monkeypatch.setattr(release_worker, "execute_auto_fetch", fake_execute_source)

        assert release_worker.run_once() == f"source:{preparation.preparation_id}"
        assert called == {"identity": preparation.preparation_id, "session_factory": factory}
    finally:
        db.close()
        engine.dispose()


def test_auto_fetch_creates_v2_snapshot_and_leaves_failures_for_manual_resolution(tmp_path, monkeypatch):
    artifact_root = _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        analysis = _seed_frozen_analysis(
            db,
            reference_urls=["https://example.com/ready", "https://example.com/partial"],
        )
        preparation, initial = _create_preparation(db, analysis)
        assert initial["preparation"]["status"] == "AUTO_FETCH_PENDING"
        assert initial["allowed_operations"][:1] == ["QUEUE_AUTO_FETCH"]
        source_preparation.queue_auto_fetch(
            db,
            preparation_id=preparation.preparation_id,
            project_id=1,
            prompt_id=44,
        )

        def fake_fetcher(urls):
            return [
                {
                    "canonical_url": url,
                    "fetch_status": "PARTIAL" if url.endswith("/partial") else "SUCCESS",
                    "failure_reason": "正文不完整" if url.endswith("/partial") else "",
                    "title": "自动获取标题",
                    "clean_text": "不完整" if url.endswith("/partial") else "自动获取的真实正文，明确保留主体、能力和适用边界。" * 5,
                }
                for url in urls
            ]

        summary = source_preparation.execute_auto_fetch(
            preparation.preparation_id,
            session_factory=factory,
            fetcher=fake_fetcher,
        )
        assert summary == {"requested": 2, "ready": 1, "manual_required": 1}

        db.expire_all()
        status = source_preparation.get_source_preparation_status(db, preparation_id=preparation.preparation_id)
        assert status["preparation"]["status"] == "MANUAL_REQUIRED"
        assert status["conservation"]["by_state"] == {"READY": 1, "MANUAL_REQUIRED": 1}
        ready = next(row for row in status["sources"] if row["state"] == "READY")
        manual = next(row for row in status["sources"] if row["state"] == "MANUAL_REQUIRED")
        assert ready["snapshot"]["acquisition_method"] == "AUTO_FETCH"
        assert ready["snapshot"]["artifact_path"].startswith(str(artifact_root))
        assert Path(ready["snapshot"]["artifact_path"]).is_file()
        assert manual["failure"]["code"] == "PARTIAL"
        assert manual["waiver"] is None
        assert status["completion_manifest"] is None

        _submit(
            db,
            preparation.preparation_id,
            manual,
            "人工补录失败来源的真实正文，保留完整上下文、主体和能力边界。" * 4,
        )
        completed = source_preparation.get_source_preparation_status(db, preparation_id=preparation.preparation_id)
        assert completed["preparation"]["status"] == "READY_TO_FREEZE"
        assert completed["conservation"]["by_state"] == {"READY": 2}
    finally:
        db.close()
        engine.dispose()


def test_auto_fetch_never_waives_and_interrupted_fetch_requires_explicit_resolution(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    try:
        analysis = _seed_frozen_analysis(db, reference_urls=["https://example.com/interrupted"])
        preparation, _ = _create_preparation(db, analysis)
        source_preparation.queue_auto_fetch(
            db,
            preparation_id=preparation.preparation_id,
            project_id=1,
            prompt_id=44,
        )
        preparation.status = "AUTO_FETCHING"
        disposition = db.query(source_preparation.SinglePromptSourceDisposition).filter_by(
            preparation_id=preparation.preparation_id
        ).one()
        disposition.state = "AUTO_FETCHING"
        db.commit()

        assert source_preparation.recover_interrupted_source_preparations(db) == 1
        status = source_preparation.get_source_preparation_status(db, preparation_id=preparation.preparation_id)
        assert status["preparation"]["status"] == "MANUAL_REQUIRED"
        assert status["sources"][0]["state"] == "MANUAL_REQUIRED"
        assert status["sources"][0]["failure"]["code"] == "AUTO_FETCH_INTERRUPTED"
        assert status["sources"][0]["waiver"] is None
    finally:
        db.close()
        engine.dispose()


def test_restart_repairs_settled_auto_fetch_summary_without_refetching(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    try:
        analysis = _seed_frozen_analysis(db, reference_urls=["https://example.com/manual"])
        preparation, _ = _create_preparation(db, analysis)
        disposition = db.query(source_preparation.SinglePromptSourceDisposition).filter_by(
            preparation_id=preparation.preparation_id
        ).one()
        disposition.state = "MANUAL_REQUIRED"
        disposition.failure_code = "FETCH_FAILED"
        disposition.failure_detail = "timeout"
        preparation.status = "AUTO_FETCH_PENDING"
        db.commit()

        assert source_preparation.recover_interrupted_source_preparations(db) == 1
        db.refresh(preparation)
        assert preparation.status == "MANUAL_REQUIRED"
        db.refresh(disposition)
        assert disposition.state == "MANUAL_REQUIRED"
        assert disposition.failure_code == "FETCH_FAILED"
    finally:
        db.close()
        engine.dispose()


def test_release_restart_preserves_queued_work_and_fails_only_running_work(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    try:
        analysis = _seed_frozen_analysis(db, reference_urls=["https://example.com/only"])
        preparation, status = _create_preparation(db, analysis)
        diagnosis, _ = create_answer_diagnosis(
            db,
            analysis_id=analysis.analysis_id,
            project_id=1,
            prompt_id=44,
            citation_manifest_id=status["citation_manifest"]["manifest_id"],
            citation_manifest_hash=status["citation_manifest"]["payload_hash"],
            answer_llm_policy="CACHE_ONLY",
            idempotency_key="restart-queue-answer",
        )

        analysis.status = "QUEUED"
        diagnosis.status = "EVIDENCE_QUEUED"
        db.commit()
        assert recover_interrupted_analyses(db) == 0
        assert recover_interrupted_diagnoses(db) == 0
        db.refresh(analysis)
        db.refresh(diagnosis)
        assert analysis.status == "QUEUED"
        assert diagnosis.status == "EVIDENCE_QUEUED"

        analysis.status = "COLLECTING"
        diagnosis.status = "EVIDENCE_RUNNING"
        db.commit()
        assert recover_interrupted_analyses(db) == 1
        assert recover_interrupted_diagnoses(db) == 1
        db.refresh(analysis)
        db.refresh(diagnosis)
        assert analysis.status == "INTERRUPTED"
        assert diagnosis.status == "EVIDENCE_FAILED"
        assert diagnosis.blocker_code == "SERVICE_RESTART_INTERRUPTED"
    finally:
        db.close()
        engine.dispose()


def test_manual_source_completion_freezes_exact_content_and_waiver_limitations(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    try:
        analysis = _seed_frozen_analysis(
            db,
            reference_urls=[
                "https://example.com/article?utm_source=test",
                "https://example.com/article",
                "https://docs.example.com/guide",
            ],
        )
        preparation, status = _create_preparation(db, analysis)
        assert status["citation_manifest"]["source_count"] == 2
        assert status["citation_manifest"]["occurrence_count"] == 3
        assert status["conservation"] == {
            "required_unique_sources": 2,
            "terminal": 0,
            "nonterminal": 2,
            "by_state": {"PENDING": 2},
            "conserved": True,
        }

        with pytest.raises(HTTPException) as pending_error:
            source_preparation.freeze_completion_manifest(
                db,
                preparation_id=preparation.preparation_id,
                created_by="qa",
            )
        assert pending_error.value.detail["code"] == "SOURCE_SCOPE_INCOMPLETE"

        first, second = status["sources"]
        content = (
            "这是人工核对后的完整正文。该页面说明甲工具支持批量生成短链，"
            "并明确给出适用场景、边界条件和原始产品说明，足以形成稳定 passage。"
        )
        snapshot = _submit(db, preparation.preparation_id, first, content)
        assert Path(snapshot.artifact_path).read_text(encoding="utf-8") == content
        assert snapshot.content_hash == hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert json.loads(snapshot.passages_json)

        current = source_preparation.get_source_preparation_status(
            db,
            preparation_id=preparation.preparation_id,
        )
        second_current = next(row for row in current["sources"] if row["source_key"] == second["source_key"])
        source_preparation.waive_source(
            db,
            preparation_id=preparation.preparation_id,
            source_key=second_current["source_key"],
            expected_row_version=second_current["row_version"],
            reason="该来源需要账号访问，当前验收不外发登录态",
            impact="无法用该来源判断其是否支持当前推荐理由",
            waived_by="qa",
        )
        completion = source_preparation.freeze_completion_manifest(
            db,
            preparation_id=preparation.preparation_id,
            created_by="qa",
        )
        assert completion.status == "FROZEN"
        assert completion.ready_source_count == 1
        assert completion.waived_source_count == 1

        validated, snapshots, limitations = source_preparation.validate_completion_for_evidence(
            db,
            analysis_id=analysis.analysis_id,
            context_id=preparation.context_id,
            citation_manifest_id=preparation.citation_manifest_id,
            citation_manifest_hash=preparation.citation_manifest_hash,
            completion_manifest_id=completion.manifest_id,
            completion_manifest_hash=completion.payload_hash,
        )
        assert validated.manifest_id == completion.manifest_id
        assert [row.snapshot_id for row in snapshots] == [snapshot.snapshot_id]
        assert [row["code"] for row in limitations] == ["SOURCE_WAIVED_WITH_LIMITATION"]
        assert db.query(SinglePromptPreparedSourceSnapshot).count() == 1
        with pytest.raises(HTTPException) as cross_context:
            source_preparation.validate_completion_for_evidence(
                db,
                analysis_id=analysis.analysis_id,
                context_id="ctx-from-another-analysis",
                citation_manifest_id=preparation.citation_manifest_id,
                citation_manifest_hash=preparation.citation_manifest_hash,
                completion_manifest_id=completion.manifest_id,
                completion_manifest_hash=completion.payload_hash,
            )
        assert cross_context.value.detail["code"] == "CITATION_MANIFEST_INPUT_MISMATCH"
    finally:
        db.close()
        engine.dispose()


def test_manual_html_source_uses_existing_primary_content_extractor(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    try:
        analysis = _seed_frozen_analysis(db, reference_urls=["https://example.com/guide"])
        preparation, status = _create_preparation(db, analysis)
        source = status["sources"][0]

        blocked_html = (
            "<html><body><main><h1>安全验证</h1><p>请完成验证后继续访问，"
            "当前页面不是来源正文。</p>" * 8 + "</main></body></html>"
        )
        with pytest.raises(HTTPException) as blocked:
            source_preparation.submit_manual_content(
                db,
                preparation_id=preparation.preparation_id,
                source_key=source["source_key"],
                expected_row_version=source["row_version"],
                title="来源页面",
                clean_text="",
                input_format="HTML_SOURCE",
                raw_html=blocked_html,
                coverage_scope="FULL_PAGE",
                submitted_by="qa",
            )
        assert blocked.value.detail["code"] == "HTML_PRIMARY_CONTENT_REJECTED"
        assert db.query(SinglePromptPreparedSourceSnapshot).count() == 0

        article_html = (
            "<html><head><title>产品说明</title></head><body><nav>首页 登录</nav>"
            "<main><article><h1>短链产品完整说明</h1>"
            + "".join(
                f"<p>这是第{index}段正式正文，详细说明短链生成能力、适用场景、使用边界和注意事项，内容来自页面实际源代码。</p>"
                for index in range(1, 12)
            )
            + "</article></main></body></html>"
        )
        snapshot = source_preparation.submit_manual_content(
            db,
            preparation_id=preparation.preparation_id,
            source_key=source["source_key"],
            expected_row_version=source["row_version"],
            title="产品说明",
            clean_text="",
            input_format="HTML_SOURCE",
            raw_html=article_html,
            coverage_scope="FULL_PAGE",
            submitted_by="qa",
        )
        assert snapshot.acquisition_method == "MANUAL_HTML_SOURCE"
        assert "短链产品完整说明" in snapshot.clean_text
        assert "<article>" not in snapshot.clean_text
        assert Path(snapshot.artifact_path).read_text(encoding="utf-8") == snapshot.clean_text
        assert json.loads(snapshot.passages_json)
    finally:
        db.close()
        engine.dispose()


def test_source_preparation_status_read_has_no_business_writes(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    try:
        analysis = _seed_frozen_analysis(db, reference_urls=["https://example.com/only"])
        preparation, first = _create_preparation(db, analysis)
        before = {
            table.__tablename__: db.query(table).count()
            for table in (
                source_preparation.SinglePromptCitationManifest,
                source_preparation.SinglePromptSourcePreparation,
                source_preparation.SinglePromptSourceDisposition,
                source_preparation.SinglePromptPreparedSourceSnapshot,
                source_preparation.SinglePromptSourceCompletionManifest,
            )
        }
        second = source_preparation.get_source_preparation_status(
            db,
            preparation_id=preparation.preparation_id,
        )
        after = {
            table.__tablename__: db.query(table).count()
            for table in (
                source_preparation.SinglePromptCitationManifest,
                source_preparation.SinglePromptSourcePreparation,
                source_preparation.SinglePromptSourceDisposition,
                source_preparation.SinglePromptPreparedSourceSnapshot,
                source_preparation.SinglePromptSourceCompletionManifest,
            )
        }
        assert second == first
        assert after == before
        assert not db.dirty
        assert not db.new
    finally:
        db.close()
        engine.dispose()


def test_blocked_content_and_all_waived_scope_never_become_evidence_ready(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    try:
        analysis = _seed_frozen_analysis(db, reference_urls=["https://example.com/only"])
        preparation, status = _create_preparation(db, analysis)
        source = status["sources"][0]
        with pytest.raises(HTTPException) as blocked:
            _submit(
                db,
                preparation.preparation_id,
                source,
                "安全验证，请完成验证后继续访问。" * 5,
                title="安全验证",
            )
        assert blocked.value.detail["code"] == "CONTENT_BLOCKED"
        assert db.query(SinglePromptPreparedSourceSnapshot).count() == 0

        source_preparation.waive_source(
            db,
            preparation_id=preparation.preparation_id,
            source_key=source["source_key"],
            expected_row_version=source["row_version"],
            reason="来源正文未获授权补录",
            impact="没有任何可用于 Evidence 的正文",
            waived_by="qa",
        )
        completion = source_preparation.freeze_completion_manifest(
            db,
            preparation_id=preparation.preparation_id,
            created_by="qa",
        )
        assert completion.status == "NO_USABLE_SOURCE"
        with pytest.raises(HTTPException) as no_source:
            source_preparation.validate_completion_for_evidence(
                db,
                analysis_id=analysis.analysis_id,
                context_id=preparation.context_id,
                citation_manifest_id=preparation.citation_manifest_id,
                citation_manifest_hash=preparation.citation_manifest_hash,
                completion_manifest_id=completion.manifest_id,
                completion_manifest_hash=completion.payload_hash,
            )
        assert no_source.value.detail["code"] == "NO_USABLE_SOURCE"
    finally:
        db.close()
        engine.dispose()


def test_new_manual_content_creates_new_snapshot_and_manifest_without_mutating_history(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    try:
        analysis = _seed_frozen_analysis(db, reference_urls=["https://example.com/only"])
        preparation, status = _create_preparation(db, analysis)
        source = status["sources"][0]
        first_text = "第一版人工正文，完整说明短链能力及适用边界，不包含任何登录墙或验证页内容。" * 2
        first_snapshot = _submit(db, preparation.preparation_id, source, first_text)
        first_manifest = source_preparation.freeze_completion_manifest(
            db,
            preparation_id=preparation.preparation_id,
            created_by="qa",
        )
        first_payload = first_manifest.payload_json

        status = source_preparation.get_source_preparation_status(db, preparation_id=preparation.preparation_id)
        source = status["sources"][0]
        second_text = "第二版人工正文，修正了页面内容并继续保留能力限定和上下文信息，形成新的不可变快照。" * 2
        second_snapshot = _submit(db, preparation.preparation_id, source, second_text)
        second_manifest = source_preparation.freeze_completion_manifest(
            db,
            preparation_id=preparation.preparation_id,
            created_by="qa",
        )

        db.expire_all()
        old_manifest = db.query(SinglePromptSourceCompletionManifest).filter_by(
            manifest_id=first_manifest.manifest_id
        ).one()
        assert old_manifest.payload_json == first_payload
        assert first_snapshot.snapshot_id != second_snapshot.snapshot_id
        assert first_manifest.manifest_id != second_manifest.manifest_id
        assert first_manifest.version_number == 1
        assert second_manifest.version_number == 2
        assert Path(first_snapshot.artifact_path).read_text(encoding="utf-8") == first_text
        assert Path(second_snapshot.artifact_path).read_text(encoding="utf-8") == second_text
        assert db.query(SinglePromptPreparedSourceSnapshot).count() == 2
    finally:
        db.close()
        engine.dispose()


class _AnswerJudge:
    def judge_answer(self, answer_text, prompt_text, brand_name, db=None):
        return {
            "events": [
                {
                    "entity_text": "甲工具",
                    "entity_type": "PRODUCT",
                    "speech_act": "RECOMMEND",
                    "recommendation_strength": "STRONG",
                    "polarity": "POSITIVE",
                    "answer_span": "甲工具值得推荐，因为支持批量生成短链。",
                    "reasons": [
                        {
                            "normalized_reason": "支持批量生成短链",
                            "reason_scope": "ENTITY_SPECIFIC",
                            "reason_span": "支持批量生成短链",
                        }
                    ],
                }
            ],
            "selection_criteria": [],
            "unresolved_items": [],
        }


class _SourceClaimJudge:
    def judge_passage(self, passage_text, db=None):
        return {
            "claims": [
                {
                    "normalized_claim": "甲工具支持批量生成短链",
                    "subject_text": "甲工具",
                    "predicate": "支持",
                    "object_text": "批量生成短链",
                    "claim_type": "CAPABILITY",
                    "polarity": "POSITIVE",
                    "source_span": "甲工具支持批量生成短链",
                }
            ]
        }


class _AlignmentJudge:
    def judge(self, reason_text, source_claim_text, db=None):
        return {
            "relation": "SUPPORTS",
            "rationale": "固定正文直接陈述了同一主体与能力",
            "confidence_raw": 0.98,
        }


def test_migrated_release_database_consumes_exact_answer_review_and_source_completion(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        analysis = _seed_frozen_analysis(db, reference_urls=["https://example.com/only"])
        preparation, status = _create_preparation(db, analysis)
        source = status["sources"][0]
        snapshot = _submit(
            db,
            preparation.preparation_id,
            source,
            "真实来源正文明确说明甲工具支持批量生成短链，并给出该能力的适用场景和边界条件。" * 2,
        )
        completion = source_preparation.freeze_completion_manifest(
            db,
            preparation_id=preparation.preparation_id,
            created_by="qa",
        )
        status = source_preparation.get_source_preparation_status(db, preparation_id=preparation.preparation_id)
        citation = status["citation_manifest"]

        diagnosis, created = create_answer_diagnosis(
            db,
            analysis_id=analysis.analysis_id,
            project_id=1,
            prompt_id=44,
            citation_manifest_id=citation["manifest_id"],
            citation_manifest_hash=citation["payload_hash"],
            answer_llm_policy="ALLOW_EXTERNAL",
            idempotency_key="answer-diagnosis-0001",
        )
        assert created is True
        token = claim_diagnosis(db, diagnosis.diagnosis_id)
        answer_result = compute_answer_diagnosis(
            db,
            diagnosis,
            token,
            answer_judge=_AnswerJudge(),
        )
        answer_output = json.loads(answer_result.output_json)
        assert answer_output["result_scope"] == "ANSWER_ONLY"
        assert answer_output["source_diagnosis"]["status"] == "SEPARATE_SOURCE_PREPARATION"
        with pytest.raises(HTTPException) as missing_review:
            continue_evidence_diagnosis(
                db,
                analysis_id=analysis.analysis_id,
                diagnosis_id=diagnosis.diagnosis_id,
                project_id=1,
                prompt_id=44,
                answer_result_version=answer_result.result_version,
                answer_result_hash=answer_result.output_hash,
                answer_review_id="review-does-not-exist",
                citation_manifest_id=citation["manifest_id"],
                citation_manifest_hash=citation["payload_hash"],
                completion_manifest_id=completion.manifest_id,
                completion_manifest_hash=completion.payload_hash,
                evidence_llm_policy="CACHE_ONLY",
            )
        assert missing_review.value.detail["code"] == "EXACT_ANSWER_REVIEW_REQUIRED"
        answer_review = complete_diagnosis_review(
            db,
            diagnosis_id=diagnosis.diagnosis_id,
            result_version=answer_result.result_version,
            result_hash=answer_result.output_hash,
            reviewable_set_hash=answer_result.reviewable_set_hash,
            reviewer="qa",
            note="确认本版 Answer 结果",
            decisions=[],
        )

        with pytest.raises(HTTPException) as wrong_version:
            continue_evidence_diagnosis(
                db,
                analysis_id=analysis.analysis_id,
                diagnosis_id=diagnosis.diagnosis_id,
                project_id=1,
                prompt_id=44,
                answer_result_version=answer_result.result_version,
                answer_result_hash=answer_result.output_hash,
                answer_review_id=answer_review.review_id,
                citation_manifest_id=citation["manifest_id"],
                citation_manifest_hash=citation["payload_hash"],
                completion_manifest_id=completion.manifest_id,
                completion_manifest_hash="0" * 64,
                evidence_llm_policy="ALLOW_EXTERNAL",
                source_claim_judge=_SourceClaimJudge(),
                alignment_judge=_AlignmentJudge(),
            )
        assert wrong_version.value.detail["code"] == "SOURCE_COMPLETION_INPUT_MISMATCH"

        queued_result, queued = queue_evidence_continuation(
            db,
            analysis_id=analysis.analysis_id,
            diagnosis_id=diagnosis.diagnosis_id,
            project_id=1,
            prompt_id=44,
            answer_result_version=answer_result.result_version,
            answer_result_hash=answer_result.output_hash,
            answer_review_id=answer_review.review_id,
            citation_manifest_id=citation["manifest_id"],
            citation_manifest_hash=citation["payload_hash"],
            completion_manifest_id=completion.manifest_id,
            completion_manifest_hash=completion.payload_hash,
            evidence_llm_policy="ALLOW_EXTERNAL",
        )
        assert queued_result is None
        assert queued is True
        db.refresh(diagnosis)
        assert diagnosis.status == "EVIDENCE_QUEUED"
        queued_progress = json.loads(diagnosis.progress_json)
        assert queued_progress["request"]["evidence_plan_id"].startswith("evidence-plan-")
        assert len(queued_progress["request"]["evidence_plan_hash"]) == 64

        evidence_result = continue_evidence_diagnosis(
            db,
            analysis_id=analysis.analysis_id,
            diagnosis_id=diagnosis.diagnosis_id,
            project_id=1,
            prompt_id=44,
            answer_result_version=answer_result.result_version,
            answer_result_hash=answer_result.output_hash,
            answer_review_id=answer_review.review_id,
            citation_manifest_id=citation["manifest_id"],
            citation_manifest_hash=citation["payload_hash"],
            completion_manifest_id=completion.manifest_id,
            completion_manifest_hash=completion.payload_hash,
            evidence_llm_policy="ALLOW_EXTERNAL",
            source_claim_judge=_SourceClaimJudge(),
            alignment_judge=_AlignmentJudge(),
        )
        output = json.loads(evidence_result.output_json)
        assert output["result_scope"] == "ANSWER_AND_EVIDENCE"
        assert output["input"]["source_snapshot_ids"] == [snapshot.snapshot_id]
        assert output["input"]["completion_manifest_id"] == completion.manifest_id
        assert output["input"]["answer_review_id"] == answer_review.review_id
        assert output["input"]["evidence_plan_hash"] == output["evidence_diagnosis"]["candidate_plan"]["plan_hash"]
        assert output["source_diagnosis"]["status"] == "SOURCE_COMPLETION_CONSUMED"
        assert output["evidence_diagnosis"]["source_claim_jobs"][0]["status"] == "DONE"
        assert output["evidence_diagnosis"]["source_relations"][0]["alignment_evaluation"] == "EVALUATED"

        repeated = continue_evidence_diagnosis(
            db,
            analysis_id=analysis.analysis_id,
            diagnosis_id=diagnosis.diagnosis_id,
            project_id=1,
            prompt_id=44,
            answer_result_version=answer_result.result_version,
            answer_result_hash=answer_result.output_hash,
            answer_review_id=answer_review.review_id,
            citation_manifest_id=citation["manifest_id"],
            citation_manifest_hash=citation["payload_hash"],
            completion_manifest_id=completion.manifest_id,
            completion_manifest_hash=completion.payload_hash,
            evidence_llm_policy="ALLOW_EXTERNAL",
            source_claim_judge=_SourceClaimJudge(),
            alignment_judge=_AlignmentJudge(),
        )
        assert repeated.result_version == evidence_result.result_version

        api_status = get_diagnosis_status(
            db,
            analysis_id=analysis.analysis_id,
            diagnosis_id=diagnosis.diagnosis_id,
            project_id=1,
            prompt_id=44,
        )
        assert api_status["result"]["result_version"] == evidence_result.result_version
        assert api_status["review"] is None
        assert api_status["source_content_status_summary"]["content_ready"] == 1
        assert not inspect(engine).has_table("single_prompt_source_snapshots")

        snapshot_id = snapshot.snapshot_id
        artifact_path = snapshot.artifact_path
        artifact_hash = snapshot.artifact_hash
        review_id = answer_review.review_id
        result_version = evidence_result.result_version
        db.close()
        engine.dispose()

        restarted_engine = create_engine(
            f"sqlite:///{(tmp_path / 'migrated-release-first-slice.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        restarted_db = sessionmaker(bind=restarted_engine, expire_on_commit=False)()
        persisted_snapshot = restarted_db.query(SinglePromptPreparedSourceSnapshot).filter_by(
            snapshot_id=snapshot_id
        ).one()
        assert persisted_snapshot.artifact_path == artifact_path
        assert hashlib.sha256(Path(artifact_path).read_bytes()).hexdigest() == artifact_hash
        assert restarted_db.query(SinglePromptDiagnosisReview).filter_by(review_id=review_id).one()
        assert restarted_db.query(SinglePromptDiagnosisResult).filter_by(
            result_version=result_version
        ).one().output_hash == evidence_result.output_hash
        restarted_db.close()
        restarted_engine.dispose()
    finally:
        db.close()
        engine.dispose()


def test_sqlite_version_policy_accepts_only_patched_branches():
    assert sqlite_has_wal_reset_fix("3.51.3") is True
    assert sqlite_has_wal_reset_fix("3.52.0") is True
    assert sqlite_has_wal_reset_fix("3.50.7") is True
    assert sqlite_has_wal_reset_fix("3.50.6") is False
    assert sqlite_has_wal_reset_fix("3.44.6") is True
    assert sqlite_has_wal_reset_fix("3.44.5") is False
    assert sqlite_has_wal_reset_fix("not-a-version") is False


def test_citation_contribution_plan_is_deterministic_complete_and_zero_call(monkeypatch, tmp_path):
    db, engine = _session(tmp_path)
    try:
        fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
        execution, created = _create_contribution_fixture_plan(db, fixture)
        assert created is True
        plan = json.loads(execution.plan_json)
        assert execution.status == "AWAITING_EXTERNAL_AUTHORIZATION"
        assert execution.selected_run_id == fixture["run"].id
        assert plan["selection"]["selection_rule"] == "FIRST_TECHNICALLY_ELIGIBLE_RUN_ASC"
        assert plan["selection"]["selection_uses_semantic_outcome"] is False
        assert plan["answer_semantic_char_coverage"]["rate"] == 1.0
        assert len(plan["answer_units"]) == 1
        assert set(plan["answer_units"][0]["semantic_facets"]) == {"BRAND_CAPABILITY", "DECISION_REASON"}
        assert len(plan["citations"]) == 2
        assert {item["processing_status"] for item in plan["citations"]} == {"PENDING", "WAIVED"}
        assert plan["call_plan"]["max_new_external_requests"] == 1
        assert plan["call_plan"]["automatic_retries"] == 0
        assert plan["call_plan"]["structured_output_mode"] == "JSON_SCHEMA"
        assert plan["call_plan"]["canary_external_requests"] == 1
        pending_citation = next(item for item in plan["citations"] if item["processing_status"] == "PENDING")
        assert plan["call_plan"]["canary_citation_ids"] == [pending_citation["citation_id"]]
        assert plan["call_plan"]["canary_token_ceiling"] > 0
        assert plan["call_plan"]["canary_budget_upper_bound_cny"] > 0
        assert len(plan["response_schema_hash"]) == 64
        assert len(plan["system_prompt_hash"]) == 64
        assert plan["call_plan"]["budget_upper_bound_cny"] > 0
        assert db.query(SinglePromptCitationContributionResult).count() == 0

        duplicate, duplicate_created = _create_contribution_fixture_plan(db, fixture)
        assert duplicate_created is False
        assert duplicate.contribution_id == execution.contribution_id
        assert db.query(SinglePromptCitationContributionExecution).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_answer_unit_classifier_keeps_headings_and_operational_choices_out_of_decision_reason():
    answer = "📱 微信/浏览器打开抖音链接\n直接复制唤醒：长按链接选择复制，再打开抖音。\n建议优先使用官方功能。"
    units = build_answer_units(answer, 1, [])
    assert [item["primary_type"] for item in units] == [
        "MARKET_CRITERION",
        "PROCEDURE",
        "DECISION_REASON",
    ]
    assert all(item["classification_status"] == "DETERMINISTIC_REVIEW_REQUIRED" for item in units)


def test_candidate_budget_preserves_disjoint_recall_boundary_controls():
    units = [
        {
            "answer_unit_id": f"au-{index}",
            "raw_text": f"能力{index} 支持场景{index}",
        }
        for index in range(1, 9)
    ]
    passages = [
        {
            "passage_id": f"psg-{index}",
            "text": f"能力{index} 支持场景{index}，并保留必要条件。",
            "content_hash": hashlib.sha256(f"passage-{index}".encode()).hexdigest(),
        }
        for index in range(1, 17)
    ]
    snapshot = SinglePromptPreparedSourceSnapshot(
        snapshot_id="snapshot-recall-controls",
        source_key="source-recall-controls",
        passages_json=json.dumps(passages, ensure_ascii=False),
    )
    selected, controls = _rank_candidate_passages(units, snapshot)
    assert len(selected) == 12
    assert len(controls) == 2
    selected_pairs = {(item["answer_unit_id"], item["passage_id"]) for item in selected}
    control_pairs = {(item["answer_unit_id"], item["passage_id"]) for item in controls}
    assert selected_pairs.isdisjoint(control_pairs)


def test_current_plan_supersedes_only_unexecuted_stale_contract(monkeypatch, tmp_path):
    db, engine = _session(tmp_path)
    try:
        fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
        stale, _ = _create_contribution_fixture_plan(db, fixture)
        stale_plan = json.loads(stale.plan_json)
        stale_plan["plan_version"] = "single_prompt_v2.citation_contribution_plan.p1.v1"
        stale.plan_json = json.dumps(stale_plan, ensure_ascii=False)
        db.commit()

        current, created = _create_contribution_fixture_plan(
            db,
            fixture,
            idempotency_key="citation-contribution-fixture-plan-v2",
        )
        db.refresh(stale)
        assert created is True
        assert stale.status == "SUPERSEDED_BEFORE_AUTHORIZATION"
        assert stale.blocker_code == "CONTRIBUTION_PLAN_CONTRACT_STALE"
        assert current.status == "AWAITING_EXTERNAL_AUTHORIZATION"
    finally:
        db.close()
        engine.dispose()


def test_citation_contribution_strict_candidate_evaluation_gate():
    unit = {
        "answer_unit_id": "au-1",
        "raw_text": "甲工具支持批量生成短链",
        "context_heading": "",
        "primary_type": "DECISION_REASON",
        "semantic_facets": ["BRAND_CAPABILITY", "DECISION_REASON"],
    }
    passage = {"passage_id": "psg-1", "text": "甲工具支持批量生成短链。"}
    pair = {"answer_unit_id": "au-1", "passage_id": "psg-1"}

    class StaticClient:
        def __init__(self, payload):
            self.payload = payload

        def structured_generate_sync(self, **kwargs):
            return kwargs["response_validator"](self.payload)

    valid = {
        "evaluations": [{
            "candidate_pair_index": 0,
            "answer_unit_index": 0,
            "citation_index": 0,
            "passage_index": 0,
            "answer_span": "甲工具支持批量生成短链",
            "source_span": "甲工具支持批量生成短链",
            "correspondence_mode": "DIRECT_REUSE",
            "evidence_relation": "SUPPORTS_FULL",
            "rationale": "原文直接对应",
        }],
        "no_binding_reason": None,
    }
    admitted = CitationContributionJudge(StaticClient(valid)).judge([unit], [passage], [pair])
    assert admitted["evaluations"][0]["answer_unit_id"] == "au-1"
    assert admitted["evaluations"][0]["passage_id"] == "psg-1"
    assert admitted["evaluations"][0]["candidate_pair_index"] == 0

    incomplete = {"evaluations": [], "no_binding_reason": "未发现"}
    with pytest.raises(Exception, match="未覆盖完整冻结候选集合"):
        CitationContributionJudge(StaticClient(incomplete)).judge([unit], [passage], [pair])

    hallucinated_span = json.loads(json.dumps(valid, ensure_ascii=False))
    hallucinated_span["evaluations"][0]["source_span"] = "甲工具永久免费"
    with pytest.raises(Exception, match="无法回指"):
        CitationContributionJudge(StaticClient(hallucinated_span)).judge([unit], [passage], [pair])


def test_citation_contribution_calibration_freezes_unbiased_and_diagnostic_samples():
    units = [
        {
            "answer_unit_id": f"au-{index}",
            "primary_type": "PROCEDURE" if index % 2 else "RULE_CONDITION",
            "semantic_facets": ["BRAND_CAPABILITY"] if index == 0 else [],
            "subject_markers": ["爱短链"] if index == 0 else [],
            "condition_markers": ["如果"] if index == 1 else [],
            "negation_markers": [],
            "comparison_markers": [],
        }
        for index in range(50)
    ]
    evaluations = [
        {
            "evaluation_id": f"evaluation-{index}",
            "answer_unit_id": f"au-{index}",
            "correspondence_mode": "FAITHFUL_PARAPHRASE" if index % 3 == 0 else "NO_CORRESPONDENCE",
            "evidence_relation": "SUPPORTS_PARTIAL" if index % 3 == 0 else "NO_MATCH",
        }
        for index in range(50)
    ]
    controls = [{"control_id": f"control-{index}"} for index in range(4)]

    first, first_meta = _build_calibration_set(
        contribution_id="contribution-fixed",
        plan_hash="a" * 64,
        evaluations=evaluations,
        recall_controls=controls,
        answer_units=units,
    )
    second, second_meta = _build_calibration_set(
        contribution_id="contribution-fixed",
        plan_hash="a" * 64,
        evaluations=list(reversed(evaluations)),
        recall_controls=list(reversed(controls)),
        answer_units=list(reversed(units)),
    )

    assert first == second
    assert first_meta == second_meta
    assert first_meta["unbiased_sample_count"] == 40
    assert first_meta["unbiased_population_count"] == 50
    assert all(item["target_type"] == "EVALUATION" for item in first[:40])
    assert {item["sample_group"] for item in first[:40]} == {"UNBIASED_CHECK"}
    assert any(item["target_type"] == "RECALL_CONTROL" for item in first[40:])
    assert all(item["sample_group"] == "DIAGNOSTIC_SUPPLEMENT" for item in first[40:])
    assert len(first) <= 60


def test_citation_contribution_execution_separates_evaluations_bindings_and_waiver(monkeypatch, tmp_path):
    db, engine = _session(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
        execution, _ = _create_contribution_fixture_plan(db, fixture)
        plan = json.loads(execution.plan_json)
        authorize_citation_contribution(
            db,
            contribution_id=execution.contribution_id,
            project_id=execution.project_id,
            prompt_id=execution.prompt_id,
            plan_hash=execution.plan_hash,
            provider="deepseek",
            model=plan["call_plan"]["model"],
            max_external_requests=plan["call_plan"]["max_new_external_requests"],
            max_total_tokens=plan["call_plan"]["conservative_token_ceiling"],
            max_budget_cny=plan["call_plan"]["budget_upper_bound_cny"],
            cost_upper_bound_cny=plan["call_plan"]["budget_upper_bound_cny"],
            pricing_basis=plan["call_plan"]["pricing_basis"],
            authorized_by="qa",
        )

        class Counters:
            call_count = 0
            external_call_count = 0
            external_token_count = 0

        class FakeJudge:
            def __init__(self):
                self.client = Counters()

            def judge(self, answer_units, passages, candidate_pairs, citation_index=0, db=None):
                self.client.call_count += 1
                self.client.external_call_count += 1
                self.client.external_token_count += 100
                evaluations = []
                for index, pair in enumerate(candidate_pairs):
                    passage = next(item for item in passages if item["passage_id"] == pair["passage_id"])
                    if index == 0:
                        evaluations.append({
                            **pair,
                            "answer_span": answer_units[0]["raw_text"],
                            "source_span": passage["text"],
                            "correspondence_mode": "FAITHFUL_PARAPHRASE",
                            "evidence_relation": "SUPPORTS_FULL",
                            "rationale": "正文支持该内容单元",
                        })
                    else:
                        evaluations.append({
                            **pair,
                            "answer_span": None,
                            "source_span": None,
                            "correspondence_mode": "NO_CORRESPONDENCE",
                            "evidence_relation": "NO_MATCH",
                            "rationale": "候选段落不对应该内容单元",
                        })
                return {"evaluations": evaluations, "no_binding_reason": None}

        contribution_id = execution.contribution_id
        db.close()
        execute_citation_contribution(contribution_id, session_factory=Session, judge=FakeJudge())
        db = Session()
        status = get_citation_contribution_status(
            db,
            analysis_id=fixture["analysis"].analysis_id,
            contribution_id=contribution_id,
            project_id=fixture["analysis"].project_id,
            prompt_id=fixture["analysis"].prompt_id,
        )
        assert status["execution"]["status"] == "READY_FOR_CALIBRATION"
        assert status["execution"]["usage"] == {
            "external_llm_calls": 1,
            "llm_cache_hits": 0,
            "external_token_usage": 100,
        }
        assert status["result"]["stats"]["citation_disposition_coverage"] == 1.0
        dispositions = {item["disposition"] for item in status["result"]["output"]["citations"]}
        assert dispositions == {"BOUND", "SOURCE_WAIVED"}
        assert status["result"]["stats"]["evaluation_count"] >= 1
        assert status["result"]["stats"]["binding_count"] == 1
        binding = status["result"]["output"]["bindings"][0]
        assert binding["answer_anchor"] == "UNPROVEN"
        assert binding["generation_influence"] == "UNAVAILABLE"
        assert all(item["target_type"] == "EVALUATION" for item in status["result"]["output"]["calibration_set"])

        decisions = [
            {
                **item,
                "decision": "ACCEPT",
                "correspondence_mode": None,
                "evidence_relation": None,
                "subject_attribution_error": False,
                "decision_role_error": False,
                "note": "",
            }
            for item in status["result"]["output"]["calibration_set"]
        ]
        review = complete_citation_contribution_review(
            db,
            contribution_id=contribution_id,
            result_version=status["result"]["result_version"],
            project_id=fixture["analysis"].project_id,
            prompt_id=fixture["analysis"].prompt_id,
            result_hash=status["result"]["output_hash"],
            reviewable_set_hash=status["result"]["reviewable_set_hash"],
            reviewer="qa",
            decisions=decisions,
            missed_bindings=[],
            note="P1 calibration",
        )
        metrics = json.loads(review.metrics_json)
        assert metrics["false_positive"] == 0
        assert metrics["false_negative"] == 0
        assert db.query(SinglePromptCitationContributionReview).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_citation_contribution_all_failed_blocks_empty_calibration_review(monkeypatch, tmp_path):
    db, engine = _session(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
        execution, _ = _create_contribution_fixture_plan(db, fixture)
        plan = json.loads(execution.plan_json)
        authorize_citation_contribution(
            db,
            contribution_id=execution.contribution_id,
            project_id=execution.project_id,
            prompt_id=execution.prompt_id,
            plan_hash=execution.plan_hash,
            provider="deepseek",
            model=plan["call_plan"]["model"],
            max_external_requests=plan["call_plan"]["max_new_external_requests"],
            max_total_tokens=plan["call_plan"]["conservative_token_ceiling"],
            max_budget_cny=plan["call_plan"]["budget_upper_bound_cny"],
            cost_upper_bound_cny=plan["call_plan"]["budget_upper_bound_cny"],
            pricing_basis=plan["call_plan"]["pricing_basis"],
            authorized_by="qa",
        )

        class Counters:
            call_count = 0
            external_call_count = 0
            external_token_count = 0

        class FailedJudge:
            def __init__(self):
                self.client = Counters()

            def judge(self, answer_units, passages, candidate_pairs, citation_index=0, db=None):
                self.client.external_call_count += 1
                self.client.external_token_count += 50
                error = RuntimeError("strict schema rejected")
                error.code = "FAILED_SCHEMA"
                raise error

        contribution_id = execution.contribution_id
        db.close()
        execute_citation_contribution(contribution_id, session_factory=Session, judge=FailedJudge())
        db = Session()
        status = get_citation_contribution_status(
            db,
            analysis_id=fixture["analysis"].analysis_id,
            contribution_id=contribution_id,
            project_id=fixture["analysis"].project_id,
            prompt_id=fixture["analysis"].prompt_id,
        )
        assert status["execution"]["status"] == "CALIBRATION_BLOCKED_NO_VALID_EVALUATIONS"
        assert status["result"]["stats"]["citation_dispositions"]["ANALYSIS_FAILED"] == 1
        assert status["result"]["output"]["calibration_set"] == []
        assert status["allowed_operations"] == ["VIEW"]
        with pytest.raises(HTTPException) as rejected:
            complete_citation_contribution_review(
                db,
                contribution_id=contribution_id,
                result_version=status["result"]["result_version"],
                project_id=fixture["analysis"].project_id,
                prompt_id=fixture["analysis"].prompt_id,
                result_hash=status["result"]["output_hash"],
                reviewable_set_hash=status["result"]["reviewable_set_hash"],
                reviewer="qa",
                decisions=[],
                missed_bindings=[],
                note="must not create empty review",
            )
        assert rejected.value.detail["code"] == "NO_CALIBRATION_TARGETS"
        assert db.query(SinglePromptCitationContributionReview).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_citation_contribution_recovery_preserves_exact_plan(monkeypatch, tmp_path):
    db, engine = _session(tmp_path)
    try:
        fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
        execution, _ = _create_contribution_fixture_plan(db, fixture)
        original_plan_hash = execution.plan_hash
        execution.status = "RUNNING"
        execution.active_attempt_token = "interrupted"
        db.commit()
        assert recover_interrupted_citation_contributions(db) == 1
        db.refresh(execution)
        assert execution.status == "QUEUED"
        assert execution.active_attempt_token == ""
        assert execution.plan_hash == original_plan_hash
        assert execution.blocker_code == "RECOVERED_AFTER_PROCESS_RESTART"
    finally:
        db.close()
        engine.dispose()
