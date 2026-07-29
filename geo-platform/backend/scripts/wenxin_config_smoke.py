import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.main import app


def main() -> None:
    with TestClient(app) as client:
        project_response = client.post(
            "/api/projects",
            json={
                "name": "Wenxin Config Smoke",
                "brand_name": "Acme",
                "website_url": "https://www.acme.com",
                "competitors": [{"name": "Rival"}],
            },
        )
        project_response.raise_for_status()
        project = project_response.json()

        prompt_response = client.post(
            f"/api/projects/{project['id']}/prompts",
            json={"title": "Wenxin", "prompt_text": "请推荐一个AI品牌可见度监测平台。"},
        )
        prompt_response.raise_for_status()
        prompt = prompt_response.json()

        run_response = client.post(
            f"/api/projects/{project['id']}/monitor-runs",
            json={"prompt_ids": [prompt["id"]], "platform_keys": ["wenxin"], "repeat_count": 1},
        )
        run_response.raise_for_status()
        run = run_response.json()
        assert run["failure_count"] == 1
        print("wenxin config smoke ok", {"run_id": run["id"], "status": run["status"]})


if __name__ == "__main__":
    main()
