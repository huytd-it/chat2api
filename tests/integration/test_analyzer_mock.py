from pathlib import Path

import pytest
import yaml

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


async def test_resumed_analyzer_copies_auth_before_final_slug_trial(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from chat2api.agents import analyzer

    recipes_dir = tmp_path / "recipes"
    existing = recipes_dir / "example"
    existing.mkdir(parents=True)
    (existing / "recipe.yaml").write_text(
        "slug: example\nurl: https://other.test\n", encoding="utf-8"
    )
    staging_state = recipes_dir / ".login" / "job" / "auth" / "state.json"
    staging_state.parent.mkdir(parents=True)
    staging_state.write_text('{"cookies": [{"name": "session"}]}', encoding="utf-8")
    cfg = SimpleNamespace(recipes_dir=recipes_dir, integrate_max_rounds=1)
    recipe_yaml = """
slug: example
url: https://example.test/chat
prompt:
  input_selector: '#prompt'
response:
  last_message_selector: '.message'
  done_signal:
    type: stable_text
models:
  - id: web
"""

    async def fake_chat_json(*args, **kwargs):
        return {"recipe_yaml": recipe_yaml}

    class Page:
        url = "https://example.test/chat"
        async def goto(self, *args, **kwargs): ...
        async def close(self): ...
        def locator(self, selector):
            return SimpleNamespace(count=lambda: None)

    class Context:
        async def new_page(self):
            return Page()

    class Pool:
        def __init__(self):
            self.dropped = []
        async def context_for(self, key, storage_state=None):
            assert key == "job__analyze"
            assert storage_state == staging_state
            return Context()
        async def drop(self, key):
            self.dropped.append(key)

    observed = {}

    class FakeBrowserRecipe:
        def __init__(self, recipe, base_dir, pool):
            observed["recipe"] = dict(recipe)
            observed["base_dir"] = base_dir
            final_state = base_dir / recipe["login"]["storage_state"]
            observed["state_at_init"] = final_state.read_text(encoding="utf-8")
        async def stream(self, messages, model_id):
            yield "OK"

    async def no_login(page):
        return False

    async def snapshot(page):
        return "dom"

    monkeypatch.setattr(analyzer.llm, "chat_json", fake_chat_json)
    monkeypatch.setattr(analyzer.dom, "snapshot", snapshot)
    monkeypatch.setattr(analyzer, "_looks_like_login", no_login)
    monkeypatch.setattr(analyzer, "BrowserRecipe", FakeBrowserRecipe)
    pool = Pool()

    result = await analyzer.integrate(
        "https://example.test/chat", pool, cfg, lambda message: None,
        storage_state=staging_state, analyze_key="job__analyze"
    )

    final_dir = recipes_dir / "example-2"
    saved = yaml.safe_load((final_dir / "recipe.yaml").read_text(encoding="utf-8"))
    assert result == {"status": "ok", "slug": "example-2", "model_id": "example-2/web"}
    assert observed["base_dir"] == final_dir
    assert observed["recipe"]["slug"] == "example-2"
    assert observed["recipe"]["login"]["storage_state"] == "auth/state.json"
    assert observed["state_at_init"] == staging_state.read_text(encoding="utf-8")
    assert pool.dropped == ["example-2"]
    assert saved["slug"] == "example-2"
    assert saved["login"]["storage_state"] == "auth/state.json"
