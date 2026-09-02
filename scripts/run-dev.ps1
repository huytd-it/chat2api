#Requires -Version 5.1
<#
.SYNOPSIS
    Chay dev ca API (python -m chat2api serve) va giao dien (desktop/vite) song song:
    don port cu, xoa cache giao dien, tranh cache trinh duyet/Vite.

.DESCRIPTION
    Quy trinh moi lan chay:
      1. Doc cong API tu .env (CHAT2API_PORT) va cong web tu desktop/src-tauri/tauri.conf.json (devUrl) / vite.config.js.
      2. Clear port: tim PID dang giu TCP port va kill (Get-NetTCPConnection -> Stop-Process).
      3. Clear giao dien cu: xoa desktop/.svelte-kit, desktop/build, desktop/.vite, desktop/node_modules/.vite, .vite.
      4. Tranh cache: chay Vite voi --force, header Cache-Control: no-store,
         dong thoi xoa Vite cache truoc khi chay; huong dan mo DevTools Disable cache.
      5. Chay song song:
           - Mac dinh (split):  API = python -m chat2api serve --host 127.0.0.1 --port <ApiPort>
                                Web = npm run dev -- --force --host 127.0.0.1 --port <WebPort>
             Moi tien trinh mo cua so PowerShell rieng de log khong tron lan.
           - -Tauri:  npm run tauri dev  (sidecar Rust tu spawn API, dung chung CHAT2API_PORT).

    Script an toan chay lai nhieu lan; moi buoc deu kiem tra ton tai truoc khi xoa/kill.

.PARAMETER ApiPort
    Cong API. 0 = doc tu .env CHAT2API_PORT, neu khong co thi 8100.

.PARAMETER WebPort
    Cong Vite dev. 0 = doc tu tauri.conf.json devUrl, neu khong co thi 1420.

.PARAMETER Tauri
    Chay che do Tauri (npm run tauri dev) thay vi split API+vite.

.PARAMETER SkipPortClear
    Bo qua buoc don port.

.PARAMETER SkipCacheClear
    Bo qua buoc xoa cache giao dien.

.PARAMETER NoForce
    Khong truyen --force cho vite (giu cache Vite neu muon debug nhanh).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\run-dev.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\run-dev.ps1 -ApiPort 8100 -WebPort 1420

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\run-dev.ps1 -Tauri

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\run-dev.ps1 -SkipCacheClear
#>

param(
    [ValidateRange(0, 65535)]
    [int]$ApiPort = 0,
    [ValidateRange(0, 65535)]
    [int]$WebPort = 0,
    [switch]$Tauri,
    [switch]$SkipPortClear,
    [switch]$SkipCacheClear,
    [switch]$NoForce
)

$ErrorActionPreference = "Stop"

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
        (Join-Path $DesktopDir "build"),
        (Join-Path $DesktopDir ".vite"),
        (Join-Path $DesktopDir "node_modules\.vite"),
        (Join-Path $Root ".vite"),
        (Join-Path $DesktopDir ".svelte-kit output"), # phong thu
        (Join-Path $Root "desktop\.svelte-kit")
    )
    foreach ($p in $targets) {
        if (Test-Path $p) {
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
# Tap port can don: Api, Web, HMR, cac port pho bien khac de tranh nham
$portsToClear = @($ApiPort, $WebPort, $HmrPort, 5199, 5173) | Sort-Object -Unique

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
if (-not $SkipCacheClear) {
    Write-Step "Xoa cache giao dien cu (.svelte-kit, build, .vite)"
    Clear-UiCache
    # Tái sinh .svelte-kit/tsconfig.json ngay để tránh warning
    # "Cannot find base config file ./.svelte-kit/tsconfig.json" ở lần vite đầu
    Write-Info "Dong bo SvelteKit (svelte-kit sync)..."
    Push-Location $DesktopDir
    try { Invoke-NativeQuiet { npx svelte-kit sync 2>$null } | Out-Null } catch { }
    finally { Pop-Location }
    if (Test-Path (Join-Path $DesktopDir ".svelte-kit\tsconfig.json")) { Write-Ok "Da tai sinh .svelte-kit/tsconfig.json" }
} else {
    Write-Step "Bo qua xoa cache (-SkipCacheClear)"
}

# ── 3. Chuan bi env tranh cache ────────────────────────────────────────
# Vite --force da bo qua cache doc; them header no-store de trinh duyet khong luu.
# Bien TAURI_DEV_PORT buoc vite.config.js dung dung port voi tauri.conf.json devUrl.
$env:TAURI_DEV_PORT = "$WebPort"
$env:CHAT2API_PORT = "$ApiPort"
# Dat CHAT2API_WORKDIR = repo root de API doc dung .env/data/recipes du khi chay tu scripts/
$env:CHAT2API_WORKDIR = $Root
# Bao vite khong dung cache dia (vite >=5 ton trong)
$env:VITE_FORCE = "true"

Write-Step "Env chong cache"
Write-Ok "TAURI_DEV_PORT=$WebPort"
Write-Ok "CHAT2API_PORT=$ApiPort"
Write-Ok "CHAT2API_WORKDIR=$Root"
Write-Info "Vite se chay voi --force va header Cache-Control: no-store"
Write-Info "Trinh duyet: mo DevTools -> Network -> tick 'Disable cache (while DevTools is open)' de tranh cache manh."

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
if ($Tauri) {
    Write-Step "Chay Tauri dev (giao dien + sidecar API)"
    Write-Info "Lenh: npm run tauri dev  (truoc do chay npm run dev tren port $WebPort, API sidecar tren $ApiPort)"
    Write-Info "Nhan Ctrl+C de dung. Dong cua so Tauri se tu kill sidecar (lib.rs: stop_server)."
    Push-Location $DesktopDir
    try {
        # --force truyen xuong vite qua beforeDevCommand; ta truyen them qua env
        if ($NoForce) { npm run tauri dev }
        else { npm run tauri dev -- -- --force 2>$null; if ($LASTEXITCODE -ne 0) { npm run tauri dev } }
        # Fallback tren neu truong hop tren khong truyen duoc flag:
        # Tauri se chay `npm run dev` nhu dinh nghia trong tauri.conf.json beforeDevCommand
    } finally { Pop-Location }
    exit $LASTEXITCODE
}

# Split mode: API + Vite chay song song, moi cai mot cua so PowerShell rieng
Write-Step "Chay split dev: API + Vite song song (2 cua so rieng)"

# Xay dung lenh cho tung cua so
$ApiCmd = "Set-Location -LiteralPath `"$Root`"; `$env:CHAT2API_PORT=`"$ApiPort`"; `$env:CHAT2API_WORKDIR=`"$Root`"; Write-Host '==> API: python -m chat2api serve --host 127.0.0.1 --port $ApiPort' -ForegroundColor Cyan; python -m chat2api serve --host 127.0.0.1 --port $ApiPort"
$ViteArgs = if ($NoForce) { "--host 127.0.0.1 --port $WebPort" } else { "--force --host 127.0.0.1 --port $WebPort" }
$WebCmd = "Set-Location -LiteralPath `"$DesktopDir`"; `$env:TAURI_DEV_PORT=`"$WebPort`"; `$env:VITE_FORCE=`"true`"; Write-Host '==> WEB: npm run dev -- $ViteArgs (no-cache)' -ForegroundColor Cyan; npm run dev -- $ViteArgs"

# Ghi ra file tam de Start-Process goi pwsh -File (tranh quote phuc tap)
$tmpApi = Join-Path $env:TEMP "chat2api-run-dev-api.ps1"
$tmpWeb = Join-Path $env:TEMP "chat2api-run-dev-web.ps1"
Set-Content -LiteralPath $tmpApi -Value $ApiCmd -Encoding UTF8
Set-Content -LiteralPath $tmpWeb -Value $WebCmd -Encoding UTF8

# Chon shell: pwsh neu co, khong thi powershell
$pwsh = if (Test-CommandExists "pwsh") { "pwsh" } else { "powershell" }

Write-Info "Mo 2 cua so PowerShell rieng (API + WEB). Dong script nay KHONG tat 2 cua so do."
Write-Info "API log: cua so 'chat2api API ($ApiPort)'  |  WEB log: cua so 'chat2api WEB ($WebPort)'"
Write-Info "De dung ca hai, dong 2 cua so do hoac chay: Get-Process python,node | Stop-Process"

try {
    $apiProc = Start-Process -FilePath $pwsh -ArgumentList "-NoExit", "-File", "`"$tmpApi`"" -PassThru
    # Tieu de cua so (chi co tac dung khi dung conhost/Windows Terminal)
    try { $apiProc | Out-Null } catch { }
    Start-Sleep -Milliseconds 600

    $webProc = Start-Process -FilePath $pwsh -ArgumentList "-NoExit", "-File", "`"$tmpWeb`"" -PassThru
    Start-Sleep -Milliseconds 600

    Write-Ok "Da mo API (PID $($apiProc.Id)) va WEB (PID $($webProc.Id))"
    Write-Host ""
    Write-Host "  API : http://127.0.0.1:$ApiPort  (health: http://127.0.0.1:$ApiPort/health)" -ForegroundColor White
    Write-Host "  WEB : http://127.0.0.1:$WebPort" -ForegroundColor White
    if ($ApiPort -ne 8100) {
        Write-Warn "CHAT2API_PORT=$ApiPort khac mac dinh 8100 -> nho sua tauri devUrl hoac ?api=http://127.0.0.1:$ApiPort khi mo web ngoai Tauri"
    }
    Write-Host ""
    Write-Host "Meo tranh cache:" -ForegroundColor Yellow
    Write-Host "  - Vite da chay --force + da xoa .svelte-kit/build/.vite" -ForegroundColor Yellow
    Write-Host "  - Trinh duyet: F12 -> Network -> tick Disable cache" -ForegroundColor Yellow
    Write-Host "  - Neu van thay giao dien cu: Ctrl+F5 hoac xoa localStorage key c2a_api_base" -ForegroundColor Yellow
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
