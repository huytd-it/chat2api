"""Convert ``recipes/*/recipe.yaml`` thành template Flows kiểu n8n.

Quy ước đã chốt:

- 1 recipe cũ tách thành N flow con, mỗi flow = 1 model (``1 file = 1 flow``).
- Template là chuỗi tuyến tính suy từ recipe để người dùng so được cái nào
  dễ custom hơn, sau đó tự sửa trên canvas.
- Account/login/trial khai riêng trong từng flow (không mượn recipe gốc).
- ``models[]`` cũ không expose nữa — đường bấm chọn model thành node
  ``select-model`` trong graph.
- Migration idempotent: flow đã tồn tại thì giữ nguyên (người dùng có thể đã
  sửa trên canvas), chỉ tạo mới.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import flows as flows_mod

_X = 220


def sanitize_slug(raw: Any, fallback: str = "flow") -> str:
    s = str(raw or "").strip().lower().replace("_", "-")
    s = re.sub(r"[^a-z0-9-]+", "-", s).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return s or fallback


def _flow_kind_for_model(model: dict, built: dict[str, dict]) -> str:
    """Flow mà model này chạy — cùng logic ``BrowserRecipe.flow_for_model``."""
    for name in flows_mod.ordered_flows(flows_mod.flows_of(model)):
        if name in built and name != "select_model":
            return name
    return "text"


def _node(nid: str, ntype: str, params: dict | None = None, x: int = 0) -> dict:
    node: dict[str, Any] = {"id": nid, "type": ntype,
                            "position": {"x": x, "y": 0}}
    if params:
        node["params"] = params
    return node


def convert_recipe(recipe: dict) -> list[dict]:
    """Một dict recipe → list dict flow (mỗi model một flow)."""
    if not isinstance(recipe, dict):
        return []
    slug = str(recipe.get("slug") or "").strip().lower()
    if not slug:
        return []
    built = flows_mod.build_flows(recipe)
    models = [m for m in (recipe.get("models") or []) if isinstance(m, dict)]
    if not models:
        models = [{}]
    url = str(recipe.get("url") or "")
    timing = recipe.get("timing") or {}
    login = recipe.get("login") or {}
    new_chat = recipe.get("new_chat") or {}
    select_flow = built.get("select_model") or {}

    out: list[dict] = []
    for model in models:
        model_id = str(model.get("id") or "").strip()
        kind = _flow_kind_for_model(model, built)
        spec = built.get(kind) or {}
        flow_type = flows_mod.flow_type(kind, spec if kind in (recipe.get("flows") or {}) else spec)
        capability = {"text": "chat", "image": "image",
                      "video": "video"}.get(flow_type, "chat")

        if len(models) == 1:
            flow_slug = slug
        else:
            short = sanitize_slug(model_id.split("/")[-1] if model_id else kind, kind)
            flow_slug = f"{slug}-{short}"

        prompt = spec.get("prompt") or recipe.get("prompt") or {}
        response = spec.get("response") or recipe.get("response") or {}
        ds = response.get("done_signal") or {}

        nodes: list[dict] = []
        xi = 0

        def add(ntype: str, params: dict | None = None) -> str:
            nonlocal xi
            nid = f"{ntype}-{len(nodes)}" if ntype != "start" else "start"
            # id duy nhất trong graph
            base, n = nid, 1
            existing = {nd["id"] for nd in nodes}
            while nid in existing:
                n += 1
                nid = f"{base}-{n}"
            nodes.append(_node(nid, ntype, params, xi * _X))
            xi += 1
            return nid

        add("start")
        if url:
            add("goto-url", {"url": url})
        ready_delay = timing.get("ready_delay_ms")
        ready_timeout = timing.get("ready_timeout_ms")
        params_ready: dict[str, Any] = {}
        if isinstance(ready_delay, int):
            params_ready["delay_ms"] = ready_delay
        if isinstance(ready_timeout, int):
            params_ready["timeout_ms"] = ready_timeout
        add("wait-ready", params_ready or None)
        if isinstance(new_chat, dict) and (new_chat.get("url") or new_chat.get("selector")):
            add("new-chat", {k: v for k, v in
                             {"url": new_chat.get("url"),
                              "selector": new_chat.get("selector")}.items() if v})
        login_params: dict[str, Any] = {
            "strategy": login.get("strategy", "round_robin"),
            "quota": login.get("quota", 50),
        }
        add("assign-account", login_params)
        if isinstance(login.get("anon_trial_limit"), int):
            add("check-trial-limit", {"limit": login.get("anon_trial_limit")})
        action = str(spec.get("action") or "")
        if action:
            add("action-sequence", {"action": action})
        model_action = str(model.get("action") or "")
        model_value = str(model.get("value") or "")
        select_selector = str(select_flow.get("selector") or "")
        select_action = str(select_flow.get("action") or "")
        if model_action or model_value or select_selector or select_action:
            add("select-model", {k: v for k, v in {
                "selector": select_selector or None,
                "prelude_action": select_action or None,
                "model_action": model_action or None,
                "value": model_value or None,
                "model": model_id or None,
            }.items() if v is not None})
        input_delay = timing.get("input_delay_ms")
        if isinstance(input_delay, int) and input_delay > 0:
            add("delay", {"ms": input_delay})
        input_selector = str(prompt.get("input_selector") or "")
        if input_selector:
            add("fill-input", {
                "selector": input_selector,
                "mode": prompt.get("input_mode", "fill"),
            })
        submit = str(prompt.get("submit", "Enter"))
        if submit.startswith("click:"):
            add("submit-click", {"selector": submit.split(":", 1)[1]})
        else:
            add("submit-enter")
        if flow_type in ("image", "video"):
            media_params: dict[str, Any] = {}
            for key in ("media_selector", "copy_selector", "copy_scope",
                        "copy_exclude", "done_signal"):
                if response.get(key) is not None:
                    media_params[key] = response.get(key)
            if ds:
                media_params.setdefault("done_signal", ds)
            add("wait-media", media_params or None)
            extract_params: dict[str, Any] = {}
            for key in ("media_selector", "copy_selector", "copy_scope",
                        "copy_exclude", "capture_html"):
                if response.get(key) is not None:
                    extract_params[key] = response.get(key)
            add("extract-media", extract_params or None)
        else:
            ds_params = dict(ds) if isinstance(ds, dict) else {"type": "stable_text"}
            ds_params.setdefault("type", "stable_text")
            add("wait-done-signal", ds_params)
            last_sel = str(response.get("last_message_selector") or "")
            extract_params = {k: v for k, v in {
                "selector": last_sel or None,
                "format": response.get("format"),
                "capture_html": response.get("capture_html"),
                "use_copy_result": ds_params.get("use_copy_result"),
            }.items() if v is not None}
            add("extract-text", extract_params or None)
            if ds_params.get("type") == "copy_button":
                add("copy-button", {k: v for k, v in {
                    "selector": ds_params.get("selector"),
                    "scope": ds_params.get("scope", "after"),
                    "exclude": ds_params.get("exclude"),
                    "use_copy_result": ds_params.get("use_copy_result", True),
                }.items() if v is not None})
        add("output")

        edges = [{"source": nodes[i]["id"], "target": nodes[i + 1]["id"],
                  "id": f"e-{nodes[i]['id']}-{nodes[i + 1]['id']}"}
                 for i in range(len(nodes) - 1)]

        out.append({
            "slug": flow_slug,
            # Tên flow trong recipe gốc (text/image/video hoặc tên tự đặt).
            # Compiler dùng nó để dựng lại đúng khối flows + models[].flow.
            "kind": kind,
            "flow_type": flow_type,
            "capability": capability,
            "enabled": True,
            "model": {"id": model_id or flow_slug},
            "account": {
                "strategy": login.get("strategy", "round_robin"),
                "quota": login.get("quota", 50),
                "anon_trial_limit": login.get("anon_trial_limit"),
            },
            "meta": {
                "display_name": flow_slug,
                "source_recipe": slug,
                "source_flow": kind,
                "source_model": model_id or None,
            },
            "nodes": nodes,
            "edges": edges,
        })
    return out


def migrate_recipe_file(recipe_path: Path, flows_dir: Path) -> list[str]:
    """Convert một file recipe.yaml → các flow.json còn thiếu. Trả về slug đã tạo."""
    import json

    import yaml

    from .flow_store import flow_path, validate_flow

    try:
        recipe = yaml.safe_load(recipe_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    if isinstance(recipe, dict) and "slug" not in recipe:
        recipe["slug"] = recipe_path.parent.name
    created: list[str] = []
    for flow in convert_recipe(recipe if isinstance(recipe, dict) else {}):
        path = flow_path(Path(flows_dir), flow["slug"])
        if path.exists():
            continue
        if validate_flow(flow):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(flow, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        created.append(flow["slug"])
    return created


def migrate_all(recipes_dir: Path, flows_dir: Path) -> dict[str, int]:
    """Auto-convert toàn bộ recipes → flows (idempotent, chỉ tạo mới)."""
    recipes_dir = Path(recipes_dir)
    flows: int = 0
    recipes: int = 0
    if not recipes_dir.is_dir():
        return {"recipes": 0, "flows": 0}
    for child in sorted(recipes_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if child.name in {"gemini", "openai"}:
            continue
        yml = child / "recipe.yaml"
        if not yml.exists():
            continue
        created = migrate_recipe_file(yml, Path(flows_dir))
        if created:
            recipes += 1
            flows += len(created)
    return {"recipes": recipes, "flows": flows}
