import pytest

pytest.importorskip("playwright.async_api")

from chat2api.agents.analyzer import integrate
from chat2api.browserpool import BrowserPool


async def test_analyzer_success_with_mock_llm(site, tmp_path, monkeypatch):
    from chat2api.config import Config

    recipe_yaml = f"""
slug: fixturesite
url: {site}/chat.html
prompt:
  input_selector: "#prompt"
  input_mode: fill
  submit: "click:#send"
response:
  last_message_selector: ".msg"
  done_signal:
    type: stable_text
    quiet_ms: 500
    timeout_ms: 8000
models:
  - id: web
"""
    async def fake_chat_json(cfg, system, user, timeout=180):
        assert "#prompt" in user or "Lần" in user
        return {"recipe_yaml": recipe_yaml}

    import chat2api.agents.llm as llm_mod
    monkeypatch.setattr(llm_mod, "chat_json", fake_chat_json)

    cfg = Config()
    cfg.recipes_dir = tmp_path / "recipes"
    cfg.recipes_dir.mkdir()
    cfg.integrate_max_rounds = 3

    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        logs = []
        result = await integrate(f"{site}/chat.html", pool, cfg, logs.append)
        assert result["status"] == "ok", (result, logs)
        assert (tmp_path / "recipes" / "fixturesite" / "recipe.yaml").exists()
    finally:
        await pool.aclose()


async def test_analyzer_login_required(tmp_path, monkeypatch):
    from chat2api.agents import analyzer
    from chat2api.config import Config

    cfg = Config()
    cfg.recipes_dir = tmp_path

    async def fake_chat_json(cfg, system, user, timeout=180):
        raise AssertionError("không cần LLM khi phát hiện login")

    monkeypatch.setattr(analyzer.llm, "chat_json", fake_chat_json)

    class FakeLocator:
        async def count(self):
            return 0

    class FakePage:
        url = "https://accounts.google.com/signin"

        async def goto(self, *a, **kw): ...
        async def close(self): ...

        def locator(self, sel):
            return FakeLocator()

    class FakePool:
        async def context_for(self, slug, storage_state=None):
            return self

        async def new_page(self):
            return FakePage()

    result = await analyzer.integrate("https://accounts.google.com/x",
                                      FakePool(), cfg, lambda m: None)
    assert result["status"] == "login_required"
