#!/usr/bin/env bash
set -euo pipefail
umask 077

ACTION="${1:-status}"
APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BETA_HOME="${GEO_BETA_HOME:-$(cd "$APP_ROOT/.." && pwd)}"
BACKEND_DIR="$APP_ROOT/geo-platform/backend"
DATA_DIR="$BETA_HOME/data"
LOG_DIR="$BETA_HOME/logs"
RUN_DIR="$BETA_HOME/run"
LAUNCHD_DIR="$BETA_HOME/launchd"
DATABASE_PATH="${GEO_BETA_DATABASE_PATH:-$DATA_DIR/geo-beta.db}"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="${GEO_BETA_PORT:-8032}"
URL="http://$BACKEND_HOST:$BACKEND_PORT/"
# launchd may reject an executable reached through a symlinked parent directory
# with EX_CONFIG before the process starts. Resolve the venv bin directory while
# retaining the venv interpreter path (and therefore its installed packages).
PYTHON_BIN="$(cd "$BACKEND_DIR/.venv/bin" 2>/dev/null && pwd -P)/python"
BACKEND_LABEL="com.geo.beta.backend"
WORKER_LABEL="com.geo.beta.worker"
BACKEND_PLIST="$LAUNCHD_DIR/$BACKEND_LABEL.plist"
WORKER_PLIST="$LAUNCHD_DIR/$WORKER_LABEL.plist"
BACKEND_LOG="$LOG_DIR/backend.log"
WORKER_LOG="$LOG_DIR/worker.log"
LAUNCH_DOMAIN="gui/$(id -u)"

usage() { echo "Usage: $0 {start|stop|restart|status|logs|open}"; }

require_runtime() {
  [[ "$(uname -s)" == "Darwin" ]] || { echo "This local controller requires macOS launchd." >&2; exit 2; }
  command -v launchctl >/dev/null 2>&1 || { echo "launchctl is unavailable." >&2; exit 2; }
  [[ -x "$PYTHON_BIN" ]] || { echo "Missing Python runtime: $PYTHON_BIN" >&2; exit 2; }
  [[ -f "$DATABASE_PATH" ]] || { echo "Missing Beta database: $DATABASE_PATH" >&2; exit 2; }
  [[ -f "$APP_ROOT/geo-platform/frontend/dist/index.html" ]] || {
    echo "Missing built frontend: $APP_ROOT/geo-platform/frontend/dist/index.html" >&2
    exit 2
  }
  [[ -f "$APP_ROOT/scripts/launchd/$BACKEND_LABEL.plist.in" ]] || { echo "Missing launchd template." >&2; exit 2; }
  mkdir -p "$DATA_DIR" "$LOG_DIR" "$RUN_DIR" "$LAUNCHD_DIR"
  chmod 700 "$DATA_DIR" "$LOG_DIR" "$RUN_DIR" "$LAUNCHD_DIR"
  chmod 600 "$DATABASE_PATH"
}

render_plists() {
  local database_url="sqlite:///$DATABASE_PATH"
  sed -e "s|@@PYTHON_BIN@@|$PYTHON_BIN|g" \
      -e "s|@@BACKEND_DIR@@|$BACKEND_DIR|g" \
      -e "s|@@DATABASE_URL@@|$database_url|g" \
      -e "s|@@PORT@@|$BACKEND_PORT|g" \
      -e "s|@@LOG_PATH@@|$BACKEND_LOG|g" \
      "$APP_ROOT/scripts/launchd/$BACKEND_LABEL.plist.in" > "$BACKEND_PLIST"
  sed -e "s|@@PYTHON_BIN@@|$PYTHON_BIN|g" \
      -e "s|@@BACKEND_DIR@@|$BACKEND_DIR|g" \
      -e "s|@@DATABASE_URL@@|$database_url|g" \
      -e "s|@@LOG_PATH@@|$WORKER_LOG|g" \
      "$APP_ROOT/scripts/launchd/$WORKER_LABEL.plist.in" > "$WORKER_PLIST"
  chmod 600 "$BACKEND_PLIST" "$WORKER_PLIST"
}

service_loaded() { launchctl print "$LAUNCH_DOMAIN/$1" >/dev/null 2>&1; }
service_pid() { launchctl print "$LAUNCH_DOMAIN/$1" 2>/dev/null | awk '/pid = / { print $3; exit }'; }

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

bootstrap_or_restart() {
  local label="$1" plist="$2"
  if service_loaded "$label"; then
    # kickstart reuses the already loaded definition and would ignore a newly
    # rendered plist. Reload so path, port and safety settings are authoritative.
    launchctl bootout "$LAUNCH_DOMAIN/$label"
  fi
  launchctl bootstrap "$LAUNCH_DOMAIN" "$plist"
}

start() {
  require_runtime
  local database_url="sqlite:///$DATABASE_PATH"
  (
    cd "$BACKEND_DIR"
    GEO_RELEASE_DATABASE_URL="$database_url" "$PYTHON_BIN" -m alembic -c alembic.release.ini upgrade head
    GEO_RELEASE_DATABASE_URL="$database_url" "$PYTHON_BIN" -c \
      'from app.core.release_database import release_engine; from app.release_schema import validate_release_database; validate_release_database(release_engine)'
  )
  render_plists
  bootstrap_or_restart "$BACKEND_LABEL" "$BACKEND_PLIST"
  bootstrap_or_restart "$WORKER_LABEL" "$WORKER_PLIST"
  for _ in $(seq 1 60); do
    if health_check >/dev/null 2>&1; then
      echo "GEO Beta is ready: $URL"
      echo "Daily model generation: 0 (history-only; deployment authorization is not configured)"
      return
    fi
    sleep 0.5
  done
  echo "GEO Beta failed to become healthy. Inspect $BACKEND_LOG and $WORKER_LOG" >&2
  exit 1
}

stop_service() {
  local label="$1" name="$2"
  if service_loaded "$label"; then
    launchctl bootout "$LAUNCH_DOMAIN/$label"
    echo "$name: stopped"
  else
    echo "$name: not running"
  fi
}

status() {
  require_runtime
  local failed=0 pid
  if service_loaded "$BACKEND_LABEL"; then
    pid="$(service_pid "$BACKEND_LABEL")"
    if [[ -n "$pid" ]]; then
      echo "backend: running (pid $pid)"
    else
      echo "backend: loaded but not running"
      failed=1
    fi
  else
    echo "backend: stopped"
    failed=1
  fi
  if service_loaded "$WORKER_LABEL"; then
    pid="$(service_pid "$WORKER_LABEL")"
    if [[ -n "$pid" ]]; then
      echo "worker: running (pid $pid)"
    else
      echo "worker: loaded but not running"
      failed=1
    fi
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
    require_runtime
    stop_service "$WORKER_LABEL" "worker"
    stop_service "$BACKEND_LABEL" "backend"
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
