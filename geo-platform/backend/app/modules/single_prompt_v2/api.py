from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.single_prompt_v2.diagnosis import (
    complete_diagnosis_review,
    continue_evidence_diagnosis,
    create_answer_diagnosis,
    create_diagnosis,
    execute_diagnosis,
    get_diagnosis_status,
    retry_diagnosis,
    revise_diagnosis_result,
)
from app.modules.single_prompt_v2.schemas import (
    SinglePromptAnalysisCreate,
    SinglePromptAnalysisStatusRead,
    SinglePromptAnswerDiagnosisCreate,
    SinglePromptDiagnosisCreate,
    SinglePromptDiagnosisReviewCreate,
    SinglePromptDiagnosisRevisionCreate,
    SinglePromptEvidenceContinuationCreate,
    SinglePromptManualSourceContentCreate,
    SinglePromptSourceCompletionCreate,
    SinglePromptSourcePreparationCreate,
    SinglePromptSourceWaiverCreate,
    SinglePromptStrategyCreate,
    SinglePromptStrategyPriorityRevisionCreate,
    SinglePromptStrategyReviewCreate,
    SinglePromptExecutionConfirmationCreate,
    SinglePromptExecutionProposalCreate,
    SinglePromptExecutionProposalRevisionCreate,
    SinglePromptPublicationCreate,
    SinglePromptRetestAction,
    SinglePromptRetestCreate,
    SinglePromptSemanticMeasurementCreate,
)
from app.modules.single_prompt_v2.source_preparation import (
    create_source_preparation,
    freeze_completion_manifest,
    get_source_preparation_for_analysis,
    get_source_preparation_status,
    submit_manual_content,
    waive_source,
)
from app.modules.single_prompt_v2.execution import (
    confirm_execution_proposal,
    create_execution_proposal,
    get_execution_proposal_status,
    record_publication,
    revise_execution_proposal,
)
from app.modules.single_prompt_v2.service import create_analysis, execute_analysis, get_analysis_status, retry_analysis
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
from app.modules.single_prompt_v2.strategy import (
    build_strategy_readiness,
    complete_strategy_review,
    create_strategy_candidate,
    get_strategy_status,
    revise_strategy_priority,
)
from app.modules.single_prompt_v2.qualification import build_qualification_projection


router = APIRouter(prefix="/api/v2/single-prompt", tags=["single-prompt-v2"])


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
    background_tasks.add_task(execute_retest_sampling, retest_id)
    return get_retest_status(db, retest_id=retest_id, project_id=payload.project_id, prompt_id=payload.prompt_id)


@router.post("/retests/{retest_id}/sampling/retry", status_code=202)
def retry_retest(
    retest_id: str,
    payload: SinglePromptRetestAction,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    retry_retest_sampling(db, retest_id=retest_id, project_id=payload.project_id, prompt_id=payload.prompt_id)
    background_tasks.add_task(execute_retest_sampling, retest_id)
    return get_retest_status(db, retest_id=retest_id, project_id=payload.project_id, prompt_id=payload.prompt_id)


@router.post("/retests/{retest_id}/sampling/finalize")
def finalize_retest_sampling_with_failures(
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
    background_tasks.add_task(execute_semantic_measurement, retest_id, payload.authorize_external_llm)
    return get_retest_status(db, retest_id=retest_id, project_id=payload.project_id, prompt_id=payload.prompt_id)


@router.post("/retests/{retest_id}/comparisons", status_code=201)
def build_retest_comparison(
    retest_id: str,
    payload: SinglePromptRetestAction,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    _, created = create_comparison(db, retest_id=retest_id, project_id=payload.project_id, prompt_id=payload.prompt_id)
    if not created:
        response.status_code = 200
    return get_retest_status(db, retest_id=retest_id, project_id=payload.project_id, prompt_id=payload.prompt_id)


@router.post("/analyses", response_model=SinglePromptAnalysisStatusRead, status_code=202)
def start_analysis(
    payload: SinglePromptAnalysisCreate,
    background_tasks: BackgroundTasks,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    analysis, created = create_analysis(
        db,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        sample_count=payload.sample_count,
        idempotency_key=payload.idempotency_key,
    )
    if created:
        background_tasks.add_task(execute_analysis, analysis.analysis_id)
    else:
        response.status_code = 200
    return get_analysis_status(db, analysis.analysis_id)


@router.get("/analyses/{analysis_id}", response_model=SinglePromptAnalysisStatusRead)
def read_analysis(analysis_id: str, project_id: int, prompt_id: int, db: Session = Depends(get_db)) -> dict:
    status = get_analysis_status(db, analysis_id)
    identity = status["analysis"]
    if identity["project_id"] != project_id or identity["prompt_id"] != prompt_id:
        raise HTTPException(status_code=409, detail="分析身份与当前 Project/Prompt 不匹配")
    return status


@router.post("/analyses/{analysis_id}/retry", response_model=SinglePromptAnalysisStatusRead, status_code=202)
def retry_collection(
    analysis_id: str,
    project_id: int,
    prompt_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    status = get_analysis_status(db, analysis_id)
    identity = status["analysis"]
    if identity["project_id"] != project_id or identity["prompt_id"] != prompt_id:
        raise HTTPException(status_code=409, detail="分析身份与当前 Project/Prompt 不匹配")
    retry_analysis(db, analysis_id)
    background_tasks.add_task(execute_analysis, analysis_id)
    return get_analysis_status(db, analysis_id)


@router.post("/analyses/{analysis_id}/source-preparation", status_code=201)
def start_source_preparation(
    analysis_id: str,
    payload: SinglePromptSourcePreparationCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
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
def read_analysis_source_preparation(
    analysis_id: str,
    project_id: int,
    prompt_id: int,
    db: Session = Depends(get_db),
) -> dict | None:
    return get_source_preparation_for_analysis(
        db,
        analysis_id=analysis_id,
        project_id=project_id,
        prompt_id=prompt_id,
    )


@router.get("/source-preparations/{preparation_id}")
def read_source_preparation(preparation_id: str, db: Session = Depends(get_db)) -> dict:
    return get_source_preparation_status(db, preparation_id=preparation_id)


@router.post("/source-preparations/{preparation_id}/manual-content")
def submit_source_manual_content(
    preparation_id: str,
    payload: SinglePromptManualSourceContentCreate,
    db: Session = Depends(get_db),
) -> dict:
    status = get_source_preparation_status(db, preparation_id=preparation_id)
    identity = status["preparation"]
    if identity["project_id"] != payload.project_id or identity["prompt_id"] != payload.prompt_id:
        raise HTTPException(status_code=409, detail="来源准备与当前 Project/Prompt 不匹配")
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
def waive_prepared_source(
    preparation_id: str,
    payload: SinglePromptSourceWaiverCreate,
    db: Session = Depends(get_db),
) -> dict:
    status = get_source_preparation_status(db, preparation_id=preparation_id)
    identity = status["preparation"]
    if identity["project_id"] != payload.project_id or identity["prompt_id"] != payload.prompt_id:
        raise HTTPException(status_code=409, detail="来源准备与当前 Project/Prompt 不匹配")
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
def complete_source_preparation(
    preparation_id: str,
    payload: SinglePromptSourceCompletionCreate,
    db: Session = Depends(get_db),
) -> dict:
    status = get_source_preparation_status(db, preparation_id=preparation_id)
    identity = status["preparation"]
    if identity["project_id"] != payload.project_id or identity["prompt_id"] != payload.prompt_id:
        raise HTTPException(status_code=409, detail="来源准备与当前 Project/Prompt 不匹配")
    freeze_completion_manifest(db, preparation_id=preparation_id, created_by=payload.created_by)
    return get_source_preparation_status(db, preparation_id=preparation_id)


@router.post("/analyses/{analysis_id}/answer-diagnoses", status_code=202)
def start_answer_diagnosis(
    analysis_id: str,
    payload: SinglePromptAnswerDiagnosisCreate,
    background_tasks: BackgroundTasks,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
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
    if created:
        background_tasks.add_task(execute_diagnosis, execution.diagnosis_id)
    else:
        response.status_code = 200
    return get_diagnosis_status(
        db,
        analysis_id=analysis_id,
        diagnosis_id=execution.diagnosis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.post("/analyses/{analysis_id}/diagnoses/{diagnosis_id}/evidence-continuations", status_code=201)
def start_evidence_continuation(
    analysis_id: str,
    diagnosis_id: str,
    payload: SinglePromptEvidenceContinuationCreate,
    db: Session = Depends(get_db),
) -> dict:
    continue_evidence_diagnosis(
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
    return get_diagnosis_status(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.post("/analyses/{analysis_id}/diagnoses", status_code=202)
def start_diagnosis(
    analysis_id: str,
    payload: SinglePromptDiagnosisCreate,
    background_tasks: BackgroundTasks,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    execution, created = create_diagnosis(
        db,
        analysis_id=analysis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        idempotency_key=payload.idempotency_key,
        source_snapshot_policy=payload.source_snapshot_policy,
        evidence_llm_policy=payload.evidence_llm_policy,
    )
    if created:
        background_tasks.add_task(execute_diagnosis, execution.diagnosis_id)
    else:
        response.status_code = 200
    return get_diagnosis_status(
        db,
        analysis_id=analysis_id,
        diagnosis_id=execution.diagnosis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.get("/analyses/{analysis_id}/diagnoses/{diagnosis_id}")
def read_diagnosis(
    analysis_id: str,
    diagnosis_id: str,
    project_id: int,
    prompt_id: int,
    db: Session = Depends(get_db),
) -> dict:
    return get_diagnosis_status(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        project_id=project_id,
        prompt_id=prompt_id,
    )


@router.post("/analyses/{analysis_id}/diagnoses/{diagnosis_id}/retry", status_code=202)
def retry_diagnosis_execution(
    analysis_id: str,
    diagnosis_id: str,
    project_id: int,
    prompt_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    get_diagnosis_status(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        project_id=project_id,
        prompt_id=prompt_id,
    )
    retry_diagnosis(db, diagnosis_id)
    background_tasks.add_task(execute_diagnosis, diagnosis_id)
    return get_diagnosis_status(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        project_id=project_id,
        prompt_id=prompt_id,
    )


@router.post("/analyses/{analysis_id}/diagnoses/{diagnosis_id}/results/{result_version}/revisions")
def revise_diagnosis(
    analysis_id: str,
    diagnosis_id: str,
    result_version: str,
    payload: SinglePromptDiagnosisRevisionCreate,
    db: Session = Depends(get_db),
) -> dict:
    if result_version != payload.base_result_version:
        raise HTTPException(status_code=409, detail="路径结果版本与提交版本不一致")
    get_diagnosis_status(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )
    revise_diagnosis_result(
        db,
        diagnosis_id=diagnosis_id,
        base_result_version=payload.base_result_version,
        base_result_hash=payload.base_result_hash,
        reviewable_set_hash=payload.reviewable_set_hash,
        edits=[item.model_dump() for item in payload.edits],
        editor=payload.editor,
    )
    return get_diagnosis_status(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


@router.post("/analyses/{analysis_id}/diagnoses/{diagnosis_id}/results/{result_version}/reviews")
def review_diagnosis(
    analysis_id: str,
    diagnosis_id: str,
    result_version: str,
    payload: SinglePromptDiagnosisReviewCreate,
    db: Session = Depends(get_db),
) -> dict:
    get_diagnosis_status(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )
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
    return get_diagnosis_status(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
    )


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
    db: Session = Depends(get_db),
) -> dict:
    return build_qualification_projection(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        result_version=result_version,
        project_id=project_id,
        prompt_id=prompt_id,
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


@router.post("/analyses/{analysis_id}/diagnoses/{diagnosis_id}/strategies/{strategy_id}/results/{result_version}/execution-proposals", status_code=201)
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
        db, strategy_id=strategy_id, analysis_id=analysis_id, diagnosis_id=diagnosis_id,
        project_id=payload.project_id, prompt_id=payload.prompt_id,
    )
    if not strategy_status.get("review") or strategy_status["review"].get("decision") != "ACCEPTED":
        raise HTTPException(status_code=409, detail="当前精确策略版本尚未确认")
    proposal, _result, created = create_execution_proposal(
        db, strategy_id=strategy_id, strategy_result_version=result_version,
        project_id=payload.project_id, prompt_id=payload.prompt_id,
        direction_id=payload.direction_id, idempotency_key=payload.idempotency_key,
        strategy_result_hash=payload.strategy_result_hash,
        strategy_review_id=payload.strategy_review_id,
        strategy_review_snapshot_hash=payload.strategy_review_snapshot_hash,
    )
    if not created:
        response.status_code = 200
    return get_execution_proposal_status(
        db, proposal_id=proposal.proposal_id, strategy_id=strategy_id,
        project_id=payload.project_id, prompt_id=payload.prompt_id,
    )


@router.get("/strategies/{strategy_id}/execution-proposals/{proposal_id}")
def read_execution_proposal(
    strategy_id: str,
    proposal_id: str,
    project_id: int,
    prompt_id: int,
    db: Session = Depends(get_db),
) -> dict:
    return get_execution_proposal_status(
        db, proposal_id=proposal_id, strategy_id=strategy_id,
        project_id=project_id, prompt_id=prompt_id,
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
        db, proposal_id=proposal_id, base_result_version=result_version,
        base_result_hash=payload.base_result_hash, reviewable_set_hash=payload.reviewable_set_hash,
        editor=payload.editor, edit=payload.edit,
    )
    return get_execution_proposal_status(
        db, proposal_id=proposal_id, strategy_id=strategy_id,
        project_id=payload.project_id, prompt_id=payload.prompt_id,
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
        db, proposal_id=proposal_id, result_version=result_version,
        result_hash=payload.result_hash, reviewable_set_hash=payload.reviewable_set_hash,
        idempotency_key=payload.idempotency_key, confirmer=payload.confirmer, note=payload.note,
    )
    if not created:
        response.status_code = 200
    return get_execution_proposal_status(
        db, proposal_id=proposal_id, strategy_id=strategy_id,
        project_id=payload.project_id, prompt_id=payload.prompt_id,
    )


@router.post("/strategies/{strategy_id}/execution-proposals/{proposal_id}/confirmations/{confirmation_id}/publications", status_code=201)
def publish_execution_record(
    strategy_id: str,
    proposal_id: str,
    confirmation_id: str,
    payload: SinglePromptPublicationCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    get_execution_proposal_status(
        db, proposal_id=proposal_id, strategy_id=strategy_id,
        project_id=payload.project_id, prompt_id=payload.prompt_id,
    )
    report = payload.model_dump(exclude={"project_id", "prompt_id", "idempotency_key", "prior_publication_id", "recorder"})
    _publication, created = record_publication(
        db, confirmation_id=confirmation_id, proposal_id=proposal_id, idempotency_key=payload.idempotency_key,
        prior_publication_id=payload.prior_publication_id, recorder=payload.recorder, report=report,
    )
    if not created:
        response.status_code = 200
    return get_execution_proposal_status(
        db, proposal_id=proposal_id, strategy_id=strategy_id,
        project_id=payload.project_id, prompt_id=payload.prompt_id,
    )
