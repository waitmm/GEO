"""Isolated persistence for GEO Agent Experiment V1."""

from alembic import op

from app.models import Base


revision = "20261019_02"
down_revision = "20261019_01"
branch_labels = None
depends_on = None


TABLES = (
    "agent_experiment_runs",
    "agent_events",
    "agent_checkpoints",
    "agent_result_versions",
)


def upgrade() -> None:
    bind = op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=False)

    for name in ("agent_events", "agent_checkpoints", "agent_result_versions"):
        op.execute(f"""CREATE TRIGGER trg_{name}_no_update
          BEFORE UPDATE ON {name}
          BEGIN SELECT RAISE(ABORT, 'AGENT_EXPERIMENT_APPEND_ONLY'); END""")
        op.execute(f"""CREATE TRIGGER trg_{name}_no_delete
          BEFORE DELETE ON {name}
          BEGIN SELECT RAISE(ABORT, 'AGENT_EXPERIMENT_APPEND_ONLY'); END""")

    op.execute("""CREATE TRIGGER trg_agent_experiment_run_identity_immutable
      BEFORE UPDATE ON agent_experiment_runs
      WHEN OLD.run_id != NEW.run_id
        OR OLD.project_id != NEW.project_id
        OR OLD.prompt_id != NEW.prompt_id
        OR OLD.analysis_id != NEW.analysis_id
        OR OLD.context_id != NEW.context_id
        OR OLD.idempotency_key != NEW.idempotency_key
        OR OLD.requested_by != NEW.requested_by
        OR OLD.input_scope_json != NEW.input_scope_json
        OR OLD.input_scope_hash != NEW.input_scope_hash
        OR OLD.agent_execution_json != NEW.agent_execution_json
        OR OLD.agent_execution_hash != NEW.agent_execution_hash
        OR OLD.qualification_hash != NEW.qualification_hash
        OR OLD.budget_json != NEW.budget_json
      BEGIN SELECT RAISE(ABORT, 'AGENT_EXPERIMENT_IDENTITY_IMMUTABLE'); END""")
    op.execute("""CREATE TRIGGER trg_agent_experiment_run_no_delete
      BEFORE DELETE ON agent_experiment_runs
      BEGIN SELECT RAISE(ABORT, 'AGENT_EXPERIMENT_APPEND_ONLY'); END""")


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(bind)
