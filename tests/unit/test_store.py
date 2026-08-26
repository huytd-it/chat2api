import sqlite3

import pytest

from chat2api import store

# Version cao nhất mà kho biết tới = baseline + mọi file trong migrations/.
# Tính ra thay vì viết cứng, để thêm một migration không phải sửa test.
MIGRATIONS = store._migration_files()
LATEST = max([store.BASELINE_VERSION] + [version for version, _ in MIGRATIONS])


@pytest.fixture
def db(tmp_path):
    s = store.Store(tmp_path / "sub" / "chat2api.db")
    try:
        yield s
    finally:
        s.close()


def test_migrate_creates_schema_and_stamps_version(db):
    assert db.migrate() == LATEST
    names = {r["name"] for r in db.query(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    # Bốn nhóm bảng của docs/design-v2.md §2 phải có mặt hết.
    assert {"profile", "domain", "account", "recipe", "model", "session", "message",
            "tool_call", "request_log", "job", "job_log", "app_log", "api_key",
            "v_session_list"} <= names
    # DB rỗng chạy thẳng schema.sql rồi đóng dấu MỌI version đã biết — apply
    # lại từng migration lên nó sẽ là double-apply.
    stamped = db.query("SELECT version, name FROM schema_migrations ORDER BY version")
    assert [(r["version"], r["name"]) for r in stamped] == [
        (store.BASELINE_VERSION, store.BASELINE_NAME),
        *((version, path.name) for version, path in MIGRATIONS)]


def test_migrate_is_idempotent(db):
    assert db.migrate() == db.migrate() == LATEST
    assert (db.query("SELECT COUNT(*) AS n FROM schema_migrations")[0]["n"]
            == 1 + len(MIGRATIONS))


def test_migrate_reopens_existing_db(tmp_path):
    path = tmp_path / "chat2api.db"
    first = store.Store(path)
    first.migrate()
    first.close()
    # Mở lại kho đã có: không được chạy lại schema.sql, không được mất dữ liệu.
    second = store.Store(path)
    try:
        second.submit("INSERT INTO app_log(ts, level, source, message) VALUES (1, 'info', 'app', 'x')")
        second.flush()
        assert second.migrate() == LATEST
        assert second.query("SELECT COUNT(*) AS n FROM app_log")[0]["n"] == 1
    finally:
        second.close()


def test_wal_and_foreign_keys_on(db):
    db.migrate()
    assert db.query("PRAGMA journal_mode")[0][0] == "wal"
    assert db.query("PRAGMA foreign_keys")[0][0] == 1


def test_submit_batches_and_flush_waits(db):
    db.migrate()
    for i in range(500):
        db.submit("INSERT INTO app_log(ts, level, source, message) VALUES (?, 'info', 'app', ?)",
                  (i, f"dòng {i}"))
    assert db.flush(timeout=10) is True
    assert db.query("SELECT COUNT(*) AS n FROM app_log")[0]["n"] == 500


def test_submit_never_raises_on_bad_sql(db, capsys):
    db.migrate()
    db.submit("INSERT INTO bảng_không_có_thật(x) VALUES (1)")
    db.submit("INSERT INTO app_log(ts, level, source, message) VALUES (2, 'info', 'app', 'sau')")
    db.flush(timeout=10)
    # Lệnh hỏng chỉ in ra stderr; writer không được chết, lệnh sau vẫn ghi được.
    assert "store write failed" in capsys.readouterr().err
    assert db.query("SELECT message FROM app_log")[0]["message"] == "sau"


def test_profile_can_hold_accounts_on_many_domains(db):
    """Ràng buộc cốt lõi của §3: một profile đăng nhập được nhiều domain."""
    db.migrate()
    conn = db.connection()
    with conn:
        conn.execute("INSERT INTO profile(name, user_data_dir, created_at)"
                     " VALUES ('main', 'data/profiles/main', 0)")
        for host in ("chat.qwen.ai", "chatgpt.com"):
            conn.execute("INSERT INTO domain(host, created_at) VALUES (?, 0)", (host,))
            conn.execute("INSERT INTO account(profile_id, domain_id, label, created_at)"
                         " VALUES (1, last_insert_rowid(), 'work', 0)")
    hosts = [r["host"] for r in db.query(
        "SELECT d.host FROM account a JOIN domain d ON d.id = a.domain_id"
        " WHERE a.profile_id = 1 ORDER BY d.host")]
    assert hosts == ["chat.qwen.ai", "chatgpt.com"]


def test_one_default_profile_only(db):
    db.migrate()
    conn = db.connection()
    conn.execute("INSERT INTO profile(name, user_data_dir, is_default, created_at)"
                 " VALUES ('a', 'x', 1, 0)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO profile(name, user_data_dir, is_default, created_at)"
                     " VALUES ('b', 'y', 1, 0)")


def test_message_fts_matches_vietnamese_without_diacritics(db):
    db.migrate()
    conn = db.connection()
    with conn:
        conn.execute("INSERT INTO session(id, created_at, updated_at) VALUES ('s1', 0, 0)")
        conn.execute("INSERT INTO message(session_id, seq, role, content, created_at)"
                     " VALUES ('s1', 0, 'user', 'Phân tích trang web này', 0)")
    assert db.query("SELECT rowid FROM message_fts WHERE message_fts MATCH 'phan'")
    assert db.query("SELECT rowid FROM message_fts WHERE message_fts MATCH 'phân'")
    # Trigger xoá phải dọn cả index, không để lại bóng ma.
    with conn:
        conn.execute("DELETE FROM message")
    assert not db.query("SELECT rowid FROM message_fts WHERE message_fts MATCH 'phan'")


def test_deleting_session_cascades_to_messages(db):
    db.migrate()
    conn = db.connection()
    with conn:
        conn.execute("INSERT INTO session(id, created_at, updated_at) VALUES ('s1', 0, 0)")
        conn.execute("INSERT INTO message(session_id, seq, role, content, created_at)"
                     " VALUES ('s1', 0, 'user', 'hi', 0)")
        conn.execute("DELETE FROM session WHERE id = 's1'")
    assert db.query("SELECT COUNT(*) AS n FROM message")[0]["n"] == 0


def test_close_releases_connections_made_on_other_threads(tmp_path):
    """Reader được tạo trong to_thread pool; shutdown chạy ở thread khác vẫn phải đóng được."""
    import threading

    s = store.Store(tmp_path / "chat2api.db")
    s.migrate()
    worker = threading.Thread(target=lambda: s.query("SELECT 1"))
    worker.start()
    worker.join()
    assert len(s._readers) == 2          # main (migrate) + worker
    s.close()
    assert s._readers == []
    # Connection đã đóng thật thì dùng lại phải nổ, không phải im lặng rò rỉ.
    with pytest.raises(sqlite3.ProgrammingError):
        s.connection().execute("SELECT 1")


def test_connect_replaces_previous_default(tmp_path):
    try:
        first = store.connect(tmp_path / "a.db")
        assert store.default() is first
        second = store.connect(tmp_path / "b.db")
        assert store.default() is second
        assert second is not first
    finally:
        store.shutdown()
    assert store.default() is None
