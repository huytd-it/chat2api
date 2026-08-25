import time
from collections import deque

from . import store

# Nhật ký toàn app (không phải log per-job của Integrate) — cho tab "Logs" trên
# desktop app xem hoạt động server: request, lỗi, login, recipe reload/delete...
#
# Hai tầng, có chủ đích:
#   * ring buffer trong RAM  -> `since(cursor)`, đường poll nóng của desktop.
#     `id` tăng dần để client lấy phần mới thay vì tải lại toàn bộ.
#   * bảng `app_log` trong DB -> `history()`, sống sót qua restart và lọc được.
# DB chưa mở (CLI, test đơn vị) thì tầng RAM vẫn chạy y như trước.
_MAX_ENTRIES = 500
_entries: deque[dict] = deque(maxlen=_MAX_ENTRIES)
_next_id = 0

# Message theo quy ước "<nguồn>: <nội dung>". Rút tiền tố ra cột `source` để
# trang Logs lọc được, thay vì bắt mọi lời gọi log() phải thêm tham số.
_SOURCES = {"chat", "integrate", "account", "recipe", "browser", "settings",
            "login", "job", "pool", "store"}
_LEVELS = {"info", "warn", "error"}


def _source_of(message: str) -> str:
    head, sep, _ = message.partition(":")
    return head if sep and head in _SOURCES else "app"


def log(message: str, level: str = "info") -> None:
    global _next_id
    _next_id += 1
    ts = time.time()
    _entries.append({"id": _next_id, "ts": ts, "level": level, "message": message})
    db = store.default()
    if db is not None:
        db.submit(
            "INSERT INTO app_log(ts, level, source, message) VALUES (?, ?, ?, ?)",
            (int(ts * 1000), level, _source_of(message), message))


def since(cursor: int = 0, limit: int = 200) -> list[dict]:
    out = [e for e in _entries if e["id"] > cursor]
    return out[-limit:]


def history(level: str = "", source: str = "", search: str = "",
            before: int = 0, limit: int = 200) -> list[dict]:
    """Đọc log đã lưu trong DB, mới nhất trước. `before` là `id` để phân trang.

    Trả list rỗng khi chưa mở DB — người gọi không cần biết kho có sẵn hay không.
    """
    db = store.default()
    if db is None:
        return []
    where = []
    params: list = []
    if level in _LEVELS:
        where.append("level = ?")
        params.append(level)
    if source:
        where.append("source = ?")
        params.append(source)
    if search:
        where.append("message LIKE ? ESCAPE '\\'")
        params.append("%" + search.replace("\\", "\\\\").replace("%", "\\%")
                      .replace("_", "\\_") + "%")
    if before > 0:
        where.append("id < ?")
        params.append(before)
    sql = "SELECT id, ts, level, source, message FROM app_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 1000)))
    rows = db.query(sql, tuple(params))
    return [{"id": r["id"], "ts": r["ts"] / 1000, "level": r["level"],
             "source": r["source"], "message": r["message"]} for r in rows]
