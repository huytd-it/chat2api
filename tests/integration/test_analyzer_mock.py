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


async def test_authenticated_trial_is_isolated_then_atomically_published(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from chat2api.agents import analyzer

    recipes_dir = tmp_path / "recipes"
    final_dir = recipes_dir / "example"
    staging_state = recipes_dir / ".login" / "job" / "auth" / "state.json"
    staging_state.parent.mkdir(parents=True)
    staging_state.write_text("job-marker", encoding="utf-8")
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
            observed["slug"] = recipe["slug"]
            observed["base_dir"] = base_dir
            observed["state"] = (base_dir / recipe["login"]["storage_state"]).read_text()
            assert not final_dir.exists()
        async def stream(self, messages, model_id):
            yield "OK"

    async def no_login(page): return False
    async def snapshot(page): return "dom"

    monkeypatch.setattr(analyzer.llm, "chat_json", fake_chat_json)
    monkeypatch.setattr(analyzer.dom, "snapshot", snapshot)
    monkeypatch.setattr(analyzer, "_looks_like_login", no_login)
    monkeypatch.setattr(analyzer, "BrowserRecipe", FakeBrowserRecipe)
    pool = Pool()
    result = await analyzer.integrate(
        "https://example.test/chat", pool, cfg, lambda message: None,
        storage_state=staging_state, analyze_key="job__analyze",
        publish_lock=asyncio.Lock(),
    )

    saved = yaml.safe_load((final_dir / "recipe.yaml").read_text(encoding="utf-8"))
    assert result == {"status": "ok", "slug": "example", "model_id": "example/web"}
    assert observed == {"slug": "trial-job-analyze", "base_dir": staging_state.parents[1], "state": "job-marker"}
    assert (final_dir / "auth" / "state.json").read_text() == "job-marker"
    assert saved["slug"] == "example"
    assert saved["login"]["storage_state"] == "auth/state.json"
    assert pool.dropped == ["trial-job-analyze", "example", "trial-job-analyze"]


async def test_failed_authenticated_trial_leaves_final_bytes_unchanged(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from chat2api.agents import analyzer

    recipes_dir = tmp_path / "recipes"
    final_dir = recipes_dir / "example"
    (final_dir / "auth").mkdir(parents=True)
    recipe_path = final_dir / "recipe.yaml"
    state_path = final_dir / "auth" / "state.json"
    recipe_path.write_bytes(b"old-recipe")
    state_path.write_bytes(b"old-state")
    staged = recipes_dir / ".login" / "job" / "auth" / "state.json"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"new-state")
    cfg = SimpleNamespace(recipes_dir=recipes_dir, integrate_max_rounds=1)

    async def fake_chat_json(*args, **kwargs):
        return {"recipe_yaml": """slug: example\nurl: https://example.test/chat\nprompt:\n  input_selector: '#p'\nresponse:\n  last_message_selector: '.m'\n  done_signal:\n    type: stable_text\nmodels:\n  - id: web\n"""}
    class Page:
        url = "https://example.test/chat"
        async def goto(self, *args, **kwargs): ...
        async def close(self): ...
    class Pool:
        def __init__(self): self.dropped = []
        async def context_for(self, *args): return self
        async def new_page(self): return Page()
        async def drop(self, key): self.dropped.append(key)
    class FailingRecipe:
        def __init__(self, *args): ...
        async def stream(self, *args):
            if False:
                yield None
            raise RuntimeError("trial failed")

    monkeypatch.setattr(analyzer.llm, "chat_json", fake_chat_json)
    monkeypatch.setattr(analyzer.dom, "snapshot", lambda page: _async_value("dom"))
    monkeypatch.setattr(analyzer, "_looks_like_login", lambda page: _async_value(False))
    monkeypatch.setattr(analyzer, "BrowserRecipe", FailingRecipe)
    pool = Pool()
    result = await analyzer.integrate("https://example.test/chat", pool, cfg, lambda _: None,
                                      staged, "job", asyncio.Lock())
    assert result["status"] == "failed"
    assert recipe_path.read_bytes() == b"old-recipe"
    assert state_path.read_bytes() == b"old-state"
    assert pool.dropped == ["trial-job", "trial-job"]


async def test_concurrent_authenticated_publication_separates_hosts_and_state(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from chat2api.agents import analyzer

    recipes_dir = tmp_path / "recipes"
    cfg = SimpleNamespace(recipes_dir=recipes_dir, integrate_max_rounds=1)
    states = {}
    for job, marker in (("job-a", "marker-a"), ("job-b", "marker-b")):
        state = recipes_dir / ".login" / job / "auth" / "state.json"
        state.parent.mkdir(parents=True)
        state.write_text(marker)
        states[job] = state
    barrier = asyncio.Barrier(2)
    trial_slugs = set()

    async def fake_chat_json(cfg, system, user, timeout=180):
        host = "foo.com" if "foo.com" in user else "foo.org"
        return {"recipe_yaml": f"""slug: foo\nurl: https://{host}/chat\nprompt:\n  input_selector: '#p'\nresponse:\n  last_message_selector: '.m'\n  done_signal:\n    type: stable_text\nmodels:\n  - id: web\n"""}

    class Page:
        def __init__(self, url): self.url = url
        async def goto(self, url, **kwargs): self.url = url
        async def close(self): ...
    class Context:
        def __init__(self, url): self.url = url
        async def new_page(self): return Page(self.url)
    class Pool:
        def __init__(self): self.dropped = []
        async def context_for(self, key, storage_state=None):
            host = "foo.com" if "job-a" in key else "foo.org"
            return Context(f"https://{host}/chat")
        async def drop(self, key): self.dropped.append(key)
    class Recipe:
        def __init__(self, recipe, base_dir, pool):
            trial_slugs.add(recipe["slug"])
            self.marker = (base_dir / recipe["login"]["storage_state"]).read_text()
        async def stream(self, *args):
            await barrier.wait()
            yield "OK"

    monkeypatch.setattr(analyzer.llm, "chat_json", fake_chat_json)
    monkeypatch.setattr(analyzer.dom, "snapshot", lambda page: _async_value("dom"))
    monkeypatch.setattr(analyzer, "_looks_like_login", lambda page: _async_value(False))
    monkeypatch.setattr(analyzer, "BrowserRecipe", Recipe)
    pool = Pool()
    lock = asyncio.Lock()
    results = await asyncio.gather(*(
        analyzer.integrate(f"https://foo.{tld}/chat", pool, cfg, lambda _: None,
                           states[job], f"{job}__analyze", lock)
        for job, tld in (("job-a", "com"), ("job-b", "org"))
    ))

    assert {result["slug"] for result in results} == {"foo", "foo-2"}
    assert trial_slugs == {"trial-job-a-analyze", "trial-job-b-analyze"}
    published = {
        yaml.safe_load((recipes_dir / slug / "recipe.yaml").read_text())["url"]:
        (recipes_dir / slug / "auth" / "state.json").read_text()
        for slug in ("foo", "foo-2")
    }
    assert published == {
        "https://foo.com/chat": "marker-a",
        "https://foo.org/chat": "marker-b",
    }


async def _async_value(value):
    return value
