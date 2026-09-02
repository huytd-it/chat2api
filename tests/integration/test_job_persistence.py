"""Job integrate ghi xuống DB (pha 1 của docs/design-v2.md §7).

JOBS trong RAM vẫn là nguồn đọc; những test này chỉ kiểm tra rằng trạng thái và
từng dòng log cũng rơi xuống bảng `job` / `job_log` để sống sót qua restart.
"""

import asyncio
from types import SimpleNamespace

import pytest

from chat2api import jobs, store

from test_integrate_login_flow import FakeLoginManager, FakePool, FakeRouter, wait_for_status


@pytest.fixture
async def db(tmp_path):
    jobs.JOBS.clear()
    s = store.connect(tmp_path / "chat2api.db")
    s.migrate()
    try:
        yield s
    finally:
        tasks = [j.get(k) for j in jobs.JOBS.values() for k in ("task", "timeout_task")]
        for task in tasks:
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*(t for t in tasks if t), return_exceptions=True)
        jobs.JOBS.clear()
        store.shutdown()


async def test_job_row_follows_status_transitions(db, monkeypatch, tmp_path):
    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None,
                             publish_lock=None, headed=False, **kwargs):
        log("đang phân tích trang")
        return {"status": "ok", "slug": "example", "model_id": "example/web"}

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeLoginManager(cfg.recipes_dir / "example" / "auth" / "state.json")

    job_id = jobs.start_integrate("https://example.test", cfg, FakePool(), FakeRouter(), manager)
    await wait_for_status(job_id, "ok")
    db.flush(timeout=10)

    row = db.query("SELECT * FROM job WHERE id = ?", (job_id,))[0]
    assert (row["kind"], row["status"], row["slug"]) == ("integrate", "ok", "example")
    assert row["url"] == "https://example.test"
    assert row["headed"] == 0
    assert row["updated_at"] >= row["created_at"] > 0


async def test_job_log_lines_persist_in_order(db, monkeypatch, tmp_path):
    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None,
                             publish_lock=None, headed=False, **kwargs):
        log("mở trang")
        log("tìm thấy ô nhập")
        return {"status": "ok", "slug": "example"}

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeLoginManager(cfg.recipes_dir / "example" / "auth" / "state.json")

    job_id = jobs.start_integrate("https://example.test", cfg, FakePool(), FakeRouter(), manager)
    await wait_for_status(job_id, "ok")
    db.flush(timeout=10)

    rows = db.query("SELECT seq, line FROM job_log WHERE job_id = ? ORDER BY seq", (job_id,))
    assert [(r["seq"], r["line"]) for r in rows] == [(0, "mở trang"), (1, "tìm thấy ô nhập")]
    # Cùng nội dung với list trong RAM — hai tầng không được lệch nhau.
    assert list(jobs.JOBS[job_id]["log"]) == [r["line"] for r in rows]


async def test_headed_and_login_attempts_recorded(db, monkeypatch, tmp_path):
    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None,
                             publish_lock=None, headed=False, **kwargs):
        return {"status": "login_required", "slug": "example"}

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeLoginManager(cfg.recipes_dir / "example" / "auth" / "state.json")

    job_id = jobs.start_integrate("https://example.test", cfg, FakePool(), FakeRouter(), manager,
                                  headed=True)
    await wait_for_status(job_id, "waiting_login")
    db.flush(timeout=10)

    row = db.query("SELECT status, headed, login_attempts FROM job WHERE id = ?", (job_id,))[0]
    assert (row["status"], row["headed"], row["login_attempts"]) == ("waiting_login", 1, 1)


async def test_cancel_recorded(db, monkeypatch, tmp_path):
    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None,
                             publish_lock=None, headed=False, **kwargs):
        return {"status": "login_required", "slug": "example"}

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeLoginManager(cfg.recipes_dir / "example" / "auth" / "state.json")

    job_id = jobs.start_integrate("https://example.test", cfg, FakePool(), FakeRouter(), manager)
    await wait_for_status(job_id, "waiting_login")
    await jobs.cancel_job(job_id, manager)
    db.flush(timeout=10)

    assert db.query("SELECT status FROM job WHERE id = ?", (job_id,))[0]["status"] == "cancelled"


async def test_jobs_run_unchanged_without_store(monkeypatch, tmp_path):
    """Không có kho (CLI, hoặc DB hỏng) thì job vẫn chạy bình thường."""
    store.shutdown()
    jobs.JOBS.clear()
    assert store.default() is None

    async def fake_integrate(url, pool, cfg, log, storage_state=None, analyze_key=None,
                             publish_lock=None, headed=False, **kwargs):
        log("một dòng")
        return {"status": "ok", "slug": "example"}

    monkeypatch.setattr(jobs, "integrate", fake_integrate)
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeLoginManager(cfg.recipes_dir / "example" / "auth" / "state.json")

    job_id = jobs.start_integrate("https://example.test", cfg, FakePool(), FakeRouter(), manager)
    job = await wait_for_status(job_id, "ok")
    assert job["log"] == ["một dòng"]
    jobs.JOBS.clear()
