"""Append-only human fact corrections; original facts and results stay intact."""
from alembic import op
from app.models import Base

revision = "20261010_02"
down_revision = "20261010_01"
branch_labels = None
depends_on = None


def upgrade():
    name = "single_prompt_truth_corrections"
    Base.metadata.tables[name].create(op.get_bind(), checkfirst=False)
    for action in ("UPDATE", "DELETE"):
        op.execute(f"""CREATE TRIGGER trg_truth_correction_no_{action.lower()} BEFORE {action} ON {name}
          BEGIN SELECT RAISE(ABORT, 'TRUTH_CORRECTION_IMMUTABLE'); END""")


def downgrade():
    Base.metadata.tables["single_prompt_truth_corrections"].drop(op.get_bind())
