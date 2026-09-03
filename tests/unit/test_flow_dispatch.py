"""Chọn model = chọn flow, ở mức provider.

`stream()` gọi `flow_for_model(model_id)` rồi truyền xuống `_run`, nên đúng/sai
ở đây quyết định request đi vào flow nào.
"""

from chat2api.providers.browser_recipe import BrowserRecipe

TEXT_RESPONSE = {"last_message_selector": ".msg", "done_signal": {"type": "stable_text"}}


def _recipe(**over):
    base = {
        "slug": "s", "url": "https://s.test/",
        "prompt": {"input_selector": "#p", "submit": "Enter"},
        "response": dict(TEXT_RESPONSE),
        "models": [{"id": "m1"}],
    }
    base.update(over)
    return base


def _provider(recipe, tmp_path):
    return BrowserRecipe(recipe, tmp_path / "r", None, accounts_root=tmp_path)


class TestModelSpec:
    def test_finds_a_model_by_bare_id(self, tmp_path):
        p = _provider(_recipe(), tmp_path)
        assert p.model_spec("m1")["id"] == "m1"

    def test_finds_a_model_by_prefixed_id(self, tmp_path):
        # Router phát ra `slug/id`; `stream()` nhận lại đúng chuỗi đó.
        p = _provider(_recipe(), tmp_path)
        assert p.model_spec("s/m1")["id"] == "m1"

    def test_unknown_model_gives_an_empty_spec(self, tmp_path):
        assert _provider(_recipe(), tmp_path).model_spec("nope") == {}


class TestFlowForModel:
    def test_plain_recipe_runs_text(self, tmp_path):
        assert _provider(_recipe(), tmp_path).flow_for_model("m1") == "text"

    def test_named_flow_on_the_model_wins(self, tmp_path):
        recipe = _recipe(
            flows={"deep_research": {"type": "text", "action": "click:#t",
                                     "response": dict(TEXT_RESPONSE)},
                   "text": {"response": dict(TEXT_RESPONSE)}},
            models=[{"id": "deep", "flow": "deep_research"}, {"id": "plain"}])
        p = _provider(recipe, tmp_path)
        assert p.flow_for_model("deep") == "deep_research"
        assert p.flow_for_model("plain") == "text"

    def test_capability_still_routes_when_no_flow_is_named(self, tmp_path):
        recipe = _recipe(
            flows={"image": {"response": {"media_selector": "img"}},
                   "text": {"response": dict(TEXT_RESPONSE)}},
            models=[{"id": "drawer", "capability": "image"}])
        assert _provider(recipe, tmp_path).flow_for_model("drawer") == "image"

    def test_falls_back_to_text_when_the_named_flow_is_missing(self, tmp_path):
        # `validate_flows` chặn từ lúc lưu; đây là chốt chặn cho file cũ đã nằm
        # sẵn trên đĩa — thà chạy flow chat còn hơn ném lỗi lúc nhận request.
        recipe = _recipe(models=[{"id": "m1", "flow": "khong_co"}])
        assert _provider(recipe, tmp_path).flow_for_model("m1") == "text"

    def test_unknown_model_falls_back_to_text(self, tmp_path):
        assert _provider(_recipe(), tmp_path).flow_for_model("nope") == "text"


class TestSupportedFlows:
    def test_custom_flows_are_listed_after_the_builtin_ones(self, tmp_path):
        recipe = _recipe(flows={
            "canvas": {"type": "text", "response": dict(TEXT_RESPONSE)},
            "select_model": {"action": "click:#m"},
            "text": {"response": dict(TEXT_RESPONSE)}})
        assert _provider(recipe, tmp_path).supported_flows() == [
            "select_model", "text", "canvas"]


class TestFlowConfigLookup:
    def test_custom_flow_reads_its_own_response(self, tmp_path):
        recipe = _recipe(flows={
            "canvas": {"type": "text",
                       "response": {"last_message_selector": ".canvas",
                                    "done_signal": {"type": "stable_text"}}},
            "text": {"response": dict(TEXT_RESPONSE)}})
        p = _provider(recipe, tmp_path)
        assert p._last_message_selector("canvas") == ".canvas"
        assert p._last_message_selector("text") == ".msg"

    def test_flat_recipe_reads_the_same_selector_through_either_path(self, tmp_path):
        # Đây là bảo chứng cho tính tương thích ngược của `_run`: nó đã đổi từ
        # `self.response_cfg` sang `_last_message_selector(flow)`.
        p = _provider(_recipe(), tmp_path)
        assert p._last_message_selector("text") == p.response_cfg["last_message_selector"]

    def test_custom_flow_inherits_the_flat_done_signal(self, tmp_path):
        recipe = _recipe(flows={
            "canvas": {"type": "text", "response": {"last_message_selector": ".c"}}})
        p = _provider(recipe, tmp_path)
        assert p.flow_done_signal("canvas")["type"] == "stable_text"


class TestReplyFlags:
    """`format` / `capture_html` cũng là cấu hình của flow, không phải của recipe.

    `_evaluate_reply` truyền hai cờ này thẳng vào JS đọc reply; đọc nhầm cờ
    phẳng thì flow khai `format: markdown` sẽ bị đọc như text thường.
    """

    def test_flow_declaring_markdown_overrides_the_flat_setting(self, tmp_path):
        recipe = _recipe(flows={
            "canvas": {"type": "text", "response": {
                "last_message_selector": ".c", "format": "markdown"}},
            "text": {"response": dict(TEXT_RESPONSE)}})
        p = _provider(recipe, tmp_path)
        assert p._reply_flags("canvas") == (False, True)
        assert p._reply_flags("text") == (False, False)

    def test_flow_may_turn_markdown_back_off(self, tmp_path):
        recipe = _recipe(
            response={**TEXT_RESPONSE, "format": "markdown"},
            flows={"raw": {"type": "text", "response": {
                "last_message_selector": ".r", "format": "text"}}})
        p = _provider(recipe, tmp_path)
        assert p._reply_flags("raw")[1] is False

    def test_flow_inherits_the_flat_flags_when_silent(self, tmp_path):
        recipe = _recipe(response={**TEXT_RESPONSE, "capture_html": True})
        p = _provider(recipe, tmp_path)
        assert p._reply_flags("text")[0] is True
