import asyncio
import sys
import time
from pathlib import Path
from typing import AsyncIterator

from ..prompt import flatten_messages
from .base import ModelInfo, Provider


def validate_recipe(d: dict) -> list[str]:
    errs: list[str] = []

    def need(name: str, ok: bool):
        if not ok:
            errs.append(f"missing/invalid field: {name}")

    need("slug", bool(d.get("slug")))
    need("url", bool(d.get("url")))
    need("prompt.input_selector", bool((d.get("prompt") or {}).get("input_selector")))
    resp = d.get("response") or {}
    ds = resp.get("done_signal") or {}
    need("response.last_message_selector", bool(resp.get("last_message_selector")))
    need("response.done_signal.type",
         ds.get("type") in {"stable_text", "selector_appear", "selector_disappear"})
    if ds.get("type") in {"selector_appear", "selector_disappear"}:
        need("response.done_signal.selector", bool(ds.get("selector")))
    models = d.get("models")
    need("models", isinstance(models, list) and len(models) > 0 and all(m.get("id") for m in models))
    return errs


class BrowserRecipe(Provider):
    def __init__(self, recipe: dict, base_dir: Path, pool):
        self._recipe = recipe
        self.slug = recipe["slug"]
        self.base_dir = base_dir
        self.pool = pool
        self.prompt_cfg = recipe.get("prompt", {})
        self.response_cfg = recipe.get("response", {})
        self.ds = self.response_cfg.get("done_signal", {})

    @property
    def url(self) -> str:
        return self._recipe["url"]

    def models(self) -> list[ModelInfo]:
        return [ModelInfo(id=f"{self.slug}/{m['id']}", slug=self.slug) for m in self._recipe["models"]]

    def _storage_state(self) -> Path | None:
        st = (self._recipe.get("login") or {}).get("storage_state")
        return self.base_dir / st if st else None

    async def _reply_text(self, page) -> str:
        sel = self.response_cfg["last_message_selector"]
        return await page.evaluate(
            """(sel) => { const els = document.querySelectorAll(sel);
                 return els.length ? els[els.length - 1].innerText : ""; }""",
            sel,
        )

    async def stream(self, messages: list[dict], model_id: str) -> AsyncIterator[str]:
        prompt = flatten_messages(messages)
        ctx = await self.pool.context_for(self.slug, self._storage_state())
        page = await ctx.new_page()
        timeout_ms = int(self.ds.get("timeout_ms", 120000))
        deadline = time.monotonic() + timeout_ms / 1000
        quiet_ms = int(self.ds.get("quiet_ms", 3000))
        try:
            await page.goto(self.url, wait_until="domcontentloaded", timeout=min(timeout_ms, 60000))
            box = page.locator(self.prompt_cfg["input_selector"]).first
            if self.prompt_cfg.get("input_mode", "fill") == "type":
                await box.click()
                await box.type(prompt)
            else:
                await box.fill(prompt)
            submit = self.prompt_cfg.get("submit", "Enter")
            if submit.startswith("click:"):
                await page.click(submit.split(":", 1)[1])
            else:
                await box.press("Enter")

            dtype = self.ds.get("type", "stable_text")
            stable_since = None
            last = ""
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"recipe '{self.slug}' timeout sau {timeout_ms}ms")
                text = await self._reply_text(page)
                if text != last:
                    if text.startswith(last):
                        yield text[len(last):]
                    last = text
                    stable_since = time.monotonic()
                if dtype == "stable_text":
                    done = (bool(last.strip()) and last.strip() != prompt.strip()
                            and stable_since is not None
                            and (time.monotonic() - stable_since) * 1000 >= quiet_ms)
                else:
                    count = await page.locator(self.ds["selector"]).count()
                    appear = dtype == "selector_appear"
                    done = ((count > 0) == appear) and stable_since is not None \
                        and (time.monotonic() - stable_since) * 1000 >= min(quiet_ms, 1000)
                if done:
                    return
                await asyncio.sleep(0.5)
        finally:
            await page.close()
