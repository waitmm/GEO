"""将所有 pending 的 Run 改为 queued 以让 Worker 领取，同时将 Task 状态改为 queued"""
import sys
sys.path.insert(0, '.')
from app.core.database import SessionLocal
from app.models import BrowserMonitorRun, BrowserMonitorTask, MonitoringBatch

db = SessionLocal()

runs = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.status == 'pending').all()
print(f"Found {len(runs)} pending runs")
for r in runs:
    r.status = 'queued'
    r.stage = 'queued'
    print(f"  Run#{r.id} -> queued")

tasks = db.query(BrowserMonitorTask).filter(BrowserMonitorTask.status == 'pending').all()
print(f"Found {len(tasks)} pending tasks")
for t in tasks:
    t.status = 'queued'
    print(f"  Task#{t.id} -> queued")

batches = db.query(MonitoringBatch).filter(MonitoringBatch.status == 'draft').all()
print(f"Found {len(batches)} draft batches")
for b in batches:
    b.status = 'queued'
    print(f"  Batch#{b.id} -> queued")

db.commit()
print("Done. Refresh frontend to see runs in the queue.")
db.close()