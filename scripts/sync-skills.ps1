#Requires -Version 5.1
# Đồng bộ mọi skill nguồn trong skills\<name>\ ra các CLI skill dirs
# (.claude, .opencode, .codex). Nguồn chính duy nhất: skills\.
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$skills = Join-Path $root "skills"
if (-not (Test-Path $skills)) { Write-Error "Không tìm thấy $skills"; exit 1 }
foreach ($src in Get-ChildItem -Directory $skills) {
  if (-not (Test-Path (Join-Path $src.FullName "SKILL.md"))) { continue }
  foreach ($base in @(".claude\skills", ".opencode\skills", ".codex\skills")) {
    $dst = Join-Path $root (Join-Path $base $src.Name)
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    Copy-Item -Path (Join-Path $src.FullName "*") -Destination $dst -Recurse -Force
    Write-Host "  synced $base\$($src.Name)"
  }
}
Write-Host "Done."
