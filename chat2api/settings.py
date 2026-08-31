"""Cấu hình runtime cho trang Settings — bảng `setting` là kho chính.

Thứ tự ưu tiên khi đọc một khoá (docs/design-v2.md §2, pha 6):

1. **môi trường thật / `.env`** — dành cho bootstrap và CI. Đặt ở đây là chốt
   cứng: một lần bấm Lưu trên UI không được ghi đè lặng lẽ giá trị mà người
   vận hành đã ghim từ bên ngoài.
2. **bảng `setting`** — thứ trang Settings ghi vào.
3. **`default` khai báo ở FIELDS**.

Bước nối hai thế giới là `preload()`: `Config.__init__` gọi nó ngay sau
`load_dotenv`, đổ hàng DB vào `os.environ` cho những khoá `.env` bỏ trống. Nhờ
vậy mọi chỗ đang đọc `os.environ` (Config, provider, recipe) thấy giá trị lưu
trong DB mà không phải biết DB tồn tại.

Chỉ các khoá khai báo ở FIELDS mới được sửa qua API — .env có thể chứa thứ khác
mà app không nên đụng tới. Khi kho SQLite chưa mở, `save()` rơi về ghi thẳng
`.env` (giữ nguyên comment và thứ tự dòng cũ) để app không có DB vẫn cấu hình được.
"""

import os
import sqlite3
from pathlib import Path

from . import store

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
    {"key": "POOL_MAX_PROFILES", "type": "int", "default": "6", "group": "Browser",
     "apply": "restart", "label": "Số profile mở cùng lúc",
     "help": "Mỗi profile là một tiến trình Chromium. Chỉ dùng ở chế độ profile. "
             "Đây là trần cho số profile chọn được cùng lúc ở bàn test Sessions."},
    {"key": "PROFILE_MAX_TABS", "type": "int", "default": "8", "group": "Browser",
     "apply": "restart", "label": "Số tab tối đa trong một profile",
     "help": "Vượt thì tab RẢNH ít dùng nhất bị đóng, browser vẫn mở. Đây là trần "
             "cho số domain/account của cùng một profile chạy song song."},
    {"key": "API_ACCOUNT_STRATEGY", "type": "choice", "default": "least_busy", "group": "API",
     "apply": "reload", "label": "Cách chọn account cho mỗi request",
     "choices": ["least_busy", "round_robin", "sticky_session", "off"],
     "help": "Client gọi /v1/chat/completions mà không gửi header X-Chat2api-Account-Id thì "
             "server tự chọn. least_busy: ưu tiên account đang rảnh nhất (nhiều request một "
             "lúc sẽ toả ra nhiều profile). round_robin: xoay vòng đều. sticky_session: cùng "
             "một session luôn về đúng một account. off: giữ cách cũ (storage_state, không gắn "
             "profile vào request)."},
    {"key": "API_MAX_CONCURRENT_PER_ACCOUNT", "type": "int", "default": "1", "group": "API",
     "apply": "reload", "label": "Số request song song trên một account",
     "help": "Mỗi slot là một tab riêng trong cùng profile. Để 1 nếu site chỉ chịu được một "
             "hội thoại mỗi lúc; request thứ hai của cùng account sẽ xếp hàng."},
    {"key": "API_MAX_CONCURRENT_REQUESTS", "type": "int", "default": "0", "group": "API",
     "apply": "reload", "label": "Trần request chat song song",
     "help": "0 = không giới hạn. Vượt trần thì request mới chờ, không bị từ chối."},
    {"key": "API_HEADED", "type": "choice", "default": "auto", "group": "API",
      "apply": "reload", "label": "Hiện cửa sổ browser cho request API",
      "choices": ["auto", "always", "never"],
      "help": "auto (mặc định): theo ô 'Chạy ẩn' của từng profile ở tab "
              "Profiles — profile headless=true thì chạy ẩn, ngược lại hiện cửa sổ. "
              "always: mọi request API mở cửa sổ nhìn thấy được. "
              "never: luôn chạy ẩn. Header X-Chat2api-Headed của client vẫn thắng cả ba."},
    {"key": "API_SESSION_MODE", "type": "choice", "default": "per_request", "group": "API",
     "apply": "reload", "label": "Gom request thành session",
     "choices": ["per_request", "client_window"],
     "help": "per_request: mỗi request không kèm header X-Chat2api-Session-Id là một session "
             "riêng. client_window: gom các request cùng client + model trong 30 phút vào "
             "chung một session."},
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
SECRET_KEYS = {f["key"] for f in FIELDS if f["type"] == "secret"}

# Khoá đã có sẵn trong môi trường thật / `.env` lúc Config() chạy. Chúng thắng
# bảng `setting` — xem docstring đầu file.
_env_keys: set[str] = set()
# Khoá do chính module này bơm vào os.environ (preload/save). Phải nhớ để lần
# dựng Config kế tiếp trong cùng tiến trình không nhầm chúng là do `.env` đặt —
# nếu nhầm, mọi khoá lưu ở DB sẽ tự khoá chính nó sau một vòng khởi động.
_injected: set[str] = set()


def capture_env() -> set[str]:
    """Chụp danh sách khoá do môi trường/`.env` đặt. Gọi từ `Config.__init__`."""
    global _env_keys
    _env_keys = {f["key"] for f in FIELDS
                 if os.environ.get(f["key"], "") != "" and f["key"] not in _injected}
    return _env_keys


def env_locked(key: str) -> bool:
    """True khi `.env` đang ghim khoá này — ghi vào DB sẽ không có tác dụng."""
    return key in _env_keys


def shadowed(keys) -> list[str]:
    """Trong các khoá vừa lưu, khoá nào bị `.env` che mất."""
    return sorted(key for key in keys if key in _env_keys)



def current(key: str) -> str:
    """Giá trị đang chạy của một khoá — không phải giá trị lúc khởi động.

    `preload()` và `save()` đều bơm vào `os.environ`, nên đọc từ đó là cách duy
    nhất để một khoá `apply: reload` có hiệu lực ngay khi người dùng bấm Lưu.
    """
    field = BY_KEY.get(key)
    if field is None:
        return ""
    value = os.environ.get(key, "")
    return value if value != "" else str(field["default"])


def current_bool(key: str) -> bool:
    return current(key).strip().lower() in TRUE


def current_int(key: str, minimum: int | None = None) -> int:
    try:
        value = int(current(key))
    except (TypeError, ValueError):
        value = int(BY_KEY[key]["default"])
    return value if minimum is None else max(minimum, value)


def stored() -> dict[str, str]:
    """Bảng `setting` dưới dạng dict. Rỗng khi kho chưa mở hoặc đọc lỗi."""
    db = store.default()
    if db is None:
        return {}
    try:
        return {row["key"]: row["value"] for row in db.query("SELECT key, value FROM setting")}
    except Exception:
        return {}


def preload(db_path) -> int:
    """Đổ bảng `setting` vào os.environ cho những khoá `.env` không đặt.

    Mở **read-only**: hàm này chạy trong `Config.__init__`, tức là lúc import
    `chat2api.main` — import không được phép tạo file trong thư mục dữ liệu của
    người dùng (cùng lý do với `store.connect` nằm ở lifespan).
    """
    path = Path(db_path)
    if not path.is_file():
        return 0
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error:
        return 0
    try:
        rows = conn.execute("SELECT key, value FROM setting").fetchall()
    except sqlite3.Error:
        return 0  # DB chưa migrate: chưa có bảng `setting` nào để đọc
    finally:
        conn.close()
    count = 0
    for key, value in rows:
        if key in BY_KEY and key not in _env_keys:
            os.environ[key] = value
            _injected.add(key)
            count += 1
    return count


def describe() -> list[dict]:
    """Giá trị hiện tại kèm metadata để UI dựng form. Secret không bao giờ trả ra."""
    rows = stored()
    out = []
    for field in FIELDS:
        key = field["key"]
        if key in _env_keys:
            raw, source = os.environ[key], "env"
        elif key in rows:
            raw, source = rows[key], "db"
        else:
            raw, source = os.environ.get(key, field["default"]), "default"
        entry = {k: v for k, v in field.items()}
        entry["source"] = source
        entry["env_locked"] = source == "env"
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


def _save_env(env_path: Path, values: dict[str, str]) -> None:
    """Ghi .env giữ nguyên comment và thứ tự dòng cũ."""
    env_path = Path(env_path)
    old = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(_render(old, values)) + "\n", encoding="utf-8")


def _save_db(db, values: dict[str, str]) -> None:
    conn = db.connection()
    now = store.now_ms()
    with conn:
        for key, value in values.items():
            conn.execute(
                "INSERT INTO setting(key, value, is_secret, updated_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
                " is_secret = excluded.is_secret, updated_at = excluded.updated_at",
                (key, value, int(key in SECRET_KEYS), now))


def save(env_path: Path, values: dict[str, str]) -> list[str]:
    """Lưu vào bảng `setting` (hoặc .env khi kho chưa mở) và cập nhật os.environ.

    Blocking (SQLite + file) nên phải gọi qua `asyncio.to_thread` trong handler
    async. Trả về các khoá cần khởi động lại server mới có hiệu lực.

    Khoá bị `.env` ghim vẫn được ghi xuống DB nhưng không đổi giá trị đang chạy —
    hỏi `shadowed()` để nói thẳng chuyện đó, thay vì để người dùng tưởng đã xong.
    """
    db = store.default()
    if db is None:
        _save_env(Path(env_path), values)
    else:
        _save_db(db, values)
    needs_restart = []
    for key, value in values.items():
        if key not in _env_keys:
            os.environ[key] = value
            _injected.add(key)
        if BY_KEY[key]["apply"] == "restart":
            needs_restart.append(key)
    return needs_restart
