import pytest

from chat2api import store
from chat2api.store import Store


@pytest.fixture
def combo_store(tmp_path):
    db = store.connect(tmp_path / "chat2api.db")
    db.migrate()
    yield db
    store.shutdown()


async def _create(client, save_history):
    r = await client.post("/admin/combos", json={
        "slug": "direct", "strategy": "round_robin", "save_history": save_history,
        "members": [{"model_id": "fake/m1"}],
    })
    assert r.status_code == 200, r.text
    return r.json()


def _counts(db):
    return tuple(db.query(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"]
                 for t in ("session", "message", "request_log"))


@pytest.mark.parametrize("stream", [False, True])
async def test_combo_without_history_returns_reply_and_writes_nothing(app_client, combo_store, stream):
    await _create(app_client, False)
    r = await app_client.post("/v1/chat/completions", json={
        "model": "combo/direct", "stream": stream,
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 200
    if stream:
        assert '"Hello "' in r.text and "[DONE]" in r.text
    else:
        assert r.json()["choices"][0]["message"]["content"] == "Hello world"
    assert r.headers["X-Chat2api-Session-Id"]
    assert r.headers["X-Chat2api-Combo-Member"] == "fake/m1"
    assert _counts(combo_store) == (0, 0, 0)


async def test_combo_keeps_history_by_default_and_flag_can_be_toggled(app_client, combo_store):
    r = await app_client.post("/admin/combos", json={
        "slug": "direct", "members": [{"model_id": "fake/m1"}],
    })
    assert r.json()["save_history"] is True
    body = {"model": "combo/direct", "messages": [{"role": "user", "content": "hi"}]}
    await app_client.post("/v1/chat/completions", json=body)
    recorded = _counts(combo_store)
    assert recorded == (1, 2, 1)

    r = await app_client.put("/admin/combos/direct", json={"save_history": False})
    assert r.status_code == 200 and r.json()["save_history"] is False
    await app_client.post("/v1/chat/completions", json=body)
    assert _counts(combo_store) == recorded


def test_migration_adds_flag_to_existing_combos(tmp_path):
    db = Store(tmp_path / "old.db")
    db.migrate()
    conn = db.connection()
    with conn:
        conn.execute("ALTER TABLE combo DROP COLUMN save_history")
        conn.execute("DELETE FROM schema_migrations WHERE version = 12")
        conn.execute("INSERT INTO combo(slug, created_at, updated_at) VALUES('old', 0, 0)")
    db.migrate()
    assert db.query("SELECT save_history FROM combo")[0]["save_history"] == 1
    db.close()
