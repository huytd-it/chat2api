"""Trang Integrations gộp: CRUD profile + tự dò domain (pha 5, docs/design-v2.md §6).

Không mở Chromium thật ở đây — phần mở browser đã có test riêng ở
`test_pool_profile.py`. File này kiểm phần API: hàng DB, luật từ chối xoá, và
đường quét cookie của một profile đang mở (context giả).
"""

import json

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from chat2api import store
from chat2api.config import Config
from chat2api.main import create_app


class FakePage:
    """Tab giả cho /open — không mở Chromium thật trong test API."""

    async def goto(self, url, **kwargs):
        return None


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


async def test_scrapling_mode_is_chosen_when_creating_a_profile(client):
    """Form "Tạo profile mới" gửi chế độ Scrapling — mọi lựa chọn phải xuống tới DB."""
    c, *_ = client
    stealthy = (await _create(c, "kin", scrapling_mode="stealthy")).json()
    assert stealthy["scrapling_mode"] == "stealthy"
    # Không chọn thì mặc định là dynamic, không phải NULL.
    assert (await _create(c, "main")).json()["scrapling_mode"] == "dynamic"
    # Và đổi lại được ở form sửa.
    back = await c.patch(f"/admin/profiles/{stealthy['id']}", json={"scrapling_mode": "dynamic"})
    assert back.json()["scrapling_mode"] == "dynamic"
    fetcher = (await _create(c, "http-only", scrapling_mode="fetcher")).json()
    assert fetcher["scrapling_mode"] == "fetcher"


async def test_open_passes_the_profile_mode_to_the_pool(client, monkeypatch):
    c, app, db, cfg = client
    created = (await _create(c, "kin", scrapling_mode="stealthy")).json()
    opened = []

    async def fake_page_for(profile, slug):
        opened.append((profile.name, profile.scrapling_mode, slug))
        return FakePage()

    monkeypatch.setattr(app.state.pool, "page_for", fake_page_for)

    response = await c.post(f"/admin/profiles/{created['id']}/open", json={})

    assert response.status_code == 200, response.text
    assert response.json()["profile"] == "kin"
    # Pool nhận đúng chế độ của hàng DB để chọn StealthySession hay DynamicSession.
    assert opened == [("kin", "stealthy", "__manual__")]


async def test_open_explains_that_a_fetcher_profile_has_no_window(client):
    """fetcher chỉ gửi HTTP: nút Mở phải nói rõ lý do, không phải lỗi 500 chung chung."""
    c, *_ = client
    created = (await _create(c, "http-only", scrapling_mode="fetcher")).json()

    response = await c.post(f"/admin/profiles/{created['id']}/open", json={})

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "no_browser_mode"
    assert "stealthy" in response.json()["error"]["message"]


async def test_patch_rejects_nonsense_values(client):
    c, *_ = client
    created = (await _create(c, "main")).json()
    for values in ({"viewport": "to-bang-man-hinh"}, {"max_tabs": 999}, {"scrapling_mode": "playwright"}):
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


async def test_clone_duplicates_logins_and_accounts_into_a_new_mode(client):
    """Đường "đổi sang stealthy mà vẫn giữ bản dynamic đang chạy tốt"."""
    c, app, db, cfg = client
    source = (await _create(c, "main", scrapling_mode="dynamic", max_tabs=6)).json()
    await c.post(f"/admin/profiles/{source['id']}/accounts",
                 json={"domain": "chat.qwen.ai", "label": "codex1"})
    (cfg.profiles_dir / "main" / "Default").mkdir(parents=True, exist_ok=True)
    (cfg.profiles_dir / "main" / "Default" / "Cookies").write_text("phiên", encoding="utf-8")

    response = await c.post(f"/admin/profiles/{source['id']}/clone",
                            json={"name": "main-stealthy", "scrapling_mode": "stealthy"})

    assert response.status_code == 200, response.text
    copy = response.json()
    assert copy["scrapling_mode"] == "stealthy" and copy["max_tabs"] == 6 and copy["is_default"] == 0
    assert (cfg.profiles_dir / "main-stealthy" / "Default" / "Cookies").read_text(
        encoding="utf-8") == "phiên"

    listing = {p["name"]: p for p in (await c.get("/admin/profiles")).json()["profiles"]}
    assert [(a["host"], a["label"]) for a in listing["main-stealthy"]["accounts"]] == \
        [("chat.qwen.ai", "codex1")]
    # Bản gốc giữ nguyên chế độ lẫn cờ mặc định.
    assert listing["main"]["scrapling_mode"] == "dynamic" and listing["main"]["is_default"] == 1


async def test_clone_refuses_while_the_source_profile_is_open(client):
    c, app, db, cfg = client
    source = (await _create(c, "main")).json()
    # `open_profiles` là property đọc từ đây — giả lập profile đang chạy.
    app.state.pool._profiles["main"] = None

    response = await c.post(f"/admin/profiles/{source['id']}/clone", json={"name": "main-2"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "profile_open"
    assert not (cfg.profiles_dir / "main-2").exists()


async def test_clone_rejects_a_name_already_taken(client):
    c, *_ = client
    source = (await _create(c, "main")).json()
    await _create(c, "work")
    response = await c.post(f"/admin/profiles/{source['id']}/clone", json={"name": "work"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_profile"


async def test_rename_is_refused_instead_of_ignored(client):
    c, *_ = client
    created = (await _create(c, "main")).json()
    response = await c.patch(f"/admin/profiles/{created['id']}", json={"name": "khac"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "rename_unsupported"
    # Gửi lại đúng tên cũ thì không sao — UI có thể echo nguyên hàng về.
    same = await c.patch(f"/admin/profiles/{created['id']}", json={"name": "main", "max_tabs": 3})
    assert same.status_code == 200 and same.json()["max_tabs"] == 3


# ------------------------------------------- mang profile sang máy khác

STATE = {
    "cookies": [{"name": "session-id", "value": "abc", "domain": ".chat.qwen.ai", "path": "/"}],
    "origins": [{"origin": "https://chat.qwen.ai",
                 "localStorage": [{"name": "token", "value": "t"}]}],
}


class ExportContext:
    """Context giả trả về storage_state, như browser thật đã giải mã cookie."""

    async def storage_state(self, **kwargs):
        return STATE


async def _exported(c, app, name="main"):
    source = (await _create(c, name, scrapling_mode="stealthy", max_tabs=6)).json()
    await c.post(f"/admin/profiles/{source['id']}/accounts",
                 json={"domain": "chat.qwen.ai", "label": "codex1"})
    app.state.pool.open_context = lambda _name: ExportContext()
    response = await c.post(f"/admin/profiles/{source['id']}/export")
    assert response.status_code == 200, response.text
    return response.json()


async def test_export_bundles_settings_accounts_and_decrypted_logins(client):
    c, app, db, cfg = client
    bundle = await _exported(c, app)

    assert bundle["format"] == "chat2api-profile" and bundle["version"] == 1
    assert bundle["profile"]["name"] == "main"
    assert bundle["profile"]["scrapling_mode"] == "stealthy" and bundle["profile"]["max_tabs"] == 6
    assert [(a["host"], a["label"]) for a in bundle["accounts"]] == [("chat.qwen.ai", "codex1")]
    assert bundle["storage_state"] == STATE
    # Đường dẫn thư mục và cờ mặc định là chuyện của máy nguồn.
    assert "user_data_dir" not in bundle["profile"] and "is_default" not in bundle["profile"]


async def test_export_opens_a_closed_profile_headless_then_closes_it(client, monkeypatch):
    c, app, db, cfg = client
    source = (await _create(c, "main", headless=False)).json()
    opened, dropped = [], []

    async def fake_context_for_profile(profile):
        opened.append((profile.name, profile.headless))
        return ExportContext()

    async def fake_drop(name):
        dropped.append(name)
        return True

    monkeypatch.setattr(app.state.pool, "context_for_profile", fake_context_for_profile)
    monkeypatch.setattr(app.state.pool, "drop_profile", fake_drop)

    response = await c.post(f"/admin/profiles/{source['id']}/export")

    assert response.status_code == 200, response.text
    assert response.json()["storage_state"] == STATE
    # Không bật cửa sổ lên chỉ để đọc cookie, và không để lại Chromium treo.
    assert opened == [("main", True)] and dropped == ["main"]


async def test_export_of_a_fetcher_profile_falls_back_to_unseeded_state(client):
    """fetcher không mở được browser: gói vẫn mang theo state còn chờ seed."""
    c, app, db, cfg = client
    bundle = await _exported(c, app)
    imported = (await c.post("/admin/profiles/import",
                             json={"bundle": bundle, "name": "http-only"})).json()
    await c.patch(f"/admin/profiles/{imported['id']}", json={"scrapling_mode": "fetcher"})
    app.state.pool.open_context = lambda _name: None

    response = await c.post(f"/admin/profiles/{imported['id']}/export")

    assert response.status_code == 200, response.text
    assert response.json()["storage_state"] == STATE


async def test_import_recreates_the_profile_and_queues_the_logins(client):
    c, app, db, cfg = client
    bundle = await _exported(c, app)

    response = await c.post("/admin/profiles/import", json={"bundle": bundle, "name": "from-pc1"})

    assert response.status_code == 200, response.text
    created = response.json()
    assert created["name"] == "from-pc1" and created["scrapling_mode"] == "stealthy"
    assert created["max_tabs"] == 6 and created["is_default"] == 0
    assert created["imported"] == {"accounts": 1, "cookies": 1, "origins": 1}
    # Thư mục nằm dưới profiles_dir của MÁY NÀY, không phải đường dẫn máy nguồn.
    assert created["user_data_dir"] == str(cfg.profiles_dir / "from-pc1")
    seed = cfg.profiles_dir / "from-pc1" / "chat2api-import-state.json"
    assert json.loads(seed.read_text(encoding="utf-8")) == STATE

    listing = {p["name"]: p for p in (await c.get("/admin/profiles")).json()["profiles"]}
    assert [(a["host"], a["label"]) for a in listing["from-pc1"]["accounts"]] == \
        [("chat.qwen.ai", "codex1")]


async def test_import_keeps_the_original_name_and_becomes_default_on_an_empty_machine(client):
    c, app, db, cfg = client
    bundle = await _exported(c, app)
    source_id = (await c.get("/admin/profiles")).json()["profiles"][0]["id"]
    assert (await c.delete(f"/admin/profiles/{source_id}?purge=true")).status_code == 200

    created = (await c.post("/admin/profiles/import", json={"bundle": bundle})).json()

    assert created["name"] == "main" and created["is_default"] == 1


async def test_import_rejects_a_taken_name_and_foreign_files(client):
    c, app, db, cfg = client
    bundle = await _exported(c, app)

    taken = await c.post("/admin/profiles/import", json={"bundle": bundle})
    assert taken.status_code == 400 and taken.json()["error"]["code"] == "invalid_profile"

    foreign = await c.post("/admin/profiles/import", json={"bundle": {"cookies": []}, "name": "x"})
    assert foreign.status_code == 400
    newer = await c.post("/admin/profiles/import",
                         json={"bundle": {**bundle, "version": 99}, "name": "x"})
    assert newer.status_code == 400
    assert not (cfg.profiles_dir / "x").exists()

    empty = await c.post("/admin/profiles/import", json={})
    assert empty.status_code == 400 and empty.json()["error"]["code"] == "invalid_import"


async def test_import_skips_malformed_accounts(client):
    c, app, db, cfg = client
    bundle = await _exported(c, app)
    bundle["accounts"].append({"host": "../evil", "label": "x"})

    created = (await c.post("/admin/profiles/import",
                            json={"bundle": bundle, "name": "copy"})).json()

    assert created["imported"]["accounts"] == 1


async def test_import_pulls_straight_from_another_machine(client, monkeypatch):
    c, app, db, cfg = client
    bundle = await _exported(c, app)
    calls = []

    async def fake_remote(method, base_url, api_key, path):
        calls.append((method, base_url, api_key, path))
        if path == "/admin/profiles":
            return {"profiles": [{"name": "main", "scrapling_mode": "stealthy", "id": 7,
                                  "user_data_dir": "C:/secret",
                                  "accounts": [{"host": "chat.qwen.ai", "label": "codex1"}]}]}
        return bundle

    monkeypatch.setattr("chat2api.main._remote_json", fake_remote)

    listing = await c.post("/admin/profiles/remote-list",
                           json={"remote_url": "192.168.1.5:8100", "remote_api_key": "k"})
    assert listing.json()["profiles"] == [{
        "name": "main", "scrapling_mode": "stealthy",
        "accounts": [{"host": "chat.qwen.ai", "label": "codex1"}]}]

    response = await c.post("/admin/profiles/import", json={
        "remote_url": "192.168.1.5:8100", "remote_api_key": "k",
        "remote_profile": "main", "name": "pc1-main"})

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "pc1-main"
    assert calls[-1] == ("POST", "192.168.1.5:8100", "k", "/admin/profiles/main/export")
    assert (cfg.profiles_dir / "pc1-main" / "chat2api-import-state.json").is_file()


async def test_unreachable_remote_is_reported_as_a_gateway_error(client):
    c, *_ = client
    response = await c.post("/admin/profiles/remote-list",
                            json={"remote_url": "http://127.0.0.1:9", "remote_api_key": ""})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "remote_unreachable"
