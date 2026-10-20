"""Durable browser-session HTTP contract, retry journal and media persistence.

Chạy bằng provider giả kế thừa ``BrowserRecipe`` để không mở Chromium: phần cần
kiểm là journal/HTTP, không phải selector của website thật.
"""
import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def durable(tmp_path):
    from chat2api import profiles, store
    from chat2api.providers.browser_recipe import AccountLimitExceeded, Assignment, BrowserRecipe

    db = store.connect(tmp_path / "durable.db")
    db.migrate()

    accounts = []
    for name, label in (("alpha", "one"), ("beta", "two")):
        profile = profiles.ensure_profile(name, tmp_path / "profiles")
        account = profiles.add_account(profile.id, "example.com", label)
        accounts.append((account["id"], profile.id, name))

    class DurableProvider(BrowserRecipe):
        slug = "durable"
        supports_attachments = True

        def __init__(self):
            super().__init__({
                "slug": "durable", "url": "https://example.com/chat",
                "models": [{"id": "m1"}],
                "flows": {"image": {"type": "image",
                                    "response": {"media_selector": "img.generated"}}},
            }, Path("."), None)

        def models(self):
            from chat2api.providers.base import ModelInfo
            return [ModelInfo(id="durable/m1", slug=self.slug),
                    ModelInfo(id="durable/image", slug=self.slug, capability="image")]

        def supports_image(self):
            return True

        def resolve_headed(self, headed, profile):
            return headed

        async def assign(self, target_account_id=None, *, sticky_key="", exclude=None):
            from chat2api import account_limits as limits
            exclude = set(exclude or ())
            for index, (account_id, profile_id, name) in enumerate(accounts):
                if target_account_id is not None and account_id != target_account_id:
                    continue
                item = Assignment(self, f"ctx-{index}", account_id=account_id,
                                  account_label=("one" if index == 0 else "two"),
                                  profile_id=profile_id, profile_name=name,
                                  host="example.com",
                                  profile=SimpleNamespace(name=name))
                if limits.db_key(account_id) in exclude:
                    continue
                return item
            raise AccountLimitExceeded("all", "quota", recipe_slug=self.slug)

        async def stream(self, messages, model_id, headed=None, assignment=None, **kwargs):
            from chat2api.automation import journal
            from chat2api.automation.service import current_turn
            turn = current_turn.get()
            self.calls.append({
                "account_id": assignment.account_id,
                "messages": messages,
                "resume_url": turn.conversation_url if turn else None,
                "project_url": turn.project_url if turn else None,
            })
            if self.fail_first and assignment.account_id == accounts[0][0]:
                self.fail_first = False
                raise AccountLimitExceeded("all", "quota", recipe_slug=self.slug)
            url = f"https://example.com/c/{assignment.account_id}-{len(self.calls)}"
            if turn is not None:
                turn.conversation_url = url
                await asyncio.to_thread(
                    journal.bind, turn.session_id, assignment.account_id, url)
            yield "ok"

        async def generate_images(self, prompt, n=1, size="1024x1024", **kwargs):
            self.image_calls.append(prompt)
            return [{"b64_json": base64.b64encode(PNG).decode("ascii")} for _ in range(n)]

        calls = None
        image_calls = None
        fail_first = False

    provider = DurableProvider()
    provider.calls = []
    provider.image_calls = []
    yield db, provider, accounts, AccountLimitExceeded
    store.shutdown()


async def test_idempotent_replay_and_two_books_stay_separate(app_client, durable):
    _, provider, _, _ = durable
    app_client._transport.app.state.router.providers["durable"] = provider

    first = {"model": "durable/m1", "session_id": "book-a", "request_id": "a1",
             "messages": [{"role": "user", "content": "alpha"}]}
    r1 = await app_client.post("/v1/chat/completions", json=first)
    assert r1.status_code == 200
    assert r1.json()["chat2api"]["successful_requests"] == 1

    # Gửi lại đúng operation: trả journal, không gõ prompt lần hai.
    r2 = await app_client.post("/v1/chat/completions", json=first)
    assert r2.status_code == 200
    assert r2.json()["choices"][0]["message"]["content"] == "ok"
    assert len(provider.calls) == 1

    # Ebook thứ hai bắt đầu ở context trống, không thấy URL của ebook A.
    r3 = await app_client.post("/v1/chat/completions", json={
        "model": "durable/m1", "session_id": "book-b", "request_id": "b1",
        "messages": [{"role": "user", "content": "beta"}]})
    assert r3.status_code == 200
    assert provider.calls[1]["resume_url"] is None

    # Lượt tiếp theo của A nối đúng hội thoại A, không phải B.
    r4 = await app_client.post("/v1/chat/completions", json={
        "model": "durable/m1", "session_id": "book-a", "request_id": "a2",
        "messages": [{"role": "user", "content": "alpha 2"}]})
    assert r4.status_code == 200
    assert provider.calls[2]["resume_url"] == "https://example.com/c/1-1"
    assert r4.json()["chat2api"]["successful_requests"] == 2


async def test_rollover_requires_policy_and_clears_remote_context(app_client, durable):
    _, provider, _, _ = durable
    app_client._transport.app.state.router.providers["durable"] = provider

    base = {"model": "durable/m1", "session_id": "roll", "max_session_requests": 1}
    r1 = await app_client.post("/v1/chat/completions", json={
        **base, "request_id": "r1", "messages": [{"role": "user", "content": "one"}]})
    assert r1.status_code == 200

    r2 = await app_client.post("/v1/chat/completions", json={
        **base, "request_id": "r2", "messages": [{"role": "user", "content": "two"}]})
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "rollover_policy_required"

    r3 = await app_client.post("/v1/chat/completions", json={
        **base, "request_id": "r2-new", "rollover_policy": "new_context",
        "messages": [{"role": "user", "content": "two"}]})
    assert r3.status_code == 200
    assert r3.json()["chat2api"]["generation"] == 1
    assert r3.json()["chat2api"]["context_reset"] is True
    # Lượt rollover mở context mới, không resume hội thoại cũ.
    assert provider.calls[-1]["resume_url"] is None


async def test_account_failover_keeps_files_and_does_not_replay_history(
        app_client, durable, monkeypatch, tmp_path):
    db, provider, accounts, _ = durable
    app_client._transport.app.state.router.providers["durable"] = provider
    provider.fail_first = True

    from chat2api.automation import journal, projects

    conn = journal.connection()
    with conn:
        conn.execute("INSERT INTO automation_project(id,recipe_slug,active_account_id,title,updated_at) "
                     "VALUES('book-project','durable',?,'Book',1)", (accounts[0][0],))
        conn.execute("INSERT INTO automation_project_copy"
                     "(project_id,account_id,remote_url,instructions,files,source_complete,state) "
                     "VALUES('book-project',?,'https://example.com/project','dịch sát nghĩa','[]',1,'ready')",
                     (accounts[0][0],))
    cloned = []

    async def fake_clone(provider_, project_id, account_id, headed=None):
        cloned.append((project_id, account_id))
        return "https://example.com/project-2"

    monkeypatch.setattr(projects, "clone_to", fake_clone)

    r = await app_client.post("/v1/chat/completions", json={
        "model": "durable/m1", "session_id": "failover", "request_id": "f1",
        "project_id": "book-project",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "dịch chương 1"},
            {"type": "file", "file": {"filename": "source.txt",
                                      "file_data": "data:text/plain;base64,"
                                                   + base64.b64encode(b"noi dung").decode()}},
        ]}],
    }, headers={"X-Chat2api-Headed": "true"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chat2api"]["generation"] == 1
    assert body["chat2api"]["account_id"] == accounts[1][0]
    assert cloned == [("book-project", accounts[1][0])]

    assert len(provider.calls) == 2
    # Lần thử lại trên account mới: file vẫn còn, nhưng không resume hội thoại
    # của account cũ và nhận project URL của bản sao mới.
    retry = provider.calls[1]
    assert retry["account_id"] == accounts[1][0]
    assert retry["resume_url"] is None
    assert retry["project_url"] == "https://example.com/project-2"
    assert retry["messages"][0]["attachments"][0].data == b"noi dung"
    state = journal.get_session("failover")
    assert state["successes"] == 1 and state["account_id"] == accounts[1][0]


async def test_generated_image_is_saved_and_downloadable(app_client, durable):
    _, provider, accounts, _ = durable
    app_client._transport.app.state.router.providers["durable"] = provider

    r = await app_client.post("/v1/images/generations", json={
        "model": "durable/image", "prompt": "a red dot", "response_format": "url"},
        headers={"X-Chat2api-Account-Id": str(accounts[0][0])})
    assert r.status_code == 200, r.text
    item = r.json()["data"][0]
    assert item["image_id"] > 0
    assert item["url"].startswith("http://t/v1/images/")

    download = await app_client.get(item["url"])
    assert download.status_code == 200
    assert download.content == PNG
    assert download.headers["content-type"].startswith("image/png")

    session_id = item["url"].split("/")[-2]
    detail = await app_client.get(f"/admin/sessions/{session_id}")
    message = detail.json()["messages"][-1]
    assert message["attachments"][0]["kind"] == "image"
    assert message["attachments"][0]["bytes"] == len(PNG)


# 1x1 PNG trong suốt — đủ để kiểm magic bytes/mime và đường tải file.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
