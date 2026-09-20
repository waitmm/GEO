"""Single-Prompt Core V2 fourth-slice execution and publication records."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260911_v2_execution"
down_revision = "20260911_v2_strategy"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "single_prompt_execution_proposals" not in _tables():
        op.create_table(
            "single_prompt_execution_proposals",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("proposal_id", sa.String(80), nullable=False),
            sa.Column("strategy_id", sa.String(80), nullable=False),
            sa.Column("analysis_id", sa.String(64), nullable=False),
            sa.Column("context_id", sa.String(80), nullable=False),
            sa.Column("diagnosis_id", sa.String(64), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("prompt_id", sa.Integer(), nullable=False),
            sa.Column("direction_id", sa.String(96), nullable=False),
            sa.Column("idempotency_key", sa.String(120), nullable=False),
            sa.Column("input_fingerprint", sa.String(64), nullable=False),
            sa.Column("strategy_result_version", sa.String(96), nullable=False),
            sa.Column("strategy_result_hash", sa.String(64), nullable=False),
            sa.Column("strategy_review_id", sa.String(80), nullable=False),
            sa.Column("strategy_review_snapshot_hash", sa.String(64), nullable=False),
            sa.Column("validation_contract_version", sa.String(120), nullable=False),
            sa.Column("input_snapshot_json", sa.Text(), nullable=False),
            sa.Column("input_snapshot_hash", sa.String(64), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("active_result_version", sa.String(96), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["strategy_id"], ["single_prompt_strategy_executions.strategy_id"]),
            sa.ForeignKeyConstraint(["analysis_id"], ["single_prompt_analyses.analysis_id"]),
            sa.ForeignKeyConstraint(["context_id"], ["single_prompt_analysis_contexts.context_id"]),
            sa.ForeignKeyConstraint(["diagnosis_id"], ["single_prompt_diagnosis_executions.diagnosis_id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["prompt_id"], ["prompts.id"]),
            sa.ForeignKeyConstraint(["strategy_result_version"], ["single_prompt_strategy_results.result_version"]),
            sa.ForeignKeyConstraint(["strategy_review_id"], ["single_prompt_strategy_reviews.review_id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("proposal_id"),
            sa.UniqueConstraint("strategy_id", "idempotency_key", name="uq_single_prompt_execution_proposal_idempotency"),
        )
        op.create_index("ix_single_prompt_execution_proposal_strategy", "single_prompt_execution_proposals", ["strategy_id", "status"])
        op.create_index("ix_single_prompt_execution_proposal_input", "single_prompt_execution_proposals", ["input_fingerprint"])

    if "single_prompt_execution_proposal_results" not in _tables():
        op.create_table(
            "single_prompt_execution_proposal_results",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("result_version", sa.String(96), nullable=False),
            sa.Column("proposal_id", sa.String(80), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("parent_result_version", sa.String(96), nullable=True),
            sa.Column("output_json", sa.Text(), nullable=False),
            sa.Column("output_hash", sa.String(64), nullable=False),
            sa.Column("reviewable_set_hash", sa.String(64), nullable=False),
            sa.Column("limitations_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["proposal_id"], ["single_prompt_execution_proposals.proposal_id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("result_version"),
            sa.UniqueConstraint("proposal_id", "version_number", name="uq_single_prompt_execution_proposal_result_version"),
        )
        op.create_index("ix_single_prompt_execution_proposal_result", "single_prompt_execution_proposal_results", ["proposal_id", "version_number"])

    if "single_prompt_execution_confirmations" not in _tables():
        op.create_table(
            "single_prompt_execution_confirmations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("confirmation_id", sa.String(80), nullable=False),
            sa.Column("proposal_id", sa.String(80), nullable=False),
            sa.Column("result_version", sa.String(96), nullable=False),
            sa.Column("result_hash", sa.String(64), nullable=False),
            sa.Column("reviewable_set_hash", sa.String(64), nullable=False),
            sa.Column("input_snapshot_hash", sa.String(64), nullable=False),
            sa.Column("idempotency_key", sa.String(120), nullable=False),
            sa.Column("confirmation_snapshot_json", sa.Text(), nullable=False),
            sa.Column("confirmation_snapshot_hash", sa.String(64), nullable=False),
            sa.Column("confirmer", sa.String(120), nullable=False),
            sa.Column("note", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["proposal_id"], ["single_prompt_execution_proposals.proposal_id"]),
            sa.ForeignKeyConstraint(["result_version"], ["single_prompt_execution_proposal_results.result_version"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("confirmation_id"),
            sa.UniqueConstraint("result_version", name="uq_single_prompt_execution_confirmation_result"),
            sa.UniqueConstraint("proposal_id", "idempotency_key", name="uq_single_prompt_execution_confirmation_idempotency"),
        )

    if "single_prompt_publication_records" not in _tables():
        op.create_table(
            "single_prompt_publication_records",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("publication_id", sa.String(80), nullable=False),
            sa.Column("confirmation_id", sa.String(80), nullable=False),
            sa.Column("proposal_id", sa.String(80), nullable=False),
            sa.Column("prior_publication_id", sa.String(80), nullable=True),
            sa.Column("revision_number", sa.Integer(), nullable=False),
            sa.Column("idempotency_key", sa.String(120), nullable=False),
            sa.Column("publication_status", sa.String(40), nullable=False),
            sa.Column("conformance", sa.String(40), nullable=False),
            sa.Column("report_json", sa.Text(), nullable=False),
            sa.Column("report_hash", sa.String(64), nullable=False),
            sa.Column("conformance_json", sa.Text(), nullable=False),
            sa.Column("recorder", sa.String(120), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["confirmation_id"], ["single_prompt_execution_confirmations.confirmation_id"]),
            sa.ForeignKeyConstraint(["proposal_id"], ["single_prompt_execution_proposals.proposal_id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("publication_id"),
            sa.UniqueConstraint("confirmation_id", "idempotency_key", name="uq_single_prompt_publication_idempotency"),
        )
        op.create_index("ix_single_prompt_publication_confirmation", "single_prompt_publication_records", ["confirmation_id", "created_at"])

    if op.get_bind().dialect.name == "sqlite":
        for table in (
            "single_prompt_execution_proposal_results",
            "single_prompt_execution_confirmations",
            "single_prompt_publication_records",
        ):
            op.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update
                BEFORE UPDATE ON {table}
                BEGIN
                  SELECT RAISE(ABORT, 'V2_EXECUTION_HISTORY_IMMUTABLE');
                END
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table}_no_delete
                BEFORE DELETE ON {table}
                BEGIN
                  SELECT RAISE(ABORT, 'V2_EXECUTION_HISTORY_IMMUTABLE');
                END
                """
            )


def downgrade() -> None:
    for table in (
        "single_prompt_publication_records",
        "single_prompt_execution_confirmations",
        "single_prompt_execution_proposal_results",
        "single_prompt_execution_proposals",
    ):
        if table in _tables():
            op.drop_table(table)
