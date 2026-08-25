import asyncio
import json
import sys
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import accounts, applog, auth, errors, live_view, store  # noqa: F401  (import auth để đăng ký dependency)
from .config import Config
from .errors import OpenAIError
from .providers.browser_recipe import TrialLimitExceeded
from .router import ModelNotFound, Router
from .schemas import ChatRequest


def _sse(cid: str, model: str, delta: str) -> str:
    chunk = {
        "id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}],
    }
    return "data: " + json.dumps(chunk) + "\n\n"


def _sse_error(e: OpenAIError) -> str:
    # Lỗi nổ ra GIỮA stream (sau khi headers 200 đã gửi) không thể đổi status
    # được nữa — nếu chỉ raise, Starlette cắt kết nối và client chỉ thấy
    # "network error" mù mờ. Gửi payload lỗi chuẩn OpenAI qua SSE để client
    # hiển thị đúng thông điệp (timeout, hết lượt dùng thử, upstream fail...).
    return "data: " + json.dumps(
        {"error": {"message": e.message, "type": e.typ, "code": e.code}}) + "\n\n"


def create_app(cfg: Config) -> FastAPI:
    from . import router as router_mod  # trigger LOADERS registration
    from .browserpool import BrowserPool
    from .login_sessions import LoginSessionManager
    from .store import importer

    pool = BrowserPool(cfg.browser_engine, cfg.pool_max_contexts)
    login_manager = LoginSessionManager()
    router = Router(cfg.recipes_dir, pool)
    router.reload()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from . import jobs

        # Mở kho SQLite trước mọi thứ khác để dòng log đầu tiên cũng được lưu.
        # Đặt ở lifespan chứ không phải create_app: module này tạo `app` lúc
        # import, và import không được phép ghi ra đĩa của người dùng.
        try:
            version = store.connect(cfg.db_path).migrate()
        except Exception as error:
            # Kho hỏng chỉ mất phần ghi lịch sử — app vẫn phải chat được.
            print(f"[chat2api] không mở được kho {cfg.db_path}: {error}", file=sys.stderr)
            store.shutdown()
            version = None
        await pool.start()
        applog.log(f"Server khởi động (engine={cfg.browser_engine})")
        if version is not None:
            applog.log(f"store: {cfg.db_path} (schema v{version})")
        else:
            applog.log("store: không mở được kho, log chỉ nằm trong RAM", "warn")
        # Gom account kiểu cũ vào kho chung khi server thật sự chạy — không đặt
        # trong create_app vì module này tạo `app` lúc import, và import không
        # được phép ghi vào thư mục recipes của người dùng.
        migrated = accounts.migrate_legacy(cfg.recipes_dir)
        if migrated:
            applog.log(f"account: gom {len(migrated)} account vào kho chung: {', '.join(migrated)}")
        # Mirror đĩa vào DB *sau* migrate_legacy (để account vừa gom cũng vào kho)
        # và *trước* reload cuối (để provider dựng lại đọc được state đã lưu, ví
        # dụ số lượt dùng thử ẩn danh đã tiêu).
        db = store.default()
        if db is not None:
            try:
                counts = await asyncio.to_thread(importer.import_all, db, cfg.recipes_dir)
                applog.log("store: import {recipes} recipe / {models} model / {accounts} account"
                           " ({versions} bản YAML mới)".format(**counts))
            except Exception as error:
                applog.log(f"store: import thất bại: {error}", "error")
        router.reload()
        try:
            yield
        finally:
            applog.log("Server đang tắt")
            # Close login browsers first, then shutdown jobs; pool always last
            # (even when jobs.shutdown raises) so Chromium processes never leak.
            try:
                await login_manager.close_all()
                await jobs.shutdown(login_manager)
            finally:
                try:
                    await pool.aclose()
                finally:
                    # Cuối cùng: xả nốt hàng đợi ghi rồi đóng, để dòng log lúc
                    # tắt máy không rơi mất.
                    await asyncio.to_thread(store.shutdown)

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
        # Playground HTML đã bị thay bằng desktop app (Tauri + Svelte), server
        # không còn phục vụ UI nào nữa — chỉ báo mình là ai để người dò cổng
        # biết đây là chat2api.
        return {"name": "chat2api", "docs": "/docs", "api": "/v1",
                "ui": "desktop app"}

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
                rt.mark_failure(provider.slug, f"timeout sau {cfg_.recipe_timeout_ms}ms")
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
                rt.mark_failure(provider.slug, str(e))
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
                try:
                    async for d in upstream():
                        yield _sse(cid, body.model, d)
                except OpenAIError as e:
                    yield _sse_error(e)
                except TimeoutError:
                    yield _sse_error(OpenAIError(
                        504, "recipe_timeout",
                        f"Không nhận được reply trong thời hạn ({cfg_.recipe_timeout_ms}ms)",
                        "api_error"))
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
    from . import jobs, settings
    from .schemas import (AccountLoginRequest, AddAccountRequest, IntegrateRequest,
                          SaveAccountRequest, SettingsRequest)

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
        # Đường poll nóng: ring buffer trong RAM, `after` là cursor.
        return {"entries": applog.since(after, limit)}

    @admin.get("/logs/history")
    async def get_log_history(level: str = "", source: str = "", q: str = "",
                              before: int = 0, limit: int = 200):
        # Đường tra cứu: đọc bảng app_log nên thấy được cả log trước lần restart
        # gần nhất. `before` là id để phân trang lùi. Rỗng khi chưa mở được kho.
        entries = await asyncio.to_thread(applog.history, level, source, q, before, limit)
        return {"entries": entries, "persisted": store.default() is not None}

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

    @admin.post("/recipes/{slug}/browser/close")
    async def close_recipe_browser(slug: str, request: Request):
        # Browser của recipe được giữ mở sau mỗi request; đây là đường duy nhất
        # để tắt nó từ app (ngoài việc người dùng tự đóng cửa sổ).
        provider = _browser_recipe_or_404(request, slug)
        closed = await provider.close_browser()
        applog.log(f"browser: đóng thủ công {slug} ({closed} context)")
        return {"ok": True, "closed": closed}

    def _domain_usage(request: Request) -> dict[str, list[str]]:
        from .providers.browser_recipe import BrowserRecipe as BR

        usage: dict[str, list[str]] = {}
        for slug, provider in request.app.state.router.providers.items():
            if isinstance(provider, BR) and provider.domain:
                usage.setdefault(provider.domain, []).append(slug)
        return usage

    @admin.get("/accounts")
    async def list_all_accounts(request: Request):
        # Account thuộc về domain chứ không thuộc recipe: mọi recipe cùng domain
        # dùng chung danh sách này.
        cfg = request.app.state.cfg
        usage = _domain_usage(request)
        domains = sorted(set(accounts.list_domains(cfg.recipes_dir)) | set(usage))
        out = []
        for domain in domains:
            items = []
            for name, path in accounts.list_accounts(cfg.recipes_dir, domain):
                stat = path.stat()
                items.append({"name": name, "size": stat.st_size, "updated_at": stat.st_mtime})
            out.append({"domain": domain, "accounts": items,
                        "recipes": sorted(usage.get(domain, []))})
        return out

    @admin.post("/accounts/login")
    async def start_domain_login(request: Request, body: AccountLoginRequest):
        cfg = request.app.state.cfg
        domain = (body.domain or accounts.domain_of(body.url)).strip().lower()
        if not accounts.valid_domain(domain):
            raise OpenAIError(400, "invalid_domain", "Domain không hợp lệ")
        url = body.url.strip() or f"https://{domain}"
        session_id = f"acct-{uuid.uuid4().hex[:10]}"
        state_path = accounts.account_path(cfg.recipes_dir, domain, body.name.strip()) \
            if accounts.valid_name(body.name.strip()) else None
        try:
            await request.app.state.login_manager.start(
                session_id, domain, url, accounts.domain_dir(cfg.recipes_dir, domain),
                storage_state=state_path)
        except Exception:
            applog.log(f"account: không mở được browser cho {domain}", "error")
            raise OpenAIError(500, "login_open_failed",
                              "Không thể mở browser đăng nhập trên máy chạy chat2api.")
        applog.log(f"account: mở browser đăng nhập {domain} (session={session_id})")
        return {"session_id": session_id, "domain": domain}

    @admin.post("/accounts/login/{session_id}/complete")
    async def complete_domain_login(session_id: str, request: Request, body: SaveAccountRequest):
        cfg = request.app.state.cfg
        domain, name = body.domain.strip().lower(), body.name.strip()
        if not accounts.valid_domain(domain):
            raise OpenAIError(400, "invalid_domain", "Domain không hợp lệ")
        if not accounts.valid_name(name):
            raise OpenAIError(400, "invalid_account_name",
                              "Tên account chỉ được gồm chữ thường, số và dấu -")
        try:
            # login_manager ghi vào <recipe_dir>/auth/<file>; recipe_dir ở đây là
            # thư mục domain nên state nằm đúng kho chung.
            saved = await request.app.state.login_manager.complete(session_id,
                                                                   filename=f"{name}.json")
        except Exception:
            applog.log(f"account: lưu session thất bại cho {domain}/{name}", "error")
            raise OpenAIError(500, "login_save_failed", "Không thể lưu session đăng nhập")
        target = accounts.account_path(cfg.recipes_dir, domain, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if saved.resolve() != target.resolve():
            shutil.move(str(saved), str(target))
        request.app.state.router.reload()
        applog.log(f"account: đã lưu {domain}/{name}")
        return {"ok": True, "domain": domain, "name": name}

    @admin.post("/accounts/{domain}/{name}/reopen")
    async def reopen_domain_login(domain: str, name: str, request: Request):
        cfg = request.app.state.cfg
        if not (accounts.valid_domain(domain) and accounts.valid_name(name)):
            raise OpenAIError(400, "invalid_account", "Domain hoặc tên account không hợp lệ")
        state_path = accounts.account_path(cfg.recipes_dir, domain, name)
        if not state_path.exists():
            raise OpenAIError(404, "not_found", f"Account '{name}' không tồn tại")
        session_id = f"acct-{uuid.uuid4().hex[:10]}"
        try:
            await request.app.state.login_manager.start(
                session_id, domain, f"https://{domain}",
                accounts.domain_dir(cfg.recipes_dir, domain), storage_state=state_path)
        except Exception:
            applog.log(f"account: không mở lại được browser cho {domain}/{name}", "error")
            raise OpenAIError(500, "login_open_failed",
                              "Không thể mở browser đăng nhập trên máy chạy chat2api.")
        applog.log(f"account: mở lại browser cho {domain}/{name} (session={session_id})")
        return {"session_id": session_id, "domain": domain, "name": name}

    @admin.delete("/accounts/{domain}/{name}")
    async def delete_domain_account(domain: str, name: str, request: Request):
        cfg = request.app.state.cfg
        if not accounts.delete_account(cfg.recipes_dir, domain, name):
            raise OpenAIError(404, "not_found", f"Account '{name}' không tồn tại")
        request.app.state.router.reload()
        applog.log(f"account: xóa {domain}/{name}", "warn")
        return {"ok": True}

    @admin.get("/settings")
    async def get_settings(request: Request):
        return {"fields": settings.describe(),
                "env_path": str(request.app.state.cfg.env_path)}

    @admin.put("/settings")
    async def put_settings(request: Request, body: SettingsRequest):
        clean, errs = settings.validate(body.values)
        if errs:
            raise OpenAIError(400, "invalid_settings", "; ".join(errs))
        needs_restart = settings.save(request.app.state.cfg.env_path, clean)
        request.app.state.router.reload()
        applog.log(f"settings: cập nhật {', '.join(sorted(clean))}")
        return {"ok": True, "saved": sorted(clean), "needs_restart": sorted(needs_restart)}

    @admin.get("/overview")
    async def overview(request: Request):
        from .providers.browser_recipe import BrowserRecipe as BR

        rt = request.app.state.router
        cfg = request.app.state.cfg
        browser_recipes = [p for p in rt.providers.values() if isinstance(p, BR)]
        account_total = sum(
            len(accounts.list_accounts(cfg.recipes_dir, d))
            for d in accounts.list_domains(cfg.recipes_dir))
        return {
            "engine": cfg.browser_engine,
            "contexts": request.app.state.pool.size,
            "models": len(rt.all_models()),
            "recipes": len(rt.providers),
            "browser_recipes": len(browser_recipes),
            "unhealthy": sorted(s for s in rt.providers if rt.is_unhealthy(s)),
            "domains": len(accounts.list_domains(cfg.recipes_dir)),
            "accounts": account_total,
            "open_browsers": sorted(p.slug for p in browser_recipes if p.browser_open),
        }

    # Các endpoint theo recipe dưới đây là lối tắt tiện tay từ trang Recipes:
    # chúng chỉ suy ra domain của recipe rồi ghi vào đúng kho account chung, nên
    # account thêm ở đây lập tức dùng được cho mọi recipe cùng domain.
    @admin.post("/recipes/{slug}/accounts")
    async def start_account_login(slug: str, request: Request):
        provider = _browser_recipe_or_404(request, slug)
        cfg = request.app.state.cfg
        session_id = f"acct-{uuid.uuid4().hex[:10]}"
        try:
            await request.app.state.login_manager.start(
                session_id, slug, provider.url,
                accounts.domain_dir(cfg.recipes_dir, provider.domain))
        except Exception:
            applog.log(f"account: không mở được browser cho {slug}", "error")
            raise OpenAIError(500, "login_open_failed",
                              "Không thể mở browser đăng nhập trên máy chạy chat2api.")
        applog.log(f"account: mở browser thêm account mới cho {slug} (session={session_id})")
        return {"session_id": session_id, "domain": provider.domain}

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
                session_id, slug, provider.url,
                accounts.domain_dir(cfg.recipes_dir, provider.domain),
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
        provider = _browser_recipe_or_404(request, slug)
        name = (body.name or "").strip()
        if not accounts.valid_name(name):
            raise OpenAIError(400, "invalid_account_name",
                              "Tên account chỉ được gồm chữ thường, số và dấu -")
        cfg = request.app.state.cfg
        recipe_path = cfg.recipes_dir / slug / "recipe.yaml"
        if not recipe_path.exists():
            raise OpenAIError(404, "not_found", "Recipe không tồn tại")
        try:
            saved = await request.app.state.login_manager.complete(session_id,
                                                                   filename=f"{name}.json")
        except Exception:
            applog.log(f"account: lưu session thất bại cho {slug}/{name}", "error")
            raise OpenAIError(500, "login_save_failed", "Không thể lưu session đăng nhập")
        async with request.app.state.recipe_publish_lock:
            target = accounts.account_path(cfg.recipes_dir, provider.domain, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if saved.resolve() != target.resolve():
                shutil.move(str(saved), str(target))
            # Có account thật rồi thì bỏ giới hạn dùng thử ẩn danh (không còn dùng tới).
            import yaml
            data = yaml.safe_load(recipe_path.read_text(encoding="utf-8")) or {}
            if isinstance(data.get("login"), dict) and data["login"].pop("anon_trial_limit", None) is not None:
                recipe_path.write_text(
                    yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            request.app.state.router.reload()
        applog.log(f"account: đã lưu {provider.domain}/{name} (từ recipe {slug})")
        return {"ok": True, "slug": slug, "account": name, "domain": provider.domain}

    @admin.post("/recipes/{slug}/accounts/{session_id}/cancel")
    async def cancel_account_login(slug: str, session_id: str, request: Request):
        await request.app.state.login_manager.cancel(session_id)
        return {"ok": True}


app = create_app(Config())