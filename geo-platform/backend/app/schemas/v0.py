from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class OrganizationCreate(BaseModel):
    name: str
    plan_type: str = "v0"


class OrganizationRead(OrganizationCreate):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CompetitorCreate(BaseModel):
    name: str
    aliases: list[str] = []
    website_url: str = ""


class CompetitorRead(CompetitorCreate):
    id: int
    project_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class ProjectCreate(BaseModel):
    organization_id: Optional[int] = None
    name: str
    brand_name: str
    brand_aliases: list[str] = []
    website_url: str = ""
    competitors: list[CompetitorCreate] = []
    industry: str = ""
    region: str = "CN"
    language: str = "zh-CN"


class ProjectRead(BaseModel):
    id: int
    organization_id: int
    name: str
    brand_name: str
    brand_aliases: list[str]
    website_url: str
    industry: str
    region: str
    language: str
    status: str
    created_at: datetime
    updated_at: datetime
    competitors: list[CompetitorRead] = []


class PromptCreate(BaseModel):
    topic_id: Optional[int] = None
    cluster_id: Optional[int] = None
    title: str = ""
    prompt_text: str
    prompt_group: str = ""
    intent_type: str = "category_awareness"
    importance: int = Field(default=3, ge=1, le=5)
    sample_count: int = Field(default=3, ge=1, le=20)
    enabled: bool = True


class PromptRead(PromptCreate):
    id: int
    project_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TopicCreate(BaseModel):
    name: str
    description: str = ""
    sort_order: int = 0
    enabled: bool = True


class TopicUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    enabled: Optional[bool] = None


class TopicRead(TopicCreate):
    id: int
    project_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PromptClusterCreate(BaseModel):
    topic_id: Optional[int] = None
    name: str
    description: str = ""
    sample_count: int = Field(default=3, ge=1, le=20)
    sort_order: int = 0
    enabled: bool = True


class PromptClusterUpdate(BaseModel):
    topic_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    sample_count: Optional[int] = Field(default=None, ge=1, le=20)
    sort_order: Optional[int] = None
    enabled: Optional[bool] = None


class PromptClusterRead(PromptClusterCreate):
    id: int
    project_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MonitoringBatchCreate(BaseModel):
    name: str
    platform: str = "wenxin"
    collection_mode: str = "single_independent"
    sample_count: int = Field(default=3, ge=1, le=20)
    status: str = "draft"
    notes: str = ""


class MonitoringBatchUpdate(BaseModel):
    name: Optional[str] = None
    platform: Optional[str] = None
    collection_mode: Optional[str] = None
    sample_count: Optional[int] = Field(default=None, ge=1, le=20)
    status: Optional[str] = None
    notes: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class MonitoringBatchRead(MonitoringBatchCreate):
    id: int
    project_id: int
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MonitorRunCreate(BaseModel):
    prompt_ids: list[int]
    platform_keys: list[str] = ["mock"]
    repeat_count: int = Field(default=3, ge=1, le=10)


class MonitorRunRead(BaseModel):
    id: int
    project_id: int
    run_type: str
    status: str
    platform_keys: list[str]
    prompt_count: int
    repeat_count: int
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    success_count: int
    failure_count: int
    cost_estimate: float


class CitationRead(BaseModel):
    id: int
    url: str
    title: str
    snippet: str
    source_name: str
    domain: str
    position: int

    class Config:
        from_attributes = True


class MentionRead(BaseModel):
    brand_mentioned: bool
    brand_recommended: bool
    brand_first_position: int
    competitors: list[dict[str, Any]]
    cited_official_domain: bool
    cited_competitor_domains: list[str]
    sentiment: str


class ObservationRead(BaseModel):
    id: int
    run_id: int
    project_id: int
    prompt_id: int
    platform_key: str
    entry_type: str
    model: str
    model_version: str
    web_search_enabled: bool
    sample_index: int
    status: str
    answer_text: str
    latency_ms: int
    cost_estimate: float
    queried_at: datetime
    content_hash: str
    citations: list[CitationRead] = []
    mention: Optional[MentionRead] = None


class MetricsOverview(BaseModel):
    prompt_count: int
    observation_count: int
    platform_success_rate: float
    brand_mention_rate: float
    competitor_mention_rate: float
    official_citation_rate: float
