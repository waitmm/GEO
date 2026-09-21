#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/geo-platform/backend"
FRONTEND_DIR="$ROOT_DIR/geo-platform/frontend"
PYTHON_BIN="${PYTHON_BIN:-$BACKEND_DIR/.venv/bin/python}"
RELEASE_DB_PATH="${RELEASE_DB_PATH:-$BACKEND_DIR/geo_release.db}"
RELEASE_HOST="${RELEASE_HOST:-127.0.0.1}"
RELEASE_PORT="${RELEASE_PORT:-8020}"
WORKER_INTERVAL="${WORKER_INTERVAL:-2}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Release Python not found: $PYTHON_BIN" >&2
  exit 1
fi
if [[ ! -f "$FRONTEND_DIR/dist/index.html" ]]; then
  echo "Release frontend is not built. Run npm run build:release in geo-platform/frontend." >&2
  exit 1
fi
RELEASE_BUILD_MARKER="$FRONTEND_DIR/dist/geo-release-build.json"
if [[ ! -f "$RELEASE_BUILD_MARKER" ]] || ! grep -q '"release_first_slice":true' "$RELEASE_BUILD_MARKER"; then
  echo "Frontend dist is not a GEO release build. Run npm run build:release in geo-platform/frontend." >&2
  exit 1
fi

export GEO_RELEASE_DATABASE_URL="${GEO_RELEASE_DATABASE_URL:-sqlite:///$RELEASE_DB_PATH}"
export EVIDENCE_ARTIFACT_DIR="${EVIDENCE_ARTIFACT_DIR:-$BACKEND_DIR/artifacts/release-evidence}"

cd "$BACKEND_DIR"
"$PYTHON_BIN" -c 'from app.core.release_database import release_engine; from app.release_schema import validate_release_database; print(validate_release_database(release_engine))'

WORKER_PID=""
cleanup() {
  if [[ -n "$WORKER_PID" ]] && kill -0 "$WORKER_PID" 2>/dev/null; then
    kill "$WORKER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

"$PYTHON_BIN" scripts/release_worker.py --interval "$WORKER_INTERVAL" &
WORKER_PID="$!"

echo "GEO 1.0 release UI/API: http://$RELEASE_HOST:$RELEASE_PORT"
"$PYTHON_BIN" -m uvicorn app.release_main:app --host "$RELEASE_HOST" --port "$RELEASE_PORT" --workers 1
