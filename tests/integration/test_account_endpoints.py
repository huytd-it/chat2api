import yaml
from httpx import ASGITransport, AsyncClient

from chat2api.config import Config
from chat2api.main import create_app


class FakeLoginManager:
    def __init__(self, cookies=None, url=""):
        self.starts: dict[str, tuple] = {}
        self.completed: list[str] = []
        self.cancelled: list[str] = []
        # Dấu vết mà một phiên đăng nhập thật để lại — đường tự dò domain đọc nó.
        self.cookies = cookies or []
        self.url = url

    async def snapshot(self, session_id: str) -> dict:
        if session_id not in self.starts:
            return {}
        return {"cookies": list(self.cookies), "url": self.url}

    async def has(self, session_id: str) -> bool:
        return session_id in self.starts

    async def start(self, session_id, slug, url, recipe_dir, storage_state=None) -> None:
        self.starts[session_id] = (slug, url, recipe_dir, storage_state)

    async def complete(self, session_id: str, filename: str = "state.json"):
        _, _, recipe_dir, _ = self.starts.pop(session_id)
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


async def _client(tmp_path, login=None, cookies=None, url=""):
    cfg = Config()
    cfg.agent_llm_base_url = ""
    cfg.recipes_dir = tmp_path / "recipes"
    d = _write_recipe(tmp_path, login=login)
    app = create_app(cfg)
    fake = FakeLoginManager(cookies, url)
    app.state.login_manager = fake
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://t")
    return client, app, fake, d


async def test_add_account_saves_into_shared_domain_store(tmp_path):
    """Account mới về kho chung của domain, recipe.yaml không cần biết tới nó."""
    client, app, fake, d = await _client(tmp_path, login={"anon_trial_limit": 5})
    store = tmp_path / "recipes" / ".accounts" / "site.example"
    async with client:
        r = await client.post("/admin/recipes/sitea/accounts")
        assert r.status_code == 200
        session_id = r.json()["session_id"]
        slug, url, recipe_dir, storage_state = fake.starts[session_id]
        assert slug == "sitea" and url == "https://site.example/chat"
        assert recipe_dir == store
        assert storage_state is None

        r2 = await client.post(
            f"/admin/recipes/sitea/accounts/{session_id}/complete", json={"name": "acct-1"})
        assert r2.status_code == 200
        assert r2.json() == {"ok": True, "slug": "sitea", "account": "acct-1",
                             "domain": "site.example"}

        r3 = await client.get("/admin/recipes")
        entry = next(e for e in r3.json() if e["slug"] == "sitea")
        assert entry["accounts"] == 1
        assert entry["trial"] is None

    assert (store / "acct-1.json").exists()
    saved = yaml.safe_load((d / "recipe.yaml").read_text(encoding="utf-8"))
    assert "accounts" not in saved.get("login", {})
    assert "anon_trial_limit" not in saved["login"]


async def test_recipe_sees_both_declared_and_shared_accounts(tmp_path):
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

        r3 = await client.get("/admin/recipes")
        entry = next(e for e in r3.json() if e["slug"] == "sitea")
        assert set(entry["account_names"]) == {"acct-1", "acct-2"}


async def test_second_recipe_on_same_domain_reuses_accounts(tmp_path):
    """Đúng yêu cầu chính: đăng nhập một lần, mọi recipe cùng domain dùng lại."""
    client, app, fake, d = await _client(tmp_path)
    async with client:
        r = await client.post("/admin/recipes/sitea/accounts")
        session_id = r.json()["session_id"]
        await client.post(
            f"/admin/recipes/sitea/accounts/{session_id}/complete", json={"name": "shared-1"})

        _write_recipe(tmp_path, slug="siteb")
        await client.post("/admin/recipes/siteb/reload")

        r2 = await client.get("/admin/recipes")
        entry = next(e for e in r2.json() if e["slug"] == "siteb")
        assert entry["account_names"] == ["shared-1"]


async def test_accounts_page_lists_domains_with_using_recipes(tmp_path):
    client, app, fake, d = await _client(tmp_path)
    async with client:
        r = await client.post("/admin/recipes/sitea/accounts")
        session_id = r.json()["session_id"]
        await client.post(
            f"/admin/recipes/sitea/accounts/{session_id}/complete", json={"name": "acct-1"})

        r2 = await client.get("/admin/accounts")
        assert r2.status_code == 200
        entry = next(e for e in r2.json() if e["domain"] == "site.example")
        assert [a["name"] for a in entry["accounts"]] == ["acct-1"]
        assert entry["recipes"] == ["sitea"]


async def test_delete_shared_account(tmp_path):
    client, app, fake, d = await _client(tmp_path)
    async with client:
        r = await client.post("/admin/recipes/sitea/accounts")
        session_id = r.json()["session_id"]
        await client.post(
            f"/admin/recipes/sitea/accounts/{session_id}/complete", json={"name": "acct-1"})

        r2 = await client.delete("/admin/accounts/site.example/acct-1")
        assert r2.status_code == 200
        r3 = await client.get("/admin/recipes")
        entry = next(e for e in r3.json() if e["slug"] == "sitea")
        assert entry["account_names"] == []

        assert (await client.delete("/admin/accounts/site.example/acct-1")).status_code == 404


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


async def test_recipes_list_exposes_account_names(tmp_path):
    client, app, fake, d = await _client(
        tmp_path, login={"accounts": [{"name": "acct-1", "storage_state": "auth/acct-1.json"}]})
    async with client:
        r = await client.get("/admin/recipes")
        entry = next(e for e in r.json() if e["slug"] == "sitea")
        assert entry["account_names"] == ["acct-1"]


async def test_reopen_account_login_uses_saved_storage_state(tmp_path):
    client, app, fake, d = await _client(
        tmp_path, login={"accounts": [{"name": "acct-1", "storage_state": "auth/acct-1.json"}]})
    async with client:
        r = await client.post("/admin/recipes/sitea/accounts/acct-1/reopen")
        assert r.status_code == 200
        session_id = r.json()["session_id"]
        assert r.json()["name"] == "acct-1"
        slug, url, recipe_dir, storage_state = fake.starts[session_id]
        assert slug == "sitea"
        assert storage_state == d / "auth" / "acct-1.json"


async def test_reopen_unknown_account_404(tmp_path):
    client, app, fake, d = await _client(
        tmp_path, login={"accounts": [{"name": "acct-1", "storage_state": "auth/acct-1.json"}]})
    async with client:
        r = await client.post("/admin/recipes/sitea/accounts/nope/reopen")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"


# ------------------------------------ tự dò domain khi để trống (§6.1, pha 5)


async def test_login_without_domain_opens_blank_page_in_pending_dir(tmp_path):
    """Bậc 4: chưa biết đi đâu thì mở trang trắng, không tạo domain rác."""
    client, app, fake, d = await _client(tmp_path)
    async with client:
        r = await client.post("/admin/accounts/login", json={"domain": "", "url": ""})
        assert r.status_code == 200
        assert r.json()["domain"] == ""
        _, url, login_dir, storage_state = fake.starts[r.json()["session_id"]]
        assert url == "about:blank"
        assert login_dir == tmp_path / "recipes" / ".accounts" / "_pending"
        assert storage_state is None


async def test_save_without_domain_infers_it_from_cookies(tmp_path):
    client, app, fake, d = await _client(
        tmp_path,
        cookies=[{"domain": ".site.example", "name": "session-token"},
                 {"domain": ".accounts.google.com", "name": "__Secure-auth"},
                 {"domain": ".metrics.example", "name": "_ga"}],
        url="https://site.example/chat")
    async with client:
        session_id = (await client.post(
            "/admin/accounts/login", json={"domain": ""})).json()["session_id"]
        r = await client.post(f"/admin/accounts/login/{session_id}/complete",
                              json={"domain": "", "name": "acct-1"})
        assert r.status_code == 200
        body = r.json()
        assert body["domain"] == "site.example" and body["name"] == "acct-1"
        # Cookie Google trong cùng phiên là gợi ý, không phải account tự tạo.
        assert body["suggested"] == ["accounts.google.com"]

        listing = (await client.get("/admin/accounts")).json()
        entry = next(e for e in listing if e["domain"] == "site.example")
        assert [a["name"] for a in entry["accounts"]] == ["acct-1"]

    # State chuyển từ thư mục tạm về đúng kho của domain, không để lại rác.
    store = tmp_path / "recipes" / ".accounts"
    assert (store / "site.example" / "acct-1.json").exists()
    assert not (store / "_pending").exists()


async def test_save_without_domain_falls_back_to_cookies_when_url_is_blank(tmp_path):
    client, app, fake, d = await _client(
        tmp_path, cookies=[{"domain": "site.example", "name": "sid"}], url="about:blank")
    async with client:
        session_id = (await client.post(
            "/admin/accounts/login", json={"domain": ""})).json()["session_id"]
        r = await client.post(f"/admin/accounts/login/{session_id}/complete",
                              json={"domain": "", "name": "acct-1"})
        assert r.json()["domain"] == "site.example"


async def test_save_without_domain_and_without_session_cookies_is_rejected(tmp_path):
    client, app, fake, d = await _client(
        tmp_path, cookies=[{"domain": ".metrics.example", "name": "_ga"}], url="about:blank")
    async with client:
        session_id = (await client.post(
            "/admin/accounts/login", json={"domain": ""})).json()["session_id"]
        r = await client.post(f"/admin/accounts/login/{session_id}/complete",
                              json={"domain": "", "name": "acct-1"})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "domain_not_detected"
        # Phiên vẫn còn để người dùng đăng nhập tiếp rồi lưu lại.
        assert session_id in fake.starts


async def test_explicit_domain_still_wins_over_cookies(tmp_path):
    client, app, fake, d = await _client(
        tmp_path, cookies=[{"domain": ".other.example", "name": "session"}],
        url="https://other.example/")
    async with client:
        session_id = (await client.post(
            "/admin/accounts/login", json={"domain": "site.example"})).json()["session_id"]
        r = await client.post(f"/admin/accounts/login/{session_id}/complete",
                              json={"domain": "site.example", "name": "acct-1"})
        assert r.json()["domain"] == "site.example"
    assert (tmp_path / "recipes" / ".accounts" / "site.example" / "acct-1.json").exists()


async def test_recipes_listing_exposes_domain_for_grouping(tmp_path):
    client, app, fake, d = await _client(tmp_path)
    async with client:
        entry = next(e for e in (await client.get("/admin/recipes")).json()
                     if e["slug"] == "sitea")
        assert entry["domain"] == "site.example"
        assert entry["url"] == "https://site.example/chat"
