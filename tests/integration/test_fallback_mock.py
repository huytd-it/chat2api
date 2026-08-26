import pytest

pytest.importorskip("playwright.async_api")

from pathlib import Path

from chat2api.agents.fallback import run
from chat2api.browserpool import BrowserPool
from chat2api.config import Config


async def test_fallback_scripted(site):
    actions = [
        {"action": "fill", "selector": "#prompt", "text": "Reply with exactly: OK"},
        {"action": "click", "selector": "#send"},
        {"action": "wait_text"},
        {"done": True, "answer": "This is the reply."},
    ]
    calls = {"n": 0}

    async def fake_chat_json(cfg, system, user, timeout=180):
        i = min(calls["n"], len(actions) - 1)
        calls["n"] += 1
        assert "#prompt" in user  # có DOM snapshot
        return actions[i]

    import chat2api.agents.llm as llm_mod
    monkey_llm = llm_mod
    orig = monkey_llm.chat_json

    async def patched(cfg_, system, user, timeout=180):
        return await fake_chat_json(cfg_, system, user, timeout)

    from chat2api.agents import fallback as fb
    fb.llm.chat_json = patched
    try:
        cfg = Config()
        pool = BrowserPool(max_contexts=1)
        await pool.start()
        try:
            out = []
            logs = []
            async for d in run(f"{site}/chat.html",
                               [{"role": "user", "content": "hi"}],
                               pool, cfg, logs.append):
                out.append(d)
            assert "".join(out).strip() == "This is the reply."
            assert any("[fallback" not in l for l in logs)
        finally:
            await pool.aclose()
    finally:
        fb.llm.chat_json = orig


async def test_unhealthy_recipe_routes_to_fallback(app_client, monkeypatch):
    app = app_client._transport.app

    # main.py fallback_ok yêu cầu isinstance BrowserRecipe → fake phải kế thừa
    from chat2api.providers.browser_recipe import BrowserRecipe

    class FakeRecipeProvider(BrowserRecipe):
        slug = "broken"

        def __init__(self):
            super().__init__({"slug": "broken", "url": "http://127.0.0.1:9/nothing"},
                             Path("."), None)

        def models(self):
            from chat2api.providers.base import ModelInfo
            return [ModelInfo(id="broken/m1", slug="broken")]

        async def stream(self, messages, model_id, headed=None):
            raise TimeoutError("recipe 'broken' timeout")
            yield ""

    provider = FakeRecipeProvider()
    app.state.router.providers["broken"] = provider
    for _ in range(3):
        app.state.router.mark_failure("broken")  # unhealthy

    cfg = app.state.cfg
    cfg.enable_fallback = True

    from chat2api.agents import fallback as fb

    async def fake_run(url, messages, pool, cfg_, log):
        assert url == provider.url
        yield "saved by agent"

    monkeypatch.setattr(fb, "run", fake_run)

    # llm.configured phải trả True để nhánh fallback được phép chạy
    import chat2api.agents.llm as llm_mod
    monkeypatch.setattr(llm_mod, "configured", lambda cfg_: True)

    r = await app_client.post("/v1/chat/completions", json={
        "model": "broken/m1", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "saved by agent"


async def test_unhealthy_recipe_routes_to_real_fallback_run(app_client, monkeypatch, site):
    # Không mock fallback.run: bug "log = [...]" (list, không phải callable) chỉ lộ ra
    # khi fallback.run() thật sự chạy và gọi log(...) bên trong.
    from chat2api.providers.browser_recipe import BrowserRecipe

    class FakeRecipeProvider(BrowserRecipe):
        slug = "broken2"

        def __init__(self):
            super().__init__({"slug": "broken2", "url": f"{site}/chat.html"},
                             Path("."), None)

        def models(self):
            from chat2api.providers.base import ModelInfo
            return [ModelInfo(id="broken2/m1", slug="broken2")]

        async def stream(self, messages, model_id, headed=None):
            raise TimeoutError("recipe 'broken2' timeout")
            yield ""

    app = app_client._transport.app
    provider = FakeRecipeProvider()
    app.state.router.providers["broken2"] = provider
    for _ in range(3):
        app.state.router.mark_failure("broken2")

    cfg = app.state.cfg
    cfg.enable_fallback = True

    async def fake_chat_json(cfg_, system, user, timeout=180):
        return {"done": True, "answer": "This is the reply."}

    import chat2api.agents.llm as llm_mod
    from chat2api.agents import fallback as fb
    monkeypatch.setattr(llm_mod, "configured", lambda cfg_: True)
    monkeypatch.setattr(fb.llm, "chat_json", fake_chat_json)

    await app.state.pool.start()
    try:
        r = await app_client.post("/v1/chat/completions", json={
            "model": "broken2/m1", "messages": [{"role": "user", "content": "hi"}]})
    finally:
        await app.state.pool.aclose()
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "This is the reply."


async def test_recipe_error_without_fallback_is_504(app_client):
    app = app_client._transport.app
    app.state.cfg.enable_fallback = False

    class Boom:
        slug = "boom"

        def models(self):
            from chat2api.providers.base import ModelInfo
            return [ModelInfo(id="boom/m1", slug="boom")]

        async def stream(self, messages, model_id):
            raise TimeoutError("timeout")
            yield ""

    app.state.router.providers["boom"] = Boom()
    r = await app_client.post("/v1/chat/completions", json={
        "model": "boom/m1", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 504
    assert r.json()["error"]["code"] == "recipe_timeout"
