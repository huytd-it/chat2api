"""Synchronous SQLite transactions; call from a worker thread.

The busy marker is durable: after a crash we refuse to submit again until the
remote outcome has been reconciled. We never claim website exactly-once.
"""
import hashlib
import json
from dataclasses import dataclass

from .. import store
from ..errors import OpenAIError


def connection():
    db = store.default()
    if db is None:
        raise OpenAIError(503, "store_unavailable", "Kho dữ liệu chưa mở")
    return db.connection()


def fingerprint(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


@dataclass
class Claim:
    session: dict
    result: dict | None = None


def claim(session_id: str, request_id: str, model: str, digest: str, project_id: str | None = None) -> Claim:
    conn = connection()
    now = store.now_ms()
    try:
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute("SELECT * FROM automation_operation WHERE id=?", (request_id,)).fetchone()
        if old:
            if old["session_id"] != session_id or old["fingerprint"] != digest:
                raise OpenAIError(409, "idempotency_conflict", "request_id đã dùng cho nội dung khác")
            if old["state"] == "completed":
                session = dict(conn.execute("SELECT * FROM automation_session WHERE id=?", (session_id,)).fetchone())
                conn.commit()
                return Claim(session, json.loads(old["result"]))
            if old["state"] != "failed":
                raise OpenAIError(409, "operation_unresolved",
                                  "Tác vụ chưa có kết quả xác nhận; cần đối soát trước khi gửi lại")
            conn.execute("DELETE FROM automation_operation WHERE id=?", (request_id,))
        conn.execute("INSERT OR IGNORE INTO automation_session(id,model,project_id,updated_at) VALUES(?,?,?,?)",
                     (session_id, model, project_id, now))
        session = dict(conn.execute("SELECT * FROM automation_session WHERE id=?", (session_id,)).fetchone())
        if session["model"] != model:
            raise OpenAIError(409, "session_model_conflict", "Session đang gắn với model khác")
        if session["project_id"] != project_id:
            raise OpenAIError(409, "session_project_conflict", "Session đang gắn với project khác")
        if session["busy_operation"]:
            raise OpenAIError(409, "session_unresolved", "Session còn tác vụ chưa đối soát")
        conn.execute("INSERT INTO automation_operation(id,session_id,fingerprint,state,created_at,updated_at) "
                     "VALUES(?,?,?,'prepared',?,?)", (request_id, session_id, digest, now, now))
        conn.execute("UPDATE automation_session SET busy_operation=?,updated_at=? WHERE id=?",
                     (request_id, now, session_id))
        conn.commit()
        return Claim(session)
    except BaseException:
        conn.rollback()
        raise


def submitted(request_id: str):
    conn = connection()
    with conn:
        changed = conn.execute(
            "UPDATE automation_operation SET state='submitted',updated_at=? "
            "WHERE id=? AND state='prepared' AND EXISTS ("
            "SELECT 1 FROM automation_session s WHERE s.id=automation_operation.session_id "
            "AND s.busy_operation=automation_operation.id)",
            (store.now_ms(), request_id)).rowcount
        if changed != 1:
            raise OpenAIError(409, "operation_not_prepared",
                              "Không có operation prepared đang giữ session; không được gửi lại lên website")


def bind(session_id: str, account_id: int | None, url: str | None):
    conn = connection()
    with conn:
        conn.execute("UPDATE automation_session SET account_id=?,conversation_url=?,updated_at=? WHERE id=?",
                     (account_id, url, store.now_ms(), session_id))


def submit_bound(session_id: str, request_id: str, model: str,
                 account_id: int, conversation_url: str | None):
    """Atomically validate the claim, bind its account, and cross submit gate."""
    conn = connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT s.*,o.state AS operation_state FROM automation_session s "
            "JOIN automation_operation o ON o.session_id=s.id AND o.id=? WHERE s.id=?",
            (request_id, session_id)).fetchone()
        if (row is None or row["busy_operation"] != request_id or row["model"] != model
                or row["operation_state"] != "prepared"):
            raise OpenAIError(409, "operation_not_prepared", "Session/request/model không khớp claim prepared hiện tại")
        if row["account_id"] not in (None, account_id):
            raise OpenAIError(409, "session_account_conflict", "Session thuộc account khác")
        if row["conversation_url"] != conversation_url:
            raise OpenAIError(409, "session_context_conflict", "Context đã thay đổi sau khi chuẩn bị request")
        now = store.now_ms()
        conn.execute("UPDATE automation_session SET account_id=?,updated_at=? WHERE id=?",
                     (account_id, now, session_id))
        conn.execute("UPDATE automation_operation SET state='submitted',updated_at=? WHERE id=?",
                     (now, request_id))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def complete(session_id: str, request_id: str, result: dict):
    conn = connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        changed = conn.execute("UPDATE automation_operation SET state='completed',result=?,updated_at=? "
                               "WHERE id=? AND session_id=? AND state IN ('prepared','submitted')",
                               (json.dumps(result, ensure_ascii=False), store.now_ms(), request_id, session_id)).rowcount
        if changed != 1:
            raise RuntimeError("Operation is no longer completable")
        conn.execute("UPDATE automation_session SET successes=successes+1,busy_operation=NULL,updated_at=? "
                     "WHERE id=? AND busy_operation=?", (store.now_ms(), session_id, request_id))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def fail(session_id: str, request_id: str, error: str):
    conn = connection()
    with conn:
        row = conn.execute("SELECT state FROM automation_operation WHERE id=?", (request_id,)).fetchone()
        if not row or row["state"] == "completed":
            return
        uncertain = row["state"] in ("submitted", "uncertain")
        conn.execute("UPDATE automation_operation SET state=?,error=?,updated_at=? WHERE id=?",
                     ("uncertain" if uncertain else "failed", error, store.now_ms(), request_id))
        if not uncertain:
            conn.execute("UPDATE automation_session SET busy_operation=NULL WHERE id=? AND busy_operation=?",
                         (session_id, request_id))


def get_session(session_id: str):
    row = connection().execute("SELECT * FROM automation_session WHERE id=?", (session_id,)).fetchone()
    return dict(row) if row else None


def rollover(session_id: str):
    conn = connection()
    with conn:
        conn.execute("UPDATE automation_session SET conversation_url=NULL,successes=0,"
                     "generation=generation+1,updated_at=? WHERE id=?",
                     (store.now_ms(), session_id))
