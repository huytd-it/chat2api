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


class LoginSessionManager:
    def __init__(self, playwright_factory: Callable[[], Any] | None = None):
        self._playwright_factory = playwright_factory
        self._playwright = None
        self._sessions: dict[str, LoginSession] = {}
        self._lock = asyncio.Lock()

    def has(self, job_id: str) -> bool:
        return job_id in self._sessions

    async def _driver(self):
        if self._playwright is None:
            if self._playwright_factory is None:
                from playwright.async_api import async_playwright

                driver = await async_playwright().start()
            else:
                driver = self._playwright_factory()
                if inspect.isawaitable(driver):
                    driver = await driver
            self._playwright = driver
        return self._playwright

    async def start(self, job_id: str, slug: str, url: str, recipe_dir: Path) -> None:
        browser = None
        async with self._lock:
            if job_id in self._sessions:
                raise LoginSessionError(f"Login session already exists for job {job_id}")
            created_driver = self._playwright is None
            try:
                playwright = await self._driver()
                browser = await playwright.chromium.launch(headless=False)
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto(url)
                self._sessions[job_id] = LoginSession(
                    job_id=job_id,
                    slug=slug,
                    url=url,
                    recipe_dir=Path(recipe_dir),
                    browser=browser,
                    context=context,
                    page=page,
                    created_at=time.time(),
                )
            except Exception as error:
                if browser is not None:
                    try:
                        await browser.close()
                    except Exception:
                        pass
                if created_driver and self._playwright is not None:
                    try:
                        await self._playwright.stop()
                    except Exception:
                        pass
                    self._playwright = None
                raise LoginSessionError("Unable to start login session") from error

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
        except Exception as error:
            raise LoginSessionError("Unable to save login session") from error
        finally:
            try:
                await session.browser.close()
            except Exception:
                pass

    async def cancel(self, job_id: str) -> None:
        async with self._lock:
            session = self._sessions.pop(job_id, None)
        if session is not None:
            try:
                await session.browser.close()
            except Exception:
                pass

    async def close_all(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            playwright = self._playwright
            self._playwright = None
        for session in sessions:
            try:
                await session.browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                pass
