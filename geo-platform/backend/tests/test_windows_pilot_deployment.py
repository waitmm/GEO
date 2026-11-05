from pathlib import Path
import hashlib
import json
import sqlite3
import subprocess
import sys

import pytest

from scripts.m1_beta_ops import backup_home
from test_m1_beta_ops import _database


ROOT = Path(__file__).resolve().parents[3]
WINDOWS = ROOT / "scripts" / "windows"


def source(name: str) -> str:
    return (WINDOWS / name).read_text(encoding="utf-8")


def test_windows_entrypoints_are_present_and_use_one_controller():
    controller = source("geo-beta.ps1")
    for name, action in {
        "install.ps1": "install", "start.ps1": "start", "stop.ps1": "stop",
        "restart.ps1": "restart", "status.ps1": "status", "backup.ps1": "backup",
        "restore.ps1": "restore",
    }.items():
        assert f'") {action} @args' in source(name)
    assert 'ValidateSet("install", "start", "stop", "restart", "status", "backup", "restore")' in controller


def test_windows_pilot_is_private_http_password_mode_without_tls_material():
    controller = source("geo-beta.ps1")
    runner = source("run-process.ps1")
    password = source("set-password.ps1")
    combined = controller + runner + password
    assert "GEO_ALLOW_TRUSTED_LAN_HTTP=1" in controller
    assert "GEO_TRUSTED_LAN_CIDR=$TrustedCidr" in controller
    assert "Assert-PrivateIPv4 $BindAddress" in controller
    assert "New-NetFirewallRule" in controller and "-RemoteAddress $TrustedCidr" in controller
    assert "release-access.json" in controller
    assert "create_shared_password_config.py" in password
    assert "Read-Host" in password and "-AsSecureString" in password
    assert "ZeroFreeBSTR" in password
    assert "PASSWORD_UPDATED_SESSIONS_REVOKED" in password
    assert not any(value in combined.lower() for value in ("server.crt", "server.key", "geo-beta-ca"))


def test_windows_pilot_keeps_external_capabilities_closed_and_worker_singleton():
    controller = source("geo-beta.ps1")
    assert "GEO_AGENT_BETA_DAILY_MODEL_CALLS=0" in controller
    assert "GEO_BETA_SCHEDULED_SAMPLING_ENABLED=0" in controller
    assert "WENXIN_MAX_CONCURRENCY=1" in controller
    assert "WENXIN_MAX_RETRIES=0" in controller
    assert "-MultipleInstances IgnoreNew" in controller
    assert '"GEO Beta Worker"' in controller
    assert "RAW_DATABASE_BACKUP_UNSUPPORTED_USE_FULL_BACKUP" in controller
    assert "m1_beta_ops.py\") backup" in controller


def test_windows_install_is_stopped_by_default_and_has_no_implicit_public_binding():
    controller = source("geo-beta.ps1")
    install = controller.split("function Install-Geo", 1)[1].split("function Start-Geo", 1)[0]
    assert "Stop-GeoTasks" in install
    assert "Start-ScheduledTask" not in install
    assert 'BIND_ADDRESS_MUST_BE_RFC1918_PRIVATE' in controller
    assert '0.0.0.0' not in controller
    assert 'New-ScheduledTaskPrincipal -UserId "SYSTEM"' in controller


def test_windows_restore_targets_final_home_before_install_and_never_moves_database():
    controller = source("geo-beta.ps1")
    install = controller.split("function Install-Geo", 1)[1].split("function Start-Geo", 1)[0]
    assert "restore --backup $RestoreBackup --target-home $paths.Home" in install
    assert install.index("restore --backup") < install.index("-m venv")
    assert install.index("preflight --database") < install.index("restore --backup")
    assert install.index("RAW_DATABASE_BACKUP_UNSUPPORTED") < install.index("New-Item")
    assert "WINDOWS_HOME_MUST_BE_NEW_OR_EMPTY" in install
    assert ".restore-stage" not in install
    assert "Move-Item" not in install
    assert "Copy-Item -LiteralPath $DatabaseBackup" not in install
    assert "Remove-Item -Recurse" not in install


def test_windows_restore_command_only_restores_a_complete_backup_to_a_new_home():
    controller = source("geo-beta.ps1")
    restore = controller.split("function Restore-Geo", 1)[1].split("switch ($Action)", 1)[0]
    assert "COMPLETE_BACKUP_DIRECTORY_REQUIRED" in restore
    assert "RESTORE_TARGET_HOME_REQUIRED" in restore
    assert "RESTORE_TARGET_MUST_BE_NEW_OR_EMPTY" in restore
    assert "restore --backup $RestoreBackup --target-home $target" in restore
    assert "Start-ScheduledTask" not in restore
    assert "Remove-Item" not in restore


def test_windows_full_backup_cli_preserves_final_source_paths_and_unknown_audit(tmp_path):
    # Execute the same stdlib CLI used by PowerShell. No Windows runtime is
    # claimed here; this tests the actual data restore, not mocked copies.
    original = tmp_path / "mac-home"
    _database(original)[1].close()
    with sqlite3.connect(original / "data" / "internal-beta-model-budget.sqlite3") as ledger:
        ledger.execute("CREATE TABLE audit_events(state TEXT, reserved_cny TEXT)")
        ledger.execute("INSERT INTO audit_events VALUES ('DELIVERY_UNKNOWN', '0.31172')")
    backup = tmp_path / "full-backup"
    backup_home(original, backup)
    final_home = tmp_path / "GEO Beta"
    helper = ROOT / "geo-platform" / "backend" / "scripts" / "m1_beta_ops.py"
    subprocess.run([sys.executable, str(helper), "preflight", "--database", str(backup / "database.db")],
                   check=True, capture_output=True, text=True)
    completed = subprocess.run([sys.executable, str(helper), "restore", "--backup", str(backup),
                                "--target-home", str(final_home)], check=True, capture_output=True, text=True)
    report = json.loads(completed.stdout)
    assert report["target_home"] == str(final_home.resolve())
    assert report["daily_model_calls"] == report["scheduled_sampling"] == 0
    assert report["audit_ledgers_restored_for_audit_only"] == 1
    with sqlite3.connect(final_home / "data" / "geo-beta.db") as database:
        path, expected = database.execute(
            "SELECT artifact_path, artifact_hash FROM single_prompt_prepared_source_snapshots").fetchone()
    artifact = Path(path)
    assert artifact.is_relative_to(final_home / "evidence")
    assert ".restore-stage" not in artifact.parts
    assert artifact.is_file()
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected
    assert (final_home / "evidence" / "source.txt").is_file()
    audit = final_home / "backups" / "audit-ledgers" / "internal-beta-model-budget.sqlite3"
    with sqlite3.connect(audit) as ledger:
        assert ledger.execute("SELECT * FROM audit_events").fetchall() == [("DELIVERY_UNKNOWN", "0.31172")]
    assert not (final_home / "data" / "internal-beta-model-budget.sqlite3").exists()
    assert (final_home / "RESTORE_REPORT.json").is_file()
    again = subprocess.run([sys.executable, str(helper), "restore", "--backup", str(backup),
                            "--target-home", str(final_home)], capture_output=True, text=True)
    assert again.returncode != 0 and "RESTORE_TARGET_NOT_EMPTY" in again.stderr
    assert artifact.is_file() and audit.is_file()


@pytest.mark.parametrize("violation,expected", [
    ("queue", "BLOCKED_ACTIVE_WORK"),
    ("unknown_revision", "BLOCKED_SCHEMA_REVISION_UNKNOWN"),
    ("foreign_key", "BLOCKED_FOREIGN_KEY_VIOLATIONS"),
])
def test_windows_migration_preflight_blocks_unsafe_database(tmp_path, violation, expected):
    database, writer = _database(tmp_path / "fixture")
    if violation == "queue":
        writer.execute("INSERT INTO browser_monitor_tasks VALUES ('queued')")
    elif violation == "unknown_revision":
        writer.execute("DELETE FROM alembic_version")
    else:
        writer.executescript("CREATE TABLE parent(id INTEGER PRIMARY KEY);"
                             "CREATE TABLE child(id INTEGER REFERENCES parent(id));"
                             "INSERT INTO child VALUES (1);")
    writer.commit()
    writer.close()
    helper = ROOT / "geo-platform" / "backend" / "scripts" / "m1_beta_ops.py"
    checked = subprocess.run([sys.executable, str(helper), "preflight", "--database", str(database)],
                             capture_output=True, text=True)
    assert checked.returncode == 3
    assert json.loads(checked.stdout)["status"] == expected
