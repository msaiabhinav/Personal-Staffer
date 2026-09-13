<#
.SYNOPSIS
  Nightly logical backup of the live Personal Staffer database on the owner's laptop.

.DESCRIPTION
  Runs pg_dump (custom format, compressed) inside the running postgres container of the
  live compose project and writes it to %USERPROFILE%\PersonalStafferBackups, keeping the
  newest 14 files. The dump has the same protection as the Docker data disk it comes from
  (the owner's profile on this laptop); the encrypted off-machine path in
  docs/BACKUP_RESTORE.md (restic) is for the hosted phase.

  Restore (clean, isolated database):
    docker compose -p personal-staffer-local -f deployment/compose.local.yml exec -T postgres \
      createdb -U staffer staffer_restore
    docker compose ... exec -T postgres pg_restore -U staffer -d staffer_restore --no-owner < file.dump

.PARAMETER Keep
  Number of newest dumps to keep (default 14).
#>
[CmdletBinding()]
param([int]$Keep = 14, [string]$Mode = 'local')

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$env:STAFFER_ENV_FILE = Join-Path $repo ".env.$Mode"
$project = "personal-staffer-$Mode"  # backup Mode is the compose project suffix: local (owner data) or demo
$compose = Join-Path $repo 'deployment\compose.local.yml'
$dir = Join-Path $env:USERPROFILE 'PersonalStafferBackups'
New-Item -ItemType Directory -Force $dir | Out-Null
$log = Join-Path $dir 'backup.log'
function Note($m) { $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"; Write-Host $line; Add-Content $log $line -Encoding UTF8 }

$target = Join-Path $dir ("staffer-{0}-{1}.dump" -f $Mode, (Get-Date -Format 'yyyyMMdd-HHmmss'))
$engine = $null
try { $engine = docker info --format '{{.ServerVersion}}' 2>$null } catch { $engine = $null }
if (-not $engine) { Note 'Docker engine not running; backup skipped'; exit 2 }

# pg_dump writes binary to stdout; capture it as bytes, never through a text pipeline.
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'docker'
$psi.Arguments = "compose -p $project -f `"$compose`" exec -T postgres pg_dump -U staffer -d staffer -Fc"
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.UseShellExecute = $false
$proc = [System.Diagnostics.Process]::Start($psi)
$out = [System.IO.File]::Create($target)
$proc.StandardOutput.BaseStream.CopyTo($out)
$out.Close()
$stderr = $proc.StandardError.ReadToEnd()
$proc.WaitForExit()
if ($proc.ExitCode -ne 0 -or (Get-Item $target).Length -lt 1024) {
    Remove-Item $target -ErrorAction SilentlyContinue
    Note "backup FAILED (exit $($proc.ExitCode)): $stderr"
    exit 1
}
# A custom-format dump starts with the "PGDMP" magic; anything else is not a backup.
$head = [System.IO.File]::ReadAllBytes($target)[0..4]
if (-not ([System.Text.Encoding]::ASCII.GetString($head) -eq 'PGDMP')) {
    Remove-Item $target -ErrorAction SilentlyContinue
    Note 'backup FAILED: output is not a pg_dump archive'
    exit 1
}
Note ("backup OK {0} ({1:N1} MB)" -f $target, ((Get-Item $target).Length / 1MB))
Get-ChildItem $dir -Filter "staffer-$Mode-*.dump" | Sort-Object Name -Descending | Select-Object -Skip $Keep |
    ForEach-Object { Remove-Item $_.FullName; Note "pruned $($_.Name)" }
exit 0
