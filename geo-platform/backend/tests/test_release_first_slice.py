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
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    BrowserMonitorRun,
    Organization,
    Project,
    Prompt,
    ReferenceSource,
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
from app.modules.single_prompt_v2 import source_preparation
from app.modules.single_prompt_v2.service import (
    claim_analysis,
    create_analysis,
    finalize_analysis,
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
    assert "single_prompt_strategy_executions" not in status["tables"]

    if sqlite_has_wal_reset_fix(status["sqlite_version"]):
        assert validate_release_database(engine)["status"] == "READY"
    else:
        with pytest.raises(RuntimeError, match="RELEASE_SQLITE_VERSION_UNSAFE"):
            validate_release_database(engine)
    engine.dispose()


def test_release_startup_contract_rejects_unmigrated_database(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'unmigrated.db').as_posix()}")
    with pytest.raises(RuntimeError, match="RELEASE_SCHEMA_REVISION_MISMATCH:UNMIGRATED"):
        validate_release_database(engine)
    engine.dispose()


def test_release_routes_exclude_legacy_and_later_workflows():
    app = create_release_app(validate_on_startup=False)
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/v2/single-prompt/analyses" in paths
    assert any("source-preparation" in path for path in paths)
    assert any("evidence-continuations" in path for path in paths)
    assert not any("strategy" in path for path in paths)
    assert not any("execution-proposal" in path for path in paths)
    assert not any("retest" in path for path in paths)
    assert not any(path.startswith("/api/optimization") for path in paths)

    response = TestClient(app).get("/api/optimization/workflow/1/prompt-overview")
    assert response.status_code == 404
    assert response.json() == {"detail": "Release API route not found"}


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
