"""Flow — thao tác đã ghi, chia theo việc mà nó phục vụ.

Trước đây recipe chỉ mô tả ĐÚNG MỘT luồng: gõ prompt vào ``prompt.input_selector``
rồi đọc câu trả lời ở ``response.last_message_selector``. Tạo ảnh phải mượn tạm
``mode.image_action`` + ``response.image_selector`` gắn kèm vào luồng chat đó, và
tạo video thì không có chỗ nào để khai báo.

Ở đây mỗi loại việc là một *flow* riêng, ghi riêng, chạy riêng:

``select_model``
    Phần dạo đầu dùng chung: mở dropdown model, chờ nó hiện ra. Bản thân việc
    chọn model nào vẫn nằm ở ``models[].action`` vì mỗi model một đường bấm.
``text``
    Gửi prompt, đọc chữ — phục vụ ``POST /v1/chat/completions``.
``image``
    Gửi prompt, đọc ảnh — phục vụ ``POST /v1/images/generations``.
``video``
    Gửi prompt, đọc video. Chạy được nhưng chưa gắn endpoint OpenAI: API video
    của OpenAI là job bất đồng bộ (tạo job → poll → tải file), tách ra làm sau.

Ba flow sau có cùng hình dạng: ``action`` (chuyển chế độ) → ``prompt`` (gõ +
gửi) → ``response`` (chờ xong + lấy kết quả), nên chúng phối hợp được với nhau
và với ``select_model`` mà không cần code riêng cho từng loại.

Recipe cũ (phẳng, không có khóa ``flows``) vẫn chạy nguyên trạng: ``build_flows``
dựng flow tương đương từ ``prompt`` / ``response`` / ``mode``.
"""

from __future__ import annotations

from copy import deepcopy

# Thứ tự cũng là thứ tự hiển thị trong UI ghi thao tác.
FLOW_KINDS: tuple[str, ...] = ("select_model", "text", "image", "video")
# Flow sinh nội dung: cùng hình dạng action → prompt → response.
GENERATE_FLOWS: tuple[str, ...] = ("text", "image", "video")
# Flow trả về file (ảnh/video) thay vì chữ.
MEDIA_FLOWS: tuple[str, ...] = ("image", "video")

FLOW_LABELS: dict[str, str] = {
    "select_model": "Chọn model",
    "text": "Generate text",
    "image": "Generate image",
    "video": "Generate video",
}

# capability trong models[] ↔ flow chạy nó.
CAPABILITY_FLOW: dict[str, str] = {"chat": "text", "image": "image", "video": "video"}
FLOW_CAPABILITY: dict[str, str] = {v: k for k, v in CAPABILITY_FLOW.items()}
CAPABILITIES: tuple[str, ...] = ("chat", "image", "video", "both")

# Alias thân thiện trong YAML → khóa chuẩn của response một media flow.
_MEDIA_ALIASES: dict[str, str] = {
    "image_selector": "media_selector",
    "video_selector": "media_selector",
    "image_copy_selector": "copy_selector",
    "video_copy_selector": "copy_selector",
    "image_copy_scope": "copy_scope",
    "video_copy_scope": "copy_scope",
    "image_copy_exclude": "copy_exclude",
    "video_copy_exclude": "copy_exclude",
}

_TEXT_RESPONSE_KEYS = ("last_message_selector", "done_signal", "format", "capture_html")
_MEDIA_RESPONSE_KEYS = ("media_selector", "copy_selector", "copy_scope", "copy_exclude",
                        "done_signal", "capture_html")


def capabilities_of(model: dict) -> set[str]:
    """Tập capability của một model. ``both`` = chat + image (nghĩa cũ).

    Nhận cả list (``[chat, image]``) lẫn chuỗi ngăn bằng dấu phẩy
    (``"chat,video"``) để một model khai báo được nhiều việc mà không phải mượn
    lại chữ ``both``.
    """
    raw = model.get("capability") or "chat"
    if isinstance(raw, (list, tuple, set)):
        items = [str(x).strip() for x in raw]
    else:
        items = [part.strip() for part in str(raw).split(",")]
    out: set[str] = set()
    for item in items:
        if item == "both":
            out.update({"chat", "image"})
        elif item in CAPABILITIES:
            out.add(item)
    return out or {"chat"}


def capability_valid(raw) -> bool:
    """True nếu giá trị ``capability`` khai báo được — dùng cho validate."""
    if isinstance(raw, (list, tuple, set)):
        items = [str(x).strip() for x in raw]
    elif isinstance(raw, str):
        items = [part.strip() for part in raw.split(",")]
    else:
        return False
    return bool(items) and all(item in CAPABILITIES for item in items)


def flows_of(model: dict) -> set[str]:
    """Các flow mà model này chạy được."""
    return {CAPABILITY_FLOW[c] for c in capabilities_of(model) if c in CAPABILITY_FLOW}


def _canon_media_response(raw: dict) -> dict:
    """Đổi alias ``image_*`` / ``video_*`` về khóa chuẩn của media flow."""
    out: dict = {}
    for key, value in (raw or {}).items():
        out[_MEDIA_ALIASES.get(key, key)] = value
    return {k: v for k, v in out.items() if k in _MEDIA_RESPONSE_KEYS and v is not None}


def _pick(src: dict, keys) -> dict:
    return {k: deepcopy(src[k]) for k in keys if src.get(k) is not None}


def _legacy_flows(recipe: dict) -> dict[str, dict]:
    """Dựng flows tương đương từ recipe phẳng đời cũ."""
    prompt = recipe.get("prompt") or {}
    response = recipe.get("response") or {}
    mode = recipe.get("mode") or {}
    models = [m for m in (recipe.get("models") or []) if isinstance(m, dict)]

    out: dict[str, dict] = {}
    if mode.get("selector") or mode.get("model_action"):
        out["select_model"] = {k: v for k, v in {
            "selector": mode.get("selector"),
            "action": mode.get("model_action"),
        }.items() if v}

    # Luồng chat cũ luôn tồn tại: recipe phẳng nào cũng gõ prompt rồi đọc chữ.
    text: dict = {"prompt": deepcopy(prompt), "response": _pick(response, _TEXT_RESPONSE_KEYS)}
    if mode.get("chat_action"):
        text["action"] = mode["chat_action"]
    out["text"] = text

    # Ảnh: chỉ dựng khi recipe có dấu hiệu tạo ảnh, không thì mọi recipe chat
    # đều tự nhiên "hỗ trợ ảnh" và /v1/images sẽ nhận rồi hỏng giữa chừng.
    image_response = _canon_media_response(response)
    has_image = bool(image_response.get("media_selector") or image_response.get("copy_selector")
                     or mode.get("image_action")
                     or any("image" in flows_of(m) for m in models))
    if has_image:
        image: dict = {"prompt": deepcopy(prompt),
                       "response": image_response or _pick(response, ("done_signal",))}
        image["response"].setdefault("done_signal", deepcopy(response.get("done_signal") or {}))
        if mode.get("image_action"):
            image["action"] = mode["image_action"]
        out["image"] = image
    return out


def build_flows(recipe: dict) -> dict[str, dict]:
    """Flows chuẩn hoá của recipe — khai báo tường minh thắng, không thì suy từ recipe cũ.

    Flow khai báo tường minh vẫn được vá những chỗ bỏ trống bằng phần phẳng:
    recipe chỉ thêm ``flows.image`` mà không lặp lại ``prompt`` thì flow ảnh
    dùng luôn ô nhập của recipe (rất nhiều site dùng chung một ô cho mọi chế độ).
    """
    declared = recipe.get("flows")
    if not isinstance(declared, dict) or not declared:
        return _legacy_flows(recipe)

    base_prompt = recipe.get("prompt") or {}
    base_response = recipe.get("response") or {}
    out: dict[str, dict] = {}
    for kind in FLOW_KINDS:
        spec = declared.get(kind)
        if not isinstance(spec, dict):
            continue
        if kind == "select_model":
            out[kind] = {k: deepcopy(v) for k, v in spec.items() if v is not None}
            continue
        prompt = deepcopy(spec.get("prompt") or base_prompt)
        raw_response = spec.get("response") or {}
        if kind in MEDIA_FLOWS:
            response = _canon_media_response(raw_response)
            if not response.get("done_signal"):
                response["done_signal"] = deepcopy(base_response.get("done_signal") or {})
        else:
            response = _pick(raw_response, _TEXT_RESPONSE_KEYS)
            for key in _TEXT_RESPONSE_KEYS:
                if response.get(key) is None and base_response.get(key) is not None:
                    response[key] = deepcopy(base_response[key])
        flow: dict = {"prompt": prompt, "response": response}
        if spec.get("action"):
            flow["action"] = spec["action"]
        if spec.get("selector"):
            flow["selector"] = spec["selector"]
        out[kind] = flow
    if "text" not in out and (base_prompt or base_response):
        out["text"] = {"prompt": deepcopy(base_prompt),
                       "response": _pick(base_response, _TEXT_RESPONSE_KEYS)}
    return out


def _action_errors(label: str, value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, str):
        return [f"invalid field: {label} (phải là string)"]
    if not value.strip():
        return []
    steps = [s.strip() for s in value.split(";") if s.strip()]
    ok = steps and all(
        (s.startswith("click:") or s.startswith("select:")) and s.split(":", 1)[1].strip()
        for s in steps)
    return [] if ok else [f"invalid field: {label} (click:<selector> | select:<selector>)"]


def validate_flows(recipe: dict, done_signals, copy_scopes) -> list[str]:
    """Kiểm tra khối ``flows`` khai báo tường minh.

    ``done_signals`` / ``copy_scopes`` truyền từ ``browser_recipe`` để hai module
    không nhập vòng lẫn nhau.
    """
    declared = recipe.get("flows")
    if declared is None:
        return []
    if not isinstance(declared, dict):
        return ["invalid field: flows (phải là mapping)"]
    if not declared:
        return ["invalid field: flows (rỗng — bỏ hẳn khóa này nếu không dùng)"]

    errs: list[str] = []
    for kind, spec in declared.items():
        if kind not in FLOW_KINDS:
            errs.append(f"invalid field: flows.{kind} (chỉ {', '.join(FLOW_KINDS)})")
            continue
        if not isinstance(spec, dict):
            errs.append(f"invalid field: flows.{kind} (phải là mapping)")
            continue
        errs += _action_errors(f"flows.{kind}.action", spec.get("action"))
        if spec.get("selector") is not None and not isinstance(spec.get("selector"), str):
            errs.append(f"invalid field: flows.{kind}.selector (phải là string)")
        if kind == "select_model":
            continue

    built = build_flows(recipe)
    for kind, flow in built.items():
        if kind == "select_model":
            continue
        if kind not in declared:
            continue  # flow suy ra từ phần phẳng — phần phẳng tự validate ở chỗ khác
        prompt = flow.get("prompt") or {}
        if not prompt.get("input_selector"):
            errs.append(f"missing/invalid field: flows.{kind}.prompt.input_selector")
        submit = prompt.get("submit", "Enter")
        if not isinstance(submit, str) or (submit != "Enter" and not submit.startswith("click:")):
            errs.append(f"invalid field: flows.{kind}.prompt.submit (Enter | click:<selector>)")
        response = flow.get("response") or {}
        ds = response.get("done_signal") or {}
        if ds.get("type") is not None and ds.get("type") not in done_signals:
            errs.append(f"invalid field: flows.{kind}.response.done_signal.type")
        if ds.get("type") in {"selector_appear", "selector_disappear"} and not ds.get("selector"):
            errs.append(f"missing/invalid field: flows.{kind}.response.done_signal.selector")
        for key in ("scope", "copy_scope"):
            value = ds.get(key) if key == "scope" else response.get(key)
            if value is not None and value not in copy_scopes:
                where = f"done_signal.{key}" if key == "scope" else key
                errs.append(f"invalid field: flows.{kind}.response.{where} "
                            f"({' | '.join(copy_scopes)})")
        if kind in MEDIA_FLOWS:
            if not response.get("media_selector") and not response.get("copy_selector"):
                errs.append(f"missing/invalid field: flows.{kind}.response.media_selector "
                            "(hoặc copy_selector)")
        elif not response.get("last_message_selector"):
            errs.append(f"missing/invalid field: flows.{kind}.response.last_message_selector")
    return errs


def supported_flows(recipe: dict) -> list[str]:
    """Các flow recipe này chạy được, theo thứ tự hiển thị."""
    built = build_flows(recipe)
    return [k for k in FLOW_KINDS if k in built]
