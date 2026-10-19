"""Reconcile one isolated Agent Run projection from the shared budget ledger."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not args.database.is_file() or not args.ledger.is_file():
        raise SystemExit("database and ledger must be existing files")
    os.environ["GEO_RELEASE_DATABASE_URL"] = f"sqlite:///{args.database.resolve()}"
    from app.core.release_database import ReleaseSessionLocal
    from app.modules.agent_experiment.reconciliation import reconcile_agent_run_usage

    with ReleaseSessionLocal() as db:
        result = reconcile_agent_run_usage(
            db, ledger_path=args.ledger.resolve(), run_id=args.run_id,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
