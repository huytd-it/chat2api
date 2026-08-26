"""Bảng `api_key` (pha 6): tạo/thu hồi/xoá, cache, và tiết chế last_used_at."""

import pytest

from chat2api import apikeys, store


@pytest.fixture
def db(tmp_path):
    store.shutdown()
    apikeys.invalidate()
    apikeys._touched.clear()
    handle = store.connect(tmp_path / "k.db")
    handle.migrate()
    yield handle
    store.shutdown()
    apikeys.invalidate()
    apikeys._touched.clear()


def test_create_returns_raw_key_once_and_stores_only_hash(db):
    created = apikeys.create("desktop")

    assert created["key"].startswith(apikeys.PREFIX)
    assert created["key_prefix"] == created["key"][:8]
    # Key thô không được nằm ở bất kỳ cột nào — DB chỉ giữ sha256.
    row = db.query("SELECT * FROM api_key WHERE id = ?", (created["id"],))[0]
    assert row["key_hash"] == apikeys.hash_key(created["key"])
    assert created["key"] not in "".join(str(v) for v in tuple(row))
    # Và không lộ lại ở đường liệt kê.
    listed = apikeys.list_keys()[0]
    assert "key" not in listed and "key_hash" not in listed


def test_match_finds_active_key_and_misses_revoked(db):
    created = apikeys.create("ci")
    raw = created["key"]

    assert apikeys.match(raw)["id"] == created["id"]
    assert apikeys.match("c2a-khong-ton-tai") is None

    apikeys.revoke(created["id"])
    assert apikeys.match(raw) is None


def test_revoke_keeps_row_purge_removes_it(db):
    created = apikeys.create("n8n")

    revoked = apikeys.revoke(created["id"])
    assert revoked["revoked_at"] is not None
    assert len(apikeys.list_keys()) == 1  # còn hàng để request_log truy ngược

    assert apikeys.delete(created["id"]) is True
    assert apikeys.list_keys() == []
    assert apikeys.delete(created["id"]) is False


def test_cache_is_lazy_and_dropped_on_change(db):
    apikeys.invalidate()
    assert apikeys.cached() is None  # chưa nạp thì không chạm đĩa

    apikeys.active()
    assert apikeys.cached() == {}

    created = apikeys.create("a")
    assert apikeys.cached() is None  # tạo key phải làm cache cũ hết hiệu lực
    assert len(apikeys.active()) == 1

    apikeys.revoke(created["id"])
    assert apikeys.cached() is None


def test_scopes_filtered_and_defaulted(db):
    assert apikeys.create("a", "chat")["scopes"] == ["chat"]
    assert apikeys.create("b", "admin, chat")["scopes"] == ["chat", "admin"]
    assert apikeys.create("c", "root")["scopes"] == ["chat", "admin"]
    assert apikeys.create("d", "")["scopes"] == ["chat", "admin"]


def test_label_is_required(db):
    with pytest.raises(ValueError):
        apikeys.create("   ")


def test_touch_is_throttled(db):
    created = apikeys.create("x")
    apikeys.match(created["key"])
    db.flush()
    first = db.query("SELECT last_used_at FROM api_key WHERE id = ?",
                     (created["id"],))[0]["last_used_at"]
    assert first is not None

    # Lượt kế tiếp trong cùng phút không được xếp thêm lệnh ghi nào.
    apikeys.match(created["key"])
    db.flush()
    again = db.query("SELECT last_used_at FROM api_key WHERE id = ?",
                     (created["id"],))[0]["last_used_at"]
    assert again == first


def test_create_without_store_refuses(tmp_path):
    store.shutdown()
    apikeys.invalidate()
    with pytest.raises(RuntimeError):
        apikeys.create("mo-coi")
    assert apikeys.list_keys() == []
