"""Đọc/ghi cấu hình runtime trong .env cho trang Settings.

Chỉ các khoá khai báo ở FIELDS mới được sửa qua API — .env có thể chứa thứ khác
mà app không nên đụng tới. Ghi lại giữ nguyên comment và thứ tự dòng cũ.
"""

import os
from pathlib import Path

# apply: "reload"  -> có hiệu lực ngay sau khi reload recipe (đọc env lúc dựng recipe)
#        "restart" -> Config đọc một lần lúc khởi động, phải chạy lại server
FIELDS: list[dict] = [
    {"key": "RECIPE_READY_DELAY_MS", "type": "int", "default": "1200", "group": "Browser",
     "apply": "reload", "label": "Delay chờ web sẵn sàng (ms)",
     "help": "Chờ thêm sau khi ô input hiện ra, trước khi thao tác."},
    {"key": "RECIPE_INPUT_DELAY_MS", "type": "int", "default": "400", "group": "Browser",
     "apply": "reload", "label": "Delay trước khi nhập prompt (ms)",
     "help": "Chờ ngay trước khi đổ prompt vào ô input."},
    {"key": "RECIPE_READY_TIMEOUT_MS", "type": "int", "default": "20000", "group": "Browser",
     "apply": "reload", "label": "Hạn chờ ô input xuất hiện (ms)"},
    {"key": "POOL_MAX_CONTEXTS", "type": "int", "default": "3", "group": "Browser",
     "apply": "restart", "label": "Số browser context tối đa"},
    {"key": "BROWSER_ENGINE", "type": "choice", "default": "playwright", "group": "Browser",
     "apply": "restart", "label": "Engine browser", "choices": ["playwright", "cloak"]},
    {"key": "BROWSER_PROFILE_MODE", "type": "choice", "default": "storage_state",
     "group": "Browser", "apply": "restart", "label": "Chế độ danh tính trình duyệt",
     "choices": ["storage_state", "profile"],
     "help": "storage_state: mỗi recipe một context, chỉ cookie + localStorage. "
             "profile: một Chromium profile giữ đăng nhập mọi domain, mỗi recipe một tab "
             "chạy song song. Không áp dụng cho engine cloak."},
    {"key": "POOL_MAX_PROFILES", "type": "int", "default": "2", "group": "Browser",
     "apply": "restart", "label": "Số profile mở cùng lúc",
     "help": "Mỗi profile là một tiến trình Chromium. Chỉ dùng ở chế độ profile."},
    {"key": "PROFILE_MAX_TABS", "type": "int", "default": "4", "group": "Browser",
     "apply": "restart", "label": "Số tab tối đa trong một profile",
     "help": "Vượt thì tab ít dùng nhất bị đóng, browser vẫn mở."},
    {"key": "RECIPE_TIMEOUT_MS", "type": "int", "default": "120000", "group": "Server",
     "apply": "restart", "label": "Hạn chờ recipe trả lời (ms)"},
    {"key": "ANON_TRIAL_LIMIT", "type": "int", "default": "20", "group": "Server",
     "apply": "restart", "label": "Số lượt dùng thử ẩn danh",
     "help": "0 = không giới hạn."},
    {"key": "CHAT2API_KEYS", "type": "secret", "default": "", "group": "Server",
     "apply": "restart", "label": "API key (ngăn cách bằng dấu phẩy)",
     "help": "Để trống = không yêu cầu key."},
    {"key": "ENABLE_AGENT_FALLBACK", "type": "bool", "default": "false", "group": "Agent",
     "apply": "restart", "label": "Bật agent fallback khi recipe hỏng"},
    {"key": "INTEGRATE_MAX_ROUNDS", "type": "int", "default": "5", "group": "Agent",
     "apply": "restart", "label": "Số vòng thử tối đa khi Integrate"},
    {"key": "AGENT_LLM_BASE_URL", "type": "str", "default": "", "group": "Agent",
     "apply": "restart", "label": "LLM base URL"},
    {"key": "AGENT_LLM_MODEL", "type": "str", "default": "", "group": "Agent",
     "apply": "restart", "label": "LLM model"},
    {"key": "AGENT_LLM_API_KEY", "type": "secret", "default": "", "group": "Agent",
     "apply": "restart", "label": "LLM API key"},
]

BY_KEY = {f["key"]: f for f in FIELDS}
TRUE = {"1", "true", "yes", "on"}


def describe() -> list[dict]:
    """Giá trị hiện tại kèm metadata để UI dựng form. Secret không bao giờ trả ra."""
    out = []
    for field in FIELDS:
        raw = os.environ.get(field["key"], field["default"])
        entry = {k: v for k, v in field.items()}
        if field["type"] == "secret":
            entry["value"] = ""
            entry["is_set"] = bool(raw)
        else:
            entry["value"] = raw
        out.append(entry)
    return out


def validate(values: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Lọc bỏ khoá lạ, kiểm kiểu. Trả (giá trị sạch, danh sách lỗi)."""
    clean: dict[str, str] = {}
    errors: list[str] = []
    for key, value in values.items():
        field = BY_KEY.get(key)
        if field is None:
            errors.append(f"khoá không hợp lệ: {key}")
            continue
        text = ("" if value is None else str(value)).strip()
        if field["type"] == "secret" and not text:
            # Ô secret để trống nghĩa là giữ nguyên giá trị cũ, không phải xoá.
            continue
        if field["type"] == "int":
            try:
                number = int(text)
            except ValueError:
                errors.append(f"{key}: phải là số nguyên")
                continue
            if number < 0:
                errors.append(f"{key}: phải >= 0")
                continue
            text = str(number)
        elif field["type"] == "bool":
            text = "true" if text.lower() in TRUE else "false"
        elif field["type"] == "choice" and text not in field["choices"]:
            errors.append(f"{key}: chỉ nhận {' | '.join(field['choices'])}")
            continue
        if "\n" in text or "\r" in text:
            errors.append(f"{key}: không được chứa xuống dòng")
            continue
        clean[key] = text
    return clean, errors


def _render(lines: list[str], values: dict[str, str]) -> list[str]:
    remaining = dict(values)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
                continue
        out.append(line)
    if remaining:
        if out and out[-1].strip():
            out.append("")
        out.extend(f"{key}={value}" for key, value in remaining.items())
    return out


def save(env_path: Path, values: dict[str, str]) -> list[str]:
    """Ghi .env (giữ comment/thứ tự cũ) và cập nhật os.environ.

    Trả về các khoá cần khởi động lại server mới có hiệu lực.
    """
    env_path = Path(env_path)
    old = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(_render(old, values)) + "\n", encoding="utf-8")
    needs_restart = []
    for key, value in values.items():
        os.environ[key] = value
        if BY_KEY[key]["apply"] == "restart":
            needs_restart.append(key)
    return needs_restart
