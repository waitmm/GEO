import argparse
import atexit
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal, init_db
from app.models import BrowserMonitorRun, BrowserMonitorTask
from app.modules.monitoring.enums import BROWSER_AUDIT_ENTRY_TYPE, WENXIN_PLATFORM, WENXIN_WEB_ADAPTER
from app.modules.monitoring.executor import MonitoringTaskExecutor
from app.modules.monitoring.services import update_task_status_from_runs


def main() -> None:
    parser = argparse.ArgumentParser(description="Continuously execute queued browser-audit monitoring runs.")
    parser.add_argument("--interval", type=int, default=10, help="Polling interval in seconds.")
    parser.add_argument("--batch-size", type=int, default=1, help="Maximum runs to execute per polling pass.")
    parser.add_argument("--task-id", type=int, default=None, help="Optional task id filter.")
    parser.add_argument("--max-idle-passes", type=int, default=0, help="Stop after N idle passes. 0 means run forever.")
    args = parser.parse_args()

    init_db()
    executor = MonitoringTaskExecutor()
    atexit.register(executor.close)
    idle_passes = 0
    print(
        "monitoring worker started",
        {
            "interval": args.interval,
            "batch_size": args.batch_size,
            "task_id": args.task_id,
            "max_idle_passes": args.max_idle_passes,
        },
    )

    while True:
        picked = _run_once(executor, args.batch_size, args.task_id)
        if picked == 0:
            idle_passes += 1
            print(f"worker idle pass={idle_passes}")
        else:
            idle_passes = 0

        if args.max_idle_passes and idle_passes >= args.max_idle_passes:
            print("monitoring worker stopped after idle limit")
            return
        time.sleep(args.interval)


def _run_once(executor: MonitoringTaskExecutor, batch_size: int, task_id: Optional[int]) -> int:
    db = SessionLocal()
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
        if task_id is not None:
            query = query.filter(BrowserMonitorRun.task_id == task_id)
        runs = query.limit(batch_size).all()

        for run in runs:
            print(f"executing run_id={run.id} task_id={run.task_id} query={run.original_query[:80]}")
            executor.execute_run(db, run.id)
            db.refresh(run)
            task = db.get(BrowserMonitorTask, run.task_id)
            if task:
                update_task_status_from_runs(db, task)
            print(f"finished run_id={run.id} status={run.status} stage={run.stage} error_type={run.error_type}")
        return len(runs)
    finally:
        db.close()


if __name__ == "__main__":
    main()
