"""Add Citation Passage Intelligence tables for Golden Case analysis."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260811_01"
down_revision = "20260808_01"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()

    if "source_documents" not in tables:
        op.create_table("source_documents",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("url", sa.String(1200), nullable=False),
            sa.Column("canonical_url", sa.String(1200), nullable=False),
            sa.Column("domain", sa.String(255), nullable=False),
            sa.Column("source_type", sa.String(40), nullable=False),
            sa.Column("fetch_status", sa.String(40), nullable=False),
            sa.Column("failure_reason", sa.Text(), nullable=False),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("author", sa.String(240), nullable=False),
            sa.Column("publish_time", sa.String(80), nullable=False),
            sa.Column("raw_html", sa.Text(), nullable=False),
            sa.Column("clean_text", sa.Text(), nullable=False),
            sa.Column("clean_text_hash", sa.String(64), nullable=False),
            sa.Column("content_blocks_json", sa.Text(), nullable=False),
            sa.Column("fetch_time", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_source_documents_url", "source_documents", ["url"])
        op.create_index("ix_source_documents_domain", "source_documents", ["domain"])
        op.create_index("ix_source_documents_source_type", "source_documents", ["source_type"])
        op.create_index("ix_source_documents_fetch_status", "source_documents", ["fetch_status"])

    if "answer_claims" not in tables:
        op.create_table("answer_claims",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("browser_monitor_runs.id"), nullable=False),
            sa.Column("claim_index", sa.Integer(), nullable=False),
            sa.Column("raw_text", sa.Text(), nullable=False),
            sa.Column("claim_type", sa.String(60), nullable=False),
            sa.Column("citation_anchor", sa.Integer(), nullable=True),
            sa.Column("citation_ids_json", sa.Text(), nullable=False),
            sa.Column("epistemic_status", sa.String(40), nullable=False),
            sa.Column("provenance", sa.String(40), nullable=False),
            sa.Column("reviewer", sa.String(120), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("review_note", sa.Text(), nullable=False),
            sa.Column("answer_position", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_answer_claims_run_id", "answer_claims", ["run_id"])

    if "passage_alignments" not in tables:
        op.create_table("passage_alignments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("answer_claim_id", sa.Integer(), sa.ForeignKey("answer_claims.id"), nullable=False),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("browser_monitor_runs.id"), nullable=False),
            sa.Column("citation_id", sa.Integer(), sa.ForeignKey("reference_sources.id"), nullable=True),
            sa.Column("source_document_id", sa.Integer(), sa.ForeignKey("source_documents.id"), nullable=True),
            sa.Column("passage_index", sa.Integer(), nullable=True),
            sa.Column("alignment_level", sa.String(40), nullable=False),
            sa.Column("alignment_method", sa.String(80), nullable=False),
            sa.Column("score", sa.Float(), nullable=False),
            sa.Column("evidence", sa.Text(), nullable=False),
            sa.Column("epistemic_status", sa.String(40), nullable=False),
            sa.Column("provenance", sa.String(40), nullable=False),
            sa.Column("review_status", sa.String(40), nullable=False),
            sa.Column("reviewer", sa.String(120), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_passage_alignments_answer_claim_id", "passage_alignments", ["answer_claim_id"])
        op.create_index("ix_passage_alignments_citation_id", "passage_alignments", ["citation_id"])
        op.create_index("ix_passage_alignments_source_document_id", "passage_alignments", ["source_document_id"])


def downgrade() -> None:
    for table in ["passage_alignments", "answer_claims", "source_documents"]:
        if table in _tables():
            op.drop_table(table)
