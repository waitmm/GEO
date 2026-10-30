[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("install", "start", "stop", "restart", "status", "backup")]
    [string]$Action,
    [string]$Home = "$env:ProgramData\GEO Beta",
    [string]$Source,
    [string]$DatabaseBackup,
    [string]$RestoreBackup,
    [string]$ReleaseId,
    [string]$SourceSha,
    [string]$PythonExe = "py.exe",
    [string]$Wheelhouse,
    [switch]$AllowDependencyDownload,
    [string]$BindAddress,
    [string]$TrustedCidr,
    [int]$ProjectId = 1,
    [string]$BackupOutput
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$BackendTask = "GEO Beta Backend"
$WorkerTask = "GEO Beta Worker"
$FirewallRule = "GEO Beta Trusted LAN"

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "WINDOWS_ADMINISTRATOR_REQUIRED"
    }
}

function Get-Paths {
    $root = [IO.Path]::GetFullPath($Home)
    return @{
        Home = $root
        Current = Join-Path $root "current"
        Config = Join-Path $root "config"
        Data = Join-Path $root "data"
        Logs = Join-Path $root "logs"
        Run = Join-Path $root "run"
        Database = Join-Path $root "data\geo-beta.db"
        Env = Join-Path $root "config\backend.env"
        Access = Join-Path $root "config\release-access.json"
        Runner = Join-Path $root "current\scripts\windows\run-process.ps1"
    }
}

function Assert-PrivateIPv4([string]$Value) {
    $parsed = $null
    if (-not [Net.IPAddress]::TryParse($Value, [ref]$parsed)) { throw "BIND_ADDRESS_MUST_BE_NUMERIC_IP" }
    $bytes = $parsed.GetAddressBytes()
    if ($bytes.Length -ne 4) { throw "WINDOWS_M1_REQUIRES_PRIVATE_IPV4" }
    $private = $bytes[0] -eq 10 -or ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or ($bytes[0] -eq 192 -and $bytes[1] -eq 168)
    if (-not $private) { throw "BIND_ADDRESS_MUST_BE_RFC1918_PRIVATE" }
}

function Read-ConfigValue([string]$Path, [string]$Name) {
    $line = Get-Content -LiteralPath $Path | Where-Object { $_ -match "^$([regex]::Escape($Name))=" } | Select-Object -First 1
    if (-not $line) { throw "CONFIG_VALUE_MISSING:$Name" }
    return $line.Substring($Name.Length + 1)
}

function Stop-GeoTasks {
    foreach ($name in @($WorkerTask, $BackendTask)) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($task) { Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue }
    }
    Start-Sleep -Milliseconds 500
    $paths = Get-Paths
    New-Item -ItemType Directory -Force -Path $paths.Run | Out-Null
    Set-Content -LiteralPath (Join-Path $paths.Run "services-stopped") -Value ([DateTime]::UtcNow.ToString("o")) -Encoding UTF8
}

function Register-GeoTasks {
    $paths = Get-Paths
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
    foreach ($row in @(@($BackendTask, "backend"), @($WorkerTask, "worker"))) {
        $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$($paths.Runner)`" -Home `"$($paths.Home)`" -Role $($row[1])"
        $taskAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
        Register-ScheduledTask -TaskName $row[0] -Action $taskAction -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    }
}

function Set-RestrictedAcl([string]$Path) {
    & icacls.exe $Path /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "ACL_CONFIGURATION_FAILED:$Path" }
}

function Install-Geo {
    Assert-Administrator
    if (-not $Source -or -not (Test-Path -LiteralPath $Source -PathType Container)) { throw "PREPARED_SOURCE_REQUIRED" }
    if (-not $ReleaseId -or $ReleaseId -notmatch '^[A-Za-z0-9._-]{1,100}$') { throw "RELEASE_ID_INVALID" }
    if (-not $SourceSha -or $SourceSha -notmatch '^[0-9a-f]{7,40}$') { throw "SOURCE_SHA_INVALID" }
    if (-not $BindAddress -or -not $TrustedCidr) { throw "BIND_ADDRESS_AND_TRUSTED_CIDR_REQUIRED" }
    Assert-PrivateIPv4 $BindAddress
    if ($ProjectId -lt 1) { throw "PROJECT_ID_MUST_BE_POSITIVE" }
    $paths = Get-Paths
    # A database file alone does not carry immutable Evidence or usage-audit
    # ledgers. Never promote it into a runnable company instance.
    if ($DatabaseBackup) { throw "RAW_DATABASE_BACKUP_UNSUPPORTED_USE_FULL_BACKUP" }
    if (-not $RestoreBackup -or -not (Test-Path -LiteralPath $RestoreBackup -PathType Container)) {
        throw "COMPLETE_BACKUP_DIRECTORY_REQUIRED"
    }
    if ((Test-Path -LiteralPath $paths.Home) -and (Get-ChildItem -Force -LiteralPath $paths.Home | Select-Object -First 1)) {
        throw "WINDOWS_HOME_MUST_BE_NEW_OR_EMPTY"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Source "geo-platform\frontend\dist\index.html"))) { throw "RELEASE_FRONTEND_BUILD_REQUIRED" }

    # This helper is stdlib-only. Preflight and restore before installing the
    # application: restore rewrites prepared-source bindings to its target.
    # That target MUST be the final Home, never a subsequently moved stage.
    $lifecycle = Join-Path $Source "geo-platform\backend\scripts\m1_beta_ops.py"
    & $PythonExe $lifecycle preflight --database (Join-Path $RestoreBackup "database.db")
    if ($LASTEXITCODE -ne 0) { throw "BACKUP_DATABASE_PREFLIGHT_FAILED" }
    New-Item -ItemType Directory -Force -Path $paths.Home | Out-Null
    Set-RestrictedAcl $paths.Home
    & $PythonExe $lifecycle restore --backup $RestoreBackup --target-home $paths.Home
    if ($LASTEXITCODE -ne 0) { throw "RESTORE_BACKUP_FAILED" }

    foreach ($directory in @($paths.Home, $paths.Config, $paths.Data, $paths.Logs, $paths.Run, (Join-Path $paths.Home "releases"), (Join-Path $paths.Home "backups"), (Join-Path $paths.Home "evidence"))) {
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
    }
    Set-RestrictedAcl $paths.Home
    $release = Join-Path $paths.Home "releases\$ReleaseId"
    New-Item -ItemType Directory -Force -Path $release | Out-Null
    & robocopy.exe $Source $release /E /R:1 /W:1 /XD .git .venv data evidence logs config run backups runtime browser-profile wenxin-profile /XF .env "*.pyc" "*.pyo" | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "RELEASE_COPY_FAILED:$LASTEXITCODE" }
    New-Item -ItemType Junction -Path $paths.Current -Target $release | Out-Null

    $backend = Join-Path $paths.Current "geo-platform\backend"
    $venv = Join-Path $backend ".venv\Scripts\python.exe"
    & $PythonExe -m venv (Join-Path $backend ".venv")
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venv)) { throw "WINDOWS_VENV_CREATE_FAILED" }
    $requirements = Join-Path $backend "requirements.txt"
    if ($Wheelhouse) {
        & $venv -m pip install --no-index --find-links $Wheelhouse -r $requirements
    } elseif ($AllowDependencyDownload) {
        & $venv -m pip install -r $requirements
    } else {
        throw "WHEELHOUSE_REQUIRED_OR_ALLOW_DEPENDENCY_DOWNLOAD"
    }
    if ($LASTEXITCODE -ne 0) { throw "DEPENDENCY_INSTALL_FAILED" }

    $databaseUrl = "sqlite:///" + ($paths.Database -replace '\\', '/')
    $env:GEO_RELEASE_DATABASE_URL = $databaseUrl
    Push-Location $backend
    try {
        & $venv -m alembic -c alembic.release.ini upgrade head
        if ($LASTEXITCODE -ne 0) { throw "RELEASE_MIGRATION_FAILED" }
        & $venv -c "from app.core.release_database import release_engine; from app.release_schema import validate_release_database; print(validate_release_database(release_engine))"
        if ($LASTEXITCODE -ne 0) { throw "RELEASE_SCHEMA_VALIDATION_FAILED" }
    } finally { Pop-Location }

    @(
        "GEO_RELEASE_DATABASE_URL=$databaseUrl",
        "GEO_RELEASE_ACCESS_CONFIG=$($paths.Access)",
        "GEO_ALLOW_TRUSTED_LAN_HTTP=1",
        "GEO_TRUSTED_LAN_CIDR=$TrustedCidr",
        "GEO_BIND_ADDRESS=$BindAddress",
        "GEO_BETA_PORT=8032",
        "GEO_AGENT_BETA_DAILY_MODEL_CALLS=0",
        "GEO_BETA_SCHEDULED_SAMPLING_ENABLED=0",
        "WENXIN_PROFILE_DIR=$($paths.Data)\wenxin-profile",
        "WENXIN_MAX_CONCURRENCY=1",
        "WENXIN_MAX_RETRIES=0"
    ) | Set-Content -LiteralPath $paths.Env -Encoding UTF8
    & (Join-Path $PSScriptRoot "set-password.ps1") -Home $paths.Home -ProjectId $ProjectId
    Set-RestrictedAcl $paths.Config
    "$ReleaseId / $SourceSha" | Set-Content -LiteralPath (Join-Path $paths.Home "VERSION") -Encoding UTF8
    Register-GeoTasks
    Get-NetFirewallRule -DisplayName $FirewallRule -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $FirewallRule -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8032 -RemoteAddress $TrustedCidr -Profile Domain,Private | Out-Null
    Stop-GeoTasks
    Write-Output "INSTALLED_STOPPED:$($paths.Home)"
}

function Start-Geo {
    Assert-Administrator
    $paths = Get-Paths
    if (-not (Test-Path -LiteralPath $paths.Env)) { throw "WINDOWS_GEO_NOT_INSTALLED" }
    Remove-Item -Force -ErrorAction SilentlyContinue -LiteralPath (Join-Path $paths.Run "services-stopped")
    Start-ScheduledTask -TaskName $BackendTask
    Start-ScheduledTask -TaskName $WorkerTask
    $address = Read-ConfigValue $paths.Env "GEO_BIND_ADDRESS"
    $ready = $false
    foreach ($attempt in 1..120) {
        try {
            $health = Invoke-RestMethod -Uri "http://$address`:8032/api/health" -TimeoutSec 2
            if ($health.status -eq "ok") { $ready = $true; break }
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw "WINDOWS_GEO_HEALTH_TIMEOUT" }
    Write-Output "RUNNING:http://$address`:8032"
}

function Get-GeoStatus {
    $paths = Get-Paths
    $address = if (Test-Path $paths.Env) { Read-ConfigValue $paths.Env "GEO_BIND_ADDRESS" } else { "UNKNOWN" }
    $rows = foreach ($name in @($BackendTask, $WorkerTask)) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        [ordered]@{ name = $name; installed = [bool]$task; state = if ($task) { [string]$task.State } else { "MISSING" } }
    }
    [ordered]@{ home = $paths.Home; url = if ($address -eq "UNKNOWN") { $null } else { "http://$address`:8032" }; tasks = $rows } | ConvertTo-Json -Depth 5
}

switch ($Action) {
    "install" { Install-Geo }
    "start" { Start-Geo }
    "stop" { Assert-Administrator; Stop-GeoTasks; Write-Output "STOPPED" }
    "restart" { Assert-Administrator; Stop-GeoTasks; Start-Geo }
    "status" { Get-GeoStatus }
    "backup" {
        Assert-Administrator
        if (-not $BackupOutput) { throw "BACKUP_OUTPUT_REQUIRED" }
        Stop-GeoTasks
        $paths = Get-Paths
        $python = Join-Path $paths.Current "geo-platform\backend\.venv\Scripts\python.exe"
        & $python (Join-Path $paths.Current "geo-platform\backend\scripts\m1_beta_ops.py") backup --home $paths.Home --output $BackupOutput
        if ($LASTEXITCODE -ne 0) { throw "WINDOWS_BACKUP_FAILED" }
    }
}
