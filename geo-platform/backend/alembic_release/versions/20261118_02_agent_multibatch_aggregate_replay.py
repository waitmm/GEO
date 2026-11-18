"""Add append-only offline aggregate replay candidate persistence."""

from alembic import op
from sqlalchemy import text

from app.models import Base


revision = "20261118_02"
down_revision = "20261118_01"
branch_labels = None
depends_on = None


TABLES = (
    "agent_multibatch_aggregate_replay_attempts",
    "agent_multibatch_aggregate_replay_result_candidates",
)


def upgrade() -> None:
    bind = op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=False)
        op.execute(f"""CREATE TRIGGER trg_{name}_no_update
          BEFORE UPDATE ON {name}
          BEGIN SELECT RAISE(ABORT, 'AGENT_MULTIBATCH_AGGREGATE_REPLAY_APPEND_ONLY'); END""")
        op.execute(f"""CREATE TRIGGER trg_{name}_no_delete
          BEFORE DELETE ON {name}
          BEGIN SELECT RAISE(ABORT, 'AGENT_MULTIBATCH_AGGREGATE_REPLAY_APPEND_ONLY'); END""")
    op.execute("""CREATE TRIGGER trg_agent_multibatch_aggregate_replay_attempt_plan_state
      BEFORE INSERT ON agent_multibatch_aggregate_replay_attempts
      WHEN (SELECT status FROM agent_multibatch_plans WHERE plan_id = NEW.plan_id)
        != 'AGGREGATE_REPLAY_RUNNING'
      BEGIN SELECT RAISE(ABORT, 'AGENT_MULTIBATCH_AGGREGATE_REPLAY_PLAN_STATE_INVALID'); END""")


def downgrade() -> None:
    bind = op.get_bind()
    populated = {
        name: int(bind.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar_one())
        for name in TABLES
    }
    if any(populated.values()):
        raise RuntimeError("AGENT_MULTIBATCH_AGGREGATE_REPLAY_AUDIT_ROWS_PRESENT")
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(bind, checkfirst=True)
