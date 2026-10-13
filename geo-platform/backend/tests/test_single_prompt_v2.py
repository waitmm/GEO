from __future__ import annotations

import json
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    BrowserMonitorRun,
    BrowserMonitorTask,
    Project,
    Prompt,
    ReferenceSource,
    RetrievalCandidate,
    RunArtifact,
    SinglePromptAnalysis,
    SinglePromptAnalysisContext,
)
from app.modules.single_prompt_v2.service import (
    claim_analysis,
    create_analysis,
    finalize_analysis,
    get_analysis_status,
    project_platform_reported_search,
    recover_interrupted_analyses,
    retry_analysis,
)
from app.modules.single_prompt_v2.schemas import SinglePromptAnalysisStatusRead
from app.modules.monitoring.collectors.wenxin.search_process import (
    final_answer_boundary,
    project_platform_search_observation,
)


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'single-prompt-v2.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


def _seed(db):
    db.add(Project(id=1, organization_id=1, name="V2", brand_name="Target"))
    db.add_all([
        Prompt(id=11, project_id=1, title="Prompt A", prompt_text="哪个工具支持短链？"),
        Prompt(id=12, project_id=1, title="Prompt B", prompt_text="另一个问题"),
    ])
    db.commit()


def _create(db, prompt_id=11, count=2, key="request-key-0001"):
    return create_analysis(
        db,
        project_id=1,
        prompt_id=prompt_id,
        sample_count=count,
        idempotency_key=key,
    )[0]


def _runs(db, analysis):
    return (
        db.query(BrowserMonitorRun)
        .filter(BrowserMonitorRun.task_id == analysis.task_id)
        .order_by(BrowserMonitorRun.run_sequence)
        .all()
    )


def _succeed(run, answer="有效回答正文，包含足够长度用于真实采样结果验证。"):
    run.status = "success"
    run.stage = "success"
    run.answer_text = answer
    run.answer_char_count = len(answer)
    run.reference_complete = True


def test_create_is_idempotent_and_plan_is_fixed(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _seed(db)
        first, created = create_analysis(db, project_id=1, prompt_id=11, sample_count=2, idempotency_key="same-request-key")
        second, created_again = create_analysis(db, project_id=1, prompt_id=11, sample_count=2, idempotency_key="same-request-key")

        assert created is True
        assert created_again is False
        assert first.analysis_id == second.analysis_id
        assert db.query(SinglePromptAnalysis).count() == 1
        assert db.query(BrowserMonitorTask).count() == 1
        assert len(_runs(db, first)) == 2
        assert get_analysis_status(db, first.analysis_id)["context_id"] is None
    finally:
        db.close()
        engine.dispose()


def test_success_and_failure_freeze_exact_raw_outputs(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _seed(db)
        analysis = _create(db)
        token = claim_analysis(db, analysis.analysis_id)
        first, second = _runs(db, analysis)
        _succeed(first)
        second.status = "failed"
        second.stage = "failed"
        second.error_type = "network_error"
        second.error_message = "network unavailable"
        db.add(ReferenceSource(run_id=first.id, reference_index=1, display_title="Source", url="https://example.com/a"))
        db.add(RetrievalCandidate(run_id=first.id, rank=1, title="Candidate", url="https://example.com/b"))
        db.commit()

        assert finalize_analysis(db, analysis.analysis_id, token) is True
        status = get_analysis_status(db, analysis.analysis_id)

        assert status["sampling"]["status"] == "READY_WITH_FAILURES"
        assert status["sampling"]["valid_run_count"] == 1
        assert status["sampling"]["failed_run_count"] == 1
        assert status["context_id"]
        assert status["result_version"].startswith("raw-v1:")
        assert status["result_source"] == "FROZEN_ANALYSIS_CONTEXT"
        assert status["runs"][0]["references"][0]["title"] == "Source"
        assert status["runs"][0]["retrieval_candidates"][0]["title"] == "Candidate"
        assert status["failures"][0]["error"]["type"] == "network_error"
        assert [warning["code"] for warning in status["warnings"]] == ["INDEPENDENT_SESSION_PROOF_UNAVAILABLE"]
        SinglePromptAnalysisStatusRead.model_validate(status)
    finally:
        db.close()
        engine.dispose()


def test_zero_valid_runs_fail_without_context(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _seed(db)
        analysis = _create(db)
        token = claim_analysis(db, analysis.analysis_id)
        runs = _runs(db, analysis)
        runs[0].status = "success"
        runs[0].stage = "success"
        runs[0].answer_text = ""
        for run in runs[1:]:
            run.status = "failed"
            run.stage = "failed"
            run.error_type = "network_error"
        db.commit()

        assert finalize_analysis(db, analysis.analysis_id, token) is False
        status = get_analysis_status(db, analysis.analysis_id)
        assert status["sampling"]["status"] == "FAILED"
        assert status["sampling"]["valid_run_count"] == 0
        assert status["context_id"] is None
        assert status["blocker"]["code"] == "NO_VALID_RUNS"
        assert "RETRY_COLLECTION" in status["allowed_operations"]
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize('baseline_count,new_count', [(1, 1), (9, 3)])
def test_frozen_context_ignores_later_run_mutation_and_new_sampling(tmp_path, baseline_count, new_count):
    db, engine = _session(tmp_path)
    try:
        _seed(db)
        analysis = _create(db, count=baseline_count)
        token = claim_analysis(db, analysis.analysis_id)
        baseline_runs = _runs(db, analysis)
        for run in baseline_runs:
            _succeed(run, "冻结时的有效回答正文，不应被后续采样覆盖。")
        run = baseline_runs[0]
        db.add(ReferenceSource(run_id=run.id, reference_index=1, display_title="Only reference", url="https://example.com/reference-only"))
        db.commit()
        assert finalize_analysis(db, analysis.analysis_id, token)
        frozen = get_analysis_status(db, analysis.analysis_id)
        assert "RETRIEVAL_OBSERVATION_UNAVAILABLE" in {warning["code"] for warning in frozen["warnings"]}

        run.answer_text = "后来被旧采集路径修改的回答"
        other_task = BrowserMonitorTask(project_id=1, question_ids_json="[11]", run_count=new_count)
        db.add(other_task)
        db.flush()
        for _ in range(new_count):
            db.add(BrowserMonitorRun(task_id=other_task.id, project_id=1, prompt_id=11, status="success", answer_text="新增采样"))
        db.commit()

        after = get_analysis_status(db, analysis.analysis_id)
        assert after["result_version"] == frozen["result_version"]
        assert len(after["runs"]) == baseline_count
        assert after["runs"] == frozen["runs"]
        assert after["context_id"] == frozen["context_id"]
        assert db.query(BrowserMonitorRun).filter_by(task_id=other_task.id).count() == new_count
        assert after["runs"][0]["answer_text"] == "冻结时的有效回答正文，不应被后续采样覆盖。"
    finally:
        db.close()
        engine.dispose()


def test_legacy_mixed_answer_projects_search_terms_but_keeps_boundary_limitation(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _seed(db)
        analysis = _create(db, count=1)
        token = claim_analysis(db, analysis.analysis_id)
        run = _runs(db, analysis)[0]
        _succeed(
            run,
            "\n".join([
                "搜索3个关键词 共参考28篇资料",
                "搜索关键词“抖音跳转链接”、“抖音跳转链接生成方法”、“抖音跳转链接使用规则”",
                "搜索全网28篇资料",
                "这里是文心合并生成的一条最终回答。",
            ]),
        )
        db.add(ReferenceSource(run_id=run.id, reference_index=1, display_title="引用资料", url="https://example.com/source"))
        db.commit()

        assert finalize_analysis(db, analysis.analysis_id, token)
        context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis.analysis_id).one()
        assert json.loads(context.raw_output_json)["runs"][0]["platform_reported_search"] is None

        status = get_analysis_status(db, analysis.analysis_id)
        projection = status["runs"][0]["platform_reported_search"]
        assert projection["terms"] == ["抖音跳转链接", "抖音跳转链接生成方法", "抖音跳转链接使用规则"]
        assert projection["source"] == "LEGACY_MIXED_ANSWER_TEXT_PROJECTION"
        assert projection["consumption_policy"] == "OBSERVATION_ONLY"
        assert status["runs"][0]["answer_content_boundary"]["status"] == "LEGACY_MIXED_CONTAINER"
        assert status["runs"][0]["retrieval_candidates"] == []
        assert {warning["code"] for warning in status["warnings"]} == {
            "INDEPENDENT_SESSION_PROOF_UNAVAILABLE",
            "RETRIEVAL_OBSERVATION_UNAVAILABLE",
        }
    finally:
        db.close()
        engine.dispose()


def test_new_run_freezes_search_observation_separately_from_final_answer(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _seed(db)
        analysis = _create(db, count=1)
        token = claim_analysis(db, analysis.analysis_id)
        run = _runs(db, analysis)[0]
        final_answer = "这是单独保存的最终回答正文，不包含搜索过程和引用资料标题。"
        _succeed(run, final_answer)
        artifact_path = tmp_path / "semantic-regions.json"
        artifact_path.write_text(
            json.dumps(
                {
                    "platform_reported_search": project_platform_search_observation(
                        "搜索3个关键词 共参考28篇资料\n搜索关键词“抖音跳转链接”、“生成方法”、“使用规则”"
                    ),
                    "answer_content_boundary": final_answer_boundary(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        db.add(
            RunArtifact(
                run_id=run.id,
                artifact_type="wenxin_semantic_regions",
                storage_path=str(artifact_path),
                mime_type="application/json",
                size_bytes=artifact_path.stat().st_size,
            )
        )
        db.commit()

        assert finalize_analysis(db, analysis.analysis_id, token)
        status = get_analysis_status(db, analysis.analysis_id)
        frozen_run = status["runs"][0]

        assert frozen_run["answer_text"] == final_answer
        assert "搜索关键词" not in frozen_run["answer_text"]
        assert frozen_run["answer_content_boundary"]["status"] == "FINAL_ANSWER_ONLY"
        assert frozen_run["platform_reported_search"]["terms"] == ["抖音跳转链接", "生成方法", "使用规则"]
        assert frozen_run["platform_reported_search"]["consumption_policy"] == "OBSERVATION_ONLY"
        assert frozen_run["retrieval_candidates"] == []
    finally:
        db.close()
        engine.dispose()


def test_platform_reported_search_does_not_parse_unscoped_quoted_text():
    projection = project_platform_reported_search('回答正文说“关键词甲”和“关键词乙”，但没有平台搜索头。')
    assert projection["status"] == "NOT_REPORTED"
    assert projection["terms"] == []
    assert projection["verification_status"] == "UNVERIFIED_RETRIEVAL_TRACE"


def test_prompt_and_task_scopes_do_not_cross(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _seed(db)
        analysis_a = _create(db, prompt_id=11, count=1, key="request-key-a")
        analysis_b = _create(db, prompt_id=12, count=1, key="request-key-b")
        token_a = claim_analysis(db, analysis_a.analysis_id)
        token_b = claim_analysis(db, analysis_b.analysis_id)
        _succeed(_runs(db, analysis_a)[0], "Prompt A 的独立有效回答正文。")
        _succeed(_runs(db, analysis_b)[0], "Prompt B 的独立有效回答正文。")
        db.commit()
        finalize_analysis(db, analysis_a.analysis_id, token_a)
        finalize_analysis(db, analysis_b.analysis_id, token_b)

        status_a = get_analysis_status(db, analysis_a.analysis_id)
        status_b = get_analysis_status(db, analysis_b.analysis_id)
        assert status_a["analysis"]["prompt_id"] == 11
        assert status_b["analysis"]["prompt_id"] == 12
        assert status_a["runs"][0]["answer_text"].startswith("Prompt A")
        assert status_b["runs"][0]["answer_text"].startswith("Prompt B")
    finally:
        db.close()
        engine.dispose()


def test_restart_is_explicit_and_retry_reuses_same_identity(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _seed(db)
        analysis = _create(db, count=1)
        token = claim_analysis(db, analysis.analysis_id)
        assert token
        run = _runs(db, analysis)[0]
        run.status = "running"
        run.stage = "waiting_answer"
        db.commit()

        assert recover_interrupted_analyses(db) == 1
        interrupted = get_analysis_status(db, analysis.analysis_id)
        assert interrupted["sampling"]["status"] == "INTERRUPTED"
        assert interrupted["runs"][0]["error"]["type"] == "service_restart_uncertain"

        retried = retry_analysis(db, analysis.analysis_id)
        assert retried.analysis_id == analysis.analysis_id
        assert retried.task_id == analysis.task_id
        assert retried.status == "QUEUED"
        assert _runs(db, analysis)[0].retry_count == 1
    finally:
        db.close()
        engine.dispose()


def test_only_one_worker_can_claim_analysis(tmp_path):
    db, engine = _session(tmp_path)
    try:
        _seed(db)
        analysis = _create(db, count=1)
        assert claim_analysis(db, analysis.analysis_id)
        assert claim_analysis(db, analysis.analysis_id) is None
        assert db.query(SinglePromptAnalysisContext).count() == 0
    finally:
        db.close()
        engine.dispose()
