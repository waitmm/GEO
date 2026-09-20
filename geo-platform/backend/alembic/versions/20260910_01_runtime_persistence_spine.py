"""RFC-RUNTIME-001 Phase 1A persistence spine.

This revision is an artifact only until a separately authorized Runtime shadow
deployment. Phase 1A acceptance applies it exclusively to temporary databases.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260910_01"
down_revision = "20260819_01"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _immutable_triggers(table_names: list[str]) -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    for table_name in table_names:
        op.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS trg_{table_name}_no_update
            BEFORE UPDATE ON {table_name}
            BEGIN
              SELECT RAISE(ABORT, 'IMMUTABLE_OBJECT');
            END
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS trg_{table_name}_no_delete
            BEFORE DELETE ON {table_name}
            BEGIN
              SELECT RAISE(ABORT, 'HISTORICAL_OBJECT_DELETE_FORBIDDEN');
            END
            """
        )


def _projection_guard_triggers() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_runtime_stage_execution_identity_immutable
        BEFORE UPDATE ON runtime_stage_executions
        WHEN OLD.context_id IS NOT NEW.context_id
          OR OLD.runtime_stage_profile_version IS NOT NEW.runtime_stage_profile_version
          OR OLD.stage_type IS NOT NEW.stage_type
          OR OLD.stage_scope_key IS NOT NEW.stage_scope_key
          OR OLD.stage_contract_version IS NOT NEW.stage_contract_version
          OR OLD.input_manifest_id IS NOT NEW.input_manifest_id
          OR OLD.input_set_hash IS NOT NEW.input_set_hash
          OR OLD.configuration_manifest_id IS NOT NEW.configuration_manifest_id
          OR OLD.semantic_config_signature IS NOT NEW.semantic_config_signature
          OR OLD.semantic_execution_fingerprint IS NOT NEW.semantic_execution_fingerprint
          OR OLD.supersedes_stage_execution_id IS NOT NEW.supersedes_stage_execution_id
          OR OLD.created_by IS NOT NEW.created_by
          OR OLD.creation_reason IS NOT NEW.creation_reason
          OR OLD.created_at IS NOT NEW.created_at
        BEGIN
          SELECT RAISE(ABORT, 'STAGE_EXECUTION_IDENTITY_IMMUTABLE');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_runtime_stage_success_immutable
        BEFORE UPDATE ON runtime_stage_executions
        WHEN OLD.compute_outcome = 'SUCCEEDED'
        BEGIN
          SELECT RAISE(ABORT, 'SUCCESSFUL_STAGE_EXECUTION_IMMUTABLE');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_runtime_stage_success_fenced
        BEFORE UPDATE ON runtime_stage_executions
        WHEN NEW.compute_outcome = 'SUCCEEDED' AND OLD.compute_outcome != 'SUCCEEDED'
          AND NOT EXISTS (
            SELECT 1
            FROM runtime_stage_attempts AS attempt
            WHERE attempt.attempt_id = NEW.completion_attempt_id
              AND attempt.stage_execution_id = OLD.stage_execution_id
              AND attempt.authority_generation = OLD.current_active_authority_generation
          )
        BEGIN
          SELECT RAISE(ABORT, 'FENCING_AUTHORITY_REQUIRED');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_runtime_review_linear_chain
        BEFORE INSERT ON runtime_stage_review_decisions
        WHEN (
          NEW.supersedes_review_id IS NULL
          AND EXISTS (
            SELECT 1 FROM runtime_review_targets AS target
            WHERE target.review_target_id = NEW.review_target_id
              AND (target.current_review_id IS NOT NULL OR target.state_version != NEW.submitted_state_version)
          )
        ) OR (
          NEW.supersedes_review_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1
            FROM runtime_review_targets AS target
            JOIN runtime_stage_review_decisions AS predecessor
              ON predecessor.review_id = NEW.supersedes_review_id
            WHERE target.review_target_id = NEW.review_target_id
              AND predecessor.review_target_id = NEW.review_target_id
              AND target.current_review_id = NEW.supersedes_review_id
              AND target.state_version = NEW.submitted_state_version
          )
        )
        BEGIN
          SELECT RAISE(ABORT, 'REVIEW_CONFLICT');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_runtime_review_target_identity_immutable
        BEFORE UPDATE ON runtime_review_targets
        WHEN OLD.authority_scope_key IS NOT NEW.authority_scope_key
          OR OLD.target_type IS NOT NEW.target_type
          OR OLD.context_id IS NOT NEW.context_id
          OR OLD.stage_execution_id IS NOT NEW.stage_execution_id
          OR OLD.target_identity_ref IS NOT NEW.target_identity_ref
          OR OLD.target_version IS NOT NEW.target_version
          OR OLD.output_partition_id IS NOT NEW.output_partition_id
          OR OLD.reviewed_manifest_id IS NOT NEW.reviewed_manifest_id
          OR OLD.reviewed_output_hash IS NOT NEW.reviewed_output_hash
          OR OLD.member_count IS NOT NEW.member_count
          OR OLD.member_refs_json IS NOT NEW.member_refs_json
          OR OLD.review_contract_version IS NOT NEW.review_contract_version
          OR OLD.created_at IS NOT NEW.created_at
        BEGIN
          SELECT RAISE(ABORT, 'REVIEW_TARGET_IDENTITY_IMMUTABLE');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_runtime_pointer_scope_immutable
        BEFORE UPDATE ON runtime_current_context_pointers
        WHEN OLD.project_id IS NOT NEW.project_id
          OR OLD.prompt_id IS NOT NEW.prompt_id
          OR OLD.workflow_track IS NOT NEW.workflow_track
        BEGIN
          SELECT RAISE(ABORT, 'CURRENT_CONTEXT_POINTER_SCOPE_IMMUTABLE');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_runtime_selection_scope_immutable
        BEFORE UPDATE ON runtime_context_stage_selections
        WHEN OLD.context_id IS NOT NEW.context_id
          OR OLD.runtime_stage_profile_version IS NOT NEW.runtime_stage_profile_version
          OR OLD.stage_type IS NOT NEW.stage_type
          OR OLD.stage_scope_key IS NOT NEW.stage_scope_key
        BEGIN
          SELECT RAISE(ABORT, 'CONTEXT_STAGE_SELECTION_SCOPE_IMMUTABLE');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_runtime_validity_target_immutable
        BEFORE UPDATE ON runtime_validity_states
        WHEN OLD.target_key IS NOT NEW.target_key
          OR OLD.target_type IS NOT NEW.target_type
          OR OLD.context_id IS NOT NEW.context_id
          OR OLD.stage_execution_id IS NOT NEW.stage_execution_id
          OR OLD.target_ref IS NOT NEW.target_ref
          OR OLD.target_hash IS NOT NEW.target_hash
        BEGIN
          SELECT RAISE(ABORT, 'VALIDITY_TARGET_IMMUTABLE');
        END
        """
    )
    for table_name in (
        "runtime_stage_executions",
        "runtime_review_targets",
        "runtime_current_context_pointers",
        "runtime_context_stage_selections",
        "runtime_validity_states",
    ):
        op.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS trg_{table_name}_no_delete
            BEFORE DELETE ON {table_name}
            BEGIN
              SELECT RAISE(ABORT, 'HISTORICAL_OBJECT_DELETE_FORBIDDEN');
            END
            """
        )


def upgrade() -> None:
    tables = _tables()
    if "runtime_manifests" not in tables:
        op.create_table(
            "runtime_manifests",
            sa.Column("manifest_id", sa.String(160), nullable=False),
            sa.Column("manifest_type", sa.String(180), nullable=False),
            sa.Column("manifest_contract_version", sa.String(180), nullable=False),
            sa.Column("canonicalization_version", sa.String(100), nullable=False),
            sa.Column("member_count", sa.Integer(), nullable=False),
            sa.Column("member_refs_json", sa.Text(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("canonical_bytes", sa.LargeBinary(), nullable=False),
            sa.Column("canonical_hash", sa.String(64), nullable=False),
            sa.Column("created_by", sa.String(160), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint("member_count >= 0", name="ck_runtime_manifest_member_count"),
            sa.PrimaryKeyConstraint("manifest_id"),
        )
        op.create_index("ix_runtime_manifest_hash", "runtime_manifests", ["canonical_hash"])

    if "runtime_analysis_contexts" not in tables:
        op.create_table(
            "runtime_analysis_contexts",
            sa.Column("context_id", sa.String(160), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("prompt_id", sa.Integer(), nullable=False),
            sa.Column("workflow_track", sa.String(32), nullable=False),
            sa.Column("context_fingerprint", sa.String(64), nullable=False),
            sa.Column("fingerprint_contract_version", sa.String(120), nullable=False),
            sa.Column("root_manifest_id", sa.String(160), nullable=False),
            sa.Column("root_manifest_hash", sa.String(64), nullable=False),
            sa.Column("root_runtime_contract_profile_version", sa.String(160), nullable=False),
            sa.Column("context_manifest_hash", sa.String(64), nullable=False),
            sa.Column("evidence_package_ref", sa.String(240), nullable=False),
            sa.Column("creation_actor", sa.String(160), nullable=False),
            sa.Column("creation_reason", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "workflow_track IN ('PRODUCTION','SHADOW','GOLDEN_REPLAY','LEGACY')",
                name="ck_runtime_context_track",
            ),
            sa.ForeignKeyConstraint(["root_manifest_id"], ["runtime_manifests.manifest_id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("context_id"),
        )
        op.create_index(
            "ix_runtime_context_scope",
            "runtime_analysis_contexts",
            ["project_id", "prompt_id", "workflow_track"],
        )
        op.create_index(
            "ix_runtime_context_fingerprint", "runtime_analysis_contexts", ["context_fingerprint"]
        )

    if "runtime_stage_executions" not in tables:
        op.create_table(
            "runtime_stage_executions",
            sa.Column("stage_execution_id", sa.String(160), nullable=False),
            sa.Column("context_id", sa.String(160), nullable=False),
            sa.Column("runtime_stage_profile_version", sa.String(180), nullable=False),
            sa.Column("stage_type", sa.String(80), nullable=False),
            sa.Column("stage_scope_key", sa.String(80), nullable=False),
            sa.Column("stage_contract_version", sa.String(180), nullable=False),
            sa.Column("input_manifest_id", sa.String(160), nullable=False),
            sa.Column("input_set_hash", sa.String(64), nullable=False),
            sa.Column("configuration_manifest_id", sa.String(160), nullable=False),
            sa.Column("semantic_config_signature", sa.String(64), nullable=False),
            sa.Column("semantic_execution_fingerprint", sa.String(64), nullable=True),
            sa.Column("supersedes_stage_execution_id", sa.String(160), nullable=True),
            sa.Column("compute_outcome", sa.String(32), nullable=False),
            sa.Column("current_active_authority_generation", sa.Integer(), nullable=False),
            sa.Column("output_manifest_id", sa.String(160), nullable=True),
            sa.Column("output_set_hash", sa.String(64), nullable=True),
            sa.Column("output_count", sa.Integer(), nullable=True),
            sa.Column("completion_attempt_id", sa.String(160), nullable=True),
            sa.Column("created_by", sa.String(160), nullable=False),
            sa.Column("creation_reason", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint(
                "compute_outcome IN ('NOT_STARTED','ACTIVE','SUCCEEDED','TERMINAL_FAILED','SKIPPED')",
                name="ck_runtime_stage_compute_outcome",
            ),
            sa.CheckConstraint(
                "current_active_authority_generation >= 0", name="ck_runtime_stage_generation"
            ),
            sa.CheckConstraint(
                "(compute_outcome = 'SUCCEEDED' AND output_manifest_id IS NOT NULL "
                "AND output_set_hash IS NOT NULL AND output_count IS NOT NULL "
                "AND output_count >= 0 AND completion_attempt_id IS NOT NULL) OR "
                "(compute_outcome != 'SUCCEEDED' AND output_manifest_id IS NULL "
                "AND output_set_hash IS NULL AND output_count IS NULL "
                "AND completion_attempt_id IS NULL)",
                name="ck_runtime_stage_output_publication",
            ),
            sa.ForeignKeyConstraint(["context_id"], ["runtime_analysis_contexts.context_id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["input_manifest_id"], ["runtime_manifests.manifest_id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["configuration_manifest_id"], ["runtime_manifests.manifest_id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["output_manifest_id"], ["runtime_manifests.manifest_id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(
                ["supersedes_stage_execution_id"],
                ["runtime_stage_executions.stage_execution_id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("stage_execution_id"),
        )
        op.create_index(
            "ix_runtime_stage_context_type", "runtime_stage_executions", ["context_id", "stage_type"]
        )
        op.create_index(
            "ix_runtime_stage_semantic_fingerprint",
            "runtime_stage_executions",
            ["semantic_execution_fingerprint"],
        )

    if "runtime_stage_input_edges" not in tables:
        op.create_table(
            "runtime_stage_input_edges",
            sa.Column("edge_id", sa.String(160), nullable=False),
            sa.Column("stage_execution_id", sa.String(160), nullable=False),
            sa.Column("input_role", sa.String(40), nullable=False),
            sa.Column("source_manifest_type", sa.String(180), nullable=False),
            sa.Column("source_identity_ref", sa.String(240), nullable=False),
            sa.Column("source_contract_version", sa.String(180), nullable=False),
            sa.Column("consumed_semantic_hash", sa.String(64), nullable=False),
            sa.Column("source_partition_ref", sa.String(240), nullable=True),
            sa.Column("upstream_stage_execution_id", sa.String(160), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "input_role IN ('ROOT_MANIFEST','UPSTREAM_STAGE_OUTPUT','REUSABLE_INPUT',"
                "'AUTHORITATIVE_REVIEW','CONFIGURATION')",
                name="ck_runtime_stage_input_role",
            ),
            sa.ForeignKeyConstraint(["stage_execution_id"], ["runtime_stage_executions.stage_execution_id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["upstream_stage_execution_id"], ["runtime_stage_executions.stage_execution_id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("edge_id"),
            sa.UniqueConstraint(
                "stage_execution_id",
                "input_role",
                "source_identity_ref",
                "source_contract_version",
                "consumed_semantic_hash",
                name="uq_runtime_stage_input_edge_identity",
            ),
        )
        op.create_index(
            "ix_runtime_stage_input_upstream",
            "runtime_stage_input_edges",
            ["upstream_stage_execution_id"],
        )

    if "runtime_stage_attempts" not in tables:
        op.create_table(
            "runtime_stage_attempts",
            sa.Column("attempt_id", sa.String(160), nullable=False),
            sa.Column("stage_execution_id", sa.String(160), nullable=False),
            sa.Column("attempt_no", sa.Integer(), nullable=False),
            sa.Column("authority_generation", sa.Integer(), nullable=False),
            sa.Column("trigger_actor", sa.String(160), nullable=False),
            sa.Column("trigger_reason", sa.Text(), nullable=False),
            sa.Column("executor_identity", sa.String(180), nullable=False),
            sa.Column("owner_id", sa.String(180), nullable=False),
            sa.Column("lease_acquired_at", sa.DateTime(), nullable=False),
            sa.Column("lease_expires_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint("attempt_no > 0", name="ck_runtime_attempt_no"),
            sa.CheckConstraint("authority_generation > 0", name="ck_runtime_attempt_generation"),
            sa.ForeignKeyConstraint(["stage_execution_id"], ["runtime_stage_executions.stage_execution_id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("attempt_id"),
            sa.UniqueConstraint("stage_execution_id", "attempt_no", name="uq_runtime_attempt_no"),
            sa.UniqueConstraint(
                "stage_execution_id", "authority_generation", name="uq_runtime_attempt_generation"
            ),
        )

    if "runtime_stage_attempt_results" not in tables:
        op.create_table(
            "runtime_stage_attempt_results",
            sa.Column("attempt_id", sa.String(160), nullable=False),
            sa.Column("attempt_outcome", sa.String(48), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=False),
            sa.Column("error_code", sa.String(120), nullable=False),
            sa.Column("error_detail", sa.Text(), nullable=False),
            sa.Column("retryable", sa.Boolean(), nullable=False),
            sa.Column("runtime_metrics_json", sa.Text(), nullable=False),
            sa.Column("audit_output_manifest_id", sa.String(160), nullable=True),
            sa.Column("audit_output_hash", sa.String(64), nullable=True),
            sa.CheckConstraint(
                "attempt_outcome IN ('SUCCEEDED','FAILED_RETRYABLE','FAILED_FINAL',"
                "'LATE_OR_SUPERSEDED_ATTEMPT')",
                name="ck_runtime_attempt_outcome",
            ),
            sa.ForeignKeyConstraint(["attempt_id"], ["runtime_stage_attempts.attempt_id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["audit_output_manifest_id"], ["runtime_manifests.manifest_id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("attempt_id"),
        )

    if "runtime_review_targets" not in tables:
        op.create_table(
            "runtime_review_targets",
            sa.Column("review_target_id", sa.String(160), nullable=False),
            sa.Column("authority_scope_key", sa.String(64), nullable=False),
            sa.Column("target_type", sa.String(48), nullable=False),
            sa.Column("context_id", sa.String(160), nullable=True),
            sa.Column("stage_execution_id", sa.String(160), nullable=True),
            sa.Column("target_identity_ref", sa.String(240), nullable=False),
            sa.Column("target_version", sa.String(180), nullable=False),
            sa.Column("output_partition_id", sa.String(180), nullable=True),
            sa.Column("reviewed_manifest_id", sa.String(160), nullable=False),
            sa.Column("reviewed_output_hash", sa.String(64), nullable=False),
            sa.Column("member_count", sa.Integer(), nullable=False),
            sa.Column("member_refs_json", sa.Text(), nullable=False),
            sa.Column("review_contract_version", sa.String(180), nullable=False),
            sa.Column("current_review_id", sa.String(160), nullable=True),
            sa.Column("state_version", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "target_type IN ('STAGE_OUTPUT','STAGE_PARTITION','REUSABLE_FACT_VERSION')",
                name="ck_runtime_review_target_type",
            ),
            sa.CheckConstraint("member_count >= 0", name="ck_runtime_review_member_count"),
            sa.CheckConstraint("state_version >= 0", name="ck_runtime_review_state_version"),
            sa.ForeignKeyConstraint(["reviewed_manifest_id"], ["runtime_manifests.manifest_id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("review_target_id"),
            sa.UniqueConstraint("authority_scope_key", name="uq_runtime_review_authority_scope"),
        )

    if "runtime_stage_review_decisions" not in tables:
        op.create_table(
            "runtime_stage_review_decisions",
            sa.Column("review_id", sa.String(160), nullable=False),
            sa.Column("review_target_id", sa.String(160), nullable=False),
            sa.Column("decision", sa.String(24), nullable=False),
            sa.Column("actor", sa.String(160), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(), nullable=False),
            sa.Column("review_note", sa.Text(), nullable=False),
            sa.Column("supersedes_review_id", sa.String(160), nullable=True),
            sa.Column("submitted_state_version", sa.Integer(), nullable=False),
            sa.CheckConstraint(
                "decision IN ('CONFIRM','REJECT','REOPEN','DEFER','SHELVE')",
                name="ck_runtime_review_decision",
            ),
            sa.CheckConstraint(
                "supersedes_review_id IS NULL OR review_id != supersedes_review_id",
                name="ck_runtime_review_no_self_supersession",
            ),
            sa.ForeignKeyConstraint(["review_target_id"], ["runtime_review_targets.review_target_id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["supersedes_review_id"], ["runtime_stage_review_decisions.review_id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("review_id"),
            sa.UniqueConstraint(
                "review_target_id",
                "submitted_state_version",
                name="uq_runtime_review_target_state_version",
            ),
            sa.UniqueConstraint("supersedes_review_id", name="uq_runtime_review_supersedes"),
        )

    if "runtime_current_context_pointers" not in tables:
        op.create_table(
            "runtime_current_context_pointers",
            sa.Column("pointer_id", sa.String(160), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("prompt_id", sa.Integer(), nullable=False),
            sa.Column("workflow_track", sa.String(32), nullable=False),
            sa.Column("current_context_id", sa.String(160), nullable=True),
            sa.Column("state_version", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "workflow_track IN ('PRODUCTION','SHADOW','GOLDEN_REPLAY','LEGACY')",
                name="ck_runtime_pointer_track",
            ),
            sa.CheckConstraint("state_version >= 0", name="ck_runtime_pointer_state_version"),
            sa.ForeignKeyConstraint(["current_context_id"], ["runtime_analysis_contexts.context_id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("pointer_id"),
            sa.UniqueConstraint(
                "project_id", "prompt_id", "workflow_track", name="uq_runtime_current_context_scope"
            ),
        )

    if "runtime_current_context_pointer_events" not in tables:
        op.create_table(
            "runtime_current_context_pointer_events",
            sa.Column("event_id", sa.String(160), nullable=False),
            sa.Column("pointer_id", sa.String(160), nullable=False),
            sa.Column("previous_context_id", sa.String(160), nullable=True),
            sa.Column("new_context_id", sa.String(160), nullable=True),
            sa.Column("actor", sa.String(160), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(), nullable=False),
            sa.Column("prior_state_version", sa.Integer(), nullable=False),
            sa.Column("new_state_version", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["pointer_id"], ["runtime_current_context_pointers.pointer_id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("event_id"),
            sa.UniqueConstraint("pointer_id", "new_state_version", name="uq_runtime_pointer_event_version"),
        )

    if "runtime_context_stage_selections" not in tables:
        op.create_table(
            "runtime_context_stage_selections",
            sa.Column("selection_id", sa.String(160), nullable=False),
            sa.Column("context_id", sa.String(160), nullable=False),
            sa.Column("runtime_stage_profile_version", sa.String(180), nullable=False),
            sa.Column("stage_type", sa.String(80), nullable=False),
            sa.Column("stage_scope_key", sa.String(80), nullable=False),
            sa.Column("selected_stage_execution_id", sa.String(160), nullable=True),
            sa.Column("selected_output_manifest_id", sa.String(160), nullable=True),
            sa.Column("selected_output_hash", sa.String(64), nullable=True),
            sa.Column("selection_state_version", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint("selection_state_version >= 0", name="ck_runtime_selection_state_version"),
            sa.ForeignKeyConstraint(["context_id"], ["runtime_analysis_contexts.context_id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["selected_stage_execution_id"], ["runtime_stage_executions.stage_execution_id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("selection_id"),
            sa.UniqueConstraint(
                "context_id",
                "runtime_stage_profile_version",
                "stage_type",
                "stage_scope_key",
                name="uq_runtime_stage_selection_scope",
            ),
        )

    if "runtime_context_stage_selection_events" not in tables:
        op.create_table(
            "runtime_context_stage_selection_events",
            sa.Column("event_id", sa.String(160), nullable=False),
            sa.Column("selection_id", sa.String(160), nullable=False),
            sa.Column("previous_stage_execution_id", sa.String(160), nullable=True),
            sa.Column("new_stage_execution_id", sa.String(160), nullable=True),
            sa.Column("actor", sa.String(160), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(), nullable=False),
            sa.Column("prior_state_version", sa.Integer(), nullable=False),
            sa.Column("new_state_version", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["selection_id"], ["runtime_context_stage_selections.selection_id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("event_id"),
            sa.UniqueConstraint("selection_id", "new_state_version", name="uq_runtime_selection_event_version"),
        )

    if "runtime_validity_states" not in tables:
        op.create_table(
            "runtime_validity_states",
            sa.Column("validity_state_id", sa.String(160), nullable=False),
            sa.Column("target_key", sa.String(300), nullable=False),
            sa.Column("target_type", sa.String(40), nullable=False),
            sa.Column("context_id", sa.String(160), nullable=True),
            sa.Column("stage_execution_id", sa.String(160), nullable=True),
            sa.Column("target_ref", sa.String(240), nullable=False),
            sa.Column("target_hash", sa.String(64), nullable=True),
            sa.Column("direct_eligibility", sa.String(32), nullable=False),
            sa.Column("state_version", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "target_type IN ('CONTEXT','STAGE_EXECUTION','STAGE_OUTPUT','STAGE_PARTITION')",
                name="ck_runtime_validity_target_type",
            ),
            sa.CheckConstraint(
                "direct_eligibility IN ('ELIGIBLE','INVALIDATED','SUPERSEDED','BLOCKED')",
                name="ck_runtime_direct_eligibility",
            ),
            sa.CheckConstraint("state_version >= 0", name="ck_runtime_validity_state_version"),
            sa.PrimaryKeyConstraint("validity_state_id"),
            sa.UniqueConstraint("target_key", name="uq_runtime_validity_target"),
        )

    if "runtime_validity_events" not in tables:
        op.create_table(
            "runtime_validity_events",
            sa.Column("event_id", sa.String(160), nullable=False),
            sa.Column("validity_state_id", sa.String(160), nullable=False),
            sa.Column("decision", sa.String(24), nullable=False),
            sa.Column("previous_eligibility", sa.String(32), nullable=False),
            sa.Column("new_eligibility", sa.String(32), nullable=False),
            sa.Column("reason_code", sa.String(120), nullable=False),
            sa.Column("reason_note", sa.Text(), nullable=False),
            sa.Column("actor", sa.String(160), nullable=False),
            sa.Column("source", sa.String(160), nullable=False),
            sa.Column("authorization_evidence_json", sa.Text(), nullable=False),
            sa.Column("compatibility_validation_json", sa.Text(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(), nullable=False),
            sa.Column("expected_state_version", sa.Integer(), nullable=False),
            sa.Column("new_state_version", sa.Integer(), nullable=False),
            sa.CheckConstraint(
                "decision IN ('INVALIDATE','REACTIVATE')", name="ck_runtime_validity_decision"
            ),
            sa.ForeignKeyConstraint(["validity_state_id"], ["runtime_validity_states.validity_state_id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("event_id"),
            sa.UniqueConstraint(
                "validity_state_id", "new_state_version", name="uq_runtime_validity_event_version"
            ),
        )

    _immutable_triggers(
        [
            "runtime_manifests",
            "runtime_analysis_contexts",
            "runtime_stage_input_edges",
            "runtime_stage_attempts",
            "runtime_stage_attempt_results",
            "runtime_stage_review_decisions",
            "runtime_current_context_pointer_events",
            "runtime_context_stage_selection_events",
            "runtime_validity_events",
        ]
    )
    _projection_guard_triggers()


def downgrade() -> None:
    for table_name in (
        "runtime_validity_events",
        "runtime_validity_states",
        "runtime_context_stage_selection_events",
        "runtime_context_stage_selections",
        "runtime_current_context_pointer_events",
        "runtime_current_context_pointers",
        "runtime_stage_review_decisions",
        "runtime_review_targets",
        "runtime_stage_attempt_results",
        "runtime_stage_attempts",
        "runtime_stage_input_edges",
        "runtime_stage_executions",
        "runtime_analysis_contexts",
        "runtime_manifests",
    ):
        if table_name in _tables():
            op.drop_table(table_name)
