[CmdletBinding()]
param(
    [string]$Home = "$env:ProgramData\GEO Beta",
    [int]$ProjectId = 1
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$python = Join-Path $Home "current\geo-platform\backend\.venv\Scripts\python.exe"
$script = Join-Path $Home "current\geo-platform\backend\scripts\create_shared_password_config.py"
$config = Join-Path $Home "config\release-access.json"
$first = Read-Host "设置 GEO 试用登录密码（至少 12 位）" -AsSecureString
$second = Read-Host "再次输入登录密码" -AsSecureString
$firstPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($first)
$secondPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($second)
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($firstPtr)
    $confirm = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secondPtr)
    if ($plain -cne $confirm) { throw "PASSWORD_CONFIRMATION_MISMATCH" }
    $arguments = @($script, "--config", $config, "--project-id", $ProjectId, "--password-stdin")
    if (Test-Path -LiteralPath $config) { $arguments += "--replace" }
    $plain | & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "PASSWORD_CONFIGURATION_FAILED" }
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($firstPtr)
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secondPtr)
    $plain = $null
    $confirm = $null
}
& icacls.exe (Join-Path $Home "config") /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "PASSWORD_CONFIG_ACL_FAILED" }
Write-Output "PASSWORD_UPDATED_SESSIONS_REVOKED"
