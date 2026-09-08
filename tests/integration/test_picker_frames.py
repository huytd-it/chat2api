import asyncio
import http.server
import socketserver
import threading
from functools import partial
from pathlib import Path

import pytest

pytest.importorskip("playwright.async_api")

from chat2api.agents.dom import SELECTOR_FN_JS
from chat2api.browserpool import BrowserPool
from chat2api import picker as picker_mod

pytestmark = pytest.mark.asyncio

FIXTURES = Path(__file__).parent / "fixtures"


async def launch(pool: BrowserPool):
    await pool.start()
    # ensure chromium installed; playwright install already done
    ctx = await pool.context_for("picker-test")
    page = await ctx.new_page()
    return pool, page


UNSAFE_PORTS = {
    1,7,9,11,13,15,17,19,20,21,22,23,25,37,42,43,53,77,79,87,95,101,102,103,104,
    109,110,111,113,115,117,119,123,135,139,143,179,389,465,512,513,514,515,526,530,531,532,540,556,
    587,601,636,989,1000,1067,1068,1069,1085,1719,1720,1723,2049,3659,4045,5060,5061,6000,6566,6665,6666,6667,6668,6669,6697,10080,
}

def start_server(directory: Path):
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    for _ in range(20):
        httpd = socketserver.TCPServer(("127.0.0.1", 0), handler, bind_and_activate=False)
        httpd.allow_reuse_address = True
        httpd.server_bind()
        port = httpd.server_address[1]
        if port in UNSAFE_PORTS:
            httpd.server_close()
            continue
        httpd.server_activate()
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd, port
    handler2 = partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler2, bind_and_activate=True)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


async def test_nested_iframe_picker_and_runtime_locator(site):
    """Picker chọn trong iframe lồng nhau, selector frame-chain phải chạy qua BrowserRecipe resolver."""
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        ctx = await pool.context_for("picker-nested")
        page = await ctx.new_page()
        await page.goto(f"{site}/picker_outer.html")
        # wait iframe
        await page.wait_for_timeout(400)

        # evaluate in inner frame directly: enrich should give locator with frame chain
        inner_frame = page.frame_locator("#outer")
        # access element via dom: evaluate inside frame
        enrich_js = """(sel) => {
          """ + SELECTOR_FN_JS + """
          const el = document.getElementById(sel || 'innerBtn');
          if(!el) return null;
          return __c2aEnrich(el);
        }"""
        # Use set_content cross-origin for deterministic same-origin isolation is elsewhere;
        # for normal same-origin outer→inner, frame chain is via frameElement so enrich must contain chain.
        # Instead of relying on page.frames[inner].evaluate (which gives chain from that frame's window,
        # not top's), build locator via explicit frame chain synthesis — the real picker installs in each frame
        # and _resolve_locator is what BrowserRecipe uses at runtime.
        from chat2api.providers.browser_recipe import _resolve_locator
        # synthesize pick as picker would: frame chain + best selector
        # same-origin inner
        locator = "iframe#outer >> #innerBtn"
        loc = _resolve_locator(page, locator)
        c = await loc.count()
        assert c == 1, f"locator {locator!r} count {c}"

        # nested same-origin
        locator2 = "iframe#outer >> iframe#nested >> #deepBtn"
        loc2 = _resolve_locator(page, locator2)
        assert await loc2.count() == 1, f"{locator2!r}"

        # also verify JS enrich inside frames still returns plausible chain for same-origin
        # (get frames by url and eval inside each frame)
        frame = None
        for fr in page.frames:
            if "picker_inner.html" in fr.url:
                frame = fr
                break
        assert frame is not None, f"no inner frame, urls: {[f.url for f in page.frames]}"
        data = await frame.evaluate(enrich_js)
        # inner frame's top-level window == itself, so chain should contain #outer? No — from its window, frameElement is outer.
        # Actually from inner frame's window, frameChain returns ["#outer"]
        assert data.get("frame", {}).get("chain") == ["#outer"], data.get("frame")
        deep_frame = None
        for fr in page.frames:
            if "picker_inner_nested" in fr.url:
                deep_frame = fr
                break
        assert deep_frame is not None
        data2 = await deep_frame.evaluate("""(sel) => {
          """ + SELECTOR_FN_JS + """
          const el = document.getElementById('deepBtn');
          return __c2aEnrich(el);
        }""")
        # deep nested chain should list both ancestors from deepest window perspective
        chain2 = data2.get("frame", {}).get("chain")
        assert chain2 == ["#outer", "#nested"], chain2

        # cross-origin simulation: second server on different port same API but different origin (localhost different port is cross-origin)
        httpd2, port2 = start_server(FIXTURES)
        try:
            cross_url = f"http://127.0.0.1:{port2}/picker_cross_inner.html"
            # create page with cross-origin iframe
            await page.set_content(f'<iframe id="cross" src="{cross_url}" style="width:300px;height:200px"></iframe>')
            await page.wait_for_timeout(600)
            # wait frame
            cross_frame = None
            for _ in range(20):
                for fr in page.frames:
                    if "picker_cross_inner" in fr.url:
                        cross_frame = fr
                        break
                if cross_frame:
                    break
                await page.wait_for_timeout(150)
            assert cross_frame is not None, f"cross frame not found {[f.url for f in page.frames]}"
            enrich_data = await cross_frame.evaluate(enrich_js.replace("innerBtn", "crossBtn"))
            assert enrich_data is not None
            assert enrich_data.get("frame", {}).get("chain") == [], enrich_data.get("frame")
            locator3 = "iframe#cross >> #crossBtn"
            loc3 = _resolve_locator(page, locator3)
            assert await loc3.count() == 1, await loc3.count()
            await loc3.click()
            clicked = await cross_frame.evaluate("() => window.__clicked")
            assert clicked == 1
        finally:
            httpd2.shutdown()

        await page.close()
    finally:
        await pool.aclose()


async def test_open_shadow_picker_pierce_and_duplicate(site):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        ctx = await pool.context_for("picker-shadow")
        page = await ctx.new_page()
        await page.goto(f"{site}/picker_shadow.html")
        # outside vs shadow duplicate
        # plain querySelectorAll would miss shadow
        cnt_plain = await page.evaluate("() => document.querySelectorAll('#shadowBtn').length")
        assert cnt_plain == 0
        # playwright pierces
        cnt_play = await page.locator("#shadowBtn").count()
        assert cnt_play == 1
        # enrich inside shadow root
        enrich_js = """() => {
          """ + SELECTOR_FN_JS + """
          const host = document.getElementById('host');
          const shadow = host.shadowRoot;
          const el = shadow.getElementById('shadowBtn');
          const e = __c2aEnrich(el);
          // also verify candidate counts via pierce
          return e;
        }"""
        data = await page.evaluate(enrich_js)
        assert data is not None
        assert data["shadow"]["depth"] == 1
        assert data["shadow"]["closed"] is False
        # verify pierce counts unique
        # candidates should include at least one unique
        cands = data.get("candidates") or []
        assert any(c.get("unique") for c in cands), cands
        # locator for shadow element should still work via plain count (Playwright pierces open shadow)
        best = data.get("best") or data.get("selector")
        assert best
        assert await page.locator(best).count() == 1
        # nested shadow
        nested_js = """() => {
          """ + SELECTOR_FN_JS + """
          const host2 = document.getElementById('shadowNestedHost');
          const s2 = host2.shadowRoot;
          const innerHost = s2.getElementById('innerHost');
          const s3 = innerHost.shadowRoot;
          const el = s3.getElementById('deepShadowBtn');
          return __c2aEnrich(el);
        }"""
        data2 = await page.evaluate(nested_js)
        assert data2["shadow"]["depth"] >= 1
        assert await page.locator(data2.get("best") or data2["selector"]).count() == 1

        # closed shadow warning
        closed_js = """() => {
          """ + SELECTOR_FN_JS + """
          const host = document.getElementById('closedHost');
          const sh = host.shadowRoot;
          if(!sh) return {closed: 'no-shadowRoot - closed not accessible'};
          const el = sh.getElementById('closedBtn');
          if(!el) return {closed: 'no-el'};
          const e = __c2aEnrich(el);
          return e;
        }"""
        data3 = await page.evaluate(closed_js)
        # closed shadowRoot is not accessible from page main context => sh is null
        assert data3.get("closed") is not None or data3.get("shadow", {}).get("closed") is True or "no-shadowRoot" in str(data3)

        # dynamic replace
        await page.evaluate("() => window.replaceShadowBtn()")
        # new button should still be found
        # old selector "#shadowBtn" via pierce still finds 1 (new)
        assert await page.locator("#shadowBtn").count() == 1

        await page.close()
    finally:
        await pool.aclose()


async def test_picker_safe_click_and_cancel_cleanup(site):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        ctx = await pool.context_for("picker-safe")
        page = await ctx.new_page()
        await page.goto(f"{site}/picker_inner.html")
        frame = None
        for fr in page.frames:
            if "picker_inner" in fr.url:
                frame = fr
                break
        assert frame is not None

        # install picker JS and then simulate capture via evaluate: check that click handler prevents default
        # We test the JS logic: PICKER_JS should have mousedown/click capture with preventDefault
        from chat2api.picker import PICKER_JS
        await page.evaluate(PICKER_JS)
        await frame.evaluate(PICKER_JS)
        # before click, __clicked is 0
        assert await frame.evaluate("() => window.__clicked") == 0
        # Simulate a picker click via JS: call cleanup with enrich result, not actual click event
        # Instead verify that after picker cleanup, listeners removed
        await page.evaluate("() => { try{ window.__c2a_picker && window.__c2a_picker.cleanup(null); }catch(e){} }")
        await frame.evaluate("() => { try{ window.__c2a_picker && window.__c2a_picker.cleanup(null); }catch(e){} }")
        # cleanup should have removed overlay and not leaked highlight
        has_banner = await page.evaluate("() => !!document.getElementById('__c2a_picker_banner')")
        assert has_banner is False
        # clicking after cleanup should still trigger normal click
        await frame.locator("#innerBtn").click()
        assert await frame.evaluate("() => window.__clicked") == 1

        await page.close()
    finally:
        await pool.aclose()


async def test_picker_count_frame_chain_and_normalize(site):
    """count_selector helper supports frame chain via _resolve_locator."""
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        ctx = await pool.context_for("picker-count")
        page = await ctx.new_page()
        await page.goto(f"{site}/picker_outer.html")
        await page.wait_for_timeout(400)

        # simulate PICKERS entry with fake page that has frames
        import asyncio
        pid = "test-count-frame"
        fut = asyncio.get_running_loop().create_future()
        picker_mod.PICKERS[pid] = {"page": page, "profile": "p", "tab_key": "t", "future": fut}
        try:
            # plain
            r1 = await picker_mod.count_selector(None, pid, "#outerOnly")
            assert r1["count"] == 1 and r1["unique"] is True
            # frame chain
            r2 = await picker_mod.count_selector(None, pid, "iframe#outer >> #innerBtn")
            assert r2["count"] == 1 and r2["unique"] is True
            # nested
            r3 = await picker_mod.count_selector(None, pid, "iframe#outer >> iframe#nested >> #deepBtn")
            assert r3["count"] == 1, r3
        finally:
            picker_mod.PICKERS.pop(pid, None)
            fut.cancel() if not fut.done() else None

        # normalize frame/shadow
        raw = {
            "selector": "#innerBtn",
            "candidates": [{"sel": "#innerBtn", "unique": True, "count": 1}],
            "selectors": {"best": "#innerBtn", "locator": "iframe#outer >> #innerBtn"},
            "frame": {"chain": ["#outer"], "url": "https://x"},
            "shadow": {"hostSelector": None, "depth": 0, "closed": False},
            "locator": "iframe#outer >> #innerBtn",
        }
        out = picker_mod._normalize_pick(raw)
        assert out["locator"] == "iframe#outer >> #innerBtn"
        assert out["frame"]["chain"] == ["#outer"]

        await page.close()
    finally:
        await pool.aclose()
