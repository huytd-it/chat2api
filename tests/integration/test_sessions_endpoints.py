import json

import pytest

from chat2api import sessions, store


@pytest.fixture
async def session_client(app_client, tmp_path):
    db = store.connect(tmp_path / "sessions.db")
    db.migrate()
    try:
        yield app_client, db
    finally:
        store.shutdown()


async def _chat(client, text="Xin chào", session_id=None, stream=False):
    headers = {"X-Chat2api-Session-Id": session_id} if session_id else {}
    return await client.post("/v1/chat/completions", headers=headers, json={
        "model": "fake/m1",
        "messages": [{"role": "user", "content": text}],
        "stream": stream,
    })


async def test_non_stream_creates_session_messages_and_request_log(session_client):
    client, db = session_client
    response = await _chat(client)
    assert response.status_code == 200
    session_id = response.headers["X-Chat2api-Session-Id"]

    detail = (await client.get(f"/admin/sessions/{session_id}")).json()
    assert detail["title"] == "Xin chào"
    assert detail["kind"] == "api"
    assert detail["model_public_id"] == "fake/m1"
    assert [(m["role"], m["content"]) for m in detail["messages"]] == [
        ("user", "Xin chào"), ("assistant", "Hello world")]
    assert detail["messages"][1]["request"]["status"] == "ok"
    assert detail["messages"][1]["request"]["completion_chars"] == 11
    assert detail["message_count"] == 2
    assert db.query("SELECT COUNT(*) AS n FROM request_log")[0]["n"] == 1


async def test_target_metadata_is_stored_on_session(session_client):
    _, db = session_client
    now = store.now_ms()
    conn = db.connection()
    with conn:
        profile_id = conn.execute(
            "INSERT INTO profile(name, user_data_dir, created_at) VALUES ('target', '', ?)",
            (now,)).lastrowid
        domain_id = conn.execute(
            "INSERT INTO domain(host, created_at) VALUES ('example.com', ?)", (now,)).lastrowid
        account_id = conn.execute(
            "INSERT INTO account(profile_id, domain_id, label, created_at) "
            "VALUES (?, ?, 'main', ?)", (profile_id, domain_id, now)).lastrowid
    recording = sessions.begin(
        "target-session", "fake/m1", "fake", [{"role": "user", "content": "test"}],
        False, account_id=account_id, profile_id=profile_id)
    row = db.query(
        "SELECT account_id, profile_id FROM session WHERE id = 'target-session'")[0]
    assert (row["account_id"], row["profile_id"]) == (account_id, profile_id)


async def test_explicit_header_continues_same_session_without_duplicate_history(session_client):
    client, _ = session_client
    first = await _chat(client, "Lượt một", "desktop-session-1")
    assert first.headers["X-Chat2api-Session-Id"] == "desktop-session-1"

    second = await client.post("/v1/chat/completions", headers={
        "X-Chat2api-Session-Id": "desktop-session-1",
    }, json={
        "model": "fake/m1",
        "messages": [
            {"role": "user", "content": "Lượt một"},
            {"role": "assistant", "content": "Hello world"},
            {"role": "user", "content": "Lượt hai"},
        ],
    })
    assert second.status_code == 200
    detail = (await client.get("/admin/sessions/desktop-session-1")).json()
    assert [(m["seq"], m["role"], m["content"]) for m in detail["messages"]] == [
        (0, "user", "Lượt một"),
        (1, "assistant", "Hello world"),
        (2, "user", "Lượt hai"),
        (3, "assistant", "Hello world"),
    ]


async def test_stream_persists_once_after_done_and_returns_header(session_client):
    client, db = session_client
    response = await _chat(client, "Stream", "desktop-stream", stream=True)
    assert response.status_code == 200
    assert response.headers["X-Chat2api-Session-Id"] == "desktop-stream"
    assert "data: [DONE]" in response.text
    messages = db.query("SELECT role, content FROM message ORDER BY seq")
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "Stream"), ("assistant", "Hello world")]
    assert db.query("SELECT status FROM request_log")[0]["status"] == "ok"


async def test_stream_error_persists_partial_reply_and_error(session_client):
    from chat2api.providers.base import ModelInfo, Provider

    class Broken(Provider):
        slug = "broken-session"

        def models(self):
            return [ModelInfo(id="broken-session/m1", slug=self.slug)]

        async def stream(self, messages, model_id):
            yield "một phần"
            raise TimeoutError("quá hạn")

    client, db = session_client
    client._transport.app.state.router.providers["broken-session"] = Broken()
    response = await client.post("/v1/chat/completions", json={
        "model": "broken-session/m1",
        "messages": [{"role": "user", "content": "test"}],
        "stream": True,
    })
    assert response.status_code == 200
    row = db.query("SELECT content, error, finish_reason FROM message WHERE role='assistant'")[0]
    assert row["content"] == "một phần"
    assert row["error"] and row["finish_reason"] == "error"
    request = db.query("SELECT status, error_code FROM request_log")[0]
    assert (request["status"], request["error_code"]) == ("timeout", "recipe_timeout")


async def test_list_search_patch_archive_delete(session_client):
    client, _ = session_client
    await _chat(client, "Thành phố Hồ Chí Minh", "manage-session")

    found = (await client.get("/admin/sessions", params={"q": "Ho Chi Minh"})).json()
    assert [item["id"] for item in found["sessions"]] == ["manage-session"]

    updated = (await client.patch("/admin/sessions/manage-session", json={
        "title": "Phiên đã đổi tên", "pinned": True, "tags": ["việt nam", "debug"],
    })).json()
    assert updated["title"] == "Phiên đã đổi tên" and updated["pinned"] == 1
    assert updated["tags"] == ["debug", "việt nam"]

    await client.patch("/admin/sessions/manage-session", json={"archived": True})
    assert (await client.get("/admin/sessions")).json()["sessions"] == []
    archived = (await client.get("/admin/sessions", params={"archived": True})).json()
    assert archived["sessions"][0]["id"] == "manage-session"

    assert (await client.delete("/admin/sessions/manage-session")).json() == {"ok": True}
    assert (await client.get("/admin/sessions/manage-session")).status_code == 404


async def test_bulk_and_all_session_delete(session_client):
    client, _ = session_client
    for session_id in ("bulk-session-1", "bulk-session-2", "bulk-session-3"):
        await _chat(client, session_id, session_id=session_id)

    before = (await client.get("/admin/sessions")).json()["sessions"]
    assert {item["id"] for item in before} == {
        "bulk-session-1", "bulk-session-2", "bulk-session-3"}

    response = await client.request(
        "DELETE", "/admin/sessions", json={"ids": ["bulk-session-1", "bulk-session-3"]},
    )
    assert response.json() == {"ok": True, "deleted": 2}
    assert [item["id"] for item in (await client.get("/admin/sessions")).json()["sessions"]] == [
        "bulk-session-2"]

    response = await client.request("DELETE", "/admin/sessions", json={"all": True})
    assert response.json() == {"ok": True, "deleted": 1}
    assert (await client.get("/admin/sessions")).json()["sessions"] == []


async def test_fork_and_all_export_formats(session_client):
    client, _ = session_client
    await _chat(client, "Tạo nhánh", "fork-source")
    forked = (await client.post("/admin/sessions/fork-source/fork", json={"up_to_seq": 0})).json()
    assert forked["id"] != "fork-source"
    assert [(m["seq"], m["role"]) for m in forked["messages"]] == [(0, "user")]

    for fmt, content_type in {
        "md": "text/markdown",
        "html": "text/html",
        "json": "application/json",
        "jsonl": "application/x-ndjson",
    }.items():
        response = await client.get(f"/admin/sessions/fork-source/export?format={fmt}")
        assert response.status_code == 200
        assert content_type in response.headers["content-type"]
        assert "attachment" in response.headers["content-disposition"]
    parsed = json.loads((await client.get(
        "/admin/sessions/fork-source/export?format=json"
    )).text)
    assert parsed["id"] == "fork-source"


async def test_code_fence_becomes_artifact(session_client):
    client, db = session_client

    class CodeProvider:
        slug = "code"

        def models(self):
            from chat2api.providers.base import ModelInfo
            return [ModelInfo(id="code/m1", slug="code")]

        async def stream(self, messages, model_id):
            yield "```python\nprint('ok')\n```"

    client._transport.app.state.router.providers["code"] = CodeProvider()
    await client.post("/v1/chat/completions", json={
        "model": "code/m1", "messages": [{"role": "user", "content": "code"}],
    })
    artifact = db.query("SELECT kind, language, body FROM artifact")[0]
    assert tuple(artifact) == ("code", "python", "print('ok')")


def test_browser_reply_capture_html_is_opt_in(tmp_path):
    from chat2api.providers.browser_recipe import BrowserRecipe

    class Page:
        def __init__(self):
            self.args = None
            self.script = None

        async def evaluate(self, script, args):
            self.script = script
            self.args = args
            return ["text", "<div>text</div>" if args[1] else None]

    recipe = {
        "slug": "capture", "url": "https://example.com",
        "prompt": {"input_selector": "textarea"},
        "response": {"last_message_selector": ".reply", "capture_html": True,
                     "done_signal": {"type": "stable_text"}},
        "models": [{"id": "m1"}],
    }
    provider = BrowserRecipe(recipe, tmp_path, pool=None)
    page = Page()

    import asyncio
    assert asyncio.run(provider._reply(page)) == ("text", "<div>text</div>")
    assert page.args == [".reply", True, False]
    assert "qwen-markdown-paragraph" in page.script
    assert 'if (tag === "hr") return "---\\n\\n"' in page.script
    assert 'const marker = tag === "ol" ? `${index + 1}.` : "-"' in page.script
