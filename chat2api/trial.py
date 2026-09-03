"""Chạy thử một recipe CHƯA lưu: soi từng selector, chạy thật, rồi soi lại.

Vì sao không chỉ chạy thật rồi báo lỗi: `stream()` hỏng ở đâu cũng chỉ ném ra
đúng một chuỗi ("timeout sau 120000ms"), người sửa recipe không biết selector
nào sai. Nên một lượt chạy thử đi ba chặng:

1. **Preflight** — mở trang rồi kiểm từng selector của flow theo đúng THỨ TỰ
   `_run` sẽ dùng, và *thực thi* các bước `click:`/`select:` khi đi qua. Phải
   thực thi chứ không chỉ đếm: option trong dropdown model chỉ tồn tại sau khi
   đã bấm mở dropdown, đếm suông thì bước nào cũng "0 khớp".
2. **Chạy thật** — đúng đường production (`stream` cho chữ, `_generate_media`
   cho ảnh/video), trên cùng ctx_key nên cùng một tab.
3. **Postflight** — selector chỉ có nghĩa SAU khi đã có câu trả lời
   (`last_message_selector`, nút copy, `media_selector`) soi ở đây, vì trước
   lúc gửi prompt chúng khớp 0 element một cách hoàn toàn bình thường.

Trạng thái mỗi bước: `ok` (khớp đúng 1), `warn` (khớp nhiều — chạy được nhưng
mơ hồ, đổi giao diện là trúng nhầm), `fail` (0 khớp hoặc selector sai cú pháp),
`skip` (recipe không khai báo).
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from . import applog

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"

#: Flow chỉ chạy tới bước chọn model rồi dừng — không gõ prompt, không đọc gì.
PREFLIGHT_ONLY = "select_model"

#: Prompt mặc định cho flow chữ — câu trả lời phải khác hẳn prompt thì mới tính
#: là site đã thật sự trả lời (xem `_looks_answered`).
DEFAULT_TEXT_PROMPT = "Reply with exactly: OK"
DEFAULT_MEDIA_PROMPT = "a red circle on white background"


def _step(label: str, selector: str, status: str, matches: int | None = None,
          detail: str = "") -> dict[str, Any]:
    return {"label": label, "selector": selector[:200], "status": status,
            "matches": matches, "detail": detail}


def _split_actions(action: Any) -> list[tuple[str, str]]:
    """`'click:a;select:b'` → `[('click','a'), ('select','b')]`.

    Giữ đúng cách tách của `_exec_action_steps` để bảng báo cáo khớp với thứ tự
    thật sự chạy lúc production.
    """
    out: list[tuple[str, str]] = []
    for raw in str(action or "").split(";"):
        raw = raw.strip()
        if not raw or ":" not in raw:
            continue
        verb, selector = raw.split(":", 1)
        verb, selector = verb.strip(), selector.strip()
        if selector:
            out.append((verb, selector))
    return out


async def _count(page, selector: str) -> int:
    """Số element khớp; -1 khi selector sai cú pháp (Playwright ném)."""
    try:
        return await page.locator(selector).count()
    except Exception:
        return -1


async def _check(page, label: str, selector: str, *, required: bool = True) -> dict[str, Any]:
    """Đếm khớp cho một selector không cần thực thi gì."""
    if not selector:
        return _step(label, "", SKIP, None, "recipe không khai báo")
    n = await _count(page, selector)
    if n < 0:
        return _step(label, selector, FAIL, None, "selector sai cú pháp")
    if n == 0:
        return _step(label, selector, FAIL if required else SKIP, 0,
                     "không khớp element nào")
    if n > 1:
        return _step(label, selector, WARN, n,
                     f"khớp {n} element — chạy được nhưng mơ hồ")
    return _step(label, selector, OK, 1)


async def _run_action_step(page, label: str, verb: str, selector: str,
                           value: str | None) -> dict[str, Any]:
    """Đếm khớp RỒI thực thi bước đó, để bước sau có DOM đúng mà soi."""
    n = await _count(page, selector)
    if n < 0:
        return _step(label, selector, FAIL, None, "selector sai cú pháp")
    if n == 0:
        return _step(label, selector, FAIL, 0,
                     "không khớp element nào — các bước sau không soi được")
    loc = page.locator(selector).first
    try:
        await loc.wait_for(state="visible", timeout=10000)
    except Exception:
        pass
    try:
        if verb == "select":
            await loc.select_option(value=str(value or ""))
        else:
            await loc.click(timeout=10000)
    except Exception as error:
        return _step(label, selector, FAIL, n, f"khớp nhưng thao tác lỗi: {error}")
    detail = f"khớp {n} element — mơ hồ" if n > 1 else ""
    return _step(label, selector, WARN if n > 1 else OK, n, detail)


def _model_of(recipe: dict, flow: str) -> dict:
    """Model chạy flow này — chọn flow chính là chọn model tương ứng.

    Đây là chiều ngược của `models[].flow`: bảng báo cáo phải soi đúng đường
    bấm của model thật sự phục vụ flow đó, chứ không phải model đầu danh sách.
    """
    from .flows import flows_of

    models = [m for m in (recipe.get("models") or []) if isinstance(m, dict)]
    if not models:
        return {}
    if flow != PREFLIGHT_ONLY:
        for m in models:
            if flow in flows_of(m):
                return m
    return models[0]


async def _preflight(runner, page, flow: str, model: dict) -> list[dict[str, Any]]:
    """Chặng 1 — mở trang, đi hết đường dẫn tới ô nhập, soi từng bước."""
    steps: list[dict[str, Any]] = []
    url = runner._new_chat_url or runner.url
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        steps.append(_step("mở trang", url, OK))
    except Exception as error:
        steps.append(_step("mở trang", url, FAIL, None, str(error)))
        return steps

    # `_run` vào chế độ của flow TRƯỚC rồi mới chọn model: dropdown model của
    # nhiều site chỉ liệt kê model hợp lệ cho chế độ đang bật. Soi theo đúng
    # thứ tự đó, nếu không bảng báo cáo sẽ nói dối về nguyên nhân hỏng.
    # `value` phải truyền y hệt production, nếu không `select:` sẽ hỏng giả:
    # `_enter_flow` và phần dùng chung của `_select_model` đều gọi
    # `_exec_action_steps` KHÔNG kèm value (→ chuỗi rỗng), chỉ đường bấm riêng
    # của model mới có `value or id`.
    if flow != "select_model":
        for i, (verb, selector) in enumerate(_split_actions(runner.flow(flow).get("action")), 1):
            steps.append(await _run_action_step(
                page, f"flows.{flow}.action[{i}] {verb}", verb, selector, None))
            if steps[-1]["status"] == FAIL:
                return steps

    shared = runner.flow("select_model").get("action") or runner._select_model_action
    for i, (verb, selector) in enumerate(_split_actions(shared), 1):
        steps.append(await _run_action_step(
            page, f"select_model.action[{i}] {verb}", verb, selector, None))
        if steps[-1]["status"] == FAIL:
            return steps

    for i, (verb, selector) in enumerate(_split_actions(model.get("action")), 1):
        steps.append(await _run_action_step(
            page, f"models[{model.get('id', '?')}].action[{i}] {verb}", verb, selector,
            model.get("value") or model.get("id")))
        if steps[-1]["status"] == FAIL:
            return steps

    if flow == "select_model":
        return steps

    prompt_cfg = runner.flow_prompt(flow)
    steps.append(await _check(page, "prompt.input_selector",
                              str(prompt_cfg.get("input_selector") or "")))
    submit = str(prompt_cfg.get("submit") or "Enter")
    if submit.startswith("click:"):
        steps.append(await _check(page, "prompt.submit", submit.split(":", 1)[1]))
    else:
        steps.append(_step("prompt.submit", submit, OK, None, "gửi bằng phím"))
    return steps


async def _postflight(runner, page, flow: str) -> list[dict[str, Any]]:
    """Chặng 3 — selector chỉ có nghĩa sau khi đã có câu trả lời trên trang."""
    steps: list[dict[str, Any]] = []
    resp = runner.flow_response(flow) or runner.response_cfg
    # Theo HÌNH DẠNG kết quả, không theo tên: flow tự đặt tên `sora` với
    # type=video vẫn phải soi media_selector.
    if _is_media(runner, flow):
        steps.append(await _check(page, f"{flow}.media_selector",
                                  runner._image_selector(flow)))
        steps.append(await _check(page, f"{flow}.copy_selector",
                                  runner._image_copy_selector(flow), required=False))
        return steps

    steps.append(await _check(page, "response.last_message_selector",
                              str(resp.get("last_message_selector") or "")))
    ds = runner.flow_done_signal(flow)
    dtype = str(ds.get("type") or "")
    if dtype in ("selector_appear", "selector_disappear"):
        steps.append(await _check(page, f"done_signal.selector ({dtype})",
                                  str(ds.get("selector") or "")))
    elif dtype == "copy_button":
        from .providers.browser_recipe import DEFAULT_COPY_BUTTON_SELECTOR

        selector = str(ds.get("selector") or DEFAULT_COPY_BUTTON_SELECTOR)
        steps.append(await _check(page, "done_signal.selector (copy_button)",
                                  selector, required=False))
    return steps


async def _trial_page(runner, assignment, headed: bool):
    """Tab mà CẢ preflight lẫn lượt chạy thật dùng chung.

    Phải cùng `ctx_key` với lượt chạy thật, nếu không ta soi selector trên một
    tab còn flow chạy trên tab khác — báo cáo sẽ không nói về cùng một trang.
    Gán sẵn `assignment.headed` để `_run` dùng lại đúng quyết định này.
    """
    if assignment.headed is None:
        assignment.headed = runner.resolve_headed(headed, assignment.profile)
    if assignment.profile is not None:
        return await runner.open_profile_page(
            assignment.profile, assignment.ctx_key, assignment.headed)
    return await runner._acquire_page(
        assignment.ctx_key, assignment.storage_state, assignment.headed)


def _is_media(runner, flow: str) -> bool:
    """Flow này trả về file hay trả về chữ, theo `type` đã chuẩn hoá."""
    from .flows import is_media_flow

    return is_media_flow(flow, runner.flow(flow))


def _looks_answered(reply: str, prompt: str) -> bool:
    """Site đã trả lời thật chưa, hay ta chỉ đọc lại chính prompt vừa gõ."""
    text = (reply or "").strip()
    return bool(text) and text.lower() != prompt.strip().lower()


async def run_trial(cfg, pool, recipe: dict, headed: bool, flow: str = "text",
                    prompt: str | None = None) -> dict[str, Any]:
    """Chạy thử `recipe` (chưa ghi đĩa) cho đúng một flow, báo cáo từng bước."""
    from .providers.browser_recipe import BrowserRecipe

    trial_slug = f"manual-test-{uuid.uuid4().hex[:10]}"
    trial_recipe = {**recipe, "slug": trial_slug}
    trial_dir = cfg.recipes_dir / ".manual-test" / trial_slug
    runner = BrowserRecipe(trial_recipe, trial_dir, pool, headed=headed,
                           accounts_root=cfg.recipes_dir)
    # Flow hợp lệ là flow CHÍNH RECIPE NÀY khai, không phải một danh sách cứng:
    # recipe đặt tên flow riêng thì tên đó cũng phải chạy thử được.
    if flow != "text" and not runner.has_flow(flow):
        known = ", ".join(runner.supported_flows()) or "(chưa có flow nào)"
        return {"ok": False, "flow": flow, "reply": "", "steps": [],
                "error": f"recipe chưa khai báo flow '{flow}' — đang có: {known}"}

    model = _model_of(trial_recipe, flow)
    is_media = _is_media(runner, flow) and flow != PREFLIGHT_ONLY
    text = prompt or (DEFAULT_MEDIA_PROMPT if is_media else DEFAULT_TEXT_PROMPT)
    steps: list[dict[str, Any]] = []
    reply, error, media = "", "", 0
    started = time.monotonic()
    assignment = None
    try:
        assignment = await runner.assign(None)
        page = await _trial_page(runner, assignment, headed)
        steps = await _preflight(runner, page, flow, model)
        broken = next((s for s in steps if s["status"] == FAIL), None)
        if broken is not None:
            error = f"dừng ở bước '{broken['label']}': {broken['detail']}"
        elif flow != PREFLIGHT_ONLY:
            # Preflight đã bấm mở dropdown; lượt chạy thật tự `goto` lại từ đầu
            # nên trang được dựng lại sạch, không kế thừa state dở dang đó.
            if is_media:
                items = await runner._generate_media(
                    flow, text, 1, "1024x1024", headed, None, assignment, "b64_json")
                media = len(items or [])
            else:
                # `stream()` tự suy flow từ model, nên model phải là model của
                # đúng flow này — `_model_of` đã chọn như vậy.
                parts: list[str] = []
                async for delta in runner.stream([{"role": "user", "content": text}],
                                                 model.get("id", ""), assignment=assignment):
                    parts.append(delta)
                reply = "".join(parts).strip()
            steps += await _postflight(runner, page, flow)
    except Exception as exc:
        error = error or str(exc)
        applog.log(f"trial: '{recipe.get('slug') or '?'}' flow={flow} lỗi: {exc}", level="warn")
    finally:
        if assignment is not None:
            assignment.release()
        await pool.drop(trial_slug)

    failed = any(s["status"] == FAIL for s in steps)
    clean = not failed and not error
    if flow == PREFLIGHT_ONLY:
        ok = clean
    elif is_media:
        ok = clean and media > 0
    else:
        ok = clean and _looks_answered(reply, text)
    out = {"ok": ok, "flow": flow, "reply": reply, "steps": steps,
           "ms": int((time.monotonic() - started) * 1000)}
    if is_media:
        out["media"] = media
    if error:
        out["error"] = error
    elif not ok and not failed:
        out["error"] = ("không nhận được media nào" if is_media
                        else "site không trả lời (hoặc chỉ đọc lại prompt)")
    return out
