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
CONFIG_DIR="$BETA_HOME/config"
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
PROXY_LABEL="com.geo.beta.proxy"
BACKEND_PLIST="$LAUNCHD_DIR/$BACKEND_LABEL.plist"
WORKER_PLIST="$LAUNCHD_DIR/$WORKER_LABEL.plist"
PROXY_PLIST="$LAUNCHD_DIR/$PROXY_LABEL.plist"
BACKEND_LOG="$LOG_DIR/backend.log"
WORKER_LOG="$LOG_DIR/worker.log"
PROXY_LOG="$LOG_DIR/proxy.log"
LAUNCH_DOMAIN="gui/$(id -u)"
MODEL_BUDGET_LEDGER="$DATA_DIR/internal-beta-model-budget.sqlite3"
WENXIN_PROFILE_DIR="$DATA_DIR/wenxin-profile"
STOPPED_MARKER="$RUN_DIR/services-stopped"
ACCESS_CONFIG="$CONFIG_DIR/release-access.json"
BACKEND_ENV="$CONFIG_DIR/backend.env"
TLS_CERT="$CONFIG_DIR/tls/server.crt"
TLS_KEY="$CONFIG_DIR/tls/server.key"

read_flag() {
  local path="$1" default="$2" value
  value="$default"
  [[ -f "$path" ]] && value="$(tr -d '[:space:]' < "$path")"
  [[ "$value" == "0" || "$value" == "1" ]] || {
    echo "Invalid flag in $path (expected 0 or 1)." >&2
    exit 2
  }
  echo "$value"
}

read_token() {
  local path="$1" pattern="$2" label="$3" value
  [[ -f "$path" ]] || { echo "Missing $label: $path" >&2; exit 2; }
  value="$(tr -d '[:space:]' < "$path")"
  [[ "$value" =~ $pattern ]] || { echo "Invalid $label in $path" >&2; exit 2; }
  echo "$value"
}

DAILY_MODEL_CALLS="$(read_flag "$CONFIG_DIR/daily-model-calls" 0)"
SCHEDULED_SAMPLING="$(read_flag "$CONFIG_DIR/scheduled-sampling-enabled" 0)"
LAN_ENABLED="$(read_flag "$CONFIG_DIR/lan-enabled" 0)"
LAN_PORT="${GEO_BETA_LAN_PORT:-8443}"
LAN_CIDR="${GEO_BETA_LAN_CIDR:-192.168.0.0/16}"
[[ -f "$CONFIG_DIR/lan-port" ]] && LAN_PORT="$(read_token "$CONFIG_DIR/lan-port" '^[0-9]{2,5}$' 'LAN port')"
[[ -f "$CONFIG_DIR/lan-cidr" ]] && LAN_CIDR="$(read_token "$CONFIG_DIR/lan-cidr" '^[0-9A-Fa-f:.]+/[0-9]{1,3}$' 'LAN CIDR')"
(( LAN_PORT >= 1024 && LAN_PORT <= 65535 )) || { echo "LAN port must be between 1024 and 65535." >&2; exit 2; }
MODEL_BUDGET_BATCH_ID=""
MODEL_PRICING_DATE=""
if [[ "$DAILY_MODEL_CALLS" == "1" ]]; then
  MODEL_BUDGET_BATCH_ID="$(read_token "$CONFIG_DIR/model-budget-batch-id" '^[A-Za-z0-9._:-]+$' 'model budget batch id')"
  MODEL_PRICING_DATE="$(read_token "$CONFIG_DIR/model-pricing-checked-at" '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' 'model pricing date')"
fi

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
  if [[ -f "$BACKEND_ENV" ]]; then
    [[ "$(stat -f '%Lp' "$BACKEND_ENV")" == "600" ]] || { echo "Backend env must be 0600: $BACKEND_ENV" >&2; exit 2; }
    ln -sfn "$BACKEND_ENV" "$BACKEND_DIR/.env"
  fi
  if [[ -f "$ACCESS_CONFIG" ]]; then
    [[ "$(stat -f '%Lp' "$ACCESS_CONFIG")" == "600" ]] || { echo "Access config must be 0600: $ACCESS_CONFIG" >&2; exit 2; }
  fi
  if [[ "$LAN_ENABLED" == "1" ]]; then
    [[ -f "$ACCESS_CONFIG" ]] || { echo "LAN access requires $ACCESS_CONFIG" >&2; exit 2; }
    [[ -f "$TLS_CERT" && -f "$TLS_KEY" ]] || { echo "LAN access requires TLS certificate and key." >&2; exit 2; }
    [[ "$(stat -f '%Lp' "$TLS_KEY")" == "600" ]] || { echo "TLS private key must be 0600." >&2; exit 2; }
    [[ -f "$APP_ROOT/scripts/launchd/$PROXY_LABEL.plist.in" ]] || { echo "Missing proxy launchd template." >&2; exit 2; }
  fi
  mkdir -p "$DATA_DIR" "$LOG_DIR" "$RUN_DIR" "$LAUNCHD_DIR" "$CONFIG_DIR" "$WENXIN_PROFILE_DIR"
  chmod 700 "$DATA_DIR" "$LOG_DIR" "$RUN_DIR" "$LAUNCHD_DIR" "$CONFIG_DIR" "$WENXIN_PROFILE_DIR"
  chmod 600 "$DATABASE_PATH"
}

render_plists() {
  local database_url="sqlite:///$DATABASE_PATH"
  local access_config_value=""
  [[ -f "$ACCESS_CONFIG" ]] && access_config_value="$ACCESS_CONFIG"
  sed -e "s|@@PYTHON_BIN@@|$PYTHON_BIN|g" \
      -e "s|@@BACKEND_DIR@@|$BACKEND_DIR|g" \
      -e "s|@@DATABASE_URL@@|$database_url|g" \
      -e "s|@@ACCESS_CONFIG@@|$access_config_value|g" \
      -e "s|@@PORT@@|$BACKEND_PORT|g" \
      -e "s|@@DAILY_MODEL_CALLS@@|$DAILY_MODEL_CALLS|g" \
      -e "s|@@MODEL_BUDGET_LEDGER@@|$MODEL_BUDGET_LEDGER|g" \
      -e "s|@@MODEL_BUDGET_BATCH_ID@@|$MODEL_BUDGET_BATCH_ID|g" \
      -e "s|@@MODEL_PRICING_DATE@@|$MODEL_PRICING_DATE|g" \
      -e "s|@@SCHEDULED_SAMPLING@@|$SCHEDULED_SAMPLING|g" \
      -e "s|@@WENXIN_PROFILE_DIR@@|$WENXIN_PROFILE_DIR|g" \
      -e "s|@@LOG_PATH@@|$BACKEND_LOG|g" \
      "$APP_ROOT/scripts/launchd/$BACKEND_LABEL.plist.in" > "$BACKEND_PLIST"
  sed -e "s|@@PYTHON_BIN@@|$PYTHON_BIN|g" \
      -e "s|@@BACKEND_DIR@@|$BACKEND_DIR|g" \
      -e "s|@@DATABASE_URL@@|$database_url|g" \
      -e "s|@@ACCESS_CONFIG@@|$access_config_value|g" \
      -e "s|@@DAILY_MODEL_CALLS@@|$DAILY_MODEL_CALLS|g" \
      -e "s|@@MODEL_BUDGET_LEDGER@@|$MODEL_BUDGET_LEDGER|g" \
      -e "s|@@MODEL_BUDGET_BATCH_ID@@|$MODEL_BUDGET_BATCH_ID|g" \
      -e "s|@@MODEL_PRICING_DATE@@|$MODEL_PRICING_DATE|g" \
      -e "s|@@SCHEDULED_SAMPLING@@|$SCHEDULED_SAMPLING|g" \
      -e "s|@@WENXIN_PROFILE_DIR@@|$WENXIN_PROFILE_DIR|g" \
      -e "s|@@LOG_PATH@@|$WORKER_LOG|g" \
      "$APP_ROOT/scripts/launchd/$WORKER_LABEL.plist.in" > "$WORKER_PLIST"
  chmod 600 "$BACKEND_PLIST" "$WORKER_PLIST"
  if [[ "$LAN_ENABLED" == "1" ]]; then
    sed -e "s|@@PYTHON_BIN@@|$PYTHON_BIN|g" \
        -e "s|@@PROXY_SCRIPT@@|$BACKEND_DIR/scripts/lan_https_proxy.py|g" \
        -e "s|@@BACKEND_DIR@@|$BACKEND_DIR|g" \
        -e "s|@@PORT@@|$BACKEND_PORT|g" \
        -e "s|@@LAN_PORT@@|$LAN_PORT|g" \
        -e "s|@@LAN_CIDR@@|$LAN_CIDR|g" \
        -e "s|@@TLS_CERT@@|$TLS_CERT|g" \
        -e "s|@@TLS_KEY@@|$TLS_KEY|g" \
        -e "s|@@LOG_PATH@@|$PROXY_LOG|g" \
        "$APP_ROOT/scripts/launchd/$PROXY_LABEL.plist.in" > "$PROXY_PLIST"
    chmod 600 "$PROXY_PLIST"
  fi
}

service_loaded() { launchctl print "$LAUNCH_DOMAIN/$1" >/dev/null 2>&1; }
service_pid() { launchctl print "$LAUNCH_DOMAIN/$1" 2>/dev/null | awk '/pid = / { print $3; exit }'; }

assert_service_owned_by_home() {
  local label="$1" definition expected_database expected_plist actual_database actual_plist
  service_loaded "$label" || return 0
  definition="$(launchctl print "$LAUNCH_DOMAIN/$label" 2>/dev/null)"
  expected_database="sqlite:///$DATABASE_PATH"
  expected_plist="$LAUNCHD_DIR/$label.plist"
  actual_database="$(awk -F ' => ' '/^[[:space:]]*GEO_RELEASE_DATABASE_URL => / {print $2; exit}' <<<"$definition")"
  actual_plist="$(awk -F ' = ' '/^[[:space:]]*path = / {print $2; exit}' <<<"$definition")"
  if [[ "$label" == "$PROXY_LABEL" ]]; then
    expected_database=""
  fi
  if [[ "$actual_database" != "$expected_database" || "$actual_plist" != "$expected_plist" ]]; then
    echo "$label belongs to another GEO_BETA_HOME; refusing to inspect, restart, or stop it." >&2
    return 1
  fi
}

assert_all_service_ownership() {
  local label
  for label in "$PROXY_LABEL" "$WORKER_LABEL" "$BACKEND_LABEL"; do
    service_loaded "$label" && assert_service_owned_by_home "$label"
  done
  return 0
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

bootstrap_or_restart() {
  local label="$1" plist="$2"
  if service_loaded "$label"; then
    assert_service_owned_by_home "$label"
    local old_pid
    old_pid="$(service_pid "$label")"
    # kickstart reuses the already loaded definition and would ignore a newly
    # rendered plist. Reload so path, port and safety settings are authoritative.
    launchctl bootout "$LAUNCH_DOMAIN/$label"
    # bootout removes the launchd registration before the old process has
    # necessarily released its listener. Starting immediately can return EIO
    # or create a new process that cannot bind the port.
    if [[ -n "$old_pid" ]]; then
      for _ in $(seq 1 100); do
        kill -0 "$old_pid" >/dev/null 2>&1 || break
        sleep 0.1
      done
      if kill -0 "$old_pid" >/dev/null 2>&1; then
        echo "$label did not stop within 10 seconds; refusing to overlap services." >&2
        return 1
      fi
    fi
  fi
  launchctl bootstrap "$LAUNCH_DOMAIN" "$plist"
}

start() {
  require_runtime
  assert_all_service_ownership
  # Upgrade/start is a deployment boundary. Stop both writers before the
  # preflight or migration; never migrate underneath a running API/worker.
  stop_service "$PROXY_LABEL" "HTTPS proxy"
  stop_service "$WORKER_LABEL" "worker"
  stop_service "$BACKEND_LABEL" "backend"
  printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$STOPPED_MARKER"
  chmod 600 "$STOPPED_MARKER"
  (
    cd "$BACKEND_DIR"
    "$PYTHON_BIN" scripts/m1_beta_ops.py preflight --database "$DATABASE_PATH"
  )
  local database_url="sqlite:///$DATABASE_PATH"
  (
    cd "$BACKEND_DIR"
    GEO_RELEASE_DATABASE_URL="$database_url" "$PYTHON_BIN" -m alembic -c alembic.release.ini upgrade head
    GEO_RELEASE_DATABASE_URL="$database_url" "$PYTHON_BIN" -c \
      'from app.core.release_database import release_engine; from app.release_schema import validate_release_database; validate_release_database(release_engine)'
  )
  if [[ "$DAILY_MODEL_CALLS" == "1" ]]; then
    (
      cd "$BACKEND_DIR"
      GEO_AGENT_BETA_DAILY_MODEL_CALLS=1 \
      GEO_AGENT_BETA_BUDGET_LEDGER_PATH="$MODEL_BUDGET_LEDGER" \
      GEO_AGENT_BETA_BUDGET_BATCH_ID="$MODEL_BUDGET_BATCH_ID" \
      GEO_AGENT_BETA_BUDGET_PRICING_CHECKED_AT="$MODEL_PRICING_DATE" \
      "$PYTHON_BIN" -c \
        'from app.services.internal_beta_model_budget import initialize_daily_budget; initialize_daily_budget()'
    )
  fi
  render_plists
  rm -f "$STOPPED_MARKER"
  bootstrap_or_restart "$BACKEND_LABEL" "$BACKEND_PLIST"
  bootstrap_or_restart "$WORKER_LABEL" "$WORKER_PLIST"
  # A cold launchd start on the local Mac can spend more than 30 seconds
  # importing the release app. Keep polling instead of reporting a false
  # deployment failure while both supervised processes are still starting.
  for _ in $(seq 1 240); do
    if health_check >/dev/null 2>&1; then
      if [[ "$LAN_ENABLED" == "1" ]]; then
        bootstrap_or_restart "$PROXY_LABEL" "$PROXY_PLIST"
      fi
      echo "GEO Beta is ready: $URL"
      echo "AI generation: $DAILY_MODEL_CALLS (server-managed policy)"
      echo "Scheduled sampling: $SCHEDULED_SAMPLING (single concurrency; collector retries: 0)"
      [[ "$LAN_ENABLED" == "1" ]] && echo "LAN HTTPS: enabled on port $LAN_PORT for $LAN_CIDR"
      return
    fi
    sleep 0.5
  done
  echo "GEO Beta failed to become healthy. Inspect $BACKEND_LOG and $WORKER_LOG" >&2
  exit 1
}

stop_service() {
  local label="$1" name="$2" old_pid=""
  if service_loaded "$label"; then
    assert_service_owned_by_home "$label"
    old_pid="$(service_pid "$label")"
    launchctl bootout "$LAUNCH_DOMAIN/$label"
    if [[ -n "$old_pid" ]]; then
      for _ in $(seq 1 100); do
        kill -0 "$old_pid" >/dev/null 2>&1 || break
        sleep 0.1
      done
      if kill -0 "$old_pid" >/dev/null 2>&1; then
        echo "$name did not stop within 10 seconds; refusing deployment operations." >&2
        return 1
      fi
    fi
    echo "$name: stopped"
  else
    echo "$name: not running"
  fi
}

status() {
  require_runtime
  local failed=0 pid
  if service_loaded "$BACKEND_LABEL"; then
    if ! assert_service_owned_by_home "$BACKEND_LABEL"; then
      failed=1
    else
    pid="$(service_pid "$BACKEND_LABEL")"
    if [[ -n "$pid" ]]; then
      echo "backend: running (pid $pid)"
    else
      echo "backend: loaded but not running"
      failed=1
    fi
    fi
  else
    echo "backend: stopped"
    failed=1
  fi
  if service_loaded "$WORKER_LABEL"; then
    if ! assert_service_owned_by_home "$WORKER_LABEL"; then
      failed=1
    else
    pid="$(service_pid "$WORKER_LABEL")"
    if [[ -n "$pid" ]]; then
      echo "worker: running (pid $pid)"
    else
      echo "worker: loaded but not running"
      failed=1
    fi
    fi
  else
    echo "worker: stopped"
    failed=1
  fi
  if [[ "$LAN_ENABLED" == "1" ]]; then
    if service_loaded "$PROXY_LABEL" && assert_service_owned_by_home "$PROXY_LABEL"; then
      pid="$(service_pid "$PROXY_LABEL")"
      if [[ -n "$pid" ]]; then
        echo "HTTPS proxy: running (pid $pid)"
      else
        echo "HTTPS proxy: loaded but not running"
        failed=1
      fi
    else
      echo "HTTPS proxy: stopped"
      failed=1
    fi
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
    assert_all_service_ownership
    stop_service "$PROXY_LABEL" "HTTPS proxy"
    stop_service "$WORKER_LABEL" "worker"
    stop_service "$BACKEND_LABEL" "backend"
    printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$STOPPED_MARKER"
    chmod 600 "$STOPPED_MARKER"
    ;;
  restart)
    "$0" stop
    "$0" start
    ;;
  status) status ;;
  logs)
    require_runtime
    tail -n 80 "$BACKEND_LOG" "$WORKER_LOG" "$PROXY_LOG"
    ;;
  open)
    status >/dev/null 2>&1 || start
    open "$URL"
    ;;
  *) usage; exit 2 ;;
esac
