"""Add answer semantic facts and product truth."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260812_03"
down_revision = "20260812_02"
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
    tables = _tables()

    _add_column_if_missing("recommendation_entities", sa.Column("entity_role", sa.String(80), nullable=False, server_default="BRAND"))
    _add_column_if_missing("recommendation_entities", sa.Column("is_choice_candidate", sa.Boolean(), nullable=False, server_default=sa.false()))

    _add_column_if_missing("recommendation_claims", sa.Column("recommendation_span", sa.Text(), nullable=False, server_default=""))
    _add_column_if_missing("recommendation_claims", sa.Column("start_offset", sa.Integer(), nullable=False, server_default="-1"))
    _add_column_if_missing("recommendation_claims", sa.Column("end_offset", sa.Integer(), nullable=False, server_default="-1"))
    _add_column_if_missing("recommendation_claims", sa.Column("recommendation_strength", sa.String(40), nullable=False, server_default="UNKNOWN"))
    _add_column_if_missing("recommendation_claims", sa.Column("is_choice_candidate", sa.Boolean(), nullable=False, server_default=sa.false()))

    _add_column_if_missing("recommendation_reason_claims", sa.Column("reason_span", sa.Text(), nullable=False, server_default=""))
    _add_column_if_missing("recommendation_reason_claims", sa.Column("start_offset", sa.Integer(), nullable=False, server_default="-1"))
    _add_column_if_missing("recommendation_reason_claims", sa.Column("end_offset", sa.Integer(), nullable=False, server_default="-1"))
    _add_column_if_missing("recommendation_reason_claims", sa.Column("extractor", sa.String(80), nullable=False, server_default="RULE_DERIVED"))
    _add_column_if_missing("recommendation_reason_claims", sa.Column("extractor_version", sa.String(80), nullable=False, server_default="recommendation_reason.v1_rule_zh"))
    _add_column_if_missing("recommendation_reason_claims", sa.Column("review_status", sa.String(40), nullable=False, server_default="UNREVIEWED"))
    _add_column_if_missing("recommendation_reason_claims", sa.Column("human_labels_json", sa.Text(), nullable=False, server_default="{}"))

    _add_column_if_missing("decision_evidence_adoptions", sa.Column("evidence_status", sa.String(40), nullable=False, server_default="UNCERTAIN"))

    if "answer_semantic_facts" not in tables:
        op.create_table(
            "answer_semantic_facts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("recommendation_intelligence_snapshots.id", ondelete="SET NULL"), nullable=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("prompt_id", sa.Integer(), sa.ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("browser_monitor_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("fact_type", sa.String(80), nullable=False),
            sa.Column("fact_value", sa.Boolean(), nullable=False),
            sa.Column("evidence_span", sa.Text(), nullable=False),
            sa.Column("start_offset", sa.Integer(), nullable=False),
            sa.Column("end_offset", sa.Integer(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("extractor", sa.String(80), nullable=False),
            sa.Column("extractor_version", sa.String(80), nullable=False),
            sa.Column("review_status", sa.String(40), nullable=False),
            sa.Column("human_labels_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_answer_semantic_facts_snapshot", "answer_semantic_facts", ["snapshot_id"])
        op.create_index("ix_answer_semantic_facts_project_prompt", "answer_semantic_facts", ["project_id", "prompt_id"])
        op.create_index("ix_answer_semantic_facts_run_type", "answer_semantic_facts", ["run_id", "fact_type"])

    if "target_brand_capability_truths" not in tables:
        op.create_table(
            "target_brand_capability_truths",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("brand_id", sa.Integer(), sa.ForeignKey("recommendation_entities.id", ondelete="SET NULL"), nullable=True),
            sa.Column("capability_key", sa.String(160), nullable=False),
            sa.Column("capability_label", sa.String(160), nullable=False),
            sa.Column("product_truth_status", sa.String(40), nullable=False),
            sa.Column("truth_source", sa.String(80), nullable=False),
            sa.Column("source_reference", sa.Text(), nullable=False),
            sa.Column("reviewed_by", sa.String(120), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("note", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", "brand_id", "capability_key", name="uq_target_brand_capability_truth"),
        )
        op.create_index("ix_target_brand_capability_truths_project_status", "target_brand_capability_truths", ["project_id", "product_truth_status"])


def downgrade() -> None:
    for table in ["target_brand_capability_truths", "answer_semantic_facts"]:
        if table in _tables():
            op.drop_table(table)
