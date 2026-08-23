## Commits
62cd25b feat: per-slug browser pool with playwright/cloak engine switch

## Stat
 chat2api/browserpool.py        | 71 ++++++++++++++++++++++++++++++++++++++++++
 tests/integration/test_pool.py | 20 ++++++++++++
 2 files changed, 91 insertions(+)

## Diffdiff --git a/chat2api/browserpool.py b/chat2api/browserpool.py
new file mode 100644
index 0000000..3b8922a
--- /dev/null
+++ b/chat2api/browserpool.py
@@ -0,0 +1,71 @@
+from collections import OrderedDict
+from pathlib import Path
+
+
+class BrowserPool:
+    """Mß╗Öt BrowserContext d├ái hß║ín cho mß╗ùi slug.
+
+    ponytail: engine cloak tß║ío 1 browser ri├¬ng mß╗ùi context (nß║╖ng h╞ín) ΓÇö
+    chß║Ñp nhß║¡n v├¼ cloak chß╗ë bß║¡t cho site bot-detect kh├│.
+    """
+
+    def __init__(self, engine: str = "playwright", max_contexts: int = 3):
+        self.engine = engine
+        self.max_contexts = max_contexts
+        self._contexts: OrderedDict[str, object] = OrderedDict()
+        self._pw = None
+        self._browser = None
+
+    @property
+    def size(self) -> int:
+        return len(self._contexts)
+
+    async def start(self):
+        if self.engine == "cloak":
+            try:
+                from cloakbrowser import launch_context_async  # noqa: F401
+            except ImportError as e:
+                raise RuntimeError("BROWSER_ENGINE=cloak cß║ºn: pip install cloakbrowser") from e
+            return
+        from playwright.async_api import async_playwright
+
+        self._pw = await async_playwright().start()
+        self._browser = await self._pw.chromium.launch(headless=True)
+
+    async def context_for(self, slug: str, storage_state: Path | None = None):
+        if slug in self._contexts:
+            self._contexts.move_to_end(slug)
+            return self._contexts[slug]
+        while len(self._contexts) >= self.max_contexts:
+            _, old_ctx = self._contexts.popitem(last=False)
+            try:
+                await old_ctx.close()
+            except Exception:
+                pass
+        state = str(storage_state) if storage_state and storage_state.exists() else None
+        if self.engine == "cloak":
+            from cloakbrowser import launch_context_async
+
+            ctx = await launch_context_async(headless=True, storage_state=state)
+        else:
+            ctx = await self._browser.new_context(storage_state=state)
+        self._contexts[slug] = ctx
+        return ctx
+
+    async def aclose(self):
+        for ctx in self._contexts.values():
+            try:
+                await ctx.close()
+            except Exception:
+                pass
+        self._contexts.clear()
+        if self._browser:
+            try:
+                await self._browser.close()
+            except Exception:
+                pass
+        if self._pw:
+            try:
+                await self._pw.stop()
+            except Exception:
+                pass
diff --git a/tests/integration/test_pool.py b/tests/integration/test_pool.py
new file mode 100644
index 0000000..7f7ad6c
--- /dev/null
+++ b/tests/integration/test_pool.py
@@ -0,0 +1,20 @@
+import pytest
+
+from chat2api.browserpool import BrowserPool
+
+pytest.importorskip("playwright.async_api")
+
+
+async def test_context_reuse_and_eviction():
+    pool = BrowserPool(max_contexts=2)
+    await pool.start()
+    try:
+        c1 = await pool.context_for("a")
+        c2 = await pool.context_for("a")
+        assert c1 is c2
+        await pool.context_for("b")
+        await pool.context_for("c")  # evict "a"
+        assert pool.size <= 2
+        assert c1 not in list(pool._contexts.values())
+    finally:
+        await pool.aclose()

