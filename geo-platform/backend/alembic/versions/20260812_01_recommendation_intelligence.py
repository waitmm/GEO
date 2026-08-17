"""Add recommendation market intelligence tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260812_01"
down_revision = "20260811_01"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()

    if "recommendation_intelligence_snapshots" not in tables:
        op.create_table(
            "recommendation_intelligence_snapshots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("prompt_id", sa.Integer(), sa.ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_run_ids_json", sa.Text(), nullable=False),
            sa.Column("recommendation_schema_version", sa.String(60), nullable=False),
            sa.Column("entity_resolver_version", sa.String(60), nullable=False),
            sa.Column("recommendation_extractor_version", sa.String(60), nullable=False),
            sa.Column("decision_mode", sa.String(60), nullable=False),
            sa.Column("recommendation_expected", sa.Boolean(), nullable=False),
            sa.Column("metric_eligibility_json", sa.Text(), nullable=False),
            sa.Column("landscape_json", sa.Text(), nullable=False),
            sa.Column("positioning_json", sa.Text(), nullable=False),
            sa.Column("evidence_links_json", sa.Text(), nullable=False),
            sa.Column("gap_diagnosis_json", sa.Text(), nullable=False),
            sa.Column("intervention_candidates_json", sa.Text(), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_recommendation_snapshots_project_prompt_status",
            "recommendation_intelligence_snapshots",
            ["project_id", "prompt_id", "status"],
        )

    if "recommendation_entities" not in tables:
        op.create_table(
            "recommendation_entities",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("canonical_name", sa.String(240), nullable=False),
            sa.Column("entity_type", sa.String(40), nullable=False),
            sa.Column("aliases_json", sa.Text(), nullable=False),
            sa.Column("domain", sa.String(255), nullable=False),
            sa.Column("official_urls_json", sa.Text(), nullable=False),
            sa.Column("normalized_key", sa.String(240), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("source", sa.String(80), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", "entity_type", "normalized_key", name="uq_recommendation_entity_project_type_key"),
        )
        op.create_index("ix_recommendation_entities_project_type", "recommendation_entities", ["project_id", "entity_type"])

    if "recommendation_claims" not in tables:
        op.create_table(
            "recommendation_claims",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("recommendation_intelligence_snapshots.id", ondelete="SET NULL"), nullable=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("prompt_id", sa.Integer(), sa.ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("browser_monitor_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("entity_id", sa.Integer(), sa.ForeignKey("recommendation_entities.id", ondelete="SET NULL"), nullable=True),
            sa.Column("entity_name", sa.String(240), nullable=False),
            sa.Column("recommendation_type", sa.String(60), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("rank", sa.Integer(), nullable=True),
            sa.Column("is_conditional", sa.Boolean(), nullable=False),
            sa.Column("condition_type", sa.String(60), nullable=False),
            sa.Column("condition_text", sa.Text(), nullable=False),
            sa.Column("recommendation_text", sa.Text(), nullable=False),
            sa.Column("answer_span", sa.Text(), nullable=False),
            sa.Column("polarity", sa.String(20), nullable=False),
            sa.Column("reason_texts_json", sa.Text(), nullable=False),
            sa.Column("extraction_method", sa.String(80), nullable=False),
            sa.Column("extraction_confidence", sa.Float(), nullable=False),
            sa.Column("model", sa.String(120), nullable=False),
            sa.Column("prompt_version", sa.String(80), nullable=False),
            sa.Column("review_status", sa.String(40), nullable=False),
            sa.Column("human_payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_recommendation_claims_project_prompt", "recommendation_claims", ["project_id", "prompt_id"])
        op.create_index("ix_recommendation_claims_run_entity", "recommendation_claims", ["run_id", "entity_id"])

    if "recommendation_reason_claims" not in tables:
        op.create_table(
            "recommendation_reason_claims",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("recommendation_intelligence_snapshots.id", ondelete="SET NULL"), nullable=True),
            sa.Column("recommendation_claim_id", sa.Integer(), sa.ForeignKey("recommendation_claims.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("prompt_id", sa.Integer(), sa.ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("browser_monitor_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("entity_id", sa.Integer(), sa.ForeignKey("recommendation_entities.id", ondelete="SET NULL"), nullable=True),
            sa.Column("entity_name", sa.String(240), nullable=False),
            sa.Column("reason_type", sa.String(80), nullable=False),
            sa.Column("reason_text", sa.Text(), nullable=False),
            sa.Column("claim_span", sa.Text(), nullable=False),
            sa.Column("polarity", sa.String(20), nullable=False),
            sa.Column("is_limitation", sa.Boolean(), nullable=False),
            sa.Column("is_comparison", sa.Boolean(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_recommendation_reason_claims_rec_claim", "recommendation_reason_claims", ["recommendation_claim_id"])
        op.create_index("ix_recommendation_reason_claims_project_prompt", "recommendation_reason_claims", ["project_id", "prompt_id"])

    if "recommendation_evidence_links" not in tables:
        op.create_table(
            "recommendation_evidence_links",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("recommendation_intelligence_snapshots.id", ondelete="SET NULL"), nullable=True),
            sa.Column("recommendation_claim_id", sa.Integer(), sa.ForeignKey("recommendation_claims.id", ondelete="CASCADE"), nullable=False),
            sa.Column("reason_claim_id", sa.Integer(), sa.ForeignKey("recommendation_reason_claims.id", ondelete="SET NULL"), nullable=True),
            sa.Column("citation_id", sa.Integer(), sa.ForeignKey("reference_sources.id", ondelete="SET NULL"), nullable=True),
            sa.Column("supported_entity_id", sa.Integer(), sa.ForeignKey("recommendation_entities.id", ondelete="SET NULL"), nullable=True),
            sa.Column("supported_entity_name", sa.String(240), nullable=False),
            sa.Column("evidence_roles_json", sa.Text(), nullable=False),
            sa.Column("primary_evidence_role", sa.String(80), nullable=False),
            sa.Column("role_confidence", sa.Float(), nullable=False),
            sa.Column("role_reason", sa.Text(), nullable=False),
            sa.Column("attribution_method", sa.String(80), nullable=False),
            sa.Column("attribution_confidence", sa.Float(), nullable=False),
            sa.Column("answer_span", sa.Text(), nullable=False),
            sa.Column("source_passage", sa.Text(), nullable=False),
            sa.Column("match_method", sa.String(80), nullable=False),
            sa.Column("match_score", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_recommendation_evidence_links_rec_claim", "recommendation_evidence_links", ["recommendation_claim_id"])
        op.create_index("ix_recommendation_evidence_links_citation", "recommendation_evidence_links", ["citation_id"])


def downgrade() -> None:
    for table in [
        "recommendation_evidence_links",
        "recommendation_reason_claims",
        "recommendation_claims",
        "recommendation_entities",
        "recommendation_intelligence_snapshots",
    ]:
        if table in _tables():
            op.drop_table(table)
