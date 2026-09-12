<#
.SYNOPSIS
  One complete Windows desktop verification loop (handoff Phase D), with retained evidence.

.DESCRIPTION
  Runs, in order: frozen-lock validation (Flutter), backend Ruff lint/format (host, CI-equivalent),
  clean-database Alembic upgrade, the complete backend pytest suite on real PostgreSQL/Redis with
  TEST_DATABASE_URL (no hidden skips), policy replay, demo HTTP smoke, Flutter analyzer and tests,
  Windows debug and release builds, the encrypted-storage integration test on the device, a secret
  scan of the release directory, and `git diff --check`. The demo backend must already be running
  (scripts\start_desktop_demo.ps1 -BackendOnly). Nothing is installed or modified outside build/.

  Evidence: docs\verification\windows-desktop-loop-<N>.json and .log. Existing files are never
  overwritten; a rerun of the same pass number gets a timestamp suffix.

.PARAMETER PassNumber
  Loop number recorded in the evidence file names (1, 2, ...).

.PARAMETER SkipIntegration
  Skip the on-device integration test (it needs no running app instance; the single-instance guard
  forwards the launch otherwise).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][int]$PassNumber,
    [switch]$SkipIntegration
)

$ErrorActionPreference = 'Continue'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Client = Join-Path $RepoRoot 'client'
$Backend = Join-Path $RepoRoot 'backend'
$Evidence = Join-Path $RepoRoot 'docs\verification'
$ComposeFile = Join-Path $RepoRoot 'deployment\compose.local.yml'
$ProjectName = 'personal-staffer-demo'
$ApiPort = if ($env:STAFFER_API_PORT) { [int]$env:STAFFER_API_PORT } else { 5555 }
$ApiBase = "http://127.0.0.1:$ApiPort"
$TestDb = 'postgresql+psycopg://staffer:staffer-local@postgres:5432/staffer_loop'
$env:CI = 'true'
$env:STAFFER_ENV_FILE = Join-Path $RepoRoot '.env.demo'
$env:STAFFER_API_PORT = "$ApiPort"

New-Item -ItemType Directory -Force $Evidence | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$base = "windows-desktop-loop-$PassNumber"
if (Test-Path (Join-Path $Evidence "$base.json")) { $base = "$base-$stamp" }
$LogPath = Join-Path $Evidence "$base.log"
$JsonPath = Join-Path $Evidence "$base.json"
$steps = New-Object System.Collections.Generic.List[object]

function Write-Log {
    param([string]$Text, [string]$Color = 'White')
    Add-Content -Path $LogPath -Value $Text -Encoding UTF8
    Write-Host $Text -ForegroundColor $Color
}

function Invoke-Step {
    param([string]$Name, [string]$WorkingDirectory, [scriptblock]$Command, [string]$CommandText)
    $started = Get-Date
    Write-Log "==> [$Name] $CommandText" 'Cyan'
    Push-Location $WorkingDirectory
    $output = @()
    try {
        $global:LASTEXITCODE = 0
        $output = & $Command 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } catch {
        $output += $_.Exception.Message
        $code = 1
    } finally {
        Pop-Location
    }
    $output | Out-File -FilePath $LogPath -Append -Encoding utf8
    $summary = ($output | Select-Object -Last 3) -join ' | '
    $result = [pscustomobject]@{
        step = $Name; command = $CommandText; working_directory = $WorkingDirectory
        exit_code = $code; seconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
        tail = $summary
    }
    $steps.Add($result)
    $state = if ($code -eq 0) { 'PASS' } else { 'FAIL' }
    Write-Log "    $state (exit $code, $($result.seconds)s)" $(if ($code -eq 0) { 'Green' } else { 'Red' })
    return $code
}

function Invoke-Compose {
    param([string[]]$Arguments)
    & docker (@('compose', '-p', $ProjectName, '-f', $ComposeFile) + $Arguments)
}

"Windows desktop verification loop $PassNumber at $stamp" | Out-File -FilePath $LogPath -Encoding utf8

# The loop relinks build\windows\...\personal_staffer.exe and launches the integration test; a running
# instance locks the binary (LNK1168) and absorbs the test launch through the single-instance guard.
if (Get-Process personal_staffer -ErrorAction SilentlyContinue) {
    Write-Log 'Personal Staffer is running. Close it (tray: Exit) before running a verification loop.' 'Red'
    exit 2
}

# 0. Environment facts
Invoke-Step 'prerequisites' $RepoRoot { powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $RepoRoot 'scripts\check_desktop_prerequisites.ps1') } 'scripts\check_desktop_prerequisites.ps1' | Out-Null
Invoke-Step 'git-status' $RepoRoot { git status --short --branch; git rev-parse HEAD } 'git status --short --branch; git rev-parse HEAD' | Out-Null

# 1. Frozen dependency restore
Invoke-Step 'flutter-lock' $Client { flutter --suppress-analytics pub get --enforce-lockfile } 'flutter pub get --enforce-lockfile' | Out-Null

# 2. Backend lint and format (host ruff; CI-equivalent invocation from backend/)
$ruff = Join-Path (py -3.12 -c "import sysconfig;print(sysconfig.get_path('scripts','nt_user'))") 'ruff.exe'
if (-not (Test-Path $ruff)) { $ruff = 'ruff' }
Invoke-Step 'ruff-check' $Backend { & $ruff check --no-cache app tests ../scripts } 'ruff check app tests ../scripts' | Out-Null
Invoke-Step 'ruff-format' $Backend { & $ruff format --check --no-cache app tests ../scripts } 'ruff format --check app tests ../scripts' | Out-Null

# 3. Clean database + explicit migration + complete suite on real PostgreSQL/Redis
Invoke-Step 'backend-image' $RepoRoot { Invoke-Compose @('build', '-q', 'api') } 'docker compose build api' | Out-Null
Invoke-Step 'clean-database' $RepoRoot {
    Invoke-Compose @('exec', '-T', 'postgres', 'psql', '-U', 'staffer', '-d', 'staffer', '-v', 'ON_ERROR_STOP=1', '-c', 'DROP DATABASE IF EXISTS staffer_loop WITH (FORCE);', '-c', 'CREATE DATABASE staffer_loop;')
} 'psql: DROP DATABASE IF EXISTS staffer_loop; CREATE DATABASE staffer_loop' | Out-Null
Invoke-Step 'alembic-clean' $RepoRoot { Invoke-Compose @('run', '--rm', '--no-deps', '-T', '-e', "DATABASE_URL=$TestDb", 'api', 'alembic', 'upgrade', 'head') } 'alembic upgrade head (clean staffer_loop)' | Out-Null
Invoke-Step 'backend-pytest' $RepoRoot { Invoke-Compose @('run', '--rm', '--no-deps', '-T', '-e', "TEST_DATABASE_URL=$TestDb", 'api', 'pytest', '-p', 'no:cacheprovider', '-ra') } 'pytest -ra (TEST_DATABASE_URL=staffer_loop)' | Out-Null
Invoke-Step 'policy-replay' $RepoRoot { Invoke-Compose @('run', '--rm', '--no-deps', '-T', 'api', 'python', '-m', 'app.cli', 'replay-fixtures') } 'python -m app.cli replay-fixtures' | Out-Null
Invoke-Step 'demo-smoke' $RepoRoot { Invoke-Compose @('run', '--rm', '--no-deps', '-T', '-e', "DATABASE_URL=$TestDb", '-e', 'APP_ENV=local', '-e', 'DEMO_MODE=true', '-e', 'PYTHONPATH=.', 'api', 'python', '/scripts/smoke_demo.py') } 'python /scripts/smoke_demo.py (staffer_loop)' | Out-Null

# 4. Live API checks against the running demo backend
Invoke-Step 'http-checks' $RepoRoot {
    foreach ($probe in @(@('/api/v1/health/live', 200), @('/api/v1/health/ready', 200), @('/api/v1/version', 200), @('/api/v1/jobs', 401), @('/openapi.json', 404))) {
        try { $code = (Invoke-WebRequest -Uri "$ApiBase$($probe[0])" -UseBasicParsing -TimeoutSec 5).StatusCode } catch { $code = [int]$_.Exception.Response.StatusCode }
        "$($probe[0]) -> $code (expected $($probe[1]))"
        if ($code -ne $probe[1]) { $global:LASTEXITCODE = 1 }
    }
} "GET live/ready/version/jobs/openapi on $ApiBase" | Out-Null

# 5. Flutter analyzer, tests, builds
Invoke-Step 'flutter-analyze' $Client { flutter --suppress-analytics analyze } 'flutter analyze' | Out-Null
Invoke-Step 'flutter-test' $Client { flutter --suppress-analytics test } 'flutter test' | Out-Null
Invoke-Step 'windows-debug-build' $Client { flutter --suppress-analytics build windows --debug "--dart-define=API_BASE_URL=$ApiBase" '--dart-define=DEMO_MODE=true' } 'flutter build windows --debug' | Out-Null
Invoke-Step 'windows-release-build' $Client { flutter --suppress-analytics build windows --release "--dart-define=API_BASE_URL=$ApiBase" '--dart-define=DEMO_MODE=true' } 'flutter build windows --release' | Out-Null

# 6. Device integration test (encrypted storage on Windows)
if ($SkipIntegration) {
    $steps.Add([pscustomobject]@{ step = 'device-integration'; command = 'flutter test integration_test/device_storage_test.dart -d windows'; working_directory = $Client; exit_code = -1; seconds = 0; tail = 'SKIPPED by -SkipIntegration (not a pass)' })
} else {
    Invoke-Step 'device-integration' $Client { flutter --suppress-analytics test integration_test/device_storage_test.dart -d windows "--dart-define=API_BASE_URL=$ApiBase" } 'flutter test integration_test/device_storage_test.dart -d windows' | Out-Null
}

# 7. Artifact inspection and secret scan of the release directory
Invoke-Step 'release-artifacts' $Client {
    Get-ChildItem build\windows\x64\runner\Release -File | ForEach-Object { "$($_.Name) $($_.Length) bytes" }
    (Get-FileHash build\windows\x64\runner\Release\personal_staffer.exe -Algorithm SHA256).Hash
} 'list + SHA256 of Release\personal_staffer.exe' | Out-Null
Invoke-Step 'secret-scan' $Client {
    $patterns = 'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY', 'AIza[0-9A-Za-z_-]{30,}', 'client_secret', 'GOCSPX-', 'sk_live_', 'xox[baprs]-'
    $hits = Get-ChildItem build\windows\x64\runner\Release -Recurse -File | Select-String -Pattern $patterns -SimpleMatch:$false -List -ErrorAction SilentlyContinue
    if ($hits) { $hits | ForEach-Object { "$($_.Path):$($_.LineNumber)" }; $global:LASTEXITCODE = 1 } else { 'No recognized secret patterns in the release directory (bounded pattern scan).' }
} 'pattern scan of Release\ for private keys / OAuth secrets' | Out-Null
Invoke-Step 'git-diff-check' $RepoRoot { git diff --check; if ($LASTEXITCODE -eq 0) { 'clean' } } 'git diff --check' | Out-Null

# Summary
$failed = @($steps | Where-Object { $_.exit_code -ne 0 -and $_.exit_code -ne -1 })
$skipped = @($steps | Where-Object { $_.exit_code -eq -1 })
$pytestLine = ($steps | Where-Object step -eq 'backend-pytest').tail
[pscustomobject]@{
    pass_number = $PassNumber
    started_utc = $stamp
    commit = (git -C $RepoRoot rev-parse HEAD)
    branch = (git -C $RepoRoot rev-parse --abbrev-ref HEAD)
    host = "$env:COMPUTERNAME / $((Get-CimInstance Win32_OperatingSystem).Caption) $((Get-CimInstance Win32_OperatingSystem).BuildNumber)"
    api_base = $ApiBase
    steps = $steps
    failed_steps = @($failed | ForEach-Object step)
    skipped_steps = @($skipped | ForEach-Object step)
    backend_pytest_summary = $pytestLine
    result = $(if ($failed.Count -eq 0) { 'PASS' } else { 'FAIL' })
} | ConvertTo-Json -Depth 6 | Out-File -FilePath $JsonPath -Encoding utf8

Write-Host ''
Write-Host "Loop $PassNumber result: $(if ($failed.Count -eq 0) { 'PASS' } else { 'FAIL' }) - $($steps.Count) steps, $($failed.Count) failed, $($skipped.Count) skipped (skips are not passes)." -ForegroundColor ($(if ($failed.Count -eq 0) { 'Green' } else { 'Red' }))
Write-Host "Evidence: $JsonPath"
if ($failed.Count -gt 0) { exit 1 }
exit 0
