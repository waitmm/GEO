"""Guarded append-only refresh attempts for existing Citation snapshots."""

from alembic import op

from app.models import Base


revision = "20261019_01"
down_revision = "20261015_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    name = "single_prompt_citation_refreshes"
    Base.metadata.tables[name].create(op.get_bind(), checkfirst=False)
    op.execute(f"""CREATE TRIGGER trg_single_prompt_citation_refresh_identity_immutable
      BEFORE UPDATE ON {name}
      WHEN OLD.refresh_id != NEW.refresh_id
        OR OLD.preparation_id != NEW.preparation_id
        OR OLD.analysis_id != NEW.analysis_id
        OR OLD.context_id != NEW.context_id
        OR OLD.project_id != NEW.project_id
        OR OLD.prompt_id != NEW.prompt_id
        OR OLD.citation_manifest_id != NEW.citation_manifest_id
        OR OLD.citation_manifest_hash != NEW.citation_manifest_hash
        OR OLD.source_key != NEW.source_key
        OR OLD.canonical_url != NEW.canonical_url
        OR OLD.base_completion_manifest_id != NEW.base_completion_manifest_id
        OR OLD.base_completion_version != NEW.base_completion_version
        OR OLD.base_completion_manifest_hash != NEW.base_completion_manifest_hash
        OR OLD.base_snapshot_id != NEW.base_snapshot_id
        OR OLD.base_snapshot_hash != NEW.base_snapshot_hash
        OR OLD.idempotency_key != NEW.idempotency_key
        OR OLD.input_hash != NEW.input_hash
        OR OLD.requested_by != NEW.requested_by
        OR OLD.outcome_json != '{{}}' OR OLD.outcome_hash != ''
      BEGIN SELECT RAISE(ABORT, 'CITATION_REFRESH_IMMUTABLE'); END""")
    op.execute(f"""CREATE TRIGGER trg_single_prompt_citation_refresh_no_delete
      BEFORE DELETE ON {name}
      BEGIN SELECT RAISE(ABORT, 'CITATION_REFRESH_IMMUTABLE'); END""")


def downgrade() -> None:
    Base.metadata.tables["single_prompt_citation_refreshes"].drop(op.get_bind())
