"""Add experiment environment audit fields."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260813_01"
down_revision = "20260812_03"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if table in _tables() and column.name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    _add_column_if_missing("optimization_experiments", sa.Column("known_environment_audit_json", sa.Text(), nullable=False, server_default="{}"))
    _add_column_if_missing("optimization_experiments", sa.Column("comparability_status", sa.String(40), nullable=False, server_default="INSUFFICIENT_CONTEXT"))
    _add_column_if_missing("optimization_experiments", sa.Column("comparability_note", sa.Text(), nullable=False, server_default=""))
    _add_column_if_missing("optimization_experiments", sa.Column("controlled_intervention_json", sa.Text(), nullable=False, server_default="{}"))
    if "optimization_experiments" in _tables():
        try:
            op.create_index("ix_optimization_experiments_comparability_status", "optimization_experiments", ["comparability_status"])
        except Exception:
            pass


def downgrade() -> None:
    # SQLite development databases do not reliably support dropping columns.
    pass
