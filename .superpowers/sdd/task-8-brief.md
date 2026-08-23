### Task 8: FastAPI app â€” /v1 endpoints + health + playground mount

**Files:**
- Create: `chat2api/main.py`
- Modify: `tests/integration/conftest.py` (thÃªm fixture app client)
- Test: `tests/integration/test_chat_endpoints.py`

**Interfaces:**
- Consumes: Router/Provider (T3), GeminiNative (T4), passthrough (T5), pool (T6), BrowserRecipe (T7), auth/errors/schemas (T1-2). Import `chat2api.router` Ä‘á»ƒ trigger Ä‘Äƒng kÃ½ LOADERS.
- Produces: `create_app(cfg) -> FastAPI`; module-level `app = create_app(Config())`. State: `app.state.cfg/pool/router` â€” cfg/router/pool gÃ¡n Ä‘á»“ng bá»™ trong `create_app`, lifespan chá»‰ start/stop pool.

- [ ] **Step 1: Implement**

`chat2api/main.py`:

```python
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
```

- [ ] **Step 2: ThÃªm fixture app client vÃ o conftest**

ThÃªm cuá»‘i `tests/integration/conftest.py`:

```python
@pytest.fixture
async def app_client(tmp_path, site):
    from httpx import ASGITransport, AsyncClient

    from chat2api.config import Config
    from chat2api.main import create_app
    from chat2api.providers.base import ModelInfo, Provider

    class FakeProvider(Provider):
        slug = "fake"

        def models(self):
            return [ModelInfo(id="fake/m1", slug="fake")]

        async def stream(self, messages, model_id):
            for word in ("Hello ", "world"):
                yield word

    cfg = Config()
    cfg.recipes_dir = tmp_path / "recipes"
    cfg.recipes_dir.mkdir()
    app = create_app(cfg)
    app.state.router.providers["fake"] = FakeProvider()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        yield client
```

- [ ] **Step 3: Viáº¿t test endpoints**

`tests/integration/test_chat_endpoints.py`:

```python
import json


async def test_health(app_client):
    r = await app_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and "models" in body


async def test_models_list(app_client):
    r = await app_client.get("/v1/models")
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()["data"]]
    assert "fake/m1" in ids


async def test_completion_non_stream(app_client):
    r = await app_client.post("/v1/chat/completions", json={
        "model": "fake/m1", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    body = r.json()
    assert body["choices"][0]["message"]["content"] == "Hello world"
    assert body["usage"]["total_tokens"] == 0


async def test_completion_stream_sse(app_client):
    r = await app_client.post("/v1/chat/completions", json={
        "model": "fake/m1", "messages": [{"role": "user", "content": "hi"}], "stream": True})
    assert r.status_code == 200
    text = r.text
    assert 'data: {"id"' in text.replace(" ", "") or '"chat.completion.chunk"' in text
    assert "data: [DONE]" in text
    chunks = [json.loads(l[6:]) for l in text.splitlines() if l.startswith("data: {")]
    assert "".join(c["choices"][0]["delta"]["content"] for c in chunks) == "Hello world"


async def test_unknown_model_404(app_client):
    r = await app_client.post("/v1/chat/completions", json={
        "model": "nope/x", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "model_not_found"


async def test_auth_enforced_when_keys_set(app_client):
    app = app_client._transport.app
    app.state.cfg.api_keys = ["secret"]
    try:
        r = await app_client.get("/v1/models")
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_api_key"
        r2 = await app_client.get("/v1/models", headers={"Authorization": "Bearer secret"})
        assert r2.status_code == 200
    finally:
        app.state.cfg.api_keys = []
```

- [ ] **Step 4: Táº¡o playground táº¡m (Ä‘á»§ Ä‘á»ƒ route `/` compile)**

`chat2api/playground/index.html` â€” táº¡m placeholder, thay tháº­t á»Ÿ Task 9:

```html
<!doctype html><html><body><h1>chat2api playground (sáº¯p cÃ³)</h1></body></html>
```

- [ ] **Step 5: Cháº¡y**

Run: `python -m pytest tests/integration/test_chat_endpoints.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add chat2api/main.py tests
git commit -m "feat: FastAPI app with OpenAI-compatible v1 endpoints + SSE"
```

---


