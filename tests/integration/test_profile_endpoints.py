"""Trang Integrations gộp: CRUD profile + tự dò domain (pha 5, docs/design-v2.md §6).

Không mở Chromium thật ở đây — phần mở browser đã có test riêng ở
`test_pool_profile.py`. File này kiểm phần API: hàng DB, luật từ chối xoá, và
đường quét cookie của một profile đang mở (context giả).
"""

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from chat2api import store
from chat2api.config import Config
from chat2api.main import create_app


class FakeContext:
    """Persistent context giả, chỉ cần trả về cookie cho /detect."""

    def __init__(self, cookies):
        self._cookies = cookies

    async def cookies(self):
        return self._cookies


def _write_recipe(recipes_dir, slug="sitea", url="https://site.example/chat"):
    directory = recipes_dir / slug
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "recipe.yaml").write_text(yaml.safe_dump({
        "slug": slug, "url": url,
        "prompt": {"input_selector": "#p"},
        "response": {"last_message_selector": ".m", "done_signal": {"type": "stable_text"}},
        "models": [{"id": "web"}],
    }, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return directory


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
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            yield c, app, db, cfg
    finally:
        store.shutdown()


async def _create(client, name="main", **fields):
    return await client.post("/admin/profiles", json={"name": name, **fields})


async def test_create_profile_makes_row_and_directory(client):
    c, app, db, cfg = client
    response = await _create(c, "main", max_tabs=6)
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "main" and body["max_tabs"] == 6
    # Profile đầu tiên phải là mặc định, nếu không router không biết chạy ở đâu.
    assert body["is_default"] == 1
    assert (cfg.profiles_dir / "main").is_dir()

    listing = (await c.get("/admin/profiles")).json()
    assert [p["name"] for p in listing["profiles"]] == ["main"]
    assert listing["profiles"][0]["accounts"] == []


async def test_second_profile_is_not_default(client):
    c, *_ = client
    await _create(c, "main")
    body = (await _create(c, "work")).json()
    assert body["is_default"] == 0


async def test_duplicate_and_invalid_names_rejected(client):
    c, *_ = client
    await _create(c, "main")
    dup = await _create(c, "main")
    assert dup.status_code == 400 and dup.json()["error"]["code"] == "invalid_profile"
    bad = await _create(c, "Main Profile!")
    assert bad.status_code == 400


async def test_patch_updates_fields_and_default(client):
    c, *_ = client
    await _create(c, "main")
    created = (await _create(c, "work")).json()

    patched = await c.patch(f"/admin/profiles/{created['id']}",
                            json={"max_tabs": 2, "headless": False, "is_default": True})
    assert patched.status_code == 200
    body = patched.json()
    assert body["max_tabs"] == 2 and body["headless"] == 0 and body["is_default"] == 1

    # Chỉ một profile được là mặc định.
    listing = (await c.get("/admin/profiles")).json()["profiles"]
    assert sum(p["is_default"] for p in listing) == 1

    # Tra theo tên cũng phải ra đúng hàng đó.
    by_name = await c.patch("/admin/profiles/work", json={"notes": "máy phụ"})
    assert by_name.json()["notes"] == "máy phụ"


async def test_patch_rejects_nonsense_values(client):
    c, *_ = client
    created = (await _create(c, "main")).json()
    for values in ({"viewport": "to-bang-man-hinh"}, {"max_tabs": 999}, {"engine": "firefox"}):
        response = await c.patch(f"/admin/profiles/{created['id']}", json=values)
        assert response.status_code == 400, values


async def test_unknown_profile_404(client):
    c, *_ = client
    assert (await c.patch("/admin/profiles/999", json={"max_tabs": 2})).status_code == 404
    assert (await c.post("/admin/profiles/khong-co/open", json={})).status_code == 404


async def test_delete_refuses_while_a_recipe_uses_the_domain(client):
    c, app, db, cfg = client
    _write_recipe(cfg.recipes_dir)
    created = (await _create(c, "main")).json()
    await c.post(f"/admin/profiles/{created['id']}/accounts",
                 json={"domain": "site.example", "label": "work"})
    # Recipe phải có trong DB thì mới coi là "đang dùng" — import như lúc chạy thật.
    from chat2api.store import importer
    importer.import_all(db, cfg.recipes_dir)

    refused = await c.delete(f"/admin/profiles/{created['id']}")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "profile_in_use"
    assert "sitea" in refused.json()["error"]["message"]

    # Gỡ account ra khỏi profile rồi thì xoá được.
    db.connection().execute("DELETE FROM account WHERE profile_id = ?", (created["id"],))
    db.connection().commit()
    assert (await c.delete(f"/admin/profiles/{created['id']}")).status_code == 200
    assert (await c.get("/admin/profiles")).json()["profiles"] == []


async def test_delete_allowed_when_another_profile_still_serves_the_domain(client):
    """Domain còn account ở profile khác thì recipe vẫn chạy — không được chặn."""
    c, app, db, cfg = client
    _write_recipe(cfg.recipes_dir)
    keep = (await _create(c, "keep")).json()
    drop = (await _create(c, "drop")).json()
    for profile in (keep, drop):
        await c.post(f"/admin/profiles/{profile['id']}/accounts",
                     json={"domain": "site.example", "label": "main"})
    from chat2api.store import importer
    importer.import_all(db, cfg.recipes_dir)

    assert (await c.delete(f"/admin/profiles/{drop['id']}")).status_code == 200
    assert [p["name"] for p in (await c.get("/admin/profiles")).json()["profiles"]] == ["keep"]

    # Còn lại đúng một account cho domain đó -> lúc này mới là chặn thật.
    refused = await c.delete(f"/admin/profiles/{keep['id']}")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "profile_in_use"


async def test_delete_refuses_when_a_recipe_pins_the_profile(client):
    """Recipe ghim thẳng profile thì dù domain còn account khác vẫn phải chặn."""
    c, app, db, cfg = client
    _write_recipe(cfg.recipes_dir)
    keep = (await _create(c, "keep")).json()
    pinned = (await _create(c, "pinned")).json()
    for profile in (keep, pinned):
        await c.post(f"/admin/profiles/{profile['id']}/accounts",
                     json={"domain": "site.example", "label": "main"})
    from chat2api.store import importer
    importer.import_all(db, cfg.recipes_dir)
    conn = db.connection()
    conn.execute("UPDATE recipe SET profile_id = ? WHERE slug = 'sitea'", (pinned["id"],))
    conn.commit()

    refused = await c.delete(f"/admin/profiles/{pinned['id']}")
    assert refused.status_code == 409
    assert "sitea" in refused.json()["error"]["message"]


async def test_add_account_creates_domain_and_shows_in_listing(client):
    c, *_ = client
    created = (await _create(c, "main")).json()
    response = await c.post(f"/admin/profiles/{created['id']}/accounts",
                            json={"domain": "chat.qwen.ai", "label": "codex1"})
    assert response.status_code == 200
    assert response.json()["account"]["host"] == "chat.qwen.ai"

    # Thêm lại đúng nhãn đó không nhân đôi.
    await c.post(f"/admin/profiles/{created['id']}/accounts",
                 json={"domain": "chat.qwen.ai", "label": "codex1"})
    profile = (await c.get("/admin/profiles")).json()["profiles"][0]
    assert [(a["host"], a["label"]) for a in profile["accounts"]] == [("chat.qwen.ai", "codex1")]
    assert profile["domains"] == 1

    domains = (await c.get("/admin/domains")).json()["domains"]
    assert "chat.qwen.ai" in [d["host"] for d in domains]


async def test_add_account_rejects_bad_domain(client):
    c, *_ = client
    created = (await _create(c, "main")).json()
    response = await c.post(f"/admin/profiles/{created['id']}/accounts",
                            json={"domain": "../evil", "label": "x"})
    assert response.status_code == 400


async def test_detect_lists_logged_in_domains_not_yet_declared(client):
    c, app, db, cfg = client
    created = (await _create(c, "main")).json()
    await c.post(f"/admin/profiles/{created['id']}/accounts",
                 json={"domain": "chat.qwen.ai", "label": "codex1"})
    app.state.pool.open_context = lambda name: FakeContext([
        {"domain": ".chat.qwen.ai", "name": "session-id"},
        {"domain": ".gemini.google.com", "name": "__Secure-auth-token"},
        {"domain": ".ads.example", "name": "_ga"},
    ])

    body = (await c.post(f"/admin/profiles/{created['id']}/detect")).json()
    assert body["known"] == ["chat.qwen.ai"]
    # Domain đã khai báo bị loại; cookie đo đạc (_ga) không phải cookie phiên.
    assert body["suggested"] == ["gemini.google.com"]


async def test_detect_requires_an_open_profile(client):
    c, *_ = client
    created = (await _create(c, "main")).json()
    response = await c.post(f"/admin/profiles/{created['id']}/detect")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "profile_not_open"


async def test_domains_endpoint_merges_disk_and_recipes(client):
    c, app, db, cfg = client
    _write_recipe(cfg.recipes_dir)
    app.state.router.reload()
    store_dir = cfg.recipes_dir / ".accounts" / "chat.qwen.ai"
    store_dir.mkdir(parents=True)
    (store_dir / "codex1.json").write_text('{"cookies": [], "origins": []}', encoding="utf-8")

    domains = {d["host"]: d for d in (await c.get("/admin/domains")).json()["domains"]}
    assert domains["site.example"]["recipes"] == ["sitea"]
    assert domains["chat.qwen.ai"]["accounts"] == 1


async def test_rename_is_refused_instead_of_ignored(client):
    c, *_ = client
    created = (await _create(c, "main")).json()
    response = await c.patch(f"/admin/profiles/{created['id']}", json={"name": "khac"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "rename_unsupported"
    # Gửi lại đúng tên cũ thì không sao — UI có thể echo nguyên hàng về.
    same = await c.patch(f"/admin/profiles/{created['id']}", json={"name": "main", "max_tabs": 3})
    assert same.status_code == 200 and same.json()["max_tabs"] == 3
