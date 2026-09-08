"""Real Chromium picker integration: start_picker -> click -> capture_pick.

Covers:
- actual hosted HTTP fixtures (site fixture)
- cross-origin iframe frame.chain via authoritative Python derivation
- duplicate shadow/main ID distinction via pierce counts
- safe pointerdown/mousedown/click blocking (site handler not triggered)
- cancel/escape cleanup, dynamic iframe navigation, stop cleanup
"""

import asyncio
import http.server
import socketserver
import threading
from functools import partial
from pathlib import Path

import pytest

pytest.importorskip("playwright.async_api")

from chat2api import picker as picker_mod
from chat2api.browserpool import BrowserPool
from chat2api.selectors import FRAME_TOKEN

pytestmark = pytest.mark.asyncio

FIXTURES = Path(__file__).parent / "fixtures"


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


class StubCfg:
    def __init__(self, profiles_dir: Path):
        self.profiles_dir = profiles_dir
        self.recipes_dir = profiles_dir


class StubPoolAdapter:
    """Adapter that implements page_for/close_tab/hold needed by picker."""

    def __init__(self, real_pool: BrowserPool):
        self._pool = real_pool

    async def page_for(self, profile, tab_key):
        return await self._pool.page_for(profile, tab_key)

    async def close_tab(self, profile_name, tab_key):
        return await self._pool.close_tab(profile_name, tab_key)

    def hold(self, *a, **kw):
        return self._pool.hold(*a, **kw)


async def _setup_profile(tmp_path):
    from chat2api import profiles, store
    s = store.connect(tmp_path / "picker_real.db")
    s.migrate()
    prof = profiles.ensure_profile("picker-real", tmp_path / "profiles")
    assert prof is not None
    return prof, s


async def test_real_picker_nested_and_cross_origin_capture(site, tmp_path):
    # use BrowserPool directly for chromium, but picker needs profile holder
    real_pool = BrowserPool(max_contexts=2, max_profiles=2)
    await real_pool.start()
    try:
        prof, _ = await _setup_profile(tmp_path)
        cfg = StubCfg(tmp_path / "profiles")
        adapter = StubPoolAdapter(real_pool)
        # ensure contexts: use pool.profile path for picker, but also need real page
        info = await picker_mod.start_picker(adapter, prof.name, f"{site}/picker_outer.html", cfg)
        pid = info["picker_id"]
        try:
            page = picker_mod.PICKERS[pid]["page"]
            await page.wait_for_timeout(500)
            # click nested deepBtn via frame locator (authoritative path)
            from chat2api.selectors import resolve_locator
            # need to ensure picker overlay does not block real click? We use locator click on target directly via page, picker captures
            # Simulate user click: click the deepBtn element inside nested iframe via evaluate click dispatch
            # Find deep frame
            deep_frame = None
            for fr in page.frames:
                if "picker_inner_nested" in fr.url:
                    deep_frame = fr
                    break
            assert deep_frame is not None, [f.url for f in page.frames]
            # Trigger picker capture by dispatching click event on that element (picker listens capture)
            await deep_frame.evaluate("""() => {
                const el=document.getElementById('deepBtn');
                if(!el) throw new Error('no deepBtn');
                el.dispatchEvent(new MouseEvent('pointerdown', {bubbles:true, cancelable:true}));
                el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true}));
                el.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
            }""")
            result = await picker_mod.capture_pick(None, pid, timeout=10)
            loc = result.get("locator") or result.get("best") or ""
            assert FRAME_TOKEN in loc or "deepBtn" in loc or "deep" in loc, loc
            assert "deepBtn" in loc or "#deepBtn" in loc or 'data-testid="deep"' in loc or "data-testid" in loc
            # Verify count via runtime resolver
            cnt = await picker_mod.count_selector(None, pid, loc)
            assert cnt["count"] == 1

            # second pick: cross-origin iframe dynamic add
            httpd2, port2 = start_server(FIXTURES)
            try:
                cross_url = f"http://127.0.0.1:{port2}/picker_cross_inner.html"
                await page.evaluate(f"""(url) => {{
                    const f=document.createElement('iframe');
                    f.id='cross2'; f.src=url; f.style.width='300px'; f.style.height='200px';
                    document.body.appendChild(f);
                }}""", cross_url)
                await page.wait_for_timeout(800)
                cross_frame = None
                for _ in range(20):
                    for fr in page.frames:
                        if "picker_cross_inner" in fr.url:
                            cross_frame = fr
                            break
                    if cross_frame:
                        break
                    await page.wait_for_timeout(150)
                assert cross_frame is not None
                # need to ensure picker installed in new frame (nav handler should have)
                await page.wait_for_timeout(400)
                await cross_frame.evaluate("""() => {
                    const el=document.getElementById('crossBtn');
                    el.dispatchEvent(new MouseEvent('pointerdown', {bubbles:true, cancelable:true}));
                    el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true}));
                    el.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
                }""")
                result2 = await picker_mod.capture_pick(None, pid, timeout=10)
                loc2 = result2.get("locator") or ""
                # authoritatively derived chain must contain cross frame selector
                assert "cross" in loc2.lower() and "crossBtn" in loc2, loc2
                cnt2 = await picker_mod.count_selector(None, pid, loc2)
                assert cnt2["count"] == 1
                # ensure site click not double-triggered
                clicked = await cross_frame.evaluate("() => window.__clicked || 0")
                assert clicked == 0, "picker should block site click"
            finally:
                httpd2.shutdown()
        finally:
            await picker_mod.stop_picker(adapter, pid)
            assert pid not in picker_mod.PICKERS
            has_banner = await page.evaluate("() => !!document.getElementById('__c2a_picker_banner')") if not page.is_closed() else False
            assert has_banner is False
    finally:
        await real_pool.aclose()


async def test_real_picker_shadow_duplicate_and_safe_gesture(site, tmp_path):
    real_pool = BrowserPool(max_contexts=1)
    await real_pool.start()
    try:
        prof, _ = await _setup_profile(tmp_path)
        cfg = StubCfg(tmp_path / "profiles")
        adapter = StubPoolAdapter(real_pool)
        info = await picker_mod.start_picker(adapter, prof.name, f"{site}/picker_shadow.html", cfg)
        pid = info["picker_id"]
        try:
            page = picker_mod.PICKERS[pid]["page"]
            await page.wait_for_timeout(400)
            # hover not needed; directly click shadow button via dispatch inside shadow
            await page.evaluate("""() => {
                const host=document.getElementById('host');
                const el=host.shadowRoot.getElementById('shadowBtn');
                el._pd=0; el._md=0; el._cl=0;
                el.addEventListener('pointerdown', ()=>el._pd++, true);
                el.addEventListener('mousedown', ()=>el._md++, true);
                el.addEventListener('click', ()=>el._cl++, true);
                // dispatch via shadow host? use element's dispatch
                el.dispatchEvent(new MouseEvent('pointerdown', {bubbles:true, cancelable:true, composed:true}));
                el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, composed:true}));
                el.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, composed:true}));
            }""")
            res = await picker_mod.capture_pick(None, pid, timeout=10)
            # shadow depth should be >=1
            assert res.get("shadow", {}).get("depth") >= 1
            loc = res.get("locator") or res.get("best")
            assert loc
            cnt = await picker_mod.count_selector(None, pid, loc)
            assert cnt["count"] == 1
            # safe: site counters should be 0 because picker blocks
            counters = await page.evaluate("""() => {
                const host=document.getElementById('host');
                const el=host.shadowRoot.getElementById('shadowBtn');
                return {pd: el._pd||0, md: el._md||0, cl: el._cl||0};
            }""")
            assert counters["pd"] == 0 and counters["md"] == 0 and counters["cl"] == 0, counters

            # cancel path: start second pick then cancel via Escape/key dispatch
            await page.evaluate("""() => {
                // re-armed already, now send Escape
                document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true}));
            }""")
            # capture should raise timeout/cancel
            with pytest.raises(TimeoutError):
                await picker_mod.capture_pick(None, pid, timeout=2)

            # after cancel, overlay gone but picker still held? capture after cancel should timeout; stop will cleanup
            has = await page.evaluate("() => !!document.getElementById('__c2a_picker_banner')")
            assert has is False
        finally:
            await picker_mod.stop_picker(adapter, pid)
    finally:
        await real_pool.aclose()


async def test_real_picker_stop_and_ttl_no_self_cancel(site, tmp_path):
    real_pool = BrowserPool(max_contexts=1)
    await real_pool.start()
    try:
        prof, _ = await _setup_profile(tmp_path)
        cfg = StubCfg(tmp_path / "profiles")
        adapter = StubPoolAdapter(real_pool)
        info = await picker_mod.start_picker(adapter, prof.name, f"{site}/picker_inner.html", cfg)
        pid = info["picker_id"]
        page = picker_mod.PICKERS[pid]["page"]
        # trigger dynamic iframe navigation replace
        await page.evaluate("""() => {
            const f=document.createElement('iframe');
            f.id='dyn'; f.src='about:blank';
            document.body.appendChild(f);
        }""")
        await page.wait_for_timeout(400)
        # stop should not deadlock via canceling current task
        ok = await picker_mod.stop_picker(adapter, pid)
        assert ok is True
        assert pid not in picker_mod.PICKERS
    finally:
        await real_pool.aclose()
