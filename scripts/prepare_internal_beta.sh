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
install -m 600 "$SOURCE_DB" "$TARGET_DB"

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
