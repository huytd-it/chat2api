"""Biên dịch một flow graph thành dict recipe cho ``BrowserRecipe``.

Vai trò: dựng *runner substrate* (accounts, timing, selectors, done_signal…)
để ``flow_executor`` tái dùng các helpers browser đã kiểm chứng
(``_exec_action_steps``, ``_wait_chat_ready``, ``_reply``…). Executor vẫn
chạy **từng node theo edges** (quyết định 2B) — compiler không thay thế
executor, nó chỉ cung cấp cấu hình nền.
"""

from __future__ import annotations

from typing import Any

from . import flows as flows_mod


def _nodes_by_type(flow: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for node in flow.get("nodes") or []:
        if isinstance(node, dict):
            out.setdefault(str(node.get("type")), []).append(node)
    return out


def _first(nodes: list[dict] | None) -> dict:
    if nodes:
        params = nodes[0].get("params")
        if isinstance(params, dict):
            return params
    return {}


def compile_flow(flow: dict) -> dict:
    """Flow graph → recipe dict hợp lệ cho ``BrowserRecipe`` + ``validate_recipe``."""
    if not isinstance(flow, dict):
        raise ValueError("flow phải là một mapping")
    slug = str(flow.get("slug") or "").strip().lower()
    if not slug:
        raise ValueError("flow thiếu slug")
    kind = str(flow.get("kind") or "text")
    flow_type = str(flow.get("flow_type") or flow.get("type") or "text")
    if flow_type not in ("text", "image", "video"):
        flow_type = "text"

    by_type = _nodes_by_type(flow)
    goto = _first(by_type.get("goto-url"))
    wait_ready = _first(by_type.get("wait-ready"))
    new_chat = _first(by_type.get("new-chat"))
    assign = _first(by_type.get("assign-account"))
    trial = _first(by_type.get("check-trial-limit"))
    action_seq = _first(by_type.get("action-sequence"))
    select = _first(by_type.get("select-model"))
    fill = _first(by_type.get("fill-input"))
    submit_click = _first(by_type.get("submit-click"))
    wait_done = _first(by_type.get("wait-done-signal"))
    extract_text = _first(by_type.get("extract-text"))
    copy_btn = _first(by_type.get("copy-button"))
    wait_media = _first(by_type.get("wait-media"))
    extract_media = _first(by_type.get("extract-media"))

    url = str(goto.get("url") or "").strip()
    if not url:
        raise ValueError("flow thiếu node goto-url.url")

    input_selector = str(fill.get("selector") or "").strip()
    if not input_selector:
        raise ValueError("flow thiếu node fill-input.selector")

    if by_type.get("submit-click"):
        submit = f"click:{submit_click.get('selector', '')}"
    else:
        submit = "Enter"
    prompt = {"input_selector": input_selector,
              "input_mode": fill.get("mode", "fill"),
              "submit": submit}

    ds_type = str(wait_done.get("type") or "stable_text")
    done_signal: dict[str, Any] = {"type": ds_type}
    for key in ("selector", "quiet_ms", "timeout_ms", "scope", "exclude",
                "fallback_quiet_ms", "use_copy_result"):
        if wait_done.get(key) is not None:
            done_signal[key] = wait_done[key]
    if copy_btn:
        done_signal["type"] = "copy_button"
        for key in ("selector", "scope", "exclude", "use_copy_result"):
            if copy_btn.get(key) is not None:
                done_signal[key] = copy_btn[key]

    response: dict[str, Any] = {"done_signal": done_signal}
    last_sel = str(extract_text.get("selector") or "").strip()
    if last_sel:
        response["last_message_selector"] = last_sel
    if extract_text.get("format") is not None:
        response["format"] = extract_text["format"]
    if extract_text.get("capture_html") is not None:
        response["capture_html"] = extract_text["capture_html"]
    if extract_text.get("use_copy_result") is not None:
        done_signal["use_copy_result"] = extract_text["use_copy_result"]
    for key in ("media_selector", "copy_selector", "copy_scope", "copy_exclude"):
        if wait_media.get(key) is not None:
            response[key] = wait_media[key]
        elif extract_media.get(key) is not None:
            response[key] = extract_media[key]

    model_cfg = flow.get("model") if isinstance(flow.get("model"), dict) else {}
    model_id = str(model_cfg.get("id") or slug)
    capability = str(flow.get("capability") or
                     ({"text": "chat", "image": "image", "video": "video"}.get(flow_type, "chat")))
    model_entry: dict[str, Any] = {"id": model_id, "capability": capability,
                                   "flow": kind}
    model_action = str(select.get("model_action") or select.get("action") or "")
    if model_action:
        model_entry["action"] = model_action
    if select.get("value"):
        model_entry["value"] = str(select["value"])

    select_selector = str(select.get("selector") or "")
    prelude = str(select.get("prelude_action") or "")
    flow_action = str(action_seq.get("action") or "")

    flows: dict[str, Any] = {}
    if select_selector or prelude:
        flows["select_model"] = {k: v for k, v in
                                 {"selector": select_selector or None,
                                  "action": prelude or None}.items() if v}
    content: dict[str, Any] = {"prompt": dict(prompt), "response": dict(response),
                               "type": flow_type}
    if flow_action:
        content["action"] = flow_action
    if select_selector and not prelude and not model_action:
        content["selector"] = select_selector
    flows[kind] = content

    account_cfg = flow.get("account") if isinstance(flow.get("account"), dict) else {}
    login: dict[str, Any] = {
        "strategy": assign.get("strategy") or account_cfg.get("strategy") or "round_robin",
        "quota": assign.get("quota", account_cfg.get("quota", 50)),
    }
    anon_limit = trial.get("limit", account_cfg.get("anon_trial_limit"))
    if isinstance(anon_limit, int):
        login["anon_trial_limit"] = anon_limit

    timing: dict[str, Any] = {}
    if isinstance(wait_ready.get("delay_ms"), int):
        timing["ready_delay_ms"] = wait_ready["delay_ms"]
    if isinstance(wait_ready.get("timeout_ms"), int):
        timing["ready_timeout_ms"] = wait_ready["timeout_ms"]
    # delay ngay trước fill-input là input_delay (quy ước của converter)
    for node in flow.get("nodes") or []:
        if isinstance(node, dict) and node.get("type") == "delay":
            params = node.get("params") or {}
            if isinstance(params.get("ms"), int):
                timing.setdefault("input_delay_ms", params["ms"])
                break

    recipe: dict[str, Any] = {
        "slug": slug,
        "url": url,
        "prompt": prompt,
        "response": response,
        "models": [model_entry],
        "flows": flows,
        "login": login,
        "keep_context": bool(flow.get("keep_context", True)),
    }
    if timing:
        recipe["timing"] = timing
    if new_chat.get("url") or new_chat.get("selector"):
        recipe["new_chat"] = {k: v for k, v in
                              {"url": new_chat.get("url"),
                               "selector": new_chat.get("selector")}.items() if v}
    # Giữ khả năng validate bằng chính validate_recipe của recipe cũ.
    from .providers.browser_recipe import validate_recipe

    errs = validate_recipe(recipe)
    # Recipe đời cũ bắt `response.last_message_selector` khi không có flows;
    # ở đây luôn có flows nên lỗi còn lại (nếu có) là thật.
    media_ok = flow_type in ("image", "video") and (
        response.get("media_selector") or response.get("copy_selector"))
    if errs and not (len(errs) == 1 and "last_message_selector" in errs[0] and media_ok):
        raise ValueError("; ".join(errs))
    return recipe


def flow_kind(flow: dict) -> str:
    return str(flow.get("kind") or "text")


def flow_capability(flow: dict) -> str:
    cap = str(flow.get("capability") or "")
    if cap in ("chat", "image", "video"):
        return cap
    ftype = str(flow.get("flow_type") or "text")
    return {"image": "image", "video": "video"}.get(ftype, "chat")


def expected_model_ids(flow: dict) -> list[str]:
    """Public model id mà flow này expose: ``flow/<slug>`` (1 flow = 1 model)."""
    slug = str(flow.get("slug") or "").strip().lower()
    return [f"flow/{slug}"] if slug else []


def capability_of(flow: dict) -> str:
    cap = flow_capability(flow)
    return cap
