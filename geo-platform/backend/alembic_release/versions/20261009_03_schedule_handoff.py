"""Bounded optional Optimize handoff on the existing sampling schedule."""
from alembic import op
import sqlalchemy as sa

revision = "20261009_03"
down_revision = "20261009_02"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("single_prompt_sampling_schedules", sa.Column("optimization_progress_json", sa.Text(), nullable=False, server_default="{}"))
    op.execute("""CREATE TRIGGER trg_sampling_plan_immutable BEFORE UPDATE ON single_prompt_sampling_schedules
        WHEN OLD.plan_json != NEW.plan_json OR OLD.plan_hash != NEW.plan_hash
          OR OLD.project_id != NEW.project_id OR OLD.prompt_id != NEW.prompt_id
          OR OLD.schedule_id != NEW.schedule_id
        BEGIN SELECT RAISE(ABORT, 'SAMPLING_PLAN_IMMUTABLE'); END""")


def downgrade():
    op.execute("DROP TRIGGER trg_sampling_plan_immutable")
    op.drop_column("single_prompt_sampling_schedules", "optimization_progress_json")
