from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import sqlite3

import pytest

from scripts.m1_beta_ops import (
    backup_home,
    install_release,
    inspect_database,
    quiesce,
    restore_backup,
    rollback_release,
    runtime,
    upgrade_release,
    verify_backup,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _database(home: Path, *, active: bool = False) -> tuple[Path, sqlite3.Connection]:
    for name in ("data", "evidence", "config", "logs", "run", "backups"):
        (home / name).mkdir(parents=True, mode=0o700, exist_ok=True)
    (home / "run" / "services-stopped").write_text("test\n")
    (home / "VERSION").write_text("fixture / 1111111\n")
    artifact = home / "evidence" / "source.txt"
    artifact.write_text("immutable evidence")
    digest = _hash("immutable evidence")
    database = home / "data" / "geo-beta.db"
    db = sqlite3.connect(database)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA wal_autocheckpoint=0")
    db.executescript(
        """
        CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY);
        INSERT INTO alembic_version VALUES ('20261022_01');
        CREATE TABLE single_prompt_prepared_source_snapshots(
          snapshot_id TEXT PRIMARY KEY,
          artifact_path TEXT NOT NULL,
          artifact_hash TEXT NOT NULL,
          clean_text TEXT NOT NULL
        );
        CREATE TABLE browser_monitor_tasks(status TEXT NOT NULL);
        CREATE TABLE sample_rows(id INTEGER PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    db.execute(
        "INSERT INTO single_prompt_prepared_source_snapshots VALUES (?,?,?,?)",
        ("snapshot-1", str(artifact), digest, "immutable evidence"),
    )
    db.execute("INSERT INTO sample_rows(value) VALUES ('base')")
    if active:
        db.execute("INSERT INTO browser_monitor_tasks(status) VALUES ('queued')")
    db.commit()
    return database, db


def _prepared_release(root: Path, marker: str) -> Path:
    script = root / "scripts" / "local_beta.sh"
    python = root / "geo-platform" / "backend" / ".venv" / "bin" / "python"
    frontend = root / "geo-platform" / "frontend" / "dist" / "index.html"
    script.parent.mkdir(parents=True)
    python.parent.mkdir(parents=True)
    frontend.parent.mkdir(parents=True)
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        "# services-stopped; did not stop within 10 seconds\n"
        f"echo {marker}:$1 >> \"$GEO_BETA_HOME/runtime-actions\"\n"
        "exit 0\n"
    )
    # The migration/validation runner only needs a deterministic, non-networked
    # executable for this lifecycle test. Production validation uses the exact
    # prepared release Python and Alembic environment.
    python.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == \"-c\" && \"${2:-}\" == *\"platform.system\"* ]]; then\n"
        f"  echo '{json.dumps({'system': platform.system(), 'machine': platform.machine(), 'python_version': platform.python_version(), 'python_implementation': platform.python_implementation(), 'executable': str(python)})}'\n"
        "fi\n"
        "exit 0\n"
    )
    frontend.write_text("release")
    script.chmod(0o755)
    python.chmod(0o755)
    (root / "PREPARED_RELEASE_FINGERPRINT.json").write_text(json.dumps({
        "format": "geo-m1-prepared-release-fingerprint.v1",
        "prepared_at": "2026-10-29T00:00:00+00:00",
        "os": platform.system(),
        "arch": platform.machine(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable_at_prepare_time": str(python),
        "node_version_at_frontend_build": "v-test",
        "portability": "SAME_OS_ARCH_ONLY; copied venv is not a cross-platform artifact",
        "source_sha": "1" * 40,
        "schema_revision": "20261022_01",
    }))
    return root


def test_online_backup_includes_committed_wal_and_restores_artifact_identity(tmp_path):
    home = tmp_path / "home"
    database, writer = _database(home)
    # Keep the WAL connection open and add a committed row after schema setup.
    # A raw copy of the main file is not guaranteed to contain this row.
    writer.execute("INSERT INTO sample_rows(value) VALUES ('committed-in-wal')")
    writer.commit()

    backup = tmp_path / "backup"
    manifest = backup_home(home, backup)
    assert manifest["database"]["revision"] == "20261022_01"
    assert verify_backup(backup)["prepared_source_count"] == 1
    with sqlite3.connect(backup / "database.db") as restored:
        assert restored.execute("SELECT value FROM sample_rows ORDER BY id").fetchall() == [
            ("base",), ("committed-in-wal",),
        ]
    writer.close()

    target = tmp_path / "restored"
    report = restore_backup(backup, target)
    assert report["daily_model_calls"] == report["scheduled_sampling"] == 0
    assert (target / "config" / "daily-model-calls").read_text().strip() == "0"
    with sqlite3.connect(target / "data" / "geo-beta.db") as db:
        path, expected = db.execute(
            "SELECT artifact_path, artifact_hash FROM single_prompt_prepared_source_snapshots"
        ).fetchone()
    relocated = Path(path)
    assert relocated.is_relative_to(target / "evidence")
    assert relocated.is_file()
    assert hashlib.sha256(relocated.read_bytes()).hexdigest() == expected


def test_backup_and_preflight_fail_closed_for_active_queue(tmp_path):
    home = tmp_path / "home"
    database, connection = _database(home, active=True)
    connection.close()
    assert inspect_database(database)["active_work"] == [
        {"table": "browser_monitor_tasks", "rowid": 1, "status": "queued"}
    ]
    with pytest.raises(ValueError, match="ACTIVE_WORK_REQUIRES_QUARANTINE"):
        backup_home(home, tmp_path / "backup")


def test_backup_requires_explicit_stopped_service_marker(tmp_path):
    home = tmp_path / "home"
    _database(home)[1].close()
    (home / "run" / "services-stopped").unlink()
    with pytest.raises(ValueError, match="SERVICES_STOP_CONFIRMATION_REQUIRED"):
        backup_home(home, tmp_path / "backup")


def test_install_runtime_upgrade_and_rollback_are_versioned_and_fail_closed(tmp_path):
    home = tmp_path / "home"
    _database(home)[1].close()
    old_source = _prepared_release(tmp_path / "old-source", "old")
    new_source = _prepared_release(tmp_path / "new-source", "new")
    value = json.loads((new_source / "PREPARED_RELEASE_FINGERPRINT.json").read_text())
    value["source_sha"] = "2" * 40
    (new_source / "PREPARED_RELEASE_FINGERPRINT.json").write_text(json.dumps(value))
    installed = install_release(old_source, home, "m1-old", "1" * 40, "20261022_01")
    assert installed["source_sha"] == "1" * 40
    assert (home / "current").resolve().name == "m1-old"
    assert runtime(home, "status") == 0
    assert (home / "runtime-actions").read_text().strip() == "old:status"
    (home / "run" / "services-stopped").unlink()
    assert quiesce(home)["status"] == "PASS_SERVICES_STOPPED"
    assert (home / "run" / "services-stopped").is_file()

    upgraded = upgrade_release(new_source, home, "m1-new", "2" * 40, "20261022_01")
    assert upgraded["status"] == "PASS_UPGRADED_SERVICES_REMAIN_STOPPED"
    assert (home / "current").resolve().name == "m1-new"
    assert Path(upgraded["pre_upgrade_backup"]).is_dir()
    assert (home / "config" / "daily-model-calls").read_text().strip() == "0"
    assert (home / "config" / "scheduled-sampling-enabled").read_text().strip() == "0"

    rolled_back = rollback_release(home, Path(upgraded["pre_upgrade_backup"]), "m1-old")
    assert rolled_back["status"] == "PASS_ROLLED_BACK_SERVICES_REMAIN_STOPPED"
    assert (home / "current").resolve().name == "m1-old"
    assert Path(rolled_back["retained_pre_rollback_state"]).is_dir()
    assert inspect_database(home / "data" / "geo-beta.db")["integrity"] == "ok"


def test_install_rejects_unfingerprinted_or_cross_platform_bundle(tmp_path):
    source = _prepared_release(tmp_path / "source", "fixture")
    fingerprint = source / "PREPARED_RELEASE_FINGERPRINT.json"
    fingerprint.unlink()
    with pytest.raises(ValueError, match="PREPARED_RELEASE_FINGERPRINT_REQUIRED"):
        install_release(source, tmp_path / "home-a", "m1-a", "a" * 40, "20261022_01")
    source = _prepared_release(tmp_path / "source-b", "fixture")
    value = json.loads((source / "PREPARED_RELEASE_FINGERPRINT.json").read_text())
    value["arch"] = "definitely-not-this-machine"
    (source / "PREPARED_RELEASE_FINGERPRINT.json").write_text(json.dumps(value))
    with pytest.raises(ValueError, match="PREPARED_RELEASE_PLATFORM_MISMATCH"):
        install_release(source, tmp_path / "home-b", "m1-b", "1" * 40, "20261022_01")


def test_existing_shell_entrypoints_encode_safe_wal_and_stop_before_migrate():
    workspace = Path(__file__).resolve().parents[3]
    prepare = (workspace / "scripts" / "prepare_internal_beta.sh").read_text()
    controller = (workspace / "scripts" / "local_beta.sh").read_text()
    assert "origin.backup(destination)" in prepare
    assert 'install -m 600 "$SOURCE_DB" "$TARGET_DB"' not in prepare
    start = controller.index("start() {")
    stop_worker = controller.index('stop_service "$WORKER_LABEL"', start)
    preflight = controller.index("m1_beta_ops.py preflight", start)
    migrate = controller.index('alembic -c alembic.release.ini upgrade head', start)
    assert stop_worker < preflight < migrate
