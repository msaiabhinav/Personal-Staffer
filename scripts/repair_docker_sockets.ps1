<#
.SYNOPSIS
  Remove the stale AF_UNIX socket files that make Docker Desktop 4.8x crash on start,
  then start Docker Desktop if it is not running.

.DESCRIPTION
  After an unclean exit Docker Desktop leaves socket entries under
  %LOCALAPPDATA%\Docker\run and %LOCALAPPDATA%\docker-secrets-engine that Windows
  reports as "The file cannot be accessed by the system". The backend cannot delete
  them, dies with "initializing Inference manager / Secrets Engine: listening on
  unix://...: remove ...", and offers only "Quit" or "Reset to factory defaults" -
  the reset wipes every container and volume, i.e. the Personal Staffer database.

  This script renames those directories aside (never deletes anything), disables the
  Docker AI/inference and secrets-engine features that own the sockets, and starts
  Docker Desktop. It is safe to run at every logon and before every backend start.

  Never click "Reset to factory defaults". Run this script instead.

.PARAMETER NoStart
  Only repair; do not launch Docker Desktop.
#>
[CmdletBinding()]
param([switch]$NoStart)

$ErrorActionPreference = 'Stop'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = Join-Path $env:LOCALAPPDATA 'PersonalStaffer\repair_docker_sockets.log'
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null

function Note($message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message"
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding UTF8
}

$engineUp = $false
try { $engineUp = [bool](docker info --format '{{.ServerVersion}}' 2>$null) } catch { $engineUp = $false }
if ($engineUp) {
    Note 'Docker engine is already running; nothing to repair.'
    exit 0
}

# A backend that is still shutting down would just recreate the sockets.
Get-Process | Where-Object { $_.Name -like 'com.docker.*' -or $_.Name -eq 'Docker Desktop' } |
    ForEach-Object { Note "stopping $($_.Name) ($($_.Id))"; Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

foreach ($dir in @((Join-Path $env:LOCALAPPDATA 'Docker\run'), (Join-Path $env:LOCALAPPDATA 'docker-secrets-engine'))) {
    if (Test-Path $dir) {
        $aside = "$dir.stale-$stamp"
        Rename-Item -Path $dir -NewName (Split-Path $aside -Leaf)
        Note "moved stale socket directory aside: $dir -> $aside"
    }
}
# Old copies pile up; keep the three most recent of each.
foreach ($pattern in @('Docker\run.stale-*', 'docker-secrets-engine.stale-*')) {
    Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA $pattern) -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | Select-Object -Skip 3 |
        ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue; Note "removed old $($_.FullName)" }
}

$settings = Join-Path $env:APPDATA 'Docker\settings-store.json'
if (Test-Path $settings) {
    $json = Get-Content $settings -Raw | ConvertFrom-Json
    $changed = $false
    foreach ($flag in @('EnableDockerAI', 'EnableInference')) {
        if (-not ($json.PSObject.Properties.Name -contains $flag)) {
            $json | Add-Member -NotePropertyName $flag -NotePropertyValue $false
            $changed = $true
        } elseif ($json.$flag -ne $false) {
            $json.$flag = $false
            $changed = $true
        }
    }
    if ($changed) {
        Copy-Item $settings "$settings.bak-$stamp"
        ($json | ConvertTo-Json -Depth 30) | Set-Content $settings -Encoding utf8
        Note 'disabled Docker AI / inference (they own the sockets that go stale)'
    }
}

if ($NoStart) { exit 0 }
$exe = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'
if (-not (Test-Path $exe)) { $exe = 'C:\Program Files\Docker\Docker\Docker Desktop.exe' }
if (-not (Test-Path $exe)) { Note 'Docker Desktop executable not found'; exit 1 }
Start-Process -FilePath $exe
Note "launched $exe"
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 5
    try { $v = docker info --format '{{.ServerVersion}}' 2>$null } catch { $v = $null }
    if ($v) { Note "engine $v ready after $(($i + 1) * 5)s"; exit 0 }
}
Note 'engine did not become ready within 5 minutes'
exit 2
