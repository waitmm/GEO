"""Add effective_payload columns + backfill existing strategy candidates.

effective_payload_json: single executable truth for all execution paths.
effective_payload_version: version marker for merge contract.
effective_validation_status: validation status of the effective payload.
effective_validated_at: timestamp of last effective validation.

Backfill logic (frozen effective_payload.v1 merge):
- If human_edited_payload is empty → effective = structured_payload
- If human_edited_payload has content → deterministic merge per v1 contract
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "20260808_01"
down_revision = "20260807_01"
branch_labels = None
depends_on = None


EFFECTIVE_PAYLOAD_VERSION = "effective_payload.v1"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if table_name in _tables() and column.name not in _columns(table_name):
        op.add_column(table_name, column)


# Frozen deterministic merge for backfill (effective_payload.v1 contract).
# Scalar: edit overrides. Dict: recursive. List: edit replaces entirely.
def _frozen_deterministic_merge(base: dict, delta: dict) -> dict:
    """Frozen merge logic for effective_payload.v1 backfill."""
    result = dict(base)
    for key, val in delta.items():
        if key not in result:
            result[key] = val
        elif isinstance(val, dict) and isinstance(result[key], dict):
            result[key] = _frozen_deterministic_merge(result[key], val)
        elif isinstance(val, list) and isinstance(result[key], list):
            result[key] = list(val)  # complete replacement
        elif val is None:
            result[key] = None  # explicit clear
        else:
            result[key] = val  # scalar override
    return result


def upgrade() -> None:
    table = "optimization_strategy_candidates"
    if table not in _tables():
        return

    _add_column_if_missing(table, sa.Column("effective_payload_json", sa.Text(), nullable=False, server_default="{}"))
    _add_column_if_missing(table, sa.Column("effective_payload_version", sa.String(length=40), nullable=False, server_default=""))
    _add_column_if_missing(table, sa.Column("effective_validation_status", sa.String(length=60), nullable=False, server_default="PENDING"))
    _add_column_if_missing(table, sa.Column("effective_validated_at", sa.DateTime(), nullable=True))

    op.execute("CREATE INDEX IF NOT EXISTS ix_strategy_candidates_effective_validation_status ON optimization_strategy_candidates (effective_validation_status)")

    # Backfill existing rows
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, structured_payload_json, human_edited_payload_json FROM optimization_strategy_candidates"
    )).fetchall()

    backfilled = 0
    for row in rows:
        try:
            structured = json.loads(row[1] or "{}")
            edited = json.loads(row[2] or "{}")
        except (json.JSONDecodeError, TypeError):
            structured = {}
            edited = {}

        if edited:
            effective = _frozen_deterministic_merge(structured, edited)
        else:
            effective = structured

        conn.execute(
            sa.text(
                "UPDATE optimization_strategy_candidates SET effective_payload_json = :payload, effective_payload_version = :version, effective_validation_status = :status WHERE id = :id"
            ),
            {
                "payload": json.dumps(effective, ensure_ascii=False),
                "version": EFFECTIVE_PAYLOAD_VERSION,
                "status": "BACKFILLED_UNVERIFIED",
                "id": row[0],
            },
        )
        backfilled += 1

    print(f"effective_payload backfill: {backfilled} rows → {EFFECTIVE_PAYLOAD_VERSION}")


def downgrade() -> None:
    table = "optimization_strategy_candidates"
    if table not in _tables():
        return
    cols = _columns(table)
    for col_name in ["effective_payload_json", "effective_payload_version", "effective_validation_status", "effective_validated_at"]:
        if col_name in cols:
            op.drop_column(table, col_name)
