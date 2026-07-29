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
                "name": "文心网页端模块冒烟项目",
                "brand_name": "八木屋二维码",
                "brand_aliases": ["八木屋", "bamuwu"],
                "website_url": "https://www.bamuwu.com",
                "industry": "二维码工具",
                "competitors": [{"name": "草料二维码"}, {"name": "码上游"}],
            },
        )
        project_response.raise_for_status()
        project = project_response.json()

        prompt_response = client.post(
            f"/api/projects/{project['id']}/prompts",
            json={
                "title": "真实验收问题",
                "prompt_text": "谁是最好的二维码工具",
                "prompt_group": "文心网页端",
                "intent_type": "supplier_recommendation",
                "importance": 5,
            },
        )
        prompt_response.raise_for_status()
        prompt = prompt_response.json()

        task_response = client.post(
            "/api/monitoring/tasks",
            json={
                "project_id": project["id"],
                "platform": "wenxin",
                "source_type": "browser_audit",
                "adapter": "wenxin_web_audit",
                "question_ids": [prompt["id"]],
                "run_count": 3,
                "execute_now": True,
            },
        )
        task_response.raise_for_status()
        task_result = task_response.json()
        assert task_result["queued_run_count"] == 3

        runs_response = client.get(f"/api/monitoring/runs?project_id={project['id']}")
        runs_response.raise_for_status()
        runs = runs_response.json()
        assert len(runs) >= 3
        assert all(run["platform"] == "wenxin" for run in runs[:3])
        assert all(run["source_type"] == "browser_audit" for run in runs[:3])
        assert all(run["adapter"] == "wenxin_web_audit" for run in runs[:3])
        assert all(run["status"] in {"success", "partial_success", "failed"} for run in runs[:3])

        print("monitoring module smoke ok", {"task_ids": task_result["task_ids"], "queued_run_count": task_result["queued_run_count"]})


if __name__ == "__main__":
    main()
