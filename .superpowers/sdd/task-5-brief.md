### Task 5: OpenAI passthrough provider

**Files:**
- Create: `chat2api/providers/openai_passthrough.py`, `recipes/openai/qwen.yaml`
- Modify: `chat2api/router.py`
- Test: `tests/unit/test_passthrough.py`

**Interfaces:**
- Consumes: `Provider`, `ModelInfo`.
- Produces: `OpenAIPassthrough(cfg: dict)` â€” cfg: `slug`, `base_url`, `api_key_env|api_key`, `models: list[str]`, `stream: bool`. Loader `_passthrough_loader(directory, pool)` tráº£ **list** provider (má»™t file yaml má»™t provider).

- [ ] **Step 1: Viáº¿t test tháº¥t báº¡i**

`tests/unit/test_passthrough.py`:

```python
import httpx

from chat2api.providers.openai_passthrough import OpenAIPassthrough


async def test_stream_forward(monkeypatch):
    cfg = {"slug": "up", "base_url": "https://up.example/v1", "models": ["m1"], "stream": True}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        lines = [
            'data: {"choices":[{"delta":{"content":"He"}}]}',
            'data: {"choices":[{"delta":{"content":"y"}}]}',
            "data: [DONE]",
        ]
        return httpx.Response(200, content="\n\n".join(lines).encode(),
                              headers={"content-type": "text/event-stream"})

    real_init = httpx.AsyncClient.__init__

    def patched(self, *a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        real_init(self, *a, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)
    p = OpenAIPassthrough(cfg)
    out = [c async for c in p.stream([], "m1")]
    assert "".join(out) == "Hey"


def test_models_ready_flag(monkeypatch):
    monkeypatch.delenv("MY_UP_KEY", raising=False)
    p = OpenAIPassthrough({"slug": "up", "base_url": "https://x/v1",
                           "models": ["m1"], "api_key_env": "MY_UP_KEY"})
    assert p.models()[0].ready is False
    monkeypatch.setenv("MY_UP_KEY", "secret")
    assert p.models()[0].ready is True
```

- [ ] **Step 2: Cháº¡y xÃ¡c nháº­n fail**

Run: `python -m pytest tests/unit/test_passthrough.py -v`
Expected: FAIL ModuleNotFoundError

- [ ] **Step 3: Implement**

`chat2api/providers/openai_passthrough.py`:

```python
import json
import os
from typing import AsyncIterator

import httpx

from .base import ModelInfo, Provider


class OpenAIPassthrough(Provider):
    def __init__(self, cfg: dict):
        self.slug = cfg["slug"]
        self.base_url = cfg["base_url"].rstrip("/")
        self.api_key = cfg.get("api_key") or os.environ.get(cfg.get("api_key_env", ""), "")
        self.supports_stream = bool(cfg.get("stream", True))
        self._ids = cfg["models"]

    def models(self) -> list[ModelInfo]:
        return [ModelInfo(id=f"{self.slug}/{i}", slug=self.slug, ready=bool(self.api_key)) for i in self._ids]

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def stream(self, messages: list[dict], model_id: str) -> AsyncIterator[str]:
        payload = {"model": model_id, "messages": messages, "stream": self.supports_stream}
        async with httpx.AsyncClient(timeout=300) as client:
            if not self.supports_stream:
                r = await client.post(f"{self.base_url}/chat/completions",
                                      json=payload, headers=self._headers())
                r.raise_for_status()
                yield r.json()["choices"][0]["message"]["content"]
                return
            async with client.stream("POST", f"{self.base_url}/chat/completions",
                                     json=payload, headers=self._headers()) as resp:
                resp.raise_for_status()
                buf = ""
                async for chunk in resp.aiter_text():
                    buf += chunk
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if not line.startswith("data:") or line == "data: [DONE]":
                            continue
                        try:
                            delta = json.loads(line[5:])["choices"][0]["delta"].get("content")
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
                        if delta:
                            yield delta
```

ThÃªm cuá»‘i `chat2api/router.py`:

```python
def _passthrough_loader(directory: Path, pool):
    if directory.name != "openai":
        return None
    import yaml

    from .providers.openai_passthrough import OpenAIPassthrough

    out = []
    for yml in sorted(directory.glob("*.yaml")):
        cfg = yaml.safe_load(yml.read_text(encoding="utf-8"))
        if cfg:
            out.append(OpenAIPassthrough(cfg))
    return out or None


LOADERS.append(_passthrough_loader)
```

`recipes/openai/qwen.yaml`:

```yaml
slug: qwen
# Upstream chuáº©n OpenAI /v1 (dá»‹ch vá»¥ host cá»§a dá»± Ã¡n qwen-api).
# Láº¥y key theo README qwen-api rá»“i Ä‘áº·t vÃ o env QWEN_API_KEY.
base_url: https://qwen.aikit.club/v1
api_key_env: QWEN_API_KEY
stream: true
models: [qwen-max, qwen-plus]
```

- [ ] **Step 4: Cháº¡y xÃ¡c nháº­n pass**

Run: `python -m pytest tests/unit/test_passthrough.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add chat2api/providers/openai_passthrough.py chat2api/router.py recipes/openai tests/unit/test_passthrough.py
git commit -m "feat: openai-compatible passthrough provider"
```

---


