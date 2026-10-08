#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/geo-platform/backend"
FRONTEND_DIR="$ROOT_DIR/geo-platform/frontend"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8021}"
FRONTEND_HOST="${FRONTEND_HOST:-localhost}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_RELOAD="${BACKEND_RELOAD:-0}"
DAILY_SCHEDULER="${DAILY_SCHEDULER:-0}"
MONITORING_WORKER="${MONITORING_WORKER:-0}"
MONITORING_WORKER_INTERVAL="${MONITORING_WORKER_INTERVAL:-10}"

BACKEND_PID=""
FRONTEND_PID=""
MONITORING_WORKER_PID=""

cleanup() {
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$MONITORING_WORKER_PID" ]] && kill -0 "$MONITORING_WORKER_PID" 2>/dev/null; then
    kill "$MONITORING_WORKER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  echo "Python not found. Create backend/.venv or install python3." >&2
  exit 1
fi

port_is_open() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$2" -sTCP:LISTEN >/dev/null 2>&1 && return 0
  fi
  "$PYTHON_BIN" -c 'import socket, sys
hosts = [sys.argv[1], "localhost", "127.0.0.1", "::1"]
port = int(sys.argv[2])
for host in dict.fromkeys(hosts):
    family = socket.AF_INET6 if ":" in host else socket.AF_UNSPEC
    try:
        infos = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
    except OSError:
        continue
    for info in infos:
        sock = socket.socket(info[0], info[1], info[2])
        sock.settimeout(0.3)
        try:
            if sock.connect_ex(info[4]) == 0:
                raise SystemExit(0)
        finally:
            sock.close()
raise SystemExit(1)
' "$1" "$2"
}

if ! command -v npm >/dev/null 2>&1; then
  if [[ -s "$HOME/.nvm/nvm.sh" ]]; then
    # shellcheck source=/dev/null
    source "$HOME/.nvm/nvm.sh"
    if [[ -f "$FRONTEND_DIR/.nvmrc" ]]; then
      nvm use >/dev/null
    elif nvm ls 24.14.0 >/dev/null 2>&1; then
      nvm use 24.14.0 >/dev/null
    elif nvm ls 18.20.8 >/dev/null 2>&1; then
      nvm use 18.20.8 >/dev/null
    fi
  fi
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm not found. Install Node.js or load nvm before running this script." >&2
  exit 1
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "frontend/node_modules not found. Run npm install in geo-platform/frontend first." >&2
  exit 1
fi

if [[ "$DAILY_SCHEDULER" == "1" ]]; then
  echo "Legacy daily scheduler is not part of the release dev stack." >&2
  exit 1
fi

UVICORN_ARGS=(app.release_main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT")
if [[ "$BACKEND_RELOAD" == "1" ]]; then
  UVICORN_ARGS+=(--reload)
fi

if port_is_open "$BACKEND_HOST" "$BACKEND_PORT"; then
  echo "Checking existing GEO backend: http://$BACKEND_HOST:$BACKEND_PORT"
else
  echo "Starting GEO backend: http://$BACKEND_HOST:$BACKEND_PORT"
  (
    cd "$BACKEND_DIR"
    "$PYTHON_BIN" -m uvicorn "${UVICORN_ARGS[@]}"
  ) &
  BACKEND_PID="$!"
fi

# A listening socket alone is not proof of a compatible release service.
"$PYTHON_BIN" - "$BACKEND_HOST" "$BACKEND_PORT" <<'PY'
import json
import sys
import time
from urllib.request import ProxyHandler, build_opener

url = f"http://{sys.argv[1]}:{sys.argv[2]}/api/health"
local_open = build_opener(ProxyHandler({})).open
for attempt in range(30):
    try:
        with local_open(url, timeout=1) as response:
            health = json.load(response)
    except (OSError, ValueError):
        time.sleep(.5)
        continue
    if health.get("mode") != "release_1_0_first_slice":
        raise SystemExit(f"Backend at {url} is not the release API; stop the conflicting service first.")
    break
else:
    raise SystemExit(f"Release backend did not become ready: {url}. Check migration/version errors.")
PY

export GEO_API_PROXY_TARGET="http://$BACKEND_HOST:$BACKEND_PORT"
if port_is_open "$FRONTEND_HOST" "$FRONTEND_PORT"; then
  "$PYTHON_BIN" - "http://$FRONTEND_HOST:$FRONTEND_PORT" "$GEO_API_PROXY_TARGET" <<'PY'
import json
import sys
from urllib.request import ProxyHandler, build_opener

try:
    with build_opener(ProxyHandler({})).open(sys.argv[1] + "/__geo_dev_config", timeout=3) as response:
        config = json.load(response)
except (OSError, ValueError):
    raise SystemExit("Existing frontend is not the release dev server; restart it with npm run dev.")
if config != {"release": True, "api_target": sys.argv[2]}:
    raise SystemExit("Existing frontend mode or API target differs; restart it with the release settings.")
PY
  echo "GEO frontend already listening: http://$FRONTEND_HOST:$FRONTEND_PORT"
else
  echo "Starting GEO frontend: http://$FRONTEND_HOST:$FRONTEND_PORT"
  (
    cd "$FRONTEND_DIR"
    npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
  ) &
  FRONTEND_PID="$!"
fi

if [[ "$MONITORING_WORKER" == "1" ]]; then
  echo "Starting GEO release worker: interval=${MONITORING_WORKER_INTERVAL}s"
  (
    cd "$BACKEND_DIR"
    "$PYTHON_BIN" scripts/release_worker.py --interval "$MONITORING_WORKER_INTERVAL"
  ) &
  MONITORING_WORKER_PID="$!"
fi

if [[ -z "$BACKEND_PID" && -z "$FRONTEND_PID" && -z "$MONITORING_WORKER_PID" ]]; then
  echo "GEO dev stack is already running."
  exit 0
fi

echo "GEO dev stack is starting. Press Ctrl+C to stop started services."
PIDS=()
[[ -n "$BACKEND_PID" ]] && PIDS+=("$BACKEND_PID")
[[ -n "$FRONTEND_PID" ]] && PIDS+=("$FRONTEND_PID")
[[ -n "$MONITORING_WORKER_PID" ]] && PIDS+=("$MONITORING_WORKER_PID")
wait "${PIDS[@]}"
