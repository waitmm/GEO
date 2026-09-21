"""First-slice API without imports from later V2 or legacy workflow runners."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.release_database import get_release_db
from app.modules.single_prompt_v2.diagnosis import (
    complete_diagnosis_review,
    create_answer_diagnosis,
    get_diagnosis_status,
    queue_evidence_continuation,
    record_target_brand_truth,
    retry_diagnosis,
    revise_diagnosis_result,
)
from app.modules.single_prompt_v2.schemas import (
    SinglePromptAnalysisCreate,
    SinglePromptRunRetryCreate,
    SinglePromptRunSelectionCreate,
    SinglePromptAnswerDiagnosisCreate,
    SinglePromptDiagnosisReviewCreate,
    SinglePromptDiagnosisRevisionCreate,
    SinglePromptEvidenceContinuationCreate,
    SinglePromptManualSourceContentCreate,
    SinglePromptSourceCompletionCreate,
    SinglePromptSourceAutoFetchCreate,
    SinglePromptSourcePreparationCreate,
    SinglePromptSourceWaiverCreate,
    SinglePromptTargetBrandTruthCreate,
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
from app.modules.single_prompt_v2.source_preparation import (
    create_source_preparation,
    freeze_completion_manifest,
    get_source_preparation_for_analysis,
    get_source_preparation_status,
    queue_auto_fetch,
    submit_manual_content,
    waive_source,
)


router = APIRouter(prefix="/api/v2/single-prompt", tags=["single-prompt-v2-release"])
get_db = get_release_db


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
def read_source_preparation(preparation_id: str, db: Session = Depends(get_db)) -> dict:
    return get_source_preparation_status(db, preparation_id=preparation_id)


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
        capability_label=payload.capability_label,
        product_truth_status=payload.product_truth_status,
        source_reference=payload.source_reference,
        note=payload.note,
        reviewed_by=payload.reviewed_by,
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
