"""Finite, analysis-owned automatic delivery tasks; no legacy runner dependencies."""
from alembic import op
from app.models import Base

revision = "20261009_02"
down_revision = "20261009_01"
branch_labels = None
depends_on = None


def upgrade():
    table = "single_prompt_optimization_tasks"
    Base.metadata.tables[table].create(op.get_bind(), checkfirst=False)
    op.execute(f"""CREATE TRIGGER trg_optimization_input_immutable BEFORE UPDATE ON {table}
        WHEN OLD.input_json != NEW.input_json OR OLD.input_hash != NEW.input_hash
          OR OLD.analysis_id != NEW.analysis_id OR OLD.context_id != NEW.context_id
          OR OLD.project_id != NEW.project_id OR OLD.prompt_id != NEW.prompt_id
          OR OLD.task_id != NEW.task_id OR OLD.idempotency_key != NEW.idempotency_key
        BEGIN SELECT RAISE(ABORT, 'OPTIMIZATION_INPUT_IMMUTABLE'); END""")


def downgrade():
    Base.metadata.tables["single_prompt_optimization_tasks"].drop(op.get_bind())
