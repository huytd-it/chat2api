import asyncio
import contextlib
import json
import logging

logger = logging.getLogger(__name__)

from collections import OrderedDict
from pathlib import Path

# Chromium bóp CPU của tab nền. Trang chat đang stream trả lời sẽ đứng lại và
# vòng poll `stable_text` trong browser_recipe.stream() sẽ timeout — nên khi
# chạy nhiều recipe song song trong một profile, ba cờ này là bắt buộc.
PROFILE_ARGS = [
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]


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

    def __init__(self, engine: str = "playwright", max_contexts: int = 10,
                 max_profiles: int = 2):
        self.engine = engine
        self.max_contexts = max(1, int(max_contexts))
        self.max_profiles = max(1, int(max_profiles))
        self._contexts: OrderedDict[str, object] = OrderedDict()
        self._lock = asyncio.Lock()
        self._pw = None
        self._browser = None
        # Đường profile (BROWSER_PROFILE_MODE=profile) — sống SONG SONG với
        # _contexts ở trên, không thay thế. Mỗi profile là một persistent
        # context (vừa là browser vừa là context), giữ nhiều tab bên trong.
        self._profiles: OrderedDict[str, object] = OrderedDict()
        self._profile_ids: dict[str, int] = {}
        self._profile_headless: dict[str, bool] = {}
        self._pages: OrderedDict[str, object] = OrderedDict()
        self._profile_lock = asyncio.Lock()
        # Đếm việc đang chạy trên từng profile / từng tab. Trần max_profiles và
        # max_tabs chỉ được phép đóng thứ ĐANG RẢNH: mở nhiều
        # profile/domain/account một lúc mà cứ đóng cái cũ nhất thì request nào
        # chạy lâu cũng bị cắt giữa chừng.
        self._busy_profiles: dict[str, int] = {}
        self._busy_tabs: dict[str, int] = {}
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

    # ------------------------------------------------------- đường profile

    async def context_for_profile(self, profile):
        """Persistent context của một profile, mở nếu chưa có.

        Khác `context_for`: một profile giữ đăng nhập của mọi domain và chứa
        nhiều tab, nên nó được khoá theo tên profile chứ không theo slug recipe.
        """
        from . import profiles as profiles_mod

        ctx = self._profiles.get(profile.name)
        if ctx is not None and self._profile_alive(ctx):
            self._profiles.move_to_end(profile.name)
            return ctx
        async with self._profile_lock:
            ctx = self._profiles.get(profile.name)
            if ctx is not None and self._profile_alive(ctx):
                self._profiles.move_to_end(profile.name)
                return ctx
            self._profiles.pop(profile.name, None)
            while len(self._profiles) >= self.max_profiles:
                name = self._idle_profile()
                if name is None:
                    logger.warning(
                        "BrowserPool: %s profile đang bận, mở thêm '%s' vượt "
                        "max_profiles=%s thay vì cắt request đang chạy",
                        len(self._profiles), profile.name, self.max_profiles)
                    break
                await self._close_profile(name, self._profiles.pop(name))
                logger.info("BrowserPool: đóng profile '%s' (max_profiles=%s)",
                            name, self.max_profiles)

            # Khoá pid phải giành TRƯỚC khi Chromium chạm vào thư mục.
            await asyncio.to_thread(profiles_mod.acquire_lock, profile)
            try:
                ctx = await self._launch_profile(profile)
            except Exception:
                await asyncio.to_thread(profiles_mod.release_lock, profile.id)
                raise
            self._profiles[profile.name] = ctx
            self._profile_headless[profile.name] = bool(profile.headless)
            self._profile_ids[profile.name] = profile.id
            await self._seed_profile(profile, ctx)
            await asyncio.to_thread(profiles_mod.touch, profile.id)
            return ctx

    def _idle_profile(self) -> str | None:
        """Profile ít dùng nhất mà không có request nào đang chạy (LRU trước)."""
        return next((name for name in self._profiles if not self._busy_profiles.get(name)), None)

    @contextlib.asynccontextmanager
    async def hold(self, profile_name: str, tab_key: str = ""):
        """Ghim profile/tab trong lúc một request dùng nó.

        Không phải khoá loại trừ (đã có `_lock_for` trong recipe lo việc đó) —
        chỉ là cái phao để vòng evict biết cái nào còn đang chạy.
        """
        self._busy_profiles[profile_name] = self._busy_profiles.get(profile_name, 0) + 1
        if tab_key:
            self._busy_tabs[tab_key] = self._busy_tabs.get(tab_key, 0) + 1
        try:
            yield
        finally:
            if self._busy_profiles.get(profile_name, 0) <= 1:
                self._busy_profiles.pop(profile_name, None)
            else:
                self._busy_profiles[profile_name] -= 1
            if tab_key:
                if self._busy_tabs.get(tab_key, 0) <= 1:
                    self._busy_tabs.pop(tab_key, None)
                else:
                    self._busy_tabs[tab_key] -= 1

    async def _launch_profile(self, profile):
        kwargs = {
            "user_data_dir": profile.user_data_dir,
            "headless": profile.headless,
            "args": list(PROFILE_ARGS),
        }
        viewport = profile.viewport_size
        if viewport:
            kwargs["viewport"] = viewport
        for key, value in (("proxy", {"server": profile.proxy} if profile.proxy else None),
                           ("user_agent", profile.user_agent),
                           ("locale", profile.locale),
                           ("timezone_id", profile.timezone)):
            if value:
                kwargs[key] = value
        return await self._pw.chromium.launch_persistent_context(**kwargs)

    async def _seed_profile(self, profile, ctx) -> None:
        """Đổ storage_state cũ vào profile lần đầu, rồi bỏ đánh dấu.

        Cookie đổ thẳng được; localStorage phải mở đúng origin mới ghi được, nên
        mỗi origin tốn một lần goto. Lỗi ở đây không được chặn request: profile
        chưa seed vẫn chạy được, chỉ là người dùng phải đăng nhập lại.
        """
        from . import profiles as profiles_mod

        pending = await asyncio.to_thread(profiles_mod.pending_seeds, profile.id)
        for account_id, path in pending:
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except Exception as error:
                logger.warning("seed profile '%s': không đọc được %s: %s",
                               profile.name, path, error)
                continue
            try:
                cookies = state.get("cookies") or []
                if cookies:
                    await ctx.add_cookies(cookies)
                for origin in state.get("origins") or []:
                    items = origin.get("localStorage") or []
                    if not items:
                        continue
                    page = await ctx.new_page()
                    try:
                        await page.goto(origin["origin"], wait_until="domcontentloaded",
                                        timeout=20000)
                        await page.evaluate(
                            "(items) => { for (const it of items)"
                            " localStorage.setItem(it.name, it.value); }", items)
                    finally:
                        await page.close()
                await asyncio.to_thread(profiles_mod.clear_seed, account_id)
                logger.info("seed profile '%s' từ %s", profile.name, path.name)
            except Exception as error:
                logger.warning("seed profile '%s' từ %s thất bại: %s",
                               profile.name, path, error)

    async def page_for(self, profile, slug: str):
        """Tab dài hạn cho một cặp (profile, recipe).

        Mỗi recipe một tab riêng nên các recipe khác nhau trong cùng profile
        chạy song song được — đây chính là phần "chia tab dùng nhiều web chat
        một lúc".
        """
        ctx = await self.context_for_profile(profile)
        key = f"{profile.name}::{slug}"
        page = self._pages.get(key)
        if page is not None and not page.is_closed():
            self._pages.move_to_end(key)
            return page
        self._pages.pop(key, None)
        # Persistent context luôn mở sẵn một about:blank; nhận nó làm tab đầu
        # thay vì để một cửa sổ trống lơ lửng.
        existing = [p for p in ctx.pages if not p.is_closed()]
        claimed = {id(p) for p in self._pages.values()}
        page = next((p for p in existing if id(p) not in claimed and p.url in ("about:blank", "")),
                    None)
        if page is None:
            page = await ctx.new_page()
        self._pages[key] = page
        await self._evict_tabs(profile, keep=key)
        return page

    async def _evict_tabs(self, profile, keep: str = "") -> None:
        """Đóng bớt tab RẢNH khi vượt trần; `keep` là tab vừa mở cho người gọi."""
        prefix = f"{profile.name}::"
        keys = [k for k in self._pages if k.startswith(prefix)]
        while len(keys) > profile.max_tabs:
            victim = next((k for k in keys
                           if k != keep and not self._busy_tabs.get(k)), None)
            if victim is None:
                logger.warning("BrowserPool: %s tab của '%s' đều đang bận, giữ nguyên "
                               "(max_tabs=%s)", len(keys), profile.name, profile.max_tabs)
                break
            keys.remove(victim)
            page = self._pages.pop(victim, None)
            if page is not None and not page.is_closed():
                try:
                    await page.close()
                except Exception:
                    pass
            logger.info("BrowserPool: đóng tab '%s' (max_tabs=%s)", victim, profile.max_tabs)

    @staticmethod
    def _profile_alive(ctx) -> bool:
        browser = getattr(ctx, "browser", None)
        if browser is not None:
            return browser.is_connected()
        # Persistent context không có .browser trong vài bản Playwright; mất
        # hết page là dấu hiệu người dùng đã tắt tay cửa sổ.
        try:
            return any(not p.is_closed() for p in ctx.pages) or not ctx.pages
        except Exception:
            return False

    async def _close_profile(self, name: str, ctx) -> None:
        from . import profiles as profiles_mod

        for key in [k for k in self._pages if k.startswith(f"{name}::")]:
            self._pages.pop(key, None)
            self._busy_tabs.pop(key, None)
        self._busy_profiles.pop(name, None)
        try:
            await ctx.close()
        except Exception:
            pass
        profile_id = self._profile_ids.pop(name, None)
        self._profile_headless.pop(name, None)
        if profile_id is not None:
            await asyncio.to_thread(profiles_mod.release_lock, profile_id)

    async def drop_profile(self, name: str) -> bool:
        async with self._profile_lock:
            ctx = self._profiles.pop(name, None)
        if ctx is None:
            return False
        await _finish_cleanup(self._close_profile(name, ctx))
        return True

    @property
    def profile_count(self) -> int:
        return len(self._profiles)

    def open_context(self, profile_name: str):
        """Persistent context đang mở của một profile, None nếu chưa mở.

        Đường đọc-only cho admin (quét cookie); không tự mở browser vì người
        gọi có thể chỉ muốn biết trạng thái hiện tại.
        """
        ctx = self._profiles.get(profile_name)
        if ctx is None or not self._profile_alive(ctx):
            return None
        return ctx

    def profile_headless(self, profile_name: str) -> bool | None:
        """Launch mode of an open persistent context, if tracked."""
        if self.open_context(profile_name) is None:
            return None
        return self._profile_headless.get(profile_name)

    @property
    def open_profiles(self) -> list[str]:
        return list(self._profiles)

    def tab_count(self, profile_name: str) -> int:
        prefix = f"{profile_name}::"
        return sum(1 for k, p in self._pages.items()
                   if k.startswith(prefix) and not p.is_closed())

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
        for name, ctx in list(self._profiles.items()):
            await self._close_profile(name, ctx)
        self._profiles.clear()
        self._pages.clear()
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
