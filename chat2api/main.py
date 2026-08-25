import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

from . import auth, errors  # noqa: F401  (import auth để đăng ký dependency)
from .config import Config
from .errors import OpenAIError
from .router import ModelNotFound, Router
from .schemas import ChatRequest

PLAYGROUND = Path(__file__).parent / "playground" / "index.html"


def _sse(cid: str, model: str, delta: str) -> str:
    chunk = {
        "id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}],
    }
    return "data: " + json.dumps(chunk) + "\n\n"


def create_app(cfg: Config) -> FastAPI:
    from . import router as router_mod  # trigger LOADERS registration
    from .browserpool import BrowserPool
    from .login_sessions import LoginSessionManager

    pool = BrowserPool(cfg.browser_engine, cfg.pool_max_contexts)
    login_manager = LoginSessionManager()
    router = Router(cfg.recipes_dir, pool)
    router.reload()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from . import jobs

        await pool.start()
        try:
            yield
        finally:
            try:
                try:
                    await jobs.shutdown(login_manager)
                finally:
                    await login_manager.close_all()
            finally:
                await pool.aclose()

    app = FastAPI(title="chat2api", lifespan=lifespan)
    # The browser playground is same-origin (this app serves its own HTML), but
    # the Tauri desktop app's frontend runs on a different origin than this API
    # port, making every request cross-origin. No cookies/credentials are used
    # (auth is a Bearer token), so a wildcard origin is safe here.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    errors.register_error_handler(app)
    app.state.cfg = cfg
    app.state.pool = pool
    app.state.login_manager = login_manager
    app.state.router = router
    app.state.recipe_publish_lock = asyncio.Lock()

    @app.get("/health")
    async def health(request: Request):
        return {"status": "ok", "engine": cfg.browser_engine,
                "contexts": request.app.state.pool.size,
                "models": len(request.app.state.router.all_models())}

    @app.get("/")
    async def index():
        return HTMLResponse(PLAYGROUND.read_text(encoding="utf-8"))

    from fastapi import APIRouter

    v1 = APIRouter(dependencies=[Depends(auth.require_key)])

    @v1.get("/models")
    async def models(request: Request):
        data = [{"id": m.id, "object": "model", "owned_by": m.slug, "ready": m.ready}
                for m in request.app.state.router.all_models()]
        return {"object": "list", "data": data}

    @v1.post("/chat/completions")
    async def chat(body: ChatRequest, request: Request):
        cfg_ = request.app.state.cfg
        rt = request.app.state.router
        try:
            provider, local = rt.resolve(body.model)
        except ModelNotFound:
            raise OpenAIError(404, "model_not_found", f"The model '{body.model}' does not exist")
        msgs = body.as_list()
        cid = "chatcmpl-" + uuid.uuid4().hex[:29]

        def fallback_ok(reason: str) -> bool:
            from .providers.browser_recipe import BrowserRecipe as BR
            from .agents import llm

            return (isinstance(provider, BR) and cfg_.enable_fallback
                    and llm.configured(cfg_))

        async def agent_stream():
            from .agents import fallback

            log = [f"[fallback:{provider.slug}] recipe lỗi, agent chạy trực tiếp"]
            async for d in fallback.run(provider.url, msgs, request.app.state.pool, cfg_, log):
                yield d

        async def upstream():
            sent = {"n": 0}
            if rt.is_unhealthy(provider.slug) and fallback_ok("unhealthy recipe"):
                async for d in agent_stream():
                    yield d
                return
            try:
                async for d in provider.stream(msgs, local):
                    sent["n"] += 1
                    yield d
                rt.mark_success(provider.slug)
            except TimeoutError:
                rt.mark_failure(provider.slug)
                if sent["n"] > 0:
                    raise
                if fallback_ok("timeout"):
                    async for d in agent_stream():
                        yield d
                    rt.mark_success(provider.slug)
                    return
                raise OpenAIError(504, "recipe_timeout",
                                  f"Không nhận được reply trong thời hạn ({cfg_.recipe_timeout_ms}ms)",
                                  "api_error")
            except OpenAIError:
                raise
            except Exception as e:
                rt.mark_failure(provider.slug)
                if sent["n"] > 0:
                    raise
                if fallback_ok(str(e)):
                    async for d in agent_stream():
                        yield d
                    rt.mark_success(provider.slug)
                    return
                raise OpenAIError(502, "upstream_error", str(e), "api_error")

        if body.stream:
            async def gen():
                async for d in upstream():
                    yield _sse(cid, body.model, d)
                yield "data: [DONE]\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream")

        parts = []
        try:
            async for d in upstream():
                parts.append(d)
        except TimeoutError:
            raise OpenAIError(504, "recipe_timeout", "Recipe timeout", "api_error")
        text = "".join(parts)
        return {"id": cid, "object": "chat.completion", "created": int(time.time()),
                "model": body.model,
                "choices": [{"index": 0,
                             "message": {"role": "assistant", "content": text},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}

    admin = APIRouter(prefix="/admin", dependencies=[Depends(auth.require_key)])
    register_admin(app, admin)

    app.include_router(v1, prefix="/v1")
    app.include_router(admin)
    return app


def register_admin(app: FastAPI, admin) -> None:
    import re
    import shutil

    from .agents import llm
    from . import jobs
    from .schemas import IntegrateRequest

    @admin.post("/integrate")
    async def integrate(body: IntegrateRequest, request: Request):
        cfg = request.app.state.cfg
        if not llm.configured(cfg):
            raise OpenAIError(503, "agent_not_configured",
                              "Đặt AGENT_LLM_BASE_URL, AGENT_LLM_API_KEY, AGENT_LLM_MODEL "
                              "để dùng tính năng tích hợp tự động.")
        job_id = jobs.start_integrate(
            body.url, cfg, request.app.state.pool,
            router=request.app.state.router,
            login_manager=request.app.state.login_manager,
            publish_lock=request.app.state.recipe_publish_lock,
        )
        return {"job_id": job_id}

    @admin.get("/integrate/{job_id}")
    async def integrate_status(job_id: str):
        job = await jobs.get(job_id)
        if not job:
            raise OpenAIError(404, "not_found", "Job không tồn tại")
        return job

    @admin.post("/integrate/{job_id}/login-complete")
    async def integrate_login_complete(job_id: str, request: Request):
        try:
            return await jobs.complete_login(
                job_id, request.app.state.cfg, request.app.state.pool,
                request.app.state.router, request.app.state.login_manager)
        except jobs.JobNotFound:
            raise OpenAIError(404, "not_found", "Job không tồn tại")
        except jobs.InvalidJobState:
            raise OpenAIError(409, "invalid_job_state", "Job không chờ đăng nhập")
        except jobs.LoginSaveFailed:
            raise OpenAIError(500, "login_save_failed", "Không thể lưu session đăng nhập")
        except jobs.ContextResetFailed:
            raise OpenAIError(500, "context_reset_failed", "Không thể reset analyzer context")

    @admin.post("/integrate/{job_id}/cancel")
    async def integrate_cancel(job_id: str, request: Request):
        try:
            return await jobs.cancel_job(job_id, request.app.state.login_manager)
        except jobs.JobNotFound:
            raise OpenAIError(404, "not_found", "Job không tồn tại")
        except jobs.InvalidJobState:
            raise OpenAIError(409, "invalid_job_state", "Không thể hủy job ở trạng thái này")

    @admin.get("/integrate/{job_id}/log")
    async def integrate_log(job_id: str):
        async def gen():
            cursor = 0
            while True:
                job = await jobs.get(job_id)
                if not job:
                    yield "event: error\ndata: job not found\n\n"
                    return
                while cursor < len(job["log"]):
                    line = job["log"][cursor]
                    cursor += 1
                    yield f"data: {line}\n\n"
                if job["status"] in jobs.TERMINAL_STATUSES:
                    yield f"event: done\ndata: {job['status']}\n\n"
                    return
                await asyncio.sleep(0.5)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @admin.get("/recipes")
    async def recipes(request: Request):
        rt = request.app.state.router
        out = []
        for slug, provider in sorted(rt.providers.items()):
            out.append({"slug": slug,
                        "models": [m.id.split("/", 1)[1] for m in provider.models()],
                        "unhealthy": rt.is_unhealthy(slug),
                        "type": type(provider).__name__})
        return out

    @admin.post("/recipes/{slug}/reload")
    async def reload_recipes(slug: str, request: Request):
        request.app.state.router.reload()
        return {"ok": True}

    @admin.delete("/recipes/{slug}")
    async def delete_recipe(slug: str, request: Request):
        if not re.fullmatch(r"[a-z0-9-]+", slug or "") or slug in {"gemini", "openai"}:
            raise OpenAIError(400, "invalid_slug", "Slug không được xóa")
        target = request.app.state.cfg.recipes_dir / slug
        if target.exists():
            shutil.rmtree(target)
        request.app.state.router.reload()
        return {"ok": True}


app = create_app(Config())