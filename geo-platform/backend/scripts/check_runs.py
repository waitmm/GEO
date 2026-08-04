"""检查所有 Run 状态"""
import sys
sys.path.insert(0, '.')

from app.core.database import SessionLocal
from app.models import BrowserMonitorRun

db = SessionLocal()
runs = db.query(BrowserMonitorRun).order_by(BrowserMonitorRun.id.asc()).all()
print(f"Total runs: {len(runs)}")
for r in runs:
    query = (r.original_query[:50] if r.original_query else 'N/A').replace('\n', ' ')
    print(f"Run#{r.id} proj={r.project_id} prompt={r.prompt_id} status={r.status} stage={r.stage} dur={r.duration_ms}ms err={r.error_type} q={query}")

db.close()