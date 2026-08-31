#Requires -Version 5.1
<#
.SYNOPSIS
    Build chat2api desktop (.exe) va chay standalone, dung du lieu giong dev.

.DESCRIPTION
    1. Build frontend (SvelteKit/Vite -> desktop/build)
    2. Build Tauri desktop app (Windows .exe)
    3. Copy exe ra repo root: chat2api-desktop.exe
    4. (optional) Chay exe voi CHAT2API_WORKDIR = repo root, nen .env, data/,
       recipes/ giong het luc chay `npm run tauri dev`.

    Khi chay standalone, exe tu spawn `python -m chat2api serve` (sidecar trong
    desktop/src-tauri/src/lib.rs). Workdir sidecar mac dinh la repo root do
    CARGO_MANIFEST_DIR duoc bake vao luc compile; script nay gan CHAT2API_WORKDIR
    tuong minh de dam bao chay o bat ky thu muc nao cung dung cung data.

.PARAMETER Debug
    Build debug thay vi release (default).

.PARAMETER Clean
    Xoa cac build cu (target/release hoac target/debug) truoc khi build.

.PARAMETER NoRun
    Chi build, khong chay exe.

.PARAMETER Background
    Chay exe detached (khong cho, khong mo console).

.PARAMETER Port
    Pin cong backend (CHAT2API_PORT) cho exe spawn. Neu khong truyen, exe se
    tu doc `CHAT2API_PORT` trong `.env` (repo root); khong co thi tu chon cong
    trong.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\build-desktop.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\build-desktop.ps1 -Clean -Background -Port 9123

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\build-desktop.ps1 -NoRun
#>

param(
    [switch]$Debug,
    [switch]$Clean,
    [switch]$NoRun,
    [switch]$Background,
    [ValidateRange(1, 65535)]
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
$Root = Split-Path -Parent $ScriptDir
$DesktopDir = Join-Path $Root "desktop"
$BuildMode = if ($Debug) { "debug" } else { "release" }
$TargetDir = Join-Path $DesktopDir "src-tauri\target\$BuildMode"
$BuiltExe = Join-Path $TargetDir "desktop.exe"
$DesktopExe = Join-Path $Root "chat2api-desktop.exe"

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Write-Ok($msg) {
    Write-Host "    ok: $msg" -ForegroundColor Green
}

function Test-CommandExists([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# Windows PowerShell 5.1 turns a native command's REDIRECTED stderr into
# ErrorRecords, so with $ErrorActionPreference = "Stop" a single stderr line
# kills the whole script. Every native call using `2>` goes through here.
function Invoke-NativeQuiet([scriptblock]$Body) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Body } finally { $ErrorActionPreference = $prev }
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  chat2api - Build Desktop" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Mode: $BuildMode"
Write-Host "Repo root:  $Root"

# ── 0. Prerequisites ──────────────────────────────────────────────────────
if (-not (Test-CommandExists "npm")) {
    throw "npm was not found. Run desktop/scripts/setup-and-run.ps1 first."
}
if (-not (Test-CommandExists "python")) {
    throw "Python was not found. Run desktop/scripts/setup-and-run.ps1 first."
}

Push-Location $Root
try {
    Invoke-NativeQuiet { python -c "import chat2api, playwright" 2>$null } | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "chat2api or Playwright is not installed. Run desktop/scripts/setup-and-run.ps1 first."
    }
} finally {
    Pop-Location
}

if (-not (Test-Path (Join-Path $DesktopDir "node_modules"))) {
    throw "desktop/node_modules not found. Run desktop/scripts/setup-and-run.ps1 first."
}

try {
    # ── 1. Clean (optional) ─────────────────────────────────────────────────
    if ($Clean) {
        Write-Step "Clean"
        if (Test-Path $TargetDir) {
            Remove-Item $TargetDir -Recurse -Force
            Write-Ok "Removed $TargetDir"
        } else {
            Write-Host "    nothing to clean (target/$BuildMode absent)" -ForegroundColor DarkGray
        }
    }

    # ── 2. Build Frontend ───────────────────────────────────────────────────
    Write-Step "[1/2] Building frontend (Vite)..."
    Push-Location $DesktopDir
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
    } finally {
        Pop-Location
    }
    Write-Ok "Frontend built to desktop/build/"

    # ── 3. Build Tauri ──────────────────────────────────────────────────────
    Write-Step "[2/2] Building Tauri desktop app..."
    Push-Location $DesktopDir
    try {
        if ($Debug) {
            npm run tauri -- build --debug
        } else {
            npm run tauri build
        }
        if ($LASTEXITCODE -ne 0) { throw "Tauri build failed." }
    } finally {
        Pop-Location
    }
    Write-Ok "Tauri build complete."

    # ── 4. Copy exe ve repo root ────────────────────────────────────────────
    if (-not (Test-Path $BuiltExe)) {
        $BuiltExe = Get-ChildItem -Path $TargetDir -Filter "*.exe" -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $BuiltExe) { throw "Build completed but no executable was found in: $TargetDir" }

    Copy-Item -LiteralPath $BuiltExe -Destination $DesktopExe -Force
    $sizeMB = [math]::Round((Get-Item $DesktopExe).Length / 1MB, 1)
    Write-Ok "Executable: $DesktopExe ($sizeMB MB)"

    # Hien thi cac file bundle khac (installer, MSI...)
    $bundleDir = Join-Path $TargetDir "bundle"
    if (Test-Path $bundleDir) {
        Write-Host "  Bundle outputs:" -ForegroundColor Yellow
        Get-ChildItem -Path $bundleDir -Recurse -File -Include "*.msi", "*.exe" -ErrorAction SilentlyContinue |
            ForEach-Object {
                Write-Host "    $($_.FullName) ($([math]::Round($_.Length / 1MB, 1)) MB)" -ForegroundColor White
            }
    }

    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "  Build complete!" -ForegroundColor Green
    Write-Host "  Data dir:  $(Join-Path $Root 'data')"
    Write-Host "  Env file:  $(Join-Path $Root '.env')"
    Write-Host "  Recipes:   $(Join-Path $Root 'recipes')"
    Write-Host "========================================" -ForegroundColor Cyan

    # ── 5. Chay standalone (optional) ───────────────────────────────────────
    if ($NoRun) { exit 0 }

    Write-Step "Launching chat2api-desktop.exe (standalone, cung data nhu dev)"
    $previousWorkdir = $env:CHAT2API_WORKDIR
    $previousPort = $env:CHAT2API_PORT
    try {
        # Ghi de workdir sidecar de chac chan exe dung .env/data/recipes cua repo,
        # bat ke thu muc hien tai.
        $env:CHAT2API_WORKDIR = $Root
        if ($Port -ne 0) {
            # -Port thang tren moitruong; exe cung se doc CHAT2API_PORT tu .env
            # neu khong co bien moi truong.
            $env:CHAT2API_PORT = "$Port"
            Write-Host "  Port: $Port (truyen bang -Port)" -ForegroundColor DarkGray
        } else {
            $envLine = Select-String -LiteralPath (Join-Path $Root ".env") -Pattern "^CHAT2API_PORT\s*=" -ErrorAction SilentlyContinue
            if ($envLine) {
                $envPort = ($envLine.Line -split "=", 2)[1].Trim().Trim('"', "'")
                Write-Host "  Port: $envPort (doc tu .env)" -ForegroundColor DarkGray
            } else {
                Write-Host "  Port: tu dong chon cong trong (hoac dat CHAT2API_PORT trong .env)" -ForegroundColor DarkGray
            }
        }
        if ($Background) {
            $process = Start-Process -FilePath $DesktopExe -WindowStyle Hidden -PassThru
            Write-Host "  Running in the background (PID $($process.Id))." -ForegroundColor Green
        } else {
            & $DesktopExe
        }
    } finally {
        if ($null -eq $previousWorkdir) { Remove-Item Env:\CHAT2API_WORKDIR -ErrorAction SilentlyContinue }
        else { $env:CHAT2API_WORKDIR = $previousWorkdir }
        if ($null -eq $previousPort) { Remove-Item Env:\CHAT2API_PORT -ErrorAction SilentlyContinue }
        else { $env:CHAT2API_PORT = $previousPort }
    }
} catch {
    Write-Host "`nBUILD FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
