"""Add append-only MANUAL_IMPORT Run admission records."""

from alembic import op

from app.models import Base


revision = "20261021_01"
down_revision = "20261020_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["single_prompt_manual_imports"].create(bind, checkfirst=False)
    op.execute("""CREATE TRIGGER trg_single_prompt_manual_imports_no_update
      BEFORE UPDATE ON single_prompt_manual_imports
      BEGIN SELECT RAISE(ABORT, 'SINGLE_PROMPT_MANUAL_IMPORT_APPEND_ONLY'); END""")
    op.execute("""CREATE TRIGGER trg_single_prompt_manual_imports_no_delete
      BEFORE DELETE ON single_prompt_manual_imports
      BEGIN SELECT RAISE(ABORT, 'SINGLE_PROMPT_MANUAL_IMPORT_APPEND_ONLY'); END""")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_single_prompt_manual_imports_no_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_single_prompt_manual_imports_no_update")
    Base.metadata.tables["single_prompt_manual_imports"].drop(op.get_bind())
