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


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in _INITIAL_TABLE_ORDER:
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
