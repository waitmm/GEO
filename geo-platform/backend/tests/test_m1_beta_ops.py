from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys

import pytest

from scripts.m1_beta_ops import (
    backup_home,
    install_release,
    inspect_database,
    prepared_release_fingerprint,
    quiesce,
    restore_backup,
    rollback_release,
    runtime,
    switch_release,
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
        CREATE TRIGGER trg_prepared_source_no_update
        BEFORE UPDATE ON single_prompt_prepared_source_snapshots
        BEGIN SELECT RAISE(ABORT, 'RELEASE_HISTORY_IMMUTABLE'); END;
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
    prepared_release_fingerprint(
        root, write=True, source_sha="1" * 40, schema_revision="20261022_01",
    )
    return root


def test_online_backup_includes_committed_wal_and_restores_artifact_identity(tmp_path):
    home = tmp_path / "home"
    database, writer = _database(home)
    ledger = home / "data" / "internal-beta-model-budget.sqlite3"
    with sqlite3.connect(ledger) as budget:
        budget.execute("CREATE TABLE audit_events(id INTEGER PRIMARY KEY, state TEXT NOT NULL)")
        budget.execute("INSERT INTO audit_events(state) VALUES ('DELIVERY_UNKNOWN')")
        budget.commit()
    # Keep the WAL connection open and add a committed row after schema setup.
    # A raw copy of the main file is not guaranteed to contain this row.
    writer.execute("INSERT INTO sample_rows(value) VALUES ('committed-in-wal')")
    writer.commit()

    backup = tmp_path / "backup"
    manifest = backup_home(home, backup)
    assert manifest["database"]["revision"] == "20261022_01"
    assert verify_backup(backup)["prepared_source_count"] == 1
    assert verify_backup(backup)["audit_ledger_count"] == 1
    with sqlite3.connect(backup / "database.db") as restored:
        assert restored.execute("SELECT value FROM sample_rows ORDER BY id").fetchall() == [
            ("base",), ("committed-in-wal",),
        ]
    writer.close()

    target = tmp_path / "restored"
    report = restore_backup(backup, target)
    assert report["daily_model_calls"] == report["scheduled_sampling"] == 0
    assert report["lan_enabled"] == 0
    assert (target / "config" / "daily-model-calls").read_text().strip() == "0"
    assert (target / "config" / "lan-enabled").read_text().strip() == "0"
    assert not (target / "data" / "internal-beta-model-budget.sqlite3").exists()
    restored_ledger = target / "backups" / "audit-ledgers" / "internal-beta-model-budget.sqlite3"
    assert restored_ledger.is_file()
    with sqlite3.connect(restored_ledger) as budget:
        assert budget.execute("SELECT state FROM audit_events").fetchall() == [("DELIVERY_UNKNOWN",)]
    with sqlite3.connect(target / "data" / "geo-beta.db") as db:
        path, expected = db.execute(
            "SELECT artifact_path, artifact_hash FROM single_prompt_prepared_source_snapshots"
        ).fetchone()
        with pytest.raises(sqlite3.IntegrityError, match="RELEASE_HISTORY_IMMUTABLE"):
            db.execute(
                "UPDATE single_prompt_prepared_source_snapshots SET artifact_path='tampered' "
                "WHERE snapshot_id='snapshot-1'"
            )
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
    (home / "config" / "tls").mkdir(mode=0o700)
    old_source = _prepared_release(tmp_path / "old-source", "old")
    new_source = _prepared_release(tmp_path / "new-source", "new")
    value = json.loads((new_source / "PREPARED_RELEASE_FINGERPRINT.json").read_text())
    value["source_sha"] = "2" * 40
    (new_source / "PREPARED_RELEASE_FINGERPRINT.json").write_text(json.dumps(value))
    installed = install_release(old_source, home, "m1-old", "1" * 40, "20261022_01")
    assert (home / "config" / "tls").stat().st_mode & 0o777 == 0o700
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
    assert (home / "config" / "lan-enabled").read_text().strip() == "0"

    rolled_back = rollback_release(home, Path(upgraded["pre_upgrade_backup"]), "m1-old")
    assert rolled_back["status"] == "PASS_ROLLED_BACK_SERVICES_REMAIN_STOPPED"
    assert (home / "current").resolve().name == "m1-old"
    assert Path(rolled_back["retained_pre_rollback_state"]).is_dir()
    assert inspect_database(home / "data" / "geo-beta.db")["integrity"] == "ok"
    assert (home / "VERSION").read_text().strip() == f"m1-old / {'1' * 40}"


def test_rollback_requires_stopped_marker_and_matching_release_identity(tmp_path):
    home = tmp_path / "home"
    _database(home)[1].close()
    source = _prepared_release(tmp_path / "source", "old")
    install_release(source, home, "m1-old", "1" * 40, "20261022_01")
    backup = tmp_path / "backup"
    backup_home(home, backup)
    (home / "run" / "services-stopped").unlink()
    with pytest.raises(ValueError, match="SERVICES_STOP_CONFIRMATION_REQUIRED"):
        rollback_release(home, backup, "m1-old")
    (home / "run" / "services-stopped").write_text("stopped\n")
    other = _prepared_release(tmp_path / "other", "other")
    install_release(other, home, "m1-other", "1" * 40, "20261022_01", activate=False)
    with pytest.raises(ValueError, match="ROLLBACK_RELEASE_BACKUP_VERSION_MISMATCH"):
        rollback_release(home, backup, "m1-other")


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


def test_release_manifest_excludes_secrets_but_keeps_nested_dependency_data(tmp_path):
    source = _prepared_release(tmp_path / "source", "fixture")
    (source / "geo-platform" / "backend" / ".env").write_text("SECRET=do-not-copy\n")
    (source / "runtime" / "wenxin-profile").mkdir(parents=True)
    (source / "runtime" / "wenxin-profile" / "Cookies").write_text("session")
    (source / "geo-platform" / "artifacts" / "debug").mkdir(parents=True)
    (source / "geo-platform" / "artifacts" / "debug" / "captured.html").write_text("private")
    (source / "geo-platform" / ".pytest_cache").mkdir(parents=True)
    (source / "geo-platform" / ".pytest_cache" / "nodeids").write_text("test state")
    package_data = source / "geo-platform" / "backend" / ".venv" / "lib" / "package" / "data"
    package_data.mkdir(parents=True)
    (package_data / "required.txt").write_text("required")
    nested_profile = source / "geo-platform" / "backend" / "runtime" / "wenxin-profile" / "Default"
    nested_profile.mkdir(parents=True)
    (nested_profile / "Cookies").write_text("session")
    prepared_release_fingerprint(
        source, write=True, source_sha="1" * 40, schema_revision="20261022_01",
    )
    home = tmp_path / "home"
    install_release(source, home, "m1-safe", "1" * 40, "20261022_01")
    release = home / "releases" / "m1-safe"
    assert not (release / "geo-platform" / "backend" / ".env").exists()
    assert not (release / "runtime").exists()
    assert not (release / "geo-platform" / "backend" / "runtime").exists()
    assert not (release / "geo-platform" / "artifacts").exists()
    assert not (release / "geo-platform" / ".pytest_cache").exists()
    assert (release / package_data.relative_to(source) / "required.txt").read_text() == "required"


def test_install_rejects_bundle_modified_after_fingerprint(tmp_path):
    source = _prepared_release(tmp_path / "source", "fixture")
    (source / "geo-platform" / "frontend" / "dist" / "index.html").write_text("tampered")
    with pytest.raises(ValueError, match="PREPARED_RELEASE_CONTENT_MISMATCH"):
        install_release(source, tmp_path / "home", "m1-tampered", "1" * 40, "20261022_01")


def test_inactive_install_does_not_change_active_version_and_switch_is_guarded(tmp_path):
    home = tmp_path / "home"
    _database(home)[1].close()
    old_source = _prepared_release(tmp_path / "old", "old")
    new_source = _prepared_release(tmp_path / "new", "new")
    value = json.loads((new_source / "PREPARED_RELEASE_FINGERPRINT.json").read_text())
    value["source_sha"] = "2" * 40
    (new_source / "PREPARED_RELEASE_FINGERPRINT.json").write_text(json.dumps(value))
    install_release(old_source, home, "m1-old", "1" * 40, "20261022_01")
    install_release(new_source, home, "m1-new", "2" * 40, "20261022_01", activate=False)
    assert (home / "current").resolve().name == "m1-old"
    assert (home / "VERSION").read_text().strip() == f"m1-old / {'1' * 40}"
    (home / "run" / "services-stopped").unlink()
    with pytest.raises(ValueError, match="SERVICES_STOP_CONFIRMATION_REQUIRED"):
        switch_release(home, "m1-new")


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
    assert "assert_service_owned_by_home" in controller
    assert controller.index('assert_service_owned_by_home "$label"', controller.index("stop_service()")) \
        < controller.index('launchctl bootout "$LAUNCH_DOMAIN/$label"', controller.index("stop_service()"))


def test_local_controller_only_stops_exact_home_launchd_instance(tmp_path):
    workspace = Path(__file__).resolve().parents[3]
    home = tmp_path / "home"
    release = tmp_path / "candidate"
    controller = release / "scripts" / "local_beta.sh"
    controller.parent.mkdir(parents=True)
    controller.write_text((workspace / "scripts" / "local_beta.sh").read_text())
    controller.chmod(0o755)
    python = release / "geo-platform" / "backend" / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/usr/bin/env bash\nexit 0\n")
    python.chmod(0o755)
    (release / "geo-platform" / "frontend" / "dist").mkdir(parents=True)
    (release / "geo-platform" / "frontend" / "dist" / "index.html").write_text("release")
    templates = release / "scripts" / "launchd"
    templates.mkdir(parents=True)
    for label in ("com.geo.beta.backend", "com.geo.beta.worker"):
        (templates / f"{label}.plist.in").write_text("fixture")
    (home / "data").mkdir(parents=True)
    (home / "data" / "geo-beta.db").write_bytes(b"")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        "if [[ \"$1\" == print ]]; then\n"
        "  label=\"${2##*/}\"\n"
        "  printf 'path = %s/launchd/%s.plist\\n' \"$MOCK_HOME\" \"$label\"\n"
        "  printf 'working directory = /old/release/backend\\n'\n"
        "  if [[ \"$label\" != com.geo.beta.proxy ]]; then\n"
        "    printf 'GEO_RELEASE_DATABASE_URL => %s\\n' \"$MOCK_DATABASE_URL\"\n"
        "  fi\n"
        "elif [[ \"$1\" == bootout ]]; then\n"
        "  printf '%s\\n' \"$2\" >> \"$MOCK_BOOTOUT_LOG\"\n"
        "fi\n"
    )
    launchctl.chmod(0o755)
    common = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
        "GEO_BETA_HOME": str(home),
        "MOCK_HOME": str(home),
        "MOCK_BOOTOUT_LOG": str(tmp_path / "bootout.log"),
    }
    exact = subprocess.run(
        [str(controller), "stop"],
        env={**common, "MOCK_DATABASE_URL": f"sqlite:///{home / 'data' / 'geo-beta.db'}"},
        capture_output=True, text=True,
    )
    assert exact.returncode == 0, exact.stderr
    assert len((tmp_path / "bootout.log").read_text().splitlines()) == 3

    (tmp_path / "bootout.log").unlink()
    foreign = subprocess.run(
        [str(controller), "stop"],
        env={**common, "MOCK_DATABASE_URL": f"sqlite:///{home / 'data' / 'geo-beta.db'}-other"},
        capture_output=True, text=True,
    )
    assert foreign.returncode != 0
    assert "belongs to another GEO_BETA_HOME" in foreign.stderr
    assert not (tmp_path / "bootout.log").exists()


def test_preflight_cli_blocks_foreign_key_violation(tmp_path):
    database = tmp_path / "broken.db"
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        db.execute("CREATE TABLE child(parent_id INTEGER REFERENCES parent(id))")
        db.execute("INSERT INTO child(parent_id) VALUES (99)")
        db.commit()
    script = Path(__file__).resolve().parents[1] / "scripts" / "m1_beta_ops.py"
    result = subprocess.run(
        [sys.executable, str(script), "preflight", "--database", str(database)],
        capture_output=True, text=True,
    )
    assert result.returncode == 3
    assert '"status": "BLOCKED_FOREIGN_KEY_VIOLATIONS"' in result.stdout

    clean_unversioned = tmp_path / "unversioned.db"
    with sqlite3.connect(clean_unversioned) as db:
        db.execute("CREATE TABLE rows(id INTEGER PRIMARY KEY)")
        db.commit()
    result = subprocess.run(
        [sys.executable, str(script), "preflight", "--database", str(clean_unversioned)],
        capture_output=True, text=True,
    )
    assert result.returncode == 3
    assert '"status": "BLOCKED_SCHEMA_REVISION_UNKNOWN"' in result.stdout
