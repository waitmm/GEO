"""Single-Prompt Core V2 control plane and immutable raw context.

This is an intentional branch from the last production migration. It does not
depend on the separately gated Runtime persistence artifact.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260910_v2"
down_revision = "20260819_01"
branch_labels = ("single_prompt_core_v2",)
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "single_prompt_analyses" not in _tables():
        op.create_table(
            "single_prompt_analyses",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("analysis_id", sa.String(64), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("prompt_id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("idempotency_key", sa.String(120), nullable=False),
            sa.Column("prompt_text_snapshot", sa.Text(), nullable=False),
            sa.Column("sampling_plan_json", sa.Text(), nullable=False),
            sa.Column("sampling_plan_hash", sa.String(64), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("blocker_code", sa.String(80), nullable=False),
            sa.Column("blocker_detail", sa.Text(), nullable=False),
            sa.Column("retry_history_json", sa.Text(), nullable=False),
            sa.Column("active_attempt_token", sa.String(64), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["prompt_id"], ["prompts.id"]),
            sa.ForeignKeyConstraint(["task_id"], ["browser_monitor_tasks.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("analysis_id"),
            sa.UniqueConstraint("task_id"),
            sa.UniqueConstraint("project_id", "idempotency_key", name="uq_single_prompt_analysis_idempotency"),
        )
        op.create_index("ix_single_prompt_analyses_analysis_id", "single_prompt_analyses", ["analysis_id"])
        op.create_index("ix_single_prompt_analyses_project_id", "single_prompt_analyses", ["project_id"])
        op.create_index("ix_single_prompt_analyses_prompt_id", "single_prompt_analyses", ["prompt_id"])
        op.create_index("ix_single_prompt_analyses_status", "single_prompt_analyses", ["status"])

    if "single_prompt_analysis_contexts" not in _tables():
        op.create_table(
            "single_prompt_analysis_contexts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("context_id", sa.String(80), nullable=False),
            sa.Column("analysis_id", sa.String(64), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("prompt_id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("result_version", sa.String(96), nullable=False),
            sa.Column("run_scope_json", sa.Text(), nullable=False),
            sa.Column("run_scope_hash", sa.String(64), nullable=False),
            sa.Column("raw_output_json", sa.Text(), nullable=False),
            sa.Column("raw_output_hash", sa.String(64), nullable=False),
            sa.Column("valid_run_count", sa.Integer(), nullable=False),
            sa.Column("failed_run_count", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["analysis_id"], ["single_prompt_analyses.analysis_id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["prompt_id"], ["prompts.id"]),
            sa.ForeignKeyConstraint(["task_id"], ["browser_monitor_tasks.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("analysis_id"),
            sa.UniqueConstraint("context_id"),
            sa.UniqueConstraint("result_version"),
            sa.UniqueConstraint("task_id"),
        )
        op.create_index("ix_single_prompt_contexts_context_id", "single_prompt_analysis_contexts", ["context_id"])
        op.create_index("ix_single_prompt_contexts_analysis_id", "single_prompt_analysis_contexts", ["analysis_id"])

    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_single_prompt_context_no_update
            BEFORE UPDATE ON single_prompt_analysis_contexts
            BEGIN
              SELECT RAISE(ABORT, 'ANALYSIS_CONTEXT_IMMUTABLE');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_single_prompt_context_no_delete
            BEFORE DELETE ON single_prompt_analysis_contexts
            BEGIN
              SELECT RAISE(ABORT, 'ANALYSIS_CONTEXT_IMMUTABLE');
            END
            """
        )


def downgrade() -> None:
    if "single_prompt_analysis_contexts" in _tables():
        op.drop_table("single_prompt_analysis_contexts")
    if "single_prompt_analyses" in _tables():
        op.drop_table("single_prompt_analyses")
