import asyncio

# Đăng ký page Playwright đang "active" theo watch_id, để admin/watch/{id}/screenshot
# chụp ảnh trực tiếp bất cứ lúc nào — hoạt động cả headless lẫn headed, nên đây là
# cách xem trực quan browser đáng tin cậy hơn cửa sổ Chromium (có thể không hiện ra
# tùy máy/session của người dùng).
_pages: dict[str, object] = {}
_lock = asyncio.Lock()


async def register(watch_id: str, page) -> None:
    if not watch_id:
        return
    async with _lock:
        _pages[watch_id] = page


async def unregister(watch_id: str, page) -> None:
    if not watch_id:
        return
    async with _lock:
        if _pages.get(watch_id) is page:
            _pages.pop(watch_id, None)


async def screenshot(watch_id: str) -> bytes | None:
    async with _lock:
        page = _pages.get(watch_id)
    if page is None:
        return None
    try:
        return await page.screenshot(type="jpeg", quality=60)
    except Exception:
        return None
