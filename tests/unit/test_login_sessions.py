from pathlib import Path

import pytest

from chat2api.login_sessions import LoginSessionError, LoginSessionManager


class FakePage:
    def __init__(self, fail=False):
        self.urls = []
        self.fail = fail

    async def goto(self, url, **kwargs):
        self.urls.append(url)
        if self.fail:
            raise RuntimeError("goto failed")


class FakeContext:
    def __init__(self, fail_new_page=False, fail_goto=False, fail_save=False):
        self.page = FakePage(fail_goto)
        self.closed = False
        self.saved = None
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

    async def new_context(self):
        if self.fail_new_context:
            raise RuntimeError("new_context failed")
        return self.context

    async def close(self):
        self.closed = True


class FakeLauncher:
    def __init__(self, fail_launch=False, **browser_kwargs):
        self.browser = FakeBrowser(**browser_kwargs)
        self.fail_launch = fail_launch

    async def launch(self, **kwargs):
        assert kwargs["headless"] is False
        if self.fail_launch:
            raise RuntimeError("launch failed")
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

    assert manager.has("j1")
    assert pw.chromium.browser.context.page.urls == ["https://site.example"]
    state = await manager.complete("j1")
    assert state == tmp_path / "site" / "auth" / "state.json"
    assert state.exists()
    assert not manager.has("j1")
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
    assert not manager.has("j1")


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

    assert not manager.has("j1")
    assert pw.stopped
    if failure != "launch":
        assert pw.chromium.browser.closed


async def test_complete_failure_closes_and_forgets_session(tmp_path):
    pw = FakePW(fail_save=True)
    manager = LoginSessionManager(playwright_factory=lambda: pw)
    await manager.start("j1", "site", "https://x", tmp_path)

    with pytest.raises(LoginSessionError, match="Unable to save login session"):
        await manager.complete("j1")

    assert pw.chromium.browser.closed
    assert not manager.has("j1")


async def test_close_all_closes_sessions_and_stops_shared_driver(tmp_path):
    pw = FakePW()
    manager = LoginSessionManager(playwright_factory=lambda: pw)
    await manager.start("j1", "site", "https://x", tmp_path)

    await manager.close_all()

    assert pw.chromium.browser.closed
    assert pw.stopped
    assert not manager.has("j1")


async def test_missing_cancel_is_noop():
    manager = LoginSessionManager(playwright_factory=lambda: FakePW())

    await manager.cancel("missing")
