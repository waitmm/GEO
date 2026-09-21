"""Allow immutable V2 analyses to be created from explicit historical Runs.

Revision ID: 20260921_01
Revises: 20260920_02
Create Date: 2026-09-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260921_01"
down_revision = "20260920_02"
branch_labels = None
depends_on = None


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
    context = op.get_context()
    bind = op.get_bind()
    with context.autocommit_block():
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
        bind.exec_driver_sql("DROP TABLE IF EXISTS _alembic_tmp_single_prompt_analyses")
        bind.exec_driver_sql("DROP TABLE IF EXISTS _alembic_tmp_single_prompt_analysis_contexts")
    with op.batch_alter_table("single_prompt_analyses") as batch:
        batch.alter_column(
            "task_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
    with op.batch_alter_table("single_prompt_analysis_contexts") as batch:
        batch.alter_column(
            "task_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
    # SQLite batch recreation drops table-local triggers.
    _immutable_triggers("single_prompt_analysis_contexts")
    violations = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"release migration introduced foreign-key violations: {violations[:10]}")
    with context.autocommit_block():
        bind.exec_driver_sql("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    context = op.get_context()
    bind = op.get_bind()
    with context.autocommit_block():
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("single_prompt_analysis_contexts") as batch:
        batch.alter_column(
            "task_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
    with op.batch_alter_table("single_prompt_analyses") as batch:
        batch.alter_column(
            "task_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
    _immutable_triggers("single_prompt_analysis_contexts")
    violations = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"release downgrade introduced foreign-key violations: {violations[:10]}")
    with context.autocommit_block():
        bind.exec_driver_sql("PRAGMA foreign_keys=ON")
