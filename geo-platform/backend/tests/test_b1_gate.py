from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    BrowserMonitorRun,
    BrowserMonitorTask,
    OptimizationAction,
    OptimizationExperiment,
    OptimizationIssue,
    OptimizationIssueRun,
    OptimizationStrategyCandidate,
    PageSnapshot,
    Project,
    Prompt,
    ReferenceSource,
    RetrievalCandidate,
)
from app.modules.optimization import service
from app.modules.optimization.schemas import (
    ActionReleasePayload,
    EvidencePackageCreate,
    OptimizationHypothesisCreate,
    ReleaseConfirmationPayload,
)
from app.services.serialization import dumps


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _project_prompt_runs(db):
    project = Project(id=1, organization_id=1, name="Smoke", brand_name="SmokeBrand", website_url="http://localhost/brand")
    prompt = Prompt(id=1, project_id=1, prompt_text="抖音跳转链接", title="抖音跳转链接")
    task = BrowserMonitorTask(id=1, project_id=1, question_ids_json="[1]", status="completed")
    runs = [
        BrowserMonitorRun(id=1, task_id=1, project_id=1, prompt_id=1, status="success", original_query=prompt.prompt_text),
        BrowserMonitorRun(id=2, task_id=1, project_id=1, prompt_id=1, status="success", original_query=prompt.prompt_text),
    ]
    db.add_all([project, prompt, task, *runs])
    db.commit()
    return project, prompt, runs


def test_platform_matrix_uses_run_level_sets_not_occurrences(db):
    project, _, _ = _project_prompt_runs(db)
    retrievals = [
        RetrievalCandidate(id=1, run_id=1, title="教程 A", url="http://localhost/a", domain="localhost"),
        RetrievalCandidate(id=2, run_id=1, title="教程 A duplicate", url="http://localhost/a?utm_source=x", domain="localhost"),
        RetrievalCandidate(id=3, run_id=2, title="教程 B", url="http://localhost/b", domain="localhost"),
    ]
    refs = [ReferenceSource(id=1, run_id=2, display_title="教程 B", url="http://localhost/b", domain="localhost")]

    row = service._platform_gap_matrix(project, refs, retrievals)[0]

    assert row["candidate_occurrence_count"] == 3
    assert row["candidate_run_count"] == 2
    assert row["citation_run_count"] == 1
    assert row["retrieved_not_cited_run_ids"] == [1]
    assert row["platform_citation_conversion_rate"] == 0.5


def test_candidate_not_cited_uses_set_difference(db):
    retrievals = [
        RetrievalCandidate(id=1, run_id=1, title="A", url="http://localhost/a", domain="localhost"),
        RetrievalCandidate(id=2, run_id=1, title="A dup", url="http://localhost/a?utm_source=x", domain="localhost"),
        RetrievalCandidate(id=3, run_id=2, title="B", url="http://localhost/b", domain="localhost"),
    ]
    refs = [ReferenceSource(id=1, run_id=2, display_title="B", url="http://localhost/b", domain="localhost")]

    summary = service._candidate_not_cited_summary(refs, retrievals)

    assert summary["retrieved_not_cited_run_count"] == 1
    assert summary["retrieved_not_cited_occurrence_count"] == 2
    assert summary["representative_run_ids"] == [1]


def test_retrieval_coverage_marks_candidate_denominator_incomplete(db):
    runs = [
        BrowserMonitorRun(id=1, status="success", parsed_reference_count=30, ui_declared_count=30),
        BrowserMonitorRun(id=2, status="success", parsed_reference_count=30, ui_declared_count=30),
    ]
    retrievals = [
        *[RetrievalCandidate(id=100 + index, run_id=1, title=f"C{index}") for index in range(20)],
        *[RetrievalCandidate(id=200 + index, run_id=2, title=f"C{index}") for index in range(20)],
    ]
    references = [
        *[ReferenceSource(id=300 + index, run_id=1, display_title=f"R{index}") for index in range(30)],
        *[ReferenceSource(id=400 + index, run_id=2, display_title=f"R{index}") for index in range(30)],
    ]

    summary = service._retrieval_coverage_summary(runs, references, retrievals)

    assert summary["coverage_status"] == "INCOMPLETE"
    assert summary["incomplete_run_ids"] == [1, 2]
    assert summary["total_retrieval_candidate_count"] == 40
    assert summary["total_reference_count"] == 60
    assert summary["common_candidate_count_per_run"] == 20
    assert summary["suspected_fixed_collection_limit"] is True


def test_metric_eligibility_keeps_citation_but_blocks_retrieval(db):
    runs = [
        BrowserMonitorRun(id=1, status="success", answer_text="答案", parsed_reference_count=30, ui_declared_count=30, reference_complete=True),
        BrowserMonitorRun(id=2, status="success", answer_text="答案", parsed_reference_count=30, ui_declared_count=30, reference_complete=True),
    ]
    retrievals = [RetrievalCandidate(id=100 + index, run_id=1, title=f"C{index}") for index in range(20)]
    references = [ReferenceSource(id=200 + index, run_id=1, display_title=f"R{index}") for index in range(30)]

    eligibility = service._run_metric_eligibility(runs, references, retrievals)

    assert eligibility["answer_eligible_run_ids"] == [1, 2]
    assert eligibility["citation_eligible_run_ids"] == [1, 2]
    assert eligibility["retrieval_eligible_run_ids"] == []
    assert eligibility["exclusion_reasons"]["retrieval"][0]["reason"] == "INSUFFICIENT_RETRIEVAL_CANDIDATES"


def test_content_type_allows_uncategorized_and_rule_trace():
    empty = service._classify_content_type("", "", "", "")
    tutorial = service._classify_content_type("抖音跳转链接设置教程", "http://localhost/guide", "", "localhost")

    assert empty["content_type"] == "UNCATEGORIZED"
    assert tutorial["content_type"] == "TUTORIAL"
    assert tutorial["classification_method"] == "RULE_HEURISTIC_V1"
    assert tutorial["matched_rules"]


def test_time_unknown_does_not_invent_publish_date_from_title_year():
    info = service._source_time_info(
        {"title": "2026 抖音跳转链接教程", "published_date": "2026", "time_signal_detail": "可见年份信号：2026"},
        datetime(2026, 8, 6),
    )

    assert info["published_at"] == ""
    assert info["time_source"] == "UNKNOWN"
    assert info["freshness_bucket"] == "UNKNOWN"
    assert info["has_year_in_title"] is True


def test_evidence_package_idempotent_and_version_change_creates_new_package(db, monkeypatch):
    _project_prompt_runs(db)
    db.add(RetrievalCandidate(id=1, run_id=1, title="本地教程", url="http://localhost/brand/card", domain="localhost"))
    db.commit()
    payload = EvidencePackageCreate(prompt_id=1, run_ids=[1, 2], target_page_urls=["http://localhost/brand/card"])

    first = service.create_evidence_package(db, 1, payload)
    second = service.create_evidence_package(db, 1, payload)
    monkeypatch.setattr(service, "CONTENT_CLASSIFIER_VERSION", "content_classifier.test")
    third = service.create_evidence_package(db, 1, payload)

    assert second.id == first.id
    assert third.id != first.id
    assert third.version == first.version + 1
    assert first.status == "active"


def test_snapshot_failure_is_not_valid_snapshot(db):
    _project_prompt_runs(db)
    snapshot = service.capture_page_snapshot(
        db,
        1,
        type("Payload", (), {"url": "http://localhost/not-running", "snapshot_type": "PRE_RELEASE", "experiment_id": None})(),
    )

    assert snapshot.capture_status == "failed"
    assert not snapshot.raw_html


def test_hypothesis_acceptance_does_not_start_experiment_or_release(db):
    project, prompt, runs = _project_prompt_runs(db)
    issue = OptimizationIssue(id=1, project_id=project.id, prompt_id=prompt.id, issue_type="target_page_not_retrieved", status="in_action")
    action = OptimizationAction(id=1, issue_id=1, status="READY_FOR_MANUAL_RELEASE", target_url="http://localhost/brand/card")
    experiment = OptimizationExperiment(id=1, action_id=1, status="READY_FOR_MANUAL_RELEASE")
    db.add_all([issue, OptimizationIssueRun(issue_id=1, run_id=runs[0].id), action, experiment])
    db.commit()
    package = service.create_evidence_package(db, project.id, EvidencePackageCreate(prompt_id=prompt.id, run_ids=[run.id for run in runs], target_page_urls=[action.target_url]))

    hypothesis = service.create_hypothesis(
        db,
        experiment.id,
        OptimizationHypothesisCreate(
            evidence_package_id=package.id,
            observed_problem="0/2",
            hypothesized_cause="可能原因",
            core_mechanism="机制",
            baseline_value="0/2",
        ),
    )
    db.refresh(experiment)
    db.refresh(action)

    assert hypothesis.status == "ACCEPTED"
    assert experiment.status == "READY_FOR_MANUAL_RELEASE"
    assert experiment.released_at is None
    assert action.released_at is None
    assert project.status == "active"


def test_evidence_validator_rejects_unavailable_retrieval_metric(db):
    project, prompt, runs = _project_prompt_runs(db)
    for run in runs:
        run.answer_text = "答案"
        run.reference_complete = True
        run.parsed_reference_count = 30
    db.add_all([ReferenceSource(run_id=runs[0].id, display_title="知乎引用", url="https://www.zhihu.com/question/1", domain="zhihu.com")])
    db.commit()
    package = service.create_evidence_package(db, project.id, EvidencePackageCreate(prompt_id=prompt.id, run_ids=[run.id for run in runs], target_page_urls=["http://localhost/brand/card"]))
    payload = {
        "target_url": "http://localhost/brand/card",
        "target_metric": "target_page_retrieval_rate",
        "evidence_run_ids": [runs[0].id],
        "observed_problem": "问题",
    }

    result = service.validate_strategy_evidence(package, None, payload)

    assert result["status"] == "VALIDATION_FAILED"
    assert any("不可使用" in error or "检索候选不足" in error for error in result["errors"])


def test_hypothesis_validator_rejects_generic_empty_seo():
    result = service.validate_strategy_hypothesis(
        {
            "observed_problem": "引用不足",
            "hypothesized_cause": "内容不好",
            "core_mechanism": "优化",
            "target_object": "page",
            "target_url": "http://localhost/brand",
            "recommended_intervention": "优化SEO",
            "target_metric": "official_reference_rate",
            "validation_plan": {},
            "invalidating_result": "无变化",
            "changed_features": [],
            "controlled_variables": [],
        },
        {"warnings": []},
    )

    assert result["status"] == "VALIDATION_FAILED"
    assert result["errors"]


def test_review_before_acceptance_does_not_convert_or_overwrite_original_payload(db):
    project, prompt, runs = _project_prompt_runs(db)
    for run in runs:
        run.answer_text = "答案"
        run.reference_complete = True
    issue = OptimizationIssue(id=1, project_id=project.id, prompt_id=prompt.id, issue_type="target_page_not_retrieved", status="in_action")
    action = OptimizationAction(id=1, issue_id=1, status="READY_FOR_MANUAL_RELEASE", target_url="http://localhost/brand/card")
    experiment = OptimizationExperiment(id=1, action_id=1, status="READY_FOR_MANUAL_RELEASE", release_blocked=True, release_blocked_reason="WAITING_FOR_RECOLLECTED_RETRIEVAL_BASELINE")
    db.add_all([issue, action, experiment])
    db.commit()
    package = service.create_evidence_package(db, project.id, EvidencePackageCreate(prompt_id=prompt.id, run_ids=[run.id for run in runs], target_page_urls=[action.target_url]))
    candidate = OptimizationStrategyCandidate(
        project_id=project.id,
        experiment_id=experiment.id,
        evidence_package_id=package.id,
        target_url=action.target_url,
        provider="local_rule",
        model="local-rule-v1",
        prompt_version="test",
        original_llm_payload_json=dumps({"observed_problem": "original"}),
        structured_payload_json=dumps({
            "observed_problem": "original",
            "hypothesized_cause": "可能是因为测试",
            "core_mechanism": "test mechanism",
            "target_object": "owned_page",
            "target_url": "http://localhost/brand/card",
            "recommended_intervention": "test intervention",
            "target_metric": "brand_mention_rate",
            "validation_plan": {"test": True},
            "invalidating_result": "test invalidating",
            "changed_features": [{"feature": "FAQ"}],
            "controlled_variables": ["URL"],
        }),
        evidence_validation_status="VALIDATED",
        hypothesis_validation_status="VALIDATED",
        review_status="PENDING_REVIEW",
    )
    db.add(candidate)
    db.commit()

    with pytest.raises(Exception):
        service.strategy_to_experiment_plan(db, candidate.id)
    reviewed = service.review_strategy_candidate(
        db,
        candidate.id,
        type("Payload", (), {"review_status": "ACCEPTED_WITH_EDITS", "reviewed_by": "human", "review_note": "", "human_edited_payload": {"observed_problem": "edited"}})(),
    )

    assert reviewed["original_llm_payload"]["observed_problem"] == "original"
    assert reviewed["human_edited_payload"]["observed_problem"] == "edited"


def test_release_confirmation_requires_post_snapshot_and_keeps_released_at_empty(db):
    project, prompt, runs = _project_prompt_runs(db)
    issue = OptimizationIssue(id=1, project_id=project.id, prompt_id=prompt.id, issue_type="target_page_not_retrieved", status="in_action")
    action = OptimizationAction(id=1, issue_id=1, status="READY_FOR_MANUAL_RELEASE", target_url="http://localhost/brand/card")
    experiment = OptimizationExperiment(id=1, action_id=1, status="READY_FOR_MANUAL_RELEASE")
    db.add_all([issue, OptimizationIssueRun(issue_id=1, run_id=runs[0].id), action, experiment])
    db.commit()
    package = service.create_evidence_package(db, project.id, EvidencePackageCreate(prompt_id=prompt.id, run_ids=[run.id for run in runs], target_page_urls=[action.target_url]))
    hypothesis = service.create_hypothesis(
        db,
        experiment.id,
        OptimizationHypothesisCreate(evidence_package_id=package.id, observed_problem="0/2", hypothesized_cause="可能原因", core_mechanism="机制"),
    )

    with pytest.raises(Exception):
        service.release_action(db, action.id, ActionReleasePayload(release_note="bad", release_confirmed=True))
    with pytest.raises(Exception):
        service.confirm_experiment_release(
            db,
            experiment.id,
            ReleaseConfirmationPayload(
                hypothesis_id=hypothesis.id,
                pre_release_snapshot_id=1,
                post_release_snapshot_id=2,
                release_note="bad",
                confirmed_by="smoke",
            ),
        )
    db.refresh(experiment)
    db.refresh(action)

    assert experiment.released_at is None
    assert action.released_at is None
    assert project.status == "active"
