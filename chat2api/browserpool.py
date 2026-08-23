from collections import OrderedDict
from pathlib import Path


class BrowserPool:
    """Một BrowserContext dài hạn cho mỗi slug.

    ponytail: engine cloak tạo 1 browser riêng mỗi context (nặng hơn) —
    chấp nhận vì cloak chỉ bật cho site bot-detect khó.
    """

    def __init__(self, engine: str = "playwright", max_contexts: int = 3):
        self.engine = engine
        self.max_contexts = max_contexts
        self._contexts: OrderedDict[str, object] = OrderedDict()
        self._pw = None
        self._browser = None

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

    async def context_for(self, slug: str, storage_state: Path | None = None):
        if slug in self._contexts:
            self._contexts.move_to_end(slug)
            return self._contexts[slug]
        while len(self._contexts) >= self.max_contexts:
            _, old_ctx = self._contexts.popitem(last=False)
            try:
                await old_ctx.close()
            except Exception:
                pass
        state = str(storage_state) if storage_state and storage_state.exists() else None
        if self.engine == "cloak":
            from cloakbrowser import launch_context_async

            ctx = await launch_context_async(headless=True, storage_state=state)
        else:
            ctx = await self._browser.new_context(storage_state=state)
        self._contexts[slug] = ctx
        return ctx

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
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
