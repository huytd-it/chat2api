"""`__c2aCandidates` phải sinh selector ĐÃ VERIFY duy nhất, không phải đoán.

Trước đây `__c2aSel` trả `div:nth-of-type(3)` và không chỗ nào kiểm tính duy nhất,
nên LLM sinh recipe phải tự đoán selector. Các test dưới đây khoá lại hai điều:
ứng viên `unique=True` thì thật sự trúng đúng element đó, và bộ lọc độ bền loại
được id/class do framework sinh.
"""

import pytest
import pytest_asyncio

pytest.importorskip("playwright.async_api")

from chat2api.agents.dom import SELECTOR_FN_JS
from chat2api.browserpool import BrowserPool

# Gọi __c2aCandidates trên element chọn bằng một biểu thức JS tuỳ ý.
_EVAL = """(pick) => {
  %s
  const el = eval(pick);
  if(!el) throw new Error('không tìm thấy element: ' + pick);
  const cands = __c2aCandidates(el);
  return {cands: cands, best: __c2aBest(cands),
          // verify lại độc lập để test không tin vào cờ do chính hàm tự gắn
          resolved: cands.map(c => {
            let n = -1;
            try { const els = document.querySelectorAll(c.sel);
                  n = els.length === 1 && els[0] === el ? 1 : 0; } catch(e) { n = -2; }
            return n;
          })};
}""" % SELECTOR_FN_JS


@pytest.fixture(scope="module")
def module_site():
    """Bản module-scoped của fixture `site` — khởi động Chromium tốn ~1 phút ở đây,
    nên cả module dùng chung một trình duyệt thay vì mở lại mỗi test."""
    import http.server
    import socketserver
    import threading
    from functools import partial
    from pathlib import Path

    directory = str(Path(__file__).parent / "fixtures")
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
        httpd.shutdown()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def probe(module_site):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    ctx = await pool.context_for("candtest")
    page = await ctx.new_page()
    await page.goto(f"{module_site}/selector-candidates.html")

    async def run(pick: str) -> dict:
        return await page.evaluate(_EVAL, pick)

    try:
        yield run
    finally:
        await page.close()
        await pool.aclose()


@pytest.mark.asyncio(loop_scope="module")
async def test_test_hook_wins_and_is_unique(probe):
    r = await probe("document.querySelector('textarea')")
    assert r["best"] == '[data-testid="prompt-input"]'
    assert r["cands"][0]["kind"] == "testid"
    assert r["cands"][0]["unique"] is True


@pytest.mark.asyncio(loop_scope="module")
async def test_unique_flag_never_lies(probe):
    """Mọi ứng viên gắn unique=True phải thật sự resolve về đúng element đó."""
    for pick in ("document.querySelector('textarea')",
                 "document.querySelector('#msg-body')",
                 "document.querySelector('#left-rail button')",
                 "document.querySelector('#toolbar button')",
                 "document.querySelectorAll('#bare-box > div')[1]"):
        r = await probe(pick)
        for cand, resolved in zip(r["cands"], r["resolved"]):
            if cand["unique"]:
                assert resolved == 1, f"{pick}: {cand['sel']!r} gắn unique nhưng không trúng"
        assert r["cands"], f"{pick}: phải luôn có ít nhất ứng viên csspath"


@pytest.mark.asyncio(loop_scope="module")
async def test_framework_generated_id_rejected(probe):
    """id kiểu React useId (`:r3:`) đổi mỗi lần render — không được làm ứng viên."""
    r = await probe("document.querySelector('#msg-body').parentElement")
    assert all(c["kind"] != "id" for c in r["cands"]), r["cands"]
    # kể cả chốt chặn csspath cũng không được neo vào id đó (CSS.escape ra `#\:r3\:`)
    assert all("r3" not in c["sel"] for c in r["cands"]), r["cands"]


@pytest.mark.asyncio(loop_scope="module")
async def test_tailwind_and_hashed_classes_never_used(probe):
    """Class arbitrary-value / hash CSS-module đổi theo build, phải bị lọc sạch."""
    for pick in ("document.querySelector('textarea')",
                 "document.querySelector('#left-rail button')",
                 "document.querySelectorAll('#bare-box > div')[1]"):
        r = await probe(pick)
        for c in r["cands"]:
            assert "w-[" not in c["sel"] and "hover:" not in c["sel"], c
            assert "css-1a2b3c" not in c["sel"] and "btn_a8f93b21" not in c["sel"], c


@pytest.mark.asyncio(loop_scope="module")
async def test_duplicate_aria_label_falls_through_to_anchored(probe):
    """Hai nút trùng aria-label: `[aria-label=...]` phải bị đánh unique=False,
    và ứng viên leo tổ tiên neo vào #left-rail mới là cái được chọn."""
    r = await probe("document.querySelector('#left-rail button')")
    aria = [c for c in r["cands"] if c["kind"] == "aria"]
    assert aria, r["cands"]
    assert all(not c["unique"] for c in aria), aria
    assert all(c["count"] == 2 for c in aria), aria
    assert r["best"], "phải tìm được ứng viên duy nhất qua tổ tiên"
    assert "left-rail" in r["best"], r["best"]


@pytest.mark.asyncio(loop_scope="module")
async def test_icon_button_overlay_resolves_to_real_button(probe):
    """Click trúng lớp phủ, nhưng ứng viên của NÚT THẬT phải là data-testid của nó."""
    r = await probe("document.querySelector('#toolbar button')")
    assert r["best"] == '[data-testid="send"]'


@pytest.mark.asyncio(loop_scope="module")
async def test_csspath_is_always_the_last_resort(probe):
    """Element không có gì bám được vẫn phải ra một selector duy nhất."""
    r = await probe("document.querySelectorAll('#bare-box > div')[1]")
    assert any(c["kind"] == "csspath" for c in r["cands"]), r["cands"]
    assert r["best"], "csspath phải cứu được ca này"
