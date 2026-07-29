from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal, init_db
from app.models import MonitoringBatch, Project, Prompt, PromptCluster, Topic
from app.modules.monitoring.services import create_browser_task


PROMPT_GROUPS = {
    "综合工具推荐": [
        "哪个二维码工具最好",
        "二维码生成器哪个好",
        "好用的二维码平台有哪些",
        "国内主流二维码工具推荐",
        "做二维码用什么软件比较好",
    ],
    "企业选型": [
        "企业二维码平台哪个好",
        "公司做二维码用哪个平台",
        "企业二维码生成器推荐",
        "适合企业长期管理二维码的工具有哪些",
        "企业如何选择二维码管理平台",
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the 10-prompt Bamuwu GEO Audit qualification set.")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--sample-count", type=int, default=3)
    parser.add_argument("--queue", action="store_true", help="Create queued sample runs after seeding.")
    parser.add_argument(
        "--collection-mode",
        choices=["single_continuous", "single_independent"],
        default="single_continuous",
    )
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        project = db.get(Project, args.project_id)
        if not project:
            raise SystemExit(f"Project not found: {args.project_id}")

        topic = (
            db.query(Topic)
            .filter(Topic.project_id == project.id, Topic.name == "二维码平台选择")
            .first()
        )
        if not topic:
            topic = Topic(
                project_id=project.id,
                name="二维码平台选择",
                description="八木屋 GEO Audit Alpha 基线主题",
                sort_order=1,
            )
            db.add(topic)
            db.flush()

        prompts: list[Prompt] = []
        for order, (cluster_name, questions) in enumerate(PROMPT_GROUPS.items(), start=1):
            cluster = (
                db.query(PromptCluster)
                .filter(
                    PromptCluster.project_id == project.id,
                    PromptCluster.topic_id == topic.id,
                    PromptCluster.name == cluster_name,
                )
                .first()
            )
            if not cluster:
                cluster = PromptCluster(
                    project_id=project.id,
                    topic_id=topic.id,
                    name=cluster_name,
                    sample_count=args.sample_count,
                    sort_order=order,
                )
                db.add(cluster)
                db.flush()

            for question in questions:
                prompt = (
                    db.query(Prompt)
                    .filter(Prompt.project_id == project.id, Prompt.prompt_text == question)
                    .first()
                )
                if not prompt:
                    prompt = Prompt(
                        project_id=project.id,
                        topic_id=topic.id,
                        cluster_id=cluster.id,
                        title=question,
                        prompt_text=question,
                        prompt_group=cluster_name,
                        intent_type="supplier_recommendation",
                        importance=5,
                        sample_count=args.sample_count,
                        enabled=True,
                    )
                    db.add(prompt)
                    db.flush()
                prompts.append(prompt)

        batch = MonitoringBatch(
            project_id=project.id,
            name=f"{datetime.now():%Y-%m-%d} 八木屋文心基线监测",
            platform="wenxin",
            collection_mode=args.collection_mode,
            sample_count=args.sample_count,
            status="queued" if args.queue else "draft",
            notes=(
                "Validation Sample；单一采集环境。"
                "single_continuous 用于稳定产品观测，不能解释为真实曝光概率。"
            ),
        )
        db.add(batch)
        db.flush()

        task = None
        if args.queue:
            task = create_browser_task(
                db,
                project,
                prompts,
                args.sample_count,
                execute_now=True,
                batch_id=batch.id,
            )
        db.commit()
        print(
            {
                "project_id": project.id,
                "topic_id": topic.id,
                "prompt_count": len(prompts),
                "batch_id": batch.id,
                "task_id": task.id if task else None,
                "sample_runs": len(prompts) * args.sample_count if args.queue else 0,
                "collection_mode": args.collection_mode,
            }
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
