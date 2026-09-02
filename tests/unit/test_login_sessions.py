import asyncio
import contextlib
from dataclasses import dataclass
from pathlib import Path

import pytest

from chat2api.browserpool import BrowserPool
from chat2api.login_sessions import LoginSessionError, LoginSessionManager


class FakePage:
    def __init__(self, fail=False, goto_started=None, allow_goto=None):
        self.urls = []
        self.fail = fail
        self.goto_started = goto_started
        self.allow_goto = allow_goto

    async def goto(self, url, **kwargs):
        self.urls.append(url)
        if self.goto_started:
            self.goto_started.set()
        if self.allow_goto:
            await self.allow_goto.wait()
        if self.fail:
            raise RuntimeError("goto failed")


class FakeContext:
    def __init__(
        self,
        fail_new_page=False,
        fail_goto=False,
        fail_save=False,
        goto_started=None,
        allow_goto=None,
    ):
        self.page = FakePage(fail_goto, goto_started, allow_goto)
        self.closed = False
        self.saved = None
        self.storage_state_arg = None
        self.fail_new_page = fail_new_page
        self.fail_save = fail_save

    async def new_page(self):
        if self.fail_new_page:
            raise RuntimeError("new_page failed")
        return self.page

    async def storage_state(self, path):
        if self.fail_save:
            raise RuntimeError("storage_state failed")
        self.saved = Path(path)
        self.saved.parent.mkdir(parents=True, exist_ok=True)
        self.saved.write_text("{}")

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, fail_new_context=False, **context_kwargs):
        self.context = FakeContext(**context_kwargs)
        self.closed = False
        self.fail_new_context = fail_new_context

    async def new_context(self, storage_state=None):
        if self.fail_new_context:
            raise RuntimeError("new_context failed")
        self.context.storage_state_arg = storage_state
        return self.context

    async def close(self):
        self.closed = True


class FakeLauncher:
    def __init__(self, fail_launch=False, browser_events=None, **browser_kwargs):
        self.browser = None
        self.browsers = []
        self.browser_events = list(browser_events or [])
        self.browser_kwargs = browser_kwargs
        self.fail_launch = fail_launch

    async def launch(self, **kwargs):
        assert kwargs["headless"] is False
        if self.fail_launch:
            raise RuntimeError("launch failed")
        event_kwargs = self.browser_events[len(self.browsers)] if self.browser_events else {}
        self.browser = FakeBrowser(**{**self.browser_kwargs, **event_kwargs})
        self.browsers.append(self.browser)
        return self.browser


class FakePW:
    def __init__(self, **launcher_kwargs):
        self.chromium = FakeLauncher(**launcher_kwargs)
        self.stopped = False

    async def stop(self):
        self.stopped = True


async def test_start_complete_saves_state_and_cleans(tmp_path):
    pw = FakePW()
    manager = LoginSessionManager(playwright_factory=lambda: pw)

    await manager.start("j1", "site", "https://site.example", tmp_path / "site")

    assert await manager.has("j1")
    assert pw.chromium.browser.context.page.urls == ["https://site.example"]
    state = await manager.complete("j1")
    assert state == tmp_path / "site" / "auth" / "state.json"
    assert state.exists()
    assert not await manager.has("j1")
    assert pw.chromium.browser.closed


async def test_duplicate_job_rejected(tmp_path):
    manager = LoginSessionManager(playwright_factory=lambda: FakePW())
    await manager.start("j1", "site", "https://x", tmp_path)

    with pytest.raises(LoginSessionError):
        await manager.start("j1", "site", "https://x", tmp_path)

    await manager.close_all()


async def test_cancel_closes_without_state(tmp_path):
    pw = FakePW()
    manager = LoginSessionManager(playwright_factory=lambda: pw)
    await manager.start("j1", "site", "https://x", tmp_path)

    await manager.cancel("j1")

    assert not (tmp_path / "auth" / "state.json").exists()
    assert pw.chromium.browser.closed
    assert not await manager.has("j1")


@pytest.mark.parametrize(
    "failure",
    ["launch", "new_context", "new_page", "goto"],
)
async def test_start_failure_cleans_partial_resources(tmp_path, failure):
    kwargs = {
        "fail_launch": failure == "launch",
        "fail_new_context": failure == "new_context",
        "fail_new_page": failure == "new_page",
        "fail_goto": failure == "goto",
    }
    pw = FakePW(**kwargs)
    manager = LoginSessionManager(playwright_factory=lambda: pw)

    with pytest.raises(LoginSessionError, match="Unable to start login session"):
        await manager.start("j1", "site", "https://x", tmp_path)

    assert not await manager.has("j1")
    assert not pw.stopped
    if failure != "launch":
        assert pw.chromium.browser.closed
    await manager.close_all()
    assert pw.stopped


async def test_complete_failure_closes_and_forgets_session(tmp_path):
    pw = FakePW(fail_save=True)
    manager = LoginSessionManager(playwright_factory=lambda: pw)
    await manager.start("j1", "site", "https://x", tmp_path)

    with pytest.raises(LoginSessionError, match="Unable to save login session"):
        await manager.complete("j1")

    assert pw.chromium.browser.closed
    assert not await manager.has("j1")


async def test_close_all_closes_sessions_and_stops_shared_driver(tmp_path):
    pw = FakePW()
    manager = LoginSessionManager(playwright_factory=lambda: pw)
    await manager.start("j1", "site", "https://x", tmp_path)

    await manager.close_all()

    assert pw.chromium.browser.closed
    assert pw.stopped
    assert not await manager.has("j1")


async def test_missing_cancel_is_noop():
    manager = LoginSessionManager(playwright_factory=lambda: FakePW())

    await manager.cancel("missing")


async def test_browser_pool_drop_closes_fake_context():
    context = FakeContext()
    pool = BrowserPool()
    pool._contexts["site"] = context

    await pool.drop("site")

    assert context.closed
    assert pool.size == 0


async def test_cancelling_pending_start_during_goto_cleans_resources(tmp_path):
    goto_started = asyncio.Event()
    allow_goto = asyncio.Event()
    pw = FakePW(goto_started=goto_started, allow_goto=allow_goto)
    manager = LoginSessionManager(playwright_factory=lambda: pw)
    start = asyncio.create_task(manager.start("j1", "site", "https://x", tmp_path))
    await asyncio.wait_for(goto_started.wait(), 1)

    start.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(start, 1)

    assert pw.chromium.browser.closed
    assert not pw.stopped
    assert not await manager.has("j1")
    await manager.close_all()
    assert pw.stopped


async def test_duplicate_while_first_start_pending_is_rejected(tmp_path):
    goto_started = asyncio.Event()
    allow_goto = asyncio.Event()
    manager = LoginSessionManager(
        playwright_factory=lambda: FakePW(
            goto_started=goto_started,
            allow_goto=allow_goto,
        )
    )
    first = asyncio.create_task(manager.start("j1", "site", "https://x", tmp_path))
    await asyncio.wait_for(goto_started.wait(), 1)

    with pytest.raises(LoginSessionError, match="already exists"):
        await asyncio.wait_for(
            manager.start("j1", "site", "https://x", tmp_path),
            1,
        )

    allow_goto.set()
    await asyncio.wait_for(first, 1)
    await manager.close_all()


async def test_failed_start_does_not_stop_driver_shared_by_published_session(tmp_path):
    first_goto_started = asyncio.Event()
    fail_first_goto = asyncio.Event()
    pw = FakePW(
        browser_events=[
            {
                "goto_started": first_goto_started,
                "allow_goto": fail_first_goto,
                "fail_goto": True,
            },
            {},
        ]
    )
    manager = LoginSessionManager(playwright_factory=lambda: pw)
    first = asyncio.create_task(manager.start("j1", "site", "https://x", tmp_path))
    await asyncio.wait_for(first_goto_started.wait(), 1)

    await manager.start("j2", "site", "https://y", tmp_path)
    fail_first_goto.set()
    with pytest.raises(LoginSessionError, match="Unable to start"):
        await asyncio.wait_for(first, 1)

    assert pw.chromium.browsers[0].closed
    assert await manager.has("j2")
    assert not pw.chromium.browsers[1].closed
    assert not pw.stopped

    await manager.close_all()
    assert pw.chromium.browsers[1].closed
    assert pw.stopped


async def test_close_all_cancels_and_drains_pending_start(tmp_path):
    goto_started = asyncio.Event()
    allow_goto = asyncio.Event()
    pw = FakePW(goto_started=goto_started, allow_goto=allow_goto)
    manager = LoginSessionManager(playwright_factory=lambda: pw)
    start = asyncio.create_task(manager.start("j1", "site", "https://x", tmp_path))
    await asyncio.wait_for(goto_started.wait(), 1)

    await asyncio.wait_for(manager.close_all(), 1)

    with pytest.raises(asyncio.CancelledError):
        await start
    assert pw.chromium.browser.closed
    assert manager._pending == {}
    assert pw.stopped
    assert not await manager.has("j1")


# --------------------------------------------------- start_recording (profile)
#
# "Ghi thao tác" phải mở đúng persistent context của profile đã chọn (cookie
# đăng nhập sẵn có), không phải một browser ẩn danh trắng phiên. Các fake dưới
# đây mô phỏng đúng bề mặt của BrowserPool mà start_recording gọi tới, không
# cần Chromium thật.


@dataclass
class FakeProfile:
    # dataclass thật vì login_sessions.start_recording gọi dataclasses.replace()
    # trên `profile` giống hệt chat2api.profiles.Profile ở production.
    name: str = "main"
    headless: bool = True


class FakeRecordContext:
    def __init__(self):
        self.saved = None

    async def storage_state(self, path):
        self.saved = Path(path)
        self.saved.parent.mkdir(parents=True, exist_ok=True)
        self.saved.write_text("{}")

    async def cookies(self):
        return []


class FakeRecordPage:
    def __init__(self, url="about:blank"):
        self.context = FakeRecordContext()
        self.main_frame = None
        self.url = url
        self.goto_calls = []
        self._closed = False

    async def goto(self, url, **kwargs):
        self.goto_calls.append(url)

    def on(self, *args, **kwargs):
        pass

    def is_closed(self):
        return self._closed

    async def close(self):
        self._closed = True


class FakeRecordPool:
    """Chỉ implement đúng bề mặt mà LoginSessionManager.start_recording dùng."""

    def __init__(self, already_open=False, already_headless=False):
        self.already_open = already_open
        self.already_headless = already_headless
        self.hold_calls: list[tuple] = []
        self.page_for_calls: list[tuple] = []
        self.closed_tabs: list[tuple] = []
        self.pages: dict[tuple, FakeRecordPage] = {}

    def open_context(self, name):
        return object() if self.already_open else None

    def profile_headless(self, name):
        return self.already_headless

    @contextlib.asynccontextmanager
    async def hold(self, profile_name, tab_key=""):
        self.hold_calls.append((profile_name, tab_key, "enter"))
        try:
            yield
        finally:
            self.hold_calls.append((profile_name, tab_key, "exit"))

    async def page_for(self, profile, tab_key):
        page = FakeRecordPage()
        self.pages[(profile.name, tab_key)] = page
        self.page_for_calls.append((profile.name, tab_key, profile.headless))
        return page

    async def close_tab(self, profile_name, tab_key):
        page = self.pages.pop((profile_name, tab_key), None)
        if page is None:
            return False
        await page.close()
        self.closed_tabs.append((profile_name, tab_key))
        return True


async def test_start_recording_reuses_profile_persistent_context():
    """Chưa mở lần nào -> mở mới ép headed, ghi trong context của PROFILE
    (không phải browser ẩn danh riêng)."""
    pool = FakeRecordPool(already_open=False)
    profile = FakeProfile("codex08", headless=True)
    manager = LoginSessionManager()

    await manager.start_recording("j1", "record", "https://chat.qwen.ai", Path("recipes/.login/j1"),
                                  pool, profile)

    assert await manager.has("j1")
    assert pool.page_for_calls == [("codex08", "record-j1", False)]   # ép headed=False (hiện cửa sổ)
    assert pool.hold_calls[0] == ("codex08", "record-j1", "enter")
    page = pool.pages[("codex08", "record-j1")]
    assert page.goto_calls == ["https://chat.qwen.ai"]

    session = manager._sessions["j1"]
    assert session.browser is None            # không sở hữu browser riêng
    assert session.pool is pool
    assert session.profile_name == "codex08"
    assert session.tab_key == "record-j1"


async def test_start_recording_refuses_when_profile_already_open_headless():
    """Profile đang chạy nền (headless) từ trước -> không mở được cửa sổ thật,
    báo lỗi rõ thay vì âm thầm ghi trong chế độ ẩn (vô dụng vì cần thao tác tay)."""
    pool = FakeRecordPool(already_open=True, already_headless=True)
    profile = FakeProfile("codex08", headless=True)
    manager = LoginSessionManager()

    with pytest.raises(LoginSessionError, match="headless"):
        await manager.start_recording("j1", "record", "https://chat.qwen.ai", Path("x"),
                                      pool, profile)

    assert not await manager.has("j1")
    assert pool.page_for_calls == []
    assert pool.hold_calls == []


async def test_start_recording_reuses_existing_headed_profile_as_is():
    """Profile đã mở sẵn (không headless) -> dùng nguyên context đó, không ép
    lại `headless` (đang mở rồi thì không đổi flag khởi động được nữa)."""
    pool = FakeRecordPool(already_open=True, already_headless=False)
    profile = FakeProfile("codex08", headless=True)
    manager = LoginSessionManager()

    await manager.start_recording("j1", "record", "https://chat.qwen.ai", Path("x"), pool, profile)

    assert pool.page_for_calls == [("codex08", "record-j1", True)]  # giữ nguyên profile.headless gốc
    assert await manager.has("j1")


async def test_complete_closes_only_the_tab_not_the_profile_context():
    pool = FakeRecordPool(already_open=False)
    profile = FakeProfile("codex08", headless=True)
    manager = LoginSessionManager()
    await manager.start_recording("j1", "record", "https://chat.qwen.ai",
                                  Path("recipes") / ".login" / "j1", pool, profile)
    page = pool.pages[("codex08", "record-j1")]

    state_path = await manager.complete("j1")

    assert state_path == Path("recipes") / ".login" / "j1" / "auth" / "state.json"
    assert state_path.exists()
    state_path.unlink()
    assert pool.closed_tabs == [("codex08", "record-j1")]        # chỉ đóng tab ghi
    assert pool.hold_calls[-1] == ("codex08", "record-j1", "exit")
    assert not await manager.has("j1")
    assert page.is_closed()   # tab đóng qua close_tab; profile context không bị đụng tới


async def test_cancel_closes_only_the_tab_not_the_profile_context():
    pool = FakeRecordPool(already_open=False)
    profile = FakeProfile("codex08", headless=True)
    manager = LoginSessionManager()
    await manager.start_recording("j1", "record", "https://chat.qwen.ai", Path("x"), pool, profile)

    await manager.cancel("j1")

    assert pool.closed_tabs == [("codex08", "record-j1")]
    assert pool.hold_calls[-1] == ("codex08", "record-j1", "exit")
    assert not await manager.has("j1")


async def test_start_recording_cleans_up_tab_and_hold_on_goto_failure():
    pool = FakeRecordPool(already_open=False)
    profile = FakeProfile("codex08", headless=True)
    manager = LoginSessionManager()

    async def boom(url, **kwargs):
        raise RuntimeError("goto failed")

    real_page_for = pool.page_for

    async def page_for(profile, tab_key):
        page = await real_page_for(profile, tab_key)
        page.goto = boom
        return page

    pool.page_for = page_for

    with pytest.raises(LoginSessionError, match="Unable to start record session"):
        await manager.start_recording("j1", "record", "https://x", Path("x"), pool, profile)

    assert not await manager.has("j1")
    assert pool.closed_tabs == [("codex08", "record-j1")]
    assert pool.hold_calls[-1] == ("codex08", "record-j1", "exit")
