[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Home,
    [Parameter(Mandatory = $true)][ValidateSet("backend", "worker")][string]$Role
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$envFile = Join-Path $Home "config\backend.env"
foreach ($line in Get-Content -LiteralPath $envFile) {
    if (-not $line -or $line.StartsWith("#")) { continue }
    $parts = $line.Split("=", 2)
    if ($parts.Length -ne 2 -or $parts[0] -notmatch '^[A-Z][A-Z0-9_]*$') { throw "INVALID_ENV_LINE" }
    [Environment]::SetEnvironmentVariable($parts[0], $parts[1], "Process")
}
$backend = Join-Path $Home "current\geo-platform\backend"
$python = Join-Path $backend ".venv\Scripts\python.exe"
Set-Location $backend
if ($Role -eq "backend") {
    & $python -m uvicorn app.release_main:app --host $env:GEO_BIND_ADDRESS --port $env:GEO_BETA_PORT --workers 1
} else {
    & $python scripts\release_worker.py --interval 10
}
exit $LASTEXITCODE
