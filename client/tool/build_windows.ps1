param([Parameter(Mandatory=$true)][string]$ApiBaseUrl, [string]$Iscc = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe')
$ErrorActionPreference = 'Stop'
$env:CI = 'true'
Push-Location (Join-Path $PSScriptRoot '..')
try {
  flutter --suppress-analytics pub get --enforce-lockfile
  if ($LASTEXITCODE -ne 0) { throw 'Dependency lock validation failed' }
  flutter --suppress-analytics analyze
  if ($LASTEXITCODE -ne 0) { throw 'Analysis failed' }
  flutter --suppress-analytics test
  if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
  flutter --suppress-analytics build windows --release "--dart-define=API_BASE_URL=$ApiBaseUrl"
  if ($LASTEXITCODE -ne 0) { throw 'Windows build failed' }
  # App-local Microsoft runtime deployment; no elevated VC-redist install.
  $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
  $vsRoot = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
  if (-not $vsRoot) { throw 'Visual C++ installation not found for runtime packaging' }
  $redistRoot = Join-Path $vsRoot 'VC/Redist/MSVC'
  # Redist contains versioned folders plus a 'v143' alias without an x64 subtree; only consider
  # folders that actually carry the x64 CRT so a missing path cannot abort packaging.
  $runtime = Get-ChildItem $redistRoot -Directory |
    Where-Object { Test-Path (Join-Path $_.FullName 'x64') } |
    Sort-Object Name -Descending |
    ForEach-Object { Get-ChildItem (Join-Path $_.FullName 'x64') -Directory -Filter 'Microsoft.VC*.CRT' -ErrorAction SilentlyContinue } |
    Select-Object -First 1
  if (-not $runtime) { throw 'Microsoft x64 app-local VC runtime not found' }
  foreach ($dll in @('msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll')) {
    $source = Join-Path $runtime.FullName $dll
    if (-not (Test-Path $source)) { throw "Required runtime missing: $dll" }
    Copy-Item $source 'build/windows/x64/runner/Release/' -Force
  }
  & $Iscc installer/personal_staffer.iss
  if ($LASTEXITCODE -ne 0) { throw 'Installer packaging failed' }
  Get-ChildItem build/installer/*.exe | Get-FileHash -Algorithm SHA256 | Format-Table
} finally { Pop-Location }
