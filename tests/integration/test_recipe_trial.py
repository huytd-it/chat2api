"""Chạy thử recipe có báo cáo từng bước (`chat2api.trial`).

Chạy trên site fixture thật qua Playwright: cái đáng kiểm ở đây là bảng báo cáo
có chỉ đúng bước hỏng không, nên phải có DOM thật để đếm selector.
"""

from types import SimpleNamespace

import pytest

from chat2api.browserpool import BrowserPool
from chat2api.trial import FAIL, OK, SKIP, WARN, run_trial

pytest.importorskip("playwright.async_api")


def _cfg(tmp_path):
    return SimpleNamespace(recipes_dir=tmp_path / "recipes")


async def _trial(recipe, tmp_path, flow="text", prompt=None):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        return await run_trial(_cfg(tmp_path), pool, recipe, False, flow, prompt)
    finally:
        await pool.aclose()


def _by_label(result, label):
    return next((s for s in result["steps"] if s["label"] == label), None)


async def test_every_step_reported_ok_on_a_healthy_recipe(fixture_recipe, tmp_path):
    out = await _trial(fixture_recipe, tmp_path)

    assert out["ok"] is True, out
    assert out["flow"] == "text"
    assert out["reply"] == "This is the reply."
    # Không bước nào hỏng, và bảng phải nhắc tới cả ô nhập lẫn khối trả lời —
    # đó là hai selector người sửa recipe hay gõ sai nhất.
    assert [s for s in out["steps"] if s["status"] == FAIL] == []
    assert _by_label(out, "prompt.input_selector")["status"] == OK
    assert _by_label(out, "response.last_message_selector")["status"] == OK


async def test_broken_input_selector_names_the_step_and_skips_the_run(fixture_recipe, tmp_path):
    """Selector sai thì phải nói tên bước, và KHÔNG chạy thật.

    Chạy thật rồi mới hỏng nghĩa là người dùng ngồi đợi hết `timeout_ms` để
    nhận lại đúng một chữ "timeout" — thứ mà bảng báo cáo sinh ra để thay thế.
    """
    recipe = {**fixture_recipe,
              "prompt": {**fixture_recipe["prompt"], "input_selector": "#khong-ton-tai"}}
    out = await _trial(recipe, tmp_path)

    assert out["ok"] is False
    step = _by_label(out, "prompt.input_selector")
    assert step["status"] == FAIL
    assert step["matches"] == 0
    assert "prompt.input_selector" in out["error"]
    # Dừng ở preflight ⇒ chưa có chặng postflight nào.
    assert _by_label(out, "response.last_message_selector") is None
    assert out["reply"] == ""
    # `done_signal.timeout_ms` của fixture là 8s. Đo `out["ms"]` (chỉ tính lượt
    # thử) chứ không phải đồng hồ quanh cả hàm: mở/đóng BrowserPool trên máy
    # chậm mất hàng chục giây và không nói gì về việc preflight có dừng sớm hay
    # không — đúng thứ khẳng định này muốn kiểm.
    assert out["ms"] < 8000, f"preflight lẽ ra phải dừng sớm, mất {out['ms']}ms"


async def test_invalid_css_is_reported_as_syntax_not_as_missing(fixture_recipe, tmp_path):
    recipe = {**fixture_recipe,
              "prompt": {**fixture_recipe["prompt"], "input_selector": "#("}}
    out = await _trial(recipe, tmp_path)

    step = _by_label(out, "prompt.input_selector")
    assert step["status"] == FAIL
    assert step["matches"] is None
    assert "cú pháp" in step["detail"]


async def test_ambiguous_selector_warns_but_still_runs(fixture_recipe, tmp_path):
    """`button` trúng cả Send lẫn New chat — chạy được, nhưng phải cảnh báo.

    Đây đúng là kiểu selector sống sót lúc test rồi chết khi site thêm một nút.
    """
    recipe = {**fixture_recipe,
              "prompt": {**fixture_recipe["prompt"], "submit": "click:button"}}
    out = await _trial(recipe, tmp_path)

    step = _by_label(out, "prompt.submit")
    assert step["status"] == WARN
    assert step["matches"] == 2
    # Cảnh báo không được chặn lượt chạy: `.first` vẫn trúng nút Send.
    assert out["ok"] is True, out


async def test_select_model_flow_stops_before_the_prompt(fixture_recipe, tmp_path):
    """`select:` phải nằm ở action của từng model, không phải action dùng chung.

    `_select_model` gọi action dùng chung KHÔNG kèm value, nên `select:` ở đó
    luôn thành `select_option(value="")` và hỏng — chỉ đường bấm riêng của model
    mới nhận `value or id`. Recipe dưới đây là hình dạng chạy được thật.
    """
    recipe = {**fixture_recipe,
              "flows": {"select_model": {"selector": "#model"}},
              "models": [{"id": "fixture-web", "action": "select:#model",
                          "value": "max-v2"}]}
    out = await _trial(recipe, tmp_path, flow="select_model")

    assert out["ok"] is True, out
    assert _by_label(out, "models[fixture-web].action[1] select")["status"] == OK
    # Flow này chỉ chọn model rồi dừng — không gõ prompt, không đọc trả lời.
    assert _by_label(out, "prompt.input_selector") is None
    assert out["reply"] == ""


async def test_select_model_failure_points_at_the_action_step(fixture_recipe, tmp_path):
    recipe = {**fixture_recipe,
              "flows": {"select_model": {"action": "click:#khong-co-dropdown"}}}
    out = await _trial(recipe, tmp_path, flow="select_model")

    assert out["ok"] is False
    assert _by_label(out, "select_model.action[1] click")["status"] == FAIL
    assert "select_model.action[1]" in out["error"]


async def test_unknown_flow_is_rejected_without_opening_a_browser(fixture_recipe, tmp_path):
    out = await _trial(fixture_recipe, tmp_path, flow="khong-co")

    assert out["ok"] is False
    assert out["steps"] == []
    assert "khong-co" in out["error"]


async def test_a_custom_named_flow_runs_end_to_end(fixture_recipe, tmp_path):
    """Flow tên tự đặt chạy thật, và model trỏ tới nó quyết định flow nào chạy.

    `#new-chat` trên fixture xoá sạch khối tin nhắn — dùng làm `action` để
    chứng minh action của flow THẬT SỰ chạy trước khi gõ prompt.
    """
    recipe = {**fixture_recipe,
              "flows": {"deep_research": {
                  "type": "text",
                  "label": "Deep Research",
                  "action": "click:#new-chat",
                  "response": {**fixture_recipe["response"]}}},
              "models": [{"id": "fixture-web", "flow": "deep_research"}]}
    out = await _trial(recipe, tmp_path, flow="deep_research")

    assert out["ok"] is True, out
    assert out["flow"] == "deep_research"
    assert out["reply"] == "This is the reply."
    assert _by_label(out, "flows.deep_research.action[1] click")["status"] == OK
    assert _by_label(out, "prompt.input_selector")["status"] == OK
    assert _by_label(out, "response.last_message_selector")["status"] == OK


async def test_a_custom_flow_with_a_broken_action_names_that_step(fixture_recipe, tmp_path):
    recipe = {**fixture_recipe,
              "flows": {"deep_research": {
                  "type": "text", "action": "click:#khong-co-nut",
                  "response": {**fixture_recipe["response"]}}},
              "models": [{"id": "fixture-web", "flow": "deep_research"}]}
    out = await _trial(recipe, tmp_path, flow="deep_research")

    assert out["ok"] is False
    assert _by_label(out, "flows.deep_research.action[1] click")["status"] == FAIL
    assert "flows.deep_research.action[1]" in out["error"]


async def test_flow_not_declared_by_the_recipe_is_rejected(fixture_recipe, tmp_path):
    out = await _trial(fixture_recipe, tmp_path, flow="video")

    assert out["ok"] is False
    assert "video" in out["error"]


async def test_custom_prompt_reaches_the_site(fixture_recipe, tmp_path):
    """Prompt riêng phải được gõ thật — fixture trả lời cố định nên kiểm qua
    `_looks_answered`: prompt khác câu trả lời thì lượt thử vẫn tính là đỗ."""
    out = await _trial(fixture_recipe, tmp_path, prompt="xin chào")

    assert out["ok"] is True, out
    assert out["reply"] == "This is the reply."


async def test_optional_copy_button_missing_is_skip_not_fail(fixture_recipe, tmp_path):
    """`done_signal.selector` của copy_button là tuỳ chọn.

    Không thấy nút copy thì đó là ghi chú, không phải lỗi — recipe vẫn chốt câu
    trả lời được bằng đường lùi `fallback_quiet_ms`.
    """
    recipe = {**fixture_recipe, "response": {
        **fixture_recipe["response"],
        "done_signal": {"type": "copy_button", "selector": "#khong-co-nut-copy",
                        "scope": "after", "fallback_quiet_ms": 1000, "timeout_ms": 8000},
    }}
    out = await _trial(recipe, tmp_path)

    step = _by_label(out, "done_signal.selector (copy_button)")
    assert step["status"] == SKIP
    assert step["matches"] == 0
