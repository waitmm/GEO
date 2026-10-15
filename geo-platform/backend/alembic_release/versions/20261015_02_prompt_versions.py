"""Append-only Prompt versions with historical V1 backfill."""

import hashlib
import json
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "20261015_02"
down_revision = "20261015_01"
branch_labels = None
depends_on = None


def _snapshot(prompt):
    return {
        "project_id": prompt["project_id"],
        "prompt_id": prompt["id"],
        "prompt_text": prompt["prompt_text"],
        "title": prompt["title"],
        "intent_type": prompt["intent_type"],
        "prompt_group": prompt["prompt_group"],
        "enabled": bool(prompt["enabled"]),
        "topic_id": prompt["topic_id"],
        "cluster_id": prompt["cluster_id"],
        "importance": prompt["importance"],
        "sample_count": prompt["sample_count"],
        "daily_tracking_enabled": bool(prompt["daily_tracking_enabled"]),
        "daily_schedule_time": prompt["daily_schedule_time"],
        "daily_sample_count": prompt["daily_sample_count"],
    }


def upgrade():
    name = "prompt_versions"
    connection = op.get_bind()
    op.create_table(
        name,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("prompt_version_id", sa.String(80), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("prompt_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("prompt_id", "version_number", name="uq_prompt_version"),
    )
    op.create_index("ix_prompt_versions_prompt_version_id", name, ["prompt_version_id"], unique=True)
    op.create_index("ix_prompt_versions_project_id", name, ["project_id"])
    op.create_index("ix_prompt_versions_prompt_id", name, ["prompt_id"])
    op.create_index("ix_prompt_versions_snapshot_hash", name, ["snapshot_hash"])
    op.create_index("ix_prompt_versions_project_prompt", name, ["project_id", "prompt_id"])
    table = sa.table(
        name,
        sa.column("prompt_version_id", sa.String(80)),
        sa.column("project_id", sa.Integer()),
        sa.column("prompt_id", sa.Integer()),
        sa.column("version_number", sa.Integer()),
        sa.column("snapshot_json", sa.Text()),
        sa.column("snapshot_hash", sa.String(64)),
    )
    prompts = connection.execute(sa.text("""SELECT id, project_id, topic_id, cluster_id, title,
      prompt_text, prompt_group, intent_type, importance, sample_count, daily_tracking_enabled,
      daily_schedule_time, daily_sample_count, enabled FROM prompts ORDER BY id""")).mappings()
    for prompt in prompts:
        snapshot = _snapshot(prompt)
        serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        connection.execute(table.insert().values(
            prompt_version_id=f"prompt-version-{uuid4()}",
            project_id=prompt["project_id"],
            prompt_id=prompt["id"],
            version_number=1,
            snapshot_json=serialized,
            snapshot_hash=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        ))
    for action in ("UPDATE", "DELETE"):
        op.execute(f"""CREATE TRIGGER trg_prompt_versions_no_{action.lower()}
          BEFORE {action} ON {name}
          BEGIN SELECT RAISE(ABORT, 'PROMPT_VERSION_IMMUTABLE'); END""")


def downgrade():
    op.drop_table("prompt_versions")
