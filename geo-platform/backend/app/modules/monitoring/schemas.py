from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from pydantic import BaseModel, Field, PlainSerializer


def _serialize_utc(value: datetime) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        # 库内时间为 naive UTC，序列化时声明时区，前端 new Date() 才能正确换算本地时间
        return value.isoformat() + "Z"
    return value.astimezone(timezone.utc).isoformat()


UtcDatetime = Annotated[datetime, PlainSerializer(_serialize_utc, return_type=str, when_used="json")]


class BrowserTaskCreate(BaseModel):
    project_id: int
    batch_id: Optional[int] = None
    platform: str = "wenxin"
    source_type: str = "browser_audit"
    adapter: str = "wenxin_web_audit"
    question_ids: list[int]
    run_count: int = Field(default=1, ge=1, le=10)
    execute_now: bool = True


class BrowserTaskRead(BaseModel):
    id: int
    project_id: int
    batch_id: Optional[int] = None
    platform: str
    source_type: str
    adapter: str
    question_ids: list[int]
    run_count: int
    schedule_type: str
    status: str
    created_at: UtcDatetime
    updated_at: UtcDatetime
    queued_run_count: int = 0

    class Config:
        from_attributes = True


class BrowserRunRead(BaseModel):
    id: int
    task_id: int
    project_id: int
    batch_id: Optional[int] = None
    prompt_id: int
    platform: str
    source_type: str
    adapter: str
    run_sequence: int
    sample_index: int
    collection_mode: str
    collector_id: str
    browser: str
    browser_version: str
    os: str
    profile_identifier: str
    conversation_id: str
    network_region: str
    collector_version: str
    parser_version: str
    status: str
    stage: str
    original_query: str
    page_query: str
    retrieval_query: str
    started_at: Optional[UtcDatetime]
    finished_at: Optional[UtcDatetime]
    duration_ms: int
    answer_text: str
    answer_char_count: int
    expected_reference_count: int
    detected_reference_count: int
    resolved_reference_count: int
    ui_declared_count: int
    dom_reference_count: int
    parsed_reference_count: int
    resolved_url_count: int
    unresolved_reference_count: int
    reference_complete: bool
    brand_mentioned: bool
    brand_mention_count: int
    brand_first_position: int
    brand_recommendation_level: int
    error_stage: str
    error_type: str
    error_message: str
    outcome_category: str
    blocked_type: str
    blocked_reason: str
    retry_count: int
    created_at: UtcDatetime
    updated_at: UtcDatetime

    class Config:
        from_attributes = True


class BrowserTaskCreateResponse(BaseModel):
    task_ids: list[int]
    queued_run_count: int


class WenxinPluginImportRequest(BaseModel):
    project_id: int
    prompt_id: Optional[int] = None
    payload: dict[str, Any]


class BrowserQueueSummaryRead(BaseModel):
    project_id: Optional[int] = None
    queued: int = 0
    pending: int = 0
    running: int = 0
    success: int = 0
    partial_success: int = 0
    failed: int = 0
    blocked: int = 0
    total: int = 0
    latest_run_id: Optional[int] = None
    latest_status: str = ""
    latest_stage: str = ""
    latest_error_type: str = ""


class ReferenceSourceRead(BaseModel):
    id: int
    run_id: int
    reference_index: int
    display_title: str
    matched_title: str
    url: str
    canonical_url: str
    domain: str
    platform_name: str
    resolution_method: str
    match_confidence: float
    evidence_path: str
    relevance_label: str
    quality_label: str
    is_official_domain: bool
    is_competitor_domain: bool
    created_at: UtcDatetime

    class Config:
        from_attributes = True


class RetrievalCandidateRead(BaseModel):
    id: int
    run_id: int
    retrieval_query: str
    rank: int
    title: str
    url: str
    canonical_url: str
    domain: str
    snippet: str
    evidence_path: str
    created_at: UtcDatetime

    class Config:
        from_attributes = True


class RunArtifactRead(BaseModel):
    id: int
    run_id: int
    artifact_type: str
    storage_path: str
    mime_type: str
    size_bytes: int
    created_at: UtcDatetime

    class Config:
        from_attributes = True


class RunArtifactContentRead(BaseModel):
    id: int
    run_id: int
    artifact_type: str
    storage_path: str
    mime_type: str
    size_bytes: int
    content: str
    truncated: bool = False


class BrowserRunDetailRead(BrowserRunRead):
    references: list[ReferenceSourceRead] = []
    retrieval_candidates: list[RetrievalCandidateRead] = []
    artifacts: list[RunArtifactRead] = []
