import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from chat2api import jobs


class FakeLoginManager:
    def __init__(self, state_path: Path, *, start_error: Exception | None = None,
                 complete_error: Exception | None = None):
        self.state_path = state_path
        self.start_error = start_error
        self.complete_error = complete_error
        self.sessions: set[str] = set()
        self.started: list[str] = []
        self.recipe_dirs: list[Path] = []
        self.completed: list[str] = []
        self.cancelled: list[str] = []

    async def has(self, job_id: str) -> bool:
        return job_id in self.sessions

    async def start(self, job_id: str, slug: str, url: str, recipe_dir: Path) -> None:
        self.started.append(job_id)
        self.recipe_dirs.append(recipe_dir)
        if self.start_error:
            raise self.start_error
        self.sessions.add(job_id)

    async def complete(self, job_id: str) -> Path:
        self.completed.append(job_id)
        self.sessions.discard(job_id)
        if self.complete_error:
            raise self.complete_error
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text("{}", encoding="utf-8")
        return self.state_path

    async def cancel(self, job_id: str) -> None:
        self.cancelled.append(job_id)
        self.sessions.discard(job_id)


class FakePool:
    def __init__(self, drop_error: Exception | None = None):
        self.dropped: list[str] = []
        self.drop_error = drop_error

    async def drop(self, slug: str) -> None:
        self.dropped.append(slug)
        if self.drop_error:
            raise self.drop_error


class FakeRouter:
    def __init__(self):
        self.reloads = 0

    def reload(self) -> None:
        self.reloads += 1


async def wait_for_status(job_id: str, expected: str) -> dict:
    for _ in range(100):
        job = await jobs.get(job_id)
        if job and job["status"] == expected:
            return job
        await asyncio.sleep(0.001)
    raise AssertionError(f"job {job_id} did not reach {expected}: {await jobs.get(job_id)}")


def test_analyzer_reuses_auth_only_recipe_directory(tmp_path):
    from chat2api.agents.analyzer import _resolve_dir

    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    auth_dir = cfg.recipes_dir / "example" / "auth"
    auth_dir.mkdir(parents=True)
    (auth_dir / "state.json").write_text("{}", encoding="utf-8")

    assert _resolve_dir(cfg, "example", "https://example.test") == (
        cfg.recipes_dir / "example", "example"
    )


@pytest.fixture(autouse=True)
async def clear_jobs():
    jobs.JOBS.clear()
    yield
    tasks = [job.get("task") for job in jobs.JOBS.values()]
    timeouts = [job.get("timeout_task") for job in jobs.JOBS.values()]
    for task in tasks + timeouts:
        if task and not task.done():
            task.cancel()
    await asyncio.gather(*(task for task in tasks + timeouts if task), return_exceptions=True)
    jobs.JOBS.clear()


async def test_login_required_complete_resumes_to_ok(monkeypatch, tmp_path):
    calls = []

    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None, publish_lock=None,
                             headed=False, watch_id=None):
        calls.append(storage_state)
        if len(calls) == 1:
            return {"status": "login_required", "slug": "example"}
        assert storage_state and storage_state.exists()
        return {"status": "ok", "slug": "example", "model_id": "example/web"}

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeLoginManager(cfg.recipes_dir / "example" / "auth" / "state.json")
    pool, router = FakePool(), FakeRouter()

    job_id = jobs.start_integrate("https://example.test", cfg, pool, router, manager)
    waiting = await wait_for_status(job_id, "waiting_login")
    assert waiting["slug"] == "example"
    assert waiting["can_complete_login"] is True

    result = await jobs.complete_login(job_id, cfg, pool, router, manager)
    assert result == {"ok": True, "status": "resuming"}
    await wait_for_status(job_id, "ok")

    assert manager.started == [job_id]
    assert manager.recipe_dirs == [cfg.recipes_dir / ".login" / job_id]
    assert manager.completed == [job_id]
    assert pool.dropped == [f"{job_id}__analyze", f"{job_id}__analyze"]
    assert router.reloads == 1
    assert calls == [None, manager.state_path]
    assert not (cfg.recipes_dir / ".login" / job_id).exists()


async def test_headed_flag_carries_through_login_resume(monkeypatch, tmp_path):
    headed_calls = []

    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None, publish_lock=None,
                             headed=False, watch_id=None):
        headed_calls.append(headed)
        if storage_state is None:
            return {"status": "login_required", "slug": "example"}
        return {"status": "ok", "slug": "example", "model_id": "example/web"}

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeLoginManager(cfg.recipes_dir / "example" / "auth" / "state.json")
    pool, router = FakePool(), FakeRouter()

    job_id = jobs.start_integrate("https://example.test", cfg, pool, router, manager, headed=True)
    await wait_for_status(job_id, "waiting_login")

    await jobs.complete_login(job_id, cfg, pool, router, manager)
    await wait_for_status(job_id, "ok")

    assert headed_calls == [True, True]


async def test_concurrent_same_slug_jobs_use_isolated_analyzer_and_login_dirs(monkeypatch, tmp_path):
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None, publish_lock=None,
                             headed=False, watch_id=None):
        calls.append(analyze_key)
        if len(calls) == 2:
            entered.set()
        await release.wait()
        return {"status": "login_required", "slug": "example"}

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeLoginManager(tmp_path / "unused.json")
    pool, router = FakePool(), FakeRouter()

    first = jobs.start_integrate("https://example.test/a", cfg, pool, router, manager)
    second = jobs.start_integrate("https://example.test/b", cfg, pool, router, manager)
    await entered.wait()
    release.set()
    await wait_for_status(first, "waiting_login")
    await wait_for_status(second, "waiting_login")

    assert set(calls) == {f"{first}__analyze", f"{second}__analyze"}
    assert set(manager.recipe_dirs) == {
        cfg.recipes_dir / ".login" / first,
        cfg.recipes_dir / ".login" / second,
    }
    assert len(set(manager.recipe_dirs)) == 2


async def test_router_reload_failure_never_publishes_ok(monkeypatch, tmp_path):
    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None, publish_lock=None,
                             headed=False, watch_id=None):
        return {"status": "ok", "slug": "example", "model_id": "example/web"}

    class FailingRouter:
        def reload(self):
            raise RuntimeError("cookie=top-secret")

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeLoginManager(tmp_path / "state.json")
    job_id = jobs.start_integrate(
        "https://example.test", cfg, FakePool(), FailingRouter(), manager
    )

    job = await wait_for_status(job_id, "failed")
    assert "top-secret" not in "\n".join(job["log"])
    assert "Không thể tải recipe mới" in "\n".join(job["log"])


async def test_duplicate_complete_cannot_save_twice(monkeypatch, tmp_path):
    release = asyncio.Event()

    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None, publish_lock=None,
                             headed=False, watch_id=None):
        return {"status": "login_required", "slug": "example"}

    class BlockingManager(FakeLoginManager):
        async def complete(self, job_id: str) -> Path:
            self.completed.append(job_id)
            await release.wait()
            return self.state_path

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = BlockingManager(tmp_path / "state.json")
    job_id = jobs.start_integrate("https://example.test", cfg, FakePool(), FakeRouter(), manager)
    await wait_for_status(job_id, "waiting_login")

    first = asyncio.create_task(jobs.complete_login(job_id, cfg, FakePool(), FakeRouter(), manager))
    await wait_for_status(job_id, "resuming")
    with pytest.raises(jobs.InvalidJobState):
        await jobs.complete_login(job_id, cfg, FakePool(), FakeRouter(), manager)
    release.set()
    await first
    assert manager.completed == [job_id]


async def test_cancel_as_analyzer_returns_is_terminal_and_does_not_reload(monkeypatch, tmp_path):
    analyzer_returned = asyncio.Event()
    release_analyzer = asyncio.Event()

    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None, publish_lock=None,
                             headed=False, watch_id=None):
        analyzer_returned.set()
        try:
            await release_analyzer.wait()
        except asyncio.CancelledError:
            pass
        return {"status": "ok", "slug": "example"}

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeLoginManager(tmp_path / "state.json")
    router = FakeRouter()
    job_id = jobs.start_integrate("https://example.test", cfg, FakePool(), router, manager)
    await analyzer_returned.wait()

    cancelling = asyncio.create_task(jobs.cancel_job(job_id, manager))
    await wait_for_status(job_id, "cancelled")
    release_analyzer.set()
    await cancelling
    await asyncio.sleep(0)

    assert (await jobs.get(job_id))["status"] == "cancelled"
    assert router.reloads == 0
    assert manager.started == []


async def test_get_never_returns_terminal_status_with_complete_capability(tmp_path):
    has_started = asyncio.Event()
    release_has = asyncio.Event()

    class BlockingHasManager(FakeLoginManager):
        async def has(self, job_id: str) -> bool:
            has_started.set()
            await release_has.wait()
            return True

    manager = BlockingHasManager(tmp_path / "state.json")
    job = {
        "id": "job", "url": "https://example.test", "slug": "example",
        "status": "waiting_login", "log": [], "login_attempts": 1,
        "login_manager": manager, "lock": asyncio.Lock(), "task": None,
        "timeout_task": None,
    }
    jobs.JOBS["job"] = job

    reading = asyncio.create_task(jobs.get("job"))
    await has_started.wait()
    async with job["lock"]:
        job["status"] = "cancelled"
    release_has.set()

    snapshot = await reading
    assert snapshot["status"] == "cancelled"
    assert snapshot["can_complete_login"] is False


async def test_cancel_while_saving_does_not_resume(monkeypatch, tmp_path):
    release = asyncio.Event()
    calls = 0

    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None, publish_lock=None,
                             headed=False, watch_id=None):
        nonlocal calls
        calls += 1
        return {"status": "login_required", "slug": "example"}

    class BlockingManager(FakeLoginManager):
        async def complete(self, job_id: str) -> Path:
            self.completed.append(job_id)
            self.sessions.discard(job_id)
            await release.wait()
            return self.state_path

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = BlockingManager(tmp_path / "state.json")
    job_id = jobs.start_integrate("https://example.test", cfg, FakePool(), FakeRouter(), manager)
    await wait_for_status(job_id, "waiting_login")

    completing = asyncio.create_task(
        jobs.complete_login(job_id, cfg, FakePool(), FakeRouter(), manager)
    )
    await wait_for_status(job_id, "resuming")
    await jobs.cancel_job(job_id, manager)
    release.set()
    await completing
    await asyncio.sleep(0)

    assert (await jobs.get(job_id))["status"] == "cancelled"
    assert calls == 1


async def test_cancel_caller_cancellation_waits_for_cleanup(monkeypatch, tmp_path):
    cancel_started = asyncio.Event()
    release_cancel = asyncio.Event()

    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None,
                             publish_lock=None, headed=False, watch_id=None):
        return {"status": "login_required", "slug": "example"}

    class BlockingManager(FakeLoginManager):
        async def cancel(self, job_id: str) -> None:
            cancel_started.set()
            await release_cancel.wait()
            await super().cancel(job_id)

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = BlockingManager(tmp_path / "state.json")
    job_id = jobs.start_integrate("https://example.test", cfg, FakePool(), FakeRouter(), manager,
                                  publish_lock=asyncio.Lock())
    await wait_for_status(job_id, "waiting_login")
    staging = jobs.JOBS[job_id]["staging_dir"]
    staging.mkdir(parents=True)

    request = asyncio.create_task(jobs.cancel_job(job_id, manager))
    await cancel_started.wait()
    request.cancel()
    await asyncio.sleep(0)
    assert not request.done()
    assert (await jobs.get(job_id))["status"] == "waiting_login"
    release_cancel.set()
    with pytest.raises(asyncio.CancelledError):
        await request

    assert (await jobs.get(job_id))["status"] == "cancelled"
    assert not staging.exists()


async def test_complete_caller_cancellation_finishes_continuation(monkeypatch, tmp_path):
    complete_started = asyncio.Event()
    release_complete = asyncio.Event()

    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None,
                             publish_lock=None, headed=False, watch_id=None):
        if storage_state is None:
            return {"status": "login_required", "slug": "example"}
        return {"status": "failed", "slug": "example"}

    class BlockingManager(FakeLoginManager):
        async def complete(self, job_id: str) -> Path:
            complete_started.set()
            await release_complete.wait()
            return await super().complete(job_id)

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = BlockingManager(tmp_path / "state.json")
    job_id = jobs.start_integrate("https://example.test", cfg, FakePool(), FakeRouter(), manager,
                                  publish_lock=asyncio.Lock())
    await wait_for_status(job_id, "waiting_login")

    request = asyncio.create_task(jobs.complete_login(job_id, cfg, FakePool(), FakeRouter(), manager))
    await complete_started.wait()
    request.cancel()
    await asyncio.sleep(0)
    assert not request.done()
    release_complete.set()
    with pytest.raises(asyncio.CancelledError):
        await request

    await wait_for_status(job_id, "failed")
    assert not jobs.JOBS[job_id]["staging_dir"].exists()


async def test_cancel_waiting_login(monkeypatch, tmp_path):
    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None, publish_lock=None,
                             headed=False, watch_id=None):
        return {"status": "login_required", "slug": "example"}

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeLoginManager(tmp_path / "state.json")
    job_id = jobs.start_integrate("https://example.test", cfg, FakePool(), FakeRouter(), manager)
    await wait_for_status(job_id, "waiting_login")

    assert await jobs.cancel_job(job_id, manager) == {"ok": True, "status": "cancelled"}
    assert (await jobs.get(job_id))["status"] == "cancelled"
    assert manager.cancelled == [job_id]
    assert await jobs.cancel_job(job_id, manager) == {"ok": True, "status": "cancelled"}


async def test_login_timeout_claims_job_before_session_cleanup(monkeypatch, tmp_path):
    cancel_started = asyncio.Event()
    release_cancel = asyncio.Event()

    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None, publish_lock=None,
                             headed=False, watch_id=None):
        return {"status": "login_required", "slug": "example"}

    class BlockingCancelManager(FakeLoginManager):
        async def cancel(self, job_id: str) -> None:
            cancel_started.set()
            await release_cancel.wait()
            await super().cancel(job_id)

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    monkeypatch.setattr(jobs, "LOGIN_TIMEOUT_SECONDS", 0.01)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = BlockingCancelManager(tmp_path / "state.json")
    job_id = jobs.start_integrate("https://example.test", cfg, FakePool(), FakeRouter(), manager)

    await cancel_started.wait()
    snapshot = await jobs.get(job_id)
    assert snapshot["status"] == "waiting_login"
    assert snapshot["can_complete_login"] is False
    with pytest.raises(jobs.InvalidJobState):
        await jobs.complete_login(job_id, cfg, FakePool(), FakeRouter(), manager)
    assert manager.completed == []
    with pytest.raises(jobs.InvalidJobState):
        await jobs.cancel_job(job_id, manager)

    release_cancel.set()
    await wait_for_status(job_id, "login_timeout")
    assert manager.cancelled == [job_id]
    assert jobs.JOBS[job_id]["timeout_task"] is None


async def test_login_open_failure_sets_failed_without_secret(monkeypatch, tmp_path):
    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None, publish_lock=None,
                             headed=False, watch_id=None):
        return {"status": "login_required", "slug": "example"}

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeLoginManager(
        tmp_path / "state.json", start_error=RuntimeError("cookie=top-secret")
    )
    job_id = jobs.start_integrate("https://example.test", cfg, FakePool(), FakeRouter(), manager)

    job = await wait_for_status(job_id, "failed")
    text = "\n".join(job["log"])
    assert "python -m chat2api login example" in text
    assert "top-secret" not in text


async def test_login_save_failure_is_terminal_and_sanitized(monkeypatch, tmp_path):
    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None, publish_lock=None,
                             headed=False, watch_id=None):
        return {"status": "login_required", "slug": "example"}

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeLoginManager(
        tmp_path / "state.json", complete_error=RuntimeError("cookie=top-secret")
    )
    job_id = jobs.start_integrate("https://example.test", cfg, FakePool(), FakeRouter(), manager)
    await wait_for_status(job_id, "waiting_login")

    with pytest.raises(jobs.LoginSaveFailed):
        await jobs.complete_login(job_id, cfg, FakePool(), FakeRouter(), manager)
    job = await jobs.get(job_id)
    assert job["status"] == "failed"
    text = "\n".join(job["log"])
    assert "python -m chat2api login example" in text
    assert "top-secret" not in text


async def test_pool_drop_failure_is_sanitized(monkeypatch, tmp_path):
    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None, publish_lock=None,
                             headed=False, watch_id=None):
        return {"status": "login_required", "slug": "example"}

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeLoginManager(tmp_path / "state.json")
    pool = FakePool(RuntimeError("context secret"))
    job_id = jobs.start_integrate("https://example.test", cfg, pool, FakeRouter(), manager)

    job = await wait_for_status(job_id, "failed")
    assert "Không thể reset analyzer context" in "\n".join(job["log"])
    assert "context secret" not in "\n".join(job["log"])
    assert manager.started == []


async def test_shutdown_cancels_jobs_and_waiting_sessions(tmp_path):
    manager = FakeLoginManager(tmp_path / "state.json")
    waiting = {
        "id": "waiting", "url": "https://example.test", "slug": "example",
        "status": "waiting_login", "log": [], "login_attempts": 1,
        "login_manager": manager, "lock": asyncio.Lock(), "task": None,
        "timeout_task": None,
    }
    running_release = asyncio.Event()
    running_task = asyncio.create_task(running_release.wait())
    running = {
        "id": "running", "url": "https://example.test", "slug": None,
        "status": "running", "log": [], "login_attempts": 0,
        "login_manager": manager, "lock": asyncio.Lock(), "task": running_task,
        "timeout_task": None,
    }
    manager.sessions.add("waiting")
    jobs.JOBS.update(waiting=waiting, running=running)

    await jobs.shutdown(manager)

    assert waiting["status"] == "cancelled"
    assert running["status"] == "cancelled"
    assert running_task.done()
    assert manager.cancelled == ["waiting"]


async def test_fails_after_two_incomplete_login_attempts(monkeypatch, tmp_path):
    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None, publish_lock=None,
                             headed=False, watch_id=None):
        return {"status": "login_required", "slug": "example"}

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeLoginManager(tmp_path / "state.json")
    pool, router = FakePool(), FakeRouter()
    job_id = jobs.start_integrate("https://example.test", cfg, pool, router, manager)

    for _ in range(2):
        await wait_for_status(job_id, "waiting_login")
        await jobs.complete_login(job_id, cfg, pool, router, manager)
    job = await wait_for_status(job_id, "failed")
    assert manager.started == [job_id, job_id]
    assert any("Đăng nhập chưa hoàn tất" in line for line in job["log"])
