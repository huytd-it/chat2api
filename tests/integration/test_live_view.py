import asyncio

import pytest

from chat2api import live_view
from chat2api.browserpool import BrowserPool
from chat2api.providers.browser_recipe import BrowserRecipe

pytest.importorskip("playwright.async_api")


class FakePage:
    def __init__(self, data: bytes = b"fake-jpeg-bytes"):
        self._data = data

    async def screenshot(self, **kwargs):
        return self._data


async def test_register_then_screenshot_returns_bytes():
    page = FakePage()
    await live_view.register("w1", page)
    assert await live_view.screenshot("w1") == b"fake-jpeg-bytes"


async def test_screenshot_missing_watch_id_returns_none():
    assert await live_view.screenshot("does-not-exist") is None


async def test_unregister_only_removes_matching_page():
    page_a, page_b = FakePage(b"a"), FakePage(b"b")
    await live_view.register("w2", page_a)
    # Một page mới (vd trial run) đã chiếm chỗ — unregister của page cũ
    # không được phép xóa nhầm entry hiện tại.
    await live_view.register("w2", page_b)
    await live_view.unregister("w2", page_a)
    assert await live_view.screenshot("w2") == b"b"
    await live_view.unregister("w2", page_b)
    assert await live_view.screenshot("w2") is None


async def test_screenshot_swallows_page_errors():
    class FailingPage:
        async def screenshot(self, **kwargs):
            raise RuntimeError("page closed")

    await live_view.register("w3", FailingPage())
    assert await live_view.screenshot("w3") is None


async def test_watch_endpoint_404_when_not_registered(app_client):
    r = await app_client.get("/admin/watch/nope/screenshot")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_watch_endpoint_returns_jpeg_bytes(app_client):
    page = FakePage(b"\xff\xd8fake")
    try:
        await live_view.register("watch-test", page)
        r = await app_client.get("/admin/watch/watch-test/screenshot")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/jpeg"
        assert r.content == b"\xff\xd8fake"
    finally:
        await live_view.unregister("watch-test", page)


async def test_stream_registers_and_unregisters_real_page(fixture_recipe, tmp_path):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(fixture_recipe, tmp_path, pool)
        gen = provider.stream([{"role": "user", "content": "hi"}], "fixture-web",
                              watch_id="live-w")
        await gen.__anext__()  # đợi tới khi ít nhất 1 delta được yield — page đã mở
        shot = await live_view.screenshot("live-w")
        assert shot is not None and shot.startswith(b"\xff\xd8")  # JPEG magic bytes
        async for _ in gen:
            pass
        assert await live_view.screenshot("live-w") is None
    finally:
        await pool.aclose()
