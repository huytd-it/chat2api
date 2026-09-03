"""`_reply` không được để một lần điều hướng giết cả request.

dola đổi URL ba lần ngay sau khi gửi prompt (/chat?channel=g -> /chat/local_… ->
/chat/<id>), đúng lúc vòng poll đang gọi `_reply` mỗi 500ms. Trước đây
`page.evaluate` ném "Execution context was destroyed" và lỗi đó xuyên thẳng ra
ngoài — log production có đúng dòng này với slug dola.
"""

import asyncio

import pytest

from chat2api.providers.browser_recipe import BrowserRecipe

RECIPE = {
    "slug": "navtest",
    "url": "https://example.com",
    "prompt": {"input_selector": "textarea"},
    "response": {
        "last_message_selector": ".reply",
        "done_signal": {"type": "stable_text"},
    },
    "models": [{"id": "m1"}],
}


class NavigatingPage:
    """Ném lỗi điều hướng ở `fail_on` lần gọi đầu, sau đó trả lời bình thường."""

    def __init__(self, fail_on: int):
        self.fail_on = fail_on
        self.calls = 0

    async def evaluate(self, script, args):
        self.calls += 1
        if self.calls <= self.fail_on:
            raise Exception(
                "Page.evaluate: Execution context was destroyed, "
                "most likely because of a navigation")
        return ["Xin chào bạn", None]


def test_navigation_error_returns_none_not_empty_string(tmp_path):
    provider = BrowserRecipe(RECIPE, tmp_path, pool=None)
    page = NavigatingPage(fail_on=1)

    # None, KHÔNG phải "": vòng poll phải phân biệt "chưa đọc được" với "đọc
    # được nhưng chưa có chữ nào", nếu không `last` bị xoá và câu trả lời sẽ
    # được yield lại từ đầu ở lần đọc sau -> client nhận nội dung nhân đôi.
    assert asyncio.run(provider._reply(page)) == (None, None)


def test_recovers_on_the_next_poll(tmp_path):
    provider = BrowserRecipe(RECIPE, tmp_path, pool=None)
    page = NavigatingPage(fail_on=2)

    async def run():
        first = await provider._reply(page)
        second = await provider._reply(page)
        third = await provider._reply(page)
        return first, second, third

    first, second, third = asyncio.run(run())
    assert first == (None, None)
    assert second == (None, None)
    assert third == ("Xin chào bạn", None)


def test_reply_text_helper_still_returns_str(tmp_path):
    # `_reply_text` là hợp đồng với code ngoài module: phải luôn là str.
    provider = BrowserRecipe(RECIPE, tmp_path, pool=None)
    page = NavigatingPage(fail_on=1)
    assert asyncio.run(provider._reply_text(page)) == ""


def test_empty_page_still_reads_as_empty_string(tmp_path):
    """Đọc được nhưng chưa có chữ vẫn phải là "", không phải None."""

    class EmptyPage:
        async def evaluate(self, script, args):
            return ["", None]

    provider = BrowserRecipe(RECIPE, tmp_path, pool=None)
    assert asyncio.run(provider._reply(EmptyPage())) == ("", None)
