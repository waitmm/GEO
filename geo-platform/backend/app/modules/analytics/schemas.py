from __future__ import annotations

from pydantic import BaseModel, Field


class PromptSummary(BaseModel):
    total_prompts: int = 0
    total_clusters: int = 0
    prompts_with_runs: int = 0
    configured_samples: int = 0
    collected_samples: int = 0
    valid_samples: int = 0


class PresenceRow(BaseModel):
    entity_type: str
    name: str
    observed_runs: int = 0
    sample_runs: int = 0
    observed_share: float = 0


class RecommendationPresence(BaseModel):
    explicit_recommendation: int = 0
    general_mention: int = 0
    not_observed: int = 0
    sample_runs: int = 0


class CitationDomainRow(BaseModel):
    domain: str
    occurrences: int
    run_count: int
    prompt_count: int


class CitationUrlRow(BaseModel):
    url: str
    title: str = ""
    domain: str = ""
    occurrences: int
    run_count: int
    prompt_count: int


class ReferenceQuality(BaseModel):
    ui_declared_count: int = 0
    dom_reference_count: int = 0
    parsed_reference_count: int = 0
    resolved_url_count: int = 0
    complete_runs: int = 0
    assessed_runs: int = 0
    url_resolution_rate: float = 0


class DataQuality(BaseModel):
    total_runs: int = 0
    success: int = 0
    blocked: int = 0
    collector_failed: int = 0
    pending: int = 0
    references: ReferenceQuality = Field(default_factory=ReferenceQuality)


class ValidationDashboard(BaseModel):
    project_id: int
    sample_label: str = "Validation Sample"
    prompts: PromptSummary
    brand_presence: PresenceRow
    competitor_presence: list[PresenceRow] = Field(default_factory=list)
    recommendation_presence: RecommendationPresence
    top_citation_domains: list[CitationDomainRow] = Field(default_factory=list)
    top_citation_urls: list[CitationUrlRow] = Field(default_factory=list)
    data_quality: DataQuality

