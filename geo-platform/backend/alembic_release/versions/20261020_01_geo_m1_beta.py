"""Add append-only internal Beta feedback for Agent result versions."""

from alembic import op

from app.models import Base


revision = "20261020_01"
down_revision = "20261019_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["agent_result_feedback"].create(bind, checkfirst=False)
    op.execute("""CREATE TRIGGER trg_agent_result_feedback_no_update
      BEFORE UPDATE ON agent_result_feedback
      BEGIN SELECT RAISE(ABORT, 'AGENT_RESULT_FEEDBACK_APPEND_ONLY'); END""")
    op.execute("""CREATE TRIGGER trg_agent_result_feedback_no_delete
      BEFORE DELETE ON agent_result_feedback
      BEGIN SELECT RAISE(ABORT, 'AGENT_RESULT_FEEDBACK_APPEND_ONLY'); END""")


def downgrade() -> None:
    Base.metadata.tables["agent_result_feedback"].drop(op.get_bind())
