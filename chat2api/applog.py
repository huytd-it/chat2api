import time
from collections import deque

# Ring buffer nhật ký toàn app (không phải log per-job của Integrate) — cho
# tab "Logs" trên desktop app xem hoạt động server: request, lỗi, login,
# recipe reload/delete... `id` tăng dần để client poll theo cursor thay vì
# tải lại toàn bộ mỗi lần.
_MAX_ENTRIES = 500
_entries: deque[dict] = deque(maxlen=_MAX_ENTRIES)
_next_id = 0


def log(message: str, level: str = "info") -> None:
    global _next_id
    _next_id += 1
    _entries.append({"id": _next_id, "ts": time.time(), "level": level, "message": message})


def since(cursor: int = 0, limit: int = 200) -> list[dict]:
    out = [e for e in _entries if e["id"] > cursor]
    return out[-limit:]
