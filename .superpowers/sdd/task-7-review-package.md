## Commits
c6fb636 feat: chat recipe schema, validator, browser recipe runner

## Stat
 chat2api/providers/browser_recipe.py    | 108 ++++++++++++++++++++++++++++++++
 chat2api/router.py                      |  23 +++++++
 tests/integration/conftest.py           |  33 ++++++++++
 tests/integration/fixtures/chat.html    |  22 +++++++
 tests/integration/test_recipe_runner.py |  34 ++++++++++
 tests/unit/test_recipe_validate.py      |  25 ++++++++
 6 files changed, 245 insertions(+)

## Diffdiff --git a/chat2api/providers/browser_recipe.py b/chat2api/providers/browser_recipe.py
new file mode 100644
index 0000000..4eba1af
--- /dev/null
+++ b/chat2api/providers/browser_recipe.py
@@ -0,0 +1,108 @@
+import asyncio
+import sys
+import time
+from pathlib import Path
+from typing import AsyncIterator
+
+from ..prompt import flatten_messages
+from .base import ModelInfo, Provider
+
+
+def validate_recipe(d: dict) -> list[str]:
+    errs: list[str] = []
+
+    def need(name: str, ok: bool):
+        if not ok:
+            errs.append(f"missing/invalid field: {name}")
+
+    need("slug", bool(d.get("slug")))
+    need("url", bool(d.get("url")))
+    need("prompt.input_selector", bool((d.get("prompt") or {}).get("input_selector")))
+    resp = d.get("response") or {}
+    ds = resp.get("done_signal") or {}
+    need("response.last_message_selector", bool(resp.get("last_message_selector")))
+    need("response.done_signal.type",
+         ds.get("type") in {"stable_text", "selector_appear", "selector_disappear"})
+    if ds.get("type") in {"selector_appear", "selector_disappear"}:
+        need("response.done_signal.selector", bool(ds.get("selector")))
+    models = d.get("models")
+    need("models", isinstance(models, list) and len(models) > 0 and all(m.get("id") for m in models))
+    return errs
+
+
+class BrowserRecipe(Provider):
+    def __init__(self, recipe: dict, base_dir: Path, pool):
+        self._recipe = recipe
+        self.slug = recipe["slug"]
+        self.base_dir = base_dir
+        self.pool = pool
+        self.prompt_cfg = recipe.get("prompt", {})
+        self.response_cfg = recipe.get("response", {})
+        self.ds = self.response_cfg.get("done_signal", {})
+
+    @property
+    def url(self) -> str:
+        return self._recipe["url"]
+
+    def models(self) -> list[ModelInfo]:
+        return [ModelInfo(id=f"{self.slug}/{m['id']}", slug=self.slug) for m in self._recipe["models"]]
+
+    def _storage_state(self) -> Path | None:
+        st = (self._recipe.get("login") or {}).get("storage_state")
+        return self.base_dir / st if st else None
+
+    async def _reply_text(self, page) -> str:
+        sel = self.response_cfg["last_message_selector"]
+        return await page.evaluate(
+            """(sel) => { const els = document.querySelectorAll(sel);
+                 return els.length ? els[els.length - 1].innerText : ""; }""",
+            sel,
+        )
+
+    async def stream(self, messages: list[dict], model_id: str) -> AsyncIterator[str]:
+        prompt = flatten_messages(messages)
+        ctx = await self.pool.context_for(self.slug, self._storage_state())
+        page = await ctx.new_page()
+        timeout_ms = int(self.ds.get("timeout_ms", 120000))
+        deadline = time.monotonic() + timeout_ms / 1000
+        quiet_ms = int(self.ds.get("quiet_ms", 3000))
+        try:
+            await page.goto(self.url, wait_until="domcontentloaded", timeout=min(timeout_ms, 60000))
+            box = page.locator(self.prompt_cfg["input_selector"]).first
+            if self.prompt_cfg.get("input_mode", "fill") == "type":
+                await box.click()
+                await box.type(prompt)
+            else:
+                await box.fill(prompt)
+            submit = self.prompt_cfg.get("submit", "Enter")
+            if submit.startswith("click:"):
+                await page.click(submit.split(":", 1)[1])
+            else:
+                await box.press("Enter")
+
+            dtype = self.ds.get("type", "stable_text")
+            stable_since = None
+            last = ""
+            while True:
+                if time.monotonic() > deadline:
+                    raise TimeoutError(f"recipe '{self.slug}' timeout sau {timeout_ms}ms")
+                text = await self._reply_text(page)
+                if text != last:
+                    if text.startswith(last):
+                        yield text[len(last):]
+                    last = text
+                    stable_since = time.monotonic()
+                if dtype == "stable_text":
+                    done = (bool(last.strip()) and last.strip() != prompt.strip()
+                            and stable_since is not None
+                            and (time.monotonic() - stable_since) * 1000 >= quiet_ms)
+                else:
+                    count = await page.locator(self.ds["selector"]).count()
+                    appear = dtype == "selector_appear"
+                    done = ((count > 0) == appear) and stable_since is not None \
+                        and (time.monotonic() - stable_since) * 1000 >= min(quiet_ms, 1000)
+                if done:
+                    return
+                await asyncio.sleep(0.5)
+        finally:
+            await page.close()
diff --git a/chat2api/router.py b/chat2api/router.py
index 103b4cc..4b55f33 100644
--- a/chat2api/router.py
+++ b/chat2api/router.py
@@ -1,10 +1,11 @@
+import sys
 from pathlib import Path
 
 from .providers.base import ModelInfo, Provider
 
 UNHEALTHY_THRESHOLD = 3
 
 # Loader: (directory: Path, pool) -> Provider | list[Provider] | None
 LOADERS: list = []
 
 
@@ -82,10 +83,32 @@ def _passthrough_loader(directory: Path, pool):
 
     out = []
     for yml in sorted(directory.glob("*.yaml")):
         cfg = yaml.safe_load(yml.read_text(encoding="utf-8"))
         if cfg:
             out.append(OpenAIPassthrough(cfg))
     return out or None
 
 
 LOADERS.append(_passthrough_loader)
+
+
+def _recipe_loader(directory: Path, pool):
+    if directory.name in {"gemini", "openai"}:
+        return None
+    yml = directory / "recipe.yaml"
+    if not yml.exists():
+        return None
+    import yaml
+
+    from .providers.browser_recipe import BrowserRecipe, validate_recipe
+
+    recipe = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
+    recipe.setdefault("slug", directory.name)
+    errs = validate_recipe(recipe)
+    if errs:
+        print(f"[chat2api] invalid recipe {directory.name}: {errs}", file=sys.stderr)
+        return None
+    return BrowserRecipe(recipe, directory, pool)
+
+
+LOADERS.append(_recipe_loader)
diff --git a/tests/integration/conftest.py b/tests/integration/conftest.py
new file mode 100644
index 0000000..5b7f05c
--- /dev/null
+++ b/tests/integration/conftest.py
@@ -0,0 +1,33 @@
+import http.server
+import socketserver
+import threading
+from functools import partial
+from pathlib import Path
+
+import pytest
+
+FIXTURES = Path(__file__).parent / "fixtures"
+
+
+@pytest.fixture
+def site():
+    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(FIXTURES))
+    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
+        port = httpd.server_address[1]
+        threading.Thread(target=httpd.serve_forever, daemon=True).start()
+        yield f"http://127.0.0.1:{port}"
+        httpd.shutdown()
+
+
+@pytest.fixture
+def fixture_recipe(site):
+    return {
+        "slug": "fixture",
+        "url": f"{site}/chat.html",
+        "prompt": {"input_selector": "#prompt", "input_mode": "fill", "submit": "click:#send"},
+        "response": {
+            "last_message_selector": ".msg",
+            "done_signal": {"type": "stable_text", "quiet_ms": 400, "timeout_ms": 8000},
+        },
+        "models": [{"id": "fixture-web"}],
+    }
diff --git a/tests/integration/fixtures/chat.html b/tests/integration/fixtures/chat.html
new file mode 100644
index 0000000..a6c70ef
--- /dev/null
+++ b/tests/integration/fixtures/chat.html
@@ -0,0 +1,22 @@
+<!doctype html>
+<html>
+<body>
+<textarea id="prompt"></textarea>
+<button id="send">Send</button>
+<div id="messages"></div>
+<script>
+document.getElementById("send").onclick = () => {
+  const m = document.createElement("div");
+  m.className = "msg";
+  document.getElementById("messages").appendChild(m);
+  const full = "This is the reply.";
+  let i = 0;
+  const t = setInterval(() => {
+    i += 2;
+    m.textContent = full.slice(0, i);
+    if (i >= full.length) clearInterval(t);
+  }, 100);
+};
+</script>
+</body>
+</html>
diff --git a/tests/integration/test_recipe_runner.py b/tests/integration/test_recipe_runner.py
new file mode 100644
index 0000000..7b3fff4
--- /dev/null
+++ b/tests/integration/test_recipe_runner.py
@@ -0,0 +1,34 @@
+import pytest
+
+from chat2api.browserpool import BrowserPool
+from chat2api.providers.browser_recipe import BrowserRecipe
+
+pytest.importorskip("playwright.async_api")
+
+
+async def test_roundtrip_stream(fixture_recipe, tmp_path):
+    pool = BrowserPool(max_contexts=1)
+    await pool.start()
+    try:
+        provider = BrowserRecipe(fixture_recipe, tmp_path, pool)
+        out = []
+        async for delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
+            out.append(delta)
+        assert "".join(out).strip() == "This is the reply."
+    finally:
+        await pool.aclose()
+
+
+async def test_roundtrip_timeout(fixture_recipe, tmp_path):
+    bad = {**fixture_recipe, "response": {**fixture_recipe["response"],
+           "last_message_selector": ".does-not-exist",
+           "done_signal": {**fixture_recipe["response"]["done_signal"], "timeout_ms": 2000}}}
+    pool = BrowserPool(max_contexts=1)
+    await pool.start()
+    try:
+        provider = BrowserRecipe(bad, tmp_path, pool)
+        with pytest.raises(TimeoutError):
+            async for _ in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
+                pass
+    finally:
+        await pool.aclose()
diff --git a/tests/unit/test_recipe_validate.py b/tests/unit/test_recipe_validate.py
new file mode 100644
index 0000000..94a9556
--- /dev/null
+++ b/tests/unit/test_recipe_validate.py
@@ -0,0 +1,25 @@
+from chat2api.providers.browser_recipe import validate_recipe
+
+MINIMAL = {
+    "slug": "x",
+    "url": "https://x.example",
+    "prompt": {"input_selector": "textarea"},
+    "response": {"last_message_selector": ".m", "done_signal": {"type": "stable_text"}},
+    "models": [{"id": "x-web"}],
+}
+
+
+def test_valid_minimal():
+    assert validate_recipe(MINIMAL) == []
+
+
+def test_missing_fields():
+    errs = validate_recipe({})
+    for frag in ("slug", "url", "input_selector", "last_message_selector", "done_signal", "models"):
+        assert any(frag in e for e in errs), errs
+
+
+def test_selector_done_signal_needs_selector():
+    d = {**MINIMAL, "response": {**MINIMAL["response"],
+         "done_signal": {"type": "selector_appear"}}}
+    assert any("selector" in e for e in validate_recipe(d))

