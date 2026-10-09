"""Versioned optional context and publication-independent comparisons."""
from alembic import op
from app.models import Base

revision = "20261009_01"
down_revision = "20260930_01"
branch_labels = None
depends_on = None
TABLES = ("brand_context_versions", "single_prompt_observation_comparisons")


def upgrade():
    Base.metadata.tables["single_prompt_sampling_schedules"].create(op.get_bind(), checkfirst=False)
    op.execute("CREATE UNIQUE INDEX uq_active_prompt_schedule ON single_prompt_sampling_schedules(project_id, prompt_id) WHERE status = 'ACTIVE'")
    for name in TABLES:
        Base.metadata.tables[name].create(op.get_bind(), checkfirst=False)
        for action in ("UPDATE", "DELETE"):
            op.execute(f"CREATE TRIGGER trg_{name}_no_{action.lower()} BEFORE {action} ON {name} BEGIN SELECT RAISE(ABORT, 'RELEASE_HISTORY_IMMUTABLE'); END")


def downgrade():
    Base.metadata.tables["single_prompt_sampling_schedules"].drop(op.get_bind())
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(op.get_bind())
