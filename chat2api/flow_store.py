"""Lưu trữ Flows kiểu n8n: mỗi flow con là một file ``data/flows/<slug>/flow.json``.

Quy ước (đã chốt với người dùng):

- 1 file = 1 flow con = 1 model. Tên flow đặt như tên model.
- Template v1 được auto-convert từ ``recipe.yaml`` (xem ``flow_converter.py``),
  sau đó cắt đứt — không ghi ngược về recipe.
- Executor mới (``flow_executor.py``) chạy DAG theo ``nodes``/``edges``.
- ``FlowProvider`` expose mỗi flow như một provider ``flow/<slug>`` để không
  gãy luồng chat hiện tại.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

FLOW_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
FLOW_TYPES = ("text", "image", "video")
FLOW_CAPABILITIES = ("chat", "image", "video")

# Catalog node v1 — browser + media + account + logic đều là node riêng.
NODE_TYPES = frozenset({
    "start",
    "goto-url",
    "wait-ready",
    "new-chat",
    "assign-account",
    "check-trial-limit",
    "action-sequence",
    "select-model",
    "fill-input",
    "submit-enter",
    "submit-click",
    "wait-done-signal",
    "wait-media",
    "extract-text",
    "extract-media",
    "copy-button",
    "condition",
    "delay",
    "eval-js",
    "set-variable",
    "output",
})

_DONE_TYPES = {"stable_text", "selector_appear", "selector_disappear", "copy_button"}
_COPY_SCOPES = {"after", "inside", "page"}


def flows_dir_of(cfg=None) -> Path:
    """Thư mục flows theo ``Config.flows_dir``, fallback ``CHAT2API_DATA_DIR``."""
    if cfg is not None and getattr(cfg, "flows_dir", None) is not None:
        return Path(cfg.flows_dir)  # type: ignore[arg-type]
    base = os.environ.get("CHAT2API_DATA_DIR", "./data")
    return Path(base) / "flows"


def flow_path(flows_dir: Path, slug: str) -> Path:
    return Path(flows_dir) / slug / "flow.json"


def slug_ok(slug: Any) -> bool:
    return isinstance(slug, str) and bool(FLOW_SLUG_RE.match(slug))


def validate_flow(data: Any) -> list[str]:
    """Kiểm tra một dict flow. Trả về danh sách lỗi, rỗng là hợp lệ."""
    errs: list[str] = []
    if not isinstance(data, dict):
        return ["flow phải là một mapping"]
    slug = data.get("slug")
    if not slug_ok(slug):
        errs.append("invalid field: slug (chỉ [a-z0-9-])")
    flow_type = data.get("flow_type") or data.get("type")
    if flow_type not in FLOW_TYPES:
        errs.append(f"invalid field: flow_type ({' | '.join(FLOW_TYPES)})")
    capability = data.get("capability")
    if capability is not None and capability not in FLOW_CAPABILITIES:
        errs.append(f"invalid field: capability ({' | '.join(FLOW_CAPABILITIES)})")
    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        errs.append("invalid field: enabled (phải là boolean)")

    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errs.append("invalid field: nodes (phải là list không rỗng)")
        nodes = []
    edges = data.get("edges")
    if edges is None:
        edges = []
    if not isinstance(edges, list):
        errs.append("invalid field: edges (phải là list)")
        edges = []

    ids: list[str] = []
    by_id: dict[str, dict] = {}
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            errs.append(f"invalid field: nodes[{i}] (phải là mapping)")
            continue
        nid = node.get("id")
        if not isinstance(nid, str) or not nid.strip():
            errs.append(f"invalid field: nodes[{i}].id (phải là string không rỗng)")
            continue
        if nid in by_id:
            errs.append(f"invalid field: nodes[{i}].id '{nid}' (trùng id)")
            continue
        ids.append(nid)
        by_id[nid] = node
        ntype = node.get("type")
        if ntype not in NODE_TYPES:
            errs.append(f"invalid field: nodes[{i}].type '{ntype}' "
                        f"(phải thuộc {sorted(NODE_TYPES)})")
            continue
        params = node.get("params")
        if params is None:
            continue
        if not isinstance(params, dict):
            errs.append(f"invalid field: nodes[{i}].params (phải là mapping)")
            continue
        errs += _node_param_errors(ntype, i, params)

    starts = [nid for nid, n in by_id.items() if n.get("type") == "start"]
    if len(starts) != 1:
        errs.append("invalid field: nodes (phải có đúng 1 node `start`)")
    outputs = [nid for nid, n in by_id.items() if n.get("type") == "output"]
    if not outputs:
        errs.append("invalid field: nodes (phải có ít nhất 1 node `output`)")

    for i, edge in enumerate(edges):
        if not isinstance(edge, dict):
            errs.append(f"invalid field: edges[{i}] (phải là mapping)")
            continue
        src = edge.get("source")
        dst = edge.get("target")
        if src not in by_id:
            errs.append(f"invalid field: edges[{i}].source '{src}' (không có node này)")
        if dst not in by_id:
            errs.append(f"invalid field: edges[{i}].target '{dst}' (không có node này)")
    return errs


def _node_param_errors(ntype: str, i: int, params: dict) -> list[str]:
    errs: list[str] = []

    def need(name: str, ok: bool):
        if not ok:
            errs.append(f"missing/invalid field: nodes[{i}].params.{name}")

    if ntype == "goto-url":
        need("url", bool(str(params.get("url") or "").strip()))
    elif ntype == "fill-input":
        need("selector", bool(str(params.get("selector") or "").strip()))
    elif ntype == "submit-click":
        need("selector", bool(str(params.get("selector") or "").strip()))
    elif ntype == "wait-done-signal":
        need("type", params.get("type") in _DONE_TYPES)
        if params.get("type") in {"selector_appear", "selector_disappear"}:
            need("selector", bool(str(params.get("selector") or "").strip()))
        scope = params.get("scope")
        if scope is not None and scope not in _COPY_SCOPES:
            errs.append(f"invalid field: nodes[{i}].params.scope "
                        f"({' | '.join(sorted(_COPY_SCOPES))})")
    elif ntype == "extract-text":
        need("selector", bool(str(params.get("selector") or "").strip()))
    elif ntype == "extract-media":
        has_media = bool(str(params.get("media_selector") or "").strip())
        has_copy = bool(str(params.get("copy_selector") or "").strip())
        if not (has_media or has_copy):
            errs.append(f"missing/invalid field: nodes[{i}].params.media_selector "
                        "(hoặc copy_selector)")
    elif ntype == "delay":
        ms = params.get("ms")
        if ms is not None and (not isinstance(ms, int) or ms < 0):
            errs.append(f"invalid field: nodes[{i}].params.ms (số nguyên >= 0)")
    elif ntype == "set-variable":
        need("name", bool(str(params.get("name") or "").strip()))
    elif ntype == "eval-js":
        need("code", bool(str(params.get("code") or "").strip()))
    elif ntype == "condition":
        # Biểu thức rẽ nhánh — executor v1 hiểu `value` là tên biến boolean
        # trong context, hoặc `expression` dạng chuỗi đơn giản.
        if not params.get("expression") and not params.get("value"):
            errs.append(f"missing/invalid field: nodes[{i}].params.expression "
                        "(hoặc value)")
    elif ntype == "action-sequence":
        need("action", bool(str(params.get("action") or "").strip()))
    return errs


def _atomic_write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".tmp.")
    try:
        text = json.dumps(obj, ensure_ascii=False, indent=2)
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


def _summary(data: dict, slug: str) -> dict:
    nodes = data.get("nodes") if isinstance(data.get("nodes"), list) else []
    edges = data.get("edges") if isinstance(data.get("edges"), list) else []
    return {
        "slug": slug,
        "flow_type": data.get("flow_type") or data.get("type") or "text",
        "capability": data.get("capability") or "chat",
        "enabled": bool(data.get("enabled", True)),
        "display_name": (data.get("meta") or {}).get("display_name")
        if isinstance(data.get("meta"), dict) else None,
        "description": (data.get("meta") or {}).get("description")
        if isinstance(data.get("meta"), dict) else None,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "source_recipe": (data.get("meta") or {}).get("source_recipe")
        if isinstance(data.get("meta"), dict) else None,
    }


def list_flows(flows_dir: Path) -> list[dict]:
    """Liệt kê mọi flow đọc được. Flow hỏng validate vẫn liệt kê kèm lỗi."""
    flows_dir = Path(flows_dir)
    if not flows_dir.is_dir():
        return []
    out: list[dict] = []
    for child in sorted(flows_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        path = child / "flow.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as error:
            out.append({"slug": child.name, "enabled": True, "flow_type": "text",
                        "capability": "chat", "node_count": 0, "edge_count": 0,
                        "parse_error": str(error)})
            continue
        if not isinstance(data, dict):
            out.append({"slug": child.name, "enabled": True, "flow_type": "text",
                        "capability": "chat", "node_count": 0, "edge_count": 0,
                        "parse_error": "flow.json phải là một mapping"})
            continue
        data.setdefault("slug", child.name)
        summary = _summary(data, child.name)
        errs = validate_flow({**data, "slug": child.name})
        if errs:
            summary["errors"] = errs
        out.append(summary)
    return out


def load_flow(flows_dir: Path, slug: str) -> dict | None:
    path = flow_path(Path(flows_dir), slug)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("slug", slug)
    return data


def save_flow(flows_dir: Path, slug: str, data: dict[str, Any]) -> dict[str, Any]:
    """Validate rồi ghi atomic. Ném ``ValueError`` khi flow không hợp lệ."""
    payload = dict(data)
    payload["slug"] = slug
    errs = validate_flow(payload)
    if errs:
        raise ValueError("; ".join(errs))
    _atomic_write_json(flow_path(Path(flows_dir), slug), payload)
    return payload


def delete_flow(flows_dir: Path, slug: str) -> bool:
    import shutil

    target = Path(flows_dir) / slug
    # Chặn path traversal: slug chỉ [a-z0-9-] nên target luôn nằm trong flows_dir.
    if not slug_ok(slug) or not target.is_dir():
        return False
    shutil.rmtree(target)
    return True


def duplicate_flow(flows_dir: Path, slug: str, new_slug: str) -> dict[str, Any]:
    """Copy nhanh một flow (đã chốt: cho phép duplicate, đổi tên như model)."""
    if not slug_ok(new_slug):
        raise ValueError("invalid field: slug (chỉ [a-z0-9-])")
    src = load_flow(Path(flows_dir), slug)
    if src is None:
        raise FileNotFoundError(f"Flow '{slug}' không tồn tại")
    if flow_path(Path(flows_dir), new_slug).exists():
        raise FileExistsError(f"Slug '{new_slug}' đã tồn tại")
    payload = dict(src)
    payload["slug"] = new_slug
    meta = dict(payload.get("meta") or {})
    meta["duplicated_from"] = slug
    payload["meta"] = meta
    return save_flow(Path(flows_dir), new_slug, payload)
