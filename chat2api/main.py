import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

from . import applog, auth, errors, live_view  # noqa: F401  (import auth để đăng ký dependency)
from .config import Config
from .errors import OpenAIError
from .providers.browser_recipe import TrialLimitExceeded
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
        applog.log(f"Server khởi động (engine={cfg.browser_engine})")
        try:
            yield
        finally:
            applog.log("Server đang tắt")
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
    async def chat(body: ChatRequest, request: Request, response: Response):
        cfg_ = request.app.state.cfg
        rt = request.app.state.router
        try:
            provider, local = rt.resolve(body.model)
        except ModelNotFound:
            applog.log(f"chat: model không tồn tại: {body.model}", "error")
            raise OpenAIError(404, "model_not_found", f"The model '{body.model}' does not exist")
        applog.log(f"chat: model={body.model} stream={body.stream}")
        msgs = body.as_list()
        cid = "chatcmpl-" + uuid.uuid4().hex[:29]
        from .providers.browser_recipe import BrowserRecipe as BR

        # Chỉ dùng cho playground/desktop test thủ công: bật browser hiện lên
        # (không headless) để xem trực tiếp recipe chạy, thay vì đợi kết quả mù.
        # Dù cửa sổ Chromium có thực sự hiện ra hay không (tùy máy), watch_id
        # luôn cho phép xem live view qua /admin/watch/{id}/screenshot.
        headed = request.headers.get("x-chat2api-headed", "").strip().lower() == "true"
        watch_id = uuid.uuid4().hex[:12] if (headed and isinstance(provider, BR)) else None
        if watch_id:
            response.headers["X-Chat2api-Watch-Id"] = watch_id

        def fallback_ok(reason: str) -> bool:
            from .agents import llm

            return (isinstance(provider, BR) and cfg_.enable_fallback
                    and llm.configured(cfg_))

        async def agent_stream():
            from .agents import fallback

            log_lines = [f"[fallback:{provider.slug}] recipe lỗi, agent chạy trực tiếp"]
            async for d in fallback.run(provider.url, msgs, request.app.state.pool, cfg_,
                                        log_lines.append):
                yield d

        async def upstream():
            sent = {"n": 0}
            if rt.is_unhealthy(provider.slug) and fallback_ok("unhealthy recipe"):
                async for d in agent_stream():
                    yield d
                return
            try:
                stream_kwargs = ({"headed": headed, "watch_id": watch_id}
                                 if isinstance(provider, BR) else {})
                async for d in provider.stream(msgs, local, **stream_kwargs):
                    sent["n"] += 1
                    yield d
                rt.mark_success(provider.slug)
            except TrialLimitExceeded as e:
                applog.log(f"chat: hết lượt dùng thử ({provider.slug}): {e}", "warn")
                raise OpenAIError(403, "trial_limit_exceeded", str(e))
            except TimeoutError:
                rt.mark_failure(provider.slug)
                applog.log(f"chat: timeout ({provider.slug})", "error")
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
                applog.log(f"chat: lỗi ({provider.slug}): {e}", "error")
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

            sse_headers = {"X-Chat2api-Watch-Id": watch_id} if watch_id else None
            return StreamingResponse(gen(), media_type="text/event-stream", headers=sse_headers)

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
    from .schemas import AddAccountRequest, IntegrateRequest

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
            headed=body.headed,
        )
        applog.log(f"integrate: bắt đầu {body.url} (job={job_id}, headed={body.headed})")
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

    @admin.get("/logs")
    async def get_logs(after: int = 0, limit: int = 200):
        return {"entries": applog.since(after, limit)}

    @admin.get("/watch/{watch_id}/screenshot")
    async def watch_screenshot(watch_id: str):
        # Live view: chụp ảnh page Playwright đang chạy (headless hay headed đều
        # được), để client poll thay vì phụ thuộc cửa sổ Chromium có hiện ra hay
        # không trên máy người dùng.
        data = await live_view.screenshot(watch_id)
        if data is None:
            raise OpenAIError(404, "not_found", "Không có browser nào đang chạy cho watch_id này")
        return Response(content=data, media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})

    @admin.get("/recipes")
    async def recipes(request: Request):
        from .providers.browser_recipe import BrowserRecipe as BR

        rt = request.app.state.router
        out = []
        for slug, provider in sorted(rt.providers.items()):
            entry = {"slug": slug,
                    "models": [m.id.split("/", 1)[1] for m in provider.models()],
                    "unhealthy": rt.is_unhealthy(slug),
                    "type": type(provider).__name__}
            if isinstance(provider, BR):
                entry["accounts"] = provider.account_count
                entry["account_names"] = provider.account_names
                entry["trial"] = provider.trial_status
            out.append(entry)
        return out

    @admin.post("/recipes/{slug}/reload")
    async def reload_recipes(slug: str, request: Request):
        request.app.state.router.reload()
        applog.log(f"recipe: reload {slug}")
        return {"ok": True}

    @admin.delete("/recipes/{slug}")
    async def delete_recipe(slug: str, request: Request):
        if not re.fullmatch(r"[a-z0-9-]+", slug or "") or slug in {"gemini", "openai"}:
            raise OpenAIError(400, "invalid_slug", "Slug không được xóa")
        target = request.app.state.cfg.recipes_dir / slug
        if target.exists():
            shutil.rmtree(target)
        request.app.state.router.reload()
        applog.log(f"recipe: xóa {slug}", "warn")
        return {"ok": True}

    def _browser_recipe_or_404(request: Request, slug: str):
        from .providers.browser_recipe import BrowserRecipe as BR

        provider = request.app.state.router.providers.get(slug)
        if not isinstance(provider, BR):
            raise OpenAIError(404, "not_found", "Recipe không tồn tại")
        return provider

    @admin.post("/recipes/{slug}/accounts")
    async def start_account_login(slug: str, request: Request):
        provider = _browser_recipe_or_404(request, slug)
        cfg = request.app.state.cfg
        session_id = f"acct-{uuid.uuid4().hex[:10]}"
        try:
            await request.app.state.login_manager.start(
                session_id, slug, provider.url, cfg.recipes_dir / slug)
        except Exception:
            applog.log(f"account: không mở được browser cho {slug}", "error")
            raise OpenAIError(500, "login_open_failed",
                              "Không thể mở browser đăng nhập trên máy chạy chat2api.")
        applog.log(f"account: mở browser thêm account mới cho {slug} (session={session_id})")
        return {"session_id": session_id}

    @admin.post("/recipes/{slug}/accounts/{name}/reopen")
    async def reopen_account_login(slug: str, name: str, request: Request):
        # Mở lại browser bằng đúng profile (storage_state) của account đã lưu —
        # để re-login khi session hết hạn, thay vì phải tạo account mới.
        provider = _browser_recipe_or_404(request, slug)
        cfg = request.app.state.cfg
        state_path = provider.account_storage_state(name)
        if state_path is None:
            raise OpenAIError(404, "not_found", f"Account '{name}' không tồn tại")
        session_id = f"acct-{uuid.uuid4().hex[:10]}"
        try:
            await request.app.state.login_manager.start(
                session_id, slug, provider.url, cfg.recipes_dir / slug,
                storage_state=state_path)
        except Exception:
            applog.log(f"account: không mở lại được browser cho {slug}/{name}", "error")
            raise OpenAIError(500, "login_open_failed",
                              "Không thể mở browser đăng nhập trên máy chạy chat2api.")
        applog.log(f"account: mở lại browser cho {slug}/{name} (session={session_id})")
        return {"session_id": session_id, "name": name}

    @admin.post("/recipes/{slug}/accounts/{session_id}/complete")
    async def complete_account_login(slug: str, session_id: str, request: Request,
                                     body: AddAccountRequest):
        from . import __main__ as cli

        _browser_recipe_or_404(request, slug)
        name = (body.name or "").strip()
        if not re.fullmatch(r"[a-z0-9-]+", name):
            raise OpenAIError(400, "invalid_account_name",
                              "Tên account chỉ được gồm chữ thường, số và dấu -")
        cfg = request.app.state.cfg
        recipe_path = cfg.recipes_dir / slug / "recipe.yaml"
        if not recipe_path.exists():
            raise OpenAIError(404, "not_found", "Recipe không tồn tại")
        try:
            await request.app.state.login_manager.complete(session_id, filename=f"{name}.json")
        except Exception:
            applog.log(f"account: lưu session thất bại cho {slug}/{name}", "error")
            raise OpenAIError(500, "login_save_failed", "Không thể lưu session đăng nhập")
        async with request.app.state.recipe_publish_lock:
            cli.add_storage_state(recipe_path, name, f"auth/{name}.json")
            # Có account thật rồi thì bỏ giới hạn dùng thử ẩn danh (không còn dùng tới).
            import yaml
            data = yaml.safe_load(recipe_path.read_text(encoding="utf-8")) or {}
            if isinstance(data.get("login"), dict) and data["login"].pop("anon_trial_limit", None) is not None:
                recipe_path.write_text(
                    yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            request.app.state.router.reload()
        applog.log(f"account: đã lưu {slug}/{name}")
        return {"ok": True, "slug": slug, "account": name}

    @admin.post("/recipes/{slug}/accounts/{session_id}/cancel")
    async def cancel_account_login(slug: str, session_id: str, request: Request):
        await request.app.state.login_manager.cancel(session_id)
        return {"ok": True}


app = create_app(Config())