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
from app.release_schema import RELEASE_TABLE_ORDER


revision = "20260920_01"
down_revision = None
branch_labels = ("release_1_0",)
depends_on = None


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
    for table_name in RELEASE_TABLE_ORDER:
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
    for table_name in reversed(RELEASE_TABLE_ORDER):
        Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
