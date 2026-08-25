import pytest

from chat2api import applog, store


@pytest.fixture
def db(tmp_path):
    s = store.connect(tmp_path / "chat2api.db")
    s.migrate()
    applog._entries.clear()
    try:
        yield s
    finally:
        store.shutdown()
        applog._entries.clear()


def test_log_works_without_store():
    """CLI và test đơn vị chạy không có kho — tầng RAM phải nguyên vẹn."""
    assert store.default() is None
    applog._entries.clear()
    applog.log("chat: không có DB")
    assert applog.since()[-1]["message"] == "chat: không có DB"
    assert applog.history() == []


def test_log_persists_to_db(db):
    applog.log("chat: model=fake/m1")
    applog.log("recipe: reload chat")
    db.flush(timeout=10)
    rows = db.query("SELECT level, source, message FROM app_log ORDER BY id")
    assert [(r["source"], r["message"]) for r in rows] == [
        ("chat", "chat: model=fake/m1"),
        ("recipe", "recipe: reload chat"),
    ]


def test_source_falls_back_to_app_for_free_text(db):
    applog.log("Server khởi động (engine=playwright)")
    applog.log("linh tinh: không phải nguồn đã biết")
    db.flush(timeout=10)
    assert [r["source"] for r in db.query("SELECT source FROM app_log ORDER BY id")] == \
        ["app", "app"]


def test_history_returns_newest_first_and_filters(db):
    applog.log("chat: một")
    applog.log("account: hai", "warn")
    applog.log("chat: ba", "error")
    db.flush(timeout=10)

    assert [e["message"] for e in applog.history()] == ["chat: ba", "account: hai", "chat: một"]
    assert [e["message"] for e in applog.history(level="error")] == ["chat: ba"]
    assert [e["message"] for e in applog.history(source="chat")] == ["chat: ba", "chat: một"]
    assert [e["message"] for e in applog.history(search="hai")] == ["account: hai"]
    # ts trả ra là giây (khớp `since`), dù DB lưu milliseconds.
    assert applog.history()[0]["ts"] < 1e12


def test_history_paginates_backwards(db):
    for i in range(5):
        applog.log(f"chat: {i}")
    db.flush(timeout=10)
    first = applog.history(limit=2)
    assert [e["message"] for e in first] == ["chat: 4", "chat: 3"]
    assert [e["message"] for e in applog.history(before=first[-1]["id"], limit=2)] == \
        ["chat: 2", "chat: 1"]


def test_history_search_escapes_like_wildcards(db):
    applog.log("chat: 100% xong")
    applog.log("chat: không liên quan")
    db.flush(timeout=10)
    # '%' trong từ khoá phải là ký tự thật, không phải wildcard bắt mọi dòng.
    assert [e["message"] for e in applog.history(search="100%")] == ["chat: 100% xong"]


def test_history_survives_restart(tmp_path):
    path = tmp_path / "chat2api.db"
    first = store.connect(path)
    first.migrate()
    applog.log("chat: trước khi tắt")
    first.flush(timeout=10)
    store.shutdown()

    applog._entries.clear()          # RAM mất hết, như sau một lần restart thật
    second = store.connect(path)
    second.migrate()
    try:
        assert applog.since() == []
        assert [e["message"] for e in applog.history()] == ["chat: trước khi tắt"]
    finally:
        store.shutdown()
        applog._entries.clear()
