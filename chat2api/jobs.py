import asyncio
import re
import uuid
from contextlib import suppress
from pathlib import Path

from .agents.analyzer import integrate

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


class ContextResetFailed(RuntimeError):
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
    current = asyncio.current_task()
    try:
        await asyncio.sleep(LOGIN_TIMEOUT_SECONDS)
        await login_manager.cancel(job["id"])
        async with job["lock"]:
            if job["status"] == "waiting_login":
                job["status"] = "login_timeout"
                job["log"].append("Hết thời gian chờ đăng nhập.")
    except asyncio.CancelledError:
        pass
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
        await login_manager.start(job["id"], slug, job["url"], cfg.recipes_dir / slug)
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
        result = await integrate(job["url"], pool, cfg, job["log"].append,
                                 storage_state=storage_state)
        open_login = False
        reload_router = False
        async with job["lock"]:
            if job["status"] != expected_status:
                return
            job["slug"] = result.get("slug", job.get("slug"))
            if result.get("status") == "login_required":
                open_login = True
            else:
                job.update({key: value for key, value in result.items()
                            if key not in {"task", "timeout_task", "lock"}})
                job["status"] = result.get("status", "failed")
                reload_router = job["status"] == "ok" and router is not None
        if open_login:
            await _open_login(job, expected_status, cfg, login_manager)
        elif reload_router:
            router.reload()
    except asyncio.CancelledError:
        raise
    except Exception as error:
        async with job["lock"]:
            if job["status"] == expected_status:
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
    job["task"] = asyncio.create_task(
        _run_analyzer(job, "running", cfg, pool, router, login_manager)
    )
    return job_id


async def complete_login(job_id: str, cfg, pool, router, login_manager) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise JobNotFound

    async with job["lock"]:
        if job["status"] != "waiting_login":
            raise InvalidJobState
    if not await login_manager.has(job_id):
        raise InvalidJobState
    async with job["lock"]:
        if job["status"] != "waiting_login":
            raise InvalidJobState
        job["status"] = "resuming"
        _cancel_timeout(job)

    try:
        state_path = await login_manager.complete(job_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        async with job["lock"]:
            if job["status"] == "resuming":
                _login_failure(job, "Không thể lưu session đăng nhập.")
        raise LoginSaveFailed

    try:
        await pool.drop(f"{job['slug']}__analyze")
    except asyncio.CancelledError:
        raise
    except Exception:
        async with job["lock"]:
            if job["status"] == "resuming":
                job["log"].append("Không thể reset analyzer context.")
                job["status"] = "failed"
        raise ContextResetFailed

    async with job["lock"]:
        if job["status"] != "resuming":
            return {"ok": True, "status": job["status"]}
        job["task"] = asyncio.create_task(
            _run_analyzer(job, "resuming", cfg, pool, router, login_manager,
                          storage_state=state_path)
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
    cleanup = [login_manager.cancel(job_id) for job_id in waiting_ids]
    cleanup.extend(tasks)
    if cleanup:
        await asyncio.gather(*cleanup, return_exceptions=True)


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
        waiting = job["status"] == "waiting_login"
    if waiting and manager is not None and await manager.has(job_id):
        async with job["lock"]:
            if job["status"] == "waiting_login":
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
