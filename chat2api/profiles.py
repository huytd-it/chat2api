"""Profile Chromium dùng lại được (docs/design-v2.md §3).

Một profile = một thư mục `user_data_dir` = một danh tính trình duyệt đầy đủ:
cookie + localStorage + IndexedDB + service worker của **mọi** domain cùng lúc.
Khác hẳn `storage_state` (chỉ cookie + localStorage, một file một domain).

Module này chỉ giữ phần *trạng thái* của profile: hàng trong DB, thư mục trên
đĩa, khoá pid, và seed lần đầu từ storage_state cũ. Phần mở browser thật nằm ở
`browserpool.py`.

Toàn bộ hàm ở đây là blocking (SQLite + os.path) nên phải gọi qua
`asyncio.to_thread` khi ở trong handler async.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import store

NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
DEFAULT_PROFILE = "main"


class ProfileLocked(RuntimeError):
    """user_data_dir đang bị một tiến trình Chromium khác giữ."""


@dataclass
class Profile:
    id: int
    name: str
    user_data_dir: str
    headless: bool
    max_tabs: int
    engine: str
    proxy: str | None
    user_agent: str | None
    locale: str
    timezone: str | None
    viewport: str

    @property
    def viewport_size(self) -> dict | None:
        """'1280x800' -> {'width': 1280, 'height': 800}; None nếu không đọc được."""
        try:
            width, height = self.viewport.lower().split("x", 1)
            return {"width": int(width), "height": int(height)}
        except (ValueError, AttributeError):
            return None


def valid_name(name: str) -> bool:
    return bool(name) and NAME_RE.fullmatch(name) is not None


def _row_to_profile(row: sqlite3.Row) -> Profile:
    return Profile(
        id=row["id"], name=row["name"], user_data_dir=row["user_data_dir"],
        headless=bool(row["headless"]), max_tabs=int(row["max_tabs"]),
        engine=row["engine"], proxy=row["proxy"], user_agent=row["user_agent"],
        locale=row["locale"], timezone=row["timezone"], viewport=row["viewport"],
    )


def _pid_alive(pid: int) -> bool:
    """True khi tiến trình còn chạy. Không kết luận được thì coi như còn sống.

    Thà từ chối mở nhầm (người dùng thấy lỗi rõ ràng) còn hơn mở đè lên một
    user_data_dir đang được dùng — Chromium sẽ hỏng profile.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        SYNCHRONIZE = 0x00100000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE | 0x0400, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def ensure_profile(name: str, profiles_dir: Path, *, headless: bool = True,
                   max_tabs: int = 4, make_default: bool = False) -> Profile | None:
    """Lấy profile theo tên, tạo cùng thư mục nếu chưa có. None khi kho chưa mở."""
    if not valid_name(name):
        raise ValueError(f"tên profile không hợp lệ: {name!r} (chỉ [a-z0-9-])")
    db = store.default()
    if db is None:
        return None
    conn = db.connection()
    row = conn.execute("SELECT * FROM profile WHERE name = ?", (name,)).fetchone()
    user_data_dir = Path(profiles_dir) / name
    if row is not None and row["user_data_dir"]:
        user_data_dir = Path(row["user_data_dir"])
    user_data_dir.mkdir(parents=True, exist_ok=True)

    with conn:
        if row is None:
            conn.execute(
                "INSERT INTO profile(name, user_data_dir, headless, max_tabs, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, str(user_data_dir), int(headless), max_tabs, store.now_ms()),
            )
        elif not row["user_data_dir"]:
            # Hàng do importer tạo từ file .accounts: chưa từng mở nên chưa có
            # thư mục thật. Cấp thư mục ngay lần mở đầu tiên.
            conn.execute("UPDATE profile SET user_data_dir = ? WHERE id = ?",
                         (str(user_data_dir), row["id"]))
        if make_default:
            conn.execute("UPDATE profile SET is_default = 0 WHERE is_default = 1 AND name != ?",
                         (name,))
            conn.execute("UPDATE profile SET is_default = 1 WHERE name = ?", (name,))
    return get_profile(name)


def get_profile(name: str) -> Profile | None:
    db = store.default()
    if db is None:
        return None
    rows = db.query("SELECT * FROM profile WHERE name = ?", (name,))
    return _row_to_profile(rows[0]) if rows else None


def list_profiles() -> list[dict]:
    db = store.default()
    if db is None:
        return []
    rows = db.query(
        "SELECT p.*, "
        " (SELECT COUNT(*) FROM account a WHERE a.profile_id = p.id AND a.disabled = 0) AS domains "
        "FROM profile p ORDER BY p.is_default DESC, p.name")
    out = []
    for row in rows:
        item = dict(row)
        item["locked"] = bool(row["lock_pid"]) and _pid_alive(int(row["lock_pid"]))
        # Panel Profile hiện thẳng danh sách domain đã đăng nhập trong mỗi
        # profile — đó là thứ làm "một profile nhiều domain" nhìn thấy được.
        item["accounts"] = accounts_of(int(row["id"]))
        out.append(item)
    return out


def acquire_lock(profile: Profile) -> None:
    """Giành quyền mở user_data_dir. Ném ProfileLocked nếu tiến trình khác giữ.

    Một user_data_dir chỉ được MỘT tiến trình Chromium mở. Không kiểm thì
    Chromium fail với thông báo khó hiểu, hoặc tệ hơn là làm hỏng profile.
    """
    db = store.default()
    if db is None:
        return
    conn = db.connection()
    row = conn.execute("SELECT lock_pid FROM profile WHERE id = ?", (profile.id,)).fetchone()
    holder = row["lock_pid"] if row else None
    mine = os.getpid()
    if holder and int(holder) != mine and _pid_alive(int(holder)):
        raise ProfileLocked(
            f"profile '{profile.name}' đang được tiến trình {holder} mở. "
            "Tắt tiến trình đó rồi thử lại.")
    with conn:
        conn.execute("UPDATE profile SET lock_pid = ?, lock_at = ? WHERE id = ?",
                     (mine, store.now_ms(), profile.id))


def release_lock(profile_id: int) -> None:
    db = store.default()
    if db is None:
        return
    # Chỉ nhả khoá của chính mình: tránh xoá khoá tiến trình khác vừa giành được.
    db.submit("UPDATE profile SET lock_pid = NULL, lock_at = NULL "
              "WHERE id = ? AND lock_pid = ?", (profile_id, os.getpid()))


def touch(profile_id: int) -> None:
    db = store.default()
    if db is None:
        return
    db.submit("UPDATE profile SET last_used_at = ? WHERE id = ?",
              (store.now_ms(), profile_id))


def pending_seeds(profile_id: int) -> list[tuple[int, Path]]:
    """[(account_id, storage_state_path)] chưa seed vào profile này.

    Chỉ trả về file còn tồn tại thật; hàng trỏ vào file đã bị xoá được coi như
    đã seed xong để không thử lại mãi.
    """
    db = store.default()
    if db is None:
        return []
    rows = db.query(
        "SELECT id, storage_state_path FROM account "
        "WHERE profile_id = ? AND storage_state_path IS NOT NULL AND storage_state_path != ''",
        (profile_id,))
    out = []
    for row in rows:
        path = Path(row["storage_state_path"])
        if path.is_file():
            out.append((int(row["id"]), path))
        else:
            clear_seed(int(row["id"]))
    return out


def clear_seed(account_id: int) -> None:
    """Đánh dấu đã seed xong: từ đây profile tự đứng, file JSON chỉ còn là backup."""
    db = store.default()
    if db is None:
        return
    db.submit("UPDATE account SET storage_state_path = NULL WHERE id = ?", (account_id,))


def profile_for_recipe(slug: str, default_name: str = DEFAULT_PROFILE) -> str:
    """Tên profile mà một recipe nên chạy trong.

    Ưu tiên profile được ghim ở `recipe.profile_id`; kế đến profile của account
    đầu tiên trên domain của recipe (đó là nơi đã có đăng nhập); cuối cùng là
    profile mặc định.
    """
    db = store.default()
    if db is None:
        return default_name
    rows = db.query(
        "SELECT p.name FROM recipe r JOIN profile p ON p.id = r.profile_id WHERE r.slug = ?",
        (slug,))
    if rows:
        return rows[0]["name"]
    rows = db.query(
        "SELECT p.name FROM recipe r "
        " JOIN account a ON a.domain_id = r.domain_id AND a.disabled = 0 "
        " JOIN profile p ON p.id = a.profile_id "
        "WHERE r.slug = ? ORDER BY a.id LIMIT 1", (slug,))
    if rows:
        return rows[0]["name"]
    rows = db.query("SELECT name FROM profile WHERE is_default = 1 LIMIT 1")
    return rows[0]["name"] if rows else default_name


# ----------------------------------------------------- CRUD cho trang Profile

# Cột người dùng được sửa từ UI. `name` và `user_data_dir` không nằm ở đây: đổi
# tên profile là đổi thư mục Chromium đang giữ toàn bộ đăng nhập, không phải
# thao tác một dropdown nên làm.
EDITABLE = ("engine", "headless", "max_tabs", "proxy", "user_agent",
            "locale", "timezone", "viewport", "notes")


class ProfileInUse(RuntimeError):
    """Còn recipe đang dựa vào profile này — xoá là mất đăng nhập đang chạy."""


def get_by_id(profile_id: int) -> dict | None:
    db = store.default()
    if db is None:
        return None
    rows = db.query("SELECT * FROM profile WHERE id = ?", (int(profile_id),))
    return dict(rows[0]) if rows else None


def find(ident: str) -> dict | None:
    """Tra profile theo id (chuỗi số) hoặc theo tên — UI dùng cả hai."""
    ident = str(ident).strip()
    if ident.isdigit():
        return get_by_id(int(ident))
    db = store.default()
    if db is None:
        return None
    rows = db.query("SELECT * FROM profile WHERE name = ?", (ident,))
    return dict(rows[0]) if rows else None


def accounts_of(profile_id: int) -> list[dict]:
    db = store.default()
    if db is None:
        return []
    rows = db.query(
        "SELECT a.id, a.label, a.status, a.disabled, d.host FROM account a "
        " JOIN domain d ON d.id = a.domain_id "
        "WHERE a.profile_id = ? ORDER BY d.host, a.label", (int(profile_id),))
    return [dict(row) for row in rows]


def blockers(profile_id: int) -> list[str]:
    """Recipe THẬT SỰ hỏng nếu xoá profile này. Đúng hai trường hợp:

    * recipe ghim thẳng `profile_id` — mất profile là mất chỗ chạy;
    * profile này giữ account CUỐI CÙNG còn bật của domain mà recipe dùng.

    Domain còn account ở profile khác thì recipe vẫn xoay vòng qua chúng và chạy
    bình thường, nên không được chặn. Trước đây chỉ cần "chung domain" là chặn,
    làm người dùng không xoá nổi profile thừa — một máy hay có 2-3 profile cùng
    đăng nhập một site, tình huống mà multi-account sinh ra để phục vụ.
    """
    db = store.default()
    if db is None:
        return []
    rows = db.query(
        "SELECT DISTINCT r.slug FROM recipe r WHERE r.profile_id = ? "
        "UNION "
        "SELECT DISTINCT r.slug FROM recipe r "
        " JOIN account a ON a.domain_id = r.domain_id "
        "WHERE a.profile_id = ? AND a.disabled = 0 "
        # Không còn account nào khác phục vụ domain đó: account rời (profile_id
        # NULL, seed từ storage_state) cũng tính là "khác".
        "  AND NOT EXISTS (SELECT 1 FROM account o WHERE o.domain_id = r.domain_id "
        "                    AND o.disabled = 0 "
        "                    AND (o.profile_id IS NULL OR o.profile_id <> ?))",
        (int(profile_id), int(profile_id), int(profile_id)))
    return sorted(row["slug"] for row in rows)


def _clean(values: dict) -> dict:
    """Lọc và ép kiểu các cột sửa được. Ném ValueError khi giá trị vô lý."""
    out: dict = {}
    for key in EDITABLE:
        if key not in values or values[key] is None:
            continue
        value = values[key]
        if key == "headless":
            out[key] = 1 if value in (True, 1, "1", "true", "True") else 0
        elif key == "max_tabs":
            tabs = int(value)
            if not 1 <= tabs <= 32:
                raise ValueError("max_tabs phải từ 1 đến 32")
            out[key] = tabs
        elif key == "engine":
            engine = str(value).strip().lower()
            if engine not in {"playwright", "cloak"}:
                raise ValueError("engine phải là playwright hoặc cloak")
            out[key] = engine
        elif key == "viewport":
            viewport = str(value).strip().lower()
            if not re.fullmatch(r"\d{3,5}x\d{3,5}", viewport):
                raise ValueError("viewport phải dạng 1280x800")
            out[key] = viewport
        elif key in ("proxy", "user_agent", "timezone"):
            text = str(value).strip()
            out[key] = text or None
        else:
            out[key] = str(value).strip()
    return out


def create(name: str, profiles_dir: Path, values: dict | None = None) -> dict:
    """Tạo profile mới + thư mục user_data_dir. Ném ValueError khi trùng tên."""
    if not valid_name(name):
        raise ValueError("tên profile chỉ gồm chữ thường, số và dấu -")
    db = store.default()
    if db is None:
        raise RuntimeError("kho dữ liệu chưa mở")
    conn = db.connection()
    if conn.execute("SELECT 1 FROM profile WHERE name = ?", (name,)).fetchone():
        raise ValueError(f"profile '{name}' đã tồn tại")
    clean = _clean(values or {})
    user_data_dir = Path(profiles_dir) / name
    user_data_dir.mkdir(parents=True, exist_ok=True)
    columns = ["name", "user_data_dir", "created_at", *clean]
    placeholders = ", ".join("?" * len(columns))
    with conn:
        conn.execute(
            f"INSERT INTO profile({', '.join(columns)}) VALUES ({placeholders})",
            (name, str(user_data_dir), store.now_ms(), *clean.values()))
        # Profile đầu tiên phải là mặc định, nếu không router không biết chạy ở đâu.
        conn.execute("UPDATE profile SET is_default = 1 WHERE name = ? AND NOT EXISTS"
                     " (SELECT 1 FROM profile WHERE is_default = 1)", (name,))
    return find(name)


def update(profile_id: int, values: dict) -> dict | None:
    row = get_by_id(profile_id)
    if row is None:
        return None
    clean = _clean(values)
    db = store.default()
    conn = db.connection()
    with conn:
        if clean:
            assignments = ", ".join(f"{key} = ?" for key in clean)
            conn.execute(f"UPDATE profile SET {assignments} WHERE id = ?",
                         (*clean.values(), int(profile_id)))
        if values.get("is_default"):
            conn.execute("UPDATE profile SET is_default = 0 WHERE is_default = 1")
            conn.execute("UPDATE profile SET is_default = 1 WHERE id = ?", (int(profile_id),))
    return get_by_id(profile_id)


def delete(profile_id: int, *, remove_dir: bool = False) -> bool:
    """Xoá profile (account của nó cascade theo). Ném ProfileInUse khi còn recipe dùng."""
    row = get_by_id(profile_id)
    if row is None:
        return False
    used = blockers(profile_id)
    if used:
        raise ProfileInUse(
            f"xoá profile '{row['name']}' sẽ làm hỏng recipe: {', '.join(used)} "
            "(recipe ghim profile này, hoặc đây là account cuối cùng của domain nó dùng)")
    if row["lock_pid"] and _pid_alive(int(row["lock_pid"])):
        raise ProfileLocked(
            f"profile '{row['name']}' đang mở ở tiến trình {row['lock_pid']}. Đóng nó trước.")
    db = store.default()
    conn = db.connection()
    with conn:
        conn.execute("DELETE FROM profile WHERE id = ?", (int(profile_id),))
    if remove_dir and row["user_data_dir"]:
        import shutil

        shutil.rmtree(row["user_data_dir"], ignore_errors=True)
    return True


def add_account(profile_id: int, host: str, label: str) -> dict | None:
    """Khai báo 'profile này đã đăng nhập host kia' — tạo domain nếu chưa có.

    Đây là đường của nút "thêm luôn" sau khi /detect thấy profile còn đăng nhập
    một domain chưa khai báo: không mở browser lại, chỉ ghi nhận quan hệ.
    """
    db = store.default()
    if db is None:
        return None
    conn = db.connection()
    now = store.now_ms()
    with conn:
        conn.execute("INSERT OR IGNORE INTO domain(host, created_at) VALUES (?, ?)", (host, now))
        domain_id = conn.execute("SELECT id FROM domain WHERE host = ?", (host,)).fetchone()["id"]
        conn.execute(
            "INSERT INTO account(profile_id, domain_id, label, created_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(profile_id, domain_id, label) DO UPDATE SET disabled = 0",
            (int(profile_id), domain_id, label, now))
        row = conn.execute(
            "SELECT a.id, a.label, d.host FROM account a JOIN domain d ON d.id = a.domain_id"
            " WHERE a.profile_id = ? AND a.domain_id = ? AND a.label = ?",
            (int(profile_id), domain_id, label)).fetchone()
    return dict(row) if row else None


def add_account_with_state(profile_id: int, host: str, label: str,
                           storage_state_path: str) -> dict | None:
    """Như `add_account`, nhưng kèm sẵn `storage_state_path` để lần mở đầu
    profile tự seed cookie từ đó (§3.4). Dùng khi tích hợp mới lưu login thẳng
    vào profile người dùng đã chọn, thay vì để nó trôi vào recipe rồi tới lúc
    restart mới bị `importer` gom vào một profile tự sinh.
    """
    db = store.default()
    if db is None:
        return None
    conn = db.connection()
    now = store.now_ms()
    with conn:
        conn.execute("INSERT OR IGNORE INTO domain(host, created_at) VALUES (?, ?)", (host, now))
        domain_id = conn.execute("SELECT id FROM domain WHERE host = ?", (host,)).fetchone()["id"]
        conn.execute(
            "INSERT INTO account(profile_id, domain_id, label, storage_state_path, created_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(profile_id, domain_id, label)"
            " DO UPDATE SET storage_state_path = excluded.storage_state_path, disabled = 0",
            (int(profile_id), domain_id, label, storage_state_path, now))
        row = conn.execute(
            "SELECT a.id, a.label, d.host FROM account a JOIN domain d ON d.id = a.domain_id"
            " WHERE a.profile_id = ? AND a.domain_id = ? AND a.label = ?",
            (int(profile_id), domain_id, label)).fetchone()
    return dict(row) if row else None


def known_hosts() -> list[str]:
    """Mọi domain DB từng thấy — nguồn cho dropdown gợi ý ở dialog thêm account."""
    db = store.default()
    if db is None:
        return []
    return [row["host"] for row in db.query("SELECT host FROM domain ORDER BY host")]
