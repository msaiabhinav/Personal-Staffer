<#
.SYNOPSIS
  Read-only Windows prerequisite report for the Personal Staffer desktop demo and build.

.DESCRIPTION
  Inspects Git, Docker Desktop (CLI, running engine, Compose, WSL 2), the exact Flutter/Dart
  toolchain, Visual Studio C++ desktop tooling, Windows SDK, CMake/Ninja and Inno Setup 6.
  It never installs, updates or modifies anything. Exit code 0 when every required item is
  present; 1 when a required item is missing or the wrong version.

.PARAMETER Json
  Emit the report as JSON instead of a table.
#>
[CmdletBinding()]
param([switch]$Json)

$ErrorActionPreference = 'Continue'
$RequiredFlutter = '3.47.4'
$RequiredDart = '3.13.3'
$results = New-Object System.Collections.Generic.List[object]

function Add-Result {
    param([string]$Item, [string]$State, [string]$Detail, [bool]$Required = $true)
    $results.Add([pscustomobject]@{ Item = $Item; State = $State; Required = $Required; Detail = $Detail })
}

function Get-CommandPath {
    param([string]$Name)
    try { return (Get-Command $Name -ErrorAction Stop).Source } catch { return $null }
}

function Invoke-Native {
    # Returns [pscustomobject]@{ Output; ExitCode } and never throws for a missing executable.
    param([string]$File, [string[]]$Arguments)
    try {
        $out = & $File @Arguments 2>&1 | ForEach-Object { "$_" }
        return [pscustomobject]@{ Output = ($out -join "`n"); ExitCode = $LASTEXITCODE }
    } catch {
        return [pscustomobject]@{ Output = $_.Exception.Message; ExitCode = -1 }
    }
}

# --- Operating system and shell ---------------------------------------------------------
$os = Get-CimInstance Win32_OperatingSystem
$build = [int]$os.BuildNumber
$osState = 'PASS'
if ($build -lt 19041) { $osState = 'FAIL' }
Add-Result 'Windows' $osState "$($os.Caption) build $($os.BuildNumber) ($($os.OSArchitecture))"
Add-Result 'PowerShell' 'PASS' "$($PSVersionTable.PSVersion) ($($PSVersionTable.PSEdition))"

$drive = Get-PSDrive -Name ($PWD.Drive.Name) -ErrorAction SilentlyContinue
if ($drive) {
    $freeGb = [math]::Round($drive.Free / 1GB, 1)
    $diskState = 'PASS'
    if ($freeGb -lt 20) { $diskState = 'FAIL' } elseif ($freeGb -lt 40) { $diskState = 'WARN' }
    Add-Result 'Disk space' $diskState "$freeGb GB free on $($drive.Name):"
}

# --- Git ---------------------------------------------------------------------------------
$git = Get-CommandPath 'git'
if ($git) {
    Add-Result 'Git' 'PASS' ((Invoke-Native $git @('--version')).Output.Trim())
} else {
    Add-Result 'Git' 'FAIL' 'git is not on PATH. Install Git for Windows.'
}

# --- Docker Desktop ----------------------------------------------------------------------
$docker = Get-CommandPath 'docker'
if (-not $docker) {
    Add-Result 'Docker CLI' 'FAIL' 'docker is not on PATH. Install Docker Desktop.'
    Add-Result 'Docker engine' 'FAIL' 'Not reachable without the Docker CLI.'
    Add-Result 'Docker Compose' 'FAIL' 'Not available without the Docker CLI.'
} else {
    Add-Result 'Docker CLI' 'PASS' ((Invoke-Native $docker @('--version')).Output.Trim())
    $engine = Invoke-Native $docker @('version', '--format', '{{.Server.Version}} ({{.Server.Os}}/{{.Server.Arch}})')
    if ($engine.ExitCode -eq 0 -and $engine.Output.Trim()) {
        Add-Result 'Docker engine' 'PASS' "Running: $($engine.Output.Trim())"
    } else {
        Add-Result 'Docker engine' 'FAIL' 'Engine not reachable. Start Docker Desktop and wait for the WSL 2 engine.'
    }
    $compose = Invoke-Native $docker @('compose', 'version', '--short')
    if ($compose.ExitCode -eq 0 -and $compose.Output.Trim()) {
        $composeVersion = $compose.Output.Trim()
        $composeState = 'PASS'
        if ($composeVersion -notmatch '^v?[2-9]') { $composeState = 'FAIL' }
        Add-Result 'Docker Compose' $composeState "v$($composeVersion.TrimStart('v')) (Compose v2+ required for env_file interpolation)"
    } else {
        Add-Result 'Docker Compose' 'FAIL' 'docker compose plugin missing.'
    }
}

$wsl = Get-CommandPath 'wsl'
if ($wsl) {
    $status = Invoke-Native $wsl @('--status')
    # wsl.exe emits UTF-16 on some hosts; strip NULs so the text is searchable.
    $text = ($status.Output -replace "`0", '')
    if ($status.ExitCode -eq 0 -and $text -match 'Default Version:\s*2') {
        Add-Result 'WSL 2' 'PASS' 'Default WSL version 2'
    } elseif ($status.ExitCode -eq 0) {
        Add-Result 'WSL 2' 'WARN' 'WSL present; default version not reported as 2. Docker Desktop needs the WSL 2 engine.'
    } else {
        Add-Result 'WSL 2' 'FAIL' 'wsl --status failed. Enable WSL 2 for Docker Desktop.'
    }
} else {
    Add-Result 'WSL 2' 'FAIL' 'wsl.exe not found.'
}

# --- Flutter and Dart --------------------------------------------------------------------
$flutter = Get-CommandPath 'flutter'
if (-not $flutter) {
    $flutter = Get-CommandPath 'flutter.bat'
}
if ($flutter) {
    $env:CI = 'true'
    $fv = Invoke-Native $flutter @('--version', '--machine', '--suppress-analytics')
    $flutterVersion = $null
    $dartVersion = $null
    if ($fv.ExitCode -eq 0) {
        try {
            $jsonText = $fv.Output.Substring($fv.Output.IndexOf('{'))
            $parsed = $jsonText | ConvertFrom-Json
            $flutterVersion = $parsed.frameworkVersion
            $dartVersion = $parsed.dartSdkVersion
        } catch { }
    }
    if ($flutterVersion -eq $RequiredFlutter) {
        Add-Result 'Flutter' 'PASS' "Flutter $flutterVersion at $flutter"
    } elseif ($flutterVersion) {
        Add-Result 'Flutter' 'FAIL' "Flutter $flutterVersion found; exactly $RequiredFlutter is required (pubspec.lock is pinned to it)."
    } else {
        Add-Result 'Flutter' 'FAIL' "flutter --version failed at $flutter"
    }
    if ($dartVersion -and $dartVersion.StartsWith($RequiredDart)) {
        Add-Result 'Dart' 'PASS' "Dart $dartVersion"
    } elseif ($dartVersion) {
        Add-Result 'Dart' 'FAIL' "Dart $dartVersion found; $RequiredDart is expected with Flutter $RequiredFlutter."
    } else {
        Add-Result 'Dart' 'FAIL' 'Dart SDK version not reported by Flutter.'
    }
} else {
    Add-Result 'Flutter' 'FAIL' "flutter is not on PATH. Install Flutter $RequiredFlutter stable (Dart $RequiredDart) and add flutter\bin to PATH."
    Add-Result 'Dart' 'FAIL' 'Bundled with Flutter.'
}

# --- Visual Studio C++ desktop tooling ----------------------------------------------------
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vsRoot = $null
if (Test-Path $vswhere) {
    $vsRoot = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null | Select-Object -First 1)
    $vsName = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property displayName 2>$null | Select-Object -First 1)
    $vsVersion = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationVersion 2>$null | Select-Object -First 1)
    if ($vsRoot) {
        Add-Result 'Visual Studio C++' 'PASS' "$vsName $vsVersion at $vsRoot"
    } else {
        Add-Result 'Visual Studio C++' 'FAIL' 'Visual Studio found but the "Desktop development with C++" workload (VC x64 tools) is missing.'
    }
} else {
    Add-Result 'Visual Studio C++' 'FAIL' 'Visual Studio / Build Tools not installed (vswhere.exe absent). Install "Desktop development with C++" including Windows 10/11 SDK and C++ CMake tools.'
}

# ATL headers are required by the flutter_secure_storage and flutter_local_notifications
# Windows plugins (atlbase.h / atlstr.h). The C++ workload does not include them by default.
if ($vsRoot) {
    $atl = Get-ChildItem (Join-Path $vsRoot 'VC\Tools\MSVC') -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName 'atlmfc\include\atlbase.h' } | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($atl) {
        Add-Result 'C++ ATL' 'PASS' $atl
    } else {
        Add-Result 'C++ ATL' 'FAIL' 'Component Microsoft.VisualStudio.Component.VC.ATL missing; Windows plugin builds fail with "Cannot open include file atlbase.h".'
    }
} else {
    Add-Result 'C++ ATL' 'FAIL' 'Requires the Visual Studio C++ toolchain first.'
}

$sdkRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\Include'
if (Test-Path $sdkRoot) {
    $sdks = Get-ChildItem $sdkRoot -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^10\.' } | Sort-Object Name -Descending
    if ($sdks) {
        Add-Result 'Windows SDK' 'PASS' ("Installed: " + (($sdks | Select-Object -First 3 | ForEach-Object Name) -join ', '))
    } else {
        Add-Result 'Windows SDK' 'FAIL' 'No Windows 10/11 SDK include directories found.'
    }
} else {
    Add-Result 'Windows SDK' 'FAIL' 'Windows 10/11 SDK not installed.'
}

$cmake = Get-CommandPath 'cmake'
if (-not $cmake -and $vsRoot) {
    $candidate = Join-Path $vsRoot 'Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
    if (Test-Path $candidate) { $cmake = $candidate }
}
if ($cmake) {
    Add-Result 'CMake' 'PASS' (((Invoke-Native $cmake @('--version')).Output -split "`n")[0].Trim() + " ($cmake)")
} else {
    Add-Result 'CMake' 'FAIL' 'CMake not found on PATH or inside Visual Studio (C++ CMake tools for Windows component).'
}

$ninja = Get-CommandPath 'ninja'
if (-not $ninja -and $vsRoot) {
    $candidate = Join-Path $vsRoot 'Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe'
    if (Test-Path $candidate) { $ninja = $candidate }
}
if ($ninja) {
    Add-Result 'Ninja' 'PASS' ("ninja " + (Invoke-Native $ninja @('--version')).Output.Trim() + " ($ninja)")
} else {
    Add-Result 'Ninja' 'FAIL' 'Ninja not found; Flutter Windows builds use the Visual Studio generator but Ninja ships with the C++ CMake tools component.'
}

# --- Inno Setup 6 (only needed for installer packaging, Phase E) -------------------------
$iscc = Get-CommandPath 'iscc'
if (-not $iscc) {
    foreach ($candidate in @(
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'))) {
        if (Test-Path $candidate) { $iscc = $candidate; break }
    }
}
if ($iscc) {
    Add-Result 'Inno Setup 6' 'PASS' $iscc $false
} else {
    Add-Result 'Inno Setup 6' 'WARN' 'Not installed. Needed only for client\tool\build_windows.ps1 installer packaging.' $false
}

# --- Report ------------------------------------------------------------------------------
$requiredFailures = @($results | Where-Object { $_.Required -and $_.State -eq 'FAIL' })
if ($Json) {
    [pscustomobject]@{
        checked_at = (Get-Date).ToUniversalTime().ToString('o')
        required_flutter = $RequiredFlutter
        required_dart = $RequiredDart
        ok = ($requiredFailures.Count -eq 0)
        results = $results
    } | ConvertTo-Json -Depth 5
} else {
    $results | Format-Table -AutoSize -Wrap Item, State, Required, Detail | Out-String -Width 200 | Write-Host
    if ($requiredFailures.Count -eq 0) {
        Write-Host 'All required desktop prerequisites are present.' -ForegroundColor Green
    } else {
        Write-Host "Missing or incorrect required prerequisites: $($requiredFailures.Count). This script installs nothing; review each FAIL row." -ForegroundColor Yellow
    }
}
if ($requiredFailures.Count -gt 0) { exit 1 }
exit 0
