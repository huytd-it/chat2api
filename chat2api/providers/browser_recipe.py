import asyncio
import contextlib
import hashlib
import os
import re
import sys
import time
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import urlsplit

from .. import accounts, applog, settings, store
from ..prompt import flatten_messages
from .base import ModelInfo, Provider

DONE_SIGNALS = {"stable_text", "selector_appear", "selector_disappear", "copy_button"}
COPY_SCOPES = {"after", "inside", "page"}
# Gần như web chat nào cũng gắn nút "Copy" ngay dưới câu trả lời và CHỈ gắn khi
# câu trả lời đã viết xong — nên nó là mốc "xong" chính xác hơn hẳn việc đoán
# qua text đứng yên. Danh sách dưới là mặc định khi recipe không tự khai
# `selector`, gom các cách đánh dấu nút copy hay gặp (en/vi/zh).
DEFAULT_COPY_BUTTON_SELECTOR = (
    'button[aria-label*="copy" i], '
    'button[title*="copy" i], '
    '[role="button"][aria-label*="copy" i], '
    '[data-testid*="copy" i], '
    '[data-test-id*="copy" i], '
    'button[aria-label*="sao chép" i], '
    'button[title*="sao chép" i], '
    'button[aria-label*="复制"], '
    'button[title*="复制"], '
    "copy-button button"
)

LOGIN_STRATEGIES = {"round_robin", "fill_first"}
# Cách chọn account khi client không tự chỉ định (API_ACCOUNT_STRATEGY).
ASSIGN_STRATEGIES = {"least_busy", "round_robin", "sticky_session", "off"}

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


def _page_url(page) -> str | None:
    """URL hiện tại của tab, None khi tab đã đóng/hỏng — không được ném lỗi."""
    try:
        url = page.url
    except Exception:
        return None
    return url if url and url not in ("about:blank", "") else None


def _profile_named(name: str, profiles_dir: Path):
    """Profile theo tên, cấp thư mục user_data_dir nếu nó chưa từng được mở.

    Hàng do importer tạo từ file `.accounts` có `user_data_dir` rỗng — mở
    persistent context với đường dẫn rỗng thì Chromium chết. `ensure_profile`
    chỉ điền vào chỗ trống, không đụng cấu hình người dùng đã sửa.
    """
    from .. import profiles as profiles_mod

    try:
        return profiles_mod.ensure_profile(name, profiles_dir)
    except (ValueError, RuntimeError):
        return profiles_mod.get_profile(name)


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
    need("response.done_signal.type", ds.get("type") in DONE_SIGNALS)
    if ds.get("type") in {"selector_appear", "selector_disappear"}:
        need("response.done_signal.selector", bool(ds.get("selector")))
    if ds.get("type") == "copy_button":
        # `selector` là tùy chọn: bỏ trống thì dùng DEFAULT_COPY_BUTTON_SELECTOR.
        if ds.get("scope") is not None and ds.get("scope") not in COPY_SCOPES:
            errs.append("invalid field: response.done_signal.scope (after | inside | page)")
        fb = ds.get("fallback_quiet_ms")
        if fb is not None and (not isinstance(fb, int) or fb < 0):
            errs.append("invalid field: response.done_signal.fallback_quiet_ms (số nguyên >= 0)")
        use_copy = ds.get("use_copy_result")
        if use_copy is not None and not isinstance(use_copy, bool):
            errs.append("invalid field: response.done_signal.use_copy_result (boolean)")
    models = d.get("models")
    need("models", isinstance(models, list) and len(models) > 0
         and all(isinstance(m, dict) and m.get("id") for m in models))
    if isinstance(models, list):
        for i, model in enumerate(models):
            if not isinstance(model, dict):
                continue
            action = model.get("action")
            steps = action.split(";") if isinstance(action, str) else []
            if action is not None and not (steps and all(
                    (step.strip().startswith("click:") or step.strip().startswith("select:"))
                    and step.strip().split(":", 1)[1].strip() for step in steps)):
                errs.append(
                    f"invalid field: models[{i}].action (click:<selector> | select:<selector>)")

    login = d.get("login") or {}
    if login.get("strategy", "round_robin") not in LOGIN_STRATEGIES:
        errs.append("invalid field: login.strategy (round_robin | fill_first)")
    quota = login.get("quota", 50)
    if not isinstance(quota, int) or quota < 1:
        errs.append("invalid field: login.quota (số nguyên dương)")
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


async def discover_models(page, before_action: str = "") -> list[dict]:
    """Dò model control đang hiện trên trang, chỉ chạy khi người dùng yêu cầu."""
    found = await page.evaluate(
        r"""() => {
          const visible = el => {
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return !!(rect.width && rect.height) && style.display !== 'none'
              && style.visibility !== 'hidden';
          };
          const selector = el => {
            if (el.id) return '#' + CSS.escape(el.id);
            for (const attr of ['data-testid', 'data-model', 'data-value', 'aria-label']) {
              const value = el.getAttribute(attr);
              if (value) return `${el.tagName.toLowerCase()}[${attr}=${JSON.stringify(value)}]`;
            }
            const tag = el.tagName.toLowerCase();
            const parent = el.parentElement;
            if (!parent) return tag;
            const siblings = [...parent.children].filter(item => item.tagName === el.tagName);
            return `${tag}:nth-of-type(${siblings.indexOf(el) + 1})`;
          };
          const clean = value => String(value || '').trim().replace(/\s+/g, ' ');
          const idOf = (label, value) => {
            const source = clean(value || label).toLowerCase();
            return source.replace(/[^a-z0-9._-]+/g, '-').replace(/^-|-$/g, '') || 'model';
          };
          const out = [];
          for (const select of document.querySelectorAll('select')) {
            const hint = clean([select.name, select.id, select.getAttribute('aria-label')].join(' '));
            if (!/model|modele|mô hình|模型/i.test(hint) || !visible(select)) continue;
            for (const option of select.options) {
              const label = clean(option.textContent);
              const value = option.value;
              if (!label || option.disabled || !value) continue;
              out.push({ id: idOf(label, value), label, action: `select:${selector(select)}`, value });
            }
          }
          const choices = document.querySelectorAll(
            '[role=option], [role=menuitemradio], [data-model], [data-model-id]');
          for (const choice of choices) {
            if (!visible(choice) || choice.getAttribute('aria-disabled') === 'true') continue;
            const label = clean(choice.getAttribute('aria-label') || choice.textContent);
            const value = choice.getAttribute('data-model-id') || choice.getAttribute('data-model')
              || choice.getAttribute('data-value') || '';
            if (!label || label.length > 100) continue;
            out.push({ id: idOf(label, value), label, action: `click:${selector(choice)}` });
          }
          return out.filter((item, index) => out.findIndex(other => other.id === item.id) === index);
        }""")
    if before_action:
        for item in found:
            if item["action"].startswith("click:"):
                item["action"] = f"{before_action};{item['action']}"
    return found


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


class Assignment:
    """Account + profile + tab mà đúng MỘT request sẽ chạy trên.

    Sinh ra trước khi gọi `stream()` chứ không phải bên trong, vì hai lý do:
    handler phải trả header "request này đi tới đâu" ngay lúc mở response (SSE
    không sửa header được nữa sau byte đầu), và chỗ giữ *chỗ* (`_inflight` của
    recipe) phải được đặt trước khi request kế tiếp chọn account — nếu không hai
    request đến cùng lúc đều thấy mọi account đang rảnh và cùng nhảy vào một cái.

    Người tạo ra assignment cũng là người phải `release()` nó; `release()` gọi
    nhiều lần vẫn an toàn.
    """

    __slots__ = (
        "_released",
        "account_id",
        "account_label",
        "conversation_url",
        "ctx_key",
        "headed",
        "host",
        "html",
        "profile",
        "profile_id",
        "profile_name",
        "recipe",
        "slot",
        "storage_state",
    )

    def __init__(self, recipe, ctx_key: str, *, account_id: int | None = None,
                 account_label: str = "", profile_id: int | None = None,
                 profile_name: str | None = None, host: str = "", slot: int = 0,
                 storage_state: Path | None = None, profile=None):
        self.recipe = recipe
        self.ctx_key = ctx_key
        self.account_id = account_id
        self.account_label = account_label
        self.profile_id = profile_id
        self.profile_name = profile_name
        self.host = host
        self.slot = slot
        self.storage_state = storage_state
        self.profile = profile
        # Điền sau khi stream xong: link hội thoại thật trên site và HTML gốc.
        self.conversation_url: str | None = None
        self.html: str | None = None
        # Điền khi stream bắt đầu: request này có mở cửa sổ nhìn thấy được không.
        self.headed: bool | None = None
        self._released = False

    @property
    def label(self) -> str:
        """Một dòng đọc được cho log và header: 'profile/host/account'."""
        parts = [self.profile_name or "-", self.host or "-", self.account_label or "-"]
        return "/".join(parts)

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self.recipe is not None:
            self.recipe._unreserve(self.ctx_key)


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
        self._structured_markdown = self.response_cfg.get("format") == "markdown"
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
        # Số request đang giữ mỗi ctx_key (đã nhận nhưng chưa xong). Đây là thứ
        # `least_busy` đọc để toả request ra nhiều account thay vì dồn một chỗ.
        self._inflight: dict[str, int] = {}
        self._assign_lock = asyncio.Lock()
        self._assign_cursor = 0
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

    # ------------------------------------------------- chọn account cho request

    def _reserve(self, ctx_key: str) -> None:
        self._inflight[ctx_key] = self._inflight.get(ctx_key, 0) + 1

    def _unreserve(self, ctx_key: str) -> None:
        left = self._inflight.get(ctx_key, 0) - 1
        if left > 0:
            self._inflight[ctx_key] = left
        else:
            self._inflight.pop(ctx_key, None)

    def inflight(self, ctx_key: str = "") -> int:
        if ctx_key:
            return self._inflight.get(ctx_key, 0)
        return sum(self._inflight.values())

    def _ctx_key_for(self, account_id: int, slot: int) -> str:
        """Slot 0 giữ đúng tên cũ để tab headed đã mở bằng `open_target` dùng lại được."""
        base = f"{self.slug}::account-{account_id}"
        return base if slot == 0 else f"{base}#{slot}"

    def db_accounts(self) -> list[dict]:
        """Account trong DB phục vụ domain của recipe này (blocking — SQLite).

        Đây mới là danh sách "gửi tới Account/Profile nào" mà UI hiểu được: kho
        file `.accounts/` chỉ có tên, không có profile Chromium đi kèm.
        """
        db = store.default()
        if db is None or not self.domain:
            return []
        try:
            rows = db.query(
                "SELECT a.id, a.label, a.profile_id, p.name AS profile_name, d.host "
                "FROM account a JOIN profile p ON p.id = a.profile_id "
                "JOIN domain d ON d.id = a.domain_id "
                "WHERE a.disabled = 0 AND (d.host = ? OR d.host = ?) "
                "ORDER BY a.id", (self.domain, "www." + self.domain))
        except Exception:
            return []
        return [dict(row) for row in rows]

    def _auto_enabled(self) -> bool:
        """Tự gán account/profile được bật không.

        Tắt khi người dùng chọn `off`, và khi engine là cloak — `launch_context_async`
        không nhận `user_data_dir` nên không có persistent profile để gán.
        """
        strategy = settings.current("API_ACCOUNT_STRATEGY")
        if strategy not in ASSIGN_STRATEGIES or strategy == "off":
            return False
        return os.environ.get("BROWSER_ENGINE", "playwright").strip().lower() != "cloak"

    async def assign(self, account_id: int | None = None,
                     sticky_key: str = "") -> Assignment:
        """Chọn (và giữ chỗ) account + profile + tab cho một request.

        `account_id` là chỉ định tường minh của client (header
        X-Chat2api-Account-Id) — luôn thắng mọi chiến lược. Người gọi phải
        `release()` assignment khi request kết thúc.
        """
        slots = max(1, settings.current_int("API_MAX_CONCURRENT_PER_ACCOUNT", 1))
        if account_id is not None:
            row, profile = await asyncio.to_thread(self.resolve_target, account_id)
            async with self._assign_lock:
                slot = self._quietest_slot(int(row["id"]), slots)
                return self._make(row, profile, slot)

        rows = await asyncio.to_thread(self.db_accounts) if self._auto_enabled() else []
        if rows:
            async with self._assign_lock:
                row = self._pick_row(rows, sticky_key)
                slot = self._quietest_slot(int(row["id"]), slots)
                profile = await asyncio.to_thread(
                    _profile_named, row["profile_name"], self._profiles_dir)
                if profile is not None:
                    return self._make(row, profile, slot)

        # Không có account nào trong DB (hoặc chiến lược tắt): đường cũ — kho
        # file `.accounts/` + storage_state, và hạn mức dùng thử ẩn danh.
        name, storage_state = await self._rotator.next()
        ctx_key = self.slug if len(self._accounts) <= 1 else f"{self.slug}::{name}"
        async with self._assign_lock:
            self._reserve(ctx_key)
        return Assignment(self, ctx_key, account_label="" if name == "__anon__" else name,
                          host=self.domain, storage_state=storage_state)

    def _make(self, row, profile, slot: int) -> Assignment:
        ctx_key = self._ctx_key_for(int(row["id"]), slot)
        self._reserve(ctx_key)
        return Assignment(
            self, ctx_key, account_id=int(row["id"]), account_label=row["label"] or "main",
            profile_id=int(row["profile_id"]), profile_name=row["profile_name"],
            host=row["host"], slot=slot, profile=profile)

    def _quietest_slot(self, account_id: int, slots: int) -> int:
        keys = [self._ctx_key_for(account_id, slot) for slot in range(slots)]
        return min(range(slots), key=lambda i: (self._inflight.get(keys[i], 0), i))

    def _pick_row(self, rows: list[dict], sticky_key: str) -> dict:
        strategy = settings.current("API_ACCOUNT_STRATEGY")
        if strategy == "sticky_session" and sticky_key:
            digest = hashlib.sha256(sticky_key.encode("utf-8", "replace")).digest()
            return rows[int.from_bytes(digest[:8], "big") % len(rows)]
        # sticky_session không có khoá để bám (client không gửi session id) thì
        # xoay vòng, chứ không phải luôn trả về account đầu tiên.
        if strategy in ("round_robin", "sticky_session"):
            row = rows[self._assign_cursor % len(rows)]
            self._assign_cursor += 1
            return row
        # least_busy: account nào ít request đang chạy nhất. Con trỏ xoay vòng
        # phá hoà — nếu không, lúc mọi account đều rảnh thì request nào cũng
        # rơi vào account đầu tiên và "nhiều request một lúc" lại về một profile.
        offset = self._assign_cursor % len(rows)
        self._assign_cursor += 1
        order = [rows[(offset + i) % len(rows)] for i in range(len(rows))]
        return min(order, key=lambda r: self.account_load(int(r["id"])))

    def account_load(self, account_id: int) -> int:
        """Số request đang chạy trên một account (cộng mọi slot của nó)."""
        prefix = f"{self.slug}::account-{account_id}"
        return sum(count for key, count in self._inflight.items()
                   if key == prefix or key.startswith(prefix + "#"))

    def resolve_target(self, account_id: int):
        """Resolve a desktop test target and reject cross-domain accounts."""
        db = store.default()
        if db is None:
            raise ValueError("Kho dữ liệu chưa mở")
        rows = db.query(
            "SELECT a.id, a.label, a.profile_id, p.name AS profile_name, d.host "
            "FROM account a JOIN profile p ON p.id = a.profile_id "
            "JOIN domain d ON d.id = a.domain_id "
            "WHERE a.id = ? AND a.disabled = 0", (account_id,))
        if not rows:
            raise ValueError(f"Account {account_id} không tồn tại hoặc đã tắt")
        row = rows[0]
        account_domain = str(row["host"] or "").lower()
        if account_domain.startswith("www."):
            account_domain = account_domain[4:]
        if account_domain != self.domain:
            raise ValueError(
                f"Account {account_id} thuộc {row['host']}, không dùng được cho {self.domain}")
        profile = _profile_named(row["profile_name"], self._profiles_dir)
        if profile is None:
            raise ValueError(f"Profile '{row['profile_name']}' không tồn tại")
        return row, profile

    def resolve_headed(self, headed: bool | None, profile) -> bool:
        """Request này có mở cửa sổ nhìn thấy được không.

        Thứ tự: header ``X-Chat2api-Headed`` của client → ``API_HEADED`` →
        ô "Chạy ẩn" của chính profile → mặc định của provider. Đặt ở một chỗ để
        request API và nút Gửi ở bàn test đi đúng cùng một đường.

        ``API_HEADED`` mặc định là ``always``: request API mở cửa sổ nhìn thấy
        được, vì không nhìn thấy thì không debug được recipe đang kẹt ở đâu. Ô
        "Chạy ẩn" của profile chỉ có tiếng nói khi người dùng chọn ``auto``.
        """
        if headed is not None:
            return headed
        mode = settings.current("API_HEADED")
        if mode == "always":
            return True
        if mode == "never":
            return False
        if profile is not None:
            return not profile.headless
        return self._headed

    async def open_profile_page(self, profile, ctx_key: str, headed: bool):
        """Tab dài hạn trong một persistent profile, đúng chế độ hiện/ẩn đã chọn.

        Profile đang chạy nền mà request muốn thấy cửa sổ thì phải dựng lại tiến
        trình: Chromium không "hiện" được một cửa sổ chưa từng tồn tại. Chiều
        ngược lại thì dùng lại cửa sổ đang mở — đóng nó đi là cướp mất thứ người
        dùng đang nhìn.
        """
        from dataclasses import replace

        if headed and self.pool.profile_headless(profile.name) is True:
            await self.pool.drop_profile(profile.name)
        want = replace(profile, headless=False) if headed else profile
        return await self.pool.page_for(want, ctx_key)

    async def open_target(self, account_id: int, ctx_key: str = "", headed: bool = True):
        """Open the exact persistent-profile tab later used by ``stream``."""
        row, profile = self.resolve_target(account_id)
        tab_key = ctx_key or self._ctx_key_for(account_id, 0)
        # Ghim ngay từ đầu: mở nhiều target một lượt thì lần mở sau không được
        # phép đóng profile/tab mà lần mở trước vừa dựng xong.
        async with self.pool.hold(profile.name, tab_key):
            page = await self.open_profile_page(profile, tab_key, headed)
            await page.goto(self._new_chat_url or self.url, wait_until="domcontentloaded",
                            timeout=min(int(self.ds.get("timeout_ms", 120000)), 60000))
        return row, page

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
        """Đọc reply dưới dạng Markdown và, khi bật, outerHTML gốc."""
        sel = self.response_cfg["last_message_selector"]
        result = await page.evaluate(
            r"""([sel, captureHtml, structuredMarkdown]) => {
                 const els = document.querySelectorAll(sel);
                 if (!els.length) return ["", null];
                 const el = els[els.length - 1];
                 if (!structuredMarkdown) {
                   return [el.innerText || "", captureHtml ? el.outerHTML : null];
                 }

                 const clean = value => value
                   .replace(/[ \t]+\n/g, "\n")
                   .replace(/\n{3,}/g, "\n\n")
                   .trim();
                 const inline = node => {
                   if (node.nodeType === Node.TEXT_NODE) return node.nodeValue || "";
                   if (node.nodeType !== Node.ELEMENT_NODE) return "";
                   const tag = node.tagName.toLowerCase();
                   const body = Array.from(node.childNodes).map(inline).join("");
                   if (tag === "br") return "  \n";
                   if (tag === "strong" || tag === "b") return `**${body}**`;
                   if (tag === "em" || tag === "i") return `*${body}*`;
                   if (tag === "code") return `\`${body}\``;
                   if (tag === "a") {
                     const href = node.getAttribute("href");
                     return href ? `[${body}](${href})` : body;
                   }
                   return body;
                 };
                 const block = (node, depth = 0) => {
                   if (node.nodeType === Node.TEXT_NODE) {
                     const value = node.nodeValue || "";
                     return value.trim() ? value : "";
                   }
                   if (node.nodeType !== Node.ELEMENT_NODE) return "";
                   const tag = node.tagName.toLowerCase();
                   if (/^h[1-6]$/.test(tag)) {
                     return `${"#".repeat(Number(tag[1]))} ${clean(inline(node))}\n\n`;
                   }
                   if (tag === "p" || node.classList.contains("qwen-markdown-paragraph")) {
                     return `${clean(inline(node))}\n\n`;
                   }
                   if (tag === "hr") return "---\n\n";
                   if (tag === "pre") return `\`\`\`\n${node.innerText || ""}\n\`\`\`\n\n`;
                   if (tag === "ul" || tag === "ol") {
                     const items = Array.from(node.children).filter(child =>
                       child.tagName.toLowerCase() === "li");
                     return items.map((item, index) => {
                       const marker = tag === "ol" ? `${index + 1}.` : "-";
                       const text = clean(Array.from(item.childNodes).map(child =>
                         child.nodeType === Node.ELEMENT_NODE &&
                         ["ul", "ol"].includes(child.tagName.toLowerCase())
                           ? "" : inline(child)).join(""));
                       const nested = Array.from(item.children)
                         .filter(child => ["ul", "ol"].includes(child.tagName.toLowerCase()))
                         .map(child => block(child, depth + 1).trimEnd())
                         .join("\n");
                       return `${"  ".repeat(depth)}${marker} ${text}${nested ? `\n${nested}` : ""}`;
                     }).join("\n") + "\n\n";
                   }
                   if (tag === "blockquote") {
                     return clean(Array.from(node.childNodes).map(child => block(child, depth)).join(""))
                       .split("\n").map(line => `> ${line}`).join("\n") + "\n\n";
                   }
                   return Array.from(node.childNodes).map(child => block(child, depth)).join("");
                 };

                 const markdown = clean(Array.from(el.childNodes).map(node => block(node)).join(""));
                 return [markdown || el.innerText || "", captureHtml ? el.outerHTML : null];
               }""",
            [sel, self._capture_html, self._structured_markdown],
        )
        return str(result[0] or ""), result[1]

    async def _reply_text(self, page) -> str:
        """Compatibility helper cho code/test ngoài module chỉ cần nội dung."""
        text, _ = await self._reply(page)
        return text

    async def _copy_button_ready(self, page, selector: str, scope: str,
                                 exclude: str) -> bool:
        """Nút Copy của câu trả lời CUỐI đã hiện và bấm được chưa.

        Không dùng `count()` toàn trang như `selector_appear`: hội thoại cũ (và
        cả tin nhắn của người dùng) cũng có nút copy, đếm cả trang thì vừa gửi
        prompt đã thấy "xong". Ở đây nút phải nằm TRONG hoặc SAU khối câu trả
        lời cuối theo thứ tự DOM — đúng chỗ web chat gắn thanh hành động.
        """
        try:
            return bool(await page.evaluate(
                r"""([msgSel, btnSel, scope, excludeSel]) => {
                     let btns;
                     try { btns = Array.from(document.querySelectorAll(btnSel)); }
                     catch (e) { return false; }
                     const nameOf = b => [b.getAttribute("aria-label"),
                                          b.getAttribute("title"),
                                          b.textContent].join(" ").toLowerCase();
                     const usable = btns.filter(b => {
                       if (b.disabled || b.getAttribute("aria-disabled") === "true") return false;
                       // "Copy code" mọc lên NGAY khi code block bắt đầu stream,
                       // còn lâu mới xong câu trả lời — không được tính.
                       if (b.closest("pre")) return false;
                       if (/code|mã nguồn|代码/.test(nameOf(b))) return false;
                       if (excludeSel) {
                         try { if (b.closest(excludeSel)) return false; } catch (e) {}
                       }
                       // Nút mới render nhưng chưa chiếm chỗ (display:none) thì
                       // chưa tính; opacity 0 vì hiệu ứng hover vẫn tính là có.
                       if (!b.getClientRects().length) return false;
                       const st = getComputedStyle(b);
                       return st.visibility !== "hidden" && st.display !== "none";
                     });
                     if (!usable.length) return false;
                     if (scope === "page") return true;
                     const msgs = document.querySelectorAll(msgSel);
                     if (!msgs.length) return false;
                     const msg = msgs[msgs.length - 1];
                     return usable.some(b => {
                       if (msg.contains(b)) return true;
                       if (scope === "inside") return false;
                       return !!(msg.compareDocumentPosition(b) &
                                 Node.DOCUMENT_POSITION_FOLLOWING);
                     });
                   }""",
                [self.response_cfg["last_message_selector"], selector, scope, exclude],
            ))
        except Exception:
            # Trang đang điều hướng/đóng tab: coi như chưa xong, vòng poll sau
            # sẽ hỏi lại, hết giờ thì deadline lo.
            return False

    async def _copy_button_result(self, page, selector: str, scope: str,
                                  exclude: str) -> str:
        """Bấm đúng nút Copy của reply cuối và đọc nội dung clipboard."""
        parsed = urlsplit(page.url)
        await page.context.grant_permissions(
            ["clipboard-read", "clipboard-write"], origin=f"{parsed.scheme}://{parsed.netloc}")
        await page.evaluate("navigator.clipboard.writeText('')")
        clicked = await page.evaluate(
            r"""([msgSel, btnSel, scope, excludeSel]) => {
                 let btns;
                 try { btns = Array.from(document.querySelectorAll(btnSel)); }
                 catch (e) { return false; }
                 const nameOf = b => [b.getAttribute("aria-label"),
                                      b.getAttribute("title"),
                                      b.textContent].join(" ").toLowerCase();
                 const usable = btns.filter(b => {
                   if (b.disabled || b.getAttribute("aria-disabled") === "true") return false;
                   if (b.closest("pre") || /code|mã nguồn|代码/.test(nameOf(b))) return false;
                   if (excludeSel) {
                     try { if (b.closest(excludeSel)) return false; } catch (e) {}
                   }
                   if (!b.getClientRects().length) return false;
                   const st = getComputedStyle(b);
                   return st.visibility !== "hidden" && st.display !== "none";
                 });
                 const msgs = document.querySelectorAll(msgSel);
                 if (!usable.length || (scope !== "page" && !msgs.length)) return false;
                 const msg = msgs[msgs.length - 1];
                 let target;
                 if (scope === "page") {
                   target = usable[usable.length - 1];
                 } else {
                   const inside = usable.filter(b => msg.contains(b));
                   if (inside.length) target = inside[inside.length - 1];
                   else if (scope === "after") target = usable.find(b =>
                     msg.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
                 }
                 if (!target) return false;
                 target.click();
                 return true;
               }""",
            [self.response_cfg["last_message_selector"], selector, scope, exclude],
        )
        if not clicked:
            return ""
        await asyncio.sleep(0.1)
        return str(await page.evaluate("navigator.clipboard.readText()") or "")

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
                     headed: bool | None = None,
                     target_account_id: int | None = None,
                     assignment: "Assignment | None" = None) -> AsyncIterator[str]:
        prompt = flatten_messages(messages)
        self.last_response_html = None
        # Handler thường gán sẵn (để trả header "đi tới đâu" trước khi stream mở);
        # gọi thẳng stream() không kèm assignment vẫn chạy được, tự gán rồi tự nhả.
        owned = assignment is None
        if owned:
            assignment = await self.assign(target_account_id)
        try:
            async for delta in self._run(prompt, model_id, assignment, headed):
                yield delta
        finally:
            if owned:
                assignment.release()

    async def _run(self, prompt: str, model_id: str, assignment: "Assignment",
                   headed: bool | None) -> AsyncIterator[str]:
        target_profile = assignment.profile
        storage_state = assignment.storage_state
        ctx_key = assignment.ctx_key
        # Handler đã chốt và đã trả về trong header rồi thì phải chạy đúng cái
        # đó, không tự quyết lại — nếu không, header nói một đằng, cửa sổ một nẻo.
        if assignment.headed is None:
            assignment.headed = self.resolve_headed(headed, target_profile)
        effective_headed = assignment.headed
        timeout_ms = int(self.ds.get("timeout_ms", 120000))
        dtype = self.ds.get("type", "stable_text")
        # copy_button có tín hiệu dứt khoát nên chỉ cần chống nhiễu vài trăm ms,
        # không phải chờ hết khoảng "im lặng" dài như stable_text.
        quiet_ms = int(self.ds.get("quiet_ms", 600 if dtype == "copy_button" else 3000))
        copy_sel = str(self.ds.get("selector") or DEFAULT_COPY_BUTTON_SELECTOR)
        copy_scope = str(self.ds.get("scope") or "after")
        copy_exclude = str(self.ds.get("exclude") or "")
        use_copy_result = bool(self.ds.get("use_copy_result", False))
        # Selector nút copy sai (site đổi giao diện) mà không có lối thoát thì
        # MỌI request đều chạy tới timeout rồi hỏng — mất luôn câu trả lời đã
        # nhận đủ. Nên vẫn giữ đường lùi: text đứng yên đủ lâu thì chốt và ghi
        # log cảnh báo. Đặt `fallback_quiet_ms: 0` để tắt hẳn.
        copy_fallback_ms = int(self.ds.get("fallback_quiet_ms", 15000))
        # Page dùng chung cho mỗi ctx_key nên hai request cùng account phải nối
        # đuôi nhau, không chen ngang vào cùng một ô input.
        async with self._lock_for(ctx_key), contextlib.AsyncExitStack() as stack:
            if target_profile is not None:
                await stack.enter_async_context(self.pool.hold(target_profile.name, ctx_key))
                page = await self.open_profile_page(target_profile, ctx_key, effective_headed)
            else:
                page = await self._acquire_page(ctx_key, storage_state, effective_headed)
            deadline = time.monotonic() + timeout_ms / 1000
            try:
                await page.goto(self._new_chat_url or self.url, wait_until="domcontentloaded",
                                timeout=min(timeout_ms, 60000))
                box = page.locator(self.prompt_cfg["input_selector"]).first
                await self._wait_chat_ready(page, box)
                await _sleep_ms(self._input_delay_ms)
                model = next((item for item in self._recipe["models"]
                              if item["id"] == model_id), None)
                if model is not None and model.get("action"):
                    for step in model["action"].split(";"):
                        action, selector = step.strip().split(":", 1)
                        if action == "select":
                            await page.locator(selector).first.select_option(
                                value=str(model.get("value") or model["id"]))
                        else:
                            await page.locator(selector).first.click()
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

                stable_since = None
                # Lần đầu thấy nút copy của câu trả lời cuối (copy_button).
                copy_since = None
                last = ""
                # HTML gốc giữ ở biến cục bộ chứ không phải trên self: hai
                # request song song (hai account) dùng chung một instance
                # provider, ghi vào self là cái sau đè lên cái trước.
                captured_html: str | None = None
                while True:
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"recipe '{self.slug}' timeout sau {timeout_ms}ms")
                    text, reply_html = await self._reply(page)
                    if reply_html is not None:
                        captured_html = reply_html
                        self.last_response_html = reply_html
                    if text != last:
                        if (not use_copy_result and not self._structured_markdown and text.startswith(last)
                                and text.strip() != prompt.strip()):
                            yield text[len(last):]
                        last = text
                        stable_since = time.monotonic()
                    has_reply = bool(last.strip()) and last.strip() != prompt.strip()
                    quiet_for = ((time.monotonic() - stable_since) * 1000
                                 if stable_since is not None else 0)
                    if dtype == "stable_text":
                        done = has_reply and stable_since is not None and quiet_for >= quiet_ms
                    elif dtype == "copy_button":
                        seen = has_reply and await self._copy_button_ready(
                            page, copy_sel, copy_scope, copy_exclude)
                        if not seen:
                            copy_since = None
                        elif copy_since is None:
                            copy_since = time.monotonic()
                        # Đòi cả nút VÀ text đứng yên: vài site dựng sẵn thanh
                        # hành động (ẩn mờ) ngay khi bắt đầu trả lời.
                        done = (copy_since is not None
                                and (time.monotonic() - copy_since) * 1000 >= quiet_ms
                                and quiet_for >= quiet_ms)
                        if (not done and copy_fallback_ms and has_reply
                                and quiet_for >= copy_fallback_ms):
                            applog.log(
                                f"recipe: '{self.slug}' không thấy nút copy sau "
                                f"{copy_fallback_ms}ms text đứng yên — chốt theo "
                                f"stable_text, nên kiểm tra lại done_signal.selector",
                                level="warn")
                            done = True
                    else:
                        count = await page.locator(self.ds["selector"]).count()
                        appear = dtype == "selector_appear"
                        done = (((count > 0) == appear) and stable_since is not None
                                and quiet_for >= min(quiet_ms, 1000))
                    if done:
                        assignment.html = captured_html
                        assignment.conversation_url = _page_url(page)
                        if use_copy_result:
                            try:
                                copied = await self._copy_button_result(
                                    page, copy_sel, copy_scope, copy_exclude)
                            except Exception as error:
                                applog.log(
                                    f"recipe: '{self.slug}' không đọc được kết quả từ nút Copy: "
                                    f"{error}; dùng text từ DOM",
                                    level="warn")
                                copied = ""
                            yield copied or last
                        elif self._structured_markdown:
                            yield last
                        return
                    await asyncio.sleep(0.5)
            finally:
                if assignment.conversation_url is None:
                    # Cả đường lỗi/timeout cũng phải để lại link: đó chính là chỗ
                    # người dùng cần mở ra xem site thật đang hiện cái gì.
                    assignment.conversation_url = _page_url(page)
                    assignment.html = captured_html
                # Không đóng page/browser ở đây: cửa sổ phải còn nguyên sau khi
                # trả lời xong, chỉ đóng khi người dùng tắt tay hoặc gọi
                # close_browser(). keep_context=false là lựa chọn tường minh
                # trong recipe nên vẫn được tôn trọng.
                if not self._keep_context:
                    await self._release_ctx(ctx_key)
