<#
.SYNOPSIS
  Builds the chat2api Windows executable and optionally launches it detached.

.DESCRIPTION
  Creates the Tauri release bundle. The release executable is a GUI subsystem
  app, so neither it nor the Python sidecar it starts opens a console window.
  Use -Background to return to PowerShell immediately after launch.

.PARAMETER Background
  Launch the resulting executable as a detached background process.

.PARAMETER NoRun
  Build only; do not launch the executable.

.PARAMETER Port
  Optionally pin the locally bound chat2api backend port.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\desktop\scripts\build-and-run.ps1 -Background
#>

param(
    [switch]$Background,
    [switch]$NoRun,
    [ValidateRange(1, 65535)]
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
$DesktopDir = Split-Path -Parent $ScriptDir
$RepoRoot = Split-Path -Parent $DesktopDir
$ReleaseDir = Join-Path $DesktopDir "src-tauri\target\release"

function Test-CommandExists([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

if (-not (Test-CommandExists "npm")) {
    throw "npm was not found. Run .\desktop\scripts\setup-and-run.ps1 first."
}

if (-not (Test-CommandExists "python")) {
    throw "Python was not found. Run .\desktop\scripts\setup-and-run.ps1 first."
}

Push-Location $RepoRoot
try {
    & python -c "import chat2api, playwright" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "chat2api or Playwright is not installed. Run .\desktop\scripts\setup-and-run.ps1 first."
    }
} finally {
    Pop-Location
}

Push-Location $DesktopDir
try {
    if (-not (Test-Path (Join-Path $DesktopDir "node_modules"))) {
        npm install
        if ($LASTEXITCODE -ne 0) { throw "npm install failed." }
    }

    npm run tauri build
    if ($LASTEXITCODE -ne 0) { throw "Tauri release build failed." }
} finally {
    Pop-Location
}

$ExePath = Get-ChildItem -Path $ReleaseDir -Filter "*.exe" -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $ExePath) { throw "Build completed but no release executable was found in: $ReleaseDir" }

Write-Host "Build complete: $ExePath" -ForegroundColor Green

if ($NoRun) { exit 0 }

$previousPort = $env:CHAT2API_PORT
try {
    if ($Port -ne 0) { $env:CHAT2API_PORT = "$Port" }
    if ($Background) {
        $process = Start-Process -FilePath $ExePath -WindowStyle Hidden -PassThru
    } else {
        & $ExePath
    }
} finally {
    if ($null -eq $previousPort) { Remove-Item Env:\CHAT2API_PORT -ErrorAction SilentlyContinue }
    else { $env:CHAT2API_PORT = $previousPort }
}
if ($Background) {
    Write-Host "chat2api is running in the background (PID $($process.Id))." -ForegroundColor Green
}
