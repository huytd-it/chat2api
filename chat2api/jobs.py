import asyncio
import re
import shutil
import uuid
from contextlib import suppress
from pathlib import Path

from . import applog
from .agents.analyzer import integrate

LOGIN_TIMEOUT_SECONDS = 600
MAX_LOGIN_ATTEMPTS = 2
TERMINAL_STATUSES = {"ok", "failed", "cancelled", "login_timeout"}
CANCELLABLE_STATUSES = {"running", "waiting_login", "resuming"}
JOBS: dict[str, dict] = {}


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
    if cancel_session:
        await login_manager.cancel(job["id"])


async def _run_analyzer(job: dict, expected_status: str, cfg, pool, router, login_manager,
                        storage_state: Path | None = None) -> None:
    try:
        analyze_key = f"{job['id']}__analyze"
        try:
            result = await integrate(
                job["url"], pool, cfg, job["log"].append,
                storage_state=storage_state, analyze_key=analyze_key,
                publish_lock=job["publish_lock"], headed=job.get("headed", False),
                watch_id=job["id"] if job.get("headed") else None,
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
            if result.get("status") == "ok" and router is not None:
                try:
                    router.reload()
                except Exception:
                    job["log"].append("Không thể tải recipe mới.")
                    job["status"] = "failed"
                    _cleanup_staging(job)
                    return
            job.update({key: value for key, value in result.items()
                        if key not in {"task", "timeout_task", "lock"}})
            job["status"] = result.get("status", "failed")
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
                applog.log(f"integrate: {job['id']} lỗi reset context", "error")
                _cleanup_staging(job)
    except Exception as error:
        async with job["lock"]:
            if job["status"] == expected_status:
                job["log"].append(f"error: {error}")
                job["status"] = "failed"
                applog.log(f"integrate: {job['id']} lỗi: {error}", "error")
                _cleanup_staging(job)


def start_integrate(url: str, cfg, pool, router=None, login_manager=None,
                    publish_lock=None, headed: bool = False) -> str:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "url": url,
        "slug": None,
        "status": "running",
        "log": [],
        "task": None,
        "timeout_task": None,
        "login_attempts": 0,
        "login_timeout_claimed": False,
        "cancel_claimed": False,
        "login_manager": login_manager,
        "publish_lock": publish_lock or asyncio.Lock(),
        "staging_dir": cfg.recipes_dir / ".login" / job_id,
        "headed": headed,
        "lock": asyncio.Lock(),
    }
    JOBS[job_id] = job
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
