"""Picker count MUST use Playwright locator, not querySelectorAll; TTL/cleanup/hold."""

import asyncio
import pytest

from chat2api import picker as picker_mod


class FakeLocator:
    def __init__(self, sel, table, should_error=False):
        self.sel = sel
        self.table = table
        self.should_error = should_error

    async def count(self):
        if self.should_error or self.sel == "!!!invalid":
            raise Exception("strict mode violation: bad selector")
        return self.table.get(self.sel, 0)


class FakePage:
    def __init__(self, table=None):
        self.table = table or {}
        self._closed = False
        self.locator_calls = []
        self.evaluate_calls = []
        self.url = "https://example.com"

    def is_closed(self):
        return self._closed

    def locator(self, sel):
        self.locator_calls.append(sel)
        should_error = sel == "!!!invalid"
        return FakeLocator(sel, self.table, should_error)

    async def evaluate(self, js, *args):
        self.evaluate_calls.append(js)
        return None

    async def expose_binding(self, *a, **kw):
        return None

    async def goto(self, *a, **kw):
        return None


class FakePool:
    def __init__(self):
        self.pages = {}
        self.closed_tabs = []
        self.holds = []

    async def page_for(self, profile, tab_key):
        key = f"{profile.name}::{tab_key}"
        if key not in self.pages:
            self.pages[key] = FakePage({"#a": 1, ".x": 2, "#unique": 1})
        return self.pages[key]

    async def close_tab(self, profile_name, tab_key):
        self.closed_tabs.append((profile_name, tab_key))
        return True

    def hold(self, profile_name, tab_key):
        # mimic asynccontextmanager
        self.holds.append((profile_name, tab_key))

        class _Hold:
            async def __aenter__(self_inner):
                return None

            async def __aexit__(self_inner, *a):
                return None

        return _Hold()


class FakeProfile:
    def __init__(self, name="default", headless=True):
        self.name = name
        self.headless = headless
        self.user_data_dir = "/tmp/x"
        self.viewport_size = None
        self.user_agent = None
        self.locale = None
        self.timezone = None
        self.proxy = None
        self.id = 1
        self.max_tabs = 8


@pytest.mark.asyncio
async def test_count_uses_locator_not_querySelectorAll():
    page = FakePage({"#a": 1, ".many": 3})
    picker_mod.PICKERS["pid1"] = {"page": page, "profile": "p", "tab_key": "t", "future": asyncio.get_running_loop().create_future()}
    try:
        res = await picker_mod.count_selector(None, "pid1", "#a")
        assert res == {"selector": "#a", "count": 1, "unique": True}
        assert page.locator_calls == ["#a"]
        assert not page.evaluate_calls  # must NOT call evaluate/querySelectorAll
        res2 = await picker_mod.count_selector(None, "pid1", ".many")
        assert res2["count"] == 3 and res2["unique"] is False
    finally:
        picker_mod.PICKERS.pop("pid1", None)


@pytest.mark.asyncio
async def test_count_rejects_shadow_piercing_explicit():
    page = FakePage({})
    picker_mod.PICKERS["pid2"] = {"page": page, "profile": "p", "tab_key": "t", "future": asyncio.get_running_loop().create_future()}
    try:
        with pytest.raises(ValueError, match="shadow|>>>"):
            await picker_mod.count_selector(None, "pid2", "div >>> span")
    finally:
        picker_mod.PICKERS.pop("pid2", None)
    picker_mod.PICKERS["pid2c"] = {"page": page, "profile": "p", "tab_key": "t", "future": asyncio.get_running_loop().create_future()}
    try:
        with pytest.raises(ValueError, match="shadow"):
            await picker_mod.count_selector(None, "pid2c", "shadow=div")
    finally:
        picker_mod.PICKERS.pop("pid2c", None)


@pytest.mark.asyncio
async def test_count_frame_chain_uses_frame_locator():
    # frame chain "iframe#outer >> #innerBtn" should use frame_locator, not plain locator
    class FrameFakePage(FakePage):
        def __init__(self):
            super().__init__({})
            self.frame_locator_calls = []
        def frame_locator(self, sel):
            self.frame_locator_calls.append(sel)
            # return self-like object that has locator
            return self

    page = FrameFakePage()
    page.table["#innerBtn"] = 1
    # override locator to return count based on inner selector
    orig_locator = page.locator
    def patched_locator(sel):
        page.locator_calls.append(sel)
        return FakeLocator(sel, page.table)
    page.locator = patched_locator

    picker_mod.PICKERS["pid2b"] = {"page": page, "profile": "p", "tab_key": "t", "future": asyncio.get_running_loop().create_future()}
    try:
        res = await picker_mod.count_selector(None, "pid2b", "iframe#outer >> #innerBtn")
        assert res["count"] == 1 and res["unique"] is True
        assert "iframe#outer" in page.frame_locator_calls
        assert page.locator_calls == ["#innerBtn"]
    finally:
        picker_mod.PICKERS.pop("pid2b", None)


@pytest.mark.asyncio
async def test_count_invalid_selector_surfaces():
    page = FakePage({})
    picker_mod.PICKERS["pid3"] = {"page": page, "profile": "p", "tab_key": "t", "future": asyncio.get_running_loop().create_future()}
    try:
        with pytest.raises(ValueError, match="invalid selector"):
            await picker_mod.count_selector(None, "pid3", "!!!invalid")
    finally:
        picker_mod.PICKERS.pop("pid3", None)


@pytest.mark.asyncio
async def test_count_wrong_picker_id_cross_session_404():
    with pytest.raises(KeyError):
        await picker_mod.count_selector(None, "no-such-picker", "#a")


@pytest.mark.asyncio
async def test_count_wrong_frame_closed_page():
    page = FakePage({})
    page._closed = True
    picker_mod.PICKERS["pid4"] = {"page": page, "profile": "p", "tab_key": "t", "future": asyncio.get_running_loop().create_future()}
    try:
        with pytest.raises(KeyError):
            await picker_mod.count_selector(None, "pid4", "#a")
    finally:
        picker_mod.PICKERS.pop("pid4", None)


def test_valid_url_helper():
    assert picker_mod._valid_url("") is True
    assert picker_mod._valid_url("https://example.com/chat") is True
    assert picker_mod._valid_url("http://localhost:3000") is True
    assert picker_mod._valid_url("javascript:alert(1)") is False
    assert picker_mod._valid_url("ftp://x") is False
    assert picker_mod._valid_url("not a url") is False


def test_split_frame_selector():
    assert picker_mod._split_frame_selector("") == ([], "")
    assert picker_mod._split_frame_selector("#a") == ([], "#a")
    assert picker_mod._split_frame_selector("iframe#outer >> #inner") == (["iframe#outer"], "#inner")
    assert picker_mod._split_frame_selector("iframe#o >> iframe#i >> #btn") == (["iframe#o", "iframe#i"], "#btn")
    # legacy token
    assert picker_mod._split_frame_selector("iframe#o >> internal:control=enter-frame >> #btn") == (["iframe#o"], "#btn")


def test_normalize_pick_frame_and_locator():
    raw = {
        "selector": "#btn",
        "candidates": [{"sel": "#btn", "unique": True, "count": 1}],
        "selectors": {"best": "#btn", "locator": "iframe#outer >> #btn"},
        "frame": {"chain": ["iframe#outer"], "url": "https://x"},
        "shadow": {"hostSelector": None, "depth": 0, "closed": False},
        "locator": "iframe#outer >> #btn",
    }
    out = picker_mod._normalize_pick(raw)
    assert out["locator"] == "iframe#outer >> #btn"
    assert out["frame"]["chain"] == ["iframe#outer"]


def test_normalize_pick_closed_shadow_warning():
    raw = {"selector": "#a", "candidates": [], "shadow": {"closed": True}, "frame": {}}
    out = picker_mod._normalize_pick(raw)
    assert "warning" in out


@pytest.mark.asyncio
async def test_stop_releases_hold_and_closes_tab(monkeypatch):
    # Setup a picker with hold_ctx
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    page = FakePage({})
    closed = {}

    class Hold:
        entered = False
        exited = False

        async def __aenter__(self):
            Hold.entered = True

        async def __aexit__(self, *a):
            Hold.exited = True

    hold = Hold()
    picker_mod.PICKERS["pid5"] = {"page": page, "profile": "prof1", "tab_key": "__picker__pid5", "future": fut, "hold_ctx": hold, "ttl_task": None}

    class Pool:
        async def close_tab(self, prof, key):
            closed["args"] = (prof, key)

    ok = await picker_mod.stop_picker(Pool(), "pid5")
    assert ok is True
    assert closed["args"] == ("prof1", "__picker__pid5")
    assert Hold.exited is True
    assert "pid5" not in picker_mod.PICKERS
