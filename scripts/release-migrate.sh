#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/geo-platform/backend"
PYTHON_BIN="${PYTHON_BIN:-$BACKEND_DIR/.venv/bin/python}"
RELEASE_DB_PATH="${RELEASE_DB_PATH:-$BACKEND_DIR/geo_release.db}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Release Python not found: $PYTHON_BIN" >&2
  exit 1
fi

export GEO_RELEASE_DATABASE_URL="${GEO_RELEASE_DATABASE_URL:-sqlite:///$RELEASE_DB_PATH}"
export EVIDENCE_ARTIFACT_DIR="${EVIDENCE_ARTIFACT_DIR:-$BACKEND_DIR/artifacts/release-evidence}"

cd "$BACKEND_DIR"
"$PYTHON_BIN" -c 'from app.core.release_sqlite import get_release_sqlite_dbapi; from app.release_schema import sqlite_has_wal_reset_fix; dbapi = get_release_sqlite_dbapi(); version = dbapi.sqlite_version; assert sqlite_has_wal_reset_fix(version), f"Unsafe release SQLite {version}; run backend/scripts/bootstrap_release_sqlite.py first"; print({"release_sqlite_version": version})'
"$PYTHON_BIN" -m alembic -c alembic.release.ini upgrade head
"$PYTHON_BIN" -c 'from app.core.release_database import release_engine; from app.release_schema import validate_release_database; print(validate_release_database(release_engine))'
