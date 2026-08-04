import sys
sys.path.insert(0, '.')
from app.core.database import SessionLocal
from app.models import BrowserMonitorRun

db = SessionLocal()

# 删掉卡死的 2/3/4
for rid in [2, 3, 4]:
    r = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.id == rid).first()
    if r:
        print(f"Deleting Run#{rid} status={r.status}")
        db.delete(r)

# 5/6/7 pending -> queued
for rid in [5, 6, 7]:
    r = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.id == rid).first()
    if r:
        print(f"Run#{rid} {r.status} -> queued")
        r.status = 'queued'
        r.stage = 'queued'

db.commit()
db.close()
print("Cleaned.")