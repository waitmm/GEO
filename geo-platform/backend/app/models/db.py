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


class ProjectConfigurationVersion(Base):
    """Append-only project/brand configuration snapshot."""

    __tablename__ = "project_configuration_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_number", name="uq_project_configuration_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    configuration_version_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    snapshot_json: Mapped[str] = mapped_column(Text)
    snapshot_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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


class CompetitorRejection(Base):
    """人工判定「不是竞品」的实体，避免竞品候选反复出现。"""

    __tablename__ = "competitor_rejections"
    __table_args__ = (
        UniqueConstraint("project_id", "entity_name", name="uq_competitor_rejection_project_entity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    entity_name: Mapped[str] = mapped_column(String(240), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WorkflowConfirmation(Base):
    """工作流 Gap/Action 人工确认记录。"""

    __tablename__ = "workflow_confirmations"
    __table_args__ = (
        UniqueConstraint("project_id", "prompt_id", "step_key", name="uq_workflow_confirmation_project_prompt_step"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    prompt_id: Mapped[int] = mapped_column(Integer, index=True)
    step_key: Mapped[str] = mapped_column(String(40))
    decision_status: Mapped[str] = mapped_column(String(40), default="CONFIRMED")
    decision_note: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str] = mapped_column(String(120), default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PromptAnalysisRun(Base):
    """机器分析运行记录：区分「分析过但 0 事件」与「从未分析」。"""

    __tablename__ = "prompt_analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    prompt_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(40), default="COMPLETED")
    events_created: Mapped[int] = mapped_column(Integer, default=0)
    runs_associated: Mapped[int] = mapped_column(Integer, default=0)
    errors_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InterventionPlan(Base):
    """干预执行计划（一个 Prompt 取最新一条）。"""

    __tablename__ = "intervention_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    prompt_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    objective: Mapped[str] = mapped_column(Text, default="")
    target_brand_entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    gap_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    reason_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    intervention_goal: Mapped[str] = mapped_column(Text, default="UNRESOLVED")
    status: Mapped[str] = mapped_column(Text, default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by: Mapped[str] = mapped_column(Text, default="")
    approved_by: Mapped[str] = mapped_column(Text, default="")
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


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


class PromptVersion(Base):
    """Append-only Prompt configuration snapshot."""

    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("prompt_id", "version_number", name="uq_prompt_version"),
        Index("ix_prompt_versions_project_prompt", "project_id", "prompt_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prompt_version_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(Integer, index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    snapshot_json: Mapped[str] = mapped_column(Text)
    snapshot_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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


class SinglePromptAnalysis(Base):
    __tablename__ = "single_prompt_analyses"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_single_prompt_analysis_idempotency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    analysis_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    task_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("browser_monitor_tasks.id"), unique=True, index=True, nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(120))
    prompt_text_snapshot: Mapped[str] = mapped_column(Text)
    sampling_plan_json: Mapped[str] = mapped_column(Text)
    sampling_plan_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40), default="QUEUED", index=True)
    blocker_code: Mapped[str] = mapped_column(String(80), default="")
    blocker_detail: Mapped[str] = mapped_column(Text, default="")
    retry_history_json: Mapped[str] = mapped_column(Text, default="[]")
    active_attempt_token: Mapped[str] = mapped_column(String(64), default="")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SinglePromptOptimizationTask(Base, TimestampMixin):
    __tablename__ = "single_prompt_optimization_tasks"
    __table_args__ = (
        UniqueConstraint("analysis_id", "input_hash", name="uq_optimization_exact_input"),
        UniqueConstraint("project_id", "idempotency_key", name="uq_optimization_request"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analyses.analysis_id"), index=True)
    context_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analysis_contexts.context_id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    input_json: Mapped[str] = mapped_column(Text)
    input_hash: Mapped[str] = mapped_column(String(64))
    authorization_json: Mapped[str] = mapped_column(Text, default="{}")
    progress_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(48), default="QUEUED", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    blocker_code: Mapped[str] = mapped_column(String(80), default="")
    blocker_detail: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class SinglePromptAnalysisContext(Base):
    __tablename__ = "single_prompt_analysis_contexts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    context_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("single_prompt_analyses.analysis_id"), unique=True, index=True
    )
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    task_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("browser_monitor_tasks.id"), unique=True, index=True, nullable=True
    )
    result_version: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    run_scope_json: Mapped[str] = mapped_column(Text)
    run_scope_hash: Mapped[str] = mapped_column(String(64))
    raw_output_json: Mapped[str] = mapped_column(Text)
    raw_output_hash: Mapped[str] = mapped_column(String(64))
    valid_run_count: Mapped[int] = mapped_column(Integer)
    failed_run_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SinglePromptCitationManifest(Base):
    __tablename__ = "single_prompt_citation_manifests"
    __table_args__ = (
        UniqueConstraint("analysis_id", "version_number", name="uq_single_prompt_citation_manifest_version"),
        Index("ix_single_prompt_citation_manifest_context", "context_id", "version_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    manifest_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analyses.analysis_id"), index=True)
    context_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analysis_contexts.context_id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    raw_output_hash: Mapped[str] = mapped_column(String(64))
    url_identity_version: Mapped[str] = mapped_column(String(80))
    payload_json: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_count: Mapped[int] = mapped_column(Integer)
    occurrence_count: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SinglePromptSourcePreparation(Base):
    __tablename__ = "single_prompt_source_preparations"
    __table_args__ = (
        UniqueConstraint("citation_manifest_id", name="uq_single_prompt_source_preparation_manifest"),
        UniqueConstraint("analysis_id", "idempotency_key", name="uq_single_prompt_source_preparation_idempotency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    preparation_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analyses.analysis_id"), index=True)
    context_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analysis_contexts.context_id"), index=True)
    citation_manifest_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_citation_manifests.manifest_id"), index=True)
    citation_manifest_hash: Mapped[str] = mapped_column(String(64))
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    current_completion_manifest_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SinglePromptSourceDisposition(Base):
    __tablename__ = "single_prompt_source_dispositions"
    __table_args__ = (
        UniqueConstraint("preparation_id", "source_key", name="uq_single_prompt_source_disposition_key"),
        Index("ix_single_prompt_source_disposition_state", "preparation_id", "state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    disposition_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    preparation_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_source_preparations.preparation_id"), index=True)
    source_key: Mapped[str] = mapped_column(String(64))
    canonical_url: Mapped[str] = mapped_column(String(1200), default="")
    original_urls_json: Mapped[str] = mapped_column(Text, default="[]")
    reference_observations_json: Mapped[str] = mapped_column(Text, default="[]")
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(48), default="PENDING", index=True)
    active_snapshot_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    failure_code: Mapped[str] = mapped_column(String(80), default="")
    failure_detail: Mapped[str] = mapped_column(Text, default="")
    waiver_reason: Mapped[str] = mapped_column(Text, default="")
    waiver_impact: Mapped[str] = mapped_column(Text, default="")
    waived_by: Mapped[str] = mapped_column(String(120), default="")
    waived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SinglePromptPreparedSourceSnapshot(Base):
    __tablename__ = "single_prompt_prepared_source_snapshots"
    __table_args__ = (
        Index("ix_single_prompt_prepared_snapshot_source", "preparation_id", "source_key", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    snapshot_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    preparation_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_source_preparations.preparation_id"), index=True)
    context_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analysis_contexts.context_id"), index=True)
    citation_manifest_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_citation_manifests.manifest_id"), index=True)
    source_key: Mapped[str] = mapped_column(String(64), index=True)
    canonical_url: Mapped[str] = mapped_column(String(1200), default="")
    original_urls_json: Mapped[str] = mapped_column(Text, default="[]")
    reference_observations_json: Mapped[str] = mapped_column(Text, default="[]")
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(500), default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    clean_text: Mapped[str] = mapped_column(Text)
    artifact_path: Mapped[str] = mapped_column(String(1000))
    artifact_hash: Mapped[str] = mapped_column(String(64))
    passages_json: Mapped[str] = mapped_column(Text)
    passages_hash: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(80))
    acquisition_method: Mapped[str] = mapped_column(String(40), default="MANUAL")
    acquisition_receipt_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    coverage_scope: Mapped[str] = mapped_column(String(40))
    acquired_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    submitted_by: Mapped[str] = mapped_column(String(120))
    reused_from_snapshot_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    @property
    def fetch_status(self) -> str:
        return "SUCCESS"

    @property
    def failure_reason(self) -> str:
        return ""

    @property
    def fetched_at(self) -> datetime:
        return self.acquired_at

    @property
    def fetch_source(self) -> str:
        return "V2_SOURCE_PREPARATION"

class SinglePromptSourceCompletionManifest(Base):
    __tablename__ = "single_prompt_source_completion_manifests"
    __table_args__ = (
        UniqueConstraint("preparation_id", "version_number", name="uq_single_prompt_source_completion_version"),
        Index("ix_single_prompt_source_completion_context", "context_id", "version_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    manifest_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    preparation_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_source_preparations.preparation_id"), index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analyses.analysis_id"), index=True)
    context_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analysis_contexts.context_id"), index=True)
    citation_manifest_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_citation_manifests.manifest_id"), index=True)
    citation_manifest_hash: Mapped[str] = mapped_column(String(64))
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    required_source_count: Mapped[int] = mapped_column(Integer)
    ready_source_count: Mapped[int] = mapped_column(Integer)
    waived_source_count: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SinglePromptDiagnosisExecution(Base):
    __tablename__ = "single_prompt_diagnosis_executions"
    __table_args__ = (
        UniqueConstraint("analysis_id", "idempotency_key", name="uq_single_prompt_diagnosis_idempotency"),
        Index("ix_single_prompt_diagnosis_analysis", "analysis_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    diagnosis_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analyses.analysis_id"), index=True)
    context_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analysis_contexts.context_id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    raw_output_hash: Mapped[str] = mapped_column(String(64))
    brand_snapshot_json: Mapped[str] = mapped_column(Text)
    brand_snapshot_hash: Mapped[str] = mapped_column(String(64))
    truth_snapshot_json: Mapped[str] = mapped_column(Text)
    truth_set_hash: Mapped[str] = mapped_column(String(64))
    contract_config_json: Mapped[str] = mapped_column(Text)
    contract_config_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40), default="QUEUED", index=True)
    progress_json: Mapped[str] = mapped_column(Text, default="{}")
    blocker_code: Mapped[str] = mapped_column(String(80), default="")
    blocker_detail: Mapped[str] = mapped_column(Text, default="")
    active_attempt_token: Mapped[str] = mapped_column(String(64), default="")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    external_llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    llm_cache_hits: Mapped[int] = mapped_column(Integer, default=0)
    external_token_usage: Mapped[int] = mapped_column(Integer, default=0)
    active_result_version: Mapped[str] = mapped_column(String(96), default="", index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SinglePromptSourceSnapshot(Base):
    __tablename__ = "single_prompt_source_snapshots"
    __table_args__ = (
        UniqueConstraint("diagnosis_id", "source_key", name="uq_single_prompt_source_snapshot_key"),
        Index("ix_single_prompt_source_snapshot_diagnosis", "diagnosis_id", "fetch_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    snapshot_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    diagnosis_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_diagnosis_executions.diagnosis_id"), index=True)
    source_key: Mapped[str] = mapped_column(String(64))
    canonical_url: Mapped[str] = mapped_column(String(1200), default="")
    original_urls_json: Mapped[str] = mapped_column(Text, default="[]")
    reference_observations_json: Mapped[str] = mapped_column(Text, default="[]")
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    fetch_status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    failure_reason: Mapped[str] = mapped_column(Text, default="")
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    clean_text: Mapped[str] = mapped_column(Text, default="")
    passages_json: Mapped[str] = mapped_column(Text, default="[]")
    passages_hash: Mapped[str] = mapped_column(String(64), default="")
    parser_version: Mapped[str] = mapped_column(String(80), default="")
    fetch_source: Mapped[str] = mapped_column(String(40), default="EXTERNAL_FETCH")
    reused_from_snapshot_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SinglePromptDiagnosisResult(Base):
    __tablename__ = "single_prompt_diagnosis_results"
    __table_args__ = (
        UniqueConstraint("diagnosis_id", "version_number", name="uq_single_prompt_diagnosis_result_version"),
        Index("ix_single_prompt_diagnosis_result_diagnosis", "diagnosis_id", "version_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    result_version: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    diagnosis_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_diagnosis_executions.diagnosis_id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    parent_result_version: Mapped[Optional[str]] = mapped_column(String(96), nullable=True)
    output_json: Mapped[str] = mapped_column(Text)
    output_hash: Mapped[str] = mapped_column(String(64))
    reviewable_set_hash: Mapped[str] = mapped_column(String(64))
    limitations_json: Mapped[str] = mapped_column(Text, default="[]")
    stats_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SinglePromptDiagnosisReview(Base):
    __tablename__ = "single_prompt_diagnosis_reviews"
    __table_args__ = (
        UniqueConstraint("result_version", name="uq_single_prompt_diagnosis_review_result"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    review_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    diagnosis_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_diagnosis_executions.diagnosis_id"), index=True)
    result_version: Mapped[str] = mapped_column(ForeignKey("single_prompt_diagnosis_results.result_version"), index=True)
    result_hash: Mapped[str] = mapped_column(String(64))
    reviewable_set_hash: Mapped[str] = mapped_column(String(64))
    prior_review_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    decision: Mapped[str] = mapped_column(String(40), default="REVIEW_COMPLETED")
    decisions_json: Mapped[str] = mapped_column(Text, default="[]")
    reviewer: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SinglePromptCitationContributionExecution(Base):
    __tablename__ = "single_prompt_citation_contribution_executions"
    __table_args__ = (
        UniqueConstraint("analysis_id", "idempotency_key", name="uq_single_prompt_citation_contribution_idempotency"),
        Index("ix_single_prompt_citation_contribution_analysis", "analysis_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    contribution_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analyses.analysis_id"), index=True)
    context_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analysis_contexts.context_id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    selected_run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id"), index=True)
    input_snapshot_json: Mapped[str] = mapped_column(Text)
    input_snapshot_hash: Mapped[str] = mapped_column(String(64), index=True)
    plan_json: Mapped[str] = mapped_column(Text)
    plan_hash: Mapped[str] = mapped_column(String(64), index=True)
    contract_version: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(48), default="AWAITING_EXTERNAL_AUTHORIZATION", index=True)
    authorization_json: Mapped[str] = mapped_column(Text, default="{}")
    progress_json: Mapped[str] = mapped_column(Text, default="{}")
    blocker_code: Mapped[str] = mapped_column(String(80), default="")
    blocker_detail: Mapped[str] = mapped_column(Text, default="")
    active_attempt_token: Mapped[str] = mapped_column(String(64), default="")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    external_llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    llm_cache_hits: Mapped[int] = mapped_column(Integer, default=0)
    external_token_usage: Mapped[int] = mapped_column(Integer, default=0)
    active_result_version: Mapped[str] = mapped_column(String(96), default="", index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SinglePromptCitationContributionResult(Base):
    __tablename__ = "single_prompt_citation_contribution_results"
    __table_args__ = (
        UniqueConstraint("contribution_id", "version_number", name="uq_single_prompt_citation_contribution_result_version"),
        Index("ix_single_prompt_citation_contribution_result", "contribution_id", "version_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    result_version: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    contribution_id: Mapped[str] = mapped_column(
        ForeignKey("single_prompt_citation_contribution_executions.contribution_id"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    output_json: Mapped[str] = mapped_column(Text)
    output_hash: Mapped[str] = mapped_column(String(64))
    reviewable_set_hash: Mapped[str] = mapped_column(String(64))
    limitations_json: Mapped[str] = mapped_column(Text, default="[]")
    stats_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SinglePromptCitationContributionReview(Base):
    __tablename__ = "single_prompt_citation_contribution_reviews"
    __table_args__ = (
        UniqueConstraint("result_version", name="uq_single_prompt_citation_contribution_review_result"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    review_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    contribution_id: Mapped[str] = mapped_column(
        ForeignKey("single_prompt_citation_contribution_executions.contribution_id"), index=True
    )
    result_version: Mapped[str] = mapped_column(
        ForeignKey("single_prompt_citation_contribution_results.result_version"), index=True
    )
    result_hash: Mapped[str] = mapped_column(String(64))
    reviewable_set_hash: Mapped[str] = mapped_column(String(64))
    decisions_json: Mapped[str] = mapped_column(Text, default="[]")
    missed_bindings_json: Mapped[str] = mapped_column(Text, default="[]")
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    reviewer: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SinglePromptQualificationCriticExecution(Base):
    __tablename__ = "single_prompt_qualification_critic_executions"
    __table_args__ = (
        UniqueConstraint("analysis_id", "idempotency_key", name="uq_single_prompt_qualification_critic_idempotency"),
        Index("ix_single_prompt_qualification_critic_analysis", "analysis_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    critic_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analyses.analysis_id"), index=True)
    context_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analysis_contexts.context_id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    diagnosis_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_diagnosis_executions.diagnosis_id"), index=True)
    diagnosis_result_version: Mapped[str] = mapped_column(String(96), index=True)
    diagnosis_result_hash: Mapped[str] = mapped_column(String(64))
    baseline_projection_hash: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    input_snapshot_json: Mapped[str] = mapped_column(Text)
    input_snapshot_hash: Mapped[str] = mapped_column(String(64), index=True)
    plan_json: Mapped[str] = mapped_column(Text)
    plan_hash: Mapped[str] = mapped_column(String(64), index=True)
    contract_version: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(40))
    requested_model: Mapped[str] = mapped_column(String(160))
    authorization_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(48), default="QUEUED", index=True)
    progress_json: Mapped[str] = mapped_column(Text, default="{}")
    blocker_code: Mapped[str] = mapped_column(String(80), default="")
    blocker_detail: Mapped[str] = mapped_column(Text, default="")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    external_llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    llm_cache_hits: Mapped[int] = mapped_column(Integer, default=0)
    external_token_usage: Mapped[int] = mapped_column(Integer, default=0)
    active_result_version: Mapped[str] = mapped_column(String(96), default="", index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SinglePromptQualificationCriticResult(Base):
    __tablename__ = "single_prompt_qualification_critic_results"
    __table_args__ = (
        UniqueConstraint("critic_id", "version_number", name="uq_single_prompt_qualification_critic_result_version"),
        Index("ix_single_prompt_qualification_critic_result", "critic_id", "version_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    result_version: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    critic_id: Mapped[str] = mapped_column(
        ForeignKey("single_prompt_qualification_critic_executions.critic_id"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    output_json: Mapped[str] = mapped_column(Text)
    output_hash: Mapped[str] = mapped_column(String(64))
    stats_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SinglePromptQualificationCriticGoldReview(Base):
    __tablename__ = "single_prompt_qualification_critic_gold_reviews"
    __table_args__ = (
        UniqueConstraint(
            "phase_a_result_version",
            "reviewable_set_hash",
            "version_number",
            name="uq_single_prompt_critic_gold_review_version",
        ),
        Index("ix_single_prompt_critic_gold_analysis", "analysis_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    review_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analyses.analysis_id"), index=True)
    phase_a_critic_id: Mapped[str] = mapped_column(
        ForeignKey("single_prompt_qualification_critic_executions.critic_id"), index=True
    )
    phase_a_result_version: Mapped[str] = mapped_column(
        ForeignKey("single_prompt_qualification_critic_results.result_version"), index=True
    )
    phase_a_result_hash: Mapped[str] = mapped_column(String(64))
    supplemental_result_versions_json: Mapped[str] = mapped_column(Text, default="[]")
    reviewable_set_hash: Mapped[str] = mapped_column(String(64), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    parent_review_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    candidate_set_json: Mapped[str] = mapped_column(Text)
    decisions_json: Mapped[str] = mapped_column(Text)
    metrics_json: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SinglePromptStrategyExecution(Base):
    __tablename__ = "single_prompt_strategy_executions"
    __table_args__ = (
        UniqueConstraint("diagnosis_id", "idempotency_key", name="uq_single_prompt_strategy_idempotency"),
        Index("ix_single_prompt_strategy_diagnosis", "diagnosis_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    strategy_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analyses.analysis_id"), index=True)
    context_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analysis_contexts.context_id"), index=True)
    diagnosis_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_diagnosis_executions.diagnosis_id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    diagnosis_result_version: Mapped[str] = mapped_column(String(96), index=True)
    diagnosis_result_hash: Mapped[str] = mapped_column(String(64))
    diagnosis_review_id: Mapped[str] = mapped_column(String(80), index=True)
    review_snapshot_hash: Mapped[str] = mapped_column(String(64))
    input_authority_type: Mapped[str] = mapped_column(String(40), default="HUMAN_REVIEW", index=True)
    input_authority_id: Mapped[str] = mapped_column(String(120), default="")
    input_authority_hash: Mapped[str] = mapped_column(String(64), default="")
    validation_contract_version: Mapped[str] = mapped_column(String(120))
    input_snapshot_json: Mapped[str] = mapped_column(Text)
    input_snapshot_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40), default="READY_FOR_REVIEW", index=True)
    active_result_version: Mapped[str] = mapped_column(String(96), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SinglePromptStrategyResult(Base):
    __tablename__ = "single_prompt_strategy_results"
    __table_args__ = (
        UniqueConstraint("strategy_id", "version_number", name="uq_single_prompt_strategy_result_version"),
        Index("ix_single_prompt_strategy_result_strategy", "strategy_id", "version_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    result_version: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    strategy_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_strategy_executions.strategy_id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    parent_result_version: Mapped[Optional[str]] = mapped_column(String(96), nullable=True)
    output_json: Mapped[str] = mapped_column(Text)
    output_hash: Mapped[str] = mapped_column(String(64))
    reviewable_set_hash: Mapped[str] = mapped_column(String(64))
    limitations_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SinglePromptStrategyReview(Base):
    __tablename__ = "single_prompt_strategy_reviews"
    __table_args__ = (
        UniqueConstraint("result_version", name="uq_single_prompt_strategy_review_result"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    review_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    strategy_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_strategy_executions.strategy_id"), index=True)
    result_version: Mapped[str] = mapped_column(ForeignKey("single_prompt_strategy_results.result_version"), index=True)
    result_hash: Mapped[str] = mapped_column(String(64))
    reviewable_set_hash: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(40))
    reviewer: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SinglePromptExecutionProposal(Base):
    __tablename__ = "single_prompt_execution_proposals"
    __table_args__ = (
        UniqueConstraint("strategy_id", "idempotency_key", name="uq_single_prompt_execution_proposal_idempotency"),
        Index("ix_single_prompt_execution_proposal_strategy", "strategy_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    proposal_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    strategy_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_strategy_executions.strategy_id"), index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analyses.analysis_id"), index=True)
    context_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analysis_contexts.context_id"), index=True)
    diagnosis_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_diagnosis_executions.diagnosis_id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    direction_id: Mapped[str] = mapped_column(String(96), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    strategy_result_version: Mapped[str] = mapped_column(ForeignKey("single_prompt_strategy_results.result_version"), index=True)
    strategy_result_hash: Mapped[str] = mapped_column(String(64))
    strategy_review_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("single_prompt_strategy_reviews.review_id"), nullable=True, index=True
    )
    strategy_review_snapshot_hash: Mapped[str] = mapped_column(String(64), default="")
    input_authority_type: Mapped[str] = mapped_column(String(40), default="HUMAN_REVIEW", index=True)
    input_authority_id: Mapped[str] = mapped_column(String(120), default="")
    input_authority_hash: Mapped[str] = mapped_column(String(64), default="")
    validation_contract_version: Mapped[str] = mapped_column(String(120))
    input_snapshot_json: Mapped[str] = mapped_column(Text)
    input_snapshot_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40), default="NEEDS_HUMAN_SELECTION", index=True)
    active_result_version: Mapped[str] = mapped_column(String(96), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SinglePromptExecutionProposalResult(Base):
    __tablename__ = "single_prompt_execution_proposal_results"
    __table_args__ = (
        UniqueConstraint("proposal_id", "version_number", name="uq_single_prompt_execution_proposal_result_version"),
        Index("ix_single_prompt_execution_proposal_result", "proposal_id", "version_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    result_version: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_execution_proposals.proposal_id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    parent_result_version: Mapped[Optional[str]] = mapped_column(String(96), nullable=True)
    output_json: Mapped[str] = mapped_column(Text)
    output_hash: Mapped[str] = mapped_column(String(64))
    reviewable_set_hash: Mapped[str] = mapped_column(String(64))
    limitations_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SinglePromptExecutionConfirmation(Base):
    __tablename__ = "single_prompt_execution_confirmations"
    __table_args__ = (
        UniqueConstraint("proposal_id", "idempotency_key", name="uq_single_prompt_execution_confirmation_idempotency"),
        UniqueConstraint("result_version", name="uq_single_prompt_execution_confirmation_result"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    confirmation_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_execution_proposals.proposal_id"), index=True)
    result_version: Mapped[str] = mapped_column(ForeignKey("single_prompt_execution_proposal_results.result_version"), index=True)
    result_hash: Mapped[str] = mapped_column(String(64))
    reviewable_set_hash: Mapped[str] = mapped_column(String(64))
    input_snapshot_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    confirmation_snapshot_json: Mapped[str] = mapped_column(Text)
    confirmation_snapshot_hash: Mapped[str] = mapped_column(String(64))
    confirmer: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SinglePromptPublicationRecord(Base):
    __tablename__ = "single_prompt_publication_records"
    __table_args__ = (
        UniqueConstraint("confirmation_id", "idempotency_key", name="uq_single_prompt_publication_idempotency"),
        Index("ix_single_prompt_publication_confirmation", "confirmation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    publication_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    confirmation_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_execution_confirmations.confirmation_id"), index=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_execution_proposals.proposal_id"), index=True)
    prior_publication_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    publication_status: Mapped[str] = mapped_column(String(40), default="USER_REPORTED")
    conformance: Mapped[str] = mapped_column(String(40))
    report_json: Mapped[str] = mapped_column(Text)
    report_hash: Mapped[str] = mapped_column(String(64))
    conformance_json: Mapped[str] = mapped_column(Text)
    recorder: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SinglePromptRetestExecution(Base):
    __tablename__ = "single_prompt_retest_executions"
    __table_args__ = (
        UniqueConstraint("publication_id", "idempotency_key", name="uq_single_prompt_retest_idempotency"),
        Index("ix_single_prompt_retest_publication", "publication_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    retest_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    confirmation_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_execution_confirmations.confirmation_id"), index=True)
    publication_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_publication_records.publication_id"), index=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_execution_proposals.proposal_id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    baseline_analysis_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analyses.analysis_id"), index=True)
    baseline_context_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analysis_contexts.context_id"), index=True)
    retest_analysis_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_analyses.analysis_id"), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    confirmation_snapshot_hash: Mapped[str] = mapped_column(String(64))
    publication_report_hash: Mapped[str] = mapped_column(String(64))
    baseline_snapshot_json: Mapped[str] = mapped_column(Text)
    baseline_snapshot_hash: Mapped[str] = mapped_column(String(64))
    retest_plan_json: Mapped[str] = mapped_column(Text)
    retest_plan_hash: Mapped[str] = mapped_column(String(64))
    measurement_identity_json: Mapped[str] = mapped_column(Text)
    measurement_identity_hash: Mapped[str] = mapped_column(String(64))
    measurement_contract_json: Mapped[str] = mapped_column(Text)
    measurement_contract_hash: Mapped[str] = mapped_column(String(64))
    planned_conditions_json: Mapped[str] = mapped_column(Text)
    observed_conditions_json: Mapped[str] = mapped_column(Text, default="{}")
    unobservable_conditions_json: Mapped[str] = mapped_column(Text, default="[]")
    authorization_json: Mapped[str] = mapped_column(Text, default="{}")
    semantic_result_json: Mapped[str] = mapped_column(Text, default="{}")
    semantic_result_hash: Mapped[str] = mapped_column(String(64), default="")
    semantic_history_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(40), default="PLANNED", index=True)
    blocker_code: Mapped[str] = mapped_column(String(100), default="")
    blocker_detail: Mapped[str] = mapped_column(Text, default="")
    active_comparison_version: Mapped[str] = mapped_column(String(96), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SinglePromptSamplingSchedule(Base):
    __tablename__ = "single_prompt_sampling_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_id: Mapped[str] = mapped_column(String(80), unique=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    plan_json: Mapped[str] = mapped_column(Text)
    plan_hash: Mapped[str] = mapped_column(String(64))
    optimization_progress_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    timezone: Mapped[str] = mapped_column(String(80))
    local_time: Mapped[str] = mapped_column(String(5))
    next_due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(40), default="PAUSED")
    remaining_attempts: Mapped[int] = mapped_column(Integer)
    authorization_note: Mapped[str] = mapped_column(Text)
    last_analysis_id: Mapped[str] = mapped_column(String(80), default="")
    pause_reason: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SupplementalSourceAcquisition(Base):
    __tablename__ = "supplemental_source_acquisitions"
    __table_args__ = (UniqueConstraint("project_id", "idempotency_key", name="uq_supplemental_source_request"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    requested_url: Mapped[str] = mapped_column(String(1200))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_json: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40), default="QUEUED", index=True)
    snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    snapshot_hash: Mapped[str] = mapped_column(String(64), default="")
    failure_detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class BrandContextVersion(Base):
    __tablename__ = "brand_context_versions"
    __table_args__ = (UniqueConstraint("project_id", "version_number", name="uq_brand_context_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    context_version_id: Mapped[str] = mapped_column(String(80), unique=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text)
    source_reference: Mapped[str] = mapped_column(String(1000), default="")
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SinglePromptObservationComparison(Base):
    __tablename__ = "single_prompt_observation_comparisons"
    __table_args__ = (UniqueConstraint("project_id", "prompt_id", "input_hash", name="uq_observation_comparison_input"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_version: Mapped[str] = mapped_column(String(96), unique=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    input_snapshot_json: Mapped[str] = mapped_column(Text)
    output_json: Mapped[str] = mapped_column(Text)
    output_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SinglePromptComparisonResult(Base):
    __tablename__ = "single_prompt_comparison_results"
    __table_args__ = (
        UniqueConstraint("retest_id", "version_number", name="uq_single_prompt_comparison_version"),
        UniqueConstraint("retest_id", "input_hash", name="uq_single_prompt_comparison_input"),
        Index("ix_single_prompt_comparison_retest", "retest_id", "version_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    result_version: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    retest_id: Mapped[str] = mapped_column(ForeignKey("single_prompt_retest_executions.retest_id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    input_hash: Mapped[str] = mapped_column(String(64))
    baseline_context_id: Mapped[str] = mapped_column(String(80))
    retest_context_id: Mapped[str] = mapped_column(String(80))
    baseline_measurement_json: Mapped[str] = mapped_column(Text)
    retest_measurement_json: Mapped[str] = mapped_column(Text)
    comparison_json: Mapped[str] = mapped_column(Text)
    output_hash: Mapped[str] = mapped_column(String(64))
    limitations_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    sampling_mode: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
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
    canonical_url_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    canonicalization_version: Mapped[str] = mapped_column(String(40), default="")
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
    canonical_url_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    canonicalization_version: Mapped[str] = mapped_column(String(40), default="")
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


class RecommendationIntelligenceSnapshot(Base, TimestampMixin):
    __tablename__ = "recommendation_intelligence_snapshots"
    __table_args__ = (
        Index("ix_recommendation_snapshots_project_prompt_status", "project_id", "prompt_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id", ondelete="CASCADE"), index=True)
    source_run_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    recommendation_schema_version: Mapped[str] = mapped_column(String(60), default="recommendation_schema.v1")
    entity_resolver_version: Mapped[str] = mapped_column(String(60), default="entity_resolver.v1")
    recommendation_extractor_version: Mapped[str] = mapped_column(String(60), default="recommendation_extractor.v1")
    decision_mode: Mapped[str] = mapped_column(String(60), default="INFORMATIONAL", index=True)
    recommendation_expected: Mapped[bool] = mapped_column(Boolean, default=False)
    metric_eligibility_json: Mapped[str] = mapped_column(Text, default="{}")
    landscape_json: Mapped[str] = mapped_column(Text, default="[]")
    positioning_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_links_json: Mapped[str] = mapped_column(Text, default="[]")
    gap_diagnosis_json: Mapped[str] = mapped_column(Text, default="[]")
    intervention_candidates_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)


class RecommendationEntity(Base, TimestampMixin):
    __tablename__ = "recommendation_entities"
    __table_args__ = (
        UniqueConstraint("project_id", "entity_type", "normalized_key", name="uq_recommendation_entity_project_type_key"),
        Index("ix_recommendation_entities_project_type", "project_id", "entity_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    canonical_name: Mapped[str] = mapped_column(String(240), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), default="PRODUCT", index=True)
    entity_role: Mapped[str] = mapped_column(String(80), default="BRAND", index=True)
    is_choice_candidate: Mapped[bool] = mapped_column(Boolean, default=False)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    domain: Mapped[str] = mapped_column(String(255), default="")
    official_urls_json: Mapped[str] = mapped_column(Text, default="[]")
    normalized_key: Mapped[str] = mapped_column(String(240), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    source: Mapped[str] = mapped_column(String(80), default="RULE_DERIVED")


class RecommendationClaim(Base, TimestampMixin):
    __tablename__ = "recommendation_claims"
    __table_args__ = (
        Index("ix_recommendation_claims_project_prompt", "project_id", "prompt_id"),
        Index("ix_recommendation_claims_run_entity", "run_id", "entity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    snapshot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendation_intelligence_snapshots.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id", ondelete="CASCADE"), index=True)
    entity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendation_entities.id", ondelete="SET NULL"), nullable=True, index=True)
    entity_name: Mapped[str] = mapped_column(String(240), default="")
    recommendation_type: Mapped[str] = mapped_column(String(60), default="MENTION_ONLY", index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_conditional: Mapped[bool] = mapped_column(Boolean, default=False)
    condition_type: Mapped[str] = mapped_column(String(60), default="")
    condition_text: Mapped[str] = mapped_column(Text, default="")
    recommendation_text: Mapped[str] = mapped_column(Text, default="")
    recommendation_span: Mapped[str] = mapped_column(Text, default="")
    start_offset: Mapped[int] = mapped_column(Integer, default=-1)
    end_offset: Mapped[int] = mapped_column(Integer, default=-1)
    recommendation_strength: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    is_choice_candidate: Mapped[bool] = mapped_column(Boolean, default=False)
    answer_span: Mapped[str] = mapped_column(Text, default="")
    polarity: Mapped[str] = mapped_column(String(20), default="NEUTRAL")
    reason_texts_json: Mapped[str] = mapped_column(Text, default="[]")
    extraction_method: Mapped[str] = mapped_column(String(80), default="RULE_DERIVED")
    extraction_confidence: Mapped[float] = mapped_column(Float, default=0.5)
    model: Mapped[str] = mapped_column(String(120), default="")
    prompt_version: Mapped[str] = mapped_column(String(80), default="recommendation_extractor.v1")
    review_status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    human_payload_json: Mapped[str] = mapped_column(Text, default="{}")


class RecommendationReasonClaim(Base, TimestampMixin):
    __tablename__ = "recommendation_reason_claims"
    __table_args__ = (
        Index("ix_recommendation_reason_claims_rec_claim", "recommendation_claim_id"),
        Index("ix_recommendation_reason_claims_project_prompt", "project_id", "prompt_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    snapshot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendation_intelligence_snapshots.id", ondelete="SET NULL"), nullable=True, index=True)
    recommendation_claim_id: Mapped[int] = mapped_column(ForeignKey("recommendation_claims.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id", ondelete="CASCADE"), index=True)
    entity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendation_entities.id", ondelete="SET NULL"), nullable=True, index=True)
    entity_name: Mapped[str] = mapped_column(String(240), default="")
    reason_type: Mapped[str] = mapped_column(String(80), default="OTHER", index=True)
    reason_text: Mapped[str] = mapped_column(Text, default="")
    reason_span: Mapped[str] = mapped_column(Text, default="")
    start_offset: Mapped[int] = mapped_column(Integer, default=-1)
    end_offset: Mapped[int] = mapped_column(Integer, default=-1)
    claim_span: Mapped[str] = mapped_column(Text, default="")
    polarity: Mapped[str] = mapped_column(String(20), default="NEUTRAL")
    is_limitation: Mapped[bool] = mapped_column(Boolean, default=False)
    is_comparison: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    extractor: Mapped[str] = mapped_column(String(80), default="RULE_DERIVED")
    extractor_version: Mapped[str] = mapped_column(String(80), default="recommendation_reason.v1_rule_zh")
    review_status: Mapped[str] = mapped_column(String(40), default="UNREVIEWED", index=True)
    human_labels_json: Mapped[str] = mapped_column(Text, default="{}")


class AnswerSemanticFact(Base, TimestampMixin):
    __tablename__ = "answer_semantic_facts"
    __table_args__ = (
        Index("ix_answer_semantic_facts_snapshot", "snapshot_id"),
        Index("ix_answer_semantic_facts_project_prompt", "project_id", "prompt_id"),
        Index("ix_answer_semantic_facts_run_type", "run_id", "fact_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    snapshot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendation_intelligence_snapshots.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id", ondelete="CASCADE"), index=True)
    fact_type: Mapped[str] = mapped_column(String(80), index=True)
    fact_value: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_span: Mapped[str] = mapped_column(Text, default="")
    start_offset: Mapped[int] = mapped_column(Integer, default=-1)
    end_offset: Mapped[int] = mapped_column(Integer, default=-1)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    extractor: Mapped[str] = mapped_column(String(80), default="RULE_DERIVED")
    extractor_version: Mapped[str] = mapped_column(String(80), default="answer_semantic_fact.v1_rule_zh")
    review_status: Mapped[str] = mapped_column(String(40), default="UNREVIEWED", index=True)
    human_labels_json: Mapped[str] = mapped_column(Text, default="{}")


class RecommendationEvidenceLink(Base, TimestampMixin):
    __tablename__ = "recommendation_evidence_links"
    __table_args__ = (
        Index("ix_recommendation_evidence_links_rec_claim", "recommendation_claim_id"),
        Index("ix_recommendation_evidence_links_citation", "citation_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    snapshot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendation_intelligence_snapshots.id", ondelete="SET NULL"), nullable=True, index=True)
    recommendation_claim_id: Mapped[int] = mapped_column(ForeignKey("recommendation_claims.id", ondelete="CASCADE"), index=True)
    reason_claim_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendation_reason_claims.id", ondelete="SET NULL"), nullable=True, index=True)
    citation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reference_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    supported_entity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendation_entities.id", ondelete="SET NULL"), nullable=True, index=True)
    supported_entity_name: Mapped[str] = mapped_column(String(240), default="")
    evidence_roles_json: Mapped[str] = mapped_column(Text, default="[]")
    primary_evidence_role: Mapped[str] = mapped_column(String(80), default="", index=True)
    role_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    role_reason: Mapped[str] = mapped_column(Text, default="")
    attribution_method: Mapped[str] = mapped_column(String(80), default="RULE_DERIVED")
    attribution_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    answer_span: Mapped[str] = mapped_column(Text, default="")
    source_passage: Mapped[str] = mapped_column(Text, default="")
    match_method: Mapped[str] = mapped_column(String(80), default="")
    match_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class DecisionSelectionCriterion(Base, TimestampMixin):
    __tablename__ = "decision_selection_criteria"
    __table_args__ = (
        Index("ix_decision_selection_criteria_snapshot", "snapshot_id"),
        Index("ix_decision_selection_criteria_project_prompt", "project_id", "prompt_id"),
        Index("ix_decision_selection_criteria_run", "run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    snapshot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendation_intelligence_snapshots.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id", ondelete="CASCADE"), index=True)
    criterion_type: Mapped[str] = mapped_column(String(80), default="OTHER", index=True)
    criterion_label: Mapped[str] = mapped_column(String(160), default="")
    normalized_criterion: Mapped[str] = mapped_column(String(160), default="", index=True)
    answer_span: Mapped[str] = mapped_column(Text, default="")
    start_offset: Mapped[int] = mapped_column(Integer, default=-1)
    end_offset: Mapped[int] = mapped_column(Integer, default=-1)
    criterion_present: Mapped[bool] = mapped_column(Boolean, default=True)
    criterion_used_for_selection: Mapped[bool] = mapped_column(Boolean, default=False)
    related_brand_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendation_entities.id", ondelete="SET NULL"), nullable=True, index=True)
    related_brand_name: Mapped[str] = mapped_column(String(240), default="")
    related_solution_object: Mapped[str] = mapped_column(String(160), default="")
    polarity: Mapped[str] = mapped_column(String(20), default="NEUTRAL")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    extractor: Mapped[str] = mapped_column(String(80), default="RULE_DERIVED")
    extractor_version: Mapped[str] = mapped_column(String(80), default="selection_criterion.v1_rule_zh")
    review_status: Mapped[str] = mapped_column(String(40), default="UNREVIEWED", index=True)
    human_label_json: Mapped[str] = mapped_column(Text, default="{}")


class BrandCapabilityClaim(Base, TimestampMixin):
    __tablename__ = "brand_capability_claims"
    __table_args__ = (
        Index("ix_brand_capability_claims_snapshot", "snapshot_id"),
        Index("ix_brand_capability_claims_project_prompt", "project_id", "prompt_id"),
        Index("ix_brand_capability_claims_run_brand", "run_id", "brand_entity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    snapshot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendation_intelligence_snapshots.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id", ondelete="CASCADE"), index=True)
    brand_entity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendation_entities.id", ondelete="SET NULL"), nullable=True, index=True)
    brand_name: Mapped[str] = mapped_column(String(240), default="")
    need_label: Mapped[str] = mapped_column(String(160), default="")
    capability_label: Mapped[str] = mapped_column(String(160), default="")
    subject_text: Mapped[str] = mapped_column(String(240), default="")
    predicate: Mapped[str] = mapped_column(String(60), default="UNKNOWN", index=True)
    object_text: Mapped[str] = mapped_column(String(240), default="")
    claim_text: Mapped[str] = mapped_column(Text, default="")
    answer_span: Mapped[str] = mapped_column(Text, default="")
    start_offset: Mapped[int] = mapped_column(Integer, default=-1)
    end_offset: Mapped[int] = mapped_column(Integer, default=-1)
    polarity: Mapped[str] = mapped_column(String(20), default="NEUTRAL")
    negation: Mapped[bool] = mapped_column(Boolean, default=False)
    epistemic_status: Mapped[str] = mapped_column(String(40), default="OBSERVED")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    extractor_version: Mapped[str] = mapped_column(String(80), default="brand_capability.v1_rule_zh")
    review_status: Mapped[str] = mapped_column(String(40), default="UNREVIEWED", index=True)
    human_label_json: Mapped[str] = mapped_column(Text, default="{}")


class DecisionEvidenceAdoption(Base, TimestampMixin):
    __tablename__ = "decision_evidence_adoptions"
    __table_args__ = (
        Index("ix_decision_evidence_adoptions_snapshot", "snapshot_id"),
        Index("ix_decision_evidence_adoptions_project_prompt", "project_id", "prompt_id"),
        Index("ix_decision_evidence_adoptions_run", "run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    snapshot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendation_intelligence_snapshots.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[Optional[int]] = mapped_column(ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True, index=True)
    chunk_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    citation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reference_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    retrieval_candidate_id: Mapped[Optional[int]] = mapped_column(ForeignKey("retrieval_candidates.id", ondelete="SET NULL"), nullable=True, index=True)
    answer_claim_id: Mapped[Optional[int]] = mapped_column(ForeignKey("answer_claims.id", ondelete="SET NULL"), nullable=True, index=True)
    recommendation_claim_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendation_claims.id", ondelete="SET NULL"), nullable=True, index=True)
    selection_criterion_id: Mapped[Optional[int]] = mapped_column(ForeignKey("decision_selection_criteria.id", ondelete="SET NULL"), nullable=True, index=True)
    retrieval_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    retrieved: Mapped[bool] = mapped_column(Boolean, default=False)
    cited: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_claim: Mapped[bool] = mapped_column(Boolean, default=False)
    associated_with_selection_reason: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_status: Mapped[str] = mapped_column(String(40), default="UNCERTAIN", index=True)
    support_role: Mapped[str] = mapped_column(String(80), default="UNKNOWN", index=True)
    support_strength: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    attribution_method: Mapped[str] = mapped_column(String(80), default="RULE_DERIVED")
    attribution_version: Mapped[str] = mapped_column(String(80), default="evidence_adoption.v1")
    review_status: Mapped[str] = mapped_column(String(40), default="UNREVIEWED", index=True)
    human_label_json: Mapped[str] = mapped_column(Text, default="{}")
    answer_span: Mapped[str] = mapped_column(Text, default="")
    evidence_span: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(String(1200), default="")
    source_domain: Mapped[str] = mapped_column(String(255), default="")
    source_title: Mapped[str] = mapped_column(String(500), default="")


class TargetBrandCapabilityTruth(Base, TimestampMixin):
    __tablename__ = "target_brand_capability_truths"
    __table_args__ = (
        UniqueConstraint("project_id", "brand_id", "capability_key", name="uq_target_brand_capability_truth"),
        Index("ix_target_brand_capability_truths_project_status", "project_id", "product_truth_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    brand_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendation_entities.id", ondelete="SET NULL"), nullable=True, index=True)
    capability_key: Mapped[str] = mapped_column(String(160), index=True)
    capability_label: Mapped[str] = mapped_column(String(160), default="")
    product_truth_status: Mapped[str] = mapped_column(String(40), default="UNKNOWN", index=True)
    truth_source: Mapped[str] = mapped_column(String(80), default="MANUAL_CONFIRMED")
    source_reference: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str] = mapped_column(String(120), default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


class SinglePromptTruthCorrection(Base):
    __tablename__ = "single_prompt_truth_corrections"
    __table_args__ = (
        UniqueConstraint("truth_id", "version_number", name="uq_truth_correction_version"),
        UniqueConstraint("truth_id", "base_hash", name="uq_truth_correction_parent"),
        UniqueConstraint("project_id", "idempotency_key", name="uq_truth_correction_request"),
    )
    correction_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    truth_id: Mapped[int] = mapped_column(ForeignKey("target_brand_capability_truths.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_hash: Mapped[str] = mapped_column(String(64))
    request_json: Mapped[str] = mapped_column(Text)
    base_hash: Mapped[str] = mapped_column(String(64))
    base_json: Mapped[str] = mapped_column(Text)
    output_hash: Mapped[str] = mapped_column(String(64))
    output_json: Mapped[str] = mapped_column(Text)
    impact_json: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DecisionGapDiagnosis(Base, TimestampMixin):
    __tablename__ = "decision_gap_diagnoses"
    __table_args__ = (
        Index("ix_decision_gap_diagnoses_snapshot", "snapshot_id"),
        Index("ix_decision_gap_diagnoses_project_prompt", "project_id", "prompt_id"),
        Index("ix_decision_gap_diagnoses_type", "gap_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    snapshot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendation_intelligence_snapshots.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id", ondelete="CASCADE"), index=True)
    gap_type: Mapped[str] = mapped_column(String(80), default="UNKNOWN", index=True)
    severity: Mapped[str] = mapped_column(String(40), default="UNKNOWN", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    numerator: Mapped[int] = mapped_column(Integer, default=0)
    denominator: Mapped[int] = mapped_column(Integer, default=0)
    eligible_denominator: Mapped[int] = mapped_column(Integer, default=0)
    metric_name: Mapped[str] = mapped_column(String(120), default="")
    metric_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    supporting_run_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    counterexample_run_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    supporting_claim_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    supporting_evidence_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    diagnosis_basis_json: Mapped[str] = mapped_column(Text, default="{}")
    rule_version: Mapped[str] = mapped_column(String(80), default="gap_diagnosis.v1")
    llm_version: Mapped[str] = mapped_column(String(120), default="")
    review_status: Mapped[str] = mapped_column(String(40), default="UNREVIEWED", index=True)
    human_label_json: Mapped[str] = mapped_column(Text, default="{}")
    diagnosis_text: Mapped[str] = mapped_column(Text, default="")
    action_hint: Mapped[str] = mapped_column(Text, default="")


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
    hypothesis_type: Mapped[str] = mapped_column(String(80), default="", index=True)
    mechanism: Mapped[str] = mapped_column(Text, default="")
    intervention_family: Mapped[str] = mapped_column(String(80), default="", index=True)
    intervention_variables_json: Mapped[str] = mapped_column(Text, default="{}")
    allowed_changes_json: Mapped[str] = mapped_column(Text, default="[]")
    forbidden_changes_json: Mapped[str] = mapped_column(Text, default="[]")
    target_prompt_scope_json: Mapped[str] = mapped_column(Text, default="[]")
    control_prompt_scope_json: Mapped[str] = mapped_column(Text, default="[]")
    sentinel_prompt_scope_json: Mapped[str] = mapped_column(Text, default="[]")
    environment_scope_json: Mapped[str] = mapped_column(Text, default="{}")
    sample_plan_json: Mapped[str] = mapped_column(Text, default="{}")
    primary_metric: Mapped[str] = mapped_column(String(120), default="brand_recommendation_rate")
    secondary_metrics_json: Mapped[str] = mapped_column(Text, default="[]")
    baseline_numerator: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    baseline_denominator: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    baseline_metric_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    success_threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sample_size_target: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_prompt_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    target_brand_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendation_entities.id", ondelete="SET NULL"), nullable=True, index=True)
    target_asset_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    recollection_strategy_json: Mapped[str] = mapped_column(Text, default="{}")
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
    known_environment_audit_json: Mapped[str] = mapped_column(Text, default="{}")
    comparability_status: Mapped[str] = mapped_column(String(40), default="INSUFFICIENT_CONTEXT", index=True)
    comparability_note: Mapped[str] = mapped_column(Text, default="")
    controlled_intervention_json: Mapped[str] = mapped_column(Text, default="{}")
    conclusion: Mapped[str] = mapped_column(Text, default="")
    conclusion_reason: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Intervention Plan V2 扩展字段（per-channel experiment）
    intervention_plan_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(80), default="")
    experiment_mode: Mapped[str] = mapped_column(String(40), default="PER_CHANNEL")
    primary_benchmark_source_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    benchmark_source_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    target_reason_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    target_gap_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    hypothesis_text: Mapped[str] = mapped_column(Text, default="")
    brief_json: Mapped[str] = mapped_column(Text, default="{}")
    target_asset_type: Mapped[str] = mapped_column(String(80), default="TBD")
    target_asset_url: Mapped[str] = mapped_column(String(1200), default="")
    release_url: Mapped[str] = mapped_column(String(1200), default="")
    release_notes: Mapped[str] = mapped_column(Text, default="")
    post_run_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    outcome_summary_json: Mapped[str] = mapped_column(Text, default="{}")


# ---------------------------------------------------------------------------
# Citation Passage Intelligence — Golden Case models
# ---------------------------------------------------------------------------

class SourceDocument(Base, TimestampMixin):
    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    url: Mapped[str] = mapped_column(String(1200), index=True)
    original_url: Mapped[str] = mapped_column(String(1200), default="")
    canonical_url: Mapped[str] = mapped_column(String(1200), default="")
    canonical_url_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    canonicalization_version: Mapped[str] = mapped_column(String(40), default="")
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
    review_status: Mapped[str] = mapped_column(String(40), default="PENDING")
    human_labels_json: Mapped[str] = mapped_column(Text, default="[]")
    reviewer: Mapped[str] = mapped_column(String(120), default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    answer_position: Mapped[int] = mapped_column(Integer, default=0)


class AnswerUnit(Base, TimestampMixin):
    """V1.1 Shadow: grounded atomic answer unit derived from AnswerClaim."""

    __tablename__ = "answer_units"
    __table_args__ = (
        Index("ix_answer_units_shadow_run", "shadow_run_id"),
        Index("ix_answer_units_project_prompt", "project_id", "prompt_id"),
        Index("ix_answer_units_claim", "answer_claim_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shadow_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("answer_evidence_shadow_runs.id"), nullable=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id"), index=True)
    answer_claim_id: Mapped[int] = mapped_column(ForeignKey("answer_claims.id"), index=True)
    unit_index: Mapped[int] = mapped_column(Integer, default=0)
    unit_text_original: Mapped[str] = mapped_column(Text, default="")
    unit_text_normalized: Mapped[str] = mapped_column(Text, default="")
    source_span: Mapped[str] = mapped_column(Text, default="")
    raw_start: Mapped[int] = mapped_column(Integer, default=-1)
    raw_end: Mapped[int] = mapped_column(Integer, default=-1)
    semantic_type: Mapped[str] = mapped_column(String(40), default="GENERAL_FACT", index=True)
    entity_hint: Mapped[str] = mapped_column(String(240), default="")
    extraction_method: Mapped[str] = mapped_column(String(80), default="RULE_ATOMICIZE")
    extraction_version: Mapped[str] = mapped_column(String(80), default="answer_unit.v1_1_shadow")
    machine_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    human_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    review_status: Mapped[str] = mapped_column(String(40), default="MACHINE_GROUNDED", index=True)
    reviewer: Mapped[str] = mapped_column(String(120), default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AnswerDecisionBinding(Base, TimestampMixin):
    """V1.1 Shadow: binds an AnswerUnit to a RecommendationEvent decision role."""

    __tablename__ = "answer_decision_bindings"
    __table_args__ = (
        Index("ix_answer_decision_bindings_shadow_run", "shadow_run_id"),
        Index("ix_answer_decision_bindings_event", "recommendation_event_id"),
        Index("ix_answer_decision_bindings_unit", "answer_unit_id"),
        Index("ix_answer_decision_bindings_project_prompt", "project_id", "prompt_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shadow_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("answer_evidence_shadow_runs.id"), nullable=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id"), index=True)
    recommendation_event_id: Mapped[int] = mapped_column(ForeignKey("recommendation_events.id"), index=True)
    answer_unit_id: Mapped[int] = mapped_column(ForeignKey("answer_units.id"), index=True)
    decision_role: Mapped[str] = mapped_column(String(40), default="SUPPORTING_REASON", index=True)
    binding_strength: Mapped[str] = mapped_column(String(40), default="MEDIUM")
    scope_type: Mapped[str] = mapped_column(String(40), default="SAME_PARAGRAPH", index=True)
    scope_reason: Mapped[str] = mapped_column(Text, default="")
    binding_method: Mapped[str] = mapped_column(String(80), default="RULE_SHADOW_CANDIDATE")
    pipeline_version: Mapped[str] = mapped_column(String(80), default="citation_decision_v1_1_shadow", index=True)
    judge_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    review_status: Mapped[str] = mapped_column(String(40), default="MACHINE_GROUNDED", index=True)
    reviewer: Mapped[str] = mapped_column(String(120), default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AnswerEvidenceShadowRun(Base, TimestampMixin):
    """V1.1 Phase 0 audit run. It must not affect formal Citation Decision V1."""

    __tablename__ = "answer_evidence_shadow_runs"
    __table_args__ = (
        Index("ix_answer_evidence_shadow_runs_project_prompt", "project_id", "prompt_id"),
        Index("ix_answer_evidence_shadow_runs_package", "evidence_package_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    evidence_package_id: Mapped[Optional[int]] = mapped_column(ForeignKey("optimization_evidence_packages.id"), nullable=True, index=True)
    source_run_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    pipeline_version: Mapped[str] = mapped_column(String(80), default="citation_decision_v1_1_shadow", index=True)
    status: Mapped[str] = mapped_column(String(40), default="running", index=True)
    formal_output_impact: Mapped[str] = mapped_column(String(40), default="NONE")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")


class AnswerEvidenceShadowResult(Base, TimestampMixin):
    """V1.1 Phase 0 source/alignment result stored as audit-only JSON."""

    __tablename__ = "answer_evidence_shadow_results"
    __table_args__ = (
        Index("ix_answer_evidence_shadow_results_run", "shadow_run_id"),
        Index("ix_answer_evidence_shadow_results_event", "recommendation_event_id"),
        Index("ix_answer_evidence_shadow_results_document", "source_document_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shadow_run_id: Mapped[int] = mapped_column(ForeignKey("answer_evidence_shadow_runs.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id"), index=True)
    evidence_package_id: Mapped[Optional[int]] = mapped_column(ForeignKey("optimization_evidence_packages.id"), nullable=True, index=True)
    recommendation_event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendation_events.id"), nullable=True, index=True)
    answer_unit_id: Mapped[int] = mapped_column(ForeignKey("answer_units.id"), index=True)
    decision_binding_id: Mapped[Optional[int]] = mapped_column(ForeignKey("answer_decision_bindings.id"), nullable=True, index=True)
    reference_source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reference_sources.id"), nullable=True, index=True)
    source_document_id: Mapped[Optional[int]] = mapped_column(ForeignKey("source_documents.id"), nullable=True, index=True)
    passage_id: Mapped[str] = mapped_column(String(120), default="")
    passage_text: Mapped[str] = mapped_column(Text, default="")
    retrieval_score: Mapped[float] = mapped_column(Float, default=0)
    source_claim_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    source_claim_text: Mapped[str] = mapped_column(Text, default="")
    source_claim_subject: Mapped[str] = mapped_column(String(240), default="UNKNOWN")
    source_claim_review_status: Mapped[str] = mapped_column(String(40), default="MACHINE_CANDIDATE")
    alignment_relation: Mapped[str] = mapped_column(String(40), default="NO_SUPPORT", index=True)
    alignment_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    evidence_classification: Mapped[str] = mapped_column(String(60), default="NO_RECOMMENDATION_EVIDENCE", index=True)
    pipeline_version: Mapped[str] = mapped_column(String(80), default="citation_decision_v1_1_shadow", index=True)
    formal_output_impact: Mapped[str] = mapped_column(String(40), default="NONE")
    review_status: Mapped[str] = mapped_column(String(40), default="MACHINE_GROUNDED", index=True)


# ---------------------------------------------------------------------------
# Answer Intelligence — Claim Extraction + Atomic Claim
# ---------------------------------------------------------------------------

class LLMCallCache(Base):
    """语义模型调用缓存 — 相同输入不重复调用 API。"""

    __tablename__ = "llm_call_cache"
    __table_args__ = (
        Index("ix_llm_call_cache_lookup", "provider", "model", "prompt_version", "schema_version", "input_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    model: Mapped[str] = mapped_column(String(120), default="")
    prompt_version: Mapped[str] = mapped_column(String(80), default="")
    schema_version: Mapped[str] = mapped_column(String(40), default="v1")
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    raw_response_hash: Mapped[str] = mapped_column(String(64), default="")
    parsed_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    token_usage: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ClaimExtractionRun(Base, TimestampMixin):
    __tablename__ = "claim_extraction_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    extractor_type: Mapped[str] = mapped_column(String(40), default="rule")
    model_provider: Mapped[str] = mapped_column(String(80), default="")
    model_name: Mapped[str] = mapped_column(String(120), default="")
    prompt_version: Mapped[str] = mapped_column(String(80), default="")
    extraction_version: Mapped[str] = mapped_column(String(40), default="v1")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    error_message: Mapped[str] = mapped_column(Text, default="")


class AtomicClaim(Base, TimestampMixin):
    __tablename__ = "atomic_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_segment_id: Mapped[int] = mapped_column(ForeignKey("answer_claims.id"), index=True)
    claim_extraction_run_id: Mapped[int] = mapped_column(ForeignKey("claim_extraction_runs.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id"), index=True)

    claim_text: Mapped[str] = mapped_column(Text, default="")
    claim_types_json: Mapped[str] = mapped_column(Text, default="[]")
    speech_act: Mapped[str] = mapped_column(String(40), default="ASSERTION")
    epistemic_status: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    polarity: Mapped[str] = mapped_column(String(20), default="NEUTRAL")
    is_negated: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_priority: Mapped[str] = mapped_column(String(20), default="LOW")
    geo_importance: Mapped[str] = mapped_column(String(20), default="LOW")
    entities_json: Mapped[str] = mapped_column(Text, default="[]")
    extraction_confidence: Mapped[float] = mapped_column(Float, default=0)

    # Human review
    review_status: Mapped[str] = mapped_column(String(40), default="PENDING")
    machine_claim_text: Mapped[str] = mapped_column(Text, default="")
    human_claim_text: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str] = mapped_column(String(120), default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")


class RecommendationEvent(Base, TimestampMixin):
    """答案语义事件（LLM 提取，machine/human 分离，不覆盖旧 RecommendationClaim）。"""

    __tablename__ = "recommendation_events"
    __table_args__ = (
        Index("ix_recommendation_events_run", "run_id"),
        Index("ix_recommendation_events_answer_hash", "answer_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id"), index=True)
    answer_hash: Mapped[str] = mapped_column(String(64), default="")
    entity_text: Mapped[str] = mapped_column(String(240), default="")
    entity_type: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    speech_act: Mapped[str] = mapped_column(String(40), default="UNRESOLVED")
    recommendation_strength: Mapped[str] = mapped_column(String(20), default="NONE")
    polarity: Mapped[str] = mapped_column(String(20), default="NEUTRAL")
    answer_span: Mapped[str] = mapped_column(Text, default="")
    raw_start: Mapped[int] = mapped_column(Integer, default=-1)
    raw_end: Mapped[int] = mapped_column(Integer, default=-1)
    reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    selection_criteria_json: Mapped[str] = mapped_column(Text, default="[]")
    provider: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    prompt_version: Mapped[str] = mapped_column(String(80), default="")
    schema_version: Mapped[str] = mapped_column(String(40), default="v1")
    machine_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    human_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    review_status: Mapped[str] = mapped_column(String(40), default="MACHINE_CANDIDATE", index=True)
    reviewer: Mapped[str] = mapped_column(String(120), default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class SourceClaim(Base, TimestampMixin):
    """盲评 Source Claim（subject_entity 为语义主体，owner_entity 仅 provenance）。"""

    __tablename__ = "source_claims"
    __table_args__ = (
        Index("ix_source_claims_document", "source_document_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"), index=True)
    passage_id: Mapped[str] = mapped_column(String(120), default="")
    source_owner_entity: Mapped[str] = mapped_column(String(240), default="UNKNOWN")
    source_role: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    subject_entity: Mapped[str] = mapped_column(String(240), default="UNKNOWN")
    normalized_claim: Mapped[str] = mapped_column(Text, default="")
    subject_text: Mapped[str] = mapped_column(String(240), default="")
    predicate: Mapped[str] = mapped_column(String(240), default="")
    object_text: Mapped[str] = mapped_column(String(500), default="")
    claim_type: Mapped[str] = mapped_column(String(40), default="OTHER")
    polarity: Mapped[str] = mapped_column(String(20), default="NEUTRAL")
    source_span: Mapped[str] = mapped_column(Text, default="")
    raw_start: Mapped[int] = mapped_column(Integer, default=-1)
    raw_end: Mapped[int] = mapped_column(Integer, default=-1)
    provider: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    prompt_version: Mapped[str] = mapped_column(String(80), default="")
    schema_version: Mapped[str] = mapped_column(String(40), default="v1")
    machine_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    human_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    review_status: Mapped[str] = mapped_column(String(40), default="MACHINE_CANDIDATE", index=True)
    reviewer: Mapped[str] = mapped_column(String(120), default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class SourceClaimMaterialization(Base, TimestampMixin):
    """SourceClaim extraction ledger keyed by semantic passage input."""

    __tablename__ = "source_claim_materializations"
    __table_args__ = (
        UniqueConstraint("materialization_key", name="uq_source_claim_materializations_key"),
        Index("ix_source_claim_materializations_status", "status"),
        Index("ix_source_claim_materializations_contract", "contract_version"),
        Index("ix_source_claim_materializations_input", "passage_content_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    materialization_key: Mapped[str] = mapped_column(String(64))
    passage_id: Mapped[str] = mapped_column(String(120), default="")
    passage_content_hash: Mapped[str] = mapped_column(String(64), default="")
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"), index=True)
    source_document_content_hash: Mapped[str] = mapped_column(String(64), default="")
    observed_source_document_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    observed_passage_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    contract_version: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(40), default="MISSING")
    compatibility_status: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    claim_count: Mapped[int] = mapped_column(Integer, default=0)
    source_claim_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    output_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    output_hash: Mapped[str] = mapped_column(String(64), default="")
    extractor_impl_version: Mapped[str] = mapped_column(String(80), default="")
    prompt_version: Mapped[str] = mapped_column(String(80), default="")
    schema_version: Mapped[str] = mapped_column(String(40), default="v1")
    provider: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[str] = mapped_column(String(120), default="")
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class EvidenceAlignmentMaterialization(Base, TimestampMixin):
    """EvidenceAlignment verdict ledger keyed by semantic reason/claim input."""

    __tablename__ = "evidence_alignment_materializations"
    __table_args__ = (
        UniqueConstraint("materialization_key", name="uq_evidence_alignment_materializations_key"),
        Index("ix_evidence_alignment_materializations_status", "status"),
        Index("ix_evidence_alignment_materializations_contract", "contract_version"),
        Index("ix_evidence_alignment_materializations_answer", "answer_unit_semantic_hash"),
        Index("ix_evidence_alignment_materializations_claim", "source_claim_semantic_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    materialization_key: Mapped[str] = mapped_column(String(64))
    answer_unit_semantic_hash: Mapped[str] = mapped_column(String(64), default="")
    source_claim_semantic_hash: Mapped[str] = mapped_column(String(64), default="")
    contract_version: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(40), default="MISSING")
    compatibility_status: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    verdict: Mapped[str] = mapped_column(String(40), default="NONE")
    rationale: Mapped[str] = mapped_column(Text, default="")
    confidence_raw: Mapped[float] = mapped_column(Float, default=0.0)
    output_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    output_hash: Mapped[str] = mapped_column(String(64), default="")
    source_alignment_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    observed_prompt_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    observed_run_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    judge_impl_version: Mapped[str] = mapped_column(String(80), default="")
    prompt_version: Mapped[str] = mapped_column(String(80), default="")
    schema_version: Mapped[str] = mapped_column(String(40), default="v1")
    provider: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[str] = mapped_column(String(120), default="")
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class EvidenceAlignment(Base, TimestampMixin):
    """语义证据对齐（与旧 decision_evidence_adoptions 并存，不覆盖）。"""

    __tablename__ = "evidence_alignments"
    __table_args__ = (
        Index("ix_evidence_alignments_event", "recommendation_event_id"),
        Index("ix_evidence_alignments_claim", "source_claim_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("browser_monitor_runs.id"), index=True)
    recommendation_event_id: Mapped[int] = mapped_column(ForeignKey("recommendation_events.id"), index=True)
    recommendation_reason_id: Mapped[str] = mapped_column(String(120), default="")
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"), index=True)
    source_claim_id: Mapped[int] = mapped_column(ForeignKey("source_claims.id"), index=True)
    relation: Mapped[str] = mapped_column(String(40), default="NONE")
    scope_relation: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    provider: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    prompt_version: Mapped[str] = mapped_column(String(80), default="")
    schema_version: Mapped[str] = mapped_column(String(40), default="v1")
    machine_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    human_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    review_status: Mapped[str] = mapped_column(String(40), default="MACHINE_CANDIDATE", index=True)
    reviewer: Mapped[str] = mapped_column(String(120), default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class SourceQuality(Base):
    """SourceDocument 内容质量分层（绑定 hash/extractor，不改写 fetch_status）。"""

    __tablename__ = "source_quality"
    __table_args__ = (
        Index("ix_source_quality_document", "source_document_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"), index=True)
    content_quality_status: Mapped[str] = mapped_column(String(40), default="UNREVIEWED", index=True)
    quality_source: Mapped[str] = mapped_column(String(80), default="RULE")
    quality_reason: Mapped[str] = mapped_column(Text, default="")
    clean_text_hash: Mapped[str] = mapped_column(String(64), default="")
    extractor_version: Mapped[str] = mapped_column(String(80), default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
