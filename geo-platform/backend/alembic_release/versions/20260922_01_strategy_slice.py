"""Add the reviewed V2 strategy slice to the release database.

Revision ID: 20260922_01
Revises: 20260921_01
Create Date: 2026-09-22
"""

from __future__ import annotations

from alembic import op

from app.models import Base


revision = "20260922_01"
down_revision = "20260921_01"
branch_labels = None
depends_on = None


_TABLES = (
    "single_prompt_strategy_executions",
    "single_prompt_strategy_results",
    "single_prompt_strategy_reviews",
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
    for table_name in _TABLES:
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=False)
    for table_name in ("single_prompt_strategy_results", "single_prompt_strategy_reviews"):
        _immutable_triggers(table_name)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(_TABLES):
        Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
