import yaml
from httpx import ASGITransport, AsyncClient

from chat2api.config import Config
from chat2api.main import create_app


class FakeLoginManager:
    def __init__(self):
        self.starts: dict[str, tuple] = {}
        self.completed: list[str] = []
        self.cancelled: list[str] = []

    async def has(self, session_id: str) -> bool:
        return session_id in self.starts

    async def start(self, session_id, slug, url, recipe_dir) -> None:
        self.starts[session_id] = (slug, url, recipe_dir)

    async def complete(self, session_id: str, filename: str = "state.json"):
        _, _, recipe_dir = self.starts.pop(session_id)
        self.completed.append(session_id)
        path = recipe_dir / "auth" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
        return path

    async def cancel(self, session_id: str) -> None:
        self.starts.pop(session_id, None)
        self.cancelled.append(session_id)


def _write_recipe(tmp_path, slug="sitea", login=None):
    d = tmp_path / "recipes" / slug
    d.mkdir(parents=True)
    recipe = {
        "slug": slug, "url": "https://site.example/chat",
        "prompt": {"input_selector": "#p"},
        "response": {"last_message_selector": ".m", "done_signal": {"type": "stable_text"}},
        "models": [{"id": "web"}],
    }
    if login:
        recipe["login"] = login
    (d / "recipe.yaml").write_text(
        yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return d


async def _client(tmp_path, login=None):
    cfg = Config()
    cfg.agent_llm_base_url = ""
    cfg.recipes_dir = tmp_path / "recipes"
    d = _write_recipe(tmp_path, login=login)
    app = create_app(cfg)
    fake = FakeLoginManager()
    app.state.login_manager = fake
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://t")
    return client, app, fake, d


async def test_add_account_flow_updates_recipe_and_reloads(tmp_path):
    client, app, fake, d = await _client(tmp_path, login={"anon_trial_limit": 5})
    async with client:
        r = await client.post("/admin/recipes/sitea/accounts")
        assert r.status_code == 200
        session_id = r.json()["session_id"]
        slug, url, recipe_dir = fake.starts[session_id]
        assert slug == "sitea" and url == "https://site.example/chat"
        assert recipe_dir == d

        r2 = await client.post(
            f"/admin/recipes/sitea/accounts/{session_id}/complete", json={"name": "acct-1"})
        assert r2.status_code == 200
        assert r2.json() == {"ok": True, "slug": "sitea", "account": "acct-1"}

        r3 = await client.get("/admin/recipes")
        entry = next(e for e in r3.json() if e["slug"] == "sitea")
        assert entry["accounts"] == 1
        assert entry["trial"] is None

    saved = yaml.safe_load((d / "recipe.yaml").read_text(encoding="utf-8"))
    assert saved["login"]["accounts"] == [{"name": "acct-1", "storage_state": "auth/acct-1.json"}]
    assert "anon_trial_limit" not in saved["login"]
    assert (d / "auth" / "acct-1.json").exists()


async def test_add_second_account_appends_without_losing_first(tmp_path):
    client, app, fake, d = await _client(
        tmp_path, login={"accounts": [{"name": "acct-1", "storage_state": "auth/acct-1.json"}]})
    (d / "auth").mkdir(parents=True, exist_ok=True)
    (d / "auth" / "acct-1.json").write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    async with client:
        r = await client.post("/admin/recipes/sitea/accounts")
        session_id = r.json()["session_id"]
        r2 = await client.post(
            f"/admin/recipes/sitea/accounts/{session_id}/complete", json={"name": "acct-2"})
        assert r2.status_code == 200

    saved = yaml.safe_load((d / "recipe.yaml").read_text(encoding="utf-8"))
    names = {a["name"] for a in saved["login"]["accounts"]}
    assert names == {"acct-1", "acct-2"}


async def test_cancel_account_login(tmp_path):
    client, app, fake, d = await _client(tmp_path)
    async with client:
        r = await client.post("/admin/recipes/sitea/accounts")
        session_id = r.json()["session_id"]
        r2 = await client.post(f"/admin/recipes/sitea/accounts/{session_id}/cancel")
        assert r2.status_code == 200
        assert r2.json() == {"ok": True}
    assert fake.cancelled == [session_id]


async def test_invalid_account_name_rejected(tmp_path):
    client, app, fake, d = await _client(tmp_path)
    async with client:
        r = await client.post("/admin/recipes/sitea/accounts")
        session_id = r.json()["session_id"]
        r2 = await client.post(
            f"/admin/recipes/sitea/accounts/{session_id}/complete", json={"name": "Bad Name!"})
        assert r2.status_code == 400
        assert r2.json()["error"]["code"] == "invalid_account_name"


async def test_add_account_unknown_recipe_404(tmp_path):
    client, app, fake, d = await _client(tmp_path)
    async with client:
        r = await client.post("/admin/recipes/does-not-exist/accounts")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"
