import asyncio
import uuid

JOBS: dict[str, dict] = {}


def start_integrate(url: str, cfg, pool) -> str:
    from .agents.analyzer import integrate

    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "status": "running", "log": []}
    JOBS[job_id] = job

    def log(msg: str):
        job["log"].append(str(msg))

    async def run():
        try:
            result = await integrate(url, pool, cfg, log)
            job.update(result)
            job["status"] = result["status"]
        except Exception as e:
            job["status"] = "failed"
            job["log"].append(f"error: {e}")

    job["task"] = asyncio.create_task(run())
    return job_id


def get(job_id: str) -> dict | None:
    job = JOBS.get(job_id)
    if not job:
        return None
    return {"id": job["id"], "status": job["status"], "log": list(job["log"])}
