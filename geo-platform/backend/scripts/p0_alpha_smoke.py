from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def main() -> None:
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    temp_dir = Path(tempfile.mkdtemp(prefix="geo-p0-smoke-"))
    os.environ["DATABASE_URL"] = f"sqlite:///{(temp_dir / 'p0.db').as_posix()}"

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={
                "name": "P0 Audit Smoke",
                "brand_name": "八木屋二维码",
                "brand_aliases": ["八木屋", "bamuwu"],
                "website_url": "https://www.bamuwu.com",
                "industry": "二维码工具",
                "competitors": [{"name": "草料二维码"}, {"name": "码上游"}],
            },
        ).json()
        topic = client.post(
            f"/api/projects/{project['id']}/topics",
            json={"name": "二维码平台选择"},
        ).json()
        cluster = client.post(
            f"/api/projects/{project['id']}/prompt-clusters",
            json={"topic_id": topic["id"], "name": "企业选型"},
        ).json()
        prompt_a = client.post(
            f"/api/projects/{project['id']}/prompts",
            json={
                "topic_id": topic["id"],
                "cluster_id": cluster["id"],
                "title": "企业二维码平台哪个好",
                "prompt_text": "企业二维码平台哪个好",
                "prompt_group": "企业选型",
                "intent_type": "supplier_recommendation",
            },
        ).json()
        prompt_b = client.post(
            f"/api/projects/{project['id']}/prompts",
            json={
                "topic_id": topic["id"],
                "cluster_id": cluster["id"],
                "title": "适合做产品二维码的工具有哪些",
                "prompt_text": "适合做产品二维码的工具有哪些",
                "prompt_group": "企业选型",
                "intent_type": "supplier_recommendation",
            },
        ).json()
        batch = client.post(
            f"/api/projects/{project['id']}/monitoring-batches",
            json={
                "name": "P0 Smoke Batch",
                "collection_mode": "single_independent",
                "sample_count": 2,
                "status": "queued",
            },
        ).json()
        task = client.post(
            "/api/monitoring/tasks",
            json={
                "project_id": project["id"],
                "batch_id": batch["id"],
                "question_ids": [prompt_a["id"], prompt_b["id"]],
                "run_count": 2,
                "execute_now": False,
            },
        )
        task.raise_for_status()
        runs = client.get(f"/api/monitoring/runs?project_id={project['id']}").json()
        assert len(runs) == 4
        assert all(run["batch_id"] == batch["id"] for run in runs)
        assert all(run["collection_mode"] == "single_independent" for run in runs)
        assert [(run["run_sequence"], run["prompt_id"], run["sample_index"]) for run in runs] == [
            (1, prompt_a["id"], 1),
            (1, prompt_b["id"], 1),
            (2, prompt_a["id"], 2),
            (2, prompt_b["id"], 2),
        ]
        dashboard = client.get(
            f"/api/analytics/projects/{project['id']}/validation-dashboard"
        )
        dashboard.raise_for_status()
        payload = dashboard.json()
        assert payload["sample_label"] == "Validation Sample"
        assert payload["prompts"]["total_prompts"] == 2
        assert payload["prompts"]["configured_samples"] == 4
        assert payload["data_quality"]["pending"] == 4
        print(
            "p0 alpha smoke ok",
            {
                "project_id": project["id"],
                "topic_id": topic["id"],
                "cluster_id": cluster["id"],
                "batch_id": batch["id"],
                "sample_runs": len(runs),
            },
        )


if __name__ == "__main__":
    main()
