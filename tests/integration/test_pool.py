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


async def test_drop_context():
    pool = BrowserPool(max_contexts=2)
    await pool.start()
    try:
        first = await pool.context_for("a")

        await pool.drop("a")

        assert pool.size == 0
        second = await pool.context_for("a")
        assert second is not first
    finally:
        await pool.aclose()


async def test_headed_context_uses_separate_browser_only_created_on_demand(monkeypatch):
    # Không mở cửa sổ Chromium thật khi chạy test: fake launch(headless=False)
    # để CI không cần display server.
    pool = BrowserPool(max_contexts=2)
    await pool.start()
    try:
        assert pool._browser_headed is None
        await pool.context_for("a")
        assert pool._browser_headed is None

        launched = []

        class FakeHeadedBrowser:
            async def new_context(self, storage_state=None):
                return object()

            async def close(self):
                pass

        async def fake_launch(headless):
            launched.append(headless)
            return FakeHeadedBrowser()

        monkeypatch.setattr(pool._pw.chromium, "launch", fake_launch)

        await pool.context_for("b", headed=True)
        assert launched == [False]
        assert pool._browser_headed is not None
        assert pool._browser_headed is not pool._browser

        # Context headed thứ 2 tái dùng browser headed đã mở, không launch lại.
        await pool.context_for("c", headed=True)
        assert launched == [False]
    finally:
        await pool.aclose()
