### Task 6: Browser pool vá»›i engine switch

**Files:**
- Create: `chat2api/browserpool.py`
- Test: `tests/integration/test_pool.py`

**Interfaces:**
- Produces: `BrowserPool(engine: str = "playwright", max_contexts: int = 3)`:
  - `async start()` â€” báº¯t buá»™c gá»i trÆ°á»›c khi dÃ¹ng (engine playwright)
  - `async context_for(slug: str, storage_state: Path | None = None) -> BrowserContext` â€” context giá»¯ lÃ¢u per-slug (giá»¯ login); LRU Ä‘Ã³ng bá»›t khi vÆ°á»£t max_contexts; thuá»™c tÃ­nh `size: int`

- [ ] **Step 1: Implement**

`chat2api/browserpool.py`:

```python
from collections import OrderedDict
from pathlib import Path


class BrowserPool:
    """Má»™t BrowserContext dÃ i háº¡n cho má»—i slug.

    ponytail: engine cloak táº¡o 1 browser riÃªng má»—i context (náº·ng hÆ¡n) â€”
    cháº¥p nháº­n vÃ¬ cloak chá»‰ báº­t cho site bot-detect khÃ³.
    """

    def __init__(self, engine: str = "playwright", max_contexts: int = 3):
        self.engine = engine
        self.max_contexts = max_contexts
        self._contexts: OrderedDict[str, object] = OrderedDict()
        self._pw = None
        self._browser = None

    @property
    def size(self) -> int:
        return len(self._contexts)

    async def start(self):
        if self.engine == "cloak":
            try:
                from cloakbrowser import launch_context_async  # noqa: F401
            except ImportError as e:
                raise RuntimeError("BROWSER_ENGINE=cloak cáº§n: pip install cloakbrowser") from e
            return
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)

    async def context_for(self, slug: str, storage_state: Path | None = None):
        if slug in self._contexts:
            self._contexts.move_to_end(slug)
            return self._contexts[slug]
        while len(self._contexts) >= self.max_contexts:
            _, old_ctx = self._contexts.popitem(last=False)
            try:
                await old_ctx.close()
            except Exception:
                pass
        state = str(storage_state) if storage_state and storage_state.exists() else None
        if self.engine == "cloak":
            from cloakbrowser import launch_context_async

            ctx = await launch_context_async(headless=True, storage_state=state)
        else:
            ctx = await self._browser.new_context(storage_state=state)
        self._contexts[slug] = ctx
        return ctx

    async def aclose(self):
        for ctx in self._contexts.values():
            try:
                await ctx.close()
            except Exception:
                pass
        self._contexts.clear()
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
```

- [ ] **Step 2: Viáº¿t integration test**

`tests/integration/test_pool.py`:

```python
import pytest

from chat2api.browserpool import BrowserPool

pytest.importorskip("playwright.async_api")


async def test_context_reuse_and_eviction():
    pool = BrowserPool(max_contexts=2)
    await pool.start()
    try:
        c1 = await pool.context_for("a")
        c2 = await pool.context_for("a")
        assert c1 is c2
        await pool.context_for("b")
        await pool.context_for("c")  # evict "a"
        assert pool.size <= 2
        assert c1 not in list(pool._contexts.values())
    finally:
        await pool.aclose()
```

- [ ] **Step 3: CÃ i browser vÃ  cháº¡y**

Run: `playwright install chromium ; python -m pytest tests/integration/test_pool.py -v`
Expected: 1 passed

- [ ] **Step 4: Commit**

```bash
git add chat2api/browserpool.py tests/integration/test_pool.py
git commit -m "feat: per-slug browser pool with playwright/cloak engine switch"
```

---


