"""Phát hiện limit theo từng site/recipe + cooldown tạm trong SQLite.

Quy ước đã chốt:

- Cấu hình nằm trong ``response`` (phẳng hoặc từng flow):
  ``limit_patterns`` (list regex), ``limit_cooldown_hours`` (mặc định 24),
  ``limit_on_missing_copy`` (mặc định False).
- ``limit_patterns=[]`` (hoặc vắng mặt) = tắt phát hiện.
- Regex sai báo lỗi lúc lưu (validate), runtime compile case-insensitive.
- Khóa tạm lưu ở bảng ``account_cooldown(recipe_slug, account_key, ...)`` —
  bền qua restart, khác hẳn ``account.disabled``.
- ``account_key`` chuẩn hoá chung mọi đường assign:
  ``db:<id>`` cho account DB, ``file:<domain>/<name>`` cho kho file,
  ``__anon__`` không bao giờ bị khóa.
- Ghi qua writer fire-and-forget + mirror in-memory để retry trong cùng
  request thấy ngay (writer async, chưa flush).
"""

from __future__ import annotations

import re
import threading

DEFAULT_COOLDOWN_HOURS = 24

# Mirror in-memory: (recipe_slug, account_key) -> until_ms. Ghi trước khi
# submit xuống writer để retry cùng request không phải chờ flush.
_memory: dict[tuple[str, str], int] = {}
_memory_lock = threading.Lock()


def anon_key() -> str:
    return "__anon__"


def db_key(account_id: int) -> str:
    return f"db:{int(account_id)}"


def file_key(domain: str, name: str) -> str:
    return f"file:{(domain or '').lower()}/{name}"


def is_anon_key(key: str) -> bool:
    return not key or key == "__anon__"


def normalize_patterns(raw) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("limit_patterns phải là list regex")
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("limit_patterns: mỗi pattern phải là string không rỗng")
        out.append(item)
    return out


def compile_patterns(patterns: list[str]) -> list[re.Pattern]:
    out: list[re.Pattern] = []
    for raw in patterns:
        try:
            out.append(re.compile(raw, re.IGNORECASE | re.DOTALL))
        except re.error as error:
            raise ValueError(f"limit_patterns regex lỗi '{raw}': {error}")
    return out


def validate_limit_fields(resp: dict, label: str) -> list[str]:
    """Validate 3 khóa limit trong một khối ``response``. ``label`` để báo lỗi."""
    errs: list[str] = []
    if not isinstance(resp, dict):
        return errs
    raw_patterns = resp.get("limit_patterns")
    if raw_patterns is None:
        patterns: list[str] = []
    elif not isinstance(raw_patterns, list):
        errs.append(f"invalid field: {label}.limit_patterns (phải là list regex)")
        patterns = []
    else:
        try:
            patterns = normalize_patterns(raw_patterns)
        except ValueError as error:
            errs.append(f"invalid field: {label}.limit_patterns ({error})")
            patterns = []
        else:
            for raw in patterns:
                try:
                    re.compile(raw, re.IGNORECASE | re.DOTALL)
                except re.error as error:
                    errs.append(f"invalid field: {label}.limit_patterns regex lỗi '{raw}': {error}")
    hours = resp.get("limit_cooldown_hours")
    if hours is not None and (
        not isinstance(hours, (int, float)) or isinstance(hours, bool) or float(hours) <= 0
    ):
        errs.append(f"invalid field: {label}.limit_cooldown_hours (số > 0, đơn vị giờ)")
    flag = resp.get("limit_on_missing_copy")
    if flag is not None and not isinstance(flag, bool):
        errs.append(f"invalid field: {label}.limit_on_missing_copy (boolean)")
    return errs


def limit_config(resp: dict | None) -> dict:
    """Chuẩn hoá cấu hình limit của một khối response (không ném lỗi)."""
    resp = resp if isinstance(resp, dict) else {}
    try:
        patterns = normalize_patterns(resp.get("limit_patterns"))
    except ValueError:
        patterns = []
    try:
        compiled = compile_patterns(patterns)
    except ValueError:
        compiled = []
    hours = resp.get("limit_cooldown_hours")
    if not isinstance(hours, (int, float)) or isinstance(hours, bool) or float(hours) <= 0:
        hours = DEFAULT_COOLDOWN_HOURS
    return {
        "patterns": patterns,
        "compiled": compiled,
        "cooldown_hours": float(hours),
        "on_missing_copy": bool(resp.get("limit_on_missing_copy", False)),
    }


def match_limit(text: str, compiled: list[re.Pattern]) -> str | None:
    """Text khớp pattern limit nào → trả đoạn khớp (cắt 200 ký tự), không thì None."""
    if not text or not compiled:
        return None
    for rx in compiled:
        try:
            found = rx.search(text)
        except Exception:
            continue
        if found:
            try:
                snippet = found.group(0)
            except Exception:
                snippet = text
            snippet = " ".join(str(snippet or "").split())
            return snippet[:200] if snippet else text[:200]
    return None


def cooldown_hours_of(resp: dict | None) -> float:
    return float(limit_config(resp)["cooldown_hours"])


def _now_ms() -> int:
    from .store import now_ms

    return now_ms()


def _prune_memory(now: int) -> None:
    expired = [k for k, until in _memory.items() if until <= now]
    for key in expired:
        _memory.pop(key, None)


def is_cooled_down(recipe_slug: str, account_key: str, now: int = 0) -> tuple[bool, int, str]:
    """True + (until_ms, reason) nếu key đang bị khóa cho recipe này.

    Đọc mirror trước (thấy ngay trong cùng request), rồi mới xuống DB.
    Hết hạn thì lazy-expire (xóa dòng DB fire-and-forget).
    """
    if is_anon_key(account_key) or not recipe_slug:
        return False, 0, ""
    now = now or _now_ms()
    with _memory_lock:
        _prune_memory(now)
        until = _memory.get((recipe_slug, account_key), 0)
    if until and until > now:
        return True, until, ""
    from . import store as store_mod

    db = store_mod.default()
    if db is None:
        return False, 0, ""
    try:
        rows = db.query(
            "SELECT until_ms, reason FROM account_cooldown WHERE recipe_slug = ? AND account_key = ?",
            (recipe_slug, account_key),
        )
    except Exception:
        return False, 0, ""
    if not rows:
        return False, 0, ""
    until_ms = int(rows[0]["until_ms"] or 0)
    reason = str(rows[0]["reason"] or "")
    if until_ms <= now:
        db.submit(
            "DELETE FROM account_cooldown WHERE recipe_slug = ? AND account_key = ?",
            (recipe_slug, account_key),
        )
        with _memory_lock:
            _memory.pop((recipe_slug, account_key), None)
        return False, 0, ""
    with _memory_lock:
        _memory[(recipe_slug, account_key)] = until_ms
    return True, until_ms, reason


def mark_cooldown(
    recipe_slug: str,
    account_key: str,
    cooldown_hours: float = DEFAULT_COOLDOWN_HOURS,
    reason: str = "",
) -> int:
    """Ghi cooldown, trả về until_ms. Anon không khóa (trả 0)."""
    if is_anon_key(account_key) or not recipe_slug:
        return 0
    try:
        hours = float(cooldown_hours)
    except (TypeError, ValueError):
        hours = float(DEFAULT_COOLDOWN_HOURS)
    if hours <= 0:
        hours = float(DEFAULT_COOLDOWN_HOURS)
    now = _now_ms()
    until_ms = now + int(hours * 3600 * 1000)
    with _memory_lock:
        prev = _memory.get((recipe_slug, account_key), 0)
        _memory[(recipe_slug, account_key)] = max(prev, until_ms)
    from . import store as store_mod

    db = store_mod.default()
    if db is not None:
        db.submit(
            "INSERT INTO account_cooldown(recipe_slug, account_key, until_ms, reason, updated_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(recipe_slug, account_key) DO UPDATE SET"
            "   until_ms = MAX(account_cooldown.until_ms, excluded.until_ms),"
            "   reason = excluded.reason, updated_at = excluded.updated_at",
            (recipe_slug, account_key, until_ms, str(reason or "")[:500], now),
        )
    return until_ms


def clear_cooldown(recipe_slug: str, account_key: str) -> None:
    with _memory_lock:
        _memory.pop((recipe_slug, account_key), None)
    from . import store as store_mod

    db = store_mod.default()
    if db is not None:
        db.submit(
            "DELETE FROM account_cooldown WHERE recipe_slug = ? AND account_key = ?",
            (recipe_slug, account_key),
        )


def list_cooldowns(recipe_slug: str = "") -> list[dict]:
    """Liệt kê cooldown còn hạn (lazy-expire những dòng đã hết)."""
    from . import store as store_mod

    db = store_mod.default()
    if db is None:
        return []
    now = _now_ms()
    with _memory_lock:
        _prune_memory(now)
    try:
        if recipe_slug:
            rows = db.query(
                "SELECT recipe_slug, account_key, until_ms, reason, updated_at"
                " FROM account_cooldown WHERE recipe_slug = ? ORDER BY until_ms DESC",
                (recipe_slug,),
            )
        else:
            rows = db.query(
                "SELECT recipe_slug, account_key, until_ms, reason, updated_at"
                " FROM account_cooldown ORDER BY until_ms DESC",
            )
    except Exception:
        return []
    out: list[dict] = []
    for row in rows:
        until_ms = int(row["until_ms"] or 0)
        if until_ms <= now:
            continue
        out.append(
            {
                "recipe_slug": str(row["recipe_slug"]),
                "account_key": str(row["account_key"]),
                "until_ms": until_ms,
                "retry_after": max(0, (until_ms - now) // 1000),
                "reason": str(row["reason"] or ""),
                "updated_at": row["updated_at"],
            }
        )
    return out


def reset_memory() -> None:
    """Xóa mirror in-memory (chỉ dùng trong test)."""
    with _memory_lock:
        _memory.clear()
