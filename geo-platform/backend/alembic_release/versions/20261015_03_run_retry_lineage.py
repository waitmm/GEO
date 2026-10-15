"""Add immutable physical-attempt lineage to browser monitor Runs."""

from alembic import op
import sqlalchemy as sa


revision = "20261015_03"
down_revision = "20261015_02"
branch_labels = None
depends_on = None


_LINEAGE_COLUMNS = {
    "logical_run_id": sa.Column("logical_run_id", sa.String(80), nullable=True),
    "attempt_id": sa.Column("attempt_id", sa.String(80), nullable=True),
    "attempt_no": sa.Column("attempt_no", sa.Integer(), nullable=True),
    "retry_of_run_id": sa.Column("retry_of_run_id", sa.Integer(), nullable=True),
    "retry_idempotency_key": sa.Column("retry_idempotency_key", sa.String(120), nullable=True),
}


def upgrade() -> None:
    # The first release revision creates allowlisted tables from ORM metadata.
    # A clean install may therefore already contain these columns, while an
    # existing release database will not.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("browser_monitor_runs")}
    for name, column in _LINEAGE_COLUMNS.items():
        if name not in columns:
            op.add_column("browser_monitor_runs", column)

    # retry_count cannot prove ancestry. Preserve each historical physical Run as
    # an independent logical root instead of inventing a lineage. Existing values
    # are authoritative and must never be rewritten by a resumed/replayed upgrade.
    op.execute("UPDATE browser_monitor_runs SET logical_run_id = 'legacy-logical-run-' || id WHERE logical_run_id IS NULL")
    op.execute("UPDATE browser_monitor_runs SET attempt_id = 'legacy-run-attempt-' || id WHERE attempt_id IS NULL")
    op.execute("UPDATE browser_monitor_runs SET attempt_no = 1 WHERE attempt_no IS NULL")

    inspector = sa.inspect(bind)
    reflected_columns = {
        column["name"]: column
        for column in inspector.get_columns("browser_monitor_runs")
    }
    missing_after_add = sorted(set(_LINEAGE_COLUMNS) - set(reflected_columns))
    if missing_after_add:
        raise RuntimeError(f"run lineage migration columns missing before constraints: {missing_after_add}")

    unique_sets = {
        tuple(constraint.get("column_names") or [])
        for constraint in inspector.get_unique_constraints("browser_monitor_runs")
    }
    foreign_key_sets = {
        tuple(foreign_key.get("constrained_columns") or [])
        for foreign_key in inspector.get_foreign_keys("browser_monitor_runs")
    }
    index_sets = {
        tuple(index.get("column_names") or [])
        for index in inspector.get_indexes("browser_monitor_runs")
    }
    nullable_columns = {
        name
        for name in ("logical_run_id", "attempt_id", "attempt_no")
        if reflected_columns[name].get("nullable", True)
    }
    missing_unique_constraints = {
        ("attempt_id",): "uq_browser_monitor_run_attempt_id",
        ("logical_run_id", "attempt_no"): "uq_browser_monitor_run_logical_attempt",
        ("logical_run_id", "retry_idempotency_key"): "uq_browser_monitor_run_retry_idempotency",
    }
    missing_unique_constraints = {
        columns: name
        for columns, name in missing_unique_constraints.items()
        if columns not in unique_sets
    }
    missing_foreign_key = ("retry_of_run_id",) not in foreign_key_sets
    missing_indexes = {
        ("logical_run_id",): "ix_browser_monitor_runs_logical_run_id",
        ("retry_of_run_id",): "ix_browser_monitor_runs_retry_of_run_id",
    }
    missing_indexes = {
        columns: name
        for columns, name in missing_indexes.items()
        if columns not in index_sets
    }
    needs_batch = bool(
        nullable_columns or missing_unique_constraints or missing_foreign_key or missing_indexes
    )

    if needs_batch:
        context = op.get_context()
        if bind.dialect.name == "sqlite":
            with context.autocommit_block():
                bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
                bind.exec_driver_sql("DROP TABLE IF EXISTS _alembic_tmp_browser_monitor_runs")
        with op.batch_alter_table("browser_monitor_runs") as batch:
            for name in sorted(nullable_columns):
                batch.alter_column(name, existing_type=_LINEAGE_COLUMNS[name].type, nullable=False)
            if missing_foreign_key:
                batch.create_foreign_key(
                    "fk_browser_monitor_runs_retry_of_run_id",
                    "browser_monitor_runs",
                    ["retry_of_run_id"],
                    ["id"],
                )
            for columns, name in missing_unique_constraints.items():
                batch.create_unique_constraint(name, list(columns))
            for columns, name in missing_indexes.items():
                batch.create_index(name, list(columns))
        if bind.dialect.name == "sqlite":
            violations = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"run lineage migration introduced foreign-key violations: {violations[:10]}")
            with context.autocommit_block():
                bind.exec_driver_sql("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    context = op.get_context()
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with context.autocommit_block():
            bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
            bind.exec_driver_sql("DROP TABLE IF EXISTS _alembic_tmp_browser_monitor_runs")
    with op.batch_alter_table("browser_monitor_runs") as batch:
        batch.drop_index("ix_browser_monitor_runs_retry_of_run_id")
        batch.drop_index("ix_browser_monitor_runs_logical_run_id")
        batch.drop_constraint("uq_browser_monitor_run_retry_idempotency", type_="unique")
        batch.drop_constraint("uq_browser_monitor_run_logical_attempt", type_="unique")
        batch.drop_constraint("uq_browser_monitor_run_attempt_id", type_="unique")
        batch.drop_constraint("fk_browser_monitor_runs_retry_of_run_id", type_="foreignkey")
        batch.drop_column("retry_idempotency_key")
        batch.drop_column("retry_of_run_id")
        batch.drop_column("attempt_no")
        batch.drop_column("attempt_id")
        batch.drop_column("logical_run_id")
    if bind.dialect.name == "sqlite":
        violations = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"run lineage downgrade introduced foreign-key violations: {violations[:10]}")
        with context.autocommit_block():
            bind.exec_driver_sql("PRAGMA foreign_keys=ON")
