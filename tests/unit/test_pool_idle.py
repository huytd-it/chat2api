"""Vòng dọn RAM: đóng Chromium headless rảnh lâu, bỏ job cũ khỏi JOBS."""
import asyncio
import time
from types import SimpleNamespace

from chat2api import jobs
from chat2api.browserpool import BrowserPool


class FakeContext:
    def __init__(self):
        self.closed = False
        self.pages = []

    async def close(self):
        self.closed = True


def _router():
    return SimpleNamespace(providers={})


def _pool_with(slugs, headless=True):
    pool = BrowserPool()
    for slug in slugs:
        pool._contexts[slug] = FakeContext()
        pool._context_headless[slug] = headless
        pool._touch(f"ctx:{slug}")
    return pool


async def test_close_idle_only_closes_contexts_idle_long_enough():
    pool = _pool_with(["old", "fresh"])
    pool._last_used["ctx:old"] = time.monotonic() - 1000

    closed = await pool.close_background(_router(), idle_seconds=600)

    assert closed == 1
    assert list(pool._contexts) == ["fresh"]
    assert "ctx:old" not in pool._last_used


async def test_close_idle_keeps_headed_windows():
    pool = _pool_with(["visible"], headless=False)
    pool._last_used["ctx:visible"] = time.monotonic() - 1000

    assert await pool.close_background(_router(), idle_seconds=600) == 0
    assert pool.size == 1


async def test_close_idle_skips_busy_profile():
    pool = BrowserPool()
    ctx = FakeContext()
    pool._profiles["p"] = ctx
    pool._profile_headless["p"] = True
    pool._last_used["profile:p"] = time.monotonic() - 1000

    async with pool.hold("p"):
        pool._last_used["profile:p"] = time.monotonic() - 1000
        assert await pool.close_background(_router(), idle_seconds=600) == 0
    # hold() vừa thả ra cũng tính là vừa dùng.
    assert await pool.close_background(_router(), idle_seconds=600) == 0
    assert not ctx.closed


async def test_close_background_without_idle_closes_all_headless():
    pool = _pool_with(["a", "b"])

    assert await pool.close_background(_router()) == 2
    assert pool.size == 0


async def test_prune_drops_only_old_finished_jobs(monkeypatch):
    monkeypatch.setattr(jobs, "JOBS", {})
    monkeypatch.setattr(jobs, "_ENDED_AT", {})
    running_task = asyncio.get_running_loop().create_future()
    jobs.JOBS.update({
        "done": {"status": "ok", "task": None},
        "run": {"status": "running", "task": None},
        "cleanup": {"status": "failed", "task": running_task},
    })

    assert jobs.prune(3600) == 0  # vừa thấy kết thúc, chưa đủ hạn
    jobs._ENDED_AT["done"] -= 4000
    assert jobs.prune(3600) == 1
    assert set(jobs.JOBS) == {"run", "cleanup"}
    running_task.cancel()
