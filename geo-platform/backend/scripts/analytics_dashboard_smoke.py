import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.models import (  # noqa: E402
    Base,
    BrowserMonitorRun,
    BrowserMonitorTask,
    Competitor,
    Organization,
    Project,
    Prompt,
    ReferenceSource,
)
from app.modules.analytics.service import build_validation_dashboard  # noqa: E402


def main() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        organization = Organization(name="Analytics smoke")
        db.add(organization)
        db.flush()
        project = Project(
            organization_id=organization.id,
            name="GEO Audit",
            brand_name="八木屋",
            brand_aliases_json=json.dumps(["八木屋二维码"], ensure_ascii=False),
        )
        db.add(project)
        db.flush()
        competitor = Competitor(
            project_id=project.id,
            name="草料",
            aliases_json=json.dumps(["草料二维码"], ensure_ascii=False),
        )
        prompt = Prompt(
            project_id=project.id,
            prompt_text="哪个二维码工具最好",
            prompt_group="综合工具推荐",
        )
        db.add_all([competitor, prompt])
        db.flush()
        task = BrowserMonitorTask(project_id=project.id, question_ids_json=f"[{prompt.id}]")
        db.add(task)
        db.flush()

        runs = [
            BrowserMonitorRun(
                task_id=task.id,
                project_id=project.id,
                prompt_id=prompt.id,
                status="success",
                answer_text="推荐八木屋二维码，也可选择草料二维码。",
                brand_recommendation_level=3,
                expected_reference_count=2,
                detected_reference_count=2,
                resolved_reference_count=2,
                reference_complete=True,
            ),
            BrowserMonitorRun(
                task_id=task.id,
                project_id=project.id,
                prompt_id=prompt.id,
                status="partial_success",
                answer_text="草料二维码是常见工具。",
                expected_reference_count=2,
                detected_reference_count=2,
                resolved_reference_count=1,
            ),
            BrowserMonitorRun(
                task_id=task.id,
                project_id=project.id,
                prompt_id=prompt.id,
                status="failed",
                error_type="captcha_required",
            ),
            BrowserMonitorRun(
                task_id=task.id,
                project_id=project.id,
                prompt_id=prompt.id,
                status="failed",
                error_type="answer_parse_failed",
            ),
        ]
        db.add_all(runs)
        db.flush()
        db.add_all(
            [
                ReferenceSource(
                    run_id=runs[0].id,
                    reference_index=1,
                    url="https://example.com/a",
                    canonical_url="https://example.com/a",
                    domain="example.com",
                    display_title="A",
                ),
                ReferenceSource(
                    run_id=runs[1].id,
                    reference_index=1,
                    url="https://example.com/a",
                    canonical_url="https://example.com/a",
                    domain="example.com",
                    display_title="A",
                ),
            ]
        )
        db.commit()

        dashboard = build_validation_dashboard(db, project)
        assert dashboard.prompts.total_prompts == 1
        assert dashboard.prompts.total_clusters == 1
        assert (dashboard.brand_presence.observed_runs, dashboard.brand_presence.sample_runs) == (1, 2)
        assert dashboard.competitor_presence[0].observed_runs == 2
        assert dashboard.recommendation_presence.explicit_recommendation == 1
        assert dashboard.top_citation_domains[0].occurrences == 2
        assert dashboard.data_quality.success == 2
        assert dashboard.data_quality.blocked == 1
        assert dashboard.data_quality.collector_failed == 1
        assert dashboard.data_quality.references.url_resolution_rate == 0.75
        print("analytics dashboard smoke ok", dashboard.model_dump())


if __name__ == "__main__":
    main()

