"""OpenAI providers (pass-through) lưu trong DB, không lưu trong recipes/.

Trước đây mỗi provider là một file `recipes/openai/<slug>.yaml`. Từ schema v8,
bảng `openai_provider` + `openai_provider_model` là nguồn sự thật duy nhất khi
kho đang mở; file YAML chỉ còn để migrate một lần lúc khởi động.

Module này chỉ lo CRUD đồng bộ (SQLite blocking) — handler async phải gọi qua
`asyncio.to_thread`, giống `combos.py`.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

from . import store

SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}$")
RESERVED = {"gemini", "openai", "combo"}
CAPABILITIES = {"chat", "image", "both"}
MODEL_ID_RE = re.compile(r"[A-Za-z0-9._-]+$")


def valid_slug(slug: str) -> bool:
    return bool(slug) and SLUG_RE.fullmatch(slug) is not None


def validate(data: dict, is_update: bool = False) -> tuple[dict, list[str]]:
    """Kiểm payload tạo/sửa provider. Trả (clean, errors)."""
    errs: list[str] = []
    clean: dict = {}
    if not is_update or "slug" in data:
        slug = str(data.get("slug") or "").strip().lower()
        if not valid_slug(slug) or slug in RESERVED:
            errs.append("Slug chỉ gồm chữ thường, số và dấu -, không trùng tên hệ thống")
        else:
            clean["slug"] = slug
    if "base_url" in data or not is_update:
        base_url = str(data.get("base_url") or "").strip()
        if not base_url:
            errs.append("base_url không được rỗng")
        else:
            parsed = urlparse(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errs.append("base_url phải là http/https URL hợp lệ")
            else:
                clean["base_url"] = base_url.rstrip("/")
    if "api_key" in data and data.get("api_key") is not None:
        clean["api_key"] = str(data.get("api_key") or "").strip()
    if "api_key_env" in data and data.get("api_key_env") is not None:
        clean["api_key_env"] = str(data.get("api_key_env") or "").strip()
    if "models" in data or not is_update:
        models = data.get("models")
        if not isinstance(models, list) or not models:
            errs.append("models phải là danh sách không rỗng")
        else:
            clean_models: list[dict] = []
            seen: set[str] = set()
            for idx, m in enumerate(models):
                if isinstance(m, str):
                    mid = m.strip()
                    cap = "chat"
                elif isinstance(m, dict):
                    mid = str(m.get("id") or m.get("model_id") or "").strip()
                    cap = str(m.get("capability") or "chat").strip().lower()
                    if cap not in CAPABILITIES:
                        cap = "chat"
                else:
                    errs.append(f"models[{idx}] không hợp lệ")
                    continue
                if not mid:
                    errs.append(f"models[{idx}].id không được rỗng")
                    continue
                if not MODEL_ID_RE.fullmatch(mid):
                    errs.append(f"models[{idx}].id chỉ gồm chữ, số, ., _, -")
                    continue
                if mid in seen:
                    errs.append(f"models[{idx}].id trùng: {mid}")
                    continue
                seen.add(mid)
                clean_models.append({"id": mid, "capability": cap})
            if not errs:
                clean["models"] = clean_models
    if "stream" in data:
        clean["stream"] = data.get("stream")
    elif not is_update:
        clean["stream"] = True
    if "enabled" in data:
        val = data.get("enabled")
        clean["enabled"] = 0 if val in (False, 0, "0", "false", "False") else 1
    return clean, errs


def _row_to_provider(row: sqlite3.Row, models: list[dict] | None = None) -> dict:
    return {
        "id": row["id"],
        "slug": row["slug"],
        "base_url": row["base_url"] or "",
        "has_key": bool(row["api_key"] or row["api_key_env"]),
        "api_key_env": row["api_key_env"] or "",
        "models": models if models is not None else [],
        "stream": bool(row["stream"]),
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _load_models(db: store.Store, provider_ids: list[int]) -> dict[int, list[dict]]:
    if not provider_ids:
        return {}
    placeholders = ",".join("?" * len(provider_ids))
    rows = db.query(
        f"SELECT provider_id, model_id, capability FROM openai_provider_model "
        f"WHERE provider_id IN ({placeholders}) ORDER BY priority, model_id",
        tuple(provider_ids),
    )
    out: dict[int, list[dict]] = {pid: [] for pid in provider_ids}
    for r in rows:
        out[int(r["provider_id"])].append(
            {"id": r["model_id"], "capability": r["capability"] or "chat"})
    return out


def list_providers() -> list[dict]:
    db = store.default()
    if db is None:
        return []
    rows = db.query("SELECT * FROM openai_provider ORDER BY slug")
    by_id = _load_models(db, [int(r["id"]) for r in rows])
    return [_row_to_provider(r, by_id.get(int(r["id"]), [])) for r in rows]


def list_configs() -> list[dict]:
    """Config thô cho OpenAIPassthrough (gồm api_key thật, không mask)."""
    db = store.default()
    if db is None:
        return []
    rows = db.query("SELECT * FROM openai_provider WHERE enabled != 0 ORDER BY slug")
    by_id = _load_models(db, [int(r["id"]) for r in rows])
    out = []
    for r in rows:
        models = by_id.get(int(r["id"]), [])
        out.append({
            "slug": r["slug"],
            "base_url": r["base_url"],
            "api_key": r["api_key"] or "",
            "api_key_env": r["api_key_env"] or "",
            "models": models,
            "stream": bool(r["stream"]),
        })
    return out


def get_provider(slug: str) -> dict | None:
    db = store.default()
    if db is None:
        return None
    rows = db.query("SELECT * FROM openai_provider WHERE slug = ?", (slug.strip().lower(),))
    if not rows:
        return None
    row = rows[0]
    by_id = _load_models(db, [int(row["id"])])
    return _row_to_provider(row, by_id.get(int(row["id"]), []))


def get_config(slug: str) -> dict | None:
    """Config thô cho một provider (gồm api_key thật)."""
    db = store.default()
    if db is None:
        return None
    rows = db.query("SELECT * FROM openai_provider WHERE slug = ?", (slug.strip().lower(),))
    if not rows:
        return None
    row = rows[0]
    mrows = db.query(
        "SELECT model_id, capability FROM openai_provider_model WHERE provider_id = ?"
        " ORDER BY priority, model_id", (int(row["id"]),))
    return {
        "slug": row["slug"],
        "base_url": row["base_url"],
        "api_key": row["api_key"] or "",
        "api_key_env": row["api_key_env"] or "",
        "models": [{"id": m["model_id"], "capability": m["capability"] or "chat"} for m in mrows],
        "stream": bool(row["stream"]),
    }


def create_provider(data: dict) -> dict:
    clean, errs = validate(data, is_update=False)
    if errs:
        raise ValueError("; ".join(errs))
    db = store.default()
    if db is None:
        raise RuntimeError("kho dữ liệu chưa mở")
    conn = db.connection()
    now = store.now_ms()
    if conn.execute("SELECT 1 FROM openai_provider WHERE slug = ?",
                    (clean["slug"],)).fetchone():
        raise ValueError(f"Slug '{clean['slug']}' đã tồn tại")
    with conn:
        conn.execute(
            "INSERT INTO openai_provider(slug, base_url, api_key, api_key_env,"
            " stream, enabled, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            (clean["slug"], clean["base_url"], clean.get("api_key", ""),
             clean.get("api_key_env", ""), 1 if clean.get("stream", True) else 0,
             now, now))
        row = conn.execute("SELECT id FROM openai_provider WHERE slug = ?",
                           (clean["slug"],)).fetchone()
        pid = int(row["id"])
        for i, m in enumerate(clean.get("models", [])):
            conn.execute(
                "INSERT INTO openai_provider_model(provider_id, model_id, capability, priority)"
                " VALUES (?, ?, ?, ?)", (pid, m["id"], m.get("capability", "chat"), i))
    result = get_provider(clean["slug"])
    assert result is not None
    return result


def update_provider(slug: str, data: dict) -> dict | None:
    slug = str(slug).strip().lower()
    existing = get_provider(slug)
    if existing is None:
        return None
    payload = dict(data)
    # "***" hoặc rỗng nghĩa là giữ key cũ (đồng bộ với desktop).
    if "api_key" in payload and payload["api_key"] in ("***", ""):
        payload.pop("api_key", None)
    clean, errs = validate(payload, is_update=True)
    if errs:
        raise ValueError("; ".join(errs))
    db = store.default()
    if db is None:
        raise RuntimeError("kho dữ liệu chưa mở")
    conn = db.connection()
    now = store.now_ms()
    fields: dict = {}
    if "base_url" in clean:
        fields["base_url"] = clean["base_url"]
    if clean.get("api_key"):
        fields["api_key"] = clean["api_key"]
    if "api_key_env" in clean:
        fields["api_key_env"] = clean["api_key_env"]
    if "stream" in clean:
        fields["stream"] = 1 if clean["stream"] else 0
    if "enabled" in clean:
        fields["enabled"] = clean["enabled"]
    with conn:
        if fields:
            assignments = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE openai_provider SET {assignments}, updated_at = ? WHERE slug = ?",
                         (*fields.values(), now, slug))
        elif "models" not in clean:
            pass
        if "models" in clean:
            row = conn.execute("SELECT id FROM openai_provider WHERE slug = ?",
                               (slug,)).fetchone()
            pid = int(row["id"])
            conn.execute("DELETE FROM openai_provider_model WHERE provider_id = ?", (pid,))
            for i, m in enumerate(clean["models"]):
                conn.execute(
                    "INSERT INTO openai_provider_model(provider_id, model_id, capability, priority)"
                    " VALUES (?, ?, ?, ?)", (pid, m["id"], m.get("capability", "chat"), i))
            conn.execute("UPDATE openai_provider SET updated_at = ? WHERE slug = ?", (now, slug))
    # Validate toàn phần sau merge để không lưu trạng thái dở dang.
    full = get_config(slug)
    assert full is not None
    _, full_errs = validate(
        {"slug": slug, "base_url": full["base_url"], "models": full["models"]}, is_update=False)
    if full_errs:
        raise ValueError("; ".join(full_errs))
    return get_provider(slug)


def delete_provider(slug: str) -> bool:
    slug = str(slug).strip().lower()
    db = store.default()
    if db is None:
        return False
    conn = db.connection()
    with conn:
        cur = conn.execute("DELETE FROM openai_provider WHERE slug = ?", (slug,))
        return cur.rowcount > 0


def migrate_from_dir(recipes_dir: Path) -> dict[str, int]:
    """Migrate một lần recipes/openai/*.yaml vào DB. Idempotent.

    Chỉ insert slug chưa có — DB thắng file. Không xoá file ở đây; router ưu
    tiên DB khi kho đang mở nên file còn lại cũng thành inert.
    """
    import yaml

    recipes_dir = Path(recipes_dir)
    odir = recipes_dir / "openai"
    if not odir.is_dir():
        return {"migrated": 0, "skipped": 0}
    db = store.default()
    if db is None:
        return {"migrated": 0, "skipped": 0}
    migrated = 0
    skipped = 0
    for yml in sorted(odir.glob("*.yaml")):
        try:
            cfg = yaml.safe_load(yml.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(cfg, dict):
            continue
        slug = str(cfg.get("slug") or yml.stem).strip().lower()
        if not valid_slug(slug) or slug in RESERVED:
            continue
        if get_provider(slug) is not None:
            skipped += 1
            continue
        models = cfg.get("models") or []
        norm: list[dict] = []
        for m in models:
            if isinstance(m, str):
                norm.append({"id": m.strip(), "capability": "chat"})
            elif isinstance(m, dict) and str(m.get("id") or "").strip():
                cap = str(m.get("capability") or "chat").strip().lower()
                norm.append({"id": str(m.get("id")).strip(),
                             "capability": cap if cap in CAPABILITIES else "chat"})
        norm = [m for m in norm if m["id"]]
        if not norm:
            continue
        try:
            create_provider({
                "slug": slug,
                "base_url": str(cfg.get("base_url") or "").strip(),
                "api_key": str(cfg.get("api_key") or ""),
                "api_key_env": str(cfg.get("api_key_env") or ""),
                "models": norm,
                "stream": bool(cfg.get("stream", True)),
            })
            migrated += 1
        except ValueError:
            skipped += 1
            continue
    return {"migrated": migrated, "skipped": skipped}
