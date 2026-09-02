#Requires -Version 5.1
# Đồng bộ skill nguồn `skills/trace-analyzer` ra các CLI skill dirs (.claude, .opencode, .codex)
# Nguồn chính duy nhất: skills/trace-analyzer/
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$src  = Join-Path $root "skills\trace-analyzer"
if (-not (Test-Path $src)) { Write-Error "Không tìm thấy nguồn $src"; exit 1 }
$targets = @(".claude\skills\trace-analyzer", ".opencode\skills\trace-analyzer", ".codex\skills\trace-analyzer")
foreach ($rel in $targets) {
  $dst = Join-Path $root $rel
  New-Item -ItemType Directory -Force -Path $dst | Out-Null
  New-Item -ItemType Directory -Force -Path (Join-Path $dst "references") | Out-Null
  Copy-Item -Path (Join-Path $src "SKILL.md") -Destination (Join-Path $dst "SKILL.md") -Force
  $refSrc = Join-Path $src "references\recipe-schema.md"
  if (Test-Path $refSrc) { Copy-Item -Path $refSrc -Destination (Join-Path $dst "references\recipe-schema.md") -Force }
  Write-Host "  synced $rel"
}
Write-Host "Done."
