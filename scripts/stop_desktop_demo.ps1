<#
.SYNOPSIS
  Stop the isolated synthetic desktop demo backend. The demo PostgreSQL/Redis volumes are kept.

.PARAMETER DeleteData
  Also remove the demo database and Redis volumes. Asks for confirmation unless -Force is given.

.PARAMETER Force
  Skip the confirmation prompt when -DeleteData is used.
#>
[CmdletBinding()]
param(
    [switch]$DeleteData,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ComposeFile = Join-Path $RepoRoot 'deployment\compose.local.yml'
$EnvDemo = Join-Path $RepoRoot '.env.demo'
$ProjectName = 'personal-staffer-demo'

& docker version --format '{{.Server.Version}}' *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker engine is not reachable; nothing to stop.' }

# Compose validates env_file paths even for `down`; point at the demo file (or the example when it
# was already removed). The real .env is never referenced.
if (Test-Path $EnvDemo) { $env:STAFFER_ENV_FILE = $EnvDemo } else { $env:STAFFER_ENV_FILE = (Join-Path $RepoRoot '.env.example') }

$arguments = @('compose', '-p', $ProjectName, '-f', $ComposeFile, 'down', '--remove-orphans')
if ($DeleteData) {
    if (-not $Force) {
        $answer = Read-Host "Delete the demo PostgreSQL and Redis volumes for project '$ProjectName'? Type DELETE to confirm"
        if ($answer -ne 'DELETE') { Write-Host 'Volumes kept; containers will still be stopped.'; $DeleteData = $false }
    }
}
if ($DeleteData) { $arguments += '--volumes' }

Write-Host "==> docker $($arguments -join ' ')" -ForegroundColor Cyan
& docker @arguments
if ($LASTEXITCODE -ne 0) { throw "docker compose down failed (exit $LASTEXITCODE)" }

if ($DeleteData) {
    Write-Host 'Demo containers stopped and demo volumes deleted.' -ForegroundColor Green
} else {
    Write-Host "Demo containers stopped. Volumes '${ProjectName}_pgdata' and '${ProjectName}_redisdata' are preserved; rerun start_desktop_demo.ps1 to resume." -ForegroundColor Green
}
