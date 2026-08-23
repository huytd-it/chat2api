import json
import urllib.parse

from chat2api.providers.gemini_native import (
    build_payload,
    clean_text,
    extract_response_text,
    make_sapisidhash,
)


def inner_line(texts):
    inner = [None] * 5
    inner[4] = [[None, texts]]
    return json.dumps([["wrb.fr", None, json.dumps(inner)]]) + "x" * 250


def test_extract_picks_longest_text():
    raw = ")]}'\n\n" + inner_line(["hello", "hello world"]) + "\n" + inner_line(["tiny"])
    assert extract_response_text(raw) == "hello world"


def test_extract_raises_on_bard_error():
    try:
        extract_response_text("BardErrorInfo [123]")
        assert False
    except RuntimeError as e:
        assert "123" in str(e)


def test_build_payload_contains_model_and_think():
    body = build_payload("hi", model_id=7, think_mode=2)
    params = urllib.parse.parse_qs(body)
    outer = json.loads(params["f.req"][0])
    inner = json.loads(outer[1])
    assert inner[79] == 7
    assert inner[17] == [[2]]
    assert inner[0][0] == "hi"


def test_sapisidhash_shape():
    h = make_sapisidhash("abc")
    assert h.startswith("SAPISIDHASH ") and "_" in h


def test_clean_text_strips_artifacts():
    txt = "before\nhttp://googleusercontent.com/card_content/0\nafter"
    assert clean_text(txt) == "before\nafter"
