"""Add append-only Model B Critic Human Gold reviews.

Revision ID: 20260929_02
Revises: 20260929_01
Create Date: 2026-09-29
"""

from __future__ import annotations

from alembic import op

from app.models import Base


revision = "20260929_02"
down_revision = "20260929_01"
branch_labels = None
depends_on = None


_TABLE = "single_prompt_qualification_critic_gold_reviews"


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables[_TABLE].create(bind=bind, checkfirst=False)
    op.execute(
        """
        CREATE TRIGGER trg_single_prompt_qualification_critic_gold_reviews_no_update
        BEFORE UPDATE ON single_prompt_qualification_critic_gold_reviews
        BEGIN
          SELECT RAISE(ABORT, 'RELEASE_HISTORY_IMMUTABLE');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_single_prompt_qualification_critic_gold_reviews_no_delete
        BEFORE DELETE ON single_prompt_qualification_critic_gold_reviews
        BEGIN
          SELECT RAISE(ABORT, 'RELEASE_HISTORY_IMMUTABLE');
        END
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables[_TABLE].drop(bind=bind, checkfirst=True)
