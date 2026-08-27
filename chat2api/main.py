import asyncio
import json
import sys
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import (accounts, apikeys, applog, auth, errors, profiles, sessions,  # noqa: F401  (import auth để đăng ký dependency)
               settings, store)
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


def _target_headers(session_id: str, assignment) -> dict[str, str]:
    """Header nói thẳng request này chạy trên profile/account nào.

    Client đọc được ngay từ response đầu tiên, kể cả khi stream còn chưa có
    delta nào — nên "gửi tới đâu" không còn phải suy đoán từ log.
    """
    out = {"X-Chat2api-Session-Id": session_id}
    if assignment is None or assignment.account_id is None:
        return out
    out["X-Chat2api-Account-Id"] = str(assignment.account_id)
    out["X-Chat2api-Account-Label"] = assignment.account_label or ""
    out["X-Chat2api-Profile-Id"] = str(assignment.profile_id or "")
    out["X-Chat2api-Profile-Name"] = assignment.profile_name or ""
    out["X-Chat2api-Target"] = assignment.label
    if assignment.headed is not None:
        out["X-Chat2api-Headed"] = "true" if assignment.headed else "false"
    return out


def _reply_extras(provider, assignment, browser_recipe_cls) -> tuple[str | None, str | None]:
    """(HTML gốc, link hội thoại) của đúng request này.

    Đọc từ assignment chứ không từ `provider.last_response_html`: một provider
    phục vụ nhiều request song song, thuộc tính trên instance là của lượt nào
    ghi sau cùng chứ không phải của lượt đang kết thúc.
    """
    if assignment is not None:
        return assignment.html, assignment.conversation_url
    if isinstance(provider, browser_recipe_cls):
        return provider.last_response_html, None
    return None, None


class _ConcurrencyGate:
    """Trần số request chat chạy song song (API_MAX_CONCURRENT_REQUESTS).

    Vượt trần thì request mới CHỜ chứ không bị từ chối — client gửi một loạt
    request vẫn nhận đủ câu trả lời, chỉ là không mở 20 tab Chromium một lúc.
    0 = không giới hạn.
    """

    def __init__(self) -> None:
        self._sem: asyncio.Semaphore | None = None
        self._size = 0

    @asynccontextmanager
    async def slot(self):
        limit = settings.current_int("API_MAX_CONCURRENT_REQUESTS", 0)
        if limit <= 0:
            yield
            return
        # Đổi trần lúc đang chạy thì dựng semaphore mới; các request đang giữ
        # semaphore cũ vẫn chạy tiếp, trần mới có hiệu lực đủ từ lượt sau.
        if self._sem is None or self._size != limit:
            self._sem = asyncio.Semaphore(limit)
            self._size = limit
        async with self._sem:
            yield


def merge_recipe(base: dict, patch: dict) -> dict:
    """Ghép mảnh `patch` vào recipe `base`, giữ nguyên khóa ngoài patch.

    Biểu mẫu sửa recipe chỉ mô hình hóa được một phần recipe.yaml; những khóa
    nó không biết (`response.format`, `response.capture_html`, `login.accounts`,
    …) phải sống sót qua một lần Lưu. Quy ước:

    - mapping lồng nhau → merge đệ quy; rỗng sau khi merge → bỏ luôn khóa, để
      biểu mẫu xóa trắng cả cụm `timing` mà không để lại một mớ khóa `null`;
    - `None` → xóa hẳn khóa đó (biểu mẫu bỏ chọn `new_chat` chẳng hạn);
    - giá trị khác (kể cả list `models`) → thay thế nguyên khối.
    """
    out = dict(base)
    for key, value in patch.items():
        if value is None:
            out.pop(key, None)
        elif isinstance(value, dict):
            current = out.get(key)
            merged = merge_recipe(current if isinstance(current, dict) else {}, value)
            if merged:
                out[key] = merged
            else:
                out.pop(key, None)
        else:
            out[key] = value
    return out


async def run_recipe_trial(cfg: Config, pool, recipe: dict, headed: bool) -> dict:
    """Chạy đúng một prompt cố định qua `recipe` mà KHÔNG ghi nó xuống đĩa.

    Dùng chung cho cả recipe tạo mới lẫn bản đang sửa: người dùng biết selector
    đúng hay sai trước khi bấm lưu (form thủ công không có bước round-trip tự
    sửa như analyzer AI).
    """
    from .providers.browser_recipe import BrowserRecipe

    trial_slug = f"manual-test-{uuid.uuid4().hex[:10]}"
    trial_recipe = {**recipe, "slug": trial_slug}
    trial_dir = cfg.recipes_dir / ".manual-test" / trial_slug
    runner = BrowserRecipe(trial_recipe, trial_dir, pool, headed=headed,
                           accounts_root=cfg.recipes_dir)
    try:
        parts = []
        async for delta in runner.stream(
            [{"role": "user", "content": "Reply with exactly: OK"}],
            trial_recipe["models"][0]["id"],
        ):
            parts.append(delta)
        reply = "".join(parts).strip()
    except Exception as error:
        return {"ok": False, "reply": "", "error": str(error)}
    finally:
        await pool.drop(trial_slug)
    ok = bool(reply) and reply.lower() != "reply with exactly: ok"
    return {"ok": ok, "reply": reply}


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
    # expose_headers là bắt buộc: trình duyệt chỉ cho JS đọc vài header
    # safelisted, nên nếu không liệt kê ra đây thì desktop nhận response 200
    # nhưng `headers.get("X-Chat2api-...")` luôn null — mất cả session id lẫn
    # thông tin "request này đi tới account/profile nào".
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-Chat2api-Session-Id", "X-Chat2api-Account-Id",
            "X-Chat2api-Account-Label", "X-Chat2api-Profile-Id",
            "X-Chat2api-Profile-Name", "X-Chat2api-Target",
            "X-Chat2api-Conversation-Url", "X-Chat2api-Headed",
        ],
    )
    errors.register_error_handler(app)
    app.state.cfg = cfg
    app.state.pool = pool
    app.state.login_manager = login_manager
    app.state.router = router
    app.state.recipe_publish_lock = asyncio.Lock()
    app.state.chat_gate = _ConcurrencyGate()

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
        msgs = body.as_list()
        cid = "chatcmpl-" + uuid.uuid4().hex[:29]
        from .providers.browser_recipe import BrowserRecipe as BR

        requested_session = sessions.normalize_session_id(
            request.headers.get("x-chat2api-session-id"))
        target_account_id = None
        raw_target = request.headers.get("x-chat2api-account-id", "").strip()
        if raw_target:
            if not isinstance(provider, BR):
                raise OpenAIError(400, "target_unsupported",
                                  "Chỉ browser recipe hỗ trợ chọn profile/account")
            try:
                target_account_id = int(raw_target)
            except (TypeError, ValueError):
                raise OpenAIError(400, "invalid_target",
                                  f"X-Chat2api-Account-Id không phải số: {raw_target!r}")

        # Chọn account/profile TRƯỚC khi mở response: SSE không sửa được header
        # sau byte đầu, mà "request này đi tới đâu" phải trả về ngay. Đây cũng là
        # chỗ hai request đến cùng lúc được tách ra hai account khác nhau — chọn
        # muộn hơn (bên trong stream) thì cả hai đã cùng nhìn thấy mọi account rảnh.
        assignment = None
        if isinstance(provider, BR):
            try:
                assignment = await provider.assign(
                    target_account_id, sticky_key=requested_session or "")
            except ValueError as error:
                raise OpenAIError(400, "invalid_target", str(error))
            except TrialLimitExceeded as error:
                applog.log(f"chat: hết lượt dùng thử ({provider.slug}): {error}", "warn")
                raise OpenAIError(403, "trial_limit_exceeded", str(error))

        # Ghi một transaction trước provider và một transaction khi kết thúc;
        # tuyệt đối không ghi từng SSE delta. Header session cho desktop nối
        # nhiều lượt vào cùng một bản ghi; client API không gửi thì mỗi request
        # là một session riêng (đổi được bằng API_SESSION_MODE).
        # Ba trạng thái, không phải hai: "true"/"false" là mệnh lệnh của client,
        # KHÔNG gửi header (None) là nhường cho API_HEADED rồi tới ô "Chạy ẩn"
        # của profile. Trước đây header vắng mặt bị hiểu thành "chạy ẩn", nên
        # request API không bao giờ mở được cửa sổ dù cấu hình thế nào.
        raw_headed = request.headers.get("x-chat2api-headed", "").strip().lower()
        headed = True if raw_headed == "true" else False if raw_headed == "false" else None

        try:
            recording = await asyncio.to_thread(
                sessions.begin,
                requested_session, body.model, provider.slug,
                msgs, body.stream, request.headers.get("authorization", ""),
                request.headers.get("user-agent", ""),
                getattr(request.state, "api_key_id", None),
                assignment.account_id if assignment else None,
                assignment.profile_id if assignment else None,
                settings.current("API_SESSION_MODE"),
            )
        except Exception:
            # Chỗ đã giữ ở `assign()` chỉ được nhả trong đường đi qua stream;
            # hỏng trước đó mà không nhả thì account đó bận vĩnh viễn.
            if assignment is not None:
                assignment.release()
            raise
        if assignment is not None:
            assignment.headed = provider.resolve_headed(headed, assignment.profile)
        target_headers = _target_headers(recording.session_id, assignment)
        response.headers.update(target_headers)
        applog.log(
            f"chat: model={body.model} stream={body.stream} session={recording.session_id[:8]}"
            + (f" → {assignment.label}" if assignment and assignment.account_id else "")
            + (" (cửa sổ)" if assignment and assignment.headed else ""))

        def fallback_ok(reason: str) -> bool:
            from .agents import llm

            return (isinstance(provider, BR) and target_account_id is None and cfg_.enable_fallback
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
            # Trần song song ôm trọn cả stream: giữ chỗ từ lúc bắt đầu tới byte
            # cuối, chứ không phải chỉ lúc mở tab.
            async with request.app.state.chat_gate.slot():
                if rt.is_unhealthy(provider.slug) and fallback_ok("unhealthy recipe"):
                    async for d in agent_stream():
                        yield d
                    return
                async for d in _run_provider(sent):
                    yield d

        async def _run_provider(sent):
            try:
                stream_kwargs = {"headed": headed} if isinstance(provider, BR) else {}
                if assignment is not None:
                    # Assignment đã mang sẵn account + profile + tab, nên không
                    # truyền kèm target_account_id nữa (stream chỉ dùng nó khi
                    # phải tự gán).
                    stream_kwargs["assignment"] = assignment
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
                    html, url = _reply_extras(provider, assignment, BR)
                    if cancelled:
                        await asyncio.to_thread(
                            sessions.finish, recording, text,
                            status="cancelled", error_code="client_cancelled",
                            error_message="Client đã ngắt stream", finish_reason="error",
                            conversation_url=url)
                    elif final_error is not None:
                        status = ("timeout" if final_error.code == "recipe_timeout" else
                                  "trial_limit" if final_error.code == "trial_limit_exceeded" else "error")
                        await asyncio.to_thread(
                            sessions.finish, recording, text,
                            html=html, status=status, error_code=final_error.code,
                            error_message=final_error.message, http_status=final_error.status,
                            finish_reason="error", conversation_url=url)
                    else:
                        await asyncio.to_thread(
                            sessions.finish, recording, text, html=html, conversation_url=url)
                    # Nhả chỗ đã giữ ở `assign()` — kể cả khi client ngắt giữa
                    # chừng, nếu không account đó vĩnh viễn bị coi là đang bận.
                    if assignment is not None:
                        assignment.release()
                if not cancelled:
                    yield "data: [DONE]\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream",
                                     headers=target_headers)

        parts: list[str] = []
        try:
            try:
                async for d in upstream():
                    if not parts:
                        sessions.first_delta(recording)
                    parts.append(d)
            except TimeoutError:
                error = OpenAIError(504, "recipe_timeout", "Recipe timeout", "api_error")
                _, url = _reply_extras(provider, assignment, BR)
                await asyncio.to_thread(
                    sessions.finish, recording, "".join(parts),
                    status="timeout", error_code=error.code,
                    error_message=error.message, http_status=error.status,
                    finish_reason="error", conversation_url=url)
                raise error
            except OpenAIError as error:
                status = "trial_limit" if error.code == "trial_limit_exceeded" else "error"
                _, url = _reply_extras(provider, assignment, BR)
                await asyncio.to_thread(
                    sessions.finish, recording, "".join(parts),
                    status=status, error_code=error.code,
                    error_message=error.message, http_status=error.status,
                    finish_reason="error", conversation_url=url)
                raise
            text = "".join(parts)
            html, url = _reply_extras(provider, assignment, BR)
            await asyncio.to_thread(
                sessions.finish, recording, text, html=html, conversation_url=url)
        finally:
            if assignment is not None:
                assignment.release()
        response.headers.update(target_headers)
        if url:
            response.headers["X-Chat2api-Conversation-Url"] = url
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
                           ProfileOpenRequest, ProfileUpdateRequest, RecipeManualSpec,
                           RecipeModelDiscoveryRequest,
                           RecipeEditRequest, RecipeEditTestRequest, RecipeRenameRequest,
                           RecipeTestRequest, SaveAccountRequest,
                           SessionDeleteRequest, SessionForkRequest, SessionUpdateRequest,
                           SettingsRequest, TestTargetOpenRequest)

    # Tab do người dùng mở tay trong một profile. Đặt tên như một slug recipe để
    # dùng chung cơ chế một-tab-một-slug của pool, nhưng không recipe nào tên
    # được như vậy (slug thật chỉ gồm [a-z0-9-]).
    MANUAL_SLUG = "__manual__"

    def _browser_recipes_by_domain(rt) -> dict[str, list]:
        """domain đã chuẩn hoá → các browser recipe phục vụ nó (theo thứ tự slug)."""
        from .providers.browser_recipe import BrowserRecipe

        out: dict[str, list] = {}
        for slug, provider in sorted(rt.providers.items()):
            if isinstance(provider, BrowserRecipe):
                out.setdefault(provider.domain, []).append(provider)
        return out

    def _account_rows() -> list[dict]:
        db = store.default()
        if db is None:
            return []
        return [dict(row) for row in db.query(
            "SELECT a.id, a.label, a.status, a.disabled, d.host, "
            "p.id AS profile_id, p.name AS profile_name, p.headless, p.max_tabs "
            "FROM account a JOIN profile p ON p.id = a.profile_id "
            "JOIN domain d ON d.id = a.domain_id "
            "WHERE a.disabled = 0 ORDER BY p.name, d.host, a.label")]

    @admin.get("/test-targets")
    async def test_target_list(request: Request):
        """Toàn bộ ma trận profile × domain × account có thể đem ra test.

        Khác `/admin/profiles` (chỉ kể account) và `/admin/recipes` (chỉ kể
        model): ở đây hai bên đã được ghép sẵn, nên desktop không phải tự đoán
        domain nào khớp recipe nào — chỗ mà 'www.' hay recipe trùng domain vẫn
        làm lệch danh sách.
        """
        cfg = request.app.state.cfg
        pool_ = request.app.state.pool
        by_domain = _browser_recipes_by_domain(request.app.state.router)
        open_now = set(pool_.open_profiles)
        targets = []
        for row in _account_rows():
            host = str(row["host"] or "").lower()
            domain = host[4:] if host.startswith("www.") else host
            providers_ = by_domain.get(domain, [])
            models_ = [m.id for provider in providers_ for m in provider.models()]
            targets.append({
                "account_id": row["id"], "label": row["label"] or "main",
                "host": host, "domain": domain,
                "status": row["status"] or "",
                "profile_id": row["profile_id"], "profile_name": row["profile_name"],
                "profile_headless": bool(row["headless"]),
                "profile_open": row["profile_name"] in open_now,
                "profile_tabs": pool_.tab_count(row["profile_name"]),
                "profile_max_tabs": int(row["max_tabs"] or cfg.profile_max_tabs),
                "recipes": [provider.slug for provider in providers_],
                "models": models_,
                # Request đang chạy trên account này (mọi recipe cùng domain).
                # Bàn test đọc để biết chọn thêm target là thêm việc song song
                # thật, hay chỉ xếp thêm hàng vào một tab đang bận.
                "busy": sum(provider.account_load(row["id"]) for provider in providers_),
                # Không có recipe nào phục vụ domain này ⇒ chọn cũng không chạy
                # được; desktop hiện nó mờ kèm lý do thay vì giấu đi.
                "ready": bool(models_),
            })
        return {"targets": targets, "max_profiles": cfg.pool_max_profiles,
                "max_tabs": cfg.profile_max_tabs,
                "profile_mode": cfg.browser_profile_mode,
                "open_profiles": sorted(open_now),
                "persisted": store.default() is not None}

    def _provider_for_target(request: Request, model: str, account_id: int):
        """Browser recipe chạy một account: theo `model` nếu có, không thì tự suy."""
        from .providers.browser_recipe import BrowserRecipe

        rt = request.app.state.router
        if model:
            try:
                provider, _ = rt.resolve(model)
            except ModelNotFound:
                raise OpenAIError(404, "model_not_found", f"Model '{model}' không tồn tại")
            if not isinstance(provider, BrowserRecipe):
                raise OpenAIError(400, "target_unsupported",
                                  "Model này không chạy bằng browser recipe")
            return provider
        row = next((r for r in _account_rows() if r["id"] == account_id), None)
        if row is None:
            raise OpenAIError(400, "invalid_target",
                              f"Account {account_id} không tồn tại hoặc đã tắt")
        host = str(row["host"] or "").lower()
        domain = host[4:] if host.startswith("www.") else host
        providers_ = _browser_recipes_by_domain(rt).get(domain, [])
        if not providers_:
            raise OpenAIError(400, "target_unsupported",
                              f"Chưa có recipe nào phục vụ {host}")
        return providers_[0]

    @admin.post("/test-targets/open")
    async def test_target_open(body: TestTargetOpenRequest, request: Request):
        """Open the exact headed tab used by a targeted desktop chat request."""
        provider = _provider_for_target(request, body.model.strip(), body.account_id)
        try:
            target, page = await provider.open_target(body.account_id)
        except ValueError as error:
            raise OpenAIError(400, "invalid_target", str(error))
        applog.log(f"test-target: mở {target['profile_name']}/{target['host']}"
                   f"/{target['label']} qua {provider.slug}")
        return {"ok": True, "profile": target["profile_name"],
                "account": target["label"], "domain": target["host"],
                "url": page.url,
                "model": f"{provider.slug}/{provider.models()[0].id.split('/', 1)[1]}"
                         if provider.models() else "",
                "recipe": provider.slug}
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
        # Bắt buộc có profile hợp lệ trước khi mở job: nếu site cần đăng nhập,
        # login lưu thẳng vào profile này thay vì rơi vào một profile tự sinh.
        profile_row = await asyncio.to_thread(profiles.find, str(body.profile_id))
        if profile_row is None:
            raise OpenAIError(400, "invalid_profile",
                              "Chọn một profile hợp lệ trước khi tích hợp.")
        job_id = jobs.start_integrate(
            body.url, cfg, request.app.state.pool,
            router=request.app.state.router,
            login_manager=request.app.state.login_manager,
            publish_lock=request.app.state.recipe_publish_lock,
            headed=body.headed,
            profile={"id": profile_row["id"], "name": profile_row["name"]},
        )
        applog.log(f"integrate: bắt đầu {body.url} (job={job_id}, headed={body.headed}, "
                   f"profile={profile_row['name']})")
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
            raise OpenAIError(
                409, "profile_in_use",
                f"Xoá profile '{row['name']}' sẽ làm hỏng recipe: {', '.join(used)} — "
                "recipe ghim thẳng profile này, hoặc đây là account cuối cùng còn bật "
                "của domain nó dùng. Bỏ ghim, hoặc thêm account khác cho domain đó, "
                "rồi xoá lại.")
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
        tab_key = re.sub(r"[^a-zA-Z0-9_-]", "", body.tab_key.strip())[:80]
        manual_slug = f"{MANUAL_SLUG}-{tab_key}" if tab_key else MANUAL_SLUG
        try:
            page = await pool_.page_for(replace(profile, headless=False), manual_slug)
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
        applog.log(f"profile: mở cửa sổ '{profile.name}'")
        # `headless: true` ⇒ profile đã chạy nền từ trước nên không có cửa sổ nào
        # hiện ra; client phải bảo người dùng đóng profile rồi mở lại.
        return {"ok": True, "profile": profile.name,
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

    @admin.delete("/sessions")
    async def sessions_delete(body: SessionDeleteRequest):
        ids = None if body.all else body.ids or []
        deleted = await asyncio.to_thread(sessions.delete_sessions, ids)
        return {"ok": True, "deleted": deleted}

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

    @admin.post("/sessions/{session_id}/open")
    async def session_open(session_id: str, request: Request):
        """Mở lại hội thoại của session trong đúng profile đã chạy nó.

        Khác việc dán link vào browser thường: chỉ profile này mới có đăng nhập
        đã tạo ra hội thoại đó, mở chỗ khác chỉ thấy trang đăng nhập.
        """
        from dataclasses import replace

        cfg = request.app.state.cfg
        item = await asyncio.to_thread(sessions.get_session, session_id)
        if item is None:
            raise OpenAIError(404, "not_found", "Session không tồn tại")
        url = (item.get("site_conversation_url") or "").strip()
        if not url:
            raise OpenAIError(409, "no_conversation_url",
                              "Session này chưa ghi được link hội thoại trên site nguồn.")
        profile_name = item.get("profile_name")
        if not profile_name:
            raise OpenAIError(409, "no_profile",
                              "Session này không gắn với profile nào để mở lại.")
        profile = await asyncio.to_thread(profiles.ensure_profile, profile_name,
                                          cfg.profiles_dir)
        if profile is None:
            _need_store()
            raise OpenAIError(404, "not_found", f"Profile '{profile_name}' không tồn tại")
        pool_ = request.app.state.pool
        try:
            page = await pool_.page_for(replace(profile, headless=False),
                                        f"{MANUAL_SLUG}-session-{session_id[:12]}")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except profiles.ProfileLocked as error:
            raise OpenAIError(409, "profile_locked", str(error))
        except Exception as error:
            applog.log(f"session: không mở được {url} trong '{profile_name}': {error}", "error")
            raise OpenAIError(500, "session_open_failed", str(error))
        applog.log(f"session: mở lại {url} trong profile '{profile_name}'")
        return {"ok": True, "profile": profile_name, "url": url}

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

    @admin.post("/recipes")
    async def create_recipe(body: RecipeManualSpec, request: Request):
        """Tạo recipe thủ công (không qua analyzer AI) — người dùng tự khai CSS
        selector, dùng khi site quá lạ hoặc analyzer đoán selector sai."""
        import yaml

        from .providers.browser_recipe import validate_recipe as _validate_recipe

        slug = body.slug.strip().lower()
        if not re.fullmatch(r"[a-z0-9-]+", slug) or slug in {"gemini", "openai"}:
            raise OpenAIError(400, "invalid_slug",
                              "Slug chỉ gồm chữ thường, số và dấu -, không trùng tên hệ thống")
        cfg = request.app.state.cfg
        target = cfg.recipes_dir / slug
        if target.exists():
            raise OpenAIError(409, "slug_taken", f"Slug '{slug}' đã tồn tại")
        recipe = body.to_recipe_dict()
        recipe["slug"] = slug
        errs = _validate_recipe(recipe)
        if errs:
            raise OpenAIError(400, "invalid_recipe", "; ".join(errs))
        async with request.app.state.recipe_publish_lock:
            target.mkdir(parents=True, exist_ok=True)
            (target / "recipe.yaml").write_text(
                yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False), encoding="utf-8")
            request.app.state.router.reload()
        applog.log(f"recipe: tạo thủ công {slug}")
        return {"ok": True, "slug": slug}

    @admin.post("/recipes/test")
    async def test_recipe(body: RecipeTestRequest, request: Request):
        """Chạy thử một prompt cố định qua recipe CHƯA lưu, để người dùng biết
        selector đúng hay sai trước khi bấm tạo (form thủ công không có bước
        round-trip tự sửa như analyzer AI)."""
        from .providers.browser_recipe import validate_recipe as _validate_recipe

        recipe = body.to_recipe_dict()
        errs = _validate_recipe({**recipe, "slug": recipe.get("slug") or "test"})
        if errs:
            raise OpenAIError(400, "invalid_recipe", "; ".join(errs))
        return await run_recipe_trial(request.app.state.cfg, request.app.state.pool,
                                      recipe, body.headed)

    @admin.post("/recipes/discover-models")
    async def discover_recipe_models(body: RecipeModelDiscoveryRequest, request: Request):
        """Chủ động mở trang và dò model controls; không chạy trong tải trang nền."""
        from urllib.parse import urlparse

        from .providers.browser_recipe import discover_models

        parsed = urlparse(body.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise OpenAIError(400, "invalid_url", "URL không hợp lệ")
        key = f"__discover_models__{uuid.uuid4().hex}"
        context = await request.app.state.pool.context_for(key, headed=body.headed)
        page = await context.new_page()
        try:
            await page.goto(body.url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(1200)
            found = await discover_models(page)
            method = "dom"
            before_action = ""
            # Nhiều site chỉ render options sau khi mở nút Model.
            if not found:
                trigger = page.get_by_role("button", name=re.compile(
                    r"model|modèle|mô hình|模型", re.IGNORECASE)).first
                if await trigger.count() and await trigger.is_visible():
                    trigger_selector = await trigger.evaluate(
                        """el => el.id ? '#' + CSS.escape(el.id) : [
                          'aria-label', 'data-testid'
                        ].map(name => el.getAttribute(name) ?
                          `${el.tagName.toLowerCase()}[${name}=${JSON.stringify(el.getAttribute(name))}]`
                          : '').find(Boolean) || 'button'""")
                    await trigger.click()
                    await page.wait_for_timeout(300)
                    before_action = f"click:{trigger_selector}"
                    found = await discover_models(page, before_action)
            # Site dùng tên nút lạ hoặc custom control thường thoát khỏi heuristic.
            # Khi đã cấu hình Agent LLM, nhờ agent đọc DOM và mở picker có kiểm soát.
            if not found and llm.configured(request.app.state.cfg):
                from .agents import model_discovery

                found = await model_discovery.discover(
                    page, request.app.state.cfg, before_action=before_action)
                method = "agent" if found else method
            return {"models": found, "method": method}
        finally:
            await page.close()
            await request.app.state.pool.drop(key)

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

    @admin.patch("/recipes/{slug}")
    async def rename_recipe(slug: str, body: RecipeRenameRequest, request: Request):
        import yaml

        new_slug = (body.slug or "").strip().lower()
        if slug in {"gemini", "openai"}:
            raise OpenAIError(400, "invalid_slug", "Không thể đổi tên recipe hệ thống")
        if not re.fullmatch(r"[a-z0-9-]+", new_slug) or new_slug in {"gemini", "openai"}:
            raise OpenAIError(400, "invalid_slug",
                              "Slug chỉ gồm chữ thường, số và dấu -, không trùng tên hệ thống")
        cfg = request.app.state.cfg
        src = cfg.recipes_dir / slug
        recipe_file = src / "recipe.yaml"
        if not recipe_file.exists():
            raise OpenAIError(404, "not_found", "Recipe không tồn tại")
        if new_slug == slug:
            return {"ok": True, "slug": slug}
        dst = cfg.recipes_dir / new_slug
        if dst.exists():
            raise OpenAIError(409, "slug_taken", f"Slug '{new_slug}' đã tồn tại")
        async with request.app.state.recipe_publish_lock:
            data = yaml.safe_load(recipe_file.read_text(encoding="utf-8")) or {}
            data["slug"] = new_slug
            recipe_file.write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            shutil.move(str(src), str(dst))
            request.app.state.router.reload()
        applog.log(f"recipe: đổi tên {slug} -> {new_slug}")
        return {"ok": True, "slug": new_slug}

    def _recipe_file(request: Request, slug: str):
        """Đường tới recipe.yaml của một slug do người dùng sở hữu.

        Chặn ngay ở đây cả slug bậy (path traversal) lẫn provider hệ thống
        (`gemini`, `openai`) — chúng không chạy bằng recipe.yaml nên không có
        gì để sửa ở màn này.
        """
        if not re.fullmatch(r"[a-z0-9-]+", slug or "") or slug in {"gemini", "openai"}:
            raise OpenAIError(400, "invalid_slug", "Recipe này không sửa được")
        path = request.app.state.cfg.recipes_dir / slug / "recipe.yaml"
        if not path.exists():
            raise OpenAIError(404, "not_found", "Recipe không tồn tại")
        return path

    def _edited_recipe(request: Request, slug: str, body) -> dict:
        """Recipe sau khi áp bản sửa — chưa ghi đĩa, đã qua validate.

        Hai đường vào (`yaml` toàn văn / `patch` từ biểu mẫu) hội tụ ở đây để
        nút "Kiểm tra" và nút "Lưu" luôn nhìn thấy đúng cùng một recipe.
        """
        import yaml as yaml_mod

        from .providers.browser_recipe import validate_recipe as _validate_recipe

        recipe_file = _recipe_file(request, slug)
        if body.yaml is not None:
            try:
                data = yaml_mod.safe_load(body.yaml)
            except yaml_mod.YAMLError as error:
                raise OpenAIError(400, "invalid_yaml", f"YAML sai cú pháp: {error}") from None
            if not isinstance(data, dict):
                raise OpenAIError(400, "invalid_yaml", "YAML phải là một mapping")
        elif body.patch is not None:
            base = yaml_mod.safe_load(recipe_file.read_text(encoding="utf-8")) or {}
            data = merge_recipe(base if isinstance(base, dict) else {}, body.patch)
        else:
            raise OpenAIError(400, "empty_edit", "Không có gì để sửa")
        # Slug gắn với TÊN THƯ MỤC; đổi nó phải đi qua đường rename (có move
        # thư mục), nếu không recipe sẽ nạp lại dưới slug cũ và người dùng
        # tưởng mình vừa đổi tên thành công.
        edited_slug = data.get("slug")
        if edited_slug is not None and str(edited_slug) != slug:
            raise OpenAIError(400, "slug_mismatch",
                              "Đổi slug phải dùng nút Đổi tên, không sửa trong YAML")
        data["slug"] = slug
        errs = _validate_recipe(data)
        if errs:
            raise OpenAIError(400, "invalid_recipe", "; ".join(errs))
        return data

    @admin.get("/recipes/{slug}/source")
    async def recipe_source(slug: str, request: Request):
        """recipe.yaml nguyên văn + bản đã parse, cho màn sửa nâng cao."""
        import yaml as yaml_mod

        recipe_file = _recipe_file(request, slug)
        text = recipe_file.read_text(encoding="utf-8")
        try:
            data = yaml_mod.safe_load(text) or {}
        except yaml_mod.YAMLError as error:
            # File hỏng vẫn phải mở được ở tab YAML — đó chính là lúc cần sửa.
            return {"slug": slug, "yaml": text, "data": None, "parse_error": str(error)}
        if not isinstance(data, dict):
            return {"slug": slug, "yaml": text, "data": None,
                    "parse_error": "YAML phải là một mapping"}
        data.setdefault("slug", slug)
        return {"slug": slug, "yaml": text, "data": data, "parse_error": None}

    @admin.put("/recipes/{slug}")
    async def update_recipe(slug: str, body: RecipeEditRequest, request: Request):
        """Ghi đè recipe.yaml rồi nạp lại router ngay."""
        import yaml as yaml_mod

        # Đọc–ghép–ghi nằm trọn trong lock: một lượt đổi tên chen vào giữa sẽ
        # dời thư mục recipe, và bản ghi sẽ rơi vào đường dẫn không còn tồn tại.
        async with request.app.state.recipe_publish_lock:
            data = _edited_recipe(request, slug, body)
            _recipe_file(request, slug).write_text(
                yaml_mod.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            request.app.state.router.reload()
        mode = "yaml" if body.yaml is not None else "biểu mẫu"
        applog.log(f"recipe: sửa {slug} ({mode})")
        return {"ok": True, "slug": slug}

    @admin.post("/recipes/{slug}/preview")
    async def preview_recipe_edit(slug: str, body: RecipeEditRequest, request: Request):
        """Bản sửa sau khi áp, KHÔNG ghi đĩa — trả về cả YAML lẫn dict.

        Màn sửa dùng nó để đổi qua lại giữa tab biểu mẫu và tab YAML mà hai bên
        luôn nói cùng một recipe: đây là chỗ duy nhất biết dịch giữa hai dạng
        (client không có bộ parse YAML).
        """
        import yaml as yaml_mod

        data = _edited_recipe(request, slug, body)
        text = yaml_mod.safe_dump(data, allow_unicode=True, sort_keys=False)
        return {"slug": slug, "yaml": text, "data": data}

    @admin.post("/recipes/{slug}/test")
    async def test_recipe_edit(slug: str, body: RecipeEditTestRequest, request: Request):
        """Chạy thử bản đang sửa mà chưa ghi đè recipe đang chạy."""
        data = _edited_recipe(request, slug, body)
        return await run_recipe_trial(request.app.state.cfg, request.app.state.pool,
                                      data, body.headed)

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

        # Snapshot nhỏ cho dashboard: mỗi hàng là đường đi đã được chốt của một
        # request, từ model/recipe tới account/profile/domain. Polling endpoint này
        # không đụng vào provider và không thay đổi quyết định phân phối.
        def recent_routes() -> tuple[list[dict], int, list[dict]]:
            db = store.default()
            if db is None:
                return [], 0, []
            now = store.now_ms()
            rows = db.query(
                "SELECT q.id, q.session_id, q.model_public_id, q.status, q.started_at, "
                "q.ttfb_ms, q.duration_ms, q.stream, q.fallback_used, q.error_code, "
                "r.slug AS recipe_slug, a.label AS account_label, d.host AS domain, "
                "p.name AS profile_name "
                "FROM request_log q "
                "LEFT JOIN recipe r ON r.id = q.recipe_id "
                "LEFT JOIN account a ON a.id = q.account_id "
                "LEFT JOIN domain d ON d.id = a.domain_id "
                "LEFT JOIN profile p ON p.id = q.profile_id "
                "ORDER BY (q.status = 'running') DESC, q.started_at DESC LIMIT 20")
            last_minute = db.query(
                "SELECT COUNT(*) AS n FROM request_log WHERE started_at >= ?", (now - 60000,))
            # Diagram dùng cùng nguồn với trang Sessions: 100 session chưa archive
            # mới nhất, mỗi session được tính đúng một lần bất kể có bao nhiêu lượt
            # chat/request bên trong. Subquery LIMIT trước GROUP BY để tập dữ liệu
            # trên Overview khớp danh sách mặc định của /admin/sessions.
            distribution = db.query(
                "SELECT recipe_slug, profile_name, account_label, domain, "
                "COUNT(*) AS sessions, SUM(active) AS active, SUM(has_error) AS errors "
                "FROM ("
                "SELECT s.id, COALESCE(r.slug, 'direct') AS recipe_slug, "
                "COALESCE(p.name, '') AS profile_name, COALESCE(a.label, '') AS account_label, "
                "COALESCE(d.host, '') AS domain, "
                "CASE WHEN EXISTS (SELECT 1 FROM request_log q "
                "  WHERE q.session_id = s.id AND q.status = 'running') THEN 1 ELSE 0 END AS active, "
                "CASE WHEN s.error_count > 0 THEN 1 ELSE 0 END AS has_error "
                "FROM session s "
                "LEFT JOIN recipe r ON r.id = s.recipe_id "
                "LEFT JOIN account a ON a.id = s.account_id "
                "LEFT JOIN domain d ON d.id = a.domain_id "
                "LEFT JOIN profile p ON p.id = s.profile_id "
                "WHERE s.archived = 0 ORDER BY s.updated_at DESC LIMIT 100"
                ") recent_sessions "
                "GROUP BY recipe_slug, profile_name, account_label, domain "
                "ORDER BY sessions DESC, recipe_slug LIMIT 8")
            return ([dict(row) for row in rows],
                    int(last_minute[0]["n"] if last_minute else 0),
                    [dict(row) for row in distribution])

        routes, requests_last_minute, session_distribution = await asyncio.to_thread(recent_routes)
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
            "request_routes": routes,
            "requests_last_minute": requests_last_minute,
            "session_distribution": session_distribution,
            "routes_persisted": store.default() is not None,
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
