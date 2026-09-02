"""Thao tác ghi được chia theo việc (chat2api/flows.py).

Hai điều phải giữ:

1. Recipe cũ (phẳng: prompt/response/mode) vẫn chạy y như trước — build_flows
   dựng lại đúng flow tương đương, không đổi selector nào.
2. Recipe mới khai báo `flows` thì mỗi việc có cấu hình riêng và phối hợp được
   với nhau (chọn model → text/image/video) mà không đè lên nhau.
"""

from chat2api import flows


# --------------------------------------------------------------- capability

def test_capability_both_still_means_chat_plus_image():
    assert flows.capabilities_of({"id": "m", "capability": "both"}) == {"chat", "image"}


def test_capability_accepts_a_comma_list_and_a_yaml_list():
    assert flows.capabilities_of({"id": "m", "capability": "chat,video"}) == {"chat", "video"}
    assert flows.capabilities_of({"id": "m", "capability": ["image", "video"]}) == {"image", "video"}


def test_capability_defaults_to_chat_when_absent():
    assert flows.capabilities_of({"id": "m"}) == {"chat"}


def test_capability_valid_rejects_unknown_words():
    assert flows.capability_valid("chat,image")
    assert not flows.capability_valid("audio")
    assert not flows.capability_valid(3)


def test_flows_of_maps_capability_to_the_flow_that_runs_it():
    assert flows.flows_of({"id": "m", "capability": "both"}) == {"text", "image"}
    assert flows.flows_of({"id": "m", "capability": "video"}) == {"video"}


# ------------------------------------------------------- recipe cũ (phẳng)

FLAT_CHAT = {
    "slug": "site",
    "url": "https://site.tld",
    "prompt": {"input_selector": "#box", "input_mode": "fill", "submit": "Enter"},
    "response": {"last_message_selector": ".msg",
                 "done_signal": {"type": "copy_button", "quiet_ms": 600}},
    "models": [{"id": "site-chat"}],
}


def test_flat_recipe_becomes_a_text_flow_with_the_same_selectors():
    built = flows.build_flows(FLAT_CHAT)
    assert list(built) == ["text"]
    assert built["text"]["prompt"]["input_selector"] == "#box"
    assert built["text"]["response"]["last_message_selector"] == ".msg"
    assert built["text"]["response"]["done_signal"]["type"] == "copy_button"


def test_a_chat_only_recipe_does_not_gain_an_image_flow():
    """Nếu không, mọi recipe chat đều tự nhiên 'hỗ trợ ảnh' và /v1/images nhận
    request rồi hỏng giữa chừng thay vì từ chối ngay."""
    assert "image" not in flows.build_flows(FLAT_CHAT)


def test_flat_image_recipe_becomes_an_image_flow_sharing_the_chat_input():
    recipe = {
        **FLAT_CHAT,
        "response": {**FLAT_CHAT["response"], "image_selector": "img.result",
                     "image_copy_selector": "button.copy-img", "image_copy_scope": "after"},
        "mode": {"selector": ".mode", "image_action": "click:.mode;click:[data-v=img]",
                 "chat_action": "click:.mode;click:[data-v=chat]"},
        "models": [{"id": "site-img", "capability": "image"}],
    }
    built = flows.build_flows(recipe)
    assert built["image"]["action"] == "click:.mode;click:[data-v=img]"
    assert built["text"]["action"] == "click:.mode;click:[data-v=chat]"
    # Site dùng chung một ô nhập cho cả hai chế độ.
    assert built["image"]["prompt"]["input_selector"] == "#box"
    # Alias image_* được đổi về khóa chuẩn dùng chung với video.
    assert built["image"]["response"]["media_selector"] == "img.result"
    assert built["image"]["response"]["copy_selector"] == "button.copy-img"
    assert built["image"]["response"]["copy_scope"] == "after"
    # mode.selector là chỗ chờ dropdown model hiện ra.
    assert built["select_model"]["selector"] == ".mode"


# ------------------------------------------------------- recipe mới (flows)

FLOW_RECIPE = {
    "slug": "site",
    "url": "https://site.tld",
    "prompt": {"input_selector": "#box", "submit": "Enter"},
    "response": {"last_message_selector": ".msg",
                 "done_signal": {"type": "copy_button", "timeout_ms": 120000}},
    "models": [{"id": "m-text"}, {"id": "m-vid", "capability": "video"}],
    "flows": {
        "select_model": {"selector": ".model-btn", "action": "click:.model-btn"},
        "text": {"action": "click:[data-tab=chat]"},
        "video": {
            "action": "click:[data-tab=video]",
            "prompt": {"input_selector": "#video-box", "submit": "click:.send-video"},
            "response": {"video_selector": "video.result",
                         "done_signal": {"type": "copy_button", "timeout_ms": 600000}},
        },
    },
}


def test_declared_flows_each_keep_their_own_prompt_and_response():
    built = flows.build_flows(FLOW_RECIPE)
    assert built["video"]["prompt"]["input_selector"] == "#video-box"
    assert built["video"]["prompt"]["submit"] == "click:.send-video"
    assert built["video"]["response"]["media_selector"] == "video.result"
    # Flow text không khai lại prompt/response nên thừa hưởng phần dùng chung.
    assert built["text"]["prompt"]["input_selector"] == "#box"
    assert built["text"]["response"]["last_message_selector"] == ".msg"


def test_flows_do_not_leak_into_each_other():
    built = flows.build_flows(FLOW_RECIPE)
    assert built["text"]["action"] == "click:[data-tab=chat]"
    assert built["video"]["action"] == "click:[data-tab=video]"
    assert "last_message_selector" not in built["video"]["response"]
    assert "media_selector" not in built["text"]["response"]


def test_undeclared_flow_is_absent_rather_than_guessed():
    assert "image" not in flows.build_flows(FLOW_RECIPE)


def test_supported_flows_follows_the_declaration_order_used_by_the_ui():
    assert flows.supported_flows(FLOW_RECIPE) == ["select_model", "text", "video"]


# ------------------------------------------------------------- validate

DONE_SIGNALS = {"stable_text", "selector_appear", "selector_disappear", "copy_button"}
COPY_SCOPES = {"after", "inside", "page"}


def _errs(recipe):
    return flows.validate_flows(recipe, DONE_SIGNALS, COPY_SCOPES)


def test_a_recipe_without_flows_reports_nothing():
    assert _errs(FLAT_CHAT) == []


def test_a_well_formed_flows_block_reports_nothing():
    assert _errs(FLOW_RECIPE) == []


def test_unknown_flow_name_is_rejected():
    recipe = {**FLOW_RECIPE, "flows": {**FLOW_RECIPE["flows"], "audio": {}}}
    assert any("flows.audio" in e for e in _errs(recipe))


def test_malformed_action_is_rejected():
    recipe = {**FLOW_RECIPE, "flows": {**FLOW_RECIPE["flows"], "text": {"action": "press Enter"}}}
    assert any("flows.text.action" in e for e in _errs(recipe))


def test_media_flow_without_any_way_to_find_the_result_is_rejected():
    recipe = {**FLOW_RECIPE,
              "flows": {**FLOW_RECIPE["flows"],
                        "image": {"response": {"done_signal": {"type": "stable_text"}}}}}
    assert any("flows.image.response.media_selector" in e for e in _errs(recipe))


def test_text_flow_without_a_reply_selector_is_rejected():
    recipe = {"slug": "s", "url": "https://s.tld", "models": [{"id": "m"}],
              "flows": {"text": {"prompt": {"input_selector": "#b"}, "response": {}}}}
    assert any("flows.text.response.last_message_selector" in e for e in _errs(recipe))
