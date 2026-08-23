import asyncio
import re
import uuid
from contextlib import suppress
from pathlib import Path

from .agents.analyzer import integrate
from .login_sessions import LoginSessionError

LOGIN_TIMEOUT_SECONDS = 600
MAX_LOGIN_ATTEMPTS = 2
TERMINAL_STATUSES = {"ok", "failed", "cancelled", "login_timeout"}
CANCELLABLE_STATUSES = {"running", "waiting_login", "resuming"}
JOBS: dict[str, dict] = {}


class JobNotFound(LookupError):
    pass


class InvalidJobState(RuntimeError):
    pass


class LoginSaveFailed(RuntimeError):
    pass


def _login_failure(job: dict, message: str) -> None:
    slug = job.get("slug") or "<slug>"
    job["log"].append(message)
    job["log"].append(f"Chạy trực tiếp trên desktop hoặc dùng: python -m chat2api login {slug}")
    job["status"] = "failed"


def _cancel_timeout(job: dict) -> None:
    task = job.get("timeout_task")
    if task and task is not asyncio.current_task() and not task.done():
        task.cancel()
    job["timeout_task"] = None


async def _login_timeout(job: dict, login_manager) -> None:
    try:
        await asyncio.sleep(LOGIN_TIMEOUT_SECONDS)
        async with job["lock"]:
            if job["status"] != "waiting_login":
                return
            job["status"] = "login_timeout"
            job["timeout_task"] = None
        await login_manager.cancel(job["id"])
        job["log"].append("Hết thời gian chờ đăng nhập.")
    except asyncio.CancelledError:
        pass


async def _open_login(job: dict, cfg, login_manager) -> None:
    if job["login_attempts"] >= MAX_LOGIN_ATTEMPTS:
        _login_failure(job, "Đăng nhập chưa hoàn tất sau 2 lần thử.")
        return

    slug = job["slug"]
    if not re.fullmatch(r"[a-z0-9-]+", slug or ""):
        _login_failure(job, "Không thể mở browser desktop: slug không hợp lệ.")
        return

    try:
        await login_manager.start(job["id"], slug, job["url"], cfg.recipes_dir / slug)
    except asyncio.CancelledError:
        raise
    except LoginSessionError:
        _login_failure(job, "Không thể mở browser desktop trên máy chạy chat2api.")
        return

    async with job["lock"]:
        if job["status"] in TERMINAL_STATUSES:
            await login_manager.cancel(job["id"])
            return
        job["login_attempts"] += 1
        job["status"] = "waiting_login"
        job["log"].append("Đã mở cửa sổ Chromium. Hãy đăng nhập rồi xác nhận.")
        job["timeout_task"] = asyncio.create_task(_login_timeout(job, login_manager))


async def _run_analyzer(job: dict, cfg, pool, router, login_manager,
                        storage_state: Path | None = None) -> None:
    try:
        result = await integrate(job["url"], pool, cfg, job["log"].append,
                                 storage_state=storage_state)
        if job["status"] in TERMINAL_STATUSES:
            return
        job["slug"] = result.get("slug", job.get("slug"))
        if result.get("status") == "login_required":
            await _open_login(job, cfg, login_manager)
            return
        job.update({key: value for key, value in result.items() if key not in {"task", "timeout_task"}})
        job["status"] = result.get("status", "failed")
        if job["status"] == "ok" and router is not None:
            router.reload()
    except asyncio.CancelledError:
        raise
    except Exception as error:
        job["log"].append(f"error: {error}")
        job["status"] = "failed"


def start_integrate(url: str, cfg, pool, router=None, login_manager=None) -> str:
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
        "login_manager": login_manager,
        "lock": asyncio.Lock(),
    }
    JOBS[job_id] = job
    job["task"] = asyncio.create_task(_run_analyzer(job, cfg, pool, router, login_manager))
    return job_id


async def complete_login(job_id: str, cfg, pool, router, login_manager) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise JobNotFound

    async with job["lock"]:
        if job["status"] != "waiting_login" or not await login_manager.has(job_id):
            raise InvalidJobState
        job["status"] = "resuming"
        _cancel_timeout(job)

    try:
        state_path = await login_manager.complete(job_id)
        await pool.drop(f"{job['slug']}__analyze")
    except asyncio.CancelledError:
        raise
    except Exception:
        _login_failure(job, "Không thể lưu session đăng nhập.")
        raise LoginSaveFailed

    async with job["lock"]:
        if job["status"] != "resuming":
            return {"ok": True, "status": job["status"]}
        job["task"] = asyncio.create_task(
            _run_analyzer(job, cfg, pool, router, login_manager, storage_state=state_path)
        )
    return {"ok": True, "status": "resuming"}


async def cancel_job(job_id: str, login_manager) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise JobNotFound

    async with job["lock"]:
        if job["status"] == "cancelled":
            return {"ok": True, "status": "cancelled"}
        if job["status"] not in CANCELLABLE_STATUSES:
            raise InvalidJobState
        job["status"] = "cancelled"
        _cancel_timeout(job)
        task = job.get("task")
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()

    await login_manager.cancel(job_id)
    if task and task is not asyncio.current_task():
        with suppress(asyncio.CancelledError):
            await task
    return {"ok": True, "status": "cancelled"}


async def get(job_id: str) -> dict | None:
    job = JOBS.get(job_id)
    if job is None:
        return None
    manager = job.get("login_manager")
    can_complete = (job["status"] == "waiting_login" and manager is not None
                    and await manager.has(job_id))
    return {
        "id": job["id"],
        "url": job["url"],
        "slug": job.get("slug"),
        "status": job["status"],
        "log": list(job["log"]),
        "login_attempts": job["login_attempts"],
        "can_complete_login": can_complete,
    }
