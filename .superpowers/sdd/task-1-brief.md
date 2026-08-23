### Task 1: Scaffold + config + errors + auth

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `chat2api/__init__.py`, `chat2api/config.py`, `chat2api/errors.py`, `chat2api/auth.py`
- Test: `tests/unit/test_config_auth.py`

**Interfaces:**
- Produces: `Config` vá»›i attrs `api_keys: list[str]`, `recipes_dir: Path`, `agent_llm_base_url: str`, `agent_llm_api_key: str`, `agent_llm_model: str`, `enable_fallback: bool`, `pool_max_contexts: int`, `pool_acquire_timeout: int`, `browser_engine: str`, `recipe_timeout_ms: int`, `integrate_max_rounds: int`; `OpenAIError(status, code, message, typ)`; `register_error_handler(app)`; `require_key(request)` (Ä‘á»c `request.app.state.cfg.api_keys`, bá» qua `/` vÃ  `/health`).

- [ ] **Step 1: Táº¡o package files**

`pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "chat2api"
version = "0.1.0"
description = "Turn any web chat into an OpenAI-compatible API"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.110",
  "uvicorn>=0.29",
  "httpx>=0.27",
  "playwright>=1.44",
  "PyYAML>=6",
  "pydantic>=2.7",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23"]
cloak = ["cloakbrowser"]

[tool.setuptools.packages.find]
include = ["chat2api*"]

[tool.setuptools.package-data]
chat2api = ["playground/*.html"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

`.gitignore`:

```
__pycache__/
*.egg-info/
.venv/
.pytest_cache/
**/auth/
**/secrets/
```

`chat2api/__init__.py`:

```python
__version__ = "0.1.0"
```

`chat2api/config.py`:

```python
import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


class Config:
    def __init__(self) -> None:
        self.api_keys = [k.strip() for k in _env("CHAT2API_KEYS").split(",") if k.strip()]
        self.recipes_dir = Path(_env("RECIPES_DIR", "./recipes"))
        self.agent_llm_base_url = _env("AGENT_LLM_BASE_URL").rstrip("/")
        self.agent_llm_api_key = _env("AGENT_LLM_API_KEY")
        self.agent_llm_model = _env("AGENT_LLM_MODEL")
        self.enable_fallback = _env("ENABLE_AGENT_FALLBACK", "false").lower() == "true"
        self.pool_max_contexts = int(_env("POOL_MAX_CONTEXTS", "3"))
        self.pool_acquire_timeout = int(_env("POOL_ACQUIRE_TIMEOUT", "30"))
        self.browser_engine = _env("BROWSER_ENGINE", "playwright")
        self.recipe_timeout_ms = int(_env("RECIPE_TIMEOUT_MS", "120000"))
        self.integrate_max_rounds = int(_env("INTEGRATE_MAX_ROUNDS", "5"))
```

`chat2api/errors.py`:

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class OpenAIError(Exception):
    def __init__(self, status: int, code: str, message: str, typ: str = "invalid_request_error"):
        self.status = status
        self.code = code
        self.message = message
        self.typ = typ


def register_error_handler(app: FastAPI) -> None:
    @app.exception_handler(OpenAIError)
    async def _handler(request: Request, exc: OpenAIError):
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"message": exc.message, "type": exc.typ, "code": exc.code}},
        )
```

`chat2api/auth.py`:

```python
from fastapi import Request

from .errors import OpenAIError

PUBLIC_PATHS = {"/", "/health"}


async def require_key(request: Request) -> None:
    cfg = request.app.state.cfg
    if not cfg.api_keys or request.url.path in PUBLIC_PATHS:
        return
    header = request.headers.get("authorization", "")
    if header.startswith("Bearer ") and header[7:] in cfg.api_keys:
        return
    raise OpenAIError(401, "invalid_api_key", "Incorrect API key provided.", "authentication_error")
```

- [ ] **Step 2: Viáº¿t test**

`tests/unit/test_config_auth.py`:

```python
import asyncio

from fastapi import FastAPI

from chat2api.auth import require_key
from chat2api.config import Config
from chat2api.errors import OpenAIError


def test_config_defaults(monkeypatch):
    for k in ("CHAT2API_KEYS", "RECIPES_DIR", "AGENT_LLM_BASE_URL", "ENABLE_AGENT_FALLBACK"):
        monkeypatch.delenv(k, raising=False)
    cfg = Config()
    assert cfg.api_keys == []
    assert cfg.browser_engine == "playwright"
    assert cfg.recipe_timeout_ms == 120000
    assert cfg.enable_fallback is False


def test_config_parse(monkeypatch):
    monkeypatch.setenv("CHAT2API_KEYS", " a , b,, ")
    monkeypatch.setenv("ENABLE_AGENT_FALLBACK", "TRUE")
    cfg = Config()
    assert cfg.api_keys == ["a", "b"]
    assert cfg.enable_fallback is True


def make_request(path: str, api_keys: list[str]):
    cfg = Config()
    cfg.api_keys = api_keys
    state = type("S", (), {"cfg": cfg})()
    app = type("A", (), {"state": state})()

    class R:
        pass

    r = R()
    r.app = app
    r.url = type("U", (), {"path": path})()
    r.headers = {}
    return r


def test_auth_allows_when_no_keys():
    asyncio.run(require_key(make_request("/v1/models", [])))


def test_auth_public_path():
    asyncio.run(require_key(make_request("/health", ["k1"])))


def test_auth_valid_and_invalid_key():
    r = make_request("/v1/models", ["k1"])
    r.headers = {"authorization": "Bearer k1"}
    asyncio.run(require_key(r))
    try:
        asyncio.run(require_key(make_request("/v1/models", ["k1"])))
        assert False
    except OpenAIError as e:
        assert e.status == 401 and e.code == "invalid_api_key"
```

- [ ] **Step 3: CÃ i Ä‘áº·t vÃ  cháº¡y test**

Run: `pip install -e ".[dev]" ; python -m pytest tests/unit/test_config_auth.py -v`
Expected: 5 passed

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml .gitignore chat2api tests
git commit -m "feat: scaffold package, config, openai error shape, bearer auth"
```

---


