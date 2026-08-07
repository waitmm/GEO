from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SMOKE_DB_PATH = Path(__file__).resolve().parents[1] / "geo_platform_smoke_test.db"
SMOKE_DATABASE_URL = os.environ.get("GEO_DATABASE_URL") or f"sqlite:///{SMOKE_DB_PATH.as_posix()}"
if "geo_v0.db" in SMOKE_DATABASE_URL or SMOKE_DATABASE_URL.endswith("/geo_platform.db"):
    raise SystemExit(f"Refusing to run optimization smoke against main database: {SMOKE_DATABASE_URL}")
os.environ["DATABASE_URL"] = SMOKE_DATABASE_URL

from app.core.database import SessionLocal, init_db
from app.models import BrowserMonitorRun, BrowserMonitorTask, OptimizationStrategyCandidate, PageSnapshot, Project, Prompt, ReferenceSource, RetrievalCandidate, SourceMetadataCache
from app.modules.optimization.schemas import (
    ActionReleasePayload,
    ExperimentConclusionPayload,
    ExperimentRetestCreate,
    ExperimentRunsPayload,
    OptimizationActionCreate,
    OptimizationExperimentCreate,
    ReleaseConfirmationPayload,
)
from app.modules.optimization.service import (
    action_to_read,
    attach_validation_runs,
    confirm_conclusion,
    confirm_experiment_release,
    confirm_issue,
    create_action,
    create_experiment,
    create_hypothesis,
    experiment_to_read,
    evidence_chain,
    generate_candidate_issues,
    lock_baseline,
    queue_retest_task,
    release_action,
    start_validation,
)
from app.modules.optimization.schemas import OptimizationHypothesisCreate
from app.services.serialization import dumps


def main() -> None:
    print(f"optimization_loop_smoke database: {SMOKE_DATABASE_URL}")
    init_db()
    db = SessionLocal()
    try:
        project = Project(
            organization_id=1,
            name=f"P0 Optimization Smoke {datetime.now(UTC).isoformat()}",
            brand_name="SmokeBrand",
            brand_aliases_json='["Smoke Brand"]',
            website_url="http://localhost/smokebrand",
            industry="GEO",
        )
        db.add(project)
        db.flush()
        prompt = Prompt(
            project_id=project.id,
            title="best geo audit tool",
            prompt_text="Which GEO audit tool should a company choose?",
            prompt_group="Smoke",
            intent_type="supplier_recommendation",
        )
        db.add(prompt)
        db.flush()
        task = BrowserMonitorTask(project_id=project.id, question_ids_json=f"[{prompt.id}]", run_count=1, status="completed")
        db.add(task)
        db.flush()
        baseline = BrowserMonitorRun(
            task_id=task.id,
            project_id=project.id,
            prompt_id=prompt.id,
            run_sequence=1,
            sample_index=1,
            status="success",
            original_query=prompt.prompt_text,
            answer_text="SmokeBrand is mentioned, but other tools are the recommended choices.",
            brand_mentioned=True,
            brand_mention_count=1,
            brand_recommendation_level=1,
            reference_complete=True,
            parsed_reference_count=4,
            resolved_url_count=4,
        )
        validation = BrowserMonitorRun(
            task_id=task.id,
            project_id=project.id,
            prompt_id=prompt.id,
            run_sequence=2,
            sample_index=1,
            status="success",
            original_query=prompt.prompt_text,
            answer_text="SmokeBrand is explicitly recommended for companies that need GEO audit evidence.",
            brand_mentioned=True,
            brand_mention_count=1,
            brand_recommendation_level=2,
            reference_complete=True,
            parsed_reference_count=2,
            resolved_url_count=2,
        )
        db.add_all([baseline, validation])
        db.flush()
        db.add(ReferenceSource(run_id=baseline.id, reference_index=1, display_title="Third-party list", domain="localhost", url="http://localhost/third-party/list"))
        db.add(ReferenceSource(run_id=validation.id, reference_index=1, display_title="SmokeBrand guide", domain="localhost", url="http://localhost/smokebrand/guide", is_official_domain=True))
        db.add(ReferenceSource(run_id=validation.id, reference_index=2, display_title="公众号视频教程 2026-08-01", domain="bilibili.com", url="https://www.bilibili.com/video/BV1Smoke"))
        db.add(ReferenceSource(run_id=validation.id, reference_index=3, display_title="公众号视频教程 2026-08-01", domain="bilibili.com", url="https://www.bilibili.com/video/BV1Smoke?utm_source=share"))
        db.add(SourceMetadataCache(url="bilibili.com/video/bv1smoke", domain="bilibili.com", title="公众号视频教程 2026-08-01", author_name="Smoke UP", published_date="2026-08-01", status="success", fetched_at=datetime.now(UTC).replace(tzinfo=None)))
        db.add(RetrievalCandidate(run_id=baseline.id, rank=1, title="SmokeBrand guide", domain="localhost", url="http://localhost/smokebrand/guide"))
        db.add(RetrievalCandidate(run_id=validation.id, rank=1, title="SmokeBrand guide", domain="localhost", url="http://localhost/smokebrand/guide?utm_source=share"))
        for rank in range(2, 31):
            db.add(RetrievalCandidate(run_id=baseline.id, rank=rank, title=f"Third-party candidate {rank}", domain="example.com", url=f"http://example.com/baseline/{rank}"))
            db.add(RetrievalCandidate(run_id=validation.id, rank=rank, title=f"Third-party candidate {rank}", domain="example.com", url=f"http://example.com/validation/{rank}"))
        db.commit()
        project_id = project.id
        prompt_id = prompt.id
        baseline_id = baseline.id
        validation_id = validation.id
    finally:
        db.close()

    db = SessionLocal()
    try:
        issues = generate_candidate_issues(db, project_id)
        assert issues, "expected at least one generated issue"
        issue = confirm_issue(db, issues[0].id)
        action = create_action(
            db,
            issue.id,
            OptimizationActionCreate(
                action_summary="Improve official comparison guide",
                action_detail="Add recommendation reasons, use cases, FAQ, and fresh evidence.",
                target_url="http://localhost/smokebrand/guide",
                content_feature_changes=["comparison table", "FAQ", "case proof"],
            ),
        )
        action_read = action_to_read(action)
        assert action_read["status"] == "PLANNED"
        assert action_read["content_feature_changes"][0]["feature"] == "LEGACY_NOTE"
        experiment = create_experiment(
            db,
            action.id,
            OptimizationExperimentCreate(
                hypothesis="Official guide improvements should raise explicit recommendation rate.",
                target_prompt_scope=[issues[0].prompt_id],
                primary_metric="target_page_conversion_rate",
            ),
        )
        experiment = lock_baseline(db, experiment.id, ExperimentRunsPayload(run_ids=[baseline_id]).run_ids)
        assert experiment_to_read(experiment)["status"] == "baseline_locked"
        baseline_metrics = experiment_to_read(experiment)["baseline_metrics"]
        assert baseline_metrics["target_page_retrieved_count"] == 1
        assert baseline_metrics["target_page_cited_count"] == 0
        assert baseline_metrics["target_page_conversion_rate"] == 0
        planned_action = release_action(
            db,
            action.id,
            ActionReleasePayload(
                release_note="Ready for manual release",
                release_evidence={"planned_url": "http://localhost/smokebrand/guide"},
                validation_wait_hours=0,
            ),
        )
        assert action_to_read(planned_action)["status"] == "READY_FOR_MANUAL_RELEASE"
        assert action_to_read(planned_action)["released_at"] is None
        try:
            release_action(
                db,
                action.id,
                ActionReleasePayload(
                    release_note="Smoke release",
                    release_evidence={"url": "http://localhost/smokebrand/guide"},
                    validation_wait_hours=0,
                    release_confirmed=True,
                ),
            )
            raise AssertionError("release_action should not directly confirm release")
        except Exception as exc:
            assert "发布审计接口" in str(exc)
        package = create_evidence_package_for_smoke(db, project_id, prompt_id, baseline_id)

        # Create and accept a strategy candidate (required by release gate invariant)
        now = datetime.now(UTC)
        candidate = OptimizationStrategyCandidate(
            project_id=project_id,
            experiment_id=experiment.id,
            evidence_package_id=package.id,
            target_url="http://localhost/smoke/card",
            provider="local_rule",
            model="local-rule-v1",
            prompt_version="smoke",
            generated_at=now,
            generation_status="GENERATED",
            original_llm_payload_json=dumps({"observed_problem": "smoke"}),
            structured_payload_json=dumps({"observed_problem": "smoke"}),
            human_edited_payload_json=dumps({}),
            evidence_validation_status="VALIDATED",
            hypothesis_validation_status="VALIDATED",
            review_status="ACCEPTED",
            reviewed_by="smoke",
            reviewed_at=now,
        )
        db.add(candidate)
        db.commit()

        hypothesis = create_hypothesis(
            db,
            experiment.id,
            OptimizationHypothesisCreate(
                evidence_package_id=package.id,
                observed_problem="Smoke baseline problem.",
                hypothesized_cause="Smoke possible cause.",
                core_mechanism="Smoke mechanism.",
                baseline_value="1/1",
                changed_features=["FAQ"],
                controlled_variables=["URL"],
            ),
        )
        try:
            confirm_experiment_release(
                db,
                experiment.id,
                ReleaseConfirmationPayload(
                    hypothesis_id=hypothesis.id,
                    pre_release_snapshot_id=999001,
                    post_release_snapshot_id=999002,
                    release_note="invalid smoke release",
                    confirmed_by="smoke",
                ),
            )
            raise AssertionError("release confirmation should require valid snapshots")
        except Exception as exc:
            assert "页面快照" in str(exc)
        pre_snapshot = _smoke_snapshot(db, project_id, experiment.id, "PRE_RELEASE")
        post_snapshot = _smoke_snapshot(db, project_id, experiment.id, "POST_RELEASE")
        experiment = confirm_experiment_release(
            db,
            experiment.id,
            ReleaseConfirmationPayload(
                hypothesis_id=hypothesis.id,
                pre_release_snapshot_id=pre_snapshot.id,
                post_release_snapshot_id=post_snapshot.id,
                planned_feature_changes=["FAQ"],
                deployed_feature_changes=["FAQ"],
                release_note="Smoke release",
                confirmed_by="smoke",
                validation_wait_hours=0,
            ),
        )
        action = db.get(type(action), action.id)
        assert action_to_read(action)["status"] == "RELEASE_CONFIRMED"
        retest = queue_retest_task(db, experiment.id, ExperimentRetestCreate(sample_count=2, execute_now=False))
        assert retest["queued_run_count"] == 2
        assert len(retest["run_ids"]) == 2
        experiment = start_validation(db, experiment.id)
        experiment = attach_validation_runs(db, experiment.id, ExperimentRunsPayload(run_ids=[validation_id]).run_ids)
        comparison = experiment_to_read(experiment)["comparison"]
        assert comparison["brand_recommendation_rate"]["delta"] > 0
        assert comparison["target_page_conversion_rate"]["baseline_cited_count"] == 0
        assert comparison["target_page_conversion_rate"]["validation_cited_count"] == 1
        assert comparison["target_page_conversion_rate"]["delta_pp"] == 100
        assert experiment_to_read(experiment)["per_prompt_results"], "experiment should expose per-prompt drilldown"
        assert experiment_to_read(experiment)["per_environment_results"], "experiment should expose per-environment drilldown"
        experiment = confirm_conclusion(
            db,
            experiment.id,
            ExperimentConclusionPayload(
                conclusion="EFFECTIVE",
                conclusion_reason="Smoke validation improved the primary metric.",
                resolved=True,
            ),
        )
        assert experiment_to_read(experiment)["status"] == "completed"
        assert experiment_to_read(experiment)["conclusion"] == "EFFECTIVE"
        chain = evidence_chain(db, issue.id)
        assert chain["source_analysis"], "evidence chain should include source analysis"
        assert any(row["cited"] for row in chain["source_analysis"]), "source analysis should include cited sources"
        first_source = chain["source_analysis"][0]
        assert "source_score" in first_source
        assert "citation_occurrence_count" in first_source
        assert "answer_citation_rate" in first_source
        assert first_source["score_explanation"], "source score should explain answer citation behavior"
        assert "citation_basis" in first_source
        assert "cross_source_comparison" in first_source
        assert "platform" in first_source
        assert "author_name" in first_source
        assert "published_date" in first_source
        scores = [row["source_score"] for row in chain["source_analysis"]]
        assert scores == sorted(scores, reverse=True), "source analysis should be sorted by score desc"
        assert "account_identity" in first_source
        assert "answer_usage" in first_source
        bili_source = next(row for row in chain["source_analysis"] if row["domain"] == "bilibili.com")
        assert bili_source["platform"] == "bilibili", "domain should take priority over title keywords"
        assert bili_source["published_date"] == "2026-08-01"
        assert len([row for row in chain["source_analysis"] if row["domain"] == "bilibili.com"]) == 1
        bili_reference = next(row for row in chain["references"] if row["domain"] == "bilibili.com")
        assert bili_reference["occurrence_count"] == 2
        leading_factors = " ".join(bili_source["cross_source_comparison"]["leading_factors"])
        assert "引用率" not in leading_factors
        assert "平均引用位次" not in leading_factors
        assert chain["runs"][0]["answer_text"], "evidence run should expose answer text"
    finally:
        db.close()
    print("optimization_loop_smoke: ok")


def create_evidence_package_for_smoke(db, project_id: int, prompt_id: int, run_id: int):
    from app.modules.optimization.schemas import EvidencePackageCreate
    from app.modules.optimization.service import create_evidence_package

    return create_evidence_package(
        db,
        project_id,
        EvidencePackageCreate(
            prompt_id=prompt_id,
            run_ids=[run_id],
            target_page_urls=["http://localhost/smokebrand/guide"],
            source_note="optimization_loop_smoke",
        ),
    )


def _smoke_snapshot(db, project_id: int, experiment_id: int, snapshot_type: str) -> PageSnapshot:
    html = f"<html><head><title>{snapshot_type}</title><link rel='canonical' href='http://localhost/smokebrand/guide'></head><body><h1>{snapshot_type}</h1><main>Smoke page content FAQ</main></body></html>"
    snapshot = PageSnapshot(
        project_id=project_id,
        experiment_id=experiment_id,
        target_url="http://localhost/smokebrand/guide",
        url="http://localhost/smokebrand/guide",
        http_status=200,
        final_url="http://localhost/smokebrand/guide",
        canonical_url="http://localhost/smokebrand/guide",
        raw_html=html,
        html_hash="smoke-html-hash-" + snapshot_type,
        title=snapshot_type,
        h1=snapshot_type,
        main_text="Smoke page content FAQ",
        main_text_hash="smoke-text-hash-" + snapshot_type,
        section_headings_json=dumps([snapshot_type]),
        structured_data_json="[]",
        internal_links_json="[]",
        robots_directives_json="{}",
        snapshot_type=snapshot_type,
        capture_status="success",
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def cleanup_smoke_database() -> None:
    if not os.environ.get("GEO_DATABASE_URL") and SMOKE_DB_PATH.exists():
        SMOKE_DB_PATH.unlink()


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup_smoke_database()
