"""Add the collector-owned brand mention output to the release schema.

Revision ID: 20260920_02
Revises: 20260920_01
Create Date: 2026-09-20
"""

from __future__ import annotations

from alembic import op

from app.models import Base


revision = "20260920_02"
down_revision = "20260920_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.tables["brand_mentions"].create(bind=op.get_bind(), checkfirst=False)


def downgrade() -> None:
    Base.metadata.tables["brand_mentions"].drop(bind=op.get_bind(), checkfirst=True)
