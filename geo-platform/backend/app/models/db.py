from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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
    evidence_packages: Mapped[list["OptimizationEvidencePackage"]] = relationship(cascade="all, delete-orphan")
    page_snapshots: Mapped[list["PageSnapshot"]] = relationship(cascade="all, delete-orphan")


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


class SourceMetadataCache(Base, TimestampMixin):
    __tablename__ = "source_metadata_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    url: Mapped[str] = mapped_column(String(1200), unique=True, index=True)
    domain: Mapped[str] = mapped_column(String(255), default="", index=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    author_name: Mapped[str] = mapped_column(String(240), default="")
    published_date: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    raw_metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")


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


class OptimizationEvidencePackage(Base, TimestampMixin):
    __tablename__ = "optimization_evidence_packages"
    __table_args__ = (
        UniqueConstraint("project_id", "prompt_id", "version", name="uq_evidence_package_project_prompt_version"),
        UniqueConstraint("project_id", "package_hash", name="uq_evidence_package_project_hash"),
        Index("ix_evidence_package_project_prompt_status", "project_id", "prompt_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    prompt_id: Mapped[Optional[int]] = mapped_column(ForeignKey("prompts.id", ondelete="SET NULL"), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    schema_version: Mapped[str] = mapped_column(String(40), default="b1.v1")
    metric_spec_version: Mapped[str] = mapped_column(String(40), default="metric.v1")
    source_run_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    target_page_urls_json: Mapped[str] = mapped_column(Text, default="[]")
    environment_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    package_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    package_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    superseded_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("optimization_evidence_packages.id"), nullable=True)


class PageSnapshot(Base, TimestampMixin):
    __tablename__ = "page_snapshots"
    __table_args__ = (
        Index("ix_page_snapshots_project_url_type", "project_id", "url", "snapshot_type"),
        Index("ix_page_snapshots_experiment_type", "experiment_id", "snapshot_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    experiment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("optimization_experiments.id", ondelete="SET NULL"), nullable=True, index=True)
    target_url: Mapped[str] = mapped_column(String(1200), default="", index=True)
    url: Mapped[str] = mapped_column(String(1200), default="")
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    final_url: Mapped[str] = mapped_column(String(1200), default="")
    canonical_url: Mapped[str] = mapped_column(String(1200), default="")
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    raw_html: Mapped[str] = mapped_column(Text, default="")
    html_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    meta_description: Mapped[str] = mapped_column(Text, default="")
    h1: Mapped[str] = mapped_column(String(500), default="")
    main_text: Mapped[str] = mapped_column(Text, default="")
    main_text_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    section_headings_json: Mapped[str] = mapped_column(Text, default="[]")
    structured_data_json: Mapped[str] = mapped_column(Text, default="[]")
    internal_links_json: Mapped[str] = mapped_column(Text, default="[]")
    robots_directives_json: Mapped[str] = mapped_column(Text, default="{}")
    snapshot_type: Mapped[str] = mapped_column(String(40), default="PRE_RELEASE", index=True)
    capture_status: Mapped[str] = mapped_column(String(40), default="success", index=True)
    capture_error: Mapped[str] = mapped_column(Text, default="")


class OptimizationHypothesis(Base, TimestampMixin):
    __tablename__ = "optimization_hypotheses"
    __table_args__ = (
        Index("ix_optimization_hypotheses_experiment_status", "experiment_id", "status"),
        UniqueConstraint("experiment_id", "evidence_package_id", "status", name="uq_hypothesis_experiment_package_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("optimization_issues.id", ondelete="CASCADE"), index=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("optimization_experiments.id", ondelete="CASCADE"), index=True)
    evidence_package_id: Mapped[int] = mapped_column(ForeignKey("optimization_evidence_packages.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="ACCEPTED", index=True)
    observed_problem: Mapped[str] = mapped_column(Text, default="")
    hypothesized_cause: Mapped[str] = mapped_column(Text, default="")
    core_mechanism: Mapped[str] = mapped_column(Text, default="")
    target_metric: Mapped[str] = mapped_column(String(120), default="target_page_retrieval_rate")
    baseline_value: Mapped[str] = mapped_column(String(120), default="")
    expected_direction: Mapped[str] = mapped_column(String(40), default="increase")
    entry_observed_condition: Mapped[str] = mapped_column(Text, default="")
    sustained_improvement_condition: Mapped[str] = mapped_column(Text, default="")
    invalidating_result: Mapped[str] = mapped_column(Text, default="")
    changed_features_json: Mapped[str] = mapped_column(Text, default="[]")
    controlled_variables_json: Mapped[str] = mapped_column(Text, default="[]")
    accepted_by: Mapped[str] = mapped_column(String(120), default="human")
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")


class OptimizationStrategyCandidate(Base, TimestampMixin):
    __tablename__ = "optimization_strategy_candidates"
    __table_args__ = (
        Index("ix_strategy_candidates_project_status", "project_id", "review_status"),
        Index("ix_strategy_candidates_experiment_status", "experiment_id", "review_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    experiment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("optimization_experiments.id", ondelete="SET NULL"), nullable=True, index=True)
    evidence_package_id: Mapped[int] = mapped_column(ForeignKey("optimization_evidence_packages.id", ondelete="RESTRICT"), index=True)
    target_url: Mapped[str] = mapped_column(String(1200), default="", index=True)
    provider: Mapped[str] = mapped_column(String(120), default="")
    model: Mapped[str] = mapped_column(String(160), default="")
    prompt_version: Mapped[str] = mapped_column(String(120), default="")
    prompt_text: Mapped[str] = mapped_column(Text, default="")
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    generation_status: Mapped[str] = mapped_column(String(60), default="GENERATED", index=True)
    original_llm_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    structured_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    human_edited_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    # single executable truth — the only payload execution paths consume
    effective_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    effective_payload_version: Mapped[str] = mapped_column(String(40), default="")
    effective_validation_status: Mapped[str] = mapped_column(String(60), default="PENDING", index=True)
    effective_validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    evidence_validation_status: Mapped[str] = mapped_column(String(60), default="PENDING", index=True)
    evidence_validation_errors_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_validation_warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    evidence_validator_version: Mapped[str] = mapped_column(String(80), default="")
    hypothesis_validation_status: Mapped[str] = mapped_column(String(60), default="PENDING", index=True)
    hypothesis_validation_errors_json: Mapped[str] = mapped_column(Text, default="[]")
    hypothesis_validation_warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    hypothesis_validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    hypothesis_validator_version: Mapped[str] = mapped_column(String(80), default="")
    # P0-3: Formal strategy identity columns (not serialized in JSON)
    intervention_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    target_platform: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    target_asset: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    target_content_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    expected_primary_metric: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    source_package_id: Mapped[Optional[int]] = mapped_column(ForeignKey("optimization_evidence_packages.id", ondelete="SET NULL"), nullable=True, index=True)

    review_status: Mapped[str] = mapped_column(String(60), default="PENDING_REVIEW", index=True)
    reviewed_by: Mapped[str] = mapped_column(String(120), default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    converted_hypothesis_id: Mapped[Optional[int]] = mapped_column(ForeignKey("optimization_hypotheses.id"), nullable=True, index=True)
    experiment_plan_json: Mapped[str] = mapped_column(Text, default="{}")


class ReleaseAuditRecord(Base, TimestampMixin):
    __tablename__ = "release_audit_records"
    __table_args__ = (
        Index("ix_release_audit_records_experiment_status", "experiment_id", "online_verification_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("optimization_experiments.id", ondelete="CASCADE"), index=True)
    hypothesis_id: Mapped[int] = mapped_column(ForeignKey("optimization_hypotheses.id", ondelete="RESTRICT"), index=True)
    pre_release_snapshot_id: Mapped[int] = mapped_column(ForeignKey("page_snapshots.id", ondelete="RESTRICT"), index=True)
    post_release_snapshot_id: Mapped[int] = mapped_column(ForeignKey("page_snapshots.id", ondelete="RESTRICT"), index=True)
    planned_feature_changes_json: Mapped[str] = mapped_column(Text, default="[]")
    deployed_feature_changes_json: Mapped[str] = mapped_column(Text, default="[]")
    undeployed_feature_changes_json: Mapped[str] = mapped_column(Text, default="[]")
    release_note: Mapped[str] = mapped_column(Text, default="")
    confirmed_by: Mapped[str] = mapped_column(String(120), default="")
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    online_verification_status: Mapped[str] = mapped_column(String(80), default="PENDING", index=True)
    correction_of_id: Mapped[Optional[int]] = mapped_column(ForeignKey("release_audit_records.id"), nullable=True)
    correction_reason: Mapped[str] = mapped_column(Text, default="")


class OptimizationIssue(Base, TimestampMixin):
    __tablename__ = "optimization_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[Optional[int]] = mapped_column(ForeignKey("prompts.id"), nullable=True, index=True)
    cluster_id: Mapped[Optional[int]] = mapped_column(ForeignKey("prompt_clusters.id"), nullable=True, index=True)
    issue_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), default="candidate", index=True)
    severity: Mapped[int] = mapped_column(Integer, default=3)
    confidence_level: Mapped[str] = mapped_column(String(40), default="medium")
    observation_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    observation_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    analyzable_sample_count: Mapped[int] = mapped_column(Integer, default=0)
    observed_facts_json: Mapped[str] = mapped_column(Text, default="{}")
    possible_causes_json: Mapped[str] = mapped_column(Text, default="[]")
    diagnosis_summary: Mapped[str] = mapped_column(Text, default="")
    rejected_reason: Mapped[str] = mapped_column(Text, default="")
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class OptimizationIssueRun(Base, TimestampMixin):
    __tablename__ = "optimization_issue_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("optimization_issues.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id"), index=True)
    evidence_role: Mapped[str] = mapped_column(String(40), default="supporting")
    note: Mapped[str] = mapped_column(Text, default="")


class OptimizationAction(Base, TimestampMixin):
    __tablename__ = "optimization_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("optimization_issues.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(80), default="content_update", index=True)
    target_type: Mapped[str] = mapped_column(String(80), default="owned_content")
    target_url: Mapped[str] = mapped_column(String(1200), default="")
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    owner: Mapped[str] = mapped_column(String(120), default="")
    action_summary: Mapped[str] = mapped_column(Text, default="")
    action_detail: Mapped[str] = mapped_column(Text, default="")
    content_feature_changes_json: Mapped[str] = mapped_column(Text, default="[]")
    planned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    release_note: Mapped[str] = mapped_column(Text, default="")
    release_evidence_json: Mapped[str] = mapped_column(Text, default="{}")


class OptimizationExperiment(Base, TimestampMixin):
    __tablename__ = "optimization_experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    action_id: Mapped[int] = mapped_column(ForeignKey("optimization_actions.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    hypothesis: Mapped[str] = mapped_column(Text, default="")
    target_prompt_scope_json: Mapped[str] = mapped_column(Text, default="[]")
    control_prompt_scope_json: Mapped[str] = mapped_column(Text, default="[]")
    sentinel_prompt_scope_json: Mapped[str] = mapped_column(Text, default="[]")
    environment_scope_json: Mapped[str] = mapped_column(Text, default="{}")
    sample_plan_json: Mapped[str] = mapped_column(Text, default="{}")
    primary_metric: Mapped[str] = mapped_column(String(120), default="brand_recommendation_rate")
    secondary_metrics_json: Mapped[str] = mapped_column(Text, default="[]")
    baseline_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    baseline_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    baseline_run_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    baseline_metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    release_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    release_blocked_reason: Mapped[str] = mapped_column(Text, default="")
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    first_recrawled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    validation_not_before: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    validation_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    validation_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    validation_run_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    result_metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    comparison_json: Mapped[str] = mapped_column(Text, default="{}")
    per_prompt_results_json: Mapped[str] = mapped_column(Text, default="[]")
    per_environment_results_json: Mapped[str] = mapped_column(Text, default="[]")
    confounders_json: Mapped[str] = mapped_column(Text, default="[]")
    conclusion: Mapped[str] = mapped_column(Text, default="")
    conclusion_reason: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Citation Passage Intelligence — Golden Case models
# ---------------------------------------------------------------------------

class SourceDocument(Base, TimestampMixin):
    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    url: Mapped[str] = mapped_column(String(1200), index=True)
    canonical_url: Mapped[str] = mapped_column(String(1200), default="")
    domain: Mapped[str] = mapped_column(String(255), default="", index=True)
    source_type: Mapped[str] = mapped_column(String(40), default="CITED", index=True)
    fetch_status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    failure_reason: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(String(500), default="")
    author: Mapped[str] = mapped_column(String(240), default="")
    publish_time: Mapped[str] = mapped_column(String(80), default="")
    raw_html: Mapped[str] = mapped_column(Text, default="")
    clean_text: Mapped[str] = mapped_column(Text, default="")
    clean_text_hash: Mapped[str] = mapped_column(String(64), default="")
    content_blocks_json: Mapped[str] = mapped_column(Text, default="[]")
    fetch_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AnswerClaim(Base, TimestampMixin):
    __tablename__ = "answer_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id"), index=True)
    claim_index: Mapped[int] = mapped_column(Integer, default=0)
    raw_text: Mapped[str] = mapped_column(Text, default="")
    claim_type: Mapped[str] = mapped_column(String(60), default="")
    citation_anchor: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    citation_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    epistemic_status: Mapped[str] = mapped_column(String(40), default="FACT")
    provenance: Mapped[str] = mapped_column(String(40), default="RULE_DERIVED")
    reviewer: Mapped[str] = mapped_column(String(120), default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    answer_position: Mapped[int] = mapped_column(Integer, default=0)


class PassageAlignment(Base, TimestampMixin):
    __tablename__ = "passage_alignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    answer_claim_id: Mapped[int] = mapped_column(ForeignKey("answer_claims.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id"), index=True)
    citation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reference_sources.id"), nullable=True, index=True)
    source_document_id: Mapped[Optional[int]] = mapped_column(ForeignKey("source_documents.id"), nullable=True, index=True)
    passage_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    alignment_level: Mapped[str] = mapped_column(String(40), default="UNRESOLVED")
    alignment_method: Mapped[str] = mapped_column(String(80), default="")
    score: Mapped[float] = mapped_column(Float, default=0)
    evidence: Mapped[str] = mapped_column(Text, default="")
    epistemic_status: Mapped[str] = mapped_column(String(40), default="FACT")
    provenance: Mapped[str] = mapped_column(String(40), default="RULE_DERIVED")
    review_status: Mapped[str] = mapped_column(String(40), default="PENDING")
    reviewer: Mapped[str] = mapped_column(String(120), default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


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
