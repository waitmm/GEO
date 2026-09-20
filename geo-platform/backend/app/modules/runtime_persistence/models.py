from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class RuntimeBase(DeclarativeBase):
    pass


class RuntimeManifest(RuntimeBase):
    __tablename__ = "runtime_manifests"
    __table_args__ = (
        CheckConstraint("member_count >= 0", name="ck_runtime_manifest_member_count"),
        Index("ix_runtime_manifest_hash", "canonical_hash"),
    )

    manifest_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    manifest_type: Mapped[str] = mapped_column(String(180))
    manifest_contract_version: Mapped[str] = mapped_column(String(180))
    canonicalization_version: Mapped[str] = mapped_column(String(100))
    member_count: Mapped[int] = mapped_column(Integer)
    member_refs_json: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text)
    canonical_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    canonical_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class RuntimeAnalysisContext(RuntimeBase):
    __tablename__ = "runtime_analysis_contexts"
    __table_args__ = (
        CheckConstraint(
            "workflow_track IN ('PRODUCTION','SHADOW','GOLDEN_REPLAY','LEGACY')",
            name="ck_runtime_context_track",
        ),
        Index("ix_runtime_context_scope", "project_id", "prompt_id", "workflow_track"),
        Index("ix_runtime_context_fingerprint", "context_fingerprint"),
    )

    context_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer)
    prompt_id: Mapped[int] = mapped_column(Integer)
    workflow_track: Mapped[str] = mapped_column(String(32))
    context_fingerprint: Mapped[str] = mapped_column(String(64))
    fingerprint_contract_version: Mapped[str] = mapped_column(String(120))
    root_manifest_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_manifests.manifest_id", ondelete="RESTRICT"),
    )
    root_manifest_hash: Mapped[str] = mapped_column(String(64))
    root_runtime_contract_profile_version: Mapped[str] = mapped_column(String(160))
    context_manifest_hash: Mapped[str] = mapped_column(String(64))
    evidence_package_ref: Mapped[str] = mapped_column(String(240))
    creation_actor: Mapped[str] = mapped_column(String(160))
    creation_reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class RuntimeStageExecution(RuntimeBase):
    __tablename__ = "runtime_stage_executions"
    __table_args__ = (
        CheckConstraint(
            "compute_outcome IN ('NOT_STARTED','ACTIVE','SUCCEEDED','TERMINAL_FAILED','SKIPPED')",
            name="ck_runtime_stage_compute_outcome",
        ),
        CheckConstraint("current_active_authority_generation >= 0", name="ck_runtime_stage_generation"),
        CheckConstraint(
            "(compute_outcome = 'SUCCEEDED' AND output_manifest_id IS NOT NULL "
            "AND output_set_hash IS NOT NULL AND output_count IS NOT NULL "
            "AND output_count >= 0 AND completion_attempt_id IS NOT NULL) OR "
            "(compute_outcome != 'SUCCEEDED' AND output_manifest_id IS NULL "
            "AND output_set_hash IS NULL AND output_count IS NULL "
            "AND completion_attempt_id IS NULL)",
            name="ck_runtime_stage_output_publication",
        ),
        Index("ix_runtime_stage_context_type", "context_id", "stage_type"),
        Index("ix_runtime_stage_semantic_fingerprint", "semantic_execution_fingerprint"),
    )

    stage_execution_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    context_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_analysis_contexts.context_id", ondelete="RESTRICT"),
    )
    runtime_stage_profile_version: Mapped[str] = mapped_column(String(180))
    stage_type: Mapped[str] = mapped_column(String(80))
    stage_scope_key: Mapped[str] = mapped_column(String(80))
    stage_contract_version: Mapped[str] = mapped_column(String(180))
    input_manifest_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_manifests.manifest_id", ondelete="RESTRICT"),
    )
    input_set_hash: Mapped[str] = mapped_column(String(64))
    configuration_manifest_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_manifests.manifest_id", ondelete="RESTRICT"),
    )
    semantic_config_signature: Mapped[str] = mapped_column(String(64))
    semantic_execution_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    supersedes_stage_execution_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("runtime_stage_executions.stage_execution_id", ondelete="RESTRICT"),
        nullable=True,
    )
    compute_outcome: Mapped[str] = mapped_column(String(32))
    current_active_authority_generation: Mapped[int] = mapped_column(Integer)
    output_manifest_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("runtime_manifests.manifest_id", ondelete="RESTRICT"),
        nullable=True,
    )
    output_set_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    output_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_attempt_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    created_by: Mapped[str] = mapped_column(String(160))
    creation_reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class RuntimeStageInputEdge(RuntimeBase):
    __tablename__ = "runtime_stage_input_edges"
    __table_args__ = (
        CheckConstraint(
            "input_role IN ('ROOT_MANIFEST','UPSTREAM_STAGE_OUTPUT','REUSABLE_INPUT',"
            "'AUTHORITATIVE_REVIEW','CONFIGURATION')",
            name="ck_runtime_stage_input_role",
        ),
        UniqueConstraint(
            "stage_execution_id",
            "input_role",
            "source_identity_ref",
            "source_contract_version",
            "consumed_semantic_hash",
            name="uq_runtime_stage_input_edge_identity",
        ),
        Index("ix_runtime_stage_input_upstream", "upstream_stage_execution_id"),
    )

    edge_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    stage_execution_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_stage_executions.stage_execution_id", ondelete="RESTRICT"),
    )
    input_role: Mapped[str] = mapped_column(String(40))
    source_manifest_type: Mapped[str] = mapped_column(String(180))
    source_identity_ref: Mapped[str] = mapped_column(String(240))
    source_contract_version: Mapped[str] = mapped_column(String(180))
    consumed_semantic_hash: Mapped[str] = mapped_column(String(64))
    source_partition_ref: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    upstream_stage_execution_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("runtime_stage_executions.stage_execution_id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime)


class RuntimeStageAttempt(RuntimeBase):
    __tablename__ = "runtime_stage_attempts"
    __table_args__ = (
        UniqueConstraint("stage_execution_id", "attempt_no", name="uq_runtime_attempt_no"),
        UniqueConstraint(
            "stage_execution_id",
            "authority_generation",
            name="uq_runtime_attempt_generation",
        ),
        CheckConstraint("attempt_no > 0", name="ck_runtime_attempt_no"),
        CheckConstraint("authority_generation > 0", name="ck_runtime_attempt_generation"),
    )

    attempt_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    stage_execution_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_stage_executions.stage_execution_id", ondelete="RESTRICT"),
    )
    attempt_no: Mapped[int] = mapped_column(Integer)
    authority_generation: Mapped[int] = mapped_column(Integer)
    trigger_actor: Mapped[str] = mapped_column(String(160))
    trigger_reason: Mapped[str] = mapped_column(Text)
    executor_identity: Mapped[str] = mapped_column(String(180))
    owner_id: Mapped[str] = mapped_column(String(180))
    lease_acquired_at: Mapped[datetime] = mapped_column(DateTime)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime)
    started_at: Mapped[datetime] = mapped_column(DateTime)


class RuntimeStageAttemptResult(RuntimeBase):
    __tablename__ = "runtime_stage_attempt_results"
    __table_args__ = (
        CheckConstraint(
            "attempt_outcome IN ('SUCCEEDED','FAILED_RETRYABLE','FAILED_FINAL',"
            "'LATE_OR_SUPERSEDED_ATTEMPT')",
            name="ck_runtime_attempt_outcome",
        ),
    )

    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_stage_attempts.attempt_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    attempt_outcome: Mapped[str] = mapped_column(String(48))
    finished_at: Mapped[datetime] = mapped_column(DateTime)
    error_code: Mapped[str] = mapped_column(String(120))
    error_detail: Mapped[str] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean)
    runtime_metrics_json: Mapped[str] = mapped_column(Text)
    audit_output_manifest_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("runtime_manifests.manifest_id", ondelete="RESTRICT"),
        nullable=True,
    )
    audit_output_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class RuntimeReviewTarget(RuntimeBase):
    __tablename__ = "runtime_review_targets"
    __table_args__ = (
        UniqueConstraint("authority_scope_key", name="uq_runtime_review_authority_scope"),
        CheckConstraint(
            "target_type IN ('STAGE_OUTPUT','STAGE_PARTITION','REUSABLE_FACT_VERSION')",
            name="ck_runtime_review_target_type",
        ),
        CheckConstraint("member_count >= 0", name="ck_runtime_review_member_count"),
        CheckConstraint("state_version >= 0", name="ck_runtime_review_state_version"),
    )

    review_target_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    authority_scope_key: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(48))
    context_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    stage_execution_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    target_identity_ref: Mapped[str] = mapped_column(String(240))
    target_version: Mapped[str] = mapped_column(String(180))
    output_partition_id: Mapped[Optional[str]] = mapped_column(String(180), nullable=True)
    reviewed_manifest_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_manifests.manifest_id", ondelete="RESTRICT"),
    )
    reviewed_output_hash: Mapped[str] = mapped_column(String(64))
    member_count: Mapped[int] = mapped_column(Integer)
    member_refs_json: Mapped[str] = mapped_column(Text)
    review_contract_version: Mapped[str] = mapped_column(String(180))
    current_review_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    state_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class RuntimeStageReviewDecision(RuntimeBase):
    __tablename__ = "runtime_stage_review_decisions"
    __table_args__ = (
        UniqueConstraint(
            "review_target_id",
            "submitted_state_version",
            name="uq_runtime_review_target_state_version",
        ),
        UniqueConstraint("supersedes_review_id", name="uq_runtime_review_supersedes"),
        CheckConstraint(
            "decision IN ('CONFIRM','REJECT','REOPEN','DEFER','SHELVE')",
            name="ck_runtime_review_decision",
        ),
        CheckConstraint(
            "supersedes_review_id IS NULL OR review_id != supersedes_review_id",
            name="ck_runtime_review_no_self_supersession",
        ),
    )

    review_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    review_target_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_review_targets.review_target_id", ondelete="RESTRICT"),
    )
    decision: Mapped[str] = mapped_column(String(24))
    actor: Mapped[str] = mapped_column(String(160))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime)
    review_note: Mapped[str] = mapped_column(Text)
    supersedes_review_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("runtime_stage_review_decisions.review_id", ondelete="RESTRICT"),
        nullable=True,
    )
    submitted_state_version: Mapped[int] = mapped_column(Integer)


class RuntimeCurrentContextPointer(RuntimeBase):
    __tablename__ = "runtime_current_context_pointers"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "prompt_id", "workflow_track", name="uq_runtime_current_context_scope"
        ),
        CheckConstraint(
            "workflow_track IN ('PRODUCTION','SHADOW','GOLDEN_REPLAY','LEGACY')",
            name="ck_runtime_pointer_track",
        ),
        CheckConstraint("state_version >= 0", name="ck_runtime_pointer_state_version"),
    )

    pointer_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer)
    prompt_id: Mapped[int] = mapped_column(Integer)
    workflow_track: Mapped[str] = mapped_column(String(32))
    current_context_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("runtime_analysis_contexts.context_id", ondelete="RESTRICT"),
        nullable=True,
    )
    state_version: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class RuntimeCurrentContextPointerEvent(RuntimeBase):
    __tablename__ = "runtime_current_context_pointer_events"
    __table_args__ = (
        UniqueConstraint("pointer_id", "new_state_version", name="uq_runtime_pointer_event_version"),
    )

    event_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    pointer_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_current_context_pointers.pointer_id", ondelete="RESTRICT"),
    )
    previous_context_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    new_context_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    actor: Mapped[str] = mapped_column(String(160))
    reason: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    prior_state_version: Mapped[int] = mapped_column(Integer)
    new_state_version: Mapped[int] = mapped_column(Integer)


class RuntimeContextStageSelection(RuntimeBase):
    __tablename__ = "runtime_context_stage_selections"
    __table_args__ = (
        UniqueConstraint(
            "context_id",
            "runtime_stage_profile_version",
            "stage_type",
            "stage_scope_key",
            name="uq_runtime_stage_selection_scope",
        ),
        CheckConstraint("selection_state_version >= 0", name="ck_runtime_selection_state_version"),
    )

    selection_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    context_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_analysis_contexts.context_id", ondelete="RESTRICT"),
    )
    runtime_stage_profile_version: Mapped[str] = mapped_column(String(180))
    stage_type: Mapped[str] = mapped_column(String(80))
    stage_scope_key: Mapped[str] = mapped_column(String(80))
    selected_stage_execution_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("runtime_stage_executions.stage_execution_id", ondelete="RESTRICT"),
        nullable=True,
    )
    selected_output_manifest_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    selected_output_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    selection_state_version: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class RuntimeContextStageSelectionEvent(RuntimeBase):
    __tablename__ = "runtime_context_stage_selection_events"
    __table_args__ = (
        UniqueConstraint("selection_id", "new_state_version", name="uq_runtime_selection_event_version"),
    )

    event_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    selection_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_context_stage_selections.selection_id", ondelete="RESTRICT"),
    )
    previous_stage_execution_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    new_stage_execution_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    actor: Mapped[str] = mapped_column(String(160))
    reason: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    prior_state_version: Mapped[int] = mapped_column(Integer)
    new_state_version: Mapped[int] = mapped_column(Integer)


class RuntimeValidityState(RuntimeBase):
    __tablename__ = "runtime_validity_states"
    __table_args__ = (
        UniqueConstraint("target_key", name="uq_runtime_validity_target"),
        CheckConstraint(
            "target_type IN ('CONTEXT','STAGE_EXECUTION','STAGE_OUTPUT','STAGE_PARTITION')",
            name="ck_runtime_validity_target_type",
        ),
        CheckConstraint(
            "direct_eligibility IN ('ELIGIBLE','INVALIDATED','SUPERSEDED','BLOCKED')",
            name="ck_runtime_direct_eligibility",
        ),
        CheckConstraint("state_version >= 0", name="ck_runtime_validity_state_version"),
    )

    validity_state_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    target_key: Mapped[str] = mapped_column(String(300))
    target_type: Mapped[str] = mapped_column(String(40))
    context_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    stage_execution_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    target_ref: Mapped[str] = mapped_column(String(240))
    target_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    direct_eligibility: Mapped[str] = mapped_column(String(32))
    state_version: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class RuntimeValidityEvent(RuntimeBase):
    __tablename__ = "runtime_validity_events"
    __table_args__ = (
        UniqueConstraint("validity_state_id", "new_state_version", name="uq_runtime_validity_event_version"),
        CheckConstraint(
            "decision IN ('INVALIDATE','REACTIVATE')",
            name="ck_runtime_validity_decision",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    validity_state_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_validity_states.validity_state_id", ondelete="RESTRICT"),
    )
    decision: Mapped[str] = mapped_column(String(24))
    previous_eligibility: Mapped[str] = mapped_column(String(32))
    new_eligibility: Mapped[str] = mapped_column(String(32))
    reason_code: Mapped[str] = mapped_column(String(120))
    reason_note: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(160))
    source: Mapped[str] = mapped_column(String(160))
    authorization_evidence_json: Mapped[str] = mapped_column(Text)
    compatibility_validation_json: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    expected_state_version: Mapped[int] = mapped_column(Integer)
    new_state_version: Mapped[int] = mapped_column(Integer)
