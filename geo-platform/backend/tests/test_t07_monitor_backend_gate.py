from __future__ import annotations

from release_test_client import TestClient

from app.core.release_database import get_release_db
from app.models import Project, Prompt
from app.release_main import create_release_app
from app.services.serialization import loads
from scripts.release_upgrade_check import business_fingerprint
from test_release_first_slice import _migrated_session, _seed_frozen_analysis


def test_project_monitor_separates_aggregates_na_and_scope_without_get_writes(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        analysis = _seed_frozen_analysis(db, reference_urls=[])
        db.add(Project(id=2, organization_id=1, name="Other project", brand_name="PrivateTarget"))
        db.add(Prompt(
            id=45,
            project_id=2,
            title="Foreign prompt",
            prompt_text="PRIVATE_PROJECT_TWO_PROMPT",
        ))
        db.commit()

        plan = loads(analysis.sampling_plan_json, {})
        frozen_prompt = plan["prompt_version"]
        database = db.get_bind().url.database
        app = create_release_app(validate_on_startup=False)
        app.dependency_overrides[get_release_db] = lambda: db

        before_gets = business_fingerprint(database)
        with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
            project_response = client.get("/api/v2/projects/1/monitor")
            prompt_response = client.get("/api/v2/projects/1/prompts/44/monitor")
        assert business_fingerprint(database) == before_gets

        assert project_response.status_code == prompt_response.status_code == 200
        project_view = project_response.json()
        prompt_view = prompt_response.json()
        assert project_view["aggregation"] == "PROMPT_MACRO_WITH_SEPARATE_RUN_WEIGHTED"
        assert [row["prompt"]["id"] for row in project_view["prompts"]] == [44]
        assert "PRIVATE_PROJECT_TWO_PROMPT" not in project_response.text

        mention = project_view["metrics"]["brand_mention_rate"]
        assert mention["prompt_macro_average"] == 0
        assert mention["run_weighted_average"] == 0
        assert mention["participating_prompt_ids"] == [44]
        assert mention["participating_prompt_count"] == mention["total_prompt_count"] == 1
        assert (mention["hit_count"], mention["evaluable_count"], mention["planned_count"]) == (0, 1, 1)
        option = project_view["metrics"]["brand_option_rate"]
        assert option["prompt_macro_average"] is None
        assert option["run_weighted_average"] is None
        assert option["participating_prompt_count"] == 0
        assert option["total_prompt_count"] == 1

        selection = prompt_view["analysis_selection"]
        assert selection["project_id"] == 1 and selection["prompt_id"] == 44
        assert selection["selected_run_ids"] == prompt_view["metrics"]["brand_mention_rate"]["evaluable_run_ids"]
        assert selection["raw_output_hash"] == prompt_view["raw_output_hash"]
        assert selection["identity_hash"] == prompt_view["measurement_identity_hash"]
        assert selection["prompt_version"] == frozen_prompt
        assert len(selection["scope_hash"]) == 64

        prompt = db.get(Prompt, 44)
        prompt.prompt_text = "Changed current question"
        db.commit()
        after_range_change_before_gets = business_fingerprint(database)
        with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50001)) as client:
            changed_prompt = client.get("/api/v2/projects/1/prompts/44/monitor").json()
            changed_project = client.get("/api/v2/projects/1/monitor").json()
        assert business_fingerprint(database) == after_range_change_before_gets

        changed_selection = changed_prompt["analysis_selection"]
        assert changed_selection["scope_hash"] != selection["scope_hash"]
        assert changed_selection["selected_run_ids"] == []
        assert changed_prompt["runs"] == []
        assert [row["run_id"] for row in changed_prompt["historical_query_runs"]] == selection["selected_run_ids"]
        assert changed_prompt["metrics"]["brand_mention_rate"]["value"] is None
        changed_mention = changed_project["metrics"]["brand_mention_rate"]
        assert changed_mention["prompt_macro_average"] is None
        assert changed_mention["run_weighted_average"] is None
        assert changed_mention["participating_prompt_ids"] == []
        assert changed_mention["total_prompt_count"] == 1
    finally:
        db.close()
        engine.dispose()
