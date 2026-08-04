"""检查数据库当前状态"""
import sys
sys.path.insert(0, '.')
from app.core.database import SessionLocal
from app.models import BrowserMonitorRun, MonitoringBatch, BrowserMonitorTask, Prompt, Topic

db = SessionLocal()

batches = db.query(MonitoringBatch).order_by(MonitoringBatch.id.desc()).all()
print("=== Batches ===")
for b in batches:
    print(f"  ID={b.id} name={b.name} status={b.status} sample_count={b.sample_count}")

tasks = db.query(BrowserMonitorTask).order_by(BrowserMonitorTask.id.desc()).all()
print(f"\n=== Tasks ({len(tasks)}) ===")
for t in tasks:
    print(f"  ID={t.id} project={t.project_id} status={t.status} run_count={t.run_count} adapter={t.adapter}")

runs = db.query(BrowserMonitorRun).order_by(BrowserMonitorRun.id.desc()).limit(30).all()
print(f"\n=== Runs ({len(runs)} of {db.query(BrowserMonitorRun).count()}) ===")
for r in runs:
    print(f"  Run#{r.id} task={r.task_id} prompt={r.prompt_id} status={r.status} stage={r.stage} query={r.original_query[:40] if r.original_query else 'N/A'}")

prompts = db.query(Prompt).all()
print(f"\n=== Prompts ({len(prompts)}) ===")
for p in prompts:
    print(f"  ID={p.id} project={p.project_id} text={p.prompt_text[:50]}")

db.close()