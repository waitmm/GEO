"""Versioned optional context and publication-independent comparisons."""
from alembic import op
from app.models import Base
import sqlalchemy as sa

revision = "20261009_01"
down_revision = "20260930_01"
branch_labels = None
depends_on = None
TABLES = ("brand_context_versions", "single_prompt_observation_comparisons")


def upgrade():
    # Pin the initial table: later ORM columns belong to their own migrations.
    op.create_table("single_prompt_sampling_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("schedule_id", sa.String(80), nullable=False, unique=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("prompt_id", sa.Integer(), sa.ForeignKey("prompts.id"), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("local_time", sa.String(5), nullable=False),
        sa.Column("next_due_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("remaining_attempts", sa.Integer(), nullable=False),
        sa.Column("authorization_note", sa.Text(), nullable=False),
        sa.Column("last_analysis_id", sa.String(80), nullable=False),
        sa.Column("pause_reason", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    for column in ("project_id", "prompt_id", "next_due_at"):
        op.create_index(f"ix_single_prompt_sampling_schedules_{column}", "single_prompt_sampling_schedules", [column])
    op.execute("CREATE UNIQUE INDEX uq_active_prompt_schedule ON single_prompt_sampling_schedules(project_id, prompt_id) WHERE status = 'ACTIVE'")
    for name in TABLES:
        Base.metadata.tables[name].create(op.get_bind(), checkfirst=False)
        for action in ("UPDATE", "DELETE"):
            op.execute(f"CREATE TRIGGER trg_{name}_no_{action.lower()} BEFORE {action} ON {name} BEGIN SELECT RAISE(ABORT, 'RELEASE_HISTORY_IMMUTABLE'); END")


def downgrade():
    Base.metadata.tables["single_prompt_sampling_schedules"].drop(op.get_bind())
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(op.get_bind())
