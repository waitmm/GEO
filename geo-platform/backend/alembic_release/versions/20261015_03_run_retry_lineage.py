"""Add immutable physical-attempt lineage to browser monitor Runs."""

from alembic import op
import sqlalchemy as sa


revision = "20261015_03"
down_revision = "20261015_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The first release revision creates allowlisted tables from ORM metadata.
    # A clean install may therefore already contain these columns, while an
    # existing release database will not.
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("browser_monitor_runs")}
    added_columns = "logical_run_id" not in columns
    if added_columns:
        op.add_column("browser_monitor_runs", sa.Column("logical_run_id", sa.String(80), nullable=True))
        op.add_column("browser_monitor_runs", sa.Column("attempt_id", sa.String(80), nullable=True))
        op.add_column(
            "browser_monitor_runs",
            sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        )
        op.add_column("browser_monitor_runs", sa.Column("retry_of_run_id", sa.Integer(), nullable=True))
        op.add_column(
            "browser_monitor_runs",
            sa.Column("retry_idempotency_key", sa.String(120), nullable=True),
        )

    # retry_count cannot prove ancestry. Preserve each historical physical Run as
    # an independent logical root instead of inventing a lineage.
    op.execute(
        """
        UPDATE browser_monitor_runs
        SET logical_run_id = 'legacy-logical-run-' || id,
            attempt_id = 'legacy-run-attempt-' || id,
            attempt_no = 1,
            retry_of_run_id = NULL,
            retry_idempotency_key = NULL
        """
    )

    if added_columns:
        context = op.get_context()
        bind = op.get_bind()
        if bind.dialect.name == "sqlite":
            with context.autocommit_block():
                bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
                bind.exec_driver_sql("DROP TABLE IF EXISTS _alembic_tmp_browser_monitor_runs")
        with op.batch_alter_table("browser_monitor_runs") as batch:
            batch.alter_column("logical_run_id", existing_type=sa.String(80), nullable=False)
            batch.alter_column("attempt_id", existing_type=sa.String(80), nullable=False)
            batch.create_foreign_key(
                "fk_browser_monitor_runs_retry_of_run_id",
                "browser_monitor_runs",
                ["retry_of_run_id"],
                ["id"],
            )
            batch.create_unique_constraint("uq_browser_monitor_run_attempt_id", ["attempt_id"])
            batch.create_unique_constraint(
                "uq_browser_monitor_run_logical_attempt", ["logical_run_id", "attempt_no"]
            )
            batch.create_unique_constraint(
                "uq_browser_monitor_run_retry_idempotency",
                ["logical_run_id", "retry_idempotency_key"],
            )
            batch.create_index("ix_browser_monitor_runs_logical_run_id", ["logical_run_id"])
            batch.create_index("ix_browser_monitor_runs_retry_of_run_id", ["retry_of_run_id"])
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
