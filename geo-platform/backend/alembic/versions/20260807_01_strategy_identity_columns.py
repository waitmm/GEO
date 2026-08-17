from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260807_01"
down_revision = "20260806_01"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if table_name in _tables() and column.name not in _columns(table_name):
        op.add_column(table_name, column)


def upgrade() -> None:
    """Add formal strategy identity columns to optimization_strategy_candidates (P0-3)."""
    if "optimization_strategy_candidates" in _tables():
        _add_column_if_missing("optimization_strategy_candidates",
            sa.Column("intervention_type", sa.String(length=80), nullable=True))
        _add_column_if_missing("optimization_strategy_candidates",
            sa.Column("target_platform", sa.String(length=160), nullable=True))
        _add_column_if_missing("optimization_strategy_candidates",
            sa.Column("target_asset", sa.String(length=500), nullable=True))
        _add_column_if_missing("optimization_strategy_candidates",
            sa.Column("target_content_type", sa.String(length=80), nullable=True))
        _add_column_if_missing("optimization_strategy_candidates",
            sa.Column("expected_primary_metric", sa.String(length=120), nullable=True))
        source_package_column = (
            sa.Column("source_package_id", sa.Integer(), nullable=True)
            if op.get_bind().dialect.name == "sqlite"
            else sa.Column("source_package_id", sa.Integer(), sa.ForeignKey("optimization_evidence_packages.id", ondelete="SET NULL"), nullable=True)
        )
        _add_column_if_missing("optimization_strategy_candidates", source_package_column)

    # Create indexes for new columns
    # Note: SQLite ALTER TABLE ADD COLUMN does not create FK constraints on
    # existing tables. New databases created via Base.metadata.create_all()
    # get the full FK constraint. For existing databases, database.py enables
    # PRAGMA foreign_keys=ON so the FK is enforced at the SQLite engine level.
    op.execute("CREATE INDEX IF NOT EXISTS ix_strategy_candidates_intervention_type ON optimization_strategy_candidates (intervention_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_strategy_candidates_target_platform ON optimization_strategy_candidates (target_platform)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_strategy_candidates_source_package_id ON optimization_strategy_candidates (source_package_id)")


def downgrade() -> None:
    """Remove formal strategy identity columns."""
    if "optimization_strategy_candidates" in _tables():
        cols = _columns("optimization_strategy_candidates")
        for col_name in ["intervention_type", "target_platform", "target_asset",
                         "target_content_type", "expected_primary_metric", "source_package_id"]:
            if col_name in cols:
                op.drop_column("optimization_strategy_candidates", col_name)
