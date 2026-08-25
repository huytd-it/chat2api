import yaml
from httpx import ASGITransport, AsyncClient

from chat2api.config import Config
from chat2api.main import create_app


async def _client(tmp_path):
    cfg = Config()
    cfg.agent_llm_base_url = ""
    cfg.recipes_dir = tmp_path / "recipes"
    # Bắt buộc: mặc định env_path trỏ vào .env thật của project, test không được ghi đè.
    cfg.env_path = tmp_path / ".env"
    directory = cfg.recipes_dir / "sitea"
    directory.mkdir(parents=True)
    (directory / "recipe.yaml").write_text(yaml.safe_dump({
        "slug": "sitea", "url": "https://site.example/chat",
        "prompt": {"input_selector": "#p"},
        "response": {"last_message_selector": ".m", "done_signal": {"type": "stable_text"}},
        "models": [{"id": "web"}],
    }), encoding="utf-8")
    app = create_app(cfg)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t"), cfg


async def test_get_settings_lists_fields_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_LLM_API_KEY", "sk-secret")
    client, cfg = await _client(tmp_path)
    async with client:
        r = await client.get("/admin/settings")
        assert r.status_code == 200
        body = r.json()
        assert body["env_path"] == str(cfg.env_path)
        secret = next(f for f in body["fields"] if f["key"] == "AGENT_LLM_API_KEY")
        assert secret["value"] == "" and secret["is_set"] is True
        delay = next(f for f in body["fields"] if f["key"] == "RECIPE_READY_DELAY_MS")
        assert delay["apply"] == "reload"


async def test_put_settings_writes_env_and_flags_restart(tmp_path, monkeypatch):
    monkeypatch.delenv("POOL_MAX_CONTEXTS", raising=False)
    client, cfg = await _client(tmp_path)
    async with client:
        r = await client.put("/admin/settings", json={"values": {
            "RECIPE_READY_DELAY_MS": "1500", "POOL_MAX_CONTEXTS": "5"}})
        assert r.status_code == 200
        assert r.json()["needs_restart"] == ["POOL_MAX_CONTEXTS"]

    text = cfg.env_path.read_text(encoding="utf-8")
    assert "RECIPE_READY_DELAY_MS=1500" in text
    assert "POOL_MAX_CONTEXTS=5" in text


async def test_put_settings_rejects_bad_value(tmp_path):
    client, cfg = await _client(tmp_path)
    async with client:
        r = await client.put("/admin/settings",
                             json={"values": {"RECIPE_READY_DELAY_MS": "abc"}})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "invalid_settings"
    assert not cfg.env_path.exists()


async def test_create_app_does_not_write_into_recipes_dir(tmp_path):
    """main.py tạo `app` lúc import — import không được đụng vào recipes thật."""
    cfg = Config()
    cfg.recipes_dir = tmp_path / "recipes"
    cfg.env_path = tmp_path / ".env"
    legacy = cfg.recipes_dir / "chat" / "auth"
    legacy.mkdir(parents=True)
    (legacy / "a1.json").write_text("{}", encoding="utf-8")
    (cfg.recipes_dir / "chat" / "recipe.yaml").write_text(yaml.safe_dump({
        "slug": "chat", "url": "https://chat.example/",
        "prompt": {"input_selector": "#p"},
        "response": {"last_message_selector": ".m", "done_signal": {"type": "stable_text"}},
        "models": [{"id": "web"}],
        "login": {"accounts": [{"name": "a1", "storage_state": "auth/a1.json"}]},
    }), encoding="utf-8")

    create_app(cfg)

    # Migration chỉ chạy ở lifespan (server khởi động), không phải lúc dựng app.
    assert not (cfg.recipes_dir / ".accounts").exists()


async def test_overview_reports_counts(tmp_path):
    client, cfg = await _client(tmp_path)
    async with client:
        r = await client.get("/admin/overview")
        assert r.status_code == 200
        body = r.json()
        assert body["recipes"] == 1
        assert body["models"] == 1
        assert body["browser_recipes"] == 1
        assert body["unhealthy"] == []
        assert body["open_browsers"] == []
        assert body["accounts"] == 0
