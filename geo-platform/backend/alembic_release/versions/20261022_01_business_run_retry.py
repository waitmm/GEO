"""Separate one business Run from its retry execution attempts."""

from alembic import op
import sqlalchemy as sa


revision = "20261022_01"
down_revision = "20261021_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "browser_monitor_run_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("attempt_id", sa.String(80), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="QUEUED"),
        sa.Column("previous_status", sa.String(40), nullable=False, server_default=""),
        sa.Column("previous_error_stage", sa.String(80), nullable=False, server_default=""),
        sa.Column("previous_error_type", sa.String(80), nullable=False, server_default=""),
        sa.Column("previous_error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("result_status", sa.String(40), nullable=False, server_default=""),
        sa.Column("result_error_stage", sa.String(80), nullable=False, server_default=""),
        sa.Column("result_error_type", sa.String(80), nullable=False, server_default=""),
        sa.Column("result_error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("answer_char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reference_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["browser_monitor_runs.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["browser_monitor_tasks.id"]),
        sa.UniqueConstraint("attempt_id", name="uq_browser_monitor_run_attempt_id_v2"),
        sa.UniqueConstraint("run_id", "attempt_no", name="uq_browser_monitor_run_attempt_no_v2"),
        sa.UniqueConstraint("run_id", "idempotency_key", name="uq_browser_monitor_run_attempt_key_v2"),
        sa.UniqueConstraint("task_id", name="uq_browser_monitor_run_attempt_task_v2"),
    )
    op.create_index("ix_browser_monitor_run_attempts_attempt_id", "browser_monitor_run_attempts", ["attempt_id"])
    op.create_index("ix_browser_monitor_run_attempts_run_id", "browser_monitor_run_attempts", ["run_id"])
    op.create_index("ix_browser_monitor_run_attempts_task_id", "browser_monitor_run_attempts", ["task_id"])
    op.create_index("ix_browser_monitor_run_attempts_status", "browser_monitor_run_attempts", ["status"])
    op.create_index("ix_browser_monitor_run_attempt_run", "browser_monitor_run_attempts", ["run_id", "attempt_no"])


def downgrade() -> None:
    op.drop_table("browser_monitor_run_attempts")
