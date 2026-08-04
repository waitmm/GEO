from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    name: Mapped[str] = mapped_column(String(120))


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    plan_type: Mapped[str] = mapped_column(String(50), default="v0")

    projects: Mapped[list["Project"]] = relationship(back_populates="organization")


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    brand_name: Mapped[str] = mapped_column(String(160))
    brand_aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    website_url: Mapped[str] = mapped_column(String(500), default="")
    industry: Mapped[str] = mapped_column(String(160), default="")
    region: Mapped[str] = mapped_column(String(80), default="CN")
    language: Mapped[str] = mapped_column(String(40), default="zh-CN")
    status: Mapped[str] = mapped_column(String(40), default="active")

    organization: Mapped[Organization] = relationship(back_populates="projects")
    competitors: Mapped[list["Competitor"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    prompts: Mapped[list["Prompt"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Topic(Base, TimestampMixin):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class PromptCluster(Base, TimestampMixin):
    __tablename__ = "prompt_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    topic_id: Mapped[Optional[int]] = mapped_column(ForeignKey("topics.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    sample_count: Mapped[int] = mapped_column(Integer, default=3)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class MonitoringBatch(Base, TimestampMixin):
    __tablename__ = "monitoring_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    platform: Mapped[str] = mapped_column(String(80), default="wenxin", index=True)
    collection_mode: Mapped[str] = mapped_column(String(80), default="single_independent")
    sample_count: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Competitor(Base):
    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    website_url: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped[Project] = relationship(back_populates="competitors")


class Prompt(Base, TimestampMixin):
    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    topic_id: Mapped[Optional[int]] = mapped_column(ForeignKey("topics.id"), nullable=True, index=True)
    cluster_id: Mapped[Optional[int]] = mapped_column(ForeignKey("prompt_clusters.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(180), default="")
    prompt_text: Mapped[str] = mapped_column(Text)
    prompt_group: Mapped[str] = mapped_column(String(120), default="")
    intent_type: Mapped[str] = mapped_column(String(80), default="category_awareness")
    importance: Mapped[int] = mapped_column(Integer, default=3)
    sample_count: Mapped[int] = mapped_column(Integer, default=3)
    daily_tracking_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_schedule_time: Mapped[str] = mapped_column(String(8), default="09:00")
    daily_sample_count: Mapped[int] = mapped_column(Integer, default=1)
    last_scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    project: Mapped[Project] = relationship(back_populates="prompts")


class MonitorRun(Base):
    __tablename__ = "monitor_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    run_type: Mapped[str] = mapped_column(String(40), default="manual")
    status: Mapped[str] = mapped_column(String(40), default="pending")
    platform_keys_json: Mapped[str] = mapped_column(Text, default="[]")
    prompt_count: Mapped[int] = mapped_column(Integer, default=0)
    repeat_count: Mapped[int] = mapped_column(Integer, default=3)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    cost_estimate: Mapped[float] = mapped_column(Float, default=0)
    error_summary_json: Mapped[str] = mapped_column(Text, default="{}")


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("monitor_runs.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    platform_key: Mapped[str] = mapped_column(String(80), index=True)
    entry_type: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(120), default="")
    model_version: Mapped[str] = mapped_column(String(120), default="")
    web_search_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sample_index: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(40), default="success")
    answer_text: Mapped[str] = mapped_column(Text, default="")
    raw_response_json: Mapped[str] = mapped_column(Text, default="{}")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_estimate: Mapped[float] = mapped_column(Float, default=0)
    queried_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    content_hash: Mapped[str] = mapped_column(String(64), default="")


class AnswerCitation(Base):
    __tablename__ = "answer_citations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    observation_id: Mapped[int] = mapped_column(ForeignKey("observations.id"), index=True)
    url: Mapped[str] = mapped_column(String(800))
    title: Mapped[str] = mapped_column(String(300), default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    source_name: Mapped[str] = mapped_column(String(160), default="")
    domain: Mapped[str] = mapped_column(String(255), default="")
    position: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ExtractedMention(Base):
    __tablename__ = "extracted_mentions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    observation_id: Mapped[int] = mapped_column(ForeignKey("observations.id"), index=True)
    brand_mentioned: Mapped[bool] = mapped_column(Boolean, default=False)
    brand_recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    brand_first_position: Mapped[int] = mapped_column(Integer, default=-1)
    competitors_json: Mapped[str] = mapped_column(Text, default="[]")
    cited_official_domain: Mapped[bool] = mapped_column(Boolean, default=False)
    cited_competitor_domains_json: Mapped[str] = mapped_column(Text, default="[]")
    sentiment: Mapped[str] = mapped_column(String(40), default="neutral")
    extraction_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BrowserMonitorTask(Base):
    __tablename__ = "browser_monitor_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("monitoring_batches.id"), nullable=True, index=True)
    platform: Mapped[str] = mapped_column(String(80), default="wenxin", index=True)
    source_type: Mapped[str] = mapped_column(String(80), default="browser_audit", index=True)
    adapter: Mapped[str] = mapped_column(String(80), default="wenxin_web_audit", index=True)
    question_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    run_count: Mapped[int] = mapped_column(Integer, default=1)
    schedule_type: Mapped[str] = mapped_column(String(40), default="manual")
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    created_by: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BrowserMonitorRun(Base):
    __tablename__ = "browser_monitor_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_tasks.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("monitoring_batches.id"), nullable=True, index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    platform: Mapped[str] = mapped_column(String(80), default="wenxin", index=True)
    source_type: Mapped[str] = mapped_column(String(80), default="browser_audit", index=True)
    adapter: Mapped[str] = mapped_column(String(80), default="wenxin_web_audit", index=True)
    run_sequence: Mapped[int] = mapped_column(Integer, default=1)
    sample_index: Mapped[int] = mapped_column(Integer, default=1)
    collection_mode: Mapped[str] = mapped_column(String(80), default="single_independent")
    collector_id: Mapped[str] = mapped_column(String(160), default="")
    browser: Mapped[str] = mapped_column(String(80), default="")
    browser_version: Mapped[str] = mapped_column(String(120), default="")
    os: Mapped[str] = mapped_column(String(120), default="")
    profile_identifier: Mapped[str] = mapped_column(String(200), default="")
    conversation_id: Mapped[str] = mapped_column(String(240), default="")
    network_region: Mapped[str] = mapped_column(String(120), default="unknown")
    collector_version: Mapped[str] = mapped_column(String(80), default="")
    parser_version: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(80), default="queued")
    original_query: Mapped[str] = mapped_column(Text, default="")
    page_query: Mapped[str] = mapped_column(Text, default="")
    retrieval_query: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    answer_text: Mapped[str] = mapped_column(Text, default="")
    answer_html: Mapped[str] = mapped_column(Text, default="")
    answer_char_count: Mapped[int] = mapped_column(Integer, default=0)
    expected_reference_count: Mapped[int] = mapped_column(Integer, default=0)
    detected_reference_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved_reference_count: Mapped[int] = mapped_column(Integer, default=0)
    ui_declared_count: Mapped[int] = mapped_column(Integer, default=0)
    dom_reference_count: Mapped[int] = mapped_column(Integer, default=0)
    parsed_reference_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved_url_count: Mapped[int] = mapped_column(Integer, default=0)
    unresolved_reference_count: Mapped[int] = mapped_column(Integer, default=0)
    reference_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    brand_mentioned: Mapped[bool] = mapped_column(Boolean, default=False)
    brand_mention_count: Mapped[int] = mapped_column(Integer, default=0)
    brand_first_position: Mapped[int] = mapped_column(Integer, default=-1)
    brand_recommendation_level: Mapped[int] = mapped_column(Integer, default=0)
    error_stage: Mapped[str] = mapped_column(String(80), default="")
    error_type: Mapped[str] = mapped_column(String(80), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    outcome_category: Mapped[str] = mapped_column(String(40), default="")
    blocked_type: Mapped[str] = mapped_column(String(80), default="")
    blocked_reason: Mapped[str] = mapped_column(Text, default="")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReferenceSource(Base):
    __tablename__ = "reference_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id"), index=True)
    reference_index: Mapped[int] = mapped_column(Integer, default=1)
    display_title: Mapped[str] = mapped_column(String(500), default="")
    matched_title: Mapped[str] = mapped_column(String(500), default="")
    url: Mapped[str] = mapped_column(String(1200), default="")
    canonical_url: Mapped[str] = mapped_column(String(1200), default="")
    domain: Mapped[str] = mapped_column(String(255), default="")
    platform_name: Mapped[str] = mapped_column(String(160), default="")
    resolution_method: Mapped[str] = mapped_column(String(120), default="")
    match_confidence: Mapped[float] = mapped_column(Float, default=0)
    evidence_path: Mapped[str] = mapped_column(String(800), default="")
    relevance_label: Mapped[str] = mapped_column(String(80), default="unreviewed")
    quality_label: Mapped[str] = mapped_column(String(80), default="unknown")
    is_official_domain: Mapped[bool] = mapped_column(Boolean, default=False)
    is_competitor_domain: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RetrievalCandidate(Base):
    __tablename__ = "retrieval_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id"), index=True)
    retrieval_query: Mapped[str] = mapped_column(Text, default="")
    rank: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(500), default="")
    url: Mapped[str] = mapped_column(String(1200), default="")
    canonical_url: Mapped[str] = mapped_column(String(1200), default="")
    domain: Mapped[str] = mapped_column(String(255), default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    evidence_path: Mapped[str] = mapped_column(String(800), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PromptDailyReport(Base, TimestampMixin):
    __tablename__ = "prompt_daily_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    report_date: Mapped[str] = mapped_column(String(10), index=True)
    run_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    brand_mention_count: Mapped[int] = mapped_column(Integer, default=0)
    brand_mention_rate: Mapped[float] = mapped_column(Float, default=0)
    avg_reference_count: Mapped[float] = mapped_column(Float, default=0)
    top_reference_domains_json: Mapped[str] = mapped_column(Text, default="[]")
    top_retrieval_domains_json: Mapped[str] = mapped_column(Text, default="[]")
    summary: Mapped[str] = mapped_column(Text, default="")
    recommendations_json: Mapped[str] = mapped_column(Text, default="[]")


class BrandMention(Base):
    __tablename__ = "brand_mentions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id"), index=True)
    brand_name: Mapped[str] = mapped_column(String(160), default="")
    alias_matched: Mapped[str] = mapped_column(String(160), default="")
    mention_count: Mapped[int] = mapped_column(Integer, default=0)
    first_char_position: Mapped[int] = mapped_column(Integer, default=-1)
    first_paragraph_index: Mapped[int] = mapped_column(Integer, default=-1)
    recommendation_level: Mapped[int] = mapped_column(Integer, default=0)
    context_snippets_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RunArtifact(Base):
    __tablename__ = "run_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(80), index=True)
    storage_path: Mapped[str] = mapped_column(String(800))
    mime_type: Mapped[str] = mapped_column(String(120), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
