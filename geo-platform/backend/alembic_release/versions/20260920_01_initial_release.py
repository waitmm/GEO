"""GEO 1.0 first-slice release baseline.

Revision ID: 20260920_01
Revises: None
Create Date: 2026-09-20

The allowlist is deliberate. This migration creates selected tables one by
one and never calls Base.metadata.create_all(). Before first external delivery
the baseline may still be reviewed; after that, schema changes require a new
revision rather than editing this file.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.models import Base


revision = "20260920_01"
down_revision = None
branch_labels = ("release_1_0",)
depends_on = None


_INITIAL_TABLE_ORDER = (
    "organizations",
    "projects",
    "competitors",
    "topics",
    "prompt_clusters",
    "prompts",
    "monitoring_batches",
    "browser_monitor_tasks",
    "browser_monitor_runs",
    "reference_sources",
    "retrieval_candidates",
    "run_artifacts",
    "recommendation_entities",
    "target_brand_capability_truths",
    "llm_call_cache",
    "single_prompt_analyses",
    "single_prompt_analysis_contexts",
    "single_prompt_citation_manifests",
    "single_prompt_source_preparations",
    "single_prompt_source_dispositions",
    "single_prompt_prepared_source_snapshots",
    "single_prompt_source_completion_manifests",
    "single_prompt_diagnosis_executions",
    "single_prompt_diagnosis_results",
    "single_prompt_diagnosis_reviews",
)


_IMMUTABLE_TABLES = (
    "single_prompt_analysis_contexts",
    "single_prompt_citation_manifests",
    "single_prompt_prepared_source_snapshots",
    "single_prompt_source_completion_manifests",
    "single_prompt_diagnosis_results",
    "single_prompt_diagnosis_reviews",
)


def _create_original_source_snapshots() -> None:
    # Freeze the original schema; a later ORM column must not appear at this revision.
    name = "single_prompt_prepared_source_snapshots"
    op.create_table(name,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.String(80), nullable=False),
        sa.Column("preparation_id", sa.String(80), sa.ForeignKey("single_prompt_source_preparations.preparation_id"), nullable=False),
        sa.Column("context_id", sa.String(80), sa.ForeignKey("single_prompt_analysis_contexts.context_id"), nullable=False),
        sa.Column("citation_manifest_id", sa.String(80), sa.ForeignKey("single_prompt_citation_manifests.manifest_id"), nullable=False),
        sa.Column("source_key", sa.String(64), nullable=False),
        sa.Column("canonical_url", sa.String(1200), nullable=False),
        sa.Column("original_urls_json", sa.Text(), nullable=False),
        sa.Column("reference_observations_json", sa.Text(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("clean_text", sa.Text(), nullable=False),
        sa.Column("artifact_path", sa.String(1000), nullable=False),
        sa.Column("artifact_hash", sa.String(64), nullable=False),
        sa.Column("passages_json", sa.Text(), nullable=False),
        sa.Column("passages_hash", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(80), nullable=False),
        sa.Column("acquisition_method", sa.String(40), nullable=False),
        sa.Column("coverage_scope", sa.String(40), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("submitted_by", sa.String(120), nullable=False),
        sa.Column("reused_from_snapshot_id", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    for column in ("id", "snapshot_id", "preparation_id", "context_id", "citation_manifest_id", "source_key", "content_hash", "reused_from_snapshot_id"):
        op.create_index(f"ix_{name}_{column}", name, [column], unique=column == "snapshot_id")
    op.create_index("ix_single_prompt_prepared_snapshot_source", name, ["preparation_id", "source_key", "created_at"])


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in _INITIAL_TABLE_ORDER:
        if table_name == "single_prompt_prepared_source_snapshots":
            _create_original_source_snapshots()
        else:
            Base.metadata.tables[table_name].create(bind=bind, checkfirst=False)
    for table_name in _IMMUTABLE_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_no_update
            BEFORE UPDATE ON {table_name}
            BEGIN
              SELECT RAISE(ABORT, 'RELEASE_HISTORY_IMMUTABLE');
            END
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_no_delete
            BEFORE DELETE ON {table_name}
            BEGIN
              SELECT RAISE(ABORT, 'RELEASE_HISTORY_IMMUTABLE');
            END
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(_INITIAL_TABLE_ORDER):
        Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
