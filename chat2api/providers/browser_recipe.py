import asyncio
import os
import re
import sys
import time
from pathlib import Path
from typing import AsyncIterator

from .. import accounts, live_view, store
from ..prompt import flatten_messages
from .base import ModelInfo, Provider

LOGIN_STRATEGIES = {"round_robin", "fill_first"}

# Mỗi mục: (env override, giá trị mặc định ms)
TIMING_DEFAULTS = {
    "ready_delay_ms": ("RECIPE_READY_DELAY_MS", 1200),
    "input_delay_ms": ("RECIPE_INPUT_DELAY_MS", 400),
    "ready_timeout_ms": ("RECIPE_READY_TIMEOUT_MS", 20000),
}


def _timing(cfg: dict, key: str) -> int:
    env, default = TIMING_DEFAULTS[key]
    raw = cfg.get(key)
    if raw is None:
        raw = os.environ.get(env, default)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return default


async def _sleep_ms(ms: int) -> None:
    if ms:
        await asyncio.sleep(ms / 1000)


class TrialLimitExceeded(RuntimeError):
    pass


def _stored_anon_uses(slug: str) -> int:
    """Số lượt dùng thử ẩn danh đã tiêu, đọc lại từ DB khi dựng recipe."""
    db = store.default()
    if db is None or not slug:
        return 0
    try:
        rows = db.query("SELECT anon_used FROM recipe WHERE slug = ?", (slug,))
    except Exception:
        return 0
    return rows[0]["anon_used"] if rows else 0


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

    timing = d.get("timing")
    if timing is not None:
        if not isinstance(timing, dict):
            errs.append("invalid field: timing (phải là mapping)")
        else:
            for key in TIMING_DEFAULTS:
                value = timing.get(key)
                if value is not None and (not isinstance(value, int) or value < 0):
                    errs.append(f"invalid field: timing.{key} (số nguyên >= 0, đơn vị ms)")
    new_chat = d.get("new_chat")
    if new_chat is not None:
        if not isinstance(new_chat, dict):
            errs.append("invalid field: new_chat (phải là mapping)")
        elif not new_chat.get("url") and not new_chat.get("selector"):
            errs.append("invalid field: new_chat (cần url hoặc selector)")
    return errs


class _AccountRotator:
    """Chọn account đăng nhập cho mỗi request khi recipe có nhiều accounts.

    round_robin: xoay vòng account theo thứ tự, mỗi request 1 account khác.
    fill_first: dùng hết quota của account hiện tại rồi mới chuyển account kế tiếp.
    """

    def __init__(self, accounts: list[tuple[str, Path | None]], strategy: str, quota: int,
                anon_trial_limit: int | None = None, slug: str = "", anon_uses: int = 0):
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
        # Đếm từ DB chứ không từ 0: trước đây restart là reset, nên giới hạn dùng
        # thử không có tác dụng gì. `slug` rỗng = không có chỗ lưu (test đơn vị).
        self._anon_uses = anon_uses
        self._slug = slug

    @property
    def anon_trial_limit(self) -> int | None:
        return self._anon_trial_limit

    @property
    def anon_uses(self) -> int:
        return self._anon_uses

    def _persist_anon_uses(self) -> None:
        db = store.default()
        if db is not None and self._slug:
            db.submit("UPDATE recipe SET anon_used = ? WHERE slug = ?",
                      (self._anon_uses, self._slug))

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
                    self._persist_anon_uses()
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
    def __init__(self, recipe: dict, base_dir: Path, pool, headed: bool = False,
                 accounts_root: Path | None = None):
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
        # HTML gốc chỉ được chụp khi recipe bật tường minh để recipe cũ không
        # đổi hành vi và DB không phình ngoài ý muốn. Main đọc giá trị cuối này
        # sau khi stream kết thúc để lưu cùng message assistant.
        self._capture_html = bool(self.response_cfg.get("capture_html", False))
        self.last_response_html: str | None = None
        login_cfg = recipe.get("login") or {}
        # Kho account chung nằm cạnh các recipe (recipes/.accounts). Analyzer chạy
        # recipe thử ở thư mục tạm nên truyền accounts_root tường minh.
        self.accounts_root = Path(accounts_root) if accounts_root else Path(base_dir).parent
        self.domain = accounts.domain_of(recipe.get("url", ""))
        self._accounts = self._resolve_accounts(
            login_cfg, base_dir, self.accounts_root, recipe.get("url", ""))
        # Mặc định giữ context sống giữa các request để không phải mở lại
        # browser + đăng nhập mỗi lần. Site nào khôi phục hội thoại cũ (vd
        # chat.qwen.ai) thì khai báo `new_chat` để mở phiên chat mới; đặt
        # `keep_context: false` nếu muốn dựng context sạch mỗi request.
        self._keep_context = bool(recipe.get("keep_context", True))
        new_chat = recipe.get("new_chat") or {}
        self._new_chat_url = new_chat.get("url")
        self._new_chat_selector = new_chat.get("selector")
        timing = recipe.get("timing") or {}
        self._ready_delay_ms = _timing(timing, "ready_delay_ms")
        self._input_delay_ms = _timing(timing, "input_delay_ms")
        self._ready_timeout_ms = _timing(timing, "ready_timeout_ms")
        # Page dài hạn cho mỗi context: không bao giờ tự đóng sau request, người
        # dùng tự tắt cửa sổ browser. Mỗi ctx_key dùng chung 1 page nên request
        # cùng account phải xếp hàng qua _locks.
        self._pages: dict[str, object] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        # Chế độ profile là opt-in và đọc từ env ngay tại đây thay vì nhận qua
        # tham số: provider được dựng ở nhiều chỗ (router, analyzer, test) mà
        # không phải chỗ nào cũng cầm Config.
        mode = os.environ.get("BROWSER_PROFILE_MODE", "storage_state").strip().lower()
        self._profile_mode = mode == "profile" and os.environ.get("BROWSER_ENGINE",
                                                                  "playwright") != "cloak"
        self._profiles_dir = Path(os.environ.get("CHAT2API_DATA_DIR", "./data")) / "profiles"
        self._profile_max_tabs = max(1, int(os.environ.get("PROFILE_MAX_TABS", "4")))
        self._rotator = _AccountRotator(
            self._accounts,
            login_cfg.get("strategy", "round_robin"),
            int(login_cfg.get("quota", 50)),
            login_cfg.get("anon_trial_limit"),
            slug=self.slug,
            anon_uses=_stored_anon_uses(self.slug),
        )

    @staticmethod
    def _resolve_accounts(login_cfg: dict, base_dir: Path, accounts_root: Path,
                          url: str) -> list[tuple[str, Path | None]]:
        """Gộp account khai báo trong recipe với account dùng chung của domain.

        Account trong kho chung được nhận tự động, nên recipe mới trên domain đã
        đăng nhập chạy được ngay. Khai báo tường minh trong recipe.yaml thắng khi
        trùng tên, để recipe vẫn ghim được đúng file state của riêng nó.
        """
        resolved: dict[str, Path | None] = {}
        for account in login_cfg.get("accounts") or []:
            resolved[account["name"]] = base_dir / account["storage_state"]
        state = login_cfg.get("storage_state")
        if state and not resolved:
            resolved["default"] = base_dir / state
        for name, path in accounts.list_accounts(accounts_root, accounts.domain_of(url)):
            resolved.setdefault(name, path)
        if not resolved:
            return [("__anon__", None)]
        return list(resolved.items())

    @property
    def url(self) -> str:
        return self._recipe["url"]

    @property
    def account_count(self) -> int:
        return 0 if self._accounts[0][0] == "__anon__" else len(self._accounts)

    @property
    def account_names(self) -> list[str]:
        if self._accounts[0][0] == "__anon__":
            return []
        return [name for name, _ in self._accounts]

    def account_storage_state(self, name: str) -> Path | None:
        for acc_name, storage_state in self._accounts:
            if acc_name == name:
                return storage_state
        return None

    async def _release_ctx(self, ctx_key: str) -> None:
        """Dựng lại context sạch cho request sau (chỉ khi keep_context=false)."""
        self._pages.pop(ctx_key, None)
        await self.pool.drop(ctx_key)

    def _lock_for(self, ctx_key: str) -> asyncio.Lock:
        lock = self._locks.get(ctx_key)
        if lock is None:
            lock = self._locks[ctx_key] = asyncio.Lock()
        return lock

    async def _acquire_page(self, ctx_key: str, storage_state, headed: bool):
        """Lấy tab để chạy request, theo chế độ đang bật.

        `storage_state` (mặc định): một context riêng cho mỗi ctx_key, y như cũ.
        `profile`: một persistent context dùng chung cho nhiều recipe, mỗi
        recipe một tab — nên các recipe khác nhau chạy song song được.
        Chế độ profile không áp dụng cho engine `cloak`
        (`launch_context_async` không nhận `user_data_dir`) và cho request
        headed thủ công, hai đường đó rơi về cách cũ.
        """
        profile = None
        if self._profile_mode and not headed and self.pool is not None:
            from .. import profiles as profiles_mod

            try:
                name = await asyncio.to_thread(profiles_mod.profile_for_recipe, self.slug)
                profile = await asyncio.to_thread(
                    profiles_mod.ensure_profile, name, self._profiles_dir,
                    headless=True, max_tabs=self._profile_max_tabs)
            except Exception as error:
                # Kho chưa mở, tên hỏng, hay khoá pid — báo rồi chạy tiếp bằng
                # đường cũ chứ không để chat chết vì một tính năng opt-in.
                print(f"[chat2api] profile cho '{self.slug}' không dùng được: {error}",
                      file=sys.stderr)
                profile = None
        if profile is not None:
            try:
                return await self.pool.page_for(profile, self.slug)
            except Exception as error:
                print(f"[chat2api] mở profile '{profile.name}' thất bại, dùng storage_state: "
                      f"{error}", file=sys.stderr)
        ctx = await self.pool.context_for(ctx_key, storage_state, headed=headed)
        return await self._page_for(ctx, ctx_key)

    async def _page_for(self, ctx, ctx_key: str):
        """Tái sử dụng page đang mở; chỉ mở page mới khi chưa có hoặc bị đóng tay."""
        page = self._pages.get(ctx_key)
        if page is not None and not page.is_closed():
            return page
        page = await ctx.new_page()
        self._pages[ctx_key] = page
        return page

    async def close_browser(self) -> int:
        """Tắt browser của recipe — chỉ chạy khi người dùng bấm tắt thủ công."""
        keys = list(self._pages)
        for ctx_key in keys:
            page = self._pages.pop(ctx_key, None)
            if page is not None and not page.is_closed():
                try:
                    await page.close()
                except Exception:
                    pass
            await self.pool.drop(ctx_key)
        return len(keys)

    @property
    def browser_open(self) -> bool:
        return any(not page.is_closed() for page in self._pages.values())

    @property
    def trial_status(self) -> dict | None:
        limit = self._rotator.anon_trial_limit
        if limit is None or self.account_count:
            return None
        return {"limit": limit, "used": self._rotator.anon_uses}

    def models(self) -> list[ModelInfo]:
        return [ModelInfo(id=f"{self.slug}/{m['id']}", slug=self.slug) for m in self._recipe["models"]]

    async def _reply(self, page) -> tuple[str, str | None]:
        """Đọc reply hiện tại và, khi bật, outerHTML của cùng một element."""
        sel = self.response_cfg["last_message_selector"]
        result = await page.evaluate(
            """([sel, captureHtml]) => {
                 const els = document.querySelectorAll(sel);
                 if (!els.length) return ["", null];
                 const el = els[els.length - 1];
                 return [el.innerText || "", captureHtml ? el.outerHTML : null];
               }""",
            [sel, self._capture_html],
        )
        return str(result[0] or ""), result[1]

    async def _reply_text(self, page) -> str:
        """Compatibility helper cho code/test ngoài module chỉ cần innerText."""
        text, _ = await self._reply(page)
        return text

    async def _wait_chat_ready(self, page, box) -> None:
        """Chờ trang chat sẵn sàng nhận prompt, rồi mở phiên chat mới nếu cần.

        Input thường được render trước khi JS gắn handler: gõ sớm thì mất chữ
        hoặc Enter không gửi, nên sau khi input hiện ra vẫn chờ thêm
        `timing.ready_delay_ms`.
        """
        await box.wait_for(state="visible", timeout=self._ready_timeout_ms)
        if self._new_chat_selector:
            await page.click(self._new_chat_selector, timeout=self._ready_timeout_ms)
            await box.wait_for(state="visible", timeout=self._ready_timeout_ms)
        await _sleep_ms(self._ready_delay_ms)

    async def stream(self, messages: list[dict], model_id: str,
                     headed: bool | None = None, watch_id: str | None = None) -> AsyncIterator[str]:
        prompt = flatten_messages(messages)
        self.last_response_html = None
        account_name, storage_state = await self._rotator.next()
        ctx_key = self.slug if len(self._accounts) <= 1 else f"{self.slug}::{account_name}"
        effective_headed = self._headed if headed is None else headed
        timeout_ms = int(self.ds.get("timeout_ms", 120000))
        quiet_ms = int(self.ds.get("quiet_ms", 3000))
        # Page dùng chung cho mỗi ctx_key nên hai request cùng account phải nối
        # đuôi nhau, không chen ngang vào cùng một ô input.
        async with self._lock_for(ctx_key):
            page = await self._acquire_page(ctx_key, storage_state, effective_headed)
            if watch_id:
                await live_view.register(watch_id, page)
            deadline = time.monotonic() + timeout_ms / 1000
            try:
                await page.goto(self._new_chat_url or self.url, wait_until="domcontentloaded",
                                timeout=min(timeout_ms, 60000))
                box = page.locator(self.prompt_cfg["input_selector"]).first
                await self._wait_chat_ready(page, box)
                await _sleep_ms(self._input_delay_ms)
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
                    text, reply_html = await self._reply(page)
                    if reply_html is not None:
                        self.last_response_html = reply_html
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
                # Không đóng page/browser ở đây: cửa sổ phải còn nguyên sau khi
                # trả lời xong, chỉ đóng khi người dùng tắt tay hoặc gọi
                # close_browser(). keep_context=false là lựa chọn tường minh
                # trong recipe nên vẫn được tôn trọng.
                if watch_id:
                    await live_view.unregister(watch_id, page)
                if not self._keep_context:
                    await self._release_ctx(ctx_key)
