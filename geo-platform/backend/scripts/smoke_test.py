import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.main import app


def main() -> None:
    with TestClient(app) as client:
        run_smoke(client)


def run_smoke(client: TestClient) -> None:
    project_response = client.post(
        "/api/projects",
        json={
            "name": "Smoke Test Project",
            "brand_name": "Acme",
            "brand_aliases": ["Acme AI"],
            "website_url": "https://www.acme.com",
            "industry": "B2B SaaS",
            "competitors": [{"name": "Rival"}],
        },
    )
    project_response.raise_for_status()
    project = project_response.json()

    prompt_response = client.post(
        f"/api/projects/{project['id']}/prompts",
        json={
            "title": "Recommendation",
            "prompt_text": "Which B2B SaaS tools are recommended for brand visibility monitoring?",
            "prompt_group": "core",
            "intent_type": "supplier_recommendation",
            "importance": 5,
            "enabled": True,
        },
    )
    prompt_response.raise_for_status()
    prompt = prompt_response.json()

    run_response = client.post(
        f"/api/projects/{project['id']}/monitor-runs",
        json={"prompt_ids": [prompt["id"]], "platform_keys": ["mock"], "repeat_count": 2},
    )
    run_response.raise_for_status()
    run = run_response.json()

    metrics_response = client.get(f"/api/projects/{project['id']}/metrics/overview")
    metrics_response.raise_for_status()
    metrics = metrics_response.json()

    assert run["success_count"] == 2
    assert metrics["observation_count"] == 2
    print("smoke ok", {"project_id": project["id"], "run_id": run["id"], "metrics": metrics})


if __name__ == "__main__":
    main()
