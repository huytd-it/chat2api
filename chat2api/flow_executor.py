"""Executor Flows: chạy graph từng node theo edges (DAG + rẽ nhánh condition).

Thiết kế (quyết định 2B):

- Mỗi flow con được ``flow_compiler.compile_flow`` dựng thành dict recipe,
  rồi ``FlowRunner`` (subclass ``BrowserRecipe``) cung cấp toàn bộ helpers
  browser đã kiểm chứng (account/assign, page/pool, done_signal, media, copy).
- Executor KHÔNG gọi ``_run`` nguyên khối. Nó đi theo ``nodes``/``edges`` từ
  node ``start``, mỗi node thực hiện đúng một thao tác browser/logic, fail thì
  dừng tại node đó kèm báo cáo (phục vụ preflight/run/debug từng node sau này).
- Node ``condition`` rẽ nhánh theo ``edges`` có ``sourceHandle``:
  ``"true"`` / ``"false"`` (fallback: edge không nhãn = đi tiếp).
- Ngữ cảnh chạy (``FlowContext``) giữ ``prompt``, ``page``, ``assignment``,
  biến ``vars`` cho ``set-variable``/``condition``/``eval-js``, và text/media
  thu được để node ``output`` chốt kết quả.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator

from . import applog
from .flow_compiler import compile_flow
from .prompt import flatten_messages


class FlowNodeError(RuntimeError):
    def __init__(self, node_id: str, node_type: str, message: str):
        super().__init__(f"[{node_id}:{node_type}] {message}")
        self.node_id = node_id
        self.node_type = node_type


class FlowContext:
    def __init__(self, prompt: str, n: int = 1, size: str = "1024x1024",
                 response_format: str = "b64_json"):
        self.prompt = prompt
        self.n = n
        self.size = size
        self.response_format = response_format
        self.vars: dict[str, Any] = {"prompt": prompt}
        self.page = None
        self.box = None
        self.assignment = None
        self.text = ""
        self.media: list[dict] = []
        self.visited: list[str] = []
        self.deadline: float = 0.0
        self.media_tag: str = "img"
        self.flow_kind: str = "text"

    def set(self, name: str, value: Any) -> None:
        self.vars[str(name)] = value


def order_nodes(flow: dict) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """``(nodes_by_id, outgoing)`` — edges nhóm theo node nguồn."""
    nodes = {n["id"]: n for n in (flow.get("nodes") or [])
             if isinstance(n, dict) and isinstance(n.get("id"), str)}
    outgoing: dict[str, list[dict]] = {}
    for edge in flow.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        src = edge.get("source")
        dst = edge.get("target")
        if src in nodes and dst in nodes:
            outgoing.setdefault(str(src), []).append(edge)
    return nodes, outgoing


def entry_node_id(flow: dict) -> str:
    for node in flow.get("nodes") or []:
        if isinstance(node, dict) and node.get("type") == "start":
            return str(node["id"])
    raise ValueError("flow thiếu node `start`")


def _params(node: dict) -> dict:
    params = node.get("params")
    return dict(params) if isinstance(params, dict) else {}


async def _sleep_ms(ms: int) -> None:
    if ms:
        await asyncio.sleep(ms / 1000)


class FlowRunnerMixin:
    """Các bước node tái dùng helpers của ``BrowserRecipe`` (runner cung cấp)."""

    async def _node_goto_url(self, ctx: FlowContext, params: dict) -> None:
        url = str(params.get("url") or "").strip()
        if not url:
            raise ValueError("goto-url thiếu params.url")
        page = ctx.page
        timeout_ms = int(params.get("timeout_ms") or 60000)
        await page.goto(url, wait_until="domcontentloaded",
                        timeout=min(timeout_ms, 60000))

    async def _node_wait_ready(self, ctx: FlowContext, params: dict) -> None:
        # Ô nhập ở node fill-input gần nhất phía sau; executor v1 chạy tuyến
        # tính nên box được resolve ở fill-input, còn đây chỉ chờ delay.
        await _sleep_ms(int(params.get("delay_ms") or 0))

    async def _node_new_chat(self, ctx: FlowContext, params: dict) -> None:
        page = ctx.page
        url = str(params.get("url") or "").strip()
        selector = str(params.get("selector") or "").strip()
        if url:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if selector:
            await page.click(selector, timeout=int(params.get("timeout_ms") or 20000))

    async def _node_action_sequence(self, ctx: FlowContext, params: dict) -> None:
        action = str(params.get("action") or "")
        if action:
            await self._exec_action_steps(ctx.page, action)  # type: ignore[attr-defined]

    async def _node_select_model(self, ctx: FlowContext, params: dict) -> None:
        prelude = str(params.get("prelude_action") or "")
        selector = str(params.get("selector") or "")
        model_action = str(params.get("model_action") or params.get("action") or "")
        if prelude:
            if selector:
                try:
                    await ctx.page.locator(selector).first.wait_for(
                        state="visible", timeout=8000)
                except Exception:
                    pass
            await self._exec_action_steps(ctx.page, prelude)  # type: ignore[attr-defined]
        elif selector:
            try:
                await ctx.page.locator(selector).first.wait_for(
                    state="visible", timeout=8000)
            except Exception:
                pass
        if model_action:
            await self._exec_action_steps(  # type: ignore[attr-defined]
                ctx.page, model_action, str(params.get("value") or params.get("model") or ""))

    async def _node_fill_input(self, ctx: FlowContext, params: dict) -> None:
        selector = str(params.get("selector") or "").strip()
        if not selector:
            raise ValueError("fill-input thiếu params.selector")
        box = ctx.page.locator(selector).first
        ready_timeout = int(params.get("ready_timeout_ms") or
                            getattr(self, "_ready_timeout_ms", 20000))
        await box.wait_for(state="visible", timeout=ready_timeout)
        new_chat_sel = str(params.get("new_chat_selector") or "")
        if new_chat_sel:
            await ctx.page.click(new_chat_sel, timeout=ready_timeout)
            await box.wait_for(state="visible", timeout=ready_timeout)
        await _sleep_ms(int(params.get("ready_delay_ms") or
                            getattr(self, "_ready_delay_ms", 0)))
        ctx.box = box

    async def _node_submit(self, ctx: FlowContext, params: dict, clicked: bool) -> None:
        box = ctx.box
        if box is None:
            raise ValueError("submit chạy trước fill-input (chưa có ô nhập)")
        await _sleep_ms(int(params.get("input_delay_ms") or
                            getattr(self, "_input_delay_ms", 0)))
        mode = str(params.get("mode") or "fill")
        if mode == "type":
            await box.click()
            await box.type(ctx.prompt)
        else:
            await box.fill(ctx.prompt)
        if clicked:
            selector = str(params.get("selector") or "").strip()
            if not selector:
                raise ValueError("submit-click thiếu params.selector")
            await ctx.page.click(selector)
        else:
            await box.press("Enter")

    async def _node_wait_done_signal(self, ctx: FlowContext, params: dict) -> None:
        ds = dict(params)
        ds.setdefault("type", "stable_text")
        text, _ = await self._poll_text_until_done(ctx, ds)  # type: ignore[attr-defined]
        ctx.text = text

    async def _node_wait_media(self, ctx: FlowContext, params: dict) -> None:
        srcs = await self._wait_for_media(  # type: ignore[attr-defined]
            ctx.page, ctx.n, ctx.deadline, ctx.media_tag)  # type: ignore[attr-defined]
        ctx.set("media_srcs", srcs)

    async def _node_extract_text(self, ctx: FlowContext, params: dict) -> None:
        selector = str(params.get("selector") or "").strip()
        if selector and not ctx.text:
            text, html = await self._reply_text_and_html(ctx.page, selector, params)  # type: ignore[attr-defined]
            ctx.text = text
            if html is not None:
                ctx.set("html", html)
                if ctx.assignment is not None:
                    ctx.assignment.html = html

    async def _node_extract_media(self, ctx: FlowContext, params: dict) -> None:
        srcs = ctx.vars.get("media_srcs") or []
        out: list[dict] = []
        copy_selector = str(params.get("copy_selector") or
                            ctx.vars.get("copy_selector") or "")
        if copy_selector:
            copied = await self._copy_media_via_buttons(  # type: ignore[attr-defined]
                ctx.page, ctx.n, ctx.deadline, copy_selector, params)
            if copied and len(copied) == ctx.n:
                out = await self._format_media(ctx.page, copied, ctx.response_format)  # type: ignore[attr-defined]
        if not out:
            for src in list(srcs)[:ctx.n]:
                if ctx.response_format == "url":
                    out.append({"url": src})
                else:
                    b64 = await self._image_to_b64(ctx.page, src)  # type: ignore[attr-defined]
                    out.append({"b64_json": b64} if b64 else {"url": src})
        ctx.media = out

    async def _node_copy_button(self, ctx: FlowContext, params: dict) -> None:
        if not params.get("use_copy_result", True):
            return
        copied = await self._copy_text_result(ctx.page, params)  # type: ignore[attr-defined]
        if copied:
            ctx.text = copied
            ctx.set("copied", True)

    async def _node_condition(self, ctx: FlowContext, params: dict) -> bool:
        expr = str(params.get("expression") or params.get("value") or "").strip()
        if not expr:
            return True
        if expr in ctx.vars:
            return bool(ctx.vars[expr])
        # So sánh đơn giản `biến == giá trị` / `biến != giá trị`.
        for op in ("==", "!="):
            if op in expr:
                left, _, right = expr.partition(op)
                left = left.strip()
                right = right.strip().strip("'\"")
                hit = str(ctx.vars.get(left, "")) == right
                return hit if op == "==" else not hit
        return bool(expr)

    async def _node_delay(self, ctx: FlowContext, params: dict) -> None:
        await _sleep_ms(int(params.get("ms") or 0))

    async def _node_eval_js(self, ctx: FlowContext, params: dict) -> None:
        code = str(params.get("code") or "")
        if not code:
            return
        try:
            result = await ctx.page.evaluate(f"() => {{ {code} }}")
        except Exception:
            result = await ctx.page.evaluate(code)
        if params.get("as"):
            ctx.set(str(params["as"]), result)

    async def _node_set_variable(self, ctx: FlowContext, params: dict) -> None:
        name = str(params.get("name") or "").strip()
        if not name:
            raise ValueError("set-variable thiếu params.name")
        ctx.set(name, params.get("value"))


async def _walk_text_deltas(runner, ctx: FlowContext, flow: dict,
                            start_id: str) -> AsyncIterator[str]:
    """Chạy graph cho flow text, yield delta tăng dần như ``BrowserRecipe._run``."""
    nodes, outgoing = order_nodes(flow)
    current: str | None = start_id
    last_yielded = ""
    steps = 0
    while current is not None:
        steps += 1
        if steps > max(64, len(nodes) * 3):
            raise FlowNodeError(current, nodes[current]["type"],
                                "graph có vòng lặp hoặc quá dài")
        node = nodes[current]
        ntype = str(node.get("type"))
        params = _params(node)
        ctx.visited.append(current)
        if ntype == "start":
            pass
        elif ntype == "assign-account":
            await runner._flow_check_trial(ctx, params)  # type: ignore[attr-defined]
        elif ntype == "check-trial-limit":
            await runner._flow_check_trial(ctx, params)  # type: ignore[attr-defined]
        elif ntype == "goto-url":
            await runner._node_goto_url(ctx, params)
        elif ntype == "wait-ready":
            await runner._node_wait_ready(ctx, params)
        elif ntype == "new-chat":
            await runner._node_new_chat(ctx, params)
        elif ntype == "action-sequence":
            await runner._node_action_sequence(ctx, params)
        elif ntype == "select-model":
            await runner._node_select_model(ctx, params)
        elif ntype == "fill-input":
            merged = {**runner._flow_fill_defaults(), **params}  # type: ignore[attr-defined]
            await runner._node_fill_input(ctx, merged)
        elif ntype == "submit-enter":
            merged = {**runner._flow_submit_defaults(), **params}  # type: ignore[attr-defined]
            await runner._node_submit(ctx, merged, clicked=False)
            ctx.set("submitted", True)
        elif ntype == "submit-click":
            merged = {**runner._flow_submit_defaults(), **params}  # type: ignore[attr-defined]
            await runner._node_submit(ctx, merged, clicked=True)
            ctx.set("submitted", True)
        elif ntype == "wait-done-signal":
            merged = {**runner._flow_done_defaults(), **params}  # type: ignore[attr-defined]
            # Poll dài ở đúng node này — stream delta tăng dần như _run.
            async for delta in runner._flow_poll_deltas(ctx, merged):  # type: ignore[attr-defined]
                if delta.startswith(last_yielded) and delta != last_yielded:
                    yield delta[len(last_yielded):]
                    last_yielded = delta
                elif delta and delta != last_yielded:
                    yield delta
                    last_yielded = delta
            ctx.text = last_yielded or ctx.text
        elif ntype == "extract-text":
            await runner._node_extract_text(ctx, params)
        elif ntype == "copy-button":
            await runner._node_copy_button(ctx, params)
            if ctx.text and ctx.text != last_yielded:
                yield ctx.text if not last_yielded else ctx.text[len(last_yielded):] \
                    if ctx.text.startswith(last_yielded) else ctx.text
                last_yielded = ctx.text
        elif ntype == "condition":
            branch = await runner._node_condition(ctx, params)
            nxt = _pick_branch(outgoing.get(current, []), branch)
            current = nxt
            continue
        elif ntype == "delay":
            await runner._node_delay(ctx, params)
        elif ntype == "eval-js":
            await runner._node_eval_js(ctx, params)
        elif ntype == "set-variable":
            await runner._node_set_variable(ctx, params)
        elif ntype in ("wait-media", "extract-media"):
            raise FlowNodeError(current, ntype,
                                "node media trong flow text — tách sang flow image/video")
        elif ntype == "output":
            break
        else:
            raise FlowNodeError(current, ntype, "node chưa hỗ trợ ở executor v1")
        current = _next_linear(outgoing.get(current, []))
    if last_yielded != ctx.text and ctx.text:
        if ctx.text.startswith(last_yielded):
            yield ctx.text[len(last_yielded):]
        else:
            yield ctx.text


async def _walk_media(runner, ctx: FlowContext, flow: dict, start_id: str) -> None:
    nodes, outgoing = order_nodes(flow)
    current: str | None = start_id
    steps = 0
    while current is not None:
        steps += 1
        if steps > max(64, len(nodes) * 3):
            raise FlowNodeError(current, nodes[current]["type"],
                                "graph có vòng lặp hoặc quá dài")
        node = nodes[current]
        ntype = str(node.get("type"))
        params = _params(node)
        ctx.visited.append(current)
        if ntype == "start":
            pass
        elif ntype in ("assign-account", "check-trial-limit"):
            await runner._flow_check_trial(ctx, params)  # type: ignore[attr-defined]
        elif ntype == "goto-url":
            await runner._node_goto_url(ctx, params)
        elif ntype == "wait-ready":
            await runner._node_wait_ready(ctx, params)
        elif ntype == "new-chat":
            await runner._node_new_chat(ctx, params)
        elif ntype == "action-sequence":
            await runner._node_action_sequence(ctx, params)
        elif ntype == "select-model":
            await runner._node_select_model(ctx, params)
        elif ntype == "fill-input":
            merged = {**runner._flow_fill_defaults(), **params}  # type: ignore[attr-defined]
            await runner._node_fill_input(ctx, merged)
        elif ntype == "submit-enter":
            merged = {**runner._flow_submit_defaults(), **params}  # type: ignore[attr-defined]
            await runner._node_submit(ctx, merged, clicked=False)
        elif ntype == "submit-click":
            merged = {**runner._flow_submit_defaults(), **params}  # type: ignore[attr-defined]
            await runner._node_submit(ctx, merged, clicked=True)
        elif ntype == "wait-media":
            merged = {**runner._flow_media_defaults(), **params}  # type: ignore[attr-defined]
            await runner._node_wait_media(ctx, merged)
        elif ntype == "extract-media":
            merged = {**runner._flow_media_defaults(), **params}  # type: ignore[attr-defined]
            await runner._node_extract_media(ctx, merged)
        elif ntype == "condition":
            branch = await runner._node_condition(ctx, params)
            current = _pick_branch(outgoing.get(current, []), branch)
            continue
        elif ntype == "delay":
            await runner._node_delay(ctx, params)
        elif ntype == "eval-js":
            await runner._node_eval_js(ctx, params)
        elif ntype == "set-variable":
            await runner._node_set_variable(ctx, params)
        elif ntype == "output":
            break
        else:
            raise FlowNodeError(current, ntype, "node chưa hỗ trợ ở executor v1")
        current = _next_linear(outgoing.get(current, []))


def _next_linear(edges: list[dict]) -> str | None:
    for edge in edges:
        handle = str(edge.get("sourceHandle") or edge.get("label") or "")
        if handle in ("", "next", "out", "true"):
            target = edge.get("target")
            return str(target) if target else None
    if edges:
        target = edges[0].get("target")
        return str(target) if target else None
    return None


def _pick_branch(edges: list[dict], taken: bool) -> str | None:
    want = "true" if taken else "false"
    for edge in edges:
        handle = str(edge.get("sourceHandle") or edge.get("label") or "")
        if handle == want:
            target = edge.get("target")
            return str(target) if target else None
    return _next_linear(edges)


def describe_walk(flow: dict) -> list[str]:
    """Thứ tự node khi chạy tuyến tính (debug/canvas preview, không mở browser)."""
    nodes, outgoing = order_nodes(flow)
    current: str | None = entry_node_id(flow)
    order: list[str] = []
    seen = 0
    while current is not None and seen <= max(64, len(nodes) * 3):
        order.append(f"{current}:{nodes[current].get('type')}")
        current = _next_linear(outgoing.get(current, []))
        seen += 1
    return order
