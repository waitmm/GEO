"""Add automatic authority and delivery-loop tables to release.

Revision ID: 20260930_01
Revises: 20260929_02
Create Date: 2026-09-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models import Base


revision = "20260930_01"
down_revision = "20260929_02"
branch_labels = None
depends_on = None


_DELIVERY_TABLES = (
    "single_prompt_execution_proposals",
    "single_prompt_execution_proposal_results",
    "single_prompt_execution_confirmations",
    "single_prompt_publication_records",
    "single_prompt_retest_executions",
    "single_prompt_comparison_results",
)


def _immutable_triggers(table_name: str) -> None:
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


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    source_columns = {row["name"] for row in inspector.get_columns("single_prompt_prepared_source_snapshots")}
    if "reused_from_snapshot_id" not in source_columns:
        op.add_column(
            "single_prompt_prepared_source_snapshots",
            sa.Column("reused_from_snapshot_id", sa.String(length=80), nullable=True),
        )
    source_indexes = {row["name"] for row in inspector.get_indexes("single_prompt_prepared_source_snapshots")}
    if "ix_single_prompt_prepared_snapshot_reused_from" not in source_indexes:
        op.create_index(
            "ix_single_prompt_prepared_snapshot_reused_from",
            "single_prompt_prepared_source_snapshots",
            ["reused_from_snapshot_id"],
        )
    strategy_columns = {row["name"] for row in inspector.get_columns("single_prompt_strategy_executions")}
    if "input_authority_type" not in strategy_columns:
        op.add_column(
            "single_prompt_strategy_executions",
            sa.Column("input_authority_type", sa.String(length=40), nullable=False, server_default="HUMAN_REVIEW"),
        )
    if "input_authority_id" not in strategy_columns:
        op.add_column(
            "single_prompt_strategy_executions",
            sa.Column("input_authority_id", sa.String(length=120), nullable=False, server_default=""),
        )
    if "input_authority_hash" not in strategy_columns:
        op.add_column(
            "single_prompt_strategy_executions",
            sa.Column("input_authority_hash", sa.String(length=64), nullable=False, server_default=""),
        )
    strategy_indexes = {row["name"] for row in inspector.get_indexes("single_prompt_strategy_executions")}
    if "ix_single_prompt_strategy_execution_authority" not in strategy_indexes:
        op.create_index(
            "ix_single_prompt_strategy_execution_authority",
            "single_prompt_strategy_executions",
            ["input_authority_type", "input_authority_id"],
        )

    for table_name in _DELIVERY_TABLES:
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=False)
    for table_name in (
        "single_prompt_execution_proposal_results",
        "single_prompt_execution_confirmations",
        "single_prompt_publication_records",
        "single_prompt_comparison_results",
    ):
        _immutable_triggers(table_name)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(_DELIVERY_TABLES):
        Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
    op.drop_index("ix_single_prompt_strategy_execution_authority", table_name="single_prompt_strategy_executions")
    op.drop_column("single_prompt_strategy_executions", "input_authority_hash")
    op.drop_column("single_prompt_strategy_executions", "input_authority_id")
    op.drop_column("single_prompt_strategy_executions", "input_authority_type")
    op.drop_index(
        "ix_single_prompt_prepared_snapshot_reused_from",
        table_name="single_prompt_prepared_source_snapshots",
    )
    op.drop_column("single_prompt_prepared_source_snapshots", "reused_from_snapshot_id")
