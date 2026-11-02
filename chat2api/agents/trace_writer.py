"""Persist trace giàu ra data/traces/<domain>/<YYYY-MM-DD_HH-MM-SS>-<slug>.{json,md} — atomic write, giữ vĩnh viễn."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..config import Config  # lazy import tránh cycle khi import sớm


def _traces_dir(cfg: Config | None = None) -> Path:
    if cfg is not None and hasattr(cfg, "traces_dir"):
        return Path(cfg.traces_dir)  # type: ignore[attr-defined]
    # fallback CHAT2API_DATA_DIR hoặc ./data (khớp Config)
    base = os.environ.get("CHAT2API_DATA_DIR", "./data")
    return Path(base) / "traces"


def _slugify(s: str | None) -> str:
    s = (s or "record").strip().lower()
    s = re.sub(r"[^a-z0-9-]+", "-", s).strip("-") or "record"
    return s[:60]


def _domain_dir(url: str | None, fallback: str) -> str:
    """Tên thư mục con theo domain (vd ``chat.z.ai``); fallback slug nếu URL rỗng/không hợp lệ."""
    host = ""
    try:
        raw = (url or "").strip()
        if raw and "://" not in raw:
            raw = "https://" + raw
        host = (urlparse(raw).hostname or "").lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    host = re.sub(r"[^a-z0-9.-]+", "-", host).strip(".-")
    return host[:100] or fallback


def _unique_stem(directory: Path, stem: str) -> str:
    """Tránh ghi đè khi 2 trace trùng giây: thêm hậu tố -2, -3…"""
    candidate, n = stem, 1
    while (directory / f"{candidate}.json").exists() or (directory / f"{candidate}.md").exists():
        n += 1
        candidate = f"{stem}-{n}"
    return candidate


def find_trace(traces_dir: Path, job_id: str, fmt: str) -> Path | None:
    """Tìm file trace theo jobId (đọc metadata.jobId trong .json); hỗ trợ cả tên cũ ``<jobId>-<slug>``."""
    if not traces_dir.exists():
        return None
    for f in traces_dir.glob(f"{job_id}-*.{fmt}"):  # layout cũ
        return f
    for jf in sorted(traces_dir.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            meta = json.loads(jf.read_text(encoding="utf-8")).get("metadata") or {}
        except Exception:
            continue
        if meta.get("jobId") == job_id:
            target = jf if fmt == "json" else jf.with_suffix(".md")
            return target if target.exists() else None
    return None


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
    traces_dir = _traces_dir(cfg) / _domain_dir(metadata.get("url"), slug)
    traces_dir.mkdir(parents=True, exist_ok=True)
    stem = _unique_stem(traces_dir, f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}-{slug}")

    # .json: {metadata:{jobId,slug,url,profile,startedAt,finishedAt,flows}, events:[]}
    json_obj = {"metadata": metadata, "events": trace}
    # kèm snapshot cuối nếu có (không bắt buộc nhưng hữu ích cho skill)
    if snapshot:
        json_obj["snapshot"] = snapshot[:8000]  # type: ignore[assignment]
    json_path = traces_dir / f"{stem}.json"
    _atomic_write_json(json_path, json_obj)

    # .md — dùng formatter chuẩn của recorder (đúng spec Phase1/2)
    try:
        from .recorder import format_trace_as_markdown

        md = format_trace_as_markdown(trace, metadata=metadata, snapshot=snapshot)
    except Exception:
        # fallback tối thiểu nếu import fail
        md = f"# Trace {job_id} — {slug}\n\n```json\n{json.dumps(metadata, ensure_ascii=False, indent=2)}\n```\n\nEvents: {len(trace)}\n"
    md_path = traces_dir / f"{stem}.md"
    _atomic_write_text(md_path, md)

    return {"json": str(json_path), "md": str(md_path)}
