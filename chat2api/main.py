import asyncio
import json
import sys
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import accounts, apikeys, applog, auth, errors, live_view, profiles, sessions, store  # noqa: F401  (import auth để đăng ký dependency)
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

    pool = BrowserPool(cfg.browser_engine, cfg.pool_max_contexts,
                       max_profiles=cfg.pool_max_profiles)
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
        # Nạp sẵn tập api_key để request đầu tiên không phải xuống đĩa giữa
        # đường xác thực (auth.require_key chỉ tra dict sau bước này).
        active_keys = await asyncio.to_thread(apikeys.active)
        await pool.start()
        applog.log(f"Server khởi động (engine={cfg.browser_engine})")
        if active_keys:
            applog.log(f"auth: {len(active_keys)} api key đang hoạt động")
        elif cfg.api_keys:
            applog.log(f"auth: {len(cfg.api_keys)} key bootstrap từ CHAT2API_KEYS")
        else:
            applog.log("auth: chưa đặt api key nào, server đang mở", "warn")
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
            if cfg.browser_profile_mode == "profile":
                # Dựng profile mặc định ngay lúc khởi động để trang Profiles có
                # cái để hiện, thay vì chỉ xuất hiện sau request chat đầu tiên.
                try:
                    await asyncio.to_thread(
                        profiles.ensure_profile, profiles.DEFAULT_PROFILE, cfg.profiles_dir,
                        max_tabs=cfg.profile_max_tabs, make_default=True)
                    applog.log(f"profile: chế độ profile bật, thư mục {cfg.profiles_dir}")
                except Exception as error:
                    applog.log(f"profile: không dựng được profile mặc định: {error}", "error")
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

        # Ghi một transaction trước provider và một transaction khi kết thúc;
        # tuyệt đối không ghi từng SSE delta. Header này cho desktop nối nhiều
        # lượt vào cùng session; client API không gửi vẫn được gom theo model +
        # fingerprint trong cửa sổ 30 phút (xem sessions.begin).
        recording = await asyncio.to_thread(
            sessions.begin,
            request.headers.get("x-chat2api-session-id"), body.model, provider.slug,
            msgs, body.stream, request.headers.get("authorization", ""),
            request.headers.get("user-agent", ""),
            getattr(request.state, "api_key_id", None),
        )
        response.headers["X-Chat2api-Session-Id"] = recording.session_id

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

            recording.fallback_used = True
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
                parts: list[str] = []
                final_error: OpenAIError | None = None
                cancelled = False
                try:
                    async for d in upstream():
                        if not parts:
                            sessions.first_delta(recording)
                        parts.append(d)
                        yield _sse(cid, body.model, d)
                except OpenAIError as error:
                    final_error = error
                    yield _sse_error(error)
                except TimeoutError:
                    final_error = OpenAIError(
                        504, "recipe_timeout",
                        f"Không nhận được reply trong thời hạn ({cfg_.recipe_timeout_ms}ms)",
                        "api_error")
                    yield _sse_error(final_error)
                except asyncio.CancelledError:
                    cancelled = True
                    raise
                finally:
                    text = "".join(parts)
                    html = provider.last_response_html if isinstance(provider, BR) else None
                    if cancelled:
                        await asyncio.to_thread(
                            sessions.finish, recording, text,
                            status="cancelled", error_code="client_cancelled",
                            error_message="Client đã ngắt stream", finish_reason="error")
                    elif final_error is not None:
                        status = ("timeout" if final_error.code == "recipe_timeout" else
                                  "trial_limit" if final_error.code == "trial_limit_exceeded" else "error")
                        await asyncio.to_thread(
                            sessions.finish, recording, text,
                            html=html, status=status, error_code=final_error.code,
                            error_message=final_error.message, http_status=final_error.status,
                            finish_reason="error")
                    else:
                        await asyncio.to_thread(
                            sessions.finish, recording, text, html=html)
                if not cancelled:
                    yield "data: [DONE]\n\n"

            sse_headers = {"X-Chat2api-Session-Id": recording.session_id}
            if watch_id:
                sse_headers["X-Chat2api-Watch-Id"] = watch_id
            return StreamingResponse(gen(), media_type="text/event-stream", headers=sse_headers)

        parts: list[str] = []
        try:
            async for d in upstream():
                if not parts:
                    sessions.first_delta(recording)
                parts.append(d)
        except TimeoutError:
            error = OpenAIError(504, "recipe_timeout", "Recipe timeout", "api_error")
            await asyncio.to_thread(
                sessions.finish, recording, "".join(parts),
                status="timeout", error_code=error.code,
                error_message=error.message, http_status=error.status,
                finish_reason="error")
            raise error
        except OpenAIError as error:
            status = "trial_limit" if error.code == "trial_limit_exceeded" else "error"
            await asyncio.to_thread(
                sessions.finish, recording, "".join(parts),
                status=status, error_code=error.code,
                error_message=error.message, http_status=error.status,
                finish_reason="error")
            raise
        text = "".join(parts)
        html = provider.last_response_html if isinstance(provider, BR) else None
        await asyncio.to_thread(
            sessions.finish, recording, text, html=html)
        response.headers["X-Chat2api-Session-Id"] = recording.session_id
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
    from .schemas import (AccountLoginRequest, AddAccountRequest, ApiKeyCreateRequest,
                          IntegrateRequest, ProfileAccountRequest, ProfileCreateRequest,
                          ProfileOpenRequest, ProfileUpdateRequest, SaveAccountRequest,
                          SessionForkRequest, SessionUpdateRequest, SettingsRequest)

    # Tab do người dùng mở tay trong một profile. Đặt tên như một slug recipe để
    # dùng chung cơ chế một-tab-một-slug của pool, nhưng không recipe nào tên
    # được như vậy (slug thật chỉ gồm [a-z0-9-]).
    MANUAL_SLUG = "__manual__"
    # Nơi cất tạm state khi người dùng mở browser mà chưa biết domain (§6.1 bậc
    # 4). Không phải domain hợp lệ nên không lọt vào danh sách domain.
    PENDING_DIRNAME = "_pending"

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

    @admin.get("/profiles")
    async def profile_list(request: Request):
        cfg = request.app.state.cfg
        pool_ = request.app.state.pool
        items = await asyncio.to_thread(profiles.list_profiles)
        open_now = set(pool_.open_profiles)
        for item in items:
            item["open"] = item["name"] in open_now
            item["tabs"] = pool_.tab_count(item["name"])
        return {"profiles": items, "mode": cfg.browser_profile_mode,
                "profiles_dir": str(cfg.profiles_dir),
                "max_profiles": cfg.pool_max_profiles,
                "persisted": store.default() is not None}

    def _need_store() -> None:
        if store.default() is None:
            raise OpenAIError(503, "store_unavailable",
                              "Kho dữ liệu chưa mở nên chưa quản lý được profile.")

    async def _profile_or_404(ident: str) -> dict:
        row = await asyncio.to_thread(profiles.find, ident)
        if row is None:
            _need_store()
            raise OpenAIError(404, "not_found", f"Profile '{ident}' không tồn tại")
        return row

    @admin.post("/profiles")
    async def profile_create(body: ProfileCreateRequest, request: Request):
        _need_store()
        try:
            row = await asyncio.to_thread(
                profiles.create, (body.name or "").strip().lower(),
                request.app.state.cfg.profiles_dir, body.model_dump(exclude_none=True))
        except ValueError as error:
            raise OpenAIError(400, "invalid_profile", str(error))
        applog.log(f"profile: tạo '{row['name']}'")
        return row

    @admin.patch("/profiles/{ident}")
    async def profile_update(ident: str, body: ProfileUpdateRequest):
        row = await _profile_or_404(ident)
        if body.name is not None and body.name.strip() != row["name"]:
            # Tên profile LÀ tên thư mục Chromium đang giữ mọi đăng nhập của nó.
            # Đổi tên phải kéo theo di chuyển thư mục và nhả khoá pid, nên nói
            # thẳng là không làm chứ không lặng lẽ bỏ qua.
            raise OpenAIError(400, "rename_unsupported",
                              "Không đổi tên profile được. Tạo profile mới rồi đăng nhập lại.")
        try:
            updated = await asyncio.to_thread(profiles.update, row["id"],
                                              body.model_dump(exclude_none=True))
        except ValueError as error:
            raise OpenAIError(400, "invalid_profile", str(error))
        applog.log(f"profile: cập nhật '{row['name']}'")
        return updated

    @admin.delete("/profiles/{ident}")
    async def profile_delete(ident: str, request: Request, purge: bool = False):
        row = await _profile_or_404(ident)
        # Kiểm tra TRƯỚC khi đóng browser: từ chối xoá mà vẫn đá người dùng ra
        # khỏi phiên đang chạy thì tệ hơn là không làm gì cả.
        used = await asyncio.to_thread(profiles.blockers, row["id"])
        if used:
            raise OpenAIError(409, "profile_in_use",
                              f"Profile '{row['name']}' còn được recipe dùng: {', '.join(used)}")
        await request.app.state.pool.drop_profile(row["name"])
        try:
            await asyncio.to_thread(profiles.delete, row["id"], remove_dir=purge)
        except profiles.ProfileInUse as error:
            raise OpenAIError(409, "profile_in_use", str(error))
        except profiles.ProfileLocked as error:
            raise OpenAIError(409, "profile_locked", str(error))
        applog.log(f"profile: xóa '{row['name']}'" + (" kèm thư mục" if purge else ""), "warn")
        return {"ok": True}

    @admin.post("/profiles/{ident}/open")
    async def profile_open(ident: str, request: Request, body: ProfileOpenRequest):
        """Mở cửa sổ profile để người dùng tự đăng nhập thêm domain (§6.1)."""
        from dataclasses import replace

        cfg = request.app.state.cfg
        pool_ = request.app.state.pool
        row = await _profile_or_404(ident)
        if (row["engine"] or cfg.browser_engine) == "cloak":
            raise OpenAIError(400, "engine_unsupported",
                              "Engine cloak không mở được persistent profile.")
        profile = await asyncio.to_thread(profiles.ensure_profile, row["name"], cfg.profiles_dir)
        if profile is None:
            _need_store()
            raise OpenAIError(404, "not_found", f"Profile '{ident}' không tồn tại")
        # Profile đang chạy nền (headless) thì giữ nguyên tiến trình đó — mở lại
        # headed sẽ đụng khoá user_data_dir. Live view vẫn xem được tab.
        reused = pool_.open_context(profile.name) is not None
        try:
            page = await pool_.page_for(replace(profile, headless=False), MANUAL_SLUG)
        except profiles.ProfileLocked as error:
            raise OpenAIError(409, "profile_locked", str(error))
        except Exception as error:
            applog.log(f"profile: không mở được '{profile.name}': {error}", "error")
            raise OpenAIError(500, "profile_open_failed",
                              f"Không mở được profile '{profile.name}': {error}")
        target = body.url.strip()
        if target:
            try:
                await page.goto(target, wait_until="domcontentloaded", timeout=30000)
            except Exception as error:
                applog.log(f"profile: '{profile.name}' không tới được {target}: {error}", "warn")
        watch_id = f"profile-{profile.id}"
        await live_view.register(watch_id, page)
        applog.log(f"profile: mở cửa sổ '{profile.name}'")
        return {"ok": True, "profile": profile.name, "watch_id": watch_id,
                "headless": reused and bool(row["headless"])}

    @admin.post("/profiles/{ident}/detect")
    async def profile_detect(ident: str, request: Request):
        """Domain profile này còn đăng nhập nhưng chưa khai báo account (§6.1)."""
        row = await _profile_or_404(ident)
        ctx = request.app.state.pool.open_context(row["name"])
        if ctx is None:
            raise OpenAIError(409, "profile_not_open",
                              f"Profile '{row['name']}' chưa mở. Bấm Mở rồi dò lại.")
        try:
            cookies = await ctx.cookies()
        except Exception as error:
            raise OpenAIError(500, "detect_failed", f"Không đọc được cookie: {error}")
        known = {item["host"] for item in await asyncio.to_thread(profiles.accounts_of, row["id"])}
        hosts = accounts.session_hosts(cookies)
        return {"profile": row["name"], "known": sorted(known),
                "suggested": [host for host in hosts if host not in known]}

    @admin.post("/profiles/{ident}/accounts")
    async def profile_add_account(ident: str, body: ProfileAccountRequest):
        """Khai báo "profile này đã đăng nhập domain kia" — nút thêm-luôn."""
        row = await _profile_or_404(ident)
        host = body.domain.strip().lower()
        if not accounts.valid_domain(host):
            raise OpenAIError(400, "invalid_domain", "Domain không hợp lệ")
        label = (body.label or "").strip() or "main"
        if not accounts.valid_name(label):
            raise OpenAIError(400, "invalid_account_name",
                              "Nhãn account chỉ được gồm chữ thường, số và dấu -")
        item = await asyncio.to_thread(profiles.add_account, row["id"], host, label)
        applog.log(f"account: gắn {host}/{label} vào profile '{row['name']}'")
        return {"ok": True, "account": item}

    @admin.post("/profiles/{name}/close")
    async def profile_close(name: str, request: Request):
        closed = await request.app.state.pool.drop_profile(name)
        if closed:
            applog.log(f"profile: đã đóng '{name}'")
        return {"ok": True, "closed": closed}

    @admin.get("/sessions")
    async def session_list(q: str = "", model: str = "", archived: bool = False,
                           limit: int = 100):
        items = await asyncio.to_thread(sessions.list_sessions, q, model, archived, limit)
        return {"sessions": items, "persisted": store.default() is not None}

    @admin.get("/sessions/{session_id}")
    async def session_detail(session_id: str):
        item = await asyncio.to_thread(sessions.get_session, session_id)
        if item is None:
            raise OpenAIError(404, "not_found", "Session không tồn tại")
        return item

    @admin.patch("/sessions/{session_id}")
    async def session_update(session_id: str, body: SessionUpdateRequest):
        values = body.model_dump(exclude_none=True)
        item = await asyncio.to_thread(sessions.update_session, session_id, values)
        if item is None:
            raise OpenAIError(404, "not_found", "Session không tồn tại")
        return item

    @admin.delete("/sessions/{session_id}")
    async def session_delete(session_id: str):
        if not await asyncio.to_thread(sessions.delete_session, session_id):
            raise OpenAIError(404, "not_found", "Session không tồn tại")
        return {"ok": True}

    @admin.post("/sessions/{session_id}/fork")
    async def session_fork(session_id: str, body: SessionForkRequest):
        item = await asyncio.to_thread(sessions.fork_session, session_id, body.up_to_seq)
        if item is None:
            raise OpenAIError(404, "not_found", "Session không tồn tại")
        return item

    @admin.get("/sessions/{session_id}/export")
    async def session_export(session_id: str, format: str = "md"):
        if format not in {"md", "html", "json", "jsonl"}:
            raise OpenAIError(400, "invalid_format", "Format phải là md, html, json hoặc jsonl")
        result = await asyncio.to_thread(sessions.export_session, session_id, format)
        if result is None:
            raise OpenAIError(404, "not_found", "Session không tồn tại")
        content, media_type = result
        suffix = "md" if format == "md" else format
        return Response(
            content=content, media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="session-{session_id[:8]}.{suffix}"'},
        )

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
                # Trang Integrations gộp account vào ngay trong hàng recipe, nên
                # nó cần biết recipe này thuộc domain nào (§6).
                entry["domain"] = provider.domain
                entry["url"] = provider.url
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

    @admin.get("/domains")
    async def domain_list(request: Request):
        """Mọi domain đã biết — nguồn cho dropdown ở dialog thêm account (§6.1)."""
        cfg = request.app.state.cfg
        usage = _domain_usage(request)
        known = await asyncio.to_thread(profiles.known_hosts)
        hosts = sorted(set(known) | set(accounts.list_domains(cfg.recipes_dir)) | set(usage))
        return {"domains": [
            {"host": host,
             "accounts": len(accounts.list_accounts(cfg.recipes_dir, host)),
             "recipes": sorted(usage.get(host, []))}
            for host in hosts]}

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
        if domain and not accounts.valid_domain(domain):
            raise OpenAIError(400, "invalid_domain", "Domain không hợp lệ")
        session_id = f"acct-{uuid.uuid4().hex[:10]}"
        if domain:
            url = body.url.strip() or f"https://{domain}"
            login_dir = accounts.domain_dir(cfg.recipes_dir, domain)
            state_path = accounts.account_path(cfg.recipes_dir, domain, body.name.strip()) \
                if accounts.valid_name(body.name.strip()) else None
        else:
            # Bậc 4 của "tự dò domain" (§6.1): chưa biết đi đâu thì mở trang
            # trắng, người dùng tự vào site và đăng nhập; domain suy ra từ cookie
            # lúc lưu. State cất tạm ở _pending rồi chuyển về đúng domain sau.
            url = body.url.strip() or "about:blank"
            login_dir = accounts.store_dir(cfg.recipes_dir) / PENDING_DIRNAME
            state_path = None
        try:
            await request.app.state.login_manager.start(
                session_id, domain or "unknown", url, login_dir, storage_state=state_path)
        except Exception:
            applog.log(f"account: không mở được browser cho {domain or 'domain chưa rõ'}", "error")
            raise OpenAIError(500, "login_open_failed",
                              "Không thể mở browser đăng nhập trên máy chạy chat2api.")
        applog.log("account: mở browser đăng nhập "
                   f"{domain or 'trang trắng, chờ tự dò domain'} (session={session_id})")
        return {"session_id": session_id, "domain": domain}

    async def _login_snapshot(manager, session_id: str) -> dict:
        """Cookie + URL của phiên đăng nhập, {} nếu manager không hỗ trợ.

        Best-effort: đây chỉ là đường tự dò domain, không được làm hỏng việc lưu
        account khi có gì đó trục trặc.
        """
        snapshot = getattr(manager, "snapshot", None)
        if snapshot is None:
            return {}
        try:
            return await snapshot(session_id) or {}
        except Exception:
            return {}

    @admin.post("/accounts/login/{session_id}/complete")
    async def complete_domain_login(session_id: str, request: Request, body: SaveAccountRequest):
        cfg = request.app.state.cfg
        manager = request.app.state.login_manager
        domain, name = body.domain.strip().lower(), body.name.strip()
        # Đọc cookie TRƯỚC complete() — complete() đóng browser, sau đó không
        # còn gì để dò nữa.
        snapshot = await _login_snapshot(manager, session_id)
        cookies = snapshot.get("cookies") or []
        if not domain:
            domain = accounts.infer_domain(cookies, snapshot.get("url", ""))
            if not domain:
                raise OpenAIError(400, "domain_not_detected",
                                  "Chưa dò được domain: hãy đăng nhập xong rồi lưu lại, "
                                  "hoặc nhập domain bằng tay.")
            applog.log(f"account: tự dò ra domain {domain} (session={session_id})")
        if not accounts.valid_domain(domain):
            raise OpenAIError(400, "invalid_domain", "Domain không hợp lệ")
        if not accounts.valid_name(name):
            raise OpenAIError(400, "invalid_account_name",
                              "Tên account chỉ được gồm chữ thường, số và dấu -")
        try:
            # login_manager ghi vào <recipe_dir>/auth/<file>; recipe_dir ở đây là
            # thư mục domain nên state nằm đúng kho chung.
            saved = await manager.complete(session_id, filename=f"{name}.json")
        except Exception:
            applog.log(f"account: lưu session thất bại cho {domain}/{name}", "error")
            raise OpenAIError(500, "login_save_failed", "Không thể lưu session đăng nhập")
        target = accounts.account_path(cfg.recipes_dir, domain, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if saved.resolve() != target.resolve():
            shutil.move(str(saved), str(target))
            # Thư mục tạm của luồng "chưa biết domain" không được để lại rác.
            pending = accounts.store_dir(cfg.recipes_dir) / PENDING_DIRNAME
            if pending in saved.parents:
                shutil.rmtree(pending, ignore_errors=True)
        request.app.state.router.reload()
        applog.log(f"account: đã lưu {domain}/{name}")
        # Cùng một lần đăng nhập thường mang theo cookie của domain khác (đăng
        # nhập Google chẳng hạn). Chỉ ra chúng để người dùng thêm luôn, thay vì
        # phải mở browser lại lần nữa — đây là chỗ "một profile nhiều domain"
        # trở nên nhìn thấy được trên UI.
        suggested = [host for host in accounts.session_hosts(cookies)
                     if host != domain and not accounts.list_accounts(cfg.recipes_dir, host)]
        return {"ok": True, "domain": domain, "name": name, "suggested": suggested}

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
        fields = await asyncio.to_thread(settings.describe)
        return {"fields": fields,
                "env_path": str(request.app.state.cfg.env_path),
                # false ⇒ đang ghi vào .env vì kho chưa mở; UI nói khác đi.
                "persisted": store.default() is not None}

    @admin.put("/settings")
    async def put_settings(request: Request, body: SettingsRequest):
        clean, errs = settings.validate(body.values)
        if errs:
            raise OpenAIError(400, "invalid_settings", "; ".join(errs))
        needs_restart = await asyncio.to_thread(
            settings.save, request.app.state.cfg.env_path, clean)
        request.app.state.router.reload()
        applog.log(f"settings: cập nhật {', '.join(sorted(clean))}")
        return {"ok": True, "saved": sorted(clean), "needs_restart": sorted(needs_restart),
                # Đã ghi xuống DB nhưng .env vẫn thắng: nói thẳng, đừng để người
                # dùng tưởng đã đổi được.
                "shadowed": settings.shadowed(clean)}

    # ------------------------------------------------------------- api key

    @admin.get("/api-keys")
    async def api_key_list(request: Request):
        keys = await asyncio.to_thread(apikeys.list_keys)
        cfg = request.app.state.cfg
        active = [k for k in keys if not k["revoked_at"]]
        return {
            "keys": keys,
            "persisted": store.default() is not None,
            # Key trong CHAT2API_KEYS không có hàng DB nên không liệt kê được;
            # chỉ đếm để UI giải thích vì sao server vẫn đòi key khi bảng rỗng.
            "bootstrap_keys": len(cfg.api_keys),
            "enforced": bool(active or cfg.api_keys),
        }

    @admin.post("/api-keys")
    async def api_key_create(body: ApiKeyCreateRequest, request: Request):
        try:
            row = await asyncio.to_thread(apikeys.create, body.label, body.scopes)
        except ValueError as error:
            raise OpenAIError(400, "invalid_api_key", str(error))
        except RuntimeError as error:
            raise OpenAIError(503, "store_unavailable", str(error))
        # Chỉ ghi nhãn. Key thô chỉ tồn tại trong response này, không vào log.
        applog.log(f"auth: tạo api key '{row['label']}' ({row['key_prefix']}…)")
        return row

    @admin.delete("/api-keys/{key_id}")
    async def api_key_delete(key_id: int, purge: bool = False):
        if purge:
            removed = await asyncio.to_thread(apikeys.delete, key_id)
            if not removed:
                raise OpenAIError(404, "not_found", f"API key {key_id} không tồn tại")
            applog.log(f"auth: xóa hẳn api key {key_id}", "warn")
            return {"ok": True, "purged": True}
        row = await asyncio.to_thread(apikeys.revoke, key_id)
        if row is None:
            raise OpenAIError(404, "not_found", f"API key {key_id} không tồn tại")
        applog.log(f"auth: thu hồi api key '{row['label']}'", "warn")
        return row

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