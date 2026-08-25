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
        self._pending: dict[str, asyncio.Task] = {}
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

    async def _ensure_driver(self):
        async with self._driver_lock:
            if self._playwright is not None:
                return self._playwright
            try:
                self._playwright = await self._new_driver()
            except BaseException:
                self._playwright = None
                raise
            return self._playwright

    async def _remove_pending(self, job_id: str, task: asyncio.Task) -> None:
        async with self._lock:
            if self._pending.get(job_id) is task:
                self._pending.pop(job_id, None)

    async def start(self, job_id: str, slug: str, url: str, recipe_dir: Path) -> None:
        current_task = asyncio.current_task()
        async with self._lock:
            if self._closing:
                raise LoginSessionError("Login session manager is closed")
            if job_id in self._sessions or job_id in self._pending:
                raise LoginSessionError(f"Login session already exists for job {job_id}")
            self._pending[job_id] = current_task

        browser = None
        try:
            playwright = await self._ensure_driver()
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
            await _finish_cleanup(_close(browser, "close"))
            raise
        except Exception as error:
            await _finish_cleanup(_close(browser, "close"))
            if isinstance(error, LoginSessionError):
                raise
            raise LoginSessionError("Unable to start login session") from error
        finally:
            await _finish_cleanup(self._remove_pending(job_id, current_task))

    async def complete(self, job_id: str, filename: str = "state.json") -> Path:
        async with self._lock:
            session = self._sessions.pop(job_id, None)
        if session is None:
            raise LoginSessionError(f"No login session for job {job_id}")

        state_path = session.recipe_dir / "auth" / filename
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
        current_task = asyncio.current_task()
        async with self._lock:
            self._closing = True
            sessions = list(self._sessions.values())
            self._sessions.clear()
            pending = [task for task in self._pending.values() if task is not current_task]

        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        async def cleanup() -> None:
            for session in sessions:
                await _close(session.browser, "close")
            async with self._driver_lock:
                playwright = self._playwright
                self._playwright = None
                await _close(playwright, "stop")

        await _finish_cleanup(cleanup())
