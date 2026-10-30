"""Add recoverable execution audit to draft artifact regenerations."""

from alembic import op
import sqlalchemy as sa


revision = "20261030_02"
down_revision = "20261030_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "agent_draft_artifact_regenerations"
    # SQLite supports these additive columns directly. Avoid batch table-copy:
    # the existing identity/append-only triggers must remain attached intact.
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
    columns = (
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("audit_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("cancel_requested_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    for column in columns:
        if column.name not in existing:
            op.add_column(table, column)


def downgrade() -> None:
    table = "agent_draft_artifact_regenerations"
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
    for name in (
        "updated_at", "finished_at", "started_at", "cancel_requested_at",
        "audit_json", "usage_json", "attempt_count",
    ):
        if name in existing:
            op.drop_column(table, name)
