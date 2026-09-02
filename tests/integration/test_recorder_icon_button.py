"""Recorder phải bắt được nút icon-only bị lớp phủ vùng bấm che.

Đây là ca làm trace dola vô dụng: người dùng click trúng
``<div class="absolute inset-[-6px] opacity-0">`` bên trong ``<button>``, recorder
cũ ghi đúng cái div rỗng đó — không id, không aria-label, không text — nên không
suy ra nổi selector nút Copy.

Gộp mọi assert vào một test: mở Chromium ở đây tốn vài phút, tách ra thì mỗi test
lại mở lại một lần.
"""

import pytest

pytest.importorskip("playwright.async_api")

from chat2api.agents.recorder import RECORDER_JS_EXPR, enrich_event
from chat2api.browserpool import BrowserPool

OVERLAY = ".overlay"


async def test_overlay_click_records_the_real_button(site):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        ctx = await pool.context_for("rectest")
        page = await ctx.new_page()
        events: list[dict] = []
        await page.expose_binding("__c2a_record", lambda _src, payload: events.append(payload))
        await page.goto(f"{site}/icon-button.html")
        # evaluate (không phải add_init_script): trang đã tải xong rồi, đúng tình
        # huống mà bản cũ ném SyntaxError rồi nuốt lỗi nên không ghi được gì.
        await page.evaluate(RECORDER_JS_EXPR)
        await page.click(OVERLAY)
        await page.wait_for_timeout(200)
        await page.close()
    finally:
        await pool.aclose()

    assert events, "recorder không ghi được event nào"
    ev = enrich_event(events[-1])

    # 1. Ghi đúng nút, không phải lớp phủ
    assert ev["kind"] == "click"
    assert ev["tag"] == "button", f"vẫn ghi lớp phủ: tag={ev['tag']}"
    assert ev["attributes"].get("data-dbx-name") == "button"

    # 2. Tên leo được lên `title` của <button> (chỗ bị click không có tên)
    assert ev["name"] == "Sao chép"
    assert ev["label"] == "Sao chép"

    # 3. Vân tay icon — dấu hiệu duy nhất của nút không chữ
    icon = ev.get("icon") or {}
    assert icon.get("viewBox") == "0 0 24 24"
    assert icon.get("iconName") == "icon-copy"
    assert icon.get("pathD", "").startswith("M15.8032")

    # 4. Chuỗi tổ tiên leo tới id neo gần nhất
    anc_ids = [a.get("attributes", {}).get("id") for a in ev.get("ancestors", [])]
    assert "chat-route-main" in anc_ids, anc_ids

    # 5. snapshotDiff neo vào cha của NÚT nên chứa thẻ mở `<button ...>` — chỗ duy
    #    nhất người đọc trace thấy được attribute của nút.
    sd = ev["snapshotDiff"]
    assert "<button" in sd, sd[:300]
    assert 'title="Sao ch' in sd
