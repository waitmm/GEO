"""Preserve exact transport provenance without rewriting historical snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "20261009_04"
down_revision = "20261009_03"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("single_prompt_prepared_source_snapshots", sa.Column(
        "acquisition_receipt_json", sa.Text(), nullable=False, server_default="{}"))


def downgrade():
    op.drop_column("single_prompt_prepared_source_snapshots", "acquisition_receipt_json")
