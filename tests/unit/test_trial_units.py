"""Phần thuần logic của `chat2api.trial` + schema của lượt chạy thử."""

from chat2api.schemas import RecipeTestRequest
from chat2api.trial import _looks_answered, _model_of, _split_actions

BASE_SPEC = {
    "slug": "x", "url": "https://x.test/",
    "prompt": {"input_selector": "#p", "submit": "Enter"},
    "response": {"last_message_selector": ".m",
                 "done_signal": {"type": "stable_text"}},
    "models": [{"id": "m1"}],
}


class TestSplitActions:
    def test_splits_a_chain_into_verb_and_selector(self):
        assert _split_actions("click:#menu;select:#model") == [
            ("click", "#menu"), ("select", "#model")]

    def test_tolerates_spacing_and_empty_segments(self):
        assert _split_actions(" click: #menu ; ; select:#m ;") == [
            ("click", "#menu"), ("select", "#m")]

    def test_drops_segments_without_a_selector(self):
        # `_exec_action_steps` bỏ qua các mẩu này, bảng báo cáo phải bỏ y hệt —
        # nếu không nó liệt kê một bước mà production không bao giờ chạy.
        assert _split_actions("click:;nocolon;click:#ok") == [("click", "#ok")]

    def test_empty_and_none_give_no_steps(self):
        assert _split_actions("") == []
        assert _split_actions(None) == []

    def test_selector_containing_a_colon_stays_intact(self):
        # Pseudo-class là selector hợp lệ và rất hay gặp; tách sai ở đây thì
        # bảng báo cáo sẽ báo hỏng một selector vốn chạy tốt.
        assert _split_actions("click:button:nth-child(2)") == [
            ("click", "button:nth-child(2)")]


class TestLooksAnswered:
    def test_reply_differing_from_the_prompt_counts_as_answered(self):
        assert _looks_answered("OK", "Reply with exactly: OK") is True

    def test_echoing_the_prompt_back_is_not_an_answer(self):
        # Ô nhập không bị xoá sau khi gửi thì `last_message_selector` rất dễ
        # đọc trúng chính prompt vừa gõ — đó là recipe sai, không phải đỗ.
        assert _looks_answered("Reply with exactly: OK", "Reply with exactly: OK") is False

    def test_case_and_padding_do_not_hide_an_echo(self):
        assert _looks_answered("  reply WITH exactly: ok  ", "Reply with exactly: OK") is False

    def test_empty_reply_is_not_an_answer(self):
        assert _looks_answered("", "hỏi gì đó") is False


class TestModelOf:
    def test_picks_a_model_that_can_do_the_flow(self):
        recipe = {"models": [{"id": "chat-only"},
                             {"id": "drawer", "capability": "image"}]}
        assert _model_of(recipe, "image")["id"] == "drawer"

    def test_falls_back_to_the_first_model(self):
        recipe = {"models": [{"id": "a"}, {"id": "b"}]}
        assert _model_of(recipe, "text")["id"] == "a"

    def test_no_models_gives_an_empty_dict(self):
        assert _model_of({"models": []}, "text") == {}


class TestTrialOptionsStayOutOfTheRecipe:
    """Tuỳ chọn lượt thử không được lọt vào dict recipe.

    `to_recipe_dict` kế thừa `model_dump`, nên mọi field thêm vào request đều
    tự động chảy vào recipe đem đi validate — tức là validate một thứ khác với
    thứ sẽ ghi xuống đĩa.
    """

    def test_trial_only_keys_are_stripped(self):
        body = RecipeTestRequest(**BASE_SPEC, headed=True, flow="image",
                                 test_prompt="vẽ con mèo")
        data = body.to_recipe_dict()
        assert "headed" not in data
        assert "flow" not in data
        assert "test_prompt" not in data

    def test_the_recipe_itself_survives_intact(self):
        body = RecipeTestRequest(**BASE_SPEC, flow="video")
        data = body.to_recipe_dict()
        assert data["slug"] == "x"
        assert data["prompt"]["input_selector"] == "#p"
        assert data["models"] == [{"id": "m1"}]

    def test_recipe_prompt_block_is_not_shadowed_by_the_trial_prompt(self):
        # `test_prompt` cố tình không tên là `prompt`: trùng tên sẽ đè khối cấu
        # hình ô nhập của recipe bằng một chuỗi.
        body = RecipeTestRequest(**BASE_SPEC, test_prompt="xin chào")
        assert body.test_prompt == "xin chào"
        assert body.prompt.input_selector == "#p"

    def test_defaults_keep_the_old_behaviour(self):
        body = RecipeTestRequest(**BASE_SPEC)
        assert body.flow == "text"
        assert body.headed is False
        assert body.test_prompt is None
