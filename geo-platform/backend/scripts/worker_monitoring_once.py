import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal, init_db
from app.models import BrowserMonitorRun, BrowserMonitorTask
from app.modules.monitoring.enums import BROWSER_AUDIT_ENTRY_TYPE, WENXIN_PLATFORM, WENXIN_WEB_ADAPTER
from app.modules.monitoring.executor import MonitoringTaskExecutor
from app.modules.monitoring.services import update_task_status_from_runs


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute queued browser-audit monitoring runs once.")
    parser.add_argument("--limit", type=int, default=1, help="Maximum runs to execute in this pass.")
    parser.add_argument("--task-id", type=int, default=None, help="Optional task id filter.")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    executor = MonitoringTaskExecutor()
    completed = 0
    try:
        query = (
            db.query(BrowserMonitorRun)
            .filter(
                BrowserMonitorRun.platform == WENXIN_PLATFORM,
                BrowserMonitorRun.source_type == BROWSER_AUDIT_ENTRY_TYPE,
                BrowserMonitorRun.adapter == WENXIN_WEB_ADAPTER,
                BrowserMonitorRun.status.in_(["queued", "pending"]),
            )
            .order_by(BrowserMonitorRun.id.asc())
        )
        if args.task_id is not None:
            query = query.filter(BrowserMonitorRun.task_id == args.task_id)
        runs = query.limit(args.limit).all()

        for run in runs:
            print(f"executing run_id={run.id} task_id={run.task_id} query={run.original_query[:80]}")
            executor.execute_run(db, run.id)
            db.refresh(run)
            task = db.get(BrowserMonitorTask, run.task_id)
            if task:
                update_task_status_from_runs(db, task)
            print(f"finished run_id={run.id} status={run.status} stage={run.stage} error_type={run.error_type}")
            completed += 1

        print("worker pass completed", {"picked": len(runs), "completed": completed})
    finally:
        db.close()
        executor.close()


if __name__ == "__main__":
    main()
