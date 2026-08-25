import pytest

from chat2api.browserpool import BrowserPool
from chat2api.providers.browser_recipe import BrowserRecipe, TrialLimitExceeded, validate_recipe

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

    async def spy(key, storage_state=None, headed=False):
        calls.append(key)
        return await original(key, storage_state, headed=headed)

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

    async def spy(key, storage_state=None, headed=False):
        calls.append(key)
        return await original(key, storage_state, headed=headed)

    monkeypatch.setattr(pool, "context_for", spy)
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        for _ in range(3):
            async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
                pass
        assert calls == ["fixture::a1", "fixture::a1", "fixture::a2"]
    finally:
        await pool.aclose()


async def test_headed_flag_propagates_to_pool_context_for(fixture_recipe, tmp_path, monkeypatch):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    calls = []
    original = pool.context_for

    async def spy(key, storage_state=None, headed=False):
        calls.append(headed)
        # Ghi lại cờ headed nhưng vẫn chạy context thật ở chế độ headless để
        # test không tự mở cửa sổ Chromium hiện ra.
        return await original(key, storage_state, headed=False)

    monkeypatch.setattr(pool, "context_for", spy)
    try:
        provider = BrowserRecipe(fixture_recipe, tmp_path, pool, headed=True)
        async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
            pass
        assert calls == [True]
    finally:
        await pool.aclose()


async def test_per_call_headed_overrides_constructor_default(fixture_recipe, tmp_path, monkeypatch):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    calls = []
    original = pool.context_for

    async def spy(key, storage_state=None, headed=False):
        calls.append(headed)
        return await original(key, storage_state, headed=False)

    monkeypatch.setattr(pool, "context_for", spy)
    try:
        # Provider mặc định headless (như mọi recipe production), nhưng một
        # request cụ thể có thể yêu cầu hiện browser qua tham số stream().
        provider = BrowserRecipe(fixture_recipe, tmp_path, pool, headed=False)
        async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web",
                                            headed=True):
            pass
        async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
            pass
        assert calls == [True, False]
    finally:
        await pool.aclose()


async def test_anon_trial_limit_blocks_after_quota(fixture_recipe, tmp_path):
    recipe = {**fixture_recipe, "login": {"anon_trial_limit": 2}}
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        assert provider.account_count == 0
        for _ in range(2):
            async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
                pass
        assert provider.trial_status == {"limit": 2, "used": 2}
        with pytest.raises(TrialLimitExceeded):
            async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
                pass
    finally:
        await pool.aclose()


async def test_accounts_disable_anon_trial_limit(fixture_recipe, tmp_path):
    (tmp_path / "a1.json").write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    recipe = {**fixture_recipe, "login": {
        "anon_trial_limit": 1,
        "accounts": [{"name": "a1", "storage_state": "a1.json"}],
    }}
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        assert provider.account_count == 1
        assert provider.trial_status is None
        for _ in range(3):
            async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
                pass
    finally:
        await pool.aclose()


def test_validate_recipe_rejects_bad_anon_trial_limit(fixture_recipe):
    bad = {**fixture_recipe, "login": {"anon_trial_limit": -1}}
    errs = validate_recipe(bad)
    assert any("anon_trial_limit" in e for e in errs)


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
