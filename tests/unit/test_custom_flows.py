"""Flow tự đặt tên + `models[].flow` (chọn model = chọn flow).

Điều đáng kiểm nhất ở đây là recipe đời cũ KHÔNG đổi hành vi: mọi thứ chạy qua
`build_flows`, nên một sai sót nhỏ ở đó làm hỏng mọi site đang chạy.
"""

import pytest

from chat2api.flows import (
    build_flows,
    flow_label,
    flow_name_ok,
    flow_type,
    flows_of,
    is_media_flow,
    ordered_flows,
    supported_flows,
    validate_flows,
)

DONE_SIGNALS = {"stable_text", "selector_appear", "selector_disappear", "copy_button"}
COPY_SCOPES = {"after", "inside", "page"}

TEXT_RESPONSE = {"last_message_selector": ".msg", "done_signal": {"type": "stable_text"}}
FLAT = {
    "slug": "x", "url": "https://x.test/",
    "prompt": {"input_selector": "#p", "submit": "Enter"},
    "response": dict(TEXT_RESPONSE),
    "models": [{"id": "m1"}],
}


def _errs(recipe):
    return validate_flows(recipe, DONE_SIGNALS, COPY_SCOPES)


class TestFlowName:
    @pytest.mark.parametrize("name", ["text", "select_model", "deep_research", "canvas", "a", "a1_b"])
    def test_accepts_builtin_and_custom(self, name):
        assert flow_name_ok(name) is True

    @pytest.mark.parametrize("name", ["", "Deep", "1st", "has-dash", "has space", "a" * 41, None, 5])
    def test_rejects_the_rest(self, name):
        assert flow_name_ok(name) is False


class TestFlowType:
    def test_builtin_names_carry_their_own_shape(self):
        assert flow_type("text") == "text"
        assert flow_type("image") == "image"
        assert flow_type("video") == "video"

    def test_custom_name_defaults_to_text(self):
        assert flow_type("deep_research") == "text"

    def test_declared_type_wins(self):
        assert flow_type("sora", {"type": "video"}) == "video"
        assert is_media_flow("sora", {"type": "video"}) is True

    def test_a_builtin_name_can_be_overridden(self):
        # Không khuyến khích, nhưng `type` phải là nguồn sự thật DUY NHẤT —
        # nếu không, runtime và validate sẽ đọc ra hai hình dạng khác nhau.
        assert flow_type("image", {"type": "text"}) == "text"

    def test_rubbish_type_falls_back_to_the_name(self):
        assert flow_type("image", {"type": "banana"}) == "image"


class TestOrdering:
    def test_builtin_first_then_declaration_order(self):
        assert ordered_flows(["canvas", "text", "select_model", "deep_research"]) == [
            "select_model", "text", "canvas", "deep_research"]

    def test_is_stable_and_deduplicated(self):
        assert ordered_flows(["canvas", "canvas", "text"]) == ["text", "canvas"]


class TestFlowsOfModel:
    def test_named_flow_wins_over_capability(self):
        assert flows_of({"id": "m", "flow": "deep_research", "capability": "chat"}) == {"deep_research"}

    def test_falls_back_to_capability(self):
        assert flows_of({"id": "m", "capability": "image"}) == {"image"}
        assert flows_of({"id": "m"}) == {"text"}

    def test_blank_flow_is_ignored(self):
        assert flows_of({"id": "m", "flow": "  ", "capability": "video"}) == {"video"}


class TestBuildFlows:
    def test_custom_flow_is_built(self):
        recipe = {**FLAT, "flows": {
            "deep_research": {"type": "text", "action": "click:#tools",
                              "response": dict(TEXT_RESPONSE)}}}
        built = build_flows(recipe)
        assert "deep_research" in built
        assert built["deep_research"]["type"] == "text"
        assert built["deep_research"]["action"] == "click:#tools"

    def test_custom_flow_inherits_the_flat_input_box(self):
        # Rất nhiều site dùng chung một ô nhập cho mọi chế độ; bắt khai lại là
        # ép người dùng chép selector ba lần rồi quên sửa một chỗ.
        recipe = {**FLAT, "flows": {
            "deep_research": {"type": "text", "response": dict(TEXT_RESPONSE)}}}
        assert build_flows(recipe)["deep_research"]["prompt"]["input_selector"] == "#p"

    def test_media_shaped_custom_flow_keeps_media_keys(self):
        recipe = {**FLAT, "flows": {
            "sora": {"type": "video", "response": {"media_selector": "video"}}}}
        built = build_flows(recipe)["sora"]
        assert built["type"] == "video"
        assert built["response"]["media_selector"] == "video"

    def test_media_aliases_still_resolve_for_a_custom_flow(self):
        recipe = {**FLAT, "flows": {
            "sora": {"type": "video", "response": {"video_selector": "video.out"}}}}
        assert build_flows(recipe)["sora"]["response"]["media_selector"] == "video.out"

    def test_flat_recipe_is_untouched(self):
        built = build_flows(FLAT)
        assert set(built) == {"text"}
        assert built["text"]["type"] == "text"
        assert built["text"]["response"]["last_message_selector"] == ".msg"

    def test_supported_flows_lists_custom_after_builtin(self):
        recipe = {**FLAT, "flows": {
            "canvas": {"type": "text", "response": dict(TEXT_RESPONSE)},
            "text": {"response": dict(TEXT_RESPONSE)}}}
        assert supported_flows(recipe) == ["text", "canvas"]


class TestValidation:
    def test_a_well_formed_custom_flow_passes(self):
        recipe = {**FLAT, "flows": {
            "deep_research": {"type": "text", "action": "click:#tools",
                              "response": dict(TEXT_RESPONSE)}},
            "models": [{"id": "m1", "flow": "deep_research"}]}
        assert _errs(recipe) == []

    def test_custom_name_without_type_is_rejected(self):
        recipe = {**FLAT, "flows": {
            "deep_research": {"response": dict(TEXT_RESPONSE)}}}
        assert any("flows.deep_research.type" in e for e in _errs(recipe))

    def test_bad_type_value_is_rejected(self):
        recipe = {**FLAT, "flows": {"x1": {"type": "audio", "response": dict(TEXT_RESPONSE)}}}
        assert any("flows.x1.type" in e for e in _errs(recipe))

    def test_illegal_flow_name_is_rejected(self):
        recipe = {**FLAT, "flows": {"Deep Research": {"type": "text"}}}
        assert any("flows.Deep Research" in e for e in _errs(recipe))

    def test_media_shaped_flow_needs_a_media_selector(self):
        recipe = {**FLAT, "flows": {"sora": {"type": "video", "response": {}}}}
        assert any("flows.sora.response.media_selector" in e for e in _errs(recipe))

    def test_text_shaped_flow_needs_a_message_selector(self):
        recipe = {**FLAT, "flows": {"canvas": {"type": "text", "response": {
            "done_signal": {"type": "stable_text"}}}}}
        # Kế thừa từ khối phẳng nên KHÔNG thiếu — đây là hành vi cố ý.
        assert _errs(recipe) == []

    def test_select_model_may_not_declare_a_type(self):
        recipe = {**FLAT, "flows": {"select_model": {"type": "text", "action": "click:#m"}}}
        assert any("flows.select_model.type" in e for e in _errs(recipe))

    def test_model_pointing_at_an_unknown_flow_is_rejected(self):
        recipe = {**FLAT, "models": [{"id": "m1", "flow": "khong_co"}]}
        errs = _errs(recipe)
        assert any("models[0].flow" in e and "khong_co" in e for e in errs)

    def test_model_may_not_point_at_select_model(self):
        recipe = {**FLAT, "flows": {"select_model": {"action": "click:#m"},
                                    "text": {"response": dict(TEXT_RESPONSE)}},
                  "models": [{"id": "m1", "flow": "select_model"}]}
        assert any("models[0].flow" in e for e in _errs(recipe))

    def test_model_flow_is_checked_even_without_a_flows_block(self):
        # Recipe phẳng vẫn CÓ flow (suy ra), nên gõ sai tên ở đây cũng phải kêu.
        assert any("models[0].flow" in e
                   for e in _errs({**FLAT, "models": [{"id": "m1", "flow": "sai"}]}))
        assert _errs({**FLAT, "models": [{"id": "m1", "flow": "text"}]}) == []


class TestLabel:
    def test_builtin_label(self):
        assert flow_label("text") == "Generate text"

    def test_custom_falls_back_to_its_name(self):
        assert flow_label("deep_research") == "deep_research"

    def test_declared_label_wins(self):
        assert flow_label("deep_research", {"label": "Deep Research"}) == "Deep Research"
