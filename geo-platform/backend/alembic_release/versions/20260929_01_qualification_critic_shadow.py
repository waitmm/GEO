"""Add the bounded Model B qualification critic shadow chain.

Revision ID: 20260929_01
Revises: 20260928_01
Create Date: 2026-09-29
"""

from __future__ import annotations

from alembic import op

from app.models import Base


revision = "20260929_01"
down_revision = "20260928_01"
branch_labels = None
depends_on = None


_TABLES = (
    "single_prompt_qualification_critic_executions",
    "single_prompt_qualification_critic_results",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in _TABLES:
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=False)
    op.execute(
        """
        CREATE TRIGGER trg_single_prompt_qualification_critic_results_no_update
        BEFORE UPDATE ON single_prompt_qualification_critic_results
        BEGIN
          SELECT RAISE(ABORT, 'RELEASE_HISTORY_IMMUTABLE');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_single_prompt_qualification_critic_results_no_delete
        BEFORE DELETE ON single_prompt_qualification_critic_results
        BEGIN
          SELECT RAISE(ABORT, 'RELEASE_HISTORY_IMMUTABLE');
        END
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(_TABLES):
        Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
