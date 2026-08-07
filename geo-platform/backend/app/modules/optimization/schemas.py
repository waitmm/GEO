from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class ContentFeatureChange(BaseModel):
    feature: str
    description: str = ""
    before: Any = None
    after: Any = None
    location: str = ""


def normalize_content_feature_changes(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("content_feature_changes must be a list")
    normalized = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if text:
                normalized.append({"feature": "LEGACY_NOTE", "description": text})
            continue
        if isinstance(item, dict):
            feature = str(item.get("feature") or "").strip()
            description = str(item.get("description") or "").strip()
            if not feature:
                feature = "CUSTOM_CHANGE"
            if not description:
                description = feature
            normalized.append({**item, "feature": feature, "description": description})
            continue
        raise ValueError("content_feature_changes items must be strings or objects")
    return normalized


class OptimizationIssueCreate(BaseModel):
    project_id: int
    prompt_id: Optional[int] = None
    cluster_id: Optional[int] = None
    issue_type: str = "brand_not_recommended"
    severity: int = Field(default=3, ge=1, le=5)
    confidence_level: str = "medium"
    run_ids: list[int] = Field(default_factory=list)
    observed_facts: dict[str, Any] = Field(default_factory=dict)
    possible_causes: list[str] = Field(default_factory=list)
    diagnosis_summary: str = ""


class OptimizationIssueRead(BaseModel):
    id: int
    project_id: int
    prompt_id: Optional[int] = None
    prompt_text: str = ""
    cluster_id: Optional[int] = None
    issue_type: str
    status: str
    severity: int
    confidence_level: str
    observation_start: Optional[datetime] = None
    observation_end: Optional[datetime] = None
    analyzable_sample_count: int
    observed_facts: dict[str, Any] = Field(default_factory=dict)
    possible_causes: list[str] = Field(default_factory=list)
    diagnosis_summary: str
    rejected_reason: str = ""
    run_ids: list[int] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    confirmed_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class IssueStatusPayload(BaseModel):
    note: str = ""


class OptimizationActionCreate(BaseModel):
    action_type: str = "content_update"
    target_type: str = "owned_content"
    target_url: str = ""
    priority: int = Field(default=3, ge=1, le=5)
    owner: str = ""
    action_summary: str
    action_detail: str = ""
    content_feature_changes: list[ContentFeatureChange] = Field(default_factory=list)

    @field_validator("content_feature_changes", mode="before")
    @classmethod
    def _normalize_changes(cls, value: Any) -> list[dict[str, Any]]:
        return normalize_content_feature_changes(value)


class OptimizationActionUpdate(BaseModel):
    action_type: Optional[str] = None
    target_type: Optional[str] = None
    target_url: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[int] = Field(default=None, ge=1, le=5)
    owner: Optional[str] = None
    action_summary: Optional[str] = None
    action_detail: Optional[str] = None
    content_feature_changes: Optional[list[ContentFeatureChange]] = None

    @field_validator("content_feature_changes", mode="before")
    @classmethod
    def _normalize_changes(cls, value: Any) -> list[dict[str, Any]]:
        return normalize_content_feature_changes(value)


class ActionReleasePayload(BaseModel):
    release_note: str
    release_evidence: dict[str, Any] = Field(default_factory=dict)
    validation_wait_hours: int = Field(default=24, ge=0, le=720)
    release_confirmed: bool = False


class PageSnapshotCreate(BaseModel):
    url: str
    snapshot_type: str = "PRE_RELEASE"
    experiment_id: Optional[int] = None


class PageSnapshotRead(BaseModel):
    id: int
    project_id: int
    experiment_id: Optional[int] = None
    target_url: str = ""
    url: str
    http_status: Optional[int] = None
    final_url: str = ""
    canonical_url: str = ""
    captured_at: datetime
    raw_html: str = ""
    html_hash: str = ""
    title: str = ""
    meta_description: str = ""
    h1: str = ""
    main_text: str = ""
    main_text_hash: str = ""
    section_headings: list[str] = Field(default_factory=list)
    structured_data: list[dict[str, Any]] = Field(default_factory=list)
    internal_links: list[str] = Field(default_factory=list)
    robots_directives: dict[str, Any] = Field(default_factory=dict)
    snapshot_type: str
    capture_status: str
    capture_error: str = ""
    created_at: datetime
    updated_at: datetime


class OptimizationHypothesisCreate(BaseModel):
    evidence_package_id: int
    issue_id: Optional[int] = None
    observed_problem: str
    hypothesized_cause: str
    core_mechanism: str
    target_metric: str = "target_page_retrieval_rate"
    baseline_value: str = ""
    expected_direction: str = "increase"
    entry_observed_condition: str = ""
    sustained_improvement_condition: str = ""
    invalidating_result: str = ""
    changed_features: list[str] = Field(default_factory=list)
    controlled_variables: list[str] = Field(default_factory=list)
    accepted_by: str = "human"
    review_note: str = ""


class OptimizationHypothesisRead(BaseModel):
    id: int
    project_id: int
    issue_id: int
    experiment_id: int
    evidence_package_id: int
    status: str
    observed_problem: str
    hypothesized_cause: str
    core_mechanism: str
    target_metric: str
    baseline_value: str
    expected_direction: str
    entry_observed_condition: str
    sustained_improvement_condition: str
    invalidating_result: str
    changed_features: list[str] = Field(default_factory=list)
    controlled_variables: list[str] = Field(default_factory=list)
    accepted_by: str = ""
    accepted_at: Optional[datetime] = None
    review_note: str = ""
    created_at: datetime
    updated_at: datetime


class ReleaseConfirmationPayload(BaseModel):
    hypothesis_id: int
    pre_release_snapshot_id: int
    post_release_snapshot_id: int
    planned_feature_changes: list[ContentFeatureChange] = Field(default_factory=list)
    deployed_feature_changes: list[ContentFeatureChange] = Field(default_factory=list)
    undeployed_feature_changes: list[ContentFeatureChange] = Field(default_factory=list)
    release_note: str
    confirmed_by: str
    online_verification_status: str = "VERIFIED"
    validation_wait_hours: int = Field(default=24, ge=0, le=720)

    @field_validator("planned_feature_changes", "deployed_feature_changes", "undeployed_feature_changes", mode="before")
    @classmethod
    def _normalize_release_changes(cls, value: Any) -> list[dict[str, Any]]:
        return normalize_content_feature_changes(value)


class ReleaseAuditRead(BaseModel):
    id: int
    experiment_id: int
    hypothesis_id: int
    pre_release_snapshot_id: int
    post_release_snapshot_id: int
    planned_feature_changes: list[ContentFeatureChange] = Field(default_factory=list)
    deployed_feature_changes: list[ContentFeatureChange] = Field(default_factory=list)
    undeployed_feature_changes: list[ContentFeatureChange] = Field(default_factory=list)
    release_note: str
    confirmed_by: str
    confirmed_at: datetime
    online_verification_status: str
    correction_of_id: Optional[int] = None
    correction_reason: str = ""
    created_at: datetime
    updated_at: datetime


class StrategyGenerationCreate(BaseModel):
    evidence_package_id: int
    experiment_id: Optional[int] = None
    target_url: str = ""
    max_hypotheses: int = Field(default=3, ge=1, le=3)


class StrategyCandidateReviewPayload(BaseModel):
    review_status: str
    reviewed_by: str = "human"
    review_note: str = ""
    human_edited_payload: dict[str, Any] = Field(default_factory=dict)


class StrategyCandidateRead(BaseModel):
    id: int
    project_id: int
    experiment_id: Optional[int] = None
    evidence_package_id: int
    target_url: str
    provider: str
    model: str
    prompt_version: str
    prompt_text: str
    generated_at: datetime
    generation_status: str
    original_llm_payload: dict[str, Any] = Field(default_factory=dict)
    structured_payload: dict[str, Any] = Field(default_factory=dict)
    human_edited_payload: dict[str, Any] = Field(default_factory=dict)
    evidence_validation_status: str
    evidence_validation_errors: list[str] = Field(default_factory=list)
    evidence_validation_warnings: list[str] = Field(default_factory=list)
    evidence_validated_at: Optional[datetime] = None
    evidence_validator_version: str = ""
    hypothesis_validation_status: str
    hypothesis_validation_errors: list[str] = Field(default_factory=list)
    hypothesis_validation_warnings: list[str] = Field(default_factory=list)
    hypothesis_validated_at: Optional[datetime] = None
    hypothesis_validator_version: str = ""
    review_status: str
    reviewed_by: str = ""
    reviewed_at: Optional[datetime] = None
    review_note: str = ""
    converted_hypothesis_id: Optional[int] = None
    experiment_plan: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ExperimentPlanRead(BaseModel):
    strategy_candidate_id: int
    readiness_status: str
    readiness_errors: list[str] = Field(default_factory=list)
    readiness_warnings: list[str] = Field(default_factory=list)
    experiment_id: Optional[int] = None
    action_id: Optional[int] = None
    hypothesis_id: Optional[int] = None
    plan_payload: dict[str, Any] = Field(default_factory=dict)


class OptimizationActionRead(BaseModel):
    id: int
    issue_id: int
    action_type: str
    target_type: str
    target_url: str
    status: str
    priority: int
    owner: str
    action_summary: str
    action_detail: str
    content_feature_changes: list[ContentFeatureChange] = Field(default_factory=list)
    planned_at: Optional[datetime] = None
    released_at: Optional[datetime] = None
    release_note: str = ""
    release_evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class OptimizationExperimentCreate(BaseModel):
    hypothesis: str
    target_prompt_scope: list[int] = Field(default_factory=list)
    control_prompt_scope: list[int] = Field(default_factory=list)
    sentinel_prompt_scope: list[int] = Field(default_factory=list)
    environment_scope: dict[str, Any] = Field(default_factory=lambda: {"platform": "wenxin", "source_type": "browser_audit"})
    sample_plan: dict[str, Any] = Field(default_factory=lambda: {"baseline_samples": 3, "validation_samples": 3})
    primary_metric: str = "target_page_retrieval_rate"
    secondary_metrics: list[str] = Field(default_factory=lambda: ["target_page_conversion_rate", "brand_mention_rate", "brand_recommendation_rate", "official_reference_rate", "avg_reference_count"])


class ExperimentRunsPayload(BaseModel):
    run_ids: list[int] = Field(default_factory=list)


class ExperimentRetestCreate(BaseModel):
    sample_count: int = Field(default=3, ge=1, le=20)
    collection_mode: str = "single_continuous"
    batch_name: str = ""
    execute_now: bool = False


class ExperimentRetestRead(BaseModel):
    experiment_id: int
    batch_id: int
    task_id: int
    run_ids: list[int] = Field(default_factory=list)
    queued_run_count: int = 0
    status: str


class ExperimentConclusionPayload(BaseModel):
    conclusion: str
    conclusion_reason: str
    confounders: list[str] = Field(default_factory=list)
    resolved: bool = False


class MetricSnapshot(BaseModel):
    sample_count: int = 0
    valid_sample_count: int = 0
    valid_run_count: int = 0
    brand_mention_count: int = 0
    brand_mention_rate: float = 0
    brand_recommendation_count: int = 0
    brand_recommendation_rate: float = 0
    official_reference_count: int = 0
    official_reference_rate: float = 0
    avg_reference_count: float = 0
    reference_complete_count: int = 0
    reference_complete_rate: float = 0
    target_page_retrieved_run_count: int = 0
    target_page_retrieval_rate: Optional[float] = None
    target_page_retrieval: dict[str, Any] = Field(default_factory=dict)
    target_page_retrieved_count: int = 0
    target_page_cited_count: int = 0
    target_page_conversion_rate: Optional[float] = None
    target_page_conversion: dict[str, Any] = Field(default_factory=dict)


class EvidencePackageCreate(BaseModel):
    prompt_id: Optional[int] = None
    run_ids: list[int] = Field(default_factory=list)
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    target_page_urls: list[str] = Field(default_factory=list)
    source_note: str = ""


class EvidencePackageRead(BaseModel):
    id: int
    project_id: int
    prompt_id: Optional[int] = None
    prompt_text: str = ""
    version: int
    schema_version: str
    metric_spec_version: str
    source_run_ids: list[int] = Field(default_factory=list)
    target_page_urls: list[str] = Field(default_factory=list)
    environment_snapshot: dict[str, Any] = Field(default_factory=dict)
    package_payload: dict[str, Any] = Field(default_factory=dict)
    package_hash: str
    status: str
    superseded_by_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class OptimizationExperimentRead(BaseModel):
    id: int
    action_id: int
    status: str
    hypothesis: str
    target_prompt_scope: list[int] = Field(default_factory=list)
    control_prompt_scope: list[int] = Field(default_factory=list)
    sentinel_prompt_scope: list[int] = Field(default_factory=list)
    environment_scope: dict[str, Any] = Field(default_factory=dict)
    sample_plan: dict[str, Any] = Field(default_factory=dict)
    primary_metric: str
    secondary_metrics: list[str] = Field(default_factory=list)
    baseline_start: Optional[datetime] = None
    baseline_end: Optional[datetime] = None
    baseline_run_ids: list[int] = Field(default_factory=list)
    baseline_metrics: dict[str, Any] = Field(default_factory=dict)
    release_blocked: bool = False
    release_blocked_reason: str = ""
    released_at: Optional[datetime] = None
    first_recrawled_at: Optional[datetime] = None
    validation_not_before: Optional[datetime] = None
    validation_start: Optional[datetime] = None
    validation_end: Optional[datetime] = None
    validation_run_ids: list[int] = Field(default_factory=list)
    result_metrics: dict[str, Any] = Field(default_factory=dict)
    comparison: dict[str, Any] = Field(default_factory=dict)
    per_prompt_results: list[dict[str, Any]] = Field(default_factory=list)
    per_environment_results: list[dict[str, Any]] = Field(default_factory=list)
    confounders: list[str] = Field(default_factory=list)
    conclusion: str = ""
    conclusion_reason: str = ""
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None


class EvidenceRunRead(BaseModel):
    id: int
    prompt_id: int
    status: str
    run_sequence: int
    sample_index: int
    original_query: str
    answer_text: str = ""
    brand_mentioned: bool
    brand_recommendation_level: int
    reference_complete: bool
    parsed_reference_count: int
    resolved_url_count: int
    created_at: datetime


class EvidenceReferenceRead(BaseModel):
    id: int
    run_id: int
    reference_index: int
    display_title: str
    url: str
    domain: str
    is_official_domain: bool
    is_competitor_domain: bool
    occurrence_count: int = 1
    run_ids: list[int] = Field(default_factory=list)
    reference_indices: list[int] = Field(default_factory=list)


class EvidenceRetrievalRead(BaseModel):
    id: int
    run_id: int
    rank: int
    title: str
    url: str
    domain: str
    snippet: str
    occurrence_count: int = 1
    run_ids: list[int] = Field(default_factory=list)
    ranks: list[int] = Field(default_factory=list)


class SourceAnalysisRead(BaseModel):
    source_kind: str
    source_id: int
    run_id: int
    run_ids: list[int] = Field(default_factory=list)
    run_count: int = 1
    cited: bool
    retrieval_rank: Optional[int] = None
    title: str
    url: str
    domain: str
    ownership: str
    source_role: str
    content_format: str
    prompt_overlap_score: float = 0
    brand_signal: str = "none"
    freshness_signal: str = "unknown"
    authority_signal: str = "medium"
    platform: str = "web"
    author_name: str = ""
    published_date: str = ""
    source_score: int = 0
    score_breakdown: dict[str, Any] = Field(default_factory=dict)
    score_explanation: list[str] = Field(default_factory=list)
    citation_occurrence_count: int = 0
    cited_run_count: int = 0
    answer_citation_rate: float = 0
    avg_reference_position: float = 0
    account_platform: str = "web"
    account_identity: str = "unknown"
    account_identity_reason: str = ""
    answer_usage: str = "unknown"
    answer_usage_reason: str = ""
    citation_reason: str
    citation_basis: list[str] = Field(default_factory=list)
    content_structure_signals: list[str] = Field(default_factory=list)
    time_signal_detail: str = ""
    cross_source_comparison: dict[str, Any] = Field(default_factory=dict)
    diagnostic_angles: list[dict[str, Any]] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    comparison_note: str = ""


class OptimizationEvidenceChainRead(BaseModel):
    issue: OptimizationIssueRead
    actions: list[OptimizationActionRead] = Field(default_factory=list)
    experiments: list[OptimizationExperimentRead] = Field(default_factory=list)
    runs: list[EvidenceRunRead] = Field(default_factory=list)
    references: list[EvidenceReferenceRead] = Field(default_factory=list)
    retrieval_candidates: list[EvidenceRetrievalRead] = Field(default_factory=list)
    source_analysis: list[SourceAnalysisRead] = Field(default_factory=list)
    hypotheses: list[OptimizationHypothesisRead] = Field(default_factory=list)
    strategy_candidates: list[StrategyCandidateRead] = Field(default_factory=list)
    page_snapshots: list[PageSnapshotRead] = Field(default_factory=list)
    release_audits: list[ReleaseAuditRead] = Field(default_factory=list)
