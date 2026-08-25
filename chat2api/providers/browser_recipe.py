import asyncio
import re
import sys
import time
from pathlib import Path
from typing import AsyncIterator

from .. import live_view
from ..prompt import flatten_messages
from .base import ModelInfo, Provider

LOGIN_STRATEGIES = {"round_robin", "fill_first"}


class TrialLimitExceeded(RuntimeError):
    pass


def validate_recipe(d: dict) -> list[str]:
    errs: list[str] = []

    def need(name: str, ok: bool):
        if not ok:
            errs.append(f"missing/invalid field: {name}")

    need("slug", bool(d.get("slug")))
    slug = d.get("slug")
    if slug and not re.fullmatch(r"[a-z0-9-]+", str(slug)):
        errs.append("invalid field: slug (chỉ [a-z0-9-])")
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

    login = d.get("login") or {}
    accounts = login.get("accounts")
    if accounts is not None:
        if not isinstance(accounts, list) or not accounts:
            errs.append("invalid field: login.accounts (phải là list không rỗng)")
        else:
            names = [a.get("name") for a in accounts if isinstance(a, dict)]
            for i, acc in enumerate(accounts):
                if not isinstance(acc, dict) or not acc.get("name") or not acc.get("storage_state"):
                    errs.append(f"invalid field: login.accounts[{i}] (cần name + storage_state)")
            if len(names) != len(set(names)):
                errs.append("invalid field: login.accounts (name bị trùng)")
        if login.get("strategy", "round_robin") not in LOGIN_STRATEGIES:
            errs.append("invalid field: login.strategy (round_robin | fill_first)")
        quota = login.get("quota", 1)
        if not isinstance(quota, int) or quota < 1:
            errs.append("invalid field: login.quota (số nguyên dương)")
    anon_trial_limit = login.get("anon_trial_limit")
    if anon_trial_limit is not None and (not isinstance(anon_trial_limit, int) or anon_trial_limit < 0):
        errs.append("invalid field: login.anon_trial_limit (số nguyên >= 0)")
    return errs


class _AccountRotator:
    """Chọn account đăng nhập cho mỗi request khi recipe có nhiều accounts.

    round_robin: xoay vòng account theo thứ tự, mỗi request 1 account khác.
    fill_first: dùng hết quota của account hiện tại rồi mới chuyển account kế tiếp.
    """

    def __init__(self, accounts: list[tuple[str, Path | None]], strategy: str, quota: int,
                anon_trial_limit: int | None = None):
        self._accounts = accounts
        self._strategy = strategy
        self._quota = max(1, quota)
        self._lock = asyncio.Lock()
        self._rr_index = 0
        self._fill_index = 0
        self._fill_used = 0
        # Chỉ áp dụng khi recipe không có account nào (chạy ẩn danh): giới hạn
        # số lượt dùng thử trước khi bắt buộc thêm tài khoản đăng nhập.
        self._anon_trial_limit = anon_trial_limit
        self._anon_uses = 0

    @property
    def anon_trial_limit(self) -> int | None:
        return self._anon_trial_limit

    @property
    def anon_uses(self) -> int:
        return self._anon_uses

    async def next(self) -> tuple[str, Path | None]:
        if len(self._accounts) <= 1:
            name, storage_state = self._accounts[0]
            if name == "__anon__" and self._anon_trial_limit is not None:
                async with self._lock:
                    if self._anon_uses >= self._anon_trial_limit:
                        raise TrialLimitExceeded(
                            f"Đã dùng hết {self._anon_trial_limit} lượt dùng thử miễn phí. "
                            "Thêm tài khoản đăng nhập để tiếp tục dùng."
                        )
                    self._anon_uses += 1
            return name, storage_state
        async with self._lock:
            if self._strategy == "fill_first":
                if self._fill_used >= self._quota:
                    self._fill_index = (self._fill_index + 1) % len(self._accounts)
                    self._fill_used = 0
                self._fill_used += 1
                return self._accounts[self._fill_index]
            account = self._accounts[self._rr_index]
            self._rr_index = (self._rr_index + 1) % len(self._accounts)
            return account


class BrowserRecipe(Provider):
    def __init__(self, recipe: dict, base_dir: Path, pool, headed: bool = False):
        self._recipe = recipe
        self.slug = recipe["slug"]
        self.base_dir = base_dir
        self.pool = pool
        # True chỉ khi dùng để test recipe (Integrate) với ô "hiện browser" bật —
        # provider load từ router lúc chạy production luôn headless.
        self._headed = headed
        self.prompt_cfg = recipe.get("prompt", {})
        self.response_cfg = recipe.get("response", {})
        self.ds = self.response_cfg.get("done_signal", {})
        login_cfg = recipe.get("login") or {}
        self._accounts = self._resolve_accounts(login_cfg, base_dir)
        self._rotator = _AccountRotator(
            self._accounts,
            login_cfg.get("strategy", "round_robin"),
            int(login_cfg.get("quota", 50)),
            login_cfg.get("anon_trial_limit"),
        )

    @staticmethod
    def _resolve_accounts(login_cfg: dict, base_dir: Path) -> list[tuple[str, Path | None]]:
        accounts = login_cfg.get("accounts")
        if accounts:
            return [(a["name"], base_dir / a["storage_state"]) for a in accounts]
        state = login_cfg.get("storage_state")
        if state:
            return [("default", base_dir / state)]
        return [("__anon__", None)]

    @property
    def url(self) -> str:
        return self._recipe["url"]

    @property
    def account_count(self) -> int:
        return 0 if self._accounts[0][0] == "__anon__" else len(self._accounts)

    @property
    def trial_status(self) -> dict | None:
        limit = self._rotator.anon_trial_limit
        if limit is None or self.account_count:
            return None
        return {"limit": limit, "used": self._rotator.anon_uses}

    def models(self) -> list[ModelInfo]:
        return [ModelInfo(id=f"{self.slug}/{m['id']}", slug=self.slug) for m in self._recipe["models"]]

    async def _reply_text(self, page) -> str:
        sel = self.response_cfg["last_message_selector"]
        return await page.evaluate(
            """(sel) => { const els = document.querySelectorAll(sel);
                 return els.length ? els[els.length - 1].innerText : ""; }""",
            sel,
        )

    async def stream(self, messages: list[dict], model_id: str,
                     headed: bool | None = None, watch_id: str | None = None) -> AsyncIterator[str]:
        prompt = flatten_messages(messages)
        account_name, storage_state = await self._rotator.next()
        ctx_key = self.slug if len(self._accounts) <= 1 else f"{self.slug}::{account_name}"
        effective_headed = self._headed if headed is None else headed
        ctx = await self.pool.context_for(ctx_key, storage_state, headed=effective_headed)
        page = await ctx.new_page()
        if watch_id:
            await live_view.register(watch_id, page)
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
                    if text.startswith(last) and text.strip() != prompt.strip():
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
            if watch_id:
                await live_view.unregister(watch_id, page)
            await page.close()
