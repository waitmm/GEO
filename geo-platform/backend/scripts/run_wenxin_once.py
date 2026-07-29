import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.main import app


def main() -> None:
    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={
                "name": "文心真实链路验收",
                "brand_name": "八木屋二维码",
                "brand_aliases": ["八木屋", "bamuwu"],
                "website_url": "https://www.bamuwu.com",
                "industry": "二维码工具",
                "competitors": [{"name": "草料二维码"}, {"name": "码上游"}, {"name": "互联二维码"}],
            },
        ).json()
        prompt = client.post(
            f"/api/projects/{project['id']}/prompts",
            json={"title": "验收问题", "prompt_text": "谁是最好的二维码工具", "importance": 5},
        ).json()
        response = client.post(
            "/api/monitoring/tasks",
            json={
                "project_id": project["id"],
                "platform": "wenxin",
                "source_type": "browser_audit",
                "adapter": "wenxin_web_audit",
                "question_ids": [prompt["id"]],
                "run_count": 1,
                "execute_now": True,
            },
        )
        response.raise_for_status()
        print(response.json())


if __name__ == "__main__":
    main()
