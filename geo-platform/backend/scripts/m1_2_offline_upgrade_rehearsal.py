"""Rehearse an M1.1 -> M1.2 data upgrade on an isolated SQLite copy.

The source home is opened read-only.  SQLite's online backup API captures the
database (and any committed WAL frames) into a temporary stopped home before
the normal backup/restore helpers are exercised.  No runtime service is
started and no external capability is enabled.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from typing import Any

from m1_beta_ops import backup_home, inspect_database, restore_backup, rollback_release


M1_2_REVISIONS = ("20261030_01", "20261030_02")
EXTERNAL_CAPABILITY_FILES = (
    "daily-model-calls", "scheduled-sampling-enabled", "lan-enabled",
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=lambda item: {"bytes_sha256": hashlib.sha256(item).hexdigest()}
        if isinstance(item, bytes) else str(item),
    ).encode("utf-8")


def _table_fingerprints(database: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as db:
        tables = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version' ORDER BY name"
        )]
        for table in tables:
            quoted = table.replace('"', '""')
            columns = [row[1] for row in db.execute(f'PRAGMA table_info("{quoted}")')]
            digest = hashlib.sha256()
            count = 0
            try:
                rows = db.execute(f'SELECT * FROM "{quoted}" ORDER BY rowid')
            except sqlite3.OperationalError:
                order = ",".join(f'"{column.replace(chr(34), chr(34) * 2)}"' for column in columns)
                rows = db.execute(f'SELECT * FROM "{quoted}" ORDER BY {order}')
            for raw in rows:
                values = list(raw)
                if table == "single_prompt_prepared_source_snapshots" and "artifact_path" in columns:
                    values[columns.index("artifact_path")] = "<RELOCATED_PATH>"
                digest.update(_canonical(values))
                count += 1
            result[table] = {
                "columns": columns, "row_count": count, "rows_sha256": digest.hexdigest(),
            }
    return result


def _trigger_fingerprint(database: Path, *, exclude_new_tables: bool = False) -> str:
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as db:
        rows = db.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master "
            "WHERE type='trigger' AND sql IS NOT NULL ORDER BY name"
        ).fetchall()
    if exclude_new_tables:
        rows = [row for row in rows if row[1] not in {
            "agent_draft_artifacts", "agent_draft_artifact_versions",
            "agent_draft_artifact_feedback", "agent_draft_artifact_regenerations",
        }]
    return hashlib.sha256(_canonical(rows)).hexdigest()


def _logical_database_hash(database: Path) -> str:
    """Hash logical rows/schema; a raw main-file hash omits uncheckpointed WAL."""
    state = inspect_database(database)
    return hashlib.sha256(_canonical({
        "revision": state["revision"],
        "tables": _table_fingerprints(database),
        "triggers": _trigger_fingerprint(database),
    })).hexdigest()


def _draft_schema_summary(database: Path) -> dict[str, Any]:
    names = (
        "agent_draft_artifact_versions", "agent_draft_artifact_feedback",
        "agent_draft_artifact_regenerations",
    )
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as db:
        existing = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        tables = {}
        for name in names:
            if name not in existing:
                continue
            escaped = name.replace('"', '""')
            tables[name] = {
                "columns": [row[1] for row in db.execute(f'PRAGMA table_info("{escaped}")')],
                "row_count": db.execute(f'SELECT count(*) FROM "{escaped}"').fetchone()[0],
                "trigger_count": db.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
                    (name,),
                ).fetchone()[0],
            }
    return tables


def _online_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True) as origin, \
            sqlite3.connect(destination) as target:
        origin.backup(target)


def _prepare_stopped_copy(source_home: Path, target_home: Path) -> None:
    for name in ("data", "evidence", "config", "logs", "run", "backups"):
        (target_home / name).mkdir(parents=True, mode=0o700, exist_ok=True)
    _online_backup(source_home / "data" / "geo-beta.db", target_home / "data" / "geo-beta.db")
    ledger = source_home / "data" / "internal-beta-model-budget.sqlite3"
    if ledger.is_file():
        _online_backup(ledger, target_home / "data" / ledger.name)
    version = (source_home / "VERSION").read_text().strip()
    (target_home / "VERSION").write_text(version + "\n")
    (target_home / "run" / "services-stopped").write_text(
        datetime.now(timezone.utc).isoformat() + "\n")
    for name in EXTERNAL_CAPABILITY_FILES:
        (target_home / "config" / name).write_text("0\n")


def _run_migration(backend: Path, database: Path, revision: str) -> dict[str, Any]:
    environment = {
        **os.environ,
        "GEO_RELEASE_DATABASE_URL": f"sqlite:///{database.resolve()}",
        "GEO_AGENT_BETA_DAILY_MODEL_CALLS": "0",
        "GEO_SCHEDULED_SAMPLING_ENABLED": "0",
    }
    process = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.release.ini", "upgrade", revision],
        cwd=backend, env=environment, capture_output=True, text=True,
    )
    if process.returncode:
        raise RuntimeError(f"MIGRATION_FAILED:{revision}:" + (process.stderr or process.stdout)[-2000:])
    state = inspect_database(database)
    if state["revision"] != revision or state["integrity"] != "ok" \
            or state["foreign_key_violations"]:
        raise RuntimeError(f"MIGRATION_VALIDATION_FAILED:{revision}")
    return {
        "revision": revision,
        "logical_database_sha256": _logical_database_hash(database),
        "draft_schema": _draft_schema_summary(database),
        "migration_log_sha256": hashlib.sha256(
            (process.stdout + process.stderr).encode("utf-8")).hexdigest(),
    }


def _legacy_readback(backend: Path, database: Path) -> dict[str, Any]:
    environment = {
        **os.environ,
        "PYTHONPATH": str(backend),
        "GEO_RELEASE_DATABASE_URL": f"sqlite:///{database.resolve()}",
    }
    code = """
import json
from app.core.release_database import ReleaseSessionLocal
from app.models import AgentResultVersion
from app.modules.agent_experiment.service import result_view
db=ReleaseSessionLocal()
try:
    rows=db.query(AgentResultVersion).order_by(AgentResultVersion.id).all()
    views=[result_view(row, db=db) for row in rows]
    print(json.dumps({
      'result_count':len(rows),
      'legacy_single_draft_count':sum(view['legacy_single_draft'] for view in views),
      'child_artifact_count':sum(len(view['draft_artifacts']) for view in views),
      'result_versions':[row.result_version for row in rows],
      'result_hashes':[row.result_hash for row in rows],
      'deliverable_lengths':[len(row.deliverable_markdown or '') for row in rows],
    }, sort_keys=True))
finally:
    db.close()
"""
    process = subprocess.run(
        [sys.executable, "-c", code], cwd=backend, env=environment,
        capture_output=True, text=True,
    )
    if process.returncode:
        raise RuntimeError("LEGACY_READBACK_FAILED:" + process.stderr[-2000:])
    return json.loads(process.stdout.strip().splitlines()[-1])


def _write_release_manifest(home: Path, release_id: str, source_sha: str, revision: str) -> None:
    release = home / "releases" / release_id
    release.mkdir(parents=True, exist_ok=True)
    (release / "RELEASE_MANIFEST.json").write_text(json.dumps({
        "format": "geo-m1-release.v1", "release_id": release_id,
        "source_sha": source_sha, "schema_revision": revision,
        "external_calls": 0,
    }, ensure_ascii=False, indent=2) + "\n")


def _candidate_sha(backend: Path) -> str:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=backend,
        capture_output=True, text=True,
    )
    value = process.stdout.strip()
    if process.returncode or not value or len(value) != 40:
        raise RuntimeError("CANDIDATE_GIT_SHA_UNAVAILABLE")
    return value


def rehearse(source_home: Path, output: Path) -> dict[str, Any]:
    source_home, output = source_home.resolve(), output.resolve()
    if output.exists():
        raise ValueError(f"OUTPUT_EXISTS:{output}")
    output.mkdir(parents=True, mode=0o700)
    stopped_copy = output / "m1.1-consistent-copy"
    _prepare_stopped_copy(source_home, stopped_copy)
    source_state = inspect_database(stopped_copy / "data" / "geo-beta.db")
    if source_state["active_work"]:
        raise ValueError("SOURCE_COPY_HAS_ACTIVE_WORK")
    if source_state["revision"] != "20261022_01":
        raise ValueError(f"SOURCE_REVISION_NOT_M1_1:{source_state['revision']}")

    pre_backup = output / "m1.1-pre-upgrade-backup"
    backup_home(stopped_copy, pre_backup)
    upgrade_home = output / "m1.2-upgrade-home"
    restore_backup(pre_backup, upgrade_home)
    database = upgrade_home / "data" / "geo-beta.db"
    before = _table_fingerprints(database)
    old_trigger_hash = _trigger_fingerprint(database)

    backend = Path(__file__).resolve().parents[1]
    migrations = [_run_migration(backend, database, revision) for revision in M1_2_REVISIONS]
    after = _table_fingerprints(database)
    changed_old_tables = {
        name: {"before": value, "after": after.get(name)}
        for name, value in before.items() if after.get(name) != value
    }
    if changed_old_tables:
        raise RuntimeError("PREEXISTING_TABLE_CHANGED:" + ",".join(changed_old_tables))
    if _trigger_fingerprint(database, exclude_new_tables=True) != old_trigger_hash:
        raise RuntimeError("PREEXISTING_TRIGGER_CHANGED")
    legacy = _legacy_readback(backend, database)
    if legacy["child_artifact_count"] != 0 \
            or legacy["legacy_single_draft_count"] != legacy["result_count"]:
        raise RuntimeError("LEGACY_SINGLE_DRAFT_READBACK_FAILED")

    post_backup = output / "m1.2-post-upgrade-backup"
    backup_home(upgrade_home, post_backup)
    restored_home = output / "m1.2-restored-home"
    restore_backup(post_backup, restored_home)
    restored = _table_fingerprints(restored_home / "data" / "geo-beta.db")
    if restored != after:
        raise RuntimeError("POST_UPGRADE_RESTORE_FINGERPRINT_MISMATCH")
    restored_legacy = _legacy_readback(backend, restored_home / "data" / "geo-beta.db")
    if restored_legacy != legacy:
        raise RuntimeError("POST_UPGRADE_LEGACY_READBACK_MISMATCH")

    source_version = (stopped_copy / "VERSION").read_text().strip()
    old_release_id, _, old_source_sha = source_version.partition(" / ")
    if not old_source_sha:
        raise ValueError("SOURCE_VERSION_IDENTITY_INCOMPLETE")
    candidate_sha = _candidate_sha(backend)
    new_release_id = f"geo-m1.2-offline-{candidate_sha[:8]}"
    _write_release_manifest(upgrade_home, old_release_id, old_source_sha, "20261022_01")
    _write_release_manifest(
        upgrade_home, new_release_id, candidate_sha, "20261030_02")
    current = upgrade_home / "current"
    current.symlink_to(Path("releases") / new_release_id, target_is_directory=True)
    (upgrade_home / "VERSION").write_text(f"{new_release_id} / {candidate_sha}\n")
    rollback = rollback_release(upgrade_home, pre_backup, old_release_id)
    rolled_back_database = upgrade_home / "data" / "geo-beta.db"
    rolled_back = _table_fingerprints(rolled_back_database)
    if rolled_back != before:
        raise RuntimeError("ROLLBACK_FINGERPRINT_MISMATCH")
    if inspect_database(rolled_back_database)["revision"] != "20261022_01":
        raise RuntimeError("ROLLBACK_REVISION_MISMATCH")
    retained_revision = inspect_database(
        Path(rollback["retained_pre_rollback_state"]) / "data" / "geo-beta.db"
    )["revision"]
    if retained_revision != "20261030_02":
        raise RuntimeError("ROLLBACK_RETAINED_STATE_MISSING")
    audit_locations = rollback.get("audit_ledger_locations") or []
    if not audit_locations or not all(Path(row["path"]).is_file() for row in audit_locations):
        raise RuntimeError("ROLLBACK_AUDIT_LEDGER_NOT_TRACEABLE")

    explicit_counts = {
        name: before.get(name, {"row_count": 0})["row_count"] for name in (
            "agent_experiment_runs", "agent_result_versions", "agent_result_feedback",
            "single_prompt_prepared_source_snapshots",
        )
    }
    report = {
        "status": "PASS_M1_1_TO_M1_2_OFFLINE_REHEARSAL",
        "source_home": str(source_home),
        "candidate_source_sha": candidate_sha,
        "source_database": source_state,
        "migrations": migrations,
        "preexisting_table_count": len(before),
        "preexisting_tables_changed": [],
        "dependency_counts": explicit_counts,
        "legacy_single_draft_readback": legacy,
        "post_upgrade_backup_revision": inspect_database(post_backup / "database.db")["revision"],
        "post_upgrade_restore_revision": inspect_database(
            restored_home / "data" / "geo-beta.db")["revision"],
        "rollback_revision": inspect_database(rolled_back_database)["revision"],
        "rollback_retained_revision": retained_revision,
        "rollback_audit_ledger_locations": audit_locations,
        "rollback_report": rollback,
        "external_calls": 0,
    }
    (output / "M1_1_TO_M1_2_REHEARSAL_REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-home", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(rehearse(args.source_home, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
