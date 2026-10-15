from __future__ import annotations

import json
from uuid import uuid4

import pytest
from release_test_client import TestClient

from app.core.release_database import get_release_db
from app.models import BrowserMonitorRun, BrowserMonitorTask, SinglePromptAnalysis
from app.modules.single_prompt_v2.service import _hash
from app.release_main import create_release_app
from test_release_first_slice import _migrated_session


@pytest.fixture
def client_db(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    app = create_release_app(validate_on_startup=False)
    app.dependency_overrides[get_release_db] = lambda: db
    try:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            yield client, db
    finally:
        db.close()
        engine.dispose()


def test_analysis_creation_freezes_exact_prompt_version_and_preserves_legacy_reads(client_db):
    client, db = client_db
    project = client.post("/api/projects", json={"name": "Project", "brand_name": "Brand"}).json()
    prompt_route = f"/api/projects/{project['id']}/prompts"
    prompt = client.post(prompt_route, json={
        "prompt_text": "Question V1",
        "intent_type": "usage_instruction",
        "prompt_group": "Group V1",
    }).json()
    versions_route = f"{prompt_route}/{prompt['id']}/versions"
    v1 = client.get(versions_route).json()[0]
    analysis_route = "/api/v2/single-prompt/analyses"
    create_v1 = {
        "project_id": project["id"],
        "prompt_id": prompt["id"],
        "prompt_version_id": v1["prompt_version_id"],
        "snapshot_hash": v1["snapshot_hash"],
        "sample_count": 1,
        "idempotency_key": "prompt-version-analysis-v1",
    }

    created = client.post(analysis_route, json=create_v1)
    assert created.status_code == 202
    body = created.json()
    assert body["analysis"]["prompt_text"] == "Question V1"
    assert body["analysis"]["prompt_version"] == {
        "binding_status": "BOUND",
        "prompt_version_id": v1["prompt_version_id"],
        "version_number": 1,
        "snapshot_hash": v1["snapshot_hash"],
        "snapshot": v1["snapshot"],
    }
    analysis = db.query(SinglePromptAnalysis).filter_by(
        analysis_id=body["analysis"]["analysis_id"]
    ).one()
    plan = json.loads(analysis.sampling_plan_json)
    assert plan["prompt_text"] == "Question V1"
    assert plan["prompt_configuration"] == {
        "intent_type": "usage_instruction",
        "prompt_group": "Group V1",
    }
    run = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).one()
    assert run.original_query == "Question V1"

    client.patch(f"{prompt_route}/{prompt['id']}", json={
        "prompt_text": "Question V2",
        "prompt_group": "Group V2",
    })
    v2 = client.get(versions_route).json()[0]
    same_key_other_version = client.post(analysis_route, json={
        **create_v1,
        "prompt_version_id": v2["prompt_version_id"],
        "snapshot_hash": v2["snapshot_hash"],
    })
    assert same_key_other_version.status_code == 409
    assert client.post(analysis_route, json={
        **create_v1,
        "idempotency_key": "wrong-prompt-version-hash",
        "snapshot_hash": "0" * 64,
    }).status_code == 409

    run.status = "success"
    run.stage = "success"
    run.answer_text = "A traceable answer"
    run.answer_char_count = len(run.answer_text)
    db.commit()
    pool = client.get(
        "/api/v2/single-prompt/runs",
        params={"project_id": project["id"], "prompt_id": prompt["id"]},
    ).json()
    fingerprint = pool["items"][0]["input_fingerprint"]
    selected = client.post(f"{analysis_route}/from-runs", json={
        "project_id": project["id"],
        "prompt_id": prompt["id"],
        "prompt_version_id": v1["prompt_version_id"],
        "snapshot_hash": v1["snapshot_hash"],
        "run_ids": [run.id],
        "run_fingerprints": {str(run.id): fingerprint},
        "base_context_id": None,
        "idempotency_key": "prompt-version-from-runs-v1",
    })
    assert selected.status_code == 201
    assert selected.json()["analysis"]["prompt_version"]["prompt_version_id"] == v1["prompt_version_id"]

    legacy_task = BrowserMonitorTask(
        project_id=project["id"], platform="wenxin", source_type="browser_audit",
        adapter="wenxin_web_audit", question_ids_json=json.dumps([prompt["id"]]),
        run_count=1, schedule_type="legacy", status="success",
    )
    db.add(legacy_task)
    db.flush()
    legacy_run = BrowserMonitorRun(
        task_id=legacy_task.id, project_id=project["id"], prompt_id=prompt["id"],
        status="success", stage="success", original_query="Question V1",
        answer_text="Legacy answer", answer_char_count=13,
    )
    db.add(legacy_run)
    db.commit()
    legacy_pool = client.get(
        "/api/v2/single-prompt/runs",
        params={"project_id": project["id"], "prompt_id": prompt["id"]},
    ).json()
    legacy_fingerprint = next(
        item["input_fingerprint"] for item in legacy_pool["items"] if item["run_id"] == legacy_run.id
    )
    unsafe = client.post(f"{analysis_route}/from-runs", json={
        "project_id": project["id"],
        "prompt_id": prompt["id"],
        "prompt_version_id": v1["prompt_version_id"],
        "snapshot_hash": v1["snapshot_hash"],
        "run_ids": [legacy_run.id],
        "run_fingerprints": {str(legacy_run.id): legacy_fingerprint},
        "base_context_id": None,
        "idempotency_key": "unproven-legacy-run-selection",
    })
    assert unsafe.status_code == 409
    assert unsafe.json()["detail"]["code"] == "RUN_PROMPT_VERSION_UNPROVEN"

    legacy_plan = {"contract_version": "legacy", "sample_count": 0}
    legacy_analysis = SinglePromptAnalysis(
        analysis_id=f"legacy-{uuid4()}", project_id=project["id"], prompt_id=prompt["id"],
        task_id=None, idempotency_key="legacy-analysis-read", prompt_text_snapshot="Historical question",
        sampling_plan_json=json.dumps(legacy_plan, sort_keys=True, separators=(",", ":")),
        sampling_plan_hash=_hash(legacy_plan), status="READY",
    )
    db.add(legacy_analysis)
    db.commit()
    legacy_read = client.get(
        f"{analysis_route}/{legacy_analysis.analysis_id}",
        params={"project_id": project["id"], "prompt_id": prompt["id"]},
    )
    assert legacy_read.status_code == 200
    assert legacy_read.json()["analysis"]["prompt_version"] == {"binding_status": "LEGACY_UNBOUND"}
    listed = client.get(
        analysis_route,
        params={"project_id": project["id"], "prompt_id": prompt["id"]},
    ).json()
    assert {row["analysis"]["prompt_version"]["binding_status"] for row in listed} == {"BOUND", "LEGACY_UNBOUND"}
