"""Lưu và tra cứu hội thoại đi qua ``/v1/chat/completions``.

Đường chat chỉ gọi các hàm module này qua ``asyncio.to_thread``: SQLite là
blocking. Một request được ghi đúng hai transaction (mở và đóng), không ghi từng
delta trong lúc stream. Nếu kho chưa mở, mọi hàm trở thành no-op để việc lưu
lịch sử không bao giờ làm hỏng API chat.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from html import escape

from . import store

_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
_API_WINDOW_MS = 30 * 60 * 1000


@dataclass
class Recording:
    session_id: str
    request_id: int | None
    started_at: int
    next_seq: int
    enabled: bool = True
    ttfb_ms: int | None = None
    fallback_used: bool = False


def normalize_session_id(value: str | None) -> str | None:
    """Trả id header hợp lệ; id sai được bỏ qua thay vì cho chui vào SQL/UI."""
    value = (value or "").strip()
    return value if _SESSION_ID.fullmatch(value) else None


def _client_fingerprint(authorization: str, user_agent: str,
                        api_key_id: int | None = None) -> str:
    """Danh tính client để gom các lượt gọi API rời rạc vào cùng một session.

    Có hàng `api_key` thì dùng thẳng id của nó — ổn định, đọc được, và không đổi
    khi client nâng cấp User-Agent. Không có (key bootstrap từ CHAT2API_KEYS)
    thì rơi về hash key+UA; hash không thể khôi phục token thô.
    """
    if api_key_id is not None:
        return f"key{api_key_id}"
    raw = f"{authorization}\0{user_agent}".encode("utf-8", "replace")
    return hashlib.sha256(raw).hexdigest()[:20]


def _title(messages: list[dict]) -> str:
    text = next((str(m.get("content", "")) for m in messages if m.get("role") == "user"), "")
    text = " ".join(text.split())
    return text[:77] + "..." if len(text) > 80 else text


def _recipe_id(conn: sqlite3.Connection, slug: str) -> int | None:
    row = conn.execute("SELECT id FROM recipe WHERE slug = ?", (slug,)).fetchone()
    return row["id"] if row else None


def begin(
    requested_id: str | None,
    model: str,
    recipe_slug: str,
    messages: list[dict],
    stream: bool,
    authorization: str = "",
    user_agent: str = "",
    api_key_id: int | None = None,
    account_id: int | None = None,
    profile_id: int | None = None,
) -> Recording:
    """Mở recording và chèn phần history chưa có cùng request_log ``running``."""
    now = store.now_ms()
    db = store.default()
    if db is None:
        return Recording(requested_id or uuid.uuid4().hex, None, now, 0, enabled=False)

    conn = db.connection()
    explicit = normalize_session_id(requested_id)
    fingerprint = _client_fingerprint(authorization, user_agent, api_key_id)
    with conn:
        recipe_id = _recipe_id(conn, recipe_slug)
        session_id = explicit
        row = None
        if session_id:
            row = conn.execute("SELECT * FROM session WHERE id = ?", (session_id,)).fetchone()
        else:
            # API client không truyền header vẫn hiện trong Sessions: nhóm theo
            # danh tính client (xem _client_fingerprint) và model trong cửa sổ
            # 30 phút.
            cutoff = now - _API_WINDOW_MS
            rows = conn.execute(
                "SELECT * FROM session WHERE kind = 'api' AND model_public_id = ? "
                "AND updated_at >= ? ORDER BY updated_at DESC LIMIT 20",
                (model, cutoff),
            ).fetchall()
            row = next((r for r in rows if json.loads(r["params"] or "{}").get("client") == fingerprint), None)
            session_id = row["id"] if row else uuid.uuid4().hex

        if row is None:
            kind = "chat" if explicit else "api"
            conn.execute(
                "INSERT INTO session(id, title, kind, model_public_id, recipe_id, account_id, "
                "profile_id, params, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, _title(messages), kind, model, recipe_id, account_id, profile_id,
                 json.dumps({"client": fingerprint}, separators=(",", ":")), now, now),
            )
            existing: list[sqlite3.Row] = []
        else:
            existing = conn.execute(
                "SELECT role, content FROM message WHERE session_id = ? ORDER BY seq", (session_id,)
            ).fetchall()
            conn.execute(
                "UPDATE session SET model_public_id = ?, recipe_id = COALESCE(?, recipe_id), "
                "account_id = COALESCE(?, account_id), profile_id = COALESCE(?, profile_id), "
                "updated_at = ? WHERE id = ?",
                (model, recipe_id, account_id, profile_id, now, session_id)
            )

        # Desktop gửi toàn bộ history mỗi lượt. Chỉ nối suffix khi history là
        # prefix chính xác; nếu client sửa nhánh cũ, chỉ lấy message cuối để
        # tránh nhân đôi cả hội thoại trong cùng session.
        incoming = [(str(m.get("role", "user")), str(m.get("content", ""))) for m in messages]
        stored = [(r["role"], r["content"]) for r in existing]
        if incoming[:len(stored)] == stored:
            pending = incoming[len(stored):]
        elif incoming:
            pending = [incoming[-1]]
        else:
            pending = []
        seq = len(stored)
        for role, content in pending:
            conn.execute(
                "INSERT INTO message(session_id, seq, role, content, char_count, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, seq, role, content, len(content), now),
            )
            seq += 1

        prompt_chars = sum(len(content) for _, content in incoming)
        cursor = conn.execute(
            "INSERT INTO request_log(session_id, recipe_id, api_key_id, model_public_id, "
            "stream, status, started_at, prompt_chars, client) "
            "VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?)",
            (session_id, recipe_id, api_key_id, model, int(stream), now, prompt_chars,
             user_agent[:200]),
        )
        _refresh_session(conn, session_id, now)
        return Recording(session_id, int(cursor.lastrowid), now, seq)


def first_delta(recording: Recording) -> None:
    if recording.ttfb_ms is None:
        recording.ttfb_ms = max(0, store.now_ms() - recording.started_at)


def finish(
    recording: Recording,
    content: str,
    *,
    html: str | None = None,
    status: str = "ok",
    error_code: str | None = None,
    error_message: str | None = None,
    http_status: int | None = None,
    finish_reason: str = "stop",
) -> None:
    """Đóng recording trong một transaction, kể cả reply lỗi/partial/cancel."""
    if not recording.enabled:
        return
    db = store.default()
    if db is None:
        return
    now = store.now_ms()
    duration = max(0, now - recording.started_at)
    conn = db.connection()
    with conn:
        cursor = conn.execute(
            "INSERT INTO message(session_id, seq, role, content, content_html, finish_reason, "
            "error, ttfb_ms, duration_ms, char_count, created_at) "
            "VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?, ?, ?, ?)",
            (recording.session_id, recording.next_seq, content, html, finish_reason,
             error_message, recording.ttfb_ms, duration, len(content), now),
        )
        message_id = int(cursor.lastrowid)
        _write_artifacts(conn, message_id, content, now)
        conn.execute(
            "UPDATE request_log SET message_id = ?, status = ?, http_status = ?, error_code = ?, "
            "error_message = ?, fallback_used = ?, ttfb_ms = ?, duration_ms = ?, "
            "completion_chars = ? WHERE id = ?",
            (message_id, status, http_status, error_code, error_message,
             int(recording.fallback_used), recording.ttfb_ms, duration, len(content),
             recording.request_id),
        )
        _refresh_session(conn, recording.session_id, now)


def _refresh_session(conn: sqlite3.Connection, session_id: str, now: int) -> None:
    stats = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(char_count), 0) AS chars, "
        "COALESCE(SUM(duration_ms), 0) AS ms, "
        "COALESCE(SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END), 0) AS errors "
        "FROM message WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn.execute(
        "UPDATE session SET message_count = ?, total_chars = ?, total_ms = ?, error_count = ?, "
        "updated_at = ? WHERE id = ?",
        (stats["n"], stats["chars"], stats["ms"], stats["errors"], now, session_id),
    )


def _write_artifacts(conn: sqlite3.Connection, message_id: int, content: str, now: int) -> None:
    pattern = re.compile(r"```([A-Za-z0-9_+#.-]*)\n([\s\S]*?)```", re.MULTILINE)
    for idx, match in enumerate(pattern.finditer(content)):
        language, body = match.group(1), match.group(2).rstrip("\n")
        kind = "json" if language.lower() == "json" else "code"
        conn.execute(
            "INSERT INTO artifact(message_id, idx, kind, language, body, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)", (message_id, idx, kind, language, body, now)
        )


def list_sessions(q: str = "", model: str = "", archived: bool = False, limit: int = 100) -> list[dict]:
    db = store.default()
    if db is None:
        return []
    limit = min(max(int(limit), 1), 200)
    params: list = [int(archived)]
    where = ["s.archived = ?"]
    if model:
        where.append("s.model_public_id = ?")
        params.append(model)
    if q.strip():
        # FTS MATCH có cú pháp riêng; quote từng token để input UI không thể làm
        # hỏng query bằng dấu hai chấm/ngoặc kép.
        tokens = re.findall(r"[\wÀ-ỹ]+", q, re.UNICODE)
        if not tokens:
            return []
        match = " AND ".join('"' + token.replace('"', '""') + '"' for token in tokens)
        where.append("s.id IN (SELECT m.session_id FROM message m JOIN message_fts f ON f.rowid=m.id WHERE f.content MATCH ?)")
        params.append(match)
    params.append(limit)
    rows = db.query(
        "SELECT s.* FROM v_session_list s WHERE " + " AND ".join(where) +
        " ORDER BY s.pinned DESC, s.updated_at DESC LIMIT ?", tuple(params)
    )
    return [dict(row) for row in rows]


def get_session(session_id: str) -> dict | None:
    db = store.default()
    if db is None:
        return None
    rows = db.query("SELECT * FROM v_session_list WHERE id = ?", (session_id,))
    if not rows:
        return None
    out = dict(rows[0])
    out["tags"] = [r["tag"] for r in db.query(
        "SELECT tag FROM session_tag WHERE session_id = ? ORDER BY tag", (session_id,))]
    messages = []
    for row in db.query("SELECT * FROM message WHERE session_id = ? ORDER BY seq", (session_id,)):
        item = dict(row)
        item["artifacts"] = [dict(a) for a in db.query(
            "SELECT * FROM artifact WHERE message_id = ? ORDER BY idx", (row["id"],))]
        request = db.query(
            "SELECT * FROM request_log WHERE message_id = ? ORDER BY id DESC LIMIT 1", (row["id"],))
        item["request"] = dict(request[0]) if request else None
        messages.append(item)
    out["messages"] = messages
    return out


def update_session(session_id: str, values: dict) -> dict | None:
    db = store.default()
    if db is None:
        return None
    conn = db.connection()
    allowed = {"title", "pinned", "archived"}
    updates = {k: values[k] for k in allowed if k in values}
    with conn:
        if updates:
            clauses = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(f"UPDATE session SET {clauses}, updated_at = ? WHERE id = ?",
                         (*updates.values(), store.now_ms(), session_id))
        if "tags" in values:
            conn.execute("DELETE FROM session_tag WHERE session_id = ?", (session_id,))
            tags = []
            for raw in values.get("tags") or []:
                tag = " ".join(str(raw).strip().split())[:40]
                if tag and tag not in tags:
                    tags.append(tag)
            conn.executemany("INSERT INTO session_tag(session_id, tag) VALUES (?, ?)",
                             [(session_id, tag) for tag in tags[:20]])
    return get_session(session_id)


def delete_session(session_id: str) -> bool:
    db = store.default()
    if db is None:
        return False
    conn = db.connection()
    with conn:
        cursor = conn.execute("DELETE FROM session WHERE id = ?", (session_id,))
    return cursor.rowcount > 0


def fork_session(session_id: str, up_to_seq: int) -> dict | None:
    source = get_session(session_id)
    db = store.default()
    if source is None or db is None:
        return None
    new_id = uuid.uuid4().hex
    now = store.now_ms()
    conn = db.connection()
    with conn:
        conn.execute(
            "INSERT INTO session(id, title, kind, model_public_id, recipe_id, account_id, profile_id, "
            "system_prompt, params, created_at, updated_at) "
            "SELECT ?, ?, kind, model_public_id, recipe_id, account_id, profile_id, system_prompt, params, ?, ? "
            "FROM session WHERE id = ?",
            (new_id, (source["title"] or "Phiên")[:70] + " · nhánh", now, now, session_id),
        )
        rows = conn.execute(
            "SELECT * FROM message WHERE session_id = ? AND seq <= ? ORDER BY seq",
            (session_id, up_to_seq),
        ).fetchall()
        for row in rows:
            conn.execute(
                "INSERT INTO message(session_id, seq, role, content, content_markdown, content_html, "
                "reasoning, tool_call_id, finish_reason, error, ttfb_ms, duration_ms, char_count, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id, row["seq"], row["role"], row["content"], row["content_markdown"],
                 row["content_html"], row["reasoning"], row["tool_call_id"], row["finish_reason"],
                 row["error"], row["ttfb_ms"], row["duration_ms"], row["char_count"], now),
            )
        _refresh_session(conn, new_id, now)
    return get_session(new_id)


def export_session(session_id: str, fmt: str) -> tuple[str, str] | None:
    item = get_session(session_id)
    if item is None:
        return None
    if fmt == "json":
        return json.dumps(item, ensure_ascii=False, indent=2), "application/json"
    if fmt == "jsonl":
        lines = [json.dumps({"session_id": session_id, "role": m["role"], "content": m["content"]}, ensure_ascii=False)
                 for m in item["messages"]]
        return "\n".join(lines) + "\n", "application/x-ndjson"
    if fmt == "html":
        chunks = ["<!doctype html><meta charset=\"utf-8\"><title>" + escape(item["title"] or "Session") + "</title>"]
        for message in item["messages"]:
            chunks.append(f"<h2>{escape(message['role'])}</h2><pre>{escape(message['content'])}</pre>")
        return "\n".join(chunks), "text/html; charset=utf-8"
    chunks = [f"# {item['title'] or 'Session'}", ""]
    for message in item["messages"]:
        chunks.extend([f"## {message['role'].title()}", "", message["content"], ""])
    return "\n".join(chunks), "text/markdown; charset=utf-8"
