import argparse
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal, init_db
from app.models import Project
from app.modules.monitoring.executor import MonitoringTaskExecutor
from app.modules.monitoring.services import queue_due_daily_prompt_tasks, update_task_status_from_runs


def main() -> None:
    parser = argparse.ArgumentParser(description="Queue due daily Prompt monitoring tasks.")
    parser.add_argument("--project-id", type=int, default=None, help="Optional project id. Defaults to all active projects.")
    parser.add_argument("--execute-now", action="store_true", help="Execute queued daily tasks immediately.")
    parser.add_argument("--loop", action="store_true", help="Keep checking due schedules.")
    parser.add_argument("--interval", type=int, default=300, help="Loop interval in seconds.")
    args = parser.parse_args()

    init_db()
    while True:
        result = run_once(args.project_id, args.execute_now)
        print("daily schedule pass completed", result)
        if not args.loop:
            return
        time.sleep(max(30, args.interval))


def run_once(project_id: int | None, execute_now: bool) -> dict:
    db = SessionLocal()
    executor = MonitoringTaskExecutor() if execute_now else None
    try:
        query = db.query(Project).filter(Project.status == "active").order_by(Project.id.asc())
        if project_id is not None:
            query = query.filter(Project.id == project_id)
        projects = query.all()
        total_tasks = 0
        total_runs = 0
        project_rows = []
        for project in projects:
            tasks, queued_count = queue_due_daily_prompt_tasks(db, project, execute_now=execute_now)
            if execute_now and executor:
                for task in tasks:
                    executor.execute_queued_runs(db, task.id)
                    update_task_status_from_runs(db, task)
            total_tasks += len(tasks)
            total_runs += queued_count
            project_rows.append(
                {
                    "project_id": project.id,
                    "project_name": project.name,
                    "task_ids": [task.id for task in tasks],
                    "queued_run_count": queued_count,
                }
            )
        return {"projects": project_rows, "task_count": total_tasks, "queued_run_count": total_runs}
    finally:
        db.close()
        if executor:
            executor.close()


if __name__ == "__main__":
    main()
