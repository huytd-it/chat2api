"""'Ghi thao tác' (record) phải mở đúng persistent context của profile đã chọn
trên UI, không phải browser ẩn danh trắng phiên (xem chat2api/login_sessions.py
LoginSessionManager.start_recording). Đây là lớp wiring ở jobs.py: profile
người dùng chọn (`job["profile"]` = {"id","name"}) phải được resolve ra bản
đầy đủ (`profiles.get_profile`, dạng BrowserPool dùng được) rồi truyền xuống
`login_manager.start_recording(..., pool, profile)`.
"""

import asyncio
from types import SimpleNamespace

import pytest

from chat2api import jobs, profiles, store

from test_integrate_login_flow import FakeRouter, wait_for_status


class FakeRecordLoginManager:
    def __init__(self):
        self.start_recording_calls: list[tuple] = []
        # jobs._open_record đọc thẳng `_sessions` (đường nội bộ của
        # LoginSessionManager thật) để lấy `trace` sống — fake không giữ
        # session nào nên để trống là đủ, code sẽ rơi về `trace_of()`.
        self._sessions: dict = {}
        # Callback nhận event trace, để test giả lập người dùng thao tác.
        self.on_trace = None

    async def has(self, job_id: str) -> bool:
        return any(call[0] == job_id for call in self.start_recording_calls)

    async def start_recording(self, job_id, slug, url, recipe_dir, pool, profile, on_trace=None):
        self.start_recording_calls.append((job_id, slug, url, recipe_dir, pool, profile))
        self.on_trace = on_trace

    async def trace_of(self, job_id: str) -> list[dict]:
        return []

    async def cancel(self, job_id: str) -> None:
        pass


class FakePool:
    async def drop(self, slug: str) -> None:
        pass


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


async def test_start_record_passes_the_selected_profile_through_to_login_manager(db, tmp_path):
    profile_row = profiles.ensure_profile("codex08", tmp_path / "profiles")
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeRecordLoginManager()
    pool = FakePool()

    job_id = jobs.start_record(
        "https://chat.qwen.ai", cfg, pool, router=FakeRouter(), login_manager=manager,
        profile={"id": profile_row.id, "name": profile_row.name},
    )
    await jobs.JOBS[job_id]["task"]

    assert len(manager.start_recording_calls) == 1
    called_job_id, slug, url, recipe_dir, called_pool, called_profile = manager.start_recording_calls[0]
    assert called_job_id == job_id
    assert url == "https://chat.qwen.ai"
    assert recipe_dir == cfg.recipes_dir / ".login" / job_id
    assert called_pool is pool
    # Đúng profile người dùng chọn trên UI (không phải profile mặc định/khác).
    assert called_profile.name == "codex08"
    assert (await jobs.get(job_id))["status"] == "recording"


async def test_start_record_fails_clearly_when_the_selected_profile_is_gone(db, tmp_path):
    """Profile bị xóa giữa lúc chọn trên UI và lúc job thật sự chạy — báo lỗi rõ
    thay vì âm thầm rơi về ghi ẩn danh (đúng thứ tính năng chọn profile để tránh)."""
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeRecordLoginManager()

    job_id = jobs.start_record(
        "https://chat.qwen.ai", cfg, FakePool(), router=FakeRouter(), login_manager=manager,
        profile={"id": 999, "name": "ghost-profile"},
    )
    job = await wait_for_status(job_id, "failed")

    assert manager.start_recording_calls == []
    assert any("profile" in line.lower() for line in job["log"])


# ---------------------------------------------------------------- đoạn ghi
# Ghi thao tác chia theo việc: người dùng chọn loại TRƯỚC mỗi đoạn, nên mỗi
# event trace phải mang đúng nhãn của đoạn đang mở lúc nó xảy ra. Nhãn này là
# thứ analyzer dựa vào để dựng `flows` — sai nhãn là sai recipe.

async def _start_recording(cfg, manager, tmp_path):
    profile_row = profiles.ensure_profile("codex08", tmp_path / "profiles")
    job_id = jobs.start_record(
        "https://site.tld", cfg, FakePool(), router=FakeRouter(), login_manager=manager,
        profile={"id": profile_row.id, "name": profile_row.name},
    )
    await jobs.JOBS[job_id]["task"]
    return job_id


async def test_events_carry_the_label_of_the_segment_open_at_the_time(db, tmp_path):
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeRecordLoginManager()
    job_id = await _start_recording(cfg, manager, tmp_path)

    # Thao tác trước khi mở đoạn nào: ghi nhận nhưng không gắn nhãn.
    before = {"kind": "click", "selector": ".cookie-ok"}
    manager.on_trace(before)

    await jobs.set_record_segment(job_id, "select_model", "start")
    picked = {"kind": "click", "selector": ".model-option"}
    manager.on_trace(picked)

    await jobs.set_record_segment(job_id, "image", "start")
    typed = {"kind": "fill", "selector": "#box", "value": "a cat"}
    manager.on_trace(typed)

    assert "flow" not in before
    assert picked["flow"] == "select_model"
    assert typed["flow"] == "image"


async def test_starting_a_segment_closes_the_previous_one(db, tmp_path):
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeRecordLoginManager()
    job_id = await _start_recording(cfg, manager, tmp_path)

    await jobs.set_record_segment(job_id, "text", "start")
    snapshot = await jobs.set_record_segment(job_id, "image", "start")

    assert snapshot["segment"] == "image"
    assert [s["flow"] for s in snapshot["segments"]] == ["text", "image"]
    assert [s["open"] for s in snapshot["segments"]] == [False, True]


async def test_stopping_a_segment_leaves_later_events_unlabelled(db, tmp_path):
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeRecordLoginManager()
    job_id = await _start_recording(cfg, manager, tmp_path)

    await jobs.set_record_segment(job_id, "text", "start")
    await jobs.set_record_segment(job_id, None, "stop")
    after = {"kind": "click", "selector": ".scroll"}
    manager.on_trace(after)

    assert "flow" not in after
    assert (await jobs.get(job_id))["segment"] is None


async def test_reopening_a_flow_continues_the_same_segment(db, tmp_path):
    """Ghi thiếu một bước thì quay lại ghi bù, không mất đoạn đã ghi."""
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeRecordLoginManager()
    job_id = await _start_recording(cfg, manager, tmp_path)

    await jobs.set_record_segment(job_id, "text", "start")
    manager.on_trace({"kind": "fill", "selector": "#box"})
    await jobs.set_record_segment(job_id, "image", "start")
    snapshot = await jobs.set_record_segment(job_id, "text", "start")
    manager.on_trace({"kind": "press", "selector": "#box", "key": "Enter"})

    text_segment = next(s for s in snapshot["segments"] if s["flow"] == "text")
    assert [s["flow"] for s in snapshot["segments"]] == ["text", "image"]
    assert (await jobs.get(job_id))["segments"][0]["events"] == 2
    assert text_segment["open"] is True


async def test_segments_cannot_be_changed_once_recording_has_ended(db, tmp_path):
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeRecordLoginManager()
    job_id = await _start_recording(cfg, manager, tmp_path)

    async with jobs.JOBS[job_id]["lock"]:
        jobs.JOBS[job_id]["status"] = "resuming_record"

    with pytest.raises(jobs.InvalidJobState):
        await jobs.set_record_segment(job_id, "text", "start")


async def test_an_unknown_flow_is_refused(db, tmp_path):
    cfg = SimpleNamespace(recipes_dir=tmp_path / "recipes")
    manager = FakeRecordLoginManager()
    job_id = await _start_recording(cfg, manager, tmp_path)

    with pytest.raises(jobs.InvalidJobState):
        await jobs.set_record_segment(job_id, "audio", "start")
