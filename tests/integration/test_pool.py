import pytest

from chat2api.browserpool import BrowserPool

pytest.importorskip("playwright.async_api")


async def test_context_reuse_and_eviction():
    pool = BrowserPool(max_contexts=2)
    await pool.start()
    try:
        c1 = await pool.context_for("a")
        c2 = await pool.context_for("a")
        assert c1 is c2
        await pool.context_for("b")
        await pool.context_for("c")  # evict "a"
        assert pool.size <= 2
        assert c1 not in list(pool._contexts.values())
    finally:
        await pool.aclose()
