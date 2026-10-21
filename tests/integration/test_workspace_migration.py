"""Contract coverage for retiring the duplicate UI/admin surface."""
import pytest

from chat2api import store


@pytest.fixture
async def workspace_client(app_client, tmp_path):
    db = store.connect(tmp_path / "workspace.db")
    db.migrate()
    try:
        yield app_client, db
    finally:
        store.shutdown()


async def test_old_admin_surface_is_not_in_openapi(app_client):
    paths = (await app_client.get("/openapi.json")).json()["paths"]
    retired = ("/admin/recipes", "/admin/flows", "/admin/test-targets",
               "/admin/integrate", "/admin/record", "/admin/traces")
    assert not [p for p in paths if any(p == old or p.startswith(old + "/") for old in retired)]
    for path in retired:
        assert (await app_client.get(path)).status_code == 404
    assert "/admin/automations/{slug}/source" in paths
    assert "/admin/automation-jobs/record/{job_id}/trace.json" in paths
    assert "/admin/automation-targets" in paths
    assert "/v1/chat/completions" in paths
    assert "/v1/images/generations" in paths


async def test_custom_website_identity_survives_alias_rename_without_database_mutation(workspace_client):
    client, db = workspace_client
    now = store.now_ms()
    with db.connection() as conn:
        conn.execute("INSERT INTO recipe(slug,kind,url,enabled,created_at,updated_at) "
                     "VALUES('private-site','browser','https://private.example/chat',0,?,?)", (now, now))
        conn.execute("INSERT INTO session(id,title,kind,model_public_id,created_at,updated_at) "
                     "VALUES('private-history','saved','chat','private-site/original-model',?,?)", (now, now))
    sites = (await client.get("/admin/websites")).json()["websites"]
    custom = next(s for s in sites if s["url"] == "https://private.example")
    assert custom["id"].startswith("custom-")
    assert custom["runtime"] == "not_configured"
    assert custom["operations"] == []
    configs = (await client.get("/admin/automations", params={"site": custom["id"]})).json()
    assert configs[0]["slug"] == "private-site"
    assert configs[0]["loaded"] is False
    assert configs[0]["enabled"] is False
    source = await client.get("/admin/automations/private-site/source")
    assert source.status_code == 200
    assert source.json()["read_only"] is True
    scoped = (await client.get("/admin/sessions", params={"site": custom["id"]})).json()["sessions"]
    assert [s["id"] for s in scoped] == ["private-history"]
    with db.connection() as conn:
        conn.execute("UPDATE recipe SET slug='private-renamed' WHERE slug='private-site'")
    renamed = (await client.get("/admin/websites")).json()["websites"]
    assert next(s for s in renamed if s["url"] == custom["url"])["id"] == custom["id"]
    assert db.query("SELECT enabled FROM recipe WHERE slug='private-renamed'")[0]["enabled"] == 0


async def test_scope_validation_for_configuration_and_accounts(workspace_client):
    client, _ = workspace_client
    assert (await client.get("/admin/automations?site=unknown")).status_code == 404
    assert (await client.get("/admin/automation-targets?site=unknown")).status_code == 404
    assert (await client.get("/admin/automations?site=minimax")).json() == []
    assert (await client.get("/admin/automation-targets?site=minimax")).json()["targets"] == []


async def test_builtin_website_aliases_remain_in_catalog(workspace_client):
    client, db = workspace_client
    now = store.now_ms()
    with db.connection() as conn:
        for slug, url in (("chat", "https://chat.qwen.ai/"), ("gemini-2", "https://gemini.google.com/"), ("grok", "https://grok.com/")):
            conn.execute("INSERT INTO recipe(slug,kind,url,created_at,updated_at) VALUES(?,'browser',?,?,?)", (slug, url, now, now))
    catalog = {s["id"]: s for s in (await client.get("/admin/websites")).json()["websites"]}
    assert "chat" in catalog["qwen"]["history_slugs"]
    assert "gemini-2" in catalog["gemini"]["history_slugs"]
    assert "grok" in catalog["grok"]["history_slugs"]


async def test_domain_registration_is_idempotent_and_does_not_publish_models(workspace_client):
    client, db = workspace_client
    before = (await client.get("/v1/models")).json()
    result = await client.post("/admin/websites", json={"domain": "Chat.New-Example.COM"})
    assert result.status_code == 200
    created = result.json()
    assert created["created"] is True
    repeated = (await client.post("/admin/websites", json={"domain": "https://chat.new-example.com/"})).json()
    assert repeated["id"] == created["id"]
    assert repeated["created"] is False
    assert len(db.query("SELECT * FROM website")) == 1
    assert not db.query("SELECT * FROM recipe")
    site = next(s for s in (await client.get("/admin/websites")).json()["websites"] if s["id"] == created["id"])
    assert site["models"] == []
    assert site["operations"] == []
    assert site["runtime"] == "not_configured"
    assert (await client.get("/v1/models")).json() == before
    brief = await client.post(f"/admin/websites/{site['id']}/agent-brief", json={"requirement": "Upload file và giữ context riêng"})
    assert brief.status_code == 200
    assert "Upload file và giữ context riêng" in brief.json()["brief"]
    assert "https://chat.new-example.com" in brief.json()["brief"]
    assert "docs/website-agent-cli.md" in brief.json()["brief"]
    assert not db.query("SELECT * FROM recipe")


async def test_registering_builtin_domain_does_not_duplicate_module(workspace_client):
    client, db = workspace_client
    result = (await client.post("/admin/websites", json={"domain": "chat.qwen.ai"})).json()
    assert result["id"] == "qwen"
    assert result["created"] is False
    assert db.query("SELECT * FROM website") == []


async def test_registered_domain_survives_store_reopen(workspace_client, tmp_path):
    client, _ = workspace_client
    result = (await client.post("/admin/websites", json={"domain": "persist.example"})).json()
    store.shutdown()
    db = store.connect(tmp_path / "workspace.db")
    db.migrate()
    sites = (await client.get("/admin/websites")).json()["websites"]
    assert any(s["id"] == result["id"] and s["url"] == "https://persist.example" for s in sites)


async def test_upgrade_creates_registration_table_without_changing_recipes(workspace_client):
    _, db = workspace_client
    with db.connection() as conn:
        conn.execute("DROP TABLE website")
        conn.execute("DELETE FROM schema_migrations WHERE version=10")
    assert db.migrate() >= 10
    assert db.query("SELECT id FROM website") == []


@pytest.mark.parametrize("domain", ["", "https://x.example/path", "https://user:secret@x.example", "http://x.example", "x.example?token=x", "x.example:8443", "x.example;whoami", "x.example\ny.example"])
async def test_domain_registration_rejects_non_domain_input(workspace_client, domain):
    client, db = workspace_client
    result = await client.post("/admin/websites", json={"domain": domain})
    assert result.status_code in (400, 422)
    assert not db.query("SELECT * FROM website")
