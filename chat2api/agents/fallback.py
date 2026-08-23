import asyncio
from typing import AsyncIterator

from ..prompt import flatten_messages
from . import dom, llm

SYSTEM_ACT = """Bạn điều khiển trình duyệt web để gửi một prompt vào trang chat và đọc câu trả lời.
Mỗi lượt bạn nhận DOM snapshot hiện tại và trả về MỘT hành động dạng JSON, chỉ một object:

{"action": "goto",    "url": "..."}
{"action": "fill",    "selector": "...", "text": "..."}
{"action": "click",   "selector": "..."}
{"action": "press",   "key": "Enter"}
{"action": "wait_text"}          // chờ 20s cho text mới xuất hiện rồi snapshot lại
{"done": true, "answer": "<toàn bộ câu trả lời của AI>"}

Quy tắc: fill selector ô nhập với TEXT dưới đây rồi submit bằng cách thông thường của trang
(click nút hoặc press Enter). Khi thấy câu trả lời hiển thị đầy đủ → done kèm answer."""


async def _biggest_texts(page) -> list[str]:
    return await page.evaluate(
        """() => [...document.querySelectorAll('div,p,section')]
             .map(e => e.innerText.trim())
             .filter(t => t.length > 30)
             .slice(-6)"""
    )


async def run(url: str, messages: list[dict], pool, cfg, log) -> AsyncIterator[str]:
    prompt = flatten_messages(messages)
    ctx = await pool.context_for("agent")
    page = await ctx.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        log(f"goto {url}")
        prev_texts: list[str] = []
        for step in range(15):
            snap = await dom.snapshot(page)
            user = (f"PROMPT CẦN GỬI:\n{prompt}\n\n"
                    f"TEXT CÁC VÙNG HIỆN TẠI:\n" + "\n---\n".join(prev_texts[:3]) +
                    f"\n\nDOM SNAPSHOT:\n{snap}\n\nTrả về hành động tiếp theo.")
            act = await llm.chat_json(cfg, SYSTEM_ACT, user)
            if act.get("done"):
                log(f"step {step}: done")
                yield str(act.get("answer", "")).strip()
                return
            kind = act.get("action")
            try:
                if kind == "goto":
                    await page.goto(act["url"], wait_until="domcontentloaded")
                elif kind == "fill":
                    box = page.locator(act["selector"]).first
                    await box.click()
                    await box.fill(str(act["text"]))
                elif kind == "click":
                    await page.click(act["selector"])
                elif kind == "press":
                    await page.keyboard.press(act.get("key", "Enter"))
                elif kind == "wait_text":
                    base = "".join(prev_texts[-1:])
                    for _ in range(40):  # 20s
                        await asyncio.sleep(0.5)
                        texts = await _biggest_texts(page)
                        new = [t for t in texts if t not in prev_texts]
                        if any(len(t) > len(base) for t in texts):
                            break
                else:
                    log(f"step {step}: action lạ {kind!r}, bỏ qua")
            except Exception as e:
                log(f"step {step}: {kind} lỗi: {e}")
            prev_texts = await _biggest_texts(page)
            log(f"step {step}: {kind} ok")
        # hết bước: trả vùng text dài nhất ổn định cuối cùng (best effort)
        if prev_texts:
            yield max(prev_texts, key=len)
    finally:
        await page.close()
