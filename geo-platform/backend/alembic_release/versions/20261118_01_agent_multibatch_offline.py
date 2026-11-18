"""Add append-only offline multi-batch execution persistence."""

from alembic import op
from sqlalchemy import text

from app.models import Base


revision = "20261118_01"
down_revision = "20261030_02"
branch_labels = None
depends_on = None


TABLES = (
    "agent_multibatch_plans",
    "agent_multibatch_attempts",
    "agent_multibatch_results",
    "agent_multibatch_aggregate_candidates",
)


def upgrade() -> None:
    bind = op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=False)
    for name in (
        "agent_multibatch_attempts", "agent_multibatch_results",
        "agent_multibatch_aggregate_candidates",
    ):
        op.execute(f"""CREATE TRIGGER trg_{name}_no_update
          BEFORE UPDATE ON {name}
          BEGIN SELECT RAISE(ABORT, 'AGENT_MULTIBATCH_APPEND_ONLY'); END""")
        op.execute(f"""CREATE TRIGGER trg_{name}_no_delete
          BEFORE DELETE ON {name}
          BEGIN SELECT RAISE(ABORT, 'AGENT_MULTIBATCH_APPEND_ONLY'); END""")
    op.execute("""CREATE TRIGGER trg_agent_multibatch_plan_identity_immutable
      BEFORE UPDATE ON agent_multibatch_plans
      WHEN OLD.plan_id != NEW.plan_id
        OR OLD.agent_run_id != NEW.agent_run_id
        OR OLD.frozen_scope_hash != NEW.frozen_scope_hash
        OR OLD.plan_hash != NEW.plan_hash
        OR OLD.reservation_identity_hash != NEW.reservation_identity_hash
        OR OLD.idempotency_key != NEW.idempotency_key
        OR OLD.plan_json != NEW.plan_json
        OR OLD.reservation_json != NEW.reservation_json
        OR OLD.max_attempts_per_batch != NEW.max_attempts_per_batch
      BEGIN SELECT RAISE(ABORT, 'AGENT_MULTIBATCH_IDENTITY_IMMUTABLE'); END""")
    op.execute("""CREATE TRIGGER trg_agent_multibatch_plan_no_delete
      BEFORE DELETE ON agent_multibatch_plans
      BEGIN SELECT RAISE(ABORT, 'AGENT_MULTIBATCH_APPEND_ONLY'); END""")
    op.execute("""CREATE TRIGGER trg_agent_multibatch_attempt_plan_state
      BEFORE INSERT ON agent_multibatch_attempts
      WHEN (SELECT status FROM agent_multibatch_plans WHERE plan_id = NEW.plan_id)
        IN ('CANCEL_REQUESTED', 'CANCELLED', 'FAILED_TERMINAL',
            'AGGREGATE_CANDIDATE_READY')
      BEGIN SELECT RAISE(ABORT, 'AGENT_MULTIBATCH_PLAN_BLOCKS_ATTEMPT'); END""")


def downgrade() -> None:
    bind = op.get_bind()
    populated = {
        name: int(bind.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar_one())
        for name in TABLES
    }
    if any(populated.values()):
        raise RuntimeError("AGENT_MULTIBATCH_AUDIT_ROWS_PRESENT")
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(bind, checkfirst=True)
