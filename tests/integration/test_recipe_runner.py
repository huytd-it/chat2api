import pytest

from chat2api.browserpool import BrowserPool
from chat2api.providers.browser_recipe import BrowserRecipe

pytest.importorskip("playwright.async_api")


async def test_roundtrip_stream(fixture_recipe, tmp_path):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(fixture_recipe, tmp_path, pool)
        out = []
        async for delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
            out.append(delta)
        assert "".join(out).strip() == "This is the reply."
    finally:
        await pool.aclose()


async def test_multi_account_round_robin_uses_distinct_contexts(fixture_recipe, tmp_path, monkeypatch):
    for name in ("a1", "a2"):
        (tmp_path / f"{name}.json").write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    recipe = {**fixture_recipe, "login": {
        "strategy": "round_robin",
        "accounts": [
            {"name": "a1", "storage_state": "a1.json"},
            {"name": "a2", "storage_state": "a2.json"},
        ],
    }}
    pool = BrowserPool(max_contexts=3)
    await pool.start()
    calls = []
    original = pool.context_for

    async def spy(key, storage_state=None):
        calls.append(key)
        return await original(key, storage_state)

    monkeypatch.setattr(pool, "context_for", spy)
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        for _ in range(3):
            async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
                pass
        assert calls == ["fixture::a1", "fixture::a2", "fixture::a1"]
    finally:
        await pool.aclose()


async def test_multi_account_fill_first_exhausts_quota_before_switching(fixture_recipe, tmp_path,
                                                                         monkeypatch):
    for name in ("a1", "a2"):
        (tmp_path / f"{name}.json").write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    recipe = {**fixture_recipe, "login": {
        "strategy": "fill_first",
        "quota": 2,
        "accounts": [
            {"name": "a1", "storage_state": "a1.json"},
            {"name": "a2", "storage_state": "a2.json"},
        ],
    }}
    pool = BrowserPool(max_contexts=3)
    await pool.start()
    calls = []
    original = pool.context_for

    async def spy(key, storage_state=None):
        calls.append(key)
        return await original(key, storage_state)

    monkeypatch.setattr(pool, "context_for", spy)
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        for _ in range(3):
            async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
                pass
        assert calls == ["fixture::a1", "fixture::a1", "fixture::a2"]
    finally:
        await pool.aclose()


async def test_roundtrip_timeout(fixture_recipe, tmp_path):
    bad = {**fixture_recipe, "response": {**fixture_recipe["response"],
           "last_message_selector": ".does-not-exist",
           "done_signal": {**fixture_recipe["response"]["done_signal"], "timeout_ms": 2000}}}
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(bad, tmp_path, pool)
        with pytest.raises(TimeoutError):
            async for _ in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
                pass
    finally:
        await pool.aclose()
