from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.optimization.schemas import (
    ActionReleasePayload,
    EvidencePackageCreate,
    EvidencePackageRead,
    ExperimentConclusionPayload,
    ExperimentRetestCreate,
    ExperimentRetestRead,
    ExperimentRunsPayload,
    IssueStatusPayload,
    OptimizationActionCreate,
    OptimizationActionRead,
    OptimizationActionUpdate,
    OptimizationEvidenceChainRead,
    OptimizationExperimentCreate,
    OptimizationExperimentRead,
    OptimizationHypothesisCreate,
    OptimizationHypothesisRead,
    OptimizationIssueCreate,
    OptimizationIssueRead,
    PageSnapshotCreate,
    PageSnapshotRead,
    ReleaseAuditRead,
    ReleaseConfirmationPayload,
    StrategyCandidateRead,
    StrategyCandidateReviewPayload,
    StrategyGenerationCreate,
    ExperimentPlanRead,
)
from app.modules.optimization.service import (
    action_to_read,
    analyze_experiment,
    attach_validation_runs,
    capture_page_snapshot,
    confirm_conclusion,
    confirm_experiment_release,
    confirm_issue,
    create_action,
    create_evidence_package,
    create_experiment,
    create_hypothesis,
    create_issue,
    evidence_chain,
    evidence_package_to_read,
    experiment_to_read,
    generate_candidate_issues,
    generate_strategy_candidates,
    generate_strategy_candidates_v2,
    get_evidence_package,
    issue_to_read,
    list_evidence_packages,
    list_hypotheses,
    list_issue_reads,
    list_page_snapshots,
    list_strategy_candidates,
    lock_baseline,
    page_snapshot_to_read,
    hypothesis_to_read,
    queue_retest_task,
    reject_issue,
    release_action,
    review_strategy_candidate,
    start_validation,
    strategy_to_experiment_plan,
    update_action,
)
from app.modules.optimization.ranking import run_citation_evidence_ranking_v0


router = APIRouter(prefix="/api/optimization", tags=["optimization"])


@router.get("/projects/{project_id}/issues", response_model=list[OptimizationIssueRead])
def list_issues(project_id: int, db: Session = Depends(get_db)) -> list[dict]:
    return list_issue_reads(db, project_id)


@router.get("/projects/{project_id}/evidence-packages", response_model=list[EvidencePackageRead])
def list_project_evidence_packages(project_id: int, prompt_id: int | None = None, db: Session = Depends(get_db)) -> list[dict]:
    return list_evidence_packages(db, project_id, prompt_id)


@router.post("/projects/{project_id}/evidence-packages", response_model=EvidencePackageRead)
def create_project_evidence_package(project_id: int, payload: EvidencePackageCreate, db: Session = Depends(get_db)) -> dict:
    return evidence_package_to_read(db, create_evidence_package(db, project_id, payload))


@router.get("/projects/{project_id}/strategy-candidates", response_model=list[StrategyCandidateRead])
def list_project_strategy_candidates(
    project_id: int,
    experiment_id: int | None = None,
    evidence_package_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_strategy_candidates(db, project_id, experiment_id, evidence_package_id)


@router.post("/projects/{project_id}/strategy-candidates/generate", response_model=list[StrategyCandidateRead])
def generate_project_strategy_candidates(project_id: int, payload: StrategyGenerationCreate, db: Session = Depends(get_db)) -> list[dict]:
    return generate_strategy_candidates(db, project_id, payload)


@router.post("/projects/{project_id}/strategy-candidates/generate-v2")
def generate_project_strategy_candidates_v2(project_id: int, payload: StrategyGenerationCreate, db: Session = Depends(get_db)):
    return generate_strategy_candidates_v2(db, project_id, payload)


@router.post("/strategy-candidates/{candidate_id}/review", response_model=StrategyCandidateRead)
def review_strategy_candidate_endpoint(candidate_id: int, payload: StrategyCandidateReviewPayload, db: Session = Depends(get_db)) -> dict:
    return review_strategy_candidate(db, candidate_id, payload)


@router.post("/strategy-candidates/{candidate_id}/experiment-plan", response_model=ExperimentPlanRead)
def strategy_to_experiment_plan_endpoint(candidate_id: int, db: Session = Depends(get_db)) -> dict:
    return strategy_to_experiment_plan(db, candidate_id)


@router.get("/evidence-packages/{package_id}", response_model=EvidencePackageRead)
def get_project_evidence_package(package_id: int, db: Session = Depends(get_db)) -> dict:
    return get_evidence_package(db, package_id)


@router.get("/projects/{project_id}/page-snapshots", response_model=list[PageSnapshotRead])
def list_project_page_snapshots(project_id: int, experiment_id: int | None = None, db: Session = Depends(get_db)) -> list[dict]:
    return list_page_snapshots(db, project_id, experiment_id)


@router.post("/projects/{project_id}/page-snapshots", response_model=PageSnapshotRead)
def capture_project_page_snapshot(project_id: int, payload: PageSnapshotCreate, db: Session = Depends(get_db)) -> dict:
    return page_snapshot_to_read(capture_page_snapshot(db, project_id, payload))


@router.post("/projects/{project_id}/issues/generate-candidates", response_model=list[OptimizationIssueRead])
def generate_issues(project_id: int, db: Session = Depends(get_db)) -> list[dict]:
    issues = generate_candidate_issues(db, project_id)
    return [issue_to_read(issue) for issue in issues]


@router.post("/issues", response_model=OptimizationIssueRead)
def create_manual_issue(payload: OptimizationIssueCreate, db: Session = Depends(get_db)) -> dict:
    issue = create_issue(db, payload)
    row = issue_to_read(issue)
    row["run_ids"] = payload.run_ids
    return row


@router.get("/issues/{issue_id}", response_model=OptimizationIssueRead)
def get_issue(issue_id: int, db: Session = Depends(get_db)) -> dict:
    return evidence_chain(db, issue_id)["issue"]


@router.post("/issues/{issue_id}/confirm", response_model=OptimizationIssueRead)
def confirm_issue_endpoint(issue_id: int, db: Session = Depends(get_db)) -> dict:
    issue = confirm_issue(db, issue_id)
    return evidence_chain(db, issue.id)["issue"]


@router.post("/issues/{issue_id}/reject", response_model=OptimizationIssueRead)
def reject_issue_endpoint(issue_id: int, payload: IssueStatusPayload, db: Session = Depends(get_db)) -> dict:
    issue = reject_issue(db, issue_id, payload.note)
    return evidence_chain(db, issue.id)["issue"]


@router.post("/issues/{issue_id}/actions", response_model=OptimizationActionRead)
def create_action_endpoint(issue_id: int, payload: OptimizationActionCreate, db: Session = Depends(get_db)) -> dict:
    return action_to_read(create_action(db, issue_id, payload))


@router.patch("/actions/{action_id}", response_model=OptimizationActionRead)
def update_action_endpoint(action_id: int, payload: OptimizationActionUpdate, db: Session = Depends(get_db)) -> dict:
    return action_to_read(update_action(db, action_id, payload))


@router.post("/actions/{action_id}/release", response_model=OptimizationActionRead)
def release_action_endpoint(action_id: int, payload: ActionReleasePayload, db: Session = Depends(get_db)) -> dict:
    return action_to_read(release_action(db, action_id, payload))


@router.post("/actions/{action_id}/experiments", response_model=OptimizationExperimentRead)
def create_experiment_endpoint(action_id: int, payload: OptimizationExperimentCreate, db: Session = Depends(get_db)) -> dict:
    return experiment_to_read(create_experiment(db, action_id, payload))


@router.get("/experiments/{experiment_id}/hypotheses", response_model=list[OptimizationHypothesisRead])
def list_experiment_hypotheses(experiment_id: int, db: Session = Depends(get_db)) -> list[dict]:
    return list_hypotheses(db, experiment_id)


@router.post("/experiments/{experiment_id}/hypotheses", response_model=OptimizationHypothesisRead)
def create_experiment_hypothesis(experiment_id: int, payload: OptimizationHypothesisCreate, db: Session = Depends(get_db)) -> dict:
    return hypothesis_to_read(create_hypothesis(db, experiment_id, payload))


@router.post("/experiments/{experiment_id}/lock-baseline", response_model=OptimizationExperimentRead)
def lock_baseline_endpoint(experiment_id: int, payload: ExperimentRunsPayload, db: Session = Depends(get_db)) -> dict:
    return experiment_to_read(lock_baseline(db, experiment_id, payload.run_ids))


@router.post("/experiments/{experiment_id}/start-validation", response_model=OptimizationExperimentRead)
def start_validation_endpoint(experiment_id: int, db: Session = Depends(get_db)) -> dict:
    return experiment_to_read(start_validation(db, experiment_id))


@router.post("/experiments/{experiment_id}/release-confirmation", response_model=OptimizationExperimentRead)
def confirm_release_endpoint(experiment_id: int, payload: ReleaseConfirmationPayload, db: Session = Depends(get_db)) -> dict:
    return experiment_to_read(confirm_experiment_release(db, experiment_id, payload))


@router.post("/experiments/{experiment_id}/queue-retest", response_model=ExperimentRetestRead)
def queue_retest_endpoint(experiment_id: int, payload: ExperimentRetestCreate, db: Session = Depends(get_db)) -> dict:
    return queue_retest_task(db, experiment_id, payload)


@router.post("/experiments/{experiment_id}/attach-validation-runs", response_model=OptimizationExperimentRead)
def attach_validation_runs_endpoint(experiment_id: int, payload: ExperimentRunsPayload, db: Session = Depends(get_db)) -> dict:
    return experiment_to_read(attach_validation_runs(db, experiment_id, payload.run_ids))


@router.post("/experiments/{experiment_id}/analyze", response_model=OptimizationExperimentRead)
def analyze_experiment_endpoint(experiment_id: int, db: Session = Depends(get_db)) -> dict:
    return experiment_to_read(analyze_experiment(db, experiment_id))


@router.post("/experiments/{experiment_id}/confirm-conclusion", response_model=OptimizationExperimentRead)
def confirm_conclusion_endpoint(experiment_id: int, payload: ExperimentConclusionPayload, db: Session = Depends(get_db)) -> dict:
    return experiment_to_read(confirm_conclusion(db, experiment_id, payload))


@router.get("/issues/{issue_id}/evidence-chain", response_model=OptimizationEvidenceChainRead)
def evidence_chain_endpoint(issue_id: int, db: Session = Depends(get_db)) -> dict:
    return evidence_chain(db, issue_id)


@router.get("/evidence-packages/{package_id}/citation-ranking")
def citation_evidence_ranking_endpoint(package_id: int, db: Session = Depends(get_db)):
    return run_citation_evidence_ranking_v0(db, package_id)
