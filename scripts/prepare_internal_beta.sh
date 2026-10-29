#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "Usage: $0 /absolute/path/source.db /absolute/path/beta.db" >&2
  exit 2
fi

SOURCE_DB="$1"
TARGET_DB="$2"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/geo-platform/backend"
FRONTEND_DIR="$ROOT_DIR/geo-platform/frontend"

if [[ "$SOURCE_DB" != /* || "$TARGET_DB" != /* ]]; then
  echo "Source and target database paths must be absolute." >&2
  exit 2
fi
if [[ ! -f "$SOURCE_DB" ]]; then
  echo "Source database does not exist: $SOURCE_DB" >&2
  exit 2
fi
if [[ -e "$TARGET_DB" ]]; then
  echo "Target already exists; refusing to overwrite: $TARGET_DB" >&2
  exit 2
fi
if [[ ! -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  echo "Backend virtual environment is missing." >&2
  exit 2
fi
if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "Frontend dependencies are missing." >&2
  exit 2
fi

mkdir -p "$(dirname "$TARGET_DB")"
# A direct file copy is not a consistent backup of a live SQLite WAL database.
# Use SQLite's online backup API and validate the resulting standalone image.
"$BACKEND_DIR/.venv/bin/python" - "$SOURCE_DB" "$TARGET_DB" <<'PY'
from pathlib import Path
import sqlite3
import sys

source, target = map(lambda value: Path(value).resolve(), sys.argv[1:])
with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as origin, sqlite3.connect(target) as destination:
    origin.backup(destination)
with sqlite3.connect(f"file:{target}?mode=ro", uri=True) as database:
    if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("Prepared SQLite backup failed integrity_check")
    if database.execute("PRAGMA foreign_key_check").fetchall():
        raise SystemExit("Prepared SQLite backup failed foreign_key_check")
target.chmod(0o600)
PY

(
  cd "$BACKEND_DIR"
  GEO_RELEASE_DATABASE_URL="sqlite:///$TARGET_DB" .venv/bin/python -m alembic -c alembic.release.ini upgrade head
  GEO_RELEASE_DATABASE_URL="sqlite:///$TARGET_DB" .venv/bin/python -c \
    'from app.core.release_database import release_engine; from app.release_schema import validate_release_database; print(validate_release_database(release_engine))'
)
(
  cd "$FRONTEND_DIR"
  npm run build:release
)

echo "M1 Beta package prepared: $TARGET_DB"
echo "Daily model calls remain disabled unless GEO_AGENT_BETA_DAILY_MODEL_CALLS=1 is explicitly configured."
