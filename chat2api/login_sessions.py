import asyncio
import inspect
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class LoginSessionError(RuntimeError):
    pass


@dataclass
class LoginSession:
    job_id: str
    slug: str
    url: str
    recipe_dir: Path
    browser: Any
    context: Any
    page: Any
    created_at: float


async def _finish_cleanup(cleanup) -> None:
    task = asyncio.create_task(cleanup)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


async def _close(resource, method: str) -> None:
    if resource is None:
        return
    try:
        await getattr(resource, method)()
    except Exception:
        pass


class LoginSessionManager:
    def __init__(self, playwright_factory: Callable[[], Any] | None = None):
        self._playwright_factory = playwright_factory
        self._playwright = None
        self._sessions: dict[str, LoginSession] = {}
        self._pending: set[str] = set()
        self._closing = False
        self._lock = asyncio.Lock()
        self._driver_lock = asyncio.Lock()

    async def has(self, job_id: str) -> bool:
        async with self._lock:
            return job_id in self._sessions

    async def _new_driver(self):
        if self._playwright_factory is None:
            from playwright.async_api import async_playwright

            return await async_playwright().start()
        driver = self._playwright_factory()
        if inspect.isawaitable(driver):
            return await driver
        return driver

    async def _driver(self):
        async with self._driver_lock:
            if self._playwright is not None:
                return self._playwright, False
            task = asyncio.create_task(self._new_driver())
            try:
                driver = await asyncio.shield(task)
            except asyncio.CancelledError as cancelled:
                try:
                    driver = await task
                except Exception:
                    raise cancelled
                self._playwright = driver
                await _finish_cleanup(_close(driver, "stop"))
                self._playwright = None
                raise
            self._playwright = driver
            return driver, True

    async def _cleanup_start(self, browser, playwright, created_driver) -> None:
        await _close(browser, "close")
        if created_driver:
            async with self._driver_lock:
                if self._playwright is playwright:
                    await _close(playwright, "stop")
                    self._playwright = None

    async def start(self, job_id: str, slug: str, url: str, recipe_dir: Path) -> None:
        async with self._lock:
            if self._closing:
                raise LoginSessionError("Login session manager is closed")
            if job_id in self._sessions or job_id in self._pending:
                raise LoginSessionError(f"Login session already exists for job {job_id}")
            self._pending.add(job_id)

        browser = None
        playwright = None
        created_driver = False
        try:
            playwright, created_driver = await self._driver()
            launch = asyncio.create_task(playwright.chromium.launch(headless=False))
            try:
                browser = await asyncio.shield(launch)
            except asyncio.CancelledError:
                try:
                    browser = await launch
                except Exception:
                    pass
                raise
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(url)
            session = LoginSession(
                job_id=job_id,
                slug=slug,
                url=url,
                recipe_dir=Path(recipe_dir),
                browser=browser,
                context=context,
                page=page,
                created_at=time.time(),
            )
            async with self._lock:
                if self._closing:
                    raise LoginSessionError("Login session manager is closed")
                self._sessions[job_id] = session
        except asyncio.CancelledError:
            await _finish_cleanup(
                self._cleanup_start(browser, playwright, created_driver)
            )
            raise
        except Exception as error:
            await _finish_cleanup(
                self._cleanup_start(browser, playwright, created_driver)
            )
            if isinstance(error, LoginSessionError):
                raise
            raise LoginSessionError("Unable to start login session") from error
        finally:
            async with self._lock:
                self._pending.discard(job_id)

    async def complete(self, job_id: str) -> Path:
        async with self._lock:
            session = self._sessions.pop(job_id, None)
        if session is None:
            raise LoginSessionError(f"No login session for job {job_id}")

        state_path = session.recipe_dir / "auth" / "state.json"
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            await session.context.storage_state(path=state_path)
            return state_path
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise LoginSessionError("Unable to save login session") from error
        finally:
            await _finish_cleanup(_close(session.browser, "close"))

    async def cancel(self, job_id: str) -> None:
        async with self._lock:
            session = self._sessions.pop(job_id, None)
        if session is not None:
            await _finish_cleanup(_close(session.browser, "close"))

    async def close_all(self) -> None:
        async with self._lock:
            self._closing = True
            sessions = list(self._sessions.values())
            self._sessions.clear()
            playwright = self._playwright
            self._playwright = None

        async def cleanup() -> None:
            for session in sessions:
                await _close(session.browser, "close")
            await _close(playwright, "stop")

        await _finish_cleanup(cleanup())
