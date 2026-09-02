#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/skills/trace-analyzer"
if [ ! -d "$SRC" ]; then echo "Không tìm thấy nguồn $SRC" >&2; exit 1; fi
for rel in ".claude/skills/trace-analyzer" ".opencode/skills/trace-analyzer" ".codex/skills/trace-analyzer"; do
  DST="$ROOT/$rel"
  mkdir -p "$DST/references"
  cp -f "$SRC/SKILL.md" "$DST/SKILL.md"
  [ -f "$SRC/references/recipe-schema.md" ] && cp -f "$SRC/references/recipe-schema.md" "$DST/references/recipe-schema.md"
  echo "  synced $rel"
done
echo "Done."
