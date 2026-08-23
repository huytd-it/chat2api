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
