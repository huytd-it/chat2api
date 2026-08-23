## Commits
e662deb feat: openai-compatible passthrough provider

## Stat
 chat2api/providers/openai_passthrough.py | 56 ++++++++++++++++++++++++++++++++
 chat2api/router.py                       | 18 ++++++++++
 recipes/openai/qwen.yaml                 |  7 ++++
 tests/unit/test_passthrough.py           | 37 +++++++++++++++++++++
 4 files changed, 118 insertions(+)

## Diffdiff --git a/chat2api/providers/openai_passthrough.py b/chat2api/providers/openai_passthrough.py
new file mode 100644
index 0000000..aad5e6b
--- /dev/null
+++ b/chat2api/providers/openai_passthrough.py
@@ -0,0 +1,56 @@
+import json
+import os
+from typing import AsyncIterator
+
+import httpx
+
+from .base import ModelInfo, Provider
+
+
+class OpenAIPassthrough(Provider):
+    def __init__(self, cfg: dict):
+        self.slug = cfg["slug"]
+        self.base_url = cfg["base_url"].rstrip("/")
+        self._cfg_key = cfg.get("api_key")
+        self.api_key_env = cfg.get("api_key_env", "")
+        self.supports_stream = bool(cfg.get("stream", True))
+        self._ids = cfg["models"]
+
+    def _api_key(self) -> str:
+        return self._cfg_key or os.environ.get(self.api_key_env, "")
+
+    def models(self) -> list[ModelInfo]:
+        return [ModelInfo(id=f"{self.slug}/{i}", slug=self.slug, ready=bool(self._api_key())) for i in self._ids]
+
+    def _headers(self) -> dict:
+        h = {"Content-Type": "application/json"}
+        if self._api_key():
+            h["Authorization"] = f"Bearer {self._api_key()}"
+        return h
+
+    async def stream(self, messages: list[dict], model_id: str) -> AsyncIterator[str]:
+        payload = {"model": model_id, "messages": messages, "stream": self.supports_stream}
+        async with httpx.AsyncClient(timeout=300) as client:
+            if not self.supports_stream:
+                r = await client.post(f"{self.base_url}/chat/completions",
+                                      json=payload, headers=self._headers())
+                r.raise_for_status()
+                yield r.json()["choices"][0]["message"]["content"]
+                return
+            async with client.stream("POST", f"{self.base_url}/chat/completions",
+                                     json=payload, headers=self._headers()) as resp:
+                resp.raise_for_status()
+                buf = ""
+                async for chunk in resp.aiter_text():
+                    buf += chunk
+                    while "\n" in buf:
+                        line, buf = buf.split("\n", 1)
+                        line = line.strip()
+                        if not line.startswith("data:") or line == "data: [DONE]":
+                            continue
+                        try:
+                            delta = json.loads(line[5:])["choices"][0]["delta"].get("content")
+                        except (json.JSONDecodeError, KeyError, IndexError):
+                            continue
+                        if delta:
+                            yield delta
diff --git a/chat2api/router.py b/chat2api/router.py
index 81ff6e5..103b4cc 100644
--- a/chat2api/router.py
+++ b/chat2api/router.py
@@ -64,10 +64,28 @@ def _gemini_loader(directory: Path, pool):
         return None
     import yaml
 
     from .providers.gemini_native import GeminiNative
 
     cfg = yaml.safe_load((directory / "config.yaml").read_text(encoding="utf-8"))
     return GeminiNative(cfg, directory)
 
 
 LOADERS.append(_gemini_loader)
+
+
+def _passthrough_loader(directory: Path, pool):
+    if directory.name != "openai":
+        return None
+    import yaml
+
+    from .providers.openai_passthrough import OpenAIPassthrough
+
+    out = []
+    for yml in sorted(directory.glob("*.yaml")):
+        cfg = yaml.safe_load(yml.read_text(encoding="utf-8"))
+        if cfg:
+            out.append(OpenAIPassthrough(cfg))
+    return out or None
+
+
+LOADERS.append(_passthrough_loader)
diff --git a/recipes/openai/qwen.yaml b/recipes/openai/qwen.yaml
new file mode 100644
index 0000000..19b2cab
--- /dev/null
+++ b/recipes/openai/qwen.yaml
@@ -0,0 +1,7 @@
+slug: qwen
+# Upstream chuß║⌐n OpenAI /v1 (dß╗ïch vß╗Ñ host cß╗ºa dß╗▒ ├ín qwen-api).
+# Lß║Ñy key theo README qwen-api rß╗ôi ─æß║╖t v├áo env QWEN_API_KEY.
+base_url: https://qwen.aikit.club/v1
+api_key_env: QWEN_API_KEY
+stream: true
+models: [qwen-max, qwen-plus]
diff --git a/tests/unit/test_passthrough.py b/tests/unit/test_passthrough.py
new file mode 100644
index 0000000..851d17a
--- /dev/null
+++ b/tests/unit/test_passthrough.py
@@ -0,0 +1,37 @@
+import httpx
+
+from chat2api.providers.openai_passthrough import OpenAIPassthrough
+
+
+async def test_stream_forward(monkeypatch):
+    cfg = {"slug": "up", "base_url": "https://up.example/v1", "models": ["m1"], "stream": True}
+
+    def handler(request: httpx.Request) -> httpx.Response:
+        assert request.url.path == "/v1/chat/completions"
+        lines = [
+            'data: {"choices":[{"delta":{"content":"He"}}]}',
+            'data: {"choices":[{"delta":{"content":"y"}}]}',
+            "data: [DONE]",
+        ]
+        return httpx.Response(200, content="\n\n".join(lines).encode(),
+                              headers={"content-type": "text/event-stream"})
+
+    real_init = httpx.AsyncClient.__init__
+
+    def patched(self, *a, **kw):
+        kw["transport"] = httpx.MockTransport(handler)
+        real_init(self, *a, **kw)
+
+    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)
+    p = OpenAIPassthrough(cfg)
+    out = [c async for c in p.stream([], "m1")]
+    assert "".join(out) == "Hey"
+
+
+def test_models_ready_flag(monkeypatch):
+    monkeypatch.delenv("MY_UP_KEY", raising=False)
+    p = OpenAIPassthrough({"slug": "up", "base_url": "https://x/v1",
+                           "models": ["m1"], "api_key_env": "MY_UP_KEY"})
+    assert p.models()[0].ready is False
+    monkeypatch.setenv("MY_UP_KEY", "secret")
+    assert p.models()[0].ready is True

