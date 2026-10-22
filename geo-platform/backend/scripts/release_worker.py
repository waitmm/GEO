"""Single-concurrency business worker for the GEO 1.0 release control plane."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.release_database import ReleaseSessionLocal, release_engine
from app.core.release_worker_lifecycle import worker_ownership
from app.models import (
    AgentCheckpoint,
    AgentExperimentRun,
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
from app.services.serialization import loads
from app.services.internal_beta_model_budget import hooks_for_run
from app.modules.single_prompt_v2.scheduling import (allow_collection_start, allow_scheduled_start,
                                                      sync_execution_audit, tick)
from app.modules.single_prompt_v2.automatic_delivery import execute_task, recover_interrupted_tasks
from app.modules.single_prompt_v2.supplemental_sources import execute_source, recover_interrupted_sources
from app.modules.agent_experiment.runner import execute_agent_run


def recover_interrupted_agent_runs(db) -> int:
    rows = db.query(AgentExperimentRun).filter_by(status="RUNNING").order_by(AgentExperimentRun.id).all()
    for row in rows:
        checkpoint = db.query(AgentCheckpoint).filter_by(agent_run_id=row.run_id).first()
        progress = loads(row.progress_json, {})
        if progress.get("external_request_state") == "RESERVED_IN_FLIGHT":
            row.status = "FAILED"
            row.blocker_code = "AGENT_EXTERNAL_USAGE_UNCERTAIN"
            row.blocker_detail = "worker 在已预留外部请求期间中断；用量未知，不自动重试"
            row.finished_at = datetime.utcnow()
        elif checkpoint and not row.cancel_requested_at:
            row.status = "QUEUED"
            row.blocker_code = ""
            row.blocker_detail = ""
        else:
            row.status = "CANCELLED" if row.cancel_requested_at else "FAILED"
            row.blocker_code = "AGENT_WORKER_INTERRUPTED_NO_CHECKPOINT" if not row.cancel_requested_at else ""
            row.blocker_detail = "worker 中断且没有可恢复 checkpoint" if not row.cancel_requested_at else ""
            row.finished_at = datetime.utcnow()
        row.revision += 1
    if rows:
        db.commit()
    return len(rows)


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


def recover_interrupted_collection_tasks(db) -> int:
    """Preserve uncertain scheduled sampling attempts and never replay them."""
    tasks = db.query(BrowserMonitorTask).filter_by(
        schedule_type="collection_only_schedule", status="running",
    ).order_by(BrowserMonitorTask.id).all()
    for task in tasks:
        task.status = "interrupted"
        for run in db.query(BrowserMonitorRun).filter(
                BrowserMonitorRun.task_id == task.id,
                BrowserMonitorRun.status.in_(["queued", "running"]),
        ).all():
            run.status = "failed"
            run.stage = "failed"
            run.error_type = "worker_restart_delivery_unknown"
            run.error_message = "采集 worker 重启，外部请求送达状态未知；未自动重试。"
            run.finished_at = datetime.utcnow()
    if tasks:
        db.commit()
        sync_execution_audit(db)
    return len(tasks)


def recover_owned_tasks():
    from app.modules.single_prompt_v2.service import recover_interrupted_analyses
    from app.modules.single_prompt_v2.diagnosis import recover_interrupted_diagnoses
    from app.modules.single_prompt_v2.citation_contribution import recover_interrupted_citation_contributions
    from app.modules.single_prompt_v2.qualification_critic import recover_interrupted_qualification_critics
    from app.modules.single_prompt_v2.source_preparation import recover_interrupted_source_preparations
    db = ReleaseSessionLocal()
    try:
        for recover in (recover_interrupted_run_retries, recover_interrupted_collection_tasks, recover_interrupted_tasks,
                        recover_interrupted_agent_runs,
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
        collection_task = (
            db.query(BrowserMonitorTask)
            .filter_by(schedule_type="collection_only_schedule", status="queued")
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
        agent_experiment = db.query(AgentExperimentRun).filter_by(status="QUEUED").order_by(AgentExperimentRun.id).first()
        supplemental = db.query(SupplementalSourceAcquisition).filter_by(status="QUEUED").order_by(SupplementalSourceAcquisition.id).first()
        if retry_task:
            identity = retry_task.id
            work_type = "run_retry"
        elif collection_task:
            if not allow_collection_start(db, collection_task):
                return f"collection_cancelled:{collection_task.id}"
            identity = collection_task.id
            work_type = "collection_only"
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
        elif agent_experiment:
            identity = agent_experiment.run_id
            work_type = "agent_experiment"
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
    if work_type == "agent_experiment":
        probe = ReleaseSessionLocal()
        try:
            row = probe.query(AgentExperimentRun).filter_by(run_id=identity).one()
            authorization = loads(row.authorization_json, {})
            hooks = hooks_for_run(row) if authorization.get("mode") == "EXTERNAL_ALLOWED" else None
        finally:
            probe.close()
        if hooks is None:
            execute_agent_run(identity, session_factory=ReleaseSessionLocal)
        else:
            execute_agent_run(
                identity, session_factory=ReleaseSessionLocal,
                shared_budget_hooks=hooks,
            )
        return f"agent_experiment:{identity}"
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
    if work_type == "collection_only":
        db = ReleaseSessionLocal()
        executor = MonitoringTaskExecutor()
        try:
            task = db.get(BrowserMonitorTask, identity)
            if not task or task.status not in {"queued", "running"}:
                return None
            task.status = "running"
            db.commit()
            executor.execute_queued_runs(db, task.id)
            update_task_status_from_runs(db, task)
            sync_execution_audit(db)
        finally:
            executor.close()
            db.close()
        return f"collection_only:{identity}"
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
