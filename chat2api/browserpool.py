import asyncio
import logging

logger = logging.getLogger(__name__)

from collections import OrderedDict
from pathlib import Path


async def _finish_cleanup(cleanup) -> None:
    task = asyncio.create_task(cleanup)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


class BrowserPool:
    """Một BrowserContext dài hạn cho mỗi slug.

    ponytail: engine cloak tạo 1 browser riêng mỗi context (nặng hơn) —
    chấp nhận vì cloak chỉ bật cho site bot-detect khó.
    """

    def __init__(self, engine: str = "playwright", max_contexts: int = 10):
        self.engine = engine
        self.max_contexts = max(1, int(max_contexts))
        self._contexts: OrderedDict[str, object] = OrderedDict()
        self._lock = asyncio.Lock()
        self._pw = None
        self._browser = None
        # Browser headed (cửa sổ hiện ra) dùng khi test recipe trong lúc
        # Integrate, để xem trực quan trang web bên cạnh app — chỉ khởi
        # động khi có context nào đó yêu cầu headed=True.
        self._browser_headed = None

    @property
    def size(self) -> int:
        return len(self._contexts)

    async def start(self):
        if self.engine == "cloak":
            try:
                from cloakbrowser import launch_context_async  # noqa: F401
            except ImportError as e:
                raise RuntimeError("BROWSER_ENGINE=cloak cần: pip install cloakbrowser") from e
            return
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)

    @staticmethod
    def _alive(ctx) -> bool:
        """Context chết khi người dùng tự tay tắt cửa sổ browser headed."""
        browser = getattr(ctx, "browser", None)
        if browser is None:
            return True
        return browser.is_connected()

    def _cached(self, slug: str):
        ctx = self._contexts.get(slug)
        if ctx is None:
            return None
        if not self._alive(ctx):
            del self._contexts[slug]
            logger.info("BrowserPool: browser của '%s' đã bị đóng tay, sẽ mở lại", slug)
            return None
        self._contexts.move_to_end(slug)
        return ctx

    async def context_for(self, slug: str, storage_state: Path | None = None,
                          headed: bool = False):
        ctx = self._cached(slug)
        if ctx is not None:
            return ctx
        async with self._lock:
            ctx = self._cached(slug)
            if ctx is not None:
                return ctx
            while len(self._contexts) >= self.max_contexts:
                _, old_ctx = self._contexts.popitem(last=False)
                try:
                    await old_ctx.close()
                except Exception:
                    pass
                logger.warning(
                    "BrowserPool context evicted for slug (max_contexts=%s)", self.max_contexts
                )
            state = str(storage_state) if storage_state and storage_state.exists() else None
            if self.engine == "cloak":
                from cloakbrowser import launch_context_async

                ctx = await launch_context_async(headless=not headed, storage_state=state)
            else:
                browser = await self._browser_for(headed)
                ctx = await browser.new_context(storage_state=state)
            self._contexts[slug] = ctx
            return ctx

    async def _browser_for(self, headed: bool):
        if not headed:
            return self._browser
        # Người dùng tắt tay cửa sổ headed thì browser mất kết nối — mở lại cho
        # request kế tiếp thay vì để nó lỗi.
        if self._browser_headed is not None and not self._browser_headed.is_connected():
            self._browser_headed = None
        if self._browser_headed is None:
            self._browser_headed = await self._pw.chromium.launch(headless=False)
        return self._browser_headed

    async def drop(self, slug: str) -> None:
        async with self._lock:
            context = self._contexts.pop(slug, None)
        if context:
            async def close() -> None:
                try:
                    await context.close()
                except Exception:
                    pass

            await _finish_cleanup(close())

    async def aclose(self):
        for ctx in self._contexts.values():
            try:
                await ctx.close()
            except Exception:
                pass
        self._contexts.clear()
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._browser_headed:
            try:
                await self._browser_headed.close()
            except Exception:
                pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
