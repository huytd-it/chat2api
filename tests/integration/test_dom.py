import pytest

pytest.importorskip("playwright.async_api")

from chat2api.agents.dom import snapshot
from chat2api.browserpool import BrowserPool


async def test_snapshot_finds_prompt_box(site):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        ctx = await pool.context_for("domtest")
        page = await ctx.new_page()
        await page.goto(f"{site}/chat.html")
        snap = await snapshot(page)
        assert "#prompt" in snap and "textarea" in snap
        await page.close()
    finally:
        await pool.aclose()
