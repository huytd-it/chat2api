import base64

import pytest

from chat2api import attachments
from chat2api.errors import OpenAIError
from chat2api.prompt import flatten_messages
from chat2api.providers.browser_recipe import validate_recipe
from chat2api.schemas import ChatRequest

PNG = base64.b64encode(b"\x89PNG fake").decode()


def _request(content):
    return ChatRequest.model_validate(
        {"model": "a/b", "messages": [{"role": "user", "content": content}]})


def test_string_content_has_no_attachments_key():
    assert _request("hi").as_list() == [{"role": "user", "content": "hi"}]


def test_image_and_file_parts_are_split_from_text():
    msgs = _request([
        {"type": "text", "text": "mô tả"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG}"}},
        {"type": "file", "file": {"filename": "a.txt", "file_data": base64.b64encode(b"1,2").decode()}},
    ]).as_list()
    assert msgs[0]["content"] == "mô tả"
    image, doc = msgs[0]["attachments"]
    assert (image.name, image.mime, image.kind, image.data) == (
        "attachment-1.png", "image/png", "image", b"\x89PNG fake")
    assert (doc.name, doc.mime, doc.kind, doc.data) == ("a.txt", "text/plain", "file", b"1,2")
    assert image.payload() == {"name": "attachment-1.png", "mimeType": "image/png",
                               "buffer": b"\x89PNG fake"}


def test_remote_url_is_kept_for_later_download():
    item = _request([{"type": "image_url", "image_url": "https://x.test/img/cat.jpg?w=1"}]
                    ).as_list()[0]["attachments"][0]
    assert (item.name, item.mime, item.url, item.data) == (
        "cat.jpg", "image/jpeg", "https://x.test/img/cat.jpg?w=1", b"")


def test_filename_cannot_escape_a_directory():
    assert attachments.safe_name("..\\..\\evil/../x.txt") == "_.._evil_.._x.txt"
    assert attachments.safe_name("", "image/png", 2) == "attachment-3.png"


@pytest.mark.parametrize("content, fragment", [
    ([{"type": "audio", "audio": {}}], "không được hỗ trợ"),
    ([{"type": "image_url", "image_url": {"url": "data:image/png;base64,@@@"}}], "base64"),
    ([{"type": "file", "file": {"file_id": "file-1"}}], "file_id"),
    ([{"type": "image_url", "image_url": {"url": ""}}], "thiếu dữ liệu"),
    (42, "chuỗi hoặc mảng"),
])
def test_bad_parts_are_rejected_as_400(content, fragment):
    with pytest.raises(OpenAIError) as caught:
        attachments.split_content(content)
    assert caught.value.status == 400 and caught.value.code == "invalid_attachment"
    assert fragment in caught.value.message


def test_size_and_count_limits(monkeypatch):
    monkeypatch.setenv("ATTACHMENT_MAX_COUNT", "1")
    part = {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG}"}}
    with pytest.raises(OpenAIError) as caught:
        _request([part, part]).as_list()
    assert "tối đa 1" in caught.value.message
    monkeypatch.setattr(attachments, "max_bytes", lambda: 4)
    with pytest.raises(OpenAIError) as caught:
        _request([part]).as_list()
    assert "vượt" in caught.value.message


def test_flatten_keeps_a_turn_that_only_has_files():
    msgs = _request([{"type": "image_url",
                      "image_url": {"url": f"data:image/png;base64,{PNG}", "name": "cat.png"}}]
                    ).as_list()
    assert flatten_messages(msgs) == "User: [đính kèm: cat.png]"


def test_collect_takes_user_files_in_order():
    a, b = attachments.Attachment("a", "x/y", b"1"), attachments.Attachment("b", "x/y", b"2")
    msgs = [{"role": "user", "content": "", "attachments": [a]},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "", "attachments": [b]}]
    assert attachments.collect(msgs) == [a, b]


def test_openai_messages_rebuilds_parts():
    image = attachments.Attachment("c.png", "image/png", b"\x89PNG fake")
    doc = attachments.Attachment("a.pdf", "application/pdf", b"%PDF")
    out = attachments.openai_messages([
        {"role": "system", "content": "s"},
        {"role": "user", "content": "q", "attachments": [image, doc]},
    ])
    assert out[0] == {"role": "system", "content": "s"}
    assert out[1]["content"] == [
        {"type": "text", "text": "q"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG}"}},
        {"type": "file", "file": {"filename": "a.pdf",
                                  "file_data": "data:application/pdf;base64,JVBERg=="}},
    ]


def test_recipe_validates_attach_fields():
    recipe = {
        "slug": "s", "url": "https://x.test",
        "prompt": {"input_selector": "#p", "attach_selector": 5, "attach_wait_ms": -1},
        "response": {"last_message_selector": ".m", "done_signal": {"type": "stable_text"}},
        "models": [{"id": "m"}],
    }
    errs = validate_recipe(recipe)
    assert "invalid field: prompt.attach_selector (phải là string)" in errs
    assert "invalid field: prompt.attach_wait_ms (số nguyên >= 0)" in errs
    recipe["prompt"].update(attach_selector="input[type=file]", attach_wait_ms=500)
    assert validate_recipe(recipe) == []
