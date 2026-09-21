from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SinglePromptAnalysisCreate(BaseModel):
    project_id: int
    prompt_id: int
    sample_count: int = Field(default=3, ge=1, le=10)
    idempotency_key: str = Field(min_length=8, max_length=120)


class SinglePromptRunSelectionCreate(BaseModel):
    project_id: int
    prompt_id: int
    run_ids: list[int] = Field(min_length=1, max_length=500)
    run_fingerprints: dict[int, str]
    base_context_id: str | None = Field(default=None, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=120)


class SinglePromptRunRetryCreate(BaseModel):
    project_id: int
    prompt_id: int
    idempotency_key: str = Field(min_length=8, max_length=120)


class AnalysisIdentityRead(BaseModel):
    analysis_id: str
    project_id: int
    prompt_id: int
    task_id: int | None
    prompt_text: str
    sampling_plan_hash: str


class SamplingStateRead(BaseModel):
    status: str
    planned_run_count: int
    terminal_run_count: int
    valid_run_count: int
    failed_run_count: int
    attempt_count: int


class ActiveTaskRead(BaseModel):
    task_id: int
    status: str
    active_attempt_token: str | None = None


class SinglePromptAnalysisStatusRead(BaseModel):
    analysis: AnalysisIdentityRead
    sampling: SamplingStateRead
    result_version: str | None = None
    context_id: str | None = None
    result_source: str
    blocker: dict[str, str] | None = None
    allowed_operations: list[str]
    active_task: ActiveTaskRead | None = None
    runs: list[dict[str, Any]]
    failures: list[dict[str, Any]]
    warnings: list[dict[str, str]]
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class SinglePromptDiagnosisCreate(BaseModel):
    project_id: int
    prompt_id: int
    idempotency_key: str = Field(min_length=8, max_length=120)
    source_snapshot_policy: Literal["REUSE_OR_FETCH", "REUSE_ONLY"] = "REUSE_OR_FETCH"
    evidence_llm_policy: Literal["ALLOW_EXTERNAL", "CACHE_ONLY"] = "ALLOW_EXTERNAL"


class SinglePromptSourcePreparationCreate(BaseModel):
    project_id: int
    prompt_id: int
    idempotency_key: str = Field(min_length=8, max_length=120)
    created_by: str = Field(min_length=1, max_length=120)


class SinglePromptSourceAutoFetchCreate(BaseModel):
    project_id: int
    prompt_id: int


class SinglePromptManualSourceContentCreate(BaseModel):
    project_id: int
    prompt_id: int
    source_key: str = Field(min_length=64, max_length=64)
    expected_row_version: int = Field(ge=1)
    title: str = Field(default="", max_length=500)
    clean_text: str = Field(min_length=50)
    coverage_scope: Literal["FULL_PAGE", "EXCERPT"]
    submitted_by: str = Field(min_length=1, max_length=120)


class SinglePromptSourceWaiverCreate(BaseModel):
    project_id: int
    prompt_id: int
    source_key: str = Field(min_length=64, max_length=64)
    expected_row_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)
    impact: str = Field(min_length=1, max_length=2000)
    waived_by: str = Field(min_length=1, max_length=120)


class SinglePromptSourceCompletionCreate(BaseModel):
    project_id: int
    prompt_id: int
    created_by: str = Field(min_length=1, max_length=120)


class SinglePromptAnswerDiagnosisCreate(BaseModel):
    project_id: int
    prompt_id: int
    citation_manifest_id: str = Field(min_length=1, max_length=80)
    citation_manifest_hash: str = Field(min_length=64, max_length=64)
    answer_llm_policy: Literal["ALLOW_EXTERNAL", "CACHE_ONLY"] = "CACHE_ONLY"
    idempotency_key: str = Field(min_length=8, max_length=120)


class SinglePromptEvidenceContinuationCreate(BaseModel):
    project_id: int
    prompt_id: int
    answer_result_version: str = Field(min_length=1, max_length=96)
    answer_result_hash: str = Field(min_length=64, max_length=64)
    answer_review_id: str = Field(min_length=1, max_length=80)
    citation_manifest_id: str = Field(min_length=1, max_length=80)
    citation_manifest_hash: str = Field(min_length=64, max_length=64)
    completion_manifest_id: str = Field(min_length=1, max_length=80)
    completion_manifest_hash: str = Field(min_length=64, max_length=64)
    evidence_llm_policy: Literal["ALLOW_EXTERNAL", "CACHE_ONLY"] = "CACHE_ONLY"


class DiagnosisEdit(BaseModel):
    target_type: str
    target_id: str
    value: str
    reason: str = Field(min_length=1, max_length=2000)


class SinglePromptDiagnosisRevisionCreate(BaseModel):
    project_id: int
    prompt_id: int
    base_result_version: str
    base_result_hash: str
    reviewable_set_hash: str
    editor: str = Field(min_length=1, max_length=120)
    edits: list[DiagnosisEdit] = Field(min_length=1)


class SinglePromptDiagnosisReviewCreate(BaseModel):
    project_id: int
    prompt_id: int
    result_hash: str
    reviewable_set_hash: str
    reviewer: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=5000)
    decisions: list[dict[str, Any]] = Field(default_factory=list)


class SinglePromptStrategyCreate(BaseModel):
    project_id: int
    prompt_id: int
    idempotency_key: str = Field(min_length=8, max_length=120)
    diagnosis_result_hash: str = Field(min_length=64, max_length=64)
    reviewable_set_hash: str = Field(min_length=64, max_length=64)
    review_id: str = Field(min_length=1, max_length=80)
    review_snapshot_hash: str = Field(min_length=64, max_length=64)
    input_projection_hash: str = Field(min_length=64, max_length=64)


class SinglePromptStrategyPriorityRevisionCreate(BaseModel):
    project_id: int
    prompt_id: int
    base_result_version: str
    base_result_hash: str = Field(min_length=64, max_length=64)
    reviewable_set_hash: str = Field(min_length=64, max_length=64)
    ordered_direction_ids: list[str] = Field(min_length=1)
    editor: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=2000)


class SinglePromptStrategyReviewCreate(BaseModel):
    project_id: int
    prompt_id: int
    result_hash: str = Field(min_length=64, max_length=64)
    reviewable_set_hash: str = Field(min_length=64, max_length=64)
    decision: Literal["ACCEPTED", "REJECTED"]
    reviewer: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=5000)


class SinglePromptExecutionProposalCreate(BaseModel):
    project_id: int
    prompt_id: int
    direction_id: str = Field(min_length=1, max_length=96)
    idempotency_key: str = Field(min_length=8, max_length=120)
    strategy_result_hash: str = Field(min_length=64, max_length=64)
    strategy_review_id: str = Field(min_length=1, max_length=80)
    strategy_review_snapshot_hash: str = Field(min_length=64, max_length=64)


class SinglePromptExecutionProposalRevisionCreate(BaseModel):
    project_id: int
    prompt_id: int
    base_result_version: str = Field(min_length=1, max_length=96)
    base_result_hash: str = Field(min_length=64, max_length=64)
    reviewable_set_hash: str = Field(min_length=64, max_length=64)
    editor: str = Field(min_length=1, max_length=120)
    edit: dict[str, Any]


class SinglePromptExecutionConfirmationCreate(BaseModel):
    project_id: int
    prompt_id: int
    result_hash: str = Field(min_length=64, max_length=64)
    reviewable_set_hash: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=120)
    confirmer: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=5000)


class SinglePromptPublicationCreate(BaseModel):
    project_id: int
    prompt_id: int
    idempotency_key: str = Field(min_length=8, max_length=120)
    prior_publication_id: str | None = Field(default=None, max_length=80)
    recorder: str = Field(min_length=1, max_length=120)
    actual_channel: str = Field(min_length=1, max_length=80)
    actual_account: str = Field(min_length=1, max_length=240)
    actual_location: str = Field(min_length=1, max_length=500)
    actual_url: str = Field(min_length=1, max_length=1200)
    published_at: str = Field(min_length=1, max_length=80)
    actual_content_version: str = Field(default="", max_length=160)
    actual_title: str = Field(default="", max_length=500)
    actual_section_ids: list[str] | None = None
    actual_claim_ids: list[str] | None = None
    actual_content_excerpt: str = Field(default="", max_length=5000)
    differences: str = Field(default="", max_length=5000)
    publication_status: Literal["USER_REPORTED"] = "USER_REPORTED"


class SinglePromptMeasurementIdentityCreate(BaseModel):
    canonical_brand_name: str = Field(default="", max_length=160)
    accepted_aliases: list[str] = Field(default_factory=list, max_length=50)
    official_domains: list[str] = Field(default_factory=list, max_length=50)
    official_urls: list[str] = Field(default_factory=list, max_length=50)
    confirmed_by: str = Field(default="", max_length=120)


class SinglePromptRetestCreate(BaseModel):
    project_id: int
    prompt_id: int
    confirmation_id: str = Field(min_length=1, max_length=80)
    publication_id: str = Field(min_length=1, max_length=80)
    confirmation_snapshot_hash: str = Field(min_length=64, max_length=64)
    publication_report_hash: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=120)
    sample_count: int | None = Field(default=None, ge=1, le=10)
    measurement_identity: SinglePromptMeasurementIdentityCreate | None = None


class SinglePromptRetestAction(BaseModel):
    project_id: int
    prompt_id: int


class SinglePromptSemanticMeasurementCreate(SinglePromptRetestAction):
    authorize_external_llm: bool = False
