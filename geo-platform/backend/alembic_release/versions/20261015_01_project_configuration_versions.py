"""Append-only project/brand configuration versions."""

import hashlib
import json
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

from app.models import Base


revision = "20261015_01"
down_revision = "20261010_02"
branch_labels = None
depends_on = None


def _json_list(value):
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def upgrade():
    name = "project_configuration_versions"
    connection = op.get_bind()
    table = Base.metadata.tables[name]
    table.create(connection, checkfirst=False)
    projects = connection.execute(sa.text("""SELECT id, name, brand_name, brand_aliases_json,
      website_url, industry, region, language, status FROM projects ORDER BY id""")).mappings()
    for project in projects:
        competitors = connection.execute(sa.text("""SELECT name, aliases_json, website_url
          FROM competitors WHERE project_id = :project_id ORDER BY id"""),
          {"project_id": project["id"]}).mappings().all()
        snapshot = {
            "project_id": project["id"], "name": project["name"], "brand_name": project["brand_name"],
            "brand_aliases": _json_list(project["brand_aliases_json"]),
            "website_url": project["website_url"], "industry": project["industry"],
            "region": project["region"], "language": project["language"], "status": project["status"],
            "competitors": [{"name": row["name"], "aliases": _json_list(row["aliases_json"]),
                "website_url": row["website_url"]} for row in competitors],
        }
        serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        connection.execute(table.insert().values(
            configuration_version_id=f"project-config-{uuid4()}", project_id=project["id"],
            version_number=1, snapshot_json=serialized,
            snapshot_hash=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        ))
    for action in ("UPDATE", "DELETE"):
        op.execute(f"""CREATE TRIGGER trg_project_configuration_no_{action.lower()}
          BEFORE {action} ON {name}
          BEGIN SELECT RAISE(ABORT, 'PROJECT_CONFIGURATION_IMMUTABLE'); END""")


def downgrade():
    Base.metadata.tables["project_configuration_versions"].drop(op.get_bind())
