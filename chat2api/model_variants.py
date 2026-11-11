"""Biến thể model: ghép một model gốc với một chế độ (thinking/fast, mức effort…)
thành model ID mới, ví dụ `qwen3.8-max` + `thinking` → `qwen3.8-max-thinking`.

Recipe khai báo:

    variants:
      thinking:
        label: Thinking                 # tùy chọn, nối vào label của model gốc
        action: 'click:.mode-btn;click:[role="menuitem"]:text-is("Thinking")'
        models: ['qwen3.*', '!qwen3.5-omni-*']   # glob; '!' để loại; mặc định ['*']
        when: {thinking: true}          # điều kiện trên `meta` lấy từ model_list API
      max:
        suffix: max                     # mặc định = tên biến thể
        action: 'slider:[role="slider"][aria-label="Effort"]=Max'

Model sinh ra = bản sao model gốc với `id: <gốc>-<suffix>`, `action` = action
của model gốc rồi tới action của biến thể, `value` giữ của model gốc (bước
`select:` vẫn chọn đúng option), thêm `base` / `variant` để truy ngược.
Model gốc khai `variants: false` (hoặc list tên biến thể) để tắt/giới hạn.
Model khai tay trùng ID với model sinh ra thì bản khai tay thắng.

Chỉ model chat được ghép: model chỉ tạo ảnh/video không có chế độ suy nghĩ.
Biến thể áp cho cả model quét được theo account (catalog), không chỉ model
viết sẵn trong recipe.
"""
from fnmatch import fnmatchcase

from . import flows

_ID_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789._-")


def _variants(recipe: dict) -> dict:
    raw = recipe.get("variants")
    return raw if isinstance(raw, dict) else {}


def _applies(patterns, model_id: str) -> bool:
    pats = [str(p) for p in (patterns if isinstance(patterns, list) else ["*"])]
    include = [p for p in pats if not p.startswith("!")] or ["*"]
    exclude = [p[1:] for p in pats if p.startswith("!")]
    return (any(fnmatchcase(model_id, p) for p in include)
            and not any(fnmatchcase(model_id, p) for p in exclude))


def _is_chat(model: dict) -> bool:
    return "chat" in flows.capabilities_of(model)


def _join(*actions) -> str:
    return ";".join(a.strip().strip(";") for a in actions if isinstance(a, str) and a.strip())


def _plan(model: dict, variants: dict):
    """(id mới, tên biến thể, spec) cho mọi biến thể áp được lên `model`."""
    if model.get("variant") or not _is_chat(model):
        return
    allowed = model.get("variants", True)
    if allowed is False:
        return
    for name, spec in variants.items():
        if not isinstance(spec, dict):
            continue
        if isinstance(allowed, list) and name not in allowed:
            continue
        if not _applies(spec.get("models"), model["id"]):
            continue
        meta = model.get("meta")
        # `when` chỉ xét được khi model có `meta` (lấy qua model_list API).
        # Model chưa có meta (khai tay, catalog chưa quét) chỉ lọc bằng glob.
        if spec.get("when") and isinstance(meta, dict) and not _meets(meta, spec["when"]):
            continue
        yield f"{model['id']}-{spec.get('suffix') or name}", name, spec


def _meets(meta: dict, when: dict) -> bool:
    """Mọi điều kiện đều đúng. `true/false` so độ "có"; list trong meta → chứa;
    còn lại so chuỗi không phân biệt hoa thường."""
    for key, want in when.items():
        have = meta.get(key)
        if isinstance(want, bool):
            ok = bool(have) == want
        elif isinstance(have, (list, tuple)):
            ok = str(want).lower() in [str(x).lower() for x in have]
        else:
            ok = str(have).lower() == str(want).lower()
        if not ok:
            return False
    return True


def expand(models: list, variants: dict) -> list[dict]:
    """`models` + mọi tổ hợp model×biến thể hợp lệ, giữ thứ tự: gốc rồi tới con."""
    base = [m for m in models or [] if isinstance(m, dict) and m.get("id")]
    if not variants:
        return list(base)
    taken = {m["id"] for m in base}
    plans = {m["id"]: list(_plan(m, variants)) for m in base}
    # Model khai tay trùng ID một tổ hợp (vd `a-thinking`) là biến thể viết
    # tay, không được bung tiếp thành `a-thinking-thinking`.
    composed = {new_id for plan in plans.values() for new_id, _, _ in plan}
    out: list[dict] = []
    for model in base:
        out.append(model)
        if model["id"] in composed:
            continue
        for new_id, name, spec in plans[model["id"]]:
            if new_id in taken:
                continue
            taken.add(new_id)
            child = {k: v for k, v in model.items() if k != "variants"}
            child.update(id=new_id, base=model["id"], variant=name,
                         action=_join(model.get("action"), spec.get("action")),
                         value=str(model.get("value") or model["id"]))
            if model.get("label") or spec.get("label"):
                child["label"] = " ".join(x for x in (str(model.get("label") or model["id"]),
                                                     str(spec.get("label") or name)) if x)
            out.append(child)
    return out


def expand_recipe(recipe: dict) -> list[dict]:
    return expand(recipe.get("models") or [], _variants(recipe))


def validate(recipe: dict) -> list[str]:
    raw = recipe.get("variants")
    if raw is None:
        return []
    if not isinstance(raw, dict) or not raw:
        return ["invalid field: variants (mapping tên -> {action, models?, suffix?, label?})"]
    errs: list[str] = []
    for name, spec in raw.items():
        where = f"variants.{name}"
        if not isinstance(spec, dict):
            errs.append(f"invalid field: {where} (phải là mapping)")
            continue
        suffix = str(spec.get("suffix") or name)
        if not suffix or not set(suffix) <= _ID_CHARS:
            errs.append(f"invalid field: {where}.suffix (chỉ [a-z0-9._-])")
        action = spec.get("action")
        if not isinstance(action, str) or not action.strip():
            errs.append(f"missing/invalid field: {where}.action")
        else:
            errs += flows._action_errors(f"{where}.action", action)
        when = spec.get("when")
        if when is not None and not (isinstance(when, dict) and when):
            errs.append(f"invalid field: {where}.when (mapping khóa meta -> giá trị)")
        pats = spec.get("models")
        if pats is not None and not (isinstance(pats, list) and pats
                                     and all(isinstance(p, str) and p.strip("!") for p in pats)):
            errs.append(f"invalid field: {where}.models (list glob, '!' để loại)")
    for i, model in enumerate(recipe.get("models") or []):
        allowed = model.get("variants") if isinstance(model, dict) else None
        if allowed is None or allowed is False or allowed is True:
            continue
        if not (isinstance(allowed, list) and all(a in raw for a in allowed)):
            errs.append(f"invalid field: models[{i}].variants (false | list tên trong variants)")
    return errs
