from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WINDOWS = ROOT / "scripts" / "windows"


def source(name: str) -> str:
    return (WINDOWS / name).read_text(encoding="utf-8")


def test_windows_entrypoints_are_present_and_use_one_controller():
    controller = source("geo-beta.ps1")
    for name, action in {
        "install.ps1": "install", "start.ps1": "start", "stop.ps1": "stop",
        "restart.ps1": "restart", "status.ps1": "status", "backup.ps1": "backup",
    }.items():
        assert f'") {action} @args' in source(name)
    assert 'ValidateSet("install", "start", "stop", "restart", "status", "backup")' in controller


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
    assert "CONSISTENT_DATABASE_BACKUP_REQUIRED" in controller
    assert "m1_beta_ops.py\") backup" in controller


def test_windows_install_is_stopped_by_default_and_has_no_implicit_public_binding():
    controller = source("geo-beta.ps1")
    install = controller.split("function Install-Geo", 1)[1].split("function Start-Geo", 1)[0]
    assert "Stop-GeoTasks" in install
    assert "Start-ScheduledTask" not in install
    assert 'BIND_ADDRESS_MUST_BE_RFC1918_PRIVATE' in controller
    assert '0.0.0.0' not in controller
    assert 'New-ScheduledTaskPrincipal -UserId "SYSTEM"' in controller
