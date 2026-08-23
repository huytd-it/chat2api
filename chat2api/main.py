import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from . import auth, errors  # noqa: F401  (import auth Ä‘á»ƒ Ä‘Äƒng kÃ½ dependency)
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

    pool = BrowserPool(cfg.browser_engine, cfg.pool_max_contexts)
    router = Router(cfg.recipes_dir, pool)
    router.reload()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await pool.start()
        yield
        await pool.aclose()

    app = FastAPI(title="chat2api", lifespan=lifespan)
    errors.register_error_handler(app)
    app.state.cfg = cfg
    app.state.pool = pool
    app.state.router = router

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

            log = [f"[fallback:{provider.slug}] recipe lá»—i, agent cháº¡y trá»±c tiáº¿p"]
            async for d in fallback.run(provider.url, msgs, request.app.state.pool, cfg_, log):
                yield d

        async def upstream():
            if rt.is_unhealthy(provider.slug) and fallback_ok("unhealthy recipe"):
                async for d in agent_stream():
                    yield d
                return
            try:
                async for d in provider.stream(msgs, local):
                    yield d
                rt.mark_success(provider.slug)
            except TimeoutError:
                rt.mark_failure(provider.slug)
                if fallback_ok("timeout"):
                    async for d in agent_stream():
                        yield d
                    rt.mark_success(provider.slug)
                    return
                raise OpenAIError(504, "recipe_timeout",
                                  f"KhÃ´ng nháº­n Ä‘Æ°á»£c reply trong thá»i háº¡n ({cfg_.recipe_timeout_ms}ms)",
                                  "api_error")
            except OpenAIError:
                raise
            except Exception as e:
                rt.mark_failure(provider.slug)
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
    """Äiá»n á»Ÿ Task 12 (analyzer/jobs/recipes). Táº¡o sáºµn Ä‘á»ƒ Task 8 compile."""
    pass


app = create_app(Config())