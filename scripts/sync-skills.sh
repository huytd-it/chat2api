#!/usr/bin/env bash
# Đồng bộ mọi skill nguồn trong skills/<name>/ ra các CLI skill dirs
# (.claude, .opencode, .codex). Nguồn chính duy nhất: skills/.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -d "$ROOT/skills" ] || { echo "Không tìm thấy $ROOT/skills" >&2; exit 1; }
for SRC in "$ROOT"/skills/*/; do
  name="$(basename "$SRC")"
  [ -f "$SRC/SKILL.md" ] || continue
  for base in .claude/skills .opencode/skills .codex/skills; do
    DST="$ROOT/$base/$name"
    mkdir -p "$DST"
    cp -rf "$SRC". "$DST/"
    echo "  synced $base/$name"
  done
done
echo "Done."
