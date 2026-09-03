"""Event `fill` không được phụ thuộc vào việc người ghi có kịp dừng tay hay không.

Handler `input` debounce 700ms. Nếu enrich ở thời điểm debounce bắn thì với site
gửi-bằng-Enter (dola) ô nhập đã bị dựng lại, `el` lìa khỏi document và event
`fill` chỉ còn rác: cssPath cụt còn "div", bbox toàn 0, ancestors rỗng, value "".

Hai trace dola thật cho thấy đúng trò tung đồng xu này: lần gõ rồi dừng 8 giây
mới Enter thì fill sạch; lần gõ rồi Enter ngay thì fill hỏng hoàn toàn.

Mở Chromium ở đây tốn vài phút mỗi lần nên mỗi test chỉ mở đúng một lượt.
"""

import pytest

pytest.importorskip("playwright.async_api")

from chat2api.agents.recorder import RECORDER_JS_EXPR, enrich_event
from chat2api.browserpool import BrowserPool

EDITOR = ".tiptap"
PROMPT = "Xin chào bạn"


async def _record(site, after_typing):
    """Gõ PROMPT rồi chạy `after_typing(page)`; trả về các event đã chuẩn hoá."""
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        ctx = await pool.context_for("fillrace")
        page = await ctx.new_page()
        events: list[dict] = []
        await page.expose_binding("__c2a_record", lambda _src, payload: events.append(payload))
        await page.goto(f"{site}/remount-input.html")
        await page.evaluate(RECORDER_JS_EXPR)
        await page.click(EDITOR)
        await page.type(EDITOR, PROMPT)
        await after_typing(page)
        await page.close()
    finally:
        await pool.aclose()
    return [enrich_event(e) for e in events]


def _fills(events):
    return [e for e in events if e["kind"] == "fill"]


def _assert_usable(fill):
    """Những gì một event fill phải mang để suy ra được `prompt.input_selector`."""
    assert fill["value"] == PROMPT
    assert fill["attributes"].get("role") == "textbox"
    # Ô nhập không có id nên cssPath phải là đường dẫn neo vào container.
    assert fill["selectors"]["cssPath"].startswith("div#input-engine-container"), \
        fill["selectors"]["cssPath"]
    anc_ids = [a.get("attributes", {}).get("id") for a in fill.get("ancestors", [])]
    assert "input-engine-container" in anc_ids, anc_ids


async def test_enter_immediately_after_typing_still_yields_a_usable_fill(site):
    """Ca làm hỏng trace dola: gõ xong Enter ngay, site dựng lại ô nhập.

    Cũng chốt thứ tự `fill` trước `press` — trace cũ cho ra ngược đời vì fill
    phải đợi hết 700ms debounce, tức là sau cả Enter.
    """

    async def after(page):
        await page.press(EDITOR, "Enter")
        await page.wait_for_timeout(1000)

    events = await _record(site, after)
    fills = _fills(events)
    assert fills, f"không có event fill nào: {[e['kind'] for e in events]}"
    _assert_usable(fills[-1])

    kinds = [e["kind"] for e in events]
    assert kinds.index("fill") < kinds.index("press"), kinds
    # Recorder nghe keydown ở capture phase nên flush chạy TRƯỚC lúc site thay
    # node — ô nhập còn sống, không có gì để đánh dấu detached.
    assert not fills[-1].get("detached")


async def test_fill_flags_detachment_when_input_dies_before_the_debounce(site):
    """Ô nhập bị dựng lại KHÔNG do Enter: flush đi đường timer, element đã chết.

    Enrich vẫn phải là bản chụp lúc gõ, và event phải tự khai `detached` để
    người đọc trace biết `bbox` / DOM xung quanh không còn đáng tin.
    """

    async def after(page):
        await page.evaluate("window.__remount()")
        await page.wait_for_timeout(1200)

    fills = _fills(await _record(site, after))
    assert fills, "không có event fill nào"
    _assert_usable(fills[-1])
    assert fills[-1].get("detached") is True


async def test_normal_pause_still_records_a_clean_fill(site):
    """Người ghi dừng tay đủ lâu: đường cũ chạy y như trước, không cờ detached."""

    async def after(page):
        await page.wait_for_timeout(1000)

    fills = _fills(await _record(site, after))
    assert fills, "không có event fill nào"
    _assert_usable(fills[-1])
    assert not fills[-1].get("detached")
