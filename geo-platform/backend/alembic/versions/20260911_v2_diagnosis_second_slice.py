"""Single-Prompt Core V2 second-slice diagnosis persistence.

The revision extends only the isolated V2 migration branch. It does not depend
on or activate the gated Runtime persistence branch.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260911_v2_diag"
down_revision = "20260910_v2"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    if "single_prompt_diagnosis_executions" not in _tables():
        op.create_table(
            "single_prompt_diagnosis_executions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("diagnosis_id", sa.String(64), nullable=False),
            sa.Column("analysis_id", sa.String(64), nullable=False),
            sa.Column("context_id", sa.String(80), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("prompt_id", sa.Integer(), nullable=False),
            sa.Column("idempotency_key", sa.String(120), nullable=False),
            sa.Column("input_fingerprint", sa.String(64), nullable=False),
            sa.Column("raw_output_hash", sa.String(64), nullable=False),
            sa.Column("brand_snapshot_json", sa.Text(), nullable=False),
            sa.Column("brand_snapshot_hash", sa.String(64), nullable=False),
            sa.Column("truth_snapshot_json", sa.Text(), nullable=False),
            sa.Column("truth_set_hash", sa.String(64), nullable=False),
            sa.Column("contract_config_json", sa.Text(), nullable=False),
            sa.Column("contract_config_hash", sa.String(64), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("progress_json", sa.Text(), nullable=False),
            sa.Column("blocker_code", sa.String(80), nullable=False),
            sa.Column("blocker_detail", sa.Text(), nullable=False),
            sa.Column("active_attempt_token", sa.String(64), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("external_llm_calls", sa.Integer(), nullable=False),
            sa.Column("llm_cache_hits", sa.Integer(), nullable=False),
            sa.Column("external_token_usage", sa.Integer(), nullable=False),
            sa.Column("active_result_version", sa.String(96), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["analysis_id"], ["single_prompt_analyses.analysis_id"]),
            sa.ForeignKeyConstraint(["context_id"], ["single_prompt_analysis_contexts.context_id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["prompt_id"], ["prompts.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("analysis_id", "idempotency_key", name="uq_single_prompt_diagnosis_idempotency"),
            sa.UniqueConstraint("diagnosis_id"),
        )
        op.create_index("ix_single_prompt_diagnosis_analysis", "single_prompt_diagnosis_executions", ["analysis_id", "status"])
        op.create_index("ix_single_prompt_diagnosis_context", "single_prompt_diagnosis_executions", ["context_id"])
        op.create_index("ix_single_prompt_diagnosis_input", "single_prompt_diagnosis_executions", ["input_fingerprint"])

    if "single_prompt_source_snapshots" not in _tables():
        op.create_table(
            "single_prompt_source_snapshots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("snapshot_id", sa.String(80), nullable=False),
            sa.Column("diagnosis_id", sa.String(64), nullable=False),
            sa.Column("source_key", sa.String(64), nullable=False),
            sa.Column("canonical_url", sa.String(1200), nullable=False),
            sa.Column("original_urls_json", sa.Text(), nullable=False),
            sa.Column("reference_observations_json", sa.Text(), nullable=False),
            sa.Column("occurrence_count", sa.Integer(), nullable=False),
            sa.Column("fetch_status", sa.String(40), nullable=False),
            sa.Column("failure_reason", sa.Text(), nullable=False),
            sa.Column("fetched_at", sa.DateTime(), nullable=True),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("clean_text", sa.Text(), nullable=False),
            sa.Column("passages_json", sa.Text(), nullable=False),
            sa.Column("passages_hash", sa.String(64), nullable=False),
            sa.Column("parser_version", sa.String(80), nullable=False),
            sa.Column("fetch_source", sa.String(40), nullable=False),
            sa.Column("reused_from_snapshot_id", sa.String(80), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["diagnosis_id"], ["single_prompt_diagnosis_executions.diagnosis_id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("diagnosis_id", "source_key", name="uq_single_prompt_source_snapshot_key"),
            sa.UniqueConstraint("snapshot_id"),
        )
        op.create_index("ix_single_prompt_source_snapshot_diagnosis", "single_prompt_source_snapshots", ["diagnosis_id", "fetch_status"])
    elif "reused_from_snapshot_id" not in _columns("single_prompt_source_snapshots"):
        op.add_column(
            "single_prompt_source_snapshots",
            sa.Column("reused_from_snapshot_id", sa.String(80), nullable=True),
        )

    if "single_prompt_diagnosis_results" not in _tables():
        op.create_table(
            "single_prompt_diagnosis_results",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("result_version", sa.String(96), nullable=False),
            sa.Column("diagnosis_id", sa.String(64), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("parent_result_version", sa.String(96), nullable=True),
            sa.Column("output_json", sa.Text(), nullable=False),
            sa.Column("output_hash", sa.String(64), nullable=False),
            sa.Column("reviewable_set_hash", sa.String(64), nullable=False),
            sa.Column("limitations_json", sa.Text(), nullable=False),
            sa.Column("stats_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["diagnosis_id"], ["single_prompt_diagnosis_executions.diagnosis_id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("diagnosis_id", "version_number", name="uq_single_prompt_diagnosis_result_version"),
            sa.UniqueConstraint("result_version"),
        )
        op.create_index("ix_single_prompt_diagnosis_result_diagnosis", "single_prompt_diagnosis_results", ["diagnosis_id", "version_number"])

    if "single_prompt_diagnosis_reviews" not in _tables():
        op.create_table(
            "single_prompt_diagnosis_reviews",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("review_id", sa.String(80), nullable=False),
            sa.Column("diagnosis_id", sa.String(64), nullable=False),
            sa.Column("result_version", sa.String(96), nullable=False),
            sa.Column("result_hash", sa.String(64), nullable=False),
            sa.Column("reviewable_set_hash", sa.String(64), nullable=False),
            sa.Column("prior_review_id", sa.String(80), nullable=True),
            sa.Column("decision", sa.String(40), nullable=False),
            sa.Column("decisions_json", sa.Text(), nullable=False),
            sa.Column("reviewer", sa.String(120), nullable=False),
            sa.Column("note", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["diagnosis_id"], ["single_prompt_diagnosis_executions.diagnosis_id"]),
            sa.ForeignKeyConstraint(["result_version"], ["single_prompt_diagnosis_results.result_version"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("result_version", name="uq_single_prompt_diagnosis_review_result"),
            sa.UniqueConstraint("review_id"),
        )

    if op.get_bind().dialect.name == "sqlite":
        for table in (
            "single_prompt_source_snapshots",
            "single_prompt_diagnosis_results",
            "single_prompt_diagnosis_reviews",
        ):
            op.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update
                BEFORE UPDATE ON {table}
                BEGIN
                  SELECT RAISE(ABORT, 'V2_DIAGNOSIS_HISTORY_IMMUTABLE');
                END
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table}_no_delete
                BEFORE DELETE ON {table}
                BEGIN
                  SELECT RAISE(ABORT, 'V2_DIAGNOSIS_HISTORY_IMMUTABLE');
                END
                """
            )


def downgrade() -> None:
    for table in (
        "single_prompt_diagnosis_reviews",
        "single_prompt_diagnosis_results",
        "single_prompt_source_snapshots",
        "single_prompt_diagnosis_executions",
    ):
        if table in _tables():
            op.drop_table(table)
