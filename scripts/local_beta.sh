#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-status}"
APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BETA_HOME="${GEO_BETA_HOME:-$(cd "$APP_ROOT/.." && pwd)}"
BACKEND_DIR="$APP_ROOT/geo-platform/backend"
DATA_DIR="$BETA_HOME/data"
LOG_DIR="$BETA_HOME/logs"
RUN_DIR="$BETA_HOME/run"
DATABASE_PATH="${GEO_BETA_DATABASE_PATH:-$DATA_DIR/geo-beta.db}"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="${GEO_BETA_PORT:-8021}"
URL="http://$BACKEND_HOST:$BACKEND_PORT/"
PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
WORKER_PID_FILE="$RUN_DIR/worker.pid"
BACKEND_LOG="$LOG_DIR/backend.log"
WORKER_LOG="$LOG_DIR/worker.log"

usage() {
  echo "Usage: $0 {start|stop|restart|status|logs|open}"
}

require_runtime() {
  [[ -x "$PYTHON_BIN" ]] || { echo "Missing Python runtime: $PYTHON_BIN" >&2; exit 2; }
  [[ -f "$DATABASE_PATH" ]] || { echo "Missing Beta database: $DATABASE_PATH" >&2; exit 2; }
  [[ -f "$APP_ROOT/geo-platform/frontend/dist/index.html" ]] || {
    echo "Missing built frontend: $APP_ROOT/geo-platform/frontend/dist/index.html" >&2
    exit 2
  }
  mkdir -p "$DATA_DIR" "$LOG_DIR" "$RUN_DIR"
  chmod 700 "$DATA_DIR" "$LOG_DIR" "$RUN_DIR"
  chmod 600 "$DATABASE_PATH"
}

pid_matches() {
  local file="$1" marker="$2" pid command
  [[ -f "$file" ]] || return 1
  pid="$(tr -dc '0-9' < "$file")"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  [[ "$command" == *"$marker"* ]]
}

health_check() {
  "$PYTHON_BIN" - "$URL" <<'PY'
import json
import sys
from urllib.request import ProxyHandler, build_opener

with build_opener(ProxyHandler({})).open(sys.argv[1] + "api/health", timeout=2) as response:
    value = json.load(response)
if value.get("status") != "ok" or value.get("mode") != "release_1_0_first_slice":
    raise SystemExit(1)
if value.get("worker", {}).get("status") != "RUNNING":
    raise SystemExit(1)
print(json.dumps(value, ensure_ascii=False))
PY
}

stop_one() {
  local name="$1" file="$2" marker="$3" pid
  if ! pid_matches "$file" "$marker"; then
    rm -f "$file"
    echo "$name: not running"
    return
  fi
  pid="$(tr -dc '0-9' < "$file")"
  kill "$pid"
  for _ in $(seq 1 50); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.1
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL "$pid"
  fi
  rm -f "$file"
  echo "$name: stopped"
}

start() {
  require_runtime
  if pid_matches "$BACKEND_PID_FILE" "app.release_main:app" || pid_matches "$WORKER_PID_FILE" "scripts/release_worker.py"; then
    echo "GEO Beta is already running; use '$0 status'." >&2
    exit 1
  fi
  rm -f "$BACKEND_PID_FILE" "$WORKER_PID_FILE"
  local database_url="sqlite:///$DATABASE_PATH"
  (
    cd "$BACKEND_DIR"
    GEO_RELEASE_DATABASE_URL="$database_url" "$PYTHON_BIN" -m alembic -c alembic.release.ini upgrade head
    GEO_RELEASE_DATABASE_URL="$database_url" "$PYTHON_BIN" -c \
      'from app.core.release_database import release_engine; from app.release_schema import validate_release_database; validate_release_database(release_engine)'
  )
  (
    cd "$BACKEND_DIR"
    nohup env GEO_RELEASE_DATABASE_URL="$database_url" GEO_AGENT_BETA_DAILY_MODEL_CALLS="${GEO_AGENT_BETA_DAILY_MODEL_CALLS:-0}" \
      "$PYTHON_BIN" -m uvicorn app.release_main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --workers 1 \
      >>"$BACKEND_LOG" 2>&1 &
    echo "$!" > "$BACKEND_PID_FILE"
  )
  (
    cd "$BACKEND_DIR"
    nohup env GEO_RELEASE_DATABASE_URL="$database_url" GEO_AGENT_BETA_DAILY_MODEL_CALLS="${GEO_AGENT_BETA_DAILY_MODEL_CALLS:-0}" \
      "$PYTHON_BIN" scripts/release_worker.py --interval 10 >>"$WORKER_LOG" 2>&1 &
    echo "$!" > "$WORKER_PID_FILE"
  )
  for _ in $(seq 1 60); do
    if health_check >/dev/null 2>&1; then
      echo "GEO Beta is ready: $URL"
      echo "Daily model generation: ${GEO_AGENT_BETA_DAILY_MODEL_CALLS:-0} (0 means history-only)"
      return
    fi
    sleep 0.5
  done
  echo "GEO Beta failed to become healthy. Inspect $BACKEND_LOG and $WORKER_LOG" >&2
  exit 1
}

status() {
  require_runtime
  local failed=0
  if pid_matches "$BACKEND_PID_FILE" "app.release_main:app"; then
    echo "backend: running (pid $(cat "$BACKEND_PID_FILE"))"
  else
    echo "backend: stopped"
    failed=1
  fi
  if pid_matches "$WORKER_PID_FILE" "scripts/release_worker.py"; then
    echo "worker: running (pid $(cat "$WORKER_PID_FILE"))"
  else
    echo "worker: stopped"
    failed=1
  fi
  if (( failed == 0 )); then
    health_check
    echo "website: $URL"
  fi
  return "$failed"
}

case "$ACTION" in
  start) start ;;
  stop)
    stop_one "worker" "$WORKER_PID_FILE" "scripts/release_worker.py"
    stop_one "backend" "$BACKEND_PID_FILE" "app.release_main:app"
    ;;
  restart)
    "$0" stop
    "$0" start
    ;;
  status) status ;;
  logs)
    require_runtime
    tail -n 80 "$BACKEND_LOG" "$WORKER_LOG"
    ;;
  open)
    status >/dev/null 2>&1 || start
    open "$URL"
    ;;
  *) usage; exit 2 ;;
esac
