"""Pha 6 nhìn từ HTTP: CRUD api-key, và cửa xác thực đọc bảng `api_key`.

Các test này *không* chạy lifespan (không mở Chromium), nên kho SQLite được mở
tay bằng `store.connect` — đúng thứ lifespan làm, chỉ bỏ phần trình duyệt.
"""

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from chat2api import apikeys, store
from chat2api.config import Config
from chat2api.main import create_app


@pytest.fixture
def opened_store(tmp_path):
    store.shutdown()
    apikeys.invalidate()
    apikeys._touched.clear()
    handle = store.connect(tmp_path / "store" / "chat2api.db")
    handle.migrate()
    yield handle
    store.shutdown()
    apikeys.invalidate()
    apikeys._touched.clear()


def _app(tmp_path, api_keys=()):
    cfg = Config()
    cfg.agent_llm_base_url = ""
    cfg.env_path = tmp_path / ".env"
    cfg.api_keys = list(api_keys)
    cfg.recipes_dir = tmp_path / "recipes"
    directory = cfg.recipes_dir / "sitea"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "recipe.yaml").write_text(yaml.safe_dump({
        "slug": "sitea", "url": "https://site.example/chat",
        "prompt": {"input_selector": "#p"},
        "response": {"last_message_selector": ".m", "done_signal": {"type": "stable_text"}},
        "models": [{"id": "web"}],
    }), encoding="utf-8")
    app = create_app(cfg)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t"), cfg


async def test_create_lists_and_hides_raw_key(tmp_path, opened_store):
    client, _ = _app(tmp_path)
    async with client:
        created = await client.post("/admin/api-keys", json={"label": "desktop"})
        assert created.status_code == 200
        raw = created.json()["key"]
        assert raw.startswith("c2a-")

        # Từ giờ server đòi key — kể cả để đọc danh sách key.
        assert (await client.get("/admin/api-keys")).status_code == 401

        listed = await client.get("/admin/api-keys",
                                  headers={"authorization": f"Bearer {raw}"})
        body = listed.json()
        assert body["enforced"] is True and body["persisted"] is True
        assert len(body["keys"]) == 1
        # Key thô chỉ có ở response lúc tạo, không bao giờ quay lại.
        assert "key" not in body["keys"][0]
        assert body["keys"][0]["key_prefix"] == raw[:8]


async def test_revoke_then_purge(tmp_path, opened_store):
    client, _ = _app(tmp_path)
    async with client:
        raw = (await client.post("/admin/api-keys", json={"label": "ci"})).json()["key"]
        auth = {"authorization": f"Bearer {raw}"}
        admin = (await client.post("/admin/api-keys", json={"label": "giữ lại"},
                                   headers=auth)).json()
        keep = {"authorization": f"Bearer {admin['key']}"}

        revoked = await client.delete(f"/admin/api-keys/{admin['id']}", headers=auth)
        assert revoked.status_code == 200 and revoked.json()["revoked_at"] is not None
        # Thu hồi có hiệu lực ngay: cache phải bị xoá cùng lúc.
        assert (await client.get("/admin/api-keys", headers=keep)).status_code == 401
        # Hàng vẫn còn để request_log truy ngược được.
        assert len((await client.get("/admin/api-keys", headers=auth)).json()["keys"]) == 2

        purged = await client.delete(f"/admin/api-keys/{admin['id']}?purge=true", headers=auth)
        assert purged.status_code == 200
        assert len((await client.get("/admin/api-keys", headers=auth)).json()["keys"]) == 1

        assert (await client.delete("/admin/api-keys/999", headers=auth)).status_code == 404


async def test_scope_limits_which_router_a_key_reaches(tmp_path, opened_store):
    client, _ = _app(tmp_path)
    async with client:
        chat_only = (await client.post(
            "/admin/api-keys", json={"label": "n8n", "scopes": "chat"})).json()
        admin_key = apikeys.create("quản trị", "admin")

        chat_auth = {"authorization": f"Bearer {chat_only['key']}"}
        admin_auth = {"authorization": f"Bearer {admin_key['key']}"}

        assert (await client.get("/v1/models", headers=chat_auth)).status_code == 200
        forbidden = await client.get("/admin/api-keys", headers=chat_auth)
        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "insufficient_scope"

        assert (await client.get("/admin/api-keys", headers=admin_auth)).status_code == 200
        assert (await client.get("/v1/models", headers=admin_auth)).status_code == 403


async def test_bootstrap_keys_still_work_and_are_counted(tmp_path, opened_store):
    client, _ = _app(tmp_path, api_keys=["boot"])
    async with client:
        assert (await client.get("/admin/api-keys")).status_code == 401
        body = (await client.get("/admin/api-keys",
                                 headers={"authorization": "Bearer boot"})).json()
        assert body["bootstrap_keys"] == 1 and body["enforced"] is True
        assert body["keys"] == []


async def test_health_stays_public(tmp_path, opened_store):
    client, _ = _app(tmp_path)
    async with client:
        await client.post("/admin/api-keys", json={"label": "x"})
        assert (await client.get("/health")).status_code == 200


async def test_no_keys_anywhere_leaves_server_open(tmp_path, opened_store):
    client, _ = _app(tmp_path)
    async with client:
        listed = await client.get("/admin/api-keys")
        assert listed.status_code == 200
        assert listed.json()["enforced"] is False


async def test_create_refuses_when_store_closed(tmp_path):
    store.shutdown()
    apikeys.invalidate()
    client, _ = _app(tmp_path)
    async with client:
        r = await client.post("/admin/api-keys", json={"label": "x"})
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "store_unavailable"
        assert (await client.get("/admin/api-keys")).json()["persisted"] is False


async def test_empty_label_is_rejected(tmp_path, opened_store):
    client, _ = _app(tmp_path)
    async with client:
        r = await client.post("/admin/api-keys", json={"label": "   "})
        assert r.status_code == 400


async def test_request_log_records_which_key_called(tmp_path, opened_store):
    """`request_log.api_key_id` là lý do bảng api_key tồn tại — kiểm nó thật sự được ghi."""
    from chat2api.providers.base import ModelInfo, Provider

    class FakeProvider(Provider):
        slug = "fake"

        def models(self):
            return [ModelInfo(id="fake/m1", slug="fake")]

        async def stream(self, messages, model_id):
            yield "xong"

    client, _ = _app(tmp_path)
    client._transport.app.state.router.providers["fake"] = FakeProvider()
    async with client:
        created = (await client.post("/admin/api-keys", json={"label": "n8n"})).json()
        chat = await client.post(
            "/v1/chat/completions",
            headers={"authorization": f"Bearer {created['key']}"},
            json={"model": "fake/m1", "messages": [{"role": "user", "content": "chào"}]})
        assert chat.status_code == 200

    rows = opened_store.query("SELECT api_key_id FROM request_log ORDER BY id DESC LIMIT 1")
    assert rows[0]["api_key_id"] == created["id"]
