"""Single-concurrency business worker for the GEO 1.0 release control plane."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.release_database import ReleaseSessionLocal, release_engine
from app.models import BrowserMonitorTask, SinglePromptAnalysis, SinglePromptDiagnosisExecution, SinglePromptSourcePreparation
from app.modules.monitoring.executor import MonitoringTaskExecutor
from app.modules.monitoring.services import update_task_status_from_runs
from app.modules.single_prompt_v2.diagnosis import execute_diagnosis, execute_queued_evidence
from app.modules.single_prompt_v2.service import execute_analysis
from app.modules.single_prompt_v2.source_preparation import AUTO_FETCH_QUEUED_STATUS, execute_auto_fetch
from app.release_schema import validate_release_database


def run_once() -> str | None:
    db = ReleaseSessionLocal()
    try:
        retry_task = (
            db.query(BrowserMonitorTask)
            .filter_by(schedule_type="single_prompt_v2_run_retry", status="queued")
            .order_by(BrowserMonitorTask.id.asc())
            .first()
        )
        analysis = (
            db.query(SinglePromptAnalysis)
            .filter(SinglePromptAnalysis.status == "QUEUED")
            .order_by(SinglePromptAnalysis.id.asc())
            .first()
        )
        if retry_task:
            identity = retry_task.id
            work_type = "run_retry"
        elif analysis:
            identity = analysis.analysis_id
            work_type = "analysis"
        else:
            preparation = (
                db.query(SinglePromptSourcePreparation)
                .filter(SinglePromptSourcePreparation.status == AUTO_FETCH_QUEUED_STATUS)
                .order_by(SinglePromptSourcePreparation.id.asc())
                .first()
            )
            if preparation:
                identity = preparation.preparation_id
                work_type = "source"
            else:
                diagnosis = (
                    db.query(SinglePromptDiagnosisExecution)
                    .filter(SinglePromptDiagnosisExecution.status.in_(["QUEUED", "EVIDENCE_QUEUED"]))
                    .order_by(SinglePromptDiagnosisExecution.id.asc())
                    .first()
                )
                if not diagnosis:
                    return None
                identity = diagnosis.diagnosis_id
                work_type = "evidence" if diagnosis.status == "EVIDENCE_QUEUED" else "answer"
    finally:
        db.close()

    if work_type == "run_retry":
        db = ReleaseSessionLocal()
        executor = MonitoringTaskExecutor()
        try:
            task = db.get(BrowserMonitorTask, identity)
            if not task or task.status != "queued":
                return None
            task.status = "running"
            db.commit()
            executor.execute_queued_runs(db, task.id)
            update_task_status_from_runs(db, task)
        finally:
            executor.close()
            db.close()
        return f"run_retry:{identity}"
    if work_type == "analysis":
        # The release acceptance path retains successful planned Runs and lets
        # the operator explicitly retry failures before freezing the Context.
        execute_analysis(
            identity,
            freeze_with_failures=False,
            session_factory=ReleaseSessionLocal,
        )
        return f"analysis:{identity}"
    if work_type == "source":
        execute_auto_fetch(identity, session_factory=ReleaseSessionLocal)
        return f"source:{identity}"
    if work_type == "evidence":
        execute_queued_evidence(identity, session_factory=ReleaseSessionLocal)
        return f"evidence:{identity}"
    execute_diagnosis(identity, session_factory=ReleaseSessionLocal)
    return f"answer:{identity}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the single-concurrency GEO 1.0 release worker.")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-idle-passes", type=int, default=0)
    args = parser.parse_args()
    print({"release_database": validate_release_database(release_engine), "worker_concurrency": 1})
    idle_passes = 0
    while True:
        completed = run_once()
        print({"completed": completed or "IDLE"})
        if args.once:
            return
        idle_passes = 0 if completed else idle_passes + 1
        if args.max_idle_passes and idle_passes >= args.max_idle_passes:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
