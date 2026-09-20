"""Single-Prompt Core V2 third-slice strategy persistence."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260911_v2_strategy"
down_revision = "20260911_v2_diag"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "single_prompt_strategy_executions" not in _tables():
        op.create_table(
            "single_prompt_strategy_executions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("strategy_id", sa.String(80), nullable=False),
            sa.Column("analysis_id", sa.String(64), nullable=False),
            sa.Column("context_id", sa.String(80), nullable=False),
            sa.Column("diagnosis_id", sa.String(64), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("prompt_id", sa.Integer(), nullable=False),
            sa.Column("idempotency_key", sa.String(120), nullable=False),
            sa.Column("input_fingerprint", sa.String(64), nullable=False),
            sa.Column("diagnosis_result_version", sa.String(96), nullable=False),
            sa.Column("diagnosis_result_hash", sa.String(64), nullable=False),
            sa.Column("diagnosis_review_id", sa.String(80), nullable=False),
            sa.Column("review_snapshot_hash", sa.String(64), nullable=False),
            sa.Column("validation_contract_version", sa.String(120), nullable=False),
            sa.Column("input_snapshot_json", sa.Text(), nullable=False),
            sa.Column("input_snapshot_hash", sa.String(64), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("active_result_version", sa.String(96), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["analysis_id"], ["single_prompt_analyses.analysis_id"]),
            sa.ForeignKeyConstraint(["context_id"], ["single_prompt_analysis_contexts.context_id"]),
            sa.ForeignKeyConstraint(["diagnosis_id"], ["single_prompt_diagnosis_executions.diagnosis_id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["prompt_id"], ["prompts.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("strategy_id"),
            sa.UniqueConstraint("diagnosis_id", "idempotency_key", name="uq_single_prompt_strategy_idempotency"),
        )
        op.create_index("ix_single_prompt_strategy_diagnosis", "single_prompt_strategy_executions", ["diagnosis_id", "status"])
        op.create_index("ix_single_prompt_strategy_input", "single_prompt_strategy_executions", ["input_fingerprint"])

    if "single_prompt_strategy_results" not in _tables():
        op.create_table(
            "single_prompt_strategy_results",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("result_version", sa.String(96), nullable=False),
            sa.Column("strategy_id", sa.String(80), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("parent_result_version", sa.String(96), nullable=True),
            sa.Column("output_json", sa.Text(), nullable=False),
            sa.Column("output_hash", sa.String(64), nullable=False),
            sa.Column("reviewable_set_hash", sa.String(64), nullable=False),
            sa.Column("limitations_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["strategy_id"], ["single_prompt_strategy_executions.strategy_id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("result_version"),
            sa.UniqueConstraint("strategy_id", "version_number", name="uq_single_prompt_strategy_result_version"),
        )
        op.create_index("ix_single_prompt_strategy_result_strategy", "single_prompt_strategy_results", ["strategy_id", "version_number"])

    if "single_prompt_strategy_reviews" not in _tables():
        op.create_table(
            "single_prompt_strategy_reviews",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("review_id", sa.String(80), nullable=False),
            sa.Column("strategy_id", sa.String(80), nullable=False),
            sa.Column("result_version", sa.String(96), nullable=False),
            sa.Column("result_hash", sa.String(64), nullable=False),
            sa.Column("reviewable_set_hash", sa.String(64), nullable=False),
            sa.Column("decision", sa.String(40), nullable=False),
            sa.Column("reviewer", sa.String(120), nullable=False),
            sa.Column("note", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["strategy_id"], ["single_prompt_strategy_executions.strategy_id"]),
            sa.ForeignKeyConstraint(["result_version"], ["single_prompt_strategy_results.result_version"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("review_id"),
            sa.UniqueConstraint("result_version", name="uq_single_prompt_strategy_review_result"),
        )

    if op.get_bind().dialect.name == "sqlite":
        for table in ("single_prompt_strategy_results", "single_prompt_strategy_reviews"):
            op.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update
                BEFORE UPDATE ON {table}
                BEGIN
                  SELECT RAISE(ABORT, 'V2_STRATEGY_HISTORY_IMMUTABLE');
                END
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table}_no_delete
                BEFORE DELETE ON {table}
                BEGIN
                  SELECT RAISE(ABORT, 'V2_STRATEGY_HISTORY_IMMUTABLE');
                END
                """
            )


def downgrade() -> None:
    for table in (
        "single_prompt_strategy_reviews",
        "single_prompt_strategy_results",
        "single_prompt_strategy_executions",
    ):
        if table in _tables():
            op.drop_table(table)
