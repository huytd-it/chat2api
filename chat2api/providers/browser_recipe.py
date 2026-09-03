import asyncio
import base64
import contextlib
import hashlib
import os
import re
import sys
import time
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import urlsplit

from .. import accounts, applog, flows, settings, store
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
    # Recipe khai báo `flows` tự mang ô nhập/khối trả lời trong từng flow, nên
    # khối `prompt`/`response` phẳng ở gốc chỉ còn là giá trị mặc định dùng chung
    # và được phép vắng mặt.
    declared_flows = isinstance(d.get("flows"), dict) and bool(d.get("flows"))
    errs += flows.validate_flows(d, DONE_SIGNALS, COPY_SCOPES)
    resp = d.get("response") or {}
    ds = resp.get("done_signal") or {}
    if not declared_flows:
        need("prompt.input_selector", bool((d.get("prompt") or {}).get("input_selector")))
        # image recipe có thể dùng image_selector thay vì last_message_selector
        has_image = bool(resp.get("image_selector"))
        if not has_image:
            need("response.last_message_selector", bool(resp.get("last_message_selector")))
    # validate image_copy_selector nếu có
    img_copy_sel = resp.get("image_copy_selector")
    if img_copy_sel is not None and not isinstance(img_copy_sel, str):
        errs.append("invalid field: response.image_copy_selector (phải là string)")
    if resp.get("image_copy_scope") is not None and resp.get("image_copy_scope") not in COPY_SCOPES:
        errs.append("invalid field: response.image_copy_scope (after | inside | page)")
    if resp.get("image_copy_exclude") is not None and not isinstance(resp.get("image_copy_exclude"), str):
        errs.append("invalid field: response.image_copy_exclude (phải là string)")
    if not declared_flows or ds:
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
    mode = d.get("mode")
    if mode is not None:
        if not isinstance(mode, dict):
            errs.append("invalid field: mode (phải là mapping)")
        else:
            for key in ("selector", "image_action", "chat_action"):
                v = mode.get(key)
                if v is not None and not isinstance(v, str):
                    errs.append(f"invalid field: mode.{key} (phải là string)")
                if key.endswith("_action") and isinstance(v, str) and v:
                    steps = v.split(";")
                    if not all(((s.strip().startswith("click:") or s.strip().startswith("select:")) and s.strip().split(":",1)[1].strip()) for s in steps):
                        errs.append(f"invalid field: mode.{key} (click:<selector> | select:<selector>)")

    models = d.get("models")
    need("models", isinstance(models, list) and len(models) > 0
         and all(isinstance(m, dict) and m.get("id") for m in models))
    if isinstance(models, list):
        for i, model in enumerate(models):
            if not isinstance(model, dict):
                continue
            cap = model.get("capability")
            if cap is not None and not flows.capability_valid(cap):
                errs.append(
                    f"invalid field: models[{i}].capability "
                    f"({' | '.join(flows.CAPABILITIES)}; nhiều giá trị ngăn bằng dấu phẩy)")
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
        # Thao tác đã ghi, chia theo việc: select_model / text / image / video.
        # Recipe cũ (phẳng) được dựng lại thành flow tương đương nên không đổi
        # hành vi; recipe mới khai báo `flows` thì mỗi việc có selector riêng.
        self.flows = flows.build_flows(recipe)
        text_flow = self.flows.get("text") or {}
        # Ba thuộc tính dưới là *flow text*, giữ tên cũ vì cả main.py, analyzer
        # lẫn test đều đọc chúng như "luồng chat của recipe này".
        self.prompt_cfg = text_flow.get("prompt") or recipe.get("prompt", {})
        self.response_cfg = text_flow.get("response") or recipe.get("response", {})
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
        mode = recipe.get("mode") or {}
        self._mode_cfg = mode if isinstance(mode, dict) else {}
        # Phần dạo đầu dùng chung trước khi chọn model (mở dropdown, chờ nó hiện).
        select_flow = self.flows.get("select_model") or {}
        self._select_model_selector = str(select_flow.get("selector")
                                          or self._mode_cfg.get("selector") or "")
        self._select_model_action = str(select_flow.get("action") or "")
        self._mode_selector = self._select_model_selector
        self._mode_image_action = str((self.flows.get("image") or {}).get("action") or "")
        self._mode_chat_action = str((self.flows.get("text") or {}).get("action") or "")
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
        self._profile_mode = mode == "profile"
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
        """Tự gán account/profile được bật không. Chỉ tắt khi người dùng chọn `off`."""
        strategy = settings.current("API_ACCOUNT_STRATEGY")
        return strategy in ASSIGN_STRATEGIES and strategy != "off"

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

        ``API_HEADED`` mặc định là ``auto``: theo ô "Chạy ẩn" của profile
        (headless=true → ẩn, ngược lại → hiện). Dùng ``always``/``never`` để
        ép hiện/ẩn bất kể profile.
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

    async def _exec_action_steps(self, page, action_str: str, value: str | None = None) -> None:
        """Thực thi chuỗi `click:`/`select:` cho dropdown/chuyển mode."""
        if not action_str:
            return
        for step in action_str.split(";"):
            step = step.strip()
            if not step:
                continue
            if ":" not in step:
                continue
            action, selector = step.split(":", 1)
            action = action.strip()
            selector = selector.strip()
            if not selector:
                continue
            try:
                loc = page.locator(selector).first
                # chờ selector hiện ra trong 10s (dropdown option thường xuất hiện sau click trước)
                try:
                    await loc.wait_for(state="visible", timeout=10000)
                except Exception:
                    pass
                if action == "select":
                    await loc.select_option(value=str(value or ""))
                else:
                    await loc.click(timeout=10000)
                # chờ UI ổn định giữa các bước dropdown
                await asyncio.sleep(0.35)
            except Exception as e:
                applog.log(f"recipe: '{self.slug}' action '{action}:{selector}' lỗi: {e}", level="warn")
                raise

    # ------------------------------- flows -------------------------------

    def flow(self, kind: str) -> dict:
        """Cấu hình một flow (``text`` / ``image`` / ``video`` / ``select_model``)."""
        return self.flows.get(kind) or {}

    def has_flow(self, kind: str) -> bool:
        return kind in self.flows

    def flow_prompt(self, kind: str) -> dict:
        return self.flow(kind).get("prompt") or self.prompt_cfg

    def flow_response(self, kind: str) -> dict:
        return self.flow(kind).get("response") or {}

    def flow_done_signal(self, kind: str) -> dict:
        return self.flow_response(kind).get("done_signal") or self.ds or {}

    async def _apply_mode(self, page, capability: str) -> None:
        """Tương thích ngược: `capability` cũ → flow tương ứng."""
        await self._enter_flow(page, flows.CAPABILITY_FLOW.get(capability, "image"))

    async def _enter_flow(self, page, kind: str) -> None:
        """Đưa trang về đúng chế độ của flow trước khi nhập prompt.

        Nhiều web chat dùng chung một URL và chuyển giữa Chat / Image / Video
        bằng dropdown hoặc tab, nên mỗi flow mang sẵn chuỗi `action` ghi được
        lúc người dùng bấm. Không khai báo `action` thì không làm gì — trang
        vốn đã ở đúng chế độ.
        """
        action = str(self.flow(kind).get("action") or "")
        if not action:
            return
        selector = str(self.flow(kind).get("selector") or self._select_model_selector)
        if selector:
            try:
                await page.locator(selector).first.wait_for(state="visible", timeout=8000)
            except Exception:
                pass
        await self._exec_action_steps(page, action)

    async def _select_model(self, page, model: dict | None) -> None:
        """Chạy phần dạo đầu chung rồi đường bấm riêng của model.

        `flows.select_model.action` là thao tác dùng chung (mở dropdown model);
        `models[].action` là đường bấm riêng tới đúng model đó. Tách ra vì một
        site chỉ có một cách mở dropdown nhưng mỗi model một option.
        """
        if self._select_model_action:
            if self._select_model_selector:
                try:
                    await page.locator(self._select_model_selector).first.wait_for(
                        state="visible", timeout=8000)
                except Exception:
                    pass
            await self._exec_action_steps(page, self._select_model_action)
        if model is not None and model.get("action"):
            await self._exec_action_steps(page, str(model["action"]),
                                          str(model.get("value") or model["id"]))

    async def _acquire_page(self, ctx_key: str, storage_state, headed: bool):
        """Lấy tab để chạy request, theo chế độ đang bật.

        `storage_state` (mặc định): một context riêng cho mỗi ctx_key, y như cũ.
        `profile`: một persistent context dùng chung cho nhiều recipe, mỗi
        recipe một tab — nên các recipe khác nhau chạy song song được. Cả hai
        engine đều vào được đường này (cloak mở profile bằng
        `launch_persistent_context_async`); chỉ request headed thủ công là rơi
        về cách cũ vì nó cần cửa sổ riêng.
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
        out: list[ModelInfo] = []
        for m in self._recipe["models"]:
            caps = flows.capabilities_of(m)
            # ModelInfo.capability là một chuỗi: giữ "both" cho cặp chat+image
            # (nghĩa cũ, client đang đọc), còn lại nối bằng dấu phẩy.
            if caps == {"chat", "image"}:
                cap = "both"
            else:
                cap = ",".join(sorted(caps))
            out.append(ModelInfo(id=f"{self.slug}/{m['id']}", slug=self.slug, capability=cap))
        return out

    def _model_flows(self) -> set[str]:
        out: set[str] = set()
        for m in self._recipe.get("models") or []:
            if isinstance(m, dict):
                out |= flows.flows_of(m)
        return out

    def supports_image(self) -> bool:
        return "image" in self._model_flows() or self.has_flow("image")

    def supports_video(self) -> bool:
        return "video" in self._model_flows() or self.has_flow("video")

    def supported_flows(self) -> list[str]:
        """Flow recipe này chạy được — UI ghi thao tác đọc để biết còn thiếu gì."""
        return flows.ordered_flows(self.flows)

    def model_spec(self, model_id: str) -> dict:
        """Khối `models[]` của một model. `model_id` nhận cả `slug/id` lẫn `id`."""
        wanted = model_id.split("/", 1)[1] if "/" in model_id else model_id
        for m in self._recipe.get("models") or []:
            if isinstance(m, dict) and m.get("id") == wanted:
                return m
        return {}

    def flow_for_model(self, model_id: str) -> str:
        """Flow mà model này chạy — chọn model chính là chọn flow.

        `models[].flow` thắng; không khai thì suy từ `capability`. Trả về flow
        recipe thật sự có, nếu không thì `text` — model trỏ vào flow chưa khai
        đã bị `validate_flows` chặn từ lúc lưu, đây chỉ là chốt chặn cuối cho
        recipe cũ nạp từ đĩa trước khi có kiểm tra đó.
        """
        for name in flows.ordered_flows(flows.flows_of(self.model_spec(model_id))):
            if self.has_flow(name):
                return name
        return "text"

    # ------------------------------- media (image/video) -------------------------------
    # Ảnh và video khác nhau ở selector và cách đọc file, phần còn lại (chờ
    # xong, bấm nút copy, đổi sang b64) giống hệt nhau nên dùng chung code.
    # Flow đang chạy đi qua tham số `flow`, KHÔNG giữ trên self: một instance
    # provider phục vụ nhiều request song song (nhiều account) nên state dùng
    # chung sẽ bị request sau đè lên request trước.

    def _media_response(self, flow: str = "image") -> dict:
        return self.flow_response(flow) or self.response_cfg

    def _media_fallback_selector(self, flow: str = "image") -> str:
        """Khối tin nhắn để dò ảnh/video khi flow không khai báo media_selector."""
        return str(self._media_response(flow).get("last_message_selector")
                   or self.response_cfg.get("last_message_selector") or "")

    def _image_selector(self, flow: str = "image") -> str:
        resp = self._media_response(flow)
        return str(resp.get("media_selector") or resp.get("image_selector") or "")

    def _image_copy_selector(self, flow: str = "image") -> str:
        resp = self._media_response(flow)
        return str(resp.get("copy_selector") or resp.get("image_copy_selector") or "")

    def _image_copy_scope(self, flow: str = "image") -> str:
        resp = self._media_response(flow)
        return str(resp.get("copy_scope") or resp.get("image_copy_scope") or "after")

    def _image_copy_exclude(self, flow: str = "image") -> str:
        resp = self._media_response(flow)
        return str(resp.get("copy_exclude") or resp.get("image_copy_exclude") or "")

    async def _extract_media_srcs(self, page, limit: int, flow: str = "image") -> list[str]:
        """URL của ảnh (``flow=image``) hoặc video (``flow=video``) trong câu trả lời.

        Video hay để URL thật ở ``<source>`` con hoặc ``data-src`` chứ không phải
        ``video.src``, nên nhánh JS đọc cả hai; ảnh thì thêm đường
        ``background-image`` vì nhiều site render ảnh kết quả bằng CSS.
        """
        tag = "video" if flow == "video" else "img"
        sel = self._image_selector(flow)
        if sel:
            srcs = await page.evaluate(
                r"""([sel, tag]) => {
                    const srcOf = (n) => {
                        let src = n.getAttribute('src') || n.getAttribute('data-src') || '';
                        if (!src && n.tagName.toLowerCase() === tag) src = n.currentSrc || n.src || '';
                        if (!src) {
                            const source = n.querySelector && n.querySelector('source');
                            if (source) src = source.getAttribute('src') || source.src || '';
                        }
                        if (!src && tag === 'img') {
                            const bg = getComputedStyle(n).backgroundImage;
                            const m = bg && bg.match(/url\(["']?(.*?)["']?\)/);
                            if (m) src = m[1];
                        }
                        return src;
                    };
                    const nodes = Array.from(document.querySelectorAll(sel));
                    const out = [];
                    for (const n of nodes) {
                        const src = srcOf(n);
                        if (src && !out.includes(src)) out.push(src);
                        if (n.tagName.toLowerCase() !== tag) {
                            for (const inner of n.querySelectorAll(tag)) {
                                const s = srcOf(inner);
                                if (s && !out.includes(s)) out.push(s);
                            }
                        }
                    }
                    return out;
                }""",
                [sel, tag],
            )
            return [str(s) for s in (srcs or [])][:limit]
        # fallback: tìm mọi <img>/<video> trong khối tin nhắn cuối
        fallback = self._media_fallback_selector(flow)
        if not fallback:
            return []
        srcs = await page.evaluate(
            r"""([sel, tag]) => {
                const els = document.querySelectorAll(sel);
                if (!els.length) return [];
                const el = els[els.length - 1];
                const nodes = Array.from(el.querySelectorAll(tag));
                if (!nodes.length && el.tagName.toLowerCase() === tag) nodes.push(el);
                return nodes.map(n => {
                    if (n.currentSrc || n.src) return n.currentSrc || n.src;
                    const source = n.querySelector('source');
                    return (source && (source.src || source.getAttribute('src'))) || n.getAttribute('src') || '';
                }).filter(Boolean);
            }""",
            [fallback, tag],
        )
        return [str(s) for s in (srcs or [])][:limit]

    async def _extract_image_srcs(self, page, limit: int) -> list[str]:
        return await self._extract_media_srcs(page, limit, "image")

    async def _wait_for_media(self, page, n: int, deadline: float,
                              flow: str = "image") -> list[str]:
        """Chờ đủ n ảnh/video *đã tải xong* (bỏ qua phần tử hỏng hoặc đang tải).

        Ảnh xét ``complete && naturalWidth``; video xét ``readyState`` — có
        metadata là đủ, không chờ tải hết vì file video thường rất nặng.
        """
        tag = "video" if flow == "video" else "img"
        sel = self._image_selector(flow)
        fallback = self._media_fallback_selector(flow)
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(f"recipe '{self.slug}' {flow} timeout")
            srcs = await self._extract_media_srcs(page, n, flow)
            if len(srcs) >= n:
                loaded = await page.evaluate(
                    r"""([sel, fallback, tag]) => {
                        const ready = (n) => {
                            const t = n.tagName.toLowerCase();
                            if (t === 'img') return n.complete && n.naturalWidth > 0;
                            if (t === 'video') return n.readyState >= 1 || !!n.currentSrc;
                            return true;
                        };
                        const check = (nodes) => nodes.filter(ready).length;
                        if (sel) return check(Array.from(document.querySelectorAll(sel)).flatMap(n => {
                            if (n.tagName.toLowerCase() === tag) return [n];
                            return Array.from(n.querySelectorAll(tag));
                        }));
                        const els = document.querySelectorAll(fallback);
                        if (!els.length) return 0;
                        return check(Array.from(els[els.length-1].querySelectorAll(tag)));
                    }""",
                    [sel, fallback, tag],
                ) if sel else len(srcs)
                # nhánh sel trả về số phần tử đã tải xong; nhánh fallback đã đếm
                # sẵn qua srcs nên chấp nhận luôn.
                if not isinstance(loaded, int) or loaded >= n:
                    return srcs[:n]
            await asyncio.sleep(0.7)

    async def _wait_for_images(self, page, n: int, deadline: float) -> list[str]:
        return await self._wait_for_media(page, n, deadline, "image")

    async def _wait_for_image_copy_buttons(self, page, n: int, deadline: float,
                                           flow: str = "image") -> bool:
        """Đợi n nút copy ảnh xuất hiện và khả dụng (phân biệt với nút copy response)."""
        sel = self._image_copy_selector(flow)
        if not sel:
            return True
        scope = self._image_copy_scope(flow)
        exclude = self._image_copy_exclude(flow)
        img_sel = self._image_selector(flow)
        fallback = self._media_fallback_selector(flow)
        while True:
            if time.monotonic() > deadline:
                return False
            try:
                count = await page.evaluate(
                    r"""([btnSel, scope, excludeSel, imgSel, fallback]) => {
                        let btns;
                        try { btns = Array.from(document.querySelectorAll(btnSel)); } catch(e) { return 0; }
                        const usable = btns.filter(b => {
                          if (b.disabled || b.getAttribute('aria-disabled') === 'true') return false;
                          if (excludeSel) { try { if (b.closest(excludeSel)) return false; } catch(e) {} }
                          if (!b.getClientRects().length) return false;
                          const st = getComputedStyle(b);
                          if (st.visibility === 'hidden' || st.display === 'none') return false;
                          return true;
                        });
                        if (!usable.length) return 0;
                        if (scope === 'page') return usable.length;
                        // lọc theo ảnh: nút phải nằm trong hoặc sau container ảnh
                        let scopeNodes = [];
                        if (imgSel) scopeNodes = Array.from(document.querySelectorAll(imgSel));
                        else if (fallback) {
                          const els = document.querySelectorAll(fallback);
                          if (els.length) scopeNodes = [els[els.length-1]];
                        }
                        if (!scopeNodes.length) return usable.length;
                        // đếm số nút gắn với scopeNodes
                        let matched = 0;
                        for (const b of usable) {
                          for (const sc of scopeNodes) {
                            if (sc.contains(b)) { matched++; break; }
                            if (scope === 'after' && (sc.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)) { matched++; break; }
                          }
                        }
                        return matched;
                    }""",
                    [sel, scope, exclude, img_sel, fallback],
                )
                if int(count or 0) >= n:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)

    async def _copy_single_image(self, page, index: int, flow: str = "image") -> dict | None:
        """Bấm nút copy ảnh/video thứ index và đọc clipboard. Trả về {b64} | {text} | None."""
        sel = self._image_copy_selector(flow)
        if not sel:
            return None
        parsed = urlsplit(page.url)
        try:
            await page.context.grant_permissions(
                ["clipboard-read", "clipboard-write"], origin=f"{parsed.scheme}://{parsed.netloc}")
        except Exception:
            pass
        # xoá clipboard trước khi bấm để không nhầm ảnh cũ
        try:
            await page.evaluate("navigator.clipboard.writeText('')")
        except Exception:
            pass
        clicked = await page.evaluate(
            r"""([btnSel, idx, scope, excludeSel, imgSel, fallback]) => {
                let btns;
                try { btns = Array.from(document.querySelectorAll(btnSel)); } catch(e) { return false; }
                const usable = btns.filter(b => {
                  if (b.disabled || b.getAttribute('aria-disabled') === 'true') return false;
                  if (excludeSel) { try { if (b.closest(excludeSel)) return false; } catch(e) {} }
                  if (!b.getClientRects().length) return false;
                  const st = getComputedStyle(b);
                  return st.visibility !== 'hidden' && st.display !== 'none';
                });
                // lọc theo scope nếu có imgSel/fallback
                let filtered = usable;
                if (scope !== 'page') {
                  let scopeNodes = [];
                  if (imgSel) scopeNodes = Array.from(document.querySelectorAll(imgSel));
                  else if (fallback) {
                    const els = document.querySelectorAll(fallback);
                    if (els.length) scopeNodes = [els[els.length-1]];
                  }
                  if (scopeNodes.length) {
                    filtered = usable.filter(b => scopeNodes.some(sc =>
                      sc.contains(b) || (scope === 'after' && (sc.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING))
                    ));
                  }
                }
                const target = filtered[idx];
                if (!target) return false;
                target.click();
                return true;
            }""",
            [sel, index, self._image_copy_scope(flow), self._image_copy_exclude(flow),
             self._image_selector(flow), self._media_fallback_selector(flow)],
        )
        if not clicked:
            return None
        await asyncio.sleep(0.4)
        # đọc clipboard: ưu tiên image blob, rồi text
        try:
            result = await page.evaluate(
                r"""async () => {
                    const toB64 = async (blob) => {
                      const buf = await blob.arrayBuffer();
                      const bytes = new Uint8Array(buf);
                      let binary = '';
                      for (let i=0;i<bytes.length;i++) binary += String.fromCharCode(bytes[i]);
                      return btoa(binary);
                    };
                    try {
                      // Thử clipboard.read (cần permission, có thể trả image)
                      if (navigator.clipboard.read) {
                        try {
                          const items = await navigator.clipboard.read();
                          for (const item of items) {
                            for (const type of item.types) {
                              if (type.startsWith('image/')) {
                                const blob = await item.getType(type);
                                const b64 = await toB64(blob);
                                return {b64, mime: type};
                              }
                            }
                          }
                        } catch(e) {}
                      }
                      // fallback text (có site copy URL ảnh)
                      try {
                        const t = await navigator.clipboard.readText();
                        if (t && t.trim()) return {text: t.trim()};
                      } catch(e) {}
                    } catch(e) { return {error: String(e)}; }
                    return null;
                }""",
            )
            if not result:
                return None
            if result.get("b64"):
                return {"b64_json": str(result["b64"]), "mime": result.get("mime")}
            if result.get("text"):
                txt = str(result["text"]).strip()
                # nếu clipboard trả URL/data-uri thì giữ nguyên
                if txt.startswith("data:"):
                    comma = txt.find(",")
                    return {"b64_json": txt[comma+1:] if comma != -1 else txt}
                if txt.startswith("http"):
                    return {"url": txt}
                # có thể trả base64 trần
                if len(txt) > 100 and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=" for c in txt[:200]):
                    return {"b64_json": txt}
                return {"url": txt}
        except Exception as e:
            applog.log(f"recipe: '{self.slug}' đọc clipboard ảnh {index} lỗi: {e}", level="warn")
        return None

    async def _copy_images_via_buttons(self, page, n: int, deadline: float,
                                       flow: str = "image") -> list[dict] | None:
        """Thử copy n ảnh/video qua nút copy riêng. Trả None nếu không đủ."""
        sel = self._image_copy_selector(flow)
        if not sel:
            return None
        # đợi nút xuất hiện
        ok = await self._wait_for_image_copy_buttons(page, n, deadline, flow)
        if not ok:
            applog.log(f"recipe: '{self.slug}' không thấy {n} nút copy ảnh ({sel}) trước deadline", level="warn")
            return None
        out: list[dict] = []
        for i in range(n):
            # deadline tổng, bỏ qua ảnh lẻ nếu quá hạn
            if time.monotonic() > deadline:
                break
            item = await self._copy_single_image(page, i, flow)
            if item is None:
                # thử lại một lần sau khi chờ ngắn
                await asyncio.sleep(0.6)
                item = await self._copy_single_image(page, i, flow)
            if item is None:
                applog.log(f"recipe: '{self.slug}' không copy được ảnh {i+1}/{n} qua nút {sel}", level="warn")
                return None
            out.append(item)
            await asyncio.sleep(0.2)
        return out if len(out) == n else None

    async def _image_to_b64(self, page, src: str) -> str:
        if src.startswith("data:"):
            # data:image/png;base64,....
            comma = src.find(",")
            return src[comma + 1:] if comma != -1 else src
        # Try to fetch via browser context (has cookies/auth) and encode
        try:
            b64 = await page.evaluate(
                r"""async (url) => {
                    try {
                        const r = await fetch(url, {credentials: 'include'});
                        if (!r.ok) return null;
                        const buf = await r.arrayBuffer();
                        const bytes = new Uint8Array(buf);
                        let binary = '';
                        for (let i=0;i<bytes.length;i++) binary += String.fromCharCode(bytes[i]);
                        return btoa(binary);
                    } catch(e) { return null; }
                }""",
                src,
            )
            if b64:
                return str(b64)
        except Exception:
            pass
        # Fallback: httpx (may miss auth)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                r = await client.get(src)
                r.raise_for_status()
                return base64.b64encode(r.content).decode()
        except Exception:
            pass
        # last resort: return url itself, caller will fallback to url mode
        return ""

    async def generate_images(self, prompt: str, n: int = 1, size: str = "1024x1024",
                              headed: bool | None = None,
                              target_account_id: int | None = None,
                              assignment: "Assignment | None" = None,
                              response_format: str = "b64_json",
                              **kwargs) -> list[dict]:
        return await self._generate_media("image", prompt, n, size, headed, target_account_id,
                                          assignment, response_format, **kwargs)

    async def generate_videos(self, prompt: str, n: int = 1, size: str = "1024x1024",
                              headed: bool | None = None,
                              target_account_id: int | None = None,
                              assignment: "Assignment | None" = None,
                              response_format: str = "url",
                              **kwargs) -> list[dict]:
        """Chạy flow video đã ghi. Mặc định trả `url` vì video base64 rất nặng.

        Chưa có endpoint OpenAI gọi tới: API video của OpenAI là job bất đồng bộ
        (tạo job -> poll -> tải file), sẽ gắn ở lớp trên sau.
        """
        if not self.has_flow("video"):
            raise NotImplementedError(
                f"recipe '{self.slug}' chưa ghi thao tác generate video")
        return await self._generate_media("video", prompt, n, size, headed, target_account_id,
                                          assignment, response_format, **kwargs)

    async def _generate_media(self, flow: str, prompt: str, n: int, size: str,
                              headed: bool | None, target_account_id: int | None,
                              assignment: "Assignment | None", response_format: str,
                              **kwargs) -> list[dict]:
        owned = assignment is None
        if owned:
            assignment = await self.assign(target_account_id)
        try:
            return await self._run_media(flow, prompt, n, size, assignment, headed,
                                         response_format, **kwargs)
        finally:
            if owned:
                assignment.release()

    async def _run_images(self, prompt: str, n: int, size: str, assignment: "Assignment",
                          headed: bool | None, response_format: str, **kwargs) -> list[dict]:
        return await self._run_media("image", prompt, n, size, assignment, headed,
                                     response_format, **kwargs)

    async def _run_media(self, flow: str, prompt: str, n: int, size: str,
                         assignment: "Assignment", headed: bool | None,
                         response_format: str, **kwargs) -> list[dict]:
        """Chạy một flow sinh media (ảnh/video) tới khi có đủ n kết quả.

        Cùng khung với `_run` (chat): vào đúng chế độ -> chọn model -> gõ prompt
        -> gửi. Khác ở chỗ kết quả là file chứ không phải chữ, nên chờ theo
        `media_selector` / nút copy thay vì done_signal của text.
        """
        prompt_cfg = self.flow_prompt(flow)
        ds = self.flow_done_signal(flow)
        response_cfg = self.flow_response(flow) or self.response_cfg
        target_profile = assignment.profile
        storage_state = assignment.storage_state
        ctx_key = assignment.ctx_key
        if assignment.headed is None:
            assignment.headed = self.resolve_headed(headed, target_profile)
        effective_headed = assignment.headed
        timeout_ms = int(ds.get("timeout_ms", 120000))
        capture_html = bool(response_cfg.get("capture_html", self._capture_html))
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
                box = page.locator(prompt_cfg["input_selector"]).first
                await self._wait_chat_ready(page, box)
                await _sleep_ms(self._input_delay_ms)
                # Chuyển chế độ TRƯỚC khi chọn model: dropdown model của nhiều
                # site chỉ liệt kê model hợp lệ cho chế độ đang bật.
                await self._enter_flow(page, flow)
                model_id = kwargs.get("model_id") or ""
                catalog = [m for m in self._recipe.get("models") or [] if isinstance(m, dict)]
                model = next((item for item in catalog if item.get("id") == model_id), None)
                if model is None:
                    # Không chỉ đích danh thì lấy model làm được đúng việc này —
                    # models[0] có thể là model chat và bấm nhầm sang chế độ chat.
                    model = next((m for m in catalog if flow in flows.flows_of(m)), None)
                await self._select_model(page, model)
                if prompt_cfg.get("input_mode", "fill") == "type":
                    await box.click()
                    await box.type(prompt)
                else:
                    await box.fill(prompt)
                submit = prompt_cfg.get("submit", "Enter")
                if submit.startswith("click:"):
                    await page.click(submit.split(":", 1)[1])
                else:
                    await box.press("Enter")
                # chờ media xuất hiện (media và nút copy là 2 tập riêng)
                srcs = await self._wait_for_media(page, n, deadline, flow)
                assignment.conversation_url = _page_url(page)
                if capture_html:
                    try:
                        sel = (self._image_selector(flow)
                               or self._media_fallback_selector(flow) or "body")
                        html = await page.evaluate("(sel)=>{ const els=document.querySelectorAll(sel); const el=els[els.length-1]; return el?el.outerHTML:null; }", sel)
                        assignment.html = html
                        self.last_response_html = html
                    except Exception:
                        pass
                # Ưu tiên copy qua nút riêng cho từng kết quả (mỗi cái 1 nút)
                if self._image_copy_selector(flow):
                    copied = await self._copy_images_via_buttons(page, n, deadline, flow)
                    if copied is not None and len(copied) == n:
                        out = await self._format_media(page, copied, response_format)
                        if len(out) == n:
                            return out
                        applog.log(f"recipe: '{self.slug}' copy {flow} trả thiếu {len(out)}/{n}, "
                                   "fallback sang src", level="warn")
                    else:
                        applog.log(f"recipe: '{self.slug}' không copy đủ {n} {flow} qua nút, "
                                   "fallback sang src", level="warn")
                # Fallback: lấy trực tiếp từ src / background-image
                out: list[dict] = []
                for src in srcs[:n]:
                    if response_format == "url":
                        out.append({"url": src})
                    else:
                        b64 = await self._image_to_b64(page, src)
                        out.append({"b64_json": b64} if b64 else {"url": src})
                return out
            finally:
                if assignment.conversation_url is None:
                    assignment.conversation_url = _page_url(page)
                if not self._keep_context:
                    await self._release_ctx(ctx_key)

    async def _format_media(self, page, copied: list[dict], response_format: str) -> list[dict]:
        """Đưa kết quả đọc từ clipboard về đúng định dạng client xin."""
        out: list[dict] = []
        for item in copied:
            if response_format == "url":
                if item.get("url"):
                    out.append({"url": item["url"]})
                elif item.get("b64_json"):
                    # có b64 nhưng client xin url -> vẫn trả b64, hơn là trả rỗng
                    out.append({"b64_json": item["b64_json"]})
                else:
                    out.append(item)
            elif item.get("b64_json"):
                out.append({"b64_json": item["b64_json"]})
            elif item.get("url"):
                b64 = await self._image_to_b64(page, item["url"])
                out.append({"b64_json": b64} if b64 else {"url": item["url"]})
            else:
                out.append(item)
        return out

    def _last_message_selector(self, flow: str = "text") -> str:
        """Khối trả lời của một flow; rơi về cấu hình phẳng như recipe đời cũ.

        `__init__` dựng `self.response_cfg` TỪ chính flow `text`, nên với recipe
        cũ hai đường này cho ra cùng một chuỗi — flow tự đặt tên mới cần tới
        nhánh đầu.
        """
        return str((self.flow_response(flow) or self.response_cfg)
                   .get("last_message_selector") or "")

    async def _reply(self, page, flow: str = "text") -> tuple[str | None, str | None]:
        """Đọc reply dưới dạng Markdown và, khi bật, outerHTML gốc.

        Trả ``(None, None)`` khi KHÔNG đọc được vì trang đang điều hướng — khác
        hẳn ``("", None)`` nghĩa là đọc được nhưng chưa có chữ nào. Vòng poll
        phải phân biệt hai cái: coi lỗi điều hướng thành chuỗi rỗng sẽ xoá mất
        ``last``, rồi lần đọc sau text quay lại đầy đủ và bị yield lại từ đầu —
        client nhận nội dung nhân đôi.
        """
        sel = self._last_message_selector(flow)
        result = await self._evaluate_reply(page, sel, flow)
        if result is None:
            return None, None
        return str(result[0] or ""), result[1]

    def _reply_flags(self, flow: str = "text") -> tuple[bool, bool]:
        """`(capture_html, structured_markdown)` của một flow.

        Cả hai nằm trong `_TEXT_RESPONSE_KEYS` nên flow khai riêng được; đọc
        `self._*` phẳng ở đây sẽ khiến flow tự đặt tên khai `format: markdown`
        bị đọc như text thường.
        """
        resp = self.flow_response(flow) or self.response_cfg
        capture = bool(resp.get("capture_html", self._capture_html))
        fmt = resp.get("format")
        markdown = fmt == "markdown" if fmt is not None else self._structured_markdown
        return capture, markdown

    async def _evaluate_reply(self, page, sel, flow: str = "text"):
        """Chạy JS đọc reply; None khi context bị huỷ giữa chừng.

        Cùng lý do với `_copy_button_ready`: page.goto / SPA điều hướng đúng nhịp
        poll thì `page.evaluate` ném "Execution context was destroyed" và giết cả
        request. dola đổi URL ba lần ngay sau khi gửi prompt
        (/chat?channel=g -> /chat/local_… -> /chat/<id>) nên đây là chuyện xảy ra
        thật, không phải phòng xa. Nuốt lỗi, vòng poll sau hỏi lại, hết giờ đã có
        `deadline` lo.
        """
        try:
            return await page.evaluate(
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
                [sel, *self._reply_flags(flow)],
            )
        except Exception:
            return None

    async def _reply_text(self, page, flow: str = "text") -> str:
        """Compatibility helper cho code/test ngoài module chỉ cần nội dung."""
        text, _ = await self._reply(page, flow)
        return text or ""

    async def _copy_button_ready(self, page, selector: str, scope: str,
                                 exclude: str, flow: str = "text") -> bool:
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
                [self._last_message_selector(flow), selector, scope, exclude],
            ))
        except Exception:
            # Trang đang điều hướng/đóng tab: coi như chưa xong, vòng poll sau
            # sẽ hỏi lại, hết giờ thì deadline lo.
            return False

    async def _copy_button_result(self, page, selector: str, scope: str,
                                  exclude: str, flow: str = "text") -> str:
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
                    else if (scope === "after") {
                      const after = usable.filter(b =>
                        msg.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
                      target = after[after.length - 1];
                    }
                 }
                 if (!target) return false;
                 target.click();
                 return true;
               }""",
            [self._last_message_selector(flow), selector, scope, exclude],
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
            async for delta in self._run(prompt, model_id, assignment, headed,
                                         self.flow_for_model(model_id)):
                yield delta
        finally:
            if owned:
                assignment.release()

    async def _run(self, prompt: str, model_id: str, assignment: "Assignment",
                   headed: bool | None, flow: str = "text") -> AsyncIterator[str]:
        # Cấu hình đọc theo flow đang chạy, không đọc `self.*` phẳng: một
        # instance provider phục vụ nhiều flow, ghi vào self là flow sau đè lên
        # flow trước. Với recipe đời cũ `flow_prompt("text")` / `flow_done_signal
        # ("text")` trả về đúng `self.prompt_cfg` / `self.ds`, nên hành vi không đổi.
        prompt_cfg = self.flow_prompt(flow)
        ds = self.flow_done_signal(flow)
        resp_cfg = self.flow_response(flow) or self.response_cfg
        structured_markdown = (resp_cfg.get("format") == "markdown"
                               if resp_cfg.get("format") is not None
                               else self._structured_markdown)
        target_profile = assignment.profile
        storage_state = assignment.storage_state
        ctx_key = assignment.ctx_key
        # Handler đã chốt và đã trả về trong header rồi thì phải chạy đúng cái
        # đó, không tự quyết lại — nếu không, header nói một đằng, cửa sổ một nẻo.
        if assignment.headed is None:
            assignment.headed = self.resolve_headed(headed, target_profile)
        effective_headed = assignment.headed
        timeout_ms = int(ds.get("timeout_ms", 120000))
        dtype = ds.get("type", "stable_text")
        # copy_button có tín hiệu dứt khoát nên chỉ cần chống nhiễu vài trăm ms,
        # không phải chờ hết khoảng "im lặng" dài như stable_text.
        quiet_ms = int(ds.get("quiet_ms", 600 if dtype == "copy_button" else 3000))
        copy_sel = str(ds.get("selector") or DEFAULT_COPY_BUTTON_SELECTOR)
        copy_scope = str(ds.get("scope") or "after")
        copy_exclude = str(ds.get("exclude") or "")
        use_copy_result = bool(ds.get("use_copy_result", False))
        # Selector nút copy sai (site đổi giao diện) mà không có lối thoát thì
        # MỌI request đều chạy tới timeout rồi hỏng — mất luôn câu trả lời đã
        # nhận đủ. Nên vẫn giữ đường lùi: text đứng yên đủ lâu thì chốt và ghi
        # log cảnh báo. Đặt `fallback_quiet_ms: 0` để tắt hẳn.
        copy_fallback_ms = int(ds.get("fallback_quiet_ms", 15000))
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
                box = page.locator(prompt_cfg["input_selector"]).first
                await self._wait_chat_ready(page, box)
                await _sleep_ms(self._input_delay_ms)
                model = next((item for item in self._recipe["models"]
                              if item["id"] == model_id), None)
                # Chuyển về chế độ chat trước, rồi mới chọn model: dropdown model
                # của nhiều site chỉ liệt kê model hợp lệ cho chế độ đang bật.
                await self._enter_flow(page, flow)
                await self._select_model(page, model)
                if prompt_cfg.get("input_mode", "fill") == "type":
                    await box.click()
                    await box.type(prompt)
                else:
                    await box.fill(prompt)
                submit = prompt_cfg.get("submit", "Enter")
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
                    text, reply_html = await self._reply(page, flow)
                    if text is None:
                        # Trang đang điều hướng nên chưa đọc được gì. Giữ nguyên
                        # `last` / `stable_since`: coi đây là "text đổi thành
                        # rỗng" sẽ reset đồng hồ im lặng và làm lần đọc sau yield
                        # lại toàn bộ câu trả lời từ đầu.
                        await asyncio.sleep(0.5)
                        continue
                    if reply_html is not None:
                        captured_html = reply_html
                        self.last_response_html = reply_html
                    if text != last:
                        if (not use_copy_result and not structured_markdown and text.startswith(last)
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
                        count = await page.locator(ds["selector"]).count()
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
                            if not copied:
                                # `_copy_button_result` trả "" mà KHÔNG ném khi
                                # không bấm được nút hoặc clipboard rỗng. Rơi về
                                # text DOM thì request vẫn chạy, nhưng nội dung
                                # trả ra không còn đúng định dạng của nút Copy —
                                # im lặng ở đây nghĩa là selector gãy bao lâu
                                # cũng không ai biết.
                                applog.log(
                                    f"recipe: '{self.slug}' bật use_copy_result nhưng không lấy "
                                    f"được nội dung từ nút Copy — đang trả text DOM, KHÔNG đúng "
                                    f"format Copy; kiểm tra response.done_signal.selector",
                                    level="warn")
                            yield copied or last
                        elif structured_markdown:
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
