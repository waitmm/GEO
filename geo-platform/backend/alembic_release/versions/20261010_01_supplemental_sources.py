"""Explicit supplemental public acquisition, separate from answer citations."""
from alembic import op
from app.models import Base

revision = "20261010_01"
down_revision = "20261009_04"
branch_labels = None
depends_on = None


def upgrade():
    name = "supplemental_source_acquisitions"
    Base.metadata.tables[name].create(op.get_bind(), checkfirst=False)
    op.execute(f"""CREATE TRIGGER trg_supplemental_source_immutable BEFORE UPDATE ON {name}
      WHEN OLD.status IN ('READY','PARTIAL','FAILED','INTERRUPTED')
        OR OLD.project_id != NEW.project_id OR OLD.source_id != NEW.source_id
        OR OLD.requested_url != NEW.requested_url OR OLD.idempotency_key != NEW.idempotency_key
        OR OLD.request_json != NEW.request_json OR OLD.request_hash != NEW.request_hash
      BEGIN SELECT RAISE(ABORT, 'SUPPLEMENTAL_SOURCE_IMMUTABLE'); END""")
    op.execute(f"""CREATE TRIGGER trg_supplemental_source_no_delete BEFORE DELETE ON {name}
      BEGIN SELECT RAISE(ABORT, 'SUPPLEMENTAL_SOURCE_IMMUTABLE'); END""")


def downgrade():
    Base.metadata.tables["supplemental_source_acquisitions"].drop(op.get_bind())
