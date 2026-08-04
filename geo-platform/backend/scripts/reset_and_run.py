"""重置失败 Run 并重新执行"""
import sys, os
sys.path.insert(0, '.')

# 设置 Chrome 路径
os.environ['CHROMIUM_EXECUTABLE_PATH'] = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

from app.core.database import SessionLocal
from app.models import BrowserMonitorRun
from app.modules.monitoring.executor import MonitoringTaskExecutor

db = SessionLocal()

failed = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.status == 'failed').all()
for r in failed:
    r.status = 'queued'
    r.stage = 'queued'
    r.error_type = ''
    r.error_message = ''
    print(f"Run#{r.id} reset -> queued")
db.commit()

todo = db.query(BrowserMonitorRun).filter(
    BrowserMonitorRun.status.in_(['queued', 'pending'])
).order_by(BrowserMonitorRun.id.asc()).all()
print(f"\n{len(todo)} runs to execute")

executor = MonitoringTaskExecutor()
try:
    for run in todo:
        print(f"Executing Run#{run.id}...")
        executor.execute_run(db, run.id)
        db.refresh(run)
        print(f"  -> status={run.status}, answer_len={len(run.answer_text or '')}, duration={run.duration_ms}ms")
finally:
    executor.close()

db.commit()
db.close()
print("\nDone!")