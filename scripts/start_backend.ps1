<#
.SYNOPSIS
  Bring the Personal Staffer backend back: repair/start Docker Desktop if needed, then
  start the compose project and wait until the API answers.

.DESCRIPTION
  Used by the desktop app's "Restart backend" button and by hand. Idempotent: running it
  while everything is healthy just confirms the API. Never resets Docker or touches data.

.PARAMETER Mode
  live (default, .env.local) or demo (.env.demo).
#>
[CmdletBinding()]
param([ValidateSet('live', 'demo')][string]$Mode = 'live')

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
# The live owner data lives in compose project "personal-staffer-local" (.env.local); demo in
# "personal-staffer-demo". A wrong project name would silently create an empty second stack.
$envFile = if ($Mode -eq 'live') { '.env.local' } else { '.env.demo' }
$project = if ($Mode -eq 'live') { 'personal-staffer-local' } else { 'personal-staffer-demo' }
$env:STAFFER_ENV_FILE = Join-Path $repo $envFile
$compose = Join-Path $repo 'deployment\compose.local.yml'
$log = Join-Path $env:LOCALAPPDATA 'PersonalStaffer\start_backend.log'
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
function Note($m) { $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"; Write-Host $line; Add-Content $log $line -Encoding UTF8 }

if (-not (Test-Path $env:STAFFER_ENV_FILE)) { Note "missing $envFile"; exit 3 }
$engine = $null
try { $engine = docker info --format '{{.ServerVersion}}' 2>$null } catch { $engine = $null }
if (-not $engine) {
    Note 'Docker engine not running; repairing and starting Docker Desktop'
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'repair_docker_sockets.ps1')
    if ($LASTEXITCODE -ne 0) { Note "Docker Desktop did not start (exit $LASTEXITCODE)"; exit 2 }
}
Note "docker compose -p $project up -d"
& docker compose -p $project -f $compose up -d
if ($LASTEXITCODE -ne 0) { Note "docker compose up failed (exit $LASTEXITCODE)"; exit 1 }
$port = 5555
for ($i = 0; $i -lt 36; $i++) {
    Start-Sleep -Seconds 5
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://127.0.0.1:$port/api/v1/health/ready"
        if ($r.StatusCode -eq 200) { Note "API ready after $(($i + 1) * 5)s"; exit 0 }
    } catch { }
}
Note 'API not ready after 3 minutes'
exit 1
