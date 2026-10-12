"""First-slice API without imports from later V2 or legacy workflow runners."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, Request
from sqlalchemy.orm import Session

from app.core.release_database import ReleaseSessionLocal, get_release_db
from app.modules.single_prompt_v2.execution import (
    confirm_execution_proposal,
    create_execution_proposal,
    generate_complete_execution_deliverable,
    get_execution_proposal_status,
    record_publication,
    revise_execution_proposal,
)
from app.modules.single_prompt_v2.retest import (
    build_retest_readiness,
    create_comparison,
    create_retest,
    execute_retest_sampling,
    execute_semantic_measurement,
    finalize_retest_with_failures,
    get_retest_status,
    retry_retest_sampling,
    start_retest_sampling,
    start_semantic_measurement,
)
from app.modules.single_prompt_v2.citation_contribution import (
    authorize_citation_contribution,
    complete_citation_contribution_review,
    create_citation_contribution_plan,
    get_citation_contribution_status,
    list_citation_contributions,
    materialize_compatible_citation_contribution,
)
from app.modules.single_prompt_v2.diagnosis import (
    complete_diagnosis_review,
    create_answer_diagnosis,
    get_diagnosis_status,
    queue_evidence_continuation,
    record_target_brand_truth,
    reproject_target_brand_truths,
    retry_diagnosis,
    revise_diagnosis_result,
)
from app.modules.single_prompt_v2.schemas import (
    TruthCorrectionPreview, TruthCorrectionCreate, TruthReprojectionCreate,
    AutomaticOptimizationCreate, AutomaticOptimizationAction, AutomaticOptimizationAuthorization, AutomaticDraftRevisionCreate, AutomaticDraftRegenerationCreate,
    SinglePromptAnalysisCreate,
    SinglePromptAutomaticStrategyCreate,
    SinglePromptRunRetryCreate,
    SinglePromptRunSelectionCreate,
    SinglePromptAnswerDiagnosisCreate,
    SinglePromptCitationContributionAuthorizationCreate,
    SinglePromptCitationContributionPlanCreate,
    SinglePromptCitationContributionReuseCreate,
    SinglePromptCitationContributionReviewCreate,
    SinglePromptQualificationCriticCreate,
    SinglePromptQualificationCriticGoldReviewCreate,
    SinglePromptQualificationCriticSupplementalCreate,
    SinglePromptDiagnosisReviewCreate,
    SinglePromptDiagnosisRevisionCreate,
    SinglePromptEvidenceContinuationCreate,
    SinglePromptExecutionConfirmationCreate,
    SinglePromptExecutionDeliverableCreate,
    SinglePromptExecutionProposalCreate,
    SinglePromptExecutionProposalRevisionCreate,
    SinglePromptManualSourceContentCreate,
    SinglePromptSourceCompletionCreate,
    SinglePromptSourceAutoFetchCreate,
    SinglePromptSourceReuseCreate,
    SinglePromptSourcePreparationCreate,
    SinglePromptSourceWaiverCreate,
    SinglePromptPublicationCreate,
    SinglePromptRetestAction,
    SinglePromptRetestCreate,
    SinglePromptSemanticMeasurementCreate,
    SinglePromptStrategyCreate,
    SinglePromptStrategyPriorityRevisionCreate,
    SinglePromptStrategyReviewCreate,
    SinglePromptTargetBrandTruthCreate,
    SinglePromptTruthReprojectionCreate,
)
from app.modules.single_prompt_v2.service import (
    create_analysis,
    create_analysis_from_runs,
    get_analysis_status,
    list_prompt_run_pool,
    list_analysis_statuses,
    queue_run_retry,
    retry_analysis,
)
from app.modules.single_prompt_v2.strategy import (
    build_strategy_readiness,
    complete_strategy_review,
    create_strategy_candidate,
    create_automatic_strategy_candidate,
    get_strategy_status,
    revise_strategy_priority,
)
from app.modules.single_prompt_v2.qualification import build_qualification_projection
from app.modules.single_prompt_v2.qualification_critic import (
    get_qualification_critic_status,
    queue_qualification_critic,
    queue_qualification_critic_supplemental,
)
from app.modules.single_prompt_v2.qualification_critic_gold import (
    build_critic_gold_review_set,
    complete_critic_gold_review,
)
from app.modules.single_prompt_v2.source_preparation import (
    create_source_preparation,
    freeze_completion_manifest,
    get_source_preparation_for_analysis,
    get_source_preparation_status,
    queue_auto_fetch,
    reuse_completed_sources,
    submit_manual_content,
    waive_source,
)


router = APIRouter(prefix="/api/v2/single-prompt", tags=["single-prompt-v2-release"])
get_db = get_release_db

@router.get("/optimization-tasks/{task_id}/truths")
def read_task_truths(task_id: str, project_id: int, prompt_id: int, db: Session = Depends(get_db)):
    from .truth_corrections import task_truths
    return task_truths(db, parent_task_id=task_id, project_id=project_id, prompt_id=prompt_id)


@router.post("/optimization-tasks/{task_id}/truth-corrections/preview")
def preview_task_truth_correction(task_id: str, payload: TruthCorrectionPreview, db: Session = Depends(get_db)):
    from .truth_corrections import preview_correction
    return preview_correction(db, parent_task_id=task_id, **payload.model_dump())


@router.post("/optimization-tasks/{task_id}/truth-corrections", status_code=201)
def save_task_truth_correction(task_id: str, payload: TruthCorrectionCreate,
                               request: Request, response: Response, db: Session = Depends(get_db)):
    from .truth_corrections import correct_truth, correction_view
    from .automatic_delivery import require_task
    from app.core.release_access import principal
    require_task(db, task_id, payload.project_id, payload.prompt_id)
    row, created = correct_truth(db, parent_task_id=task_id, actor=principal(request)['name'],
        **payload.model_dump(exclude={'human_confirmed'}))
    if not created:
        response.status_code = 200
    return correction_view(row)


@router.post('/optimization-tasks/{task_id}/truth-reprojections', status_code=201)
def queue_truth_reprojection(task_id: str, payload: TruthReprojectionCreate,
                             response: Response, db: Session = Depends(get_db)):
    from .truth_corrections import create_reprojection_task
    from .automatic_delivery import task_view
    row, created = create_reprojection_task(db, parent_task_id=task_id, **payload.model_dump())
    if not created:
        response.status_code = 200
    return task_view(row)


@router.post("/analyses/{analysis_id}/optimization-tasks", status_code=201)
def queue_automatic_optimization(analysis_id: str, payload: AutomaticOptimizationCreate,
                                 response: Response, db: Session = Depends(get_db)) -> dict:
    from .automatic_delivery import create_task, task_view
    row, created = create_task(db, analysis_id=analysis_id, **payload.model_dump())
    if not created:
        response.status_code = 200
    return task_view(row)


@router.get("/analyses/{analysis_id}/optimization-tasks")
def list_automatic_optimization(analysis_id: str, project_id: int, prompt_id: int, db: Session = Depends(get_db)) -> list[dict]:
    from app.models import SinglePromptAnalysis, SinglePromptOptimizationTask
    from .automatic_delivery import task_view
    if not db.query(SinglePromptAnalysis).filter_by(analysis_id=analysis_id, project_id=project_id, prompt_id=prompt_id).one_or_none():
        raise HTTPException(404, "分析不存在或不属于当前项目/问题")
    return [task_view(row) for row in db.query(SinglePromptOptimizationTask).filter_by(
        analysis_id=analysis_id, project_id=project_id, prompt_id=prompt_id).order_by(SinglePromptOptimizationTask.id.desc())]


@router.get("/optimization-tasks/{task_id}")
def read_automatic_optimization(task_id: str, project_id: int, prompt_id: int, db: Session = Depends(get_db)) -> dict:
    from .automatic_delivery import require_task, task_view
    return task_view(require_task(db, task_id, project_id, prompt_id))


@router.get("/optimization-tasks/{task_id}/deliveries")
def read_automatic_deliveries(task_id: str, project_id: int, prompt_id: int, db: Session = Depends(get_db)) -> list[dict]:
    from .automatic_delivery import require_task
    from app.models import SinglePromptExecutionProposal, SinglePromptExecutionProposalResult
    from app.services.serialization import loads
    from .delivery_text import digest
    task = require_task(db, task_id, project_id, prompt_id)
    objects = loads(task.progress_json, {}).get("objects") or {}
    result = []
    for binding in objects.get("deliveries") or []:
        proposal = db.query(SinglePromptExecutionProposal).filter_by(proposal_id=binding["proposal_id"],
            project_id=project_id, prompt_id=prompt_id, analysis_id=task.analysis_id, context_id=task.context_id).one_or_none()
        if not proposal:
            raise HTTPException(409, "自动任务稿件归属不一致")
        value = db.query(SinglePromptExecutionProposalResult).filter_by(proposal_id=proposal.proposal_id,
            result_version=binding["result_version"], output_hash=binding["result_hash"]).one_or_none()
        if not value or digest(loads(value.output_json, {})) != value.output_hash:
            raise HTTPException(409, "自动任务稿件版本或 hash 不一致")
        output = loads(value.output_json, {})
        from .delivery_generation import editable_draft
        result.append({**binding, "output": output,
            "editable_draft": editable_draft(output["generation_receipt"]) if output.get("generation_receipt") else None})
    return result


@router.post("/optimization-tasks/{task_id}/authorization")
def authorize_automatic_optimization(task_id: str, payload: AutomaticOptimizationAuthorization,
                                     request: Request, db: Session = Depends(get_db)) -> dict:
    from .automatic_delivery import require_task, authorize_task, task_view
    from app.core.release_access import principal
    row = require_task(db, task_id, payload.project_id, payload.prompt_id)
    return task_view(authorize_task(db, row, **payload.model_dump(exclude={"project_id", "prompt_id"}),
        authorized_by=principal(request)["name"]))


@router.post("/optimization-tasks/{task_id}/draft-revisions", status_code=201)
def queue_draft_revision(task_id: str, payload: AutomaticDraftRevisionCreate,
                         request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    from .delivery_revision import create_revision_task
    from .automatic_delivery import task_view
    from app.core.release_access import principal
    row, created = create_revision_task(db, parent_task_id=task_id, **payload.model_dump(), editor=principal(request)["name"])
    if not created:
        response.status_code = 200
    return task_view(row)


@router.post("/optimization-tasks/{task_id}/draft-regenerations", status_code=201)
def queue_draft_regeneration(task_id: str, payload: AutomaticDraftRegenerationCreate,
                             request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    from .delivery_revision import create_revision_task
    from .automatic_delivery import task_view
    from app.core.release_access import principal
    row, created = create_revision_task(db, parent_task_id=task_id, **payload.model_dump(),
        editor=principal(request)["name"], regenerate=True)
    if not created:
        response.status_code = 200
    return task_view(row)


@router.post("/optimization-tasks/{task_id}/cancel")
def cancel_automatic_optimization(task_id: str, payload: AutomaticOptimizationAction, db: Session = Depends(get_db)) -> dict:
    from .automatic_delivery import require_task, cancel_task, task_view
    return task_view(cancel_task(db, require_task(db, task_id, payload.project_id, payload.prompt_id), payload.expected_revision))


@router.post("/optimization-tasks/{task_id}/resume")
def resume_automatic_optimization(task_id: str, payload: AutomaticOptimizationAction, db: Session = Depends(get_db)) -> dict:
    from .automatic_delivery import require_task, resume_task, task_view
    return task_view(resume_task(db, require_task(db, task_id, payload.project_id, payload.prompt_id), payload.expected_revision))


@router.post("/analyses/{analysis_id}/citation-contributions", status_code=201)
def plan_citation_contribution(
    analysis_id: str,
    payload: SinglePromptCitationContributionPlanCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    execution, created = create_citation_contribution_plan(
        db,
        analysis_id=analysis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        answer_result_version=payload.answer_result_version,
        answer_result_hash=payload.answer_result_hash,
        answer_review_id=payload.answer_review_id,
        input_authority=payload.input_authority,
        selected_run_id=payload.selected_run_id,
        citation_manifest_id=payload.citation_manifest_id,
        citation_manifest_hash=payload.citation_manifest_hash,
        completion_manifest_id=payload.completion_manifest_id,
        completion_manifest_hash=payload.completion_manifest_hash,
        fixed_run_ids=payload.fixed_run_ids,
        idempotency_key=payload.idempotency_key,
    )
    if not created:
        response.status_code = 200
    return get_citation_contribution_status(
        db,
        analysis_id=analysis_id,
        contribution_id=execution.contribution_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.post("/analyses/{analysis_id}/citation-contributions/materializations", status_code=201)
def materialize_citation_contribution(
    analysis_id: str,
    payload: SinglePromptCitationContributionReuseCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    execution, created = materialize_compatible_citation_contribution(
        db,
        analysis_id=analysis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        source_contribution_id=payload.source_contribution_id,
        source_result_version=payload.source_result_version,
        source_result_hash=payload.source_result_hash,
        answer_result_version=payload.answer_result_version,
        answer_result_hash=payload.answer_result_hash,
        citation_manifest_id=payload.citation_manifest_id,
        citation_manifest_hash=payload.citation_manifest_hash,
        completion_manifest_id=payload.completion_manifest_id,
        completion_manifest_hash=payload.completion_manifest_hash,
        fixed_run_ids=payload.fixed_run_ids,
        idempotency_key=payload.idempotency_key,
    )
    if not created:
        response.status_code = 200
    return get_citation_contribution_status(
        db,
        analysis_id=analysis_id,
        contribution_id=execution.contribution_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.get("/analyses/{analysis_id}/citation-contributions")
def list_analysis_citation_contributions(
    analysis_id: str,
    project_id: int,
    prompt_id: int,
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_citation_contributions(
        db,
        analysis_id=analysis_id,
        project_id=project_id,
        prompt_id=prompt_id,
    )


@router.get("/analyses/{analysis_id}/citation-contributions/{contribution_id}")
def read_citation_contribution(
    analysis_id: str,
    contribution_id: str,
    project_id: int,
    prompt_id: int,
    db: Session = Depends(get_db),
) -> dict:
    return get_citation_contribution_status(
        db,
        analysis_id=analysis_id,
        contribution_id=contribution_id,
        project_id=project_id,
        prompt_id=prompt_id,
    )


@router.post("/analyses/{analysis_id}/citation-contributions/{contribution_id}/authorizations", status_code=202)
def authorize_citation_contribution_execution(
    analysis_id: str,
    contribution_id: str,
    payload: SinglePromptCitationContributionAuthorizationCreate,
    db: Session = Depends(get_db),
) -> dict:
    get_citation_contribution_status(
        db,
        analysis_id=analysis_id,
        contribution_id=contribution_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )
    execution = authorize_citation_contribution(
        db,
        contribution_id=contribution_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        plan_hash=payload.plan_hash,
        provider=payload.provider,
        model=payload.model,
        max_external_requests=payload.max_external_requests,
        max_total_tokens=payload.max_total_tokens,
        max_budget_cny=payload.max_budget_cny,
        cost_upper_bound_cny=payload.cost_upper_bound_cny,
        pricing_basis=payload.pricing_basis,
        authorized_by=payload.authorized_by,
    )
    return get_citation_contribution_status(
        db,
        analysis_id=analysis_id,
        contribution_id=execution.contribution_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.post("/analyses/{analysis_id}/citation-contributions/{contribution_id}/results/{result_version}/reviews")
def review_citation_contribution(
    analysis_id: str,
    contribution_id: str,
    result_version: str,
    payload: SinglePromptCitationContributionReviewCreate,
    db: Session = Depends(get_db),
) -> dict:
    get_citation_contribution_status(
        db,
        analysis_id=analysis_id,
        contribution_id=contribution_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )
    complete_citation_contribution_review(
        db,
        contribution_id=contribution_id,
        result_version=result_version,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        result_hash=payload.result_hash,
        reviewable_set_hash=payload.reviewable_set_hash,
        calibration_sample_identity=payload.calibration_sample_identity,
        binding_census_hash=payload.binding_census_hash,
        human_review_set_hash=payload.human_review_set_hash,
        reviewer=payload.reviewer,
        decisions=[item.model_dump() for item in payload.decisions],
        missed_bindings=[item.model_dump() for item in payload.missed_bindings],
        note=payload.note,
    )
    return get_citation_contribution_status(
        db,
        analysis_id=analysis_id,
        contribution_id=contribution_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.post("/analyses", status_code=202)
def start_analysis(payload: SinglePromptAnalysisCreate, response: Response, db: Session = Depends(get_db)) -> dict:
    analysis, created = create_analysis(
        db,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        sample_count=payload.sample_count,
        idempotency_key=payload.idempotency_key,
    )
    if not created:
        response.status_code = 200
    return get_analysis_status(db, analysis.analysis_id)


@router.get("/runs")
def list_runs(
    project_id: int,
    prompt_id: int,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
) -> dict:
    if page < 1:
        raise HTTPException(status_code=422, detail="page 必须大于等于 1")
    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=422, detail="page_size 必须在 1 到 100 之间")
    return list_prompt_run_pool(
        db,
        project_id=project_id,
        prompt_id=prompt_id,
        page=page,
        page_size=page_size,
    )


@router.post("/analyses/from-runs", status_code=201)
def start_analysis_from_runs(
    payload: SinglePromptRunSelectionCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    analysis, created = create_analysis_from_runs(
        db,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        run_ids=payload.run_ids,
        run_fingerprints=payload.run_fingerprints,
        base_context_id=payload.base_context_id,
        idempotency_key=payload.idempotency_key,
    )
    if not created:
        response.status_code = 200
    return get_analysis_status(db, analysis.analysis_id)


@router.post("/runs/{run_id}/retry", status_code=202)
def retry_single_run(
    run_id: int,
    payload: SinglePromptRunRetryCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    run, created = queue_run_retry(
        db,
        run_id=run_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        idempotency_key=payload.idempotency_key,
    )
    if not created:
        response.status_code = 200
    return {
        "source_run_id": run_id,
        "retry_run_id": run.id,
        "task_id": run.task_id,
        "status": run.status,
        "created": created,
    }


@router.get("/analyses")
def list_analyses(
    project_id: int,
    prompt_id: int,
    limit: int = 20,
    db: Session = Depends(get_db),
) -> list[dict]:
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="limit 必须在 1 到 100 之间")
    return list_analysis_statuses(
        db,
        project_id=project_id,
        prompt_id=prompt_id,
        limit=limit,
    )


@router.get("/analyses/{analysis_id}")
def read_analysis(analysis_id: str, project_id: int, prompt_id: int, db: Session = Depends(get_db)) -> dict:
    status = get_analysis_status(db, analysis_id)
    identity = status["analysis"]
    if identity["project_id"] != project_id or identity["prompt_id"] != prompt_id:
        raise HTTPException(status_code=409, detail="分析身份与当前 Project/Prompt 不匹配")
    return status


@router.post("/analyses/{analysis_id}/retry", status_code=202)
def retry_collection(analysis_id: str, project_id: int, prompt_id: int, db: Session = Depends(get_db)) -> dict:
    read_analysis(analysis_id, project_id, prompt_id, db)
    retry_analysis(db, analysis_id)
    return get_analysis_status(db, analysis_id)


@router.post("/analyses/{analysis_id}/source-preparation", status_code=201)
def start_source_preparation(analysis_id: str, payload: SinglePromptSourcePreparationCreate, response: Response, db: Session = Depends(get_db)) -> dict:
    preparation, created = create_source_preparation(
        db,
        analysis_id=analysis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        idempotency_key=payload.idempotency_key,
        created_by=payload.created_by,
    )
    if not created:
        response.status_code = 200
    return get_source_preparation_status(db, preparation_id=preparation.preparation_id)


@router.get("/analyses/{analysis_id}/source-preparation")
def read_analysis_source_preparation(analysis_id: str, project_id: int, prompt_id: int, db: Session = Depends(get_db)) -> dict | None:
    return get_source_preparation_for_analysis(db, analysis_id=analysis_id, project_id=project_id, prompt_id=prompt_id)


@router.get("/source-preparations/{preparation_id}")
def read_source_preparation(preparation_id: str, project_id: int, prompt_id: int, db: Session = Depends(get_db)) -> dict:
    status = get_source_preparation_status(db, preparation_id=preparation_id)
    _require_preparation_scope(status, project_id, prompt_id)
    return status


def _require_preparation_scope(status: dict, project_id: int, prompt_id: int) -> None:
    identity = status["preparation"]
    if identity["project_id"] != project_id or identity["prompt_id"] != prompt_id:
        raise HTTPException(status_code=409, detail="来源准备与当前 Project/Prompt 不匹配")


@router.post("/source-preparations/{preparation_id}/auto-fetch", status_code=202)
def start_source_auto_fetch(preparation_id: str, payload: SinglePromptSourceAutoFetchCreate, db: Session = Depends(get_db)) -> dict:
    queue_auto_fetch(
        db,
        preparation_id=preparation_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )
    return get_source_preparation_status(db, preparation_id=preparation_id)


@router.post("/source-preparations/{preparation_id}/reuse-completed-sources")
def reuse_source_completion(
    preparation_id: str,
    payload: SinglePromptSourceReuseCreate,
    db: Session = Depends(get_db),
) -> dict:
    reuse_completed_sources(
        db,
        preparation_id=preparation_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        source_completion_manifest_id=payload.source_completion_manifest_id,
        source_completion_manifest_hash=payload.source_completion_manifest_hash,
        reused_by=payload.reused_by,
    )
    return get_source_preparation_status(db, preparation_id=preparation_id)


@router.post("/source-preparations/{preparation_id}/manual-content")
def submit_source_manual_content(preparation_id: str, payload: SinglePromptManualSourceContentCreate, db: Session = Depends(get_db)) -> dict:
    _require_preparation_scope(get_source_preparation_status(db, preparation_id=preparation_id), payload.project_id, payload.prompt_id)
    submit_manual_content(
        db,
        preparation_id=preparation_id,
        source_key=payload.source_key,
        expected_row_version=payload.expected_row_version,
        title=payload.title,
        clean_text=payload.clean_text,
        input_format=payload.input_format,
        raw_html=payload.raw_html,
        coverage_scope=payload.coverage_scope,
        submitted_by=payload.submitted_by,
    )
    return get_source_preparation_status(db, preparation_id=preparation_id)


@router.post("/source-preparations/{preparation_id}/waivers")
def waive_prepared_source(preparation_id: str, payload: SinglePromptSourceWaiverCreate, db: Session = Depends(get_db)) -> dict:
    _require_preparation_scope(get_source_preparation_status(db, preparation_id=preparation_id), payload.project_id, payload.prompt_id)
    waive_source(
        db,
        preparation_id=preparation_id,
        source_key=payload.source_key,
        expected_row_version=payload.expected_row_version,
        reason=payload.reason,
        impact=payload.impact,
        waived_by=payload.waived_by,
    )
    return get_source_preparation_status(db, preparation_id=preparation_id)


@router.post("/source-preparations/{preparation_id}/completion-manifests", status_code=201)
def complete_source_preparation(preparation_id: str, payload: SinglePromptSourceCompletionCreate, db: Session = Depends(get_db)) -> dict:
    _require_preparation_scope(get_source_preparation_status(db, preparation_id=preparation_id), payload.project_id, payload.prompt_id)
    freeze_completion_manifest(db, preparation_id=preparation_id, created_by=payload.created_by)
    return get_source_preparation_status(db, preparation_id=preparation_id)


@router.post("/analyses/{analysis_id}/answer-diagnoses", status_code=202)
def start_answer_diagnosis(analysis_id: str, payload: SinglePromptAnswerDiagnosisCreate, response: Response, db: Session = Depends(get_db)) -> dict:
    execution, created = create_answer_diagnosis(
        db,
        analysis_id=analysis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        citation_manifest_id=payload.citation_manifest_id,
        citation_manifest_hash=payload.citation_manifest_hash,
        answer_llm_policy=payload.answer_llm_policy,
        idempotency_key=payload.idempotency_key,
    )
    if not created:
        response.status_code = 200
    return get_diagnosis_status(db, analysis_id=analysis_id, diagnosis_id=execution.diagnosis_id, project_id=payload.project_id, prompt_id=payload.prompt_id)


@router.get("/analyses/{analysis_id}/diagnoses/{diagnosis_id}")
def read_diagnosis(analysis_id: str, diagnosis_id: str, project_id: int, prompt_id: int, db: Session = Depends(get_db)) -> dict:
    return get_diagnosis_status(db, analysis_id=analysis_id, diagnosis_id=diagnosis_id, project_id=project_id, prompt_id=prompt_id)


@router.post("/analyses/{analysis_id}/diagnoses/{diagnosis_id}/retry", status_code=202)
def retry_diagnosis_execution(analysis_id: str, diagnosis_id: str, project_id: int, prompt_id: int, db: Session = Depends(get_db)) -> dict:
    read_diagnosis(analysis_id, diagnosis_id, project_id, prompt_id, db)
    retry_diagnosis(db, diagnosis_id)
    return read_diagnosis(analysis_id, diagnosis_id, project_id, prompt_id, db)


@router.post("/analyses/{analysis_id}/diagnoses/{diagnosis_id}/results/{result_version}/revisions")
def revise_diagnosis(analysis_id: str, diagnosis_id: str, result_version: str, payload: SinglePromptDiagnosisRevisionCreate, db: Session = Depends(get_db)) -> dict:
    if result_version != payload.base_result_version:
        raise HTTPException(status_code=409, detail="路径结果版本与提交版本不一致")
    read_diagnosis(analysis_id, diagnosis_id, payload.project_id, payload.prompt_id, db)
    revise_diagnosis_result(
        db,
        diagnosis_id=diagnosis_id,
        base_result_version=payload.base_result_version,
        base_result_hash=payload.base_result_hash,
        reviewable_set_hash=payload.reviewable_set_hash,
        edits=[row.model_dump() for row in payload.edits],
        editor=payload.editor,
    )
    return read_diagnosis(analysis_id, diagnosis_id, payload.project_id, payload.prompt_id, db)


@router.post("/analyses/{analysis_id}/diagnoses/{diagnosis_id}/results/{result_version}/reviews")
def review_diagnosis(analysis_id: str, diagnosis_id: str, result_version: str, payload: SinglePromptDiagnosisReviewCreate, db: Session = Depends(get_db)) -> dict:
    read_diagnosis(analysis_id, diagnosis_id, payload.project_id, payload.prompt_id, db)
    complete_diagnosis_review(
        db,
        diagnosis_id=diagnosis_id,
        result_version=result_version,
        result_hash=payload.result_hash,
        reviewable_set_hash=payload.reviewable_set_hash,
        reviewer=payload.reviewer,
        note=payload.note,
        decisions=payload.decisions,
    )
    return read_diagnosis(analysis_id, diagnosis_id, payload.project_id, payload.prompt_id, db)


@router.get("/analyses/{analysis_id}/diagnoses/{diagnosis_id}/results/{result_version}/strategy-readiness")
def read_strategy_readiness(
    analysis_id: str,
    diagnosis_id: str,
    result_version: str,
    project_id: int,
    prompt_id: int,
    db: Session = Depends(get_db),
) -> dict:
    return build_strategy_readiness(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        result_version=result_version,
        project_id=project_id,
        prompt_id=prompt_id,
    )


@router.get("/analyses/{analysis_id}/diagnoses/{diagnosis_id}/results/{result_version}/qualification-projection")
def read_qualification_projection(
    analysis_id: str,
    diagnosis_id: str,
    result_version: str,
    project_id: int,
    prompt_id: int,
    brand_context_version_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    return build_qualification_projection(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        result_version=result_version,
        project_id=project_id,
        prompt_id=prompt_id,
        brand_context_version_id=brand_context_version_id,
    )


@router.post(
    "/analyses/{analysis_id}/diagnoses/{diagnosis_id}/results/{result_version}/qualification-critics",
    status_code=202,
)
def create_qualification_critic(
    analysis_id: str,
    diagnosis_id: str,
    result_version: str,
    payload: SinglePromptQualificationCriticCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    execution, created = queue_qualification_critic(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        result_version=result_version,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        expected_projection_hash=payload.expected_projection_hash,
        idempotency_key=payload.idempotency_key,
        max_external_requests=payload.max_external_requests,
        max_total_tokens=payload.max_total_tokens,
        authorized_by=payload.authorized_by,
    )
    if not created:
        response.status_code = 200
    return get_qualification_critic_status(
        db,
        analysis_id=analysis_id,
        critic_id=execution.critic_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.post(
    "/analyses/{analysis_id}/diagnoses/{diagnosis_id}/results/{result_version}/qualification-critics/supplemental",
    status_code=202,
)
def create_qualification_critic_supplemental(
    analysis_id: str,
    diagnosis_id: str,
    result_version: str,
    payload: SinglePromptQualificationCriticSupplementalCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    execution, created = queue_qualification_critic_supplemental(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        result_version=result_version,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        parent_critic_id=payload.parent_critic_id,
        parent_result_version=payload.parent_result_version,
        object_id=payload.object_id,
        expected_task_id=payload.expected_task_id,
        expected_plan_hash=payload.expected_plan_hash,
        expected_semantic_input_hash=payload.expected_semantic_input_hash,
        expected_provider_payload_hash=payload.expected_provider_payload_hash,
        provider=payload.provider,
        model=payload.model,
        idempotency_key=payload.idempotency_key,
        max_external_requests=payload.max_external_requests,
        max_total_tokens=payload.max_total_tokens,
        max_budget_cny=payload.max_budget_cny,
        authorized_by=payload.authorized_by,
    )
    if not created:
        response.status_code = 200
    return get_qualification_critic_status(
        db,
        analysis_id=analysis_id,
        critic_id=execution.critic_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.get("/analyses/{analysis_id}/qualification-critics/{critic_id}")
def read_qualification_critic(
    analysis_id: str,
    critic_id: str,
    project_id: int,
    prompt_id: int,
    db: Session = Depends(get_db),
) -> dict:
    return get_qualification_critic_status(
        db,
        analysis_id=analysis_id,
        critic_id=critic_id,
        project_id=project_id,
        prompt_id=prompt_id,
    )


@router.get("/analyses/{analysis_id}/qualification-critics/{critic_id}/phase-b1")
def read_qualification_critic_phase_b1(
    analysis_id: str,
    critic_id: str,
    phase_a_result_version: str,
    project_id: int,
    prompt_id: int,
    db: Session = Depends(get_db),
) -> dict:
    return build_critic_gold_review_set(
        db,
        analysis_id=analysis_id,
        phase_a_critic_id=critic_id,
        phase_a_result_version=phase_a_result_version,
        project_id=project_id,
        prompt_id=prompt_id,
    )


@router.post("/analyses/{analysis_id}/qualification-critics/{critic_id}/phase-b1/reviews", status_code=201)
def create_qualification_critic_phase_b1_review(
    analysis_id: str,
    critic_id: str,
    payload: SinglePromptQualificationCriticGoldReviewCreate,
    db: Session = Depends(get_db),
) -> dict:
    return complete_critic_gold_review(
        db,
        analysis_id=analysis_id,
        phase_a_critic_id=critic_id,
        phase_a_result_version=payload.phase_a_result_version,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        expected_phase_a_result_hash=payload.expected_phase_a_result_hash,
        expected_reviewable_set_hash=payload.expected_reviewable_set_hash,
        expected_prior_review_id=payload.expected_prior_review_id,
        decisions=[decision.model_dump(mode="json") for decision in payload.decisions],
        reviewer=payload.reviewer,
        note=payload.note,
    )


@router.post("/analyses/{analysis_id}/diagnoses/{diagnosis_id}/results/{result_version}/strategies", status_code=201)
def generate_strategy(
    analysis_id: str,
    diagnosis_id: str,
    result_version: str,
    payload: SinglePromptStrategyCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    execution, _result, created = create_strategy_candidate(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        result_version=result_version,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        idempotency_key=payload.idempotency_key,
        diagnosis_result_hash=payload.diagnosis_result_hash,
        reviewable_set_hash=payload.reviewable_set_hash,
        review_id=payload.review_id,
        review_snapshot_hash=payload.review_snapshot_hash,
        input_projection_hash=payload.input_projection_hash,
    )
    if not created:
        response.status_code = 200
    return get_strategy_status(
        db,
        strategy_id=execution.strategy_id,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.post(
    "/analyses/{analysis_id}/diagnoses/{diagnosis_id}/results/{result_version}/automatic-strategies",
    status_code=201,
)
def generate_automatic_strategy(
    analysis_id: str,
    diagnosis_id: str,
    result_version: str,
    payload: SinglePromptAutomaticStrategyCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    execution, _result, created = create_automatic_strategy_candidate(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        result_version=result_version,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        idempotency_key=payload.idempotency_key,
        expected_projection_hash=payload.expected_projection_hash,
        brand_context_version_id=payload.brand_context_version_id,
    )
    if not created:
        response.status_code = 200
    return get_strategy_status(
        db,
        strategy_id=execution.strategy_id,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.get("/analyses/{analysis_id}/diagnoses/{diagnosis_id}/strategies/{strategy_id}")
def read_strategy(
    analysis_id: str,
    diagnosis_id: str,
    strategy_id: str,
    project_id: int,
    prompt_id: int,
    db: Session = Depends(get_db),
) -> dict:
    return get_strategy_status(
        db,
        strategy_id=strategy_id,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        project_id=project_id,
        prompt_id=prompt_id,
    )


@router.post("/analyses/{analysis_id}/diagnoses/{diagnosis_id}/strategies/{strategy_id}/results/{result_version}/priority-revisions")
def revise_strategy(
    analysis_id: str,
    diagnosis_id: str,
    strategy_id: str,
    result_version: str,
    payload: SinglePromptStrategyPriorityRevisionCreate,
    db: Session = Depends(get_db),
) -> dict:
    get_strategy_status(
        db,
        strategy_id=strategy_id,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )
    if result_version != payload.base_result_version:
        raise HTTPException(status_code=409, detail="路径策略版本与提交版本不一致")
    revise_strategy_priority(
        db,
        strategy_id=strategy_id,
        base_result_version=payload.base_result_version,
        base_result_hash=payload.base_result_hash,
        reviewable_set_hash=payload.reviewable_set_hash,
        ordered_direction_ids=payload.ordered_direction_ids,
        editor=payload.editor,
        reason=payload.reason,
    )
    return get_strategy_status(
        db,
        strategy_id=strategy_id,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.post("/analyses/{analysis_id}/diagnoses/{diagnosis_id}/strategies/{strategy_id}/results/{result_version}/reviews")
def review_strategy(
    analysis_id: str,
    diagnosis_id: str,
    strategy_id: str,
    result_version: str,
    payload: SinglePromptStrategyReviewCreate,
    db: Session = Depends(get_db),
) -> dict:
    get_strategy_status(
        db,
        strategy_id=strategy_id,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )
    complete_strategy_review(
        db,
        strategy_id=strategy_id,
        result_version=result_version,
        result_hash=payload.result_hash,
        reviewable_set_hash=payload.reviewable_set_hash,
        decision=payload.decision,
        reviewer=payload.reviewer,
        note=payload.note,
    )
    return get_strategy_status(
        db,
        strategy_id=strategy_id,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.post(
    "/analyses/{analysis_id}/diagnoses/{diagnosis_id}/strategies/{strategy_id}/results/{result_version}/execution-proposals",
    status_code=201,
)
def generate_execution_proposal(
    analysis_id: str,
    diagnosis_id: str,
    strategy_id: str,
    result_version: str,
    payload: SinglePromptExecutionProposalCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    strategy_status = get_strategy_status(
        db,
        strategy_id=strategy_id,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )
    authority_type = str(strategy_status["strategy"].get("input_authority_type") or "HUMAN_REVIEW")
    if authority_type == "HUMAN_REVIEW" and (
        not strategy_status.get("review") or strategy_status["review"].get("decision") != "ACCEPTED"
    ):
        raise HTTPException(status_code=409, detail="当前精确策略版本尚未确认")
    proposal, _result, created = create_execution_proposal(
        db,
        strategy_id=strategy_id,
        strategy_result_version=result_version,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        direction_id=payload.direction_id,
        idempotency_key=payload.idempotency_key,
        strategy_result_hash=payload.strategy_result_hash,
        strategy_review_id=payload.strategy_review_id,
        strategy_review_snapshot_hash=payload.strategy_review_snapshot_hash,
        brand_context_version_id=payload.brand_context_version_id,
        input_authority_type=payload.input_authority_type,
        input_authority_id=payload.input_authority_id,
        input_authority_hash=payload.input_authority_hash,
    )
    if not created:
        response.status_code = 200
    return get_execution_proposal_status(
        db,
        proposal_id=proposal.proposal_id,
        strategy_id=strategy_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.get("/strategies/{strategy_id}/execution-proposals/{proposal_id}")
def read_execution_proposal(
    strategy_id: str,
    proposal_id: str,
    project_id: int,
    prompt_id: int,
    result_version: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    return get_execution_proposal_status(
        db,
        proposal_id=proposal_id,
        strategy_id=strategy_id,
        project_id=project_id,
        prompt_id=prompt_id,
        result_version=result_version,
    )


@router.post("/strategies/{strategy_id}/execution-proposals/{proposal_id}/results/{result_version}/revisions")
def revise_execution(
    strategy_id: str,
    proposal_id: str,
    result_version: str,
    payload: SinglePromptExecutionProposalRevisionCreate,
    db: Session = Depends(get_db),
) -> dict:
    if result_version != payload.base_result_version:
        raise HTTPException(status_code=409, detail="路径执行方案版本与提交版本不一致")
    get_execution_proposal_status(
        db, proposal_id=proposal_id, strategy_id=strategy_id,
        project_id=payload.project_id, prompt_id=payload.prompt_id,
    )
    revise_execution_proposal(
        db,
        proposal_id=proposal_id,
        base_result_version=result_version,
        base_result_hash=payload.base_result_hash,
        reviewable_set_hash=payload.reviewable_set_hash,
        editor=payload.editor,
        edit=payload.edit,
    )
    return get_execution_proposal_status(
        db,
        proposal_id=proposal_id,
        strategy_id=strategy_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.post("/strategies/{strategy_id}/execution-proposals/{proposal_id}/results/{result_version}/deliverable")
def generate_execution_deliverable(
    strategy_id: str,
    proposal_id: str,
    result_version: str,
    payload: SinglePromptExecutionDeliverableCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    if result_version != payload.base_result_version:
        raise HTTPException(status_code=409, detail="路径执行方案版本与提交版本不一致")
    get_execution_proposal_status(
        db, proposal_id=proposal_id, strategy_id=strategy_id,
        project_id=payload.project_id, prompt_id=payload.prompt_id,
    )
    _result, created = generate_complete_execution_deliverable(
        db,
        proposal_id=proposal_id,
        base_result_version=result_version,
        base_result_hash=payload.base_result_hash,
        reviewable_set_hash=payload.reviewable_set_hash,
    )
    if not created:
        response.status_code = 200
    return get_execution_proposal_status(
        db,
        proposal_id=proposal_id,
        strategy_id=strategy_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.post("/strategies/{strategy_id}/execution-proposals/{proposal_id}/results/{result_version}/confirmations")
def confirm_execution(
    strategy_id: str,
    proposal_id: str,
    result_version: str,
    payload: SinglePromptExecutionConfirmationCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    get_execution_proposal_status(
        db, proposal_id=proposal_id, strategy_id=strategy_id,
        project_id=payload.project_id, prompt_id=payload.prompt_id,
    )
    _confirmation, created = confirm_execution_proposal(
        db,
        proposal_id=proposal_id,
        result_version=result_version,
        result_hash=payload.result_hash,
        reviewable_set_hash=payload.reviewable_set_hash,
        idempotency_key=payload.idempotency_key,
        confirmer=payload.confirmer,
        note=payload.note,
    )
    if not created:
        response.status_code = 200
    return get_execution_proposal_status(
        db,
        proposal_id=proposal_id,
        strategy_id=strategy_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.post(
    "/strategies/{strategy_id}/execution-proposals/{proposal_id}/confirmations/{confirmation_id}/publications",
    status_code=201,
)
def record_execution_publication(
    strategy_id: str,
    proposal_id: str,
    confirmation_id: str,
    payload: SinglePromptPublicationCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    status = get_execution_proposal_status(
        db, proposal_id=proposal_id, strategy_id=strategy_id,
        project_id=payload.project_id, prompt_id=payload.prompt_id,
    )
    report = payload.model_dump(
        exclude={"project_id", "prompt_id", "idempotency_key", "prior_publication_id", "recorder"}
    )
    _publication, created = record_publication(
        db,
        confirmation_id=confirmation_id,
        proposal_id=proposal_id,
        idempotency_key=payload.idempotency_key,
        prior_publication_id=payload.prior_publication_id,
        recorder=payload.recorder,
        report=report,
    )
    if not created:
        response.status_code = 200
    return get_execution_proposal_status(
        db,
        proposal_id=proposal_id,
        strategy_id=strategy_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        result_version=next(row["result_version"] for row in status["confirmations"]
                            if row["confirmation_id"] == confirmation_id),
    )


@router.get("/retests/readiness")
def read_retest_readiness(
    project_id: int,
    prompt_id: int,
    confirmation_id: str | None = None,
    publication_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    return build_retest_readiness(
        db,
        project_id=project_id,
        prompt_id=prompt_id,
        confirmation_id=confirmation_id,
        publication_id=publication_id,
    )


@router.post("/retests", status_code=201)
def plan_retest(payload: SinglePromptRetestCreate, response: Response, db: Session = Depends(get_db)) -> dict:
    retest, created = create_retest(
        db,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        confirmation_id=payload.confirmation_id,
        publication_id=payload.publication_id,
        confirmation_snapshot_hash=payload.confirmation_snapshot_hash,
        publication_report_hash=payload.publication_report_hash,
        idempotency_key=payload.idempotency_key,
        sample_count=payload.sample_count,
        measurement_identity=payload.measurement_identity.model_dump() if payload.measurement_identity else None,
    )
    if not created:
        response.status_code = 200
    return get_retest_status(db, retest_id=retest.retest_id, project_id=payload.project_id, prompt_id=payload.prompt_id)


@router.get("/retests/{retest_id}")
def read_retest(retest_id: str, project_id: int, prompt_id: int, db: Session = Depends(get_db)) -> dict:
    return get_retest_status(db, retest_id=retest_id, project_id=project_id, prompt_id=prompt_id)


@router.post("/retests/{retest_id}/sampling", status_code=202)
def run_retest_sampling(
    retest_id: str,
    payload: SinglePromptRetestAction,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    start_retest_sampling(db, retest_id=retest_id, project_id=payload.project_id, prompt_id=payload.prompt_id)
    background_tasks.add_task(execute_retest_sampling, retest_id, session_factory=ReleaseSessionLocal)
    return get_retest_status(db, retest_id=retest_id, project_id=payload.project_id, prompt_id=payload.prompt_id)


@router.post("/retests/{retest_id}/sampling/retry", status_code=202)
def retry_retest(
    retest_id: str,
    payload: SinglePromptRetestAction,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    retry_retest_sampling(db, retest_id=retest_id, project_id=payload.project_id, prompt_id=payload.prompt_id)
    background_tasks.add_task(execute_retest_sampling, retest_id, session_factory=ReleaseSessionLocal)
    return get_retest_status(db, retest_id=retest_id, project_id=payload.project_id, prompt_id=payload.prompt_id)


@router.post("/retests/{retest_id}/sampling/finalize")
def finalize_retest(
    retest_id: str,
    payload: SinglePromptRetestAction,
    db: Session = Depends(get_db),
) -> dict:
    finalize_retest_with_failures(db, retest_id=retest_id, project_id=payload.project_id, prompt_id=payload.prompt_id)
    return get_retest_status(db, retest_id=retest_id, project_id=payload.project_id, prompt_id=payload.prompt_id)


@router.post("/retests/{retest_id}/semantic-measurement", status_code=202)
def run_retest_semantics(
    retest_id: str,
    payload: SinglePromptSemanticMeasurementCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    start_semantic_measurement(
        db,
        retest_id=retest_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        authorize_external_llm=payload.authorize_external_llm,
    )
    background_tasks.add_task(
        execute_semantic_measurement,
        retest_id,
        payload.authorize_external_llm,
        session_factory=ReleaseSessionLocal,
    )
    return get_retest_status(db, retest_id=retest_id, project_id=payload.project_id, prompt_id=payload.prompt_id)


@router.post("/retests/{retest_id}/comparisons", status_code=201)
def create_retest_comparison(
    retest_id: str,
    payload: SinglePromptRetestAction,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    _comparison, created = create_comparison(
        db,
        retest_id=retest_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )
    if not created:
        response.status_code = 200
    return get_retest_status(db, retest_id=retest_id, project_id=payload.project_id, prompt_id=payload.prompt_id)


@router.post("/analyses/{analysis_id}/diagnoses/{diagnosis_id}/results/{result_version}/target-brand-truths", status_code=201)
def create_target_brand_truth(
    analysis_id: str,
    diagnosis_id: str,
    result_version: str,
    payload: SinglePromptTargetBrandTruthCreate,
    db: Session = Depends(get_db),
) -> dict:
    return record_target_brand_truth(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        result_version=result_version,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        result_hash=payload.result_hash,
        frozen_truth_set_hash=payload.frozen_truth_set_hash,
        expected_project_truth_set_hash=payload.expected_project_truth_set_hash,
        source_signal_id=payload.source_signal_id,
        capability_label=payload.capability_label,
        product_truth_status=payload.product_truth_status,
        source_reference=payload.source_reference,
        note=payload.note,
        reviewed_by=payload.reviewed_by,
    )


@router.post("/analyses/{analysis_id}/diagnoses/{diagnosis_id}/results/{result_version}/truth-reprojections", status_code=201)
def create_truth_reprojection(
    analysis_id: str,
    diagnosis_id: str,
    result_version: str,
    payload: SinglePromptTruthReprojectionCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    execution, created = reproject_target_brand_truths(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        result_version=result_version,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        source_result_hash=payload.source_result_hash,
        source_review_id=payload.source_review_id,
        expected_project_truth_set_hash=payload.expected_project_truth_set_hash,
        idempotency_key=payload.idempotency_key,
    )
    if not created:
        response.status_code = 200
    return get_diagnosis_status(
        db,
        analysis_id=analysis_id,
        diagnosis_id=execution.diagnosis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.post("/analyses/{analysis_id}/diagnoses/{diagnosis_id}/evidence-continuations", status_code=202)
def start_evidence_continuation(analysis_id: str, diagnosis_id: str, payload: SinglePromptEvidenceContinuationCreate, response: Response, db: Session = Depends(get_db)) -> dict:
    _, created = queue_evidence_continuation(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        answer_result_version=payload.answer_result_version,
        answer_result_hash=payload.answer_result_hash,
        answer_review_id=payload.answer_review_id,
        citation_manifest_id=payload.citation_manifest_id,
        citation_manifest_hash=payload.citation_manifest_hash,
        completion_manifest_id=payload.completion_manifest_id,
        completion_manifest_hash=payload.completion_manifest_hash,
        evidence_llm_policy=payload.evidence_llm_policy,
    )
    if not created:
        response.status_code = 200
    return read_diagnosis(analysis_id, diagnosis_id, payload.project_id, payload.prompt_id, db)
