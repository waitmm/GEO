"""Single-concurrency business worker for the GEO 1.0 release control plane."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.release_database import ReleaseSessionLocal, release_engine
from app.core.release_worker_lifecycle import worker_ownership
from app.models import (
    BrowserMonitorRun,
    BrowserMonitorTask,
    SinglePromptAnalysis,
    SinglePromptCitationContributionExecution,
    SinglePromptDiagnosisExecution,
    SinglePromptQualificationCriticExecution,
    SinglePromptSourcePreparation,
    SinglePromptOptimizationTask,
    SupplementalSourceAcquisition,
)
from app.modules.monitoring.executor import MonitoringTaskExecutor
from app.modules.monitoring.services import update_task_status_from_runs
from app.modules.single_prompt_v2.diagnosis import execute_diagnosis, execute_queued_evidence
from app.modules.single_prompt_v2.citation_contribution import execute_citation_contribution
from app.modules.single_prompt_v2.qualification_critic import execute_qualification_critic
from app.modules.single_prompt_v2.service import execute_analysis
from app.modules.single_prompt_v2.source_preparation import AUTO_FETCH_QUEUED_STATUS, execute_auto_fetch
from app.release_schema import validate_release_database
from app.modules.single_prompt_v2.scheduling import tick, allow_scheduled_start
from app.modules.single_prompt_v2.automatic_delivery import execute_task, recover_interrupted_tasks
from app.modules.single_prompt_v2.supplemental_sources import execute_source, recover_interrupted_sources


def recover_interrupted_run_retries(db) -> int:
    """Fail closed after a retry worker dies; never replay an uncertain browser call."""
    tasks = db.query(BrowserMonitorTask).filter_by(
        schedule_type="single_prompt_v2_run_retry", status="running",
    ).order_by(BrowserMonitorTask.id).all()
    for task in tasks:
        task.status = "failed"
        for run in db.query(BrowserMonitorRun).filter(
                BrowserMonitorRun.task_id == task.id,
                BrowserMonitorRun.status.in_(["queued", "running"]),
        ).all():
            run.status = "failed"
            run.stage = "failed"
            run.error_type = "worker_restart_interrupted"
            run.error_message = "发布 worker 进程中断；本次用量未知，未自动重试。"
    if tasks:
        db.commit()
    return len(tasks)


def recover_owned_tasks():
    from app.modules.single_prompt_v2.service import recover_interrupted_analyses
    from app.modules.single_prompt_v2.diagnosis import recover_interrupted_diagnoses
    from app.modules.single_prompt_v2.citation_contribution import recover_interrupted_citation_contributions
    from app.modules.single_prompt_v2.qualification_critic import recover_interrupted_qualification_critics
    from app.modules.single_prompt_v2.source_preparation import recover_interrupted_source_preparations
    db = ReleaseSessionLocal()
    try:
        for recover in (recover_interrupted_run_retries, recover_interrupted_tasks,
                        recover_interrupted_analyses, recover_interrupted_diagnoses,
                        recover_interrupted_citation_contributions, recover_interrupted_qualification_critics,
                        recover_interrupted_source_preparations, recover_interrupted_sources):
            recover(db)
    finally:
        db.close()


def run_once() -> str | None:
    db = ReleaseSessionLocal()
    try:
        tick(db)
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
        optimization = db.query(SinglePromptOptimizationTask).filter_by(status="QUEUED").order_by(SinglePromptOptimizationTask.id).first()
        supplemental = db.query(SupplementalSourceAcquisition).filter_by(status="QUEUED").order_by(SupplementalSourceAcquisition.id).first()
        if retry_task:
            identity = retry_task.id
            work_type = "run_retry"
        elif analysis:
            if not allow_scheduled_start(db, analysis):
                return f"schedule_cancelled:{analysis.analysis_id}"
            identity = analysis.analysis_id
            work_type = "analysis"
            task = db.get(BrowserMonitorTask, analysis.task_id)
            scheduled = bool(task and task.schedule_type == "single_prompt_v2_schedule")
        elif optimization:
            identity = optimization.task_id
            work_type = "automatic_optimize"
        elif supplemental:
            identity = supplemental.source_id
            work_type = "supplemental_source"
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
                if diagnosis:
                    identity = diagnosis.diagnosis_id
                    work_type = "evidence" if diagnosis.status == "EVIDENCE_QUEUED" else "answer"
                else:
                    contribution = (
                        db.query(SinglePromptCitationContributionExecution)
                        .filter_by(status="QUEUED")
                        .order_by(SinglePromptCitationContributionExecution.id.asc())
                        .first()
                    )
                    if not contribution:
                        critic = (
                            db.query(SinglePromptQualificationCriticExecution)
                            .filter_by(status="QUEUED")
                            .order_by(SinglePromptQualificationCriticExecution.id.asc())
                            .first()
                        )
                        if not critic:
                            return None
                        identity = critic.critic_id
                        work_type = "qualification_critic"
                    else:
                        identity = contribution.contribution_id
                        work_type = "citation_contribution"
    finally:
        db.close()

    if work_type == "supplemental_source":
        execute_source(identity, session_factory=ReleaseSessionLocal)
        return f"supplemental_source:{identity}"
    if work_type == "automatic_optimize":
        execute_task(identity, session_factory=ReleaseSessionLocal)
        return f"automatic_optimize:{identity}"
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
            freeze_with_failures=scheduled,
            session_factory=ReleaseSessionLocal,
        )
        return f"analysis:{identity}"
    if work_type == "source":
        execute_auto_fetch(identity, session_factory=ReleaseSessionLocal)
        return f"source:{identity}"
    if work_type == "evidence":
        execute_queued_evidence(identity, session_factory=ReleaseSessionLocal)
        return f"evidence:{identity}"
    if work_type == "citation_contribution":
        execute_citation_contribution(identity, session_factory=ReleaseSessionLocal)
        return f"citation_contribution:{identity}"
    if work_type == "qualification_critic":
        execute_qualification_critic(identity, session_factory=ReleaseSessionLocal)
        return f"qualification_critic:{identity}"
    execute_diagnosis(identity, session_factory=ReleaseSessionLocal)
    return f"answer:{identity}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the single-concurrency GEO 1.0 release worker.")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-idle-passes", type=int, default=0)
    args = parser.parse_args()
    print({"release_database": validate_release_database(release_engine), "worker_concurrency": 1})
    with worker_ownership(release_engine):
        recover_owned_tasks()
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
