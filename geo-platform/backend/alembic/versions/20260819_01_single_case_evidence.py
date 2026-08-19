"""Single Case Evidence — 语义证据链新表。

新增：
- llm_call_cache：语义模型调用缓存
- recommendation_events：答案语义事件（machine/human 分离）
- source_claims：盲评 Source Claim
- evidence_alignments：语义证据对齐
- source_quality：SourceDocument 内容质量分层（不改写 fetch_status）
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260819_01"
down_revision = "20260813_01"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()

    if "llm_call_cache" not in tables:
        op.create_table("llm_call_cache",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("model", sa.String(120), nullable=False),
            sa.Column("prompt_version", sa.String(80), nullable=False),
            sa.Column("schema_version", sa.String(40), nullable=False),
            sa.Column("input_hash", sa.String(64), nullable=False),
            sa.Column("raw_response_hash", sa.String(64), nullable=False),
            sa.Column("parsed_payload_json", sa.Text(), nullable=False),
            sa.Column("token_usage", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_llm_call_cache_lookup", "llm_call_cache",
            ["provider", "model", "prompt_version", "schema_version", "input_hash"])

    if "recommendation_events" not in tables:
        op.create_table("recommendation_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("prompt_id", sa.Integer(), nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("answer_hash", sa.String(64), nullable=False),
            sa.Column("entity_text", sa.String(240), nullable=False),
            sa.Column("entity_type", sa.String(40), nullable=False),
            sa.Column("speech_act", sa.String(40), nullable=False),
            sa.Column("recommendation_strength", sa.String(20), nullable=False),
            sa.Column("polarity", sa.String(20), nullable=False),
            sa.Column("answer_span", sa.Text(), nullable=False),
            sa.Column("raw_start", sa.Integer(), nullable=False),
            sa.Column("raw_end", sa.Integer(), nullable=False),
            sa.Column("reasons_json", sa.Text(), nullable=False),
            sa.Column("selection_criteria_json", sa.Text(), nullable=False),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("model", sa.String(120), nullable=False),
            sa.Column("prompt_version", sa.String(80), nullable=False),
            sa.Column("schema_version", sa.String(40), nullable=False),
            sa.Column("machine_payload_json", sa.Text(), nullable=False),
            sa.Column("human_payload_json", sa.Text(), nullable=False),
            sa.Column("review_status", sa.String(40), nullable=False),
            sa.Column("reviewer", sa.String(120), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_recommendation_events_run", "recommendation_events", ["run_id"])
        op.create_index("ix_recommendation_events_answer_hash", "recommendation_events", ["answer_hash"])

    if "source_claims" not in tables:
        op.create_table("source_claims",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("source_document_id", sa.Integer(), nullable=False),
            sa.Column("passage_id", sa.String(120), nullable=False),
            sa.Column("source_owner_entity", sa.String(240), nullable=False),
            sa.Column("source_role", sa.String(40), nullable=False),
            sa.Column("subject_entity", sa.String(240), nullable=False),
            sa.Column("normalized_claim", sa.Text(), nullable=False),
            sa.Column("subject_text", sa.String(240), nullable=False),
            sa.Column("predicate", sa.String(240), nullable=False),
            sa.Column("object_text", sa.String(500), nullable=False),
            sa.Column("claim_type", sa.String(40), nullable=False),
            sa.Column("polarity", sa.String(20), nullable=False),
            sa.Column("source_span", sa.Text(), nullable=False),
            sa.Column("raw_start", sa.Integer(), nullable=False),
            sa.Column("raw_end", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("model", sa.String(120), nullable=False),
            sa.Column("prompt_version", sa.String(80), nullable=False),
            sa.Column("schema_version", sa.String(40), nullable=False),
            sa.Column("machine_payload_json", sa.Text(), nullable=False),
            sa.Column("human_payload_json", sa.Text(), nullable=False),
            sa.Column("review_status", sa.String(40), nullable=False),
            sa.Column("reviewer", sa.String(120), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_source_claims_document", "source_claims", ["source_document_id"])

    if "evidence_alignments" not in tables:
        op.create_table("evidence_alignments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("prompt_id", sa.Integer(), nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("recommendation_event_id", sa.Integer(), nullable=False),
            sa.Column("recommendation_reason_id", sa.String(120), nullable=False),
            sa.Column("source_document_id", sa.Integer(), nullable=False),
            sa.Column("source_claim_id", sa.Integer(), nullable=False),
            sa.Column("relation", sa.String(40), nullable=False),
            sa.Column("scope_relation", sa.String(40), nullable=False),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("model", sa.String(120), nullable=False),
            sa.Column("prompt_version", sa.String(80), nullable=False),
            sa.Column("schema_version", sa.String(40), nullable=False),
            sa.Column("machine_payload_json", sa.Text(), nullable=False),
            sa.Column("human_payload_json", sa.Text(), nullable=False),
            sa.Column("review_status", sa.String(40), nullable=False),
            sa.Column("reviewer", sa.String(120), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_evidence_alignments_event", "evidence_alignments", ["recommendation_event_id"])
        op.create_index("ix_evidence_alignments_claim", "evidence_alignments", ["source_claim_id"])

    if "source_quality" not in tables:
        op.create_table("source_quality",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("source_document_id", sa.Integer(), nullable=False),
            sa.Column("content_quality_status", sa.String(40), nullable=False),
            sa.Column("quality_source", sa.String(80), nullable=False),
            sa.Column("quality_reason", sa.Text(), nullable=False),
            sa.Column("clean_text_hash", sa.String(64), nullable=False),
            sa.Column("extractor_version", sa.String(80), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("reviewed_by", sa.String(120), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_source_quality_document", "source_quality", ["source_document_id"])


def downgrade() -> None:
    for table in ["source_quality", "evidence_alignments", "source_claims", "recommendation_events", "llm_call_cache"]:
        if table in _tables():
            op.drop_table(table)
