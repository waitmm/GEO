"""Single-Prompt Core V2 fifth-slice retest and comparison."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260911_v2_retest"
down_revision = "20260911_v2_execution"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "single_prompt_retest_executions" not in _tables():
        op.create_table(
            "single_prompt_retest_executions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("retest_id", sa.String(80), nullable=False),
            sa.Column("confirmation_id", sa.String(80), nullable=False),
            sa.Column("publication_id", sa.String(80), nullable=False),
            sa.Column("proposal_id", sa.String(80), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("prompt_id", sa.Integer(), nullable=False),
            sa.Column("baseline_analysis_id", sa.String(64), nullable=False),
            sa.Column("baseline_context_id", sa.String(80), nullable=False),
            sa.Column("retest_analysis_id", sa.String(64), nullable=False),
            sa.Column("idempotency_key", sa.String(120), nullable=False),
            sa.Column("input_fingerprint", sa.String(64), nullable=False),
            sa.Column("confirmation_snapshot_hash", sa.String(64), nullable=False),
            sa.Column("publication_report_hash", sa.String(64), nullable=False),
            sa.Column("baseline_snapshot_json", sa.Text(), nullable=False),
            sa.Column("baseline_snapshot_hash", sa.String(64), nullable=False),
            sa.Column("retest_plan_json", sa.Text(), nullable=False),
            sa.Column("retest_plan_hash", sa.String(64), nullable=False),
            sa.Column("measurement_identity_json", sa.Text(), nullable=False),
            sa.Column("measurement_identity_hash", sa.String(64), nullable=False),
            sa.Column("measurement_contract_json", sa.Text(), nullable=False),
            sa.Column("measurement_contract_hash", sa.String(64), nullable=False),
            sa.Column("planned_conditions_json", sa.Text(), nullable=False),
            sa.Column("observed_conditions_json", sa.Text(), nullable=False),
            sa.Column("unobservable_conditions_json", sa.Text(), nullable=False),
            sa.Column("authorization_json", sa.Text(), nullable=False),
            sa.Column("semantic_result_json", sa.Text(), nullable=False),
            sa.Column("semantic_result_hash", sa.String(64), nullable=False),
            sa.Column("semantic_history_json", sa.Text(), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("blocker_code", sa.String(100), nullable=False),
            sa.Column("blocker_detail", sa.Text(), nullable=False),
            sa.Column("active_comparison_version", sa.String(96), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["confirmation_id"], ["single_prompt_execution_confirmations.confirmation_id"]),
            sa.ForeignKeyConstraint(["publication_id"], ["single_prompt_publication_records.publication_id"]),
            sa.ForeignKeyConstraint(["proposal_id"], ["single_prompt_execution_proposals.proposal_id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["prompt_id"], ["prompts.id"]),
            sa.ForeignKeyConstraint(["baseline_analysis_id"], ["single_prompt_analyses.analysis_id"]),
            sa.ForeignKeyConstraint(["baseline_context_id"], ["single_prompt_analysis_contexts.context_id"]),
            sa.ForeignKeyConstraint(["retest_analysis_id"], ["single_prompt_analyses.analysis_id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("retest_id"),
            sa.UniqueConstraint("retest_analysis_id"),
            sa.UniqueConstraint("publication_id", "idempotency_key", name="uq_single_prompt_retest_idempotency"),
        )
        op.create_index("ix_single_prompt_retest_publication", "single_prompt_retest_executions", ["publication_id", "status"])
        op.create_index("ix_single_prompt_retest_input", "single_prompt_retest_executions", ["input_fingerprint"])

    if "single_prompt_comparison_results" not in _tables():
        op.create_table(
            "single_prompt_comparison_results",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("result_version", sa.String(96), nullable=False),
            sa.Column("retest_id", sa.String(80), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("input_hash", sa.String(64), nullable=False),
            sa.Column("baseline_context_id", sa.String(80), nullable=False),
            sa.Column("retest_context_id", sa.String(80), nullable=False),
            sa.Column("baseline_measurement_json", sa.Text(), nullable=False),
            sa.Column("retest_measurement_json", sa.Text(), nullable=False),
            sa.Column("comparison_json", sa.Text(), nullable=False),
            sa.Column("output_hash", sa.String(64), nullable=False),
            sa.Column("limitations_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["retest_id"], ["single_prompt_retest_executions.retest_id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("result_version"),
            sa.UniqueConstraint("retest_id", "version_number", name="uq_single_prompt_comparison_version"),
            sa.UniqueConstraint("retest_id", "input_hash", name="uq_single_prompt_comparison_input"),
        )
        op.create_index("ix_single_prompt_comparison_retest", "single_prompt_comparison_results", ["retest_id", "version_number"])

    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_single_prompt_comparison_results_no_update
            BEFORE UPDATE ON single_prompt_comparison_results
            BEGIN
              SELECT RAISE(ABORT, 'V2_COMPARISON_HISTORY_IMMUTABLE');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_single_prompt_comparison_results_no_delete
            BEFORE DELETE ON single_prompt_comparison_results
            BEGIN
              SELECT RAISE(ABORT, 'V2_COMPARISON_HISTORY_IMMUTABLE');
            END
            """
        )


def downgrade() -> None:
    for table in ("single_prompt_comparison_results", "single_prompt_retest_executions"):
        if table in _tables():
            op.drop_table(table)
