"""Add immutable child draft assets to frozen Agent result versions."""

from alembic import op

from app.models import Base


revision = "20261030_01"
down_revision = "20261022_01"
branch_labels = None
depends_on = None


TABLES = (
    "agent_draft_artifact_versions",
    "agent_draft_artifact_feedback",
    "agent_draft_artifact_regenerations",
)


def upgrade() -> None:
    bind = op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=False)
    for name in ("agent_draft_artifact_versions", "agent_draft_artifact_feedback"):
        op.execute(f"""CREATE TRIGGER trg_{name}_no_update
          BEFORE UPDATE ON {name}
          BEGIN SELECT RAISE(ABORT, 'AGENT_DRAFT_ARTIFACT_APPEND_ONLY'); END""")
        op.execute(f"""CREATE TRIGGER trg_{name}_no_delete
          BEFORE DELETE ON {name}
          BEGIN SELECT RAISE(ABORT, 'AGENT_DRAFT_ARTIFACT_APPEND_ONLY'); END""")
    op.execute("""CREATE TRIGGER trg_agent_draft_regeneration_identity_immutable
      BEFORE UPDATE ON agent_draft_artifact_regenerations
      WHEN OLD.request_id != NEW.request_id
        OR OLD.idempotency_key != NEW.idempotency_key
        OR OLD.source_artifact_version != NEW.source_artifact_version
        OR OLD.parent_result_version != NEW.parent_result_version
        OR OLD.agent_run_id != NEW.agent_run_id
        OR OLD.project_id != NEW.project_id
        OR OLD.prompt_id != NEW.prompt_id
        OR OLD.requested_by != NEW.requested_by
        OR OLD.request_hash != NEW.request_hash
        OR OLD.server_policy_json != NEW.server_policy_json
      BEGIN SELECT RAISE(ABORT, 'AGENT_DRAFT_REGENERATION_IDENTITY_IMMUTABLE'); END""")
    op.execute("""CREATE TRIGGER trg_agent_draft_regeneration_no_delete
      BEFORE DELETE ON agent_draft_artifact_regenerations
      BEGIN SELECT RAISE(ABORT, 'AGENT_DRAFT_REGENERATION_APPEND_ONLY'); END""")


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(bind)
