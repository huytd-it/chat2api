"""Flows đã xoá — /admin/flows trả 410, recipe là nguồn duy nhất."""
import yaml
from httpx import ASGITransport, AsyncClient

from chat2api.config import Config
from chat2api.main import create_app

RECIPE = {
    "slug": "sitea",
    "url": "https://site.example/chat",
    "prompt": {"input_selector": "#p", "input_mode": "fill", "submit": "Enter"},
    "response": {
        "last_message_selector": ".m",
        "done_signal": {"type": "stable_text", "quiet_ms": 100, "timeout_ms": 5000},
    },
    "models": [{"id": "web"}],
    "timing": {"ready_delay_ms": 0, "input_delay_ms": 0},
}


async def _client(tmp_path):
    cfg = Config()
    cfg.agent_llm_base_url = ""
    cfg.recipes_dir = tmp_path / "recipes"
    cfg.recipes_dir.mkdir(parents=True)
    (cfg.recipes_dir / "sitea").mkdir()
    (cfg.recipes_dir / "sitea" / "recipe.yaml").write_text(
        yaml.safe_dump(RECIPE, allow_unicode=True), encoding="utf-8")
    # compat: flows_dir còn tồn tại trên đĩa cũ nhưng không được nạp
    cfg.flows_dir = tmp_path / "flows"
    cfg.flows_dir.mkdir(parents=True)
    app = create_app(cfg)
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://t")
    return client, app


async def test_flow_endpoints_gone(tmp_path):
    client, _ = await _client(tmp_path)
    for path, method in [
        ("/admin/flows", "get"),
        ("/admin/flows/sitea", "get"),
        ("/admin/flows/sitea", "put"),
        ("/admin/flows/sitea/duplicate", "post"),
        ("/admin/flows/sitea/reload", "post"),
        ("/admin/flows/sitea/test", "post"),
    ]:
        if method == "get":
            r = await client.get(path)
        elif method == "put":
            r = await client.put(path, json={"slug": "sitea", "nodes": []})
        else:
            r = await client.post(path, json={})
        assert r.status_code == 410, f"{method} {path} expected 410 got {r.status_code}: {r.text}"
        assert "Flows" in r.text or "gone" in r.text.lower()


async def test_flow_overrides_recipe_now_resolves_browser_recipe(tmp_path):
    client, app = await _client(tmp_path)
    r = await client.get("/v1/models")
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()["data"]]
    assert "sitea/web" in ids
    provider, local = app.state.router.resolve("sitea/web")
    assert provider.slug == "sitea"
    assert type(provider).__name__ == "BrowserRecipe"
    assert local == "web"
