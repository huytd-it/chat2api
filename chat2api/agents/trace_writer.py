"""Persist trace giàu ra data/traces/<jobId>-<slug>.{json,md} — atomic write, giữ vĩnh viễn."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ..config import Config  # lazy import tránh cycle khi import sớm


def _traces_dir(cfg: Config | None = None) -> Path:
    if cfg is not None and hasattr(cfg, "traces_dir"):
        return Path(cfg.traces_dir)  # type: ignore[attr-defined]
    # fallback CHAT2API_DATA_DIR hoặc ./data (khớp Config)
    base = os.environ.get("CHAT2API_DATA_DIR", "./data")
    return Path(base) / "traces"


def _slugify(s: str | None) -> str:
    import re

    s = (s or "record").strip().lower()
    s = re.sub(r"[^a-z0-9-]+", "-", s).strip("-") or "record"
    return s[:60]


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".tmp.")
    try:
        os.write(fd, text.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(tmp, path)
    finally:
        if fd != -1:
            try:
                os.close(fd)
            except Exception:
                pass
        try:
            os.unlink(tmp)
        except Exception:
            pass


def _atomic_write_json(path: Path, obj: Any) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    _atomic_write_text(path, text)


def write_trace(
    job_id: str,
    slug: str | None,
    trace: list[dict[str, Any]],
    metadata: dict[str, Any],
    snapshot: str | None = None,
    cfg: Config | None = None,
) -> dict[str, str]:
    """Ghi cả .json và .md (atomic). Trả về dict path string.

    Import ``format_trace_as_markdown`` từ recorder để .md đúng spec P1 (đã có PII banner / flow / outerHTML / snapshotDiff).
    """
    slug = _slugify(slug)
    traces_dir = _traces_dir(cfg)
    traces_dir.mkdir(parents=True, exist_ok=True)

    # .json: {metadata:{jobId,slug,url,profile,startedAt,finishedAt,flows}, events:[]}
    json_obj = {"metadata": metadata, "events": trace}
    # kèm snapshot cuối nếu có (không bắt buộc nhưng hữu ích cho skill)
    if snapshot:
        json_obj["snapshot"] = snapshot[:8000]  # type: ignore[assignment]
    json_path = traces_dir / f"{job_id}-{slug}.json"
    _atomic_write_json(json_path, json_obj)

    # .md — dùng formatter chuẩn của recorder (đúng spec Phase1/2)
    try:
        from .recorder import format_trace_as_markdown

        md = format_trace_as_markdown(trace, metadata=metadata, snapshot=snapshot)
    except Exception:
        # fallback tối thiểu nếu import fail
        md = f"# Trace {job_id} — {slug}\n\n```json\n{json.dumps(metadata, ensure_ascii=False, indent=2)}\n```\n\nEvents: {len(trace)}\n"
    md_path = traces_dir / f"{job_id}-{slug}.md"
    _atomic_write_text(md_path, md)

    return {"json": str(json_path), "md": str(md_path)}
