<#
.SYNOPSIS
  Sets up everything chat2api desktop needs (Node.js, Rust, MSVC C++ build
  tools, WebView2, the Python backend) and then launches `npm run tauri dev`.

.DESCRIPTION
  Every step checks first and skips itself if already satisfied, so this is
  safe to re-run any time (e.g. after a partial/failed run, or just to launch
  the app day to day).

  Some steps install machine-wide components (MSVC Build Tools, WebView2,
  Python) via winget and may need an elevated (Run as Administrator)
  PowerShell to succeed. Rust (via rustup) and Node.js do not need elevation.

.PARAMETER NoRun
  Only run the setup checks/installs; don't launch `npm run tauri dev`
  afterwards.

.PARAMETER Port
  Fixed port for the chat2api backend the app spawns. If omitted, you're
  prompted for one interactively (blank = auto-pick a free port, which is
  also the default in a non-interactive run). Windows reserves some TCP port
  ranges for its own use (Hyper-V/WSL) that silently fail to bind -- notably
  8100 on some machines -- so a requested port that falls in one of those
  ranges is rejected and the script falls back to auto-pick instead.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\desktop\scripts\setup-and-run.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\desktop\scripts\setup-and-run.ps1 -Port 8200
#>

param(
    [switch]$NoRun,
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopDir = Split-Path -Parent $ScriptDir
$RepoRoot = Split-Path -Parent $DesktopDir

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Write-Ok($msg) {
    Write-Host "    ok: $msg" -ForegroundColor Green
}

function Write-Skip($msg) {
    Write-Host "    skip: $msg" -ForegroundColor DarkGray
}

function Write-Note($msg) {
    Write-Host "    $msg" -ForegroundColor Yellow
}

function Test-CommandExists([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-WingetInstall([string[]]$WingetArgs) {
    if (-not (Test-CommandExists "winget")) {
        Write-Note "winget not found on this machine -- install the component above manually."
        return $false
    }
    $allArgs = $WingetArgs + @("--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity")
    & winget @allArgs
    return $true
}

Write-Host "chat2api desktop -- environment setup" -ForegroundColor White
Write-Host "Repo root:       $RepoRoot"
Write-Host "Desktop project: $DesktopDir"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Note "Not running as Administrator. Node/Rust installs don't need it, but the MSVC Build Tools / WebView2 / Python installs below might fail without it. Re-run elevated if any of those steps report a failure."
}

# ---------------------------------------------------------------------------
# 1. Node.js / npm
# ---------------------------------------------------------------------------
Write-Step "Node.js / npm"
if (Test-CommandExists "npm") {
    Write-Ok "npm $(npm -v)"
} else {
    Write-Host "    not found -- installing Node.js LTS via winget..."
    Invoke-WingetInstall @("install", "--id", "OpenJS.NodeJS.LTS", "-e") | Out-Null
    if (-not (Test-CommandExists "npm")) {
        Write-Note "Node.js was installed but isn't on PATH in this session yet. Close this window, open a fresh PowerShell, and re-run this script."
        exit 1
    }
    Write-Ok "npm $(npm -v)"
}

# ---------------------------------------------------------------------------
# 2. Rust toolchain (rustup/cargo)
# ---------------------------------------------------------------------------
Write-Step "Rust toolchain (rustup / cargo)"
$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if ((Test-Path (Join-Path $cargoBin "cargo.exe")) -and ($env:Path -notlike "*$cargoBin*")) {
    $env:Path = "$cargoBin;$env:Path"
}

if (Test-CommandExists "cargo") {
    Write-Ok "$(cargo -V)"
} else {
    Write-Host "    not found -- downloading rustup-init..."
    $rustupInit = Join-Path $env:TEMP "rustup-init.exe"
    Invoke-WebRequest -Uri "https://win.rustup.rs/x86_64" -OutFile $rustupInit -UseBasicParsing
    Write-Host "    running rustup-init (stable-msvc toolchain, non-interactive)..."
    & $rustupInit -y --default-toolchain stable-msvc --profile default
    Remove-Item $rustupInit -ErrorAction SilentlyContinue

    if ($env:Path -notlike "*$cargoBin*") { $env:Path = "$cargoBin;$env:Path" }

    if (Test-CommandExists "cargo") {
        Write-Ok "$(cargo -V)"
    } else {
        Write-Note "Rust install did not complete. Install manually from https://www.rust-lang.org/tools/install and re-run this script."
        exit 1
    }
}

# ---------------------------------------------------------------------------
# 3. MSVC C++ Build Tools (the linker the stable-msvc Rust toolchain needs)
# ---------------------------------------------------------------------------
Write-Step "MSVC C++ Build Tools (Rust's Windows linker)"
$vswhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"

function Test-VCTools {
    if (-not (Test-Path $vswhere)) { return $false }
    $found = & $vswhere -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    return [bool]$found
}

if (Test-VCTools) {
    Write-Ok "MSVC C++ build tools present"
} else {
    Write-Note "not found -- installing Visual Studio Build Tools (C++ workload) via winget. This is a multi-GB download and can take a while."
    Invoke-WingetInstall @(
        "install", "--id", "Microsoft.VisualStudio.2022.BuildTools", "-e",
        "--override", "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
    ) | Out-Null
    if (Test-VCTools) {
        Write-Ok "MSVC C++ build tools installed"
    } else {
        Write-Note "Could not confirm the install. If 'npm run tauri dev' fails at the Rust link step, install manually: https://visualstudio.microsoft.com/visual-cpp-build-tools/ (select the 'Desktop development with C++' workload), then re-run this script."
    }
}

# ---------------------------------------------------------------------------
# 4. WebView2 runtime (Tauri's Windows webview)
# ---------------------------------------------------------------------------
Write-Step "WebView2 runtime"
$webview2ClientId = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
$webview2Present = (Test-Path "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$webview2ClientId") -or
                   (Test-Path "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$webview2ClientId")
if ($webview2Present) {
    Write-Ok "WebView2 runtime present"
} else {
    Write-Host "    not detected -- installing via winget..."
    Invoke-WingetInstall @("install", "--id", "Microsoft.EdgeWebView2Runtime", "-e") | Out-Null
}

# ---------------------------------------------------------------------------
# 5. Python backend (chat2api itself)
# ---------------------------------------------------------------------------
Write-Step "Python backend (chat2api)"
if (Test-CommandExists "python") {
    Write-Ok "$(python --version 2>&1)"
} else {
    Write-Host "    not found -- installing via winget..."
    Invoke-WingetInstall @("install", "--id", "Python.Python.3.11", "-e") | Out-Null
    if (-not (Test-CommandExists "python")) {
        Write-Note "Python was installed but isn't on PATH in this session yet. Close this window, open a fresh PowerShell, and re-run this script."
        exit 1
    }
}

Push-Location $RepoRoot
try {
    python -c "import chat2api, fastapi, uvicorn, playwright" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "chat2api + dependencies importable"
    } else {
        Write-Host "    installing chat2api in editable mode + dev dependencies..."
        python -m pip install -e ".[dev]"
        Write-Host "    installing Playwright's Chromium browser..."
        python -m playwright install chromium
    }
} finally {
    Pop-Location
}

# ---------------------------------------------------------------------------
# 6. Frontend dependencies (desktop/node_modules)
# ---------------------------------------------------------------------------
Write-Step "Frontend dependencies"
Push-Location $DesktopDir
try {
    if (Test-Path (Join-Path $DesktopDir "node_modules")) {
        Write-Skip "node_modules already present"
    } else {
        npm install
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green

if ($NoRun) {
    Write-Host "Skipping launch (-NoRun passed). Run 'npm run tauri dev' from $DesktopDir when ready."
    exit 0
}

# ---------------------------------------------------------------------------
# 7. Backend port
# ---------------------------------------------------------------------------
function Test-PortExcluded([int]$TestPort) {
    $ranges = netsh interface ipv4 show excludedportrange protocol=tcp 2>$null
    foreach ($line in $ranges) {
        if ($line -match '^\s*(\d+)\s+(\d+)') {
            $start = [int]$Matches[1]
            $end = [int]$Matches[2]
            if ($TestPort -ge $start -and $TestPort -le $end) { return $true }
        }
    }
    return $false
}

Write-Step "Backend port"
if ($Port -eq 0 -and -not [Console]::IsInputRedirected) {
    Write-Host "    Windows reserves some TCP port ranges for its own use (Hyper-V/WSL), which silently break binding -- 8100 is affected on some machines."
    $entered = Read-Host "    Port for the chat2api backend (Enter to auto-pick a free port)"
    if ($entered -match '^\d+$') { $Port = [int]$entered }
}

if ($Port -ne 0) {
    if (($Port -lt 1) -or ($Port -gt 65535)) {
        Write-Note "Port $Port is out of range (1-65535) -- falling back to auto-pick."
        $Port = 0
    } elseif (Test-PortExcluded $Port) {
        Write-Note "Port $Port falls inside a Windows-excluded TCP port range (see 'netsh interface ipv4 show excludedportrange protocol=tcp') and would fail to bind -- falling back to auto-pick instead."
        $Port = 0
    }
}

if ($Port -ne 0) {
    Write-Ok "using fixed port $Port"
    $env:CHAT2API_PORT = "$Port"
} else {
    Write-Ok "auto-picking a free port at launch"
    Remove-Item Env:\CHAT2API_PORT -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------------
# 8. Launch
# ---------------------------------------------------------------------------
Write-Step "Launching chat2api desktop (npm run tauri dev)"
Write-Note "First run compiles the Rust side from scratch -- this can take several minutes."
Push-Location $DesktopDir
try {
    npm run tauri dev
} finally {
    Pop-Location
}
