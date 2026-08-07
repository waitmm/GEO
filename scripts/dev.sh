#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/geo-platform/backend"
FRONTEND_DIR="$ROOT_DIR/geo-platform/frontend"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-localhost}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_RELOAD="${BACKEND_RELOAD:-0}"
DAILY_SCHEDULER="${DAILY_SCHEDULER:-0}"
DAILY_SCHEDULER_EXECUTE_NOW="${DAILY_SCHEDULER_EXECUTE_NOW:-0}"
DAILY_SCHEDULER_PROJECT_ID="${DAILY_SCHEDULER_PROJECT_ID:-}"
DAILY_SCHEDULER_INTERVAL="${DAILY_SCHEDULER_INTERVAL:-300}"
MONITORING_WORKER="${MONITORING_WORKER:-0}"
MONITORING_WORKER_INTERVAL="${MONITORING_WORKER_INTERVAL:-10}"
MONITORING_WORKER_BATCH_SIZE="${MONITORING_WORKER_BATCH_SIZE:-1}"

BACKEND_PID=""
FRONTEND_PID=""
DAILY_SCHEDULER_PID=""
MONITORING_WORKER_PID=""

cleanup() {
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$DAILY_SCHEDULER_PID" ]] && kill -0 "$DAILY_SCHEDULER_PID" 2>/dev/null; then
    kill "$DAILY_SCHEDULER_PID" 2>/dev/null || true
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

UVICORN_ARGS=(app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT")
if [[ "$BACKEND_RELOAD" == "1" ]]; then
  UVICORN_ARGS+=(--reload)
fi

if port_is_open "$BACKEND_HOST" "$BACKEND_PORT"; then
  echo "GEO backend already listening: http://$BACKEND_HOST:$BACKEND_PORT"
else
  echo "Starting GEO backend: http://$BACKEND_HOST:$BACKEND_PORT"
  (
    cd "$BACKEND_DIR"
    "$PYTHON_BIN" -m uvicorn "${UVICORN_ARGS[@]}"
  ) &
  BACKEND_PID="$!"
fi

if port_is_open "$FRONTEND_HOST" "$FRONTEND_PORT"; then
  echo "GEO frontend already listening: http://$FRONTEND_HOST:$FRONTEND_PORT"
else
  echo "Starting GEO frontend: http://$FRONTEND_HOST:$FRONTEND_PORT"
  (
    cd "$FRONTEND_DIR"
    npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
  ) &
  FRONTEND_PID="$!"
fi

if [[ "$DAILY_SCHEDULER" == "1" ]]; then
  echo "Starting GEO daily scheduler: interval=${DAILY_SCHEDULER_INTERVAL}s"
  DAILY_ARGS=(scripts/queue_daily_schedules.py --loop --interval "$DAILY_SCHEDULER_INTERVAL")
  if [[ -n "$DAILY_SCHEDULER_PROJECT_ID" ]]; then
    DAILY_ARGS+=(--project-id "$DAILY_SCHEDULER_PROJECT_ID")
  fi
  if [[ "$DAILY_SCHEDULER_EXECUTE_NOW" == "1" ]]; then
    DAILY_ARGS+=(--execute-now)
  fi
  (
    cd "$BACKEND_DIR"
    "$PYTHON_BIN" "${DAILY_ARGS[@]}"
  ) &
  DAILY_SCHEDULER_PID="$!"
fi

if [[ "$MONITORING_WORKER" == "1" ]]; then
  echo "Starting GEO monitoring worker: interval=${MONITORING_WORKER_INTERVAL}s batch=${MONITORING_WORKER_BATCH_SIZE}"
  (
    cd "$BACKEND_DIR"
    "$PYTHON_BIN" scripts/worker_monitoring_loop.py --interval "$MONITORING_WORKER_INTERVAL" --batch-size "$MONITORING_WORKER_BATCH_SIZE"
  ) &
  MONITORING_WORKER_PID="$!"
fi

if [[ -z "$BACKEND_PID" && -z "$FRONTEND_PID" && -z "$DAILY_SCHEDULER_PID" && -z "$MONITORING_WORKER_PID" ]]; then
  echo "GEO dev stack is already running."
  exit 0
fi

echo "GEO dev stack is starting. Press Ctrl+C to stop started services."
PIDS=()
[[ -n "$BACKEND_PID" ]] && PIDS+=("$BACKEND_PID")
[[ -n "$FRONTEND_PID" ]] && PIDS+=("$FRONTEND_PID")
[[ -n "$DAILY_SCHEDULER_PID" ]] && PIDS+=("$DAILY_SCHEDULER_PID")
[[ -n "$MONITORING_WORKER_PID" ]] && PIDS+=("$MONITORING_WORKER_PID")
wait "${PIDS[@]}"
