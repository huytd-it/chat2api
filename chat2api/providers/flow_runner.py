"""FlowRunner — một flow graph chạy như một BrowserRecipe.

Thiết kế tương thích (quyết định 5B + giữ luồng chat):

- Mỗi flow (``data/flows/<slug>/flow.json``) được ``flow_compiler`` dựng
  thành dict recipe chuẩn, rồi ``FlowRunner`` kế thừa toàn bộ
  ``BrowserRecipe`` (accounts, pool/page, selectors, done_signal, media…).
- Router nạp flows **sau** recipes nên flow cùng slug sẽ **ghi đè** recipe cũ
  — chat model id giữ nguyên, Combos/Test-targets/Sessions/Domains không gãy.
- ``_run`` / ``_run_media`` được override để đi **từng node theo edges**
  (quyết định 2B + 11: DAG thật, rẽ nhánh condition), thay vì chạy nguyên khối.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import AsyncIterator

from .. import applog
from ..flow_compiler import compile_flow
from ..flow_executor import (
    FlowContext,
    FlowNodeError,
    FlowRunnerMixin,
    _walk_media,
    _walk_text_deltas,
    entry_node_id,
)
from ..prompt import flatten_messages
from .browser_recipe import (
    DEFAULT_COPY_BUTTON_SELECTOR,
    BrowserRecipe,
    TrialLimitExceeded,
    _page_url,
    _sleep_ms,
)


class FlowRunner(FlowRunnerMixin, BrowserRecipe):
    """BrowserRecipe chạy bằng graph. ``flow`` là dict flow.json đã load."""

    def __init__(self, flow: dict, flows_dir: Path, pool, headed: bool = False,
                 accounts_root: Path | None = None):
        if not isinstance(flow, dict):
            raise ValueError("flow phải là một mapping")
        self.flow_doc = dict(flow)
        self.flow_slug = str(flow.get("slug") or "").strip().lower()
        self.flow_kind = str(flow.get("kind") or "text")
        self.flow_type_name = str(flow.get("flow_type") or flow.get("type") or "text")
        recipe = compile_flow({**flow, "slug": self.flow_slug})
        # base_dir riêng cho flow để storage_state tương đối (nếu có) không
        # lẫn với recipe. accounts_root vẫn là recipes_dir để dùng chung kho
        # account theo domain (tương thích test-targets).
        base_dir = Path(flows_dir) / self.flow_slug
        if accounts_root is None:
            # Layout mặc định: ./recipes và ./data/flows cùng dưới một cwd.
            accounts_root = Path(flows_dir).parent.parent / "recipes"
        super().__init__(recipe, base_dir, pool, headed=headed,
                         accounts_root=Path(accounts_root))
        # Giữ slug = flow slug (ghi đè recipe cùng tên trong router).
        self.slug = self.flow_slug

    # ------------------------- defaults cho executor -------------------------

    def _flow_fill_defaults(self) -> dict:
        return {}

    def _flow_submit_defaults(self) -> dict:
        return {}

    def _flow_done_defaults(self) -> dict:
        ds = dict(self.ds or {})
        ds.setdefault("type", "stable_text")
        return ds

    def _flow_media_defaults(self) -> dict:
        resp = dict(self.response_cfg or {})
        out: dict = {}
        for key in ("media_selector", "copy_selector", "copy_scope",
                    "copy_exclude", "done_signal", "capture_html",
                    "last_message_selector"):
            if resp.get(key) is not None:
                out[key] = resp[key]
        return out

    async def _flow_check_trial(self, ctx: FlowContext, params: dict) -> None:
        # Trial đã được enforce ở `assign()` (rotator ném TrialLimitExceeded).
        # Node này giữ để canvas hiển thị + cho phép đổi limit mà không cần
        # sửa account. V1: no-op khi assignment đã có.
        return None

    # ------------------------- poll helpers (tái dùng logic _run) -------------------------

    async def _poll_text_until_done(self, ctx: FlowContext, ds: dict) -> tuple[str, None]:
        """Chờ done_signal tới khi chốt, KHÔNG yield (node logic gọi)."""
        last = ""
        async for delta in self._flow_poll_deltas(ctx, ds):
            last += delta
        return ctx.text or last, None

    async def _flow_poll_deltas(self, ctx: FlowContext, ds: dict) -> AsyncIterator[str]:
        """Poll done_signal ở node chờ, yield delta tăng dần như `_run`.

        Sao chép đúng quy tắc yield của `BrowserRecipe._run`: text thường thì
        đẩy delta từng chặng; `use_copy_result` / `format: markdown` thì giữ
        tới lúc chốt mới yield (node `copy-button` / `extract-text` xử tiếp).
        """
        page = ctx.page
        flow = self.flow_kind if self.flow_kind in self.flows else "text"
        resp_cfg = self.flow_response(flow) or self.response_cfg
        structured_markdown = (resp_cfg.get("format") == "markdown"
                               if resp_cfg.get("format") is not None
                               else self._structured_markdown)
        timeout_ms = int(ds.get("timeout_ms", 120000))
        dtype = ds.get("type", "stable_text")
        quiet_ms = int(ds.get("quiet_ms", 600 if dtype == "copy_button" else 3000))
        copy_sel = str(ds.get("selector") or DEFAULT_COPY_BUTTON_SELECTOR)
        copy_scope = str(ds.get("scope") or "after")
        copy_exclude = str(ds.get("exclude") or "")
        use_copy_result = bool(ds.get("use_copy_result", False))
        copy_fallback_ms = int(ds.get("fallback_quiet_ms", 15000))
        deadline = time.monotonic() + timeout_ms / 1000
        ctx.deadline = deadline
        stable_since = None
        copy_since = None
        last = ""
        prompt = ctx.prompt
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(f"flow '{self.slug}' timeout sau {timeout_ms}ms")
            text, reply_html = await self._reply(page, flow)
            if text is None:
                await asyncio.sleep(0.5)
                continue
            if reply_html is not None and ctx.assignment is not None:
                ctx.assignment.html = reply_html
            if text != last:
                if (not use_copy_result and not structured_markdown
                        and text.startswith(last) and text.strip() != prompt.strip()):
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
                done = (copy_since is not None
                        and (time.monotonic() - copy_since) * 1000 >= quiet_ms
                        and quiet_for >= quiet_ms)
                if (not done and copy_fallback_ms and has_reply
                        and quiet_for >= copy_fallback_ms):
                    applog.log(
                        f"flow: '{self.slug}' không thấy nút copy sau "
                        f"{copy_fallback_ms}ms text đứng yên — chốt theo stable_text",
                        level="warn")
                    done = True
            else:
                count = await page.locator(ds["selector"]).count()
                appear = dtype == "selector_appear"
                done = (((count > 0) == appear) and stable_since is not None
                        and quiet_for >= min(quiet_ms, 1000))
            if done:
                if ctx.assignment is not None:
                    ctx.assignment.conversation_url = _page_url(page)
                ctx.text = last
                if use_copy_result:
                    # Để node `copy-button` yield nội dung clipboard (đúng
                    # `BrowserRecipe._run`); yield `last` ở đây sẽ nhân đôi.
                    return
                if structured_markdown:
                    yield last
                return
            await asyncio.sleep(0.5)

    async def _reply_text_and_html(self, page, selector: str, params: dict):
        flow = self.flow_kind if self.flow_kind in self.flows else "text"
        # Tạm trỏ _last_message_selector về selector của node bằng cách gọi
        # _evaluate_reply trực tiếp.
        result = await self._evaluate_reply(page, selector, flow)
        if result is None:
            return "", None
        return str(result[0] or ""), result[1]

    async def _copy_text_result(self, page, params: dict) -> str:
        flow = self.flow_kind if self.flow_kind in self.flows else "text"
        ds = self._flow_done_defaults()
        for key in ("selector", "scope", "exclude"):
            if params.get(key) is not None:
                ds[key] = params[key]
        copy_sel = str(ds.get("selector") or DEFAULT_COPY_BUTTON_SELECTOR)
        copy_scope = str(ds.get("scope") or "after")
        copy_exclude = str(ds.get("exclude") or "")
        try:
            return await self._copy_button_result(page, copy_sel, copy_scope,
                                                  copy_exclude, flow)
        except Exception as error:
            applog.log(f"flow: '{self.slug}' không đọc được kết quả từ nút Copy: "
                       f"{error}; dùng text từ DOM", level="warn")
            return ""

    async def _copy_media_via_buttons(self, page, n: int, deadline: float,
                                      copy_selector: str, params: dict) -> list[dict] | None:
        # Tái dùng _copy_images_via_buttons bằng cách tạm ghi đè response của
        # flow hiện tại? Đơn giản hơn: gọi trực tiếp _copy_single_image với
        # selector từ node qua evaluate tùy chỉnh — ở đây tái dùng logic bằng
        # cách set response tạm trên recipe compile (an toàn vì mỗi FlowRunner
        # phục vụ một flow, nhưng nhiều request song song → dùng lock ctx_key
        # đã giữ ở stream nên không đè nhau trong cùng tab).
        flow = self.flow_kind if self.flow_kind in self.flows else "image"
        sel = copy_selector or self._image_copy_selector(flow)
        if not sel:
            return None
        ok = await self._wait_for_image_copy_buttons(page, n, deadline, flow)
        if not ok:
            return None
        out: list[dict] = []
        for i in range(n):
            if time.monotonic() > deadline:
                break
            item = await self._copy_single_image(page, i, flow)
            if item is None:
                await asyncio.sleep(0.6)
                item = await self._copy_single_image(page, i, flow)
            if item is None:
                return None
            out.append(item)
            await asyncio.sleep(0.2)
        return out if len(out) == n else None

    # ------------------------- stream / generate (override) -------------------------

    async def stream(self, messages: list[dict], model_id: str,
                     headed: bool | None = None,
                     target_account_id: int | None = None,
                     assignment=None) -> AsyncIterator[str]:
        prompt = flatten_messages(messages)
        self.last_response_html = None
        owned = assignment is None
        if owned:
            assignment = await self.assign(target_account_id)
        try:
            async for delta in self._run_flow(prompt, assignment, headed):
                yield delta
        finally:
            if owned:
                assignment.release()

    async def _run_flow(self, prompt: str, assignment,
                        headed: bool | None) -> AsyncIterator[str]:
        flow = self.flow_doc
        start_id = entry_node_id(flow)
        target_profile = assignment.profile
        storage_state = assignment.storage_state
        ctx_key = assignment.ctx_key
        if assignment.headed is None:
            assignment.headed = self.resolve_headed(headed, target_profile)
        effective_headed = assignment.headed
        ds = self._flow_done_defaults()
        timeout_ms = int(ds.get("timeout_ms", 120000))
        ctx = FlowContext(prompt)
        ctx.assignment = assignment
        ctx.deadline = time.monotonic() + timeout_ms / 1000
        ctx.media_tag = "video" if self.flow_type_name == "video" else "img"
        async with self._lock_for(ctx_key), contextlib.AsyncExitStack() as stack:
            if target_profile is not None:
                await stack.enter_async_context(self.pool.hold(target_profile.name, ctx_key))
                page = await self.open_profile_page(target_profile, ctx_key, effective_headed)
            else:
                page = await self._acquire_page(ctx_key, storage_state, effective_headed)
            ctx.page = page
            try:
                async for delta in _walk_text_deltas(self, ctx, flow, start_id):
                    yield delta
            finally:
                if assignment.conversation_url is None:
                    assignment.conversation_url = _page_url(page)
                if not self._keep_context:
                    await self._release_ctx(ctx_key)

    async def generate_images(self, prompt: str, n: int = 1, size: str = "1024x1024",
                              headed: bool | None = None,
                              target_account_id: int | None = None,
                              assignment=None,
                              response_format: str = "b64_json",
                              **kwargs) -> list[dict]:
        owned = assignment is None
        if owned:
            assignment = await self.assign(target_account_id)
        try:
            return await self._run_media_flow(prompt, n, size, assignment, headed,
                                              response_format)
        finally:
            if owned:
                assignment.release()

    async def generate_videos(self, prompt: str, n: int = 1, size: str = "1024x1024",
                              headed: bool | None = None,
                              target_account_id: int | None = None,
                              assignment=None,
                              response_format: str = "url",
                              **kwargs) -> list[dict]:
        return await self.generate_images(prompt, n=n, size=size, headed=headed,
                                          target_account_id=target_account_id,
                                          assignment=assignment,
                                          response_format=response_format, **kwargs)

    async def _run_media_flow(self, prompt: str, n: int, size: str, assignment,
                              headed: bool | None, response_format: str) -> list[dict]:
        from ..flow_executor import _walk_media as walk_media

        flow = self.flow_doc
        start_id = entry_node_id(flow)
        target_profile = assignment.profile
        storage_state = assignment.storage_state
        ctx_key = assignment.ctx_key
        if assignment.headed is None:
            assignment.headed = self.resolve_headed(headed, target_profile)
        effective_headed = assignment.headed
        ds = self._flow_done_defaults()
        timeout_ms = int(ds.get("timeout_ms", 120000))
        ctx = FlowContext(prompt, n=n, size=size, response_format=response_format)
        ctx.assignment = assignment
        ctx.deadline = time.monotonic() + timeout_ms / 1000
        ctx.media_tag = "video" if self.flow_type_name == "video" else "img"
        async with self._lock_for(ctx_key), contextlib.AsyncExitStack() as stack:
            if target_profile is not None:
                await stack.enter_async_context(self.pool.hold(target_profile.name, ctx_key))
                page = await self.open_profile_page(target_profile, ctx_key, effective_headed)
            else:
                page = await self._acquire_page(ctx_key, storage_state, effective_headed)
            ctx.page = page
            try:
                await walk_media(self, ctx, flow, start_id)
                return ctx.media
            finally:
                if assignment.conversation_url is None:
                    assignment.conversation_url = _page_url(page)
                if not self._keep_context:
                    await self._release_ctx(ctx_key)

    # ------------------------- tương thích router/main -------------------------

    def supports_image(self) -> bool:
        if self.flow_type_name in ("image", "video"):
            return True
        return super().supports_image()

    def supports_video(self) -> bool:
        if self.flow_type_name == "video":
            return True
        return super().supports_video() if hasattr(super(), "supports_video") else False
