"""API key nằm trong bảng `api_key` (docs/design-v2.md §2, pha 6).

Thay cho `CHAT2API_KEYS` dạng CSV: mỗi key có nhãn, có scope, thu hồi được từng
cái, và `request_log.api_key_id` truy ngược được ai đã gọi.

DB chỉ giữ **sha256 của key thô** — không có đường nào lấy lại key sau khi tạo,
đúng như mọi nhà cung cấp API khác. `key_prefix` (8 ký tự đầu) là thứ duy nhất
hiện ra để người dùng nhận diện hàng nào là hàng nào.

`CHAT2API_KEYS` vẫn được chấp nhận song song: đó là đường bootstrap cho CI và
cho lần chạy đầu khi chưa có DB, cùng lý do với `.env` thắng bảng `setting`.

Xác thực nằm trên đường nóng của **mọi** request, mà SQLite thì blocking. Nên
tập key đang hoạt động được cache trong RAM (`_cache`), nạp một lần qua
`asyncio.to_thread` rồi xoá cache mỗi khi tạo/thu hồi. Sau lần nạp đầu, kiểm tra
một key chỉ là tra dict — không chạm đĩa, không nhảy thread.
"""

from __future__ import annotations

import hashlib
import secrets
import threading

from . import store

PREFIX = "c2a-"
ALL_SCOPES = ("chat", "admin")
DEFAULT_SCOPES = "chat,admin"
# Nhịp tối thiểu giữa hai lần ghi `last_used_at` của cùng một key. Không có nó,
# mỗi request chat lại xếp thêm một lệnh UPDATE vào hàng đợi ghi để lưu một con
# số không ai đọc theo giây.
_TOUCH_INTERVAL_MS = 60_000

_lock = threading.Lock()
_cache: dict[str, dict] | None = None
_touched: dict[int, int] = {}


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new_key() -> str:
    return PREFIX + secrets.token_urlsafe(32)


def clean_scopes(value: str | None) -> str:
    """Lọc scope lạ, giữ thứ tự khai báo. Rỗng ⇒ mặc định."""
    wanted = {s.strip().lower() for s in (value or "").split(",") if s.strip()}
    kept = [s for s in ALL_SCOPES if s in wanted]
    return ",".join(kept) if kept else DEFAULT_SCOPES


def invalidate() -> None:
    """Bỏ cache. Gọi sau mọi thay đổi bảng `api_key`."""
    global _cache
    with _lock:
        _cache = None


def _load() -> dict[str, dict]:
    db = store.default()
    if db is None:
        return {}
    try:
        rows = db.query("SELECT id, label, key_hash, scopes FROM api_key WHERE revoked_at IS NULL")
    except Exception:
        return {}
    return {row["key_hash"]: {"id": int(row["id"]), "label": row["label"],
                              "scopes": row["scopes"].split(",")} for row in rows}


def cached() -> dict[str, dict] | None:
    """Tập key đang hoạt động nếu đã nạp, None nếu chưa — không bao giờ chạm đĩa."""
    return _cache


def active() -> dict[str, dict]:
    """Tập key đang hoạt động, nạp từ DB lần đầu. Blocking."""
    global _cache
    if _cache is None:
        loaded = _load()
        with _lock:
            _cache = loaded
    return _cache


def match(raw: str) -> dict | None:
    """Key thô -> hàng api_key đang hoạt động. None khi không khớp."""
    entry = active().get(hash_key(raw))
    if entry is not None:
        touch(entry["id"])
    return entry


def touch(key_id: int) -> None:
    """Ghi nhận vừa dùng. Bắn-rồi-quên và có tiết chế — không chặn request."""
    now = store.now_ms()
    last = _touched.get(key_id, 0)
    if now - last < _TOUCH_INTERVAL_MS:
        return
    _touched[key_id] = now
    db = store.default()
    if db is not None:
        db.submit("UPDATE api_key SET last_used_at = ? WHERE id = ?", (now, key_id))


def create(label: str, scopes: str | None = None) -> dict:
    """Tạo key mới. Chỉ lần này trả về key thô ở khoá `key`.

    Ném RuntimeError khi kho chưa mở: không có DB thì key vừa tạo sẽ bốc hơi
    lúc restart, thà báo lỗi còn hơn đưa cho người dùng một key chết.
    """
    label = (label or "").strip()
    if not label:
        raise ValueError("api key phải có nhãn")
    db = store.default()
    if db is None:
        raise RuntimeError("kho dữ liệu chưa mở")
    raw = _new_key()
    conn = db.connection()
    with conn:
        cursor = conn.execute(
            "INSERT INTO api_key(label, key_hash, key_prefix, scopes, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (label, hash_key(raw), raw[:8], clean_scopes(scopes), store.now_ms()))
        row = conn.execute("SELECT * FROM api_key WHERE id = ?", (cursor.lastrowid,)).fetchone()
    invalidate()
    return {**_public(row), "key": raw}


def list_keys() -> list[dict]:
    db = store.default()
    if db is None:
        return []
    rows = db.query("SELECT * FROM api_key ORDER BY revoked_at IS NOT NULL, id DESC")
    return [_public(row) for row in rows]


def revoke(key_id: int) -> dict | None:
    """Đánh dấu thu hồi nhưng giữ hàng lại: `request_log.api_key_id` còn trỏ vào nó."""
    db = store.default()
    if db is None:
        return None
    conn = db.connection()
    with conn:
        row = conn.execute("SELECT * FROM api_key WHERE id = ?", (int(key_id),)).fetchone()
        if row is None:
            return None
        if row["revoked_at"] is None:
            conn.execute("UPDATE api_key SET revoked_at = ? WHERE id = ?",
                         (store.now_ms(), int(key_id)))
        row = conn.execute("SELECT * FROM api_key WHERE id = ?", (int(key_id),)).fetchone()
    invalidate()
    return _public(row)


def delete(key_id: int) -> bool:
    """Xoá hẳn hàng. `request_log.api_key_id` của nó thành NULL (ON DELETE SET NULL)."""
    db = store.default()
    if db is None:
        return False
    conn = db.connection()
    with conn:
        cursor = conn.execute("DELETE FROM api_key WHERE id = ?", (int(key_id),))
        removed = cursor.rowcount > 0
    invalidate()
    return removed


def _public(row) -> dict:
    """Hàng api_key đưa ra ngoài — không bao giờ kèm `key_hash`."""
    return {
        "id": int(row["id"]), "label": row["label"], "key_prefix": row["key_prefix"],
        "scopes": row["scopes"].split(","), "created_at": row["created_at"],
        "last_used_at": row["last_used_at"], "revoked_at": row["revoked_at"],
    }
