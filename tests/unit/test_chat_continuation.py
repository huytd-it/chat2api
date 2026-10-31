"""Tab web chat giữ nguyên giữa các request: nối tiếp hội thoại tới đủ N lượt,
rồi bấm New Chat — chỉ tải lại trang khi tab chưa mở site hoặc lạc trang."""

import asyncio

from chat2api.providers.browser_recipe import BrowserRecipe

RECIPE = {
    "slug": "conttest",
    "url": "https://chat.example.com/",
    "prompt": {"input_selector": "textarea"},
    "response": {"last_message_selector": ".reply", "done_signal": {"type": "stable_text"}},
    "models": [{"id": "m1"}],
    "new_chat": {"selector": "button.new", "every": 3},
    "timing": {"ready_delay_ms": 0, "input_delay_ms": 0},
}


class FakeLocator:
    def __init__(self, page, sel):
        self.page, self.sel = page, sel

    @property
    def first(self):
        return self

    async def click(self, timeout=None):
        self.page.clicks.append(self.sel)

    async def wait_for(self, state="visible", timeout=None):
        if not self.page.url.startswith("https://chat.example.com"):
            raise TimeoutError("box not visible")


class FakePage:
    def __init__(self):
        self.url = "about:blank"
        self.gotos: list[str] = []
        self.clicks: list[str] = []

    def locator(self, sel):
        return FakeLocator(self, sel)

    async def goto(self, url, **kw):
        self.gotos.append(url)
        self.url = url


def _run(provider, page, n, **kw):
    async def go():
        results = []
        box = page.locator("textarea")
        for _ in range(n):
            results.append(await provider._open_chat(page, box, "k", 60000, **kw))
            provider._count_chat_turn("k")
        return results
    return asyncio.run(go())


def test_continues_then_clicks_new_chat_without_reload(tmp_path):
    provider = BrowserRecipe(RECIPE, tmp_path, pool=None)
    page = FakePage()
    continued = _run(provider, page, 7)
    # Lần đầu goto (+ bấm New Chat như cũ, cho site tự mở lại chat cũ); lượt 2-3
    # nối tiếp; lượt 4 bấm New Chat; 5-6 nối tiếp; 7 bấm.
    assert continued == [False, True, True, False, True, True, False]
    assert page.gotos == ["https://chat.example.com/"]
    assert page.clicks == ["button.new"] * 3


def test_error_forces_new_chat_on_next_request(tmp_path):
    provider = BrowserRecipe(RECIPE, tmp_path, pool=None)
    page = FakePage()
    _run(provider, page, 1)
    provider._end_chat("k")
    assert _run(provider, page, 1) == [False]
    assert page.clicks == ["button.new"] * 2 and len(page.gotos) == 1


def test_durable_session_does_not_join_plain_conversation(tmp_path):
    provider = BrowserRecipe(RECIPE, tmp_path, pool=None)
    page = FakePage()
    _run(provider, page, 1)
    assert _run(provider, page, 1, owner="sess-1", fresh=True) == [False]
    assert page.clicks == ["button.new"] * 2
    # Request thường sau đó cũng không nối vào hội thoại của session bền vững.
    assert _run(provider, page, 1) == [False]


def test_resume_url_already_open_skips_goto(tmp_path):
    provider = BrowserRecipe(RECIPE, tmp_path, pool=None)
    page = FakePage()
    page.url = "https://chat.example.com/c/123"
    _run(provider, page, 1, target_url="https://chat.example.com/c/123?x=1", owner="s")
    assert page.gotos == []


def test_every_one_means_new_chat_each_request(tmp_path):
    provider = BrowserRecipe({**RECIPE, "new_chat": {"selector": "button.new", "every": 1}},
                             tmp_path, pool=None)
    page = FakePage()
    assert _run(provider, page, 3) == [False, False, False]
    assert len(page.gotos) == 1 and len(page.clicks) == 3


def test_default_turns_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAT_TURNS_PER_CONVERSATION", "10")
    provider = BrowserRecipe({**RECIPE, "new_chat": {"selector": "button.new"}}, tmp_path, pool=None)
    assert provider._turns_per_chat == 10
