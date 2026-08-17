"""Add decision market core tables and experiment fields."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260812_02"
down_revision = "20260812_01"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    tables = _tables()

    if "decision_selection_criteria" not in tables:
        op.create_table(
            "decision_selection_criteria",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("recommendation_intelligence_snapshots.id", ondelete="SET NULL"), nullable=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("prompt_id", sa.Integer(), sa.ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("browser_monitor_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("criterion_type", sa.String(80), nullable=False),
            sa.Column("criterion_label", sa.String(160), nullable=False),
            sa.Column("normalized_criterion", sa.String(160), nullable=False),
            sa.Column("answer_span", sa.Text(), nullable=False),
            sa.Column("start_offset", sa.Integer(), nullable=False),
            sa.Column("end_offset", sa.Integer(), nullable=False),
            sa.Column("criterion_present", sa.Boolean(), nullable=False),
            sa.Column("criterion_used_for_selection", sa.Boolean(), nullable=False),
            sa.Column("related_brand_id", sa.Integer(), sa.ForeignKey("recommendation_entities.id", ondelete="SET NULL"), nullable=True),
            sa.Column("related_brand_name", sa.String(240), nullable=False),
            sa.Column("related_solution_object", sa.String(160), nullable=False),
            sa.Column("polarity", sa.String(20), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("extractor", sa.String(80), nullable=False),
            sa.Column("extractor_version", sa.String(80), nullable=False),
            sa.Column("review_status", sa.String(40), nullable=False),
            sa.Column("human_label_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_decision_selection_criteria_snapshot", "decision_selection_criteria", ["snapshot_id"])
        op.create_index("ix_decision_selection_criteria_project_prompt", "decision_selection_criteria", ["project_id", "prompt_id"])
        op.create_index("ix_decision_selection_criteria_run", "decision_selection_criteria", ["run_id"])

    if "brand_capability_claims" not in tables:
        op.create_table(
            "brand_capability_claims",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("recommendation_intelligence_snapshots.id", ondelete="SET NULL"), nullable=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("prompt_id", sa.Integer(), sa.ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("browser_monitor_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("brand_entity_id", sa.Integer(), sa.ForeignKey("recommendation_entities.id", ondelete="SET NULL"), nullable=True),
            sa.Column("brand_name", sa.String(240), nullable=False),
            sa.Column("need_label", sa.String(160), nullable=False),
            sa.Column("capability_label", sa.String(160), nullable=False),
            sa.Column("subject_text", sa.String(240), nullable=False),
            sa.Column("predicate", sa.String(60), nullable=False),
            sa.Column("object_text", sa.String(240), nullable=False),
            sa.Column("claim_text", sa.Text(), nullable=False),
            sa.Column("answer_span", sa.Text(), nullable=False),
            sa.Column("start_offset", sa.Integer(), nullable=False),
            sa.Column("end_offset", sa.Integer(), nullable=False),
            sa.Column("polarity", sa.String(20), nullable=False),
            sa.Column("negation", sa.Boolean(), nullable=False),
            sa.Column("epistemic_status", sa.String(40), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("extractor_version", sa.String(80), nullable=False),
            sa.Column("review_status", sa.String(40), nullable=False),
            sa.Column("human_label_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_brand_capability_claims_snapshot", "brand_capability_claims", ["snapshot_id"])
        op.create_index("ix_brand_capability_claims_project_prompt", "brand_capability_claims", ["project_id", "prompt_id"])
        op.create_index("ix_brand_capability_claims_run_brand", "brand_capability_claims", ["run_id", "brand_entity_id"])

    if "decision_evidence_adoptions" not in tables:
        op.create_table(
            "decision_evidence_adoptions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("recommendation_intelligence_snapshots.id", ondelete="SET NULL"), nullable=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("prompt_id", sa.Integer(), sa.ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("browser_monitor_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("document_id", sa.Integer(), sa.ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True),
            sa.Column("chunk_id", sa.Integer(), nullable=True),
            sa.Column("citation_id", sa.Integer(), sa.ForeignKey("reference_sources.id", ondelete="SET NULL"), nullable=True),
            sa.Column("retrieval_candidate_id", sa.Integer(), sa.ForeignKey("retrieval_candidates.id", ondelete="SET NULL"), nullable=True),
            sa.Column("answer_claim_id", sa.Integer(), sa.ForeignKey("answer_claims.id", ondelete="SET NULL"), nullable=True),
            sa.Column("recommendation_claim_id", sa.Integer(), sa.ForeignKey("recommendation_claims.id", ondelete="SET NULL"), nullable=True),
            sa.Column("selection_criterion_id", sa.Integer(), sa.ForeignKey("decision_selection_criteria.id", ondelete="SET NULL"), nullable=True),
            sa.Column("retrieval_eligible", sa.Boolean(), nullable=False),
            sa.Column("retrieved", sa.Boolean(), nullable=False),
            sa.Column("cited", sa.Boolean(), nullable=False),
            sa.Column("supports_claim", sa.Boolean(), nullable=False),
            sa.Column("associated_with_selection_reason", sa.Boolean(), nullable=False),
            sa.Column("support_role", sa.String(80), nullable=False),
            sa.Column("support_strength", sa.String(40), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("attribution_method", sa.String(80), nullable=False),
            sa.Column("attribution_version", sa.String(80), nullable=False),
            sa.Column("review_status", sa.String(40), nullable=False),
            sa.Column("human_label_json", sa.Text(), nullable=False),
            sa.Column("answer_span", sa.Text(), nullable=False),
            sa.Column("evidence_span", sa.Text(), nullable=False),
            sa.Column("source_url", sa.String(1200), nullable=False),
            sa.Column("source_domain", sa.String(255), nullable=False),
            sa.Column("source_title", sa.String(500), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_decision_evidence_adoptions_snapshot", "decision_evidence_adoptions", ["snapshot_id"])
        op.create_index("ix_decision_evidence_adoptions_project_prompt", "decision_evidence_adoptions", ["project_id", "prompt_id"])
        op.create_index("ix_decision_evidence_adoptions_run", "decision_evidence_adoptions", ["run_id"])

    if "decision_gap_diagnoses" not in tables:
        op.create_table(
            "decision_gap_diagnoses",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("recommendation_intelligence_snapshots.id", ondelete="SET NULL"), nullable=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("prompt_id", sa.Integer(), sa.ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("gap_type", sa.String(80), nullable=False),
            sa.Column("severity", sa.String(40), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("numerator", sa.Integer(), nullable=False),
            sa.Column("denominator", sa.Integer(), nullable=False),
            sa.Column("eligible_denominator", sa.Integer(), nullable=False),
            sa.Column("metric_name", sa.String(120), nullable=False),
            sa.Column("metric_value", sa.Float(), nullable=True),
            sa.Column("supporting_run_ids_json", sa.Text(), nullable=False),
            sa.Column("counterexample_run_ids_json", sa.Text(), nullable=False),
            sa.Column("supporting_claim_ids_json", sa.Text(), nullable=False),
            sa.Column("supporting_evidence_ids_json", sa.Text(), nullable=False),
            sa.Column("diagnosis_basis_json", sa.Text(), nullable=False),
            sa.Column("rule_version", sa.String(80), nullable=False),
            sa.Column("llm_version", sa.String(120), nullable=False),
            sa.Column("review_status", sa.String(40), nullable=False),
            sa.Column("human_label_json", sa.Text(), nullable=False),
            sa.Column("diagnosis_text", sa.Text(), nullable=False),
            sa.Column("action_hint", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_decision_gap_diagnoses_snapshot", "decision_gap_diagnoses", ["snapshot_id"])
        op.create_index("ix_decision_gap_diagnoses_project_prompt", "decision_gap_diagnoses", ["project_id", "prompt_id"])
        op.create_index("ix_decision_gap_diagnoses_type", "decision_gap_diagnoses", ["gap_type"])

    if "optimization_experiments" in tables:
        _add_column_if_missing("optimization_experiments", sa.Column("hypothesis_type", sa.String(80), nullable=False, server_default=""))
        _add_column_if_missing("optimization_experiments", sa.Column("mechanism", sa.Text(), nullable=False, server_default=""))
        _add_column_if_missing("optimization_experiments", sa.Column("intervention_family", sa.String(80), nullable=False, server_default=""))
        _add_column_if_missing("optimization_experiments", sa.Column("intervention_variables_json", sa.Text(), nullable=False, server_default="{}"))
        _add_column_if_missing("optimization_experiments", sa.Column("allowed_changes_json", sa.Text(), nullable=False, server_default="[]"))
        _add_column_if_missing("optimization_experiments", sa.Column("forbidden_changes_json", sa.Text(), nullable=False, server_default="[]"))
        _add_column_if_missing("optimization_experiments", sa.Column("baseline_numerator", sa.Integer(), nullable=True))
        _add_column_if_missing("optimization_experiments", sa.Column("baseline_denominator", sa.Integer(), nullable=True))
        _add_column_if_missing("optimization_experiments", sa.Column("baseline_metric_value", sa.Float(), nullable=True))
        _add_column_if_missing("optimization_experiments", sa.Column("success_threshold", sa.Float(), nullable=True))
        _add_column_if_missing("optimization_experiments", sa.Column("sample_size_target", sa.Integer(), nullable=True))
        _add_column_if_missing("optimization_experiments", sa.Column("target_prompt_ids_json", sa.Text(), nullable=False, server_default="[]"))
        # SQLite cannot add a foreign-key constraint to an existing table via
        # ALTER TABLE; keep this as a plain column for local compatibility.
        _add_column_if_missing("optimization_experiments", sa.Column("target_brand_id", sa.Integer(), nullable=True))
        _add_column_if_missing("optimization_experiments", sa.Column("target_asset_ids_json", sa.Text(), nullable=False, server_default="[]"))
        _add_column_if_missing("optimization_experiments", sa.Column("recollection_strategy_json", sa.Text(), nullable=False, server_default="{}"))


def downgrade() -> None:
    for table in [
        "decision_gap_diagnoses",
        "decision_evidence_adoptions",
        "brand_capability_claims",
        "decision_selection_criteria",
    ]:
        if table in _tables():
            op.drop_table(table)
