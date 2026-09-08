#Requires -Version 5.1
<#
.SYNOPSIS
    Chay API va Vite song song, giu cache de khoi dong dev nhanh.
.DESCRIPTION
    Mac dinh tai su dung cache SvelteKit/Vite; chi cai dependencies neu chua co.
    -Tauri chay frontend va Rust sidecar. -CleanCache chi xoa cache sinh ra,
    khong xoa desktop/build. -Force yeu cau Vite toi uu lai dependencies.
.PARAMETER ApiPort
    Cong API. 0 = doc .env CHAT2API_PORT, fallback 8100.
.PARAMETER WebPort
    Cong Vite. 0 = doc tauri.conf.json devUrl, fallback 1420.
.PARAMETER Tauri
    Chay Tauri thay vi API + Vite rieng.
.PARAMETER SkipPortClear
    Bo qua don port.
.PARAMETER CleanCache
    Xoa cache SvelteKit/Vite khi can khac phuc cache loi.
.PARAMETER Force
    Truyen --force toi Vite, ke ca khi chay Tauri.
.PARAMETER SkipCacheClear
    Tuong thich lenh cu; giu cache nay la mac dinh.
.PARAMETER NoForce
    Tuong thich lenh cu; khong force nay la mac dinh.
.PARAMETER ShowLogs
    Mo cua so log PowerShell. Mac dinh chay an.
.EXAMPLE
    .\scripts\run-dev.ps1
.EXAMPLE
    .\scripts\run-dev.ps1 -CleanCache -Force -ShowLogs
.EXAMPLE
    .\scripts\run-dev.ps1 -Tauri
#>

param(
    [ValidateRange(0, 65535)]
    [int]$ApiPort = 0,
    [ValidateRange(0, 65535)]
    [int]$WebPort = 0,
    [switch]$Tauri,
    [switch]$SkipPortClear,
    [switch]$SkipCacheClear,
    [switch]$NoForce,
    [switch]$CleanCache,
    [switch]$Force,
    [switch]$ShowLogs
)

$ErrorActionPreference = "Stop"
if ($CleanCache -and $SkipCacheClear) { throw "Khong dung -CleanCache cung -SkipCacheClear." }
if ($Force -and $NoForce) { throw "Khong dung -Force cung -NoForce." }

$ScriptDir = $PSScriptRoot
$Root = Split-Path -Parent $ScriptDir
$DesktopDir = Join-Path $Root "desktop"
$TauriConf = Join-Path $DesktopDir "src-tauri\tauri.conf.json"
$EnvFile = Join-Path $Root ".env"

# ── helpers ──────────────────────────────────────────────────────────────
function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    ok: $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    !! $msg" -ForegroundColor Yellow }
function Write-Info($msg) { Write-Host "    $msg" -ForegroundColor DarkGray }

function Test-CommandExists([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-NativeQuiet([scriptblock]$Body) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Body } finally { $ErrorActionPreference = $prev }
}

function Get-EnvPort([string]$EnvPath, [string]$Key, [int]$Fallback) {
    if (-not (Test-Path $EnvPath)) { return $Fallback }
    $line = Select-String -LiteralPath $EnvPath -Pattern "^$Key\s*=" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $line) { return $Fallback }
    $raw = ($line.Line -split "=", 2)[1].Trim().Trim('"', "'")
    if ($raw -match '^\d+$') {
        $v = [int]$raw
        if ($v -ge 1 -and $v -le 65535) { return $v }
    }
    return $Fallback
}

function Get-TauriDevPort([int]$Fallback) {
    if (-not (Test-Path $TauriConf)) { return $Fallback }
    try {
        $json = Get-Content -LiteralPath $TauriConf -Raw | ConvertFrom-Json
        $url = $json.build.devUrl
        if ($url -match ':(\d+)(/|$)') { return [int]$Matches[1] }
    } catch { }
    return $Fallback
}

function Clear-Port([int]$Port) {
    if ($Port -le 0) { return }
    # Get-NetTCPConnection co san tu Windows 8/Server 2012; fallback sang netstat neu thieu.
    $found = $false
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
        foreach ($c in $conns) {
            $targetPid = $c.OwningProcess
            if (-not $targetPid) { continue }
            try {
                $proc = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
                $name = if ($proc) { $proc.ProcessName } else { "PID $targetPid" }
                Write-Warn "Port $Port dang bi $name (PID $targetPid) giu -> kill"
                Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue
                $found = $true
            } catch { }
        }
    } catch {
        # fallback: netstat
        $lines = Invoke-NativeQuiet { netstat -ano 2>$null } | Where-Object { $_ -match "^\s*TCP.*:$Port\s" }
        foreach ($l in $lines) {
            if ($l -match '\s(\d+)\s*$') {
                $targetPid = [int]$Matches[1]
                try { Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue; $found = $true } catch { }
                Write-Warn "Port $Port (netstat) -> kill PID $targetPid"
            }
        }
    }
    # Cho OS nha port
    if ($found) { Start-Sleep -Milliseconds 800 }
    # Kiem tra lai
    try {
        $still = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
        if ($still) { Write-Warn "Port $Port van con process giu sau khi kill (co the can chay PowerShell voi Admin)." }
        else { Write-Ok "Port $Port da trong" }
    } catch {
        Write-Ok "Port $Port da trong (khong kiem tra duoc Get-NetTCPConnection)"
    }
}

function Clear-UiCache {
    # Cac thu muc Vite/SvelteKit sinh ra va co the giu cache cu
    $targets = @(
        (Join-Path $DesktopDir ".svelte-kit"),
        (Join-Path $DesktopDir ".vite"),
        (Join-Path $DesktopDir "node_modules\.vite"),
        (Join-Path $Root ".vite")
    )
    foreach ($p in $targets) {
        $p = [IO.Path]::GetFullPath($p)
        $rootPrefix = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
        if (-not $p.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Cache path nam ngoai repo: $p"
        }
        if (Test-Path -LiteralPath $p) {
            try {
                Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop
                Write-Ok "Da xoa cache: $p"
            } catch {
                Write-Warn "Khong xoa duoc $p : $($_.Exception.Message)"
            }
        }
    }
    # Xoa them cache Vite o %LOCALAPPDATA% neu co (it gap nhung van don)
    # Khong xoa node_modules hoan toan de tranh cai lai lau; chi xoa .vite ben trong.
}

# ── resolve ports ──────────────────────────────────────────────────────
if ($ApiPort -eq 0) {
    $ApiPort = Get-EnvPort $EnvFile "CHAT2API_PORT" 8100
    Write-Info "ApiPort tu .env / default -> $ApiPort"
} else {
    Write-Info "ApiPort truyen vao -> $ApiPort"
}

if ($WebPort -eq 0) {
    # tauri.conf.json devUrl la nguon chinh; fallback 1420 (vite.config.js) roi 5199 (tauri cu)
    $fromTauri = Get-TauriDevPort 0
    if ($fromTauri -ne 0) {
        $WebPort = $fromTauri
        Write-Info "WebPort tu tauri.conf.json devUrl -> $WebPort"
    } else {
        $WebPort = 1420
        Write-Info "WebPort mac dinh (vite.config.js) -> $WebPort"
    }
} else {
    Write-Info "WebPort truyen vao -> $WebPort"
}

# HMR port mac dinh cua vite khi chay tauri la 1421; cung don de tranh treo
$HmrPort = 1421
# Chi kiem tra cong ma lan chay nay su dung; HMR rieng chi bat khi co dev host.
$portsToClear = @($ApiPort, $WebPort)
if ($env:TAURI_DEV_HOST) { $portsToClear += $HmrPort }
$portsToClear = $portsToClear | Sort-Object -Unique

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  chat2api - run dev (API + UI)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Repo:      $Root"
Write-Host "Desktop:   $DesktopDir"
Write-Host "API port:  $ApiPort"
Write-Host "Web port:  $WebPort (HMR $HmrPort)"
Write-Host "Mode:      $(if ($Tauri) { 'Tauri (npm run tauri dev)' } else { 'Split (API + Vite)' })"

# ── prereqs ────────────────────────────────────────────────────────────
if (-not (Test-Path $DesktopDir)) { throw "Khong tim thay thu muc desktop: $DesktopDir" }

if (-not (Test-CommandExists "npm"))  { throw "npm khong co tren PATH. Cai Node.js truoc." }
if (-not (Test-CommandExists "python")) { throw "python khong co tren PATH. Cai Python 3.11+ truoc." }

# Nhac nho neu thieu node_modules
if (-not (Test-Path (Join-Path $DesktopDir "node_modules"))) {
    Write-Warn "desktop/node_modules chua co -> se chay npm install truoc khi dev (co the mat 1-2 phut)."
}

# Kiem tra python co import duoc chat2api khong (khong kill script, chi canh bao)
Push-Location $Root
try {
    Invoke-NativeQuiet { python -c "import chat2api" 2>$null } | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "python khong import duoc chat2api. Chay: python -m pip install -e .  (hoac .[dev])"
    }
} finally { Pop-Location }

# ── 1. Clear port ──────────────────────────────────────────────────────
if (-not $SkipPortClear) {
    Write-Step "Don port cu ($($portsToClear -join ', '))"
    foreach ($p in $portsToClear) { Clear-Port $p }
} else {
    Write-Step "Bo qua don port (-SkipPortClear)"
}

# ── 2. Clear UI cache ──────────────────────────────────────────────────
if ($CleanCache) {
    Write-Step "Xoa cache giao dien theo yeu cau (-CleanCache)"
    Clear-UiCache
} else {
    Write-Step "Giu cache SvelteKit/Vite de khoi dong nhanh"
}

# ── 3. Chuan bi env dev ────────────────────────────────────────────────
# Bien TAURI_DEV_PORT buoc vite.config.js dung dung port voi tauri.conf.json devUrl.
$env:TAURI_DEV_PORT = "$WebPort"
$env:CHAT2API_PORT = "$ApiPort"
# Dat CHAT2API_WORKDIR = repo root de API doc dung .env/data/recipes du khi chay tu scripts/
$env:CHAT2API_WORKDIR = $Root

Write-Step "Env dev"
Write-Ok "TAURI_DEV_PORT=$WebPort"
Write-Ok "CHAT2API_PORT=$ApiPort"
Write-Ok "CHAT2API_WORKDIR=$Root"
Write-Info "Force toi uu lai dependencies: $([bool]$Force)"

# ── 4. Cai node_modules neu thieu (khong blocking neu da co) ───────────
if (-not (Test-Path (Join-Path $DesktopDir "node_modules\.package-lock.json")) -and (Test-Path (Join-Path $DesktopDir "node_modules"))) {
    # node_modules co nhung thieu stamp -> van ok
} elseif (-not (Test-Path (Join-Path $DesktopDir "node_modules"))) {
    Write-Step "Cai frontend dependencies (npm install)"
    Push-Location $DesktopDir
    try {
        npm install
        if ($LASTEXITCODE -ne 0) { throw "npm install that bai." }
        Write-Ok "npm install xong"
    } finally { Pop-Location }
}

# ── 5. Chay dev ────────────────────────────────────────────────────────
if (-not (Test-Path (Join-Path $DesktopDir ".svelte-kit\tsconfig.json"))) {
    Write-Step "Dong bo SvelteKit lan dau / sau khi xoa cache"
    Push-Location $DesktopDir
    try {
        & (Join-Path $DesktopDir "node_modules\.bin\svelte-kit.cmd") sync
        if ($LASTEXITCODE -ne 0) { throw "svelte-kit sync that bai." }
    } finally { Pop-Location }
}

if ($Tauri) {
    Write-Step "Chay Tauri dev (giao dien + sidecar API)"
    Write-Info "Lenh: npm run tauri dev  (truoc do chay npm run dev tren port $WebPort, API sidecar tren $ApiPort)"
    Write-Info "Nhan Ctrl+C de dung. Dong cua so Tauri se tu kill sidecar (lib.rs: stop_server)."
    Push-Location $DesktopDir
    try {
        $devCommand = if ($Force) { "npm run dev -- --force" } else { "npm run dev" }
        $override = @{ build = @{ beforeDevCommand = $devCommand; devUrl = "http://localhost:$WebPort" } } | ConvertTo-Json -Depth 3
        $overridePath = Join-Path ([IO.Path]::GetTempPath()) ("chat2api-tauri-dev-" + [guid]::NewGuid() + ".json")
        [IO.File]::WriteAllText($overridePath, $override)
        try { npm run tauri -- dev --config $overridePath }
        finally { Remove-Item -LiteralPath $overridePath -Force }
    } finally { Pop-Location }
    exit $LASTEXITCODE
}

# Split mode: API + Vite chay song song, moi cai mot cua so PowerShell rieng
Write-Step "Chay split dev: API + Vite song song (-ShowLogs de hien log)"

# Xay dung lenh cho tung cua so
$ApiCmd = "Set-Location -LiteralPath `"$Root`"; `$env:CHAT2API_PORT=`"$ApiPort`"; `$env:CHAT2API_WORKDIR=`"$Root`"; Write-Host '==> API: python -m chat2api serve --host 127.0.0.1 --port $ApiPort' -ForegroundColor Cyan; python -m chat2api serve --host 127.0.0.1 --port $ApiPort"
$ViteArgs = "--host 127.0.0.1 --port $WebPort"
if ($Force) { $ViteArgs = "--force $ViteArgs" }
$WebCmd = "Set-Location -LiteralPath `"$DesktopDir`"; `$env:TAURI_DEV_PORT=`"$WebPort`"; Write-Host '==> WEB: npm run dev -- $ViteArgs' -ForegroundColor Cyan; npm run dev -- $ViteArgs"

# Ghi ra file tam de Start-Process goi pwsh -File (tranh quote phuc tap)
$tmpApi = Join-Path $env:TEMP "chat2api-run-dev-api.ps1"
$tmpWeb = Join-Path $env:TEMP "chat2api-run-dev-web.ps1"
Set-Content -LiteralPath $tmpApi -Value $ApiCmd -Encoding UTF8
Set-Content -LiteralPath $tmpWeb -Value $WebCmd -Encoding UTF8

# Chon shell: pwsh neu co, khong thi powershell
$pwsh = if (Test-CommandExists "pwsh") { "pwsh" } else { "powershell" }

Write-Info "API + WEB chay doc lap. Dung -ShowLogs de hien cua so log."
Write-Info "API log: cua so 'chat2api API ($ApiPort)'  |  WEB log: cua so 'chat2api WEB ($WebPort)'"
    Write-Info "Chay lai script se don cong API/WEB cu; voi -ShowLogs co the dong cua so log de dung."

try {
    $windowStyle = if ($ShowLogs) { 'Normal' } else { 'Hidden' }
    $apiProc = Start-Process -FilePath $pwsh -WindowStyle $windowStyle -ArgumentList "-NoExit", "-File", "`"$tmpApi`"" -PassThru
    # Tieu de cua so (chi co tac dung khi dung conhost/Windows Terminal)
    try { $apiProc | Out-Null } catch { }

    $webProc = Start-Process -FilePath $pwsh -WindowStyle $windowStyle -ArgumentList "-NoExit", "-File", "`"$tmpWeb`"" -PassThru

    Write-Ok "Da mo API (PID $($apiProc.Id)) va WEB (PID $($webProc.Id))"
    Write-Host ""
    Write-Host "  API : http://127.0.0.1:$ApiPort  (health: http://127.0.0.1:$ApiPort/health)" -ForegroundColor White
    Write-Host "  WEB : http://127.0.0.1:$WebPort" -ForegroundColor White
    if ($ApiPort -ne 8100) {
        Write-Warn "CHAT2API_PORT=$ApiPort khac mac dinh 8100 -> nho sua tauri devUrl hoac ?api=http://127.0.0.1:$ApiPort khi mo web ngoai Tauri"
    }
    Write-Host ""
    Write-Host "Dev nhanh: giu cache mac dinh. Chi dung -CleanCache / -Force khi can sua cache loi." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Nhan Enter de mo ca hai URL trong trinh duyet mac dinh (hoac Ctrl+C de thoat script nay)..." -ForegroundColor DarkGray

    # Khong block vinh vien de script co the ket thuc ma van giu 2 cua so con song
    # Cho nguoi dung nhan Enter thi mo browser
    if (-not [Console]::IsInputRedirected) {
        $key = Read-Host "  Mo browser ngay? (Y/n)"
        if ($key -eq "" -or $key -match '^[Yy]') {
            try { Start-Process "http://127.0.0.1:$WebPort" | Out-Null } catch { }
            # API khong co UI, chi mo health de kiem tra
            Write-Info "Da mo http://127.0.0.1:$WebPort"
        }
    }

    Write-Ok "Xong. 2 cua so dev van dang chay doc lap."
    Write-Info "Tam file: $tmpApi , $tmpWeb (tu xoa khi reboot)"
} catch {
    Write-Host "`nRUN-DEV FAILED: $($_.Exception.Message)" -ForegroundColor Red
    # Don dep neu that bai nua chung
    try { if ($apiProc -and -not $apiProc.HasExited) { Stop-Process -Id $apiProc.Id -Force -ErrorAction SilentlyContinue } } catch { }
    try { if ($webProc -and -not $webProc.HasExited) { Stop-Process -Id $webProc.Id -Force -ErrorAction SilentlyContinue } } catch { }
    exit 1
}
