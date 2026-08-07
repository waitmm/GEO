from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260806_01"
down_revision = None
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _columns(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if table_name in _tables() and column.name not in _columns(table_name):
        op.add_column(table_name, column)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if table_name in _tables() and index_name not in _indexes(table_name):
        op.create_index(index_name, table_name, columns)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    if table_name in _tables() and index_name in _indexes(table_name):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    tables = _tables()
    if "optimization_experiments" in tables:
        _add_column_if_missing("optimization_experiments", sa.Column("release_blocked", sa.Boolean(), nullable=False, server_default=sa.false()))
        _add_column_if_missing("optimization_experiments", sa.Column("release_blocked_reason", sa.Text(), nullable=False, server_default=""))

    if "optimization_evidence_packages" in tables:
        op.execute("CREATE INDEX IF NOT EXISTS ix_evidence_package_project_prompt_status ON optimization_evidence_packages (project_id, prompt_id, status)")
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_evidence_package_project_hash ON optimization_evidence_packages (project_id, package_hash)")
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_evidence_package_project_prompt_version ON optimization_evidence_packages (project_id, prompt_id, version)")

    if "page_snapshots" not in tables:
        op.create_table(
            "page_snapshots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("experiment_id", sa.Integer(), nullable=True),
            sa.Column("target_url", sa.String(length=1200), nullable=False),
            sa.Column("url", sa.String(length=1200), nullable=False),
            sa.Column("http_status", sa.Integer(), nullable=True),
            sa.Column("final_url", sa.String(length=1200), nullable=False),
            sa.Column("canonical_url", sa.String(length=1200), nullable=False),
            sa.Column("captured_at", sa.DateTime(), nullable=False),
            sa.Column("raw_html", sa.Text(), nullable=False),
            sa.Column("html_hash", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("meta_description", sa.Text(), nullable=False),
            sa.Column("h1", sa.String(length=500), nullable=False),
            sa.Column("main_text", sa.Text(), nullable=False),
            sa.Column("main_text_hash", sa.String(length=64), nullable=False),
            sa.Column("section_headings_json", sa.Text(), nullable=False),
            sa.Column("structured_data_json", sa.Text(), nullable=False),
            sa.Column("internal_links_json", sa.Text(), nullable=False),
            sa.Column("robots_directives_json", sa.Text(), nullable=False),
            sa.Column("snapshot_type", sa.String(length=40), nullable=False),
            sa.Column("capture_status", sa.String(length=40), nullable=False),
            sa.Column("capture_error", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["experiment_id"], ["optimization_experiments.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_page_snapshots_project_id", "page_snapshots", ["project_id"])
    _create_index_if_missing("ix_page_snapshots_experiment_id", "page_snapshots", ["experiment_id"])
    _create_index_if_missing("ix_page_snapshots_target_url", "page_snapshots", ["target_url"])
    _create_index_if_missing("ix_page_snapshots_snapshot_type", "page_snapshots", ["snapshot_type"])
    _create_index_if_missing("ix_page_snapshots_capture_status", "page_snapshots", ["capture_status"])
    _create_index_if_missing("ix_page_snapshots_captured_at", "page_snapshots", ["captured_at"])
    _create_index_if_missing("ix_page_snapshots_html_hash", "page_snapshots", ["html_hash"])
    _create_index_if_missing("ix_page_snapshots_main_text_hash", "page_snapshots", ["main_text_hash"])
    _create_index_if_missing("ix_page_snapshots_project_url_type", "page_snapshots", ["project_id", "url", "snapshot_type"])
    _create_index_if_missing("ix_page_snapshots_experiment_type", "page_snapshots", ["experiment_id", "snapshot_type"])

    tables = _tables()
    if "optimization_hypotheses" not in tables:
        op.create_table(
            "optimization_hypotheses",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("issue_id", sa.Integer(), nullable=False),
            sa.Column("experiment_id", sa.Integer(), nullable=False),
            sa.Column("evidence_package_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("observed_problem", sa.Text(), nullable=False),
            sa.Column("hypothesized_cause", sa.Text(), nullable=False),
            sa.Column("core_mechanism", sa.Text(), nullable=False),
            sa.Column("target_metric", sa.String(length=120), nullable=False),
            sa.Column("baseline_value", sa.String(length=120), nullable=False),
            sa.Column("expected_direction", sa.String(length=40), nullable=False),
            sa.Column("entry_observed_condition", sa.Text(), nullable=False),
            sa.Column("sustained_improvement_condition", sa.Text(), nullable=False),
            sa.Column("invalidating_result", sa.Text(), nullable=False),
            sa.Column("changed_features_json", sa.Text(), nullable=False),
            sa.Column("controlled_variables_json", sa.Text(), nullable=False),
            sa.Column("accepted_by", sa.String(length=120), nullable=False),
            sa.Column("accepted_at", sa.DateTime(), nullable=True),
            sa.Column("review_note", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["evidence_package_id"], ["optimization_evidence_packages.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["experiment_id"], ["optimization_experiments.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["issue_id"], ["optimization_issues.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("experiment_id", "evidence_package_id", "status", name="uq_hypothesis_experiment_package_status"),
        )
    _create_index_if_missing("ix_optimization_hypotheses_project_id", "optimization_hypotheses", ["project_id"])
    _create_index_if_missing("ix_optimization_hypotheses_issue_id", "optimization_hypotheses", ["issue_id"])
    _create_index_if_missing("ix_optimization_hypotheses_experiment_id", "optimization_hypotheses", ["experiment_id"])
    _create_index_if_missing("ix_optimization_hypotheses_evidence_package_id", "optimization_hypotheses", ["evidence_package_id"])
    _create_index_if_missing("ix_optimization_hypotheses_status", "optimization_hypotheses", ["status"])
    _create_index_if_missing("ix_optimization_hypotheses_experiment_status", "optimization_hypotheses", ["experiment_id", "status"])

    tables = _tables()
    if "optimization_strategy_candidates" not in tables:
        op.create_table(
            "optimization_strategy_candidates",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("experiment_id", sa.Integer(), nullable=True),
            sa.Column("evidence_package_id", sa.Integer(), nullable=False),
            sa.Column("target_url", sa.String(length=1200), nullable=False),
            sa.Column("provider", sa.String(length=120), nullable=False),
            sa.Column("model", sa.String(length=160), nullable=False),
            sa.Column("prompt_version", sa.String(length=120), nullable=False),
            sa.Column("prompt_text", sa.Text(), nullable=False),
            sa.Column("generated_at", sa.DateTime(), nullable=False),
            sa.Column("generation_status", sa.String(length=60), nullable=False),
            sa.Column("original_llm_payload_json", sa.Text(), nullable=False),
            sa.Column("structured_payload_json", sa.Text(), nullable=False),
            sa.Column("human_edited_payload_json", sa.Text(), nullable=False),
            sa.Column("evidence_validation_status", sa.String(length=60), nullable=False),
            sa.Column("evidence_validation_errors_json", sa.Text(), nullable=False),
            sa.Column("evidence_validation_warnings_json", sa.Text(), nullable=False),
            sa.Column("evidence_validated_at", sa.DateTime(), nullable=True),
            sa.Column("evidence_validator_version", sa.String(length=80), nullable=False),
            sa.Column("hypothesis_validation_status", sa.String(length=60), nullable=False),
            sa.Column("hypothesis_validation_errors_json", sa.Text(), nullable=False),
            sa.Column("hypothesis_validation_warnings_json", sa.Text(), nullable=False),
            sa.Column("hypothesis_validated_at", sa.DateTime(), nullable=True),
            sa.Column("hypothesis_validator_version", sa.String(length=80), nullable=False),
            sa.Column("review_status", sa.String(length=60), nullable=False),
            sa.Column("reviewed_by", sa.String(length=120), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("review_note", sa.Text(), nullable=False),
            sa.Column("converted_hypothesis_id", sa.Integer(), nullable=True),
            sa.Column("experiment_plan_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["converted_hypothesis_id"], ["optimization_hypotheses.id"]),
            sa.ForeignKeyConstraint(["evidence_package_id"], ["optimization_evidence_packages.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["experiment_id"], ["optimization_experiments.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_optimization_strategy_candidates_project_id", "optimization_strategy_candidates", ["project_id"])
    _create_index_if_missing("ix_optimization_strategy_candidates_experiment_id", "optimization_strategy_candidates", ["experiment_id"])
    _create_index_if_missing("ix_optimization_strategy_candidates_evidence_package_id", "optimization_strategy_candidates", ["evidence_package_id"])
    _create_index_if_missing("ix_optimization_strategy_candidates_target_url", "optimization_strategy_candidates", ["target_url"])
    _create_index_if_missing("ix_optimization_strategy_candidates_generated_at", "optimization_strategy_candidates", ["generated_at"])
    _create_index_if_missing("ix_optimization_strategy_candidates_generation_status", "optimization_strategy_candidates", ["generation_status"])
    _create_index_if_missing("ix_optimization_strategy_candidates_evidence_validation_status", "optimization_strategy_candidates", ["evidence_validation_status"])
    _create_index_if_missing("ix_optimization_strategy_candidates_hypothesis_validation_status", "optimization_strategy_candidates", ["hypothesis_validation_status"])
    _create_index_if_missing("ix_optimization_strategy_candidates_review_status", "optimization_strategy_candidates", ["review_status"])
    _create_index_if_missing("ix_optimization_strategy_candidates_converted_hypothesis_id", "optimization_strategy_candidates", ["converted_hypothesis_id"])
    _create_index_if_missing("ix_strategy_candidates_project_status", "optimization_strategy_candidates", ["project_id", "review_status"])
    _create_index_if_missing("ix_strategy_candidates_experiment_status", "optimization_strategy_candidates", ["experiment_id", "review_status"])

    tables = _tables()
    if "release_audit_records" not in tables:
        op.create_table(
            "release_audit_records",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("experiment_id", sa.Integer(), nullable=False),
            sa.Column("hypothesis_id", sa.Integer(), nullable=False),
            sa.Column("pre_release_snapshot_id", sa.Integer(), nullable=False),
            sa.Column("post_release_snapshot_id", sa.Integer(), nullable=False),
            sa.Column("planned_feature_changes_json", sa.Text(), nullable=False),
            sa.Column("deployed_feature_changes_json", sa.Text(), nullable=False),
            sa.Column("undeployed_feature_changes_json", sa.Text(), nullable=False),
            sa.Column("release_note", sa.Text(), nullable=False),
            sa.Column("confirmed_by", sa.String(length=120), nullable=False),
            sa.Column("confirmed_at", sa.DateTime(), nullable=False),
            sa.Column("online_verification_status", sa.String(length=80), nullable=False),
            sa.Column("correction_of_id", sa.Integer(), nullable=True),
            sa.Column("correction_reason", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["correction_of_id"], ["release_audit_records.id"]),
            sa.ForeignKeyConstraint(["experiment_id"], ["optimization_experiments.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["hypothesis_id"], ["optimization_hypotheses.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["post_release_snapshot_id"], ["page_snapshots.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["pre_release_snapshot_id"], ["page_snapshots.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_release_audit_records_experiment_id", "release_audit_records", ["experiment_id"])
    _create_index_if_missing("ix_release_audit_records_hypothesis_id", "release_audit_records", ["hypothesis_id"])
    _create_index_if_missing("ix_release_audit_records_pre_release_snapshot_id", "release_audit_records", ["pre_release_snapshot_id"])
    _create_index_if_missing("ix_release_audit_records_post_release_snapshot_id", "release_audit_records", ["post_release_snapshot_id"])
    _create_index_if_missing("ix_release_audit_records_confirmed_at", "release_audit_records", ["confirmed_at"])
    _create_index_if_missing("ix_release_audit_records_online_verification_status", "release_audit_records", ["online_verification_status"])
    _create_index_if_missing("ix_release_audit_records_experiment_status", "release_audit_records", ["experiment_id", "online_verification_status"])


def downgrade() -> None:
    _drop_index_if_exists("ix_release_audit_records_experiment_status", "release_audit_records")
    if "release_audit_records" in _tables():
        op.drop_table("release_audit_records")
    _drop_index_if_exists("ix_strategy_candidates_experiment_status", "optimization_strategy_candidates")
    _drop_index_if_exists("ix_strategy_candidates_project_status", "optimization_strategy_candidates")
    if "optimization_strategy_candidates" in _tables():
        op.drop_table("optimization_strategy_candidates")
    _drop_index_if_exists("ix_optimization_hypotheses_experiment_status", "optimization_hypotheses")
    if "optimization_hypotheses" in _tables():
        op.drop_table("optimization_hypotheses")
    _drop_index_if_exists("ix_page_snapshots_experiment_type", "page_snapshots")
    _drop_index_if_exists("ix_page_snapshots_project_url_type", "page_snapshots")
    if "page_snapshots" in _tables():
        op.drop_table("page_snapshots")
    _drop_index_if_exists("ix_evidence_package_project_prompt_version", "optimization_evidence_packages")
    _drop_index_if_exists("ix_evidence_package_project_hash", "optimization_evidence_packages")
    _drop_index_if_exists("ix_evidence_package_project_prompt_status", "optimization_evidence_packages")
