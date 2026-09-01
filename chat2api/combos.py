"""Combo — model ảo là sự kết hợp nhiều model thật với chiến lược xoay vòng.

Mỗi combo có slug là phần sau "combo/<slug>" và trỏ tới nhiều member
public_id (ví dụ "qwen-web/qwen-web"). Router coi "combo" như một provider
ảo, còn việc chọn member được giao cho ComboProvider theo strategy.

Bảng DB: combo + combo_member (xem store/schema.sql và migrations/0003).
Module này chỉ lo CRUD đồng bộ (SQLite blocking) — handler async phải gọi
qua asyncio.to_thread.
"""

from __future__ import annotations

import re
import sqlite3

from . import store

SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}$")
STRATEGIES = {"round_robin", "random", "failover", "sticky_session", "weighted"}
# alias cho UI
STRATEGY_LABELS = {
    "round_robin": "Xoay vòng đều",
    "random": "Ngẫu nhiên",
    "failover": "Dự phòng (failover)",
    "sticky_session": "Bám session",
    "weighted": "Theo trọng số",
}


def valid_slug(slug: str) -> bool:
    return bool(slug) and SLUG_RE.fullmatch(slug) is not None


def _row_to_combo(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "slug": row["slug"],
        "display_name": row["display_name"] or "",
        "strategy": row["strategy"],
        "description": row["description"] or "",
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_combos(with_members: bool = True) -> list[dict]:
    db = store.default()
    if db is None:
        return []
    rows = db.query("SELECT * FROM combo ORDER BY slug")
    combos = [_row_to_combo(r) for r in rows]
    if with_members and combos:
        ids = [c["id"] for c in combos]
        placeholders = ",".join("?" * len(ids))
        mrows = db.query(
            f"SELECT combo_id, model_id, weight, priority FROM combo_member "
            f"WHERE combo_id IN ({placeholders}) ORDER BY priority, model_id",
            tuple(ids),
        )
        members_by_id: dict[int, list[dict]] = {cid: [] for cid in ids}
        for m in mrows:
            members_by_id[int(m["combo_id"])].append(
                {"model_id": m["model_id"], "weight": int(m["weight"]), "priority": int(m["priority"])}
            )
        for c in combos:
            c["members"] = members_by_id.get(c["id"], [])
            c["model_id"] = f"combo/{c['slug']}"
    else:
        for c in combos:
            c["members"] = []
            c["model_id"] = f"combo/{c['slug']}"
    return combos


def get_combo(slug_or_id: str | int) -> dict | None:
    db = store.default()
    if db is None:
        return None
    if isinstance(slug_or_id, int) or (isinstance(slug_or_id, str) and slug_or_id.isdigit()):
        rows = db.query("SELECT * FROM combo WHERE id = ?", (int(slug_or_id),))
    else:
        rows = db.query("SELECT * FROM combo WHERE slug = ?", (str(slug_or_id).strip(),))
    if not rows:
        return None
    combo = _row_to_combo(rows[0])
    mrows = db.query(
        "SELECT model_id, weight, priority FROM combo_member WHERE combo_id = ? ORDER BY priority, model_id",
        (combo["id"],),
    )
    combo["members"] = [
        {"model_id": r["model_id"], "weight": int(r["weight"]), "priority": int(r["priority"])} for r in mrows
    ]
    combo["model_id"] = f"combo/{combo['slug']}"
    return combo


def _validate_members(members: list[dict]) -> tuple[list[dict], list[str]]:
    """Chuẩn hoá members, trả (clean, errors)."""
    if not isinstance(members, list) or not members:
        return [], ["combo cần ít nhất 1 member model"]
    clean: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    for idx, m in enumerate(members):
        if not isinstance(m, dict):
            errors.append(f"members[{idx}] phải là object")
            continue
        model_id = str(m.get("model_id") or m.get("id") or "").strip()
        if not model_id or "/" not in model_id:
            errors.append(f"members[{idx}].model_id phải dạng 'slug/model' (vd 'qwen-web/qwen-web')")
            continue
        if model_id in seen:
            errors.append(f"members[{idx}].model_id trùng: {model_id}")
            continue
        seen.add(model_id)
        try:
            weight = int(m.get("weight", 1))
        except Exception:
            errors.append(f"members[{idx}].weight phải là số nguyên 1..100")
            continue
        if not 1 <= weight <= 100:
            errors.append(f"members[{idx}].weight phải 1..100")
            continue
        try:
            priority = int(m.get("priority", idx))
        except Exception:
            priority = idx
        clean.append({"model_id": model_id, "weight": weight, "priority": priority})
    # sort by priority then model_id for deterministic order
    clean.sort(key=lambda x: (x["priority"], x["model_id"]))
    # reassign priority 0..n-1 to keep order tight
    for i, c in enumerate(clean):
        c["priority"] = i
    return clean, errors


def validate_combo(data: dict, is_update: bool = False) -> tuple[dict, list[str]]:
    """Kiểm payload tạo/sửa combo. Trả (clean, errors)."""
    errors: list[str] = []
    clean: dict = {}
    slug = str(data.get("slug") or "").strip().lower()
    if not is_update or "slug" in data:
        if not valid_slug(slug):
            errors.append("slug chỉ gồm chữ thường, số, dấu - (vd 'my-combo')")
        elif slug in {"gemini", "openai", "combo"}:
            errors.append("slug trùng tên hệ thống")
        else:
            clean["slug"] = slug
    if "display_name" in data:
        clean["display_name"] = str(data.get("display_name") or "").strip()[:120]
    elif not is_update:
        clean["display_name"] = str(data.get("display_name") or "").strip()[:120]
    if "strategy" in data:
        strategy = str(data.get("strategy") or "").strip().lower()
        if strategy not in STRATEGIES:
            errors.append(f"strategy phải là {' | '.join(sorted(STRATEGIES))}")
        else:
            clean["strategy"] = strategy
    elif not is_update:
        clean["strategy"] = "round_robin"
    if "description" in data:
        clean["description"] = str(data.get("description") or "").strip()[:500]
    elif not is_update:
        clean["description"] = ""
    if "enabled" in data:
        val = data.get("enabled")
        clean["enabled"] = 1 if val in (True, 1, "1", "true", "True") else 0
    elif not is_update:
        clean["enabled"] = 1
    if "members" in data:
        members, m_errors = _validate_members(data.get("members") or [])
        errors.extend(m_errors)
        clean["members"] = members
    elif not is_update:
        errors.append("members không được rỗng")
    return clean, errors


def create_combo(data: dict) -> dict:
    clean, errors = validate_combo(data, is_update=False)
    if errors:
        raise ValueError("; ".join(errors))
    db = store.default()
    if db is None:
        raise RuntimeError("kho dữ liệu chưa mở")
    conn = db.connection()
    now = store.now_ms()
    existing = conn.execute("SELECT 1 FROM combo WHERE slug = ?", (clean["slug"],)).fetchone()
    if existing:
        raise ValueError(f"combo '{clean['slug']}' đã tồn tại")
    with conn:
        conn.execute(
            "INSERT INTO combo(slug, display_name, strategy, description, enabled, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (clean["slug"], clean.get("display_name", ""), clean.get("strategy", "round_robin"),
             clean.get("description", ""), clean.get("enabled", 1), now, now),
        )
        row = conn.execute("SELECT id FROM combo WHERE slug = ?", (clean["slug"],)).fetchone()
        combo_id = int(row["id"])
        for m in clean.get("members", []):
            conn.execute(
                "INSERT INTO combo_member(combo_id, model_id, weight, priority) VALUES (?, ?, ?, ?)",
                (combo_id, m["model_id"], m["weight"], m["priority"]),
            )
    return get_combo(clean["slug"])  # type: ignore


def update_combo(slug: str, data: dict) -> dict | None:
    slug = str(slug).strip().lower()
    existing = get_combo(slug)
    if existing is None:
        return None
    # allow renaming via new slug in payload? we handle separately via rename endpoint, not here
    clean, errors = validate_combo(data, is_update=True)
    if errors:
        raise ValueError("; ".join(errors))
    db = store.default()
    if db is None:
        raise RuntimeError("kho dữ liệu chưa mở")
    conn = db.connection()
    now = store.now_ms()
    # handle slug change if requested
    new_slug = clean.get("slug")
    if new_slug and new_slug != slug:
        if conn.execute("SELECT 1 FROM combo WHERE slug = ?", (new_slug,)).fetchone():
            raise ValueError(f"combo '{new_slug}' đã tồn tại")
    fields: dict = {}
    for k in ("display_name", "strategy", "description", "enabled"):
        if k in clean:
            fields[k] = clean[k]
    if new_slug:
        fields["slug"] = new_slug
    with conn:
        if fields:
            assignments = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE combo SET {assignments}, updated_at = ? WHERE id = ?",
                (*fields.values(), now, existing["id"]),
            )
        if "members" in clean:
            conn.execute("DELETE FROM combo_member WHERE combo_id = ?", (existing["id"],))
            for m in clean["members"]:
                conn.execute(
                    "INSERT INTO combo_member(combo_id, model_id, weight, priority) VALUES (?, ?, ?, ?)",
                    (existing["id"], m["model_id"], m["weight"], m["priority"]),
                )
    target_slug = new_slug or slug
    return get_combo(target_slug)


def delete_combo(slug: str) -> bool:
    slug = str(slug).strip().lower()
    db = store.default()
    if db is None:
        return False
    conn = db.connection()
    row = conn.execute("SELECT id FROM combo WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        return False
    with conn:
        conn.execute("DELETE FROM combo WHERE id = ?", (int(row["id"]),))
    return True


def delete_combos_by_member(model_id: str) -> int:
    """Xoá member khỏi mọi combo khi model gốc bị xoá (tuỳ chọn)."""
    db = store.default()
    if db is None:
        return 0
    conn = db.connection()
    with conn:
        cur = conn.execute("DELETE FROM combo_member WHERE model_id = ?", (model_id,))
        return cur.rowcount
