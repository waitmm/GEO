#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPS="$ROOT_DIR/geo-platform/backend/scripts/m1_beta_ops.py"
ACTION="${1:-help}"
shift || true

usage() {
  cat <<'EOF'
Usage:
  m1_beta_ops.sh install HOME PREPARED_SOURCE RELEASE_ID SOURCE_SHA SCHEMA_REVISION
  m1_beta_ops.sh start|stop|status HOME
  m1_beta_ops.sh backup HOME OUTPUT
  m1_beta_ops.sh restore BACKUP NEW_HOME
  m1_beta_ops.sh upgrade HOME PREPARED_SOURCE RELEASE_ID SOURCE_SHA SCHEMA_REVISION
  m1_beta_ops.sh rollback HOME BACKUP RELEASE_ID

Install/upgrade sources must be offline prepared releases containing the backend
virtualenv and release frontend build. Upgrade and rollback leave services
stopped; run start explicitly after reviewing their reports. New/restored
installs always have model calls and scheduled sampling disabled.
EOF
}

case "$ACTION" in
  install)
    [[ "$#" -eq 5 ]] || { usage; exit 2; }
    python3 "$OPS" install --home "$1" --source "$2" --release-id "$3" --source-sha "$4" --schema-revision "$5"
    ;;
  start|stop|status)
    [[ "$#" -eq 1 ]] || { usage; exit 2; }
    python3 "$OPS" runtime --home "$1" "$ACTION"
    ;;
  backup)
    [[ "$#" -eq 2 ]] || { usage; exit 2; }
    python3 "$OPS" quiesce --home "$1"
    python3 "$OPS" backup --home "$1" --output "$2"
    ;;
  restore)
    [[ "$#" -eq 2 ]] || { usage; exit 2; }
    python3 "$OPS" restore --backup "$1" --target-home "$2"
    ;;
  upgrade)
    [[ "$#" -eq 5 ]] || { usage; exit 2; }
    # Use the prepared candidate controller so an older installed controller
    # cannot falsely attest that its writer processes have exited.
    GEO_BETA_HOME="$1" "$2/scripts/local_beta.sh" stop
    python3 "$OPS" upgrade --home "$1" --source "$2" --release-id "$3" --source-sha "$4" --schema-revision "$5"
    ;;
  rollback)
    [[ "$#" -eq 3 ]] || { usage; exit 2; }
    python3 "$OPS" quiesce --home "$1"
    python3 "$OPS" rollback --home "$1" --backup "$2" --release-id "$3"
    ;;
  help|-h|--help) usage ;;
  *) usage; exit 2 ;;
esac
