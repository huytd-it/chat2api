"""API tài khoản Google của profile. Không đụng Google thật: phần check/login
được thay bằng service giả để kiểm đường đi của endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

from chat2api import google_auth, store
from chat2api.config import Config
from chat2api.main import create_app


@pytest.fixture
async def client(tmp_path):
    cfg = Config()
    cfg.agent_llm_base_url = ""
    cfg.recipes_dir = tmp_path / "recipes"
    cfg.recipes_dir.mkdir()
    cfg.profiles_dir = tmp_path / "profiles"
    db = store.connect(tmp_path / "chat2api.db")
    db.migrate()
    app = create_app(cfg)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            yield c, app
    finally:
        store.shutdown()


async def test_save_identity_never_returns_secrets(client):
    c, _ = client
    pid = (await c.post("/admin/profiles", json={"name": "main"})).json()["id"]
    r = await c.put(f"/admin/profiles/{pid}/google",
                    json={"email": "me@gmail.com", "password": "hunter2"})
    assert r.status_code == 200
    body = r.json()["identity"]
    assert body["email"] == "me@gmail.com" and body["has_password"]
    assert "hunter2" not in r.text

    got = (await c.get(f"/admin/profiles/{pid}/google")).json()
    assert got["identity"]["has_password"] and got["waiting"] is False
    assert "hunter2" not in (await c.get("/admin/google")).text


async def test_bad_email_is_400(client):
    c, _ = client
    pid = (await c.post("/admin/profiles", json={"name": "main"})).json()["id"]
    r = await c.put(f"/admin/profiles/{pid}/google", json={"email": "nope"})
    assert r.status_code == 400


async def test_check_and_sites_go_through_service(client, monkeypatch):
    c, app = client
    pid = (await c.post("/admin/profiles", json={"name": "main"})).json()["id"]
    svc = app.state.google

    async def fake_check(row):
        return await svc._record(row, {"status": "verify_required", "url": "https://accounts.google.com/v3/signin/challenge/ipp",
                                       "detail": "Google yêu cầu xác minh: mã SMS"})

    async def fake_sites(row, targets, **kw):
        return [{"ok": True, "host": t, "url": f"https://{t}/", "status": "done", "detail": ""}
                for t in targets]

    monkeypatch.setattr(svc, "check", fake_check)
    monkeypatch.setattr(svc, "sites", fake_sites)

    r = await c.post(f"/admin/profiles/{pid}/google/check")
    assert r.status_code == 200
    assert r.json()["identity"]["status"] == "verify_required"
    assert google_auth.get_identity(pid)["verify_url"].endswith("/ipp")

    r = await c.post(f"/admin/profiles/{pid}/google/sites", json={"targets": ["chat.qwen.ai"]})
    assert r.json()["results"][0]["host"] == "chat.qwen.ai"
    r = await c.post(f"/admin/profiles/{pid}/google/sites", json={"targets": []})
    assert r.status_code == 400
