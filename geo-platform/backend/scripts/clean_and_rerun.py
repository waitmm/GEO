"""清理异常 Run 并重新执行"""
import sys, os
sys.path.insert(0, '.')

os.environ['CHROMIUM_EXECUTABLE_PATH'] = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

from app.core.database import SessionLocal
from app.models import BrowserMonitorRun
from app.modules.monitoring.executor import MonitoringTaskExecutor

db = SessionLocal()

# 1. 删除卡死的 Run#2 (stuck running) 和 #3, #4 (queued 但不需要了)
for run_id in [2, 3, 4]:
    run = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.id == run_id).first()
    if run:
        db.delete(run)
        print(f"Deleted Run#{run_id}")

# 2. 把 pending 的 Run#5, #6, #7 改为 queued
for run_id in [5, 6, 7]:
    run = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.id == run_id).first()
    if run and run.status in ('pending', 'queued'):
        run.status = 'queued'
        run.stage = 'queued'
        run.error_type = ''
        run.error_message = ''
        print(f"Run#{run_id} set to queued")
db.commit()

# 3. 执行 Run#5, #6, #7
todo = db.query(BrowserMonitorRun).filter(
    BrowserMonitorRun.id.in_([5, 6, 7]),
    BrowserMonitorRun.status == 'queued'
).order_by(BrowserMonitorRun.id.asc()).all()

print(f"\nExecuting {len(todo)} runs...")
executor = MonitoringTaskExecutor()
try:
    for run in todo:
        print(f"\nExecuting Run#{run.id} prompt={run.prompt_id}...")
        try:
            executor.execute_run(db, run.id)
            db.refresh(run)
            print(f"  status={run.status} answer_len={len(run.answer_text or '')} dur={run.duration_ms}ms err={run.error_type}")
        except Exception as exc:
            print(f"  FAILED: {exc}")
            run.status = 'failed'
            run.error_message = str(exc)
            db.commit()
finally:
    executor.close()

db.commit()
db.close()
print("\nDone!")