import asyncio
import re
import shutil
import uuid
from contextlib import suppress
from pathlib import Path

import yaml

from . import accounts, applog, profiles as profiles_mod, store
from .agents.analyzer import integrate

LOGIN_TIMEOUT_SECONDS = 600
MAX_LOGIN_ATTEMPTS = 2
TERMINAL_STATUSES = {"ok", "failed", "cancelled", "login_timeout"}
CANCELLABLE_STATUSES = {"running", "waiting_login", "resuming"}
JOBS: dict[str, dict] = {}


class _JobLog(list):
    """Log của một job; mỗi dòng append vào đây cũng rơi xuống bảng `job_log`.

    Là subclass của list chứ không phải lớp bọc, vì `job["log"].append` được
    truyền thẳng làm callback cho analyzer, và `list(...)` / `len(...)` trên nó
    đang được dùng ở nhiều chỗ.
    """

    __slots__ = ("_job_id",)

    def __init__(self, job_id: str):
        super().__init__()
        self._job_id = job_id

    def append(self, line: str) -> None:
        seq = len(self)
        super().append(line)
        db = store.default()
        if db is not None:
            db.submit(
                "INSERT OR IGNORE INTO job_log(job_id, seq, ts, level, line)"
                " VALUES (?, ?, ?, 'info', ?)",
                (self._job_id, seq, store.now_ms(), line))


def _save(job: dict) -> None:
    """Ghi trạng thái job xuống DB (bắn-rồi-quên, không chờ, không ném lỗi).

    JOBS vẫn là nguồn đọc; bảng `job` để job sống sót qua restart và xem lại
    được sau này. Gọi tại mỗi lần đổi status.
    """
    db = store.default()
    if db is None:
        return
    now = store.now_ms()
    db.submit(
        "INSERT INTO job(id, kind, url, slug, status, headed, login_attempts,"
        "                created_at, updated_at)"
        " VALUES (?, 'integrate', ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(id) DO UPDATE SET"
        "   slug = excluded.slug, status = excluded.status,"
        "   login_attempts = excluded.login_attempts, updated_at = excluded.updated_at",
        (job["id"], job["url"], job.get("slug"), job["status"],
         1 if job.get("headed") else 0, job["login_attempts"], now, now))


async def _critical(coro):
    task = coro if isinstance(coro, asyncio.Task) else asyncio.create_task(coro)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        finally:
            raise


class JobNotFound(LookupError):
    pass


class InvalidJobState(RuntimeError):
    pass


class LoginSaveFailed(RuntimeError):
    pass


class ContextResetFailed(RuntimeError):
    pass


def _login_failure(job: dict, message: str) -> None:
    slug = job.get("slug") or "<slug>"
    job["log"].append(message)
    job["log"].append(f"Chạy trực tiếp trên desktop hoặc dùng: python -m chat2api login {slug}")
    job["status"] = "failed"
    _save(job)
    applog.log(f"integrate: thất bại {job['id']} ({slug}): {message}", "error")
    _cleanup_staging(job)


def _cancel_timeout(job: dict) -> None:
    task = job.get("timeout_task")
    if task and task is not asyncio.current_task() and not task.done():
        task.cancel()
    job["timeout_task"] = None


def _cleanup_staging(job: dict) -> None:
    staging_dir = job.get("staging_dir")
    if staging_dir:
        shutil.rmtree(staging_dir, ignore_errors=True)


async def _finish_login_timeout(job: dict, login_manager) -> None:
    try:
        await login_manager.cancel(job["id"])
    finally:
        _cleanup_staging(job)
    async with job["lock"]:
        if job["status"] == "waiting_login" and job.get("login_timeout_claimed"):
            job["status"] = "login_timeout"
            job["log"].append("Hết thời gian chờ đăng nhập.")
            job["timeout_task"] = None
            _save(job)


async def _login_timeout(job: dict, login_manager) -> None:
    current = asyncio.current_task()
    try:
        await asyncio.sleep(LOGIN_TIMEOUT_SECONDS)
        async with job["lock"]:
            if job["status"] != "waiting_login":
                return
            job["login_timeout_claimed"] = True
        await _critical(_finish_login_timeout(job, login_manager))
    except asyncio.CancelledError:
        if not job.get("login_timeout_claimed"):
            return
        raise
    finally:
        async with job["lock"]:
            if job.get("timeout_task") is current:
                job["timeout_task"] = None


async def _open_login(job: dict, expected_status: str, cfg, login_manager) -> None:
    async with job["lock"]:
        if job["status"] != expected_status:
            return
        if job["login_attempts"] >= MAX_LOGIN_ATTEMPTS:
            _login_failure(job, "Đăng nhập chưa hoàn tất sau 2 lần thử.")
            return
        slug = job["slug"]
        if not re.fullmatch(r"[a-z0-9-]+", slug or ""):
            _login_failure(job, "Không thể mở browser desktop: slug không hợp lệ.")
            return

    try:
        await login_manager.start(job["id"], slug, job["url"], job["staging_dir"])
    except asyncio.CancelledError:
        raise
    except Exception:
        async with job["lock"]:
            if job["status"] == expected_status:
                _login_failure(job, "Không thể mở browser desktop trên máy chạy chat2api.")
        return

    cancel_session = False
    async with job["lock"]:
        if job["status"] != expected_status:
            cancel_session = True
        else:
            job["login_attempts"] += 1
            job["status"] = "waiting_login"
            job["log"].append("Đã mở cửa sổ Chromium. Hãy đăng nhập rồi xác nhận.")
            job["timeout_task"] = asyncio.create_task(_login_timeout(job, login_manager))
            _save(job)
    if cancel_session:
        await login_manager.cancel(job["id"])


def _attach_login_to_profile(job: dict, cfg) -> None:
    """Chuyển login vừa lưu (nếu có) từ recipe mới sang profile đã chọn.

    Không có bước này, `auth/state.json` gắn thẳng trong recipe sẽ nằm im cho
    tới lần restart sau, lúc đó `accounts.migrate_legacy` + import mirror nó
    thành một profile TỰ SINH (tên ghép domain+label) hoàn toàn ngoài tầm kiểm
    soát của tab Profiles — đúng thứ người dùng chọn profile trước để tránh.
    Chạy ngay sau khi integrate xong thì account đi thẳng vào profile đã chọn,
    không còn gì để migrate_legacy nhặt lên nữa.
    """
    profile = job.get("profile")
    slug = job.get("slug")
    if not profile or not slug:
        return
    recipe_path = cfg.recipes_dir / slug / "recipe.yaml"
    if not recipe_path.exists():
        return
    try:
        data = yaml.safe_load(recipe_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return
    login = data.get("login")
    if not isinstance(login, dict) or not login.get("storage_state"):
        return  # site không cần đăng nhập (dùng thử ẩn danh) — không có gì để gắn
    state_path = cfg.recipes_dir / slug / login["storage_state"]
    if not state_path.exists():
        return
    domain = accounts.domain_of(data.get("url", ""))
    if not accounts.valid_domain(domain):
        return
    target = accounts.account_path(cfg.recipes_dir, domain, profile["name"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(state_path.read_bytes())
    state_path.unlink(missing_ok=True)
    login.pop("storage_state", None)
    if not login:
        data.pop("login", None)
    recipe_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    profiles_mod.add_account_with_state(profile["id"], domain, profile["name"], str(target))


async def _run_analyzer(job: dict, expected_status: str, cfg, pool, router, login_manager,
                        storage_state: Path | None = None) -> None:
    try:
        analyze_key = f"{job['id']}__analyze"
        try:
            result = await integrate(
                job["url"], pool, cfg, job["log"].append,
                storage_state=storage_state, analyze_key=analyze_key,
                publish_lock=job["publish_lock"], headed=job.get("headed", False),
            )
        finally:
            try:
                await pool.drop(analyze_key)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                raise ContextResetFailed from error
        async with job["lock"]:
            if job["status"] != expected_status or job.get("cancel_claimed", False):
                return
            job["slug"] = result.get("slug", job.get("slug"))
            open_login = result.get("status") == "login_required"

        if open_login:
            await _open_login(job, expected_status, cfg, login_manager)
            return

        async with job["lock"]:
            if job["status"] != expected_status or job.get("cancel_claimed", False):
                return
            if result.get("status") == "ok" and job.get("profile"):
                try:
                    async with job["publish_lock"]:
                        await asyncio.to_thread(_attach_login_to_profile, job, cfg)
                except Exception as error:
                    job["log"].append(f"Cảnh báo: không gắn được đăng nhập vào profile: {error}")
            if result.get("status") == "ok" and router is not None:
                try:
                    router.reload()
                except Exception:
                    job["log"].append("Không thể tải recipe mới.")
                    job["status"] = "failed"
                    _save(job)
                    _cleanup_staging(job)
                    return
            # "log" nằm trong danh sách loại trừ để _JobLog không bị thay bằng
            # list thường — mất luôn đường ghi xuống job_log.
            job.update({key: value for key, value in result.items()
                        if key not in {"task", "timeout_task", "lock", "log"}})
            job["status"] = result.get("status", "failed")
            _save(job)
            if job["status"] in TERMINAL_STATUSES:
                level = "info" if job["status"] == "ok" else "warn"
                applog.log(f"integrate: {job['id']} ({job.get('slug')}) -> {job['status']}", level)
                _cleanup_staging(job)
    except asyncio.CancelledError:
        raise
    except ContextResetFailed:
        async with job["lock"]:
            if job["status"] == expected_status:
                job["log"].append("Không thể reset analyzer context.")
                job["status"] = "failed"
                _save(job)
                applog.log(f"integrate: {job['id']} lỗi reset context", "error")
                _cleanup_staging(job)
    except Exception as error:
        async with job["lock"]:
            if job["status"] == expected_status:
                job["log"].append(f"error: {error}")
                job["status"] = "failed"
                _save(job)
                applog.log(f"integrate: {job['id']} lỗi: {error}", "error")
                _cleanup_staging(job)


def start_integrate(url: str, cfg, pool, router=None, login_manager=None,
                    publish_lock=None, headed: bool = False,
                    profile: dict | None = None) -> str:
    """`profile` (khi có) là {"id", "name"} của profile người dùng đã chọn
    trước khi bấm tích hợp — xem `_attach_login_to_profile`."""
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "url": url,
        "slug": None,
        "status": "running",
        "log": _JobLog(job_id),
        "task": None,
        "timeout_task": None,
        "login_attempts": 0,
        "login_timeout_claimed": False,
        "cancel_claimed": False,
        "login_manager": login_manager,
        "publish_lock": publish_lock or asyncio.Lock(),
        "staging_dir": cfg.recipes_dir / ".login" / job_id,
        "headed": headed,
        "profile": profile,
        "lock": asyncio.Lock(),
    }
    JOBS[job_id] = job
    _save(job)
    job["task"] = asyncio.create_task(
        _run_analyzer(job, "running", cfg, pool, router, login_manager)
    )
    return job_id


async def _complete_login(job: dict, cfg, pool, router, login_manager) -> dict:
    try:
        state_path = await login_manager.complete(job["id"])
    except Exception:
        async with job["lock"]:
            if job["status"] == "resuming":
                _login_failure(job, "Không thể lưu session đăng nhập.")
        raise LoginSaveFailed

    analyzer = asyncio.create_task(
        _run_analyzer(job, "resuming", cfg, pool, router, login_manager,
                      storage_state=state_path)
    )
    async with job["lock"]:
        job["task"] = analyzer
    await analyzer
    return {"ok": True, "status": "resuming"}


async def complete_login(job_id: str, cfg, pool, router, login_manager) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise JobNotFound

    async with job["lock"]:
        if job["status"] != "waiting_login" or job.get("login_timeout_claimed", False):
            raise InvalidJobState
    if not await login_manager.has(job_id):
        raise InvalidJobState
    async with job["lock"]:
        if job["status"] != "waiting_login" or job.get("login_timeout_claimed", False):
            raise InvalidJobState
        job["status"] = "resuming"
        _save(job)
        _cancel_timeout(job)
        continuation = asyncio.create_task(
            _complete_login(job, cfg, pool, router, login_manager)
        )
        job["task"] = continuation
    try:
        return await _critical(continuation)
    except asyncio.CancelledError:
        if continuation.cancelled() and not asyncio.current_task().cancelling():
            return {"ok": True, "status": job["status"]}
        raise


async def _cancel_job(job: dict, login_manager, task) -> dict:
    try:
        await login_manager.cancel(job["id"])
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()
        if task and task is not asyncio.current_task():
            with suppress(asyncio.CancelledError):
                await task
    finally:
        _cleanup_staging(job)
    async with job["lock"]:
        if job.get("cancel_claimed"):
            job["status"] = "cancelled"
            _save(job)
    return {"ok": True, "status": "cancelled"}


async def cancel_job(job_id: str, login_manager) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise JobNotFound

    async with job["lock"]:
        if job["status"] == "cancelled":
            return {"ok": True, "status": "cancelled"}
        if (job.get("login_timeout_claimed", False) or job.get("cancel_claimed", False)
                or job["status"] not in CANCELLABLE_STATUSES):
            raise InvalidJobState
        job["cancel_claimed"] = True
        _cancel_timeout(job)
        task = job.get("task")
    return await _critical(_cancel_job(job, login_manager, task))


async def _finish_shutdown(login_manager, waiting_ids, tasks) -> None:
    cleanup = [login_manager.cancel(job_id) for job_id in waiting_ids]
    cleanup.extend(tasks)
    try:
        if cleanup:
            await asyncio.gather(*cleanup, return_exceptions=True)
    finally:
        for job in list(JOBS.values()):
            _cleanup_staging(job)


async def shutdown(login_manager) -> None:
    current = asyncio.current_task()
    tasks = set()
    waiting_ids = []
    for job in list(JOBS.values()):
        async with job["lock"]:
            if job["status"] in TERMINAL_STATUSES:
                continue
            if job["status"] == "waiting_login":
                waiting_ids.append(job["id"])
            job["status"] = "cancelled"
            _save(job)
            for key in ("task", "timeout_task"):
                task = job.get(key)
                if task and task is not current and not task.done():
                    task.cancel()
                    tasks.add(task)
                job[key] = None
    await _critical(_finish_shutdown(login_manager, waiting_ids, tasks))


async def get(job_id: str) -> dict | None:
    job = JOBS.get(job_id)
    if job is None:
        return None
    async with job["lock"]:
        snapshot = {
            "id": job["id"],
            "url": job["url"],
            "slug": job.get("slug"),
            "status": job["status"],
            "log": list(job["log"]),
            "login_attempts": job["login_attempts"],
            "can_complete_login": False,
        }
        manager = job.get("login_manager")
        waiting = job["status"] == "waiting_login" and not job.get("login_timeout_claimed", False)
    if waiting and manager is not None and await manager.has(job_id):
        async with job["lock"]:
            if job["status"] == "waiting_login" and not job.get("login_timeout_claimed", False):
                snapshot = {
                    "id": job["id"],
                    "url": job["url"],
                    "slug": job.get("slug"),
                    "status": job["status"],
                    "log": list(job["log"]),
                    "login_attempts": job["login_attempts"],
                    "can_complete_login": True,
                }
            else:
                snapshot = {
                    "id": job["id"],
                    "url": job["url"],
                    "slug": job.get("slug"),
                    "status": job["status"],
                    "log": list(job["log"]),
                    "login_attempts": job["login_attempts"],
                    "can_complete_login": False,
                }
    return snapshot
