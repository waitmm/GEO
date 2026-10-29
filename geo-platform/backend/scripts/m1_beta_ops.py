"""Fail-closed lifecycle helpers for the M1 local Beta.

The commands in this module deliberately operate on an explicit ``--home`` and
never discover a database from application defaults.  Backup uses SQLite's
online backup API so a WAL database is copied as one consistent image.  Restore
always targets a new home and relocates immutable prepared-source artifacts;
it never overwrites a live database.

This is deployment plumbing, not an authorization mechanism.  New installs and
restores force model generation and scheduled sampling off.  An operator must
separately authorize those capabilities after deployment validation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from typing import Any


SAFE_RELEASE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
CONFIG_ALLOWLIST = (
    "daily-model-calls",
    "scheduled-sampling-enabled",
    "model-budget-batch-id",
    "model-pricing-checked-at",
)
ACTIVE_STATUSES = {
    "queued", "running", "retrying", "evidence_queued", "auto_fetch_queued",
    "reserved_in_flight",
}
# These tables are consumed by release_worker.py.  Refusing a deploy while any
# row is active is intentionally broader than attempting to infer which one may
# call a provider: an upgrade must not resume unknown work under changed code.
WORK_QUEUE_TABLES = (
    "browser_monitor_tasks",
    "single_prompt_analyses",
    "single_prompt_optimization_tasks",
    "agent_experiment_runs",
    "supplemental_source_acquisitions",
    "single_prompt_source_preparations",
    "single_prompt_diagnosis_executions",
    "single_prompt_citation_contribution_executions",
    "single_prompt_qualification_critic_executions",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)


def _connect_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def _tables(db: sqlite3.Connection) -> set[str]:
    return {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    quoted = table.replace('"', '""')
    return {row[1] for row in db.execute(f'PRAGMA table_info("{quoted}")')}


def _revision(db: sqlite3.Connection) -> str:
    if "alembic_version" not in _tables(db):
        return "UNKNOWN"
    row = db.execute("SELECT version_num FROM alembic_version").fetchone()
    return str(row[0]) if row else "UNKNOWN"


def queue_preflight(database: Path) -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    with _connect_ro(database) as db:
        existing = _tables(db)
        for table in WORK_QUEUE_TABLES:
            if table not in existing or "status" not in _columns(db, table):
                continue
            quoted = table.replace('"', '""')
            rows = db.execute(
                f'SELECT rowid, status FROM "{quoted}" '
                "WHERE lower(status) IN (%s) ORDER BY rowid" % ",".join("?" for _ in ACTIVE_STATUSES),
                tuple(sorted(ACTIVE_STATUSES)),
            ).fetchall()
            active.extend({"table": table, "rowid": rowid, "status": status} for rowid, status in rows)
    return active


def inspect_database(database: Path) -> dict[str, Any]:
    database = database.resolve()
    if not database.is_file():
        raise ValueError(f"DATABASE_NOT_FOUND:{database}")
    with _connect_ro(database) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
        journal = db.execute("PRAGMA journal_mode").fetchone()[0]
        revision = _revision(db)
    return {
        "database": str(database),
        "sha256": _hash_file(database),
        "revision": revision,
        "integrity": integrity,
        "foreign_key_violations": len(foreign_keys),
        "journal_mode": journal,
        "active_work": queue_preflight(database),
    }


def _iter_files(root: Path):
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"SYMLINK_NOT_ARCHIVED:{path}")
        if path.is_file():
            yield path


def _copy_tree_with_hashes(source: Path, destination: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not source.exists():
        return rows
    for path in _iter_files(source):
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        before = _hash_file(path)
        shutil.copyfile(path, target)
        if _hash_file(path) != before or _hash_file(target) != before:
            raise ValueError(f"FILE_CHANGED_DURING_BACKUP:{path}")
        rows.append({"path": relative.as_posix(), "sha256": before})
    return rows


def _prepared_sources(database: Path) -> list[dict[str, Any]]:
    with _connect_ro(database) as db:
        if "single_prompt_prepared_source_snapshots" not in _tables(db):
            return []
        columns = _columns(db, "single_prompt_prepared_source_snapshots")
        required = {"snapshot_id", "artifact_path", "artifact_hash"}
        if not required <= columns:
            raise ValueError("PREPARED_SOURCE_SCHEMA_INCOMPLETE")
        selected = "snapshot_id, artifact_path, artifact_hash"
        if "clean_text" in columns:
            selected += ", clean_text"
        rows = db.execute(
            f"SELECT {selected} FROM single_prompt_prepared_source_snapshots ORDER BY snapshot_id"
        ).fetchall()
    result = []
    for row in rows:
        snapshot_id, raw_path, expected = row[:3]
        text = row[3] if len(row) > 3 else None
        source = Path(raw_path)
        if not source.is_absolute():
            source = database.parent / source
        if not source.is_file():
            raise ValueError(f"PREPARED_SOURCE_MISSING:{snapshot_id}")
        actual = _hash_file(source)
        if actual != expected or (text is not None and _hash_text(text) != expected):
            raise ValueError(f"PREPARED_SOURCE_HASH_MISMATCH:{snapshot_id}")
        result.append({
            "snapshot_id": snapshot_id,
            "original_path": str(source.resolve()),
            "artifact_hash": expected,
        })
    return result


def backup_home(home: Path, output: Path) -> dict[str, Any]:
    home, output = home.resolve(), output.resolve()
    database = home / "data" / "geo-beta.db"
    if not (home / "run" / "services-stopped").is_file():
        raise ValueError("SERVICES_STOP_CONFIRMATION_REQUIRED")
    if output.exists():
        raise ValueError(f"BACKUP_DESTINATION_EXISTS:{output}")
    state = inspect_database(database)
    if state["integrity"] != "ok" or state["foreign_key_violations"]:
        raise ValueError("SOURCE_DATABASE_INTEGRITY_FAILED")
    if state["active_work"]:
        raise ValueError("ACTIVE_WORK_REQUIRES_QUARANTINE:" + json.dumps(state["active_work"], ensure_ascii=False))

    output.mkdir(parents=True, mode=0o700)
    destination = output / "database.db"
    # SQLite backup is consistent across the main DB and any committed WAL
    # frames.  Copying the .db file directly would not provide this guarantee.
    with _connect_ro(database) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    destination.chmod(0o600)
    restored_state = inspect_database(destination)
    if restored_state["integrity"] != "ok" or restored_state["foreign_key_violations"]:
        raise ValueError("BACKUP_DATABASE_INTEGRITY_FAILED")

    source_rows = _prepared_sources(database)
    archived_sources: list[dict[str, Any]] = []
    source_dir = output / "prepared-sources"
    source_dir.mkdir(mode=0o700)
    for index, row in enumerate(source_rows):
        relative = f"prepared-sources/{index:06d}.txt"
        shutil.copyfile(row["original_path"], output / relative)
        if _hash_file(output / relative) != row["artifact_hash"]:
            raise ValueError(f"ARCHIVED_SOURCE_HASH_MISMATCH:{row['snapshot_id']}")
        archived_sources.append({**row, "backup_path": relative})

    evidence_files = _copy_tree_with_hashes(home / "evidence", output / "evidence")
    config: dict[str, str] = {}
    for name in CONFIG_ALLOWLIST:
        path = home / "config" / name
        if path.is_file():
            config[name] = path.read_text().strip()
    version = (home / "VERSION").read_text().strip() if (home / "VERSION").is_file() else "UNKNOWN"
    manifest = {
        "format": "geo-m1-backup.v1",
        "created_at": _utc_now(),
        "source_home": str(home),
        "source_version": version,
        "database": restored_state,
        "prepared_sources": archived_sources,
        "evidence_files": evidence_files,
        "config_audit": config,
        "restore_policy": {
            "target_must_be_new": True,
            "prepared_source_paths_are_relocated": True,
            "daily_model_calls": 0,
            "scheduled_sampling": 0,
            "credentials_and_browser_profiles": "EXCLUDED",
        },
        "external_calls": 0,
    }
    _write_json(output / "manifest.json", manifest)
    verify_backup(output)
    return manifest


def verify_backup(directory: Path) -> dict[str, Any]:
    directory = directory.resolve()
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("format") != "geo-m1-backup.v1":
        raise ValueError("BACKUP_FORMAT_UNSUPPORTED")
    database = directory / "database.db"
    state = inspect_database(database)
    if state["sha256"] != manifest["database"]["sha256"]:
        raise ValueError("BACKUP_DATABASE_HASH_MISMATCH")
    for row in manifest.get("prepared_sources", []):
        path = directory / row["backup_path"]
        if not path.is_file() or _hash_file(path) != row["artifact_hash"]:
            raise ValueError(f"BACKUP_SOURCE_HASH_MISMATCH:{row['snapshot_id']}")
    for row in manifest.get("evidence_files", []):
        path = directory / "evidence" / row["path"]
        if not path.is_file() or _hash_file(path) != row["sha256"]:
            raise ValueError(f"BACKUP_EVIDENCE_HASH_MISMATCH:{row['path']}")
    return {
        "status": "PASS",
        "revision": state["revision"],
        "database_sha256": state["sha256"],
        "prepared_source_count": len(manifest.get("prepared_sources", [])),
        "evidence_file_count": len(manifest.get("evidence_files", [])),
        "active_work_count": len(state["active_work"]),
    }


def restore_backup(directory: Path, target_home: Path) -> dict[str, Any]:
    directory, target_home = directory.resolve(), target_home.resolve()
    verification = verify_backup(directory)
    if target_home.exists() and any(target_home.iterdir()):
        raise ValueError(f"RESTORE_TARGET_NOT_EMPTY:{target_home}")
    target_home.mkdir(parents=True, mode=0o700, exist_ok=True)
    for name in ("data", "evidence", "config", "logs", "run", "backups"):
        (target_home / name).mkdir(mode=0o700)
    (target_home / "run" / "services-stopped").write_text(_utc_now() + "\n")
    (target_home / "run" / "services-stopped").chmod(0o600)

    destination = target_home / "data" / "geo-beta.db"
    with _connect_ro(directory / "database.db") as source, sqlite3.connect(destination) as target:
        source.backup(target)
    destination.chmod(0o600)
    manifest = json.loads((directory / "manifest.json").read_text())
    if (directory / "evidence").exists():
        shutil.copytree(directory / "evidence", target_home / "evidence", dirs_exist_ok=True)

    relocated_dir = target_home / "evidence" / "prepared-sources-restored"
    relocated_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    with sqlite3.connect(destination) as db:
        for index, row in enumerate(manifest.get("prepared_sources", [])):
            suffix = Path(row["original_path"]).suffix or ".txt"
            target = relocated_dir / f"{index:06d}-{row['artifact_hash'][:16]}{suffix}"
            shutil.copyfile(directory / row["backup_path"], target)
            if _hash_file(target) != row["artifact_hash"]:
                raise ValueError(f"RESTORED_SOURCE_HASH_MISMATCH:{row['snapshot_id']}")
            cursor = db.execute(
                "UPDATE single_prompt_prepared_source_snapshots SET artifact_path=? "
                "WHERE snapshot_id=? AND artifact_hash=?",
                (str(target), row["snapshot_id"], row["artifact_hash"]),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"RESTORED_SOURCE_BINDING_MISMATCH:{row['snapshot_id']}")
        db.commit()

    # Capability flags are intentionally not restored as authorization.
    (target_home / "config" / "daily-model-calls").write_text("0\n")
    (target_home / "config" / "scheduled-sampling-enabled").write_text("0\n")
    for path in (target_home / "config").iterdir():
        path.chmod(0o600)
    (target_home / "VERSION").write_text(manifest.get("source_version", "UNKNOWN") + "\n")
    (target_home / "VERSION").chmod(0o600)

    state = inspect_database(destination)
    if state["integrity"] != "ok" or state["foreign_key_violations"] or state["active_work"]:
        raise ValueError("RESTORED_DATABASE_PREFLIGHT_FAILED")
    report = {
        "status": "PASS_RESTORED_TO_NEW_HOME",
        "source_backup": str(directory),
        "target_home": str(target_home),
        "database": state,
        "backup_verification": verification,
        "relocated_prepared_sources": len(manifest.get("prepared_sources", [])),
        "daily_model_calls": 0,
        "scheduled_sampling": 0,
        "external_calls": 0,
    }
    _write_json(target_home / "RESTORE_REPORT.json", report)
    return report


def _controller(home: Path) -> Path:
    current = home / "current"
    script = current / "scripts" / "local_beta.sh"
    if not script.is_file():
        raise ValueError(f"RUNTIME_CONTROLLER_NOT_FOUND:{script}")
    return script


def runtime(home: Path, action: str) -> int:
    environment = {**os.environ, "GEO_BETA_HOME": str(home.resolve())}
    return subprocess.run([str(_controller(home)), action], env=environment).returncode


def quiesce(home: Path) -> dict[str, str]:
    """Stop through even an older controller, then create the deploy marker."""
    home = home.resolve()
    controller = _controller(home)
    controller_text = controller.read_text()
    if "services-stopped" not in controller_text or "did not stop within 10 seconds" not in controller_text:
        raise ValueError("LEGACY_CONTROLLER_CANNOT_CONFIRM_QUIESCENCE")
    code = runtime(home, "stop")
    if code:
        raise ValueError(f"RUNTIME_STOP_FAILED:{code}")
    marker = home / "run" / "services-stopped"
    marker.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    marker.write_text(_utc_now() + "\n")
    marker.chmod(0o600)
    return {"status": "PASS_SERVICES_STOPPED", "marker": str(marker)}


def _copy_release(source: Path, destination: Path) -> None:
    excluded = {".git", "data", "evidence", "logs", "run", "backups", "__pycache__"}

    def ignore(_directory: str, names: list[str]):
        return {name for name in names if name in excluded or name.endswith((".pyc", ".pyo"))}

    shutil.copytree(source, destination, symlinks=False, ignore=ignore)


def prepared_release_fingerprint(
    source: Path,
    *,
    write: bool = False,
    source_sha: str | None = None,
    schema_revision: str | None = None,
) -> dict[str, Any]:
    """Create/verify the same-platform fingerprint of an offline bundle."""
    source = source.resolve()
    python = source / "geo-platform" / "backend" / ".venv" / "bin" / "python"
    if not python.is_file():
        raise ValueError(f"RELEASE_PYTHON_NOT_FOUND:{python}")
    process = subprocess.run(
        [
            str(python), "-c",
            "import json,platform,sys; print(json.dumps({"
            "'system':platform.system(),'machine':platform.machine(),"
            "'python_version':platform.python_version(),"
            "'python_implementation':platform.python_implementation(),"
            "'executable':sys.executable}))",
        ],
        capture_output=True,
        text=True,
    )
    if process.returncode:
        raise ValueError("PREPARED_PYTHON_NOT_EXECUTABLE:" + process.stderr[-1000:])
    runtime = json.loads(process.stdout)
    node = subprocess.run(["node", "--version"], capture_output=True, text=True)
    value = {
        "format": "geo-m1-prepared-release-fingerprint.v1",
        "prepared_at": _utc_now(),
        "os": runtime["system"],
        "arch": runtime["machine"],
        "python_version": runtime["python_version"],
        "python_implementation": runtime["python_implementation"],
        "python_executable_at_prepare_time": runtime["executable"],
        "node_version_at_frontend_build": node.stdout.strip() if node.returncode == 0 else "UNKNOWN",
        "portability": "SAME_OS_ARCH_ONLY; copied venv is not a cross-platform artifact",
    }
    if write:
        if not source_sha or not re.fullmatch(r"[0-9a-f]{7,40}", source_sha):
            raise ValueError("FINGERPRINT_SOURCE_SHA_REQUIRED")
        if not schema_revision:
            raise ValueError("FINGERPRINT_SCHEMA_REVISION_REQUIRED")
        value["source_sha"] = source_sha
        value["schema_revision"] = schema_revision
        _write_json(source / "PREPARED_RELEASE_FINGERPRINT.json", value)
    return value


def _validate_prepared_fingerprint(source: Path, source_sha: str, schema_revision: str) -> dict[str, Any]:
    path = source / "PREPARED_RELEASE_FINGERPRINT.json"
    if not path.is_file():
        raise ValueError("PREPARED_RELEASE_FINGERPRINT_REQUIRED")
    value = json.loads(path.read_text())
    if value.get("format") != "geo-m1-prepared-release-fingerprint.v1":
        raise ValueError("PREPARED_RELEASE_FINGERPRINT_UNSUPPORTED")
    if value.get("source_sha") != source_sha or value.get("schema_revision") != schema_revision:
        raise ValueError("PREPARED_RELEASE_IDENTITY_MISMATCH")
    if value.get("os") != platform.system() or value.get("arch") != platform.machine():
        raise ValueError(
            f"PREPARED_RELEASE_PLATFORM_MISMATCH:{value.get('os')}/{value.get('arch')}:"
            f"{platform.system()}/{platform.machine()}"
        )
    actual = prepared_release_fingerprint(source)
    if actual["python_version"].split(".")[:2] != str(value.get("python_version", "")).split(".")[:2]:
        raise ValueError("PREPARED_RELEASE_PYTHON_MISMATCH")
    return value


def install_release(
    source: Path,
    home: Path,
    release_id: str,
    source_sha: str,
    schema_revision: str,
    *,
    activate: bool = True,
) -> dict[str, Any]:
    source, home = source.resolve(), home.resolve()
    if not SAFE_RELEASE.fullmatch(release_id):
        raise ValueError("INVALID_RELEASE_ID")
    if not re.fullmatch(r"[0-9a-f]{7,40}", source_sha):
        raise ValueError("INVALID_SOURCE_SHA")
    required = (
        source / "scripts" / "local_beta.sh",
        source / "geo-platform" / "backend" / ".venv" / "bin" / "python",
        source / "geo-platform" / "frontend" / "dist" / "index.html",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise ValueError("PREPARED_RELEASE_INCOMPLETE:" + ",".join(missing))
    runtime_fingerprint = _validate_prepared_fingerprint(source, source_sha, schema_revision)
    release = home / "releases" / release_id
    if release.exists():
        raise ValueError(f"RELEASE_EXISTS:{release_id}")
    for name in ("releases", "data", "evidence", "config", "logs", "run", "backups"):
        (home / name).mkdir(parents=True, mode=0o700, exist_ok=True)
    staging = home / "releases" / f".{release_id}.staging"
    if staging.exists():
        raise ValueError(f"STALE_RELEASE_STAGING:{staging}")
    _copy_release(source, staging)
    manifest = {
        "format": "geo-m1-release.v1",
        "release_id": release_id,
        "source_sha": source_sha,
        "schema_revision": schema_revision,
        "installed_at": _utc_now(),
        "runtime_fingerprint": runtime_fingerprint,
        "external_calls": 0,
    }
    _write_json(staging / "RELEASE_MANIFEST.json", manifest)
    staging.rename(release)
    if activate:
        _activate_release(home, release_id)
    (home / "config" / "daily-model-calls").write_text("0\n")
    (home / "config" / "scheduled-sampling-enabled").write_text("0\n")
    for path in (home / "config").iterdir():
        path.chmod(0o600)
    (home / "VERSION").write_text(f"{release_id} / {source_sha}\n")
    (home / "VERSION").chmod(0o600)
    return manifest


def _activate_release(home: Path, release_id: str) -> str:
    current = home / "current"
    previous = current.resolve().name if current.exists() else "NONE"
    replacement = home / ".current.next"
    if replacement.exists() or replacement.is_symlink():
        replacement.unlink()
    replacement.symlink_to(Path("releases") / release_id, target_is_directory=True)
    os.replace(replacement, current)
    return previous


def switch_release(home: Path, release_id: str) -> dict[str, str]:
    home = home.resolve()
    if not SAFE_RELEASE.fullmatch(release_id) or not (home / "releases" / release_id).is_dir():
        raise ValueError(f"RELEASE_NOT_FOUND:{release_id}")
    database = home / "data" / "geo-beta.db"
    state = inspect_database(database)
    if state["active_work"]:
        raise ValueError("ACTIVE_WORK_REQUIRES_QUARANTINE")
    previous = _activate_release(home, release_id)
    return {"status": "PASS_RELEASE_POINTER_SWITCHED", "previous": previous, "current": release_id}


def _migrate_and_validate(release: Path, database: Path) -> dict[str, Any]:
    backend = release / "geo-platform" / "backend"
    python = backend / ".venv" / "bin" / "python"
    if not python.is_file():
        raise ValueError(f"RELEASE_PYTHON_NOT_FOUND:{python}")
    environment = {**os.environ, "GEO_RELEASE_DATABASE_URL": f"sqlite:///{database.resolve()}"}
    migration = subprocess.run(
        [str(python), "-m", "alembic", "-c", "alembic.release.ini", "upgrade", "head"],
        cwd=backend,
        env=environment,
        capture_output=True,
        text=True,
    )
    if migration.returncode:
        raise ValueError("ISOLATED_MIGRATION_FAILED:" + (migration.stderr or migration.stdout)[-2000:])
    validation = subprocess.run(
        [
            str(python),
            "-c",
            "from app.core.release_database import release_engine; "
            "from app.release_schema import validate_release_database; "
            "print(validate_release_database(release_engine))",
        ],
        cwd=backend,
        env=environment,
        capture_output=True,
        text=True,
    )
    if validation.returncode:
        raise ValueError("ISOLATED_SCHEMA_VALIDATION_FAILED:" + (validation.stderr or validation.stdout)[-2000:])
    state = inspect_database(database)
    return {
        "revision": state["revision"],
        "integrity": state["integrity"],
        "foreign_key_violations": state["foreign_key_violations"],
        "migration_log_sha256": _hash_text(migration.stdout + migration.stderr),
        "validation_log_sha256": _hash_text(validation.stdout + validation.stderr),
    }


def upgrade_release(
    source: Path,
    home: Path,
    release_id: str,
    source_sha: str,
    schema_revision: str,
) -> dict[str, Any]:
    """Stage and validate an upgrade, then migrate the stopped local database.

    The caller must stop the services first.  This function refuses all active
    queue rows, creates a full pre-upgrade backup, and proves the candidate on an
    isolated restore before changing the live database or release pointer.
    It intentionally leaves services stopped; starting them is a separate,
    visible operator action.
    """
    home = home.resolve()
    database = home / "data" / "geo-beta.db"
    state = inspect_database(database)
    if state["active_work"]:
        raise ValueError("ACTIVE_WORK_REQUIRES_QUARANTINE")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = home / "backups" / f"pre-upgrade-{timestamp}-{release_id}"
    backup_home(home, backup)
    install_release(source, home, release_id, source_sha, schema_revision, activate=False)
    release = home / "releases" / release_id
    with tempfile.TemporaryDirectory(prefix="geo-m1-upgrade-") as temp:
        validation_home = Path(temp) / "restore"
        restore_backup(backup, validation_home)
        isolated = _migrate_and_validate(release, validation_home / "data" / "geo-beta.db")
    # Only the stopped database is migrated, after a recoverable backup and an
    # isolated successful migration using the exact candidate runtime.
    live = _migrate_and_validate(release, database)
    previous = _activate_release(home, release_id)
    (home / "VERSION").write_text(f"{release_id} / {source_sha}\n")
    (home / "VERSION").chmod(0o600)
    for name in ("daily-model-calls", "scheduled-sampling-enabled"):
        path = home / "config" / name
        path.write_text("0\n")
        path.chmod(0o600)
    report = {
        "status": "PASS_UPGRADED_SERVICES_REMAIN_STOPPED",
        "previous_release": previous,
        "current_release": release_id,
        "pre_upgrade_backup": str(backup),
        "isolated_migration": isolated,
        "live_migration": live,
        "daily_model_calls": 0,
        "scheduled_sampling": 0,
        "external_calls": 0,
    }
    _write_json(home / "UPGRADE_REPORT.json", report)
    return report


def _relocate_restored_paths(database: Path, from_home: Path, to_home: Path) -> int:
    relocated = 0
    with sqlite3.connect(database) as db:
        if "single_prompt_prepared_source_snapshots" not in _tables(db):
            return 0
        rows = db.execute(
            "SELECT snapshot_id, artifact_path, artifact_hash "
            "FROM single_prompt_prepared_source_snapshots ORDER BY snapshot_id"
        ).fetchall()
        for snapshot_id, raw_path, expected in rows:
            old = Path(raw_path)
            try:
                relative = old.relative_to(from_home)
            except ValueError as exc:
                raise ValueError(f"RESTORED_ARTIFACT_OUTSIDE_STAGING:{snapshot_id}") from exc
            new = to_home / relative
            if not new.is_file() or _hash_file(new) != expected:
                raise ValueError(f"RESTORED_ARTIFACT_RELOCATION_FAILED:{snapshot_id}")
            db.execute(
                "UPDATE single_prompt_prepared_source_snapshots SET artifact_path=? "
                "WHERE snapshot_id=? AND artifact_hash=?",
                (str(new), snapshot_id, expected),
            )
            relocated += 1
        db.commit()
    return relocated


def rollback_release(home: Path, backup: Path, release_id: str) -> dict[str, Any]:
    """Restore data from an explicit backup and switch to an installed release.

    The caller must stop services first.  Existing data/evidence are retained in
    a timestamped failed-state directory; nothing is deleted by this command.
    """
    home, backup = home.resolve(), backup.resolve()
    if not (home / "releases" / release_id).is_dir():
        raise ValueError(f"RELEASE_NOT_FOUND:{release_id}")
    current_state = inspect_database(home / "data" / "geo-beta.db")
    if current_state["active_work"]:
        raise ValueError("ACTIVE_WORK_REQUIRES_QUARANTINE")
    staging = home / ".rollback-staging"
    if staging.exists():
        raise ValueError(f"STALE_ROLLBACK_STAGING:{staging}")
    restore_backup(backup, staging)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    retained = home / "backups" / f"pre-rollback-live-{timestamp}"
    retained.mkdir(parents=True, mode=0o700)
    (home / "data").rename(retained / "data")
    (home / "evidence").rename(retained / "evidence")
    (staging / "data").rename(home / "data")
    (staging / "evidence").rename(home / "evidence")
    relocated = _relocate_restored_paths(
        home / "data" / "geo-beta.db", staging, home,
    )
    shutil.rmtree(staging)
    previous = _activate_release(home, release_id)
    for name in ("daily-model-calls", "scheduled-sampling-enabled"):
        path = home / "config" / name
        path.write_text("0\n")
        path.chmod(0o600)
    final = inspect_database(home / "data" / "geo-beta.db")
    report = {
        "status": "PASS_ROLLED_BACK_SERVICES_REMAIN_STOPPED",
        "previous_release": previous,
        "current_release": release_id,
        "backup": str(backup),
        "retained_pre_rollback_state": str(retained),
        "relocated_prepared_sources": relocated,
        "database": final,
        "daily_model_calls": 0,
        "scheduled_sampling": 0,
        "external_calls": 0,
    }
    _write_json(home / "ROLLBACK_REPORT.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("preflight")
    inspect.add_argument("--database", required=True, type=Path)
    backup = sub.add_parser("backup")
    backup.add_argument("--home", required=True, type=Path)
    backup.add_argument("--output", required=True, type=Path)
    verify = sub.add_parser("verify-backup")
    verify.add_argument("--backup", required=True, type=Path)
    restore = sub.add_parser("restore")
    restore.add_argument("--backup", required=True, type=Path)
    restore.add_argument("--target-home", required=True, type=Path)
    install = sub.add_parser("install")
    install.add_argument("--source", required=True, type=Path)
    install.add_argument("--home", required=True, type=Path)
    install.add_argument("--release-id", required=True)
    install.add_argument("--source-sha", required=True)
    install.add_argument("--schema-revision", required=True)
    fingerprint = sub.add_parser("fingerprint")
    fingerprint.add_argument("--source", required=True, type=Path)
    fingerprint.add_argument("--write", action="store_true")
    fingerprint.add_argument("--source-sha")
    fingerprint.add_argument("--schema-revision")
    switch = sub.add_parser("switch")
    switch.add_argument("--home", required=True, type=Path)
    switch.add_argument("--release-id", required=True)
    upgrade = sub.add_parser("upgrade")
    upgrade.add_argument("--source", required=True, type=Path)
    upgrade.add_argument("--home", required=True, type=Path)
    upgrade.add_argument("--release-id", required=True)
    upgrade.add_argument("--source-sha", required=True)
    upgrade.add_argument("--schema-revision", required=True)
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--home", required=True, type=Path)
    rollback.add_argument("--backup", required=True, type=Path)
    rollback.add_argument("--release-id", required=True)
    control = sub.add_parser("runtime")
    control.add_argument("--home", required=True, type=Path)
    control.add_argument("action", choices=("start", "stop", "status", "restart"))
    quiet = sub.add_parser("quiesce")
    quiet.add_argument("--home", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.command == "preflight":
        result = inspect_database(args.database)
        result["status"] = "PASS" if not result["active_work"] else "BLOCKED_ACTIVE_WORK"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 3
    if args.command == "backup":
        result = backup_home(args.home, args.output)
    elif args.command == "verify-backup":
        result = verify_backup(args.backup)
    elif args.command == "restore":
        result = restore_backup(args.backup, args.target_home)
    elif args.command == "install":
        result = install_release(args.source, args.home, args.release_id, args.source_sha, args.schema_revision)
    elif args.command == "fingerprint":
        result = prepared_release_fingerprint(
            args.source,
            write=args.write,
            source_sha=args.source_sha,
            schema_revision=args.schema_revision,
        )
    elif args.command == "switch":
        result = switch_release(args.home, args.release_id)
    elif args.command == "upgrade":
        result = upgrade_release(args.source, args.home, args.release_id, args.source_sha, args.schema_revision)
    elif args.command == "rollback":
        result = rollback_release(args.home, args.backup, args.release_id)
    elif args.command == "runtime":
        return runtime(args.home, args.action)
    elif args.command == "quiesce":
        result = quiesce(args.home)
    else:  # pragma: no cover
        raise AssertionError(args.command)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
